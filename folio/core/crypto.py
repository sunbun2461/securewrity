"""Cryptographic primitives.

Design (envelope encryption):
  * Every encrypted account has one random 256-bit Data Encryption Key (DEK).
  * The whole SQLite database is encrypted with the DEK using AES-256-GCM.
  * The DEK is "wrapped" (encrypted) once per credential — password, passphrase,
    or seed phrase — using a Key Encryption Key derived with scrypt.
  * Changing a password or adding a recovery seed phrase only adds/removes a
    wrapped copy of the DEK; the database itself never needs re-encrypting.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LEN = 32
NONCE_LEN = 12
SALT_LEN = 16

# scrypt cost: N=2^17, r=8 -> ~128 MiB RAM, roughly 0.3-0.8 s on a laptop.
DEFAULT_KDF = {"name": "scrypt", "n": 2 ** 17, "r": 8, "p": 1}


class DecryptionError(Exception):
    """Wrong key/credential, or the data was corrupted or tampered with."""


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def new_key() -> bytes:
    return secrets.token_bytes(KEY_LEN)


def derive_key(secret: str, salt: bytes, kdf: dict | None = None) -> bytes:
    kdf = kdf or DEFAULT_KDF
    if kdf.get("name") != "scrypt":
        raise ValueError(f"Unsupported KDF: {kdf.get('name')}")
    n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
    return hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=n, r=r, p=p,
        maxmem=256 * 1024 * 1024, dklen=KEY_LEN,
    )


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    nonce = os.urandom(NONCE_LEN)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad or None)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad or None)
    except InvalidTag as e:
        raise DecryptionError("Decryption failed (wrong key or corrupted data)") from e


def wrap_key(dek: bytes, secret: str, aad: bytes, kdf: dict | None = None) -> dict:
    """Encrypt the DEK under a credential. Returns a JSON-safe key slot."""
    kdf = dict(kdf or DEFAULT_KDF)
    salt = os.urandom(SALT_LEN)
    kek = derive_key(secret, salt, kdf)
    nonce, ct = encrypt(kek, dek, aad)
    return {"kdf": kdf, "salt": b64e(salt), "nonce": b64e(nonce), "wrapped": b64e(ct)}


def unwrap_key(slot: dict, secret: str, aad: bytes) -> bytes:
    kek = derive_key(secret, b64d(slot["salt"]), slot["kdf"])
    return decrypt(kek, b64d(slot["nonce"]), b64d(slot["wrapped"]), aad)
