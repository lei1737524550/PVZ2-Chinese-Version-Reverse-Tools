"""pp.json PlayerInfo 的定位、校验与基础数据访问。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.errors import ToolError


@dataclass(frozen=True, slots=True)
class PlantState:
    json_id: int
    owned_count: int
    levels: tuple[int, ...]
    piece_counts: tuple[int, ...]

    @property
    def owned(self) -> bool:
        return self.owned_count > 0


def require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{label} 必须是整数")
    if minimum is not None and value < minimum:
        raise ToolError(f"{label} 必须 >= {minimum}")
    return value


def get_player_info(root: Any) -> dict[str, Any]:
    objects = root.get("objects") if isinstance(root, dict) else None
    if not isinstance(objects, list):
        raise ToolError("找不到 objects 数组")
    for obj in objects:
        if (
            isinstance(obj, dict)
            and obj.get("objclass") == "PlayerInfo"
            and isinstance(obj.get("objdata"), dict)
        ):
            return obj["objdata"]
    raise ToolError("找不到 objclass=PlayerInfo 的 objdata")


def validate_plant_structures(data: dict[str, Any]) -> None:
    for key in ("p", "psla", "ppr"):
        if not isinstance(data.get(key), list):
            raise ToolError(f"PlayerInfo.{key} 必须是数组")
    for key in ("rs", "snuuid", "psls", "pprs"):
        if key not in data:
            raise ToolError(f"PlayerInfo 中找不到 {key}")


def owned_ids(data: dict[str, Any]) -> list[int]:
    owned = data.get("p")
    if not isinstance(owned, list):
        raise ToolError("PlayerInfo.p 必须是数组")
    result: list[int] = []
    for index, value in enumerate(owned):
        result.append(require_int(value, f"p[{index}]", minimum=1))
    return result


def level_entries(data: dict[str, Any], plant_id: int | None = None) -> list[dict[str, Any]]:
    psla = data.get("psla")
    if not isinstance(psla, list):
        raise ToolError("PlayerInfo.psla 必须是数组")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(psla):
        if not isinstance(item, dict):
            raise ToolError(f"psla[{index}] 必须是对象")
        pid = require_int(item.get("icpi"), f"psla[{index}].icpi", minimum=1)
        require_int(item.get("icl"), f"psla[{index}].icl", minimum=1)
        if plant_id is None or pid == plant_id:
            result.append(item)
    return result


def piece_entries(data: dict[str, Any], plant_id: int | None = None) -> list[dict[str, Any]]:
    ppr = data.get("ppr")
    if not isinstance(ppr, list):
        raise ToolError("PlayerInfo.ppr 必须是数组")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(ppr):
        if not isinstance(item, dict):
            raise ToolError(f"ppr[{index}] 必须是对象")
        pid = require_int(item.get("pi"), f"ppr[{index}].pi", minimum=1)
        require_int(item.get("pc"), f"ppr[{index}].pc", minimum=0)
        if plant_id is None or pid == plant_id:
            result.append(item)
    return result


def plant_state(data: dict[str, Any], plant_id: int) -> PlantState:
    plant_id = require_int(plant_id, "植物 JSON ID", minimum=1)
    owned = owned_ids(data)
    levels = tuple(int(item["icl"]) for item in level_entries(data, plant_id))
    pieces = tuple(int(item["pc"]) for item in piece_entries(data, plant_id))
    return PlantState(
        json_id=plant_id,
        owned_count=sum(1 for value in owned if value == plant_id),
        levels=levels,
        piece_counts=pieces,
    )
