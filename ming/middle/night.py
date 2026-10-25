"""Persistent audience records, owned by the same entity/event ledger."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, literal, or_, select

from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, FACT_ROWS, Entity, Item, Ledger
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


def known_people(ledger: Ledger, decree: Item) -> set[str]:
    data = decree["data"]
    night_id = UUID(data["night_id"])
    turn = ledger.facts(entity_id=night_id, kind="turn", query=FACT_ROWS.with_only_columns(F.position)
                        .order_by(None).order_by(F.position).offset(int(data["turn"]) - 1).limit(1))[0]
    turns = hall_history(ledger.facts(entity_id=night_id, kind=("turn", "hall"),
                                      query=FACT_ROWS.where(F.position <= turn["position"])))
    return set(data["people"]) | set(turns[-1].hall)


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
