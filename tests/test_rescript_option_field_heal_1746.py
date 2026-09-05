"""#1746：票拟 option 缺结构化字段 → 同一会话补交（≤3）→ 耗尽单 option 剔除。

真实入口：generate_rescript_draft（月末 phase2 票拟 LLM 返回边界）。
decision keys：missing-field-heal-by-resume-not-drop / per-option-drop-after-heal-exhausted。
显式修订 #656 F2.5（单 option 缺字段）与 F2.2（剔后剩 1 仍呈）。
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
    """1 急务：1 协饷缺 purpose + good_n 道正常 assignment（另加 1 hold 凑 2–3）。"""
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


def _healed_items_from(first_items: list) -> list:
    items = deepcopy(first_items)
    for it in items:
        for opt in it["options"]:
            if (
                opt.get("action_type") == "grant_allocation"
                and opt.get("grant_kind") == "army_pay"
                and not str(opt.get("purpose") or "").strip()
            ):
                opt["purpose"] = "补饷"
    return items


# ---------------------------------------------------------------------------
# 参数化闭环：补交第 1/2/3 次成功；耗尽剔除
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("succeed_on", [1, 2, 3])
def test_missing_purpose_heals_on_kth_resume(succeed_on, monkeypatch, tmp_path):
    """缺 purpose → 同一会话补交；第 k 次（k≤3）补上 → 全批进入头版。

    替身观察：补交 prompt 附原始产出、焦点为缺字段；经真实补交回路（非旁路）。
    """
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    assert RESCRIPT_OPTION_FIELD_HEAL_RETRIES == 3

    first_items = _one_urgent_missing_purpose(good_n=1)
    first_raw = _items_json(first_items)
    healed_raw = _items_json(_healed_items_from(first_items))
    calls: list[dict] = []

    def _llm(_agent, prompt, tag=""):
        calls.append({"prompt": prompt, "tag": tag})
        if len(calls) == 1:
            return first_raw
        # 补交轮：前 succeed_on-1 次仍缺，第 succeed_on 次补上
        heal_idx = len(calls) - 1  # 1-based heal attempt
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
    # 结构化字段相对首抽输入：金额/账户/目标不改写
    assert grants[0]["amount"] == bad_in["amount"]
    assert grants[0]["account"] == bad_in["account"]
    assert grants[0]["target_id"] == bad_in["target_id"]
    # 正常 option 逐字段相对输入无改写（期望来自捕获的输入）
    normals = [o for o in opts if o.get("action_type") == "assignment"]
    assert len(normals) == 1
    for key in (
        "label", "hint", "action_type", "target_kind", "target_id",
        "locality_scope", "region_id", "assignee_name", "transaction_category",
    ):
        assert normals[0].get(key) == sibling_in.get(key)
    # 经真实补交：首抽 + succeed_on 次补交；tag 分流（非组合重抽 tag）
    assert len(calls) == 1 + succeed_on
    assert calls[0]["tag"] == "rescript-draft"
    for c in calls[1:]:
        assert c["tag"] == "rescript-draft-heal"
        assert first_raw in c["prompt"]
        assert "purpose" in c["prompt"]


def test_heal_exhausted_drops_only_bad_option(monkeypatch, tmp_path):
    """3 次仍缺 → 只剔该 option；同急务其余 option 仍呈；结算入口返回非 None。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    first_items = _one_urgent_missing_purpose(good_n=1)
    first_raw = _items_json(first_items)
    calls: list[str] = []

    def _llm(_agent, prompt, tag=""):
        calls.append(tag)
        return first_raw  # 永不补上

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=12)
    sibling_in = next(
        o for o in first_items[0]["options"] if o.get("action_type") == "assignment"
    )
    assert drafts is not None
    assert len(drafts) == 1
    opts = drafts[0]["options"]
    # F2.2：剔后剩 1 仍呈；且为捕获的兄弟项
    assert len(opts) == 1
    assert opts[0]["action_type"] == "assignment"
    assert opts[0]["label"] == sibling_in["label"]
    assert opts[0]["hint"] == sibling_in["hint"]
    assert len(calls) == 1 + RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn12.json"
    assert note.is_file()
    note_obj = json.loads(note.read_text(encoding="utf-8"))
    assert note_obj.get("reason") == "option_missing_fields_heal_exhausted"
    dropped = note_obj.get("dropped_options") or []
    assert any("purpose" in (d.get("missing_fields") or []) for d in dropped)
    # 三次补交各自产出摘要落 error pack
    trace = note_obj.get("heal_trace") or []
    assert len(trace) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    assert all(str(t.get("raw_summary") or "").strip() for t in trace)
    assert all(t.get("attempt") == i for i, t in enumerate(trace, start=1))


def test_all_options_dropped_removes_item_other_urgents_remain(monkeypatch, tmp_path):
    """单急务 options 全剔 → 该条目不足照实消失；其它急务照常。"""
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
        rescript_mod, "run_agent_text", lambda *_a, **_k: raw,
    )
    drafts = generate_rescript_draft(object(), _ctx(), turn=14)
    assert drafts is not None
    titles = [d["title"] for d in drafts]
    assert all_bad["title"] not in titles
    assert good["title"] in titles
    assert len(drafts) == 1
    assert len(drafts[0]["options"]) == 2
    assert [o["label"] for o in drafts[0]["options"]] == [
        o["label"] for o in good["options"]
    ]


def test_multi_urgent_multi_bad_options_isolated(monkeypatch, tmp_path):
    """多急务 × 多坏 option 互不牵连：坏项只影响自己，好项字段原样。"""
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
    # 第 1 次补交只修好 u1；u2 bad 耗尽剔除
    fixed_u1 = deepcopy(u1)
    fixed_u1["options"][0]["purpose"] = "补饷"
    # 补交仍带 u2 bad
    after_heal = _items_json([fixed_u1, u2])

    calls: list[int] = []

    def _llm(_agent, prompt, tag=""):
        calls.append(1)
        if len(calls) == 1:
            return first
        # 所有补交轮返回 u1 已修、u2 仍缺
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
    assert grant["label"] == bad1["label"]
    sib1 = next(o for o in g1 if o.get("action_type") == "assignment")
    assert sib1["label"] == good1["label"] and sib1["hint"] == good1["hint"]
    g2 = by_title[u2["title"]]["options"]
    assert len(g2) == 2
    assert all(o.get("grant_action") != "协饷" for o in g2)
    assert {o["label"] for o in g2} == {good2a["label"], good2b["label"]}


def test_combo_then_field_heal_uses_corrected_baseline(monkeypatch, tmp_path):
    """首抽组合错 → 重抽修好组合项 → 另一项缺字段补交：底稿须为组合重抽后版本。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    # option0: army+single 组合非法；option1: 协饷缺 purpose
    combo_bad = _army_pay(label="combo", locality_scope="single")
    field_bad = _army_pay(label="field", target_id="guanning", amount=200)
    field_bad.pop("purpose", None)
    # 组合重抽：combo 修好为 none，field 仍缺 purpose
    combo_fixed = dict(combo_bad, locality_scope="none")
    # 补交：field 补 purpose；故意把 combo 改回 single（若误用首抽底稿会整批挂）
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
    after_heal = _items_json([{
        "title": "辽东欠饷", "context": "九边告匮。",
        "options": [combo_poison, field_fixed],  # poison 不得写回
    }])
    calls: list[str] = []

    def _llm(_agent, prompt, tag=""):
        calls.append(tag)
        if len(calls) == 1:
            return first
        if "结构组合校验失败" in prompt:
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


def test_action_conditional_missing_heals_not_whole_batch(monkeypatch, tmp_path):
    """military_order 缺 assignee_name → 进补交分支，不整批无头版。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    mo_bad = {
        "label": "调关宁赴援",
        "hint": "边情急",
        "action_type": "military_order",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "assignee_name": "",  # 缺必填
        "transaction_category": "",
        "station": "宁远",
    }
    mo_good = dict(mo_bad, assignee_name="袁崇焕")
    sibling = _hold(label="缓议", hint="候报")
    first = _items_json([{
        "title": "关宁请援", "context": "奴贼压境。",
        "options": [mo_bad, sibling],
    }])
    healed = _items_json([{
        "title": "关宁请援", "context": "奴贼压境。",
        "options": [mo_good, _hold(label="CHANGED", hint="x")],
    }])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=31)
    assert drafts is not None
    assert n["i"] == 2  # 首抽 + 1 次补交
    opts = drafts[0]["options"]
    assert len(opts) == 2
    mo = next(o for o in opts if o["action_type"] == "military_order")
    assert mo["assignee_name"] == mo_good["assignee_name"]
    sib = next(o for o in opts if o.get("action_type") == "assignment")
    assert sib["label"] == sibling["label"] and sib["hint"] == sibling["hint"]


def test_heal_only_fills_missing_fields_preserves_world_facts(monkeypatch, tmp_path):
    """补交只回填缺字段；amount/account/target 等首抽世界事实不得被改写。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(
        label="pay", amount=300, account="国库", target_id="guanning",
    )
    bad.pop("purpose", None)
    sibling = _hold(label="sib", hint="keep")
    first = _items_json([{
        "title": "u", "context": "c", "options": [bad, sibling],
    }])
    # 补交同身份但篡改世界事实字段
    mutated = dict(
        bad,
        purpose="补饷",
        amount=999,
        account="内库",
        target_id="xuanfu",
    )
    healed = _items_json([{
        "title": "u", "context": "c",
        "options": [mutated, _hold(label="CHANGED", hint="x")],
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
    sib = next(o for o in drafts[0]["options"] if o.get("action_type") == "assignment")
    assert sib["label"] == sibling["label"] and sib["hint"] == sibling["hint"]


def test_heal_freezes_sibling_options_from_first_draw(monkeypatch, tmp_path):
    """补交只采纳缺字段 option；兄弟 option 冻结首抽原文（LLM 改写无效）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay")
    bad.pop("purpose", None)
    sibling = _hold(label="stable", hint="keep")
    first = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, sibling],
    }])
    healed_bad = dict(bad, purpose="补饷")
    changed_sibling = _hold(label="CHANGED", hint="CHANGED")
    healed = _items_json([{
        "title": "u", "context": "c",
        "options": [healed_bad, changed_sibling],
    }])
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


def test_heal_reorder_matches_by_label_not_index(monkeypatch, tmp_path):
    """补交重排 options：按 label 身份合并，不得把兄弟顶到缺字段槽。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad = _army_pay(label="pay-grant")
    bad.pop("purpose", None)
    sibling = _hold(label="sib-hold", hint="keep-me")
    first = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, sibling],  # index0=bad
    }])
    # 重排：兄弟在前、修好的 grant 在后；若按 index 盲取会吞掉 grant
    healed = _items_json([{
        "title": "u", "context": "c",
        "options": [
            _hold(label="sib-hold", hint="CHANGED"),
            dict(bad, purpose="补饷", amount=bad["amount"]),
        ],
    }])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=23)
    assert drafts is not None
    opts = drafts[0]["options"]
    assert len(opts) == 2
    grants = [o for o in opts if o.get("grant_action") == "协饷"]
    asserts_sib = [o for o in opts if o.get("action_type") == "assignment"]
    assert len(grants) == 1 and grants[0]["purpose"] == "补饷"
    assert grants[0]["label"] == bad["label"]
    assert len(asserts_sib) == 1
    assert asserts_sib[0]["label"] == sibling["label"]
    assert asserts_sib[0]["hint"] == sibling["hint"]  # 冻结首抽，非 CHANGED


def test_heal_tlog_includes_raw_summary_each_attempt(monkeypatch, tmp_path):
    """后台响亮：每次补交 tlog 含 raw_summary + option 身份/缺字段。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    items = _one_urgent_missing_purpose(good_n=1)
    raw = _items_json(items)
    logs: list[str] = []
    monkeypatch.setattr(rescript_mod, "tlog", logs.append)
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    drafts = generate_rescript_draft(object(), _ctx(), turn=22)
    assert drafts is not None  # 耗尽剔除后仍有 sibling
    produce_logs = [line for line in logs if "补交产出" in line and "raw_summary" in line]
    assert len(produce_logs) == RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    assert any("purpose" in line and "缺字段" in line for line in logs)


def test_heal_does_not_mark_approved(monkeypatch, tmp_path):
    """补齐进入头版 ≠ 已准旨：生成结果仍是候选 option，无已准/choice 痕迹。"""
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
        # 生成层不写 status/choice；落库前为纯候选
        assert "status" not in d
        assert "choice" not in d and "choice_json" not in d
        for o in d["options"]:
            assert "approved" not in o
            assert "verdict" not in o


def test_emperor_channel_gains_no_heal_fields(monkeypatch, tmp_path):
    """皇帝侧零新增提示：产出 draft 不新增补交/剔除技术字段（不以措辞扫描证明）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    items = _one_urgent_missing_purpose(good_n=1)
    raw = _items_json(items)
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    drafts = generate_rescript_draft(object(), _ctx(), turn=17)
    assert drafts is not None
    banned = {
        "heal", "healed", "dropped", "missing_fields", "补交", "剔除",
        "heal_attempts", "option_drop", "field_heal",
    }
    blob = json.dumps(drafts, ensure_ascii=False)
    for key in banned:
        # 技术通道键不得作为 draft 结构字段出现；自由文本 label 不含这些键名即可
        for d in drafts:
            assert key not in d
            for o in d["options"]:
                assert key not in o
    del blob  # 不用措辞扫描正文


def test_combo_correction_still_distinct_from_field_heal(monkeypatch, tmp_path):
    """组合错误整批重抽与缺字段补交是两种动作：army+single 仍走组合有界重抽。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    bad_combo = {
        "title": "辽东欠饷",
        "context": "九边欠饷。",
        "options": [
            _army_pay(locality_scope="single"),  # 组合非法
            _hold(),
        ],
    }
    good_combo = deepcopy(bad_combo)
    good_combo["options"][0]["locality_scope"] = "none"
    calls: list[dict] = []

    def _llm(_agent, prompt, tag=""):
        calls.append({"tag": tag, "prompt": prompt})
        if len(calls) == 1:
            return _items_json([bad_combo])
        return _items_json([good_combo])

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=18)
    assert drafts is not None
    assert len(calls) == 2
    # 组合重抽：两次均 rescript-draft tag（非 heal）；第二次 prompt 含纠错前缀形态
    assert all(c["tag"] == "rescript-draft" for c in calls)
    assert calls[1]["prompt"] != calls[0]["prompt"]
    assert calls[1]["prompt"].endswith(calls[0]["prompt"]) or calls[0]["prompt"] in calls[1]["prompt"]
    assert drafts[0]["options"][0]["locality_scope"] == "none"


def test_provider_failure_still_whole_batch_none(monkeypatch, tmp_path):
    """调用失败分流不动：LLMUnavailable → 留痕 return None（整批无头版）。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    def _boom(*_a, **_k):
        raise LLMUnavailable("provider down")

    monkeypatch.setattr(rescript_mod, "run_agent_text", _boom)
    assert generate_rescript_draft(object(), _ctx(), turn=19) is None
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn19.json"
    assert note.is_file()


def test_item_level_missing_still_whole_batch_degrade(monkeypatch, tmp_path):
    """F2.5 其它分支不动：急务条目缺 context → 整批无头版（非 option 剔除）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    raw = _items_json([{
        "title": "辽饷告匮",
        # 缺 context
        "options": [_hold(), _army_pay()],
    }])
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda *_a, **_k: raw)
    assert generate_rescript_draft(object(), _ctx(), turn=20) is None


def test_heal_ambiguous_identity_refuses_merge_then_drops(monkeypatch, tmp_path):
    """无唯一 option 身份（空 label + 同 action 兄弟）→ 拒绝合并，耗尽剔除坏项。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    # label 空白 → 缺字段；兄弟同为 assignment
    bad = _hold(label="", hint="need-label")
    sibling = _hold(label="stable", hint="keep")
    first = _items_json([{
        "title": "u", "context": "c",
        "options": [bad, sibling],
    }])
    # 重排：兄弟在前；若按 action/index 静默取会复制 stable
    healed = _items_json([{
        "title": "u", "context": "c",
        "options": [
            _hold(label="stable", hint="CHANGED"),
            _hold(label="fixed-now", hint="need-label"),
        ],
    }])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=33)
    assert drafts is not None
    opts = drafts[0]["options"]
    # 坏项因身份不唯一无法合并 → 耗尽剔除；只剩捕获的兄弟一份
    assert len(opts) == 1
    assert opts[0]["label"] == sibling["label"]
    assert opts[0]["hint"] == sibling["hint"]


def test_heal_same_title_duplicate_identity_refuses_cross_merge(monkeypatch, tmp_path):
    """两急务同 title 且 option label/action 相同 → 身份不唯一，不得串 target。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    shared_label = "同名协饷"
    bad = _army_pay(label=shared_label, target_id="guanning", amount=100)
    bad.pop("purpose", None)
    sib1 = _hold(label="缓一", hint="a")
    u1 = {"title": "同题急务", "context": "甲。", "options": [bad, sib1]}
    other = _army_pay(label=shared_label, target_id="xuanfu", amount=200)
    sib2 = _hold(label="缓二", hint="b")
    u2 = {"title": "同题急务", "context": "乙。", "options": [other, sib2]}
    first = _items_json([u1, u2])
    # 补交产出两份同 label/action 协饷（含 xuanfu）；唯一性闸须拒绝，不能把 xuanfu 并进 u1
    healed = _items_json([
        {
            "title": "同题急务", "context": "乙。",
            "options": [dict(other), sib2],
        },
        {
            "title": "同题急务", "context": "甲。",
            "options": [dict(bad, purpose="补饷", target_id="guanning"), sib1],
        },
    ])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=34)
    assert drafts is not None
    by_ctx = {d["context"]: d for d in drafts}
    # u1（甲）坏 grant 歧义未合并 → 剔除，只剩缓一；不得串入 xuanfu
    assert u1["context"] in by_ctx
    u1_opts = by_ctx[u1["context"]]["options"]
    assert len(u1_opts) == 1
    assert u1_opts[0]["label"] == sib1["label"]
    assert all(o.get("grant_action") != "协饷" for o in u1_opts)
    # u2（乙）原样保留 xuanfu 协饷
    assert u2["context"] in by_ctx
    u2_grants = [
        o for o in by_ctx[u2["context"]]["options"] if o.get("grant_action") == "协饷"
    ]
    assert len(u2_grants) == 1 and u2_grants[0]["target_id"] == "xuanfu"


def test_heal_does_not_cross_urgent_same_label(monkeypatch, tmp_path):
    """两急务同 label：补交重排后不得把另一急务的 assignment 并进失败急务的 grant 槽。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    shared = "同名拟"
    bad = _army_pay(label=shared)
    bad.pop("purpose", None)
    sib_a = _hold(label="甲缓", hint="a")
    u_fail = {"title": "关宁欠饷", "context": "边饷急。", "options": [bad, sib_a]}
    # 另一急务：同 label 但是 assignment（合法）
    other = _hold(label=shared, hint="other-hold")
    sib_b = _hold(label="乙缓", hint="b")
    u_ok = {"title": "陕西告饥", "context": "秦旱。", "options": [other, sib_b]}
    first = _items_json([u_fail, u_ok])
    # 重排急务 + 同 label 的 assignment 出现在失败急务侧——身份绑定须拒跨急务
    healed_grant = dict(bad, purpose="补饷")
    healed = _items_json([
        {"title": "陕西告饥", "context": "秦旱。", "options": [sib_b, other]},
        {
            "title": "关宁欠饷", "context": "边饷急。",
            # index0 放同 label 的 assignment（来自另一急务形态），index1 才是修好的 grant
            "options": [deepcopy(other), healed_grant],
        },
    ])
    n = {"i": 0}

    def _llm(*_a, **_k):
        n["i"] += 1
        return first if n["i"] == 1 else healed

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=32)
    assert drafts is not None
    by_title = {d["title"]: d for d in drafts}
    assert set(by_title) == {u_fail["title"], u_ok["title"]}
    fail_opts = by_title[u_fail["title"]]["options"]
    grants = [o for o in fail_opts if o.get("grant_action") == "协饷"]
    assert len(grants) == 1
    assert grants[0]["purpose"] == "补饷"
    assert grants[0]["action_type"] == "grant_allocation"
    assert grants[0]["label"] == shared
    # 不得变成 assignment
    assert not any(
        o.get("label") == shared and o.get("action_type") == "assignment"
        for o in fail_opts
    )
    ok_opts = by_title[u_ok["title"]]["options"]
    assert {o["label"] for o in ok_opts} == {other["label"], sib_b["label"]}


def test_settle_entry_heals_same_agent_and_persists(game, monkeypatch, tmp_path):
    """真实结算入口：同 agent 会话续接 + 落库可见 + 兄弟字段不改写。"""
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

    bad = _army_pay(label="边饷拟")
    bad.pop("purpose", None)
    sibling = _hold(label="缓边", hint="候核")
    first_items = [{
        "title": "关宁欠饷", "context": "边军待哺。",
        "options": [bad, sibling],
    }]
    first_raw = _items_json(first_items)
    # 补交故意篡改 amount/account/target——结算落库须仍是首抽世界事实
    healed_items = _healed_items_from(first_items)
    for it in healed_items:
        for opt in it["options"]:
            if opt.get("action_type") == "grant_allocation":
                opt["amount"] = 999
                opt["account"] = "内库"
                opt["target_id"] = "xuanfu"
    healed_raw = _items_json(healed_items)
    agents_seen: list[object] = []
    tags_seen: list[str] = []
    n = {"i": 0}

    def _fake_run(agent, prompt, tag=""):
        if tag.startswith("extractor/"):
            return _CANNED
        if tag == "rescript-draft" or tag == "rescript-draft-heal":
            agents_seen.append(agent)
            tags_seen.append(tag)
            n["i"] += 1
            return first_raw if n["i"] == 1 else healed_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _fake_run)
    # 结算侧 draft agent 与 generate 共用同一实例：side_leg 内 create 后传入 generate
    shared_agent = object()
    monkeypatch.setattr(
        decree_mod, "create_rescript_draft_agent", lambda *a, **k: shared_agent,
    )

    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报全文",
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

    # 同会话：首抽+补交均见同一 agent 实例
    assert tags_seen[0] == "rescript-draft"
    assert "rescript-draft-heal" in tags_seen
    assert agents_seen and all(a is shared_agent for a in agents_seen)

    rows = db.list_rescript_drafts()
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == first_items[0]["title"]
    assert row["status"] == "pending"  # 补齐 ≠ 已准旨
    opts = row["options"]
    assert len(opts) == 2
    grant = next(o for o in opts if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷"
    assert grant["amount"] == bad["amount"]
    assert grant["account"] == bad["account"]
    assert grant["target_id"] == bad["target_id"]  # 非 999/内库/xuanfu
    hold = next(o for o in opts if o.get("action_type") == "assignment")
    for key in (
        "label", "hint", "target_id", "locality_scope",
        "region_id", "transaction_category",
    ):
        assert hold.get(key) == sibling.get(key)


@pytest.mark.parametrize("succeed_on", [1, 2, 3, None])
def test_settle_entry_heal_k_or_exhaust(succeed_on, game, monkeypatch, tmp_path):
    """真实结算入口参数化：补交第 k 次成功，或耗尽剔除后落库。"""
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

    def _fake_run(agent, prompt, tag=""):
        del agent, prompt
        if tag.startswith("extractor/"):
            return _CANNED
        if tag in ("rescript-draft", "rescript-draft-heal"):
            heal_n["i"] += 1
            if succeed_on is None:
                return first_raw
            # 第 1 次=首抽；heal 轮序号 = i-1
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
    opts = rows[0]["options"]
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
