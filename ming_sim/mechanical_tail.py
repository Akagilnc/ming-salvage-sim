"""#1845：月份推进后的机械尾（关系／派系酿制、结局总评）后台化。

复用 SessionWriteQueue 票键与 audience 执行器——与夜里预推同形，不另造平行调度。
持久未完态写在 closed turn 的 month_chain；重开／下次过月 ensure 续接。
召对高亮不在此列（ADR 0045）。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, Dict, Optional

from ming_sim.applier import Provenance
from ming_sim.models import _load_durable_json_object
from ming_sim.relation_brew import MonthEndRelationBrewLeg
from ming_sim.session_write_queue import get_session_write_queue

logger = logging.getLogger(__name__)

_TAIL_STATUS_PENDING = "pending"
_TAIL_STATUS_DONE = "done"
_TAIL_STATUS_FAILED = "failed"


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
    error_pack_path: Optional[str] = None,
) -> None:
    from ming_sim import month_chain

    chain = month_chain._load_chain(db, int(closed_turn))
    tail = chain.get("mechanical_tail")
    if tail is None or not tail.keys():
        return
    tail["status"] = status
    if status != _TAIL_STATUS_FAILED:
        tail.pop("error", None)
    if error_pack_path is not None:
        tail["error_pack_path"] = error_pack_path
    else:
        tail.pop("error_pack_path", None)
    chain["mechanical_tail"] = tail
    month_chain._save_chain(db, int(closed_turn), chain, source=source)


def generate_ending_summary_for_tail(
    db: Any,
    closed_state: Any,
    outcome: Dict[str, object],
    *,
    llm_config: Any = None,
    save_fn: Any = None,
    gate_run: Any = None,
) -> str:
    """结局总评按需取阅邸报目录；已落总评在重试／重开时不再生成。

    SQLite 读与落库走 gate_run（会话既有写闸）。模型调用留在闸外。
    """
    from ming_sim.agents import create_ending_summary_agent, run_agent_text
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.materials import prepare_ending_materials, release_material_tree
    import json

    under = gate_run if gate_run is not None else (lambda fn: fn())
    existing = under(db.reign.get_ending_summary)
    if existing is not None and int(existing["turn"]) == int(closed_state.turn):
        return str(existing["summary"])
    if llm_config is None:
        raise LLMUnavailable("结局总评缺少模型配置", stage="ending_summary")

    def _load_gazettes():
        loaded = []
        for row in db.turn_reports.list_archives():
            turn = int(row.get("turn") or 0)
            if turn > int(closed_state.turn):
                continue
            # P6 / ADR 0142：邸报正文是自由文本；判空只观察副本，下传原串。
            body = str(row.get("report") or row.get("body") or "")
            if not body.strip():
                continue
            loaded.append({
                "turn": turn,
                "year": int(row.get("year") or 0),
                "period": int(row.get("period") or 0),
                "body": body,
                "title": str(row.get("title") or ""),
            })
        return loaded

    reports = under(_load_gazettes)
    payload = {
        "ending": {
            "status": outcome.get("status"),
            "summary": outcome.get("summary"),
        },
        "final_state": {
            "year": closed_state.year,
            "period": closed_state.period,
            "turn": closed_state.turn,
            "metrics": dict(getattr(closed_state, "metrics", {}) or {}),
        },
    }
    prepared = prepare_ending_materials(db, closed_state, reports)
    try:
        ending_agent = create_ending_summary_agent(llm_config, prepared)
        summary_text = run_agent_text(
            ending_agent,
            json.dumps(payload, ensure_ascii=False, sort_keys=False),
            tag="ending-summary",
        )
    finally:
        release_material_tree(prepared.root)
    if not summary_text:
        return ""
    # 终章 UI 历程从同一份已加载邸报投影 gazette，不另读、不把第二份正文送进模型。
    timeline = [
        {
            "turn": int(row["turn"]),
            "year": int(row["year"]),
            "period": int(row["period"]),
            "gazette": str(row.get("body") or ""),
        }
        for row in reports
    ]
    save = save_fn or db.reign.save_ending_summary

    def _save():
        save(
            closed_state,
            str(outcome.get("status") or ""),
            summary_text,
            timeline,
        )

    under(_save)
    return summary_text


def _brew_fn_for_session(session: Any):
    """生产路径注入真实 LLM；缺配置如实失败，不给测试开空串分支。"""
    llm_config = getattr(session, "llm_config", None)
    if llm_config is None:
        from ming_sim.exceptions import LLMUnavailable

        def _missing(_payload: str) -> str:
            raise LLMUnavailable("关系酿制缺少模型配置", stage="relation_brew")

        return _missing

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
            create_faction_brew_agent(llm_config)
            if payload.get("view") == VIEW_FACTION_STANCE
            else create_relation_brew_agent(llm_config)
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
        # Persist the successful items first; their cleared pending claims prevent
        # retry from applying them again. The remaining failures belong to the
        # tail's existing failure/retry path, not a discarded degraded report.
        for _job, parsed, error in leg.outcomes:
            if error is not None:
                raise error
            if parsed is None:
                raise RuntimeError("关系／派系酿制无结果")


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

    def brew() -> None:
        _run_relation_brew(
            session, closed_turn=closed_turn, settled_year=settled_year,
            settled_period=settled_period, queue=queue, ticket=ticket,
        )

    if ending_outcome is None or not ending_outcome.get("status"):
        brew()
        return _TAIL_STATUS_DONE

    def ending() -> None:
        summary = generate_ending_summary_for_tail(
            db, closed_state, ending_outcome,
            llm_config=getattr(session, "llm_config", None),
            gate_run=lambda fn: queue.run(ticket, fn),
        )
        if not summary:
            raise RuntimeError("结局总评无正文")

    # Independent LLM legs; SQLite still uses the session's single write gate.
    # Observe both terminal results before releasing the parent ticket, even
    # when one fails. Successful DB results are the recovery checkpoints.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mechanical-tail") as pool:
        futures = [pool.submit(brew), pool.submit(ending)]
        errors = [error for future in futures if (error := future.exception()) is not None]
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup("；".join(str(error) for error in errors), errors)
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
        from ming_sim import month_chain

        def still_pending() -> bool:
            chain = month_chain._load_chain(session.db, int(closed_turn))
            tail = chain.get("mechanical_tail")
            return tail is not None and tail.get("status") == _TAIL_STATUS_PENDING

        try:
            # 扫描见到 pending 之后，上一张票可能已经终结。写闸内再读，
            # 避免把已完成的尾再跑一遍。
            if not queue.run(ticket, still_pending):
                return
            _run_tail_body(
                session,
                closed_turn=closed_turn,
                settled_year=settled_year,
                settled_period=settled_period,
                ending_outcome=ending_outcome,
                queue=queue,
                ticket=ticket,
            )
            queue.run(ticket, lambda: _set_tail_status(
                session.db, closed_turn, _TAIL_STATUS_DONE, source=source,
            ))
        except Exception as exc:
            logger.exception("[mechanical-tail] turn=%s 后台执行失败，等待玩家重试", closed_turn)
            from ming_sim.error_pack import write_error_pack

            def record_failure(error: Exception = exc) -> None:
                pack_path = write_error_pack(
                    session.db, session.state, exc=error,
                )
                from ming_sim import month_chain
                chain = month_chain._load_chain(session.db, closed_turn)
                chain["mechanical_tail"]["error"] = str(error)
                month_chain._save_chain(session.db, closed_turn, chain, source=source)
                _set_tail_status(
                    session.db, closed_turn, _TAIL_STATUS_FAILED,
                    source=source, error_pack_path=pack_path,
                )

            queue.run(ticket, record_failure)
            raise
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
    """#1843 主链推进后启动本月机械尾；接线异常沿现役出口上抛。"""
    if not pending_already_marked:
        mark_mechanical_tail_pending(
            session.db, closed_turn,
            settled_year=settled_year,
            settled_period=settled_period,
            ending_outcome=ending_outcome,
            source=source,
        )
    get_session_write_queue(session)
    _submit_tail(
        session,
        closed_turn=closed_turn,
        settled_year=settled_year,
        settled_period=settled_period,
        ending_outcome=ending_outcome,
        source=source,
    )


def _pending_mechanical_tails(
    db: Any,
) -> list[tuple[int, Dict[str, Any]]]:
    """Still-running tails; code failures require an explicit retry."""
    from ming_sim import month_chain

    pending: list[tuple[int, Dict[str, Any]]] = []
    for turn in db.resolve_contexts.turns():
        chain = month_chain._load_chain(db, turn)
        tail = chain.get("mechanical_tail")
        if tail is not None and tail.get("status") == _TAIL_STATUS_PENDING:
            pending.append((turn, tail))
    return pending


def failed_mechanical_tail(db: Any) -> Optional[tuple[int, Dict[str, Any]]]:
    """Persisted failure, visible even when no next month exists."""
    from ming_sim import month_chain

    for turn in db.resolve_contexts.turns():
        tail = month_chain._load_chain(db, turn).get("mechanical_tail")
        if tail is not None and tail.get("status") == _TAIL_STATUS_FAILED:
            return turn, tail
    return None


def retry_failed_mechanical_tail(session: Any) -> bool:
    failure = failed_mechanical_tail(session.db)
    if failure is None:
        return False
    turn, tail = failure
    # 必要读取（含 ending_outcome 形状）须先于 pending 写；失败态/真因/重试归属
    # 在读取失败时不得被 _set_tail_status 洗失。
    settled_year = int(tail.get("settled_year") or 0)
    settled_period = int(tail.get("settled_period") or 0)
    ending_outcome = tail.get("ending_outcome")
    if ending_outcome is not None:
        ending_outcome = {**ending_outcome}
    _set_tail_status(session.db, turn, _TAIL_STATUS_PENDING,
                     source=Provenance.system_simulation)
    return _submit_tail(
        session, closed_turn=turn,
        settled_year=settled_year,
        settled_period=settled_period,
        ending_outcome=ending_outcome,
        source=Provenance.system_simulation,
    )


def ending_summary_pending(db: Any, state: Any) -> bool:
    """结局总评尾尚未终结。前台不等；完成前呈现层据此重取。"""
    if not bool(getattr(state, "ended", False)):
        return False
    for _turn, tail in _pending_mechanical_tails(db):
        outcome = tail.get("ending_outcome")
        if outcome is not None and outcome.get("status"):
            return True
    return False


def ensure_mechanical_tails(session: Any) -> None:
    """重开或下次过月前：按 DB pending 续接未完尾（claim_if_absent 防重复执行）。"""
    db = session.db
    get_session_write_queue(session)
    pending_turns = _pending_mechanical_tails(db)

    source = Provenance.system_simulation
    for turn, tail in pending_turns:
        _submit_tail(
            session,
            closed_turn=turn,
            settled_year=int(tail["settled_year"]),
            settled_period=int(tail["settled_period"]),
            ending_outcome=_load_durable_json_object(tail.get("ending_outcome"), surface="ending_outcome"),
            source=source,
        )
