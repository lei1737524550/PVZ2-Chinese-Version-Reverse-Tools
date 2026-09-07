"""PCPID 查看与自动刷新服务。"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import SETTINGS
from infrastructure.project_context import PCPID_FILE, read_pcpid, refresh_pcpid


@dataclass(slots=True)
class PCPIDService:
    package: str | None = None
    rish: str | None = None

    def refresh(self) -> str:
        package = self.package or SETTINGS.android.package
        rish = self.rish or SETTINGS.android.rish
        old = read_pcpid()
        new = refresh_pcpid(package, rish)
        print(f"PCPID：{new}")
        if old and old != new:
            print(f"旧值：{old}")
        print(f"保存：{PCPID_FILE}")
        return new

    def show(self) -> str:
        value = read_pcpid()
        print(f"PCPID：{value or '（空）'}")
        print(f"路径：{PCPID_FILE}")
        return value
