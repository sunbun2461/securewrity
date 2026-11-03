"""User accounts and their protection (none / password / passphrase / seed phrase).

Layout on disk (default root: ~/.local/share/folio):

    users/<username>/account.json   public metadata + wrapped keys (no secrets)
    users/<username>/data.db        plain SQLite        (unprotected accounts)
    users/<username>/data.folio     AES-GCM encrypted   (protected accounts)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import crypto
from .seed import normalize_phrase, validate_seed_phrase
from .storage import Store

GUEST = "Guest"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$")
CRED_TYPES = ("password", "passphrase", "seed")


def default_root() -> Path:
    base = os.environ.get("FOLIO_HOME")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(xdg) / "folio"


class AccountError(Exception):
    pass


@dataclass
class Account:
    directory: Path
    id: str
    username: str
    created: float
    slots: list[dict] = field(default_factory=list)
    is_guest: bool = False

    @property
    def encrypted(self) -> bool:
        return bool(self.slots)

    def slot_types(self) -> list[str]:
        return [s["type"] for s in self.slots]

    def to_json(self) -> dict:
        return {
            "format": 1, "id": self.id, "username": self.username,
            "created": self.created, "is_guest": self.is_guest, "keyslots": self.slots,
        }

    def save(self) -> None:
        path = self.directory / "account.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def aad(self) -> bytes:
        return b"folio-keyslot:" + self.id.encode()


def _prepare_secret(cred_type: str, secret: str) -> str:
    if cred_type == "seed":
        return normalize_phrase(secret)
    return secret


def validate_credential(cred_type: str, secret: str) -> str | None:
    """Return an error message, or None if acceptable."""
    if cred_type not in CRED_TYPES:
        return f"Unknown credential type {cred_type}"
    if cred_type == "password" and len(secret) < 8:
        return "Password must be at least 8 characters."
    if cred_type == "passphrase":
        words = [w for w in re.split(r"[\s\-_.]+", secret) if w]
        if len(words) < 4 or len(secret) < 16:
            return "A passphrase should be at least 4 words (16+ characters)."
    if cred_type == "seed":
        ok, msg = validate_seed_phrase(secret)
        if not ok:
            return msg
    return None


class AccountManager:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or default_root())
        self.users_dir = self.root / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    # --- listing -----------------------------------------------------------
    def list_accounts(self) -> list[Account]:
        out = []
        for d in sorted(self.users_dir.iterdir()) if self.users_dir.exists() else []:
            f = d / "account.json"
            if not f.is_file():
                continue
            try:
                j = json.loads(f.read_text())
                out.append(Account(d, j["id"], j["username"], j.get("created", 0),
                                   j.get("keyslots", []), j.get("is_guest", False)))
            except (OSError, ValueError, KeyError):
                continue
        out.sort(key=lambda a: (not a.is_guest, a.username.lower()))
        return out

    def get(self, username: str) -> Account | None:
        for a in self.list_accounts():
            if a.username.lower() == username.lower():
                return a
        return None

    def ensure_guest(self) -> Account:
        g = self.get(GUEST)
        if g:
            return g
        acc, store = self.create_account(GUEST, [], _guest=True)
        store.close()
        return acc

    # --- create / open -----------------------------------------------------
    def create_account(self, username: str, credentials: list[tuple[str, str, str]],
                       _guest: bool = False) -> tuple[Account, Store]:
        """credentials: list of (type, secret, label). Empty list = unprotected."""
        username = username.strip()
        if not USERNAME_RE.match(username):
            raise AccountError("Username: 1-32 letters, digits, '.', '_' or '-'.")
        if username.lower() == GUEST.lower() and not _guest:
            raise AccountError("'Guest' is reserved.")
        if self.get(username):
            raise AccountError("That username already exists.")
        for ctype, secret, _ in credentials:
            err = validate_credential(ctype, secret)
            if err:
                raise AccountError(err)
        d = self.users_dir / username
        d.mkdir(mode=0o700)
        acc = Account(d, uuid.uuid4().hex, username, time.time(), [], _guest)
        dek = crypto.new_key() if credentials else None
        for ctype, secret, label in credentials:
            acc.slots.append(self._make_slot(acc, dek, ctype, secret, label))
        acc.save()
        store = Store(d, acc.id, dek).open()
        store.save()
        return acc, store

    def _make_slot(self, acc: Account, dek: bytes, ctype: str, secret: str, label: str) -> dict:
        slot = crypto.wrap_key(dek, _prepare_secret(ctype, secret), acc.aad())
        slot.update({"id": uuid.uuid4().hex[:8], "type": ctype,
                     "label": label or ctype.capitalize(), "created": time.time()})
        return slot

    def open_unprotected(self, acc: Account) -> Store:
        if acc.encrypted:
            raise AccountError("This account is protected.")
        return Store(acc.directory, acc.id, None).open()

    def unlock(self, acc: Account, secret: str) -> Store:
        """Try the secret against every key slot. Raises AccountError if none match."""
        if not acc.encrypted:
            return self.open_unprotected(acc)
        dek = self._try_slots(acc, secret)
        if dek is None:
            raise AccountError("Incorrect password, passphrase or seed phrase.")
        return Store(acc.directory, acc.id, dek).open()

    def _try_slots(self, acc: Account, secret: str) -> bytes | None:
        for slot in acc.slots:
            try:
                return crypto.unwrap_key(slot, _prepare_secret(slot["type"], secret), acc.aad())
            except crypto.DecryptionError:
                continue
        return None

    def verify(self, acc: Account, secret: str) -> bool:
        """Check a credential without opening the store (for sensitive changes)."""
        return self._try_slots(acc, secret) is not None

    # --- protection management --------------------------------------------
    def enable_encryption(self, acc: Account, store: Store,
                          credentials: list[tuple[str, str, str]]) -> None:
        if acc.encrypted:
            raise AccountError("Already encrypted.")
        if not credentials:
            raise AccountError("Choose at least one credential.")
        for ctype, secret, _ in credentials:
            err = validate_credential(ctype, secret)
            if err:
                raise AccountError(err)
        dek = crypto.new_key()
        acc.slots = [self._make_slot(acc, dek, c, s, l) for c, s, l in credentials]
        store.convert_to_encrypted(dek)
        acc.save()

    def add_credential(self, acc: Account, store: Store, ctype: str, secret: str, label: str = "") -> dict:
        if not store.encrypted:
            raise AccountError("Account is not encrypted.")
        err = validate_credential(ctype, secret)
        if err:
            raise AccountError(err)
        slot = self._make_slot(acc, store.dek, ctype, secret, label)
        acc.slots.append(slot)
        acc.save()
        return slot

    def remove_credential(self, acc: Account, slot_id: str) -> None:
        if len(acc.slots) <= 1:
            raise AccountError("Can't remove the last credential — remove encryption instead.")
        acc.slots = [s for s in acc.slots if s["id"] != slot_id]
        acc.save()

    def disable_encryption(self, acc: Account, store: Store) -> None:
        store.convert_to_plain()
        acc.slots = []
        acc.save()

    def delete_account(self, acc: Account) -> None:
        shutil.rmtree(acc.directory)
