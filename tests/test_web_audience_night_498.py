"""#498 召对夜 × web 真实入口 tracer（只 fake LLM 边界）。

真实 WebGame + 真实 FastAPI 路由（经 httpx.ASGITransport 走 SSE / HTTP），仅把大臣
agent.run 与月末推演（resolve_directives / write_decree_with_agno）这层 LLM 边界换成 canned。

覆盖：
- 完成回话 SSE 入档→持久化→颁诏顺势收夜→回合推进（AC8/AC10 happy path，真实
  /chat/stream + /decree/issue/stream 两条 SSE 串联）；
- 挂起回话在飞 → 真实 /decree/issue/stream fail-closed（SSE error）、夜保持开、turn 不变（AC10）；
- 同步退朝端点被 threadpool offload、阻塞在飞等待不冻结 event loop（ASGI + ticker）；
- 等 gate 期间相位翻到亲裁（TOCTOU）→ 持锁内权威复查拒、零新夜/新 chat turn（chat 与
  chat_stream 两种入口；确定性栅栏 = 真实 pending-write 态，删掉持锁内复查即红）；
- 拟诏 preview 不收夜（真实 /api/decree/write）。

不用 iscoroutinefunction / 手造 Lock / SimpleNamespace gate / object.__new__ partial WebGame /
手动 attach+_land_reply / time.sleep 作竞态同步。
"""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest

import web_app
import ming_sim.session as session_mod
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase
from ming_sim.session import ResolveResult


# ── canned LLM 边界（唯一 fake）────────────────────────────────────────
class _RunContent:
    event = "RunContent"

    def __init__(self, content: str):
        self.content = content


class RunCompletedEvent:  # 类名须为 RunOutput / RunCompletedEvent（web_app 按 type(event).__name__ 判终帧）
    content = ""
    tools: list = []


class _FakeAgent:
    """canned 大臣回话流；allow 非空则在 delta 与终帧之间阻塞（模拟在飞挂起）。"""

    def __init__(self, allow: threading.Event | None = None, answer: str = "臣已知悉，边饷当速清。"):
        self.allow = allow
        self.answer = answer

    def run(self, *args, **kwargs):
        yield _RunContent(self.answer)
        if self.allow is not None:
            assert self.allow.wait(5.0), "fake agent 等待超时"
        yield RunCompletedEvent()

    def get_last_run_output(self):
        return None


@pytest.fixture
def web_game(tmp_path, monkeypatch):
    """真实 WebGame（新档、temp DB、离线 LLM）。仅 verify_llm 与 runtime 配置被中和。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(session_mod, "verify_llm_available", lambda cfg: None)
    game = web_app.WebGame(fresh=False)
    monkeypatch.setattr(web_app, "web_game", game)
    yield game
    try:
        game.session.close()
    except Exception:
        pass


def _active_minister(game) -> str:
    for name, ch in game.content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if game.db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _count(db, table: str) -> int:
    return int(db.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=web_app.app), base_url="http://t")


async def _drain_sse(response) -> list[dict]:
    """把一条 SSE 响应读成 [{event, data}] 直到终帧（done/error/decisions）。"""
    events: list[dict] = []
    cur: dict = {}
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            cur["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            cur["data"] = line[len("data:"):].strip()
        elif line == "" and cur:
            events.append(dict(cur))
            if cur.get("event") in ("done", "error", "decisions"):
                break
            cur = {}
    return events


# ── ① AC8/AC10 happy path：真实 /chat/stream SSE → /decree/issue/stream SSE ──
def test_asgi_completed_chat_then_issue_closes_night(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    game.session.registry.get = lambda ch: _FakeAgent()
    # 月末推演这层 LLM 边界 canned（只 fake LLM）
    monkeypatch.setattr(session_mod, "write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")
    monkeypatch.setattr(
        session_mod, "resolve_directives",
        lambda *a, **k: ResolveResult(awaiting=False, report="本月邸报：边饷已清。"))

    async def scenario():
        async with _client() as client:
            async with client.stream(
                "POST", f"/api/ministers/{minister}/chat/stream", json={"message": "边饷如何？"}
            ) as resp:
                chat_events = await _drain_sse(resp)
            # 待颁诏有候选：staged 拟旨（issue 的 default-agree 会提交为 draft）
            game.db.upsert_pending_directive(
                game.state.turn, minister, payload={"text": "着户部核边饷", "actor": minister})
            issue_resp = await client.post("/api/decree/issue/stream", json={})
            issue_events = await _drain_sse_bytes(issue_resp)
            return chat_events, issue_events

    chat_events, issue_events = asyncio.run(scenario())

    assert any(e["event"] == "delta" for e in chat_events)
    assert chat_events[-1]["event"] == "done"
    # 回话真实入档（持久化到 chat_messages）
    assert game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_messages WHERE minister_name=? AND role='minister'",
        (minister,)).fetchone()["c"] == 1
    # 颁诏成功（done，非 error/decisions）且顺势收夜（night 收夜封闭）
    # —— 月末推演（turn 推进/结算数值）是被 canned 的 LLM 边界之后的引擎效果，非本片契约。
    assert issue_events[-1]["event"] == "done"
    assert "诏" in (issue_events[-1].get("data") or "")
    night = an.get_night(game.db, 1)
    assert night is not None and night["status"] == "closed"


async def _drain_sse_bytes(response) -> list[dict]:
    """非 stream() 拿到的响应：body 已就绪，按 SSE 帧切。"""
    events: list[dict] = []
    text = response.text if hasattr(response, "text") else (await response.aread()).decode()
    for block in text.strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur:
            events.append(cur)
    return events


# ── ② AC10 fail-closed：挂起在飞 → 真实 /decree/issue/stream SSE error、夜开、turn 不变 ──
def test_asgi_hanging_chat_makes_issue_fail_closed(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    allow = threading.Event()
    game.session.registry.get = lambda ch: _FakeAgent(allow=allow)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.0)

    # 真实 chat_stream 起一轮回话并卡在生成中（在飞）：读首个 delta 即建成 generating 轮。
    # （chat 用真实方法起在飞态，避免 SSE 中途断流误 fail 该轮；被测重点是颁诏路的 SSE fail-closed。）
    stream = game.chat_stream(minister, "边饷如何？")
    assert next(stream)["type"] == "delta"
    night = an.get_open_night(game.db)
    assert night is not None and night["status"] == "open"
    turn_before = int(game.state.turn)

    async def issue():
        async with _client() as client:
            resp = await client.post("/api/decree/issue/stream", json={})
            return await _drain_sse_bytes(resp)

    issue_events = asyncio.run(issue())

    # 在飞未落档 → 真实颁诏端点经 SSE 报错、夜保持开、turn 不变
    assert issue_events[-1]["event"] == "error"
    assert an.get_night(game.db, night["id"])["status"] == "open"
    assert int(game.state.turn) == turn_before

    # 回话落档后不再挡（放行 + 排空）
    allow.set()
    list(stream)


# ── ③ 同步退朝端点 offload 不冻结 event loop（真实 ASGI 路由 + ticker）──────
def test_sync_advance_endpoint_does_not_stall_event_loop(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    allow = threading.Event()
    game.session.registry.get = lambda ch: _FakeAgent(allow=allow)
    # 在飞挂起，使退朝端点在 _await_audience_inflight_clear 阻塞约 0.4s（同步 sleep）
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.4)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_POLL_S", 0.02)

    stream = game.chat_stream(minister, "边饷如何？")
    assert next(stream)["type"] == "delta"  # in-flight generating 轮

    async def drive():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        async with _client() as client:
            resp = await client.post("/api/decree/advance_without_edict")
        t.cancel()
        return ticks, resp.status_code

    ticks, status = asyncio.run(drive())
    assert ticks >= 5, f"event loop 被同步端点冻结（ticks={ticks}）"
    assert status == 409  # 在飞超时 fail-closed

    allow.set()
    list(stream)


# ── ④ TOCTOU：等 gate 期间相位翻转被持锁内复查拒（确定性栅栏 = 真实 pending-write 态）──
def _run_race(game, minister, drive, on_reached):
    """通用：持真实 write_gate → 起 worker（drive）→ worker 过锁前查、达栅栏后阻塞抢 gate →
    on_reached 翻相位并放锁 → worker 抢到 gate 后权威复查拒。返回 worker 结果。"""
    game.state.turn_phase = TurnPhase.SUMMONING.value
    reached = threading.Event()
    result: dict = {}

    def worker():
        try:
            result["value"] = drive()
        except BaseException as exc:  # noqa: BLE001
            result["exc"] = exc

    game._write_gate.acquire()  # 扮演结算 worker 持真实 gate
    t = threading.Thread(target=worker)
    on_reached(reached)  # 装好「达栅栏」信号
    t.start()
    assert reached.wait(3.0), "worker 未到达 gate 前栅栏"
    # worker 已过锁前快速查、标记 pending-write、正阻塞抢 gate：此刻结算翻相位到亲裁
    game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    game._write_gate.release()
    t.join(3.0)
    assert not t.is_alive()
    return result


def test_phase_flip_while_waiting_gate_rejected_chat_stream(web_game):
    game = web_game
    minister = _active_minister(game)
    nights0, turns0 = _count(game.db, "audience_nights"), _count(game.db, "chat_turns")

    def on_reached(reached):
        orig = game._mark_pending_write  # 锁前查之后、抢 gate 之前的真实态

        def hooked():
            ok = orig()
            reached.set()
            return ok

        game._mark_pending_write = hooked

    result = _run_race(game, minister, lambda: list(game.chat_stream(minister, "边饷如何？")), on_reached)

    events = result["value"]
    assert events and events[-1]["type"] == "error"
    assert "结算" in events[-1]["message"] or "亲裁" in events[-1]["message"]
    assert _count(game.db, "audience_nights") == nights0
    assert _count(game.db, "chat_turns") == turns0


def test_phase_flip_while_waiting_gate_rejected_chat(web_game):
    from fastapi import HTTPException

    game = web_game
    minister = _active_minister(game)
    nights0, turns0 = _count(game.db, "audience_nights"), _count(game.db, "chat_turns")

    def on_reached(reached):
        orig = game._runtime_write_gate  # chat：取 gate 之后即 `with gate:` 阻塞

        def hooked():
            g = orig()
            reached.set()
            return g

        game._runtime_write_gate = hooked

    result = _run_race(game, minister, lambda: game.chat(minister, "边饷如何？"), on_reached)

    assert isinstance(result.get("exc"), HTTPException)
    assert result["exc"].status_code == 409
    assert _count(game.db, "audience_nights") == nights0
    assert _count(game.db, "chat_turns") == turns0


# ── ⑤ 拟诏 preview 不收夜（真实 /api/decree/write）───────────────────────
def test_asgi_write_decree_preview_does_not_close_night(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    game.session.registry.get = lambda ch: _FakeAgent()
    list(game.chat_stream(minister, "边饷如何？"))  # 开夜 + 入档
    night = an.get_open_night(game.db)
    assert night is not None and night["status"] == "open"

    game.db.upsert_pending_directive(
        game.state.turn, minister, payload={"text": "着户部核边饷", "actor": minister})
    game.db.commit_pending_actions(game.state, kind_filter="directive")  # 有效 draft
    monkeypatch.setattr(session_mod, "write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")

    async def scenario():
        async with _client() as client:
            return await client.post("/api/decree/write", json={})

    resp = asyncio.run(scenario())
    assert resp.status_code == 200
    assert "诏" in resp.json()["decree"]
    # 拟诏是 preview：夜仍开、无收夜账
    assert an.get_night(game.db, night["id"])["status"] == "open"
    closes = [e for e in an.list_ledger(game.db, night["id"]) if an.TAG_CLOSE_NIGHT in (e.get("tags") or [])]
    assert closes == []
