"""RSB/RSG 二进制容器共用的底层辅助函数。"""

from struct import unpack

RSB_MAGIC = b"1bsr"
RSG_MAGIC = b"pgsr"


def matches(value: str, prefixes: tuple[str, ...], suffixes: tuple[str, ...]) -> bool:
    """根据可选前缀与后缀过滤资源名称。"""
    lowered = value.lower()
    return (not prefixes or lowered.startswith(tuple(prefix.lower() for prefix in prefixes))) and (
        not suffixes or lowered.endswith(tuple(suffix.lower() for suffix in suffixes))
    )


def read_u32(file) -> int:
    """从当前位置读取一个小端 uint32。"""
    return unpack("<I", file.read(4))[0]


def pad4096(length: int) -> bytes:
    """返回把当前长度补齐到 4096 字节边界所需的零字节。"""
    return b"\0" * ((4096 - length) & 4095)
