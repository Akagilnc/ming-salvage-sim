"""Persistent audience records, owned by the same entity/event ledger."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import CompoundSelect, Select, func, literal, or_, select, true, union_all
from sqlalchemy.sql.elements import ColumnElement

from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, Entity, Item, Ledger
from ming.middle.calendar import calendar_row
from ming.middle.queries import LATEST_NIGHT, NIGHT_ROWS

INITIAL_HALL = ("王承恩",)


class TurnView(BaseModel):
    id: str
    emperor_words: str
    scene: str
    hall: list[str]


class NightView(BaseModel):
    id: UUID
    closed: bool
    hall: list[str]
    date: dict[str, int]
    turns: list[TurnView] = Field(default_factory=list[TurnView])
    result: Literal["translated", "unhandled"] | None = None


def change_hall(hall: list[str], add: list[str], remove: list[str]) -> list[str]:
    return list(dict.fromkeys(p for p in hall + add if p not in remove))


def hall_history(events: list[Item]) -> list[TurnView]:
    turns: list[TurnView] = []
    # A turn is recorded after its scene, whose hall changes come first; the
    # turn's hall is the one present when the emperor spoke, before that scene.
    hall: list[str] = list(INITIAL_HALL)
    spoken = hall
    for item in events:
        detail = item["detail"]
        if item["kind"] == "hall":
            hall = change_hall(hall, detail["add"], detail["remove"])
        else:
            turns.append(
                TurnView(**detail, emperor_words=item["emperor_words"], hall=spoken)
            )
            spoken = hall
    return turns


def read_night(ledger: Ledger, night_id: UUID) -> NightView:
    night = ledger.entities(entity_id=night_id, query=NIGHT_ROWS)[0]
    turns = hall_history(ledger.facts(entity_id=night_id, kind=("turn", "hall")))
    return NightView(
        id=night_id,
        **night["data"],
        turns=turns,
        result=night["result"],
    )


def witnessed_nights(people: list[str], query: Select[Any]) -> Select[Any]:
    added = func.json_each(F.detail["add"]).table_valued("value")
    removed = func.json_each(F.detail["remove"]).table_valued("value")
    return query.where(E.kind == "night", or_(
        literal(bool(set(INITIAL_HALL).intersection(people))),
        select(F.position).where(
            F.entity_id == E.id, F.kind == "hall",
            select(added.c.value).where(
                added.c.value.in_(people),
                ~select(removed.c.value).where(removed.c.value == added.c.value).exists(),
            ).exists(),
        ).correlate(E.id.table).exists(),
    ))


def known_people(data: ColumnElement[Any], people: list[str] | None = None) -> CompoundSelect[Any]:
    """Declared handlers and the hall before the approval turn's scene changes."""
    night_id = func.replace(data["night_id"].as_string(), "-", "")
    turn = F.position.table.alias().c
    turns = select(turn.position, func.row_number().over(order_by=turn.position).label("number")).where(
        turn.entity_id == night_id, turn.kind == "turn",
    ).correlate_except(turn.position.table).subquery()
    boundary = select(turns.c.position).where(
        turns.c.number == data["turn"].as_integer() - 1,
    ).correlate_except(turns).scalar_subquery()
    hall = F.position.table.alias().c
    added = func.json_each(hall.detail["add"]).table_valued("value")
    candidates = union_all(
        *(select(literal(person).label("person"), literal(0).label("position")) for person in INITIAL_HALL),
        select(added.c.value.label("person"), hall.position).select_from(
            hall.position.table.join(added, true()),
        ).where(hall.entity_id == night_id, hall.kind == "hall", hall.position <= boundary)
        .correlate_except(hall.position.table, added),
    ).subquery()
    removed = func.json_each(hall.detail["remove"]).table_valued("value")
    absent = select(hall.position).where(
        hall.entity_id == night_id, hall.kind == "hall",
        hall.position >= candidates.c.position, hall.position <= boundary,
        select(removed.c.value).where(removed.c.value == candidates.c.person).correlate_except(removed).exists(),
    ).correlate_except(hall.position.table)
    attendees = select(candidates.c.person).where(
        or_(candidates.c.position == 0, candidates.c.position <= boundary), ~absent.exists(),
    ).correlate_except(candidates)
    assigned = func.json_each(data["people"]).table_valued("value")
    declared = select(assigned.c.value.label("person")).correlate_except(assigned)
    if people is not None:
        declared = declared.where(assigned.c.value.in_(people))
        attendees = attendees.where(candidates.c.person.in_(people))
    return declared.union(attendees)


def open_night(ledger: Ledger) -> UUID:
    for row in ledger.read(LATEST_NIGHT):
        if not row["data"]["closed"]:
            return row["id"]
    date = calendar_row(ledger)["data"]
    night = Entity(
        "night", str(uuid4()), "", {"closed": False, "hall": list(INITIAL_HALL), "date": {k: date[k] for k in ("year", "month")}}
    )
    ledger.commit([night])
    return night.id


def dismiss(ledger: Ledger, night_id: UUID) -> None:
    night = ledger.get(night_id)
    if not night.data["closed"]:
        night.record("dismissed", "", {}, {"closed": True})
        ledger.commit([night])
