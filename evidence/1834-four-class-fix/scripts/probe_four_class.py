"""Temporary real-entry probe for #1834 F15/F16/F13. Not a permanent test."""

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
from ming_sim.db import GameDB
from ming_sim.materials import (
    PreparedMaterials,
    affair_ids_for_dossiers,
    list_materials,
    read_material,
    release_material_tree,
    secret_order_dossier_ids,
    write_identity_materials,
)
from ming_sim.month_chain import prepare_gazette_author_materials
from ming_sim.staged_commitment import normalize_commitment_stages
from tests.conftest import append_night_chat, open_audience_night
from tests.dossier_test_helpers import TYPED_COVERT_TASK


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="1834-four-class-", dir="/tmp"))
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

        minister = next(
            name for name, ch in content.characters.items()
            if getattr(ch, "power_id", "ming") == "ming"
            and getattr(ch, "office_type", "") != "后宫"
            and db.get_character_status(name)[0] == "active"
        )
        secret_name = "暗查国丈侵吞边饷"
        secret_origin = "奉密旨查国丈私吞边饷，暂瞒外廷"
        night_id = open_audience_night(db, state)
        _secret_turn, first_mid = append_night_chat(
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

        secret_ids = secret_order_dossier_ids(db)
        derived_affairs = affair_ids_for_dossiers(db, secret_ids)
        prepared = prepare_gazette_author_materials(db, state)
        hits = []
        for rel in list_materials(prepared.root):
            body = read_material(prepared.root, rel)
            if secret_name in body or secret_origin in body:
                hits.append({
                    "rel": rel,
                    "name": secret_name in body,
                    "origin": secret_origin in body,
                })
        f15 = {
            "secret_dossier_in_exclude_set": secret_did in secret_ids,
            "affair_derived_from_dossiers": affair_id in derived_affairs,
            "parallel_secret_order_affair_ids_fn": hasattr(
                sys.modules.get("ming_sim.materials")
                or __import__("ming_sim.materials", fromlist=["*"]),
                "secret_order_affair_ids",
            ),
            "opening_has_name": secret_name in prepared.opening,
            "opening_has_origin": secret_origin in prepared.opening,
            "file_hits": hits,
            "clean": (
                secret_name not in prepared.opening
                and secret_origin not in prepared.opening
                and not hits
                and affair_id in derived_affairs
            ),
        }

        long_decree = (
            "着户部核边饷亏空，查清国丈侵吞数目及仓场实存，"
            "务须据实回奏，并将侵蚀年月、经手官吏、挪移路径一并开列，"
            "不许另向百姓加派"
        )
        long_reason = (
            "因边饷案核明国丈侵吞，着将某省火耗率下调，"
            "省出之数尽数补边饷欠发，并将核销清册按季奏报，"
            "另须会同兵部核对各边镇月支实数与截留细目，"
            "凡虚冒空额、重复请领者立时驳回并追缴，"
            "其已支未销之项限两月内清结，逾期按挪移论处，"
            "并令巡按御史随同按册抽核，不得仅凭司府申报了事，"
            "各镇册籍须与太仓实发流水对读，有名无兵者尽数删除，"
            "其应补之饷按现额月支改注，不得仍照旧册虚额请领，"
            "违者户部堂上官议处；此事只在账册落地，严禁再向百姓加派。"
        ) * 2
        assert len(long_decree) > 48, len(long_decree)
        assert len(long_reason) > 240, len(long_reason)
        plain = db.create_decree_dossier(
            state, action_type="policy", decree_text=long_decree,
            target_kind="issue", target_id="f16-fork-probe",
        )
        db.conn.execute(
            "UPDATE decree_dossiers SET status='executing', decree_text=? WHERE id=?",
            (long_decree, plain),
        )
        db.conn.commit()
        # Direct case_summary projection path (same function judge cited).
        # Temporarily mark fork by patching read_dossier_fork_state result via SQL
        # fields the fork reader uses when available; always exercise fiscal path.
        key = "辽饷_rate"
        old = int(db.get_fiscal_config().get(key, 100))
        db.record_fiscal_config_change(
            turn=int(state.turn), key=key,
            old_value=old, new_value=max(0, old - 1),
            origin_ref=f"dossier:{plain}", reason=long_reason,
        )
        hist = db.list_fiscal_effects_for_dossier(plain)
        stored_reasons = [str(row.get("reason") or "") for row in hist]
        # case_summary via build helper when fork exists — also call the crop site
        # by constructing through denunciation facts after forcing fork=True via
        # a minimal monkey of read_dossier_fork_state for this dossier only.
        original_fork = db.read_dossier_fork_state

        def _fork(did, *a, **k):
            state_fork = original_fork(did, *a, **k)
            if int(did) == plain:
                patched = dict(state_fork)
                patched["fork"] = True
                return patched
            return state_fork

        db.read_dossier_fork_state = _fork  # type: ignore[method-assign]
        facts = db.build_faction_denunciation_facts()
        summaries = [
            str(item.get("case_summary") or "")
            for item in (facts.get("forked_dossiers") or [])
            if int(item.get("dossier_id") or 0) == plain
        ]
        db.read_dossier_fork_state = original_fork  # type: ignore[method-assign]

        long_c = "甲" * 250
        long_o = "乙" * 280
        stages = normalize_commitment_stages([{
            "stage_idx": 0, "due_turn": 9,
            "criterion_text": long_c, "origin_context": long_o,
        }])

        # Building status → materials 营建段（本轮扩枚举漏网成员）
        long_status = (
            "新立营建须按原估料核验木石砖灰并会同工部司官亲履工所，"
            "凡偷减材料、虚报进度、挪移工食者立时纠参，"
            "且不得以年例不足为由另向沿途州县摊派丁夫与折色，"
            "其已支未销之工料银两限两月内按册清结，逾期按挪移论处，"
            "并令巡按御史随同按册抽核，不得仅凭司府申报了事，"
            "各厂作匠籍须与工部实发流水对读，有名无役者尽数删除，"
            "违者工部堂上官议处；此事只在营造落地，严禁再向百姓加派。"
        )
        assert len(long_status) > 160, len(long_status)
        bid = db.add_building(
            state,
            region_id="beizhili",
            name="边饷稽核公廨",
            category="财政",
            status=long_status,
            origin=f"dossier:{plain}",
            origin_ref=f"dossier:{plain}",
            commit=True,
        )
        from ming_sim import action_clusters as ac
        building_row = db.conn.execute(
            "SELECT status FROM buildings WHERE id=?", (bid,)
        ).fetchone()
        stored_status = str(building_row["status"] if building_row else "")
        release_material_tree(prepared.root)
        prepared = prepare_gazette_author_materials(db, state)
        board_hit = any(
            long_status in read_material(prepared.root, rel)
            for rel in list_materials(prepared.root)
        )

        f16 = {
            "decree_len": len(long_decree),
            "case_summaries": summaries,
            "case_full": bool(summaries) and all(s == long_decree for s in summaries),
            "case_suffix": bool(summaries) and all(
                s.endswith("不许另向百姓加派") for s in summaries
            ),
            "reason_len": len(long_reason),
            "stored_reason_lens": [len(r) for r in stored_reasons],
            "fiscal_full": any(r == long_reason for r in stored_reasons),
            "fiscal_suffix": any(r.endswith("严禁再向百姓加派。") for r in stored_reasons),
            "staged_criterion_full": (
                stages and str(stages[0]["criterion_text"]) == long_c
            ),
            "staged_origin_full": (
                stages and str(stages[0]["origin_context"]) == long_o
            ),
            "building_status_len": len(stored_status),
            "building_status_full": stored_status == long_status,
            "building_in_materials": board_hit,
            "max_len_field_absent": "max_len" not in Path(
                ac.__file__
            ).read_text(encoding="utf-8"),
            "free_prose_no_strip": (
                "_FREE_PROSE_FIELD_NAMES" in Path(ac.__file__).read_text(encoding="utf-8")
                and 'if name in _FREE_PROSE_FIELD_NAMES' in Path(
                    ac.__file__
                ).read_text(encoding="utf-8")
            ),
        }

        pm = PreparedMaterials(root=prepared.root, opening="probe")
        before = hasattr(pm, "index_lines")
        written = write_identity_materials(pm, db, state, [minister])
        after = hasattr(pm, "index_lines")
        f13 = {
            "declared_fields": list(PreparedMaterials.__dataclass_fields__),
            "before": before,
            "after": after,
            "written_n": len(written),
            "clean": (not before) and (not after),
        }

        out = {"F15": f15, "F16": f16, "F13": f13}
        dest = Path(__file__).resolve().parents[1] / "probe_new_green.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(dest.read_text(encoding="utf-8"), end="")
        ok = (
            f15["clean"] and f13["clean"]
            and f16["fiscal_full"] and f16["case_full"]
            and f16["staged_criterion_full"] and f16["staged_origin_full"]
            and f16["building_status_full"] and f16["building_in_materials"]
            and f16["max_len_field_absent"] and f16["free_prose_no_strip"]
            and not f15["parallel_secret_order_affair_ids_fn"]
        )
        return 0 if ok else 1
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
