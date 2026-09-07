"""Tool_2 的唯一命令行与交互界面。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config.settings import SETTINGS
from domain.errors import ToolError
from domain.models import DiffRequest, ExportPaths, ExportRequest, ImportPaths, ImportRequest, InventoryRequest
from infrastructure.project_context import PP_DAT, PP_JSON, PVZ_JSON_DIR
from services.diff import DiffService
from services.export import ExportService
from services.import_pp import ImportService
from services.inspect import InspectService
from services.inventory import InventoryService
from services.pcpid import PCPIDService

DEFAULT_WORK_DIR = PVZ_JSON_DIR


def _path(value: str | Path) -> Path:
    if isinstance(value, Path):
        return value.expanduser()
    return Path(value.strip().strip('"').strip("'")).expanduser()


def _export_paths(work_dir: Path) -> ExportPaths:
    files = SETTINGS.files
    return ExportPaths(
        work_dir=work_dir,
        dat=work_dir / files.export_dat,
        bin=work_dir / files.export_bin,
        json=work_dir / files.export_json,
    )


def export_workflow(
    source: Path | None = None,
    *,
    work_dir: Path = DEFAULT_WORK_DIR,
    package: str | None = None,
    game_path: str | None = None,
    rish: str | None = None,
) -> Path:
    android = SETTINGS.android
    request = ExportRequest(
        paths=_export_paths(work_dir.expanduser()),
        package=package or android.package,
        game_path=game_path or android.game_dat,
        rish=rish or android.rish,
        source=source.expanduser() if source else None,
    )
    return ExportService(request).run()


def import_workflow(
    base_dat: Path,
    changed_json: Path,
    *,
    work_dir: Path = DEFAULT_WORK_DIR,
    package: str | None = None,
    game_path: str | None = None,
    game_backup_path: str | None = None,
    rish: str | None = None,
    build_only: bool = False,
    write_game_backup: bool | None = None,
    force_stop: bool | None = None,
) -> Path:
    android = SETTINGS.android
    files = SETTINGS.files
    work_dir = work_dir.expanduser()
    request = ImportRequest(
        paths=ImportPaths(
            work_dir=work_dir,
            base_dat=base_dat.expanduser(),
            changed_json=changed_json.expanduser(),
            output_bin=work_dir / files.import_bin,
            output_dat=work_dir / files.import_dat,
        ),
        package=package or android.package,
        game_dat=game_path or android.game_dat,
        game_backup=game_backup_path or android.game_backup,
        rish=rish or android.rish,
        build_only=build_only,
        write_game_backup=(
            android.write_game_backup if write_game_backup is None else write_game_backup
        ),
        force_stop_game=android.force_stop_game if force_stop is None else force_stop,
    )
    return ImportService(request).run()


def inventory_workflow(
    json_path: Path,
    *,
    entity: str,
    action: str,
    plant_id: int | None = None,
    value: int | None = None,
    pcpid: str | None = None,
) -> bool:
    request = InventoryRequest(
        json_path=json_path.expanduser(),
        entity=entity,
        action=action,
        plant_id=plant_id,
        value=value,
        pcpid=pcpid,
    )
    return InventoryService(request).run()


def diff_workflow(before: Path, after: Path, output: Path) -> Path:
    return DiffService(
        DiffRequest(before=before.expanduser(), after=after.expanduser(), output=output.expanduser())
    ).run()


def _default_json_prompt() -> Path:
    raw = input(f"pp.json（回车={PP_JSON}）：").strip()
    return _path(raw) if raw else PP_JSON


def _interactive_inventory(entity: str) -> int:
    json_path = _default_json_prompt()
    if entity == "plant":
        raw = input("操作：1=查询 2=添加 3=删除：").strip()
        action = {"1": "query", "2": "add", "3": "remove"}.get(raw, raw)
    elif entity == "pieces":
        raw = input("操作：1=查询 2=设置数量 3=删除记录：").strip()
        action = {"1": "query", "2": "set", "3": "remove"}.get(raw, raw)
    else:
        raw = input("操作：1=查询 2=设置等级 3=删除等级记录：").strip()
        action = {"1": "query", "2": "set", "3": "remove"}.get(raw, raw)

    plant_id = int(input("植物 JSON ID：").strip(), 10)
    value: int | None = None
    if entity == "pieces" and action == "set":
        value = int(input("碎片数量：").strip(), 10)
    if entity == "level" and action == "set":
        value = int(input("植物等级：").strip(), 10)
    inventory_workflow(
        json_path,
        entity=entity,
        action=action,
        plant_id=plant_id,
        value=value,
    )
    return 0


def verify_signatures_workflow(json_path: Path, *, pcpid: str | None = None) -> bool:
    """验证当前 pp.json 的植物等级/碎片签名。"""
    from infrastructure.files import read_json
    from domain.profile import get_player_info, validate_plant_structures
    from infrastructure.project_context import resolve_pcpid

    root = read_json(json_path.expanduser())
    data = get_player_info(root)
    validate_plant_structures(data)
    resolved = resolve_pcpid(
        pcpid,
        package=SETTINGS.android.package,
        rish=SETTINGS.android.rish,
        auto_discover=True,
    )
    all_ok = True
    for name, checker in (("pprs", verify_pprs), ("psls", verify_psls)):
        ok, actual, expected = checker(data, resolved)
        all_ok &= ok
        print(f"[{'OK' if ok else 'FAIL'}] {name}")
        print(f"  文件值：{actual}")
        print(f"  计算值：{expected}")
    return all_ok


def interactive_main() -> int:
    print(
        "\nPVZ2 pp.dat / pp.json 工具\n"
        "1. 导出 pp.dat -> pp.json\n"
        "2. 导入 pp.json -> pp.dat\n"
        "3. 查看 pp.json 核心数据\n"
        "4. 植物增删查\n"
        "5. 植物碎片增删改查\n"
        "6. 植物等级增删改查\n"
        "7. 修除植物违法（删除未拥有植物的等级记录）\n"
        "8. 对比两个 pp.json\n"
        "9. 获取/刷新 PCPID\n"
        "10. 验证 pprs / psls\n"
        "0. 退出\n"
    )
    choice = input("> ").strip()
    if choice in {"0", "q", "quit", "exit"}:
        return 0
    if choice == "1":
        raw = input("本地 pp.dat/RTON 路径（回车=从游戏提取）：").strip()
        work = input(f"输出目录（回车={DEFAULT_WORK_DIR}）：").strip()
        export_workflow(
            _path(raw) if raw else None,
            work_dir=_path(work) if work else DEFAULT_WORK_DIR,
        )
        return 0
    if choice == "2":
        base_raw = input(f"原始 pp.dat（回车={PP_DAT}）：").strip()
        json_raw = input(f"修改后的 pp.json（回车={PP_JSON}）：").strip()
        build_only = input("只构建 changed.dat，不写游戏？[y/N]：").strip().lower() in {
            "y", "yes", "1"
        }
        import_workflow(
            _path(base_raw) if base_raw else PP_DAT,
            _path(json_raw) if json_raw else PP_JSON,
            build_only=build_only,
        )
        return 0
    if choice == "3":
        InspectService().run(_default_json_prompt())
        return 0
    if choice == "4":
        return _interactive_inventory("plant")
    if choice == "5":
        return _interactive_inventory("pieces")
    if choice == "6":
        return _interactive_inventory("level")
    if choice == "7":
        inventory_workflow(_default_json_prompt(), entity="repair", action="repair")
        return 0
    if choice == "8":
        before = _path(input("修改前 pp.json："))
        after = _path(input("修改后 pp.json："))
        raw = input(f"报告路径（回车={DEFAULT_WORK_DIR / SETTINGS.files.diff_output}）：").strip()
        output = _path(raw) if raw else DEFAULT_WORK_DIR / SETTINGS.files.diff_output
        diff_workflow(before, after, output)
        return 0
    if choice == "9":
        PCPIDService().refresh()
        return 0
    if choice == "10":
        return 0 if verify_signatures_workflow(_default_json_prompt()) else 2
    raise ToolError("请输入 0~10")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PVZ2 pp.dat / pp.json 工具；无参数进入一次性交互界面"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-export", nargs="?", const="", metavar="PP.DAT", help="导出；省略文件则从游戏提取")
    mode.add_argument("-import", dest="do_import", action="store_true", help="重建/导入 pp.dat")
    mode.add_argument("-inspect", nargs="?", const="", metavar="PP.JSON", help="打印 pp.json 核心数据")
    mode.add_argument("-plant", choices=("query", "add", "remove"), help="植物拥有状态操作")
    mode.add_argument("-pieces", choices=("query", "set", "remove"), help="植物碎片操作")
    mode.add_argument("-level", choices=("query", "set", "remove"), help="植物等级操作")
    mode.add_argument("-repair-plants", action="store_true", help="删除未拥有植物对应的 psla 等级记录")
    mode.add_argument("-diff", action="store_true", help="比较两个 pp.json")
    mode.add_argument("-refresh-pcpid", action="store_true", help="自动获取/刷新 PCPID 并写入项目根目录 pcpid.txt")
    mode.add_argument("-verify-signatures", action="store_true", help="验证 pp.json 的 pprs / psls")

    parser.add_argument("paths", nargs="*")
    parser.add_argument("--json", default=str(PP_JSON), help="植物相关操作使用的 pp.json")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--package", default=SETTINGS.android.package)
    parser.add_argument("--game-path", default=SETTINGS.android.game_dat)
    parser.add_argument("--game-backup-path", default=SETTINGS.android.game_backup)
    parser.add_argument("--rish", default=SETTINGS.android.rish)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument(
        "--game-backup",
        action=argparse.BooleanOptionalAction,
        default=SETTINGS.android.write_game_backup,
        help="是否同时写入 pp.dat.bak",
    )
    parser.add_argument(
        "--force-stop",
        action=argparse.BooleanOptionalAction,
        default=SETTINGS.android.force_stop_game,
        help="写入前是否停止游戏进程",
    )
    parser.add_argument("--pcpid")
    parser.add_argument("--plant-id", type=int, help="植物 JSON ID")
    parser.add_argument("--count", type=int, help="植物碎片数量")
    parser.add_argument("--value-level", type=int, help="植物等级")
    parser.add_argument("--show-owned", type=int, default=20, help="inspect 时最多展开多少个已拥有植物")
    parser.add_argument("-o", "--output")
    return parser


def _inventory_path(args: argparse.Namespace) -> Path:
    if len(args.paths) > 1:
        raise ToolError("植物相关命令最多附带一个 pp.json 路径")
    return _path(args.paths[0]) if args.paths else _path(args.json)


def cli_main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        try:
            return interactive_main()
        except KeyboardInterrupt:
            print("\n已取消。", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

    # Termux 中命令回显可能与 argparse 的 usage 紧邻；显式先换行。
    if "-h" in argv or "--help" in argv:
        print()

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        work_dir = _path(args.work_dir)

        if args.export is not None:
            if args.paths:
                raise ToolError("-export 不接受额外位置参数")
            source = _path(args.export) if args.export else None
            export_workflow(
                source,
                work_dir=work_dir,
                package=args.package,
                game_path=args.game_path,
                rish=args.rish,
            )
            return 0

        if args.do_import:
            if len(args.paths) not in {0, 2}:
                raise ToolError("-import 可不传路径，或依次传入原始 pp.dat 与修改后的 pp.json")
            base, changed = (
                (PP_DAT, PP_JSON)
                if not args.paths
                else (_path(args.paths[0]), _path(args.paths[1]))
            )
            import_workflow(
                base,
                changed,
                work_dir=work_dir,
                package=args.package,
                game_path=args.game_path,
                game_backup_path=args.game_backup_path,
                rish=args.rish,
                build_only=args.build_only,
                write_game_backup=args.game_backup,
                force_stop=args.force_stop,
            )
            return 0

        if args.refresh_pcpid:
            if args.paths:
                raise ToolError("-refresh-pcpid 不接受额外位置参数")
            PCPIDService(package=args.package, rish=args.rish).refresh()
            return 0

        if args.verify_signatures:
            if len(args.paths) > 1:
                raise ToolError("-verify-signatures 最多附带一个 pp.json 路径")
            path = _path(args.paths[0]) if args.paths else _path(args.json)
            return 0 if verify_signatures_workflow(path, pcpid=args.pcpid) else 2

        if args.inspect is not None:
            if args.paths:
                raise ToolError("-inspect 不接受额外位置参数")
            path = _path(args.inspect) if args.inspect else _path(args.json)
            InspectService().run(path, show_owned=max(0, args.show_owned))
            return 0

        if args.plant is not None:
            if args.plant_id is None:
                raise ToolError("-plant 需要 --plant-id")
            inventory_workflow(
                _inventory_path(args),
                entity="plant",
                action=args.plant,
                plant_id=args.plant_id,
                pcpid=args.pcpid,
            )
            return 0

        if args.pieces is not None:
            if args.plant_id is None:
                raise ToolError("-pieces 需要 --plant-id")
            if args.pieces == "set" and args.count is None:
                raise ToolError("-pieces set 需要 --count")
            inventory_workflow(
                _inventory_path(args),
                entity="pieces",
                action=args.pieces,
                plant_id=args.plant_id,
                value=args.count,
                pcpid=args.pcpid,
            )
            return 0

        if args.level is not None:
            if args.plant_id is None:
                raise ToolError("-level 需要 --plant-id")
            if args.level == "set" and args.value_level is None:
                raise ToolError("-level set 需要 --value-level")
            inventory_workflow(
                _inventory_path(args),
                entity="level",
                action=args.level,
                plant_id=args.plant_id,
                value=args.value_level,
                pcpid=args.pcpid,
            )
            return 0

        if args.repair_plants:
            inventory_workflow(
                _inventory_path(args),
                entity="repair",
                action="repair",
                pcpid=args.pcpid,
            )
            return 0

        if args.diff:
            if len(args.paths) != 2:
                raise ToolError("-diff 需要两个 pp.json 路径")
            output = _path(args.output) if args.output else work_dir / SETTINGS.files.diff_output
            diff_workflow(_path(args.paths[0]), _path(args.paths[1]), output)
            return 0

        parser.print_help()
        return 0
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
