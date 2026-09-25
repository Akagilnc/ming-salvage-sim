"""诏书生成与回合结算：拟诏、推演落库、无诏推进。L7。

纯逻辑（无 input()）；resolve_directives 的 print 是诊断输出，非交互。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence

from agno.db.sqlite import SqliteDb
from openai import APIConnectionError, APIStatusError, APITimeoutError

from ming_sim.agents import (
    _dump_llm_messages,
    create_arrival_attendant_agent,
    create_chapter_memory_agent,
    create_decree_writer_agent,
    create_promulgation_judge_agent,
    create_ending_summary_agent,
    create_relation_brew_agent,
    create_faction_brew_agent,
    create_season_simulator_agent,
    create_settlement_attendant_agent,
    parse_agent_json,
    run_agent_text,
)
from ming_sim.applier import (
    Provenance, RejectedItem, RejectionCollector, atomic,
    mirror_rejections_after_commit,
)
from ming_sim.constants import TURN_UNIT
from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
from ming_sim.db import GameDB
from ming_sim.error_pack import (
    ARRIVAL_COMPANION_SIM_DONE_KEY,
    _next_attempt,
    clear_for_resimulation,
    rejections_jsonl_path,
    settlement_abort_message,
    write_error_pack,
)
from ming_sim.exceptions import (
    LLMContractError,
    LLMUnavailable,
    PromulgationHealEvidence,
    SettlementAbort,
)
from ming_sim.faction_brew import VIEW_FACTION_STANCE
from ming_sim.flows import apply_fixed_period_flows, raise_fixed_period_flow_abort_if_needed
from ming_sim.issues import (
    apply_event_terminal_states,
    apply_historical_fiscal_rates,
    apply_issue_inertia_and_ongoing,
    apply_score_extraction,
    _apply_levy_driven_transfers,
    auto_trigger_seed_issues,
    clear_gated_legacies,
    gather_impeachment_surge_candidates,
    sanitize_delta_shape,
    validate_delta_shape,
)
from ming_sim.llm_model import extract_agent_text, llm_unavailable_from_error
from ming_sim.models import FRONT_HALF_DONE_PHASES, GameState, LLMConfig, TurnPhase
from ming_sim.qualitative import imperial_authority_band, power_band, qualitative_character_axis
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
from ming_sim.relation_brew import MonthEndRelationBrewLeg
from ming_sim.simulation import (
    build_simulator_payload,
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

# #1725：月末结算 SSE stage 唯一权威。六名冻结；emit 只经 settlement_stage_payload，
# 携带独立于显示措辞的 typed 进度事实（current/total），前端不得文案反查。
SETTLEMENT_STAGE_LABELS = (
    "固定月度财政入账",
    "回顾近来朝局",
    "推演月末邸报",
    "数值推演结算",
    "落库与事项推进",
    "记起居注",
)
# #1740：结局回合第七段——不并入六名表（普通回合永不发）。
# emit 只经 settlement_ending_stage_payload，current/total=7；普通六阶 total 仍为 6。
SETTLEMENT_ENDING_STAGE_LABEL = "国史编纂结局总评"


def settlement_stage_payload(index: int) -> Dict[str, Any]:
    """Ordinary wait-stage fact: display label + typed 1-based current/total."""
    return {
        "content": SETTLEMENT_STAGE_LABELS[index],
        "current": index + 1,
        "total": len(SETTLEMENT_STAGE_LABELS),
    }


def settlement_ending_stage_payload() -> Dict[str, Any]:
    """Ending-round seventh stage; total becomes 7 only on this emit."""
    total = len(SETTLEMENT_STAGE_LABELS) + 1
    return {
        "content": SETTLEMENT_ENDING_STAGE_LABEL,
        "current": total,
        "total": total,
    }

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
    _select_secret_orders_for_sim,
    _strip_player_internal_fields,
    augment_secret_orders_with_due_commitments,
    bind_decision_options,
    bind_decisions_to_candidate_events,
    group_secret_orders_for_sim,
    iter_secret_order_ids,
    parse_decision_blocks,
)


@dataclass
class ResolveResult:
    """过月入口的返回。advanced 才表示回合已推进。

    awaiting=True：批红案头待裁（#1847 请旨/打回三选，沿既有 HITL）。
    awaiting=False 且 stage=gazette：邸报尚未归档，主链未推进。
    """
    awaiting: bool
    report: str = ""
    decisions: List[Dict[str, object]] = field(default_factory=list)
    advanced: bool = False
    stage: str = ""


def collect_new_arrival_waiting_audience(
    transit_arrivals: Sequence[Mapping[str, object]] | None,
    waiting_audience: Sequence[Mapping[str, object]] | None,
) -> List[Dict[str, object]]:
    """#671：frozen transit_arrivals ∩ waiting_audience（typed 键，不解析自由文）。

    映射：``transit_arrivals[].name`` ↔ ``waiting_audience[].person_name``，
    并核抵京 location（``is_capital_location``）。集合空 → 调用方零调用。
    """
    from ming_sim.matching import is_capital_location

    waiting_by_name: Dict[str, Mapping[str, object]] = {}
    for item in waiting_audience or ():
        if not isinstance(item, Mapping):
            continue
        person_name = str(item.get("person_name") or "").strip()
        if person_name and person_name not in waiting_by_name:
            waiting_by_name[person_name] = item

    result: List[Dict[str, object]] = []
    seen: set[str] = set()
    for arrival in transit_arrivals or ():
        if not isinstance(arrival, Mapping):
            continue
        name = str(arrival.get("name") or "").strip()
        if not name or name in seen or name not in waiting_by_name:
            continue
        location = str(arrival.get("location") or "").strip()
        waiting = waiting_by_name[name]
        wait_loc = str(waiting.get("location") or "").strip()
        effective_loc = location or wait_loc
        # #671：双来源均空或非京 → 拒收；不得默认 beizhili。只认 is_capital_location。
        if not is_capital_location(effective_loc):
            continue
        seen.add(name)
        result.append({
            "name": name,
            "person_name": name,
            "location": effective_loc,
            "status": "候旨",
            "origin_id": waiting.get("origin_id"),
            "source_entry_id": waiting.get("source_entry_id"),
            "year": arrival.get("year"),
            "period": arrival.get("period"),
        })
    return result


def run_arrival_attendant_message(
    llm_config: LLMConfig,
    *,
    year: int,
    period: int,
    arrivals: Sequence[Mapping[str, object]],
    agent=None,
) -> str:
    """#671：王承恩抵京报到 one-shot。集合非空而空文 → LLMContractError。"""
    if not arrivals:
        return ""
    facts = {
        "year": int(year),
        "period": int(period),
        "arrivals": [
            {
                "name": str(row.get("name") or row.get("person_name") or "").strip(),
                "location": str(row.get("location") or "").strip(),
                "status": str(row.get("status") or "候旨"),
            }
            for row in arrivals
            if str(row.get("name") or row.get("person_name") or "").strip()
        ],
    }
    if not facts["arrivals"]:
        return ""
    runner = agent if agent is not None else create_arrival_attendant_agent(llm_config)
    try:
        text = run_agent_text(
            runner,
            json.dumps(facts, ensure_ascii=False),
            tag="arrival-attendant",
        )
    except (APITimeoutError, APIConnectionError, APIStatusError) as error:
        # 生产 provider 调用适配缝：只捕已知超时/连接/HTTP 异常，译 LLMUnavailable
        #（保留 cause）。LLMContractError（空文）与程序错不捕，照旧响亮上抛。
        raise llm_unavailable_from_error(error, "王承恩抵京报到") from error
    text = str(text or "")
    if not text.strip():
        raise LLMContractError("王承恩抵京报到返回空文")
    return text  # 原文，含首尾空白（P6：零删改）


def run_settlement_attendant_message(
    llm_config: LLMConfig,
    *,
    year: int,
    period: int,
    rejections: Sequence[Mapping[str, object]],
    agent=None,
) -> str:
    """#1745：王承恩结算拒收递话 one-shot。有玩家来源拒收而空文 → LLMContractError。

    只吃结构化 section/category/reason；原文返回（P6 零删改）。
    """
    if not rejections:
        return ""
    facts = {
        "year": int(year),
        "period": int(period),
        "rejections": [
            {
                "section": str(row.get("section") or ""),
                "category": str(row.get("category") or ""),
                "reason": str(row.get("reason") or ""),
            }
            for row in rejections
        ],
    }
    if not facts["rejections"]:
        return ""
    runner = agent if agent is not None else create_settlement_attendant_agent(llm_config)
    try:
        text = run_agent_text(
            runner,
            json.dumps(facts, ensure_ascii=False),
            tag="settlement-attendant",
        )
    except (APITimeoutError, APIConnectionError, APIStatusError) as error:
        raise llm_unavailable_from_error(error, "王承恩结算拒收递话") from error
    text = str(text or "")
    if not text.strip():
        raise LLMContractError("王承恩结算拒收递话返回空文")
    return text  # 原文，含首尾空白（P6：零删改）


# #1753 decision key promulgation-verdict-heal-by-resume-then-fail-closed：
# 颁布判决 LLM 违契约 → 同一会话有界纠正补交次数（单一真源；不含首次）。
PROMULGATION_VERDICT_HEAL_RETRIES = 3


def stub_promulgation_verdicts(
    dossiers: Sequence[Dict[str, object]], state: GameState,
) -> List[Dict[str, object]]:
    """Deterministic auto-promulgation for exempt dossiers and explicit test fixtures."""
    del state
    return [
        {"dossier_id": int(row["id"]), "decision": "promulgated"}
        for row in dossiers
    ]


def _collect_compliant_promulgation_items(
    batch: object,
    db: GameDB,
    *,
    proposed_modes: Dict[int, str],
    prepared_context: Optional[Dict[str, object]],
    reviewed_dossier_ids: Optional[set[int]],
) -> List[Dict[str, object]]:
    """从不合规整批中收集单项已过闸的判决（证据保留，不落判、不伪造缺案）。"""
    if not isinstance(batch, list):
        return []
    good: List[Dict[str, object]] = []
    seen: set[int] = set()
    for candidate in batch:
        try:
            valid = _validate_promulgation_verdict_item(
                candidate, db,
                proposed_modes=proposed_modes,
                prepared_context=prepared_context,
            )
        except LLMContractError:
            continue
        dossier_id = int(valid["dossier_id"])
        if reviewed_dossier_ids is not None and dossier_id not in reviewed_dossier_ids:
            continue
        if dossier_id in seen:
            continue
        seen.add(dossier_id)
        good.append(valid)
    return good


def _merge_compliant_promulgation_items(
    accumulated: List[Dict[str, object]],
    fresh: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    """跨补交轮次并集保留已合规判决：先到先留，后轮不得冲掉前轮好判（#1753）。

    输入仅来自 _collect_compliant_promulgation_items 已过闸项，不再二次类型过滤。
    """
    by_id: Dict[int, Dict[str, object]] = {}
    order: List[int] = []
    for row in list(accumulated) + list(fresh):
        dossier_id = int(row["dossier_id"])
        if dossier_id in by_id:
            continue
        by_id[dossier_id] = row
        order.append(dossier_id)
    return [by_id[item] for item in order]


def _dossier_payload_dict(row: Mapping[str, object] | Dict[str, object]) -> Dict[str, object]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    try:
        parsed = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_stalled_deliberation(dossier: Mapping[str, object] | Dict[str, object]) -> bool:
    """#658：stalled 廷议不进颁布集合（判官/stub/校验/消费共用）。"""
    return str(_dossier_payload_dict(dossier).get("deliberation_state") or "") == "stalled"


def _promulgable_proposed_dossiers(
    proposed_dossiers: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    """本轮可颁布 proposed = 非 stalled 廷议的 proposed 案卷。"""
    return [row for row in proposed_dossiers if not _is_stalled_deliberation(row)]


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
    authority_band = imperial_authority_band(authority)
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


@dataclass
class _PromulgationJudgeSession:
    """Attempt-scoped judge holder：单次 resolve/直呼尝试内 heal 复用同一 agent。

    session 身份在 holder 构造时固定；同月另一次结算/恢复新建 holder 不得
    复用上一尝试的 Agno 持久化历史。turn 仅作可读前缀，不充当跨尝试主键。
    """

    llm_config: object
    agno_db: object
    turn: int
    agent: object | None = None
    session_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = (
                f"promulgation-judge-turn-{int(self.turn)}-{uuid.uuid4().hex}"
            )

    def get_or_create(self) -> object:
        if self.agent is None:
            self.agent = create_promulgation_judge_agent(
                self.llm_config,
                self.agno_db,
                session_id=self.session_id,
                num_history_runs=PROMULGATION_VERDICT_HEAL_RETRIES + 1,
            )
        return self.agent


def llm_promulgation_verdicts(
    dossiers: Sequence[Dict[str, object]], state: GameState, *, db: GameDB,
    agno_db: SqliteDb, llm_config: LLMConfig,
    prepared_context: Optional[Dict[str, object]] = None,
    judge_session: Optional[_PromulgationJudgeSession] = None,
    correction_feedback: str = "",
    transport_policy: object | None = None,
) -> List[Dict[str, object]]:
    """Run exactly one LLM call for one reviewed promulgation batch.

    judge_session / correction_feedback：#1753 有界补交复用同一会话。
    首抽送输入快照；补交 = 同 agent 会话续接 + correction（原始产出/失败原因/
    待判 id）+ 再次附带首抽快照（draft 同款回喂形，确保缺盖时补交输入仍含
    全案卷身份，不单靠 history）。
    判官工厂只在 _PromulgationJudgeSession.get_or_create：同一 holder 复用同一
    agent/session；直呼（scripts）无 session 时本函数建临时 holder，临时 holder
    同样获得独立 session 身份，单一装配不平行。
    替身替换本函数则不触工厂（既有 tracer 契约）。
    """
    context = prepared_context or build_promulgation_judge_context(db, state, dossiers)
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    # 单一装配：heal holder 与 scripts 直呼都经 get_or_create，不平行调工厂。
    session = judge_session or _PromulgationJudgeSession(
        llm_config=llm_config,
        agno_db=agno_db,
        turn=int(state.turn),
    )
    judge = session.get_or_create()
    if correction_feedback:
        # 同会话续接：history 应已有首轮；仍附首抽快照（draft 骨架），
        # 使补交输入可独立核验含全案卷身份。
        prompt = f"{correction_feedback}\n{context_json}"
    else:
        prompt = context_json
    # #1465 ②：history-backed transport 重试截 run 走 GameDB.truncate_agno_session_runs
    # （与召对 truncate_chat_turn_agno_runs 同接缝）；不新造历史机制。
    # GameDB 经入参契约显式交给 run_agent_text，不挂 agent 私有属性。
    raw = run_agent_text(
        judge, prompt, tag="promulgation-judge", game_db=db,
        transport_policy=transport_policy,
    )
    parsed = parse_agent_json(raw, "颁布判官")
    return _require_promulgation_verdict_list(
        parsed.get("verdicts"), raw_value=parsed,
    )


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
        mode = modes.get(dossier_id) if isinstance(dossier_id, int) else None
        # Work on a shallow copy: 顺颁 may strip LLM noise without mutating caller input.
        item: Dict[str, object] = dict(row)
        if decision == "promulgated":
            # #1397 / r6: 颁布判官 LLM 常在 decision=promulgated 上夹带打回形解释字段
            # （reason/gatekeeper_id/primary_opponents/criteria_snapshot 等）。decision 已
            # 钉顺颁，这些字段是产出噪声而非语义；硬拒会在 pre_settle 落 settling 后
            # SettlementAbort 卡死整月。剥离已知噪声， downstream 按干净顺颁继续。
            # 真正未知键与打回契约仍硬拒（见下方 exact-key / rejection 校验）。
            for key in rejection_only_fields:
                item.pop(key, None)
            item.pop("legal_reason_code", None)
            # ordinary/midzhi 顺颁均省略 affected_parties（#657 §C.8 later-wins：中旨不猜派）。
            item.pop("affected_parties", None)
        elif mode == "midzhi" and decision == "rejected":
            # 中旨打回：剥离猜派字段；正式离心归 M12。
            item.pop("affected_parties", None)
        marker = item.get("midzhi_unpromulgatable", False)
        if not isinstance(marker, bool):
            raise ValueError("中旨亦不可颁标记必须为 bool")
        if marker:
            if mode is not None:
                if decision != "rejected" or mode != "midzhi":
                    raise ValueError("中旨亦不可颁只能标记中旨打回判决")
            elif decision != "rejected":
                raise ValueError("中旨亦不可颁只能标记打回判决")
        if any(isinstance(key, str) and key.startswith("resistance_") for key in item):
            raise ValueError("颁布判决不得携带阻力数值字段")
        # Exact verdict-key enforcement (#561) when mode is known from proposed set.
        if mode is not None:
            allowed_keys = {"dossier_id", "decision"}
            if decision == "rejected":
                allowed_keys.update(rejection_only_fields - {"midzhi_unpromulgatable"})
                allowed_keys.update({"legal_reason_code"})
                if mode == "midzhi":
                    allowed_keys.add("midzhi_unpromulgatable")
                else:
                    # ordinary 打回仍承载 typed 反应清单
                    allowed_keys.add("affected_parties")
            unknown_keys = set(item) - allowed_keys
            if unknown_keys:
                raise ValueError(f"颁布判决含未知字段：{sorted(unknown_keys)}")
            validate_verdict_affected_parties(
                item, mode, faction_names=faction_names, class_names=class_names,
            )
        else:
            affected = item.get("affected_parties", [])
            if not isinstance(affected, list):
                raise ValueError("受损方必须为 typed 清单")
            validate_affected_parties(
                affected, faction_names=faction_names, class_names=class_names,
            )
        if item.get("decision") == "rejected":
            validate_rejection_verdict(
                item, {"cabinet_drafting", "palace_rescript", "six_offices"},
                faction_names=faction_names,
                class_names=class_names,
                character_ids=gatekeeper_ids,
            )
            if dossier_id in context_dossiers:
                source_snapshot = context_dossiers[dossier_id].get(
                    "criteria_snapshot_source"
                )
                if item.get("criteria_snapshot") != source_snapshot:
                    raise ValueError("打回判决 criteria_snapshot 与判官输入原值不一致")
    except ValueError as exc:
        raise LLMContractError(str(exc)) from exc
    return item


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
            # hint（非 note）：前端 isPendingDecision / DecisionOption 认 hint；
            # dossier_id/dossier_decision 是批红能力字段，点选必须原样回传（#1490）。
            "options": [
                *([] if verdict.get("midzhi_unpromulgatable") is True else [{
                    "label": "强颁",
                    "hint": "改走中旨强行颁出，并承担中旨代价",
                    "dossier_id": dossier_id,
                    "dossier_decision": "force_promulgated",
                }]),
                {
                    "label": "收回",
                    "hint": "收回此道准旨",
                    "dossier_id": dossier_id,
                    "dossier_decision": "withdrawn",
                },
                {
                    "label": "留中",
                    "hint": "留待下月重判",
                    "dossier_id": dossier_id,
                    "dossier_decision": "hold",
                },
            ],
        })
    return decisions


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


def _open_affair_ids_from_payload(payload: object) -> set[int]:
    from ming_sim.entities.affair import parse_positive_affair_id

    if not isinstance(payload, dict):
        return set()
    raw = payload.get("open_affairs")
    if not isinstance(raw, list):
        return set()
    ids: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ids.add(parse_positive_affair_id(item.get("id")))
        except (TypeError, ValueError):
            continue
    return ids


def secret_dossier_ids_from_secret_orders(db: GameDB, secret_orders: object) -> set[int]:
    """#1252: freeze secret-dossier roster-write authority from batch secret_orders.

    Resolve each real secret-order id via get_dossier_for_secret_order. Missing
    authority is an empty closed set — callers must never rebuild from live DB
    beyond the frozen order-id batch.
    """
    out: set[int] = set()
    for order_id in iter_secret_order_ids(secret_orders):
        dossier = db.get_dossier_for_secret_order(int(order_id))
        if dossier is None:
            continue
        out.add(int(dossier["id"]))
    return out


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
    # #671 / P6 / ADR 0142：simulator 自由文本零删改；strip 只在临时副本上判空
    narrative_text = str(narrative or "")
    if not narrative_text.strip():
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
    # #1769：跨月未成案 draft 在既有 directives 投影上标 admission_status（输入侧；
    # 不新建通知；不另抽 helper）。
    current_turn = int(state.turn)
    directive_feed: List[Dict[str, object]] = []
    for row in directives:
        item: Dict[str, object] = {"text": str(row["text"] or "")}
        if int(row["turn"]) < current_turn:
            item["admission_status"] = "上月未入档"
        directive_feed.append(item)
    payload = {
        "turn": {"year": state.year, "period": state.period, "turn": state.turn},
        "directives": directive_feed,
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
        "execution_signal": row.get("execution_signal"),
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
    # #651: expose durable monthly pay truth before execution is judged; this
    # remains a field of the canonical dossier rather than a parallel wrapper.
    from ming_sim.covert_levy import army_pay_fact_for_dossier
    projected["army_pay_fact"] = army_pay_fact_for_dossier(db, int(row["id"]))
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
        # In-transit executing work and just-promulgated payload-owned work need
        # command/target context without re-materializing.
        just_promulgated_payload = (
            policy["effect_owner"] == "payload"
            and policy.get("execution_surface") == "terminal"
            and str(row.get("settlement_verdict") or "") == "promulgated"
        )
        if admitted and (
            str(row.get("status") or "") == "executing" or just_promulgated_payload
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
    """Whether the month has durable work that must enter resolve_directives.

    Used by resolve_turn's draft-gate bypass (long secret orders / proposed
    dossiers / monthly progress nudges).  No longer gates a no-edict fast path
    — empty-decree months always take the full pre_settle+simulator+settle rail
    (#1274 QA J-1 / owner B-2).
    """
    executing_work = False
    for row in db.list_decree_dossiers(status="executing"):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = json.loads(str(row.get("payload_json") or "{}"))
        # Non-terminal executing dossiers remain simulator continuation context.
        if dossier_action_policy(row.get("action_type"), payload)["execution_surface"] != "terminal":
            executing_work = True
            break
    return bool(db.list_monthly_dossier_progress_nudges()) or bool(
        db.list_decree_dossiers(status="proposed")
    ) or executing_work or any(
        row.get("kind") == "directive"
        for row in db.list_pending_actions(state.turn)
    )


def _carry_pending_clarification_actions(
    db: GameDB, state: GameState, before_turn: int, *, content=None,
) -> None:
    """Keep unresolved pre-edict drafts discoverable in the new month."""
    for pending_action in db.list_pending_actions(before_turn):
        prepared = db._prepare_pending_directive(state, pending_action, content=content)
        if prepared["classification"] == "needs_clarification":
            db.conn.execute(
                "UPDATE pending_actions "
                "SET turn=?, night_id=0, night_approved=0 WHERE id=?",
                (int(state.turn), int(pending_action["id"])),
            )


def resolve_directives(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    directives: List[sqlite3.Row],
    decree_text: str,
    deaths_this_turn: Optional[List[Dict[str, str]]] = None,
    debuts_this_turn: Optional[List[Dict[str, str]]] = None,
    on_event: Optional[Callable[[str, Any], None]] = None,
    content=None,
    registry=None,
    cheat_directive: str = "",
    source: Provenance = Provenance.player_decree,
    scene_registry=None,
) -> ResolveResult:
    """玩家过月入口：前括号之后走 ADR 0157 主链，不再用 extractor 落账。

    source（#146 cmr r2）：本回合结算 delta 的来源。默认 player_decree——正常皇帝下旨路
    行为不变。崩溃恢复 fallthrough（SETTLING 非 ready ctx 重走本函数）须把存档 ctx['source']
    经 _provenance_from_stored 还原后传入，使 provenance 按构造保真（system_simulation 重跑仍
    记 system、对玩家静默），不依赖「非 ready SETTLING ctx 恒 player」这一脆弱不变式。

    on_event(kind, data): 推演过程实时回调。
    kind ∈ {stage, thinking, text}；stage 为 settlement_stage_payload 字典
    （content + typed current/total），thinking/text 为增量字符串。

    cheat_directive: 作弊控制台（Ctrl+~）下的强制结算指令。非空时交给本月世界段，
    按字面当既成事实，不另开 extractor。

    返回 ResolveResult。advanced 为假时主链停在批红或邸报交接，回合不推进。
    """
    def _emit(kind: str, data: Any) -> None:
        if on_event:
            on_event(kind, data)

    # #1274 / ADR 0157：无旨不再分流快路。有旨、无旨都走同一过月主链：
    # 前括号之后按旨序核算，再跑世界段。批红、邸报与推进是后续阶段的交接，
    # 不在本入口用 extractor 落账。

    before_turn = state.turn

    # 草案内容已由拟诏合并进 decree_text，simulator 只读 decree_text，不再单传逐条草案。

    # 1) 前括号确定性结算：与探针 driver 共用 prepare_resolve_front_half（ADR 0004 / #668）。
    prepare_resolve_front_half(
        state, db,
        decree_text=decree_text,
        content=content,
        registry=registry,
        scene_registry=scene_registry,
        source=source,
        on_stage=lambda payload: _emit("stage", payload),
    )

    from ming_sim.month_chain import run_player_month_chain
    return run_player_month_chain(
        state, db, agno_db, llm_config,
        decree_text=decree_text,
        before_turn=before_turn,
        on_event=on_event,
        content=content,
        registry=registry,
        source=source,
        cheat_directive=cheat_directive,
    )


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


# #657：HITL phase2 续跑时 persist 不得触碰急务票拟行（return_revise 等跨 phase2 存活）。
# 与 None/[]（#656 空票拟 → DELETE 本回合 draft）三态分立。
_PRESERVE_RESCRIPT_DRAFTS = object()


class _AppendRescriptDrafts:
    """#657 HITL phase2：追加本回合新票拟，不 DELETE 既有急务行。"""

    __slots__ = ("items",)

    def __init__(self, items: List[Dict[str, object]]) -> None:
        self.items = list(items)


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
    rescript_drafts: Optional[List[Dict[str, object]]] = None,
    attendant_message: str = "",
) -> Dict[str, object]:
    """ADR 0008 S2：每回合进入结算后半段前无条件持久化 resolve_context（extractor delta + 叙事）。

    source（#144）：拒收 provenance 一并持久化，driver 崩溃恢复据此还原
    原始来源——否则玩家来源(player_decree/hitl)拒收被恢复路记成 system_simulation、静默不提示。

    driver 重跑真源：跨进程恢复从此重灌；玩家月链改用暂存声明及落账状态。
    **持久化前先过 validate_delta_shape**——形状畸形的 delta 绝不入 resolve_context
    （否则钉进重试真源：apply 永崩、而「重跑 extractor」被「context 已存在」挡死=soft-lock）。
    校验失败响亮抛 ValueError，save 不执行。注意此门只挡形状毒：shape 合法但值级
    必炸的 payload（如 new_armies 项里非数值兵力）由 ADR 0008 决定 6 的「重新推演」
    逃生口兜底（清 context 重产 delta）；driver 不能假设 ready=1 即重放安全。
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
            attendant_message=attendant_message,
        )
        # #656 / F2.5：急务票拟行与重跑真源同一事务——ready context 存在 ⟺ 票拟已落
        # （生成成功时）。崩溃恢复从持久层读回，不重跑已完成的票拟步（F1.3）；
        # extractor 中止则整个事务回滚，票拟一并回滚不落、重试重生成。
        # #657：_PRESERVE_RESCRIPT_DRAFTS → 零触碰；_AppendRescriptDrafts → 追加不删既有。
        if rescript_drafts is _PRESERVE_RESCRIPT_DRAFTS:
            pass
        elif isinstance(rescript_drafts, _AppendRescriptDrafts):
            if rescript_drafts.items:
                db.append_rescript_drafts(turn, rescript_drafts.items)
        elif isinstance(rescript_drafts, list) and rescript_drafts:
            db.save_rescript_drafts(turn, rescript_drafts)
        elif rescript_drafts is None or (isinstance(rescript_drafts, list) and len(rescript_drafts) == 0):
            # r4 p3：空/None 时同一事务内 DELETE 本回合 kind='rescript_draft' 行，
            # 防同回合二次 persist 残留上一 attempt 的行（F2.5 context⟺票拟对应）。
            db.conn.execute(
                "DELETE FROM pending_decisions WHERE turn = ? AND kind = 'rescript_draft'",
                (int(turn),),
            )
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return cleaned


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

    抽自结算管线同款 try/atomic/except-reload-reraise（pre_settle / settle_with_delta /
    resolve_directives 前括号 + fallback + HITL 暂停三件 + driver.run_settle）。

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


def tick_transit_arrivals(
    db: GameDB,
    state: GameState,
    content=None,
    *,
    commit: bool = True,
) -> List[Dict[str, object]]:
    """0095/#668 确定性在途倒数：active 在途者 remaining -= 1.0 * speed_factor；≤0 当月抵达。

    只处理新档完整四量（transit_to + remaining + factor）；缺量旧行不特判、不迁移。
    抵达经唯一写缝 set_character_transit 整账清零；返回本 tick 抵达列表
    （[{"name", "location"}, ...]，按 name 稳定序）。

    commit=False 时不提交——由外层事务（如 pre_settle 的 atomic_and_reload）统一提交。
    """
    current_turn = int(state.turn)
    rows = db.conn.execute(
        "SELECT name, transit_to, transit_distance_remaining, transit_speed_factor, "
        "transit_start_turn FROM characters "
        "WHERE status='active' AND COALESCE(transit_to, '') != '' "
        "AND transit_distance_remaining IS NOT NULL "
        "AND transit_speed_factor IS NOT NULL "
        "ORDER BY name"
    ).fetchall()
    arrivals: List[Dict[str, object]] = []
    for row in rows:
        name = str(row["name"])
        dest = str(row["transit_to"])
        remaining = float(row["transit_distance_remaining"])
        factor = float(row["transit_speed_factor"])
        start_turn = int(row["transit_start_turn"] or 0)
        # F2：启程当月只落账、当月不减；次月起首减。
        if start_turn >= current_turn:
            continue
        new_remaining = remaining - 1.0 * factor
        if new_remaining <= 0:
            db.set_character_transit(
                name, location=dest, content=content, commit=False,
            )
            arrivals.append({"name": name, "location": dest})
        else:
            db.set_character_transit(
                name,
                transit_to=dest,
                distance_remaining=new_remaining,
                speed_factor=factor,
                start_turn=start_turn,
                content=content,
                commit=False,
            )
    if commit:
        db.conn.commit()
    return arrivals


def prepare_resolve_front_half(
    state: GameState,
    db: GameDB,
    *,
    decree_text: str = "",
    content=None,
    registry=None,
    scene_registry=None,
    source: object = Provenance.player_decree,
    on_stage: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, object]]:
    """共享前半段 seam（ADR 0004 / #668）：pre_settle + ready=0 占位（含 transit_arrivals）。

    resolve_directives 与 driver.prepare 共用此 helper。外层 atomic 使 settling 相位与
    ready=0 context 同生共死。已有 context 的 FRONT_HALF_DONE 重入只读返回既有
    transit_arrivals，禁止 placeholder upsert 覆写 durable 真源（ready=0 原诏/source
    与 ready=1 崩溃重放载荷），不二次 tick/财政。返回本回合 `transit_arrivals`
    （无抵达 = `[]`）。
    """
    # 已有-context 重入：只读既有真源。save_resolve_context 是整行 upsert，placeholder
    # 默认空字段会冲掉 ready=0 原诏/source 与 ready=1 extracted/contract/narrative。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        existing = db.get_resolve_context(int(state.turn))
        if existing is not None:
            payload = existing.get("simulator_payload")
            if isinstance(payload, dict) and isinstance(payload.get("transit_arrivals"), list):
                return list(payload["transit_arrivals"])
            return []

    # 诏书占位真源（ship-pre r5）：pre_settle 成功后立即把 decree_text 落为 ready=0
    # 占位——begin_turn 会清内存 last_decree，跨进程恢复的 no-ready fallthrough 没有
    # 此行就只能用 LLM 从草案重新生成，玩家手改的原诏蒸发。HITL/ready persist 后续
    # 同键 upsert，settle 尾 clear 收掉。
    #
    # 占位与 settling 相位同事务可见（PR #90 R1 codex P2）：外层 atomic 把 pre_settle
    # 的内层事务并入（flat 可重入），崩在「settling 已提交、占位未落」的窗口不再可能
    # ——要么两者都见，要么整段回滚重来。
    try:
        transit_arrivals_box: List[Dict[str, object]] = []
        with atomic_and_reload(db, state, content=content, registry=registry):
            pre_settle(
                state, db, on_stage=on_stage,
                content=content, registry=registry,
                scene_registry=scene_registry,
                transit_arrivals_out=transit_arrivals_box,
            )
            # #668：transit_arrivals 与 ready=0 占位同外层 atomic 写入。
            placeholder_payload = {
                "transit_arrivals": list(transit_arrivals_box),
                "open_affairs": db.affairs.input_brief(getattr(db, "textual_facts", None)),
            }
            # #671：占位 upsert 不得以默认空串覆盖已持久 attendant_message
            #（clear_for_resimulation 后 phase 非 FRONT_HALF_DONE 重入时尤甚）。
            prior_placeholder = db.get_resolve_context(int(state.turn))
            preserved_attendant = (
                str(prior_placeholder.get("attendant_message") or "")
                if isinstance(prior_placeholder, dict)
                else ""
            )
            db.save_resolve_context(
                state.turn, decree_text, "", placeholder_payload,
                secret_orders={}, relevant_memories=[],  # #48：占位用分组承载的空 dict（旋即被真存覆盖）
                source=Provenance(source).value,  # #146 A：归一 enum/合法值串
                attendant_message=preserved_attendant,
            )
    except BaseException as exc:
        raise_fixed_period_flow_abort_if_needed(db, state, exc)
        raise

    ctx = db.get_resolve_context(int(state.turn))
    payload = ctx.get("simulator_payload") if isinstance(ctx, dict) else None
    if isinstance(payload, dict) and isinstance(payload.get("transit_arrivals"), list):
        return list(payload["transit_arrivals"])
    return list(transit_arrivals_box)


def pre_settle(
    state: GameState, db: GameDB, *, on_stage=None, content=None, registry=None,
    scene_registry=None,
    transit_arrivals_out: Optional[List[Dict[str, object]]] = None,
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
    #   （settle_with_delta / fallback）各自在 atomic 内 commit；
    #   早退路在事务外 commit 会让重推演路上 extractor 再炸时动作已提交而回合未推进。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        return []
    if transit_arrivals_out is not None:
        transit_arrivals_out.clear()
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
    collector = RejectionCollector()
    try:
        with atomic_and_reload(
            db, state, content=content, registry=registry,
            on_error=lambda _exc: collector.reset(),
        ):
            # 动作闸门(ADR 0006)：颁诏最前批量落库本回合暂存的结构化聊天写动作（密令更新/催办/任免/…），
            # 在跑 LLM 结算管线前，使 simulator/extractor 读到的盘面与旧「召对期直写」时序一致。
            # driver 路径无聊天暂存 → 空 no-op。幂等（committed 行不重跑）。
            # #1560 / CONTEXT：过回合丢弃既有 failed secret-order intents，再 commit；
            # 顺序在 commit 前，避免误清同次 commit 新产生的 failure。
            discarded_failed = db.discard_failed_secret_order_intents()
            if discarded_failed:
                tlog(f"[pending_actions] 过回合丢弃既有 failed 密令意图 {discarded_failed} 条")
            committed = db.commit_pending_actions(
                state, content=content, registry=registry,
                rejection_collector=collector,
            )
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
                on_stage(settlement_stage_payload(0))
            # 落账副作用；明细不再进 simulator payload（欠饷哗变走前置事件/issue）
            apply_fixed_period_flows(db, state)
            # 0095/#668 在途倒数 tick：remaining -= 1.0*factor，≤0 引擎抵达。
            # 必须先于 apply_event_terminal_states / auto_trigger_seed_issues：门控读 location 前
            # 在途者须先完成本月抵达（decree 既有顺序约束）。
            arrivals = tick_transit_arrivals(db, state, content, commit=False)
            if transit_arrivals_out is not None:
                transit_arrivals_out.clear()
                transit_arrivals_out.extend(arrivals)
            if arrivals:
                tlog(f"[transit-tick] 本月抵达 {len(arrivals)} 人：{[a['name'] for a in arrivals]}")
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
            # #1504：到期密令只打期限戳，保持 active；结案在 settle 尾部机械对账。
            # 推演前的确定性写，挪入前半段事务（原在 resolve_directives，ADR 0008 S4）。
            due_orders = db.auto_submit_due_secret_orders(state)
            if due_orders:
                tlog(f"[secret_order] 到期待对账 {due_orders}")
            # 完成相位：同事务内落 settling（崩在上面任一步=全回滚=相位未变）。
            state.turn_phase = TurnPhase.SETTLING.value
            db.save_state(state)
            collector.flush_to_db(db)
    except BaseException as exc:
        raise_fixed_period_flow_abort_if_needed(db, state, exc)
        raise
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return auto_triggered


def _make_relation_brew_runner(
        llm_config: LLMConfig, agno_db: SqliteDb,
) -> Callable[[GameState, GameDB, int, int, int], MonthEndRelationBrewLeg]:
    """#636 S5：月末关系酿制腿的注入工厂（真实流程= LLM agent；driver= None 跳过）。

    返回 (state, db, settled_turn, settled_year, settled_period) -> Leg 工厂；
    settle_with_delta 单点拥有 start/join/drain 生命周期：在结算事务内边事件定型
    后调 prepare()，把 brew()（零 DB 的 LLM 相）放进唯一一条受管 Future 与
    chapter/ending 重叠，提交后、摘要持久化前 join，异常路排空丢弃。每条关系一个
    新 agent 实例（批内并行各自独享，不共享运行态）；输出零裁剪零 clamp
    （庭裁 r1 F2），长度约束只走 prompt 正向输入契约。"""

    def _create(state: GameState, db: GameDB, *, settled_turn: int, settled_year: int,
                settled_period: int) -> MonthEndRelationBrewLeg:
        def _brew_fn(payload_json: str) -> str:
            # 同批双契约分派（#637 S6，庭裁 r1 F2：同一受管批次不建第二编排腿）：
            # 派系工作项走派系态势裁判，关系工作项走关系酿制裁判。payload 是本腿
            # 自产的确定性 JSON；解析炸属程序错，响亮上抛（ADR 0005）。
            payload = json.loads(payload_json)
            agent = (
                create_faction_brew_agent(llm_config, agno_db)
                if payload.get("view") == VIEW_FACTION_STANCE
                else create_relation_brew_agent(llm_config, agno_db)
            )
            try:
                return run_agent_text(agent, payload_json, tag="relation-brew")
            except (APITimeoutError, APIConnectionError, APIStatusError) as error:
                # 生产 provider 调用适配缝（庭裁 Z3）：只捕实际 provider 的已知
                # 超时/连接/HTTP 异常，复用 llm_unavailable_from_error 译成声明
                # 类型 LLMUnavailable（保留原异常为 cause），_brew_one 调用段
                # 依法单条降级留痕。不宽吞 Exception：KeyError/ValueError 等
                # 程序错照旧响亮上抛（ADR 0008）。
                raise llm_unavailable_from_error(error, "关系酿制") from error

        return MonthEndRelationBrewLeg(
            db, state, _brew_fn,
            settled_turn=settled_turn,
            settled_year=settled_year,
            settled_period=settled_period,
        )

    return _create


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
    relation_brew_runner=None,
    source: Provenance = Provenance.unknown,
    dossier_verdicts: Optional[List[Dict[str, object]]] = None,
    dossier_rescript_actions: Optional[List[Dict[str, object]]] = None,
    attendant_message: str = "",
    settlement_attendant_runner=None,
) -> str:
    """确定性结算「后括号」：apply→turn_logs→inertia→留痕→章节记忆→clear→结局判定→next_period。

    收一份**已规范化**的 extracted（英文 canonical key，见 simulation._canonicalize_extraction）。
    不依赖 llm_config —— 章节记忆 / 结局总评 / 落库 enrichment / 拒收递话 全经注入闭包：
    章节记忆=chapter_recorder、结局总评=ending_summarizer、落库（含 issue/office 的
    通道感知 enrichment）=delta_applier、玩家来源拒收呈现=settlement_attendant_runner。
    真实流程传捕获 llm_config 的闭包；探针 driver 对 chapter_recorder/ending_summarizer
    传 None，对 settlement_attendant_runner 由调用方注入（缺则玩家拒收诚实失败，P7），对
    delta_applier 传 channel=api 确定性闭包——结算核本体都不见 llm_config（ADR 0004）。

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

    # #636 S5：settled 年月快照——next_period 推进后 state 已指下一个月，月末酿制腿的
    # 输入/落款/认领一律用此快照（庭裁：runner 取结算月须用 next_period 前的年月）。
    settled_turn, settled_year, settled_period = (
        int(state.turn), int(state.year), int(state.period),
    )

    def _stage(payload: Dict[str, Any]) -> None:
        if on_stage is not None:
            on_stage(payload)

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
    # #636 S5（ID-10/P5，判词类②跨阶段并行）：月末酿制腿的唯一受管 Future——
    # start/join/drain 生命周期单点归 settle_with_delta。start 在结算事务内、本月
    # 边事件集定型后（body 在 chapter/ending 前触发钩子）执行：prepare()（DB 相，
    # 事务内选中＋认领＋备料）后把 brew()（零 DB 的 LLM 相）放进单工 executor，
    # 使酿制 LLM 等待与无依赖的 chapter/ending 等后处理重叠。提交成功后、摘要
    # 持久化前 join；异常路（结算回滚）排空等待并丢弃结果——事务回滚后事件与
    # 认领均不存在，酿制产物一律作废。探针 driver 传 None（无腿，零 Future）。
    _brew_pool = None
    _brew_future = None
    _brew_leg = None
    affected_people: set[str] = set()

    def _start_relation_brew() -> None:
        nonlocal _brew_pool, _brew_future, _brew_leg
        leg = relation_brew_runner(
            state, db,
            settled_turn=settled_turn,
            settled_year=settled_year,
            settled_period=settled_period,
        )
        if not leg.prepare():
            return
        _brew_leg = leg
        _brew_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="relation-brew-leg")
        _brew_future = _brew_pool.submit(leg.brew)
    try:
        with atomic_and_reload(
            db, state, content=content, registry=registry,
            on_error=lambda _exc: collector.reset(),
        ) as _atomic:
            # 暂存动作 commit 在结算事务内最前（幂等，只处理 pending 行；正常路 pre_settle
            # 已 commit=无操作）——恢复/phase2 重抽路在此获得覆盖，且与结算同生死：
            # 事务外 commit 的话重放炸时结算回滚而动作及其真表副作用留存=跨事务半写
            # （cmr S7 r4，claude+codex 两面同根）。
            # registry=None：事务内零 registry 变更。pending 直写人物（调教/密令等）
            # 的受影响名随 applied 回执并入 outer-commit 投影；office 仍经案卷判决。
            for item in db.commit_pending_actions(
                state, content=content, registry=None,
                rejection_collector=collector,
            ) or ():
                for person in item.get("affected_people") or ():
                    name = str(person or "").strip()
                    if name:
                        affected_people.add(name)
            if dossier_verdicts:
                affected_people.update(db.apply_dossier_verdicts(
                    state, dossier_verdicts, content=content, registry=None,
                ))
            # Player disposition rows are not Judge verdicts: no affected_parties,
            # no midzhi validator, no apply_dossier_verdicts. Route each chosen
            # rescript action through the existing promulgation seam under this
            # outer atomic batch (ADR 0056 force reads current-turn Judge evidence).
            if dossier_rescript_actions:
                for action in dossier_rescript_actions:
                    affected_people.update(db.apply_dossier_promulgation(
                        state,
                        int(action["dossier_id"]),
                        str(action["decision"]),
                        content=content,
                        registry=None,
                    ) or set())
            full_report = _settle_after_extract_body(
                state, db, extracted,
                before_turn=before_turn, content=content, registry=registry,
                decree_text=decree_text, narrative=narrative,
                trace_narrative=trace_narrative,
                extractor_input=extractor_input, extractor_output=extractor_output,
                chapter_recorder=chapter_recorder, ending_summarizer=ending_summarizer,
                delta_applier=delta_applier, _stage=_stage,
                collector=collector, source=source,
                start_relation_brew=(
                    _start_relation_brew if relation_brew_runner is not None else None
                ),
                attendant_message=attendant_message,
                settlement_attendant_runner=settlement_attendant_runner,
            )
    except BaseException as exc:
        # 酿制腿异常路排空（判词：异常时也排空）：等 brew() 收尾并丢弃结果——结算
        # 事务已整体回滚，本月边事件与认领均不存在，任何酿制产物一律作废；排空
        # 不吞不换原异常，只防悬空 worker。
        if _brew_pool is not None:
            _brew_pool.shutdown(wait=True)
            _brew_exc = _brew_future.exception() if _brew_future is not None else None
            if _brew_exc is not None:
                tlog(f"[relation-brew] 酿制 Future 随结算回滚排空丢弃：{_brew_exc}")
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
    # Registry projection only after the real outermost commit; outer rollback discards.
    # Existing roster → refresh; brand-new formal people (e.g. 纳妃) → register.
    # Duck-type project_outcome so test fakes that only implement refresh still work.
    if registry is not None and affected_people:
        from ming_sim.applier import register_runtime_outcome_callbacks
        names = sorted(affected_people)
        project = getattr(registry, "project_outcome", None)

        def _project_affected() -> None:
            for person_name in names:
                if project is not None:
                    project(person_name)
                else:
                    registry.refresh(person_name)

        register_runtime_outcome_callbacks(db, on_commit=_project_affected)
    # JSONL follows the real outer transaction outcome; DB remains truth.
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    # #636 S5 月末酿制腿收尾（判词类②）：结算事务已提交，摘要持久化前 join。
    # brew() 内仅单条 LLM 调用/输出契约失败降级留痕；persist 内 apply/mark 的
    # DB/schema/程序错误响亮上抛（ADR 0005/0008）——腿级宽吞已删。
    if _brew_pool is not None:
        try:
            _brew_future.result()
        finally:
            _brew_pool.shutdown(wait=True)
        _brew_leg.persist()
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


def _ensure_rejection_reports_table(db: GameDB) -> str:
    """Ensure rejection_reports exists; return SQL fragment for non-invalidated rows."""
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
    return "resimulation_invalidated = 0" if "resimulation_invalidated" in cols else "1=1"


def list_durable_player_visible_rejections(
    db: GameDB, turn: int,
) -> List[Dict[str, object]]:
    """0008-D5 来源门：本 turn 未作废的 player_decree/hitl_decision 拒收结构化事实。

    只投影 section/category/reason 供 LLM 呈现接缝；不含 item 明细（不泄技术载荷）。
    """
    invalidated_expr = _ensure_rejection_reports_table(db)
    rows = db.conn.execute(
        f"""
        SELECT section, category, reason FROM rejection_reports
        WHERE turn=? AND source IN (?, ?) AND {invalidated_expr}
        ORDER BY id
        """,
        (int(turn), Provenance.player_decree.value, Provenance.hitl_decision.value),
    ).fetchall()
    return [
        {
            "section": str(r["section"] or ""),
            "category": str(r["category"] or ""),
            "reason": str(r["reason"] or ""),
        }
        for r in rows
    ]


def _has_durable_player_visible_rejection(db: GameDB, turn: int) -> bool:
    """True when any non-resimulation-invalidated player-source rejection exists for turn."""
    return bool(list_durable_player_visible_rejections(db, turn))


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
    _stage: Callable[[Dict[str, Any]], None],
    collector: Optional[RejectionCollector] = None,
    source: Provenance = Provenance.unknown,
    start_relation_brew: Optional[Callable[[], None]] = None,
    attendant_message: str = "",
    settlement_attendant_runner: Optional[Callable[..., str]] = None,
) -> str:
    """settle_with_delta 的后半段写序列正文（被其 atomic 包裹调用）。

    抽成独立函数只为让 settle_with_delta 的 try/atomic/except 块清爽；不单独对外。
    """
    tlog("结算 4/4 落库 + inertia/ongoing")
    _stage(settlement_stage_payload(4))
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
    # #1745：无目标/坏引用提案逐项拒收进 collector，好项同 atomic 落库（0015-D7）。
    db.record_monthly_grant_reconciliations(
        before_turn, extracted.get("dossier_reconciliations"),
        rejection_collector=collector, source=source,
    )
    # 对账落账后：loss>0 ∧ 本 turn 稽核在场 → 空子暴露。
    db.record_monthly_loophole_exposures_from_reconciliations(
        before_turn, commit=False,
    )
    # #650/0089：先消费月初已提交的旧账，再应用本月 extractor 改账；两者与
    # extraction 留痕同属本 phase2 atomic，跨进程恢复无需易失桥且可整体重放。
    levy_applied, levy_rejected = _apply_levy_driven_transfers(db, commit=False)
    if delta_applier is not None:
        applied = delta_applier(db, state, extracted, content, registry)
    else:
        applied = apply_score_extraction(db, state, extracted, content=content, registry=registry)
    # #670：判官所产续程只有在 canonical applier 已成功后才按故事账 origin 结清；
    # 本函数外层 atomic 使行止与结清同成同败；另退役非 active 未结传召。
    from ming_sim.audience_night import (
        settle_applied_arrived_summons,
        retire_unsettled_summons_for_inactive,
    )
    applied["settled_summon_origins"] = settle_applied_arrived_summons(db, applied)
    applied["retired_summon_origins"] = retire_unsettled_summons_for_inactive(db)
    applied.setdefault("population_transfers", []).extend(levy_applied)
    applied.setdefault("population_transfers_rejections", []).extend(levy_rejected)
    # #1504：当月 covert 实况进度与 apply 同一 atomic（0073 实况轨；不读奏报）。
    from ming_sim.covert_progress import (
        apply_monthly_covert_actual_progress,
        parse_covert_exec_selections,
    )
    applied["covert_actual_progress"] = apply_monthly_covert_actual_progress(
        db, state,
        selections=parse_covert_exec_selections(extracted),
        commit=False,
    )
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

    # #651：普通旨只骑既有 canonical 字段结账；三路揭破仍写唯一 todo 表。
    from ming_sim.covert_levy import settle_exposure_from_canonical_actions, write_exposure_todos
    applied["covert_levy_exposure_settlements"] = settle_exposure_from_canonical_actions(db, state, applied)
    applied["covert_levy_exposures"] = write_exposure_todos(db, state, applied)

    # #621 / ADR 0076：经召对窗后的 pending todo → 正式复核落格并消费（三拍第 3 拍）。
    # 须在本 settle 写新 todo 之前：只消费 created_turn < 当前 turn 者，保留本拍新写给次回合。
    # kind 分派：仅 staged 终裁；哭谏 pending 保留。
    from ming_sim.due_review import apply_pending_due_reviews
    apply_pending_due_reviews(db, state, commit=False)

    # #1504：当月实况已落后 → 到期密令只读实况轨缺口对账（替换 secret_order_closes）。
    from ming_sim.covert_progress import settle_due_secret_orders
    applied["secret_order_settlements"] = settle_due_secret_orders(
        db, state, commit=False,
    )

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

    # ADR 0008 决定 5 来源门 + 0150-D5-b / P7：玩家来源拒收 → 结构化事实包送
    # settlement attendant LLM 接缝，原文写入 attendant_message 槽；代码不写戏内句、
    # 不改 narrative。system_simulation 来源不进此门。空文/失败 fail-loud（整 settle 回滚）。
    # 既有抵京 companion 稿占槽时：同槽第二段换行并列（代码只做布局拼接）。
    player_rejections = list_durable_player_visible_rejections(db, before_turn)
    if player_rejections:
        if settlement_attendant_runner is None:
            raise LLMContractError(
                "玩家来源拒收须经 settlement attendant 呈现接缝"
            )
        rejection_speech = settlement_attendant_runner(
            year=int(state.year),
            period=int(state.period),
            rejections=player_rejections,
        )
        if not str(rejection_speech or "").strip():
            raise LLMContractError("王承恩结算拒收递话返回空文")
        # P6/0142：判空用临时副本；拼接只加布局分隔，不 rstrip/裁剪任一份 LLM 原文。
        existing = str(attendant_message or "")
        if existing.strip():
            attendant_message = existing + "\n" + str(rejection_speech)
        else:
            attendant_message = str(rejection_speech)
    # 机械人口真相只留在 extraction/applied 内账；公开回响由下方既有邸报来源承担，
    # 不再把精确人数强制广播为所有角色的公共知识。
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
        state, narrative, knowledge_items=[],
        attendant_message=attendant_message, commit=False,
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

    # #636 S5（ID-10/P5）：本月边事件集至此已全部定型——delta 落库与 breach plea 等
    # 确定性补写全毕，此后到提交再无边事件写口。此刻触发酿制腿 start 钩子：
    # prepare() 在本事务内选中＋认领（与边事件同生共死，庭裁 r2/r3 F1），brew()
    # 进受管 Future 与下方无依赖的章节记忆/结局总评重叠。start/join/drain 归
    # settle_with_delta 单点所有，此处只触发。prepare 的 DB/程序错误响亮上抛、
    # 随本 atomic 整体回滚走错误包路（ADR 0005/0008）。
    if start_relation_brew is not None:
        start_relation_brew()

    # 章节记忆：注入回调（真实流程= LLM 浓缩落 event_memories；driver= None 跳过）。失败不抛断。
    _stage(settlement_stage_payload(5))
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
    # #657：return_revise 清锚纳入 settle 单一终态（与 next_period 同 atomic），
    # 禁 phase2 成功后再另笔 commit（崩溃窗口会卡住已应用 revise 锚）。
    from ming_sim.rescript_actions import clear_return_revise_choice_anchors
    clear_return_revise_choice_anchors(db, None)
    state.next_period()
    # 颁诏前要求澄清的拟旨不会在 commit_pending_actions 中落印；推进后把它们移交新回合，
    # 使当前 turn 的唯一发现口仍能供后续召对核定，并解除已关闭召对夜的绑定。
    _carry_pending_clarification_actions(db, state, before_turn, content=content)
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
    on_event: Optional[Callable[[str, Any], None]] = None,
    content=None,
    registry=None,
    cheat_directive: str = "",
) -> str:
    """phase2：皇帝亲裁完，读回 phase1 暂存上下文 + 已存决策点选择，续跑结算。
    要求本回合处于 awaiting_decision（已有 resolve_context）。返回完整结算报告。"""
    def _emit(kind: str, data: Any) -> None:
        if on_event:
            on_event(kind, data)

    ctx = db.get_resolve_context(state.turn)
    if ctx is None:
        raise LLMContractError("无待决推演上下文，无法续跑结算（phase1 未暂停或已结算）。")
    before_turn = state.turn
    if ctx.get("extracted") is not None:
        # 旧 phase2 ready delta 不是新月链的恢复真源；保留原诏/来源与已裁记录，
        # 废弃旧整段落账产物后从现役暂存声明继续。
        clear_for_resimulation(db, before_turn)
        ctx = db.get_resolve_context(before_turn) or ctx
    from ming_sim.month_chain import run_player_month_chain
    result = run_player_month_chain(
        state, db, agno_db, llm_config,
        decree_text=str(ctx.get("decree_text") or ""),
        content=content,
        registry=registry,
        source=_provenance_from_stored(ctx.get("source")),
        cheat_directive=cheat_directive,
    )
    return result.report


def _generate_ending_summary(
    db: GameDB,
    state: GameState,
    llm_config: LLMConfig,
    agno_db: SqliteDb,
    outcome: Dict[str, object],
    _emit: Callable[[str, Any], None],
) -> str:
    """国史编纂官读全部章节记忆生成结局总评，落库 ending_summary（含逐回合时间线）。
    LLM 失败时用章节拼保底总评。返回总评正文（也已落库）。"""
    chapters = db.list_chapter_memories(upto_turn=state.turn)
    timeline = build_timeline(db, upto_turn=state.turn)
    summary_text = ""
    try:
        _emit("stage", settlement_ending_stage_payload())
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
