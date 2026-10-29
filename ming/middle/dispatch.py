"""Land a whole declaration, query rows and events in the same transaction."""

import json
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import tuple_

from ming.ledger import Entity, Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, FACT_ROWS
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
from ming.middle.travel import journey_distances, journey_route, move_person

def landing_entities(
    ledger: Ledger, result: Declaration | Unhandled, owner: Entity,
    sources: Sequence[tuple[Item, LandingMode | None, list[Item]]] = (),
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
    # Reuse the owner and source rows already acquired by this dispatch.
    found = {(owner.kind, owner.key): owner.snapshot()}
    references: set[int | None] = set() if isinstance(result, Unhandled) else {e.decree for e in result.decree_events}
    found.update(((row["kind"], row["key"]), row) for index, (row, mode, _events) in enumerate(sources)
                 if mode is not None or index in references)
    if not isinstance(result, Unhandled):
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
    if missing := sorted(pairs - found.keys()):
        found.update({
            (e["kind"], e["key"]): e
            for e in ledger.entities(query=ENTITY_ROWS.where(tuple_(E.kind, E.key).in_(missing)))
        })
    incumbents = {name for (kind, _), row in found.items() if kind == "incumbency" for field in APPOINTMENT_ROLES for name in row["data"][field]}
    incumbents.difference_update(key for kind, key in found if kind == "person")
    for e in (ledger.entities(kind="person", query=ENTITY_ROWS.where(E.key.in_(incumbents))) if incumbents else ()):
        found[e["kind"], e["key"]] = e
    # Keep the original keyed-target order before supplemental rows.
    return {**{pair: found[pair] for pair in sorted(pairs) if pair in found}, **found}


def landing_sources(
    ledger: Ledger, date: Item, *, include_history: bool = True,
) -> list[tuple[Item, LandingMode | None, list[Item]]]:
    """Ordered sources, retaining decisions already read while resolving their mode."""
    records = ledger.entities(query=queries.landing_rows(date, include_history=include_history))
    if not records:
        return []
    decisions: dict[UUID, list[Item]] = defaultdict(list)
    for event in ledger.facts(entity_id=[row["id"] for row in records], kind=("deliberation", "choice"), date=date):
        decisions[event["entity_id"]].append(event)
    sources: list[tuple[Item, LandingMode | None, list[Item]]] = []
    for row in records:
        mode: LandingMode | None = "landed" if row.pop("errand") else None
        events = decisions[row["id"]]
        if row.pop("deliberated"):
            verdict = latest_detail(events, "deliberation")
            choice = latest_detail(events, "choice")
            mode = None
            if verdict and (verdict["verdict"] == "准" or (choice and choice["text"] == "强颁")):
                mode = "landed"
            elif row["data"].get("interim"):
                mode = "attempted"
        sources.append((row, mode, events))
    return sources


def dispatch(
    ledger: Ledger,
    result: Declaration | Unhandled,
    night_id: UUID,
    monthly: LandingMode | None = None,
) -> None:
    owner = ledger.get(night_id)
    sources = landing_sources(ledger, owner.data) if monthly and owner.kind == "calendar" else []
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
                changed[pair] = owner if existing[pair]["id"] == owner.id else ledger.get(existing[pair]["id"])
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

    decrees = [(decree.id, decree.key) for decree in record_decrees(result, owner, known, record)] + [
        (row["id"], row["key"]) for row, _mode, _events in sources
    ]
    if not isinstance(result, Unhandled):
        distances = journey_distances(ledger, result.facts, {key: row["data"] for (kind, key), row in existing.items() if kind == "person"})
        for fact in result.facts:
            if (fact.create or fact.entity_type == "incumbency") and (fact.entity_type, fact.entity) not in existing:
                existing[fact.entity_type, fact.entity] = known(fact.entity_type, fact.entity).snapshot()
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
                **({"origin_ref": str(decrees[fact.decree][0])} if fact.decree is not None else {}),
            }
            if entity.kind == "person":
                move_person(entity, detail["changes"], journey_route(distances, entity.data, detail["changes"]), record, date)
            if entity.kind == "incumbency":
                displace(entity, detail["changes"], known, record, {**association, "text": fact.text})
            record(entity, "changed", detail, detail["changes"])
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
            target = known("decree", decrees[cast(int, event.decree)][1])
            fact_origin = {"origin_ref": str(target.id)}
            record(target, event.kind, {"text": event.text})
        fact_origin = {}
    sources = [source for source in sources if source[1] is not None]
    prior_interims: set[UUID] = {event["entity_id"] for event in ledger.facts(
        entity_id=[row["id"] for row, _mode, _events in sources], kind="interim",
        query=FACT_ROWS.with_only_columns(F.entity_id).order_by(None).distinct(),
    )} if sources else set()
    for source in sources:
        target = known("decree", source[0]["key"])
        for kind, detail in decree_disposition(
            target.id in prior_interims, target, cast(LandingMode, source[1]), source[2],
            not isinstance(result, Unhandled),
        ):
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


def latest_detail(events: Sequence[Item], kind: str) -> Item | None:
    """Latest deliberation or choice of this month, the row both landing and interim use."""
    return next(
        (event["detail"] for event in reversed(events) if event["kind"] == kind),
        None,
    )


def decree_disposition(
    prior_interim: bool, decree: Entity, mode: LandingMode, events: Sequence[Item], translated: bool,
) -> list[tuple[str, Item]]:
    choice = latest_detail(events, "choice")
    interim = decree.data.get("interim") or (
        choice and choice["text"] == "强颁" and latest_detail(events, "deliberation")
    )
    return ([('interim', {"text": decree.data["text"]})]
            if interim and not prior_interim else []) + ([(mode, {"monthly": mode})] if translated else [])


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
