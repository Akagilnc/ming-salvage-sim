"""Medium: HTTP/CLI entry acceptance with per-step recorded model overrides."""

import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.function import FunctionModel
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from ming.middle.court import Court
from ming.middle.invoke import Configuration
from ming.middle.month_work import prompt
from ming.middle.records import Materials, read_records
from ming.middle.view import Officials
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


def record_queries(catalogue, date, secret=None, night=None):
    queries = {
        "empty": {},
        "class": {"kind": "person"},
        "date": {"date": date},
        "date-original": {"date": {"id": "world", **date}},
        "date-reordered": {"date": {"month": date["month"], "year": date["year"], "id": "world"}},
        "class-date": {"kind": "person", "date": date},
        "one": {"kind": "person", "key": "温体仁"},
        "pair": {"kind": "person", "key": ["温体仁", "杨嗣昌"]},
        "many": {"key": [e["key"] for e in catalogue if e["kind"] in {"account", "army"} or e["key"] == "杨嗣昌"]},
        "named": {"key": [e["key"] for e in catalogue]},
        "dated": {"key": "徐光启", "date": {"id": "world", **date}},
        "dated-ym": {"key": "徐光启", "date": {"year": date["year"], "month": date["month"]}},
        "prior": {"key": [e["key"] for e in catalogue], "date": {"year": date["year"], "month": date["month"] - 1}},
        "unknown-key": {"key": "不存在的人"},
        "unknown-kind": {"kind": "不存在的类"},
        "office": {"kind": "incumbency", "key": "陕西巡抚"},
        "office-person": {"kind": "person", "key": "洪承畴"},
        "self": {"kind": "person", "key": "王体乾"},
        "faction": {"kind": "faction", "key": "阉党"},
        "other": {"kind": "faction", "key": "东林"},
    }
    if secret is not None:
        queries["secret"] = {"kind": "decree", "key": secret}
    if night is not None:
        queries["night"] = {"kind": "night", "key": night}
    return queries


def record_months(baseline, audit):
    # Public projection can erase dates. Align complete event groups, never prose.
    dates = defaultdict(list)
    for fact in audit["facts"]:
        dates[fact["entity_id"], fact["kind"]].append(fact["detail"].get("date", {}))
    sizes = Counter((f["entity_id"], f["kind"]) for f in baseline["facts"])
    seen = Counter()
    months = []
    for fact in baseline["facts"]:
        key = fact["entity_id"], fact["kind"]
        if "date" not in fact["detail"]:
            assert sizes[key] == len(dates[key])
        months.append(fact["detail"].get("date", dates[key][seen[key]]))
        seen[key] += 1
    return months


async def assert_record_queries(court: Court, secret_appointment: bool = False) -> None:
    audit = await court.read_records("audit")
    rows = {e["id"]: e for e in audit["entities"]}
    for identity in ("world", "emperor", "public", Officials(people=["郭允厚"], exclude_secrets=True),
                     Officials(people=["王承恩"]), Officials(people=["王体乾"])):
        baseline = await court.read_records(identity)
        months = record_months(baseline, audit)
        counts = Counter(f["entity_id"] for f in baseline["facts"])
        catalogue = json.loads(prompt(court, identity, {}))["catalogue"]
        assert len(catalogue) == len({e["id"] for e in baseline["entities"]} | counts.keys())
        assert {(e["kind"], e["key"], e["event_count"]) for e in catalogue} == {
            (rows[entity_id]["kind"], rows[entity_id]["key"], counts[entity_id])
            for entity_id in {e["id"] for e in baseline["entities"]} | counts.keys()
        }
        assert all(set(e) == {"kind", "key", "event_count"} for e in catalogue)
        assert any(e["event_count"] == 0 for e in catalogue)
        queries = record_queries(
            catalogue,
            court.calendar().data | {"month": court.calendar().data["month"] - bool(baseline["facts"])},
            next((e["key"] for e in rows.values() if e["kind"] == "decree" and e["data"]["secret"]), None),
            next((e["key"] for e in rows.values() if e["kind"] == "night"), None),
        )
        # Native graph entry keeps the real tool schema and dispatch; only the model is recorded.
        async with Agent(
            replaying([
                ModelResponse(parts=[ToolCallPart("read_records", args, tool_call_id=label) for label, args in queries.items()]),
                "done",
            ]),
            deps_type=Materials, tools=[read_records],
        ).iter(prompt(court, identity, {}), deps=Materials(court, identity)) as run:
            async for _ in run:
                pass
        results = {
            part.tool_call_id: part.model_response_object()
            for m in run.all_messages() for part in m.parts if isinstance(part, ToolReturnPart)
        }
        assert results.keys() == queries.keys()
        assert results["empty"]["status"] == "query_required"
        for label in ("unknown-key", "unknown-kind"):
            assert results[label]["status"] == "not_found"
            assert "names_and_aliases" not in results[label]
        assert set(results["empty"]).isdisjoint({"entities", "facts", "catalogue"})
        for label in ("class", "date", "class-date"):
            assert set(results[label]) == {"catalogue"}
            counts = Counter(
                (rows[f["entity_id"]]["kind"], rows[f["entity_id"]]["key"])
                for f, month in zip(baseline["facts"], months, strict=True)
                if label == "class" or all(month.get(k) == queries[label]["date"][k] for k in ("year", "month"))
            )
            assert Counter((e["kind"], e["key"], e["event_count"]) for e in results[label]["catalogue"]) == Counter(
                (e["kind"], e["key"], counts[e["kind"], e["key"]]) for e in catalogue
                if (label == "date" or e["kind"] == "person")
                and (label == "class" or counts[e["kind"], e["key"]])
            )
        assert [e["key"] for e in results["one"]["entities"]] == ["温体仁"]
        assert {e["key"] for e in results["pair"]["entities"]} == {"温体仁", "杨嗣昌"}
        assert len(results["pair"]["entities"]) == 2
        for label in ("one", "pair", "many", "named", "dated", "dated-ym", "prior"):
            ids = {
                e["id"] for e in rows.values()
                if ("kind" not in queries[label] or e["kind"] == queries[label]["kind"])
                and e["key"] in ([queries[label]["key"]] if isinstance(queries[label]["key"], str) else queries[label]["key"])
            }
            expected = {
                "entities": [e for e in baseline["entities"] if e["id"] in ids],
                "facts": [
                    f for f, month in zip(baseline["facts"], months, strict=True)
                    if f["entity_id"] in ids
                    and ("date" not in queries[label] or all(month.get(k) == queries[label]["date"][k] for k in ("year", "month")))
                ],
            } if label != "named" else baseline
            counts = [
                Counter((f["entity_id"], f["kind"], tuple(f["detail"].get("date", {}).get(k) for k in ("year", "month"))) for f in facts)
                for facts in (results[label]["facts"], expected["facts"])
            ]
            assert counts[0] == counts[1]
            assert Counter((e["id"], frozenset(e["data"])) for e in results[label]["entities"]) == Counter(
                (e["id"], frozenset(e["data"])) for e in expected["entities"]
            )
        known = identity in ("world", "emperor") or identity == Officials(people=["王承恩"])
        assert results["office"]["status"] == ("vacant" if not secret_appointment else "occupied" if known else "not_found")
        assert any(a["office"] == "巡抚" and a["territory"] == "陕西"
                   for a in results["office-person"]["entities"][0]["data"]["appointments"]) == (secret_appointment and known)
        assert any(f["detail"].get("office") == "巡抚" for f in results["office-person"]["facts"]) == (secret_appointment and known)
        if isinstance(identity, Officials):
            accounts = {e["key"]: e["data"] for e in results["named"]["entities"] if e["kind"] == "account"}
            assert {k for k, data in accounts.items() if data == {"name": k}} == (
                {"国库", "内库", "节慎库", "常盈库"} if identity.people == ["王承恩"] else {"节慎库"}
            )
            assert accounts.keys() == {"国库", "内库", "节慎库", "常盈库"}
            data = results["self"]["entities"][0]["data"]
            assert {"loyalty", "integrity", "courage", "intrigue", "identity", "seed_guilt", "dossier"}.issubset(data) == ("王体乾" in identity.people)
            assert data.get("loyalty") == ("心志浮动" if "王体乾" in identity.people else None)
            assert ("satisfaction" in results["faction"]["entities"][0]["data"]) == ("王体乾" in identity.people or "郭允厚" in identity.people)
            assert results["other"]["entities"][0]["data"] == {"name": "东林"}
        if "night" in results:
            assert bool(results["night"].get("entities")) == known
        if "secret" in results:
            if known:
                assert [e["key"] for e in results["secret"]["entities"]] == [queries["secret"]["key"]]
            else:
                assert results["secret"]["status"] == "not_found"
                assert queries["secret"]["key"] not in results["secret"].get("names_and_aliases", {}).get("decree", {})


def test_menu_creates_distinct_games_and_opens_only_existing_saves(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        menu = client.get("/state").json()
        assert (menu["saves"], menu["save"], menu["game"]) == ([], None, None)
        assert client.post("/actions", json={"action": "continue"}).status_code == 404
        assert (
            client.post(
                "/actions", json={"action": "load", "save": "missing.sqlite"}
            ).status_code
            == 404
        )
        first = client.post("/actions", json={"action": "new"}).json()["save"]
        second = client.post("/actions", json={"action": "new"}).json()["save"]
        assert first != second
        assert set(client.get("/state").json()["saves"]) == {first, second}
        assert (
            client.post("/actions", json={"action": "continue"}).json()["save"]
            == second
        )
        assert (
            client.post("/actions", json={"action": "load", "save": first}).json()[
                "save"
            ]
            == first
        )
        asyncio.run(assert_record_queries(client.app.state.web.game.court))
        records = client.get("/records").json()
        assert {e["kind"] for e in records["entities"]} == {
            "person",
            "calendar",
            "gazette",
            "incumbency",
        }
        assert all(
            set(e["data"]) <= {"name", "appointments", "location", "status", "identity_description", "transit_to", "waiting_audience", "journey"}
            for e in records["entities"]
            if e["kind"] == "person"
        )
        assert (
            client.post(
                "/actions", json={"action": "load", "save": "../outside.sqlite"}
            ).status_code
            == 400
        )
    with TestClient(create_app(tmp_path)) as client:
        assert set(client.get("/state").json()["saves"]) == {first, second}
        assert client.get("/state").json()["game"] is None
        assert (
            client.post("/actions", json={"action": "continue"}).json()["save"]
            == second
        )


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize(
    ("path", "game_db"),
    [
        (
            path,
            "opening_db"
            if path in {"multiple-petitions", "choice-error"}
            else "first_night",
        )
        for path in (
            "multiple-petitions",
            "choice-error",
            "decree",
            "precompute-error",
            "precompute-structure",
            "translation-error",
        )
    ],
    indirect=["game_db"],
)
def test_http_month_dispatches_choices_and_retries_missing_step(
    game_db: Path, path: str, steps, audit, clock
) -> None:
    money = json.loads((RECORDED / "month_money_once_300000.json").read_text())["reply"]
    received = {name: [] for name in ("deliberation", "simulation", "gazette")}
    if path in {"multiple-petitions", "choice-error"}:
        case = (RECORDED / "month_multiple_petitions.txt").read_text()
        steps["simulation"] = replaying([case])
        steps["month_final"] = replaying(
            ([RuntimeError("final unavailable")] if path == "choice-error" else [])
            + [(RECORDED / "simulation.txt").read_text()]
        )
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        db = game_db
        if path in {
            "decree",
            "precompute-error",
            "precompute-structure",
            "translation-error",
        }:
            for name in received:
                text = (RECORDED / f"{name}.txt").read_text()
                steps[name] = replaying(
                    lambda messages, text=text: (
                        ModelResponse(parts=[TextPart(text)])
                        if any(
                            isinstance(part, ToolReturnPart)
                            for m in messages
                            for part in m.parts
                        )
                        else ModelResponse(parts=[
                            ToolCallPart("read_records", args, tool_call_id=label)
                            for label, args in record_queries(
                                json.loads(messages[0].parts[0].content)["catalogue"],
                                {"year": 1627, "month": 10},
                            ).items()
                            if label in {"empty", "date", "date-original", "date-reordered", "unknown-key", "many"}
                        ])
                    ),
                    received[name],
                )
            case = json.loads((RECORDED / "night_approved.json").read_text())
            steps["NightDeclaration"] = (
                replaying([ModelHTTPError(429, "recording"), *case["replies"]])
                if path == "translation-error"
                else steps["NightDeclaration"]
            )
            steps["Declaration"] = TestModel(call_tools=[], custom_output_text=money)
            if path in {"precompute-error", "precompute-structure"}:
                steps["deliberation"] = replaying(
                    [
                        *(
                            [ModelHTTPError(500, "recording")] * 3
                            if path == "precompute-error"
                            else [(RECORDED / "deliberation_invalid.txt").read_text()]
                            * 4
                        ),
                        (RECORDED / "deliberation.txt").read_text(),
                    ]
                )
            for words in case["words"]:
                assert (
                    client.post(
                        "/actions", json={"action": "say", "words": words}
                    ).status_code
                    == 204
                )
            client.post("/actions", json={"action": "load", "save": save})
            if path == "translation-error":
                assert (
                    client.get("/state").json()["game"]["failure"]["action"]
                    == "translation"
                )
                received["retry"] = []

                async def retry_translation(messages, info):
                    async with AsyncClient(transport=ASGITransport(app), base_url="http://game") as http:
                        state = (await http.get("/state")).json()["game"]
                        opened = await http.post("/actions", json={"action": "open"})
                        received["retry"].append((state["running"], state["pending"], opened.status_code))
                    return ModelResponse(parts=[TextPart(case["replies"][0])])

                steps["NightDeclaration"] = FunctionModel(retry_translation)
                assert (
                    client.post("/actions", json={"action": "retry"}).status_code == 200
                )
                assert client.portal is not None
                client.portal.call(app.state.web.game.drain)
                assert received.pop("retry") == [(False, None, 200)]
                steps["NightDeclaration"] = replaying([(RECORDED / "night_empty.txt").read_text()])
                client.post("/actions", json={"action": "dismiss"}).raise_for_status()
                client.portal.call(app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
            ledger = audit(db)
            decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
            products = [
                f["kind"] for f in ledger["facts"] if f["entity_id"] == decree["id"]
            ]
            assert products.count("deliberation") == int(
                path not in {"precompute-error", "precompute-structure"}
            )
            assert not set(products).intersection({"simulation", "declaration"})
            assert {
                f["entity_id"] for f in ledger["facts"] if f["kind"] == "simulation"
            } == set()
            assert client.get("/state").json()["game"]["date"]["month"] == 10
            assert clock == ([5, 5] if path == "precompute-error" else [])
            assert {
                f["detail"]["action"]
                for f in audit(db)["facts"]
                if f["kind"] == "interaction" and f["detail"]["status"] == "failed"
            } == ({"translation"} if path == "translation-error" else set())
        before = audit(db)
        assert [
            client.post("/actions", json={"action": "choose", **parameters}).status_code
            for parameters in ({}, {"petition": None}, {"petition": str(uuid4())})
        ] == [400, 400, 400]
        assert client.get("/state").json()["game"]["failure"] is None
        assert audit(db) == before
        assert client.post("/actions", json={"action": "month"}).status_code == 204
        game = client.get("/state").json()["game"]
        if path == "precompute-structure":
            assert game["date"]["month"] == 10
            assert game["failure"]["payload"]["type"] == "UnexpectedModelBehavior"
            assert not [f for f in audit(db)["facts"] if f["kind"] == "unhandled"]
            client.post("/actions", json={"action": "retry"})
            game = client.get("/state").json()["game"]
        if path in {"multiple-petitions", "choice-error"}:
            client.portal.call(app.state.web.game.drain)
            assert (game["date"]["month"], game["face"], game["running"]) == (
                10,
                "month",
                False,
            )
            before = audit(db)
            client.get("/state")
            assert not [f for f in client.get("/records").json()["facts"] if f["kind"] in {"month_draft", "month_final", "forecast"}]
            assert not [f for f in before["facts"] if f["kind"] in {"month_final", "forecast"}]
            assert audit(db) == before
            for petition in game["petitions"][:]:
                choice = {"action": "choose", "petition": petition["id"], "option": 0}
                assert (
                    client.post("/actions", json={**choice, "option": -1}).status_code
                    == 400
                )
                assert client.post("/actions", json=choice).status_code == 204
                assert client.post("/actions", json=choice).status_code == 400
                game["petitions"].remove(petition)
                if game["petitions"]:
                    assert not [f for f in audit(db)["facts"] if f["kind"] == "month_final"]
                assert {
                    p["id"] for p in client.get("/state").json()["game"]["petitions"]
                } == {p["id"] for p in game["petitions"]}
        # Choice completion no longer waits for the shared month action.
        client.portal.call(app.state.web.game.drain)
        if path == "choice-error":
            game = client.get("/state").json()["game"]
            assert game["failure"]["action"] == "month"
            assert game["date"]["month"] == 10
            before = audit(db)
            assert not [f for f in before["facts"] if f["kind"] == "month_final"]
            client.post("/actions", json={"action": "load", "save": save}).raise_for_status()
            client.post("/actions", json={"action": "retry"}).raise_for_status()
            assert len([f for f in audit(db)["facts"] if f["kind"] == "month_draft"]) == 1
        game = client.get("/state").json()["game"]
        assert (
            game["date"]["month"],
            game["face"],
            game["running"],
            game["failure"],
            game["petitions"],
        ) == (11, "desk", False, None, [])
        ledger = audit(db)
        assert len([f for f in ledger["facts"] if f["kind"] == "gazette"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "month_draft"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "month_final"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "declaration"]) == 1
        assert [
            f["detail"]["date"]
            for f in client.get("/records").json()["facts"]
            if f["kind"] == "gazette"
        ] == [{"id": "world", "year": 1627, "month": 10}]
        if path == "decree":
            decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
            assert {
                f["kind"] for f in ledger["facts"] if f["entity_id"] == decree["id"]
            } >= {
                "deliberation",
                "landed",
            }
            assert [
                f
                for f in ledger["facts"]
                if f["kind"] == "changed" and "taels" in f["detail"]["actual"]
            ]
            materials = {
                name: [
                    part.model_response_object()
                    for m in messages
                    for part in m.parts
                    if isinstance(part, ToolReturnPart) and part.tool_call_id == "many"
                ]
                for name, messages in received.items()
            }
            case = [
                {part.tool_call_id: part.model_response_object()
                 for m in messages for part in m.parts if isinstance(part, ToolReturnPart)}
                for messages in received.values()
            ]
            assert all("names_and_aliases" not in data["unknown-key"] for data in case)
            assert all(data["date"] == data["date-original"] == data["date-reordered"] for data in case)
            assert not [f for f in materials["gazette"][0]["facts"] if f["kind"] == "reported"]
            assert all(
                {e["key"]: e["data"] for e in data["entities"] if e["kind"] == "account"}
                == {name: {"name": name} for name in ("国库", "内库", "节慎库", "常盈库")}
                for data in materials["deliberation"]
            )
            assert all(not [e for e in data["entities"] if e["kind"] == "account"] for data in materials["gazette"])
            assert {
                e["key"]: e["data"]["taels"]
                for e in materials["simulation"][0]["entities"]
                if e["kind"] == "account"
            } == {"国库": 3200000, "内库": 4400000, "节慎库": 600000, "常盈库": 1200000}
            assert (
                next(
                    e["data"]
                    for e in materials["simulation"][0]["entities"]
                    if e["kind"] == "person" and e["key"] == "杨嗣昌"
                ).items()
                >= {
                    "loyalty": "颇知向背",
                    "ability": "足任大事",
                    "integrity": "操守平常",
                    "courage": "敢任其事",
                    "identity": "党色极深",
                    "intrigue": "善藏行迹",
                }.items()
            )
            assert {
                (e["key"], field): e["data"][field]
                for e in materials["simulation"][0]["entities"]
                if e["kind"] == "army"
                for field in ("firearm_equipment", "cannon_equipment")
            } == {
                (e["key"], field): e["data"][field]
                for e in ledger["entities"]
                if e["kind"] == "army"
                for field in ("firearm_equipment", "cannon_equipment")
            }
            assert (
                next(
                    e["data"]["loyalty"]
                    for e in audit(db, identity="world")["entities"]
                    if e["kind"] == "person" and e["key"] == "杨嗣昌"
                )
                == 75
            )
        before = audit(db)
        client.get("/state")
        client.get("/records")
        assert audit(db) == before


@pytest.mark.parametrize(
    ("step", "failure", "game_db"),
    [
        (
            step,
            RuntimeError,
            "opening_db"
            if step == "month"
            else "first_night"
            if step == "say"
            else "spoken_night",
        )
        for step in (
            "say",
            "translation",
            "month-translation",
            "translation-then-month",
            "month",
        )
    ]
    + [
        ("translation", ConnectionError, "spoken_night"),
        ("translation", UnexpectedModelBehavior, "spoken_night"),
    ],
    indirect=["game_db"],
)
def test_settings_survive_reopening_and_failed_scene_retries_in_place(
    tmp_path: Path, game_db: Path, step: str, failure: type[Exception], steps
) -> None:
    case = json.loads((RECORDED / "night_invalid.json").read_text())
    name = (
        "scene"
        if step == "say"
        else "NightDeclaration"
        if "translation" in step
        else "simulation"
    )
    working = steps[name]
    steps[name] = replaying([failure("external backend unavailable")] * 2)
    settings = Configuration(backend="claude-cli")
    with TestClient(create_app(tmp_path)) as client:
        assert (
            client.post(
                "/actions",
                json={"action": "settings", "settings": {"backend": "unknown"}},
            ).status_code
            == 400
        )
        client.post(
            "/actions", json={"action": "settings", "settings": settings.model_dump()}
        )
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        if step == "month":
            client.post("/actions", json={"action": "month"})
        elif step == "say":
            client.post(
                "/actions", json={"action": "say", "words": case["emperor_words"]}
            )
        else:
            client.post("/actions", json={"action": "dismiss"})
            client.post("/actions", json={"action": "load", "save": save})
            if step == "month-translation":
                client.post("/actions", json={"action": "month"})
        game = client.get("/state").json()["game"]
        if step == "translation-then-month":
            assert game["failure"]["action"] == "translation"
            steps[name] = working
            client.post("/actions", json={"action": "month"})
            state = client.get("/state").json()["game"]
            assert state["failure"] is None
            assert state["date"]["month"] == 11
            assert state["running"] is False
            return
        assert game["failure"]["action"] == (
            "translation" if step.endswith("translation") else step
        )
        assert game["failure"]["payload"]["type"] == failure.__name__
        assert not [
            f
            for f in client.get("/records").json()["facts"]
            if f["kind"] == "unhandled"
        ]
        assert game["date"]["month"] == 10
        if step == "say":
            assert game["night"]["turns"] == []
    steps[name] = working
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/state").json()["settings"] == settings.model_dump()
        client.post("/actions", json={"action": "continue"})
        assert client.get("/state").json()["game"]["failure"] == game["failure"]
        client.post("/actions", json={"action": "retry"})
        if step == "translation":
            client.portal.call(client.app.state.web.game.drain)
        game = client.get("/state").json()["game"]
        assert game["failure"] is None
        if step == "say":
            assert len(game["night"]["turns"]) == 1
        elif step == "translation":
            assert game["date"]["month"] == 10
            assert game["night"]["result"] == "unhandled"
        else:
            assert game["date"]["month"] == 11
        assert game["running"] is False


@pytest.mark.parametrize(
    "case",
    [
        (500, 1, [5], "simulation"),
        (500, 3, [5, 5], "simulation"),
        (429, 1, [], "simulation"),
        (500, 3, [5, 5], "gazette"),
        ("structure", 2, [], "simulation"),
        *[
            (status, attempts, waits, name)
            for name in ("urgent", "impeachment")
            for status, attempts, waits in (
                (500, 3, [5, 5]),
                ("structure", 2, []),
                ("name", 2, []),
            )
        ],
    ],
)
def test_month_transport_retry_is_bounded_and_persistent(
    game_db: Path, case, steps, clock, audit
) -> None:
    status, failures, waits, name = case
    source = name in {"urgent", "impeachment"}
    bad = (
        json.loads((RECORDED / f"sources_{name}-{status}.json").read_text())
        if source and isinstance(status, str)
        else [
            (RECORDED / "simulation_invalid.txt").read_text()
            if status == "structure"
            else ModelHTTPError(status, "recording")
            for _ in range(failures)
        ]
    )
    replies = iter(
        [
            *bad,
            (
                RECORDED / (f"sources_{name}.txt" if source else f"{name}.txt")
            ).read_text(),
        ]
    )

    def reply(messages):
        if (
            name == "impeachment"
            and json.loads(messages[0].parts[0].content)["context"]["faction"]
            != "阉党"
        ):
            return (RECORDED / "sources_empty.txt").read_text()
        return next(replies)

    steps[name] = replaying(reply)
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "month"})
        state = client.get("/state").json()["game"]
        assert clock == waits
        if failures == 3 or status in (429, "structure", "name"):
            assert state["failure"]["payload"]["type"] == (
                "UnexpectedModelBehavior"
                if isinstance(status, str)
                else "ModelHTTPError"
            )
            before = audit(game_db)
            assert not [f for f in before["facts"] if f["kind"] == "unhandled"]
            if source:
                factions = len(
                    [e for e in before["entities"] if e["kind"] == "faction"]
                )
                assert len([f for f in before["facts"] if f["kind"] == "gazette"]) == 1
                assert len(
                    [f for f in before["facts"] if f["kind"] == "impeachment"]
                ) == factions - (name == "impeachment")
            assert state["date"]["month"] == 10
            if name == "gazette":
                before = audit(game_db)
                assert (
                    len([f for f in before["facts"] if f["kind"] == "month_accounts"])
                    == 1
                )
                balances = {
                    e["key"]: e["data"]["taels"]
                    for e in before["entities"]
                    if e["kind"] == "account"
                }
                client.post("/actions", json={"action": "load", "save": game_db.name})
            client.post("/actions", json={"action": "continue"})
            assert client.get("/state").json()["game"]["failure"] == state["failure"]
            client.post("/actions", json={"action": "retry"})
        state = client.get("/state").json()["game"]
        assert state["date"]["month"] == 11
        assert state["failure"] is None
        ledger = audit(game_db.parent / client.get("/state").json()["save"])
        assert len([f for f in ledger["facts"] if f["kind"] == "landed"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "gazette"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "urgent"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "impeachment"]) == len(
            [e for e in ledger["entities"] if e["kind"] == "faction"]
        )
        if source:
            assert all(
                f in ledger["facts"]
                for f in before["facts"]
                if f["kind"] != "interaction"
            )
        assert len([f for f in ledger["facts"] if f["kind"] == "month_accounts"]) == 1
        if name == "gazette":
            assert {
                e["key"]: e["data"]["taels"]
                for e in ledger["entities"]
                if e["kind"] == "account"
            } == balances
