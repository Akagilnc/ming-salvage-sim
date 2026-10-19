"""Medium (SQLite): the common landing door, not the removed Assign/Grant schema."""

import asyncio
import json
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ming.audience import Audience
from ming.middle.court import Court


def replaying(replies: list[str]) -> FunctionModel:
    remaining = iter(replies)

    def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(next(remaining))])

    return FunctionModel(reply)


def physical_state(court: Court, replay: bool = False) -> list[dict[str, object]]:
    fields = {
        "office",
        "office_region",
        "location",
        "status",
        "origin",
        "stance",
        "night_id",
        "turn_id",
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


def test_common_declaration_updates_entities_and_displaces_incumbent_atomically(
    tmp_path: Path,
) -> None:
    # The sole schema-only example (#1943): landing, not the model's reading of prose.
    reply = json.dumps(
        {
            "decrees": [],
            "assents": [],
            "segments": [],
            "protagonist": None,
            "dismiss": False,
            "facts": [
                {
                    "entity_type": "person",
                    "entity": "洪承畴",
                    "create": False,
                    "changes": [
                        {"field": "office", "value": "巡抚"},
                        {"field": "office_region", "value": "shaanxi"},
                        {"field": "status", "value": "active"},
                    ],
                    "text": "特旨钦命。",
                },
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
    scene = json.loads(
        (Path(__file__).parent / "recorded/turn_dismiss.json").read_text()
    )["scene"]

    async def play() -> None:
        audience = Audience(court, replaying([scene]))
        audience.open()
        await audience.say("任命洪承畴为陕西巡抚，调银三十万两赈灾。")
        await audience.drain()

    asyncio.run(play())
    people = {e.key: e for e in court.entities("audit") if e.kind == "person"}
    assert people["洪承畴"].data["office"] == "巡抚"
    assert people["洪承畴"].data["location"] == "shaanxi"
    assert people["练国事"].data["status"] == "offstage"
    assert people["练国事"].data["office"] == ""
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
