#!/usr/bin/env python3
"""#1835 S2 R1/R2 mutation probes — real dispatch_month_segment entrance.

装回 06b167f9b 口径旧逻辑 → 新回归案红；当前修复 → 绿。
不改仓库文件，仅进程内 monkeypatch。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

for k in (
    "MING_SIM_AGY_BIN",
    "MING_SIM_CODEX_BIN",
    "MING_SIM_CLAUDE_BIN",
    "MING_SIM_CURSOR_BIN",
    "MING_SIM_KIMI_BIN",
    "MING_SIM_GROK_BIN",
    "MING_SIM_PI_BIN",
):
    os.environ[k] = "/usr/bin/false"

TMP = Path(tempfile.mkdtemp(prefix="1835-s2-mut-"))
os.environ["MING_SIM_USER_DATA_DIR"] = str(TMP / "user")
(TMP / "user").mkdir()
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
OUT = Path(__file__).resolve().parent / "mutation-probes.txt"
lines: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def boot_game():
    from ming_sim.content import GameContent
    from ming_sim.db import GameDB
    from ming_sim import issues as issues_mod

    content = GameContent.load()
    issues_mod.bind_content(content)
    work = TMP / f"game-{len(lines)}"
    work.mkdir()
    path = str(work / "opening.db")
    seed = GameDB(path, content)
    try:
        seed.seed_static_data()
        st = seed.load_state()
        issues_mod.sync_opening_legacies(seed, st)
    finally:
        seed.close()
    db = GameDB(path, content)
    state = db.load_state()
    state.year = 1629
    state.period = 11
    return db, state, content


def _configure_pay(db) -> None:
    for key in ("__army_pay_source_cutover", "__fiscal_engine"):
        db.conn.execute(
            "INSERT INTO fiscal_config(key,value,kind,note) VALUES (?,?,'meta','mut') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, 1),
        )
    db.conn.commit()


def _r1_scenario(db, state, content, *, label: str) -> str:
    from ming_sim import issues as issue_engine
    from ming_sim.month_translate import dispatch_month_segment

    issue_engine.bind_content(content)
    army = "guanning"
    target = db.conn.execute(
        "SELECT id FROM armies WHERE id != ? ORDER BY id LIMIT 1", (army,)
    ).fetchone()[0]
    db.conn.execute(
        "UPDATE armies SET cannon_equipment=5, is_mutinied=0 WHERE id=?", (army,)
    )
    db.conn.execute(
        "UPDATE armies SET cannon_equipment=0, is_mutinied=0 WHERE id=?", (target,)
    )
    db.conn.execute("DELETE FROM event_triggers WHERE event_id='jisi_lubian'")
    db.conn.commit()
    dispatch_month_segment(
        db,
        state,
        segment=f"s2-r1-{label}",
        translate_fn=lambda _r, _c: {
            "effects": [
                {
                    "event_id": "jisi_lubian",
                    "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
                    "事件结局": {"jisi_lubian": "入塞被遏"},
                    "army_delta": {
                        army: {
                            "origin_ref": "盘面自发",
                            "随军大炮": -3,
                            "cannon_transfer_to": target,
                            "reason": "缴获",
                        }
                    },
                }
            ]
        },
    )
    cannons = {
        row["id"]: row["cannon_equipment"]
        for row in db.conn.execute(
            "SELECT id, cannon_equipment FROM armies WHERE id IN (?, ?)",
            (army, target),
        )
    }
    triggered = db.has_event_triggered("jisi_lubian")
    return (
        f"triggered={triggered} src={cannons[army]} dst={cannons[target]} "
        f"(expect triggered=True src=2 dst=3)"
    )


def _r2_scenario(db, state, content, *, label: str) -> str:
    from ming_sim import issues as issue_engine
    from ming_sim.month_translate import dispatch_month_segment

    issue_engine.bind_content(content)
    army = "guanning"
    _configure_pay(db)
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_mutinied=1, mutiny_count=1,
           redemption_count=0, loyalty=80, arrears=5, manpower=10000,
           province_pay_arrears=0, central_pay_arrears=5 WHERE id=?""",
        (army,),
    )
    db.conn.execute(
        "UPDATE regions SET military_pressure=? WHERE id='beizhili'", (20,)
    )
    db.conn.execute("DELETE FROM event_triggers WHERE event_id='jisi_lubian'")
    db.conn.commit()
    dispatch_month_segment(
        db,
        state,
        segment=f"s2-r2-{label}",
        translate_fn=lambda _r, _c: {
            "effects": [
                {
                    "event_id": "jisi_lubian",
                    "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
                    "事件结局": {"jisi_lubian": "入塞被遏"},
                    "region_delta": {
                        "beizhili": {
                            "origin_ref": "盘面自发",
                            "military_pressure": 35,
                        }
                    },
                    "army_delta": {
                        army: {
                            "origin_ref": "盘面自发",
                            "loyalty": 5,
                            "manpower": -100,
                        }
                    },
                }
            ]
        },
    )
    loyalty = db.conn.execute(
        "SELECT loyalty FROM armies WHERE id=?", (army,)
    ).fetchone()["loyalty"]
    manpower = db.conn.execute(
        "SELECT manpower FROM armies WHERE id=?", (army,)
    ).fetchone()["manpower"]
    pressure = db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id='beizhili'"
    ).fetchone()["military_pressure"]
    triggered = db.has_event_triggered("jisi_lubian")
    return (
        f"triggered={triggered} loyalty={loyalty} manpower={manpower} "
        f"pressure={pressure} "
        f"(expect triggered=False loyalty=80 manpower=10000 pressure=20)"
    )


def main() -> int:
    import ming_sim.entities.army.delta_section as army_section
    import ming_sim.settlement.preflight as pf

    log("=== S2 R1/R2 MUTATION (dispatch_month_segment; in-process reinject) ===")
    log(f"tmp={TMP}")
    log(
        "COMMAND: env MING_SIM_*_BIN=/usr/bin/false "
        ".venv/bin/python -B evidence/issue-1835/w5-s2/run_mutation_probes.py"
    )

    db, state, content = boot_game()
    try:
        log(f"R1_CURRENT_TRANSFER_GREEN: {_r1_scenario(db, state, content, label='cur')}")
    finally:
        db.close()

    db, state, content = boot_game()
    try:
        log(f"R2_CURRENT_PER_FIELD_GREEN: {_r2_scenario(db, state, content, label='cur')}")
    finally:
        db.close()

    # R1 old: 预检装回 apply_army_deltas（不认 cannon_transfer_to）
    real_transfer = army_section.apply_army_delta_with_cannon_transfer

    def apply_army_deltas_as_transfer(
        db, state, pseudo_event, army_id, raw_changes, source=None,
    ):
        from ming_sim.applier import Provenance

        return db.apply_army_deltas(
            state,
            pseudo_event,
            None,
            "档房",
            {army_id: raw_changes},
            commit=False,
            source=source or Provenance.system_simulation,
        )

    army_section.apply_army_delta_with_cannon_transfer = apply_army_deltas_as_transfer
    try:
        db, state, content = boot_game()
        try:
            log(
                f"R1_OLD_APPLY_ARMY_DELTAS_RED: "
                f"{_r1_scenario(db, state, content, label='old-r1')}"
            )
        finally:
            db.close()
    finally:
        army_section.apply_army_delta_with_cannon_transfer = real_transfer

    # R2 old: 整类 any(material) 才拒
    orig_preflight = pf._strategic_event_result_preflight_error

    def preflight_with_class_level_any_material(
        db, state, event_id, event_title, outcome_label,
        region_deltas, army_deltas, power_updates, person_changes, new_armies,
        content, llm_config, preflight_event,
        ordered_region_items=None, ordered_army_items=None, ordered_power_items=None,
    ):
        import copy

        from ming_sim.applier import Provenance, RejectedItem
        from ming_sim.entities.army.delta_section import (
            apply_army_delta_with_cannon_transfer,
        )

        preview_state = copy.deepcopy(state)
        region_items = list(
            ordered_region_items
            if ordered_region_items is not None
            else region_deltas.items()
        )
        army_items = list(
            ordered_army_items if ordered_army_items is not None else army_deltas.items()
        )
        region_results = []
        army_results = []
        db.conn.execute("SAVEPOINT strategic_entity_result_preflight")
        try:
            for region_id, raw_changes in region_items:
                if not isinstance(raw_changes, dict):
                    return f"坏地区对象：{region_id}"
                landed, refused = db.apply_region_deltas(
                    preview_state,
                    preflight_event,
                    None,
                    "档房",
                    {region_id: raw_changes},
                    commit=False,
                    source=Provenance.system_simulation,
                )
                for result in refused:
                    if isinstance(result, RejectedItem):
                        return f"地区拒收：{result.reason or result.category}"
                region_results.extend(landed)
            for army_id, raw_changes in army_items:
                if not isinstance(raw_changes, dict):
                    return f"坏军队对象：{army_id}"
                landed, refused = apply_army_delta_with_cannon_transfer(
                    db,
                    preview_state,
                    preflight_event,
                    str(army_id),
                    raw_changes,
                    source=Provenance.system_simulation,
                )
                for result in refused:
                    if isinstance(result, RejectedItem):
                        return f"军队拒收：{result.reason or result.category}"
                army_results.extend(landed)
        finally:
            db.conn.execute("ROLLBACK TO SAVEPOINT strategic_entity_result_preflight")
            db.conn.execute("RELEASE SAVEPOINT strategic_entity_result_preflight")

        if region_items and not any(
            pf._strategic_result_item_has_material_world_state(r) for r in region_results
        ):
            rid, raw = region_items[0]
            return (
                f"战略/外敌事件「{event_title or event_id}」战果 region.{rid}.region_delta "
                f"无真实世界状态变化：{raw!r}"
            )
        if army_items and not any(
            pf._strategic_result_item_has_material_world_state(r) for r in army_results
        ):
            aid, raw = army_items[0]
            return (
                f"战略/外敌事件「{event_title or event_id}」战果 army.{aid}.army_delta "
                f"无真实世界状态变化：{raw!r}"
            )
        return orig_preflight(
            db,
            state,
            event_id,
            event_title,
            outcome_label,
            {},
            {},
            power_updates,
            person_changes,
            new_armies,
            content,
            llm_config,
            preflight_event,
            ordered_region_items=[],
            ordered_army_items=[],
            ordered_power_items=ordered_power_items,
        )

    pf._strategic_event_result_preflight_error = preflight_with_class_level_any_material
    try:
        db, state, content = boot_game()
        try:
            log(
                f"R2_OLD_CLASS_ANY_MATERIAL_RED: "
                f"{_r2_scenario(db, state, content, label='old-r2')}"
            )
        finally:
            db.close()
    finally:
        pf._strategic_event_result_preflight_error = orig_preflight

    log(
        "WITHDRAWN_T1_CLAIM: w5-s1s4 mutation-probes S2_EVENT_WHOLE_PACKAGE_REJECT "
        "only exercised loyalty-only envelope; must not claim mixed-field/"
        "cannon-transfer whole-package preflight was established."
    )
    log("ALL_S2_MUTATION_PROBES_DONE")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
