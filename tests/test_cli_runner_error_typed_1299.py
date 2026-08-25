"""#1299/#1310：CLI runner 失败横幅不得进 content 当大臣台词。

三缝：
1. CliChat.invoke — runner 自身失败 → typed LLMUnavailable（非 RuntimeError 原文上抛）
2. extract_agent_text — agno 把异常 str 塞进 run_output.content+status=ERROR 时，
   翻成 LLMUnavailable，永不得把机器横幅当叙事返回
3. 召对消费链 — extract 抛 typed 后不得把横幅当 answer 落库/上卷轴

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
_MACHINE_MARKERS = (
    "codex 调用失败",
    "OpenAI Codex",
    "workdir:",
    "sandbox:",
    "退出码",
)


def _assert_no_machine_text(text: str) -> None:
    lowered = text or ""
    for marker in _MACHINE_MARKERS:
        assert marker not in lowered, f"machine text leaked: {marker!r} in {text!r}"


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
    # 玩家可见 message 走 diegetic 口吻，不夹机器原文
    _assert_no_machine_text(str(exc))
    _assert_no_machine_text(exc.message)
    # 技术细节可留 provider_message 供日志，但不得冒充台词
    assert "codex" in (exc.provider_message or "").lower() or "退出码" in (exc.provider_message or "")
    assert exc.code  # typed


def test_clichat_normal_reply_still_returns(monkeypatch):
    """负向：正常 CLI 回话照常出文本。"""
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
    assert "臣遵旨" in captured["text"]


# ── seam 2: extract_agent_text ──


def test_extract_agent_text_error_status_raises_typed_not_leaks_banner():
    """agno 吞异常后 status=ERROR + content=横幅 → extract 抛 typed，不返回横幅。"""
    run_output = SimpleNamespace(content=_RUNNER_BANNER, status="ERROR")
    with pytest.raises(LLMUnavailable) as ei:
        extract_agent_text(run_output)
    _assert_no_machine_text(ei.value.message)
    _assert_no_machine_text(str(ei.value))


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


# ── seam 3: 召对消费链（extract → answer）不得把横幅当台词 ──


def test_chat_answer_path_typed_failure_keeps_scroll_clean():
    """模拟 session.chat 消费链：agent.run 回 ERROR run_output → extract 抛 typed；
    调用方不得把横幅当 answer 交给 persist_minister_reply。"""
    run_output = SimpleNamespace(content=_RUNNER_BANNER, status="ERROR", tools=[])
    persisted: list[str] = []

    def persist_minister_reply(_name: str, _turn: int, answer: str, _ctid: int) -> int:
        persisted.append(answer)
        return 1

    with pytest.raises(LLMUnavailable) as ei:
        # 与 session.chat / web_app 同序：extract 先于 persist
        answer = extract_agent_text(run_output)
        persist_minister_reply("袁崇焕", 1, answer, 42)

    _assert_no_machine_text(ei.value.message)
    assert persisted == []


def test_llm_unavailable_player_message_is_diegetic_not_template_wall():
    """呈现层可见文案：短、diegetic、可重试口吻；禁机器原文、禁模板化长文。"""
    run_output = SimpleNamespace(content=_RUNNER_BANNER, status="ERROR")
    with pytest.raises(LLMUnavailable) as ei:
        extract_agent_text(run_output)
    msg = ei.value.message
    _assert_no_machine_text(msg)
    # 短文：非堆砌长模板
    assert len(msg) <= 40
    # 可重试语义（稍候/再/重）
    assert any(tok in msg for tok in ("稍", "再", "重", "未"))
