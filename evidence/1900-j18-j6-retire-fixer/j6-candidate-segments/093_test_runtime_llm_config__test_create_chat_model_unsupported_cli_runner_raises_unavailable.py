def test_create_chat_model_unsupported_cli_runner_raises_unavailable(monkeypatch):
    # ship-pre CMR round-3：显式不支持的 CLI runner 在构造期优雅抛 LLMUnavailable，
    # 而非返回 CliChat、等首次 invoke 才 raw RuntimeError。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    import pytest as _pytest
    from ming_sim.llm_model import create_chat_model
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="x", channel="cli", cli_runner="bogus")

    with _pytest.raises(LLMUnavailable):
        create_chat_model(cfg)
