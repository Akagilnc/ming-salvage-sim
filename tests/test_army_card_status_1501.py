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

import pytest

import web_app
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import list_materials, prepare_character_materials


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


def _assert_text_keeps_statuses(text: str, statuses: list[str], label: str) -> None:
    assert text and text != "军队尚未建档。", f"{label} 空报告"
    for st in statuses:
        assert st in text, f"{label} 缺 status 原句：{st!r}\n出口={text!r}"


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
    """Army cards expose only the public contract fields, keyed by army id."""
    db, _state, _ = read_game

    rows_by_id = {row["id"]: row for row in db.army_rows()}
    payload = db.army_payload()
    assert len(payload) == len(rows_by_id)
    by_id = {p["id"]: p for p in payload}

    for army_id, row in rows_by_id.items():
        card = by_id[army_id]
        assert set(card.keys()) == _ARMY_PAYLOAD_KEYS, (
            f"{army_id}: payload 键集偏离。"
            f" extra={set(card.keys()) - _ARMY_PAYLOAD_KEYS!r}"
            f" missing={_ARMY_PAYLOAD_KEYS - set(card.keys())!r}"
        )
        assert "status" not in card
        assert {"morale", "loyalty", "arrears"}.isdisjoint(card.keys())

        assert card["name"] == row["name"]
        assert isinstance(card["arrears_text"], str)


def test_army_report_keeps_row_status(read_game):
    """共享读者真源：army_report 仍含 row.status 原样。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)
    report = db.army_report(limit=20)
    assert seed_status in report, "army_report 须保留 DB status 原句"
    _assert_text_keeps_statuses(
        report, _danger_top_statuses(db, 20), "army_report(limit=20)"
    )


def test_shared_consumers_still_surface_status(read_game):
    """逐点真实消费出口：仍含原 status（禁以直调 army_report(limit=N) 顶替）。"""
    db, state, content = read_game
    seed_status = _guanning_db_status(db)

    # 2) The war ministry ledger is selected by the military contract key.
    war = next(c for c in content.characters.values() if c.office_type == "兵部")
    knowledge = build_character_knowledge(db, state, war.name)
    world = knowledge.get("world") or {}
    assert "military" in world

    # 3) state_payload.army_warning → 真实 WebGame.state_payload 键
    payload = web_app.WebGame.state_payload(_web_runtime(db, state, content))
    army_warning = payload.get("army_warning") or ""
    _assert_text_keeps_statuses(
        army_warning, _danger_top_statuses(db, 5), "state_payload.army_warning"
    )
    # 军牌列表投影仍停携 status（与 army_warning 共享读者分流）
    for card in payload.get("armies") or []:
        assert "status" not in card or card.get("status") in (None, "")

    # 4) army_detail → 真实详情缝（关宁全量，必含 seed status）
    detail = db.army_detail(_GUANNING_ID)
    assert seed_status in detail, f"army_detail 缺关宁 status\n{detail!r}"

    # 5) army_roster → 真实名册缝（全表，含各军 status）
    roster = db.army_roster()
    all_statuses = [
        str(row["status"] or "").strip()
        for row in db.conn.execute("SELECT status FROM armies").fetchall()
        if str(row["status"] or "").strip()
    ]
    _assert_text_keeps_statuses(roster, all_statuses, "army_roster")
    assert seed_status in roster
    prepared = prepare_character_materials(db, state, war)
    paths = [
        path for path in list_materials(prepared.root) if path != "INDEX.txt"
    ]
    assert any(path.endswith("/公事档案.txt") for path in paths)

    # DB 字段零改写
    assert _guanning_db_status(db) == seed_status
    assert state is not None


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
