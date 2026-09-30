"""#1898：收夜待补转译同夜只跑一次。

钉：
1. 首次补跑耗尽 → 同次收夜**无第二处自动调用**（模型调用次数 == 待补轮数），
   收夜仍成案（CLOSED），该轮保持待补、不阻断退朝。
2. 恢复口不删：进来时已是 CLOSING（收夜中断后重开）的收夜仍走补跑。

成功补跑与玩家重试另有既有行为案覆盖（tests/test_audience_extraction_501.py
的收夜 drain、tests/test_web_audience_night_498.py 的真实 HTTP 重试），此处不复制。
"""

from __future__ import annotations

import time

import pytest

import web_app
from ming_sim import audience_night as an
from ming_sim.session_write_queue import SessionWriteQueue
from tests.conftest import stub_audience_translate
from tests.test_audience_extraction_501 import (
    _minister,
    _open_night_with_persisted_reply,
)


def _close(db, state, *, night_id, translate_fn, **extra):
    q = SessionWriteQueue()
    return an.close_night(
        db, state, night_id=int(night_id), llm_config=object(),
        write_gate=q.write_gate, write_queue=q, translate_fn=translate_fn,
        **extra,
    )


def test_exhausted_catch_up_runs_once_per_night_close(game):
    """耗尽轮：同次收夜只调一次模型；收夜成案、该轮保持待补。"""
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister, reply="臣愿领办。")
    calls: list[int] = []

    def boom(prompt, llm_config):
        calls.append(1)
        raise RuntimeError("translate exhausted")

    result = _close(db, state, night_id=nid, translate_fn=boom)

    assert len(calls) == 1, calls          # 旧码此处为 2（OPEN 分支 + drain）
    assert result["closed"] is True
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert str(db.get_story_extract_status(ctid) or "") in ("", "pending")

    from ming_sim.audience_translation import list_pending_translations
    assert [int(p["chat_turn_id"]) for p in list_pending_translations(db)] == [ctid]


def test_closing_restore_path_still_catches_up(game):
    """恢复口保留：进来时已是 CLOSING（收夜中断后重开）仍补跑待补轮。"""
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister, reply="臣遵旨。")
    an._set_night_fields(db, nid, status=an.NIGHT_STATUS_CLOSING)
    calls: list[int] = []

    def translate_fn(prompt, llm_config):
        calls.append(1)
        return {
            "scene_facts": [{
                "body": "臣遵旨。", "role": "minister",
                "audibility": "殿上公开", "person_names": [minister], "tags": [],
            }],
        }

    _close(db, state, night_id=nid, translate_fn=translate_fn)

    assert len(calls) == 1, calls
    assert db.get_story_extract_status(ctid) == "done"


def _drain(queue) -> None:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and queue.inflight_count() > 0:
        time.sleep(0.05)
    assert queue.inflight_count() == 0, "重开补跑票据未排空"


def _ledger_rows(game, nid, ctid) -> int:
    return int(game.db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries "
        "WHERE night_id=? AND source_chat_turn_id=?",
        (nid, ctid),
    ).fetchone()["c"])


def test_reopen_webgame_catches_up_pending_translation(tmp_path, monkeypatch):
    """恢复接缝真源：关档重开经真实 WebGame 入口补跑待补转译（ADR 0036）。

    旧码把 TicketedWriteGate 传给只收 ClassifiedWriteGate 的 catch_up，
    重开补跑整体哑掉（待补永不转 done）而日志只留一行。
    """
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])

    first = web_app.WebGame(fresh=True)
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
    first.session.close()
    del first

    reopened = web_app.WebGame(fresh=False)
    try:
        _drain(reopened._runtime_write_queue())
        assert reopened.db.get_story_extract_status(ctid) == "done"
        assert _ledger_rows(reopened, nid, ctid) >= 1
        reopened.session.close()
    finally:
        del reopened

    # 再次重开不增副本（恢复是补跑，不是重复落账）。
    again = web_app.WebGame(fresh=False)
    try:
        _drain(again._runtime_write_queue())
        assert _ledger_rows(again, nid, ctid) == 1
    finally:
        again.session.close()
