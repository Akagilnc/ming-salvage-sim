"""#1843 reopen：史册本月诏书改读 pending_resolve_context.decree_text。"""

from __future__ import annotations


def test_history_turn_reads_decree_text_from_resolve_context(game, monkeypatch):
    db, state, content = game
    turn = int(state.turn)
    db.save_resolve_context(
        turn,
        decree_text="着宁远补饷三十万两",
        simulator_payload={},
    )
    db.save_turn_report(state, "邸报正文", knowledge_items=[], attendant_message="")
    from fastapi.testclient import TestClient
    import web_app

    monkeypatch.setattr(web_app, "get_game", lambda: type("Game", (), {"db": db})())
    response = TestClient(web_app.app).get(f"/api/history/turn/{turn}")
    assert response.status_code == 200
    history = response.json()
    assert history["exists"] is True
    assert history["decree_text"] == "着宁远补饷三十万两"
