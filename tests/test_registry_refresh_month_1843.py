"""#672 acceptance migrated from retired materializer suites to the player month chain."""

import pytest

from ming_sim.decree_forecast import decree_ref_for_dossier
from tests.test_month_chain_1843 import _prepare_player_month


class _Registry:
    def __init__(self):
        self.refreshed = []

    def refresh(self, name):
        self.refreshed.append(name)


def _promulgate_in_player_month(db, state, content, monkeypatch, dossier_id):
    dossier = db.get_decree_dossier(dossier_id)
    db.staged_declarations.stage(
        decree_ref=decree_ref_for_dossier(db, dossier), declaration={},
        turn=int(state.turn), verdict={"decision": "promulgated"}, forecast_text="",
    )
    registry = _Registry()
    session = _prepare_player_month(db, state, content, monkeypatch)
    session.registry = registry
    session.resolve_turn(allow_empty_decree=True)
    return registry


@pytest.mark.parametrize("action", ["punishment", "pacification", "military_order"])
def test_player_month_promulgation_refreshes_changed_person(game, monkeypatch, action):
    db, state, content = game
    if action == "pacification":
        name = "张献忠"
        db.conn.execute("UPDATE characters SET status='active' WHERE name=?", (name,))
        content.characters[name].status = "active"
        payload = {"target_id": name, "text": "招抚归明"}
        target_kind, target_id = "character", name
    else:
        name = next(
            ch.name for ch in content.characters.values()
            if db.get_character_status(ch.name)[0] == "active"
            and db.resolve_power_id(ch) == "ming" and str(ch.office or "").strip()
        )
        if action == "punishment":
            payload = {"target_id": name, "punish_action": "拿问下狱", "text": "拿问下狱"}
            target_kind, target_id = "character", name
        else:
            payload = {"target_id": "xuan_da", "office": "大同总兵", "region_id": "shanxi", "text": "改任大同总兵"}
            target_kind, target_id = "army", "xuan_da"
    dossier_id = db.create_decree_dossier(
        state, action_type=action, decree_text=str(payload["text"]),
        target_kind=target_kind, target_id=target_id,
        executor_kind="character", executor_id=name, payload=payload,
    )
    registry = _promulgate_in_player_month(db, state, content, monkeypatch, dossier_id)
    assert name in registry.refreshed
    if action == "punishment":
        assert db.get_character_status(name)[0] == "imprisoned"
    elif action == "pacification":
        assert db.conn.execute("SELECT power_id FROM characters WHERE name=?", (name,)).fetchone()[0] == "ming"
    else:
        assert db.conn.execute("SELECT office FROM characters WHERE name=?", (name,)).fetchone()[0] == "大同总兵"


def test_player_month_appointment_refreshes_displaced_holder(game, monkeypatch):
    db, state, content = game
    active = [
        ch for ch in content.characters.values()
        if db.resolve_power_id(ch) == "ming" and db.get_character_status(ch.name)[0] == "active"
        and str(ch.office or "").strip() and ch.office_type != "后宫"
    ]
    new_holder, partial = active[:2]
    db.conn.execute(
        "UPDATE characters SET office='兵部尚书,左都御史',office_type='兵部' WHERE name=?",
        (partial.name,),
    )
    db.conn.commit()
    content.characters[partial.name].office = "兵部尚书,左都御史"
    content.characters[partial.name].office_type = "兵部"
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=new_holder.name,
        target_id=None,
        payload={"text": "任兵部尚书", "name": new_holder.name, "office": "兵部尚书"},
    )
    db.commit_pending_actions(state, content=content, registry=None)
    dossier = next(
        row for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == pending_id
    )
    registry = _promulgate_in_player_month(db, state, content, monkeypatch, dossier["id"])
    assert {new_holder.name, partial.name} <= set(registry.refreshed)
    assert db.conn.execute("SELECT office FROM characters WHERE name=?", (partial.name,)).fetchone()[0] == "左都御史"


def test_pending_consort_cultivation_refreshes_after_commit(game):
    db, state, content = game
    consort = next(
        (ch for ch in content.characters.values()
         if ch.office_type == "后宫" and db.get_character_status(ch.name)[0] == "active"),
        None,
    )
    if consort is None:
        pytest.skip("基底无 active 后宫角色")
    db.stage_pending_action(
        state.turn, kind="consort", action="调教", minister_name=consort.name,
        target_id=None, payload={"name": consort.name, "skill": "理财", "trait": ""},
    )
    registry = _Registry()
    db.commit_pending_actions(state, content=content, registry=registry)
    assert consort.name in registry.refreshed
    assert "理财" in (db.get_consort_traits(consort.name).get("extra_skills") or [])
