"""#1281: issue materials = knowledge visibility ∪ audience-named supplement."""

from __future__ import annotations

import json

import pytest

from ming_sim.knowledge import project_issue_materials
from ming_sim.materials import list_materials, prepare_character_materials


AUDIENCE_NAME = "郭允厚"
ISSUE_TITLE = "户部亏空"
NON_AUDIENCE_NAME = "崔呈秀"
PRIVATE_PARTICIPANT = "温体仁"


def _issue_row(db):
    row = db.conn.execute(
        "SELECT id, stage_text, origin_ref FROM issues WHERE title=? AND status='active' LIMIT 1",
        (ISSUE_TITLE,),
    ).fetchone()
    assert row is not None
    return row


def _issue_paths(prepared, issue_id: int) -> set[str]:
    expected = f"事务/issue-{issue_id}/当前情况.txt"
    return {path for path in list_materials(prepared.root) if path == expected}


def test_issue_materials_keep_knowledge_visibility_without_audience_veto(game, tmp_path):
    db, state, content = game
    issue_id = int(_issue_row(db)["id"])
    audience_knowledge = db.get_character_knowledge(state, AUDIENCE_NAME)
    outsider_knowledge = db.get_character_knowledge(state, NON_AUDIENCE_NAME)
    assert any(int(row["id"]) == issue_id for row in audience_knowledge.get("issues") or [])
    assert any(int(row["id"]) == issue_id for row in outsider_knowledge.get("issues") or [])

    audience_projection = project_issue_materials(db, AUDIENCE_NAME, audience_knowledge)
    outsider_projection = project_issue_materials(db, NON_AUDIENCE_NAME, outsider_knowledge)
    audience_row = next(row for row in audience_projection if row["id"] == issue_id)
    outsider_row = next(row for row in outsider_projection if row["id"] == issue_id)

    assert audience_row["source_id"] == f"issue:{issue_id}"
    assert outsider_row["source_id"] == f"issue:{issue_id}"
    assert AUDIENCE_NAME in audience_row["audience_names"]
    assert NON_AUDIENCE_NAME not in outsider_row["audience_names"]

    audience = prepare_character_materials(
        db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "audience",
    )
    outsider = prepare_character_materials(
        db, state, content.characters[NON_AUDIENCE_NAME], dest_root=tmp_path / "outsider",
    )
    assert _issue_paths(audience, issue_id) == {f"事务/issue-{issue_id}/当前情况.txt"}
    assert _issue_paths(outsider, issue_id) == {f"事务/issue-{issue_id}/当前情况.txt"}
    assert f"事务/issue-{issue_id}/当前情况.txt" in audience.index_lines
    assert f"事务/issue-{issue_id}/当前情况.txt" in outsider.index_lines


def test_empty_audience_is_empty_supplement_not_knowledge_veto(game, tmp_path):
    db, state, content = game
    row = _issue_row(db)
    issue_id = int(row["id"])
    db.conn.execute(
        "UPDATE events SET audiences=? WHERE id=?", ("[]", row["origin_ref"]),
    )

    knowledge = db.get_character_knowledge(state, AUDIENCE_NAME)
    assert any(int(item["id"]) == issue_id for item in knowledge.get("issues") or [])
    projected = next(
        item for item in project_issue_materials(db, AUDIENCE_NAME, knowledge)
        if item["id"] == issue_id
    )
    assert projected["audience_names"] == ()

    prepared = prepare_character_materials(
        db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "materials",
    )
    assert _issue_paths(prepared, issue_id) == {f"事务/issue-{issue_id}/当前情况.txt"}


def test_audience_supplement_grants_originating_issue_outside_knowledge(game, tmp_path):
    db, state, content = game
    row = _issue_row(db)
    issue_id = int(row["id"])
    db.conn.execute(
        "UPDATE issues SET participant_roster=? WHERE id=?",
        (json.dumps([{"character_id": PRIVATE_PARTICIPANT}], ensure_ascii=False), issue_id),
    )

    audience_knowledge = db.get_character_knowledge(state, AUDIENCE_NAME)
    outsider_knowledge = db.get_character_knowledge(state, NON_AUDIENCE_NAME)
    assert all(int(item["id"]) != issue_id for item in audience_knowledge.get("issues") or [])
    assert all(int(item["id"]) != issue_id for item in outsider_knowledge.get("issues") or [])

    audience_projection = project_issue_materials(db, AUDIENCE_NAME, audience_knowledge)
    outsider_projection = project_issue_materials(db, NON_AUDIENCE_NAME, outsider_knowledge)
    projected = next(item for item in audience_projection if item["id"] == issue_id)
    assert projected["source_id"] == f"issue:{issue_id}"
    assert AUDIENCE_NAME in projected["audience_names"]
    assert all(item["id"] != issue_id for item in outsider_projection)

    audience = prepare_character_materials(
        db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "audience",
    )
    outsider = prepare_character_materials(
        db, state, content.characters[NON_AUDIENCE_NAME], dest_root=tmp_path / "outsider",
    )
    assert _issue_paths(audience, issue_id) == {f"事务/issue-{issue_id}/当前情况.txt"}
    assert _issue_paths(outsider, issue_id) == set()


@pytest.mark.parametrize(
    "stored_audiences",
    ["{}", "not-json", "null", '[1, "郭允厚"]', '["郭允厚", {"name": "x"}]'],
)
def test_malformed_event_audience_fails_loud_from_material_entry(game, tmp_path, stored_audiences):
    db, state, content = game
    row = _issue_row(db)
    db.conn.execute(
        "UPDATE events SET audiences=? WHERE id=?", (stored_audiences, row["origin_ref"]),
    )

    with pytest.raises((TypeError, ValueError, json.JSONDecodeError)):
        prepare_character_materials(
            db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "materials",
        )


def test_malformed_knowledge_issue_id_fails_loud_from_projection(game):
    db, state, _content = game
    knowledge = dict(db.get_character_knowledge(state, AUDIENCE_NAME))
    issues = list(knowledge.get("issues") or [])
    assert issues
    bad = dict(issues[0])
    bad["id"] = "not-an-id"
    knowledge["issues"] = [bad, *issues[1:]]

    with pytest.raises((TypeError, ValueError)):
        project_issue_materials(db, AUDIENCE_NAME, knowledge)


def test_event_audience_read_failure_escapes_material_preparation(game, tmp_path):
    db, state, content = game
    real_conn = db.conn

    class FailingEventAudienceConnection:
        def __getattr__(self, name):
            return getattr(real_conn, name)

        def execute(self, sql, parameters=()):
            if "SELECT audiences FROM events" in sql:
                raise RuntimeError("audience ledger read failed")
            return real_conn.execute(sql, parameters)

    db.conn = FailingEventAudienceConnection()
    try:
        with pytest.raises(RuntimeError, match="audience ledger read failed"):
            prepare_character_materials(
                db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "materials",
            )
    finally:
        db.conn = real_conn


def test_issue_material_projection_does_not_pollute_durable_events_or_db(game, tmp_path):
    db, state, content = game
    row = _issue_row(db)
    issue_id = int(row["id"])
    stage_before = row["stage_text"]
    public_before = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events WHERE character_name=''"
    ).fetchone()["n"])
    durable_before = tuple(db.get_character_knowledge(state, AUDIENCE_NAME).get("events") or [])

    prepared = prepare_character_materials(
        db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "materials",
    )

    assert _issue_paths(prepared, issue_id)
    assert tuple(db.get_character_knowledge(state, AUDIENCE_NAME).get("events") or []) == durable_before
    row_after = _issue_row(db)
    assert row_after["stage_text"] == stage_before
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM character_knowledge_events WHERE character_name=''"
    ).fetchone()["n"]) == public_before
