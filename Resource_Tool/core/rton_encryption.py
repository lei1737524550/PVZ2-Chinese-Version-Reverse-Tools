from __future__ import annotations

import hashlib

from .conversion_settings import RTON_BLOCK_SIZE, RTON_ENCRYPTION_SEED
from .rijndael_cipher import RijndaelCBC

RTON_MAGIC = b"RTON"
ENCRYPTED_MAGIC = b"\x10\x00"
BLOCK_SIZE = RTON_BLOCK_SIZE


def derive_key(seed: str = RTON_ENCRYPTION_SEED) -> tuple[str, bytes, bytes]:
    key_text = hashlib.md5(seed.encode("utf-8")).hexdigest()
    key = key_text.encode("ascii")
    iv = key[4:28]
    if len(key) != 32 or len(iv) != BLOCK_SIZE:
        raise ValueError("invalid RTON key/IV length")
    return key_text, key, iv


def _cipher(seed: str = RTON_ENCRYPTION_SEED) -> RijndaelCBC:
    _, key, _ = derive_key(seed)
    return RijndaelCBC(key, BLOCK_SIZE)


def decrypt_rton(data: bytes, source: str = "RTON", seed: str = RTON_ENCRYPTION_SEED) -> bytes:
    if data.startswith(RTON_MAGIC):
        return data
    if not data.startswith(ENCRYPTED_MAGIC):
        raise ValueError(f"{source}: expected 10 00 or RTON header")
    ciphertext = data[2:]
    if not ciphertext or len(ciphertext) % BLOCK_SIZE:
        raise ValueError(f"{source}: invalid encrypted RTON length {len(ciphertext)}")
    plain = _cipher(seed).decrypt(ciphertext)
    if not plain.startswith(RTON_MAGIC):
        raise ValueError(f"{source}: decrypted data does not start with RTON")
    return plain


def encrypt_rton(data: bytes, source: str = "RTON", seed: str = RTON_ENCRYPTION_SEED) -> bytes:
    if data.startswith(ENCRYPTED_MAGIC):
        return data
    if not data.startswith(RTON_MAGIC):
        raise ValueError(f"{source}: expected RTON header")
    return ENCRYPTED_MAGIC + _cipher(seed).encrypt(data)
