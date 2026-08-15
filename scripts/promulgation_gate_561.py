"""Issue #561 real-model promulgation gate.

Runs the production ``resolve_directives`` judge/simulator assembly, the production
rescript hold transition, and the next-month production reconsideration rail.
No model provider or production collaborator is replaced.

  MING_SIM_TRACE_PATH=/tmp/issue-561-trace.jsonl \
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
    llm_promulgation_verdicts,
    resolve_decisions_phase2,
    resolve_directives,
    validate_promulgation_verdicts,
)
from ming_sim.issues import (
    apply_score_extraction,
    bind_content as bind_issue_content,
)
from ming_sim.models import LLMConfig


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", choices=("codex", "claude"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _dossier(db: GameDB, state, text: str, *, mode: str = "ordinary") -> int:
    return db.create_decree_dossier(
        state, action_type="policy", decree_text=text, target_kind="issue",
        target_id=f"gate-561-{state.turn}-{text[:6]}", payload={"mode": mode},
    )


def _cfg(args: argparse.Namespace) -> LLMConfig:
    return LLMConfig(
        api_key="", base_url="", model=args.model, channel="cli",
        cli_runner=args.runner, cli_model=args.model, cli_timeout_seconds=600,
        max_tokens=6000, reasoning_strength="high",
    )


def _choose_rescripts(
    db: GameDB, turn: int, hostile: int, vital: int, appointment: int,
) -> list[dict]:
    """Persist choices exactly as the normal session boundary does, then phase2 owns them."""
    chosen = []
    for decision in db.list_pending_decisions(turn):
        options = decision["options"]
        if decision["event_id"] == f"dossier:{hostile}":
            choice = next(row for row in options if row.get("dossier_decision") == "hold")
        elif decision["event_id"] in {f"dossier:{vital}", f"dossier:{appointment}"}:
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


def _trace_records(path: Path, start: int) -> tuple[list[dict], int]:
    """Read complete records appended by the existing real-CLI trace seam."""
    if not path.exists():
        raise RuntimeError(f"CLI trace was not created: {path}")
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(start)
        chunk = handle.read()
        end = handle.tell()
    try:
        records = [json.loads(line) for line in chunk.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise RuntimeError("CLI trace contains an incomplete or invalid record") from exc
    return records, end


def _judge_payload_from_prompt(prompt: object) -> dict:
    """Decode the user JSON exactly as serialized into the real CLI prompt."""
    if not isinstance(prompt, str):
        raise RuntimeError("CLI judge trace has no prompt")
    marker = "【皇帝/输入】\n"
    positions = [index for index in range(len(prompt)) if prompt.startswith(marker, index)]
    if len(positions) != 1:
        raise RuntimeError(f"CLI judge prompt must have one user payload; got {len(positions)}")
    start = positions[0] + len(marker)
    try:
        payload, consumed = json.JSONDecoder().raw_decode(prompt[start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError("CLI judge prompt user payload is not complete JSON") from exc
    remainder = prompt[start + consumed:]
    if not remainder.startswith("\n\n【") or not isinstance(payload, dict):
        raise RuntimeError("CLI judge prompt user payload boundary is invalid")
    return payload


def _captured_judge_payload(records: list[dict], expected: dict) -> tuple[dict, dict]:
    """Select exactly one successful real judge call by its complete input payload."""
    matches = []
    for record in records:
        try:
            payload = _judge_payload_from_prompt(record.get("prompt"))
        except RuntimeError:
            continue
        if payload == expected:
            matches.append((payload, record))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one matching real CLI judge call; got {len(matches)}")
    payload, record = matches[0]
    if record.get("error") is not None or record.get("attempts") != 1:
        raise RuntimeError("real CLI judge call must succeed in exactly one attempt")
    if record.get("prompt_chars") != len(record.get("prompt", "")):
        raise RuntimeError("real CLI judge prompt was truncated in trace")
    provenance = {
        "source": "MING_SIM_TRACE_PATH real CliChat.invoke prompt",
        "seq": record.get("seq"), "attempts": record.get("attempts"),
        "error": record.get("error"), "matches_builder_expectation": True,
    }
    return payload, provenance


def _run_judge_batch(db, state, agno, cfg, dossiers: list[dict]) -> tuple[dict, list[dict]]:
    """Call and validate the production batch judge without replacing a collaborator."""
    context = build_promulgation_judge_context(db, state, dossiers)
    verdicts = llm_promulgation_verdicts(
        dossiers, state, db=db, agno_db=agno, llm_config=cfg,
        prepared_context=context,
    )
    return context, validate_promulgation_verdicts(
        verdicts, dossiers, db, prepared_context=context,
    )


def _judge_context_for_dossier(db: GameDB, state, dossier_id: int) -> dict:
    """Build evidence from the same fresh dossier row production will consume."""
    return build_promulgation_judge_context(
        db, state, [db.get_decree_dossier(dossier_id)],
    )


def _prepare_reconsideration_facts(
    db: GameDB, state, dossier_id: int, first_context: dict,
) -> dict:
    """Remove the first named blocker while retaining the production-derived bench."""
    first_names = {str(row["name"]) for row in first_context["gatekeepers"]}
    named_opponent = "许誉卿"
    if named_opponent not in first_names:
        raise RuntimeError("reconsideration requires 许誉卿 on the first gatekeeping bench")
    db.conn.execute(
        "UPDATE characters SET status='dismissed' WHERE name=?",
        (named_opponent,),
    )
    db.conn.execute(
        "UPDATE factions SET leverage=5,agenda='失去许誉卿封驳支点，转入复议' WHERE name='东林'"
    )
    held = db.get_decree_dossier(dossier_id)
    # #611: grant from a separate promulgated dossier through the sole
    # authority_changes owner.  The held/rejected reconsideration dossier is
    # only the eventual consumer and can never authorize its own effects.
    holder = next(
        str(row["name"]) for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
            "ORDER BY name"
        )
    )
    target_kind = str(held.get("target_kind") or "").strip() or "issue"
    target_id = str(held.get("target_id") or "").strip() or "清丈田亩"
    scope = f"{target_kind}:{target_id}"
    db.conn.execute(
        "UPDATE decree_dossiers SET executor_kind='character', executor_id=?, "
        "target_kind=?, target_id=? WHERE id=?",
        (holder, target_kind, target_id, dossier_id),
    )
    grant_dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="复议前另案授以便宜行事之权",
        target_kind=target_kind,
        target_id=target_id,
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(grant_dossier_id, "promulgated")
    grant = apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
            "scope": scope, "dossier_id": grant_dossier_id,
        }],
    })["authority_changes"][0]
    if grant.get("rejected") is True:
        raise RuntimeError(f"reconsideration authority grant rejected: {grant}")
    state.metrics["皇威"] = 100
    db.save_state(state)
    db.conn.commit()

    second_context = _judge_context_for_dossier(db, state, dossier_id)
    second_names = {str(row["name"]) for row in second_context["gatekeepers"]}
    if not second_names:
        raise RuntimeError("reconsideration must retain a real gatekeeping bench")
    if named_opponent in second_names or not (second_names & (first_names - {named_opponent})):
        raise RuntimeError("reconsideration must remove only the named blocker from the bench")
    return second_context


def _select_second_verdict(
    awaiting: bool, hostile: int, pending: list[dict], history: list[dict],
) -> dict:
    """Read the second judgment from the production owner for its current phase."""
    source = pending if awaiting else history
    matches = [row for row in source if int(row.get("dossier_id", -1)) == hostile]
    if len(matches) != 1:
        raise RuntimeError(
            f"second judgment must contain hostile dossier exactly once; got {len(matches)}"
        )
    verdict = matches[0]
    if verdict.get("decision") not in {"promulgated", "rejected"}:
        raise RuntimeError("second judgment has an empty or illegal decision")
    return verdict


def main() -> int:
    args = _args()
    content = GameContent.load()
    bind_content(content)
    bind_issue_content(content)
    bind_agent_content(content)
    trace_setting = os.environ.get("MING_SIM_TRACE_PATH", "").strip()
    if not trace_setting or os.environ.get("MING_SIM_TRACE", "1").strip().lower() in {"0", "false", "no"}:
        raise RuntimeError("set MING_SIM_TRACE_PATH to a fresh path with CLI tracing enabled")
    trace_path = Path(trace_setting).resolve()
    if trace_path.exists():
        raise RuntimeError(f"CLI trace path must be fresh: {trace_path}")
    trace_offset = 0

    with tempfile.TemporaryDirectory(prefix="ming-561-gate-") as tmp:
        db = GameDB(os.path.join(tmp, "gate.db"), content)
        db.seed_static_data()
        state = db.load_state()
        agno = SqliteDb(db_file=os.path.join(tmp, "agno.db"))
        cfg = _cfg(args)

        db.conn.execute(
            "UPDATE factions SET leverage=95, agenda='反对清丈，维护田赋旧例' WHERE name='东林'"
        )
        state.metrics["皇威"] = 0
        db.save_state(state)
        db.conn.commit()
        hostile_text = "许誉卿执掌封驳时，不经部议清丈天下田亩并追夺东林士绅隐田"
        hostile = _dossier(db, state, hostile_text)
        ordinary = _dossier(db, state, "循户部成例补发边军一月欠饷")
        authority_edge = _dossier(db, state, "越一级特授边将虚衔，仍循兵部具题复核")
        appointment = db.create_decree_dossier(
            state, action_type="appointment", decree_text="调任许誉卿出京清查东林隐田",
            target_kind="character", target_id="许誉卿", payload={"任别": "真除"},
        )
        admin_midzhi = _dossier(
            db, state, "中旨命内廷整理既有文册，不动外廷钱权", mode="midzhi",
        )
        vital_midzhi = _dossier(
            db, state, "中旨绕开户部，强夺太仓全部钱粮交内廷支配", mode="midzhi",
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
        trace_records, trace_offset = _trace_records(trace_path, trace_offset)
        first_actual_input, first_provenance = _captured_judge_payload(
            trace_records, first_context,
        )
        first_turn = state.turn
        first_ctx = db.get_resolve_context(first_turn) or {}
        first_verdicts = db.get_pending_promulgation_verdicts(first_turn)
        by_id = {int(row["dossier_id"]): row for row in first_verdicts}

        # A leader-only seed mutation is deliberately invisible to the production
        # payload; high imperial authority is the sole judge-visible change.
        db.conn.execute(
            "UPDATE characters SET status='active' WHERE name='钱谦益'"
        )
        state.metrics["皇威"] = 100
        db.save_state(state)
        db.conn.commit()
        high_dossiers = db.list_decree_dossiers(status="proposed")
        high_context, high_verdicts = _run_judge_batch(db, state, agno, cfg, high_dossiers)
        trace_records, trace_offset = _trace_records(trace_path, trace_offset)
        high_actual_input, high_provenance = _captured_judge_payload(
            trace_records, high_context,
        )
        high_by_id = {int(row["dossier_id"]): row for row in high_verdicts}
        choices = _choose_rescripts(
            db, first_turn, hostile, vital_midzhi, appointment,
        )

        # This is the production hold owner: phase2 reads the persisted choice,
        # applies the verdict batch and rescript action atomically, then advances.
        resolve_decisions_phase2(
            state, db, agno, cfg, content=content,
        )
        held = db.get_decree_dossier(hostile)
        held_history = db.list_decree_dossier_decisions(hostile)
        text_after_hold = str(held["decree_text"])

        # Change only the first named blocker and its faction posture.  The
        # other production-derived gatekeepers remain a real reconsideration bench.
        second_context = _prepare_reconsideration_facts(
            db, state, hostile, first_context,
        )
        second_turn = state.turn
        second_result = resolve_directives(
            state, db, agno, cfg, [], "留中案下月重判", content=content,
        )
        trace_records, trace_offset = _trace_records(trace_path, trace_offset)
        second_actual_input, second_provenance = _captured_judge_payload(
            trace_records, second_context,
        )
        second_pending = db.get_pending_promulgation_verdicts(second_turn)
        second_history = [
            row for row in db.list_decree_dossier_decisions(hostile)
            if int(row["turn"]) == second_turn and not row.get("rescript_action")
        ]
        second_verdict = _select_second_verdict(
            second_result.awaiting, hostile, second_pending, second_history,
        )
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
        all_verdicts = first_verdicts + high_verdicts + [second_verdict]
        all_payloads = [first_actual_input, high_actual_input, second_actual_input]
        checks = {
            "hostile_land_rejected": by_id[hostile]["decision"] == "rejected",
            "ordinary_pay_promulgated": by_id[ordinary]["decision"] == "promulgated",
            "three_trigger_faces_reject_at_low_authority": all(
                by_id[dossier_id]["decision"] == "rejected"
                for dossier_id in (authority_edge, hostile, appointment)
            ),
            "authority_edge_passes_only_at_high_authority": (
                by_id[authority_edge]["decision"] == "rejected"
                and high_by_id[authority_edge]["decision"] == "promulgated"
            ),
            "vital_exception_still_rejects_at_high_authority": (
                high_by_id[vital_midzhi]["decision"] == "rejected"
            ),
            "leader_change_does_not_remove_named_gatekeeper_block": (
                high_by_id[hostile]["decision"] == "rejected"
                and {row["name"] for row in high_context["gatekeepers"]}
                == {row["name"] for row in first_context["gatekeepers"]}
            ),
            "gatekeeper_appointment_is_judged_and_rejected": (
                by_id[appointment]["decision"] == "rejected"
                and appointment in {int(row["dossier_id"]) for row in first_verdicts}
            ),
            "named_gatekeeper_change_unblocks_same_decree": (
                second_verdict["decision"] == "promulgated"
            ),
            "decisions_are_binary_and_batches_cover_inputs": (
                {row["decision"] for row in all_verdicts}
                <= {"promulgated", "rejected"}
                and {int(row["dossier_id"]) for row in first_verdicts}
                == {int(row["id"]) for row in first_context["dossiers"]}
                and {int(row["dossier_id"]) for row in high_verdicts}
                == {int(row["id"]) for row in high_context["dossiers"]}
            ),
            "real_judge_payloads_exclude_satisfaction": all(
                "satisfaction" not in json.dumps(payload, ensure_ascii=False)
                and "满意" not in json.dumps(payload, ensure_ascii=False)
                for payload in all_payloads
            ),
            "held_by_production_rescript": (
                int(held["held_turn"]) == first_turn
                and any(row.get("rescript_action") == "hold" for row in held_history)
            ),
            "held_decree_text_unchanged": text_after_hold == hostile_text,
            "held_land_changes_after_board_change": (
                second_verdict["decision"] == "promulgated"
                and second_verdict["decision"] != by_id[hostile]["decision"]
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
                        "authority_edge": authority_edge, "appointment": appointment,
                        "administrative_midzhi": admin_midzhi,
                        "vital_midzhi": vital_midzhi},
                "rescript_choices": choices,
                "hold_state": {"held_turn": held["held_turn"], "history": held_history},
                "reconsideration_facts": {
                    "factions": [first_context["factions"], second_context["factions"]],
                    "皇威": [first_context["imperial_authority_band"],
                             second_context["imperial_authority_band"]],
                    "gatekeepers": [first_context["gatekeepers"],
                                    second_context["gatekeepers"]],
                    "authorization_ids": [
                        first_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"],
                        second_context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"],
                    ],
                    "decree_text": [
                        first_context["dossiers"][0]["decree_text"],
                        second_context["dossiers"][0]["decree_text"],
                    ],
                },
            },
            "judge_first": {
                "input": first_actual_input, "input_provenance": first_provenance,
                "output": first_verdicts,
            },
            "judge_after_authority_and_leader_change": {
                "input": high_actual_input, "input_provenance": high_provenance,
                "output": high_verdicts,
            },
            "judge_after_hold_and_board_change": {
                "input": second_actual_input, "input_provenance": second_provenance,
                "output": second_verdict,
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
