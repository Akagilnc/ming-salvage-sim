"""S4 — pre_settle 自成事务 + settling 完成相位 + begin_turn 白名单（ADR 0008 决定 3 第二条）。

pre_settle（暂存动作 commit + 固定财政 + auto_trigger + auto_submit_due_secret_orders）
整体包成自己的单事务：完成时同事务内落中间相位 settling；崩在内部=全回滚=相位未变=
重进时干净重跑前半段。settling 加进 begin_turn 保活白名单，重载不被重置回 summoning。

用 conftest 的 game fixture（活存档副本，连接走 _SuspendableConnection factory，atomic 可用）。

注：本文件设置/断言 turn_phase 时故意用 raw 字符串（如 "settling"/"awaiting_decision"）而非
TurnPhase.X.value——pin 的是**落盘字符串值本身**，有意 enum 无关：枚举重命名而落盘值漂移时
应响亮失败。S4 把生产代码相位比较统一到 TurnPhase enum，测试侧落盘断言不跟随。
"""

from __future__ import annotations

import sqlite3

import pytest

import ming_sim.decree as decree_mod
from ming_sim.decree import pre_settle


def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def test_crash_reload_at_settling_no_double_fiscal_tick(game):
    """pre_settle 完成（phase=settling 已落盘）→ 模拟崩溃重载（新开 GameDB 读盘）→
    重进 pre_settle 幂等守门直接 return，economy_ledger 不二次增行（ADR 0008 验收测试①）。"""
    from ming_sim.db import GameDB

    db, state, content = game
    turn = state.turn

    auto = pre_settle(state, db)
    assert isinstance(auto, list)
    assert state.turn_phase == "settling"
    after_first = _ledger_count(db, turn)
    assert after_first > 0  # 财政确已落
    db.conn.close()

    # 崩溃重载：新开 GameDB（落盘的 phase=settling 读回），重进 pre_settle 不重跑前半段。
    db2 = GameDB(db.path, content)
    try:
        state2 = db2.load_state()
        assert state2.turn_phase == "settling"  # 同事务落库，崩溃前已持久
        auto2 = pre_settle(state2, db2)
        assert auto2 == []  # 幂等守门：直接 return
        assert _ledger_count(db2, turn) == after_first  # 财政只落一次
    finally:
        db2.conn.close()


def test_settling_survives_begin_turn_phase_whitelist(game, monkeypatch):
    """phase=settling 重载走 begin_turn → 保活不被重置回 summoning（白名单生效，
    ADR 0008 S4；白名单外的相位重载即被重置，守门失效）。"""
    from ming_sim.session import GameSession, TurnPhase
    import ming_sim.session as session_mod

    db, state, content = game
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    # 用 __new__ 跳过重型 __init__（agno/registry/LLM），只装 begin_turn 需要的协作者；
    # 重型协作者打桩（registry 建 agent / auto_save / office 同步均与白名单无关）。
    monkeypatch.setattr(session_mod, "MinisterRegistry", lambda *a, **k: object())
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl", lambda *a, **k: None)
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.content = content
    sess.llm_config = None
    sess.agno_db = None
    monkeypatch.setattr(GameSession, "auto_save", lambda self, tag: None)

    snap = sess.begin_turn()

    assert snap.phase == TurnPhase.SETTLING.value
    assert sess.state.turn_phase == TurnPhase.SETTLING.value
    # 落盘也仍是 settling（未被重置写回 summoning）
    assert db.load_state().turn_phase == TurnPhase.SETTLING.value


def test_due_secret_order_submission_rolls_back_on_pre_settle_crash(saved_game, monkeypatch):
    """auto_submit_due_secret_orders 挪进 pre_settle 事务（ADR 0008 S4）：到期密令本应
    转 pending_review，但 pre_settle 内部崩溃 → 该状态翻转随事务回滚，order 仍是 active。
    用 saved_game：依赖玩过存档里到期的 secret_order，fresh seed 无（#5）。"""
    db, state, content = saved_game
    turn = state.turn
    # 让某 active 密令本回合到期（due_turn <= 当前 turn），auto_submit 应将其转 pending_review。
    db.conn.execute(
        "UPDATE secret_orders SET status='active', due_turn=? WHERE id=2", (turn,))
    db.conn.commit()
    assert db.conn.execute(
        "SELECT status FROM secret_orders WHERE id=2").fetchone()[0] == "active"

    # 在 auto_submit 之后的相位写处崩：用 save_state 抛错，验前面 auto_submit 的写回滚。
    orig_save = db.save_state
    def _boom_save(st):
        raise RuntimeError("phase-write boom")
    monkeypatch.setattr(db, "save_state", _boom_save)

    with pytest.raises(RuntimeError, match="phase-write boom"):
        pre_settle(state, db)

    monkeypatch.setattr(db, "save_state", orig_save)
    # 用新连接读盘：密令呈递随事务整体回滚，仍是 active（没有事务外散写）。
    other = sqlite3.connect(db.path)
    try:
        st = other.execute("SELECT status FROM secret_orders WHERE id=2").fetchone()[0]
    finally:
        other.close()
    assert st == "active"


def test_driver_pre_settle_same_transaction_semantics(game, monkeypatch):
    """driver 路径（直接调 pre_settle）同样获得自事务语义：内部崩溃 → 财政回滚、phase 未推进
    （ADR 0004/0008，driver 与真实流程同核同位）。"""
    import ming_sim.decree as dm
    db, state, content = game
    turn = state.turn
    before_phase = state.turn_phase
    before_ledger = _ledger_count(db, turn)

    def _boom(*a, **k):
        raise RuntimeError("driver pre_settle boom")
    monkeypatch.setattr(dm, "auto_trigger_seed_issues", _boom)

    # driver.run_settle 内部第一步即 pre_settle；这里直接调 pre_settle 等价（同函数同核）。
    with pytest.raises(RuntimeError, match="driver pre_settle boom"):
        pre_settle(state, db)

    other = sqlite3.connect(db.path)
    try:
        on_disk = other.execute(
            "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    finally:
        other.close()
    assert on_disk == before_ledger
    assert state.turn_phase == before_phase != "settling"
    assert not db.conn.in_transaction


def test_crash_inside_pre_settle_no_missing_fiscal(game, monkeypatch):
    """pre_settle 内部注入异常（auto_trigger 抛）→ 异常透传、economy_ledger 无半行、
    phase 仍是入口态（非 settling）——整体回滚干净（ADR 0008 验收测试②）。"""
    db, state, content = game
    turn = state.turn
    before_phase = state.turn_phase
    before_ledger = _ledger_count(db, turn)

    # auto_trigger_seed_issues 在固定财政落账之后调；让它抛，验前面已落的财政被回滚。
    def _boom(*a, **k):
        raise RuntimeError("auto_trigger boom")
    monkeypatch.setattr(decree_mod, "auto_trigger_seed_issues", _boom)

    with pytest.raises(RuntimeError, match="auto_trigger boom"):
        pre_settle(state, db)

    # 财政落账随回滚消失（用新连接读盘，验真回滚到磁盘态）
    other = sqlite3.connect(db.path)
    try:
        on_disk = other.execute(
            "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
        ).fetchone()[0]
    finally:
        other.close()
    assert on_disk == before_ledger
    # 内存 phase 未推进到 settling（pre_settle 尾部才写，异常在此前）
    assert state.turn_phase == before_phase
    assert state.turn_phase != "settling"
    # 连接干净，无悬挂事务
    assert not db.conn.in_transaction


# ---------------------------------------------------------------------------
# cmr S4 r1 修复回归（F1 settling 复位 / F2 sticky / F3 skip 路守门）
# ---------------------------------------------------------------------------

def test_two_consecutive_driver_settles_both_get_fiscal_tick(game):
    """driver 连续结算两回合，第二回合财政照常落账（cmr S4 r1 F1，3/3 critical）。

    settling 推进回合后不复位的话，第二回合 pre_settle 被守门跳过=
    此后每月财政/暂存/密令全静默丢。
    """
    from driver import run_settle
    db, state, content = game
    t1 = state.turn
    run_settle(db, state, content, {})
    t2 = state.turn
    assert t2 == t1 + 1
    assert state.turn_phase != "settling"  # 推进后复位

    run_settle(db, state, content, {})
    assert state.turn == t2 + 1
    rows_t2 = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (t2,)).fetchone()[0]
    assert rows_t2 > 0  # 第二回合财政 tick 真跑了


def test_enter_review_does_not_clobber_settling(game):
    """enter_review 不得抹掉崩溃保活的 settling（cmr S4 r1 F2）。

    抹成 reviewing 后 pre_settle 守门失效=同回合二次财政 tick。
    """
    from ming_sim.session import GameSession, TurnPhase
    db, state, content = game
    state.turn_phase = "settling"
    db.save_state(state)

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state

    sess.enter_review()
    assert state.turn_phase == "settling"

    sess.back_to_summoning()
    assert state.turn_phase == "settling"


def test_advance_without_edict_refused_after_settling(game):
    """#1274 r1：空壳已删；settling 恢复归 session.resolve_turn，不再经独立退朝壳拒绝。"""
    import inspect

    import ming_sim.decree as decree_mod
    from ming_sim.decree import pre_settle

    assert not hasattr(decree_mod, "advance_without_edict")
    assert "def advance_without_edict" not in inspect.getsource(decree_mod)

    db, state, content = game
    turn = state.turn
    pre_settle(state, db)  # 真跑：落财政 + settling
    rows_after_pre = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    assert rows_after_pre > 0
    assert state.turn_phase == "settling"
    assert state.turn == turn
    rows_final = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    assert rows_final == rows_after_pre


# ---------------------------------------------------------------------------
# cmr S4 r2 修复回归（F1 第三推进尾 / F2 HITL 相位耐崩+守门）
# ---------------------------------------------------------------------------

def _drive_resolve_directives(db, state, content, monkeypatch, *, simulator_behavior):
    """stub 驱动真实 resolve_directives。simulator_behavior: 'fail' / 'decision'。"""
    import ming_sim.decree as decree_mod

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )

    decision_narrative = (
        "本月邸报正文。\n<<DECISION>>"
        '{"title": "辽东战和", "context": "皇太极请款", "options": '
        '[{"label": "战"}, {"label": "和"}]}'
        "<<END>>"
    )

    def _stub_sim(*a, **k):
        if simulator_behavior == "fail":
            raise RuntimeError("simulated simulator crash")
        return decision_narrative, k.get("simulator_payload") or {}
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _stub_sim)

    return decree_mod.resolve_directives(
        state, db, None, None, [1], "减赋诏",
        content=content, registry=None,
    )


def test_simulator_fallback_tail_resets_settling(game, monkeypatch):
    """第三条推进尾（simulator-fallback）也要复位 settling（cmr S4 r2 F1）。

    不复位的话推进后的新回合持久化为 settling，下回合前半段被守门跳过
    ——而那个月的财政/暂存/密令从未做过。
    """
    db, state, content = game
    turn = state.turn
    res = _drive_resolve_directives(db, state, content, monkeypatch,
                                    simulator_behavior="fail")
    assert res.awaiting is False
    assert state.turn == turn + 1
    assert state.turn_phase == "summoning"
    row = db.conn.execute("SELECT turn_phase FROM game_state").fetchone()
    assert row[0] == "summoning"  # 落库的也复位


def test_hitl_pause_persists_awaiting_phase_durably(game, monkeypatch):
    """HITL 暂停时 AWAITING_DECISION 随决策点同笔持久化（cmr S4 r2 F2a）。

    靠 session 事后另笔写的话，崩在窗口里 DB 停在 settling 而决策已存，
    web submit_decisions 只认 AWAITING=恢复死路。
    """
    db, state, content = game
    turn = state.turn
    res = _drive_resolve_directives(db, state, content, monkeypatch,
                                    simulator_behavior="decision")
    assert res.awaiting is True
    assert state.turn == turn  # 回合未推进
    row = db.conn.execute("SELECT turn_phase FROM game_state").fetchone()
    assert row[0] == "awaiting_decision"  # DB 持久化的相位，非内存
    db.clear_resolve_context(turn)


def test_pre_settle_guard_covers_awaiting_decision(game):
    """守门扩到 AWAITING_DECISION：该相位只可能在 pre_settle 已提交后出现（cmr S4 r2 F2b）。

    只认 settling 的话，HITL 后重发 issue 守门 miss=同回合二次财政 tick。
    """
    from ming_sim.decree import pre_settle
    db, state, content = game
    turn = state.turn
    state.turn_phase = "awaiting_decision"
    rows_before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]

    out = pre_settle(state, db)

    assert out == []
    rows_after = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    assert rows_after == rows_before  # 前半段没有二跑


# ---------------------------------------------------------------------------
# cmr S4 r3 修复回归（FRONT_HALF_DONE_PHASES 集中化）
# ---------------------------------------------------------------------------

def test_sticky_phases_cover_awaiting_decision(game):
    """粘滞守门覆盖 awaiting_decision（cmr S4 r3 F1）。

    CLI 重载于 awaiting 时 enter_review 抹相位=守门 miss 双 tick+决策搁浅。
    """
    from ming_sim.session import GameSession
    db, state, content = game
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state

    sess.enter_review()
    assert state.turn_phase == "awaiting_decision"
    sess.back_to_summoning()
    assert state.turn_phase == "awaiting_decision"


def test_advance_without_edict_refused_at_awaiting(game):
    """#1274 r1：空壳已删；awaiting 由 session.resolve_turn 幂等返回决策，不经退朝壳拒绝。"""
    import inspect

    import ming_sim.decree as decree_mod
    from ming_sim.decree import pre_settle
    from ming_sim.session import GameSession

    assert not hasattr(decree_mod, "advance_without_edict")
    assert "def advance_without_edict" not in inspect.getsource(decree_mod)

    db, state, content = game
    turn = state.turn
    pre_settle(state, db)  # 真落财政 + settling
    state.turn_phase = "awaiting_decision"  # HITL 暂停后的相位
    db.save_state(state)
    rows_before = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    result = sess.advance_without_decree()
    assert result is not None and result.awaiting is True

    rows_after = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
    assert rows_after == rows_before
    assert state.turn == turn
    assert state.turn_phase == "awaiting_decision"


def test_resolve_turn_idempotent_at_awaiting(game, monkeypatch):
    """resolve_turn 在 awaiting 态幂等返回已存决策，不二跑 simulator（cmr S4 r3 F3）。

    二跑会覆盖 pending_decisions 或绕过亲裁直接结算。
    """
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession
    db, state, content = game
    state.turn_phase = "awaiting_decision"
    db.save_state(state)
    db.save_pending_decisions(state.turn, [{
        "title": "辽东战和", "context": "皇太极请款",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])

    def _must_not_run(*a, **k):
        raise AssertionError("resolve_directives 不应被调")
    monkeypatch.setattr(session_mod, "resolve_directives", _must_not_run)

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state

    res = sess.resolve_turn()
    assert res.awaiting is True
    assert res.decisions
    db.clear_resolve_context(state.turn)


def test_guarded_early_return_does_not_consume_pending(game):
    """守门早退不消费暂存动作（cmr S7 r5 改约）。

    所有权规则：推进回合的终端写路（settle/advance/fallback）各自在 atomic 内 commit；
    早退路事务外 commit 会造成跨事务半写。孤儿防线由终端路测试接管
    （test_advance_paths_atomic 的 settle 回滚/HITL 重抽/fallback/advance 各条）。"""
    from ming_sim.decree import pre_settle
    from tests.test_pending_actions import _active_minister_name
    db, state, content = game
    name = _active_minister_name(db, content)

    pre_settle(state, db)  # 落 settling
    # 崩溃重载后玩家召对新 stage 的动作
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "守门后标题", "new_content": "x", "deadline_months": 0})

    out = pre_settle(state, db)  # 守门早退：不消费，留给终端路在 atomic 内落库

    assert out == []
    statuses = [r["status"] for r in db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=?", (state.turn,)).fetchall()]
    assert statuses and all(s == "pending" for s in statuses)


def test_write_decree_raises_at_awaiting_not_resolveresult(game):
    """write_decree(-> str) 在 awaiting 态响亮拒绝，不返回 ResolveResult（cmr S4 r4，3/3）。

    r3 的全局替换把守门误贴进了 write_decree——web 会把 dataclass 序列化进
    {"decree": ...}，terminal 把 repr 当诏书正文打印。
    """
    from ming_sim.session import GameSession
    db, state, content = game
    state.turn_phase = "awaiting_decision"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state

    with pytest.raises(ValueError, match="亲裁"):
        sess.write_decree()


def test_hitl_pause_crash_reloads_memory(game, monkeypatch):
    """HITL 暂停 atomic 崩溃后内存与 DB 同源（ship-pre r2，五事务块唯一漏 reload 的）。

    不 reload 的话内存留 awaiting/DB 回滚回 settling，进程内重试走 awaiting 幂等叉
    读到空决策=死胡同。
    """
    db, state, content = game
    turn = state.turn

    real_save = type(db).save_state
    calls = {"n": 0}
    def _boom_save(self, st):
        # pre_settle 尾的 save 照常；HITL 暂停块里的 save（phase=awaiting 时）炸
        if st.turn_phase == "awaiting_decision":
            raise RuntimeError("save_state crash in HITL pause")
        return real_save(self, st)
    monkeypatch.setattr(type(db), "save_state", _boom_save)

    with pytest.raises(RuntimeError, match="HITL pause"):
        _drive_resolve_directives(db, state, content, monkeypatch,
                                  simulator_behavior="decision")

    monkeypatch.setattr(type(db), "save_state", real_save)
    # 内存与 DB 同源：回滚后都应是 settling（pre_settle 已提交的真相）
    assert state.turn_phase == "settling"
    assert db.load_state().turn_phase == "settling"
    assert db.list_pending_decisions(turn) == []  # 决策随回滚消失


def test_placeholder_save_crash_rolls_back_settling(game, monkeypatch):
    """settling 相位与诏书占位同事务可见（PR #90 R1 codex P2）：占位写崩 → 前半段
    整体回滚（相位回 summoning、财政无残留、无 context 行）。

    否则崩在 pre_settle 提交后、占位落盘前的窗口 = 盘上 settling 而无 context 行，
    恢复 fallthrough 只能用 LLM 从草案重生诏书——玩家手编原诏蒸发。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    turn = state.turn
    before_ledger = _ledger_count(db, turn)

    def _boom(self, *a, **k):
        raise RuntimeError("placeholder save crash")
    monkeypatch.setattr(type(db), "save_resolve_context", _boom)

    with pytest.raises(RuntimeError, match="placeholder save crash"):
        decree_mod.resolve_directives(state, db, None, None, [1], "减赋诏",
                                      content=content, registry=None)

    monkeypatch.undo()
    assert state.turn_phase == "summoning"            # 内存已重载刷净
    assert db.load_state().turn_phase == "summoning"  # 盘上 settling 未泄漏
    assert _ledger_count(db, turn) == before_ledger   # 财政随占位一起回滚
    assert db.get_resolve_context(turn) is None       # 不留半截上下文
