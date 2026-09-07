"""pp.json 差分报告；植物相关 ID 自动查 table 补全名称。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.catalog import Catalog, load_catalog
from domain.models import DiffRequest
from domain.profile import get_player_info
from infrastructure.files import read_json


def _scalar_changes(a: Any, b: Any, path: str = "$") -> list[tuple[str, Any, Any]]:
    out: list[tuple[str, Any, Any]] = []
    if type(a) is not type(b):
        return [(path, a, b)]
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            child = f"{path}.{key}"
            if key not in a:
                out.append((child, "<MISSING>", b[key]))
            elif key not in b:
                out.append((child, a[key], "<MISSING>"))
            else:
                out.extend(_scalar_changes(a[key], b[key], child))
        return out
    if isinstance(a, list):
        for index, (old, new) in enumerate(zip(a, b)):
            out.extend(_scalar_changes(old, new, f"{path}[{index}]"))
        if len(a) != len(b):
            out.append((f"{path}.__len__", len(a), len(b)))
        return out
    if a != b:
        out.append((path, a, b))
    return out


def _keyed(items: Any, key: str) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if isinstance(item, dict) and key in item:
            result[item[key]] = item
    return result


@dataclass(slots=True)
class DiffService:
    request: DiffRequest
    catalog: Catalog | None = None

    def __post_init__(self) -> None:
        if self.catalog is None:
            self.catalog = load_catalog()

    def _plant_name(self, value: Any) -> str:
        if isinstance(value, int) and not isinstance(value, bool):
            assert self.catalog is not None
            return self.catalog.describe_plant(value)
        return repr(value)

    def _diff_owned(self, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        old = set(before.get("p", []) or [])
        new = set(after.get("p", []) or [])
        lines: list[str] = []
        for plant_id in sorted(new - old):
            lines.append(f"+ p：{self._plant_name(plant_id)}")
        for plant_id in sorted(old - new):
            lines.append(f"- p：{self._plant_name(plant_id)}")
        return lines

    def _diff_plant_records(
        self,
        name: str,
        before: dict[str, Any],
        after: dict[str, Any],
        *,
        id_key: str,
        value_key: str,
    ) -> list[str]:
        old_map = _keyed(before.get(name), id_key)
        new_map = _keyed(after.get(name), id_key)
        lines: list[str] = []
        for plant_id in sorted(set(old_map) | set(new_map), key=str):
            old = old_map.get(plant_id)
            new = new_map.get(plant_id)
            label = self._plant_name(plant_id)
            if old is None:
                lines.append(f"+ {name}：{label} | {value_key}={new.get(value_key)!r}")
                continue
            if new is None:
                lines.append(f"- {name}：{label} | {value_key}={old.get(value_key)!r}")
                continue
            old_value = old.get(value_key)
            new_value = new.get(value_key)
            if old_value != new_value:
                delta = ""
                if isinstance(old_value, int) and isinstance(new_value, int):
                    delta = f" | Δ={new_value - old_value:+d}"
                lines.append(
                    f"* {name}：{label} | {value_key}: {old_value!r} -> {new_value!r}{delta}"
                )
        return lines

    def run(self):
        before_doc = read_json(self.request.before)
        after_doc = read_json(self.request.after)
        before = get_player_info(before_doc)
        after = get_player_info(after_doc)
        lines = [
            "PVZ2 pp.json 差分报告",
            "=" * 60,
            f"before: {self.request.before}",
            f"after : {self.request.after}",
            "",
            "===== 植物相关变化 =====",
        ]
        lines += self._diff_owned(before, after)
        lines += self._diff_plant_records(
            "psla", before, after, id_key="icpi", value_key="icl"
        )
        lines += self._diff_plant_records(
            "ppr", before, after, id_key="pi", value_key="pc"
        )
        if lines[-1] == "===== 植物相关变化 =====":
            lines.append("(无)")

        lines.extend(["", "===== 全部标量变化 ====="])
        changes = _scalar_changes(before, after, "$.objdata")
        if not changes:
            lines.append("(无)")
        else:
            for path, old, new in changes:
                line = f"{path}: {old!r} -> {new!r}"
                if (
                    isinstance(old, int) and not isinstance(old, bool)
                    and isinstance(new, int) and not isinstance(new, bool)
                ):
                    line += f"  Δ={new - old:+d}"
                lines.append(line)

        text = "\n".join(lines) + "\n"
        self.request.output.parent.mkdir(parents=True, exist_ok=True)
        self.request.output.write_text(text, encoding="utf-8")
        print(text, end="")
        print(f"已写入：{self.request.output}")
        return self.request.output
