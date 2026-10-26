"""Medium: batched declared journeys through HTTP and read_records."""

import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import RECORDED, replaying


@pytest.mark.parametrize("case", ["journeys", "missing_day_month", "missing_day_night", "invalid_speed", "missing_distance"])
def test_declared_journey_dates_and_month_end_arrival(game_db, steps, audit, case):
    # All seven travellers start in the capital; dates are independent worked examples.
    cases = [
        ("黄立极", "山东", 20, 20, "常速", (1627, 11, 10)),
        ("张瑞图", "山东", 10, 10, "常速", (1627, 10, 30)),
        ("施凤来", "山东", 11, 11, "常速", (1627, 11, 1)),
        ("王绍徽", "山东", 0, 1, "押运", (1627, 10, 21)),
        ("郭允厚", "山东", 31, 30, "常速", (1627, 11, 20)),
        ("李国普", "山东", 5, 5, "加急", (1627, 10, 16)),
        ("杨嗣昌", "广东", 5, 5, "常速", (1628, 3, 30)),
    ]
    reply = {"facts": [{"entity_type": "person", "entity": name, "create": False,
        "changes": [{"field": "location", "value": destination},
                    {"field": "departure_day", "value": day},
                    {"field": "travel_speed", "value": pace}], "text": ""}
        for name, destination, day, _, pace, _ in cases]}
    if case.startswith("missing_day"):
        reply = json.loads((RECORDED / "month_travel.txt").read_text())
    elif case == "invalid_speed":
        reply["facts"] = reply["facts"][:1]
        reply["facts"][0]["changes"][2]["value"] = 2
    elif case == "missing_distance":
        reply["facts"] = reply["facts"][:1]
        reply["facts"][0]["changes"][0]["value"] = "新地区"
        reply["facts"].append({"entity_type": "region", "entity": "新地区", "create": True, "changes": [], "text": ""})
    if case != "missing_day_month":
        reply["decrees"] = []
    received = []
    steps["Declaration" if case == "missing_day_month" else "NightDeclaration"] = replaying([json.dumps(reply)] * 2, received)
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        if case == "missing_day_month":
            client.post("/actions", json={"action": "month"}).raise_for_status()
        else:
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        ledger = audit(game_db)
        if case != "journeys":
            assert json.loads(next(p.content for m in received for p in m.parts if p.part_kind == "retry-prompt"))["field"] == {
                "missing_day_month": "facts[0].departure_day", "missing_day_night": "facts[0].departure_day",
                "invalid_speed": "facts[0].changes[2].value", "missing_distance": "facts[0].location",
            }[case]
            assert not [f for f in ledger["facts"] if f["kind"] in {"departed", "arrived"}]
            assert len([f for f in ledger["facts"] if f["kind"] == "unhandled"]) == 1
            return
        data = {e["key"]: e["data"] for e in ledger["entities"] if e["kind"] == "person"}
        for name, destination, _, day, pace, expected in cases:
            assert data[name]["departure_date"] == {"year": 1627, "month": 10, "day": day}
            assert data[name]["arrival_date"] == dict(zip(("year", "month", "day"), expected))
            assert data[name]["travel_speed"] == pace
            assert data[name]["transit_to"] == destination
        received = []
        steps["simulation"] = replaying([
            ModelResponse(parts=[ToolCallPart("read_records", {"kind": "distance", "key": "北直隶 / 京师"}, tool_call_id="distance"),
                                 ToolCallPart("read_records", {"kind": "person", "key": "黄立极"}, tool_call_id="person")]),
            (RECORDED / "simulation.txt").read_text(),
        ], received)
        # A second location declaration while travelling cannot change this journey.
        steps["Declaration"] = replaying([json.dumps({"facts": [{"entity_type": "person", "entity": "黄立极", "create": False,
            "changes": [{"field": "location", "value": "广东"}], "text": ""}]})])
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        ledger = audit(game_db)
        result = {p.tool_call_id: p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart)}
        assert result["distance"]["entities"][0]["data"]["山东"] == {
            "distance": 900, "days": {"常速": 20, "加急": pytest.approx(10.5882352941), "押运": 20},
            "delivery_days": 3, "deadline_days": 20,
        }
        assert result["distance"]["entities"][0]["data"]["北直隶 / 京师"]["distance"] == 0
        assert result["person"]["entities"][0]["data"]["arrival_date"] == {"year": 1627, "month": 11, "day": 10}
        result = {e["key"]: e["data"] for e in ledger["entities"] if e["kind"] == "person"}
        assert result["黄立极"] == data["黄立极"]
        for name, destination, _, _, _, expected in cases:
            if expected[1] == 10:
                assert result[name]["location"] == destination
                assert result[name]["transit_to"] == ""
                assert result[name]["departure_date"] is None
                assert result[name]["arrival_date"] is None
                assert result[name]["travel_speed"] is None
            else:
                assert result[name] == data[name]
        assert [f["detail"]["date"] for f in ledger["facts"] if f["kind"] == "arrived"] == [
            {"year": 1627, "month": 10, "day": 30}, {"year": 1627, "month": 10, "day": 21},
            {"year": 1627, "month": 10, "day": 16},
        ]
