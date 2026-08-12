"""Deterministic #562 judge-input evaluator (does not call or impersonate an LLM).

It evaluates an exported production ``build_promulgation_judge_context`` payload and
proves only that the judge can distinguish a marked appointment from an ordinary one.
It deliberately makes no claim about a model's eventual verdict.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def evaluate(context: dict) -> dict:
    appointments = [
        row for row in context.get("dossiers", [])
        if row.get("action_type") == "appointment" and isinstance(row.get("break_rank"), dict)
    ]
    marked = [row for row in appointments if row["break_rank"].get("is_break_rank") is True]
    ordinary = [row for row in appointments if row["break_rank"].get("is_break_rank") is False]
    checks = {
        "marked_appointment_reaches_judge": len(marked) == 1,
        "ordinary_appointment_reaches_judge": len(ordinary) == 1,
        "pair_has_distinct_break_rank_signal": len(marked) == 1 and len(ordinary) == 1,
    }
    return {
        "gate": "issue-562-deterministic-judge-input-discrimination",
        "scope": "judge input only; no LLM verdict or model-quality claim",
        "ids": {
            "marked": marked[0].get("id") if len(marked) == 1 else None,
            "ordinary": ordinary[0].get("id") if len(ordinary) == 1 else None,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(Path(args.input).read_text(encoding="utf-8")))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
