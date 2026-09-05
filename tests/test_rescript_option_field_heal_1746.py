"""#1746：缺字段同一会话补交 ≤3 → 耗尽单 option 剔除。

真实入口：resolve_decisions_phase2（唯一 k/耗尽/多急务 tracer）。
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
# 分类：真实分流（generate）；非法/组合 ≠ missing heal
# ---------------------------------------------------------------------------

def _assert_not_missing_error(exc: BaseException) -> None:
    """分类负向：不得用 ValueError 父类吞掉 missing 子类。"""
    assert not isinstance(exc, rescript_mod.RescriptOptionMissingFieldsError)
    assert not isinstance(exc, rescript_mod.RescriptOptionMissingFieldsBatch)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o.update({"amount": -5}),
        lambda o: o.update({"purpose": "赈灾"}),
        lambda o: o.update({"label": "", "amount": -5}),
        lambda o: o.update({"label": "", "amount": 3.5}),
        lambda o: o.update({"label": "", "grant_kind": "bogus"}),
        lambda o: o.update({"label": "", "cadence": "weekly"}),
        lambda o: o.update({"label": "", "account": "坏账"}),
        lambda o: (o.update({"amount": -5}), o.pop("grant_kind", None)),
        lambda o: (o.update({"label": "", "amount": -5}), o.pop("assignee_name", None)),
        lambda o: (o.pop("amount", None), o.update({"cadence": "weekly"})),
    ],
    ids=[
        "neg_amount", "bad_purpose",
        "miss_label_neg_amt", "miss_label_float", "miss_label_bogus_kind",
        "miss_label_cadence", "miss_label_account",
        "miss_kind_neg_amt", "miss_label_assignee_neg_amt", "miss_amt_bad_cadence",
    ],
)
def test_illegal_or_coexisting_illegal_not_heal(mutate, monkeypatch, tmp_path):
    """真实 generate 分流：非法/共处非法 → 整批降级，零 heal 调用。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay()
    mutate(bad)
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    tags: list[str] = []

    def _llm(_a, _p, tag="", prior_messages=None):
        tags.append(tag)
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=40) is None
    assert tags == ["rescript-draft"]
    with pytest.raises(Exception) as ei:
        normalize_rescript_layer_a_option(bad, generation_admission=True)
    _assert_not_missing_error(ei.value)


def test_missing_target_kind_only_heals_not_combo_batch(monkeypatch, tmp_path):
    """反例1：合法 army_pay 仅缺 target_kind → 补交，不得虚填 region 变组合整批 None。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay()
    bad.pop("target_kind")
    sibling = _hold()
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
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
    assert len(drafts[0]["options"]) == 2
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["target_kind"] == "army" and grant["amount"] == 300


def test_dual_missing_discriminator_heals_grant_action(monkeypatch, tmp_path):
    """反例4：region grant 双缺辨别 → 索 grant_kind|grant_action；可补合法 grant_action。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _hold(action_type="grant_allocation", amount=50, account="国库")
    bad.pop("grant_action", None)
    bad.pop("grant_kind", None)
    sibling = _hold(label="hold2")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    healed = _heals_json([("0:0", {"grant_action": "赈灾"})])
    tags: list[str] = []
    n = {"i": 0}

    def _llm(_a, prompt, tag="", prior_messages=None):
        tags.append(tag)
        n["i"] += 1
        if n["i"] == 1:
            return first
        assert "grant_kind" in prompt and "grant_action" in prompt
        return healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=44)
    assert drafts is not None and "rescript-draft-heal" in tags
    grant = next(o for o in drafts[0]["options"] if o.get("action_type") == "grant_allocation")
    assert grant["grant_action"] == "赈灾" and grant["amount"] == 50


def test_deadline_months_non_int_is_illegal_not_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    mo = {
        "label": "调关宁", "hint": "边情", "action_type": "military_order",
        "target_kind": "army", "target_id": "guanning", "locality_scope": "none",
        "region_id": "", "assignee_name": "袁崇焕", "transaction_category": "",
        "station": "宁远", "deadline_months": "abc",
    }
    raw = _items_json([{"title": "u", "context": "c", "options": [mo, _hold()]}])
    tags: list[str] = []
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda _a, _p, tag="", prior_messages=None: (tags.append(tag) or raw),
    )
    assert generate_rescript_draft(object(), _ctx(), turn=45) is None
    assert tags == ["rescript-draft"]
    with pytest.raises(Exception) as ei:
        normalize_rescript_layer_a_option(mo, generation_admission=True)
    _assert_not_missing_error(ei.value)


def test_required_wrong_type_not_missing_heal(monkeypatch, tmp_path):
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _hold(label=123)  # type: ignore[arg-type]
    raw = _items_json([{"title": "u", "context": "c", "options": [bad, _hold()]}])
    tags: list[str] = []
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda _a, _p, tag="", prior_messages=None: (tags.append(tag) or raw),
    )
    assert generate_rescript_draft(object(), _ctx(), turn=46) is None
    assert tags == ["rescript-draft"]
    with pytest.raises(Exception) as ei:
        normalize_rescript_layer_a_option(bad, generation_admission=True)
    _assert_not_missing_error(ei.value)


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


def test_combo_then_heal_uses_latest_working_draft(monkeypatch, tmp_path):
    """组合重抽刷新底稿后，补交合并以最新整批为基（非首抽 raw）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    # 首抽：组合错（army+single）
    first_bad = {
        "title": "辽东欠饷", "context": "c",
        "options": [
            _army_pay(locality_scope="single", label="边饷", amount=150),
            _hold(label="缓边", hint="候核", transaction_category="督赈"),
        ],
    }
    # 组合纠正后：缺 purpose
    after_combo = deepcopy(first_bad)
    after_combo["options"][0]["locality_scope"] = "none"
    after_combo["options"][0].pop("purpose", None)
    # 补交：按 heal_id 回填 purpose；尝试改 amount 不得落
    heal = _heals_json([("0:0", {"purpose": "补饷", "amount": 999})])
    calls: list[dict] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        calls.append({
            "tag": tag,
            "prompt": prompt,
            "prior": list(prior_messages or []),
            "roles": [m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
                      for m in (prior_messages or [])],
        })
        i = len(calls)
        if i == 1:
            return _items_json([first_bad])
        if i == 2:
            return _items_json([after_combo])
        return heal

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=18)
    assert drafts is not None
    assert [c["tag"] for c in calls] == [
        "rescript-draft", "rescript-draft", "rescript-draft-heal",
    ]
    # 历次 prior：首抽空；组合重抽含首轮 user/assistant；heal 含至组合纠正的会话
    assert calls[0]["prior"] == []
    assert calls[1]["roles"] == ["user", "assistant"]
    assert calls[2]["roles"] == ["user", "assistant", "user", "assistant"]
    assert "heal_id" in calls[2]["prompt"] and "purpose" in calls[2]["prompt"]
    opts = drafts[0]["options"]
    assert len(opts) == 2
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷"
    assert grant["amount"] == 150  # 补交改 999 不落
    hold = next(o for o in opts if o.get("action_type") == "assignment")
    assert hold["label"] == "缓边" and hold["transaction_category"] == "督赈"


# ---------------------------------------------------------------------------
# heal_id 负向（heals typed 契约；不进 phase2 重复 k 链）
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


def test_heal_same_title_reorder_explicit_heal_id(monkeypatch, tmp_path):
    """同题同名/重排：只认显式 heal_id，不按位次/label 猜配。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="同名拟", amount=120)
    bad.pop("purpose", None)
    sibling = _hold(label="同名拟", hint="缓")
    first = _items_json([{"title": "同题", "context": "c", "options": [bad, sibling]}])
    # 响应 options 倒序，且只给 heal_id=0:0
    healed = _items_json([{
        "title": "同题", "context": "c",
        "options": [
            dict(sibling, heal_id="0:1"),
            dict(bad, purpose="补饷", amount=999, heal_id="0:0"),
        ],
    }])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=34)
    assert drafts is not None
    opts = drafts[0]["options"]
    assert len(opts) == 2
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷" and grant["amount"] == 120  # 冻结
    hold = next(o for o in opts if o.get("action_type") == "assignment")
    assert hold["hint"] == "缓"


def test_heal_partial_progress_then_complete(monkeypatch, tmp_path):
    """部分进度：先补 purpose，再补 account；已填保留。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(amount=200)
    bad.pop("purpose", None)
    bad["account"] = ""
    sibling = _hold(label="s", hint="h")
    first = _items_json([{"title": "u", "context": "c", "options": [bad, sibling]}])
    heal1 = _heals_json([("0:0", {"purpose": "补饷"})])
    heal2 = _heals_json([("0:0", {"account": "国库"})])
    n = {"i": 0}
    prompts: list[str] = []

    def _llm(_a, prompt, tag="", prior_messages=None):
        n["i"] += 1
        if tag == "rescript-draft-heal":
            prompts.append(prompt)
        if n["i"] == 1:
            return first
        if n["i"] == 2:
            return heal1
        return heal2

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=35)
    assert drafts is not None
    assert len(prompts) >= 2
    assert "purpose" in prompts[0]
    # 第二轮仍可索 account（purpose 已部分进展）
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷" and grant["account"] == "国库"
    assert grant["amount"] == 200


# ---------------------------------------------------------------------------
# resolve_decisions_phase2：唯一 k/耗尽/多急务 + 会话 prior + 落库
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


def _freeze_option_fields(opt: dict) -> dict:
    """正常项逐字段冻结比对用（排除服务端 draft_capability）。"""
    return {k: v for k, v in opt.items() if k != "draft_capability"}


@pytest.mark.parametrize("succeed_on", [1, 2, 3, None])
def test_phase2_entry_heal_k_or_exhaust(succeed_on, game, monkeypatch, tmp_path):
    """唯一 k 参数化：真实调用输入序列、heals 落库、error pack typed、逐字段冻结。"""
    db, state, content, turn, decree_mod, simulation, _CANNED = _phase2_hitl_setup(
        game, monkeypatch, tmp_path,
    )
    bad = _army_pay(label="边饷拟", amount=150)
    bad.pop("purpose", None)
    sibling = _hold(
        label="缓边", hint="候核",
        transaction_category="督赈", region_id="shaanxi",
    )
    sibling_frozen = dict(sibling)
    first_items = [{
        "title": "关宁欠饷", "context": "边军待哺。",
        "options": [bad, sibling],
    }]
    first_raw = _items_json(first_items)
    # 补交：完整 option 带 heal_id；企图改 amount/sibling 不得落
    healed_opt = dict(bad, purpose="补饷", amount=999, heal_id="0:0")
    healed_raw = _items_json([{
        "title": "关宁欠饷", "context": "边军待哺。",
        "options": [
            healed_opt,
            dict(sibling, label="被改写", hint="坏", heal_id="0:1"),
        ],
    }])
    heal_n = {"i": 0}
    calls: list[dict] = []

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent
        if tag.startswith("extractor/") or tag.startswith("sanitizer/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            heal_n["i"] += 1
            prior = list(prior_messages or [])
            calls.append({
                "tag": tag,
                "prompt": prompt,
                "prior": prior,
                "roles": [
                    m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
                    for m in prior
                ],
                "contents": [
                    m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
                    for m in prior
                ],
            })
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
    assert calls[0]["prior"] == []
    # 完整 user/assistant 交替：第 k 次 heal prior 长度 = 2*k（含首抽与历次补交）
    for idx, c in enumerate(calls):
        if idx == 0:
            continue
        assert c["tag"] == "rescript-draft-heal"
        assert c["roles"] == ["user", "assistant"] * idx
        assert c["contents"][0]  # 首轮 user=payload
        assert c["contents"][1] == first_raw
        assert "heal_id" in c["prompt"]
        assert "purpose" in c["prompt"]
        # prior 末轮 assistant 为最近一次模型返回
        assert c["contents"][-1] in (first_raw, healed_raw) or c["roles"][-1] == "assistant"

    if succeed_on is None:
        assert len(opts) == 1
        hold = opts[0]
        assert _freeze_option_fields({
            k: hold[k] for k in sibling_frozen if k in hold
        }) == _freeze_option_fields(sibling_frozen)
        assert sum(1 for c in calls if c["tag"] == "rescript-draft-heal") == (
            RESCRIPT_OPTION_FIELD_HEAL_RETRIES
        )
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
    else:
        assert len(opts) == 2
        grant = next(o for o in opts if o.get("grant_action") == "协饷")
        assert grant["purpose"] == "补饷"
        assert grant["amount"] == bad["amount"]  # 999 不落
        assert grant["label"] == bad["label"]
        assert grant["account"] == bad["account"]
        assert grant["target_id"] == bad["target_id"]
        hold = next(o for o in opts if o.get("action_type") == "assignment")
        # 正常项逐字段冻结（补交不得改写兄弟）
        for k, v in sibling_frozen.items():
            assert hold.get(k) == v, f"sibling field {k} mutated"
        assert heal_n["i"] == 1 + succeed_on
        assert any(c["tag"] == "rescript-draft-heal" for c in calls)


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
            calls.append({
                "tag": tag,
                "prior_roles": [
                    m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
                    for m in (prior_messages or [])
                ],
                "prompt": prompt,
            })
            return first if n["i"] == 1 else after
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
    # u3 正常项逐字段冻结
    assert len(rows[u3["title"]]["options"]) == 2
    got_u3 = {o["label"]: o for o in rows[u3["title"]]["options"]}
    for src in (u3_a, u3_b):
        got = got_u3[src["label"]]
        for k, v in src.items():
            assert got.get(k) == v
    assert calls[0]["tag"] == "rescript-draft" and calls[0]["prior_roles"] == []
    assert any(c["tag"] == "rescript-draft-heal" for c in calls)
