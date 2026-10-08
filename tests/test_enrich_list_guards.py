"""#117：apply 路径对 LLM 给的「真值非 list/dict」集合加 isinstance 守卫，不崩回合。

根因：`X.get(key) or []` 只兜 None/假值，兜不住真值非 list（true/数字/字符串）——`for x in 它`
抛 TypeError（字符串还逐字符迭代）。issue-effect 的 economy（经 _apply_economy_list apply choke）
与展示用 _format_issue_ongoing 属此类。
"""
from __future__ import annotations

from ming_sim.flows import (
    _apply_class_dict,
    _apply_economy_list,
    _apply_faction_dict,
    _apply_metric_dict,
)


def test_apply_economy_list_non_list_no_crash(read_game):
    """_apply_economy_list 的 economy 被给成真值非 list（含 dict）时不抛，返回空 applied（#117）。"""
    db, state, _content = read_game
    for bad in (True, 5, "oops", {"account": "国库", "delta": -10}):
        assert _apply_economy_list(db, state, bad) == []


def test_loads_effect_dict_healthy_and_legal_empty():
    """loads_effect_dict：合法 dict 原样；真空合法空 → {}。腐坏/非对象响亮由 parse_engine 现役闸覆盖，不复活吞腐。"""
    from ming_sim.models import loads_effect_dict  # 单一 home 在 models（leaf），各模块从此取
    assert loads_effect_dict('{"metrics": {"民心": 1}}') == {"metrics": {"民心": 1}}
    assert loads_effect_dict({"already": "parsed"}) == {"already": "parsed"}
    assert loads_effect_dict(None) == {}
    assert loads_effect_dict("") == {}
    assert loads_effect_dict("{}") == {}


def test_apply_economy_list_skips_non_dict_items(game):
    """list 内混非 dict 项不崩，跳过非 dict、只落合法项（#117 codex 逐项守）。"""
    db, state, _content = game
    out = _apply_economy_list(db, state, [1, "x", None, {"account": "国库", "delta": -3, "reason": "t"}])
    assert len(out) == 1, f"非 dict 项未被跳过/合法项未保留：{out}"
    assert out[0].get("account") == "国库"  # 只落合法那一项


def test_apply_metric_faction_class_dict_non_dict_no_crash(read_game):
    """metrics/factions/class 被给成真值非 dict（issue-effect 未验证路径）时不抛、返回空（#117 同类）。

    faction/class 自迁逐项拒收契约后返回 (已落 delta dict, 拒收项列表)（ADR 0008 决定 1，
    #14/#63），非 dict 入参 → 空 dict + 空拒收列表 `({}, [])`；metric 仍返 dict。
    """
    db, state, _content = read_game
    for bad in (True, 5, "oops", [1, 2]):
        assert _apply_metric_dict(state, bad, db=db) == {}
        assert _apply_faction_dict(db, bad) == ({}, [])
        assert _apply_class_dict(db, bad) == ({}, [])
