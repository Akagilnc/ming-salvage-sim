"""#1356/#1292：删除固定开局邸报（P7）。

钉测双向：
- 新档 t0：玩家可见面无固定 seed 邸报文（负向）
- 首月结算后：真实邸报正常出现（正向）
- 旧档载入：仅精确清除已知 seed 文，真实结算邸报保留
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
import ming_sim.memories as memories
from ming_sim.session import GameSession

ROOT = Path(__file__).resolve().parents[1]

# 固定 seed 报文指纹（与 content/opening_gazette.md 对齐；禁出现在新档 t0 玩家面）
_SEED_MARKERS = (
    "天启七年九月邸报",
    "待办未解（开局三事）",
    "信王于乾清宫即皇帝位",
)


def _seed_text() -> str:
    return (ROOT / "content" / "opening_gazette.md").read_text(encoding="utf-8").strip()


def _assert_no_seed_gazette(blob: str) -> None:
    text = str(blob or "")
    for marker in _SEED_MARKERS:
        assert marker not in text, f"seed 指纹仍在玩家面: {marker!r}"


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


def test_new_game_t0_has_no_fixed_opening_gazette(game):
    """新档 t0：turn_reports 无 seed 文；previous_summary 不含固定开局邸报。"""
    db, state, _content = game
    assert state.turn == 1
    assert (state.year, state.period) == (1627, 10)

    assert db.get_turn_report(0) == ""
    # turn=0 不得落固定 seed 行
    row = db.conn.execute("SELECT report FROM turn_reports WHERE turn = 0").fetchone()
    assert row is None

    summary = db.previous_turn_summary(state)
    _assert_no_seed_gazette(summary)
    # 允许空或系统占位（登基伊始），二者都不是合法 seed 邸报
    assert summary.strip() == "" or summary.startswith("登基伊始")


def test_first_month_settlement_produces_real_gazette(game, monkeypatch):
    """正向：首份真实邸报由第一个正常月末结算产生（非 seed）。"""
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
    _assert_no_seed_gazette(report)

    summary = db.previous_turn_summary(state)
    assert "首月真结算" in summary
    _assert_no_seed_gazette(summary)


def test_old_save_purges_seed_keeps_real_settlement_report(game):
    """旧档：精确清 seed 文；真实结算邸报保留。"""
    db, state, _content = game
    seed = _seed_text()
    assert seed, "fingerprint 源 content/opening_gazette.md 须存在"

    # 模拟旧档：turn0 写死 seed + turn1 真实结算产物（REPLACE 覆盖模板可能残留）
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (0, 1627, 9, seed),
    )
    real = "天启七年十月邸报\n\n一、真结算产物·辽饷催征，不得被清。"
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (1, 1627, 10, real),
    )
    db.conn.commit()
    assert db.get_turn_report(0) == seed
    assert "真结算产物" in db.get_turn_report(1)

    # 清 meta 标记后重跑 purge（模拟旧档首次打开）
    db.conn.execute(
        "DELETE FROM metrics WHERE key = ?",
        ("__opening_gazette_seed_purged_1356",),
    )
    db.conn.commit()
    db._purge_fixed_opening_gazette_seed()
    db.conn.commit()

    assert db.get_turn_report(0) == ""
    assert db.conn.execute("SELECT 1 FROM turn_reports WHERE turn = 0").fetchone() is None
    kept = db.get_turn_report(1)
    assert "真结算产物" in kept
    assert kept == real


def test_purge_is_idempotent_and_marker_match(game):
    """标记识别路径：含全部 seed 指纹的报文亦清；幂等再跑不伤真报。"""
    db, state, _content = game
    # 轻微空白变体（非逐字节等于文件）但仍含全部标记
    variant = (
        "天启七年九月邸报\n\n"
        "……信王于乾清宫即皇帝位……\n\n"
        "七、待办未解（开局三事）：\n假 seed 变体"
    )
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (0, 1627, 9, variant),
    )
    real = "真实月报·无 seed 标记"
    db.conn.execute(
        "INSERT OR REPLACE INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
        (2, 1627, 11, real),
    )
    db.conn.commit()

    db.conn.execute(
        "DELETE FROM metrics WHERE key = ?",
        ("__opening_gazette_seed_purged_1356",),
    )
    db.conn.commit()
    db._purge_fixed_opening_gazette_seed()
    db._purge_fixed_opening_gazette_seed()  # 幂等
    db.conn.commit()

    assert db.get_turn_report(0) == ""
    assert db.get_turn_report(2) == real


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_state_payload_t0_has_no_seed_gazette(game):
    """Web state_payload 开局 previous_summary 无固定 seed 文。"""
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
    _assert_no_seed_gazette(payload.get("previous_summary") or "")
    # 十月当前回合语义保留
    assert payload["turn"]["reign_period_label"] == "天启七年十月"
