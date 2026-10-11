"""#1501 军牌欠饷呈现单源化：军牌专属投影停携静态 status；共享读者走结构化字段。

刀口：
- army_payload（web 军牌）停止携带 status；其余字段完整键集/逐字段机械对照
- DB armies.status 零改写；payload 用 arrears_text approximate，省略 raw arrears
- 共享读者（army_rows / state_payload.armies）以结构化字段承接，不锁自由散文子串
"""

from __future__ import annotations





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




def _expected_army_card_from_row(row) -> dict:
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



def test_army_payload_omits_static_status_exposes_arrears_text(read_game):
    """军牌出口：army_payload 无 status、无 raw arrears 键；arrears_text 在场；完整键集/逐字段对照。"""
    db, _state, _ = read_game

    rows_by_id = {row["id"]: row for row in db.army_rows()}
    payload = db.army_payload()
    assert len(payload) == len(rows_by_id)
    by_id = {p["id"]: p for p in payload}

    for army_id, row in rows_by_id.items():
        card = by_id[army_id]
        expected = _expected_army_card_from_row(row)

        assert set(card.keys()) == _ARMY_PAYLOAD_KEYS, (
            f"{army_id}: payload 键集偏离。"
            f" extra={set(card.keys()) - _ARMY_PAYLOAD_KEYS!r}"
            f" missing={_ARMY_PAYLOAD_KEYS - set(card.keys())!r}"
        )
        for key in ("morale_text", "arrears_text", "mutiny_tier"):
            assert isinstance(card[key], str)

        for key, value in expected.items():
            assert card[key] == value, (
                f"{army_id}.{key}: payload={card[key]!r} expected={value!r}"
            )

    # 病灶样本：关宁欠饷奏报文案在场（派生文本的逐字对照由 #321 承接）；status 键已从上断言排除。
    guanning = by_id[_GUANNING_ID]
    assert isinstance(guanning["arrears_text"], str) and guanning["arrears_text"]
    assert "status" not in guanning
