"""Land a whole declaration, query rows and events in the same transaction."""

from collections.abc import Callable
from uuid import UUID

from ming.ledger import Entity, Item, Ledger
from ming.middle.declaration import Declaration, NightDeclaration
from ming.middle.translate import Unhandled
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
        entity.record(kind, words, {**detail, "date": date}, changes)
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
            detail = field_values(fact, entity.data, amounts.get(i))
            changes = detail["changes"]
            record(entity, "changed", detail, changes)
            if (
                entity.kind == "person"
                and {"office", "office_region"}.intersection(changes)
                and entity.data.get("office")
            ):
                displace(entity, existing, known, record)
        for i, fact in enumerate(result.facts):
            for change in fact.changes:
                if change.counterpart and change.counterpart.entity_type != "account":
                    record(
                        known(
                            change.counterpart.entity_type, change.counterpart.entity
                        ),
                        "received",
                        {
                            "nominal": -change.value,
                            "actual": -amounts[i],
                            "source": fact.entity,
                            "audience": "world",
                        },
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
    record(
        known(owner.kind, owner.key),
        "unhandled"
        if isinstance(result, Unhandled)
        else ("landed" if monthly else "translated"),
        {"result": result.model_dump()},
    )
    ledger.commit(list(changed.values()))


# This rule is shared by immediate and monthly landing, not a second dispatch path.
def displace(
    appointee: Entity,
    existing: dict[tuple[str, str], Item],
    known: Callable[[str, str], Entity],
    record: Callable[[Entity, str, Item, Item], None],
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
                    {"successor": appointee.key},
                    {"office": "", "status": "offstage"},
                )
