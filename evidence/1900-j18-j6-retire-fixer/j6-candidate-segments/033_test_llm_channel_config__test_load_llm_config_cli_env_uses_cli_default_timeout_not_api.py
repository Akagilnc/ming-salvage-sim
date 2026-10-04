def test_load_llm_config_cli_env_uses_cli_default_timeout_not_api(monkeypatch):
    """codex R1 #2：legacy env CLI（MING_SIM_LLM_BACKEND 设）时 cli_timeout_seconds 必须用
    CLI 槽默认（静默判死 60），不沿用 API 的 timeout_seconds（180）。"""
    from ming_sim.llm_config import load_llm_config, CLI_DEFAULT_TIMEOUT_SECONDS
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    cfg = load_llm_config(base_url="", model="m", api_key="", timeout_seconds=180.0)
    assert cfg.channel == "cli"
    assert cfg.cli_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS == 60.0
    assert cfg.cli_timeout_seconds != 180.0
