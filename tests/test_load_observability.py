"""#84 接档观测性：CLI 通道日志显示真实 runner/model（非 API-fallback 占位 cfg.model）。

`[simulator] 使用模型 gpt-4o-mini` 这类是 CLI 通道下 cfg.model 的 API-fallback 占位，真实走
codex spark——误导排查。describe_effective_model 与 create_chat_model 的后端解析同口径解真实 runner/model
（legacy-env 默认模型下比 trace 的未解析 id 更准，见源 docstring）。
"""
from __future__ import annotations

from ming_sim.cli_backend import describe_effective_model
from ming_sim.models import LLMConfig


def test_cli_shows_real_runner_and_model():
    cli = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback",
                    channel="cli", cli_runner="codex", cli_model="gpt-5.3-codex-spark")
    assert describe_effective_model(cli) == "codex/gpt-5.3-codex-spark"
    assert "api-fallback" not in describe_effective_model(cli)


def test_cli_resolves_default_model_when_blank(monkeypatch):
    monkeypatch.delenv("MING_SIM_CODEX_MODEL", raising=False)
    cli = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback",
                    channel="cli", cli_runner="codex")  # 无 cli_model → 解析 codex 默认
    label = describe_effective_model(cli)
    assert label.startswith("codex/")
    assert "api-fallback" not in label  # 绝不回落到占位 model


def test_api_channel_uses_model():
    api = LLMConfig(api_key="sk", base_url="https://x/v1", model="gpt-x", channel="api")
    assert describe_effective_model(api) == "gpt-x"


def test_agy_runner_no_misleading_model_suffix():
    """agy 不消费 --model（走自身 Gemini ladder），即便挂了 cli_model 也只显示 'agy'，不误导（#84 codex）。"""
    agy = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback",
                    channel="cli", cli_runner="agy", cli_model="不该显示的model")
    assert describe_effective_model(agy) == "agy"


def test_legacy_env_shows_real_runner(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    cfg = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback", channel="")
    label = describe_effective_model(cfg)
    assert label.startswith("codex/")
    assert "api-fallback" not in label
