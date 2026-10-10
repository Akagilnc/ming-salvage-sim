"""#1501 军牌欠饷呈现单源化：军牌专属投影停携/停渲静态 status 句；共享读者保留。

刀口：
- army_payload（web 军牌）停止携带 status；其余字段完整键集/逐字段机械对照
- 军牌前端不渲染状态句（前端单测另钉）
- 共享出口逐点真实调用：army_report / intelligence /
  knowledge / state_payload.army_warning /
  army_roster，仍含原 status（禁以直调 army_report 顶替消费点）
  （#321 P7：print_header 已拆除 army_report 直显，不再作为 status 消费点）
- DB armies.status 零改写；payload 用 arrears_text approximate，省略 raw arrears
"""

from __future__ import annotations

from types import SimpleNamespace


import web_app
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import list_materials, prepare_character_materials


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


def _guanning_db_status(db) -> str:
    row = db.conn.execute(
        "SELECT status, arrears FROM armies WHERE id=?", (_GUANNING_ID,)
    ).fetchone()
    assert row is not None, "seed 须有关宁军"
    status = str(row["status"] or "")
    assert status.strip()
    return status


def _expected_army_card_from_row(db, row) -> dict:
    """Direct DB-field transport; derived situation fields are covered by #321."""
    from ming_sim.army_pay import army_needed

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
    _guanning_db_status(db)  # seed status 行仍在 DB

    rows_by_id = {row["id"]: row for row in db.army_rows()}
    payload = db.army_payload()
    assert len(payload) == len(rows_by_id)
    by_id = {p["id"]: p for p in payload}

    for army_id, row in rows_by_id.items():
        card = by_id[army_id]
        expected = _expected_army_card_from_row(db, row)

        # 完整键集：恰好等于投影契约（无 status / 无 raw morale|loyalty|arrears）
        assert set(card.keys()) == _ARMY_PAYLOAD_KEYS, (
            f"{army_id}: payload 键集偏离。"
            f" extra={set(card.keys()) - _ARMY_PAYLOAD_KEYS!r}"
            f" missing={_ARMY_PAYLOAD_KEYS - set(card.keys())!r}"
        )
        for key in ("morale_text", "arrears_text", "mutiny_tier"):
            assert isinstance(card[key], str)

        # Compare transported DB fields; #321 covers derived situation assembly.
        for key, value in expected.items():
            assert card[key] == value, (
                f"{army_id}.{key}: payload={card[key]!r} expected={value!r}"
            )

    # 病灶样本：关宁欠饷奏报文案在场（派生文本的逐字对照由 #321 承接）；status 键已从上断言排除。
    guanning = by_id[_GUANNING_ID]
    assert isinstance(guanning["arrears_text"], str) and guanning["arrears_text"]
    assert "status" not in guanning
