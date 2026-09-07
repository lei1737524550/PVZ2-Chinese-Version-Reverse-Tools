"""原始 RSB 容器的子组表解析与 RSG 写回。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from struct import pack, unpack_from

from .container_common import RSB_MAGIC, RSG_MAGIC, matches, pad4096
from .conversion_settings import RSG_NAME_PREFIXES, RSG_NAME_SUFFIXES


@dataclass(frozen=True, slots=True)
class RsbSubgroup:
    """RSB 子组在容器中的定位信息。"""

    name: str
    offset: int
    size: int
    info_start: int


def _read_rsb_subgroups(data: bytes) -> list[RsbSubgroup]:
    if data[:4] != RSB_MAGIC:
        raise ValueError("expected 1bsr header")
    subgroup_count = unpack_from("<I", data, 40)[0]
    subgroup_info_offset = unpack_from("<I", data, 44)[0]
    subgroup_info_entry_size = unpack_from("<I", data, 48)[0]

    # 提取子包时不需要其余头字段，因此直接定位到表区域，
    # 无需逐项解析无关头字段。
    if subgroup_info_entry_size < 176:
        raise ValueError(f"unsupported RSB subgroup entry size: {subgroup_info_entry_size}")

    out: list[RsbSubgroup] = []
    for index in range(subgroup_count):
        info_start = subgroup_info_offset + index * subgroup_info_entry_size
        name = bytes(data[info_start:info_start + 128]).split(b"\0", 1)[0].decode("utf-8")
        rsg_offset, rsg_size_field = unpack_from("<II", data, info_start + 128)
        image_data_offset, compressed_image_data_size = unpack_from("<II", data, info_start + 164)
        # 表中的总长度是 RSB 对该子包边界的权威记录。旧逻辑只用
        # image_data_offset + compressed_image_data_size 推算；无图片区、额外尾部
        # 或某些对齐布局会因此被截断。仅在异常的零值表项上才回退到推算值。
        rsg_size = rsg_size_field or (image_data_offset + compressed_image_data_size)
        if rsg_offset + rsg_size > len(data):
            raise ValueError(
                f"RSB subgroup {name!r} exceeds container boundary: "
                f"offset={rsg_offset}, size={rsg_size}, container={len(data)}"
            )
        out.append(RsbSubgroup(name, rsg_offset, rsg_size, info_start))
    return out


def iter_rsb_rsg_files(data, source: str = "RSB"):
    """逐个产生 RSG，避免同时在内存中保留整个 RSB 和全部子包。"""
    if data[:4] != RSB_MAGIC:
        raise ValueError(f"{source}: expected 1bsr header")
    for item in _read_rsb_subgroups(data):
        if not matches(item.name, RSG_NAME_PREFIXES, RSG_NAME_SUFFIXES):
            continue
        sub = bytearray(data[item.offset:item.offset + item.size])
        if len(sub) < 52:
            raise ValueError(f"{source}:{item.name}: truncated RSG")
        sub[:4] = RSG_MAGIC
        sub[16:36] = data[item.info_start + 140:item.info_start + 160]
        sub[40:52] = data[item.info_start + 164:item.info_start + 176]
        yield item.name + ".rsg", bytes(sub)




def patch_rsb_rsgs(base_data: bytes, patch_root: Path, *, verbose: bool = False) -> bytes:
    if not base_data.startswith(RSB_MAGIC):
        raise ValueError("expected 1bsr header")
    out = bytearray(base_data)
    subgroups = sorted(_read_rsb_subgroups(base_data), key=lambda x: x.offset)
    shift = 0
    for item in subgroups:
        new_offset = shift + item.offset
        if matches(item.name, RSG_NAME_PREFIXES, RSG_NAME_SUFFIXES):
            patch_path = patch_root / (item.name + ".rsg")
            if patch_path.is_file():
                sub = bytearray(patch_path.read_bytes())
                if not sub.startswith(RSG_MAGIC):
                    raise ValueError(f"{patch_path}: expected pgsr header")
                original_view = bytearray(base_data[item.offset:item.offset + item.size])
                original_view[:4] = RSG_MAGIC
                original_view[16:36] = base_data[item.info_start + 140:item.info_start + 160]
                original_view[40:52] = base_data[item.info_start + 164:item.info_start + 176]
                if bytes(sub) == bytes(original_view):
                    if verbose:
                        print(f"kept original {patch_path}")
                    out[item.info_start + 128:item.info_start + 132] = pack("<I", new_offset)
                    continue

                # 某些 PvZ 版本会把嵌入式 RSG 头部最后
                # 12 字节作为水印或保留字段（例如
                # ``zuozheqq:777``），而真正有效的数值
                # 位于 RSB 子组表中，因此应保留这 12 字节。
                table_fields = sub[16:36] + sub[32:36] + sub[40:52]
                sub[40:52] = base_data[item.offset + 40:item.offset + 52]
                sub += pad4096(len(sub))
                out[new_offset:new_offset + item.size] = sub
                out[item.info_start + 132:item.info_start + 136] = pack("<I", len(sub))
                out[item.info_start + 140:item.info_start + 176] = table_fields
                shift += len(sub) - item.size
                if verbose:
                    print(f"patched {patch_path}")
        out[item.info_start + 128:item.info_start + 132] = pack("<I", new_offset)
    return bytes(out)


