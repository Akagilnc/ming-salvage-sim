"""Machine-readable ADR 0009 person archive contract index.

This module keeps the contract as data plus pure lookup helpers. The person
applier consumes it in later slices; keeping the contract index separate lets
tests name ADR scenarios before the state mutation code exists.
"""

from __future__ import annotations


PERSON_TRANSITION_ACTIONS = ("任命", "罢黜", "调任", "处置", "易主", "册封", "行止")

PERSON_NON_TRANSITION_ACTIONS = ("评定", "性情")

PERSON_ACTIONS = PERSON_TRANSITION_ACTIONS + PERSON_NON_TRANSITION_ACTIONS


def format_person_actions() -> str:
    """Project currently writable actions; legacy 评定 remains parseable only for rejection/migration."""
    return " / ".join(f"`{action}`" for action in PERSON_ACTIONS if action != "评定")


PERSON_STATUSES = (
    "active",
    "candidate",
    "offstage",
    "dismissed",
    "imprisoned",
    "exiled",
    "retired",
    "dead",
)

PERSON_REASON_CODES = (
    "被顶替",
    "获罪削籍",
    "致仕",
    "丁忧",
    "自请",
    "出宫",
    "陷虏",
    "落选",
    "历史卒",
    "登场",
    # #690 / ADR 0011-2 D2-5：依律集扩 0009（走程序坐实 flag；与 cw 高低正交）
    "依律",
    "谋逆坐实",
    "贪墨坐实",
    "未识别",
)

# ADR 0011-2 D2-5 named subset of PERSON_REASON_CODES; not a parallel enum.
PERSON_LEGAL_REASON_CODES = ("依律", "谋逆坐实", "贪墨坐实")

PERSON_TITLE_KINDS = ("职名分", "身名分", "无名分")

PERSON_IDENTITY_TITLES = ("听用候铨", "降臣", "归附", "待选", "诸生")

PERSON_ALLEGIANCE_CHANGE_WAYS = ("主动投敌", "被俘而降", "主动归附")

PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS = ("不明",)

PERSON_REASON_CODE_ALIASES = {
    "守制": "丁忧",
    "丁艰": "丁忧",
    "被俘": "陷虏",
    "陷敌": "陷虏",
}

PERSON_REASON_TRANSITION_OVERRIDES = {
    ("offstage", "任命", "丁忧"): "derive:夺情",
    ("imprisoned", "任命", "陷虏"): "reject:invalid_transition",
    ("imprisoned", "调任", "陷虏"): "reject:invalid_transition",
    ("imprisoned", "易主", "陷虏"): "apply",
}

PERSON_TITLE_KIND_TRANSITION_OVERRIDES = {
    ("active", "任命", "职名分"): "normalize:调任",
    ("active", "任命", "身名分"): "apply",
    ("active", "任命", "无名分"): "apply",
    ("active", "调任", "职名分"): "apply",
    ("active", "调任", "身名分"): "normalize:任命",
    ("active", "调任", "无名分"): "normalize:任命",
}


def normalize_reason_code(value: object) -> str:
    """Normalize ADR 0009 reason_code values.

    Empty means the model did not provide a code. A non-empty unrecognized code
    is machine-distinct and maps to the sentinel, preserving status_reason for
    later human repair.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = PERSON_REASON_CODE_ALIASES.get(raw, raw)
    if normalized in PERSON_REASON_CODES:
        return normalized
    return "未识别"


def normalize_title_kind(value: object) -> str:
    """Normalize ADR 0009 title-kind values used for active normalization."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in PERSON_TITLE_KINDS:
        return raw
    if raw in PERSON_IDENTITY_TITLES:
        return "身名分"
    return ""


def resolve_person_transition(
    status: str,
    action: str,
    *,
    reason_code: object = "",
    current_title_kind: object = "",
) -> str:
    """Resolve an ADR 0009 transition outcome.

    reason_code-specific rules are checked before the status/action default
    matrix, because ADR 0009 makes specialized reasons outrank status rules.
    """
    status_key = str(status or "").strip()
    action_key = str(action or "").strip()
    normalized_reason = normalize_reason_code(reason_code)
    normalized_title_kind = normalize_title_kind(current_title_kind)
    override = PERSON_REASON_TRANSITION_OVERRIDES.get(
        (status_key, action_key, normalized_reason)
    )
    if override is not None:
        return override
    title_kind_override = PERSON_TITLE_KIND_TRANSITION_OVERRIDES.get(
        (status_key, action_key, normalized_title_kind)
    )
    if title_kind_override is not None:
        return title_kind_override
    # 防御（5b r1 PR #106 gemini）：status/action 非矩阵已知 key（历史脏数据/未预期输入）时
    # 用 .get() 回落 reject 而非 KeyError 崩结算——状态白名单在 applier 先校验，此为深防。
    return PERSON_TRANSITION_MATRIX.get(status_key, {}).get(action_key, "reject:invalid_transition")


PERSON_TRANSITION_MATRIX = {
    "active": {
        "任命": "normalize:调任",
        "罢黜": "apply",
        "调任": "apply",
        "处置": "apply",
        "易主": "apply",
        "册封": "reject:invalid_transition",
        "行止": "apply",
    },
    "candidate": {
        "任命": "reject:invalid_transition",
        "罢黜": "reject:invalid_transition",
        "调任": "reject:invalid_transition",
        "处置": "apply",
        "易主": "reject:invalid_transition",
        "册封": "apply",
        "行止": "reject:invalid_transition",
    },
    "offstage": {
        "任命": "derive:起复",
        "罢黜": "apply",
        "调任": "normalize:任命",
        "处置": "apply",
        "易主": "reject:invalid_transition",
        "册封": "reject:invalid_transition",
        "行止": "reject:invalid_transition",
    },
    "dismissed": {
        "任命": "derive:昭雪",
        "罢黜": "apply",
        "调任": "normalize:任命",
        "处置": "apply",
        "易主": "reject:invalid_transition",
        "册封": "reject:invalid_transition",
        "行止": "reject:invalid_transition",
    },
    "imprisoned": {
        "任命": "derive:放归",
        "罢黜": "reject:invalid_transition",
        "调任": "derive:放归",
        "处置": "apply",
        "易主": "reject:invalid_transition",
        "册封": "reject:invalid_transition",
        "行止": "reject:invalid_transition",
    },
    "exiled": {
        "任命": "derive:赦还",
        "罢黜": "reject:invalid_transition",
        "调任": "derive:赦还",
        "处置": "apply",
        "易主": "reject:invalid_transition",
        "册封": "reject:invalid_transition",
        "行止": "reject:invalid_transition",
    },
    "retired": {
        "任命": "derive:起复",
        "罢黜": "apply",
        "调任": "normalize:任命",
        "处置": "apply",
        "易主": "reject:invalid_transition",
        "册封": "reject:invalid_transition",
        "行止": "reject:invalid_transition",
    },
    "dead": {
        "任命": "reject:invalid_transition",
        "罢黜": "reject:invalid_transition",
        "调任": "reject:invalid_transition",
        "处置": "reject:invalid_transition",
        "易主": "reject:invalid_transition",
        "册封": "reject:invalid_transition",
        "行止": "reject:invalid_transition",
    },
}

ACCEPTANCE_SCENARIOS = (
    {
        "id": "S1",
        "title": "狱中拜将",
        "input": "任命孙传庭为陕西总督",
        "actions": ("处置", "任命"),
        "requires": ("derived_from", "invariant:office_implies_active"),
    },
    {
        "id": "S2",
        "title": "起复",
        "input": "起复孙承宗督师蓟辽",
        "actions": ("处置", "任命"),
        "requires": ("reason_code:致仕", "derive:起复"),
    },
    {
        "id": "S3",
        "title": "翻案起用",
        "input": "任命韩爌入阁",
        "actions": ("处置", "任命"),
        "requires": ("reason_code:获罪削籍", "derive:昭雪"),
    },
    {
        "id": "S4",
        "title": "夺情",
        "input": "夺情起复杨嗣昌",
        "actions": ("处置", "任命"),
        "requires": ("reason_code:丁忧", "derive:夺情"),
    },
    {
        "id": "S5",
        "title": "被顶替",
        "input": "任命毕自严为户部尚书",
        "actions": ("任命", "处置"),
        "requires": ("derive:顶替离任", "talent_pool:听用候铨"),
    },
    {
        "id": "S6",
        "title": "主动投敌",
        "input": "孔有德举军降虏",
        "actions": ("易主",),
        "requires": ("方式:主动投敌", "backlash_required"),
    },
    {
        "id": "S7",
        "title": "被俘未降",
        "input": "洪承畴兵败被执",
        "actions": ("处置",),
        "requires": (
            "reason_code:陷虏",
            "apply",
            "blocks:任命",
            "reject:invalid_transition",
        ),
        "transition_checks": (
            ("active", "处置", "陷虏", "apply"),
            ("imprisoned", "任命", "陷虏", "reject:invalid_transition"),
        ),
    },
    {
        "id": "S8",
        "title": "官降三级",
        "input": "放出某官贬三级任用",
        "actions": ("处置", "处置", "任命"),
        "requires": ("sequence", "derive:起复"),
    },
    {
        "id": "S9",
        "title": "出宫",
        "input": "客氏出宫居家",
        "actions": ("处置",),
        "requires": ("reason_code:出宫", "invariant:offstage_clears_office"),
    },
    {
        "id": "S10",
        "title": "追谥",
        "input": "追谥毛文龙",
        "actions": (),
        "requires": ("out_of_pipe", "dead_no_outgoing_status"),
    },
    {
        "id": "S11",
        "title": "赴任在途",
        "input": "袁崇焕今日启程赴辽",
        "actions": ("行止",),
        "requires": ("transit_to", "invariant:transit_implies_active"),
    },
    {
        "id": "S12",
        "title": "幻觉人事",
        "input": "任命不存在者为兵部尚书",
        "actions": ("任命",),
        "requires": ("reject:hallucinated_id",),
    },
    {
        "id": "S13",
        "title": "任命死人",
        "input": "任命毛文龙镇东江",
        "actions": ("任命",),
        "requires": ("reject:invalid_transition", "dead_no_outgoing_status"),
    },
    {
        "id": "S14",
        "title": "选妃册封",
        "input": "册封某氏为妃",
        "actions": ("册封",),
        "requires": ("status:candidate", "candidate_exit"),
    },
    {
        "id": "S15",
        "title": "招抚归明",
        "input": "招安郑芝龙，授游击",
        "actions": ("易主", "任命"),
        "requires": ("方式:主动归附", "enemy_to_ming"),
    },
)
