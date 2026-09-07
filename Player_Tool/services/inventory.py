"""植物、植物碎片与植物等级的统一增删改查服务。"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import SETTINGS
from infrastructure.project_context import refresh_pcpid, resolve_pcpid
from domain.catalog import Catalog, load_catalog
from domain.errors import ToolError
from domain.inventory import (
    add_plant,
    find_orphan_levels,
    remove_level,
    remove_pieces,
    remove_plant,
    repair_orphan_levels,
    set_level,
    set_pieces,
)
from domain.models import InventoryRequest
from domain.profile import get_player_info, plant_state, require_int, validate_plant_structures
from domain.signatures import calculate_pprs, calculate_psls, verify_pprs, verify_psls
from infrastructure.files import atomic_write_bytes, read_json, write_json_atomic


class _SignatureMismatch(ToolError):
    """当前 PCPID 不能验证目标签名；用于触发一次自动刷新。"""


@dataclass(slots=True)
class InventoryService:
    request: InventoryRequest
    catalog: Catalog | None = None

    def __post_init__(self) -> None:
        if self.catalog is None:
            self.catalog = load_catalog()

    def _describe(self, plant_id: int) -> str:
        assert self.catalog is not None
        return self.catalog.describe_plant(plant_id)

    def _load(self):
        path = self.request.json_path.expanduser()
        root = read_json(path)
        data = get_player_info(root)
        validate_plant_structures(data)
        return path, root, data

    def _resolve_pcpid(self) -> str:
        return resolve_pcpid(
            self.request.pcpid,
            package=SETTINGS.android.package,
            rish=SETTINGS.android.rish,
            auto_discover=True,
        )

    @staticmethod
    def _require_signature(data, pcpid: str, kind: str) -> None:
        if kind == "psls":
            ok, actual, expected = verify_psls(data, pcpid)
        elif kind == "pprs":
            ok, actual, expected = verify_pprs(data, pcpid)
        else:
            raise AssertionError(kind)
        if not ok:
            raise _SignatureMismatch(
                f"当前 {kind} 校验失败。\n"
                f"文件值：{actual}\n计算值：{expected}"
            )

    def query(self) -> bool:
        _, _, data = self._load()
        plant_id = require_int(self.request.plant_id, "植物 JSON ID", minimum=1)
        state = plant_state(data, plant_id)
        print(self._describe(plant_id))
        print(f"  拥有：{'是' if state.owned else '否'}（p 中 {state.owned_count} 条）")
        print(f"  等级：{list(state.levels) if state.levels else '无记录'}")
        print(f"  碎片：{list(state.piece_counts) if state.piece_counts else '无记录'}")
        return False

    def _write_and_verify(self, path, root, original: bytes, data, pcpid: str, signatures: frozenset[str]) -> None:
        if "psls" in signatures:
            data["psls"] = calculate_psls(data, pcpid)
        if "pprs" in signatures:
            data["pprs"] = calculate_pprs(data, pcpid)
        try:
            write_json_atomic(path, root, indent=2)
            checked = get_player_info(read_json(path))
            validate_plant_structures(checked)
            if "psls" in signatures:
                ok, actual, expected = verify_psls(checked, pcpid)
                if not ok:
                    raise ToolError(f"写回后 psls 验证失败：{actual} != {expected}")
            if "pprs" in signatures:
                ok, actual, expected = verify_pprs(checked, pcpid)
                if not ok:
                    raise ToolError(f"写回后 pprs 验证失败：{actual} != {expected}")
        except Exception:
            atomic_write_bytes(path, original)
            raise

    def _mutate(self, operation) -> bool:
        path, root, data = self._load()
        pcpid = self._resolve_pcpid()
        try:
            signatures = operation(data, pcpid)
        except _SignatureMismatch as first_error:
            # 显式 --pcpid 属于用户本次强制覆盖，不擅自替换。
            if self.request.pcpid is not None and str(self.request.pcpid).strip():
                raise ToolError(
                    f"{first_error}\n显式指定的 PCPID 无法验证当前 pp.json。"
                ) from first_error
            print("当前 PCPID 与 pp.json 签名不匹配，正在自动刷新 PCPID...")
            try:
                pcpid = refresh_pcpid(SETTINGS.android.package, SETTINGS.android.rish)
            except Exception as exc:
                raise ToolError(
                    f"{first_error}\n自动刷新 PCPID 失败：{exc}"
                ) from exc
            try:
                signatures = operation(data, pcpid)
            except _SignatureMismatch as second_error:
                raise ToolError(
                    f"自动刷新后的 PCPID 仍无法验证当前 pp.json。\n{second_error}"
                ) from second_error
        if signatures is None:
            return False
        original = path.read_bytes()
        self._write_and_verify(path, root, original, data, pcpid, signatures)
        print(f"完成：{path}")
        return True

    def run_plant(self) -> bool:
        if self.request.action == "query":
            return self.query()
        plant_id = require_int(self.request.plant_id, "植物 JSON ID", minimum=1)

        def operation(data, pcpid: str):
            self._require_signature(data, pcpid, "psls")
            if self.request.action == "add":
                changed = add_plant(data, plant_id)
                if not changed:
                    print(f"{self._describe(plant_id)} 已拥有，无需修改")
                    return None
                print(f"添加植物：{self._describe(plant_id)}")
            elif self.request.action == "remove":
                removed_p, removed_levels = remove_plant(data, plant_id)
                if removed_p == 0 and removed_levels == 0:
                    print(f"{self._describe(plant_id)} 不存在，无需删除")
                    return None
                print(
                    f"删除植物：{self._describe(plant_id)} | "
                    f"p 删除 {removed_p} 条，psla 删除 {removed_levels} 条"
                )
            else:
                raise ToolError(f"植物操作不支持：{self.request.action}")
            return frozenset({"psls"})

        return self._mutate(operation)

    def run_level(self) -> bool:
        if self.request.action == "query":
            return self.query()
        plant_id = require_int(self.request.plant_id, "植物 JSON ID", minimum=1)

        def operation(data, pcpid: str):
            self._require_signature(data, pcpid, "psls")
            if self.request.action == "set":
                level = require_int(self.request.value, "植物等级", minimum=1)
                old = set_level(data, plant_id, level)
                if old == level:
                    print(f"{self._describe(plant_id)} 已经是等级 {level}")
                    return None
                before = "无记录" if old is None else str(old)
                print(f"植物等级：{self._describe(plant_id)} | {before} -> {level}")
            elif self.request.action == "remove":
                removed = remove_level(data, plant_id)
                if removed == 0:
                    print(f"{self._describe(plant_id)} 没有等级记录")
                    return None
                print(f"删除等级：{self._describe(plant_id)} | 删除 {removed} 条")
            else:
                raise ToolError(f"等级操作不支持：{self.request.action}")
            return frozenset({"psls"})

        return self._mutate(operation)

    def run_pieces(self) -> bool:
        if self.request.action == "query":
            return self.query()
        plant_id = require_int(self.request.plant_id, "植物 JSON ID", minimum=1)

        def operation(data, pcpid: str):
            self._require_signature(data, pcpid, "pprs")
            if self.request.action == "set":
                count = require_int(self.request.value, "植物碎片数量", minimum=0)
                old = set_pieces(data, plant_id, count)
                if old == count:
                    print(f"{self._describe(plant_id)} 碎片已经是 {count}")
                    return None
                before = "无记录" if old is None else str(old)
                print(f"植物碎片：{self._describe(plant_id)} | {before} -> {count}")
            elif self.request.action == "remove":
                removed = remove_pieces(data, plant_id)
                if removed == 0:
                    print(f"{self._describe(plant_id)} 没有碎片记录")
                    return None
                print(f"删除碎片：{self._describe(plant_id)} | 删除 {removed} 条")
            else:
                raise ToolError(f"碎片操作不支持：{self.request.action}")
            return frozenset({"pprs"})

        return self._mutate(operation)

    def repair(self) -> bool:
        def operation(data, pcpid: str):
            self._require_signature(data, pcpid, "psls")
            before = find_orphan_levels(data)
            if not before:
                print("没有发现植物等级违法记录")
                return None
            removed = repair_orphan_levels(data)
            print(f"删除 {len(removed)} 条违法等级记录：")
            for item in removed:
                print(f"  {self._describe(item.plant_id)} | 等级 {item.level}")
            return frozenset({"psls"})

        return self._mutate(operation)

    def run(self) -> bool:
        entity = self.request.entity
        if entity == "plant":
            return self.run_plant()
        if entity == "level":
            return self.run_level()
        if entity == "pieces":
            return self.run_pieces()
        if entity == "repair":
            return self.repair()
        raise ToolError(f"未知植物数据类型：{entity}")
