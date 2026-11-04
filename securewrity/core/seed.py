"""Seed phrases (BIP39-compatible) and generated passphrases."""
from __future__ import annotations

import hashlib
import secrets
from functools import lru_cache
from pathlib import Path

WORDLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "bip39_english.txt"


@lru_cache(maxsize=1)
def wordlist() -> list[str]:
    words = WORDLIST_PATH.read_text(encoding="utf-8").split()
    if len(words) != 2048:
        raise RuntimeError("BIP39 wordlist is damaged")
    return words


def normalize_phrase(text: str) -> str:
    return " ".join(text.lower().split())


def generate_seed_phrase(num_words: int = 12) -> str:
    """Generate a BIP39 mnemonic (12 or 24 words) with a valid checksum."""
    if num_words not in (12, 15, 18, 21, 24):
        raise ValueError("num_words must be 12, 15, 18, 21 or 24")
    ent_bits = num_words * 11 * 32 // 33
    entropy = secrets.token_bytes(ent_bits // 8)
    cs_bits = ent_bits // 32
    h = hashlib.sha256(entropy).digest()
    bits = int.from_bytes(entropy, "big") << cs_bits | (h[0] >> (8 - cs_bits))
    total = ent_bits + cs_bits
    words = wordlist()
    return " ".join(words[(bits >> (total - 11 * (i + 1))) & 0x7FF] for i in range(num_words))


def validate_seed_phrase(phrase: str) -> tuple[bool, str]:
    """Check word count, that every word is in the list, and the checksum."""
    parts = normalize_phrase(phrase).split()
    if len(parts) not in (12, 15, 18, 21, 24):
        return False, f"Expected 12 or 24 words, got {len(parts)}."
    index = {w: i for i, w in enumerate(wordlist())}
    bad = [w for w in parts if w not in index]
    if bad:
        return False, f"Unknown word(s): {', '.join(bad[:5])}"
    total = len(parts) * 11
    cs_bits = total // 33
    ent_bits = total - cs_bits
    bits = 0
    for w in parts:
        bits = (bits << 11) | index[w]
    entropy = (bits >> cs_bits).to_bytes(ent_bits // 8, "big")
    checksum = bits & ((1 << cs_bits) - 1)
    if hashlib.sha256(entropy).digest()[0] >> (8 - cs_bits) != checksum:
        return False, "Checksum mismatch — check the word order and spelling."
    return True, "OK"


def generate_passphrase(num_words: int = 6, sep: str = "-") -> str:
    """Diceware-style passphrase from the 2048-word list (11 bits per word)."""
    words = wordlist()
    return sep.join(secrets.choice(words) for _ in range(num_words))


def password_strength(pw: str) -> tuple[int, str]:
    """Rough 0-4 score with a label. Not a guarantee, just guidance."""
    if not pw:
        return 0, ""
    pool = 0
    if any(c.islower() for c in pw): pool += 26
    if any(c.isupper() for c in pw): pool += 26
    if any(c.isdigit() for c in pw): pool += 10
    if any(not c.isalnum() for c in pw): pool += 33
    import math
    bits = len(pw) * math.log2(max(pool, 2))
    words = len([w for w in pw.replace("-", " ").split() if w])
    if words >= 4:
        bits = max(bits, words * 11)
    for limit, score, label in ((28, 0, "Very weak"), (40, 1, "Weak"), (60, 2, "Fair"), (80, 3, "Strong")):
        if bits < limit:
            return score, label
    return 4, "Very strong"
