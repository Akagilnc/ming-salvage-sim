def test_gate_evidence_config_omits_max_tokens():
    """#1472：四闸证据块不再写 max_tokens。"""
    from types import SimpleNamespace
    from ming_sim import cli_backend as cb

    args = SimpleNamespace(channel="cli", runner="kimi", model="kimi-k2")
    cfg = cb.gate_llm_config_from_args(args)
    block = cb.gate_evidence_config(args, cfg)
    assert "max_tokens" not in block
