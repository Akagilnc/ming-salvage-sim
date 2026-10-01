"""军饷结构化读侧：实扣应发与欠饷排序。"""

import pytest

from ming_sim.flows import army_needed


def test_army_payload_exposes_army_needed(read_game):
    db, _state, _ = read_game
    payload = db.army_payload()
    assert payload, "应有军队"
    by_id = {p["id"]: p for p in payload}
    for row in db.conn.execute("SELECT * FROM armies").fetchall():
        assert by_id[row["id"]]["army_needed"] == army_needed(row)


def test_danger_order_uses_army_needed_for_arrears_months(game):
    db, _state, _ = game
    rows = db.conn.execute(
        "SELECT id,name FROM armies WHERE owner_power='ming' AND salary_rate>0 LIMIT 2"
    ).fetchall()
    if len(rows) < 2:
        pytest.skip("需≥2 支 salary_rate>0 的明军作排序对比（数据前提）")
    a, b = rows
    for aid in (a["id"], b["id"]):
        db.conn.execute(
            "UPDATE armies SET supply=80,morale=80,loyalty=80,training=80,"
            "arrears=50,manpower=20000 WHERE id=?",
            (aid,),
        )
    db.conn.execute("UPDATE armies SET salary_rate=5.0 WHERE id=?", (a["id"],))
    db.conn.execute("UPDATE armies SET salary_rate=0.5 WHERE id=?", (b["id"],))
    db.conn.commit()
    ordered = [r["name"] for r in db.army_rows(danger_order=True)]
    assert ordered.index(b["name"]) < ordered.index(a["name"])


def test_danger_order_preserves_fractional_arrears(game):
    db, _state, _ = game
    rows = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' AND salary_rate>0 LIMIT 2"
    ).fetchall()
    if len(rows) < 2:
        pytest.skip("需≥2 支 salary_rate>0 的明军作排序对比（数据前提）")
    low, high = rows
    for aid in (low["id"], high["id"]):
        db.conn.execute(
            """
            UPDATE armies
            SET supply=80,morale=80,loyalty=80,training=80,manpower=20000,salary_rate=1.0
            WHERE id=?
            """,
            (aid,),
        )
    db.conn.execute("UPDATE armies SET name='A低欠饷军', arrears=12.1 WHERE id=?", (low["id"],))
    db.conn.execute("UPDATE armies SET name='Z高欠饷军', arrears=12.9 WHERE id=?", (high["id"],))
    db.conn.commit()
    ordered = [r["name"] for r in db.army_rows(danger_order=True)]
    assert ordered.index("Z高欠饷军") < ordered.index("A低欠饷军")


def test_army_rows_non_danger_sorted_by_theater_name(read_game):
    db, _state, _ = read_game
    rows = db.army_rows(danger_order=False)
    if len(rows) < 2:
        pytest.skip("需≥2 支军队验排序/limit（数据前提）")
    keys = [(str(r["theater"]), str(r["name"])) for r in rows]
    assert keys == sorted(keys)
    assert len(db.army_rows(limit=2, danger_order=False)) == 2


def test_army_report_shows_actual_charge(game):
    """army_report 月饷总额须基于 army_needed（引擎实扣）——格式化金额串出现在真实出口。"""
    from ming_sim.assets import format_money
    from ming_sim.models import monthly_amount

    db, _state, _ = game
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' AND salary_rate>0 "
        "ORDER BY manpower DESC LIMIT 1"
    ).fetchone()["id"]
    db.conn.execute(
        "UPDATE armies SET manpower = manpower + 100000 WHERE id=?", (aid,)
    )
    db.conn.commit()
    total_needed = sum(
        army_needed(r) for r in db.conn.execute("SELECT * FROM armies").fetchall()
    )
    expected = format_money(monthly_amount(total_needed))
    report = db.army_report(limit=20)
    assert expected in report
    assert monthly_amount(total_needed) > 0



def test_army_public_exits_approx_arrears_and_hide_split_accounts(game):
    """#305/D10：分账机器字段不进出口，欠饷事实仍接通 detail。"""
    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id,name FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    db.conn.execute(
        "UPDATE armies SET arrears=12.5, province_pay_arrears=12.5, central_pay_arrears=0 WHERE id=?",
        (row["id"],),
    )
    db.conn.commit()
    name = row["name"]
    detail, roster = db.army_detail(name), db.army_roster(filter_names=[name])
    report = db.army_report(limit=100)
    for text in (detail, report, roster):
        for field in ("province_pay_arrears", "central_pay_arrears"):
            assert field not in text
    db.conn.execute(
        "UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE id=?",
        (row["id"],),
    )
    db.conn.commit()
    assert db.army_detail(name) != detail



def test_army_arrears_presentation_rounds_half_steps_up(game):
    """#305：真实军牌的半档进位；固定月饷，避免欠饷月数干扰。"""

    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id,name FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()

    def _arrears_fact(arrears: float) -> str:
        db.conn.execute(
            "UPDATE armies SET arrears=?, province_pay_arrears=?, central_pay_arrears=0, "
            "manpower=20000, salary_rate=100 WHERE id=?",
            (arrears, arrears, row["id"]),
        )
        db.conn.commit()
        return next(card for card in db.army_payload() if card["id"] == row["id"])["arrears_text"]

    assert _arrears_fact(12.5) == _arrears_fact(15) != _arrears_fact(12)
    assert _arrears_fact(25) == _arrears_fact(30) != _arrears_fact(15)
