"""Shared test fixtures for rescript_draft row planting (explicit idx/event_id only)."""

from __future__ import annotations

import json


def sql_rescript_draft(
    db,
    turn,
    *,
    idx,
    event_id,
    title,
    context="",
    options=None,
    actor_name="",
    actor_office="",
    actor_faction="",
):
    """Single-row SQL plant: idx and event_id required; no retired write-path rules."""
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, event_id, title, context, options_json, choice_json, "
        " status, kind, actor_name, actor_office, actor_faction) "
        "VALUES (?, ?, ?, ?, ?, ?, '', 'pending', 'rescript_draft', ?, ?, ?)",
        (
            int(turn),
            int(idx),
            str(event_id),
            str(title),
            str(context),
            json.dumps(options or [], ensure_ascii=False),
            str(actor_name),
            str(actor_office),
            str(actor_faction),
        ),
    )
