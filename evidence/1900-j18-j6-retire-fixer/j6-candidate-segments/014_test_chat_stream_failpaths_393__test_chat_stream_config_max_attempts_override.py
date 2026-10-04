def test_chat_stream_config_max_attempts_override(monkeypatch, tmp_path, game):
    """#1465 ①：runtime transport 改次数 → 真实召对入口行为随之变。"""
    from ming_sim import llm_config as llm_config_mod

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "cli": {"timeout_seconds": 30},
        "transport": {
            "max_attempts": 1,
            "attempt_timeout_seconds": 30,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))

    def _conn_err(_n):
        return LLMUnavailable(
            "连接失败",
            code="llm_connection_error",
            provider_message="connection reset",
        )

    agent = _CountingFailAgent(fail_times=99, error_factory=_conn_err)
    web_game, minister = _transport_web_game(game, agent, monkeypatch)
    web_game.session.llm_config = SimpleNamespace(channel="api")

    response = _post_chat_stream(monkeypatch, web_game, minister)
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    detail = events[-1][1]
    assert agent.calls == 1
    assert detail.get("code") == "llm_connection_error"
    assert len(detail.get("transport_attempts") or []) == 1
