def test_cli_backend_active_total_on_unsupported_runner(monkeypatch):
    # ship-pre CMR Group F：不支持的 runner 不该让守卫崩（应判 not-active，不抛 RuntimeError）。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False
