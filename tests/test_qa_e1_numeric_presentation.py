"""包戊 数值呈现钉测（#1334/#1350/#1363/#1383 浮点族 + #1366 预算/警讯口径）。

真缝：
- army_logs.reason → turn_army_summary / previous_summary 路径上的欠发文案
- 省源分账 reason / turn_army_summary delta（#1383 残余）
- API armies.arrears 只读投影（#1363 同源呈现面）
- budget「各军军饷」vs army_report「应发」呈现口径标注
"""

from __future__ import annotations

import json
import re

from types import SimpleNamespace

import web_app
from ming_sim.assets import format_wanliang_amount
from ming_sim.flows import apply_fixed_period_flows, army_needed, compute_budget_lines


# 多于一位小数的 IEEE 残渣（如 1.2000000000000002 / 0.09999999999999964）
_FLOAT_GARBAGE = re.compile(r"\d+\.\d{3,}")
# 奏报口吻：整数或恰好一位小数
_WANLIANG_AMOUNT = re.compile(r"欠发(\d+(?:\.\d)?)万两")
# 省源分账 reason 内嵌万两数额
_PROVINCE_WANLIANG = re.compile(r"(摊新增欠|偿还)(\d+(?:\.\d+)?)万两")
# #1471：玩家预算字段不得泄漏工程注记词
_ENGINEERING_NOTE_TOKENS = ("hub", "旁路", "substrate", "实发率", "可降到")


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


def test_player_budget_payload_strips_engineering_notes(read_game):
    """#1471：API 玩家定额行键集恰为 {name, amount}；工程 note/internal 不得下发。"""
    db, state, _ = read_game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, state=state)

    # 工程侧仍保留注记（flows / fiscal_config 源不丢）
    eng = compute_budget_lines(db, state)
    eng_notes = [
        str(item.get("note") or "")
        for acc in eng.values()
        for direction in ("income", "expense")
        for item in acc[direction]
    ]
    assert any(eng_notes), "compute_budget_lines 工程 note 不得被删空"
    assert any(
        item.get("internal") == "substrate_hub"
        for item in eng["国库"]["income"] + eng["国库"]["expense"]
    ), "flows internal=substrate_hub 工程标记须保留"

    payload = runtime.budget_payload()
    player_texts: list[str] = []
    for account_name in ("国库", "内库"):
        account = payload[account_name]
        for direction in ("income", "expense"):
            for item in account[direction]:
                assert set(item.keys()) == {"name", "amount"}, (
                    f"玩家预算行键集须恰为 name+amount：{item!r}"
                )
                assert "note" not in item
                assert "internal" not in item
                player_texts.append(str(item.get("name") or ""))
                player_texts.append(str(item.get("amount") or ""))

    joined = "\n".join(player_texts)
    for token in _ENGINEERING_NOTE_TOKENS:
        assert token not in joined, (
            f"玩家预算字段泄漏工程词 {token!r}：{joined!r}"
        )


def _seed_province_pay_split_scenario(db) -> None:
    """触发省源分账 reason 真路径（与 fiscal bridge 同源夹具，最小可复现）。"""
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 1, is_tusi = 1, province_pay_share = 0,
            central_pay_share = 0, pay_source_region = '',
            province_pay_arrears = 0, central_pay_arrears = 0, arrears = 0
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 1.0,
            central_pay_share = 0.0, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            station = '福建', manpower = 10000, salary_rate = 5
        WHERE id = 'fujian_navy'
        """
    )
    db.conn.execute(
        """
        UPDATE armies
        SET self_funded_pay = 0, is_tusi = 0, owner_power = 'ming',
            pay_source_region = 'shaanxi', province_pay_share = 0.65,
            central_pay_share = 0.35, province_pay_arrears = 6.5,
            central_pay_arrears = 3.5, arrears = 10,
            station = '北直隶 / 客防', manpower = 10000, salary_rate = 10
        WHERE id = 'shaanxi_army'
        """
    )
    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id = 'shaanxi'"
    ).fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}"))
    fiscal["settle"] = {
        "st": {
            "省库库银": 0,
            "C_地方截留": 0,
            "C_中饱": 0,
            "C_漂没": 0,
            "C_eff损耗": 0,
            "民欠旧赋": 0,
            "军饷欠": 999,
            "官俸欠": 0,
            "宗禄欠": 0,
            "官民田": 0,
            "隐田": 0,
        },
        "p": {
            "正赋应征": 0,
            "三饷应征": 0,
            "火耗率": 0,
            "逋赋率": 0,
            "起运定额": 0,
            "拨付gross": 8,
            "中饱率": 0,
            "漂没率": 0,
            "Due": {"军饷": 999, "官俸": 0, "宗禄": 0, "赈济": 0},
        },
    }
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = 'shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()


def test_province_pay_split_reason_and_summary_have_no_float_garbage(game):
    """#1383 残余：省源分账 reason 真路径 + turn_army_summary delta 无 IEEE 残渣。"""
    db, state, _ = game
    _seed_province_pay_split_scenario(db)
    db.settle_province_tick("shaanxi")

    reasons = [
        str(row["reason"] or "")
        for row in db.conn.execute(
            """
            SELECT reason FROM army_logs
            WHERE field = 'province_pay_arrears'
              AND reason LIKE '%省源军饷分账%'
            """
        ).fetchall()
    ]
    assert reasons, "省源分账真路径应写入 province_pay_arrears reason"

    for reason in reasons:
        assert not _FLOAT_GARBAGE.search(reason), f"省源 reason 含浮点垃圾：{reason}"
        for _kind, amount in _PROVINCE_WANLIANG.findall(reason):
            assert re.fullmatch(r"\d+(\.\d)?", amount), (
                f"省源万两须为整数或一位小数，得 {amount!r} in {reason}"
            )
            # 与 format_wanliang_amount 单真源同形
            raw = float(amount)
            assert amount == format_wanliang_amount(raw), (
                f"省源数额须走 format_wanliang_amount，得 {amount!r}"
            )

    summary = db.turn_army_summary(state.turn)
    assert "省源" in summary or "欠饷" in summary
    assert not _FLOAT_GARBAGE.search(summary), (
        f"turn_army_summary delta/reason 含浮点垃圾：{summary}"
    )


def test_army_payload_arrears_projection_rounds_to_one_decimal(game):
    """#321：API armies.arrears_text 为 approximate 奏报；禁 raw 数与浮点残渣。"""
    from ming_sim.db import _player_army_situation

    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    army_id = row["id"]

    samples = (
        1.2000000000000002,
        1.5217391304347827,
        12.5,
        11.978260869565217,
        0,
        -1.234,
    )
    for raw in samples:
        db.conn.execute(
            "UPDATE armies SET arrears=?, province_pay_arrears=?, central_pay_arrears=0 WHERE id=?",
            (raw, raw, army_id),
        )
        db.conn.commit()
        full = db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()
        expected = _player_army_situation(full, db._army_pay(full))["arrears_text"]
        payload = {army["id"]: army for army in db.army_payload()}
        card = payload[army_id]
        assert "arrears" not in card
        got = card["arrears_text"]
        assert got == expected, f"raw={raw!r} → arrears_text 应得 {expected!r}，得 {got!r}"
        assert not _FLOAT_GARBAGE.search(got), f"arrears_text 仍含浮点残渣：{got!r}"
        # 原始精确小数不得裸出
        if isinstance(raw, float) and raw != int(raw):
            assert str(raw) not in got

    # None → or 0 回落：列 NOT NULL 不可直写，替身 row 走 army_payload 同一投影式
    base = db.conn.execute("SELECT * FROM armies WHERE id=?", (army_id,)).fetchone()
    none_row = {key: base[key] for key in base.keys()}
    none_row["arrears"] = None
    original_rows = db.army_rows
    try:
        db.army_rows = lambda limit=None, danger_order=False: [none_row]  # type: ignore[method-assign]
        payload = {army["id"]: army for army in db.army_payload()}
        got = payload[army_id]["arrears_text"]
        assert got == "无欠饷", f"raw=None → arrears_text 应得 无欠饷，得 {got!r}"
    finally:
        db.army_rows = original_rows  # type: ignore[method-assign]
