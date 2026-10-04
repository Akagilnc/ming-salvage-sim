def test_advance_schedules_mechanical_tail_after_front_month_advance(game, monkeypatch):
    """提交到受管后台票；前台推进后尾状态先 pending，延期执行后变 done。"""
    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    def silent_brew(_session, **_kwargs):
        return {"selected": 0, "brewed": [], "degraded": [], "skipped_events": 0}

    # 外部边界：挡真实酿制 LLM；不断言私有 brew 调用形状。
    monkeypatch.setattr("ming_sim.mechanical_tail._run_relation_brew", silent_brew)
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()

    executor = _install_deferred(monkeypatch)
    try:
        result = session.resolve_turn(allow_empty_decree=True)
        assert result.advanced is True
        assert int(state.turn) == closed_turn + 1
        assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "pending"
    finally:
        if hasattr(executor, "fn"):
            _run_deferred(executor)
    assert get_session_write_queue(session).wait_idle(timeout_s=1)
    assert month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"] == "done"
