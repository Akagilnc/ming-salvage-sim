def test_staged_ending_is_available_inside_its_settlement_transaction(game):
    db, state, _content = game
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import (
        settle_staged_declarations_in_decree_order, stage_declaration,
    )

    stage_declaration(
        db, decree_ref="ending-decree", turn=int(state.turn),
        declaration={"effects": {"emperor_fate": "abdicate"}},
    )
    committed = {}
    settled = settle_staged_declarations_in_decree_order(
        db, state, ["ending-decree"], source=Provenance.player_decree,
        alongside=lambda ref, result: committed.update(
            ref=ref, outcome=month_chain._ending_from_dispatch_result(result),
        ),
    )

    assert "ending-decree" in settled
    assert committed["ref"] == "ending-decree"
    assert committed["outcome"]["status"] == "emperor_abdicate"
    assert db.staged_declarations.is_settled("ending-decree")
