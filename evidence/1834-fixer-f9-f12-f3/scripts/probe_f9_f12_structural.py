#!/usr/bin/env python3
"""#1834 F9/F12 structural boundary probe (manual, not pytest).

Checks structure only — no free-text prose sentinels or rendered field-header
regexes:
  F9: while forming the material catalog, the Mapping fed to
      _material_facts_text must not contain decoded machine keys
      payload / stigma / execution_signal (from dossier items).
  F12: list_world_effect_history must not contain person_logs (or sibling
      audit dump tables); prepare_world_materials + prepare_gazette_author_materials
      succeed for open / close(advance) / restore.

Env (required by ticket):
  seven MING_SIM_*_BIN=/usr/bin/false
  PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=$PWD
  interpreter: ../Ming_LLM/.venv/bin/python
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

MACHINE_INPUT_KEYS = frozenset({"payload", "stigma", "execution_signal"})
AUDIT_DUMP_TABLES = (
    "person_logs", "army_logs", "building_logs", "power_logs", "region_logs",
    "population_transfer_ledger", "investigation_spoiled_facts",
    "office_change_records", "authority_records", "decree_cost_events",
    "dossier_loophole_exposures", "dossier_supervision_presence",
)


def _assert_history_clean(db, origin: str) -> None:
    history = db.list_world_effect_history(origin)
    bad = sorted(t for t in AUDIT_DUMP_TABLES if t in history)
    if bad:
        raise AssertionError(f"list_world_effect_history({origin}) dumps {bad}")


def _patch_old_f9(materials_mod):
    materials_mod._DOSSIER_MATERIAL_SKIP = frozenset({"office_archive_keys"})


def _patch_old_f12(db_mod):
    GameDB = db_mod.GameDB
    orig = GameDB.list_world_effect_history

    def patched(self, origin: str):
        history = orig(self, origin)
        history["person_logs"] = [
            dict(row) for row in self.conn.execute(
                "SELECT * FROM person_logs WHERE origin_ref=? ORDER BY id",
                (origin,),
            ).fetchall()
        ]
        for row in history["person_logs"]:
            row["normalized"] = json.loads(row.get("normalized") or "{}")
        return history

    GameDB.list_world_effect_history = patched
    return orig


def _assert_no_machine_keys(value, path: str = "$") -> None:
    """Walk feed structure; fail if decoded machine keys are present."""
    if isinstance(value, Mapping):
        leaked = sorted(MACHINE_INPUT_KEYS & set(value.keys()))
        if leaked:
            raise AssertionError(
                f"machine input keys {leaked} entered material feed at {path}"
            )
        for key, item in value.items():
            _assert_no_machine_keys(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _assert_no_machine_keys(item, f"{path}[{i}]")


def _install_input_structure_guard(materials_mod):
    """Guard existing renderer inputs — no production export, no prose headers."""
    orig = materials_mod._material_facts_text

    def guarded(value, indent: str = ""):
        _assert_no_machine_keys(value)
        return orig(value, indent)

    materials_mod._material_facts_text = guarded
    return orig


def _active_minister(db) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("no active character")
    return str(row["name"])


def run(mode: str) -> str:
    from ming_sim.content import GameContent
    from ming_sim.context import bind_content as ctx_bind
    import ming_sim.issues as issues_mod
    from ming_sim.db import GameDB
    import ming_sim.db as db_mod
    from ming_sim import materials as materials_mod
    from ming_sim.month_chain import prepare_gazette_author_materials
    from ming_sim.materials import release_material_tree

    content = GameContent.load()
    ctx_bind(content)
    issues_mod.bind_content(content)

    tmp = Path(tempfile.mkdtemp(prefix="1834-struct-probe-"))
    db_path = tmp / "probe.db"
    db = None
    orig_facts = None
    try:
        db = GameDB(str(db_path), content)
        db.seed_static_data()
        state = db.load_state()
        issues_mod.sync_opening_legacies(db, state)
        minister = _active_minister(db)

        if mode == "old":
            _patch_old_f9(materials_mod)
            _patch_old_f12(db_mod)
        elif mode == "old-f12":
            _patch_old_f12(db_mod)

        orig_facts = _install_input_structure_guard(materials_mod)

        # Real dossier with decoded machine loads (loyalty bare value inside payload).
        affair = db.affairs.open(
            name="结构边界探针事务", origin="探针",
            year=state.year, period=state.period, turn=state.turn,
        )
        payload = {
            "ongoing_effects": {
                "人物变更": [{"name": minister, "loyalty": 2}],
            },
            "reason": "密令私密理由-结构探针",
            "assignee_id": minister,
            "affair_declaration": {"attach": "existing", "affair_id": affair.id},
        }
        did = db.create_decree_dossier(
            state,
            action_type="assignment",
            decree_text="结构边界探针案",
            target_kind="issue",
            target_id="struct-probe",
            executor_kind="character",
            executor_id=minister,
            payload=payload,
            extension={"execution_signal": {"kind": "probe", "ok": True}},
        )
        # Seed stigma_json so decoded stigma key would dump if not skipped.
        db.conn.execute(
            "UPDATE decree_dossiers SET stigma_json=? WHERE id=?",
            (json.dumps([{"decision": "probe"}], ensure_ascii=False), did),
        )
        # person_logs row on dossier origin (F12 dump source).
        origin = f"dossier:{did}"
        db.conn.execute(
            """
            INSERT INTO person_logs
            (turn, year, period, person_name, action, payload_summary, derived_from,
             normalized, source, origin_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.turn, state.year, state.period, minister, "评定",
                "summary", "",
                json.dumps({"reason": "私密评定理由", "loyalty": 2}, ensure_ascii=False),
                "secret_order", origin,
            ),
        )
        db.conn.commit()
        row = db.get_decree_dossier(did)
        affair_id = int(row.get("affair_id") or affair.id)

        def check(label: str, prepared) -> None:
            root = Path(prepared.root)
            nfiles = sum(1 for p in root.rglob("*") if p.is_file())
            _assert_history_clean(db, origin)
            _assert_history_clean(db, db.affairs.origin_ref(affair_id))
            print(f"PASS {label} dossier={did} affair={affair_id} files={nfiles}")

        # OPEN
        world = materials_mod.prepare_world_materials(db, state)
        try:
            check("OPEN_WORLD", world)
        finally:
            release_material_tree(world.root)
        public = prepare_gazette_author_materials(db, state)
        try:
            check("OPEN_PUBLIC", public)
        finally:
            release_material_tree(public.root)

        # CLOSE (advance calendar; dossiers remain readable)
        state.turn += 1
        state.period = min(12, int(state.period) + 1)
        db.save_state(state)
        world = materials_mod.prepare_world_materials(db, state)
        try:
            check("CLOSED_WORLD", world)
        finally:
            release_material_tree(world.root)
        public = prepare_gazette_author_materials(db, state)
        try:
            check("CLOSED_PUBLIC", public)
        finally:
            release_material_tree(public.root)

        # RESTORE
        db.close()
        db = GameDB(str(db_path), content)
        state = db.load_state()
        world = materials_mod.prepare_world_materials(db, state)
        try:
            check("RESTORE_WORLD", world)
        finally:
            release_material_tree(world.root)
        public = prepare_gazette_author_materials(db, state)
        try:
            check("RESTORE_PUBLIC", public)
        finally:
            release_material_tree(public.root)

        return "ALL_GREEN"
    finally:
        if orig_facts is not None:
            materials_mod._material_facts_text = orig_facts
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", action="store_true")
    ap.add_argument("--old-f12", action="store_true")
    args = ap.parse_args()
    mode = "old" if args.old else ("old-f12" if args.old_f12 else "current")
    # Host BIN reminder (do not call models).
    for k in (
        "MING_SIM_AGY_BIN", "MING_SIM_CODEX_BIN", "MING_SIM_CLAUDE_BIN",
        "MING_SIM_CURSOR_BIN", "MING_SIM_KIMI_BIN", "MING_SIM_GROK_BIN", "MING_SIM_PI_BIN",
    ):
        os.environ.setdefault(k, "/usr/bin/false")
    try:
        print(run(mode))
        return 0
    except Exception as exc:
        tag = {
            "old": "OLD_LOGIC_RED",
            "old-f12": "F12_OLD_LOGIC_RED",
            "current": "CURRENT_RED",
        }[mode]
        print(f"{tag} {type(exc).__name__}: {exc}")
        return 2 if mode != "current" else 1


if __name__ == "__main__":
    sys.exit(main())
