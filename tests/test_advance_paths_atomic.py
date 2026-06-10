"""S7 (ADR 0008 PR1) — 三条推进回合写路径统一 atomic 事务包裹 + 恢复入口消费。

决定 2：任何推进回合的写序列(正常 settle / simulator-fallback / advance_without_edict)
全有或全无——整体包 atomic，崩在中途整体回滚、内存从 DB 重载、相位/回合不前进。
决定 3：跨进程恢复入口(session.resolve_turn)在 settling 态分流——有 ready context 直入
apply(不重跑贵的 simulator/extractor)；无则重跑推演(验收③)。
决定 4：事务内 LLM 回调失败沿用降级，不触发回滚(章节记忆/结局总评内部已自吞)。

用 conftest 的 game fixture(活存档副本，连接走 _SuspendableConnection factory，atomic 可用)。
"""

from __future__ import annotations

import sqlite3

import pytest

import ming_sim.decree as decree_mod
from ming_sim.decree import advance_without_edict, persist_resolve_context, settle_with_delta


def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def _log_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM turn_logs WHERE turn=?", (turn,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# 路 3：advance_without_edict 整体 atomic
# ---------------------------------------------------------------------------

def test_advance_without_edict_atomic(game, monkeypatch):
    """advance_without_edict 中途崩(record_log 之后、推进之前注入异常)→ 全回滚：
    财政/日志都不留、turn 未推进、内存 state 与 DB 同源(ADR 0008 决定 2/3)。"""
    db, state, content = game
    turn = state.turn
    before_ledger = _ledger_count(db, turn)
    before_log = _log_count(db, turn)
    before_phase = state.turn_phase

    # 在 advance 写序列中途崩：clear_resolve_context 在 record_log 之后、next_period 之前。
    def _boom(*a, **k):
        raise RuntimeError("advance boom")
    monkeypatch.setattr(db, "clear_resolve_context", _boom)

    with pytest.raises(RuntimeError, match="advance boom"):
        advance_without_edict(state, db, content=content)

    # 用新连接读盘：写序列随事务整体回滚。
    other = sqlite3.connect(db.path)
    try:
        on_disk_ledger = other.execute(
            "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)).fetchone()[0]
        on_disk_log = other.execute(
            "SELECT COUNT(*) FROM turn_logs WHERE turn=?", (turn,)).fetchone()[0]
        on_disk_turn = other.execute(
            "SELECT turn FROM game_state").fetchone()[0]
    finally:
        other.close()
    assert on_disk_ledger == before_ledger
    assert on_disk_log == before_log
    assert on_disk_turn == turn  # 回合未推进
    # 内存与 DB 同源(reload)：turn 未前进、相位未变。
    assert state.turn == turn
    assert state.turn_phase == before_phase
    assert not db.conn.in_transaction


# ---------------------------------------------------------------------------
# 路 2：simulator-fallback 整体 atomic
# ---------------------------------------------------------------------------

def _drive_fallback(db, state, content, monkeypatch):
    """stub 驱动真实 resolve_directives，令 simulator 抛错走 fallback 分支。"""
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)

    def _stub_sim(*a, **k):
        raise RuntimeError("simulated simulator crash")
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _stub_sim)

    return decree_mod.resolve_directives(
        state, db, None, None, [1], "减赋诏",
        content=content, registry=None,
    )


def test_fallback_branch_atomic(game, monkeypatch):
    """simulator-fallback 分支中途崩(apply_issue_inertia_and_ongoing 抛)→ 全回滚：
    record_log/turn_report 都不留、turn 未推进、内存与 DB 同源(ADR 0008 决定 2)。"""
    db, state, content = game
    # pre_settle 在 resolve_directives 早期跑(自有 atomic)，先让它走完落 settling；
    # 然后 fallback 分支跑推进尾，在 inertia 处注入崩溃。
    turn = state.turn

    def _boom(*a, **k):
        raise RuntimeError("fallback inertia boom")
    monkeypatch.setattr(decree_mod, "apply_issue_inertia_and_ongoing", _boom)

    before_report = db.conn.execute(
        "SELECT COUNT(*) FROM turn_reports WHERE turn=?", (turn,)).fetchone()[0]

    with pytest.raises(RuntimeError, match="fallback inertia boom"):
        _drive_fallback(db, state, content, monkeypatch)

    other = sqlite3.connect(db.path)
    try:
        on_disk_report = other.execute(
            "SELECT COUNT(*) FROM turn_reports WHERE turn=?", (turn,)).fetchone()[0]
        on_disk_turn = other.execute("SELECT turn FROM game_state").fetchone()[0]
    finally:
        other.close()
    assert on_disk_report == before_report  # fallback 写序列回滚
    assert on_disk_turn == turn  # 回合未推进
    assert state.turn == turn  # 内存与 DB 同源
    assert not db.conn.in_transaction


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
    extracted = {"metric_delta": {"国库": 30}}
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


def test_recovery_entry_consumes_ready_context(game, monkeypatch):
    """settling + ready context（手工 persist 一份非空 delta）→ resolve_turn 直入 apply：
    不重跑 simulator/extractor（stub 成抛错断言未被调）、context 清掉、turn+1（ADR 0008 决定 3）。"""
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    extracted = {"metric_delta": {"国库": 30}}
    # 模拟「崩在 settle 之前、extractor 已产出并 persist」：pre_settle 已落 settling。
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    dm.persist_resolve_context(
        db, turn, extracted,
        decree_text="减赋诏", narrative="已存邸报……",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    # 贵调用 stub 成抛错：被调到即测试红。
    def _must_not_run(*a, **k):
        raise AssertionError("恢复直入 apply 不应重跑 simulator/extractor")
    monkeypatch.setattr(dm, "simulate_season_with_payload", _must_not_run)
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _must_not_run)

    sess = _recovery_session(db, state, content, monkeypatch)
    result = sess.resolve_turn()

    assert result.awaiting is False
    assert state.turn == turn + 1  # 完整推进
    assert db.get_resolve_context(turn) is None  # settle 尾清掉
    assert state.turn_phase == TurnPhase.ISSUED.value


def test_recover_after_simulation_crash_can_resettle(game, monkeypatch):
    """验收③：真跑 pre_settle（settling 落库）→ 模拟崩在推演期间（无 ready context）→
    恢复（resolve_turn 走 fallthrough 重跑推演）→ 能重新推演并完整结算推进（turn+1、财政不二跑）。

    崩于推演/抽取期间的窗口里 LLM 产出本就没持久化（resolve_context 无 ready）——重跑是
    唯一选择（ADR 0008 决定 3）。pre_settle 的 settling 守门保证前半段不二跑。"""
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    # 真跑前半段：财政落账 + settling 相位提交。模拟「崩在推演期间」——无 resolve_context。
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.get_resolve_context(turn) is None  # 推演产出未持久化
    ledger_after_pre = _ledger_count(db, turn)
    assert ledger_after_pre > 0

    # 恢复：simulator/extractor 重跑成功（stub）。无决策块 → 直接续跑结算。
    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")

    def _resim(*a, **k):
        return "重新推演后的邸报，无决策块。", (k.get("simulator_payload") or {})
    monkeypatch.setattr(dm, "simulate_season_with_payload", _resim)

    def _reextract(*a, **k):
        return {"metric_delta": {"国库": 10}}, "raw-out", "raw-in"
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _reextract)

    sess = _recovery_session(db, state, content, monkeypatch)
    # 需要一条 draft 才能走正常 resolve_directives（fallthrough 路径）。
    db.add_directive(state, None, "减赋", source="player", status="draft")
    result = sess.resolve_turn(decree="补颁诏")

    assert result.awaiting is False
    assert state.turn == turn + 1  # 重新推演后完整结算推进
    assert state.turn_phase == TurnPhase.ISSUED.value
    # 财政不二跑：settling 守门跳过 pre_settle 前半段。
    assert _ledger_count(db, turn) == ledger_after_pre
    assert db.get_resolve_context(turn) is None  # settle 尾清掉
