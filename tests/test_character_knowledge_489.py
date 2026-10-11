"""#489 角色见闻：职位裁切、公开事件与参与留痕。"""

import json
import sqlite3

import pytest
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import (
    list_materials,
    prepare_character_materials,
    read_material,
    release_material_tree,
)
from tests.dossier_test_helpers import create_test_secret_order

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
    db.get_character_knowledge(state, reader.name)
    listed = {
        row["name"]
        for row in db.current_court_roster_rows(state)
        if row["office_type"] == reader.office_type
    }
    assert set(names).isdisjoint(listed)


def test_office_slice_does_not_read_unrelated_sensitive_reports(game, monkeypatch):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")

    def forbidden(*args, **kwargs):
        raise AssertionError("礼部见闻不应读取军情或国库报告")

    monkeypatch.setattr(db, "army_report", forbidden)
    monkeypatch.setattr(db, "treasury_report", forbidden)

    view = db.get_character_knowledge(state, minister.name)

    assert "personnel" not in view["world"]
    assert "military" not in view["world"]
    assert "treasury" not in view["world"]

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

def test_public_directive_is_seen_without_granting_secret_order(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    order = create_test_secret_order(db,
        state, "毕自严", "暗查亏空", "查户部旧账", []
    )
    db.record_public_knowledge_event(state, "明发清丈诏", "全国清丈田亩")

    view = db.get_character_knowledge(state, minister.name)

    assert any(
        item.get("source_id") == f"public:{state.turn}:明发清丈诏"
        for item in view["public_events"]
    )
    assert not any(item.get("source_id") == f"secret_order:{order}" for item in view["events"])

def test_public_disclosure_remains_distinct_from_secret_order(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    order = create_test_secret_order(db,
        state, "毕自严", "暗查亏空", "密事不得告知礼部", []
    )
    disclosure_id = f"secret_order_disclosure:{order}:{state.turn}"
    db.record_public_knowledge_event(
        state, "密事记录", "SECRET_SOURCE_MARKER_490", source_id=disclosure_id,
    )
    marker = "TURN_REPORT_SECRET_MARKER_490"
    # #883: this independently public source, not the aggregate itself,
    # authorizes the visible public fragment.
    db.record_public_knowledge_event(state, "朝廷常务", marker, source_id="test:490:public")
    db.save_turn_report(
        state, f"朝廷常务；{marker}", public_body=f"朝廷常务；{marker}",
    )

    view = db.get_character_knowledge(state, minister.name)
    public_ids = {item.get("source_id") for item in view["public_events"]}

    assert "test:490:public" in public_ids
    assert disclosure_id in public_ids


def test_participation_survives_restore(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "内阁")
    db.record_character_participation(
        state, [minister.name], "audience", "召对议饷", "议定辽饷缓急"
    )
    stored = db.conn.execute(
        "SELECT source_id FROM character_knowledge_sources ORDER BY id DESC LIMIT 1"
    ).fetchone()
    before = db.get_character_knowledge(state, minister.name)

    db.conn.commit()
    restored = db.load_state()
    after = db.get_character_knowledge(restored, minister.name)

    assert before["events"] == after["events"]
    assert any(item["source_id"] == stored["source_id"] for item in after["events"])


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
    assert not any(
        item.get("source_id") == source_id
        for item in db.get_character_knowledge(state, minister.name)["events"]
    )

def test_public_directive_remains_visible_on_a_later_turn(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    cursor = db.conn.execute(
        "INSERT INTO turn_directives (turn, year, period, text, source, status) VALUES (?, ?, ?, ?, ?, 'issued')",
        (state.turn, state.year, state.period, "奉天承运，明发清丈诏。", "test"),
    )
    directive_id = int(cursor.lastrowid)
    db.conn.commit()

    later = db.load_state()
    later.turn += 1
    view = db.get_character_knowledge(later, minister.name)

    assert any(item.get("source_id") == f"directive:{directive_id}" for item in view["public_events"])


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

    public_ids = {item.get("source_id") for item in view["public_events"]}
    assert "test:turn-one" in public_ids
    assert "test:turn-three" in public_ids


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
    assert json.loads(row["participants"]) == [minister.name]
    before = db.get_character_knowledge(state, minister.name)

    restored = db.load_state()
    after = db.get_character_knowledge(restored, minister.name)

    assert any(item["source_id"] == f"issue:{issue_id}" for item in before["issues"])
    assert before["issues"] == after["issues"]


def test_long_knowledge_bodies_survive_storage_without_brief_card_cap(game):
    db, state, content = game
    reader = next(iter(content.characters.values()))
    body = "甲" * 454
    db.register_character_knowledge_source(
        state, [{"character_id": reader.name}], "audience", "长奏报", body,
        source_id="test:long-source",
    )
    row = db.conn.execute(
        "SELECT body FROM character_knowledge_sources WHERE source_id='test:long-source'"
    ).fetchone()
    assert row["body"] == body


def test_issue_roster_is_structured_and_read_side_projection_needs_no_write_hook(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    issue_id = db.insert_issue(
        state, kind="initiative", title="清丈差事", participants=[
            {"character_id": minister.name, "tier": "主办", "role": "监理", "delegator_id": "毕自严"}
        ]
    )
    row = db.conn.execute("SELECT participants, participant_roster FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert json.loads(row["participants"]) == [minister.name]
    roster = json.loads(row["participant_roster"])
    assert any(
        item.get("character_id") == minister.name and item.get("tier") == "主办"
        for item in roster
    )
    assert any(item["source_id"] == f"issue:{issue_id}" for item in db.get_character_knowledge(state, minister.name)["issues"])


def test_participant_roster_is_discovered_from_persistent_record_without_adapter(game):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    cursor = db.conn.execute(
        """INSERT INTO issues
           (kind, title, origin_turn, stage_text, participants, participant_roster)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("initiative", "未经适配的新案卷", state.turn, "案卷正文",
         "[]", '[{"character_id": "' + minister.name + '"}]'),
    )
    issue_id = int(cursor.lastrowid)
    db.conn.commit()

    view = db.get_character_knowledge(state, minister.name)

    assert any(item["source_id"] == f"issue:{issue_id}" for item in view["issues"])


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
    order_id = create_test_secret_order(db,
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


def test_knowledge_projects_mixed_archive_from_durable_source_scope(game):
    """归档不冻结来源；后续登记立即可读，独立公开版本不授予秘密权限。"""
    db, state, content = game
    ministers = [
        character for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]
    knower, outsider = ministers[:2]
    public_body = "source表公开事项"
    initial_body = "source表不得知密事"

    db.register_character_knowledge_source(
        state,
        [{"character_id": knower.name, "tier": "主办"}],
        "private_matter",
        "密查",
        initial_body,
        source_id="test:durable-secret",
    )
    db.record_public_knowledge_event(
        state, "公开事项", public_body, source_id="test:durable-public",
    )
    db.save_turn_report(state, public_body)
    updated_body = "后续登记的完整正文\r\n保留原样。"
    db.register_character_knowledge_source(
        state, [{"character_id": knower.name, "tier": "主办"}],
        "private_matter", "密查续报", updated_body,
        source_id="test:durable-secret",
    )

    outsider_rows = db.get_character_knowledge(state, outsider.name)["public_events"]
    knower_rows = db.get_character_knowledge(state, knower.name)["events"]
    outsider_ids = {item["source_id"] for item in outsider_rows}
    knower_ids = {item["source_id"] for item in knower_rows}

    assert "test:durable-public" in outsider_ids
    assert "test:durable-secret" not in outsider_ids
    assert "test:durable-secret" in knower_ids
    visible_source = next(
        item for item in knower_rows
        if item["source_id"] == "test:durable-secret"
    )
    assert (visible_source["title"], visible_source["body"]) == ("密查续报", updated_body)


def test_shared_archive_storage_never_writes_restricted_aggregate(game):
    db, state, content = game
    state.turn += 1
    participant = next(iter(content.characters))
    secret = "仅经手人可知的密令细节"
    public = "本月公开政务"
    db.register_character_knowledge_source(
        state, [{"character_id": participant}], "private_matter", "密令", secret,
        source_id="restricted:test-write-boundary",
    )
    db.record_public_knowledge_event(state, "公开事项", public, source_id="public:test-write-boundary")

    db.save_turn_report(state, f"{public}；{secret}", public_body=public)

    assert db.get_turn_report_archive(state.turn)["report"] == public
    outsider = next(name for name in content.characters if name != participant)
    outsider_ids = {
        item.get("source_id")
        for bucket in ("public_events", "events")
        for item in db.get_character_knowledge(state, outsider)[bucket]
    }
    assert "public:test-write-boundary" in outsider_ids
    assert "restricted:test-write-boundary" not in outsider_ids
    own_ids = {
        item.get("source_id")
        for item in db.get_character_knowledge(state, participant)["events"]
    }
    assert "restricted:test-write-boundary" in own_ids

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
        state, f"聚合转述：{secret}", public_body="",
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
    visible_ids = {
        item.get("source_id")
        for item in [*projected["public_events"], *projected["events"]]
    }
    assert "restricted:test-late-reader-boundary" not in visible_ids

def test_raw_aggregate_does_not_authorize_knowledge(game):
    db, state, content = game
    db.conn.execute(
        "INSERT INTO turn_reports(turn, year, period, report) VALUES (?, ?, ?, ?)",
        (state.turn + 9, state.year, state.period, "旧档密令摘要不得公开"),
    )
    db.conn.commit()
    reader = next(iter(content.characters))
    assert not any(
        int(item.get("turn") or 0) == state.turn + 9
        for item in db.get_character_knowledge(state, reader)["public_events"]
    )

def test_structured_person_scope_replaces_role_wide_world_reports(game):
    """Appointment jurisdiction via real declaration entrance — not DB setter hooks."""
    from ming_sim.issues import apply_person_changes_only

    db, state, content = game

    def appoint(name, office, office_type, region_id="", reason="test-appointment"):
        item = {
            "name": name,
            "动作": "任命",
            "office": office,
            "office_type": office_type,
            "reason": reason,
        }
        if region_id:
            item["region_id"] = region_id
        return apply_person_changes_only(
            db, state, [item], content=content,
        )["applied_person_changes"]

    official = next(c for c in content.characters.values() if c.office_type == "地方")
    applied = appoint(official.name, "河南巡抚", "地方", region_id="henan")
    assert applied and not applied[0].get("rejected"), applied
    # Physical presence elsewhere must not rewrite durable 辖域.
    db.conn.execute(
        "UPDATE characters SET location=? WHERE name=?",
        ("fujian", official.name),
    )
    db.conn.commit()
    scoped = db.get_character_knowledge(state, official.name)
    assert scoped["scope"]["region_ids"] == ("henan",)
    assert "regional" in scoped["world"] and "construction" in scoped["world"]
    assert db.project_office_identity(
        "河南巡抚", "地方", character_name=official.name, location="fujian",
    )["region_ids"] == ("henan",)
    assert db.character_office_region(official.name) == "henan"

    # Explicit content office_region seed; location override still ignored.
    seeded = (
        ("邹维琏", "福建巡抚", "地方", "fujian"),
        ("焦源溥", "大同巡抚", "地方", "shanxi"),
        ("阎鸣泰", "蓟辽总督", "边镇", "liaodong"),
    )
    for name, title, kind, region in seeded:
        row = db.conn.execute(
            "SELECT office, office_type, location FROM characters WHERE name=?",
            (name,),
        ).fetchone()
        assert row is not None and row["office"] == title and row["office_type"] == kind
        assert content.characters[name].office_region == region
        assert db.character_office_region(name) == region
        view = db.get_character_knowledge(state, name)
        assert view["scope"]["region_ids"] == (region,), name
        assert "regional" in view["world"]
        proj = db.project_office_identity(
            title, kind, character_name=name, location="beizhili",
        )
        assert proj["region_ids"] == (region,)
        assert proj["archive_key"] == f"slot:{title}@{region}"

    # Cross-province same bare title must not share or overwrite seat identity.
    other = next(
        c for c in content.characters.values()
        if c.name not in {official.name, "邹维琏", "焦源溥", "阎鸣泰", "练国事"}
        and db.get_character_status(c.name)[0] == "active"
        and c.office_type not in {"地方", "督抚", "边镇"}
    )
    a1 = appoint("练国事", "巡抚", "地方", region_id="shaanxi")
    a2 = appoint(other.name, "巡抚", "地方", region_id="henan")
    assert a1 and not a1[0].get("rejected"), a1
    assert a2 and not a2[0].get("rejected"), a2
    assert db.character_office_region("练国事") == "shaanxi"
    assert db.character_office_region(other.name) == "henan"
    # Cross-province same bare title must not exclusive-displace each other.
    assert db.get_character_status("练国事")[0] == "active"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", ("练国事",),
    ).fetchone()["office"] == "巡抚"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (other.name,),
    ).fetchone()["office"] == "巡抚"
    key_sx = db.project_office_identity("巡抚", "地方", character_name="练国事")
    key_hn = db.project_office_identity("巡抚", "地方", character_name=other.name)
    assert key_sx["archive_key"] == "slot:巡抚@shaanxi"
    assert key_hn["archive_key"] == "slot:巡抚@henan"
    assert key_sx["archive_key"] != key_hn["archive_key"]

    # Succession: same seat title@region shares archive identity with predecessor.
    pred = official.name
    succ = next(
        c.name for c in content.characters.values()
        if c.name not in {pred, other.name, "练国事", "邹维琏", "焦源溥", "阎鸣泰"}
        and db.get_character_status(c.name)[0] == "active"
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="HENAN_SEAT_ARCHIVE",
        target_kind="issue", target_id="henan-seat",
        participants=[{"character_id": pred, "tier": "主办"}],
    )
    # predecessor leaves; successor takes same seat
    appoint(pred, "闲住", "未仕")
    s_applied = appoint(succ, "河南巡抚", "地方", region_id="henan")
    assert s_applied and not s_applied[0].get("rejected"), s_applied
    visible = {
        int(item["id"])
        for item in db.list_referenceable_dossiers(succ, state.turn)
    }
    assert int(dossier_id) in visible
    assert db.project_office_identity(
        "河南巡抚", "地方", character_name=succ,
    )["archive_key"] == "slot:河南巡抚@henan"

    # 未仕/内廷 mere location is not jurisdiction.
    idle = next(
        c for c in content.characters.values()
        if c.office_type not in {"地方", "督抚", "边镇"}
        and c.name not in {succ, other.name}
    )
    regions = [str(r["id"]) for r in db.conn.execute("SELECT id FROM regions ORDER BY id").fetchall()]
    assert len(regions) >= 2
    db.conn.execute(
        "UPDATE characters SET office=?, office_type=?, location=? WHERE name=?",
        ("闲住", "未仕", regions[0], idle.name),
    )
    db.conn.commit()
    idle_proj = db.project_office_identity(
        "闲住", "未仕", character_name=idle.name, location=regions[0],
    )
    assert idle_proj["region_ids"] == ()
    assert idle_proj["archive_key"] == ""
    assert db.get_character_knowledge(state, idle.name)["scope"]["region_ids"] == ()
    inner_proj = db.project_office_identity("内廷随侍", "内廷", location=regions[1])
    assert inner_proj["region_ids"] == ()
    assert inner_proj["archive_key"] == ""

    # Local appointment missing region_id is rejected item-wise — no silent empty 辖域.
    bare = next(
        c for c in content.characters.values()
        if c.name not in {
            official.name, idle.name, other.name, succ, "邹维琏", "焦源溥", "阎鸣泰", "练国事",
        }
        and db.get_character_status(c.name)[0] == "active"
        and c.office_type not in {"地方", "督抚", "边镇"}
    )
    prior_office = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (bare.name,),
    ).fetchone()
    rejected = appoint(bare.name, "新设巡抚", "地方")
    assert rejected and rejected[0].get("rejected"), rejected
    assert rejected[0].get("category") == "missing_field", rejected
    assert isinstance(rejected[0].get("item"), dict), rejected
    assert rejected[0]["item"].get("office") == "新设巡抚"
    assert rejected[0]["item"].get("office_type") == "地方"
    assert "region_id" not in rejected[0]["item"]
    after = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (bare.name,),
    ).fetchone()
    assert after["office"] == prior_office["office"]
    assert db.get_character_knowledge(state, bare.name)["scope"]["region_ids"] == ()
    # Unknown region_id is typed missing_ref — still no silent empty 辖域.
    unknown = appoint(bare.name, "新设巡抚", "地方", region_id="not_a_region")
    assert unknown and unknown[0].get("rejected"), unknown
    assert unknown[0].get("category") == "missing_ref", unknown
    assert isinstance(unknown[0].get("item"), dict), unknown
    assert unknown[0]["item"].get("region_id") == "not_a_region"
    after_unknown = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?", (bare.name,),
    ).fetchone()
    assert after_unknown["office"] == prior_office["office"]
    assert db.get_character_knowledge(state, bare.name)["scope"]["region_ids"] == ()
    # Same real entrance later attaches seat; migration still independent of location.
    ok = appoint(bare.name, "新设巡抚", "地方", region_id="jiangxi")
    assert ok and not ok[0].get("rejected"), ok
    db.conn.execute(
        "UPDATE characters SET location=? WHERE name=?", ("henan", bare.name),
    )
    db.conn.commit()
    attached = db.project_office_identity(
        "新设巡抚", "地方", character_name=bare.name, location="henan",
    )
    assert attached["region_ids"] == ("jiangxi",)
    assert attached["archive_key"] == "slot:新设巡抚@jiangxi"
    assert db.get_character_knowledge(state, bare.name)["scope"]["region_ids"] == ("jiangxi",)

    # content 实有中央衙门（六科）进入权威投影，不是手补 whitelist 漏项。
    keke_lead = db.conn.execute(
        "SELECT name, office, office_type FROM characters "
        "WHERE office_type='六科' ORDER BY name LIMIT 1"
    ).fetchone()
    assert keke_lead is not None
    assert db._office_archive_key(
        keke_lead["office"], keke_lead["office_type"],
    ) == "central:六科"
    keke_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="KEKE_ARCHIVE",
        target_kind="issue", target_id="keke-admin",
        participants=[{"character_id": keke_lead["name"], "tier": "主办"}],
    )
    successor = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND name!=? ORDER BY name LIMIT 1",
        (keke_lead["name"],),
    ).fetchone()["name"]
    db.set_character_office(successor, "户科给事中", office_type="六科")
    visible_ids = {
        int(item["id"])
        for item in db.list_referenceable_dossiers(successor, state.turn)
    }
    assert int(keke_id) in visible_ids
    # 外臣等人物 office_type 不得 mint central: 档案身份（朝鲜国王 ≠ 中央衙门）。
    foreign = db.conn.execute(
        "SELECT name FROM characters WHERE office_type='外臣' ORDER BY name LIMIT 2"
    ).fetchall()
    if len(foreign) >= 2:
        assert db._office_archive_key("朝鲜国王", "外臣") == ""
        wai_id = db.create_decree_dossier(
            state, action_type="assignment", decree_text="WAI_LEAK",
            target_kind="issue", target_id="wai-admin",
            participants=[{"character_id": foreign[0]["name"], "tier": "主办"}],
        )
        wai_keys = db.conn.execute(
            "SELECT office_archive_keys FROM decree_dossiers WHERE id=?",
            (int(wai_id),),
        ).fetchone()
        assert json.loads(wai_keys["office_archive_keys"] or "[]") == []
        wai_visible = {
            int(item["id"])
            for item in db.list_referenceable_dossiers(foreign[1]["name"], state.turn)
        }
        assert int(wai_id) not in wai_visible

    # Malformed durable office_archive_keys fail loud on append participant.
    broken = db.create_decree_dossier(
        state, action_type="assignment", decree_text="BROKEN_KEYS",
        target_kind="issue", target_id="broken-keys",
        participants=[{"character_id": official.name, "tier": "主办"}],
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET office_archive_keys=? WHERE id=?",
        ("{not-a-list", int(broken)),
    )
    db.conn.commit()
    helper = next(
        c for c in content.characters.values()
        if c.name != official.name and db.get_character_status(c.name)[0] == "active"
    )
    with pytest.raises((TypeError, ValueError, json.JSONDecodeError)):
        db.append_decree_dossier_participants(
            broken,
            [{"character_id": helper.name, "tier": "协办"}],
            state=state,
        )

    unscoped = next(c for c in content.characters.values() if c.office_type == "礼部")
    world = db.get_character_knowledge(state, unscoped.name)["world"]
    assert not ({"treasury", "military", "regional", "construction", "security"} & set(world))

def test_army_truth_is_exactly_scoped_to_person_command(game):
    db, state, content = game
    general = next(c for c in content.characters.values() if c.office_type == "边镇")
    rows = db.conn.execute("SELECT id,name FROM armies ORDER BY id LIMIT 2").fetchall()
    db.conn.execute("UPDATE armies SET commander='' WHERE commander=?", (general.name,))
    db.conn.execute("UPDATE armies SET commander=? WHERE id=?", (general.name, rows[0]["id"]))
    db.conn.commit()
    view = db.get_character_knowledge(state, general.name)
    # 契约落结构化面：辖域 army_ids 恰是本人统领的那一支。正文 `command` 由
    # db.army_roster(filter_names=scope) 现算，在它里面找军队名只是同源比较，
    # 只能证接线，且人读正文不是记录身份（大理寺 aa62c7def）。
    assert view["scope"]["army_ids"] == (rows[0]["id"],)
    assert view["world"]["command"]


def _office_archive_path_from_materials(db, state, character, root):
    prepared = prepare_character_materials(db, state, character, dest_root=root)
    paths = list_materials(prepared.root)
    return next(p for p in paths if p.endswith("/公事档案.txt"))

def _referenceable_dossier_ids(db, character_name, turn) -> set[int]:
    return {
        int(item["id"])
        for item in db.list_referenceable_dossiers(character_name, turn)
    }

def test_multi_lead_typed_archives_reach_only_each_office_successor(game, tmp_path):
    db, state, content = game
    people = [c for c in content.characters.values() if db.get_character_status(c.name)[0] == "active"]
    (
        central_lead, slot_lead, central_successor, slot_successor, outsider,
        case_successor, inner_lead, inner_other, case_lead, case_helper,
    ) = people[:10]
    slot = db.conn.execute(
        "SELECT office_title, region_id FROM office_slots "
        "WHERE region_id<>'' ORDER BY sort_order LIMIT 1"
    ).fetchone()
    slot_region = str(slot["region_id"] or "").strip()
    other_region = db.conn.execute(
        "SELECT id FROM regions WHERE id<>? ORDER BY id LIMIT 1", (slot_region,),
    ).fetchone()["id"]
    db.set_character_office(central_lead.name, "礼部尚书", office_type="礼部")
    db.set_character_office(
        slot_lead.name, slot["office_title"], office_type="地方", region_id=slot_region,
    )
    db.record_character_participation(
        state, [central_lead.name], "private_matter", "私事", "PRIVATE_HISTORY_ONLY",
    )
    joint_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="JOINT_ADMIN_ARCHIVE",
        target_kind="issue", target_id="joint-admin",
        participants=[
            {"character_id": central_lead.name, "tier": "主办"},
            {"character_id": slot_lead.name, "tier": "主办"},
        ],
    )
    db.set_character_office(central_lead.name, "闲住", office_type="未仕")
    db.set_character_office(slot_lead.name, "闲住", office_type="未仕")
    db.set_character_office(central_successor.name, "礼部尚书", office_type="礼部")
    db.set_character_office(
        slot_successor.name, slot["office_title"], office_type="地方", region_id=slot_region,
    )
    db.set_character_office(
        outsider.name, "另一地方官", office_type="地方", region_id=other_region,
    )
    db.set_character_office(case_successor.name, "刑部尚书", office_type="刑部")
    db.set_character_office(inner_lead.name, "内廷随侍", office_type="内廷")
    db.set_character_office(inner_other.name, "内廷随侍", office_type="内廷")
    inner_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="INNER_COURT_ARCHIVE",
        target_kind="issue", target_id="inner-admin",
        participants=[{"character_id": inner_lead.name, "tier": "主办"}],
    )
    db.set_character_office(case_lead.name, "刑部尚书", office_type="刑部")
    db.set_character_office(case_helper.name, "锦衣卫指挥使", office_type="锦衣卫")
    case_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="CASE_FILE_ARCHIVE",
        target_kind="issue", target_id="criminal-case",
        participants=[
            {"character_id": case_lead.name, "tier": "主办"},
            {"character_id": case_helper.name, "tier": "协办"},
        ],
    )
    db.set_character_office(case_lead.name, "闲住", office_type="未仕")

    turn = int(state.turn)
    joint_id, inner_id, case_id = int(joint_id), int(inner_id), int(case_id)
    for reader in (central_successor, slot_successor):
        ids = _referenceable_dossier_ids(db, reader.name, turn)
        assert joint_id in ids
    assert joint_id not in _referenceable_dossier_ids(db, outsider.name, turn)
    assert joint_id not in _referenceable_dossier_ids(db, case_successor.name, turn)
    assert inner_id in _referenceable_dossier_ids(db, inner_lead.name, turn)
    assert inner_id not in _referenceable_dossier_ids(db, inner_other.name, turn)
    assert case_id in _referenceable_dossier_ids(db, case_helper.name, turn)
    # 刑部 is a legal central yamen: successor shares archive identity with the lead.
    assert case_id in _referenceable_dossier_ids(db, case_successor.name, turn)

def test_central_ledgers_reach_each_office_archive_carrier_without_crossing(game, tmp_path):
    """户部／兵部／吏部各自只带自己那把账键，且都落在本人 公事档案.txt 载体上。

    契约只落结构化面（大理寺 01a0f1f4 裁定）：载体路径存在 + 本人
    `get_character_knowledge` 的 world 账键恰是自己那把。删去的两类断言不得
    换形复造：
    - 不重调生产渲染器逐字比档案正文（与被调函数同进同出，只证接线）；
    - 不用 reason／人名在档案正文里做子串推断来证「逐条完整」或「不串门」
      （旧账1 被旧账10 顶替仍绿；兵名／人名会与别段偶然撞字）。
    """
    db, state, content = game

    from ming_sim.materials import _LEDGER_KEYS

    holders = {
        office_type: next(
            c for c in content.characters.values() if c.office_type == office_type
        )
        for office_type in ("户部", "兵部", "吏部")
    }
    office_ledger_key = {"户部": "treasury", "兵部": "military", "吏部": "personnel"}
    for office_type, character in holders.items():
        # 载体面：本衙门职官的材料目录里有本人公事档案。
        assert _office_archive_path_from_materials(
            db, state, character, tmp_path / office_type,
        ).endswith("/公事档案.txt")
        # 准入面：本人 world 只带自己那把账键（跨衙门不串门，结构化字段）。
        knowledge = db.get_character_knowledge(state, character.name)
        assert [
            key for key in (knowledge.get("world") or {}) if key in _LEDGER_KEYS
        ] == [office_ledger_key[office_type]]


def test_current_state_facts_are_selected_by_content_domain_not_role_label(
    game, monkeypatch
):
    db, state, content = game
    minister = next(c for c in content.characters.values() if c.office_type == "吏部")

    # 契约只落结构化面：本门类的账键恰是 personnel，他衙门那两把不在；越界读取
    # 由「调用即抛」钉死，而不是在人事正文里做人名／官职子串推断（人读正文不是
    # 结构化记录身份，大理寺 aa62c7def）。
    def forbidden(*_args, **_kwargs):
        raise AssertionError("吏部见闻不应读取军情／国库／派系底账")

    monkeypatch.setattr(db, "army_report", forbidden)
    monkeypatch.setattr(db, "treasury_report", forbidden)

    view = db.get_character_knowledge(state, minister.name)["world"]
    assert db.current_court_roster_rows(state)
    assert "personnel" in view
    assert "military" not in view
    assert "treasury" not in view


