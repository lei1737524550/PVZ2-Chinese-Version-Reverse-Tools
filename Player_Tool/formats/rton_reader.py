"""将 pp.bin 的 RTON 解码为普通 Python 对象。"""

from __future__ import annotations

import struct

from domain.errors import RtonFormatError

RTONError = RtonFormatError


class RTONReader:
    def __init__(self, data):
        self.data = data
        self.p = 0
        self.ascii_cache = []
        self.utf8_cache = []

    def error(self, message):
        nearby = self.data[self.p:self.p + 16].hex(" ")
        raise RTONError(
            f"{message}\n"
            f"offset = 0x{self.p:x}\n"
            f"next   = {nearby}"
        )

    def read(self, n):
        end = self.p + n
        if end > len(self.data):
            self.error("unexpected EOF")

        value = self.data[self.p:end]
        self.p = end
        return value

    def u8(self):
        return self.read(1)[0]

    def unpack(self, fmt):
        return struct.unpack(
            fmt,
            self.read(struct.calcsize(fmt))
        )[0]

    def uvar(self):
        result = 0
        shift = 0

        while True:
            b = self.u8()
            result |= (b & 0x7F) << shift

            if not (b & 0x80):
                return result

            shift += 7
            if shift > 70:
                self.error("invalid variable integer")

    def svar(self):
        value = self.uvar()
        return -((value + 1) // 2) if value & 1 else value // 2

    def text(self, n):
        raw = self.read(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    def utf8_body(self):
        self.uvar()          # Unicode 字符数量
        return self.text(self.uvar())

    def cached_ascii(self):
        s = self.text(self.uvar())
        self.ascii_cache.append(s)
        return s

    def cached_utf8(self):
        s = self.utf8_body()
        self.utf8_cache.append(s)
        return s

    def rtid(self):
        subtype = self.u8()

        if subtype == 0:
            return "RTID()"

        if subtype == 2:
            name = self.utf8_body()
            u2 = self.uvar()
            u1 = self.uvar()
            ident = self.unpack("<I")
            return f"RTID({u1}.{u2}.{ident:08x}@{name})"

        if subtype == 3:
            first = self.utf8_body()
            second = self.utf8_body()
            return f"RTID({second}@{first})"

        self.error(f"unknown RTID subtype 0x{subtype:02x}")

    def array(self):
        marker = self.u8()

        if marker != 0xFD:
            self.error(
                f"array missing FD marker, got 0x{marker:02x}"
            )

        count = self.uvar()
        values = [self.value() for _ in range(count)]

        end = self.u8()
        if end != 0xFE:
            self.error(
                f"array missing FE marker, got 0x{end:02x}"
            )

        return values

    def object(self):
        result = {}

        while True:
            if self.p >= len(self.data):
                self.error("unterminated object")

            if self.data[self.p] == 0xFF:
                self.p += 1
                return result

            key = self.value()

            if not isinstance(key, str):
                self.error(f"object key is not string: {key!r}")

            result[key] = self.value()

    def value(self):
        pos = self.p
        t = self.u8()

        # 布尔值
        if t == 0x00: return False
        if t == 0x01: return True

        # 8 位整数
        if t == 0x08: return self.unpack("<b")
        if t == 0x09: return 0
        if t == 0x0A: return self.unpack("<B")
        if t == 0x0B: return 0

        # 16 位整数
        if t == 0x10: return self.unpack("<h")
        if t == 0x11: return 0
        if t == 0x12: return self.unpack("<H")
        if t == 0x13: return 0

        # 32 位整数
        if t == 0x20: return self.unpack("<i")
        if t == 0x21: return 0
        if t == 0x22: return self.unpack("<f")
        if t == 0x23: return 0.0
        if t in (0x24, 0x28): return self.uvar()
        if t in (0x25, 0x29): return self.svar()
        if t == 0x26: return self.unpack("<I")
        if t == 0x27: return 0

        # 64 位整数
        if t == 0x40: return self.unpack("<q")
        if t == 0x41: return 0
        if t == 0x42: return self.unpack("<d")
        if t == 0x43: return 0.0
        if t in (0x44, 0x48): return self.uvar()
        if t in (0x45, 0x49): return self.svar()
        if t == 0x46: return self.unpack("<Q")
        if t == 0x47: return 0

        # 字符串 / 对象
        if t == 0x81: return self.text(self.uvar())
        if t == 0x82: return self.utf8_body()
        if t == 0x83: return self.rtid()
        if t == 0x85: return self.object()
        if t == 0x86: return self.array()

        # 缓存的 ASCII 字符串
        if t == 0x90:
            return self.cached_ascii()

        if t == 0x91:
            idx = self.uvar()
            try:
                return self.ascii_cache[idx]
            except IndexError:
                self.error(f"bad ASCII cache index {idx}")

        # 缓存的 UTF-8 字符串
        if t == 0x92:
            return self.cached_utf8()

        if t == 0x93:
            idx = self.uvar()
            try:
                return self.utf8_cache[idx]
            except IndexError:
                self.error(f"bad UTF8 cache index {idx}")

        self.p = pos
        self.error(f"unknown type 0x{t:02x}")

    def document(self):
        if self.read(4) != b"RTON":
            self.error("not an RTON file")

        version = self.unpack("<I")
        root = self.object()

        if self.read(4) != b"DONE":
            self.error("missing DONE footer")

        # pp.bin 已去掉 00 填充；DONE 标记后不应还有有效数据。
        if self.p != len(self.data):
            self.error(
                f"unexpected trailing data: {len(self.data) - self.p} bytes"
            )

        return {
            "_rton_version": version,
            **root,
        }


def decode_rton_document(data: bytes) -> dict:
    """解析一个完整 RTON 文档。"""
    return RTONReader(data).document()
