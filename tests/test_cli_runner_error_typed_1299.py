"""#1299/#1310：CLI runner 失败横幅不得进 content 当大臣台词。

真实入口：
1. CliChat.invoke — 未分类 runner 故障 → 原异常上抛（不冒称 LLM 故障）
2. extract_agent_text — ERROR 状态转成 typed failure

原文运输由 CliChat.invoke 的既有成功案承接。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agno.models.message import Message

import ming_sim.cli_backend as cb
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import extract_agent_text

# QA 实锤横幅形态（cli_backend.py:424/590 原文 + stderr 含版本/workdir/model/sandbox）
_RUNNER_BANNER = (
    "codex 调用失败（退出码 1）："
    "OpenAI Codex v0.50.0\n"
    "workdir: /tmp/ming-sandbox\n"
    "model: gpt-5.5\n"
    "sandbox: workspace-write"
)
# ── seam 1: CliChat ──


def test_clichat_unclassified_runner_failure_preserves_original(monkeypatch):
    """未分类故障不能靠 runner 名字洗成模型错误。"""
    cc = cb.CliChat(id="cli-test", backend="codex")
    fault = RuntimeError(_RUNNER_BANNER)
    monkeypatch.setattr(cc, "_call_cli", lambda p: (_ for _ in ()).throw(fault))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)

    with pytest.raises(RuntimeError) as ei:
        cc.invoke(
            [SimpleNamespace(role="user", content="宣袁崇焕")],
            Message(role="assistant"),
        )
    assert ei.value is fault


def test_clichat_normal_reply_still_returns(monkeypatch):
    """夹具 CLI 回包贯穿 invoke 原样透传（非生成散文锁）。"""
    cc = cb.CliChat(id="cli-test", backend="agy")
    original = "  臣遵旨，边事容臣细奏。\n"
    monkeypatch.setattr(cc, "_call_cli", lambda p: (original, 1))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    result = cc.invoke(
        [SimpleNamespace(role="user", content="边事如何")],
        Message(role="assistant"),
    )
    assert result.content == original


# ── seam 2: extract_agent_text ──


def test_extract_agent_text_error_status_raises_typed_not_leaks_banner():
    """agno 吞异常后 status=ERROR + content=横幅 → extract 抛 typed，不返回横幅。

    #1465 ④：系统层 code=llm_run_error、message != 戏内单源；机器横幅不进 message。
    """
    run_output = SimpleNamespace(content=_RUNNER_BANNER, status="ERROR")
    with pytest.raises(LLMUnavailable) as ei:
        extract_agent_text(run_output)
    assert ei.value.message
    assert ei.value.code == "llm_run_error"
    assert _RUNNER_BANNER not in ei.value.message
    assert ei.value.provider_message == _RUNNER_BANNER


def test_extract_agent_text_error_enum_status_raises():
    """status 亦可能是 enum-like（value=ERROR）。"""
    status = SimpleNamespace(value="ERROR")
    run_output = SimpleNamespace(content=_RUNNER_BANNER, status=status)
    with pytest.raises(LLMUnavailable):
        extract_agent_text(run_output)
