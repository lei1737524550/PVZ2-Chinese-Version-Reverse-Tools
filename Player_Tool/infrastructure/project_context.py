"""Tool_2 项目根路径与 PCPID 的唯一管理入口。

标准安装结构::

    /storage/emulated/0/aPVZ/
      pcpid.txt
      PVZ_Json/
        pp.dat
        pp.bin
        pp.json
      PVZ_Tools/
        Tool_2/
          main.py

所有模块都先定位 ``Tool_2``，再由 ``Tool_2 -> PVZ_Tools -> aPVZ``
得到项目根目录。业务代码不得自己拼 ``../../`` 或 ``../../../``。
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

# project_context.py 位于 Tool_2/infrastructure/。
TOOL_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = TOOL_DIR.parent

# 标准结构：<project>/PVZ_Tools/Tool_2/。
# 在标准结构中，PROJECT_DIR 就是 /storage/emulated/0/aPVZ。
# 为了让 Tool_2 单独解压后仍可做静态测试，仅在不是标准结构时退回 Tool_2 的父目录。
if TOOL_DIR.name.startswith("Tool_") and TOOLS_DIR.name == "PVZ_Tools":
    PROJECT_DIR = TOOLS_DIR.parent
else:
    PROJECT_DIR = TOOL_DIR.parent

PVZ_JSON_DIR = PROJECT_DIR / "PVZ_Json"
PCPID_FILE = PROJECT_DIR / "pcpid.txt"

PP_DAT = PVZ_JSON_DIR / "pp.dat"
PP_BIN = PVZ_JSON_DIR / "pp.bin"
PP_JSON = PVZ_JSON_DIR / "pp.json"

_UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
_PACKAGE_RE = re.compile(r"^package:(\S+)$")


def ensure_project_layout() -> None:
    """创建统一数据目录和 PCPID 文件。"""
    PVZ_JSON_DIR.mkdir(parents=True, exist_ok=True)
    if not PCPID_FILE.exists():
        PCPID_FILE.write_text("", encoding="utf-8")


def _normalize_pcpid(text: str) -> str:
    """兼容纯 UUID 和 ``pcpid: UUID`` 两种文本格式。"""
    value = str(text).strip()
    if not value:
        return ""
    if ":" in value and value.lower().split(":", 1)[0].strip() == "pcpid":
        value = value.split(":", 1)[1].strip()
    match = _UUID_RE.search(value)
    return match.group(0).lower() if match else value


def read_pcpid() -> str:
    ensure_project_layout()
    return _normalize_pcpid(PCPID_FILE.read_text(encoding="utf-8", errors="ignore"))


def write_pcpid(value: str) -> str:
    """覆盖项目根目录 pcpid.txt；所有工具后续自动共享这个值。"""
    ensure_project_layout()
    pcpid = _normalize_pcpid(value)
    if not pcpid:
        raise ValueError("PCPID 为空，不能写入 pcpid.txt")
    tmp = PCPID_FILE.with_name(PCPID_FILE.name + ".part")
    tmp.write_text(pcpid + "\n", encoding="utf-8")
    tmp.replace(PCPID_FILE)
    return pcpid


def _run_text(command: list[str], timeout: int = 15) -> str:
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def _candidate_packages(package: str | None, rish: str) -> list[str]:
    """配置包名优先，随后补充设备上可见的 PvZ/PopCap 相关包。"""
    result: list[str] = []
    if package and str(package).strip():
        result.append(str(package).strip())

    commands: list[list[str]] = []
    if rish and shutil.which(str(rish)):
        commands.append([str(rish), "-c", "pm list packages"])
    if shutil.which("pm"):
        commands.append(["pm", "list", "packages"])

    for command in commands:
        for line in _run_text(command, timeout=10).splitlines():
            match = _PACKAGE_RE.match(line.strip())
            if not match:
                continue
            name = match.group(1)
            low = name.lower()
            if any(key in low for key in ("popcap", "pvz", "losswingfish")):
                if name not in result:
                    result.append(name)
    return result


def _grep_pcpid_for_package(package: str, rish: str) -> tuple[str, str]:
    """在一个应用的私有目录中查找 PCPID，返回 (pcpid, 来源行)。"""
    grep_cmd = (
        "grep -R -a -n -i 'pcpid' shared_prefs files databases no_backup "
        "2>/dev/null"
    )
    run_as_shell = f"run-as {shlex.quote(package)} sh -c {shlex.quote(grep_cmd)}"

    commands: list[list[str]] = []
    if rish and shutil.which(str(rish)):
        commands.append([str(rish), "-c", run_as_shell])
    if shutil.which("run-as"):
        commands.append(["run-as", package, "sh", "-c", grep_cmd])

    for command in commands:
        output = _run_text(command)
        for line in output.splitlines():
            if "pcpid" not in line.lower():
                continue
            match = _UUID_RE.search(line)
            if match:
                return match.group(0).lower(), line.strip()
    return "", ""


def discover_pcpid(package: str | None = None, rish: str = "rish") -> str:
    """自动从游戏私有数据获取 PCPID，不要求用户在脚本中填写。"""
    for candidate in _candidate_packages(package, rish):
        pcpid, _ = _grep_pcpid_for_package(candidate, rish)
        if pcpid:
            return pcpid
    return ""


def refresh_pcpid(package: str | None = None, rish: str = "rish") -> str:
    """强制重新获取 PCPID，并覆盖项目根目录 pcpid.txt。"""
    found = discover_pcpid(package, rish)
    if not found:
        packages = ", ".join(_candidate_packages(package, rish)) or "未发现候选包"
        raise ValueError(
            "自动获取 PCPID 失败。"
            f"\n候选游戏包：{packages}"
            "\n请确认 Termux/Shizuku 的 rish + run-as 可以读取游戏私有目录。"
        )
    return write_pcpid(found)


def resolve_pcpid(
    override: str | None = None,
    *,
    package: str | None = None,
    rish: str = "rish",
    auto_discover: bool = True,
    force_refresh: bool = False,
) -> str:
    """统一解析 PCPID。

    顺序：
    1. 调用方显式传入 PCPID -> 立即覆盖 pcpid.txt；
    2. force_refresh=True -> 强制自动获取并覆盖；
    3. 读取项目根目录 pcpid.txt；
    4. 文件为空时自动获取并写入。
    """
    if override is not None and str(override).strip():
        return write_pcpid(str(override))

    if force_refresh:
        return refresh_pcpid(package, rish)

    stored = read_pcpid()
    if stored:
        return stored

    if auto_discover:
        return refresh_pcpid(package, rish)

    raise ValueError(f"找不到 PCPID：{PCPID_FILE}")


ensure_project_layout()
