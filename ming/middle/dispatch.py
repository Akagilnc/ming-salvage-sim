"""Land a whole declaration, query rows and events in the same transaction."""

import json
from collections.abc import Callable, Iterator, Sequence
from typing import cast
from uuid import UUID

from ming.ledger import Entity, Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS
from ming.middle.declaration import (
    Declaration,
    EntityRef,
    Fact,
    LandingMode,
    NightDeclaration,
    Unhandled,
)
from ming.middle import queries
from ming.middle.rules import field_values, money_amounts
from ming.middle.fiscal import WAN, current_paid, has_obligation
from ming.middle.appointments import APPOINTMENT_ROLES, cabinet_members, cabinet_records, incumbency_record
from ming.middle.travel import move_person

def landing_entities(
    ledger: Ledger, result: Declaration | Unhandled, owner: Entity,
    sources: Sequence[tuple[UUID, LandingMode | None]] = (),
) -> dict[tuple[str, str], Item]:
    pairs = {("calendar", "world"), (owner.kind, owner.key)}
    if not isinstance(result, Unhandled):
        pairs.update(
            (f.entity_type, f.entity)
            for f in [*result.facts, *result.reports]
        )
        pairs.update(
            (c.counterpart.entity_type, c.counterpart.entity)
            for f in result.facts for c in f.changes if c.counterpart
        )
        pairs.update(
            ("person", name) for f in result.facts if f.entity_type == "incumbency"
            for c in f.changes if c.field in APPOINTMENT_ROLES for name in c.value
        )
        pairs.update(("affair", f.affair) for f in result.facts if f.affair is not None)
    if isinstance(result, NightDeclaration):
        pairs.update(("person", p) for d in result.decrees for p in d.people)
        pairs.update(("person", e.endorser) for d in result.decrees for e in d.endorsements if e.endorser != "御笔")
    found = {
        (e["kind"], e["key"]): e
        for kind, key in sorted(pairs)
        for e in ledger.entities(kind=kind, key=key)
    }
    # Fact origins need only IDs; decree events and dispositions need entities.
    references: set[int | None] = set() if isinstance(result, Unhandled) else {e.decree for e in result.decree_events}
    found.update(((row["kind"], row["key"]), row) for row in ledger.entities(entity_id=[
        source for index, (source, mode) in enumerate(sources)
        if mode is not None or index in references
    ]))
    if isinstance(result, Unhandled):
        return found
    if any(f.entity_type == "affair" and any(c.field == "monthly_funding" for c in f.changes) for f in result.facts):
        found.update(((e["kind"], e["key"]), e) for e in ledger.entities(kind="account"))
    if any(f.entity_type == "incumbency" for f in result.facts):
        found.update(cabinet_records(ledger))
    if any(
        c.counterpart
        and c.counterpart.entity_type == "fiscal"
        and c.purpose == "当月饷"
        for f in result.facts
        for c in f.changes
    ):
        found.update(
            ((e["kind"], e["key"]), e)
            for e in ledger.entities(kind=("fiscal", "building"))
        )
    incumbents = {name for (kind, _), row in found.items() if kind == "incumbency" for field in APPOINTMENT_ROLES for name in row["data"][field]}
    for e in ledger.entities(kind="person", query=ENTITY_ROWS.where(E.key.in_(incumbents))):
        found.setdefault((e["kind"], e["key"]), e)
    return found


def landing_sources(
    ledger: Ledger, date: Item, *, include_history: bool = True,
) -> list[tuple[Item, LandingMode | None]]:
    """The ordered decree references shared by monthly input, validation and landing."""
    sources: dict[UUID, tuple[Item, LandingMode | None]] = {
        row["id"]: (row, "landed") for row in ledger.read(queries.errands(date))
    }
    for row in ledger.read(queries.decrees_with("deliberation", date)):
        events = [(f["kind"], f["detail"]) for f in ledger.facts(
            entity_id=row["id"], kind=("deliberation", "choice"), date=date,
        )]
        verdict = latest_detail(events, "deliberation")
        choice = latest_detail(events, "choice")
        mode: LandingMode | None = None
        if verdict and (verdict["verdict"] == "准" or (choice and choice["text"] == "强颁")):
            mode = "landed"
        elif row["data"].get("interim"):
            mode = "attempted"
        sources[row["id"]] = (row, mode)
    if include_history:
        for row in ledger.read(ENTITY_ROWS.where(queries.public_decree())):
            sources.setdefault(row["id"], (row, None))
    return list(sources.values())


def dispatch(
    ledger: Ledger,
    result: Declaration | Unhandled,
    night_id: UUID,
    monthly: LandingMode | None = None,
    sources: Sequence[tuple[UUID, LandingMode | None]] = (),
) -> None:
    owner = ledger.get(night_id)
    existing = landing_entities(ledger, result, owner, sources)
    changed: dict[tuple[str, str], Entity] = {}
    fact_origin: Item = {}
    date = existing[("calendar", "world")]["data"]
    words = "\n".join(
        e["emperor_words"]
        for e in ledger.facts(
            entity_id=UUID(owner.data["night_id"]) if owner.kind == "decree" else owner.id,
            kind="turn",
        )
    )

    def known(kind: str, key: str) -> Entity:
        pair = kind, key
        if pair not in changed:
            if pair in existing:
                changed[pair] = ledger.get(existing[pair]["id"])
            else:
                data: Item = incumbency_record(json.loads(key), [])[1] if kind == "incumbency" else {}
                changed[pair] = Entity(*pair, "", data)
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

    decrees = [decree.id for decree in record_decrees(result, owner, known, record)] + [
        source for source, _mode in sources
    ]
    decree_keys = {row["id"]: row["key"] for row in existing.values() if row["kind"] == "decree"}
    if not isinstance(result, Unhandled):
        for fact in result.facts:
            pair = fact.entity_type, fact.entity
            if (fact.create or fact.entity_type == "incumbency") and pair not in existing:
                existing[pair] = known(fact.entity_type, fact.entity).snapshot()
        amounts, reasons = money_amounts(result.facts, existing)
        for i, j, fact in landing_facts(result.facts):
            entity = known(fact.entity_type, fact.entity)
            association = (
                {"affair_id": str(known("affair", fact.affair).id)}
                if fact.affair is not None
                else {}
            )
            detail = field_values(fact, entity.data, amounts.get((i, j)))
            detail.update(association)
            if (i, j) in reasons:
                detail["limit_reason"] = reasons[i, j]
            fact_origin = {
                "discovered": fact.discovered,
                **({"origin_ref": str(decrees[fact.decree])} if fact.decree is not None else {}),
            }
            changes = detail["changes"]
            if entity.kind == "person":
                move_person(entity, changes, ledger, record, date)
            if entity.kind == "incumbency":
                displace(entity, changes, known, record, {**association, "text": fact.text})
            record(entity, "changed", detail, changes)
            retire_chief(existing, known, record, {**association, "text": fact.text})
            if (i, j) in amounts:
                record_receipts(fact, amounts[i, j], reasons[i, j], known, record)
        fact_origin = {}
        register_funding(result.facts, existing, known, record)
        for report in result.reports:
            record(
                known(report.entity_type, report.entity),
                "reported",
                report.model_dump(),
            )
        for event in result.decree_events:
            target = known("decree", decree_keys[decrees[cast(int, event.decree)]])
            fact_origin = {"origin_ref": str(target.id)}
            record(target, event.kind, {"text": event.text})
        fact_origin = {}
    for index, mode in ((i, mode) for i, (_source, mode) in enumerate(sources) if mode is not None):
        target = known("decree", decree_keys[decrees[index]])
        for kind, detail in decree_disposition(ledger, target, cast(LandingMode, mode), date, not isinstance(result, Unhandled)):
            record(target, kind, detail)
    record(
        known(owner.kind, owner.key),
        "unhandled"
        if isinstance(result, Unhandled)
        else (monthly or "translated"),
        {"result": result.model_dump(mode="json"), "monthly": monthly},
    )
    ledger.commit(list(changed.values()))


def register_funding(
    facts: list[Fact],
    existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> None:
    """Keep a funded affair in its source account's order, retaining explicit order."""
    for fact in facts:
        if fact.entity_type != "affair" or not any(c.field == "monthly_funding" for c in fact.changes):
            continue
        entity = known("affair", fact.entity)
        recipient = EntityRef(entity_type=entity.kind, entity=entity.key).model_dump()
        for kind, key in list(existing):
            if kind != "account":
                continue
            account = known(kind, key)
            order = list(account.data.get("payment_order", []))
            if key == entity.data["monthly_funding"]["account"]:
                if recipient not in order:
                    order.append(recipient)
            elif recipient in order:
                order.remove(recipient)
            if order != account.data.get("payment_order", []):
                record(account, "payment_order", {"recipient": entity.key}, {"payment_order": order})


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
    amount: float,
    reason: str | None,
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> None:
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
                date = known("calendar", "world").data
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
                    "limit_reason": reason,
                    "affair_id": str(known("affair", fact.affair).id)
                    if fact.affair is not None
                    else None,
                    "audience": "world",
                },
                changes,
            )


def latest_detail(events: Sequence[tuple[str, Item]], kind: str) -> Item | None:
    """Latest deliberation or choice of this month, the row both landing and interim use."""
    return next(
        (detail for event_kind, detail in reversed(events) if event_kind == kind),
        None,
    )


def decree_disposition(
    ledger: Ledger, decree: Entity, mode: LandingMode, date: Item, translated: bool,
) -> list[tuple[str, Item]]:
    events = [(row["kind"], row["detail"]) for row in ledger.facts(
        entity_id=decree.id, kind=("deliberation", "choice"), date=date,
    )]
    choice = latest_detail(events, "choice")
    interim = decree.data.get("interim") or (
        choice and choice["text"] == "强颁" and latest_detail(events, "deliberation")
    )
    return ([('interim', {"text": decree.data["text"]})]
            if interim and not ledger.facts(entity_id=decree.id, kind="interim") else []) + ([(mode, {"monthly": mode})] if translated else [])


def retire_chief(
    existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
    record: Callable[[Entity, str, Item, Item], None],
    association: Item,
) -> None:
    chief = existing.get(("incumbency", incumbency_record(("内阁首辅", ""), [])[0]))
    if not chief:
        return
    eligible = cabinet_members(existing)
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
