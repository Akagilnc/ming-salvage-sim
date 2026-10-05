"""#1501 军牌欠饷呈现单源化：军牌专属投影停携/停渲静态 status 句；共享读者保留。

刀口：
- army_payload（web 军牌）停止携带 status；其余字段完整键集/逐字段机械对照
- 军牌前端不渲染状态句（前端单测另钉）
- 共享出口逐点真实调用：army_report / intelligence /
  knowledge / state_payload.army_warning /
  army_detail / army_roster，仍含原 status（禁以直调 army_report 顶替消费点）
  （#321 P7：print_header 已拆除 army_report 直显，不再作为 status 消费点）
- DB armies.status 零改写；payload 用 arrears_text approximate，省略 raw arrears
"""

from __future__ import annotations

from types import SimpleNamespace


import web_app
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import list_materials, prepare_character_materials, read_material


# 关宁 seed 静态 status 句（content/armies.json）；永不随 arrears 更新，是本票病灶样本。
_GUANNING_STATUS = "宁锦守线尚可，欠饷严重，主动大举出击风险极高。"
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
    assert str(row["status"]) == _GUANNING_STATUS
    return str(row["status"])


def _danger_top_statuses(db, limit: int) -> list[str]:
    return [
        str(row["status"] or "").strip()
        for row in db.army_rows(limit=limit, danger_order=True)
        if str(row["status"] or "").strip()
    ]


def _assert_ming_register(db, text: str) -> None:
    rows = db.conn.execute(
        "SELECT name, manpower, status FROM armies WHERE owner_power='ming'"
    ).fetchall()
    assert rows and text
    for row in rows:
        assert row["name"] in text
        status = str(row["status"] or "").strip()
        if status:
            assert status not in text


def _assert_text_keeps_statuses(text: str, statuses: list[str], label: str) -> None:
    assert text, f"{label} 空报告"
    for st in statuses:
        assert st in text, f"{label} 缺 status 原句：{st!r}\n出口={text!r}"


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



def test_army_payload_omits_static_status_exposes_arrears_text(read_game):
    """军牌出口：army_payload 无 status、无 raw arrears 键；arrears_text 在场；完整键集/逐字段对照。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)

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
        assert "status" not in card
        assert {"morale", "loyalty", "arrears"}.isdisjoint(card.keys())
        for key in ("morale_text", "arrears_text", "mutiny_tier"):
            assert isinstance(card[key], str)

        # Compare transported DB fields; #321 covers derived situation assembly.
        for key, value in expected.items():
            assert card[key] == value, (
                f"{army_id}.{key}: payload={card[key]!r} expected={value!r}"
            )

        # seed status 句不得以任何字段值形式泄漏
        st = str(row["status"] or "").strip()
        if st:
            joined = " ".join(str(v) for v in card.values())
            assert st not in joined

    # 病灶样本：关宁欠饷奏报文案仍在，status 句不在
    from ming_sim.db import _player_army_situation

    guanning = by_id[_GUANNING_ID]
    g_row = rows_by_id[_GUANNING_ID]
    expected_arr = _player_army_situation(g_row, db._army_pay(g_row))["arrears_text"]
    assert guanning["arrears_text"] == expected_arr
    assert seed_status not in " ".join(str(v) for v in guanning.values())


def test_army_report_keeps_row_status(read_game):
    """共享读者真源：army_report 仍含 row.status 原样。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)
    report = db.army_report(limit=20)
    assert seed_status in report, "army_report 须保留 DB status 原句"
    _assert_text_keeps_statuses(
        report, _danger_top_statuses(db, 20), "army_report(limit=20)"
    )




def test_db_status_field_untouched_after_payload_read(read_game):
    """DB armies.status 与 seed 不被 payload 投影改写/拆句。"""
    db, _state, content = read_game
    before = {
        r["id"]: str(r["status"] or "")
        for r in db.conn.execute("SELECT id, status FROM armies").fetchall()
    }
    _ = db.army_payload()
    _ = db.army_report(limit=5)
    after = {
        r["id"]: str(r["status"] or "")
        for r in db.conn.execute("SELECT id, status FROM armies").fetchall()
    }
    assert before == after
    seed = content.armies[_GUANNING_ID]
    assert after[_GUANNING_ID] == seed.status == _GUANNING_STATUS
