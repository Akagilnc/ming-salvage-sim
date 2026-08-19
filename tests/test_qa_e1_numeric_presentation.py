"""包戊 数值呈现钉测（#1334/#1350/#1363/#1383 浮点族 + #1366 预算/警讯口径）。

真缝：
- army_logs.reason → turn_army_summary / previous_summary 路径上的欠发文案
- budget「各军军饷」vs army_report「应发」呈现口径标注
"""

from __future__ import annotations

import re

from ming_sim.flows import apply_fixed_period_flows, army_needed, compute_budget_lines


# 多于一位小数的 IEEE 残渣（如 1.2000000000000002 / 0.09999999999999964）
_FLOAT_GARBAGE = re.compile(r"\d+\.\d{3,}")
# 奏报口吻：整数或恰好一位小数
_WANLIANG_AMOUNT = re.compile(r"欠发(\d+(?:\.\d)?)万两")


def test_army_pay_shortfall_reason_has_no_float_garbage(game):
    """#1334/#1383：真实落账 reason 与 summary 不得出现浮点垃圾小数。"""
    db, state, _ = game
    apply_fixed_period_flows(db, state)

    reasons = [
        str(row["reason"] or "")
        for row in db.conn.execute(
            "SELECT reason FROM army_logs WHERE reason LIKE '%欠发%'"
        ).fetchall()
    ]
    assert reasons, "开局结算应产生中央军饷欠发 reason（国库不足以足额）"

    for reason in reasons:
        assert not _FLOAT_GARBAGE.search(reason), f"reason 含浮点垃圾：{reason}"
        for amount in _WANLIANG_AMOUNT.findall(reason):
            assert re.fullmatch(r"\d+(\.\d)?", amount), (
                f"欠发数额须为整数或一位小数，得 {amount!r} in {reason}"
            )

    summary = db.turn_army_summary(state.turn)
    assert "欠发" in summary
    assert not _FLOAT_GARBAGE.search(summary), f"turn_army_summary 含浮点垃圾：{summary}"


def test_budget_army_pay_and_warning_due_calibers_are_labeled(read_game):
    """#1366：预算各军军饷(hub 实拨)与警讯月应发本不同口径——数不变，呈现标明。"""
    db, state, _ = read_game
    assert db.fiscal_engine() == "substrate_hub"

    budget = compute_budget_lines(db, state)
    army_line = next(
        row for row in budget["国库"]["expense"] if row["name"] == "各军军饷"
    )
    nominal_due = sum(
        army_needed(row)
        for row in db.conn.execute(
            "SELECT * FROM armies WHERE owner_power = 'ming'"
        ).fetchall()
    )
    report = db.army_report(limit=5)

    # 开局两套数本就不同（hub 实拨含中央份额/京运损耗 ≠ 全军名义应发）
    assert army_line["amount"] == 87
    assert nominal_due == 72
    assert f"{nominal_due}" in report or "72万两" in report.replace(" ", "")

    note = str(army_line.get("note") or "")
    assert any(token in note for token in ("实拨", "hub", "中央", "损耗")), (
        f"预算各军军饷 note 须标明 hub/实拨口径，得 {note!r}"
    )
    assert "应发" in report, "army_warning 须标明应发口径"
