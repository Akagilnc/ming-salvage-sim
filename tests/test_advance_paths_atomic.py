from __future__ import annotations
import json
import pytest
import ming_sim.decree as decree_mod
"""玩家月链恢复入口与持久化决议验证。"""







# ---------------------------------------------------------------------------
# B. 恢复入口消费：由玩家月链接续已保存的结算进度
# ---------------------------------------------------------------------------

def _recovery_session(db, state, content, monkeypatch):
    """复用现有轻 session；真实恢复入口与办公室同步不替换。"""
    from tests.month_chain_helpers import make_light_session

    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in dossiers
        ],
    )
    sess = make_light_session(db, state, content)
    return sess




def test_record_event_decision_choice_preserves_non_triggered_terminal_state(game):
    """integrated cmr Gate2 codex correctness：event_triggers 是终态账，HITL 选择 upsert 冲突时
    只补 choice_json，**不得**把已有非 triggered 终态（avoided/expired/obsolete）翻成 triggered，
    也不得把非 triggered 行的 source 改成 hitl_decision（原 ON CONFLICT 的 terminal_state CASE
    实为空操作：excluded 恒为 'triggered'）。"""
    db, state, content = game
    eid = "__terminal_account_preserve_test__"
    db.conn.execute(
        "INSERT INTO events (id,title,kind,summary,urgency,severity,credibility,interests,audiences) "
        "VALUES (?, ?, '测试', '', 0, 0, 0, '[]', '[]')",
        (eid, eid),
    )
    db.conn.execute(
        "INSERT INTO event_triggers (event_id, turn, year, period, source, terminal_state, terminal_reason) "
        "VALUES (?, ?, ?, ?, 'simulation', 'avoided', '前提已不成立')",
        (eid, state.turn, state.year, state.period),
    )
    db.conn.commit()

    db.record_event_decision_choice(state, eid, {"label": "留"})

    row = db.conn.execute(
        "SELECT terminal_state, source, choice_json FROM event_triggers WHERE event_id=?", (eid,)
    ).fetchone()
    assert row["terminal_state"] == "avoided"          # 未被翻成 triggered
    assert row["source"] == "simulation"               # 非 triggered 行 source 不被误标
    assert json.loads(row["choice_json"]) == {"label": "留"}  # choice 仍记录

def test_record_event_decision_choice_inserts_fresh_without_terminal_state(game):
    """HITL 选择只暂存 choice，不抢先把新事件写成 triggered 终态。"""
    db, state, content = game
    eid = content.events[0].id
    db.record_event_decision_choice(state, eid, {"label": "斩"})
    row = db.conn.execute(
        "SELECT terminal_state, source, choice_json FROM event_triggers WHERE event_id=?", (eid,)
    ).fetchone()
    assert row["terminal_state"] == ""
    assert row["source"] == "hitl_decision"
    assert json.loads(row["choice_json"]) == {"label": "斩"}

def test_mark_event_triggered_upgrades_pending_choice_row(game):
    """phase2 正常触发事件时，空终态 choice 行升级为 triggered 且保留亲裁选择。

    终态本身照旧晋级，source 照旧记晋级来源，choice 与 reason 照旧保留。
    #1899（R4）：此前此用例还断言时刻列保留批红回合，那是**已删**的时序比较补丁的
    配套断言（比较本身已删，时刻保留失去依据）；按「被改动作废的旧物随同改动删除」，
    时刻断言一并删除，此处只留仍然成立的终态／来源／choice 契约。
    """
    db, state, content = game
    eid = content.events[0].id
    db.record_event_decision_choice(state, eid, {"label": "留"})
    state.turn = state.turn + 1
    state.year = state.year + 1
    state.period = 7

    db.mark_event_triggered(state, eid, source="event_pool")

    row = db.conn.execute(
        "SELECT terminal_state, source, terminal_reason, choice_json FROM event_triggers WHERE event_id=?",
        (eid,),
    ).fetchone()
    assert row["terminal_state"] == "triggered"
    assert row["source"] == "event_pool"
    assert row["terminal_reason"] == "留"
    assert json.loads(row["choice_json"]) == {"label": "留"}

@pytest.mark.parametrize(
    ("marker", "terminal_state", "source", "reason"),
    [
        ("expired", "expired", "window_expired", "过最晚触发时点仍未达成触发门"),
        ("avoided", "avoided", "gate_avoided", "前提已不成立"),
        ("obsolete", "obsolete", "person_core_dead", "点名人物已死亡"),
    ],
)
def test_terminal_markers_upgrade_pending_choice_row(game, marker, terminal_state, source, reason):
    """确定性终态须覆盖空终态 HITL choice 行，保留亲裁选择，并刷新终态时刻。"""
    db, state, content = game
    eid = content.events[0].id
    db.record_event_decision_choice(state, eid, {"label": "留"})
    terminal_turn = state.turn + 1
    terminal_year = state.year + 1
    terminal_period = 7
    state.turn = terminal_turn
    state.year = terminal_year
    state.period = terminal_period

    if marker == "expired":
        db.mark_event_expired(state, eid)
    elif marker == "avoided":
        db.mark_event_avoided(state, eid, reason)
    elif marker == "obsolete":
        db.mark_event_obsolete(state, eid, reason)
    else:
        raise AssertionError(marker)

    row = db.conn.execute(
        "SELECT turn, year, period, terminal_state, source, terminal_reason, choice_json FROM event_triggers WHERE event_id=?",
        (eid,),
    ).fetchone()
    assert row["turn"] == terminal_turn
    assert row["year"] == terminal_year
    assert row["period"] == terminal_period
    assert row["terminal_state"] == terminal_state
    assert row["source"] == source
    assert row["terminal_reason"] == "留"
    assert json.loads(row["choice_json"]) == {"label": "留"}



def test_draft_mutators_frozen_at_front_half_done(game, monkeypatch):
    """FRONT_HALF_DONE 冻结 draft/诏书变更器（ship-pre r1 codex）。

    恢复窗口新增/确认的 draft 会被 mark_directives_issued 连带标 issued，
    但它们未经过本月逐旨核算=幽灵颁布。
    """
    db, state, content = game
    state.turn_phase = "settling"

    sess = _recovery_session(db, state, content, monkeypatch)
    for call in (
        lambda: sess.delete_directive(1),
    ):
        with pytest.raises(ValueError):
            call()


def test_resolve_turn_write_gate_held_by_caller_no_reenter(game, monkeypatch):
    from tests.month_chain_helpers import make_light_session, canned_full_settlement
    db, state, content = game
    session = make_light_session(db, state, content)
    canned_full_settlement(monkeypatch)
    gate = session._write_gate
    assert gate.acquire(blocking=False)
    try:
        session.resolve_turn(allow_empty_decree=True, write_gate_already_held=True)
        assert not gate.acquire(blocking=False)
    finally:
        gate.release()

def test_recovery_blocked_by_pending_directives(game, monkeypatch):
    """恢复与正常路同守门：pending 拟旨未核定不得推进（cmr S7 r8 codex）。

    跳过守门的话恢复期大臣新拟的旨随推进孤儿在旧回合——正常路会拦。
    """
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    # 恢复期大臣拟旨（pending 待准驳）
    db.issues.add_directive(state.turn, state.year, state.period, None, '请拨内帑', source='minister', status='pending')
    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(ValueError):
        sess.resolve_turn()
    assert state.turn == turn  # 未推进，拟旨不孤儿
