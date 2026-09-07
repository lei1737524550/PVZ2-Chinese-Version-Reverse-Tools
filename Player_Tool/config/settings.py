"""Tool_2 根目录 params.json 的强类型读取层。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

TOOL_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = TOOL_ROOT / "params.json"


@dataclass(frozen=True, slots=True)
class AndroidSettings:
    package: str
    game_dat: str
    game_backup: str
    rish: str = "rish"
    write_game_backup: bool = True
    force_stop_game: bool = True


@dataclass(frozen=True, slots=True)
class FileSettings:
    export_dat: str = "pp.dat"
    export_bin: str = "pp.bin"
    export_json: str = "pp.json"
    import_bin: str = "changed.bin"
    import_dat: str = "changed.dat"
    diff_before: str = "pp_before.json"
    diff_after: str = "pp.json"
    diff_output: str = "pp_diff.txt"


@dataclass(frozen=True, slots=True)
class RtonSettings:
    encryption_seed: str
    block_size: int = 24


@dataclass(frozen=True, slots=True)
class Settings:
    android: AndroidSettings
    files: FileSettings
    rton: RtonSettings


def _section(root: dict[str, Any], name: str) -> dict[str, Any]:
    value = root.get(name)
    if not isinstance(value, dict):
        raise RuntimeError(f"params.json 缺少对象配置：{name}")
    return value


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    try:
        root = json.loads(PARAMS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"缺少配置文件：{PARAMS_FILE}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"params.json 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列：{exc.msg}"
        ) from exc
    if not isinstance(root, dict):
        raise RuntimeError("params.json 顶层必须是 JSON 对象")

    android = _section(root, "android")
    files = _section(root, "files")
    rton = _section(root, "rton")
    settings = Settings(
        android=AndroidSettings(
            package=str(android["package"]),
            game_dat=str(android["game_dat"]),
            game_backup=str(android["game_backup"]),
            rish=str(android.get("rish", "rish")),
            write_game_backup=bool(android.get("write_game_backup", True)),
            force_stop_game=bool(android.get("force_stop_game", True)),
        ),
        files=FileSettings(
            export_dat=str(files.get("export_dat", "pp.dat")),
            export_bin=str(files.get("export_bin", "pp.bin")),
            export_json=str(files.get("export_json", "pp.json")),
            import_bin=str(files.get("import_bin", "changed.bin")),
            import_dat=str(files.get("import_dat", "changed.dat")),
            diff_before=str(files.get("diff_before", "pp_before.json")),
            diff_after=str(files.get("diff_after", "pp.json")),
            diff_output=str(files.get("diff_output", "pp_diff.txt")),
        ),
        rton=RtonSettings(
            encryption_seed=str(rton["encryption_seed"]),
            block_size=int(rton.get("block_size", 24)),
        ),
    )
    if settings.rton.block_size < 1:
        raise RuntimeError("rton.block_size 必须大于 0")
    return settings


SETTINGS = load_settings()
