"""pp.dat 导出业务流程。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from formats.pp_dat import decrypt_pp, key_description, validate_dat
from formats.rton_reader import decode_rton_document
from domain.errors import ToolError
from domain.models import ExportRequest
from infrastructure.android import AndroidBridge
from infrastructure.files import atomic_write_bytes, atomic_write_text, file_info
from services.inspect import InspectService


@dataclass(slots=True)
class ExportService:
    request: ExportRequest
    _bridge: AndroidBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.request.paths.work_dir.mkdir(parents=True, exist_ok=True)
        self._bridge = AndroidBridge(self.request.package, self.request.rish)

    def acquire_dat(self) -> Path:
        """从游戏私有目录提取一致性 pp.dat 快照。"""
        target = self.request.paths.dat
        print("===== STEP 1/3: 获取 pp.dat =====")
        print("package :", self.request.package)
        print("source  :", self.request.game_path)
        print("output  :", target)
        self._bridge.copy_snapshot_to_shared(self.request.game_path, target)
        data = target.read_bytes()
        cipher_length = validate_dat(data)
        print("\npp.dat 获取成功")
        print("info   :", file_info(target))
        print("head   :", data[:16].hex(" "))
        print(
            f"验证通过：ciphertext={cipher_length} bytes，"
            f"{cipher_length // 24} blocks"
        )
        return target

    def dat_to_bin(self) -> Path:
        """解密 pp.dat 并生成明文 RTON。"""
        source = self.request.paths.dat
        target = self.request.paths.bin
        print("\n===== STEP 2/3: pp.dat -> pp.bin =====")
        if not source.is_file():
            raise FileNotFoundError(f"找不到 {source}")
        plain = decrypt_pp(source.read_bytes(), str(source)).rstrip(b"\x00")
        if not plain.startswith(b"RTON"):
            raise ToolError(f"解密结果不是 RTON：head={plain[:32]!r}")
        atomic_write_bytes(target, plain)
        key_text, iv = key_description()
        print("pp.bin 生成成功")
        print("input  :", source)
        print("output :", target)
        print("size   :", len(plain))
        print("key    :", key_text)
        print("iv     :", iv)
        print("head   :", plain[:32])
        print("验证通过：RTON header 正常。")
        return target

    def bin_to_json(self) -> Path:
        """解析明文 RTON 并生成 pp.json。"""
        source = self.request.paths.bin
        target = self.request.paths.json
        print("\n===== STEP 3/3: pp.bin -> pp.json =====")
        if not source.is_file():
            raise FileNotFoundError(f"找不到 {source}")
        obj = decode_rton_document(source.read_bytes())
        atomic_write_text(target, json.dumps(obj, ensure_ascii=False, indent=2))
        print("pp.json 生成成功")
        print("input  :", source)
        print("output :", target)
        print("size   :", target.stat().st_size)
        try:
            InspectService().print_document(obj, show_owned=20)
        except Exception as exc:
            print(f"核心数据读取失败：{exc}")
        return target

    def run(self) -> Path:
        """执行一次完整导出；本地输入可从 pp.dat 或 pp.bin 开始。"""
        source = self.request.source
        if source is None:
            self.acquire_dat()
            self.dat_to_bin()
        else:
            source = source.expanduser()
            if not source.is_file():
                raise FileNotFoundError(f"输入不存在：{source}")
            head = source.read_bytes()[:4]
            if head.startswith(b"\x10\x00"):
                if source.resolve() != self.request.paths.dat.resolve():
                    shutil.copy2(source, self.request.paths.dat)
                self.dat_to_bin()
            elif head == b"RTON":
                if source.resolve() != self.request.paths.bin.resolve():
                    shutil.copy2(source, self.request.paths.bin)
            else:
                raise ToolError("输入既不是 10 00 开头的 pp.dat，也不是 RTON 明文")

        output = self.bin_to_json()
        print(f"完成：{output}")
        return output
