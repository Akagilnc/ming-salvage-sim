"""#1281: issue audience facts use the canonical typed material projection."""

from __future__ import annotations

import pytest

from ming_sim.knowledge import project_issue_materials
from ming_sim.materials import list_materials, prepare_character_materials


AUDIENCE_NAME = "郭允厚"
ISSUE_TITLE = "户部亏空"
NON_AUDIENCE_NAME = "崔呈秀"


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


def test_issue_material_is_visible_only_to_the_typed_event_audience(game, tmp_path):
    db, state, content = game
    issue_id = int(_issue_row(db)["id"])
    audience_projection = project_issue_materials(
        db, AUDIENCE_NAME, db.get_character_knowledge(state, AUDIENCE_NAME),
    )
    outsider_projection = project_issue_materials(
        db, NON_AUDIENCE_NAME, db.get_character_knowledge(state, NON_AUDIENCE_NAME),
    )
    projected = next(row for row in audience_projection if row["id"] == issue_id)
    assert projected["source_id"] == f"issue:{issue_id}"
    assert AUDIENCE_NAME in projected["audience_names"]
    assert all(row["id"] != issue_id for row in outsider_projection)

    audience = prepare_character_materials(
        db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "audience",
    )
    outsider = prepare_character_materials(
        db, state, content.characters[NON_AUDIENCE_NAME], dest_root=tmp_path / "outsider",
    )

    assert _issue_paths(audience, issue_id) == {f"事务/issue-{issue_id}/当前情况.txt"}
    assert _issue_paths(outsider, issue_id) == set()
    assert f"事务/issue-{issue_id}/当前情况.txt" in audience.index_lines
    assert f"事务/issue-{issue_id}/当前情况.txt" not in outsider.index_lines


@pytest.mark.parametrize("stored_audiences", ["[]", "{}", "not-json"])
def test_event_issue_without_valid_audience_is_absent_from_the_material_directory(
    game, tmp_path, stored_audiences,
):
    db, state, content = game
    row = _issue_row(db)
    issue_id = int(row["id"])
    db.conn.execute(
        "UPDATE events SET audiences=? WHERE id=?", (stored_audiences, row["origin_ref"]),
    )

    prepared = prepare_character_materials(
        db, state, content.characters[AUDIENCE_NAME], dest_root=tmp_path / "materials",
    )

    assert _issue_paths(prepared, issue_id) == set()
    assert f"事务/issue-{issue_id}/当前情况.txt" not in prepared.index_lines


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
