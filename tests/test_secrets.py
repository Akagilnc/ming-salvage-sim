"""Medium: one recorded mixed night through HTTP actions and identity read doors."""

import asyncio
import json
from functools import partial
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessagesTypeAdapter
from starlette.testclient import TestClient

from ming.middle.view import Officials
from ming.web import create_app
from tests.test_court import replaying
from tests.test_web import assert_record_queries

RECORDED = Path(__file__).parent / "recorded"


def _declaration_prompt(messages):
    return json.loads(messages[0].parts[0].content.split("\n", 1)[1])


def declaration_reply(messages, response_file, quiet_month=None, stage="landing"):
    prompt = _declaration_prompt(messages) if stage == "landing" else json.loads(messages[0].parts[0].content)
    source = prompt["source"] if stage == "landing" else next(iter(prompt["context"].get("decrees", [])), None)
    if response_file == "night_ordering.json":
        if source is None or source["kind"] != "decree":
            return (RECORDED / ("month_empty.txt" if stage == "landing" else "simulation.txt")).read_text()
        name = "secret" if source["data"].get("secret") else "public"
        return json.loads((RECORDED / response_file).read_text())[name][stage]
    name = response_file if source["data"].get("secret") and prompt["date"]["month"] != quiet_month else "month_empty.txt"
    return (RECORDED / name).read_text()


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
@pytest.mark.parametrize("failure", [None, "declaration", "report"])
def test_secret_orders_keep_their_readers_and_monthly_products(
    tmp_path: Path, game_db: Path, steps, audit, failure
) -> None:
    material = []
    declarations = []
    steps["Declaration"] = replaying(
        partial(
            declaration_reply,
            response_file="month_invalid.txt" if failure == "declaration" else "month_empty.txt",
        ),
        declarations,
    )
    if failure == "report":
        steps["secret_report"] = replaying([ModelHTTPError(429, "recorded")])
    else:
        steps["secret_report"] = replaying(
            [(RECORDED / "secret_report.txt").read_text()] * 6, material
        )
    with TestClient(create_app(tmp_path)) as client:
        client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).raise_for_status()
        court = client.app.state.web.game.court
        orders = court.entities("audit", kind="decree")
        secret = next(d for d in orders if d.data["secret"])
        public = next(d for d in orders if not d.data["secret"])
        assert (secret.data["turn"], public.data["turn"]) == (3, 6)
        assert secret.data["exposure"] == {"score": 0, "stage": "密"}
        for person, expected in (
            ("王承恩", {secret.id, public.id}),
            ("杨嗣昌", {secret.id}),
            ("王绍徽", {public.id}),
            ("魏忠贤", set()),
        ):
            assert {
                d.id for d in court.entities(Officials(people=[person]), kind="decree")
            } == expected
            assert [
                e["date"]
                for e in court.read_person(person).events
                if e["kind"] == "decreed"
            ] == [court.calendar().data] * len(expected)
        assert not court.entities("public", kind="decree")
        assert {
            d.id
            for d in court.entities(
                Officials(people=["王承恩"], exclude_secrets=True), kind="decree"
            )
        } == {public.id}
        assert {f.entity_id for f in court.facts("audit", kind="deliberation")} == {
            public.id
        }
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        if failure == "report":
            assert (
                client.get("/state").json()["game"]["failure"]["payload"]["type"]
                == "ModelHTTPError"
            )
            before = audit(game_db)
            client.post(
                "/actions", json={"action": "load", "save": game_db.name}
            ).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert audit(game_db) == before
            steps["secret_report"] = replaying(
                [(RECORDED / "secret_report.txt").read_text()] * 6, material
            )
            client.post("/actions", json={"action": "retry"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        # The new native night has two knowers and no handled event.
        for month in range(6):
            court = client.app.state.web.game.court
            assert client.get("/state").json()["game"]["failure"] is None
            assert client.get("/state").json()["game"]["unhandled_monthly"] == (
                [{"entity_id": str(secret.id), "kind": "decree", "text": secret.data["text"]}]
                if failure == "declaration" else []
            )
            if failure is None and month < 2:
                asyncio.run(assert_record_queries(court))
            assert {d.id for d in court.entities("public", kind="decree")} == {
                public.id
            }
            exposure = court.products(secret.id, kind="exposure", current=False)
            assert [f.detail["score"] for f in exposure] == [2, 4, 6, 8, 10, 12][: month + 1]
            assert exposure[-1].detail["stage"] == ("半公开" if month == 5 else "密")
            assert {f.entity_id for f in court.facts("audit", kind="unhandled")} == (
                {secret.id} if failure == "declaration" else set()
            )
            world = next(
                prompt for r in declarations
                if r.kind == "request" and r.parts[0].part_kind == "user-prompt"
                and (prompt := _declaration_prompt([r]))["scope"] == "world"
                and prompt["date"] == exposure[-1].detail["date"]
            )
            assert [o["decree"]["id"] for o in world["others"]] == [
                str(d.id) for d in orders if month == 0 or d.id == secret.id
            ]
            for person, count in (
                ("王承恩", month + 1),
                ("杨嗣昌", 0),
                ("王绍徽", 0),
                ("魏忠贤", 0),
            ):
                assert (
                    len(court.facts(Officials(people=[person]), kind="secret_report"))
                    == count
                )
            assert [
                f.detail["date"] for f in court.facts("emperor", kind="secret_report")
            ] == [f.detail["date"] for f in exposure]
            assert not court.facts("public", kind="secret_report")
            if month < 5:
                client.post(
                    "/actions", json={"action": "load", "save": game_db.name}
                ).raise_for_status()
                client.post("/actions", json={"action": "month"}).raise_for_status()
                client.portal.call(client.app.state.web.game.drain)
        for message in material:
            for part in message.parts:
                if part.part_kind == "user-prompt":
                    prompt = json.loads(part.content)
                    assert prompt["decree"]["id"] == str(secret.id)
                    assert all(
                        "emperor_words" not in f
                        for f in prompt["facts"] + prompt["products"]
                    )
        assert (
            json.loads(material[-1].parts[0].content)["decree"]["data"]["exposure"][
                "stage"
            ]
            == "半公开"
        )


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
@pytest.mark.parametrize(
    "scenario",
    [
        # Done in its decree month: the first accumulation already crosses.
        (None, [13, 26, 39, 52], ("半公开", "半公开", "满朝风闻", "满朝风闻")),
        # Quiet through its decree month, done the next from its own share.
        (10, [2, 15, 28, 41], ("密", "半公开", "半公开", "满朝风闻")),
    ],
    ids=["done-in-decree-month", "done-next-month"],
)
def test_discoveries_stay_private_and_completion_stops_only_reports(
    tmp_path: Path, game_db: Path, steps, scenario
) -> None:
    quiet_month, scores, stages = scenario
    steps["Declaration"] = replaying(
        partial(
            declaration_reply,
            response_file="month_secret_completed.txt",
            quiet_month=quiet_month,
        )
    )
    simulations = []
    steps["simulation"] = replaying(
        [(RECORDED / "simulation.txt").read_text()] * 4, simulations
    )
    with TestClient(create_app(tmp_path)) as client:
        client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).raise_for_status()
        court = client.app.state.web.game.court
        secret = next(
            d for d in court.entities("audit", kind="decree") if d.data["secret"]
        )
        for month in range(4):
            client.post("/actions", json={"action": "month"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
            court = client.app.state.web.game.court
            done = month >= (quiet_month is not None)
            assert len(
                court.products(secret.id, kind="completed", current=False)
            ) == int(done)
            for identity in ("emperor", Officials(people=["王承恩"])):
                assert len(court.facts(identity, kind="secret_report")) == min(
                    month + 1, 1 + (quiet_month is not None)
                )
            exposure = court.products(secret.id, kind="exposure", current=False)
            assert [f.detail["score"] for f in exposure] == scores[: month + 1]
            assert exposure[-1].detail["stage"] == stages[month]
            changed = [
                f
                for f in court.facts("audit", kind="changed")
                if f.detail.get("origin_ref") == str(secret.id)
            ]
            assert len(changed) == 2 * done
            assert [
                e["date"]
                for e in court.read_person("王承恩").events
                if e["kind"] == "changed"
            ] == [f.detail["date"] for f in changed if not f.detail["discovered"]]
            assert (
                court.entities("audit", kind="person", key="韩爌")[0].data["intrigue"]
                == 75
            ) == done
            for identity, discoveries in (
                ("emperor", True),
                ("public", False),
                (Officials(people=["王承恩"]), True),
                (Officials(people=["杨嗣昌"]), False),
                (Officials(people=["韩爌"]), False),
                (Officials(people=["魏忠贤"]), False),
            ):
                assert {f.entity_id for f in court.facts(identity, kind="changed")} == {
                    f.entity_id
                    for f in changed
                    if discoveries or not f.detail["discovered"]
                }
                assert all(
                    "origin_ref" not in f.detail
                    for f in court.facts(identity, kind="changed")
                )
            client.post(
                "/actions", json={"action": "load", "save": game_db.name}
            ).raise_for_status()
        assert (
            json.loads(simulations[-1].parts[0].content)["context"]["secret_orders"][0][
                "decree"
            ]["data"]["exposure"]["stage"]
            == stages[2]
        )


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_month_lands_an_earlier_public_decree_before_a_later_secret(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    """A public decree completed before a secret errand must land first.

    night_secret.json creates the secret first, so it cannot show the inversion.
    """
    cases = json.loads((RECORDED / "night_ordering.json").read_text())
    steps["Declaration"] = replaying(partial(declaration_reply, response_file="night_ordering.json"))
    steps["simulation"] = replaying(partial(declaration_reply, response_file="night_ordering.json", stage="simulation"))
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        for case in cases.values():
            steps["scene"] = replaying(ModelMessagesTypeAdapter.validate_python(case["scene_responses"]))
            steps["NightDeclaration"] = replaying([case["declaration"]])
            client.post("/actions", json={"action": "open"}).raise_for_status()
            for words in case["words"]:
                client.post("/actions", json={"action": "say", "words": words}).raise_for_status()
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        ledger = audit(tmp_path / save)
        decrees = [e for e in ledger["entities"] if e["kind"] == "decree"]
        appointment = next(e for e in ledger["entities"] if e["kind"] == "incumbency" and e["data"]["office"] == "巡抚" and e["data"]["territory"] == "陕西")
        assert [e["data"]["secret"] for e in decrees] == [False, True]
        assert not [f for f in ledger["facts"] if f["kind"] == "unhandled"]
        assert appointment["data"]["holders"] == ["杨嗣昌"]
        assert [f["detail"]["actual"]["holders"] for f in ledger["facts"] if f["entity_id"] == appointment["id"] and f["kind"] == "changed"] == [["洪承畴"], ["杨嗣昌"]]
