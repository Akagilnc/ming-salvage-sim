"""Test helpers that stage pending actions without the retired classifier chain.

#1871 deleted apply_cli_conversation_actions / intent classifier. Downstream
settle/transaction tests still need a deterministic way to plant pending rows
and close them into dossiers.
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim import audience_night
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline


def active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


# Back-compat alias used by older imports.
_active_minister_name = active_minister_name


def _ctx(db, character, candidates, turn, *, message, reply):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def stage_punishment(db, turn, target, *, action="拿问下狱", amount=0, message=None, reply=None):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "punishment",
        "punish_action": action,
        "transaction_category": "缉拿",
        "name": target,
    }
    if amount:
        payload["amount"] = amount
    candidate = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor, candidate, turn,
        message=message or f"将{target}{action}。",
        reply=reply or f"臣请将{target}{action}，请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


# Back-compat aliases
_stage_punishment = stage_punishment
_close_night_dossier = close_night_dossier


def stage_yuan_appointment_summon(
    game, monkeypatch=None, *, summon_after="是", appt_name="袁崇焕",
    office="辽东巡抚", region_id="", player_message=None,
    ban_appointment_extract=False,
):
    """Materialize appointment pending (no classifier LLM). Flags kept for call-site compat."""
    del monkeypatch, ban_appointment_extract
    db, state, content = game
    minister = active_minister_name(db, content)
    audience_night.open_night(db, state, empty_scaffold=True)
    spoken = player_message or f"起复{appt_name}为{office}，传召入京。"
    seat = str(region_id or "").strip() or {
        "巡抚登莱": "shandong",
        "辽东巡抚": "liaodong",
        "陕西三边总督": "shaanxi",
    }.get(str(office or "").strip(), "")
    intent = {
        "kind": "appointment", "appoint_action": "任命",
        "name": appt_name, "office": office, "summon_after": summon_after,
    }
    if seat:
        intent["region_id"] = seat
    candidates = candidates_from_classifier_payload(intent, soft=False)
    ctx = _ctx(
        db, minister, candidates, int(state.turn),
        message=spoken, reply="遵旨。",
    )
    run_materialize_pipeline(ctx)
    pending = next(row for row in db.list_pending_actions(state.turn) if row["kind"] == "office")
    return pending, f"office:{pending['id']}"


def close_office_to_dossier(db, state, content, pending_id):
    db.mark_pending_night_approved(
        [pending_id], night_id=int(audience_night.get_open_night(db)["id"]),
    )
    audience_night.close_night(
        db, state, night_id=int(audience_night.get_open_night(db)["id"]),
        content=content,
    )
    return next(
        row["id"] for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == int(pending_id)
    )


def yuan_row(db, name="袁崇焕"):
    return db.conn.execute(
        "SELECT status, office, location, transit_to, transit_distance_remaining, "
        "transit_speed_factor, transit_start_turn FROM characters WHERE name=?",
        (name,),
    ).fetchone()


# Back-compat aliases
_stage_yuan_appointment_summon = stage_yuan_appointment_summon
_close_office_to_dossier = close_office_to_dossier
_yuan_row = yuan_row
