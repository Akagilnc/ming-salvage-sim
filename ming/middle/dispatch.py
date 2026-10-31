"""Land a whole declaration, query rows and events in the same transaction."""

import json
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
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
from ming.middle import queries
from ming.middle.rules import Names, check_journey, fail, field_values, money_amounts, name_expected
from ming.middle.fiscal import WAN, current_paid, expense_rate, has_obligation
from ming.middle.appointments import APPOINTMENT_ROLES, cabinet_members, incumbency_record, reference_key
from ming.middle.travel import journey_distances, move_person

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


def check_decrees(
    ledger: Ledger, out: Declaration, owner: Entity, names: Names, count: int,
) -> str:
    # One turn read supplies both validation IDs and the landing's emperor words.
    turns = ledger.facts(
        entity_id=UUID(owner.data["night_id"]) if owner.kind == "decree" else owner.id,
        kind="turn", query=FACT_ROWS.with_only_columns(F.emperor_words, F.detail["id"].as_string().label("turn_id")),
    ) if owner.kind != "calendar" else ()
    count = len(out.decrees) if isinstance(out, NightDeclaration) else count
    labeled = (("facts", out.facts), ("decree_events", out.decree_events))
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
            expected: object = allowed
            if endorsement.form != "御笔手敕":
                endorsement.endorser = reference_key(ledger, "person", endorsement.endorser, names)
                allowed = names.get("person", {})
                expected = name_expected("person", endorsement.endorser, names)
            if endorsement.endorser not in allowed:
                fail(
                    path + ".endorser",
                    endorsement.endorser,
                    expected,
                    names,
                    "参照 expected 的正名清单或输入目录指针核对 endorser，重交整份。",
                )


def prepare(
    ledger: Ledger, result: Declaration, owner: Entity,
    records: dict[tuple[str, str], Item], names: Names,
) -> None:
    sources = landing_sources(ledger, owner.data) if owner.kind == "calendar" else []
    existing = {pair: row for pair, row in records.items() if pair[0] in {"office", "incumbency"} and row["data"]}
    existing[owner.kind, owner.key] = owner.snapshot()
    records.update(((row["kind"], row["key"]), row) for row, _mode, _events in sources)
    changed: dict[tuple[str, str], Entity] = {}
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
    if result.facts or result.reports or result.decree_events:
        for fact in result.facts:
            known(fact.entity_type, fact.entity)
        distances = journey_distances(ledger, result.facts, {key: row["data"] for (kind, key), row in existing.items() if kind == "person"})
        values, projected = calculated_values(ledger, result.facts, existing, known)
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
                retire_chief(existing, known, record, {**association, "text": fact.text}, (i, fact, names))
            if (i, j) not in values:
                record_receipts(fact, detail, date, known, record)
        fact_origin = {}
        register_funding(ledger, result.facts, known, record)
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
    result.prepared = ([entity for entity in changed.values() if entity.pending_events], sources, words, date)


def dispatch(
    ledger: Ledger, result: Declaration | Unhandled, night_id: UUID,
    monthly: LandingMode | None = None,
) -> None:
    owner = ledger.get(night_id)
    changed, sources, words, date = result.prepared if isinstance(result, Declaration) and result.prepared is not None else (
        [], landing_sources(ledger, owner.data) if monthly and owner.kind == "calendar" else [], "\n".join(
            e["emperor_words"] for e in ledger.facts(entity_id=owner.id, kind="turn")
        ), owner.data if owner.kind == "calendar" else ledger.entities(kind="calendar", key="world")[0]["data"],
    )
    targets = {entity.id: entity for entity in changed}
    sources = [source for source in sources if source[1] is not None]
    prior_interims: set[UUID] = {event["entity_id"] for event in ledger.facts(
        entity_id=[row["id"] for row, _mode, _events in sources], kind="interim",
        query=FACT_ROWS.with_only_columns(F.entity_id).order_by(None).distinct(),
    )} if sources else set()
    for source in sources:
        target = targets.get(source[0]["id"])
        if target is None:
            target = ledger.get(source[0]["id"])
            targets[target.id] = target
        for kind, detail in decree_disposition(
            target.id in prior_interims, target, cast(LandingMode, source[1]), source[2],
            not isinstance(result, Unhandled),
        ):
            target.record(kind, words, {"origin_ref": str(owner.id), "date": date, **detail})
    target = targets.setdefault(owner.id, owner)
    target.record(
        "unhandled"
        if isinstance(result, Unhandled)
        else (monthly or "translated"),
        words,
        {"origin_ref": str(owner.id), "date": date, "result": result.model_dump(mode="json"), "monthly": monthly},
    )
    ledger.commit(list(targets.values()))


def calculated_values(
    ledger: Ledger, facts: list[Fact], existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
) -> tuple[dict[tuple[int, int], Item], dict[tuple[str, str], Item]]:
    """Local arithmetic only; the handoff contains aggregates, not these intermediates."""
    buildings_read = False
    for fact in facts:
        for change in fact.changes:
            if change.counterpart is None:
                continue
            recipient = known(change.counterpart.entity_type, change.counterpart.entity)
            if recipient.kind != "fiscal" or change.purpose != "当月饷":
                continue
            if recipient.key == "建筑维护_base":
                if not buildings_read:
                    for row in ledger.entities(kind="building"):
                        existing.setdefault((row["kind"], row["key"]), row)
                    buildings_read = True
            elif ("fiscal", expense_rate(recipient.key)) not in existing:
                for row in ledger.entities(kind="fiscal", key=expense_rate(recipient.key)):
                    existing[row["kind"], row["key"]] = row
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
    for name in dict.fromkeys(f.entity for f in facts if f.entity_type == "affair"
                              and any(c.field == "monthly_funding" for c in f.changes)):
        entity = known("affair", name)
        recipient = EntityRef(entity_type=entity.kind, entity=entity.key).model_dump()
        orders = func.json_each(E.data["payment_order"]).table_valued("value", "type")
        order = case((orders.c.type == "object", orders.c.value), else_="{}")
        accounts = {row["key"] for row in ledger.entities(kind="account", query=ENTITY_ROWS.with_only_columns(E.key).where(
            select(orders.c.value).where(func.json_extract(order, "$.entity_type") == "affair",
                                        func.json_extract(order, "$.entity") == entity.key).exists(),
        ))}
        accounts.add(entity.data["monthly_funding"]["account"])
        for key in sorted(accounts):
            account = known("account", key)
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
    declaration: tuple[int, Fact, Names],
) -> None:
    chief = existing.get(("incumbency", incumbency_record(("内阁首辅", ""), [])[0]))
    if not chief:
        return
    eligible = cabinet_members(existing)
    index, fact, names = declaration
    if fact.entity_type == "incumbency" and fact.entity == chief["key"]:
        for j, change in enumerate(fact.changes):
            for k, person in enumerate(change.value):
                if person not in eligible:
                    fail(f"facts[{index}].changes[{j}].value[{k}]", person, sorted(eligible), names,
                         "首辅须为在任阁臣；可在同份声明中先任大学士，再任首辅。重交整份。")
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
