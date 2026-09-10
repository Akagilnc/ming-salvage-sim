"""#1828 文字事实：追加、带月、挂对象；不当传闻、不转公式。"""

from __future__ import annotations

import json

from ming_sim.db import GameDB
from ming_sim.knowledge import build_character_knowledge, render_character_knowledge


INJURY = "孙传庭右臂受伤，暂时不能亲自挥刀，但仍能指挥军队"
RECOVERY = "已痊愈"


def test_sun_chuanting_injury_then_recovery_both_readable_by_month(game):
    db, state, _ = game
    assert state.year == 1627 and state.period == 10

    db.textual_facts.append(
        subject_kind="character",
        subject_id="孙传庭",
        body=INJURY,
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="character",
        subject_id="孙传庭",
        body=RECOVERY,
        year=state.year,
        period=state.period + 1,
        turn=state.turn + 1,
    )

    materials = db.textual_facts.readable_materials(
        subject_kind="character", subject_id="孙传庭",
    )
    assert [fact.body for fact in materials] == [INJURY, RECOVERY]
    assert [fact.occurred_month for fact in materials] == ["天启七年十月", "天启七年十一月"]


def test_textual_facts_on_army_region_and_affair_are_object_materials(game):
    db, state, _ = game
    army_id = db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"]
    region_id = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()["id"]

    db.textual_facts.append(
        subject_kind="army",
        subject_id=army_id,
        body="该营火器受潮，铳手暂不能齐放",
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="region",
        subject_id=region_id,
        body="城中疫气未散",
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair",
        subject_id="ningyuan-escort",
        body="护送银两已出京，尚未抵宁远",
        year=state.year,
        period=state.period,
        turn=state.turn,
    )

    assert [f.body for f in db.textual_facts.readable_materials(subject_kind="army", subject_id=army_id)] == [
        "该营火器受潮，铳手暂不能齐放",
    ]
    assert [f.body for f in db.textual_facts.readable_materials(subject_kind="region", subject_id=region_id)] == [
        "城中疫气未散",
    ]
    assert [f.body for f in db.textual_facts.readable_materials(subject_kind="affair", subject_id="ningyuan-escort")] == [
        "护送银两已出京，尚未抵宁远",
    ]
    assert db.textual_facts.readable_materials(subject_kind="character", subject_id="孙传庭") == ()


def test_textual_facts_are_not_rumors_and_do_not_change_character_mechanics(game):
    db, state, _ = game
    before_status, before_reason = db.get_character_status("孙传庭")
    before_row = db.conn.execute(
        "SELECT loyalty, ability, status FROM characters WHERE name=?",
        ("孙传庭",),
    ).fetchone()

    db.textual_facts.append(
        subject_kind="character",
        subject_id="孙传庭",
        body=INJURY,
        year=state.year,
        period=state.period,
        turn=state.turn,
    )

    after_status, after_reason = db.get_character_status("孙传庭")
    after_row = db.conn.execute(
        "SELECT loyalty, ability, status FROM characters WHERE name=?",
        ("孙传庭",),
    ).fetchone()
    assert (after_status, after_reason) == (before_status, before_reason)
    assert tuple(after_row) == tuple(before_row)

    knowledge = build_character_knowledge(db, state, "孙传庭")
    rendered = render_character_knowledge(knowledge, "孙传庭", db=db, state=state)
    dump = json.dumps(knowledge, ensure_ascii=False)
    assert INJURY not in dump
    assert INJURY not in rendered
    public = knowledge.get("public_events") or []
    private = knowledge.get("events") or []
    assert not any(INJURY in str(item.get("body") or "") for item in (*public, *private))


def test_textual_facts_survive_reopen(game, content):
    db, state, _ = game
    path = db.path
    db.textual_facts.append(
        subject_kind="character",
        subject_id="孙传庭",
        body=INJURY,
        year=state.year,
        period=state.period,
        turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="character",
        subject_id="孙传庭",
        body=RECOVERY,
        year=state.year,
        period=state.period + 1,
        turn=state.turn + 1,
    )
    db.close()

    restored = GameDB(path, content)
    try:
        materials = restored.textual_facts.readable_materials(
            subject_kind="character", subject_id="孙传庭",
        )
        assert [fact.body for fact in materials] == [INJURY, RECOVERY]
        assert [fact.occurred_month for fact in materials] == ["天启七年十月", "天启七年十一月"]
    finally:
        restored.close()
