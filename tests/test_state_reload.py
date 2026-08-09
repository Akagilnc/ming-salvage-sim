"""S5 — 内存态与 DB 同源恢复（ADR 0008 决定 3 第三条）。

DB 回滚不还原内存副作用（state.metrics 直加 flows.py:192、turn_phase、next_period）。
回滚后重跑前把 state 从 DB 重载（与 restore/load_state 同路径），原地刷新同一对象
（各处持引用，不能换新对象）。

注：本文件设置/断言 turn_phase 时故意用 raw 字符串（如 "settling"/"reviewing"）而非
TurnPhase.X.value——pin 的是**落盘字符串值本身**，有意 enum 无关。S4 把生产代码相位比较
统一到 TurnPhase enum，测试侧落盘断言不跟随。
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _restore_content(content):
    """content 是 session-scope 共享 fixture;本文件的回滚/重建用例会全量替换
    content.characters(_sync_offices_from_db_impl 来自各用例的临时 probe.db 副本,
    teardown 即删)。每用例后快照还原,杜绝跨用例污染(cmr S5 r3,同 test_pending_actions 先例)。"""
    snap = dict(content.characters)
    field_snap = {name: (ch.office, ch.status, ch.office_type, ch.faction)
                  for name, ch in snap.items()}
    yield
    content.characters = snap
    for name, (office, status, office_type, faction) in field_snap.items():
        ch = content.characters.get(name)
        if ch is not None:
            ch.office, ch.status, ch.office_type, ch.faction = office, status, office_type, faction

import ming_sim.decree as decree_mod
from ming_sim.decree import pre_settle, reload_state_from_db


def test_reload_refreshes_state_in_place(game):
    """DB 改值后调 reload → state 字段被刷成 DB 值，且仍是同一对象（id 不变）。"""
    db, state, content = game
    state_id_before = id(state)

    # 制造内存/DB 分歧：直接改 DB 的相位与某 metric，不动内存 state。
    db.conn.execute("UPDATE game_state SET turn_phase='reviewing' WHERE id=1")
    db.conn.execute("UPDATE metrics SET value=7 WHERE key='皇威'")
    db.conn.commit()
    # 内存仍是旧值
    assert state.turn_phase != "reviewing"
    assert state.metrics["皇威"] != 7

    returned = reload_state_from_db(db, state)

    # 原地刷新：同一对象、字段已是 DB 值。
    assert id(state) == state_id_before
    assert returned is state
    assert state.turn_phase == "reviewing"
    assert state.metrics["皇威"] == 7


def test_reload_scrubs_next_period_advance(game):
    """reload 刷掉 next_period 的内存推进（turn/year/period）——DB 回滚不还原它们（ADR 0008 决定 3）。"""
    db, state, content = game
    db_turn = state.turn
    db_year, db_period = state.year, state.period

    state.next_period()  # 内存推进，未落盘
    assert state.turn == db_turn + 1

    reload_state_from_db(db, state)

    assert state.turn == db_turn
    assert state.year == db_year and state.period == db_period


def test_reload_passthrough_content_registry_no_crash(game):
    """registry 非 None 时只透传不处理（session 级接线待后续）；content 非 None 时
    重建 characters（幽灵/属性还原另有专测），本测只断不报错且 state 仍刷新。"""
    db, state, content = game
    db.conn.execute("UPDATE game_state SET turn_phase='reviewing' WHERE id=1")
    db.conn.commit()

    returned = reload_state_from_db(db, state, content=content, registry=object())

    assert returned is state
    assert state.turn_phase == "reviewing"


def _ledger_count(db, turn: int) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE turn=?", (turn,)
    ).fetchone()[0]


def test_reload_scrubs_dirty_settling_phase(game):
    """reload 单元：手工造脏 settling 相位（DB 是旧相位）→ reload 刷回 DB 真相（非 settling）。

    伤口本质：dirty settling 会被 pre_settle 守门跳过=整月财政丢；reload 是解药。
    """
    db, state, content = game
    db_phase = db.conn.execute(
        "SELECT turn_phase FROM game_state WHERE id=1").fetchone()[0]
    assert db_phase != "settling"

    state.turn_phase = "settling"  # 模拟 save_state 崩前已被赋的脏相位

    reload_state_from_db(db, state)

    assert state.turn_phase == db_phase != "settling"


def test_pre_settle_self_reloads_memory_on_rollback(game, monkeypatch):
    """pre_settle 内任一步抛错 → atomic 回滚后 pre_settle 自己 reload 刷净内存（调用方不必手动 reload）
    → 异常仍透传 → 再调 pre_settle 能完整跑（不被脏相位守门跳过）。脏读防线钉死（ADR 0008 决定 3 第三条）。"""
    db, state, content = game
    turn = state.turn
    before_phase = state.turn_phase
    before_metrics = dict(state.metrics)
    before_ledger = _ledger_count(db, turn)

    # save_state 抛错：此时内存 phase 已被赋成 settling、apply_fixed_period_flows 已直改 state.metrics。
    def _boom_save(st):
        raise RuntimeError("save boom")

    monkeypatch.setattr(db, "save_state", _boom_save)

    with pytest.raises(RuntimeError, match="save boom"):
        pre_settle(state, db)

    # pre_settle 已在回滚后自我 reload：内存与 DB 同源（phase 非 settling、metrics 回到回滚态）。
    assert state.turn_phase == before_phase != "settling"
    on_disk_phase = sqlite3.connect(db.path).execute(
        "SELECT turn_phase FROM game_state WHERE id=1").fetchone()[0]
    assert state.turn_phase == on_disk_phase
    # metrics 与 DB 同源：财政副作用随回滚消失，内存被刷回。
    assert state.metrics == before_metrics
    assert _ledger_count(db, turn) == before_ledger

    # 再调 pre_settle（恢复 save_state）能完整跑、不被脏相位跳过。
    monkeypatch.setattr(db, "save_state", db.__class__.save_state.__get__(db))
    pre_settle(state, db)
    assert state.turn_phase == "settling"
    assert _ledger_count(db, turn) > before_ledger


# ---------------------------------------------------------------------------
# cmr S5 r1 修复回归（F1 content 幽灵 / F2 嵌套脏读 / F3 metrics 窗口）
# ---------------------------------------------------------------------------

def test_rollback_purges_content_character_ghost(game, monkeypatch):
    """回滚后 content.characters 幽灵被清，重试任免不再被误拒（cmr S5 r1 F1，codex trace）。

    任免 commit 先挂 content 再写 DB；回滚删行留幽灵 → 重试走「在册」路因无行被拒，
    合法 pending 任免标 failed = 决策丢失。
    """
    import ming_sim.decree as decree_mod
    from ming_sim.decree import pre_settle
    db, state, content = game
    new_name = "赵无忌"
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name="王承恩",
        payload={"name": new_name, "office": "兵部右侍郎"})

    # commit_pending_actions 之后的步骤抛错 → 回滚
    def _boom(*a, **k):
        raise RuntimeError("post-commit step crash")
    monkeypatch.setattr(decree_mod, "auto_trigger_seed_issues", _boom)

    with pytest.raises(RuntimeError, match="post-commit step crash"):
        pre_settle(state, db, content=content, registry=None)

    assert new_name not in content.characters  # 幽灵已清
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (new_name,)).fetchone() is None
    # pending 行随回滚回到 pending(行本身也回滚了 status 变更)
    monkeypatch.undo()

    pre_settle(state, db, content=content, registry=None)  # 正常重试

    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE turn=? AND kind='office'",
        (state.turn,)).fetchone()
    assert row is not None and row["status"] == "committed"  # 合法任免不被误拒
    assert db.conn.execute(
        "SELECT name FROM characters WHERE name=?", (new_name,)).fetchone() is None
    dossiers = db.list_decree_dossiers(
        status="proposed", target_kind="character", target_id=new_name
    )
    assert len(dossiers) == 1  # 成案已 durable；颁布判决前仍不改人物盘面


def test_reload_skipped_inside_nested_atomic(game, monkeypatch):
    """嵌套 atomic 内不 reload：rollback 尚未发生，load_state 读到未提交脏写（cmr S5 r1 F2）。"""
    import ming_sim.decree as decree_mod
    from ming_sim.applier import atomic
    from ming_sim.decree import pre_settle
    db, state, content = game

    calls = {"n": 0}
    real_reload = decree_mod.reload_state_from_db
    def _counting_reload(*a, **k):
        calls["n"] += 1
        return real_reload(*a, **k)
    monkeypatch.setattr(decree_mod, "reload_state_from_db", _counting_reload)

    def _boom(*a, **k):
        raise RuntimeError("inner crash")
    monkeypatch.setattr(decree_mod, "auto_trigger_seed_issues", _boom)

    with pytest.raises(RuntimeError, match="回滚"):  # 外层 rollback-only 响亮
        with atomic(db):
            try:
                pre_settle(state, db)
            except RuntimeError:
                pass  # 吞内层异常,外层 rollback-only 接管

    assert calls["n"] == 0  # 嵌套内未 reload(脏读防线)


def test_metrics_refresh_never_empty_window(game):
    """metrics 刷新无空窗口：同一 dict 对象、键集与 DB 一致（cmr S5 r1 F3）。"""
    from ming_sim.decree import reload_state_from_db
    db, state, content = game
    before_id = id(state.metrics)
    state.metrics["国库"] = 999999  # 脏值
    state.metrics["幽灵指标"] = 1   # DB 没有的 key

    reload_state_from_db(db, state)

    assert id(state.metrics) == before_id
    assert "幽灵指标" not in state.metrics
    fresh = db.load_state()
    assert state.metrics == fresh.metrics


def test_rollback_restores_existing_character_attributes(game, monkeypatch):
    """存量人物的属性变更随回滚刷回 DB 真相（cmr S5 r2，claude+codex 2/2）。

    罢免 commit 改了 content 里现有 Character 的 status/office；回滚还原 DB 行，
    幽灵清理管不到「名字仍在」的脏属性 → content 与 DB 分叉持续整个 session。
    """
    import ming_sim.decree as decree_mod
    from ming_sim.decree import pre_settle
    from tests.test_pending_actions import _active_minister_name
    db, state, content = game
    name = _active_minister_name(db, content)
    # 基准取 DB 行（不变式=reload 后 content 与 DB 同源；活存档 DB 值可能已偏离 content JSON 初值）。
    row = db.conn.execute(
        "SELECT office, status FROM characters WHERE name=?", (name,)).fetchone()
    office_before, status_before = row["office"], row["status"]

    db.stage_pending_action(
        state.turn, kind="office", action="罢免", minister_name="王承恩",
        payload={"name": name})

    def _boom(*a, **k):
        raise RuntimeError("post-commit step crash")
    monkeypatch.setattr(decree_mod, "auto_trigger_seed_issues", _boom)

    with pytest.raises(RuntimeError, match="post-commit step crash"):
        pre_settle(state, db, content=content, registry=None)

    # DB 已回滚 → 内存 content 必须同源
    refreshed = content.characters[name]
    assert refreshed.status == status_before
    assert refreshed.office == office_before


def test_reload_passes_llm_config_to_content_rebuild(game, monkeypatch):
    """content 重建走 restore 同参：llm_config 必传（cmr S5 r3，缺省会降级「待铨」）。"""
    import ming_sim.session as session_mod
    from ming_sim.decree import reload_state_from_db
    db, state, content = game
    db.llm_config = object()  # 哨兵

    seen = {}
    def _spy(content_arg, db_arg, llm_config=None):
        seen["llm_config"] = llm_config
    monkeypatch.setattr(session_mod, "_sync_offices_from_db_impl", _spy)

    reload_state_from_db(db, state, content=content)

    assert seen["llm_config"] is db.llm_config


# ── atomic_and_reload helper（S4：六处 try/atomic/except-reload-reraise 公共内核） ──

def test_atomic_and_reload_commits_on_success(game):
    """正常退出：body 写入照常提交（与裸 with atomic 同语义）。"""
    from ming_sim.decree import atomic_and_reload
    db, state, content = game
    with atomic_and_reload(db, state, content=content):
        db.conn.execute("UPDATE metrics SET value = 12345 WHERE key = '国库'")
    row = db.conn.execute("SELECT value FROM metrics WHERE key = '国库'").fetchone()
    assert int(row["value"]) == 12345


def test_atomic_and_reload_reloads_and_reraises_at_depth0(game):
    """最外层 body 抛错：回滚后 reload 刷净内存，原异常透传。"""
    from ming_sim.decree import atomic_and_reload
    db, state, content = game
    state.metrics["国库"] = 999999  # 脏内存
    with pytest.raises(RuntimeError, match="boom"):
        with atomic_and_reload(db, state, content=content):
            db.conn.execute("UPDATE metrics SET value = 7 WHERE key = '国库'")
            raise RuntimeError("boom")
    # 回滚 + reload：内存与 DB 同源，脏值被刷掉
    fresh = db.load_state()
    assert state.metrics == fresh.metrics
    assert state.metrics["国库"] != 999999


def test_atomic_and_reload_skips_reload_when_nested(game, monkeypatch):
    """嵌套（depth>0）：内核不 reload（rollback 未发生，防脏读），原异常透传给外层。"""
    import ming_sim.decree as decree_mod
    from ming_sim.applier import atomic
    from ming_sim.decree import atomic_and_reload
    db, state, content = game

    calls = {"n": 0}
    real_reload = decree_mod.reload_state_from_db
    def _counting_reload(*a, **k):
        calls["n"] += 1
        return real_reload(*a, **k)
    monkeypatch.setattr(decree_mod, "reload_state_from_db", _counting_reload)

    with pytest.raises(RuntimeError, match="回滚"):  # 外层 rollback-only 响亮
        with atomic(db):
            try:
                with atomic_and_reload(db, state, content=content):
                    raise RuntimeError("inner crash")
            except RuntimeError:
                pass  # 吞内层异常，外层 rollback-only 接管
    assert calls["n"] == 0  # 嵌套内未 reload


def test_atomic_and_reload_chains_reload_failure(game, monkeypatch):
    """reload 自身再炸：原异常不被顶替，reload 异常链上抛（raise exc from reload_exc）。"""
    import ming_sim.decree as decree_mod
    from ming_sim.decree import atomic_and_reload
    db, state, content = game

    def _boom_reload(*a, **k):
        raise ValueError("reload failed")
    monkeypatch.setattr(decree_mod, "reload_state_from_db", _boom_reload)

    with pytest.raises(RuntimeError, match="orig") as ei:
        with atomic_and_reload(db, state, content=content):
            raise RuntimeError("orig")
    assert isinstance(ei.value.__cause__, ValueError)  # 链：orig from reload failed


def test_atomic_and_reload_runs_on_error_before_reload(game, monkeypatch):
    """on_error 钩子在 reload 前触发（settle 的 collector.reset 语义）。"""
    import ming_sim.decree as decree_mod
    from ming_sim.decree import atomic_and_reload
    db, state, content = game

    order = []
    real_reload = decree_mod.reload_state_from_db
    def _tracking_reload(*a, **k):
        order.append("reload")
        return real_reload(*a, **k)
    monkeypatch.setattr(decree_mod, "reload_state_from_db", _tracking_reload)

    with pytest.raises(RuntimeError):
        with atomic_and_reload(db, state, content=content,
                               on_error=lambda exc: order.append("on_error")):
            raise RuntimeError("boom")
    assert order == ["on_error", "reload"]
