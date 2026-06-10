"""诏书生成与回合结算：拟诏、推演落库、无诏推进。L7。

纯逻辑（无 input()）；resolve_directives 的 print 是诊断输出，非交互。
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from agno.db.sqlite import SqliteDb

from ming_sim.agents import (
    _dump_llm_messages,
    create_chapter_memory_agent,
    create_decree_writer_agent,
    create_ending_summary_agent,
    create_json_sanitizer_agent,
    create_score_extractor_module_agent,
    create_season_simulator_agent,
    run_agent_text,
)
from ming_sim.applier import atomic
from ming_sim.constants import TURN_UNIT
from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
from ming_sim.db import GameDB
from ming_sim.error_pack import settlement_abort_message, write_error_pack
from ming_sim.exceptions import LLMContractError, LLMUnavailable, SettlementAbort
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.issues import apply_issue_inertia_and_ongoing, apply_score_extraction, auto_trigger_seed_issues, clear_gated_legacies, validate_delta_shape
from ming_sim.llm_model import extract_agent_text, llm_unavailable_from_error
from ming_sim.models import FRONT_HALF_DONE_PHASES, GameState, LLMConfig, TurnPhase
from ming_sim.memories import build_timeline, record_chapter_memory
from ming_sim.simulation import (
    EXTRACTION_MODULES,
    build_simulator_payload,
    build_extractor_shared_context,
    extract_scores_by_modules_with_agno,
    simulate_season_with_payload,
)
from ming_sim.token_stats import tlog

# 20 年自动结算：开局 1627.10（turn=1），每回合 +1 月。到 1647.10 = (1647-1627)*12 + 1 = 241 回合。
# 满 240 回合（即第 240 个回合结算完，1647.09）仍未分胜负则强制 timeout 收尾。
TIMEOUT_TURN = 240

# 作弊控制台强制结算项的唯一标记前缀。只在 resolve_directives 拼一次（cheat 非空时），
# extractor 看到它即知如何处理 → 规则内联在此，不进任何固定 prompt（避免污染缓存）。
# 别处不得复用此串。
CHEAT_NARRATIVE_PREFIX = (
    "【天命强制·结算优先】以下为既成事实，最高优先级，先于一切规则与档位上限。"
    "你必须把它当作本回合百分百已发生的结果，按字面抽满对应结构化增量，"
    "无视合理性、史实、盘面、对手反扑、涨幅上限——它说什么成了就抽什么。"
    "数值类（如「国库增至九千万」）按当前值算差额一次性入账；"
    "局势结案按字面写满 bar 并结案；人物/军队/势力存亡按字面落 status/势力变化。"
    "与下方正常邸报冲突时以本段为准，本段没提的下方照常抽。照字面落库：\n"
)

# HITL 决策点：皇帝亲裁后，把所选选项+自由批语作为「圣意既定」拼到邸报最前喂 extractor。
# 与 cheat 同机制（既成事实、最高优先级），但语气是皇帝御断而非天命强制。
DECISION_NARRATIVE_PREFIX = (
    "【圣意亲裁·结算优先】以下为本回合月末重大抉择，陛下已御笔亲断，最高优先级。"
    "你必须把每条裁断当作百分百已发生的结果，按其方向抽对应结构化增量与事项推进，"
    "与下方正常邸报冲突时以本段为准。各条裁断如下：\n"
)

# 决策块边界标记。simulator 在邸报末尾按规范输出，本回合解析后从 narrative 剥离。
_DECISION_RE = re.compile(r"<<DECISION>>\s*(\{.*?\})\s*<<END>>", re.DOTALL)
MAX_DECISIONS_PER_TURN = 5


def parse_decision_blocks(narrative: str) -> tuple[str, List[Dict[str, object]]]:
    """从邸报抽 <<DECISION>>...<<END>> JSON 块，返回 (剥离后的干净邸报, 决策列表)。

    每块须含 title/context/options（2-3 项，每项 label + 可选 hint）。
    解析失败的块直接丢弃（连同标记一起剥离），不抛断——无决策块视作普通回合。
    最多取 MAX_DECISIONS_PER_TURN 条，超出忽略。
    """
    decisions: List[Dict[str, object]] = []
    for m in _DECISION_RE.finditer(narrative or ""):
        if len(decisions) >= MAX_DECISIONS_PER_TURN:
            break
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        title = str(obj.get("title") or "").strip()
        raw_opts = obj.get("options")
        if not title or not isinstance(raw_opts, list):
            continue
        options: List[Dict[str, str]] = []
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            label = str(o.get("label") or "").strip()
            if not label:
                continue
            options.append({"label": label, "hint": str(o.get("hint") or "").strip()})
        if len(options) < 2:  # 至少给 2 个选项才算有效抉择
            continue
        decisions.append({
            "title": title,
            "context": str(obj.get("context") or "").strip(),
            "options": options[:3],
        })
    clean = _DECISION_RE.sub("", narrative or "").strip()
    return clean, decisions


@dataclass
class ResolveResult:
    """resolve phase1 的返回。awaiting=True 时表示需皇帝亲裁，已存决策点暂停，
    report 为空、回合未推进；调用方据此置 awaiting_decision 态弹窗。
    awaiting=False 时 report 为完整结算报告（含诏书+邸报+结局），回合已推进。"""
    awaiting: bool
    report: str = ""
    decisions: List[Dict[str, object]] = field(default_factory=list)


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


def advance_without_edict(state: GameState, db: GameDB, *, content=None, registry=None) -> None:
    # 退朝未下正式诏书也是月末:先 commit 本回合暂存的结构化写动作(颁诏前未撤回即通过,
    # ADR 0006),否则暂存成孤儿、随 next_period 永久丢失(CMR P1)。须在 next_period 前。
    # content/registry 供 office(任免)落库注册新臣;无则任免落不了(标 failed,不静默)。
    # 暂存动作 commit 幂等（只处理 pending 行），两条分支都跑：守门分支跳过它的话，
    # 崩溃重载后新 stage 的动作随 next_period 成旧回合孤儿死行，违 P1（cmr S4 r3 F4）。
    db.commit_pending_actions(state, content=content, registry=registry)
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        # 崩溃重载后走 skip 路：前半段（财政+auto_trigger+密令）已随 pre_settle 事务提交，
        # 二跑=同回合双财政 tick（cmr S4 r1 F3 / r3 F2）。只走推进尾。
        pass
    else:
        apply_fixed_period_flows(db, state)
    message = f"本{TURN_UNIT}退朝未下正式圣旨，诸事仍待来{TURN_UNIT}处置。"
    db.record_log(state, message)
    print("\n" + message)
    # 推进回合的路都得清本回合 resolve_context：崩溃重试后改走此路时，留下的
    # ready=1 行会被恢复入口当「未完成回合」重放=double-apply（cmr S2+S3 r4）。
    db.clear_resolve_context(state.turn)
    state.next_period()
    # settling 随推进复位，同 settle_with_delta（cmr S4 r1 F1）。
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)


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
) -> ResolveResult:
    """phase1：跑固定财政 + simulator 写邸报，解析 HITL 决策点。

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

    if not directives:
        advance_without_edict(state, db, content=content, registry=registry)
        return ResolveResult(awaiting=False, report=f"本{TURN_UNIT}未颁正式诏书。")

    before_turn = state.turn

    # 草案内容已由拟诏合并进 decree_text，simulator 只读 decree_text，不再单传逐条草案。

    # 1) 前括号确定性结算：固定月度财政 tick + auto_trigger 硬立 seed 情势（均在 LLM 推演前）。
    #    与探针 driver 共用同一段（ADR 0004）。
    auto_triggered = pre_settle(
        state, db, on_stage=lambda label: _emit("stage", label),
        content=content, registry=registry)

    # 1.8) 历史脉络：取近几回合章节记忆注入推演（章节记忆取代旧的关键词原子检索）。
    relevant_memories: List[Dict] = []
    secret_orders_for_sim: list = []  # try 外初始化：检索失败也不能让后续 NameError
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
        active_orders = (
            db.list_secret_orders(status="active")
            + db.list_secret_orders(status="pending_review")
        )[:20]
        for o in active_orders:
            secret_orders_for_sim.append({
                "id": int(o["id"]),
                "minister_name": o["minister_name"],
                "title": o["title"],
                "content": o["content"][:120],
                "status": o["status"],
                "turn_issued": o.get("turn_issued") or 0,
                "due_turn": o.get("due_turn") or 0,
                "progress": o.get("result") or "",      # 承办人聊天里存的当前进展
                "sim_note": o.get("sim_note") or "",     # 上轮推演写的副作用
            })
        n_active = sum(1 for o in active_orders if o["status"] == "active")
        n_pending = sum(1 for o in active_orders if o["status"] == "pending_review")
        tlog(f"[secret_order] 注入推演 active={n_active} pending_review={n_pending}"
             + (f" titles={[o['title'] for o in active_orders]}" if active_orders else ""))
    except Exception as exc:
        tlog(f"[secret_order] 注入失败，跳过：{exc}")

    # 2) 推演 agent: 写邸报
    tlog("结算 2/4 推演 agent（月末邸报）")
    _emit("stage", "推演月末邸报")
    previous_narrative = db.previous_turn_summary(state) or ""
    simulator_payload = build_simulator_payload(
        state, db, decree_text, previous_narrative,
        deaths_this_turn=deaths_this_turn,
        debuts_this_turn=debuts_this_turn,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders_for_sim,
    )
    simulator = create_season_simulator_agent(
        llm_config, agno_db, state=state, db=db, simulator_payload=simulator_payload
    )
    try:
        narrative, simulator_payload = simulate_season_with_payload(
            simulator, state, db, decree_text, previous_narrative,
            deaths_this_turn=deaths_this_turn,
            debuts_this_turn=debuts_this_turn,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
            simulator_payload=simulator_payload,
            on_thinking=lambda c: _emit("thinking", c),
            on_text=lambda c: _emit("text", c),
        )
    except Exception as exc:
        print(f"[WARN] 推演 agent 失败：{exc}；本{TURN_UNIT}用简化邸报兜底，跳过 LLM 结算。")
        narrative = (
            f"奉天承运皇帝诏曰：本{TURN_UNIT}推演 agent 被服务方拦截，无完整邸报。"
            f"已颁诏书：\n{decree_text}\n"
            f"固定收支已落账，事项 inertia 自然漂移；本{TURN_UNIT}无新立 issue。"
        )
        # 跳过 extractor，避免连锁失败
        db.record_log(state, narrative[:1200])
        db.save_turn_report(state, narrative)
        db.save_turn_extraction(
            state, decree_text=decree_text, narrative=narrative,
            extractor_output=f"[推演 agent 失败] {exc}；本回合跳过 extractor。",
        )
        apply_issue_inertia_and_ongoing(db, state, touched_ids=set())
        for name in clear_gated_legacies(db, state):
            db.record_log(state, f"帝国修正消除：{name}")
        db.mark_directives_issued(state)
        # 同 advance_without_edict：推进回合前清 stale context（cmr S2+S3 r4）。
        db.clear_resolve_context(state.turn)
        state.next_period()
        # 第三条推进尾同样复位 settling（cmr S4 r2）：漏掉的话新回合被守门跳过前半段。
        state.turn_phase = TurnPhase.SUMMONING.value
        db.save_state(state)
        return ResolveResult(
            awaiting=False,
            report=f"\n本{TURN_UNIT}颁布诏书：\n" + decree_text + "\n\n" + narrative,
        )

    # 2.4) HITL 决策点：从邸报抽 <<DECISION>> 块。有 → 存上下文+决策点，暂停等皇帝亲裁。
    #      剥离后的干净邸报落库/展示；决策点选完由 resolve_decisions_phase2 续跑结算。
    narrative, decisions = parse_decision_blocks(narrative)
    if decisions:
        tlog(f"[HITL] 检测到 {len(decisions)} 个决策点，暂停等皇帝亲裁：{[d['title'] for d in decisions]}")
        # 暂停态三件（上下文+决策点+AWAITING 相位）同事务落库（cmr S4 r2）：相位若靠
        # session 事后另笔写，崩在窗口里 DB 停在 settling 而决策已存——web submit_decisions
        # 只认 AWAITING 相位，恢复死路。session 事后那笔写变为幂等。
        with atomic(db):
            db.save_resolve_context(
                state.turn, decree_text, narrative, simulator_payload,
                secret_orders=secret_orders_for_sim, relevant_memories=relevant_memories,
            )
            db.save_pending_decisions(state.turn, decisions)
            state.turn_phase = TurnPhase.AWAITING_DECISION.value
            db.save_state(state)
        return ResolveResult(awaiting=True, decisions=db.list_pending_decisions(state.turn))

    # 无决策点：透明续跑结算（cheat 仍可叠加）。
    report = _settle_after_narrative(
        state, db, agno_db, llm_config, decree_text, narrative,
        simulator_payload=simulator_payload,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders_for_sim,
        before_turn=before_turn, _emit=_emit,
        content=content, registry=registry,
        cheat_directive=cheat_directive,
    )
    return ResolveResult(awaiting=False, report=report)


def persist_resolve_context(
    db: GameDB,
    turn: int,
    extracted: Dict[str, object],
    *,
    decree_text: str,
    narrative: str,
    simulator_payload: Dict[str, object],
    secret_orders: list,
    relevant_memories: List[Dict],
) -> None:
    """ADR 0008 S2：每回合进入结算后半段前无条件持久化 resolve_context（extractor delta + 叙事）。

    重跑真源：跨进程恢复从此重灌，不重跑贵的 simulator/extractor。
    **持久化前先过 validate_delta_shape**——形状畸形的 delta 绝不入 resolve_context
    （否则钉进重试真源：apply 永崩、而「重跑 extractor」被「context 已存在」挡死=soft-lock）。
    校验失败响亮抛 ValueError，save 不执行。注意此门只挡形状毒：shape 合法但值级
    必炸的 payload（如 new_armies 项里非数值兵力）由 ADR 0008 决定 6 的「重新推演」
    逃生口兜底（清 context 重产 delta），S4 恢复入口不得假设 ready=1 即重放安全。
    """
    validate_delta_shape(extracted)  # 抛 → save 不执行，毒 payload 不钉进真源
    db.save_resolve_context(
        turn, decree_text, narrative, simulator_payload,
        secret_orders=secret_orders, relevant_memories=relevant_memories,
        extracted=extracted,
    )


def _settle_after_narrative(
    state: GameState,
    db: GameDB,
    agno_db: SqliteDb,
    llm_config: LLMConfig,
    decree_text: str,
    narrative: str,
    simulator_payload: Dict[str, object],
    relevant_memories: List[Dict],
    secret_orders: list,
    before_turn: int,
    _emit: Callable[[str, str], None],
    content=None,
    registry=None,
    cheat_directive: str = "",
    decision_directive: str = "",
) -> str:
    """phase2：邸报已定（已剥离决策块），跑 extractor→落库→章节记忆→结局→推进。
    cheat_directive / decision_directive 各自拼到 effective_narrative 最前喂 extractor。"""
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
    extractor_shared_context = build_extractor_shared_context(
        db, state, effective_narrative, decree_text,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders_for_sim,
    )
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
                supplemental_context=extractor_shared_context,
            )
            for module in EXTRACTION_MODULES
        }
        extracted, extractor_output, extractor_input = extract_scores_by_modules_with_agno(
            extractors, db, state, effective_narrative, decree_text=decree_text, sanitizer=sanitizer,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
        )
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
        except BaseException as pack_exc:
            # 写包自身炸（磁盘满/路径不可写）不得顶替原 extractor 异常（同 pre_settle
            # reload 先例 raise exc from ...）：原异常是真因，写包失败是次生。
            raise exc from pack_exc
        raise SettlementAbort(
            settlement_abort_message(pack_path),
            turn=before_turn, stage="extract", error_pack_path=pack_path,
        ) from exc
    else:
        extractor_ok = True

    # ADR 0008 S2：进入结算后半段（settle_with_delta 动 DB）前，持久化 resolve_context
    # （extractor delta + 叙事）作重跑真源——跨进程恢复从它重灌，不重跑贵的 simulator/extractor。
    # 持久化前过 validate_delta_shape：畸形 delta 响亮抛错且绝不入真源（防毒钉死锁，见 persist_resolve_context）。
    # before_turn == state.turn（next_period 尚未执行），与 settle 内 clear 同键。
    # 仅 extractor 真成功才入真源：失败的 {} 占位若持久化，恢复入口会当真 delta
    # 重放=整月效果静默丢（cmr S2+S3 F1；响亮中止是 S6 的活，in-process 路径暂照旧）。
    if extractor_ok:
        persist_resolve_context(
            db, before_turn, extracted,
            decree_text=decree_text, narrative=narrative,
            simulator_payload=simulator_payload,
            secret_orders=secret_orders_for_sim,
            relevant_memories=relevant_memories,
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
            d, s, ex, content=ct, registry=rg, llm_config=llm_config
        ),
        on_stage=lambda label: _emit("stage", label),
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


def pre_settle(
    state: GameState, db: GameDB, *, on_stage=None, content=None, registry=None,
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
    # （防二次 tick，cmr S4 r2/r3）。暂存动作 commit 幂等、早退前仍要跑：崩溃重载后
    # 新 stage 的动作不 commit 会成孤儿死行，违 P1（cmr S4 r3 F4）。
    if state.turn_phase in FRONT_HALF_DONE_PHASES:
        committed = db.commit_pending_actions(state, content=content, registry=registry)
        if committed:
            tlog(f"[pending_actions] 守门早退前落库 {len(committed)} 条")
        return []
    auto_triggered: List[Dict[str, object]] = []
    try:
        with atomic(db):
            # 动作闸门(ADR 0006)：颁诏最前批量落库本回合暂存的结构化聊天写动作（密令更新/催办/任免/…），
            # 在跑 LLM 结算管线前，使 simulator/extractor 读到的盘面与旧「召对期直写」时序一致。
            # driver 路径无聊天暂存 → 空 no-op。幂等（committed 行不重跑）。
            committed = db.commit_pending_actions(state, content=content, registry=registry)
            if committed:
                tlog(f"[pending_actions] 颁诏批量落库 {len(committed)} 条：{[(c['kind'], c['action']) for c in committed]}")
            tlog("结算 1/4 固定月度财政 tick")
            if on_stage is not None:
                on_stage("固定月度财政入账")
            # 落账副作用；明细不再进 simulator payload（欠饷哗变走前置事件/issue）
            apply_fixed_period_flows(db, state)
            # 程序硬触发：标了 auto_trigger 的 seed 情势，gate 达标即由程序直接立项，绕过 LLM 因果判定。
            auto_triggered = auto_trigger_seed_issues(state, db)
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
        # atomic 已回滚 SQLite（仅当本层是最外层），但内存副作用留脏（ADR 0008 决定 3 第三条）：
        # apply_fixed_period_flows 直改了 state.metrics（flows.py:192）、尾部 turn_phase 已被赋 settling。
        # 回滚后立即把 state 从 DB 重载刷净——否则脏 settling 会被下次 pre_settle 守门跳过=该月财政
        # 永久丢（cmr S4 r1 F4），脏 metrics 污染重跑读数。reload 后 re-raise 原异常（fail-loud）；
        # reload 自身再炸（如盘故障连带）时原异常不被顶替，链上抛（cmr S5 r2）。
        # 嵌套在外层 atomic 内时回滚尚未发生，load_state 会读到未提交脏写——跳过 reload，
        # 由最外层拥有者真回滚后处理（cmr S5 r1）。
        if getattr(db.conn, "_atomic_depth", 0) == 0:
            try:
                reload_state_from_db(db, state, content=content, registry=registry)
            except BaseException as reload_exc:
                raise exc from reload_exc
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
) -> str:
    """确定性结算「后括号」：apply→turn_logs→章节记忆→inertia→clear→结局判定→next_period。

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

    tlog("结算 4/4 落库 + inertia/ongoing")
    _stage("落库与事项推进")
    if delta_applier is not None:
        applied = delta_applier(db, state, extracted, content, registry)
    else:
        applied = apply_score_extraction(db, state, extracted, content=content, registry=registry)

    # 把 narrative 与诏书写入 turn_logs 作下月前文
    db.record_log(state, narrative[:1200])
    db.save_turn_report(state, narrative)
    # 推演链原始输入/输出留痕，事后可追「该立的 issue 为何没立」。
    db.save_turn_extraction(
        state,
        decree_text=decree_text,
        narrative=trace_narrative,  # 留痕含作弊段，便于事后追「为何这么落库」
        extractor_input=extractor_input,
        extractor_output=extractor_output,
    )

    # 章节记忆：注入回调（真实流程= LLM 浓缩落 event_memories；driver= None 跳过）。失败不抛断。
    _stage("记起居注")
    if chapter_recorder is not None:
        try:
            chapter_recorder(db, state, decree_text, narrative, applied)
        except Exception as exc:
            tlog(f"[chapter-memory] 跳过：{exc}")

    # 落 inertia + ongoing (未被本月 issue_advances 触动的)
    touched_ids = set()
    for adv in applied.get("issue_summary", {}).get("advances", []) or []:
        touched_ids.add(int(adv.get("issue_id") or 0))
    apply_issue_inertia_and_ongoing(db, state, touched_ids=touched_ids)

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
    # 注意：此刻 save_state 与本清仍是两次独立 commit，「已提交但 context 残留」的崩溃
    # 窗口尚未闭合——本切片只把位置摆好，S7 把整段包进 atomic 后窗口才真正关掉
    # （cmr S2+S3 codex R2，defer→S7，S7 须加该崩溃点回归测试）。
    db.clear_resolve_context(before_turn)

    ending = ""
    if ended:
        label = ENDING_LABELS.get(str(outcome.get("status")), "结局")
        ending = f"\n\n【结局·{label}】{outcome.get('summary', '')}"
        if ending_text:
            ending += "\n\n" + ending_text
    full_report = f"\n本{TURN_UNIT}颁布诏书：\n" + decree_text + "\n\n" + narrative + ending
    return full_report


def _format_decision_directive(decisions: List[Dict[str, object]]) -> str:
    """把皇帝已裁的决策点拼成喂 extractor 的「圣意亲裁」正文。
    每条：标题 + 所选选项 label/hint + 自由批语。未裁的跳过。"""
    lines: List[str] = []
    for i, d in enumerate(decisions, 1):
        choice = d.get("choice") or {}
        if not isinstance(choice, dict):
            continue
        label = str(choice.get("label") or "").strip()
        note = str(choice.get("note") or "").strip()
        if not label and not note:
            continue
        title = str(d.get("title") or f"抉择{i}").strip()
        seg = f"{i}. 【{title}】陛下御断：{label or '（未选预设项）'}"
        hint = str(choice.get("hint") or "").strip()
        if hint:
            seg += f"（倾向：{hint}）"
        if note:
            seg += f"。朱批：{note}"
        lines.append(seg)
    return "\n".join(lines)


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
    decisions = db.list_pending_decisions(state.turn)
    decision_directive = _format_decision_directive(decisions)
    before_turn = state.turn
    report = _settle_after_narrative(
        state, db, agno_db, llm_config,
        decree_text=str(ctx["decree_text"]),
        narrative=str(ctx["narrative"]),
        simulator_payload=ctx["simulator_payload"] if isinstance(ctx["simulator_payload"], dict) else {},
        relevant_memories=ctx["relevant_memories"] if isinstance(ctx["relevant_memories"], list) else [],
        secret_orders=ctx["secret_orders"] if isinstance(ctx["secret_orders"], list) else [],
        before_turn=before_turn, _emit=_emit,
        content=content, registry=registry,
        cheat_directive=cheat_directive,
        decision_directive=decision_directive,
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
