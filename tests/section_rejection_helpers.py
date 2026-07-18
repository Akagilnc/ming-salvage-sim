"""Shared setup seam for rejection-section integration tests.

The harness deliberately dispatches through ``driver.run_settle`` so rejection
fixtures exercise the rendered production contract rather than a pre-seeded
input or an applier implementation detail.
"""

from __future__ import annotations

from driver import run_settle


def rejection_rows(db, turn, section=None, *, columns="section, reason, category, source"):
    query = (
        f"SELECT {columns} FROM rejection_reports"
        " WHERE turn=?"
    )
    params = [turn]
    if section is not None:
        query += " AND section=?"
        params.append(section)
    return db.conn.execute(query + " ORDER BY id", params).fetchall()


class SectionRejectionHarness:
    """Run one rejection section through settlement and return its durable rows."""

    def __init__(self, game):
        self.db, self.state, self.content = game

    def settle(self, delta, *, section=None, narrative="x", decree_text="y"):
        turn = self.state.turn
        run_settle(
            self.db,
            self.state,
            self.content,
            delta,
            narrative=narrative,
            decree_text=decree_text,
        )
        return rejection_rows(self.db, turn, section)
