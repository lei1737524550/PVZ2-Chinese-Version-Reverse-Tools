#!/usr/bin/env python3
"""PVZ_Player_Tool 唯一直接执行入口。"""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from app.cli import cli_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(cli_main())
