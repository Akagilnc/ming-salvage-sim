"""Import authored world records; never infer titles from character prose."""

import json
from pathlib import Path

from ming.ledger import Entity, Ledger

CONTENT = Path(__file__).resolve().parents[2] / "content"
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
    ("official_titles", "offices", "office", ("name",)),
    ("territories", "territories", "territory", ("name",)),
    ("fiscal_config", "items", "fiscal", ("key",)),
    ("events", "", "historical_event", ("title",)),
]

REFERENCES = {
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
    appointments: dict[tuple[str, str], list[str]] = {}
    names = {
        kind: {r["id"]: r["name"] for r in json.loads((content / f"{filename}.json").read_text())[filename]}
        for kind, filename in (("region", "regions"), ("power", "powers"))
    }
    for filename, collection, kind, fields in COLLECTIONS:
        path = content / f"{filename}.json"
        try:
            records = json.loads(path.read_text())
            if collection:
                records = records[collection]
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        for index, record in enumerate(records):
            try:
                for (source, field), target in REFERENCES.items():
                    if source == kind and field in record:
                        record[field] = names.get(target, {}).get(record[field], record[field])
                if "id" in record and "name" in record:
                    record["id"] = record["name"]
                parts = [record[field] for field in fields]
                key = "·".join(p for p in parts if p) if kind == "class" else (
                    parts[0] if len(parts) == 1 else json.dumps(parts, ensure_ascii=False)
                )
                if kind == "person":
                    for appointment in record.pop("appointments"):
                        pair = appointment["office"], appointment["territory"]
                        appointments.setdefault(pair, []).append(key)
                entities.append(Entity(kind, key, f"{path.name}/{collection}", record))
            except (KeyError, TypeError) as exc:
                raise ValueError(f"{path}/{collection}[{index}]: {record!r}: {exc}") from exc
    entities.extend(
        Entity("incumbency", json.dumps(pair, ensure_ascii=False), "characters.json/appointments", {
            "office": pair[0], "territory": pair[1], "holders": holders,
        }) for pair, holders in appointments.items()
    )
    matrix = json.loads((content / "distance_matrix.json").read_text())["matrix"]
    entities.extend(
        Entity("distance", names["region"][origin], "distance_matrix.json", {
            names["region"][destination]: distance for destination, distance in routes.items()
        }) for origin, routes in matrix.items()
    )
    path = content / "minister_dossiers.json"
    try:
        dossiers = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    entities.extend(Entity("dossier", name, path.name, data) for name, data in dossiers.items())
    gazette = (content / "opening_gazette.md").read_text()
    entities.append(Entity("gazette", "opening", "opening_gazette.md", {"text": gazette}))
    ledger.commit(entities)
