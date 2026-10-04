"""CLI provider invocation keeps typed failures separate from successful content."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from agno.models.message import Message

import ming_sim.cli_backend as cb
from ming_sim.exceptions import LLMUnavailable
from tests.cli_process_doubles import FakeCliProcess


_RUNNER_BANNER = (
    "codex 调用失败（退出码 1）："
    "OpenAI Codex v0.50.0\n"
    "workdir: /tmp/ming-sandbox\n"
    "model: gpt-5.5\n"
    "sandbox: workspace-write"
)


def _popen_with(monkeypatch, *, stdout="", stderr="", returncode=0):
    def fake_popen(cmd, **kw):
        return FakeCliProcess(
            cmd,
            stdout_script=((stdout,) if stdout else ()),
            stderr_script=((stderr,) if stderr else ()),
            returncode=returncode,
            popen_kwargs=kw,
        )

    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)


def test_clichat_runner_exit_raises_typed_llm_unavailable(monkeypatch):
    _popen_with(
        monkeypatch,
        stderr=(
            "OpenAI Codex v0.50.0\n"
            "workdir: /tmp/ming-sandbox\n"
            "model: gpt-5.5\n"
            "sandbox: workspace-write"
        ),
        returncode=1,
    )
    cc = cb.CliChat(id="cli-test", backend="codex")
    with pytest.raises(LLMUnavailable) as ei:
        cc.invoke(
            [SimpleNamespace(role="user", content="宣袁崇焕")],
            Message(role="assistant"),
        )
    assert ei.value.code
    assert ei.value.provider_message == _RUNNER_BANNER


def test_clichat_normal_reply_still_returns(monkeypatch):
    raw = "臣遵旨，边事容臣细奏。"
    _popen_with(monkeypatch, stdout=raw)
    cc = cb.CliChat(id="cli-test", backend="agy")
    response = cc.invoke(
        [SimpleNamespace(role="user", content="边事如何")],
        Message(role="assistant"),
    )
    assert response.content == raw
