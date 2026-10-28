"""Medium: month forks and durable recovery through HTTP actions and CLI reads."""

import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying
from tests.test_month import GUOKU_ORDER
from tests.test_read_budget import measure_reads
from tests.test_secrets import _declaration_prompt

RECORDED = Path(__file__).parent / "recorded"
FUNDED_AFFAIRS = (
    ("陕西专款", "国库", "funded_affair"), ("军饷", "国库", "funded_army"),
    ("官俸_base", "国库", "funded_salary"), ("官俸_base", "内库", "funded_private_salary"),
)


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize("option,forecast_failure,game_db", [
    (0, False, "rejected_night"), (1, False, "rejected_month"),
    (2, False, "rejected_month"), (0, True, "rejected_night"),
], indirect=["game_db"])
def test_rejected_decree_is_forced_withdrawn_or_held(game_db, steps, audit, option, forecast_failure):
    received = []
    if forecast_failure:
        steps["month_final"] = replaying([RuntimeError("candidate unavailable")] * 5 + [(RECORDED / "simulation.txt").read_text()] * 4, received)
        steps["gazette"] = replaying([RuntimeError("gazette unavailable"), *[(RECORDED / "gazette.txt").read_text()] * 2])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        before = audit(game_db)
        if option == 0:
            assert client.get("/state").json()["game"]["petitions"] == []
            assert not [f for f in before["facts"] if f["kind"] in {"month_draft", "month_final", "simulation"}]
            client.post("/actions", json={"action": "month"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 10
        assert len(state["petitions"]) == 1
        petition = state["petitions"][0]
        assert petition["options"] == ["强颁", "收回", "留中", "御笔强推"]
        ledger = audit(game_db)
        assert len([f for f in ledger["facts"] if f["kind"] == "forecast"]) == (0 if forecast_failure else 4)
        assert not [f for f in ledger["facts"] if f["kind"] in {"endorsed", "month_final"}]
        client.post("/actions", json={"action": "choose", "petition": petition["id"], "option": option}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        if forecast_failure:
            assert client.get("/state").json()["game"]["failure"]["payload"]["type"] == "RuntimeError"
            for final_exists in (False, True):
                assert bool([f for f in audit(game_db)["facts"] if f["kind"] == "month_final"]) == final_exists
                client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
                client.post("/actions", json={"action": "retry"}).raise_for_status()
                client.portal.call(client.app.state.web.game.drain)
                assert len(received) == 6
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["failure"], state["petitions"]) == (11, None, [])
        assert client.post("/actions", json={"action": "choose", "petition": petition["id"], "option": option}).status_code == 400
        ledger = audit(game_db)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        assert len([f for f in ledger["facts"] if f["kind"] == "declaration"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == int(option == 0)
        assert len([f for f in ledger["facts"] if f["kind"] == "interim"]) == int(option == 0)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["date"]["month"] == 12
        assert len([f for f in audit(game_db)["facts"] if f["kind"] == "deliberation"]) == 1


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize("game_db", ["endorsed_month"], indirect=True)
@pytest.mark.parametrize("case", ["approved", "rejected", "retry", "reopen"])
def test_imperial_backing_reconsiders_the_original_decree(game_db, steps, audit, clock, case):
    received = []
    verdict = "deliberation_rejected.txt" if case == "rejected" else "deliberation.txt"
    steps["deliberation"] = replaying(
        ([TimeoutError()] * 3 if case in {"retry", "reopen"} else [])
        + [(RECORDED / verdict).read_text()], received,
    )
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        ledger = audit(game_db)
        petition = {"id": next(f["detail"]["decision_key"]["petition_id"] for f in ledger["facts"] if f["kind"] == "endorsed")}
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        assert len([f for f in ledger["facts"] if f["kind"] == "deliberation"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "endorsed"]) == 1
        assert decree["data"]["endorsements"] == [{
            "endorser": "御笔", "form": "御笔手敕",
            "decision_key": {"petition_id": petition["id"], "option": 3},
        }]
        assert not [f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]
        assert (client.get("/state").json()["game"]["date"]["month"], received) == (11, [])
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        if case in {"retry", "reopen"}:
            stopped = client.get("/state").json()["game"]
            assert stopped["date"]["month"] == 11
            assert stopped["failure"]["payload"]["type"] == "TimeoutError"
            assert len([f for f in audit(game_db)["facts"] if f["kind"] == "month_draft"]) == 1
            if case == "reopen":
                client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
            client.post("/actions", json={"action": "retry"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["failure"], state["petitions"]) == (12, None, [])
        ledger = audit(game_db)
        verdicts = [f["detail"] for f in ledger["facts"] if f["kind"] == "deliberation"]
        assert [(v["date"]["month"], v["decision_key"]) for v in verdicts] == [
            (10, None), (11, {"petition_id": petition["id"], "option": 3}),
        ]
        assert len([f for f in ledger["facts"] if f["kind"] == "petition"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == int(case != "rejected")
        assert len([f for f in ledger["facts"] if f["kind"] == "endorsed"]) == 1
        assert json.loads(received[-1].parts[0].content)["context"]["decree"]["data"]["endorsements"] == decree["data"]["endorsements"]
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert len([f for f in audit(game_db)["facts"] if f["kind"] == "deliberation"]) == 2


@pytest.mark.parametrize("game_db", ["interim_backed_night"], indirect=True)
@pytest.mark.parametrize("case", ["approved", "withdrawn", "held", "vital"])
def test_interim_costs_follow_promulgation_not_backing(game_db, steps, audit, case):
    rejected = case != "approved"
    replies = json.loads((RECORDED / "night_interim.json").read_text())["replies"]
    steps["NightDeclaration"] = replaying(replies)
    steps["deliberation"] = replaying([(RECORDED / ("deliberation_vital.txt" if case == "vital" else "deliberation_rejected.txt" if rejected else "deliberation.txt")).read_text()])
    steps["Declaration"] = replaying(json.loads((RECORDED / f"month_interim_{'rejected' if rejected else 'approved'}.json").read_text())["replies"])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["petitions"] == []
        client.post("/actions", json={"action": "month"}).raise_for_status()
        if rejected:
            petition = client.get("/state").json()["game"]["petitions"][0]
            assert petition["options"] == (["收回", "留中"] if case == "vital" else ["强颁", "收回", "留中"])
            client.post("/actions", json={"action": "choose", "petition": petition["id"], "option": 0 if case == "vital" else 2 if case == "held" else 1}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["failure"], state["petitions"]) == (11, None, [])
        ledger = audit(game_db)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        assert len([f for f in ledger["facts"] if f["kind"] == "interim" and f["entity_id"] == decree["id"]]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == int(not rejected)
        assert len([f for f in ledger["facts"] if f["kind"] == "attempted" and f["entity_id"] == decree["id"]]) == int(rejected)
        effects = [f for f in ledger["facts"] if f["kind"] == "changed" and f["detail"].get("origin_ref") == decree["id"]]
        assert len([f for f in effects if "imperial_prestige" in f["detail"]["actual"]]) == int(not rejected)
        assert any("satisfaction" in f["detail"]["actual"] for f in effects)
        assert len({f["entity_id"] for f in effects if "satisfaction" in f["detail"]["actual"]}) == len([f for f in effects if "satisfaction" in f["detail"]["actual"]])
        if rejected:
            assert not [f for f in effects if "taels" in f["detail"]["actual"]]
        steps["Declaration"] = replaying([(RECORDED / "month_empty.txt").read_text()])
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert len([f for f in audit(game_db)["facts"] if f["kind"] == "interim"]) == 1


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("game_db", ["two_nights"], indirect=True)
@pytest.mark.parametrize("interrupt", [False, True])
def test_two_nights_feed_world_and_arrivals_wait_for_audience(tmp_path, game_db, steps, audit, interrupt):
    received = []
    steps["simulation"] = replaying([(RECORDED / "simulation.txt").read_text()] * 2, received)
    declarations = []
    steps["Declaration"] = replaying([(RECORDED / "month_journey_dates.json").read_text(), (RECORDED / "month_decree_money.txt").read_text()], declarations)
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "load", "save": game_db.name}).json()["save"]
        ledger = audit(tmp_path / save)
        nights = {e["id"] for e in ledger["entities"] if e["kind"] == "night"}
        assert not [f for f in ledger["facts"] if f["kind"] in {"simulation", "month_draft", "month_final"}]
        assert len(nights) == 2
        observed = []
        steps["gazette"] = replaying(lambda _: observed.append(audit(tmp_path / save)) or (TimeoutError() if interrupt and len(observed) <= 3 else (RECORDED / "gazette.txt").read_text()))
        for month in (11, 12):
            client.post("/actions", json={"action": "month"})
            if interrupt and month == 11:
                stopped = client.get("/state").json()["game"]
                assert stopped["failure"] is not None and stopped["date"]["month"] == 10
                client.post("/actions", json={"action": "load", "save": save})
                client.post("/actions", json={"action": "retry"})
            state = client.get("/state").json()["game"]
            assert (state["date"]["month"], state["failure"]) == (month, None)
            assert json.loads(received[-1].parts[0].content)["context"]["arrivals"] == (
                [] if month == 11 else [{"person": "徐光启", "destination": "北直隶 / 京师",
                                         "date": {"year": 1627, "month": 11, "day": 16}}]
            )
            ledger = audit(tmp_path / save)
            decrees = {e["id"] for e in ledger["entities"] if e["kind"] == "decree"}
            assert {d["decree"]["id"] for d in json.loads(received[-1].parts[0].content)["context"]["decrees"]} == (decrees if month == 11 else set())
            assert {d["decree"]["id"] for d in _declaration_prompt(declarations[-1:])["decrees"]} == decrees
            assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] in decrees]) == len(decrees)
            if month == 12:
                sources = _declaration_prompt(declarations[-1:])["decrees"]
                assert all(set(d["decree"]) == {"id", "kind", "key", "data"} and d["decree"]["data"] == {"secret": False} and d["mode"] is None for d in sources)
                assert not [f for f in ledger["facts"] if f["kind"] == "unhandled"]
                movement = [f for f in ledger["facts"] if f["kind"] == "received" or (f["kind"] == "changed" and "taels" in f["detail"]["actual"])]
                assert [(f["kind"], f["detail"]["actual"]) for f in movement] == [("changed", {"taels": -300000}), ("received", 300000)]
                assert {f["detail"]["origin_ref"] for f in movement} == {sources[0]["decree"]["id"]}
                assert len([f for f in ledger["facts"] if f["kind"] == "deliberation"]) == len(decrees)
            movement = [f for f in ledger["facts"] if f["kind"] == "arrived"]
            assert movement and all(f in observed[-1]["facts"] for f in movement)
            assert len(movement) == (2 if month == 12 else 1)
            if interrupt:
                assert all(f in observed[0]["facts"] for f in movement if f["detail"]["date"]["month"] == 10)
            for person in [
                e
                for e in ledger["entities"]
                if e["kind"] == "person" and e["key"] in {"毕自严", "徐光启"}
            ]:
                assert person["data"]["arrival_date"] == (
                    {"year": 1627, "month": 11, "day": 16} if person["key"] == "徐光启" and month == 11
                    else None
                )
                if person["data"]["arrival_date"] is None:
                    assert person["data"]["departure_date"] is None
                    assert person["data"]["travel_speed"] is None
                assert person["data"]["location"] == (
                    "南直隶 / 南京" if person["key"] == "徐光启" and month == 11 else "北直隶 / 京师"
                )
                assert person["data"]["waiting_audience"] == (person["key"] == "毕自严" or month == 12)
                assert person["key"] not in state["night"]["hall"]
            client.post("/actions", json={"action": "load", "save": save})
            assert audit(tmp_path / save) == ledger
        prior = [e for e in ledger["entities"] if e["kind"] == "night"]
        received = []
        steps["scene"] = replaying(
            [ModelResponse(parts=[ToolCallPart("read_records", {"kind": "night", "key": e["key"]}, tool_call_id=e["id"]) for e in prior]),
             *ModelMessagesTypeAdapter.validate_json((RECORDED / "travel_admission.json").read_bytes())], received,
        )
        client.post("/actions", json={"action": "open"})
        client.post("/actions", json={"action": "say", "words": "宣毕自严、徐光启入殿。"})
        results = {p.tool_call_id: p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == "read_records"}
        for night in prior:
            data = results[night["id"]]["entities"][0]["data"]
            assert data["date"] == {"year": 1627, "month": 10}
            assert {t["id"] for t in data["turns"]} == {f["detail"]["id"] for f in ledger["facts"] if f["entity_id"] == night["id"] and f["kind"] == "turn"}
            assert all("hall" in t for t in data["turns"])
        assert {"毕自严", "徐光启"} <= set(client.get("/state").json()["game"]["night"]["hall"])
        assert not any(e["data"]["waiting_audience"] for e in audit(tmp_path / save)["entities"] if e["kind"] == "person" and e["key"] in {"毕自严", "徐光启"})


@pytest.mark.parametrize("case,game_db", [
    pytest.param((case, *FUNDED_AFFAIRS[0][:2]), FUNDED_AFFAIRS[0][2] if case in {"regular", "reduce", "stop", "reorder"} else "opening_db", id=case)
    for case in ("regular", "until", "factor", "defer", "reduce", "stop", "reorder", "shortage", "resume", "invalid_account")
] + [pytest.param(("reorder", *source[:2]), source[2], id=f"reorder-{source[0]}-{source[1]}") for source in FUNDED_AFFAIRS[1:]]
  + [pytest.param(("switch", *FUNDED_AFFAIRS[2][:2]), FUNDED_AFFAIRS[2][2], id="switch-官俸_base")], indirect=["game_db"])
def test_month_pays_affair_from_declaration_month(game_db, steps, audit, clock, case):
    case, name, account = case
    funding = {"amount": 500000, "account": account, **({"until": {"year": 1627, "month": 11}} if case == "until" else {})}
    shared = case in {"regular", "reduce", "stop", "reorder", "switch"}
    declaration = {"facts": [] if shared else [{"entity_type": "affair", "entity": name, "create": True, "changes": [{"field": "monthly_funding", "value": funding}], "text": "每月拨五十万两"}]}
    if case in {"factor", "defer"}:
        declaration["facts"][0]["changes"].append({"field": "payment_policy", "value": {case: 0.5, "until": {"year": 1627, "month": 11}}})
    if case == "shortage":
        declaration["facts"].append({"entity_type": "account", "entity": "国库", "create": False, "changes": [{"field": "taels", "value": -3100000, "counterpart": {"entity_type": "account", "entity": "内库"}}], "text": "移库"})
        funding["amount"] = 100000000
        declaration["facts"].append({"entity_type": "account", "entity": "国库", "create": False,
            "changes": [{"field": "payment_order", "value": [*reversed(GUOKU_ORDER), {"entity_type": "affair", "entity": name}]}], "text": "改序"})
    received = []
    steps["Declaration"] = replaying(
        [json.dumps({"facts": [{"entity_type": "affair", "entity": "陕西专款", "create": True, "changes": [{"field": "monthly_funding", "value": {**funding, "account": "太仓假名"}}], "text": "专款"}]}, ensure_ascii=False), json.dumps(declaration, ensure_ascii=False)]
        if case == "invalid_account" else lambda _: json.dumps(declaration, ensure_ascii=False), received,
    )
    if case == "resume":
        steps["gazette"] = replaying([TimeoutError()] * 3 + [(RECORDED / "gazette.txt").read_text()])
    with (
        measure_reads() if case == "regular" else nullcontext() as reads,
        TestClient(create_app(game_db.parent)) as client,
    ):
        client.post("/actions", json={"action": "load", "save": game_db.name})
        for index in range(1 if case == "invalid_account" else 2 if name != "陕西专款" else 3):
            # Session nodes run the first month from the opening through HTTP;
            # every branch asserts that same immutable result.
            if index != 0 or not shared:
                client.post("/actions", json={"action": "month"})
            if case == "resume" and index == 0:
                state = client.get("/state").json()["game"]
                assert state["failure"] is not None and state["date"]["month"] == 10
                client.post("/actions", json={"action": "load", "save": game_db.name})
                client.post("/actions", json={"action": "retry"})
                steps["gazette"] = TestModel(call_tools=[], custom_output_text=(RECORDED / "gazette.txt").read_text())
            assert client.get("/state").json()["game"]["failure"] is None
            ledger = audit(game_db)
            rows = {(e["kind"], e["key"]): e["data"] for e in ledger["entities"]}
            assert {f["entity_id"] for f in ledger["facts"] if f["kind"] == "monthly_payment"} >= {
                e["id"] for e in ledger["entities"] if e["kind"] == "fiscal" and e["data"].get("direction") == "expense"
            }
            payments = [f["detail"] for f in ledger["facts"] if f["kind"] == "monthly_payment" and f["detail"]["recipient"] == name and f["entity_id"] == next(e["id"] for e in ledger["entities"] if e["kind"] == "affair")]
            expected = {"factor": [25, 25, 50], "defer": [25, 25, 50], "until": [50, 50, 0], "stop": [50, 0, 0], "reduce": [50, 20, 20]}.get(case, [50, 50, 50])
            assert len(payments) == index + 1
            if case == "shortage":
                assert payments[-1]["paid"] < payments[-1]["due"]
                assert rows[("account", "国库")]["taels"] == 0
                assert all(f["detail"]["unpaid"] == 0 for f in ledger["facts"] if f["kind"] == "monthly_payment" and f["detail"]["account"] == "国库" and f["detail"]["recipient"] != name)
            else:
                assert [p["paid"] for p in payments] == expected[:index + 1]
                assert rows[("affair", name)]["arrears"] == (25 * min(index + 1, 2) if case == "defer" else 0)
                if index == 0 and account == "国库":
                    assert rows[("account", "国库")]["taels"] == pytest.approx(11690269.2869425 if case in {"factor", "defer"} else 11440269.2869425)
            assert rows[("affair", name)]["month_paid"]["amount"] == payments[-1]["paid"]
            assert rows[("affair", name)]["arrears"] == pytest.approx(sum(p["unpaid"] for p in payments))
            assert not [f for f in ledger["facts"] if f["kind"] == "received" and case != "shortage"]
            if case == "invalid_account" and index == 0:
                assert [json.loads(p.content)["field"] for m in received for p in m.parts if p.part_kind == "retry-prompt"] == ["facts[0].changes[0].value.account"]
            recipient = {"entity_type": "affair", "entity": name}
            original = list(reversed(GUOKU_ORDER)) if case == "shortage" else GUOKU_ORDER if account == "国库" else ["内廷俸_base", "妃嫔_base", "宫廷_base"]
            assert rows[("account", account)]["payment_order"] == ([recipient, *original] if case == "reorder" and index else [*original, recipient])
            assert account != "内库" or rows[("account", "国库")]["payment_order"] == GUOKU_ORDER
            declaration = {"facts": []}
            if index == 0 and case in {"stop", "reduce", "switch"}:
                account = "内库" if case == "switch" else account
                declaration["facts"].append({
                    "entity_type": "affair", "entity": name, "create": False,
                    "changes": [{"field": "monthly_funding", "value": {**funding, "account": account, "amount": 0 if case == "stop" else 200000 if case == "reduce" else funding["amount"]}}],
                    "text": "改拨",
                })
            if index == 0 and case == "reorder":
                declaration["facts"].append({
                    "entity_type": "account", "entity": account, "create": False,
                    "changes": [{"field": "payment_order", "value": [recipient, *original]}],
                    "text": "改序",
                })
            steps["Declaration"] = replaying([json.dumps(declaration, ensure_ascii=False)])
    assert reads is None or reads["repeated"] == []
