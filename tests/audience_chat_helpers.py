"""#1902：召对非流式路由退役后，测试改走唯一的流式入口。

#1902 撤下 POST /api/audience/chat（非流式，drain stream 回 done 载荷）——前端自
#1842 起只用 /api/audience/chat/stream，说话只有一条入口。本模块给测试一条
SSE 终态夹具；SSE 解析本身在 tests.sse_helpers（#1902 全仓单一真源）。
"""

from __future__ import annotations

from typing import Any

from tests.sse_helpers import parse_sse_events


def post_audience_chat(client, message: str, *, step: str = "audience chat") -> dict:
    """真实玩家入口：POST /api/audience/chat/stream，消费 SSE 到终态并回 done 载荷。

    终态 error 直接断言红（带 detail），与旧非流式路由的 400/409 同义。
    """
    import json

    resp = client.post("/api/audience/chat/stream", json={"message": message})
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    events = parse_sse_events(resp.text)
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
