"""诏书生成与回合结算：拟诏、推演落库、无诏推进。L7。

纯逻辑（无 input()）；resolve_directives 的 print 是诊断输出，非交互。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Protocol, Sequence

from agno.db.sqlite import SqliteDb

from ming_sim.agents import (
    _dump_llm_messages,
    create_chapter_memory_agent,
    create_decree_writer_agent,
    create_promulgation_judge_agent,
    create_ending_summary_agent,
    create_json_sanitizer_agent,
    create_score_extractor_module_agent,
    create_season_simulator_agent,
    parse_agent_json,
    run_agent_text,
)
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector, atomic
from ming_sim.cli_backend import cli_backend_parallel_safe
from ming_sim.constants import TURN_UNIT
from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
from ming_sim.db import GameDB
from ming_sim.error_pack import (
    _next_attempt,
    clear_for_resimulation,
    complete_error_packs_for_ready,
    rejections_jsonl_path,
    settlement_abort_message,
    write_error_pack,
)
from ming_sim.exceptions import LLMContractError, LLMUnavailable, SettlementAbort
from ming_sim.flows import apply_fixed_period_flows, raise_fixed_period_flow_abort_if_needed
from ming_sim.issues import (
    apply_event_terminal_states,
    apply_historical_fiscal_rates,
    apply_issue_inertia_and_ongoing,
    apply_score_extraction,
    auto_trigger_seed_issues,
    clear_gated_legacies,
    sanitize_delta_shape,
    validate_delta_shape,
)
from ming_sim.llm_model import extract_agent_text, llm_unavailable_from_error
from ming_sim.models import FRONT_HALF_DONE_PHASES, GameState, LLMConfig, TurnPhase
from ming_sim.qualitative import power_band, qualitative_band, qualitative_character_axis
from ming_sim.appointment_tenure import (
    DEFAULT_APPOINTMENT_TENURE,
    command_power_rank,
    execution_distortion_weight,
    normalize_appointment_tenure,
)
from ming_sim.participant_roster import resolve_dossier_owner_name
from ming_sim.supervision import unpack_supervision_surface
from ming_sim.decree_vocabulary import (
    SIM_DOSSIER_EXECUTION_KEYS,
    SIM_DOSSIER_NARRATIVE_KEYS,
    dossier_action_policy,
    qualitative_dossier_outcome,
    qualitative_promulgation_slot,
)
from ming_sim.memories import build_timeline, record_chapter_memory
from ming_sim.simulation import (
    EXTRACTION_MODULES,
    build_simulator_payload,
    build_extractor_shared_context,
    extract_scores_by_modules_with_agno,
    simulate_season_with_payload,
)
from ming_sim.strict_types import (
    IMPERIAL_AUTHORITY_BANDS, validate_affected_parties, validate_rejection_verdict,
    validate_verdict_affected_parties,
)
from ming_sim.token_stats import tlog

# 20 年自动结算：开局 1627.10（turn=1），每回合 +1 月。到 1647.10 = (1647-1627)*12 + 1 = 241 回合。
# 满 240 回合（即第 240 个回合结算完，1647.09）仍未分胜负则强制 timeout 收尾。
TIMEOUT_TURN = 240

# 结算 payload 工具（注入文案常量 / 决策块解析 / 密令分组承载 / 已裁决策正文 / 玩家可见
# 呈现脱敏）已抽到 ming_sim.settlement_payload（#91 coordinator 拆分第一刀，纯搬家、行为保持）。
# 此处 re-import 保 `from ming_sim.decree import X` 公开表面 + decree 内部调用点不变。
from ming_sim.settlement_payload import (  # noqa: E402
    CHEAT_NARRATIVE_PREFIX,
    DECISION_NARRATIVE_PREFIX,
    MAX_DECISIONS_PER_TURN,
    _DECISION_RE,
    _format_decision_directive,
    _player_visible_extractor_output,
    _recovered_grouped,
    _select_secret_orders_for_sim,
    _strip_player_internal_fields,
    augment_secret_orders_with_due_commitments,
    bind_decisions_to_candidate_events,
    group_secret_orders_for_sim,
    parse_decision_blocks,
)


@dataclass
class ResolveResult:
    """resolve phase1 的返回。awaiting=True 时表示需皇帝亲裁，已存决策点暂停，
    report 为空、回合未推进；调用方据此置 awaiting_decision 态弹窗。
    awaiting=False 时 report 为完整结算报告（含诏书+邸报+结局），回合已推进。"""
    awaiting: bool
    report: str = ""
    decisions: List[Dict[str, object]] = field(default_factory=list)


class PromulgationVerdictProvider(Protocol):
    """颁布判决注入 seam；实现不得写 DB，判决在后半段 atomic 内统一落库。"""

    def __call__(
        self, dossiers: Sequence[Dict[str, object]], state: GameState,
    ) -> List[Dict[str, object]]: ...


def stub_promulgation_verdicts(
    dossiers: Sequence[Dict[str, object]], state: GameState,
) -> List[Dict[str, object]]:
    """Deterministic auto-promulgation for exempt dossiers and explicit test fixtures."""
    del state
    return [
        {"dossier_id": int(row["id"]), "decision": "promulgated"}
        for row in dossiers
    ]


def _dossier_payload_dict(row: Mapping[str, object] | Dict[str, object]) -> Dict[str, object]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    try:
        parsed = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolve_executor_appointment_tenure(
    db: GameDB, dossier: Mapping[str, object] | Dict[str, object],
) -> str:
    """#613：承办人现职任别——归属人单源后查 character_offices；缺档按真除。

    身份选定与档案取值分离：resolve_dossier_owner_name（#613/#625 共调）
    只定唯一承办人后查该人任别；缺行不得试下一候选换人（禁静默继承他人任别）。
    与 court_roster COALESCE(...,'真除') 及 DELTA_SCHEMA 缺省真除同构。
    """
    name = resolve_dossier_owner_name(dossier)
    if not name:
        return DEFAULT_APPOINTMENT_TENURE
    row = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (name,),
    ).fetchone()
    if row is None:
        return DEFAULT_APPOINTMENT_TENURE
    return normalize_appointment_tenure(row["appointment_tenure"])


def execution_side_read_fields(
    db: GameDB,
    state: GameState,
    dossier: Mapping[str, object] | Dict[str, object],
) -> Dict[str, object]:
    """#613 执行格/推演共用读端字段：任别 + #611 唯一授权投影 + 号令力权重。

    authorization_ids 只来自 project_applicable_authorities，禁止 payload 旁路。
    """
    tenure = resolve_executor_appointment_tenure(db, dossier)
    held_authorities = db.project_applicable_authorities(state.turn, dossier)
    authorization_ids = [str(item["id"]) for item in held_authorities]
    return {
        "appointment_tenure": tenure,
        "held_authorities": held_authorities,
        "authorization_ids": authorization_ids,
        "command_power_rank": command_power_rank(tenure),
        "distortion_weight": execution_distortion_weight(tenure, held_authorities),
    }


def build_promulgation_judge_context(
    db: GameDB,
    state: GameState,
    dossiers: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    """Build the deterministic snapshot from persisted dossier evidence only."""
    faction_rows = db.conn.execute(
        "SELECT name,leverage,agenda FROM factions ORDER BY name"
    ).fetchall()
    class_rows = db.conn.execute(
        "SELECT DISTINCT name FROM classes ORDER BY name"
    ).fetchall()
    issue_rows = db.list_active_issues()
    authority = int(state.metrics.get("皇威", 0))
    authority_band = qualitative_band(
        authority, ("极弱", "偏弱", "中等", "偏强", "强盛")
    )
    assert authority_band in IMPERIAL_AUTHORITY_BANDS
    dossier_rows: List[Dict[str, object]] = []
    for row in sorted(dossiers, key=lambda item: int(item["id"])):
        payload = _dossier_payload_dict(row)
        target_id = row.get("target_id")
        appointment_tenure = str(payload.get("任别") or "")
        # #612: endorsements are DB-backed spoken facts, not payload-only ids.
        endorsements = db.list_dossier_endorsements(int(row["id"]))
        endorsement_ids = [int(item["id"]) for item in endorsements]
        # #611: authorization_ids come only from the unique applicability projection.
        # Never read payload authorization_id(s) as a parallel authority identity source.
        held_authorities = db.project_applicable_authorities(state.turn, row)
        authorization_ids = [str(item["id"]) for item in held_authorities]
        dossier_rows.append({
            "id": int(row["id"]),
            "action_type": str(row.get("action_type") or ""),
            "decree_text": str(row.get("decree_text") or ""),
            "target_kind": str(row.get("target_kind") or ""),
            "target_id": target_id,
            "mode": str(payload.get("mode") or "ordinary"),
            "appointment_tenure": appointment_tenure,
            "break_rank": payload.get("break_rank"),
            "endorsements": endorsements,
            "held_authorities": held_authorities,
            "criteria_snapshot_source": {
                "imperial_authority_band": authority_band,
                "appointment_tenure": appointment_tenure,
                "authorization_ids": authorization_ids,
                "endorsement_entry_ids": sorted(set(endorsement_ids)),
            },
        })
    gatekeepers = [
        {
            **dict(row),
            "courage": qualitative_character_axis("courage", row["courage"]),
            "integrity": qualitative_character_axis("integrity", row["integrity"]),
        }
        for row in db.conn.execute(
            "SELECT name,office,office_type,faction,courage,integrity FROM characters "
            "WHERE status='active' AND power_id='ming' AND "
            "(office LIKE '%首辅%' OR office LIKE '%掌印%' OR office LIKE '%给事中%' "
            "OR office_type='六科') ORDER BY office_type,office,name"
        ).fetchall()
    ]
    history = []
    for item in db.conn.execute(
        "SELECT d.dossier_id,d.turn,d.decision,d.rescript_action,x.payload_json "
        "FROM decree_dossier_decisions d JOIN decree_dossiers x ON x.id=d.dossier_id "
        "ORDER BY d.turn,d.dossier_id,d.id"
    ).fetchall():
        payload = json.loads(str(item["payload_json"] or "{}"))
        mode = str(payload.get("mode") or "ordinary")
        rescript_action = str(item["rescript_action"] or "")
        forced = rescript_action == "force_promulgated"
        # A rescript disposition is not another promulgation attempt.  Force is
        # retained independently because it is itself a durable history marker.
        if not forced and (mode != "midzhi" or rescript_action):
            continue
        history.append({
            "dossier_id": int(item["dossier_id"]), "turn": int(item["turn"]),
            "mode": mode, "marker": "批红强颁" if forced else "中旨",
            "outcome": "promulgated" if forced else str(item["decision"]),
        })
    return {
        "turn": {"turn": state.turn, "year": state.year, "period": state.period},
        "dossiers": dossier_rows,
        "factions": [
            # #614 / ADR 0143: player-visible judge reasons inherit this input;
            # project resistance as the same qualitative band as imperial_authority_band.
            {"name": str(row["name"]),
             "leverage": power_band(row["leverage"]),
             "agenda": str(row["agenda"] or "")}
            for row in faction_rows
        ],
        "imperial_authority_band": authority_band,
        # Enumeration only: classes are valid affected-party keys, never an
        # extra resistance signal (in particular no satisfaction is exposed).
        "classes": [str(row["name"]) for row in class_rows],
        "gatekeepers": gatekeepers,
        "promulgation_history": history,
        "current_events": [
            {key: row[key] for key in ("id", "title", "status") if key in row.keys()}
            for row in issue_rows
        ],
    }


def _require_promulgation_verdict_list(
    generated: object, *, raw_value: object = None,
) -> List[Dict[str, object]]:
    """Canonical top-level shape authority for every promulgation verdict batch."""
    if not isinstance(generated, list):
        raise LLMContractError(
            "颁布判官 verdicts 必须为列表", raw_value=raw_value,
        )
    return generated


def llm_promulgation_verdicts(
    dossiers: Sequence[Dict[str, object]], state: GameState, *, db: GameDB,
    agno_db: SqliteDb, llm_config: LLMConfig,
    prepared_context: Optional[Dict[str, object]] = None,
) -> List[Dict[str, object]]:
    """Run exactly one LLM call for one reviewed promulgation batch."""
    context = prepared_context or build_promulgation_judge_context(db, state, dossiers)
    agent = create_promulgation_judge_agent(llm_config, agno_db)
    raw = run_agent_text(
        agent, json.dumps(context, ensure_ascii=False, sort_keys=True),
        tag="promulgation-judge",
    )
    parsed = parse_agent_json(raw, "颁布判官")
    verdicts = parsed.get("verdicts") if isinstance(parsed, dict) else None
    return _require_promulgation_verdict_list(verdicts, raw_value=parsed)


def _validate_promulgation_verdict_item(
    row: object, db: GameDB,
    *,
    proposed_modes: Optional[Dict[int, str]] = None,
    prepared_context: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """The single shape/identity authority for one provider verdict."""
    if not isinstance(row, dict):
        raise LLMContractError("颁布判决须为对象")
    if str(row.get("decision") or "") not in {"promulgated", "rejected"}:
        raise LLMContractError("颁布判决 decision 只能为 promulgated 或 rejected")
    dossier_id = row.get("dossier_id")
    if (isinstance(dossier_id, bool) or not isinstance(dossier_id, int)
            or not 0 < dossier_id <= 2 ** 63 - 1):
        raise LLMContractError("颁布判决 dossier_id 必须为有效 SQLite 正整数")

    context = prepared_context or {}
    if prepared_context is not None:
        faction_names = {
            str(item["name"]) for item in context.get("factions", [])
            if isinstance(item, dict)
        }
        class_names = {str(item) for item in context.get("classes", [])}
        gatekeeper_ids = {
            str(item["name"]) for item in context.get("gatekeepers", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        context_dossiers = {
            int(item["id"]): item for item in context.get("dossiers", [])
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
    else:
        faction_names = {
            str(item["name"]) for item in db.conn.execute("SELECT name FROM factions")
        }
        class_names = {
            str(item["name"])
            for item in db.conn.execute("SELECT DISTINCT name FROM classes")
        }
        gatekeeper_ids = {
            str(item["name"])
            for item in db.conn.execute("SELECT name FROM characters")
        }
        context_dossiers = {}

    modes = proposed_modes or {}
    rejection_only_fields = {
        "blocked_layer", "primary_opponents", "gatekeeper_id", "reason",
        "criteria_snapshot", "midzhi_unpromulgatable",
    }
    try:
        decision = row.get("decision")
        if decision == "promulgated" and rejection_only_fields & row.keys():
            raise ValueError("顺颁判决不得携带打回专属字段")
        marker = row.get("midzhi_unpromulgatable", False)
        if not isinstance(marker, bool):
            raise ValueError("中旨亦不可颁标记必须为 bool")
        mode = modes.get(dossier_id) if isinstance(dossier_id, int) else None
        if marker:
            if mode is not None:
                if decision != "rejected" or mode != "midzhi":
                    raise ValueError("中旨亦不可颁只能标记中旨打回判决")
            elif decision != "rejected":
                raise ValueError("中旨亦不可颁只能标记打回判决")
        if any(isinstance(key, str) and key.startswith("resistance_") for key in row):
            raise ValueError("颁布判决不得携带阻力数值字段")
        # Exact verdict-key enforcement (#561) when mode is known from proposed set.
        if mode is not None:
            allowed_keys = {"dossier_id", "decision"}
            if decision == "promulgated" and mode == "midzhi":
                allowed_keys.add("affected_parties")
            elif decision == "rejected":
                allowed_keys.update(rejection_only_fields - {"midzhi_unpromulgatable"})
                allowed_keys.update({"affected_parties", "legal_reason_code"})
                if mode == "midzhi":
                    allowed_keys.add("midzhi_unpromulgatable")
            unknown_keys = set(row) - allowed_keys
            if unknown_keys:
                raise ValueError(f"颁布判决含未知字段：{sorted(unknown_keys)}")
            validate_verdict_affected_parties(
                row, mode, faction_names=faction_names, class_names=class_names,
            )
        else:
            affected = row.get("affected_parties", [])
            if not isinstance(affected, list):
                raise ValueError("受损方必须为 typed 清单")
            validate_affected_parties(
                affected, faction_names=faction_names, class_names=class_names,
            )
        if row.get("decision") == "rejected":
            validate_rejection_verdict(
                row, {"cabinet_drafting", "palace_rescript", "six_offices"},
                faction_names=faction_names,
                class_names=class_names,
                character_ids=gatekeeper_ids,
            )
            if dossier_id in context_dossiers:
                source_snapshot = context_dossiers[dossier_id].get(
                    "criteria_snapshot_source"
                )
                if row.get("criteria_snapshot") != source_snapshot:
                    raise ValueError("打回判决 criteria_snapshot 与判官输入原值不一致")
    except ValueError as exc:
        raise LLMContractError(str(exc)) from exc
    return row


def validate_promulgation_verdicts(
    generated: object, proposed_dossiers: Sequence[Dict[str, object]], db: GameDB,
    *, prepared_context: Optional[Dict[str, object]] = None,
) -> List[Dict[str, object]]:
    """Validate items through one authority, then enforce batch coverage once."""
    generated = _require_promulgation_verdict_list(generated)
    context = prepared_context
    if context is None:
        # Minimal identity sets when callers do not pass the judge snapshot.
        context = {
            "dossiers": [],
            "factions": [
                dict(item) for item in db.conn.execute("SELECT name FROM factions")
            ],
            "classes": [
                str(item["name"]) for item in db.conn.execute(
                    "SELECT DISTINCT name FROM classes ORDER BY name"
                )
            ],
            "gatekeepers": [
                {"name": str(item["name"])}
                for item in db.conn.execute("SELECT name FROM characters")
            ],
        }
    proposed_modes: Dict[int, str] = {}
    for dossier in proposed_dossiers:
        payload = dossier.get("payload")
        if not isinstance(payload, dict):
            payload = json.loads(str(dossier.get("payload_json") or "{}"))
        action_type = dossier.get("action_type")
        external_review = (
            dossier_action_policy(action_type, payload)["external_review"]
            if action_type is not None else True
        )
        # Exempt actions are deterministic auto-promulgations, not judge
        # verdicts. Their payload mode cannot require reviewed-only evidence.
        proposed_modes[int(dossier["id"])] = (
            str(payload.get("mode") or "ordinary")
            if external_review else "ordinary"
        )
    rows = [
        _validate_promulgation_verdict_item(
            row, db, proposed_modes=proposed_modes, prepared_context=context,
        )
        for row in generated
    ]
    verdict_ids = {int(row["dossier_id"]) for row in rows}
    proposed_ids = {int(row["id"]) for row in proposed_dossiers}
    if verdict_ids != proposed_ids or len(rows) != len(proposed_ids):
        raise LLMContractError("颁布判决须逐案覆盖全部 proposed 案卷，不能静默跳过")
    return rows


def _rescript_decisions(
    verdicts: List[Dict[str, object]],
    dossiers: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Turn rejected promulgation verdicts into the existing HITL decision rail."""
    by_id = {int(row["id"]): row for row in dossiers}
    decisions: List[Dict[str, object]] = []
    for verdict in verdicts:
        if str(verdict.get("decision") or "") != "rejected":
            continue
        dossier_id = int(verdict.get("dossier_id") or 0)
        dossier = by_id.get(dossier_id)
        if dossier is None:
            continue
        opponents = [
            str(item.get("key") or "").strip()
            for item in verdict.get("primary_opponents", [])
            if isinstance(item, dict) and str(item.get("key") or "").strip()
        ]
        opposition = "、".join(opponents)
        decisions.append({
            "event_id": f"dossier:{dossier_id}",
            "title": "批红待裁",
            "context": str(dossier.get("decree_text") or ""),
            "rejection_reason": str(verdict.get("reason") or "").strip(),
            "opposition": opposition,
            "options": [
                *([] if verdict.get("midzhi_unpromulgatable") is True else [{
                    "label": "强颁",
                    "note": "以中旨强行颁出",
                    "dossier_id": dossier_id,
                    "dossier_decision": "force_promulgated",
                }]),
                {
                    "label": "收回",
                    "note": "收回此道准旨",
                    "dossier_id": dossier_id,
                    "dossier_decision": "withdrawn",
                },
                {
                    "label": "留中",
                    "note": "留待下月重判",
                    "dossier_id": dossier_id,
                    "dossier_decision": "hold",
                },
            ],
        })
    return decisions


def _chosen_rescript_actions(
    decisions: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    actions: List[Dict[str, object]] = []
    for decision in decisions:
        if not str(decision.get("event_id") or "").startswith("dossier:"):
            continue
        choice = decision.get("choice")
        if not isinstance(choice, dict):
            raise LLMContractError("批红决策缺少玩家选择")
        dossier_id = int(choice.get("dossier_id") or 0)
        action = str(choice.get("dossier_decision") or "")
        if dossier_id <= 0 or action not in {
            "force_promulgated", "withdrawn", "hold",
        }:
            raise LLMContractError("批红决策载荷非法")
        actions.append({"dossier_id": dossier_id, "decision": action})
    return actions


def _dossier_ids_from_simulator_payload(simulator_payload: object) -> set[int]:
    if not isinstance(simulator_payload, dict):
        return set()
    raw = simulator_payload.get("decree_dossiers")
    if not isinstance(raw, list):
        return set()
    return {
        int(item["id"])
        for item in raw
        if isinstance(item, dict) and str(item.get("id") or "").isdigit()
    }


def _candidate_event_ids_from_simulator_payload(simulator_payload: object) -> Optional[set[str]]:
    if not isinstance(simulator_payload, dict):
        return None
    raw = simulator_payload.get("candidate_events")
    if not isinstance(raw, list):
        return None
    return {
        str(item.get("id") or "").strip()
        for item in raw
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def _record_settlement_narrative_sources(
    db: GameDB, state: GameState, narrative: str, *, commit: bool = False,
) -> None:
    """Archive settlement prose without making an aggregate an access boundary.

    A simulator narrative is an aggregate and may paraphrase a restricted
    source.  When this turn has restricted material it is never an audience
    source: independently persisted source items and explicit public archive
    counterparts provide the only readable material.
    """
    items = db.knowledge_items_for_turn(state.turn)
    restricted_ids = [
        str(item.get("source_id") or "")
        for item in items if item.get("excluded_names")
    ]
    # Audience chat is not an input to the month-end simulator.  Its presence
    # in the same turn therefore cannot taint an independently produced public
    # settlement narrative.  Other restricted shared sources still block it.
    # #883/#976: active secret-order briefs are private structure — their
    # presence alone must NOT swallow pure public narrative (F3).  Public LLM
    # inputs never preload secrets (structure); no text-filter strip.
    restricted_kinds = set()
    for source_id in restricted_ids:
        row = db.conn.execute(
            "SELECT kind FROM character_knowledge_sources WHERE source_id=?",
            (source_id,),
        ).fetchone()
        restricted_kinds.add(str(row["kind"] or "") if row is not None else "unknown")
    has_restricted_source = db._has_restricted_source_gate(
        any(kind != "audience" for kind in restricted_kinds)
    )
    source_id = f"settlement:narrative:{state.turn}"
    if has_restricted_source:
        return
    narrative_text = str(narrative or "").strip()
    if not narrative_text:
        return
    db.record_public_knowledge_event(
        state, "本回合邸报", narrative_text, source_id=source_id, commit=commit,
    )


def write_decree_with_agno(
    llm_config: LLMConfig,
    agno_db: SqliteDb,
    state: GameState,
    directives: List[sqlite3.Row],
    db: Optional[GameDB] = None,
) -> str:
    if not directives:
        raise LLMContractError("无草案不能拟诏。")
    # 已办结密令的 result 作为实质证据清单注入——皇帝下旨拿人/定罪时可引为依据。
    closed_evidence: List[Dict[str, object]] = []
    if db is not None:
        try:
            for o in db.list_secret_orders(status="done"):
                if o.get("result"):
                    closed_evidence.append({
                        "id": int(o["id"]), "title": o["title"],
                        "assignee": o["minister_name"], "evidence": o["result"],
                    })
        except Exception:
            closed_evidence = []
    payload = {
        "turn": {"year": state.year, "period": state.period, "turn": state.turn},
        "directives": [
            {
                "text": row["text"],
            }
            for row in directives
        ],
        "closed_secret_orders": closed_evidence,
        "instruction": "合并成一份正式诏书正文。closed_secret_orders 是已办结密令查得的实证，"
                       "若草案据某密令查办之事拿人定罪，可在诏书里引该实证为据，使罪名落到实处。",
    }
    try:
        agent = create_decree_writer_agent(llm_config, agno_db)
        run_output = agent.run(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        _dump_llm_messages(run_output, "拟诏", agent=agent)
        text = extract_agent_text(run_output)
    except LLMUnavailable:
        raise
    except Exception as error:
        raise llm_unavailable_from_error(error, "拟诏") from error
    if not text.strip():
        raise LLMContractError("拟诏输出为空。")
    return text.strip()


def _simulator_link_item(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "target_dossier_id": int(item["target_dossier_id"]),
        "relation_type": str(item.get("relation_type") or ""),
        "note": str(item.get("note") or ""),
    }


def _simulator_promulgated_turn(row: Dict[str, object], db: GameDB) -> int:
    """Resolve promulgated_turn from row or durable decision history (fail loud)."""
    if row.get("promulgated_turn") not in (None, ""):
        try:
            return int(row["promulgated_turn"])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    # ADR 0005: db read errors must not collapse into hollow 0 for 邸报 inputs.
    hist = db.list_decree_dossier_decisions(int(row["id"]))
    for item in hist:
        if str(item.get("decision") or "") == "promulgated":
            return int(item.get("turn") or 0)
        if str(item.get("rescript_action") or "") == "force_promulgated":
            return int(item.get("turn") or 0)
    return 0


def _simulator_dossier_links(
    row: Dict[str, object], db: GameDB,
) -> List[Dict[str, object]]:
    if isinstance(row.get("links"), list):
        raw = row["links"]  # type: ignore[assignment]
    else:
        # ADR 0005: no silent empty-links on db/schema failure.
        raw = db.list_dossier_links(int(row["id"]))
    return [
        _simulator_link_item(item)
        for item in raw
        if isinstance(item, dict) and item.get("target_dossier_id") is not None
    ]


def _project_one_dossier_for_simulator(
    row: Dict[str, object],
    *,
    track: str,
    db: GameDB,
    execution_summary: Optional[Dict[str, object]] = None,
    side_fields: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """#569 B + #613: fixed-key projection with execution-side tenure fields."""
    stigma = row.get("stigma")
    if not isinstance(stigma, list):
        stigma = []
    roster = row.get("participant_roster")
    if not isinstance(roster, list):
        roster = []
    projected: Dict[str, object] = {
        "id": int(row["id"]),
        "action_type": str(row.get("action_type") or ""),
        "status": str(row.get("status") or ""),
        "decision": qualitative_promulgation_slot(row),
        "outcome": qualitative_dossier_outcome(
            row.get("execution_outcome"), status=row.get("status"),
        ),
        "note": str(row.get("execution_note") or ""),
        "mode": str(row.get("mode") or "ordinary"),
        "stigma": list(stigma),
        "participant_roster": list(roster),
        "links": _simulator_dossier_links(row, db),
        "due_turn": int(row.get("due_turn") or 0),
        "created_turn": int(row.get("created_turn") or 0),
        "promulgated_turn": _simulator_promulgated_turn(row, db),
        "target_kind": str(row.get("target_kind") or ""),
        "target_id": str(row.get("target_id") or ""),
        "executor_kind": str(row.get("executor_kind") or ""),
        "executor_id": str(row.get("executor_id") or ""),
    }
    # #613: tenure + #611 authority projection ride the fixed-key surface.
    projected.update(dict(side_fields or {}))
    # #625: supervision fact bottom (read-only inject; empty when none).
    projected.update(
        unpack_supervision_surface(
            db.build_supervision_judge_surface(int(row["id"]))
        )
    )
    if track == "narrative":
        projected["decree_text"] = str(row.get("decree_text") or "")
        expected = SIM_DOSSIER_NARRATIVE_KEYS
    else:
        projected["execution_summary"] = dict(execution_summary or {})
        expected = SIM_DOSSIER_EXECUTION_KEYS
    keys = set(projected)
    if keys != expected:
        raise RuntimeError(
            f"simulator dossier projection key drift track={track} "
            f"missing={sorted(expected - keys)} extra={sorted(keys - expected)}"
        )
    return projected


def project_dossiers_for_simulator(
    simulation_visible_dossiers: List[Dict[str, object]],
    db: GameDB,
    state: GameState,
) -> List[Dict[str, object]]:
    """Assemble decree_dossiers for the month simulator (ADR 0055 / #517 / #569 / #613).

    db/state are required: #569 links/promulgated_turn and #613 tenure + #611
    authority projection must read DB truth; silent skip is not allowed.
    """
    if db is None or state is None:
        raise TypeError(
            "project_dossiers_for_simulator requires db and state "
            "(no silent skip of execution-side projection)"
        )
    dossier_payload: List[Dict[str, object]] = []
    for row in simulation_visible_dossiers:
        payload = _dossier_payload_dict(row)
        policy = dossier_action_policy(row.get("action_type"), payload)
        # Narrative-owned effects are simulator material.  Deterministically
        # materialized payload-owned work remains visible only as inert execution
        # context: decree text and mechanical payload must not be replayed.
        admitted = (
            str(row.get("status") or "") != "proposed"
            or str(row.get("settlement_verdict") or "") == "promulgated"
        )
        # #613: same #611 projection + executor tenure on the sim assembly chain.
        side_fields: Dict[str, object] = (
            execution_side_read_fields(db, state, row) if admitted else {}
        )
        if policy["effect_owner"] == "narrative" and admitted:
            dossier_payload.append(
                _project_one_dossier_for_simulator(
                    row, track="narrative", db=db, side_fields=side_fields,
                )
            )
            continue
        # In-transit executing work, and just-promulgated payload-owned terminal
        # effects (惩处/招抚等), need command/target context without re-materializing.
        just_promulgated_terminal = (
            policy["effect_owner"] == "payload"
            and policy.get("execution_surface") == "terminal"
            and str(row.get("settlement_verdict") or "") == "promulgated"
        )
        if admitted and (
            str(row.get("status") or "") == "executing" or just_promulgated_terminal
        ):
            execution_summary: Dict[str, object] = {
                "command": str(row.get("decree_text") or "").strip(),
            }
            # target_id 已在行级字段；此处补 payload 侧必要动作上下文（金额/账户/惩处动作）。
            for key in (
                "amount", "account", "target_account", "purpose", "reason",
                "punish_action",
            ):
                value = payload.get(key)
                if value not in (None, ""):
                    execution_summary[key] = value
            dossier_payload.append(
                _project_one_dossier_for_simulator(
                    row, track="execution",
                    execution_summary=execution_summary, db=db,
                    side_fields=side_fields,
                )
            )
    return dossier_payload


def _requires_full_settlement(state: GameState, db: GameDB) -> bool:
    """Whether advancing this month requires the normal simulator/extractor rail."""
    executing_work = False
    for row in db.list_decree_dossiers(status="executing"):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = json.loads(str(row.get("payload_json") or "{}"))
        # Terminal immediate actions (notably short secret orders) are already
        # materialized and must retain the no-edict fast path.  Other executing
        # dossiers remain simulator continuation context under the #560 policy.
        if dossier_action_policy(row.get("action_type"), payload)["execution_surface"] != "terminal":
            executing_work = True
            break
    return bool(db.list_monthly_dossier_progress_nudges()) or bool(
        db.list_decree_dossiers(status="proposed")
    ) or executing_work or any(
        row.get("kind") == "directive"
        for row in db.list_pending_actions(state.turn)
    )


class _NeedsFullSettlement(Exception):
    """Abort the speculative fast transaction and retry on the full rail."""


def advance_without_edict(state: GameState, db: GameDB, *, content=None, registry=None,
                          inflight_wait_s: float | None = None,
                          llm_config=None, write_gate=None,
                          scene_registry=None) -> bool:
    # 退朝未下正式诏书也是月末:先 commit 本回合暂存的结构化写动作(颁诏前未撤回即通过,
    # ADR 0006),否则暂存成孤儿、随 next_period 永久丢失(CMR P1)。须在 next_period 前。
    # content/registry 供 office(任免)落库注册新臣;无则任免落不了(标 failed,不静默)。
    #
    # ADR 0008 S7（决定 2）：整条推进尾包进单事务——任何一步崩则全回滚（commit_pending_actions
    # / 财政 / record_log / clear / 推进写序列全有或全无，不许半写）。回滚后内存从 DB 重载
    # （同 pre_settle 先例），链式 re-raise 不吞（fail-loud，ADR 0005）。pre_settle 自己的
    # atomic 与本路不嵌套（advance 路上 pre_settle 不在调用栈），各包裹层自治。
    # ADR 决定 6：不提供「跳过本月结算」。前半段已提交后退朝=财政已落而本月 LLM 结算
    # 永不落+丢弃已存结算上下文=自愿半落库（ship-pre r1，废除 S4 时代的「安全推进」语义）。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        if state.turn_phase == TurnPhase.AWAITING_DECISION.value:
            raise ValueError("月末重大抉择待裁决，请先裁决后完成结算，不能退朝跳过。")
        raise ValueError("月末结算已开始（前半段已入账），请重试颁诏完成结算，不能退朝跳过。")
    # #1234/#1235：退朝入口点击受理即独立提交月初快照（任何突变之前，含 auto_close）。
    db.capture_month_open_snapshot(state)
    # #498：过回合遇开夜 → 顺势自动收夜（在飞 fail-closed 会挡住本路，夜保持开）。
    # 放在 atomic 外：收夜自有写与错误包，不与推进事务半嵌。
    # #503：收夜 beat 生产路径接通编排缝。
    from ming_sim.audience_night import AudienceNightError, auto_close_open_night
    from ming_sim.beat_orchestration import create_llm_beat_generator
    from ming_sim.month_open_snapshot import exit_settlement_display_on_failure
    # Forward llm_config/write_gate so close-night can catch up ordinary story
    # facts and run the gate-free endorsement-only batch. Callers must not hold
    # an outer non-reentrant runtime write gate while passing nullcontext.
    # #503/#542：收夜 beat 与开夜/入殿共用真实 scene LLM adapter。
    effective_llm = llm_config if llm_config is not None else getattr(db, "llm_config", None)
    # No usable config → skip adapter construction (None would AttributeError on base_url).
    beat_generator = (
        create_llm_beat_generator(effective_llm) if effective_llm is not None else None
    )
    # #542：调用方既有 ChatTurnSceneRegistry（session._scene_registry）；不在此新建。
    try:
        auto_close_open_night(db, state, content=content, registry=registry,
                              wait_timeout_s=inflight_wait_s,
                              beat_generator=beat_generator,
                              llm_config=effective_llm, write_gate=write_gate,
                              scene_registry=scene_registry)
    except AudienceNightError:
        # #1235 真失败另形：0036 收夜 fail-closed 后人话中止 + 出展示态。
        exit_settlement_display_on_failure(db, state)
        raise
    # atomic + 最外层回滚后从 DB 重载刷净内存（state.metrics 直加 / next_period / turn_phase
    # 留脏）：公共内核见 atomic_and_reload（ADR 0008 决定 3，reload 再炸链上抛 cmr S5 r2）。
    try:
        with atomic_and_reload(db, state, content=content, registry=registry):
            db.commit_pending_actions(state, content=content, registry=registry)
            # Classification is only valid after every pending kind has materialized.
            # If the DB truth requires the expensive rail, abort this transaction so
            # pre_settle owns materialization and every associated side effect.
            if _requires_full_settlement(state, db):
                raise _NeedsFullSettlement
            fiscal_levies = apply_historical_fiscal_rates(state, db, commit=False)
            if fiscal_levies:
                tlog(
                    f"[fiscal-levy] 本回合饷率事件前置落账 {len(fiscal_levies)} 条："
                    f"{[(t['id'], t.get('terminal_reason') or t['terminal_state']) for t in fiscal_levies]}"
                )
            apply_fixed_period_flows(db, state)
            message = f"本{TURN_UNIT}退朝未下正式圣旨，诸事仍待来{TURN_UNIT}处置。"
            db.record_log(state, message)
            print("\n" + message)
            # 推进回合的路都得清本回合 resolve_context：崩溃重试后改走此路时，留下的
            # ready=1 行会被恢复入口当「未完成回合」重放=double-apply（cmr S2+S3 r4）。
            db.clear_resolve_context(state.turn)
            # #1234：月推进完成，快照按回合绑定在同一 atomic 内过期（禁 commit 后再清）。
            db.clear_month_open_snapshot(state.turn)
            state.next_period()
            # settling 随推进复位，同 settle_with_delta（cmr S4 r1 F1）。
            state.turn_phase = TurnPhase.SUMMONING.value
            db.save_state(state)
    except _NeedsFullSettlement:
        return False
    except BaseException as exc:
        raise_fixed_period_flow_abort_if_needed(db, state, exc)
        raise
    return True


def resolve_directives(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    directives: List[sqlite3.Row],
    decree_text: str,
    deaths_this_turn: Optional[List[Dict[str, str]]] = None,
    debuts_this_turn: Optional[List[Dict[str, str]]] = None,
    on_event: Optional[Callable[[str, str], None]] = None,
    content=None,
    registry=None,
    cheat_directive: str = "",
    source: Provenance = Provenance.player_decree,
    promulgation_verdict_provider: Optional[PromulgationVerdictProvider] = None,
    scene_registry=None,
) -> ResolveResult:
    """phase1：跑固定财政 + simulator 写邸报，解析 HITL 决策点。

    source（#146 cmr r2）：本回合结算 delta 的来源。默认 player_decree——正常皇帝下旨路
    行为不变。崩溃恢复 fallthrough（SETTLING 非 ready ctx 重走本函数）须把存档 ctx['source']
    经 _provenance_from_stored 还原后传入，使 provenance 按构造保真（system_simulation 重跑仍
    记 system、对玩家静默），不依赖「非 ready SETTLING ctx 恒 player」这一脆弱不变式。

    on_event(kind, data): 推演过程实时回调。
    kind ∈ {stage, thinking, text}；stage 携带阶段名，thinking/text 携带增量片段。

    cheat_directive: 作弊控制台（Ctrl+~）下的强制结算指令。非空时拼到当期邸报最前面
    一起喂给 extractor，按字面当既成事实落库。唯一入口——只此一处写入标记前缀（见
    CHEAT_NARRATIVE_PREFIX），别处不得复用。

    返回 ResolveResult：simulator 邸报含决策点 → 存上下文+决策点暂停（awaiting=True，
    回合未推进）；无决策点 → 直接续跑 extractor 结算，返回完整报告（awaiting=False）。
    """
    def _emit(kind: str, data: str) -> None:
        if on_event:
            on_event(kind, data)

    if (not directives and not _requires_full_settlement(state, db)
            and not db.list_pending_actions(state.turn)):
        advance_without_edict(
            state, db, content=content, registry=registry,
            scene_registry=scene_registry,
        )
        return ResolveResult(awaiting=False, report=f"本{TURN_UNIT}未颁正式诏书。")

    before_turn = state.turn

    # 草案内容已由拟诏合并进 decree_text，simulator 只读 decree_text，不再单传逐条草案。

    # 1) 前括号确定性结算：固定月度财政 tick + auto_trigger 硬立 seed 情势（均在 LLM 推演前）。
    #    与探针 driver 共用同一段（ADR 0004）。
    #
    # 诏书占位真源（ship-pre r5）：pre_settle 成功后立即把 decree_text 落为 ready=0
    # 占位——begin_turn 会清内存 last_decree，跨进程恢复的 no-ready fallthrough 没有
    # 此行就只能用 LLM 从草案重新生成，玩家手改的原诏蒸发。HITL/ready persist 后续
    # 同键 upsert，settle 尾 clear 收掉。
    #
    # 占位与 settling 相位同事务可见（PR #90 R1 codex P2）：外层 atomic 把 pre_settle
    # 的内层事务并入（flat 可重入），崩在「settling 已提交、占位未落」的窗口不再可能
    # ——要么两者都见，要么整段回滚重来。恢复重推演路重进时 pre_settle 幂等守门
    # 早退、占位同键 upsert，语义不变。
    # pre_settle 自己的 atomic 在此嵌套（depth>0）时跳过 reload，由本层（最外层）真回滚后
    # 重载刷净内存（同 advance_without_edict 先例）；reload 再炸链上抛。见 atomic_and_reload。
    try:
        with atomic_and_reload(db, state, content=content, registry=registry):
            auto_triggered = pre_settle(
                state, db, on_stage=lambda label: _emit("stage", label),
                content=content, registry=registry,
                scene_registry=scene_registry)
            db.save_resolve_context(
                state.turn, decree_text, "", {},
                secret_orders={}, relevant_memories=[],   # #48：占位用分组承载的空 dict（旋即被真存覆盖）
                source=Provenance(source).value,    # #146 A：皇帝下旨回合默认 player（被真存同值覆盖）；恢复 fallthrough 穿透 ctx 真源。Provenance(source).value 归一(兼容 enum/合法值串)、与 persist_resolve_context 一致(gemini R5)
            )
    except BaseException as exc:
        raise_fixed_period_flow_abort_if_needed(db, state, exc)
        raise

    proposed_dossiers = db.list_decree_dossiers(status="proposed")
    verdict_rows: List[Dict[str, object]] = []
    rejected_verdict_batch: object = None
    reviewed_dossier_ids: Optional[set[int]] = None
    prepared_context: Optional[Dict[str, object]] = None
    proposed_modes: Dict[int, str] = {}
    try:
        if proposed_dossiers:
            reviewed, exempt = [], []
            for dossier in proposed_dossiers:
                payload = dossier.get("payload")
                if not isinstance(payload, dict):
                    payload = json.loads(str(dossier.get("payload_json") or "{}"))
                proposed_modes[int(dossier["id"])] = str(payload.get("mode") or "ordinary")
                (reviewed if dossier_action_policy(
                    dossier.get("action_type"), payload,
                )["external_review"] else exempt).append(dossier)
            # One prepared object is the judge input and validator truth source.
            # Exempt dossiers are included only for ID/mode validation; they are
            # never sent to the LLM.
            prepared_context = build_promulgation_judge_context(db, state, reviewed)
            reviewed_dossier_ids = {int(row["id"]) for row in reviewed}
            # A validated batch is durable before any simulator work.  Recovery is
            # turn-scoped: an old hold verdict can never suppress this month's call.
            stored = db.get_pending_promulgation_verdicts(state.turn)
            if stored:
                rejected_verdict_batch = stored
                verdict_rows = validate_promulgation_verdicts(
                    stored, proposed_dossiers, db, prepared_context=prepared_context,
                )
            else:
                provider = promulgation_verdict_provider
                generated = (
                    provider(reviewed, state) if provider is not None else
                    llm_promulgation_verdicts(
                        reviewed, state, db=db, agno_db=agno_db,
                        llm_config=llm_config, prepared_context=prepared_context,
                    )
                ) if reviewed else []
                rejected_verdict_batch = generated
                generated = _require_promulgation_verdict_list(generated) + (
                    stub_promulgation_verdicts(exempt, state) if exempt else []
                )
                verdict_rows = validate_promulgation_verdicts(
                    generated, proposed_dossiers, db,
                    prepared_context=prepared_context,
                )
                db.save_pending_promulgation_verdicts(state.turn, verdict_rows)
    except LLMContractError as exc:
        # Attribute item failures through the same validator used above.  Synthetic
        # exempt stubs never enter this provider audit input.
        if exc.raw_value is not None:
            rejected_items = [(exc.raw_value, str(exc))]
        elif isinstance(rejected_verdict_batch, list):
            rejected_items = []
            seen_provider_ids: set[int] = set()
            for candidate in rejected_verdict_batch:
                try:
                    valid_candidate = _validate_promulgation_verdict_item(
                        candidate, db,
                        proposed_modes=proposed_modes,
                        prepared_context=prepared_context,
                    )
                except LLMContractError as item_exc:
                    rejected_items.append((candidate, str(item_exc)))
                    continue
                if reviewed_dossier_ids is not None:
                    dossier_id = int(valid_candidate["dossier_id"])
                    if dossier_id not in reviewed_dossier_ids or dossier_id in seen_provider_ids:
                        rejected_items.append((candidate, str(exc)))
                    seen_provider_ids.add(dossier_id)
            # Missing coverage has no guilty item: retain the provider batch once
            # as raw batch evidence instead of mislabelling every valid verdict.
            if not rejected_items:
                rejected_items = [({"raw_value": rejected_verdict_batch}, str(exc))]
        else:
            rejected_items = [(rejected_verdict_batch, str(exc))]
        collector = RejectionCollector(attempt=_next_attempt(state.turn))
        with atomic(db):
            for rejected_verdict, rejection_reason in rejected_items:
                collector.record(
                    "promulgation_verdicts",
                    RejectedItem(
                        item=(
                            rejected_verdict if isinstance(rejected_verdict, dict)
                            else {"raw_value": rejected_verdict}
                        ),
                        reason=rejection_reason,
                        category="invalid_shape",
                        source=Provenance(source),
                    ),
                    state.turn,
                )
            collector.flush_to_db(db)
        _mirror_rejections_after_commit(db, collector)
        try:
            pack_path = write_error_pack(
                db, state, exc=exc, extracted=None,
                resolve_ctx=db.get_resolve_context(state.turn),
            )
        except Exception as pack_exc:
            raise exc from pack_exc
        raise SettlementAbort(
            settlement_abort_message(pack_path), turn=state.turn,
            stage="promulgation", error_pack_path=pack_path,
        ) from exc

    verdict_by_id = {
        int(row["dossier_id"]): str(row.get("decision") or "")
        for row in verdict_rows
    }
    simulation_visible_dossiers = [
        {
            **(
                {
                    key: value for key, value in row.items()
                    if key != "promulgation_decision"
                }
                if int(row["id"]) in verdict_by_id else row
            ),
            **(
                {"settlement_verdict": verdict_by_id[int(row["id"])]}
                if int(row["id"]) in verdict_by_id else {}
            ),
        }
        for row in db.list_decree_dossiers_for_simulation(state.turn)
    ]
    dossier_payload = project_dossiers_for_simulator(
        simulation_visible_dossiers, db=db, state=state,
    )
    current_decree_ids = set(verdict_by_id)
    current_decree_ids.update(
        db.executable_decree_dossier_ids(simulation_visible_dossiers)
    )
    executable_decree_text = "\n".join(
        str(row.get("decree_text") or "").strip()
        for row in dossier_payload
        if int(row["id"]) in current_decree_ids
        and str(row.get("decree_text") or "").strip()
    )

    # 1.8) 历史脉络：取近几回合章节记忆注入推演（章节记忆取代旧的关键词原子检索）。
    relevant_memories: List[Dict] = []
    secret_orders_for_sim: Dict[str, list] = {}  # try 外初始化：检索失败也不能让后续 NameError
    try:
        _emit("stage", "回顾近来朝局")
        # state.turn 此刻仍是本回合（尚未 next_period），章节记忆存的是 turn-1 及更早的已结算回合。
        relevant_memories = db.list_chapter_memories(upto_turn=state.turn, recent=6)
        tlog(f"[memory/chapters] inject={len(relevant_memories)} upto_turn={state.turn}")
    except Exception as exc:
        tlog(f"[memory/chapters] 失败，跳过：{exc}")

    # 密令期限到期送核议已挪进 pre_settle 事务（ADR 0008 S4）——此处不再单独调用，
    # 否则二次写在 pre_settle 提交后散落事务外。下面只读注入推演（含 pending_review）。

    # 密令注入推演：active + pending_review 都要进（pending_review 需推演本月核议判 done/failed）
    try:
        active_orders = _select_secret_orders_for_sim(db)  # pending_review 全进，不被 active 饿死（#108）
        # 分组承载、剥英文 status：simulator/extractor 收到的密令零英文 enum（#48）。
        secret_orders_for_sim = group_secret_orders_for_sim(active_orders)
        secret_orders_for_sim = augment_secret_orders_with_due_commitments(secret_orders_for_sim, db, state)
        n_active = len(secret_orders_for_sim["在办"])
        n_pending = len(secret_orders_for_sim["待核议"])
        tlog(f"[secret_order] 注入推演 在办={n_active} 待核议={n_pending}"
             + (f" titles={[o['title'] for o in active_orders]}" if active_orders else ""))
    except Exception as exc:
        tlog(f"[secret_order] 注入失败，跳过：{exc}")

    # 2) 推演 agent: 写邸报
    tlog("结算 2/4 推演 agent（月末邸报）")
    _emit("stage", "推演月末邸报")
    previous_narrative = db.previous_turn_summary(state) or ""
    simulator_payload = build_simulator_payload(
        state, db, executable_decree_text, previous_narrative,
        deaths_this_turn=deaths_this_turn,
        debuts_this_turn=debuts_this_turn,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders_for_sim,
        decree_dossiers=dossier_payload,
    )
    simulator_payload["dossier_verdicts"] = verdict_rows
    simulator_payload["promulgation_instruction"] = (
        "颁布判决是硬约束：可演新旨意以 decree_dossiers 为权威；"
        "dossier_verdicts 承载本月判决（含打回）。"
        "纯打回未颁（verdict decision=rejected 且未入 decree_dossiers）"
        "只在 dossier_verdicts；严禁写成已办成、已生效、已到任或银已出库，"
        "只据 verdict 字段写封驳／等待批红，不得假定案卷列表有其全文。"
        "列表内 decision 为「打回」且 status 为 promulgated／executing"
        "乃强颁组合态（颁布格留打回本值、案已入办）：按已颁／在途演，"
        "确已落地可标已办成，禁写成封驳待批红；识别以 decision+status 为准，"
        "勿单靠 stigma 是否含强颁。顺颁与上述入列表者均可进入本月办理。"
        "decree_text 仅为兼容摘要，不得覆盖案卷列表与判决。"
    )
    simulator = create_season_simulator_agent(
        llm_config, agno_db, state=state, db=db, simulator_payload=simulator_payload
    )
    try:
        narrative, simulator_payload = simulate_season_with_payload(
            simulator, state, db, executable_decree_text, previous_narrative,
            deaths_this_turn=deaths_this_turn,
            debuts_this_turn=debuts_this_turn,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
            simulator_payload=simulator_payload,
            on_thinking=lambda c: _emit("thinking", c),
            on_text=lambda c: _emit("text", c),
        )
    except Exception as exc:
        print(f"[WARN] 推演 agent 失败：{exc}；本{TURN_UNIT}用简化邸报兜底，继续正常抽取结算。")
        narrative = (
            f"奉天承运皇帝诏曰：本{TURN_UNIT}推演 agent 被服务方拦截，无完整邸报。"
            f"已颁诏书：\n{executable_decree_text}\n"
            f"固定收支已落账，事项 inertia 自然漂移；本{TURN_UNIT}无新立 issue。"
        )
        rescript_decisions = _rescript_decisions(verdict_rows, proposed_dossiers)
        if rescript_decisions:
            with atomic_and_reload(db, state, content=content, registry=registry):
                db.save_resolve_context(
                    state.turn, decree_text, narrative, simulator_payload,
                    secret_orders=secret_orders_for_sim,
                    relevant_memories=relevant_memories,
                    source=Provenance(source).value,
                )
                db.save_pending_decisions(state.turn, rescript_decisions)
                state.turn_phase = TurnPhase.AWAITING_DECISION.value
                db.save_state(state)
            return ResolveResult(
                awaiting=True,
                decisions=db.list_pending_decisions(state.turn),
            )
        # Fallback only replaces the unavailable narrative.  Extraction,
        # private-context merge, durable resolve context, and atomic settlement
        # remain on the normal single rail; a missing required report therefore
        # raises SettlementAbort and leaves the turn unadvanced.
        report = _settle_after_narrative(
            state, db, agno_db, llm_config, decree_text, narrative,
            simulator_payload=simulator_payload,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
            before_turn=before_turn, _emit=_emit,
            content=content, registry=registry,
            cheat_directive=cheat_directive,
            source=source,
            dossier_verdicts=verdict_rows,
        )
        return ResolveResult(awaiting=False, report=report)

    # 2.4) HITL 决策点：从邸报抽 <<DECISION>> 块。有 → 存上下文+决策点，暂停等皇帝亲裁。
    #      剥离后的干净邸报落库/展示；决策点选完由 resolve_decisions_phase2 续跑结算。
    narrative, decisions = parse_decision_blocks(narrative)
    decisions = _rescript_decisions(verdict_rows, proposed_dossiers) + (
        bind_decisions_to_candidate_events(decisions, simulator_payload)
    )
    if decisions:
        tlog(f"[HITL] 检测到 {len(decisions)} 个决策点，暂停等皇帝亲裁：{[d['title'] for d in decisions]}")
        # 暂停态三件（上下文+决策点+AWAITING 相位）同事务落库（cmr S4 r2）：相位若靠
        # session 事后另笔写，崩在窗口里 DB 停在 settling 而决策已存——web submit_decisions
        # 只认 AWAITING 相位，恢复死路。session 事后那笔写变为幂等。
        # 五个事务块同款（ADR 决定 3）：回滚后内存与 DB 同源——不 reload 的话内存留
        # awaiting/DB 回滚回 settling，进程内重试走 awaiting 幂等叉读空决策=死胡同
        # （ship-pre r2）。嵌套时跳过，最外层拥有者处理。见 atomic_and_reload。
        with atomic_and_reload(db, state, content=content, registry=registry):
            db.save_resolve_context(
                state.turn, decree_text, narrative, simulator_payload,
                secret_orders=secret_orders_for_sim, relevant_memories=relevant_memories,
                source=Provenance(source).value,  # #146 A：HITL 暂停存触发源（默认 player），phase2 续跑/崩溃恢复继承。Provenance(source).value 归一(兼容 enum/合法值串)、与 persist_resolve_context 一致(gemini R5)
            )
            db.save_pending_decisions(state.turn, decisions)
            state.turn_phase = TurnPhase.AWAITING_DECISION.value
            db.save_state(state)
        return ResolveResult(awaiting=True, decisions=db.list_pending_decisions(state.turn))

    # 无决策点：透明续跑结算（cheat 仍可叠加）。来源贯穿 source 参数（默认 player_decree：皇帝下旨
    # 拒收提示皇帝；恢复 fallthrough 穿透 ctx 真源，system 重跑仍记 system 静默——#146 cmr r2）。
    report = _settle_after_narrative(
        state, db, agno_db, llm_config, decree_text, narrative,
        simulator_payload=simulator_payload,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders_for_sim,
        before_turn=before_turn, _emit=_emit,
        content=content, registry=registry,
        cheat_directive=cheat_directive,
        source=source,
        dossier_verdicts=(
            simulator_payload.get("dossier_verdicts")
            if isinstance(simulator_payload, dict) else None
        ),
    )
    return ResolveResult(awaiting=False, report=report)


def _provenance_from_stored(value: object) -> Provenance:
    """从 ctx 持久值还原 Provenance（#146 恢复路）：兼容 Provenance 实例、已存的字符串值、
    历史误序列化的 'Provenance.<name>' 字面串、及非法/缺失值。非法/缺失回落 system_simulation。

    防静默丢源（Sourcery + gemini + coderabbit #175 concur）：Provenance 是 (str, Enum)，
    若曾把枚举实例 str() 落库会得到 'Provenance.player_decree'（而非值 'player_decree'），
    Provenance(...) 不匹配 → ValueError → 丢源退回 system_simulation。故分三层：
    ① 实例直接返回；② 纯值走 Provenance(value)；③ 'Provenance.<name>' 旧脏串剥前缀按成员名查回；
    仍无法识别才回落 system_simulation。"""
    if isinstance(value, Provenance):
        return value
    text = str(value or "system_simulation")
    try:
        return Provenance(text)
    except ValueError:
        pass
    # 历史误序列化：str(枚举实例) 落库的 'Provenance.player_decree' 脏串——剥前缀按成员名查回，
    # 不让旧档玩家来源静默退化成 system_simulation。
    if text.startswith("Provenance."):
        try:
            return Provenance[text.split(".", 1)[1]]
        except KeyError:
            pass
    return Provenance.system_simulation


def resolve_settling_recovery(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    ctx: Dict[str, object],
    *,
    on_event: Optional[Callable[[str, str], None]] = None,
    content=None,
    registry=None,
) -> ResolveResult:
    """ADR 0008 S7（决定 3）：settling 态崩溃恢复的「直入 apply」——ready context 已带
    extractor delta，不重跑贵的 simulator/extractor，直接调 settle_with_delta 后半段。

    ctx = db.get_resolve_context(before_turn)，要求 ctx["extracted"] is not None（ready）。
    跨进程恢复无原 extractor_input（那些在崩溃进程的易失内存里）；turn_extractions 的
    extractor_output 会由 applied 结果重建。章节记忆/结局总评是便宜调用，
    按真实流程同款构造（决定 3/4 明示重调可接受）。pre_settle 的 settling 相位已提交，恢复路
    不重跑前半段（财政不二跑）。
    """
    def _emit(kind: str, data: str) -> None:
        if on_event:
            on_event(kind, data)

    extracted = ctx["extracted"]
    if not isinstance(extracted, dict):
        # 不应到此（调用方已判 ready）；防御性响亮，免把 None/坏值喂进 settle。
        raise LLMContractError("恢复直入 apply 要求 ctx 带 ready 的 extractor delta。")
    before_turn = state.turn
    decree_text = str(ctx.get("decree_text") or "")
    narrative = str(ctx.get("narrative") or "")
    # 恢复重放沿用持久化的原始拒收来源（#144）：玩家来源(player_decree/hitl)拒收恢复后仍给玩家
    # 邸报提示，不被记成 system_simulation 而静默。非法/缺失值回落 system_simulation（旧档兼容）。
    source = _provenance_from_stored(ctx.get("source"))
    # 暂存动作 commit 已下沉进 settle_with_delta 的 atomic 体内（与结算同生死，
    # cmr S7 r4）——此处不再事务外预 commit。
    try:
        report = _replay_settle(
            state, db, agno_db, llm_config, extracted,
            before_turn=before_turn, decree_text=decree_text, narrative=narrative,
            simulator_payload=ctx.get("simulator_payload"),
            dossier_rescript_actions=_chosen_rescript_actions(
                db.list_pending_decisions(state.turn)
            ),
            content=content, registry=registry, _emit=_emit, source=source,
        )
    except SettlementAbort as abort_exc:
        # First failure keeps the ready context for an ordinary atomic retry.
        # A repeated failure of that same ready payload may downgrade only after
        # both attempts have produced ADR0008 error packs.  If pack creation
        # failed, no matching directories exist and the evidence is preserved.
        packed_attempts = complete_error_packs_for_ready(db.path, before_turn, extracted)
        if len(packed_attempts) >= 2:
            try:
                clear_for_resimulation(db, before_turn)
            except Exception as clear_exc:
                raise abort_exc from clear_exc
        raise
    return ResolveResult(awaiting=False, report=report)


def _replay_settle(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    extracted: Dict[str, object],
    *,
    before_turn: int,
    decree_text: str,
    narrative: str,
    simulator_payload: object = None,
    dossier_rescript_actions: Optional[List[Dict[str, object]]] = None,
    content=None,
    registry=None,
    _emit: Callable[[str, str], None],
    source: Provenance = Provenance.system_simulation,
) -> str:
    report = settle_with_delta(
        state,
        db,
        extracted,
        before_turn=before_turn,
        content=content,
        registry=registry,
        decree_text=decree_text,
        narrative=narrative,
        extractor_output="[恢复重灌] 从 resolve_context 直入 apply（未重跑 extractor）。",
        chapter_recorder=lambda d, s, dt, nr, ap: record_chapter_memory(
            create_chapter_memory_agent(llm_config, agno_db), d, s, dt, nr, ap
        ),
        ending_summarizer=lambda d, s, oc: _generate_ending_summary(
            d, s, llm_config, agno_db, oc, _emit
        ),
        delta_applier=lambda d, s, ex, ct, rg: apply_score_extraction(
            d, s, ex, content=ct, registry=rg, llm_config=llm_config,
            candidate_event_ids_at_input=_candidate_event_ids_from_simulator_payload(simulator_payload),
            dossier_ids_at_input=_dossier_ids_from_simulator_payload(simulator_payload),
        ),
        on_stage=lambda label: _emit("stage", label),
        source=source,  # 恢复重放沿用原始来源（#144）：玩家来源拒收恢复后仍给提示，不被记成 system
        dossier_verdicts=(
            simulator_payload.get("dossier_verdicts")
            if isinstance(simulator_payload, dict) else None
        ),
        dossier_rescript_actions=dossier_rescript_actions,
    )
    return report


def _mirror_rejections_after_commit(db: GameDB, collector: RejectionCollector) -> None:
    """Mirror flushed rejection rows only after the owning transaction commits.

    validate-layer collectors in persist_resolve_context may run under an outer
    atomic owner (driver.run_settle). In that case the local collector would go
    out of scope before _atomic_depth returns to 0, so register a post-commit
    callback on the shared connection instead of mirroring early.
    """
    def _mirror() -> None:
        try:
            collector.mirror_to_jsonl(rejections_jsonl_path())
        except Exception as mirror_exc:
            tlog(f"[rejection] jsonl 镜像失败（DB 行已落，仅副本丢失）：{mirror_exc}")

    if getattr(db.conn, "_atomic_depth", 0) == 0:
        _mirror()
        return
    callbacks = getattr(db.conn, "_runtime_commit_callbacks", None)
    if callbacks is None:
        callbacks = []
        db.conn._runtime_commit_callbacks = callbacks
    callbacks.append(_mirror)


def persist_resolve_context(
    db: GameDB,
    turn: int,
    extracted: Dict[str, object],
    *,
    decree_text: str,
    narrative: str,
    simulator_payload: Dict[str, object],
    secret_orders: Dict[str, object],
    relevant_memories: List[Dict],
    source: Provenance = Provenance.system_simulation,
) -> Dict[str, object]:
    """ADR 0008 S2：每回合进入结算后半段前无条件持久化 resolve_context（extractor delta + 叙事）。

    source（#144）：拒收 provenance 一并持久化，崩溃恢复重放（resolve_settling_recovery）据此还原
    原始来源——否则玩家来源(player_decree/hitl)拒收被恢复路记成 system_simulation、静默不提示。

    重跑真源：跨进程恢复从此重灌，不重跑贵的 simulator/extractor。
    **持久化前先过 validate_delta_shape**——形状畸形的 delta 绝不入 resolve_context
    （否则钉进重试真源：apply 永崩、而「重跑 extractor」被「context 已存在」挡死=soft-lock）。
    校验失败响亮抛 ValueError，save 不执行。注意此门只挡形状毒：shape 合法但值级
    必炸的 payload（如 new_armies 项里非数值兵力）由 ADR 0008 决定 6 的「重新推演」
    逃生口兜底（清 context 重产 delta），S4 恢复入口不得假设 ready=1 即重放安全。
    """
    cleaned, rejections = sanitize_delta_shape(extracted)
    validate_delta_shape(cleaned)  # sanitized ready context must itself satisfy the shape gate
    try:
        attempt = _next_attempt(turn)
    except Exception:
        attempt = 1
    collector = RejectionCollector(attempt=attempt)
    with atomic(db):
        for section, item, reason in rejections:
            collector.record(
                section,
                RejectedItem(
                    item=item,
                    reason=reason,
                    category="invalid_shape",
                    source=Provenance(source),
                ),
                turn,
            )
        collector.flush_to_db(db)
        db.save_resolve_context(
            turn, decree_text, narrative, simulator_payload,
            secret_orders=secret_orders, relevant_memories=relevant_memories,
            extracted=cleaned, source=Provenance(source).value,
        )
    _mirror_rejections_after_commit(db, collector)
    return cleaned


def _settle_after_narrative(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    decree_text: str,
    narrative: str,
    simulator_payload: Dict[str, object],
    relevant_memories: List[Dict],
    secret_orders: Dict[str, object],
    before_turn: int,
    _emit: Callable[[str, str], None],
    content=None,
    registry=None,
    cheat_directive: str = "",
    decision_directive: str = "",
    source: Provenance = Provenance.system_simulation,
    dossier_verdicts: Optional[List[Dict[str, object]]] = None,
    dossier_rescript_actions: Optional[List[Dict[str, object]]] = None,
) -> str:
    """phase2：邸报已定（已剥离决策块），跑 extractor→落库→章节记忆→结局→推进。
    cheat_directive / decision_directive 各自拼到 effective_narrative 最前喂 extractor。
    source（#146 A，整批按触发源）：本批 extractor 产出的来源——皇帝下旨触发=player_decree
    （拒收给皇帝可见提示）、无旨/世界自演变=system_simulation（静默）。重抽路从 ctx['source']
    贯穿、不因重抽改变（用户拍：皇帝原旨没变、来源就没变）。"""
    secret_orders_for_sim = secret_orders
    # 2.5) 作弊强制项 + 圣意亲裁：拼到邸报最前面一起喂 extractor（唯一入口）。
    #      落库前文/turn_report 仍用原始 narrative，effective 版只进 extractor 与留痕。
    effective_narrative = narrative
    decision = (decision_directive or "").strip()
    if decision:
        effective_narrative = DECISION_NARRATIVE_PREFIX + decision + "\n\n" + effective_narrative
        tlog(f"[HITL] 圣意亲裁注入 extractor（{len(decision)}字）：{decision[:200]}")
    cheat = (cheat_directive or "").strip()
    if cheat:
        effective_narrative = CHEAT_NARRATIVE_PREFIX + cheat + "\n\n" + effective_narrative
        tlog(f"[CHEAT] 强制结算项注入 extractor（{len(cheat)}字）：{cheat[:200]}")

    # 3) 结算 agent: 读邸报抽 JSON
    tlog("结算 3/4 结算 agent（抽 JSON）")
    _emit("stage", "数值推演结算")
    # simulator_payload 的 decree_text 已在 phase1 收敛为本批可执行诏文；extractor
    # 必须复用同一授权输入，不能重新接回包含封驳案卷的原始聚合文本。
    executable_decree_text = str(simulator_payload.get("decree_text") or "")
    # #883: per-module supplemental context so only personnel_secret receives
    # secret-order prose; other public extractors never pre-read it.
    extractor_shared_contexts = {
        module: build_extractor_shared_context(
            db, state, effective_narrative, executable_decree_text,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
            module=module,
            decree_dossiers=(
                simulator_payload.get("decree_dossiers")
                if isinstance(simulator_payload.get("decree_dossiers"), list)
                else []
            ),
        )
        for module in EXTRACTION_MODULES
    }
    sanitizer = create_json_sanitizer_agent(llm_config, agno_db)
    extractor_input = ""
    extractor_output = ""
    try:
        tlog("结算 3/4 抽取（模块 module）")
        extractors = {
            module: create_score_extractor_module_agent(
                llm_config,
                agno_db,
                module,
                simulator_payload=simulator_payload,
                supplemental_context=extractor_shared_contexts[module],
            )
            for module in EXTRACTION_MODULES
        }
        # 仅并发安全的 CLI runner（codex，--ephemeral 隔离）下并发跑 4 个 extractor（#83，省约 1 分钟）；
        # claude/agy/api/形态1 → cli_backend_parallel_safe=False → 串行不变。合并/落库仍串行单事务（ADR 0008）。
        extracted, extractor_output, extractor_input = extract_scores_by_modules_with_agno(
            extractors, db, state, effective_narrative, decree_text=executable_decree_text, sanitizer=sanitizer,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
            parallel=cli_backend_parallel_safe(llm_config),
        )
        # 拆不出 section 的 extractor 产物（顶层非 dict / 未知顶层 key）仍属 extractor 失败：
        # 在 try 内验形，让它走 pack+SettlementAbort 路。ADR0015 下可拆 section/list/entity
        # 坏项不在这里 abort；persist_resolve_context 会逐项净化并留痕后二次校验净化版。
        validate_delta_shape(extracted)
    except Exception as exc:
        # ADR 0008 决定 3/6（S6）：extractor 失败响亮中止——不再 extracted={} 静默续跑
        # （整月 delta 蒸发而回合照推=最毒半落库点，本 ADR 立项动机）。此分支在 settle_with_delta
        # 的 atomic 之外（resolve_context 也只有真成功才 persist），中止后 LLM 产出本未持久化，
        # 重试=重跑 simulator/extractor（决定 3 明示唯一选择且可接受）；pre_settle 的 settling
        # 相位已提交，重进被守门跳过前半段直接重推演。错误包在 atomic 外写（backup_to 拒绝事务内备份）。
        try:
            pack_path = write_error_pack(
                db, state, exc=exc, extracted=None,
                resolve_ctx=db.get_resolve_context(before_turn),
            )
        except Exception as pack_exc:
            # 写包自身炸（磁盘满/路径不可写）不得顶替原 extractor 异常（同 pre_settle
            # reload 先例 raise exc from ...）：原异常是真因，写包失败是次生。
            # 只捕 Exception：写包期间（conn.backup 最慢步）落 Ctrl-C/SystemExit 须原样
            # 传播，降级成普通结算错误会被上游 except Exception 吞掉继续跑（cmr S6 r1）。
            raise exc from pack_exc
        raise SettlementAbort(
            settlement_abort_message(pack_path),
            turn=before_turn, stage="extract", error_pack_path=pack_path,
        ) from exc

    # ADR 0008 S2：进入结算后半段（settle_with_delta 动 DB）前，持久化 resolve_context
    # （extractor delta + 叙事）作重跑真源——跨进程恢复从它重灌，不重跑贵的 simulator/extractor。
    # ADR0015：持久化会先把可拆坏项逐项拒收留痕、仅把净化版写入 resolve_context；
    # 净化版再过 validate_delta_shape，防毒 payload 钉进重试真源。
    # before_turn == state.turn（next_period 尚未执行），与 settle 内 clear 同键。
    # 走到这里 = extractor 至少可拆 section（不可拆失败已在上方响亮中止）。
    extracted = persist_resolve_context(
        db, before_turn, extracted,
        decree_text=decree_text, narrative=narrative,
        simulator_payload=simulator_payload,
        secret_orders=secret_orders_for_sim,
        relevant_memories=relevant_memories,
        source=source,  # #146 A：来源贯穿进 ctx，崩溃恢复重抽从 ctx['source'] 继承、不丢
    )

    # 后括号确定性结算核：与探针 driver 共用同一段（ADR 0004）。章节记忆 / 结局总评
    # 作为注入回调传入（真实流程= LLM agent 闭包；driver= None 跳过）。
    return settle_with_delta(
        state,
        db,
        extracted,
        before_turn=before_turn,
        content=content,
        registry=registry,
        decree_text=decree_text,
        narrative=narrative,
        trace_narrative=effective_narrative,
        extractor_input=extractor_input,
        extractor_output=extractor_output,
        chapter_recorder=lambda d, s, dt, nr, ap: record_chapter_memory(
            create_chapter_memory_agent(llm_config, agno_db), d, s, dt, nr, ap
        ),
        ending_summarizer=lambda d, s, oc: _generate_ending_summary(
            d, s, llm_config, agno_db, oc, _emit
        ),
        # 落库走捕获 llm_config 的闭包：issue/office 的通道感知 enrichment 才能按 active
        # channel 选后端（cli_backend_active(llm_config)）；结算核本体仍不见 llm_config。
        delta_applier=lambda d, s, ex, ct, rg: apply_score_extraction(
            d, s, ex, content=ct, registry=rg, llm_config=llm_config,
            candidate_event_ids_at_input=_candidate_event_ids_from_simulator_payload(simulator_payload),
            dossier_ids_at_input=_dossier_ids_from_simulator_payload(simulator_payload),
        ),
        on_stage=lambda label: _emit("stage", label),
        # 来源贯穿（#146 A，整批按触发源）：皇帝下旨触发=player_decree（拒收提示皇帝）、
        # 无旨/世界自演变=system_simulation（静默）。重抽路从 ctx['source'] 继承、不因重抽改变。
        source=source,
        dossier_verdicts=dossier_verdicts,
        dossier_rescript_actions=dossier_rescript_actions,
    )


# 同源恢复刷新的标量字段（与 db.load_state 读盘列对齐）。metrics 单独深刷。
_RELOAD_SCALAR_FIELDS = ("year", "period", "turn", "turn_phase", "ended", "ending_status")


def reload_state_from_db(db: GameDB, state: GameState, *, content=None, registry=None) -> GameState:
    """回滚后把内存 state 从 DB 原地刷新（ADR 0008 决定 3 第三条）。

    DB 回滚只回 SQLite，Python 对象留脏（state.metrics 直加 flows.py:192、turn_phase、
    next_period 的 turn/year/period）。事务期内正常写内存——回滚后须把这些副作用按 DB 真相
    刷掉，否则脏内存会污染重跑（如脏 settling 相位被守门跳过=整月财政丢，cmr S4 r1 F4）。

    走 db.load_state 同路径（与 restore 同源），但 load_state 返回**新对象**；state 被各处
    持引用（session.state、driver 闭包、各调用栈），必须**原地刷新**而非返回新对象——把 DB 值
    写回同一对象的字段、metrics dict 原地 update-then-prune（任何时刻非空），返回同一 state（id 不变）。

    content 非 None 时以 DB 全量重建 characters（restore 同路径 _sync_offices_from_db_impl）：
    既清幽灵（任免 commit 先挂 content 再写 DB，回滚删行留幽灵——重试被误拒，cmr S5 r1
    codex trace），也刷掉存量人物的脏属性（罢免/调任/顶替改的 status/office/office_type
    随 DB 回滚必须同源还原，cmr S5 r2 双家共识）。
    registry 重建依赖 GameSession 重型协作者，decree 层拿不全；被清条目对应的 registry
    agent 若存在会成悬挂引用，本层无清理接口（限制：session 级重载后续接线时处理）。

    嵌套 atomic 内禁止 reload：depth>0 时 rollback 尚未发生（flat 语义，最外层才回滚），
    load_state 同连接会读到未提交脏写——把脏数据当真相刷进 state（cmr S5 r1 claude）。
    """
    if getattr(db.conn, "_atomic_depth", 0) > 0:
        raise RuntimeError(
            "reload_state_from_db 在 atomic 事务内禁止：回滚尚未发生，会把未提交脏写"
            "当 DB 真相刷进内存。最外层 atomic 拥有者负责真回滚后再 reload。"
        )
    fresh = db.load_state()
    for field_name in _RELOAD_SCALAR_FIELDS:
        setattr(state, field_name, getattr(fresh, field_name))
    # metrics 原地刷，update-then-prune：任何时刻 dict 非空（Ctrl-C 落在中间也不会
    # 留全空 metrics，cmr S5 r1）、同一 dict 对象（持引用方继续读同一引用）。
    state.metrics.update(fresh.metrics)
    for key in [k for k in state.metrics if k not in fresh.metrics]:
        del state.metrics[key]
    if content is not None:
        # lazy import：session 顶层 import decree，反向只能函数内取（同 db.py 先例）。
        from ming_sim.session import _sync_offices_from_db_impl
        # llm_config 必传（restore 各调用点同款）：缺省 None 会让 LLM 自创官职的
        # office_type 推断降级成「待铨」，reload 后内存又与 DB 分叉（cmr S5 r3 双家）。
        _sync_offices_from_db_impl(content, db, getattr(db, "llm_config", None))
    return state


class _AtomicOutcome:
    """atomic_and_reload yield 出的结果句柄（cmr PR2 R1 sourcery）：取代把
    `_reload_failed` 动态属性挂到任意 BaseException 上（slotted/复用异常时脆弱）。
    专用对象、固定字段——settle 用 `as` 接、外层 except 读 `.reload_failed`。"""
    __slots__ = ("reload_failed",)

    def __init__(self) -> None:
        self.reload_failed = False


@contextmanager
def atomic_and_reload(
    db: GameDB,
    state: GameState,
    *,
    content=None,
    registry=None,
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> "Iterator[_AtomicOutcome]":
    """`with atomic(db)` + 「最外层异常回滚后从 DB 重载内存」的公共内核（ADR 0008 S4）。

    抽自结算管线 ~6 处同款 try/atomic/except-reload-reraise（pre_settle / settle_with_delta /
    advance_without_edict / resolve_directives 前括号 + fallback + HITL 暂停三件 + driver.run_settle）。

    语义（逐处保真）：
    - body 包进 `with atomic(db)`，正常退出由 atomic 统一提交（嵌套时由最外层落定）。
    - body 抛 BaseException 时：先（若有）调 on_error(exc)，再仅当 `_atomic_depth==0`（本层
      即最外层、atomic 已真回滚）调 reload_state_from_db 把脏内存按 DB 刷净；嵌套（depth>0）
      跳过 reload（回滚尚未发生，load_state 会读未提交脏写）。reload 自身再炸不顶替原异常，
      链上抛 `raise exc from reload_exc`。最后原样 re-raise 原异常（fail-loud，ADR 0005）。

    on_error 在 reload 之前触发（settle_with_delta 的 collector.reset 语义：DB 行随回滚消失，
    内存缓冲须同步清场）。settle 的中断透传 / 错误包 / SettlementAbort 包装等**特殊** except
    逻辑不属公共内核，仍由调用方在本助手之外的外层 try/except 处理。
    """
    outcome = _AtomicOutcome()
    try:
        with atomic(db):
            yield outcome
    except BaseException as exc:
        if on_error is not None:
            on_error(exc)
        if getattr(db.conn, "_atomic_depth", 0) == 0:
            try:
                reload_state_from_db(db, state, content=content, registry=registry)
            except BaseException as reload_exc:
                # reload 失败标记落在专用句柄上（不挂异常属性）：settle 的外层 except
                # 凭 `as` 句柄裸传播原异常,不包 SettlementAbort 不写错误包（内存仍脏时
                # 宣传可重试/基于脏态写包都是误导;b12a60e 原语义保真,cmr S4 r1）。
                outcome.reload_failed = True
                raise exc from reload_exc
        raise


def force_transit_arrivals(
    db: GameDB,
    state: GameState,
    content=None,
    *,
    commit: bool = True,
) -> List[Dict[str, object]]:
    """确定性在途兜底：在途 ≥2 回合（或旧数据 transit_start_turn=0）→ 强制到任。

    ADR 0009 决策 5 明确靠叙事自然到任（行止+location）；本函数为兜底——simulator 未能
    在 2 个月内产到任叙事时，程序强制 transit_to→location、清 transit_to。
    旧数据 transit_start_turn=0 视为「启程时间未知，按超期处理」。
    返回被强制到任的人物列表（[{"name": ..., "location": ...}, ...]）。

    commit=False 时不提交——由外层事务（如 pre_settle 的 atomic_and_reload）统一提交，
    确保不提前截断外层事务、破坏回滚原子性（P1 issue: inner commit() inside atomic block）。
    """
    current_turn = state.turn
    overdue = db.conn.execute(
        "SELECT name, transit_to FROM characters "
        "WHERE COALESCE(transit_to, '') != '' "
        "AND (transit_start_turn = 0 OR ? - transit_start_turn >= 2)",
        (current_turn,),
    ).fetchall()
    if not overdue:
        return []
    forced: List[Dict[str, object]] = []
    for row in overdue:
        name = str(row["name"])
        dest = str(row["transit_to"])
        db.conn.execute(
            "UPDATE characters SET location=?, transit_to='', transit_start_turn=0 WHERE name=?",
            (dest, name),
        )
        if content is not None and name in content.characters:
            ch = content.characters[name]
            ch.location = dest
            ch.transit_to = ""
            # 镜像 DB 清掉的行止时钟，保持内存/DB 一致（同回合内存读不到陈旧 start turn）
            if hasattr(ch, "transit_start_turn"):
                ch.transit_start_turn = 0
        forced.append({"name": name, "location": dest})
    if commit:
        db.conn.commit()
    return forced


def pre_settle(
    state: GameState, db: GameDB, *, on_stage=None, content=None, registry=None,
    scene_registry=None,
) -> List[Dict[str, object]]:
    """确定性结算「前括号」：固定月度财政 tick + auto_trigger 硬立 seed 情势，均在 LLM 推演前。

    返回本回合程序硬触发的清单。真实流程与探针 driver 共用此核（ADR 0004）。
    content/registry 供 office(任免)暂存动作落库注册新臣；driver 路径无聊天暂存，传 None 即 no-op。

    ADR 0008 S4：整段（暂存动作 commit + 固定财政 + auto_trigger + 到期密令呈递）包成
    **自己的单事务**——崩在内部=全回滚=相位未变=重进时干净重跑前半段。完成时**同事务内**
    落中间相位 settling（写 state.turn_phase + save_state）：只意味着「前半段已完成，不再
    重跑 pre_settle」，不意味着后半段就绪（恢复入口的消费分流是 S7 的活，本切片只立相位机械）。
    settling 相位用 models.TurnPhase.SETTLING（单一真源已下沉 models，无循环）。settling 已是入口态时直接 return（幂等守门）：
    「不再重跑前半段」正是 settling 的语义，恢复后重进 pre_settle 不二次落财政。

    auto_submit_due_secret_orders（原在 resolve_directives 调用点）挪入本事务：它只是
    「推演前的确定性写」，崩溃时密令呈递须随财政一并回滚；挪入不改它先于 simulator 的事实。
    """
    # 幂等守门：前半段已提交相位（FRONT_HALF_DONE_PHASES 单一真源）重进不重跑财政
    # （防二次 tick，cmr S4 r2/r3）。早退**不消费**暂存动作。所有权规则（cmr S7 r5/r6）：
    # ① 正常路=pre_settle 前半段事务内 commit（下方正常体）——ADR 0006 要求推演前盘面
    #   已定，动作必须先于 simulator 提交；extractor 后炸时前半段保持已落是 ADR 决定 2
    #   明文设计（「pre_settle 的效果在中止/重试时保持已落，这是设计而非缺陷」），非半写。
    # ② 前半段已提交后（本守门内）新 stage 的动作=推进回合的终端写路
    #   （settle_with_delta / advance_without_edict / fallback）各自在 atomic 内 commit；
    #   早退路在事务外 commit 会让重推演路上 extractor 再炸时动作已提交而回合未推进。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        return []
    auto_triggered: List[Dict[str, object]] = []
    # #498：颁诏遇开夜 → 顺势自动收夜（王承恩代宣）；在飞回话 fail-closed 中止，不进 settling。
    # 放在 atomic 外：收夜提交与错误包独立；成功后 pre_settle 事务内 commit_pending 仍幂等。
    # #503：收夜 beat 生产路径接通编排缝。
    from ming_sim.audience_night import auto_close_open_night
    from ming_sim.beat_orchestration import create_llm_beat_generator
    effective_llm = getattr(db, "llm_config", None)
    # No usable config → skip adapter construction (probe/engine often pass bare GameDB).
    beat_generator = (
        create_llm_beat_generator(effective_llm) if effective_llm is not None else None
    )
    # #542：调用方既有 ChatTurnSceneRegistry（session._scene_registry）；不在此新建。
    auto_close_open_night(db, state, content=content, registry=registry,
                          beat_generator=beat_generator,
                          scene_registry=scene_registry)
    # atomic + 最外层回滚后从 DB 重载（ADR 0008 决定 3 第三条）：apply_fixed_period_flows 直改了
    # state.metrics（flows.py:192）、尾部 turn_phase 已被赋 settling，脏 settling 会被下次 pre_settle
    # 守门跳过=该月财政永久丢（cmr S4 r1 F4）。嵌套时跳过 reload，由最外层拥有者处理。见 atomic_and_reload。
    try:
        with atomic_and_reload(db, state, content=content, registry=registry):
            # 动作闸门(ADR 0006)：颁诏最前批量落库本回合暂存的结构化聊天写动作（密令更新/催办/任免/…），
            # 在跑 LLM 结算管线前，使 simulator/extractor 读到的盘面与旧「召对期直写」时序一致。
            # driver 路径无聊天暂存 → 空 no-op。幂等（committed 行不重跑）。
            committed = db.commit_pending_actions(state, content=content, registry=registry)
            if committed:
                tlog(f"[pending_actions] 颁诏批量落库 {len(committed)} 条：{[(c['kind'], c['action']) for c in committed]}")
            fiscal_levies = apply_historical_fiscal_rates(state, db, commit=False)
            if fiscal_levies:
                tlog(
                    f"[fiscal-levy] 本回合饷率事件前置落账 {len(fiscal_levies)} 条："
                    f"{[(t['id'], t.get('terminal_reason') or t['terminal_state']) for t in fiscal_levies]}"
                )
            tlog("结算 1/4 固定月度财政 tick")
            if on_stage is not None:
                on_stage("固定月度财政入账")
            # 落账副作用；明细不再进 simulator payload（欠饷哗变走前置事件/issue）
            apply_fixed_period_flows(db, state)
            # 在途兜底：在途 ≥2 回合（或旧数据 transit_start_turn=0）的人物强制到任，
            # 确保 LLM 漏产到任叙事时不永久在途（ADR 0009 决策5 = 叙事优先；此为代码兜底）。
            # 必须先于 apply_event_terminal_states / auto_trigger_seed_issues：二者按 character.X.location
            # 等门控判事件终态/硬立项，超期在途赴门控地的人物若未先到任，门控读旧 location 不达标 →
            # person-core 事件被误判 avoided 永久作废、兜底形同虚设（CMR r2 P2）。
            forced_arrivals = force_transit_arrivals(db, state, content, commit=False)
            if forced_arrivals:
                tlog(f"[transit-aging] 强制到任 {len(forced_arrivals)} 人：{[f['name'] for f in forced_arrivals]}")
            terminalized = apply_event_terminal_states(state, db, commit=False)
            if terminalized:
                tlog(f"[event_terminal] 本回合事件终态落账 {len(terminalized)} 条：{[(t['id'], t['terminal_state']) for t in terminalized]}")
            # 程序硬触发：标了 auto_trigger 的 seed 情势，gate 达标即由程序直接立项，绕过 LLM 因果判定。
            auto_triggered = auto_trigger_seed_issues(state, db)
            # #625：孤直稽核反制——涌现缝＋逐人硬门读事实底，邸报前同缝立 issue。
            counter_hits = db.trigger_supervision_countermeasures(state, commit=False)
            if counter_hits:
                auto_triggered = list(auto_triggered) + [
                    {
                        "id": item.get("origin_ref"),
                        "title": f"supervision_countermeasure:{item.get('countermeasure_kind')}",
                        "issue_id": item.get("issue_id"),
                        "source": "supervision_countermeasure",
                    }
                    for item in counter_hits
                ]
            # #626：承诺所系反噬——事废/烂尾/变形暴露状态驱动，#625 同格挂点。
            backlash_hits = db.trigger_commitment_backlashes(state, commit=False)
            if backlash_hits:
                auto_triggered = list(auto_triggered) + [
                    {
                        "id": item.get("origin_ref"),
                        "title": f"commitment_backlash:{item.get('source_kind')}",
                        "issue_id": item.get("issue_id"),
                        "source": "commitment_backlash",
                        "trigger_ref": item.get("trigger_ref"),
                    }
                    for item in backlash_hits
                ]
            if auto_triggered:
                tlog(f"[AUTO-TRIGGER] 本回合程序硬立项 {len(auto_triggered)} 条：{[t.get('title') for t in auto_triggered]}")
            # 密令期限：到期 active 自动转 pending_review，保证本月核议一锤定音。
            # 推演前的确定性写，挪入前半段事务（原在 resolve_directives，ADR 0008 S4）。
            due_orders = db.auto_submit_due_secret_orders(state)
            if due_orders:
                tlog(f"[secret_order] 到期送核议 {due_orders}")
            # 完成相位：同事务内落 settling（崩在上面任一步=全回滚=相位未变）。
            state.turn_phase = TurnPhase.SETTLING.value
            db.save_state(state)
    except BaseException as exc:
        raise_fixed_period_flow_abort_if_needed(db, state, exc)
        raise
    return auto_triggered


def settle_with_delta(
    state: GameState,
    db: GameDB,
    extracted: Dict[str, object],
    *,
    before_turn: int,
    content=None,
    registry=None,
    decree_text: str = "",
    narrative: str = "",
    trace_narrative=None,
    extractor_input: str = "",
    extractor_output: str = "",
    chapter_recorder=None,
    ending_summarizer=None,
    delta_applier=None,
    on_stage=None,
    source: Provenance = Provenance.unknown,
    dossier_verdicts: Optional[List[Dict[str, object]]] = None,
    dossier_rescript_actions: Optional[List[Dict[str, object]]] = None,
) -> str:
    """确定性结算「后括号」：apply→turn_logs→inertia→留痕→章节记忆→clear→结局判定→next_period。

    收一份**已规范化**的 extracted（英文 canonical key，见 simulation._canonicalize_extraction）。
    不依赖 llm_config —— 章节记忆 / 结局总评 / 落库 enrichment 全经注入闭包：
    章节记忆=chapter_recorder、结局总评=ending_summarizer、落库（含 issue/office 的
    通道感知 enrichment）=delta_applier。真实流程传捕获 llm_config 的闭包；探针 driver 对
    chapter_recorder/ending_summarizer 传 None（不产 LLM 叙事），对 delta_applier 传一个
    **channel=api 确定性配置**的闭包（不走 legacy env enrichment,#54）——无论哪种,结算核
    本体都不见 llm_config（ADR 0004）。返回 full_report 文本。

    delta_applier(db, state, extracted, content, registry) -> applied dict；None 时回退到
    `apply_score_extraction(llm_config=None)`——**不注入运行时通道**。注意裸 None 分支不等于
    「绝对无 LLM」：apply_score_extraction 对 llm_config=None 仍按旧 env 后端判定
    （`cli_backend_active(None)` 回落 `MING_SIM_LLM_BACKEND`），见
    test_settle_none_branch_legacy_env_enriches。**探针 driver 已不走此裸 None 分支**——它注入
    channel=api 的确定性 applier,无论 env 都不触发 legacy enrichment（#54，见
    test_driver_run_settle_deterministic_under_legacy_env）。
    """
    if trace_narrative is None:
        trace_narrative = narrative

    def _stage(label: str) -> None:
        if on_stage is not None:
            on_stage(label)

    # ADR 0008 S7（决定 2）：整个后半段写序列包进单事务——apply→turn_logs→inertia→留痕→章节记忆
    # →clear→结局→next_period 全有或全无。崩在中途（含 save_state 之后、clear 之前那个
    # 「已提交但 context 残留」的崩溃窗口，S2+S3 codex R2 defer 至此）则整体回滚，turn 不推进、
    # resolve_context 仍在可重试。回滚后内存从 DB 重载（决定 3），再于 atomic 外写错误包并抛
    # SettlementAbort（决定 6）。事务内 LLM 回调（章节记忆/结局总评）失败沿用降级、内部已自吞
    # 不触发回滚（决定 4）——故从 settle 冒出的 Exception 即代码异常，一律走错误包。
    # 拒收收集器与结算事务同生命周期（ADR 决定 5，PR2-S0）：apply 的拒收项在事务内
    # flush 进 rejection_reports（行随回滚消失），commit 成功后才镜像 jsonl（文件 append
    # 不可回滚），异常路 reset 清场。attempt 从错误目录推导——同一回合第 N 次重试的拒收
    # 与第 N 个错误包同号，不从 DB 取（DB 计数随回滚重置即失真）。推导扫的是诊断目录，
    # 自身故障（不可遍历等）不得拖垮主流程：回落 attempt=1（与 mirror 失败同向，cmr S0 r2）。
    try:
        attempt = _next_attempt(before_turn)
    except Exception as attempt_exc:
        tlog(f"[rejection] attempt 推导失败，回落 1（诊断侧路径不拖垮结算）：{attempt_exc}")
        attempt = 1
    collector = RejectionCollector(attempt=attempt)
    # 公共内核（atomic + 最外层回滚后 reload + 链式 reraise）走 atomic_and_reload；
    # on_error 在 reload 前清拒收缓冲（DB 行随回滚消失，内存同步清场，不留待镜像快照）。
    # settle 特有的「中断透传 / 错误包 / SettlementAbort 包装」属特殊路，仍在本助手之外的
    # 外层 try/except 处理（ADR 0008 决定 6）——helper 化内核，特殊路外包。
    # _atomic 预置 None：atomic_and_reload 的 __enter__ 在 yield 前就抛（如 atomic(db)
    # 拒非 _SuspendableConnection、BEGIN 撞锁）时 as 绑定不发生，except 块若裸访问
    # _atomic.reload_failed 会触发 UnboundLocalError 吃掉原始结算异常（cmr S4 三模型收敛）。
    _atomic = None
    try:
        with atomic_and_reload(
            db, state, content=content, registry=registry,
            on_error=lambda _exc: collector.reset(),
        ) as _atomic:
            # 暂存动作 commit 在结算事务内最前（幂等，只处理 pending 行；正常路 pre_settle
            # 已 commit=无操作）——恢复/phase2 重抽路在此获得覆盖，且与结算同生死：
            # 事务外 commit 的话重放炸时结算回滚而动作及其真表副作用留存=跨事务半写
            # （cmr S7 r4，claude+codex 两面同根）。
            db.commit_pending_actions(state, content=content, registry=registry)
            if dossier_verdicts:
                db.apply_dossier_verdicts(
                    state, dossier_verdicts, content=content, registry=registry,
                )
            # Player disposition rows are not Judge verdicts: no affected_parties,
            # no midzhi validator, no apply_dossier_verdicts. Route each chosen
            # rescript action through the existing promulgation seam under this
            # outer atomic batch (ADR 0056 force reads current-turn Judge evidence).
            if dossier_rescript_actions:
                for action in dossier_rescript_actions:
                    db.apply_dossier_promulgation(
                        state,
                        int(action["dossier_id"]),
                        str(action["decision"]),
                        content=content,
                        registry=registry,
                    )
            full_report = _settle_after_extract_body(
                state, db, extracted,
                before_turn=before_turn, content=content, registry=registry,
                decree_text=decree_text, narrative=narrative,
                trace_narrative=trace_narrative,
                extractor_input=extractor_input, extractor_output=extractor_output,
                chapter_recorder=chapter_recorder, ending_summarizer=ending_summarizer,
                delta_applier=delta_applier, _stage=_stage,
                collector=collector, source=source,
            )
    except BaseException as exc:
        # reload 失败（atomic_and_reload 在 yield 句柄上标的,cmr S4 r1）：内存仍脏——
        # 裸传播,不写包不包 SettlementAbort（脏态写包/宣传可重试都是误导;b12a60e 原语义）。
        if _atomic is not None and _atomic.reload_failed:
            raise
        # 中断/降级类异常（KeyboardInterrupt/SystemExit/LLMUnavailable）不当代码异常处理：
        # 不写包、不二次包装，原样传播。SettlementAbort（理论上 settle 内不抛）也不二次包。
        if isinstance(exc, (KeyboardInterrupt, SystemExit, LLMUnavailable, SettlementAbort)):
            raise
        if not isinstance(exc, Exception):
            raise  # 其余 BaseException 原样传播
        # 代码异常：错误包（带 extracted + resolve_ctx）在 atomic 外写，抛 SettlementAbort（决定 6）。
        try:
            pack_path = write_error_pack(
                db, state, exc=exc, extracted=extracted,
                resolve_ctx=db.get_resolve_context(before_turn),
            )
        except Exception as pack_exc:
            # 写包自身炸不得顶替原异常（同 extractor 先例 raise exc from ...）：
            # 只捕 Exception，写包期间落 Ctrl-C/SystemExit 须原样传播。
            raise exc from pack_exc
        raise SettlementAbort(
            settlement_abort_message(pack_path),
            turn=before_turn, stage="settle", error_pack_path=pack_path,
        ) from exc
    # commit 已成功（atomic 正常退出）才镜像——jsonl 是可回收副本，DB 为真源（决定 5/7）。
    # 嵌套守门与异常路对称（cmr S0 r1）：depth>0 时本层退出并未真 commit，先写镜像=
    # 外层回滚后留「DB 无行、jsonl 有行」孤儿；嵌套场景放弃镜像（丢的只是可回收副本）。
    # 镜像失败不回滚结算：吞 Exception 记日志（行已在 DB）。
    if getattr(db.conn, "_atomic_depth", 0) == 0:
        try:
            collector.mirror_to_jsonl(rejections_jsonl_path())
        except Exception as mirror_exc:
            tlog(f"[rejection] jsonl 镜像失败（DB 行已落，仅副本丢失）：{mirror_exc}")
    return full_report


def _collect_inline_rejections(
    collector: RejectionCollector,
    applied: Dict[str, object],
    turn: int,
    source: Provenance,
) -> None:
    """把 apply 结果里各 section 内嵌的拒收项收进收集器（PR2-S0 桥接）。

    约定：section 结果列表中 `{"rejected": True, ...}` 即拒收项；`reason` 为人读原因，
    `category` 为机读类别（未迁契约的 section 没有此键 → 兜底 "legacy_inline"）。
    一层 dict-of-list（issue_summary 的 new_issues/cancels 等）也要下探——new_issues
    正是实测最常被拒的段，跳过它聚合就失明（cmr S0 r1）。
    item_json 的取值（ship-pre r3/r4）：迁约 producer（S1-S3 已迁全部）在 wrapper 里
    携原始 delta 项（'item' 键）→ 桥接解包存原件；仅未迁 legacy section
    （office_changes/secret_order_* 等）无 'item' 键时才兜底存 wrapper 回显记录。
    """
    def _scan(section: str, items: list) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("rejected"):
                report_section = str(item.get("report_section") or section)
                collector.record(report_section, RejectedItem(
                    # item_json = 原始 delta 项（ADR 决定 5「原 item 原样保留」）：迁约
                    # producer 在 wrapper 里带原件（'item' 键）则解包,否则兜底存 wrapper
                    # （ship-pre r3——存整个 wrapper 会让重放分析消费到嵌套形状）。
                    # 按 'item' 键**存在性**解包（非值类型）：原 isinstance(dict/list/str) 判会把
                    # 标量/null 原件（如 close_issues:[null]/[42] 的非 dict 拒收）误存成 wrapper、
                    # 丢原件保真——key 在即解包，覆盖标量原件（cmr close-issues r5 codex）。
                    item=item["item"] if "item" in item else item,
                    # ADR「拒收行必带人读原因」在此集中守门：producer 漏给则合成非空兜底
                    # ——规则写一处，新 section 免疫同类缺陷（fix-coverage 处方，cmr S0 r3）。
                    reason=str(item.get("reason") or "") or f"拒收（{report_section} 未注明原因）",
                    category=str(item.get("report_category") or item.get("category") or "legacy_inline"),
                    source=source,
                ), turn)
            for subkey, subvalue in item.items():
                if isinstance(subvalue, list):
                    nested_section = f"{section}.{subkey}"
                    if nested_section == "issue_summary.closes.applied_person_changes":
                        continue
                    _scan(nested_section, subvalue)

    for section, value in applied.items():
        if isinstance(value, list):
            _scan(section, value)
        elif isinstance(value, dict):
            for subkey, subvalue in value.items():
                if isinstance(subvalue, list):
                    _scan(f"{section}.{subkey}", subvalue)


def _has_durable_player_visible_rejection(db: GameDB, turn: int) -> bool:
    """True when any non-resimulation-invalidated player-source rejection exists for turn."""
    db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rejection_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn INTEGER NOT NULL,
            section TEXT NOT NULL,
            item_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            category TEXT NOT NULL,
            source TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            resimulation_invalidated INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cols = {str(row[1]) for row in db.conn.execute("PRAGMA table_info(rejection_reports)").fetchall()}
    invalidated_expr = "resimulation_invalidated = 0" if "resimulation_invalidated" in cols else "1=1"
    row = db.conn.execute(
        f"""
        SELECT 1 FROM rejection_reports
        WHERE turn=? AND source IN (?, ?) AND {invalidated_expr}
        LIMIT 1
        """,
        (int(turn), Provenance.player_decree.value, Provenance.hitl_decision.value),
    ).fetchone()
    return row is not None


def _settle_after_extract_body(
    state: GameState,
    db: GameDB,
    extracted: Dict[str, object],
    *,
    before_turn: int,
    content,
    registry,
    decree_text: str,
    narrative: str,
    trace_narrative,
    extractor_input: str,
    extractor_output: str,
    chapter_recorder,
    ending_summarizer,
    delta_applier,
    _stage: Callable[[str], None],
    collector: Optional[RejectionCollector] = None,
    source: Provenance = Provenance.unknown,
) -> str:
    """settle_with_delta 的后半段写序列正文（被其 atomic 包裹调用）。

    抽成独立函数只为让 settle_with_delta 的 try/atomic/except 块清爽；不单独对外。
    """
    tlog("结算 4/4 落库 + inertia/ongoing")
    _stage("落库与事项推进")
    # Persist private monthly reports before applying disclosure updates from
    # the same extraction, so the one authorized promotion event can project
    # the complete canonical history.  The enclosing atomic transaction keeps
    # this ordering all-or-nothing; the DB owns the single eligibility check.
    # #625 / ADR 0077：在场扫描须先于月报 origin 标记；暴露派生须在对账之后
    # （同段 atomic 内 commit=False；两单职责，各调一次）。
    db.record_monthly_supervision_presence(before_turn, commit=False)
    db.record_monthly_dossier_progress(
        before_turn, extracted.get("dossier_progress_reports"),
    )
    # #627：政敌检举——叙事/extractor 结构化条目承接落库（clamp+真伪底+去重）。
    db.accept_faction_denunciations(
        state, extracted.get("faction_denunciations"), commit=False,
    )
    # #567：在途拨帑月度机械对账（被护侧真源）；与 #566 进展分轨，不扩 0058。
    db.record_monthly_grant_reconciliations(
        before_turn, extracted.get("dossier_reconciliations"),
    )
    # 对账落账后：loss>0 ∧ 本 turn 稽核在场 → 空子暴露。
    db.record_monthly_loophole_exposures_from_reconciliations(
        before_turn, commit=False,
    )
    if delta_applier is not None:
        applied = delta_applier(db, state, extracted, content, registry)
    else:
        applied = apply_score_extraction(db, state, extracted, content=content, registry=registry)
    if collector is not None:
        # 桥接：各 section 内嵌的拒收项（{"rejected": True, ...}）收进收集器并在
        # 事务内 flush——delta_applier 闭包签名不动（ADR 决定 8 原地迁入）。section
        # 迁契约后（S1-S3）在此带上精确 category；桥接对未迁 section 兜底。
        _collect_inline_rejections(collector, applied, before_turn, source)
        collector.flush_to_db(db)

    # 把 narrative 写入 turn_logs 作下月前文（sim 前文，不带玩家邸报提示噪声）。
    # save_turn_report 延后到 inertia 拒收收齐之后（见下），以涵盖 inertia-only 的玩家来源拒收
    # （codex R1 P2 + CodeRabbit Major：提前算会漏 inertia 路产生的拒收）。
    db.record_log(state, narrative[:1200])

    # 落 inertia + ongoing (未被本月 issue_advances 触动的)
    touched_ids = set()
    for adv in applied.get("issue_summary", {}).get("advances", []) or []:
        touched_ids.add(int(adv.get("issue_id") or 0))
    inertia_person_changes: list[dict[str, object]] = []
    inertia_rejections = apply_issue_inertia_and_ongoing(
        db,
        state,
        touched_ids=touched_ids,
        applied_person_changes=inertia_person_changes,
    )
    if inertia_person_changes:
        issue_summary = applied.setdefault("issue_summary", {})
        existing = issue_summary.get("applied_person_changes")
        if isinstance(existing, list):
            existing.extend(inertia_person_changes)
        else:
            issue_summary["applied_person_changes"] = list(inertia_person_changes)
    if collector is not None and (inertia_rejections or inertia_person_changes):
        # 桥接跑在 inertia 之前——自然结案路的容忍拒收在此补收并再 flush（仍在事务内,
        # flush 增量安全;只 tlog 等于这条路脱离 rejection_reports 管线,ship-pre r1）。
        # 注:fallback 推进路(resolve_directives 降级分支)无收集器,其 inertia 容忍项
        # 维持 tlog-only(该路本就跳过结算管线)。
        inline_rejections: dict[str, object] = {}
        if inertia_rejections:
            inline_rejections["issue_inertia"] = {"entity_rejections": inertia_rejections}
        if inertia_person_changes:
            inline_rejections["issue_summary"] = {"applied_person_changes": inertia_person_changes}
        _collect_inline_rejections(
            collector, inline_rejections,
            before_turn, source)
        collector.flush_to_db(db)

    # #621 / ADR 0076：经召对窗后的 pending todo → 正式复核落格并消费（三拍第 3 拍）。
    # 须在本 settle 写新 todo 之前：只消费 created_turn < 当前 turn 者，保留本拍新写给次回合。
    # kind 分派：仅 staged 终裁；哭谏 pending 保留。
    from ming_sim.due_review import apply_pending_due_reviews
    apply_pending_due_reviews(db, state, commit=False)

    # #623 / ADR 0075：承诺 due 到 → 挽留条目失效关闭（不走坚持撤分档）。
    from ming_sim.breach_plea import (
        expire_breach_pleas_on_due,
        scan_and_write_breach_pleas,
    )
    expire_breach_pleas_on_due(db, state, commit=False)

    # #624 / ADR 0078：谏/宽限经召对顶出后离 pending（不落执行格、不连坐）。
    from ming_sim.urge_lever import consume_pending_urge_audience_todos
    consume_pending_urge_audience_todos(db, state, commit=False)

    # #620 / ADR 0074：分段到期 → 次回合召对待办（结算内确定性写入，不停轮、不 DECISION）。
    from ming_sim.staged_commitment import write_due_staged_commitment_todos
    write_due_staged_commitment_todos(db, state, commit=False)

    # #623：断供/挪用/撤人机器扫描 → 当回合只写挽留 todo（改弦走 revoke 拦截缝）。
    scan_and_write_breach_pleas(db, state, commit=False)

    # ADR 0008 决定 5：主 apply + inertia 拒收全部收齐后，玩家来源(player_decree/hitl_decision)的
    # 落库拒收 → 邸报附一句 in-world 提示，并**持久化进 turn_report**（web/history/重读都见，非仅即时
    # 返回串；涵盖 inertia-only 拒收，codex R1 P2 + CodeRabbit Major）。system_simulation 来源静默。
    # record_log(sim 下月前文)在 inertia 前已跑、不带此提示噪声。提示极简、不暴露明细（明细落 DB/jsonl）。
    if _has_durable_player_visible_rejection(db, before_turn):
        narrative = narrative + "\n\n有司奏：所拟之事有窒碍未行者，已录档待酌。"
    # #976: release held pure-public audience chat (non-withheld) before
    # archive materialization so 参与即知 lands without secret-origin rows.
    db.release_held_audience_knowledge(commit=False)
    # The simulator narrative is the real settlement input for the public
    # gazette.  Keep it as its own source before archiving, so a mixed
    # aggregate cannot become the only durable representation of this turn.
    _record_settlement_narrative_sources(db, state, narrative, commit=False)
    # Persist the per-source public projection before either aggregate archive
    # is written.  turn_report/chapter are derived prose and cannot provide an
    # authorization boundary when they mix public and restricted matters.
    db.persist_knowledge_items_for_turn(state, commit=False)
    db.save_turn_report(
        state, narrative, knowledge_items=[], commit=False
    )

    # 推演链留痕：extractor_input 保留输入；extractor_output 存最终 applied 结果,
    # 供玩家明细/时间线读取（raw canonical delta 的重跑真源在 pending_resolve_context）。
    # inertia/ongoing 也可能追加玩家可见人物变更,所以必须在上方合并后再保存。
    db.save_turn_extraction(
        state,
        decree_text=decree_text,
        narrative=trace_narrative,  # 留痕含作弊段，便于事后追「为何这么落库」
        extractor_input=extractor_input,
        extractor_output=json.dumps(_player_visible_extractor_output(applied), ensure_ascii=False),
    )

    # #9 cmr R2：派系 leverage 全量 reconcile 兜底（两层设计的第二层，见 db.recompute_all_faction_leverage）。
    # 即时 hook 覆盖单点 office/status/易主变动，但多条改 faction 成员的路径会绕过 hook
    # （裸 UPDATE 改 office_type、power_id 翻走的易主/降臣、放归赦还+任命被拒回滚 等）。在此处
    # （delta 全部落库 + inertia/ongoing 推进之后）扫一遍全部白名单派系重算成公式末值，保无论本回合经
    # 哪条路径改了成员/官职/易主，末态都正确、无残留漂移。
    # #9 线上 R6（codex P2）：必须排在【任何读 faction leverage 的下游】之前——章节记忆、
    # clear_gated_legacies（legacy gate 如「阉党专权」读 faction.阉党.leverage<30）、结局判定。
    # 原置于 clear_gated_legacies 之后 → 同回合经兜底 reconcile 才跌破阈值的派系，会被先跑的 gate
    # 读到陈旧值、使该帝国修正多挂一回合。故前移到此（仍在 settle_with_delta 的 atomic_and_reload 体内、
    # next_period 之前——与结算同生死、可整体回滚；recompute 绝对幂等，被 hook 重算过再扫一遍得同值）。
    db.recompute_all_faction_leverage()

    # 章节记忆：注入回调（真实流程= LLM 浓缩落 event_memories；driver= None 跳过）。失败不抛断。
    _stage("记起居注")
    if chapter_recorder is not None:
        try:
            chapter_recorder(db, state, decree_text, narrative, applied)
        except Exception as exc:
            tlog(f"[chapter-memory] 跳过：{exc}")

    # 开局负面帝国修正：本月若达成消除条件即清除（程序判定，不靠 LLM/时长）
    cleared = clear_gated_legacies(db, state)
    for name in cleared:
        db.record_log(state, f"帝国修正消除：{name}")

    # 结局判定：叙事型（退位/自尽，applied 已带）→ 数值型（京畿失守）→ 到期型（20 年/240 回合）。
    #   state.turn 此刻仍是刚结算完的本回合（next_period 之前）。结局只触发一次。
    outcome = None
    ended = False
    ending_text = ""
    if not state.ended:
        outcome = applied.get("victory_status") or victory_status(db, state)
        if (
            isinstance(outcome, dict)
            and outcome.get("status") == ENDING_ONGOING
            and state.turn >= TIMEOUT_TURN
        ):
            outcome = {
                "status": ENDING_TIMEOUT,
                "summary": "崇祯在位二十载，朝局至此尘埃落定，是中兴、是苟延、还是衰亡，自有史评。",
            }

        ended = isinstance(outcome, dict) and outcome.get("status") != ENDING_ONGOING
        if ended:
            db.record_log(state, f"结局判定：{outcome.get('summary', '')}")
            # 章节记忆（含本回合）已落库，国史编纂官读全程生成结局总评（注入；driver 跳过）。
            if ending_summarizer is not None:
                ending_text = ending_summarizer(db, state, outcome)
            state.ended = True
            state.ending_status = str(outcome.get("status") or "")

    db.mark_directives_issued(state)
    state.next_period()
    # 不变式先验后再写：assert 排在 clear 之后的话，失败时重试真源已被删（cmr r4 codex）。
    assert state.turn == before_turn + 1
    # settling 随推进复位（同笔 save_state 落库）：不复位的话下一回合 pre_settle 被守门
    # 跳过=此后每月财政/暂存/密令全静默丢（cmr S4 r1，3/3）。session 层随后照旧置 ISSUED。
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    # ADR 0008 S3：清 resolve_context 作 settle 写序列的最后一笔（紧贴 next_period 等推进写）。
    # 按 before_turn 清本回合那一行（next_period 已把 state.turn 推进到下一回合）。
    # S7：整段已包进 settle_with_delta 的 atomic——save_state 与本清同事务原子提交，
    # 「已提交但 context 残留」的崩溃窗口已闭合（cmr S2+S3 codex R2 defer→S7，崩溃点回归见
    # test_settle_crash_after_savestate_before_clear_rolls_back）。
    db.clear_resolve_context(before_turn)
    # #1234：月初快照同窗过期（路③呈现投影，非结算权威；与 resolve_context 清法同构）。
    db.clear_month_open_snapshot(before_turn)

    ending = ""
    if ended:
        label = ENDING_LABELS.get(str(outcome.get("status")), "结局")
        ending = f"\n\n【结局·{label}】{outcome.get('summary', '')}"
        if ending_text:
            ending += "\n\n" + ending_text
    # in-world 拒收提示已在 save_turn_report 前追加进 narrative（持久化 + 流入此处 full_report），
    # 不在此重复 append（ADR 0008 决定 5；codex R1 high：须持久化非仅返回串）。
    full_report = f"\n本{TURN_UNIT}颁布诏书：\n" + decree_text + "\n\n" + narrative + ending
    return full_report




def resolve_decisions_phase2(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    on_event: Optional[Callable[[str, str], None]] = None,
    content=None,
    registry=None,
    cheat_directive: str = "",
) -> str:
    """phase2：皇帝亲裁完，读回 phase1 暂存上下文 + 已存决策点选择，续跑结算。
    要求本回合处于 awaiting_decision（已有 resolve_context）。返回完整结算报告。"""
    def _emit(kind: str, data: str) -> None:
        if on_event:
            on_event(kind, data)

    ctx = db.get_resolve_context(state.turn)
    if ctx is None:
        raise LLMContractError("无待决推演上下文，无法续跑结算（phase1 未暂停或已结算）。")
    before_turn = state.turn
    if ctx.get("extracted") is not None:
        # ready context = 上次 phase2 已抽取并持久化、settle 曾中止。直入重放，不重跑贵的
        # simulator/extractor（决定 3；重抽还会 upsert 覆盖 ready 真源，cmr S7 r2 codex）。
        # 亲裁指令已在上次抽取时拼进 narrative 并体现在 ready delta 中。重放炸 →
        # resolve_settling_recovery 的逃生口降级 context，下次重试重新推演。
        # 重试新传的 cheat_directive 在重放叉被忽略（重放使用崩溃前真源），留痕（cmr S7 r4）。
        if (cheat_directive or "").strip():
            tlog("[恢复重放] 本次传入的 cheat_directive 被忽略（重放使用崩溃前真源）。")
        # 走到此叉必有重交的亲裁选择（submit_decisions 已 overwrite choice_json），同样
        # 被忽略——重放体现的是崩溃前已抽取的旧选择（cmr S7 r5）。
        tlog("[恢复重放] 本次重交的亲裁选择被忽略（重放使用崩溃前真源）。")
        result = resolve_settling_recovery(
            state, db, agno_db, llm_config, ctx,
            on_event=on_event, content=content, registry=registry,
        )
        db.clear_pending_decisions(before_turn)
        return result.report
    decisions = db.list_pending_decisions(state.turn)
    decision_directive = _format_decision_directive(decisions)
    rescript_actions = _chosen_rescript_actions(decisions)
    # #48 / #883 恢复端闭环：HITL 续跑复用存档的 narrative + simulator_payload（不重推演）。
    # 密令分组真源在 ctx["secret_orders"]，经独立 rail 喂 personnel_secret extractor
    # （_recovered_grouped 归一 list/dict）；simulator_payload 是公共轨，不含密令正文。
    sim_payload = ctx["simulator_payload"] if isinstance(ctx["simulator_payload"], dict) else {}
    # #146 A：来源从 ctx 继承（phase1 皇帝下旨存的 player_decree）。HITL 续跑 / 崩溃重抽都不改来源
    # ——皇帝原旨没变、来源就没变。非法/缺失回落 system_simulation（旧档兼容，同 resolve_settling_recovery）。
    ctx_source = _provenance_from_stored(ctx.get("source"))
    report = _settle_after_narrative(
        state, db, agno_db, llm_config,
        decree_text=str(ctx["decree_text"]),
        narrative=str(ctx["narrative"]),
        simulator_payload=sim_payload,
        relevant_memories=ctx["relevant_memories"] if isinstance(ctx["relevant_memories"], list) else [],
        secret_orders=_recovered_grouped(ctx["secret_orders"]),
        before_turn=before_turn, _emit=_emit,
        content=content, registry=registry,
        cheat_directive=cheat_directive,
        decision_directive=decision_directive,
        source=ctx_source,
        dossier_verdicts=(
            sim_payload.get("dossier_verdicts")
            if isinstance(sim_payload.get("dossier_verdicts"), list) else None
        ),
        dossier_rescript_actions=rescript_actions,
    )
    # 结算完清掉暂存决策点（next_period 已在 _settle 内执行，故按 before_turn 清理本回合残留）。
    # resolve_context 的清理已移入 settle_with_delta 的写序列内（ADR 0008 S3），不在此 post-settle 处清。
    db.clear_pending_decisions(before_turn)
    return report


def _generate_ending_summary(
    db: GameDB,
    state: GameState,
    llm_config: LLMConfig,
    agno_db: SqliteDb,
    outcome: Dict[str, object],
    _emit: Callable[[str, str], None],
) -> str:
    """国史编纂官读全部章节记忆生成结局总评，落库 ending_summary（含逐回合时间线）。
    LLM 失败时用章节拼保底总评。返回总评正文（也已落库）。"""
    chapters = db.list_chapter_memories(upto_turn=state.turn)
    timeline = build_timeline(db, upto_turn=state.turn)
    summary_text = ""
    try:
        _emit("stage", "国史编纂结局总评")
        ending_agent = create_ending_summary_agent(llm_config, agno_db)
        payload = {
            "ending": {"status": outcome.get("status"), "summary": outcome.get("summary")},
            "chapters": chapters,
            "final_state": {
                "year": state.year, "period": state.period, "turn": state.turn,
                "metrics": dict(state.metrics),
            },
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
        tlog(f"[ending-summary/INPUT] chapters={len(chapters)} ({len(payload_json)}字)")
        summary_text = run_agent_text(ending_agent, payload_json, tag="ending-summary").strip()
        tlog(f"[ending-summary/OUTPUT] ({len(summary_text)}字)")
    except Exception as exc:
        tlog(f"[ending-summary] LLM 失败，走保底：{exc}")

    if not summary_text:
        bits = [str(outcome.get("summary") or "")]
        for c in chapters[-6:]:
            body = (c.get("body") or "").strip()
            if body:
                bits.append(f"{c['year']}年{c['period']}月：{body}")
        summary_text = "\n".join(b for b in bits if b)

    try:
        db.save_ending_summary(
            state, str(outcome.get("status") or ""), summary_text, timeline,
        )
    except Exception as exc:
        tlog(f"[ending-summary] 落库失败：{exc}")
    return summary_text
