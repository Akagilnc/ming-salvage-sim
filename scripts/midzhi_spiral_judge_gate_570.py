"""Live #570 midzhi-spiral paired comparison (Court pin P-4).

Same board; sole intervention = prior force_promulgated history 3 vs 0.
Target IDs / presentation order counterbalanced. Exact two-sided paired sign
test α=0.05. samples default 12, minimum 6.

This is acceptance evidence only — MUST NOT add production midzhi
threshold / counter / ratchet (PRD #556 OOS).

  MING_SIM_TRACE_PATH=/tmp/issue-570-spiral-trace.jsonl \
    python scripts/midzhi_spiral_judge_gate_570.py \
      --runner codex --model gpt-5.6-sol --samples 12 \
      --output docs/evidence/issue-570-midzhi-spiral.json
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
from ming_sim.cli_backend import cli_backend_parallel_safe
from ming_sim.issues import bind_content as bind_issue_content
from ming_sim.models import LLMConfig

# Borderline administrative midzhi — not a vital 命门 reverse-scale item.
# Vital land-survey midzhi rejects on both arms → zero discordant pairs, dead gate.
# Spiral signal needs a decree that can pass without force-history and is more
# rejectable once 批红强颁 markers accumulate (Court pin P-4).
TEST_MIDZHI_TEXT = (
    "中旨绕开内阁票拟，径令各省布政司旬日造报田亩清册并送内廷备览，"
    "仍不追夺隐田、不动正项钱粮"
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", choices=("codex", "claude"), required=True)
    parser.add_argument("--model", required=True)
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


def _config(args: argparse.Namespace) -> LLMConfig:
    return LLMConfig(
        api_key="", base_url="", model=args.model, channel="cli",
        cli_runner=args.runner, cli_model=args.model, cli_timeout_seconds=600,
        max_tokens=6000, reasoning_strength="high",
    )


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
        state.metrics["皇威"] = 40
        db.conn.execute(
            "UPDATE factions SET leverage=90, agenda=? WHERE name='东林'",
            ("反对清丈，维护田赋旧例",),
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
    trace_records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(record.get("error") is not None for record in trace_records):
        raise RuntimeError("CLI trace contains failed records")

    p_value = _two_sided_sign_p(hist_only, clean_only)
    correct_direction = hist_only > clean_only
    passed = correct_direction and p_value < 0.05

    artifact = {
        "gate": "issue-570-midzhi-spiral-live-production-judge-comparison",
        "method": {
            "design": (
                "paired independent samples on isolated DBs; sole intervention is "
                "promulgation_history force_promulgated markers 3 vs 0; "
                "opaque target IDs and arm run-order counterbalanced; "
                "single borderline administrative midzhi test decree per arm"
            ),
            "test": "exact two-sided paired sign test (exact McNemar on discordant pairs)",
            "alpha": 0.05,
            "samples": args.samples,
            "config": {
                "channel": "cli", "runner": args.runner, "model": args.model,
                "reasoning_strength": cfg.reasoning_strength,
                "max_tokens": cfg.max_tokens,
            },
            "oos_boundary": (
                "Acceptance evidence only. No production midzhi threshold, "
                "counter gate, or ratchet may be added (#556 OOS 中旨闸量化)."
            ),
        },
        "summary": {
            "hist3_rejections": hist_rej,
            "hist0_rejections": clean_rej,
            "hist_only_discordant": hist_only,
            "clean_only_discordant": clean_only,
            "p_value_two_sided": p_value,
            "hist3_rejected_more_often": correct_direction,
            "statistically_distinct_at_0_05": p_value < 0.05,
            "passed": passed,
        },
        "limitations": [
            "One configured model/provider and one matched midzhi hostile scenario; "
            "acceptance evidence, not population-wide calibration.",
            "History is injected as durable decision rows (批红强颁 markers), not via "
            "a production counter; if the Judge ignores history the gate fails honestly.",
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
