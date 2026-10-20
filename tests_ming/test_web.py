"""Deterministic HTTP acceptance; models replay the existing live recordings."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import Settings, create_app
from tests_ming.test_court import replaying


def test_menu_creates_distinct_games_and_opens_only_existing_saves(
    tmp_path: Path,
) -> None:
    app = create_app(tmp_path, model_factory=lambda _settings: TestModel())
    with TestClient(app) as client:
        menu = client.get("/state").json()
        assert menu["saves"] == []
        assert menu["save"] is None
        assert menu["game"] is None
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
    with TestClient(
        create_app(tmp_path, model_factory=lambda _settings: TestModel())
    ) as client:
        menu = client.get("/state").json()
        assert set(menu["saves"]) == {first, second}
        assert menu["save"] is None
        assert menu["game"] is None
        assert (
            client.post("/actions", json={"action": "continue"}).json()["save"]
            == second
        )


@pytest.mark.parametrize("path", ["complete", "petition", "gazette-error"])
def test_http_month_dispatches_choices_streams_and_retries_missing_step(
    tmp_path: Path,
    path: str,
) -> None:
    recorded = Path(__file__).parent / "recorded"
    empty = (recorded / "month_empty.txt").read_text()
    petition = (recorded / "month_petition.txt").read_text()
    money = (recorded / "month_money_300000.txt").read_text()
    gazette = json.loads((recorded / "night_invalid.json").read_text())["cases"][
        "missing_fields"
    ]["scene"]
    replies = (
        [petition, petition, money, money, gazette]
        if path == "petition"
        else [
            empty,
            empty,
            *([RuntimeError("gazette unavailable")] if path == "gazette-error" else []),
            gazette,
        ]
    )
    with TestClient(
        create_app(tmp_path, model_factory=lambda _: replaying(replies))
    ) as client:
        client.post("/actions", json={"action": "new"})
        before = client.get("/records").json()["entities"]
        assert (
            client.post(
                "/actions", json={"action": "choose", "petition": str(uuid4())}
            ).status_code
            == 400
        )
        response = client.post("/actions", json={"action": "month"})
        assert response.status_code == 200
        transitions: list[dict[str, Any] | str] = [
            json.loads(line[6:])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
        assert any(
            isinstance(value, dict)
            and value.get("game", {}).get("face") == "month"
            and value["game"]["running"]
            for value in transitions
        )
        game = client.get("/state").json()["game"]
        if path == "petition":
            assert game["date"]["month"] == 10
            choice = {
                "action": "choose",
                "petition": game["petitions"][0]["id"],
                "option": 0,
            }
            assert (
                client.post("/actions", json={**choice, "option": -1}).status_code
                == 400
            )
            response = client.post("/actions", json=choice)
            assert response.status_code == 200
            assert client.post("/actions", json=choice).status_code == 400
        elif path == "gazette-error":
            assert game["failure"]["action"] == "month"
            assert game["failure"]["payload"]["type"] == "RuntimeError"
            assert game["date"]["month"] == 10
            assert client.get("/records").json()["entities"] == before
            response = client.post("/actions", json={"action": "retry"})
            assert response.status_code == 200
        game = client.get("/state").json()["game"]
        assert game["date"]["month"] == 11
        assert game["face"] == "desk"
        assert game["failure"] is None
        assert game["petitions"] == []
        assert "event: gazette" in response.text.splitlines()
        assert (
            len(
                [
                    f
                    for f in client.get("/records").json()["facts"]
                    if f["kind"] == "gazette"
                ]
            )
            == 1
        )


def test_http_audience_records_unhandled_night_and_resumes_after_reopening(
    tmp_path: Path,
) -> None:
    case = json.loads(
        (Path(__file__).parent / "recorded/night_invalid.json").read_text()
    )
    sample = case["cases"]["missing_fields"]

    def models(_settings: Settings):
        return replaying([sample["scene"], sample["reply"], sample["reply"]])

    with TestClient(create_app(tmp_path, model_factory=models)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        assert client.post("/actions", json={"action": "open"}).status_code == 200
        response = client.post(
            "/actions", json={"action": "say", "words": case["emperor_words"]}
        )
        assert response.status_code == 200
        state = client.get("/state").json()["game"]
        assert state["face"] == "audience"
        assert len(state["night"]["turns"]) == 1
        assert state["failure"] is None
        assert client.post("/actions", json={"action": "dismiss"}).status_code == 200
        client.post("/actions", json={"action": "load", "save": save})
        state = client.get("/state").json()["game"]
        assert state["face"] == "desk"
        assert state["night"]["result"] == "unhandled"
        assert state["failure"] is None
        assert client.post("/actions", json={"action": "open"}).status_code == 200
    with TestClient(
        create_app(tmp_path, model_factory=lambda _settings: TestModel())
    ) as client:
        assert client.get("/state").json()["game"] is None
        client.post("/actions", json={"action": "continue"})
        state = client.get("/state").json()["game"]
        assert state["face"] == "audience"
        assert state["night"]["turns"] == []
        assert client.post("/actions", json={"action": "month"}).status_code == 409


@pytest.mark.parametrize("step", ["say", "translation", "month-translation", "month"])
def test_settings_survive_reopening_and_failed_scene_retries_in_place(
    tmp_path: Path,
    step: str,
) -> None:
    case = json.loads(
        (Path(__file__).parent / "recorded/night_invalid.json").read_text()
    )

    sample = case["cases"]["missing_fields"]
    empty = (Path(__file__).parent / "recorded/month_empty.txt").read_text()

    def models(settings: Settings):
        if settings.api_key == "broken":
            return replaying(
                [
                    *(
                        [sample["scene"]]
                        if step in {"translation", "month-translation"}
                        else []
                    ),
                    RuntimeError("external backend unavailable"),
                    RuntimeError("external backend unavailable"),
                ]
            )
        return replaying(
            [sample["scene"]]
            if step == "say"
            else [sample["reply"], sample["reply"], empty, empty, sample["scene"]]
            if step in {"translation", "month-translation"}
            else [empty, empty, sample["scene"]]
        )

    settings = Settings(api_key="broken")
    with TestClient(create_app(tmp_path, model_factory=models)) as client:
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
        client.post("/actions", json={"action": "new"})
        if step == "month":
            client.post("/actions", json={"action": "month"})
        else:
            client.post("/actions", json={"action": "open"})
            client.post(
                "/actions", json={"action": "say", "words": case["emperor_words"]}
            )
            if step != "say":
                client.post("/actions", json={"action": "dismiss"})
                # Selecting waits for the live worker, without fabricating a failure.
                save = client.get("/state").json()["save"]
                client.post("/actions", json={"action": "load", "save": save})
                if step == "month-translation":
                    client.post("/actions", json={"action": "month"})
        game = client.get("/state").json()["game"]
        failed_action = "translation" if step.endswith("translation") else step
        assert game["failure"]["action"] == failed_action
        assert game["failure"]["payload"]["type"] == "RuntimeError"
        assert game["date"]["month"] == 10
        if step == "say":
            assert game["night"]["turns"] == []
        assert not [
            f
            for f in client.get("/records").json()["facts"]
            if f["kind"] == "unhandled"
        ]
    with TestClient(create_app(tmp_path, model_factory=models)) as client:
        menu = client.get("/state").json()
        assert menu["settings"] == settings.model_dump()
        assert menu["game"] is None
        client.post("/actions", json={"action": "continue"})
        assert client.get("/state").json()["game"]["failure"] == game["failure"]
        settings.api_key = "fixed"
        client.post(
            "/actions", json={"action": "settings", "settings": settings.model_dump()}
        )
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
