"""Medium: declarations through HTTP, observed through the audit CLI."""

import json
from pathlib import Path
from collections.abc import AsyncIterator, Callable, Sequence

import pytest
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel, DeltaToolCall
from starlette.testclient import TestClient

from ming.web import create_app

RECORDED = Path(__file__).parent / "recorded"


def replaying(
    replies: Sequence[str | ModelResponse | Exception]
    | Callable[[list[ModelMessage]], str | ModelResponse | Exception],
    received: list[ModelMessage] | None = None,
) -> FunctionModel:
    remaining = iter(replies) if not callable(replies) else iter(())

    async def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # Native async callback; model I/O alone is replaced.
        if received is not None:
            received.extend(_messages)
        result = replies(_messages) if callable(replies) else next(remaining)
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, ModelResponse) else ModelResponse(parts=[TextPart(result)])

    async def stream_response(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for index, part in enumerate((await reply(messages, info)).parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {index: DeltaToolCall(name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id=part.tool_call_id)}

    return FunctionModel(reply, stream_function=stream_response)


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_common_declaration_updates_entities_and_displaces_incumbent_atomically(game_db, steps, audit):
    case = json.loads((RECORDED / "appointments.json").read_text())
    replacement = json.loads((RECORDED / "appointments_replace_aliases.json").read_text())
    steps["NightDeclaration"] = replaying([case["reply"], replacement["reply"], replacement["reply"]])
    before = {e["key"]: e for e in audit(game_db)["entities"] if e["kind"] == "person"}
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["night"]["result"] == "translated"
        ledger = audit(game_db)
        held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"}
        assert held[("户部右侍郎", "")] == ["杨嗣昌"]
        assert held[("户部尚书", "")] == ["徐光启"]
        assert held[("內承運庫掌印太监", "")] == ["徐光启"]
        assert held[("内阁大学士", "")] == ["韩爌", "毕自严"]
        shown = next(e for e in client.get("/records").json()["entities"] if e["kind"] == "person" and e["key"] == "徐光启")
        assert {(a["office"], a["territory"]) for a in shown["data"]["appointments"]} == {("户部尚书", ""), ("內承運庫掌印太监", "")}
        assert held[("知县", "保定府新城县")] == ["李待问"]
        assert held[("知县", "济南府新城县")] == ["练国事"]
        people = {e["key"]: e for e in ledger["entities"] if e["kind"] == "person"}
        assert {k: e["data"] for k, e in people.items()} == {k: e["data"] for k, e in before.items()}
        assert not any({"office", "office_type", "office_region"} & e["data"].keys() for e in people.values())
        assert any(f["entity_id"] == people["郭允厚"]["id"] and f["kind"] == "displaced" for f in ledger["facts"])
        dossier = json.loads((RECORDED / "appointment_dossiers.json").read_text())
        received = []
        steps["scene"] = replaying(ModelMessagesTypeAdapter.validate_python(dossier["messages"]), received)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": dossier["words"]}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        returned = {p.model_response_object()["person"]["name"]: p.model_response_object()
                    for m in received for p in m.parts
                    if isinstance(p, ToolReturnPart) and p.tool_name == "read_person"}
        for name in ("徐光启", "王体乾", "郭允厚"):
            assert {a["key"]: a["data"]["taels"] for a in returned[name]["accounts"]} == {"国库": 3200000, "内库": 4400000}
        assert {a["key"] for a in returned["韩爌"]["accounts"]} == {"国库"}
        assert "taels" not in returned["韩爌"]["accounts"][0]["data"]
        assert {(a["office"], a["territory"]) for a in returned["徐光启"]["appointments"]} == {("户部尚书", ""), ("內承運庫掌印太监", "")}
        assert returned["郭允厚"]["appointments"] == []
        urgent = []
        steps["urgent"] = replaying([(RECORDED / "sources_empty.txt").read_text()], urgent)
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["night"]["result"] == "translated"
        after = audit(game_db)
        held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in after["entities"] if e["kind"] == "incumbency"}
        assert held[("户部尚书", "")] == ["毕自严"]
        assert held[("內承運庫掌印太监", "")] == ["徐光启"]
        assert held[("户部右侍郎", "")] == []
        assert held[("知县", "保定府新城县")] == ["王绍徽"]
        assert held[("知县", "济南府新城县")] == ["练国事"]
        assert held[("巡抚", "陕西")] == held[("巡抚", "山西")] == ["洪承畴"]
        assert {e["key"]: e["data"] for e in after["entities"] if e["kind"] == "person"} == {k: e["data"] for k, e in before.items()}
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        assert audit(game_db) == after
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        assert urgent
        assert {p["name"] for p in json.loads(urgent[0].parts[0].content)["context"]["drafters"]} == {"韩爌", "毕自严", "李国普", "王体乾"}


@pytest.mark.parametrize("case", ["range", "purpose_region"])
def test_recorded_r2_reply_lands(game_db, steps, audit, case):
    reply = (json.loads((RECORDED / "range_v9.json").read_text())["reply"] if case == "range" else
             json.dumps(json.loads((RECORDED / "declarations_v9.json").read_text())["cases"][case], ensure_ascii=False))
    steps["Declaration"] = replaying([reply, reply])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 11
        ledger = audit(game_db)
        assert not [f for f in ledger["facts"] if f["kind"] == "unhandled"]
        rows = {(e["kind"], e["key"]): e for e in ledger["entities"]}
        if case == "range":
            assert rows[("army", "京营")]["data"]["firearm_equipment"] == 100
            assert rows[("army", "京营")]["data"]["cannon_equipment"] == 0
            assert rows[("person", "洪承畴")]["data"]["travel_speed"] == 2
            assert rows[("fiscal", "宗室禄米_base")]["data"]["payment_policy"] == {"factor": 1, "defer": 0}
            actual = {f["entity_id"]: f["detail"] for f in ledger["facts"] if f["kind"] == "changed"}
            assert actual[rows[("fiscal", "宗室禄米_base")]["id"]]["nominal"]["payment_policy"] == {"factor": 1.5, "defer": -0.5}
        else:
            assert [(f["detail"]["actual"], f["detail"]["purpose"]) for f in ledger["facts"]
                    if f["entity_id"] == rows[("region", "陕西")]["id"] and f["kind"] == "received"] == [(10000, "专项")]
            assert "arrears" not in rows[("region", "陕西")]["data"]
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        assert audit(game_db) == ledger
