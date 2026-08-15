"""Issue #561 real-model promulgation gate.

Runs the production ``resolve_directives`` judge/simulator assembly, the production
rescript hold transition, and the next-month production reconsideration rail.
No model provider or production collaborator is replaced.

Independent authority / person / trigger-face arms share one scene constructor and
the same production ``resolve_directives`` runner on isolated temporary DBs, and
are scheduled concurrently (P5).

  MING_SIM_TRACE_PATH=/tmp/issue-561-trace.jsonl \
    ../Ming_LLM/.venv/bin/python scripts/promulgation_gate_561.py \
      --runner codex --model gpt-5.6-sol --output docs/evidence/issue-561-gate.json
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
from typing import Callable, Optional

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
from ming_sim.issues import (
    apply_score_extraction,
    bind_content as bind_issue_content,
)
from ming_sim.models import LLMConfig

HOSTILE_TEXT = "许誉卿执掌封驳时，不经部议清丈天下田亩并追夺东林士绅隐田"
ORDINARY_TEXT = "循户部成例补发边军一月欠饷"
AUTHORITY_EDGE_TEXT = "越一级特授边将虚衔，仍循兵部具题复核"
APPOINTMENT_TEXT = "调任许誉卿出京清查东林隐田"
ADMIN_MIDZHI_TEXT = "中旨命内廷整理既有文册，不动外廷钱权"
VITAL_MIDZHI_TEXT = "中旨绕开户部，强夺太仓全部钱粮交内廷支配"
# Judge-visible faction posture (leverage+agenda only; never satisfaction).
BASE_DONGLIN_AGENDA = "反对清丈，维护田赋旧例"
# person_leader sole mutation: leader appeased via agenda, not character status.
LEADER_APPEASED_AGENDA = "钱谦益已受安抚，东林首领息争"

# Full low/high authority batch: same planted dossiers, only 皇威 differs.
FULL_KINDS = (
    "hostile", "ordinary", "authority_edge", "appointment",
    "admin_midzhi", "vital_midzhi",
)


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


def _trace_records(path: Path, start: int = 0) -> tuple[list[dict], int]:
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


def _open_scene(root: str, name: str, content: GameContent) -> tuple[GameDB, object, SqliteDb]:
    """One isolated temporary DB pair for a single arm."""
    arm_dir = Path(root) / name
    arm_dir.mkdir(parents=True, exist_ok=True)
    db = GameDB(str(arm_dir / "gate.db"), content)
    db.seed_static_data()
    state = db.load_state()
    agno = SqliteDb(db_file=str(arm_dir / "agno.db"))
    return db, state, agno


def _apply_base_board(db: GameDB, state, *, authority: int) -> None:
    """Shared minimal board. Arms may then change exactly one tested variable."""
    db.conn.execute(
        "UPDATE factions SET leverage=95, agenda=? WHERE name='东林'",
        (BASE_DONGLIN_AGENDA,),
    )
    state.metrics["皇威"] = int(authority)
    db.save_state(state)
    db.conn.commit()


def _plant_dossiers(db: GameDB, state, kinds: tuple[str, ...] | list[str]) -> dict[str, int]:
    """Plant the named dossier kinds; kind set is the only dossier-level difference."""
    ids: dict[str, int] = {}
    for kind in kinds:
        if kind == "hostile":
            ids["hostile"] = _dossier(db, state, HOSTILE_TEXT)
        elif kind == "ordinary":
            ids["ordinary"] = _dossier(db, state, ORDINARY_TEXT)
        elif kind == "authority_edge":
            ids["authority_edge"] = _dossier(db, state, AUTHORITY_EDGE_TEXT)
        elif kind == "appointment":
            ids["appointment"] = db.create_decree_dossier(
                state, action_type="appointment", decree_text=APPOINTMENT_TEXT,
                target_kind="character", target_id="许誉卿", payload={"任别": "真除"},
            )
        elif kind == "admin_midzhi":
            ids["admin_midzhi"] = _dossier(db, state, ADMIN_MIDZHI_TEXT, mode="midzhi")
        elif kind == "vital_midzhi":
            ids["vital_midzhi"] = _dossier(db, state, VITAL_MIDZHI_TEXT, mode="midzhi")
        else:
            raise RuntimeError(f"unknown dossier kind: {kind}")
    return ids


def _mutate_leader_only(db: GameDB, state) -> None:
    """按人对照·首领臂：只改东林 agenda 表达首领已安抚；不改 leverage/把关人/皇威。"""
    del state  # board authority already fixed by the arm
    db.conn.execute(
        "UPDATE factions SET agenda=? WHERE name='东林'",
        (LEADER_APPEASED_AGENDA,),
    )
    db.conn.commit()


def _mutate_gatekeeper_only(db: GameDB, state) -> None:
    """按人对照·把关人臂：只撤许誉卿，不改皇威/首领/派系 leverage/授权。"""
    del state
    db.conn.execute("UPDATE characters SET status='dismissed' WHERE name='许誉卿'")
    db.conn.commit()


def _run_resolve_arm(
    root: str,
    content: GameContent,
    cfg: LLMConfig,
    *,
    name: str,
    authority: int,
    kinds: tuple[str, ...] | list[str],
    mutation: Optional[Callable] = None,
    decree_label: str = "",
) -> dict:
    """Shared production resolve_directives runner on an isolated temporary DB."""
    db, state, agno = _open_scene(root, name, content)
    try:
        _apply_base_board(db, state, authority=authority)
        ids = _plant_dossiers(db, state, kinds)
        if mutation is not None:
            mutation(db, state)
        proposed = db.list_decree_dossiers(status="proposed")
        context = build_promulgation_judge_context(db, state, proposed)
        label = decree_label or name
        result = resolve_directives(
            state, db, agno, cfg, [object()], label, content=content,
        )
        turn = state.turn
        verdicts = db.get_pending_promulgation_verdicts(turn)
        resolve_ctx = db.get_resolve_context(turn) or {}
        return {
            "name": name,
            "authority": authority,
            "ids": ids,
            "context": context,
            "verdicts": verdicts,
            "awaiting": bool(result.awaiting),
            "resolve_context": resolve_ctx,
            "report": str(result.report or ""),
        }
    finally:
        db.close()


def _run_low_hold_rail(root: str, content: GameContent, cfg: LLMConfig) -> dict:
    """Low-authority full batch through production hold + next-month reconsideration."""
    db, state, agno = _open_scene(root, "low_hold_rail", content)
    try:
        _apply_base_board(db, state, authority=0)
        ids = _plant_dossiers(db, state, FULL_KINDS)
        first_context = build_promulgation_judge_context(
            db, state, db.list_decree_dossiers(status="proposed"),
        )
        first_result = resolve_directives(
            state, db, agno, cfg, [object()], "四旨并下", content=content,
        )
        if not first_result.awaiting:
            raise RuntimeError("real gate expected rejected dossiers to reach rescript")
        first_turn = state.turn
        first_ctx = db.get_resolve_context(first_turn) or {}
        first_verdicts = db.get_pending_promulgation_verdicts(first_turn)
        choices = _choose_rescripts(
            db, first_turn, ids["hostile"], ids["vital_midzhi"], ids["appointment"],
        )
        resolve_decisions_phase2(state, db, agno, cfg, content=content)
        held = db.get_decree_dossier(ids["hostile"])
        held_history = db.list_decree_dossier_decisions(ids["hostile"])
        text_after_hold = str(held["decree_text"])

        second_context = _prepare_reconsideration_facts(
            db, state, ids["hostile"], first_context,
        )
        second_turn = state.turn
        second_result = resolve_directives(
            state, db, agno, cfg, [], "留中案下月重判", content=content,
        )
        second_pending = db.get_pending_promulgation_verdicts(second_turn)
        second_history = [
            row for row in db.list_decree_dossier_decisions(ids["hostile"])
            if int(row["turn"]) == second_turn and not row.get("rescript_action")
        ]
        second_verdict = _select_second_verdict(
            second_result.awaiting, ids["hostile"], second_pending, second_history,
        )
        second_ctx = db.get_resolve_context(second_turn) or {}
        second_narrative = (
            str(second_ctx.get("narrative") or "")
            if second_result.awaiting else str(second_result.report or "")
        )
        return {
            "name": "low_hold_rail",
            "ids": ids,
            "first_context": first_context,
            "first_verdicts": first_verdicts,
            "first_resolve_context": first_ctx,
            "first_turn": first_turn,
            "choices": choices,
            "held": held,
            "held_history": held_history,
            "text_after_hold": text_after_hold,
            "second_context": second_context,
            "second_verdict": second_verdict,
            "second_narrative": second_narrative,
            "second_awaiting": bool(second_result.awaiting),
        }
    finally:
        db.close()


def _gatekeeper_names(context: dict) -> set[str]:
    return {str(row["name"]) for row in context.get("gatekeepers", [])}


def _faction_row(context: dict, name: str) -> dict:
    for row in context.get("factions", []):
        if str(row.get("name")) == name:
            return dict(row)
    raise RuntimeError(f"faction not in judge context: {name}")


def _by_id(verdicts: list[dict]) -> dict[int, dict]:
    return {int(row["dossier_id"]): row for row in verdicts}


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
    cfg = _cfg(args)

    with tempfile.TemporaryDirectory(prefix="ming-561-gate-") as tmp:
        # Independent arms share one scene constructor + resolve_directives runner;
        # each arm owns an isolated temporary DB and changes only its tested variable.
        arm_jobs = {
            "high_authority": lambda: _run_resolve_arm(
                tmp, content, cfg, name="high_authority", authority=100,
                kinds=FULL_KINDS, decree_label="高皇威对照",
            ),
            "person_leader": lambda: _run_resolve_arm(
                tmp, content, cfg, name="person_leader", authority=100,
                kinds=("hostile",), mutation=_mutate_leader_only,
                decree_label="按人·只安抚首领",
            ),
            "person_gatekeeper": lambda: _run_resolve_arm(
                tmp, content, cfg, name="person_gatekeeper", authority=100,
                kinds=("hostile",), mutation=_mutate_gatekeeper_only,
                decree_label="按人·只换把关人",
            ),
            "face_rank": lambda: _run_resolve_arm(
                tmp, content, cfg, name="face_rank", authority=0,
                kinds=("authority_edge",), decree_label="触发面·越制破格",
            ),
            "face_faction": lambda: _run_resolve_arm(
                tmp, content, cfg, name="face_faction", authority=0,
                kinds=("hostile",), decree_label="触发面·派系逆鳞",
            ),
            "face_office": lambda: _run_resolve_arm(
                tmp, content, cfg, name="face_office", authority=0,
                kinds=("appointment",), decree_label="触发面·把关关口任免",
            ),
            "low_hold_rail": lambda: _run_low_hold_rail(tmp, content, cfg),
        }
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=len(arm_jobs)) as executor:
            futures = {executor.submit(job): name for name, job in arm_jobs.items()}
            for future in as_completed(futures):
                name = futures[future]
                results[name] = future.result()

        trace_records, _ = _trace_records(trace_path)

        low = results["low_hold_rail"]
        high = results["high_authority"]
        leader = results["person_leader"]
        gatekeeper = results["person_gatekeeper"]
        face_rank = results["face_rank"]
        face_faction = results["face_faction"]
        face_office = results["face_office"]

        first_actual_input, first_provenance = _captured_judge_payload(
            trace_records, low["first_context"],
        )
        high_actual_input, high_provenance = _captured_judge_payload(
            trace_records, high["context"],
        )
        leader_actual_input, leader_provenance = _captured_judge_payload(
            trace_records, leader["context"],
        )
        gatekeeper_actual_input, gatekeeper_provenance = _captured_judge_payload(
            trace_records, gatekeeper["context"],
        )
        face_rank_input, face_rank_provenance = _captured_judge_payload(
            trace_records, face_rank["context"],
        )
        face_faction_input, face_faction_provenance = _captured_judge_payload(
            trace_records, face_faction["context"],
        )
        face_office_input, face_office_provenance = _captured_judge_payload(
            trace_records, face_office["context"],
        )
        second_actual_input, second_provenance = _captured_judge_payload(
            trace_records, low["second_context"],
        )

        ids = low["ids"]
        hostile = ids["hostile"]
        ordinary = ids["ordinary"]
        authority_edge = ids["authority_edge"]
        appointment = ids["appointment"]
        admin_midzhi = ids["admin_midzhi"]
        vital_midzhi = ids["vital_midzhi"]
        by_id = _by_id(low["first_verdicts"])
        high_by_id = _by_id(high["verdicts"])
        leader_by_id = _by_id(leader["verdicts"])
        gatekeeper_by_id = _by_id(gatekeeper["verdicts"])
        face_rank_by_id = _by_id(face_rank["verdicts"])
        face_faction_by_id = _by_id(face_faction["verdicts"])
        face_office_by_id = _by_id(face_office["verdicts"])

        first_ctx = low["first_resolve_context"]
        sent_payload = first_ctx.get("simulator_payload") or {}
        sent_ids = {
            int(row["id"]) for row in sent_payload.get("decree_dossiers", [])
            if isinstance(row, dict)
        }
        first_narrative = str(first_ctx.get("narrative") or "")
        forbidden = ("清丈已经完成", "清丈已完成", "太仓已交内廷", "旨意已生效")
        all_verdicts = (
            list(low["first_verdicts"])
            + list(high["verdicts"])
            + list(leader["verdicts"])
            + list(gatekeeper["verdicts"])
            + list(face_rank["verdicts"])
            + list(face_faction["verdicts"])
            + list(face_office["verdicts"])
            + [low["second_verdict"]]
        )
        all_payloads = [
            first_actual_input, high_actual_input, leader_actual_input,
            gatekeeper_actual_input, face_rank_input, face_faction_input,
            face_office_input, second_actual_input,
        ]
        checks = {
            "hostile_land_rejected": by_id[hostile]["decision"] == "rejected",
            "ordinary_pay_promulgated": by_id[ordinary]["decision"] == "promulgated",
            "three_trigger_faces_reject_at_low_authority": all(
                arm_by_id[arm_ids[key]]["decision"] == "rejected"
                for arm_by_id, arm_ids, key in (
                    (face_rank_by_id, face_rank["ids"], "authority_edge"),
                    (face_faction_by_id, face_faction["ids"], "hostile"),
                    (face_office_by_id, face_office["ids"], "appointment"),
                )
            ),
            "authority_edge_passes_only_at_high_authority": (
                by_id[authority_edge]["decision"] == "rejected"
                and high_by_id[high["ids"]["authority_edge"]]["decision"] == "promulgated"
            ),
            "vital_exception_still_rejects_at_high_authority": (
                high_by_id[high["ids"]["vital_midzhi"]]["decision"] == "rejected"
            ),
            "leader_change_does_not_remove_named_gatekeeper_block": (
                leader_by_id[leader["ids"]["hostile"]]["decision"] == "rejected"
                and "许誉卿" in _gatekeeper_names(leader["context"])
                and _gatekeeper_names(leader["context"])
                == _gatekeeper_names(high["context"])
                and _faction_row(leader["context"], "东林")["agenda"]
                == LEADER_APPEASED_AGENDA
                and _faction_row(high["context"], "东林")["agenda"]
                == BASE_DONGLIN_AGENDA
                and int(_faction_row(leader["context"], "东林")["leverage"])
                == int(_faction_row(high["context"], "东林")["leverage"])
            ),
            "gatekeeper_appointment_is_judged_and_rejected": (
                by_id[appointment]["decision"] == "rejected"
                and appointment in {int(row["dossier_id"]) for row in low["first_verdicts"]}
            ),
            "named_gatekeeper_change_unblocks_same_decree": (
                gatekeeper_by_id[gatekeeper["ids"]["hostile"]]["decision"] == "promulgated"
            ),
            "decisions_are_binary_and_batches_cover_inputs": (
                {row["decision"] for row in all_verdicts}
                <= {"promulgated", "rejected"}
                and {int(row["dossier_id"]) for row in low["first_verdicts"]}
                == {int(row["id"]) for row in low["first_context"]["dossiers"]}
                and {int(row["dossier_id"]) for row in high["verdicts"]}
                == {int(row["id"]) for row in high["context"]["dossiers"]}
            ),
            "real_judge_payloads_exclude_satisfaction": all(
                "satisfaction" not in json.dumps(payload, ensure_ascii=False)
                and "满意" not in json.dumps(payload, ensure_ascii=False)
                for payload in all_payloads
            ),
            "held_by_production_rescript": (
                int(low["held"]["held_turn"]) == low["first_turn"]
                and any(row.get("rescript_action") == "hold" for row in low["held_history"])
            ),
            "held_decree_text_unchanged": low["text_after_hold"] == HOSTILE_TEXT,
            "held_land_changes_after_board_change": (
                low["second_verdict"]["decision"] == "promulgated"
                and low["second_verdict"]["decision"] != by_id[hostile]["decision"]
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
            "method": {
                "runner": "resolve_directives",
                "scheduling": "concurrent isolated temporary DBs",
                "arms": sorted(arm_jobs),
                "controls": {
                    "authority_slider": "only 皇威 differs between low_hold_rail and high_authority",
                    "person_not_leader": (
                        "person_leader only sets 东林 agenda to leader-appeased text; "
                        "person_gatekeeper only dismisses 许誉卿; "
                        "both keep 许誉卿-or-not as the sole person variable, "
                        "share 皇威=100 / leverage / the same hostile decree"
                    ),
                    "three_trigger_faces": (
                        "face_rank / face_faction / face_office each plant one dossier"
                    ),
                },
            },
            "scenarios": {
                "ids": {"hostile_land": hostile, "ordinary_pay": ordinary,
                        "authority_edge": authority_edge, "appointment": appointment,
                        "administrative_midzhi": admin_midzhi,
                        "vital_midzhi": vital_midzhi},
                "rescript_choices": low["choices"],
                "hold_state": {
                    "held_turn": low["held"]["held_turn"],
                    "history": low["held_history"],
                },
                "reconsideration_facts": {
                    "factions": [low["first_context"]["factions"],
                                 low["second_context"]["factions"]],
                    "皇威": [low["first_context"]["imperial_authority_band"],
                             low["second_context"]["imperial_authority_band"]],
                    "gatekeepers": [low["first_context"]["gatekeepers"],
                                    low["second_context"]["gatekeepers"]],
                    "authorization_ids": [
                        low["first_context"]["dossiers"][0]["criteria_snapshot_source"][
                            "authorization_ids"
                        ],
                        low["second_context"]["dossiers"][0]["criteria_snapshot_source"][
                            "authorization_ids"
                        ],
                    ],
                    "decree_text": [
                        low["first_context"]["dossiers"][0]["decree_text"],
                        low["second_context"]["dossiers"][0]["decree_text"],
                    ],
                },
                "person_arms": {
                    "leader": {
                        "ids": leader["ids"],
                        "gatekeepers": leader["context"]["gatekeepers"],
                        "factions": leader["context"]["factions"],
                        "leader_appeased_agenda": LEADER_APPEASED_AGENDA,
                    },
                    "gatekeeper": {
                        "ids": gatekeeper["ids"],
                        "gatekeepers": gatekeeper["context"]["gatekeepers"],
                        "factions": gatekeeper["context"]["factions"],
                    },
                },
                "trigger_face_arms": {
                    "rank": face_rank["ids"],
                    "faction": face_faction["ids"],
                    "office": face_office["ids"],
                },
            },
            "judge_first": {
                "input": first_actual_input, "input_provenance": first_provenance,
                "output": low["first_verdicts"],
            },
            "judge_after_authority_change": {
                "input": high_actual_input, "input_provenance": high_provenance,
                "output": high["verdicts"],
            },
            "judge_person_leader_only": {
                "input": leader_actual_input, "input_provenance": leader_provenance,
                "output": leader["verdicts"],
            },
            "judge_person_gatekeeper_only": {
                "input": gatekeeper_actual_input,
                "input_provenance": gatekeeper_provenance,
                "output": gatekeeper["verdicts"],
            },
            "judge_trigger_faces": {
                "rank": {
                    "input": face_rank_input, "input_provenance": face_rank_provenance,
                    "output": face_rank["verdicts"],
                },
                "faction": {
                    "input": face_faction_input,
                    "input_provenance": face_faction_provenance,
                    "output": face_faction["verdicts"],
                },
                "office": {
                    "input": face_office_input,
                    "input_provenance": face_office_provenance,
                    "output": face_office["verdicts"],
                },
            },
            "judge_after_hold_and_board_change": {
                "input": second_actual_input, "input_provenance": second_provenance,
                "output": low["second_verdict"],
            },
            "simulator": {
                "assembly": "resolve_directives production simulator_payload",
                "input": sent_payload, "output": first_narrative,
                "rejected_decree_texts": [HOSTILE_TEXT, VITAL_MIDZHI_TEXT],
                "reconsideration_output": low["second_narrative"],
            },
            "checks": checks,
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"output": args.output, "checks": checks}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
