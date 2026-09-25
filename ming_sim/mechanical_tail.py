"""#1845：月份推进后的机械尾（关系／派系酿制、结局总评）后台化。

复用 SessionWriteQueue 票键与 audience 执行器——与夜里预推同形，不另造平行调度。
持久未完态写在 closed turn 的 month_chain；重开／下次过月 ensure 续接。
召对高亮不在此列（ADR 0045）。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, Optional

from ming_sim.applier import Provenance
from ming_sim.relation_brew import MonthEndRelationBrewLeg
from ming_sim.session_write_queue import get_session_write_queue
from ming_sim.decree_forecast import _call_exhausted

logger = logging.getLogger(__name__)

_TAIL_STATUS_PENDING = "pending"
_TAIL_STATUS_DONE = "done"
_TAIL_STATUS_DEGRADED = "degraded"


def mechanical_tail_key(closed_turn: int) -> tuple:
    return ("mechanical-tail", int(closed_turn))


def mark_mechanical_tail_pending(
    db: Any,
    closed_turn: int,
    *,
    settled_year: int,
    settled_period: int,
    ending_outcome: Optional[Dict[str, object]] = None,
    source: Provenance = Provenance.system_simulation,
) -> None:
    """推进后落盘未完尾——恢复真源，不靠内存票。"""
    from ming_sim import month_chain

    chain = month_chain._load_chain(db, int(closed_turn))
    chain["mechanical_tail"] = {
        "status": _TAIL_STATUS_PENDING,
        "settled_year": int(settled_year),
        "settled_period": int(settled_period),
        "ending_outcome": ending_outcome,
    }
    month_chain._save_chain(db, int(closed_turn), chain, source=source)


def _set_tail_status(
    db: Any, closed_turn: int, status: str, *, source: Provenance,
) -> None:
    from ming_sim import month_chain

    chain = month_chain._load_chain(db, int(closed_turn))
    tail = dict(chain.get("mechanical_tail") or {})
    if not tail:
        return
    tail["status"] = status
    chain["mechanical_tail"] = tail
    month_chain._save_chain(db, int(closed_turn), chain, source=source)


def generate_ending_summary_for_tail(
    db: Any,
    closed_state: Any,
    outcome: Dict[str, object],
    *,
    llm_config: Any = None,
    agno_db: Any = None,
    save_fn: Any = None,
) -> str:
    """结局总评：读历月邸报／时间线，不再依赖章节记忆。"""
    from ming_sim.agents import create_ending_summary_agent, run_agent_text
    from ming_sim.memories import build_timeline
    import json

    if llm_config is None:
        return ""
    reports = []
    if hasattr(db, "list_turn_reports"):
        for row in db.list_turn_reports():
            turn = int(row.get("turn") or 0)
            if turn > int(closed_state.turn):
                continue
            body = str(row.get("report") or row.get("body") or "").strip()
            if not body:
                continue
            reports.append({
                "turn": turn,
                "year": int(row.get("year") or 0),
                "period": int(row.get("period") or 0),
                "body": body,
            })
    timeline = build_timeline(db, upto_turn=int(closed_state.turn))
    ending_agent = create_ending_summary_agent(llm_config, agno_db)
    payload = {
        "ending": {
            "status": outcome.get("status"),
            "summary": outcome.get("summary"),
        },
        "gazettes": reports,
        "timeline": timeline,
        "final_state": {
            "year": closed_state.year,
            "period": closed_state.period,
            "turn": closed_state.turn,
            "metrics": dict(getattr(closed_state, "metrics", {}) or {}),
        },
    }
    summary_text = run_agent_text(
        ending_agent,
        json.dumps(payload, ensure_ascii=False, sort_keys=False),
        tag="ending-summary",
    ).strip()
    if not summary_text:
        return ""
    save = save_fn or db.save_ending_summary
    save(
        closed_state,
        str(outcome.get("status") or ""),
        summary_text,
        timeline,
    )
    return summary_text


def _brew_fn_for_session(session: Any):
    """生产路径注入真实 LLM；测试无模型时用空串保底。"""
    llm_config = getattr(session, "llm_config", None)
    agno_db = getattr(session, "agno_db", None)
    if llm_config is None:
        return lambda _payload: ""

    from ming_sim.agents import (
        create_faction_brew_agent,
        create_relation_brew_agent,
        run_agent_text,
    )
    from ming_sim.faction_brew import VIEW_FACTION_STANCE
    from ming_sim.llm_model import llm_unavailable_from_error
    from openai import APIConnectionError, APIStatusError, APITimeoutError
    import json

    def _brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        agent = (
            create_faction_brew_agent(llm_config, agno_db)
            if payload.get("view") == VIEW_FACTION_STANCE
            else create_relation_brew_agent(llm_config, agno_db)
        )
        try:
            return run_agent_text(agent, payload_json, tag="relation-brew")
        except (APITimeoutError, APIConnectionError, APIStatusError) as error:
            raise llm_unavailable_from_error(error, "关系酿制") from error

    return _brew


def _run_relation_brew(
    session: Any,
    *,
    closed_turn: int,
    settled_year: int,
    settled_period: int,
    queue: Any,
    ticket: Any,
) -> None:
    leg = MonthEndRelationBrewLeg(
        session.db, session.state, _brew_fn_for_session(session),
        settled_turn=int(closed_turn),
        settled_year=int(settled_year),
        settled_period=int(settled_period),
    )
    if queue.run(ticket, leg.prepare):
        leg.brew()
        queue.run(ticket, leg.persist)


def _run_tail_body(
    session: Any,
    *,
    closed_turn: int,
    settled_year: int,
    settled_period: int,
    ending_outcome: Optional[Dict[str, object]],
    queue: Any,
    ticket: Any,
) -> str:
    db, state = session.db, session.state
    closed_state = SimpleNamespace(
        turn=int(closed_turn),
        year=int(settled_year),
        period=int(settled_period),
        metrics=dict(getattr(state, "metrics", {}) or {}),
        ended=bool(getattr(state, "ended", False)),
    )
    _run_relation_brew(
        session, closed_turn=closed_turn, settled_year=settled_year,
        settled_period=settled_period, queue=queue, ticket=ticket,
    )
    if isinstance(ending_outcome, dict) and ending_outcome.get("status"):
        generate_ending_summary_for_tail(
            db, closed_state, ending_outcome,
            llm_config=getattr(session, "llm_config", None),
            agno_db=getattr(session, "agno_db", None),
            save_fn=lambda *args: queue.run(
                ticket, lambda: db.save_ending_summary(*args),
            ),
        )
    return _TAIL_STATUS_DONE


def _submit_tail(
    session: Any,
    *,
    closed_turn: int,
    settled_year: int,
    settled_period: int,
    ending_outcome: Optional[Dict[str, object]],
    source: Provenance,
) -> bool:
    from ming_sim import audience_translation

    queue = get_session_write_queue(session)
    ticket = queue.claim_if_absent([mechanical_tail_key(closed_turn)])[0]
    if ticket is None:
        return False

    def run() -> None:
        status = _TAIL_STATUS_DONE
        try:
            status = _run_tail_body(
                session,
                closed_turn=closed_turn,
                settled_year=settled_year,
                settled_period=settled_period,
                ending_outcome=ending_outcome,
                queue=queue,
                ticket=ticket,
            )
            queue.run(ticket, lambda: _set_tail_status(
                session.db, closed_turn, status, source=source,
            ))
        except Exception as exc:
            if not _call_exhausted(exc):
                logger.exception(
                    "[mechanical-tail] turn=%s 后台执行失败，保留 pending 供续接",
                    closed_turn,
                )
                raise
            status = _TAIL_STATUS_DEGRADED
            logger.info(
                "[mechanical-tail] turn=%s 耗尽降级留痕：%s", closed_turn, exc,
            )
            queue.run(ticket, lambda: _set_tail_status(
                session.db, closed_turn, status, source=source,
            ))
        finally:
            queue.complete(ticket)

    try:
        future = audience_translation._executor.submit(run)
    except BaseException:
        queue.complete(ticket)
        raise
    future.add_done_callback(
        lambda done: audience_translation._observe_finished_future(
            done, where="mechanical tail", key=getattr(ticket, "key", None),
        )
    )
    return True


def schedule_mechanical_tail_after_advance(
    session: Any,
    *,
    closed_turn: int,
    settled_year: int,
    settled_period: int,
    ending_outcome: Optional[Dict[str, object]] = None,
    source: Provenance = Provenance.system_simulation,
    pending_already_marked: bool = False,
) -> None:
    """#1843 主链推进后启动本月机械尾；无会话写队列则只保留 pending。"""
    if not pending_already_marked:
        mark_mechanical_tail_pending(
            session.db, closed_turn,
            settled_year=settled_year,
            settled_period=settled_period,
            ending_outcome=ending_outcome,
            source=source,
        )
    try:
        get_session_write_queue(session)
    except Exception:
        return
    _submit_tail(
        session,
        closed_turn=closed_turn,
        settled_year=settled_year,
        settled_period=settled_period,
        ending_outcome=ending_outcome,
        source=source,
    )


def ensure_mechanical_tails(session: Any) -> None:
    """重开或下次过月前：按 DB pending 续接未完尾（claim_if_absent 防重复执行）。"""
    from ming_sim import month_chain

    db = session.db
    try:
        get_session_write_queue(session)
    except Exception:
        return
    pending_turns: list[tuple[int, Dict[str, Any]]] = []
    current = int(getattr(session.state, "turn", 0) or 0)
    # 下月 barrier 保证最多只有紧邻的已结束月份可以遗留 pending。
    for turn in range(max(0, current - 1), current + 1):
        chain = month_chain._load_chain(db, turn)
        tail = chain.get("mechanical_tail")
        if isinstance(tail, dict) and tail.get("status") == _TAIL_STATUS_PENDING:
            pending_turns.append((turn, tail))

    source = Provenance.system_simulation
    for turn, tail in pending_turns:
        _submit_tail(
            session,
            closed_turn=turn,
            settled_year=int(tail.get("settled_year") or 0),
            settled_period=int(tail.get("settled_period") or 0),
            ending_outcome=tail.get("ending_outcome")
            if isinstance(tail.get("ending_outcome"), dict) else None,
            source=source,
        )
