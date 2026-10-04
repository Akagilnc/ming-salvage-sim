#!/usr/bin/env python3
"""In-process old-logic mutation for F15/F16. Evidence only — not a test."""

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
from ming_sim import materials as materials_mod
from ming_sim import staged_commitment as staged_mod
from ming_sim import settlement_payload as settle_mod
from ming_sim.db import GameDB
from ming_sim.materials import (
    list_materials,
    read_material,
    release_material_tree,
    secret_order_dossier_ids,
)
from ming_sim.month_chain import prepare_gazette_author_materials
from tests.conftest import append_night_chat, open_audience_night
from tests.dossier_test_helpers import TYPED_COVERT_TASK


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="1834-mut-", dir="/tmp"))
    db = None
    prepared = None
    try:
        content = GameContent.load()
        ctx_bind(content)
        issues_mod.bind_content(content)
        path = workdir / "probe.db"
        db = GameDB(str(path), content)
        db.seed_static_data()
        state = db.load_state()
        issues_mod.sync_opening_legacies(db, state)

        # --- F15 old: empty exclude set (bypass) ---
        real_affair_ids = materials_mod.affair_ids_for_dossiers
        materials_mod.affair_ids_for_dossiers = lambda _db, _ids: set()  # type: ignore

        minister = next(
            name for name, ch in content.characters.items()
            if getattr(ch, "power_id", "ming") == "ming"
            and getattr(ch, "office_type", "") != "后宫"
            and db.get_character_status(name)[0] == "active"
        )
        secret_name = "暗查国丈侵吞边饷"
        secret_origin = "奉密旨查国丈私吞边饷，暂瞒外廷"
        night_id = open_audience_night(db, state)
        _t, first_mid = append_night_chat(
            db, state, night_id, minister, "问密", "答密", 1,
        )
        pending = db.stage_pending_action(
            state.turn, kind="secret_order", action="新建", minister_name=minister,
            payload={
                "title": secret_name, "content": secret_origin, "assignee": minister,
                "origin_chat_message_id": first_mid,
                "tags": ["查办"], "covert_task": TYPED_COVERT_TASK,
            },
        )
        assert db.commit_pending_actions(
            state, minister_name=minister, action_ids={pending}, content=content,
        )
        order_id = int(db.conn.execute(
            "SELECT id FROM secret_orders ORDER BY id DESC LIMIT 1"
        ).fetchone()[0])
        dossier = db.get_dossier_for_secret_order(order_id)
        assert dossier is not None
        secret_did = int(dossier["id"])
        affair_id = int(dossier.get("affair_id") or 0)
        if affair_id <= 0:
            affair_id = db.affairs.open(
                name=secret_name, origin=secret_origin,
                year=state.year, period=state.period, turn=state.turn,
            ).id
            db.affairs.point_dossier(secret_did, affair_id)
        else:
            db.conn.execute(
                "UPDATE affairs SET name=?, origin=? WHERE id=?",
                (secret_name, secret_origin, affair_id),
            )
            db.conn.commit()

        prepared = prepare_gazette_author_materials(db, state)
        hits = []
        for rel in list_materials(prepared.root):
            body = read_material(prepared.root, rel)
            if secret_name in body or secret_origin in body:
                hits.append(rel)
        f15_old = {
            "opening_has_name": secret_name in prepared.opening,
            "file_hit_n": len(hits),
            "clean": secret_name not in prepared.opening and not hits,
        }
        materials_mod.affair_ids_for_dossiers = real_affair_ids

        # --- F16 old: re-apply crops on staged + fiscal + due content ---
        long_c = "甲" * 250
        long_o = "乙" * 280
        stages = staged_mod.normalize_commitment_stages([{
            "stage_idx": 0, "due_turn": 9,
            "criterion_text": long_c, "origin_context": long_o,
        }])
        # mutate: crop like old code
        cropped = [{
            **stages[0],
            "criterion_text": str(stages[0]["criterion_text"])[:200],
            "origin_context": str(stages[0]["origin_context"])[:240],
        }]
        f16_staged_old = {
            "criterion_len": len(str(cropped[0]["criterion_text"])),
            "origin_len": len(str(cropped[0]["origin_context"])),
            "suffix_kept": str(cropped[0]["criterion_text"]).endswith("甲")
            and len(str(cropped[0]["criterion_text"])) == 250,
        }

        long_reason = ("因边饷案核明侵吞，" + "补边饷欠发并严禁再向百姓加派。") * 20
        assert len(long_reason) > 240
        plain = db.create_decree_dossier(
            state, action_type="policy", decree_text="probe",
            target_kind="issue", target_id="mut-f16",
        )
        key = "辽饷_rate"
        old = int(db.get_fiscal_config().get(key, 100))
        # old crop path
        db.record_fiscal_config_change(
            turn=int(state.turn), key=key,
            old_value=old, new_value=max(0, old - 1),
            origin_ref=f"dossier:{plain}", reason=long_reason[:240],
        )
        hist = db.list_fiscal_effects_for_dossier(plain)
        stored = [str(row.get("reason") or "") for row in hist]
        f16_fiscal_old = {
            "stored_lens": [len(r) for r in stored],
            "full": any(r == long_reason for r in stored),
        }

        # due_commitments old crop
        content = ("丙" * 180)
        old_due = content[:120]
        f16_due_old = {
            "len": len(old_due),
            "full": old_due == content,
        }

        out = {
            "F15_old_red": f15_old,
            "F16_staged_old_red": f16_staged_old,
            "F16_fiscal_old_red": f16_fiscal_old,
            "F16_due_old_red": f16_due_old,
            "verdict": (
                (not f15_old["clean"])
                and (not f16_staged_old["suffix_kept"])
                and (not f16_fiscal_old["full"])
                and (not f16_due_old["full"])
            ),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["verdict"] else 1
    finally:
        if prepared is not None:
            try:
                release_material_tree(prepared.root)
            except Exception:
                pass
        if db is not None:
            db.close()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
