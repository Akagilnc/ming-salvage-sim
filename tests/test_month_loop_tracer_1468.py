"""#1468 / #1353：转译 LLM 死透 → 耗尽失败单源（真实 HTTP 入口）。

主两月 tracer 与场外 COURT_BREAK 夹具已随退役入口清除；本文件只保留仍有
真实入口契约价值的死透负向案。#1902 F3：删专用死夹具。
"""

from __future__ import annotations
from tests.conftest import stub_webgame_boundary

import json

import pytest
from fastapi.testclient import TestClient

import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes
from tests.conftest import stub_audience_translate


# ── outermost LLM seams only ─────────────────────────────────────────────


def _stub_outer_llm_seams(monkeypatch) -> None:
    """只换最外层 LLM 工厂/调用；结算核、收夜、HTTP 路由、月尾 writer 全真跑。

    现役关系／派系酿制外部模型出口一并纳入：复用 deterministic brew 手，不改生产
    ``load_runtime_llm() == {}`` 配置语义，也不截月尾／queue／持久化。
    """
    from tests.test_web_audience_night_498 import _fake_settlement_llm
    from tests.test_faction_brew_637 import _dual_brew_fn_factory
    _fake_settlement_llm(monkeypatch, narrative="本月邸报：边饷已清，流寇未息。")
    stub_webgame_boundary(monkeypatch)
    # 月尾关系／派系酿制：隔离外部 brew 模型出口，保留 mechanical_tail 真路径。
    offline_brew = _dual_brew_fn_factory([])
    monkeypatch.setattr(
        "ming_sim.mechanical_tail._brew_fn_for_session",
        lambda _session: offline_brew,
    )




@pytest.fixture
def tracer_client(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """真实 FastAPI TestClient；用户数据落 tmp；仅外层 LLM stub。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_DB", raising=False)
    _stub_outer_llm_seams(monkeypatch)
    monkeypatch.setattr(web_app, "web_game", None)

    client = TestClient(web_app.app)
    yield client

    game = web_app.web_game
    if game is not None:
        # 等召对尾随落完再关库；fail-loud——wait_idle=False/异常不得吞掉后继续关库。
        try:
            _wait_pending_writes(game)
            game.session.close()
        finally:
            web_app.web_game = None



def _assert_not_bare_500(resp, *, step: str) -> None:
    """裸 500 = 无 detail 的服务器崩；结构化 4xx/可读 500 detail 另论。"""
    if resp.status_code < 500:
        return
    detail = None
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else body
    except Exception:
        detail = resp.text
    assert detail not in (None, "", {}), (
        f"{step}: bare 500 without detail; body={resp.text!r}"
    )
    # 仍禁止主链撞 500——玩家基本流程必须走通。
    assert resp.status_code < 500, (
        f"{step}: unexpected {resp.status_code}; detail={detail!r}"
    )



def _pick_active_minister(state: dict) -> str:
    for m in state.get("ministers") or []:
        if not isinstance(m, dict):
            continue
        if m.get("status") != "active":
            continue
        if m.get("power_id", "ming") != "ming":
            continue
        if m.get("office_type") in ("后宫", "宗藩"):
            continue
        name = str(m.get("name") or "").strip()
        if name:
            return name
    raise AssertionError(f"no active ming minister in state ministers={state.get('ministers')!r}")



def _turn_of(state: dict) -> int:
    turn = state.get("turn") or {}
    return int(turn.get("turn") or 0)



def _get_state(client: TestClient) -> dict:
    resp = client.get("/api/game/state")
    _assert_not_bare_500(resp, step="GET /api/game/state")
    assert resp.status_code == 200, resp.text
    return resp.json()



def _pending_payload(client: TestClient) -> dict:

    """#1842/#1853：待补投影唯一真源 = list_pending_translations → scroll.translation_retries。"""
    resp = client.get("/api/audience/scroll")
    _assert_not_bare_500(resp, step="GET /api/audience/scroll")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    retries = list(body.get("translation_retries") or [])
    return {"pending": retries, "count": len(retries)}



def _parse_sse(text: str) -> list[dict]:
    """解析 SSE 文本为 [{event, data}, ...]（与仓内其他 ASGI tracer 同形）。"""
    events: list[dict] = []
    for block in (text or "").strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur:
            events.append(cur)
    return events



def _post_issue_stream(
    client: TestClient, *, expected_turn: int, step: str,
    allow_error: bool = False,
) -> dict:
    """玩家真入口：POST /api/decree/issue/stream，消费 SSE 到终态。

    返回归一化 body：done → payload；decisions → payload + awaiting_decision=True。
    event:error 且 status_code=409 → 死锁断言红；其它 error 默认亦红。
    allow_error=True（#1769 真故障钉）：error 终态返回 payload 并标 _event='error'。
    """
    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": expected_turn},
    )
    _assert_not_bare_500(resp, step=step)
    assert resp.status_code == 200, f"{step} → {resp.status_code}: {resp.text}"
    # 流式入口 HTTP 层 200；业务失败走 event:error（含 409 令牌/锁语义）。
    events = _parse_sse(resp.text)
    assert events, f"{step}: empty SSE body={resp.text!r}"
    terminal = events[-1]
    ev = terminal.get("event")
    raw = terminal.get("data") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = {"message": raw}
    if ev == "error":
        status = data.get("status_code") if isinstance(data, dict) else None
        assert status != 409, (
            f"{step}: 409 deadlock on issue/stream; body={resp.text}"
        )
        if allow_error:
            payload = dict(data) if isinstance(data, dict) else {"message": data}
            return {**payload, "_event": "error"}
        raise AssertionError(f"{step}: stream error event: {data!r}; sse={resp.text!r}")
    if ev == "decisions":
        assert isinstance(data, dict), f"{step}: decisions payload not dict: {data!r}"
        return {**data, "awaiting_decision": True}
    if ev == "done":
        assert isinstance(data, dict), f"{step}: done payload not dict: {data!r}"
        return data
    raise AssertionError(
        f"{step}: unexpected terminal SSE event {ev!r}; body={resp.text!r}"
    )
