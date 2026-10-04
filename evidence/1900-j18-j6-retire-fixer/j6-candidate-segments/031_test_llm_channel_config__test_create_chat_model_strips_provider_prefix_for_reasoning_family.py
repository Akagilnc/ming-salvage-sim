def test_create_chat_model_strips_provider_prefix_for_reasoning_family(monkeypatch):
    """#1461：openai/gpt-5.x 带 provider 前缀仍须识别为推理族（剥前缀后判）。"""
    from ming_sim.llm_config import supports_openai_reasoning_effort

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert supports_openai_reasoning_effort("openai/gpt-5.4")
    assert supports_openai_reasoning_effort("openai/o3-mini")
    assert supports_openai_reasoning_effort("openai/o4-mini")
    assert not supports_openai_reasoning_effort("openai/gpt-4o")

    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="openai/o3-mini",
        channel="api",
        reasoning_strength="off",
    )
    model = create_chat_model(cfg)
    assert model.reasoning_effort == "minimal"

    cfg5 = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="openai/gpt-5.4",
        channel="api",
        reasoning_strength="off",
    )
    model5 = create_chat_model(cfg5)
    assert model5.reasoning_effort == "none"
