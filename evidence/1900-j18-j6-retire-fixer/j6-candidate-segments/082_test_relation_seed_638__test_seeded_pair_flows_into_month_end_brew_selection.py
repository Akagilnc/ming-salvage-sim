def test_seeded_pair_flows_into_month_end_brew_selection(fresh_session):
    """同一套酿制（ADR 0086 机械面）：seed 对在真实月末落新事件后，月末腿照常
    选中该对，且 seed 边因水位为 0 一并进入酿制输入。"""
    from ming_sim.relation_brew import collect_new_edge_events, select_brew_targets

    sess, _content = fresh_session
    state = sess.state
    pair_events = [
        e for e in sess.db.get_relation_edge_events()
        if e["source"] == "魏忠贤" and e["target"] == "杨涟"
    ]
    assert pair_events, "样例 seed 缺魏忠贤→杨涟奠基边"

    new_id = sess.db.record_relation_edge_event(
        source="魏忠贤", target="杨涟", event_kind="结怨",
        context="崇祯元年十月新账。",
        origin="test:month-event", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    targets = select_brew_targets(db=sess.db, year=int(state.year), period=int(state.period))
    match = [t for t in targets if t["source"] == "魏忠贤" and t["target"] == "杨涟"]
    assert match, "seed 对未被月末腿选中"
    assert int(match[0]["watermark"]) == 0, "seed 导入不得推进水位"

    new_events = collect_new_edge_events(
        db=sess.db, source="魏忠贤", target="杨涟", watermark=0,
    )
    ids = {int(event["id"]) for event in new_events}
    assert int(new_id) in ids
    assert {int(event["id"]) for event in pair_events} <= ids
