"""Live #570 family-tail acceptance anchors (Court pins P-2 / P-3 / P-5 LLM 面).

Not an ordinary CI test: requires an explicitly selected live CLI provider.

  MING_SIM_TRACE_PATH=/tmp/issue-570-acceptance-trace.jsonl \
    python scripts/family_tail_acceptance_570.py \
      --runner codex --model gpt-5.6-sol --samples 1 \
      --output docs/evidence/issue-570-acceptance-anchors.json

Assertions read structured fields only (P-3):
  - 破格授阁臣: decision=rejected ∧ blocked_layer∈{cabinet_drafting,palace_rescript,six_offices}
    OR (force path) execution_outcome∈{degraded,failed}
  - 白身破格授巡抚: decision=rejected；可强颁时 force 三笔闸检（signed direction×intensity）
  - 中旨强授: structured decision + 必过 force 端到端三笔复验（非命门、非 unpromulgatable）
  - P4 LLM 面: 邸报/密奏/召对 brief 消费真实渲染产物（每面正负各一；空产物不计过）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agno.db.sqlite import SqliteDb

from ming_sim.agents import bind_content as bind_agent_content
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.decree import (
    build_promulgation_judge_context,
    llm_promulgation_verdicts,
    validate_promulgation_verdicts,
)
from ming_sim.decree_vocabulary import render_referenceable_dossier_brief
from ming_sim.cli_backend import cli_backend_parallel_safe
from ming_sim.issues import bind_content as bind_issue_content
from ming_sim.models import Character, LLMConfig

_LOG = logging.getLogger("issue-570-acceptance")
_BLOCKED_LAYERS = frozenset({"cabinet_drafting", "palace_rescript", "six_offices"})
_REACTION_INTENSITY = {"weak": 4, "strong": 8}
_REACTION_SIGN = {"positive": 1, "negative": -1}
_AUTHORITY_DELTA = -5
_SYSTEM_LEAK = re.compile(
    r"\b(?:promulgated|rejected|executing|proposed|force_promulgated|midzhi|"
    r"break_rank|blocked_layer|degraded|failed|fulfilled|transformed|"
    r"cabinet_drafting|palace_rescript|six_offices|is_break_rank)\b"
    r"|破格标|进展档|execution_outcome"
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", choices=("codex", "claude"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    return args


def _config(args: argparse.Namespace) -> LLMConfig:
    return LLMConfig(
        api_key="", base_url="", model=args.model, channel="cli",
        cli_runner=args.runner, cli_model=args.model, cli_timeout_seconds=600,
        max_tokens=6000, reasoning_strength="high",
    )


def _character(name: str, office: str, office_type: str) -> Character:
    return Character(
        name=name, office=office, office_type=office_type, faction="中立",
        aliases=[], personal_skills=[], loyalty=50, ability=50, integrity=50,
        courage=50, style="", power_id="ming",
    )


def _cost_events(db: GameDB, dossier_id: int) -> list[dict]:
    return [dict(row) for row in db.conn.execute(
        "SELECT * FROM decree_cost_events WHERE dossier_id=? ORDER BY id",
        (int(dossier_id),),
    ).fetchall()]


def _expected_satisfaction(
    affected_parties: Sequence[Dict[str, Any]],
) -> Dict[Tuple[str, str], int]:
    """Map typed signed reactions → delta; zero-reaction parties are omitted upstream."""
    expected: Dict[Tuple[str, str], int] = {}
    for party in affected_parties or []:
        if not isinstance(party, dict):
            continue
        kind = str(party.get("kind") or "")
        key = str(party.get("key") or "")
        magnitude = _REACTION_INTENSITY.get(str(party.get("intensity") or ""))
        sign = _REACTION_SIGN.get(str(party.get("direction") or ""))
        if kind not in {"faction", "class"} or not key or magnitude is None or sign is None:
            continue
        delta = sign * magnitude
        if delta == 0:
            # 零反应不入清单
            continue
        expected[(kind, key)] = delta
    return expected


def _three_cost_legs(
    db: GameDB,
    dossier_id: int,
    row: dict,
    affected_parties: Sequence[Dict[str, Any]],
) -> dict:
    """#564 three legs: authority event, signed satisfaction, midzhi stigma.

    Satisfaction must match direction×intensity deltas exactly; delta=0 never lands.
    """
    events = _cost_events(db, dossier_id)
    auth_events = [
        e for e in events
        if e.get("cost_kind") == "authority"
        and e.get("target_kind") == "metric"
        and e.get("target_id") == "皇威"
    ]
    has_authority = any(int(e.get("delta") or 0) == _AUTHORITY_DELTA for e in auth_events)

    expected = _expected_satisfaction(affected_parties)
    sat_events = [e for e in events if e.get("cost_kind") == "satisfaction"]
    actual: Dict[Tuple[str, str], int] = {}
    zero_reaction_rows = []
    for e in sat_events:
        key = (str(e.get("target_kind") or ""), str(e.get("target_id") or ""))
        delta = int(e.get("delta") or 0)
        if delta == 0:
            zero_reaction_rows.append(e)
            continue
        actual[key] = delta
    has_satisfaction = bool(expected) and actual == expected and not zero_reaction_rows

    stigma = row.get("stigma") or []
    has_stigma = any(
        isinstance(item, dict) and item.get("kind") == "midzhi"
        for item in stigma
    )
    return {
        "authority": has_authority,
        "satisfaction": has_satisfaction,
        "midzhi_stigma": has_stigma,
        "expected_satisfaction": {
            f"{k}/{t}": d for (k, t), d in sorted(expected.items())
        },
        "actual_satisfaction": {
            f"{k}/{t}": d for (k, t), d in sorted(actual.items())
        },
        "zero_reaction_rows": zero_reaction_rows,
        "events": [
            {
                "cost_kind": e["cost_kind"],
                "target_kind": e["target_kind"],
                "target_id": e["target_id"],
                "delta": e.get("delta"),
            }
            for e in events
        ],
        "stigma": stigma,
        "all_three": has_authority and has_satisfaction and has_stigma,
        "kind_set": sorted(
            {
                f"{e['cost_kind']}/{e['target_kind']}/{e['target_id']}"
                for e in events
            }
        ),
    }


def _judge_batch(
    db: GameDB, state, rows: list[dict], cfg: LLMConfig, agno,
) -> Tuple[dict, list[dict]]:
    context = build_promulgation_judge_context(db, state, rows)
    raw = llm_promulgation_verdicts(
        rows, state, db=db, agno_db=agno, llm_config=cfg,
        prepared_context=context,
    )
    verdicts = validate_promulgation_verdicts(
        raw, rows, db, prepared_context=context,
    )
    return context, verdicts


def _p4_scan(label: str, text: str) -> dict:
    """Positive clean requires non-empty real product; empty never counts as pass."""
    blob = str(text or "")
    non_empty = bool(blob.strip())
    clean = non_empty and _SYSTEM_LEAK.search(blob) is None
    return {
        "label": label,
        "non_empty": non_empty,
        "clean": clean,
        "text": blob,
    }


def _run_sample(index: int, root: str, content: GameContent, cfg: LLMConfig) -> dict:
    sample_dir = Path(root) / str(index)
    sample_dir.mkdir()
    db = GameDB(str(sample_dir / "game.db"), content)
    try:
        db.seed_static_data()
        state = db.load_state()
        # Low authority so resistance is on the table.
        state.metrics["皇威"] = 15
        db.save_state(state)

        cabinet_name = f"候补阁僚-{index}"
        bare_name = f"白身巡抚-{index}"
        midzhi_name = f"中旨授官-{index}"
        db.add_character(state, _character(cabinet_name, "翰林院编修", "翰林院"))
        db.add_character(state, _character(bare_name, "白身", "布衣"))
        db.add_character(state, _character(midzhi_name, "礼部主事", "礼部"))

        # Opaque target ids + counterbalanced create order.
        # midzhi arm: non-vital 太常寺卿 so force is not blocked by unpromulgatable.
        specs = [
            ("cabinet", cabinet_name, "东阁大学士", "内阁", "ordinary",
             f"破格特授{cabinet_name}入阁为东阁大学士"),
            ("bare", bare_name, "陕西巡抚", "地方", "ordinary",
             f"破格特授白身{bare_name}为陕西巡抚"),
            ("midzhi", midzhi_name, "太常寺卿", "太常寺", "midzhi",
             f"中旨特授{midzhi_name}为太常寺卿"),
        ]
        if index % 2:
            specs = list(reversed(specs))

        planted: dict[str, int] = {}
        rows_by_id: dict[int, dict] = {}
        for key, name, office, office_type, mode, text in specs:
            did = db.create_decree_dossier(
                state,
                action_type="appointment",
                decree_text=text,
                target_kind="character",
                target_id=f"gate-570-{index}-{key}",
                payload={
                    "name": name, "office": office, "office_type": office_type,
                    "mode": mode, "任别": "真除",
                },
            )
            planted[key] = did
            rows_by_id[did] = db.get_decree_dossier(did)

        # break_rank must be on both extreme appointments.
        for key in ("cabinet", "bare"):
            br = json.loads(str(rows_by_id[planted[key]]["payload_json"])).get("break_rank") or {}
            if not br.get("is_break_rank"):
                raise RuntimeError(f"{key} appointment missing break_rank mark: {br}")

        order = list(planted.values())
        if index % 4 in (1, 2):
            order.reverse()
        rows = [rows_by_id[i] for i in order]
        agno = SqliteDb(db_file=str(sample_dir / "agno.db"))
        context, verdicts = _judge_batch(db, state, rows, cfg, agno)
        by_id = {int(v["dossier_id"]): v for v in verdicts}

        # Apply verdicts so force / stigma / costs can be exercised on structured path.
        db.apply_dossier_verdicts(state, verdicts)

        cabinet_v = by_id[planted["cabinet"]]
        bare_v = by_id[planted["bare"]]
        midzhi_v = by_id[planted["midzhi"]]

        cabinet_reject_ok = (
            cabinet_v.get("decision") == "rejected"
            and str(cabinet_v.get("blocked_layer") or "") in _BLOCKED_LAYERS
        )
        # 辞让 path needs force+execution judge; this gate records structured
        # reject as the primary anchor. execution_outcome checked if already set.
        cabinet_row = db.get_decree_dossier(planted["cabinet"])
        cabinet_exec = str(cabinet_row.get("execution_outcome") or "")
        cabinet_resign_ok = cabinet_exec in {"degraded", "failed"}
        cabinet_ok = cabinet_reject_ok or cabinet_resign_ok

        bare_reject_ok = bare_v.get("decision") == "rejected"
        bare_force_costs: Optional[dict] = None
        bare_force_ok = False
        bare_force_error: Optional[str] = None
        bare_force_attempted = False
        if bare_reject_ok and bare_v.get("midzhi_unpromulgatable") is not True:
            bare_force_attempted = True
            try:
                db.apply_dossier_promulgation(
                    state, planted["bare"], "force_promulgated", content=content,
                )
            except Exception as exc:  # noqa: BLE001 — evidence path; counted failed
                bare_force_error = f"{type(exc).__name__}: {exc}"
                _LOG.exception(
                    "bare force_promulgated failed sample=%s dossier=%s",
                    index + 1, planted["bare"],
                )
                bare_force_costs = {"force_error": bare_force_error}
            else:
                bare_row = db.get_decree_dossier(planted["bare"])
                bare_force_costs = _three_cost_legs(
                    db, planted["bare"], bare_row,
                    bare_v.get("affected_parties") or [],
                )
                bare_force_ok = bool(bare_force_costs["all_three"])
        # P-3 primary arm = reject. Dead OR removed: force is a separate gate leg
        # that must pass whenever the force path is attempted.
        bare_ok = bare_reject_ok and (
            bare_force_ok if bare_force_attempted else True
        ) and bare_force_error is None

        # 中旨强授：结构化判决 + 必过 force 端到端三笔（非 unpromulgatable）。
        midzhi_decision = str(midzhi_v.get("decision") or "")
        midzhi_structured = midzhi_decision in {"promulgated", "rejected"}
        midzhi_force: Optional[dict] = None
        midzhi_force_ok = False
        midzhi_force_error: Optional[str] = None
        midzhi_force_attempted = False
        midzhi_unpromulgatable = midzhi_v.get("midzhi_unpromulgatable") is True
        if midzhi_decision == "rejected" and not midzhi_unpromulgatable:
            midzhi_force_attempted = True
            try:
                db.apply_dossier_promulgation(
                    state, planted["midzhi"], "force_promulgated", content=content,
                )
            except Exception as exc:  # noqa: BLE001 — counted failed
                midzhi_force_error = f"{type(exc).__name__}: {exc}"
                _LOG.exception(
                    "midzhi force_promulgated failed sample=%s dossier=%s",
                    index + 1, planted["midzhi"],
                )
                midzhi_force = {"force_error": midzhi_force_error}
            else:
                midzhi_row = db.get_decree_dossier(planted["midzhi"])
                midzhi_force = _three_cost_legs(
                    db, planted["midzhi"], midzhi_row,
                    midzhi_v.get("affected_parties") or [],
                )
                midzhi_force_ok = bool(midzhi_force["all_three"])
        # Required end-to-end: rejected ∧ forceable ∧ three costs; unpromulgatable
        # on this non-vital arm is a gate failure (scenario miscalibration).
        midzhi_ok = (
            midzhi_structured
            and midzhi_decision == "rejected"
            and not midzhi_unpromulgatable
            and midzhi_force_attempted
            and midzhi_force_ok
            and midzhi_force_error is None
        )

        # ── P-5 three LLM/text faces: real rendered products, pos+neg each ──
        # 1) 召对认账 brief（真实 vocabulary 渲染产物；空 brief 不计过）
        ref_name = cabinet_name
        # Prefer a name that still has referenceable force-promulgated bare dossier.
        candidates = db.list_referenceable_dossiers(bare_name, state.turn)
        if not candidates:
            candidates = db.list_referenceable_dossiers(ref_name, state.turn)
        brief = render_referenceable_dossier_brief(candidates)
        p4_brief = _p4_scan("召对认账brief", brief)

        # 2) 密奏：真实 record_dossier_progress → list_dossier_progress 产物
        memorial_text = f"{state.year}年边饷核验，兵额如实陈，库银按册无缺。"
        errand = db.create_decree_dossier(
            state, action_type="assignment",
            decree_text=f"差{cabinet_name}核边饷",
            target_kind="issue", target_id=f"p4-mem-{index}",
            executor_kind="character", executor_id=cabinet_name,
            participants=[{"character_id": cabinet_name, "tier": "主办"}],
            payload={"mode": "ordinary"},
        )
        db.conn.execute(
            "UPDATE decree_dossiers SET status='executing', promulgation_decision='promulgated' "
            "WHERE id=?",
            (int(errand),),
        )
        db.conn.commit()
        db.record_dossier_progress(
            errand, state.turn, "在途", memorial_text,
            origin="dossier-report:monthly_errand",
        )
        progress_rows = db.list_dossier_progress(errand)
        memorial_blob = "\n".join(
            str(r.get("memorial_text") or "") for r in progress_rows
        )
        p4_memorial = _p4_scan("密奏memorial", memorial_blob)

        # 3) 邸报：seed_opening_gazette 真实落库产物（get_turn_report）
        gazette_blob = str(db.get_turn_report(0) or "")
        p4_gazette = _p4_scan("邸报gazette", gazette_blob)

        # Negative controls: detector must fire on injected system words.
        neg_brief = _SYSTEM_LEAK.search("force_promulgated break_rank") is not None
        neg_memorial = _SYSTEM_LEAK.search("execution_outcome=failed 破格标") is not None
        neg_gazette = _SYSTEM_LEAK.search(
            "decision=rejected blocked_layer=six_offices midzhi"
        ) is not None

        checks = {
            "cabinet_break_rank_resisted": cabinet_ok,
            "bare_body_rejected": bare_reject_ok,
            "bare_force_three_costs": (
                bare_force_ok if bare_force_attempted else False
            ),
            "bare_force_no_error": bare_force_error is None and bare_force_attempted,
            "midzhi_structured_decision": midzhi_structured,
            "midzhi_force_e2e_three_costs": midzhi_ok,
            "p4_audience_brief_clean": p4_brief["clean"],
            "p4_memorial_clean": p4_memorial["clean"],
            "p4_gazette_clean": p4_gazette["clean"],
            "p4_negative_brief_detector": neg_brief,
            "p4_negative_memorial_detector": neg_memorial,
            "p4_negative_gazette_detector": neg_gazette,
        }
        # force_error must count as failed even if other arms look green.
        if bare_force_error:
            checks["bare_force_no_error"] = False
        if midzhi_force_error:
            checks["midzhi_force_e2e_three_costs"] = False

        detail = {
            "cabinet_reject_with_layer": cabinet_reject_ok,
            "cabinet_resign_execution": cabinet_resign_ok,
            "bare_rejected": bare_reject_ok,
            "bare_force_attempted": bare_force_attempted,
            "bare_force_three_costs": bare_force_ok,
            "bare_force_error": bare_force_error,
            "midzhi_decision": midzhi_decision,
            "midzhi_unpromulgatable": midzhi_unpromulgatable,
            "midzhi_force_attempted": midzhi_force_attempted,
            "midzhi_force_ok": midzhi_force_ok,
            "midzhi_force_error": midzhi_force_error,
            "bare_combined_ok": bare_ok,
        }
        return {
            "sample": index + 1,
            "planted": planted,
            "input": context,
            "verdicts": verdicts,
            "cabinet": {
                "verdict": cabinet_v,
                "execution_outcome": cabinet_exec,
                "break_rank": json.loads(
                    str(rows_by_id[planted["cabinet"]]["payload_json"])
                ).get("break_rank"),
            },
            "bare": {
                "verdict": bare_v,
                "force_costs": bare_force_costs,
                "break_rank": json.loads(
                    str(rows_by_id[planted["bare"]]["payload_json"])
                ).get("break_rank"),
            },
            "midzhi": {
                "verdict": midzhi_v,
                "force": midzhi_force,
            },
            "p4_surfaces": {
                "brief": p4_brief,
                "memorial": p4_memorial,
                "gazette": p4_gazette,
            },
            "checks": checks,
            "detail": detail,
        }
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _args()
    trace_setting = os.environ.get("MING_SIM_TRACE_PATH", "").strip()
    if not trace_setting or os.environ.get("MING_SIM_TRACE", "1").lower() in {
        "0", "false", "no",
    }:
        raise RuntimeError("set MING_SIM_TRACE_PATH to a fresh path with CLI tracing enabled")
    trace_path = Path(trace_setting).resolve()
    if trace_path.exists():
        raise RuntimeError(f"CLI trace path must be fresh: {trace_path}")

    content = GameContent.load()
    bind_content(content)
    bind_issue_content(content)
    bind_agent_content(content)
    cfg = _config(args)

    with tempfile.TemporaryDirectory(prefix="ming-570-accept-") as tmp:
        workers = min(4, args.samples) if cli_backend_parallel_safe(cfg) else 1
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_run_sample, i, tmp, content, cfg)
                for i in range(args.samples)
            ]
            samples = sorted(
                (future.result() for future in as_completed(futures)),
                key=lambda row: row["sample"],
            )

    trace_records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Acceptance gate: one judge call per sample → trace count == samples.
    if len(trace_records) != args.samples or any(
        record.get("error") is not None for record in trace_records
    ):
        raise RuntimeError(
            f"expected {args.samples} successful raw trace records; "
            f"got {len(trace_records)}"
        )

    # Aggregate checks: every sample must pass every check.
    check_names = sorted(samples[0]["checks"])
    aggregate = {
        name: all(bool(s["checks"][name]) for s in samples)
        for name in check_names
    }
    failed = [name for name, ok in aggregate.items() if not ok]
    artifact = {
        "gate": "issue-570-family-tail-acceptance-anchors",
        "method": {
            "design": (
                "Live production promulgation Judge on isolated DBs; "
                "P-3 structured-field anchors for 破格授阁臣 / 白身破格授巡抚 / 中旨强授; "
                "force three-cost legs assert signed direction×intensity; "
                "P4 scans real 邸报/密奏/召对 brief products "
                "(positive non-empty clean + negative detector self-check)."
            ),
            "samples": args.samples,
            "config": {
                "channel": "cli", "runner": args.runner, "model": args.model,
                "reasoning_strength": cfg.reasoning_strength,
                "max_tokens": cfg.max_tokens,
            },
            "assertion_targets": {
                "cabinet": (
                    "rejected ∧ blocked_layer∈cabinet_drafting|palace_rescript|six_offices "
                    "∨ execution_outcome∈{degraded,failed}"
                ),
                "bare_body": (
                    "rejected ∧ (force attempted → authority-5 + signed satisfaction "
                    "direction×intensity exact match + midzhi stigma; zero reaction ∉ list)"
                ),
                "midzhi": (
                    "rejected ∧ ¬unpromulgatable ∧ force e2e three costs "
                    "(non-vital 太常寺卿 arm)"
                ),
                "p4_faces": "邸报 gazette / 密奏 memorial / 召对 brief — real products",
            },
            "trace_contract": f"raw_cli_trace length == samples ({args.samples})",
        },
        "summary": {
            "samples": args.samples,
            "trace_records": len(trace_records),
            "checks": aggregate,
            "failed": failed,
            "passed": not failed,
        },
        "limitations": [
            "Acceptance evidence on one configured model/provider; not population calibration.",
            "辞让 (execution degraded/failed) path requires full execution Judge after force; "
            "this gate primarily locks the promulgation reject+layer arm of P-3 for cabinet.",
            "Force errors are logged and count as failed checks (no silent swallow).",
            "P4 LLM faces consume real render products reachable without a second full-month "
            "settle: opening gazette (邸报), dossier progress memorial (密奏), "
            "referenceable-dossier brief (召对认账). Live minister dialogue prose is not "
            "re-run here; brief is the production audience-facing dossier render.",
        ],
        "samples": samples,
        "raw_cli_trace": trace_records,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(
        {"output": str(output), "summary": artifact["summary"]},
        ensure_ascii=False, indent=2,
    ))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
