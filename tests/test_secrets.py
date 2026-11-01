"""Medium: one recorded mixed night through HTTP actions and identity read doors."""

import asyncio
import json
from collections import Counter
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from pydantic_ai._run_context import get_current_run_context
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart, ToolReturnPart
from starlette.testclient import TestClient

from ming.middle.view import Officials, character_input
from ming.web import create_app
from tests.test_court import reopening, replaying
from tests.test_read_budget import measure_reads

RECORDED = Path(__file__).parent / "recorded"


def _declaration_prompt(messages):
    return json.loads(messages[0].parts[0].content.split("\n", 1)[1])


def declaration_reply(messages, response_file, quiet_month=None):
    prompt = _declaration_prompt(messages)
    secret = any(item["decree"]["data"]["secret"] for item in prompt["decrees"])
    name = response_file if secret and prompt["date"]["month"] != quiet_month else "month_empty.txt"
    return (RECORDED / name).read_text()


def record_queries(catalogue):
    date = {"year": 1627, "month": 10}
    return {
        "empty": {},
        "class": {"kind": "person"},
        "date": {"date": date},
        "class-date": {"kind": "person", "date": date},
        "dated": {"kind": "person", "key": "王承恩", "date": date},
        "prior": {"kind": "person", "key": "王承恩", "date": {"year": 1627, "month": 9}},
        "prior-class": {"kind": "person", "date": {"year": 1627, "month": 9}},
        "date-original": {"date": {"id": "world", **date}},
        "date-reordered": {"date": {"month": 10, "year": 1627, "id": "world"}},
        "pair": {"kind": "person", "key": ["温体仁", "杨嗣昌"]},
        "many": {"key": [e["key"] for e in catalogue if e["kind"] in {"account", "army"} or e["key"] == "杨嗣昌"]},
        "unknown-key": {"key": "不存在的人"},
        "unknown-kind": {"kind": "不存在的类"},
    }


def assert_model_read_tools(received, tools, model_invocations, court):
    expected = {
        "scene": Officials(people=["王承恩"]),
        "NightDeclaration": "world", "Declaration": "world", "simulation": "world", "gazette": "public",
        "deliberation": Officials(people=["王体乾"], exclude_secrets=True),
        "urgent": Officials(people=["黄立极", "王体乾"]),
        "secret_report": Officials(people=["王承恩"]),
    }
    for name, messages in received.items():
        assert model_invocations[name]
        if name != "impeachment":
            assert all(identity == expected[name] for identity in model_invocations[name])
        else:
            people = court.entities("world", kind="person")
            assert all(isinstance(identity, Officials) and not identity.exclude_secrets for identity in model_invocations[name])
            assert {tuple(identity.people) for identity in model_invocations[name]} == {
                tuple(p.key for p in people if p.data["appointments"] and p.data.get("faction") == faction.key)
                for faction in court.entities("audit", kind="faction")
            }
        identity = model_invocations[name][0]
        assert tools[name]
        assert all("read_records" in available and "read_person" not in available for available in tools[name])
        returns = [p.model_response_object() for m in messages for p in m.parts
                   if isinstance(p, ToolReturnPart) and p.tool_call_id == "office"]
        assert returns and all(r["appointments"][0]["holders"] == ["郭允厚"] for r in returns)
        responses = {p.tool_call_id: p.model_response_object() for m in messages for p in m.parts
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
        if name in {"scene", "simulation", "gazette"}:
            assert responses["empty"]["status"] == "query_required"
            assert all(responses[label]["status"] == "not_found" and "names_and_aliases" not in responses[label]
                       for label in ("unknown-key", "unknown-kind"))
            assert {e["key"] for e in responses["pair"]["entities"]} == {"温体仁", "杨嗣昌"}
            assert {e["kind"] for e in responses["class"]["catalogue"]} == {"person"}
            assert all(set(e) == {"kind", "key", "event_count"} for e in responses["class"]["catalogue"])
            assert responses["date"] == responses["date-original"] == responses["date-reordered"]
            accounts = {e["key"]: e["data"] for e in responses["many"]["entities"] if e["kind"] == "account"}
            if name == "scene":
                assert accounts == {key: {"name": key} for key in ("国库", "内库", "节慎库", "常盈库")}
            elif name == "gazette":
                assert accounts == {}
                assert not [f for f in responses["many"]["facts"] if f["kind"] == "reported"]
            else:
                assert {key: data["taels"] for key, data in accounts.items()} == {
                    "国库": 3200000, "内库": 4400000, "节慎库": 600000, "常盈库": 1200000,
                }
                assert {tuple(f["detail"]["date"][k] for k in ("year", "month"))
                        for f in responses["dated"]["facts"]} == {(1627, 10)}
                assert next(e["event_count"] for e in responses["class-date"]["catalogue"] if e["key"] == "王承恩") == len(responses["dated"]["facts"])
                assert responses["prior"]["facts"] == []
                assert responses["prior-class"]["catalogue"] == []
                assert next(e["data"] for e in responses["many"]["entities"] if e["key"] == "杨嗣昌").items() >= {
                    "loyalty": "颇知向背", "ability": "足任大事", "integrity": "操守平常",
                    "courage": "敢任其事", "identity": "党色极深", "intrigue": "善藏行迹",
                }.items()
                assert next(e.data["loyalty"] for e in court.entities("world", kind="person", key="杨嗣昌")) == 75
                assert {(e["key"], field): e["data"][field] for e in responses["many"]["entities"] if e["kind"] == "army"
                        for field in ("firearm_equipment", "cannon_equipment")} == {
                    (e.key, field): e.data[field] for e in court.entities("audit", kind="army")
                    for field in ("firearm_equipment", "cannon_equipment")
                }
        if name in {"urgent", "impeachment", "deliberation", "secret_report"}:
            for identity, message in zip(model_invocations[name], (
                m for m in messages if m.kind == "request" and m.parts[0].part_kind == "user-prompt"
            ), strict=True):
                data = json.loads(message.parts[0].content)
                # Check speakers against the task identities, not inferred prompt visibility.
                assert data["speakers"] == [e.model_dump(mode="json") for person in identity.people
                                            for e in court.entities(identity, kind="person", key=person)]
                assert all({"seed_guilt", "dossier"}.issubset(e["data"]) for e in data["speakers"])
                assert "factions" not in data["context"]


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
def test_every_model_call_reads_identity_scoped_records(game_db, steps):
    received = {name: [] for name in ("scene", "NightDeclaration", "Declaration", "simulation", "deliberation", "urgent", "impeachment", "secret_report", "gazette")}
    tools = {name: [] for name in received}
    model_invocations = {name: [] for name in received}
    outputs = {
        "scene": "done",
        # Spec boundary: two public tasks share readers, and a second secret task
        # shares the recorded night's handler. No production grouping is replaced.
        "NightDeclaration": json.dumps({"facts": [], "decrees": [
            *[{"text": "", "origin": origin, "secret": False, "turn": 1, "people": ["王体乾"]} for origin in ("emperor", "minister")],
            {"text": "", "origin": "emperor", "secret": True, "turn": 1, "people": ["王承恩"], "handler": "王承恩"},
        ]}),
        "Declaration": json.dumps({"facts": [], "decree_events": [], "reports": [{
            "entity_type": "incumbency", "entity": "户部尚书",
            "text": "官报：户部实存银若干。", "audience": "official",
        }]}),
        "urgent": (RECORDED / "sources_empty.txt").read_text(),
        "impeachment": (RECORDED / "sources_empty.txt").read_text(),
        **{name: (RECORDED / f"{name}.txt").read_text() for name in ("simulation", "deliberation", "secret_report", "gazette")},
    }
    running = Counter()
    overlap = set()
    checked = set()
    started, completed = [], []
    release = asyncio.Event()
    precompute = True
    reads = None
    for name in received:
        async def respond(messages, name=name):
            # Leave both verdicts unfinished for the real month batch, rather
            # than accidentally testing only already-persisted precomputation.
            if name == "deliberation" and precompute:
                return ModelHTTPError(429, "recorded")
            if name in {"deliberation", "urgent", "impeachment", "secret_report"} and not any(
                isinstance(p, ToolReturnPart) for m in messages for p in m.parts
            ):
                deps = get_current_run_context().deps
                data = json.loads(messages[0].parts[0].content)
                assert [e["key"] for e in data["speakers"]] == deps.identity.people
                identity = (tuple(deps.identity.people), deps.identity.exclude_secrets)
                if name == "deliberation":
                    started.append(data["context"]["decree"]["id"])
                if reads is not None and identity not in checked:
                    # The whole group's preparation precedes its first model call.
                    # Check before the test's own visibility query below.
                    assert reads["catalogues"][identity] == 1, identity
                    checked.add(identity)
                assert data["catalogue"] == character_input(deps.court.read.record_catalogue(deps.identity))
            if name in {"deliberation", "impeachment", "secret_report"}:
                running[name] += 1
                if running[name] > 1:
                    overlap.add(name)
                await asyncio.sleep(0)  # Yield at the model boundary, never wait on a wall clock.
                running[name] -= 1
            if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
                # Distinct recorded verdicts are assigned by the task's structured
                # origin, not call order or the prose of either decree.
                if name == "deliberation":
                    decree = json.loads(messages[0].parts[0].content)["context"]["decree"]
                    if decree["id"] == started[0] and len(started) > 1:
                        await release.wait()
                    else:
                        release.set()
                    completed.append(decree["id"])
                    if decree["data"]["origin"] == "minister":
                        return (RECORDED / "deliberation_rejected.txt").read_text()
                return outputs[name]
            return ModelResponse(parts=[
                *(ToolCallPart("read_records", args, tool_call_id=label)
                  for label, args in (record_queries(json.loads(
                      messages[0].parts[0].content[0] if name == "scene" else messages[0].parts[0].content,
                  )["catalogue"]) if name in {"scene", "simulation", "gazette"} else {}).items()),
                ToolCallPart("read_records", {"kind": "incumbency", "key": "户部尚书"}, tool_call_id="office"),
                *([] if name == "impeachment" else [
                    ToolCallPart("read_records", {"kind": "person", "key": "王体乾"}, tool_call_id="person"),
                    ToolCallPart("read_records", {"kind": "account", "key": "国库"}, tool_call_id="treasury"),
                    ToolCallPart("read_records", {"kind": "faction", "key": ["阉党", "东林"]}, tool_call_id="factions"),
                ]),
            ])

        steps[name] = replaying(respond, received[name], tools[name], model_invocations[name])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "目前陕西巡抚可有？最高长官是谁？"}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        precompute = False
        court = client.app.state.web.game.court.read
        with measure_reads(count_rows=False) as reads:
            client.post("/actions", json={"action": "month"}).raise_for_status()
            assert {p["entity_id"] for p in client.get("/state").json()["game"]["petitions"]} == {
                str(d.id) for d in court.entities("audit", kind="decree") if d.data["origin"] == "minister"
            }
            client.post("/actions", json={
                "action": "choose", "petition": client.get("/state").json()["game"]["petitions"][0]["id"], "option": 1,
            }).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        assert completed == started[::-1]
        assert overlap == {"deliberation", "impeachment", "secret_report"}
        assert client.get("/state").json()["game"]["failure"] is None
        reports = court.facts(Officials(people=["郭允厚"]), kind="reported")
        assert reports
        assert {f.entity_id for f in reports} == {
            e.id for e in court.entities("audit", kind="incumbency") if e.data["office"] == "户部尚书"
        }
        assert not court.facts("public", kind="reported")
        assert not court.facts("emperor", kind="reported")
        assert_model_read_tools(received, tools, model_invocations, court)


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
def test_month_retries_only_failed_source(game_db, steps, audit):
    before = audit(game_db)
    factions = sum(e["kind"] == "faction" for e in before["entities"])
    calls = {name: [] for name in ("urgent", "impeachment", "secret_report", "gazette")}
    for name in calls:
        reply = (RECORDED / ("sources_empty.txt" if name in {"urgent", "impeachment"} else f"{name}.txt")).read_text()
        steps[name] = replaying(
            [ModelHTTPError(429, "recorded"), *[reply] * factions] if name == "impeachment" else [reply] * 2,
            identities=calls[name],
        )
    with reopening(game_db.parent) as reopen:
        client = reopen()
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"]["payload"]["type"] == "ModelHTTPError"
        before = audit(game_db)
        completed = {(f["entity_id"], f["kind"]) for f in before["facts"] if f["kind"] in calls}
        assert sum(kind == "impeachment" for _, kind in completed) == factions - 1
        counts = {name: len(values) for name, values in calls.items()}
        client = reopen()
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.post("/actions", json={"action": "retry"}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        before = audit(game_db)
        assert all(sum((f["entity_id"], f["kind"]) == key for f in before["facts"]) == 1 for key in completed)
        assert {name: len(values) - counts[name] for name, values in calls.items()} == {
            name: int(name == "impeachment") for name in calls
        }


def configure_secret_order_retries(steps, case, handler, failure):
    declaration = json.loads(case["replies"][0])
    declaration["decrees"][0]["people"] = ["毕自严", "王承恩"] if handler == "毕尚书" else [] if failure == "declaration" else ["王承恩"]
    declaration["decrees"][0].pop("handler")
    declaration["decrees"][0].update({} if handler == "毕尚书" else {"handler": "户部那位老先生"})
    invalid = json.dumps(declaration, ensure_ascii=False)
    declaration["decrees"][0]["handler"] = handler
    steps["scene"] = replaying([m for m in ModelMessagesTypeAdapter.validate_python(case["scene_responses"]) if isinstance(m, ModelResponse)])
    steps["NightDeclaration"] = replaying([invalid, json.dumps(declaration, ensure_ascii=False)])


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
@pytest.mark.parametrize("handler,failure", [("毕尚书", None), ("徐光启", "declaration"), ("徐光启", "report")], ids=["alias", "absent-handler", "report-retry"])
def test_secret_orders_keep_their_readers_and_monthly_products(
    game_db: Path, steps, audit, failure, handler
) -> None:
    case = json.loads((RECORDED / "night_secret.json").read_text())
    configure_secret_order_retries(steps, case, handler, failure)
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
    with reopening(game_db.parent) as reopen:
        client = reopen()
        client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).raise_for_status()
        for words in case["words"]:
            client.post("/actions", json={"action": "say", "words": words}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        court = client.app.state.web.game.court.read
        secret, public = court.entities("audit", kind="decree")
        assert (secret.data["secret"], public.data["secret"]) == (True, False)
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
        views = [client.get("/records").json()]
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        if failure == "report":
            assert (
                client.get("/state").json()["game"]["failure"]["payload"]["type"]
                == "ModelHTTPError"
            )
            before = audit(game_db)
            views.append(client.get("/records").json())
            assert any(f["kind"] == "arrived" for f in before["facts"])
            client = reopen()
            client.post(
                "/actions", json={"action": "load", "save": game_db.name}
            ).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            views.append(client.get("/records").json())
            assert all(value == values[0] for values in (
                [[(e["id"], e["data"].get("location"), e["data"].get("transit_to"))
                  for e in view["entities"] if e["kind"] == "person"] for view in views],
                [[(f["entity_id"], f["kind"], f["detail"].get("date"))
                  for f in view["facts"] if f["kind"] in {"changed", "arrived", "departed"}] for view in views],
            ) for value in values[1:])
            assert all(
                {e.id for e in client.app.state.web.game.court.read.entities("emperor", **selection)} == expected
                for selection, expected in (
                    ({"ids": [secret.id]}, {secret.id}),
                    ({"ids": [UUID(int=0)]}, set()),
                    ({"ids": []}, set()),
                    ({"ids": [secret.id], "kind": "decree"}, {secret.id}),
                    ({"ids": [secret.id], "kind": "calendar"}, set()),
                    ({"ids": [secret.id], "key": public.key}, set()),
                    ({"ids": [secret.id], "key": [secret.key, public.key]}, {secret.id}),
                )
            )
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
        court = client.app.state.web.game.court.read
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
                str(d.id) for d in (secret, public) if month == 0 or d.id == secret.id or failure != "declaration"
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
                client = reopen()
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
    with reopening(tmp_path) as reopen:
        client = reopen()
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
            client = reopen()
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
