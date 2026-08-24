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
            "减赋诏", "本月邸报……", {"k": "v", "transit_semantics": []}, [], [],
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
            "减赋诏", "本月邸报……", {"k": "v", "transit_semantics": []}, [], [],
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
            "减赋诏", "本月邸报……", {"k": "v", "transit_semantics": []}, [], [],
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
            "减赋诏", "本月邸报……", {"k": "v", "transit_semantics": []}, [], [],
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


def test_clear_for_resimulation_preserves_source(game):
    """降级回写须保留 provenance source（#144 cmr r1 回归）。

    clear_for_resimulation 回读 phase1 字段重建 context；source 是 #144 新增的
    phase1 持久字段，恢复重放据此判玩家可见性。若回写漏传 source，会被
    save_resolve_context 默认 system_simulation 盖掉，使降级路径静默吞掉
    player_decree/hitl_decision 来源 → 恢复后玩家可见拒收提示丢失。
    """
    from ming_sim.error_pack import clear_for_resimulation
    db, state, content = game
    turn = state.turn

    db.save_resolve_context(turn, "d", "n", {"k": "v"},
                            secret_orders=[], relevant_memories=[],
                            extracted={"metric_delta": {"国库": 1}},
                            source="player_decree")
    assert db.get_resolve_context(turn)["source"] == "player_decree"

    clear_for_resimulation(db, turn)

    ctx = db.get_resolve_context(turn)
    assert ctx is not None
    assert ctx["extracted"] is None, "LLM 段产出仍应清除"
    assert ctx["source"] == "player_decree", "玩家来源须随降级保留，不被默认 system_simulation 盖回"
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
        def resolve_turn(self, cheat_directive="", inflight_wait_s=None):
            raise SettlementAbort(
                "本月结算失败，进度已保存，可重试。\n错误包已生成：/tmp/x\n请把该文件夹发给作者，以便排查。",
                turn=3, stage="extract", error_pack_path="/tmp/x")

    class _StubGame:
        session = _StubSession()
        class state:
            ended = False

    monkeypatch.setattr(web_app, "get_game", lambda: _StubGame())

    with pytest.raises(HTTPException) as ei:
        web_app.api_issue_decree()

    assert ei.value.status_code != 500
    assert "可重试" in str(ei.value.detail)
    assert "错误包" in str(ei.value.detail)


def test_shape_garbage_extractor_product_is_sanitized_and_recorded(game, monkeypatch, tmp_path):
    """ADR0015：可拆 shape 垃圾不再中止整月，拒收留痕后净化落库。"""
    from tests.test_resolve_context_recovery import _drive_settle_after_narrative
    import ming_sim.decree as dm

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    # stub extractor 返回 shape 垃圾（region_delta 应为 dict 实得 list）
    monkeypatch.setattr(dm, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(dm, "build_extractor_shared_context", lambda *a, **k: "ctx")
    monkeypatch.setattr(dm, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: ({"region_delta": ["garbage"]}, "o", "i"))

    turn = state.turn
    report = dm._settle_after_narrative(
        state, db, None, None,
        "诏", "邸报", {"transit_semantics": []}, [], [],
        turn, lambda *a: None,
        content=content, registry=None,
    )
    assert "邸报" in report
    assert db.get_resolve_context(turn) is None  # 成功推进后清理真源
    row = db.conn.execute("SELECT section, item_json FROM rejection_reports WHERE turn=?", (turn,)).fetchone()
    assert row["section"] == "region_delta"
    assert '"raw_value"' in row["item_json"]


def test_next_attempt_skips_malformed_and_foreign_entries(game, monkeypatch, tmp_path):
    """attempt 推导跳过畸形后缀/他 turn/非目录项，取本 turn 数字后缀 max+1
    （PR #90 R3 sourcery：钉 _next_attempt 防御分支）。"""
    from ming_sim.error_pack import error_packs_root, write_error_pack
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = state.turn
    root = error_packs_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"turn{turn}_attempt7").mkdir()        # 有效：进 max
    (root / f"turn{turn}_attemptX").mkdir()        # 畸形后缀：忽略
    (root / f"turn{turn + 1}_attempt99").mkdir()   # 他 turn：不串号
    (root / f"turn{turn}_attempt9").write_text("")  # 同名文件非目录：忽略

    p = write_error_pack(db, state, exc=RuntimeError("boom"),
                         extracted=None, resolve_ctx=None)

    m = json.loads((Path(p) / "manifest.json").read_text(encoding="utf-8"))
    assert m["attempt"] == 8  # 7+1，不被 X/99/文件项带偏


def test_version_read_failure_falls_back_to_unknown(game, monkeypatch, tmp_path):
    """VERSION 缺失/读失败 → manifest.version='unknown'，写包不失败
    （PR #90 R3 sourcery：钉 _read_version 防御分支）。"""
    import ming_sim.error_pack as ep
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ep, "bundled_path",
                        lambda name: str(tmp_path / "no-such-dir" / name))

    p = ep.write_error_pack(db, state, exc=RuntimeError("boom"),
                            extracted=None, resolve_ctx=None)

    m = json.loads((Path(p) / "manifest.json").read_text(encoding="utf-8"))
    assert m["version"] == "unknown"


def test_complete_ready_packs_match_database_turn_digest_and_manifest_shape(game, monkeypatch, tmp_path):
    """Ready retry evidence is scoped by db path + turn + digest; malformed manifests are ignored."""
    from ming_sim.error_pack import complete_error_packs_for_ready, ready_payload_digest

    db, state, _ = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    from ming_sim.error_pack import error_packs_root
    root = error_packs_root()
    root.mkdir(parents=True)
    payload = {"metric_delta": {"民心": 1}}
    required = ("traceback.txt", "delta.json", "resolve_context.json", "save_backup.db")

    def pack(name, manifest):
        path = root / name
        path.mkdir()
        for filename in required:
            (path / filename).write_text("x", encoding="utf-8")
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return path

    good = pack(f"turn{state.turn}_attempt1", {"db_path": db.path, "turn": state.turn,
                         "ready_payload_digest": ready_payload_digest(payload)})
    pack(f"turn{state.turn}_attempt2", {"db_path": db.path + ".other", "turn": state.turn,
                      "ready_payload_digest": ready_payload_digest(payload)})
    pack(f"turn{state.turn}_attempt3", {"db_path": db.path, "turn": state.turn + 1,
                        "ready_payload_digest": ready_payload_digest(payload)})
    pack(f"turn{state.turn}_attempt4", ["not", "an", "object"])

    assert complete_error_packs_for_ready(db.path, state.turn, payload) == [good]
