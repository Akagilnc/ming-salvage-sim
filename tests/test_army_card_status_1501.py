"""#1501 军牌欠饷呈现单源化：军牌专属投影停携/停渲静态 status 句；共享读者保留。

刀口：
- army_payload（web 军牌）停止携带 status；其余字段完整键集/逐字段机械对照
- 军牌前端不渲染状态句（前端单测另钉）
- 共享出口逐点真实调用：army_report / tools.list_armies / intelligence /
  knowledge / state_payload.army_warning /
  army_detail / army_roster，仍含原 status（禁以直调 army_report 顶替消费点）
  （#321 P7：print_header 已拆除 army_report 直显，不再作为 status 消费点）
- DB armies.status 零改写；欠饷栏真数不动
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import web_app
from ming_sim.intelligence import _qualitative_domain_statement
from ming_sim.knowledge import build_character_knowledge
from ming_sim.models import CourtContext
from ming_sim.tools import build_board_query_tools, build_minister_tools


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


def _expected_army_card_from_row(db, row) -> dict:
    """由 DB 行机械重建军牌投影（含历史 status 键），供「其余字段不变」对照。"""
    from ming_sim.db import _player_army_situation

    pay = db._army_pay(row)
    sit = _player_army_situation(row, pay)
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
        "morale_text": sit["morale_text"],
        "training": int(row["training"]),
        "equipment": int(row["equipment"]),
        "arrears_text": sit["arrears_text"],
        "mobility": int(row["mobility"]),
        "mutiny_tier": sit["mutiny_tier"],
        "firearm_equipment": int(row["firearm_equipment"]),
        "cannon_equipment": int(row["cannon_equipment"]),
        "status": row["status"],  # 旧投影曾携；#1501 允许删除
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


def test_army_payload_omits_static_status_keeps_arrears(read_game):
    """军牌出口：army_payload 不含 status；完整键集/逐字段对照（#321 欠饷走 arrears_text）。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)

    rows_by_id = {row["id"]: row for row in db.army_rows()}
    payload = db.army_payload()
    assert len(payload) == len(rows_by_id)
    by_id = {p["id"]: p for p in payload}

    for army_id, row in rows_by_id.items():
        card = by_id[army_id]
        legacy = _expected_army_card_from_row(db, row)
        expected = {k: v for k, v in legacy.items() if k != "status"}

        # 完整键集：恰好等于投影契约（无 status / 无 raw morale|loyalty|arrears）
        assert set(card.keys()) == set(expected.keys()) == _ARMY_PAYLOAD_KEYS, (
            f"{army_id}: payload 键集偏离。"
            f" extra={set(card.keys()) - _ARMY_PAYLOAD_KEYS!r}"
            f" missing={_ARMY_PAYLOAD_KEYS - set(card.keys())!r}"
        )
        assert "status" not in card
        assert {"morale", "loyalty", "arrears"}.isdisjoint(card.keys())

        # 逐字段机械对照（唯一允许差异已在 expected 中删除 status）
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
    assert "欠饷严重" not in " ".join(str(v) for v in guanning.values())


def test_army_report_keeps_row_status(read_game):
    """共享读者真源：army_report 仍含 row.status 原样。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)
    report = db.army_report(limit=20)
    assert seed_status in report, "army_report 须保留 DB status 原句"
    assert "欠饷严重" in report
    _assert_text_keeps_statuses(
        report, _danger_top_statuses(db, 20), "army_report(limit=20)"
    )


def test_shared_consumers_still_surface_status(read_game):
    """逐点真实消费出口：仍含原 status（禁以直调 army_report(limit=N) 顶替）。"""
    db, state, content = read_game
    seed_status = _guanning_db_status(db)
    ctx = CourtContext(state=state, db=db, previous_summary="")
    board_tools = {f.__name__: f for f in build_board_query_tools(ctx)}

    # 1) tools.list_armies → 真实 tool 闭包（limit=8）
    tools_text = board_tools["list_armies"]()
    _assert_text_keeps_statuses(
        tools_text, _danger_top_statuses(db, 8), "tools.list_armies"
    )
    if any(r["id"] == _GUANNING_ID for r in db.army_rows(limit=8, danger_order=True)):
        assert seed_status in tools_text

    # 2) intelligence arrears domain → 真实 _qualitative_domain_statement
    intel_text, intel_src = _qualitative_domain_statement(db, "各军欠饷如何")
    assert intel_src == "armies"
    _assert_text_keeps_statuses(
        intel_text, _danger_top_statuses(db, 10), "intelligence"
    )
    if any(r["id"] == _GUANNING_ID for r in db.army_rows(limit=10, danger_order=True)):
        assert seed_status in intel_text

    # 3) knowledge military builder → 真实 build_character_knowledge（兵部可见 military）
    war = next(c for c in content.characters.values() if c.office_type == "兵部")
    knowledge = build_character_knowledge(db, state, war.name)
    military = (knowledge.get("world") or {}).get("military") or ""
    _assert_text_keeps_statuses(
        military, _danger_top_statuses(db, 30), "knowledge.world.military"
    )
    assert seed_status in military

    # 4) state_payload.army_warning → 真实 WebGame.state_payload 键
    payload = web_app.WebGame.state_payload(_web_runtime(db, state, content))
    army_warning = payload.get("army_warning") or ""
    _assert_text_keeps_statuses(
        army_warning, _danger_top_statuses(db, 5), "state_payload.army_warning"
    )
    # 军牌列表投影仍停携 status（与 army_warning 共享读者分流）
    for card in payload.get("armies") or []:
        assert "status" not in card or card.get("status") in (None, "")

    # 5) army_detail → 真实详情缝（关宁全量，必含 seed status）
    detail = db.army_detail(_GUANNING_ID)
    assert seed_status in detail, f"army_detail 缺关宁 status\n{detail!r}"
    assert "欠饷严重" in detail
    # 经 tools.inspect_army 同一消费闭包再钉一次
    inspect_text = board_tools["inspect_army"](_GUANNING_ID)
    assert seed_status in inspect_text

    # 6) army_roster → 真实名册缝（全表，含各军 status）
    roster = db.army_roster()
    all_statuses = [
        str(row["status"] or "").strip()
        for row in db.conn.execute("SELECT status FROM armies").fetchall()
        if str(row["status"] or "").strip()
    ]
    _assert_text_keeps_statuses(roster, all_statuses, "army_roster")
    assert seed_status in roster
    # 经大臣 query_army_roster 工具闭包再钉（军事域授权）
    mtools = {
        f.__name__: f
        for f in build_minister_tools(war, ctx, use_army_tool=True)
    }
    tool_roster = mtools["query_army_roster"]([])
    _assert_text_keeps_statuses(tool_roster, all_statuses, "tools.query_army_roster")

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
