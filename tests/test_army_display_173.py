"""#173 显示口径：军饷呈现端从退役的 maintenance_per_turn 迁到引擎实扣的 army_needed。

#44 后引擎按 army_needed=ceil(manpower×salary_rate/10000) 扣应发；呈现端（army_payload/
army_report/欠饷月数/simulator TSV）统一到 army_needed，玩家与审计大臣 LLM 看到的月饷=实扣。
#173 删列 PR 已物理移除 maintenance_per_turn 列，army_needed 是月饷唯一真源。
"""

from __future__ import annotations

import pytest

from ming_sim.flows import army_needed


def test_army_payload_exposes_army_needed(game):
    """army_payload 须暴露引擎实扣应发 army_needed（供 web/LLM 呈现「月饷」），与 flows.army_needed 一致。"""
    db, _state, _ = game
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
    """army_report 的月饷总额须基于 army_needed（引擎实扣）——#173 删 maintenance 后 army_needed 是
    月饷唯一真源。扩军使 needed 涨，断言报告里出现实扣总额（格式化串，避免裸数字子串脆性）。"""
    db, _state, _ = game
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' AND salary_rate>0 ORDER BY manpower DESC LIMIT 1"
    ).fetchone()["id"]
    db.conn.execute("UPDATE armies SET manpower = manpower + 100000 WHERE id=?", (aid,))
    db.conn.commit()
    total_needed = sum(army_needed(r) for r in db.conn.execute("SELECT * FROM armies").fetchall())
    report = db.army_report(limit=20)
    from ming_sim.assets import format_money
    from ming_sim.models import monthly_amount
    expected = format_money(monthly_amount(total_needed))
    assert expected in report, f"army_report 月饷总额应=实扣总和格式化『{expected}』"


def test_simulator_payload_exposes_army_needed(game):
    """#173 cmr（codex high + Claude medium concur）：simulator/extractor 盘面（裁判/审计大臣读的 TSV）
    须暴露引擎实扣 army_needed，否则审计大臣读到的月饷≠实扣、「账本一致」机制误判。
    #173：maintenance_per_turn 列已删，army_needed 列是月应发唯一真源。"""
    from ming_sim.simulation import build_simulator_payload, _extractor_context_payload
    db, _state, _ = game
    # 扩军造可观测的 army_needed 变化。
    aid = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' AND salary_rate>0 LIMIT 1"
    ).fetchone()["id"]
    db.conn.execute("UPDATE armies SET manpower=manpower+100000 WHERE id=?", (aid,))
    db.conn.commit()
    full = db.conn.execute("SELECT * FROM armies WHERE id=?", (aid,)).fetchone()
    name = full["name"]
    expected = army_needed(full)

    for payload in (
        build_simulator_payload(_state, db, "x", "y"),
        _extractor_context_payload(db, _state, "y", "x"),
    ):
        armies = payload["armies"]
        assert "army_needed" in armies["cols"], "simulator/extractor 盘面须含 army_needed 列"
        ni = armies["cols"].index("army_needed")
        nidx = armies["cols"].index("name")
        row = next(r for r in armies["rows"] if r[nidx] == name)
        assert int(row[ni]) == expected, (
            f"simulator 盘面 {name} army_needed={row[ni]} 应=引擎 {expected}"
        )


def test_danger_order_uses_army_needed_for_arrears_months(game):
    """#173 cmr（Claude medium 测试覆盖）：army_rows(danger_order=True) 的欠饷月数归一须按 army_needed
    （非退役 maintenance）。两明军同短板/同 arrears、唯 salary_rate 不同（→army_needed 不同）：
    army_needed 低（欠饷月数高）者更危、排更前。锁 SQL ORDER BY→Python sorted 重构的归一口径。"""
    db, _state, _ = game
    rows = db.conn.execute(
        "SELECT id,name FROM armies WHERE owner_power='ming' AND salary_rate>0 LIMIT 2"
    ).fetchall()
    if len(rows) < 2:
        pytest.skip("需≥2 支 salary_rate>0 的明军作排序对比（数据前提）")
    a, b = rows
    for aid in (a["id"], b["id"]):
        db.conn.execute(
            "UPDATE armies SET supply=80,morale=80,loyalty=80,training=80,arrears=50,manpower=20000 WHERE id=?",
            (aid,),
        )
    db.conn.execute("UPDATE armies SET salary_rate=5.0 WHERE id=?", (a["id"],))   # army_needed=10→月数低
    db.conn.execute("UPDATE armies SET salary_rate=0.5 WHERE id=?", (b["id"],))   # army_needed=1→月数高→更危
    db.conn.commit()
    ordered = [r["name"] for r in db.army_rows(danger_order=True)]
    assert ordered.index(b["name"]) < ordered.index(a["name"]), (
        f"欠饷月数高(army_needed 低)者应排更前(更危)；danger 归一须用 army_needed。序={ordered[:6]}"
    )


def test_army_rows_non_danger_sorted_by_theater_name(game):
    """#173 cmr：非 danger 路（走 SQL ORDER BY theater,name）排序保持原语义、limit 生效。"""
    db, _state, _ = game
    rows = db.army_rows(danger_order=False)
    if len(rows) < 2:
        pytest.skip("需≥2 支军队验排序/limit（数据前提）")
    keys = [(str(r["theater"]), str(r["name"])) for r in rows]
    assert keys == sorted(keys), "非 danger 路应按 theater,name 升序"
    assert len(db.army_rows(limit=2, danger_order=False)) == 2, "limit 应生效"
