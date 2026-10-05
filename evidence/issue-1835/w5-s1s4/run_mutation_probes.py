#!/usr/bin/env python3
"""#1835 S1–S4 mutation probes via real settle_delta / advance_issue.

NOT a test. In-process reinject old logic → old red / current green.
Withdraws prior overstrong claims (direct typed-result construction;
helper/symbol-only probes; ImportError noise).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import traceback
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

TMP = Path(tempfile.mkdtemp(prefix="1835-s1s4-mut-"))
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
    work = TMP / "game"
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
    return db, db.load_state(), content


def promulgate(db, state, text: str) -> str:
    dossier = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=text,
        target_kind="army",
        target_id="guanning",
    )
    db.record_dossier_decision(dossier, "promulgated")
    db.transition_decree_dossier(dossier, "executing")
    return f"dossier:{dossier}"


def main() -> int:
    log("=== MUTATION PROBES (real settle_delta / advance_issue; in-process reinject) ===")
    log(f"tmp={TMP}")
    log(
        "COMMAND: env MING_SIM_*_BIN=/usr/bin/false "
        ".venv/bin/python -B evidence/issue-1835/w5-s1s4/run_mutation_probes.py"
    )
    db = None
    try:
        db, state, content = boot_game()
        from ming_sim.applier import RejectedItem
        from ming_sim.entities.issue import delta_section as issue_delta
        from ming_sim.settlement import SettlementContext, settle_delta
        from ming_sim import staged_commitment as sc
        from ming_sim import db as dbmod
        from ming_sim import issues as issues_mod
        import ming_sim.cli_backend as cli_backend

        issues_mod.bind_content(content)
        ctx = SettlementContext(content=content)
        state.year, state.period = 1629, 11

        # Payload that reaches _resolve_strategic_events outcome_error path
        s1_payload = {
            "new_issues": [
                {"origin_kind": "event_pool", "id": "jisi_lubian", "title": "己巳虏变"}
            ],
            "region_delta": {
                "beizhili": {
                    "unrest": 1,
                    "reason": "战况",
                    "origin_ref": "jisi_lubian",
                }
            },
        }
        s1_kwargs = {"ordered_effect_event_ids": {"region_delta": ["jisi_lubian"]}}

        # ── S1: reinject old dict write ──
        orig_resolve = issue_delta._resolve_strategic_events

        def old_resolve(run, issue_summary):
            from ming_sim.settlement.preflight import (
                _strategic_event_outcome_label_or_error,
            )

            for new_issue in list(issue_summary.new_issues):
                if not (isinstance(new_issue, dict) and new_issue.get("deferred_trigger")):
                    continue
                event_id = str(new_issue.get("id") or "").strip()
                if event_id not in run.strategic_event_pool_ids:
                    continue
                _label, outcome_error = _strategic_event_outcome_label_or_error(
                    event_id, run.extracted, run.runtime_content,
                )
                if outcome_error:
                    # OLD (pre-fix): dict subscript on typed IssueSectionResult
                    issue_summary["rejected"].append(
                        RejectedItem(
                            item=new_issue,
                            reason=outcome_error,
                            category="missing_event_outcome",
                            source=run.ctx.source,
                        )
                    )
                    return {}
            return orig_resolve(run, issue_summary)

        issue_delta._resolve_strategic_events = old_resolve
        try:
            try:
                settle_delta(state, db, s1_payload, ctx, **s1_kwargs)
                log("S1_OLD_DICT_ACCESS_RED: UNEXPECTED_GREEN")
            except TypeError as exc:
                log(f"S1_OLD_DICT_ACCESS_RED: TypeError: {exc}")
            except Exception as exc:
                log(f"S1_OLD_DICT_ACCESS_RED: OTHER {type(exc).__name__}: {exc}")
        finally:
            issue_delta._resolve_strategic_events = orig_resolve

        out = settle_delta(state, db, s1_payload, ctx, **s1_kwargs)
        rejected = list(out.issue.rejected) if out.issue else []
        log(
            f"S1_CURRENT_ATTR_GREEN: rejected_len={len(rejected)} "
            f"cats={[getattr(r, 'category', None) for r in rejected[:3]]} "
            f"reasons={[str(getattr(r, 'reason', ''))[:60] for r in rejected[:2]]}"
        )

        # ── S2: old prose-stages silent capture via settle_delta ──
        def old_capture(raw=None):
            _MISS = object()
            if raw in (None, "", [], (), {}):
                return []
            if isinstance(raw, str):
                text = raw
                if not text.strip() or text.strip() in ("[]", "{}"):
                    return []
                try:
                    data = json.loads(text)
                except (TypeError, ValueError):
                    data = _MISS
                if data is not _MISS:
                    if not isinstance(data, (list, tuple)):
                        raise ValueError("stages 须为 JSON 数组")
                    if not data:
                        return []
                    structured = sc.normalize_commitment_stages(data)
                    if not structured:
                        raise ValueError("stages 无有效段")
                    return structured
                if text.lstrip()[:1] in "[{":
                    raise ValueError(
                        f"stages 须为 JSON 数组字符串，解析失败：{text!r}"
                    )
                return []  # OLD: prose → silent []
            if not isinstance(raw, (list, tuple)):
                raise ValueError("stages 须为 JSON 数组")
            structured = sc.normalize_commitment_stages(raw)
            if not structured:
                raise ValueError("stages 无有效段")
            return structured

        orig_list_from = sc.stages_list_from_source
        # Also silence stages_to_json for list-already-normalized empty from capture path:
        # tracker passes stages_norm (list) into insert → stages_to_json(list).
        sc.stages_list_from_source = old_capture
        try:
            origin = promulgate(db, state, "练兵分年旧")
            out_old = settle_delta(
                state,
                db,
                {
                    "new_issues": [
                        {
                            "origin_kind": "decree",
                            "origin_ref": origin,
                            "kind": "initiative",
                            "title": "散文 stages 旧捕获变异",
                            "commitment_kind": "until_stop",
                            "ongoing_effects": {
                                "economy": [
                                    {
                                        "account": "国库",
                                        "delta": -1,
                                        "reason": "练兵",
                                        "category": "军费",
                                    }
                                ]
                            },
                            "stages": "三年练兵五年成军",
                        }
                    ]
                },
                ctx,
            )
            ni = out_old.issue.new_issues if out_old.issue else []
            rj = [
                (getattr(r, "category", None), str(getattr(r, "reason", ""))[:80])
                for r in (out_old.issue.rejected if out_old.issue else [])
            ]
            log(f"S2_OLD_PROSE_STAGES_VIA_SETTLE: new={len(ni)} rejected={rj}")
        except Exception as exc:
            log(f"S2_OLD_PROSE_STAGES_VIA_SETTLE: EXC {type(exc).__name__}: {exc}")
        finally:
            sc.stages_list_from_source = orig_list_from

        origin2 = promulgate(db, state, "练兵分年新")
        out_cur = settle_delta(
            state,
            db,
            {
                "new_issues": [
                    {
                        "origin_kind": "decree",
                        "origin_ref": origin2,
                        "kind": "initiative",
                        "title": "散文 stages 当前严格面",
                        "commitment_kind": "until_stop",
                        "ongoing_effects": {
                            "economy": [
                                {
                                    "account": "国库",
                                    "delta": -1,
                                    "reason": "练兵",
                                    "category": "军费",
                                }
                            ]
                        },
                        "stages": "三年练兵五年成军",
                    }
                ]
            },
            ctx,
        )
        ni = out_cur.issue.new_issues if out_cur.issue else []
        rj = [
            (getattr(r, "category", None), str(getattr(r, "reason", ""))[:100])
            for r in (out_cur.issue.rejected if out_cur.issue else [])
        ]
        log(f"S2_CURRENT_PROSE_STAGES_VIA_SETTLE: new={len(ni)} rejected={rj}")

        # Event whole-package reject after shadow-formula deletion.
        # Real entrance = month_translate.dispatch_month_segment (same as #319 tracer):
        # latched loyalty at mutiny cap → preflight rejects entire strategic envelope;
        # unrelated region pressure must not land; event must not trigger.
        from ming_sim.month_translate import dispatch_month_segment

        army = "guanning"
        db.conn.execute(
            """UPDATE armies SET owner_power='ming', is_mutinied=1, mutiny_count=1,
               redemption_count=0, loyalty=80, arrears=5, manpower=10000,
               province_pay_arrears=0, central_pay_arrears=5
               WHERE id=?""",
            (army,),
        )
        db.conn.execute(
            "UPDATE regions SET military_pressure=? WHERE id='beizhili'", (20,)
        )
        db.conn.execute("DELETE FROM event_triggers WHERE event_id='jisi_lubian'")
        db.conn.commit()
        loyalty_before = db.conn.execute(
            "SELECT loyalty FROM armies WHERE id=?", (army,)
        ).fetchone()["loyalty"]
        pressure_before = db.conn.execute(
            "SELECT military_pressure FROM regions WHERE id='beizhili'"
        ).fetchone()["military_pressure"]
        dispatch_month_segment(
            db,
            state,
            segment="1835-s2-envelope-probe",
            translate_fn=lambda _request, _config: {
                "effects": [
                    {
                        "event_id": "jisi_lubian",
                        "new_issues": [
                            {"origin_kind": "event_pool", "id": "jisi_lubian"}
                        ],
                        "事件结局": {"jisi_lubian": "入塞被遏"},
                        "region_delta": {
                            "beizhili": {
                                "origin_ref": "盘面自发",
                                "military_pressure": 35,
                            }
                        },
                        "army_delta": {
                            army: {"origin_ref": "盘面自发", "loyalty": 5}
                        },
                        "metric_delta": {"民心": 1},
                    }
                ]
            },
        )
        loyalty_after = db.conn.execute(
            "SELECT loyalty FROM armies WHERE id=?", (army,)
        ).fetchone()["loyalty"]
        pressure_after = db.conn.execute(
            "SELECT military_pressure FROM regions WHERE id='beizhili'"
        ).fetchone()["military_pressure"]
        mind_after = int(state.metrics.get("民心", 50))
        log(
            f"S2_EVENT_WHOLE_PACKAGE_REJECT: loyalty {loyalty_before}->{loyalty_after} "
            f"pressure {pressure_before}->{pressure_after} mind_after={mind_after} "
            f"triggered={db.has_event_triggered('jisi_lubian')} "
            f"(expect loyalty/pressure unchanged, triggered=False; mind may land as independent)"
        )

        # ── S3: old resolve_condition-as-stop via advance_issue effect reinject ──
        orig_advance = dbmod.GameDB.advance_issue

        def advance_with_legacy_resolve_stop(self, state, issue_id, *args, **kwargs):
            row = self.conn.execute(
                "SELECT resolve_condition, commitment_kind, stop_condition FROM issues WHERE id=?",
                (issue_id,),
            ).fetchone()
            legacy = bool(
                re.fullmatch(
                    r"character\.[^.]+\.loyalty\s*(?:>=|>)\s*\d+",
                    str(row["resolve_condition"] or "").strip(),
                )
            )
            restored = False
            if legacy and not row["commitment_kind"] and not dbmod._has_stop_condition(
                row["stop_condition"]
            ):
                # Reinject old effect: resolve_condition loyalty prose acted as stop.
                self.conn.execute(
                    "UPDATE issues SET commitment_kind=? WHERE id=?",
                    ("until_stop", issue_id),
                )
                restored = True
            try:
                return orig_advance(self, state, issue_id, *args, **kwargs)
            finally:
                if restored:
                    self.conn.execute(
                        "UPDATE issues SET commitment_kind=? WHERE id=?",
                        ("", issue_id),
                    )
                    if kwargs.get("commit", True):
                        self.conn.commit()

        iid = db.insert_issue(
            state,
            kind="initiative",
            title="旧 resolve 冒充 stop 变异",
            origin_kind="decree",
            origin_ref="decree:turn-1:legacy-resolve-mut",
            bar_value=90,
            resolve_condition="character.毛文龙.loyalty >= 65",
        )
        dbmod.GameDB.advance_issue = advance_with_legacy_resolve_stop
        try:
            old_row = db.advance_issue(
                state, iid, trigger_kind="decree", delta_bar=20, narrative="满值"
            )
            log(
                f"S3_OLD_RESOLVE_AS_STOP_VIA_ADVANCE: status={old_row['status']} "
                f"bar={old_row['bar_value']}"
            )
        finally:
            dbmod.GameDB.advance_issue = orig_advance

        iid2 = db.insert_issue(
            state,
            kind="initiative",
            title="当前 resolve 不冒充 stop",
            origin_kind="decree",
            origin_ref="decree:turn-1:legacy-resolve-cur",
            bar_value=90,
            resolve_condition="character.毛文龙.loyalty >= 65",
        )
        cur_row = db.advance_issue(
            state, iid2, trigger_kind="decree", delta_bar=20, narrative="满值"
        )
        log(
            f"S3_CURRENT_RESOLVE_NOT_STOP_VIA_ADVANCE: status={cur_row['status']} "
            f"bar={cur_row['bar_value']}"
        )
        iid3 = db.insert_issue(
            state,
            kind="initiative",
            title="typed stop 仍挡满值",
            origin_kind="decree",
            origin_ref="decree:turn-1:typed-stop",
            bar_value=90,
            stop_condition={"character.毛文龙.loyalty": ">=65"},
            commitment_kind="until_stop",
        )
        typed_row = db.advance_issue(
            state, iid3, trigger_kind="decree", delta_bar=20, narrative="满值"
        )
        log(
            f"S3_TYPED_STOP_STILL_GATES: status={typed_row['status']} "
            f"bar={typed_row['bar_value']}"
        )

        # ── S4: old floor via settle_delta (insert_issue reinject after empty enrich) ──
        orig_active = cli_backend.cli_backend_active
        orig_enrich = cli_backend.enrich_initiative_effects
        cli_backend.cli_backend_active = lambda _cfg=None: True
        cli_backend.enrich_initiative_effects = lambda *a, **k: {
            "effect_on_resolve": {},
            "ongoing_effects": {},
            "effect_on_fail": {},
        }
        _orig_insert = db.insert_issue

        def insert_with_floor(st, **kw):
            if (
                kw.get("kind") == "initiative"
                and not kw.get("commitment_kind")
                and not (kw.get("effect_on_resolve") or {})
            ):
                kw = dict(kw)
                kw["effect_on_resolve"] = {"metrics": {"民心": 1}}
            return _orig_insert(st, **kw)

        db.insert_issue = insert_with_floor
        try:
            settle_delta(
                state,
                db,
                {
                    "new_issues": [
                        {
                            "origin_kind": "decree",
                            "kind": "initiative",
                            "title": "空回报国策变异旧floor",
                            "stage_text": "空",
                            "origin_ref": promulgate(db, state, "空回报旧"),
                        }
                    ]
                },
                SettlementContext(content=content, llm_config={"backend": "agy"}),
            )
            row = db.conn.execute(
                "SELECT effect_on_resolve FROM issues WHERE title=?",
                ("空回报国策变异旧floor",),
            ).fetchone()
            log(
                f"S4_OLD_FLOOR_VIA_SETTLE: effect={row['effect_on_resolve'] if row else None}"
            )
        finally:
            db.insert_issue = _orig_insert

        settle_delta(
            state,
            db,
            {
                "new_issues": [
                    {
                        "origin_kind": "decree",
                        "kind": "initiative",
                        "title": "空回报国策变异当前",
                        "stage_text": "空",
                        "origin_ref": promulgate(db, state, "空回报新"),
                    }
                ]
            },
            SettlementContext(content=content, llm_config={"backend": "agy"}),
        )
        row = db.conn.execute(
            "SELECT effect_on_resolve FROM issues WHERE title=?",
            ("空回报国策变异当前",),
        ).fetchone()
        log(
            f"S4_CURRENT_NO_FLOOR_VIA_SETTLE: effect={row['effect_on_resolve'] if row else None}"
        )

        cli_backend.cli_backend_active = orig_active
        cli_backend.enrich_initiative_effects = orig_enrich

        log(
            "WITHDRAWN_PRIOR_CLAIMS: prior S1 constructed IssueSectionResult[] directly; "
            "prior S2 helper/symbol probes + ImportError×2 — not real-entrance evidence."
        )
        log("ALL_MUTATION_PROBES_DONE")
        return 0
    except Exception:
        log("PROBE_FATAL:\n" + traceback.format_exc())
        return 1
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        shutil.rmtree(TMP, ignore_errors=True)
        print(f"wrote {OUT}; tmp_exists={TMP.exists()}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
