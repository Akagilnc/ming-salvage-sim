import shutil
import sys

import pytest

from ming_sim import issues
from ming_sim.issues import apply_office_appointment
from ming_sim.decree import reload_state_from_db
from ming_sim.session import apply_appointment


def _active(db):
    return db.conn.execute("SELECT name FROM characters WHERE status='active' LIMIT 1").fetchone()["name"]


@pytest.mark.parametrize("invalid_distance", [float("nan"), float("inf"), float("-inf")])
def test_departure_rejects_nonfinite_distance_before_ledger_write(game, monkeypatch, invalid_distance):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"
    fields = (
        "transit_to", "transit_distance_remaining", "transit_speed_factor", "transit_start_turn",
    )
    before_db = tuple(db.conn.execute(
        "SELECT transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?", (name,),
    ).fetchone())
    character = content.characters[name]
    before_memory = tuple(getattr(character, field, 0) for field in fields)

    class InvalidMatrix:
        def travel_time(self, origin, destination):
            return invalid_distance

    monkeypatch.setattr(
        issues.DistanceMatrix, "from_file", classmethod(lambda cls, path: InvalidMatrix()),
    )

    with pytest.raises(ValueError, match="invalid baked travel time"):
        issues.apply_score_extraction(db, state, {"人物变更": [{
            "name": name, "origin_ref": "盘面自发", "动作": "行止",
            "transit_to": "liaodong",
        }]}, content=content)

    after_db = tuple(db.conn.execute(
        "SELECT transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?", (name,),
    ).fetchone())
    assert after_db == before_db
    assert tuple(getattr(character, field, 0) for field in fields) == before_memory


def test_departure_reads_matrix_from_frozen_bundle_outside_cwd(game, monkeypatch, tmp_path):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"
    bundle = tmp_path / "bundle"
    (bundle / "content").mkdir(parents=True)
    shutil.copy("content/distance_matrix.json", bundle / "content" / "distance_matrix.json")
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.chdir(elsewhere)

    issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止", "transit_to": "liaodong",
    }]}, content=content)

    assert db.conn.execute(
        "SELECT transit_to FROM characters WHERE name=?", (name,)
    ).fetchone()["transit_to"] == "liaodong"


@pytest.mark.parametrize("payload", [
    {"location": "liaodong"},
    {"location": "beizhili", "transit_to": "liaodong"},
])
def test_departure_rejects_location_shapes_without_mutation(game, payload):
    db, state, content = game
    name = _active(db)
    before = tuple(db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?", (name,),
    ).fetchone())

    result = issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止", **payload,
    }]}, content=content)

    after = tuple(db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?", (name,),
    ).fetchone())
    assert after == before
    assert result["applied_person_changes"][0]["category"] == "invalid_transition"


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


@pytest.mark.parametrize("origin", ["", "not-a-region"])
def test_noncanonical_origin_is_narrative_only_noop(game, origin):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location=? WHERE name=?", (origin, name))
    content.characters[name].location = origin

    result = issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止", "transit_to": "liaodong",
    }]}, content=content)

    row = db.conn.execute(
        "SELECT transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert tuple(row) == ("", None, None, 0)
    character = content.characters[name]
    assert (
        character.transit_to,
        character.transit_distance_remaining,
        character.transit_speed_factor,
        getattr(character, "transit_start_turn", 0),
    ) == ("", None, None, 0)
    assert result["applied_person_changes"] == []


@pytest.mark.parametrize("exit_path", ["appointment_replacement", "pending_dismissal"])
def test_status_exit_clears_complete_transit_ledger(game, exit_path):
    db, state, content = game
    name = _active(db)
    db.set_character_transit(
        name,
        transit_to="liaodong",
        distance_remaining=2.1,
        speed_factor=1.5,
        start_turn=1,
        content=content,
    )

    if exit_path == "appointment_replacement":
        appointed, displaced = apply_appointment(
            db, state, content, None,
            {"name": "新任测试官", "office": "兵部尚书", "replaces": name},
        )
        assert appointed == "新任测试官"
        assert displaced == name
    else:
        assert db._commit_office_action(
            state, {"action": "罢免"}, {"name": name}, content, None,
        ) == {name}

    row = db.conn.execute(
        "SELECT status, transit_to, transit_distance_remaining, transit_speed_factor, transit_start_turn "
        "FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert tuple(row) == ("dismissed", "", None, None, 0)
    character = content.characters[name]
    assert (
        character.status,
        character.transit_to,
        character.transit_distance_remaining,
        character.transit_speed_factor,
        character.transit_start_turn,
    ) == ("dismissed", "", None, None, 0)


@pytest.mark.parametrize(
    ("starting_status", "appointment_reason", "expected_reason"),
    [
        ("active", "调任测试", ""),
        ("dismissed", "起复测试", "起复测试"),
    ],
)
def test_office_appointment_keeps_status_reason_mirrored(
    game, starting_status, appointment_reason, expected_reason,
):
    db, state, content = game
    name = _active(db)
    character = content.characters[name]
    db.conn.execute(
        "UPDATE characters SET status=?, status_reason='旧缘由', reason_code='旧代码' WHERE name=?",
        (starting_status, name),
    )
    character.status = starting_status
    character.status_reason = "旧缘由"
    character.reason_code = "旧代码"

    result = apply_office_appointment(
        db, state, content, None, name, "兵部尚书", reason=appointment_reason,
    )

    assert not result.get("rejected")
    row = db.conn.execute(
        "SELECT status, status_reason, reason_code FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert tuple(row) == ("active", expected_reason, "")
    assert (character.status, character.status_reason, character.reason_code) == (
        "active", expected_reason, "",
    )


@pytest.mark.parametrize("invalid_tone", ["", 0, False, "飞驰"])
def test_invalid_tone_is_rejected_before_same_destination_idempotence(game, invalid_tone):
    db, state, content = game
    name = _active(db)
    db.conn.execute("UPDATE characters SET location='beizhili', transit_to='liaodong' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"
    content.characters[name].transit_to = "liaodong"

    result = issues.apply_score_extraction(db, state, {"人物变更": [{
        "name": name, "origin_ref": "盘面自发", "动作": "行止",
        "transit_to": "liaodong", "行程语气": invalid_tone,
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
