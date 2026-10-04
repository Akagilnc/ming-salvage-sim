def test_t3_zero_delta_empty_namespace_is_legal_noop(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=3,
        idem_base="t3|zero",
    )
    assert _snapshot(db) == before
