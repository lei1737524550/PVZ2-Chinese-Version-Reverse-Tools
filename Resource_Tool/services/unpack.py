"""资源解包流程编排。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from converters import (
    decode_rton_files,
    decrypt_and_decode_rton_files,
    decrypt_rton_files,
    extract_internal_files,
    extract_rsg_files,
)
from domain.formats import (
    FORMAT_NAMES,
    FORMAT_RANK,
    container_output_name,
    default_unpack_output,
    detect_format,
    normalize_format,
    read_head,
    resource_level,
    single_file_output,
    validate_forced_format,
)
from project.index import StageRecord, build_stage_record, write_index
from binary_codecs.smf import smf_to_rsb


@dataclass(frozen=True, slots=True)
class UnpackRequest:
    """一次解包任务的完整输入。"""

    source: Path
    target_format: str
    output_root: Path
    source_format: str
    jobs: int | None = None
    verbose: bool = False


_UNPACK_STEPS = {
    1: extract_rsg_files,
    2: extract_internal_files,
    3: decrypt_rton_files,
    4: decode_rton_files,
}


def _copy_rsb_representation(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _collect_smf_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        try:
            if read_head(item, 4) == b"RSLB":
                files.append(item)
        except OSError:
            continue
    return files


def _prepare_request(
    source: str | Path,
    target_level: str,
    output: str | Path | None,
    source_level: str | None,
    jobs: int | None,
    verbose: bool,
) -> UnpackRequest:
    current = Path(source).expanduser()
    if not current.exists():
        raise FileNotFoundError(f"输入不存在：{current}")

    source_format = normalize_format(source_level) if source_level else detect_format(current)
    if source_level:
        validate_forced_format(current, source_format)

    target_format = normalize_format(target_level)
    source_rank = FORMAT_RANK[source_format]
    target_rank = FORMAT_RANK[target_format]
    same_rsb_representation = (
        source_rank == target_rank == 1
        and source_format != target_format
        and {source_format, target_format} <= {"rsb", "rsbx"}
    )
    if target_rank <= source_rank and not same_rsb_representation:
        raise ValueError("解包目标必须位于输入格式的右侧；RSB/RSBX 仅允许同级改名")

    output_root = Path(output).expanduser() if output else default_unpack_output(current)
    return UnpackRequest(
        source=current,
        target_format=target_format,
        output_root=output_root,
        source_format=source_format,
        jobs=jobs,
        verbose=verbose,
    )


def _unpack_smf_layer(
    request: UnpackRequest,
    current: Path,
    sequence: int,
    target_rank: int,
    project_root: Path,
) -> tuple[Path, StageRecord]:
    stage_dir = request.output_root / f"{sequence:02d}_RSB"
    stage_dir.mkdir(parents=True, exist_ok=True)
    representation = (
        request.target_format
        if target_rank == 1 and request.target_format in {"rsb", "rsbx"}
        else "rsb"
    )
    print(f"\n[{sequence}] SMF / RSLB → {FORMAT_NAMES[representation]}")

    if current.is_file():
        destination = stage_dir / container_output_name(current, representation)
        smf_to_rsb(current, destination)
    else:
        smf_files = _collect_smf_files(current)
        if not smf_files:
            raise FileNotFoundError(f"目录中没有 RSLB SMF：{current}")
        for item in smf_files:
            relative_parent = item.relative_to(current).parent
            target = stage_dir / relative_parent / container_output_name(item, representation)
            smf_to_rsb(item, target)
            if request.verbose:
                print(f"生成：{target}")
        destination = stage_dir
        print(f"完成：SMF -> RSB 共 {len(smf_files)} 个文件")

    record = build_stage_record(
        project_root,
        sequence,
        "rsb",
        FORMAT_NAMES[representation],
        destination.resolve(),
        record_files=target_rank == 1,
    )
    return destination, record


def unpack(
    source: str | Path,
    target_level: str,
    output: str | Path | None = None,
    source_level: str | None = None,
    jobs: int | None = None,
    verbose: bool = False,
) -> Path:
    """按资源层级连续解包，并生成工程索引。"""
    request = _prepare_request(source, target_level, output, source_level, jobs, verbose)
    request.output_root.mkdir(parents=True, exist_ok=True)

    current = request.source
    source_rank = FORMAT_RANK[request.source_format]
    target_rank = FORMAT_RANK[request.target_format]
    project_root = request.output_root.resolve()
    original_source = current.resolve()
    stage_records: list[StageRecord] = []

    print(f"识别输入：{FORMAT_NAMES[request.source_format]}")
    print(f"目标格式：{FORMAT_NAMES[request.target_format]}")

    same_rsb_representation = (
        source_rank == target_rank == 1
        and request.source_format != request.target_format
        and {request.source_format, request.target_format} <= {"rsb", "rsbx"}
    )
    if same_rsb_representation:
        stage_dir = request.output_root / "01_RSB"
        stage_dir.mkdir(parents=True, exist_ok=True)
        destination = stage_dir / container_output_name(current, request.target_format)
        _copy_rsb_representation(current, destination)
        stage_records.append(
            build_stage_record(
                project_root,
                1,
                "rsb",
                FORMAT_NAMES[request.target_format],
                destination.resolve(),
                record_files=True,
            )
        )
        index = write_index(project_root, original_source, request.source_format, stage_records)
        print(f"\n完成：{destination}")
        print(f"工程索引：{index}")
        return destination

    sequence = 1
    step_rank = source_rank

    if source_rank == 0:
        current, record = _unpack_smf_layer(request, current, sequence, target_rank, project_root)
        stage_records.append(record)
        sequence += 1
        step_rank = 1
        if target_rank == 1:
            index = write_index(project_root, original_source, request.source_format, stage_records)
            print(f"\n完成：{current}")
            print(f"工程索引：{index}")
            return current

    while step_rank < target_rank:
        next_rank = step_rank + 1
        next_level = resource_level(next_rank)
        stage_dir = request.output_root / f"{sequence:02d}_{next_level.folder}"
        destination = (
            single_file_output(current, stage_dir, next_rank)
            if current.is_file() and next_rank in {4, 5}
            else stage_dir
        )

        print(f"\n[{sequence}] {resource_level(step_rank).name} → {next_level.name}")

        if step_rank == 3 and target_rank >= 5:
            rton_destination = destination
            json_stage = request.output_root / f"{sequence + 1:02d}_JSON"
            json_destination = (
                single_file_output(rton_destination, json_stage, 5)
                if current.is_file()
                else json_stage
            )
            print(f"[{sequence + 1}] .rton → .json（合并处理）")
            decrypt_and_decode_rton_files(
                current,
                rton_destination,
                json_destination,
                jobs=request.jobs,
                verbose=request.verbose,
            )
            stage_records.append(
                build_stage_record(project_root, sequence, "rton", ".rton", rton_destination.resolve())
            )
            stage_records.append(
                build_stage_record(
                    project_root,
                    sequence + 1,
                    "json",
                    ".json",
                    json_destination.resolve(),
                    record_files=True,
                )
            )
            current = json_destination
            sequence += 2
            step_rank = 5
            continue

        converter = _UNPACK_STEPS.get(step_rank)
        if converter is None:
            raise ValueError(f"没有定义解包转换：rank {step_rank} -> {next_rank}")
        converter(current, destination, jobs=request.jobs, verbose=request.verbose)
        stage_records.append(
            build_stage_record(
                project_root,
                sequence,
                next_level.id,
                next_level.name,
                destination.resolve(),
                record_files=next_rank == target_rank,
            )
        )
        current = destination
        sequence += 1
        step_rank = next_rank

    index = write_index(project_root, original_source, request.source_format, stage_records)
    print(f"\n完成：{current}")
    print(f"工程索引：{index}")
    return current
