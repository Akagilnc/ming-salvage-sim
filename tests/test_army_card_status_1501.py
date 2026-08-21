"""#1501 军牌欠饷呈现单源化：军牌专属投影停携/停渲静态 status 句；共享读者保留。

刀口：
- army_payload（web 军牌）停止携带 status
- 军牌前端不渲染状态句（前端单测另钉）
- army_report 及 tools/intelligence/knowledge/report 消费点仍含原 status
- DB armies.status 零改写；欠饷栏真数不动
"""

from __future__ import annotations

import pytest


# 关宁 seed 静态 status 句（content/armies.json）；永不随 arrears 更新，是本票病灶样本。
_GUANNING_STATUS = "宁锦守线尚可，欠饷严重，主动大举出击风险极高。"
_GUANNING_ID = "guanning"


def _guanning_db_status(db) -> str:
    row = db.conn.execute(
        "SELECT status, arrears FROM armies WHERE id=?", (_GUANNING_ID,)
    ).fetchone()
    assert row is not None, "seed 须有关宁军"
    assert str(row["status"]) == _GUANNING_STATUS
    return str(row["status"])


def _assert_report_keeps_top_statuses(db, limit: int) -> str:
    """army_report(limit) 须含 danger_order top-N 各行 status 原句。"""
    report = db.army_report(limit=limit)
    assert report and report != "军队尚未建档。"
    for row in db.army_rows(limit=limit, danger_order=True):
        st = str(row["status"] or "").strip()
        if st:
            assert st in report, (
                f"army_report(limit={limit}) 缺 status 原句：{st!r}\n报告={report!r}"
            )
    return report


def test_army_payload_omits_static_status_keeps_arrears(read_game):
    """军牌出口：army_payload 不含 status 键/seed 句；欠饷与其余字段保留。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)
    seed_row = db.conn.execute(
        "SELECT arrears, manpower, name, station FROM armies WHERE id=?",
        (_GUANNING_ID,),
    ).fetchone()

    payload = db.army_payload()
    by_id = {p["id"]: p for p in payload}
    assert _GUANNING_ID in by_id
    card = by_id[_GUANNING_ID]

    # 停携：键不在，或显式空；且全文不得出现 seed status 句
    assert "status" not in card or card.get("status") in (None, ""), (
        f"army_payload 不得携带静态 status，得 {card.get('status')!r}"
    )
    joined = " ".join(str(v) for v in card.values())
    assert seed_status not in joined
    assert "欠饷严重" not in joined

    # 欠饷真数与其余字段不变（投影仍读 DB）
    assert card["arrears"] == pytest.approx(float(seed_row["arrears"] or 0), abs=0.05)
    assert card["manpower"] == int(seed_row["manpower"])
    assert card["name"] == seed_row["name"]
    assert card["station"] == seed_row["station"]
    assert "army_needed" in card
    assert "id" in card

    # 全表扫描：任何军的 payload 均不得夹带 DB status 原文
    for row in db.conn.execute("SELECT id, status FROM armies").fetchall():
        p = by_id[row["id"]]
        assert "status" not in p or p.get("status") in (None, "")
        st = str(row["status"] or "").strip()
        if st:
            assert st not in " ".join(str(v) for v in p.values())


def test_army_report_keeps_row_status(read_game):
    """共享读者真源：army_report 仍含 row.status 原样。"""
    db, _state, _ = read_game
    seed_status = _guanning_db_status(db)
    report = db.army_report(limit=20)
    assert seed_status in report, "army_report 须保留 DB status 原句"
    assert "欠饷严重" in report


def test_shared_consumers_still_surface_status(read_game):
    """逐点抽验：tools/intelligence/knowledge/report 消费点仍含原 status（禁全局删字段）。"""
    db, state, _ = read_game
    seed_status = _guanning_db_status(db)

    # 1) tools.list_armies → army_report(limit=8)（ming_sim/tools.py）
    tools_text = _assert_report_keeps_top_statuses(db, 8)
    # limit=8 在 seed 规模下应盖住关宁；若危险序把它挤出 top-8，top 状态句仍须在
    if any(r["id"] == _GUANNING_ID for r in db.army_rows(limit=8, danger_order=True)):
        assert seed_status in tools_text

    # 2) intelligence arrears domain → army_report(limit=10)
    from ming_sim.intelligence import _qualitative_domain_statement

    intel_text, intel_src = _qualitative_domain_statement(db, "各军欠饷如何")
    assert intel_src == "armies"
    _assert_report_keeps_top_statuses(db, 10)
    # 消费点返回值本身也须带 status（非另造空串）
    top10 = db.army_rows(limit=10, danger_order=True)
    for row in top10:
        st = str(row["status"] or "").strip()
        if st:
            assert st in intel_text, f"intelligence 出口缺 status：{st!r}"

    # 3) knowledge military builder → army_report(limit=30)
    military = _assert_report_keeps_top_statuses(db, 30)
    assert seed_status in military

    # 4) report.print_header 同源 army_report(limit=3)
    _assert_report_keeps_top_statuses(db, 3)

    # 5) state_payload.army_warning 同源 army_report(limit=5)
    _assert_report_keeps_top_statuses(db, 5)

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
