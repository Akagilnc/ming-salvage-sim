"""#1797：DeepSeek 全系按模型 id 关思考；llm_dump 记 reasoning/usage/finish_reason。

真实入口 create_chat_model / _dump_llm_messages；不跑真实 LLM。
"""

from __future__ import annotations

from types import SimpleNamespace

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


def test_dump_llm_messages_records_reasoning_usage_finish_reason(monkeypatch, tmp_path):
    """dump 三样均落盘：reasoning 正文 / usage.reasoning_tokens / finish_reason（键值同断）。

    finish_reason 只读 model_provider_data / message.provider_data 字面键；
    生产形（两容器皆无该键）据实记 (缺)；有值夹具只种实有字段。
    """
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
        provider_data=None,
    )
    metrics = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        reasoning_tokens=42,
    )

    # 生产形缺席：agno 不写 finish_reason 进实有容器 → 记缺
    agents_mod._dump_llm_messages(
        SimpleNamespace(
            messages=[msg],
            reasoning_content=None,
            metrics=metrics,
            model_provider_data=None,
        ),
        "test-tag",
    )
    text = dump_path.read_text(encoding="utf-8")
    # reasoning：字段正文（不锁 dump 字数/标签模板）
    assert "思考过程甲" in text
    assert "中转 reasoning 正文" in text
    # usage / finish_reason：键值同断
    assert '"reasoning_tokens": 42' in text
    assert "[finish_reason] (缺)" in text

    # 有值演练：只种 RunOutput.model_provider_data 字面键（bounce 明示允许）
    dump_path.write_text("", encoding="utf-8")
    agents_mod._dump_llm_messages(
        SimpleNamespace(
            messages=[msg],
            reasoning_content=None,
            metrics=metrics,
            model_provider_data={"finish_reason": "stop"},
        ),
        "test-tag-mpd",
    )
    assert "[finish_reason] stop" in dump_path.read_text(encoding="utf-8")

    # 有值演练：只种 Message.provider_data 字面键
    dump_path.write_text("", encoding="utf-8")
    agents_mod._dump_llm_messages(
        SimpleNamespace(
            messages=[
                SimpleNamespace(
                    role="assistant",
                    content="x",
                    reasoning_content=None,
                    reasoning=None,
                    reasoning_details=None,
                    tool_calls=None,
                    provider_data={"finish_reason": "length"},
                )
            ],
            reasoning_content=None,
            metrics=metrics,
            model_provider_data=None,
        ),
        "test-tag-pd",
    )
    assert "[finish_reason] length" in dump_path.read_text(encoding="utf-8")
