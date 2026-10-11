"""#1902：非流式颁诏路由退役后，测试改走唯一的流式入口。

web_app 撤 POST /api/decree/issue（非流式，与 issue/stream 的 worker 同构）——颁布
只有流式一条入口。本模块把 SSE 终态（done / decisions / error）解成测试可直接断言
的形状：成功回 done 载荷，失败抛 :class:`IssueStreamError`（带 status_code 与
payload），使原来看 HTTP 状态码 + detail 的断言可以逐字迁移，不被削弱。
"""

from __future__ import annotations

from typing import Any, Optional

from tests.conftest import wait_for_background_jobs
from tests.sse_helpers import parse_sse_events as _parse_sse


class IssueStreamError(AssertionError):
    """流式颁诏终态为 error；status_code/payload 与旧非流式路由的 HTTP 语义对应。"""

    def __init__(self, status_code: Optional[int], payload: Any):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"issue/stream error → status={status_code} payload={payload!r}")


def _terminal_payload(events: list[dict], *, step: str) -> dict:
    """done / decisions / error 三种终态归一：成功回载荷，失败抛 IssueStreamError。"""
    terminal = next(
        (e for e in reversed(events) if e.get("event") in ("done", "decisions", "error")),
        None,
    )
    assert terminal is not None, f"{step}: 无 done/decisions/error 终态 → {events!r}"
    payload = _loads(terminal.get("data"))
    if terminal.get("event") == "error":
        # #1902：status_code 只在载荷自带时采信（issue/stream 上 409 专表令牌失效/
        # 死锁）；结算中止不带它，靠 stage / error_pack_path 判——禁在此替它补 409。
        status = payload.get("status_code") if isinstance(payload, dict) else None
        raise IssueStreamError(status if isinstance(status, int) else None, payload)
    out = dict(payload) if isinstance(payload, dict) else {"payload": payload}
    if terminal.get("event") == "decisions":
        out["awaiting_decision"] = True
    return out


def _loads(data: Any) -> Any:
    import json

    if isinstance(data, str):
        try:
            return json.loads(data)
        except ValueError:
            return data
    return data


def post_issue_stream(client, *, expected_turn: Optional[int] = None, step: str = "issue/stream"):
    """真实玩家入口 POST /api/decree/issue/stream → 终态。

    - 终态 done → 返回 payload（含 awaiting_decision 时的决策点）
    - 终态 error → 抛 IssueStreamError(status_code, payload)，status_code 取
      payload 内的 typed 键（旧路由是 HTTP 状态码），缺省按 500 对齐
    """
    body: dict[str, Any] = {}
    if expected_turn is not None:
        body["expected_turn"] = int(expected_turn)
    resp = client.post("/api/decree/issue/stream", json=body)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    payload = _terminal_payload(_parse_sse(resp.text), step=step)
    from web_app import get_game

    wait_for_background_jobs(get_game().db)
    return payload


async def apost_issue_stream(client, *, expected_turn: Optional[int] = None,
                             step: str = "issue/stream"):
    """async httpx client 版（tests 里 ASGI transport 的 client 同形）。"""
    body: dict[str, Any] = {}
    if expected_turn is not None:
        body["expected_turn"] = int(expected_turn)
    resp = await client.post("/api/decree/issue/stream", json=body)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    payload = _terminal_payload(_parse_sse(resp.text), step=step)
    from web_app import get_game

    wait_for_background_jobs(get_game().db)
    return payload


async def consume_issue_stream_response(response, *, step: str = "issue/stream"):
    """直调 api_issue_decree_stream 时的同形解析（不经 HTTP client 的旧式用例用）。"""

    events: list[dict] = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        events.extend(_parse_sse(text))
    payload = _terminal_payload(events, step=step)
    from web_app import get_game

    wait_for_background_jobs(get_game().db)
    return payload
