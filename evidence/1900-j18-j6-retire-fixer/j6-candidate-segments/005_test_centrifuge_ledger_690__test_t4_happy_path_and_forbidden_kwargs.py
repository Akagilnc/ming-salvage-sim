def test_t4_happy_path_and_forbidden_kwargs(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    before = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t4|happy",
        reason_code="依律",
        source="test",
    )
    faction = _faction_of(db, _TARGET_EUNUCH)
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t4|happy|")]
    kinds = {r["kind"] for r in rows}
    assert "direct" in kinds
    assert "kinship" in kinds
    for r in rows:
        assert r["source_name"] == _TARGET_EUNUCH
        assert r["faction"] == faction
    cache = [
        r
        for r in _cache_rows(db)
        if r["faction"] == faction and r["axis"] == _AXIS
    ]
    assert cache and int(cache[0]["blood_debt"]) > 0

    for kwargs in (
        {"faction": faction},
        {"identity": 50},
        {"amount": 1},
    ):
        snap = _snapshot(db)
        with pytest.raises(TypeError):
            accrue_blood_debt(
                db=db,
                turn=state.turn,
                target=_TARGET_EUNUCH,
                axis=_AXIS,
                penalty_type="抄家",
                crime_weight=70,
                idem_base="t4|forbidden",
                **kwargs,
            )
        assert _snapshot(db) == snap
    assert before != _snapshot(db)
