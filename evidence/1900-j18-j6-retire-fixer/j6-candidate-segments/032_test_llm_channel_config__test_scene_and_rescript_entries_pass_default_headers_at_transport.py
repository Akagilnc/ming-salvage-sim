def test_scene_and_rescript_entries_pass_default_headers_at_transport(monkeypatch, game, tmp_path):
    """#1794：召对/拟诏真实入口 → OpenAIChat 构造缝头表整张到达；不跑真实 LLM。"""
    from ming_sim.agents import bind_content as agents_bind, create_rescript_draft_agent
    from ming_sim.materials import PreparedMaterials
    from ming_sim.registry import create_scene_agent

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    db, state, content = game
    agents_bind(content)

    headers = {
        "X-Custom-Session": "sess-fixed-1",
        "User-Agent": "ming-qa/1.0",
    }
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
        default_headers=headers,
    )

    captured: list = []
    real = llm_model.OpenAIChat

    def spy(*args, **kwargs):
        captured.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(llm_model, "OpenAIChat", spy)

    create_scene_agent(
        cfg, PreparedMaterials(root=tmp_path, opening="", index_lines=()),
        content=content,
    )
    assert captured, "召对入口须构造 OpenAIChat"
    assert captured[-1].get("default_headers") == headers

    before = len(captured)
    create_rescript_draft_agent(cfg, db)
    assert len(captured) == before + 1, "拟诏入口须再构造一次 OpenAIChat"
    assert captured[-1].get("default_headers") == headers
