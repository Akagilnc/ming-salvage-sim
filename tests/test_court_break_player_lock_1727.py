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
from types import SimpleNamespace

import httpx
import pytest

import ming_sim.agents as agents_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from tests.conftest import stub_audience_translate, stub_scene_agent


class _CannedExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


class _CannedEndorsementExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"endorsements":[]}')


class _CannedMindreadingAgent:
    def run(self, _material):
        return SimpleNamespace(content="近臣低声：边饷事重。")




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
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreadingAgent(),
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


def test_court_break_locks_player_writes_and_closes_night(web_game, monkeypatch):
    """#1727：真实退朝在 done 暴露前预领屏障，随后收夜。"""
    game = web_game
    minister = _active_minister(game)
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    agent = _StreamFarewellAgent()
    game.session.registry.get = lambda _ch, **_kw: agent
    stub_scene_agent(monkeypatch, agent)

    statuses: dict[str, int] = {}
    barrier_at_done: list[bool] = []

    class _DoneProbeQueue(web_app.queue.Queue):
        """在生产 worker 发布 done 的同步边界观察外部写入口。"""

        def put(self, item, *args, **kwargs):
            if item.get("type") == "done":
                barrier_at_done.append(game._runtime_write_queue().has_open_barrier())
                if not barrier_at_done[-1]:
                    return super().put(item, *args, **kwargs)
                async def _probe() -> dict[str, int]:
                    async with _client() as client:
                        requests = {
                            "chat": client.post(
                                f"/api/ministers/{minister}/chat",
                                json={"message": "再问边饷？"},
                            ),
                            "undo": client.post(f"/api/ministers/{minister}/chat/undo"),
                            "secret_order": client.post(
                                f"/api/ministers/{minister}/secret_order",
                                json={"title": "边饷", "content": "速办边饷"},
                            ),
                            "withdraw": client.post("/api/pending_actions/1/withdraw"),
                        }
                        return {
                            name: (await request).status_code
                            for name, request in requests.items()
                        }

                statuses.update(asyncio.run(_probe()))
            return super().put(item, *args, **kwargs)

    monkeypatch.setattr(web_app.queue, "Queue", _DoneProbeQueue)

    async def _run_stream() -> list[dict]:
        async with _client() as client:
            resp = await client.post(
                f"/api/ministers/{minister}/chat/stream",
                json={"message": "退朝"},
            )
            assert resp.status_code == 200, resp.text
            return _parse_sse_chunk(resp.text)

    stream_events = asyncio.run(_run_stream())

    types = [str(ev.get("event") or "") for ev in stream_events]
    assert "error" not in types, stream_events
    assert "done" in types, stream_events
    assert "end" in types, stream_events
    done_raw = next(ev for ev in stream_events if ev.get("event") == "done").get("data") or "{}"
    done_payload = json.loads(done_raw) if isinstance(done_raw, str) else done_raw
    assert isinstance(done_payload, dict), done_payload
    assert done_payload.get("court_action") == "court_break", done_payload
    assert barrier_at_done == [True]
    assert statuses == {
        "chat": 409,
        "undo": 409,
        "secret_order": 409,
        "withdraw": 409,
    }
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
    # 告退轮仍在：undo 被拒，玩家发话与中性戏文仍归同一轮。
    user_turn_ids = {
        int(m["chat_turn_id"]) for m in scroll
        if m.get("role") == "user" and m.get("chat_turn_id")
    }
    assert any(
        m.get("role") != "user"
        and int(m.get("chat_turn_id") or 0) in user_turn_ids
        and m.get("beat") == "dialogue"
        for m in scroll
    ), scroll
