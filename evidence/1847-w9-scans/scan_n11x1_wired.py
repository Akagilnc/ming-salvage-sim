#!/usr/bin/env python3
"""#1847 w9 N11-X1 — scan w8 wired/shim production additions and current state.

Replay:
  MING_SIM_*_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w9-scans/scan_n11x1_wired.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    swq = (ROOT / "ming_sim/session_write_queue.py").read_text(encoding="utf-8")
    db = (ROOT / "ming_sim/db.py").read_text(encoding="utf-8")
    brew = (ROOT / "ming_sim/relation_brew.py").read_text(encoding="utf-8")
    faction_test = (ROOT / "tests/test_faction_brew_637.py").read_text(encoding="utf-8")

    rows = []
    # 1) seal impossible guard
    has_guard = 'raise RuntimeError("write queue seal failed")' in swq
    has_is_sealed = "def is_sealed" in swq
    rows.append((
        "session_write_queue.seal_guard",
        "DELETE_GUARD" if not has_guard else "STILL_PRESENT",
        f"is_sealed_def={has_is_sealed}; prod_guard={has_guard}",
    ))
    # 2) settle dual branch
    dual = re.search(
        r"def settle_ming_province_substrate_ticks[\s\S]*?return outcomes",
        db,
    )
    body = dual.group(0) if dual else ""
    calls_public = "self.settle_province_tick(" in body
    calls_internal = "self._settle_province_tick_from_fiscal(" in body
    rows.append((
        "db.settle_ming_province_substrate_ticks_branch",
        "REVERTED" if (calls_internal and not calls_public) else "STILL_BRANCHED",
        f"calls_settle_province_tick={calls_public}; calls__from_fiscal={calls_internal}",
    ))
    # 3) relation_brew production shim
    prod_shim = "def run_month_end_relation_brew" in brew
    test_shim = "def run_month_end_relation_brew" in faction_test
    rows.append((
        "relation_brew.run_month_end_relation_brew",
        "PROD_DELETED_TEST_LOCAL_OK" if (not prod_shim and test_shim) else "CHECK",
        f"prod_def={prod_shim}; test_local_def={test_shim}",
    ))

    out = ROOT / "evidence/1847-w9-scans/n11x1_wired.tsv"
    out.write_text(
        "member\tdisposition\tnotes\n"
        + "\n".join(f"{a}\t{b}\t{c}" for a, b, c in rows)
        + "\n",
        encoding="utf-8",
    )
    for r in rows:
        print("\t".join(r))
    bad = [r for r in rows if r[1] in {"STILL_PRESENT", "STILL_BRANCHED", "CHECK"}]
    if bad:
        raise SystemExit(f"N11-X1 scan FAIL: {bad}")
    print("N11X1_WIRED_SCAN PASS")


if __name__ == "__main__":
    main()
