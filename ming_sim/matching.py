"""地区/军队名称模糊匹配。L1（仅依赖 models + re）。

接受 regions/armies 字典作参数——不持全局态，db 与 context 都可调用。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ming_sim.models import Army, Region


def compact_name(value: str) -> str:
    return re.sub(r"[\s/／、，。,.：:；;（）()《》<>-]+", "", value)


# 单一真源：region_aliases / 旧档 location 归一 / 在京判断共用，禁止他处再抄一份。
REGION_SPECIAL_ALIASES: Dict[str, Tuple[str, ...]] = {
    "beizhili": ("北直隶", "京师", "北京", "beijing", "顺天", "直隶"),
    "nanzhili": ("南直隶", "南京", "江南", "应天", "南都"),
    "shaanxi": ("陕西", "陕地", "西安"),
    "huguang": ("湖广", "荆楚"),
    "fujian": ("福建", "闽地"),
    "guangdong": ("广东", "粤地"),
    "guangxi": ("广西", "桂地"),
}


def resolve_special_region_alias(token: str) -> Optional[str]:
    """Exact id or special-alias token → region_id；未知返回 None（不模糊匹配）。"""
    raw = str(token or "").strip()
    if not raw:
        return None
    if raw in REGION_SPECIAL_ALIASES:
        return raw
    key = compact_name(raw)
    if not key:
        return None
    if key in REGION_SPECIAL_ALIASES:
        return key
    for region_id, aliases in REGION_SPECIAL_ALIASES.items():
        if key == compact_name(region_id):
            return region_id
        for alias in aliases:
            if key == compact_name(alias):
                return region_id
    return None


def canonicalize_location_region_id(location: str) -> str:
    """人物 location 归一：空串保持空；特殊别名写回 region_id；其余原样。"""
    raw = str(location or "").strip()
    if not raw:
        return ""
    resolved = resolve_special_region_alias(raw)
    return resolved if resolved is not None else raw


def is_capital_location(location: str) -> bool:
    """明确在京（beizhili 或其别名）。空 location 不算在京——fail-open 仅 admission 自决。"""
    return canonicalize_location_region_id(location) == "beizhili"


def region_aliases(region: Region) -> List[str]:
    aliases = [region.id, region.name, compact_name(region.name)]
    for part in re.split(r"\s*/\s*|\s*／\s*", region.name):
        if part.strip():
            aliases.append(part.strip())
    aliases.extend(REGION_SPECIAL_ALIASES.get(region.id, ()))
    unique: List[str] = []
    seen: set = set()
    for alias in aliases:
        key = compact_name(alias)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(alias)
    return unique


def canonical_region_id_exact(
    raw: object, regions: Dict[str, Region],
) -> Optional[str]:
    """location 写缝专用：仅 compact 精确等值（id/name/region_aliases）。

    空串 → ''；未知非空 → None（调用方 fail-loud）。
    禁止子串/模糊；不调用 match_region_id_from_text。
    """
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    key = compact_name(text)
    if not key:
        return ""
    for region in regions.values():
        candidates = [region.id, region.name, *region_aliases(region)]
        for alias in candidates:
            if compact_name(alias) == key:
                return region.id
    return None


def match_region_id_from_text(text: str, regions: Dict[str, Region]) -> Optional[str]:
    cleaned = compact_name(text)
    if not cleaned:
        return None
    matches: List[Tuple[int, str]] = []
    for region in regions.values():
        score = 0
        for alias in region_aliases(region):
            alias_key = compact_name(alias)
            if cleaned == alias_key:
                score = max(score, 120)
            elif alias_key and alias_key in cleaned:
                score = max(score, 80 + len(alias_key))
            elif cleaned in alias_key:
                score = max(score, 45 + len(cleaned))
        if score:
            matches.append((score, region.id))
    if not matches:
        return None
    matches.sort(reverse=True, key=lambda item: item[0])
    if len(matches) == 1 or matches[0][0] >= matches[1][0] + 8:
        return matches[0][1]
    return None


def army_aliases(army: Army) -> List[str]:
    aliases = [
        army.id,
        army.name,
        compact_name(army.name),
        army.station,
        army.theater,
        army.commander,
        army.controller,
    ]
    for part in re.split(r"\s*/\s*|\s*／\s*", army.name):
        if part.strip():
            aliases.append(part.strip())
    special = {
        "jingying": ["京营", "京军", "京师兵", "京畿兵"],
        "guanning": ["关宁", "宁锦", "辽东军", "关宁军", "宁锦防线", "袁军"],
        "shanhaiguan": ["山海关", "关门守军", "山海关守军"],
        "xuan_da": ["宣大", "宣府", "大同", "宣大边军"],
        "jizhen": ["蓟镇", "蓟镇兵"],
        "denglai": ["登莱", "登莱兵", "山东水师"],
        "dongjiang": ["东江", "皮岛", "东江镇"],
        "shaanxi_army": ["陕西兵", "陕西边军", "西北边军"],
        "nanjing_garrison": ["南京兵", "南京守备", "南兵", "南京守备军"],
        "fujian_navy": ["福建水师", "闽海水师"],
        "guangdong_navy": ["广东水师", "南海水师"],
        "southwest_tusi": ["土司兵", "西南土司", "西南土兵"],
    }
    aliases.extend(special.get(army.id, []))
    unique: List[str] = []
    seen: set = set()
    for alias in aliases:
        key = compact_name(alias)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(alias)
    return unique


def match_army_id_from_text(text: str, armies: Dict[str, Army]) -> Optional[str]:
    cleaned = compact_name(text)
    if not cleaned:
        return None
    matches: List[Tuple[int, str]] = []
    for army in armies.values():
        score = 0
        for alias in army_aliases(army):
            alias_key = compact_name(alias)
            if cleaned == alias_key:
                score = max(score, 125)
            elif alias_key and alias_key in cleaned:
                score = max(score, 80 + len(alias_key))
            elif cleaned in alias_key:
                score = max(score, 45 + len(cleaned))
        if score:
            matches.append((score, army.id))
    if not matches:
        return None
    matches.sort(reverse=True, key=lambda item: item[0])
    if len(matches) == 1 or matches[0][0] >= matches[1][0] + 8:
        return matches[0][1]
    return None
