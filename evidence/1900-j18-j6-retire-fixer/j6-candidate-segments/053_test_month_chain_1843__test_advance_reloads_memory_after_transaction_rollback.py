def test_advance_reloads_memory_after_transaction_rollback(game, monkeypatch):
    db, state, content = game
    turn = int(state.turn)
    db.save_turn_report(state, "邸报已成")

    def fail_after_advance(*_args, **_kwargs):
        raise RuntimeError("injected tail failure")

    monkeypatch.setattr(
        decree_mod, "_carry_pending_clarification_actions", fail_after_advance,
    )
    with pytest.raises(RuntimeError, match="injected tail failure"):
        month_chain._advance_after_gazette(
            db, state, {}, turn, "", month_chain.Provenance.system_simulation,
            content=content,
        )

    assert int(state.turn) == turn
    assert db.load_state().turn == turn
