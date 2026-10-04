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
    from tests.settlement_seam_helpers import canned_full_settlement
    canned_full_settlement(monkeypatch, narrative=narrative)


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

    assert db.turn_reports.report_text(0) == ""
    assert db.conn.execute("SELECT report FROM turn_reports WHERE turn = 0").fetchone() is None

    summary = db.previous_turn_summary(state)
    assert summary == ""
    # 固定空态文案不得回流


def test_new_game_t0_previous_reign_period_label_empty_with_empty_summary(game):
    """r5：t0 无上月报 → previous_reign_period_label 与空 summary 同口径（禁九月残留）。"""
    db, state, _content = game
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)
    assert db.previous_turn_summary(state) == ""
    label = db.previous_turn_reign_period_label(state)
    assert label == ""


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
    assert payload["turn"]["reign_period_label"] == "天启七年十月"
    # r5：payload 开局 label 与空 summary 同口径，禁九月残留
    assert payload.get("previous_reign_period_label") in ("", None)
