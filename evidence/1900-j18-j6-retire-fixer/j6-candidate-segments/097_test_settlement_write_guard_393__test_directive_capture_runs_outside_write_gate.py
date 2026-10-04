def test_directive_capture_runs_outside_write_gate(
    monkeypatch, operation,
):
    """capture 在写闸外执行：闸内可另写；API 可见结果落草案响应。"""
    import ming_sim.cli_backend as cli_backend

    game = _FakeGame(TurnPhase.SUMMONING.value)
    payload = {
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "land-survey",
    }

    captured_context = []

    def capture(text, llm_config, **context):
        captured_context.append(context)
        with web_app._serialized_web_write(game):
            game.db.writes.append("unrelated-write")
        return payload

    game.session.llm_config = SimpleNamespace()
    game.session.add_directive = lambda text, notes, dossier_payload: (
        SimpleNamespace(id=8, text=text, status="draft")
    )
    game.session.update_directive = (
        lambda directive_id, text, dossier_payload: None
    )
    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", capture)
    monkeypatch.setattr(web_app, "get_game", lambda: game)

    if operation == "create":
        body = _invoke(web_app.api_create_directive(
            web_app.DirectiveRequest(text="清丈田亩"),
        ))
        assert body["directive"]["id"] == 8
        assert body["directive"]["text"] == "清丈田亩"
        assert body["directive"]["status"] == "draft"
    else:
        body = _invoke(web_app.api_update_directive(
            7, web_app.DirectivePatch(text="重定清丈田亩"),
        ))
        assert "directives" in body
        assert captured_context[0]["existing_mode"] == "midzhi"
    # 闸契约：capture 期间能完成另一次串行写（证明不在占用写闸时抽取）
    assert game.db.writes == ["unrelated-write"]
