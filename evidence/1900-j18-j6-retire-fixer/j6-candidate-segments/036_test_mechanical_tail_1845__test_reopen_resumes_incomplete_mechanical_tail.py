def test_reopen_resumes_incomplete_mechanical_tail(game, monkeypatch):
    """崩溃后只留 DB 未完标记时，同过月入口续接，不因重开跳过或重复执行。"""
    db, state, content = game
    closed_turn = int(state.turn)
    closed_year, closed_period = int(state.year), int(state.period)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    from ming_sim.mechanical_tail import ensure_mechanical_tails

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()

    def silent_brew(_session, **_kwargs):
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", silent_brew,
    )
    executor = _install_deferred(monkeypatch)
    try:
        assert session.resolve_turn(allow_empty_decree=True).advanced is True
    finally:
        if hasattr(executor, "fn"):
            _run_deferred(executor)
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"

    # 模拟进程退出后只剩 DB pending、写队列票已失
    chain = month_chain._load_chain(db, closed_turn)
    chain["mechanical_tail"] = {
        "status": "pending",
        "settled_year": closed_year,
        "settled_period": closed_period,
        "ending_outcome": None,
    }
    month_chain._save_chain(db, closed_turn, chain, source=Provenance.system_simulation)
    try:
        ensure_mechanical_tails(session)
    finally:
        if not executor.future.done():
            _run_deferred(executor)
    get_session_write_queue(session).wait_idle(timeout_s=5)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
