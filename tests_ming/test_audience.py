"""Medium, deterministic acceptance through the audience user and its read door."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from ming.audience import Audience
from ming.middle.court import Court
from tests_ming.test_court import physical_state, replaying


def test_nights_are_persistent_and_dismissal_does_not_create_orders(
    tmp_path: Path,
) -> None:
    case = json.loads(
        (Path(__file__).parent / "recorded/turn_dismiss.json").read_text()
    )

    async def play() -> None:
        court = Court.new_game(tmp_path, replaying(case["replies"]))
        audience = Audience(court, replaying([case["scene"]]))
        first = audience.open()
        assert court.night(first).closed is False
        assert court.night(first).hall == ["王承恩"]
        await audience.say(case["emperor_words"])
        await audience.drain()
        assert court.night(first).closed is True
        audience.dismiss()
        second = audience.open()
        assert first != second
        assert court.night(first).closed is True
        assert court.night(second).closed is False
        path = court.db_path
        await audience.close()
        court = Court(path, TestModel())
        audience = Audience(court, TestModel())
        assert audience.open() == second
        assert {n.id for n in court.nights()} == {first, second}
        assert court.night(second).turns == []
        assert not [e for e in court.entities("audit") if e.kind == "decree"]
        await audience.close()

    asyncio.run(play())


@pytest.mark.parametrize(
    "failure", [ConnectionError, UnexpectedModelBehavior, RuntimeError]
)
def test_call_failures_remain_pending_not_unhandled(
    tmp_path: Path, failure: type[Exception]
) -> None:
    case = json.loads((Path(__file__).parent / "recorded/turn_summon.json").read_text())

    def broken(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise failure("backend did not supply a declaration")

    async def play() -> None:
        court = Court.new_game(tmp_path, FunctionModel(broken))
        audience = Audience(court, replaying([case["scene"]]))
        night = audience.open()
        await audience.say(case["emperor_words"])
        with pytest.raises(failure):
            await audience.drain()
        assert court.night(night).turns[0].result is None
        assert court.pending_turns()
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
    "name,unhandled",
    [
        ("turn_summon", False),
        ("turn_bad_offsets", True),
        ("turn_bad_offsets", False),
        ("turn_missing_fields", True),
        ("turn_unknown_field", True),
        ("turn_unknown_entity", True),
    ],
)
def test_each_scene_round_survives_reopening_and_failed_translation(
    tmp_path: Path, name: str, unhandled: bool
) -> None:
    following = json.loads(
        (Path(__file__).parent / "recorded/turn_summon.json").read_text()
    )
    case = following | json.loads(
        (Path(__file__).parent / f"recorded/{name}.json").read_text()
    )

    async def play() -> None:
        replies = (
            [case["replies"][0]] * 2 + following["replies"]
            if unhandled
            else case["replies"]
        )
        court = Court.new_game(tmp_path, replaying(replies))
        audience = Audience(court, replaying([case["scene"], following["scene"]]))
        night = audience.open()
        before_world = [e for e in physical_state(court) if e["kind"] != "night"]
        await audience.say(case["emperor_words"])
        await audience.drain()
        (turn,) = court.night(night).turns
        assert turn.unhandled is unhandled
        assert turn.result is not None
        if not unhandled:
            orders = court.decrees(night)
            history = court.read_person(
                "毕自严" if name == "turn_summon" else "徐光启"
            ).events
            assert any(
                e.get("decree", {}).get("origin") == "emperor"
                and e["decree"]["stance"] == "approved"
                for e in history
            )
            petition = next(e for e in orders if e.data["origin"] == "minister")
            assert petition.data["stance"] == "unanswered"
            assert petition.id not in {e.id for e in court.approved_decrees()}
            audience.dismiss()
            assert petition.id in {e.id for e in court.approved_decrees()}
            assert (
                next(e for e in court.decrees(night) if e.id == petition.id).data[
                    "stance"
                ]
                == "unanswered"
            )
        else:
            assert turn.result == {"kind": "unhandled"}
            assert [
                e for e in physical_state(court) if e["kind"] != "night"
            ] == before_world
            assert court.facts("emperor")[-1].detail == {}
            material = court.scene_material(night)
            assert set(material) == {"date", "gazette", "unhandled"}
            assert material["unhandled"] == [{"kind": "unhandled", "turn_id": turn.id}]
            await audience.say(following["emperor_words"])
            await audience.drain()
            assert court.night(night).turns[-1].unhandled is False
        turns = [(t.id, t.unhandled, t.result) for t in court.night(night).turns]
        before = physical_state(court)
        facts = [(f.entity_id, f.kind) for f in court.facts("audit")]
        path = court.db_path
        await audience.close()
        court = Court(path, replaying([]))
        audience = Audience(court, replaying([]))
        if unhandled:
            assert audience.open() == night
        await audience.drain()
        assert [
            (t.id, t.unhandled, t.result) for t in court.night(night).turns
        ] == turns
        assert physical_state(court) == before == physical_state(court, replay=True)
        assert [(f.entity_id, f.kind) for f in court.facts("audit")] == facts
        assert [
            (f.entity_id, f.kind) for f in court.facts("audit", replay=True)
        ] == facts
        await audience.close()

    asyncio.run(play())
