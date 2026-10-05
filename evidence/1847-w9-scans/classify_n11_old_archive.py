#!/usr/bin/env python3
"""#1847 w9 N11-R2 — classify old-archive-specialized production by real consumers.

Not a refcount scan. Each member is judged by whether it only exists to serve
pre-current-format saves / old seed fingerprints / old-column drops.

Replay:
  MING_SIM_*_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w9-scans/classify_n11_old_archive.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _exists(rel: str, needle: str) -> bool:
    path = ROOT / rel
    if not path.exists():
        return False
    return needle in path.read_text(encoding="utf-8")


def main() -> None:
    members = [
        # named / clear deletes this round
        ("_known_opening_gazette_seed_text", "ming_sim/db.py", "DELETE_DONE",
         "fingerprint reader for old seed purge only", "absent" if not _exists("ming_sim/db.py", "def _known_opening_gazette_seed_text") else "STILL_PRESENT"),
        ("_purge_fixed_opening_gazette_seed", "ming_sim/db.py", "DELETE_DONE",
         "old-save exact DELETE of fixed opening gazette", "absent" if not _exists("ming_sim/db.py", "def _purge_fixed_opening_gazette_seed") else "STILL_PRESENT"),
        ("content/opening_gazette.md", "content/", "DELETE_DONE",
         "fingerprint file only; seed_opening_gazette no longer writes it", "absent" if not (ROOT / "content/opening_gazette.md").exists() else "STILL_PRESENT"),
        ("tests/test_opening_gazette_delete_1356.py", "tests/", "DELETE_DONE",
         "exclusive purge/fingerprint test", "absent" if not (ROOT / "tests/test_opening_gazette_delete_1356.py").exists() else "STILL_PRESENT"),
        ("dossier_source_turn payload fallback", "ming_sim/db.py:~17838", "DELETE_DONE",
         "payload source_chat_turn_id fallback labeled old-save only",
         "absent" if not _exists("ming_sim/db.py", "structured.get(\"source_chat_turn_id\")") else "STILL_PRESENT"),
        ("_drop_maintenance_column", "ming_sim/db.py", "DELETE_DONE",
         "DROP COLUMN only when old save still has maintenance_per_turn", "absent" if not _exists("ming_sim/db.py", "def _drop_maintenance_column") else "STILL_PRESENT"),
        ("test_drop_maintenance_column_* / open-old-save", "tests/test_army_maintenance_retire_173.py", "DELETE_DONE",
         "exclusive old-save DROP proofs removed; current schema contract tests kept",
         "absent" if not _exists("tests/test_army_maintenance_retire_173.py", "def test_drop_maintenance_column") else "STILL_PRESENT"),
        # keep / shared
        ("seed_opening_gazette", "ming_sim/db.py", "KEEP_SHARED",
         "new-game public knowledge events; no fixed gazette write", "live"),
        ("settle_province_tick", "ming_sim/db.py", "KEEP_TEST_OR_SHARED",
         "public single-province bridge; tests call it; batch uses _from_fiscal", "live"),
        ("is_sealed", "ming_sim/session_write_queue.py", "KEEP_TEST_READ",
         "legitimate test read of seal flag; no production guard consumer", "live"),
        ("_migrate_character_identity_seed", "ming_sim/db.py", "KEEP_CONTENT_SYNC",
         "INSERT OR IGNORE content roster into existing characters table; not format migrate", "live"),
        ("_backfill_bandit_power_split", "ming_sim/db.py", "KEEP_CONTENT_SYNC",
         "INSERT OR IGNORE bandit powers; old rewrite path already retired", "live"),
        ("_backfill_healed_participant_refs", "ming_sim/cli_backend.py", "KEEP_SHARED",
         "correction-round participant heal for current translate path", "live"),
        ("normalize_appointment_tenure default", "ming_sim/appointment_tenure.py", "KEEP_SHARED",
         "illegal/empty → 真除; serves missing-prep current path, not only old saves", "live"),
        ("decree_text dual-read with payload.text", "ming_sim/db.py / cli_backend", "KEEP_SHARED",
         "decree_text still written by create_decree_dossiers; current column", "live"),
        # escalate — law conflict or mass schema evolution
        ("population_unit / scale_content_population_to_save_unit / 万人 legacy",
         "ming_sim/db.py + ADR 0088", "ESCALATE",
         "ADR 0088 requires unlabeled saves=万人 legacy; 09-28/ADR 0108 forbid old-save compat", "live_unresolved"),
        ("ensure_column blocks annotated 旧档补列", "ming_sim/db.py init_schema", "ESCALATE",
         "columns already in CREATE make ensure old-open-only; mass strip vs mid-version current-format recovery unclear", "live_unresolved"),
        ("init_fiscal_config _FISCAL_MIGRATIONS / 老档升版", "ming_sim/db.py", "ESCALATE",
         "schema_version step migrations are old-save upgrades; also used for fiscal key evolution", "live_unresolved"),
        ("_calibrate_faction_offsets 老档反推分支", "ming_sim/db.py", "ESCALATE",
         "offset_col_added old-save calibration intertwined with new-game calibrate", "live_unresolved"),
    ]

    out = ROOT / "evidence/1847-w9-scans/n11_old_archive_members.tsv"
    lines = ["member\tloc\tdisposition\treason\tstatus"]
    for m in members:
        lines.append("\t".join(m))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for m in members:
        print("\t".join(m))
    still = [m for m in members if m[4] == "STILL_PRESENT"]
    if still:
        raise SystemExit(f"N11-R2 DELETE_DONE members still present: {still}")
    print(f"N11_OLD_ARCHIVE_CLASSIFY rows={len(members)} -> {out}")


if __name__ == "__main__":
    main()
