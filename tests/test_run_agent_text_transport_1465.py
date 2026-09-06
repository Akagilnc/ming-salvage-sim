"""#1465 ② 缝级：run_agent_text 终文取 SDK 终包，非 chunk 拼接。

结算入口空转/跨墙/自愈/耗尽见 test_settlement_extractor_transport_1750（可观察流替身）。
本文件只留 chunk 畸形 vs 终包完整 content 的独立证明。
"""

from __future__ import annotations

import json

import ming_sim.agents as agents_mod


class RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:
    def __init__(self, content=None):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


class RunOutput:
    def __init__(self, content: str):
        self.content = content
        self.status = "COMPLETED"
        self.messages = None


def test_run_agent_text_final_text_from_terminal_not_chunk_join(monkeypatch):
    """chunk 含畸形片段时，终文仍取 SDK 终包完整 content（严格 JSON 真源）。"""
    monkeypatch.setattr(agents_mod, "_dump_llm_messages", lambda *_a, **_k: None)
    good = '{"国势变化": {"民心": -1}, "钱粮收支": []}'

    class _ChunkGarbageTerminalGood:
        def run(self, *_a, **_k):
            yield RunContent('{"partial":')
            yield RunContent(" NOT_JSON_GARBAGE ")
            yield RunCompletedEvent(content=None)
            yield RunOutput(good)

    text = agents_mod.run_agent_text(
        _ChunkGarbageTerminalGood(), "payload", tag="extractor/internal",
    )
    assert text == good
    assert json.loads(text)["国势变化"]["民心"] == -1
