"""SSE 文本 → 事件列表的单一真源（#1902）。

此前仓内有多份同形解析：非流式召对/颁诏退役后新增的两个 helper 各自抄了一份，
`test_month_loop_tracer_1468` / `test_court_break_player_lock_1727` 又各带一份。
本模块只做一件事——把 `event:` / `data:` 行解成 `[{event, data}, ...]`，
`data` 保持原始字符串（各调用方按自己的契约 json.loads）。
`parse_sse_event_pairs` 是同一份解析的 tuple 投影（`[(event, json), ...]`），
供按位置解包的调用方使用——同一契约只此一份实现，返回形态不是另抄一份的理由。

生产发射侧恒为单行 `event: <name>` / `data: <json>`（web_app.sse_event），
故多行拼接分支不会出现；解析仍按 SSE 规范把同名字段的多行 data 接起来。
"""

from __future__ import annotations

import json


def parse_sse_events(text: str) -> list[dict]:
    """SSE 文本 → [{event, data}, ...]；`data` 为原始字符串。"""
    events: list[dict] = []
    for block in (text or "").strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                # 同一事件的多行 data 按 SSE 规范以换行接续。
                chunk = line.split(":", 1)[1].strip()
                cur["data"] = f"{cur['data']}\n{chunk}" if "data" in cur else chunk
        if cur:
            events.append(cur)
    return events


def parse_sse_event_pairs(text: str) -> list[tuple[str, dict]]:
    """`parse_sse_events` 的 tuple 投影：[(event, json.loads(data)), ...]。"""
    pairs: list[tuple[str, dict]] = []
    for item in parse_sse_events(text):
        name = str(item.get("event") or "")
        data_raw = str(item.get("data") or "")
        if not name or not data_raw:
            continue
        pairs.append((name, json.loads(data_raw)))
    return pairs
