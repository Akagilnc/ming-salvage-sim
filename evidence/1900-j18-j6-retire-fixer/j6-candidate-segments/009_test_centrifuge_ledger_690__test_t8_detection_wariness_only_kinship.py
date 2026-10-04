def test_t8_detection_wariness_only_kinship(game):
    from ming_sim.centrifuge_ledger import accrue_detection_wariness

    db, state, _content = game
    before = _snapshot(db)
    accrue_detection_wariness(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        alert_severity=10,
        idem_base="t8|det",
        source="alert",
    )
    rows = [r for r in _log_rows(db) if str(r["idem_key"]).startswith("t8|det|")]
    assert len(rows) == 1
    assert rows[0]["kind"] == "kinship"
    assert int(rows[0]["legitimacy_pct"]) == 100
    assert rows[0]["kind"] != "direct"
    assert all(r["kind"] != "overdraw" for r in rows)
    assert all(r["kind"] != "direct" for r in rows)

    for kwargs in (
        {"penalty_type": "抄家"},
        {"crime_weight": 1},
        {"amount": 1},
        {"faction": "阉党"},
        {"identity": 1},
    ):
        snap = _snapshot(db)
        with pytest.raises(TypeError):
            accrue_detection_wariness(
                db=db,
                turn=state.turn,
                target=_TARGET_EUNUCH,
                axis=_AXIS,
                alert_severity=10,
                idem_base="t8|bad",
                **kwargs,
            )
        assert _snapshot(db) == snap
    assert _snapshot(db) != before
