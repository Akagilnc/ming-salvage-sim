def test_final_strategic_rejection_leaves_no_owned_effects(game):
    """Owned fields and the event ledger stay one envelope.

    An independent same-kind delta may move the board before the event is
    judged (#1844). Whatever this entry finally records, a non-trigger must
    not keep the event's own metric or treasury delta.
    """
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    state.year, state.period = 1629, 11
    state.metrics["民心"] = 50
    db.conn.execute("UPDATE regions SET military_pressure=90 WHERE id='beizhili'")
    db.conn.commit()
    metric_before = state.metrics["民心"]
    treasury_before = state.metrics["国库"]
    dispatch_month_segment(db, state, segment="独立军压后事件战果", translate_fn=lambda _request, _config: {
        "effects": [
            {"region_delta": {"beizhili": {
                "origin_ref": "盘面自发", "military_pressure": 10,
            }}},
            {
                "event_id": "jisi_lubian",
                "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
                "事件结局": {"jisi_lubian": "入塞被遏"},
                "region_delta": {"beizhili": {
                    "origin_ref": "盘面自发", "military_pressure": 5,
                    "reason": "己巳之变敌逼京畿",
                }},
                "metric_delta": {"民心": -3},
                "economy_moves": [{
                    "origin_ref": "盘面自发", "account": "国库", "delta": -1,
                    "category": "过月支出", "reason": "事件所属军需",
                }],
            },
        ],
    })
    triggered = db.has_event_triggered("jisi_lubian")
    assert state.metrics["民心"] == metric_before + (-3 if triggered else 0)
    assert state.metrics["国库"] == treasury_before + (-1 if triggered else 0)
