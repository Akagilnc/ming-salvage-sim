def test_runtime_llm_transport_nonpositive_falls_back_to_defaults(tmp_path, monkeypatch):
    """#1465 fo2Nb / #1792：预算非正数（0/负）回落 typed 默认，不进空 range/即死预算。

    静默判死阈值同理，且它的真源是设置页那一格（cli.timeout_seconds）——坏值回落
    CLI_DEFAULT_TIMEOUT_SECONDS。
    """
    from ming_sim.llm_transport import transport_policy_from_mapping
    from ming_sim.models import (
        CLI_DEFAULT_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_MAX_ATTEMPTS,
        TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS,
    )

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "cli",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": 0},
        "transport": {
            "max_attempts": 0,
            "attempt_timeout_seconds": -1,
            "retry_interval_seconds": 0,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert out["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert out["transport"]["retry_interval_seconds"] == TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
    policy = transport_policy_from_mapping(out)
    assert policy.max_attempts == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert policy.attempt_timeout_seconds == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert policy.retry_interval_seconds == TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
    assert policy.idle_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS
    # 保存路径同样经单权威：显式 0 不得落盘为 0
    llm_config.save_runtime_llm(
        base_url="https://x/v1",
        model="m",
        api_key="sk-x",
        channel="api",
        transport_max_attempts=0,
        transport_attempt_timeout_seconds=0.0,
        transport_retry_interval_seconds=0.0,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert saved["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert saved["transport"]["retry_interval_seconds"] == TRANSPORT_DEFAULT_RETRY_INTERVAL_SECONDS
