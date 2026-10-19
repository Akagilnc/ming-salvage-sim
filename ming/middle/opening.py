"""Import world records, not rules; only identity is required from opening data."""

import json
from pathlib import Path

from ming.ledger import Entity, Ledger

CONTENT = Path(__file__).resolve().parents[2] / "content"
# filename, collection, entity kind, identity fields (composite where necessary).
COLLECTIONS = [
    ("characters", "characters", "person", ("name",)),
    ("characters", "factions", "faction", ("name",)),
    ("regions", "regions", "region", ("id",)),
    ("buildings", "buildings", "building", ("id",)),
    ("armies", "armies", "army", ("id",)),
    ("powers", "powers", "power", ("id",)),
    ("classes", "classes", "class", ("name", "region_id")),
    ("relation_seed", "events", "relationship", ("origin",)),
    ("relation_seed", "summaries", "relationship_summary", ("source", "target")),
    ("opening", "accounts", "account", ("name",)),
    ("opening", "calendar", "calendar", ("id",)),
]


def import_opening(ledger: Ledger, content: Path) -> None:
    entities: list[Entity] = []
    for filename, collection, kind, fields in COLLECTIONS:
        path = content / f"{filename}.json"
        try:
            records = json.loads(path.read_text())[collection]
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        for index, record in enumerate(records):
            try:
                parts = [record[field] for field in fields]
                key = (
                    parts[0]
                    if len(parts) == 1
                    else json.dumps(parts, ensure_ascii=False)
                )
                entities.append(Entity(kind, key, f"{path.name}/{collection}", record))
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"{path}/{collection}[{index}]: {record!r}: {exc}"
                ) from exc
    path = content / "minister_dossiers.json"
    try:
        dossiers = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    entities.extend(
        Entity("dossier", name, path.name, data) for name, data in dossiers.items()
    )
    ledger.commit(entities)
