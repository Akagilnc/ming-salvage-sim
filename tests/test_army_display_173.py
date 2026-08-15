"""#173 显示口径：军饷呈现端从退役的 maintenance_per_turn 迁到引擎实扣的 army_needed。

#44 后引擎按 army_needed=ceil(manpower×salary_rate/10000) 扣应发；呈现端（army_payload/
army_report/欠饷月数/simulator TSV）统一到 army_needed，玩家与审计大臣 LLM 看到的月饷=实扣。
#173 删列 PR 已物理移除 maintenance_per_turn 列，army_needed 是月饷唯一真源。

#1185：不锁中文奏报措辞；真实出口差分/可数域值 tracer。
"""

from __future__ import annotations

import re

import pytest

from ming_sim.flows import army_needed


def test_army_payload_exposes_army_needed(read_game):
    """army_payload 须暴露引擎实扣应发 army_needed（供 web/LLM 呈现「月饷」），与 flows.army_needed 一致。"""
    db, _state, _ = read_game
    payload = db.army_payload()
    assert payload, "应有军队"
    by_id = {p["id"]: p for p in payload}
    for row in db.conn.execute("SELECT * FROM armies").fetchall():
        p = by_id[row["id"]]
        assert "army_needed" in p, "army_payload 须含 army_needed（实扣应发）"
        assert p["army_needed"] == army_needed(row), (
            f"{row['id']} army_payload.army_needed={p['army_needed']} 应=引擎 {army_needed(row)}"
        )


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
    """#305/D10：detail/report/roster 走欠饷近似；分账字段与抽象裸分不进真实出口。"""
    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id,name FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    # 受控裸分 token：不与兵额/合计饷银等合法可数事实混淆
    scores = dict(loyalty=67, supply=69, morale=61, training=59, equipment=53, mobility=47)
    db.conn.execute(
        "UPDATE armies SET arrears=63, province_pay_arrears=17, central_pay_arrears=46,"
        "manpower=20000, cannon_equipment=0, firearm_equipment=0,"
        "loyalty=?, supply=?, morale=?, training=?, equipment=?, mobility=? WHERE id=?",
        (*scores.values(), row["id"]),
    )
    db.conn.commit()
    name = row["name"]
    detail, roster = db.army_detail(name), db.army_roster(filter_names=[name])
    report = db.army_report(limit=100)
    # 按出口结构隔离目标军字段（report 只扫目标段，避开合计饷银）
    seg = next(p for p in report.split("：", 1)[-1].split("；") if p.startswith(name + "："))
    exits = (detail, seg, roster)
    joined = "\n".join(exits)
    assert name in detail and "63" not in joined
    for forbidden in ("province_pay_arrears", "central_pay_arrears", "省份额欠", "中央份额欠"):
        assert forbidden not in joined
    db.conn.execute(
        "UPDATE armies SET arrears=0, province_pay_arrears=0, central_pay_arrears=0 WHERE id=?",
        (row["id"],),
    )
    db.conn.commit()
    assert db.army_detail(name) != detail
    for text in exits:
        for bare in scores.values():
            assert not re.search(rf"(?<!\d){bare}(?!\d)", text)


def test_army_arrears_presentation_rounds_half_steps_up(game):
    """#305：半档进位只比欠饷近似事实（不拿含 pay_months 的整份 detail 当 oracle）。"""
    from ming_sim.db import _approx_wanliang

    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id,name FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()

    def _arrears_fact(arrears: float) -> str:
        db.conn.execute(
            "UPDATE armies SET arrears=?, province_pay_arrears=?, central_pay_arrears=0 WHERE id=?",
            (arrears, arrears, row["id"]),
        )
        db.conn.commit()
        approx = _approx_wanliang(arrears)
        assert approx in db.army_detail(row["name"])
        return approx

    assert _arrears_fact(12.5) == _arrears_fact(15) != _arrears_fact(12)
    assert _arrears_fact(25) == _arrears_fact(30) != _arrears_fact(15)


def test_army_payload_preserves_fractional_arrears_for_web_rendering(game):
    """#305 cmr：web 只读 army_payload；12.5 万两不可被截成 12。"""
    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    db.conn.execute(
        """
        UPDATE armies
        SET arrears=12.5, province_pay_arrears=12.5, central_pay_arrears=0
        WHERE id=?
        """,
        (row["id"],),
    )
    db.conn.commit()

    payload = {army["id"]: army for army in db.army_payload()}
    assert payload[row["id"]]["arrears"] == pytest.approx(12.5)


def test_simulator_payload_exposes_army_needed(game):
    """simulator/extractor 盘面须暴露引擎实扣 army_needed。"""
    from ming_sim.simulation import build_simulator_payload, _extractor_context_payload

    db, _state, _ = game
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' AND salary_rate>0 LIMIT 1"
    ).fetchone()["id"]
    db.conn.execute(
        "UPDATE armies SET manpower=manpower+100000 WHERE id=?", (aid,)
    )
    db.conn.commit()
    full = db.conn.execute("SELECT * FROM armies WHERE id=?", (aid,)).fetchone()
    name = full["name"]
    expected = army_needed(full)

    for payload in (
        build_simulator_payload(_state, db, "x", "y"),
        _extractor_context_payload(db, _state, "y", "x"),
    ):
        armies = payload["armies"]
        assert "army_needed" in armies["cols"]
        ni = armies["cols"].index("army_needed")
        nidx = armies["cols"].index("name")
        row = next(r for r in armies["rows"] if r[nidx] == name)
        assert int(row[ni]) == expected


def test_danger_order_uses_army_needed_for_arrears_months(game):
    """army_rows(danger_order=True) 欠饷月数归一须按 army_needed。"""
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
    """danger_order 欠饷月数排序键不得截断小数。"""
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
    db.conn.execute(
        "UPDATE armies SET name='A低欠饷军', arrears=12.1 WHERE id=?", (low["id"],)
    )
    db.conn.execute(
        "UPDATE armies SET name='Z高欠饷军', arrears=12.9 WHERE id=?", (high["id"],)
    )
    db.conn.commit()

    ordered = [r["name"] for r in db.army_rows(danger_order=True)]
    assert ordered.index("Z高欠饷军") < ordered.index("A低欠饷军")


def test_army_rows_non_danger_sorted_by_theater_name(read_game):
    """非 danger 路按 theater,name 升序；limit 生效。"""
    db, _state, _ = read_game
    rows = db.army_rows(danger_order=False)
    if len(rows) < 2:
        pytest.skip("需≥2 支军队验排序/limit（数据前提）")
    keys = [(str(r["theater"]), str(r["name"])) for r in rows]
    assert keys == sorted(keys)
    assert len(db.army_rows(limit=2, danger_order=False)) == 2
