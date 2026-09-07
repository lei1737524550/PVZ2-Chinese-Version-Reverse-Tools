"""植物等级与碎片完整性摘要规则。"""

from __future__ import annotations

import hashlib
from typing import Any

from domain.errors import ToolError
from domain.profile import require_int


def _require_pcpid(pcpid: str) -> str:
    value = str(pcpid).strip()
    if not value:
        raise ToolError("PCPID 为空")
    return value


def _common(data: dict[str, Any]) -> tuple[int, str]:
    rs = require_int(data.get("rs"), "PlayerInfo.rs")
    snuuid = data.get("snuuid")
    if not isinstance(snuuid, str):
        raise ToolError("PlayerInfo.snuuid 必须是字符串")
    return rs, snuuid


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def serialize_psla(data: dict[str, Any]) -> str:
    psla = data.get("psla")
    if not isinstance(psla, list):
        raise ToolError("PlayerInfo.psla 必须是数组")
    parts: list[str] = []
    for index, item in enumerate(psla):
        if not isinstance(item, dict):
            raise ToolError(f"psla[{index}] 必须是对象")
        plant_id = require_int(item.get("icpi"), f"psla[{index}].icpi", minimum=1)
        level = require_int(item.get("icl"), f"psla[{index}].icl", minimum=1)
        parts.append(f"{plant_id}_{level}")
    return "".join(parts)


def serialize_ppr(data: dict[str, Any]) -> str:
    ppr = data.get("ppr")
    if not isinstance(ppr, list):
        raise ToolError("PlayerInfo.ppr 必须是数组")
    parts: list[str] = []
    for index, item in enumerate(ppr):
        if not isinstance(item, dict):
            raise ToolError(f"ppr[{index}] 必须是对象")
        plant_id = require_int(item.get("pi"), f"ppr[{index}].pi", minimum=1)
        count = require_int(item.get("pc"), f"ppr[{index}].pc", minimum=0)
        parts.append(f"{plant_id}_{count}")
    return "".join(parts)


def calculate_psls(data: dict[str, Any], pcpid: str) -> str:
    pcpid = _require_pcpid(pcpid)
    rs, snuuid = _common(data)
    raw = f"dja{pcpid}DM&{rs}Oc{serialize_psla(data)}-@ow{snuuid}o2"
    return _md5(raw)


def calculate_pprs(data: dict[str, Any], pcpid: str) -> str:
    pcpid = _require_pcpid(pcpid)
    rs, snuuid = _common(data)
    raw = f"Owe{pcpid}_(sd{rs}NNlsd{serialize_ppr(data)}55{snuuid}"
    return _md5(raw)


def verify_psls(data: dict[str, Any], pcpid: str) -> tuple[bool, str, str]:
    actual = data.get("psls")
    if not isinstance(actual, str):
        raise ToolError("PlayerInfo.psls 必须是字符串")
    expected = calculate_psls(data, pcpid)
    return actual.lower() == expected, actual, expected


def verify_pprs(data: dict[str, Any], pcpid: str) -> tuple[bool, str, str]:
    actual = data.get("pprs")
    if not isinstance(actual, str):
        raise ToolError("PlayerInfo.pprs 必须是字符串")
    expected = calculate_pprs(data, pcpid)
    return actual.lower() == expected, actual, expected
