"""转换层使用的强类型任务与结果对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class TransformAction(StrEnum):
    """单文件 RTON 转换动作。"""

    DECRYPT = "decrypt"
    ENCRYPT = "encrypt"
    DECODE = "decode"
    ENCODE = "encode"


@dataclass(frozen=True, slots=True)
class TransformTask:
    """单个文件的转换与失败回退目标。"""

    source: Path
    converted: Path
    fallback: Path
    action: TransformAction


@dataclass(frozen=True, slots=True)
class CopyTask:
    """单个原样复制任务。"""

    source: Path
    destination: Path


@dataclass(frozen=True, slots=True)
class TransformResult:
    """单文件转换结果。"""

    success: bool
    destination: Path
    error: str = ""


@dataclass(frozen=True, slots=True)
class DecryptDecodeTask:
    """一次读取同时生成 RTON 与 JSON 的任务。"""

    source: Path
    rton_path: Path
    json_path: Path
    rton_fallback: Path
    json_fallback: Path


@dataclass(frozen=True, slots=True)
class DecryptDecodeResult:
    """解密并解码任务的结果。"""

    status: str
    destination: Path
    error: str = ""


@dataclass(frozen=True, slots=True)
class CopyPairTask:
    """把同一个源文件同时保留到两层输出目录。"""

    source: Path
    first: Path
    second: Path


@dataclass(frozen=True, slots=True)
class InternalExtractTask:
    """单个 RSG 的内部文件提取任务。"""

    source: Path
    destination: Path
    verbose: bool = False


@dataclass(frozen=True, slots=True)
class RsgTask:
    """单个 RSG 回包任务。"""

    base: Path
    patch_dir: Path
    destination: Path
    mode: str = "stored"
    unchanged: frozenset[str] = field(default_factory=frozenset)
    verbose: bool = False
    copy_whole: bool = False


@dataclass(frozen=True, slots=True)
class RsgBuildResult:
    """RSG 回包后的验证上下文。"""

    base: Path
    destination: Path
    relative: Path
