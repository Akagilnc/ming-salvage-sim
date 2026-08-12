from ming_sim.db import GameDB
import ming_sim.decree as decree_mod


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _dossier(db, state, assignee):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="清丈田亩",
        target_kind="issue", target_id="authority-fixture",
        payload={"assignee_id": assignee},
    )
    return db.get_decree_dossier(dossier_id)


def test_active_authority_survives_reopen_and_is_read_by_promulgation_judge(game):
    db, state, content = game
    assignee = _minister(db)
    authority_id = db.grant_authority(
        state, assignee, "便宜行事", "清丈田亩", effective_turn=state.turn,
    )
    dossier = _dossier(db, state, assignee)

    before = decree_mod.build_promulgation_judge_context(db, state, [dossier])
    db.close()
    restored = GameDB(db.path, content)
    restored_state = restored.load_state()
    after = decree_mod.build_promulgation_judge_context(
        restored, restored_state, [restored.get_decree_dossier(dossier["id"])],
    )

    expected = [{
        "id": authority_id, "holder_id": assignee, "privilege": "便宜行事",
        "scope": "清丈田亩", "effective_turn": state.turn,
    }]
    assert before["dossiers"][0]["held_authorities"] == expected
    assert after["dossiers"][0]["held_authorities"] == expected


def test_revoked_authority_is_durable_and_no_longer_modifies_judge_context(game):
    db, state, _content = game
    assignee = _minister(db)
    authority_id = db.grant_authority(
        state, assignee, "尚方剑密授", "辽东军务", effective_turn=state.turn,
    )
    metrics_before = dict(state.metrics)
    factions_before = [dict(row) for row in db.conn.execute(
        "SELECT name,satisfaction,leverage FROM factions ORDER BY name"
    )]
    assert db.revoke_authority(authority_id, state.turn) is True

    dossier = _dossier(db, state, assignee)
    context = decree_mod.build_promulgation_judge_context(db, state, [dossier])
    record = db.get_authority(authority_id)

    assert record["revoked"] is True
    assert record["revoked_turn"] == state.turn
    assert context["dossiers"][0]["held_authorities"] == []
    assert state.metrics == metrics_before
    assert [dict(row) for row in db.conn.execute(
        "SELECT name,satisfaction,leverage FROM factions ORDER BY name"
    )] == factions_before
