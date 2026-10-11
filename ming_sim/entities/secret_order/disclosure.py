"""密令延后披露落库：由 issues.py 清算迁入（ADR 0150 决定 8）。"""

from __future__ import annotations


from typing import Any

from ming_sim.decree_vocabulary import (
    format_public_progress_disclosure,
)


def record_secret_order_disclosure(
    db: Any,
    state: Any,
    order_id: int,
    sim_note: str,
) -> bool:
    """Record public knowledge event for secret order disclosure if not already disclosed (#883, ADR 0157).

    Returns True if a new public knowledge event was recorded, False otherwise.
    """
    order = db.character_knowledge.get_secret_order(order_id)
    if order is None:
        return False
    # Disclosure is the only promotion from the assignee-only
    # brief into a public knowledge event (#883).
    # Cross-turn dedupe: disclosed is a state (prompt) not a monthly
    # event — re-true each month must not mint another public row.
    disclosure_prefix = f"secret_order_disclosure:{order_id}:"
    # LIKE treats `_`/`%` as wildcards; escape the literal prefix
    # (same ESCAPE idiom as db.py iter_budget_items / get_fiscal_config).
    like_prefix = (
        disclosure_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    already_disclosed = db.conn.execute(
        "SELECT 1 FROM character_knowledge_events "
        "WHERE character_name='' AND source_id LIKE ? ESCAPE '\\' LIMIT 1",
        (f"{like_prefix}%",),
    ).fetchone()
    if already_disclosed is not None:
        return False
    dossier = db.dossiers.get_for_secret_order(order_id)
    progress = (
        db.dossiers.list_dossier_progress(int(dossier["id"])) if dossier is not None else []
    )
    progress_text = format_public_progress_disclosure(progress)
    public_body = sim_note
    if progress_text:
        public_body = f"{sim_note}\n{progress_text}"
    db.record_public_knowledge_event(
        state,
        str(order["title"]),
        public_body,
        source_id=f"{disclosure_prefix}{state.turn}",
        commit=False,
    )
    return True
