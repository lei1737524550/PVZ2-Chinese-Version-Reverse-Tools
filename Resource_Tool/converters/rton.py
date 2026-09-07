"""加密 RTON、RTON 与 JSON 的并行文件转换入口。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from converters.models import (
    CopyPairTask,
    CopyTask,
    DecryptDecodeResult,
    DecryptDecodeTask,
    TransformAction,
    TransformResult,
    TransformTask,
)
from core.rton_encryption import decrypt_rton, encrypt_rton
from core.rton_json_codec import json_to_rton_bytes, rton_to_json_bytes
from infrastructure.files import PathLike, clone_or_copy, recommended_jobs

type RenameRule = Callable[[str], str]

_CONVERSION_ERRORS = (ValueError, TypeError, KeyError, IndexError, EOFError, UnicodeError)


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _apply_transform(action: TransformAction, payload: bytes, source: str) -> bytes:
    transforms = {
        TransformAction.DECRYPT: decrypt_rton,
        TransformAction.ENCRYPT: encrypt_rton,
        TransformAction.DECODE: rton_to_json_bytes,
        TransformAction.ENCODE: json_to_rton_bytes,
    }
    return transforms[action](payload, source)


def _transform_one(task: TransformTask) -> TransformResult:
    try:
        payload = _apply_transform(task.action, task.source.read_bytes(), str(task.source))
    except _CONVERSION_ERRORS as error:
        clone_or_copy(task.source, task.fallback)
        return TransformResult(False, task.fallback, str(error))
    _write(task.converted, payload)
    return TransformResult(True, task.converted)


def _copy_one(task: CopyTask) -> tuple[Path, str]:
    return task.destination, clone_or_copy(task.source, task.destination)


def _decrypt_decode_one(task: DecryptDecodeTask) -> DecryptDecodeResult:
    try:
        plain = decrypt_rton(task.source.read_bytes(), str(task.source))
    except _CONVERSION_ERRORS as error:
        clone_or_copy(task.source, task.rton_fallback)
        clone_or_copy(task.source, task.json_fallback)
        return DecryptDecodeResult("decrypt_failed", task.json_fallback, str(error))

    _write(task.rton_path, plain)
    try:
        payload = rton_to_json_bytes(plain, str(task.source))
    except _CONVERSION_ERRORS as error:
        clone_or_copy(task.rton_path, task.json_fallback)
        return DecryptDecodeResult("decode_failed", task.json_fallback, str(error))

    _write(task.json_path, payload)
    return DecryptDecodeResult("converted", task.json_path)


def _copy_pair(task: CopyPairTask) -> tuple[int, int]:
    methods = (
        clone_or_copy(task.source, task.first),
        clone_or_copy(task.source, task.second),
    )
    return methods.count("clone"), methods.count("copy")


def _run_conversion_tasks(
    tasks: list[TransformTask],
    jobs: int,
    verbose: bool,
) -> tuple[int, int]:
    converted = 0
    failed = 0

    if jobs == 1 or len(tasks) < 2:
        results = map(_transform_one, tasks)
        for result in results:
            if result.success:
                converted += 1
                if verbose:
                    print(f"转换：{result.destination}")
            else:
                failed += 1
                if verbose:
                    print(f"保留：{result.destination}（转换失败：{result.error}）")
        return converted, failed

    chunk = max(1, len(tasks) // (jobs * 8))
    with ProcessPoolExecutor(max_workers=jobs) as executor:
        for result in executor.map(_transform_one, tasks, chunksize=chunk):
            if result.success:
                converted += 1
                if verbose:
                    print(f"转换：{result.destination}")
            else:
                failed += 1
                if verbose:
                    print(f"保留：{result.destination}（转换失败：{result.error}）")
    return converted, failed


def _run_copy_tasks(
    tasks: list[CopyTask],
    jobs: int,
    verbose: bool,
) -> tuple[int, int]:
    cloned = 0
    copied = 0

    if jobs == 1 or len(tasks) < 2:
        results = map(_copy_one, tasks)
        for destination, method in results:
            cloned += method == "clone"
            copied += method == "copy"
            if verbose:
                print(f"保留：{destination}")
        return cloned, copied

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        for destination, method in executor.map(_copy_one, tasks):
            cloned += method == "clone"
            copied += method == "copy"
            if verbose:
                print(f"保留：{destination}")
    return cloned, copied


def _source_files(source_root: Path) -> list[Path]:
    if source_root.is_file():
        return [source_root]
    return sorted(path for path in source_root.rglob("*") if path.is_file())


def _transform_tree(
    source: PathLike,
    output: PathLike,
    suffixes: tuple[str, ...],
    rename: RenameRule,
    action: TransformAction,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    source_root = Path(source).expanduser()
    output_root = Path(output).expanduser()
    if not source_root.exists():
        raise FileNotFoundError(f"输入不存在：{source_root}")

    files = _source_files(source_root)
    if not files:
        raise FileNotFoundError(f"{source_root} 中没有文件")

    normalized_suffixes = tuple(suffix.lower() for suffix in suffixes)
    transform_tasks: list[TransformTask] = []
    copy_tasks: list[CopyTask] = []

    for source_file in files:
        relative = (
            Path(source_file.name)
            if source_root.is_file()
            else source_file.relative_to(source_root)
        )
        fallback = output_root if source_root.is_file() else output_root / relative
        if source_file.name.lower().endswith(normalized_suffixes):
            renamed = relative.with_name(rename(relative.name))
            converted = output_root if source_root.is_file() else output_root / renamed
            transform_tasks.append(
                TransformTask(
                    source=source_file,
                    converted=converted,
                    fallback=fallback,
                    action=action,
                )
            )
        else:
            copy_tasks.append(CopyTask(source_file, fallback))

    worker_count = recommended_jobs(jobs)
    converted, failed = _run_conversion_tasks(transform_tasks, worker_count, verbose)
    cloned, copied = _run_copy_tasks(copy_tasks, worker_count, verbose)
    preserved = failed + cloned + copied
    print(
        f"完成：转换 {converted} 个，原样保留 {preserved} 个"
        f"（并发 {worker_count}，写时复制 {cloned}）"
    )
    return converted + preserved


def decrypt_rton_files(
    source: PathLike,
    output: PathLike,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    return _transform_tree(
        source,
        output,
        (".rton", ".bin", ".dat"),
        lambda name: name,
        TransformAction.DECRYPT,
        jobs=jobs,
        verbose=verbose,
    )


def encrypt_rton_files(
    source: PathLike,
    output: PathLike,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    return _transform_tree(
        source,
        output,
        (".rton", ".bin", ".dat"),
        lambda name: name,
        TransformAction.ENCRYPT,
        jobs=jobs,
        verbose=verbose,
    )


def decode_rton_files(
    source: PathLike,
    output: PathLike,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    return _transform_tree(
        source,
        output,
        (".rton", ".bin", ".dat"),
        lambda name: name[:-5] + ".json" if name.lower().endswith(".rton") else name + ".json",
        TransformAction.DECODE,
        jobs=jobs,
        verbose=verbose,
    )


def encode_json_files(
    source: PathLike,
    output: PathLike,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    return _transform_tree(
        source,
        output,
        (".json",),
        lambda name: name[:-5] + ".rton" if name.lower().endswith(".json") else name + ".rton",
        TransformAction.ENCODE,
        jobs=jobs,
        verbose=verbose,
    )


def decrypt_and_decode_rton_files(
    source: PathLike,
    rton_output: PathLike,
    json_output: PathLike,
    *,
    jobs: int | None = None,
    verbose: bool = False,
) -> int:
    """一次读取同时生成 RTON 和 JSON 两层，避免重复遍历与读取。"""
    source_root = Path(source).expanduser()
    rton_root = Path(rton_output).expanduser()
    json_root = Path(json_output).expanduser()
    if not source_root.exists():
        raise FileNotFoundError(f"输入不存在：{source_root}")

    files = _source_files(source_root)
    if not files:
        raise FileNotFoundError(f"{source_root} 中没有文件")

    transform_tasks: list[DecryptDecodeTask] = []
    copy_tasks: list[CopyPairTask] = []
    suffixes = (".rton", ".bin", ".dat")

    for source_file in files:
        relative = (
            Path(source_file.name)
            if source_root.is_file()
            else source_file.relative_to(source_root)
        )
        rton_path = rton_root if source_root.is_file() else rton_root / relative
        json_fallback = json_root if source_root.is_file() else json_root / relative
        if source_file.name.lower().endswith(suffixes):
            json_name = (
                relative.name[:-5] + ".json"
                if relative.name.lower().endswith(".rton")
                else relative.name + ".json"
            )
            json_path = (
                json_root
                if source_root.is_file()
                else json_root / relative.with_name(json_name)
            )
            transform_tasks.append(
                DecryptDecodeTask(
                    source=source_file,
                    rton_path=rton_path,
                    json_path=json_path,
                    rton_fallback=rton_path,
                    json_fallback=json_fallback,
                )
            )
        else:
            copy_tasks.append(CopyPairTask(source_file, rton_path, json_fallback))

    worker_count = recommended_jobs(jobs)
    converted = 0
    failed = 0

    if worker_count == 1 or len(transform_tasks) < 2:
        transform_results = map(_decrypt_decode_one, transform_tasks)
        for result in transform_results:
            converted += result.status == "converted"
            failed += result.status != "converted"
            if verbose:
                label = "转换" if result.status == "converted" else "保留"
                detail = "" if not result.error else f"（转换失败：{result.error}）"
                print(f"{label}：{result.destination}{detail}")
    else:
        chunk = max(1, len(transform_tasks) // (worker_count * 8))
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            for result in executor.map(_decrypt_decode_one, transform_tasks, chunksize=chunk):
                converted += result.status == "converted"
                failed += result.status != "converted"
                if verbose:
                    label = "转换" if result.status == "converted" else "保留"
                    detail = "" if not result.error else f"（转换失败：{result.error}）"
                    print(f"{label}：{result.destination}{detail}")

    clone_count = 0
    copy_count = 0
    if worker_count == 1 or len(copy_tasks) < 2:
        copy_results = map(_copy_pair, copy_tasks)
        for cloned, copied in copy_results:
            clone_count += cloned
            copy_count += copied
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for cloned, copied in executor.map(_copy_pair, copy_tasks):
                clone_count += cloned
                copy_count += copied

    print(
        f"完成：一次生成 RTON 和 JSON，转换 {converted} 个，"
        f"原样保留 {failed + len(copy_tasks)} 个（并发 {worker_count}）"
    )
    return converted + failed + len(copy_tasks)


