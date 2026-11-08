"""Medium: audience behavior through the HTTP boundary and CLI ledger reads."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelResponse,
    ToolCallPart,
    RetryPromptPart,
    ToolReturnPart,
)
from starlette.testclient import TestClient

from ming.middle.view import Officials
from ming.web import create_app
from tests.test_court import record_results, replaying
from tests.test_secrets import _declaration_prompt
from tests.test_web import state_updates

RECORDED = Path(__file__).parent / "recorded"
HALL_RESULT = frozenset({"ok", "hall", "failures"})
ATTACH_QUERY = frozenset({"kind", "key"})


def attached_records(value: dict) -> dict:
    """Person page carried on set_hall, without hall wrapper or continuation query."""
    return {key: value[key] for key in value if key not in HALL_RESULT | ATTACH_QUERY}


def tool_returns(received: list) -> dict:
    return {
        part.tool_call_id: (part.tool_name, part.model_response_object())
        for message in received
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }


def assert_set_hall_page(value: dict, court, names: list[str]) -> None:
    assert value["ok"] is True
    assert (value["kind"], value["key"]) == ("person", names)
    expected = court.read.query(Officials(people=value["hall"]), "person", names)
    assert attached_records(value) == expected
    if value.get("entities"):
        assert {"dossier", "seed_guilt"} <= value["entities"][0]["data"].keys()


def scene_tool_script(case: dict) -> list:
    return [
        ModelResponse(parts=[ToolCallPart("read_records", {"kind": "office", "key": case["offices"]}, tool_call_id="offices")]),
        ModelResponse(parts=[ToolCallPart("read_records", {"kind": "person", "key": "王体乾"}, tool_call_id="before")]),
        ModelResponse(parts=[ToolCallPart("set_hall", {"add": ["王体乾"], "remove": []}, tool_call_id="admit")]),
        # Mixed reject while 王体乾 is already in the hall must not attach his dossier.
        ModelResponse(parts=[ToolCallPart("set_hall", {"add": ["王体乾", "张三"], "remove": []}, tool_call_id="mixed")]),
        ModelResponse(parts=[ToolCallPart("read_records", {"kind": "person", "key": "王体乾"}, tool_call_id="after")]),
        ModelResponse(parts=[ToolCallPart("set_hall", {"add": ["王体乾"], "remove": []}, tool_call_id="again")]),
        ModelResponse(parts=[ToolCallPart("set_hall", {"add": [], "remove": ["王体乾"]}, tool_call_id="remove")]),
        ModelResponse(parts=[ToolCallPart("set_hall", {"add": ["王体乾"], "remove": ["王体乾"]}, tool_call_id="inout")]),
        *ModelMessagesTypeAdapter.validate_python(case["scene_responses"]),
    ]


def assert_scene_tool_returns(received, events, court, continuations, multi: tuple) -> None:
    names, multi_id = multi
    returned = tool_returns(received)
    # Rejected and unchanged successful set_hall calls have no visible transition.
    assert [event["data"] for event in (events.get_nowait() for _ in range(events.qsize()))
            if event["event"] == "hall"] == [
        ["王承恩", "王体乾"],
        ["王承恩"],
        ["王承恩", "杨嗣昌", "王绍徽"],
        ["王承恩", "王绍徽", "郭允厚"],
        ["王承恩", "郭允厚"],
    ]
    assert [result["status"] for result in returned["offices"][1]["offices"]] == ["occupied", "occupied"]
    assert [result["appointments"][0]["holders"] for result in returned["offices"][1]["offices"]] == [["黄立极"], ["郭允厚"]]
    before, after = (returned[key][1]["entities"][0] for key in ("before", "after"))
    assert before["key"] == after["key"] == "王体乾"
    for field in ("name", "location", "appointments"):
        assert before["data"][field] == after["data"][field]
    assert not {"dossier", "seed_guilt"}.intersection(before["data"])
    assert {"dossier", "seed_guilt"} <= after["data"].keys()

    for call_id, admitted in (("admit", ["王体乾"]), ("again", ["王体乾"])):
        assert_set_hall_page(returned[call_id][1], court, admitted)
    assert returned["remove"][1]["ok"] is True
    assert attached_records(returned["remove"][1]) == {}
    assert returned["inout"][1]["ok"] is True
    assert "王体乾" not in returned["inout"][1]["hall"]
    assert attached_records(returned["inout"][1]) == {}

    mixed = returned["mixed"][1]
    assert mixed["ok"] is False
    assert {(f["name"], f["found"]) for f in mixed["failures"]} == {("张三", False)}
    assert "王体乾" in mixed["hall"]
    assert attached_records(mixed) == {}

    absent = next(value for name, value in returned.values()
                  if name == "set_hall" and not value["ok"] and value is not mixed)
    assert {(f["name"], f["found"]) for f in absent["failures"]} == {("徐光启", True), ("张三", False)}
    assert set(absent["hall"]) == {"王承恩", "杨嗣昌", "王绍徽"}
    assert attached_records(absent) == {}
    xuguangqi = next(value["entities"][0]["data"] for name, value in returned.values()
                     if name == "read_records" and value.get("entities") and value["entities"][0]["key"] == "徐光启")
    assert xuguangqi["location"] == "南直隶 / 南京"
    assert xuguangqi["status"] == "offstage"
    assert not {"loyalty", "ability", "integrity", "courage", "intrigue"}.intersection(xuguangqi)

    # Multi-admit first page carries continuation query; pages stay within budget and assemble fully.
    first_page = returned[multi_id][1]
    assert first_page["ok"] is True
    assert (first_page["kind"], first_page["key"]) == ("person", names)
    assert "next" in first_page
    pages = {
        call_id: obj for call_id, (_, obj) in returned.items()
        if continuations.get(call_id, call_id) == multi_id or call_id == multi_id
    }
    assert all(len(json.dumps(page, ensure_ascii=False).encode()) <= 20_000 for page in pages.values())
    queries = {
        part.tool_call_id: part.args_as_dict()
        for message in received for part in message.parts if isinstance(part, ToolCallPart)
    }
    assembled = record_results(queries, {i: o for i, (_, o) in returned.items()}, continuations)[multi_id]
    assert "next" not in assembled
    complete = court.read.read_records(Officials(people=assembled["hall"]), "person", names)
    assert {e["key"]: e for e in assembled["entities"]} == {e["key"]: e for e in complete["entities"]}


@pytest.mark.parametrize("recording,steps", [("approved", "approved"), ("new_office", "new_office")], indirect=["steps"])
@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_nights_are_persistent_and_translate_only_after_dismissal(
    tmp_path: Path, game_db: Path, steps, audit, recording
) -> None:
    case = json.loads((RECORDED / f"night_{recording}.json").read_text())
    with TestClient(create_app(tmp_path)) as client:
        events = asyncio.Queue()
        client.app.state.web.listeners.add(events)
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        assert [state["game"]["face"] for state in state_updates(events)] == ["audience"]
        client.post("/actions", json={"action": "say", "words": case["words"][0]})
        assert [
            (state["game"]["running"], len(state["game"]["night"]["turns"]))
            for state in state_updates(events)
        ] == [(True, 0), (False, 1)]
        first = client.get("/state").json()["game"]["night"]
        assert first["closed"] is False
        assert first["result"] is None
        assert not [
            e for e in audit(tmp_path / save)["entities"] if e["kind"] == "decree"
        ]
    with TestClient(create_app(tmp_path)) as client:
        events = asyncio.Queue()
        client.app.state.web.listeners.add(events)
        client.post("/actions", json={"action": "continue"})
        assert [(state["game"]["night"]["id"], len(state["game"]["night"]["turns"]))
                for state in state_updates(events)] == [(first["id"], 1)]
        assert client.get("/state").json()["game"]["night"] == first
        for index, words in enumerate(case["words"][1:], start=1):
            client.post("/actions", json={"action": "say", "words": words})
            client.portal.call(client.app.state.web.game.drain)
            assert [
                (state["game"]["running"], len(state["game"]["night"]["turns"]),
                 state["game"]["night"]["result"])
                for state in state_updates(events)
            ] == [
                (True, index, None), (False, index + 1, None),
                *([(False, index + 1, "translated")]
                  if recording == "approved" and index == len(case["words"]) - 1 else []),
            ]
        if recording == "new_office":
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert [(state["game"]["night"]["closed"], state["game"]["night"]["result"])
                    for state in state_updates(events)] == [(True, None), (True, "translated")]
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            assert state_updates(events) == []
        client.post("/actions", json={"action": "load", "save": save})
        night = client.get("/state").json()["game"]["night"]
        assert night["closed"] is True
        assert night["result"] == "translated"
        ledger = audit(tmp_path / save)
        orders = [e for e in ledger["entities"] if e["kind"] == "decree"]
        assert orders
        if recording == "approved":
            steps["Declaration"] = replaying([json.dumps({"facts": [{
                "entity_type": "decree", "entity": orders[0]["key"], "create": False,
                "changes": [{"field": "people", "value": []}], "text": "",
            }]})])
        assert all(e["data"]["night_id"] == first["id"] for e in orders)
        assert all(e["data"].get("secret") is False for e in orders)
        assert all(e["data"]["turn"] == {"approved": 4, "new_office": 2}[recording] for e in orders)
        assert all(
            set(e["data"])
            == {"text", "origin", "people", "night_id", "secret", "handler", "turn", "endorsements", "interim"}
            and e["data"]["handler"] is None
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
        ledger = audit(tmp_path / save)
        assert {f["entity_id"] for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] in {e["id"] for e in orders}} == {e["id"] for e in orders}
        if recording == "approved":
            assert next(e["data"]["people"] for e in ledger["entities"] if e["id"] == orders[0]["id"]) == []
        client.post("/actions", json={"action": "open"})
        second = client.get("/state").json()["game"]["night"]
        assert first["id"] != second["id"]
        assert second["turns"] == []


def run_scene_tools_night(client, case, received, translated, multi):
    client.post("/actions", json={"action": "load", "save": case["save"]})
    court = client.app.state.web.game.court
    # Oversized private files force the recorded multi-admit through #2017 pages.
    for name in multi:
        court.record(("dossier", name), [("changed", {})], {"pad": "字" * 5000})
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
        assert next(part.content for message in reversed(received)
                    for part in message.parts if part.part_kind == "user-prompt") == turn["emperor_words"]
    assert received[0].parts[0].part_kind == "system-prompt"
    assert received[0].parts[1].part_kind == "system-prompt"
    material = json.loads(received[0].parts[1].content)
    assert isinstance(material["imperial_prestige"], str)
    assert material["gazette"] == court.read.entities("audit", kind="gazette")[0].data["text"]
    assert court.nights()[0].result == "translated"
    assert _declaration_prompt(translated)["turns"] == [t.model_dump(mode="json") for t in court.nights()[0].turns]
    first, second = sorted(
        court.read.entities("audit", kind="decree"), key=lambda d: d.data["turn"]
    )
    # Knowledge follows the hall at approval, before that turn's scene tools.
    for person, known in (
        ("杨嗣昌", {first.id}),
        ("王绍徽", {first.id, second.id}),
        ("郭允厚", {second.id}),
    ):
        assert {
            d.id for d in court.read.entities(Officials(people=[person]), kind="decree")
        } == known
    return court


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_scene_tools_use_physical_location_not_office_and_project_dossiers(
    tmp_path: Path, game_db: Path, steps
) -> None:
    case = json.loads((RECORDED / "night_tools.json").read_text())
    case["offices"] = ["内阁首辅", "户部尚书"]
    case["save"] = game_db.name
    received: list = []
    continuations: dict[str, str] = {}
    multi = ["杨嗣昌", "王绍徽"]
    steps["scene"] = replaying(scene_tool_script(case), received, continuations=continuations)
    translated: list = []
    steps["NightDeclaration"] = replaying(case["replies"], translated)
    events = asyncio.Queue()
    with TestClient(create_app(tmp_path)) as client:
        client.app.state.web.listeners.add(events)
        court = run_scene_tools_night(client, case, received, translated, multi)
    assert_scene_tool_returns(
        received, events, court, continuations,
        (multi, "toolu_01HpPBW2pUSsbkYWHzFR5vLd"),
    )


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_set_hall_retry_after_model_failure_still_attaches_records(
    tmp_path: Path, game_db: Path, steps,
) -> None:
    first_calls: list[list] = []
    first_replies = iter([
        ModelResponse(parts=[ToolCallPart("set_hall", {"add": ["杨嗣昌"], "remove": []}, tool_call_id="first")]),
        ModelHTTPError(429, "recording"),
    ])
    steps["scene"] = replaying(
        lambda messages: first_calls.append(list(messages)) or next(first_replies),
    )
    with TestClient(create_app(tmp_path)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "say", "words": "宣杨嗣昌。"})
        client.portal.call(client.app.state.web.game.drain)
        game = client.get("/state").json()["game"]
        assert game["failure"]["action"] == "say"
        assert game["night"]["turns"] == []
        assert "杨嗣昌" in game["night"]["hall"]

        retry_calls: list[list] = []
        retry_received: list = []
        retry_replies = iter([
            ModelResponse(parts=[ToolCallPart("set_hall", {"add": ["杨嗣昌"], "remove": []}, tool_call_id="retry")]),
            "臣杨嗣昌见驾。",
        ])
        steps["scene"] = replaying(
            lambda messages: retry_calls.append(list(messages)) or next(retry_replies),
            retry_received,
        )
        client.post("/actions", json={"action": "retry"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        game = client.get("/state").json()["game"]
        assert game["failure"] is None
        assert len(game["night"]["turns"]) == 1
        assert "杨嗣昌" in game["night"]["hall"]
        court = client.app.state.web.game.court

        # Retry starts from the same input as the first attempt; failed tool traffic is not history.
        def prompt_parts(messages):
            return [
                (part.part_kind, getattr(part, "content", None))
                for message in messages for part in message.parts
                if part.part_kind in {"system-prompt", "user-prompt"}
            ]

        assert prompt_parts(retry_calls[0]) == prompt_parts(first_calls[0])
        assert not any(
            isinstance(part, (ToolCallPart, ToolReturnPart))
            for message in retry_calls[0] for part in message.parts
        )

        retry_return = next(
            part.model_response_object()
            for message in retry_received
            for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == "set_hall"
        )
        expected = court.read.query(Officials(people=retry_return["hall"]), "person", ["杨嗣昌"])
        assert {key: retry_return[key] for key in expected} == expected
        assert "dossier" in retry_return["entities"][0]["data"]


@pytest.mark.parametrize("recording,case,game_db", [
    ("endorsed", case, "backed_night") for case in ["approved", "held", "form", "source", "name", "person"]
] + [("double", "approved", "double_backed_night")], indirect=["game_db"])
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
        [(RECORDED / ("deliberation_rejected.txt" if case == "held" else "deliberation.txt")).read_text()], received,
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
                assert failure["expected"] == {"catalogue": "person"}
                assert set(failure) == {"field", "current", "expected", "action"}
            assert len([f for f in audit(game_db)["facts"] if f["kind"] == "unhandled"]) == 1
            assert [f["detail"] for f in client.get("/records").json()["facts"] if f["kind"] == "unhandled"] == [{}]
            # One terminal night failure proves month handoff; the other
            # invalid fields still prove rejection and opening the next night.
            if case == "source":
                client.post("/actions", json={"action": "month"}).raise_for_status()
                state = client.get("/state").json()["game"]
                assert (state["face"], state["failure"], state["unhandled_monthly"], state["date"]["month"]) == ("desk", None, [], 11)
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
        assert state["petitions"] == []
        client.post("/actions", json={"action": "month"}).raise_for_status()
        if case == "held":
            state = client.get("/state").json()["game"]
            assert state["petitions"][0]["options"] == ["强颁", "收回", "留中"]
            client.post("/actions", json={"action": "choose", "petition": state["petitions"][0]["id"], "option": 2}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
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
            p.model_response_object()["entities"][0]["key"]: p.model_response_object()
            for m in dossiers for p in m.parts
            if isinstance(p, ToolReturnPart) and p.tool_name == "read_records"
        }
        for signer in signers:
            events = [{"kind": f["kind"], **f["detail"]} for f in returned[signer["endorser"]]["facts"]]
            assert [
                (e["decree_id"], e["endorser"], e["form"])
                for e in events if e["kind"] == "endorsed"
            ] == [(decree["id"], signer["endorser"], signer["form"])]


def test_failed_night_translation_is_terminal_and_reaches_following_nights(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    recording = json.loads((RECORDED / "night_invalid.json").read_text())
    cases = recording["cases"]
    steps["scene"] = replaying([case["scene"] for case in cases.values()])
    steps["NightDeclaration"] = replaying(
        [case["reply"] for case in cases.values() for _ in range(2)],
    )
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        before = audit(tmp_path / save)["entities"]
        nights = []
        for case in cases:
            assert client.post("/actions", json={"action": "open"}).status_code == 204
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
                client.post("/actions", json={"action": "dismiss"}).status_code == 204
            )
            client.post("/actions", json={"action": "load", "save": save})
            state = client.get("/state").json()["game"]
            assert state["face"] == "desk"
            assert state["night"]["result"] == "unhandled"
            assert state["failure"] is None
            ledger = audit(tmp_path / save)
            nights.append(state["night"]["id"])
            assert [
                e for e in ledger["entities"] if e["kind"] != "night"
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
        assert client.post("/actions", json={"action": "open"}).status_code == 204
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/state").json()["game"] is None
        client.post("/actions", json={"action": "continue"})
        state = client.get("/state").json()["game"]
        assert state["face"] == "audience"
        assert state["night"]["turns"] == []
        assert client.post("/actions", json={"action": "month"}).status_code == 409
