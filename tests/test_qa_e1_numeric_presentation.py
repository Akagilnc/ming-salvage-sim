"""Structured budget identity and non-duplication contracts (#1366/#1471).

Numeric truth is asserted on budget rows and ledgers, never parsed from prose.
"""
from __future__ import annotations

from types import SimpleNamespace

import web_app
from ming_sim.flows import apply_fixed_period_flows, compute_budget_lines

def _army_pay_budget_lines(budget):
    return [row for row in budget["国库"]["expense"] if row.get("budget_key") == "army_pay"]


def test_substrate_budget_splits_proposals_without_treasury_cap(game):
    db, state, _ = game
    db.conn.execute(
        "UPDATE armies SET self_funded_pay=1, is_tusi=1, province_pay_share=0, "
        "central_pay_share=0, pay_source_region='', province_pay_arrears=0, "
        "central_pay_arrears=0, arrears=0"
    )
    db.conn.execute(
        "UPDATE armies SET self_funded_pay=0, is_tusi=0, owner_power='ming', "
        "pay_source_region='shaanxi', province_pay_share=0, central_pay_share=1, "
        "manpower=10000, salary_rate=10 WHERE id='guanning'"
    )
    db.conn.execute("UPDATE regions SET fiscal=json_set(fiscal, '$.settle.p.拨付gross', 0)")
    db.conn.execute(
        "UPDATE regions SET fiscal=json_set(fiscal, '$.settle.p.拨付gross', 7) WHERE id='shaanxi'"
    )
    db.conn.commit()

    def proposed_parts():
        return {line["budget_part"]: line["amount"]
                for line in _army_pay_budget_lines(compute_budget_lines(db, state))}

    state.metrics["国库"] = 0
    assert proposed_parts() == {"central": 10, "jingyun": 7}
    state.metrics["国库"] = 100
    assert proposed_parts() == {"central": 10, "jingyun": 7}


def test_renaming_army_pay_budget_line_does_not_double_debit(game, monkeypatch):
    import ming_sim.flows as flows_mod

    db, state, _ = game
    assert db.fiscal_engine() == "substrate_hub"
    real = flows_mod.compute_budget_lines
    renamed = "完全不同的军饷科目名"

    def _renamed(db_, state_, **kwargs):
        budget = real(db_, state_, **kwargs)
        for row in budget["国库"]["expense"]:
            if row.get("budget_key") == "army_pay":
                row["name"] = renamed
        return budget

    monkeypatch.setattr(flows_mod, "compute_budget_lines", _renamed)
    flow_rows = apply_fixed_period_flows(db, state)
    assert not any(row.get("account") == "国库" and row.get("category") == renamed for row in flow_rows)
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM economy_ledger WHERE account='国库' AND category=?", (renamed,),
    ).fetchone()["n"] == 0
    hub_rows = [row for row in flow_rows if row.get("category") == "边饷hub"]
    assert len(hub_rows) == 1
    assert int(hub_rows[0]["paid"]) > 0


def test_player_budget_payload_strips_engineering_notes(read_game):
    """#1471：API 玩家定额行键集恰为 {name, amount}；工程 note/internal 不得下发。"""
    db, state, _ = read_game
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(db=db, state=state)
    eng = compute_budget_lines(db, state)
    assert any(item.get("note") for acc in eng.values()
               for direction in ("income", "expense") for item in acc[direction])
    assert any(item.get("internal") == "substrate_hub"
               for item in eng["国库"]["income"] + eng["国库"]["expense"])
    payload = runtime.budget_payload()
    for account_name in ("国库", "内库"):
        for direction in ("income", "expense"):
            for item in payload[account_name][direction]:
                assert set(item) == {"name", "amount"}
                assert isinstance(item["name"], str)
                assert isinstance(item["amount"], int)


def test_army_payload_arrears_text_is_approximate_not_raw(game):
    db, _state, _ = game
    army_id = db.conn.execute(
        "SELECT id FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    raw = 1.2000000000000002
    db.conn.execute(
        "UPDATE armies SET arrears=?, province_pay_arrears=?, central_pay_arrears=0 WHERE id=?",
        (raw, raw, army_id),
    )
    db.conn.commit()
    card = {army["id"]: army for army in db.army_payload()}[army_id]
    assert "arrears" not in card
    assert isinstance(card["arrears_text"], str) and card["arrears_text"]
