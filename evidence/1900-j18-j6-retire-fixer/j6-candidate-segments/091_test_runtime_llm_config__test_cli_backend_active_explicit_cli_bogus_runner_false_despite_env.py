def test_cli_backend_active_explicit_cli_bogus_runner_false_despite_env(monkeypatch):
    # ship-pre CMR Group F'：显式 channel=cli + 不支持 runner，即便 env 有 agy
    # 也不该误报 active（否则执行期 _run_backend_for_config 仍会崩）。
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False
