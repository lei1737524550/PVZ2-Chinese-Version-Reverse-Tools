from __future__ import annotations

from io import BytesIO
from json import JSONDecodeError

from .conversion_settings import (
    JSON_ENSURE_ASCII,
    JSON_INDENT,
    JSON_REPAIR_FILES,
    JSON_SORT_KEYS,
    JSON_SORT_VALUES,
)
from .rton_binary import JSONDecoder, RTONDecoder


def _decoder() -> RTONDecoder:
    if JSON_INDENT is None:
        current_indent = b""
        indent = b""
    elif JSON_INDENT < 0:
        current_indent = b"\r\n"
        indent = b"\t"
    else:
        current_indent = b"\r\n"
        indent = b" " * JSON_INDENT
    return RTONDecoder(
        comma=b",",
        currrent_indent=current_indent,
        doublePoint=b": ",
        ensureAscii=JSON_ENSURE_ASCII,
        indent=indent,
        repairFiles=JSON_REPAIR_FILES,
        sortKeys=JSON_SORT_KEYS,
        sortValues=JSON_SORT_VALUES,
        warning_message=lambda text: print(f"warning: {text}"),
    )


def rton_to_json_bytes(data: bytes, source: str = "RTON") -> bytes:
    if not data.startswith(b"RTON"):
        raise ValueError(f"{source}: expected RTON header")
    fp = BytesIO(data)
    fp.name = source
    fp.read(4)
    return _decoder().parse_root_object(fp)


def json_to_rton_bytes(data: bytes, source: str = "JSON") -> bytes:
    fp = BytesIO(data)
    fp.name = source
    try:
        return JSONDecoder().encode_root_object(fp)
    except JSONDecodeError as error:
        raise ValueError(
            f"{source}: JSON 语法错误，第 {error.lineno} 行，"
            f"第 {error.colno} 列：{error.msg}"
        ) from None
