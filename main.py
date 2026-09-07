#!/usr/bin/env python3
"""PvZ2 Resource Tool 唯一执行入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# main.py 是唯一允许直接执行的脚本；内部模块统一采用同一种绝对导入方式。
_TOOL_ROOT = Path(__file__).resolve().parent
if str(_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOL_ROOT))

from app.cli import cli_main  # noqa: E402
from domain.formats import detect_format, detect_level  # noqa: E402
from project.index import run_index_reverse  # noqa: E402
from services.pack import pack  # noqa: E402
from binary_codecs.smf import rsb_to_smf, smf_to_rsb  # noqa: E402
from services.unpack import unpack  # noqa: E402

__all__ = [
    "cli_main",
    "detect_format",
    "detect_level",
    "pack",
    "rsb_to_smf",
    "run_index_reverse",
    "smf_to_rsb",
    "unpack",
]


if __name__ == "__main__":
    raise SystemExit(cli_main())
