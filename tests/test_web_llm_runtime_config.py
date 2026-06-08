from __future__ import annotations

import asyncio
from types import SimpleNamespace

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


def test_apply_llm_config_saves_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))
    current = LLMConfig(
        api_key="cli-backend",
        base_url="https://old.example.com/v1",
        model="old-model",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-cli",
        cli_timeout_seconds=240,
    )
    fake = SimpleNamespace(
        session=SimpleNamespace(
            llm_config=current,
            begin_turn=lambda: None,
        )
    )

    cfg = web_app.WebGame.apply_llm_config(
        fake,
        "https://api.example.com",
        "gpt-api",
        "sk-test",
        max_tokens=16000,
        timeout_seconds=90,
        thinking_level="medium",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )

    assert cfg.channel == "api"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "gpt-cli"
    assert seen[0].channel == "api"
    assert fake.session.llm_config.channel == "api"
    assert saved


def test_menu_save_llm_validates_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))

    result = asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="https://api.example.com",
        model="gpt-api",
        api_key="sk-test",
        max_tokens=16000,
        timeout_seconds=90,
        thinking_level="medium",
    )))

    assert result["ok"] is True
    assert seen[0].channel == "api"
    assert saved
