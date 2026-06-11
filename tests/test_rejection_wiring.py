"""PR2-S0(ADR 0008 决定 5/8,#91)——拒收收集器接进结算管线。

生命周期与事务对齐:apply 产生的拒收项 → 事务内 flush 进 rejection_reports →
commit 成功后镜像 jsonl → 回滚路 reset 不留行不留镜像。attempt 从错误目录推导
(不从 DB 取,随回滚重置即失真)。经 driver.run_settle 端到端驱动(公共接口)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driver import run_settle


def _rejection_rows(db, turn):
    try:
        return db.conn.execute(
            "SELECT section, reason, category, source, attempt FROM rejection_reports"
            " WHERE turn=? ORDER BY id", (turn,)
        ).fetchall()
    except Exception:
        return []


def test_rejected_item_lands_in_reports_and_jsonl(game, monkeypatch, tmp_path):
    """坏 delta 项(查无此人的人物状态变化)经结算后:rejection_reports 落行 +
    commit 后镜像 jsonl——「哪个 section 最常被喂脏」从此可聚合(决定 5)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    run_settle(db, state, content, {
        "人物状态变化": [{"name": "查无此人甲", "status": "dead", "reason": "测试"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    section, reason, category, source, attempt = rows[0]
    assert section == "character_status_changes"
    assert reason  # 人读原因非空
    assert attempt == 1
    jsonl = tmp_path / "error_packs" / "rejections.jsonl"
    assert jsonl.exists()
    lines = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["section"] == "character_status_changes"
    assert lines[0]["turn"] == turn


def test_rollback_leaves_no_rows_and_no_jsonl(game, monkeypatch, tmp_path):
    """settle 在 flush 之后崩 → 事务回滚:rejection_reports 无行、jsonl 无镜像
    (镜像只在 commit 成功后写,否则留「DB 没有、文件却有」的孤立行)。"""
    import ming_sim.decree as decree_mod
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    real_clear = type(db).clear_resolve_context
    def _boom(self, t):
        raise RuntimeError("crash after flush")
    monkeypatch.setattr(type(db), "clear_resolve_context", _boom)

    with pytest.raises(SettlementAbort):
        run_settle(db, state, content, {
            "人物状态变化": [{"name": "查无此人乙", "status": "dead", "reason": "测试"}],
        }, narrative="x", decree_text="y")

    monkeypatch.setattr(type(db), "clear_resolve_context", real_clear)
    assert _rejection_rows(db, turn) == []
    assert not (tmp_path / "error_packs" / "rejections.jsonl").exists()


def test_attempt_derived_from_error_pack_dirs(game, monkeypatch, tmp_path):
    """同回合已有 attempt1 错误包(上次失败)→ 本次重试的拒收行 attempt=2:
    拒收与错误包同号,事后能对上「第几次重试产生的」(决定 5,不从 DB 取)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    (tmp_path / "error_packs" / f"turn{turn}_attempt1").mkdir(parents=True)

    run_settle(db, state, content, {
        "人物状态变化": [{"name": "查无此人丙", "status": "dead", "reason": "测试"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][4] == 2  # attempt


def test_engine_extractor_path_stamps_system_simulation(game, monkeypatch, tmp_path):
    """引擎 resolve 路(simulator→extractor→settle)的拒收行 source=system_simulation
    ——extractor 产出属推演管线,与 driver 信封(unknown 兜底)区分(决定 5 provenance)。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "simulate_season_with_payload",
                        lambda *a, **k: ("本月邸报。", k.get("simulator_payload") or {}))
    monkeypatch.setattr(decree_mod, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({"character_status_changes": [
            {"name": "查无此人丁", "status": "dead", "reason": "测试"}]}, "out", "in"))

    decree_mod.resolve_directives(state, db, None, None, [1], "减赋诏",
                                  content=content, registry=None)

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][3] == "system_simulation"  # source


def test_issue_summary_nested_rejections_are_collected(game, monkeypatch, tmp_path):
    """issue_summary 是 dict(嵌套 new_issues/cancels 列表),桥接不能只看顶层 list
    ——new_issues 正是实测最常被喂脏的段(origin_kind 缺失被拒,agy 实录),
    决定 5 的「哪个 section 最常被喂脏」聚合对它失明即失去主要价值(cmr S0 r1,2/2)。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    run_settle(db, state, content, {
        "new_issues": [{"title": "臆造局势", "kind": "initiative"}],  # 缺 origin_kind → 拒
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn)
    assert len(rows) == 1
    assert rows[0][0] == "issue_summary.new_issues"
    assert "decree/event_pool" in rows[0][1]  # 拒收原因原样保留


def test_nested_atomic_success_path_does_not_orphan_jsonl(game, monkeypatch, tmp_path):
    """嵌套 atomic 内跑 settle:mirror 必须等最外层 commit——否则外层回滚后
    DB 行消失而 jsonl 已写=孤立镜像行(违决定 5「commit 成功后才 append」;
    异常路有对称守门,成功路同样要有)(cmr S0 r1,2/2)。"""
    from ming_sim.applier import atomic

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn

    with pytest.raises(RuntimeError, match="outer rollback"):
        with atomic(db):
            run_settle(db, state, content, {
                "人物状态变化": [{"name": "查无此人戊", "status": "dead", "reason": "测试"}],
            }, narrative="x", decree_text="y")
            raise RuntimeError("outer rollback")

    assert _rejection_rows(db, turn) == []  # DB 行随外层回滚消失
    assert not (tmp_path / "error_packs" / "rejections.jsonl").exists()  # 镜像未先写
