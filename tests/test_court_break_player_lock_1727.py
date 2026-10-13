from __future__ import annotations
import asyncio
from types import SimpleNamespace
import httpx
import web_app
from ming_sim import audience_night as an
from tests.conftest import stub_scene_agent
from tests.sse_helpers import parse_sse_event_pairs as _parse_sse_chunk
"""#1727：court_break 后 done→end 窗口内召对写入口必须落幕。

常绿验收（fix 后一直绿）：
- done.payload.court_action == court_break
- done 之后、end 之前，并发召对写入口不可再用（HTTP/SSE 外部可见拒）
- end 之后夜 closed（#1838：无 exit/divider/closing 收尾旁白三拍）
- 复用 #1353 屏障票作玩家写入口外可见锁；不另造平行写队列

D2/D3 是病因钉，修好后不要求常绿——本文件不收录。
"""






class _StreamFarewellAgent:
    def run(self, *_a, **_k):
        yield SimpleNamespace(event="RunContent", content="臣告退。")
        yield SimpleNamespace(content="", tools=[])

    def get_last_run_output(self):
        return None




def _active_minister(game) -> str:
    for name, ch in game.content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if game.db.characters.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no active ming minister")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_app.app),
        base_url="http://t",
    )




def _named_scene_beats(scroll) -> list[str]:
    return [m["beat"] for m in scroll if m["beat"] not in {"coda", ""}]


def test_court_break_locks_player_writes_and_closes_night(web_game, monkeypatch):
    """#1727：真实退朝在 done 暴露前预领屏障，随后收夜。"""
    game = web_game
    _active_minister(game)
    night = an.open_night(game.db, game.state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    agent = _StreamFarewellAgent()
    stub_scene_agent(monkeypatch, agent)

    statuses: dict[str, int] = {}
    chat_accepted: list[int] = []
    chat_terminal: list[dict] = []
    barrier_at_done: list[bool] = []

    class _DoneProbeQueue(web_app.queue.Queue):
        """在生产 worker 发布 done 的同步边界观察外部写入口。"""

        def put(self, item, *args, **kwargs):
            if item.get("type") == "done":
                barrier_at_done.append(game._runtime_write_queue().has_open_barrier())
                if not barrier_at_done[-1]:
                    return super().put(item, *args, **kwargs)
                async def _probe() -> dict[str, int]:
                    # #1902：非流式召对入口退役，说话只有流式一条。屏障守的是玩家写
                    # 入口本身：流式请求在屏障窗内照发 200，拒收落在 SSE 终态——故此处
                    # 必须把流消费到终态并断言那条结构化拒收（#1727 承诺的
                    # 「HTTP/SSE 外部可见拒」）；只看 200 等于什么都不证明。
                    async with _client() as client:
                        chat = await client.post(
                            "/api/audience/chat/stream",
                            json={"message": "再问边饷？"},
                        )
                        undo = await client.post("/api/audience/chat/undo")
                        chat_accepted.append(chat.status_code)
                        chat_terminal.append(next({"event": kind, "data": data} for kind, data in reversed(_parse_sse_chunk(chat.text)) if kind in ("done", "error")))
                        return {"undo": undo.status_code}

                statuses.update(asyncio.run(_probe()))
            return super().put(item, *args, **kwargs)

    monkeypatch.setattr(web_app.queue, "Queue", _DoneProbeQueue)

    async def _run_stream() -> list[dict]:
        async with _client() as client:
            resp = await client.post(
                "/api/audience/chat/stream",
                json={"message": "退朝"},
            )
            assert resp.status_code == 200, resp.text
            return _parse_sse_chunk(resp.text)

    stream_events = asyncio.run(_run_stream())

    types = [name for name, _ in stream_events]
    assert "error" not in types, stream_events
    assert "done" in types, stream_events
    assert "end" in types, stream_events
    done_payload = next(data for name, data in stream_events if name == "done")
    assert isinstance(done_payload, dict), done_payload
    assert done_payload.get("court_action") == "court_break", done_payload
    assert barrier_at_done == [True]
    # #1902：召对只有流式一条，屏障窗内受理（200）但拒收在终态；undo 同步 409。
    assert statuses == {"undo": 409}, statuses
    assert chat_accepted == [200], chat_accepted
    # 负向契约在终态里：屏障窗内的召对必须是那条结构化拒收，不得出现成功 done/end。
    assert len(chat_terminal) == 1, chat_terminal
    assert chat_terminal[0]["event"] == "error", chat_terminal
    assert chat_terminal[0]["data"].get("code") == "night_closing", chat_terminal
    # end 后终态：夜 closed；#1838 reopen 无 closing/exit/divider 收尾旁白三拍。
    row = game.db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert row is not None
    assert str(row["status"]) == an.NIGHT_STATUS_CLOSED, dict(row)
    assert an.get_open_night(game.db) is None
    scroll = an.read_night_scroll(game.db, night_id)
    beats = _named_scene_beats(scroll)
    assert "closing" not in beats and "coda" not in beats, beats
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
