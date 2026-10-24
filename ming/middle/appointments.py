"""Exact catalogue references and current appointments, independent of people."""

import json

from sqlalchemy import func, literal, or_, select

from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, Item, Ledger


def named(ledger: Ledger, kind: str, value: str) -> list[Item]:
    aliases = func.json_each(E.data["aliases"]).table_valued("value")
    return ledger.entities(kind=kind, query=ENTITY_ROWS.where(or_(
        E.key == value,
        select(aliases.c.value).where(aliases.c.value == value).exists(),
    )))


def office_pairs(ledger: Ledger, value: str) -> list[tuple[str, str]]:
    exact = named(ledger, "office", value)
    if exact:
        return [(row["key"], "") for row in exact]
    aliases = func.json_each(E.data["aliases"]).table_valued("value")
    pairs: set[tuple[str, str]] = set()
    query = ENTITY_ROWS.where(or_(
        func.substr(literal(value), -func.length(E.key)) == E.key,
        select(aliases.c.value).where(func.substr(literal(value), -func.length(aliases.c.value)) == aliases.c.value).exists(),
    ))
    for office in ledger.entities(kind="office", query=query):
        for title in [office["key"], *office["data"]["aliases"]]:
            if title and value.endswith(title):
                for territory in named(ledger, "territory", value[:-len(title)]):
                    pairs.add((office["key"], territory["key"]))
    return sorted(pairs)


def reference_key(ledger: Ledger, kind: str, value: str) -> str:
    matches = (
        [json.dumps(pair, ensure_ascii=False) for pair in office_pairs(ledger, value)]
        if kind == "incumbency"
        else [row["key"] for row in named(ledger, kind, value)]
    )
    return matches[0] if len(matches) == 1 else value


def held_by(ledger: Ledger, people: list[str]) -> list[Item]:
    holders = func.json_each(E.data["holders"]).table_valued("value")
    return ledger.entities(kind="incumbency", query=ENTITY_ROWS.where(
        select(holders.c.value).where(holders.c.value.in_(people)).exists()
    ))
