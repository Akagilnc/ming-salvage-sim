"""Issue #561 real-model promulgation gate.

Runs the production ``resolve_directives`` judge/simulator assembly, the production
rescript hold transition, and the next-month production reconsideration rail.
No model provider or production collaborator is replaced.

  ../Ming_LLM/.venv/bin/python scripts/promulgation_gate_561.py \
      --runner codex --model gpt-5.6-sol --output docs/evidence/issue-561-gate.json
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agno.db.sqlite import SqliteDb

from ming_sim.agents import bind_content as bind_agent_content
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.decree import (
    build_promulgation_judge_context,
    resolve_decisions_phase2,
    resolve_directives,
)
from ming_sim.issues import bind_content as bind_issue_content
from ming_sim.models import LLMConfig


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", choices=("codex", "claude"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _dossier(db: GameDB, state, text: str, *, mode: str = "regular") -> int:
    return db.create_decree_dossier(
        state, action_type="policy", decree_text=text, target_kind="issue",
        target_id=f"gate-561-{state.turn}-{text[:6]}", payload={"mode": mode},
    )


def _cfg(args: argparse.Namespace) -> LLMConfig:
    return LLMConfig(
        api_key="", base_url="", model=args.model, channel="cli",
        cli_runner=args.runner, cli_model=args.model, cli_timeout_seconds=600,
        max_tokens=6000, reasoning_strength="medium",
    )


def _choose_rescripts(db: GameDB, turn: int, hostile: int, vital: int) -> list[dict]:
    """Persist choices exactly as the normal session boundary does, then phase2 owns them."""
    chosen = []
    for decision in db.list_pending_decisions(turn):
        options = decision["options"]
        if decision["event_id"] == f"dossier:{hostile}":
            choice = next(row for row in options if row.get("dossier_decision") == "hold")
        elif decision["event_id"] == f"dossier:{vital}":
            choice = next(row for row in options if row.get("dossier_decision") == "withdrawn")
        else:
            choice = options[0]
        db.conn.execute(
            "UPDATE pending_decisions SET choice_json=?,status='chosen' WHERE turn=? AND idx=?",
            (json.dumps(choice, ensure_ascii=False), int(turn), int(decision["idx"])),
        )
        chosen.append({"event_id": decision["event_id"], "choice": choice})
    db.conn.commit()
    return chosen


def main() -> int:
    args = _args()
    content = GameContent.load()
    bind_content(content)
    bind_issue_content(content)
    bind_agent_content(content)
    with tempfile.TemporaryDirectory(prefix="ming-561-gate-") as tmp:
        db = GameDB(os.path.join(tmp, "gate.db"), content)
        db.seed_static_data()
        state = db.load_state()
        agno = SqliteDb(db_file=os.path.join(tmp, "agno.db"))
        cfg = _cfg(args)

        db.conn.execute(
            "UPDATE factions SET leverage=95, agenda='反对清丈，维护田赋旧例' WHERE name='东林'"
        )
        db.conn.commit()
        hostile_text = "不经部议，清丈天下田亩并追夺士绅隐田"
        hostile = _dossier(db, state, hostile_text)
        ordinary = _dossier(db, state, "循户部成例补发边军一月欠饷")
        admin_midzhi = _dossier(
            db, state, "中旨命内廷整理既有文册，不动外廷钱权", mode="中旨",
        )
        vital_midzhi = _dossier(
            db, state, "中旨绕开户部，强夺太仓全部钱粮交内廷支配", mode="中旨",
        )
        first_context = build_promulgation_judge_context(
            db, state, db.list_decree_dossiers(status="proposed"),
        )

        # Production owns judge invocation, validation, dossier filtering,
        # promulgation_instruction injection, simulator creation and invocation.
        first_result = resolve_directives(
            state, db, agno, cfg, [object()], "四旨并下", content=content,
        )
        if not first_result.awaiting:
            raise RuntimeError("real gate expected rejected dossiers to reach rescript")
        first_turn = state.turn
        first_ctx = db.get_resolve_context(first_turn) or {}
        first_verdicts = db.get_pending_promulgation_verdicts(first_turn)
        by_id = {int(row["dossier_id"]): row for row in first_verdicts}
        choices = _choose_rescripts(db, first_turn, hostile, vital_midzhi)

        # This is the production hold owner: phase2 reads the persisted choice,
        # applies the verdict batch and rescript action atomically, then advances.
        resolve_decisions_phase2(
            state, db, agno, cfg, content=content,
        )
        held = db.get_decree_dossier(hostile)
        held_history = db.list_decree_dossier_decisions(hostile)
        text_after_hold = str(held["decree_text"])

        # Change only actual board facts.  The held decree text is immutable here.
        db.conn.execute(
            "UPDATE factions SET leverage=5, agenda='支持清丈以均平田赋' WHERE name='东林'"
        )
        state.metrics["皇威"] = 100
        db.save_state(state)
        db.conn.commit()
        second_context = build_promulgation_judge_context(db, state, [held])
        second_turn = state.turn
        second_result = resolve_directives(
            state, db, agno, cfg, [], "留中案下月重判", content=content,
        )
        second_history = [
            row for row in db.list_decree_dossier_decisions(hostile)
            if int(row["turn"]) == second_turn and not row.get("rescript_action")
        ]
        second_verdict = second_history[-1] if second_history else {}
        second_ctx = db.get_resolve_context(second_turn) or {}
        second_narrative = (
            str(second_ctx.get("narrative") or "")
            if second_result.awaiting else str(second_result.report or "")
        )

        sent_payload = first_ctx.get("simulator_payload") or {}
        sent_ids = {
            int(row["id"]) for row in sent_payload.get("decree_dossiers", [])
            if isinstance(row, dict)
        }
        rejected_texts = [
            row["decree_text"] for row in db.list_decree_dossiers()
            if int(row["id"]) in {hostile, vital_midzhi}
        ]
        first_narrative = str(first_ctx.get("narrative") or "")
        forbidden = ("清丈已经完成", "清丈已完成", "太仓已交内廷", "旨意已生效")
        checks = {
            "hostile_land_rejected": by_id[hostile]["decision"] == "rejected",
            "ordinary_pay_promulgated": by_id[ordinary]["decision"] == "promulgated",
            "held_by_production_rescript": (
                int(held["held_turn"]) == first_turn
                and any(row.get("rescript_action") == "hold" for row in held_history)
            ),
            "held_decree_text_unchanged": text_after_hold == hostile_text,
            "held_land_changes_after_board_change": (
                second_verdict.get("decision") != by_id[hostile]["decision"]
            ),
            "administrative_midzhi_promulgated_with_stigma": (
                by_id[admin_midzhi]["decision"] == "promulgated"
                and bool(by_id[admin_midzhi].get("affected_parties"))
            ),
            "vital_midzhi_rejected_with_exclusive_marker": (
                by_id[vital_midzhi]["decision"] == "rejected"
                and by_id[vital_midzhi].get("midzhi_unpromulgatable") is True
            ),
            "simulator_excludes_rejected_dossiers": not ({hostile, vital_midzhi} & sent_ids),
            "simulator_instruction_from_production": "promulgation_instruction" in sent_payload,
            "simulator_does_not_claim_rejected_effective": not any(
                token in first_narrative for token in forbidden
            ),
        }
        artifact = {
            "gate": "issue-561-production-judge-rescript-and-simulator",
            "config": {"channel": "cli", "runner": args.runner, "model": args.model,
                       "reasoning_strength": cfg.reasoning_strength},
            "scenarios": {
                "ids": {"hostile_land": hostile, "ordinary_pay": ordinary,
                        "administrative_midzhi": admin_midzhi,
                        "vital_midzhi": vital_midzhi},
                "rescript_choices": choices,
                "hold_state": {"held_turn": held["held_turn"], "history": held_history},
                "board_mutation_only": {
                    "东林.leverage": [95, 5],
                    "东林.agenda": ["反对清丈，维护田赋旧例", "支持清丈以均平田赋"],
                    "皇威": [first_context["imperial_authority_band"],
                             second_context["imperial_authority_band"]],
                    "decree_text": [hostile_text, text_after_hold],
                },
            },
            "judge_first": {"input": first_context, "output": first_verdicts},
            "judge_after_hold_and_board_change": {
                "input": second_context, "output": second_verdict,
            },
            "simulator": {
                "assembly": "resolve_directives production simulator_payload",
                "input": sent_payload, "output": first_narrative,
                "rejected_decree_texts": rejected_texts,
                "reconsideration_output": second_narrative,
            },
            "checks": checks,
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        db.close()
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"output": args.output, "checks": checks}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
