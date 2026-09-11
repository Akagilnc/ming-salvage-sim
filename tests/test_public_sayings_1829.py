"""#1829 公开说法：独立记录入 0034 公开层，不冒充实况。"""

from __future__ import annotations

import shutil

from ming_sim.db import GameDB
from ming_sim.knowledge import render_character_knowledge
from ming_sim.public_sayings import list_public_sayings, record_public_saying


def _礼部大臣(content):
    return next(c for c in content.characters.values() if c.office_type == "礼部")


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
    assert "有此说法" in (view["world"].get("public") or "")
    rendered = render_character_knowledge(view, reader.name)
    assert "有此说法" in rendered
    assert "袁崇焕已死于宁远" in rendered

    status, _ = db.get_character_status("袁崇焕")
    assert status != "dead"
    # 公开层是说法，不是把实况改成死讯。
    known_items = list(view.get("events") or []) + list(public)
    assert not any(
        item.get("kind") == "character_status" and "死" in str(item.get("body") or "")
        for item in known_items
    )


def test_public_saying_survives_same_turn_archive_projection(game):
    db, state, content = game
    reader = _礼部大臣(content)
    claim = "袁崇焕已死于宁远"
    record_public_saying(db, state, claim, involved_characters=["袁崇焕"])
    db.save_turn_report(state, f"本月邸报亦录：{claim}", public_body=f"本月邸报亦录：{claim}")
    db.save_chapter_memory(state, "朝局", f"章节旧闻复述：{claim}")

    view = db.get_character_knowledge(state, reader.name)
    saying = next(
        item for item in view["public_events"]
        if str(item.get("source_id") or "").startswith("public_saying:")
    )
    assert saying["title"] == "有此说法"
    assert saying["body"] == claim
    public_text = view["world"].get("public") or ""
    assert "有此说法" in public_text
    assert claim in public_text


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
