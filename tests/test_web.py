"""Medium: HTTP/CLI entry acceptance with per-step recorded model overrides."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import Settings, create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


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
        records = client.get("/records").json()
        assert {e["kind"] for e in records["entities"]} == {
            "person",
            "calendar",
            "gazette",
        }
        assert all(
            set(e["data"]) <= {"name", "office", "location", "status"}
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
            if path in {"petition", "multiple-petitions", "choice-error"}
            else "first_night",
        )
        for path in (
            "petition",
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
    money = (RECORDED / "month_money_300000.txt").read_text()
    received = {name: [] for name in ("deliberation", "simulation", "gazette")}
    if path in {"petition", "multiple-petitions", "choice-error"}:
        case = (
            RECORDED
            / (
                "month_multiple_petitions.txt"
                if path == "multiple-petitions"
                else "month_petition.txt"
            )
        ).read_text()
        steps["simulation"] = replaying(
            [
                case,
                *(
                    [
                        RuntimeError("forecast unavailable")
                        if path == "choice-error"
                        else (RECORDED / "simulation.txt").read_text()
                    ]
                    * sum(len(p["options"]) for p in json.loads(case)["petitions"])
                ),
            ]
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
                        else ModelResponse(parts=[ToolCallPart("read_records", {})])
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
                assert (
                    client.post("/actions", json={"action": "retry"}).status_code == 204
                )
                assert client.portal is not None
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
            } == (
                {decree["data"]["night_id"]}
                if path not in {"precompute-error", "precompute-structure"}
                else set()
            )
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
        if path in {"petition", "multiple-petitions", "choice-error"}:
            client.portal.call(app.state.web.game.drain)
            assert (game["date"]["month"], game["face"], game["running"]) == (
                10,
                "month",
                False,
            )
            before = audit(db)
            client.get("/state")
            client.get("/records")
            assert audit(db) == before
            for petition in game["petitions"][:]:
                choice = {"action": "choose", "petition": petition["id"], "option": 0}
                assert (
                    client.post("/actions", json={**choice, "option": -1}).status_code
                    == 400
                )
                if path == "choice-error":
                    steps["simulation"] = replaying(
                        [
                            RuntimeError("continuation unavailable"),
                            (RECORDED / "simulation.txt").read_text(),
                        ]
                    )
                assert client.post("/actions", json=choice).status_code == 204
                if path == "choice-error":
                    failure = client.get("/state").json()["game"]["failure"]
                    assert failure["action"] == "choose"
                    assert failure["payload"]["petition"] == choice["petition"]
                    assert failure["payload"]["option"] == 0
                    assert (
                        client.post("/actions", json={"action": "retry"}).status_code
                        == 204
                    )
                assert client.post("/actions", json=choice).status_code == 400
                game["petitions"].remove(petition)
                assert {
                    p["id"] for p in client.get("/state").json()["game"]["petitions"]
                } == {p["id"] for p in game["petitions"]}
        # Choice completion no longer waits for the shared month action.
        client.portal.call(app.state.web.game.drain)
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
        if path == "decree":
            decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
            assert {
                f["kind"] for f in ledger["facts"] if f["entity_id"] == decree["id"]
            } >= {
                "deliberation",
                "declaration",
                "landed",
            }
            assert [
                f
                for f in ledger["facts"]
                if f["kind"] == "changed" and f["detail"]["origin_ref"] == decree["id"]
            ]
            materials = {
                name: [
                    part.model_response_object()
                    for m in messages
                    for part in m.parts
                    if isinstance(part, ToolReturnPart)
                ]
                for name, messages in received.items()
            }
            assert all(materials.values())
            assert all(
                not [e for e in data["entities"] if e["kind"] == "account"]
                for name in ("deliberation", "gazette")
                for data in materials[name]
            )
            assert {
                e["key"]: e["data"]["taels"]
                for e in materials["simulation"][0]["entities"]
                if e["kind"] == "account"
            } == {"国库": 3200000, "内库": 4400000}
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
    settings = Settings(backend="claude-cli")
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
            and json.loads(messages[0].parts[0].content)["context"]["faction"]["key"]
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
                assert len([f for f in before["facts"] if f["kind"] == "gazette"]) == 1
                assert len(
                    [f for f in before["facts"] if f["kind"] == "impeachment"]
                ) == (6 if name == "impeachment" else 7)
            assert state["date"]["month"] == 10
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
        assert len([f for f in ledger["facts"] if f["kind"] == "impeachment"]) == 7
        if source:
            assert all(
                f in ledger["facts"]
                for f in before["facts"]
                if f["kind"] != "interaction"
            )


@pytest.mark.parametrize("model", ["", "sonnet"])
@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_cli_backend_leaves_the_default_model_to_the_host(
    tmp_path: Path, game_db: Path, model: str, monkeypatch
) -> None:
    calls = []
    reply = json.loads((RECORDED / "night_invalid.json").read_text())["cases"][
        "missing_fields"
    ]["reply"]

    async def spawn(*args, **kwargs):
        calls.append(args)
        output = asyncio.StreamReader()
        for event in [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": reply},
                },
            },
            {"type": "result", "is_error": False},
        ]:
            output.feed_data(json.dumps(event).encode() + b"\n")
        output.feed_eof()
        return SimpleNamespace(
            stdout=output, returncode=0, communicate=AsyncMock(return_value=(b"", b""))
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with TestClient(create_app(tmp_path)) as client:
        client.post(
            "/actions",
            json={
                "action": "settings",
                "settings": {"backend": "claude-cli", "model": model},
            },
        )
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        client.post("/actions", json={"action": "dismiss"})
        client.post("/actions", json={"action": "load", "save": save})
        assert client.get("/state").json()["game"]["failure"] is None
    assert calls
    for args in calls:
        assert args[0] == "claude"
        if model:
            assert args[args.index("--model") + 1] == model
        else:
            assert "--model" not in args
