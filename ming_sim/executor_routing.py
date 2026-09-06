"""ADR 0117（#721）承办人主办档确定性路由。

承办人＝0053 案卷参与人「主办」档的确定性填充，两源有序：
①任免类执行主体＝被任命者本人（非吏部、非承办衙门）；
②点将优先——旨里点了谁（规范 assignee 或 roster 主办行 delegator_id 为空）即钉，
  多人＝多主办。

#1778 决定 3（owner 2026-09-06「推荐谁是 llm 的活。和代码无关！」）：没点将时
由拟票大臣把参与名单写进票拟，代码不再按事务类别→职司表配人、不再走缺位降档链。
职司表数据件（offices.json duty_routes）仍是 transaction_category 词表真源。

签名不接自由文本、无 LLM、判官零指认；同一旨意+同一名单 → 同一主办。
#1778 决定 4：全国政令不再拆省子行；region_id 只由 region 目标（单省）给出。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# ── 覆盖域判别（0116 三类 vs 立即 delta 排除；机读 action_type 闭集）────

_COVERAGE_APPOINTMENT = frozenset({"appointment", "acting_appointment"})
_COVERAGE_MULTI_MONTH = frozenset({"assignment", "military_order"})


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
        from ming_sim.action_clusters import cluster_by_kind

        punish_action = str((payload or {}).get("punish_action") or "").strip()
        cluster = cluster_by_kind("punishment")
        field = next((f for f in cluster.fields if f.name == "punish_action"), None) if cluster else None
        if field is not None and field.execution_coverage is not None:
            return field.execution_coverage.get(punish_action)
    return None


# ── 事务类别词表数据件读取（offices.json duty_routes，同族缓存范式）────────

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


def duty_route_categories() -> frozenset[str]:
    """职司路由事务类别闭集唯一派生（offices.json duty_routes；禁手抄第二份）。"""
    cats: set[str] = set()
    for entry in _duty_table().get("routes", []) or []:
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("category") or "").strip()
        if token:
            cats.add(token)
    return frozenset(cats)


def resolve_lead_executors(
    *,
    action_type: object = "",
    target_id: object = "",
    payload: Optional[Mapping[str, object]] = None,
    participant_roster: object = None,
) -> Dict[str, object]:
    """确定性点将路由（ADR 0117 净新契约 a）：返回结构化路由结果。

    leads 有序去重；signal.code='idle_start'＝怠办起步（任免无被任命者）。
    #1778 决定 3：没点将时代码不配人——名单由拟票大臣写在票拟里，
    空 leads 即空，不查职司表、不走降档链。
    """
    canonical_payload = payload or {}
    coverage = classify_execution_coverage(action_type, canonical_payload)
    if coverage is None:
        return {
            "coverage": None, "route": "excluded", "leads": [], "signal": None,
        }

    # ① 任免：执行主体＝被任命者本人
    if coverage == "appointment":
        who = str(target_id or "").strip()
        if who:
            return {
                "coverage": coverage,
                "route": "appointment_self",
                "leads": [who],
                "signal": None,
            }
        return {
            "coverage": coverage,
            "route": "appointment_self",
            "leads": [],
            "signal": {"code": "idle_start", "reason": "appointment_without_target"},
        }

    # ② 点将优先：规范化 assignee 是生产点将；0053 roster 是同义结构入口。
    assignee = str(canonical_payload.get("assignee_id") or "").strip()
    if assignee:
        return {
            "coverage": coverage, "route": "named",
            "leads": [assignee], "signal": None,
        }
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
    return {
        "coverage": coverage,
        "route": "named" if named else "unassigned",
        "leads": named,
        "signal": None,
    }
