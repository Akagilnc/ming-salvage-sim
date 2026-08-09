import json

from ming_sim import issues as issue_engine


VALID_TENURES = ("真除", "署理", "兼署", "加衔")


def _active_minister(db):
    return db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' ORDER BY rowid LIMIT 1"
    ).fetchone()["name"]


def _promulgate_appointment(db, state, content, name, office, tenure=None):
    payload = {"name": name, "office": office}
    if tenure is not None:
        payload["任别"] = tenure
    pending_id = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=_active_minister(db), target_id=None, payload=payload,
    )
    db.commit_pending_actions(state, content=content, registry=None)
    dossier = next(
        row for row in db.list_decree_dossiers()
        if row["pending_action_id"] == pending_id
    )
    db.apply_dossier_promulgation(
        state, dossier["id"], "promulgated", content=content, registry=None,
    )
    return db.get_decree_dossier(dossier["id"])


def test_appointment_dossier_and_office_archive_preserve_each_tenure(game):
    db, state, content = game
    names = [
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
            "AND office_type!='后宫' ORDER BY rowid LIMIT 4"
        )
    ]

    for index, (name, tenure) in enumerate(zip(names, VALID_TENURES), 1):
        dossier = _promulgate_appointment(
            db, state, content, name, f"任别验收官{index}", tenure,
        )
        assert json.loads(dossier["payload_json"])["任别"] == tenure
        office = db.conn.execute(
            "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
            (name,),
        ).fetchone()
        assert office["appointment_tenure"] == tenure


def test_legacy_appointment_defaults_to_permanent_without_rejudging(game):
    db, state, content = game
    name = _active_minister(db)

    dossier = _promulgate_appointment(db, state, content, name, "旧档兜底官")

    assert json.loads(dossier["payload_json"])["任别"] == "真除"
    row = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?", (name,)
    ).fetchone()
    assert row["appointment_tenure"] == "真除"


def test_person_delta_rejects_invalid_appointment_tenure_without_mutation(game):
    db, state, content = game
    name = _active_minister(db)
    before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name,)
    ).fetchone()["office"]

    result = issue_engine.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "动作": "任命", "office": "非法任别官", "任别": "试署",
    }]}, content=content)

    rejected = result["applied_person_changes"][0]
    assert rejected["rejected"] is True
    assert rejected["category"] == "invalid_enum"
    assert rejected["item"]["任别"] == "试署"
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (name,)
    ).fetchone()["office"] == before


def test_appointment_tenure_survives_restore(game):
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB

    db, state, content = game
    name = _active_minister(db)
    _promulgate_appointment(db, state, content, name, "恢复验收官", "兼署")
    path = db.conn.execute("PRAGMA database_list").fetchone()["file"]

    restored = GameDB(path, GameContent.load())
    try:
        row = restored.conn.execute(
            "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
            (name,),
        ).fetchone()
        assert row["appointment_tenure"] == "兼署"
    finally:
        restored.conn.close()


def test_acting_appointment_can_be_reappointed_permanent_on_same_path(game):
    db, state, content = game
    name = _active_minister(db)

    _promulgate_appointment(db, state, content, name, "转正验收官", "署理")
    _promulgate_appointment(db, state, content, name, "转正验收官", "真除")

    row = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?", (name,)
    ).fetchone()
    assert row["appointment_tenure"] == "真除"
