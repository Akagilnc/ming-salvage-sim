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


def test_public_directive_remains_visible_on_a_later_turn(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.conn.execute(
        "INSERT INTO turn_directives (turn, year, period, text, source, status) VALUES (?, ?, ?, ?, ?, 'issued')",
        (state.turn, state.year, state.period, "奉天承运，明发清丈诏。", "test"),
    )
    db.conn.commit()

    later = db.load_state()
    later.turn += 1
    view = db.get_character_knowledge(later, minister.name)

    assert any("明发清丈诏" in item["body"] for item in view["public_events"])


def test_excluded_participant_event_is_not_visible_to_excluded_character(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.record_character_participation(
        state,
        [minister.name],
        "secret_order",
        "密查亏空",
        "查户部旧账",
        source_id="secret_order:excluded",
        excluded_names=[minister.name],
    )

    view = db.get_character_knowledge(state, minister.name)

    assert not any(item["source_id"] == "secret_order:excluded" for item in view["events"])


def test_secret_blacklist_survives_later_public_projection(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_names=[minister.name]
    )
    db.record_public_knowledge_event(
        state, "密查公开", "该案已奉明发", source_id=f"secret_order:{order}"
    )

    view = db.get_character_knowledge(db.load_state(), minister.name)

    assert not any(item["source_id"] == f"secret_order:{order}" for item in view["public_events"])


def test_public_reports_accumulate_across_turns(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.save_turn_report(state, "第一回合：清丈已明发。")
    later = db.load_state()
    later.turn += 2
    db.save_turn_report(later, "第三回合：军务有变。")

    view = db.get_character_knowledge(later, minister.name)

    bodies = [item["body"] for item in view["public_events"]]
    assert "第一回合：清丈已明发。" in bodies
    assert "第三回合：军务有变。" in bodies


def test_participation_record_adapter_covers_assignment_shape(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.record_participation_record(
        state,
        {"participants": [minister.name], "title": "清丈差事", "body": "奉命督办"},
        kind="assignment",
        source_id="assignment:1",
    )

    view = db.get_character_knowledge(state, minister.name)

    assert any(item["source_id"] == "assignment:1" for item in view["events"])


def test_issue_write_path_projects_participants_across_restore(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="清丈差事",
        origin_kind="decree",
        origin_ref="decree:1",
        participants=[minister.name],
        stage_text="奉命督办",
    )

    row = db.conn.execute("SELECT participants FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row["participants"] == f'["{minister.name}"]'
    before = db.get_character_knowledge(state, minister.name)

    restored = db.load_state()
    after = db.get_character_knowledge(restored, minister.name)

    assert any(item["source_id"] == f"issue:{issue_id}" for item in before["events"])
    assert before["events"] == after["events"]


def test_knowledge_world_is_qualitative_not_numeric(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "户部")

    view = db.get_character_knowledge(state, minister.name)

    assert "treasury" in view["world"]
    assert not any(char.isdigit() for char in view["world"]["treasury"])


def test_secret_office_exclusion_blocks_dynamic_office_bucket(game):
    db, state, content = game
    clerk = next(c for c in content.characters.values() if c.office_type == "户部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_offices=["户部"]
    )
    view = db.get_character_knowledge(state, clerk.name)

    assert db.list_secret_orders()[0]["excluded_targets"] == {"people": [], "offices": ["户部"]}
    assert view["world"]["public"] == "登基伊始，朝廷暂无前回合奏报。"
    assert view["world"].get("treasury", "") == ""
    assert not any(item["source_id"] == f"secret_order:{order}" for item in view["events"])


def test_issue_roster_is_structured_and_read_side_projection_needs_no_write_hook(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    issue_id = db.insert_issue(
        state, kind="initiative", title="清丈差事", participants=[
            {"character_id": minister.name, "tier": "主办", "role": "监理", "delegator_id": "毕自严"}
        ]
    )
    row = db.conn.execute("SELECT participants, participant_roster FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row["participants"] == f'["{minister.name}"]'
    assert '"tier": "主办"' in row["participant_roster"]
    assert any(item["source_id"] == f"issue:{issue_id}" for item in db.get_character_knowledge(state, minister.name)["events"])


def test_participation_adapter_reads_structured_roster_without_fake_names(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.record_participation_record(
        state,
        {
            "participant_roster": [{"character_id": minister.name, "tier": "主办", "role": "督办"}],
            "title": "清丈差事",
            "body": "奉命督办",
        },
        kind="assignment",
        source_id="assignment:structured",
    )

    view = db.get_character_knowledge(state, minister.name)

    assert any(item["source_id"] == "assignment:structured" for item in view["events"])
