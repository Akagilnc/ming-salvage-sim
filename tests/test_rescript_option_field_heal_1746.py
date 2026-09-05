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

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=11)
    assert drafts is not None
    assert len(drafts) == 1
    opts = drafts[0]["options"]
    # good_n=1 + 1 bad + 隐式不再另加 → first had bad+1 good = 2
    assert len(opts) == 2
    grants = [o for o in opts if o.get("grant_action") == "协饷"]
    assert len(grants) == 1
    assert grants[0]["purpose"] == "补饷"
    assert grants[0]["amount"] == 300
    assert grants[0]["account"] == "国库"
    assert grants[0]["target_id"] == "guanning"
    # 正常 option 逐字段无改写
    normals = [o for o in opts if o.get("action_type") == "assignment"]
    assert len(normals) == 1
    assert normals[0]["label"] == "正常拟0"
    assert normals[0]["hint"] == "h0"
    # 经真实补交：首抽 + succeed_on 次补交
    assert len(calls) == 1 + succeed_on
    assert calls[0]["tag"] == "rescript-draft"
    for c in calls[1:]:
        assert "heal" in c["tag"]
        # 原始产出进入补交上下文
        assert first_raw in c["prompt"] or "补发关宁军饷" in c["prompt"]
        assert "purpose" in c["prompt"]
    # 补交 ≠ 组合重抽：补交 prompt 不得整批重抛 payload 冒充（无「结构组合校验失败」）
    for c in calls[1:]:
        assert "结构组合校验失败" not in c["prompt"]


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
    assert drafts is not None
    assert len(drafts) == 1
    opts = drafts[0]["options"]
    assert len(opts) == 1  # bad dropped
    assert opts[0]["action_type"] == "assignment"
    assert opts[0]["label"] == "正常拟0"
    # 首抽 + 3 补交
    assert len(calls) == 1 + RESCRIPT_OPTION_FIELD_HEAL_RETRIES
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn12.json"
    assert note.is_file()
    body = note.read_text(encoding="utf-8")
    assert "purpose" in body
    assert "关宁欠饷" in body


def test_drop_leaving_one_option_still_presents(monkeypatch, tmp_path):
    """F2.2 局部修订：因剔除剩 1 个 option 仍可呈（非整批作废）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    # 恰 2 option：1 bad + 1 good → 剔后剩 1
    items = _one_urgent_missing_purpose(good_n=1)
    assert len(items[0]["options"]) == 2
    raw = _items_json(items)
    monkeypatch.setattr(
        rescript_mod, "run_agent_text", lambda *_a, **_k: raw,
    )
    drafts = generate_rescript_draft(object(), _ctx(), turn=13)
    assert drafts is not None
    assert len(drafts[0]["options"]) == 1


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
    assert "辽东索饷" not in titles
    assert "陕西告饥" in titles
    assert len(drafts) == 1
    assert len(drafts[0]["options"]) == 2
    assert [o["label"] for o in drafts[0]["options"]] == ["发帑赈济", "缓征加赈"]


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
    assert set(by_title) == {"关宁急饷", "宣大欠饷"}
    # u1：bad 已补上，2 option 全在
    g1 = by_title["关宁急饷"]["options"]
    assert len(g1) == 2
    grant = next(o for o in g1 if o.get("grant_action") == "协饷")
    assert grant["purpose"] == "补饷" and grant["label"] == "关宁补饷"
    assert next(o for o in g1 if o["label"] == "关宁缓议")["hint"] == "候边报"
    # u2：bad 剔除，两 good 原样
    g2 = by_title["宣大欠饷"]["options"]
    assert [o["label"] for o in g2] == ["宣大查核", "宣大缓派"]
    assert all(o.get("grant_action") != "协饷" for o in g2)


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
    assert by_label["combo"]["locality_scope"] == "none"  # 组合重抽结果保留
    assert by_label["field"]["purpose"] == "补饷"
    assert by_label["field"]["amount"] == 200


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
    assert mo["assignee_name"] == "袁崇焕"
    assert next(o for o in opts if o["label"] == "缓议")["hint"] == "候报"


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
    # 补交轮故意改写兄弟 label/hint
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
    assert grant["purpose"] == "补饷" and grant["label"] == "pay"
    sib = next(o for o in opts if o.get("action_type") == "assignment")
    assert sib["label"] == "stable"
    assert sib["hint"] == "keep"


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
    calls: list[str] = []

    def _llm(_agent, prompt, tag=""):
        calls.append(prompt)
        if len(calls) == 1:
            return _items_json([bad_combo])
        return _items_json([good_combo])

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), _ctx(), turn=18)
    assert drafts is not None
    assert len(calls) == 2
    # 组合纠错反馈形态（非缺字段补交）
    assert "结构组合校验失败" in calls[1]
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
