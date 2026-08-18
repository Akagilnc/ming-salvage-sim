"""#471 皇帝动作在案卷层的 canonical 受控词表。"""

DOSSIER_ACTION_TYPES = frozenset({
    "policy", "appointment", "acting_appointment",
    "assignment", "military_order",
    "grant_allocation", "authorization", "secret_authorization",
    "secret_investigation", "protection",
    "strategy_selection", "approve_reject",
    "secret_order", "special_decree",
    "revoke_decree", "punishment", "pacification", "referral",
    "revoke_authority", "dismiss_assignment",
})

DIRECTIVE_ACTION_TYPES = DOSSIER_ACTION_TYPES - {"appointment", "secret_order"}

# ADR 0055 / #560: the single policy source for dossier admission and effect
# timing.  Consumers must not infer these properties from ad-hoc action sets.
# ``payload`` means a structured effect is materialized after promulgation;
# ``narrative`` means the simulator/extractor owns the effect; ``immediate``
# is an exempt palace/private action already materialized at admission.
_DOSSIER_NARRATIVE_ACTIONS = frozenset({
    "policy", "strategy_selection", "approve_reject", "special_decree",
    "secret_investigation", "protection",
    # pacification / punishment: payload-owned — 顺颁后自案卷物化（#522/#517 / ADR 0055）
    # revoke_authority / revoke_decree: payload-owned — #523 / ADR 0055 判后物化
    # referral: payload-owned — #524 下议 initiative 顺颁后落（ADR 0055）
})
_DOSSIER_EXTERNAL_REVIEW_EXEMPT = frozenset({
    "secret_order", "secret_authorization", "secret_investigation", "protection",
})
_DOSSIER_IMMEDIATE_ACTIONS = frozenset({"secret_order"})
_DOSSIER_TERMINAL_ACTIONS = frozenset({
    "authorization", "secret_authorization", "secret_order", "dismiss_assignment",
    # #522：招抚顺颁物化 #190 后即终局，复用通用 terminal 分支（禁止 db.py 动作特判）。
    "pacification",
    # #517：惩处/宥赦顺颁即终局（下狱/削籍/罚俸/叙事廷杖）。
    "punishment",
    # #523：收权/撤回成命顺颁即终局（authority_changes / breach）。
    "revoke_authority", "revoke_decree",
})

DOSSIER_ACTION_POLICY = {
    action: {
        "external_review": action not in _DOSSIER_EXTERNAL_REVIEW_EXEMPT,
        "effect_owner": (
            "immediate" if action in _DOSSIER_IMMEDIATE_ACTIONS
            else "narrative" if action in _DOSSIER_NARRATIVE_ACTIONS
            else "payload"
        ),
        "execution_surface": (
            "terminal" if action in _DOSSIER_TERMINAL_ACTIONS else "in_transit"
        ),
    }
    for action in DOSSIER_ACTION_TYPES
}
assert frozenset(DOSSIER_ACTION_POLICY) == DOSSIER_ACTION_TYPES


def dossier_action_policy(action_type: object, payload=None):
    """Return canonical policy, including the documented inner-treasury exemption."""
    action = str(action_type or "")
    policy = dict(DOSSIER_ACTION_POLICY[action])
    if action == "grant_allocation":
        payload = payload or {}
        grant_action = str(payload.get("grant_action") or "").strip()
        cadence = str(payload.get("cadence") or "").strip()
        if grant_action in {"加衔", "荫叙"}:
            policy["execution_surface"] = "terminal"
            return policy
        if str(payload.get("account") or "") == "内库":
            policy.update(external_review=False, effect_owner="immediate")
        if cadence == "每月":
            policy["execution_surface"] = "terminal"
            return policy
        surface = str(payload.get("execution_surface") or "in_transit")
        if surface not in {"immediate", "in_transit"}:
            raise ValueError("拨帑旨意 execution_surface 非法")
        policy["execution_surface"] = surface
    return policy


# ── #569 认账 brief / 推演投影词表（禁 session/web 双写）────────────────
# 认账 brief：status/颁布格/执行格/中旨标记一律定性中文（ADR 0052 P4 方向）。
# 推演投影：颁布格/执行格定性；status/mode/stigma 结构位仍按契约原样投出。

DOSSIER_STATUS_CN = {
    "proposed": "准旨",
    "promulgated": "已颁",
    "executing": "执行中",
    "closed": "结案",
}

DOSSIER_DECISION_CN = {
    "promulgated": "顺颁",
    "rejected": "打回",
    "force_promulgated": "强颁",
    "hold": "留中",
    "withdrawn": "收回",
}

DOSSIER_OUTCOME_CN = {
    "fulfilled": "兑现",
    "degraded": "打折走样",
    "failed": "烂尾",
    "transformed": "变形",
}

SIM_DOSSIER_COMMON_KEYS = frozenset({
    "id", "action_type", "status",
    "decision", "outcome", "note",
    "mode", "stigma", "participant_roster", "links",
    "due_turn", "created_turn", "promulgated_turn",
    "target_kind", "target_id", "executor_kind", "executor_id",
})
SIM_DOSSIER_NARRATIVE_KEYS = SIM_DOSSIER_COMMON_KEYS | {"decree_text"}
SIM_DOSSIER_EXECUTION_KEYS = SIM_DOSSIER_COMMON_KEYS | {"execution_summary"}


def qualitative_dossier_status(value: object) -> str:
    key = str(value or "").strip()
    return DOSSIER_STATUS_CN.get(key, "")


def qualitative_dossier_decision(value: object) -> str:
    key = str(value or "").strip()
    return DOSSIER_DECISION_CN.get(key, "")


def qualitative_dossier_outcome(value: object, *, status: object = "") -> str:
    key = str(value or "").strip()
    if key in DOSSIER_OUTCOME_CN:
        return DOSSIER_OUTCOME_CN[key]
    if str(status or "").strip() == "executing" and not key:
        return "执行中"
    return ""


def _promulgation_decision_raw(row: dict) -> str:
    """Resolve the current promulgation-slot raw enum for a dossier row."""
    verdict = str(row.get("settlement_verdict") or "").strip()
    if verdict in DOSSIER_DECISION_CN:
        return verdict
    decision = str(row.get("promulgation_decision") or "").strip()
    if decision in DOSSIER_DECISION_CN:
        return decision
    if bool(row.get("was_force_promulgated")):
        return "force_promulgated"
    stigma = row.get("stigma") or []
    if isinstance(stigma, list):
        for item in stigma:
            if not isinstance(item, dict) or item.get("kind") != "midzhi":
                continue
            source = str(item.get("source_action") or "").strip()
            if source == "force_promulgated":
                return "force_promulgated"
            if source == "promulgated":
                return "promulgated"
            if source == "rejected":
                return "rejected"
    return decision


def qualitative_promulgation_slot(row: dict) -> str:
    """颁布格定性。强颁组合态保留「打回」本值，另由 stigma/标记位表达强颁。"""
    raw = _promulgation_decision_raw(row)
    # 强颁：颁布格 outcome 仍是打回（0052），brief 侧并列「强颁」标记。
    if raw == "force_promulgated":
        base = str(row.get("promulgation_decision") or "").strip()
        if base == "rejected":
            return DOSSIER_DECISION_CN["rejected"]
        return DOSSIER_DECISION_CN["force_promulgated"]
    return qualitative_dossier_decision(raw)


def qualitative_midzhi_markers(row: dict) -> list[str]:
    markers: list[str] = []
    mode = str(row.get("mode") or "").strip()
    if mode == "midzhi":
        markers.append("中旨")
    stigma = row.get("stigma") or []
    if isinstance(stigma, list):
        for item in stigma:
            if not isinstance(item, dict) or item.get("kind") != "midzhi":
                continue
            source = str(item.get("source_action") or "").strip()
            if source == "force_promulgated":
                label = "批红强颁"
            elif source == "rejected":
                label = "中旨打回"
            else:
                label = "中旨"
            if label not in markers:
                markers.append(label)
    if bool(row.get("was_force_promulgated")) and "批红强颁" not in markers:
        markers.append("批红强颁")
    return markers


def render_referenceable_dossier_brief(candidates) -> str:
    """认账唯一 brief 渲染：status/颁布格/执行格/中旨标记一律定性中文。"""
    if not candidates:
        return ""
    lines = [
        "【可参考既有旨意（若有关联，请按标题或事项复述；勿向陛下念内部编号）】",
    ]
    for row in candidates:
        if not isinstance(row, dict):
            continue
        title = str(
            row.get("secret_title") or row.get("decree_text") or row.get("action_type") or ""
        ).strip()
        status_cn = qualitative_dossier_status(row.get("status"))
        decision_cn = qualitative_promulgation_slot(row)
        outcome_cn = qualitative_dossier_outcome(
            row.get("execution_outcome"), status=row.get("status"),
        )
        note = str(row.get("execution_note") or "").strip()
        markers = qualitative_midzhi_markers(row)
        facts = []
        if status_cn:
            facts.append(f"状态：{status_cn}")
        if decision_cn:
            facts.append(f"颁布：{decision_cn}")
        if outcome_cn:
            facts.append(f"执行：{outcome_cn}")
        if note:
            facts.append(f"说明：{note}")
        if markers:
            facts.append("标记：" + "、".join(markers))
        fact_text = "；".join(facts)
        suffix = f"（{fact_text}）" if fact_text else ""
        lines.append(f"- [内部键 {int(row['id'])}] {title}{suffix}")
    return "\n".join(lines)
