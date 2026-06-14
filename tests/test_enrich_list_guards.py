"""#117：enrich / apply 路径对 LLM 给的「真值非 list/dict」集合加 isinstance 守卫，不崩回合。

根因：`X.get(key) or []` 只兜 None/假值，兜不住真值非 list（true/数字/字符串）——`for x in 它`
抛 TypeError（字符串还逐字符迭代）。enrich_initiative_effects.buildings 是直接诱因；同 bug 类还有
issue-effect 的 economy（经 _apply_economy_list apply choke）与展示用 _format_issue_ongoing。
"""
from __future__ import annotations

import ming_sim.cli_backend as cb
from ming_sim.flows import (
    _apply_class_dict,
    _apply_economy_list,
    _apply_faction_dict,
    _apply_metric_dict,
)


def test_enrich_buildings_non_list_no_crash(monkeypatch):
    """enrich_initiative_effects 的 buildings 被 LLM 给成真值非 list（true/数字/字符串）不抛 TypeError。"""
    for bad in ("true", "5", '"oops"'):
        raw = ('{"effect_on_resolve": {"buildings": ' + bad +
               ', "metrics": {"民心": 1}}, "ongoing_effects": {}, "effect_on_fail": {}}')
        monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (raw, 1))
        out = cb.enrich_initiative_effects("练新军", "现状", llm_config=None)
        assert isinstance(out["effect_on_resolve"], dict)  # 不崩、结构正常
        assert out["effect_on_resolve"].get("buildings") == []  # 脏非 list 值被源头清成 []（gemini PR#127）


def test_apply_economy_list_non_list_no_crash(game):
    """_apply_economy_list 的 economy 被给成真值非 list（含 dict）时不抛，返回空 applied（#117）。"""
    db, state, _content = game
    for bad in (True, 5, "oops", {"account": "国库", "delta": -10}):
        assert _apply_economy_list(db, state, bad) == []


def test_apply_economy_list_valid_still_works(game):
    """守卫不误伤正常 list：合法 economy 项确实落账（断内容，非仅 isinstance——codex）。"""
    db, state, _content = game
    out = _apply_economy_list(db, state, [{"account": "国库", "delta": -5, "reason": "测试"}])
    assert len(out) == 1, f"合法 economy 项被守卫误吞：{out}"
    assert out[0].get("account") == "国库"


def test_loads_effect_dict_coerces_non_dict():
    """loads_effect_dict：effect_on_resolve/fail/ongoing_effects 列读取单一守门——合法 dict 原样，
    真值非 dict / 解析失败 / 空 → {}（#117 R3：集中所有 effect-列读取于此，止 coverage-drift）。"""
    from ming_sim.models import loads_effect_dict  # 单一 home 在 models（leaf），各模块从此取
    assert loads_effect_dict('{"metrics": {"民心": 1}}') == {"metrics": {"民心": 1}}
    assert loads_effect_dict({"already": "parsed"}) == {"already": "parsed"}  # 已解析 dict 原样（codex R4）
    for bad in ('"oops"', "5", "true", "[1,2]", "null", "", None, "不是合法json", 5, [1, 2], True):
        assert loads_effect_dict(bad) == {}, f"{bad!r} 未归 {{}}"


def test_inertia_ongoing_non_dict_no_crash(game):
    """apply_issue_inertia_and_ongoing（结算链 ongoing_effects 第三读取者）读到已存的真值非 dict
    ongoing_effects 不崩——与 _issue_auto_economy / _format_issue_ongoing 同口径外层守（#117 R2 Claude+codex）。"""
    from ming_sim.issues import apply_issue_inertia_and_ongoing
    db, state, _content = game
    iid = db.insert_issue(state, kind="situation", title="畸形ongoing测试", bar_value=50, inertia=1)
    for bad in ('"oops"', "5", "true", "[1,2]"):
        db.conn.execute("UPDATE issues SET ongoing_effects=? WHERE id=?", (bad, iid))
        db.conn.commit()
        apply_issue_inertia_and_ongoing(db, state)  # 不抛 AttributeError/TypeError


def test_apply_economy_list_skips_non_dict_items(game):
    """list 内混非 dict 项不崩，跳过非 dict、只落合法项（#117 codex 逐项守）。"""
    db, state, _content = game
    out = _apply_economy_list(db, state, [1, "x", None, {"account": "国库", "delta": -3, "reason": "t"}])
    assert len(out) == 1, f"非 dict 项未被跳过/合法项未保留：{out}"
    assert out[0].get("account") == "国库"  # 只落合法那一项


def test_apply_metric_faction_class_dict_non_dict_no_crash(game):
    """metrics/factions/class 被给成真值非 dict（issue-effect 未验证路径）时不抛、返回空（#117 同类）。"""
    db, state, _content = game
    for bad in (True, 5, "oops", [1, 2]):
        assert _apply_metric_dict(state, bad, db=db) == {}
        assert _apply_faction_dict(db, bad) == {}
        assert _apply_class_dict(db, bad) == {}
