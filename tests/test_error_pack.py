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


def test_clear_for_resimulation_clears_context_keeps_settling(game):
    """重新推演逃生口：清 resolve_context，但 settling 相位不动（前半段已提交不可重跑）。"""
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

    # context 已清。
    assert db.get_resolve_context(turn) is None
    # settling 相位不动（DB 与内存都仍为 settling）。
    assert state.turn_phase == TurnPhase.SETTLING.value
    assert db.load_state().turn_phase == TurnPhase.SETTLING.value


def test_rejections_jsonl_path_in_error_dir(monkeypatch, tmp_path):
    """拒收 jsonl 与错误包集中同一 user-data 错误目录（决定 7：一次打包全带走）。"""
    from ming_sim.error_pack import error_packs_root, rejections_jsonl_path
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    jsonl = Path(rejections_jsonl_path())
    assert jsonl.parent == error_packs_root()
    assert jsonl.name == "rejections.jsonl"
