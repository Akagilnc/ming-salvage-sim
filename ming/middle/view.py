"""Identity-specific structured read boundary; no summaries of model prose."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from ming.ledger import Ledger

Identity = Literal["emperor", "audit"]


class EntityView(BaseModel):
    id: UUID
    kind: str
    key: str
    source: str
    data: dict[str, Any]


class FactView(BaseModel):
    entity_id: UUID
    kind: str
    emperor_words: str
    detail: dict[str, Any]


def entities(
    ledger: Ledger, identity: Identity, replay: bool = False
) -> list[EntityView]:
    result: list[EntityView] = []
    for row in ledger.entities(replay):
        if identity == "emperor":
            if row["kind"] != "person":
                continue
            row["data"] = {
                k: v
                for k, v in row["data"].items()
                if k in {"name", "office", "location", "status"}
            }
        result.append(EntityView.model_validate(row))
    return result


def project(ledger: Ledger, identity: Identity, replay: bool = False) -> list[FactView]:
    result: list[FactView] = []
    for row in ledger.entities(replay):
        for item in row["events"]:
            fact = FactView(entity_id=row["id"], **item)
            if identity == "emperor":
                if fact.kind != "unhandled":
                    continue
                fact.detail = {}
            result.append(fact)
    return result
