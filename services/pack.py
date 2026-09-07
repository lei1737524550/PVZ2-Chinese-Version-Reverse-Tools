"""资源回包主流程。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from binary_codecs.smf import rsb_to_smf
from converters import (
    encode_json_files,
    encrypt_rton_files,
    rebuild_rsb,
    rebuild_rsg,
    rebuild_rsg_directory,
    verify_json_patches_in_rsb,
)
from domain.formats import FORMAT_NAMES, FORMAT_RANK, RANK_TO_FORMAT, RESOURCE_LEVELS, normalize_format
from project.index import unchanged_files_from_index
from project.layout import (
    ask_existing,
    container_kind,
    copy_rsb_representation,
    default_pack_output,
    detect_source_format,
    find_base_container,
    find_base_rsg,
    output_file,
    prepare_stage,
    project_base_name,
    project_root,
    raw_base_rsb,
    resolve_stage_source,
    validate_base_container,
    validate_changed_json,
)


@dataclass(frozen=True, slots=True)
class PackRequest:
    """一次回包任务的规范化输入。"""

    source: Path
    source_format: str
    target_format: str
    output_root: Path
    base_rsg: Path | None
    base_container: Path | None
    verify_roundtrip: bool
    jobs: int | None
    verbose: bool


def _prepare_request(
    source: str | Path,
    target_level: str,
    output: str | Path | None,
    source_level: str | None,
    base_rsg: str | Path | None,
    base_rsb: str | Path | None,
    verify_roundtrip: bool,
    jobs: int | None,
    verbose: bool,
) -> PackRequest:
    original_source = Path(source).expanduser()
    if not original_source.exists():
        raise FileNotFoundError(f"输入不存在：{original_source}")

    source_format = normalize_format(source_level) if source_level else detect_source_format(original_source)
    target_format = normalize_format(target_level)
    source_rank = FORMAT_RANK[source_format]
    target_rank = FORMAT_RANK[target_format]
    same_rsb_representation = (
        source_rank == target_rank == 1
        and source_format != target_format
        and {source_format, target_format} <= {"rsb", "rsbx"}
    )
    if target_rank >= source_rank and not same_rsb_representation:
        raise ValueError("打包目标必须位于输入格式的左侧；RSB/RSBX 仅允许同级改名")

    root = project_root(original_source)
    need_base_rsg = source_rank >= FORMAT_RANK["encrypted"] and target_rank <= FORMAT_RANK["rsg"]
    need_base_container = source_rank >= FORMAT_RANK["rsg"] and target_rank <= FORMAT_RANK["rsb"]

    if base_rsg is not None:
        base_rsg_path = Path(base_rsg).expanduser()
        if not base_rsg_path.exists():
            raise FileNotFoundError(f"基础 RSG 不存在：{base_rsg_path}")
    elif need_base_rsg:
        base_rsg_path = find_base_rsg(root)
    else:
        base_rsg_path = None

    if base_rsb is not None:
        base_container = Path(base_rsb).expanduser()
        validate_base_container(base_container)
    elif need_base_container:
        base_container = find_base_container(root)
    else:
        base_container = None

    return PackRequest(
        source=original_source,
        source_format=source_format,
        target_format=target_format,
        output_root=Path(output).expanduser() if output else default_pack_output(original_source),
        base_rsg=base_rsg_path,
        base_container=base_container,
        verify_roundtrip=verify_roundtrip,
        jobs=jobs,
        verbose=verbose,
    )


def _show_request(
    request: PackRequest,
    current: Path,
    known_unchanged: frozenset[str],
    changed_json_files: tuple[Path, ...],
) -> None:
    """输出本次回包任务摘要。"""
    print(f"识别输入：{FORMAT_NAMES[request.source_format]}")
    print(f"目标格式：{FORMAT_NAMES[request.target_format]}")
    if current != request.source:
        print(f"实际打包源：{current}")
    print(f"输出目录：{request.output_root}")
    if request.base_rsg is not None:
        print(f"基础 RSG：{request.base_rsg}")
    if request.base_container is not None:
        print(f"基础容器：{request.base_container} ({container_kind(request.base_container)})")
    if known_unchanged:
        print(f"索引确认未修改：{len(known_unchanged)} 个文件")
    if FORMAT_RANK[request.source_format] == FORMAT_RANK["json"]:
        print(f"JSON 数据输入：{current}")
        print(f"本次写入 JSON：{len(changed_json_files)} 个")




def _direct_patch_chain(
    request: PackRequest,
    patch_source: Path,
    known_unchanged: frozenset[str],
    changed_json_files: tuple[Path, ...],
    base_name: str,
    temp_dir: Path,
) -> Path:
    """JSON/RTON/加密 RTON 直接补丁到 RSG，并继续回到目标容器。"""
    source_rank = FORMAT_RANK[request.source_format]
    target_rank = FORMAT_RANK[request.target_format]
    base_rsg = request.base_rsg or ask_existing(
        "原始基础 RSG 文件或目录",
        allow_file=True,
        allow_dir=True,
    )

    rsg_stage = request.output_root / "01_RSG"
    prepare_stage(rsg_stage)
    mode = {
        FORMAT_RANK["encrypted"]: "stored",
        FORMAT_RANK["rton"]: "rton",
        FORMAT_RANK["json"]: "json",
    }[source_rank]
    print(f"\n[1] {FORMAT_NAMES[request.source_format]} → .rsg（直接回包）")

    if base_rsg.is_dir():
        current = rsg_stage
        rebuild_rsg_directory(
            base_rsg,
            patch_source,
            current,
            verify_unchanged=request.verify_roundtrip,
            mode=mode,
            known_unchanged=known_unchanged,
            jobs=request.jobs,
            verbose=request.verbose,
        )
    else:
        current = rsg_stage / base_rsg.name
        rebuild_rsg(
            base_rsg,
            patch_source,
            current,
            mode=mode,
            known_unchanged=known_unchanged,
            jobs=request.jobs,
            verbose=request.verbose,
        )

    if target_rank == FORMAT_RANK["rsg"]:
        print(f"\n完成：{current}")
        return current

    base_container = request.base_container or ask_existing(
        "原始基础 RSB 或 SMF",
        allow_file=True,
        allow_dir=False,
    )
    validate_base_container(base_container)
    raw_base = raw_base_rsb(base_container, temp_dir)

    rsb_stage = request.output_root / "02_RSB"
    prepare_stage(rsb_stage)
    raw_output_format = request.target_format if target_rank == 1 else "rsb"
    rsb_destination = output_file(rsb_stage, base_name, raw_output_format)
    print(f"\n[2] .rsg → {FORMAT_NAMES[raw_output_format]}")
    rebuild_rsb(
        raw_base,
        current,
        rsb_destination,
        jobs=request.jobs,
        verbose=request.verbose,
    )

    if source_rank == FORMAT_RANK["json"] and changed_json_files:
        verified = verify_json_patches_in_rsb(rsb_destination, patch_source, changed_json_files)
        print(f"最终 RSB 校验通过：{verified} 个 JSON 已真实写入")

    if target_rank == 1:
        print(f"\n完成：{rsb_destination}")
        return rsb_destination

    smf_stage = request.output_root / "03_SMF"
    prepare_stage(smf_stage)
    smf_destination = output_file(smf_stage, base_name, "smf")
    print("\n[3] RSB / 1bsr → SMF / RSLB")
    rsb_to_smf(rsb_destination, smf_destination)
    print(f"\n完成：{smf_destination}")
    return smf_destination


def _stepwise_chain(
    request: PackRequest,
    current: Path,
    known_unchanged: frozenset[str],
    base_name: str,
    temp_dir: Path,
) -> Path:
    """执行普通逐级回包流程。"""
    target_rank = FORMAT_RANK[request.target_format]
    current_rank = FORMAT_RANK[request.source_format]
    base_rsg = request.base_rsg
    base_container = request.base_container
    sequence = 0

    while current_rank > target_rank:
        sequence += 1
        next_rank = current_rank - 1
        current_fmt = RANK_TO_FORMAT[current_rank]
        next_fmt = RANK_TO_FORMAT[next_rank]
        display_next_fmt = request.target_format if next_rank == 1 and target_rank == 1 else next_fmt
        stage_dir = request.output_root / f"{sequence:02d}_{RESOURCE_LEVELS[next_rank].folder}"
        prepare_stage(stage_dir)
        print(f"\n[{sequence}] {FORMAT_NAMES[current_fmt]} → {FORMAT_NAMES[display_next_fmt]}")
        print(f"输入：{current}")
        print(f"输出：{stage_dir}")

        if current_rank == FORMAT_RANK["json"]:
            if current.is_file():
                name = current.name[:-5] + ".rton" if current.name.lower().endswith(".json") else current.name + ".rton"
                destination = stage_dir / name
            else:
                destination = stage_dir
            encode_json_files(current, destination, jobs=request.jobs, verbose=request.verbose)

        elif current_rank == FORMAT_RANK["rton"]:
            destination = stage_dir / current.name if current.is_file() else stage_dir
            encrypt_rton_files(current, destination, jobs=request.jobs, verbose=request.verbose)

        elif current_rank == FORMAT_RANK["encrypted"]:
            base_rsg = base_rsg or ask_existing(
                "原始基础 RSG 文件或目录",
                allow_file=True,
                allow_dir=True,
            )
            if base_rsg.is_dir():
                destination = stage_dir
                rebuild_rsg_directory(
                    base_rsg,
                    current,
                    destination,
                    verify_unchanged=request.verify_roundtrip,
                    mode="stored",
                    known_unchanged=known_unchanged,
                    jobs=request.jobs,
                    verbose=request.verbose,
                )
            else:
                destination = stage_dir / base_rsg.name
                rebuild_rsg(
                    base_rsg,
                    current,
                    destination,
                    mode="stored",
                    known_unchanged=known_unchanged,
                    jobs=request.jobs,
                    verbose=request.verbose,
                )

        elif current_rank == FORMAT_RANK["rsg"]:
            base_container = base_container or ask_existing(
                "原始基础 RSB 或 SMF",
                allow_file=True,
                allow_dir=False,
            )
            validate_base_container(base_container)
            raw_base = raw_base_rsb(base_container, temp_dir)
            output_fmt = request.target_format if next_rank == 1 and target_rank == 1 else "rsb"
            destination = output_file(stage_dir, base_name, output_fmt)
            rebuild_rsb(
                raw_base,
                current,
                destination,
                jobs=request.jobs,
                verbose=request.verbose,
            )

        elif current_rank == FORMAT_RANK["rsb"]:
            destination = output_file(stage_dir, base_name, "smf")
            rsb_to_smf(current, destination)

        else:
            raise ValueError(f"无效的打包等级：{current_rank}")

        current = destination
        current_rank = next_rank

    print(f"\n完成：{current}")
    return current


def pack(
    source: str | Path,
    target_level: str,
    output: str | Path | None = None,
    source_level: str | None = None,
    base_rsg: str | Path | None = None,
    base_rsb: str | Path | None = None,
    verify_roundtrip: bool = False,
    jobs: int | None = None,
    verbose: bool = False,
) -> Path:
    """按资源层级连续回包。"""
    request = _prepare_request(
        source,
        target_level,
        output,
        source_level,
        base_rsg,
        base_rsb,
        verify_roundtrip,
        jobs,
        verbose,
    )

    source_rank = FORMAT_RANK[request.source_format]
    target_rank = FORMAT_RANK[request.target_format]
    current = resolve_stage_source(request.source, source_rank)
    root = project_root(request.source)
    base_name = project_base_name(request.source)
    known_unchanged = unchanged_files_from_index(root, current)
    changed_json_files = (
        validate_changed_json(current, known_unchanged)
        if source_rank == FORMAT_RANK["json"]
        else ()
    )

    request.output_root.mkdir(parents=True, exist_ok=True)
    _show_request(request, current, known_unchanged, changed_json_files)

    same_rsb_representation = (
        source_rank == target_rank == 1
        and request.source_format != request.target_format
        and {request.source_format, request.target_format} <= {"rsb", "rsbx"}
    )
    if same_rsb_representation:
        stage_dir = request.output_root / "01_RSB"
        prepare_stage(stage_dir)
        destination = output_file(stage_dir, base_name, request.target_format)
        copy_rsb_representation(current, destination)
        print(f"\n完成：{destination}")
        return destination

    with tempfile.TemporaryDirectory(prefix="pvz_pack_base_") as temp_name:
        temp_dir = Path(temp_name)
        if source_rank >= FORMAT_RANK["encrypted"] and target_rank <= FORMAT_RANK["rsg"]:
            return _direct_patch_chain(
                request,
                current,
                known_unchanged,
                changed_json_files,
                base_name,
                temp_dir,
            )
        return _stepwise_chain(request, current, known_unchanged, base_name, temp_dir)
