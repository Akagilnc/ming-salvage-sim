def test_step_4a_no_eligible_objects_skips_run_and_completes(game, monkeypatch):
    """步骤 4a：无合资格长差案卷且无在办密令时，不为凑调用而起 run。"""
    db, state, content = game
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}})

    def forbidden_supply(*a, **k):
        raise AssertionError("没有合资格对象时不应调用整月供料 run")

    monkeypatch.setattr(month_chain, "run_secret_orders_supply", forbidden_supply)
    session = make_light_session(db, state, content)

    result = session.resolve_turn(allow_empty_decree=True)

    assert result.stage == "gazette"
    chain = month_chain._load_chain(db, int(state.turn))
    assert chain.get("secret_orders_supply_done") is True
