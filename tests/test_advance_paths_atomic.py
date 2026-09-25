"""S7 (ADR 0008 PR1) — 三条推进回合写路径统一 atomic 事务包裹 + 恢复入口消费。

决定 2：任何推进回合的写序列（正常 settle / 无旨 session.advance_without_decree）
全有或全无——整体包 atomic，崩在中途整体回滚、内存从 DB 重载、相位/回合不前进。
玩家 settling 入口已改走 ADR 0157 月链；此处保留共享旧核及 driver 的原子事务契约。
决定 4：事务内 LLM 回调失败沿用降级，不触发回滚(章节记忆/结局总评内部已自吞)。

用 conftest 的 game fixture(活存档副本，连接走 _SuspendableConnection factory，atomic 可用)。

注：本文件设置/断言 turn_phase 时故意用 raw 字符串(如 "settling"/"awaiting_decision")而非
TurnPhase.X.value——它们 pin 的是**落盘字符串值本身**，有意 enum 无关：枚举重命名而落盘值
漂移时这些断言应响亮失败。S4 把生产代码相位比较统一到 TurnPhase enum，测试侧落盘断言不跟随。
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

import ming_sim.decree as decree_mod
import ming_sim.issues as I
from ming_sim.decree import persist_resolve_context, settle_with_delta
from tests.dossier_test_helpers import TYPED_COVERT_TASK


def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def _log_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM turn_logs WHERE turn=?", (turn,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# 路 3：无旨 session.advance_without_decree 整体 atomic
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 路 1：settle_with_delta 整体 atomic —— 闭合 save_state→clear 崩溃窗口（S2+S3 defer）
# ---------------------------------------------------------------------------

def test_settle_crash_after_savestate_before_clear_rolls_back(game, monkeypatch, tmp_path):
    """注入异常于 save_state 之后、clear_resolve_context 之前（seam：monkeypatch
    db.clear_resolve_context 抛错）→ 整体回滚：turn 未推进、resolve_context 仍在（可重试）、
    内存 state 与 DB 同源（ADR 0008 S2+S3 codex R2 defer→S7，崩溃窗口真正闭合）。

    代码异常经 settle 的 atomic 上抛后被包成 SettlementAbort(stage="settle")（决定 6）；
    本测试聚焦的是「整体回滚 + context 仍在」这个崩溃点不变式。错误包隔离到 tmp_path。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    extracted = {"region_delta": {"shanxi": {"unrest": 1}}}
    persist_resolve_context(
        db, turn, extracted,
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    assert db.get_resolve_context(turn) is not None

    # clear 是 settle 写序列最后一笔（next_period + save_state 之后）。让它抛——
    # 包 atomic 前：save_state 已 commit（turn 已推进、context 残留）；包 atomic 后整体回滚。
    orig_clear = db.clear_resolve_context

    def _boom_clear(t):
        # 抛错前证明窗口真实：next_period/save_state 已发生（clear 在其后），
        # 否则 clear 被挪到推进写之前测试也照样绿（cmr S7 r1 codex）。
        assert state.turn == turn + 1, "clear 必须在 next_period/save_state 之后"
        raise RuntimeError("clear boom")
    monkeypatch.setattr(db, "clear_resolve_context", _boom_clear)

    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort) as ei:
        settle_with_delta(state, db, extracted, before_turn=turn, content=content)
    assert ei.value.stage == "settle"
    assert isinstance(ei.value.__cause__, RuntimeError)

    monkeypatch.setattr(db, "clear_resolve_context", orig_clear)

    # 整体回滚：用新连接读盘，turn 未推进、context 仍在。
    other = sqlite3.connect(db.path)
    try:
        on_disk_turn = other.execute("SELECT turn FROM game_state").fetchone()[0]
    finally:
        other.close()
    assert on_disk_turn == turn  # 回合未推进（save_state 随回滚消失）
    assert db.get_resolve_context(turn) is not None  # context 仍在，可重试
    # 内存与 DB 同源（reload）：turn 未前进。
    assert state.turn == turn
    assert not db.conn.in_transaction


def test_settle_code_exception_writes_pack_and_aborts(game, monkeypatch, tmp_path):
    """settle 内注入代码异常（apply_score_extraction 抛 RuntimeError）→ SettlementAbort
    (stage="settle")、错误包五件齐、DB 全回滚、内存已 reload（ADR 0008 决定 2/3/6，S6 defer F1）。"""
    from pathlib import Path
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    extracted = {"metric_delta": {"民心": -4}}  # 国库由 economy_accounts 派生不可直写；民心负向不撞 clamp
    persist_resolve_context(
        db, turn, extracted,
        decree_text="减赋诏", narrative="本月邸报……",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    # apply_score_extraction 是 settle 第一笔写（delta_applier=None 回退到它）。
    def _boom(*a, **k):
        raise RuntimeError("apply boom")
    monkeypatch.setattr(decree_mod, "apply_score_extraction", _boom)

    with pytest.raises(SettlementAbort) as ei:
        settle_with_delta(state, db, extracted, before_turn=turn, content=content)

    assert ei.value.stage == "settle"
    assert ei.value.turn == turn
    assert isinstance(ei.value.__cause__, RuntimeError)

    # 错误包五件齐
    packs = list((tmp_path / "error_packs").iterdir())
    assert len(packs) == 1
    pack = packs[0]
    for name in ("traceback.txt", "delta.json", "resolve_context.json",
                 "save_backup.db", "manifest.json"):
        assert (pack / name).exists(), f"缺 {name}"
    # delta.json 是本回合 extracted（非占位）
    import json
    assert json.loads((pack / "delta.json").read_text(encoding="utf-8")) == extracted

    # DB 全回滚：turn 未推进、context 仍在
    other = sqlite3.connect(db.path)
    try:
        on_disk_turn = other.execute("SELECT turn FROM game_state").fetchone()[0]
    finally:
        other.close()
    assert on_disk_turn == turn
    assert db.get_resolve_context(turn) is not None
    # 内存已 reload（同源）
    assert state.turn == turn
    assert not db.conn.in_transaction


# ---------------------------------------------------------------------------
# B. 恢复入口消费（决定 3）：settling + ready context → 直入 apply，不重跑贵调用
# ---------------------------------------------------------------------------

def _recovery_session(db, state, content, monkeypatch):
    """装一个最小 GameSession（__new__ 跳过重型 __init__），供 resolve_turn 恢复分流。"""
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    monkeypatch.setattr(session_mod, "MinisterRegistry", lambda *a, **k: object())
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
        write_gate=threading.Lock(),
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


def test_submit_event_decision_binds_from_candidate_snapshot_without_event_id(game, monkeypatch):
    """#389：simulator 漏写 event_id 时，事件亲裁仍从权威候选快照确定性绑定并持久化。"""
    import json
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    turn = state.turn
    event_id = "mao_wenlong"
    db.save_resolve_context(
        turn,
        "测试诏书",
        "邸报正文未回显事件编号。",
        {"candidate_events": [{"id": event_id, "title": "毛文龙裁断"}]},
        secret_orders=[],
        relevant_memories=[],
    )
    db.save_pending_decisions(turn, [{
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

    # #1589：绑定发生在 desk 读出口（prepare_rescript_prewrite），键仍取绑定前
    # 的 decision:{turn}:0 投影——event_id 是否已绑定不改变 decision_key 形状。
    d_key = db.list_rescript_desk(turn)[0]["decision_key"]
    sess.submit_hitl_choices(
        [{"decision_key": d_key, "label": "留", "hint": "暂稳东江", "note": "姑留观后效"}],
        write_gate=threading.Lock(),
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


def test_hitl_ready_replay_retry_keeps_original_event_choice(game, monkeypatch):
    """cmr Gate2 r4 Finding2 / #1589 最短 ready-replay tracer：ready-context 重试时
    phase2 走「恢复重放」、**忽略**重交的亲裁选择（重放崩溃前真源的旧选择 delta）。
    submit_hitl_choices（keyed）此刻绝不能用新选择覆写 event_triggers.choice_json——
    否则事件账记新选择 B、而重放的世界状态来自旧选择 A，durable 账实不符。
    断言：重试改投不同选择（仍显式携原 decision_key）后，事件账仍是原选择。"""
    import json
    import ming_sim.decree as dm
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    turn = state.turn
    event_id = "mao_wenlong"
    # 第一次 submit 已把原选择 A=「斩」记进事件账
    db.record_event_decision_choice(state, event_id, {"label": "斩", "note": "原裁断"}, commit=True)
    # phase2 已抽取并 persist ready delta、settle 曾 abort → ready context
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -3}},
        decree_text="HITL诏", narrative="裁断后邸报",
        simulator_payload={"candidate_events": [{"id": event_id, "title": "毛文龙裁断"}]},
        secret_orders=[], relevant_memories=[],
    )
    assert db.get_resolve_context(turn).get("extracted") is not None
    db.save_pending_decisions(turn, [{
        "event_id": event_id, "title": "毛文龙裁断", "context": "c",
        "options": [{"label": "斩", "hint": ""}, {"label": "留", "hint": ""}],
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
    sess.last_decree = "HITL诏"
    sess.agno_db = None
    sess.llm_config = None
    sess.content = content
    sess.registry = None

    # 重试改投「留」（B，与原 A 不同，显式携 key）——ready-replay 应跳过覆写
    d_key = db.list_rescript_desk(turn)[0]["decision_key"]
    sess.submit_hitl_choices(
        [{"decision_key": d_key, "label": "留", "note": "改裁"}],
        write_gate=threading.Lock(),
    )

    row = db.conn.execute(
        "SELECT choice_json FROM event_triggers WHERE event_id=?", (event_id,)).fetchone()
    assert json.loads(row["choice_json"]) == {"label": "斩", "note": "原裁断"}, \
        "ready-replay 重试不得用新选择覆写事件账"


def test_submit_decisions_does_not_overwrite_already_decided_rows(game, monkeypatch):
    """#1418 r2 / #1589：phase2 失败后续跑——已 decided 行不得被空/异载荷覆写。

    崩溃安全先写后跑：choice 已落 status=decided，但 extracted 未就绪（非 ready_replay）。
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
    # phase1 HITL 暂停上下文（无 extracted）——与真实 awaiting 存档同形
    db.save_resolve_context(
        turn, "HITL诏", "待续邸报", {"candidate_events": []},
        secret_orders=[], relevant_memories=[],
    )
    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx.get("extracted") is None
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
    assert sess.submit_hitl_choices([], write_gate=threading.Lock()) == "ok"
    assert db.list_pending_decisions(turn)[0]["choice"] == original

    # 复位 awaiting 再试异载荷（模拟 phase2 再次失败后的续跑）
    state.turn_phase = "awaiting_decision"
    db.save_state(state)
    # ② #1589：空 desk + 非空无键异载荷整批拒，不静默吞掉——phase2 不重入
    with pytest.raises(ValueError, match="decision_key"):
        sess.submit_hitl_choices(
            [{"label": "留", "note": "改裁"}], write_gate=threading.Lock(),
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
        [{**option, "decision_key": d_key}], write_gate=threading.Lock(),
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
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    # 恢复期大臣拟旨（pending 待准驳）
    db.add_directive(state, None, "请拨内帑", source="minister", status="pending")

    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(ValueError, match="核定"):
        sess.resolve_turn()
    assert state.turn == turn  # 未推进，拟旨不孤儿
    db.clear_resolve_context(turn)


def test_skip_refused_at_front_half_done(game):
    """#1274 r1：decree.advance_without_edict 空壳已删；跳过结算的快路名缺席。

    FRONT_HALF_DONE 恢复/亲裁由 session.resolve_turn 真缝承担（settling 恢复 /
    awaiting 幂等返回决策），不再经独立退朝壳拒绝。
    """
    import inspect

    import ming_sim.decree as decree_mod
    from ming_sim.decree import pre_settle

    assert not hasattr(decree_mod, "advance_without_edict")
    assert "def advance_without_edict" not in inspect.getsource(decree_mod)

    db, state, content = game
    turn = state.turn
    pre_settle(state, db, content=content)
    rows_before = _ledger_count(db, turn)
    # settling 已提交前半：turn 不因「缺壳」而推进；财政行保留
    assert state.turn == turn
    assert _ledger_count(db, turn) == rows_before


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
        with pytest.raises(ValueError, match="结算|亲裁"):
            call()




def test_settle_reload_failure_propagates_raw_not_abort(game, monkeypatch, tmp_path):
    """settle 崩+回滚后 reload 自身再炸 → 原异常裸传播(带 __cause__=reload 异常),
    **不包 SettlementAbort 不写错误包**——内存仍脏时向玩家宣传「可重试」是误导,
    写包也会基于脏态(b12a60e 原语义;cmr S4 r1,2/2:helper 重构后被外层 except
    二次捕获误包装)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    extracted = {"metric_delta": {"民心": -1}}
    persist_resolve_context(
        db, turn, extracted,
        decree_text="减赋诏", narrative="本月邸报……",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    def _boom(*a, **k):
        raise RuntimeError("apply boom")
    monkeypatch.setattr(decree_mod, "apply_score_extraction", _boom)

    def _reload_boom(*a, **k):
        raise OSError("reload boom")
    monkeypatch.setattr(decree_mod, "reload_state_from_db", _reload_boom)

    with pytest.raises(RuntimeError, match="apply boom") as ei:
        settle_with_delta(state, db, extracted, before_turn=turn, content=content)

    assert isinstance(ei.value.__cause__, OSError)  # reload 异常链上保留
    packs = list((tmp_path / "error_packs").glob("turn*")) if (tmp_path / "error_packs").exists() else []
    assert packs == []  # 不基于脏态写包
