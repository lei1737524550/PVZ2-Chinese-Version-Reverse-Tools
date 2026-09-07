"""植物、碎片和等级的纯数据操作。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.errors import ToolError
from domain.profile import level_entries, owned_ids, piece_entries, require_int


@dataclass(frozen=True, slots=True)
class RepairItem:
    plant_id: int
    level: int


def add_plant(data: dict[str, Any], plant_id: int, *, default_level: int = 1) -> bool:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    default_level = require_int(default_level, "默认等级", minimum=1)

    changed = False
    owned = data["p"]
    occurrences = [i for i, value in enumerate(owned) if value == plant_id]
    if not occurrences:
        owned.append(plant_id)
        changed = True
    elif len(occurrences) > 1:
        first = occurrences[0]
        data["p"] = [
            value for index, value in enumerate(owned)
            if value != plant_id or index == first
        ]
        changed = True

    levels = level_entries(data, plant_id)
    if not levels:
        data["psla"].append({"icpi": plant_id, "icl": default_level})
        changed = True
    elif len(levels) > 1:
        seen = False
        normalized: list[Any] = []
        for item in data["psla"]:
            if isinstance(item, dict) and item.get("icpi") == plant_id:
                if seen:
                    changed = True
                    continue
                seen = True
            normalized.append(item)
        data["psla"] = normalized
    return changed


def remove_plant(data: dict[str, Any], plant_id: int) -> tuple[int, int]:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    before_p = len(data["p"])
    before_levels = len(data["psla"])
    data["p"] = [value for value in data["p"] if value != plant_id]
    data["psla"] = [
        item for item in data["psla"]
        if not (isinstance(item, dict) and item.get("icpi") == plant_id)
    ]
    return before_p - len(data["p"]), before_levels - len(data["psla"])


def set_level(data: dict[str, Any], plant_id: int, level: int) -> int | None:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    level = require_int(level, "植物等级", minimum=1)
    if plant_id not in owned_ids(data):
        raise ToolError(f"植物 {plant_id} 未拥有，拒绝创建等级记录")

    matches = level_entries(data, plant_id)
    if len(matches) > 1:
        raise ToolError(f"psla 中植物 {plant_id} 出现 {len(matches)} 条等级记录，拒绝猜测")
    if not matches:
        data["psla"].append({"icpi": plant_id, "icl": level})
        return None
    old = int(matches[0]["icl"])
    matches[0]["icl"] = level
    return old


def remove_level(data: dict[str, Any], plant_id: int) -> int:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    if plant_id in owned_ids(data):
        raise ToolError("已拥有植物不能单独删除等级；如需删除植物请使用植物删除")
    before = len(data["psla"])
    data["psla"] = [
        item for item in data["psla"]
        if not (isinstance(item, dict) and item.get("icpi") == plant_id)
    ]
    return before - len(data["psla"])


def set_pieces(data: dict[str, Any], plant_id: int, count: int) -> int | None:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    count = require_int(count, "植物碎片数量", minimum=0)
    matches = piece_entries(data, plant_id)
    if len(matches) > 1:
        raise ToolError(f"ppr 中植物 {plant_id} 出现 {len(matches)} 条碎片记录，拒绝猜测")
    if not matches:
        data["ppr"].append({"pi": plant_id, "pc": count})
        return None
    old = int(matches[0]["pc"])
    matches[0]["pc"] = count
    return old


def remove_pieces(data: dict[str, Any], plant_id: int) -> int:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    before = len(data["ppr"])
    data["ppr"] = [
        item for item in data["ppr"]
        if not (isinstance(item, dict) and item.get("pi") == plant_id)
    ]
    return before - len(data["ppr"])


def find_orphan_levels(data: dict[str, Any]) -> list[RepairItem]:
    owned = set(owned_ids(data))
    orphans: list[RepairItem] = []
    for item in level_entries(data):
        plant_id = int(item["icpi"])
        if plant_id not in owned:
            orphans.append(RepairItem(plant_id=plant_id, level=int(item["icl"])))
    return orphans


def repair_orphan_levels(data: dict[str, Any]) -> list[RepairItem]:
    orphans = find_orphan_levels(data)
    if not orphans:
        return []
    owned = set(owned_ids(data))
    kept: list[Any] = []
    for index, item in enumerate(data["psla"]):
        if not isinstance(item, dict):
            raise ToolError(f"psla[{index}] 必须是对象")
        plant_id = require_int(item.get("icpi"), f"psla[{index}].icpi", minimum=1)
        if plant_id in owned:
            kept.append(item)
    data["psla"] = kept
    return orphans
