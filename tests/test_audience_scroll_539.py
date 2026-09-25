"""Issue #539: night-scroll read contract at the audience-night public seam."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from ming_sim import audience_night as an
from ming_sim.audience_translation import list_pending_translations
from tests.conftest import append_night_chat, open_audience_night


def _archive_mindreading(db, chat_turn_id, *, target, narration):
    db.conn.execute(
        "INSERT INTO mindreading_records "
        "(chat_turn_id, reader, target, source, precision, narration) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (chat_turn_id, "王承恩", target, "察言观色", "约略", narration),
    )
    db.conn.commit()


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
        "/api/ministers/%E6%B8%A9%E4%BD%93%E4%BB%81/chat/stream",
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
        "/api/ministers/%E6%B8%A9%E4%BD%93%E4%BB%81/chat/stream",
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
    }
    assert live["status"] == "open"
    assert closed["status"] == "closed"


def test_empty_open_night_scroll_exposes_persisted_container(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = int(an.open_night(db, state, time_of_day="午时", location="文华殿", empty_scaffold=True)["id"])
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
        db, night_id, body="御前密奏。", tags=["scroll_role:attendant"],
        person_names=["杨嗣昌"], audibility="御前低语",
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
    reply = next(m for m in payload["messages"] if m["content"] == "臣领旨。")
    assert (reply["role"], reply["speaker"]) == ("scene", "")


def test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 10)
    _archive_mindreading(
        db, first_turn, target="杨嗣昌", narration="万岁爷，他尚有保留。",
    )
    an.append_ledger_entry(
        db, night_id, body="杨嗣昌以身家作保。", tags=["站台", "作保"],
        person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="帘外忽起雨声。", tags=["天气"],
        person_names=[], source_chat_turn_id=first_turn, order_key=10,
    )
    append_night_chat(db, state, night_id, "洪承畴", "边情如何？", "边关尚稳。", 20)
    monkeypatch.setattr(web_app, "get_game", lambda: _scroll_game(db))

    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    messages = payload["messages"]
    contents = [message["content"] for message in messages]

    assert [content for content in contents if content in {
        "辽饷如何？", "臣请据实核账。", "万岁爷，他尚有保留。", "边情如何？", "边关尚稳。",
    }] == ["辽饷如何？", "臣请据实核账。", "万岁爷，他尚有保留。", "边情如何？", "边关尚稳。"]
    assert "杨嗣昌以身家作保。" not in contents
    # #1293a：抽取派生（含非对话复述的故事事实）不上 live 卷轴
    assert "帘外忽起雨声。" not in contents
    assert [message["content"] for message in messages if message["role"] == "scene" and message.get("chat_turn_id")] == ["臣请据实核账。", "边关尚稳。"]

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
    night_id = open_audience_night(db, state)
    an.append_ledger_entry(db, night_id, body="帘外风紧。", tags=[an.TAG_ENTER], person_names=["杨嗣昌"])
    append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"] == {"time_of_day": "戌时", "location": "乾清宫", "audience_type": "召对"}
    assert [(m["role"], m["speaker"], m["content"]) for m in scroll if m["role"] != "scene"] == [
        ("user", "朕", "辽饷如何？"),
    ]
    assert any(m["role"] == "scene" and m["content"] == "臣请据实核账。" for m in scroll)
    assert all({"role", "speaker", "audibility", "time", "soft_boundary", "beat", "highlights", "container"} <= set(m) for m in scroll)
    assert scroll[-1]["beat"] == "coda"
    assert scroll[-1]["content"] == ""


def test_presence_commands_project_to_diegetic_scene_beats(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    baseline = len([
        message for message in an.read_night_scroll(db, night_id)
        if message["beat"] in {"entrance", "exit"}
    ])
    an.summon_enter(db, night_id, "杨嗣昌")
    an.dismiss_from_audience(db, "杨嗣昌", night_id=night_id, body="杨嗣昌退下。")

    scroll = an.read_night_scroll(db, night_id)
    presence = [
        message for message in scroll if message["beat"] in {"entrance", "exit"}
    ][baseline:]

    assert [(message["role"], message["beat"]) for message in presence] == [
        ("scene", "entrance"),
        ("scene", "exit"),
    ]
    assert all(message["content"] for message in presence)


def test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
    an.append_ledger_entry(db, night_id, body="臣告退。", tags=["人际动作"], person_names=["杨嗣昌"], source_chat_turn_id=first_turn, order_key=10)
    an.append_ledger_entry(db, night_id, body="杨嗣昌退下。", tags=[an.TAG_EXIT], person_names=["杨嗣昌"])
    an.append_ledger_entry(db, night_id, body="洪承畴入殿。", tags=[an.TAG_ENTER], person_names=["洪承畴"])

    scroll = an.read_night_scroll(db, night_id)

    assert [m["content"] for m in scroll].count("臣告退。") == 1
    segment = [m["beat"] for m in scroll if m["beat"] in {"exit", "divider", "entrance"}]
    assert segment[-3:] == ["exit", "divider", "entrance"]
    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["soft_boundary"] is True
    assert divider["speaker"] == "洪承畴"


def test_scroll_merges_mindreading_and_uses_structured_dedup_boundaries(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    turn_id, _ = append_night_chat(db, state, night_id, "杨嗣昌", "卿可担名？", "臣愿当面作保。", 10)
    _archive_mindreading(
        db, turn_id, target="杨嗣昌", narration="万岁爷，他这话留了半分。",
    )
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
    # #1293a：抽取派生故事事实不上卷轴；王承恩读心旁白仍在
    assert "帘外忽起雨声。" not in [message["content"] for message in scroll]


def test_extractor_open_tags_do_not_drive_beat_or_soft_boundary(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    turn_id, _ = append_night_chat(db, state, night_id, "杨嗣昌", "说下去。", "臣遵旨。", 10)
    an.append_ledger_entry(
        db, night_id, body="只是提到了入殿旧事。", tags=[an.TAG_ENTER],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )
    an.append_ledger_entry(
        db, night_id, body="又提到了告退旧事。", tags=[an.TAG_EXIT],
        person_names=["洪承畴"], source_chat_turn_id=turn_id, order_key=10,
    )

    scroll = an.read_night_scroll(db, night_id)

    contents = [message["content"] for message in scroll]
    # #1293a：抽取派生（含开放 tag 的伪入殿/告退提及）不上卷轴，更不驱动 beat/divider
    assert "只是提到了入殿旧事。" not in contents
    assert "又提到了告退旧事。" not in contents
    assert not any(message["beat"] == "divider" and message["speaker"] == "洪承畴" for message in scroll)


def test_scroll_container_presents_audience_type_from_persisted_summon_method(game):
    db, state, _ = game
    yueci_night = open_audience_night(db, state)
    an.summon_enter(db, yueci_night, "杨嗣昌", method=an.METHOD_YUECI)
    db.conn.execute("UPDATE audience_nights SET status='closed' WHERE id=?", (yueci_night,))
    ordinary_night = open_audience_night(db, state)
    an.summon_enter(db, ordinary_night, "洪承畴", method=an.METHOD_XUANRU)

    yueci_scroll = an.read_night_scroll(db, yueci_night)
    ordinary_scroll = an.read_night_scroll(db, ordinary_night)

    assert yueci_scroll[0]["container"]["audience_type"] == "越次召对"
    assert ordinary_scroll[0]["container"]["audience_type"] == "召对"


def test_scroll_without_next_entrance_has_unnamed_boundary(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.append_ledger_entry(db, night_id, body="众臣告退。", tags=[an.TAG_EXIT], person_names=["杨嗣昌"])

    scroll = an.read_night_scroll(db, night_id)

    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["speaker"] == ""


def test_same_departure_facts_emit_one_divider_but_later_departure_survives(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "退下。", "臣告退。", 10)
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
    an.append_ledger_entry(db, first, body="密议边饷。", tags=["军务"], person_names=["洪承畴", "杨嗣昌"])
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


# ---------------------------------------------------------------------------
# #657 片3 S4：P7 三写口空垫位不可见
# ---------------------------------------------------------------------------

def test_657_s4_empty_scaffold_open_enter_and_scene_not_on_scroll(game):
    """generator 未完成期：scroll 无空 OPEN/ENTER/普通 scene。"""
    from ming_sim.audience_night import (
        append_ledger_entry,
        open_night,
        prepare_rescript_summon_scaffold,
        read_night_scroll,
        rescript_summon_origin_ref,
    )

    db, state, _content = game
    night = open_night(db, state, empty_scaffold=True)
    origin = rescript_summon_origin_ref(int(state.turn), 0, 0)
    prepare_rescript_summon_scaffold(
        db, state, person_name="杨嗣昌", origin_ref=origin,
    )
    append_ledger_entry(db, int(night["id"]), body="", tags=["军务"])
    scroll = read_night_scroll(db, int(night["id"]))
    openings = [m for m in scroll if m.get("beat") == "opening"]
    entrances = [m for m in scroll if m.get("beat") == "entrance"]
    scenes = [m for m in scroll if m.get("beat") == "scene"]
    # 空垫位 OPEN/ENTER 与普通公共 scene 均不得投影
    assert openings == []
    assert entrances == []
    assert scenes == []


def test_657_s4_success_persist_shows_generator_body_only(game):
    """成功后 scroll 仅 generator 原文。"""
    from ming_sim.audience_night import (
        prepare_rescript_summon_scaffold,
        read_night_scroll,
        rescript_summon_origin_ref,
    )
    from ming_sim.beat_orchestration import persist_chat_turn_scene

    db, state, _content = game
    origin = rescript_summon_origin_ref(int(state.turn), 1, 0)
    sc = prepare_rescript_summon_scaffold(
        db, state, person_name="杨嗣昌", origin_ref=origin,
    )
    gen_body = "杨嗣昌趋步入殿，顿首请安。"
    persist_chat_turn_scene(db, [(int(sc["entry_id"]), gen_body)])
    db.conn.commit()
    scroll = read_night_scroll(db, int(sc["night_id"]))
    entrances = [m for m in scroll if m.get("beat") == "entrance"]
    assert [m.get("content") for m in entrances] == [gen_body]
