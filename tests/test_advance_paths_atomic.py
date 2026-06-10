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
    # 真正咬住 reload：崩前 apply_fixed_period_flows 已直改内存 metrics(flows 直加)，
    # 回滚后 reload 必须把它刷回 DB 真相(cmr S7 r1 claude——turn 断言在崩点前未变，空泛)。
    assert state.metrics == db.load_state().metrics
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
    # 真正咬住 reload：settling 相位是 pre_settle 已提交的 DB 真相，fallback 回滚后
    # 内存须与之同源；metrics 同断言（cmr S7 r1 claude）。
    assert state.metrics == db.load_state().metrics
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
    extracted = {"metric_delta": {"民心": -4}}  # 国库由 economy_accounts 派生不可直写；民心负向不撞 clamp
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

    support_before = db.load_state().metrics["民心"]

    sess = _recovery_session(db, state, content, monkeypatch)
    result = sess.resolve_turn()

    assert result.awaiting is False
    assert state.turn == turn + 1  # 完整推进
    assert db.get_resolve_context(turn) is None  # settle 尾清掉
    assert state.turn_phase == TurnPhase.ISSUED.value
    # ready delta 真被 apply（不是空 delta 走个过场，cmr S7 r1 codex）。
    assert db.load_state().metrics["民心"] == support_before - 4


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

    calls = {"sim": 0, "extract": 0}

    def _resim(*a, **k):
        calls["sim"] += 1
        return "重新推演后的邸报，无决策块。", (k.get("simulator_payload") or {})
    monkeypatch.setattr(dm, "simulate_season_with_payload", _resim)

    def _reextract(*a, **k):
        calls["extract"] += 1
        return {"metric_delta": {"民心": -2}}, "raw-out", "raw-in"
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _reextract)
    support_before = db.load_state().metrics["民心"]

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
    # 贵调用真重跑了一次，且重抽的 delta 真落地（cmr S7 r1 codex）。
    assert calls == {"sim": 1, "extract": 1}
    assert db.load_state().metrics["民心"] == support_before - 2


def test_recovery_path_commits_pending_actions(game, monkeypatch):
    """恢复直入 apply 路也要 commit 暂存动作（cmr S7 r1 claude，P1）。

    web 在 settling 态可继续召对 stage 动作（chat 无相位门）；恢复结算推进后
    不 commit 的话这些行成旧回合孤儿死行（违 P1，advance_without_edict 同款不变式）。
    """
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm
    from tests.test_pending_actions import _active_minister_name

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"国库": 5}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    # 崩溃重载后玩家继续召对，stage 一条动作
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "恢复期标题", "new_content": "x", "deadline_months": 0})

    sess = _recovery_session(db, state, content, monkeypatch)
    result = sess.resolve_turn()

    assert result.awaiting is False
    assert state.turn == turn + 1
    statuses = [r["status"] for r in db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=?", (turn,)).fetchall()]
    assert statuses and all(st != "pending" for st in statuses)  # 不留孤儿


def test_poison_replay_clears_context_for_resimulation(game, monkeypatch, tmp_path):
    """重放炸 → 自动清 context（决定 6 逃生口接线），下次重试走重新推演（cmr S7 r2 claude）。

    不清的话:值级毒 delta（shape 合法 apply 必炸）每次重试同样重放同样炸=永久软死锁;
    原 delta 已在错误包留档，清掉不丢证据。
    """
    from ming_sim.session import TurnPhase
    from ming_sim.exceptions import SettlementAbort
    import ming_sim.decree as dm

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    def _poison_apply(*a, **k):
        raise RuntimeError("value-level poison")
    monkeypatch.setattr(dm, "apply_score_extraction", _poison_apply)

    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        sess.resolve_turn()

    ctx_after = db.get_resolve_context(turn)
    assert ctx_after is not None and ctx_after["extracted"] is None  # 降级非 ready：软死锁不可达，phase1 字段保留

    # 第二次重试：apply 恢复正常，无 ready context → 走重新推演（fallthrough）。
    monkeypatch.undo()
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "simulate_season_with_payload",
                        lambda *a, **k: ("重新推演邸报。", {}))
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: ({"metric_delta": {"民心": -1}}, "o", "i"))
    sess2 = _recovery_session(db, state, content, monkeypatch)
    db.add_directive(state, None, "减赋", source="player", status="draft")
    result = sess2.resolve_turn(decree="补颁诏")
    assert result.awaiting is False
    assert state.turn == turn + 1


def test_hitl_retry_replays_ready_context_without_reextract(game, monkeypatch):
    """HITL 重试消费 ready context，不重跑 extractor（cmr S7 r2 codex）。

    phase2 已 persist ready delta 后 settle 曾 abort：重试 submit_decisions
    不得重跑贵调用并覆盖 ready context。
    """
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    # 模拟「phase2 已抽取并 persist、settle abort 后」的 DB 态
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -3}},
        decree_text="HITL诏", narrative="裁断后邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    db.save_pending_decisions(turn, [{
        "title": "辽东战和", "context": "c",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    def _must_not_reextract(*a, **k):
        raise AssertionError("HITL 重试不应重跑 extractor")
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _must_not_reextract)
    monkeypatch.setattr(dm, "simulate_season_with_payload", _must_not_reextract)

    support_before = db.load_state().metrics["民心"]
    sess = _recovery_session(db, state, content, monkeypatch)
    report = sess.submit_decisions([{"label": "战"}])

    assert state.turn == turn + 1
    assert db.load_state().metrics["民心"] == support_before - 3  # ready delta 真重放
    assert db.get_resolve_context(turn) is None
    assert db.list_pending_decisions(turn) == []


def test_hitl_poison_replay_downgrades_context_then_reextracts(game, monkeypatch, tmp_path):
    """HITL 毒重放 → context 降级为非 ready（保 phase1 字段），重试走重抽（cmr S7 r3，2/2）。

    整行删除会造成新软死锁：awaiting+决策在+context 没了 → phase2 永远 LLMContractError，
    且 phase1 叙事/payload 唯一副本被毁=连重抽都数据不可能。
    """
    import ming_sim.decree as dm
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -3}},
        decree_text="HITL诏", narrative="裁断后邸报",
        simulator_payload={"k": "v"}, secret_orders=[], relevant_memories=[],
    )
    db.save_pending_decisions(turn, [{
        "title": "辽东战和", "context": "c",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    def _poison(*a, **k):
        raise RuntimeError("value-level poison")
    monkeypatch.setattr(dm, "apply_score_extraction", _poison)

    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        sess.submit_decisions([{"label": "战"}])

    ctx = db.get_resolve_context(turn)
    assert ctx is not None  # 行没被删（phase1 字段是重抽的数据依赖）
    assert ctx["extracted"] is None  # 降级非 ready
    assert ctx["narrative"] == "裁断后邸报"

    # 重试：apply 恢复 + stub 重抽成功 → phase2 走非 ready 分支重抽并完整结算。
    monkeypatch.undo()
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: ({"metric_delta": {"民心": -3}}, "o", "i"))
    state.turn_phase = "awaiting_decision"  # 回滚已还原；拼装 session 重建
    sess2 = _recovery_session(db, state, content, monkeypatch)
    report = sess2.submit_decisions([{"label": "战"}])

    assert state.turn == turn + 1  # 不再 LLMContractError，正常重抽结算
