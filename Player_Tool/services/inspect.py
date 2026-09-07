"""读取 pp.json 并以 table 数据表输出可读的核心信息。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain.catalog import Catalog, load_catalog
from domain.inventory import find_orphan_levels
from domain.profile import get_player_info, level_entries, owned_ids, piece_entries, validate_plant_structures
from infrastructure.files import read_json


@dataclass(slots=True)
class InspectService:
    catalog: Catalog | None = None

    def __post_init__(self) -> None:
        if self.catalog is None:
            self.catalog = load_catalog()

    def print_document(self, root: Any, *, show_owned: int = 20) -> None:
        catalog = self.catalog
        assert catalog is not None
        data = get_player_info(root)
        validate_plant_structures(data)
        owned = owned_ids(data)
        levels = level_entries(data)
        pieces = piece_entries(data)
        orphans = find_orphan_levels(data)

        print("\n===== pp.json 核心数据 =====")
        print(f"{catalog.field_name('p')} [p]：{len(owned)}")
        print(f"{catalog.field_name('psla')} [psla]：{len(levels)}")
        print(f"{catalog.field_name('ppr')} [ppr]：{len(pieces)}")
        print(f"{catalog.field_name('psls')} [psls]：{data.get('psls')}")
        print(f"{catalog.field_name('pprs')} [pprs]：{data.get('pprs')}")
        print(f"植物表记录数：{catalog.known_plant_count()}")

        unknown = sorted({plant_id for plant_id in owned if catalog.plant(plant_id) is None})
        if unknown:
            print("未知植物 JSON ID：" + ", ".join(map(str, unknown)))

        if show_owned > 0 and owned:
            print(f"\n已拥有植物（显示前 {min(show_owned, len(owned))} 项）：")
            for plant_id in owned[:show_owned]:
                print(f"  {catalog.describe_plant(plant_id)}")
            if len(owned) > show_owned:
                print(f"  ... 其余 {len(owned) - show_owned} 项未展开")

        if orphans:
            print(f"\n发现 {len(orphans)} 条植物等级违法记录（有等级但未拥有）：")
            for item in orphans:
                print(f"  {catalog.describe_plant(item.plant_id)} | 等级 {item.level}")
        else:
            print("\n植物等级违法记录：0")

    def run(self, path: Path, *, show_owned: int = 20) -> Path:
        root = read_json(path.expanduser())
        self.print_document(root, show_owned=show_owned)
        return path
