"""Deterministic entity × field rules; prose and intent are never inspected."""

import math
from typing import Any

from pydantic_ai import ModelRetry

from ming.middle.declaration import Change, Declaration, Fact
from ming.middle.fiscal import WAN, clamp_scale, current_paid, obligation

SCALE_FIELDS = ("imperial_prestige", "public_support", "satisfaction")


def check_rules(out: Declaration, affairs: set[str]) -> None:
    for i, fact in enumerate(out.facts):
        if fact.affair is not None and fact.affair not in affairs:
            raise ModelRetry(
                f"facts[{i}].affair: {fact.affair!r}; 期望事务正名 {sorted(affairs)}，重交整份。"
            )
        if len({c.field for c in fact.changes}) != len(fact.changes):
            raise ModelRetry("一条事实的字段变更不得重名；重交整份，不能静默丢项。")
        for change in fact.changes:
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
                raise ModelRetry(
                    f"{fact.entity}.{change.field}: {change.value!r}; 期望有限数字，重交整份。"
                )
            if (
                (fact.entity_type, change.field) == ("person", "travel_speed")
                and change.value != 1
                and not 1.5 <= change.value <= 2
            ):
                raise ModelRetry("行速须为常速1，或加急1.5至2；重交整份。")
    for fact in out.facts:
        check_money(fact, out)


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


def check_money(fact: Fact, out: Declaration) -> None:
    # A counterpart is a fact reference, not a guessed source or intent check.
    for change in fact.changes:
        if (fact.entity_type, change.field) != ("account", "taels"):
            if change.counterpart is not None:
                raise ModelRetry("counterpart 只属于账户 taels，重交整份。")
            continue
        if change.purpose is not None and (
            change.counterpart is None
            or change.counterpart.entity_type not in {"army", "fiscal"}
        ):
            raise ModelRetry("purpose仅属于账户付给军队或财政科目的款，重交整份。")
        if (
            change.counterpart
            and change.counterpart.entity_type in {"army", "fiscal"}
            and change.purpose is None
        ):
            raise ModelRetry(
                "付给军队或财政科目的款须声明purpose：补欠、当月饷、犒赏、专项；重交整份。"
            )
        if change.counterpart is None:
            if change.value < 0:
                raise ModelRetry("账户支出须指明 counterpart 出处去处，重交整份。")
            continue
        matches = [
            f
            for f in out.facts
            if (f.entity_type, f.entity)
            == (change.counterpart.entity_type, change.counterpart.entity)
        ]
        if not matches or (
            change.counterpart.entity_type,
            change.counterpart.entity,
        ) == (fact.entity_type, fact.entity):
            raise ModelRetry("counterpart 必须指向同份 facts 的另一实体，重交整份。")
        if change.counterpart.entity_type == "account":
            mirrors = money_mirrors(out.facts, fact, change)
            sources = [
                c
                for f in out.facts
                for c in f.changes
                if (f.entity_type, f.entity) == (fact.entity_type, fact.entity)
                and c.field == "taels"
                and c.value == change.value
                and c.counterpart == change.counterpart
            ]
            if len(mirrors) != len(sources):
                raise ModelRetry("钱粮两边必须相反等额、互指 counterpart，重交整份。")
        elif change.value > 0:
            raise ModelRetry("无存量的去处不能充当出处，重交整份。")


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
                if change.counterpart and change.purpose in {"补欠", "当月饷"}:
                    recipient = (
                        change.counterpart.entity_type,
                        change.counterpart.entity,
                    )
                    key = (*recipient, change.purpose)
                    if key not in limits:
                        data = projected[recipient]["data"]
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
