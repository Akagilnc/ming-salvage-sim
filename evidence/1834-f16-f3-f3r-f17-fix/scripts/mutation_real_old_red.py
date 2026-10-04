#!/usr/bin/env python3
"""#1834 F17: real-entry mutation — replace production symbols with OLD strip logic.

Inputs are full free prose. No pre-crop of args, no post-crop of results outside entry.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim import materials as materials_mod
from ming_sim import staged_commitment as staged_mod
from ming_sim import settlement_payload as settle_mod
from ming_sim.action_clusters import season_option_fields, validate_season_option
from ming_sim.db import GameDB
from ming_sim.materials import list_materials, read_material, release_material_tree
from ming_sim.month_chain import prepare_gazette_author_materials
from tests.conftest import append_night_chat, open_audience_night
from tests.dossier_test_helpers import TYPED_COVERT_TASK

_DECISION_RE = re.compile(r"<<DECISION>>\s*(\{.*?\})\s*<<END>>", re.DOTALL)
MAX_DECISIONS_PER_TURN = 5


def old_normalize_commitment_stages(raw: object) -> List[Dict[str, object]]:
    if raw in (None, "", [], ()):
        return []
    data = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text in ("[]", "{}"):
            return []
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, (list, tuple)):
        return []
    out: List[Dict[str, object]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        try:
            due_turn = int(item.get("due_turn") or 0)
        except (TypeError, ValueError):
            continue
        if due_turn <= 0:
            continue
        try:
            stage_idx = int(item.get("stage_idx", idx))
        except (TypeError, ValueError):
            stage_idx = idx
        criterion = str(
            item.get("criterion_text") or item.get("criterion") or ""
        ).strip()
        origin_context = str(
            item.get("origin_context") or item.get("origin") or criterion or ""
        ).strip()
        if not criterion and origin_context:
            criterion = origin_context
        if not criterion:
            continue
        out.append({
            "stage_idx": stage_idx,
            "due_turn": due_turn,
            "criterion_text": criterion,
            "origin_context": (origin_context or criterion),
        })
    out.sort(key=lambda s: (int(s["stage_idx"]), int(s["due_turn"])))
    return out


def old_parse_decision_blocks(text: str) -> List[Dict[str, object]]:
    """Old production shape: strip title/context/label/hint before durable store."""
    decisions: List[Dict[str, object]] = []
    for m in _DECISION_RE.finditer(text or ""):
        if len(decisions) >= MAX_DECISIONS_PER_TURN:
            break
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        title = str(obj.get("title") or "").strip()
        raw_opts = obj.get("options")
        if not title or not isinstance(raw_opts, list):
            continue
        options: List[Dict[str, object]] = []
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            label = str(o.get("label") or "").strip()
            if not label:
                continue
            try:
                action_type = validate_season_option(o)
            except ValueError:
                options = []
                break
            option: Dict[str, object] = {
                "label": label,
                "hint": str(o.get("hint") or "").strip(),
            }
            for key in season_option_fields(action_type):
                if key in o:
                    option[key] = action_type if key == "action_type" else o[key]
            options.append(option)
        try:
            settle_mod.bind_decision_options(options)
        except ValueError:
            continue
        if len(options) < 2:
            continue
        decision = {
            "title": title,
            "context": str(obj.get("context") or "").strip(),
            "options": options[:3],
        }
        decisions.append(decision)
    return decisions


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="1834-mut-real-", dir="/tmp"))
    db = None
    prepared = None
    real_affair_ids = materials_mod.affair_ids_for_dossiers
    real_norm = staged_mod.normalize_commitment_stages
    real_parse = settle_mod.parse_decision_blocks
    out_path = Path(__file__).resolve().parents[1] / "mutation_old_red.json"
    try:
        content = GameContent.load()
        ctx_bind(content)
        issues_mod.bind_content(content)
        db = GameDB(str(workdir / "probe.db"), content)
        db.seed_static_data()
        state = db.load_state()
        issues_mod.sync_opening_legacies(db, state)

        # F15 old bypass
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
        prepared = prepare_gazette_author_materials(db, state)
        hits = [
            rel for rel in list_materials(prepared.root)
            if secret_name in read_material(prepared.root, rel)
            or secret_origin in read_material(prepared.root, rel)
        ]
        f15_old = {
            "opening_has_name": secret_name in prepared.opening,
            "file_hit_n": len(hits),
            "clean": secret_name not in prepared.opening and not hits,
        }
        materials_mod.affair_ids_for_dossiers = real_affair_ids

        prose = "\n  逐项核实边饷。  \n"

        # F16 staged: replace production normalize with old strip implementation
        staged_mod.normalize_commitment_stages = old_normalize_commitment_stages  # type: ignore
        stages = staged_mod.normalize_commitment_stages([{
            "stage_idx": 0, "due_turn": 9,
            "criterion_text": prose, "origin_context": prose,
        }])
        blob = staged_mod.stages_to_json([{
            "stage_idx": 0, "due_turn": 9,
            "criterion_text": prose, "origin_context": prose,
        }])
        stored = json.loads(blob)[0]
        staged_mod.normalize_commitment_stages = real_norm  # type: ignore
        f16_staged = {
            "input": prose,
            "normalized": stages[0]["criterion_text"] if stages else None,
            "via_stages_to_json": stored.get("criterion_text"),
            "preserved": bool(stages) and stages[0]["criterion_text"] == prose
            and stored.get("criterion_text") == prose,
        }

        # F16 decisions: replace production parser with old strip implementation
        settle_mod.parse_decision_blocks = old_parse_decision_blocks  # type: ignore
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
        settle_mod.parse_decision_blocks = real_parse  # type: ignore
        f16_decision = {
            "context": blocks[0]["context"] if blocks else None,
            "hint": (blocks[0]["options"][0]["hint"] if blocks else None),
            "preserved": bool(blocks)
            and blocks[0]["context"] == prose
            and blocks[0]["options"][0]["hint"] == prose,
        }

        out = {
            "method": "replace_production_symbol_with_old_implementation",
            "F15_old_red": f15_old,
            "F16_staged_old_red": f16_staged,
            "F16_decision_old_red": f16_decision,
            "verdict": (
                (not f15_old["clean"])
                and (not f16_staged["preserved"])
                and (not f16_decision["preserved"])
            ),
        }
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(out_path.read_text(encoding="utf-8"), end="")
        return 0 if out["verdict"] else 1
    finally:
        materials_mod.affair_ids_for_dossiers = real_affair_ids
        staged_mod.normalize_commitment_stages = real_norm  # type: ignore
        settle_mod.parse_decision_blocks = real_parse  # type: ignore
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
