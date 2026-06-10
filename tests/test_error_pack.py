"""S6 (ADR 0008 PR1) — extractor 失败响亮中止 + 错误包。

决定 3（:406 改响亮中止）：extractor 抛错不再 extracted={} 静默续跑——上抛 SettlementAbort，
回合不推进、无落库。决定 6/7：自动落错误包到 user-data 目录（traceback + delta + resolve_context
+ 存档副本 + manifest），attempt 从目录文件数推导，中止提示自带路径指引。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
from ming_sim.exceptions import SettlementAbort


def _drive_extractor_failure(db, state, content, monkeypatch):
    """以 stub 驱动真实 _settle_after_narrative，令 extractor 抛错。

    返回 before_turn。期望 _settle_after_narrative 上抛 SettlementAbort。
    """
    monkeypatch.setattr(decree_mod, "build_extractor_shared_context",
                        lambda *a, **k: "ctx")
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent",
                        lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent",
                        lambda *a, **k: None)

    def _stub_extract(*a, **k):
        raise RuntimeError("simulated extractor crash")
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", _stub_extract)
    return state.turn


def test_extractor_failure_raises_settlement_abort(game, monkeypatch, tmp_path):
    """tracer bullet：extractor 抛错 → 响亮中止（SettlementAbort），回合未推进。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    before = _drive_extractor_failure(db, state, content, monkeypatch)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod._settle_after_narrative(
            state, db, None, None,
            "减赋诏", "本月邸报……", {"k": "v"}, [], [],
            before, lambda *a: None,
            content=content, registry=None,
        )

    assert ei.value.turn == before
    assert state.turn == before  # 回合未推进


def test_error_pack_written_with_five_files(game, monkeypatch, tmp_path):
    """中止时落错误包：目录存在、五件齐、manifest 字段对、save_backup.db 可被 sqlite3 打开。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    before = _drive_extractor_failure(db, state, content, monkeypatch)

    with pytest.raises(SettlementAbort) as ei:
        decree_mod._settle_after_narrative(
            state, db, None, None,
            "减赋诏", "本月邸报……", {"k": "v"}, [], [],
            before, lambda *a: None,
            content=content, registry=None,
        )

    pack = Path(ei.value.error_pack_path)
    assert pack.is_dir()
    for fname in ("traceback.txt", "delta.json", "resolve_context.json",
                  "save_backup.db", "manifest.json"):
        assert (pack / fname).exists(), f"缺 {fname}"

    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["turn"] == before
    assert manifest["attempt"] == 1
    assert manifest["exception_type"] == "RuntimeError"
    assert "simulated extractor crash" in manifest["exception_message"]
    assert manifest["db_path"] == db.path

    # save_backup.db 能被 sqlite3 打开且含 game_state 行。
    conn = sqlite3.connect(str(pack / "save_backup.db"))
    try:
        n = conn.execute("SELECT COUNT(*) FROM game_state").fetchone()[0]
        assert n >= 1
    finally:
        conn.close()


def test_abort_leaves_no_db_settlement_writes(game, monkeypatch, tmp_path):
    """中止 → 无 turn_report / turn_extraction 落库、resolve_context 无 ready 行。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    before = _drive_extractor_failure(db, state, content, monkeypatch)

    with pytest.raises(SettlementAbort):
        decree_mod._settle_after_narrative(
            state, db, None, None,
            "减赋诏", "本月邸报……", {"k": "v"}, [], [],
            before, lambda *a: None,
            content=content, registry=None,
        )

    assert db.get_turn_report(before) == ""
    assert db.get_turn_extraction(before) is None
    ctx = db.get_resolve_context(before)
    assert ctx is None or ctx["extracted"] is None  # 无 ready delta 行


def test_attempt_derived_from_existing_dirs(game, monkeypatch, tmp_path):
    """同 turn 写两次包 → attempt=1,2（从错误目录文件数推导，不从 DB）。"""
    from ming_sim.error_pack import write_error_pack
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    exc = RuntimeError("boom")

    p1 = write_error_pack(db, state, exc=exc, extracted=None, resolve_ctx=None)
    p2 = write_error_pack(db, state, exc=exc, extracted=None, resolve_ctx=None)

    m1 = json.loads((Path(p1) / "manifest.json").read_text(encoding="utf-8"))
    m2 = json.loads((Path(p2) / "manifest.json").read_text(encoding="utf-8"))
    assert m1["attempt"] == 1
    assert m2["attempt"] == 2
    assert Path(p1) != Path(p2)


def test_write_error_pack_inside_atomic_is_rejected(game, monkeypatch, tmp_path):
    """在 atomic 内写包 → backup_to 守卫响亮拒绝（钉住「包必须在 atomic 外」约束）。"""
    from ming_sim.applier import atomic
    from ming_sim.error_pack import write_error_pack
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="atomic"):
        with atomic(db):
            write_error_pack(db, state, exc=RuntimeError("x"),
                             extracted=None, resolve_ctx=None)


def test_pack_write_failure_does_not_mask_original(game, monkeypatch, tmp_path):
    """写包中途失败 → 原结算异常不被顶替（链式保留）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    before = _drive_extractor_failure(db, state, content, monkeypatch)

    # 令写包炸（backup_to 失败模拟磁盘故障）。
    def _boom_backup(*a, **k):
        raise OSError("disk full while backing up")
    monkeypatch.setattr(db, "backup_to", _boom_backup)

    with pytest.raises(BaseException) as ei:
        decree_mod._settle_after_narrative(
            state, db, None, None,
            "减赋诏", "本月邸报……", {"k": "v"}, [], [],
            before, lambda *a: None,
            content=content, registry=None,
        )

    # 原 extractor 异常（RuntimeError simulated extractor crash）须在异常链里可寻。
    chain = []
    e = ei.value
    while e is not None:
        chain.append(e)
        e = e.__cause__ or e.__context__
    assert any("simulated extractor crash" in str(c) for c in chain), \
        f"原异常被顶替丢失：{[type(c).__name__ for c in chain]}"


def test_clear_for_resimulation_downgrades_context_keeps_settling(game):
    """重新推演逃生口：context 降级非 ready（保 phase1 字段），settling 相位不动。

    整行删除会毁掉 HITL 重抽的数据依赖（phase1 叙事/payload 唯一副本）并造成
    awaiting 叉新软死锁（cmr S7 r3，2/2）。
    """
    from ming_sim.error_pack import clear_for_resimulation
    from ming_sim.models import TurnPhase
    db, state, content = game
    turn = state.turn

    # 立一个 ready 的 resolve_context + settling 相位。
    db.save_resolve_context(turn, "d", "n", {"k": "v"},
                            secret_orders=[], relevant_memories=[],
                            extracted={"metric_delta": {"国库": 1}})
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    assert db.get_resolve_context(turn) is not None

    clear_for_resimulation(db, turn)

    # 降级：LLM 段产出清除、phase1 字段保留。
    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] is None
    assert ctx["decree_text"] == "d"
    assert ctx["narrative"] == "n"
    assert ctx["simulator_payload"] == {"k": "v"}
    # settling 相位不动（DB 与内存都仍为 settling）。
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.load_state().turn_phase == TurnPhase.SETTLING.value
    db.clear_resolve_context(turn)


def test_clear_for_resimulation_noop_when_no_context(game):
    """无 context 行时逃生口 no-op（分支双侧）。"""
    from ming_sim.error_pack import clear_for_resimulation
    db, state, content = game
    db.clear_resolve_context(state.turn)
    clear_for_resimulation(db, state.turn)
    assert db.get_resolve_context(state.turn) is None


def test_rejections_jsonl_path_in_error_dir(monkeypatch, tmp_path):
    """拒收 jsonl 与错误包集中同一 user-data 错误目录（决定 7：一次打包全带走）。"""
    from ming_sim.error_pack import error_packs_root, rejections_jsonl_path
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    jsonl = Path(rejections_jsonl_path())
    assert jsonl.parent == error_packs_root()
    assert jsonl.name == "rejections.jsonl"


# ---------------------------------------------------------------------------
# cmr S6 r1 修复回归（F2 attempt 防覆盖 / F3 mirror 父目录 / F4 中断不降级）
# ---------------------------------------------------------------------------

def test_attempt_never_overwrites_existing_pack(game, tmp_path, monkeypatch):
    """非连续 attempt 目录下写包绝不覆盖既有包（cmr S6 r1 F2，claude+codex）。

    len+1 + exist_ok=True 会算出 attempt=2 并静默覆盖既有 turn{N}_attempt2。
    """
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    from ming_sim.error_pack import error_packs_root, write_error_pack
    db, state, content = game
    turn = state.turn

    stale = error_packs_root() / f"turn{turn}_attempt2"
    stale.mkdir(parents=True)
    (stale / "manifest.json").write_text('{"sentinel": "keep me"}', encoding="utf-8")

    pack = write_error_pack(db, state, exc=RuntimeError("x"))

    assert pack.endswith("attempt3")  # max+1，不是 len+1=2
    assert (stale / "manifest.json").read_text(encoding="utf-8") == '{"sentinel": "keep me"}'


def test_mirror_writes_to_rejections_jsonl_path(game, tmp_path, monkeypatch):
    """rejections_jsonl_path 开箱可写：父目录就位，mirror 直接 append（cmr S6 r1 F3）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
    from ming_sim.error_pack import rejections_jsonl_path
    db, state, content = game
    db.conn.execute("DROP TABLE IF EXISTS rejection_reports")
    rc = RejectionCollector()
    rc.record("army_delta", RejectedItem(
        item={}, reason="r", category="invalid_enum", source=Provenance.unknown), turn=1)
    rc.flush_to_db(db)
    db.conn.commit()

    path = rejections_jsonl_path()
    rc.mirror_to_jsonl(path)

    lines = open(path, encoding="utf-8").readlines()
    assert len(lines) == 1


def test_pack_write_interrupt_propagates_as_interrupt(game, tmp_path, monkeypatch):
    """写包期间 Ctrl-C 原样传播，不降级成普通结算错误（cmr S6 r1 F4）。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    import ming_sim.decree as decree_mod
    from tests.test_resolve_context_recovery import _drive_settle_after_narrative

    def _interrupt(*a, **k):
        raise KeyboardInterrupt()
    monkeypatch.setattr(decree_mod, "write_error_pack", _interrupt)

    db, state, content = game
    with pytest.raises(KeyboardInterrupt):
        _drive_settle_after_narrative(db, state, content, monkeypatch,
                                      extractor_behavior="fail",
                                      error_pack_dir=tmp_path)


def test_web_issue_endpoint_returns_structured_abort(monkeypatch):
    """SettlementAbort 在 /api/decree/issue 回结构化非 500，玩家看得到指引（cmr S6 r2 codex）。"""
    import asyncio
    from fastapi import HTTPException
    import web_app
    from ming_sim.exceptions import SettlementAbort

    class _StubSession:
        def resolve_turn(self, cheat_directive=""):
            raise SettlementAbort(
                "本月结算失败，进度已保存，可重试。\n错误包已生成：/tmp/x\n请把该文件夹发给作者，以便排查。",
                turn=3, stage="extract", error_pack_path="/tmp/x")

    class _StubGame:
        session = _StubSession()
        class state:
            ended = False

    monkeypatch.setattr(web_app, "get_game", lambda: _StubGame())

    with pytest.raises(HTTPException) as ei:
        asyncio.run(web_app.api_issue_decree())

    assert ei.value.status_code != 500
    assert "可重试" in str(ei.value.detail)
    assert "错误包" in str(ei.value.detail)


def test_web_directive_endpoints_409_when_frozen(monkeypatch):
    """恢复窗冻结的 mutator 在 web 端回 409 指引而非 500（ship-pre r3 codex）。"""
    import asyncio
    from fastapi import HTTPException
    import web_app

    class _StubSession:
        def confirm_directive(self, directive_id):
            raise ValueError("月末结算进行中（恢复态），请先完成结算再改诏稿。")
        def pending_count(self):
            return 0

    class _StubGame:
        session = _StubSession()
        def directive_payload(self, item):
            return {}
        def directive_rows(self):
            return []

    monkeypatch.setattr(web_app, "get_game", lambda: _StubGame())

    with pytest.raises(HTTPException) as ei:
        asyncio.run(web_app.api_confirm_directive(1))
    assert ei.value.status_code == 409
    assert "结算" in str(ei.value.detail)
