"""#1898：关档重开经真实 WebGame 入口补跑待补转译（ADR 0036 恢复接缝）。

钉：重开补跑走票据写闸真源，票据排空后待补轮转 done 且落账成行；再次重开
不增副本（恢复是补跑，不是重复落账）。

旧码把 TicketedWriteGate 传给只收 ClassifiedWriteGate 的 catch_up，重开补跑
整体哑掉（待补永不转 done）而日志只留一行。

同核的收夜行为断言（耗尽同次不二试、CLOSING 恢复口续收）已并入既有行为案
tests/test_qa_t1_extraction_dual_source_1353.py，此处不复制。
"""

from __future__ import annotations

from contextlib import contextmanager

import web_app
from ming_sim import audience_night as an
from tests.conftest import stub_audience_translate
from tests.test_audience_extraction_501 import _minister


def _ledger_rows(game, nid, ctid) -> int:
    return int(game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries "
        "WHERE night_id=? AND source_chat_turn_id=?",
        (nid, ctid),
    ).fetchone()["c"])


# 释放前排空的上限：只在清理路径用，失败时不追加断言（正文红字才是结论）。
_CLOSE_DRAIN_TIMEOUT_S = 30


@contextmanager
def _open_webgame(*, fresh: bool):
    """开一个 WebGame 并保证释放：setup 之后任何失败都不漏连接（#1898 判官）。

    排空与关连接都在 finally：断言红在 setup 中途也要走到这里。排空有限时，
    真挂死不在清理里拖住整个用例。
    """
    game = web_app.WebGame(fresh=fresh)
    try:
        yield game
    finally:
        try:
            game._runtime_write_queue().wait_idle(timeout_s=_CLOSE_DRAIN_TIMEOUT_S)
        finally:
            game.session.close()


def test_reopen_webgame_catches_up_pending_translation(tmp_path, monkeypatch):
    """恢复接缝真源：关档重开经真实 WebGame 入口补跑待补转译（ADR 0036）。"""
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])

    with _open_webgame(fresh=True) as first:
        minister = _minister(first.db, first.content)
        stub_audience_translate(monkeypatch, lambda *_a, **_k: {
            "scene_facts": [{
                "body": "臣领旨。", "role": "minister",
                "audibility": "殿上公开", "person_names": [minister], "tags": [],
            }],
        })
        night = an.open_night(first.db, first.state, location="乾清宫", time_of_day="夜")
        nid = int(night["id"])
        ctid = first.db.create_chat_turn(first.state, minister, "sess", 0, night_id=nid)
        first.db.persist_minister_reply(minister, int(first.state.turn), "臣领旨。", ctid)
        first.db.mark_story_extraction_pending(ctid)
        an._set_night_fields(first.db, nid, status=an.NIGHT_STATUS_CLOSING)
        first.db.conn.commit()

    with _open_webgame(fresh=False) as reopened:
        # 排空走队列唯一真源 wait_idle（禁另造轮询/sleep 排空）。
        assert reopened._runtime_write_queue().wait_idle(), "重开补跑票据未排空"
        assert reopened.db.get_story_extract_status(ctid) == "done"
        assert _ledger_rows(reopened, nid, ctid) >= 1

    # 再次重开不增副本（恢复是补跑，不是重复落账）。
    with _open_webgame(fresh=False) as again:
        assert again._runtime_write_queue().wait_idle(), "重开补跑票据未排空"
        assert _ledger_rows(again, nid, ctid) == 1
