"""#173 显示口径：军饷呈现端从退役的 maintenance_per_turn 迁到引擎实扣的 army_needed。

#44 后引擎按 army_needed=ceil(manpower×salary_rate/10000) 扣应发，但 army_payload/army_report/
欠饷月数/simulator TSV 仍显示 maintenance_per_turn → 玩家与审计大臣 LLM 看到「显示≠实扣」
（京营显示 7 实扣 9），项目「账本一致」机制会误判。本 slice 把呈现端统一到 army_needed。
字段去留（删 maintenance_per_turn 列）= 设计决策，本 slice 留列、只改呈现，不删列。
"""

from __future__ import annotations

from ming_sim.flows import army_needed


def test_army_payload_exposes_army_needed(game):
    """army_payload 须暴露引擎实扣应发 army_needed（供 web/LLM 呈现「月饷」），与 flows.army_needed 一致。"""
    db, state, _ = game
    payload = db.army_payload()
    assert payload, "应有军队"
    by_id = {p["id"]: p for p in payload}
    for row in db.conn.execute("SELECT * FROM armies").fetchall():
        p = by_id[row["id"]]
        assert "army_needed" in p, "army_payload 须含 army_needed（实扣应发）"
        assert p["army_needed"] == army_needed(row), (
            f"{row['id']} army_payload.army_needed={p['army_needed']} 应=引擎 {army_needed(row)}"
        )


def test_army_report_shows_actual_charge_not_maintenance(game):
    """army_report 的月饷总额/欠饷月数须基于 army_needed（实扣），非退役 maintenance_per_turn。
    构造一支 maintenance≠army_needed 的明军（扩军使 needed 涨、maint 不动），断言报告里出现实扣值。"""
    db, state, _ = game
    # 取一支明军，扩兵让 army_needed 明显 > maintenance_per_turn（制造显示≠实扣差）。
    row = db.conn.execute(
        "SELECT id, manpower, maintenance_per_turn, salary_rate FROM armies "
        "WHERE owner_power='ming' AND salary_rate>0 ORDER BY manpower DESC LIMIT 1"
    ).fetchone()
    aid = row["id"]
    db.conn.execute("UPDATE armies SET manpower = manpower + 100000 WHERE id=?", (aid,))
    db.conn.commit()
    full = db.conn.execute("SELECT * FROM armies WHERE id=?", (aid,)).fetchone()
    needed = army_needed(full)
    maint = int(full["maintenance_per_turn"])
    assert needed != maint, f"前提：扩军后 needed({needed})应≠maint({maint})"
    # army_report 月饷总额应反映实扣（army_needed 之和），不应等于 maintenance 之和。
    total_needed = sum(army_needed(r) for r in db.conn.execute("SELECT * FROM armies").fetchall())
    total_maint = db.conn.execute("SELECT SUM(maintenance_per_turn) AS t FROM armies").fetchone()["t"]
    assert total_needed != total_maint, "前提：总实扣应≠总 maintenance"
    report = db.army_report(limit=20)
    assert f"{total_needed}" in report, (
        f"army_report 月饷总额应=实扣总和 {total_needed}，实际报告未含该值（仍按 maintenance {total_maint}？）"
    )
