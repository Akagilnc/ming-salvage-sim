"""#1797：DeepSeek 全系按模型 id 关思考；llm_dump 记 reasoning/usage。

聚焦 subprocess 单测，不跑真实 LLM。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ming_sim.llm_config import is_deepseek_model, provider_extra_body
from ming_sim.llm_model import create_chat_model
from ming_sim.models import LLMConfig


def test_is_deepseek_model_recognizes_family_and_prefix():
    assert is_deepseek_model("deepseek-v4-flash-0731") is True
    assert is_deepseek_model("deepseek/deepseek-v4-flash-0731") is True
    assert is_deepseek_model("DeepSeek-V3") is True
    assert is_deepseek_model("nous/deepseek-chat") is True
    assert is_deepseek_model("gpt-5.5") is False
    assert is_deepseek_model("qwen-plus") is False
    assert is_deepseek_model("") is False


def test_provider_extra_body_deepseek_model_on_relay_emits_reasoning_disable():
    """非官方 base_url + DeepSeek 系模型 → 关思考键（runner 实测 reasoning.enabled=false）。"""
    body = provider_extra_body(
        "http://127.0.0.1:8645/v1",
        "deepseek/deepseek-v4-flash-0731",
    )
    assert body == {"reasoning": {"enabled": False}}


def test_provider_extra_body_deepseek_model_on_official_keeps_thinking_disabled():
    """官方 deepseek.com + DeepSeek 模型 → 既有 thinking.disabled。"""
    body = provider_extra_body(
        "https://api.deepseek.com/v1",
        "deepseek-v4-flash-0731",
    )
    assert body == {"thinking": {"type": "disabled"}}


def test_provider_extra_body_non_deepseek_unchanged_on_relay():
    """非 DeepSeek 模型 + 中转 base_url → 与现状一致（不发关闭键）。"""
    assert provider_extra_body("http://127.0.0.1:8645/v1", "gpt-5.5") is None
    assert provider_extra_body("https://api.example.com/v1", "qwen-plus") is None


def test_provider_extra_body_dashscope_and_minimax_unchanged():
    assert provider_extra_body(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
    ) == {"enable_thinking": False}
    assert provider_extra_body(
        "https://api.minimaxi.com/v1",
        "minimax-test",
    ) == {"thinking": {"type": "disabled"}}


def test_create_chat_model_deepseek_on_hermes_extra_body(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="http://127.0.0.1:8645/v1",
        model="deepseek/deepseek-v4-flash-0731",
        channel="api",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"reasoning": {"enabled": False}}


def test_create_chat_model_deepseek_on_official_extra_body(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        channel="api",
    )
    model = create_chat_model(cfg, enable_thinking=False)
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_create_chat_model_non_deepseek_on_relay_no_extra(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="http://127.0.0.1:8645/v1",
        model="gpt-5.5",
        channel="api",
    )
    model = create_chat_model(cfg)
    assert model.extra_body is None


def test_dump_llm_messages_records_reasoning_and_usage(monkeypatch, tmp_path):
    """dump 记 reasoning 类字段（长度+正文）与 usage（含 reasoning_tokens）。"""
    import ming_sim.agents as agents_mod

    dump_path = tmp_path / "llm_dump_test.log"
    monkeypatch.setattr(agents_mod, "_DUMP_LLM", True)
    monkeypatch.setattr(agents_mod, "_DUMP_PATH", str(dump_path))

    msg = SimpleNamespace(
        role="assistant",
        content="可见正文",
        reasoning_content="思考过程甲",
        reasoning=None,
        reasoning_details=None,
        tool_calls=None,
        metrics=None,
        provider_data=None,
    )
    # provider 原始结构偶发落在 provider_data
    msg_raw = SimpleNamespace(
        role="assistant",
        content="",
        reasoning_content=None,
        reasoning=None,
        reasoning_details=None,
        tool_calls=None,
        metrics=None,
        provider_data={"reasoning": "中转商 reasoning 正文", "reasoning_details": [{"type": "reasoning.text", "text": "细节"}]},
    )
    metrics = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        reasoning_tokens=0,
        cache_read_tokens=50,
        cache_write_tokens=0,
        cost=0.001,
        completion_tokens_details=None,
        prompt_tokens=None,
        completion_tokens=None,
    )
    output = SimpleNamespace(
        messages=[msg, msg_raw],
        reasoning_content="run 级 reasoning",
        metrics=metrics,
    )

    agents_mod._dump_llm_messages(output, "test-tag")

    text = dump_path.read_text(encoding="utf-8")
    assert "role=assistant" in text
    assert "可见正文" in text
    assert "[reasoning_content]" in text
    assert "思考过程甲" in text
    assert "中转商 reasoning 正文" in text
    assert "reasoning_tokens" in text
    assert "run 级 reasoning" in text or "[run.reasoning_content]" in text
