"""PvZ2 Resource Tool 的命令行参数与交互界面。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from domain.errors import FormatError
from domain.formats import FORMAT_NAMES, FORMAT_RANK, detect_format
from project.index import run_index_reverse
from services.pack import pack
from services.unpack import unpack

_TARGET_FLAGS = ("smf", "rsb", "rsbx", "rsg", "encrypted", "rton", "json")


class ToolArgumentParser(argparse.ArgumentParser):
    """确保帮助文本与终端中的命令行提示明确分行。"""

    def format_help(self) -> str:
        help_text = super().format_help()
        return help_text if help_text.startswith("\n") else f"\n{help_text}"


def _add_target_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    for fmt in _TARGET_FLAGS:
        group.add_argument(
            f"-{fmt}",
            dest="target",
            action="store_const",
            const=fmt,
            help=f"目标格式：{FORMAT_NAMES[fmt]}",
        )


def _add_source_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    for fmt in _TARGET_FLAGS:
        group.add_argument(
            f"--from-{fmt}",
            dest="source_format",
            action="store_const",
            const=fmt,
            help=f"严格指定输入为 {FORMAT_NAMES[fmt]}",
        )


def build_cli() -> argparse.ArgumentParser:
    """建立 CLI 参数解析器。"""
    parser = ToolArgumentParser(
        prog="main.py",
        description=(
            "PvZ2 资源统一打包/解包工具。\n\n"
            "示例：\n"
            "  python main.py -unpack dynamic.smf -json -j 4\n"
            "  python main.py -pack /path/to/04_JSON -rsb -j 4\n"
            "  python main.py -pack /path/to/04_JSON -rsbx -j 4\n"
            "  python main.py -pack /path/to/04_JSON -smf -j 4\n"
            "  python main.py -reverse /path/to/dynamic_unpacked"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    action = parser.add_mutually_exclusive_group()
    action.add_argument("-unpack", metavar="PATH", help="解包输入文件/目录")
    action.add_argument("-pack", metavar="PATH", help="打包输入文件/阶段目录/工程目录")
    action.add_argument("-reverse", metavar="PROJECT", help="按 index.md 原路回包")

    _add_target_flags(parser)
    _add_source_flags(parser)

    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument("-j", "--jobs", type=int, help="并发数；手机建议 2~4")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示逐文件信息")
    parser.add_argument("--base-rsg", help="打包时指定原始 RSG 文件/目录")
    parser.add_argument("--base-rsb", help="打包时指定基础 1bsr RSB 或 RSLB SMF")
    parser.add_argument("--verify-roundtrip", action="store_true", help="回包时校验未修改数据")
    return parser


def _choose_target(action: str, source: Path) -> str:
    source_format = detect_format(source)
    source_rank = FORMAT_RANK[source_format]
    if action == "unpack":
        valid = [fmt for fmt in _TARGET_FLAGS if FORMAT_RANK[fmt] > source_rank]
        if source_rank == 1:
            valid.insert(0, "rsbx" if source_format == "rsb" else "rsb")
    else:
        valid = [fmt for fmt in _TARGET_FLAGS[:-1] if FORMAT_RANK[fmt] < source_rank]
        if source_rank == 1:
            valid.insert(0, "rsbx" if source_format == "rsb" else "rsb")

    if not valid:
        operation = "解包" if action == "unpack" else "打包"
        raise ValueError(f"{FORMAT_NAMES[source_format]} 没有可用的{operation}目标")

    print(f"识别输入：{FORMAT_NAMES[source_format]}")
    print("可选目标：")
    for index, fmt in enumerate(valid, 1):
        print(f"  [{index}] -{fmt:<10} {FORMAT_NAMES[fmt]}")

    while True:
        raw = input("选择编号或直接输入参数（如 -rsb）：").strip()
        if raw.startswith("-") and raw[1:] in valid:
            return raw[1:]
        try:
            index = int(raw) - 1
        except ValueError:
            index = -1
        if 0 <= index < len(valid):
            return valid[index]
        print("输入无效。")


def interactive_main() -> int:
    """运行一次交互式任务，任务完成或失败后立即退出。"""
    print(
        "\nPvZ2 Resource Tool\n"
        "1. 解包\n"
        "2. 打包\n"
        "3. 按 index.md 反向回包\n"
        "0. 退出\n"
    )

    while True:
        choice = input("> ").strip()
        if choice in {"0", "q", "quit", "exit"}:
            return 0
        if choice in {"1", "2", "3"}:
            break
        print("请输入 0~3。")

    try:
        if choice == "1":
            source = Path(input("输入文件或目录：").strip().strip('"').strip("'")).expanduser()
            target = _choose_target("unpack", source)
            jobs_raw = input("并发数（回车自动）：").strip()
            unpack(source, target, jobs=int(jobs_raw) if jobs_raw else None)

        elif choice == "2":
            source = Path(input("输入文件/阶段目录/工程目录：").strip().strip('"').strip("'")).expanduser()
            target = _choose_target("pack", source)
            jobs_raw = input("并发数（回车自动）：").strip()
            pack(source, target, jobs=int(jobs_raw) if jobs_raw else None)

        else:
            project = input("工程目录：").strip().strip('"').strip("'")
            run_index_reverse(project or None)

        print("\n任务完成。")
        return 0
    except KeyboardInterrupt:
        print("\n用户取消。", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, FormatError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def cli_main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return interactive_main()

    parser = build_cli()
    args = parser.parse_args(argv)

    try:
        if args.reverse:
            if args.target:
                raise ValueError("-reverse 不接受目标格式参数")
            run_index_reverse(args.reverse)
            return 0

        if args.unpack:
            if not args.target:
                raise ValueError("-unpack 必须指定目标，例如 -json / -rsb / -rsbx")
            unpack(
                args.unpack,
                args.target,
                args.output,
                args.source_format,
                args.jobs,
                args.verbose,
            )
            return 0

        if args.pack:
            if not args.target:
                raise ValueError("-pack 必须指定目标，例如 -rsb / -rsbx / -smf")
            if args.target == "json":
                raise ValueError("-pack 的目标不能是 -json")
            pack(
                args.pack,
                args.target,
                args.output,
                args.source_format,
                args.base_rsg,
                args.base_rsb,
                args.verify_roundtrip,
                args.jobs,
                args.verbose,
            )
            return 0

        parser.print_help()
        return 0
    except KeyboardInterrupt:
        print("\n用户取消。", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, FormatError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
