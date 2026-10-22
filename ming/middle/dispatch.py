"""Land a whole declaration, query rows and events in the same transaction."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_

from ming.ledger import Entity, Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, FACT_COLUMNS as F, FACT_ROWS
from ming.middle.declaration import Declaration, LandingMode, NightDeclaration, Unhandled
from ming.middle.rules import field_values, money_amounts


def landing_entities(
    ledger: Ledger, result: Declaration | Unhandled, owner: Entity
) -> dict[tuple[str, str], Item]:
    pairs = {("calendar", "world"), (owner.kind, owner.key)}
    if not isinstance(result, Unhandled):
        pairs.update(
            (f.entity_type, f.entity) for f in [*result.facts, *result.reports]
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
    if isinstance(result, Unhandled):
        return found
    # Only a location change can start a journey (from the current or a first
    # location), and only an office/region change can displace its incumbents.
    origins: set[str] = set()
    offices: set[str] = set()
    for fact in result.facts:
        if fact.entity_type != "person":
            continue
        held = found.get(("person", fact.entity), {"data": {}})["data"]
        changes = {c.field: c.value for c in fact.changes}
        if "location" in changes:
            origins.add(held.get("location") or str(changes["location"]))
        if {"office", "office_region"}.intersection(changes):
            offices.add(str(changes.get("office", held.get("office", ""))))
    offices.discard("")
    if origins or offices:
        for e in ledger.read(
            ENTITY_ROWS.where(
                or_(
                    and_(E.kind == "distance", E.key.in_(origins)),
                    and_(E.kind == "office", E.key.in_(offices)),
                    and_(E.kind == "person", E.data["office"].as_string().in_(offices)),
                )
            )
        ):
            found.setdefault((e["kind"], e["key"]), e)
    return found


def dispatch(
    ledger: Ledger,
    result: Declaration | Unhandled,
    night_id: UUID,
    monthly: LandingMode | None = None,
    baselines: dict[tuple[str, str, str], Any] | None = None,
) -> None:
    owner = ledger.get(night_id)
    existing = landing_entities(ledger, result, owner)
    changed: dict[tuple[str, str], Entity] = {}
    date = existing[("calendar", "world")]["data"]
    origin = (
        ledger.get(UUID(owner.data["night_id"])) if owner.kind == "decree" else owner
    )
    words = "\n".join(
        e["emperor_words"] for e in ledger.facts(entity_id=origin.id, kind="turn")
    )

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

    def record_facts(output: Declaration) -> None:
        amounts = money_amounts(output.facts, existing)
        # A share declares post-values from the reading it saw. Shares landed
        # since then shift the whole share once: none overwrites another, and
        # its own successive facts stay the progression it declared.
        offsets = {
            key: existing[key[:2]]["data"][key[2]] - value
            for key, value in (baselines or {}).items()
            if key[:2] in existing
        }
        for fact in output.facts:
            pair = fact.entity_type, fact.entity
            if fact.create and pair not in existing:
                entity = Entity(*pair, "", {})
                changed[pair] = entity
                existing[pair] = entity.snapshot()
        for i, fact in enumerate(output.facts):
            entity = known(fact.entity_type, fact.entity)
            association = (
                {"affair_id": str(known("affair", fact.affair).id)}
                if fact.affair is not None
                else {}
            )
            detail = field_values(fact, entity.data, amounts.get(i), offsets)
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
        record_receipts(output, amounts, known, record)
        for report in output.reports:
            record(
                known(report.entity_type, report.entity),
                "reported",
                report.model_dump(),
            )
    if not isinstance(result, Unhandled):
        record_facts(result)
    if isinstance(result, NightDeclaration):
        record_decrees(result, night_id, known, record)
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
        else (monthly or "translated"),
        {"result": result.model_dump(), "monthly": monthly},
    )
    ledger.commit(list(changed.values()))


def record_decrees(
    result: NightDeclaration,
    night_id: UUID,
    known: Callable[[str, str], Entity],
    record: Callable[..., None],
) -> None:
    for decree in result.decrees:
        data = {**decree.model_dump(), "night_id": str(night_id)}
        entity = Entity("decree", "", "", data)
        record(entity, "decreed", data)
        for endorsement in decree.endorsements:
            if endorsement.endorser != "御笔":
                record(known("person", endorsement.endorser), "endorsed", {
                    "decree_id": str(entity.id), **endorsement.model_dump(),
                })
        for person in decree.people:
            record(known("person", person), "decreed", {"decree_id": str(entity.id)})


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
    if ledger.facts(entity_id=decree.id, kind="interim"):
        return None
    if decree.data.get("interim"):
        return decree.data["text"]
    verdict = next(
        (
            e["detail"]
            for e in ledger.facts(entity_id=decree.id, kind="deliberation", date=date)
        ),
        None,
    )
    forced = next(
        (
            e["detail"]
            for e in ledger.facts(entity_id=decree.id, kind="choice", date=date)
            if e["detail"]["text"] == "强颁"
        ),
        None,
    )
    if forced and verdict:
        return ledger.facts(
            entity_id=UUID(verdict["route_id"]),
            kind="simulation",
            date=date,
            query=FACT_ROWS.where(
                F.detail["petition_id"].as_string() == forced["petition_id"]
            ),
        )[0]["detail"]["output"]["text"]
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
