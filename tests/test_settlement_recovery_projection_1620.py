"""#1620：settling 恢复面投影 ADR 0008 abort message + ready_replay。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web_app
from ming_sim.decree import persist_resolve_context
from ming_sim.error_pack import (
    clear_for_resimulation,
    error_packs_root,
    settlement_abort_message,
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
    # 当前包若已有 attempt1/2，诱饵用更高号，确保仅按 attempt 会误选它。
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

    # 非 settling → 无 recovery 投影
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    payload = game.state_payload()
    assert payload.get("settlement_recovery") is None

    # settling + ready extracted；本库两包 + 异库更高 attempt 诱饵
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

    ready_payload = game.state_payload()
    recovery = ready_payload.get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery["ready_replay"] is True
    own = str(Path(pack2).resolve())
    assert recovery["error_pack_path"] == own
    assert recovery["error_pack_path"] != str(foreign.resolve())
    assert recovery["message"] == settlement_abort_message(own)
    assert "进度已保存" in recovery["message"]
    assert "发给作者" in recovery["message"]
    assert own in recovery["message"]
    assert str(foreign) not in recovery["message"]

    # 同 digest 再败后 clear → ready=0：重新推演；仍不串异库包
    clear_for_resimulation(db, turn)
    resim_payload = game.state_payload()
    recovery2 = resim_payload.get("settlement_recovery")
    assert isinstance(recovery2, dict)
    assert recovery2["ready_replay"] is False
    assert recovery2["error_pack_path"] == own
    assert "发给作者" in recovery2["message"]
