from __future__ import annotations

import pytest
from agno.models.openai import OpenAIChat

from ming_sim import cli_backend
from ming_sim.cli_backend import CliChat
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_config import for_role, load_llm_config
from ming_sim import llm_model
from ming_sim.llm_model import create_chat_model, verify_llm_available
from ming_sim.models import LLMConfig


def test_create_chat_model_respects_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
    )

    model = create_chat_model(cfg)

    assert isinstance(model, OpenAIChat)
    assert not isinstance(model, CliChat)


def test_create_chat_model_uses_cli_channel_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="",  # CLI 通道 LLMConfig.api_key 永空；占位符在此构造时才注入
        base_url="",
        model="api-fallback-model",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    model = create_chat_model(cfg)

    assert isinstance(model, CliChat)
    assert model.backend == "codex"
    assert model.id == "gpt-5.5"
    assert model.timeout == 240
    # 空 CLI key 也能构造：占位符在构造时注入以满足 OpenAIChat 父类。
    assert model.api_key == "cli-backend"


def test_load_llm_config_records_backend_env_as_cli_channel(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setenv("MING_SIM_CODEX_MODEL", "gpt-codex-test")

    cfg = load_llm_config("https://api.example.com", "api-fallback", api_key="")

    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "gpt-codex-test"
    assert cfg.api_key == ""


def test_loaded_api_config_is_not_rerouted_by_later_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = load_llm_config("https://api.example.com", "gpt-test", api_key="sk-test")

    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    model = create_chat_model(cfg)

    assert cfg.channel == "api"
    assert isinstance(model, OpenAIChat)
    assert not isinstance(model, CliChat)


def test_legacy_backend_env_uses_runner_default_model_not_api_model(monkeypatch):
    captured = {}

    class Proc:
        stdout = "臣领旨。"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cli_backend.subprocess, "run", fake_run)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="deepseek-v4-flash",
    )

    model = create_chat_model(cfg)
    model._call_cli("p")

    assert isinstance(model, CliChat)
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == cli_backend._CODEX_MODEL


def test_verify_llm_available_respects_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["model"] = kwargs["model"]

        def run(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return "ok"

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    monkeypatch.setattr(llm_model, "extract_agent_text", lambda output: output)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
    )

    verify_llm_available(cfg)

    assert captured["prompt"] == "输出 ok"
    assert not isinstance(captured["model"], CliChat)


def test_verify_llm_available_smokes_cli_channel_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    seen = {}

    def fake_run(prompt, llm_config=None):
        seen["prompt"] = prompt
        seen["config"] = llm_config
        return "ok", 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", fake_run)
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    verify_llm_available(cfg)

    assert seen["prompt"] == "输出 ok"
    assert seen["config"] is cfg


def test_verify_llm_available_cli_channel_failure_raises(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def boom(prompt, llm_config=None):
        raise RuntimeError("codex missing")

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", boom)
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    with pytest.raises(LLMUnavailable):
        verify_llm_available(cfg)


def test_for_role_preserves_cli_channel_fields_for_advanced_roles():
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="https://api.example.com/v1",
        model="api-model",
        advanced_model="api-advanced",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    derived = for_role(cfg, "simulator")

    assert derived.channel == "cli"
    assert derived.cli_runner == "codex"
    assert derived.cli_model == "gpt-5.5"
    assert derived.cli_timeout_seconds == 240
