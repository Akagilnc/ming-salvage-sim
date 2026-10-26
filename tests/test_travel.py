"""Medium: declared journeys through HTTP and the model's read_records tool."""

import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import RECORDED, replaying


@pytest.mark.parametrize("stage,case", [
    ("month", ("毕自严", "北直隶 / 京师", 5, "常速", (1627, 10, 25), None)),
    ("month", ("毕自严", "北直隶 / 京师", 20, "常速", (1627, 11, 10), None)),
    ("month", ("毕自严", "北直隶 / 京师", 10, "常速", (1627, 10, 30), None)),
    ("month", ("毕自严", "北直隶 / 京师", 11, "常速", (1627, 11, 1), None)),
    ("month", ("毕自严", "北直隶 / 京师", 0, "押运", (1627, 10, 21), None)),
    ("month", ("毕自严", "北直隶 / 京师", 31, "常速", (1627, 11, 20), None)),
    ("month", ("毕自严", "北直隶 / 京师", 5, "加急", (1627, 10, 16), None)),
    ("month", ("黄立极", "广东", 5, "常速", (1628, 3, 30), None)),
    ("month", ("毕自严", "北直隶 / 京师", None, "常速", None, "facts[0].departure_day")),
    ("month", ("毕自严", "北直隶 / 京师", 5, 2, None, "facts[0].changes[2].value")),
    ("month", ("毕自严", "新地区", 5, "常速", None, "facts[0].location")),
    ("night", ("毕自严", "北直隶 / 京师", 5, "常速", (1627, 10, 25), None)),
    ("night", ("毕自严", "北直隶 / 京师", 20, "常速", (1627, 11, 10), None)),
    ("night", ("毕自严", "北直隶 / 京师", None, "常速", None, "facts[0].departure_day")),
])
def test_declared_journey_dates_and_month_end_arrival(game_db, steps, audit, case, stage):
    received = []
    reply = {"facts": [{"entity_type": "person", "entity": case[0], "create": False,
        "changes": [{"field": "location", "value": case[1]},
                    {"field": "departure_day", "value": case[2]},
                    {"field": "travel_speed", "value": case[3]}], "text": ""}]}
    if case[1] == "新地区":
        reply["facts"].append({"entity_type": "region", "entity": "新地区", "create": True, "changes": [], "text": ""})
    if case[2] is None:
        reply = json.loads((RECORDED / "month_travel.txt").read_text())
    if stage == "night":
        reply["decrees"] = []
    steps["NightDeclaration" if stage == "night" else "Declaration"] = replaying([json.dumps(reply)] * 2, received)
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        if stage == "night":
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        else:
            client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        ledger = audit(game_db)
        if case[5]:
            assert json.loads(next(p.content for m in received for p in m.parts if p.part_kind == "retry-prompt"))["field"] == case[5]
            assert not [f for f in ledger["facts"] if f["kind"] in {"departed", "arrived"}]
            assert len([f for f in ledger["facts"] if f["kind"] == "unhandled"]) == 1
            return
        data = next(e["data"] for e in ledger["entities"] if e["kind"] == "person" and e["key"] == case[0])
        assert data["departure_date"] == {"year": 1627, "month": 10, "day": min(30, max(1, case[2]))}
        assert data["arrival_date"] == dict(zip(("year", "month", "day"), case[4]))
        assert data["travel_speed"] == case[3]
        arrived = stage == "month" and case[4][1] == 10
        assert data.get("waiting_audience", False) == arrived
        assert data["transit_to"] == ("" if arrived else case[1])
        assert len([f for f in ledger["facts"] if f["kind"] == "arrived"]) == int(arrived)
        if stage == "night" and case[2] == 20:
            received = []
            steps["simulation"] = replaying([
                ModelResponse(parts=[ToolCallPart("read_records", {"kind": "distance", "key": "山东"}, tool_call_id="distance"),
                                     ToolCallPart("read_records", {"kind": "person", "key": "毕自严"}, tool_call_id="person")]),
                (RECORDED / "simulation.txt").read_text(),
            ], received)
            # A second location declaration while travelling cannot change this journey.
            steps["Declaration"] = replaying([json.dumps({"facts": [{"entity_type": "person", "entity": "毕自严", "create": False,
                "changes": [{"field": "location", "value": "广东"}], "text": ""}]})])
            client.post("/actions", json={"action": "month"}).raise_for_status()
            assert client.get("/state").json()["game"]["failure"] is None
            result = {p.tool_call_id: p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart)}
            assert result["distance"]["entities"][0]["data"]["北直隶 / 京师"] == {
                "distance": 900, "days": {"常速": 20, "加急": pytest.approx(10.5882352941), "押运": 20},
                "delivery_days": 3, "deadline_days": 20,
            }
            assert result["distance"]["entities"][0]["data"]["山东"]["distance"] == 0
            assert result["person"]["entities"][0]["data"]["arrival_date"] == {"year": 1627, "month": 11, "day": 10}
            assert next(e["data"] for e in audit(game_db)["entities"] if e["key"] == "毕自严" and e["kind"] == "person") == data
