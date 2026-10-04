def test_t9_idempotency_namespace_and_empty_planned(game):
    from ming_sim.centrifuge_ledger import accrue_blood_debt

    db, state, _content = game

    # ① replay：同参两次，第二次零增
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t9|replay",
        reason_code="依律",
        source="s",
    )
    mid = _snapshot(db)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="抄家",
        crime_weight=70,
        idem_base="t9|replay",
        reason_code="依律",
        source="s",
    )
    assert _snapshot(db) == mid

    # ② 同 idem_base 异载荷（换 target）且 kinds 仍能凑集合相等 → Abort
    # 先用另一 base 写军队目标，确保军队可被写；此处专门：已有 t9|payload 写阉党后换军队
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|payload",
    )
    before_payload = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=1,
            idem_base="t9|payload",
        )
    assert _snapshot(db) == before_payload

    # ③ 旧批多 kind / 当前真子集：identity→0 去掉 kinship
    _set_identity(db, _TARGET_ARMY, 80)
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_ARMY,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|subset",
    )
    kinds_first = {
        r["kind"]
        for r in _log_rows(db)
        if str(r["idem_key"]).startswith("t9|subset|")
    }
    assert kinds_first == {"direct", "kinship"}
    _set_identity(db, _TARGET_ARMY, 0)
    before_subset = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_ARMY,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=1,
            idem_base="t9|subset",
        )
    assert _snapshot(db) == before_subset

    # ④ 旧批非空 / 当前 planned 空：申饬 cw1→cw3，同 target/axis/idem_base
    accrue_blood_debt(
        db=db,
        turn=state.turn,
        target=_TARGET_EUNUCH,
        axis=_AXIS,
        penalty_type="申饬",
        crime_weight=1,
        idem_base="t9|empty_planned",
    )
    first_rows = [
        r
        for r in _log_rows(db)
        if str(r["idem_key"]).startswith("t9|empty_planned|")
    ]
    assert any(r["kind"] == "direct" and int(r["amount"]) == 2 for r in first_rows)
    before_empty = _snapshot(db)
    with pytest.raises(SettlementAbort):
        accrue_blood_debt(
            db=db,
            turn=state.turn,
            target=_TARGET_EUNUCH,
            axis=_AXIS,
            penalty_type="申饬",
            crime_weight=3,
            idem_base="t9|empty_planned",
        )
    assert _snapshot(db) == before_empty
