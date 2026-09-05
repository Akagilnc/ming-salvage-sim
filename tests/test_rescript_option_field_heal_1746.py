"""#1746：缺字段同一会话补交 ≤3 → 耗尽单 option 剔除。

真实入口：resolve_decisions_phase2（唯一 k/耗尽/多急务/部分进度/组合后补交 tracer）。
decision keys：missing-field-heal-by-resume-not-drop / per-option-drop-after-heal-exhausted。
分类负向：generate 最短分流；契约只落 prior 结构、heals/heal_id typed、外部可见结果。
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

import ming_sim.rescript_draft as rescript_mod
from ming_sim.rescript_draft import (
    RESCRIPT_OPTION_FIELD_HEAL_RETRIES,
    generate_rescript_draft,
    normalize_rescript_layer_a_option,
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
    }
    base.update(kw)
    return base


def _items_json(items: list) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


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


def _banned_tech_keys() -> set[str]:
    return {
        "heal", "healed", "dropped", "missing_fields", "补交", "剔除",
        "heal_attempts", "option_drop", "field_heal", "heal_id",
    }


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


_MISSING = object()  # draft_extra 哨兵：键不在场或空


def _heal_request_facts(prompt: str) -> list[dict]:
    """从补交请求提取结构身份 / 最新失败字段 / 底稿 option（契约键，不钉 prose 教条）。"""
    import re

    facts: list[dict] = []
    lines = str(prompt or "").splitlines()
    i = 0
    while i < len(lines):
        m = re.match(
            r"- heal_id=(\S+) item_index=(\d+) option_index=(\d+) 缺字段: (\S+)",
            lines[i],
        )
        if not m:
            i += 1
            continue
        entry: dict = {
            "heal_id": m.group(1),
            "item_index": int(m.group(2)),
            "option_index": int(m.group(3)),
            "missing_fields": [f for f in m.group(4).split(",") if f],
        }
        j = i + 1
        while j < len(lines) and lines[j].startswith("  "):
            nxt = lines[j].strip()
            if nxt.startswith("失败原因:"):
                entry["field_reasons"] = json.loads(nxt.split(":", 1)[1].strip())
            elif "原始 option:" in nxt:
                entry["draft_option"] = json.loads(
                    nxt.split("原始 option:", 1)[1].strip()
                )
            j += 1
        i = j
        facts.append(entry)
    return facts


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

def _assert_heal_error(exc: BaseException, *must_fields: str) -> None:
    assert isinstance(exc, rescript_mod.RescriptOptionMissingFieldsError), type(exc)
    got = set(exc.missing_fields)
    for f in must_fields:
        assert f in got, (f, exc.missing_fields, getattr(exc, "field_reasons", None))


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
    n = {"i": 0}

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        if n["i"] == 1:
            return first
        idx = n["i"] - 2
        return steps[idx] if idx < len(steps) else steps[-1]

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    with pytest.raises(rescript_mod.RescriptOptionMissingFieldsError) as ei:
        normalize_rescript_layer_a_option(bad, generation_admission=True)
    _assert_heal_error(ei.value, *must_fields)

    drafts = generate_rescript_draft(object(), _ctx(), turn=40)
    assert drafts is not None
    assert "rescript-draft-heal" in tags
    opts = drafts[0]["options"]
    assert any(o.get("label") == sibling["label"] for o in opts)
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    assert grant["amount"] == 300
    assert grant.get("purpose") == "补饷"


def test_amount_numeric_string_accepted_via_grant_shape(monkeypatch, tmp_path):
    """既有 grant 归一：amount='300' 经 require_grant_allocation_shape 接受为 300。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    opt = _army_pay(amount="300")
    out = normalize_rescript_layer_a_option(opt, generation_admission=True)
    assert out["amount"] == 300 and out["grant_action"] == "协饷"
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


def test_army_single_combo_even_if_target_id_blank(monkeypatch, tmp_path):
    """army+single 组合矛盾独立可判，不因 target_id 空白被缺字段遮住。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(locality_scope="single", target_id="")
    with pytest.raises(Exception) as ei:
        normalize_rescript_layer_a_option(bad, generation_admission=True)
    assert isinstance(ei.value, rescript_mod.StructuredDecreeCombinationError) or (
        type(ei.value).__name__ == "StructuredDecreeCombinationError"
    )
    # generate：组合有界重抽，不是 option heal
    first = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    fixed = _items_json([{
        "title": "u", "context": "c",
        "options": [_army_pay(locality_scope="none"), _hold()],
    }])
    tags: list[str] = []
    n = {"i": 0}

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        return first if n["i"] == 1 else fixed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=47)
    assert drafts is not None
    assert tags.count("rescript-draft") >= 2
    assert "rescript-draft-heal" not in tags


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
    n = {"i": 0}

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    with pytest.raises(rescript_mod.RescriptOptionMissingFieldsError) as ei:
        normalize_rescript_layer_a_option(bad, generation_admission=True)
    _assert_heal_error(ei.value, *must_fields)
    drafts = generate_rescript_draft(object(), _ctx(), turn=45)
    assert drafts is not None and "rescript-draft-heal" in tags
    assert any(o.get("label") == sibling["label"] for o in drafts[0]["options"])


@pytest.mark.parametrize("kind", ["ungrounded", "surrogate"], ids=["ungrounded", "surrogate_label"])
def test_missing_plus_ungrounded_or_surrogate_whole_batch(kind, monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    if kind == "ungrounded":
        bad = _army_pay(target_id="not-in-catalog")
    else:
        bad = _army_pay(label="坏\ud800标")
    bad.pop("purpose", None)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    tags: list[str] = []
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda _a, _p, tag="", prior_messages=None: (tags.append(tag) or raw),
    )
    assert generate_rescript_draft(object(), _ctx(), turn=43) is None
    assert tags == ["rescript-draft"]


def test_provider_and_item_level_still_whole_batch(monkeypatch, tmp_path):
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: (_ for _ in ()).throw(LLMUnavailable("down")),
    )
    assert generate_rescript_draft(object(), _ctx(), turn=19) is None
    raw = _items_json([{"title": "辽饷告匮", "options": [_hold(), _army_pay()]}])
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    assert generate_rescript_draft(object(), _ctx(), turn=20) is None


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


# ---------------------------------------------------------------------------
# resolve_decisions_phase2：唯一验收入口
# ---------------------------------------------------------------------------

def _phase2_hitl_setup(game, monkeypatch, tmp_path):
    import ming_sim.decree as decree_mod
    import ming_sim.simulation as simulation
    from tests.test_rescript_draft_656 import (
        _CANNED,
        _add_character,
        _retire_existing_actors,
        _stub_settle_agents,
    )

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    db, state, content = game
    turn = state.turn
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")
    sim_payload = {
        "active_issues": [],
        "regions": {"cols": ["id", "name", "kind"],
                    "rows": [["shaanxi", "陕西", "布政司"]]},
        "armies": {
            "cols": ["id", "name", "station", "owner_power"],
            "rows": [
                ["guanning", "关宁", "宁远", "ming"],
                ["xuanfu", "宣府", "宣府", "ming"],
            ],
        },
        "transit_semantics": [],
    }
    db.save_resolve_context(
        turn, "诏", "邸报全文", sim_payload,
        secret_orders={}, relevant_memories=[], extracted=None,
    )
    db.save_pending_decisions(turn, [{
        "title": "辽东战和", "context": "边事",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, status='decided' "
        "WHERE turn=? AND kind='decision'",
        (json.dumps({"label": "战", "note": ""}, ensure_ascii=False), turn),
    )
    db.conn.commit()
    return db, state, content, turn, decree_mod, simulation, _CANNED


def _assert_no_tech_keys_on_player_rows(rows: list) -> None:
    banned = _banned_tech_keys()
    for row in rows:
        assert not (banned & set(row))
        for o in row.get("options") or []:
            assert not (banned & set(o))
        assert row.get("status") == "pending"


@pytest.mark.parametrize(
    "scenario",
    [
        "k1", "k2", "k3", "exhaust",
        "partial_progress",
        "combo_then_heal",
        "reorder_identity",
    ],
)
def test_phase2_entry_heal_k_or_exhaust(scenario, game, monkeypatch, tmp_path):
    """唯一 phase2 tracer：k/耗尽、部分进度、组合后底稿、显式身份、逐字段冻结、prior 结构。"""
    db, state, content, turn, decree_mod, simulation, _CANNED = _phase2_hitl_setup(
        game, monkeypatch, tmp_path,
    )
    sibling = _hold(
        label="缓边", hint="候核",
        transaction_category="督赈", region_id="shaanxi",
    )
    sibling_frozen = dict(sibling)
    calls: list[dict] = []

    if scenario in ("k1", "k2", "k3", "exhaust"):
        succeed_on = {"k1": 1, "k2": 2, "k3": 3, "exhaust": None}[scenario]
        bad = _army_pay(label="边饷拟", amount=150)
        bad.pop("purpose", None)
        first_items = [{
            "title": "关宁欠饷", "context": "边军待哺。",
            "options": [bad, sibling],
        }]
        first_raw = _items_json(first_items)
        healed_raw = _items_json([{
            "title": "关宁欠饷", "context": "边军待哺。",
            "options": [
                dict(bad, purpose="补饷", amount=999, heal_id="0:0"),
                dict(sibling, label="被改写", hint="坏", heal_id="0:1"),
            ],
        }])
        heal_n = {"i": 0}

        def _script(tag, prior_messages):
            heal_n["i"] += 1
            if succeed_on is None:
                return first_raw
            if heal_n["i"] == 1:
                return first_raw
            if heal_n["i"] - 1 < succeed_on:
                return first_raw
            return healed_raw

        expected_heal_calls = (
            RESCRIPT_OPTION_FIELD_HEAL_RETRIES if succeed_on is None else succeed_on
        )

    elif scenario == "partial_progress":
        bad = _army_pay(label="边饷拟", amount=200)
        bad.pop("purpose", None)
        bad["account"] = ""
        first_raw = _items_json([{
            "title": "关宁欠饷", "context": "边军待哺。",
            "options": [bad, sibling],
        }])
        heal1 = _heals_json([("0:0", {"purpose": "补饷"})])
        heal2 = _heals_json([("0:0", {"account": "国库", "amount": 999})])
        step = {"i": 0}

        def _script(tag, prior_messages):
            step["i"] += 1
            if step["i"] == 1:
                return first_raw
            if step["i"] == 2:
                return heal1
            return heal2

        expected_heal_calls = 2
        succeed_on = "partial"
        bad_amount = 200

    elif scenario == "combo_then_heal":
        first_combo = {
            "title": "关宁欠饷", "context": "边军待哺。",
            "options": [
                _army_pay(locality_scope="single", label="边饷拟", amount=150),
                sibling,
            ],
        }
        after_combo = deepcopy(first_combo)
        after_combo["options"][0]["locality_scope"] = "none"
        after_combo["options"][0].pop("purpose", None)
        first_raw = _items_json([first_combo])
        combo_fixed_raw = _items_json([after_combo])
        heal_raw = _heals_json([("0:0", {"purpose": "补饷", "amount": 999})])
        step = {"i": 0}

        def _script(tag, prior_messages):
            step["i"] += 1
            if step["i"] == 1:
                return first_raw
            if step["i"] == 2:
                return combo_fixed_raw
            return heal_raw

        expected_heal_calls = 1
        succeed_on = "combo"
        bad_amount = 150

    else:  # reorder_identity
        bad = _army_pay(label="同名拟", amount=120)
        bad.pop("purpose", None)
        twin = _hold(label="同名拟", hint="缓", transaction_category="督赈")
        sibling_frozen = dict(twin)
        first_raw = _items_json([{
            "title": "同题", "context": "边军待哺。",
            "options": [bad, twin],
        }])
        # 响应倒序 + 显式 heal_id；企图改 amount
        healed_raw = _items_json([{
            "title": "同题", "context": "边军待哺。",
            "options": [
                dict(twin, heal_id="0:1"),
                dict(bad, purpose="补饷", amount=999, heal_id="0:0"),
            ],
        }])
        step = {"i": 0}

        def _script(tag, prior_messages):
            step["i"] += 1
            return first_raw if step["i"] == 1 else healed_raw

        expected_heal_calls = 1
        succeed_on = "reorder"
        bad_amount = 120
        sibling = twin

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent
        if tag.startswith("extractor/") or tag.startswith("sanitizer/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            prior = list(prior_messages or [])
            raw = _script(tag, prior_messages)
            calls.append({
                "tag": tag,
                "prompt": prompt,
                "roles": _prior_roles(prior),
                "contents": _prior_contents(prior),
                "response": raw,
            })
            return raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _fake_run)
    monkeypatch.setattr(
        decree_mod, "create_rescript_draft_agent", lambda *a, **k: object(),
    )

    report = decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )
    assert isinstance(report, str) and report

    rows = db.list_rescript_drafts()
    assert len(rows) == 1
    _assert_no_tech_keys_on_player_rows(rows)
    banned = _banned_tech_keys()
    for d in db.list_rescript_desk(turn):
        if d.get("kind") != "rescript_draft":
            continue
        assert not (banned & set(d))
        for o in d.get("options") or []:
            assert not (banned & set(o))

    opts = rows[0]["options"]
    assert db.list_pending_decisions(turn) == []
    assert calls[0]["tag"] == "rescript-draft"
    # 原始 user 入场：首抽 prior 空，prompt 即 payload（非空 JSON 对象）
    assert calls[0]["roles"] == [] and calls[0]["contents"] == []
    first_user = json.loads(calls[0]["prompt"])
    assert isinstance(first_user, dict)
    _assert_call_history(calls)

    heal_calls = [c for c in calls if c["tag"] == "rescript-draft-heal"]
    assert len(heal_calls) == expected_heal_calls

    def _expect_heal_identity(hc, *, missing, draft_amount, draft_extra=None):
        facts = _heal_request_facts(hc["prompt"])
        assert len(facts) == 1
        fact = facts[0]
        assert fact["heal_id"] == "0:0"
        assert fact["item_index"] == 0 and fact["option_index"] == 0
        assert fact["missing_fields"] == list(missing)
        draft = fact["draft_option"]
        assert draft.get("heal_id") == "0:0"
        assert draft.get("amount") == draft_amount
        if draft_extra:
            for k, v in draft_extra.items():
                if v is _MISSING:
                    assert k not in draft or draft.get(k) in (None, "")
                else:
                    assert draft.get(k) == v
        return fact

    # combo：calls[0]=首抽 combo 错, calls[1]=组合重抽, calls[2]=heal；
    # 请求与合并均以最新底稿（combo_fixed）为准，prior 含完整两轮。
    if scenario == "combo_then_heal":
        assert [c["tag"] for c in calls] == [
            "rescript-draft", "rescript-draft", "rescript-draft-heal",
        ]
        assert calls[0]["response"] == first_raw
        assert calls[1]["response"] == combo_fixed_raw
        assert heal_calls[0]["contents"][1] == first_raw
        assert heal_calls[0]["contents"][3] == combo_fixed_raw
        _expect_heal_identity(
            heal_calls[0],
            missing=["purpose"],
            draft_amount=bad_amount,
            draft_extra={
                "locality_scope": "none",
                "purpose": _MISSING,
                "label": "边饷拟",
            },
        )
    elif scenario == "partial_progress":
        # 第 1 次索 purpose+account；第 2 次只索尚缺 account，底稿保留已补 purpose 与 amount
        assert len(heal_calls) == 2
        _expect_heal_identity(
            heal_calls[0],
            missing=["account", "purpose"],
            draft_amount=bad_amount,
            draft_extra={"purpose": _MISSING, "account": _MISSING},
        )
        _expect_heal_identity(
            heal_calls[1],
            missing=["account"],
            draft_amount=bad_amount,
            draft_extra={"purpose": "补饷"},
        )
        # 完整顺序：原始 user + 首抽 assistant + heal1 user/asst
        assert heal_calls[1]["contents"][1] == first_raw
        assert heal_calls[1]["contents"][2] == heal_calls[0]["prompt"]
        assert heal_calls[1]["contents"][3] == heal_calls[0]["response"]
    else:
        for hc in heal_calls:
            _expect_heal_identity(
                hc,
                missing=["purpose"],
                draft_amount=bad_amount if scenario == "reorder_identity" else 150,
                draft_extra={
                    "purpose": _MISSING,
                    "label": (
                        "同名拟" if scenario == "reorder_identity" else "边饷拟"
                    ),
                },
            )
            assert hc["contents"][1] == first_raw

    if scenario == "exhaust":
        assert len(opts) == 1
        hold = opts[0]
        for k, v in sibling_frozen.items():
            assert hold.get(k) == v
        note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
        note_obj = json.loads(note.read_text(encoding="utf-8"))
        assert note_obj.get("reason") == "option_missing_fields_heal_exhausted"
        assert "missing_fields_detail" not in note_obj
        dropped = note_obj.get("dropped_options") or []
        assert dropped and dropped[0].get("heal_id") == "0:0"
        assert list(dropped[0].get("missing_fields") or []) == ["purpose"]
        trace = note_obj.get("heal_trace") or []
        assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
        for i, entry in enumerate(trace, start=1):
            assert entry.get("attempt") == i
            assert str(entry.get("raw_summary") or "").strip()
            fails = entry.get("failures") or []
            assert fails[0].get("heal_id") == "0:0"
            assert list(fails[0].get("missing_fields") or []) == ["purpose"]
        return

    assert len(opts) == 2
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    hold = next(o for o in opts if o.get("action_type") == "assignment")
    assert grant["purpose"] == "补饷"
    if scenario == "partial_progress":
        assert grant["account"] == "国库"
        assert grant["amount"] == bad_amount
    elif scenario in ("combo_then_heal", "reorder_identity"):
        assert grant["amount"] == bad_amount
    else:
        assert grant["amount"] == 150
        assert grant["label"] == "边饷拟"
        assert grant["account"] == "国库"
        assert grant["target_id"] == "guanning"
    for k, v in sibling_frozen.items():
        assert hold.get(k) == v, f"sibling field {k} mutated"


def test_phase2_multi_urgent_isolation_and_zero_item(game, monkeypatch, tmp_path):
    db, state, content, turn, decree_mod, simulation, _CANNED = _phase2_hitl_setup(
        game, monkeypatch, tmp_path,
    )
    bad1 = _army_pay(label="关宁补饷")
    bad1.pop("purpose", None)
    u1 = {
        "title": "关宁急饷", "context": "关宁待哺。",
        "options": [bad1, _hold(label="关宁缓议", hint="候边报")],
    }
    bad2a = _army_pay(label="宣大甲", target_id="xuanfu", amount=120)
    bad2a.pop("purpose", None)
    bad2b = _army_pay(label="宣大乙", target_id="xuanfu", amount=80)
    bad2b.pop("purpose", None)
    u2 = {"title": "宣大欠饷", "context": "宣大告急。", "options": [bad2a, bad2b]}
    u3_a = _hold(label="赈A", hint="ha", transaction_category="督赈")
    u3_b = _hold(label="赈B", hint="b", transaction_category="督赈")
    u3 = {"title": "陕西告饥", "context": "秦旱。", "options": [u3_a, u3_b]}
    first = _items_json([u1, u2, u3])
    fixed_u1 = deepcopy(u1)
    fixed_u1["options"][0]["purpose"] = "补饷"
    after = _items_json(_stamp_heal_ids([fixed_u1, u2, u3]))
    n = {"i": 0}
    calls: list[dict] = []

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent
        if tag.startswith("extractor/") or tag.startswith("sanitizer/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            n["i"] += 1
            prior = list(prior_messages or [])
            raw = first if n["i"] == 1 else after
            calls.append({
                "tag": tag,
                "prompt": prompt,
                "roles": _prior_roles(prior),
                "contents": _prior_contents(prior),
                "response": raw,
            })
            return raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _fake_run)
    monkeypatch.setattr(
        decree_mod, "create_rescript_draft_agent", lambda *a, **k: object(),
    )
    assert isinstance(
        decree_mod.resolve_decisions_phase2(state, db, None, None, content=content),
        str,
    )
    rows = {r["title"]: r for r in db.list_rescript_drafts()}
    assert u2["title"] not in rows
    assert set(rows) == {u1["title"], u3["title"]}
    _assert_no_tech_keys_on_player_rows(list(rows.values()))
    assert any(
        o.get("grant_action") == "协饷" and o.get("purpose") == "补饷"
        for o in rows[u1["title"]]["options"]
    )
    assert len(rows[u3["title"]]["options"]) == 2
    got_u3 = {o["label"]: o for o in rows[u3["title"]]["options"]}
    for src in (u3_a, u3_b):
        got = got_u3[src["label"]]
        for k, v in src.items():
            assert got.get(k) == v
    assert calls[0]["tag"] == "rescript-draft" and calls[0]["roles"] == []
    _assert_call_history(calls)
    heal_calls = [c for c in calls if c["tag"] == "rescript-draft-heal"]
    assert heal_calls
    # 多急务：heal 请求以结构身份回指坏项，且只索尚缺字段
    facts = _heal_request_facts(heal_calls[0]["prompt"])
    assert {f["heal_id"] for f in facts} >= {"0:0", "1:0", "1:1"}
    for fact in facts:
        assert fact["missing_fields"] == ["purpose"]
        assert fact["draft_option"].get("heal_id") == fact["heal_id"]
