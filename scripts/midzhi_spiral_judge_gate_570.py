"""Live #570 midzhi-spiral paired comparison (Court pin P-4).

Same board; sole intervention = prior force_promulgated history 3 vs 0.
Target IDs / presentation order counterbalanced. Exact two-sided paired sign
test α=0.05. samples default 12, minimum 6.

This is acceptance evidence only — MUST NOT add production midzhi
threshold / counter / ratchet (PRD #556 OOS).

Scenario design (r1 diagnosis):
  Prior red evidence used a 田亩清册 decree that hit Donglin anti-清丈 agenda on
  BOTH arms → 12/12 reject / 0 discordant → cannot distinguish scenario ceiling
  from Judge history-insensitivity. This revision uses the #561 administrative
  midzhi that is designed to promulgate on a clean board (sole intervention =
  history markers). If clean promulgates and hist does not reject more often,
  the failure diagnoses Judge-side history insensitivity (prompt never names
  promulgation_history) — hold evidence, do not self-exempt AC④, no production
  ratchet.

  MING_SIM_TRACE_PATH=/tmp/issue-570-spiral-trace.jsonl \
    python scripts/midzhi_spiral_judge_gate_570.py \
      --runner codex --model gpt-5.6-sol --samples 12 \
      --output docs/evidence/issue-570-midzhi-spiral.json

  # 族尾闸新跑默认 ds-flash 档（api 通道；opus 仅争议复裁与同基对照）：
  # MING_SIM_API_KEY=... MING_SIM_API_BASE_URL=https://opencode.ai/zen/v1 \
  #   python scripts/midzhi_spiral_judge_gate_570.py --channel api \
  #     --model deepseek-v4-flash --samples 6 \
  #     --output docs/evidence/issue-570-midzhi-spiral-ds-flash.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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
from ming_sim.cli_backend import (
    add_gate_llm_args,
    cli_backend_parallel_safe,
    gate_evidence_config,
    gate_llm_config_from_args,
)
from ming_sim.issues import bind_content as bind_issue_content

# #561 administrative midzhi — designed to promulgate (stigma path), not a
# vital 命门 reverse-scale item. Spiral signal needs a decree that CAN pass
# without force-history; only the history arm should become more rejectable.
TEST_MIDZHI_TEXT = "中旨命内廷整理既有文册，不动外廷钱权"
# Board agenda must NOT itself veto the test decree (prior 反对清丈 ceiling).
BOARD_DONGLIN_AGENDA = "整肃吏治，慎核边饷"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_gate_llm_args(parser)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.samples < 6:
        parser.error("--samples must be at least 6")
    return args


def _two_sided_sign_p(a_only: int, b_only: int) -> float:
    """Exact paired sign/McNemar test on discordant pairs."""
    n = a_only + b_only
    if not n:
        return 1.0
    k = min(a_only, b_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _config(args: argparse.Namespace):
    return gate_llm_config_from_args(args)


def _plant_force_history(db: GameDB, state, count: int) -> list[int]:
    """Persist count prior 批红强颁 markers visible to build_promulgation_judge_context."""
    ids = []
    for i in range(count):
        # Prior force rows themselves carry midzhi mode so history reads as
        # repeated 中旨/强颁 spiral texture (still only decision-table evidence).
        did = db.create_decree_dossier(
            state,
            action_type="policy",
            decree_text=f"历史中旨强颁先例-{i + 1}：绕票拟径发内廷差遣",
            target_kind="issue",
            target_id=f"hist-force-{i}",
            payload={"mode": "midzhi"},
        )
        # Closed historical force row: decision rejected + rescript force.
        # History loader joins decisions×payload; marker=批红强颁 when rescript_action set.
        db.conn.execute(
            """
            UPDATE decree_dossiers
            SET status='closed', promulgation_decision='rejected',
                rescript_pending=0, closed_turn=?
            WHERE id=?
            """,
            (int(state.turn), int(did)),
        )
        db.conn.execute(
            """
            INSERT INTO decree_dossier_decisions
                (dossier_id, turn, decision, rescript_action, reason, legal_reason_code)
            VALUES (?, ?, 'rejected', 'force_promulgated', '批红强颁', '')
            """,
            (int(did), max(1, int(state.turn) - 1)),
        )
        ids.append(did)
    db.conn.commit()
    return ids


def _run_arm(
    db: GameDB, state, cfg: LLMConfig, agno, *,
    force_history: int, target_id: str,
) -> dict:
    hist_ids = _plant_force_history(db, state, force_history) if force_history else []
    # Single midzhi test decree only. An ordinary filler invites the model to
    # attach affected_parties on ordinary promulgate (illegal per #564) and
    # collapses the pair under validator noise unrelated to the spiral signal.
    test_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=TEST_MIDZHI_TEXT,
        target_kind="issue",
        target_id=target_id,
        payload={"mode": "midzhi"},
    )
    rows = [db.get_decree_dossier(test_id)]
    context = build_promulgation_judge_context(db, state, rows)
    history_markers = [
        item.get("marker") for item in context.get("promulgation_history") or []
    ]
    raw = llm_promulgation_verdicts(
        rows, state, db=db, agno_db=agno, llm_config=cfg,
        prepared_context=context,
    )
    verdicts = validate_promulgation_verdicts(
        raw, rows, db, prepared_context=context,
    )
    by_id = {int(v["dossier_id"]): v for v in verdicts}
    test_v = by_id[test_id]
    return {
        "force_history": force_history,
        "hist_ids": hist_ids,
        "test_id": test_id,
        "history_markers": history_markers,
        "context": context,
        "verdicts": verdicts,
        "test_rejected": test_v.get("decision") == "rejected",
        "test_verdict": test_v,
    }


def _open_pair(root: str, index: int, content: GameContent) -> tuple:
    pair_dir = Path(root) / str(index)
    pair_dir.mkdir()
    # Two isolated DBs: history=3 vs history=0; same seed board otherwise.
    dbs = []
    for arm in ("hist3", "hist0"):
        arm_dir = pair_dir / arm
        arm_dir.mkdir()
        db = GameDB(str(arm_dir / "game.db"), content)
        db.seed_static_data()
        state = db.load_state()
        # Moderate authority: admin midzhi should clear on clean arm (#561 path).
        state.metrics["皇威"] = 55
        db.conn.execute(
            "UPDATE factions SET leverage=70, agenda=? WHERE name='东林'",
            (BOARD_DONGLIN_AGENDA,),
        )
        db.save_state(state)
        db.conn.commit()
        agno = SqliteDb(db_file=str(arm_dir / "agno.db"))
        dbs.append((db, state, agno))
    return dbs


def _run_sample(index: int, root: str, content: GameContent, cfg: LLMConfig) -> dict:
    (db_a, state_a, agno_a), (db_b, state_b, agno_b) = _open_pair(root, index, content)
    try:
        # Counterbalance arm run order and opaque target ids.
        if index % 2 == 0:
            hist_first = True
            id_hist, id_clean = f"spiral-{index}-H", f"spiral-{index}-C"
        else:
            hist_first = False
            id_hist, id_clean = f"spiral-{index}-C", f"spiral-{index}-H"

        def run_hist():
            return _run_arm(
                db_a, state_a, cfg, agno_a,
                force_history=3, target_id=id_hist,
            )

        def run_clean():
            return _run_arm(
                db_b, state_b, cfg, agno_b,
                force_history=0, target_id=id_clean,
            )

        if hist_first:
            hist_arm = run_hist()
            clean_arm = run_clean()
        else:
            clean_arm = run_clean()
            hist_arm = run_hist()

        # Sanity: history arm must expose 3 批红强颁 markers.
        force_markers = [
            m for m in hist_arm["history_markers"] if m == "批红强颁"
        ]
        if len(force_markers) < 3:
            raise RuntimeError(
                f"hist arm expected ≥3 批红强颁 markers; got {hist_arm['history_markers']}"
            )
        if any(m == "批红强颁" for m in clean_arm["history_markers"]):
            raise RuntimeError("clean arm must not carry force history markers")

        return {
            "sample": index + 1,
            "hist_first": hist_first,
            "hist": {
                "test_rejected": hist_arm["test_rejected"],
                "test_verdict": hist_arm["test_verdict"],
                "history_markers": hist_arm["history_markers"],
                "input": hist_arm["context"],
            },
            "clean": {
                "test_rejected": clean_arm["test_rejected"],
                "test_verdict": clean_arm["test_verdict"],
                "history_markers": clean_arm["history_markers"],
                "input": clean_arm["context"],
            },
            "classification": {
                "hist_rejected": hist_arm["test_rejected"],
                "clean_rejected": clean_arm["test_rejected"],
            },
        }
    finally:
        db_a.close()
        db_b.close()


def main() -> int:
    args = _args()
    content = GameContent.load()
    bind_content(content)
    bind_issue_content(content)
    bind_agent_content(content)
    cfg = _config(args)
    trace_path = None
    if cfg.channel == "cli":
        trace_setting = os.environ.get("MING_SIM_TRACE_PATH", "").strip()
        if not trace_setting or os.environ.get("MING_SIM_TRACE", "1").lower() in {
            "0", "false", "no",
        }:
            raise RuntimeError("set MING_SIM_TRACE_PATH to a fresh path with CLI tracing enabled")
        trace_path = Path(trace_setting).resolve()
        if trace_path.exists():
            raise RuntimeError(f"CLI trace path must be fresh: {trace_path}")

    with tempfile.TemporaryDirectory(prefix="ming-570-spiral-") as tmp:
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

    hist_rej = sum(s["classification"]["hist_rejected"] for s in samples)
    clean_rej = sum(s["classification"]["clean_rejected"] for s in samples)
    hist_only = sum(
        s["classification"]["hist_rejected"] and not s["classification"]["clean_rejected"]
        for s in samples
    )
    clean_only = sum(
        s["classification"]["clean_rejected"] and not s["classification"]["hist_rejected"]
        for s in samples
    )
    both_rej = sum(
        s["classification"]["hist_rejected"] and s["classification"]["clean_rejected"]
        for s in samples
    )
    both_pass = sum(
        (not s["classification"]["hist_rejected"])
        and (not s["classification"]["clean_rejected"])
        for s in samples
    )
    # Spiral: two arms × samples judge calls (do NOT copy 562's 1×samples).
    expected_traces = 2 * args.samples
    if trace_path is not None:
        trace_records = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(trace_records) != expected_traces or any(
            record.get("error") is not None for record in trace_records
        ):
            raise RuntimeError(
                f"expected {expected_traces} successful raw trace records "
                f"(2 arms × {args.samples} samples); got {len(trace_records)}"
            )
    else:
        trace_records = []

    p_value = _two_sided_sign_p(hist_only, clean_only)
    correct_direction = hist_only > clean_only
    passed = correct_direction and p_value < 0.05

    # Minimal diagnosis labels for the evidence artifact (scripts-only).
    if both_rej == args.samples:
        diagnosis = (
            "scenario_ceiling_both_reject: both arms saturated reject — "
            "scenario still too hostile; not yet informative about history sensitivity"
        )
    elif both_pass == args.samples and hist_only == 0:
        diagnosis = (
            "judge_history_insensitive: clean arm can pass (scenario OK) but "
            "hist arm never rejects more — Judge does not differentially weight "
            "promulgation_history 批红强颁 markers (production prompt never names the field). "
            "Hold evidence; do not self-exempt AC④; no production ratchet."
        )
    elif passed:
        diagnosis = (
            "history_sensitive_pass: hist arm rejects more often with p<0.05"
        )
    elif correct_direction and p_value >= 0.05:
        diagnosis = (
            "direction_correct_underpowered: hist_only>clean_only but p≥0.05; "
            "need more samples or stronger history salience (still no production ratchet)"
        )
    elif clean_only > hist_only:
        diagnosis = (
            "wrong_direction: clean rejects more than hist — unexpected; inspect traces"
        )
    else:
        diagnosis = (
            f"inconclusive: hist_only={hist_only} clean_only={clean_only} "
            f"both_rej={both_rej} both_pass={both_pass} p={p_value}"
        )

    artifact = {
        "gate": "issue-570-midzhi-spiral-live-production-judge-comparison",
        "method": {
            "design": (
                "paired independent samples on isolated DBs; sole intervention is "
                "promulgation_history force_promulgated markers 3 vs 0; "
                "opaque target IDs and arm run-order counterbalanced; "
                "single administrative midzhi test decree per arm "
                f"({TEST_MIDZHI_TEXT!r}); board agenda neutral to the decree "
                f"({BOARD_DONGLIN_AGENDA!r}); 皇威=55"
            ),
            "test": "exact two-sided paired sign test (exact McNemar on discordant pairs)",
            "alpha": 0.05,
            "samples": args.samples,
            "config": gate_evidence_config(args, cfg),
            "oos_boundary": (
                "Acceptance evidence only. No production midzhi threshold, "
                "counter gate, or ratchet may be added (#556 OOS 中旨闸量化)."
            ),
            "trace_contract": (
                f"raw_cli_trace length == 2×samples ({expected_traces})"
            ),
            "prior_red_diagnosis": (
                "r0 used 田亩清册 + 反对清丈 agenda → both arms 12/12 reject "
                "(scenario ceiling). r1 recalibrates to #561 admin midzhi + neutral agenda."
            ),
        },
        "summary": {
            "hist3_rejections": hist_rej,
            "hist0_rejections": clean_rej,
            "hist_only_discordant": hist_only,
            "clean_only_discordant": clean_only,
            "both_reject": both_rej,
            "both_promulgate": both_pass,
            "p_value_two_sided": p_value,
            "hist3_rejected_more_often": correct_direction,
            "statistically_distinct_at_0_05": p_value < 0.05,
            "passed": passed,
            "diagnosis": diagnosis,
            "trace_records": len(trace_records),
            "expected_trace_records": expected_traces,
        },
        "limitations": [
            "One configured model/provider and one matched midzhi admin scenario; "
            "acceptance evidence, not population-wide calibration.",
            "History is injected as durable decision rows (批红强颁 markers), not via "
            "a production counter; if the Judge ignores history the gate fails honestly.",
            "Production promulgation Judge instructions do not name promulgation_history; "
            "a clean-pass + hist-insensitive result is engine-side evidence to hold, "
            "not a license to add production ratchet or self-exempt AC④ (P-4/P-7).",
            "Repeated live-model calls may drift across provider/model revisions; "
            "embedded raw trace makes this run auditable.",
            "Pairs share the same production Judge instruction and game snapshot shape; "
            "inference is conditional on that controlled snapshot.",
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
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
