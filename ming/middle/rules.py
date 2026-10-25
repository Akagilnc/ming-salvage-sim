"""Deterministic entity × field rules; prose and intent are never inspected."""

import json
import math
from typing import Any

from pydantic_ai import ModelRetry

from ming.middle.appointments import CATALOGUE_KINDS
from ming.middle.declaration import Declaration, Fact
from ming.middle.fiscal import WAN, clamp_scale, current_paid, has_obligation, obligation

SCALE_FIELDS = ("imperial_prestige", "public_support", "satisfaction")
Names = dict[str, dict[str, list[str]]]


def matching_names(names: Names, queries: list[str]) -> Names:
    """All substring candidates within the caller's already visible names."""
    return {
        kind: matches for kind, entries in names.items()
        if (matches := {name: aliases for name, aliases in entries.items()
                        if any(query and any(query in label for label in [name, *aliases])
                               for query in queries)})
    }


def name_expected(
    kind: str, value: str, names: Names,
) -> dict[str, Any]:
    if kind not in CATALOGUE_KINDS:
        return {"catalogue": kind}
    return matching_names({kind: names.get(kind, {})}, [value]) or {"status": "not_found", "tool": "read_records"}


def fail(field: str, value: object, expected: object, names: Names, how: str) -> None:
    raise ModelRetry(json.dumps({
        "field": field, "current": value, "expected": expected, "action": how,
    }, ensure_ascii=False))


def check_rules(out: Declaration, affairs: set[str], names: Names) -> None:
    for i, fact in enumerate(out.facts):
        if fact.affair is not None and fact.affair not in affairs:
            fail(f"facts[{i}].affair", fact.affair, name_expected("affair", fact.affair, names), names,
                 "事务正名查 expected 指向的输入目录，或在本份先 create 该事务，重交整份。")
        seen = [change.field for change in fact.changes
                if (fact.entity_type, change.field) != ("account", "taels")]
        if len(set(seen)) != len(seen):
            fail(f"facts[{i}].changes", [field for field in seen if seen.count(field) > 1],
                 "每个字段只出现一次", names, "删掉重名的字段变更，重交整份，不能静默丢项。")
        for j, change in enumerate(fact.changes):
            if (fact.entity_type, change.field) in {
                ("account", "taels"), ("region", "fiscal_surcharge"), ("fiscal", "value"),
                ("army", "manpower"), ("army", "salary_rate"), ("building", "maintenance"),
                ("building", "condition"), ("building", "output_amount"), ("person", "travel_speed"),
                ("army", "firearm_equipment"), ("army", "cannon_equipment"),
                ("world", "imperial_prestige"), ("world", "public_support"),
                ("faction", "satisfaction"), ("class", "satisfaction"),
            } and (type(change.value) not in (int, float)
                   or (type(change.value) is float and not math.isfinite(change.value))):
                fail(f"facts[{i}].changes[{j}].value", change.value, "有限数字", names,
                     "把这个字段改成有限数字，重交整份。")
        check_money(fact, names, i)


def check_money(fact: Fact, names: Names, index: int) -> None:
    for j, change in enumerate(fact.changes):
        path = f"facts[{index}].changes[{j}]"
        if (fact.entity_type, change.field) != ("account", "taels"):
            if change.counterpart is not None:
                fail(path + ".counterpart", change.counterpart.model_dump(), "省略", names,
                     "删掉 counterpart。它只属于账户 taels，重交整份。")
            continue
        if change.counterpart is None:
            if change.value < 0:
                fail(path + ".counterpart", None, {"entity_type": list(names), "entity": "收方正名"},
                     names, "支出补上 counterpart 收方，重交整份。")
            continue
        kind = change.counterpart.entity_type
        if kind not in names:
            fail(path + ".counterpart.entity_type", kind, list(names), names, "收方类型改成 expected，重交整份。")
        if change.counterpart.entity not in names[kind]:
            fail(path + ".counterpart.entity", change.counterpart.entity, name_expected(kind, change.counterpart.entity, names), names,
                 "参照 expected 的输入目录指针或候选填写收方正名，重交整份；不必另交收方 fact。")
        if kind in {"army", "fiscal"} and change.purpose is None:
            fail(path + ".purpose", None, ["补欠", "当月饷", "犒赏", "专项"], names,
                 "付给军队或财政科目的款补上 purpose，重交整份。")
        if change.value > 0:
            fail(path + ".value", change.value, "付方负数增减，加 counterpart 收方", names,
                 "有往来方的款改写到付方去；无出处收入用正数且省略 counterpart。重交整份。")


def money_amounts(
    facts: list[Fact], existing: dict[tuple[str, str], dict[str, Any]]
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], str | None]]:
    amounts: dict[tuple[int, int], float] = {}
    reasons: dict[tuple[int, int], str | None] = {}
    balances = {key: row["data"].get("taels", 0) for key, row in existing.items()}
    # Caps use the declared post-values of policy, manpower and rates.
    projected = {key: {**row, "data": dict(row["data"])} for key, row in existing.items()}
    for fact in facts:
        if (fact.entity_type, fact.entity) in projected:
            projected[(fact.entity_type, fact.entity)]["data"].update(
                field_values(fact, projected[(fact.entity_type, fact.entity)]["data"], None)["changes"]
            )
    limits: dict[tuple[str, str, str], float] = {}
    for i, fact in enumerate(facts):
        for j, change in enumerate(fact.changes):
            if fact.entity_type != "account" or change.field != "taels":
                continue
            pair = fact.entity_type, fact.entity
            recipient = (change.counterpart.entity_type, change.counterpart.entity) if change.counterpart else None
            amounts[i, j] = (
                -min(-change.value, max(0, balances.get(pair, 0))) if change.value <= 0
                else change.value
            )
            reasons[i, j] = "balance" if amounts[i, j] != change.value else None
            row = projected.get(recipient) if recipient else None
            if (recipient is not None and row is not None and change.purpose in {"补欠", "当月饷"}
                    and has_obligation(change.purpose, recipient[0], row["data"])):
                key = (*recipient, change.purpose)
                if key not in limits:
                    limits[key] = max(0, row["data"].get("arrears", 0) if change.purpose == "补欠"
                                      else obligation(recipient, projected) - current_paid(
                                          row["data"], projected[("calendar", "world")]["data"]
                                      )) * WAN
                if -amounts[i, j] > limits[key]:
                    reasons[i, j] = "obligation"
                amounts[i, j] = -min(-amounts[i, j], limits[key])
                limits[key] += amounts[i, j]
            balances[pair] = balances.get(pair, 0) + amounts[i, j]
            if recipient is not None and recipient[0] == "account":
                balances[recipient] = balances.get(recipient, 0) - amounts[i, j]
    return amounts, reasons


def field_values(
    fact: Fact,
    data: dict[str, Any],
    amount: float | None,
) -> dict[str, Any]:
    nominal = {c.field: c.value for c in fact.changes}
    actual = dict(nominal)
    if amount is not None:
        actual["taels"] = amount
    for field, cap in (("firearm_equipment", 100), ("cannon_equipment", 12)):
        if fact.entity_type == "army" and field in actual:
            actual[field] = min(cap, max(0, actual[field]))
    if fact.entity_type == "person" and "travel_speed" in actual:
        actual["travel_speed"] = min(2, max(1, actual["travel_speed"]))
    for field in SCALE_FIELDS:
        if field in actual and fact.entity_type in {"world", "faction", "class"}:
            actual[field] = clamp_scale(data.get(field, 0) + actual[field])
    if "payment_policy" in actual:
        actual["payment_policy"] = {key: min(1, max(0, value)) if key in {"factor", "defer"} else value
                                    for key, value in actual["payment_policy"].items()}
    changes = dict(actual)
    if "taels" in changes and fact.entity_type == "account":
        changes["taels"] += data.get("taels", 0)
    return {"text": fact.text, "changes": changes, "nominal": nominal, "actual": actual, "audience": "world"}
