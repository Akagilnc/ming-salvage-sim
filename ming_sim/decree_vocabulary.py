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
