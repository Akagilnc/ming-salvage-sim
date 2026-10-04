"""Mutations: restore old logic → expect RED; restore fix → GREEN. Temp evidence only."""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EV = Path(__file__).resolve().parent

BINENV = {
    "MING_SIM_AGY_BIN": "/usr/bin/false",
    "MING_SIM_CODEX_BIN": "/usr/bin/false",
    "MING_SIM_CLAUDE_BIN": "/usr/bin/false",
    "MING_SIM_CURSOR_BIN": "/usr/bin/false",
    "MING_SIM_KIMI_BIN": "/usr/bin/false",
    "MING_SIM_GROK_BIN": "/usr/bin/false",
    "MING_SIM_PI_BIN": "/usr/bin/false",
}
env = {**os.environ, **BINENV}


def run_pytest(nodeids, label):
    cmd = ["python3", "-m", "pytest", *nodeids, "-q", "--tb=line"]
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    print(f"\n## {label} exit={p.returncode}")
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-900:])
    return p.returncode


def main() -> int:
    files = {
        "cutoff": ROOT / "ming_sim/audience_translate.py",
        "carry": ROOT / "ming_sim/materials.py",
        "dispatch": ROOT / "ming_sim/declaration_dispatch.py",
        "web": ROOT / "web_app.py",
        "db": ROOT / "ming_sim/db.py",
    }
    bak = {k: p.read_text(encoding="utf-8") for k, p in files.items()}
    results: dict[str, object] = {}
    try:
        return _run(files, bak, results)
    finally:
        for k, p in files.items():
            p.write_text(bak[k], encoding="utf-8")
        print("## finally: all mutated sources restored from backup")


def _run(files, bak, results) -> int:
    # ----- J6 cutoff -----
    p = files["cutoff"]
    needle = "cutoff_id = int(until_chat_turn_id or 0)"
    assert needle in bak["cutoff"]
    p.write_text(
        bak["cutoff"].replace(needle, "cutoff_id = 0  # MUTATION: disable cutoff", 1),
        encoding="utf-8",
    )
    results["j6_cutoff_red"] = run_pytest(
        ["tests/test_audience_translate_1837.py::test_translation_entry_preserves_unknown_rejection_and_source_cutoff"],
        "J6 cutoff MUTATION RED",
    )
    p.write_text(bak["cutoff"], encoding="utf-8")
    results["j6_cutoff_green"] = run_pytest(
        ["tests/test_audience_translate_1837.py::test_translation_entry_preserves_unknown_rejection_and_source_cutoff"],
        "J6 cutoff restore GREEN",
    )

    # ----- J6 draft -----
    p = files["carry"]
    old = 'if int(row["turn"]) < int(state.turn)'
    assert old in bak["carry"]
    p.write_text(
        bak["carry"].replace(
            old, 'if int(row["turn"]) <= int(state.turn)  # MUTATION: include current', 1
        ),
        encoding="utf-8",
    )
    results["j6_draft_red"] = run_pytest(
        ["tests/test_audience_background.py::test_current_unissued_draft_is_not_character_carryover"],
        "J6 draft MUTATION RED",
    )
    p.write_text(bak["carry"], encoding="utf-8")
    results["j6_draft_green"] = run_pytest(
        ["tests/test_audience_background.py::test_current_unissued_draft_is_not_character_carryover"],
        "J6 draft restore GREEN",
    )

    # ----- J6 archive -----
    p = files["web"]
    mut = bak["web"].replace(
        'def _c7_try_fulfill_archive(path: str) -> bool:\n    """C7 唯一执行接缝：opening==0 ∧ holders 空 ∧ pending → 搬库。',
        'def _c7_try_fulfill_archive(path: str) -> bool:\n    return False  # MUTATION: never archive\n    """C7 唯一执行接缝：opening==0 ∧ holders 空 ∧ pending → 搬库。',
        1,
    )
    assert mut != bak["web"]
    p.write_text(mut, encoding="utf-8")
    # wait_until 无界；归档被禁时用 timeout 证明新断言会咬住（红），禁止挂死。
    cmd_red = [
        "/opt/homebrew/bin/timeout", "8",
        "python3", "-m", "pytest",
        "tests/test_menu_lifecycle_drain_396.py::test_drain_archive_move_failure_keeps_wal_and_shm",
        "-q", "--tb=line",
    ]
    pr = subprocess.run(cmd_red, cwd=ROOT, env=env, capture_output=True, text=True)
    print(f"\n## J6 archive MUTATION RED exit={pr.returncode}")
    print(((pr.stdout or "") + (pr.stderr or ""))[-900:])
    results["j6_archive_red"] = pr.returncode
    p.write_text(bak["web"], encoding="utf-8")
    results["j6_archive_green"] = run_pytest(
        ["tests/test_menu_lifecycle_drain_396.py::test_drain_archive_move_failure_keeps_wal_and_shm"],
        "J6 archive restore GREEN",
    )

    # ----- J19 silent-id -----
    p = files["dispatch"]
    marker = (
        "# 复用押解侧既有 equality 追加（同 _attach_commission_escort），\n"
        "        # 不按人物 id 静默丢后项（#1900 J19）。\n"
        '        existing = payload.get("participant_roster")\n'
        "        merged = list(existing) if isinstance(existing, list) else []\n"
        "        for entry in roster:\n"
        "            if entry not in merged:\n"
        "                merged.append(entry)\n"
        '        payload["participant_roster"] = merged'
    )
    assert marker in bak["dispatch"], "staging equality block missing"
    silent = '''# MUTATION silent-id
        merged = list(payload.get("participant_roster") or []) if isinstance(payload.get("participant_roster"), list) else []
        seen = {str(e.get("character_id") or "") for e in merged if isinstance(e, dict) and str(e.get("character_id") or "")}
        for entry in roster:
            cid = str(entry.get("character_id") or "") if isinstance(entry, dict) else ""
            if cid and cid in seen:
                continue
            merged.append(entry)
            if cid:
                seen.add(cid)
        payload["participant_roster"] = merged'''
    p.write_text(bak["dispatch"].replace(marker, silent, 1), encoding="utf-8")

    probe_py = ROOT / "tests/_tmp_j19_mutation_probe_1900.py"
    probe_py.write_text(
        textwrap.dedent(
            """
            \"\"\"临时变异探针：真实 dispatch 入口；跑完即删，不入库。\"\"\"
            from ming_sim.applier import Provenance
            from ming_sim.declaration_dispatch import dispatch_declaration

            def test_j19_same_person_escort_and_host_both_kept(game):
                db, state, _ = game
                actor = db.conn.execute(
                    "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
                ).fetchone()["name"]
                state.metrics["内库"] = max(int(state.metrics.get("内库") or 0), 5000)
                result = dispatch_declaration(
                    db, state,
                    {"commissions": [{
                        "text": "拨银往陕西，着人押解并统筹。",
                        "participant_roster": [{
                            "character_id": actor, "tier": "主办", "role": "统筹",
                            "delegator_id": None,
                        }],
                        "grant": {
                            "grant_action": "赈灾", "amount": 1000, "account": "内库",
                            "target_kind": "region", "target_id": "shaanxi",
                            "escort": {"escortees": [{
                                "character_id": actor, "tier": "协办",
                                "role": "押解护送", "delegator_id": None,
                            }]},
                        },
                    }]},
                    source=Provenance.system_simulation,
                )
                assert result.commissions.rejected == []
                roster = result.commissions.applied[0]["payload"]["participant_roster"]
                tiers = {(e["character_id"], e["tier"], e["role"]) for e in roster}
                assert (actor, "主办", "统筹") in tiers
                assert (actor, "协办", "押解护送") in tiers
            """
        ),
        encoding="utf-8",
    )
    node = "tests/_tmp_j19_mutation_probe_1900.py::test_j19_same_person_escort_and_host_both_kept"
    try:
        results["j19_red"] = run_pytest([node], "J19 silent-id MUTATION RED")
        p.write_text(bak["dispatch"], encoding="utf-8")
        results["j19_green"] = run_pytest([node], "J19 restore GREEN")
    finally:
        probe_py.unlink(missing_ok=True)

    # ----- J18 dead helper -----
    dbt = bak["db"]
    insert_at = dbt.find("    def get_dossier_for_secret_order")
    assert insert_at > 0
    dead = (
        "    def is_secret_order_dossier(self, dossier_id: int) -> bool:\n"
        '        """MUTATION restore dead helper."""\n'
        "        row = self.conn.execute(\n"
        '            "SELECT secret_order_id FROM decree_dossiers WHERE id=?",\n'
        "            (int(dossier_id),),\n"
        "        ).fetchone()\n"
        '        return row is not None and row["secret_order_id"] is not None\n\n'
    )
    files["db"].write_text(dbt[:insert_at] + dead + dbt[insert_at:], encoding="utf-8")
    refs = subprocess.run(
        ["rg", "-n", "is_secret_order_dossier", "ming_sim", "web_app.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print("\n## J18 MUTATION dead helper refs:\n", refs.stdout)
    results["j18_dead_restored_refs"] = len(
        [ln for ln in refs.stdout.splitlines() if "def is_secret_order_dossier" not in ln]
    )
    files["db"].write_text(dbt, encoding="utf-8")
    gone = subprocess.run(
        ["rg", "-n", "def is_secret_order_dossier", "ming_sim/db.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print("## J18 restore delete:", "GONE" if gone.returncode != 0 else gone.stdout)
    results["j18_dead_gone"] = gone.returncode != 0

    # stale doc mutation
    dsp = bak["dispatch"]
    stale_mut = dsp.replace(
        "月度拨帑核账走 ``record_monthly_grant_reconciliations``（引擎中位实抵），本口不碰。",
        "对账只落本段提案，未提案目标的中位默认留到月末一次补。",
        1,
    )
    assert stale_mut != dsp
    files["dispatch"].write_text(stale_mut, encoding="utf-8")
    hit = subprocess.run(
        ["rg", "-n", "对账只落本段提案", "ming_sim/declaration_dispatch.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print("## J18 stale doc MUTATION present:", hit.stdout.strip())
    results["j18_stale_red"] = hit.returncode == 0
    files["dispatch"].write_text(dsp, encoding="utf-8")
    hit2 = subprocess.run(
        ["rg", "-n", "对账只落本段提案", "ming_sim/declaration_dispatch.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print("## J18 stale doc restore gone:", hit2.returncode != 0)
    results["j18_stale_green"] = hit2.returncode != 0

    print("\n=== SUMMARY ===")
    for k, v in results.items():
        print(k, v)
    ok = (
        results["j6_cutoff_red"] != 0
        and results["j6_cutoff_green"] == 0
        and results["j6_draft_red"] != 0
        and results["j6_draft_green"] == 0
        and results["j6_archive_red"] != 0
        and results["j6_archive_green"] == 0
        and results["j19_red"] != 0
        and results["j19_green"] == 0
        and results["j18_dead_restored_refs"] == 0
        and results["j18_dead_gone"]
        and results["j18_stale_red"]
        and results["j18_stale_green"]
    )
    print("ALL_MUTATIONS_OK" if ok else "MUTATION_MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
