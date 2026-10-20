"""Deterministic HTTP acceptance; models replay the existing live recordings."""

import json
from pathlib import Path

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


def test_settings_survive_reopening_and_failed_scene_retries_in_place(
    tmp_path: Path,
) -> None:
    case = json.loads(
        (Path(__file__).parent / "recorded/night_invalid.json").read_text()
    )

    def models(settings: Settings):
        return (
            replaying([RuntimeError("external backend unavailable")])
            if settings.api_key == "broken"
            else replaying([case["cases"]["missing_fields"]["scene"]])
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
        client.post("/actions", json={"action": "open"})
        client.post("/actions", json={"action": "say", "words": case["emperor_words"]})
        game = client.get("/state").json()["game"]
        assert game["failure"]["action"] == "say"
        assert game["failure"]["payload"]["type"] == "RuntimeError"
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
        assert client.get("/state").json()["game"]["failure"]["action"] == "say"
        settings.api_key = "fixed"
        client.post(
            "/actions", json={"action": "settings", "settings": settings.model_dump()}
        )
        client.post("/actions", json={"action": "retry"})
        game = client.get("/state").json()["game"]
        assert game["failure"] is None
        assert len(game["night"]["turns"]) == 1
        assert game["running"] is False
