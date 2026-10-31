"""Recorded model boundary: native overrides selected only by the declared call name."""

import asyncio
import json
from contextlib import ExitStack, contextmanager
from collections import UserDict
from pathlib import Path
from shutil import copyfile, copytree

import pytest
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.__main__ import main
from ming.audience import Audience, scene
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.gazette import Gazette
from ming.month_steps.landing import Landing
from ming.month_steps.secrets import Secrets
from ming.month_steps.simulation import Simulations
from ming.month_steps.sources import Sources
from ming.middle.court import Court
from ming.middle.opening import CONTENT, build_opening
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"
CALLS = {agent.name: agent for agent in (
    scene, Audience.translation, Deliberations.agent, Gazette.agent, Landing.agent,
    Secrets.agent, Simulations.draft_agent, Simulations.final_agent,
    Sources.urgent, Sources.impeachment,
)}
HISTORY_ACTIONS = {
    "month": ({"action": "month"},),
    "night": ({"action": "open"}, {"action": "dismiss"}),
}


INVALID_NIGHT = json.loads((RECORDED / "night_invalid.json").read_text())["cases"][
    "missing_fields"
]
RECORDED_REPLIES = {
    "scene": INVALID_NIGHT["scene"],
    "NightDeclaration": INVALID_NIGHT["reply"],
    "Declaration": (RECORDED / "month_empty.txt").read_text(),
    "month_final": (RECORDED / "simulation.txt").read_text(),
    **{
        name: (RECORDED / "sources_empty.txt").read_text()
        for name in ("urgent", "impeachment")
    },
    **{
        name: (RECORDED / f"{name}.txt").read_text()
        for name in ("deliberation", "simulation", "gazette", "secret_report")
    },
}


class StepOverrides(UserDict):
    def __init__(self, stack):
        self.stack = stack
        super().__init__()

    def __setitem__(self, name, model):
        self.stack.enter_context(CALLS[name].override(model=model))
        super().__setitem__(name, model)


@contextmanager
def recorded_steps(case=None, start=0):
    with ExitStack() as stack, override_allow_model_requests(False), pytest.MonkeyPatch.context() as patch:
        replies = StepOverrides(stack)
        for name, text in RECORDED_REPLIES.items():
            replies[name] = TestModel(call_tools=[], custom_output_text=text)
        if case is not None:
            case = json.loads((RECORDED / f"night_{case}.json").read_text())
            replies["scene"] = replaying(
                [m for m in ModelMessagesTypeAdapter.validate_python(case["scene_responses"])
                 if isinstance(m, ModelResponse)] if "scene_responses" in case else
                [turn["scene"] for turn in case["turns"][start:]]
            )
            replies["NightDeclaration"] = replaying(case["replies"])
        if case is not None and "turns" in case:
            patch.setattr("ming.game.uuid4", iter(t["id"] for t in case["turns"][start:]).__next__)
        yield replies


@pytest.fixture
def steps(request):
    with recorded_steps(getattr(request, "param", None)) as replies:
        yield replies


@pytest.fixture(scope="session", autouse=True)
def opening_template_db(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(home))
        patch.setenv("USERPROFILE", str(home))
        patch.setenv("CODEX_HOME", str(home / ".codex"))
        patch.setenv("GROK_HOME", str(home / ".grok"))
        yield build_opening()


def opening_node(tmp_path_factory, variant=None):
    directory = tmp_path_factory.mktemp("opening")
    if variant is not None:
        content = copytree(CONTENT, directory / "content")
        opening = json.loads((content / "opening.json").read_text())
        if variant == "shortage":
            for account in opening["accounts"]:
                account["taels"] = 0
            config = json.loads((content / "fiscal_config.json").read_text())
            for item in config["items"]:
                if item["key"] in {"官俸_base", "宫廷_base"}:
                    item["value"] = {"官俸_base": 2000, "宫廷_base": 1000}[item["key"]]
            (content / "fiscal_config.json").write_text(json.dumps(config))
        elif variant == "two-payments-shortage":
            next(a for a in opening["accounts"] if a["name"] == "国库")["taels"] = 250000
        elif variant == "prestige":
            opening["world"][0]["imperial_prestige"] = 100
        else:
            opening["calendar"][0].update(year=variant, month=1)
        (content / "opening.json").write_text(json.dumps(opening))
        if variant == 1640:
            events = json.loads((content / "events.json").read_text())
            next(e for e in events if e["id"] == "jiao_levy_start_1637")[
                "terminal_reason"
            ] = "已准"
            (content / "events.json").write_text(json.dumps(events))
        template = build_opening(content, content / "opening.sqlite")
        court = Court.new_game(directory, template)
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
def opening_default(tmp_path_factory, opening_template_db):
    return opening_node(tmp_path_factory)


@pytest.fixture(scope="session")
def opening_shortage(tmp_path_factory, opening_template_db):
    return opening_node(tmp_path_factory, "shortage")


@pytest.fixture(scope="session")
def opening_two_payments_shortage(tmp_path_factory, opening_template_db):
    return opening_node(tmp_path_factory, "two-payments-shortage")


@pytest.fixture(scope="session")
def opening_prestige(tmp_path_factory, opening_template_db):
    return opening_node(tmp_path_factory, "prestige")


@pytest.fixture(scope="session")
def opening_1631(tmp_path_factory, opening_template_db):
    return opening_node(tmp_path_factory, 1631)


@pytest.fixture(scope="session")
def opening_1640(tmp_path_factory, opening_template_db):
    return opening_node(tmp_path_factory, 1640)


@pytest.fixture
def opening_db(request):
    # Only selection is parameterized. Immutable resource nodes never lose their
    # session lifetime when pytest switches away from, then back to an input.
    return request.getfixturevalue({
        None: "opening_default", "shortage": "opening_shortage",
        "two-payments-shortage": "opening_two_payments_shortage",
        "prestige": "opening_prestige", 1631: "opening_1631", 1640: "opening_1640",
    }[getattr(request, "param", None)])


@pytest.fixture(scope="session")
def first_night(opening_default, tmp_path_factory):
    return extend_history(
        opening_default, tmp_path_factory.mktemp("first-night"), ({"action": "open"},),
    )


@pytest.fixture(scope="session")
def shortage_first_night(opening_two_payments_shortage, tmp_path_factory):
    return extend_history(
        opening_two_payments_shortage, tmp_path_factory.mktemp("shortage-first-night"), ({"action": "open"},),
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
        assert client.get("/state").json()["game"]["petitions"] == []
    return path


@pytest.fixture(scope="session")
def rejected_month(rejected_night, tmp_path_factory):
    return extend_history(
        rejected_night, tmp_path_factory.mktemp("rejected-month"),
        ({"action": "month"},), case="approved",
    )


@pytest.fixture(scope="session")
def endorsed_month(rejected_month, tmp_path_factory):
    path = tmp_path_factory.mktemp("endorsed-month") / rejected_month.name
    copyfile(rejected_month, path)
    with recorded_steps("approved"), TestClient(create_app(path.parent)) as client:
        client.post("/actions", json={"action": "load", "save": path.name}).raise_for_status()
        petition = client.get("/state").json()["game"]["petitions"][0]
        client.post("/actions", json={"action": "choose", "petition": petition["id"], "option": 3}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["failure"], state["petitions"]) == (11, None, [])
    return path


def declared_night(source, tmp_path_factory, recording):
    case = json.loads((RECORDED / f"night_{recording}.json").read_text())
    return extend_history(
        source, tmp_path_factory.mktemp("declared-night"),
        [*({"action": "say", "words": words} for words in case["words"]), {"action": "dismiss"}],
        case=recording,
    )


@pytest.fixture(scope="session")
def payment_night(first_night, tmp_path_factory):
    return declared_night(first_night, tmp_path_factory, "payments")


@pytest.fixture(scope="session")
def county_night(first_night, tmp_path_factory):
    return declared_night(first_night, tmp_path_factory, "county")


@pytest.fixture(scope="session")
def travel_night(first_night, tmp_path_factory):
    return declared_night(first_night, tmp_path_factory, "travel")


@pytest.fixture(scope="session")
def shortage_payment_night(shortage_first_night, tmp_path_factory):
    return declared_night(shortage_first_night, tmp_path_factory, "payments")


@pytest.fixture(scope="session")
def two_nights(travel_night, tmp_path_factory):
    case = json.loads((RECORDED / "night_approved.json").read_text())
    return extend_history(
        travel_night, tmp_path_factory.mktemp("two-nights"),
        [{"action": "open"}, *({"action": "say", "words": words} for words in case["words"]), {"action": "dismiss"}],
        case="approved",
    )


@pytest.fixture(scope="session")
def secret_night(first_night, tmp_path_factory):
    case = json.loads((RECORDED / "night_secret.json").read_text())
    return extend_history(
        first_night,
        tmp_path_factory.mktemp("secret-night"),
        tuple({"action": "say", "words": words} for words in case["words"]),
        "secret",
    )


@pytest.fixture(scope="session")
def backing_offer(first_night, tmp_path_factory):
    case = json.loads((RECORDED / "night_endorsed.json").read_text())
    return extend_history(
        first_night, tmp_path_factory.mktemp("backing-offer"),
        [{"action": "say", "words": turn["emperor_words"]} for turn in case["turns"][:2]],
        case="endorsed",
    )


def finish_backing(backing_offer, tmp_path_factory, case):
    recording = json.loads((RECORDED / f"night_{case}.json").read_text())
    return extend_history(
        backing_offer, tmp_path_factory.mktemp(f"{case}-night"),
        [{"action": "say", "words": turn["emperor_words"]} for turn in recording["turns"][2:]],
        case=case, start=2,
    )


@pytest.fixture(scope="session")
def backed_night(backing_offer, tmp_path_factory):
    return finish_backing(backing_offer, tmp_path_factory, "endorsed")


@pytest.fixture(scope="session")
def double_backed_night(backing_offer, tmp_path_factory):
    return finish_backing(backing_offer, tmp_path_factory, "double")


@pytest.fixture(scope="session")
def interim_backed_night(backing_offer, tmp_path_factory):
    return finish_backing(backing_offer, tmp_path_factory, "interim")


def extend_history(source, directory, actions, case=None, start=0):
    path = directory / source.name
    copyfile(source, path)
    with recorded_steps(case, start) as replies, TestClient(create_app(directory)) as client:
        if case is None:
            replies["NightDeclaration"] = TestModel(
                call_tools=[],
                custom_output_text=(RECORDED / "night_empty.txt").read_text(),
            )
        client.post("/actions", json={"action": "load", "save": path.name})
        for action in actions:
            client.post("/actions", json=action).raise_for_status()
            client.portal.call(client.app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
    return path


def funded_month(opening_db, tmp_path_factory, name, account):
    path = tmp_path_factory.mktemp("funded-month") / opening_db.name
    copyfile(opening_db, path)
    declaration = {"facts": [{
        "entity_type": "affair", "entity": name, "create": True,
        "changes": [{"field": "monthly_funding", "value": {"amount": 500000, "account": account}}],
        "text": "每月拨五十万两",
    }]}
    with recorded_steps() as replies, TestClient(create_app(path.parent)) as client:
        replies["Declaration"] = TestModel(call_tools=[], custom_output_text=json.dumps(declaration, ensure_ascii=False))
        client.post("/actions", json={"action": "load", "save": path.name}).raise_for_status()
        client.post("/actions", json={"action": "month"}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["failure"]) == (11, None)
    return path


@pytest.fixture(scope="session")
def funded_affair(opening_default, tmp_path_factory):
    return funded_month(opening_default, tmp_path_factory, "陕西专款", "国库")


@pytest.fixture(scope="session")
def funded_army(opening_default, tmp_path_factory):
    return funded_month(opening_default, tmp_path_factory, "军饷", "国库")


@pytest.fixture(scope="session")
def funded_salary(opening_default, tmp_path_factory):
    return funded_month(opening_default, tmp_path_factory, "官俸_base", "国库")


@pytest.fixture(scope="session")
def funded_private_salary(opening_default, tmp_path_factory):
    return funded_month(opening_default, tmp_path_factory, "官俸_base", "内库")


@pytest.fixture(scope="session")
def pending_histories(request, tmp_path_factory):
    history = request.param
    actions = HISTORY_ACTIONS[history]
    node = request.getfixturevalue(
        "opening_default" if history == "month" else "first_night"
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
def audit(capsys):
    def read(db: Path, *, identity: str = "audit", replay: bool = False):
        capsys.readouterr()
        main(
            [
                "read",
                "--db",
                str(db),
                "--identity",
                identity,
                *(["--replay"] if replay else []),
            ]
        )
        return json.loads(capsys.readouterr().out)

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
