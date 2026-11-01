"""Medium: HTTP/CLI entry acceptance with per-step recorded model overrides."""

import asyncio
import json
import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager, closing
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from ming.middle.court import Court
from ming.middle.invoke import Configuration
from ming.web import create_app
from tests.test_court import reopening, replaying

RECORDED = Path(__file__).parent / "recorded"


def state_updates(events: asyncio.Queue) -> list[dict]:
    """Read the state payloads delivered to the existing stream subscriber."""
    return [
        event["data"]
        for event in (events.get_nowait() for _ in range(events.qsize()))
        if event["event"] == "state"
    ]


def test_menu_creates_distinct_games_and_opens_only_existing_saves(
    tmp_path: Path,
) -> None:
    app = create_app(tmp_path)
    events = asyncio.Queue()
    app.state.web.listeners.add(events)
    with TestClient(app) as client:
        menu = client.get("/state").json()
        assert (menu["saves"], menu["save"], menu["game"]) == ([], None, None)
        assert client.post("/actions", json={"action": "continue"}).status_code == 404
        assert (
            client.post(
                "/actions", json={"action": "load", "save": "missing.sqlite"}
            ).status_code
            == 404
        )
        assert state_updates(events) == []
        first = client.post("/actions", json={"action": "new"}).json()["save"]
        assert [state["save"] for state in state_updates(events)] == [first]
        client.post("/actions", json={"action": "open"}).raise_for_status()
        assert [state["game"]["face"] for state in state_updates(events)] == ["audience"]
        client.post("/actions", json={"action": "open"}).raise_for_status()
        assert state_updates(events) == []
        before = client.get("/records").json()
        night = client.get("/state").json()["game"]["night"]
        for _ in range(2):
            client.post("/actions", json={"action": "menu"}).raise_for_status()
            menu = client.get("/state").json()
            assert (menu["save"], menu["game"]) == (None, None)
            assert [(state["save"], state["game"]) for state in state_updates(events)] == (
                [(None, None)] if _ == 0 else []
            )
        client.post("/actions", json={"action": "load", "save": first}).raise_for_status()
        assert [(state["save"], state["game"]["night"]["id"]) for state in state_updates(events)] == [(first, night["id"])]
        assert client.get("/state").json()["game"]["night"] == night
        assert client.get("/records").json() == before
        second = client.post("/actions", json={"action": "new"}).json()["save"]
        assert [state["save"] for state in state_updates(events)] == [second]
        assert first != second
        assert set(client.get("/state").json()["saves"]) == {first, second}
        assert (
            client.post("/actions", json={"action": "continue"}).json()["save"]
            == second
        )
        assert state_updates(events) == []
        assert (
            client.post("/actions", json={"action": "load", "save": first}).json()[
                "save"
            ]
            == first
        )
        assert [state["save"] for state in state_updates(events)] == [first]
        records = client.get("/records").json()
        assert {e["kind"] for e in records["entities"]} == {
            "person",
            "calendar",
            "gazette",
            "incumbency",
            "night",
        }
        assert all(
            set(e["data"]) <= {"name", "appointments", "location", "status", "identity_description", "transit_to", "waiting_audience", "departure_date", "arrival_date", "travel_speed"}
            for e in records["entities"]
            if e["kind"] == "person"
        )
        assert (
            client.post(
                "/actions", json={"action": "load", "save": "../outside.sqlite"}
            ).status_code
            == 400
        )
        assert state_updates(events) == []
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
            else "approved_night" if path == "decree" else "first_night",
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
    if path not in {"multiple-petitions", "choice-error"}:
        steps["Declaration"] = TestModel(call_tools=[], custom_output_text=(RECORDED / "month_decree_money.txt").read_text())
    received = {}
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
            "precompute-error",
            "precompute-structure",
            "translation-error",
        }:
            case = json.loads((RECORDED / "night_approved.json").read_text())
            steps["NightDeclaration"] = (
                replaying([ModelHTTPError(429, "recording"), *case["replies"]])
                if path == "translation-error"
                else steps["NightDeclaration"]
            )
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
                        # Preserve the accepted old-night work, with the new
                        # night already open, at the external model boundary.
                        (game_db.parent / "recovery").mkdir()
                        with closing(sqlite3.connect(game_db)) as source, closing(
                            sqlite3.connect(game_db.parent / "recovery" / game_db.name)
                        ) as target:
                            source.backup(target)
                    return ModelResponse(parts=[TextPart(case["replies"][0])])

                steps["NightDeclaration"] = FunctionModel(retry_translation)
                assert (
                    client.post("/actions", json={"action": "retry"}).status_code == 204
                )
                assert client.portal is not None
                client.portal.call(app.state.web.game.drain)
                assert received.pop("retry") == [(False, None, 204)]
                # The other HTTP chain opened this night while translation awaited.
                assert client.get("/state").json()["game"]["night"]["closed"] is False
                steps["NightDeclaration"] = replaying(case["replies"])
                with TestClient(create_app(game_db.parent / "recovery")) as restored:
                    events = asyncio.Queue()
                    restored.app.state.web.listeners.add(events)
                    restored.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
                    restored.portal.call(restored.app.state.web.game.drain)
                    game = restored.get("/state").json()["game"]
                    assert game["night"]["closed"] is False
                    # Opening and finishing recovery each refresh once;
                    # completion refreshes /records even with the same night.
                    assert [
                        (state["game"]["night"]["id"], state["game"]["running"], state["game"]["failure"])
                        for state in state_updates(events)
                    ] == [(game["night"]["id"], False, None)] * 2
                    assert [
                        entity["data"]["result"]
                        for entity in restored.get("/records").json()["entities"]
                        if entity["kind"] == "night" and entity["data"]["closed"]
                    ] == ["translated"]
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
        events = asyncio.Queue()
        app.state.web.listeners.add(events)
        assert client.post("/actions", json={"action": "month"}).status_code == 204
        game = client.get("/state").json()["game"]
        # One acceptance and one completion, regardless of monthly writes.
        assert [
            (state["game"]["running"], state["game"]["date"]["month"],
             state["game"]["failure"] and state["game"]["failure"]["action"])
            for state in state_updates(events)
        ] == [
            (True, 10, None),
            (False, game["date"]["month"],
             "month" if path == "precompute-structure" else None),
        ]
        if path == "precompute-structure":
            assert game["date"]["month"] == 10
            assert game["failure"]["payload"]["type"] == "UnexpectedModelBehavior"
            assert not [f for f in audit(db)["facts"] if f["kind"] == "unhandled"]
            client.post("/actions", json={"action": "retry"})
            game = client.get("/state").json()["game"]
            assert [
                (state["game"]["running"], state["game"]["failure"])
                for state in state_updates(events)
            ] == [(True, None), (False, None)]
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
                assert client.post("/actions", json=choice).status_code == 204
                game["petitions"].remove(petition)
                if game["petitions"]:
                    assert not [f for f in audit(db)["facts"] if f["kind"] == "month_final"]
                client.portal.call(app.state.web.game.drain)
                assert {
                    p["id"] for p in client.get("/state").json()["game"]["petitions"]
                } == {p["id"] for p in game["petitions"]}
                # The last choice completes and starts the month in ONE frame;
                # monthly commits add none.
                assert [
                    (state["game"]["running"],
                     state["game"]["pending"] and state["game"]["pending"]["action"],
                     state["game"]["date"]["month"],
                     {p["id"] for p in state["game"]["petitions"]})
                    for state in state_updates(events)
                ] == [
                    (True, "choose", 10, {p["id"] for p in game["petitions"]}),
                    (not game["petitions"], "month" if not game["petitions"] else None,
                     10, {p["id"] for p in game["petitions"]}),
                    *([(False, None, 10 if path == "choice-error" else 11, set())]
                      if not game["petitions"] else []),
                ]
        # Choice completion no longer waits for the shared month action.
        client.portal.call(app.state.web.game.drain)
        if path == "choice-error":
            game = client.get("/state").json()["game"]
            assert game["failure"]["action"] == "month"
            assert game["date"]["month"] == 10
            before = audit(db)
            assert not [f for f in before["facts"] if f["kind"] == "month_final"]
            client.post("/actions", json={"action": "load", "save": save}).raise_for_status()
            assert state_updates(events) == []  # Selecting the current save is a no-op.
            client.post("/actions", json={"action": "retry"}).raise_for_status()
            assert [
                (state["game"]["running"], state["game"]["failure"], state["game"]["date"]["month"])
                for state in state_updates(events)
            ] == [(True, None, 10), (False, None, 11)]
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
                if f["kind"] == "changed" and f["detail"].get("origin_ref") == decree["id"] and "taels" in f["detail"]["actual"]
            ]
        before = audit(db)
        client.get("/state")
        client.get("/records")
        assert audit(db) == before
        assert state_updates(events) == []


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
        events = asyncio.Queue()
        client.app.state.web.listeners.add(events)
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
        assert [
            (state["game"]["running"],
             state["game"]["failure"] and state["game"]["failure"]["action"])
            for state in state_updates(events)
        ] == [
            (step in {"say", "month"}, None),
            (False, "translation" if "translation" in step else step),
            *([(True, None), (False, "translation")] if step == "month-translation" else []),
        ]
        if step == "translation-then-month":
            assert game["failure"]["action"] == "translation"
            steps[name] = working
            client.post("/actions", json={"action": "month"})
            state = client.get("/state").json()["game"]
            assert state["failure"] is None
            assert state["date"]["month"] == 11
            assert state["running"] is False
            assert [
                (update["game"]["running"], update["game"]["failure"],
                 update["game"]["date"]["month"], update["game"]["night"]["result"])
                for update in state_updates(events)
            ] == [(True, None, 10, None), (True, None, 10, "unhandled"),
                  (False, None, 11, "unhandled")]
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
        events = asyncio.Queue()
        client.app.state.web.listeners.add(events)
        assert client.get("/state").json()["settings"] == settings.model_dump()
        client.post("/actions", json={"action": "continue"})
        assert [
            (state["save"], state["game"]["running"], state["game"]["failure"]["action"])
            for state in state_updates(events)
        ] == [(save, False, game["failure"]["action"])]
        assert client.get("/state").json()["game"]["failure"] == game["failure"]
        client.post("/actions", json={"action": "retry"})
        if step == "translation":
            client.portal.call(client.app.state.web.game.drain)
        game = client.get("/state").json()["game"]
        assert game["failure"] is None
        assert [
            (state["game"]["running"], state["game"]["failure"], state["game"]["date"]["month"],
             state["game"]["night"] and state["game"]["night"]["result"])
            for state in state_updates(events)
        ] == [
            (step != "translation", None, 10, None),
            *([(True, None, 10, "unhandled")] if step == "month-translation" else []),
            (False, None, game["date"]["month"], game["night"] and game["night"]["result"]),
        ]
        if step == "say":
            assert len(game["night"]["turns"]) == 1
        elif step == "translation":
            assert game["date"]["month"] == 10
            assert game["night"]["result"] == "unhandled"
        else:
            assert game["date"]["month"] == 11
        assert game["running"] is False


class CountedModel(WrapperModel):
    """Counts requests at the model seam; the wrapped reply still runs."""

    def __init__(self, wrapped, name, invocations):
        super().__init__(wrapped)
        self.name = name
        self.invocations = invocations

    async def request(self, *args, **kwargs):
        self.invocations[self.name].append(args[0])
        return await super().request(*args, **kwargs)

    @asynccontextmanager
    async def request_stream(self, *args, **kwargs):
        self.invocations[self.name].append(args[0])
        async with super().request_stream(*args, **kwargs) as stream:
            yield stream


def counted(steps):
    invocations = defaultdict(list)
    for name, model in list(steps.items()):
        steps[name] = CountedModel(model, name, invocations)
    return invocations


@pytest.mark.parametrize("case,game_db", [
    (("say", "turn", False), "first_night"),
    (("say", "turn", True), "first_night"),
    (("translation", "unhandled", False), "spoken_night"),
    (("month", "advanced", False), "opening_db"),
    (("choose", "choice", False), "rejected_month"),
    (("month", "month_draft", False), "opening_db"),
    (("choose", "advanced", False), "rejected_month"),
], indirect=["game_db"])
def test_http_reopens_committed_action_gaps(game_db, case, audit, steps):
    """Freeze real commits, not a normally drained save or hand-written events."""
    action, product, dismiss = case
    preparing = product == "month_draft" or (action == "choose" and product == "advanced")
    if dismiss or preparing:
        steps["scene" if dismiss else "simulation" if product == "month_draft" else "urgent"] = TestModel(
            call_tools=["dismiss"] if dismiss else [],
            custom_output_text=(json.loads((RECORDED / "night_invalid.json").read_text())["cases"]["missing_fields"]["scene"]
                                if dismiss else (RECORDED / ("month_petition.txt" if product == "month_draft" else "sources_urgent.txt")).read_text()),
        )
    snapshots = {stage: game_db.parent / stage / game_db.name for stage in ("accepted", "product")}
    for path in snapshots.values():
        path.parent.mkdir()

    def committed(session):
        with closing(sqlite3.connect(game_db)) as source:
            kind, detail = source.execute(
                "SELECT kind, detail FROM facts WHERE kind IN ('interaction', ?) ORDER BY position DESC LIMIT 1", (product,),
            ).fetchone()
            detail = json.loads(detail)
            stage = "product" if kind == product else "accepted" if (
                kind == "interaction" and detail["action"] == action and detail["status"] != "failed"
            ) else None
            if stage is not None and not snapshots[stage].exists():
                with closing(sqlite3.connect(snapshots[stage])) as target:
                    source.backup(target)

    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        request = {"action": "dismiss" if action == "translation" else action}
        if action == "say":
            request["words"] = json.loads((RECORDED / "night_invalid.json").read_text())["emperor_words"]
        if action == "choose":
            request.update(petition=client.get("/state").json()["game"]["petitions"][0]["id"],
                           option=3 if product == "advanced" else 0)
        event.listen(Session, "after_commit", committed)
        try:
            client.post("/actions", json=request).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        finally:
            event.remove(Session, "after_commit", committed)
        assert client.get("/state").json()["game"]["failure"] is None
    model_invocations = counted(steps)
    for stage, path in snapshots.items():
        before = audit(path)
        assert len([f for f in before["facts"] if f["kind"] == product]) == int(stage == "product")
        model_invocations.clear()
        with TestClient(create_app(path.parent)) as client:
            client.post("/actions", json={"action": "load", "save": path.name}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            state = client.get("/state").json()["game"]
            assert (state["failure"], state["running"]) == (None, False)
            assert state["date"]["month"] == (11 if action in {"month", "choose"} and product != "month_draft" else 10)
            if action == "say":
                assert len(state["night"]["turns"]) == 1
                assert state["night"]["turns"][0]["emperor_words"] == request["words"]
            after = audit(path)
            assert len([f for f in after["facts"] if f["kind"] == product]) == 1
            assert all(f in after["facts"] for f in before["facts"])
            if dismiss:
                assert state["night"]["closed"] is True
                assert state["night"]["result"] == "unhandled"
                if stage == "product":
                    assert not model_invocations["scene"]
            elif stage == "product" and action != "choose" and product != "month_draft":
                assert not model_invocations
                assert after == before
            if action == "choose":
                assert [f["detail"]["option"] for f in after["facts"] if f["kind"] == "choice"] == [request["option"]]
        if preparing:
            assert (len([f for f in after["facts"] if f["kind"] == "forecast"]) if product == "month_draft"
                    else len(model_invocations["deliberation"])) == (len(state["petitions"][0]["options"]) if product == "month_draft" else 1)
            model_invocations.clear()
            with TestClient(create_app(path.parent)) as client:
                client.post("/actions", json={"action": "load", "save": path.name}).raise_for_status()
                client.portal.call(client.app.state.web.game.drain)
            assert not model_invocations
            assert audit(path) == after


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
    with reopening(game_db.parent) as reopen:
        client = reopen()
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
                client = reopen()
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
