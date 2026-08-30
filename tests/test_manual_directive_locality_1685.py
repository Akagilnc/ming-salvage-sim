"""#1685 manual directive locality contract through the real HTTP entry."""

from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("target_kind", "target_id", "scope", "status", "expected_scope"),
    [
        ("region", "shaanxi", "单省", 200, "single"),
        ("region", "shaanxi", "无", 409, None),
        ("policy", "realm-relief", "全国", 200, "national"),
    ],
)
def test_manual_directive_locality_is_validated_before_admission(
    game, monkeypatch, target_kind, target_id, scope, status, expected_scope,
):
    import ming_sim.cli_backend as cli_backend
    import web_app
    from ming_sim.session import GameSession

    db, state, content = game
    extracted = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": target_kind,
        "目标ID": target_id,
        "颁布方式": "普通",
        "施行范围": scope,
        "承办人": "毕自严",
        "参与人": [{"character_id": "毕自严", "tier": "主办"}],
    }
    monkeypatch.setattr(
        cli_backend,
        "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(extracted, ensure_ascii=False), 1),
    )

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    web_game = types.SimpleNamespace(
        db=db,
        state=state,
        content=content,
        session=session,
        directive_rows=lambda: db.list_directives(state, statuses=("pending", "draft")),
        directive_payload=lambda row: dict(row),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)

    response = TestClient(web_app.app).post(
        "/api/directives", json={"text": "着依旨施行。", "notes": ""},
    )
    assert response.status_code == status

    directives = db.list_directives(state)
    if status == 409:
        assert directives == []
        assert db.list_decree_dossiers() == []
        return

    assert len(directives) == 1
    assert directives[0]["status"] == "draft"
    assert db.ensure_dossiers_for_draft_directives(state) == []
    dossiers = db.list_decree_dossiers()
    assert dossiers, [dict(row) for row in directives]
    payloads = [json.loads(row["payload_json"]) for row in dossiers]
    assert {payload["locality_scope"] for payload in payloads} == {expected_scope}
    if expected_scope == "single":
        assert len(dossiers) == 1
        assert dossiers[0]["region_id"] == "shaanxi"
    else:
        from ming_sim.execution_pressure import ming_province_ids

        assert {row["region_id"] for row in dossiers} == set(ming_province_ids(db.conn))
