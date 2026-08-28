"""包戊 数值呈现钉测（#1334/#1350/#1363/#1383 浮点族 + #1366 预算口径）。

真缝：
- army_logs.reason → turn_army_summary / previous_summary 路径上的欠发文案
- 省源分账 reason / turn_army_summary delta（#1383 残余）
- API armies.arrears_text approximate 投影；raw arrears 键缺席（#1363 同源呈现面）
- budget_key=army_pay 结构化身份、金额口径与改名不双扣（#1366；不锁显示措辞）
"""

from __future__ import annotations

import json
import re

from types import SimpleNamespace
from unittest.mock import patch

import web_app
from ming_sim.assets import format_wanliang_amount
from ming_sim.flows import (
    _substrate_hub_budget_army_pay,
    apply_fixed_period_flows,
    army_needed,
    compute_budget_lines,
)


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


def _army_pay_budget_lines(budget):
    return [
        row for row in budget["国库"]["expense"] if row.get("budget_key") == "army_pay"
    ]


def test_budget_army_pay_typed_identity_and_amounts(read_game):
    """#1366：两引擎各恰一条 army_pay；金额跟现行算法，不靠显示名。"""
    db, state, _ = read_game
    assert db.fiscal_engine() == "substrate_hub"

    substrate_budget = compute_budget_lines(db, state)
    substrate_lines = _army_pay_budget_lines(substrate_budget)
    assert len(substrate_lines) == 1
    assert substrate_lines[0]["amount"] == _substrate_hub_budget_army_pay(db, state)
    assert substrate_lines[0]["amount"] == 87

    # legacy 引擎：金额 = sum(army_needed)，仍是唯一 army_pay 行。
    with patch.object(type(db), "fiscal_engine", return_value="legacy"):
        legacy_budget = compute_budget_lines(db, state)
    legacy_lines = _army_pay_budget_lines(legacy_budget)
    assert len(legacy_lines) == 1
    expected_legacy = sum(
        army_needed(row)
        for row in db.conn.execute(
            "SELECT manpower, salary_rate, owner_power FROM armies "
            "WHERE owner_power='ming'"
        ).fetchall()
    )
    assert legacy_lines[0]["amount"] == expected_legacy
    assert expected_legacy == 72

    # 玩家投影剥离 budget_key，只留 name/amount。
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, state=state)
    payload = runtime.budget_payload()
    player_line = next(
        row for row in payload["国库"]["expense"]
        if row["name"] == substrate_lines[0]["name"]
    )
    assert set(player_line.keys()) == {"name", "amount"}
    assert player_line["amount"] == substrate_lines[0]["amount"]


def test_renaming_army_pay_budget_line_does_not_double_debit(game, monkeypatch):
    """#1366：改 army_pay 显示名不得让定额路径再扣一笔。"""
    import ming_sim.flows as flows_mod

    db, state, _ = game
    assert db.fiscal_engine() == "substrate_hub"

    real = flows_mod.compute_budget_lines

    def _renamed(db_, state_, **kwargs):
        budget = real(db_, state_, **kwargs)
        for row in budget["国库"]["expense"]:
            if row.get("budget_key") == "army_pay":
                row["name"] = "完全不同的军饷科目名"
        return budget

    monkeypatch.setattr(flows_mod, "compute_budget_lines", _renamed)
    flow_rows = apply_fixed_period_flows(db, state)

    renamed = "完全不同的军饷科目名"
    assert not any(
        row.get("account") == "国库" and row.get("category") == renamed
        for row in flow_rows
    )
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM economy_ledger "
        "WHERE account = '国库' AND category = ?",
        (renamed,),
    ).fetchone()["n"] == 0
    hub_rows = [row for row in flow_rows if row.get("category") == "边饷hub"]
    assert len(hub_rows) == 1
    assert int(hub_rows[0]["paid"]) > 0


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
                assert "budget_key" not in item
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


def test_army_payload_arrears_text_is_approximate_not_raw(game):
    """#321：API armies.arrears_text 为 approximate 奏报；禁 raw 键与 IEEE 残渣。"""
    db, _state, _ = game
    row = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()
    army_id = row["id"]
    # 唯一 residue 样本：须命中 _FLOAT_GARBAGE（≥3 位小数）；12.5 一位小数对此正则惰性
    raw = 1.2000000000000002
    db.conn.execute(
        "UPDATE armies SET arrears=?, province_pay_arrears=?, central_pay_arrears=0 WHERE id=?",
        (raw, raw, army_id),
    )
    db.conn.commit()
    card = {army["id"]: army for army in db.army_payload()}[army_id]
    assert "arrears" not in card
    arrears_text = card["arrears_text"]
    assert isinstance(arrears_text, str) and arrears_text
    assert not _FLOAT_GARBAGE.search(arrears_text), (
        f"arrears_text 含 IEEE 残渣：{arrears_text!r}"
    )
