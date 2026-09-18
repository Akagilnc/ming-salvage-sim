"""召对转译场中承接与后台调度（C1b #1838；T2 #1842）。

同步落账核：声明已到手后，接到既有分派器（分段/可闻性/在场/主角/边事件/
公开说法及 C0 其余 section），源轮绑定、主角持久化、抽取/判官水位推进——
故事抽取、边事件判官、代码触发读心不再另起（ADR 0155 场中承接段）。

后台调度（#1842）：每轮回话后按轮串行起转译，前台不等；封夜提交 join
最后一轮；耗尽标 extract_status=pending（待补），不挡下一句；过月前 join
全部。水位复用 chat_turns.extract_status（与旧抽取同一真源，转译承接后
标 done，收夜不再跑故事抽取）。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Mapping, Optional

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import set_night_protagonist
from ming_sim.declaration_dispatch import (
    DeclarationDispatchResult,
    dispatch_declaration,
)

TranslateFn = Callable[[str, Any], Mapping[str, object]]

# 进程级：按夜串行（同一夜 FIFO）；跨夜可并行。
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="audience-translate")
_night_serial_guard = threading.Lock()
_night_serial_locks: Dict[int, threading.Lock] = {}
_night_inflight_guard = threading.Lock()
_night_inflight: Dict[int, List[Future]] = {}


def apply_audience_round_translation(
    db: Any,
    state: Any,
    declaration: Mapping[str, object],
    *,
    night_id: int,
    chat_turn_id: int = 0,
    minister_name: str = "",
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """把本轮转译声明落到召对夜账本与世界记录，并按源轮绑主角 / 水位。

    - ``night_id``：本轮所属召对夜（在场进出、说话人分段挂此夜）
    - ``chat_turn_id``：源对话轮；>0 时 ledger 写 ``source_chat_turn_id``、主角
      写到该轮与夜当前值，并把 ``extract_status`` / ``relation_judge_status``
      标 ``done``（转译已承接，收夜不再跑故事抽取 / 边事件判官）

    第四类落账委托公开入口 :func:`dispatch_declaration`——入口自记撤回前像，
    后台 worker 直接调用本函数时 undo 亦可逆转，不另造第二份 capture/record。
    主角 / 水位写仍由本入口在分派后执行（chat_turns 不在前像表，属 #1838 语义）。
    """
    nid = int(night_id or 0)
    ctid = int(chat_turn_id or 0)
    # 复用公开入口的前像自足机制；不直调私有执行体绕过 capture/record。
    result = dispatch_declaration(
        db, state, declaration,
        minister_name=minister_name,
        night_id=nid,
        chat_turn_id=ctid,
        source=source,
    )
    # 主角持久化 + 抽取/判官水位：chat_turns 不在前像表，undo 走重投影。
    with atomic(db):
        _bind_round_after_dispatch(db, nid, ctid, result)
    return result


def _bind_round_after_dispatch(
    db: Any,
    night_id: int,
    chat_turn_id: int,
    result: DeclarationDispatchResult,
) -> None:
    """主角持久化 + 本轮抽取/判官水位。须在调用方 atomic 内。"""
    validated = result.protagonist.validated
    name = ""
    if isinstance(validated, Mapping):
        name = str(validated.get("person_name") or "").strip()
    if name and night_id > 0:
        set_night_protagonist(db, night_id, name, reason="translation", commit=False)
    if chat_turn_id <= 0:
        return
    if name:
        db.conn.execute(
            "UPDATE chat_turns SET protagonist_name=? WHERE id=?",
            (name, int(chat_turn_id)),
        )
    # 转译已声明本轮记录 → 故事抽取与边事件判官退役于本轮（水位 done，收夜 drain 跳过）
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done', relation_judge_status='done' "
        "WHERE id=? AND status NOT IN ('failed','undone')",
        (int(chat_turn_id),),
    )


def _night_lock(night_id: int) -> threading.Lock:
    nid = int(night_id or 0)
    with _night_serial_guard:
        lock = _night_serial_locks.get(nid)
        if lock is None:
            lock = threading.Lock()
            _night_serial_locks[nid] = lock
        return lock


def _track_future(night_id: int, fut: Future) -> None:
    nid = int(night_id or 0)
    with _night_inflight_guard:
        _night_inflight.setdefault(nid, []).append(fut)

        def _cleanup(_f: Future, *, _nid: int = nid, _fut: Future = fut) -> None:
            with _night_inflight_guard:
                bucket = _night_inflight.get(_nid) or []
                try:
                    bucket.remove(_fut)
                except ValueError:
                    pass
                if not bucket:
                    _night_inflight.pop(_nid, None)

        fut.add_done_callback(_cleanup)


def _mark_translation_pending(db: Any, chat_turn_id: int, write_gate: Any) -> None:
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "mark_story_extraction_pending"):
        return
    gate = write_gate if write_gate is not None else threading.Lock()
    with gate:
        db.mark_story_extraction_pending(ctid)


def list_pending_translations(
    db: Any, *, night_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """转译待补真源：复用 list_unextracted_replies（extract_status ''/'pending'）。"""
    if not hasattr(db, "list_unextracted_replies"):
        return []
    return list(db.list_unextracted_replies(night_id=night_id) or [])


def run_turn_translation_job(
    db: Any,
    state: Any,
    *,
    emperor_message: str,
    reply: str,
    night_id: int,
    chat_turn_id: int,
    minister_name: str = "",
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
    write_gate: Any = None,
    source: Provenance = Provenance.system_simulation,
) -> DeclarationDispatchResult:
    """单轮转译+落账（已持夜串行锁时由 worker 调用；失败标 pending）。"""
    from ming_sim.audience_translate import (
        AudienceTranslateError,
        run_audience_turn_translation,
    )

    ctid = int(chat_turn_id or 0)
    nid = int(night_id or 0)
    gate = write_gate  # 可为 None（单写测试路径）

    def _gate_cm():
        if gate is None:
            import contextlib
            return contextlib.nullcontext()
        return gate

    # 死轮 / 已 done：闸内短读后早退（禁持非重入锁再嵌套写）。
    already_done = False
    if ctid > 0 and hasattr(db, "conn"):
        with _gate_cm():
            row = db.conn.execute(
                "SELECT status FROM chat_turns WHERE id=?", (ctid,),
            ).fetchone()
            if row is not None and str(row["status"] or "") in {"failed", "undone"}:
                raise AudienceTranslateError(f"源轮已死：chat_turn_id={ctid}")
            already_done = (
                hasattr(db, "get_story_extract_status")
                and db.get_story_extract_status(ctid) == "done"
            )
            if not already_done and hasattr(db, "mark_story_extraction_pending"):
                db.mark_story_extraction_pending(ctid)
        if already_done:
            from ming_sim.applier import SectionResult
            from ming_sim.declaration_dispatch import ProtagonistResult
            empty = SectionResult(applied=[], rejected=[])
            return DeclarationDispatchResult(
                commissions=empty, promises=empty, textual_facts=empty,
                public_sayings=empty, on_scene_facts=empty, presence=empty,
                scene_facts=empty, edge_events=empty,
                protagonist=ProtagonistResult(validated=None, rejected=[]),
                registrations=empty,
            )

    try:
        # LLM 在 write_gate 外；声明到手后再短持锁落账。
        from ming_sim.audience_translate import (
            build_night_said_so_far,
            build_pending_summaries,
            translate_audience_turn,
        )
        # 读上下文：有 gate 则短持（共享 conn）；无 gate 直接读。
        with _gate_cm():
            night_said = build_night_said_so_far(db, nid)
            pending = build_pending_summaries(db, int(state.turn), night_id=nid)
        declaration = translate_audience_turn(
            emperor_message=emperor_message,
            reply=reply,
            night_said=night_said,
            pending_summaries=pending,
            llm_config=llm_config,
            translate_fn=translate_fn,
        )
        with _gate_cm():
            return apply_audience_round_translation(
                db, state, declaration,
                night_id=nid, chat_turn_id=ctid,
                minister_name=minister_name, source=source,
            )
    except Exception:
        _mark_translation_pending(db, ctid, write_gate)
        raise


def schedule_audience_turn_translation(
    db: Any,
    state: Any,
    *,
    emperor_message: str,
    reply: str,
    night_id: int,
    chat_turn_id: int,
    minister_name: str = "",
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
    write_gate: Any = None,
    source: Provenance = Provenance.system_simulation,
) -> Future:
    """后台调度本轮转译：立即返回 Future；同夜按轮串行。"""
    nid = int(night_id or 0)
    ctid = int(chat_turn_id or 0)
    if ctid > 0 and hasattr(db, "mark_story_extraction_pending"):
        gate = write_gate if write_gate is not None else threading.Lock()
        with gate:
            db.mark_story_extraction_pending(ctid)

    serial = _night_lock(nid)

    def _worker() -> DeclarationDispatchResult:
        with serial:
            return run_turn_translation_job(
                db, state,
                emperor_message=emperor_message,
                reply=reply,
                night_id=nid,
                chat_turn_id=ctid,
                minister_name=minister_name,
                llm_config=llm_config,
                translate_fn=translate_fn,
                write_gate=write_gate,
                source=source,
            )

    fut = _executor.submit(_worker)
    _track_future(nid, fut)
    return fut


def join_night_translations(night_id: int, *, timeout_s: float = 120.0) -> bool:
    """等待本夜在飞转译全部结束（成功或失败）。返回是否在时限内清空。"""
    import time

    nid = int(night_id or 0)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        with _night_inflight_guard:
            bucket = list(_night_inflight.get(nid) or ())
        if not bucket:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        for fut in bucket:
            try:
                fut.result(timeout=min(remaining, 0.5))
            except Exception:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False


def join_all_translations(*, timeout_s: float = 120.0) -> bool:
    """过月前 join：等全部夜的在飞转译。"""
    import time

    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        with _night_inflight_guard:
            nights = list(_night_inflight.keys())
        if not nights:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        for nid in nights:
            ok = join_night_translations(nid, timeout_s=remaining)
            if not ok:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False


def catch_up_pending_translations(
    db: Any,
    state: Any,
    *,
    night_id: Optional[int] = None,
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
    write_gate: Any = None,
    source: Provenance = Provenance.system_simulation,
) -> Dict[str, int]:
    """补跑转译待补：已持久化回话但 extract_status 未 done 的轮，按夜序串行重试。

    **从不抛**——单轮失败保持 pending，继续后续轮。
    """
    rows = list_pending_translations(db, night_id=night_id)
    extracted = 0
    pending = 0
    scanned = 0
    for row in rows:
        scanned += 1
        ctid = int(row.get("chat_turn_id") or 0)
        nid = int(row.get("night_id") or 0)
        reply = str(row.get("reply") or "")
        emperor = ""
        if ctid > 0 and hasattr(db, "conn"):
            gate = write_gate if write_gate is not None else threading.Lock()
            try:
                with gate:
                    trow = db.conn.execute(
                        "SELECT user_message_id FROM chat_turns WHERE id=?", (ctid,),
                    ).fetchone()
                    if trow is not None and trow["user_message_id"]:
                        mrow = db.conn.execute(
                            "SELECT content FROM chat_messages WHERE id=?",
                            (int(trow["user_message_id"]),),
                        ).fetchone()
                        if mrow is not None:
                            emperor = str(mrow["content"] or "")
            except Exception:
                pass
        serial = _night_lock(nid)
        try:
            with serial:
                run_turn_translation_job(
                    db, state,
                    emperor_message=emperor,
                    reply=reply,
                    night_id=nid,
                    chat_turn_id=ctid,
                    llm_config=llm_config,
                    translate_fn=translate_fn,
                    write_gate=write_gate,
                    source=source,
                )
            extracted += 1
        except Exception:
            pending += 1
    return {"extracted": extracted, "pending": pending, "scanned": scanned}
