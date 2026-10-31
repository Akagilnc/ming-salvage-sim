"""Land a whole declaration, query rows and events in the same transaction."""

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import case, func, select

from ming.ledger import Entity, Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, FACT_ROWS
from ming.middle.declaration import (
    Declaration,
    DecreeEvent,
    EntityRef,
    Fact,
    LandingMode,
    NightDeclaration,
    Unhandled,
)
from ming.middle.reading import Records, was_forced
from ming.middle.rules import Names, check_chief, check_journey, fail, field_values, money_amounts, name_expected
from ming.middle.fiscal import WAN, current_paid, expense_rate, has_obligation
from ming.middle.appointments import APPOINTMENT_ROLES, incumbency_record, reference_key
from ming.middle.travel import journey_distances, move_person


@dataclass
class Translation:
    """Output-function return value: the declaration and its native working objects."""
    declaration: Declaration | Unhandled
    owner: Entity
    targets: dict[tuple[str, str], Entity]
    words: str
    date: Item


def check_decrees(
    ledger: Ledger, out: Declaration | Unhandled, owner: Entity, names: Names, count: int,
) -> str:
    # One turn read supplies both validation IDs and the landing's emperor words.
    turns = ledger.facts(
        entity_id=owner.id,
        kind="turn", query=FACT_ROWS.with_only_columns(F.emperor_words, F.detail["id"].as_string().label("turn_id")),
    ) if owner.kind != "calendar" else ()
    count = len(out.decrees) if isinstance(out, NightDeclaration) else count
    labeled = (("facts", out.facts), ("decree_events", out.decree_events)) if isinstance(out, Declaration) else ()
    for label, items in labeled:
        for i, item in enumerate(items):
            ref = item.decree
            path = f"{label}[{i}].decree"
            if (ref is None and (isinstance(item, DecreeEvent) or item.discovered)) or (ref is not None and not 0 <= ref < count):
                fail(path, ref, "decrees 的零基下标", names, "使用所属旨意在 decrees 中的下标，重交整份。")
    if isinstance(out, NightDeclaration) and out.decrees:
        for i, decree in enumerate(out.decrees):
            if decree.secret:
                decree.handler = reference_key(ledger, "person", decree.handler, names) if decree.handler is not None else None
                if decree.handler not in names.get("person", {}):
                    fail(
                        f"decrees[{i}].handler", decree.handler,
                        name_expected("person", decree.handler or "", names), names,
                        "密令须声明唯一承办人，用人物目录正名或所列别名；照整夜戏文记录领旨去办者，重交整份。",
                    )
            if decree.turn > len(turns):
                fail(
                    f"decrees[{i}].turn",
                    decree.turn,
                    list(range(1, len(turns) + 1)),
                    names,
                    "turn 改成 expected 里的本夜轮次，重交整份。",
                )
        check_endorsements(ledger, out, {row["turn_id"] for row in turns}, names)
    return "\n".join(row["emperor_words"] for row in turns)


def check_endorsements(
    ledger: Ledger,
    out: NightDeclaration,
    turn_ids: set[str],
    names: dict[str, dict[str, list[str]]],
) -> None:
    for i, decree in enumerate(out.decrees):
        for j, endorsement in enumerate(decree.endorsements):
            path = f"decrees[{i}].endorsements[{j}]"
            if endorsement.source_chat_turn_id not in turn_ids:
                fail(
                    path + ".source_chat_turn_id",
                    endorsement.source_chat_turn_id,
                    sorted(turn_ids),
                    names,
                    "source_chat_turn_id 改成 expected 里的本夜轮次 id，重交整份。",
                )
            allowed: list[str] | dict[str, list[str]] = ["御笔"]
            if endorsement.form != "御笔手敕":
                endorsement.endorser = reference_key(ledger, "person", endorsement.endorser, names)
                allowed = names.get("person", {})
            if endorsement.endorser not in allowed:
                fail(
                    path + ".endorser",
                    endorsement.endorser,
                    allowed if endorsement.form == "御笔手敕" else name_expected("person", endorsement.endorser, names),
                    names,
                    "参照 expected 的正名清单或输入目录指针核对 endorser，重交整份。",
                )


def prepare(
    ledger: Ledger, result: Declaration | Unhandled, owner: Entity,
    records: dict[tuple[str, str], Item], names: Names,
) -> Translation:
    sources = Records(ledger).landing_sources(owner.data) if owner.kind == "calendar" else []
    existing = {pair: row for pair, row in records.items() if pair[0] in {"office", "incumbency"} and row["data"]}
    existing[owner.kind, owner.key] = owner.snapshot()
    records.update(((row["kind"], row["key"]), row) for row, _mode, _events in sources)
    changed = {(owner.kind, owner.key): owner}
    fact_origin: Item = {}
    date = owner.data if owner.kind == "calendar" else ledger.entities(kind="calendar", key="world")[0]["data"]
    existing["calendar", "world"] = {"data": date}
    words = check_decrees(ledger, result, owner, names, len(sources))

    def known(kind: str, key: str) -> Entity:
        pair = kind, key
        if pair not in changed:
            if pair in records:
                changed[pair] = owner if records[pair]["id"] == owner.id else ledger.get(records[pair]["id"])
            else:
                data: Item = incumbency_record(json.loads(key), [])[1] if kind == "incumbency" else {}
                changed[pair] = Entity(*pair, "", data)
            existing[pair] = changed[pair].snapshot()
        return changed[pair]

    def record(
        entity: Entity,
        kind: str,
        detail: dict[str, object],
        changes: dict[str, object] | None = None,
    ) -> None:
        entity.record(
            kind,
            words,
            {"origin_ref": str(owner.id), "date": date, **fact_origin, **detail},
            changes,
        )
        changed[(entity.kind, entity.key)] = entity
        existing[(entity.kind, entity.key)] = entity.snapshot()

    decrees = [(decree.id, decree.key) for decree in record_decrees(result, owner, known, record)] + [
        (row["id"], row["key"]) for row, _mode, _events in sources
    ]
    if isinstance(result, Declaration):
        values, projected = calculated_values(ledger, result.facts, existing, known)
        distances = journey_distances(ledger, result.facts, {key: row["data"] for (kind, key), row in existing.items() if kind == "person"})
        limits: dict[tuple[str, str, str], float] = {}
        for i, j, fact in landing_facts(result.facts):
            entity = known(fact.entity_type, fact.entity)
            association = (
                {"affair_id": str(known("affair", fact.affair).id)}
                if fact.affair is not None
                else {}
            )
            if (i, j) in values:
                detail = values[i, j]
            else:
                detail = money_amounts(fact, entity, projected, limits)
            detail.update(association)
            fact_origin = {
                "discovered": fact.discovered,
                **({"origin_ref": str(decrees[fact.decree][0])} if fact.decree is not None else {}),
            }
            if entity.kind == "person":
                move_person(entity, detail["changes"], check_journey(distances, fact, f"facts[{i}]", names, entity), record, date)
            if entity.kind == "incumbency":
                displace(entity, detail["changes"], known, record, {**association, "text": fact.text})
            record(entity, "changed", detail, detail["changes"])
            if entity.kind in {"office", "incumbency"}:
                eligible = check_chief(fact, i, existing, names)
                retire_chief(existing, known, record, {**association, "text": fact.text}, eligible)
            if (i, j) not in values:
                record_receipts(fact, detail, date, known, record)
        fact_origin = {}
        register_funding(ledger, result.facts, known, record)
        for report in result.reports:
            known(report.entity_type, report.entity)
        for event in result.decree_events:
            entity = known("decree", decrees[cast(int, event.decree)][1])
            fact_origin = {"origin_ref": str(entity.id)}
            record(entity, event.kind, {"text": event.text})
        fact_origin = {}
    sources = [source for source in sources if source[1] is not None]
    prior_interims: set[UUID] = {event["entity_id"] for event in ledger.facts(
        entity_id=[row["id"] for row, _mode, _events in sources], kind="interim",
        query=FACT_ROWS.with_only_columns(F.entity_id).order_by(None).distinct(),
    )} if sources else set()
    for source in sources:
        entity = known(source[0]["kind"], source[0]["key"])
        for kind, detail in decree_disposition(
            entity.id in prior_interims, entity, cast(LandingMode, source[1]), source[2],
            not isinstance(result, Unhandled),
        ):
            record(entity, kind, detail)
    return Translation(result, owner, changed, words, date)


def dispatch(ledger: Ledger, work: Translation, monthly: LandingMode | None = None) -> None:
    # Reports have no calculations; append them after any intervening source write.
    if isinstance(work.declaration, Declaration):
        for report in work.declaration.reports:
            work.targets[report.entity_type, report.entity].record(
                "reported", work.words,
                {"origin_ref": str(work.owner.id), "date": work.date, **report.model_dump()},
            )
    work.owner.record(
        "unhandled" if isinstance(work.declaration, Unhandled) else (monthly or "translated"),
        work.words,
        {"origin_ref": str(work.owner.id), "date": work.date,
         "result": work.declaration.model_dump(mode="json"), "monthly": monthly},
    )
    ledger.commit(list(work.targets.values()))


def calculated_values(
    ledger: Ledger, facts: list[Fact], existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
) -> tuple[dict[tuple[int, int], Item], dict[tuple[str, str], Item]]:
    """Local arithmetic only; the handoff contains aggregates, not these intermediates."""
    expenses: set[str] = set()
    for fact in facts:
        known(fact.entity_type, fact.entity)
        for change in fact.changes:
            if change.counterpart is not None:
                recipient = known(change.counterpart.entity_type, change.counterpart.entity)
                if recipient.kind == "fiscal" and change.purpose == "当月饷":
                    expenses.add(recipient.key)
    rates = {expense_rate(key) for key in expenses if key != "建筑维护_base"} - {
        key for kind, key in existing if kind == "fiscal"
    }
    if rates:
        for row in ledger.entities(kind="fiscal", query=ENTITY_ROWS.where(E.key.in_(rates))):
            existing[row["kind"], row["key"]] = row
    if "建筑维护_base" in expenses:
        for row in ledger.entities(kind="building"):
            existing.setdefault((row["kind"], row["key"]), row)
    projected = {pair: {**row, "data": dict(row["data"])} for pair, row in existing.items()}
    values: dict[tuple[int, int], Item] = {}
    for i, j, fact in landing_facts(facts):
        if fact.entity_type == "account" and any(c.field == "taels" for c in fact.changes):
            continue
        data = projected[fact.entity_type, fact.entity]["data"]
        values[i, j] = field_values(fact, data, None)
        data.update(values[i, j]["changes"])
    return values, projected


def register_funding(
    ledger: Ledger,
    facts: list[Fact],
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> None:
    """Keep a funded affair in its source account's order, retaining explicit order."""
    grants = {name: known("affair", name).data["monthly_funding"]["account"]
              for name in dict.fromkeys(f.entity for f in facts if f.entity_type == "affair"
                                       and any(c.field == "monthly_funding" for c in f.changes))}
    if not grants:
        return
    orders = func.json_each(E.data["payment_order"]).table_valued("value", "type")
    order_value = case((orders.c.type == "object", orders.c.value), else_="{}")
    accounts = {row["key"] for row in ledger.entities(kind="account", query=ENTITY_ROWS.with_only_columns(E.key).where(
        select(orders.c.value).where(func.json_extract(order_value, "$.entity_type") == "affair",
                                    func.json_extract(order_value, "$.entity").in_(grants)).exists(),
    ))} | set(grants.values())
    for name, source in grants.items():
        recipient = EntityRef(entity_type="affair", entity=name).model_dump()
        for key in sorted(accounts):
            account = known("account", key)
            payment_order = list(account.data.get("payment_order", []))
            if account.key == source:
                if recipient not in payment_order:
                    payment_order.append(recipient)
            elif recipient in payment_order:
                payment_order.remove(recipient)
            if payment_order != account.data.get("payment_order", []):
                record(account, "payment_order", {"recipient": name}, {"payment_order": payment_order})


def landing_facts(facts: list[Fact]) -> Iterator[tuple[int, int, Fact]]:
    """Account deltas retain their original (fact, change) indices and order."""
    for i, fact in enumerate(facts):
        if fact.entity_type == "account" and any(c.field == "taels" for c in fact.changes):
            for j, change in enumerate(fact.changes):
                yield i, j, fact.model_copy(update={"changes": [change]})
        else:
            yield i, -1, fact


def record_decrees(
    result: Declaration | Unhandled,
    owner: Entity,
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> list[Entity]:
    decrees: list[Entity] = []
    if isinstance(result, NightDeclaration):
        for decree in result.decrees:
            data = {**decree.model_dump(), "night_id": str(owner.id)}
            entity = Entity("decree", "", "", data)
            record(entity, "decreed", data)
            decrees.append(entity)
            for endorsement in decree.endorsements:
                if endorsement.endorser != "御笔":
                    record(known("person", endorsement.endorser), "endorsed", {
                        "decree_id": str(entity.id), **endorsement.model_dump(),
                    })
            for person in decree.people:
                record(
                    known("person", person), "decreed", {"decree_id": str(entity.id)}
                )
    return decrees


def record_receipts(
    fact: Fact,
    detail: Item,
    date: Item,
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> None:
    amount = detail["actual"]["taels"]
    for change in fact.changes:
        if change.counterpart:
            recipient = known(change.counterpart.entity_type, change.counterpart.entity)
            changes: Item = {}
            if recipient.kind == "account":
                changes["taels"] = recipient.data["taels"] - amount
            elif change.purpose == "补欠" and has_obligation(
                "补欠", recipient.kind, recipient.data
            ):
                changes["arrears"] = max(
                    0, recipient.data.get("arrears", 0) + amount / WAN
                )
            elif change.purpose == "当月饷" and has_obligation(
                "当月饷", recipient.kind, recipient.data
            ):
                changes["month_paid"] = {
                    "date": date,
                    "amount": current_paid(recipient.data, date) - amount / WAN,
                }
            record(
                recipient,
                "received",
                {
                    "nominal": -change.value,
                    "actual": -amount,
                    "source": fact.entity,
                    "purpose": change.purpose,
                    "limit_reason": detail["limit_reason"],
                    "affair_id": str(known("affair", fact.affair).id)
                    if fact.affair is not None
                    else None,
                    "audience": "world",
                },
                changes,
            )


def decree_disposition(
    prior_interim: bool, decree: Entity, mode: LandingMode, events: Sequence[Item], translated: bool,
) -> list[tuple[str, Item]]:
    interim = decree.data.get("interim") or was_forced(events)
    return ([('interim', {"text": decree.data["text"]})]
            if interim and not prior_interim else []) + ([(mode, {"monthly": mode})] if translated else [])


def retire_chief(
    existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
    record: Callable[[Entity, str, Item, Item], None],
    association: Item,
    eligible: set[str],
) -> None:
    chief = existing.get(("incumbency", incumbency_record(("内阁首辅", ""), [])[0]))
    if not chief:
        return
    changes: Item = {role: [] for role in APPOINTMENT_ROLES
               if chief["data"][role] and chief["data"][role][0] not in eligible}
    if changes:
        appointment = known("incumbency", chief["key"])
        displace(appointment, changes, known, record, association)
        record(appointment, "changed", {**association, "changes": changes}, changes)


# This rule is shared by immediate and monthly landing, not a second dispatch path.
def displace(
    appointment: Entity,
    changes: Item,
    known: Callable[[str, str], Entity],
    record: Callable[[Entity, str, Item, Item], None],
    association: Item,
) -> None:
    for field in APPOINTMENT_ROLES:
        if field not in changes:
            continue
        previous = appointment.data[field]
        holders = changes[field]
        for person in dict.fromkeys([*previous, *holders]):
            if (person in previous) != (person in holders):
                record(known("person", person), "appointed" if person in holders else "displaced", {
                    "incumbency_id": str(appointment.id),
                    "office": appointment.data["office"],
                    "territory": appointment.data["territory"],
                    field: holders,
                    "role": field,
                    **association,
                }, {})
