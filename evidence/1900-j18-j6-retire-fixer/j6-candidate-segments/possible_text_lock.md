# possible_text_lock (1)

## [16] tests/test_draft_admission_resubmit_1769.py:672 `test_advance_without_edict_vacuum_steam_no_decree_issued`
flags=['possible_text_lock'] lines=26
```
def test_advance_without_edict_vacuum_steam_no_decree_issued(
    admission_game, monkeypatch,
):
    """类B：POST 真空退朝成功 → 有 TURNS_PLAYED/MAX_TURN，无 DECREES_ISSUED。"""
    game = admission_game
    turn = int(game.state.turn)
    assert not (game.session.last_decree or "").strip()
    client = TestClient(web_app.app)
    resp = client.post(
        "/api/decree/advance_without_edict",
        json={"expected_turn": turn},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("awaiting_decision") is False
    assert _turn_of(_get_state(client)) == turn + 1

    steam = body.get("steam_events") or []
    names = [
        e.get("name") for e in steam if isinstance(e, dict)
    ]
    assert "STAT_TURNS_PLAYED" in names, f"邸报写成后应计过月: {steam!r}"
    assert "STAT_MAX_TURN_REACHED" in names, f"邸报写成后应计最大月: {steam!r}"
    assert "STAT_DECREES_ISSUED" not in names, (
        f"真空退朝不得计已颁: {steam!r}"
    )
```
