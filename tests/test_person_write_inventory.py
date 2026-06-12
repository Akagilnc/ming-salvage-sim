"""ADR 0009 person write-point inventory."""

from __future__ import annotations


def test_person_write_inventory_covers_current_character_sql_writes():
    """Current direct characters writes are inventoried for later migration."""
    from ming_sim.person_write_inventory import (
        PERSON_WRITE_POINT_INVENTORY,
        discover_character_write_sql_locations,
    )

    inventory_locations = {item["location"] for item in PERSON_WRITE_POINT_INVENTORY}
    discovered_locations = {item["location"] for item in discover_character_write_sql_locations()}

    assert discovered_locations <= inventory_locations
    assert {
        "ming_sim/db.py:seed_static_data",
        "ming_sim/db.py:set_character_status",
        "ming_sim/db.py:apply_character_power_changes",
        "ming_sim/db.py:set_character_office",
        "ming_sim/db.py:add_character",
        "ming_sim/issues.py:_displace_duplicate_offices",
        "ming_sim/issues.py:_apply_person_changes",
        "ming_sim/session.py:_apply_appointment_delta:candidate_upgrade",
    } <= inventory_locations


def test_person_write_inventory_classifies_each_write_point_disposition():
    """Every inventory row names its ADR 0009 migration disposition."""
    from ming_sim.person_write_inventory import PERSON_WRITE_POINT_INVENTORY

    allowed = {
        "migrate_to_person_applier",
        "adr0009_exempt",
        "dedicated_person_entry",
        "outside_person_archive",
    }
    for item in PERSON_WRITE_POINT_INVENTORY:
        assert item["disposition"] in allowed
        assert item["owner"]
        assert item["reason"]

    by_location = {item["location"]: item for item in PERSON_WRITE_POINT_INVENTORY}
    assert by_location["ming_sim/db.py:seed_static_data"]["disposition"] == "adr0009_exempt"
    assert by_location["ming_sim/db.py:set_portrait_id"]["disposition"] == (
        "outside_person_archive"
    )
    assert by_location[
        "ming_sim/session.py:_apply_appointment_delta:candidate_upgrade"
    ]["disposition"] == "dedicated_person_entry"


def test_person_write_inventory_lists_pending_migration_locations():
    """Later slices can ask which legacy write points still need migration."""
    from ming_sim.person_write_inventory import person_write_locations_by_disposition

    assert person_write_locations_by_disposition("migrate_to_person_applier") == (
        "ming_sim/db.py:add_character",
        "ming_sim/db.py:apply_character_power_changes",
        "ming_sim/db.py:set_character_office",
        "ming_sim/db.py:set_character_status",
        "ming_sim/issues.py:_apply_person_changes",
        "ming_sim/issues.py:_displace_duplicate_offices",
    )


def test_person_write_inventory_scanner_fallbacks_are_explicit():
    """Scanner fallback branches stay deterministic for odd AST nodes."""
    import ast

    from ming_sim.person_write_inventory import (
        _call_name,
        _enclosing_function_name,
        _inventory_location,
    )

    literal = ast.Constant(value="UPDATE characters SET office=''")
    assert _enclosing_function_name(literal, {}) == "<module>"
    assert _call_name(ast.Name(id="execute")) == "execute"
    assert _call_name(literal) == ""
    assert _inventory_location(
        "ming_sim/new_person_path.py",
        "insert_character_elsewhere",
        "INSERT INTO characters (name) VALUES (?)",
    ) == "ming_sim/new_person_path.py:insert_character_elsewhere"
    assert _inventory_location(
        "ming_sim/db.py",
        "future_insert_character",
        "INSERT INTO characters (name) VALUES (?)",
    ) == "ming_sim/db.py:future_insert_character"
