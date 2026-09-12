"""#884 — 点火冒烟装钟 + 主/高级并行 + 阶段名留痕。

编排器已迁仓外；本仓残留接缝 = 设置页连通性 verify（点火冒烟）。
验收：永不响应 → 超时→重试→耗尽，账面有阶段名（正负成对）；主+高级烟互不依赖则并行。
"""

from __future__ import annotations

import threading

import httpx
import pytest
from agno.models.openai import OpenAIChat

import ming_sim.llm_model as llm_model
import web_app
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import verify_llm_available
from ming_sim.models import (
    LLMConfig,
    TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
    TRANSPORT_DEFAULT_MAX_ATTEMPTS,
)


def _api_cfg(**overrides) -> LLMConfig:
    base = dict(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        channel="api",
    )
    base.update(overrides)
    return LLMConfig(**base)


def _timeout_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.example.com/v1/chat/completions")


def _openai_chat_with_mock_transport(handler, calls: dict) -> OpenAIChat:
    """真实 OpenAIChat（含 invoke 包装）；只在底层 http client 注入提供方失败。

    路径：httpx → openai SDK typed 异常 → OpenAIChat.invoke 包 ModelProviderError
    （显式 __cause__）→ transport 捕获还原。禁覆写 invoke / 替换 Agent。
    """

    def counting_handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return handler(request)

    return OpenAIChat(
        id="gpt-main",
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(counting_handler)),
        max_retries=0,
    )


def _patch_openai_chat_provider(monkeypatch, handler, calls: dict) -> None:
    """真实 Agent 留下；create_chat_model 返回带 MockTransport 的真 OpenAIChat。"""
    monkeypatch.setattr(
        llm_model,
        "create_chat_model",
        lambda *_a, **_k: _openai_chat_with_mock_transport(handler, calls),
    )


def test_api_verify_hang_retries_then_exhausts_with_stage(monkeypatch):
    """注入：provider 永不响应（每次 attempt 以超时收场）→ 重试耗尽，账面带阶段名。

    入口 = 真实 verify_llm_available → 真实 agno Agent → 真实 OpenAIChat.invoke；
    只在 http client 抛 ReadTimeout → SDK APITimeoutError → ModelProviderError。
    """
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    calls = {"n": 0}

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    _patch_openai_chat_provider(monkeypatch, hang, calls)
    with pytest.raises(LLMUnavailable) as ei:
        verify_llm_available(_api_cfg())
    err = ei.value
    assert err.code == "llm_timeout"
    assert getattr(err, "stage", None) == "smoke-main"
    attempts = err.transport_attempts or []
    assert len(attempts) == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert [a.get("code") for a in attempts] == ["llm_timeout"] * TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert [a.get("outcome") for a in attempts] == (
        ["retryable_fail"] * (TRANSPORT_DEFAULT_MAX_ATTEMPTS - 1) + ["terminal_fail"]
    )
    assert calls["n"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS


def test_api_verify_401_does_not_retry(monkeypatch):
    """负：确定性 4xx 立即降级，不走瞬断重试。

    入口 = 真实 verify_llm_available → 真实 agno Agent → 真实 OpenAIChat.invoke；
    只在 http client 回 401 → SDK APIStatusError → ModelProviderError。
    """
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    calls = {"n": 0}

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid API key", "code": "invalid_api_key"}},
            request=request,
        )

    _patch_openai_chat_provider(monkeypatch, unauthorized, calls)
    with pytest.raises(LLMUnavailable) as ei:
        verify_llm_available(_api_cfg())
    err = ei.value
    assert err.status_code == 401
    assert err.code == "llm_http_401"
    assert getattr(err, "stage", None) == "smoke-main"
    assert calls["n"] == 1
    attempts = err.transport_attempts or []
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "terminal_fail"
    assert attempts[0].get("status_code") == 401
    assert attempts[0].get("code") == "llm_http_401"


def test_api_verify_installs_sdk_attempt_clock(monkeypatch):
    """API 烟必须把 SDK timeout 绑到 attempt 钟，不得沿用未迁移的 180s 墙。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    seen = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]

        def run(self, prompt: str) -> str:
            seen["timeout"] = getattr(self.model, "timeout", None)
            seen["max_retries"] = getattr(self.model, "max_retries", None)
            return "ok"

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    monkeypatch.setattr(llm_model, "extract_agent_text", lambda output: output)
    verify_llm_available(_api_cfg())
    assert seen["timeout"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert seen["max_retries"] == 0


def test_verify_main_and_advanced_smoke_overlap(monkeypatch):
    """主+高级烟互不依赖：必须并行起跑（串行会在 barrier 上睡死）。"""
    barrier = threading.Barrier(2, timeout=1.0)
    seen: list[LLMConfig] = []

    def fake_verify(cfg, **_kwargs):
        barrier.wait()
        seen.append(cfg)

    monkeypatch.setattr(web_app, "verify_llm_available", fake_verify)
    cfg = _api_cfg(advanced_model="gpt-advanced")
    web_app._verify_llm_configs_or_raise(cfg)
    assert {item.model for item in seen} == {"gpt-main", "gpt-advanced"}


def test_verify_stage_lines_are_attributable(monkeypatch, capsys):
    """每进一阶段打一行，沉默可归因。"""
    monkeypatch.setattr(web_app, "verify_llm_available", lambda cfg, **_k: None)
    web_app._verify_llm_configs_or_raise(_api_cfg(advanced_model="gpt-advanced"))
    out = capsys.readouterr().out
    assert "[llm:stage] smoke-main" in out
    assert "[llm:stage] smoke-advanced" in out


def test_verify_http_detail_carries_stage(monkeypatch):
    """降级出口的 HTTP detail 带阶段名。"""

    def boom(cfg, **_k):
        err = LLMUnavailable(
            "timeout",
            code="llm_timeout",
            transport_attempts=[{"index": 1, "outcome": "terminal_fail", "code": "llm_timeout"}],
        )
        err.stage = "smoke-main"
        raise err

    monkeypatch.setattr(web_app, "verify_llm_available", boom)
    with pytest.raises(web_app.HTTPException) as ei:
        web_app._verify_llm_configs_or_raise(_api_cfg())
    assert ei.value.status_code == 400
    assert ei.value.detail["stage"] == "smoke-main"
    assert ei.value.detail["code"] == "llm_timeout"
