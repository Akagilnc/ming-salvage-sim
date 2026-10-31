"""Medium: declarations through HTTP, observed through the audit CLI."""

import json
from pathlib import Path
from collections.abc import AsyncIterator, Callable, Sequence

import pytest
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel, DeltaToolCall
from starlette.testclient import TestClient

from ming.web import create_app
from ming.middle.view import Officials

RECORDED = Path(__file__).parent / "recorded"


def replaying(
    replies: Sequence[str | ModelResponse | Exception]
    | Callable[[list[ModelMessage]], str | ModelResponse | Exception],
    received: list[ModelMessage] | None = None,
    toolsets: list[list[str]] | None = None,
) -> FunctionModel:
    remaining = iter(replies) if not callable(replies) else iter(())

    async def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # Native async callback; model I/O alone is replaced.
        if received is not None:
            received.extend(_messages)
        if toolsets is not None:
            toolsets.append([tool.name for tool in _info.function_tools])
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
@pytest.mark.parametrize("acting", [None, "holders", "acting"], ids=["holders", "acting-cabinet", "acting-chief"])
def test_common_declaration_updates_entities_and_displaces_incumbent_atomically(game_db, steps, audit, acting):
    case = json.loads((RECORDED / "appointments.json").read_text())
    replacement = json.loads((RECORDED / "appointments_replace_aliases.json").read_text())
    if acting:
        case["parsed"] = json.loads(case["reply"])
        case["parsed"]["facts"].extend([
            {"entity_type": "incumbency", "entity": office, "create": False, "text": "", "changes": changes}
            for office, changes in (
                ("内阁大学士", [{"field": "holders", "value": []}, {"field": "acting", "value": ["黄立极"]}]),
                ("司礼监掌印太监", [{"field": "holders", "value": []}, {"field": "acting", "value": ["王体乾"]}]),
                ("内阁首辅", [{"field": "holders", "value": ["黄立极"] if acting == "holders" else []},
                            *([{"field": "acting", "value": ["黄立极"]}] if acting == "acting" else [])]),
                ("户部尚书", [{"field": "acting", "value": ["毕自严"]}]),
            )
        ])
        case["reply"] = json.dumps(case["parsed"])
    received = []
    steps["NightDeclaration"] = replaying([case["reply"], replacement["reply"], replacement["reply"]], received)
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
        assert set(held[("内阁大学士", "")]) == (set() if acting else {"黄立极", "施凤来", "张瑞图", "韩爌", "毕自严"})
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
        returned = {p.model_response_object()["entities"][0]["key"]: p.model_response_object()
                    for m in received for p in m.parts
                    if isinstance(p, ToolReturnPart) and p.tool_name == "read_records"}
        assert {(a["office"], a["territory"]) for a in returned["徐光启"]["entities"][0]["data"]["appointments"]} == {("户部尚书", ""), ("內承運庫掌印太监", "")}
        assert returned["郭允厚"]["entities"][0]["data"]["appointments"] == []
        assert [(e["detail"]["office"], e["detail"]["territory"], e["detail"]["holders"]) for e in returned["郭允厚"]["facts"] if e["kind"] == "displaced"] == [("户部尚书", "", ["徐光启"])]
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
        returned = client.portal.call(
            client.app.state.web.game.court.read.read_records, Officials(people=["毕自严"]), None, ["国库", "郭允厚"],
        )
        assert next(e["data"]["taels"] for e in returned["entities"] if e["key"] == "国库") == 3200000
        assert not {"dossier", "seed_guilt", "loyalty"}.intersection(
            next(e["data"] for e in returned["entities"] if e["key"] == "郭允厚")
        )
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        assert urgent
        assert {p["key"] for p in json.loads(urgent[0].parts[0].content)["speakers"]} == {"黄立极", "王体乾"}
        if acting:
            assert held[("内阁首辅", "")] == (["黄立极"] if acting == "holders" else [])
            received = []
            steps["scene"] = replaying([ModelResponse(parts=[
                ToolCallPart("read_records", {"kind": "office", "key": office}, tool_call_id=office)
                for office in ("内阁大学士", "内阁首辅", "司礼监掌印太监", "户部尚书")
            ]), "done"], received)
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post("/actions", json={"action": "say", "words": "查任职"}).raise_for_status()
            returned = {p.tool_call_id: p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart)}
            assert returned["内阁大学士"]["appointments"][0]["acting"] == ["黄立极"]
            assert returned["内阁首辅"]["appointments"][0][acting] == ["黄立极"]
            assert returned["司礼监掌印太监"]["status"] == "acting"
            assert returned["户部尚书"]["status"] == "occupied"
            assert returned["户部尚书"]["appointments"][0]["acting"] == ["毕自严"]
            return
        # Income is a one-month contract, independent of the appointment matrix.
        ledger = audit(game_db)
        for name, amount in (("节慎库", 3), ("常盈库", 5)):
            assert [f["detail"]["amount"] for f in ledger["facts"] if f["kind"] == "monthly_income" and f["detail"]["account"] == name] == [amount]
            assert next(e["data"]["taels"] for e in ledger["entities"] if e["kind"] == "account" and e["key"] == name) == {"节慎库": 600000, "常盈库": 1200000}[name] + amount * 10000
        case = json.loads((RECORDED / "cabinet_wei.json").read_text())["cases"]
        # Month boundaries exercise new chief, seal-holder alone, failed landing,
        # and neither holder. Joining the cabinet is a local prerequisite only.
        for name, expected, month in (("chief_swap", ["施凤来"], 12), ("chief_exit", [], 1), ("chief_join", ["崔呈秀"], 1), ("chief_invalid", ["崔呈秀"], 2), ("chief_vacancy", [], 3)):
            received = []
            urgent = []
            steps["urgent"] = replaying([(RECORDED / "sources_empty.txt").read_text()], urgent)
            if name == "chief_join":
                steps["NightDeclaration"] = replaying([json.dumps({"decrees": [], **case[name]}, ensure_ascii=False)], received)
                client.post("/actions", json={"action": "open"}).raise_for_status()
                client.post("/actions", json={"action": "dismiss"}).raise_for_status()
                client.portal.call(client.app.state.web.game.drain)
                assert client.get("/state").json()["game"]["night"]["result"] == "translated"
            else:
                steps["Declaration"] = replaying([json.dumps(case[name], ensure_ascii=False)] * 2, received)
                client.post("/actions", json={"action": "month"}).raise_for_status()
                assert (not urgent) == (name == "chief_vacancy")
            state = client.get("/state").json()["game"]
            assert (state["failure"], state["date"]["month"]) == (None, month)
            ledger = audit(game_db)
            held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"}
            assert held[("内阁首辅", "")] == expected
            if urgent:
                assert {p["key"] for p in json.loads(urgent[0].parts[0].content)["speakers"]} == {*expected, "王体乾"}
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
            assert len([f for f in ledger["facts"] if f["kind"] == "unhandled"]) == int(name in {"chief_invalid", "chief_vacancy"})
        # Border appointments and replacement have ordering, but no month clock.
        case = json.loads((RECORDED / "border_appointments.json").read_text())["cases"]
        for name in ("wei", "wei_replace"):
            steps["NightDeclaration"] = replaying([json.dumps({"decrees": [], **case[name]}, ensure_ascii=False)])
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            state = client.get("/state").json()["game"]
            assert (state["failure"], state["night"]["result"], state["date"]["month"]) == (None, "translated", 3)
        ledger = audit(game_db)
        held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"}
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


@pytest.mark.parametrize("case,game_db", [
    (case, "county_night" if case == "provincial_county" else "opening_db")
    for case in ["range", "purpose_region", "provincial_county", "bad_territory_retry", "acting", "acting_coexist", "acting_withdraw", "acting_invalid", "unqualified", "capital_territory", "scale_recorded", "scale_bounds", "scale_invalid", "salary_invalid", "maintenance_invalid", "fiscal_recorded"]
], indirect=["game_db"])
def test_recorded_r2_reply_lands(game_db, steps, audit, case):
    reply = (json.dumps({"facts": [f for f in json.loads(json.loads((RECORDED / "range_v9.json").read_text())["reply"])["facts"]
                                  if f["entity_type"] != "person"]}) if case != "purpose_region" else
             json.dumps(json.loads((RECORDED / "declarations_v9.json").read_text())["cases"]["purpose_region"], ensure_ascii=False))
    received = []
    numeric_cases = {
        "scale_recorded": (("region", "陕西", "public_support", -2, 30),),
        "fiscal_recorded": (
            ("fiscal", "工程_base", "value", 8, 8),
            ("fiscal", "工程_rate", "value", 3.5, 3.5),
            ("account", "国库", "taels", 123456, pytest.approx(12110925.2869425)),
        ),
        "scale_bounds": (
            ("region", "河南", "public_support", 80, 100),
            ("region", "山东", "public_support", -80, 0),
            ("power", "蒙古", "satisfaction", -5, 35),
            ("power", "大明", "satisfaction", 80, 100),
            ("power", "后金", "satisfaction", -50, 0),
        ),
        "scale_invalid": (("region", "河南", "public_support", "bad", 40),),
        "salary_invalid": (("army", "京营", "salary_rate", "bad", 1.0),),
        "maintenance_invalid": (("building", "京营火器局", "maintenance", "bad", 1),),
    }
    if case in numeric_cases.keys() - {"scale_recorded", "fiscal_recorded"}:
        reply = json.dumps({"facts": [
            {"entity_type": kind, "entity": name, "create": False, "text": "",
             "changes": [{"field": field, "value": value}]}
            for kind, name, field, value, _ in numeric_cases[case]
        ]})
    recording = {
        "provincial_county": "month_provincial_county.txt",
        "scale_recorded": "month_scale_1982.json",
        "fiscal_recorded": "month_fiscal_values_1982.txt",
    }.get(case)
    reply = (RECORDED / recording).read_text() if recording else reply
    reply = json.dumps({"facts": json.loads(reply)["facts"]}) if case == "provincial_county" else reply
    if case.startswith("acting") or case in {"unqualified", "capital_territory"}:
        reply = {"facts": [{"entity_type": "incumbency", "entity": "陕西巡抚" if case.startswith("acting") else {"unqualified": "巡抚", "capital_territory": "陕西户部尚书"}[case], "create": False,
                            "changes": [*([{"field": "holders", "value": ["洪承畴"]}] if case == "acting_coexist" else []),
                                        {"field": "acting" if case.startswith("acting") else "holders", "value": ["毕自严"]}], "text": ""}]}
        reply["facts"] += ([{**reply["facts"][0], "changes": [{"field": "acting", "value": []}]}]
                           if case == "acting_withdraw" else [])
        reply = json.dumps(reply, ensure_ascii=False)
    # Keep month-specific sources, full world translation and fiscal settlement.
    # The remaining field/appointment matrix needs only the real night landing.
    monthly = case in {"provincial_county", "bad_territory_retry", "scale_recorded", "fiscal_recorded"}
    reply = reply if monthly else json.dumps({"decrees": [], **json.loads(reply)}, ensure_ascii=False)
    steps["Declaration" if monthly else "NightDeclaration"] = replaying(
        ModelMessagesTypeAdapter.validate_python(json.loads((RECORDED / "declarations_1972.json").read_text())["cases"][case])
        if case == "bad_territory_retry" else
        [reply.replace('["毕自严"]', '["毕自严", "徐光启"]'), reply] if case == "acting_invalid" else [reply, reply], received,
    )
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        for action in (("month",) if monthly else ("open", "dismiss")):
            client.post("/actions", json={"action": action}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == (11 if monthly else 10)
        assert "entities" not in json.loads(received[0].parts[0].content.split("\n", 1)[1])
        ledger = audit(game_db)
        assert bool([f for f in ledger["facts"] if f["kind"] == "unhandled"]) == (case in {"unqualified", "capital_territory", "scale_invalid", "salary_invalid", "maintenance_invalid"})
        rows = {(e["kind"], e["key"]): e for e in ledger["entities"]}
        for kind, name, field, _, expected in numeric_cases.get(case, ()):
            assert rows[(kind, name)]["data"][field] == expected
        if case == "fiscal_recorded":
            assert [f["detail"]["actual"]["value"] for f in ledger["facts"]
                    if f["entity_id"] == rows[("fiscal", "工程_rate")]["id"] and f["kind"] == "changed"] == [3, 3.5]
            payment = next(f["detail"] for f in ledger["facts"]
                           if f["kind"] == "monthly_payment" and f["detail"]["recipient"] == "工程_base")
            assert payment["due"] == pytest.approx(8 * 3.5 / 100)
            assert payment["paid"] == payment["due"]
            donations = [f["detail"] for f in ledger["facts"]
                         if f["kind"] == "changed" and "taels" in f["detail"]["actual"]]
            assert [(f["nominal"]["taels"], f["actual"]["taels"], f.get("counterpart"))
                    for f in donations] == [(123456, 123456, None)]
            assert not [f for f in ledger["facts"] if f["kind"] == "received"]
        elif case in numeric_cases and case.endswith("invalid"):
            assert json.loads(next(p.content for m in received for p in m.parts if p.part_kind == "retry-prompt"))["field"] == "facts[0].changes[0].value"
            assert not [f for f in ledger["facts"] if f["kind"] == "changed"]
        elif case.startswith("acting"):
            appointment = next(e["data"] for e in ledger["entities"] if e["kind"] == "incumbency" and e["data"]["office"] == "巡抚" and e["data"]["territory"] == "陕西")
            assert appointment["holders"] == (["洪承畴"] if case == "acting_coexist" else [])
            assert appointment["acting"] == ([] if case == "acting_withdraw" else ["毕自严"])
            assert [json.loads(p.content)["expected"] for m in received for p in m.parts
                    if p.part_kind == "retry-prompt"] == ([{"maxItems": 1}] if case == "acting_invalid" else [])
            assert [f["detail"]["role"] for f in ledger["facts"]
                    if f["kind"] == "displaced"] == (["acting"] if case == "acting_withdraw" else [])
            shown = next(e["data"] for e in client.get("/records").json()["entities"] if e["kind"] == "person" and e["key"] == "毕自严")
            assert any(a["role"] == "acting" and a["territory"] == "陕西" for a in shown["appointments"]) == (case != "acting_withdraw")
            assert ("identity_description" in shown) == (case == "acting_withdraw")
            steps["scene"] = replaying([ModelResponse(parts=[ToolCallPart("read_records", {"kind": "office", "key": "陕西巡抚"}, tool_call_id="acting")]), "done"], received)
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post("/actions", json={"action": "say", "words": "目前陕西巡抚可有？最高长官是谁？"}).raise_for_status()
            result = next(p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_call_id == "acting")
            assert result["status"] == {"acting_coexist": "occupied", "acting_withdraw": "vacant"}.get(case, "acting")
            assert result["appointments"][0]["acting"] == appointment["acting"]
            assert result["appointments"][0]["holders"] == appointment["holders"]
            ledger = audit(game_db)
        elif case in {"unqualified", "capital_territory"}:
            failure = json.loads(next(p.content for m in received for p in m.parts if p.part_kind == "retry-prompt"))
            assert failure["expected"] == {
                "unqualified": {"status": "territory_required", "territories": ["北直隶保定六府"], "pairs": []},
                "capital_territory": {"status": "office_not_found", "territories": [], "pairs": []},
            }[case]
            assert not any(e["kind"] == "incumbency" and (e["data"]["office"], e["data"]["territory"]) in {("巡抚", ""), ("户部尚书", "陕西")} for e in ledger["entities"])
        elif case == "range":
            assert rows[("army", "京营")]["data"]["firearm_equipment"] == 100
            assert rows[("army", "京营")]["data"]["cannon_equipment"] == 0
            assert rows[("fiscal", "宗室禄米_base")]["data"]["payment_policy"] == {"factor": 1, "defer": 0}
            actual = {f["entity_id"]: f["detail"] for f in ledger["facts"] if f["kind"] == "changed"}
            assert actual[rows[("fiscal", "宗室禄米_base")]["id"]]["nominal"]["payment_policy"] == {"factor": 1.5, "defer": -0.5}
        elif case == "provincial_county":
            assert {f["detail"]["origin_ref"] for f in ledger["facts"] if f["kind"] == "changed"} == {
                e["id"] for e in ledger["entities"] if e["kind"] == "decree"
            }
            assert next(e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"
                        and e["data"]["office"] == "知县" and e["data"]["territory"] == "保定府新城县") == ["徐应秋"]
            assert not [p for m in received for p in m.parts if p.part_kind == "retry-prompt"]
        elif case == "bad_territory_retry":
            assert [f["entity_id"] for f in ledger["facts"] if f["kind"] == "changed"] == [rows["territory", "保定府新城县"]["id"]]
            assert set(json.loads(next(p.content for m in received for p in m.parts if p.part_kind == "retry-prompt"))["expected"]["territory"]) == {
                "保定府新城县", "济南府新城县", "建昌府新城县", "杭州府新城县",
            }
        elif case == "purpose_region":
            assert [(f["detail"]["actual"], f["detail"]["purpose"]) for f in ledger["facts"]
                    if f["entity_id"] == rows[("region", "陕西")]["id"] and f["kind"] == "received"] == [(10000, "专项")]
            assert "arrears" not in rows[("region", "陕西")]["data"]
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        assert audit(game_db) == ledger


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
@pytest.mark.parametrize("stage", ["night", "month", "simulation"])
def test_translation_queries_preserve_two_table_permissions(game_db, steps, stage):
    recording = json.loads((RECORDED / "declarations_1972.json").read_text())["cases"]
    received = []
    offices = ["陕西巡抚", "巡抚", "新城知县", "西安知府", "内阁大学士", "陕西巡府", "不存在的官职", "内阁大学士"]
    steps["NightDeclaration"] = replaying([(RECORDED / "night_empty.txt").read_text()])
    steps[{"night": "NightDeclaration", "month": "Declaration", "simulation": "simulation"}[stage]] = replaying(
        [ModelResponse(parts=[ToolCallPart("read_records", {"kind": "incumbency", "key": offices}, tool_call_id="batch"),
                              ToolCallPart("read_records", {"kind": "person", "key": ["郭允厚", "郭允厚"], "date": {"year": 1600, "month": 1}}, tool_call_id="people"),
                              ToolCallPart("read_records", {}, tool_call_id="empty"),
                              *(ToolCallPart("read_records", {"key": key}, tool_call_id=f"names-{i}")
                                for i, key in enumerate(["郭允厚", "郭尚书", "毕自严", "南户部", ["郭允厚", "毕自严"], ["郭尚书", "毕尚书"]])),
                              *(ToolCallPart("read_records", {"kind": "incumbency", "key": name}, tool_call_id=name)
                                for name in dict.fromkeys(offices))]),
         *([(RECORDED / "simulation.txt").read_text()] if stage == "simulation" else
           ModelMessagesTypeAdapter.validate_python(recording["night_catalogue_queries" if stage == "night" else "catalogue_queries"]))], received,
    )
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        if stage != "night":
            client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
    queries = {p.tool_call_id: p.args_as_dict() for m in received for p in m.parts if isinstance(p, ToolCallPart)}
    results = {p.tool_call_id: p.model_response_object() for m in received for p in m.parts if isinstance(p, ToolReturnPart)}
    batches = [[(
        {field: result.get(field) for field in ("status", "appointments", "territories", "pairs", "names_and_aliases")},
        [e["id"] for e in result.get("entities", [])],
        [(f["entity_id"], f["kind"]) for f in result.get("facts", [])],
    ) for result in batch] for batch in (results.pop("batch")["offices"], [results[name] for name in offices])]
    assert batches[0] == batches[1]
    queries.pop("batch")
    assert results.pop("empty")["status"] == "query_required"
    queries.pop("empty")
    people = results.pop("people")
    queries.pop("people")
    assert [(e["kind"], e["key"]) for e in people["entities"]] == [("person", "郭允厚")]
    assert people["facts"] == []
    assert people["entities"][0]["data"]["appointments"][0]["office"] == "户部尚书"
    assert [results.pop(f"names-{i}") for i in (0, 2, 4)] == [results.pop(f"names-{i}") for i in (1, 3, 5)]
    queries = {call_id: query for call_id, query in queries.items() if not call_id.startswith("names-")}
    for call_id, query in queries.items():
        result = results[call_id]
        if query.get("kind") == "incumbency":
            name = query["key"]
            assert result["status"] == {
                "陕西巡抚": "vacant", "巡抚": "territory_required", "新城知县": "territory_required", "西安知府": "vacant",
                "内阁大学士": "occupied", "陕西巡府": "office_not_found", "不存在的官职": "office_not_found",
            }[name]
            if name in {"巡抚", "新城知县"}:
                assert set(result["territories"]) == {
                    "巡抚": {"北直隶保定六府"},
                    "新城知县": {"保定府新城县", "济南府新城县", "建昌府新城县", "杭州府新城县"},
                }[name]
            elif name in {"陕西巡府", "不存在的官职"}:
                assert ("巡抚" in result["names_and_aliases"]["office"]) if name == "陕西巡府" else result["names_and_aliases"] == {}
        elif query.get("key") in {"保定府新城县", "北直隶保定府新城县", "户部尚书"}:
            assert len(result["entities"]) == 1
            assert result["facts"] == []
            assert result["entities"][0]["kind"] in {"office", "territory"}
            if query.get("key") == "户部尚书":
                assert result["status"] == "occupied"
                assert result["appointments"][0]["holders"] == ["郭允厚"]
        elif query.get("key") in {"新城县", "县"}:
            assert result["status"] == "not_found"
            assert len(result["names_and_aliases"]["territory"]) == (4 if query["key"] == "新城县" else 1172)
            assert set(result["names_and_aliases"]) == {"territory"}
        elif query.get("kind") == "territory" and "key" not in query:
            assert len(result["catalogue"]) == 1733
            assert {item["kind"] for item in result["catalogue"]} == {"territory"}
        elif query.get("kind") == "person":
            assert result["entities"][0]["key"] == "郭允厚"
        elif "date" in query:
            assert "catalogue" in result
        else:
            assert result["status"] == "not_found"
            assert "names_and_aliases" not in result
