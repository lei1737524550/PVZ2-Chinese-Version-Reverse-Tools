"""读取 Tool_2/table 中的字段表与植物表。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from domain.errors import ToolError

TOOL_ROOT = Path(__file__).resolve().parents[1]
TABLE_ROOT = TOOL_ROOT / "table"
PLANT_TABLE = TABLE_ROOT / "plants.json"
FIELD_TABLE = TABLE_ROOT / "json_fields.json"


@dataclass(frozen=True, slots=True)
class PlantInfo:
    json_id: int
    english_name: str
    chinese_name: str
    resource_id: int | None = None
    address: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.json_id} | {self.english_name} | {self.chinese_name}"


@dataclass(frozen=True, slots=True)
class FieldInfo:
    key: str
    name: str
    description: str
    value_type: str


class Catalog:
    """将 JSON ID 和字段缩写翻译为可读信息。"""

    def __init__(self, plants: dict[int, PlantInfo], fields: dict[str, FieldInfo]) -> None:
        self._plants = plants
        self._fields = fields

    def plant(self, json_id: int) -> PlantInfo | None:
        return self._plants.get(json_id)

    def describe_plant(self, json_id: int) -> str:
        info = self.plant(json_id)
        if info is None:
            return f"{json_id} | <未知英文名> | <未知中文名>"
        return info.display_name

    def field(self, key: str) -> FieldInfo | None:
        return self._fields.get(key)

    def field_name(self, key: str) -> str:
        info = self.field(key)
        return info.name if info else key

    def known_plant_count(self) -> int:
        return len(self._plants)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"缺少数据表：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(
            f"数据表 JSON 格式错误：{path}，第 {exc.lineno} 行，第 {exc.colno} 列：{exc.msg}"
        ) from exc


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    raw_plants = _read_json(PLANT_TABLE)
    raw_fields = _read_json(FIELD_TABLE)
    if not isinstance(raw_plants, list):
        raise ToolError("plants.json 顶层必须是数组")
    if not isinstance(raw_fields, dict):
        raise ToolError("json_fields.json 顶层必须是对象")

    plants: dict[int, PlantInfo] = {}
    for index, row in enumerate(raw_plants):
        if not isinstance(row, dict):
            raise ToolError(f"plants.json[{index}] 必须是对象")
        try:
            json_id = int(row["json_id"])
            english = str(row["english_name"])
            chinese = str(row["chinese_name"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolError(f"plants.json[{index}] 缺少有效字段") from exc
        resource_raw = row.get("resource_id")
        resource_id = int(resource_raw) if resource_raw is not None else None
        address_raw = row.get("address")
        plants[json_id] = PlantInfo(
            json_id=json_id,
            english_name=english,
            chinese_name=chinese,
            resource_id=resource_id,
            address=str(address_raw) if address_raw else None,
        )

    fields: dict[str, FieldInfo] = {}
    for key, row in raw_fields.items():
        if not isinstance(row, dict):
            raise ToolError(f"json_fields.json[{key!r}] 必须是对象")
        fields[str(key)] = FieldInfo(
            key=str(key),
            name=str(row.get("name", key)),
            description=str(row.get("description", "")),
            value_type=str(row.get("value_type", "")),
        )
    return Catalog(plants, fields)
