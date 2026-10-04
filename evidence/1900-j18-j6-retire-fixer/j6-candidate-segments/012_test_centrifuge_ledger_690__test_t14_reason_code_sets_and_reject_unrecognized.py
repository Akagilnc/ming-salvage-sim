def test_t14_reason_code_sets_and_reject_unrecognized(game):
    from ming_sim.centrifuge_ledger import STIGMA_REASON_CODES, accrue_blood_debt

    db, state, _content = game
    for code in ("依律", "谋逆坐实", "贪墨坐实"):
        assert code in PERSON_REASON_CODES
        assert normalize_reason_code(code) == code

    for code in ("中旨除授", "非正途", "罗织"):
        assert code in STIGMA_REASON_CODES
        assert code not in PERSON_REASON_CODES

    before = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="抄家",
            crime_weight=70,
            idem_base="t14|bad_reason",
            reason_code="完全不是码",
        )
    assert _snapshot(db) == before
