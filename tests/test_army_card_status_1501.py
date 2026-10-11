"""#1501 军牌欠饷呈现单源化：军牌专属投影停携静态 status；共享读者走结构化字段。

刀口：
- army_payload（web 军牌）停止携带 status；其余字段完整键集/逐字段机械对照
- DB armies.status 零改写；payload 用 arrears_text approximate，省略 raw arrears
- 共享读者（army_rows / state_payload.armies）以结构化字段承接，不锁自由散文子串
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app


_GUANNING_ID = "guanning"

# army_payload 投影完整键集（#1501 删 status；#321 军心/士气/欠饷改三字符串键）。
_ARMY_PAYLOAD_KEYS = frozenset(
    {
        "id",
        "name",
        "station",
        "theater",
        "commander",
        "controller",
        "troop_type",
        "manpower",
        "army_needed",
        "supply",
        "morale_text",
        "training",
        "equipment",
        "arrears_text",
        "mobility",
        "mutiny_tier",
        "firearm_equipment",
        "cannon_equipment",
        "owner_power",
    }
)


def _expected_army_card_from_row(db, row) -> dict:
    """Direct DB-field transport; derived situation fields are covered by #321."""
    from ming_sim.flows import army_needed

    pay = army_needed(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "station": row["station"],
        "theater": row["theater"],
        "commander": row["commander"],
        "controller": row["controller"],
        "troop_type": row["troop_type"],
        "manpower": int(row["manpower"]),
        "army_needed": pay,
        "supply": int(row["supply"]),
        "training": int(row["training"]),
        "equipment": int(row["equipment"]),
        "mobility": int(row["mobility"]),
        "firearm_equipment": int(row["firearm_equipment"]),
        "cannon_equipment": int(row["cannon_equipment"]),
        "owner_power": row["owner_power"],
    }


def _web_runtime(db, state, content):
    """轻壳 WebGame：走真实 state_payload（含 army_warning 缝）。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary="",
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.map_nodes = lambda: []
    runtime.ending_payload = lambda: None
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    return runtime


def test_army_payload_omits_static_status_exposes_arrears_text(read_game):
    """军牌出口：army_payload 无 status、无 raw arrears 键；arrears_text 在场；完整键集/逐字段对照。"""
    db, _state, _ = read_game

    rows_by_id = {row["id"]: row for row in db.army_rows()}
    payload = db.army_payload()
    assert len(payload) == len(rows_by_id)
    by_id = {p["id"]: p for p in payload}

    for army_id, row in rows_by_id.items():
        card = by_id[army_id]
        expected = _expected_army_card_from_row(db, row)

        assert set(card.keys()) == _ARMY_PAYLOAD_KEYS, (
            f"{army_id}: payload 键集偏离。"
            f" extra={set(card.keys()) - _ARMY_PAYLOAD_KEYS!r}"
            f" missing={_ARMY_PAYLOAD_KEYS - set(card.keys())!r}"
        )
        assert "status" not in card
        assert {"morale", "loyalty", "arrears"}.isdisjoint(card.keys())
        for key in ("morale_text", "arrears_text", "mutiny_tier"):
            assert isinstance(card[key], str)

        for key, value in expected.items():
            assert card[key] == value, (
                f"{army_id}.{key}: payload={card[key]!r} expected={value!r}"
            )



def test_shared_army_readers_keep_status_field_and_card_omission(read_game):
    """共享读者：army_rows 仍携 status 字段；state_payload.armies 军牌投影仍停携 status。"""
    db, state, content = read_game

    rows = list(db.army_rows(limit=20, danger_order=True))
    assert rows
    assert any(str(row["status"] or "").strip() for row in rows)
    guanning = next(row for row in db.army_rows() if row["id"] == _GUANNING_ID)
    assert str(guanning["status"] or "").strip()

    payload = web_app.WebGame.state_payload(_web_runtime(db, state, content))
    assert "army_warning" in payload
    for card in payload.get("armies") or []:
        assert "status" not in card or card.get("status") in (None, "")
        assert "arrears_text" in card


def test_db_status_field_untouched_after_payload_read(read_game):
    """DB armies.status 与 seed 不被 payload 投影改写。"""
    db, _state, content = read_game
    before = {
        r["id"]: str(r["status"] or "")
        for r in db.conn.execute("SELECT id, status FROM armies").fetchall()
    }
    _ = db.army_payload()
    _ = db.army_rows(limit=5)
    after = {
        r["id"]: str(r["status"] or "")
        for r in db.conn.execute("SELECT id, status FROM armies").fetchall()
    }
    assert before == after
    seed = content.armies[_GUANNING_ID]
    assert after[_GUANNING_ID] == seed.status
    assert str(after[_GUANNING_ID] or "").strip()
