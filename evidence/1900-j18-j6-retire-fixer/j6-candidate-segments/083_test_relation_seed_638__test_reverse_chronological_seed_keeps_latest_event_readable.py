def test_reverse_chronological_seed_keeps_latest_event_readable(fresh_session):
    """逆序素材按史时稳定写入。"""
    from ming_sim.relation_seed import import_relationship_seed

    sess, _content = fresh_session
    doc = {"events": [
        {"source": "甲", "target": "乙", "event_kind": "结怨", "context": "后事。",
         "origin": "seed:later", "evidence": False, "year": 1626, "period": 2},
        {"source": "甲", "target": "乙", "event_kind": "结怨", "context": "前事。",
         "origin": "seed:earlier", "evidence": False, "year": 1625, "period": 2},
    ]}
    import_relationship_seed(sess.db, doc, opening_year=1627, opening_period=10)
    rows = sess.db.get_relation_edge_events(source="甲", target="乙")
    assert [(row["year"], row["period"]) for row in rows] == [(1625, 2), (1626, 2)]
