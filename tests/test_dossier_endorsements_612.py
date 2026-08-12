import json
import threading

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_extraction import run_extraction_for_turn
from ming_sim.db import GameDB
from ming_sim.decree import build_promulgation_judge_context


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _night_reply(db, state, minister):
    night_id = int(an.open_night(db, state, location="乾清宫", time_of_day="夜")["id"])
    an.ensure_summon_enter(db, night_id, minister)
    chat_turn_id = db.create_chat_turn(
        state, minister, "endorsement-612", 0, night_id=night_id,
    )
    db.persist_minister_reply(minister, state.turn, "臣愿会签此旨。", chat_turn_id)
    row = db.conn.execute("SELECT night_seq FROM chat_turns WHERE id=?", (chat_turn_id,)).fetchone()
    return night_id, chat_turn_id, int(row["night_seq"] or 0)


class _Agent:
    def __init__(self, payload):
        self.payload = payload

    def run(self, _materials):
        return json.dumps(self.payload, ensure_ascii=False)


def test_spoken_cosign_is_persisted_restored_and_read_by_promulgation_judge(game):
    db, state, content = game
    minister = _minister(db)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清核辽饷",
        target_kind="issue", target_id="liao-pay",
    )
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    result = run_extraction_for_turn(
        db=db, minister_name=minister, reply="臣愿会签此旨。",
        chat_turn_id=chat_turn_id, night_id=night_id, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_Agent({"facts": [{
            "body": "大臣当殿愿为辽饷旨意会签。", "person_names": [minister],
            "tags": ["会签"], "endorsement": {
                "dossier_id": dossier_id, "form": "会签", "endorser_id": minister,
            },
        }]}),
    )
    assert result["status"] == "done"
    expected = [{
        "id": 1, "dossier_id": dossier_id, "form": "会签",
        "endorser_id": minister, "imperial": False,
        "source_chat_turn_id": chat_turn_id,
    }]
    assert db.list_dossier_endorsements(dossier_id) == expected
    context = build_promulgation_judge_context(db, state, db.list_decree_dossiers())
    assert context["dossiers"][0]["endorsements"] == expected
    assert context["dossiers"][0]["criteria_snapshot_source"]["endorsement_entry_ids"] == [1]

    reopened = GameDB(db.path, content=content)
    try:
        assert reopened.list_dossier_endorsements(dossier_id) == expected
    finally:
        reopened.close()


def test_imperial_hand_endorsement_is_captured_without_authority_suppression(game):
    db, state, _content = game
    minister = _minister(db)
    state.metrics["皇威"] = 100
    dossier_id = db.create_decree_dossier(
        state, action_type="appointment", decree_text="擢任兵部侍郎",
        target_kind="character", target_id=minister,
    )
    night_id, chat_turn_id, seq = _night_reply(db, state, minister)
    run_extraction_for_turn(
        db=db, minister_name=minister, reply="朕亲书手敕为此旨作保。",
        chat_turn_id=chat_turn_id, night_id=night_id, source_night_seq=seq,
        llm_config=object(), write_gate=threading.Lock(),
        extractor_agent=_Agent({"facts": [{
            "body": "皇帝亲书手敕。", "endorsement": {
                "dossier_id": dossier_id, "form": "御笔手敕", "imperial": True,
            },
        }]}),
    )
    assert db.list_dossier_endorsements(dossier_id)[0]["form"] == "御笔手敕"


def test_endorsement_write_boundary_rejects_unknown_or_forward_dossier(game):
    db, state, _content = game
    minister = _minister(db)
    _night_id, chat_turn_id, _seq = _night_reply(db, state, minister)
    with pytest.raises(ValueError, match="案卷不存在"):
        db.add_dossier_endorsement(
            999999, form="会签", endorser_id=minister,
            source_chat_turn_id=chat_turn_id,
        )
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossier_endorsements").fetchone()[0] == 0
