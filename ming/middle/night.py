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
    turns: list[TurnView] = Field(default_factory=list[TurnView])
    result: Literal["translated", "unhandled"] | None = None


def read_night(ledger: Ledger, night_id: UUID) -> NightView:
    night = ledger.get(night_id)
    turns: list[TurnView] = []
    result = None
    for item in night.events:
        detail = item["detail"]
        if item["kind"] == "turn":
            turns.append(TurnView(**detail, emperor_words=item["emperor_words"]))
        elif item["kind"] == "translated":
            result = "translated"
        elif item["kind"] == "unhandled":
            result = "unhandled"
    return NightView(id=night.id, **night.data, turns=turns, result=result)


def open_night(ledger: Ledger) -> UUID:
    for row in reversed(ledger.entities()):
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


def append_turn(ledger: Ledger, night_id: UUID, words: str, scene: str) -> str:
    night = ledger.get(night_id)
    turn_id = str(uuid4())
    night.record("turn", words, {"id": turn_id, "scene": scene})
    ledger.commit([night])
    return turn_id
