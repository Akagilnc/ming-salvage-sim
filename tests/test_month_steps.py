"""Medium: the new month branches through the same HTTP/CLI boundaries."""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize(
    ("option", "new_night"), [(0, False), (0, True), (1, False), (2, False), (2, True)]
)
def test_rejected_decree_is_forced_withdrawn_or_reconsidered(
    tmp_path: Path, steps, audit, option: int, new_night: bool
) -> None:
    steps["deliberation"] = replaying(
        [
            (RECORDED / name).read_text()
            for name in ("deliberation_rejected.txt", "deliberation.txt")
        ]
    )
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        client.post("/actions", json={"action": "open"})
        for words in json.loads((RECORDED / "night_approved.json").read_text())[
            "words"
        ]:
            client.post("/actions", json={"action": "say", "words": words})
        client.post("/actions", json={"action": "load", "save": save})
        state = client.get("/state").json()["game"]
        petition = state["petitions"][0]
        assert petition["options"] == ["强颁", "收回", "留中"]
        ledger = audit(tmp_path / save)
        assert len([f for f in ledger["facts"] if f["kind"] == "simulation"]) == 1
        assert not [f for f in ledger["facts"] if f["kind"] == "declaration"]
        if option == 0:
            steps["Declaration"] = replaying(
                [
                    (RECORDED / name).read_text()
                    for name in ("month_force.txt", "month_empty.txt")
                ]
            )
        if option != 0 or new_night:
            client.post("/actions", json={"action": "month"})
            assert (
                len(
                    [
                        f
                        for f in audit(tmp_path / save)["facts"]
                        if f["kind"] == "simulation"
                    ]
                )
                == 1
            )
        client.post(
            "/actions",
            json={"action": "choose", "petition": petition["id"], "option": option},
        )
        if option == 0 and not new_night:
            assert client.get("/state").json()["game"]["date"]["month"] == 10
            client.post("/actions", json={"action": "month"})
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        ledger = audit(tmp_path / save)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        world = next(e for e in ledger["entities"] if e["kind"] == "world")
        assert world["data"]["public_support"] == 50
        assert (world["data"]["imperial_prestige"] < 20) == (option == 0)
        assert (world["data"]["imperial_prestige"] == 20) == (option != 0)
        assert len(
            [
                f
                for f in ledger["facts"]
                if f["kind"] == "landed" and f["entity_id"] == decree["id"]
            ]
        ) == int(option == 0)
        assert len([f for f in ledger["facts"] if f["kind"] == "interim"]) == int(
            option == 0
        )
        if option == 0:
            assert any(
                "satisfaction" in f["detail"]["actual"]
                for f in ledger["facts"]
                if f["kind"] == "changed" and f["detail"]["origin_ref"] == decree["id"]
            )
            segments = [
                f["detail"]
                for f in ledger["facts"]
                if f["kind"] == "simulation"
                and f["entity_id"] == decree["data"]["night_id"]
            ]
            assert len(segments) == 2
            assert segments[1]["petition_id"] == petition["id"]
            assert len(segments[1]["messages"]) > len(segments[0]["messages"])
        steps["Declaration"] = TestModel(
            call_tools=[], custom_output_text=(RECORDED / "month_empty.txt").read_text()
        )
        if new_night:
            steps["NightDeclaration"] = TestModel(
                call_tools=[],
                custom_output_text=(RECORDED / "night_empty.txt").read_text(),
            )
            client.post("/actions", json={"action": "open"})
            client.post("/actions", json={"action": "dismiss"})
        client.post("/actions", json={"action": "month"})
        ledger = audit(tmp_path / save)
        assert client.get("/state").json()["game"]["date"]["month"] == 12
        assert len(
            [f for f in ledger["facts"] if f["kind"] == "deliberation"]
        ) == 1 + int(option == 2)
        if option == 2:
            assert any(
                f["kind"] == "landed" and f["entity_id"] == decree["id"]
                for f in ledger["facts"]
            )
            assert next(
                f["detail"]["route_id"]
                for f in reversed(ledger["facts"])
                if f["kind"] == "deliberation"
            ) == next(e["id"] for e in ledger["entities"] if e["kind"] == "calendar")
        assert ledger == audit(tmp_path / save, True)


def test_two_nights_feed_world_and_arrivals_wait_for_audience(
    tmp_path: Path, steps, audit
) -> None:
    received = []
    steps["simulation"] = replaying(
        [(RECORDED / "simulation.txt").read_text()] * 4, received
    )
    steps["Declaration"] = replaying(
        [
            (RECORDED / "month_travel.txt").read_text(),
            *[(RECORDED / "month_empty.txt").read_text()] * 4,
        ]
    )
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        for case in ("travel", "approved"):
            case = json.loads((RECORDED / f"night_{case}.json").read_text())
            steps["scene"] = replaying(
                [
                    m
                    for m in ModelMessagesTypeAdapter.validate_python(
                        case["scene_responses"]
                    )
                    if isinstance(m, ModelResponse)
                ]
            )
            steps["NightDeclaration"] = replaying(case["replies"])
            client.post("/actions", json={"action": "open"})
            for words in case["words"]:
                client.post("/actions", json={"action": "say", "words": words})
            client.post("/actions", json={"action": "dismiss"})
            client.post("/actions", json={"action": "load", "save": save})
        ledger = audit(tmp_path / save)
        nights = {e["id"] for e in ledger["entities"] if e["kind"] == "night"}
        assert {
            f["entity_id"] for f in ledger["facts"] if f["kind"] == "simulation"
        } == nights
        assert len(nights) == 2
        for month in (11, 12):
            client.post("/actions", json={"action": "month"})
            state = client.get("/state").json()["game"]
            assert state["date"]["month"] == month
            assert state["failure"] is None
            if month == 11:
                assert {
                    n["night_id"]
                    for n in json.loads(received[-1].parts[0].content)["context"][
                        "nights"
                    ]
                } == nights
            ledger = audit(tmp_path / save)
            for person in [
                e
                for e in ledger["entities"]
                if e["kind"] == "person" and e["key"] in {"毕自严", "徐光启"}
            ]:
                assert person["data"]["remaining_distance"] == pytest.approx(
                    0.6 if month == 11 else 0
                )
                assert person["data"]["location"] == (
                    "南直隶 / 南京" if month == 11 else "北直隶 / 京师"
                )
                assert person["data"]["waiting_audience"] == (month == 12)
                assert person["key"] not in state["night"]["hall"]
            client.post("/actions", json={"action": "load", "save": save})
            assert audit(tmp_path / save) == ledger == audit(tmp_path / save, True)
        steps["scene"] = replaying(
            ModelMessagesTypeAdapter.validate_json(
                (RECORDED / "travel_admission.json").read_bytes()
            )
        )
        client.post("/actions", json={"action": "open"})
        client.post(
            "/actions", json={"action": "say", "words": "宣毕自严、徐光启入殿。"}
        )
        assert {"毕自严", "徐光启"} <= set(
            client.get("/state").json()["game"]["night"]["hall"]
        )
        assert not any(
            e["data"]["waiting_audience"]
            for e in audit(tmp_path / save)["entities"]
            if e["kind"] == "person" and e["key"] in {"毕自严", "徐光启"}
        )
