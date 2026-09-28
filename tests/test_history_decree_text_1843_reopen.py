"""#1843 reopen：史册本月诏书改读 pending_resolve_context.decree_text。"""

from __future__ import annotations


def test_history_turn_reads_decree_text_from_resolve_context(game):
    db, state, content = game
    turn = int(state.turn)
    db.save_resolve_context(
        turn,
        decree_text="着宁远补饷三十万两",
        narrative="",
        simulator_payload={},
    )
    db.save_turn_report(state, "邸报正文", knowledge_items=[], attendant_message="")
    # No turn_extractions table/row.
    assert not hasattr(db, "get_turn_extraction")
    row = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='turn_extractions'"
    ).fetchone()
    assert row is None

    ctx = db.get_resolve_context(turn) or {}
    assert str(ctx.get("decree_text") or "") == "着宁远补饷三十万两"
