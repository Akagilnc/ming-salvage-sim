from __future__ import annotations

import web_app
from ming_sim.models import LLMConfig


def test_runtime_cli_slot_builds_cli_llm_config_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    runtime = {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
    }

    cfg = web_app._llm_config_from_runtime(
        runtime,
        base_url="https://api.example.com/v1",
        model="gpt-api",
        api_key="",
        max_tokens=8000,
        timeout_seconds=180,
        thinking_level="",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )

    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "gpt-5.5"
    assert cfg.cli_timeout_seconds == 240
    assert cfg.api_key == "cli-backend"


def test_advanced_llm_verification_preserves_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    monkeypatch.setattr(web_app, "verify_llm_available", lambda cfg: seen.append(cfg))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        advanced_model="gpt-advanced",
        channel="api",
    )

    web_app._verify_llm_configs_or_raise(cfg)

    assert [item.channel for item in seen] == ["api", "api"]
