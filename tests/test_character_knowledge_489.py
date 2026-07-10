"""#489 角色见闻：职位裁切、公开事件与参与留痕。"""

from ming_sim.models import Character


def test_turn_zero_knowledge_is_role_specific_and_restores(game):
    db, state, content = game
    household = next(c for c in content.characters.values() if c.office_type == "户部")
    war = next(c for c in content.characters.values() if c.office_type == "兵部")

    household_view = db.get_character_knowledge(state, household.name)
    war_view = db.get_character_knowledge(state, war.name)

    assert household_view["turn"] == state.turn
    assert household_view["office_type"] == "户部"
    assert household_view["world"] != war_view["world"]
    assert household_view["world"]["treasury"]
    assert war_view["world"]["military"]


def test_public_directive_is_seen_by_uninvolved_minister_but_secret_exclusion_wins(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_names=[minister.name]
    )
    db.record_public_knowledge_event(state, "明发清丈诏", "全国清丈田亩")

    view = db.get_character_knowledge(state, minister.name)

    assert any("明发清丈诏" in item["title"] for item in view["public_events"])
    assert not any(item.get("source_id") == f"secret_order:{order}" for item in view["events"])


def test_participation_survives_restore(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "内阁")
    db.record_character_participation(
        state, [minister.name], "audience", "召对议饷", "议定辽饷缓急"
    )
    before = db.get_character_knowledge(state, minister.name)

    db.conn.commit()
    restored = db.load_state()
    after = db.get_character_knowledge(restored, minister.name)

    assert before["events"] == after["events"]
    assert after["events"][0]["title"] == "召对议饷"
