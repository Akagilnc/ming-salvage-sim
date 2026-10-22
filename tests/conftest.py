"""Recorded model boundary: native overrides selected only by the declared call name."""

import asyncio
import io
import json
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from shutil import copyfile, copytree

import pytest
from pydantic_ai import Agent, models
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.__main__ import main
from ming.middle.court import Court
from ming.middle.opening import CONTENT
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"
AGENT_RUN = Agent.run
HISTORY_ACTIONS = {
    "month": ({"action": "month"},),
    "night": ({"action": "open"}, {"action": "dismiss"}),
}


@contextmanager
def recorded_steps(case=None):
    invalid = json.loads((RECORDED / "night_invalid.json").read_text())["cases"][
        "missing_fields"
    ]
    replies = {
        "scene": TestModel(call_tools=[], custom_output_text=invalid["scene"]),
        "NightDeclaration": TestModel(
            call_tools=[], custom_output_text=invalid["reply"]
        ),
        "Declaration": TestModel(
            call_tools=[], custom_output_text=(RECORDED / "month_empty.txt").read_text()
        ),
        **{
            name: TestModel(
                call_tools=[], custom_output_text=(RECORDED / f"{name}.txt").read_text()
            )
            for name in ("deliberation", "simulation", "gazette")
        },
    }
    if case == "approved":
        case = json.loads((RECORDED / "night_approved.json").read_text())
        replies["scene"] = replaying(
            [
                m
                for m in ModelMessagesTypeAdapter.validate_python(
                    case["scene_responses"]
                )
                if isinstance(m, ModelResponse)
            ]
        )
        replies["NightDeclaration"] = replaying(case["replies"])

    async def recorded(agent, *args, **kwargs):
        # Only the external model is substituted; Agent, tools and validators run normally.
        with agent.override(model=replies[agent.name]):
            return await AGENT_RUN(agent, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
        patch.setattr(Agent, "run", recorded)
        yield replies


@pytest.fixture
def steps(request):
    with recorded_steps(getattr(request, "param", None)) as replies:
        yield replies


@pytest.fixture(scope="session")
def opening_db(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("opening")
    if getattr(request, "param", None) is not None:
        content = copytree(CONTENT, directory / "content")
        opening = json.loads((content / "opening.json").read_text())
        if request.param == "shortage":
            for account in opening["accounts"]:
                account["taels"] = 0
            config = json.loads((content / "fiscal_config.json").read_text())
            for item in config["items"]:
                if item["key"] in {"官俸_base", "宫廷_base"}:
                    item["value"] = {"官俸_base": 2000, "宫廷_base": 1000}[item["key"]]
            (content / "fiscal_config.json").write_text(json.dumps(config))
        elif request.param == "prestige":
            opening["world"][0]["imperial_prestige"] = 100
        else:
            opening["calendar"][0].update(year=request.param, month=1)
        (content / "opening.json").write_text(json.dumps(opening))
        if request.param == 1640:
            events = json.loads((content / "events.json").read_text())
            next(e for e in events if e["id"] == "jiao_levy_start_1637")[
                "terminal_reason"
            ] = "已准"
            (content / "events.json").write_text(json.dumps(events))
        court = Court.new_game(directory, TestModel(), content)
        court.close()
        return court.db_path
    with TestClient(create_app(directory)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        fresh = client.get("/state").json()["game"]
        assert (fresh["night"], fresh["date"]) == (
            None,
            {"id": "world", "year": 1627, "month": 10},
        )
    return directory / save


@pytest.fixture(scope="session")
def first_night(opening_db, tmp_path_factory):
    return extend_history(
        opening_db, tmp_path_factory.mktemp("first-night"), ({"action": "open"},)
    )


@pytest.fixture(scope="session")
def spoken_night(first_night, tmp_path_factory):
    case = json.loads((RECORDED / "night_invalid.json").read_text())
    return extend_history(
        first_night,
        tmp_path_factory.mktemp("spoken-night"),
        ({"action": "say", "words": case["emperor_words"]},),
    )


@pytest.fixture(scope="session")
def rejected_night(first_night, tmp_path_factory):
    path = tmp_path_factory.mktemp("rejected-night") / first_night.name
    copyfile(first_night, path)
    with (
        recorded_steps("approved") as replies,
        TestClient(create_app(path.parent)) as client,
    ):
        replies["deliberation"] = replaying(
            [(RECORDED / "deliberation_rejected.txt").read_text()]
        )
        client.post("/actions", json={"action": "load", "save": path.name})
        for words in json.loads((RECORDED / "night_approved.json").read_text())[
            "words"
        ]:
            client.post(
                "/actions", json={"action": "say", "words": words}
            ).raise_for_status()
        client.post("/actions", json={"action": "load", "save": path.name})
        client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["petitions"]
    return path


def extend_history(source, directory, actions):
    path = directory / source.name
    copyfile(source, path)
    with recorded_steps() as replies, TestClient(create_app(directory)) as client:
        replies["NightDeclaration"] = TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"facts": [], "reports": [], "decrees": []}),
        )
        client.post("/actions", json={"action": "load", "save": path.name})
        for action in actions:
            client.post("/actions", json=action).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
    return path


@pytest.fixture(scope="session")
def pending_histories(request, tmp_path_factory):
    history = request.param
    actions = HISTORY_ACTIONS[history]
    node = request.getfixturevalue(
        "opening_db" if history == "month" else "first_night"
    )
    paths = {}
    for size, added in ((1, actions[-1:]), (2, actions), (4, actions * 2)):
        node = extend_history(node, tmp_path_factory.mktemp("history"), added)
        directory = tmp_path_factory.mktemp("pending-history")
        path = (
            extend_history(node, directory, HISTORY_ACTIONS["night"])
            if history == "month"
            else copyfile(node, directory / node.name)
        )
        with recorded_steps() as replies, TestClient(create_app(directory)) as client:
            petitions = (RECORDED / "month_multiple_petitions.txt").read_text()
            replies["simulation"] = replaying(
                [
                    petitions,
                    *[(RECORDED / "simulation.txt").read_text()]
                    * sum(
                        len(p["options"]) for p in json.loads(petitions)["petitions"]
                    ),
                ]
            )
            client.post("/actions", json={"action": "load", "save": path.name})
            client.post("/actions", json={"action": "month"}).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
            client.post("/actions", json={"action": "load", "save": path.name})
            client.portal.call(client.app.state.web.game.drain)
            assert client.get("/state").json()["game"]["failure"] is None
        paths[size] = path
    return paths


@pytest.fixture
def game_db(request, tmp_path):
    # Sources are closed before copying; no live connection or WAL is shared.
    source = request.getfixturevalue(getattr(request, "param", "opening_db"))
    path = tmp_path / source.name
    copyfile(source, path)
    return path


@pytest.fixture
def audit():
    def read(db: Path, *, identity: str = "audit"):
        output = io.StringIO()
        with redirect_stdout(output):
            main(
                [
                    "read",
                    "--db",
                    str(db),
                    "--identity",
                    identity,
                ]
            )
        return json.loads(output.getvalue())

    return read


@pytest.fixture
def clock(monkeypatch):
    waits = []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        if delay == 5:
            waits.append(delay)
            delay = 0
        await real_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return waits
