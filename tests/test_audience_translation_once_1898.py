"""#1898：收夜待补转译同夜只跑一次。

钉：
1. 首次补跑耗尽 → 同次收夜**无第二处自动调用**（模型调用次数 == 待补轮数），
   收夜仍成案（CLOSED），该轮保持待补、不阻断退朝。
2. 首次补跑成功 → 该轮标 done，收夜成案；不因删第二处而漏补。
3. 恢复口不删：进来时已是 CLOSING（收夜中断后重开）的收夜仍走补跑。
4. 补跑权仍在别处：#1846 的按轮重试入口（catch_up 按 chat_turn_id 收窄）
   照旧能把待补轮补成 done——本切片只删同次收夜的重复调用。
"""

from __future__ import annotations

from ming_sim import audience_night as an
from ming_sim.session_write_queue import SessionWriteQueue
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


def test_successful_catch_up_still_marks_done(game):
    """删第二处不得漏补：首次补跑成功即 done，成案有账。"""
    db, state, content = game
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister, reply="臣作保。")
    calls: list[int] = []

    def translate_fn(prompt, llm_config):
        calls.append(1)
        return {
            "scene_facts": [{
                "body": "臣作保。", "role": "minister",
                "audibility": "殿上公开", "person_names": [minister], "tags": [],
            }],
        }

    result = _close(db, state, night_id=nid, translate_fn=translate_fn)

    assert len(calls) == 1, calls
    assert result["closed"] is True
    assert db.get_story_extract_status(ctid) == "done"
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries "
        "WHERE night_id=? AND source_chat_turn_id=?",
        (nid, ctid),
    ).fetchone()["c"] >= 1


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


def test_player_retry_still_heals_pending_after_close(game):
    """耗尽后玩家重试（#1846 按轮入口）仍能把该轮补成 done。"""
    from ming_sim.audience_translation import catch_up_pending_translations

    db, state, content = game
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister, reply="臣愿承办。")

    def boom(prompt, llm_config):
        raise RuntimeError("translate exhausted")

    _close(db, state, night_id=nid, translate_fn=boom)
    assert str(db.get_story_extract_status(ctid) or "") in ("", "pending")

    def heal(prompt, llm_config):
        return {
            "scene_facts": [{
                "body": "臣愿承办。", "role": "minister",
                "audibility": "殿上公开", "person_names": [minister], "tags": [],
            }],
        }

    q = SessionWriteQueue()
    summary = catch_up_pending_translations(
        db, state, chat_turn_id=ctid, llm_config=object(),
        translate_fn=heal, write_gate=q.write_gate, write_queue=q,
    )
    assert int(summary["extracted"]) == 1
    assert db.get_story_extract_status(ctid) == "done"
