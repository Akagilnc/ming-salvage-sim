from types import SimpleNamespace

import web_app
from ming_sim.flows import compute_budget_lines
from tests.fiscal_test_utils import zero_non_meta_fiscal_config


def _player_army_pay_amount(payload, db, state):
    """玩家投影无 budget_key：先从源侧取 army_pay 行 name，再对齐 amount。"""
    src = next(
        row for row in compute_budget_lines(db, state)["国库"]["expense"]
        if row.get("budget_key") == "army_pay"
    )
    return next(
        row["amount"] for row in payload["国库"]["expense"] if row["name"] == src["name"]
    )


def test_budget_payload_filters_central_army_pay_fixed_flow(game):
    db, state, _content = game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, state=state)

    db.record_issue_economy_move(state, "国库", -3, "中央军饷", "测试中央军饷")
    db.record_issue_economy_move(state, "国库", -2, "临时调拨", "测试临时调拨")
    state.turn += 1

    payload = runtime.budget_payload()

    categories = [row["category"] for row in payload["国库"]["movements"]]
    assert "中央军饷" not in categories
    assert "临时调拨" in categories


def test_budget_payload_filters_real_substrate_hub_fixed_flow(game):
    from ming_sim.flows import apply_fixed_period_flows

    db, state, _content = game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, state=state)
    state.metrics["国库"] = 5
    db.save_state(state)
    db.conn.execute("UPDATE buildings SET output_amount = 0, maintenance = 0")
    zero_non_meta_fiscal_config(db)
    db.conn.execute(
        """
        UPDATE regions
        SET tax_per_turn = 0,
            fiscal = json_set(
                fiscal, '$.huang_tian', 0, '$.liao_xiang', 0,
                '$.salt_tax', 0, '$.commerce_tax', 0,
                '$.settle.p.拨付gross', 0
            )
        """
    )
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
            pay_source_region = 'shaanxi', province_pay_share = 0,
            central_pay_share = 1, province_pay_arrears = 0,
            central_pay_arrears = 0, arrears = 0,
            manpower = 10000, salary_rate = 10
        WHERE id = 'guanning'
        """
    )
    db.conn.commit()

    pre_payload = runtime.budget_payload()
    army_pay = _player_army_pay_amount(pre_payload, db, state)
    assert army_pay == 5

    apply_fixed_period_flows(db, state)
    state.turn += 1

    payload = runtime.budget_payload()

    ledger_categories = [
        row["category"]
        for row in db.conn.execute(
            "SELECT category FROM economy_ledger WHERE turn = ?",
            (state.turn - 1,),
        ).fetchall()
    ]
    categories = [row["category"] for row in payload["国库"]["movements"]]
    assert "边饷hub" in ledger_categories
    assert "边饷hub" not in categories
    assert payload["国库"]["movements_total"] == 0

    state.metrics["国库"] = 20
    db.save_state(state)
    db.conn.execute("UPDATE armies SET manpower = 20000 WHERE id = 'guanning'")
    db.conn.commit()

    updated_payload = runtime.budget_payload()
    updated_army_pay = _player_army_pay_amount(updated_payload, db, state)
    assert updated_army_pay == 20
