"""ADR 0117（#721）承办人主办档确定性路由。

承办人＝0053 案卷参与人「主办」档的确定性填充，三源有序：
①任免类执行主体＝被任命者本人（非吏部、非承办衙门）；
②点将优先——皇帝直点（roster 主办行 delegator_id 为空）即钉，多人＝多主办；
③职司表兜底——事务类别（机读闭集 token）→ offices.json duty_routes 同族
  显式扩展数据件 → 对口衙门在任主官；缺位降档链 主官→署理→无人＝怠办起步。
未命中映射 ≠ 无人可承：fail-loud 产结构化 rejection 供观测补条目，不落怠办。

签名不接自由文本、无 LLM、判官零指认；同一旨意+同一官职档案 → 同一主办。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Mapping, Optional

# ── 覆盖域判别（0116 三类 vs 立即 delta 排除；机读 action_type 闭集）────

_COVERAGE_APPOINTMENT = frozenset({"appointment", "acting_appointment"})
_COVERAGE_MULTI_MONTH = frozenset({"assignment", "military_order"})
# 当前 canonical punishment schema 尚无 execution-class 元数据。依 0116/0117
# 收窄到明确含「拿问」这一结构化差务的既有枚举；不得由 punishment 顶层或旨文扩张。
_STRIKE_PUNISH_ACTIONS = frozenset({"拿问下狱", "拿问去职"})


def classify_execution_coverage(
    action_type: object, payload: Optional[Mapping[str, object]] = None,
) -> Optional[str]:
    """只读 canonical 动作及结构化细类判别执行覆盖域，不解析旨文。"""
    action = str(action_type or "").strip()
    if action in _COVERAGE_APPOINTMENT:
        return "appointment"
    if action in _COVERAGE_MULTI_MONTH:
        return "multi_month"
    if action == "punishment":
        punish_action = str((payload or {}).get("punish_action") or "").strip()
        if punish_action in _STRIKE_PUNISH_ACTIONS:
            return "strike"
    return None


# ── 事务类别→职司映射数据件读取（offices.json duty_routes，同族缓存范式）──

_DUTY_TABLE: Optional[Mapping[str, Any]] = None


def _duty_table() -> Mapping[str, Any]:
    global _DUTY_TABLE
    if _DUTY_TABLE is None:
        from ming_sim.assets import load_json_asset

        data = load_json_asset("offices.json")
        routes = data.get("duty_routes") if isinstance(data, dict) else None
        if not isinstance(routes, dict):
            raise ValueError("offices.json 缺 duty_routes 数据件（ADR 0117 扩条清单）")
        _DUTY_TABLE = routes
    return _DUTY_TABLE


def duty_route_office_type(category: object) -> Optional[str]:
    """机读事务类别 token → office_type。priority 首中即胜、无 LLM。
    未命中返回 None（fail-loud 哨兵，与空串区分）。"""
    token = str(category or "").strip()
    if not token:
        return None
    for entry in _duty_table().get("routes", []) or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("category") or "").strip() == token:
            return str(entry.get("office_type") or "")
    return None


# ── 在任者查表＋缺位降档链 ───────────────────────────────────────────


def _holders_in_office(conn: sqlite3.Connection, office_type: str) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT c.name AS name, c.office AS office,"
            " COALESCE(co.appointment_tenure, '真除') AS tenure"
            " FROM characters c LEFT JOIN character_offices co"
            " ON co.character_name = c.name"
            " WHERE c.office_type=? AND c.status='active' AND c.power_id='ming'"
            " ORDER BY c.name",
            (office_type,),
        )
    )


def _downgrade_chain(conn: sqlite3.Connection, office_type: str) -> tuple:
    """主官→署理降档，确定性（同名序 tie-break）。命中返回 (name, step)。"""
    rows = _holders_in_office(conn, office_type)
    chiefs = [
        r["name"]
        for r in rows
        if any(s in (r["office"] or "") for s in _duty_table().get("chief_stems", []))
        and "署理" not in (r["office"] or "")
    ]
    if chiefs:
        return chiefs[0], "主官"
    deputies = [
        r["name"]
        for r in rows
        if "署理" in (r["office"] or "")
        or r["tenure"] == "署理"
        or any(s in (r["office"] or "") for s in _duty_table().get("deputy_stems", []))
    ]
    if deputies:
        return deputies[0], "署理降档"
    return "", ""


def resolve_lead_executors(
    conn: sqlite3.Connection,
    *,
    action_type: object = "",
    target_id: object = "",
    payload: Optional[Mapping[str, object]] = None,
    participant_roster: object = None,
) -> Dict[str, object]:
    """确定性双源路由（ADR 0117 净新契约 a）：返回结构化路由结果。

    leads 有序去重；signal.code='idle_start'＝怠办起步（缺位链穷尽或任免无
    被任命者），rejection 非 None＝映射未命中 fail-loud（两者互斥、不同时落）。
    """
    canonical_payload = payload or {}
    coverage = classify_execution_coverage(action_type, canonical_payload)
    if coverage is None:
        return {
            "coverage": None, "route": "excluded", "office_type": "", "leads": [],
            "downgrade_step": "", "signal": None, "rejection": None,
        }

    # ① 任免：执行主体＝被任命者本人
    if coverage == "appointment":
        who = str(target_id or "").strip()
        if who:
            return {
                "coverage": coverage,
                "route": "appointment_self",
                "office_type": "",
                "leads": [who],
                "downgrade_step": "",
                "signal": None,
                "rejection": None,
            }
        return {
            "coverage": coverage,
            "route": "appointment_self",
            "office_type": "",
            "leads": [],
            "downgrade_step": "",
            "signal": {"code": "idle_start", "reason": "appointment_without_target"},
            "rejection": None,
        }

    # ② 点将优先：主办行且 delegator_id 为空＝皇帝直点；多人＝多主办
    roster = participant_roster if isinstance(participant_roster, list) else []
    named: List[str] = []
    seen: set = set()
    for entry in roster:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("tier") or "").strip() != "主办":
            continue
        name = str(entry.get("character_id") or "").strip()
        if name and not str(entry.get("delegator_id") or "").strip() and name not in seen:
            seen.add(name)
            named.append(name)
    if named:
        return {
            "coverage": coverage,
            "route": "named",
            "office_type": "",
            "leads": named,
            "downgrade_step": "",
            "signal": None,
            "rejection": None,
        }

    # ③ 职司表兜底：事务类别（结构化闭集 token）→ 职司 → 在任主官
    category = str(canonical_payload.get("transaction_category") or "").strip()
    office_type = duty_route_office_type(category)
    if office_type is None:
        # 未命中映射 ＝ 归口缺口，fail-loud 进 rejections；不是怠办起步。
        return {
            "coverage": coverage,
            "route": "duty_table",
            "office_type": "",
            "leads": [],
            "downgrade_step": "",
            "signal": None,
            "rejection": {
                "section": "executor_routing",
                "reason_code": "duty_route_unmapped",
                "category": category,
            },
        }
    holder, step = _downgrade_chain(conn, office_type)
    if holder:
        return {
            "coverage": coverage,
            "route": "duty_table",
            "office_type": office_type,
            "leads": [holder],
            "downgrade_step": step,
            "signal": None,
            "rejection": None,
        }
    # 映射命中但在任者出缺：降档链穷尽 → 怠办起步（消极端意愿轴底档）。
    return {
        "coverage": coverage,
        "route": "duty_table",
        "office_type": office_type,
        "leads": [],
        "downgrade_step": "",
        "signal": {
            "code": "idle_start",
            "reason": "vacancy_chain_exhausted",
            "chain": office_type,
        },
        "rejection": None,
    }
