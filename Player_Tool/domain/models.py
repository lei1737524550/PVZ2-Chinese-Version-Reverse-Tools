"""Tool_2 各工作流之间传递的强类型数据。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExportPaths:
    work_dir: Path
    dat: Path
    bin: Path
    json: Path


@dataclass(frozen=True, slots=True)
class ExportRequest:
    paths: ExportPaths
    package: str
    game_path: str
    rish: str
    source: Path | None = None


@dataclass(frozen=True, slots=True)
class ImportPaths:
    work_dir: Path
    base_dat: Path
    changed_json: Path
    output_bin: Path
    output_dat: Path


@dataclass(frozen=True, slots=True)
class ImportRequest:
    paths: ImportPaths
    package: str
    game_dat: str
    game_backup: str
    rish: str
    build_only: bool = False
    write_game_backup: bool = True
    force_stop_game: bool = True


@dataclass(frozen=True, slots=True)
class InventoryRequest:
    json_path: Path
    entity: str
    action: str
    plant_id: int | None = None
    value: int | None = None
    pcpid: str | None = None


@dataclass(frozen=True, slots=True)
class DiffRequest:
    before: Path
    after: Path
    output: Path
