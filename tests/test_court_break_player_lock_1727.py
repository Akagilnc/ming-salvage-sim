"""#1727：court_break 后 done→end 窗口内召对写入口必须落幕。

常绿验收（fix 后一直绿）：
- done.payload.court_action == court_break
- done 之后、end 之前，并发召对写入口不可再用（HTTP/SSE 外部可见拒）
- end 之后夜 closed，且 exit/divider/closing 三拍均在
- 复用 #1353 屏障票作玩家写入口外可见锁；不另造平行写队列

D2/D3 是病因钉，修好后不要求常绿——本文件不收录。
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

import ming_sim.agents as agents_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from tests.test_month_loop_tracer_1468 import _install_trail_hold


class _CannedExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


class _CannedEndorsementExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"endorsements":[]}')


class _CannedMindreadingAgent:
    def run(self, _material):
        return SimpleNamespace(content="近臣低声：边饷事重。")


class _CannedRelationJudge:
    def run(self, _prompt):
        return SimpleNamespace(content='{"events":[]}')


class _StreamFarewellAgent:
    def run(self, *_a, **_k):
        yield SimpleNamespace(event="RunContent", content="臣告退。")
        yield SimpleNamespace(content="", tools=[])

    def get_last_run_output(self):
        return None


@pytest.fixture
def web_game(tmp_path, monkeypatch, _offline_scene_beat_generator):
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _CannedExtractor(),
    )
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreadingAgent(),
    )
    monkeypatch.setattr(
        agents_mod, "create_relation_judge_agent",
        lambda *a, **k: _CannedRelationJudge(),
    )
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    # stream worker 在 payload 前启动 _start_cli_action_intent → 真 classify LLM；
    # 本测只钉写入口锁，动作意图分类确定性空返，禁真网。
    monkeypatch.setattr(
        session_mod.GameSession, "_start_cli_action_intent",
        lambda self, *_a, **_k: None,
    )
    monkeypatch.setattr(
        session_mod.GameSession, "_finish_cli_action_intent",
        lambda self, *_a, **_k: None,
    )
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


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app.app),
        base_url="http://t",
    )


def _parse_sse_chunk(buf: str) -> list[dict]:
    events: list[dict] = []
    for block in buf.split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur.get("event"):
            events.append(cur)
    return events


def _named_scene_beats(scroll) -> list[str]:
    return [m["beat"] for m in scroll if m["beat"] not in {"coda", ""}]


def test_court_break_locks_player_write_between_done_and_end(web_game):
    """#1727 常绿：done(court_break) 后写入口锁；end 后 closed + exit/divider/closing。

    观测形态（#498 ASGI 在飞）：尾随 hold 拉长 done→end 窗；claim_barrier 接缝
    一置位即并发 POST /chat——断言外部 409，不依赖 SSE 半流缓冲时序。
    """
    game = web_game
    minister = _active_minister(game)
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    game.session.registry.get = lambda _ch: _StreamFarewellAgent()

    trail_release = threading.Event()
    restore_trails = _install_trail_hold(game, trail_release)

    q = game._runtime_write_queue()
    barrier_claimed = threading.Event()
    real_claim = q.claim_barrier

    def _claim_and_signal():
        ticket = real_claim()
        barrier_claimed.set()
        return ticket

    q.claim_barrier = _claim_and_signal  # type: ignore[method-assign]

    stream_events: list[dict] = []
    stream_error: list[BaseException] = []
    concurrent_results: dict[str, dict] = {}

    def _run_stream() -> None:
        try:
            async def _go() -> None:
                async with _client() as client:
                    resp = await client.post(
                        f"/api/ministers/{minister}/chat/stream",
                        json={"message": "退朝"},
                    )
                    assert resp.status_code == 200, resp.text
                    stream_events.extend(_parse_sse_chunk(resp.text))

            asyncio.run(_go())
        except BaseException as exc:  # noqa: BLE001
            stream_error.append(exc)

    def _probe_when_barrier_open() -> None:
        barrier_claimed.wait()
        # hold 窗内：屏障已开、尾随未放行 → 召对写入口必须外部可见拒。
        assert q.has_open_barrier(), "预领屏障后 has_open_barrier 应为 True"
        async def _probe() -> None:
            async with _client() as client:
                probes = {
                    "chat": client.post(
                        f"/api/ministers/{minister}/chat",
                        json={"message": "再问边饷？"},
                    ),
                    # #1727 T1/T2：撤回本轮不得绕过屏障（亦防 cancel_key 抽空尾随票）。
                    "undo": client.post(f"/api/ministers/{minister}/chat/undo"),
                    # 同类补扫：secret_order 持闸兼容路亦须端点侧拒。
                    "secret_order": client.post(
                        f"/api/ministers/{minister}/secret_order",
                        json={"title": "边饷", "content": "速办边饷"},
                    ),
                    # pending withdraw 同属召对写入口族。
                    "withdraw": client.post("/api/pending_actions/1/withdraw"),
                }
                for name, awaitable in probes.items():
                    probe = await awaitable
                    concurrent_results[name] = {
                        "status": probe.status_code,
                        "body": probe.text,
                    }

        asyncio.run(_probe())
        trail_release.set()

    stream_thread = threading.Thread(target=_run_stream, daemon=True, name="1727-stream")
    probe_thread = threading.Thread(
        target=_probe_when_barrier_open, daemon=True, name="1727-probe",
    )
    try:
        stream_thread.start()
        probe_thread.start()
        probe_thread.join()
        stream_thread.join()
    finally:
        trail_release.set()
        q.claim_barrier = real_claim  # type: ignore[method-assign]
        restore_trails()

    assert not stream_error, stream_error
    assert not stream_thread.is_alive(), "stream 未在期限内结束"
    assert not probe_thread.is_alive(), "probe 未在期限内结束"
    assert barrier_claimed.is_set(), "未领 court_break 屏障票"

    types = [str(ev.get("event") or "") for ev in stream_events]
    assert "error" not in types, stream_events
    assert "done" in types, stream_events
    assert "end" in types, stream_events
    done_raw = next(ev for ev in stream_events if ev.get("event") == "done").get("data") or "{}"
    done_payload = json.loads(done_raw) if isinstance(done_raw, str) else done_raw
    assert isinstance(done_payload, dict), done_payload
    # D1 同形常绿：判词链无辜——done 已带 court_break。
    assert done_payload.get("court_action") == "court_break", done_payload
    # 写入口外可见锁：hold 窗内并发召对写入口结构化拒写（HTTP 409）；不锁呈现措辞。
    for name in ("chat", "undo", "secret_order", "withdraw"):
        assert concurrent_results.get(name, {}).get("status") == 409, (
            name, concurrent_results.get(name),
        )
    # end 后终态：夜 closed + 收尾三拍 + 告退轮仍在（未被 undo 抽空）。
    row = game.db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert row is not None
    assert str(row["status"]) == an.NIGHT_STATUS_CLOSED, dict(row)
    assert an.get_open_night(game.db) is None
    scroll = an.read_night_scroll(game.db, night_id)
    beats = _named_scene_beats(scroll)
    assert "exit" in beats and "divider" in beats and "closing" in beats, beats
    # 告退轮仍在：undo 被拒，未抽空本轮（结构化：minister 对话气泡带 chat_turn_id）。
    assert any(
        m.get("role") == "minister" and int(m.get("chat_turn_id") or 0) > 0
        for m in scroll
    ), scroll
