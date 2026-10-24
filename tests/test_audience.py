"""Medium: audience behavior through the HTTP boundary and CLI ledger reads."""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    RetryPromptPart,
    ToolReturnPart,
)
from starlette.testclient import TestClient

from ming.middle.view import Officials
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("recording,steps", [("approved", "approved"), ("new_office", "new_office")], indirect=["steps"])
@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_nights_are_persistent_and_translate_only_after_dismissal(
    tmp_path: Path, game_db: Path, steps, audit, recording
) -> None:
    case = json.loads((RECORDED / f"night_{recording}.json").read_text())
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
        if recording == "new_office":
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.post("/actions", json={"action": "load", "save": save})
        night = client.get("/state").json()["game"]["night"]
        assert night["closed"] is True
        assert night["result"] == "translated"
        ledger = audit(tmp_path / save)
        orders = [e for e in ledger["entities"] if e["kind"] == "decree"]
        assert orders
        assert all(e["data"]["night_id"] == first["id"] for e in orders)
        assert all(e["data"].get("secret") is False for e in orders)
        assert all(e["data"]["turn"] == {"approved": 4, "new_office": 2}[recording] for e in orders)
        assert all(
            set(e["data"])
            == {"text", "origin", "people", "night_id", "secret", "turn", "endorsements", "interim"}
            for e in orders
        )
        ids = {e["key"]: e["id"] for e in ledger["entities"] if e["kind"] == "person"}
        for name in ("王承恩", "徐光启") if recording == "approved" else ("王承恩",):
            assert {
                f["detail"]["decree_id"]
                for f in ledger["facts"]
                if f["entity_id"] == ids[name] and f["kind"] == "decreed"
            } == {e["id"] for e in orders}
        if recording == "approved":
            assert not [f for f in ledger["facts"] if f["entity_id"] == ids["杨嗣昌"] and f["kind"] == "decreed"]
            assert all(e["data"]["endorsements"] == [] for e in orders)
        else:
            held = {(e["data"]["office"], e["data"]["territory"]): e["data"]["holders"] for e in ledger["entities"] if e["kind"] == "incumbency"}
            assert held[("户部右侍郎", "")] == ["杨嗣昌"]
            assert "杨嗣昌" in held[("户部郎中", "")]
            assert {e["data"]["interim"] for e in orders} == {True, False}
            assert [x["endorser"] for e in orders for x in e["data"]["endorsements"]] == ["御笔"]
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
    case = json.loads((RECORDED / "night_tools.json").read_text())
    received = []
    steps["scene"] = replaying(
        ModelMessagesTypeAdapter.validate_python(case["scene_responses"]), received
    )
    steps["NightDeclaration"] = replaying(case["replies"])
    with TestClient(create_app(tmp_path)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        for turn, hall in zip(case["turns"], (
            {"王承恩", "杨嗣昌", "王绍徽"},
            {"王承恩", "郭允厚", "王绍徽"},
            {"王承恩", "郭允厚"},
        ), strict=True):
            client.post("/actions", json={"action": "say", "words": turn["emperor_words"]})
            client.portal.call(client.app.state.web.game.drain)
            game = client.get("/state").json()["game"]
            assert game["failure"] is None
            assert set(game["night"]["hall"]) == hall
        assert isinstance(json.loads(received[0].parts[0].content[0])["imperial_prestige"], str)
        court = client.app.state.web.game.court
        assert court.nights()[0].result == "translated"
        first, second = sorted(
            court.entities("audit", kind="decree"), key=lambda d: d.data["turn"]
        )
        # Knowledge follows the hall at approval, before that turn's scene tools.
        for person, known in (
            ("杨嗣昌", {first.id}),
            ("王绍徽", {first.id, second.id}),
            ("郭允厚", {second.id}),
        ):
            assert {
                d.id for d in court.entities(Officials(people=[person]), kind="decree")
            } == known
    returned = {
        part.tool_call_id: (part.tool_name, part.model_response_object())
        for message in received
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    absent = next(value for name, value in returned.values() if name == "set_hall" and not value["ok"])
    assert {(f["name"], f["found"]) for f in absent["failures"]} == {("徐光启", True), ("张三", False)}
    assert set(absent["hall"]) == {"王承恩", "杨嗣昌", "王绍徽"}
    dossier = next(value for name, value in returned.values() if name == "read_person" and value["person"]["name"] == "徐光启")
    assert dossier["person"]["location"] == "南直隶 / 南京"
    assert dossier["person"]["status"] == "offstage"
    assert not {"loyalty", "ability", "integrity", "courage", "intrigue"}.intersection(dossier["person"])


@pytest.mark.usefixtures("backed_night")
@pytest.mark.parametrize("game_db", ["backed_night"], indirect=True)
@pytest.mark.parametrize("backed_night,recording,case", [
    ("endorsed", "endorsed", case) for case in ["approved", "held", "form", "source", "name", "person"]
] + [("double", "double", "approved")], indirect=["backed_night"])
def test_backing_follows_its_decree_and_signers(game_db, steps, audit, case, recording):
    recording = json.loads((RECORDED / f"night_{recording}.json").read_text())
    reply = json.loads(recording["replies"][-1])
    declared = reply["decrees"][0]["endorsements"]
    received = []
    if case in {"form", "source", "name", "person"}:
        endorsement = dict(declared[0])
        reply["decrees"][0]["endorsements"] = [endorsement, *declared[1:]]
        endorsement.update({"form": {"form": "力保"}, "source": {"source_chat_turn_id": "other-night"}, "name": {"endorser": "不存在的担名人"}, "person": {}}[case])
        reply["decrees"][0]["people"][0] = "不存在的领旨者" if case == "person" else reply["decrees"][0]["people"][0]
        if case == "form":
            del endorsement["endorser"]
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
            if case == "form":
                errors = retries[0].content
                assert any(
                    item["type"] == "missing"
                    and item["loc"] == ("decrees", 0, "endorsements", 0, "endorser")
                    and item["input"] == {
                        "form": "力保", "source_chat_turn_id": declared[0]["source_chat_turn_id"],
                    }
                    for item in errors
                )
                assert any(
                    item["type"] == "literal_error"
                    and item["loc"] == ("decrees", 0, "endorsements", 0, "form")
                    and item["input"] == "力保"
                    for item in errors
                )
            if case in {"name", "person"}:
                failure = json.loads(retries[0].content)
                assert failure["field"] == ("decrees[0].endorsements[0].endorser" if case == "name" else "decrees[0].people[0]")
                assert failure["current"] == ("不存在的担名人" if case == "name" else "不存在的领旨者")
                assert failure["expected"] == {"names_and_aliases": "person"}
                assert set(failure) == {"field", "current", "expected", "action"}
            assert len([f for f in audit(game_db)["facts"] if f["kind"] == "unhandled"]) == 1
            assert [f["detail"] for f in client.get("/records").json()["facts"] if f["kind"] == "unhandled"] == [{}]
            client.post("/actions", json={"action": "month"}).raise_for_status()
            state = client.get("/state").json()["game"]
            assert (state["face"], state["failure"], state["unhandled_monthly"]) == ("desk", None, [])
            client.post("/actions", json={"action": "open"}).raise_for_status()
            assert client.get("/state").json()["game"]["night"]["turns"] == []
            return
        assert state["night"]["result"] == "translated"
        ledger = audit(game_db)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        # The ledger lands exactly what the replayed declaration declared.
        assert decree["data"]["endorsements"] == declared
        assert json.loads(received[-1].parts[0].content)["context"]["decree"]["data"]["endorsements"] == decree["data"]["endorsements"]
        for endorsement in (e for e in declared if e["endorser"] != "御笔"):
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
        assert not [f for f in ledger["facts"] if f["kind"] == "changed" and f["detail"]["origin_ref"] == decree["id"] and "imperial_prestige" in f["detail"]["actual"]]
        assert not [f for f in ledger["facts"] if f["kind"] == "interim"]
        assert not [f for f in ledger["facts"] if f["kind"] == "changed" and "satisfaction" in f["detail"].get("actual", {})]
        signers = [e for e in declared if e["endorser"] != "御笔"]
        dossiers = []
        dossier_recording = json.loads((RECORDED / "endorsed_dossier.json").read_text())
        steps["scene"] = replaying(
            ModelMessagesTypeAdapter.validate_python(dossier_recording["messages"]), dossiers
        )
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": dossier_recording["words"]}).raise_for_status()
        assert client.get("/state").json()["game"]["failure"] is None
        returned = {
            p.model_response_object()["person"]["name"]: p.model_response_object()
            for m in dossiers for p in m.parts
            if isinstance(p, ToolReturnPart) and p.tool_name == "read_person"
        }
        for signer in signers:
            events = returned[signer["endorser"]]["events"]
            assert [
                (e["decree_id"], e["endorser"], e["form"], e["decree"]["endorsements"])
                for e in events if e["kind"] == "endorsed"
            ] == [(decree["id"], signer["endorser"], signer["form"], declared)]


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
