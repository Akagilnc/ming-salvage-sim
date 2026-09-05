"""#1746：缺字段同一会话补交 ≤3 → 耗尽单 option 剔除。

真实入口：resolve_decisions_phase2（web/亲裁续跑读 persisted resolve_context）。
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


def _healed_items_from(first_items: list) -> list:
    items = _stamp_heal_ids(first_items)
    for it in items:
        for opt in it["options"]:
            if (
                opt.get("action_type") == "grant_allocation"
                and not str(opt.get("purpose") or "").strip()
            ):
                opt["purpose"] = "补饷"
    return items


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
# 层 A 分类：非法值不得进补交
# ---------------------------------------------------------------------------

def test_illegal_amount_does_not_enter_missing_heal(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(amount=-5)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=40) is None
    assert len(calls) == 1


def test_missing_grant_kind_with_illegal_amount_not_heal(monkeypatch, tmp_path):
    """双缺 grant_kind 不得短路吞掉已给的非正 amount。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(amount=-5)
    bad.pop("grant_kind", None)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=42) is None
    assert len(calls) == 1
    with pytest.raises(ValueError, match="amount"):
        normalize_rescript_layer_a_option(bad, generation_admission=True)


@pytest.mark.parametrize(
    "bad_kw, match",
    [
        ({"label": "", "amount": -5}, "amount"),
        ({"label": "", "amount": 3.5}, "amount"),  # float 拒，不得 int() 截断
        ({"label": "", "grant_kind": "bogus"}, "grant_kind"),
    ],
    ids=["neg_amount", "float_amount", "bogus_grant_kind"],
)
def test_missing_label_with_coexisting_illegal_not_heal(
    bad_kw, match, monkeypatch, tmp_path,
):
    """前置缺 label + 同 option 非法值 → F2.5，不进补交。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(**bad_kw)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=45) is None
    assert len(calls) == 1
    with pytest.raises(ValueError, match=match):
        normalize_rescript_layer_a_option(bad, generation_admission=True)


def test_deadline_months_non_int_is_illegal_not_absent():
    mo = {
        "label": "调关宁",
        "hint": "边情",
        "action_type": "military_order",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "assignee_name": "袁崇焕",
        "transaction_category": "",
        "station": "宁远",
        "deadline_months": "abc",
    }
    with pytest.raises(ValueError, match="deadline_months"):
        normalize_rescript_layer_a_option(mo, generation_admission=True)


def test_illegal_purpose_value_does_not_enter_missing_heal(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(purpose="赈灾")
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=41) is None
    assert len(calls) == 1


def test_required_wrong_type_not_missing_heal():
    bad = _hold(label=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="须为 str"):
        normalize_rescript_layer_a_option(bad, generation_admission=True)


def test_missing_plus_ungrounded_target_whole_batch(monkeypatch, tmp_path):
    """缺 purpose + army target 不在 catalog → 整批 F2.5，不进补交。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(target_id="not-in-catalog")
    bad.pop("purpose", None)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=43) is None
    assert len(calls) == 1


def test_missing_plus_surrogate_label_whole_batch(monkeypatch, tmp_path):
    """缺 purpose + label 含 lone surrogate → UTF-8 F2.5，不进补交、不炸 tlog。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="坏\ud800标")
    bad.pop("purpose", None)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=44) is None
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 结构身份 / 部分进度 / 冻结（generate 最短负向+契约）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "heal_payload",
    [
        lambda bad, sibling: _items_json([{
            "title": "u", "context": "c",
            "options": [dict(bad, purpose="补饷"), sibling],
        }]),
        lambda bad, sibling: _heals_json([("0:1", {"purpose": "补饷"})]),
        lambda bad, sibling: json.dumps({
            "heals": [
                {"heal_id": "0:0", "purpose": "补饷"},
                {"heal_id": "0:0", "purpose": "补饷", "amount": 1},
            ],
        }, ensure_ascii=False),
    ],
    ids=["no_id", "wrong_slot", "duplicate_id"],
)
def test_heal_bad_identity_refuses_merge_then_drops(heal_payload, monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay", amount=300)
    bad.pop("purpose", None)
    sibling = _hold(label="stable", hint="keep")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    healed = heal_payload(bad, sibling)
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=33)
    assert drafts is not None
    opts = drafts[0]["options"]
    assert len(opts) == 1
    assert opts[0]["label"] == sibling["label"]
    assert all(o.get("grant_action") != "协饷" for o in opts)


def test_heal_partial_and_freeze_world_facts(monkeypatch, tmp_path):
    """分次补齐 + 世界事实冻结 + heals 契约。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay-partial", amount=300, account="")
    bad.pop("purpose", None)
    sibling = _hold(label="sib", hint="p")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    seq = [
        first,
        _heals_json([("0:0", {"purpose": "补饷", "amount": 999})]),
        _heals_json([("0:0", {"account": "国库"})]),
    ]
    n = {"i": 0}

    def _llm(*_a, **_k):
        i = n["i"]
        n["i"] += 1
        return seq[min(i, len(seq) - 1)]

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=37)
    assert drafts is not None
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷"
    assert grant["account"] == "国库"
    assert grant["amount"] == 300  # 冻结，非 999
    sib = next(o for o in drafts[0]["options"] if o.get("action_type") == "assignment")
    assert sib["label"] == sibling["label"]
    assert n["i"] == 3


def test_combo_then_field_heal_uses_session_baseline(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    combo_bad = _army_pay(label="combo", locality_scope="single")
    field_bad = _army_pay(label="field", target_id="guanning", amount=200)
    field_bad.pop("purpose", None)
    combo_fixed = dict(combo_bad, locality_scope="none")
    field_fixed = dict(field_bad, purpose="补饷")
    first = _items_json([{
        "title": "辽东欠饷", "context": "九边告匮。",
        "options": [combo_bad, field_bad],
    }])
    after_combo = _items_json([{
        "title": "辽东欠饷", "context": "九边告匮。",
        "options": [combo_fixed, field_bad],
    }])
    after_heal = _heals_json([("0:1", {"purpose": "补饷"})])
    calls: list[dict] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        del prompt
        calls.append({"tag": tag, "prior_len": len(prior_messages or [])})
        if len(calls) == 1:
            return first
        if tag == "rescript-draft":
            return after_combo
        return after_heal

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=30)
    assert drafts is not None
    by_label = {o["label"]: o for o in drafts[0]["options"]}
    assert by_label["combo"]["locality_scope"] == "none"
    assert by_label["field"]["purpose"] == "补饷"
    assert by_label["field"]["amount"] == 200
    heal_calls = [c for c in calls if c["tag"] == "rescript-draft-heal"]
    assert heal_calls and heal_calls[0]["prior_len"] >= 4


def test_action_conditional_and_grant_kind_heal(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    mo_bad = {
        "label": "调关宁赴援",
        "hint": "边情急",
        "action_type": "military_order",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "assignee_name": "",
        "transaction_category": "",
        "station": "宁远",
    }
    sibling = _hold(label="缓议", hint="候报")
    first = _items_json([{
        "title": "关宁请援", "context": "奴贼压境。",
        "options": [mo_bad, sibling],
    }])
    healed = _heals_json([("0:0", {"assignee_name": "袁崇焕"})])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=31)
    assert drafts is not None
    mo = next(o for o in drafts[0]["options"] if o["action_type"] == "military_order")
    assert mo["assignee_name"] == "袁崇焕"


def test_provider_and_item_level_still_whole_batch(monkeypatch, tmp_path):
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    def _boom(*_a, **_k):
        raise LLMUnavailable("provider down")

    monkeypatch.setattr(rescript_mod, "run_agent_text", _boom)
    assert generate_rescript_draft(object(), _ctx(), turn=19) is None

    raw = _items_json([{
        "title": "辽饷告匮",
        "options": [_hold(), _army_pay()],
    }])
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    assert generate_rescript_draft(object(), _ctx(), turn=20) is None


def test_combo_correction_tag_not_heal(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad_combo = {
        "title": "辽东欠饷",
        "context": "九边欠饷。",
        "options": [_army_pay(locality_scope="single"), _hold()],
    }
    good_combo = deepcopy(bad_combo)
    good_combo["options"][0]["locality_scope"] = "none"
    calls: list[dict] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        del prompt
        calls.append({"tag": tag, "prior_len": len(prior_messages or [])})
        if len(calls) == 1:
            return _items_json([bad_combo])
        return _items_json([good_combo])

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=18)
    assert drafts is not None
    assert all(c["tag"] == "rescript-draft" for c in calls)
    assert calls[1]["prior_len"] >= 2
    assert drafts[0]["options"][0]["locality_scope"] == "none"


# ---------------------------------------------------------------------------
# 真实入口：resolve_decisions_phase2（唯一 k/耗尽/多急务 tracer）
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
        turn, "诏", "邸报全文",
        sim_payload,
        secret_orders={},
        relevant_memories=[],
        extracted=None,
    )
    db.save_pending_decisions(turn, [{
        "title": "辽东战和",
        "context": "边事",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, status='decided' "
        "WHERE turn=? AND kind='decision'",
        (json.dumps({"label": "战", "note": ""}, ensure_ascii=False), turn),
    )
    db.conn.commit()
    assert db.get_resolve_context(turn) is not None
    assert db.get_resolve_context(turn).get("extracted") is None
    return db, state, content, turn, decree_mod, simulation, _CANNED


def _assert_no_tech_keys_on_player_rows(rows: list) -> None:
    banned = _banned_tech_keys()
    for row in rows:
        assert not (banned & set(row))
        for o in row.get("options") or []:
            assert not (banned & set(o))
        # 批红 desk 同源字段：status 仍为候选 pending
        assert row.get("status") == "pending"


@pytest.mark.parametrize("succeed_on", [1, 2, 3, None])
def test_phase2_entry_heal_k_or_exhaust(succeed_on, game, monkeypatch, tmp_path):
    """亲裁续跑唯一 k 参数化：会话 prior、落库、玩家通道无技术键、error pack。"""
    db, state, content, turn, decree_mod, simulation, _CANNED = _phase2_hitl_setup(
        game, monkeypatch, tmp_path,
    )

    bad = _army_pay(label="边饷拟", amount=150)
    bad.pop("purpose", None)
    sibling = _hold(label="缓边", hint="候核")
    first_items = [{
        "title": "关宁欠饷", "context": "边军待哺。",
        "options": [bad, sibling],
    }]
    first_raw = _items_json(first_items)
    healed_raw = _items_json(_healed_items_from(first_items))
    heal_n = {"i": 0}
    priors: list[int] = []

    heal_prompts: list[str] = []

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent
        if tag.startswith("extractor/") or tag.startswith("sanitizer/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            heal_n["i"] += 1
            priors.append(len(prior_messages or []))
            if tag == "rescript-draft-heal":
                heal_prompts.append(prompt)
                assert len(prior_messages or []) >= 2
                assert (prior_messages or [])[1].get("content") == first_raw
                # 结构化契约：请求携带 heal_id 与缺字段名，不整份粘贴首抽 raw
                assert "0:0" in prompt
                assert "purpose" in prompt
                assert first_raw not in prompt
            if succeed_on is None:
                return first_raw
            if heal_n["i"] == 1:
                return first_raw
            if heal_n["i"] - 1 < succeed_on:
                return first_raw
            return healed_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _fake_run)
    monkeypatch.setattr(
        decree_mod, "create_rescript_draft_agent", lambda *a, **k: object(),
    )

    report = decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )
    assert isinstance(report, str) and report  # 结算报告非空；不扫描正文措辞

    rows = db.list_rescript_drafts()
    assert len(rows) == 1
    _assert_no_tech_keys_on_player_rows(rows)
    banned = _banned_tech_keys()
    # desk 读面：结构键成员，不扫自由文
    desk = [r for r in db.list_rescript_desk(turn) if r.get("kind") == "rescript_draft"]
    for d in desk:
        assert not (banned & set(d))
        for o in d.get("options") or []:
            assert not (banned & set(o))

    opts = rows[0]["options"]
    assert db.list_pending_decisions(turn) == []
    if succeed_on is None:
        assert len(opts) == 1
        assert opts[0]["label"] == sibling["label"]
        note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
        assert note.is_file()
        note_obj = json.loads(note.read_text(encoding="utf-8"))
        assert note_obj.get("reason") == "option_missing_fields_heal_exhausted"
        assert "missing_fields_detail" not in note_obj
        dropped = note_obj.get("dropped_options") or []
        assert dropped and dropped[0].get("heal_id") == "0:0"
        assert "purpose" in (dropped[0].get("missing_fields") or [])
        trace = note_obj.get("heal_trace") or []
        assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
        for i, entry in enumerate(trace, start=1):
            assert entry.get("attempt") == i
            assert str(entry.get("raw_summary") or "").strip()
            fails = entry.get("failures") or []
            assert fails and fails[0].get("heal_id") == "0:0"
            assert "purpose" in (fails[0].get("missing_fields") or [])
        assert len(heal_prompts) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    else:
        assert len(opts) == 2
        grant = next(o for o in opts if o.get("grant_action") == "协饷")
        assert grant["purpose"] == "补饷" and grant["amount"] == bad["amount"]
        assert heal_n["i"] == 1 + succeed_on
        assert priors[0] == 0
        assert all(p >= 2 for p in priors[1:])
        assert heal_prompts  # 至少一次补交请求经真实回路


def test_phase2_multi_urgent_isolation_and_zero_item(game, monkeypatch, tmp_path):
    """多急务隔离 + 一急务 options 全剔后其它急务仍呈。"""
    db, state, content, turn, decree_mod, simulation, _CANNED = _phase2_hitl_setup(
        game, monkeypatch, tmp_path,
    )

    bad1 = _army_pay(label="关宁补饷")
    bad1.pop("purpose", None)
    good1 = _hold(label="关宁缓议", hint="候边报")
    u1 = {"title": "关宁急饷", "context": "关宁待哺。", "options": [bad1, good1]}
    bad2a = _army_pay(label="宣大甲", target_id="xuanfu", amount=120)
    bad2a.pop("purpose", None)
    bad2b = _army_pay(label="宣大乙", target_id="xuanfu", amount=80)
    bad2b.pop("purpose", None)
    u2_all_bad = {
        "title": "宣大欠饷", "context": "宣大告急。",
        "options": [bad2a, bad2b],
    }
    u3 = {
        "title": "陕西告饥", "context": "秦旱。",
        "options": [_hold(label="赈A"), _hold(label="赈B", hint="b")],
    }
    first = _items_json([u1, u2_all_bad, u3])
    fixed_u1 = deepcopy(u1)
    fixed_u1["options"][0]["purpose"] = "补饷"
    # u2 仍缺；u3 原样
    after = _items_json(_stamp_heal_ids([fixed_u1, u2_all_bad, u3]))
    n = {"i": 0}

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent, prompt, prior_messages
        if tag.startswith("extractor/") or tag.startswith("sanitizer/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            n["i"] += 1
            return first if n["i"] == 1 else after
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _fake_run)
    monkeypatch.setattr(
        decree_mod, "create_rescript_draft_agent", lambda *a, **k: object(),
    )
    report = decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )
    assert isinstance(report, str)
    rows = {r["title"]: r for r in db.list_rescript_drafts()}
    assert u2_all_bad["title"] not in rows  # 全剔 → 条目消失
    assert set(rows) == {u1["title"], u3["title"]}
    _assert_no_tech_keys_on_player_rows(list(rows.values()))
    g1 = rows[u1["title"]]["options"]
    assert any(o.get("grant_action") == "协饷" and o.get("purpose") == "补饷" for o in g1)
    assert len(rows[u3["title"]]["options"]) == 2
