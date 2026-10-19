"""Medium (SQLite): the common landing door, not the removed Assign/Grant schema."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ming.audience import Audience
from ming.middle.court import Court


def replaying(replies: list[str] | list[ModelResponse]) -> FunctionModel:
    remaining = iter(replies)

    def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        result = next(remaining)
        return (
            result
            if isinstance(result, ModelResponse)
            else ModelResponse(parts=[TextPart(result)])
        )

    return FunctionModel(reply)


def physical_state(court: Court, replay: bool = False) -> list[dict[str, object]]:
    fields = {
        "office",
        "office_region",
        "location",
        "status",
        "origin",
        "night_id",
        "closed",
        "hall",
    }
    return [
        {
            "id": e.id,
            "kind": e.kind,
            "key": e.key,
            "state": {k: v for k, v in e.data.items() if k in fields},
        }
        for e in court.entities("audit", replay)
    ]


@pytest.mark.parametrize(
    ("appointee", "changes", "incumbent_status"),
    [
        ("洪承畴", [{"office": "巡抚"}], "offstage"),
        (
            "洪承畴",
            [{"office": "巡抚", "office_region": "shaanxi", "status": "active"}],
            "offstage",
        ),
        ("李待问", [{"office_region": "shaanxi"}], "offstage"),
        ("李待问", [{"office": "巡抚"}, {"office_region": "shaanxi"}], "offstage"),
        ("李待问", [{"office_region": "shaanxi"}, {"office": "巡抚"}], "offstage"),
        ("李待问", [{"office": "", "office_region": "shaanxi"}], "active"),
        ("李待问", [{"office": ""}, {"office_region": "shaanxi"}], "active"),
        ("洪承畴", [{"location": "beizhili"}], "active"),
    ],
    ids=[
        "office-only",
        "combined",
        "region-only",
        "office-then-region",
        "region-then-office",
        "clear-office",
        "empty-office-then-region",
        "location-only",
    ],
)
def test_common_declaration_updates_entities_and_displaces_incumbent_atomically(
    tmp_path: Path,
    appointee: str,
    changes: list[dict[str, str]],
    incumbent_status: str,
) -> None:
    # The sole schema-only example (#1943): landing, not the model's reading of prose.
    reply = json.dumps(
        {
            "decrees": [],
            "facts": [
                *[
                    {
                        "entity_type": "person",
                        "entity": appointee,
                        "create": False,
                        "changes": [
                            {"field": field, "value": value}
                            for field, value in fields.items()
                        ],
                        "text": "特旨钦命。",
                    }
                    for fields in changes
                ],
                {
                    "entity_type": "person",
                    "entity": "徐光启",
                    "create": False,
                    "changes": [
                        {"field": "office", "value": "内阁大学士"},
                        {"field": "status", "value": "active"},
                    ],
                    "text": "起复入阁。",
                },
                {
                    "entity_type": "person",
                    "entity": "徐光启",
                    "create": False,
                    "changes": [{"field": "office_region", "value": "shaanxi"}],
                    "text": "任职地区变更。",
                },
                {
                    "entity_type": "person",
                    "entity": "徐光启",
                    "create": False,
                    "changes": [{"field": "office_region", "value": ""}],
                    "text": "任职地区变更。",
                },
                {
                    "entity_type": "affair",
                    "entity": "陕西赈灾",
                    "create": True,
                    "changes": [],
                    "text": "调银三十万两赈灾。",
                },
            ],
        },
        ensure_ascii=False,
    )
    court = Court.new_game(tmp_path, replaying([reply]))
    expected = dict(court.read_person(appointee).person)
    for fields in changes:
        expected.update(fields)
    scene = json.loads(
        (Path(__file__).parent / "recorded/night_unknown_field.json").read_text()
    )["scene"]

    async def play() -> None:
        audience = Audience(court, replaying([scene]))
        night = audience.open()
        before = physical_state(court)
        await audience.say("任命洪承畴为陕西巡抚，调银三十万两赈灾。")
        assert [e for e in physical_state(court) if e["kind"] != "night"] == [
            e for e in before if e["kind"] != "night"
        ]
        audience.dismiss()
        await audience.drain()
        assert court.night(night).result == "translated"

    asyncio.run(play())
    people = {e.key: e for e in court.entities("audit") if e.kind == "person"}
    assert court.read_person(appointee).person == expected
    assert people["练国事"].data["status"] == incumbent_status
    assert people["练国事"].data["office"] == (
        "" if incumbent_status == "offstage" else "巡抚"
    )
    assert people["徐光启"].data["status"] == "active"
    assert people["徐光启"].data["location"] == "nanzhili"
    assert people["张瑞图"].data["office"] == "内阁大学士"
    assert [e.key for e in court.entities("audit") if e.kind == "affair"] == [
        "陕西赈灾"
    ]
    before = physical_state(court)
    facts = [(f.entity_id, f.kind) for f in court.facts("audit")]
    path = court.db_path
    court.close()
    court = Court(path, replaying([]))
    assert physical_state(court) == before == physical_state(court, replay=True)
    assert [(f.entity_id, f.kind) for f in court.facts("audit")] == facts
    assert [(f.entity_id, f.kind) for f in court.facts("audit", replay=True)] == facts
    court.close()
