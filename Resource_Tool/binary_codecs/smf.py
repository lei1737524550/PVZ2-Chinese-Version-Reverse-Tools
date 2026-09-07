"""SMF/RSLB 与原始 RSB 之间的编解码实现。"""

from __future__ import annotations

import hashlib
import lzma
import struct
from dataclasses import dataclass
from pathlib import Path

from config import SETTINGS
from domain.errors import FormatError
from domain.formats import RSB_MAGICS, RSLB_MAGIC

_SMF = SETTINGS.smf
RSLB_VERSION = _SMF.rslb_version
CHUNK_SIZE = _SMF.chunk_size
FIXED_HEADER_SIZE = _SMF.fixed_header_size
BASE_ENTRY_SIZE = _SMF.base_entry_size
LINK_SIZE = _SMF.link_size
KNOWN_SIZE_FIELD_STYLES = _SMF.known_size_field_styles
DEFAULT_SIZE_FIELD_STYLE = _SMF.default_size_field_style


@dataclass(frozen=True, slots=True)
class ChunkEntry:
    """SMF 数据块在容器中的定位与解压信息。"""

    data_offset: int
    compressed_size: int
    properties: bytes
    output_size: int


def _filters(properties: bytes) -> list[dict[str, int]]:
    if len(properties) != 5:
        raise FormatError("LZMA properties must contain exactly 5 bytes")

    first = properties[0]
    if first >= 9 * 5 * 5:
        raise FormatError(f"invalid LZMA property byte: 0x{first:02X}")

    lc = first % 9
    remainder = first // 9
    lp = remainder % 5
    pb = remainder // 5

    dictionary_size = int.from_bytes(properties[1:5], "little")
    if dictionary_size == 0:
        dictionary_size = 1

    return [{
        "id": lzma.FILTER_LZMA1,
        "dict_size": dictionary_size,
        "lc": lc,
        "lp": lp,
        "pb": pb,
    }]


def _properties(
    dictionary_size: int,
    lc: int = 3,
    lp: int = 0,
    pb: int = 2,
) -> bytes:
    first = (pb * 5 + lp) * 9 + lc
    return bytes((first,)) + dictionary_size.to_bytes(4, "little")


def _dictionary_size(data_size: int) -> int:
    # 已观察到的文件会把最后一个数据块的字典大小向上取整到 1 MiB。
    mib = 0x100000
    return max(
        mib,
        min(CHUNK_SIZE, (data_size + mib - 1) // mib * mib),
    )


def _decompress_raw(
    data: bytes,
    properties: bytes,
    expected_size: int,
) -> bytes:
    """解码一个原始 LZMA 数据块。

    官方数据流可能省略结束标记，而 Python 生成的数据流通常会包含该标记。
    因此，只要实际输出大小与声明值完全一致，即使 eof=False 也不视为错误。
    """
    decoder = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=_filters(properties),
    )

    try:
        result = decoder.decompress(data, max_length=expected_size)
    except lzma.LZMAError as exc:
        raise FormatError(f"Raw-LZMA decompression failed: {exc}") from exc

    if len(result) != expected_size:
        raise FormatError(
            f"chunk size mismatch: expected {expected_size}, got {len(result)}"
        )

    return result


def _accepted_repeated_size(
    repeated_size: int,
    total_size: int,
    nominal_chunk_size: int,
) -> bool:
    """兼容头字段 0x28 已知的两种含义。"""
    return repeated_size in (total_size, nominal_chunk_size)


def _parse_smf(blob: bytes) -> tuple[int, int, int, list[ChunkEntry], str]:
    if len(blob) < FIXED_HEADER_SIZE:
        raise FormatError("truncated RSLB header")
    if blob[:4] != RSLB_MAGIC:
        raise FormatError("input is not an RSLB SMF file")

    version = struct.unpack_from("<I", blob, 4)[0]
    if version != RSLB_VERSION:
        raise FormatError(f"unsupported RSLB version: {version}")

    total_size = struct.unpack_from("<Q", blob, 0x08)[0]
    stored_file_size_minus_0x20 = struct.unpack_from("<Q", blob, 0x10)[0]
    nominal_chunk_size, chunk_count = struct.unpack_from("<II", blob, 0x18)
    reserved = struct.unpack_from("<Q", blob, 0x20)[0]
    repeated_size = struct.unpack_from("<Q", blob, 0x28)[0]

    if total_size <= 0:
        raise FormatError("invalid RSLB total output size")
    if nominal_chunk_size <= 0:
        raise FormatError("invalid RSLB nominal chunk size")
    if chunk_count <= 0:
        raise FormatError("invalid RSLB chunk count")

    # 已知样本在头部 +0x10 处均保存 文件大小 - 0x20。
    # 非零时执行校验；为扩大兼容范围，也允许该字段为零。
    expected_file_size_minus_0x20 = len(blob) - 0x20
    if (
        stored_file_size_minus_0x20 != 0
        and stored_file_size_minus_0x20 != expected_file_size_minus_0x20
    ):
        raise FormatError(
            "RSLB file-size field disagrees with actual file size: "
            f"header={stored_file_size_minus_0x20}, "
            f"actual={expected_file_size_minus_0x20}"
        )

    # 已知样本中的 0x20 字段均为零，但不要拒绝非零值：
    # 该字段属于保留或未知用途，不能据此认定文件损坏。
    _ = reserved

    if not _accepted_repeated_size(
        repeated_size,
        total_size,
        nominal_chunk_size,
    ):
        raise FormatError(
            "unsupported RSLB size-field variant at 0x28: "
            f"{repeated_size} "
            f"(expected total size {total_size} or chunk size "
            f"{nominal_chunk_size})"
        )

    size_field_style = (
        "total" if repeated_size == total_size else "chunk"
    )

    cursor = FIXED_HEADER_SIZE
    produced = 0
    chunks: list[ChunkEntry] = []

    for index in range(chunk_count):
        if cursor + BASE_ENTRY_SIZE > len(blob):
            raise FormatError("truncated RSLB chunk table")

        data_offset, compressed_size = struct.unpack_from("<QI", blob, cursor)
        properties = blob[cursor + 12:cursor + 17]
        padding = blob[cursor + 17:cursor + 20]
        cursor += BASE_ENTRY_SIZE

        if compressed_size < 5:
            raise FormatError(
                f"chunk {index}: compressed payload is smaller than "
                "the 5-byte LZMA property prefix"
            )

        if padding != b"\0\0\0":
            raise FormatError(
                f"chunk {index}: invalid RSLB chunk-table padding"
            )

        # 如果存在明确的链接边界，则优先使用它；这种方式更加稳健，
        # 不应假定除最后一块外的每个数据块都恰好等于 nominal_chunk_size。
        if index < chunk_count - 1:
            if cursor + LINK_SIZE > len(blob):
                raise FormatError("truncated RSLB chunk link")

            current_end, next_size = struct.unpack_from("<QQ", blob, cursor)
            cursor += LINK_SIZE

            if current_end <= produced or current_end > total_size:
                raise FormatError(
                    f"chunk {index}: invalid uncompressed end boundary "
                    f"{current_end}"
                )

            output_size = current_end - produced

            if next_size <= 0 or current_end + next_size > total_size:
                raise FormatError(
                    f"chunk {index}: invalid declared next-chunk size "
                    f"{next_size}"
                )
        else:
            output_size = total_size - produced

        if output_size <= 0:
            raise FormatError(
                f"chunk {index}: invalid output size {output_size}"
            )

        end = data_offset + compressed_size
        if data_offset < cursor:
            raise FormatError(
                f"chunk {index}: compressed payload overlaps the chunk table"
            )
        if end > len(blob):
            raise FormatError(
                f"chunk {index}: compressed payload lies outside the file"
            )

        # 每个数据载荷都以相同的 5 字节属性开头，这些属性同时
        # 保存在数据块表条目中。
        stored_properties = blob[data_offset:data_offset + 5]
        if stored_properties != properties:
            raise FormatError(
                f"chunk {index}: chunk-table and payload LZMA properties differ"
            )

        chunks.append(ChunkEntry(
            data_offset=data_offset,
            compressed_size=compressed_size,
            properties=properties,
            output_size=output_size,
        ))
        produced += output_size

    if produced != total_size:
        raise FormatError(
            "RSLB chunks do not cover the declared output size: "
            f"{produced} != {total_size}"
        )

    # 第一段载荷必须从完整数据块表结束位置或其后开始。
    # 允许存在间隙，但不允许发生重叠。
    if chunks and chunks[0].data_offset < cursor:
        raise FormatError("first compressed payload overlaps RSLB metadata")

    return total_size, nominal_chunk_size, repeated_size, chunks, size_field_style


def smf_to_rsb(source: Path, destination: Path) -> None:
    blob = source.read_bytes()
    _, _, _, chunks, _ = _parse_smf(blob)

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with destination.open("wb") as output:
            for index, entry in enumerate(chunks):
                # compressed_size 包含重复保存的 5 字节属性。
                compressed = blob[
                    entry.data_offset + 5:
                    entry.data_offset + entry.compressed_size
                ]
                raw = _decompress_raw(
                    compressed,
                    entry.properties,
                    entry.output_size,
                )
                output.write(raw)

        with destination.open("rb") as result:
            magic = result.read(4)

        if magic not in RSB_MAGICS:
            raise FormatError(
                f"decompressed data does not have an RSB magic: {magic!r}"
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def rsb_to_smf(
    source: Path,
    destination: Path,
    write_tag: bool = True,
    *,
    size_field_style: str = DEFAULT_SIZE_FIELD_STYLE,
) -> Path | None:
    """将 RSB 打包为 RSLB SMF。

    size_field_style 参数：
        "total"  -> 头部 +0x28 保存完整未压缩 RSB 大小，保持旧工具的输出行为。
        "chunk"  -> 头部 +0x28 保存标称数据块大小，与已提供的官方风格 SMF 样本一致。
        "auto"   -> 当前对新生成文件等同于 "chunk"。
    """
    if size_field_style not in KNOWN_SIZE_FIELD_STYLES:
        raise ValueError(
            f"size_field_style must be one of {KNOWN_SIZE_FIELD_STYLES}"
        )

    data = source.read_bytes()
    if len(data) < 4 or data[:4] not in RSB_MAGICS:
        raise FormatError("input is not an RSB (1bsr/rsb1) file")

    raw_chunks = [
        data[i:i + CHUNK_SIZE]
        for i in range(0, len(data), CHUNK_SIZE)
    ]

    entries: list[tuple[bytes, bytes]] = []

    for raw in raw_chunks:
        dictionary_size = _dictionary_size(len(raw))
        properties = _properties(dictionary_size)
        filters = _filters(properties)
        filters[0].update({
            "mode": lzma.MODE_NORMAL,
            "nice_len": 64,
            "mf": lzma.MF_BT4,
        })

        compressed = lzma.compress(
            raw,
            format=lzma.FORMAT_RAW,
            filters=filters,
        )

        # 在 RSLB 中，compressed_size 包含属性和原始 LZMA 数据。
        payload = properties + compressed
        entries.append((properties, payload))

    chunk_count = len(entries)

    table_size = sum(
        BASE_ENTRY_SIZE + (LINK_SIZE if i < chunk_count - 1 else 0)
        for i in range(chunk_count)
    )

    data_offset = FIXED_HEADER_SIZE + table_size

    offsets: list[int] = []
    current_offset = data_offset
    for _, payload in entries:
        offsets.append(current_offset)
        current_offset += len(payload)

    if size_field_style == "auto":
        size_field_style = "chunk"

    field_0x28 = (
        len(data)
        if size_field_style == "total"
        else CHUNK_SIZE
    )

    # 头部 +0x10 保存完整 SMF 文件大小减去 0x20 后的值。
    header = bytearray(FIXED_HEADER_SIZE)
    struct.pack_into(
        "<4sIQQIIQQ",
        header,
        0,
        RSLB_MAGIC,
        RSLB_VERSION,
        len(data),
        current_offset - 0x20,
        CHUNK_SIZE,
        chunk_count,
        0,
        field_0x28,
    )

    table = bytearray()
    produced = 0

    for index, ((properties, payload), offset) in enumerate(
        zip(entries, offsets)
    ):
        table += struct.pack("<QI", offset, len(payload))
        table += properties + b"\0\0\0"

        produced += len(raw_chunks[index])

        if index < chunk_count - 1:
            table += struct.pack(
                "<QQ",
                produced,
                len(raw_chunks[index + 1]),
            )

    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("wb") as output:
        output.write(header)
        output.write(table)
        for _, payload in entries:
            output.write(payload)

    if not write_tag:
        return None

    tag_path = Path(str(destination).removesuffix(".smf") + ".tag.smf")
    digest = hashlib.md5(destination.read_bytes()).hexdigest().upper()
    tag_path.write_bytes(digest.encode("ascii") + b"\r\n")
    return tag_path


