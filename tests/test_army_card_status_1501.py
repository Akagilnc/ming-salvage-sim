"""#1501: army cards expose the declared fields without rewriting stored status."""
from __future__ import annotations

_ARMY_PAYLOAD_KEYS = frozenset({
    "id", "name", "station", "theater", "commander", "controller", "troop_type",
    "manpower", "army_needed", "supply", "morale_text", "training", "equipment",
    "arrears_text", "mobility", "mutiny_tier", "firearm_equipment",
    "cannon_equipment", "owner_power",
})


def test_army_payload_omits_static_status_exposes_arrears_text(read_game):
    db, _state, _content = read_game
    rows = {row["id"]: row for row in db.army_rows()}
    cards = {card["id"]: card for card in db.army_payload()}
    assert set(cards) == set(rows)
    derived = {"army_needed", "morale_text", "arrears_text", "mutiny_tier"}
    for army_id, card in cards.items():
        assert set(card) == _ARMY_PAYLOAD_KEYS
        for field in _ARMY_PAYLOAD_KEYS - derived:
            assert card[field] == rows[army_id][field]
        for field in ("morale_text", "arrears_text", "mutiny_tier"):
            assert isinstance(card[field], str)


def test_db_status_field_untouched_after_payload_read(read_game):
    db, _state, content = read_game
    before = {
        row["id"]: row["status"]
        for row in db.conn.execute("SELECT id, status FROM armies")
    }
    db.army_payload()
    db.army_report(limit=5)
    after = {
        row["id"]: row["status"]
        for row in db.conn.execute("SELECT id, status FROM armies")
    }
    assert before == after
    assert after["guanning"] == content.armies["guanning"].status
