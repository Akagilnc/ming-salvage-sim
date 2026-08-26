import json

import ming_sim.cli_backend as cb
import ming_sim.audience_night as audience_night
from ming_sim.audience_night import list_unsettled_summons, open_night
from ming_sim.session import GameSession
from ming_sim.decree import prepare_resolve_front_half, settle_with_delta
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

    db.mark_pending_night_approved(
        [pending["id"]], night_id=int(audience_night.get_open_night(db)["id"]),
    )
    audience_night.close_night(
        db, state, night_id=int(audience_night.get_open_night(db)["id"]),
        content=content,
    )
    dossier_id = next(
        row["id"] for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
    )
    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
    )

    assert [(x["person_name"], x["origin_id"], x["kind"]) for x in list_unsettled_summons(db)] == [
        ("袁崇焕", origin, "in_transit")
    ]
    row = db.conn.execute(
        "SELECT status,transit_to FROM characters WHERE name='袁崇焕'"
    ).fetchone()
    assert (row["status"], row["transit_to"]) == ("active", "beizhili")

    for _ in range(60):
        if list_unsettled_summons(db)[0]["kind"] == "waiting":
            break
        prepare_resolve_front_half(state, db, content=content)
        settle_with_delta(
            state, db, {}, before_turn=int(state.turn), content=content,
        )
    assert list_unsettled_summons(db)[0]["kind"] == "waiting"


def test_appointment_summon_staging_rolls_back_both_rows(game, monkeypatch):
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    monkeypatch.setattr(
        audience_night, "ensure_inactive_office_summon",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger failed")),
    )

    try:
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state, content), minister,
            player_message="任命并传召", answer="遵旨。", has_directive=False,
            secret_order_id=None, preclassified_intent=[{
                "kind": "appointment", "appoint_action": "任命",
                "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是",
            }],
        )
    except RuntimeError as exc:
        assert str(exc) == "ledger failed"
    else:
        raise AssertionError("ledger failure must propagate")
    assert [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"] == []


def test_dedup_promotes_existing_appointment_summon(game, monkeypatch):
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    session = _fake_session(db, state, content)
    base = {
        "kind": "appointment", "appoint_action": "任命",
        "name": "袁崇焕", "office": "辽东巡抚",
    }
    for summon_after in ("否", "是"):
        GameSession.apply_cli_conversation_actions(
            session, minister, player_message="任命并传召", answer="遵旨。",
            has_directive=False, secret_order_id=None,
            preclassified_intent=[dict(base, summon_after=summon_after)],
        )

    rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
    assert len(rows) == 1
    assert json.loads(rows[0]["payload_json"])["summon_after"] == "是"
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?",
        (f"office:{rows[0]['id']}",),
    ).fetchone()[0] == 1
