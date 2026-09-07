"""读取 项目根目录唯一的 params.json，并转换为强类型配置对象。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_FILE = Path(__file__).resolve().parents[1] / "params.json"


@dataclass(frozen=True, slots=True)
class SmfSettings:
    """SMF/RSLB 容器参数。"""

    rslb_version: int
    chunk_size: int
    fixed_header_size: int
    base_entry_size: int
    link_size: int
    known_size_field_styles: tuple[str, ...]
    default_size_field_style: str


@dataclass(frozen=True, slots=True)
class IndexSettings:
    """工程索引参数。"""

    hash_workers: int = 4


@dataclass(frozen=True, slots=True)
class ConversionSettings:
    """RTON、RSG 与 JSON 转换参数。"""

    rton_encryption_seed: str
    rton_block_size: int
    rsg_name_prefixes: tuple[str, ...]
    rsg_name_suffixes: tuple[str, ...]
    internal_path_prefixes: tuple[str, ...]
    internal_path_suffixes: tuple[str, ...]
    json_indent: int | None
    json_ensure_ascii: bool
    json_sort_keys: bool
    json_sort_values: bool
    json_repair_files: bool


@dataclass(frozen=True, slots=True)
class FileSystemSettings:
    """文件系统级优化参数。"""

    ficlone_ioctl: int


@dataclass(frozen=True, slots=True)
class ToolSettings:
    """PvZ2 Resource Tool 的完整配置。"""

    smf: SmfSettings
    index: IndexSettings
    conversion: ConversionSettings
    filesystem: FileSystemSettings


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"params.json 中 {name} 必须是 JSON 对象")
    return value


@lru_cache(maxsize=1)
def load_settings() -> ToolSettings:
    """加载并校验 项目根目录的唯一配置文件。"""
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"缺少 项目配置文件：{_CONFIG_FILE}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"项目配置 JSON 格式错误：{_CONFIG_FILE} "
            f"(第 {exc.lineno} 行，第 {exc.colno} 列：{exc.msg})"
        ) from exc

    root = _require_object(raw, "根对象")
    smf = _require_object(root.get("smf"), "smf")
    index = _require_object(root.get("index", {}), "index")
    conversion = _require_object(root.get("conversion"), "conversion")
    filesystem = _require_object(root.get("filesystem"), "filesystem")

    return ToolSettings(
        smf=SmfSettings(
            rslb_version=int(smf["rslb_version"]),
            chunk_size=int(smf["chunk_size"]),
            fixed_header_size=int(smf["fixed_header_size"]),
            base_entry_size=int(smf["base_entry_size"]),
            link_size=int(smf["link_size"]),
            known_size_field_styles=tuple(str(x) for x in smf["known_size_field_styles"]),
            default_size_field_style=str(smf["default_size_field_style"]),
        ),
        index=IndexSettings(hash_workers=int(index.get("hash_workers", 4))),
        conversion=ConversionSettings(
            rton_encryption_seed=str(conversion["rton_encryption_seed"]),
            rton_block_size=int(conversion["rton_block_size"]),
            rsg_name_prefixes=tuple(str(x) for x in conversion.get("rsg_name_prefixes", [])),
            rsg_name_suffixes=tuple(str(x) for x in conversion.get("rsg_name_suffixes", [])),
            internal_path_prefixes=tuple(str(x) for x in conversion.get("internal_path_prefixes", [])),
            internal_path_suffixes=tuple(str(x) for x in conversion.get("internal_path_suffixes", [])),
            json_indent=conversion.get("json_indent", 4),
            json_ensure_ascii=bool(conversion.get("json_ensure_ascii", False)),
            json_sort_keys=bool(conversion.get("json_sort_keys", False)),
            json_sort_values=bool(conversion.get("json_sort_values", False)),
            json_repair_files=bool(conversion.get("json_repair_files", False)),
        ),
        filesystem=FileSystemSettings(ficlone_ioctl=int(filesystem["ficlone_ioctl"])),
    )


SETTINGS = load_settings()
