import json

import ming_sim.cli_backend as cb
from ming_sim.audience_night import list_unsettled_summons, open_night
from ming_sim.session import GameSession
from tests.dossier_test_helpers import promulgate_proposed_appointments
from tests.test_qa_c_p0_1380_1355 import _fake_session, _minister_wang_shaohui


def test_appointment_summon_activates_only_after_promulgation(game, monkeypatch):
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))

    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message="起复袁崇焕为辽东巡抚，传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "任命",
            "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是",
        }],
    )
    pending = next(row for row in db.list_pending_actions(state.turn) if row["kind"] == "office")
    origin = f"office:{pending['id']}"
    ledger = db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()
    assert ledger is not None and "传召未结" not in json.loads(ledger["tags"])
    assert list_unsettled_summons(db) == []

    db.commit_pending_actions(state, content=content, registry=None)
    promulgate_proposed_appointments(db, state, content)

    assert [(x["person_name"], x["origin_id"], x["kind"]) for x in list_unsettled_summons(db)] == [
        ("袁崇焕", origin, "in_transit")
    ]
    row = db.conn.execute(
        "SELECT status,transit_to FROM characters WHERE name='袁崇焕'"
    ).fetchone()
    assert (row["status"], row["transit_to"]) == ("active", "beizhili")
