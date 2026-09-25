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


def test_web_issue_endpoint_returns_structured_abort(monkeypatch):
    """SettlementAbort 在 /api/decree/issue 回结构化非 500，玩家看得到指引（cmr S6 r2 codex）。"""
    import asyncio
    from fastapi import HTTPException
    import web_app
    from ming_sim.exceptions import SettlementAbort

    class _StubSession:
        def await_translations_before_month(self, after_drain=None):
            if after_drain is not None:
                after_drain()

        def resolve_turn(
            self, cheat_directive="", inflight_wait_s=None,
            write_gate_already_held=False,
        ):
            raise SettlementAbort(
                "本月结算失败，进度已保存，可重试。\n错误包已生成：/tmp/x\n请把该文件夹发给作者，以便排查。",
                turn=3, stage="extract", error_pack_path="/tmp/x")

    class _StubGame:
        session = _StubSession()
        class state:
            ended = False
            turn = 3
            turn_phase = "summoning"

    monkeypatch.setattr(web_app, "get_game", lambda: _StubGame())

    with pytest.raises(HTTPException) as ei:
        web_app.api_issue_decree()

    assert ei.value.status_code != 500
    assert "可重试" in str(ei.value.detail)
    assert "错误包" in str(ei.value.detail)




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


def test_clear_for_resimulation_preserves_audience_decree_rows(game):
    """T4：重模拟作废范围排除召对段；settlement 段仍作废。"""
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
    from ming_sim.error_pack import clear_for_resimulation

    db, state, _content = game
    turn = state.turn
    collector = RejectionCollector()
    collector.record(
        "audience_decree",
        RejectedItem(
            item={"kind": "draft"},
            reason="audience validation",
            category="decree_validation",
            source=Provenance.player_decree,
        ),
        turn,
    )
    collector.record(
        "region_delta",
        RejectedItem(
            item={"raw_value": []},
            reason="settlement shape",
            category="invalid_shape",
            source=Provenance.player_decree,
        ),
        turn,
    )
    collector.flush_to_db(db)
    db.conn.commit()

    db.save_resolve_context(
        turn, "d", "n", {"k": "v"},
        secret_orders=[], relevant_memories=[],
        extracted={"metric_delta": {"国库": 1}},
        source="player_decree",
    )
    clear_for_resimulation(db, turn)

    rows = {
        str(row["section"]): int(row["resimulation_invalidated"] or 0)
        for row in db.conn.execute(
            "SELECT section, resimulation_invalidated FROM rejection_reports WHERE turn=?",
            (turn,),
        ).fetchall()
    }
    assert rows["audience_decree"] == 0
    assert rows["region_delta"] == 1
    assert decree_mod._has_durable_player_visible_rejection(db, turn)
    db.clear_resolve_context(turn)
