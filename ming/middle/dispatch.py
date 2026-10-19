"""Land a whole declaration, query rows and events in the same transaction."""

from collections.abc import Callable
from uuid import UUID

from ming.ledger import Entity, Item, Ledger
from ming.middle.declaration import Declaration, TurnDeclaration
from ming.middle.translate import Unhandled


def dispatch(
    ledger: Ledger,
    result: Declaration | Unhandled,
    emperor_words: str,
    turn: tuple[UUID, str] | None = None,
) -> None:
    existing = {(e["kind"], e["key"]): e for e in ledger.entities()}
    changed: dict[tuple[str, str], Entity] = {}
    date = existing[("calendar", "world")]["data"]

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
        entity.record(kind, emperor_words, {**detail, "date": date}, changes)
        changed[(entity.kind, entity.key)] = entity
        existing[(entity.kind, entity.key)] = entity.snapshot()

    if not isinstance(result, Unhandled):
        for fact in result.facts:
            pair = fact.entity_type, fact.entity
            entity = Entity(*pair, "", {}) if fact.create else known(*pair)
            changes = {c.field: c.value for c in fact.changes}
            record(entity, "changed", {"text": fact.text, "changes": changes}, changes)
            if entity.kind == "person" and "office" in changes and changes["office"]:
                displace(entity, existing, known, record)
        if isinstance(result, TurnDeclaration):
            for decree in result.decrees:
                data = decree.model_dump(exclude={"people"})
                if turn:
                    data.update({"night_id": str(turn[0]), "turn_id": turn[1]})
                entity = Entity("decree", "", "", data)
                record(entity, "decreed", data)
                for person in decree.people:
                    record(
                        known("person", person),
                        "decreed",
                        {"decree_id": str(entity.id)},
                    )
            for assent in result.assents:
                record(
                    known("decree", assent.decree_id),
                    "assent",
                    assent.model_dump(),
                    {"stance": assent.stance},
                )
    if turn:
        night = ledger.get(turn[0])
        record(
            night,
            "unhandled" if isinstance(result, Unhandled) else "translated",
            {
                "turn_id": turn[1],
                "result": result.model_dump(),
            },
        )
        if (
            isinstance(result, TurnDeclaration)
            and result.dismiss
            and not night.data["closed"]
        ):
            record(night, "dismissed", {}, {"closed": True})
    elif isinstance(result, Unhandled):
        entity = Entity("decree", "", "", {"emperor_words": emperor_words})
        record(entity, "unhandled", result.model_dump())
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
