"""资源格式定义、识别与命名规则。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ResourceLevel:
    """资源链中的一个语义层级。"""

    id: str
    flag: str
    name: str
    folder: str
    magic: tuple[bytes, ...]
    suffix: tuple[str, ...]
    rank: int


RESOURCE_LEVELS = (
    ResourceLevel("smf", "-smf", "SMF / RSLB", "SMF", (b"RSLB",), (".smf", ".rsb.smf"), 0),
    ResourceLevel("rsb", "-rsb", "RSB / 1bsr", "RSB", (b"1bsr", b"rsb1"), (".rsb", ".1bsr", ".rsb1", ".obb"), 1),
    ResourceLevel("rsg", "-rsg", ".rsg", "RSG", (b"pgsr",), (".rsg",), 2),
    ResourceLevel("encrypted", "-encrypted", "加密 RTON", "ENCRYPTED_RTON", (b"\x10\x00",), (".rton", ".bin", ".dat"), 3),
    ResourceLevel("rton", "-rton", ".rton", "RTON", (b"RTON",), (".rton", ".bin", ".dat"), 4),
    ResourceLevel("json", "-json", ".json", "JSON", (), (".json",), 5),
)

FORMAT_ALIASES = {
    "smf": "smf",
    "rsb": "rsb",
    "rsbx": "rsbx",
    "rsg": "rsg",
    "encrypted": "encrypted",
    "rton": "rton",
    "json": "json",
}

FORMAT_FLAGS = {
    "smf": "-smf",
    "rsb": "-rsb",
    "rsbx": "-rsbx",
    "rsg": "-rsg",
    "encrypted": "-encrypted",
    "rton": "-rton",
    "json": "-json",
}

FORMAT_NAMES = {
    "smf": "SMF / RSLB (.smf)",
    "rsb": "RSB / 1bsr (.rsb)",
    "rsbx": "RSBX / 1bsr (.rsb.smf)",
    "rsg": ".rsg",
    "encrypted": "加密 RTON",
    "rton": ".rton",
    "json": ".json",
}

FORMAT_RANK = {
    "smf": 0,
    "rsb": 1,
    "rsbx": 1,
    "rsg": 2,
    "encrypted": 3,
    "rton": 4,
    "json": 5,
}

RANK_TO_FORMAT = {
    0: "smf",
    1: "rsb",
    2: "rsg",
    3: "encrypted",
    4: "rton",
    5: "json",
}

RSLB_MAGIC = b"RSLB"
RSB_MAGICS = (b"1bsr", b"rsb1")


def normalize_format(value: str) -> str:
    """把命令行格式名规范化为内部格式 ID。"""
    key = value.strip().lower().lstrip("-")
    try:
        return FORMAT_ALIASES[key]
    except KeyError:
        choices = " / ".join(FORMAT_FLAGS.values())
        raise ValueError(f"未知格式 {value!r}；可用格式：{choices}") from None


def level_index(value: str) -> int:
    """返回格式在资源链中的语义层级；RSBX 与 RSB 同为 1。"""
    return FORMAT_RANK[normalize_format(value)]


def resource_level(rank: int) -> ResourceLevel:
    """按层级编号返回资源格式定义。"""
    return RESOURCE_LEVELS[rank]


def read_head(path: Path, size: int = 64) -> bytes:
    """读取文件头。"""
    with path.open("rb") as file:
        return file.read(size)


def _strict_suffix_error(path: Path, head: bytes) -> ValueError | None:
    lower = path.name.lower()
    header = head[:8].hex(" ").upper()

    if lower.endswith(".rsb.smf"):
        if head.startswith(RSLB_MAGIC) or head.startswith(RSB_MAGICS):
            return None
        return ValueError(
            f".rsb.smf 只能是 SMF(RSLB) 或显式 RSBX(1bsr)：{path}\n"
            f"文件头：{header}"
        )

    if lower.endswith(".smf") and not head.startswith(RSLB_MAGIC):
        return ValueError(f".smf 必须是 RSLB 文件：{path}\n文件头：{header}")

    if lower.endswith((".rsb", ".1bsr", ".rsb1")) and not head.startswith(RSB_MAGICS):
        return ValueError(f"RSB 后缀必须对应 1bsr/rsb1：{path}\n文件头：{header}")

    return None


def detect_file_format(path: Path) -> str | None:
    """严格按魔数优先识别单个文件格式。"""
    head = read_head(path)
    lower = path.name.lower()

    if head.startswith(RSLB_MAGIC):
        return "smf"
    if head.startswith(RSB_MAGICS):
        return "rsbx" if lower.endswith(".rsb.smf") else "rsb"
    if head.startswith(b"pgsr"):
        return "rsg"
    if head.startswith(b"RTON"):
        return "rton"
    if head.startswith(b"\x10\x00"):
        return "encrypted"
    if path.suffix.lower() == ".json" or head.lstrip().startswith((b"{", b"[")):
        return "json"

    suffix_error = _strict_suffix_error(path, head)
    if suffix_error is not None:
        raise suffix_error

    for fmt in ("rsg", "encrypted", "rton", "json"):
        level = resource_level(FORMAT_RANK[fmt])
        if lower.endswith(level.suffix):
            return fmt
    return None


def detect_format(source: str | Path) -> str:
    """识别单文件或目录所代表的最高资源层级。"""
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"输入不存在：{path}")

    if path.is_file():
        detected = detect_file_format(path)
        if detected is None:
            header = read_head(path, 8).hex(" ").upper()
            raise ValueError(f"无法识别输入格式：{path}\n文件头：{header}")
        return detected

    counts = {fmt: 0 for fmt in FORMAT_ALIASES}
    for file in sorted(path.rglob("*")):
        if not file.is_file():
            continue
        try:
            detected = detect_file_format(file)
        except ValueError:
            continue
        if detected is not None:
            counts[detected] += 1

    found = [fmt for fmt, count in counts.items() if count]
    if not found:
        raise ValueError(f"目录中没有可识别的资源文件：{path}")

    highest_rank = max(FORMAT_RANK[fmt] for fmt in found)
    same_rank = [fmt for fmt in found if FORMAT_RANK[fmt] == highest_rank]
    if "json" in same_rank:
        return "json"
    if "rsbx" in same_rank and "rsb" not in same_rank:
        return "rsbx"
    return RANK_TO_FORMAT[highest_rank]


def detect_level(source: str | Path) -> int:
    """兼容旧接口：返回识别后的层级编号。"""
    return FORMAT_RANK[detect_format(source)]


def validate_forced_format(path: Path, fmt: str) -> None:
    """校验用户手动指定的输入格式是否与真实内容一致。"""
    if not path.is_file():
        return
    actual = detect_file_format(path)
    if fmt in {"rsb", "rsbx"} and actual in {"rsb", "rsbx"}:
        if fmt == "rsbx" and not path.name.lower().endswith(".rsb.smf"):
            raise ValueError("--from-rsbx 要求输入文件名以 .rsb.smf 结尾")
        return
    if actual != fmt:
        raise ValueError(
            f"手动指定格式与文件实际格式冲突：指定={fmt}，实际={actual}，文件={path}"
        )


def strip_container_suffix(name: str) -> str:
    """移除容器相关扩展名。"""
    lower = name.lower()
    for suffix in (".rsb.smf", ".1bsr", ".rsb1", ".rsb", ".smf", ".obb"):
        if lower.endswith(suffix):
            return name[:-len(suffix)]
    return Path(name).stem


def default_unpack_output(source: Path) -> Path:
    """生成默认解包工程目录。"""
    name = source.name if source.is_dir() else strip_container_suffix(source.name)
    return source.parent / f"{name}_unpacked"


def container_output_name(source: Path, fmt: str) -> str:
    """根据逻辑容器格式生成输出文件名。"""
    base = strip_container_suffix(source.name)
    if fmt == "rsb":
        return f"{base}.rsb"
    if fmt == "rsbx":
        return f"{base}.rsb.smf"
    if fmt == "smf":
        return f"{base}.smf"
    raise ValueError(f"不是容器输出格式：{fmt}")


def single_file_output(current: Path, stage_dir: Path, next_rank: int) -> Path:
    """生成单文件跨层转换时的目标路径。"""
    name = current.name
    if next_rank == 4:
        return stage_dir / name
    if next_rank == 5:
        name = name[:-5] + ".json" if name.lower().endswith(".rton") else name + ".json"
    return stage_dir / name
