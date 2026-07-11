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
        "secret_order",
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
        "secret_order",
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
        "secret_order",
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
        "secret_order", "密查", "受限来源标记",
        source_id="test:chapter-restricted", excluded_names=[excluded.name],
    )

    counterpart = _public_chapter_counterpart(db.knowledge_items_for_turn(state.turn))

    assert "公开来源标记" in counterpart
    assert "受限来源标记" not in counterpart
