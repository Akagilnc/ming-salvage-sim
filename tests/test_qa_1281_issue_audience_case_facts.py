"""#1281: issue materials = knowledge visibility ∪ audience-named supplement."""

from __future__ import annotations





ISSUE_TITLE = "户部亏空"


def _issue_row(db):
    row = db.conn.execute(
        "SELECT id, stage_text, origin_ref FROM issues WHERE title=? AND status='active' LIMIT 1",
        (ISSUE_TITLE,),
    ).fetchone()
    assert row is not None
    return row
