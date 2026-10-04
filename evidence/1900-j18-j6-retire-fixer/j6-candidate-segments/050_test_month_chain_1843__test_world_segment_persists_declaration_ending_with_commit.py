def test_world_segment_persists_declaration_ending_with_commit(game, monkeypatch):
    db, state, content = game
    from ming_sim.applier import Provenance

    monkeypatch.setattr(
        month_translate, "translate_month_segment",
        lambda *_a, **_k: {"effects": {"emperor_fate": "suicide"}},
    )
    chain = {"world_text_ready": True, "world_text": "世界段"}
    session = make_light_session(db, state, content)

    outcome = month_chain._run_world_segment(
        session, chain, source=Provenance.system_simulation,
    )

    assert outcome["status"] == "emperor_suicide"
    assert chain["declaration_outcome"] == outcome
    payload = db.get_resolve_context(int(state.turn))["simulator_payload"]
    assert payload["month_chain"]["declaration_outcome"] == outcome
