"""#1829 公开说法：独立记录入 0034 公开层，不冒充实况。"""

from __future__ import annotations

import shutil
import threading

import ming_sim.month_chain as month_chain
from ming_sim.audience_night import open_night
from types import SimpleNamespace

from ming_sim.session import GameSession
from ming_sim.db import GameDB
from ming_sim.models import LLMConfig
from ming_sim.public_sayings import list_public_sayings, record_public_saying
from tests.conftest import (
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
    stub_scene_agent,
)
from tests.test_month_chain_1843 import _prepare_player_month


def _礼部大臣(content):
    return next(c for c in content.characters.values() if c.office_type == "礼部")


def _active_other(db, content, *, exclude: set[str]) -> str:
    for character in content.characters.values():
        if character.name in exclude:
            continue
        if character.office_type in ("后宫", "宗藩", "未仕"):
            continue
        if db.get_character_status(character.name)[0] != "active":
            continue
        return character.name
    raise AssertionError("no other active minister")


def test_yuan_public_death_rumor_does_not_change_actual_life(game, tmp_path):
    db, state, content = game
    status_before, _ = db.get_character_status("袁崇焕")
    assert status_before != "dead"

    saying_id = record_public_saying(
        db,
        state,
        "袁崇焕已死于宁远",
        involved_characters=["袁崇焕"],
    )

    status_after, _ = db.get_character_status("袁崇焕")
    assert status_after == status_before
    rows = list_public_sayings(db)
    assert len(rows) == 1
    assert rows[0]["id"] == saying_id
    assert rows[0]["body"] == "袁崇焕已死于宁远"
    assert rows[0]["involved_characters"] == ["袁崇焕"]
    assert rows[0]["affair_ref"] == ""

    shutil.copy(db.path, tmp_path / "save.db")
    restored = GameDB(str(tmp_path / "save.db"), content)
    try:
        restored_state = restored.load_state()
        restored_status, _ = restored.get_character_status("袁崇焕")
        assert restored_status == status_before
        restored_rows = list_public_sayings(restored)
        assert restored_rows[0]["body"] == "袁崇焕已死于宁远"
        view = restored.get_character_knowledge(restored_state, _礼部大臣(content).name)
        assert any(
            item.get("source_id") == restored_rows[0]["source_id"]
            for item in view["public_events"]
        )
    finally:
        restored.close()


def test_absent_minister_reads_saying_not_actual_status(game):
    db, state, content = game
    reader = _礼部大臣(content)
    assert reader.name != "袁崇焕"

    record_public_saying(
        db,
        state,
        "袁崇焕已死于宁远",
        involved_characters=["袁崇焕"],
    )

    view = db.get_character_knowledge(state, reader.name)
    public = view["public_events"]
    saying = next(
        item for item in public
        if str(item.get("source_id") or "").startswith("public_saying:")
    )
    assert saying["title"] == "有此说法"
    assert saying["body"] == "袁崇焕已死于宁远"

    status, _ = db.get_character_status("袁崇焕")
    assert status != "dead"
    # 公开层是说法，不是把实况改成死讯。
    known_items = list(view.get("events") or []) + list(public)
    assert not any(
        item.get("kind") == "character_status" and "死" in str(item.get("body") or "")
        for item in known_items
    )


def test_public_saying_excluded_name_does_not_see_it_others_do(game, monkeypatch):
    """#1829 reopen：召对转译落账 + 玩家过月主链后，被瞒者零条、其余恰一条。"""
    db, state, content = game
    excluded_name = _礼部大臣(content).name
    other_name = _active_other(db, content, exclude={excluded_name, "袁崇焕"})
    claim = "袁崇焕已死于宁远"

    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    def translate_fn(prompt, config):
        return {
            **offline_empty_audience_translate(prompt, config),
            "public_sayings": [{
                "body": claim,
                "involved_characters": ["袁崇焕"],
                "excluded_names": [excluded_name],
                "excluded_offices": [],
            }],
            "scene_facts": [{
                "body": "臣遵旨。", "role": "minister", "audibility": "殿上公开", "person_names": [other_name],
            }],
        }

    class Agent:
        def run(self, message):
            return SimpleNamespace(content="臣遵旨。", tools=[])

    stub_scene_agent(monkeypatch, Agent())
    stub_audience_translate(monkeypatch, translate_fn)
    session = GameSession.__new__(GameSession)
    session.db, session.state, session.content = db, state, content
    session.registry = None
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    session.temporary_characters = {}
    session.agno_db = None
    session._beat_generator = None
    session._scene_registry = None
    session._write_gate = threading.Lock()
    chat_turn_id = int(db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night["id"]), status="active",
    ))
    reply = session.scene_chat("对外只说此事，勿使某人得知。", chat_turn_id=chat_turn_id)
    pending = persist_and_schedule_scene(session, db, reply)
    assert pending is not None
    pending.result()
    sayings = list_public_sayings(db)
    assert len(sayings) == 1
    saying_id = int(sayings[0]["id"])
    source_id = f"public_saying:{saying_id}"
    assert db.conn.execute(
        "SELECT 1 FROM character_knowledge_sources WHERE source_id=?", (source_id,),
    ).fetchone() is None
    saying = next(row for row in list_public_sayings(db) if row["id"] == saying_id)
    assert saying["body"] == claim
    assert excluded_name in saying["excluded_names"]

    # 现役玩家过月主链（resolve_directives → run_player_month_chain）；只替 LLM 缝。
    before_turn = int(state.turn)
    monkeypatch.setattr(
        month_chain, "run_gazette_text",
        lambda *_a, **_k: ("邸报", "本月朝局如常"),
    )
    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_tail_body", lambda *_a, **_k: "done",
    )
    session = _prepare_player_month(db, state, content, monkeypatch)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    session._write_gate = threading.Lock()
    advanced = session.resolve_turn(allow_empty_decree=True)
    assert advanced.advanced is True
    assert int(state.turn) == before_turn + 1

    def _saying_hits(name: str):
        view = db.get_character_knowledge(state, name)
        return [
            item for item in view["public_events"]
            if str(item.get("source_id") or "") == source_id
        ]

    assert _saying_hits(excluded_name) == []
    other_hits = _saying_hits(other_name)
    assert len(other_hits) == 1
    assert other_hits[0]["title"] == "有此说法"
    assert other_hits[0]["body"] == claim
    assert db.conn.execute(
        "SELECT 1 FROM character_knowledge_events "
        "WHERE character_name='' AND source_id=?", (source_id,),
    ).fetchone() is None


def test_public_saying_survives_same_turn_archive_projection(game):
    db, state, content = game
    reader = _礼部大臣(content)
    claim = "袁崇焕已死于宁远"
    record_public_saying(db, state, claim, involved_characters=["袁崇焕"])
    db.save_turn_report(state, f"本月邸报亦录：{claim}", public_body=f"本月邸报亦录：{claim}")

    view = db.get_character_knowledge(state, reader.name)
    saying = next(
        item for item in view["public_events"]
        if str(item.get("source_id") or "").startswith("public_saying:")
    )
    assert saying["title"] == "有此说法"
    assert saying["body"] == claim


def test_public_saying_may_annotate_person_affair_or_neither(game):
    db, state, _content = game

    rumor_id = record_public_saying(db, state, "宫中有人夜见彗星")
    person_id = record_public_saying(
        db,
        state,
        "袁崇焕已死于宁远",
        involved_characters=["袁崇焕"],
    )
    affair_id = record_public_saying(
        db,
        state,
        "宁远兵变已平",
        involved_characters=["袁崇焕"],
        affair_ref="affair:ningyuan-mutiny",
    )

    rumor = next(row for row in list_public_sayings(db) if row["id"] == rumor_id)
    person = next(row for row in list_public_sayings(db) if row["id"] == person_id)
    affair = next(row for row in list_public_sayings(db) if row["id"] == affair_id)

    assert rumor["involved_characters"] == []
    assert rumor["affair_ref"] == ""
    assert person["involved_characters"] == ["袁崇焕"]
    assert person["affair_ref"] == ""
    assert affair["involved_characters"] == ["袁崇焕"]
    assert affair["affair_ref"] == "affair:ningyuan-mutiny"
    assert list_public_sayings(db, involved_character="袁崇焕") == [person, affair]
    assert list_public_sayings(db, affair_ref="affair:ningyuan-mutiny") == [affair]
    assert list_public_sayings(db, affair_ref="") == [rumor, person]
