"""Issue #539: night-scroll read contract at the audience-night public seam."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from ming_sim import audience_night as an
from tests.conftest import append_night_chat, open_audience_night


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
    assert events == [
        ("accepted", {"campaign_id": "", "night_id": int(persisted["id"]), "chat_turn_id": 1}),
        ("error", {"message": "reply failed", "campaign_id": "", "night_id": int(persisted["id"]), "chat_turn_id": 1}),
    ]
    assert int(persisted["id"]) != old_night_id
    assert int(persisted["turn"]) == int(state.turn)


def test_live_and_closed_night_share_the_real_http_contract(game, monkeypatch):
    import web_app

    db, state, _ = game
    night_id = open_audience_night(db, state)
    append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)
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
    night_id = open_audience_night(db, state)
    first_turn, _ = append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 10)
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
    append_night_chat(db, state, night_id, "洪承畴", "边情如何？", "边关尚稳。", 20)
    monkeypatch.setattr(web_app, "get_game", lambda: SimpleNamespace(db=db))

    payload = TestClient(web_app.app).get("/api/audience/scroll").json()
    messages = payload["messages"]
    contents = [message["content"] for message in messages]

    assert [content for content in contents if content in {
        "辽饷如何？", "臣请据实核账。", "万岁爷，他尚有保留。", "边情如何？", "边关尚稳。",
    }] == ["辽饷如何？", "臣请据实核账。", "万岁爷，他尚有保留。", "边情如何？", "边关尚稳。"]
    assert "杨嗣昌以身家作保。" not in contents
    # #1293a：抽取派生（含非对话复述的故事事实）不上 live 卷轴
    assert "帘外忽起雨声。" not in contents
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
    night_id = open_audience_night(db, state)
    an.append_ledger_entry(db, night_id, body="帘外风紧。", tags=[an.TAG_ENTER], person_names=["杨嗣昌"])
    append_night_chat(db, state, night_id, "杨嗣昌", "辽饷如何？", "臣请据实核账。", 20)

    scroll = an.read_night_scroll(db, night_id)

    assert scroll[0]["container"] == {"time_of_day": "戌时", "location": "乾清宫", "audience_type": "召对"}
    assert [(m["role"], m["speaker"], m["content"]) for m in scroll if m["role"] != "scene"] == [
        ("user", "朕", "辽饷如何？"),
        ("minister", "杨嗣昌", "臣请据实核账。"),
    ]
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
    an.dismiss_from_audience(db, "杨嗣昌", night_id=night_id)

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
    divider = next(m for m in scroll if m["beat"] == "divider")
    assert divider["soft_boundary"] is True
    assert divider["speaker"] == "洪承畴"


def test_scroll_merges_mindreading_and_uses_structured_dedup_boundaries(game):
    db, state, _ = game
    night_id = open_audience_night(db, state)
    turn_id, _ = append_night_chat(db, state, night_id, "杨嗣昌", "卿可担名？", "臣愿当面作保。", 10)
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


def test_extraction_derived_facts_stay_off_live_scroll_but_remain_in_ledger(game):
    """#1293a：结构 provenance（source_chat_turn_id>0）排除抽取派生卡出 live 卷轴。

    正向：对话原话 + beat/旁白/divider/coda 在；转述/抽取散文不在。
    负向：list_ledger 记忆读端仍见 story facts（抽取照跑照入档）。
    """
    db, state, _ = game
    night_id = open_audience_night(db, state)
    an.summon_enter(db, night_id, "杨嗣昌")
    turn_id, _ = append_night_chat(
        db, state, night_id, "杨嗣昌",
        "辽饷如何？", "臣请据实核账，不敢欺瞒。", 10,
    )
    db.record_mindreading(turn_id, {
        "reader": "王承恩", "target": "杨嗣昌", "source": "察言观色",
        "precision": "约略", "narration": "万岁爷，他话里留了半分。",
    })
    # 经抽取唯一入口落账——结构上 source_chat_turn_id=轮（非盯文本）
    paraphrase = "皇帝询问辽饷，杨嗣昌答称当据实核账。"
    atmosphere = "殿角烛火轻颤。"
    db.settle_story_extraction(
        turn_id, night_id,
        [
            {
                "person_names": ["杨嗣昌"],
                "audibility": "殿上公开",
                "body": paraphrase,
                "tags": ["对话摘要"],
                "presence_effect": "",
            },
            {
                "person_names": [],
                "audibility": "殿上公开",
                "body": atmosphere,
                "tags": ["场景"],
                "presence_effect": "",
            },
        ],
        10,
    )
    an.dismiss_from_audience(db, "杨嗣昌", night_id=night_id)

    scroll = an.read_night_scroll(db, night_id)
    contents = [m["content"] for m in scroll]
    beats = {m["beat"] for m in scroll}

    # 正向：原话在
    assert "辽饷如何？" in contents
    assert "臣请据实核账，不敢欺瞒。" in contents
    # 正向：王承恩旁白 / entrance·exit beat / divider / coda 在
    assert "万岁爷，他话里留了半分。" in contents
    assert "entrance" in beats
    assert "exit" in beats
    assert "divider" in beats
    assert scroll[-1]["beat"] == "coda"
    # 正向：抽取转述与派生场景卡零出现
    assert paraphrase not in contents
    assert atmosphere not in contents
    assert not any(
        m["role"] == "scene" and m["content"] in {paraphrase, atmosphere}
        for m in scroll
    )

    # 负向：记忆读端（list_ledger）仍见 story facts
    ledger_bodies = {
        e["body"] for e in an.list_ledger(db, night_id)
        if int(e.get("source_chat_turn_id") or 0) == turn_id
    }
    assert paraphrase in ledger_bodies
    assert atmosphere in ledger_bodies


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

def test_657_s4_empty_scaffold_open_enter_roster_not_on_scroll(game):
    """generator 未完成期：scroll 无空 OPEN/ENTER。"""
    from ming_sim.audience_night import (
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
    scroll = read_night_scroll(db, int(night["id"]))
    openings = [m for m in scroll if m.get("beat") == "opening"]
    entrances = [m for m in scroll if m.get("beat") == "entrance"]
    # 空垫位 OPEN/ENTER 不得投影
    assert openings == []
    assert entrances == []


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
