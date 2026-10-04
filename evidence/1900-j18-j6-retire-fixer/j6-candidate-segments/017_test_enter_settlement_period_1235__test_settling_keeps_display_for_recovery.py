def test_settling_keeps_display_for_recovery(game):
    """AC3：settling 相位下快照保留（恢复入口可达的状态口条件）。"""
    db, state, content = game
    before = _click_before(state)
    db.capture_month_open_snapshot(state)
    import ming_sim.decree as dm
    dm.pre_settle(state, db, content=content)
    assert state.turn_phase == TurnPhase.SETTLING.value
    # 真失败退出不得误清 settling 快照
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    assert exit_settlement_display_on_failure(db, state) is False
    assert db.get_month_open_snapshot(int(state.turn)) == before
    payload = _runtime_payload(db, state)
    assert payload["turn"]["settlement_display"] is True
    assert payload["turn"]["phase"] == "settling"
