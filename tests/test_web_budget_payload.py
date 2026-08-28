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
