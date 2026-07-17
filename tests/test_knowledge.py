"""Per-character knowledge projection tests (#489)."""

from __future__ import annotations

import pytest

from ming_sim.knowledge import build_character_knowledge


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
