#!/usr/bin/env python3
"""F12 full-repo enum: audit/history whole-row dumps into material history API."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "evidence", "dist", "build", "web"}

AUDIT = (
    "person_logs",
    "army_logs",
    "building_logs",
    "power_logs",
    "region_logs",
    "population_transfer_ledger",
    "investigation_spoiled_facts",
    "office_change_records",
    "authority_records",
    "decree_cost_events",
    "dossier_loophole_exposures",
    "dossier_supervision_presence",
)
API = (
    "list_world_effect_history",
    "_world_effect_materials",
    "prepare_world_materials",
    "prepare_public_author_materials",
    "_write_world_tree",
)


def main() -> int:
    print("==== F12 FULL ENUM (history dump → materials) ====")
    print(f"ROOT={ROOT}")
    hits = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(p in SKIP for p in path.parts):
            continue
        rel = str(path.relative_to(ROOT))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not any(tok in line for tok in AUDIT + API):
                continue
            # Always emit materials/db history bridge.
            if rel in {"ming_sim/materials.py", "ming_sim/db.py"} or any(a in line for a in API):
                if line.lstrip().startswith("#") and "person_logs" not in line and "list_world" not in line:
                    continue
                print(f"{rel}:{i}:{line.rstrip()}")
                hits += 1
                continue
            # Other files: only when audit table couples to material/history supply.
            if any(t in line for t in AUDIT) and any(
                k in line for k in ("material", "list_world_effect", "history[")
            ):
                print(f"{rel}:{i}:{line.rstrip()}")
                hits += 1
    db = (ROOT / "ming_sim" / "db.py").read_text(encoding="utf-8")
    start = db.find("def list_world_effect_history")
    end = db.find("\n    def ", start + 1) if start >= 0 else -1
    body = db[start:end] if start >= 0 else ""
    # Dump loop = iterating audit table names into history[table] via SELECT.
    dump = (
        "for table in" in body
        and "person_logs" in body
        and ("army_logs" in body or "building_logs" in body)
        and "history[table]" in body
    )
    print(f"STRUCT list_world_effect_history_audit_dump_loop={'PRESENT' if dump else 'ABSENT'}")
    print(
        "STRUCT keeps="
        + ",".join(k for k in ("实况轨", "issues", "characters", "relation_edge_events") if k in body)
    )
    print(f"==== F12 HIT_COUNT={hits} ====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
