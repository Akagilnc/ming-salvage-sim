def test_t5_bastinado_overdraw_batch_and_non_bastinado(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game
    faction = _faction_of(db, _TARGET_EUNUCH)
    before_od = _overdraw_map(db)[faction]

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="廷杖",
        crime_weight=1,
        idem_base="t5|廷杖",
    )
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t5|廷杖|")]
    kinds = {r["kind"] for r in rows}
    assert "overdraw" in kinds
    od = next(r for r in rows if r["kind"] == "overdraw")
    assert od["axis"] is None and od["base"] is None and od["legitimacy_pct"] is None
    assert int(od["amount"]) == 1
    assert _overdraw_map(db)[faction] == before_od + 1

    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="罢黜",
        crime_weight=1,
        idem_base="t5|罢黜",
    )
    non = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t5|罢黜|")]
    assert all(r["kind"] != "overdraw" for r in non)
