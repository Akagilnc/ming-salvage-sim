"""#498 召对夜 × web 真实入口 tracer（只 fake LLM 边界）。

用真实 WebGame + 真实 FastAPI 路由（chat_stream / advance / issue / write），仅把大臣
agent.run 换成 canned stream。覆盖：完成回话入档→收夜→过回合；挂起回话 fail-closed 409、
夜保持开、落档后可续；同步端点 offload 不冻结 event loop；等 gate 期间相位翻转（TOCTOU）被拒、
零新夜/新 chat turn；拟诏 preview 不收夜。

不手造 Lock / object.__new__ WebGame / SimpleNamespace gate / iscoroutinefunction。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

import web_app
import ming_sim.session as session_mod
from ming_sim import audience_night as an
from ming_sim.models import TurnPhase


# ── canned LLM stream（唯一 fake 边界）──────────────────────────────────
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


# ── ① 完成回话：入档→持久化→顺势收夜→过回合 ─────────────────────────────
def test_completed_reply_lands_then_night_closes_on_advance(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    game.session.registry.get = lambda ch: _FakeAgent()

    events = list(game.chat_stream(minister, "边饷如何？"))
    assert any(e["type"] == "delta" for e in events)
    assert events[-1]["type"] == "done"

    # 回话真实入档；对话轮升 active；开夜且大臣入殿
    assert game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM chat_messages WHERE minister_name=? AND role='minister'",
        (minister,)).fetchone()["c"] == 1
    night = an.get_open_night(game.db)
    assert night is not None and night["status"] == "open"
    assert minister in an.persons_entered_tonight(game.db, night["id"])

    # 真实过回合入口顺势收夜 + 推进
    before = int(game.state.turn)
    out = web_app.api_advance_without_edict()
    assert an.get_night(game.db, night["id"])["status"] == "closed"
    assert out["state"]["turn"]["turn"] == before + 1


# ── ② 挂起回话：真实退朝端点 fail-closed 409、夜保持开；落档后可续 ──────────
def test_hanging_reply_fails_closed_then_resumable(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    allow = threading.Event()
    game.session.registry.get = lambda ch: _FakeAgent(allow=allow)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.0)

    stream = game.chat_stream(minister, "边饷如何？")
    first = next(stream)  # prologue 建 generating 轮 + worker 阻塞在终帧前
    assert first["type"] == "delta"
    night = an.get_open_night(game.db)
    assert night is not None and night["status"] == "open"

    # 在飞未落档 → 退朝端点即时 fail-closed 409，夜保持开、turn 不进
    before = int(game.state.turn)
    with pytest.raises(HTTPException) as ei:
        web_app.api_advance_without_edict()
    assert ei.value.status_code == 409
    assert an.get_night(game.db, night["id"])["status"] == "open"
    assert int(game.state.turn) == before

    # 回话落档后可续：过回合收夜 + 推进
    allow.set()
    rest = list(stream)
    assert rest[-1]["type"] == "done"
    out = web_app.api_advance_without_edict()
    assert an.get_night(game.db, night["id"])["status"] == "closed"
    assert out["state"]["turn"]["turn"] == before + 1


# ── ③ 同步端点 offload 不冻结 event loop（真实 ASGI 路由 + ticker）──────────
def test_sync_advance_endpoint_does_not_stall_event_loop(web_game, monkeypatch):
    import httpx

    game = web_game
    minister = _active_minister(game)
    allow = threading.Event()
    game.session.registry.get = lambda ch: _FakeAgent(allow=allow)
    # 在飞挂起，使退朝端点在 _await_audience_inflight_clear 阻塞约 0.4s（同步 sleep）
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_WAIT_S", 0.4)
    monkeypatch.setattr("ming_sim.audience_night.DEFAULT_IN_FLIGHT_POLL_S", 0.02)

    stream = game.chat_stream(minister, "边饷如何？")
    assert next(stream)["type"] == "delta"  # in-flight

    async def drive():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        transport = httpx.ASGITransport(app=web_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.post("/api/decree/advance_without_edict")
        t.cancel()
        return ticks, resp.status_code

    ticks, status = asyncio.run(drive())
    # 同步端点被 Starlette offload 到 threadpool：阻塞的 0.4s 里 event loop 仍在推进
    assert ticks >= 5, f"event loop 被同步端点冻结（ticks={ticks}）"
    assert status == 409  # 在飞超时 fail-closed

    allow.set()
    list(stream)


# ── ④ 等 gate 期间相位翻转（TOCTOU）被持锁复查拒；零新夜/新 chat turn ────────
def test_phase_flip_while_waiting_gate_is_rejected(web_game):
    game = web_game
    minister = _active_minister(game)
    game.state.turn_phase = TurnPhase.SUMMONING.value  # 锁前快速查通过
    nights0 = _count(game.db, "audience_nights")
    turns0 = _count(game.db, "chat_turns")

    game._write_gate.acquire()  # 模拟结算 worker 持锁
    result: dict = {}

    def run():
        result["events"] = list(game.chat_stream(minister, "边饷如何？"))

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(0.2)  # chat_stream 已过锁前快速查、阻塞在 write_gate.acquire()
    # 结算把相位翻到亲裁，再放锁 → chat_stream 抢到 gate 后权威复查须拒
    game.state.turn_phase = TurnPhase.AWAITING_DECISION.value
    game._write_gate.release()
    worker.join(3.0)

    assert not worker.is_alive()
    events = result["events"]
    assert events and events[-1]["type"] == "error"
    assert "结算" in events[-1]["message"] or "亲裁" in events[-1]["message"]
    # 未建任何夜 / chat turn
    assert _count(game.db, "audience_nights") == nights0
    assert _count(game.db, "chat_turns") == turns0
    assert an.get_open_night(game.db) is None


# ── ⑤ 拟诏 preview 不收夜（真实 /api/decree/write）───────────────────────
def test_write_decree_preview_does_not_close_night(web_game, monkeypatch):
    game = web_game
    minister = _active_minister(game)
    game.session.registry.get = lambda ch: _FakeAgent()
    list(game.chat_stream(minister, "边饷如何？"))  # 开夜 + 入档
    night = an.get_open_night(game.db)
    assert night is not None and night["status"] == "open"

    # 一条已 draft 候选（应允/默认同意路径），使拟诏有草案可 preview
    game.db.upsert_pending_directive(
        game.state.turn, minister, payload={"text": "着户部核边饷", "actor": minister})
    game.db.commit_pending_actions(game.state, kind_filter="directive")
    monkeypatch.setattr(session_mod, "write_decree_with_agno", lambda *a, **k: "奉天承运，诏曰……")

    # 真实 /api/decree/write（async def）
    payload = asyncio.run(web_app.api_write_decree())
    assert "诏" in payload["decree"]
    # 拟诏是 preview：夜仍开、无收夜账
    assert an.get_night(game.db, night["id"])["status"] == "open"
    closes = [e for e in an.list_ledger(game.db, night["id"]) if an.TAG_CLOSE_NIGHT in (e.get("tags") or [])]
    assert closes == []
