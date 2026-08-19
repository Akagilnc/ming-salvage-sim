"""#1374 续跑：phase2 已落 decided 后 LLM 失败/重交不得覆写已落档亲裁。

崩溃安全先写 choice+status=decided；失败后玩家须能续跑同一选择，
禁第二客户端/空 payload 把落档改成别的 label。
"""

from __future__ import annotations

import json

from ming_sim.models import TurnPhase
from ming_sim.session import GameSession


def _session(db, state, content, monkeypatch, *, phase2):
    import ming_sim.session as session_mod

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", phase2)
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.last_decree = "测试诏书"
    sess.agno_db = None
    sess.llm_config = None
    sess.content = content
    sess.registry = None
    return sess


def test_submit_decisions_already_decided_keeps_stored_choice(game, monkeypatch):
    """已 decided 再交不同 label / 空 choices：账上仍是原裁，并进入 phase2。"""
    db, state, content = game
    db.save_pending_decisions(state.turn, [{
        "event_id": "evt-ning",
        "title": "关宁军饷",
        "context": "辽东急报",
        "options": [
            {"label": "发内库银三十万两先济关宁军", "hint": "先解燃眉"},
            {"label": "缓发", "hint": "再议"},
        ],
    }])
    original = {"label": "发内库银三十万两先济关宁军", "hint": "先解燃眉"}
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, status='decided' WHERE turn=? AND idx=?",
        (json.dumps(original, ensure_ascii=False), int(state.turn), 0),
    )
    db.conn.commit()
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    seen = {"n": 0}

    def _phase2(_state, _db, *_a, **_k):
        seen["n"] += 1
        stored = _db.list_pending_decisions(int(_state.turn))
        assert stored[0]["choice"] == original
        assert stored[0]["status"] == "decided"
        return "邸报：续跑。"

    sess = _session(db, state, content, monkeypatch, phase2=_phase2)
    assert sess.submit_decisions([{"label": "缓发", "note": "改裁"}]) == "邸报：续跑。"
    assert seen["n"] == 1
    row = db.list_pending_decisions(int(state.turn))
    # phase2 替身未清行：落档选择仍是原裁
    assert row[0]["choice"] == original
    assert row[0]["status"] == "decided"


def test_submit_decisions_already_decided_empty_payload_resumes(game, monkeypatch):
    """空 choices 续跑不得把 choice_json 写成 {}。"""
    db, state, content = game
    db.save_pending_decisions(state.turn, [{
        "title": "河工",
        "context": "河决在即",
        "options": [{"label": "拨银修堤", "hint": "保百姓"}],
    }])
    original = {"label": "拨银修堤", "hint": "保百姓"}
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, status='decided' WHERE turn=? AND idx=?",
        (json.dumps(original, ensure_ascii=False), int(state.turn), 0),
    )
    db.conn.commit()
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)

    def _phase2(_state, _db, *_a, **_k):
        stored = _db.list_pending_decisions(int(_state.turn))
        assert stored[0]["choice"] == original
        return "ok"

    sess = _session(db, state, content, monkeypatch, phase2=_phase2)
    assert sess.submit_decisions([]) == "ok"
    assert db.list_pending_decisions(int(state.turn))[0]["choice"] == original
