"""pp.json → pp.dat 的业务编排。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from formats.pp_dat import decrypt_pp, encrypt_pp
from formats.typed_rton import RTONError, TypedRTONReader, build_rton, node_to_value
from domain.errors import ToolError
from domain.models import ImportRequest
from infrastructure.android import AndroidBridge
from infrastructure.files import atomic_write_bytes, sha256_file


def _count_changes(before, after) -> int:
    if type(before) is not type(after):
        return 1
    if isinstance(before, dict):
        return sum(
            1 if key not in before or key not in after else _count_changes(before[key], after[key])
            for key in before.keys() | after.keys()
        )
    if isinstance(before, list):
        if len(before) != len(after):
            return 1
        return sum(_count_changes(a, b) for a, b in zip(before, after))
    return 0 if before == after else 1


def _validate_game_targets(request: ImportRequest) -> None:
    dat = PurePosixPath(request.game_dat)
    bak = PurePosixPath(request.game_backup)
    required_parent = PurePosixPath("files/No_Backup")
    if dat.name != "pp.dat" or dat.parent != required_parent:
        raise ToolError(f"game_dat 必须是 files/No_Backup/pp.dat，当前：{request.game_dat}")
    if bak.name != "pp.dat.bak" or bak.parent != required_parent:
        raise ToolError(f"game_backup 必须是 files/No_Backup/pp.dat.bak，当前：{request.game_backup}")


@dataclass(slots=True)
class ImportService:
    request: ImportRequest
    _bridge: AndroidBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.request.paths.work_dir.mkdir(parents=True, exist_ok=True)
        _validate_game_targets(self.request)
        self._bridge = AndroidBridge(self.request.package, self.request.rish)

    def _build_bin(self) -> bytes:
        paths = self.request.paths
        print("\n===== STEP 1/4: 从 pp.dat 恢复 RTON 类型模板 =====")
        if not paths.base_dat.is_file():
            raise FileNotFoundError(f"找不到原始 pp.dat：{paths.base_dat}")
        if not paths.changed_json.is_file():
            raise FileNotFoundError(f"找不到 pp.json：{paths.changed_json}")

        template_data = decrypt_pp(paths.base_dat.read_bytes(), str(paths.base_dat))
        if not template_data.startswith(b"RTON"):
            raise ToolError(f"原始 pp.dat 解密后不是 RTON：head={template_data[:16]!r}")
        try:
            version, template_root = TypedRTONReader(template_data).document()
        except RTONError as exc:
            raise ToolError(f"原始 pp.dat 中的 RTON 解析失败：\n{exc}") from exc

        changed_json = json.loads(paths.changed_json.read_text(encoding="utf-8"))
        original_json = {"_rton_version": version, **node_to_value(template_root)}
        print("template RTON version:", version)
        print("detected changed values:", _count_changes(original_json, changed_json))

        print("\n===== STEP 2/4: pp.json -> changed.bin =====")
        try:
            new_bin = build_rton(version, template_root, changed_json)
        except RTONError as exc:
            raise ToolError(f"JSON -> RTON 失败：\n{exc}") from exc
        atomic_write_bytes(paths.output_bin, new_bin)

        try:
            check_version, check_root = TypedRTONReader(new_bin).document()
        except RTONError as exc:
            raise ToolError(f"生成的 changed.bin 无法重新解析：\n{exc}") from exc
        roundtrip_json = {"_rton_version": check_version, **node_to_value(check_root)}
        if roundtrip_json != changed_json:
            raise ToolError("changed.bin 重新解析后的 JSON 与输入 pp.json 不一致")
        print("RTON round-trip validation: OK")
        print("changed.bin size:", len(new_bin))
        print("changed.bin head:", new_bin[:16])
        return new_bin

    def _build_dat(self, new_bin: bytes) -> bytes:
        paths = self.request.paths
        print("\n===== STEP 3/4: changed.bin -> changed.dat =====")
        new_dat = encrypt_pp(new_bin, str(paths.changed_json))
        atomic_write_bytes(paths.output_dat, new_dat)
        if decrypt_pp(new_dat, str(paths.output_dat)) != new_bin:
            raise ToolError("changed.dat 解密回来与 changed.bin 不一致")
        print("Rijndael encrypt/decrypt validation: OK")
        print("changed.dat size :", len(new_dat))
        print("changed.dat head :", new_dat[:16].hex(" "))
        print("sha256           :", sha256_file(paths.output_dat))
        return new_dat

    def _write_game(self) -> None:
        paths = self.request.paths
        print("\n===== STEP 4/4: 校验并覆盖游戏存档 =====")
        base_sha = sha256_file(paths.base_dat)
        live_sha = self._bridge.private_sha256(self.request.game_dat, paths.work_dir, required=True)
        print("base :", base_sha)
        print("live :", live_sha)
        if live_sha != base_sha:
            raise ToolError(
                "当前游戏 pp.dat 已经和本地原始 pp.dat 不一致；"
                "为避免旧 JSON 覆盖新进度，本次导入中止"
            )

        if self.request.force_stop_game:
            self._bridge.force_stop()
            live_after_stop = self._bridge.private_sha256(
                self.request.game_dat, paths.work_dir, required=True
            )
            if live_after_stop != base_sha:
                raise ToolError("停止游戏后重新校验发现 pp.dat 已变化，本次导入中止")

        backup_dir = self._bridge.snapshot_private_files(
            paths.work_dir,
            self.request.game_dat,
            self.request.game_backup if self.request.write_game_backup else None,
        )
        expected_sha = sha256_file(paths.output_dat)
        self._bridge.write_shared_to_private(paths.output_dat, self.request.game_dat)
        if self.request.write_game_backup:
            self._bridge.write_shared_to_private(paths.output_dat, self.request.game_backup)

        written_dat_sha = self._bridge.private_sha256(
            self.request.game_dat, paths.work_dir, required=True
        )
        if written_dat_sha != expected_sha:
            raise ToolError(
                "写入后的 pp.dat SHA256 不一致。\n"
                f"expected={expected_sha}\nactual={written_dat_sha}\nbackup={backup_dir}"
            )
        if self.request.write_game_backup:
            written_bak_sha = self._bridge.private_sha256(
                self.request.game_backup, paths.work_dir, required=True
            )
            if written_bak_sha != expected_sha:
                raise ToolError(
                    "写入后的 pp.dat.bak SHA256 不一致。\n"
                    f"expected={expected_sha}\nactual={written_bak_sha}\nbackup={backup_dir}"
                )
        print("\n===== IMPORT OK =====")
        print("game pp.dat sha256:", written_dat_sha)
        print("backup directory   :", backup_dir)

    def run(self):
        paths = self.request.paths
        print("PVZ2 pp.json -> changed.bin -> changed.dat -> game")
        print("base pp.dat :", paths.base_dat)
        print("changed json:", paths.changed_json)
        print("output bin  :", paths.output_bin)
        print("output dat  :", paths.output_dat)
        new_bin = self._build_bin()
        self._build_dat(new_bin)
        if self.request.build_only:
            print("\n===== BUILD ONLY OK =====")
            print("BIN:", paths.output_bin)
            print("DAT:", paths.output_dat)
            return paths.output_dat
        self._write_game()
        return paths.output_dat
