def test_pre_tianqi_seed_event_retains_structured_clock(fresh_session):
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    doc = {"events": [{
        "source": "丙", "target": "丁", "event_kind": "结怨", "context": "旧事。",
        "origin": "seed:1620", "evidence": False, "year": 1620, "period": 1,
    }]}
    import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    rows = sess.db.get_relation_edge_events(source="丙", target="丁")
    assert [(row["year"], row["period"]) for row in rows] == [(1620, 1)]
