"""#1829 公开说法：独立记录入 0034 公开层，不冒充实况。"""

from __future__ import annotations

import json
import shutil
import threading

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

    from ming_sim.declaration_dispatch import dispatch_declaration
    result = dispatch_declaration(db, state, {"public_sayings": [{
        "body": "袁崇焕已死于宁远", "involved_characters": ["袁崇焕"],
    }]}, minister_name=reader.name)
    assert result.public_sayings.rejected == []
    saying_id = result.public_sayings.applied[0]["id"]
    source_id = f"public_saying:{saying_id}"

    view = db.get_character_knowledge(state, reader.name)
    public = view["public_events"]
    saying = next(
        item for item in public
        if str(item.get("source_id") or "") == source_id
    )
    assert saying["body"] == "袁崇焕已死于宁远"

    status, _ = db.get_character_status("袁崇焕")
    assert status != "dead"


def _saying_hits_on(db, state, name: str, source_id: str) -> list[dict]:
    """按 typed source_id 回读公开层，不按输出措辞断言。"""
    view = db.get_character_knowledge(state, name)
    return [
        item for item in view["public_events"]
        if str(item.get("source_id") or "") == source_id
    ]




def test_public_saying_survives_same_turn_archive_projection(game):
    db, state, content = game
    reader = _礼部大臣(content)
    claim = "袁崇焕已死于宁远"
    saying_id = record_public_saying(db, state, claim, involved_characters=["袁崇焕"])
    source_id = f"public_saying:{saying_id}"
    db.save_turn_report(state, f"本月邸报亦录：{claim}", public_body=f"本月邸报亦录：{claim}")

    view = db.get_character_knowledge(state, reader.name)
    saying = next(
        item for item in view["public_events"]
        if str(item.get("source_id") or "") == source_id
    )
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
