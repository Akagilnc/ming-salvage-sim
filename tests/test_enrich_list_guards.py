"""#117：enrich / apply 路径对 LLM 给的「真值非 list/dict」集合加 isinstance 守卫，不崩回合。

根因：`X.get(key) or []` 只兜 None/假值，兜不住真值非 list（true/数字/字符串）——`for x in 它`
抛 TypeError（字符串还逐字符迭代）。enrich_initiative_effects.buildings 是直接诱因；同 bug 类还有
issue-effect 的 economy（经 _apply_economy_list apply choke）与展示用 _format_issue_ongoing。
"""
from __future__ import annotations

import ming_sim.cli_backend as cb
from ming_sim.flows import _apply_economy_list


def test_enrich_buildings_non_list_no_crash(monkeypatch):
    """enrich_initiative_effects 的 buildings 被 LLM 给成真值非 list（true/数字/字符串）不抛 TypeError。"""
    for bad in ("true", "5", '"oops"'):
        raw = ('{"effect_on_resolve": {"buildings": ' + bad +
               ', "metrics": {"民心": 1}}, "ongoing_effects": {}, "effect_on_fail": {}}')
        monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: (raw, 1))
        out = cb.enrich_initiative_effects("练新军", "现状", llm_config=None)
        assert isinstance(out["effect_on_resolve"], dict)  # 不崩、结构正常


def test_apply_economy_list_non_list_no_crash(game):
    """_apply_economy_list 的 economy 被给成真值非 list（含 dict）时不抛，返回空 applied（#117）。"""
    db, state, _content = game
    for bad in (True, 5, "oops", {"account": "国库", "delta": -10}):
        assert _apply_economy_list(db, state, bad) == []


def test_apply_economy_list_valid_still_works(game):
    """守卫不误伤正常 list：合法 economy 仍正常落账。"""
    db, state, _content = game
    out = _apply_economy_list(db, state, [{"account": "国库", "delta": -5, "reason": "测试"}])
    assert isinstance(out, list)  # 正常路径不被守卫吞掉
