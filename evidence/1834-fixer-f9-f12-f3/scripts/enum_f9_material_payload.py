#!/usr/bin/env python3
"""F9 full-repo enum: decoded dossier machine loads crossing into material supply.

Scope = production writers that build material trees / world affair files from
dossier rows. Prints every hit for human classification; does not delete.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "evidence", "dist", "build", "web"}

# Material-supply boundary tokens (not every DB payload_json).
PATTERNS = [
    re.compile(r"dossier\.items\(\)"),
    re.compile(r"_DOSSIER_MATERIAL_SKIP"),
    re.compile(r'endswith\("_json"\)'),
    re.compile(r'endswith\(\'_json\'\)'),
    re.compile(r"prepare_world_materials|prepare_public_author_materials|prepare_scene_materials|prepare_character_materials|_write_world_tree|_world_effect_materials"),
    re.compile(r'["\']payload["\']'),
    re.compile(r'["\']stigma["\']'),
    re.compile(r'["\']execution_signal["\']'),
    re.compile(r"ongoing_effects"),
    re.compile(r"list_decree_dossiers"),
]


def main() -> int:
    print("==== F9 FULL ENUM (material-supply boundary) ====")
    print(f"ROOT={ROOT}")
    hits = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(p in SKIP for p in path.parts):
            continue
        rel = path.relative_to(ROOT)
        # Focus production material / dossier bridge + tests that assert material payload shape.
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if not any(p.search(line) for p in PATTERNS):
                continue
            # Keep materials.py always; elsewhere require material/dossier dump context.
            if str(rel) == "ming_sim/materials.py" or any(
                k in line
                for k in (
                    "dossier.items()",
                    "_DOSSIER_MATERIAL_SKIP",
                    "endswith(\"_json\")",
                    "endswith('_json')",
                    "prepare_world_materials",
                    "prepare_public_author_materials",
                    "_write_world_tree",
                    "_world_effect_materials",
                )
            ):
                print(f"{rel}:{i}:{line.rstrip()}")
                hits += 1
                continue
            if str(rel).startswith("ming_sim/") and (
                ("payload" in line or "stigma" in line or "execution_signal" in line)
                and any(k in line for k in ("material", "dossier", "affair"))
            ):
                print(f"{rel}:{i}:{line.rstrip()}")
                hits += 1
    # Structural verdict on the known dump site.
    mat = (ROOT / "ming_sim" / "materials.py").read_text(encoding="utf-8")
    skip = "_DOSSIER_MATERIAL_SKIP" in mat and '"payload"' in mat and '"stigma"' in mat
    dump = "dossier.items()" in mat
    print(f"STRUCT dossier.items_dump={'PRESENT' if dump else 'ABSENT'}")
    print(f"STRUCT _DOSSIER_MATERIAL_SKIP_has_payload_stigma_signal={'YES' if skip else 'NO'}")
    print(f"==== F9 HIT_COUNT={hits} ====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
