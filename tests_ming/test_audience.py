"""Medium, deterministic acceptance through the audience user and its read door."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ModelMessagesTypeAdapter
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from ming.audience import Audience
from ming.middle.court import Court
from tests_ming.test_court import physical_state, replaying


def test_nights_are_persistent_and_translate_only_after_dismissal(
    tmp_path: Path,
) -> None:
    case = json.loads(
        (Path(__file__).parent / "recorded/night_approved.json").read_text()
    )
    scene = replaying(
        [
            m
            for m in ModelMessagesTypeAdapter.validate_python(case["scene_responses"])
            if isinstance(m, ModelResponse)
        ]
    )

    async def play() -> None:
        court = Court.new_game(tmp_path, replaying(case["replies"]))
        audience = Audience(court, scene)
        first = audience.open()
        assert court.night(first).hall == ["王承恩"]
        await audience.say(case["words"][0])
        await audience.drain()
        assert court.night(first).closed is False
        assert court.night(first).result is None
        assert court.pending_nights() == []
        assert court.approved_decrees() == []
        path = court.db_path
        await audience.close()
        court = Court(path, replaying(case["replies"]))
        audience = Audience(court, scene)
        assert audience.open() == first
        assert len(court.night(first).turns) == 1
        for words in case["words"][1:]:
            await audience.say(words)
        assert court.night(first).closed is True  # The recorded scene called dismiss.
        await audience.drain()
        assert court.night(first).result == "translated"
        assert court.pending_nights() == []
        orders = court.approved_decrees()
        assert orders
        assert {e.id for e in orders} == {e.id for e in court.decrees(first)}
        assert all(
            set(e.data) == {"text", "origin", "people", "night_id"} for e in orders
        )
        history = court.read_person("徐光启").events
        assert any(e.get("decree", {}).get("origin") == "emperor" for e in history)
        events = [f.kind for f in court.facts("audit") if f.entity_id == first]
        assert events[-2:] == ["dismissed", "translated"]
        second = audience.open()
        assert first != second
        assert court.night(second).closed is False
        before = physical_state(court)
        await audience.close()
        court = Court(path, replaying([]))
        audience = Audience(court, replaying([]))
        assert audience.open() == second
        await audience.drain()
        assert physical_state(court) == before == physical_state(court, replay=True)
        assert {n.id for n in court.nights()} == {first, second}
        assert court.night(second).turns == []
        await audience.close()

    asyncio.run(play())


@pytest.mark.parametrize(
    "failure", [ConnectionError, UnexpectedModelBehavior, RuntimeError]
)
def test_call_failures_remain_pending_not_unhandled(
    tmp_path: Path, failure: type[Exception]
) -> None:
    case = json.loads(
        (Path(__file__).parent / "recorded/night_unknown_field.json").read_text()
    )

    def broken(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise failure("backend did not supply a declaration")

    async def play() -> None:
        court = Court.new_game(tmp_path, FunctionModel(broken))
        audience = Audience(court, replaying([case["scene"]]))
        night = audience.open()
        await audience.say(case["emperor_words"])
        audience.dismiss()
        with pytest.raises(failure):
            await audience.drain()
        assert court.night(night).result is None
        assert court.pending_nights() == [night]
        assert not [f for f in court.facts("audit") if f.kind == "unhandled"]
        with pytest.raises(failure):
            await audience.close()

    asyncio.run(play())


def test_scene_tools_use_physical_location_not_office_and_project_dossiers(
    tmp_path: Path,
) -> None:
    court = Court.new_game(tmp_path, TestModel())
    night = court.open_night()
    assert court.set_hall(night, ["杨嗣昌", "韩爌"], []).ok is True
    assert set(court.night(night).hall) == {"王承恩", "杨嗣昌", "韩爌"}
    assert court.set_hall(night, ["徐光启"], []).ok is False
    assert court.set_hall(night, ["张三"], []).ok is False
    assert set(court.night(night).hall) == {"王承恩", "杨嗣昌", "韩爌"}
    assert court.set_hall(night, [], ["杨嗣昌", "韩爌", "张三"]).ok is True
    assert court.night(night).hall == ["王承恩"]
    dossier = court.read_person("徐光启")
    assert dossier.found is True
    assert dossier.person["location"] == "nanzhili"
    assert dossier.person["status"] == "offstage"
    assert set(dossier.person) <= {
        "name",
        "office",
        "office_type",
        "office_region",
        "location",
        "status",
        "faction",
        "personal_skills",
        "style",
        "status_reason",
        "identity",
        "temperament",
        "motivation",
        "burden",
        "episode",
    }
    assert court.read_person("杨嗣昌").person["office"] == "户部郎中"
    assert court.read_person("张三").found is False
    court.close()


@pytest.mark.parametrize(
    "name",
    [
        "missing_fields",
        "unknown_field",
        "unknown_entity",
        "affair_field",
        "decree_field",
    ],
)
def test_failed_night_translation_is_terminal_and_reaches_following_nights(
    tmp_path: Path, name: str
) -> None:
    case = json.loads(
        (Path(__file__).parent / f"recorded/night_{name}.json").read_text()
    )

    async def play() -> None:
        court = Court.new_game(tmp_path, replaying(case["replies"]))
        audience = Audience(court, replaying([case["scene"]]))
        night = audience.open()
        before_world = [e for e in physical_state(court) if e["kind"] != "night"]
        await audience.say(case["emperor_words"])
        audience.dismiss()
        await audience.drain()
        assert court.night(night).result == "unhandled"
        assert court.pending_nights() == []
        assert [
            e for e in physical_state(court) if e["kind"] != "night"
        ] == before_world
        assert court.facts("emperor")[-1].detail == {}
        second = audience.open()
        material = court.scene_material()
        assert set(material) == {"date", "gazette", "unhandled"}
        assert material["unhandled"] == [{"kind": "unhandled", "night_id": str(night)}]
        before = physical_state(court)
        facts = [(f.entity_id, f.kind) for f in court.facts("audit")]
        path = court.db_path
        await audience.close()
        court = Court(path, replaying([]))
        audience = Audience(court, replaying([]))
        assert audience.open() == second
        await audience.drain()
        assert court.night(night).result == "unhandled"
        assert physical_state(court) == before == physical_state(court, replay=True)
        assert [
            (f.entity_id, f.kind) for f in court.facts("audit", replay=True)
        ] == facts
        await audience.close()

    asyncio.run(play())
