"""玩家月链恢复入口与持久化决议验证。"""

from __future__ import annotations

from ming_sim.session_write_queue import get_session_write_queue

import json
import threading

import pytest

import ming_sim.decree as decree_mod
import ming_sim.issues as I
from tests.dossier_test_helpers import TYPED_COVERT_TASK

def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# B. 恢复入口消费：由玩家月链接续已保存的结算进度
# ---------------------------------------------------------------------------

def _recovery_session(db, state, content, monkeypatch):
    """装一个最小 GameSession（__new__ 跳过重型 __init__），供真实恢复入口。"""
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"}
            for row in dossiers
        ],
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    sess.agno_db = None
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    sess.last_decree = ""
    sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._write_gate = get_session_write_queue(sess).write_gate
    monkeypatch.setattr(GameSession, "auto_save", lambda self, tag: None)
    return sess

def test_submit_event_decision_persists_choice_after_pending_cleanup(game, monkeypatch):
    """#345：事件亲裁选择不能只活在 pending_decisions；phase2 清理后仍须可从事件账恢复。"""
    import json
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    turn = state.turn
    event_id = "mao_wenlong"
    db.save_pending_decisions(turn, [{
        "event_id": event_id,
        "title": "毛文龙裁断",
        "context": "东江事急，须御前亲裁。",
        "options": [
            {"label": "斩", "hint": "严肃军纪"},
            {"label": "留", "hint": "暂稳东江"},
        ],
    }])
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    def _phase2(_state, _db, *_args, **_kwargs):
        _db.clear_pending_decisions(turn)
        return "ok"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.last_decree = "测试诏书"
    sess.agno_db = None
    sess.llm_config = None
    sess.content = content
    sess.registry = None

    d_key = db.list_rescript_desk(turn)[0]["decision_key"]
    sess.submit_hitl_choices(
        [{
            "decision_key": d_key, "action": "follow_draft",
            "label": "留", "hint": "暂稳东江", "note": "姑留观后效",
        }],
        write_gate=get_session_write_queue(sess).write_gate,
    )

    assert db.list_pending_decisions(turn) == []
    row = db.conn.execute(
        "SELECT terminal_state, source, choice_json FROM event_triggers WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == ""
    assert row["source"] == "hitl_decision"
    assert json.loads(row["choice_json"]) == {
        "decision_key": d_key,
        "action": "decision",
        "label": "留",
        "hint": "暂稳东江",
        "note": "姑留观后效",
    }
    assert not db.has_event_triggered(event_id)
    assert event_id not in I._event_trigger_refs(db), (
        "submit_hitl_choices 只能暂存亲裁 choice，不能在 phase2 前抢先把候选事件记成终态"
    )

def test_submit_decisions_does_not_overwrite_already_decided_rows(game, monkeypatch):
    """#1418 r2 / #1589：phase2 失败后续跑——已 decided 行不得被空/异载荷覆写。

    崩溃安全先写后跑：choice 已落 status=decided，phase2 尚未完成。
    desk 此刻无 pending 行（已 decided，不在 list_rescript_desk 投影内）：
    ① 真正空 choices 续跑合法，保留账上原 choice 再进 phase2；
    ② #1589 起，非空无键载荷不再被静默吞掉/忽略——空 desk 无例外，整批拒、零写，
    account 上原 choice 因整批拒直接原样未动（比忽略更强的不变式）。
    """
    import json
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    turn = state.turn
    original = {"label": "斩", "note": "原裁断"}
    # phase1 HITL 暂停上下文——与真实 awaiting 存档同形
    db.save_resolve_context(
        turn, "HITL诏", {"candidate_events": []},
    )
    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    db.save_pending_decisions(turn, [{
        "title": "毛文龙裁断", "context": "c",
        "options": [{"label": "斩", "hint": ""}, {"label": "留", "hint": ""}],
    }])
    # 模拟先写后跑：status=decided + choice 已落
    db.conn.execute(
        "UPDATE pending_decisions SET choice_json=?, status='decided' WHERE turn=? AND idx=0",
        (json.dumps(original, ensure_ascii=False), turn),
    )
    db.conn.commit()
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    seen = []

    def _phase2(_state, _db, *_args, **_kwargs):
        rows = _db.list_pending_decisions(turn)
        assert rows and rows[0]["status"] == "decided"
        assert rows[0]["choice"] == original, "phase2 读到的须是原 choice"
        seen.append(dict(rows[0]["choice"] or {}))
        # 不清 pending——便于第二刀再读；真实 phase2 成功后会 clear
        return "ok"

    monkeypatch.setattr(session_mod, "resolve_decisions_phase2", _phase2)

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.last_decree = "HITL诏"
    sess.agno_db = None
    sess.llm_config = None
    sess.content = content
    sess.registry = None

    # ① 空载荷续跑不得清空
    assert sess.submit_hitl_choices([], write_gate=get_session_write_queue(sess).write_gate) == "ok"
    assert db.list_pending_decisions(turn)[0]["choice"] == original

    # 复位 awaiting 再试异载荷（模拟 phase2 再次失败后的续跑）
    state.turn_phase = "awaiting_decision"
    db.save_state(state)
    # ② #1589：空 desk + 非空无键异载荷整批拒，不静默吞掉——phase2 不重入
    with pytest.raises(ValueError):
        sess.submit_hitl_choices(
            [{"label": "留", "note": "改裁"}], write_gate=get_session_write_queue(sess).write_gate,
        )
    assert db.list_pending_decisions(turn)[0]["choice"] == original, \
        "已 decided 行不得被异载荷覆写"
    assert seen == [original]

def test_submit_dossier_rescript_does_not_create_event_trigger(game, monkeypatch):
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    # 现行 rendered 契约：服务端 option 带 hint；choice 由服务端 option 重建（#1492 D）
    option = {
        "label": "收回",
        "hint": "收回此道准旨",
        "dossier_id": dossier_id,
        "dossier_decision": "withdrawn",
    }
    db.save_pending_decisions(state.turn, [{
        "event_id": f"dossier:{dossier_id}", "title": "批红待裁",
        "context": "清核河工", "options": [option],
    }])
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    monkeypatch.setattr(
        session_mod, "resolve_decisions_phase2", lambda *_a, **_k: "ok",
    )
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.last_decree = "测试诏书"
    sess.agno_db = None
    sess.llm_config = None
    sess.content = content
    sess.registry = None

    d_key = db.list_rescript_desk(state.turn)[0]["decision_key"]
    assert sess.submit_hitl_choices(
        [{**option, "decision_key": d_key}], write_gate=get_session_write_queue(sess).write_gate,
    ) == "ok"
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        (f"dossier:{dossier_id}",),
    ).fetchone() is None
    stored = db.list_pending_decisions(state.turn)[0]
    assert stored["status"] == "decided"
    assert stored["choice"] == {
        "decision_key": d_key,
        "action": "withdrawn",
        "label": "收回",
        "hint": "收回此道准旨",
        "dossier_id": dossier_id,
        "dossier_decision": "withdrawn",
    }

def test_record_event_decision_choice_preserves_non_triggered_terminal_state(game):
    """integrated cmr Gate2 codex correctness：event_triggers 是终态账，HITL 选择 upsert 冲突时
    只补 choice_json，**不得**把已有非 triggered 终态（avoided/expired/obsolete）翻成 triggered，
    也不得把非 triggered 行的 source 改成 hitl_decision（原 ON CONFLICT 的 terminal_state CASE
    实为空操作：excluded 恒为 'triggered'）。"""
    import json
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
    import json
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
    """phase2 正常触发事件时，空终态 choice 行升级为 triggered 且保留亲裁选择。"""
    import json
    db, state, content = game
    eid = content.events[0].id
    db.record_event_decision_choice(state, eid, {"label": "留"})
    trigger_turn = state.turn + 1
    trigger_year = state.year + 1
    trigger_period = 7
    state.turn = trigger_turn
    state.year = trigger_year
    state.period = trigger_period

    db.mark_event_triggered(state, eid, source="event_pool")

    row = db.conn.execute(
        "SELECT turn, year, period, terminal_state, source, terminal_reason, choice_json FROM event_triggers WHERE event_id=?",
        (eid,),
    ).fetchone()
    assert row["turn"] == trigger_turn
    assert row["year"] == trigger_year
    assert row["period"] == trigger_period
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
    import json
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

def test_recovery_replay_blocked_by_pending_directives(game, monkeypatch):
    """恢复重放与正常路同守门：pending 拟旨未核定不得推进（cmr S7 r8 codex）。

    跳过守门的话恢复期大臣新拟的旨随推进孤儿在旧回合——正常路会拦。
    """
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    # 恢复期大臣拟旨（pending 待准驳）
    db.add_directive(state, None, "请拨内帑", source="minister", status="pending")

    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(ValueError):
        sess.resolve_turn()
    assert state.turn == turn  # 未推进，拟旨不孤儿

def test_skip_refused_at_front_half_done(game):
    """#1274 r1：decree.advance_without_edict 空壳已删；跳过结算的快路名缺席。

    FRONT_HALF_DONE 恢复/亲裁由 session.resolve_turn 真缝承担（settling 恢复 /
    awaiting 幂等返回决策），不再经独立退朝壳拒绝。
    """
    from ming_sim.decree import pre_settle

    db, state, content = game
    turn = state.turn
    pre_settle(state, db, content=content)
    # 前半落账不推进月份；财政落账/恢复另由本文件真实收尾案证明。
    assert state.turn == turn

def test_draft_mutators_frozen_at_front_half_done(game, monkeypatch):
    """FRONT_HALF_DONE 冻结 draft/诏书变更器（ship-pre r1 codex）。

    恢复窗口新增/确认的 draft 会被 mark_directives_issued 连带标 issued，
    而重放 delta 不含它们=幽灵颁布。
    """
    from ming_sim.session import GameSession
    db, state, content = game
    state.turn_phase = "settling"

    sess = _recovery_session(db, state, content, monkeypatch)
    for call in (
        lambda: sess.add_directive("新草案"),
        lambda: sess.update_directive(1, "改"),
        lambda: sess.delete_directive(1),
        # #1341：set_decree 已删；冻结面只覆盖逐道草案变更器 + write_decree
        lambda: sess.write_decree(),
    ):
        with pytest.raises(ValueError):
            call()
