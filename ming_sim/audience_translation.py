"""召对转译场中承接与后台调度（C1b #1838；T2 #1842）。

同步落账核：声明已到手后，接到既有分派器（分段/可闻性/在场/主角/边事件/
公开说法及 C0 其余 section），源轮绑定、主角持久化、抽取/判官水位推进——
故事抽取、边事件判官、代码触发读心不再另起（ADR 0155 场中承接段）。

后台调度（#1842）：每轮回话后按轮串行起转译，前台不等；转译以
SessionWriteQueue 票据登记，封夜与过月 barrier 等待此前已受理票据排空；
耗尽标 extract_status=pending（待补），不挡下一句。水位复用
chat_turns.extract_status（与旧抽取同一真源，转译承接后标 done，收夜不再跑
故事抽取）。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import set_night_protagonist
from ming_sim.declaration_dispatch import (
    DeclarationDispatchResult,
    dispatch_declaration,
)

TranslateFn = Callable[[str, Any], Mapping[str, object]]
logger = logging.getLogger(__name__)

# 同夜 FIFO 只保留 Future tail；在飞/排空/关闭的唯一真源是
# SessionWriteQueue 的 open ticket。Future 不再另建 owner/night ledger。
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="audience-translate")
_night_inflight_guard = threading.Lock()
_night_tail: Dict[Tuple[int, int], Future] = {}  # (queue identity, night_id)
_turn_future: Dict[Tuple[int, int], Future] = {}  # cancellation scheduling only


def translation_holding_write_gate(gate: Any) -> bool:
    """该 gate 是否正被转译短持（与所有权同临界可读；不 join、不 cancel）。"""
    from ming_sim.session_write_queue import ClassifiedWriteGate

    if isinstance(gate, ClassifiedWriteGate):
        return gate.is_held_by_translation()
    return False


def wait_translation_write_gate_released(gate: Any) -> None:
    """等到该 gate 不再被转译持有（不抢闸、不加超时；结算/他写不抬此等待）。"""
    from ming_sim.session_write_queue import ClassifiedWriteGate

    if isinstance(gate, ClassifiedWriteGate):
        gate.wait_while_held_by_translation()


@contextlib.contextmanager
def _translation_write_cm(gate: Any) -> Iterator[None]:
    """转译侧短持会话 write_gate；holder kind 与取得所有权同临界（#1842）。"""
    from ming_sim.session_write_queue import ClassifiedWriteGate

    if gate is None:
        yield
        return
    if isinstance(gate, ClassifiedWriteGate):
        gate.acquire_translation()
    else:
        # 裸 Lock 测试夹具：无分类能力，仅保互斥（生产路径均为 ClassifiedWriteGate）。
        gate.acquire()
    try:
        yield
    finally:
        gate.release()


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
    # 单轮转译权威事务：section 副作用 + 拒收 flush + 撤回前像（dispatch 内）
    # + 主角/水位共处同一 atomic（嵌套 flat）；不另开第二段提交。
    # 复用公开入口的前像自足机制；不直调私有执行体绕过 capture/record。
    with atomic(db):
        result = dispatch_declaration(
            db, state, declaration,
            minister_name=minister_name,
            night_id=nid,
            chat_turn_id=ctid,
            source=source,
        )
        # 分段若有一项拒收，整轮不可标 done；atomic 回滚部分落账，后台保 pending。
        if ctid > 0 and result.scene_facts.rejected:
            from ming_sim.audience_translate import AudienceTranslateError
            raise AudienceTranslateError("说话人分段声明有拒收项")
        # 主角持久化 + 抽取/判官水位：chat_turns 不在前像表，undo 走重投影。
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
    mark_turn_translation_done(db, chat_turn_id, commit=False)


def mark_turn_translation_done(
    db: Any, chat_turn_id: int, *, commit: bool = True,
) -> None:
    """水位单真源：源轮 extract/relation_judge → done（控制口令早退与转译落账共用）。"""
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "conn"):
        return
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done', relation_judge_status='done' "
        "WHERE id=? AND status NOT IN ('failed','undone')",
        (ctid,),
    )
    if not commit:
        return
    if (
        not bool(getattr(db.conn, "_commit_suspended", False))
        and int(getattr(db.conn, "_atomic_depth", 0) or 0) == 0
    ):
        db.conn.commit()


def cancel_turn_translation(chat_turn_id: int, *, write_queue: Any) -> int:
    """撤回本轮：由 SessionWriteQueue 取消唯一在飞票。"""
    ctid = int(chat_turn_id or 0)
    if ctid <= 0:
        return 0
    n = int(write_queue.cancel_key(("audience_translation", ctid)))
    turn_key = (id(write_queue), ctid)
    with _night_inflight_guard:
        fut = _turn_future.get(turn_key)
    if fut is not None:
        fut.cancel()
    return n


def _observe_finished_future(
    fut: Future,
    *,
    where: str,
    **fields: Any,
) -> None:
    """已完成 Future 的终态观测：失败留痕；取消不当事故。须在摘账前调用。"""
    if not fut.done():
        return
    try:
        exc = fut.exception()
    except CancelledError:
        return
    if exc is None:
        return
    detail = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.error("%s: future failed %s", where, detail, exc_info=exc)


def _mark_translation_pending(db: Any, chat_turn_id: int, write_gate: Any) -> None:
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "mark_story_extraction_pending"):
        return
    # 失败路径短持：与 job 内读写同属转译持闸类（ClassifiedWriteGate kind）。
    with _translation_write_cm(write_gate):
        db.mark_story_extraction_pending(ctid)


def list_pending_translations(
    db: Any, *, night_id: Optional[int] = None, chat_turn_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """转译待补真源：复用 list_unextracted_replies（extract_status ''/'pending'）。

    可按夜 / 源轮收窄。返回行附结构化系统提示态（供 0158 决定 6 投影，不做页面）。
    """
    if not hasattr(db, "list_unextracted_replies"):
        return []
    rows = list(db.list_unextracted_replies(night_id=night_id) or [])
    want = int(chat_turn_id) if chat_turn_id is not None else None
    out: List[Dict[str, Any]] = []
    for row in rows:
        ctid = int(row.get("chat_turn_id") or 0)
        if want is not None and ctid != want:
            continue
        item = dict(row)
        item["chat_turn_id"] = ctid
        item["night_id"] = int(row.get("night_id") or 0)
        item["minister_name"] = str(row.get("minister_name") or "")
        # 结构化系统提示状态（前端渲染提示行 + 重试钮；本层只交能力）
        item["kind"] = "translation_pending"
        item["retryable"] = True
        item["extract_status"] = str(row.get("extract_status") or "pending") or "pending"
        out.append(item)
    return out


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
        # 转译短持带 holder kind，供前台非阻塞抢闸区分「等转译」与「结算 → 409」。
        return _translation_write_cm(gate)

    # 死轮 / 未落定回话 / 已 done：闸内短读后早退（禁持非重入锁再嵌套写）。
    # ADR 0155 / 0036：转译真源 = 已持久化回话；generating 或无 minister_message_id 拒绝。
    already_done = False
    if ctid > 0 and hasattr(db, "conn"):
        with _gate_cm():
            row = db.conn.execute(
                "SELECT status, minister_message_id FROM chat_turns WHERE id=?",
                (ctid,),
            ).fetchone()
            if row is not None and str(row["status"] or "") in {"failed", "undone"}:
                raise AudienceTranslateError(f"源轮已死：chat_turn_id={ctid}")
            status = str(row["status"] or "") if row is not None else ""
            mid = 0
            if row is not None and row["minister_message_id"] is not None:
                try:
                    mid = int(row["minister_message_id"] or 0)
                except (TypeError, ValueError):
                    mid = 0
            if status == "generating" or mid <= 0:
                raise AudienceTranslateError(
                    f"源轮回话未落定：chat_turn_id={ctid} status={status}"
                )
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
        # said-so-far 按本源轮截止，不读后续轮、不重复本轮（ADR 0155）。
        with _gate_cm():
            night_said = build_night_said_so_far(
                db, nid, until_chat_turn_id=ctid,
            )
            pending = build_pending_summaries(db, int(state.turn), night_id=nid)
            from ming_sim.audience_translate import build_translation_target_grounding
            target_grounding = build_translation_target_grounding(db)
        declaration = translate_audience_turn(
            emperor_message=emperor_message,
            reply=reply,
            night_said=night_said,
            pending_summaries=pending,
            target_grounding=target_grounding,
            llm_config=llm_config,
            translate_fn=translate_fn,
        )
        # 分段是整轮回话的结构化覆盖声明；不完整或改字不得入账并置 done。
        # 失败走既有 pending/retry 路径，原戏文继续中性显示。
        segments = declaration.get("scene_facts")
        if (
            not isinstance(segments, list) or not segments
            or any(not isinstance(item, Mapping) or item.get("role") not in {"user", "minister", "attendant", "scene"}
                   or not isinstance(item.get("body"), str) for item in segments)
            or "".join(item["body"] for item in segments) != reply
        ):
            raise AudienceTranslateError("说话人分段未逐字覆盖源轮回话")
        with _gate_cm():
            # 落账临界区复查源轮仍存活（ADR 0038：后台写入前须校验目标轮仍存活）。
            if ctid > 0 and hasattr(db, "conn"):
                live = db.conn.execute(
                    "SELECT status FROM chat_turns WHERE id=?", (ctid,),
                ).fetchone()
                if live is None or str(live["status"] or "") in {"failed", "undone"}:
                    from ming_sim.audience_translate import AudienceTranslateError
                    raise AudienceTranslateError(
                        f"源轮已死（落账前复查）：chat_turn_id={ctid}"
                    )
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
    write_queue: Any = None,
    admitted_ticket: Any = None,
    source: Provenance = Provenance.system_simulation,
) -> Future:
    """后台调度本轮转译：立即返回 Future；同夜按轮串行（显式 Future 链 FIFO）。"""
    nid = int(night_id or 0)
    ctid = int(chat_turn_id or 0)
    if write_queue is None:
        raise RuntimeError("audience translation requires SessionWriteQueue")
    ticket = (
        write_queue.retain(admitted_ticket, ("audience_translation", ctid))
        if admitted_ticket is not None
        else write_queue.claim(key=("audience_translation", ctid))
    )
    if ticket is None:
        raise RuntimeError("write queue sealed")
    try:
        if ctid > 0 and hasattr(db, "mark_story_extraction_pending"):
            # 调度线程短标 pending：同属转译持闸类（调用方须已放闸，禁嵌套非重入锁）。
            with _translation_write_cm(write_gate):
                db.mark_story_extraction_pending(ctid)
    except Exception:
        write_queue.complete(ticket)
        raise

    night_key = (id(write_queue), nid)

    def _run_job() -> DeclarationDispatchResult:
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

    def _observe_predecessor(pred: Future) -> None:
        """前驱失败留痕后仍跑本轮（每轮失败隔离）；不占执行线程等待。"""
        try:
            pred.result()
        except Exception:
            logger.exception(
                "audience translation predecessor failed; "
                "continuing night=%s chat_turn_id=%s",
                nid, ctid,
            )

    # 同夜 FIFO 真源 = Future 链。后继不得先占 worker 再 pred.result()——旧局积压
    # 会填满进程级线程池，饿死新会话（票面：新局不等待旧局后台转译）。
    # 有未完成前驱时只登记占位 Future，前驱终态后再 submit 实活；无前驱则直接提交。
    # 读前驱 + 登记同持非重入锁；done callback 一律锁外挂（已完成 Future 同步回调会死锁）。
    with _night_inflight_guard:
        pred = _night_tail.get(night_key)
        # Future 终态先于 cleanup callback 可见；此窗口内的 tail 已不是
        # 在飞前驱，新一轮不得继承它的旧失败。
        if pred is not None and pred.done():
            pred = None
        if pred is None:
            fut: Future = _executor.submit(_run_job)
            chain_pred: Optional[Future] = None
        else:
            fut = Future()
            chain_pred = pred
        _night_tail[night_key] = fut
        if ctid > 0:
            _turn_future[(id(write_queue), ctid)] = fut

    def _cleanup(
        _f: Future,
        *,
        _night_key: Tuple[int, int] = night_key,
        _turn_key: Optional[Tuple[int, int]] = (id(write_queue), ctid) if ctid > 0 else None,
        _fut: Future = fut,
    ) -> None:
        # 摘账前观测终态：末轮失败若先摘空，join 会直接 True 且无人读异常。
        _observe_finished_future(
            _f,
            where="audience translation cleanup",
            night_key=_night_key,
            turn_key=_turn_key,
        )
        with _night_inflight_guard:
            if _turn_key is not None and _turn_future.get(_turn_key) is _fut:
                _turn_future.pop(_turn_key, None)
            if _night_tail.get(_night_key) is _fut:
                _night_tail.pop(_night_key, None)
        write_queue.complete(ticket)

    def _bridge_work(
        work: Future,
        *,
        _out: Future = fut,
    ) -> None:
        # _out 已 set_running；终态只能 set_result / set_exception。
        try:
            if work.cancelled():
                raise CancelledError()
            exc = work.exception()
            if exc is not None:
                _out.set_exception(exc)
            else:
                _out.set_result(work.result())
        except Exception as exc:
            if not _out.done():
                _out.set_exception(exc)

    def _launch_after_pred(
        pred_fut: Future,
        *,
        _out: Future = fut,
        _night_key: Tuple[int, int] = night_key,
    ) -> None:
        _observe_predecessor(pred_fut)
        if _out.done():
            return
        # 占位 Future：submit 前标 RUNNING，避免 cancel 成功摘账而实活仍在跑。
        if not _out.set_running_or_notify_cancel():
            return
        try:
            work = _executor.submit(_run_job)
        except Exception as exc:
            _out.set_exception(exc)
            return
        work.add_done_callback(_bridge_work)

    if chain_pred is not None:
        chain_pred.add_done_callback(_launch_after_pred)
    fut.add_done_callback(_cleanup)
    return fut


def _load_emperor_message_for_turn(
    db: Any, chat_turn_id: int, write_gate: Any,
) -> str:
    """读源轮皇帝原话。查询成功且缺行 → 空串；SQL/连接/Row 形状异常响亮上抛。"""
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "conn"):
        return ""
    with _translation_write_cm(write_gate):
        trow = db.conn.execute(
            "SELECT user_message_id FROM chat_turns WHERE id=?", (ctid,),
        ).fetchone()
        if trow is None:
            return ""
        uid = trow["user_message_id"]
        if not uid:
            return ""
        mrow = db.conn.execute(
            "SELECT content FROM chat_messages WHERE id=?",
            (int(uid),),
        ).fetchone()
        if mrow is None:
            return ""
        return str(mrow["content"] or "")


def catch_up_pending_translations(
    db: Any,
    state: Any,
    *,
    night_id: Optional[int] = None,
    chat_turn_id: Optional[int] = None,
    llm_config: Any = None,
    translate_fn: Optional[TranslateFn] = None,
    write_gate: Any = None,
    write_queue: Any = None,
    within_barrier: bool = False,
    source: Provenance = Provenance.system_simulation,
) -> Dict[str, int]:
    """补跑转译待补：已持久化回话但 extract_status 未 done 的轮，按夜序串行重试。

    可按 night_id / chat_turn_id 收窄（源轮重试入口复用本函数，不复用已退役故事抽取）。
    单轮转译/落账失败保持 pending、继续后续轮；源轮查询等代码异常按 ADR 0005 上抛，
    不洗成空原话继续转译。
    """
    rows = list_pending_translations(
        db, night_id=night_id, chat_turn_id=chat_turn_id,
    )
    extracted = 0
    pending = 0
    scanned = 0
    for row in rows:
        scanned += 1
        ctid = int(row.get("chat_turn_id") or 0)
        nid = int(row.get("night_id") or 0)
        reply = str(row.get("reply") or "")
        # 查询异常在 schedule 外上抛——不得被单轮失败宽吞洗成空输入。
        emperor = _load_emperor_message_for_turn(db, ctid, write_gate)
        if within_barrier:
            # 过月已由 SessionWriteQueue 屏障独占准入；此时再领后序票
            # 并等 Future 会被当前屏障拦住自等。复用同一翻译作业同步
            # 完成，写入生命期由已开的唯一屏障票覆盖。
            try:
                run_turn_translation_job(
                    db, state,
                    emperor_message=emperor,
                    reply=reply,
                    night_id=nid,
                    chat_turn_id=ctid,
                    minister_name=str(row.get("minister_name") or ""),
                    llm_config=llm_config,
                    translate_fn=translate_fn,
                    write_gate=write_gate,
                    source=source,
                )
                extracted += 1
            except Exception:
                logger.exception(
                    "catch_up_pending_translations: turn failed night=%s chat_turn_id=%s",
                    nid, ctid,
                )
                pending += 1
            continue
        # 普通补跑复用同夜 Future FIFO 单真源。
        with _night_inflight_guard:
            existing = _turn_future.get((id(write_queue), ctid)) if ctid > 0 else None
            # Future 先标记终态、再同步执行 cleanup callback。终态旧账即使
            # 尚未从 ledger 摘除，也不是本次 catch-up，不得复用。
            if existing is not None and existing.done():
                existing = None
        fut = existing if existing is not None else schedule_audience_turn_translation(
            db, state,
            emperor_message=emperor,
            reply=reply,
            night_id=nid,
            chat_turn_id=ctid,
            llm_config=llm_config,
            translate_fn=translate_fn,
            write_gate=write_gate,
            write_queue=write_queue,
            source=source,
        )
        try:
            fut.result()
            extracted += 1
        except Exception:
            logger.exception(
                "catch_up_pending_translations: turn failed night=%s chat_turn_id=%s",
                nid, ctid,
            )
            pending += 1
    return {"extracted": extracted, "pending": pending, "scanned": scanned}
