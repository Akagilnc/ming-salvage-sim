def test_answering_world_question_resumes_suffix_then_gazette(game, monkeypatch):
    """真实 continue_world_after_answers：只打 LLM 外缝，续推闸与清问须落库可见。"""
    db, state, content = game
    closed_turn = int(state.turn)
    continuation_calls = []
    dispatched_segments = []

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: _WORLD_WITH_QUESTION,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )

    def fake_continuation(session, chain, answers):
        continuation_calls.append(list(answers))
        return "准调关宁，关宁增戍。"

    real_dispatch = month_translate.dispatch_month_segment

    def spy_dispatch(db_, state_, *, segment, llm_config, source, alongside=None):
        dispatched_segments.append(str(segment))
        return real_dispatch(
            db_, state_, segment=segment, llm_config=llm_config,
            source=source, alongside=alongside,
        )

    monkeypatch.setattr(month_chain, "_run_world_continuation_text", fake_continuation)
    monkeypatch.setattr(month_translate, "dispatch_month_segment", spy_dispatch)

    session = make_light_session(db, state, content)
    session.llm_config = object()
    session.resolve_turn(allow_empty_decree=True)
    desk_row = session.pending_decisions()[0]
    choice = desk_row["options"][0]

    session.submit_hitl_choices(
        [{
            "decision_key": desk_row["decision_key"],
            "label": choice["label"],
            "hint": choice.get("hint") or "",
        }],
        write_gate=session._write_gate,
    )

    assert continuation_calls and continuation_calls[0][0]["label"] == choice["label"]
    assert any("关宁增戍" in seg for seg in dispatched_segments)
    assert session.state.turn_phase == TurnPhase.SETTLING.value
    chain = month_chain._load_chain(db, closed_turn)
    assert chain.get("world_questions") in (None, [], ())
    assert chain.get("world_continued") is True

    again = session.resolve_turn(allow_empty_decree=True)
    assert again.stage == "gazette"
    assert again.awaiting is False
    # 同回合重入不得再烧续推。
    assert len(continuation_calls) == 1
