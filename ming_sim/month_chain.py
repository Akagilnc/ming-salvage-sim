"""ADR 0157 玩家过月主链：步骤 1–3，以及步骤 4–6 的继续条件。

#1846: existing monthly progress and saved night directives are the recovery sources.

#1847：步骤 4 请旨/打回三选统一收口既有 HITL 案头；答复后从问处续推再交步骤 5。
批红文书页呈现归 #1826。#1862：批红与全部效果落定后，邸报作者一次写出标题和正文，
入档后交回本链推进。推进后的机械尾（#1845：关系／派系酿制与结局总评）由本链
调度到 SessionWriteQueue 后台票，下次过月前 join。不另造平行机制。不另建无旨
快路，也不再走五模块 extractor。
"""

from __future__ import annotations
from ming_sim.applier import parse_engine_payload_json
from ming_sim.applier import list_rejection_reports_for_turn

from ming_sim.settlement.dossier import apply_dossier_promulgation, apply_dossier_verdict_metadata
import re
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional

from ming_sim.applier import Provenance, atomic
from ming_sim.models import _load_durable_json_list

_CHAIN_KEY = "month_chain"
_WORLD_QUESTION_PREFIX = "world-question:"
_DECREE_QUESTION_PREFIX = "decree-question:"
# #1891：请饷／议停请旨的案头身份前缀。真实事件身份在交接时绑定（真实 id 藏在前缀后），
# 不从疏文猜配（ADR 0115）。与 world-question/decree-question 同列：都是案头身份，
# 不是 events 表事件，故不进 event_triggers 的普通回写分支。
_LEVY_PETITION_PREFIX = "levy-petition:"
# 与 <<DECISION>> 同一类机标：切前缀与交接读取共用这一条，不另写切分。
# 括号里是整段载荷。只认 `{...}` 会把 null / 数组看成「没有块」。
_LEVY_BLOCK_RE = re.compile(r"<<LEVY>>(.*?)<<END>>", re.DOTALL)
_LEVY_OPEN = "<<LEVY>>"
# 世界段生产指令与用户消息里的交接契约共用这一句，避免一边只认 DECISION。
LEVY_HANDOFF_RULE = (
    "levy_petitions 的数组顺序就是本月交接顺序。"
    "上疏时按这个顺序逐件写 <<LEVY>>{title, context, options}<<END>>，"
    "块内不写事件 id；写了也不作关联。"
    "块数必须与名单等长。不再上疏的一件写 {\"present\": false}。"
    "presentation_due 为 true 的必须写成请旨，不能写 present false。"
    "presentation_due 为 false 的由你决定是否再上疏；一件都不上时整段不写 LEVY 块。"
    "普通请旨仍用 <<DECISION>>，不能代替 LEVY 块，也不承担请饷事件身份。"
)


def _session_owner(db: Any, state: Any, llm_config: Any, agno_db: Any, content: Any):
    from ming_sim.decree_forecast import _owner_for

    owner = _owner_for(db)
    if owner is None or getattr(owner, "db", None) is not db:
        return SimpleNamespace(
            db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content,
        )
    owner.state = state
    if llm_config is not None:
        owner.llm_config = llm_config
    if agno_db is not None:
        owner.agno_db = agno_db
    return owner


def run_world_segment_text(
    db: Any, state: Any, llm_config: Any,
    cheat_directive: str = "",
) -> str:
    """落账后的盘面只推演一次；缺模型时停在本段，不伪造已完成。"""
    if llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段缺少模型配置", stage="world_text")
    from ming_sim.agents import create_world_segment_agent, run_agent_text
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import prepare_world_materials, release_material_tree

    prepared = prepare_world_materials(db, state)
    try:
        agent = create_world_segment_agent(llm_config, prepared)
        return run_agent_text(
            agent, _world_segment_message(db, state, cheat_directive),
            tag="world-segment",
            transport_policy=audience_transport_policy(),
        )
    finally:
        release_material_tree(prepared.root)


def _world_segment_message(db: Any, state: Any, cheat_directive: str) -> str:
    """#1891：本月可呈的请饷／议停事件随世界段消息交接（材料＋军费实况已在目录）。

    只是供料：怎么陈情、拟什么旨，由过月模型自己判断（ADR 0153 / P6）。不给判定
    指令、不代它写疏文——P7 下疏文必须由模型长出。是否上疏的权限按 #1891 分两层：
    本月到点、尚未呈过的应呈请；已留中过的（re_presentation）由大臣自决是否再上。

    这份名单与月链 ``chain["levy_petitions"]`` 取自同一次交接：月链在推演前取定并存
    链，推演时账本尚未变动（纯读函数），身份钉定再读链上那份快照。
    """
    import json

    from ming_sim.issues import list_fiscal_levy_petitions_due

    petitions = list_fiscal_levy_petitions_due(state, db)
    message = "推演本月世界段。"
    if str(cheat_directive or "").strip():
        message = str(cheat_directive) + "\n" + message
    if not petitions:
        return message
    return json.dumps({
        "instruction": message,
        "levy_petitions": petitions,
        "levy_petitions_contract": LEVY_HANDOFF_RULE,
    }, ensure_ascii=False)


def _unclosed_levy_opener(text: str) -> Optional[int]:
    """``<<LEVY>>`` 已经写下、但没有落到闭合 ``<<END>>`` 的起点。

    闭合块内部再出现这四个字不算第二处开头。没有开头是合法缺席，不是坏块。
    """
    raw = text or ""
    covered = [(match.start(), match.end()) for match in _LEVY_BLOCK_RE.finditer(raw)]
    idx = 0
    while True:
        open_at = raw.find(_LEVY_OPEN, idx)
        if open_at < 0:
            return None
        if any(start <= open_at < end for start, end in covered):
            idx = open_at + len(_LEVY_OPEN)
            continue
        return open_at


def _levy_handoff_blocks(text: str, turn: int) -> List[Dict[str, Any]]:
    """按出现顺序读 <<LEVY>> 块。块内的事件 id 不是绑定源，读的时候丢掉。"""
    import json

    from ming_sim.exceptions import SettlementAbort
    from ming_sim.settlement_payload import parse_decision_blocks

    if _unclosed_levy_opener(text) is not None:
        raise SettlementAbort(
            "请饷交接块未闭合",
            turn=int(turn), stage="world_bind",
        )
    blocks: List[Dict[str, Any]] = []
    for match in _LEVY_BLOCK_RE.finditer(text or ""):
        try:
            obj = json.loads(match.group(1).strip())
        except Exception as exc:
            raise SettlementAbort(
                f"请饷交接块 <<LEVY>> JSON 解析失败：{exc}",
                turn=int(turn), stage="world_bind",
            ) from exc
        if not isinstance(obj, dict):
            raise SettlementAbort(
                f"请饷交接块 <<LEVY>> 根须为对象，得 {type(obj).__name__}",
                turn=int(turn), stage="world_bind",
            )
        if obj.get("present") is False:
            blocks.append({"present": False})
            continue
        body = {
            key: value for key, value in obj.items()
            if key not in {"event_id", "origin_ref", "petition_ref", "present"}
        }
        parsed = parse_decision_blocks(
            "<<DECISION>>" + json.dumps(body, ensure_ascii=False) + "<<END>>"
        )
        if len(parsed) != 1:
            raise SettlementAbort(
                "请饷交接块不是可上呈的请旨",
                turn=int(turn), stage="world_bind",
            )
        blocks.append(dict(parsed[0]))
    return blocks


def _pin_world_question_identities(
    levy_petitions: List[Dict[str, Any]], questions: List[Dict[str, Any]],
    turn: int = 0, *, world_text: str = "",
) -> List[Dict[str, Any]]:
    """#1891（ADR 0115）：请旨与事件的关联由交接名单的顺序构造，不读回显。

    名单快照的下标就是稳定键。``<<LEVY>>`` 块按同一顺序对齐；块里没有事件 id
    可读，写了也丢掉。普通 ``<<DECISION>>`` 保持世界段请旨，不承担请饷身份。

    显式坏块在读取时失败，不因名单为空或无人应呈而当成没写。名单为空时，合法块
    不占用请旨。有应呈件却没有等长的块，或块数对不上名单，无法唯一对齐，响亮
    失败。已留中的可以整段不写块（不再上疏）；要再上疏就必须与名单等长，不上的
    那件显式 present false。
    """
    from ming_sim.exceptions import SettlementAbort

    roster = levy_petitions
    mandatory = []
    for item in roster:
        event_id = item["event_id"]
        if item["presentation_due"]:
            mandatory.append(event_id)
    # 世界段 questions 是请旨数组，成员坏即整段载荷坏：显式响亮失败，不静默丢请旨。
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            raise SettlementAbort(
                f"世界段请旨成员须为对象：questions[{index}] 得 {type(question).__name__}",
                turn=int(turn), stage="world_bind",
            )
    ordinary = [dict(question) for question in questions]
    # 先读块：显式坏载荷在这里失败，不能因为名单为空或无人应呈就被当成没写块。
    blocks = _levy_handoff_blocks(world_text, turn)
    if not roster:
        return ordinary
    if not blocks:
        if mandatory:
            missing = "、".join(mandatory)
            raise SettlementAbort(
                f"本月到点应呈的请饷事件没有按交接顺序形成请旨：{missing}",
                turn=int(turn), stage="world_bind",
            )
        return ordinary
    if len(blocks) != len(roster):
        raise SettlementAbort(
            f"请饷交接块数与本月名单无法对齐：块 {len(blocks)}，名单 {len(roster)}",
            turn=int(turn), stage="world_bind",
        )
    pinned: List[Dict[str, Any]] = []
    for item, block in zip(roster, blocks):
        event_id = item["event_id"]
        if block.get("present") is False:
            if item["presentation_due"]:
                raise SettlementAbort(
                    f"本月到点应呈的请饷事件没有形成请旨：{event_id}",
                    turn=int(turn), stage="world_bind",
                )
            continue
        row = dict(block)
        row.pop("present", None)
        row["event_id"] = f"{_LEVY_PETITION_PREFIX}{event_id}"
        pinned.append(row)
    return pinned + ordinary


def _month_fact_materials(
    db: Any, state: Any, chain: Dict[str, Any],
) -> Dict[str, Any]:
    """本月事实材料：名义/预推文、实入、拒收、世界段、请旨答复、月初快照。

    材料是事实与原话，不由代码归纳、拼装或投影为「已生效效果」清单。
    整月密报 run 可读密令来源；公开作者只读公开目录。
    """
    turn = int(state.turn)
    nominal: List[Dict[str, Any]] = []
    forecasts: List[str] = []
    rows = db.staged_declarations.read_month_fact_materials((turn,))
    for row in rows:
        decree_ref = str(row["decree_ref"] or "")
        # 已结算声明是内部机械事实；与 parse_engine_payload_json 同权威，
        # 空串/腐坏响亮，不得洗成空声明供料（#1897 E1/K2）。
        try:
            declaration = parse_engine_payload_json(row["declaration_json"])
        except ValueError as exc:
            raise ValueError(
                f"settled declaration_json 无效：{decree_ref}"
            ) from exc
        nominal.append({"decree_ref": decree_ref, "declaration": declaration})
        forecast = row["forecast_text"]
        if isinstance(forecast, str) and forecast.strip():
            forecasts.append(forecast)
    landed: List[Dict[str, Any]] = []
    for row in db.reign.read_month_ledger((turn,)):
        origin = str(row["origin_ref"] or "")
        landed.append({
            "account": row["account"],
            "delta": int(row["delta"]),
            "category": row["category"],
            "reason": row["reason"],
            "origin_ref": origin,
        })
    rejections: List[Dict[str, Any]] = []

    for row in list_rejection_reports_for_turn(db.conn, turn):

        item = parse_engine_payload_json(
            row["item_json"],
        )
        rejections.append(
            {
                "section": row["section"],
                "item": item,
                "reason": row["reason"],
                "category": row["category"],
            }
        )
    answers: List[Dict[str, Any]] = []
    answer_rows = db.issues.list_pending_decisions(turn) + [
        r for r in db.issues.list_rescript_drafts() if r["answered_turn"] == turn
    ]
    for row in answer_rows:
        if str(row.get("status") or "") not in {"decided", "revision_pending"}:
            continue
        choice = row["choice"] or {}
        answers.append({
            **row, "choice": dict(choice),
            "title": row.get("title") or "",
            "label": choice.get("label") or "",
            "note": choice.get("note") or "",
            "event_id": row.get("event_id") or "",
        })
    snapshot = db.month_open_snapshots.get(turn)
    return {
        "nominal": nominal,
        "landed": landed,
        "rejections": rejections,
        "forecasts": forecasts,
        "world_segment": str(chain.get("world_text") or ""),
        "rescript_answers": answers,
        "month_open": snapshot,
    }


def _gazette_feed(db: Any, state: Any) -> Dict[str, Any]:
    """公开目录之外只附日期、可见到期承诺与抵京候见投影。"""
    from ming_sim.audience_night import list_waiting_audience_summons
    from ming_sim.decree import collect_new_arrival_waiting_audience
    from ming_sim.models import reign_period_label
    from ming_sim.knowledge import origin_visible_to
    from ming_sim.settlement_payload import list_due_commitments

    turn = int(state.turn)
    due_commitments = [
        item for item in list_due_commitments(db, state)
        if origin_visible_to(db, item["origin_ref"])
    ]
    return {
        "instruction": "据已落定的实况写本期邸报。title 由你写，report 是全文。",
        "reign_period_label": reign_period_label(int(state.year), int(state.period)),
        "due_commitments": due_commitments,
        "waiting_audience": collect_new_arrival_waiting_audience(
            _persisted_transit_arrivals(db, turn),
            list_waiting_audience_summons(db),
        ),
    }


def transit_arrivals_from_payload(payload: object) -> list:
    """simulator_payload.transit_arrivals 单一读口：缺键/None→[]；list→list；错形响亮。"""
    if not isinstance(payload, dict):
        return []
    if "transit_arrivals" not in payload or payload.get("transit_arrivals") is None:
        return []
    arrivals = payload.get("transit_arrivals")
    if not isinstance(arrivals, list):
        raise ValueError(
            f"simulator_payload.transit_arrivals 须为 list，得 {type(arrivals).__name__}"
        )
    return list(arrivals)


def _persisted_transit_arrivals(db: Any, turn: int) -> list:
    """过月前半段已写入 resolve context 的本月抵达。"""
    ctx = db.resolve_contexts.get(int(turn)) or {}
    payload = ctx.get("simulator_payload") if isinstance(ctx, dict) else None
    return transit_arrivals_from_payload(payload)


def prepare_gazette_author_materials(db: Any, state: Any):
    """Public monthly catalog uses the same provenance boundary as people."""
    from ming_sim.materials import prepare_world_materials
    from ming_sim.knowledge import origin_visible_to, knowledge_row_visible_to

    return prepare_world_materials(
        db, state,
        include_fact=lambda fact: origin_visible_to(db, fact.origin_ref),
        include_event=lambda event: knowledge_row_visible_to(db, event, ""),
        exclude_secret_order_audience=True,
        exclude_secret_order_dossiers=True,
        public_feed=True,
    )


def run_gazette_text(
    db: Any, state: Any, llm_config: Any, *, on_gazette: Any = None,
) -> tuple[str, str]:
    """批红与全部效果落定后的一次邸报写作。返回作者自写的 (title, report)。"""
    import json

    from ming_sim.agents import create_gazette_author_agent, parse_agent_json, run_agent_text
    from ming_sim.exceptions import LLMContractError, LLMUnavailable
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import release_material_tree
    from pydantic_core import from_json

    raw_prefix = ""

    def _on_text(piece: str, replace: bool) -> None:
        nonlocal raw_prefix
        raw_prefix = piece if replace else raw_prefix + piece
        if on_gazette is None:
            return
        if replace:
            on_gazette({"report": ""})
        try:
            data = from_json(raw_prefix, allow_partial="trailing-strings")
        except ValueError:
            # Incomplete JSON is expected here; only the strict terminal decoder
            # decides whether the completed model response satisfies the contract.
            return
        if isinstance(data, dict) and isinstance(data.get("report"), str):
            on_gazette({"report": data["report"]})

    if llm_config is None:
        raise LLMUnavailable("邸报缺少模型配置", stage="gazette")
    prepared = prepare_gazette_author_materials(db, state)
    message = json.dumps(_gazette_feed(db, state), ensure_ascii=False)
    try:
        agent = create_gazette_author_agent(llm_config, prepared)
        raw = run_agent_text(
            agent, message, tag="gazette",
            transport_policy=audience_transport_policy(),
            on_text=_on_text if on_gazette is not None else None,
        )
    finally:
        release_material_tree(prepared.root)
    data = parse_agent_json(raw, "gazette")
    title = data.get("title")
    report = data.get("report")
    if not isinstance(title, str) or not title.strip():
        raise LLMContractError("邸报缺少作者标题", raw_value=data)
    if not isinstance(report, str) or not report.strip():
        raise LLMContractError("邸报缺少正文", raw_value=data)
    if on_gazette is not None:
        on_gazette({"report": report})
    return title, report


def month_chain_call_failure(db: Any, turn: int) -> Optional[Dict[str, Any]]:
    """核账期恢复投影只读：本月链上未消费的调用失败（无则 None）。"""
    chain = _load_chain(db, int(turn))
    failure = chain.get("call_failure")
    if failure is not None and not isinstance(failure, dict):
        raise TypeError(f"month_chain:{turn}.call_failure must be an object, got {failure!r}")
    return failure


def continue_world_after_answers(
    session: Any, chain: Dict[str, Any], *, answers: List[Dict[str, object]], source: Provenance,
    prepared=None,
) -> Optional[Dict[str, object]]:
    from ming_sim.month_translate import _answered_levy_verdicts, dispatch_month_segment

    db, state = session.db, session.state
    turn = int(state.turn)
    event_id = answers[0]["event_id"]
    if event_id not in _world_question_ids(chain, turn):
        event_id = _LEVY_PETITION_PREFIX + event_id
    if event_id not in _world_question_ids(chain, turn):
        return chain.get("declaration_outcome")
    if session.llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段续推缺少模型配置", stage="world-segment-continue")
    products = chain.setdefault("rescript_continuation_texts", {})
    text = products[event_id]
    prefix, extra = _split_at_question(str(text or ""))
    outcome = None

    def mark_continued(result: Any = None) -> None:
        nonlocal outcome
        candidate = _ending_from_dispatch_result(result)
        if candidate is not None:
            chain["declaration_outcome"] = candidate
            outcome = candidate
        _collect_disclosures_from_result(chain, result)
        pinned, chain["world_question_offset"] = _pin_rescript_questions(
            extra, f"{_WORLD_QUESTION_PREFIX}{turn}:", int(chain.get("world_question_offset", 0)),
        )
        chain["world_questions"] = [
            q for q in chain["world_questions"] if q["event_id"] != event_id
        ] + pinned
        chain["world_text"] = str(chain.get("world_text") or "") + "\n" + str(text or "")
        products.pop(event_id)
        _save_chain(db, turn, chain, source=source)

    verdicts = _answered_levy_verdicts(db, turn, answers=answers)
    if prefix.strip() or verdicts:
        result = dispatch_month_segment(
            db, state, segment=prefix, llm_config=session.llm_config, source=source,
            alongside=mark_continued, answered_verdicts=verdicts, prepared=prepared,
        )
        return _ending_from_dispatch_result(result) or outcome
    # 空续推：无落账后果，仍须原子记下已续，避免重入再烧。
    with atomic(db):
        mark_continued(None)
    return outcome


def continue_decree_after_answers(
    session: Any, *, decree_ref: str, answers: List[Dict[str, object]],
    chain: Optional[Dict[str, Any]] = None,
    source: Provenance = Provenance.player_decree,
    prepared=None,
) -> None:
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.month_translate import dispatch_month_segment

    db, state = session.db, session.state
    turn = int(state.turn)
    if chain is None:
        chain = _load_chain(db, turn)
    event_id = answers[0]["event_id"]
    if not any(q.get("event_id") == event_id for q in db.staged_declarations.questions_for(decree_ref)):
        return
    if session.llm_config is None:
        raise LLMUnavailable("旨意续推缺少模型配置", stage="decree-forecast-continue")
    dossier = _dossier_for_decree_ref(db, decree_ref)
    if dossier is None:
        return
    products = chain.setdefault("rescript_continuation_texts", {})
    text = products[event_id]
    prefix, extra = _split_at_question(str(text or ""))
    payload = dossier["payload"]

    def consume(result: Any = None) -> None:
        candidate = _ending_from_dispatch_result(result)
        if candidate is not None:
            chain["declaration_outcome"] = candidate
        _collect_disclosures_from_result(chain, result)
        offsets = chain.setdefault("decree_question_offsets", {})
        pinned, offsets[decree_ref] = _pin_rescript_questions(
            extra, f"{_DECREE_QUESTION_PREFIX}{decree_ref}:", int(offsets.get(decree_ref, 0)),
        )
        remaining = [q for q in db.staged_declarations.questions_for(decree_ref)
                     if q["event_id"] != event_id]
        db.staged_declarations.replace_questions(decree_ref, remaining + pinned, forecast_text=str(text or ""))
        products.pop(event_id)
        _save_chain(db, int(state.turn), chain, source=source)

    if not prefix.strip():
        with atomic(db):
            consume()
        return
    dispatch_month_segment(
        db, state, segment=prefix,
        decree_payload=payload,
        llm_config=session.llm_config,
        source=source,
        alongside=consume, prepared=prepared,
    )


def _run_decree_continuation_text(
    session: Any, dossier: Dict[str, Any], answers: List[Dict[str, object]],
) -> str:
    import json

    from ming_sim.agents import create_decree_forecast_agent, run_agent_text
    from ming_sim.decree_forecast import (
        decree_ref_for_dossier,
        forecast_snapshot,
        release_forecast_materials,
    )
    from ming_sim.llm_transport import audience_transport_policy

    db = session.db
    decree_ref = decree_ref_for_dossier(db, dossier)
    snapshot = getattr(session, "_rescript_decree_snapshot", None)
    owns_snapshot = snapshot is None
    if owns_snapshot:
        snapshot = forecast_snapshot(session, dict(dossier), decree_ref=decree_ref)
    try:
        agent = create_decree_forecast_agent(session.llm_config, snapshot["prepared"])
        return run_agent_text(
            agent,
            json.dumps({
                "instruction": "皇帝已批红答复本旨的一道请旨。只续写这一问的后果；其他请旨各自办理。已落的事实保持原状，相互牵连的后续选择合为一道请旨。",
                "this_decree": snapshot["this_decree"],
                "prior_forecast_text": db.staged_declarations.forecast_text_for(decree_ref),
                "questions": [{"title": a["title"], "context": a["context"], "options": a["options"]}
                              for a in answers],
                "answers": answers,
            }, ensure_ascii=False),
            tag="decree-forecast-continue",
            transport_policy=audience_transport_policy(),
        )
    finally:
        if owns_snapshot:
            release_forecast_materials(snapshot)


def run_player_month_chain(
    state: Any,
    db: Any,
    agno_db: Any,
    llm_config: Any,
    *,
    decree_text: str = "",
    content: Any = None,
    source: Provenance = Provenance.system_simulation,
    cheat_directive: str = "",
    on_gazette: Any = None,
    write_gate_already_held: bool = False,
) -> Any:
    """从现有过月入口继续。已落的旨不动，未落的按序接着落。"""
    from ming_sim.exceptions import LLMUnavailable, SettlementAbort
    from ming_sim.mechanical_tail import ensure_mechanical_tails

    from ming_sim.decree_forecast import _owner_for
    owner = _owner_for(db)
    gate = owner._write_gate if owner is not None and not write_gate_already_held else nullcontext()
    turn = int(state.turn)
    with gate:
        chain = _load_chain(db, turn)

    def abort_from(exc: BaseException) -> None:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise exc
        if isinstance(exc, SettlementAbort) and _load_chain(db, turn).get("call_failure"):
            raise exc
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=str(getattr(exc, "stage", None) or "month_chain"),
            exc=exc,
            kind="model_exhausted" if isinstance(exc, LLMUnavailable) else "code_exception",
        )

    try:
        with gate:
            cheat = str(cheat_directive or "")
            if cheat.strip() and not chain.get("cheat_directive"):
                chain["cheat_directive"] = cheat
                _save_chain(db, turn, chain, decree_text=decree_text, source=source)
            _consume_call_failure_for_retry(db, chain, turn, decree_text, source)
    except Exception as exc:
        with gate:
            abort_from(exc)
    # #1845：下次过月前 join／重开续接上月机械尾。尾异常不改写成月链 call_failure。
    ensure_mechanical_tails(_session_owner(db, state, llm_config, agno_db, content))
    try:
        # Phase-1 Web recovery already holds this non-reentrant gate. Release
        # only the answer legs; their admission/commits take short holds themselves.
        if write_gate_already_held:
            owner._write_gate.release()
        try:
            _consume_rescript_answers(
                SimpleNamespace(db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content),
                chain, source=source,
            )
            # Concurrent submissions share answer claims, not a lock across model calls.
            # Only the last consumer may resume the monthly tail; an in-flight sibling
            # must not cause already-answered questions to be resubmitted or re-applied.
            from ming_sim.decree import ResolveResult
            from ming_sim.rescript_forecast import schedule_forecasts
            jobs = getattr(owner, "_rescript_jobs", None)
            if jobs is not None:
                with owner._write_gate:
                    chain.clear()
                    chain.update(_load_chain(db, turn))
                    if chain.get("call_failure"):
                        raise SettlementAbort(
                            chain["call_failure"]["message"], turn=turn,
                            stage=chain["call_failure"]["step"],
                            error_pack_path=chain["call_failure"].get("error_pack_path"),
                        )
                    desk = _materialize_rescript_desk(db, state, chain)
                    if desk or jobs:
                        if desk:
                            schedule_forecasts(session=owner, chain=chain, desk=desk)
                        return ResolveResult(awaiting=True, decisions=desk or [], advanced=False, stage="rescript")
                    jobs[None] = None  # Exclusive tail claim, held without the write gate.
        finally:
            if write_gate_already_held:
                owner._write_gate.acquire()
        try:
            return _run_loaded_month_chain(
                state, db, agno_db, llm_config, chain,
                decree_text=decree_text, content=content,
                source=source, on_gazette=on_gazette,
            )
        finally:
            if jobs is not None:
                with gate:
                    jobs.pop(None)
    except Exception as exc:
        with gate:
            abort_from(exc)
    raise AssertionError("month chain abort must raise")


def _run_loaded_month_chain(
    state: Any,
    db: Any,
    agno_db: Any,
    llm_config: Any,
    chain: Dict[str, Any],
    *,
    decree_text: str,
    content: Any,
    source: Provenance,
    on_gazette: Any = None,
) -> Any:
    """已装入的月链。代码异常由入口收成同一条 call_failure，不在这里另做恢复。"""
    from ming_sim.decree import ResolveResult

    turn = int(state.turn)
    session = SimpleNamespace(
        db=db, state=state, llm_config=llm_config, agno_db=agno_db, content=content,
    )
    _run_opening_levy(db, chain, turn, decree_text, source)

    def persist_declaration_outcome(outcome: Dict[str, object]) -> None:
        chain["declaration_outcome"] = outcome
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)

    declaration_outcome = _settle_edicts(
        session, chain=chain, on_outcome=persist_declaration_outcome,
    )
    _consume_event_gates_after_edicts(
        session, chain, decree_text=decree_text, source=source,
    )
    world_outcome = _run_world_segment(session, chain, source=source)
    declaration_outcome = world_outcome or declaration_outcome
    from ming_sim.rescript_draft import produce_memorials
    _guard_month_call(
        db, state, chain, decree_text=decree_text, source=source, step="rescript-draft",
        operation=lambda: produce_memorials(session, chain, source=source),
    )
    desk = _materialize_rescript_desk(db, state, chain)
    if desk is not None:
        from ming_sim.rescript_forecast import schedule_forecasts
        schedule_forecasts(session, chain, desk)
        return ResolveResult(
            awaiting=True, decisions=desk, advanced=False, stage="rescript",
        )
    _step_4a_secret_order_supply(
        db, state, chain,
        turn=turn, decree_text=decree_text, source=source, llm_config=llm_config,
    )
    # 问后续推与强颁问前效果、整月密令义务（4a）都在案头清空后才齐。惯性、派系杠杆与
    # 门控遗产读的是这些写入，须晚于它们；催办/待核只消费上月待办，并入这一次即可。
    # 到期密令结案已由步骤 4a 办理；drift 内再调为幂等兜底。
    _run_month_drift(db, state, chain, turn, decree_text, source)
    archive = db.turn_reports.archive(turn)
    if archive is None or not str(archive.get("report") or "").strip():
        from ming_sim.models import LLMConfig

        if not isinstance(llm_config, LLMConfig):
            return _pause(db, turn, chain, decree_text, source, "gazette")

        def _write_gazette() -> tuple[str, str]:
            title, report = run_gazette_text(db, state, llm_config, on_gazette=on_gazette)
            db.save_turn_report(state, report, title=title, public_body=report)
            return title, report

        _guard_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step="gazette", operation=_write_gazette,
        )
        archive = db.turn_reports.archive(turn)
        if archive is None or not str(archive.get("report") or "").strip():
            return _pause(db, turn, chain, decree_text, source, "gazette")
    advanced = _advance_after_gazette(
        db, state, chain, turn, decree_text, source, content=content,
        declaration_outcome=declaration_outcome,
        llm_config=llm_config, agno_db=agno_db,
    )
    return ResolveResult(
        awaiting=False, report=str(archive["report"]), advanced=advanced,
        stage="advanced" if advanced else "gazette",
    )


def _run_opening_levy(
    db: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    """月初旧账只消费一次，先于本月旨意改账。"""
    if chain.get("opening_levy_done"):
        return
    from ming_sim.displaced_population import apply_levy_driven_transfers
    from ming_sim.applier import RejectionCollector, mirror_rejections_after_commit
    from ming_sim.error_pack import rejections_jsonl_path

    collector = RejectionCollector()
    with atomic(db):
        _applied, rejected = apply_levy_driven_transfers(db,  source=source)
        if rejected:
            for item in rejected:
                collector.record("population_transfers", item, turn)
            collector.flush_to_db(db)
        chain["opening_levy_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        mirror_rejections_after_commit(db, collector, rejections_jsonl_path)


def _consume_call_failure_for_retry(
    db: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    """清失败标记，保留已存产物与落账进度。"""
    failure = chain.get("call_failure")
    if failure is None:
        return
    step = str(failure.get("step") or "")
    if step == "world_bind":
        # 绑不上的世界段文本是**无效产物**：它已被判为契约违反，重来一次也绑不上，
        # 留着只会让原位重试反复撞同一堵墙。按 #1846「只续未成」丢弃该未成产物，
        # 让重试真正重跑世界段；已提交的财政与已答批红一概不动。
        chain.pop("world_text", None)
        chain["world_text_ready"] = False
        chain.pop("world_questions", None)
        chain.pop("levy_petitions", None)
    if step == "secret_orders_supply":
        # 0058 缺报或 0073 执行态校验失败的产物作废并重起供料；其它中断保留产物。
        if chain.get("secret_orders_supply_invalid"):
            # 作废的是整份产物。奏报相与执行态相属于这份额度，旧完成标记
            # 不得让下一份空报或残报跳过验收。已落的密奏披露不重做。
            chain.pop("secret_orders_supply_product", None)
            chain.pop("secret_orders_supply_invalid", None)
            chain.pop("secret_orders_reports_done", None)
            chain.pop("covert_progress_done", None)
    chain.pop("call_failure", None)
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)


def _abort_month_call(
    db: Any,
    state: Any,
    chain: Dict[str, Any],
    *,
    decree_text: str,
    source: Provenance,
    step: str,
    exc: BaseException,
    kind: str,
    decree_ref: str = "",
) -> None:
    """停住当前过月 run：持久化相位内 call_failure + 错误包，再 SettlementAbort。"""
    from ming_sim.error_pack import write_error_pack
    from ming_sim.exceptions import SettlementAbort

    turn = int(state.turn)
    # 事务已回滚时，失败记录只叠在已提交链上。调用方链在 alongside 里改过的
    # 内存相位（world_committed 等）不随失败写回。
    if kind == "code_exception" and db.owns_transaction():
        from ming_sim.decree import reload_state_from_db
        reload_state_from_db(db, state, content=db.content)
    committed = _load_chain(db, turn)
    original = str(getattr(exc, "message", None) or exc)
    pack_path = ""
    pack_exc: Optional[BaseException] = None
    try:
        pack_path = write_error_pack(
            db, state, exc=exc,
        )
    except Exception as caught_pack:
        # 写包失败不得顶替原故障，也不得挡住已提交相位上的失败标记。
        pack_exc = caught_pack
    failure: Dict[str, Any] = {
        "kind": kind,
        "step": step,
        "message": original,
    }
    if pack_path:
        failure["error_pack_path"] = pack_path
    if decree_ref:
        failure["decree_ref"] = decree_ref
    committed["call_failure"] = failure
    chain.clear()
    chain.update(committed)
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    if pack_exc is not None:
        raise SettlementAbort(
            original, turn=turn, stage=step, error_pack_path=None,
        ) from pack_exc
    raise SettlementAbort(
        original,
        turn=turn,
        stage=step,
        error_pack_path=pack_path,
    ) from exc


def _guard_month_call(
    db: Any,
    state: Any,
    chain: Dict[str, Any],
    *,
    decree_text: str,
    source: Provenance,
    step: str,
    operation: Any,
    decree_ref: str = "",
    code_step: Optional[str] = None,
) -> Any:
    """模型用尽 → 停住可重试；其它代码异常 → 错误包后停住；中断类原样上浮。

    已有错误包或 call_failure 的 SettlementAbort 原样上浮；尚无诊断的中止
    接同一诊断与恢复通道。
    """
    from ming_sim.exceptions import LLMUnavailable, SettlementAbort

    try:
        return operation()
    except LLMUnavailable as exc:
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=step, exc=exc, kind="model_exhausted", decree_ref=decree_ref,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except SettlementAbort as exc:
        if exc.error_pack_path or _load_chain(db, int(state.turn)).get("call_failure"):
            raise
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=step, exc=exc, kind="code_exception", decree_ref=decree_ref,
        )
    except Exception as exc:
        _abort_month_call(
            db, state, chain, decree_text=decree_text, source=source,
            step=code_step or step, exc=exc, kind="code_exception", decree_ref=decree_ref,
        )
    raise AssertionError("month call abort must raise")


def _settle_edicts(
    session: Any, *, chain: Dict[str, Any], on_outcome: Any = None,
) -> Optional[Dict[str, object]]:
    from ming_sim.declaration_dispatch import settle_staged_declarations_in_decree_order
    from ming_sim.decree import _is_stalled_deliberation
    from ming_sim.decree_forecast import (
        _is_held_for_rejudgment,
        decree_ref_for_dossier,
        produce_forecast_product,
        snapshot_for_existing_dossier,
        stage_declaration,
    )

    db, state = session.db, session.state
    outcome = None
    # 同月任免的快照均以首案物化前盘面为准。未判案只记录校验结果，
    # 直到判官实际顺颁才消费；中断重开仍认这一批的原始盘面。
    prevalidated = set(_load_durable_json_list(chain.get("recommendation_prevalidated_ids"), surface="month_chain.recommendation_prevalidated_ids"))
    invalid = set(_load_durable_json_list(chain.get("recommendation_invalid_ids"), surface="month_chain.recommendation_invalid_ids"))
    if "recommendation_prevalidated_ids" not in chain:
        appointments = [row for row in db.dossiers.list_dossiers(status="proposed")
                        if row.get("action_type") == "appointment"
                        and not _is_stalled_deliberation(row)
                        and (not row.get("promulgation_decision")
                             or _is_held_for_rejudgment(row, int(state.turn)))]
        if len(appointments) > 1:
            invalid = db._invalid_office_recommendation_snapshots(state, appointments)
            prevalidated = {int(row["id"]) for row in appointments} - invalid
            chain["recommendation_prevalidated_ids"] = sorted(prevalidated)
            chain["recommendation_invalid_ids"] = sorted(invalid)
            _save_chain(db, int(state.turn), chain, source=Provenance.player_decree)
    for dossier in db.dossiers.list_dossiers():
        if _is_stalled_deliberation(dossier):
            continue
        status = str(dossier.get("status") or "")
        held = _is_held_for_rejudgment(dossier, int(state.turn))
        ref = decree_ref_for_dossier(db, dossier)
        promulgated = str(dossier.get("promulgation_decision") or "") in {
            "promulgated", "force_promulgated",
        } or status == "promulgated"
        pending_judgment = status == "proposed" and (not dossier.get("promulgation_decision") or held)
        pending_settle = (
            promulgated and not db.staged_declarations.is_settled(ref)
            and bool(db.staged_declarations.staged_for(ref))
        )
        if not pending_judgment and not pending_settle:
            continue
        if (
            status == "proposed"
            and (not dossier.get("promulgation_decision") or held)
            and not db.staged_declarations.is_settled(ref)
        ):
            staged = db.staged_declarations.staged_for(ref, turn=int(state.turn))
            verdict = staged[0].verdict if staged else None
            if verdict is None and session.llm_config is not None:
                snapshot = snapshot_for_existing_dossier(session, dossier)

                def _produce() -> Dict[str, Any]:
                    return produce_forecast_product(session, snapshot)

                product = _guard_month_call(
                    db, state, chain, decree_text="", source=Provenance.player_decree,
                    step="edict_forecast", operation=_produce, decree_ref=ref,
                )
                stage_declaration(
                    db, decree_ref=ref,
                    declaration=product["declaration"] or {},
                    turn=int(state.turn),
                    verdict=product["verdict"],
                    questions=product["questions"],
                    forecast_text=product["forecast_text"],
                    visible_refs=snapshot.get("visible_refs"),
                )
                verdict = product["verdict"]
            if isinstance(verdict, dict) and verdict.get("decision"):
                current = db.dossiers.get(int(dossier["id"])) or dossier
                if str(current.get("status") or "") == "proposed":
                    # 失效快照只在实际顺颁时拒，不因未判/打回阻断整月。
                    if int(dossier["id"]) in invalid and verdict["decision"] in {"promulgated", "force_promulgated"}:
                        raise ValueError("任免案卷载荷物化失败")
                    # 判决与元数据、预声明中旨代价同一事务；两种入口共用 DB 写口。
                    previous = getattr(db.conn, "_recommendation_snapshots_prevalidated", False)
                    db.conn._recommendation_snapshots_prevalidated = previous or int(dossier["id"]) in prevalidated
                    try:
                        with atomic(db):
                            apply_dossier_promulgation(db,
                                state, int(dossier["id"]), str(verdict["decision"]),
                                blocked_layer=str(verdict.get("blocked_layer") or ""),
                                reason=str(verdict.get("reason") or ""),
                                legal_reason_code=str(verdict.get("legal_reason_code") or ""),
                                primary_opponents=verdict.get("primary_opponents") or [],
                                gatekeeper_id=verdict.get("gatekeeper_id"),
                                criteria_snapshot=verdict.get("criteria_snapshot") or {},
                                content=session.content,
                            )
                            apply_dossier_verdict_metadata(db, state, int(dossier["id"]), verdict)
                    finally:
                        db.conn._recommendation_snapshots_prevalidated = previous
        current = db.dossiers.get(int(dossier["id"])) or dossier
        if str(current.get("promulgation_decision") or "") == "promulgated":
            def persist_result(_decree_ref: str, result: Any) -> None:
                # 披露暂缓与旨意落账同事务：alongside 在 settle 的 atomic 内，
                # 须把 pending_disclosures 一并写入月链。
                nonlocal outcome
                candidate = _ending_from_dispatch_result(result)
                if candidate is not None:
                    outcome = candidate
                    if on_outcome is not None:
                        on_outcome(candidate)
                _collect_disclosures_from_result(chain, result)
                _save_chain(
                    db, int(state.turn), chain, source=Provenance.player_decree,
                )

            settle_staged_declarations_in_decree_order(
                db, state, [ref], source=Provenance.player_decree,
                alongside=persist_result,
            )
    return outcome


def _ending_from_dispatch_result(result: Any) -> Optional[Dict[str, object]]:
    if result is None:
        return None
    for outcome in result.effects.applied:
        candidate = getattr(outcome, "victory_status", None)
        if isinstance(candidate, dict) and candidate.get("status") != "ongoing":
            return candidate
    return None


def _collect_disclosures_from_result(chain: Optional[Dict[str, Any]], result: Any) -> None:
    if chain is None or result is None:
        return
    pending = chain.setdefault("pending_disclosures", [])
    effects = getattr(result, "effects", None)
    applied = getattr(effects, "applied", []) if effects is not None else []
    from ming_sim.settlement.views import view

    for outcome in applied:
        for update in view(outcome, "secret_order_updates"):
            if isinstance(update, dict) and update.get("disclosed"):
                item = {
                    "order_id": int(update["order_id"]),
                    "sim_note": str(update.get("sim_note") or ""),
                }
                if item not in pending:
                    pending.append(item)


def _consume_event_gates_after_edicts(
    session: Any, chain: Dict[str, Any], *, decree_text: str, source: Provenance,
) -> None:
    """#1892：世界事件的唯一消费时点——逐旨落账之后、世界段之前。

    判门读当月实账。旨前跑过的终态不可撤销，所以这里不是第二遍补判，
    ``pre_settle`` 不再调用这两条判门。``event_gates_after_edicts_done`` 只防止
    同月恢复时再消费一次。
    """
    from ming_sim.entities.issue.event_terminal import apply_event_terminal_states
    from ming_sim.issues import auto_trigger_seed_issues
    from ming_sim.token_stats import tlog

    db, state = session.db, session.state
    turn = int(state.turn)
    if chain.get("event_gates_after_edicts_done"):
        return
    with atomic(db):
        terminalized = apply_event_terminal_states(state, db)
        triggered = auto_trigger_seed_issues(state, db)
    if terminalized:
        tlog(
            f"[event-gate] 逐旨后终态 {len(terminalized)} 条："
            f"{[(t['id'], t['terminal_state']) for t in terminalized]}"
        )
    if triggered:
        tlog(
            f"[event-gate] 逐旨后硬触发 {len(triggered)} 条："
            f"{[t.get('title') for t in triggered]}"
        )
    with atomic(db):
        chain["event_gates_after_edicts_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)


def _run_world_segment(
    session: Any, chain: Dict[str, Any], *, source: Provenance,
) -> Optional[Dict[str, object]]:
    from ming_sim.month_translate import dispatch_month_segment

    db, state = session.db, session.state
    turn = int(state.turn)
    if not chain.get("world_text_ready"):
        # #1891：交接名单只取一次，随链持久化。世界段消息与下面的身份钉定读同一份
        # 快照；恢复时读链上已存身份与奏疏，不按实时资格重解（ADR 0115）。
        from ming_sim.issues import list_fiscal_levy_petitions_due

        def _push() -> str:
            chain["levy_petitions"] = list_fiscal_levy_petitions_due(state, db)
            return run_world_segment_text(
                db, state, session.llm_config,
                cheat_directive=str(chain.get("cheat_directive") or ""),
            )

        chain["world_text"] = _guard_month_call(
            db, state, chain, decree_text="", source=source,
            step="world_text", operation=_push,
        )
        chain["world_text_ready"] = True
        _save_chain(db, turn, chain, decree_text="", source=source)
    if chain.get("world_committed"):
        return chain.get("declaration_outcome")
    prefix, questions = _split_at_question(str(chain.get("world_text") or ""))

    def _bind() -> List[Dict[str, Any]]:
        # 交接时钉定：请旨按上面那份名单快照换上稳定案头身份，随链持久化。绑定是
        # 生成之后、本段转译之前的一步，未成即本段未完成——故按既有失败通道登记
        # （call_failure + 错误包），由 #1846 的持久相位续未成，而非静默放行。
        return _pin_world_question_identities(
            _load_durable_json_list(chain.get("levy_petitions"), surface="month_chain.levy_petitions"), questions, turn,
            world_text=str(chain.get("world_text") or ""),
        )

    chain["world_questions"] = _guard_month_call(
        db, state, chain, decree_text="", source=source,
        step="world_bind", operation=_bind,
    )

    def mark(result: Any) -> None:
        # 完成标记与世界效果同一事务；调用方链要等提交成功后再采纳。
        persisted = dict(chain)
        outcome = _ending_from_dispatch_result(result)
        if outcome is not None:
            persisted["declaration_outcome"] = outcome
        _collect_disclosures_from_result(persisted, result)
        persisted["world_committed"] = True
        _save_chain(db, turn, persisted, source=source)

    def adopt_committed() -> None:
        chain.clear()
        chain.update(_load_chain(db, turn))

    if prefix.strip():
        result = _guard_month_call(
            db, state, chain, decree_text="", source=source,
            step="world_translate", code_step="world_commit",
            operation=lambda: dispatch_month_segment(
                db, state, segment=prefix, llm_config=session.llm_config, source=source,
                alongside=mark,
            ),
        )
        adopt_committed()
        return _ending_from_dispatch_result(result)
    with atomic(db):
        mark(None)
    adopt_committed()
    return None


def _apply_deferred_disclosures(
    db: Any, state: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    pending = chain.get("pending_disclosures") or []
    from ming_sim.entities.secret_order.disclosure import record_secret_order_disclosure
    with atomic(db):
        for item in pending:
            order_id = int(item["order_id"])
            sim_note = str(item.get("sim_note") or "")
            record_secret_order_disclosure(db, state, order_id, sim_note)
        chain["secret_orders_disclosures_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)


def _enrich_eligible_dossiers_for_supply(
    db: Any, candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """合资格案卷供料：复用 DossierStore.get／typed contract 读口补齐正文与执行契约。

    密令关联案卷的现行要旨与期限只读 secret_orders（#1897 S2）；案卷 decree_text
    是发令历史原诏，不作现行正文真源。
    """
    from ming_sim.covert_progress import read_covert_task_contract

    out: List[Dict[str, Any]] = []
    for item in candidates:
        row = dict(item)
        dossier_id = int(item.get("dossier_id") or 0)
        dossier = db.dossiers.get(dossier_id) if dossier_id else None
        if dossier is not None:
            secret_order_id = int(
                dossier.get("secret_order_id") or item.get("secret_order_id") or 0
            )
            order = (
                db.character_knowledge.get_secret_order(secret_order_id)
                if secret_order_id
                else None
            )
            if order is not None:
                row["decree_text"] = str(order.get("content") or "")
                row["title"] = str(order.get("title") or row.get("title") or "")
                row["due_turn"] = int(order.get("due_turn") or 0)
            else:
                row["decree_text"] = str(dossier.get("decree_text") or "")
            row["payload"] = dossier["payload"]
            row["status"] = str(dossier.get("status") or "")
            contract = read_covert_task_contract(dossier)
            if contract is not None:
                row["covert_task_contract"] = contract
        out.append(row)
    return out


def _identity_materials(db: Any, state: Any, name: str) -> Dict[str, Any]:
    """按身份指给某人一份可及材料（ADR 0034 非全知 / 0155 身份隔离 / #1814）。

    只给**材料目录里的路径**，不给正文：读取形态是「备一个地方它自己读」
    （ADR 0155:8）。``materials.write_identity_materials`` 在 4a 备树之后、
    调用之前复用人物材料写手，按身份分列正文，``identity_material_rel``
    指向本人子目录的人读索引；不保留综合正文副本，restore 可复现。
    查案对象不是真人物（如「某类人」式题名）时没有身份材料，如实留空，不编。
    """
    who = str(name or "").strip()
    if not who:
        return {}
    if db.characters.row(who) is None:
        # 不是真人物（如「某类人」式题名）：没有身份材料，如实留空，不编。
        return {"name": who}
    from ming_sim.knowledge import build_character_knowledge

    knowledge = build_character_knowledge(db, state, who)
    from ming_sim.materials import identity_material_rel

    return {
        "name": who,
        "office": str(knowledge.get("office") or ""),
        "materials_path": identity_material_rel(who),
    }


def _attach_investigation_facts(
    db: Any, state: Any, orders: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """#1896 给 4a 逐证清单：每条实有罪证的键、已投入多少、还差多少、是否已被毁。

    并按身份接入办案人与被查者的可及材料（#1814）：4a 一次 run 里既扮办案人
    决定查法与投入，也扮经真实关系网知情后的被查者决定毁证／压案／不动——
    两个人各自只见自己身份下能接触到的材料（ADR 0034／0155），同场不等于全知。

    供料是人物"能接触到的材料"：只列真相底 live 集里的实有罪证，不塞机制说明
    以外的判定口径；空 lane 集照列空清单（清白目标也照开案，不因无证而拒开——
    那会变成免费清白神谕）。
    """
    from ming_sim.covert_progress import (
        investigation_fact_is_gone,
        investigation_tip_records,
        investigation_action_records,
        live_investigation_fact_keys,
        read_covert_task_contract,
        _investigation_target_of,
        _dossier_payload_map,
        _lanes_from_payload,
    )

    out: List[Dict[str, Any]] = []
    for raw in orders:
        order = dict(raw)
        dossier = db.dossiers.get_for_secret_order(int(order.get("id") or 0))
        if dossier is None:
            out.append(order)
            continue
        contract = read_covert_task_contract(dossier)
        target = _investigation_target_of(contract) if contract else ""
        if not target:
            out.append(order)
            continue
        did = int(dossier["id"])
        investigator = str(order.get("minister_name") or "")
        lanes = {
            str(lane["fact_key"]): lane
            for lane in _lanes_from_payload(_dossier_payload_map(db, did))
        }
        facts: List[Dict[str, Any]] = []
        for key in live_investigation_fact_keys(db, target):
            lane = lanes.get(key, {})
            if investigation_fact_is_gone(db, target, key):
                state_text = "已被毁证湮灭"
            elif bool(lane.get("mastered")):
                state_text = "已掌握"
            else:
                state_text = "在查"
            # 不把 difficulty 数值递给模型：那是引擎的账，给了等于递答案，
            # 模型会照着填一个"刚好够"的值。人物只据实说自己下了多大劲。
            facts.append({
                "fact_key": key,
                "months_under_investigation": int(lane.get("months") or 0),
                "effort_so_far": round(float(lane.get("effort") or 0.0), 3),
                "state": state_text,
            })
        order["investigation_target"] = target
        order["investigation_facts"] = facts
        order["investigator_identity_materials"] = _identity_materials(
            db, state, investigator,
        )
        order["investigation_target_identity_materials"] = _identity_materials(
            db, state, target,
        )
        order["investigation_tips"] = investigation_tip_records(db, did)
        # 完整历史实况供料（ADR 0155:8 撤除硬上限）：不取"最后 6 条"——尾取
        # 会让跨月的知情与因果承接读不到上月记录。
        order["investigation_actions"] = investigation_action_records(db, did)
        out.append(order)
    return out


def _feed_identity_names(feed: Mapping[str, Any]) -> List[str]:
    """从 4a 供料里取出该备身份材料的人名（承办人与被查者，去重保序）。

    供料与材料树两处都以这里为准：供料给路径、材料树写正文，名单不同源就会
    出现"给了路径却读不到"或"备了没人指"的对不上。
    """
    names: List[str] = []
    for order in feed.get("active_secret_orders") or []:
        if not isinstance(order, Mapping):
            continue
        for side in ("investigator_identity_materials", "investigation_target_identity_materials"):
            who = str((order.get(side) or {}).get("name") or "").strip()
            if who and who not in names:
                names.append(who)
    return names


def build_secret_orders_supply_feed(
    db: Any, state: Any, chain: Dict[str, Any],
) -> Dict[str, Any]:
    """整月密报供料：读取本月原始事实与原话，含密令来源；另附密令对象与盘面。

    不拼装「已生效效果」清单，也不另造逐段实际结果账本；专用逐路实况账本已退役（#1900 J18）。
    """
    from ming_sim.covert_progress import _is_issuance_turn
    from ming_sim.materials import _world_board_text, actual_progress_notes

    turn = int(state.turn)
    candidates = db.list_monthly_dossier_progress_nudges()
    eligible = _enrich_eligible_dossiers_for_supply(db, candidates)
    for row in eligible:
        dossier_id = int(row.get("dossier_id") or 0)
        row["actual_notes"] = actual_progress_notes(db, dossier_id) if dossier_id else []
    active_orders = _attach_investigation_facts(db, state, [
        dict(o) for o in db.character_knowledge.list_secret_orders(status="active")
        if not _is_issuance_turn(o, turn)
    ])
    # #1897：密令供料附实况轨原文（与案卷 eligible 同形）。
    for item in active_orders:
        dossier = db.dossiers.get_for_secret_order(int(item["id"]))
        item["actual_notes"] = (
            actual_progress_notes(db, int(dossier["id"])) if dossier is not None else []
        )
    materials = _month_fact_materials(db, state, chain)
    return {
        "instruction": (
            "为本月所有在办密令产出密奏和执行态声明。据实况自行判断办理与拒收。"
            "逐路汇总执行状态时据案卷关联与核账事实读，别拿整条密令的成败反推。"
        ),
        "turn": turn,
        "eligible_dossiers": eligible,
        "active_secret_orders": active_orders,
        **materials,
        "board": _world_board_text(db, state),
    }


def run_secret_orders_supply(
    db: Any, state: Any, llm_config: Any, chain: Dict[str, Any],
) -> Dict[str, Any]:
    """步骤 4a 整月密令供料 run。产出覆盖整月合资格长差案卷与在办密令的密奏与执行态。"""
    import json
    from ming_sim.agents import create_secret_order_supply_agent, parse_agent_json, run_agent_text
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import prepare_world_materials, release_material_tree
    from ming_sim.models import LLMConfig

    if not isinstance(llm_config, LLMConfig):
        raise LLMUnavailable("整月供料缺少模型配置", stage="secret_orders_supply")

    feed = build_secret_orders_supply_feed(db, state, chain)
    message = json.dumps(feed, ensure_ascii=False)
    # 与邸报作者同目录读口；密报侧不滤密令来源（默认 prepare 全量可读）。
    prepared = prepare_world_materials(db, state)
    # #1896：供料里只给身份材料路径，正文写进**本次调用自己**的树（ADR 0155:8
    # 目录读取形态／#1814 身份隔离）。不并进世界段与邸报作者共用的世界树——那份
    # 树的读者不该因共用而读到某人的私务（含其在办密报正文）。
    # 身份写入与调用同在既有 try/finally 里：写入失败也释放本树，不另建清理层。
    from ming_sim.materials import write_identity_materials

    try:
        write_identity_materials(prepared, db, state, _feed_identity_names(feed))
        agent = create_secret_order_supply_agent(llm_config, prepared)
        raw = run_agent_text(
            agent, message, tag="secret_orders_supply",
            transport_policy=audience_transport_policy(),
        )
    finally:
        release_material_tree(prepared.root)
    # 顶层 object 唯一权威在 parse_agent_json；此处不再重复判定。
    return parse_agent_json(raw, "secret_orders_supply")


def _step_4a_secret_order_supply(
    db: Any,
    state: Any,
    chain: Dict[str, Any],
    *,
    turn: int,
    decree_text: str,
    source: Provenance,
    llm_config: Any,
) -> None:
    if chain.get("secret_orders_supply_done"):
        return

    from ming_sim.covert_progress import _is_issuance_turn
    from ming_sim.exceptions import DeclarationDataError

    candidates = db.list_monthly_dossier_progress_nudges()
    active_orders = [
        o for o in db.character_knowledge.list_secret_orders(status="active")
        if not _is_issuance_turn(o, turn)
    ]
    if not candidates and not active_orders:
        if not chain.get("secret_orders_disclosures_done"):
            _apply_deferred_disclosures(db, state, chain, turn, decree_text, source)
        chain["secret_orders_supply_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        return

    product = chain.get("secret_orders_supply_product")
    if product is None:
        def _call_supply() -> Dict[str, Any]:
            return run_secret_orders_supply(db, state, llm_config, chain)

        product = _guard_month_call(
            db, state, chain,
            decree_text=decree_text, source=source,
            step="secret_orders_supply",
            operation=_call_supply,
        )
        # parse_agent_json 已保证 dict；_guard_month_call 失败即中止，无第三层顶层 object 收口。
        chain["secret_orders_supply_product"] = product
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)

    # Phase 1: 0058 覆盖校验。已提交过的合法报告不重写；新重起产物仍须完整校验。
    reports = product.get("dossier_progress_reports") or []
    if chain.get("secret_orders_reports_done"):
        try:
            db.validate_monthly_dossier_progress(reports)
        except ValueError as exc:
            chain["secret_orders_supply_invalid"] = True
            _save_chain(db, turn, chain, decree_text=decree_text, source=source)
            _abort_month_call(
                db, state, chain,
                decree_text=decree_text, source=source,
                step="secret_orders_supply",
                exc=exc,
                kind="code_exception",
            )
    else:
        validation_failed = False
        try:
            with atomic(db):
                db.dossiers.record_monthly_supervision_presence(turn, commit=False)
                try:
                    db.record_monthly_dossier_progress(turn, reports)
                except DeclarationDataError:
                    # 仅 0058 完整性校验失败标 invalid；其它异常保留产物供重试接续。
                    validation_failed = True
                    raise
                chain["secret_orders_reports_done"] = True
                _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        except Exception as exc:
            if validation_failed:
                # 无效标记须先落盘：_abort_month_call 只叠 call_failure 到已提交链。
                chain["secret_orders_supply_invalid"] = True
                _save_chain(db, turn, chain, decree_text=decree_text, source=source)
            _abort_month_call(
                db, state, chain,
                decree_text=decree_text, source=source,
                step="secret_orders_supply",
                exc=exc,
                kind="code_exception",
            )

    def _abort_4a(exc: BaseException) -> None:
        _abort_month_call(
            db, state, chain,
            decree_text=decree_text, source=source,
            step="secret_orders_supply",
            exc=exc,
            kind="code_exception",
        )

    # Phase 2: Deferred disclosures
    if not chain.get("secret_orders_disclosures_done"):
        try:
            _apply_deferred_disclosures(db, state, chain, turn, decree_text, source)
        except Exception as exc:
            _abort_4a(exc)

    # Phase 3: Covert actual progress (0073)
    if not chain.get("covert_progress_done"):
        from ming_sim.applier import RejectionCollector, mirror_rejections_after_commit
        from ming_sim.covert_progress import apply_monthly_covert_actual_progress
        from ming_sim.error_pack import rejections_jsonl_path

        collector = RejectionCollector()
        selections = product.get("covert_exec_selections") or []
        invalid_declarations = False
        try:
            with atomic(db):
                rows, rows_rejections = apply_monthly_covert_actual_progress(
                    db, state, selections=selections, only_supplied=False,
                    source=source)
                # #1835 S1：只消费 canonical RejectedItem；保留 invalid_enum 停续语义。
                rejections = list(rows_rejections)
                invalid_declarations = any(
                    getattr(item, "category", None) == "invalid_enum"
                    for item in rejections
                )
                if invalid_declarations:
                    # #1846：无效声明不冒充合法完成；标 invalid 并中止，重试弃 4a 产物。
                    raise ValueError("密令声明无效，本月 4a 产物须重来")
                if rejections:
                    for item in rejections:
                        collector.record("covert_exec_selections", item, turn)
                    collector.flush_to_db(db)
                chain["covert_progress_done"] = True
                _save_chain(db, turn, chain, decree_text=decree_text, source=source)
                mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
        except Exception as exc:
            if invalid_declarations:
                chain["secret_orders_supply_invalid"] = True
                _save_chain(db, turn, chain, decree_text=decree_text, source=source)
            _abort_4a(exc)

    # Phase 4: Settle due secret orders
    if not chain.get("due_secret_orders_settled"):
        from ming_sim.covert_progress import settle_due_secret_orders
        try:
            with atomic(db):
                settle_due_secret_orders(db, state)
                chain["due_secret_orders_settled"] = True
                chain["secret_orders_supply_done"] = True
                _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        except Exception as exc:
            _abort_4a(exc)


def _run_month_drift(
    db: Any, state: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
) -> None:
    if chain.get("inertia_done") or not chain.get("world_committed"):
        return
    from ming_sim.situation_drift import apply_situation_monthly_drift
    from ming_sim.entities.issue.legacy import clear_gated_legacies
    from ming_sim.due_review import apply_pending_due_reviews
    from ming_sim.staged_commitment import write_due_staged_commitment_todos
    from ming_sim.breach_plea import expire_breach_pleas_on_due, scan_and_write_breach_pleas
    from ming_sim.covert_progress import settle_due_secret_orders
    from ming_sim.urge_lever import consume_pending_urge_audience_todos
    from ming_sim.audience_night import retire_unsettled_summons_for_inactive
    from ming_sim.applier import RejectionCollector, mirror_rejections_after_commit
    from ming_sim.error_pack import rejections_jsonl_path

    collector = RejectionCollector()
    with atomic(db):
        db.dossiers.record_monthly_supervision_presence(turn, commit=False)
        db.record_monthly_grant_reconciliations(turn)
        db.dossiers.record_monthly_loophole_exposures_from_reconciliations(turn, commit=False)
        retire_unsettled_summons_for_inactive(db)
        # #651：漂移只承接不依赖本段 applied 的持久态（已决「禁摊派」欠饷是否再开口）。
        # 默许/查办必须在逐段落账接缝带该段 report 结算，见 declaration_dispatch。
        from ming_sim.covert_levy import settle_exposure_from_canonical_actions, write_exposure_todos
        write_exposure_todos(db, state)
        settle_exposure_from_canonical_actions(db, state, None)
        person_changes: list[dict[str, object]] = []
        rejections = apply_situation_monthly_drift(
            db, state, applied_person_changes=person_changes,
            source=source)
        for item in rejections:
            collector.record("issue_inertia", item, turn)
        collector.flush_to_db(db)
        db.recompute_all_faction_leverage()
        clear_gated_legacies(db, state)
        apply_pending_due_reviews(db, state)
        settle_due_secret_orders(db, state)
        expire_breach_pleas_on_due(db, state)
        consume_pending_urge_audience_todos(db, state)
        write_due_staged_commitment_todos(db, state)
        scan_and_write_breach_pleas(db, state)
        chain["inertia_done"] = True
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
        mirror_rejections_after_commit(db, collector, rejections_jsonl_path)


def _open_rescript_items(
    db: Any, state: Any, chain: Dict[str, Any],
) -> Dict[str, Any]:
    """本回合待答：打回三选 + 旨意请旨 + 世界段请旨。上月已答项不入。"""
    from ming_sim.decree_forecast import decree_ref_for_dossier

    turn = int(state.turn)
    triad = _this_turn_rescript_dossiers(db, turn)
    decree_questions: List[tuple[str, list]] = []
    seen_refs: set[str] = set()
    for dossier in db.dossiers.list_dossiers():
        ref = decree_ref_for_dossier(db, dossier)
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        questions = db.staged_declarations.questions_for(ref)
        if questions:
            # 未答请旨不论案卷创建回合，均须本回合收口（#1847 / 留中回流同审）。
            decree_questions.append((ref, questions))
    world_questions = _load_durable_json_list(chain.get("world_questions"), surface="month_chain.world_questions")
    return {
        "triad": triad,
        "decree_questions": decree_questions,
        "world_questions": world_questions,
    }


def _this_turn_rescript_dossiers(db: Any, turn: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for dossier in db.dossiers.list_dossiers():
        if not dossier.get("rescript_pending"):
            continue
        if not _dossier_rejection_is_this_turn(db, dossier, turn):
            continue
        out.append(dossier)
    return out


def _dossier_rejection_is_this_turn(db: Any, dossier: Dict[str, Any], turn: int) -> bool:
    dossier_id = int(dossier["id"])
    if int(dossier.get("created_turn") or 0) == turn:
        return True
    latest = db.dossiers.rejection_this_turn(dossier_id, turn)
    if latest is None:
        return False
    # 上月已作三选（hold/withdrawn/force）的旧件即使残留 pending 也不再挡本月。
    rejected_turn, rescript_action = latest
    if rescript_action.strip():
        return False
    return rejected_turn == turn


def _materialize_rescript_desk(
    db: Any, state: Any, chain: Dict[str, Any],
) -> Optional[List[Dict[str, object]]]:
    from ming_sim.decree import _rescript_decisions

    open_items = _open_rescript_items(db, state, chain)
    turn = int(state.turn)
    decisions: List[Dict[str, object]] = []

    if open_items["triad"]:
        verdicts = []
        for dossier in open_items["triad"]:
            hist = db.dossiers.decisions(int(dossier["id"]))
            latest = hist[-1] if hist else {}
            verdicts.append({
                "dossier_id": int(dossier["id"]),
                "decision": "rejected",
                "reason": str(
                    dossier.get("promulgation_reason") or latest.get("reason") or ""
                ),
                "primary_opponents": (
                    dossier.get("primary_opponents")
                    or latest.get("primary_opponents")
                    or []
                ),
                "midzhi_unpromulgatable": bool(
                    (latest or {}).get("midzhi_unpromulgatable")
                ),
            })
        decisions.extend(_rescript_decisions(verdicts, open_items["triad"]))
    for dossier in db.dossiers.list_dossiers(status="proposed"):
        if (dossier["payload"] or {}).get("deliberation_state") != "stalled":
            continue
        decisions.append({
            "event_id": f"deliberation:{dossier['id']}", "title": "无人站台原案",
            "context": dossier["decree_text"], "options": [
                {"label": "御笔强推", "hint": "皇帝独担，复用原案颁布", "action": "imperial_push"},
                {"label": "留中", "hint": "原案留存", "action": "hold"},
            ],
        })
    for ref, questions in open_items["decree_questions"]:
        offsets = chain.setdefault("decree_question_offsets", {})
        pinned, offsets[ref] = _pin_rescript_questions(
            questions, f"{_DECREE_QUESTION_PREFIX}{ref}:", int(offsets.get(ref, 0)),
        )
        if pinned != questions:
            db.staged_declarations.replace_questions(ref, pinned)
        decisions.extend(_question_as_decision(q, event_id=q["event_id"]) for q in pinned)
    pinned, chain["world_question_offset"] = _pin_rescript_questions(
        open_items["world_questions"], f"{_WORLD_QUESTION_PREFIX}{turn}:",
        int(chain.get("world_question_offset", 0)),
    )
    chain["world_questions"] = pinned
    decisions.extend(_question_as_decision(q, event_id=q["event_id"]) for q in pinned)
    if decisions:
        db.issues.save_pending_decisions(turn, decisions)
    desk = db.issues.list_rescript_desk(turn)
    if not desk:
        return None
    chain["stage"] = "rescript"
    _save_chain(db, turn, chain, source=Provenance.system_simulation)
    return desk


def _question_as_decision(question: Dict[str, object], *, event_id: str) -> Dict[str, object]:
    from ming_sim.settlement_payload import bind_decision_options

    options = question.get("options", [])
    cleaned = []
    for label, opt in bind_decision_options(options).items():
        cleaned.append({
            "label": label,
            "hint": str(opt.get("hint") or ""),
            **{
                key: opt[key] for key in opt
                if key not in {"label", "hint"} and opt[key] is not None
            },
        })
    decision = {
        "event_id": event_id,
        "title": str(question.get("title") or "") or "请旨",
        "context": str(question.get("context") or ""),
        "options": cleaned,
    }
    return decision


def _answer_from_row(row: Dict[str, object]) -> Dict[str, object]:
    choice = row["choice"] or {}
    event_id = str(row.get("event_id") or "")
    # #1891：请饷／议停请旨交续推的是真实事件身份——案头前缀只是批红页身份，
    # 不该让推演方看到（ADR 0115）。御批原话（label/hint/note）原样带出。
    if event_id.startswith(_LEVY_PETITION_PREFIX):
        event_id = event_id[len(_LEVY_PETITION_PREFIX):]
    return {
        **row, "choice": dict(choice),
        "label": str(choice.get("label") or ""),
        "hint": str(choice.get("hint") or ""),
        "note": str(choice.get("note") or ""),
        "context": str(row.get("context") or ""),
        "event_id": event_id,
        "title": str(row.get("title") or ""),
    }


def _pin_rescript_questions(questions, prefix, offset):
    """Allocate each question's existing event identity once, independent of siblings."""
    pinned = []
    for question in questions:
        row = dict(question)
        if not row.get("event_id"):
            row["event_id"] = f"{prefix}{offset}"
            offset += 1
        pinned.append(row)
    return pinned, offset


def _world_question_ids(chain, turn):
    return {q["event_id"] for q in _load_durable_json_list(
        chain.get("world_questions"), surface="month_chain.world_questions",
    )}


def _consume_rescript_answers(
    session: Any, chain: Dict[str, Any], *, source: Provenance,
) -> None:
    """Independent answer model legs; completion-order, short atomic live commits.

    Failure is recorded immediately through the original month-call boundary, but
    only re-raised after sibling jobs have had their own chance to commit.
    """
    from concurrent.futures import as_completed
    from ming_sim.decree_forecast import _owner_for
    from ming_sim.rescript_draft import consume_memorial_answer
    from ming_sim.rescript_forecast import prepare_answers

    db, state = session.db, session.state
    turn = int(state.turn)
    owner = _owner_for(db)
    with owner._write_gate if owner is not None else nullcontext():
        rows = db.issues.list_pending_decisions(turn) + db.issues.list_rescript_drafts()
        decided = [r for r in rows if r["status"] == "decided" and r["answered_turn"] == turn]
        # Retain the existing durable recovery fields even before any answer.
        chain.setdefault("rescript_consumed", [])
        chain.setdefault("rescript_answer_products", {})
        if not decided:
            return
        chain.clear()
        chain.update(_load_chain(db, turn))
        for row in decided:
            event_id = str(row.get("event_id") or "")
            if event_id.startswith("deliberation:"):
                from ming_sim.rescript_actions import apply_imperial_deliberation_push
                original = db.dossiers.get(int(event_id.partition(":")[2]))
                if (row["choice"] or {}).get("action") == "imperial_push" and (original["payload"] or {}).get("deliberation_state") == "stalled":
                    with atomic(db):
                        apply_imperial_deliberation_push(
                            db, state, target_dossier_id=int(original["id"]),
                            decision_key=row["decision_key"],
                            decree_text=(row.get("choice") or {}).get("note", ""),
                        )
            elif event_id.startswith("dossier:"):
                _apply_decided_triad(db, state, row, row["choice"] or {}, content=session.content)
        world_ids = _world_question_ids(chain, turn)
        eligible = []
        for row in decided:
            event = str(row.get("event_id") or "")
            if row["kind"] == "rescript_draft":
                if row["decision_key"] not in chain.get("rescript_consumed", []):
                    eligible.append(row)
            elif event in world_ids:
                eligible.append(row)
            elif event.startswith(_DECREE_QUESTION_PREFIX):
                ref = event[len(_DECREE_QUESTION_PREFIX):].rpartition(":")[0]
                if any(q["event_id"] == event for q in db.staged_declarations.questions_for(ref)):
                    eligible.append(row)
        jobs, launches = prepare_answers(session, chain, eligible, source=source)
    for launch in launches:
        launch()
    failure = None
    for future in as_completed(jobs):
        row, kind, ref = jobs[future]
        with owner._write_gate:
            chain.clear()
            chain.update(_load_chain(db, turn))

            def consume():
                prepared = future.result()
                if kind == "memorial":
                    consume_memorial_answer(session, chain, row, source=source, prepared=prepared)
                elif kind == "world":
                    continue_world_after_answers(
                        session, chain, answers=[_answer_from_row(row)], source=source, prepared=prepared,
                    )
                else:
                    decree_ref = ref[len(_DECREE_QUESTION_PREFIX):].rpartition(":")[0]
                    continue_decree_after_answers(
                        session, decree_ref=decree_ref, chain=chain,
                        answers=[_answer_from_row(row)], source=source, prepared=prepared,
                    )
            try:
                _guard_month_call(
                    db, state, chain, decree_text="", source=source,
                    step="rescript-answer" if kind == "memorial" else f"{kind}_continue", operation=consume,
                )
            except Exception as exc:
                failure = failure or exc
            finally:
                del owner._rescript_jobs[(turn, row["decision_key"])]
    with owner._write_gate:
        chain.clear()
        chain.update(_load_chain(db, turn))
    if failure is not None:
        raise failure


def _apply_decided_triad(
    db: Any, state: Any, row: Dict[str, object], choice: Dict[str, object], *, content: Any,
) -> None:
    event_id = str(row.get("event_id") or "")
    raw_id = event_id.split(":", 1)[1] if ":" in event_id else ""
    if not raw_id.isdigit():
        return
    dossier_id = int(raw_id)
    dossier = db.dossiers.get(dossier_id)
    if dossier is None or not dossier.get("rescript_pending"):
        return
    decision = str(
        choice.get("dossier_decision") or choice.get("action") or ""
    ).strip()
    if decision not in {"force_promulgated", "withdrawn", "hold"}:
        return
    apply_dossier_promulgation(db,
        state, dossier_id, decision, content=content,
    )


def _run_world_continuation_text(
    session: Any, chain: Dict[str, Any], answers: List[Dict[str, object]],
) -> str:
    if session.llm_config is None:
        from ming_sim.exceptions import LLMUnavailable
        raise LLMUnavailable("世界段续推缺少模型配置", stage="world-segment-continue")
    from ming_sim.agents import create_world_segment_agent, run_agent_text
    from ming_sim.llm_transport import audience_transport_policy
    from ming_sim.materials import prepare_world_materials, release_material_tree
    import json

    prepared = getattr(session, "_rescript_world_materials", None)
    owns_materials = prepared is None
    if owns_materials:
        prepared = prepare_world_materials(session.db, session.state)
    try:
        agent = create_world_segment_agent(session.llm_config, prepared)
        payload = {
            "instruction": "皇帝已批红答复世界段的一道请旨。只续写这一问的后果；其他请旨各自办理。已落的事实保持原状，相互牵连的后续选择合为一道请旨。",
            "answers": answers,
            "prior_world_text": str(chain.get("world_text") or ""),
        }
        return run_agent_text(
            agent, json.dumps(payload, ensure_ascii=False), tag="world-segment-continue",
            transport_policy=audience_transport_policy(),
        )
    finally:
        if owns_materials:
            release_material_tree(prepared.root)


def _dossier_for_decree_ref(db: Any, decree_ref: str) -> Optional[Dict[str, Any]]:
    from ming_sim.decree_forecast import decree_ref_for_dossier

    for dossier in db.dossiers.list_dossiers():
        if decree_ref_for_dossier(db, dossier) == decree_ref:
            return dossier
    if decree_ref.startswith("dossier:"):
        raw = decree_ref.split(":", 1)[1]
        if raw.isdigit():
            return db.dossiers.get(int(raw))
    return None


def _advance_after_gazette(
    db: Any, state: Any, chain: Dict[str, Any], turn: int, decree_text: str, source: Provenance,
    *, content: Any = None, declaration_outcome: Optional[Dict[str, object]] = None,
    llm_config: Any = None, agno_db: Any = None,
) -> bool:
    if chain.get("advanced"):
        return True
    from ming_sim.context import ENDING_LABELS, ENDING_ONGOING, ENDING_TIMEOUT, victory_status
    from ming_sim.decree import (
        TIMEOUT_TURN, atomic_and_reload,
    )
    settled_year, settled_period = int(state.year), int(state.period)
    ending_outcome: Optional[Dict[str, object]] = None

    def _coalesce_declaration_outcome(
        *candidates: object,
    ) -> Optional[Dict[str, object]]:
        """合并对象，合法空对象不抢下一位真源。"""
        for value in candidates:
            if value is None:
                continue
            checked = {**value}
            if checked:  # 合法 {} 继续回落
                return checked
        return None

    with atomic_and_reload(db, state, content=content):
        if not state.ended:
            outcome = _coalesce_declaration_outcome(
                declaration_outcome, chain.get("declaration_outcome"),
            )
            if outcome is None:
                outcome = victory_status(db)
            if (
                outcome.get("status") == ENDING_ONGOING
                and state.turn >= TIMEOUT_TURN
            ):
                outcome = {
                    "status": ENDING_TIMEOUT,
                    "summary": ENDING_LABELS.get(ENDING_TIMEOUT, ""),
                }
            if outcome.get("status") != ENDING_ONGOING:
                state.ended = True
                state.ending_status = str(outcome.get("status") or "")
                ending_outcome = dict(outcome)
        else:
            ending_outcome = _coalesce_declaration_outcome(
                declaration_outcome, chain.get("declaration_outcome"),
            )
        from ming_sim.mechanical_tail import mark_mechanical_tail_pending
        mark_mechanical_tail_pending(
            db, turn, settled_year=settled_year, settled_period=settled_period,
            ending_outcome=ending_outcome, source=source,
        )
        chain = _load_chain(db, turn)
        db.mark_directives_issued(state)
        # #652：刚结束的月份的执行判定和实付已落定；下月任何吸收前回流。
        from ming_sim.entities.population.recovery import _apply_recovery_driven_transfers
        _apply_recovery_driven_transfers(db, state)
        state.next_period()
        state.turn_phase = "issued"
        db.reign.save_game_state(state)
        db.month_open_snapshots.delete(turn)
        chain["advanced"] = True
        chain["stage"] = "advanced"
        _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    # #1845：推进后启动机械尾（后台；不挡新月前台）。结局总评属尾，判定已在上面完成。
    from ming_sim.mechanical_tail import schedule_mechanical_tail_after_advance

    owner = _session_owner(db, state, llm_config, agno_db, content)
    schedule_mechanical_tail_after_advance(
        owner,
        closed_turn=int(turn),
        settled_year=settled_year,
        settled_period=settled_period,
        ending_outcome=ending_outcome,
        source=source,
        pending_already_marked=True,
    )
    return True


def _pause(
    db: Any, turn: int, chain: Dict[str, Any], decree_text: str, source: Provenance, stage: str,
) -> Any:
    from ming_sim.decree import ResolveResult

    chain["stage"] = stage
    _save_chain(db, turn, chain, decree_text=decree_text, source=source)
    return ResolveResult(awaiting=False, advanced=False, stage=stage)


def _levy_block_declines_presentation(raw_json: str) -> bool:
    """合法不呈请：块是 JSON 对象且 present 恰为 false。坏 JSON 不是不呈请。"""
    import json

    try:
        obj = json.loads(raw_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(obj, dict) and obj.get("present") is False


def _split_at_question(text: str) -> tuple[str, List[dict]]:
    """前缀 = 首个真实请旨之前，并剔除此前的合法不呈请交接块。

    真实请旨 = 合法 DECISION，或 present 不是 false 的 LEVY。
    ``present: false`` 只是交接标记：从送去转译的前缀里拿掉，不截断其后的世界事实。
    整段只有这一块、没有其它事实时，前缀为空，标记本段完成仍合法。
    questions 只收 DECISION。LEVY 身份仍由全文交接读取。坏 JSON、非对象载荷
    在绑定处失败，并且从送去转译的前缀里切开，不把机标当世界事实送进去。
    """
    from ming_sim.settlement_payload import _DECISION_RE, parse_decision_blocks

    questions: List[dict] = []
    spans: List[tuple[int, int, bool]] = []
    for match in _DECISION_RE.finditer(text or ""):
        parsed = parse_decision_blocks(match.group(0))
        if not parsed:
            continue
        # Desk identity is allocated by the ledger, never by a model's echoed id.
        questions.extend({k: v for k, v in q.items() if k not in {"event_id", "origin_ref"}}
                         for q in parsed)
        spans.append((match.start(), match.end(), True))
    for match in _LEVY_BLOCK_RE.finditer(text or ""):
        declines = _levy_block_declines_presentation(match.group(1).strip())
        spans.append((match.start(), match.end(), not declines))
    # 未闭合的开头不是散文：从送去转译的前缀里切开，绑定处再按坏块失败。
    unclosed = _unclosed_levy_opener(text or "")
    if unclosed is not None:
        spans.append((unclosed, unclosed, True))
    spans.sort()
    first_real = next((start for start, _end, real in spans if real), None)
    limit = len(text or "") if first_real is None else first_real
    pieces: List[str] = []
    cursor = 0
    for start, end, real in spans:
        if start >= limit or real:
            break
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:limit])
    return "".join(pieces), questions


def _load_chain(db: Any, turn: int) -> Dict[str, Any]:
    ctx = db.resolve_contexts.get(turn) or {}
    payload = ctx.get("simulator_payload", {})
    chain = payload.get(_CHAIN_KEY)
    if chain is None:
        return {}
    return {**chain}


def _save_chain(
    db: Any, turn: int, chain: Dict[str, Any], *,
    decree_text: str = "", source: Provenance = Provenance.system_simulation,
) -> None:
    ctx = db.resolve_contexts.get(turn) or {}
    payload = {**ctx.get("simulator_payload", {})}
    payload[_CHAIN_KEY] = chain
    stored_source = ctx.get("source") or source
    source_value = stored_source.value if isinstance(stored_source, Provenance) else str(stored_source)
    db.resolve_contexts.save(
        turn,
        decree_text or str(ctx.get("decree_text") or ""),
        payload,
        source=source_value or Provenance.system_simulation.value,
        attendant_message=str(ctx.get("attendant_message") or ""),
    )
