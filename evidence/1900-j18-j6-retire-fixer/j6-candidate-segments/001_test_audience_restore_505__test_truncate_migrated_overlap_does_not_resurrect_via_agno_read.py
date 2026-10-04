def test_truncate_migrated_overlap_does_not_resurrect_via_agno_read(restore_env):
    """#1716 mixed-state B: official table+blob overlap must not resurrect tail."""
    env = restore_env
    db = env.db
    overlap = ["r0", "r1", "r2"]
    other = ["other-0"]
    # Official v3 migration shape: runs copied into table, legacy blob retained.
    db.conn.execute("DROP TABLE IF EXISTS agno_runs")
    db.conn.execute("DROP TABLE IF EXISTS agno_sessions")
    db.conn.execute(
        "CREATE TABLE agno_sessions ("
        "session_id TEXT PRIMARY KEY, session_type TEXT NOT NULL, "
        "agent_id TEXT, team_id TEXT, workflow_id TEXT, user_id TEXT, "
        "session_data TEXT, agent_data TEXT, team_data TEXT, workflow_data TEXT, "
        "metadata TEXT, summary TEXT, runs TEXT, "
        "created_at INTEGER NOT NULL, updated_at INTEGER)"
    )
    _ensure_agno_runs_table(db)
    for sid, ids in (("sess", overlap), ("other", other)):
        db.conn.execute(
            "INSERT INTO agno_sessions "
            "(session_id, session_type, runs, created_at, updated_at) "
            "VALUES (?, 'agent', ?, 1, 1)",
            (sid, json.dumps([{"run_id": rid} for rid in ids])),
        )
        for i, rid in enumerate(ids):
            db.conn.execute(
                "INSERT INTO agno_runs "
                "(run_id, session_id, run_type, status, run_index, run_data, created_at) "
                "VALUES (?, ?, 'agent', 'COMPLETED', ?, ?, ?)",
                (rid, sid, i, json.dumps({"run_id": rid}), i + 1),
            )
    db.conn.commit()

    assert db.agno_runs_length("sess") == 3
    db._truncate_agno_runs_in_tx("sess", 2)
    db.conn.commit()
    assert db.agno_runs_length("sess") == 2
    assert db.agno_runs_length("other") == 1

    assert _agno_public_run_ids(env.path, "sess") == ["r0", "r1"]
    assert _agno_public_run_ids(env.path, "other") == ["other-0"]
