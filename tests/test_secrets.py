"""Medium: one recorded mixed night through HTTP actions and identity read doors."""

import json
from functools import partial
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from starlette.testclient import TestClient

from ming.middle.view import Officials
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


def _declaration_prompt(messages):
    return json.loads(messages[0].parts[0].content.split("\n", 1)[1])


def declaration_reply(messages, response_file, quiet_month=None):
    prompt = _declaration_prompt(messages)
    name = (
        response_file
        if prompt["source"]["data"].get("secret")
        and prompt["date"]["month"] != quiet_month
        else "month_empty.txt"
    )
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
@pytest.mark.parametrize(
    "scenario",
    [
        # Done in its decree month: the first accumulation already crosses.
        (None, [14, 28, 42, 56], ("半公开", "半公开", "满朝风闻", "满朝风闻")),
        # Quiet through its decree month, done the next from its own share.
        (10, [3, 17, 31, 45], ("密", "半公开", "半公开", "满朝风闻")),
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


def _night_reply(secret: bool) -> str:
    return json.dumps(
        {
            "facts": [],
            "reports": [],
            "decree_events": [],
            "decrees": [
                {
                    "text": "密查内库" if secret else "任命巡抚",
                    "origin": "emperor",
                    "secret": secret,
                    "turn": 1,
                    "people": ["王承恩"],
                }
            ],
        },
        ensure_ascii=False,
    )


def _appointment(person: str) -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "entity_type": "person",
                    "entity": person,
                    "create": False,
                    "changes": [
                        {"field": "office", "value": "巡抚"},
                        {"field": "office_region", "value": "陕西"},
                    ],
                    "text": "任职。",
                }
            ],
            "reports": [],
            "decree_events": [],
        },
        ensure_ascii=False,
    )


def _landing_reply(messages):
    source = _declaration_prompt(messages)["source"]
    if source["kind"] != "decree":
        return (RECORDED / "month_empty.txt").read_text()
    person = "杨嗣昌" if source["data"].get("secret") else "洪承畴"
    return _appointment(person)


@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_month_lands_an_earlier_public_decree_before_a_later_secret(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    """A public decree completed before a secret errand must land first.

    night_secret.json creates the secret first, so it cannot show the inversion.
    """
    steps["Declaration"] = replaying(_landing_reply)
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        for secret in (False, True):
            steps["scene"] = replaying(["殿上无事。"] * 2)
            steps["NightDeclaration"] = replaying([_night_reply(secret)])
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post(
                "/actions", json={"action": "say", "words": "先拟旨。"}
            ).raise_for_status()
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        ledger = audit(tmp_path / save)
        decrees = [e for e in ledger["entities"] if e["kind"] == "decree"]
        people = {
            e["key"]: e["data"] for e in ledger["entities"] if e["kind"] == "person"
        }
        assert [e["data"]["secret"] for e in decrees] == [False, True]
        assert (people["杨嗣昌"]["office"], people["杨嗣昌"]["office_region"]) == (
            "巡抚",
            "陕西",
        )
        assert people["洪承畴"]["office"] == ""
