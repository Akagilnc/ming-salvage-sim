"""召对转译场中承接与后台调度（C1b #1838；T2 #1842）。

同步落账核：声明已到手后，接到既有分派器（分段/可闻性/在场/主角/边事件/
公开说法及 C0 其余 section），源轮绑定、主角持久化、抽取/判官水位推进——
故事抽取、边事件判官、代码触发读心不再另起（ADR 0155 场中承接段）。

后台调度（#1842）：每轮回话后按轮串行起转译，前台不等；封夜提交 join
本 owner×夜最后一轮；耗尽标 extract_status=pending（待补），不挡下一句；
过月前 join 本会话 owner。水位复用 chat_turns.extract_status（与旧抽取
同一真源，转译承接后标 done，收夜不再跑故事抽取）。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ming_sim.applier import Provenance, atomic
from ming_sim.audience_night import set_night_protagonist
from ming_sim.declaration_dispatch import (
    DeclarationDispatchResult,
    dispatch_declaration,
)

TranslateFn = Callable[[str, Any], Mapping[str, object]]

# 进程级：按「会话 owner × 夜」串行与登记（同一夜 FIFO）；跨夜 / 跨会话可并行。
# owner = id(write_gate) 或 id(db)：锁、inflight、join、清理共用同一 (owner, night)
# 边界——独立存档同夜号不得互等；关库后旧会话 worker 不得占住新会话同夜串行锁，
# 也不得继续出现在本 owner 的 join 账上（xdist 复用进程 / 菜单退局后的孤儿 Future）。
# 源轮 Future 按 (owner, chat_turn_id) 索引——跨存档同号轮次不得覆盖/撤错
# （ADR 0038 / 0155）。
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="audience-translate")
_night_serial_guard = threading.Lock()
_night_serial_locks: Dict[Tuple[int, int], threading.Lock] = {}
_night_inflight_guard = threading.Lock()
_night_inflight: Dict[Tuple[int, int], List[Future]] = {}  # (owner, night_id)
_turn_inflight: Dict[Tuple[int, int], Future] = {}  # (owner, chat_turn_id)
# 同夜显式 FIFO 链：不依赖 Lock 争用顺序；tail Future 按 (owner, night) 串起后继。
_night_tail: Dict[Tuple[int, int], Future] = {}


def translation_owner_key(write_gate: Any = None, db: Any = None) -> int:
    """转译 inflight / 夜串行锁的会话锚：优先 write_gate，否则 db。"""
    if write_gate is not None:
        return id(write_gate)
    if db is not None:
        return id(db)
    return 0


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
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done', relation_judge_status='done' "
        "WHERE id=? AND status NOT IN ('failed','undone')",
        (int(chat_turn_id),),
    )


def _night_lock(night_id: int, *, owner_key: int = 0) -> threading.Lock:
    nid = int(night_id or 0)
    key = (int(owner_key), nid)
    with _night_serial_guard:
        lock = _night_serial_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _night_serial_locks[key] = lock
        return lock


def cancel_turn_translation(chat_turn_id: int, *, owner_key: int) -> int:
    """撤回本轮：取消/失效该会话 owner 下该源轮在飞转译 Future（ADR 0038 / 0155）。

    必须传当前会话 ``owner_key``——跨存档同号 ``chat_turn_id`` 不得撤到别家。
    返回触及的 Future 数（0/1）。已跑到 write-gate 落账前的 worker 仍靠源轮
    存活复查挡写；pending/retry 真源随 chat_turns.status=undone 自然出窗。
    """
    ctid = int(chat_turn_id or 0)
    owner = int(owner_key)
    if ctid <= 0:
        return 0
    turn_key = (owner, ctid)
    with _night_inflight_guard:
        fut = _turn_inflight.pop(turn_key, None)
        if fut is None:
            return 0
        for key, bucket in list(_night_inflight.items()):
            if key[0] != owner:
                continue
            try:
                bucket.remove(fut)
            except ValueError:
                continue
            if not bucket:
                _night_inflight.pop(key, None)
            break
    fut.cancel()
    return 1


def abandon_owner_translations(owner_key: int) -> int:
    """会话关库/退局：从 join 账上剥离该 owner 的在飞 Future，并 best-effort cancel。

    已在跑的 worker 不能靠 Future.cancel 打断；剥离后本 owner 的
    ``join_owner_translations`` / ``join_night_translations`` 不再被孤儿挂死。
    worker 若仍持旧 write_gate，落账前复查 / 闭库写失败会自行收口
    （done callback 对已剥离项是 no-op）。返回剥离数。
    """
    owner = int(owner_key)
    doomed: List[Future] = []
    with _night_inflight_guard:
        for key, bucket in list(_night_inflight.items()):
            if key[0] != owner:
                continue
            doomed.extend(bucket)
            _night_inflight.pop(key, None)
        for turn_key in list(_turn_inflight.keys()):
            if turn_key[0] == owner:
                _turn_inflight.pop(turn_key, None)
        for night_key in list(_night_tail.keys()):
            if night_key[0] == owner:
                _night_tail.pop(night_key, None)
    for fut in doomed:
        fut.cancel()
    return len(doomed)


def join_owner_translations(owner_key: int, *, timeout_s: float = 120.0) -> bool:
    """等待该会话 owner 名下在飞转译全部结束。返回是否在时限内清空。"""
    import time

    owner = int(owner_key)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        with _night_inflight_guard:
            bucket = [
                fut
                for key, futs in _night_inflight.items()
                if key[0] == owner
                for fut in futs
            ]
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


def _mark_translation_pending(db: Any, chat_turn_id: int, write_gate: Any) -> None:
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "mark_story_extraction_pending"):
        return
    gate = write_gate if write_gate is not None else threading.Lock()
    with gate:
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
    source: Provenance = Provenance.system_simulation,
) -> Future:
    """后台调度本轮转译：立即返回 Future；同夜按轮串行（显式 Future 链 FIFO）。"""
    nid = int(night_id or 0)
    ctid = int(chat_turn_id or 0)
    owner = translation_owner_key(write_gate, db)
    if ctid > 0 and hasattr(db, "mark_story_extraction_pending"):
        gate = write_gate if write_gate is not None else threading.Lock()
        with gate:
            db.mark_story_extraction_pending(ctid)

    serial = _night_lock(nid, owner_key=owner)
    night_key = (owner, nid)
    # 前驱在临界区写入 pred_holder；worker 启动后读同一格，保证与 tail 登记同序。
    pred_holder: List[Optional[Future]] = [None]

    def _worker() -> DeclarationDispatchResult:
        pred = pred_holder[0]
        if pred is not None:
            try:
                pred.result()
            except Exception:
                pass
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

    # 读前驱 + submit + 写 tail + inflight 登记同持非重入锁；done callback 锁外挂
    # （已完成 Future 会同步回调，持锁再挂会死锁）。
    with _night_inflight_guard:
        pred_holder[0] = _night_tail.get(night_key)
        fut = _executor.submit(_worker)
        _night_tail[night_key] = fut
        _night_inflight.setdefault(night_key, []).append(fut)
        if ctid > 0:
            _turn_inflight[(owner, ctid)] = fut

    def _cleanup(
        _f: Future,
        *,
        _night_key: Tuple[int, int] = night_key,
        _turn_key: Optional[Tuple[int, int]] = (owner, ctid) if ctid > 0 else None,
        _fut: Future = fut,
    ) -> None:
        with _night_inflight_guard:
            bucket = _night_inflight.get(_night_key) or []
            try:
                bucket.remove(_fut)
            except ValueError:
                pass
            if not bucket:
                _night_inflight.pop(_night_key, None)
            if _turn_key is not None and _turn_inflight.get(_turn_key) is _fut:
                _turn_inflight.pop(_turn_key, None)
            if _night_tail.get(_night_key) is _fut:
                _night_tail.pop(_night_key, None)

    fut.add_done_callback(_cleanup)
    return fut


def join_night_translations(
    night_id: int,
    *,
    timeout_s: float = 120.0,
    owner_key: Optional[int] = None,
) -> bool:
    """等待本夜在飞转译清空。返回是否在时限内清空。

    ``owner_key`` 显式传入时只等该会话（生产封夜/恢复口）；``None`` 时等该夜
    全部 owner（单会话测试清理便利，不得用于生产过月——过月走
    :func:`join_owner_translations`）。
    """
    import time

    nid = int(night_id or 0)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        with _night_inflight_guard:
            if owner_key is None:
                bucket = [
                    fut
                    for key, futs in _night_inflight.items()
                    if key[1] == nid
                    for fut in futs
                ]
            else:
                bucket = list(_night_inflight.get((int(owner_key), nid)) or ())
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
    """测试/进程清理用：等全部 owner×夜在飞转译。生产过月走 join_owner_translations。"""
    import time

    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        with _night_inflight_guard:
            keys = list(_night_inflight.keys())
        if not keys:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        for owner, nid in keys:
            ok = join_night_translations(
                nid, timeout_s=remaining, owner_key=owner,
            )
            if not ok:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False


def _load_emperor_message_for_turn(
    db: Any, chat_turn_id: int, write_gate: Any,
) -> str:
    """读源轮皇帝原话。查询成功且缺行 → 空串；SQL/连接/Row 形状异常响亮上抛。"""
    ctid = int(chat_turn_id or 0)
    if ctid <= 0 or not hasattr(db, "conn"):
        return ""
    gate = write_gate if write_gate is not None else threading.Lock()
    with gate:
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
        # 查询异常在 job try 外上抛——不得被单轮失败宽吞洗成空输入。
        emperor = _load_emperor_message_for_turn(db, ctid, write_gate)
        owner = translation_owner_key(write_gate, db)
        serial = _night_lock(nid, owner_key=owner)
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
