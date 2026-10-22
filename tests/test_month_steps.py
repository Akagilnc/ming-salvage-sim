"""Medium: the new month branches through the same HTTP/CLI boundaries."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize(
    ("case", "game_db"),
    [
        ({"option": case[0], "new_night": case[1], "verdicts": case[2]},
         "first_night" if case[2] == ("vital",) else "rejected_night")
        for case in (
            (0, False, ("rejected", "approved")),
            (0, True, ("rejected", "approved")),
            (1, False, ("rejected", "approved")),
            (2, False, ("rejected", "approved")),
            (2, True, ("rejected", "approved")),
            (0, False, ("vital",)),
            (2, False, ("rejected", "rejected")),
            (2, False, ("rejected", "rejected", "approved")),
        )
    ],
    indirect=["game_db"],
)
def test_rejected_decree_is_forced_withdrawn_or_reconsidered(
    game_db: Path, steps, audit, clock, case: dict
) -> None:
    vital = case["verdicts"][0] == "vital"
    # The shared rejected node has already consumed the first verdict.
    steps["deliberation"] = replaying(
        [
            (RECORDED / {"rejected": "deliberation_rejected.txt", "approved": "deliberation.txt", "vital": "deliberation_vital.txt"}[v]).read_text()
            for v in (case["verdicts"] if vital else case["verdicts"][1:])
        ]
    )
    reforced = case["verdicts"][1:2] == ("rejected",)
    # The world's re-rejected held decree is pushed while the world segment fails.
    repushed = len(case["verdicts"]) == 3
    with TestClient(create_app(game_db.parent)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        if vital:
            for words in json.loads((RECORDED / "night_approved.json").read_text())[
                "words"
            ]:
                client.post("/actions", json={"action": "say", "words": words})
            client.post("/actions", json={"action": "load", "save": save})
        petition = client.get("/state").json()["game"]["petitions"][0]
        assert petition["options"] == (
            ["收回", "留中"] if vital else ["强颁", "收回", "留中", "御笔强推"]
        )
        ledger = audit(game_db.parent / save)
        assert len([f for f in ledger["facts"] if f["kind"] == "simulation"]) == 1
        assert not [f for f in ledger["facts"] if f["kind"] == "declaration"]
        if vital:
            decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
            assert next(
                f["detail"]["route_id"]
                for f in ledger["facts"]
                if f["kind"] == "deliberation"
            ) == decree["data"]["night_id"]
            steps["Declaration"] = replaying(
                [(RECORDED / "month_empty.txt").read_text()] * 2
            )
            client.post(
                "/actions",
                json={"action": "choose", "petition": petition["id"], "option": 0},
            )
            assert client.get("/state").json()["game"]["date"]["month"] == 10
            client.post("/actions", json={"action": "month"})
            assert client.get("/state").json()["game"]["date"]["month"] == 11
            client.post("/actions", json={"action": "month"})
            ledger = audit(game_db.parent / save)
            assert client.get("/state").json()["game"]["date"]["month"] == 12
            assert not [
                f
                for f in ledger["facts"]
                if f["kind"] == "landed" and f["entity_id"] == decree["id"]
            ]
            assert not [f for f in ledger["facts"] if f["kind"] == "interim"]
            assert next(e for e in ledger["entities"] if e["kind"] == "world")["data"]["imperial_prestige"] == 20
            return
        if case["option"] == 0 or reforced:
            steps["Declaration"] = replaying(
                [(RECORDED / name).read_text() for name in (
                    ("month_empty.txt", "month_empty.txt" if repushed else "month_force.txt", "month_empty.txt") if reforced
                    else ("month_force.txt", "month_empty.txt")
                )]
            )
        if case["option"] != 0 or case["new_night"]:
            client.post("/actions", json={"action": "month"})
            assert (
                len(
                    [
                        f
                        for f in audit(game_db.parent / save)["facts"]
                        if f["kind"] == "simulation"
                    ]
                )
                == 1
            )
        client.post(
            "/actions",
            json={"action": "choose", "petition": petition["id"], "option": case["option"]},
        )
        if case["option"] == 0 and not case["new_night"]:
            assert client.get("/state").json()["game"]["date"]["month"] == 10
            client.post("/actions", json={"action": "month"})
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        ledger = audit(game_db.parent / save)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        assert [(e["data"]["public_support"], e["data"]["imperial_prestige"] < 20,
                 e["data"]["imperial_prestige"] == 20)
                for e in ledger["entities"] if e["kind"] == "world"] == [(50, case["option"] == 0, case["option"] != 0)]
        assert len(
            [
                f
                for f in ledger["facts"]
                if f["kind"] == "landed" and f["entity_id"] == decree["id"]
            ]
        ) == int(case["option"] == 0)
        assert len([f for f in ledger["facts"] if f["kind"] == "interim"]) == int(
            case["option"] == 0
        )
        if case["option"] == 0:
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
        if reforced:
            if repushed:
                steps["simulation"] = replaying([TimeoutError()] * 30)
            client.post("/actions", json={"action": "month"})
            assert client.get("/state").json()["game"]["date"]["month"] == 11
            petition = client.get("/state").json()["game"]["petitions"][0]
            assert petition["options"] == ["强颁", "收回", "留中", "御笔强推"]
            client.post(
                "/actions",
                json={"action": "choose", "petition": petition["id"], "option": 3 if repushed else 0},
            )
            client.portal.call(client.app.state.web.game.drain)
            if repushed:
                assert client.get("/state").json()["game"]["failure"] is not None
                assert [f["detail"]["verdict"] for f in audit(game_db.parent / save)["facts"] if f["kind"] == "deliberation"] == ["驳", "驳", "准"]
                steps["simulation"] = replaying([(RECORDED / "simulation.txt").read_text()] * 6)
                client.post("/actions", json={"action": "retry"}).raise_for_status()
                client.portal.call(client.app.state.web.game.drain)
                assert client.get("/state").json()["game"]["date"]["month"] == 12
                ledger = audit(game_db.parent / save)
                original = next(
                    f["detail"] for f in ledger["facts"]
                    if f["kind"] == "simulation" and f["detail"]["date"]["month"] == 11
                    and f["detail"].get("petition_id") is None
                )
                context = json.loads(original["messages"][0]["parts"][0]["content"])["context"]
                assert [r["deliberation"]["decision_key"] for r in context["reconsidered"]] == [None]
                assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == 1
                assert next(e for e in ledger["entities"] if e["kind"] == "world")["data"]["imperial_prestige"] == 20
                return
            assert client.get("/state").json()["game"]["date"]["month"] == 12
            ledger = audit(game_db.parent / save)
            assert next(e for e in ledger["entities"] if e["kind"] == "world")["data"]["imperial_prestige"] < 20
            assert len(
                [
                    f
                    for f in ledger["facts"]
                    if f["kind"] == "landed" and f["entity_id"] == decree["id"]
                ]
            ) == 1
            assert len([f for f in ledger["facts"] if f["kind"] == "interim"]) == 1
            assert len(
                [f for f in ledger["facts"] if f["kind"] == "deliberation"]
            ) == 2
            assert next(
                f["detail"]["route_id"]
                for f in reversed(ledger["facts"])
                if f["kind"] == "deliberation"
            ) == next(e["id"] for e in ledger["entities"] if e["kind"] == "calendar")
            return
        steps["Declaration"] = TestModel(
            call_tools=[], custom_output_text=(RECORDED / "month_empty.txt").read_text()
        )
        if case["new_night"]:
            steps["NightDeclaration"] = TestModel(
                call_tools=[],
                custom_output_text=(RECORDED / "night_empty.txt").read_text(),
            )
            client.post("/actions", json={"action": "open"})
            received = []
            steps["scene"] = replaying([json.loads((RECORDED / "night_invalid.json").read_text())["cases"]["missing_fields"]["scene"]], received)
            client.post("/actions", json={"action": "say", "words": "宣徐光启。"}).raise_for_status()
            assert json.loads(received[0].parts[0].content[0])["imperial_prestige"] == ("威令未立" if case["option"] == 0 else "威福旁落")
            client.post("/actions", json={"action": "dismiss"})
        client.post("/actions", json={"action": "month"})
        ledger = audit(game_db.parent / save)
        assert client.get("/state").json()["game"]["date"]["month"] == 12
        assert len(
            [f for f in ledger["facts"] if f["kind"] == "deliberation"]
        ) == 1 + int(case["option"] == 2)
        if case["option"] == 2:
            assert any(
                f["kind"] == "landed" and f["entity_id"] == decree["id"]
                for f in ledger["facts"]
            )
            assert next(
                f["detail"]["route_id"]
                for f in reversed(ledger["facts"])
                if f["kind"] == "deliberation"
            ) == next(e["id"] for e in ledger["entities"] if e["kind"] == "calendar")


async def _month_during_push(
    client, petition_id: str, steps, received: list, fail: bool = False
) -> bool:
    """Busy choose of a push; month starts before that reconsideration lands or fails."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow(messages, _info):
        if not fail:
            received.extend(messages)
        entered.set()
        await release.wait()
        if fail:
            raise TimeoutError()
        return ModelResponse(parts=[TextPart((RECORDED / "deliberation.txt").read_text())])

    game = client.app.state.web.game
    await game.drain()
    steps["deliberation"] = FunctionModel(slow)
    hold = asyncio.Event()

    async def busy():
        await hold.wait()

    game.active = asyncio.create_task(busy())
    choose = game.start("choose", {"petition": petition_id, "option": 3})
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0)
        assert entered.is_set()
        hold.set()
        await asyncio.sleep(0)
        month = game.start("month")
        for _ in range(100):
            if month.done():
                break
            await asyncio.sleep(0)
        waited = not month.done()
        if fail:
            assert waited
        release.set()
        await asyncio.gather(month, choose, return_exceptions=fail)
        await game.drain()
        return waited
    finally:
        hold.set()
        release.set()
        await game.drain()


def _recover_failed_push(client, petition_id, steps, received, save: str | None) -> None:
    """Failed push, then in-process retry, or the same retry after reopen."""
    client.portal.call(
        _month_during_push, client, petition_id, steps, received, True
    )
    steps["deliberation"] = replaying(
        [(RECORDED / "deliberation.txt").read_text()], received
    )
    if save is not None:
        client.post("/actions", json={"action": "load", "save": save}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
    for _ in client.app.state.web.game.failures():
        if client.get("/state").json()["game"]["failure"] is None:
            break
        client.post("/actions", json={"action": "retry"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)


def _retry_choose(client, game_db, steps, case, audit) -> None:
    unsimulated = case.startswith("original")
    assert len([f for f in audit(game_db)["facts"] if f["kind"] == "deliberation"]) == 1 + unsimulated
    if unsimulated:
        steps["simulation"] = replaying([(RECORDED / "simulation.txt").read_text()] * 6)
    if case == "original_reopen":
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
    client.post("/actions", json={"action": "retry"}).raise_for_status()
    client.portal.call(client.app.state.web.game.drain)


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
@pytest.mark.parametrize(
    ("case", "game_db"),
    [(case, "rejected_night") for case in (
        "approved", "rejected", "retry", "in_flight", "push_fail", "push_reopen",
    )]
    + [(case, "first_night") for case in ("original_retry", "original_reopen")],
    indirect=["game_db"],
)
def test_imperial_backing_reconsiders_the_original_decree(game_db, steps, audit, clock, case):
    received = []
    unsimulated = case.startswith("original")
    steps["deliberation"] = replaying(
        ([TimeoutError()] * 3 if case == "retry" else [])
        + ([(RECORDED / "deliberation_rejected.txt").read_text()] if unsimulated else [])
        + [(RECORDED / ("deliberation_rejected.txt" if case == "rejected" else "deliberation.txt")).read_text()],
        received,
    )
    if unsimulated:
        # The night's own segment keeps failing until the push has been approved.
        steps["simulation"] = replaying([TimeoutError()] * 30)
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        if unsimulated:
            for words in json.loads((RECORDED / "night_approved.json").read_text())["words"]:
                client.post("/actions", json={"action": "say", "words": words}).raise_for_status()
            client.post("/actions", json={"action": "load", "save": game_db.name})
            client.portal.call(client.app.state.web.game.drain)
        petition = client.get("/state").json()["game"]["petitions"][0]
        if case == "approved":
            for invalid in (
                {"petition": "00000000-0000-0000-0000-000000000000", "option": 3},
                {"petition": petition["id"], "option": 4},
                {"petition": petition["id"], "words": "朕另下手敕，照此办理。"},
            ):
                assert client.post("/actions", json={"action": "choose", **invalid}).status_code == 400
        if case.startswith("push_"):
            _recover_failed_push(
                client, petition["id"], steps, received,
                game_db.name if case == "push_reopen" else None,
            )
        elif case == "in_flight":
            # J3: busy choose of 御笔强推, month starts while that reconsideration is in flight.
            assert client.portal.call(_month_during_push, client, petition["id"], steps, received)
        else:
            client.post("/actions", json={"action": "choose", "petition": petition["id"], "option": 3}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        if not case.startswith("push_") and (case.endswith("retry") or case == "original_reopen"):
            _retry_choose(client, game_db, steps, case, audit)
        ledger = audit(game_db)
        decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
        original = next(
            f["detail"] for f in ledger["facts"]
            if f["kind"] == "simulation" and f["entity_id"] == decree["data"]["night_id"]
            and f["detail"].get("petition_id") is None
        )
        # The night's own segment keeps its own verdict; the push belongs to the petition's chain.
        context = json.loads(original["messages"][0]["parts"][0]["content"])["context"]
        assert context["decrees"] == []
        assert [d["decision_key"] for d in context["deliberations"]] == [None]
        assert decree["data"]["endorsements"] == [{
            "endorser": "御笔", "form": "御笔手敕",
            "decision_key": {"petition_id": petition["id"], "option": 3},
        }]
        assert json.loads(received[-1].parts[0].content)["context"]["decree"]["data"]["endorsements"] == decree["data"]["endorsements"]
        assert len([e for e in ledger["entities"] if e["kind"] == "decree"]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "deliberation"]) == 2
        assert len([f for f in ledger["facts"] if f["kind"] == "endorsed"]) == 1
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        if case == "rejected":
            assert state["petitions"][0]["options"] == ["强颁", "收回", "留中"]
            assert client.post("/actions", json={"action": "choose", "petition": state["petitions"][0]["id"], "option": 3}).status_code == 400
            client.post("/actions", json={"action": "choose", "petition": state["petitions"][0]["id"], "option": 1}).raise_for_status()
        else:
            assert state["petitions"] == []
        if case != "in_flight" and not case.startswith("push_"):
            client.post("/actions", json={"action": "month"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        ledger = audit(game_db)
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == int(case != "rejected")
        assert next(
            f["detail"]["date"]["month"]
            for f in ledger["facts"]
            if f["kind"] == "deliberation" and f["detail"].get("decision_key")
        ) == 10
        assert len([
            f for f in ledger["facts"]
            if f["kind"] == "simulation" and f["entity_id"] == decree["data"]["night_id"]
            and f["detail"].get("petition_id") == petition["id"]
        ]) == int(case != "rejected")
        assert not [f for f in ledger["facts"] if f["kind"] == "interim"]
        assert next(e for e in ledger["entities"] if e["kind"] == "world")["data"]["imperial_prestige"] == 20
        assert not [f for f in ledger["facts"] if f["kind"] == "changed" and "satisfaction" in f["detail"].get("actual", {})]


@pytest.mark.usefixtures("backed_night")
@pytest.mark.parametrize("backed_night", ["interim"], indirect=True)
@pytest.mark.parametrize("game_db", ["backed_night"], indirect=True)
@pytest.mark.parametrize("case", ["approved", "withdrawn", "held"])
def test_interim_costs_follow_promulgation_not_backing(game_db, steps, audit, case):
    rejected = case != "approved"
    steps["NightDeclaration"] = replaying(json.loads((RECORDED / "night_interim.json").read_text())["replies"])
    received = []
    # A held decree is reconsidered and approved the next month.
    verdicts = ["rejected", "approved"] if case == "held" else ["rejected" if rejected else "approved"]
    steps["deliberation"] = replaying([(RECORDED / ("deliberation_rejected.txt" if v == "rejected" else "deliberation.txt")).read_text() for v in verdicts], received)
    steps["Declaration"] = replaying([
        reply for v in verdicts
        for reply in (*json.loads((RECORDED / f"month_interim_{v}.json").read_text())["replies"], (RECORDED / "month_empty.txt").read_text())
    ])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        decree = next(e for e in audit(game_db)["entities"] if e["kind"] == "decree")
        assert decree["data"]["interim"] is True
        assert json.loads(received[-1].parts[0].content)["context"]["decree"]["data"]["interim"] is True
        assert [e["endorser"] for e in decree["data"]["endorsements"]] == ["毕自严", "御笔"]
        if rejected:
            assert state["petitions"][0]["options"] == ["强颁", "收回", "留中"]
            client.post("/actions", json={"action": "choose", "petition": state["petitions"][0]["id"], "option": 2 if case == "held" else 1}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        ledger = audit(game_db)
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        assert len([f for f in ledger["facts"] if f["kind"] == "interim" and f["entity_id"] == decree["id"]]) == 1
        assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == int(not rejected)
        effects = [f for f in ledger["facts"] if f["kind"] == "changed" and f["detail"]["origin_ref"] == decree["id"]]
        assert len([f for f in effects if "imperial_prestige" in f["detail"]["actual"]]) == int(not rejected)
        assert any("satisfaction" in f["detail"]["actual"] for f in effects)
        assert len({f["entity_id"] for f in effects if "satisfaction" in f["detail"]["actual"]}) == len([f for f in effects if "satisfaction" in f["detail"]["actual"]])
        if rejected:
            assert next(e for e in ledger["entities"] if e["kind"] == "world")["data"]["imperial_prestige"] == 20
            assert not [f for f in effects if "taels" in f["detail"]["actual"]]
        if case == "held":
            client.post("/actions", json={"action": "month"}).raise_for_status()
            ledger = audit(game_db)
            assert client.get("/state").json()["game"]["date"]["month"] == 12
            assert [f["detail"]["verdict"] for f in ledger["facts"] if f["kind"] == "deliberation"] == ["驳", "准"]
            assert len([f for f in ledger["facts"] if f["kind"] == "landed" and f["entity_id"] == decree["id"]]) == 1
            assert len([f for f in ledger["facts"] if f["kind"] == "interim" and f["entity_id"] == decree["id"]]) == 1


def test_two_nights_feed_world_and_arrivals_wait_for_audience(
    tmp_path: Path, game_db: Path, steps, audit
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
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
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
            assert audit(tmp_path / save) == ledger
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
