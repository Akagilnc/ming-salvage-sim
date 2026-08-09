"""Issue #539: night-scroll read contract at the audience-night public seam."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from ming_sim import audience_night as an


def _night(db, state):
    return int(an.open_night(db, state, time_of_day="戌时", location="乾清宫")["id"])


def _chat(db, state, night_id, minister, user_text, answer, seq):
    uid = db.append_chat_message(minister, state.turn, "user", user_text)
    mid = db.append_chat_message(minister, state.turn, "minister", answer)
    cur = db.conn.execute(
        "INSERT INTO chat_turns (minister_name,turn,year,period,user_message_id,minister_message_id,night_id,night_seq) VALUES (?,?,?,?,?,?,?,?)",
        (minister, state.turn, state.year, state.period, uid, mid, night_id, seq),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def test_real_player_sse_replaces_closed_same_turn_night_before_failed_reply(game, monkeypatch):
    import json
    import web_app
    from tests.test_audience_background import _FakeAgent, _web_game

    class _FailingAgent(_FakeAgent):
        def run(self, *_args, **_kwargs):
            raise RuntimeError("reply failed")
            yield  # pragma: no cover - make this the agent's streaming generator

    db, state, content = game
    old_night_id = _night(db, state)
    db.conn.execute(
        "UPDATE audience_nights SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
        (old_night_id,),
    )
    db.conn.commit()
    runtime = _web_game(db, state, content, _FailingAgent())
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        "/api/ministers/%E6%B8%A9%E4%BD%93%E4%BB%81/chat/stream",
        json={"message": "新场问话"},
    )
    events = [
        (block.splitlines()[0].removeprefix("event: "), json.loads(block.splitlines()[1].removeprefix("data: ")))
        for block in response.text.strip().split("\n\n")
    ]
    persisted = an.get_open_night(db)

    assert response.headers["content-type"].startswith("text/event-stream")
    assert events == [
        ("accepted", {"campaign_id": "", "night_id": int(persisted["id"]), "chat_turn_id": 1}),
        ("error", {"message": "reply failed", "campaign_id": "", "night_id": int(persisted["id"]), "chat_turn_id": 1}),
    ]
    assert int(persisted["id"]) != old_night_id
    assert int(persisted["turn"]) == int(state.turn)


def test_live_and_closed_night_share_the_real_http_contract(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = _night(db, state)
    _chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)
    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=db))
    client = TestClient(web_app.app)

    live = client.get("/api/audience/scroll").json()
    db.conn.execute("UPDATE audience_nights SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?", (night_id,))
    db.conn.commit()
    closed = client.get(f"/api/audience/scroll?night_id={night_id}").json()

    assert live["night_id"] == closed["night_id"] == night_id
    assert [set(message) for message in live["messages"]] == [set(message) for message in closed["messages"]]
    assert [message["content"] for message in live["messages"]] == [message["content"] for message in closed["messages"]]
    assert set(live) == set(closed) == {"night_id", "status", "messages"}
    assert live["status"] == "open"
    assert closed["status"] == "closed"


def test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = _night(db, state)
    first_turn = _chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 10)
    db.record_mindreading(first_turn, {
        "reader": "王承恩", "target": "杨嗣昌", "source": "察言观色",
        "precision": "约略", "narration": "万岁爷，他尚有保留。",
    })
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌以身家作保。", tags=["站台", "作保"],
        person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="帘外忽起雨声。", tags=["天气"],
        person_names=[], source_chat_turn_id=first_turn, order_key=10,
    )
    _chat(db, state, night_id, "洪承畴", "边情如何？", "边关尚稳。", 20)
    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=db))

    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    messages = payload["messages"]
    contents = [message["content"] for message in messages]

    assert [content for content in contents if content in {
        "辽饷如何？", "臣请据实核账。", "万岁爷，他尚有保留。", "边情如何？", "边关尚稳。",
    }] == ["辽饷如何？", "臣请据实核账。", "万岁爷，他尚有保留。", "边情如何？", "边关尚稳。"]
    assert "杨嗣昌以身家作保。" not in contents
    assert "帘外忽起雨声。" in contents
    assert {message["speaker"] for message in messages if message["role"] == "minister"} == {"杨嗣昌", "洪承畴"}

    allowed_message_fields = {
        "role", "speaker", "audibility", "time", "content",
        "soft_boundary", "beat", "highlights", "container",
        "chat_turn_id", "record_id",
    }
    forbidden_character_stats = {"loyalty", "ability", "importance", "influence", "power", "favor"}
    assert messages
    base_message_fields = allowed_message_fields - {"chat_turn_id", "record_id"}
    dialogue_contents = {"辽饷如何？", "臣请据实核账。", "边情如何？", "边关尚稳。"}
    for message in messages:
        expected_fields = set(base_message_fields)
        if message["content"] in dialogue_contents:
            expected_fields.add("chat_turn_id")
            assert message["chat_turn_id"] > 0
        if message["role"] == "attendant" and message["content"] == "万岁爷，他尚有保留。":
            expected_fields.update({"chat_turn_id", "record_id"})
            assert message["chat_turn_id"] > 0
            assert message["record_id"] > 0
        assert set(message) == expected_fields
        assert forbidden_character_stats.isdisjoint(message)
        assert forbidden_character_stats.isdisjoint(message["container"])
        assert set(message["container"]) == {"time_of_day", "location", "audience_type"}


def test_scroll_contract_merges_both_stores_with_container_and_coda(game):
    db, state, _ = game
    night_id = _night(db, state)
    an.append_ledger_entry(db, night_id, body="帘外风紧。", tags=[an.TAG_ENTER], person_names=["杨嗣昌"])
    _chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"] == {"time_of_day": "戌时", "location": "乾清宫", "audience_type": "召对"}
    assert [(m["role"], m["speaker"], m["content"]) for m in scroll if m["role"] != "scene"] == [
        ("user", "朕", "辽饷如何？"),
        ("minister", "杨嗣昌", "臣请据实核账。"),
    ]
    assert all({"role", "speaker", "audibility", "time", "soft_boundary", "beat", "highlights", "container"} <= set(m) for m in scroll)
    assert scroll[-1]["beat"] == "coda"
    assert scroll[-1]["content"] == ""


def test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action(game):
    db, state, _ = game
    night_id = _night(db, state)
    first_turn = _chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
    an.append_ledger_entry(db, night_id, body="臣告退。", tags=["人际动作"], person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10)
    an.append_ledger_entry(db, night_id, body="杨嗣昌退下。", tags=[an.TAG_EXIT], person_names=["杨嗣昌"])
    an.append_ledger_entry(db, night_id, body="洪承畴入殿。", tags=[an.TAG_ENTER], person_names=["洪承畴"])

    scroll = an.read_night_scroll(db, night_id)

    assert [m["content"] for m in scroll].count("臣告退。") == 1
    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["soft_boundary"] is True
    assert divider["speaker"] == "洪承畴"


def test_scroll_merges_mindreading_and_uses_structured_dedup_boundaries(game):
    db, state, _ = game
    night_id = _night(db, state)
    turn_id = _chat(db, state, night_id, "杨嗣昌", "卿可担名？", "臣愿当面作保。", 10)
    db.record_mindreading(turn_id, {
        "reader": "王承恩", "target": "杨嗣昌", "source": "察言观色",
        "precision": "约略", "narration": "万岁爷，他这话留了半分。",
    })
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌以身家作保。", tags=["站台", "作保"],
        person_names=["杨嗣昌"], source_chat_turn_id=turn_id, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="帘外忽起雨声。", tags=["天气"],
        person_names=[], source_chat_turn_id=turn_id, order_key=10,
    )

    scroll = an.read_night_scroll(db, night_id)

    aside = next(message for message in scroll if message["role"] == "attendant")
    assert (aside["speaker"], aside["beat"], aside["audibility"]) == ("王承恩", "aside", an.AUDIBILITY_PRIVATE)
    assert aside["content"] == "万岁爷，他这话留了半分。"
    assert "杨嗣昌以身家作保。" not in [message["content"] for message in scroll]
    assert "帘外忽起雨声。" in [message["content"] for message in scroll]


def test_extractor_open_tags_do_not_drive_beat_or_soft_boundary(game):
    db, state, _ = game
    night_id = _night(db, state)
    turn_id = _chat(db, state, night_id, "杨嗣昌", "说下去。", "臣遵旨。", 10)
    an.append_ledger_entry(
        db, night_id, body="只是提到了入殿旧事。", tags=[an.TAG_ENTER],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="又提到了告退旧事。", tags=[an.TAG_EXIT],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )

    scroll = an.read_night_scroll(db, night_id)

    by_content = {message["content"]: message["beat"] for message in scroll}
    assert by_content["只是提到了入殿旧事。"] == "scene"
    assert by_content["又提到了告退旧事。"] == "scene"
    assert not any(message["beat"] == "divider" and message["speaker"] == "洪承畴" for message in scroll)


def test_scroll_container_uses_persisted_summon_method(game):
    db, state, _ = game
    night_id = _night(db, state)
    an.summon_enter(db, night_id, "杨嗣昌", method=an.METHOD_YUECI)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"]["audience_type"] == an.METHOD_YUECI


def test_scroll_without_next_entrance_has_unnamed_boundary(game):
    db, state, _ = game
    night_id = _night(db, state)
    an.append_ledger_entry(db, night_id, body="众臣告退。", tags=[an.TAG_EXIT], person_names=["杨嗣昌"])

    scroll = an.read_night_scroll(db, night_id)

    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["speaker"] == ""


def test_same_departure_facts_emit_one_divider_but_later_departure_survives(game):
    db, state, _ = game
    night_id = _night(db, state)
    first_turn = _chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌退下。", tags=[an.TAG_EXIT],
        person_names=["杨嗣昌"], order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌告退。", tags=[], person_names=["杨嗣昌"],
        presence_effect=an.PRESENCE_EXIT, source_chat_turn_id=first_turn, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌再度告退。", tags=[an.TAG_EXIT],
        person_names=["杨嗣昌"], order_key=20,
    )

    dividers = [message for message in an.read_night_scroll(db, night_id) if message["beat"] == "divider"]

    assert len(dividers) == 2


def test_history_turns_lists_every_closed_night_including_night_only_turns(game, monkeypatch):
    import web_app

    db, state, _ = game
    first = _night(db, state)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (first,))
    second = _night(db, state)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (second,))
    db.conn.commit()
    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=db))

    payload = TestClient(web_app.app).get("/api/history/turns").json()
    entries = [item for item in payload["turns"] if item["turn"] == state.turn]

    assert [item["night_id"] for item in entries] == [first, second]
    assert [(item["kind"], item["time_of_day"], item["location"]) for item in entries] == [
        ("night", "戌时", "乾清宫"), ("night", "戌时", "乾清宫"),
    ]
    assert [(item["scene_number"], item["scene_count"]) for item in entries] == [(1, 2), (2, 2)]
    assert len([item for item in payload["turns"] if item["turn"] == state.turn and item["kind"] == "month"]) <= 1
    assert all(not item["has_report"] and not item["has_directive"] for item in entries)
    assert all("has_extraction" not in item for item in entries)


def test_personal_projection_only_reads_the_current_open_night(game):
    db, state, _ = game
    old_night = _night(db, state)
    _chat(db, state, old_night, "杨嗣昌", "旧夜问话", "旧夜答复", 10)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (old_night,))
    current_night = _night(db, state)
    current_turn = _chat(db, state, current_night, "杨嗣昌", "本夜问话", "本夜答复", 10)

    projection = db.build_chat_projection("杨嗣昌")

    assert [message["content"] for message in projection] == ["本夜问话", "本夜答复"]
    assert {message["chat_turn_id"] for message in projection} == {current_turn}


def test_ending_timeline_consumes_monthly_archive_once_not_scene_rows():
    from ming_sim.memories import build_timeline

    class FakeDB:
        def list_chapter_memories(self, upto_turn=None): return []
        def list_monthly_archives(self):
            return [{"turn": 7, "year": 1628, "period": 3}]
        def list_archived_turns(self):
            raise AssertionError("scene-combined archive must not drive ending timeline")
        def get_turn_extraction(self, turn): return None

    assert build_timeline(FakeDB()) == [{
        "turn": 7, "year": 1628, "period": 3,
        "decree_brief": "", "effect_brief": "", "chapter": "",
    }]


def test_history_projection_handlers_are_sync_for_sqlite_access():
    import inspect
    import web_app

    assert not inspect.iscoroutinefunction(web_app.api_audience_scroll)
    assert not inspect.iscoroutinefunction(web_app.api_history_turns)
