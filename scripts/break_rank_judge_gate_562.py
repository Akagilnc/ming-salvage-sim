"""Live #562 paired comparison through the production promulgation Judge seam.

Not an ordinary CI test: it requires an explicitly selected live CLI provider.

  MING_SIM_TRACE_PATH=/tmp/issue-562-trace.jsonl \
    ../Ming_LLM/.venv/bin/python scripts/break_rank_judge_gate_562.py \
      --runner codex --model gpt-5.6-sol --samples 12 \
      --output docs/evidence/issue-562-break-rank-judge.json
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
from ming_sim.issues import bind_content as bind_issue_content
from ming_sim.models import Character, LLMConfig


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


def _two_sided_sign_p(break_only: int, ordinary_only: int) -> float:
    """Exact paired sign/McNemar test, conditioning on discordant pairs."""
    n = break_only + ordinary_only
    if not n:
        return 1.0
    k = min(break_only, ordinary_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


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


def _run_sample(index: int, root: str, content: GameContent, cfg: LLMConfig) -> dict:
    """Run one independent persisted-history pair in its own databases."""
    sample_dir = Path(root) / str(index)
    sample_dir.mkdir()
    db = GameDB(str(sample_dir / "game.db"), content)
    try:
        db.seed_static_data()
        state = db.load_state()
        # Different real histories produce the intervention: 编修→巡抚 is a
        # four-band jump; 布政使→巡抚 is same-band. Neither condition is fabricated.
        break_name = f"候补官员-{index}-甲"
        ordinary_name = f"候补官员-{index}-乙"
        db.add_character(state, _character(break_name, "翰林院编修", "翰林院"))
        db.add_character(state, _character(ordinary_name, "陕西布政使", "地方"))
        names = [break_name, ordinary_name]
        if index % 2:
            names.reverse()
        ids = []
        for slot, name in zip(("a", "b"), names):
            ids.append(db.create_decree_dossier(
                state, action_type="appointment",
                decree_text=f"任命候补官员为陕西巡抚(比较样本{index + 1})",
                target_kind="character", target_id=f"gate-562-{index}-{slot}",
                payload={"name": name, "office": "陕西巡抚"},
            ))
        rows = [db.get_decree_dossier(dossier_id) for dossier_id in ids]
        persisted = {
            int(row["id"]): json.loads(str(row["payload_json"]))["break_rank"]
            for row in rows
        }
        break_id = next(i for i, marker in persisted.items() if marker["is_break_rank"])
        ordinary_id = next(i for i, marker in persisted.items() if not marker["is_break_rank"])
        context = build_promulgation_judge_context(db, state, rows)
        if index % 4 in (1, 2):
            context["dossiers"].reverse()
            rows.reverse()
        agno = SqliteDb(db_file=str(sample_dir / "agno.db"))
        raw_typed = llm_promulgation_verdicts(
            rows, state, db=db, agno_db=agno, llm_config=cfg,
            prepared_context=context,
        )
        verdicts = validate_promulgation_verdicts(
            raw_typed, rows, db, prepared_context=context,
        )
        by_id = {int(verdict["dossier_id"]): verdict for verdict in verdicts}
        br = by_id[break_id]["decision"] == "rejected"
        ordinary = by_id[ordinary_id]["decision"] == "rejected"
        return {
            "sample": index + 1, "input": context, "typed_verdicts": verdicts,
            "classification": {
                "break_rank_rejected": br, "ordinary_rejected": ordinary,
            },
        }
    finally:
        db.close()


def main() -> int:
    args = _args()
    trace_setting = os.environ.get("MING_SIM_TRACE_PATH", "").strip()
    if not trace_setting or os.environ.get("MING_SIM_TRACE", "1").lower() in {"0", "false", "no"}:
        raise RuntimeError("set MING_SIM_TRACE_PATH to a fresh path with CLI tracing enabled")
    trace_path = Path(trace_setting).resolve()
    if trace_path.exists():
        raise RuntimeError(f"CLI trace path must be fresh: {trace_path}")

    content = GameContent.load()
    bind_content(content)
    bind_issue_content(content)
    bind_agent_content(content)
    cfg = _config(args)
    with tempfile.TemporaryDirectory(prefix="ming-562-gate-") as tmp:
        with ThreadPoolExecutor(max_workers=min(4, args.samples)) as executor:
            futures = [executor.submit(_run_sample, i, tmp, content, cfg) for i in range(args.samples)]
            samples = sorted((future.result() for future in as_completed(futures)), key=lambda row: row["sample"])

    break_rejected = sum(s["classification"]["break_rank_rejected"] for s in samples)
    ordinary_rejected = sum(s["classification"]["ordinary_rejected"] for s in samples)
    break_only = sum(s["classification"]["break_rank_rejected"] and not s["classification"]["ordinary_rejected"] for s in samples)
    ordinary_only = sum(s["classification"]["ordinary_rejected"] and not s["classification"]["break_rank_rejected"] for s in samples)
    trace_records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line]
    if len(trace_records) != args.samples or any(record.get("error") is not None for record in trace_records):
        raise RuntimeError(f"expected {args.samples} successful raw trace records; got {len(trace_records)}")
    p_value = _two_sided_sign_p(break_only, ordinary_only)
    correct_direction = break_only > ordinary_only
    artifact = {
        "gate": "issue-562-break-rank-live-production-judge-comparison",
        "method": {
            "design": "paired independent samples; persisted different office histories are the only rank-condition intervention; opaque target IDs and presentation order are counterbalanced",
            "test": "exact two-sided paired sign test (exact McNemar on discordant pairs)",
            "alpha": 0.05, "samples": args.samples,
            "config": {"channel": "cli", "runner": args.runner, "model": args.model,
                       "reasoning_strength": cfg.reasoning_strength, "max_tokens": cfg.max_tokens},
        },
        "summary": {
            "break_rank_rejections": break_rejected,
            "ordinary_rejections": ordinary_rejected,
            "break_only_discordant": break_only,
            "ordinary_only_discordant": ordinary_only,
            "p_value_two_sided": p_value,
            "break_rank_rejected_more_often": correct_direction,
            "statistically_distinct_at_0_05": p_value < 0.05,
        },
        "limitations": [
            "One configured model/provider and one matched appointment scenario; this is acceptance evidence, not population-wide calibration.",
            "Repeated live-model calls may drift across provider/model revisions; the embedded raw trace makes this run auditable.",
            "Pairs share the same production Judge instruction and game snapshot; inference is conditional on that controlled snapshot.",
        ],
        "samples": samples,
        "raw_cli_trace": trace_records,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": artifact["summary"]}, ensure_ascii=False, indent=2))
    return 0 if p_value < 0.05 and correct_direction else 1


if __name__ == "__main__":
    raise SystemExit(main())
