"""Persistent audience records, owned by the same entity/event ledger."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ming.ledger import Entity, Ledger
from ming.ledger import ENTITY_ORDER
from ming.middle.queries import NIGHT_ROWS


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
    night = ledger.entities(entity_id=night_id, query=NIGHT_ROWS)[0]
    date = ledger.entities(kind="calendar")[0]["data"]
    turns: list[TurnView] = []
    for item in ledger.facts(entity_id=night_id, kind="turn"):
        detail = item["detail"]
        turns.append(TurnView(**detail, emperor_words=item["emperor_words"]))
    return NightView(
        id=night_id,
        **night["data"],
        date={"year": date["year"], "month": date["month"]},
        turns=turns,
        result=night["result"],
    )


def open_night(ledger: Ledger) -> UUID:
    for row in ledger.read(
        NIGHT_ROWS.order_by(None).order_by(ENTITY_ORDER.desc()).limit(1)
    ):
        if not row["data"]["closed"]:
            return row["id"]
    night = Entity("night", str(uuid4()), "", {"closed": False, "hall": ["王承恩"]})
    ledger.commit([night])
    return night.id


def dismiss(ledger: Ledger, night_id: UUID) -> None:
    night = ledger.get(night_id)
    if not night.data["closed"]:
        night.record("dismissed", "", {}, {"closed": True})
        ledger.commit([night])
