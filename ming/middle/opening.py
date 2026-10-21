"""Import world records, not rules; only identity is required from opening data."""

import json
from pathlib import Path

from ming.ledger import Entity, Ledger

CONTENT = Path(__file__).resolve().parents[2] / "content"
# filename, collection, entity kind, identity fields (composite where necessary).
COLLECTIONS = [
    ("characters", "characters", "person", ("name",)),
    ("characters", "factions", "faction", ("name",)),
    ("regions", "regions", "region", ("name",)),
    ("buildings", "buildings", "building", ("name",)),
    ("armies", "armies", "army", ("name",)),
    ("powers", "powers", "power", ("name",)),
    ("classes", "classes", "class", ("region_id", "name")),
    ("relation_seed", "events", "relationship", ("origin",)),
    ("relation_seed", "summaries", "relationship_summary", ("source", "target")),
    ("opening", "accounts", "account", ("name",)),
    ("opening", "calendar", "calendar", ("id",)),
    ("opening", "world", "world", ("name",)),
    ("multiple_offices", "offices", "office", ("name",)),
    ("offices", "priority", "office_type", ("type",)),
]

# Scalar entity references, shared by import and declaration validation.
# Army controller/commander and historical relationship names are prose, not keys.
REFERENCES = {
    ("person", "office"): "office",
    ("person", "office_region"): "region",
    ("person", "location"): "region",
    ("person", "power_id"): "power",
    ("army", "station_region"): "region",
    ("army", "owner_power"): "power",
    ("building", "region_id"): "region",
    ("class", "region_id"): "region",
    ("region", "controlled_by"): "power",
}


def import_opening(ledger: Ledger, content: Path) -> None:
    entities: list[Entity] = []
    names = {
        kind: {
            r["id"]: r["name"]
            for r in json.loads((content / f"{filename}.json").read_text())[filename]
        }
        for kind, filename in (("region", "regions"), ("power", "powers"))
    }
    for filename, collection, kind, fields in COLLECTIONS:
        path = content / f"{filename}.json"
        try:
            records = json.loads(path.read_text())[collection]
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        for index, record in enumerate(records):
            try:
                for (source, field), target in REFERENCES.items():
                    if source == kind and field in record:
                        record[field] = names.get(target, {}).get(
                            record[field], record[field]
                        )
                if "id" in record and "name" in record:
                    record["id"] = record["name"]
                parts = [record[field] for field in fields]
                key = (
                    "·".join(p for p in parts if p)
                    if kind == "class"
                    else (
                        parts[0]
                        if len(parts) == 1
                        else json.dumps(parts, ensure_ascii=False)
                    )
                )
                entities.append(Entity(kind, key, f"{path.name}/{collection}", record))
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"{path}/{collection}[{index}]: {record!r}: {exc}"
                ) from exc
    matrix = json.loads((content / "distance_matrix.json").read_text())["matrix"]
    entities.extend(
        Entity(
            "distance",
            names["region"][origin],
            "distance_matrix.json",
            {
                names["region"][destination]: distance
                for destination, distance in routes.items()
            },
        )
        for origin, routes in matrix.items()
    )
    path = content / "minister_dossiers.json"
    try:
        dossiers = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    entities.extend(
        Entity("dossier", name, path.name, data) for name, data in dossiers.items()
    )
    multi = {e.key for e in entities if e.kind == "office"}
    titles = {
        title
        for e in entities
        if e.kind == "person"
        for title in (e.data.get("office"), e.data.get("historical_office"))
        if title
    }
    entities.extend(
        Entity(
            "office",
            title,
            "characters.json/offices",
            {"name": title, "multiple": False},
        )
        for title in sorted(titles - multi)
    )
    gazette = (content / "opening_gazette.md").read_text()
    entities.append(
        Entity("gazette", "opening", "opening_gazette.md", {"text": gazette})
    )
    ledger.commit(entities)
