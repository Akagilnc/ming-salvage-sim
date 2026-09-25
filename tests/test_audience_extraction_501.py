"""#501 仍现役的召对转译补跑边界。"""

from __future__ import annotations

from ming_sim import audience_night as an


def _minister(db, content) -> str:
    from tests.conftest import active_ming_character

    return active_ming_character(db, content)


def _open_night_with_persisted_reply(db, state, minister, reply="臣愿肩起此事。"):
    """持久化夜内完整回话但不转译，制造现役待补输入。"""
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    an.ensure_summon_enter(db, nid, minister)
    ctid = db.create_chat_turn(state, minister, "sess", 0, night_id=nid)
    db.persist_minister_reply(minister, int(state.turn), reply, ctid)
    return nid, ctid


def test_engine_close_night_drains_pending_success(game, monkeypatch):
    """收夜 join 转译 catch-up 清待补。"""
    db, state, content = game
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister, reply="臣作保。")
    assert db.count_pending_story_extractions(night_id=nid) == 1

    def translate_fn(prompt, llm_config):
        return {
            "scene_facts": [{
                "body": "臣作保。",
                "role": "minister",
                "audibility": "殿上公开",
                "person_names": [minister],
                "tags": [],
            }],
        }

    from ming_sim.session_write_queue import SessionWriteQueue
    write_queue = SessionWriteQueue()
    result = an.close_night(
        db, state, night_id=nid, llm_config=object(),
        write_gate=write_queue.write_gate, write_queue=write_queue,
        translate_fn=translate_fn,
    )
    assert result["closed"] is True
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED
    assert db.get_story_extract_status(ctid) == "done"
    assert db.conn.execute(
        "SELECT COUNT(*) AS c FROM story_ledger_entries "
        "WHERE night_id=? AND source_chat_turn_id=?",
        (nid, ctid),
    ).fetchone()["c"] >= 1


def test_engine_close_night_without_deps_keeps_pending_no_fail_closed(
    game, tmp_path, monkeypatch,
):
    """无 llm/write_gate 时待补保留，不 fail-closed。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setattr(
        "ming_sim.audience_extraction.extract_endorsements_for_night",
        lambda **k: [],
    )
    minister = _minister(db, content)
    nid, ctid = _open_night_with_persisted_reply(db, state, minister)
    an.close_night(db, state, night_id=nid)
    assert db.count_pending_story_extractions(night_id=nid) >= 1
    assert str(db.get_story_extract_status(ctid) or "") in ("", "pending")
