"""Medium (SQLite): the common landing door, not the removed Assign/Grant schema."""

import asyncio
import json
from pathlib import Path
from collections.abc import AsyncIterator, Callable, Sequence

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel, DeltaToolCall

from starlette.testclient import TestClient
from ming.web import create_app
from ming.middle.court import Court
from ming.middle.declaration import Declaration
from ming.middle.view import Officials

RECORDED = Path(__file__).parent / "recorded"


def replaying(
    replies: Sequence[str | ModelResponse | Exception]
    | Callable[[list[ModelMessage]], str | ModelResponse | Exception],
    received: list[ModelMessage] | None = None,
) -> FunctionModel:
    remaining = iter(replies) if not callable(replies) else iter(())

    async def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # Use FunctionModel's native async callback, not competing worker threads
        # consuming the same recorded sequence.
        if received is not None:
            received.extend(_messages)
        result = replies(_messages) if callable(replies) else next(remaining)
        if isinstance(result, Exception):
            raise result
        return (
            result
            if isinstance(result, ModelResponse)
            else ModelResponse(parts=[TextPart(result)])
        )

    async def stream_response(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for index, part in enumerate((await reply(messages, info)).parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name,
                        json_args=part.args_as_json_str(),
                        tool_call_id=part.tool_call_id,
                    )
                }

    return FunctionModel(reply, stream_function=stream_response)


def physical_state(court: Court) -> list[dict[str, object]]:
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
        for e in court.entities("audit")
    ]


@pytest.mark.parametrize(
    ("appointee", "changes", "incumbent_status", "office_status"),
    [
        ("洪承畴", [{"office": "巡抚"}], "offstage", "active"),
        ("洪承畴", [{"office": "巡抚"}], "offstage", "offstage"),
        (
            "洪承畴",
            [{"office": "巡抚", "office_region": "陕西", "status": "active"}],
            "offstage",
            "active",
        ),
        ("李待问", [{"office_region": "陕西"}], "offstage", "active"),
        (
            "李待问",
            [{"office": "巡抚"}, {"office_region": "陕西"}],
            "offstage",
            "active",
        ),
        (
            "李待问",
            [{"office_region": "陕西"}, {"office": "巡抚"}],
            "offstage",
            "active",
        ),
        ("李待问", [{"office": "", "office_region": "陕西"}], "active", "active"),
        ("李待问", [{"office": ""}, {"office_region": "陕西"}], "active", "active"),
        ("洪承畴", [{"location": "北直隶 / 京师"}], "active", "active"),
        (
            "洪承畴",
            [{"location": "北直隶 / 京师", "travel_speed": 1.5}],
            "active",
            "active",
        ),
        ("李待问", [{"location": "北直隶 / 京师"}], "active", "active"),
    ],
    ids=[
        "office-only",
        "inactive-office",
        "combined",
        "region-only",
        "office-then-region",
        "region-then-office",
        "clear-office",
        "empty-office-then-region",
        "location-only",
        "expedited-journey",
        "first-known-location",
    ],
)
@pytest.mark.parametrize("game_db", ["first_night"], indirect=True)
def test_common_declaration_updates_entities_and_displaces_incumbent_atomically(
    game_db: Path,
    appointee: str,
    changes: list[dict[str, str | float]],
    incumbent_status: str,
    office_status: str,
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
                        "affair": "陕西赈灾",
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
                    "affair": "陕西赈灾",
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
                    "changes": [{"field": "office_region", "value": "陕西"}],
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
                    "entity_type": "person",
                    "entity": "徐光启",
                    "create": False,
                    "changes": [
                        {"field": "office", "value": "户部尚书"},
                        {"field": "status", "value": office_status},
                    ],
                    "text": "钦命户部尚书。",
                },
                {
                    "entity_type": "army",
                    "entity": "京营",
                    "affair": "陕西赈灾",
                    "create": False,
                    "changes": [
                        {"field": "firearm_equipment", "value": 120},
                        {"field": "cannon_equipment", "value": -2},
                    ],
                    "text": "军器交割。",
                },
                {
                    "entity_type": "affair",
                    "entity": "陕西赈灾",
                    "create": True,
                    "changes": [],
                    "text": "调银三十万两赈灾。",
                },
                {
                    "entity_type": "account",
                    "entity": "国库",
                    "create": False,
                    "changes": [
                        {
                            "field": "taels",
                            "value": -1000,
                            "counterpart": {
                                "entity_type": "person",
                                "entity": "徐光启",
                            },
                        }
                    ],
                    "text": "赐徐光启银一千两。",
                },
            ],
            "reports": [
                {
                    "entity_type": "person",
                    "entity": "徐光启",
                    "text": "徐光启具疏谢恩。",
                    "audience": "public",
                }
            ],
        },
        ensure_ascii=False,
    )
    court = Court(game_db, replaying([reply, reply]))
    assert asyncio.run(
        court.read_records(Officials(people=["郭允厚"]), "account", "国库")
    )["entities"]
    for name in ("徐光启", "韩爌", "王承恩"):
        assert (
            asyncio.run(court.read_records(Officials(people=[name]), "account"))[
                "entities"
            ]
            == []
        )
    expected = dict(court.read_person(appointee).person)
    for fields in changes:
        expected.update(fields)
    if appointee == "洪承畴" and any("location" in fields for fields in changes):
        speed = expected.pop("travel_speed", 1)
        expected.update(
            location="陕西",
            transit_to="北直隶 / 京师",
            status="active",
            waiting_audience=False,
            journey={
                "elapsed_months": 0,
                "total_months": 2.4 / speed,
                **({"pace": "加急"} if speed > 1 else {}),
            },
        )
    scene = json.loads(
        (Path(__file__).parent / "recorded/night_invalid.json").read_text()
    )["cases"]["unknown_field"]["scene"]

    app = create_app(game_db.parent)
    with TestClient(app) as client:
        client.post("/actions", json={"action": "load", "save": court.db_path.name})
        audience = app.state.web.game.audience
        with (
            audience.scene.override(model=replaying([scene])),
            audience.translation.override(model=replaying([reply, reply])),
        ):
            before = physical_state(court)
            client.post(
                "/actions",
                json={
                    "action": "say",
                    "words": "任命洪承畴为陕西巡抚，调银三十万两赈灾。",
                },
            )
            assert [e for e in physical_state(court) if e["kind"] != "night"] == [
                e for e in before if e["kind"] != "night"
            ]
            client.post("/actions", json={"action": "dismiss"})
            client.post("/actions", json={"action": "load", "save": court.db_path.name})
            assert (
                client.get("/state").json()["game"]["night"]["result"] == "translated"
            )
    people = {e.key: e for e in court.entities("audit") if e.kind == "person"}
    assert court.read_person(appointee).person == expected
    if any("location" in fields for fields in changes):
        if appointee == "洪承畴":
            assert people[appointee].data["remaining_distance"] == 2.4
            assert people[appointee].data["travel_speed"] == speed
            assert [
                (
                    e.data["journey"],
                    {"remaining_distance", "travel_speed"} & e.data.keys(),
                )
                for e in court.entities("world")
                if e.id == people[appointee].id
            ] == [(expected["journey"], set())]
        else:
            assert "transit_to" not in people[appointee].data
    assert people["练国事"].data["status"] == incumbent_status
    assert people["练国事"].data["office"] == (
        "" if incumbent_status == "offstage" else "巡抚"
    )
    assert people["徐光启"].data["status"] == office_status
    assert people["徐光启"].data["location"] == "南直隶 / 南京"
    assert people["郭允厚"].data["office"] == ""
    assert people["郭允厚"].data["status"] == "offstage"
    assert [
        (e["date"], e["successor"])
        for e in court.read_person("郭允厚").events
        if e["kind"] == "displaced"
    ] == [(court.calendar().data, "徐光启")]
    assert {
        e["kind"]: e["date"]
        for e in court.read_person("徐光启").events
        if e["kind"] in ("reported", "received")
    } == {"reported": court.calendar().data, "received": court.calendar().data}
    for identity, names in (
        (Officials(people=["徐光启"]), ["国库"] if office_status == "active" else []),
        (Officials(people=["郭允厚"]), []),
        (
            Officials(people=["徐光启", "郭允厚", "王承恩"]),
            ["国库"] if office_status == "active" else [],
        ),
    ):
        assert [
            e["key"]
            for e in asyncio.run(court.read_records(identity, "account"))["entities"]
        ] == names
    assert people["张瑞图"].data["office"] == "内阁大学士"
    army = next(
        e for e in court.entities("audit") if e.kind == "army" and e.key == "京营"
    )
    assert (army.data["firearm_equipment"], army.data["cannon_equipment"]) == (100, 0)
    assert [e.key for e in court.entities("audit") if e.kind == "affair"] == [
        "陕西赈灾"
    ]
    affair = next(e for e in court.entities("audit") if e.kind == "affair")
    associated = [f for f in court.facts("audit") if f.detail.get("affair_id")]
    expected_entities = {people[appointee].id, people["徐光启"].id, army.id}
    if incumbent_status == "offstage":
        expected_entities.add(people["练国事"].id)
    assert {f.entity_id for f in associated} == expected_entities
    assert all(f.detail["affair_id"] == str(affair.id) for f in associated)
    assert all(
        f.detail["origin_ref"] == str(n.id) for f in associated for n in court.nights()
    )
    before = physical_state(court)
    facts = court.facts("audit")
    path = court.db_path
    court.close()
    court = Court(path, replaying([]))
    assert physical_state(court) == before
    assert court.facts("audit") == facts
    court.close()


@pytest.mark.parametrize(
    "reply",
    ["northstar_b_1169.txt", "northstar_c_717.txt"],
    ids=["B-1169", "C-717"],
)
def test_recorded_world_month_reply_lands(tmp_path: Path, reply: str) -> None:
    text = (RECORDED / reply).read_text()
    court = Court.new_game(tmp_path, replaying([text, text]))
    if reply == "northstar_b_1169.txt":
        court.record(("affair", "白水王二起事"), [])
    source = court.calendar().id
    result = asyncio.run(
        court.translate(court.translation_agent(Declaration), "", source)
    )
    court.land(result, source, monthly="landed")
    kinds = [fact.kind for fact in court.facts("audit", entity_id=source)]
    assert "landed" in kinds and "unhandled" not in kinds
    court.close()


@pytest.mark.parametrize(
    "reply",
    ["r2_b_1136.txt", "r2_d_withdrawn_986.txt", "r2_d_1017.txt", "speed"],
    ids=["B-1136", "D-withdrawn-986", "D-1017", "speed"],
)
def test_recorded_r2_reply_lands(tmp_path: Path, reply: str) -> None:
    text = (
        json.dumps(
            {
                "facts": [
                    {
                        "entity_type": "person",
                        "entity": "洪承畴",
                        "create": False,
                        "changes": [{"field": "travel_speed", "value": 3}],
                        "text": "行速。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        if reply == "speed"
        else (RECORDED / reply).read_text()
    )
    second = (
        text.replace('"兵部尚书"', '"兵部尚书,左都御史"')
        if reply == "r2_d_1017.txt"
        else text
    )
    court = Court.new_game(tmp_path, replaying([text, second]))
    if "关宁补饷" in text:
        court.record(("affair", "关宁补饷"), [])
    source = court.calendar().id
    result = asyncio.run(
        court.translate(court.translation_agent(Declaration), "", source)
    )
    court.land(result, source, monthly="landed")
    kinds = [fact.kind for fact in court.facts("audit", entity_id=source)]
    assert "landed" in kinds and "unhandled" not in kinds
    rows = {(entity.kind, entity.key): entity for entity in court.entities("audit")}
    if reply == "r2_b_1136.txt":
        person = rows[("person", "洪承畴")]
        assert (person.data["office"], person.data["office_region"]) == ("巡抚", "陕西")
        appointed = [
            fact
            for fact in court.facts("audit", entity_id=person.id)
            if fact.kind == "changed" and fact.detail["nominal"].get("office") == "陕西巡抚"
        ]
        assert appointed[-1].detail["actual"]["office"] == "巡抚"
        assert appointed[-1].detail["actual"]["office_region"] == "陕西"
    elif reply == "r2_d_withdrawn_986.txt":
        region = rows[("region", "陕西")]
        assert "arrears" not in region.data and "month_paid" not in region.data
        assert "专项" in [
            fact.detail["purpose"]
            for fact in court.facts("audit", entity_id=region.id)
            if fact.kind == "received"
        ]
    elif reply == "r2_d_1017.txt":
        assert rows[("person", "崔呈秀")].data["office"] == "兵部尚书,左都御史"
        building = rows[("building", "锦州卫军器局")]
        assert "arrears" not in building.data
        assert "专项" in [
            fact.detail["purpose"]
            for fact in court.facts("audit", entity_id=building.id)
            if fact.kind == "received"
        ]
    else:
        person = rows[("person", "洪承畴")]
        assert person.data["travel_speed"] == 2
        changed = [
            fact
            for fact in court.facts("audit", entity_id=person.id)
            if fact.kind == "changed"
        ]
        assert changed[-1].detail["nominal"]["travel_speed"] == 3
        assert changed[-1].detail["actual"]["travel_speed"] == 2
    court.close()
