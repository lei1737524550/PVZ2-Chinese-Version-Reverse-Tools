"""解包工程目录识别、阶段定位与基础容器选择。"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from binary_codecs.smf import smf_to_rsb
from domain.formats import (
    FORMAT_RANK,
    RANK_TO_FORMAT,
    RESOURCE_LEVELS,
    RSB_MAGICS,
    RSLB_MAGIC,
    container_output_name,
    detect_format,
    level_index,
)

_STAGE_RE = re.compile(r"^(\d+)_([A-Za-z0-9_]+)$")


@dataclass(frozen=True, slots=True)
class StageInfo:
    """工程目录中一个阶段目录的语义信息。"""

    sequence: int
    rank: int


def stage_info(path: Path) -> StageInfo | None:
    """从阶段目录名中解析顺序与资源层级。"""
    if not path.is_dir():
        return None
    match = _STAGE_RE.match(path.name)
    if not match:
        return None
    folder_name = match.group(2).upper()
    for level in RESOURCE_LEVELS:
        if level.folder.upper() == folder_name:
            return StageInfo(sequence=int(match.group(1)), rank=level.rank)
    return None


def detect_source_format(source: Path) -> str:
    """识别阶段目录、工程目录或普通资源输入的格式。"""
    own_stage = stage_info(source)
    if own_stage is not None:
        return RANK_TO_FORMAT[own_stage.rank]

    if source.is_dir():
        found = [
            info
            for child in source.iterdir()
            if (info := stage_info(child)) is not None
        ]
        if found:
            return RANK_TO_FORMAT[max(info.rank for info in found)]
    return detect_format(source)


def find_stage_dir(root: Path, level_rank: int) -> Path | None:
    """返回工程中指定资源层级最新的阶段目录。"""
    if not root.is_dir():
        return None
    matches: list[tuple[int, Path]] = []
    for child in root.iterdir():
        info = stage_info(child)
        if info is not None and info.rank == level_rank:
            matches.append((info.sequence, child))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def resolve_stage_source(source: Path, source_rank: int) -> Path:
    """工程目录输入时自动定位实际阶段目录。"""
    if not source.is_dir():
        return source
    own_stage = stage_info(source)
    if own_stage is not None and own_stage.rank == source_rank:
        return source
    return find_stage_dir(source, source_rank) or source


def project_root(source: Path) -> Path:
    """返回阶段目录对应的工程根目录。"""
    return source.parent if stage_info(source) is not None else source


def strip_pack_suffixes(name: str) -> str:
    """移除工程名尾部重复的打包状态后缀。"""
    while True:
        old = name
        for suffix in ("_unpacked", "_packed", "_repacked"):
            if name.lower().endswith(suffix):
                name = name[:-len(suffix)]
        if name == old:
            return name


def strip_resource_extension(name: str) -> str:
    """移除已知资源扩展名。"""
    lower = name.lower()
    for suffix in (
        ".rsb.smf",
        ".rsb1",
        ".1bsr",
        ".rsb",
        ".smf",
        ".obb",
        ".rsg",
        ".rton",
        ".json",
    ):
        if lower.endswith(suffix):
            return name[:-len(suffix)]
    return Path(name).stem


def default_pack_output(source: Path) -> Path:
    """生成默认回包输出目录。"""
    root = project_root(source)
    if root.is_dir():
        name, parent = root.name, root.parent
    else:
        name, parent = strip_resource_extension(root.name), root.parent
    return parent / f"{strip_pack_suffixes(name)}_packed"


def project_base_name(source: Path) -> str:
    """取得回包输出使用的基础文件名。"""
    root = project_root(source)
    name = root.name if root.is_dir() else strip_resource_extension(root.name)
    return strip_pack_suffixes(name)


def prepare_stage(stage_dir: Path) -> None:
    """清理并重新创建一个输出阶段目录。"""
    if stage_dir.exists():
        if stage_dir.is_dir():
            shutil.rmtree(stage_dir)
        else:
            stage_dir.unlink()
    stage_dir.mkdir(parents=True, exist_ok=True)


def validate_changed_json(
    source: Path,
    known_unchanged: frozenset[str],
) -> tuple[Path, ...]:
    """检查本次真正需要回写的 JSON 是否为合法 UTF-8 JSON。"""
    files = [source] if source.is_file() else sorted(source.rglob("*.json"))
    changed: list[Path] = []
    for path in files:
        if str(path.resolve()) in known_unchanged:
            continue
        changed.append(path.resolve())
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                json.load(file)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"JSON 语法错误：{path}\n"
                f"第 {error.lineno} 行，第 {error.colno} 列：{error.msg}"
            ) from None
        except UnicodeDecodeError as error:
            raise ValueError(f"JSON 不是有效的 UTF-8：{path}\n{error}") from None
    if changed:
        print(f"JSON 检查通过：{len(changed)} 个修改或未索引文件")
    return tuple(changed)


def ask_existing(label: str, *, allow_file: bool, allow_dir: bool) -> Path:
    """交互式请求一个已存在的文件或目录。"""
    while True:
        value = input(f"{label}：").strip().strip('"').strip("'")
        path = Path(value).expanduser()
        if allow_file and path.is_file():
            return path
        if allow_dir and path.is_dir():
            return path
        kind = "文件或目录" if allow_file and allow_dir else ("文件" if allow_file else "目录")
        print(f"{kind}不存在：{path}")


def find_base_rsg(root: Path) -> Path | None:
    """从工程目录自动定位基础 RSG 阶段。"""
    return find_stage_dir(root, level_index("rsg"))


def read_magic(path: Path) -> bytes:
    """读取容器魔数；读取失败时返回空字节串。"""
    try:
        with path.open("rb") as file:
            return file.read(4)
    except OSError:
        return b""


def container_kind(path: Path) -> str | None:
    """判断基础容器是原始 RSB 还是 RSLB SMF。"""
    magic = read_magic(path)
    if magic in RSB_MAGICS:
        return "rsb"
    if magic == RSLB_MAGIC:
        return "smf"
    return None


def _logical_container_name(path: Path) -> str:
    return strip_resource_extension(path.name).lower()


def _format_size(size: int) -> str:
    return f"{size:,} bytes ({size / 1024 / 1024:.2f} MiB)"


def choose_container(
    candidates: list[Path],
    expected_name: str | None = None,
) -> Path | None:
    """从多个基础容器候选中选择最合适的一项。"""
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key not in seen and path.is_file() and container_kind(path) is not None:
            seen.add(key)
            unique.append(path)

    if expected_name:
        exact = [path for path in unique if _logical_container_name(path) == expected_name.lower()]
        if exact:
            unique = exact
    if not unique:
        return None

    raw = [path for path in unique if container_kind(path) == "rsb"]
    preferred = raw if raw else [path for path in unique if container_kind(path) == "smf"]
    preferred.sort(key=lambda path: (path.stat().st_size, path.name.lower()), reverse=True)

    if len(preferred) == 1:
        chosen = preferred[0]
        kind = "RSB/1bsr" if container_kind(chosen) == "rsb" else "SMF/RSLB"
        print(f"自动选择基础容器：{chosen} [{kind}, {_format_size(chosen.stat().st_size)}]")
        return chosen

    print("\n检测到多个同等级基础容器：")
    for index, path in enumerate(preferred, 1):
        kind = "RSB/1bsr" if container_kind(path) == "rsb" else "SMF/RSLB"
        recommended = "  ← 推荐（同格式中容量最大）" if index == 1 else ""
        print(
            f"[{index}] {path}\n"
            f"    类型：{kind}\n"
            f"    大小：{_format_size(path.stat().st_size)}{recommended}"
        )

    if not sys.stdin.isatty():
        print(f"非交互环境，自动使用推荐项：[1] {preferred[0]}")
        return preferred[0]

    while True:
        value = input("直接回车使用推荐项，或输入编号：").strip()
        if not value:
            return preferred[0]
        try:
            index = int(value) - 1
        except ValueError:
            index = -1
        if 0 <= index < len(preferred):
            return preferred[index]
        print("输入无效。")


def find_base_container(root: Path) -> Path | None:
    """从工程阶段和工程同级目录查找基础 RSB/SMF。"""
    base_name = strip_pack_suffixes(root.name).lower()
    candidates: list[Path] = []

    rsb_stage = find_stage_dir(root, level_index("rsb"))
    if rsb_stage is not None:
        candidates.extend(path for path in rsb_stage.iterdir() if path.is_file())

    smf_stage = find_stage_dir(root, level_index("smf"))
    if smf_stage is not None:
        candidates.extend(path for path in smf_stage.iterdir() if path.is_file())

    suffixes = (".rsb", ".rsb.smf", ".smf", ".1bsr", ".rsb1", ".obb")
    for child in root.parent.iterdir():
        if child.is_file() and child.name.lower().endswith(suffixes):
            candidates.append(child)
    return choose_container(candidates, base_name)


def validate_base_container(path: Path) -> str:
    """验证基础容器并返回 rsb/smf 类型。"""
    if not path.is_file():
        raise FileNotFoundError(f"基础容器不存在：{path}")
    kind = container_kind(path)
    if kind is None:
        magic = read_magic(path).hex(" ").upper()
        raise ValueError(
            f"基础容器必须是 RSB(1bsr/rsb1) 或 SMF(RSLB)：{path}\n文件头：{magic}"
        )
    return kind


def raw_base_rsb(container: Path, temp_dir: Path) -> Path:
    """确保回包模板是原始 RSB；SMF 会先临时解出 RSB。"""
    kind = validate_base_container(container)
    if kind == "rsb":
        return container
    destination = temp_dir / f"{strip_resource_extension(container.name)}.base.rsb"
    print(f"基础容器是 SMF，自动临时解出 RSB：{destination}")
    smf_to_rsb(container, destination)
    return destination


def output_file(stage_dir: Path, base_name: str, fmt: str) -> Path:
    """生成阶段中的容器输出路径。"""
    return stage_dir / container_output_name(Path(base_name + ".rsb"), fmt)


def copy_rsb_representation(source: Path, destination: Path) -> None:
    """RSB 与 RSBX 同级表示切换时只复制数据。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
