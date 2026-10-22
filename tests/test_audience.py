"""Medium: audience behavior through the HTTP boundary and CLI ledger reads."""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_nights_are_persistent_and_translate_only_after_dismissal(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    case = json.loads((RECORDED / "night_approved.json").read_text())
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
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
            set(e["data"]) == {"text", "origin", "people", "night_id", "endorsements", "interim"} for e in orders
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
        assert all(e["data"]["endorsements"] == [] for e in orders)
        assert client.get("/state").json()["game"]["petitions"] == []
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        assert {f["entity_id"] for f in audit(tmp_path / save)["facts"] if f["kind"] == "landed" and f["entity_id"] in {e["id"] for e in orders}} == {e["id"] for e in orders}
        client.post("/actions", json={"action": "open"})
        second = client.get("/state").json()["game"]["night"]
        assert first["id"] != second["id"]
        assert second["turns"] == []


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_scene_tools_use_physical_location_not_office_and_project_dossiers(
    tmp_path: Path, game_db: Path, steps
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
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "say", "words": case["emperor_words"]})
        game = client.get("/state").json()["game"]
        assert json.loads(received[0].parts[0].content[0])["imperial_prestige"] == "威福旁落"
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


@pytest.mark.usefixtures("backed_night")
@pytest.mark.parametrize("game_db", ["backed_night"], indirect=True)
@pytest.mark.parametrize("backed_night,recording,case", [
    ("endorsed", "endorsed", case) for case in ["approved", "held", "name", "form", "source"]
] + [("double", "double", "approved")], indirect=["backed_night"])
def test_backing_follows_its_decree_and_signers(game_db, steps, audit, case, recording):
    multiple = recording == "double"
    recording = json.loads((RECORDED / f"night_{recording}.json").read_text())
    reply = json.loads(recording["replies"][-1])
    received = []
    if case in {"name", "form", "source"}:
        endorsement = reply["decrees"][0]["endorsements"][0]
        if case == "form":
            del endorsement["endorser"]
            endorsement["form"] = "力保"
        else:
            endorsement[{
                "name": "endorser", "source": "source_chat_turn_id",
            }[case]] = {"name": "毕尚书", "source": "other-night"}[case]
        steps["NightDeclaration"] = replaying([json.dumps(reply, ensure_ascii=False)] * 2, received)
    else:
        steps["NightDeclaration"] = replaying(recording["replies"])
    steps["deliberation"] = replaying(
        [(RECORDED / ("deliberation_rejected.txt" if case == "held" else "deliberation.txt")).read_text(),
         (RECORDED / "deliberation.txt").read_text()], received,
    )
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        if case not in {"approved", "held"}:
            assert state["night"]["result"] == "unhandled"
            retries = [p for m in received for p in m.parts if isinstance(p, RetryPromptPart)]
            assert len(retries) == 1
            if case == "name":
                reply = json.loads(retries[0].content)
                assert reply["field"] == "decrees[0].endorsements[0].endorser"
                assert reply["current"] == "毕尚书"
                assert "毕自严" in reply["expected"]
            elif case == "form":
                errors = retries[0].content
                assert any(
                    item["type"] == "missing"
                    and item["loc"] == ("decrees", 0, "endorsements", 0, "endorser")
                    and item["input"] == {
                        "form": "力保", "source_chat_turn_id": "north-star-backing",
                    }
                    for item in errors
                )
                assert any(
                    item["type"] == "literal_error"
                    and item["loc"] == ("decrees", 0, "endorsements", 0, "form")
                    and item["input"] == "力保"
                    for item in errors
                )
            assert len([f for f in audit(game_db)["facts"] if f["kind"] == "unhandled"]) == 1
            assert [f["detail"] for f in client.get("/records").json()["facts"] if f["kind"] == "unhandled"] == [{}]
            client.post("/actions", json={"action": "month"}).raise_for_status()
            client.post("/actions", json={"action": "open"}).raise_for_status()
            assert client.get("/state").json()["game"]["night"]["turns"] == []
            return
        assert state["night"]["result"] == "translated"
        ledger = audit(game_db)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        expected = [{"endorser": "毕自严", "form": "当面站台", "source_chat_turn_id": "north-star-backing"}]
        if multiple:
            expected += [
                {"endorser": "王绍徽", "form": "会签", "source_chat_turn_id": "north-star-cosign"},
                {"endorser": "御笔", "form": "御笔手敕", "source_chat_turn_id": "north-star-cosign"},
            ]
        assert decree["data"]["endorsements"] == expected
        assert "毕自严" not in decree["data"]["people"]
        assert json.loads(received[-1].parts[0].content)["context"]["decree"]["data"]["endorsements"] == decree["data"]["endorsements"]
        for endorsement in (e for e in expected if e["endorser"] != "御笔"):
            assert [f["detail"]["decree_id"] for f in ledger["facts"]
                    if f["kind"] == "endorsed" and f["entity_id"] == next(e["id"] for e in ledger["entities"] if e["key"] == endorsement["endorser"])] == [decree["id"]]
        if case == "held":
            assert state["petitions"][0]["options"] == ["强颁", "收回", "留中"]
            client.post("/actions", json={"action": "choose", "petition": state["petitions"][0]["id"], "option": 2}).raise_for_status()
        else:
            assert state["petitions"] == []
        client.post("/actions", json={"action": "month"}).raise_for_status()
        if case == "held":
            client.post("/actions", json={"action": "load", "save": game_db.name})
            client.post("/actions", json={"action": "month"}).raise_for_status()
            assert json.loads(received[-1].parts[0].content)["context"]["decree"]["data"]["endorsements"] == decree["data"]["endorsements"]
        ledger = audit(game_db)
        assert next(e for e in ledger["entities"] if e["kind"] == "world")["data"]["imperial_prestige"] == 20
        assert not [f for f in ledger["facts"] if f["kind"] == "interim"]
        assert not [f for f in ledger["facts"] if f["kind"] == "changed" and "satisfaction" in f["detail"].get("actual", {})]


def test_failed_night_translation_is_terminal_and_reaches_following_nights(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    recording = json.loads((RECORDED / "night_invalid.json").read_text())
    cases = recording["cases"]
    steps["scene"] = replaying([case["scene"] for case in cases.values()])
    steps["NightDeclaration"] = replaying(
        [case["reply"] for case in cases.values() for _ in range(2)]
    )
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
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
