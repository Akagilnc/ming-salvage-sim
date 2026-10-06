"""#1501 军牌欠饷呈现单源化：军牌专属投影停携 status；DB status 不被投影改写。

契约面（结构化）：
- army_payload / state_payload.armies 无 status 键，无 raw arrears/morale/loyalty
- 完整键集对照 + 逐字段 DB 直输字段
- arrears_text / morale_text / mutiny_tier 为非空 str
- 读 payload 后 DB armies.status 原样
不锁 army_report／detail／roster／知识材料等生成正文中的 status 原句。
"""

from __future__ import annotations

from types import SimpleNamespace

import web_app
from ming_sim.army_pay import army_needed


_GUANNING_STATUS = "宁锦守线尚可，欠饷严重，主动大举出击风险极高。"
_GUANNING_ID = "guanning"

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


def _guanning_db_status(db) -> str:
    row = db.conn.execute(
        "SELECT status, arrears FROM armies WHERE id=?", (_GUANNING_ID,)
    ).fetchone()
    assert row is not None, "seed 须有关宁军"
    assert str(row["status"]) == _GUANNING_STATUS
    return str(row["status"])


def _expected_army_card_from_row(db, row) -> dict:
    """DB 直输字段；派生 situation 三键由 #321 契约另盖。"""
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
    """军牌出口：无 status／raw 轴键；键集与 DB 直输字段对照；situation 三键非空 str。"""
    db, _state, _ = read_game
    _guanning_db_status(db)

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
            assert isinstance(card[key], str) and card[key].strip()

        for key, value in expected.items():
            assert card[key] == value, (
                f"{army_id}.{key}: payload={card[key]!r} expected={value!r}"
            )

    guanning = by_id[_GUANNING_ID]
    assert isinstance(guanning.get("arrears_text"), str) and guanning["arrears_text"].strip()
    assert "status" not in guanning


def test_state_payload_armies_omit_status(read_game):
    """Web state_payload.armies 与军牌同：无 status 键。"""
    db, state, content = read_game
    payload = web_app.WebGame.state_payload(_web_runtime(db, state, content))
    armies = payload.get("armies") or []
    assert armies
    for card in armies:
        assert "status" not in card or card.get("status") in (None, "")
        assert "arrears_text" in card
        assert isinstance(card["arrears_text"], str)


def test_db_status_field_untouched_after_payload_read(read_game):
    """DB armies.status 与 seed 不被 payload 投影改写。"""
    db, _state, content = read_game
    before = {
        r["id"]: str(r["status"] or "")
        for r in db.conn.execute("SELECT id, status FROM armies").fetchall()
    }
    _ = db.army_payload()
    web_app.WebGame.state_payload(_web_runtime(db, _state, content))
    after = {
        r["id"]: str(r["status"] or "")
        for r in db.conn.execute("SELECT id, status FROM armies").fetchall()
    }
    assert after == before
    assert before.get(_GUANNING_ID) == _GUANNING_STATUS
