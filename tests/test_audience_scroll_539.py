"""Issue #539: night-scroll read contract at the audience-night public seam."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from ming_sim import audience_night as an
from ming_sim.audience_translation import list_pending_translations
from tests.conftest import append_night_chat, open_audience_night


def _scroll_game(db):
    return SimpleNamespace(
        db=db,
        pending_translation_retries=lambda **kw: list_pending_translations(db, **kw),
    )


def test_real_player_sse_replaces_closed_same_turn_night_before_failed_reply(game, monkeypatch):
    import json
    import web_app
    from tests.test_audience_background import _FakeAgent, _web_game

    class _FailingAgent(_FakeAgent):
        def run(self, *_args, **_kwargs):
            raise RuntimeError("reply failed")
            yield  # pragma: no cover - make this the agent's streaming generator

    db, state, content = game
    old_night_id = open_audience_night(db, state)
    db.conn.execute(
        "UPDATE audience_nights SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
        (old_night_id,),
    )
    db.conn.commit()
    runtime = _web_game(db, state, content, _FailingAgent())
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    response = TestClient(web_app.app).post(
        "/api/audience/chat/stream",
        json={"message": "新场问话"},
    )
    events = [
        (block.splitlines()[0].removeprefix("event: "), json.loads(block.splitlines()[1].removeprefix("data: ")))
        for block in response.text.strip().split("\n\n")
    ]
    persisted = an.get_open_night(db)

    assert response.headers["content-type"].startswith("text/event-stream")
    # #1465 ④：回话未成终失败 — error 前无条件空 replace（清半句；即使本案零 content）
    assert events == [
        ("accepted", {"campaign_id": "", "night_id": int(persisted["id"]), "chat_turn_id": 1}),
        ("delta", {"content": "", "replace": True}),
        ("error", {"message": "reply failed", "campaign_id": "", "night_id": int(persisted["id"]), "chat_turn_id": 1}),
    ]
    assert int(persisted["id"]) != old_night_id
    assert int(persisted["turn"]) == int(state.turn)


def test_real_player_summon_sse_precedes_reply_and_scroll_shows_protagonist(game, monkeypatch):
    import json
    import web_app
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    runtime = _web_game(db, state, content, _FakeAgent(), monkeypatch)
    runtime.favorites = set()
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    client = TestClient(web_app.app)

    response = client.post(
        "/api/audience/chat/stream",
        json={"message": "宣王绍徽"},
    )
    events = [
        (block.splitlines()[0].removeprefix("event: "), json.loads(block.splitlines()[1].removeprefix("data: ")))
        for block in response.text.strip().split("\n\n")
    ]
    kinds = [kind for kind, _ in events]
    assert response.status_code == 200
    assert kinds.index("accepted") < kinds.index("protagonist_changed") < kinds.index("done")
    scroll = client.get("/api/audience/scroll").json()
    assert scroll["protagonist"] == "王绍徽"
    assert any(person["name"] == "王绍徽" and person["portrait_id"] == content.characters["王绍徽"].portrait_id for person in scroll["characters"])


def test_live_and_closed_night_share_the_real_http_contract(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = open_audience_night(db, state)
    append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))
    client = TestClient(web_app.app)

    live = client.get("/api/audience/scroll").json()
    db.conn.execute("UPDATE audience_nights SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?", (night_id,))
    db.conn.commit()
    closed = client.get(f"/api/audience/scroll?night_id={night_id}").json()

    assert live["night_id"] == closed["night_id"] == night_id
    assert [set(message) for message in live["messages"]] == [set(message) for message in closed["messages"]]
    assert [message["content"] for message in live["messages"]] == [message["content"] for message in closed["messages"]]
    assert set(live) == set(closed) == {
        "night_id", "status", "messages", "protagonist", "roster", "characters",
        "translation_pending", "translation_retries", "pending_translation_turn_ids", "container",
        "reply_retries",
    }
    assert live["status"] == "open"
    assert closed["status"] == "closed"


def test_empty_open_night_scroll_exposes_persisted_container(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = int(an.open_night(db, state, time_of_day="午时", location="文华殿")["id"])
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))
    payload = TestClient(web_app.app).get("/api/audience/scroll").json()

    assert payload["night_id"] == night_id
    assert all(not message["content"] for message in payload["messages"])
    assert payload["container"] == {"time_of_day": "午时", "location": "文华殿", "audience_type": "召对"}


def test_scroll_exposes_declared_protagonist_and_ledger_roster(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.summon_enter(db, night_id, "王绍徽")
    an.summon_enter(db, night_id, "毕自严")
    an.set_night_protagonist(db, night_id, "王绍徽")
    an.dismiss_from_audience(db, "王绍徽", night_id=night_id)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))

    payload = TestClient(web_app.app).get("/api/audience/scroll").json()

    assert payload["protagonist"] == "王绍徽"
    assert payload["roster"] == [
        {"name": "王承恩", "present": True},
        {"name": "王绍徽", "present": False},
        {"name": "毕自严", "present": True},
    ]


def test_scroll_projects_portrait_for_legal_aside_speaker_outside_roster(game, monkeypatch):
    import web_app
    from tests.test_audience_background import _FakeAgent, _web_game

    db, state, content = game
    night_id = open_audience_night(db, state)
    an.append_ledger_entry(
        db, night_id, tags=["scroll_role:attendant"],
        person_names=["杨嗣昌"], audibility="御前低语",
        body="杨嗣昌低语。",
    )
    runtime = _web_game(db, state, content, _FakeAgent(), monkeypatch)
    runtime.favorites = set()
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    assert "杨嗣昌" not in [entry["name"] for entry in payload["roster"]]
    assert any(message["role"] == "attendant" and message["speaker"] == "杨嗣昌" for message in payload["messages"])
    assert any(person["name"] == "杨嗣昌" and person["portrait_id"] == content.characters["杨嗣昌"].portrait_id for person in payload["characters"])


def test_scroll_exposes_translation_pending_until_late_declaration_lands(game, monkeypatch):
    import web_app
    from ming_sim.audience_translation import apply_audience_round_translation

    db, state, _ = game
    night_id = open_audience_night(db, state)
    turn, _ = append_night_chat(db, state, night_id, "王绍徽", "请奏", "臣在", 20)
    db.mark_story_extraction_pending(turn)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))
    client = TestClient(web_app.app)

    assert client.get("/api/audience/scroll").json()["translation_pending"] is True
    apply_audience_round_translation(db, state, {"protagonist": {"person_name": "王绍徽"}}, night_id=night_id, chat_turn_id=turn)
    settled = client.get("/api/audience/scroll").json()
    assert settled["translation_pending"] is False
    assert settled["protagonist"] == "王绍徽"


def test_translation_segments_replace_neutral_reply_in_real_scroll(game, monkeypatch):
    import web_app
    from ming_sim.audience_translation import apply_audience_round_translation

    db, state, _ = game
    night_id = open_audience_night(db, state)
    story = "臣领旨。王承恩低语。殿内烛影摇曳。"
    turn_id, _ = append_night_chat(db, state, night_id, "杨嗣昌", "辽饷何解？", story, 10)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))
    client = TestClient(web_app.app)
    before = client.get("/api/audience/scroll").json()["messages"]
    assert [m["content"] for m in before if m.get("chat_turn_id") == turn_id][-1] == story
    assert [(m["role"], m["speaker"], m["highlights"]) for m in before if m.get("chat_turn_id") == turn_id][-1] == ("scene", "", [])
    assert client.get("/api/audience/scroll").json()["translation_pending"] is True

    apply_audience_round_translation(db, state, {
        "scene_facts": [
            {"body": "臣领旨。", "role": "minister", "audibility": "殿上公开", "person_names": ["杨嗣昌"]},
            {"body": "王承恩低语。", "role": "attendant", "audibility": "御前低语", "person_names": ["王承恩"]},
            {"body": "殿内烛影摇曳。", "role": "scene", "audibility": "殿上公开", "person_names": []},
        ],
    }, night_id=night_id, chat_turn_id=turn_id, minister_name="杨嗣昌")
    after = client.get("/api/audience/scroll").json()["messages"]
    assert client.get("/api/audience/scroll").json()["translation_pending"] is False
    segments = [m for m in after if m.get("chat_turn_id") == turn_id and m["role"] != "user"]
    assert [(m["role"], m["speaker"], m["content"]) for m in segments] == [
        ("minister", "杨嗣昌", "臣领旨。"), ("attendant", "王承恩", "王承恩低语。"),
        ("scene", "", "殿内烛影摇曳。"),
    ]
    assert segments[1]["audibility"] == "御前低语"
    assert segments[1]["beat"] == "aside"
    assert "".join(m["content"] for m in segments) == story
    assert [m for m in client.get(f"/api/audience/scroll?night_id={night_id}").json()["messages"] if m.get("chat_turn_id") == turn_id and m["role"] != "user"] == segments


def test_unnamed_speaker_cannot_finish_translation(game, monkeypatch):
    import pytest
    import web_app
    from ming_sim.audience_translate import AudienceTranslateError
    from ming_sim.audience_translation import apply_audience_round_translation

    db, state, _ = game
    night_id = open_audience_night(db, state)
    turn_id, _ = append_night_chat(db, state, night_id, "杨嗣昌", "何解？", "臣领旨。", 10)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))
    for role in ("minister", "attendant"):
        with pytest.raises(AudienceTranslateError):
            apply_audience_round_translation(db, state, {
                "scene_facts": [{"body": "臣领旨。", "role": role, "audibility": "殿上公开", "person_names": []}],
            }, night_id=night_id, chat_turn_id=turn_id)
    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    assert payload["translation_pending"] is True
    reply = next(m for m in payload["messages"]
                 if m.get("chat_turn_id") == turn_id and m["role"] != "user")
    assert (reply["role"], reply["speaker"]) == ("scene", "")


def test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 10)
    an.append_ledger_entry(
        db, night_id, tags=["站台", "作保"],
        person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, tags=["天气"],
        person_names=[], source_chat_turn_id=first_turn, order_key=10,
    )
    second_turn, _ = append_night_chat(db, state, night_id, "洪承畴", "边情如何？", "边关尚稳。", 20)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))

    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    messages = payload["messages"]
    dialogue = [message for message in messages
                if message.get("chat_turn_id") in {first_turn, second_turn}]
    assert [message["content"] for message in dialogue] == [
        "辽饷如何？", "臣请据实核账。", "边情如何？", "边关尚稳。",
    ]
    # Derived ledger entries do not become live dialogue records.
    assert not any(message.get("record_id") for message in messages)
    assert [message["content"] for message in messages if message["role"] == "scene" and message.get("chat_turn_id")] == ["臣请据实核账。", "边关尚稳。"]

    allowed_message_fields = {
        "role", "speaker", "audibility", "time", "content",
        "soft_boundary", "beat", "highlights", "container",
        "chat_turn_id", "record_id",
    }
    forbidden_character_stats = {"loyalty", "ability", "importance", "influence", "power", "favor"}
    assert messages
    base_message_fields = allowed_message_fields - {"chat_turn_id", "record_id"}
    for message in messages:
        expected_fields = set(base_message_fields)
        if message.get("chat_turn_id") in {first_turn, second_turn}:
            expected_fields.add("chat_turn_id")
            assert message["chat_turn_id"] > 0
        assert set(message) == expected_fields
        assert forbidden_character_stats.isdisjoint(message)
        assert forbidden_character_stats.isdisjoint(message["container"])
        assert set(message["container"]) == {"time_of_day", "location", "audience_type"}


def test_scroll_contract_merges_both_stores_with_container_and_coda(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.append_ledger_entry(db, night_id, tags=[an.TAG_ENTER], person_names=["杨嗣昌"])
    append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"] == {"time_of_day": "戌时", "location": "乾清宫", "audience_type": "召对"}
    assert [(m["role"], m["speaker"], m["content"]) for m in scroll if m["role"] != "scene"] == [
        ("user", "朕", "辽饷如何？"),
    ]
    assert any(m["role"] == "scene" and m.get("chat_turn_id") for m in scroll)
    assert all({"role", "speaker", "audibility", "time", "soft_boundary", "beat", "highlights", "container"} <= set(m) for m in scroll)
    assert not any(m.get("beat") == "coda" for m in scroll)  # #1838 reopen：无 coda


def test_presence_commands_only_record_facts(game):
    """入殿/告退只记事实账，戏文由场景 LLM 写。"""
    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.summon_enter(db, night_id, "杨嗣昌")
    an.dismiss_from_audience(db, "杨嗣昌", night_id=night_id)

    scroll = an.read_night_scroll(db, night_id)
    assert not any(m.get("beat") == "entrance" for m in scroll)
    assert not any(m.get("beat") == "exit" for m in scroll)
    # 事实账仍在
    tags_sets = [set(e.get("tags") or []) for e in an.list_ledger(db, night_id)]
    assert any(an.TAG_ENTER in ts and "杨嗣昌" in str(e.get("person_names"))
               for e, ts in zip(an.list_ledger(db, night_id), tags_sets))


def test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
    an.append_ledger_entry(db, night_id, tags=["人际动作"], person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10)
    an.append_ledger_entry(db, night_id, tags=[an.TAG_EXIT], person_names=["杨嗣昌"], body="杨嗣昌告退。")
    an.append_ledger_entry(db, night_id, tags=[an.TAG_ENTER], person_names=["洪承畴"])

    scroll = an.read_night_scroll(db, night_id)

    assert len([m for m in scroll
                if m.get("chat_turn_id") == first_turn and m["role"] != "user"]) == 1
    # #1838：无 entrance 卡；exit 有正文 + divider
    segment = [m["beat"] for m in scroll if m["beat"] in {"exit", "divider"}]
    assert "exit" in segment and "divider" in segment
    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["soft_boundary"] is True
    assert divider["speaker"] == "洪承畴"


def test_extractor_open_tags_do_not_drive_beat_or_soft_boundary(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    turn_id, _ = append_night_chat(db, state, night_id, "杨嗣昌", "说下去。", "臣遵旨。", 10)
    an.append_ledger_entry(
        db, night_id, tags=[an.TAG_ENTER],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, tags=[an.TAG_EXIT],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )

    scroll = an.read_night_scroll(db, night_id)

    # Derived entries are not dialogue, regardless of their prose.
    assert not any(message.get("record_id") for message in scroll)
    assert not any(message["beat"] == "divider" and message["speaker"] == "洪承畴" for message in scroll)


def test_scroll_container_presents_audience_type_from_persisted_summon_method(game):
    """#1838：入殿正文恒空不进卷轴；audience_type 仍由入殿召法 tag 派生。"""
    db, state, _ = game
    yueci_night = open_audience_night(db, state)
    an.summon_enter(db, yueci_night, "杨嗣昌", method=an.METHOD_YUECI)
    append_night_chat(db, state, yueci_night, "杨嗣昌", "问", "答", 10)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (yueci_night,))
    ordinary_night = open_audience_night(db, state)
    an.summon_enter(db, ordinary_night, "洪承畴", method=an.METHOD_XUANRU)
    append_night_chat(db, state, ordinary_night, "洪承畴", "问", "答", 10)

    yueci_scroll = an.read_night_scroll(db, yueci_night)
    ordinary_scroll = an.read_night_scroll(db, ordinary_night)

    assert yueci_scroll[0]["container"]["audience_type"] == "越次召对"
    assert ordinary_scroll[0]["container"]["audience_type"] == "召对"


def test_scroll_without_next_entrance_has_unnamed_boundary(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.append_ledger_entry(
        db, night_id, tags=[an.TAG_EXIT], person_names=["杨嗣昌"], body="杨嗣昌告退。",
    )

    scroll = an.read_night_scroll(db, night_id)

    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["speaker"] == ""


def test_same_departure_facts_emit_one_divider_but_later_departure_survives(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
    an.append_ledger_entry(
        db, night_id, tags=[an.TAG_EXIT],
        person_names=["杨嗣昌"], order_key=10, body="杨嗣昌告退。",
    )
    an.append_ledger_entry(
        db, night_id, tags=[], person_names=["杨嗣昌"],
        presence_effect=an.PRESENCE_EXIT, source_chat_turn_id=first_turn, order_key=10,
        body="杨嗣昌再退。",
    )
    an.append_ledger_entry(
        db, night_id, tags=[an.TAG_EXIT],
        person_names=["杨嗣昌"], order_key=20, body="杨嗣昌三退。",
    )

    dividers = [message for message in an.read_night_scroll(db, night_id) if message["beat"] == "divider"]

    assert len(dividers) >= 2


def test_history_turns_lists_every_closed_night_including_night_only_turns(game, monkeypatch):
    import web_app

    db, state, _ = game
    first = open_audience_night(db, state)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (first,))
    second = open_audience_night(db, state)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (second,))
    db.conn.commit()
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))

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


def test_closed_night_archive_derives_stable_titles_people_and_no_content(game):
    db, state, _ = game
    first = open_audience_night(db, state)
    an.summon_enter(db, first, "杨嗣昌", method=an.METHOD_YUECI)
    an.append_ledger_entry(db, first, tags=["军务"], person_names=["洪承畴", "杨嗣昌"])
    append_night_chat(db, state, first, "孙传庭", "边饷如何？", "尚可支应。", 10)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (first,))
    second = open_audience_night(db, state)
    append_night_chat(db, state, second, "洪承畴", "再议。", "臣遵旨。", 10)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (second,))
    db.conn.commit()

    entries = db.list_closed_night_archives()

    assert [item["night_id"] for item in entries] == [first, second]
    assert [item["title"] for item in entries] == [
        f"{state.year}年{state.period}月 · 戌时乾清宫 · 越次召对 · 第1场",
        f"{state.year}年{state.period}月 · 戌时乾清宫 · 召对 · 第2场",
    ]
    assert entries[0]["audience_type"] == "越次召对"
    assert entries[0]["involved_people"] == ["王承恩", "杨嗣昌", "洪承畴", "孙传庭"]
    assert entries[1]["involved_people"] == ["王承恩", "洪承畴"]
    assert all("messages" not in item and "content" not in item for item in entries)


def test_closed_night_archive_batches_each_metadata_store_once(game):
    db, state, _ = game
    for minister in ("杨嗣昌", "洪承畴", "孙传庭"):
        night_id = open_audience_night(db, state)
        an.summon_enter(db, night_id, minister, method=an.METHOD_YUECI)
        append_night_chat(db, state, night_id, minister, "问话", "答复", 10)
        db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (night_id,))
    db.conn.commit()
    statements = []
    db.conn.set_trace_callback(statements.append)

    entries = db.list_closed_night_archives()

    db.conn.set_trace_callback(None)
    selects = [" ".join(statement.lower().split()) for statement in statements if statement.lstrip().lower().startswith("select")]
    assert len(entries) == 3
    assert sum(" from audience_nights " in statement for statement in selects) == 1
    assert sum(" from story_ledger_entries " in statement for statement in selects) == 1
    assert sum(" from chat_turns " in statement for statement in selects) == 1


def test_read_night_scroll_reads_each_metadata_store_once(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.summon_enter(db, night_id, "杨嗣昌", method=an.METHOD_YUECI)
    append_night_chat(db, state, night_id, "杨嗣昌", "问话", "答复", 10)
    statements = []
    db.conn.set_trace_callback(statements.append)

    scroll = an.read_night_scroll(db, night_id)

    db.conn.set_trace_callback(None)
    selects = [" ".join(statement.lower().split()) for statement in statements if statement.lstrip().lower().startswith("select")]
    assert scroll[0]["container"]["audience_type"] == "越次召对"
    assert sum(" from story_ledger_entries " in statement for statement in selects) == 1
    assert sum(" from chat_turns " in statement for statement in selects) == 1


def test_personal_projection_only_reads_the_current_open_night(game):
    db, state, _ = game
    old_night = open_audience_night(db, state)
    append_night_chat(db, state, old_night, "杨嗣昌", "旧夜问话", "旧夜答复", 10)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (old_night,))
    current_night = open_audience_night(db, state)
    current_turn, _ = append_night_chat(db, state, current_night, "杨嗣昌", "本夜问话", "本夜答复", 10)

    projection = db.build_chat_projection("杨嗣昌")

    assert [message["content"] for message in projection] == ["本夜问话", "本夜答复"]
    assert {message["chat_turn_id"] for message in projection} == {current_turn}
