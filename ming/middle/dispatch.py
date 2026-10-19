"""Land one entire declaration atomically, on each affected entity."""

from ming.ledger import Entity, Ledger
from ming.middle.declaration import Declaration
from ming.middle.translate import Unhandled


def dispatch(
    ledger: Ledger, result: Declaration | Unhandled, emperor_words: str
) -> None:
    changed: dict[str, Entity] = {}
    existing = {(e["kind"], e["key"]): e for e in ledger.entities()}
    date = existing[("calendar", "world")]["data"]

    def known(kind: str, key: str) -> Entity:
        row = existing[(kind, key)]
        entity_id = str(row["id"])
        if entity_id not in changed:
            changed[entity_id] = ledger.get(row["id"])
        return changed[entity_id]

    def record(entity: Entity, kind: str, detail: dict[str, object]) -> None:
        entity.record(kind, emperor_words, {**detail, "date": date})
        changed[str(entity.id)] = entity

    if isinstance(result, Unhandled):
        decree = Entity("decree", "", "", {"emperor_words": emperor_words})
        record(decree, "unhandled", result.model_dump())
    else:
        for assign in result.assigns:
            affair = Entity("affair", assign.task, "", {"task": assign.task})
            record(affair, "assigned", {"assignees": assign.assignees})
            for person in dict.fromkeys(assign.assignees):
                record(
                    known("person", person), "assigned", {"affair_id": str(affair.id)}
                )
        for grant in result.grants:
            record(known("account", grant.account), "grant_nominal", grant.model_dump())
    ledger.commit(list(changed.values()))
