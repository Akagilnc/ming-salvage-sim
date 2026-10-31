"""Medium: one recorded mixed night through HTTP actions and identity read doors."""

import json
from functools import partial
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart, ToolReturnPart
from starlette.testclient import TestClient

from ming.middle.view import Officials, character_input
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


def _declaration_prompt(messages):
    return json.loads(messages[0].parts[0].content.split("\n", 1)[1])


def declaration_reply(messages, response_file, quiet_month=None):
    prompt = _declaration_prompt(messages)
    secret = any(item["decree"]["data"]["secret"] for item in prompt["decrees"])
    name = response_file if secret and prompt["date"]["month"] != quiet_month else "month_empty.txt"
    return (RECORDED / name).read_text()


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
def test_every_model_call_reads_identity_scoped_records(game_db, steps):
    names = ("scene", "NightDeclaration", "Declaration", "simulation", "deliberation", "urgent", "impeachment", "secret_report", "gazette")
    received = {name: [] for name in names}
    tools = {name: [] for name in names}
    model_invocations = {name: [] for name in names}
    declaration = {"facts": [], "decree_events": [], "reports": [{
        "entity_type": "incumbency", "entity": "户部尚书",
        "text": "官报：户部实存银若干。", "audience": "official",
    }]}
    outputs = {
        "scene": "done",
        "NightDeclaration": json.dumps({"facts": [], "decrees": [{"text": "", "origin": "emperor", "secret": False, "turn": 1, "people": ["王体乾"]}]}),
        "Declaration": json.dumps(declaration),
        "urgent": (RECORDED / "sources_empty.txt").read_text(),
        "impeachment": (RECORDED / "sources_empty.txt").read_text(),
        **{name: (RECORDED / f"{name}.txt").read_text() for name in ("simulation", "deliberation", "secret_report", "gazette")},
    }
    for name in names:
        steps[name] = replaying(
            lambda messages, name=name: outputs[name] if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
            else ModelResponse(parts=[ToolCallPart("read_records", {"kind": "incumbency", "key": "户部尚书"}, tool_call_id="office"),
                                      *([] if name == "impeachment" else [
                                          ToolCallPart("read_records", {"kind": "person", "key": "王体乾"}, tool_call_id="person"),
                                          ToolCallPart("read_records", {"kind": "account", "key": "国库"}, tool_call_id="treasury"),
                                          ToolCallPart("read_records", {"kind": "faction", "key": ["阉党", "东林"]}, tool_call_id="factions"),
                                      ])]),
            received[name], tools[name], model_invocations[name],
        )
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "目前陕西巡抚可有？最高长官是谁？"}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        court = client.app.state.web.game.court.read
        reports = court.facts(Officials(people=["郭允厚"]), kind="reported")
        assert reports
        assert {f.entity_id for f in reports} == {
            e.id for e in court.entities("audit", kind="incumbency") if e.data["office"] == "户部尚书"
        }
        assert not court.facts("public", kind="reported")
        assert not court.facts("emperor", kind="reported")
        expected = {
            "scene": Officials(people=["王承恩"]),
            "NightDeclaration": "world", "Declaration": "world", "simulation": "world", "gazette": "public",
            "deliberation": Officials(people=["王体乾"], exclude_secrets=True),
            "urgent": Officials(people=["黄立极", "王体乾"]),
            "secret_report": Officials(people=["王承恩"]),
        }
        for name in names:
            assert model_invocations[name]
            if name != "impeachment":
                assert all(identity == expected[name] for identity in model_invocations[name])
            else:
                assert all(isinstance(identity, Officials) and not identity.exclude_secrets for identity in model_invocations[name])
                assert {frozenset(identity.people) for identity in model_invocations[name]} == {
                    frozenset(client.app.state.web.game.court.read.office_holders(faction=faction.key))
                    for faction in court.entities("audit", kind="faction")
                }
            assert tools[name]
            assert all("read_records" in available and "read_person" not in available for available in tools[name])
            returns = [p.model_response_object() for m in received[name] for p in m.parts
                       if isinstance(p, ToolReturnPart) and p.tool_call_id == "office"]
            assert returns and all(r["appointments"][0]["holders"] == ["郭允厚"] for r in returns)
            identity = model_invocations[name][0]
            responses = {p.tool_call_id: p.model_response_object() for m in received[name] for p in m.parts
                         if isinstance(p, ToolReturnPart)}
            if name != "impeachment":
                assert ("dossier" in responses["person"]["entities"][0]["data"]) == (
                    isinstance(identity, Officials) and "王体乾" in identity.people
                )
                assert ("taels" in next(iter(responses["treasury"].get("entities", [])), {"data": {}})["data"]) == (
                    name in {"NightDeclaration", "Declaration", "simulation", "deliberation", "urgent"}
                )
            if isinstance(identity, Officials) and name != "impeachment":
                factions = {e["key"]: e["data"] for e in responses["factions"]["entities"]}
                assert ("satisfaction" in factions["阉党"]) == (name in {"deliberation", "urgent"})
                assert factions["东林"] == {"name": "东林"}
            for message in received[name]:
                if message.kind != "request" or message.parts[0].part_kind != "user-prompt":
                    continue
                if name in {"urgent", "impeachment", "deliberation", "secret_report"}:
                    data = json.loads(message.parts[0].content)
                    people = [e["key"] for e in data["speakers"]]
                    identity = Officials(people=people, exclude_secrets=name == "deliberation")
                    assert data["speakers"] == [e.model_dump(mode="json") for person in people
                                                for e in court.entities(identity, kind="person", key=person)]
                    assert all({"seed_guilt", "dossier"}.issubset(e["data"]) for e in data["speakers"])
                    assert "factions" not in data["context"]


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
@pytest.mark.parametrize("handler,failure", [("毕尚书", None), ("徐光启", "declaration"), ("徐光启", "report")], ids=["alias", "absent-handler", "report-retry"])
def test_secret_orders_keep_their_readers_and_monthly_products(
    game_db: Path, steps, audit, failure, handler
) -> None:
    case = json.loads((RECORDED / "night_secret.json").read_text())
    declaration = json.loads(case["replies"][0])
    declaration["decrees"][0]["people"] = ["毕自严", "王承恩"] if handler == "毕尚书" else [] if failure == "declaration" else ["王承恩"]
    declaration["decrees"][0].pop("handler")
    declaration["decrees"][0].update({} if handler == "毕尚书" else {"handler": "户部那位老先生"})
    invalid = json.dumps(declaration, ensure_ascii=False)
    declaration["decrees"][0]["handler"] = handler
    steps["scene"] = replaying([m for m in ModelMessagesTypeAdapter.validate_python(case["scene_responses"]) if isinstance(m, ModelResponse)])
    steps["NightDeclaration"] = replaying([invalid, json.dumps(declaration, ensure_ascii=False)])
    handler = "毕自严" if handler == "毕尚书" else handler
    material = []
    declarations = []
    steps["Declaration"] = replaying(
        partial(
            declaration_reply,
            response_file="month_invalid.txt" if failure == "declaration" else "month_secret_appointment.json" if failure is None else "month_journey_dates.json",
        ),
        declarations,
    )
    if failure == "report":
        steps["secret_report"] = replaying([ModelHTTPError(429, "recorded")])
    else:
        steps["secret_report"] = replaying(
            ([ModelResponse(parts=[ToolCallPart("read_records", {"kind": "person", "key": ["毕自严", "徐光启"]})])]
             if failure is None else []) + [(RECORDED / "secret_report.txt").read_text()] * 2, material
        )
    with TestClient(create_app(game_db.parent)) as client:
        client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).raise_for_status()
        for words in case["words"]:
            client.post("/actions", json={"action": "say", "words": words}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        court = client.app.state.web.game.court.read
        orders = court.entities("audit", kind="decree")
        secret = next(d for d in orders if d.data["secret"])
        public = next(d for d in orders if not d.data["secret"])
        gazettes = []
        steps["gazette"] = replaying([
            ModelResponse(parts=[ToolCallPart("read_records", {"kind": "decree", "key": secret.key}, tool_call_id="secret")]),
            (RECORDED / "gazette.txt").read_text(),
        ] * 2, gazettes)
        assert (secret.data["turn"], public.data["turn"]) == (3, 6)
        assert secret.data["handler"] == handler
        assert public.data.get("handler") is None
        assert not court.facts("audit", kind="unhandled")
        assert "exposure" not in secret.data
        for person, expected in (
            (handler, {secret.id}),
            ("王承恩", {secret.id, public.id}),
            ("杨嗣昌", {secret.id}),
            ("王绍徽", {public.id}),
            ("魏忠贤", set()),
        ):
            assert {
                d.id for d in court.entities(Officials(people=[person]), kind="decree")
            } == expected
            assert [
                e.detail["date"]
                for e in court.facts(Officials(people=[person]), entity_id=list(expected), kind="decreed")
            ] == [court.calendar().data] * len(expected)
        assert not court.entities("public", kind="decree")
        assert {
            d.id
            for d in court.entities(
                Officials(people=["王承恩"], exclude_secrets=True), kind="decree"
            )
        } == {public.id}
        assert {f.entity_id for f in court.facts("audit", kind="deliberation")} == {
            public.id
        }
        case["views"] = [client.get("/records").json()]
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        if failure == "report":
            assert (
                client.get("/state").json()["game"]["failure"]["payload"]["type"]
                == "ModelHTTPError"
            )
            before = audit(game_db)
            case["views"].append(client.get("/records").json())
            assert any(f["kind"] == "arrived" for f in before["facts"])
            client.post("/actions", json={"action": "menu"}).raise_for_status()
            client.post(
                "/actions", json={"action": "load", "save": game_db.name}
            ).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            case["views"].append(client.get("/records").json())
            assert all(value == views[0] for views in (
                [[(e["id"], e["data"].get("location"), e["data"].get("transit_to"))
                  for e in view["entities"] if e["kind"] == "person"] for view in case["views"]],
                [[(f["entity_id"], f["kind"], f["detail"].get("date"))
                  for f in view["facts"] if f["kind"] in {"changed", "arrived", "departed"}] for view in case["views"]],
            ) for value in views[1:])
            assert audit(game_db) == before
            steps["secret_report"] = replaying(
                [(RECORDED / "secret_report.txt").read_text()] * 2, material
            )
            client.post("/actions", json={"action": "retry"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        assert all(
            [p["key"] for p in json.loads(part.content)["speakers"]] == [handler]
            for message in material for part in message.parts if part.part_kind == "user-prompt"
        )
        if failure is None:
            returned = next(p.model_response_object() for m in material for p in m.parts if isinstance(p, ToolReturnPart))
            assert {e["key"]: e["data"]["location"] for e in returned["entities"]} == {
                "毕自严": "北直隶 / 京师", "徐光启": "南直隶 / 南京",
            }
            assert any(f["kind"] == "arrived" for f in returned["facts"])
            assert returned == character_input(client.portal.call(court.read_records, Officials(people=[handler]), "person", ["毕自严", "徐光启"]))
        # Repeated months keep recorded knowledge without an exposure accumulator.
        for month in range(2):
            court = client.app.state.web.game.court.read
            assert client.get("/state").json()["game"]["failure"] is None
            assert client.get("/state").json()["game"]["unhandled_monthly"] == (
                [{"entity_id": str(court.calendar().id)}]
                if failure == "declaration" else []
            )
            if failure is None:
                assert [(
                    court.office_record(identity, "陕西巡抚")["status"],
                    any(a["office"] == "巡抚" and a["territory"] == "陕西"
                        for a in court.entities(identity, kind="person", key="洪承畴")[0].data["appointments"]),
                ) for identity in ("world", "emperor", "public", Officials(people=[handler]), Officials(people=["王体乾"]))] == [
                    ("occupied", True), ("occupied", True), ("not_found", False), ("occupied", True), ("not_found", False),
                ]
                private = {f.entity_id for f in court.facts("audit", kind="changed") if f.detail.get("discovered")}
                assert private
                for person in ("emperor", handler, "王承恩", "杨嗣昌", "韩爌"):
                    assert private & {f.entity_id for f in court.facts("emperor" if person == "emperor" else Officials(people=[person]), kind="changed")} == (private if person in ("emperor", handler) else set())
            assert {d.id for d in court.entities("public", kind="decree")} == (
                set() if failure == "declaration" else {public.id}
            )
            assert not court.facts("audit", entity_id=secret.id, kind="exposure", date=None)
            assert "exposure" not in court.entities("audit", ids=[secret.id])[0].data
            assert {f.entity_id for f in court.facts("audit", kind="unhandled")} == (
                {court.calendar().id} if failure == "declaration" else set()
            )
            world = next(
                prompt for r in declarations
                if r.kind == "request" and r.parts[0].part_kind == "user-prompt"
                and (prompt := _declaration_prompt([r]))["scope"] == "month"
                and prompt["date"] == court.facts("emperor", kind="secret_report")[-1].detail["date"]
            )
            assert set(next(o["known_people"] for o in world["decrees"] if o["decree"]["id"] == str(secret.id))) == {handler, "王承恩", "杨嗣昌"}
            assert {o["decree"]["id"] for o in world["decrees"]} == {
                str(d.id) for d in orders if month == 0 or d.id == secret.id or failure != "declaration"
            }
            for person, count in (
                (handler, month + 1),
                ("王承恩", 0),
                ("杨嗣昌", 0),
                ("王绍徽", 0),
                ("魏忠贤", 0),
            ):
                assert (
                    len(court.facts(Officials(people=[person]), kind="secret_report"))
                    == count
                )
            assert [
                f.detail["date"] for f in court.facts("emperor", kind="secret_report")
            ] == [{"id": "world", "year": year, "month": number}
                  for year, number in [(1627, 10), (1627, 11)][:month + 1]]
            assert not court.facts("public", kind="secret_report")
            if month < 1:
                client.post(
                    "/actions", json={"action": "load", "save": game_db.name}
                ).raise_for_status()
                client.post("/actions", json={"action": "month"}).raise_for_status()
                client.portal.call(client.app.state.web.game.drain)
        assert {p.model_response_object()["status"] for m in gazettes for p in m.parts
                if isinstance(p, ToolReturnPart) and p.tool_call_id == "secret"} == {"not_found"}
        assert all(not {"entities", "facts", "names_and_aliases"}.intersection(p.model_response_object())
                   for m in gazettes for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_call_id == "secret")
        for prompt in [json.loads(part.content) for message in material for part in message.parts if part.part_kind == "user-prompt"]:
            assert prompt["context"]["decree"]["id"] == str(secret.id)
            assert all("emperor_words" not in f for f in prompt["context"]["facts"] + prompt["context"]["products"])
            assert "exposure" not in prompt["context"]["decree"]["data"]
            assert all(f["kind"] != "exposure" for f in prompt["context"]["products"])


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
@pytest.mark.parametrize("quiet_month", [None, 10], ids=["done-in-decree-month", "done-next-month"])
def test_discoveries_stay_private_and_completion_stops_only_reports(
    tmp_path: Path, game_db: Path, steps, quiet_month
) -> None:
    steps["Declaration"] = replaying(
        partial(
            declaration_reply,
            response_file="month_secret_completed.txt",
            quiet_month=quiet_month,
        )
    )
    simulations = []
    steps["simulation"] = replaying(
        [(RECORDED / "simulation.txt").read_text()] * 3, simulations
    )
    with TestClient(create_app(tmp_path)) as client:
        client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).raise_for_status()
        court = client.app.state.web.game.court.read
        secret = next(
            d for d in court.entities("audit", kind="decree") if d.data["secret"]
        )
        for month in range(3):
            client.post("/actions", json={"action": "month"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
            court = client.app.state.web.game.court.read
            done = month >= (quiet_month is not None)
            assert len(
                court.facts("audit", entity_id=secret.id, kind="completed", date=None)
            ) == int(done)
            for identity in ("emperor", Officials(people=["王承恩"])):
                assert len(court.facts(identity, kind="secret_report")) == min(
                    month + 1, 1 + (quiet_month is not None)
                )
            assert not court.facts("audit", entity_id=secret.id, kind="exposure", date=None)
            assert "exposure" not in court.entities("audit", ids=[secret.id])[0].data
            changed = [
                f
                for f in court.facts("audit", kind="changed")
                if f.detail.get("origin_ref") == str(secret.id)
            ]
            assert len(changed) == 2 * done
            assert [
                e.detail["date"]
                for e in court.facts(Officials(people=["王承恩"]), entity_id=court.entities("audit", kind="person", key="王承恩")[0].id, kind="changed")
            ] == [f.detail["date"] for f in changed if not f.detail["discovered"]]
            assert (
                court.entities("audit", kind="person", key="韩爌")[0].data["intrigue"]
                == 75
            ) == done
            for identity, discoveries in (
                ("emperor", True),
                ("public", False),
                (Officials(people=["王承恩"]), True),
                (Officials(people=["杨嗣昌"]), False),
                (Officials(people=["韩爌"]), False),
                (Officials(people=["魏忠贤"]), False),
            ):
                assert {f.entity_id for f in court.facts(identity, kind="changed")} == {
                    f.entity_id
                    for f in changed
                    if discoveries or not f.detail["discovered"]
                }
                assert all(
                    "origin_ref" not in f.detail
                    for f in court.facts(identity, kind="changed")
                )
            client.post(
                "/actions", json={"action": "load", "save": game_db.name}
            ).raise_for_status()
        for message in simulations:
            if message.parts[0].part_kind == "user-prompt":
                for order in json.loads(message.parts[0].content)["context"]["decrees"]:
                    if order["decree"]["data"]["secret"]:
                        assert "exposure" not in order["decree"]["data"]
                        assert set(order["known_people"]) == {"王承恩", "杨嗣昌"}
        assert not json.loads(simulations[-1].parts[0].content)["context"]["decrees"]


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_month_lands_an_earlier_public_decree_before_a_later_secret(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    """Both decrees share one monthly declaration, without per-decree landing."""
    cases = json.loads((RECORDED / "night_ordering.json").read_text())
    steps["Declaration"] = replaying([(RECORDED / "month_ordering.txt").read_text()])
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        for case in cases.values():
            steps["scene"] = replaying(ModelMessagesTypeAdapter.validate_python(case["scene_responses"]))
            steps["NightDeclaration"] = replaying([case["declaration"]])
            client.post("/actions", json={"action": "open"}).raise_for_status()
            for words in case["words"]:
                client.post("/actions", json={"action": "say", "words": words}).raise_for_status()
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        ledger = audit(tmp_path / save)
        decrees = [e for e in ledger["entities"] if e["kind"] == "decree"]
        appointment = next(e for e in ledger["entities"] if e["kind"] == "incumbency" and e["data"]["office"] == "巡抚" and e["data"]["territory"] == "陕西")
        assert [e["data"]["secret"] for e in decrees] == [False, True]
        assert not [f for f in ledger["facts"] if f["kind"] == "unhandled"]
        assert appointment["data"]["holders"] == ["杨嗣昌"]
        assert [f["detail"]["actual"]["holders"] for f in ledger["facts"] if f["entity_id"] == appointment["id"] and f["kind"] == "changed"] == [["洪承畴"], ["杨嗣昌"]]
        assert [f["detail"]["origin_ref"] for f in ledger["facts"] if f["entity_id"] == appointment["id"] and f["kind"] == "changed"] == [d["id"] for d in decrees]
