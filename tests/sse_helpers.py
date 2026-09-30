"""SSE 文本 → 事件列表的单一真源（#1902）。

此前仓内有多份同形解析：非流式召对/颁诏退役后新增的两个 helper 各自抄了一份，
`test_month_loop_tracer_1468` / `test_court_break_player_lock_1727` 又各带一份。
本模块只做一件事——把 `event:` / `data:` 行解成 `[{event, data}, ...]`，
`data` 保持原始字符串（各调用方按自己的契约 json.loads）。调用方只引用，不再重抄。
"""

from __future__ import annotations


def parse_sse_events(text: str) -> list[dict]:
    """SSE 文本 → [{event, data}, ...]；`data` 为原始字符串。"""
    events: list[dict] = []
    for block in (text or "").strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                cur["data"] = line.split(":", 1)[1].strip()
        if cur:
            events.append(cur)
    return events
