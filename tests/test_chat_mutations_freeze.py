"""恢复窗内任免落地与史实人物补档不改盘。"""

from __future__ import annotations

from types import SimpleNamespace

import ming_sim.session as session_mod
from ming_sim.session import GameSession, TurnPhase


def _settling_session(db, state, content):
    """轻量 GameSession（__new__ 跳过重型 init），相位置 settling。"""
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    state.turn_phase = TurnPhase.SETTLING.value
    return sess


def test_appointment_blocked_in_recovery_window(game, monkeypatch):
    """恢复窗内 propose_appointment 落地核不触发，返回空对（恢复窗婉拒）。"""
    db, state, content = game
    sess = _settling_session(db, state, content)
    called = []
    monkeypatch.setattr(
        session_mod, "apply_appointment",
        lambda *a, **k: called.append(1) or ("某甲", ""))

    appointed, displaced = sess._apply_appointment(
        '{"name": "测试某甲", "office": "兵部右侍郎"}',
        appointer=SimpleNamespace(name="吏部尚书"))

    assert (appointed, displaced) == ("", "")
    assert called == []  # 落地核未被触达


def test_unlisted_person_blocked_in_recovery_window(game):
    """恢复窗内史实补档不建档，characters 表无新行。"""
    db, state, content = game
    sess = _settling_session(db, state, content)

    registered, summon_after = sess._apply_unlisted_person_registration(
        '{"name": "测试乙补档", "office": "翰林院编修", "office_type": "文官"}')

    assert (registered, summon_after) == ("", False)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM characters WHERE name=?", ("测试乙补档",)
    ).fetchone()[0] == 0
