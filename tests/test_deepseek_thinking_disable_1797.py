"""#1797：DeepSeek 全系按模型 id 关思考；llm_dump 记 reasoning/usage/finish_reason。

真实入口 create_chat_model / _dump_llm_messages；不跑真实 LLM。
"""

from __future__ import annotations

from types import SimpleNamespace

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


def test_dump_llm_messages_records_reasoning_usage_finish_reason(monkeypatch, tmp_path):
    """dump 三样均落盘：reasoning 正文 / usage.reasoning_tokens / finish_reason（键值同断）。

    finish_reason 只读 model_provider_data / message.provider_data 字面键；
    生产形（两容器皆无该键）据实为 null；有值夹具只种实有字段。
    验收读结构化记录字段，不锁 JSON 空格/键序等编码呈现。
    """
    import ming_sim.agents as agents_mod

    import json

    dump_path = tmp_path / "llm_dump_test.jsonl"
    monkeypatch.setattr(agents_mod, "_DUMP_LLM", True)
    monkeypatch.setattr(agents_mod, "_DUMP_PATH", str(dump_path))

    def _last_record() -> dict:
        lines = [ln for ln in dump_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines, "dump 应至少落一条 JSONL 记录"
        return json.loads(lines[-1])

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

    # 生产形缺席：agno 不写 finish_reason 进实有容器 → null
    agents_mod._dump_llm_messages(
        SimpleNamespace(
            messages=[msg],
            reasoning_content=None,
            metrics=metrics,
            model_provider_data=None,
        ),
        "test-tag",
    )
    record = _last_record()
    assert record["tag"] == "test-tag"
    assert record["messages"][0]["content"] == msg.content
    assert record["messages"][0]["reasoning_content"] == msg.reasoning_content
    assert record["messages"][0]["reasoning"] == msg.reasoning
    usage = record["usage"]
    assert usage is not None
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20
    assert usage["total_tokens"] == 120
    assert usage["reasoning_tokens"] == 42
    assert record["finish_reason"] is None

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
    assert _last_record()["finish_reason"] == "stop"

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
    assert _last_record()["finish_reason"] == "length"
