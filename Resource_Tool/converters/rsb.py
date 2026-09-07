"""RSB 容器与 RSG 子包之间的转换。"""

from __future__ import annotations

import mmap
from pathlib import Path

from core.rsb_format import iter_rsb_rsg_files, patch_rsb_rsgs
from infrastructure.files import PathLike, as_path, require_path

_RAW_RSB_MAGICS = frozenset({b"1bsr", b"rsb1"})


def _is_raw_rsb(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(4) in _RAW_RSB_MAGICS
    except OSError:
        return False


def extract_rsg_files(
    source: PathLike,
    output: PathLike,
    *,
    verbose: bool = False,
    jobs: int | None = None,
) -> int:
    """从一个或多个原始 RSB 中提取 RSG。"""
    del jobs
    source_root = require_path(as_path(source), "RSB 输入")
    output_root = as_path(output)

    if source_root.is_file():
        if not _is_raw_rsb(source_root):
            with source_root.open("rb") as file:
                magic = file.read(4)
            raise ValueError(
                f"RSB → RSG 只接受 1bsr/rsb1；当前文件头={magic!r}：{source_root}"
            )
        sources = [source_root]
    else:
        sources = sorted(
            path
            for path in source_root.rglob("*")
            if path.is_file() and _is_raw_rsb(path)
        )

    count = 0
    for source_file in sources:
        target_root = (
            output_root
            if source_root.is_file()
            else output_root / source_file.relative_to(source_root).parent / source_file.stem
        )
        with source_file.open("rb") as file, mmap.mmap(
            file.fileno(), 0, access=mmap.ACCESS_READ
        ) as data:
            for name, payload in iter_rsb_rsg_files(data, str(source_file)):
                destination = target_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                if verbose:
                    print(f"生成：{destination}")
                count += 1

    if count == 0:
        raise FileNotFoundError(
            "没有提取到 RSG；请检查 Tool_1 根 params.json 的 conversion 过滤设置"
        )
    print(f"完成：提取 {count} 个 RSG")
    return count


def rebuild_rsb(
    base_rsb: PathLike,
    rsg_directory: PathLike,
    output: PathLike,
    *,
    verbose: bool = False,
    jobs: int | None = None,
) -> None:
    """以原始 RSB 为结构基底，写回修改后的 RSG。"""
    del jobs
    base = require_path(as_path(base_rsb), "基础 RSB", file=True)
    patches = require_path(as_path(rsg_directory), "RSG 修改目录")
    destination = as_path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    patch_root = patches.parent if patches.is_file() else patches
    destination.write_bytes(patch_rsb_rsgs(base.read_bytes(), patch_root, verbose=verbose))
    print(f"生成：{destination}")
