"""Medium: audience behavior through the HTTP boundary and CLI ledger reads."""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
def test_nights_are_persistent_and_translate_only_after_dismissal(
    tmp_path: Path, steps, audit
) -> None:
    case = json.loads((RECORDED / "night_approved.json").read_text())
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        client.post("/actions", json={"action": "open"})
        client.post("/actions", json={"action": "say", "words": case["words"][0]})
        first = client.get("/state").json()["game"]["night"]
        assert first["closed"] is False
        assert first["result"] is None
        assert not [
            e for e in audit(tmp_path / save)["entities"] if e["kind"] == "decree"
        ]
    with TestClient(create_app(tmp_path)) as client:
        client.post("/actions", json={"action": "continue"})
        assert client.get("/state").json()["game"]["night"] == first
        for words in case["words"][1:]:
            client.post("/actions", json={"action": "say", "words": words})
        client.post("/actions", json={"action": "load", "save": save})
        night = client.get("/state").json()["game"]["night"]
        assert night["closed"] is True
        assert night["result"] == "translated"
        ledger = audit(tmp_path / save)
        orders = [e for e in ledger["entities"] if e["kind"] == "decree"]
        assert orders
        assert all(e["data"]["night_id"] == first["id"] for e in orders)
        assert all(
            set(e["data"]) == {"text", "origin", "people", "night_id"} for e in orders
        )
        ids = {e["key"]: e["id"] for e in ledger["entities"] if e["kind"] == "person"}
        for name in ("王承恩", "徐光启"):
            assert {
                f["detail"]["decree_id"]
                for f in ledger["facts"]
                if f["entity_id"] == ids[name] and f["kind"] == "decreed"
            } == {e["id"] for e in orders}
        assert not [
            f
            for f in ledger["facts"]
            if f["entity_id"] == ids["杨嗣昌"] and f["kind"] == "decreed"
        ]
        client.post("/actions", json={"action": "open"})
        second = client.get("/state").json()["game"]["night"]
        assert first["id"] != second["id"]
        assert second["turns"] == []
    assert audit(tmp_path / save) == audit(tmp_path / save, True)


def test_scene_tools_use_physical_location_not_office_and_project_dossiers(
    tmp_path: Path, steps
) -> None:
    case = json.loads((RECORDED / "night_invalid.json").read_text())
    received = []
    steps["scene"] = replaying(
        [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        "read_person", {"name": "徐光启"}, tool_call_id="person"
                    ),
                    ToolCallPart(
                        "set_hall",
                        {"add": ["杨嗣昌", "韩爌", "李待问"], "remove": []},
                        tool_call_id="present",
                    ),
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        "set_hall",
                        {"add": ["徐光启", "张三"], "remove": []},
                        tool_call_id="absent",
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        "set_hall",
                        {"add": [], "remove": ["韩爌", "张三"]},
                        tool_call_id="leave",
                    )
                ]
            ),
            case["cases"]["missing_fields"]["scene"],
        ],
        received,
    )
    with TestClient(create_app(tmp_path)) as client:
        client.post("/actions", json={"action": "new"})
        client.post("/actions", json={"action": "open"})
        client.post("/actions", json={"action": "say", "words": case["emperor_words"]})
        game = client.get("/state").json()["game"]
        assert game["failure"] is None
        assert set(game["night"]["hall"]) == {"王承恩", "杨嗣昌", "李待问"}
    returned = {
        part.tool_call_id: part.model_response_object()
        for message in received
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    assert returned["present"]["ok"] is True
    assert returned["absent"]["ok"] is False
    assert returned["leave"]["ok"] is True
    assert returned["person"]["person"]["location"] == "南直隶 / 南京"
    assert returned["person"]["person"]["status"] == "offstage"
    assert not {"loyalty", "ability", "integrity", "courage", "intrigue"}.intersection(
        returned["person"]["person"]
    )


def test_failed_night_translation_is_terminal_and_reaches_following_nights(
    tmp_path: Path, steps, audit
) -> None:
    recording = json.loads((RECORDED / "night_invalid.json").read_text())
    cases = recording["cases"]
    steps["scene"] = replaying([case["scene"] for case in cases.values()])
    steps["NightDeclaration"] = replaying(
        [case["reply"] for case in cases.values() for _ in range(2)]
    )
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        before = audit(tmp_path / save)["entities"]
        nights = []
        for _ in cases:
            assert client.post("/actions", json={"action": "open"}).status_code == 200
            assert (
                client.post(
                    "/actions",
                    json={"action": "say", "words": recording["emperor_words"]},
                ).status_code
                == 204
            )
            state = client.get("/state").json()["game"]
            assert state["face"] == "audience"
            assert len(state["night"]["turns"]) == 1
            assert state["failure"] is None
            assert (
                client.post("/actions", json={"action": "dismiss"}).status_code == 200
            )
            client.post("/actions", json={"action": "load", "save": save})
            state = client.get("/state").json()["game"]
            assert state["face"] == "desk"
            assert state["night"]["result"] == "unhandled"
            assert state["failure"] is None
            nights.append(state["night"]["id"])
            assert [
                e for e in audit(tmp_path / save)["entities"] if e["kind"] != "night"
            ] == before
        assert {
            f["entity_id"]
            for f in client.get("/records").json()["facts"]
            if f["kind"] == "unhandled"
        } == set(nights)
        assert all(
            not f["detail"]
            for f in client.get("/records").json()["facts"]
            if f["kind"] == "unhandled"
        )
        assert client.post("/actions", json={"action": "open"}).status_code == 200
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/state").json()["game"] is None
        client.post("/actions", json={"action": "continue"})
        state = client.get("/state").json()["game"]
        assert state["face"] == "audience"
        assert state["night"]["turns"] == []
        assert client.post("/actions", json={"action": "month"}).status_code == 409
    assert audit(tmp_path / save) == audit(tmp_path / save, True)
