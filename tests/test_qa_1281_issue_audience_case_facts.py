"""#1281: issue materials = knowledge visibility ∪ audience-named supplement."""

from __future__ import annotations



from ming_sim.materials import list_materials


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
