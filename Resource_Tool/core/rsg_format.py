"""RSG 容器头、条目表、数据区与补丁写回。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from struct import pack, unpack
from zlib import compress, decompress

from .container_common import RSG_MAGIC, matches, pad4096, read_u32
from .conversion_settings import INTERNAL_PATH_PREFIXES, INTERNAL_PATH_SUFFIXES
from .rton_encryption import decrypt_rton, encrypt_rton
from .rton_json_codec import json_to_rton_bytes, rton_to_json_bytes


@dataclass(frozen=True, slots=True)
class RsgEntry:
    """RSG 内部文件条目。"""

    name: str
    is_image: bool
    offset: int
    size: int
    info_end: int


def _rsg_header(data: bytes) -> dict[str, int]:
    fp = BytesIO(data)
    if fp.read(4) != RSG_MAGIC:
        raise ValueError("expected pgsr header")
    version = read_u32(fp)
    fp.seek(8, 1)
    compression_flags = read_u32(fp)
    header_length = read_u32(fp)
    data_offset = read_u32(fp)
    compressed_data_size = read_u32(fp)
    decompressed_data_size = read_u32(fp)
    fp.seek(4, 1)
    image_data_offset = read_u32(fp)
    compressed_image_data_size = read_u32(fp)
    decompressed_image_data_size = read_u32(fp)
    fp.seek(20, 1)
    info_size = read_u32(fp)
    info_offset = read_u32(fp)
    return {
        "version": version,
        "compression_flags": compression_flags,
        "header_length": header_length,
        "data_offset": data_offset,
        "compressed_data_size": compressed_data_size,
        "decompressed_data_size": decompressed_data_size,
        "image_data_offset": image_data_offset,
        "compressed_image_data_size": compressed_image_data_size,
        "decompressed_image_data_size": decompressed_image_data_size,
        "info_size": info_size,
        "info_offset": info_offset,
    }


def _inflate_rsg_sections(data: bytes) -> tuple[dict[str, int], bytearray | None, bytearray | None]:
    h = _rsg_header(data)
    flags = h["compression_flags"]

    for offset_name, size_name in (
        ("data_offset", "compressed_data_size"),
        ("image_data_offset", "compressed_image_data_size"),
    ):
        start = h[offset_name]
        size = h[size_name]
        if size and (start < h["header_length"] or start + size > len(data)):
            raise ValueError(
                f"RSG section outside container: {offset_name}={start}, "
                f"{size_name}={size}, container={len(data)}"
            )

    raw_data: bytearray | None = None
    if flags & 2 == 0:
        raw_data = bytearray(data[h["data_offset"]:h["data_offset"] + h["compressed_data_size"]])
    elif h["compressed_data_size"]:
        raw_data = bytearray(decompress(data[h["data_offset"]:h["data_offset"] + h["compressed_data_size"]]))

    raw_images: bytearray | None = None
    if h["decompressed_image_data_size"]:
        if flags & 1 == 0:
            raw_images = bytearray(data[h["image_data_offset"]:h["image_data_offset"] + h["compressed_image_data_size"]])
        else:
            raw_images = bytearray(decompress(data[h["image_data_offset"]:h["image_data_offset"] + h["compressed_image_data_size"]]))
    return h, raw_data, raw_images


def _read_rsg_entries(data: bytes) -> list[RsgEntry]:
    h = _rsg_header(data)
    fp = BytesIO(data)
    info_limit = h["info_offset"] + h["info_size"]
    fp.seek(h["info_offset"])
    name_dict: dict[bytes, int] = {}
    entries: list[RsgEntry] = []
    temp = h["info_offset"]
    while temp < info_limit:
        file_name = b""
        for key in list(name_dict.keys()):
            if name_dict[key] + h["info_offset"] < temp:
                name_dict.pop(key)
            else:
                file_name = key
        byte = b""
        while byte != b"\0":
            file_name += byte
            byte = fp.read(1)
            if len(byte) != 1:
                raise EOFError("unexpected EOF in RSG filename table")
            length_raw = fp.read(3)
            if len(length_raw) != 3:
                raise EOFError("unexpected EOF in RSG filename table")
            length = 4 * unpack("<I", length_raw + b"\0")[0]
            if length:
                name_dict[file_name] = length

        name = file_name.decode("utf-8").replace("\\", "/")
        is_image = read_u32(fp) == 1
        offset = read_u32(fp)
        size = read_u32(fp)
        if is_image:
            fp.seek(20, 1)
        temp = fp.tell()
        if name:
            entries.append(RsgEntry(name, is_image, offset, size, temp))
    return entries




def rsg_to_internal_files(
    data: bytes,
    mode: str = "stored",
    source: str = "RSG",
    *,
    selected_names: frozenset[str] | None = None,
) -> dict[str, bytes]:
    if mode not in {"stored", "rton", "json"}:
        raise ValueError("mode must be stored, rton, or json")
    h, raw_data, raw_images = _inflate_rsg_sections(data)
    result: dict[str, bytes] = {}
    wanted = {name.casefold() for name in selected_names} if selected_names else None
    for entry in _read_rsg_entries(data):
        if wanted is not None and entry.name.casefold() not in wanted:
            continue
        if not matches(entry.name, INTERNAL_PATH_PREFIXES, INTERNAL_PATH_SUFFIXES):
            continue
        section = raw_images if entry.is_image else raw_data
        if section is None:
            continue
        payload = bytes(section[entry.offset:entry.offset + entry.size])
        if entry.offset + entry.size > len(section):
            raise ValueError(
                f"{source}:{entry.name}: file range exceeds its RSG section"
            )
        out_name = entry.name
        if mode in {"rton", "json"} and entry.name.lower().endswith(".rton"):
            payload = decrypt_rton(payload, f"{source}:{entry.name}") if payload.startswith(b"\x10\x00") else payload
        if mode == "json" and entry.name.lower().endswith(".rton"):
            payload = rton_to_json_bytes(payload, f"{source}:{entry.name}")
            out_name = entry.name[:-5] + ".json"
        result[out_name] = payload
    return result


def _find_patch_file(patch_root: Path, internal_name: str, mode: str) -> Path | None:
    rel = Path(*internal_name.replace("\\", "/").split("/"))
    if mode == "json" and internal_name.lower().endswith(".rton"):
        rel = rel.with_suffix(".json")
    path = patch_root / rel
    if not path.is_file():
        # RSG 内部通常使用大写 .RTON，而 JSON 转换器输出小写 .rton。
        # Android/Windows 可能掩盖问题，Linux/Termux 会把它们视为不同文件。
        # 逐级使用 casefold 进行不区分大小写匹配，既保留原始目录结构，也避免静默忽略修改。
        current = patch_root
        for part in rel.parts:
            if not current.is_dir():
                return None
            candidates = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
            if len(candidates) > 1:
                raise ValueError(f"补丁路径存在大小写冲突：{current / part}")
            if not candidates:
                return None
            current = candidates[0]
        path = current
    if not path.is_file():
        return None
    return path




def patch_rsg_internal_files(
    base_data: bytes,
    patch_root: Path,
    mode: str,
    preserve_encryption: bool = True,
    force_encryption: bool | None = None,
    compress_data_override: bool | None = None,
    compress_image_override: bool | None = None,
    known_unchanged: frozenset[str] = frozenset(),
    verbose: bool = False,
) -> bytes:
    """把修改后的内部文件写回现有 RSG。

    mode 参数：
      stored -> 按输入内容原样写入字节
      rton   -> 写入明文 RTON；除非显式覆盖，否则沿用原文件加密状态
      json   -> 先把 JSON 编码为 RTON；除非显式覆盖，否则沿用原文件加密状态
    """
    if mode not in {"stored", "rton", "json"}:
        raise ValueError("mode must be stored, rton, or json")

    h, raw_data, raw_images = _inflate_rsg_sections(base_data)
    out = bytearray(base_data)
    entries = _read_rsg_entries(base_data)

    def patch_section(section: bytearray | None, image: bool) -> bytearray | None:
        if section is None:
            return None
        original_length = len(section)
        chosen = [e for e in entries if e.is_image == image]
        sentinel = RsgEntry("", image, len(section), 0, 0)
        chosen_plus = sorted(chosen + [sentinel], key=lambda e: e.offset)
        shift = 0
        current: RsgEntry | None = None
        current_offset = 0
        for nxt in chosen_plus:
            next_offset = shift + nxt.offset
            if current is not None:
                file_offset = current_offset
                file_info = current.info_end
                if matches(current.name, INTERNAL_PATH_PREFIXES, INTERNAL_PATH_SUFFIXES):
                    patch_path = _find_patch_file(patch_root, current.name, mode)
                    if patch_path is not None:
                        original = bytes(section[file_offset:file_offset + current.size])
                        indexed_unchanged = str(patch_path.resolve()) in known_unchanged
                        if indexed_unchanged:
                            reuse_original = True
                            payload = original
                        else:
                            payload = patch_path.read_bytes()
                            if mode == "json" and current.name.lower().endswith(".rton"):
                                payload = json_to_rton_bytes(payload, str(patch_path))
                        # 所有未修改条目（不仅是 RTON）都必须保持在原来的
                        # 数据槽位中。若把较小的 INI/TXT 替换为
                        # ``载荷 + 4096 字节填充``，会使紧密排列的 RSG 异常膨胀。
                        if not indexed_unchanged:
                            reuse_original = payload == original
                        if not indexed_unchanged and mode in {"rton", "json"} and current.name.lower().endswith(".rton"):
                            # JSON 无法表达 RTON 的全部整数/字符串类型标签，因此即使
                            # JSON 文件未修改，重新编码后其二进制也可能发生变化，
                            # 即使可见数据完全相同。应与原条目的标准化视图比较，
                            # 若内容未变，则保留原始存储字节。
                            original_plain = (
                                decrypt_rton(original, f"base:{current.name}")
                                if original.startswith(b"\x10\x00")
                                else original
                            )
                            if mode == "json":
                                reuse_original = (
                                    patch_path.read_bytes()
                                    == rton_to_json_bytes(original_plain, f"base:{current.name}")
                                )
                            else:
                                reuse_original = patch_path.read_bytes() == original_plain

                            should_encrypt = force_encryption
                            if should_encrypt is None and preserve_encryption:
                                should_encrypt = original.startswith(b"\x10\x00")
                            if should_encrypt and not reuse_original:
                                payload = encrypt_rton(payload, str(patch_path))
                        if reuse_original:
                            if verbose:
                                print(f"保留原始字节：{patch_path}")
                        else:
                            size = len(payload)
                            # RSG 数据条目是连续排列的，只有
                            # 整个数据区需要按 4096 字节对齐；如果
                            # 给每个文件单独填充，会破坏后续偏移，
                            # 并导致大型资源包显著膨胀。
                            section[file_offset:file_offset + current.size] = payload
                            if image:
                                out[file_info - 24:file_info - 20] = pack("<I", size)
                            else:
                                out[file_info - 4:file_info] = pack("<I", size)
                            delta = size - current.size
                            shift += delta
                            next_offset += delta
                            if verbose:
                                print(f"写入修改：{patch_path}")
                if image:
                    out[file_info - 28:file_info - 24] = pack("<I", file_offset)
                else:
                    out[file_info - 8:file_info - 4] = pack("<I", file_offset)
            current_offset = next_offset
            current = nxt
        if chosen:
            # 扩大数据区前，优先使用现有尾部预留空间。
            # 某些资源包保留了超出最小对齐要求的空间，因此绝不能
            # 把数据区缩小到原始解压长度以下。
            logical_end = max(entry.offset + entry.size for entry in chosen) + shift
            aligned_end = (logical_end + 4095) & ~4095
            target_length = max(original_length, aligned_end)
            if len(section) > target_length:
                del section[target_length:]
            elif len(section) < target_length:
                section.extend(b"\0" * (target_length - len(section)))
        return section

    raw_data = patch_section(raw_data, False)
    raw_images = patch_section(raw_images, True)

    flags = h["compression_flags"]
    data_offset = h["data_offset"]
    original_image_offset = h["image_data_offset"]

    if raw_data is not None:
        if compress_data_override is not None:
            if compress_data_override:
                flags |= 2
            else:
                flags &= ~2
        raw_data += pad4096(len(raw_data))
        decompressed_size = len(raw_data)
        if flags & 2:
            packed_data = bytearray(compress(bytes(raw_data), 9))
            packed_data += pad4096(len(packed_data))
        else:
            packed_data = raw_data
        compressed_size = len(packed_data)
        out[data_offset:original_image_offset] = packed_data
        out[28:36] = pack("<II", compressed_size, decompressed_size)
        new_image_offset = data_offset + compressed_size
        out[40:44] = pack("<I", new_image_offset)
    else:
        new_image_offset = original_image_offset

    if raw_images is not None:
        if compress_image_override is not None:
            if compress_image_override:
                flags |= 1
            else:
                flags &= ~1
        raw_images += pad4096(len(raw_images))
        decompressed_image_size = len(raw_images)
        if flags & 1:
            packed_images = bytearray(compress(bytes(raw_images), 9))
            packed_images += pad4096(len(packed_images))
        else:
            packed_images = raw_images
        compressed_image_size = len(packed_images)
        out[new_image_offset:] = packed_images
        out[44:52] = pack("<II", compressed_image_size, decompressed_image_size)

    out[16:20] = pack("<I", flags)
    return bytes(out)




