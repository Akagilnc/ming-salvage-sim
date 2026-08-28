"""#489 角色见闻：职位裁切、公开事件与参与留痕。"""

import json

from ming_sim.models import Character
import pytest
from ming_sim.knowledge import build_character_knowledge

def test_role_roster_only_lists_current_active_ming_people(game):
    db, state, content = game
    reader = next(c for c in content.characters.values() if c.office_type == "礼部")
    names = [c.name for c in content.characters.values() if c.name != reader.name][:4]
    for name, status, debut_year, power_id in zip(
        names, ("dismissed", "offstage", "active", "active"),
        (0, 0, state.year + 1, 0), ("ming", "ming", "ming", "houjin"),
    ):
        db.conn.execute("UPDATE characters SET office_type='礼部', status=?, debut_year=?, power_id=? WHERE name=?",
                        (status, debut_year, power_id, name))
    db.conn.commit()
    roster = db.get_character_knowledge(state, reader.name)["world"]["role"]
    assert all(name not in roster for name in names)

def test_chapter_aggregate_never_projects_paraphrased_restricted_source(game):
    db, state, content = game
    knower, excluded = list(content.characters.values())[:2]
    db.register_character_knowledge_source(
        state, [{"character_id": knower.name}], "private_matter", "密查", "原始密事",
        source_id="test:chapter-secret", excluded_names=[excluded.name],
    )
    db.save_chapter_memory(state, "朝局", "宫中有人暗中安排了不应知晓的事务。")
    text = " ".join(item.get("body", "") for item in db.get_character_knowledge(state, excluded.name)["public_events"])
    assert "宫中有人暗中安排" not in text

def test_secret_alias_exclusion_is_canonicalized_before_projection(game):
    db, state, _content = game
    order = db.create_secret_order(state, "毕自严", "密查", "查账", [], excluded_names=["九千岁"])
    row = db.conn.execute("SELECT excluded_names FROM secret_orders WHERE id=?", (order,)).fetchone()
    assert "魏忠贤" in row["excluded_names"]

def test_secret_order_commit_recovers_named_alias_and_office_targets_from_content(game):
    """All issue paths share the commit boundary when tool fields are omitted."""
    db, state, content = game
    excluded = content.characters["魏忠贤"]
    academy = next(c for c in content.characters.values() if c.office_type == "翰林院")

    order = db.create_secret_order(
        state, "毕自严", "密查", "密查账目，瞒住九千岁与翰林院诸官。", []
    )

    row = db.conn.execute(
        "SELECT excluded_names, excluded_targets FROM secret_orders WHERE id=?", (order,)
    ).fetchone()
    assert excluded.name in json.loads(row["excluded_names"])
    assert academy.name in json.loads(row["excluded_names"])
    assert json.loads(row["excluded_targets"]) == {
        "people": [excluded.name], "offices": ["翰林院"],
    }

def test_secret_order_commit_recovers_non_disclosure_clause(game):
    """持久化边界不能因措辞不同丢失具体官职排除。"""
    db, state, _content = game

    order = db.create_secret_order(
        state, "毕自严", "密查", "不可令翰林院侍读学士知情。", []
    )

    row = db.conn.execute(
        "SELECT excluded_targets FROM secret_orders WHERE id=?", (order,)
    ).fetchone()
    assert json.loads(row["excluded_targets"])["offices"] == ["翰林院侍读学士"]

def test_secret_order_tool_path_canonicalizes_omitted_exclusions_before_staging(game):
    """Function callers may omit fields; prose still excludes the whole office."""
    from ming_sim.models import CourtContext
    from ming_sim.tools import build_minister_tools

    db, state, content = game
    academy = next(c for c in content.characters.values() if c.office_type == "翰林院")
    context = CourtContext(db=db, state=state)
    tools = {tool.__name__: tool for tool in build_minister_tools(academy, context)}
    payload = tools["secret_order"](
        action="issue", title="密查", content="密查账目，勿使翰林院诸官知晓。",
        kind="清丈", axes_json='["实务事功"]', delivery_unit="亩",
        delivery_target_units=1, region="henan", field="registered_land",
        region_target="421",
    ).removeprefix("__secret_order__")

    staged = json.loads(payload)
    assert staged["excluded_offices"] == ["翰林院"]

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
        rows = db.conn.execute(
            "SELECT name FROM characters WHERE office_type=? AND status='active' AND power_id='ming' "
            "AND (debut_year=0 OR debut_year<? OR (debut_year=? AND debut_month<=?))",
            (office_type, state.year, state.year, state.period),
        ).fetchall()
        assert all(row["name"] in role_facts for row in rows)

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
    seen_limits = []

    def complete_small_army_report(*, limit):
        seen_limits.append(limit)
        return "\n".join(f"军籍第{i}营" for i in range(1, limit + 1))

    monkeypatch.setattr(db, "army_report", complete_small_army_report)

    view = db.get_character_knowledge(state, minister.name)

    assert "military" in view["world"]
    assert "军籍第30营" in view["world"]["military"]
    assert seen_limits == [30]
    assert "personnel" not in view["world"]

def test_current_state_facts_are_selected_by_content_domain_not_role_label(
    game, monkeypatch
):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    monkeypatch.setattr(db, "faction_report", lambda **_: "当前派系事实")
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

def test_restored_knowledge_uses_current_db_office_after_transfer(tmp_path, content):
    from ming_sim.db import GameDB

    path = tmp_path / "knowledge-transfer.db"
    db = GameDB(str(path), content)
    db.seed_static_data()
    state = db.load_state()
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")

    # Simulate a persisted transfer followed by restore while the original
    # content roster is still resident in memory.  The DB row is the durable
    # current-world source; a stale content object must not keep the old rail.
    db.conn.execute(
        "UPDATE characters SET office = ?, office_type = ? WHERE name = ?",
        ("户部尚书", "户部", minister.name),
    )
    db.record_public_knowledge_event(
        state, "转任后公开事项", "户部新任须核验太仓账目",
        source_id="public:post-transfer",
    )
    db.conn.commit()
    db.close()

    restored_db = GameDB(str(path), content)
    try:
        restored = restored_db.load_state()
        view = restored_db.get_character_knowledge(restored, minister.name)

        assert view["office_type"] == "户部"
        assert "treasury" in view["world"]
        assert "personnel" not in view["world"]
        assert any(
            item["source_id"] == "public:post-transfer"
            for item in view["public_events"]
        )
    finally:
        restored_db.close()

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
    # #883: this independently public source, not the aggregate itself,
    # authorizes the visible public fragment.
    db.record_public_knowledge_event(state, "朝廷常务", marker, source_id="test:490:public")
    db.save_turn_report(
        state, f"朝廷常务；{marker}", public_body=f"朝廷常务；{marker}",
    )

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
        source_id="restricted:mixed-report",
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

def test_undo_chat_turn_removes_chat_derived_knowledge_from_context(game):
    """撤回本轮后，已删除聊天消息的见闻源不可继续投影到人物上下文。

    #976: user 行先 hold；放行共享轨后才有见闻投影；撤回仍须清掉已放行源。
    """
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "内阁")
    marker = "撤回应一并抹去的召对事项"

    chat_turn_id = db.create_chat_turn(state, minister.name, "undo-knowledge", 0)
    before = db.capture_chat_rollback_snapshot()
    message_id = db.append_chat_message(minister.name, state.turn, "user", marker)
    # Pure-public emperor speech is held until release (no secret classification).
    db.release_held_audience_knowledge()
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(chat_turn_id, before, after)
    db.update_chat_turn_messages(chat_turn_id, user_message_id=message_id)

    assert any(marker in item["body"] for item in db.get_character_knowledge(state, minister.name)["events"])

    db.undo_chat_turn(chat_turn_id)

    source_id = f"chat_message:{message_id}"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_events WHERE source_id=?", (source_id,)
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?", (source_id,)
    ).fetchone()[0] == 0
    assert not any(marker in item["body"] for item in db.get_character_knowledge(state, minister.name)["events"])

def test_undo_chat_turn_removes_turn_scoped_near_minister_report(game):
    db, state, content = game
    minister = content.characters["王承恩"]
    chat_turn_id = db.create_chat_turn(state, minister.name, "undo-report", 0)
    db.persist_return_report(state, minister.name, "军情如何？", chat_turn_id=chat_turn_id)

    db.undo_chat_turn(chat_turn_id)

    assert not any(
        item.get("source_id", "").startswith("near_minister:")
        for item in db.get_character_knowledge(state, minister.name)["events"]
    )

def test_failed_chat_turn_removes_turn_scoped_near_minister_report_but_keeps_prior_one(game):
    db, state, content = game
    minister = content.characters["王承恩"]
    db.persist_return_report(state, minister.name, "军情如何？")
    chat_turn_id = db.create_chat_turn(state, minister.name, "failed-report", 0)
    db.persist_return_report(state, minister.name, "陕西巡抚可有？", chat_turn_id=chat_turn_id)

    db.fail_chat_turn(chat_turn_id)

    sources = db.conn.execute(
        "SELECT source_id FROM character_knowledge_sources WHERE source_id LIKE 'near_minister:%'"
    ).fetchall()
    assert len(sources) == 1
    assert ":chat_turn:" not in sources[0]["source_id"]

def test_undo_chat_turn_keeps_preexisting_identical_near_minister_report(game):
    """撤回只清本轮临时来源，不能删除同题已存在的稳定回奏。"""
    db, state, content = game
    minister = content.characters["王承恩"]
    query = "军情如何？"

    db.persist_return_report(state, minister.name, query)
    chat_turn_id = db.create_chat_turn(state, minister.name, "undo-same-report", 0)
    # The prompt rebuild sees the stable source and must not turn it into a
    # turn-owned duplicate that undo could remove.
    db.persist_return_report(state, minister.name, query, chat_turn_id=chat_turn_id)

    db.undo_chat_turn(chat_turn_id)

    sources = db.conn.execute(
        "SELECT source_id FROM character_knowledge_sources WHERE source_id LIKE 'near_minister:%'"
    ).fetchall()
    assert len(sources) == 1
    assert ":chat_turn:" not in sources[0]["source_id"]

def test_delete_chat_messages_removes_chat_derived_knowledge_from_context(game):
    """删除聊天消息时也不能留下可投影的见闻来源。"""
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "内阁")
    marker = "删除消息应一并抹去的召对事项"

    message_id = db.append_chat_message(minister.name, state.turn, "assistant", marker)
    db.delete_chat_messages([message_id])

    source_id = f"chat_message:{message_id}"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_events WHERE source_id=?", (source_id,)
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id=?", (source_id,)
    ).fetchone()[0] == 0
    assert not any(marker in item["body"] for item in db.get_character_knowledge(state, minister.name)["events"])

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
        "private_matter",
        "密查亏空",
        "查户部旧账",
        source_id="restricted:excluded",
        excluded_names=[minister.name],
    )

    view = db.get_character_knowledge(state, minister.name)

    assert not any(item["source_id"] == "restricted:excluded" for item in view["events"])

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
    # #883: aggregates never authorize knowledge; independently persisted
    # public sources are the cross-turn knowledge rail.
    db.record_public_knowledge_event(state, "清丈", "第一回合：清丈已明发。", source_id="test:turn-one")
    db.save_turn_report(state, "第一回合：清丈已明发。")
    later = db.load_state()
    later.turn += 2
    db.record_public_knowledge_event(later, "军务", "第三回合：军务有变。", source_id="test:turn-three")
    db.save_turn_report(later, "第三回合：军务有变。")

    view = db.get_character_knowledge(later, minister.name)

    bodies = [item["body"] for item in view["public_events"]]
    assert any("第一回合：清丈已明发。" in body for body in bodies)
    assert any("第三回合：军务有变。" in body for body in bodies)

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

def test_public_disclosure_drops_private_roster_but_keeps_event_exclusion(game):
    db, state, content = game
    people = [c for c in content.characters.values() if c.office_type not in ("后宫", "宗藩")]
    participant, allowed, excluded = people[:3]
    source_id = "restricted:public-disclosure-roster"
    db.register_character_knowledge_source(
        state, [{"character_id": participant.name}], "private_matter", "密查", "旧密令",
        source_id=source_id,
    )
    db.record_public_knowledge_event(
        state, "奉明公开", "公开案情", source_id=source_id,
        excluded_names=[excluded.name],
    )

    allowed_view = db.get_character_knowledge(state, allowed.name)
    excluded_view = db.get_character_knowledge(state, excluded.name)
    assert any(item["body"] == "公开案情" for item in allowed_view["public_events"])
    assert not any(item["body"] == "公开案情" for item in excluded_view["public_events"])

def test_long_knowledge_bodies_survive_storage_without_brief_card_cap(game):
    db, state, content = game
    reader = next(iter(content.characters.values()))
    body = "甲" * 450 + "完整结尾"
    db.register_character_knowledge_source(
        state, [{"character_id": reader.name}], "audience", "长奏报", body,
        source_id="test:long-source",
    )
    row = db.conn.execute(
        "SELECT body FROM character_knowledge_sources WHERE source_id='test:long-source'"
    ).fetchone()
    assert row["body"].endswith("完整结尾")

def test_secret_amendment_preserves_legacy_blacklist_and_public_disclosure(game):
    db, state, _content = game
    order = db.create_secret_order(state, "毕自严", "密查", "查账", [])
    db.conn.execute(
        "UPDATE secret_orders SET excluded_names=?, excluded_targets='{}' WHERE id=?",
        (json.dumps(["魏忠贤"], ensure_ascii=False), order),
    )
    db.record_public_knowledge_event(
        state, "密查公开", "该案已奉明发", source_id=f"secret_order:{order}"
    )
    assert db.update_secret_order_by_id(state, order, "续查", "继续查账")
    saved = db.conn.execute(
        "SELECT excluded_names FROM secret_orders WHERE id=?", (order,)
    ).fetchone()
    assert "魏忠贤" in json.loads(saved["excluded_names"])
    public = db.conn.execute(
        "SELECT body FROM character_knowledge_events WHERE source_id=? AND character_name=''",
        (f"secret_order:{order}",),
    ).fetchone()
    assert public["body"] == "该案已奉明发"

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
        "private_matter",
        "仅瞒礼部尚书",
        "不可宣示",
        source_id="restricted:office-name",
        excluded_targets={"offices": [minister.office]},
    )

    view = db.get_character_knowledge(state, minister.name)

    assert not any(
        item["source_id"] == "restricted:office-name"
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

def test_appended_dossier_participant_learns_only_on_join_turn_after_restore(game):
    from ming_sim.db import GameDB

    db, state, content = game
    lead, newcomer = [
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' LIMIT 2"
        ).fetchall()
    ]
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="着核定历书。",
        target_kind="issue", target_id="calendar-copy",
        participants=[{"character_id": lead, "tier": "主办"}],
    )
    created_turn = state.turn
    state.turn = 7
    db.append_decree_dossier_participants(dossier_id, [{
        "character_id": newcomer, "tier": "协办", "delegator_id": lead,
    }], state=state)

    assert min(item["turn"] for item in db.get_character_knowledge(
        state, lead,
    )["events"] if item["source_id"] == f"decree_dossier:{dossier_id}") == created_turn
    joined = [item for item in db.get_character_knowledge(state, newcomer)["events"]
              if item["source_id"].startswith(f"dossier:{dossier_id}:participant:")]
    assert [item["turn"] for item in joined] == [7]

    path = db.path
    db.close()
    reopened = GameDB(path, content=content)
    try:
        restored = [item for item in reopened.get_character_knowledge(state, newcomer)["events"]
                    if item["source_id"].startswith(f"dossier:{dossier_id}:participant:")]
        assert [item["turn"] for item in restored] == [7]
    finally:
        reopened.close()

def test_decree_dossier_participant_reads_frozen_metadata_and_text(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="着礼部核定历书正文。",
        target_kind="issue", target_id="calendar-copy",
        participants=[{"character_id": minister.name, "tier": "主办"}],
    )

    item = next(
        item for item in db.get_character_knowledge(state, minister.name)["events"]
        if item["source_id"] == f"decree_dossier:{dossier_id}"
    )
    assert (item["turn"], item["year"], item["period"]) == (
        state.turn, state.year, state.period,
    )
    assert item["body"] == "着礼部核定历书正文。"

def test_secret_order_dossier_never_leaks_through_shared_roster_projection(game):
    db, state, content = game
    member = next(c for c in content.characters.values() if c.office_type == "礼部")
    outsider = next(c for c in content.characters.values() if c.name != member.name)
    order_id = db.create_secret_order(
        state, member.name, "密核历书", "暗查历局底稿。", [], deadline_months=0,
    )
    dossier = next(d for d in db.list_decree_dossiers() if d["secret_order_id"] == order_id)
    db.conn.execute(
        "UPDATE decree_dossiers SET participant_roster=? WHERE id=?",
        (json.dumps([{"character_id": member.name, "tier": "主办"}], ensure_ascii=False), dossier["id"]),
    )
    db.conn.commit()

    for reader in (member.name, outsider.name):
        assert not any(
            item["source_id"] == f"decree_dossier:{dossier['id']}"
            for item in db.get_character_knowledge(state, reader)["events"]
        )

def test_knowledge_titles_restore_without_persistence_truncation(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    title = "密令长标题" * 20
    db.register_character_knowledge_source(
        state, [{"character_id": minister.name}], "private_matter", title, "内容", "restricted:long-title",
    )
    db.record_public_knowledge_event(state, title, "公开内容", source_id="public:long-title")

    source = db.conn.execute(
        "SELECT title FROM character_knowledge_sources WHERE source_id='restricted:long-title'"
    ).fetchone()["title"]
    public_event = db.conn.execute(
        "SELECT title FROM character_knowledge_events WHERE source_id='public:long-title'"
    ).fetchone()["title"]
    assert source == public_event == title

# ── archive / source_scope contracts (moved from test_knowledge.py, #1185 wave1) ──

def test_regional_world_keeps_qualitative_and_countable_region_facts(game):
    """本职地区见闻须同时保留定性轴与独立的税额、炮数事实。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE regions SET public_support=13, unrest=87, grain_security=60, "
        "tax_per_turn=20, cannon=3"
    )
    db.conn.commit()
    regional = next(
        knowledge["world"]["regional"]
        for character in content.characters.values()
        if db.get_character_status(character.name)[0] == "active"
        for knowledge in [build_character_knowledge(db, state, character.name)]
        if "regional" in knowledge["world"]
    )

    assert "民心" in regional
    assert "动乱" in regional
    assert "粮情" in regional
    assert "税20万两/月" in regional
    assert "城防炮3门" in regional
    assert "已略去" not in regional

@pytest.mark.parametrize(
    ("target_kind", "expected_visible"),
    [
        ("none", True),
        ("unrelated-office", True),
        ("office-type", False),
        ("office-name", False),
    ],
    ids=["no-exclusion", "unrelated-office", "matching-office-type", "matching-office-name"],
)
def test_knowledge_exclusion_reads_current_office_without_nameerror(
    game, monkeypatch, target_kind, expected_visible
):
    db, state, content = game
    name, character = next(
        (name, character)
        for name, character in content.characters.items()
        if character.office_type == "户部"
    )
    row = {
        "turn": state.turn,
        "year": state.year,
        "period": state.period,
        "kind": "secret",
        "title": "密令",
        "body": "不可忽略的密令",
        "source_id": "test:office-exclusion",
        "excluded_names": "[]",
    }
    excluded_office = {
        "none": [],
        "unrelated-office": ["不相干职位"],
        "office-type": [character.office_type],
        "office-name": [character.office],
    }[target_kind]
    targets = {"people": [], "offices": excluded_office}

    def events(character_name, *, include_exclusions=False):
        return [row] if character_name == name else []

    monkeypatch.setattr(db, "_character_knowledge_events", events)
    monkeypatch.setattr(db, "list_issued_directives", lambda: [])
    monkeypatch.setattr(db, "list_turn_reports", lambda: [])
    monkeypatch.setattr(db, "knowledge_exclusion_targets_for_source", lambda _: targets)

    knowledge = build_character_knowledge(db, state, name)

    assert (knowledge["events"] != []) is expected_visible
    if expected_visible:
        assert knowledge["events"][0]["body"] == "不可忽略的密令"
    else:
        assert knowledge["events"] == []

def test_knowledge_projects_gazette_and_chapter_sources_per_character(game):
    """同一份公共叙事中的密事不能借原始邸报/章节副本泄漏。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    public_marker = "公开事项标记"
    secret_marker = "不得知密事标记"

    db.record_public_knowledge_event(
        state, "密查", secret_marker, source_id="test:mixed-source",
        excluded_names=[excluded.name],
    )
    db.record_public_knowledge_event(
        state, "公开事项", public_marker, source_id="test:mixed-public",
    )
    db.save_turn_report(state, f"{public_marker}；{secret_marker}")
    db.save_chapter_memory(state, "朝局", f"{public_marker}；{secret_marker}")

    excluded_knowledge = db.get_character_knowledge(state, excluded.name)
    knower_knowledge = db.get_character_knowledge(state, knower.name)
    excluded_text = " ".join(
        item.get("body", "") for item in excluded_knowledge["public_events"]
    )
    knower_text = " ".join(
        item.get("body", "") for item in knower_knowledge["public_events"]
    )

    assert public_marker in excluded_text
    assert secret_marker not in excluded_text
    assert secret_marker in knower_text

def test_knowledge_projects_mixed_archive_from_durable_source_scope(game):
    """受限事项来自 source 表时，聚合邸报仍保留公开事项但不泄密。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    public_marker = "source表公开事项"
    secret_marker = "source表不得知密事"

    db.register_character_knowledge_source(
        state,
        [{"character_id": knower.name, "tier": "主办"}],
        "private_matter",
        "密查",
        secret_marker,
        source_id="test:durable-secret",
        excluded_names=[excluded.name],
    )
    db.record_public_knowledge_event(
        state, "公开事项", public_marker, source_id="test:durable-public",
    )
    db.save_turn_report(state, f"{public_marker}；{secret_marker}")
    db.save_chapter_memory(state, "朝局", f"{public_marker}；{secret_marker}")

    excluded_text = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, excluded.name)["public_events"]
    )
    knower_text = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, knower.name)["public_events"]
    )

    assert public_marker in excluded_text
    assert secret_marker not in excluded_text
    assert secret_marker in knower_text

def test_rewritten_archive_cannot_reintroduce_restricted_source(game):
    """章节改写不是来源边界；受限事项必须在改写后仍不可见。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    db.register_character_knowledge_source(
        state,
        [{"character_id": knower.name, "tier": "主办"}],
        "private_matter",
        "密查",
        "原始密事",
        source_id="test:rewritten-secret",
        excluded_names=[excluded.name],
    )
    db.save_turn_report(state, "聚合邸报改写：有人暗中安排了不应知晓的事务。")
    db.save_chapter_memory(state, "朝局", "章节改写：宫中另有暗流，未明言其由来。")

    excluded_text = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, excluded.name)["public_events"]
    )
    assert "有人暗中安排了不应知晓的事务" not in excluded_text
    assert "宫中另有暗流" not in excluded_text

def test_archive_write_materializes_unmirrored_source_scope(game):
    """结算保存聚合档案时，不能丢掉先写入的受限事项来源边界。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, excluded = ministers[:2]
    secret_marker = "未镜像的受限事项"

    db.register_character_knowledge_source(
        state,
        [{"character_id": knower.name, "tier": "主办"}],
        "private_matter",
        "密查",
        secret_marker,
        source_id="test:unmirrored-source",
        excluded_names=[excluded.name],
    )
    db.save_turn_report(state, "聚合邸报中的公开事项")

    rows = db.conn.execute(
        "SELECT character_name, body, excluded_names FROM character_knowledge_events "
        "WHERE source_id = ? ORDER BY character_name",
        ("test:unmirrored-source",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["character_name"] == ""
    assert rows[0]["body"] == secret_marker
    assert excluded.name in rows[0]["excluded_names"]

def test_chapter_public_counterpart_keeps_only_independent_public_sources(game):
    """公开章节对应体来自公开 source，不从聚合章节删改密事。"""
    from ming_sim.memories import _public_chapter_counterpart

    db, state, content = game
    knower, excluded = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ][:2]
    db.record_public_knowledge_event(
        state, "公开事项", "公开来源标记", source_id="test:chapter-public",
    )
    db.register_character_knowledge_source(
        state,
        [{"character_id": knower.name, "tier": "主办"}],
        "private_matter", "密查", "受限来源标记",
        source_id="test:chapter-restricted", excluded_names=[excluded.name],
    )

    counterpart = _public_chapter_counterpart(db.knowledge_items_for_turn(state.turn))

    assert "公开来源标记" in counterpart
    assert "受限来源标记" not in counterpart

def test_chapter_counterpart_never_uses_aggregate_when_sources_exist(game):
    """已有来源边界时，章节聚合正文不能自行成为公开来源。"""
    db, state, content = game
    reader = next(
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    )
    public_marker = "已立来源的公开事项"
    unscoped_marker = "无来源的章节改写"
    db.record_public_knowledge_event(
        state, "公开事项", public_marker, source_id="test:source-bound-public",
    )

    db.save_chapter_memory(
        state, "朝局", f"{public_marker}；{unscoped_marker}",
        knowledge_items=db.knowledge_items_for_turn(state.turn),
    )

    projected = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, reader.name)["public_events"]
    )
    assert public_marker in projected
    assert unscoped_marker not in projected

def test_turn_report_counterpart_never_uses_aggregate_when_sources_exist(game):
    """已有来源边界时，邸报聚合正文不能自行成为公开来源。"""
    db, state, content = game
    reader = next(
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    )
    public_marker = "已立来源的邸报公开事项"
    unscoped_marker = "无来源的邸报改写"
    db.record_public_knowledge_event(
        state, "公开事项", public_marker, source_id="test:report-source-bound-public",
    )

    db.save_turn_report(
        state, f"{public_marker}；{unscoped_marker}",
        knowledge_items=db.knowledge_items_for_turn(state.turn),
    )

    projected = " ".join(
        item.get("body", "")
        for item in db.get_character_knowledge(state, reader.name)["public_events"]
    )
    assert public_marker in projected
    assert unscoped_marker not in projected

def test_chapter_counterpart_does_not_repeat_derived_turn_report_source(game):
    """The normal report→chapter sequence projects monthly prose only once."""
    from ming_sim.memories import _public_chapter_counterpart

    db, state, _content = game
    marker = "本月独立公开来源"
    db.record_public_knowledge_event(state, "公开事项", marker, source_id="test:monthly-source")
    db.save_turn_report(state, "月结改写", knowledge_items=db.knowledge_items_for_turn(state.turn))

    counterpart = _public_chapter_counterpart(db.knowledge_items_for_turn(state.turn))

    assert marker in (counterpart or "")
    assert "月结改写" not in (counterpart or "")

def test_character_projection_shows_monthly_public_source_once_after_chapter_write(game):
    """A chapter counterpart must not re-aggregate its turn-report counterpart."""
    from ming_sim.memories import _public_chapter_counterpart

    db, state, content = game
    reader = next(c for c in content.characters.values() if c.office_type == "礼部")
    marker = "正常月结公开正文"
    db.record_public_knowledge_event(state, "公开事项", marker, source_id="test:monthly-once")
    db.save_turn_report(state, marker, knowledge_items=db.knowledge_items_for_turn(state.turn))
    db.save_chapter_memory(
        state, "朝局", "章节改写", knowledge_items=db.knowledge_items_for_turn(state.turn),
        public_body=_public_chapter_counterpart(db.knowledge_items_for_turn(state.turn)),
    )

    projected = "\n".join(
        str(item.get("body") or "")
        for item in db.get_character_knowledge(state, reader.name)["public_events"]
    )
    assert projected.count(marker) == 1

def test_shared_archive_storage_never_writes_restricted_aggregate(game):
    db, state, content = game
    participant = next(iter(content.characters))
    secret = "仅经手人可知的密令细节"
    public = "本月公开政务"
    db.register_character_knowledge_source(
        state, [{"character_id": participant}], "private_matter", "密令", secret,
        source_id="restricted:test-write-boundary",
    )
    db.record_public_knowledge_event(state, "公开事项", public, source_id="public:test-write-boundary")

    db.save_turn_report(state, f"{public}；{secret}", knowledge_items=db.knowledge_items_for_turn(state.turn))
    db.save_chapter_memory(
        state, "本月", f"章节转述：{secret}", knowledge_items=db.knowledge_items_for_turn(state.turn),
        public_body=public,
    )

    assert secret not in db.get_turn_report(state.turn)
    assert secret not in db.list_chapter_memories(upto_turn=state.turn)[-1]["body"]

def test_character_added_after_archive_cannot_read_old_participant_source(game):
    """The durable participant roster, not an archival deny-list snapshot, grants access."""
    db, state, content = game
    participant = next(iter(content.characters))
    secret = "旧档中仅经手人可知的密令细节"
    db.register_character_knowledge_source(
        state, [{"character_id": participant}], "private_matter", "密令", secret,
        source_id="restricted:test-late-reader-boundary",
    )
    db.save_turn_report(
        state, f"聚合转述：{secret}", knowledge_items=db.knowledge_items_for_turn(state.turn),
    )

    late_reader = "归档后新入仕者"
    template = db.conn.execute("SELECT * FROM characters LIMIT 1").fetchone()
    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(characters)").fetchall()]
    values = [template[column] for column in columns]
    values[columns.index("name")] = late_reader
    values[columns.index("aliases")] = "[]"
    placeholders = ",".join("?" for _ in columns)
    db.conn.execute(
        f"INSERT INTO characters ({','.join(columns)}) VALUES ({placeholders})",
        values,
    )
    db.conn.commit()

    projected = db.get_character_knowledge(state, late_reader)
    rendered = "\n".join(
        str(item.get("body") or "")
        for item in [*projected["public_events"], *projected["events"]]
    )
    assert secret not in rendered

def test_chapter_with_only_derived_report_does_not_publish_its_body_again(game):
    """The report projection alone is not an independently public chapter source."""
    from ming_sim.memories import _public_chapter_counterpart

    db, state, content = game
    reader = next(c for c in content.characters.values() if c.office_type == "礼部")
    report_marker = "已经派生的月结正文"
    chapter_marker = "章节改写不得借派生邸报重发"
    db.record_public_knowledge_event(
        state, "邸报", report_marker, source_id=f"turn_report:{state.turn}:public",
    )

    counterpart = _public_chapter_counterpart(db.knowledge_items_for_turn(state.turn))
    db.save_chapter_memory(
        state, "朝局", chapter_marker, knowledge_items=db.knowledge_items_for_turn(state.turn),
        public_body=counterpart,
    )

    projected = "\n".join(
        str(item.get("body") or "")
        for item in db.get_character_knowledge(state, reader.name)["public_events"]
    )
    assert chapter_marker not in projected

def test_chapter_counterpart_filters_derived_report_before_reaggregating_sources(game):
    """A chapter counterpart receives only independent source rows, never its report projection."""
    from ming_sim.memories import _public_chapter_counterpart

    db, state, _content = game
    source_marker = "本月独立源"
    report_marker = "已经派生的邸报正文"
    db.record_public_knowledge_event(state, "公开事项", source_marker, source_id="test:independent")
    db.record_public_knowledge_event(
        state, "邸报", report_marker, source_id=f"turn_report:{state.turn}:public",
    )

    counterpart = _public_chapter_counterpart(db.knowledge_items_for_turn(state.turn))

    assert source_marker in (counterpart or "")
    assert report_marker not in (counterpart or "")

def test_chapter_counterpart_filters_settlement_narrative_derived_with_report(game):
    """同月结算叙事和邸报是派生行，章节不得再次合并它们。"""
    from ming_sim.memories import _public_chapter_counterpart

    db, state, _content = game
    db.record_public_knowledge_event(
        state, "结算叙事", "正常月结正文", source_id=f"settlement:narrative:{state.turn}",
    )
    db.record_public_knowledge_event(
        state, "邸报", "正常月结正文", source_id=f"turn_report:{state.turn}:public",
    )

    assert "正常月结正文" not in _public_chapter_counterpart(
        db.knowledge_items_for_turn(state.turn)
    )

def test_883_legacy_aggregate_without_source_rows_does_not_authorize_knowledge(game):
    db, state, content = game
    db.conn.execute(
        "INSERT INTO turn_reports(turn, year, period, report) VALUES (?, ?, ?, ?)",
        (state.turn + 9, state.year, state.period, "旧档密令摘要不得公开"),
    )
    db.conn.commit()
    reader = next(iter(content.characters))
    rendered = "\n".join(
        item.get("body", "") for item in db.get_character_knowledge(state, reader)["public_events"]
    )
    assert "旧档密令摘要不得公开" not in rendered

