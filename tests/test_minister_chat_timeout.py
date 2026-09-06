"""Minister chat uses a short timeout (≤ MINISTER_CHAT_CLI_TIMEOUT_SECONDS),
decoupled from settlement's long timeout (issue #353).

#1185: observe short-timeout failure via public model.invoke. Boundary stubs
only time out when the forwarded timeout is short (≤ cap); missing/long values
succeed immediately — production that stops forwarding the short timeout goes red.
No sleep, real network, or real LLM.

#1465 切片③：CLI 侧该槽位仍按 90 封顶（ADR 0001 槽位保留），但**不再当子进程总墙钟**
——不得再拿它 SIGKILL 正在出字的 CLI；CLI 空转预算归 transport 策略。API 侧不变。
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.exceptions import ModelProviderError

from ming_sim.cli_backend import CliChat
from ming_sim.models import CLI_DEFAULT_TIMEOUT_SECONDS, MINISTER_CHAT_CLI_TIMEOUT_SECONDS, LLMConfig
from ming_sim.registry import create_minister_agent
import ming_sim.cli_backend as cli_backend


def _cfg_settlement_timeout(*, channel: str = "cli") -> LLMConfig:
    if channel == "cli":
        return LLMConfig(
            api_key="",
            base_url="",
            model="gpt-5.5",
            channel="cli",
            cli_runner="codex",
            cli_model="gpt-5.5",
            cli_timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
            timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
        )
    return LLMConfig(
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="gpt-4",
        channel="api",
        timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
    )


def _make_context() -> MagicMock:
    state = MagicMock(year=1640, period=1, turn=1)
    db_mock = MagicMock()
    db_mock.get_consort_traits.return_value = {"extra_skills": [], "extra_traits": []}
    db_mock.conn.execute.return_value.fetchone.return_value = [0]
    db_mock.get_character_status.return_value = ("active", "在朝")
    db_mock.resolve_power_id.return_value = "ming"
    db_mock.army_roster.return_value = ""
    ctx = MagicMock()
    ctx.state = state
    ctx.db = db_mock
    ctx.game_world_prompt = ""
    ctx.minister_agent_prompt = ""
    ctx.consort_agent_prompt = ""
    ctx.characters = {}
    return ctx


def _make_character() -> MagicMock:
    ch = MagicMock()
    ch.name = "测试大臣"
    ch.office = "内阁"
    ch.office_type = "cabinet"
    ch.personal_skills = ["谋略"]
    ch.style = "周正"
    ch.summary = "测试"
    ch.power_id = "ming"
    return ch


_REGISTRY_STUBS = [
    ("ming_sim.registry.build_character_knowledge_brief", ""),
    ("ming_sim.registry.build_recommendation_brief", ""),
    ("ming_sim.registry.build_secret_order_brief", ""),
    ("ming_sim.registry.build_minister_tools", []),
    ("ming_sim.registry._skills_for", MagicMock()),
    ("ming_sim.registry.character_context_with_db", "角色描述"),
]


@contextmanager
def _minister_agent_construction(ctx):
    """Stub registry side seams; keep real create_chat_model so timeout is live."""
    with ExitStack() as stack:
        for name, val in _REGISTRY_STUBS:
            stack.enter_context(patch(name, return_value=val))
        stack.enter_context(
            patch(
                "ming_sim.registry.Agent",
                side_effect=lambda **kwargs: MagicMock(model=kwargs.get("model")),
            )
        )
        stack.enter_context(patch("ming_sim.registry._ctx", return_value=ctx))
        yield


def _invoke_minister_model(model) -> None:
    model.invoke(
        [Message(role="user", content="召对")],
        Message(role="assistant"),
    )


def _install_cli_process_boundary(monkeypatch) -> dict:
    """CLI 子进程边界替身（生产 Popen + 增量读）；记录 Popen kwargs 供墙钟断言。"""
    from tests.cli_process_doubles import FakeCliProcess

    captured: dict = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = list(cmd)
        captured["kw"] = kw
        return FakeCliProcess(cmd, stdout_script=("大臣回话\n",), returncode=0,
                              popen_kwargs=kw)

    monkeypatch.setattr(cli_backend.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli_backend, "_resolve_cli_bin", lambda name, configured: f"/fake/{name}")
    monkeypatch.setattr(cli_backend, "_trace", lambda rec: None)
    return captured


def _short_timeout_values(timeout_ext) -> list[float]:
    if not timeout_ext:
        return []
    values: list[float] = []
    if isinstance(timeout_ext, dict):
        for key in ("read", "connect"):
            raw = timeout_ext.get(key)
            if raw is not None:
                values.append(float(raw))
    else:
        for key in ("read", "connect"):
            raw = getattr(timeout_ext, key, None)
            if raw is not None:
                values.append(float(raw))
    return values


def _api_timeout_transport() -> httpx.MockTransport:
    """Boundary stand-in: ReadTimeout only when request timeout extension is short."""

    def handler(request: httpx.Request) -> httpx.Response:
        ext = request.extensions.get("timeout")
        short = any(v <= MINISTER_CHAT_CLI_TIMEOUT_SECONDS for v in _short_timeout_values(ext))
        if short:
            raise httpx.ReadTimeout("minister chat short timeout", request=request)
        body = {
            "id": "chatcmpl-minister-timeout",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "臣遵旨。"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def _bind_api_timeout_transport(model) -> None:
    model.http_client = httpx.Client(transport=_api_timeout_transport())
    model.client = None


def test_minister_agent_cli_timeout_slot_capped_and_not_a_subprocess_wall(monkeypatch):
    """召对 CLI 槽位仍按 90 封顶（#353 / ADR 0001），且不再下发成子进程墙钟（#1465）。

    观察面 = 公共 model.timeout（封顶事实）+ Popen 实参（无 timeout 墙）+ 出字即成案。
    """
    captured = _install_cli_process_boundary(monkeypatch)
    ctx = _make_context()
    cfg = _cfg_settlement_timeout(channel="cli")
    with _minister_agent_construction(ctx):
        agent = create_minister_agent(_make_character(), cfg, ctx, ctx.db)

    assert isinstance(agent.model, CliChat)
    # 槽位仍封顶（结算 300 → 召对 90）
    assert float(agent.model.timeout) == MINISTER_CHAT_CLI_TIMEOUT_SECONDS
    # 出字的子进程照常成案：短槽位不再 SIGKILL 它
    _invoke_minister_model(agent.model)
    assert "timeout" not in captured["kw"]
    assert cfg.cli_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS
    assert cfg.timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS


def test_minister_agent_api_timeout_capped(monkeypatch):
    """API minister invoke fails on short request timeout; channel stays API not env CLI."""
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    ctx = _make_context()
    cfg = _cfg_settlement_timeout(channel="api")
    assert cfg.channel == "api"
    with _minister_agent_construction(ctx):
        agent = create_minister_agent(_make_character(), cfg, ctx, ctx.db)

    model = agent.model
    assert isinstance(model, OpenAIChat)
    assert not isinstance(model, CliChat)
    _bind_api_timeout_transport(model)
    with pytest.raises(ModelProviderError, match="[Tt]imed out|timeout"):
        _invoke_minister_model(model)
    assert cfg.timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS


def test_minister_agent_does_not_mutate_original_llm_config(monkeypatch):
    """create_minister_agent must not modify the caller's LLMConfig (no side-effects)."""
    _install_cli_process_boundary(monkeypatch)
    original_cli = CLI_DEFAULT_TIMEOUT_SECONDS
    original_api = CLI_DEFAULT_TIMEOUT_SECONDS
    cfg = LLMConfig(
        api_key="",
        base_url="",
        model="gpt-5.5",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=original_cli,
        timeout_seconds=original_api,
    )
    ctx = _make_context()
    with _minister_agent_construction(ctx):
        agent = create_minister_agent(_make_character(), cfg, ctx, ctx.db)

    assert cfg.cli_timeout_seconds == original_cli
    assert cfg.timeout_seconds == original_api
    _invoke_minister_model(agent.model)
    assert cfg.cli_timeout_seconds == original_cli
    assert cfg.timeout_seconds == original_api
