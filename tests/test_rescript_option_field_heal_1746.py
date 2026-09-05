"""#1746：票拟 option 缺结构化字段 → 同一会话补交（≤3）→ 耗尽单 option 剔除。

真实入口：resolve_decisions_phase2 / _settle_after_narrative（web 亲裁续跑同源 phase2）。
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


def _one_urgent_missing_purpose(*, good_n: int = 0) -> list:
    bad = _army_pay()
    bad.pop("purpose", None)
    opts = [bad]
    for i in range(good_n):
        opts.append(_hold(label=f"正常拟{i}", hint=f"h{i}"))
    if len(opts) < 2:
        opts.append(_hold())
    return [{
        "title": "关宁欠饷",
        "context": "边军待哺，急须补饷。",
        "options": opts,
    }]


def _stamp_heal_ids(items: list) -> list:
    """补交响应回指请求显式结构身份（heal_id=item_index:option_index）。"""
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
                and opt.get("grant_kind") == "army_pay"
                and not str(opt.get("purpose") or "").strip()
            ):
                opt["purpose"] = "补饷"
    return items


def _heals_json(pairs: list[tuple[str, dict]]) -> str:
    return json.dumps(
        {"heals": [{"heal_id": hid, **fields} for hid, fields in pairs]},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 参数化闭环：补交第 1/2/3 次成功；耗尽剔除；会话 prior_messages 续接
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("succeed_on", [1, 2, 3])
def test_missing_purpose_heals_on_kth_resume(succeed_on, monkeypatch, tmp_path):
    """缺 purpose → 同一会话补交；第 k 次补上；prior 含首抽输入/输出。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    assert RESCRIPT_OPTION_FIELD_HEAL_RETRIES == 3

    first_items = _one_urgent_missing_purpose(good_n=1)
    first_raw = _items_json(first_items)
    healed_raw = _items_json(_healed_items_from(first_items))
    calls: list[dict] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        calls.append({
            "prompt": prompt,
            "tag": tag,
            "prior": list(prior_messages or []),
        })
        if len(calls) == 1:
            return first_raw
        heal_idx = len(calls) - 1
        if heal_idx < succeed_on:
            return first_raw
        return healed_raw

    sibling_in = next(
        o for o in first_items[0]["options"] if o.get("action_type") == "assignment"
    )
    bad_in = next(
        o for o in first_items[0]["options"]
        if o.get("action_type") == "grant_allocation"
    )
    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=11)
    assert drafts is not None
    assert len(drafts) == 1
    opts = drafts[0]["options"]
    assert len(opts) == 2
    grants = [o for o in opts if o.get("grant_action") == "协饷"]
    assert len(grants) == 1
    assert grants[0]["purpose"] == "补饷"
    assert grants[0]["amount"] == bad_in["amount"]
    assert grants[0]["account"] == bad_in["account"]
    assert grants[0]["target_id"] == bad_in["target_id"]
    normals = [o for o in opts if o.get("action_type") == "assignment"]
    assert len(normals) == 1
    for key in (
        "label", "hint", "action_type", "target_kind", "target_id",
        "locality_scope", "region_id", "assignee_name", "transaction_category",
    ):
        assert normals[0].get(key) == sibling_in.get(key)
    assert len(calls) == 1 + succeed_on
    assert calls[0]["tag"] == "rescript-draft"
    assert calls[0]["prior"] == []
    for c in calls[1:]:
        assert c["tag"] == "rescript-draft-heal"
        # 真实会话：prior 含首抽 user+assistant，不是拼 original_raw 冒充
        assert len(c["prior"]) >= 2
        assert c["prior"][0]["role"] == "user"
        assert c["prior"][1]["role"] == "assistant"
        assert c["prior"][1]["content"] == first_raw
        assert "heal_id" in c["prompt"]
        assert "purpose" in c["prompt"]
        # 补交请求不再把整份 original_raw 粘进 user 正文
        assert first_raw not in c["prompt"]


def test_heal_exhausted_drops_only_bad_option(monkeypatch, tmp_path):
    """3 次仍缺 → 只剔该 option；error pack 单份 dropped_options（含 heal_attempts）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first_items = _one_urgent_missing_purpose(good_n=1)
    first_raw = _items_json(first_items)

    def _llm(_agent, prompt, tag="", prior_messages=None):
        del prompt, prior_messages
        return first_raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=12)
    sibling_in = next(
        o for o in first_items[0]["options"] if o.get("action_type") == "assignment"
    )
    assert drafts is not None
    assert len(drafts) == 1
    opts = drafts[0]["options"]
    assert len(opts) == 1
    assert opts[0]["action_type"] == "assignment"
    assert opts[0]["label"] == sibling_in["label"]
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn12.json"
    assert note.is_file()
    note_obj = json.loads(note.read_text(encoding="utf-8"))
    assert note_obj.get("reason") == "option_missing_fields_heal_exhausted"
    dropped = note_obj.get("dropped_options") or []
    assert any("purpose" in (d.get("missing_fields") or []) for d in dropped)
    assert all("heal_attempts" in d for d in dropped)
    # H2：不再平行 missing_fields_detail 副本
    assert "missing_fields_detail" not in note_obj
    trace = note_obj.get("heal_trace") or []
    assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    assert all(str(t.get("raw_summary") or "").strip() for t in trace)


def test_all_options_dropped_removes_item_other_urgents_remain(monkeypatch, tmp_path):
    """单急务 options 全剔 → 该条目消失；其它急务照常。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad_a = _army_pay(label="辽东补饷")
    bad_a.pop("purpose", None)
    bad_b = _army_pay(label="关宁急饷", target_id="guanning")
    bad_b.pop("purpose", None)
    all_bad = {
        "title": "辽东索饷",
        "context": "两镇告匮。",
        "options": [bad_a, bad_b],
    }
    good = {
        "title": "陕西告饥",
        "context": "秦地赤旱。",
        "options": [_hold(label="发帑赈济"), _hold(label="缓征加赈", hint="先赈")],
    }
    raw = _items_json([all_bad, good])
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: raw,
    )
    drafts = generate_rescript_draft(object(), _ctx(), turn=14)
    assert drafts is not None
    titles = [d["title"] for d in drafts]
    assert all_bad["title"] not in titles
    assert good["title"] in titles
    assert len(drafts) == 1
    assert len(drafts[0]["options"]) == 2


def test_multi_urgent_multi_bad_options_isolated(monkeypatch, tmp_path):
    """多急务 × 多坏 option：结构身份回指，坏项只影响自己。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad1 = _army_pay(label="关宁补饷")
    bad1.pop("purpose", None)
    good1 = _hold(label="关宁缓议", hint="候边报")
    u1 = {"title": "关宁急饷", "context": "关宁待哺。", "options": [bad1, good1]}

    bad2 = _army_pay(label="宣大续饷", target_id="xuanfu", amount=120)
    bad2.pop("purpose", None)
    good2a = _hold(label="宣大查核", hint="核册")
    good2b = _hold(label="宣大缓派", hint="苏民")
    u2 = {
        "title": "宣大欠饷",
        "context": "宣大告急。",
        "options": [good2a, bad2, good2b],
    }

    first = _items_json([u1, u2])
    fixed_u1 = deepcopy(u1)
    fixed_u1["options"][0]["purpose"] = "补饷"
    after_heal = _items_json(_stamp_heal_ids([fixed_u1, u2]))

    calls: list[int] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        del prompt, prior_messages
        calls.append(1)
        if len(calls) == 1:
            return first
        return after_heal

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=15)
    assert drafts is not None
    by_title = {d["title"]: d for d in drafts}
    assert set(by_title) == {u1["title"], u2["title"]}
    g1 = by_title[u1["title"]]["options"]
    assert len(g1) == 2
    grant = next(o for o in g1 if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷"
    g2 = by_title[u2["title"]]["options"]
    assert len(g2) == 2
    assert all(o.get("grant_action") != "协饷" for o in g2)
    assert {o["label"] for o in g2} == {good2a["label"], good2b["label"]}


def test_combo_then_field_heal_uses_corrected_baseline(monkeypatch, tmp_path):
    """组合重抽后补交用对应底稿（单一 working_data），会话保留组合轮。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    combo_bad = _army_pay(label="combo", locality_scope="single")
    field_bad = _army_pay(label="field", target_id="guanning", amount=200)
    field_bad.pop("purpose", None)
    combo_fixed = dict(combo_bad, locality_scope="none")
    field_fixed = dict(field_bad, purpose="补饷")
    combo_poison = dict(combo_fixed, locality_scope="single")

    first = _items_json([{
        "title": "辽东欠饷", "context": "九边告匮。",
        "options": [combo_bad, field_bad],
    }])
    after_combo = _items_json([{
        "title": "辽东欠饷", "context": "九边告匮。",
        "options": [combo_fixed, field_bad],
    }])
    after_heal_items = _stamp_heal_ids([{
        "title": "辽东欠饷", "context": "九边告匮。",
        "options": [combo_poison, field_fixed],
    }])
    after_heal = _items_json(after_heal_items)
    calls: list[dict] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        calls.append({
            "tag": tag,
            "prompt": prompt,
            "prior_len": len(prior_messages or []),
        })
        if len(calls) == 1:
            return first
        if tag == "rescript-draft":
            return after_combo
        return after_heal

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=30)
    assert drafts is not None, f"calls={calls}"
    opts = drafts[0]["options"]
    assert len(opts) == 2
    by_label = {o["label"]: o for o in opts}
    assert by_label[combo_fixed["label"]]["locality_scope"] == combo_fixed["locality_scope"]
    assert by_label[field_fixed["label"]]["purpose"] == "补饷"
    assert by_label[field_fixed["label"]]["amount"] == field_bad["amount"]
    heal_calls = [c for c in calls if c["tag"] == "rescript-draft-heal"]
    assert heal_calls and heal_calls[0]["prior_len"] >= 4  # 首抽+组合 各 user/assistant


def test_action_conditional_missing_heals_not_whole_batch(monkeypatch, tmp_path):
    """military_order 缺 assignee_name → 补交；不限协饷 purpose。"""
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
    mo_good = dict(mo_bad, assignee_name="袁崇焕")
    sibling = _hold(label="缓议", hint="候报")
    first = _items_json([{
        "title": "关宁请援", "context": "奴贼压境。",
        "options": [mo_bad, sibling],
    }])
    healed = _heals_json([("0:0", {"assignee_name": mo_good["assignee_name"]})])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=31)
    assert drafts is not None
    assert n["i"] == 2
    opts = drafts[0]["options"]
    assert len(opts) == 2
    mo = next(o for o in opts if o["action_type"] == "military_order")
    assert mo["assignee_name"] == mo_good["assignee_name"]
    sib = next(o for o in opts if o.get("action_type") == "assignment")
    assert sib["label"] == sibling["label"] and sib["hint"] == sibling["hint"]


def test_heal_accepts_grant_kind_when_first_draw_omitted_kind(monkeypatch, tmp_path):
    """双缺 grant_kind → 索取辨别字段；补交 grant_kind=army_pay 可采纳。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay-kind")
    bad.pop("grant_kind", None)
    bad["purpose"] = "补饷"
    sibling = _hold(label="sib", hint="k")
    first = _items_json([{
        "title": "u", "context": "c", "options": [bad, sibling],
    }])
    healed = _heals_json([("0:0", {"grant_kind": "army_pay"})])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=36)
    assert drafts is not None
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷"
    assert grant["amount"] == bad["amount"]


def test_heal_partial_progress_keeps_filled_missing_fields(monkeypatch, tmp_path):
    """多缺字段分次回填：先 purpose 后 account，保留进度。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay-partial", amount=300, account="")
    bad.pop("purpose", None)
    sibling = _hold(label="sib", hint="p")
    first = _items_json([{
        "title": "u", "context": "c", "options": [bad, sibling],
    }])
    seq = [
        first,
        _heals_json([("0:0", {"purpose": "补饷"})]),
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
    assert grant["amount"] == 300
    assert n["i"] == 3


def test_heal_only_fills_missing_fields_preserves_world_facts(monkeypatch, tmp_path):
    """补交只回填缺字段；世界事实冻结；完整 option 重交亦可消费（heal_id 回指）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(
        label="pay", amount=300, account="国库", target_id="guanning",
    )
    bad.pop("purpose", None)
    sibling = _hold(label="sib", hint="keep")
    first = _items_json([{
        "title": "u", "context": "c", "options": [bad, sibling],
    }])
    mutated = dict(
        bad,
        purpose="补饷",
        amount=999,
        account="内库",
        target_id="xuanfu",
        heal_id="0:0",
    )
    healed = _items_json([{
        "title": "u", "context": "c",
        "options": [mutated, dict(sibling, heal_id="0:1", label="CHANGED")],
    }])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=35)
    assert drafts is not None
    grant = next(o for o in drafts[0]["options"] if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷"
    assert grant["amount"] == bad["amount"]
    assert grant["account"] == bad["account"]
    assert grant["target_id"] == bad["target_id"]
    assert "heal_id" not in grant
    sib = next(o for o in drafts[0]["options"] if o.get("action_type") == "assignment")
    assert sib["label"] == sibling["label"] and sib["hint"] == sibling["hint"]


def test_heal_freezes_sibling_options_from_first_draw(monkeypatch, tmp_path):
    """兄弟 option 冻结首抽；补交 heals 只动缺项。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay")
    bad.pop("purpose", None)
    sibling = _hold(label="stable", hint="keep")
    first = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, sibling],
    }])
    healed = _heals_json([("0:0", {"purpose": "补饷"})])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=21)
    assert drafts is not None
    opts = drafts[0]["options"]
    assert len(opts) == 2
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷" and grant["label"] == bad["label"]
    sib = next(o for o in opts if o.get("action_type") == "assignment")
    assert sib["label"] == sibling["label"] and sib["hint"] == sibling["hint"]


def test_heal_matches_by_explicit_heal_id_not_prose(monkeypatch, tmp_path):
    """同题同名亦可：只认 heal_id 回指，不靠 title/label 猜配。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    shared = "同名协饷"
    bad = _army_pay(label=shared, target_id="guanning", amount=100)
    bad.pop("purpose", None)
    sib1 = _hold(label="缓一", hint="a")
    u1 = {"title": "同题急务", "context": "甲。", "options": [bad, sib1]}
    other = _army_pay(label=shared, target_id="xuanfu", amount=200)
    sib2 = _hold(label="缓二", hint="b")
    u2 = {"title": "同题急务", "context": "乙。", "options": [other, sib2]}
    first = _items_json([u1, u2])
    # 只修 u1 的 0:0；u2 原样（无缺字段）
    healed = _heals_json([
        ("0:0", {"purpose": "补饷"}),
    ])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=34)
    assert drafts is not None
    by_ctx = {d["context"]: d for d in drafts}
    u1_opts = by_ctx[u1["context"]]["options"]
    assert len(u1_opts) == 2
    g1 = next(o for o in u1_opts if o.get("grant_action") == "协饷")
    assert g1["purpose"] == "补饷" and g1["target_id"] == "guanning"
    u2_grants = [
        o for o in by_ctx[u2["context"]]["options"] if o.get("grant_action") == "协饷"
    ]
    assert len(u2_grants) == 1 and u2_grants[0]["target_id"] == "xuanfu"


def test_heal_without_heal_id_refuses_merge_then_drops(monkeypatch, tmp_path):
    """补交未回指结构身份 → 不按位次/措辞猜配，耗尽剔坏项。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay")
    bad.pop("purpose", None)
    sibling = _hold(label="stable", hint="keep")
    first = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, sibling],
    }])
    # 故意不带 heal_id
    healed = _items_json([{
        "title": "u", "context": "c",
        "options": [dict(bad, purpose="补饷"), sibling],
    }])
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


def test_heal_does_not_mark_approved(monkeypatch, tmp_path):
    """补齐进入头版 ≠ 已准旨。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    items = _one_urgent_missing_purpose(good_n=1)
    first = _items_json(items)
    healed = _items_json(_healed_items_from(items))
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=16)
    assert drafts is not None
    for d in drafts:
        assert "status" not in d
        assert "choice" not in d and "choice_json" not in d
        for o in d["options"]:
            assert "approved" not in o
            assert "verdict" not in o


def test_emperor_channel_gains_no_heal_fields(monkeypatch, tmp_path):
    """皇帝侧零新增提示通道：draft 结构无补交/剔除技术键。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    items = _one_urgent_missing_purpose(good_n=1)
    raw = _items_json(items)
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    drafts = generate_rescript_draft(object(), _ctx(), turn=17)
    assert drafts is not None
    banned = {
        "heal", "healed", "dropped", "missing_fields", "补交", "剔除",
        "heal_attempts", "option_drop", "field_heal", "heal_id",
    }
    for d in drafts:
        assert not (banned & set(d))
        for o in d["options"]:
            assert not (banned & set(o))


def test_combo_correction_still_distinct_from_field_heal(monkeypatch, tmp_path):
    """组合错误整批重抽 ≠ 缺字段补交。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad_combo = {
        "title": "辽东欠饷",
        "context": "九边欠饷。",
        "options": [
            _army_pay(locality_scope="single"),
            _hold(),
        ],
    }
    good_combo = deepcopy(bad_combo)
    good_combo["options"][0]["locality_scope"] = "none"
    calls: list[dict] = []

    def _llm(_agent, prompt, tag="", prior_messages=None):
        del prior_messages
        calls.append({"tag": tag, "prompt": prompt})
        if len(calls) == 1:
            return _items_json([bad_combo])
        return _items_json([good_combo])

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=18)
    assert drafts is not None
    assert len(calls) == 2
    assert all(c["tag"] == "rescript-draft" for c in calls)
    assert calls[1]["prompt"] != calls[0]["prompt"]
    assert drafts[0]["options"][0]["locality_scope"] == "none"


def test_provider_failure_still_whole_batch_none(monkeypatch, tmp_path):
    """调用失败分流不动。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    def _boom(*_a, **_k):
        raise LLMUnavailable("provider down")

    monkeypatch.setattr(rescript_mod, "run_agent_text", _boom)
    assert generate_rescript_draft(object(), _ctx(), turn=19) is None


def test_item_level_missing_still_whole_batch_degrade(monkeypatch, tmp_path):
    """F2.5 其它分支：急务条目缺 context → 整批无头版。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    raw = _items_json([{
        "title": "辽饷告匮",
        "options": [_hold(), _army_pay()],
    }])
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    assert generate_rescript_draft(object(), _ctx(), turn=20) is None


def test_illegal_amount_does_not_enter_missing_heal(monkeypatch, tmp_path):
    """非正/非法 amount 不得冒称缺失进补交；整批 F2.5。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(amount=-5)
    raw = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, _hold()],
    }])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=40) is None
    assert len(calls) == 1  # 无补交轮


def test_illegal_purpose_value_does_not_enter_missing_heal(monkeypatch, tmp_path):
    """非空非法 purpose 不得进缺字段补交。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(purpose="赈灾")
    raw = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, _hold()],
    }])
    calls: list[str] = []

    def _llm(*_a, **_k):
        calls.append("x")
        return raw

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    assert generate_rescript_draft(object(), _ctx(), turn=41) is None
    assert len(calls) == 1


def test_required_wrong_type_not_missing_heal():
    """层 A required 错误类型 → ValueError，不进 Missing。"""
    bad = _hold(label=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="须为 str"):
        normalize_rescript_layer_a_option(bad, generation_admission=True)


# ---------------------------------------------------------------------------
# 真实入口：phase2 / 结算落库 + 玩家通道结构
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("succeed_on", [1, 2, 3, None])
def test_phase2_entry_heal_k_or_exhaust(succeed_on, game, monkeypatch, tmp_path):
    """resolve_decisions_phase2 / settle 同源入口：k 成功或耗尽；会话 prior；pending 落库。"""
    import ming_sim.decree as decree_mod
    import ming_sim.simulation as simulation
    from ming_sim.decree import _settle_after_narrative
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

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent
        if tag.startswith("extractor/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            heal_n["i"] += 1
            priors.append(len(prior_messages or []))
            if tag == "rescript-draft-heal":
                assert "heal_id" in prompt
                assert first_raw not in prompt
                assert len(prior_messages or []) >= 2
                assert (prior_messages or [])[1].get("content") == first_raw
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

    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={
            "active_issues": [],
            "regions": {"cols": ["id", "name", "kind"],
                        "rows": [["shaanxi", "陕西", "布政司"]]},
            "armies": {
                "cols": ["id", "name", "station", "owner_power"],
                "rows": [["guanning", "关宁", "宁远", "ming"]],
            },
            "transit_semantics": [],
        },
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )

    rows = db.list_rescript_drafts()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    opts = rows[0]["options"]
    banned = {"heal", "healed", "dropped", "missing_fields", "heal_id", "heal_attempts"}
    assert not (banned & set(rows[0]))
    for o in opts:
        assert not (banned & set(o))
    if succeed_on is None:
        assert len(opts) == 1
        assert opts[0]["label"] == sibling["label"]
        note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
        assert note.is_file()
        trace = json.loads(note.read_text(encoding="utf-8")).get("heal_trace") or []
        assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    else:
        assert len(opts) == 2
        grant = next(o for o in opts if o.get("grant_action") == "协饷")
        assert grant["purpose"] == "补饷" and grant["amount"] == bad["amount"]
        assert heal_n["i"] == 1 + succeed_on
        assert priors[0] == 0
        assert all(p >= 2 for p in priors[1:])


def test_settle_multi_urgent_isolation_persists(game, monkeypatch, tmp_path):
    """结算入口：多急务多坏项隔离落库。"""
    import ming_sim.decree as decree_mod
    import ming_sim.simulation as simulation
    from ming_sim.decree import _settle_after_narrative
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

    bad1 = _army_pay(label="关宁补饷")
    bad1.pop("purpose", None)
    good1 = _hold(label="关宁缓议", hint="候边报")
    u1 = {"title": "关宁急饷", "context": "关宁待哺。", "options": [bad1, good1]}
    bad2 = _army_pay(label="宣大续饷", target_id="xuanfu", amount=120)
    bad2.pop("purpose", None)
    good2a = _hold(label="宣大查核", hint="核册")
    good2b = _hold(label="宣大缓派", hint="苏民")
    u2 = {"title": "宣大欠饷", "context": "宣大告急。", "options": [good2a, bad2, good2b]}
    first = _items_json([u1, u2])
    fixed_u1 = deepcopy(u1)
    fixed_u1["options"][0]["purpose"] = "补饷"
    after = _items_json(_stamp_heal_ids([fixed_u1, u2]))
    n = {"i": 0}

    def _fake_run(agent, prompt, tag="", prior_messages=None):
        del agent, prompt, prior_messages
        if tag.startswith("extractor/"):
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
    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={
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
        },
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )
    rows = {r["title"]: r for r in db.list_rescript_drafts()}
    assert set(rows) == {u1["title"], u2["title"]}
    assert rows[u1["title"]]["status"] == "pending"
    g1 = rows[u1["title"]]["options"]
    assert any(o.get("grant_action") == "协饷" and o.get("purpose") == "补饷" for o in g1)
    g2 = rows[u2["title"]]["options"]
    assert len(g2) == 2
    assert all(o.get("grant_action") != "协饷" for o in g2)
