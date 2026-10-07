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
    create_decree_writer_agent,
    create_promulgation_judge_agent,
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
    _next_attempt,
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
    apply_historical_fiscal_rates,
)
from ming_sim.llm_model import extract_agent_text, llm_unavailable_from_error
from ming_sim.models import FRONT_HALF_DONE_PHASES, GameState, LLMConfig, TurnPhase
from ming_sim.qualitative import imperial_authority_band, power_band, qualitative_character_axis
from ming_sim.decree_vocabulary import (
    dossier_action_policy,
)
from ming_sim.strict_types import (
    IMPERIAL_AUTHORITY_BANDS, validate_affected_parties, validate_rejection_verdict,
    validate_verdict_affected_parties,
)
from ming_sim.token_stats import tlog

# 20 年自动结算：开局 1627.10（turn=1），每回合 +1 月。到 1647.10 = (1647-1627)*12 + 1 = 241 回合。
# 满 240 回合（即第 240 个回合结算完，1647.09）仍未分胜负则强制 timeout 收尾。
TIMEOUT_TURN = 240

# 逐旨／世界段请旨解析工具位于 ming_sim.settlement_payload，不从邸报抽取。
# 此处 re-import 保 `from ming_sim.decree import X` 公开表面 + decree 内部调用点不变。
from ming_sim.settlement_payload import (  # noqa: E402
    _DECISION_RE,
    bind_decision_options,
    parse_decision_blocks,
)


@dataclass
class ResolveResult:
    """过月入口的返回。advanced 才表示回合已推进。

    awaiting=True：批红案头待裁（#1847 请旨/打回三选，沿既有 HITL）。
    awaiting=False 且 stage=gazette：邸报尚未归档，主链未推进。
    有模型配置时作者会先写再推进；没有配置时仍停在这一相位。
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
        entry = {
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
        }
        # #1894：撤令案卷须带原旨、已投入与办理进度给外廷判官——撤的是哪道
        # 已发旨、办到几分、钱花掉多少，本就在既有账里（materials 单一读口）。
        # 只是供料，不新增调用、不新增判官；判官据此自定准行/劝回/拖延。
        if str(row.get("action_type") or "") == "revoke_decree":
            from ming_sim.materials import revoke_target_facts
            entry["revoke_target"] = revoke_target_facts(db, payload, row)
        dossier_rows.append(entry)
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
        for o in db.list_secret_orders(status="done"):
            if o.get("result"):
                closed_evidence.append({
                    "id": int(o["id"]), "title": o["title"],
                    "assignee": o["minister_name"], "evidence": o["result"],
                })
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
    content=None,
    cheat_directive: str = "",
    source: Provenance = Provenance.player_decree,
) -> ResolveResult:
    """玩家过月入口：前括号之后走 ADR 0157 主链，不再用 extractor 落账。

    source（#146 cmr r2）：本回合结算 delta 的来源。默认 player_decree——正常皇帝下旨路
    行为不变。崩溃恢复 fallthrough（SETTLING 非 ready ctx 重走本函数）须把存档 ctx['source']
    经 _provenance_from_stored 还原后传入，使 provenance 按构造保真（system_simulation 重跑仍
    记 system、对玩家静默），不依赖「非 ready SETTLING ctx 恒 player」这一脆弱不变式。

    cheat_directive: 作弊控制台（Ctrl+~）下的强制结算指令。非空时交给本月世界段，
    按字面当既成事实，不另开 extractor。

    返回 ResolveResult。advanced 为假时主链停在批红或邸报交接，回合不推进。
    """
    # #1274 / ADR 0157：无旨不再分流快路。有旨、无旨都走同一过月主链：
    # 前括号之后按旨序核算，再跑世界段。批红、邸报与推进是后续阶段的交接，
    # 不在本入口用 extractor 落账。

    before_turn = state.turn

    # 草案内容已由拟诏合并进 decree_text；月链沿已保存的旨意继续。

    # 1) 前括号确定性结算：玩家月链的唯一准备入口。
    prepare_resolve_front_half(
        state, db,
        decree_text=decree_text,
        content=content,
        source=source,
    )

    from ming_sim.month_chain import run_player_month_chain
    return run_player_month_chain(
        state, db, agno_db, llm_config,
        decree_text=decree_text,
        before_turn=before_turn,
        content=content,
        source=source,
        cheat_directive=cheat_directive,
    )


def _provenance_from_stored(value: object) -> Provenance:
    """从 ctx 持久值还原 Provenance（#146 恢复路）。

    接受 Provenance 实例与已存的枚举值字符串；非法/缺失回落 system_simulation。
    写库侧见 db.save_resolve_context：一律落枚举值字符串，不落 str(member)。
    """
    if isinstance(value, Provenance):
        return value
    text = str(value or "system_simulation")
    try:
        return Provenance(text)
    except ValueError:
        return Provenance.system_simulation


# 同源恢复刷新的标量字段（与 db.load_state 读盘列对齐）。metrics 单独深刷。
_RELOAD_SCALAR_FIELDS = ("year", "period", "turn", "turn_phase", "ended", "ending_status")


def reload_state_from_db(db: GameDB, state: GameState, *, content=None) -> GameState:
    """回滚后把内存 state 从 DB 原地刷新（ADR 0008 决定 3 第三条）。

    DB 回滚只回 SQLite，Python 对象留脏（state.metrics 直加 flows.py:192、turn_phase、
    next_period 的 turn/year/period）。事务期内正常写内存——回滚后须把这些副作用按 DB 真相
    刷掉，否则脏内存会污染重跑（如脏 settling 相位被守门跳过=整月财政丢，cmr S4 r1 F4）。

    走 db.load_state 同路径（与 restore 同源），但 load_state 返回**新对象**；state 被各处
    持引用（session.state、各调用栈），必须**原地刷新**而非返回新对象——把 DB 值
    写回同一对象的字段、metrics dict 原地 update-then-prune（任何时刻非空），返回同一 state（id 不变）。

    content 非 None 时以 DB 全量重建 characters（restore 同路径 _sync_offices_from_db_impl）：
    既清幽灵（任免 commit 先挂 content 再写 DB，回滚删行留幽灵——重试被误拒，cmr S5 r1
    codex trace），也刷掉存量人物的脏属性（罢免/调任/顶替改的 status/office/office_type
    随 DB 回滚必须同源还原，cmr S5 r2 双家共识）。
    嵌套 atomic 内禁止 reload：depth>0 时 rollback 尚未发生（flat 语义，最外层才回滚），
    load_state 同连接会读到未提交脏写——把脏数据当真相刷进 state（cmr S5 r1 claude）。
    """
    if not db.owns_transaction():
        raise RuntimeError(
            "reload_state_from_db 在外层事务内禁止：回滚尚未发生，会把未提交脏写"
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
        _sync_offices_from_db_impl(content, db, db.llm_config)
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
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> "Iterator[_AtomicOutcome]":
    """`with atomic(db)` + 「最外层异常回滚后从 DB 重载内存」的公共内核（ADR 0008 S4）。

    供 pre_settle 与玩家月链中需要事务回滚并重载内存状态的步骤使用。

    语义（逐处保真）：
    - body 包进 `with atomic(db)`，正常退出由 atomic 统一提交（嵌套时由最外层落定）。
    - body 抛 BaseException 时：先（若有）调 on_error(exc)，再仅当本层即最外层、
      atomic 已真回滚（owns_transaction）时调 reload_state_from_db 把脏内存按 DB 刷净；
      仍在外层事务内则跳过 reload（回滚尚未发生，load_state 会读未提交脏写）。
      reload 自身再炸不顶替原异常，链上抛 `raise exc from reload_exc`。最后原样
      re-raise 原异常（fail-loud，ADR 0005）。

    on_error 在 reload 之前触发（DB 行随回滚消失，
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
        if db.owns_transaction():
            try:
                reload_state_from_db(db, state, content=content)
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
    source: object = Provenance.player_decree,
) -> List[Dict[str, object]]:
    """共享前半段 seam（ADR 0004 / #668）：pre_settle + ready=0 占位（含 transit_arrivals）。

    玩家月链通过 resolve_directives 调用此 helper。外层 atomic 使 settling 相位与
    ready=0 context 同生共死。已有 context 的 FRONT_HALF_DONE 重入只读返回既有
    transit_arrivals，禁止 placeholder upsert 覆写 durable 真源（ready=0 原诏/source
    ），不二次 tick/财政。返回本回合 `transit_arrivals`
    （无抵达 = `[]`）。
    """
    # 已有-context 重入：只读既有真源。save_resolve_context 是整行 upsert，placeholder
    # 默认空字段会冲掉已有原诏/source。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        existing = db.get_resolve_context(int(state.turn))
        if existing is not None:
            payload = existing.get("simulator_payload")
            if isinstance(payload, dict) and isinstance(payload.get("transit_arrivals"), list):
                return list(payload["transit_arrivals"])
            return []

    # 诏书占位真源（ship-pre r5）：pre_settle 成功后立即把 decree_text 落为 ready=0
    # 占位——begin_turn 会清内存 last_decree，跨进程恢复的 no-ready fallthrough 没有
    # 此行就只能用 LLM 从草案重新生成，玩家手改的原诏蒸发。后续同键 upsert 保留本月上下文。
    #
    # 占位与 settling 相位同事务可见（PR #90 R1 codex P2）：外层 atomic 把 pre_settle
    # 的内层事务并入（flat 可重入），崩在「settling 已提交、占位未落」的窗口不再可能
    # ——要么两者都见，要么整段回滚重来。
    try:
        transit_arrivals_box: List[Dict[str, object]] = []
        with atomic_and_reload(db, state, content=content):
            pre_settle(
                state, db,
                content=content,
                transit_arrivals_out=transit_arrivals_box,
            )
            # #668：transit_arrivals 与 ready=0 占位同外层 atomic 写入。
            placeholder_payload = {
                "transit_arrivals": list(transit_arrivals_box),
                "open_affairs": db.affairs.input_brief(db.textual_facts),
            }
            # #671：占位 upsert 不得以默认空串覆盖已持久 attendant_message
            #（同 turn 占位重入时尤甚）。
            prior_placeholder = db.get_resolve_context(int(state.turn))
            preserved_attendant = (
                str(prior_placeholder.get("attendant_message") or "")
                if isinstance(prior_placeholder, dict)
                else ""
            )
            db.save_resolve_context(
                state.turn, decree_text, placeholder_payload,
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
    state: GameState, db: GameDB, *, content=None,
    transit_arrivals_out: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """确定性结算「前括号」：暂存动作、固定月度财政、在途抵达、稽核反制与到期密令。

    世界事件判门不在此处。它们只在逐旨落账之后消费一次，才能读到当月实账。
    返回本段仍由程序硬触发的清单（稽核反制、承诺反噬）；content 供 office(任免)暂存动作落库。

    ADR 0008 S4：整段（暂存动作 commit + 固定财政 + 到期密令呈递）包成
    **自己的单事务**——崩在内部=全回滚=相位未变=重进时干净重跑前半段。完成时**同事务内**
    落中间相位 settling（写 state.turn_phase + save_state）：只意味着「前半段已完成，不再
    重跑 pre_settle」，不意味着后半段就绪（恢复入口的消费分流是 S7 的活，本切片只立相位机械）。
    settling 相位用 models.TurnPhase.SETTLING（单一真源已下沉 models，无循环）。settling 已是入口态时直接 return（幂等守门）：
    「不再重跑前半段」正是 settling 的语义，恢复后重进 pre_settle 不二次落财政。

    auto_submit_due_secret_orders（原在 resolve_directives 调用点）挪入本事务：它只是
    「推演前的确定性写」，崩溃时密令呈递须随财政一并回滚；挪入不改它先于世界段的事实。
    """
    # 幂等守门：前半段已提交相位（FRONT_HALF_DONE_PHASES 单一真源）重进不重跑财政
    # （防二次 tick，cmr S4 r2/r3）。早退**不消费**暂存动作。所有权规则（cmr S7 r5/r6）：
    # ① 正常路=pre_settle 前半段事务内 commit（下方正常体）——ADR 0006 要求推演前盘面
    #   已定，动作必须先于世界段提交；后续步骤失败时前半段保持已落是 ADR 决定 2
    #   明文设计（「pre_settle 的效果在中止/重试时保持已落，这是设计而非缺陷」），非半写。
    # ② 前半段已提交后（本守门内）新 stage 的动作=推进回合的终端写路
    #   各自在 atomic 内 commit；
    #   早退路在事务外 commit 会让恢复中的后续步骤失败时动作已提交而回合未推进。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        return []
    if transit_arrivals_out is not None:
        transit_arrivals_out.clear()
    auto_triggered: List[Dict[str, object]] = []
    # #498：颁诏遇开夜 → 顺势自动收夜（王承恩代宣）；在飞回话 fail-closed 中止，不进 settling。
    # 放在 atomic 外：收夜提交与错误包独立；成功后 pre_settle 事务内 commit_pending 仍幂等。
    # #503：收夜 beat 生产路径接通编排缝。
    from ming_sim.audience_night import auto_close_open_night
    auto_close_open_night(db, state, content=content)
    # atomic + 最外层回滚后从 DB 重载（ADR 0008 决定 3 第三条）：apply_fixed_period_flows 直改了
    # state.metrics（flows.py:192）、尾部 turn_phase 已被赋 settling，脏 settling 会被下次 pre_settle
    # 守门跳过=该月财政永久丢（cmr S4 r1 F4）。嵌套时跳过 reload，由最外层拥有者处理。见 atomic_and_reload。
    collector = RejectionCollector()
    try:
        with atomic_and_reload(
            db, state, content=content,
            on_error=lambda _exc: collector.reset(),
        ):
            # 动作闸门(ADR 0006)：颁诏最前批量落库本回合暂存的结构化聊天写动作（密令更新/催办/任免/…），
            # 在跑月链世界段前，使后续步骤读到已落账的聊天动作。
            # 无聊天暂存时为空操作；committed 行不重跑。
            # #1560 / CONTEXT：过回合丢弃既有 failed secret-order intents，再 commit；
            # 顺序在 commit 前，避免误清同次 commit 新产生的 failure。
            discarded_failed = db.discard_failed_secret_order_intents()
            if discarded_failed:
                tlog(f"[pending_actions] 过回合丢弃既有 failed 密令意图 {discarded_failed} 条")
            committed = db.commit_pending_actions(
                state, content=content,
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
            # 落账副作用；明细不再进 simulator payload（欠饷哗变走前置事件/issue）
            apply_fixed_period_flows(db, state)
            # 0095/#668 在途倒数 tick：remaining -= 1.0*factor，≤0 引擎抵达。
            # 世界事件判门在逐旨落账后才读 location，抵达须先在本段落定。
            arrivals = tick_transit_arrivals(db, state, content, commit=False)
            if transit_arrivals_out is not None:
                transit_arrivals_out.clear()
                transit_arrivals_out.extend(arrivals)
            if arrivals:
                tlog(f"[transit-tick] 本月抵达 {len(arrivals)} 人：{[a['name'] for a in arrivals]}")
            # #1895：原 #625 孤直稽核反制硬门退役——代码不再按 integrity 档
            # 判定「这位大臣会不会反制」并 hash 指定反制形态。监督在场／连续月数／
            # 稽核人派系操守等事实仍留在 dossier_supervision_presence 与
            # build_supervision_judge_surface 供料面；是否反制、采取何种行动由
            # #1861 逐旨推演／#1843 世界段 run 依人物可及事实自选。
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
    携原始 delta 项（'item' 键）→ 桥接解包存原件；仅未迁 section
    （secret_order_* 等）无 'item' 键时才兜底存 wrapper 回显记录。
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


def resolve_decisions_phase2(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    content=None,
    cheat_directive: str = "",
) -> str:
    """phase2：皇帝亲裁完，读回 phase1 暂存上下文 + 已存决策点选择，续跑结算。
    要求本回合处于 awaiting_decision（已有 resolve_context）。返回完整结算报告。"""
    ctx = db.get_resolve_context(state.turn)
    if ctx is None:
        raise LLMContractError("无待决推演上下文，无法续跑结算（phase1 未暂停或已结算）。")
    before_turn = state.turn
    from ming_sim.month_chain import run_player_month_chain
    result = run_player_month_chain(
        state, db, agno_db, llm_config,
        decree_text=str(ctx.get("decree_text") or ""),
        content=content,
        source=_provenance_from_stored(ctx.get("source")),
        cheat_directive=cheat_directive,
    )
    return result.report
