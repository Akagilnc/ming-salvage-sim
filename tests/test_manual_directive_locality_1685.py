"""#1685 manual directive region locality via assembly write + real HTTP tracer."""

from __future__ import annotations

import json

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client


def _extracted(scope, person="毕自严"):
    return {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "颁布方式": "普通",
        "施行范围": scope,
        "承办人": "毕自严",
        "参与人": [{"character_id": person, "tier": "主办"}],
    }


def test_manual_directive_region_assembly_writes_single_and_advances(
    tracer_client, monkeypatch,
):
    """#1685 主干：一次 LLM 抽 region+「无」→ assembly 写 single → 封存推进。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None
    calls = []

    def backend(*_args, **_kwargs):
        calls.append(1)
        return json.dumps(_extracted("无"), ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    response = tracer_client.post(
        "/api/directives", json={"text": "着依旨施行。", "notes": ""},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    turn_before = game.state.turn
    _post_issue_stream(
        tracer_client, expected_turn=turn_before, step="#1685 locality issue/stream",
    )
    assert game.state.turn == turn_before + 1
    dossiers = game.db.list_decree_dossiers()
    assert len(dossiers) == 1
    assert dossiers[0]["region_id"] == "shaanxi"
    payload = json.loads(dossiers[0]["payload_json"])
    assert payload["locality_scope"] == "single"
    assert [p["character_id"] for p in payload["participant_roster"]] == ["毕自严"]
