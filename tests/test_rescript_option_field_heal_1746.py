"""#1746：缺字段同一会话补交 ≤3 → 耗尽单 option 剔除。

真实入口：generate_rescript_draft。
decision keys：missing-field-heal-by-resume-not-drop / per-option-drop-after-heal-exhausted。
"""
from __future__ import annotations

import json
from copy import deepcopy


def _ctx() -> dict:
    return {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [
            {"id": "guanning", "name": "关宁军", "station": "宁远"},
            {"id": "xuanfu", "name": "宣府", "station": "宣府"},
        ],
        "gazette": "邸报",
        "triage_actor": {},
        "turn": {},
    }


# #1778 决定 3：生成批次的票拟必带参与名单（ADR 0053 三档，至少一名主办）。
_ROSTER = [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}]


def _hold(**kw) -> dict:
    base = {
        "label": "缓议候报",
        "hint": "所安者边计",
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "assignee_name": "",
        "transaction_category": "督赈",
        "participant_roster": [dict(i) for i in _ROSTER],
    }
    base.update(kw)
    return base


def _army_pay(**kw) -> dict:
    base = {
        "label": "补发关宁军饷",
        "hint": "边饷急",
        "action_type": "grant_allocation",
        "assignee_name": "",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "grant_kind": "army_pay",
        "amount": 300,
        "account": "国库",
        "purpose": "补饷",
        "participant_roster": [dict(i) for i in _ROSTER],
    }
    base.update(kw)
    return base


def _items_json(items: list) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


# JSON 数字 1e309/-1e309 经 loads 成 ±inf；不能经 Python float 再 dumps（非 JSON 合规）。
_OVERFLOW_SENTINEL = "__overflow_num__"


def _items_json_num(items: list, number_literal: str) -> str:
    """Serialize items；把哨兵字符串替换为裸 JSON 数字字面量。"""
    return _items_json(items).replace(
        json.dumps(_OVERFLOW_SENTINEL), number_literal,
    )


def _punish(**kw) -> dict:
    base = {
        "label": "惩戒拟",
        "hint": "示惩",
        "action_type": "punishment",
        "target_kind": "character",
        "target_id": "x",
        "locality_scope": "none",
        "region_id": "",
        "assignee_name": "",
        "transaction_category": "",
        "punish_action": "罚俸",
        "amount": 1,
        "participant_roster": [dict(i) for i in _ROSTER],
    }
    base.update(kw)
    return base


def _stamp_heal_ids(items: list) -> list:
    out = deepcopy(items)
    for ii, it in enumerate(out):
        for oi, opt in enumerate(it.get("options") or []):
            if isinstance(opt, dict):
                opt["heal_id"] = f"{ii}:{oi}"
    return out


def _heals_json(pairs: list[tuple[str, dict]]) -> str:
    return json.dumps(
        {"heals": [{"heal_id": hid, **fields} for hid, fields in pairs]},
        ensure_ascii=False,
    )


def _prior_roles(prior_messages) -> list:
    return [
        m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        for m in (prior_messages or [])
    ]


def _prior_contents(prior_messages) -> list:
    return [
        m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        for m in (prior_messages or [])
    ]


def _assert_call_history(calls: list[dict]) -> None:
    """每轮 prior = 此前全部 user/assistant 完整顺序（含原始 user 与各轮响应）。"""
    hist_roles: list[str] = []
    hist_contents: list[object] = []
    for call in calls:
        assert call["roles"] == hist_roles
        assert call["contents"] == hist_contents
        assert isinstance(call.get("prompt"), str) and call["prompt"]
        assert isinstance(call.get("response"), str) and call["response"]
        hist_roles = hist_roles + ["user", "assistant"]
        hist_contents = hist_contents + [call["prompt"], call["response"]]


def _parse_heal_request(prompt: object) -> dict:
    """LLM 实际收到的补交 user 内容：结构化 JSON（非 formatter 旁路）。"""
    assert isinstance(prompt, str) and prompt.strip()
    body = json.loads(prompt)
    assert isinstance(body, dict)
    assert body.get("kind") == "rescript_option_field_heal"
    assert isinstance(body.get("failures"), list)
    return body


def _field_failure_map(failure_entry: dict) -> dict:
    out = {}
    for fact in failure_entry.get("field_failures") or []:
        assert isinstance(fact, dict)
        field = fact.get("field")
        assert isinstance(field, str) and field
        assert "current" in fact and "expected" in fact
        out[field] = fact
    return out


# ---------------------------------------------------------------------------
# agents.run_agent_text 适配器（无真实 LLM）
# ---------------------------------------------------------------------------

def test_run_agent_text_prior_messages_sent_as_message_list():
    from agno.models.message import Message
    from ming_sim.agents import run_agent_text

    captured: list[object] = []

    class _Agent:
        def run(self, input):
            captured.append(input)

            class _Out:
                content = '{"ok":true}'
                messages = None

            return _Out()

    prior = [
        {"role": "user", "content": "first-user"},
        {"role": "assistant", "content": "first-assistant"},
    ]
    text = run_agent_text(
        _Agent(), "heal-user", tag="rescript-draft-heal", prior_messages=prior,
    )
    assert text == '{"ok":true}'
    payload = captured[0]
    assert isinstance(payload, list) and len(payload) == 3
    assert all(isinstance(m, Message) for m in payload)
    assert [m.role for m in payload] == ["user", "assistant", "user"]
    assert [m.content for m in payload] == [
        "first-user", "first-assistant", "heal-user",
    ]


def test_run_agent_text_without_prior_passes_plain_prompt():
    from ming_sim.agents import run_agent_text

    captured: list[object] = []

    class _Agent:
        def run(self, input):
            captured.append(input)

            class _Out:
                content = "x"
                messages = None

            return _Out()

    assert run_agent_text(_Agent(), "solo", tag="t") == "x"
    assert captured == ["solo"]


# ---------------------------------------------------------------------------
# 契约失败 → 同一 heal 回路（heal-covers-illegal-values-too；缺或错不分类）
# ---------------------------------------------------------------------------


def _overflow_case_matrix():
    """四整数键 ±超范围 + punishment 罚俸/非罚俸两条件转换。"""
    cases = []
    for key in ("end_turn", "deadline_months", "due_turn", "amount"):
        for lit, sign in (("1e309", "pos"), ("-1e309", "neg")):
            cases.append((
                f"{key}_{sign}",
                lambda k=key: _hold(**{k: _OVERFLOW_SENTINEL, "label": "坏项"}),
                lit,
                {key: 3},
                (key,),
                {"type": "int"},
            ))
    # 罚俸：positive_amount_when 原转换点；非罚俸（削籍）：forbid 吞溢出后 int_keys 收
    cases.append((
        "punish_fine_pos",
        lambda: _punish(
            punish_action="罚俸", amount=_OVERFLOW_SENTINEL, label="坏项",
        ),
        "1e309",
        {"amount": 3},
        ("amount",),
        {"type": "positive_int"},
    ))
    cases.append((
        "punish_strip_pos",
        lambda: _punish(
            punish_action="削籍", amount=_OVERFLOW_SENTINEL, label="坏项",
        ),
        "1e309",
        {"amount": 0},
        ("amount",),
        {"type": "int"},
    ))
    return cases


# ---------------------------------------------------------------------------
# 补交响应解析/运输契约失败：消耗本次补交，不整批无头版
# ---------------------------------------------------------------------------

_BAD_HEAL_RESPONSES = {
    "malformed_json": "already filled purpose. {not-json",
    "fence_prose": (
        "already filled purpose.\n"
        "```json\n{\"heals\":[]}\n```\n"
        "done."
    ),
    "top_array": "[{\"purpose\":\"补饷\"}]",
}


# ---------------------------------------------------------------------------
# heal_id 负向（typed 身份契约；不进 phase2 重复 k 链）
# ---------------------------------------------------------------------------
