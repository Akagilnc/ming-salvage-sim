"""Deterministic entity × field rules; prose and intent are never inspected."""

import json
import math
from typing import Any

from pydantic_ai import ModelRetry

from ming.middle.declaration import Change, Declaration, Fact
from ming.middle.fiscal import WAN, clamp_scale, current_paid, has_obligation, obligation

SCALE_FIELDS = ("imperial_prestige", "public_support", "satisfaction")
Names = dict[str, dict[str, list[str]]]


def fail(field: str, value: object, expected: object, names: Names, how: str) -> None:
    raise ModelRetry(
        json.dumps(
            {
                "field": field,
                "current": value,
                "expected": expected,
                "names_and_aliases": names,
                "action": how,
            },
            ensure_ascii=False,
        )
    )


def check_rules(out: Declaration, affairs: set[str], names: Names) -> None:
    for i, fact in enumerate(out.facts):
        if fact.affair is not None and fact.affair not in affairs:
            fail(
                f"facts[{i}].affair",
                fact.affair,
                sorted(affairs),
                names,
                "affair 改成 expected 里的事务正名，或在本份先 create 该事务，重交整份。",
            )
        seen = [change.field for change in fact.changes]
        if len(set(seen)) != len(seen):
            fail(
                f"facts[{i}].changes",
                [field for field in seen if seen.count(field) > 1],
                "每个字段只出现一次",
                names,
                "删掉重名的字段变更，重交整份，不能静默丢项。",
            )
        for j, change in enumerate(fact.changes):
            if (fact.entity_type, change.field) in {
                ("account", "taels"),
                ("region", "fiscal_surcharge"),
                ("fiscal", "value"),
                ("army", "manpower"),
                ("army", "salary_rate"),
                ("building", "maintenance"),
                ("building", "condition"),
                ("building", "output_amount"),
                ("person", "travel_speed"),
                ("army", "firearm_equipment"),
                ("army", "cannon_equipment"),
                ("world", "imperial_prestige"),
                ("world", "public_support"),
                ("faction", "satisfaction"),
                ("class", "satisfaction"),
            } and (
                type(change.value) not in (int, float)
                or (type(change.value) is float and not math.isfinite(change.value))
            ):
                fail(
                    f"facts[{i}].changes[{j}].value",
                    change.value,
                    "有限数字",
                    names,
                    "把这个字段改成有限数字，重交整份。",
                )
    for i, fact in enumerate(out.facts):
        check_money(fact, out, names, i)


def money_mirrors(facts: list[Fact], fact: Fact, change: Change) -> list[int]:
    return [
        i
        for i, other in enumerate(facts)
        if change.counterpart is not None
        and (other.entity_type, other.entity)
        == (change.counterpart.entity_type, change.counterpart.entity)
        for c in other.changes
        if c.field == "taels"
        and c.value == -change.value
        and c.counterpart is not None
        and (c.counterpart.entity_type, c.counterpart.entity)
        == (fact.entity_type, fact.entity)
    ]


def check_money(fact: Fact, out: Declaration, names: Names, index: int) -> None:
    # A counterpart is a fact reference, not a guessed source or intent check.
    for j, change in enumerate(fact.changes):
        path = f"facts[{index}].changes[{j}]"
        if (fact.entity_type, change.field) != ("account", "taels"):
            if change.counterpart is not None:
                fail(
                    path + ".counterpart",
                    change.counterpart.model_dump(),
                    "省略",
                    names,
                    "删掉 counterpart。它只属于账户 taels，重交整份。",
                )
            continue
        if (
            change.counterpart
            and change.counterpart.entity_type in {"army", "fiscal"}
            and change.purpose is None
        ):
            fail(
                path + ".purpose",
                None,
                ["补欠", "当月饷", "犒赏", "专项"],
                names,
                "付给军队或财政科目的款补上 purpose，重交整份。",
            )
        if change.counterpart is None:
            if change.value < 0:
                fail(
                    path + ".counterpart",
                    None,
                    "同份 facts 里的另一实体",
                    names,
                    "支出补上 counterpart 出处去处，重交整份。",
                )
            continue
        matches = [
            other
            for other in out.facts
            if (other.entity_type, other.entity)
            == (change.counterpart.entity_type, change.counterpart.entity)
        ]
        if not matches or (
            change.counterpart.entity_type,
            change.counterpart.entity,
        ) == (fact.entity_type, fact.entity):
            fail(
                path + ".counterpart",
                change.counterpart.model_dump(),
                "同份 facts 的另一实体",
                names,
                "counterpart 改成同份 facts 里的另一实体，重交整份。",
            )
        if change.counterpart.entity_type == "account":
            mirrors = money_mirrors(out.facts, fact, change)
            sources = [
                other_change
                for other in out.facts
                for other_change in other.changes
                if (other.entity_type, other.entity) == (fact.entity_type, fact.entity)
                and other_change.field == "taels"
                and other_change.value == change.value
                and other_change.counterpart == change.counterpart
            ]
            if len(mirrors) != len(sources):
                fail(
                    path + ".counterpart",
                    change.value,
                    "两边相反等额并互指 counterpart",
                    names,
                    "钱粮两边改成相反等额、互指 counterpart，重交整份。",
                )
        elif change.value > 0:
            fail(
                path + ".value",
                change.value,
                "支出为负",
                names,
                "无存量的去处不能当出处。改成收款方且金额为支出，重交整份。",
            )


def money_amounts(
    facts: list[Fact], existing: dict[tuple[str, str], dict[str, Any]]
) -> tuple[dict[int, float], dict[int, str | None]]:
    amounts: dict[int, float] = {}
    reasons: dict[int, str | None] = {}
    balances = {key: row["data"].get("taels", 0) for key, row in existing.items()}
    # Obligation caps read this share's declared post-values (policy, manpower,
    # rates) without reordering how the share lands.
    projected = {
        key: {**row, "data": dict(row["data"])} for key, row in existing.items()
    }
    for fact in facts:
        if (fact.entity_type, fact.entity) in projected:
            projected[(fact.entity_type, fact.entity)]["data"].update(
                {c.field: c.value for c in fact.changes if c.field != "taels"}
            )
    limits: dict[tuple[str, str, str], float] = {}
    for i, fact in enumerate(facts):
        for change in fact.changes:
            if fact.entity_type != "account" or change.field != "taels" or i in amounts:
                continue
            pair = fact.entity_type, fact.entity
            if change.counterpart and change.counterpart.entity_type == "account":
                other = change.counterpart.entity_type, change.counterpart.entity
                j = next(
                    j for j in money_mirrors(facts, fact, change) if j not in amounts
                )
                # Either edge establishes the whole transfer, exactly once.
                source, destination = (
                    (pair, other) if change.value <= 0 else (other, pair)
                )
                actual = min(abs(change.value), max(0, balances.get(source, 0)))
                amounts[i] = -actual if change.value <= 0 else actual
                amounts[j] = -amounts[i]
                reasons[i] = reasons[j] = (
                    "balance" if actual < abs(change.value) else None
                )
                balances[source] = balances.get(source, 0) - actual
                balances[destination] = balances.get(destination, 0) + actual
            else:
                amounts[i] = (
                    -min(-change.value, max(0, balances.get(pair, 0)))
                    if change.value <= 0
                    else change.value
                )
                reasons[i] = "balance" if amounts[i] != change.value else None
                recipient = (
                    change.counterpart.entity_type,
                    change.counterpart.entity,
                ) if change.counterpart else None
                row = projected.get(recipient) if recipient else None
                if (
                    recipient is not None
                    and row is not None
                    and change.purpose in {"补欠", "当月饷"}
                    and has_obligation(change.purpose, recipient[0], row["data"])
                ):
                    key = (*recipient, change.purpose)
                    if key not in limits:
                        data = row["data"]
                        limits[key] = (
                            max(
                                0,
                                data.get("arrears", 0)
                                if change.purpose == "补欠"
                                else obligation(recipient, projected)
                                - current_paid(
                                    data, projected[("calendar", "world")]["data"]
                                ),
                            )
                            * WAN
                        )
                    if -amounts[i] > limits[key]:
                        reasons[i] = "obligation"
                    amounts[i] = -min(-amounts[i], limits[key])
                    limits[key] += amounts[i]
                balances[pair] = balances.get(pair, 0) + amounts[i]
    return amounts, reasons


def field_values(
    fact: Fact,
    data: dict[str, Any],
    amount: float | None,
    offsets: dict[tuple[str, str, str], Any],
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
            key = fact.entity_type, fact.entity, field
            actual[field] = clamp_scale(actual[field] + offsets.get(key, 0))
    changes = dict(actual)
    if "taels" in changes and fact.entity_type == "account":
        changes["taels"] += data.get("taels", 0)
    return {
        "text": fact.text,
        "changes": changes,
        "nominal": nominal,
        "actual": actual,
        "audience": "world",
    }
