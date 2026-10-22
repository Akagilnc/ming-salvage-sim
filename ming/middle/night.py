"""Persistent audience records, owned by the same entity/event ledger."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ming.ledger import Entity, Item, Ledger
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


def read_night(ledger: Ledger, night_id: UUID) -> NightView:
    night = ledger.entities(entity_id=night_id, query=NIGHT_ROWS)[0]
    date = ledger.entities(kind="calendar")[0]["data"]
    turns: list[TurnView] = []
    hall: list[str] = list(INITIAL_HALL)
    for item in ledger.facts(entity_id=night_id, kind=("turn", "hall")):
        detail = item["detail"]
        if item["kind"] == "hall":
            hall = change_hall(hall, detail["add"], detail["remove"])
        else:
            turns.append(
                TurnView(**detail, emperor_words=item["emperor_words"], hall=hall)
            )
    return NightView(
        id=night_id,
        **night["data"],
        date={"year": date["year"], "month": date["month"]},
        turns=turns,
        result=night["result"],
    )


def known_people(ledger: Ledger, decree: Item) -> set[str]:
    data = decree["data"]
    night = read_night(ledger, UUID(data["night_id"]))
    return set(data["people"]) | set(night.turns[int(data["turn"]) - 1].hall)


def open_night(ledger: Ledger) -> UUID:
    for row in ledger.read(LATEST_NIGHT):
        if not row["data"]["closed"]:
            return row["id"]
    night = Entity("night", str(uuid4()), "", {"closed": False, "hall": list(INITIAL_HALL)})
    ledger.commit([night])
    return night.id


def dismiss(ledger: Ledger, night_id: UUID) -> None:
    night = ledger.get(night_id)
    if not night.data["closed"]:
        night.record("dismissed", "", {}, {"closed": True})
        ledger.commit([night])
