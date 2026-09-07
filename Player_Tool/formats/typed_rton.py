"""保留原始 RTON 类型信息的读取、校验与编码。"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

from domain.errors import RtonFormatError

RTONError = RtonFormatError


@dataclass(slots=True)
class Node:
    """一个带原始 RTON 类型信息的领域节点。"""

    kind: str
    value: Any = None
    tag: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def encode_uvar(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise RTONError(f"uvar 需要整数，实际为 {value!r}")

    if value < 0:
        raise RTONError(f"uvar 不能编码负数: {value}")

    out = bytearray()

    while True:
        b = value & 0x7F
        value >>= 7

        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def zigzag_encode(value):
    if value >= 0:
        return value * 2

    return (-value * 2) - 1


def encode_svar(value):
    return encode_uvar(zigzag_encode(value))


class TypedRTONReader:
    def __init__(self, data):
        self.data = data
        self.p = 0
        self.ascii_cache = []
        self.utf8_cache = []

    def fail(self, msg):
        nearby = self.data[self.p:self.p + 16].hex(" ")

        raise RTONError(
            f"{msg}\n"
            f"offset = 0x{self.p:x}\n"
            f"next   = {nearby}"
        )

    def read(self, n):
        if self.p + n > len(self.data):
            self.fail("unexpected EOF")

        b = self.data[self.p:self.p + n]
        self.p += n
        return b

    def u8(self):
        return self.read(1)[0]

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))[0]

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
                self.fail("invalid variable integer")

    def svar(self):
        u = self.uvar()
        return -((u + 1) // 2) if u & 1 else u // 2

    def text_bytes(self, n):
        raw = self.read(n)

        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    def utf8_body(self):
        chars = self.uvar()
        nbytes = self.uvar()
        text = self.text_bytes(nbytes)
        return text, chars, nbytes

    def read_rtid(self):
        subtype = self.u8()

        if subtype == 0:
            return Node(
                "rtid",
                "RTID()",
                tag=0x83,
                meta={"subtype": 0},
            )

        if subtype == 2:
            name, _, _ = self.utf8_body()
            u2 = self.uvar()
            u1 = self.uvar()
            ident = self.unpack("<I")

            return Node(
                "rtid",
                f"RTID({u1}.{u2}.{ident:08x}@{name})",
                tag=0x83,
                meta={
                    "subtype": 2,
                    "name": name,
                    "u2": u2,
                    "u1": u1,
                    "ident": ident,
                },
            )

        if subtype == 3:
            first, _, _ = self.utf8_body()
            second, _, _ = self.utf8_body()

            return Node(
                "rtid",
                f"RTID({second}@{first})",
                tag=0x83,
                meta={
                    "subtype": 3,
                    "first": first,
                    "second": second,
                },
            )

        self.fail(f"unknown RTID subtype 0x{subtype:02x}")

    def read_array(self):
        marker = self.u8()

        if marker != 0xFD:
            self.fail(
                f"array missing FD marker, got 0x{marker:02x}"
            )

        count = self.uvar()
        items = [self.value() for _ in range(count)]

        end = self.u8()

        if end != 0xFE:
            self.fail(
                f"array missing FE marker, got 0x{end:02x}"
            )

        return Node("array", items, tag=0x86)

    def read_object(self, *, root=False):
        pairs = []

        while True:
            if self.p >= len(self.data):
                self.fail("unterminated object")

            if self.data[self.p] == 0xFF:
                self.p += 1

                return Node(
                    "object",
                    pairs,
                    tag=None if root else 0x85,
                    meta={"root": root},
                )

            key_node = self.value()
            key = node_to_value(key_node)

            if not isinstance(key, str):
                self.fail(
                    f"object key is not string: {key!r}"
                )

            value_node = self.value()
            pairs.append((key, value_node))

    def value(self):
        pos = self.p
        t = self.u8()

        # 布尔值
        if t == 0x00:
            return Node("bool", False, tag=t)

        if t == 0x01:
            return Node("bool", True, tag=t)

        # 8 位整数
        if t == 0x08:
            return Node("int", self.unpack("<b"), tag=t)

        if t == 0x09:
            return Node("int", 0, tag=t)

        if t == 0x0A:
            return Node("int", self.unpack("<B"), tag=t)

        if t == 0x0B:
            return Node("int", 0, tag=t)

        # 16 位整数
        if t == 0x10:
            return Node("int", self.unpack("<h"), tag=t)

        if t == 0x11:
            return Node("int", 0, tag=t)

        if t == 0x12:
            return Node("int", self.unpack("<H"), tag=t)

        if t == 0x13:
            return Node("int", 0, tag=t)

        # 32 位整数
        if t == 0x20:
            return Node("int", self.unpack("<i"), tag=t)

        if t == 0x21:
            return Node("int", 0, tag=t)

        if t == 0x22:
            return Node("float", self.unpack("<f"), tag=t)

        if t == 0x23:
            return Node("float", 0.0, tag=t)

        if t in (0x24, 0x28):
            return Node("int", self.uvar(), tag=t)

        if t in (0x25, 0x29):
            return Node("int", self.svar(), tag=t)

        if t == 0x26:
            return Node("int", self.unpack("<I"), tag=t)

        if t == 0x27:
            return Node("int", 0, tag=t)

        # 64 位整数
        if t == 0x40:
            return Node("int", self.unpack("<q"), tag=t)

        if t == 0x41:
            return Node("int", 0, tag=t)

        if t == 0x42:
            return Node("float", self.unpack("<d"), tag=t)

        if t == 0x43:
            return Node("float", 0.0, tag=t)

        if t in (0x44, 0x48):
            return Node("int", self.uvar(), tag=t)

        if t in (0x45, 0x49):
            return Node("int", self.svar(), tag=t)

        if t == 0x46:
            return Node("int", self.unpack("<Q"), tag=t)

        if t == 0x47:
            return Node("int", 0, tag=t)

        # 字符串
        if t == 0x81:
            return Node(
                "string",
                self.text_bytes(self.uvar()),
                tag=t,
            )

        if t == 0x82:
            text, _, _ = self.utf8_body()
            return Node("string", text, tag=t)

        # RTID 类型
        if t == 0x83:
            return self.read_rtid()

        # 对象
        if t == 0x85:
            return self.read_object(root=False)

        # 数组
        if t == 0x86:
            return self.read_array()

        # 缓存的 ASCII 字符串 definition
        if t == 0x90:
            n = self.uvar()
            text = self.text_bytes(n)
            self.ascii_cache.append(text)
            return Node("string", text, tag=t)

        # 缓存的 ASCII 字符串 reference
        if t == 0x91:
            index = self.uvar()

            try:
                text = self.ascii_cache[index]
            except IndexError:
                self.fail(f"bad ASCII cache index {index}")

            return Node(
                "string",
                text,
                tag=t,
                meta={"cache_index": index},
            )

        # 缓存的 UTF-8 字符串 definition
        if t == 0x92:
            text, _, _ = self.utf8_body()
            self.utf8_cache.append(text)
            return Node("string", text, tag=t)

        # 缓存的 UTF-8 字符串 reference
        if t == 0x93:
            index = self.uvar()

            try:
                text = self.utf8_cache[index]
            except IndexError:
                self.fail(f"bad UTF8 cache index {index}")

            return Node(
                "string",
                text,
                tag=t,
                meta={"cache_index": index},
            )

        self.p = pos
        self.fail(f"unknown type 0x{t:02x}")

    def document(self):
        if self.read(4) != b"RTON":
            self.fail("not an RTON file")

        version = self.unpack("<I")
        root = self.read_object(root=True)

        if self.read(4) != b"DONE":
            self.fail("missing DONE footer")

        if self.p != len(self.data):
            rest = self.data[self.p:]

            if rest.strip(b"\x00"):
                self.fail("unexpected bytes after DONE")

        return version, root


def node_to_value(node):
    if node.kind == "object":
        return {
            key: node_to_value(value)
            for key, value in node.value
        }

    if node.kind == "array":
        return [
            node_to_value(item)
            for item in node.value
        ]

    return node.value


def clone_template_node(node):
    """复制节点树，使同级元素可以安全地作为类型模板。"""
    if node.kind == "object":
        return Node(
            "object",
            [(k, clone_template_node(v)) for k, v in node.value],
            tag=node.tag,
            meta=dict(node.meta),
        )
    if node.kind == "array":
        return Node(
            "array",
            [clone_template_node(v) for v in node.value],
            tag=node.tag,
            meta=dict(node.meta),
        )
    return Node(node.kind, node.value, tag=node.tag, meta=dict(node.meta))


def array_item_template(node, index):
    """
    已有元素严格沿用各自原始模板。
    新增元素继承最后一个已有元素的 RTON 类型和结构。
    空模板数组由于无法确定元素类型，因此保持保护状态。
    """
    if index < len(node.value):
        return node.value[index]
    if not node.value:
        raise RTONError(
            "无法向原本为空的数组新增元素：没有可用于恢复 RTON 类型的元素模板。"
        )
    return node.value[-1]


def validate_changed(node, changed, path="root"):
    if node.kind == "object":
        if not isinstance(changed, dict):
            raise RTONError(
                f"{path}: 模板是 object，但 changed.json 是 "
                f"{type(changed).__name__}"
            )

        template_keys = [key for key, _ in node.value]
        changed_keys = list(changed.keys())

        missing = [k for k in template_keys if k not in changed]
        extra = [k for k in changed_keys if k not in template_keys]

        if missing:
            raise RTONError(
                f"{path}: changed.json 删除了字段: {missing[:10]}"
            )

        if extra:
            raise RTONError(
                f"{path}: changed.json 新增了字段: {extra[:10]}\n"
                "当前版本只允许修改已有字段的值。"
            )

        for key, child in node.value:
            validate_changed(
                child,
                changed[key],
                f"{path}.{key}",
            )

        return

    if node.kind == "array":
        if not isinstance(changed, list):
            raise RTONError(
                f"{path}: 模板是 array，但 changed.json 是 "
                f"{type(changed).__name__}"
            )

        # 允许数组增删元素。
        # 已有元素沿用各自原始 RTON 类型；新增元素继承最后一个原始元素的类型/结构。
        # 原本为空的数组没有类型模板，因此仍禁止从 0 增长。
        if len(changed) > len(node.value) and not node.value:
            raise RTONError(
                f"{path}: 原数组为空，无法安全推断新增元素的 RTON 类型。"
            )

        for i, new_value in enumerate(changed):
            child = array_item_template(node, i)
            validate_changed(
                child,
                new_value,
                f"{path}[{i}]",
            )

        return

    if node.kind in ("string", "rtid"):
        if not isinstance(changed, str):
            raise RTONError(
                f"{path}: 原值是字符串，changed.json 必须仍是字符串。"
            )
        return

    if node.kind == "bool":
        if not isinstance(changed, bool):
            raise RTONError(
                f"{path}: 原值是 bool，changed.json 必须仍是 bool。"
            )
        return

    if node.kind == "int":
        if not isinstance(changed, int) or isinstance(changed, bool):
            raise RTONError(
                f"{path}: 原值是整数，changed.json 必须仍是整数。"
            )
        return

    if node.kind == "float":
        if (
            not isinstance(changed, (int, float))
            or isinstance(changed, bool)
        ):
            raise RTONError(
                f"{path}: 原值是浮点数，changed.json 必须仍是数字。"
            )
        return

    raise RTONError(
        f"{path}: unsupported node kind {node.kind}"
    )


def encode_text(text):
    raw = text.encode("utf-8")

    if text.isascii():
        return b"\x81" + encode_uvar(len(raw)) + raw

    return (
        b"\x82"
        + encode_uvar(len(text))
        + encode_uvar(len(raw))
        + raw
    )


def ensure_range(value, lo, hi, label):
    if not (lo <= value <= hi):
        raise RTONError(
            f"{label} 超出范围: {value}，允许 {lo}..{hi}"
        )


def encode_int_like_template(tag, value):
    if tag == 0x08:
        ensure_range(value, -128, 127, "int8")
        return b"\x08" + struct.pack("<b", value)

    if tag == 0x09:
        if value == 0:
            return b"\x09"
        ensure_range(value, -128, 127, "int8")
        return b"\x08" + struct.pack("<b", value)

    if tag == 0x0A:
        ensure_range(value, 0, 255, "uint8")
        return b"\x0A" + struct.pack("<B", value)

    if tag == 0x0B:
        if value == 0:
            return b"\x0B"
        ensure_range(value, 0, 255, "uint8")
        return b"\x0A" + struct.pack("<B", value)

    if tag == 0x10:
        ensure_range(value, -32768, 32767, "int16")
        return b"\x10" + struct.pack("<h", value)

    if tag == 0x11:
        if value == 0:
            return b"\x11"
        ensure_range(value, -32768, 32767, "int16")
        return b"\x10" + struct.pack("<h", value)

    if tag == 0x12:
        ensure_range(value, 0, 65535, "uint16")
        return b"\x12" + struct.pack("<H", value)

    if tag == 0x13:
        if value == 0:
            return b"\x13"
        ensure_range(value, 0, 65535, "uint16")
        return b"\x12" + struct.pack("<H", value)

    if tag == 0x20:
        ensure_range(value, -(2**31), 2**31 - 1, "int32")
        return b"\x20" + struct.pack("<i", value)

    if tag == 0x21:
        if value == 0:
            return b"\x21"
        ensure_range(value, -(2**31), 2**31 - 1, "int32")
        return b"\x20" + struct.pack("<i", value)

    if tag in (0x24, 0x28):
        if value < 0:
            raise RTONError(
                f"模板类型 0x{tag:02x} 是 unsigned varint，"
                f"不能写入负数 {value}"
            )
        return bytes([tag]) + encode_uvar(value)

    if tag in (0x25, 0x29):
        return bytes([tag]) + encode_svar(value)

    if tag == 0x26:
        ensure_range(value, 0, 2**32 - 1, "uint32")
        return b"\x26" + struct.pack("<I", value)

    if tag == 0x27:
        if value == 0:
            return b"\x27"
        ensure_range(value, 0, 2**32 - 1, "uint32")
        return b"\x26" + struct.pack("<I", value)

    if tag == 0x40:
        ensure_range(value, -(2**63), 2**63 - 1, "int64")
        return b"\x40" + struct.pack("<q", value)

    if tag == 0x41:
        if value == 0:
            return b"\x41"
        ensure_range(value, -(2**63), 2**63 - 1, "int64")
        return b"\x40" + struct.pack("<q", value)

    if tag in (0x44, 0x48):
        if value < 0:
            raise RTONError(
                f"模板类型 0x{tag:02x} 是 unsigned varint，"
                f"不能写入负数 {value}"
            )
        return bytes([tag]) + encode_uvar(value)

    if tag in (0x45, 0x49):
        return bytes([tag]) + encode_svar(value)

    if tag == 0x46:
        ensure_range(value, 0, 2**64 - 1, "uint64")
        return b"\x46" + struct.pack("<Q", value)

    if tag == 0x47:
        if value == 0:
            return b"\x47"
        ensure_range(value, 0, 2**64 - 1, "uint64")
        return b"\x46" + struct.pack("<Q", value)

    raise RTONError(
        f"unsupported integer template tag 0x{tag:02x}"
    )


def encode_utf8_body(text):
    raw = text.encode("utf-8")

    return (
        encode_uvar(len(text))
        + encode_uvar(len(raw))
        + raw
    )


def encode_rtid(node, changed):
    if changed == node.value:
        meta = node.meta
        subtype = meta["subtype"]

        if subtype == 0:
            return b"\x83\x00"

        if subtype == 2:
            return (
                b"\x83\x02"
                + encode_utf8_body(meta["name"])
                + encode_uvar(meta["u2"])
                + encode_uvar(meta["u1"])
                + struct.pack("<I", meta["ident"])
            )

        if subtype == 3:
            return (
                b"\x83\x03"
                + encode_utf8_body(meta["first"])
                + encode_utf8_body(meta["second"])
            )

    if changed == "RTID()":
        return b"\x83\x00"

    m = RTID2_RE.match(changed)

    if m:
        u1 = int(m.group(1))
        u2 = int(m.group(2))
        ident = int(m.group(3), 16)
        name = m.group(4)

        return (
            b"\x83\x02"
            + encode_utf8_body(name)
            + encode_uvar(u2)
            + encode_uvar(u1)
            + struct.pack("<I", ident)
        )

    raise RTONError(
        "RTID 被修改，但新值无法安全恢复原始 RTID 类型："
        f"{changed!r}"
    )


def encode_node(node, changed, path="root"):
    if node.kind == "object":
        out = bytearray()

        if not node.meta.get("root"):
            out.append(0x85)

        # 不复用模板字符串缓存，统一重新编码为普通字符串。
        for key, child in node.value:
            out.extend(encode_text(key))
            out.extend(
                encode_node(
                    child,
                    changed[key],
                    f"{path}.{key}",
                )
            )

        out.append(0xFF)
        return bytes(out)

    if node.kind == "array":
        out = bytearray(b"\x86\xFD")
        out.extend(encode_uvar(len(changed)))

        for i, new_value in enumerate(changed):
            child = array_item_template(node, i)
            out.extend(
                encode_node(
                    child,
                    new_value,
                    f"{path}[{i}]",
                )
            )

        out.append(0xFE)
        return bytes(out)

    if node.kind == "string":
        return encode_text(changed)

    if node.kind == "rtid":
        return encode_rtid(node, changed)

    if node.kind == "bool":
        return b"\x01" if changed else b"\x00"

    if node.kind == "int":
        try:
            return encode_int_like_template(
                node.tag,
                changed,
            )
        except RTONError as e:
            raise RTONError(f"{path}: {e}") from e

    if node.kind == "float":
        value = float(changed)

        if node.tag == 0x22:
            return b"\x22" + struct.pack("<f", value)

        if node.tag == 0x23:
            if value == 0.0:
                return b"\x23"
            return b"\x22" + struct.pack("<f", value)

        if node.tag == 0x42:
            return b"\x42" + struct.pack("<d", value)

        if node.tag == 0x43:
            if value == 0.0:
                return b"\x43"
            return b"\x42" + struct.pack("<d", value)

        raise RTONError(
            f"{path}: unsupported float tag 0x{node.tag:02x}"
        )

    raise RTONError(
        f"{path}: unsupported node kind {node.kind}"
    )


def build_rton(template_version, template_root, changed_json):
    changed_version = changed_json.get("_rton_version")

    if changed_version != template_version:
        raise RTONError(
            "_rton_version 不允许修改："
            f"template={template_version}, changed={changed_version}"
        )

    changed_root = {
        key: value
        for key, value in changed_json.items()
        if key != "_rton_version"
    }

    validate_changed(
        template_root,
        changed_root,
        path="root",
    )

    body = encode_node(
        template_root,
        changed_root,
        path="root",
    )

    return (
        b"RTON"
        + struct.pack("<I", template_version)
        + body
        + b"DONE"
    )


