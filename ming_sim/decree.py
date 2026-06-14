"""诏书生成与回合结算：拟诏、推演落库、无诏推进。L7。

纯逻辑（无 input()）；resolve_directives 的 print 是诊断输出，非交互。
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional

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
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector, atomic
from ming_sim.cli_backend import cli_backend_parallel_safe
from ming_sim.constants import TURN_UNIT
from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
from ming_sim.db import GameDB
from ming_sim.error_pack import (
    _next_attempt,
    clear_for_resimulation,
    rejections_jsonl_path,
    settlement_abort_message,
    write_error_pack,
)
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
    # atomic + 最外层回滚后从 DB 重载刷净内存（state.metrics 直加 / next_period / turn_phase
    # 留脏）：公共内核见 atomic_and_reload（ADR 0008 决定 3，reload 再炸链上抛 cmr S5 r2）。
    with atomic_and_reload(db, state, content=content, registry=registry):
        db.commit_pending_actions(state, content=content, registry=registry)
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


def group_secret_orders_for_sim(
    rows: List[Dict[str, object]],
) -> Dict[str, List[Dict[str, object]]]:
    """把密令 DB 行按状态分进中文键两组，作喂 simulator/extractor 的承载形状（#48）。

    输入 = db.list_secret_orders 返回的行（含英文 status）；输出 =
    `{"在办": [...], "待核议": [...]}`。英文 status（active/pending_review）只用来分组，
    **不当字段进 LLM 输入**——否则 simulator 把它照抄进「密旨动向」邸报段，中文游戏里
    冒出「孙承宗密旨（active）」（本 issue 根因）。条目保留
    id/minister_name/title/content[:120]/turn_issued/due_turn/progress/sim_note，不含 status。
    done/failed/cancelled 是裁决输出、无注入需求，落到此函数时忽略不进任何组。

    单点改：fan-out 到 simulator 推演、extractor 抽取、恢复存档三处同一承载，形状一致。
    """
    groups: Dict[str, List[Dict[str, object]]] = {"在办": [], "待核议": []}
    bucket = {"active": "在办", "pending_review": "待核议"}
    # 恢复路也用本函数重分组旧存档 list（见 _recovered_grouped）；损坏/历史遗留数据可能非 list
    # 或含非 dict 元素，照 simulation._clean_* 的守门惯例跳过，不让 TypeError 崩在恢复链上。
    if not isinstance(rows, list):
        return groups
    for o in rows:
        if not isinstance(o, dict):
            continue
        key = bucket.get(o.get("status"))
        if key is None:
            continue
        # 字符串字段一律 str() 兜底：损坏存档里若为非字符串（如 content 是整数），切片/落库
        # 不致 TypeError（照 simulation._clean_* 的 `str(item.get(...) or "")` 惯例）。
        groups[key].append({
            "id": int(o.get("id") or 0),
            "minister_name": str(o.get("minister_name") or ""),
            "title": str(o.get("title") or ""),
            "content": str(o.get("content") or "")[:120],
            "turn_issued": o.get("turn_issued") or 0,
            "due_turn": o.get("due_turn") or 0,
            # DB 行的进展在 result；已分组过的旧承载条目在 progress——两者都收，使本函数
            # 能就地重分组旧 list 形状 ctx（恢复端归一，见 _recovered_grouped）。
            "progress": str(o.get("result") or o.get("progress") or ""),
            "sim_note": str(o.get("sim_note") or ""),     # 上轮推演写的副作用
        })
    return groups


def _recovered_grouped(value: object) -> Dict[str, object]:
    """恢复路把存档里的 secret_orders 归一成分组 dict（#48 恢复端闭环）。

    新档已是分组 dict → 原样返回。**部署前存的旧 list 形状 ctx** → 按状态重分组、剥英文
    status（旧条目仍带 status，可据以分桶）：否则把扁平 list 透传给改读 `secret_orders.在办`/
    `待核议` 的新 extractor prompt，HITL 续跑会漏抽密令副作用/结案。其余杂值 → 空 dict。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return group_secret_orders_for_sim(value)
    return {}


def _select_secret_orders_for_sim(db: GameDB, cap: int = 20) -> List[Dict[str, object]]:
    """选注入月末推演的密令：**pending_review 全进**（到期密令本回合须给 done/failed 裁决，被截断会
    永久卡住不结案）+ active 填满剩余预算（cap）。修 #108：旧码 `(active + pending_review)[:cap]`
    在 active 满载 cap 时把所有 pending_review 整体切掉、饿死核议。pending_review 即便超 cap 也全保。"""
    pending = db.list_secret_orders(status="pending_review")
    active = db.list_secret_orders(status="active")
    return pending + active[: max(0, cap - len(pending))]


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
    with atomic_and_reload(db, state, content=content, registry=registry):
        auto_triggered = pre_settle(
            state, db, on_stage=lambda label: _emit("stage", label),
            content=content, registry=registry)
        db.save_resolve_context(
            state.turn, decree_text, "", {},
            secret_orders={}, relevant_memories=[],   # #48：占位用分组承载的空 dict（旋即被真存覆盖）
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
        # ADR 0008 S7（决定 2）：fallback 是降级正常路径，其推进写序列同样整体包 atomic
        # ——崩在其中(只可能是代码异常，simulator 失败已被本 except 接住)则全回滚、内存从 DB
        # 重载、回合不前进，与正常路/advance 同语义。此路无 LLM 产出、无 resolve_context 入真源
        # （extractor 被跳过），故不写错误包——裸异常透传（上游 user 边界按普通错误处理；本
        # 路本就不抛 SettlementAbort）。pre_settle 自有 atomic 在本 except 之前已提交，不嵌套。
        # 回滚后内存从 DB 重载（同 pre_settle 先例），链式 re-raise 不吞（fail-loud）。见 atomic_and_reload。
        with atomic_and_reload(db, state, content=content, registry=registry):
            # 终端写路所有权：fallback 推进回合，暂存动作在此 atomic 内 commit
            # （幂等；守门早退已不消费，不补则成孤儿，cmr S7 r5）。
            db.commit_pending_actions(state, content=content, registry=registry)
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
        # 五个事务块同款（ADR 决定 3）：回滚后内存与 DB 同源——不 reload 的话内存留
        # awaiting/DB 回滚回 settling，进程内重试走 awaiting 幂等叉读空决策=死胡同
        # （ship-pre r2）。嵌套时跳过，最外层拥有者处理。见 atomic_and_reload。
        with atomic_and_reload(db, state, content=content, registry=registry):
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
    # 暂存动作 commit 已下沉进 settle_with_delta 的 atomic 体内（与结算同生死，
    # cmr S7 r4）——此处不再事务外预 commit。
    try:
        report = _replay_settle(
            state, db, agno_db, llm_config, extracted,
            before_turn=before_turn, decree_text=decree_text, narrative=narrative,
            content=content, registry=registry, _emit=_emit,
        )
    except SettlementAbort as abort_exc:
        # 重放炸 = 值级毒 delta（shape 门挡不住）。不清 context 的话每次重试同样重放
        # 同样炸=永久软死锁（ADR 决定 6 预言）；原 delta 已在错误包留档不丢证据，
        # 降级让下次重试自然走重新推演（决定 6 逃生口在此接线，cmr S7 r2/r3）。
        # 逃生口自身炸不得顶替 SettlementAbort——terminal 只接它，顶替=玩家指引丢失
        # （cmr S7 r4，与本文件链式惯例一致）。
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
    content,
    registry,
    _emit: Callable[[str, str], None],
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
            d, s, ex, content=ct, registry=rg, llm_config=llm_config
        ),
        on_stage=lambda label: _emit("stage", label),
        source=Provenance.system_simulation,
    )
    return report


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
    secret_orders: Dict[str, object],
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
        # 仅并发安全的 CLI runner（codex，--ephemeral 隔离）下并发跑 4 个 extractor（#83，省约 1 分钟）；
        # claude/agy/api/形态1 → cli_backend_parallel_safe=False → 串行不变。合并/落库仍串行单事务（ADR 0008）。
        extracted, extractor_output, extractor_input = extract_scores_by_modules_with_agno(
            extractors, db, state, effective_narrative, decree_text=decree_text, sanitizer=sanitizer,
            relevant_memories=relevant_memories,
            secret_orders=secret_orders_for_sim,
            parallel=cli_backend_parallel_safe(llm_config),
        )
        # shape 垃圾的 extractor 产物 = extractor 失败：在 try 内验形，让它走同一条
        # pack+SettlementAbort 路（ship-pre r4）——留给 persist 的裸 ValueError 没有
        # 用户边界接（CLI 原始 traceback 崩出、无错误包）。persist 自身仍二次验形
        # （driver 路防线，幂等）。
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
    # 持久化前过 validate_delta_shape：畸形 delta 响亮抛错且绝不入真源（防毒钉死锁，见 persist_resolve_context）。
    # before_turn == state.turn（next_period 尚未执行），与 settle 内 clear 同键。
    # 走到这里 = extractor 真成功（失败已在上方响亮中止，S6）——失败产物永不入真源。
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
        # extractor 产出属推演管线（决定 5 provenance）；driver 信封路保持 unknown 兜底。
        # 按 source 细分到 player_decree/hitl_decision 需 extractor schema 扩来源字段（后续波次）。
        source=Provenance.system_simulation,
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
    # atomic + 最外层回滚后从 DB 重载（ADR 0008 决定 3 第三条）：apply_fixed_period_flows 直改了
    # state.metrics（flows.py:192）、尾部 turn_phase 已被赋 settling，脏 settling 会被下次 pre_settle
    # 守门跳过=该月财政永久丢（cmr S4 r1 F4）。嵌套时跳过 reload，由最外层拥有者处理。见 atomic_and_reload。
    with atomic_and_reload(db, state, content=content, registry=registry):
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
                    item=item.get("item", item) if isinstance(item.get("item", None), (dict, list, str)) else item,
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


def _player_visible_extractor_output(applied: object) -> object:
    if not isinstance(applied, dict):
        return applied
    visible = dict(applied)
    visible.pop("person_changes", None)
    issue_summary = visible.get("issue_summary")
    if isinstance(issue_summary, dict):
        issue_person_changes = issue_summary.get("applied_person_changes")
        if isinstance(issue_person_changes, list) and issue_person_changes:
            direct = visible.get("applied_person_changes")
            merged = list(direct) if isinstance(direct, list) else []
            merged.extend(issue_person_changes)
            visible["applied_person_changes"] = merged
    return _strip_player_internal_fields(visible)


def _strip_player_internal_fields(value: object) -> object:
    if isinstance(value, list):
        return [_strip_player_internal_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_player_internal_fields(item)
            for key, item in value.items()
            if key not in {"item", "report_section", "report_category"}
        }
    return value


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

    # 把 narrative 与诏书写入 turn_logs 作下月前文
    db.record_log(state, narrative[:1200])
    db.save_turn_report(state, narrative)

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
    # #48 恢复端闭环：HITL 续跑直接复用存档的 narrative + simulator_payload（不重推演），
    # extractor 实际从 simulator_payload 读密令分组（module 模式剔除补充上下文里的副本）。
    # 故把分组承载归一成 dict——新档原样、旧 list 形状 ctx 就地重分组——再喂下游，使新
    # extractor prompt（读 secret_orders.在办/待核议）在旧档恢复时也不漏抽密令副作用/结案。
    sim_payload = ctx["simulator_payload"] if isinstance(ctx["simulator_payload"], dict) else {}
    if isinstance(sim_payload.get("secret_orders"), list):
        sim_payload = {**sim_payload, "secret_orders": _recovered_grouped(sim_payload["secret_orders"])}
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
