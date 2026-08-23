from ming_sim import issues
from ming_sim.decree import reload_state_from_db


def _active(db):
    return db.conn.execute("SELECT name FROM characters WHERE status='active' LIMIT 1").fetchone()["name"]


def test_departure_persists_matrix_distance_and_urgent_factor(game):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"

    issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止",
        "transit_to": "liaodong", "行程语气": "加急",
    }]}, content=content)

    row = db.conn.execute("SELECT transit_to, transit_distance_remaining, transit_speed_factor FROM characters WHERE name=?", (name,)).fetchone()
    assert dict(row) == {"transit_to": "liaodong", "transit_distance_remaining": 2.1, "transit_speed_factor": 1.5}
    assert content.characters[name].transit_distance_remaining == 2.1
    assert content.characters[name].transit_speed_factor == 1.5

    content.characters[name].transit_distance_remaining = None
    content.characters[name].transit_speed_factor = None
    reload_state_from_db(db, state, content=content)
    assert content.characters[name].transit_distance_remaining == 2.1
    assert content.characters[name].transit_speed_factor == 1.5


def test_empty_origin_is_narrative_only_noop(game):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='' WHERE name=?", (name,))
    content.characters[name].location = ""

    result = issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止", "transit_to": "liaodong",
    }]}, content=content)

    row = db.conn.execute("SELECT transit_to, transit_distance_remaining, transit_speed_factor FROM characters WHERE name=?", (name,)).fetchone()
    assert tuple(row) == ("", None, None)
    assert result["applied_person_changes"] == []


def test_invalid_tone_is_rejected_before_same_destination_idempotence(game):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='beizhili', transit_to='liaodong' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"
    content.characters[name].transit_to = "liaodong"

    result = issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止",
        "transit_to": "liaodong", "行程语气": "飞驰",
    }]}, content=content)

    assert result["applied_person_changes"][0]["category"] == "invalid_enum"


def test_same_destination_is_idempotent(game):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"
    base = {"name": name, "origin_ref": "盘面自发", "动作": "行止", "transit_to": "liaodong"}
    issues.apply_score_extraction(db, state, {"人物变更": [base]}, content=content)
    db.conn.execute("UPDATE characters SET transit_distance_remaining=1.25 WHERE name=?", (name,))
    issues.apply_score_extraction(db, state, {"人物变更": [{**base, "行程语气": "星夜兼程"}]}, content=content)
    row = db.conn.execute("SELECT transit_distance_remaining, transit_speed_factor FROM characters WHERE name=?", (name,)).fetchone()
    assert tuple(row) == (1.25, 1.0)
