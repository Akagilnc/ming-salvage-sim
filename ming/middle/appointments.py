"""Exact catalogue references and current appointments, independent of people."""

import json
from collections.abc import Callable, Sequence

from sqlalchemy import JSON, and_, case, func, or_, select, type_coerce
from sqlalchemy.sql.elements import BindParameter, ColumnElement

from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, Item, Ledger

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


def named(ledger: Ledger, kind: str | None, value: str | list[str]) -> tuple[Item, ...]:
    values = [value] if isinstance(value, str) else value
    aliases = func.json_each(ALIASES).table_valued("value")
    return ledger.entities(kind=kind, query=ENTITY_ROWS.add_columns(ALIASES.label("aliases")).where(or_(
        E.key.in_(values),
        select(aliases.c.value).where(aliases.c.value.in_(values)).exists(),
    )))


def office_pairs(
    ledger: Ledger, values: list[str],
    visible: Callable[[Sequence[Item]], Sequence[Item]] | None = None,
    *, include_cabinet: bool = False,
) -> tuple[dict[str, tuple[list[tuple[str, str]], Item, Item]], tuple[Item, ...]]:
    """Resolve the known batch and return its office/appointment material."""
    requests = func.json_each(json.dumps(values, ensure_ascii=False)).table_valued("value")
    aliases = func.json_each(ALIASES).table_valued("value")
    known = E.id.table.alias("named_incumbency").c
    offices = {row["key"]: row for row in ledger.entities(kind="office", query=ENTITY_ROWS.add_columns(ALIASES.label("aliases")).where(or_(
        E.data["department"].as_string() == "内阁" if include_cabinet else False,
        E.key.in_(select(known.data["office"].as_string()).where(known.kind == "incumbency", known.key.in_(values))),
        select(requests.c.value).where(or_(
            E.key == requests.c.value,
            select(aliases.c.value).where(aliases.c.value == requests.c.value).correlate(E.id.table, requests).exists(),
            and_(E.data["external"].as_boolean().is_(True), or_(
                func.substr(requests.c.value, -func.length(E.key)) == E.key,
                select(aliases.c.value).where(func.substr(requests.c.value, -func.length(aliases.c.value)) == aliases.c.value).correlate(E.id.table, requests).exists(),
            )),
        )).correlate(E.id.table).exists(),
    )))}
    exact = {value: [row for row in offices.values() if value == row["key"] or value in row["aliases"]] for value in values}
    required = {value: {row["key"] for row in rows} for value, rows in exact.items() if any(row["data"]["external"] for row in rows)}
    unresolved = [value for value in values if not exact[value]]
    office_keys = {key for keys in required.values() for key in keys} | {
        key for key, row in offices.items() if include_cabinet and row["data"]["department"] == "内阁"
    }
    records = {row["key"]: row for row in ledger.entities(kind="incumbency", query=ENTITY_ROWS.where(or_(
        E.key.in_(unresolved), E.data["office"].as_string().in_(office_keys),
    )))} if unresolved or office_keys else {}
    seen = visible(list(records.values())) if visible and required else list(records.values())
    candidates = {value: [(row, value[:-len(title)]) for row in offices.values() if row["data"]["external"]
                          for title in [row["key"], *row["aliases"]] if title and value.endswith(title)]
                  for value in values if not exact[value] and value not in records}
    prefixes = {prefix for rows in candidates.values() for _, prefix in rows}
    territories = named(ledger, "territory", list(prefixes)) if prefixes else ()
    results: dict[str, tuple[list[tuple[str, str]], Item, Item]] = {}
    for value in values:
        if value in required:
            results[value] = [], {"status": "territory_required", "territories": sorted({
                row["data"]["territory"] for row in seen if row["data"]["office"] in required[value]
            }), "pairs": []}, {}
            continue
        if exact[value]:
            pairs = sorted({(row["key"], "") for row in exact[value]})
        elif value in records:
            pairs = [(records[value]["data"]["office"], records[value]["data"]["territory"])]
        else:
            pairs = sorted({(office["key"], territory["key"]) for office, prefix in candidates[value] for territory in territories
                            if prefix == territory["key"] or prefix in territory["aliases"]})
        results[value] = pairs, {
            "status": "resolved" if len(pairs) == 1 else "territory_required" if pairs else "office_not_found",
            "territories": sorted({territory for _, territory in pairs}),
            "pairs": [{"office": office, "territory": territory} for office, territory in pairs],
        }, offices[pairs[0][0]] if len(pairs) == 1 else {}
    return results, (*offices.values(), *records.values())


def reference_key(kind: str, value: str, names: dict[str, dict[str, list[str]]],
                  *, resolution: tuple[list[tuple[str, str]], Item, Item] | None = None) -> str:
    if resolution is not None:
        pairs, status, _ = resolution
        return incumbency_record(pairs[0], [])[0] if status["status"] == "resolved" else value
    matches = [key for key, aliases in names.get(kind, {}).items() if key == value or value in aliases]
    return matches[0] if len(matches) == 1 else value


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
