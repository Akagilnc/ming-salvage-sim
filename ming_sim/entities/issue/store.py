"""Issue rows and issue advances.

#1889: one write port. Phase, status and bar arithmetic stay with the caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from ming_sim.entities.column_write import checked_columns


ISSUE_COLUMNS = frozenset({
    "kind", "title", "origin_kind", "origin_ref", "origin_turn",
    "bar_value", "bar_good_meaning", "bar_bad_meaning", "inertia",
    "phase", "stage_text", "status", "severity", "region_hint", "faction_hint",
    "tags", "participants", "participant_roster", "target_roster",
    "ongoing_effects", "cancellable", "cancel_cost",
    "effect_on_resolve", "effect_on_fail", "resolve_condition", "fail_condition",
    "end_turn", "stop_condition", "commitment_kind", "stages_json",
    "resolution_summary", "last_advance_turn", "closed_turn", "affair_id",
})

_ADVANCE_COLUMNS = (
    "issue_id", "turn", "trigger_kind", "trigger_ref", "delta_bar",
    "from_value", "to_value", "from_stage_text", "to_stage_text",
    "narrative", "metric_delta",
)


def _checked(values: Mapping[str, object]) -> list[str]:
    return checked_columns(values, ISSUE_COLUMNS, what="issues")


class IssueStore:
    """Single write port for an issue and its advances."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert(self, row: Mapping[str, object]) -> int:
        columns = _checked(row)
        if not columns:
            raise ValueError("issues insert needs fields")
        placeholders = ", ".join("?" for _ in columns)
        cursor = self._conn.execute(
            f"INSERT INTO issues ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )
        return int(cursor.lastrowid)

    def update(self, issue_id: int, values: Mapping[str, object]) -> int:
        columns = _checked(values)
        if not columns:
            raise ValueError("issues update needs fields")
        assignments = ", ".join(f"{column}=?" for column in columns)
        cursor = self._conn.execute(
            f"UPDATE issues SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [values[column] for column in columns] + [int(issue_id)],
        )
        return int(cursor.rowcount or 0)

    def append_advance(self, row: Mapping[str, object]) -> None:
        checked_columns(row, set(_ADVANCE_COLUMNS), what="issue_advances")
        columns = [column for column in _ADVANCE_COLUMNS if column in row]
        if "issue_id" not in columns or "turn" not in columns or "trigger_kind" not in columns:
            raise ValueError("issue_advances needs issue_id, turn, trigger_kind")
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT INTO issue_advances ({', '.join(columns)}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def affair_id_of(self, issue_id: int) -> int:
        row = self._conn.execute(
            "SELECT affair_id FROM issues WHERE id=?", (int(issue_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"局势不存在：{issue_id}")
        return int(row["affair_id"] or 0)

    def set_affair_id_if_unbound(self, issue_id: int, affair_id: int) -> int:
        """Bind once; same id is idempotent; a different id fails loud."""
        from ming_sim.applier import connection_owns_transaction

        want = int(affair_id)
        target = int(issue_id)
        owns = connection_owns_transaction(self._conn)
        cursor = self._conn.execute(
            "UPDATE issues SET affair_id=? WHERE id=? AND affair_id=0",
            (want, target),
        )
        if int(cursor.rowcount or 0) == 1:
            if owns:
                self._conn.commit()
            return want
        current = self.affair_id_of(target)
        if current == want:
            if owns:
                self._conn.commit()
            return want
        if owns:
            self._conn.rollback()
        raise ValueError(f"局势已指向事务 {current}，不能改指 {want}")
