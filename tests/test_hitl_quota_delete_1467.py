"""#1467 r3 — 端到端删除 hitl_min_decisions 配额机制。

庭裁：月末亲裁最低题数配额违 P6；r1 只改默认仍保留 opt-in。
本片删除 UI/API/config/payload/prompt 整条配额接缝；旧 runtime_game.json
正值自然失效（不写迁移）；禁加去重/题库/冷却/替代 quota。

钉测：
1. 机制缺席：源码/payload 不再出现 hitl_min_decisions 读写与注入
2. 失效钉：旧持久值经 user_data_path 落在真实用户数据位时，无真实抉择月仍 0 题过月
3. 正向：有真实抉择月仍进 pending
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
import ming_sim.llm_config as llm_config
import ming_sim.memories as memories
import ming_sim.simulation as simulation
import web_app
from ming_sim.paths import user_data_path


_DECISION_BLOCK = (
    "本月邸报正文。\n"
    "<<DECISION>>"
    '{"title": "内帑先济何处", "context": "辽饷与秦赈两急，库银不足同济。", '
    '"options": [{"label": "先济辽饷", "hint": "边防暂安"}, '
    '{"label": "先赈陕西", "hint": "流寇稍缓"}]}'
    "<<END>>"
)

_REPO = Path(__file__).resolve().parents[1]


def _stub_full_settlement(monkeypatch, *, narrative: str, payload_spy=None):
    """只替外部 LLM 缝；结算脊骨走生产码。"""
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    def _sim(*a, **k):
        payload = k.get("simulator_payload") or {}
        if payload_spy is not None:
            payload_spy.append(payload)
        return narrative, payload

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _sim)
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


def test_hitl_quota_mechanism_fully_deleted():
    """机制缺席：配置读写/loader/API/payload 注入/UI 选择器全部不在。"""
    # config / loader 符号
    assert not hasattr(llm_config, "GAME_SETTINGS_DEFAULTS")
    assert not hasattr(llm_config, "load_runtime_game")
    assert not hasattr(llm_config, "save_runtime_game")
    assert not hasattr(llm_config, "RUNTIME_GAME_PATH")
    assert not hasattr(simulation, "_load_hitl_min_decisions")

    # payload 组装源不再含配额字段
    src = inspect.getsource(simulation)
    assert "hitl_min_decisions" not in src
    assert "_load_hitl_min_decisions" not in src

    # API 面
    assert not hasattr(web_app, "GameSettingsRequest")
    assert not hasattr(web_app, "api_menu_game_settings")
    assert not hasattr(web_app, "api_menu_save_game_settings")
    web_src = inspect.getsource(web_app)
    assert "hitl_min_decisions" not in web_src
    assert "/api/menu/game_settings" not in web_src

    # UI 选择器与 game_settings 字段
    menu = (_REPO / "web/src/components/menuPage.tsx").read_text(encoding="utf-8")
    assert "hitl_min_decisions" not in menu
    assert "GameSettingsModal" not in menu
    assert "每回合最少重大抉择数" not in menu
    assert "每回合至少 1 个" not in menu
    types = (_REPO / "web/src/types.ts").read_text(encoding="utf-8")
    assert "hitl_min_decisions" not in types
    assert "game_settings" not in types

    # prompt 不再读配额字段（正向措辞由源码复核，不盯自由文本）
    prompt = (_REPO / "content/prompts/season_simulator.md").read_text(encoding="utf-8")
    assert "hitl_min_decisions" not in prompt


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_stale_persisted_quota_ineffective_zero_decision_month(game, monkeypatch):
    """失效钉：旧 runtime_game.json 正值落在真实用户数据位时，无真实抉择月仍 0 题过月。"""
    # 经现行 user_data_path 写到生产原先真实用户数据位置（隔离 fixture 下）
    stale = Path(user_data_path("runtime_game.json"))
    stale.write_text(json.dumps({"hitl_min_decisions": 5}), encoding="utf-8")

    db, state, content = game
    closed_turn = int(state.turn)
    payloads = []
    _stub_full_settlement(
        monkeypatch,
        narrative="本月无值得亲裁的新决策，朝局按惯性推移。",
        payload_spy=payloads,
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
    assert db.list_pending_decisions(int(state.turn)) == []
    # payload 不得再携带配额字段（旧存值自然失效）
    assert payloads, "simulator must have been invoked"
    for p in payloads:
        assert "hitl_min_decisions" not in p


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
    assert result.decisions
    assert len(result.decisions) == len(pending)
