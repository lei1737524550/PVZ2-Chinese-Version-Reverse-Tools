"""RSG 与内部资源文件之间的转换。"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from converters.models import InternalExtractTask, RsgBuildResult, RsgTask
from core.rsg_format import patch_rsg_internal_files, rsg_to_internal_files
from infrastructure.files import (
    PathLike,
    as_path,
    clone_or_copy,
    recommended_jobs,
    require_path,
    sha256,
)


def _rsg_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() == ".rsg"
    )
    if not files:
        raise FileNotFoundError(f"{source} 中没有 RSG 文件")
    return files


def _all_files_unchanged(directory: Path, known_unchanged: frozenset[str]) -> bool:
    files = [path for path in directory.rglob("*") if path.is_file()]
    return bool(files) and all(str(path.resolve()) in known_unchanged for path in files)


def _extract_internal_task(task: InternalExtractTask) -> int:
    contents = rsg_to_internal_files(task.source.read_bytes(), "stored", str(task.source))
    for name, data in contents.items():
        relative = Path(*name.replace("\\", "/").split("/"))
        destination = task.destination / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        if task.verbose:
            print(f"生成：{destination}")
    return len(contents)


def extract_internal_files(
    source: PathLike,
    output: PathLike,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    """从 RSG 并行提取内部文件；加密 RTON 保持原始状态。"""
    source_root = require_path(as_path(source), "RSG 输入")
    output_root = as_path(output)
    tasks = [
        InternalExtractTask(
            source=source_file,
            destination=(
                output_root / source_file.relative_to(source_root).with_suffix("")
                if source_root.is_dir()
                else output_root
            ),
            verbose=verbose,
        )
        for source_file in _rsg_files(source_root)
    ]

    worker_count = recommended_jobs(jobs)
    if worker_count == 1 or len(tasks) < 2:
        count = sum(map(_extract_internal_task, tasks))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            count = sum(executor.map(_extract_internal_task, tasks))

    if count == 0:
        raise FileNotFoundError(
            "没有提取到内部文件；请检查 Tool_1 根 params.json 的 conversion 过滤设置"
        )
    print(f"完成：提取 {count} 个内部文件（并发 {worker_count}）")
    return count


def _rebuild_rsg_task(task: RsgTask) -> Path:
    if task.copy_whole:
        clone_or_copy(task.base, task.destination)
        return task.destination
    task.destination.parent.mkdir(parents=True, exist_ok=True)
    task.destination.write_bytes(
        patch_rsg_internal_files(
            task.base.read_bytes(),
            task.patch_dir,
            mode=task.mode,
            known_unchanged=task.unchanged,
            verbose=task.verbose,
        )
    )
    return task.destination


def rebuild_rsg(
    base_rsg: PathLike,
    internal_directory: PathLike,
    output: PathLike,
    *,
    mode: str = "stored",
    known_unchanged: frozenset[str] = frozenset(),
    verbose: bool = False,
    jobs: int | None = None,
) -> None:
    """以原始 RSG 为结构基底，写回内部文件。"""
    del jobs
    base = require_path(as_path(base_rsg), "基础 RSG", file=True)
    patches = require_path(as_path(internal_directory), "内部文件目录")
    destination = as_path(output)
    task = RsgTask(
        base=base,
        patch_dir=patches,
        destination=destination,
        mode=mode,
        unchanged=known_unchanged,
        verbose=verbose,
        copy_whole=_all_files_unchanged(patches, known_unchanged),
    )
    _rebuild_rsg_task(task)
    print(f"生成：{destination}")


def _create_rsg_tasks(
    bases: Path,
    patches: Path,
    output_root: Path,
    *,
    mode: str,
    known_unchanged: frozenset[str],
    verbose: bool,
) -> tuple[list[RsgTask], list[RsgBuildResult]]:
    tasks: list[RsgTask] = []
    results: list[RsgBuildResult] = []
    for base in _rsg_files(bases):
        relative = base.relative_to(bases)
        patch_dir = require_path(
            patches / relative.with_suffix(""),
            f"{base} 对应的内部文件目录",
            file=False,
        )
        destination = output_root / relative
        prefix = f"{patch_dir.resolve()}{os.sep}"
        unchanged_subset = frozenset(
            path for path in known_unchanged if path.startswith(prefix)
        )
        tasks.append(
            RsgTask(
                base=base,
                patch_dir=patch_dir,
                destination=destination,
                mode=mode,
                unchanged=unchanged_subset,
                verbose=verbose,
                copy_whole=_all_files_unchanged(patch_dir, unchanged_subset),
            )
        )
        results.append(RsgBuildResult(base, destination, relative))
    return tasks, results


def _verify_rsg_roundtrip(results: list[RsgBuildResult], *, verbose: bool) -> None:
    for result in results:
        expected = sha256(result.base)
        actual = sha256(result.destination)
        if actual != expected:
            raise ValueError(
                f"RSG 往返 SHA-256 不一致：{result.relative}\n"
                f"原 SHA-256：{expected}\n新 SHA-256：{actual}"
            )
        if verbose:
            print(f"SHA-256 一致：{result.relative}")


def rebuild_rsg_directory(
    base_rsg_directory: PathLike,
    internal_directory: PathLike,
    output_directory: PathLike,
    *,
    verify_unchanged: bool = False,
    mode: str = "stored",
    known_unchanged: frozenset[str] = frozenset(),
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    """按 ``name.rsg`` 与 ``name/`` 的对应关系并行回包 RSG。"""
    bases = require_path(as_path(base_rsg_directory), "基础 RSG 目录", file=False)
    patches = require_path(as_path(internal_directory), "内部文件目录", file=False)
    tasks, results = _create_rsg_tasks(
        bases,
        patches,
        as_path(output_directory),
        mode=mode,
        known_unchanged=known_unchanged,
        verbose=verbose,
    )
    worker_count = recommended_jobs(jobs)

    if worker_count == 1 or len(tasks) < 2:
        generated = map(_rebuild_rsg_task, tasks)
        for destination in generated:
            if verbose:
                print(f"生成：{destination}")
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            for destination in executor.map(_rebuild_rsg_task, tasks):
                if verbose:
                    print(f"生成：{destination}")

    if verify_unchanged:
        _verify_rsg_roundtrip(results, verbose=verbose)
    print(f"完成：重建 {len(tasks)} 个 RSG（并发 {worker_count}）")
    return len(tasks)
