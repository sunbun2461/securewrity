"""SQLite storage, plain or encrypted.

Plain accounts use a normal on-disk SQLite file (data.db).

Encrypted accounts keep the database *only in memory* while unlocked. On save
the in-memory database is serialized, encrypted with AES-256-GCM, and written
atomically to data.securewrity. No plaintext ever touches the disk.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

from . import crypto

MAGIC = b"SECUREWRITYv1\n"


def _fsync_dir(directory: Path) -> None:
    """Make renames inside a directory durable (no-op where unsupported)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace `path` with `data` so that a crash at any moment leaves either the
    old file or the new one in place, never neither:

    1. write the new data to <path>.tmp and fsync it
    2. point <path>.bak at the current file (hard link, or copy), path untouched
    3. atomically rename <path>.tmp over <path>
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        bak_tmp = path.with_suffix(path.suffix + ".bak.tmp")
        try:
            bak_tmp.unlink(missing_ok=True)
            try:
                os.link(path, bak_tmp)          # instant, path keeps existing
            except OSError:
                shutil.copyfile(path, bak_tmp)  # filesystems without hard links
            os.replace(bak_tmp, bak)
        except OSError:
            pass  # a missing backup must never block saving
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _shred(path: Path) -> None:
    """Best-effort overwrite + delete. (Not guaranteed on SSDs/COW filesystems.)"""
    for p in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if p.exists():
            try:
                size = p.stat().st_size
                with open(p, "r+b") as f:
                    f.write(b"\0" * size)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass
            p.unlink(missing_ok=True)


class Store:
    """Owns the SQLite connection for one unlocked account."""

    def __init__(self, directory: Path, account_id: str, dek: bytes | None):
        self.directory = Path(directory)
        self.account_id = account_id
        self.dek = dek
        self.conn: sqlite3.Connection | None = None
        self.dirty = False
        self.recovered_from: str | None = None  # set if the main file was missing or damaged

    # --- paths -------------------------------------------------------------
    @property
    def plain_path(self) -> Path:
        return self.directory / "data.db"

    @property
    def enc_path(self) -> Path:
        return self.directory / "data.securewrity"

    @property
    def encrypted(self) -> bool:
        return self.dek is not None

    def _aad(self) -> bytes:
        return MAGIC + self.account_id.encode()

    def _decrypt_file(self, path: Path) -> bytes:
        blob = path.read_bytes()
        if not blob.startswith(MAGIC):
            raise crypto.DecryptionError(f"{path.name} is not a Securewrity vault file")
        body = blob[len(MAGIC):]
        nonce, ct = body[: crypto.NONCE_LEN], body[crypto.NONCE_LEN:]
        return crypto.decrypt(self.dek, nonce, ct, self._aad())

    def _read_vault(self) -> bytes | None:
        """Decrypt the newest intact copy. The key was already checked against the
        account's key slots, so a file that fails to decrypt is damaged, not locked
        with another key. Order: the main file, a finished-but-not-renamed .tmp
        (crash during save), then the previous version (.bak).
        Returns None only for a brand-new account with no vault files at all."""
        e = self.enc_path
        candidates = [e, e.with_suffix(e.suffix + ".tmp"), e.with_suffix(e.suffix + ".bak")]
        existing = [p for p in candidates if p.exists()]
        if not existing:
            return None
        errors = []
        for p in existing:
            try:
                data = self._decrypt_file(p)
            except (crypto.DecryptionError, OSError, ValueError) as err:
                errors.append(f"{p.name}: {err}")
                continue
            self.recovered_from = None if p == e else p.name
            return data
        raise crypto.DecryptionError("No readable copy of your notes: " + "; ".join(errors))

    # --- open/close --------------------------------------------------------
    def open(self) -> "Store":
        if self.encrypted:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            plaintext = self._read_vault()
            if plaintext is not None:
                conn.deserialize(plaintext)
            else:
                # a brand-new empty in-memory DB has no pages and can't be serialized
                conn.execute("CREATE TABLE IF NOT EXISTS securewrity_meta (key TEXT PRIMARY KEY, value TEXT)")
        else:
            conn = sqlite3.connect(self.plain_path, check_same_thread=False)
            os.chmod(self.plain_path, 0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self.conn = conn
        return self

    def save(self) -> None:
        if not self.conn:
            return
        self.conn.commit()
        if self.encrypted:
            data = self.conn.serialize()
            nonce, ct = crypto.encrypt(self.dek, data, self._aad())
            _atomic_write(self.enc_path, MAGIC + nonce + ct)
        self.dirty = False

    def close(self) -> None:
        if self.conn:
            self.save()
            self.conn.close()
            self.conn = None
        self.dek = None

    # --- conversions -------------------------------------------------------
    def convert_to_encrypted(self, dek: bytes) -> None:
        assert self.conn and not self.encrypted
        self.conn.commit()
        data = self.conn.serialize()
        self.conn.close()
        mem = sqlite3.connect(":memory:", check_same_thread=False)
        mem.deserialize(data)
        mem.row_factory = sqlite3.Row
        mem.execute("PRAGMA foreign_keys = ON")
        self.conn, self.dek = mem, dek
        self.save()
        _shred(self.plain_path)

    def convert_to_plain(self) -> None:
        assert self.conn and self.encrypted
        self.conn.commit()
        data = self.conn.serialize()
        self.conn.close()
        _atomic_write(self.plain_path, data)
        Path(str(self.plain_path) + ".bak").unlink(missing_ok=True)
        for suffix in ("", ".bak", ".tmp", ".bak.tmp"):
            p = Path(str(self.enc_path) + suffix)
            p.unlink(missing_ok=True)
        self.dek = None
        self.open()
