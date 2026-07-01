from types import SimpleNamespace

import web_app


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
    db.conn.execute(
        """
        UPDATE fiscal_config
        SET value = 0
        WHERE kind != 'meta'
        """
    )
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
    army_pay = next(
        row["amount"] for row in pre_payload["国库"]["expense"]
        if row["name"] == "各军军饷"
    )
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
