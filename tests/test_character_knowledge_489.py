"""#489 角色见闻：职位裁切、公开事件与参与留痕。"""

import json

from ming_sim.models import Character


def test_every_supported_office_type_has_a_role_specific_current_world_slice(game):
    db, state, content = game
    characters_by_type = {
        character.office_type: character
        for character in content.characters.values()
        if character.office_type
    }

    for office_type, domains in content.office_knowledge_domains.items():
        character = characters_by_type.get(office_type)
        if character is None:
            continue
        world = db.get_character_knowledge(state, character.name)["world"]
        assert domains[0] in world, office_type
        assert len(world) > 1, office_type


def test_every_character_office_type_has_a_content_knowledge_mapping(game):
    _db, _state, content = game

    character_types = {
        character.office_type
        for character in content.characters.values()
        if character.office_type
    }

    assert character_types <= set(content.office_knowledge_domains)


def test_generic_offices_receive_distinct_current_world_slices(game):
    db, state, content = game

    expected_domains = {
        # These offices have no dedicated numeric/report rail yet.  Their
        # closest current-state rails are still better than a public-only view.
        "礼部": {"personnel"},
        "刑部": {"security"},
        "翰林院": {"personnel"},
        "都察院": {"personnel", "security"},
    }
    views = {
        office_type: db.get_character_knowledge(
            state,
            next(c.name for c in content.characters.values()
                 if c.office_type == office_type),
        )["world"]
        for office_type in expected_domains
    }

    for office_type, domains in expected_domains.items():
        assert domains <= views[office_type].keys(), office_type
        assert views[office_type]["public"]
    assert views["礼部"] != views["刑部"]
    assert views["刑部"] != views["都察院"]


def test_office_slice_does_not_read_unrelated_sensitive_reports(game, monkeypatch):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")

    def forbidden(*args, **kwargs):
        raise AssertionError("礼部见闻不应读取军情或国库报告")

    monkeypatch.setattr(db, "army_report", forbidden)
    monkeypatch.setattr(db, "treasury_report", forbidden)

    view = db.get_character_knowledge(state, minister.name)

    assert "personnel" in view["world"]
    assert "military" not in view["world"]
    assert "treasury" not in view["world"]


def test_every_distinct_office_type_gets_a_distinct_current_world_slice(game):
    db, state, content = game
    characters_by_type = {
        character.office_type: character
        for character in content.characters.values()
        if character.office_type in content.office_knowledge_domains
    }

    views = {
        office_type: db.get_character_knowledge(state, character.name)["world"]
        for office_type, character in characters_by_type.items()
    }

    office_types = sorted(views)
    for index, office_type in enumerate(office_types):
        for other_type in office_types[index + 1:]:
            assert views[office_type] != views[other_type], (
                f"{office_type} 与 {other_type} 不应共享完全相同的见闻切片"
            )


def test_role_slice_contains_only_the_current_office_roster(game):
    db, state, content = game
    characters_by_type = {
        character.office_type: character
        for character in content.characters.values()
        if character.office_type in content.office_knowledge_domains
    }

    for office_type, character in characters_by_type.items():
        world = db.get_character_knowledge(state, character.name)["world"]
        role_facts = world["role"]

        assert office_type in role_facts
        for name, candidate in content.characters.items():
            if candidate.office_type == office_type:
                assert name in role_facts
            else:
                assert name not in role_facts


def test_different_office_types_do_not_share_the_same_role_facts(game):
    db, state, content = game
    representatives = {}
    for character in content.characters.values():
        if character.office_type in content.office_knowledge_domains:
            representatives.setdefault(character.office_type, character)

    role_facts = {
        office_type: db.get_character_knowledge(state, character.name)["world"]["role"]
        for office_type, character in representatives.items()
    }

    assert len(set(role_facts.values())) == len(role_facts)


def test_office_knowledge_domains_are_loaded_from_content(game, monkeypatch):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    monkeypatch.setitem(content.office_knowledge_domains, "礼部", ("military",))

    view = db.get_character_knowledge(state, minister.name)

    assert "military" in view["world"]
    assert "personnel" not in view["world"]


def test_current_state_facts_are_selected_by_content_domain_not_role_label(
    game, monkeypatch
):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    monkeypatch.setattr(db, "faction_report", lambda: "当前派系事实")
    monkeypatch.setattr(db, "army_report", lambda **_: "不应读取的军情")
    monkeypatch.setattr(db, "treasury_report", lambda *_args, **_: "不应读取的账目")

    view = db.get_character_knowledge(state, minister.name)["world"]

    assert view["personnel"] == "当前派系事实"
    assert "礼部本职所涉" not in view["personnel"]
    assert "military" not in view
    assert "treasury" not in view


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
    assert any(item["source_id"] == "opening:accession" for item in household_view["public_events"])
    assert any(item["source_id"] == "opening:anti_eunuch" for item in household_view["public_events"])


def test_restored_knowledge_uses_current_db_office_after_transfer(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")

    # Simulate a persisted transfer followed by restore while the original
    # content roster is still resident in memory.  The DB row is the durable
    # current-world source; a stale content object must not keep the old rail.
    db.conn.execute(
        "UPDATE characters SET office = ?, office_type = ? WHERE name = ?",
        ("户部尚书", "户部", minister.name),
    )
    db.conn.commit()
    restored = db.load_state()

    view = db.get_character_knowledge(restored, minister.name)

    assert view["office_type"] == "户部"
    assert "treasury" in view["world"]
    assert "personnel" not in view["world"]


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


def test_turn_report_keeps_source_specific_secret_exclusion_boundary(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "密事不得告知礼部", [], excluded_names=[minister.name]
    )
    db.record_public_knowledge_event(
        state, "密事记录", "SECRET_SOURCE_MARKER_490", source_id=f"secret_order:{order}"
    )
    marker = "TURN_REPORT_SECRET_MARKER_490"
    db.save_turn_report(state, f"朝廷常务；{marker}")

    view = db.get_character_knowledge(state, minister.name)

    assert marker in view["world"]["public"]
    assert any(marker in item.get("body", "") for item in view["public_events"])
    assert not any("SECRET_SOURCE_MARKER_490" in item.get("body", "")
                   for item in view["public_events"])


def test_turn_report_projects_public_and_secret_items_per_character(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    secret_marker = "MIXED_REPORT_SECRET_MARKER_490"
    public_marker = "MIXED_REPORT_PUBLIC_MARKER_490"
    db.record_public_knowledge_event(
        state, "密事来源", secret_marker,
        source_id="secret_order:mixed-report",
        excluded_names=[minister.name],
    )
    db.record_public_knowledge_event(
        state, "公开来源", public_marker,
        source_id="public:mixed-report",
    )
    db.save_turn_report(state, f"公开事项：{public_marker}\n密事项：{secret_marker}")

    view = db.get_character_knowledge(state, minister.name)

    assert public_marker in view["world"]["public"]
    assert secret_marker not in view["world"]["public"]


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


def test_knowledge_world_keeps_countable_fiscal_facts_but_not_abstract_axes(game, monkeypatch):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "户部")
    monkeypatch.setattr(
        db, "treasury_report", lambda _state: "太仓银两167万两；民心低迷；皇威不足。"
    )

    view = db.get_character_knowledge(state, minister.name)

    assert "treasury" in view["world"]
    assert "167万两" in view["world"]["treasury"]
    assert "民心低迷" in view["world"]["treasury"]


def test_secret_office_exclusion_does_not_hide_unrelated_world_bucket(game):
    db, state, content = game
    clerk = next(c for c in content.characters.values() if c.office_type == "户部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_offices=["户部"]
    )
    view = db.get_character_knowledge(state, clerk.name)

    assert db.list_secret_orders()[0]["excluded_targets"] == {"people": [], "offices": ["户部"]}
    assert view["world"]["public"] == "登基伊始，朝廷暂无前回合奏报。"
    assert view["world"].get("treasury")
    assert not any(item["source_id"] == f"secret_order:{order}" for item in view["events"])


def test_secret_office_snapshot_keeps_explicit_people_target_separate(game):
    db, state, content = game
    office_member = next(c for c in content.characters.values() if c.office_type == "户部")
    explicit_person = next(c for c in content.characters.values() if c.name != office_member.name)

    order = db.create_secret_order(
        state,
        "毕自严",
        "暗查亏空",
        "查户部旧账",
        [],
        excluded_names=[explicit_person.name],
        excluded_offices=["户部"],
    )

    row = db.conn.execute(
        "SELECT excluded_names, excluded_targets FROM secret_orders WHERE id=?", (order,)
    ).fetchone()
    assert set(json.loads(row["excluded_names"])) >= {
        explicit_person.name,
        office_member.name,
    }
    assert json.loads(row["excluded_targets"]) == {
        "people": [explicit_person.name],
        "offices": ["户部"],
    }


def test_secret_office_exclusion_snapshots_people_before_transfer_and_publication(game):
    db, state, content = game
    excluded = next(c for c in content.characters.values() if c.office_type == "户部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_offices=["户部"]
    )

    db.set_character_office(excluded.name, "礼部尚书", office_type="礼部")
    db.record_public_knowledge_event(
        state, "密查公开", "该案已奉明发", source_id=f"secret_order:{order}"
    )

    row = db.conn.execute("SELECT excluded_names FROM secret_orders WHERE id=?", (order,)).fetchone()
    assert excluded.name in row["excluded_names"]
    view = db.get_character_knowledge(state, excluded.name)
    assert not any(item["source_id"] == f"secret_order:{order}" for item in view["events"])
    assert not any(item["source_id"] == f"secret_order:{order}" for item in view["public_events"])
    assert excluded.office == "礼部尚书"


def test_disclosed_secret_source_keeps_its_public_projection(game):
    """A later public disclosure must not be replaced by the private source payload."""
    db, state, content = game
    excluded = next(c for c in content.characters.values() if c.office_type == "户部")
    order = db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [],
        excluded_names=[excluded.name],
    )
    db.record_public_knowledge_event(
        state, "密查公开", "该案已奉明发", source_id=f"secret_order:{order}"
    )

    items = db.knowledge_items_for_turn(state.turn)

    disclosed = next(item for item in items if item["source_id"] == f"secret_order:{order}")
    assert disclosed["title"] == "密查公开"
    assert disclosed["body"] == "该案已奉明发"


def test_secret_exclusion_is_source_scoped_not_global_for_same_bucket(game):
    db, state, content = game
    treasury_ministers = [c for c in content.characters.values() if c.office_type == "户部"]
    excluded = treasury_ministers[0]
    unaffected = treasury_ministers[1]
    db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_offices=[excluded.office]
    )

    excluded_view = db.get_character_knowledge(state, excluded.name)
    unaffected_view = db.get_character_knowledge(state, unaffected.name)

    assert excluded_view["world"].get("treasury")
    assert unaffected_view["world"].get("treasury")


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


def test_new_participation_source_is_projected_without_read_side_type_branch(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.record_participation_record(
        state,
        {"participants": [minister.name], "title": "新型案卷", "body": "案卷内容"},
        kind="new_record_type",
        source_id="new_record:1",
    )

    assert any(item["source_id"] == "new_record:1" for item in db.get_character_knowledge(state, minister.name)["events"])


def test_participant_roster_is_discovered_from_persistent_record_without_adapter(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.conn.execute(
        """INSERT INTO issues
           (kind, title, origin_turn, stage_text, participants, participant_roster)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("initiative", "未经适配的新案卷", state.turn, "案卷正文",
         "[]", '[{"character_id": "' + minister.name + '"}]'),
    )
    db.conn.commit()

    view = db.get_character_knowledge(state, minister.name)

    assert any(item["title"] == "未经适配的新案卷" for item in view["events"])


def test_office_blacklist_preserves_unrelated_court_domain_fact(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "内阁")
    db.create_secret_order(
        state, "毕自严", "暗查亏空", "查户部旧账", [], excluded_offices=["户部"]
    )

    view = db.get_character_knowledge(state, minister.name)

    assert view["world"].get("personnel")
    assert view["world"].get("treasury")


def test_event_office_blacklist_matches_current_office_name(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.register_character_knowledge_source(
        state,
        [{"character_id": minister.name}],
        "secret_order",
        "仅瞒礼部尚书",
        "不可宣示",
        source_id="secret_order:office-name",
        excluded_targets={"offices": [minister.office]},
    )

    view = db.get_character_knowledge(state, minister.name)

    assert not any(
        item["source_id"] == "secret_order:office-name"
        for item in view["events"]
    )


def test_participant_roster_is_discovered_from_any_persistent_table(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    db.conn.execute(
        """
        CREATE TABLE custom_participant_records (
            id INTEGER PRIMARY KEY,
            turn INTEGER NOT NULL,
            year INTEGER NOT NULL,
            period INTEGER NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            source_id TEXT NOT NULL,
            participant_roster TEXT NOT NULL
        )
        """
    )
    db.conn.execute(
        """
        INSERT INTO custom_participant_records
            (turn, year, period, kind, title, body, source_id, participant_roster)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (state.turn, state.year, state.period, "custom", "新型案卷", "案卷内容",
         "custom:1", '[{"character_id": "' + minister.name + '"}]'),
    )
    db.conn.commit()

    view = db.get_character_knowledge(state, minister.name)

    assert any(item["source_id"] == "custom:1" for item in view["events"])
