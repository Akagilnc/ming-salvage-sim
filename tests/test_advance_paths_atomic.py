"""S7 (ADR 0008 PR1) — 三条推进回合写路径统一 atomic 事务包裹 + 恢复入口消费。

决定 2：任何推进回合的写序列(正常 settle / simulator-fallback / advance_without_edict)
全有或全无——整体包 atomic，崩在中途整体回滚、内存从 DB 重载、相位/回合不前进。
决定 3：跨进程恢复入口(session.resolve_turn)在 settling 态分流——有 ready context 直入
apply(不重跑贵的 simulator/extractor)；无则重跑推演(验收③)。
决定 4：事务内 LLM 回调失败沿用降级，不触发回滚(章节记忆/结局总评内部已自吞)。

用 conftest 的 game fixture(活存档副本，连接走 _SuspendableConnection factory，atomic 可用)。

注：本文件设置/断言 turn_phase 时故意用 raw 字符串(如 "settling"/"awaiting_decision")而非
TurnPhase.X.value——它们 pin 的是**落盘字符串值本身**，有意 enum 无关：枚举重命名而落盘值
漂移时这些断言应响亮失败。S4 把生产代码相位比较统一到 TurnPhase enum，测试侧落盘断言不跟随。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

import ming_sim.decree as decree_mod
import ming_sim.issues as I
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
    # Fallback now replaces only the narrative and deliberately stays on the
    # normal extractor→atomic-settle rail.
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "fallback-extractor-output", "fallback-extractor-input"),
    )
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)

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

    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort) as error:
        _drive_fallback(db, state, content, monkeypatch)
    assert error.value.stage == "settle"
    assert isinstance(error.value.__cause__, RuntimeError)
    assert str(error.value.__cause__) == "fallback inertia boom"

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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_recovery_entry_resimulates_legacy_commitment_without_origin(game, monkeypatch):
    """A pre-origin ready commitment is not replayed and cannot advance the period."""
    import ming_sim.decree as dm
    import ming_sim.session as session_mod

    db, state, content = game
    turn = state.turn
    state.turn_phase = "settling"
    db.save_state(state)
    persist_resolve_context(
        db, turn, {
            "new_issues": [{
                "title": "旧档承诺", "commitment_kind": "until_stop",
                "stop_condition": {"type": "manual"},
            }],
        }, decree_text="旧诏", narrative="旧叙事", simulator_payload={},
        secret_orders=[], relevant_memories=[],
    )
    # Simulate a ready row written before the current replay contract existed.
    db.conn.execute(
        "UPDATE pending_resolve_context SET resolve_contract_version=0 WHERE turn=?",
        (turn,),
    )
    db.conn.commit()
    replayed = []
    monkeypatch.setattr(session_mod, "resolve_settling_recovery", lambda *a, **k: replayed.append(True))
    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "simulate_season_with_payload", lambda *a, **k: ("重推演", {}))
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", lambda *a, **k: ({}, "o", "i"))

    result = _recovery_session(db, state, content, monkeypatch).resolve_turn()

    assert result.awaiting is False
    assert replayed == []
    assert state.turn == turn + 1


def test_recovery_entry_replays_modern_noop_without_origin(
    game, monkeypatch,
):
    """Modern invalid/no-op envelopes are replayed, not mistaken for legacy."""
    import ming_sim.session as session_mod

    db, state, content = game
    turn = state.turn
    state.turn_phase = "settling"
    db.save_state(state)
    region = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    persist_resolve_context(
        db, turn, {"region_delta": {region: {"prosperity": 1}}},
        decree_text="今诏", narrative="今叙事", simulator_payload={},
        secret_orders=[], relevant_memories=[],
    )
    assert db.get_resolve_context(turn)["resolve_contract_version"] == 1
    replayed = []

    def _replay(*args, **kwargs):
        replayed.append(True)
        return session_mod.ResolveResult(awaiting=False, report="replayed")

    monkeypatch.setattr(session_mod, "resolve_settling_recovery", _replay)

    result = _recovery_session(db, state, content, monkeypatch).resolve_turn()

    assert result.awaiting is False
    assert replayed == [True]
    assert state.turn == turn
    assert state.turn_phase == "issued"


def test_recovery_entry_consumes_ready_context(saved_game, monkeypatch):
    """settling + ready context（手工 persist 一份非空 delta）→ resolve_turn 直入 apply：
    不重跑 simulator/extractor（stub 成抛错断言未被调）、context 清掉、turn+1（ADR 0008 决定 3）。
    用 saved_game：断言依赖玩过存档的民心基线 + 帝国修正下的 metric 增量，fresh seed 不复现（#5）。"""
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm

    db, state, content = saved_game
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


def test_recover_after_simulation_crash_can_resettle(saved_game, monkeypatch):
    """验收③：真跑 pre_settle（settling 落库）→ 模拟崩在推演期间（无 ready context）→
    恢复（resolve_turn 走 fallthrough 重跑推演）→ 能重新推演并完整结算推进（turn+1、财政不二跑）。

    崩于推演/抽取期间的窗口里 LLM 产出本就没持久化（resolve_context 无 ready）——重跑是
    唯一选择（ADR 0008 决定 3）。pre_settle 的 settling 守门保证前半段不二跑。
    用 saved_game：断言依赖玩过存档的结算链路状态，fresh seed 不复现（#5）。"""
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm

    db, state, content = saved_game
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
    db.add_directive(
        state, None, "减赋", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "tax-relief",
        },
    )
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
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND target_id=?",
        (turn, oid)).fetchone()
    assert row is not None and row["status"] == "committed"  # 真 committed 非 failed（ship-pre r1）
    title = db.conn.execute(
        "SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"]
    assert title == "恢复期标题"  # 真表生效


@pytest.mark.usefixtures("_offline_scene_beat_generator")
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
    # 首败只回滚并保留 ready 真源，允许原子重放；第二次同 payload 失败且两份
    # ADR0008 错误包都落成后才降级，避免一次偶发代码错误毁掉可重放产物。
    assert db.get_resolve_context(turn)["extracted"] is not None
    with pytest.raises(SettlementAbort):
        sess.resolve_turn()

    ctx_after = db.get_resolve_context(turn)
    assert ctx_after is not None and ctx_after["extracted"] is None

    # 第三次重试：apply 恢复正常，无 ready context → 走重新推演（fallthrough）。
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
    db.add_directive(
        state, None, "减赋", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "tax-relief",
        },
    )
    result = sess2.resolve_turn(decree="补颁诏")
    assert result.awaiting is False
    assert state.turn == turn + 1


def test_hitl_retry_replays_ready_context_without_reextract(saved_game, monkeypatch):
    """HITL 重试消费 ready context，不重跑 extractor（cmr S7 r2 codex）。

    phase2 已 persist ready delta 后 settle 曾 abort：重试 submit_decisions
    不得重跑贵调用并覆盖 ready context。
    用 saved_game：断言依赖玩过存档的结算链路状态，fresh seed 不复现（#5）。
    """
    from ming_sim.session import TurnPhase
    import ming_sim.decree as dm

    db, state, content = saved_game
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

    sess.submit_decisions([{"label": "留", "hint": "暂稳东江", "note": "姑留观后效"}])

    assert db.list_pending_decisions(turn) == []
    row = db.conn.execute(
        "SELECT terminal_state, source, choice_json FROM event_triggers WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == ""
    assert row["source"] == "hitl_decision"
    assert json.loads(row["choice_json"]) == {
        "label": "留",
        "hint": "暂稳东江",
        "note": "姑留观后效",
    }
    assert not db.has_event_triggered(event_id)
    assert event_id not in I._event_trigger_refs(db), (
        "submit_decisions 只能暂存亲裁 choice，不能在 phase2 前抢先把候选事件记成终态"
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

    sess.submit_decisions([{"label": "留", "hint": "暂稳东江", "note": "姑留观后效"}])

    assert db.list_pending_decisions(turn) == []
    row = db.conn.execute(
        "SELECT terminal_state, source, choice_json FROM event_triggers WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["terminal_state"] == ""
    assert row["source"] == "hitl_decision"
    assert json.loads(row["choice_json"]) == {
        "label": "留",
        "hint": "暂稳东江",
        "note": "姑留观后效",
    }


def test_hitl_ready_replay_retry_keeps_original_event_choice(game, monkeypatch):
    """cmr Gate2 r4 Finding2：ready-context 重试时 phase2 走「恢复重放」、**忽略**重交的亲裁
    选择（重放崩溃前真源的旧选择 delta）。submit_decisions 此刻绝不能用新选择覆写
    event_triggers.choice_json——否则事件账记新选择 B、而重放的世界状态来自旧选择 A，durable
    账实不符。断言：重试改投不同选择后，事件账仍是原选择。"""
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

    # 重试改投「留」（B，与原 A 不同）——ready-replay 应跳过覆写
    sess.submit_decisions([{"label": "留", "note": "改裁"}])

    row = db.conn.execute(
        "SELECT choice_json FROM event_triggers WHERE event_id=?", (event_id,)).fetchone()
    assert json.loads(row["choice_json"]) == {"label": "斩", "note": "原裁断"}, \
        "ready-replay 重试不得用新选择覆写事件账"


def test_submit_dossier_rescript_does_not_create_event_trigger(game, monkeypatch):
    import ming_sim.session as session_mod
    from ming_sim.session import GameSession

    db, state, content = game
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id="river-works",
    )
    option = {
        "label": "收回", "dossier_id": dossier_id,
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

    assert sess.submit_decisions([option]) == "ok"
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        (f"dossier:{dossier_id}",),
    ).fetchone() is None
    stored = db.list_pending_decisions(state.turn)[0]
    assert stored["status"] == "decided"
    assert stored["choice"] == option


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
    assert db.get_resolve_context(turn)["extracted"] is not None  # 首败仍可原子重放
    with pytest.raises(SettlementAbort):
        sess.submit_decisions([{"label": "战"}])

    ctx = db.get_resolve_context(turn)
    assert ctx is not None  # 行没被删（phase1 字段是重抽的数据依赖）
    assert ctx["extracted"] is None  # 重复失败且两份错误包后降级非 ready
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


def test_pending_commit_rolls_back_with_failed_replay(game, monkeypatch, tmp_path):
    """暂存动作 commit 与结算同生死：重放炸 → 动作随结算回滚回 pending（cmr S7 r4，2/2）。

    commit 在 atomic 外的话，结算回滚而动作及其真表副作用留存=跨事务半写。
    """
    import ming_sim.decree as dm
    from ming_sim.exceptions import SettlementAbort
    from tests.test_pending_actions import _active_minister_name

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "重放期标题", "new_content": "x", "deadline_months": 0})

    def _poison(*a, **k):
        raise RuntimeError("value-level poison")
    monkeypatch.setattr(dm, "apply_score_extraction", _poison)

    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        sess.resolve_turn()

    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND target_id=?",
        (turn, oid)).fetchone()
    assert row is not None and row["status"] == "pending"  # 随结算回滚，非半写
    title = db.conn.execute(
        "SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"]
    assert title == "原标题"  # 真表副作用也回滚


def test_hitl_reextract_branch_commits_pending(game, monkeypatch, tmp_path):
    """phase2 非 ready 分支也 commit 暂存动作（cmr S7 r4 claude）。"""
    import ming_sim.decree as dm
    from tests.test_pending_actions import _active_minister_name

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    # 非 ready context（如降级后）+ awaiting：重试走重抽分支
    db.save_resolve_context(turn, "HITL诏", "裁断后邸报", {},
                            secret_orders=[], relevant_memories=[])
    db.save_pending_decisions(turn, [{
        "title": "辽东战和", "context": "c",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])
    state.turn_phase = "awaiting_decision"
    db.save_state(state)

    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "重抽期标题", "new_content": "x", "deadline_months": 0})

    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: ({"metric_delta": {"民心": -1}}, "o", "i"))

    sess = _recovery_session(db, state, content, monkeypatch)
    sess.submit_decisions([{"label": "战"}])

    assert state.turn == turn + 1
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND target_id=?",
        (turn, oid)).fetchone()
    assert row is not None and row["status"] == "committed"  # 真 committed 非 failed（ship-pre r1）
    title = db.conn.execute(
        "SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"]
    assert title == "重抽期标题"


def test_escape_hatch_failure_does_not_mask_abort(game, monkeypatch, tmp_path):
    """逃生口自身炸不顶替 SettlementAbort（terminal 只接它=玩家指引不丢，cmr S7 r4）。"""
    import ming_sim.decree as dm
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    def _poison(*a, **k):
        raise RuntimeError("value-level poison")
    monkeypatch.setattr(dm, "apply_score_extraction", _poison)

    def _clear_boom(*a, **k):
        raise RuntimeError("clear boom")
    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort):
        sess.resolve_turn()  # 首败不调用逃生口

    monkeypatch.setattr(dm, "clear_for_resimulation", _clear_boom)
    with pytest.raises(SettlementAbort) as ei:
        sess.resolve_turn()  # 重复失败才尝试降级
    assert isinstance(ei.value.__cause__, RuntimeError)
    assert "clear boom" in str(ei.value.__cause__)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_resim_path_does_not_preconsume_pending(game, monkeypatch, tmp_path):
    """settling 无 ready 重推演路：守门早退不提前消费暂存动作（cmr S7 r5 codex）。

    早退路在事务外 commit 的话，extractor 再炸时动作及真表副作用已提交
    而回合未推进=跨事务半写。所有权规则：终端写路各自在 atomic 内 commit。
    """
    import ming_sim.decree as dm
    from ming_sim.exceptions import SettlementAbort
    from tests.test_pending_actions import _active_minister_name

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    dm.pre_settle(state, db, content=content)  # 落 settling
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "重推演期标题", "new_content": "x", "deadline_months": 0})

    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "simulate_season_with_payload",
                        lambda *a, **k: ("重新推演邸报。", {}))

    def _extract_boom(*a, **k):
        raise RuntimeError("extractor crash on resim")
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _extract_boom)

    sess = _recovery_session(db, state, content, monkeypatch)
    db.add_directive(
        state, None, "减赋", source="player", status="draft",
        dossier_payload={
            "dossier_action_type": "policy",
            "target_kind": "issue", "target_id": "tax-relief",
        },
    )
    with pytest.raises(SettlementAbort):
        sess.resolve_turn(decree="补颁诏")

    assert state.turn == turn  # 回合未推进
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND target_id=?",
        (turn, oid)).fetchone()
    assert row is not None and row["status"] == "pending"  # 未被提前消费
    title = db.conn.execute(
        "SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"]
    assert title == "原标题"  # 真表无半写


def test_fallback_path_commits_pending(game, monkeypatch):
    """fallback 终端路（推进回合）在自己的 atomic 内 commit 暂存动作（cmr S7 r5）。"""
    import ming_sim.decree as dm
    from tests.test_pending_actions import _active_minister_name

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)  # settling：守门早退不再消费
    name = _active_minister_name(db, content)
    oid = db.create_secret_order(state, name, "原标题", "原内容", [], deadline_months=0)
    db.stage_pending_action(
        turn, kind="secret_order", action="更新", minister_name=name, target_id=oid,
        payload={"new_title": "fallback标题", "new_content": "x", "deadline_months": 0})

    res = _drive_fallback(db, state, content, monkeypatch)

    assert res.awaiting is False
    assert state.turn == turn + 1
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND target_id=?",
        (turn, oid)).fetchone()
    assert row is not None and row["status"] == "committed"  # 真 committed 非 failed（ship-pre r1）
    title = db.conn.execute(
        "SELECT title FROM secret_orders WHERE id=?", (oid,)).fetchone()["title"]
    assert title == "fallback标题"


def test_fallback_persists_sources_created_by_inertia_before_archive(game, monkeypatch):
    """降级结算也须在 inertia 产生见闻后再投影聚合档案。"""
    db, state, content = game
    turn = state.turn
    dm = decree_mod
    original = dm.apply_issue_inertia_and_ongoing
    minister = next(
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    )

    def _inertia_with_source(*args, **kwargs):
        db.register_character_knowledge_source(
            state,
            [{"character_id": minister.name, "tier": "inertia"}],
            "inertia",
            "降级见闻",
            "inertia 受限事项",
            source_id="test:fallback-inertia-source",
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(dm, "apply_issue_inertia_and_ongoing", _inertia_with_source)
    _drive_fallback(db, state, content, monkeypatch)

    row = db.conn.execute(
        "SELECT body FROM character_knowledge_events "
        "WHERE character_name='' AND turn=? AND source_id=?",
        (turn, "test:fallback-inertia-source"),
    ).fetchone()
    assert row is not None
    assert row["body"] == "inertia 受限事项"


def test_recovery_restores_last_decree_for_web_display(game, monkeypatch):
    """重放路恢复 session.last_decree——跨进程恢复后 web 响应诏书字段不为空（cmr S7 r7）。"""
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="崩溃前诏书全文", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )

    def _must_not_run(*a, **k):
        raise AssertionError("不应重跑")
    monkeypatch.setattr(dm, "simulate_season_with_payload", _must_not_run)
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno", _must_not_run)

    sess = _recovery_session(db, state, content, monkeypatch)
    assert sess.last_decree == ""  # 跨进程恢复：内存里没有
    sess.resolve_turn()
    assert sess.last_decree == "崩溃前诏书全文"


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


def test_hitl_replay_blocked_by_pending_directives(game, monkeypatch):
    """HITL 重放入口同守门：pending 拟旨未核定不得推进（cmr S7 r9 codex，对称面）。"""
    import ming_sim.decree as dm

    db, state, content = game
    turn = state.turn
    dm.pre_settle(state, db, content=content)
    dm.persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    db.save_pending_decisions(turn, [{
        "title": "辽东战和", "context": "c",
        "options": [{"label": "战", "hint": ""}, {"label": "和", "hint": ""}],
    }])
    state.turn_phase = "awaiting_decision"
    db.save_state(state)
    db.add_directive(state, None, "请拨内帑", source="minister", status="pending")

    sess = _recovery_session(db, state, content, monkeypatch)
    with pytest.raises(ValueError, match="核定"):
        sess.submit_decisions([{"label": "战"}])
    assert state.turn == turn
    db.clear_resolve_context(turn)


def test_skip_refused_at_front_half_done(game):
    """ADR 决定 6：不提供「跳过本月结算」——FRONT_HALF_DONE 相位退朝响亮拒绝（ship-pre r1）。

    settling 时 skip=财政已提交而本月 LLM 结算永不落+丢弃已存结算上下文=自愿半落库。
    """
    from ming_sim.decree import advance_without_edict, pre_settle
    db, state, content = game
    turn = state.turn
    pre_settle(state, db, content=content)
    rows_before = _ledger_count(db, turn)

    with pytest.raises(ValueError, match="结算"):
        advance_without_edict(state, db, content=content)
    assert state.turn == turn  # 未推进
    assert _ledger_count(db, turn) == rows_before  # 财政不动

    state.turn_phase = "awaiting_decision"
    with pytest.raises(ValueError, match="裁决|结算"):
        advance_without_edict(state, db, content=content)
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
        lambda: sess.set_decree("改诏"),
        lambda: sess.write_decree(),
    ):
        with pytest.raises(ValueError, match="结算|亲裁"):
            call()


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_noready_recovery_uses_persisted_decree(game, monkeypatch):
    """跨进程 no-ready 恢复用占位真源里的原诏，免草案要求，不重新生成（ship-pre r5）。

    begin_turn 清 last_decree；不持久化的话玩家手改过的原诏在恢复时被 LLM 重生成顶替；
    零草案 settling（driver 档/逃生口降级后）还会撞「至少一条草案」死路。
    """
    import ming_sim.decree as dm
    import ming_sim.session as session_mod

    db, state, content = game
    turn = state.turn

    # 崩在 simulator payload 构建（pre_settle 之后、fallback try 之前）=真崩溃窗口
    def _crash(*a, **k):
        raise RuntimeError("crash before simulation")
    monkeypatch.setattr(dm, "build_simulator_payload", _crash)
    with pytest.raises(RuntimeError, match="crash before simulation"):
        dm.resolve_directives(state, db, None, None, [1], "皇帝手改的原诏",
                              content=content, registry=None)

    ctx = db.get_resolve_context(turn)
    assert ctx is not None and ctx["extracted"] is None  # 占位 ready=0
    assert ctx["decree_text"] == "皇帝手改的原诏"
    assert state.turn_phase == "settling"

    # 跨进程恢复：fresh 拼装（last_decree 空、无草案），fallthrough 用存诏、免草案、不重新生成
    monkeypatch.undo()
    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "simulate_season_with_payload",
                        lambda *a, **k: ("恢复推演邸报。", {}))
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: ({"metric_delta": {"民心": -1}}, "o", "i"))

    def _must_not_regen(*a, **k):
        raise AssertionError("不得重新生成诏书——恢复须用占位真源里的原诏")
    monkeypatch.setattr(session_mod, "write_decree_with_agno", _must_not_regen)

    sess = _recovery_session(db, state, content, monkeypatch)
    assert sess.last_decree == ""
    result = sess.resolve_turn()

    assert result.awaiting is False
    assert state.turn == turn + 1
    assert sess.last_decree == "皇帝手改的原诏"  # 原诏从真源恢复


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
