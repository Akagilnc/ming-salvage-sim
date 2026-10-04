def test_hidden_affair_strategic_result_does_not_trigger_or_land(game):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    hidden = db.affairs.open(
        name="已了结事务", origin="未供料", year=state.year,
        period=state.period, turn=state.turn,
    )
    db.affairs.declare_closed(hidden.id, turn=state.turn)
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    dispatch_month_segment(db, state, segment="不可见事务战果", translate_fn=lambda _request, _config: {
        "effects": [{
            "event_id": "jisi_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {"beizhili": {
                "origin_ref": f"affair:{hidden.id}", "military_pressure": 5,
            }},
            "metric_delta": {"民心": -3},
            "economy_moves": [{
                "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                "category": "过月支出", "reason": "事件所属军需",
            }],
        }],
    })
    assert db.has_event_triggered("jisi_lubian") is False
    assert state.metrics["民心"] == metric_before
    assert state.metrics["国库"] == treasury_before
