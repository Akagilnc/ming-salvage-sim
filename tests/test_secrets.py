"""Medium: one recorded mixed night through HTTP actions and identity read doors."""

import json
from functools import partial
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from starlette.testclient import TestClient

from ming.middle.view import Officials
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


def declaration_reply(messages, response_file, quiet_month=None):
    prompt = json.loads(messages[0].parts[0].content.split("\n", 1)[1])
    return ModelResponse(
        parts=[
            TextPart(
                (
                    RECORDED
                    / (
                        response_file
                        if prompt["source"]["data"].get("secret")
                        and prompt["date"]["month"] != quiet_month
                        else "month_empty.txt"
                    )
                ).read_text()
            )
        ]
    )


@pytest.mark.parametrize("game_db", ["secret_night"], indirect=True)
@pytest.mark.parametrize("failure", [None, "declaration", "report"])
def test_secret_orders_keep_their_readers_and_monthly_products(
    tmp_path: Path, game_db: Path, steps, audit, failure
) -> None:
    material = []
    if failure == "declaration":
        steps["Declaration"] = replaying(
            partial(declaration_reply, response_file="month_invalid.txt")
        )
    if failure == "report":
        steps["secret_report"] = replaying([ModelHTTPError(429, "recorded")])
    else:
        steps["secret_report"] = replaying(
            [(RECORDED / "secret_report.txt").read_text()] * 4, material
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
            ("韩爌", {public.id}),
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
                [(RECORDED / "secret_report.txt").read_text()] * 4, material
            )
            client.post("/actions", json={"action": "retry"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        for month in range(4):
            court = client.app.state.web.game.court
            assert client.get("/state").json()["game"]["failure"] is None
            assert {d.id for d in court.entities("public", kind="decree")} == {
                public.id
            }
            exposure = court.products(secret.id, kind="exposure", current=False)
            assert [f.detail["score"] for f in exposure] == [3, 6, 9, 12][: month + 1]
            assert exposure[-1].detail["stage"] == ("半公开" if month == 3 else "密")
            assert {f.entity_id for f in court.facts("audit", kind="unhandled")} == (
                {secret.id} if failure == "declaration" else set()
            )
            for person, count in (
                ("王承恩", month + 1),
                ("杨嗣昌", 0),
                ("韩爌", 0),
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
            if month < 3:
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
def test_discoveries_stay_private_and_completion_stops_only_reports(
    tmp_path: Path, game_db: Path, steps
) -> None:
    # The errand runs quietly through its decree month and is done the next.
    steps["Declaration"] = replaying(
        partial(
            declaration_reply,
            response_file="month_secret_completed.txt",
            quiet_month=10,
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
            done = month >= 1
            assert len(
                court.products(secret.id, kind="completed", current=False)
            ) == int(done)
            for identity in ("emperor", Officials(people=["王承恩"])):
                assert len(court.facts(identity, kind="secret_report")) == min(
                    month + 1, 2
                )
            exposure = court.products(secret.id, kind="exposure", current=False)
            assert [f.detail["score"] for f in exposure] == [3, 17, 31, 45][: month + 1]
            assert (
                exposure[-1].detail["stage"]
                == ("密", "半公开", "半公开", "满朝风闻")[month]
            )
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
            == "半公开"
        )
