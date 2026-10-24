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
    received = []
    steps["NightDeclaration"] = replaying([*ModelMessagesTypeAdapter.validate_python(case["responses"]), replacement["reply"], replacement["reply"]], received)
    before = {e["key"]: e for e in audit(game_db)["entities"] if e["kind"] == "person"}
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["night"]["result"] == "translated"
        directory = next(p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == "read_catalogues")
        assert directory["office"]["户部尚书"]["multiple"] is False
        assert directory["office"]["内阁大学士"]["multiple"] is True
        assert "西安" in directory["territory"]["陕西西安府"]["aliases"]
        ledger = audit(game_db)
        held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"}
        assert held[("户部右侍郎", "")] == ["杨嗣昌"]
        assert held[("户部尚书", "")] == ["徐光启"]
        assert held[("內承運庫掌印太监", "")] == ["徐光启"]
        assert set(held[("内阁大学士", "")]) == {"黄立极", "施凤来", "张瑞图", "韩爌", "毕自严"}
        assert held[("中极殿大学士", "")] == ["李国普"]
        assert held[("知府", "陕西西安府")] == ["李待问"]
        assert held[("巡抚", "山西大同镇")] == ["王绍徽"]
        xian = next(e for e in ledger["entities"] if e["kind"] == "incumbency" and e["data"]["office"] == "知府" and e["data"]["territory"] == "陕西西安府")
        assert [f["detail"]["actual"]["holders"] for f in ledger["facts"] if f["entity_id"] == xian["id"] and f["kind"] == "changed"] == [["杨嗣昌"], ["李待问"]]
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
            assert {a["key"]: a["data"]["taels"] for a in returned[name]["accounts"] if "taels" in a["data"]} == {"国库": 3200000, "内库": 4400000, **({"常盈库": 1200000} if name != "徐光启" else {})}
            assert {a["key"] for a in returned[name]["accounts"]} == {"国库", "内库", "节慎库", "常盈库"}
        assert {a["key"]: a["data"] for a in returned["韩爌"]["accounts"]} == {name: {"name": name} for name in ("国库", "内库", "节慎库", "常盈库")}
        assert {(a["office"], a["territory"]) for a in returned["徐光启"]["appointments"]} == {("户部尚书", ""), ("內承運庫掌印太监", "")}
        assert returned["郭允厚"]["appointments"] == []
        assert [(e["office"], e["territory"], e["holders"]) for e in returned["郭允厚"]["events"] if e["kind"] == "displaced"] == [("户部尚书", "", ["徐光启"])]
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
        assert {p["name"] for p in json.loads(urgent[0].parts[0].content)["context"]["drafters"]} == {"黄立极", "王体乾"}
        case = (
            json.loads((RECORDED / "cabinet_wei.json").read_text())["cases"]
            | json.loads((RECORDED / "border_appointments.json").read_text())["cases"]
        )
        for name, expected in (("chief_swap", ["施凤来"]), ("chief_exit", []), ("chief_join", ["崔呈秀"]), ("chief_invalid", ["崔呈秀"]), ("chief_vacancy", []), ("wei", []), ("wei_replace", [])):
            received = []
            steps["Declaration"] = replaying([json.dumps(case[name], ensure_ascii=False)] * 2, received)
            urgent = []
            steps["urgent"] = replaying([(RECORDED / "sources_empty.txt").read_text()], urgent)
            client.post("/actions", json={"action": "month"}).raise_for_status()
            assert client.get("/state").json()["game"]["failure"] is None
            ledger = audit(game_db)
            held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"}
            assert held[("内阁首辅", "")] == expected
            assert (not urgent) == (name in {"chief_vacancy", "wei", "wei_replace"})
            if urgent:
                assert {p["name"] for p in json.loads(urgent[0].parts[0].content)["context"]["drafters"]} == {*expected, "王体乾"}
            if name == "chief_swap":
                assert "黄立极" in held[("内阁大学士", "")]
                assert any(f["kind"] == "displaced" and f["detail"]["office"] == "内阁首辅" and f["entity_id"] == people["黄立极"]["id"] for f in ledger["facts"])
            elif name == "chief_exit":
                assert "施凤来" not in held[("内阁大学士", "")]
                assert {f["detail"]["office"] for f in ledger["facts"] if f["kind"] == "displaced" and f["entity_id"] == people["施凤来"]["id"]} >= {"内阁大学士", "内阁首辅"}
            elif name == "chief_join":
                assert "崔呈秀" in held[("内阁大学士", "")]
                assert held[("兵部尚书", "")] == ["崔呈秀"]
            elif name == "chief_invalid":
                assert json.loads(next(p.content for m in received for p in m.parts if p.part_kind == "retry-prompt"))["field"] == "facts[0].changes[0].value[0]"
                assert len([f for f in ledger["facts"] if f["kind"] == "unhandled"]) == 1
            assert len([f for f in ledger["facts"] if f["kind"] == "unhandled"]) == int(name in {"chief_invalid", "chief_vacancy", "wei", "wei_replace"})
        assert held[("正千户", "北直隶兴和千户所")] == ["杨嗣昌"]
        assert held[("卫指挥使", "辽东宁远卫")] == ["练国事"]
        assert held[("卫指挥使", "北直隶延庆卫")] == ["郭允厚"]
        assert held[("卫指挥使", "山西天成卫")] == ["李待问"]
        assert held[("总兵官", "辽东锦州")] == ["孙传庭"]
        assert held[("总兵官", "辽东广宁中屯卫")] == ["练国事"]
        assert held[("卫指挥使", "北直隶山海卫")] == ["郭允厚"]
        assert held[("卫指挥使", "山海关")] == ["孙传庭"]
        assert held[("卫指挥使", "山西高山卫")] == ["卢象升"]
        assert held[("正千户", "山西高山守御千户所")] == ["毕自严"]
        assert held[("卫指挥使", "山西镇虏卫")] == ["洪承畴"]
        assert {(f["entity_id"], f["detail"]["office"], f["detail"]["territory"]) for f in ledger["facts"] if f["kind"] == "displaced"} >= {
            (people["李待问"]["id"], "卫指挥使", "北直隶延庆卫"),
            (people["卢象升"]["id"], "卫指挥使", "山西天成卫"),
        }
        assert {e["key"]: e["data"] for e in ledger["entities"] if e["kind"] == "person"} == {k: e["data"] for k, e in before.items()}
        dossier = json.loads((RECORDED / "account_dossiers.json").read_text())
        received = []
        steps["scene"] = replaying(ModelMessagesTypeAdapter.validate_python(dossier["messages"]), received)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": dossier["words"]}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        returned = {p.model_response_object()["person"]["name"]: p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == "read_person"}
        for name, known in (("李从心", {"国库", "内库", "节慎库", "常盈库"}), ("魏忠贤", {"国库", "内库", "常盈库"}), ("韩爌", set())):
            assert {a["key"] for a in returned[name]["accounts"]} == {"国库", "内库", "节慎库", "常盈库"}
            for account in returned[name]["accounts"]:
                if account["key"] in known:
                    assert account["data"]["taels"] == next(e["data"]["taels"] for e in ledger["entities"] if e["kind"] == "account" and e["key"] == account["key"])
                else:
                    assert account["data"] == {"name": account["key"]}
        for name, amount in (("节慎库", 3), ("常盈库", 5)):
            assert all(f["detail"]["amount"] == amount for f in ledger["facts"] if f["kind"] == "monthly_income" and f["detail"]["account"] == name)
            assert next(e["data"]["taels"] for e in ledger["entities"] if e["kind"] == "account" and e["key"] == name) == {"节慎库": 600000, "常盈库": 1200000}[name] + amount * 10000 * 8


@pytest.mark.parametrize("case", ["range", "purpose_region"])
def test_recorded_r2_reply_lands(game_db, steps, audit, case):
    reply = (json.loads((RECORDED / "range_v9.json").read_text())["reply"] if case == "range" else
             json.dumps(json.loads((RECORDED / "declarations_v9.json").read_text())["cases"][case], ensure_ascii=False))
    received = []
    steps["Declaration"] = replaying([reply, reply], received)
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 11
        material = json.loads(received[0].parts[0].content.split("\n", 1)[1])
        assert not {"office", "territory"}.intersection(e["kind"] for e in material["entities"])
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
