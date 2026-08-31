"""#1620：settling 恢复面投影 ADR 0008 abort message + ready_replay。"""

from __future__ import annotations

from pathlib import Path

import pytest

import web_app
from ming_sim.decree import persist_resolve_context
from ming_sim.error_pack import (
    clear_for_resimulation,
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


def test_state_payload_settlement_recovery_ready_and_resim(
    recovery_web_game, monkeypatch, tmp_path,
):
    """ready=1 投影续跑语义；两次错误包取最新；clear 后 ready=0 重新推演。"""
    game = recovery_web_game
    db, state = game.db, game.state
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    turn = int(state.turn)

    # 非 settling → 无 recovery 投影
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    payload = game.state_payload()
    assert payload.get("settlement_recovery") is None

    # settling + ready extracted；写两份错误包，投影须取 attempt 更高者
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
    state.turn_phase = TurnPhase.SETTLING.value
    db.save_state(state)

    ready_payload = game.state_payload()
    recovery = ready_payload.get("settlement_recovery")
    assert isinstance(recovery, dict)
    assert recovery["ready_replay"] is True
    assert recovery["error_pack_path"] == str(Path(pack2).resolve())
    assert recovery["message"] == settlement_abort_message(recovery["error_pack_path"])
    assert "进度已保存" in recovery["message"]
    assert "发给作者" in recovery["message"]
    assert recovery["error_pack_path"] in recovery["message"]

    # 同 digest 再败后 clear → ready=0：重新推演
    clear_for_resimulation(db, turn)
    resim_payload = game.state_payload()
    recovery2 = resim_payload.get("settlement_recovery")
    assert isinstance(recovery2, dict)
    assert recovery2["ready_replay"] is False
    assert recovery2["error_pack_path"]
    assert "发给作者" in recovery2["message"]
