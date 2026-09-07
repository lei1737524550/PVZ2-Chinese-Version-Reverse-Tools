"""最终 RSB 中 JSON 修改的回读验证。"""

from __future__ import annotations

import json
import mmap
from pathlib import Path

from core.rsb_format import iter_rsb_rsg_files
from core.rsg_format import rsg_to_internal_files
from core.rton_encryption import decrypt_rton
from core.rton_json_codec import rton_to_json_bytes
from infrastructure.files import PathLike, as_path, require_path


def verify_json_patches_in_rsb(
    rsb_file: PathLike,
    json_root: PathLike,
    json_files: tuple[Path, ...],
) -> int:
    """从最终 RSB 重新解出修改项，确认写入值与 JSON 输入相同。"""
    if not json_files:
        return 0

    rsb = require_path(as_path(rsb_file), "待验证 RSB", file=True)
    root = require_path(as_path(json_root), "JSON 输入", file=False).resolve()
    grouped: dict[str, list[tuple[Path, str]]] = {}
    for json_file in json_files:
        relative = json_file.resolve().relative_to(root)
        if len(relative.parts) < 2:
            raise ValueError(f"JSON 不在 RSG 分组目录中：{json_file}")
        group = relative.parts[0]
        internal_name = Path(*relative.parts[1:]).with_suffix(".RTON").as_posix()
        grouped.setdefault(group.casefold(), []).append((json_file, internal_name))

    needed_groups = set(grouped)
    selected_rsgs: dict[str, bytes] = {}
    with rsb.open("rb") as file, mmap.mmap(
        file.fileno(), 0, access=mmap.ACCESS_READ
    ) as data:
        for name, payload in iter_rsb_rsg_files(data, str(rsb)):
            group = (name[:-4] if name.lower().endswith(".rsg") else name).casefold()
            if group not in needed_groups:
                continue
            selected_rsgs[group] = payload
            if len(selected_rsgs) == len(needed_groups):
                break

    verified = 0
    for group, patches in grouped.items():
        rsg_data = selected_rsgs.get(group)
        if rsg_data is None:
            raise ValueError(f"最终 RSB 中找不到 JSON 对应的 RSG：{patches[0][0]}")

        wanted = frozenset(internal_name for _, internal_name in patches)
        extracted = rsg_to_internal_files(
            rsg_data,
            "stored",
            group,
            selected_names=wanted,
        )
        contents = {name.casefold(): payload for name, payload in extracted.items()}

        for json_file, internal_name in patches:
            stored = contents.get(internal_name.casefold())
            if stored is None:
                raise ValueError(f"最终 RSB 中找不到 JSON 对应的数据项：{json_file}")
            plain = (
                decrypt_rton(stored, str(json_file))
                if stored.startswith(b"\x10\x00")
                else stored
            )
            actual = json.loads(rton_to_json_bytes(plain, str(json_file)).decode("utf-8"))
            with json_file.open("r", encoding="utf-8-sig") as file:
                expected = json.load(file)
            if actual != expected:
                raise ValueError(f"最终 RSB 未写入 JSON 修改：{json_file}")
            verified += 1
    return verified
