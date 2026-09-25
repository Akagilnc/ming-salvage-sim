"""#1746：缺字段同一会话补交 ≤3 → 耗尽单 option 剔除。

真实入口：generate_rescript_draft。
decision keys：missing-field-heal-by-resume-not-drop / per-option-drop-after-heal-exhausted。
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

import ming_sim.rescript_draft as rescript_mod
from ming_sim.rescript_draft import (
    RESCRIPT_OPTION_FIELD_HEAL_RETRIES,
    generate_rescript_draft,
)


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

@pytest.mark.parametrize(
    "mutate, heal_steps, must_fields",
    [
        (lambda o: o.update({"amount": -5}), [{"amount": 300}], ("amount",)),
        (lambda o: o.update({"purpose": "赈灾"}), [{"purpose": "补饷"}], ("purpose",)),
        (
            lambda o: o.update({"label": "", "amount": -5}),
            [{"label": "边饷拟", "amount": 300}],
            ("label", "amount"),
        ),
        (
            lambda o: o.update({"label": "", "amount": 3.5}),
            [{"label": "边饷拟", "amount": 300}],
            ("label", "amount"),
        ),
        (
            lambda o: o.update({"label": "", "grant_kind": "bogus"}),
            [{"label": "边饷拟", "grant_kind": "army_pay"}],
            ("label", "grant_kind"),
        ),
        (
            lambda o: o.update({"label": "", "cadence": "weekly"}),
            [{"label": "边饷拟", "cadence": "一次性"}],
            ("label", "cadence"),
        ),
        (
            lambda o: o.update({"label": "", "account": "坏账"}),
            [{"label": "边饷拟", "account": "国库"}],
            ("label", "account"),
        ),
        # 先补辨别，再补金额（权威 shape 在辨别齐后才验 amount）
        (
            lambda o: (o.update({"amount": -5}), o.pop("grant_kind", None)),
            [{"grant_kind": "army_pay"}, {"amount": 300}],
            ("grant_kind",),
        ),
        (
            lambda o: (
                o.update({"label": "", "amount": -5}),
                o.pop("assignee_name", None),
            ),
            [{"label": "边饷拟", "amount": 300, "assignee_name": ""}],
            ("label", "amount", "assignee_name"),
        ),
        # amount 缺时 grant shape 先报 amount；cadence 非法在金额齐后由协饷权威再报
        (
            lambda o: (o.pop("amount", None), o.update({"cadence": "weekly"})),
            [{"amount": 300}, {"cadence": "一次性"}],
            ("amount",),
        ),
    ],
    ids=[
        "neg_amount", "bad_purpose",
        "miss_label_neg_amt", "miss_label_float", "miss_label_bogus_kind",
        "miss_label_cadence", "miss_label_account",
        "miss_kind_neg_amt", "miss_label_assignee_neg_amt", "miss_amt_bad_cadence",
    ],
)
def test_contract_failure_heals_not_batch_reject(
    mutate, heal_steps, must_fields, monkeypatch, tmp_path,
):
    """r3 八反例：不合契约（缺或错）→ 补交，不整批拒；兄弟项保留。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="边饷拟")
    mutate(bad)
    sibling = _hold(label="缓议")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    steps = [_heals_json([("0:0", dict(s))]) for s in heal_steps]
    tags: list[str] = []
    prompts: list[str] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        prompts.append(prompt)
        n["i"] += 1
        if n["i"] == 1:
            return first
        idx = n["i"] - 2
        return steps[idx] if idx < len(steps) else steps[-1]

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=40)
    assert drafts is not None
    assert "rescript-draft-heal" in tags
    heal_prompt = next(p for t, p in zip(tags, prompts) if t == "rescript-draft-heal")
    req = _parse_heal_request(heal_prompt)
    ff = _field_failure_map(req["failures"][0])
    for name in must_fields:
        assert name in ff
    opts = drafts[0]["options"]
    assert any(o.get("label") == sibling["label"] for o in opts)
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    assert grant["amount"] == 300
    assert grant.get("purpose") == "补饷"


def test_amount_numeric_string_accepted_via_grant_shape(monkeypatch, tmp_path):
    """既有 grant 归一：amount='300' 经 require_grant_allocation_shape 接受为 300。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    opt = _army_pay(amount="300")
    raw = _items_json([{"title": "u", "context": "c", "options": [opt, _hold()]}])
    tags: list[str] = []
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda _a, _p, tag="", prior_messages=None: (tags.append(tag) or raw),
    )
    drafts = generate_rescript_draft(object(), _ctx(), turn=46)
    assert drafts is not None and tags == ["rescript-draft"]
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["amount"] == 300


def test_missing_target_kind_only_heals_not_combo_batch(monkeypatch, tmp_path):
    """仅缺 target_kind → heal；不得虚填 region 变组合整批 None。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay()
    bad.pop("target_kind")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    healed = _heals_json([("0:0", {"target_kind": "army"})])
    tags: list[str] = []
    n = {"i": 0}

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=41)
    assert drafts is not None
    assert "rescript-draft-heal" in tags
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["target_kind"] == "army" and grant["amount"] == 300


def test_army_single_combo_heals_not_batch_redraw(monkeypatch, tmp_path):
    """army+single 组合矛盾 → 同一 option heal；不整批组合重抽。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(locality_scope="single", target_id="")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    healed = _heals_json([("0:0", {"locality_scope": "none", "target_id": "guanning"})])
    tags: list[str] = []
    prompts: list[str] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        prompts.append(prompt)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=47)
    assert drafts is not None
    assert tags == ["rescript-draft", "rescript-draft-heal"]
    req = _parse_heal_request(prompts[1])
    ff = _field_failure_map(req["failures"][0])
    assert "locality_scope" in ff
    assert ff["locality_scope"]["current"] == "single"
    assert "none" in (ff["locality_scope"]["expected"] or [])
    # 缺 target_id 同时 army+single：权威一次给出完整事实
    assert "target_id" in ff
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["locality_scope"] == "none"
    assert any(o.get("label") == "缓议候报" for o in drafts[0]["options"])


def test_dual_missing_discriminator_heals_grant_action(monkeypatch, tmp_path):
    """双缺辨别 → 可补合法 grant_action（不预断 army_pay；无平行金额预检）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _hold(action_type="grant_allocation", amount=50, account="国库")
    sibling = _hold(label="hold2")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    healed = _heals_json([("0:0", {"grant_action": "赈灾"})])
    tags: list[str] = []
    n = {"i": 0}

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=44)
    assert drafts is not None and "rescript-draft-heal" in tags
    grant = next(
        o for o in drafts[0]["options"] if o.get("action_type") == "grant_allocation"
    )
    assert grant["grant_action"] == "赈灾" and grant["amount"] == 50


@pytest.mark.parametrize(
    "bad_factory, heal_fix, must_fields",
    [
        (
            lambda: {
                "label": "调关宁", "hint": "边情", "action_type": "military_order",
                "target_kind": "army", "target_id": "guanning", "locality_scope": "none",
                "region_id": "", "assignee_name": "袁崇焕", "transaction_category": "",
                "station": "宁远", "deadline_months": "abc",
            },
            {"deadline_months": 2},
            ("deadline_months",),
        ),
        (
            lambda: _hold(label=123),  # type: ignore[arg-type]
            {"label": "缓议候报"},
            ("label",),
        ),
    ],
    ids=["deadline_non_int", "required_wrong_type"],
)
def test_typed_illegal_also_heals(bad_factory, heal_fix, must_fields, monkeypatch, tmp_path):
    """错类型/不可解析值同样走补交，不整批拒。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = bad_factory()
    sibling = _hold(label="兄弟")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    healed = _heals_json([("0:0", dict(heal_fix))])
    tags: list[str] = []
    prompts: list[str] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        prompts.append(prompt)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=45)
    assert drafts is not None and "rescript-draft-heal" in tags
    heal_prompt = next(p for t, p in zip(tags, prompts) if t == "rescript-draft-heal")
    ff = _field_failure_map(_parse_heal_request(heal_prompt)["failures"][0])
    for name in must_fields:
        assert name in ff
    assert any(o.get("label") == sibling["label"] for o in drafts[0]["options"])


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


@pytest.mark.parametrize(
    "case_id,bad_factory,number_lit,heal_fix,must_fields,expected_type",
    _overflow_case_matrix(),
    ids=[c[0] for c in _overflow_case_matrix()],
)
def test_overflow_json_number_heals_not_batch(
    case_id, bad_factory, number_lit, heal_fix, must_fields,
    expected_type, monkeypatch, tmp_path,
):
    """合法 JSON 超范围数字（±1e309→±inf）→ 同一补交；字段/现值/期望入 LLM；兄弟保留。"""
    del case_id
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = bad_factory()
    sibling = _hold(label="兄弟")
    sibling_frozen = dict(sibling)
    first = _items_json_num(
        [{"title": "u", "context": "c", "options": [bad, sibling]}],
        number_lit,
    )
    healed = _heals_json([("0:0", dict(heal_fix))])
    calls: list[dict] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        n["i"] += 1
        calls.append({
            "tag": tag,
            "prompt": prompt,
            "roles": _prior_roles(prior_messages),
            "contents": _prior_contents(prior_messages),
            "response": first if n["i"] == 1 else healed,
        })
        return calls[-1]["response"]

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=52)
    assert drafts is not None
    assert [c["tag"] for c in calls] == ["rescript-draft", "rescript-draft-heal"]
    _assert_call_history(calls)
    # 同会话：补交 prior 含首抽 user+assistant
    assert calls[1]["roles"] == ["user", "assistant"]
    assert calls[1]["contents"][1] == first
    req = _parse_heal_request(calls[1]["prompt"])
    ff = _field_failure_map(req["failures"][0])
    for name in must_fields:
        assert name in ff
        assert "current" in ff[name] and "expected" in ff[name]
        assert ff[name]["expected"] == expected_type
        # ±inf 经 JSON 运输（Infinity）loads 后仍为非有限浮点
        cur = ff[name]["current"]
        assert isinstance(cur, float) and abs(cur) == float("inf")
    opts = drafts[0]["options"]
    hold = next(o for o in opts if o.get("label") == sibling_frozen["label"])
    for k, v in sibling_frozen.items():
        assert hold.get(k) == v
    fixed = next(o for o in opts if o.get("label") == "坏项")
    for k, v in heal_fix.items():
        assert fixed.get(k) == v


@pytest.mark.parametrize("number_lit", ["1e309", "-1e309"], ids=["pos", "neg"])
def test_overflow_json_number_exhaust_drops_only_bad(
    number_lit, monkeypatch, tmp_path,
):
    """超范围数字耗尽 → 只剔坏项；兄弟保留；error pack 响亮。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _hold(due_turn=_OVERFLOW_SENTINEL, label="坏项")
    sibling = _hold(label="兄弟")
    sibling_frozen = dict(sibling)
    first = _items_json_num(
        [{"title": "u", "context": "c", "options": [bad, sibling]}],
        number_lit,
    )
    tags: list[str] = []

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        return first  # 永不修

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=53)
    assert drafts is not None
    assert tags == ["rescript-draft"] + ["rescript-draft-heal"] * RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    opts = drafts[0]["options"]
    assert len(opts) == 1
    hold = opts[0]
    for k, v in sibling_frozen.items():
        assert hold.get(k) == v
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn53.json"
    note_obj = json.loads(note.read_text(encoding="utf-8"))
    assert note_obj.get("reason") == "option_missing_fields_heal_exhausted"
    dropped = note_obj.get("dropped_options") or []
    assert dropped and dropped[0].get("heal_id") == "0:0"
    assert list(dropped[0].get("missing_fields") or []) == ["due_turn"]
    trace = note_obj.get("heal_trace") or []
    assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES


@pytest.mark.parametrize(
    "kind,mutate,heal_fix,must_field",
    [
        (
            "ungrounded",
            lambda o: o.update({"target_id": "not-in-catalog"}),
            {"target_id": "guanning"},
            "target_id",
        ),
        (
            "unknown_key",
            lambda o: o.update({"extra_junk": 1}),
            {"extra_junk": None},  # merged via full option below
            "extra_junk",
        ),
        (
            "non_object",
            None,
            None,
            "option",
        ),
    ],
    ids=["ungrounded", "unknown_key", "non_object"],
)
def test_option_shape_failures_heal_not_batch(
    kind, mutate, heal_fix, must_field, monkeypatch, tmp_path,
):
    """可定位 option 的形/接地/未知键失败 → heal；兄弟保留。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    sibling = _hold(label="兄弟")
    if kind == "non_object":
        bad: object = "not-a-dict"
        fixed_opt = _army_pay(label="边饷拟")
        first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
        healed = _heals_json([("0:0", {"option": fixed_opt})])
    elif kind == "unknown_key":
        bad = _army_pay(label="边饷拟")
        mutate(bad)
        fixed = dict(bad)
        fixed.pop("extra_junk", None)
        first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
        healed = _heals_json([("0:0", {"option": fixed})])
    else:
        bad = _army_pay(label="边饷拟")
        mutate(bad)
        first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
        healed = _heals_json([("0:0", dict(heal_fix))])
    tags: list[str] = []
    prompts: list[str] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        prompts.append(prompt)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=43)
    assert drafts is not None
    assert "rescript-draft-heal" in tags
    req = _parse_heal_request(next(
        p for t, p in zip(tags, prompts) if t == "rescript-draft-heal"
    ))
    ff = _field_failure_map(req["failures"][0])
    assert must_field in ff
    assert ff[must_field]["expected"] is not None or must_field == "extra_junk"
    assert any(o.get("label") == sibling["label"] for o in drafts[0]["options"])




def test_provider_still_whole_batch_item_missing_heals_and_drops(monkeypatch, tmp_path):
    """provider 不可用仍立即降级；#1801 ②条目缺字段走 heal，耗尽只剔该条目。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: (_ for _ in ()).throw(LLMUnavailable("down")),
    )
    assert generate_rescript_draft(object(), _ctx(), turn=19) is None

    good = {"title": "陕西告饥", "context": "赤旱", "options": [_hold(label="兄")]}
    bad = {"title": "辽饷告匮", "options": [_hold(), _army_pay()]}  # 缺 context
    raw = _items_json([good, bad])
    tags: list[str] = []

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=20)
    assert drafts is not None
    assert len(drafts) == 1 and drafts[0]["title"] == good["title"]
    assert "rescript-draft-heal" in tags


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


@pytest.mark.parametrize("bad_kind", sorted(_BAD_HEAL_RESPONSES))
@pytest.mark.parametrize(
    "succeed_on", [2, 3, None], ids=["ok_on_2", "ok_on_3", "exhaust"],
)
def test_heal_response_contract_failure_consumes_attempt_keeps_siblings(
    bad_kind, succeed_on, monkeypatch, tmp_path,
):
    """已有底稿时补交响应非法 JSON/围栏外 prose/非 object → 消耗本次补交。

    第 2/3 次成功保留全批；三次耗尽只剔坏项；兄弟逐字段不变；三轮日志完整。
    下一次补交请求须结构化携带本次响应哪里不合契约（heal_response 事实）。
    """
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="坏项", amount=300)
    bad.pop("purpose", None)
    sibling = _hold(label="兄弟稳定", hint="keep-me")
    sibling_frozen = dict(sibling)
    # 另一急务此前已成功：整批不得因补交响应失败无头版
    other_item = {
        "title": "他务",
        "context": "旁路",
        "options": [
            _hold(label="他务甲", hint="a"),
            _hold(label="他务乙", hint="b"),
        ],
    }
    other_frozen = deepcopy(other_item)
    first = _items_json([
        {"title": "缺目", "context": "c", "options": [bad, sibling]},
        other_item,
    ])
    bad_raw = _BAD_HEAL_RESPONSES[bad_kind]
    healed = _heals_json([("0:0", {"purpose": "补饷"})])
    calls: list[dict] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        n["i"] += 1
        if n["i"] == 1:
            response = first
        elif succeed_on is not None and n["i"] == succeed_on + 1:
            # succeed_on=k means heal attempt k succeeds → call index k+1
            response = healed
        else:
            response = bad_raw
        calls.append({
            "tag": tag,
            "prompt": prompt,
            "response": response,
            "roles": _prior_roles(prior_messages),
            "contents": _prior_contents(prior_messages),
        })
        return response

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=61)
    assert drafts is not None
    _assert_call_history(calls)
    tags = [c["tag"] for c in calls]
    assert tags[0] == "rescript-draft"
    assert all(t == "rescript-draft-heal" for t in tags[1:])

    if succeed_on is None:
        assert tags == (
            ["rescript-draft"]
            + ["rescript-draft-heal"] * RESCRIPT_OPTION_FIELD_HEAL_RETRIES
        )
        # 耗尽：只剔坏项；兄弟与他务保留
        by_title = {d["title"]: d for d in drafts}
        assert set(by_title) == {"缺目", "他务"}
        opts = by_title["缺目"]["options"]
        assert len(opts) == 1
        hold = opts[0]
        for k, v in sibling_frozen.items():
            assert hold.get(k) == v
        other = by_title["他务"]
        assert other["context"] == other_frozen["context"]
        assert len(other["options"]) == 2
        for got, exp in zip(other["options"], other_frozen["options"]):
            for k, v in exp.items():
                assert got.get(k) == v
        note = (
            tmp_path / "error_packs" / "rescript_draft_degraded" / "turn61.json"
        )
        note_obj = json.loads(note.read_text(encoding="utf-8"))
        assert note_obj.get("reason") == "option_missing_fields_heal_exhausted"
        trace = note_obj.get("heal_trace") or []
        assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
        dropped = note_obj.get("dropped_options") or []
        assert dropped and dropped[0].get("heal_id") == "0:0"
    else:
        assert len(tags) == succeed_on + 1
        by_title = {d["title"]: d for d in drafts}
        assert set(by_title) == {"缺目", "他务"}
        opts = by_title["缺目"]["options"]
        assert len(opts) == 2
        fixed = next(o for o in opts if o.get("label") == "坏项")
        assert fixed.get("purpose") == "补饷"
        hold = next(o for o in opts if o.get("label") == sibling_frozen["label"])
        for k, v in sibling_frozen.items():
            assert hold.get(k) == v
        other = by_title["他务"]
        for got, exp in zip(other["options"], other_frozen["options"]):
            for k, v in exp.items():
                assert got.get(k) == v

    # 每一次失败补交之后的下一次请求须携带 heal_response 契约事实
    heal_calls = [c for c in calls if c["tag"] == "rescript-draft-heal"]
    for idx in range(1, len(heal_calls)):
        # heal_calls[idx] 的 prompt 对应前一次坏响应之后
        prev_response = heal_calls[idx - 1]["response"]
        if prev_response == bad_raw:
            req = _parse_heal_request(heal_calls[idx]["prompt"])
            ff = _field_failure_map(req["failures"][0])
            assert "heal_response" in ff
            assert "purpose" in ff  # 旧缺字段仍在
            cur = ff["heal_response"]["current"]
            assert isinstance(cur, dict)
            assert cur.get("error")
            assert "raw_summary" in cur
            exp = ff["heal_response"]["expected"]
            assert isinstance(exp, dict)
            assert exp.get("type") == "object"


def test_first_draw_parse_failure_heals_then_degrades(monkeypatch, tmp_path):
    """#1801 ①a：首抽未成形 → 同一 heal 回路重试；耗尽本月无票拟且响亮留痕。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    tags: list[str] = []
    prompts: list[str] = []

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        prompts.append(prompt)
        return "not-json {"

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=62) is None
    assert tags == ["rescript-draft"] + ["rescript-draft-heal"] * RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    req = _parse_heal_request(prompts[1])
    assert req["failures"] and req["failures"][0].get("scope") == "top"
    ff = _field_failure_map(req["failures"][0])
    assert "items" in ff
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn62.json"
    assert note.is_file()


# ---------------------------------------------------------------------------
# heal_id 负向（typed 身份契约；不进 phase2 重复 k 链）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "heal_payload",
    [
        lambda bad, sib: _items_json([{
            "title": "u", "context": "c",
            "options": [dict(bad, purpose="补饷"), sib],
        }]),
        lambda bad, sib: _heals_json([("0:1", {"purpose": "补饷"})]),
        lambda bad, sib: _heals_json([
            ("0:0", {"purpose": "补饷"}),
            ("0:0", {"purpose": "补饷", "amount": 1}),
        ]),
    ],
    ids=["no_id", "wrong_slot", "duplicate_id"],
)
def test_heal_bad_identity_refuses_merge_then_drops(heal_payload, monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay", amount=300)
    bad.pop("purpose", None)
    sibling = _hold(label="stable", hint="keep")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else heal_payload(bad, sibling)

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=33)
    assert drafts is not None
    opts = drafts[0]["options"]
    assert len(opts) == 1 and opts[0]["label"] == sibling["label"]
