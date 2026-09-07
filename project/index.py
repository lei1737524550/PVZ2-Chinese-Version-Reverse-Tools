"""解包工程索引的生成、读取与反向回包入口。"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import SETTINGS

BEGIN = "<!-- PVZ-INDEX-JSON-BEGIN -->"
END = "<!-- PVZ-INDEX-JSON-END -->"
_HASH_WORKERS = SETTINGS.index.hash_workers


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """单个文件在解包时的尺寸与哈希。"""

    size: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"size": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class StageRecord:
    """解包工程中的一个阶段记录。"""

    sequence: int
    level: str
    format: str
    path: str
    file_count: int
    total_bytes: int
    file_fingerprints: dict[str, FileFingerprint] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "sequence": self.sequence,
            "level": self.level,
            "format": self.format,
            "path": self.path,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }
        if self.file_fingerprints:
            data["file_fingerprints"] = {
                name: fingerprint.to_dict()
                for name, fingerprint in self.file_fingerprints.items()
            }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageRecord":
        fingerprints = {
            name: FileFingerprint(
                size=int(raw["size"]),
                sha256=str(raw["sha256"]),
            )
            for name, raw in data.get("file_fingerprints", {}).items()
        }
        return cls(
            sequence=int(data["sequence"]),
            level=str(data["level"]),
            format=str(data["format"]),
            path=str(data["path"]),
            file_count=int(data.get("file_count", 0)),
            total_bytes=int(data.get("total_bytes", 0)),
            file_fingerprints=fingerprints,
        )


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """工程索引记录的原始输入。"""

    path: Path
    name: str
    level: str
    size: int | None = None
    sha256: str | None = None
    header: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": str(self.path),
            "name": self.name,
            "level": self.level,
        }
        if self.size is not None:
            data["size"] = self.size
        if self.sha256 is not None:
            data["sha256"] = self.sha256
        if self.header is not None:
            data["header"] = self.header
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRecord":
        return cls(
            path=Path(data["path"]),
            name=str(data["name"]),
            level=str(data["level"]),
            size=int(data["size"]) if "size" in data else None,
            sha256=str(data["sha256"]) if "sha256" in data else None,
            header=str(data["header"]) if "header" in data else None,
        )


@dataclass(frozen=True, slots=True)
class ProjectIndex:
    """解析后的工程索引。"""

    root: Path
    source: SourceRecord
    stages: tuple[StageRecord, ...]
    version: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary(path: Path) -> tuple[int, int]:
    if path.is_file():
        return 1, path.stat().st_size

    count = 0
    size = 0
    for item in path.rglob("*"):
        if item.is_file():
            count += 1
            size += item.stat().st_size
    return count, size


def _fingerprints(path: Path) -> dict[str, FileFingerprint]:
    """记录最深编辑层的文件指纹，回包时只处理真正改过的文件。"""
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    root = path.parent if path.is_file() else path

    def fingerprint(item: Path) -> tuple[str, FileFingerprint]:
        return (
            item.relative_to(root).as_posix(),
            FileFingerprint(size=item.stat().st_size, sha256=_sha256(item)),
        )

    with ThreadPoolExecutor(max_workers=_HASH_WORKERS) as executor:
        return dict(executor.map(fingerprint, files))


def build_stage_record(
    project_root: Path,
    sequence: int,
    level_id: str,
    level_name: str,
    path: Path,
    *,
    record_files: bool = False,
) -> StageRecord:
    """建立单个阶段的强类型索引记录。"""
    count, size = _summary(path)
    return StageRecord(
        sequence=sequence,
        level=level_id,
        format=level_name,
        path=path.relative_to(project_root).as_posix(),
        file_count=count,
        total_bytes=size,
        file_fingerprints=_fingerprints(path) if record_files else {},
    )


def write_index(
    project_root: Path,
    source: Path,
    source_level: str,
    stages: list[StageRecord],
) -> Path:
    """写入含机器数据块和人工摘要表的 index.md。"""
    source = source.resolve()
    source_record = SourceRecord(
        path=source,
        name=source.name,
        level=source_level,
    )

    if source.is_file():
        with source.open("rb") as file:
            header = file.read(16).hex(" ").upper()
        source_record = SourceRecord(
            path=source,
            name=source.name,
            level=source_level,
            size=source.stat().st_size,
            sha256=_sha256(source),
            header=header,
        )

    manifest = {
        "index_version": 2,
        "source": source_record.to_dict(),
        "stages": [stage.to_dict() for stage in stages],
    }

    lines = [
        "# PvZ2 解包工程索引",
        "",
        "> 此文件由工具生成。可以阅读，但不要手动修改机器数据块。",
        "",
        "## 原始输入",
        "",
        f"- 文件：`{source_record.name}`",
        f"- 路径：`{source_record.path}`",
        f"- 格式：`{source_level}`",
    ]
    if source_record.size is not None:
        lines.extend(
            [
                f"- 大小：`{source_record.size}` 字节",
                f"- SHA-256：`{source_record.sha256}`",
                f"- 文件头：`{source_record.header}`",
            ]
        )

    lines.extend(
        [
            "",
            "## 阶段目录",
            "",
            "| 顺序 | 格式 | 路径 | 文件数 | 总字节数 |",
            "| ---: | --- | --- | ---: | ---: |",
        ]
    )
    for stage in stages:
        lines.append(
            f"| {stage.sequence} | {stage.format} | `{stage.path}` | "
            f"{stage.file_count} | {stage.total_bytes} |"
        )
        if stage.file_fingerprints:
            lines.append(f"<!-- 已记录 {len(stage.file_fingerprints)} 个文件指纹 -->")

    lines.extend(
        [
            "",
            "## 机器数据",
            "",
            BEGIN,
            "```json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
            "```",
            END,
            "",
        ]
    )

    destination = project_root / "index.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def read_index(project: str | Path) -> ProjectIndex:
    """读取并解析工程索引。"""
    path = Path(project).expanduser()
    index = path if path.is_file() else path / "index.md"
    if not index.is_file():
        raise FileNotFoundError(f"找不到工程索引：{index}")

    text = index.read_text(encoding="utf-8")
    try:
        block = text.split(BEGIN, 1)[1].split(END, 1)[0]
        payload = block.split("```json", 1)[1].split("```", 1)[0]
        manifest = json.loads(payload)
    except (IndexError, json.JSONDecodeError) as error:
        raise ValueError(f"index.md 的机器数据块损坏：{index}") from error

    version = int(manifest.get("index_version", 0))
    raw_stages = manifest.get("stages")
    if version not in {1, 2} or not raw_stages:
        raise ValueError(f"不支持或不完整的工程索引：{index}")

    return ProjectIndex(
        root=index.parent.resolve(),
        source=SourceRecord.from_dict(manifest["source"]),
        stages=tuple(StageRecord.from_dict(stage) for stage in raw_stages),
        version=version,
    )


def unchanged_files_from_index(project_root: Path, source: Path) -> frozenset[str]:
    """返回从解包至今内容未变化的绝对文件路径集合。"""
    index_path = project_root / "index.md"
    if not index_path.is_file():
        return frozenset()

    try:
        project = read_index(index_path)
    except (OSError, ValueError):
        return frozenset()

    source = source.resolve()
    stage = next(
        (
            item
            for item in project.stages
            if (project.root / item.path).resolve() == source
        ),
        None,
    )
    if stage is None or not stage.file_fingerprints:
        return frozenset()

    def unchanged(item: tuple[str, FileFingerprint]) -> str | None:
        relative, expected = item
        path = source / relative if source.is_dir() else source
        try:
            if path.stat().st_size != expected.size or _sha256(path) != expected.sha256:
                return None
        except OSError:
            return None
        return str(path.resolve())

    with ThreadPoolExecutor(max_workers=_HASH_WORKERS) as executor:
        return frozenset(filter(None, executor.map(unchanged, stage.file_fingerprints.items())))


def reverse_from_index(project: str | Path) -> Path:
    """读取 index.md，自动从最深阶段反向打包到原输入格式。"""
    from services.pack import pack

    index = read_index(project)
    source = index.source.path
    if not source.exists():
        raise FileNotFoundError(f"原始基础文件不存在：{source}")
    if source.is_file() and index.source.sha256 and _sha256(source) != index.source.sha256:
        raise ValueError(f"原始基础文件已变化，拒绝回包：{source}")

    deepest = index.stages[-1]
    input_path = index.root / deepest.path

    target_level = index.source.level
    if source.is_file():
        with source.open("rb") as file:
            magic = file.read(4)
        if magic == b"RSLB":
            target_level = "smf"
        elif magic in {b"1bsr", b"rsb1"}:
            target_level = "rsbx" if source.name.lower().endswith(".rsb.smf") else "rsb"

    rsg_stage = next((stage for stage in index.stages if stage.level == "rsg"), None)
    base_rsg = source if target_level == "rsg" else (index.root / rsg_stage.path if rsg_stage else None)
    base_rsb = source if target_level in {"smf", "rsb", "rsbx"} else None

    output_name = index.root.name
    if output_name.lower().endswith("_unpacked"):
        output_name = output_name[:-9]
    output = index.root.parent / f"{output_name}_repacked"

    print(f"读取索引：{index.root / 'index.md'}")
    print(f"反向起点：{input_path}")
    return pack(
        input_path,
        target_level,
        output,
        source_level=deepest.level,
        base_rsg=base_rsg,
        base_rsb=base_rsb,
    )


def run_index_reverse(project: str | Path | None = None) -> Path:
    """从参数、当前目录或交互输入中确定解包工程并回包。"""
    candidate = Path(project).expanduser() if project else Path.cwd()
    index = candidate if candidate.is_file() else candidate / "index.md"
    if not index.is_file() and project is None:
        entered = input("解包工程目录（里面应有 index.md）：").strip().strip('"').strip("'")
        if not entered:
            raise ValueError("未指定解包工程目录")
        candidate = Path(entered).expanduser()
    return reverse_from_index(candidate)
