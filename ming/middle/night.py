"""Persistent audience records, owned by the same entity/event ledger."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ming.ledger import Entity, Ledger


class TurnView(BaseModel):
    id: str
    emperor_words: str
    scene: str


class NightView(BaseModel):
    id: UUID
    closed: bool
    hall: list[str]
    date: dict[str, int]
    turns: list[TurnView] = Field(default_factory=list[TurnView])
    result: Literal["translated", "unhandled"] | None = None


def read_night(ledger: Ledger, night_id: UUID) -> NightView:
    night = ledger.entities(entity_id=night_id)[0]
    date = ledger.entities(kind="calendar")[0]["data"]
    turns: list[TurnView] = []
    result = None
    for item in ledger.facts(entity_id=night_id):
        detail = item["detail"]
        if item["kind"] == "turn":
            turns.append(TurnView(**detail, emperor_words=item["emperor_words"]))
        elif item["kind"] == "translated":
            result = "translated"
        elif item["kind"] == "unhandled":
            result = "unhandled"
    return NightView(
        id=night_id,
        **night["data"],
        date={"year": date["year"], "month": date["month"]},
        turns=turns,
        result=result,
    )


def open_night(ledger: Ledger) -> UUID:
    for row in ledger.entities(kind="night", night="latest"):
        if row["kind"] == "night" and not row["data"]["closed"]:
            return row["id"]
    night = Entity("night", str(uuid4()), "", {"closed": False, "hall": ["王承恩"]})
    ledger.commit([night])
    return night.id


def dismiss(ledger: Ledger, night_id: UUID) -> None:
    night = ledger.get(night_id)
    if not night.data["closed"]:
        night.record("dismissed", "", {}, {"closed": True})
        ledger.commit([night])
