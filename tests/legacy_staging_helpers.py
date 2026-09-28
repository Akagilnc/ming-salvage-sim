"""Test helpers that stage pending actions without the retired classifier chain.

#1871 deleted apply_cli_conversation_actions / run_materialize_pipeline.
Downstream settle/transaction tests plant pending rows via shared stage_* seams
or direct db.stage_pending_action.
"""

from __future__ import annotations

from ming_sim import audience_night
from ming_sim.action_materialize import stage_punishment_candidate


def active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


_active_minister_name = active_minister_name


class _PunishmentStageResult:
    """Duck-type former MaterializeCtx.out for transaction tests."""

    def __init__(self, pending_action_id: int):
        self.out = {"pending_action_id": int(pending_action_id or 0)}


def stage_punishment(db, turn, target, *, action="拿问下狱", amount=0, message=None, reply=None):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    body = message or f"将{target}{action}。"
    if reply:
        body = f"{body}\n{reply}"
    pending_id = stage_punishment_candidate(
        db, int(turn), actor,
        text=body,
        target_id=str(target),
        punish_action=str(action),
        amount=amount,
    )
    return _PunishmentStageResult(pending_id)


def close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


_stage_punishment = stage_punishment
_close_night_dossier = close_night_dossier


def stage_yuan_appointment_summon(
    game, monkeypatch=None, *, summon_after="是", appt_name="袁崇焕",
    office="辽东巡抚", region_id="", player_message=None,
    ban_appointment_extract=False,
):
    del monkeypatch, ban_appointment_extract, player_message
    db, state, content = game
    minister = active_minister_name(db, content)
    audience_night.open_night(db, state, empty_scaffold=True)
    seat = str(region_id or "").strip() or {
        "巡抚登莱": "shandong",
        "辽东巡抚": "liaodong",
        "陕西三边总督": "shaanxi",
    }.get(str(office or "").strip(), "")
    payload = {
        "appoint_action": "任命",
        "name": appt_name,
        "office": office,
        "summon_after": summon_after,
    }
    if seat:
        payload["region_id"] = seat
    pending_id = db.stage_pending_action(
        int(state.turn), kind="office", action="任命",
        minister_name=minister, target_id=None, payload=payload,
    )
    pending = next(
        row for row in db.list_pending_actions(state.turn)
        if int(row["id"]) == int(pending_id)
    )
    return pending, f"office:{pending['id']}"


def close_office_to_dossier(db, state, content, pending_id):
    """Mark night-approved and close; office pending becomes appointment dossier."""
    night = audience_night.get_open_night(db)
    assert night is not None, "need open night to close office pending"
    nid = int(night["id"])
    # ensure pending is attached to this night
    db.conn.execute(
        "UPDATE pending_actions SET night_id=?, night_approved=1 WHERE id=?",
        (nid, int(pending_id)),
    )
    db.conn.commit()
    audience_night.close_night(db, state, night_id=nid, content=content)
    dossiers = [
        row for row in db.list_decree_dossiers()
        if int(row.get("pending_action_id") or 0) == int(pending_id)
    ]
    if not dossiers:
        # fallback: commit path used by some office kinds
        db.commit_pending_actions(state, content=content, action_ids=[int(pending_id)])
        dossiers = [
            row for row in db.list_decree_dossiers()
            if int(row.get("pending_action_id") or 0) == int(pending_id)
        ]
    assert dossiers, f"office pending {pending_id} produced no dossier after close"
    return int(dossiers[0]["id"])


def yuan_row(db, name="袁崇焕"):
    return db.conn.execute(
        "SELECT status, office, location, transit_to, transit_distance_remaining, "
        "transit_speed_factor, transit_start_turn FROM characters WHERE name=?",
        (name,),
    ).fetchone()


_stage_yuan_appointment_summon = stage_yuan_appointment_summon
_close_office_to_dossier = close_office_to_dossier
_yuan_row = yuan_row
