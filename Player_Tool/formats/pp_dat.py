"""pp.dat 加密容器的验证与 RTON 加解密。"""

from __future__ import annotations

from config.settings import SETTINGS
from core.rton_encryption import decrypt_rton, derive_key, encrypt_rton
from domain.errors import RtonFormatError

HEADER = b"\x10\x00"


def validate_dat(data: bytes) -> int:
    if len(data) < len(HEADER):
        raise RtonFormatError("pp.dat 太短")
    if not data.startswith(HEADER):
        raise RtonFormatError(
            f"pp.dat 头错误：expected={HEADER.hex(' ')}, actual={data[:2].hex(' ')}"
        )
    cipher_length = len(data) - len(HEADER)
    block_size = SETTINGS.rton.block_size
    if cipher_length <= 0 or cipher_length % block_size:
        raise RtonFormatError(
            "pp.dat 密文长度不符合分组大小。\n"
            f"cipher size={cipher_length}, block size={block_size}, "
            f"remainder={cipher_length % block_size}"
        )
    return cipher_length


def decrypt_pp(data: bytes, source: str = "pp.dat") -> bytes:
    validate_dat(data)
    return decrypt_rton(data, source=source, seed=SETTINGS.rton.encryption_seed)


def encrypt_pp(data: bytes, source: str = "pp.bin") -> bytes:
    return encrypt_rton(data, source=source, seed=SETTINGS.rton.encryption_seed)


def key_description() -> tuple[str, str]:
    key_text, _, iv = derive_key(SETTINGS.rton.encryption_seed)
    return key_text, iv.decode("ascii")
