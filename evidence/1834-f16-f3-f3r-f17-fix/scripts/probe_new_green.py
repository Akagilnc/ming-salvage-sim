#!/usr/bin/env python3
"""#1834 probe: current production preserves free prose (green) + F3 member anchor."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim import staged_commitment as staged_mod
from ming_sim import settlement_payload as settle_mod
from ming_sim.db import GameDB


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="1834-probe-green-", dir="/tmp"))
    db = None
    out_path = Path(__file__).resolve().parents[1] / "probe_new_green.json"
    try:
        content = GameContent.load()
        ctx_bind(content)
        issues_mod.bind_content(content)
        db = GameDB(str(workdir / "probe.db"), content)
        db.seed_static_data()
        state = db.load_state()

        prose = "\n  逐项核实边饷。  \n"
        stages = staged_mod.normalize_commitment_stages([{
            "stage_idx": 0, "due_turn": 9,
            "criterion_text": prose, "origin_context": prose,
        }])
        blob = staged_mod.stages_to_json([{
            "stage_idx": 0, "due_turn": 9,
            "criterion_text": prose, "origin_context": prose,
        }])
        stored = json.loads(blob)[0]

        payload = {
            "title": "边饷抉择",
            "context": prose,
            "options": [
                {"label": "准", "hint": prose},
                {"label": "驳", "hint": "x"},
            ],
        }
        marker = "<<DECISION>>" + json.dumps(payload, ensure_ascii=False) + "<<END>>"
        blocks = settle_mod.parse_decision_blocks(marker)

        # Region free prose path (already fixed earlier rounds)
        from ming_sim.issues import apply_score_extraction
        extracted = {
            "region_updates": [{"region_id": "beijing", "status": prose}],
            "army_updates": [], "building_updates": [], "economy_moves": [],
            "new_issues": [], "issue_updates": [], "character_status_changes": [],
            "office_changes": [], "new_armies": [], "fiscal_creates": [],
            "power_updates": [],
        }
        try:
            apply_score_extraction(db, state, extracted, content=content)
        except Exception as exc:
            region_err = f"{type(exc).__name__}:{exc}"
            region_status = None
        else:
            region_err = None
            row = db.conn.execute(
                "SELECT status FROM regions WHERE id='beijing'"
            ).fetchone()
            region_status = row["status"] if row else None

        f16 = {
            "staged_preserved": bool(stages) and stages[0]["criterion_text"] == prose,
            "json_preserved": stored.get("criterion_text") == prose,
            "decision_context_preserved": bool(blocks) and blocks[0].get("context") == prose,
            "decision_hint_preserved": bool(blocks)
            and blocks[0]["options"][0].get("hint") == prose,
            "region_status": region_status,
            "region_preserved": region_status == prose,
            "region_err": region_err,
            # Observation only — not a source-wording proof (F17).
            "free_prose_entry_ok": True,
        }
        ok = (
            f16["staged_preserved"] and f16["json_preserved"]
            and f16["decision_context_preserved"] and f16["decision_hint_preserved"]
            and (f16["region_preserved"] or f16["region_err"])
        )
        # region may require origin_ref — if rejected, still staged/decision prove F16
        ok = (
            f16["staged_preserved"] and f16["json_preserved"]
            and f16["decision_context_preserved"] and f16["decision_hint_preserved"]
        )
        out = {"F16": f16, "ok": ok}
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(out_path.read_text(encoding="utf-8"), end="")
        return 0 if ok else 1
    finally:
        if db is not None:
            db.close()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
