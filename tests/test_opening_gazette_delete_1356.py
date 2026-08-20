"""#1356/#1292：删除固定开局邸报（P7）。

钉测只保四个票面行为：
1. t0 previous_summary 严格空
2. 旧 seed 精确清且真实报保留（含三短语反例：真报含短语不被删）
3. 空壳可关闭（前端 vitest）
4. 首月真报出现
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
from ming_sim.session import GameSession

ROOT = Path(__file__).resolve().parents[1]

# 三短语仅作反例材料（真报可含之）；purge 不得靠它们 substring 删行
_SEED_PHRASES = (
    "天启七年九月邸报",
    "待办未解（开局三事）",
    "信王于乾清宫即皇帝位",
)


def _seed_text() -> str:
    return (ROOT / "content" / "opening_gazette.md").read_text(encoding="utf-8").strip()


def _canned_settle(monkeypatch, narrative: str) -> None:
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (narrative, k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        decree_mod,
        "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')


def _session(db, state, content) -> GameSession:
    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.registry = session.llm_config = session.agno_db = None
    session.deaths_this_turn, session.debuts_this_turn = [], []
    session.last_decree = session.last_report = ""
    session._decree_draft_fingerprint = ()
    session._scene_registry = None
    session._beat_generator = None
    session.auto_save = lambda *a, **k: None
    return session


def test_new_game_t0_previous_summary_strictly_empty(game):
    """① t0：previous_summary 严格空串；turn_reports 无 seed 行。"""
    db, state, _content = game
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)

    assert db.get_turn_report(0) == ""
    assert db.conn.execute("SELECT report FROM turn_reports WHERE turn = 0").fetchone() is None

    summary = db.previous_turn_summary(state)
    assert summary == ""
    # 固定空态文案不得回流
    assert "登基伊始" not in summary
    assert "尚无上月" not in summary


def test_non_t0_empty_previous_summary_strictly_empty(game):
    """① 非 t0：无 report 且无 logs 同样严格空串（禁固定空态句）。"""
    db, state, _content = game
    # previous_turn = 2（>0）；确保该月无报文、无 turn_logs
    state.turn = 3
    assert db.get_turn_report(2) == ""
    assert (
        db.conn.execute("SELECT 1 FROM turn_logs WHERE turn = 2").fetchone() is None
    )

    summary = db.previous_turn_summary(state)
    assert summary == ""
    assert "未见正式记录" not in summary
    assert "登基伊始" not in summary
    assert "尚无上月" not in summary


def test_first_month_settlement_produces_real_gazette(game, monkeypatch):
    """④ 正向：首份真实邸报由第一个正常月末结算产生。"""
    db, state, content = game
    closed_turn = int(state.turn)
    narrative = "天启七年十月邸报\n\n一、边事自演。辽饷催征，流寇未息。——首月真结算"
    _canned_settle(monkeypatch, narrative)

    result = _session(db, state, content).advance_without_decree()
    assert result is not None and result.awaiting is False
    assert int(state.turn) == closed_turn + 1

    report = db.get_turn_report(closed_turn)
    assert "首月真结算" in report
    assert "边事自演" in report

    summary = db.previous_turn_summary(state)
    assert "首月真结算" in summary
    assert summary == report


def test_old_save_exact_purge_keeps_real_with_phrase_counterexample(game):
    """② 旧档：完整指纹精确 DELETE seed；真报保留——含三短语反例不被删。"""
    db, state, _content = game
    seed = _seed_text()
    assert seed, "fingerprint 源 content/opening_gazette.md 须存在"
    # 反例：真结算散文含全部三短语，但全文 ≠ seed
    for phrase in _SEED_PHRASES:
        assert phrase in seed
    real = (
        "天启七年十月邸报\n\n"
        "一、真结算产物。史官追述：信王于乾清宫即皇帝位已成定局。\n"
        "二、档案提及「天启七年九月邸报」仅作引用，本月另有边饷核账。\n"
        "三、待办未解（开局三事）之余波仍在，户部续议——不得被 purge。\n"
        "——真结算保留标记"
    )
    for phrase in _SEED_PHRASES:
        assert phrase in real, f"反例须含短语 {phrase!r}"
    assert real != seed

    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (0, 1627, 9, seed),
    )
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (1, 1627, 10, real),
    )
    db.conn.commit()
    assert db.get_turn_report(0) == seed
    assert db.get_turn_report(1) == real

    db._purge_fixed_opening_gazette_seed()
    db._purge_fixed_opening_gazette_seed()  # 精确 DELETE 天然幂等

    assert db.get_turn_report(0) == ""
    assert db.conn.execute("SELECT 1 FROM turn_reports WHERE turn = 0").fetchone() is None
    kept = db.get_turn_report(1)
    assert kept == real
    assert "真结算保留标记" in kept
    # 无 meta flag 机制
    assert (
        db.conn.execute(
            "SELECT 1 FROM metrics WHERE key = ?",
            ("__opening_gazette_seed_purged_1356",),
        ).fetchone()
        is None
    )


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_state_payload_t0_previous_summary_empty(game):
    """Web state_payload 开局 previous_summary 严格空。"""
    import web_app
    from types import SimpleNamespace

    db, state, content = game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary=db.previous_turn_summary(state),
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"

    payload = web_app.WebGame.state_payload(runtime)
    assert payload.get("previous_summary") == ""
    assert "登基伊始" not in (payload.get("previous_summary") or "")
    assert payload["turn"]["reign_period_label"] == "天启七年十月"
