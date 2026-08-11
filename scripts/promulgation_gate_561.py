"""Issue #561 real-model promulgation gate.

Runs the production judge and simulator agents with an actual CLI configuration.  It
writes raw inputs/outputs plus five scenario checks; no provider is replaced or
monkeypatched.

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

from ming_sim.agents import bind_content as bind_agent_content, create_season_simulator_agent
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.decree import (
    build_promulgation_judge_context,
    llm_promulgation_verdicts,
    validate_promulgation_verdicts,
)
from ming_sim.issues import bind_content as bind_issue_content
from ming_sim.models import LLMConfig
from ming_sim.simulation import build_simulator_payload, simulate_season_with_payload


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

        # Make the opening coalition explicitly hostile.  These are real board
        # facts consumed by the production context builder, not prompt-only labels.
        db.conn.execute("UPDATE factions SET leverage=95, agenda='反对清丈，维护田赋旧例' WHERE name='东林'")
        db.conn.commit()
        hostile = _dossier(db, state, "不经部议，清丈天下田亩并追夺士绅隐田")
        ordinary = _dossier(db, state, "循户部成例补发边军一月欠饷")
        admin_midzhi = _dossier(db, state, "中旨命内廷整理既有文册，不动外廷钱权", mode="中旨")
        vital_midzhi = _dossier(db, state, "中旨绕开户部，强夺太仓全部钱粮交内廷支配", mode="中旨")
        dossiers = db.list_decree_dossiers(status="proposed")
        first_context = build_promulgation_judge_context(db, state, dossiers)
        first_raw = llm_promulgation_verdicts(
            dossiers, state, db=db, agno_db=agno, llm_config=cfg,
            prepared_context=first_context,
        )
        first = validate_promulgation_verdicts(
            first_raw, dossiers, db, prepared_context=first_context,
        )
        by_id = {row["dossier_id"]: row for row in first}

        # The rejected land decree is held.  Then change actual leverage, agenda,
        # imperial authority, and event board before asking the same production judge.
        db.conn.execute("UPDATE factions SET leverage=5, agenda='支持清丈以均平田赋' WHERE name='东林'")
        db.conn.execute(
            "UPDATE decree_dossiers SET decree_text=? WHERE id=?",
            ("依户部会同都察院章程清丈天下田亩，先核官田，不得擅追民产", hostile),
        )
        state.metrics["皇威"] = 100
        db.save_state(state)
        db.conn.commit()
        reconsidered = next(
            row for row in db.list_decree_dossiers(status="proposed") if row["id"] == hostile
        )
        second_context = build_promulgation_judge_context(db, state, [reconsidered])
        second_raw = llm_promulgation_verdicts(
            [reconsidered], state, db=db, agno_db=agno, llm_config=cfg,
            prepared_context=second_context,
        )
        second = validate_promulgation_verdicts(
            second_raw, [reconsidered], db, prepared_context=second_context,
        )

        executable = [row for row in dossiers if by_id[row["id"]]["decision"] == "promulgated"]
        decree_text = "\n".join(row["decree_text"] for row in executable)
        payload = build_simulator_payload(
            state, db, decree_text, "", decree_dossiers=executable,
            deaths_this_turn=[], debuts_this_turn=[], relevant_memories=[], secret_orders={},
        )
        payload["dossier_verdicts"] = first
        payload["promulgation_instruction"] = (
            "颁布判决是硬约束：decision=rejected 的案卷本月未颁、不得写成已办成或已生效；"
            "只能叙述其被打回并等待批红。decision=promulgated 的案卷才可进入本月办理。"
        )
        simulator = create_season_simulator_agent(cfg, agno, state=state, db=db, simulator_payload=payload)
        narrative, sent_payload = simulate_season_with_payload(
            simulator, state, db, decree_text, "", deaths_this_turn=[], debuts_this_turn=[],
            relevant_memories=[], secret_orders={}, simulator_payload=payload,
        )
        rejected_texts = [row["decree_text"] for row in dossiers if by_id[row["id"]]["decision"] == "rejected"]
        forbidden = ("清丈已经完成", "清丈已完成", "太仓已交内廷", "旨意已生效")
        checks = {
            "hostile_land_rejected": by_id[hostile]["decision"] == "rejected",
            "ordinary_pay_promulgated": by_id[ordinary]["decision"] == "promulgated",
            "held_land_changes_after_board_change": second[0]["decision"] != by_id[hostile]["decision"],
            "administrative_midzhi_promulgated_with_stigma": (
                by_id[admin_midzhi]["decision"] == "promulgated" and bool(by_id[admin_midzhi].get("affected_parties"))
            ),
            "vital_midzhi_rejected_with_exclusive_marker": (
                by_id[vital_midzhi]["decision"] == "rejected"
                and by_id[vital_midzhi].get("midzhi_unpromulgatable") is True
            ),
            "simulator_excludes_rejected_dossiers": not ({hostile, vital_midzhi} & {row["id"] for row in sent_payload["decree_dossiers"]}),
            "simulator_does_not_claim_rejected_effective": not any(token in narrative for token in forbidden),
        }
        artifact = {
            "gate": "issue-561-real-judge-and-simulator", "config": {
                "channel": "cli", "runner": args.runner, "model": args.model,
                "reasoning_strength": cfg.reasoning_strength,
            },
            "scenarios": {"ids": {"hostile_land": hostile, "ordinary_pay": ordinary,
                "administrative_midzhi": admin_midzhi, "vital_midzhi": vital_midzhi},
                "hold_action": "hostile_land held before real board mutation",
                "board_mutation": {"东林.leverage": [95, 5], "东林.agenda": ["反对清丈，维护田赋旧例", "支持清丈以均平田赋"], "皇威": [first_context["imperial_authority_band"], second_context["imperial_authority_band"]], "留中修旨": ["不经部议，追夺隐田", "依户部会同都察院章程，先核官田，不擅追民产"]},
            },
            "judge_first": {"input": first_context, "output": first},
            "judge_after_hold_and_board_change": {"input": second_context, "output": second},
            "simulator": {"input": sent_payload, "output": narrative, "rejected_decree_texts": rejected_texts},
            "checks": checks,
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        db.close()
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"output": args.output, "checks": checks}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
