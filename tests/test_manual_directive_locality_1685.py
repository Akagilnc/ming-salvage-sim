"""#1685 manual directive locality correction through the real HTTP entry."""

from __future__ import annotations

import json
import types

from fastapi.testclient import TestClient

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client


def _client(game, monkeypatch, replies):
    import ming_sim.cli_backend as cli_backend
    import web_app
    from ming_sim.session import GameSession

    db, state, content = game
    calls = []

    def backend(*_args, **_kwargs):
        calls.append(1)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return json.dumps(reply, ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    session = GameSession.__new__(GameSession)
    session.db, session.state = db, state
    session.llm_config, session.content = None, content
    web_game = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        directive_rows=lambda: db.list_directives(
            state, statuses=("pending", "draft"),
        ),
        directive_payload=lambda row: dict(row),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    return TestClient(web_app.app), calls


def _extracted(scope):
    return {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "颁布方式": "普通",
        "施行范围": scope,
        "承办人": "毕自严",
        "参与人": [{"character_id": "毕自严", "tier": "主办"}],
    }


def test_manual_directive_locality_heals_before_admission(tracer_client, monkeypatch):
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None
    calls = []
    replies = [_extracted("无"), _extracted("单省")]

    def backend(*_args, **_kwargs):
        calls.append(1)
        return json.dumps(replies[min(len(calls) - 1, 1)], ensure_ascii=False), 1

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    response = tracer_client.post(
        "/api/directives", json={"text": "着依旨施行。", "notes": ""},
    )

    assert response.status_code == 200
    assert len(calls) == 2
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


def test_manual_directive_locality_rejects_non_locality_drift(game, monkeypatch):
    import ming_sim.cli_backend as cli_backend

    db, _state, _content = game
    changed = _extracted("单省")
    changed["动作类型"] = "military_order"
    client, calls = _client(game, monkeypatch, [_extracted("无"), changed])

    response = client.post(
        "/api/directives", json={"text": "着依旨施行。", "notes": ""},
    )

    assert response.status_code == 409
    assert len(calls) == 1 + cli_backend.DRAFT_INTENT_HEAL_RETRIES
    assert db.conn.execute("SELECT COUNT(*) FROM turn_directives").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0


def test_manual_directive_non_combination_failure_does_not_retry(game, monkeypatch):
    db, _state, _content = game
    missing = _extracted("单省")
    missing["目标ID"] = "不存在的省"
    client, calls = _client(game, monkeypatch, [missing])

    response = client.post(
        "/api/directives", json={"text": "着依旨施行。", "notes": ""},
    )

    assert response.status_code != 200
    assert len(calls) == 1
    assert db.conn.execute("SELECT COUNT(*) FROM turn_directives").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0


def test_manual_directive_locality_retry_exhaustion_admits_nothing(game, monkeypatch):
    import ming_sim.cli_backend as cli_backend

    db, _state, _content = game
    client, calls = _client(game, monkeypatch, [_extracted("无")])

    response = client.post(
        "/api/directives", json={"text": "着依旨施行。", "notes": ""},
    )

    assert response.status_code == 409
    assert len(calls) == 1 + cli_backend.DRAFT_INTENT_HEAL_RETRIES
    assert db.conn.execute("SELECT COUNT(*) FROM turn_directives").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
