"""文件系统访问与并发策略。"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from config import SETTINGS

try:
    import fcntl
except ImportError:  # Windows 不提供 reflink ioctl，自动退回普通复制。
    fcntl = None


type PathLike = str | Path

_FICLONE = SETTINGS.filesystem.ficlone_ioctl
_HASH_CHUNK_SIZE = 8 * 1024 * 1024


def as_path(value: PathLike) -> Path:
    """展开用户目录并转换为 Path。"""
    return Path(value).expanduser()


def recommended_jobs(value: int | None = None) -> int:
    """返回适合手机和桌面端的保守并发数。"""
    if value is not None:
        if value < 1:
            raise ValueError("并发数必须大于 0")
        return value
    return min(4, max(1, (os.cpu_count() or 2) - 1))


def require_path(path: Path, label: str, *, file: bool | None = None) -> Path:
    """校验路径存在性以及文件/目录类型。"""
    match file:
        case True:
            valid = path.is_file()
        case False:
            valid = path.is_dir()
        case None:
            valid = path.exists()
    if not valid:
        raise FileNotFoundError(f"{label}不存在：{path}")
    return path


def sha256(path: Path) -> str:
    """计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clone_or_copy(source: Path, destination: Path) -> str:
    """优先使用 reflink，不支持时退回普通复制。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        if fcntl is None:
            raise OSError
        with source.open("rb") as src, destination.open("wb") as dst:
            fcntl.ioctl(dst.fileno(), _FICLONE, src.fileno())
        return "clone"
    except OSError:
        destination.unlink(missing_ok=True)
        shutil.copyfile(source, destination)
        return "copy"
