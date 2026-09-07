"""Canonical read projection for persisted participant rosters.

Also owns the raw-layer non-person participant name gate shared by manual
directive capture (#1279 / QA A-2) and night-archive involved_people projection
(#1331/#1339). Filter before canon — never after (司礼监→王承恩 trap).
"""

from __future__ import annotations

import json
from typing import Dict, List, Mapping

# ADR 0053 机械三档闭集（唯一真源）：归一缝、票拟层 A shape 与 prompt 契约共引，
# 禁第二份字面量。主办可多人（北极星实证：倪元璐＋黄道周合力清丈畿辅）。
PARTICIPANT_TIERS = ("主办", "协办", "知情")
PARTICIPANT_LEAD_TIER = "主办"

# 卫/司 类机关整词（单字留作姓、整词才判机关）。词表单源：assignee-hint 子串与
# 参与人裸机构 fullmatch 共用，防漂移。
INSTITUTION_PARTICIPANT_TOKENS = (
    "锦衣卫", "府军卫", "羽林卫", "金吾卫", "腾骧卫",
    "布政司", "按察司", "通政司", "通政使司", "都司", "市舶司", "盐课司",
    "北镇抚司", "南镇抚司", "镇抚司", "尚宝司", "行人司",
)

# #1279 / QA A-2 / #1391：raw 层三分流（canon 前判定，ADR 0053 缝不动）。
# ① 裸机构 token 整词 fullmatch → 非人
# ② 自称/泛称/集体通名闭集 → 非人（#1391 补「大臣」等）
# ③ 带姓称谓别名（韩阁老/毕户部…）→ 非①②，走 canon 留人名
NON_PERSON_PARTICIPANT_NAMES = frozenset({
    # 自称 / 帝称
    "陛下", "皇帝", "皇上", "圣上", "天子", "朝廷", "朕",
    # 泛称 / 集体通名（#1391 票面 + #1331/#1339 起居注混入）
    "大臣", "群臣", "众臣", "诸臣", "边将", "朝鲜边军",
})
# 明代中枢/部院寺监/厂卫 + 卫/司整词。fullmatch 闭集，不用单字 stop-class search。
BARE_INSTITUTION_PARTICIPANT_NAMES = frozenset({
    "吏部", "户部", "礼部", "兵部", "刑部", "工部",
    "内阁", "都察院", "六科", "翰林院", "詹事府",
    "大理寺", "太常寺", "太仆寺", "光禄寺", "鸿胪寺",
    "太医院", "钦天监", "国子监", "宗人府",
    "五军都督府", "都督府",
    "司礼监", "东厂", "西厂",
    "御马监", "内官监", "尚膳监", "司设监",
}) | frozenset(INSTITUTION_PARTICIPANT_TOKENS)


def is_non_person_participant_name(name: str) -> bool:
    """raw 层：裸机构整词 / 自称泛称集体 → 非人物参与人；带姓称谓别名放行走 canon。"""
    n = str(name or "").strip()
    if not n:
        return True
    if n in NON_PERSON_PARTICIPANT_NAMES:
        return True
    if n in BARE_INSTITUTION_PARTICIPANT_NAMES:
        return True
    return False


def resolve_dossier_owner_name(dossier: Mapping[str, object]) -> str:
    """案卷归属人：首名 canonical 主办，缺档时才读 legacy executor。

    #613 任别读端与 #625 监督事实底共调此单源；roster 解析禁止第三份遍历。
    缺档（无主办且无 executor）返回空串，由调用方按真除或缺席降级。
    """
    roster = dossier.get("participant_roster") or []
    if isinstance(roster, str):
        try:
            roster = json.loads(roster)
        except (TypeError, ValueError):
            # json.JSONDecodeError ⊂ ValueError
            roster = []
    if isinstance(roster, list):
        for entry in roster:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("tier") or "").strip() != "主办":
                continue
            name = str(entry.get("character_id") or "").strip()
            if name:
                return name
    executor_id = str(dossier.get("executor_id") or "").strip()
    executor_kind = str(dossier.get("executor_kind") or "").strip()
    if executor_id and executor_kind in {"", "character"}:
        return executor_id
    return ""


def participant_roster_names(raw: object) -> set[str]:
    """Project persisted dict roster entries to their character names."""
    try:
        roster = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(roster, list):
        return set()
    return {
        str(item.get("character_id") or item.get("name"))
        for item in roster
        if isinstance(item, dict) and (item.get("character_id") or item.get("name"))
    }


def project_execution_liability_parties(
    roster: object,
) -> List[Dict[str, object]]:
    """#565 连坐责任投影：主办→primary；主办/协办行 delegator_id 一级→secondary。

    同构 breach_decree_dossier 双处收集：协办本人零机械只作戏源，
    但其委派人仍次责（ADR 0053：大臣遣学生为协办办砸→全权者背锅）。
    先定档后去重：同一人 primary 胜 secondary；知情永不入。
    写路与 list_execution_liability_parties 共用本函数，禁止第二份 roster 遍历。
    """
    if not isinstance(roster, list):
        return []

    primary_ids: List[str] = []
    seen_primary: set[str] = set()
    for item in roster:
        if not isinstance(item, dict) or item.get("tier") != "主办":
            continue
        lead = str(item.get("character_id") or "").strip()
        if lead and lead not in seen_primary:
            seen_primary.add(lead)
            primary_ids.append(lead)

    secondary_ids: List[str] = []
    seen_secondary: set[str] = set()
    for item in roster:
        if not isinstance(item, dict) or item.get("tier") not in {"主办", "协办"}:
            continue
        delegator = str(item.get("delegator_id") or "").strip()
        if (
            delegator
            and delegator not in seen_primary
            and delegator not in seen_secondary
        ):
            seen_secondary.add(delegator)
            secondary_ids.append(delegator)

    parties: List[Dict[str, object]] = [
        {
            "character_id": lead,
            "responsibility": "primary",
            "tier": "主办",
        }
        for lead in primary_ids
    ]
    parties.extend(
        {
            "character_id": delegator,
            "responsibility": "secondary",
            "tier": "delegator",
        }
        for delegator in secondary_ids
    )
    return parties
