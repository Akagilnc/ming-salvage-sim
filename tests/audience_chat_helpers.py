"""#1902：召对非流式路由退役后，测试改走唯一的流式入口。

#1902 撤下 POST /api/audience/chat（非流式，drain stream 回 done 载荷）——前端自
#1842 起只用 /api/audience/chat/stream，说话只有一条入口。本模块给测试一条
SSE 终态解析夹具，避免每处各写一份解析。
"""

from __future__ import annotations

from typing import Any


def parse_sse(text: str) -> list[dict]:
    """SSE 文本 → [{event, data}, ...]（与仓内 ASGI tracer 同形）。"""
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


def post_audience_chat(client, message: str, *, step: str = "audience chat") -> dict:
    """真实玩家入口：POST /api/audience/chat/stream，消费 SSE 到终态并回 done 载荷。

    终态 error 直接断言红（带 detail），与旧非流式路由的 400/409 同义。
    """
    import json

    resp = client.post("/api/audience/chat/stream", json={"message": message})
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    events = parse_sse(resp.text)
    assert events, f"{step}: 空 SSE 流"
    # 流以 end 收尾，故取 done/error 事件而非最后一条。
    terminal = next((e for e in reversed(events) if e.get("event") in ("done", "error")), None)
    assert terminal is not None, f"{step}: 无 done/error 终态 → {events!r}"
    if terminal.get("event") == "error":
        detail: Any = terminal.get("data") or {}
        try:
            detail = json.loads(detail) if isinstance(detail, str) else detail
        except ValueError:
            pass
        raise AssertionError(f"{step}: 召对终态 error → {detail!r}")
    data = terminal.get("data") or "{}"
    return json.loads(data) if isinstance(data, str) else dict(data)
