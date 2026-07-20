"""召对夜容器与故事账本地基（#498 / ADR 0035）。

公开 seam：开夜 → 宣人入殿账 → 对话轮锚定 → 收夜；按夜取账/对话；
廉价死账校验；常在员额动态解析；夜×结算顺势收夜；收夜提交幂等游标；
在飞回话 fail-closed。

口令账标签由本模块引擎常量写入——确定性写读，restore 不解析自由文本。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from ming_sim.error_pack import error_packs_root
from ming_sim.mindreading import is_inner_court_attendant
from ming_sim.models import GameState

# ── 引擎侧口令标签常量（ADR 0035：确定性写读）──────────────────────────
TAG_OPEN_NIGHT = "开夜"
TAG_ENTER = "入殿"
TAG_CLOSE_NIGHT = "收夜"
TAG_STANDING_ROSTER = "常在员额"
TAG_AUTO_CLOSE = "顺势收夜"
TAG_MINGFA = "明发"  # 夜内定案的旨在公开层账上标已明发（#502 AC6，供 #459 扩散）
_MINGFA_ID_PREFIX = "明发#"  # 明发账挂 directive_id 的结构化标（逐条幂等续跑，#502 L6）
# 进出账（ADR 0035：TAG_ENTER/TAG_EXIT 是机器承重的在场效果标识「进/出」）
TAG_EXIT = "告退"          # 出：离场；确定性「令 X 退下」口令落此账
TAG_IN_TRANSIT = "传召在途"  # 账在人不在场：传召已发、人在途（不落在场效果）

METHOD_XUANRU = "宣入"
METHOD_CHUANZHAO = "传召"
METHOD_YUECI = "越次"
SUMMON_METHODS = frozenset({METHOD_XUANRU, METHOD_CHUANZHAO, METHOD_YUECI})

AUDIBILITY_PUBLIC = "殿上公开"
AUDIBILITY_PRIVATE = "御前低语"

# #501 机器可读在场效果（ADR 0035 线上 R2）：在场是机器承重态，其输入不靠解析自由文本。
PRESENCE_ENTER = "enter"
PRESENCE_EXIT = "exit"
PRESENCE_NONE = ""
PRESENCE_EFFECTS = frozenset({PRESENCE_NONE, PRESENCE_ENTER, PRESENCE_EXIT})

NIGHT_STATUS_OPEN = "open"
NIGHT_STATUS_CLOSING = "closing"
NIGHT_STATUS_CLOSED = "closed"

CLOSE_STEP_COMMIT_OFFICE = 1
CLOSE_STEP_TRANSFER_CANDIDATES = 2
CLOSE_STEP_FINALIZE = 3
CLOSE_STEPS = (
    CLOSE_STEP_COMMIT_OFFICE,
    CLOSE_STEP_TRANSFER_CANDIDATES,
    CLOSE_STEP_FINALIZE,
)

# 在飞回话：公开入口可达的有界等待（秒）。挂起/超时 fail-closed。
DEFAULT_IN_FLIGHT_WAIT_S = 30.0
DEFAULT_IN_FLIGHT_POLL_S = 0.05

# 收夜提交的 night-domain kinds（密令应允即落地，不进收夜提交）
_CLOSE_COMMIT_KINDS_OFFICE = frozenset({"office", "consort"})
_CLOSE_COMMIT_KINDS_DIRECTIVE = frozenset({"directive"})


class AudienceNightError(Exception):
    """召对夜域响亮失败（死账 / 在飞 / 坏输入 / 提交失败）。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        error_pack_path: str | None = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.error_pack_path = error_pack_path
        self.detail = detail or {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _row_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _should_commit(db: Any) -> bool:
    """本域多语句写各自开隐式事务，故用 owns_transaction() 会因自身 in_transaction 恒 False
    而永不 durable commit（跨进程恢复丢失）。改与 db.py 同 idiom：仅当外层无显式 atomic/
    suspend 持有事务时才提交（用 _commit_suspended / _atomic_depth 判据，不看 in_transaction）。"""
    conn = getattr(db, "conn", None)
    if conn is None:
        return True
    return (
        not bool(getattr(conn, "_commit_suspended", False))
        and int(getattr(conn, "_atomic_depth", 0) or 0) == 0
    )


def _commit_if_owns(db: Any) -> None:
    if _should_commit(db):
        db.conn.commit()


def write_audience_error_pack(
    *,
    kind: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> str:
    """落一份夜域错误包到 user-data error_packs（响亮、可发包）。"""
    root = error_packs_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pack_dir = root / f"audience_{kind}_{stamp}"
    suffix = 0
    while pack_dir.exists():
        suffix += 1
        pack_dir = root / f"audience_{kind}_{stamp}_{suffix}"
    pack_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "kind": kind,
        "message": message,
        "detail": detail or {},
        "written_at": _now_iso(),
    }
    (pack_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (pack_dir / "message.txt").write_text(message + "\n", encoding="utf-8")
    return str(pack_dir.resolve())


def resolve_standing_roster(db: Any) -> List[str]:
    """开夜时动态解析常在员额：在职且 active 的御前近臣槽位持有者。"""
    if not hasattr(db, "conn"):
        return []
    rows = db.conn.execute(
        "SELECT name, office, office_type, status FROM characters "
        "WHERE status = 'active' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows if is_inner_court_attendant(row)]


def get_open_night(db: Any) -> Optional[Dict[str, Any]]:
    row = db.conn.execute(
        "SELECT * FROM audience_nights "
        "WHERE status IN (?, ?) ORDER BY id DESC LIMIT 1",
        (NIGHT_STATUS_OPEN, NIGHT_STATUS_CLOSING),
    ).fetchone()
    return _hydrate_night(_row_dict(row)) if row is not None else None


def get_night(db: Any, night_id: int) -> Optional[Dict[str, Any]]:
    row = db.conn.execute(
        "SELECT * FROM audience_nights WHERE id = ?",
        (int(night_id),),
    ).fetchone()
    return _hydrate_night(_row_dict(row)) if row is not None else None


def _hydrate_night(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not raw:
        return raw
    return {
        "id": int(raw["id"]),
        "turn": int(raw["turn"]),
        "year": int(raw["year"]),
        "period": int(raw["period"]),
        "time_of_day": str(raw.get("time_of_day") or ""),
        "location": str(raw.get("location") or ""),
        "status": str(raw.get("status") or ""),
        "close_commit_cursor": int(raw.get("close_commit_cursor") or 0),
        "next_event_seq": int(raw.get("next_event_seq") or 0),
        "opened_at": raw.get("opened_at"),
        "closed_at": raw.get("closed_at"),
    }


def _entry_order_key(raw: Dict[str, Any]) -> float:
    """时序排序键：抽取账绑源对话轮原始时序（order_key），口令账回退自身 seq。"""
    ok = raw.get("order_key")
    if ok is None:
        return float(int(raw.get("seq") or 0))
    return float(ok)


def list_ledger(db: Any, night_id: int) -> List[Dict[str, Any]]:
    # 时序键排序（#501 AC11）：COALESCE(order_key, seq) 使补跑的抽取账落回源轮原位、
    # 不因补跑执行时刻排到后续轮之后；同键内 id 稳定次序。
    rows = db.conn.execute(
        "SELECT * FROM story_ledger_entries WHERE night_id = ? "
        "ORDER BY COALESCE(order_key, seq) ASC, id ASC",
        (int(night_id),),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw = _row_dict(row)
        ok = raw.get("order_key")
        out.append({
            "id": int(raw["id"]),
            "night_id": int(raw["night_id"]),
            "seq": int(raw["seq"]),
            "order_key": None if ok is None else float(ok),
            "person_names": [str(n) for n in _json_list(raw.get("person_names"))],
            "audibility": str(raw.get("audibility") or AUDIBILITY_PUBLIC),
            "body": str(raw.get("body") or ""),
            "tags": [str(t) for t in _json_list(raw.get("tags"))],
            "source_chat_turn_id": int(raw.get("source_chat_turn_id") or 0),
            "presence_effect": str(raw.get("presence_effect") or ""),
            "created_at": raw.get("created_at"),
            "kind": "ledger",
        })
    return out


def list_chat_turns_for_night(db: Any, night_id: int) -> List[Dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT * FROM chat_turns WHERE night_id = ? ORDER BY night_seq ASC, id ASC",
        (int(night_id),),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def list_night_timeline(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """账本 + 对话轮按 night_seq/seq 合流（AC4 时序对齐真源）。"""
    events: List[Dict[str, Any]] = []
    for e in list_ledger(db, night_id):
        # 抽取账用 order_key（源轮时序）排序；口令/框架账回退 seq。
        events.append({
            "kind": "ledger",
            "seq": _entry_order_key(e),
            "payload": e,
        })
    for t in list_chat_turns_for_night(db, night_id):
        events.append({
            "kind": "chat_turn",
            "seq": float(int(t.get("night_seq") or 0)),
            "payload": t,
        })
    events.sort(key=lambda x: (float(x["seq"]), 0 if x["kind"] == "ledger" else 1, int(x["payload"].get("id") or 0)))
    return events


def _allocate_seq(db: Any, night_id: int) -> int:
    if hasattr(db, "allocate_night_seq"):
        return int(db.allocate_night_seq(int(night_id)))
    row = db.conn.execute(
        "SELECT next_event_seq FROM audience_nights WHERE id = ?",
        (int(night_id),),
    ).fetchone()
    if row is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    nxt = int(row["next_event_seq"] or 0) + 1
    db.conn.execute(
        "UPDATE audience_nights SET next_event_seq = ? WHERE id = ?",
        (nxt, int(night_id)),
    )
    return nxt


def _character_status(db: Any, name: str) -> str:
    if hasattr(db, "get_character_status"):
        status, _reason = db.get_character_status(name)
        return str(status or "")
    row = db.conn.execute(
        "SELECT status FROM characters WHERE name = ?", (name,)
    ).fetchone()
    return str(row["status"]) if row is not None else ""


def assert_persons_not_dead(
    db: Any,
    names: Sequence[str],
    *,
    context: str = "在场",
) -> None:
    dead: List[str] = []
    for name in names:
        n = str(name or "").strip()
        if not n:
            continue
        if _character_status(db, n) == "dead":
            dead.append(n)
    if not dead:
        return
    message = f"死账校验失败：已殁者不可{context}：{('、'.join(dead))}"
    pack = write_audience_error_pack(
        kind="dead_present",
        message=message,
        detail={"dead": dead, "context": context},
    )
    raise AudienceNightError(
        message, code="dead_present", error_pack_path=pack,
        detail={"dead": dead, "context": context},
    )


def append_ledger_entry(
    db: Any,
    night_id: int,
    *,
    person_names: Optional[Sequence[str]] = None,
    audibility: str = AUDIBILITY_PUBLIC,
    body: str = "",
    tags: Optional[Sequence[str]] = None,
    check_dead: bool = True,
    commit: bool = True,
    source_chat_turn_id: int = 0,
    presence_effect: str = "",
    order_key: Optional[float] = None,
) -> int:
    """追加一条故事账。commit=False 时由外层事务统一提交（开夜原子）。

    抽取账（#501）额外带溯源 `source_chat_turn_id`、机器可读 `presence_effect`
    （''/enter/exit）与时序键 `order_key`（绑定源对话轮原始时序，补跑落回原位）；
    口令/框架账三者取默认（0/''/NULL），读取端 order_key 缺省 COALESCE 回退 seq。
    """
    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    if night["status"] == NIGHT_STATUS_CLOSED:
        raise AudienceNightError(
            f"夜已收，不能再落账：{night_id}", code="night_closed",
        )
    persons = [str(n).strip() for n in (person_names or []) if str(n).strip()]
    if check_dead and persons:
        assert_persons_not_dead(db, persons)
    if audibility not in {AUDIBILITY_PUBLIC, AUDIBILITY_PRIVATE}:
        raise AudienceNightError(
            f"可闻性非法：{audibility!r}", code="bad_audibility",
        )
    if presence_effect not in PRESENCE_EFFECTS:
        raise AudienceNightError(
            f"在场效果非法：{presence_effect!r}", code="bad_presence_effect",
        )
    tag_list = [str(t) for t in (tags or []) if str(t)]
    seq = _allocate_seq(db, night_id)
    cur = db.conn.execute(
        """
        INSERT INTO story_ledger_entries
            (night_id, seq, person_names, audibility, body, tags,
             source_chat_turn_id, presence_effect, order_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(night_id),
            seq,
            json.dumps(persons, ensure_ascii=False),
            audibility,
            body or "",
            json.dumps(tag_list, ensure_ascii=False),
            int(source_chat_turn_id or 0),
            presence_effect or "",
            None if order_key is None else float(order_key),
        ),
    )
    if commit and _should_commit(db):
        db.conn.commit()
    return int(cur.lastrowid)


def open_night(
    db: Any,
    state: GameState,
    *,
    time_of_day: str = "",
    location: str = "",
    body: str = "",
) -> Dict[str, Any]:
    """开夜：夜实体 + 开夜账 + 常在员额入殿账，单事务全有或全无。"""
    existing = get_open_night(db)
    if existing is not None and existing["status"] == NIGHT_STATUS_OPEN:
        return existing
    if existing is not None and existing["status"] == NIGHT_STATUS_CLOSING:
        # 上一夜收夜中断（closing）。不在此隐式续收：open_night 无 content/registry，
        # 隐式 close_night 会让缺依赖的已应允任免 terminal failed、夜仍被封=丢合法任免。
        # 响亮停住——续收必须走携 content/registry 的显式 close/resume（resolve_turn/advance/
        # auto_close_open_night），不准开新夜、不准封夜。
        raise AudienceNightError(
            f"上一夜收夜未完（closing），须先携 content/registry 显式续收再开新夜：{int(existing['id'])}",
            code="night_closing_incomplete",
            detail={"night_id": int(existing["id"])},
        )

    roster = resolve_standing_roster(db)
    open_body = body or (
        f"{location or '便殿'}·{time_of_day or '此时'}，召对夜启。"
    )

    # 原子：实体 + 开夜账 + 员额入殿账，SAVEPOINT 全有或全无。
    # 不 BEGIN 顶层事务（避免嵌套/泄漏；外层 atomic 可组合）。
    sp = f"open_night_{int(state.turn)}_{id(state)}"
    db.conn.execute(f"SAVEPOINT {sp}")
    try:
        cur = db.conn.execute(
            """
            INSERT INTO audience_nights
                (turn, year, period, time_of_day, location, status,
                 close_commit_cursor, next_event_seq)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                int(state.turn),
                int(state.year),
                int(state.period),
                time_of_day or "",
                location or "",
                NIGHT_STATUS_OPEN,
            ),
        )
        night_id = int(cur.lastrowid)
        append_ledger_entry(
            db, night_id,
            person_names=[],
            audibility=AUDIBILITY_PUBLIC,
            body=open_body,
            tags=[TAG_OPEN_NIGHT],
            check_dead=False,
            commit=False,
        )
        for name in roster:
            append_ledger_entry(
                db, night_id,
                person_names=[name],
                audibility=AUDIBILITY_PUBLIC,
                body=f"{name}随侍在侧。",
                tags=[TAG_ENTER, TAG_STANDING_ROSTER],
                check_dead=True,
                commit=False,
            )
        db.conn.execute(f"RELEASE SAVEPOINT {sp}")
        # 非外层 atomic 时提交本夜写入（不用 owns_transaction：in_transaction 时它恒 False）
        if _should_commit(db):
            db.conn.commit()
    except Exception:
        try:
            db.conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            db.conn.execute(f"RELEASE SAVEPOINT {sp}")
        except Exception:
            pass
        raise

    night = get_night(db, night_id)
    assert night is not None
    return night


def _validate_summon_method(method: str, *, default: str) -> str:
    """校验召法白名单（summon_enter / record_summon_in_transit 共用单一真源）。"""
    m = str(method or default).strip()
    if m not in SUMMON_METHODS:
        raise AudienceNightError(
            f"召法非法：{m!r}（须为 {'/'.join(sorted(SUMMON_METHODS))}）",
            code="bad_summon_method",
        )
    return m


def summon_enter(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_XUANRU,
    body: str = "",
    audibility: str = AUDIBILITY_PUBLIC,
) -> int:
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    method = _validate_summon_method(method, default=METHOD_XUANRU)
    text = body or f"{method}{name}入殿。"
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=audibility,
        body=text,
        tags=[TAG_ENTER, method],
        check_dead=True,
    )


def list_in_flight_chat_turns(db: Any, night_id: int) -> List[Dict[str, Any]]:
    if hasattr(db, "list_in_flight_chat_turns"):
        return db.list_in_flight_chat_turns(night_id=int(night_id))
    rows = db.conn.execute(
        """
        SELECT * FROM chat_turns
        WHERE night_id = ?
          AND (
            status = 'generating'
            OR (status = 'active' AND (minister_message_id IS NULL OR minister_message_id = 0))
          )
        ORDER BY id ASC
        """,
        (int(night_id),),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def wait_in_flight_clear(
    db: Any,
    night_id: int,
    *,
    timeout_s: float | None = None,
    poll_s: float | None = None,
) -> None:
    """等在飞回话完成；超时 fail-closed（夜保持开）。不持 write_gate。"""
    if timeout_s is None:
        timeout_s = DEFAULT_IN_FLIGHT_WAIT_S
    if poll_s is None:
        poll_s = DEFAULT_IN_FLIGHT_POLL_S
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        inflight = list_in_flight_chat_turns(db, night_id)
        if not inflight:
            return
        if time.monotonic() >= deadline:
            ids = [int(r["id"]) for r in inflight]
            message = (
                "收夜中止：本夜仍有未完成回话（在飞/挂起），"
                f"chat_turn_ids={ids}。夜保持开启，可原地重试。"
            )
            pack = write_audience_error_pack(
                kind="in_flight_chat",
                message=message,
                detail={"night_id": int(night_id), "chat_turn_ids": ids},
            )
            raise AudienceNightError(
                message,
                code="in_flight_chat",
                error_pack_path=pack,
                detail={"night_id": int(night_id), "chat_turn_ids": ids},
            )
        time.sleep(max(0.0, float(poll_s)))


def _set_night_fields(db: Any, night_id: int, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [int(night_id)]
    db.conn.execute(
        f"UPDATE audience_nights SET {assignments} WHERE id = ?",
        params,
    )
    _commit_if_owns(db)


def _commit_night_approved(
    db: Any,
    state: GameState,
    night_id: int,
    *,
    kinds: frozenset,
    content: Any,
    registry: Any,
    directive_status: str = "draft",
) -> List[Dict[str, object]]:
    """收夜提交本夜已应允白名单。沿用 commit_pending_actions 既有 terminal 语义：
    落得了标 committed、落不了标 failed（都不留 pending，故幂等、可续跑）；失败由既有
    pending_action_failures 渠道显眼上报，不在此另造「可续跑」的假失败阻断（否则第二次
    只读 pending 会漏交终态 failed）。"""
    if not hasattr(db, "list_night_approved_pending"):
        return []
    rows: List[Dict[str, object]] = []
    for kind in sorted(kinds):
        rows.extend(db.list_night_approved_pending(int(night_id), kind=kind))
    if not rows:
        return []
    action_ids = [int(r["id"]) for r in rows]
    applied = db.commit_pending_actions(
        state,
        content=content,
        registry=registry,
        action_ids=action_ids,
        directive_status=directive_status,
    )
    return list(applied or [])


def _drain_story_extraction_or_fail_closed(
    db: Any, night_id: int, *, llm_config: Any, write_gate: Any,
) -> None:
    """收夜前清空待补抽取（ADR 0036 线上 R3）——引擎侧强制闸，不只挂 web 前门。

    收夜是史实书写边界：带待补账收夜会把过期在场名单写进收尾叙事，补账插回原时序后同一
    时间线自相矛盾。有待补 → 强制同步补跑；仍有 → fail-closed 中止收夜（夜保持开、可重试）。
    无 llm_config/write_gate 又有待补 = 无从清空又不得带待补收夜 → 同样 fail-closed
    （绝不静默跳过史实边界）。无待补则 no-op（无依赖时正常收夜）。测试替身无该接口时跳过。
    """
    if not hasattr(db, "count_pending_story_extractions"):
        return
    pending = int(db.count_pending_story_extractions(night_id=int(night_id)) or 0)
    if pending <= 0:
        return
    if llm_config is None or write_gate is None:
        rows = db.list_unextracted_replies(night_id=int(night_id))
        ids = [int(r.get("chat_turn_id") or 0) for r in rows]
        message = (
            f"收夜中止：本夜仍有 {pending} 条待补抽取，且无 LLM/写锁可清空"
            f"（chat_turn_ids={ids}）。夜保持开启，可原地重试补跑。"
        )
        pack = write_audience_error_pack(
            kind="pending_extraction", message=message,
            detail={"night_id": int(night_id), "chat_turn_ids": ids},
        )
        raise AudienceNightError(
            message, code="pending_extraction", error_pack_path=pack,
            detail={"night_id": int(night_id), "chat_turn_ids": ids},
        )
    from ming_sim.audience_extraction import drain_pending_before_close

    drain_pending_before_close(
        db=db, llm_config=llm_config, write_gate=write_gate, night_id=int(night_id),
    )


def close_night(
    db: Any,
    state: GameState,
    *,
    night_id: Optional[int] = None,
    content: Any = None,
    registry: Any = None,
    auto: bool = False,
    body: str = "",
    wait_timeout_s: float | None = None,
    crash_after_step: Optional[int] = None,
    on_step: Optional[Callable[[int, Dict[str, Any]], None]] = None,
    beat_generator: Any = None,
    knowledge_provider: Any = None,
    llm_config: Any = None,
    write_gate: Any = None,
) -> Dict[str, Any]:
    """收夜：在飞守卫 → 收夜前清空待补抽取（引擎侧史实边界闸）→ 仅本夜已应允提交（游标幂等）
    → 收夜账 → closed。

    beat_generator 注入时（#503 编排）：收夜账正文经编排层路由输入后由内容生成填充；
    不注入（或返空）则沿用 #498 确定性兜底正文。见 beat_orchestration。

    `llm_config`/`write_gate` 供收夜前 drain 用；web 前门已预清（pending=0）时本闸 no-op、
    不重复 drain（也不因此在已持锁的 runtime write_gate 上自锁）。带待补而无依赖 → fail-closed。
    """
    if wait_timeout_s is None:
        wait_timeout_s = DEFAULT_IN_FLIGHT_WAIT_S
    if night_id is None:
        open_n = get_open_night(db)
        if open_n is None:
            return {"closed": False, "reason": "no_open_night"}
        night_id = int(open_n["id"])

    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    if night["status"] == NIGHT_STATUS_CLOSED:
        return {"closed": True, "night_id": int(night_id), "already": True}

    if night["status"] == NIGHT_STATUS_OPEN:
        wait_in_flight_clear(db, night_id, timeout_s=wait_timeout_s)
        # 史实书写边界：收夜前强制清空待补抽取（fail-closed），先于任何收夜写。
        _drain_story_extraction_or_fail_closed(
            db, int(night_id), llm_config=llm_config, write_gate=write_gate,
        )
        _set_night_fields(db, night_id, status=NIGHT_STATUS_CLOSING)
        night = get_night(db, night_id)
        assert night is not None

    cursor = int(night["close_commit_cursor"] or 0)

    def _advance(step: int) -> None:
        nonlocal cursor
        _set_night_fields(db, night_id, close_commit_cursor=int(step))
        cursor = int(step)
        if on_step is not None:
            on_step(step, get_night(db, night_id) or {})
        if crash_after_step is not None and int(crash_after_step) == int(step):
            raise AudienceNightError(
                f"收夜提交崩溃注入：step={step}",
                code="close_crash",
                detail={"night_id": int(night_id), "step": int(step)},
            )

    if cursor < CLOSE_STEP_COMMIT_OFFICE:
        _commit_night_approved(
            db, state, int(night_id),
            kinds=_CLOSE_COMMIT_KINDS_OFFICE,
            content=content, registry=registry,
        )
        _advance(CLOSE_STEP_COMMIT_OFFICE)

    if cursor < CLOSE_STEP_TRANSFER_CANDIDATES:
        _commit_night_approved(
            db, state, int(night_id),
            kinds=_CLOSE_COMMIT_KINDS_DIRECTIVE,
            content=content, registry=registry,
            directive_status="draft",
        )
        # 夜内定案的旨落公开层账、标已明发（#502 AC6，供 #459 扩散）——每道一条，
        # 机器辨识经 pending_actions↔turn_directives 关联（list_night_promulgated_directives），
        # 账本正文只作叙事呈现、不被解析。密令私密，不入明发。
        # 幂等按 directive_id 逐条（#502 L6）：半写后续跑只补缺的那几道、不漏不重——
        # 不用「整夜已有任意明发标」一门（那会在半写后跳过剩余道，公开账残缺）。
        if hasattr(db, "list_night_promulgated_directives"):
            already_ids = {
                str(t)[len(_MINGFA_ID_PREFIX):]
                for e in list_ledger(db, night_id) for t in e.get("tags") or []
                if str(t).startswith(_MINGFA_ID_PREFIX)
            }
            for _pd in db.list_night_promulgated_directives(int(night_id)):
                _did = str(int(_pd.get("directive_id") or 0))
                if _did in already_ids:
                    continue
                append_ledger_entry(
                    db, night_id,
                    person_names=[str(_pd.get("actor") or "")] if _pd.get("actor") else [],
                    audibility=AUDIBILITY_PUBLIC,
                    body=f"明发旨意：{str(_pd.get('text') or '')}",
                    tags=[TAG_MINGFA, f"{_MINGFA_ID_PREFIX}{_did}"],
                    check_dead=False,
                )
        _advance(CLOSE_STEP_TRANSFER_CANDIDATES)

    if cursor < CLOSE_STEP_FINALIZE:
        tags = [TAG_CLOSE_NIGHT]
        if auto:
            tags.append(TAG_AUTO_CLOSE)
        # 收夜账幂等只看口令账的确定性收夜标——抽取账开放 tags 里的「收夜」不算数
        # （否则 LLM 叙事标签旁路收夜账、夜 closed 却无退朝账）。
        existing_tags = {
            t for e in list_ledger(db, night_id) if _is_command_entry(e)
            for t in e.get("tags") or []
        }
        if TAG_CLOSE_NIGHT not in existing_tags:
            # 收夜账正文只在真要落且无显式正文时才生成——避免为已落账/已给 body 的
            # 幂等续跑白跑贵 LLM（P5）。
            generated_close = ""
            if not body and beat_generator is not None:
                from ming_sim import beat_orchestration as beats

                generated_close = beats.generate_close_beat_body(
                    db, state, night=night,
                    beat_generator=beat_generator, knowledge_provider=knowledge_provider,
                )
            close_body = body or generated_close or (
                "王承恩代宣退朝，今夜召对到此。" if auto else "退朝，今夜召对到此。"
            )
            append_ledger_entry(
                db, night_id,
                person_names=[],
                audibility=AUDIBILITY_PUBLIC,
                body=close_body,
                tags=tags,
                check_dead=False,
            )
        _set_night_fields(
            db, night_id,
            status=NIGHT_STATUS_CLOSED,
            closed_at=_now_iso(),
            close_commit_cursor=CLOSE_STEP_FINALIZE,
        )

    final = get_night(db, night_id)
    return {
        "closed": True,
        "night_id": int(night_id),
        "already": False,
        "night": final,
        "auto": bool(auto),
    }


def auto_close_open_night(
    db: Any,
    state: GameState,
    *,
    content: Any = None,
    registry: Any = None,
    wait_timeout_s: float | None = None,
    crash_after_step: Optional[int] = None,
    beat_generator: Any = None,
    knowledge_provider: Any = None,
    llm_config: Any = None,
    write_gate: Any = None,
) -> Optional[Dict[str, Any]]:
    """颁诏/过回合前：有开夜则顺势收夜；无开夜返回 None。

    `llm_config`/`write_gate` 透传给收夜前 drain 闸；web 结算路已在前门预清待补，故此处
    多数为 no-op（pending=0），无依赖也不会误 fail-closed。"""
    open_n = get_open_night(db)
    if open_n is None:
        return None
    return close_night(
        db, state,
        night_id=int(open_n["id"]),
        content=content,
        registry=registry,
        auto=True,
        wait_timeout_s=wait_timeout_s,
        crash_after_step=crash_after_step,
        beat_generator=beat_generator,
        knowledge_provider=knowledge_provider,
        llm_config=llm_config,
        write_gate=write_gate,
    )


def ensure_open_night_for_audience(
    db: Any,
    state: GameState,
    *,
    time_of_day: str = "",
    location: str = "",
    body: str = "",
) -> Dict[str, Any]:
    return open_night(db, state, time_of_day=time_of_day, location=location, body=body)


def record_summon_in_transit(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_CHUANZHAO,
    body: str = "",
) -> int:
    """落传召在途账：账在人不在场——传召已发、人在途，不落在场效果。"""
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("传召人名不能为空", code="empty_person")
    method = _validate_summon_method(method, default=METHOD_CHUANZHAO)
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body=body or f"传召{name}，在途未至。",
        tags=[TAG_IN_TRANSIT, method],
    )


def dismiss_from_audience(
    db: Any,
    person_name: str,
    *,
    night_id: Optional[int] = None,
    body: str = "",
) -> Optional[int]:
    """「令 X 退下」口令：确定性落告退账，即时反映于名单查询。

    不在场者令退 = 幂等 no-op（不落账、返 None）；名不填 → 响亮 empty_person。"""
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("令退人名不能为空", code="empty_person")
    nid = night_id
    if nid is None:
        open_n = get_open_night(db)
        if open_n is None:
            return None
        nid = int(open_n["id"])
    if name not in present_names_at(db, int(nid)):
        return None
    return append_ledger_entry(
        db, int(nid),
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body=body or f"帝令{name}退下，{name}告退。",
        tags=[TAG_EXIT],
        check_dead=False,
    )


def _apply_presence(present: set[str], entry: Dict[str, Any]) -> None:
    """按一条进出账更新在场集：入殿=进、告退=出、传召在途=无在场效果。"""
    tags = entry.get("tags") or []
    persons = entry.get("person_names") or []
    if TAG_EXIT in tags:
        present.difference_update(persons)
    elif TAG_ENTER in tags:
        present.update(persons)


def present_names_at(
    db: Any, night_id: int, *, at_seq: Optional[int] = None,
) -> set[str]:
    """确定性推导任一时刻在场名单：进出账累积到 at_seq（含）为止的净在场者。

    机器承重态只有在场/不在场；at_seq=None 取夜内末态。侍立/正对奏是叙事层次
    非硬状态，不影响本推导。"""
    present: set[str] = set()
    for entry in list_ledger(db, night_id):
        if at_seq is not None and int(entry["seq"]) > int(at_seq):
            break
        _apply_presence(present, entry)
    return present


def audible_entries_for(
    db: Any, night_id: int, person_name: str,
) -> List[Dict[str, Any]]:
    """某人侍立区间内可闻的账目：以其进出账时刻为界，仅殿上公开条目。

    御前低语（AUDIBILITY_PRIVATE）不流入；从未入殿者（如仅传召在途）取数为空。"""
    name = str(person_name or "").strip()
    if not name:
        return []
    present: set[str] = set()
    out: List[Dict[str, Any]] = []
    for entry in list_ledger(db, night_id):
        _apply_presence(present, entry)
        if name in present and entry.get("audibility") == AUDIBILITY_PUBLIC:
            out.append(entry)
    return out


SCENE_RECAP_HEADER = "【殿上先前所闻】"


def audience_scene_recap(
    db: Any, person_name: str, *, night_id: Optional[int] = None,
) -> str:
    """连场组装：某人在场时段所闻的殿上公开对话，渲染为可读回顾块（#507 presence-aware）。

    宣下一个不断场、前一位留殿侧侍立时，对话流按在场名单送入组装：侍立者补话可引用
    其在场时段殿上公开对话（AC2 区间取数）。未在场者 / 无开夜 / 区间无公开对话 →
    空串（AC3 负向：未在场者的组装输入不含殿内对话）。区间与可闻性判据复用
    audible_entries_for（御前低语不流入、入殿前不闻），不另立第二套在场/可闻性真源。"""
    name = str(person_name or "").strip()
    if not name or not hasattr(db, "conn"):
        return ""
    nid = night_id
    if nid is None:
        open_n = get_open_night(db)
        if open_n is None:
            return ""
        nid = int(open_n["id"])
    bodies: List[str] = []
    for entry in audible_entries_for(db, int(nid), name):
        body = str(entry.get("body") or "").strip()
        if body:
            bodies.append(body)
    if not bodies:
        return ""
    return SCENE_RECAP_HEADER + "\n" + "\n".join(bodies)


def _is_command_entry(entry: Dict[str, Any]) -> bool:
    """口令/框架账（发起/进出/收夜/常在员额）由引擎侧确定性写入、`source_chat_turn_id==0`；
    抽取账（`>0`）的 tags 是 LLM 开放叙事标签。引擎口令常量标（TAG_ENTER/TAG_CLOSE_NIGHT…）
    只在口令账上机器承重——抽取账开放 tags 不得驱动机器态（ADR 0035：在场等机器承重态输入
    不解析自由文本；否则 LLM 写「入殿」旁路死账、写「收夜」旁路收夜账幂等）。"""
    return int(entry.get("source_chat_turn_id") or 0) == 0


def _command_entry_has_tag_enter(entry: Dict[str, Any]) -> bool:
    """在场进=口令账（宣入/常在员额）的确定性 TAG_ENTER；抽取账进只认机器 `presence_effect`。"""
    return _is_command_entry(entry) and TAG_ENTER in (entry.get("tags") or [])


def persons_entered_tonight(db: Any, night_id: int) -> set[str]:
    names: set[str] = set()
    for entry in list_ledger(db, night_id):
        if _command_entry_has_tag_enter(entry):
            names.update(entry.get("person_names") or [])
    return names


def persons_present_tonight(db: Any, night_id: int) -> set[str]:
    """当前在场名单：按时序键消费机器可读的进/出效果（#501 AC2/AC9）。

    在场是机器承重态，其输入**不解析自由文本**——进=口令账 TAG_ENTER（宣入/常在员额，
    引擎确定性写）**或**抽取账 presence_effect='enter'（机器可读字段）；出=抽取账
    presence_effect='exit'。抽取账开放 tags 不驱动在场（否则 LLM 写「入殿」旁路死账校验、
    与 settle 的 `check_dead=(presence_effect==enter)` 不对称）。派生只认已落账（list_ledger
    只返回已 settle 的账），故待补期间缺账 = 尚未发生、不猜（AC9）；补账落地后自然校正。
    """
    present: set[str] = set()
    for entry in list_ledger(db, night_id):  # 已按时序键排序
        persons = [str(n) for n in (entry.get("person_names") or [])]
        effect = str(entry.get("presence_effect") or "")
        if effect == PRESENCE_ENTER or _command_entry_has_tag_enter(entry):
            present.update(persons)
        if effect == PRESENCE_EXIT:
            present.difference_update(persons)
    return present


def ensure_summon_enter(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_XUANRU,
    body: str = "",
) -> Optional[int]:
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    # 单一在场真源：已在场者不重复宣入；告退后再宣须重新落入殿账（present_names_at
    # 会去人，persons_entered_tonight「凡入过即并集」会漏——双真源导致 chat 有名单无）。
    if name in present_names_at(db, night_id):
        return None
    return summon_enter(db, night_id, name, method=method, body=body)


def attach_chat_turn_to_night(
    db: Any,
    state: GameState,
    minister_name: str,
    *,
    agno_session_id: str = "",
    agno_runs_before: int = 0,
    time_of_day: str = "",
    location: str = "",
    summon_method: str = METHOD_XUANRU,
    beat_generator: Any = None,
    knowledge_provider: Any = None,
) -> tuple[int, int]:
    """开夜（若需）+ 首次对话落宣入账 + 建 generating 对话轮挂 night_id/night_seq。

    beat_generator 注入时（#503 编排）：开夜/入殿账正文经编排层路由输入后由内容生成填充，
    落为对应账正文；不注入则沿用 #498 确定性兜底正文。见 beat_orchestration。
    """
    from ming_sim import beat_orchestration as beats

    # beat 正文（慢 LLM）在**任何落库之前**全部生成好，再落库——生成中途抛错则本次零写入，
    # 不留「开着的夜有开夜/员额账却无入殿账、无对话轮」的半场（#503 L4）。
    # 也不把 LLM 调用裹进写事务（否则持写锁跨 ~15-30s LLM，撞 #498/#499 写锁纪律，P5）。
    existing = get_open_night(db)
    if existing is not None and existing["status"] == NIGHT_STATUS_CLOSING:
        # 上一夜收夜未完（closing）：open_night 会响亮拒绝——早于任何 beat 生成触发，零写零浪费。
        ensure_open_night_for_audience(
            db, state, time_of_day=time_of_day, location=location,
        )  # 必抛 night_closing_incomplete

    enter_body = ""
    if existing is not None and existing["status"] == NIGHT_STATUS_OPEN:
        # 已开夜：不重复开夜账；入殿账只在真正首入殿时生成（重复起聊＝奏对非再入殿）。
        night = existing
        night_id = int(night["id"])
        if beat_generator is not None and minister_name not in persons_entered_tonight(db, night_id):
            enter_body = beats.generate_enter_beat_body(
                db, state, night=night, person_name=minister_name,
                summon_method=summon_method,
                beat_generator=beat_generator, knowledge_provider=knowledge_provider,
            )
    else:
        # 新夜：开夜账 + 首入殿账都先生成，再一并落库（生成抛错 → 本次零写入）。
        # 首入殿时夜尚无公开层/前情（无明旨、无前次），以刚生成的开夜气氛作临时公开层供给
        # （不复刻 open_night 的员额账内部格式）。
        open_body = ""
        if beat_generator is not None:
            open_body = beats.generate_open_beat_body(
                db, state, time_of_day=time_of_day, location=location,
                beat_generator=beat_generator, knowledge_provider=knowledge_provider,
            )
            enter_body = beats.generate_enter_beat_body(
                db, state,
                night={"id": 0, "time_of_day": time_of_day, "location": location},
                person_name=minister_name, summon_method=summon_method,
                beat_generator=beat_generator, knowledge_provider=knowledge_provider,
                extra_public_layer=(open_body,) if open_body else (),
            )
        night = ensure_open_night_for_audience(
            db, state, time_of_day=time_of_day, location=location, body=open_body,
        )
    night_id = int(night["id"])
    ensure_summon_enter(db, night_id, minister_name, method=summon_method, body=enter_body)
    chat_turn_id = db.create_chat_turn(
        state,
        minister_name,
        agno_session_id,
        agno_runs_before,
        night_id=night_id,
    )
    return night_id, int(chat_turn_id)


def mark_actions_night_approved(
    db: Any, action_ids: Sequence[int], *, night_id: Optional[int] = None,
) -> int:
    """对话应允时：把暂存标为本夜已应允，收夜再提交（密令除外，调用方分流）。"""
    if not hasattr(db, "mark_pending_night_approved"):
        return 0
    nid = night_id
    if nid is None:
        open_n = get_open_night(db)
        nid = int(open_n["id"]) if open_n else None
    return int(db.mark_pending_night_approved(action_ids, night_id=nid) or 0)
