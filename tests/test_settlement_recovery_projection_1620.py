"""#1620：settling 恢复面投影 ADR 0008 abort message + ready_replay。

契约只落 typed 字段：ready_replay / error_pack_path（当前 db_path）。
不锁 settlement_abort_message 散文措辞。
另：current-schema ready → 真 HTTP /api/decree/issue/stream 恢复主干。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import web_app
from ming_sim.decree import persist_resolve_context
from ming_sim.error_pack import (
    clear_for_resimulation,
    error_packs_root,
    write_error_pack,
)
from ming_sim.models import TurnPhase


@pytest.fixture
def recovery_web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def _plant_foreign_higher_attempt_pack(*, turn: int, foreign_db_path: str) -> Path:
    """同 turn、更高 attempt、不同 db_path 的完整五件包（串档诱饵）。"""
    root = error_packs_root()
    attempt = 99
    pack = root / f"turn{int(turn)}_attempt{attempt}"
    pack.mkdir(parents=True, exist_ok=False)
    for name in (
        "traceback.txt", "delta.json", "resolve_context.json", "save_backup.db",
    ):
        (pack / name).write_text("foreign", encoding="utf-8")
    (pack / "manifest.json").write_text(
        json.dumps({
            "db_path": foreign_db_path,
            "turn": int(turn),
            "attempt": attempt,
            "exception_type": "RuntimeError",
            "exception_message": "other-save",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return pack


def test_state_payload_settlement_recovery_ready_and_resim(
    recovery_web_game, monkeypatch, tmp_path,
):
    """ready=1 投影续跑；同 turn 异库更高 attempt 不串档；clear 后 ready=0。"""
    game = recovery_web_game
    db, state = game.db, game.state
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = int(state.turn)

    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    assert game.state_payload().get("settlement_recovery") is None

    persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="d", narrative="n",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    write_error_pack(
        db, state, exc=RuntimeError("settlement-fail-1"),
        extracted={"metric_delta": {"民心": -1}},
    )
    pack2 = write_error_pack(
        db, state, exc=RuntimeError("settlement-fail-2"),
        extracted={"metric_delta": {"民心": -1}},
    )
    foreign = _plant_foreign_higher_attempt_pack(
        turn=turn, foreign_db_path=str(tmp_path / "other-save.db"),
    )
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    recovery = game.state_payload().get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery["ready_replay"] is True
    own = str(Path(pack2).resolve())
    assert recovery["error_pack_path"] == own
    assert recovery["error_pack_path"] != str(foreign.resolve())
    # message 有值即证明 abort 指引已挂上；不锁散文措辞
    assert isinstance(recovery.get("message"), str) and recovery["message"]

    # 诊断目录不可遍历：恢复面仍可达，ready 保留，path 缺席（ADR 0008 逃生口）
    import ming_sim.error_pack as error_pack_mod

    class _BoomRoot:
        def exists(self):
            return True

        def iterdir(self):
            raise OSError("error_packs root not traversable")

    real_root = error_pack_mod.error_packs_root
    monkeypatch.setattr(error_pack_mod, "error_packs_root", lambda: _BoomRoot())
    recovery_io = game.state_payload().get("settlement_recovery")
    assert isinstance(recovery_io, dict)
    assert recovery_io["ready_replay"] is True
    assert recovery_io["error_pack_path"] == ""
    assert isinstance(recovery_io.get("message"), str) and recovery_io["message"]
    monkeypatch.setattr(error_pack_mod, "error_packs_root", real_root)

    # 完整包 entry stat（is_file）OSError：同一 soft-fail 边界，state 仍可达
    real_is_file = Path.is_file

    def _boom_pack_entry_stat(self):
        if self.name in error_pack_mod._COMPLETE_PACK_FILES:
            raise OSError("pack entry stat failed")
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", _boom_pack_entry_stat)
    recovery_stat = game.state_payload().get("settlement_recovery")
    assert isinstance(recovery_stat, dict)
    assert recovery_stat["ready_replay"] is True
    assert recovery_stat["error_pack_path"] == ""
    assert isinstance(recovery_stat.get("message"), str) and recovery_stat["message"]
    monkeypatch.setattr(Path, "is_file", real_is_file)

    clear_for_resimulation(db, turn)
    recovery2 = game.state_payload().get("settlement_recovery")
    assert isinstance(recovery2, dict)
    assert recovery2["ready_replay"] is False
    assert recovery2["error_pack_path"] == own
    assert isinstance(recovery2.get("message"), str) and recovery2["message"]


def _terminal_sse(response: httpx.Response) -> tuple[str, object]:
    blocks = [block for block in response.text.split("\n\n") if block.strip()]
    assert blocks, f"empty SSE body: {response.text!r}"
    lines = blocks[-1].splitlines()
    event = next(line[7:] for line in lines if line.startswith("event: "))
    data_line = next(line[6:] for line in lines if line.startswith("data: "))
    try:
        data = json.loads(data_line)
    except json.JSONDecodeError:
        data = data_line
    return event, data


def test_ready_recovery_issue_stream_clears_context_and_advances(
    recovery_web_game, monkeypatch,
):
    """current-schema ready → 真 HTTP /api/decree/issue/stream → 清 context、离 settling、turn+1 与 year/period 一次推进。

    复用 ASGI seam；不覆盖 version=0 旧档，不 mock 掉恢复入口。
    """
    game = recovery_web_game
    db, state = game.db, game.state
    turn = int(state.turn)
    start_year = int(state.year)
    start_period = int(state.period)
    # 一次 next_period 的外部月历契约（跨年语义由 models.next_period 最低层专测覆盖）
    expected_year = start_year + (1 if start_period >= 12 else 0)
    expected_period = 1 if start_period >= 12 else start_period + 1

    persist_resolve_context(
        db, turn, {"metric_delta": {"民心": -1}},
        decree_text="恢复诏", narrative="恢复邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    ctx = db.get_resolve_context(turn)
    assert ctx is not None and ctx.get("extracted") is not None
    assert int(ctx.get("resolve_contract_version") or 0) >= 1

    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)
    recovery = game.state_payload().get("settlement_recovery")
    assert isinstance(recovery, dict) and recovery["ready_replay"] is True

    def _must_not_rerun(*_a, **_k):
        raise AssertionError("ready recovery must not rerun simulator/extractor")

    monkeypatch.setattr(decree_mod, "simulate_season_with_payload", _must_not_rerun)
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", _must_not_rerun)
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        memories_mod, "run_agent_text",
        lambda *a, **k: '{"body": "月记", "tags": []}',
    )

    async def _issue():
        transport = httpx.ASGITransport(app=web_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.post(
                "/api/decree/issue/stream",
                json={"expected_turn": turn},
            )

    resp = asyncio.run(_issue())
    assert resp.status_code == 200, resp.text
    event, _data = _terminal_sse(resp)
    assert event == "done", resp.text

    assert int(game.state.turn) == turn + 1
    assert int(game.state.year) == expected_year
    assert int(game.state.period) == expected_period
    assert game.state.turn_phase != TurnPhase.SETTLING.value
    assert db.get_resolve_context(turn) is None
    assert game.state_payload().get("settlement_recovery") is None
