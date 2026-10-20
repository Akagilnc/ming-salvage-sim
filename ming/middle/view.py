"""Identity-specific structured read boundary; no summaries of model prose."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from ming.ledger import Item, Ledger

PublicIdentity = Literal["emperor", "audit", "world", "public"]


class Officials(BaseModel):
    people: list[str]


Identity = PublicIdentity | Officials


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


def owned_accounts(rows: list[Item], identity: Identity) -> set[UUID]:
    if not isinstance(identity, Officials):
        return set()
    departments = {
        {"司礼监": "内廷"}.get(
            r["data"].get("office_type"), r["data"].get("office_type")
        )
        for r in rows
        if r["kind"] == "person" and r["key"] in identity.people
    }
    return {
        r["id"]
        for r in rows
        if r["kind"] == "account" and r["data"].get("department") in departments
    }


def entities(
    ledger: Ledger, identity: Identity, replay: bool = False
) -> list[EntityView]:
    rows = ledger.entities(replay)
    accounts = owned_accounts(rows, identity)
    result: list[EntityView] = []
    for row in rows:
        if identity not in ("audit", "world"):
            if row["id"] in accounts:
                pass
            elif row["kind"] == "person":
                row["data"] = {
                    k: v
                    for k, v in row["data"].items()
                    if k in {"name", "office", "location", "status"}
                }
            elif row["kind"] not in {"gazette", "calendar"} or identity == "emperor":
                continue
        result.append(EntityView.model_validate(row))
    return result


def project(ledger: Ledger, identity: Identity, replay: bool = False) -> list[FactView]:
    rows = ledger.entities(replay)
    accounts = owned_accounts(rows, identity)
    result: list[FactView] = []
    for row in rows:
        for item in row["events"]:
            fact = FactView(entity_id=row["id"], **item)
            if identity not in ("audit", "world"):
                if (
                    fact.kind == "gazette"
                    or fact.detail.get("audience") == "public"
                    or (
                        identity == "public"
                        and fact.detail.get("audience") == "official"
                    )
                ):
                    fact.detail = {"text": fact.detail["text"]}
                elif fact.kind in {"petition", "choice"}:
                    pass
                elif fact.kind == "unhandled" and identity == "emperor":
                    fact.detail = {}
                elif (
                    isinstance(identity, Officials)
                    and (
                        row["id"] in accounts
                        or (
                            row["kind"] == "decree"
                            and set(identity.people).intersection(
                                row["data"].get("people", [])
                            )
                        )
                    )
                    and fact.kind in {"changed", "received", "decreed"}
                ):
                    fact.detail = {"text": fact.detail.get("text", "")}
                else:
                    continue
                fact.emperor_words = ""
            result.append(fact)
    return result
