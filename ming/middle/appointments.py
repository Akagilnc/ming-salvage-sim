"""Exact catalogue references and current appointments, independent of people."""

import json
from collections.abc import Sequence

from sqlalchemy import func, literal, or_, select

from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, Item, Ledger

CATALOGUE_KINDS = ("office", "territory")


def incumbency_record(pair: Sequence[str], holders: list[str]) -> tuple[str, Item]:
    return json.dumps(pair, ensure_ascii=False), {
        "office": pair[0], "territory": pair[1], "holders": holders, "acting": [],
    }


def named(ledger: Ledger, kind: str, value: str) -> list[Item]:
    aliases = func.json_each(E.data["aliases"]).table_valued("value")
    return ledger.entities(kind=kind, query=ENTITY_ROWS.where(or_(
        E.key == value,
        select(aliases.c.value).where(aliases.c.value == value).exists(),
    )))


def office_pairs(ledger: Ledger, value: str) -> list[tuple[str, str]]:
    exact = named(ledger, "office", value)
    if exact:
        return [(row["key"], "") for row in exact if not row["data"].get("external", False)]
    records = ledger.entities(kind="incumbency", key=value)
    if records:
        return [(r["data"]["office"], r["data"]["territory"]) for r in records
                if r["data"]["territory"] or not named(ledger, "office", r["data"]["office"])[0]["data"].get("external", False)]
    aliases = func.json_each(E.data["aliases"]).table_valued("value")
    pairs: set[tuple[str, str]] = set()
    query = ENTITY_ROWS.where(or_(
        func.substr(literal(value), -func.length(E.key)) == E.key,
        select(aliases.c.value).where(func.substr(literal(value), -func.length(aliases.c.value)) == aliases.c.value).exists(),
    ))
    for office in ledger.entities(kind="office", query=query.where(E.data["external"].as_boolean().is_not(False))):
        for title in [office["key"], *office["data"]["aliases"]]:
            if title and value.endswith(title):
                for territory in named(ledger, "territory", value[:-len(title)]):
                    pairs.add((office["key"], territory["key"]))
    return sorted(pairs)


def reference_key(ledger: Ledger, kind: str, value: str) -> str:
    matches = (
        [incumbency_record(pair, [])[0] for pair in office_pairs(ledger, value)]
        if kind == "incumbency"
        else [row["key"] for row in named(ledger, kind, value)]
    )
    return matches[0] if len(matches) == 1 else value


def cabinet_records(ledger: Ledger) -> dict[tuple[str, str], Item]:
    """Load cabinet offices and appointments for validation and in-flight landing."""
    offices = ledger.entities(kind="office", query=ENTITY_ROWS.where(
        E.data["department"].as_string() == "内阁"
    ))
    appointments = ledger.entities(kind="incumbency", query=ENTITY_ROWS.where(
        E.data["office"].as_string().in_([row["key"] for row in offices])
    ))
    return {(row["kind"], row["key"]): row for row in [*offices, *appointments]}


def cabinet_members(records: dict[tuple[str, str], Item]) -> set[str]:
    """Derive eligible members from the caller's current appointment snapshot."""
    offices = {key for (kind, key), row in records.items()
               if kind == "office" and row["data"].get("department") == "内阁"
               and key != "内阁首辅"}
    return {person for (kind, _), row in records.items() if kind == "incumbency"
            and row["data"]["office"] in offices for person in row["data"]["holders"]}


def held_by(ledger: Ledger, people: list[str]) -> list[Item]:
    holders = func.json_each(E.data["holders"]).table_valued("value")
    acting = func.json_each(E.data["acting"]).table_valued("value")
    return ledger.entities(kind="incumbency", query=ENTITY_ROWS.where(or_(
        select(holders.c.value).where(holders.c.value.in_(people)).exists(),
        select(acting.c.value).where(acting.c.value.in_(people)).exists(),
    )))
