"""#1797：DeepSeek 全系按模型 id 关思考；llm_dump 记 reasoning/usage/finish_reason。

真实入口 create_chat_model / _dump_llm_messages；不跑真实 LLM。
"""

from __future__ import annotations


import pytest

from ming_sim.llm_model import create_chat_model
from ming_sim.models import LLMConfig


def test_create_chat_model_deepseek_on_hermes_emits_reasoning_disable(monkeypatch):
    """DeepSeek 系 + 非端点特化中转（如 hermes/Nous）→ reasoning.enabled=false。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="http://127.0.0.1:8645/v1",
        model="deepseek/deepseek-v4-flash-0731",
        channel="api",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"reasoning": {"enabled": False}}


def test_create_chat_model_deepseek_on_official_keeps_thinking_disabled(monkeypatch):
    """DeepSeek 系 + 官方 deepseek.com → 既有 thinking.disabled。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash-0731",
        channel="api",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_create_chat_model_deepseek_on_dashscope_uses_enable_thinking(monkeypatch):
    """DeepSeek 系（含 deepseek/ 前缀）× dashscope → 端点既有键 enable_thinking:false。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="deepseek/deepseek-v4-flash-0731",
        channel="api",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"enable_thinking": False}


def test_create_chat_model_deepseek_on_minimax_uses_endpoint_key(monkeypatch):
    """DeepSeek 系 × minimax → 端点既有键 thinking.disabled。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.minimaxi.com/v1",
        model="deepseek-v4-flash-0731",
        channel="api",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_create_chat_model_non_deepseek_on_relay_unchanged(monkeypatch):
    """非 DeepSeek 模型 + 中转 base_url → 与现状一致（无 extra_body）。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="http://127.0.0.1:8645/v1",
        model="gpt-5.5",
        channel="api",
    )
    model = create_chat_model(cfg)
    assert model.extra_body is None


# v7 1b：DeepSeek 系 × low/medium/high × 四类端点仍发关闭键；非 DeepSeek 既有强度语义不动。
_DEEPSEEK_DISABLE_BY_ENDPOINT = (
    ("https://api.deepseek.com/v1", "deepseek-v4-flash-0731", {"thinking": {"type": "disabled"}}),
    ("http://127.0.0.1:8645/v1", "deepseek/deepseek-v4-flash-0731", {"reasoning": {"enabled": False}}),
    (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "deepseek/deepseek-v4-flash-0731",
        {"enable_thinking": False},
    ),
    (
        "https://api.minimaxi.com/v1",
        "deepseek-v4-flash-0731",
        {"thinking": {"type": "disabled"}},
    ),
)


@pytest.mark.parametrize("strength", ("low", "medium", "high"))
@pytest.mark.parametrize("base_url,model_id,expected", _DEEPSEEK_DISABLE_BY_ENDPOINT)
def test_create_chat_model_deepseek_strength_still_disables(
    monkeypatch, strength, base_url, model_id, expected
):
    """DeepSeek 系 × reasoning_strength=low/med/high × 四端点 → 仍发该端点关闭键。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url=base_url,
        model=model_id,
        channel="api",
        reasoning_strength=strength,
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == expected


def test_create_chat_model_deepseek_enable_thinking_still_disables(monkeypatch):
    """DeepSeek 系 × enable_thinking=True 亦不得清掉关闭键（含官方/中转）。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    official = create_chat_model(
        LLMConfig(
            api_key="sk-test",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash-0731",
            channel="api",
        ),
        enable_thinking=True,
    )
    assert official.extra_body == {"thinking": {"type": "disabled"}}
    relay = create_chat_model(
        LLMConfig(
            api_key="sk-test",
            base_url="http://127.0.0.1:8645/v1",
            model="deepseek/deepseek-v4-flash-0731",
            channel="api",
        ),
        enable_thinking=True,
    )
    assert relay.extra_body == {"reasoning": {"enabled": False}}


def test_create_chat_model_non_deepseek_dashscope_strength_unchanged(monkeypatch):
    """非 DeepSeek × dashscope × medium → 既有开思考 + budget（本片不得改坏）。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        channel="api",
        reasoning_strength="medium",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"enable_thinking": True, "thinking_budget": 10000}


def test_create_chat_model_non_deepseek_minimax_strength_unchanged(monkeypatch):
    """非 DeepSeek × minimax × medium → 既有 adaptive（本片不得改坏）。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.minimaxi.com/v1",
        model="minimax-test",
        channel="api",
        reasoning_strength="medium",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"thinking": {"type": "adaptive"}, "reasoning_split": True}
