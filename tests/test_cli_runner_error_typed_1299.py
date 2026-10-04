"""#1299/#1310：CLI runner 失败横幅不得进 content 当大臣台词。

真实入口：
1. CliChat.invoke — runner 自身失败 → typed LLMUnavailable（非 RuntimeError 原文上抛）
2. extract_agent_text — ERROR 状态转成 typed failure，正常原文保真

负向：正常回话 content 照常提取。
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


def test_clichat_runner_exit_raises_typed_llm_unavailable(monkeypatch):
    """runner exit 1 带横幅 → CliChat 抛 typed LLMUnavailable，非 RuntimeError。"""
    cc = cb.CliChat(id="cli-test", backend="codex")
    monkeypatch.setattr(
        cc, "_call_cli",
        lambda p: (_ for _ in ()).throw(RuntimeError(_RUNNER_BANNER)),
    )
    monkeypatch.setattr(cb, "_trace", lambda rec: None)

    with pytest.raises(LLMUnavailable) as ei:
        cc.invoke(
            [SimpleNamespace(role="user", content="宣袁崇焕")],
            Message(role="assistant"),
        )
    exc = ei.value
    # The injected provider diagnostic is not the player-facing message.
    assert _RUNNER_BANNER not in exc.message
    assert exc.provider_message == _RUNNER_BANNER
    assert exc.code  # typed


def test_clichat_normal_reply_still_returns(monkeypatch):
    """夹具 CLI 回包经 _fake_completion 原样透传（非生成散文锁）。"""
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cc, "_call_cli", lambda p: ("臣遵旨，边事容臣细奏。", 1))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    captured = {}
    real_fake = cb._fake_completion

    def spy(text, model_id, *a, **k):
        captured["text"] = text
        return real_fake(text, model_id, *a, **k)

    monkeypatch.setattr(cb, "_fake_completion", spy)
    cc.invoke(
        [SimpleNamespace(role="user", content="边事如何")],
        Message(role="assistant"),
    )
    assert captured["text"] == "臣遵旨，边事容臣细奏。"


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


def test_extract_agent_text_normal_reply_passes():
    """负向：正常 content 原样返回。"""
    run_output = SimpleNamespace(content="臣请据实回奏边饷事。", status="COMPLETED")
    assert extract_agent_text(run_output) == "臣请据实回奏边饷事。"


def test_extract_agent_text_preserves_leading_trailing_whitespace():
    """#671：真实 agent.run 提取不得 strip；空白只在判空临时副本用。"""
    raw = "\n  奴婢禀报：洪承畴抵京候旨。  \n"
    run_output = SimpleNamespace(content=raw, status="COMPLETED")
    assert extract_agent_text(run_output) == raw
    # 纯空白仍原样返回（空判定由调用方临时 strip）
    blank = "   \n\t  "
    assert extract_agent_text(SimpleNamespace(content=blank, status="COMPLETED")) == blank


def test_extract_agent_text_plain_string_still_works():
    """无 status 的纯文本/旧路径仍可提取。"""
    assert extract_agent_text("臣领旨。") == "臣领旨。"


def test_run_cli_runner_preserves_llm_body_whitespace(monkeypatch):
    """#1834 F16：CLI runner 终文是 LLM 正文，进入 supply/write；禁 strip 包装清理。"""
    from tests.cli_process_doubles import FakeCliProcess

    raw = "\n  臣请据实回奏边饷事。  \n"

    def fake_popen(cmd, **kw):
        return FakeCliProcess(
            cmd, stdout_script=(raw,), stderr_script=(), returncode=0, popen_kwargs=kw,
        )

    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    out, attempts = cb._run_cli_runner("agy", "PROMPT")
    assert attempts == 1
    assert out == raw
    chunks = list(cb._iter_cli_runner_text("agy", "PROMPT"))
    assert chunks == [raw]


def test_run_cli_runner_whitespace_only_still_empty(monkeypatch):
    """判空用 strip 副本：纯空白仍作空输出失败，取值路径不改写成非空。"""
    from tests.cli_process_doubles import FakeCliProcess
    from ming_sim.exceptions import LLMUnavailable

    blank = "   \n\t  "

    def fake_popen(cmd, **kw):
        return FakeCliProcess(
            cmd, stdout_script=(blank,), stderr_script=(), returncode=0, popen_kwargs=kw,
        )

    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    with pytest.raises(LLMUnavailable) as ei:
        cb._run_cli_runner("agy", "PROMPT")
    assert ei.value.code == "llm_empty_output"


def test_write_decree_with_agno_preserves_whitespace(monkeypatch):
    """#1834 F16：拟诏 LLM 正文保原文；strip 只判空。"""
    from ming_sim.decree import write_decree_with_agno
    from ming_sim.models import GameState, LLMConfig

    raw = "\n  诏曰：着户部清核辽饷。  \n"

    class _Agent:
        def run(self, _prompt):
            return SimpleNamespace(content=raw, status="COMPLETED")

    monkeypatch.setattr(
        "ming_sim.decree.create_decree_writer_agent",
        lambda *a, **k: _Agent(),
    )
    monkeypatch.setattr("ming_sim.decree._dump_llm_messages", lambda *a, **k: None)
    row = {"text": "清核辽饷", "turn": 1}

    class _Row(dict):
        pass

    got = write_decree_with_agno(
        LLMConfig(api_key="x", base_url="", model="m"),
        object(),
        GameState(year=1627, period=1, turn=1),
        [_Row(row)],
    )
    assert got == raw


def test_require_non_empty_text_preserves_whitespace():
    """契约校验判空用副本，返回原文。"""
    from ming_sim.llm_contract import require_non_empty_text

    raw = "\n  边饷未清。  \n"
    assert require_non_empty_text(raw, "测", "field") == raw
    with pytest.raises(Exception):
        require_non_empty_text("   ", "测", "field")
