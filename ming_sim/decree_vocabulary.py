"""#471 皇帝动作在案卷层的 canonical 受控词表。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

DOSSIER_ACTION_TYPES = frozenset({
    "policy", "appointment", "acting_appointment",
    "assignment", "military_order",
    "grant_allocation", "authorization", "secret_authorization",
    "secret_investigation", "protection",
    "strategy_selection", "approve_reject",
    "secret_order", "special_decree",
    "revoke_decree", "punishment", "pacification", "referral",
    "revoke_authority", "dismiss_assignment",
    # #653 / ADR 0090：偿还序 override＋Due 折发系数旨——payload-owned，顺颁/强颁后
    # 自案卷载荷经 materialize_pay_order_decree 唯一入口物化 fiscal_config（ADR 0055
    # 判后物化轨）；打回零写。fiscal_config 键族是唯一持久真源，案卷只是颁布门与
    # provenance origin_ref（dossier:<id>），非第二旨意真源。
    "pay_order_override",
    # #651: a case-bound, payload-owned terminal order; never infer it from effects.
    "prohibit_covert_levy",
})

DIRECTIVE_ACTION_TYPES = DOSSIER_ACTION_TYPES - {"appointment", "secret_order"}

# #1778 决定 2（owner「1」）：批红可路由七类闭集整体取消——票拟/中旨 action_type
# 值域＝库级全集 DOSSIER_ACTION_TYPES（机器必须懂的形状检查仍在，ADR 0040）。
# 本集只钉「原七类 → 落库类型」的映射终点：罢免在 choice 上仍用 appointment +
# appoint_action=罢免，emitted 为 dismiss_assignment（#657 §C C.1）。
RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES = frozenset({
    "assignment", "military_order", "grant_allocation", "appointment",
    "dismiss_assignment",  # 罢免支
    "punishment", "authorization", "pacification",
})
assert RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES <= DOSSIER_ACTION_TYPES

# C.4 capability 派生闭集（全键 · 仅此表）。缺键按协议默认（""/0）参与派生。
_DRAFT_CAPABILITY_KEYS: tuple[tuple[str, Any], ...] = (
    ("action_type", ""),
    ("label", ""),
    ("hint", ""),
    ("assignee_name", ""),
    ("name", ""),
    ("target_kind", ""),
    ("target_id", ""),
    ("transaction_category", ""),
    ("locality_scope", ""),
    ("region_id", ""),
    ("title", ""),
    ("commitment_kind", ""),
    ("stop_condition", ""),
    ("end_turn", 0),
    ("deadline_months", 0),
    ("station", ""),
    ("due_turn", 0),
    ("office", ""),
    ("grant_action", ""),
    ("account", ""),
    ("purpose", ""),
    ("amount", 0),
    ("cadence", ""),
    ("execution_surface", ""),
    ("appoint_action", ""),
    ("appointment_tenure", ""),
    ("punish_action", ""),
    ("privilege", ""),
    ("summon_target", ""),
)

# #1778 决定 3：参与名单（ADR 0053 三档、主办可多人）是票拟的结构化载荷键——
# 由拟票大臣写进 option，随落桌呈皇帝，成案时钉进案卷。形状真源＝
# GameDB._normalize_participant_roster；此处只登记键名与 capability 派生方式。
PARTICIPANT_ROSTER_KEY = "participant_roster"

# C.4 capability 结构化键（非 str/int）：按 canonical JSON 参与派生，
# 换人/换档同样变键（与上表同一闭集，禁另开第二份 capability 真源）。
_DRAFT_CAPABILITY_JSON_KEYS: tuple[tuple[str, Any], ...] = (
    (PARTICIPANT_ROSTER_KEY, []),
)


def derive_draft_capability(fields: Mapping[str, Any] | None) -> str:
    """#657 C.4：闭集键 canonical JSON + sha256 截断。同字段⇒同键；任一有效差变键。"""
    src = fields or {}
    canonical: dict[str, Any] = {}
    for key, default in _DRAFT_CAPABILITY_JSON_KEYS:
        raw = src.get(key, default)
        canonical[key] = json.dumps(
            default if raw is None else raw,
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
        )
    for key, default in _DRAFT_CAPABILITY_KEYS:
        raw = src.get(key, default)
        if isinstance(default, int):
            if isinstance(raw, bool) or raw is None or raw == "":
                canonical[key] = 0
            else:
                try:
                    canonical[key] = int(raw)
                except (TypeError, ValueError):
                    canonical[key] = 0
        else:
            canonical[key] = "" if raw is None else str(raw)
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# Ming #654 / owner A：旨意 target_kind 唯一八值真源（含结构目标 dossier）。
# durable normalization / producer / locality oracle 共引；禁第二份枚举。
TARGET_KINDS = frozenset({
    "policy", "character", "office", "army", "region", "issue", "account",
    "dossier",
})

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
    # pay_order_override: payload-owned — #653 判后物化 fiscal_config（ADR 0055/0090）
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
    # #653：偿还序/折发旨顺颁即物化 config、效果已落地（无执行判定面）→ 终局。
    "pay_order_override",
    "prohibit_covert_levy",
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

# #622：奏报轨终值旁路——定性中文 band + 承办人假象，禁英文枚举/判官真值回填。
# 系统词（变形/打折走样/分界 等）不得出现在 progress_band / memorial。
# #629：测试本地禁词提升为生产单源（全族 P4 assert 哨兵共引）。
# 汉语普通词（变形/分界/打折走样/烂尾）只进 assert 哨兵响亮拦截，
# 不进运行时静默剥离——静默剜字会把 diegetic 朝语剜成病句。
DEFORMATION_BANNED_PLAYER_TOKENS = (
    "transformed", "degraded", "fulfilled", "failed", "executing",
    "progress_band", "is_terminal", "beyond_intent",
    "变形", "分界", "打折走样", "烂尾",
)
# 生产静默剥离子集：仅无歧义系统词（英文枚举/引擎键），零汉语普通词。
DEFORMATION_STRIP_PLAYER_TOKENS = tuple(
    token for token in DEFORMATION_BANNED_PLAYER_TOKENS
    if not any("\u4e00" <= ch <= "\u9fff" for ch in token)
)
assert DEFORMATION_STRIP_PLAYER_TOKENS
assert all(
    token in DEFORMATION_BANNED_PLAYER_TOKENS
    for token in DEFORMATION_STRIP_PLAYER_TOKENS
)
assert not any(
    any("\u4e00" <= ch <= "\u9fff" for ch in token)
    for token in DEFORMATION_STRIP_PLAYER_TOKENS
)

# #624/#629：真伪底/失真引擎词——urge_lever 与 due_review 共引叶模块，
# 禁双份漂移；亦消 urge_lever↔due_review 顶层环边。
URGE_TRUTH_BANNED_PLAYER_TOKENS = (
    "truth", "grace_fake", "pretextual", "genuine",
    "payload_json", "distortion_band", "urge_tightness",
    "distortion_tendency", "unreasonable", "supervision_history",
)
_TERMINAL_REPORT_FACADE_BAND = {
    "transformed": "已竣",
    "degraded": "将结",
}
_TERMINAL_REPORT_FACADE_MEMORIAL = {
    "transformed": "所委各节均已依限办结，并无违误。",
    "degraded": "所委已有成数，余事容再陈。",
}


def format_public_progress_disclosure(progress_rows: object) -> str:
    """公开披露面：progress_band + memorial_text 的 join 渲染（#622 AC6 面2 单源）。"""
    return "\n".join(
        f"【{item['progress_band']}】{item['memorial_text']}"
        for item in (progress_rows or [])
    )


def terminal_report_facade(
    outcome: object,
    *,
    prior_reports: object = None,
) -> tuple[str, str]:
    """终值奏报行的（progress_band, memorial_text）假象面。

    变形案必须载承办人假象（奏报说兑现），不得回填判官真值；
    progress_band 一律定性中文。
    """
    key = str(outcome or "").strip()
    band = _TERMINAL_REPORT_FACADE_BAND.get(key, "办结")
    memorial = _TERMINAL_REPORT_FACADE_MEMORIAL.get(
        key, "所委诸事已有回奏。",
    )
    # 变形：优先复用末次非终值月报陈词作假象载体（仍须成功口径）。
    if key == "transformed" and prior_reports:
        for item in reversed(list(prior_reports)):
            if not isinstance(item, dict):
                continue
            if item.get("is_terminal"):
                continue
            text = str(item.get("memorial_text") or "").strip()
            if text:
                memorial = text
                break
    return band, memorial

SIM_DOSSIER_COMMON_KEYS = frozenset({
    "id", "action_type", "status",
    "decision", "outcome", "note",
    "mode", "stigma", "participant_roster", "links", "execution_signal",
    "due_turn", "created_turn", "promulgated_turn",
    "target_kind", "target_id", "executor_kind", "executor_id",
    # #613 执行侧任别读端（与 #569 固定键投影同面）
    "appointment_tenure", "held_authorities", "authorization_ids",
    "command_power_rank", "distortion_weight",
    # #625 / ADR 0077 监督事实底只读注入（解 A）
    "supervision_history", "loophole_exposures",
    "transformation_tendency_facts",
    # #651 monthly pay truth rides the existing dossier judge surface.
    "army_pay_fact",
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
