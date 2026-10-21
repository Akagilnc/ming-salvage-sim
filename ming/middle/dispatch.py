"""Land a whole declaration, query rows and events in the same transaction."""

from collections.abc import Callable
from uuid import UUID

from ming.ledger import Entity, Item, Ledger
from ming.middle.declaration import Declaration, NightDeclaration, Unhandled
from ming.middle.rules import field_values, money_amounts


def dispatch(
    ledger: Ledger,
    result: Declaration | Unhandled,
    night_id: UUID,
    monthly: bool = False,
) -> None:
    existing = {(e["kind"], e["key"]): e for e in ledger.entities()}
    changed: dict[tuple[str, str], Entity] = {}
    date = existing[("calendar", "world")]["data"]
    owner = ledger.get(night_id)
    origin = (
        ledger.get(UUID(owner.data["night_id"])) if owner.kind == "decree" else owner
    )
    words = "\n".join(e["emperor_words"] for e in origin.events if e["kind"] == "turn")

    def known(kind: str, key: str) -> Entity:
        pair = kind, key
        if pair not in changed:
            changed[pair] = ledger.get(existing[pair]["id"])
        return changed[pair]

    def record(
        entity: Entity,
        kind: str,
        detail: dict[str, object],
        changes: dict[str, object] | None = None,
    ) -> None:
        entity.record(
            kind, words, {**detail, "origin_ref": str(owner.id), "date": date}, changes
        )
        changed[(entity.kind, entity.key)] = entity
        existing[(entity.kind, entity.key)] = entity.snapshot()

    if not isinstance(result, Unhandled):
        amounts = money_amounts(result.facts, existing)
        for fact in result.facts:
            pair = fact.entity_type, fact.entity
            if fact.create and pair not in existing:
                entity = Entity(*pair, "", {})
                changed[pair] = entity
                existing[pair] = entity.snapshot()
        for i, fact in enumerate(result.facts):
            entity = known(fact.entity_type, fact.entity)
            association = (
                {"affair_id": str(known("affair", fact.affair).id)}
                if fact.affair is not None
                else {}
            )
            detail = field_values(fact, entity.data, amounts.get(i))
            detail.update(association)
            changes = detail["changes"]
            if entity.kind == "person":
                move_person(entity, changes, existing, record)
            record(entity, "changed", detail, changes)
            if (
                entity.kind == "person"
                and {"office", "office_region"}.intersection(changes)
                and entity.data.get("office")
            ):
                displace(entity, existing, known, record, association)
        record_receipts(result, amounts, known, record)
        for report in result.reports:
            record(
                known(report.entity_type, report.entity),
                "reported",
                report.model_dump(),
            )
    if isinstance(result, NightDeclaration):
        for decree in result.decrees:
            data = decree.model_dump()
            data["night_id"] = str(night_id)
            entity = Entity("decree", "", "", data)
            record(entity, "decreed", data)
            for person in decree.people:
                record(
                    known("person", person),
                    "decreed",
                    {"decree_id": str(entity.id)},
                )
    if (
        monthly
        and owner.kind == "decree"
        and (mark := interim_mark(ledger, owner, date)) is not None
    ):
        record(known(owner.kind, owner.key), "interim", {"text": mark})
    record(
        known(owner.kind, owner.key),
        "unhandled"
        if isinstance(result, Unhandled)
        else ("landed" if monthly else "translated"),
        {"result": result.model_dump()},
    )
    ledger.commit(list(changed.values()))


def record_receipts(
    result: Declaration,
    amounts: dict[int, float],
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> None:
    for i, fact in enumerate(result.facts):
        for change in fact.changes:
            if change.counterpart and change.counterpart.entity_type != "account":
                record(
                    known(change.counterpart.entity_type, change.counterpart.entity),
                    "received",
                    {
                        "nominal": -change.value,
                        "actual": -amounts[i],
                        "source": fact.entity,
                        "affair_id": str(known("affair", fact.affair).id)
                        if fact.affair is not None
                        else None,
                        "audience": "world",
                    },
                )


def interim_mark(ledger: Ledger, decree: Entity, date: Item) -> str | None:
    verdict = next(
        (
            e["detail"]
            for e in decree.events
            if e["kind"] == "deliberation" and e["detail"]["date"] == date
        ),
        None,
    )
    forced = next(
        (
            e["detail"]
            for e in decree.events
            if e["kind"] == "choice"
            and e["detail"]["date"] == date
            and e["detail"]["text"] == "强颁"
        ),
        None,
    )
    if forced and verdict:
        route = ledger.get(UUID(verdict["route_id"]))
        return next(
            e["detail"]["output"]["text"]
            for e in route.events
            if e["kind"] == "simulation"
            and e["detail"].get("petition_id") == forced["petition_id"]
        )
    return None


def move_person(
    person: Entity,
    changes: dict[str, object],
    existing: dict[tuple[str, str], Item],
    record: Callable[[Entity, str, Item, Item], None],
) -> None:
    # A first location is a fact, not a journey from an invented origin.
    if not person.data.get("location"):
        return
    destination = changes.pop("location", person.data["location"])
    if changes.get("status") not in (None, "active"):
        # Leaving active (卒/下狱/罢黜/归场) clears the journey like offstage does.
        changes.update(transit_to="", remaining_distance=0, waiting_audience=False)
    elif destination != person.data.get("location") and not person.data.get(
        "transit_to"
    ):
        distance = existing[("distance", person.data["location"])]["data"][destination]
        changes["travel_speed"] = changes.get("travel_speed", 1)
        record(
            person,
            "departed",
            {
                "destination": destination,
                "distance": distance,
                "travel_speed": changes["travel_speed"],
            },
            {
                "transit_to": destination,
                "remaining_distance": distance,
                "travel_speed": changes["travel_speed"],
                "waiting_audience": False,
            },
        )
        changes["status"] = "active"
    elif person.data.get("transit_to"):
        changes["status"] = "active"


# This rule is shared by immediate and monthly landing, not a second dispatch path.
def displace(
    appointee: Entity,
    existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
    record: Callable[[Entity, str, Item, Item], None],
    association: Item,
) -> None:
    office = appointee.data["office"]
    office_row = existing.get(("office", office))
    if office_row and office_row["data"]["multiple"]:
        return
    for (kind, key), row in existing.items():
        if kind == "person" and key != appointee.key:
            if row["data"].get("office") == office and row["data"].get(
                "office_region", ""
            ) == appointee.data.get("office_region", ""):
                record(
                    known(kind, key),
                    "displaced",
                    {"successor": appointee.key, **association},
                    {
                        "office": "",
                        "status": "offstage",
                        "transit_to": "",
                        "remaining_distance": 0,
                        "waiting_audience": False,
                    },
                )
