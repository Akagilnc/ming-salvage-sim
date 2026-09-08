"""#1797：DeepSeek 全系按模型 id 关思考；llm_dump 记 reasoning/usage。

真实入口 create_chat_model / _dump_llm_messages；不跑真实 LLM。
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim.llm_model import create_chat_model
from ming_sim.models import LLMConfig


def test_create_chat_model_deepseek_on_hermes_emits_reasoning_disable(monkeypatch):
    """DeepSeek 系 + 非官方 base_url → reasoning.enabled=false。"""
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


def test_dump_llm_messages_records_reasoning_body_and_usage_tokens(monkeypatch, tmp_path):
    """dump 落盘含 reasoning 正文与 usage.reasoning_tokens（不锁标签句式）。"""
    import ming_sim.agents as agents_mod

    dump_path = tmp_path / "llm_dump_test.log"
    monkeypatch.setattr(agents_mod, "_DUMP_LLM", True)
    monkeypatch.setattr(agents_mod, "_DUMP_PATH", str(dump_path))

    msg = SimpleNamespace(
        role="assistant",
        content="可见正文",
        reasoning_content="思考过程甲",
        reasoning="中转 reasoning 正文",
        reasoning_details=None,
        tool_calls=None,
    )
    metrics = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        reasoning_tokens=42,
    )
    output = SimpleNamespace(
        messages=[msg],
        reasoning_content=None,
        metrics=metrics,
    )

    agents_mod._dump_llm_messages(output, "test-tag")

    text = dump_path.read_text(encoding="utf-8")
    assert "思考过程甲" in text
    assert "中转 reasoning 正文" in text
    assert '"reasoning_tokens": 42' in text
