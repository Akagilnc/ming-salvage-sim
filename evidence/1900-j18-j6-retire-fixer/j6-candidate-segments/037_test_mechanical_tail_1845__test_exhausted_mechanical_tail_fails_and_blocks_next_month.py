def test_exhausted_mechanical_tail_fails_and_blocks_next_month(game, monkeypatch):
    """模型耗尽须留下失败凭据并阻断下次过月。"""
    from ming_sim.exceptions import LLMUnavailable

    db, state, content = game
    closed_turn = int(state.turn)
    _forbid_extractor(monkeypatch)
    _archive_and_stub_world(db, state, monkeypatch)

    def boom(*_a, **_k):
        raise LLMUnavailable("酿制耗尽", stage="relation-brew")

    monkeypatch.setattr(
        "ming_sim.mechanical_tail._run_relation_brew", boom,
    )
    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.agno_db = object()
    executor = _install_deferred(monkeypatch)

    try:
        assert session.resolve_turn(allow_empty_decree=True).advanced is True
    finally:
        if hasattr(executor, "fn"):
            with pytest.raises(LLMUnavailable):
                _run_deferred(executor)
    assert get_session_write_queue(session).wait_idle(timeout_s=5)
    status = month_chain._load_chain(db, closed_turn)["mechanical_tail"]["status"]
    assert status == "failed"

    db.save_turn_report(state, "下月邸报")
    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort):
        session.resolve_turn(allow_empty_decree=True)
