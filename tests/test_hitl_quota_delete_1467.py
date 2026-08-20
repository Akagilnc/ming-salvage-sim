"""#1467 — 删「每月至少一题」亲裁配额（0 题合法）。

庭裁：月末亲裁最低题数配额违 P6；题源不足时反复兜底同一母题。
本片只删配额默认，禁加去重/题库/冷却机制。

双向钉测：
1. 默认 hitl_min_decisions = 0（无「每月至少一题」）
2. 无新决策月 → pending_decisions 空，过月不被批红闸卡
3. 有真实新决策月 → 照常出题（正向不回退）
"""

from __future__ import annotations

import pytest

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
from ming_sim.llm_config import GAME_SETTINGS_DEFAULTS, load_runtime_game
from ming_sim.simulation import _load_hitl_min_decisions


_DECISION_BLOCK = (
    "本月邸报正文。\n"
    "<<DECISION>>"
    '{"title": "内帑先济何处", "context": "辽饷与秦赈两急，库银不足同济。", '
    '"options": [{"label": "先济辽饷", "hint": "边防暂安"}, '
    '{"label": "先赈陕西", "hint": "流寇稍缓"}]}'
    "<<END>>"
)


def _stub_full_settlement(monkeypatch, *, narrative: str):
    """只替外部 LLM 缝；结算脊骨走生产码。"""
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: (narrative, k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


def test_default_hitl_min_decisions_is_zero_no_monthly_quota(tmp_path, monkeypatch):
    """默认配额=0：缺 runtime_game.json / 读失败均不回落成「每月至少一题」。"""
    assert GAME_SETTINGS_DEFAULTS["hitl_min_decisions"] == 0

    missing = tmp_path / "runtime_game.json"
    monkeypatch.setattr("ming_sim.llm_config.RUNTIME_GAME_PATH", str(missing))
    loaded = load_runtime_game()
    assert loaded["hitl_min_decisions"] == 0
    assert _load_hitl_min_decisions() == 0

    # 读失败回落也必须是 0，不得悄悄恢复配额 1
    import ming_sim.llm_config as llm_cfg
    monkeypatch.setattr(
        llm_cfg, "load_runtime_game",
        lambda: (_ for _ in ()).throw(OSError("boom")),
    )
    assert _load_hitl_min_decisions() == 0


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_zero_decision_month_pending_empty_month_advances(game, monkeypatch):
    """无新决策月：pending_decisions 为空（0 题合法），过月不被批红闸卡。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _stub_full_settlement(
        monkeypatch,
        narrative="本月无值得亲裁的新决策，朝局按惯性推移。",
    )

    result = decree_mod.resolve_directives(
        state, db, None, None, [], "",
        content=content, registry=None,
    )

    assert result.awaiting is False
    assert result.decisions in (None, [])
    assert db.list_pending_decisions(closed_turn) == []
    assert int(state.turn) == closed_turn + 1
    assert state.turn_phase != "awaiting_decision"
    # 过月后新回合也无残留批红题
    assert db.list_pending_decisions(int(state.turn)) == []


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_real_decision_month_still_surfaces_pending(game, monkeypatch):
    """有真实新决策月：照常出题，正向不回退。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _stub_full_settlement(monkeypatch, narrative=_DECISION_BLOCK)

    result = decree_mod.resolve_directives(
        state, db, None, None, [1], "减赋诏",
        content=content, registry=None,
    )

    assert result.awaiting is True
    assert int(state.turn) == closed_turn  # 亲裁前不推进
    pending = db.list_pending_decisions(closed_turn)
    assert len(pending) >= 1
    assert any("内帑" in str(d.get("title") or "") for d in pending)
    assert state.turn_phase == "awaiting_decision"
    # 回执面：result.decisions 与库同真源
    assert result.decisions
    assert len(result.decisions) == len(pending)
