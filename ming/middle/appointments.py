"""Exact catalogue references and current appointments, independent of people."""

import json
from collections.abc import Callable, Sequence

from sqlalchemy import JSON, case, func, literal, or_, select, type_coerce
from sqlalchemy.sql.elements import BindParameter, ColumnElement

from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, Item, Ledger, read_once

CATALOGUE_KINDS = ("office", "territory")
APPOINTMENT_ROLES = ("holders", "acting")

DISPLAY_NAME = E.data["name"].as_string()
DECLARED_ALIASES = func.coalesce(E.data["aliases"].as_string(), "[]")
ALIASES = type_coerce(case(
    ((DISPLAY_NAME != "") & (DISPLAY_NAME != E.key),
     func.json_insert(DECLARED_ALIASES, "$[#]", DISPLAY_NAME)),
    else_=DECLARED_ALIASES,
), JSON)


def incumbency_record(pair: Sequence[str], holders: list[str]) -> tuple[str, Item]:
    return json.dumps(pair, ensure_ascii=False), {
        "office": pair[0], "territory": pair[1], "holders": holders, "acting": [],
    }


@read_once
def named(ledger: Ledger, kind: str | None, value: str | list[str]) -> tuple[Item, ...]:
    values = [value] if isinstance(value, str) else value
    aliases = func.json_each(ALIASES).table_valued("value")
    return ledger.entities(kind=kind, query=ENTITY_ROWS.where(or_(
        E.key.in_(values),
        select(aliases.c.value).where(aliases.c.value.in_(values)).exists(),
    )))


def office_pairs(
    ledger: Ledger, value: str,
    visible: Callable[[Sequence[Item]], Sequence[Item]] | None = None,
) -> tuple[list[tuple[str, str]], Item]:
    """Resolve once for both queries and landing; candidates are caller-visible rows."""
    exact = named(ledger, "office", value)
    if exact and any(row["data"]["external"] for row in exact):
        incumbencies = ledger.entities(kind="incumbency", query=ENTITY_ROWS.where(
            E.data["office"].as_string().in_([row["key"] for row in exact])
        ))
        return [], {"status": "territory_required", "territories": sorted({
            row["data"]["territory"] for row in (visible(incumbencies) if visible else incumbencies)
        }), "pairs": []}
    records = ledger.entities(kind="incumbency", key=value)
    pairs: set[tuple[str, str]] = set()
    if exact:
        pairs.update((row["key"], "") for row in exact)
    elif records:
        pairs.update((row["data"]["office"], row["data"]["territory"]) for row in records)
    else:
        aliases = func.json_each(ALIASES).table_valued("value")
        query = ENTITY_ROWS.add_columns(ALIASES.label("aliases")).where(E.data["external"].as_boolean().is_(True), or_(
            func.substr(literal(value), -func.length(E.key)) == E.key,
            select(aliases.c.value).where(func.substr(literal(value), -func.length(aliases.c.value)) == aliases.c.value).exists(),
        ))
        for office in ledger.entities(kind="office", query=query):
            for title in [office["key"], *office["aliases"]]:
                if title and value.endswith(title):
                    for territory in named(ledger, "territory", value[:-len(title)]):
                        pairs.add((office["key"], territory["key"]))
    return sorted(pairs), {
        "status": "resolved" if len(pairs) == 1 else "territory_required" if pairs else "office_not_found",
        "territories": sorted({territory for _, territory in pairs}),
        "pairs": [{"office": office, "territory": territory} for office, territory in sorted(pairs)],
    }


@read_once
def reference_key(ledger: Ledger, kind: str, value: str) -> str:
    if kind == "incumbency":
        pairs, resolution = office_pairs(ledger, value)
        matches = [incumbency_record(pair, [])[0] for pair in pairs] if resolution["status"] == "resolved" else []
    else:
        matches = [row["key"] for row in named(ledger, kind, value)]
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
            and row["data"]["office"] in offices
            for role in APPOINTMENT_ROLES for person in row["data"][role]}


def held_by(people: BindParameter[str]) -> ColumnElement[bool]:
    return or_(*(
        select(members.c.value).where(members.c.value.in_(people)).exists()
        for role in APPOINTMENT_ROLES
        for members in [func.json_each(E.data[role]).table_valued("value")]
    ))
