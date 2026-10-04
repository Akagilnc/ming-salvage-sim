def test_load_relation_history_before_empty_when_no_older_events(game):
    """r4 验收第三例：无严格更早流水 → 空列表。"""
    from ming_sim.relation_read import load_relation_history_before

    db, state, _ = game
    db.record_relation_edge_event(
        source="徐光启", target="杨嗣昌", event_kind="协作",
        context="本月当场协作。", origin="audience:now",
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    prior = load_relation_history_before(
        db, source="徐光启", target="杨嗣昌",
        before_year=int(state.year), before_period=int(state.period),
    )
    assert prior == []
