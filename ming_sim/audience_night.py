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
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ming_sim.error_pack import error_packs_root
from ming_sim.mindreading import is_inner_court_attendant
from ming_sim.models import GameState

# ── 引擎侧口令标签常量（ADR 0035：确定性写读）──────────────────────────
TAG_OPEN_NIGHT = "开夜"
TAG_ENTER = "入殿"
TAG_CLOSE_NIGHT = "收夜"
TAG_STANDING_ROSTER = "常在员额"
TAG_AUTO_CLOSE = "顺势收夜"

# 召法：发起账开放标签，非硬骨架字段
METHOD_XUANRU = "宣入"
METHOD_CHUANZHAO = "传召"
METHOD_YUECI = "越次"
SUMMON_METHODS = frozenset({METHOD_XUANRU, METHOD_CHUANZHAO, METHOD_YUECI})

AUDIBILITY_PUBLIC = "殿上公开"
AUDIBILITY_PRIVATE = "御前低语"

NIGHT_STATUS_OPEN = "open"
NIGHT_STATUS_CLOSING = "closing"
NIGHT_STATUS_CLOSED = "closed"

# 收夜提交步（游标幂等；crash 后从 cursor 续跑）
CLOSE_STEP_COMMIT_OFFICE = 1       # 任免类 pending → 真实盘面
CLOSE_STEP_TRANSFER_CANDIDATES = 2  # 拟旨候选转档
CLOSE_STEP_FINALIZE = 3            # 收夜账 + 标 closed
CLOSE_STEPS = (
    CLOSE_STEP_COMMIT_OFFICE,
    CLOSE_STEP_TRANSFER_CANDIDATES,
    CLOSE_STEP_FINALIZE,
)

# 在飞回话等待（AC10）：默认短熔断；测试可覆写
DEFAULT_IN_FLIGHT_WAIT_S = 0.05
DEFAULT_IN_FLIGHT_POLL_S = 0.01


class AudienceNightError(Exception):
    """召对夜域响亮失败（死账 / 在飞 / 坏输入）。携带 code 与可选错误包路径。"""

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


def write_audience_error_pack(
    *,
    kind: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> str:
    """落一份夜域错误包到 user-data error_packs（响亮、可发包，与结算包同根）。"""
    root = error_packs_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pack_dir = root / f"audience_{kind}_{stamp}"
    # 并发撞名时加后缀，不覆盖
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
    """开夜时动态解析常在员额：在职且 active 的御前近臣槽位持有者。

    死/免者不入名单（不硬编码人名）——防死人自动入殿撞死账锁死开夜（ADR 0035 R5）。
    """
    if not hasattr(db, "conn"):
        return []
    rows = db.conn.execute(
        "SELECT name, office, office_type, status FROM characters "
        "WHERE status = 'active' ORDER BY name"
    ).fetchall()
    names: List[str] = []
    for row in rows:
        if is_inner_court_attendant(row):
            names.append(str(row["name"]))
    return names


def get_open_night(db: Any) -> Optional[Dict[str, Any]]:
    """当前唯一开着的夜（含 closing 未收齐）；无则 None。"""
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
        "opened_at": raw.get("opened_at"),
        "closed_at": raw.get("closed_at"),
    }


def list_ledger(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """按夜取有序账目（硬骨架三字段 + 正文/标签）。"""
    rows = db.conn.execute(
        "SELECT * FROM story_ledger_entries WHERE night_id = ? ORDER BY seq ASC, id ASC",
        (int(night_id),),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw = _row_dict(row)
        out.append({
            "id": int(raw["id"]),
            "night_id": int(raw["night_id"]),
            "seq": int(raw["seq"]),
            "person_names": [str(n) for n in _json_list(raw.get("person_names"))],
            "audibility": str(raw.get("audibility") or AUDIBILITY_PUBLIC),
            "body": str(raw.get("body") or ""),
            "tags": [str(t) for t in _json_list(raw.get("tags"))],
            "created_at": raw.get("created_at"),
        })
    return out


def list_chat_turns_for_night(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """按夜取有序对话轮（含完成态）。"""
    rows = db.conn.execute(
        "SELECT * FROM chat_turns WHERE night_id = ? ORDER BY id ASC",
        (int(night_id),),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def _next_seq(db: Any, night_id: int) -> int:
    row = db.conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM story_ledger_entries WHERE night_id = ?",
        (int(night_id),),
    ).fetchone()
    return int(row["m"] if row is not None else 0) + 1


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
    """廉价死账校验：已死者不能在场。响亮 AudienceNightError + 错误包。"""
    dead: List[str] = []
    for name in names:
        n = str(name or "").strip()
        if not n:
            continue
        status = _character_status(db, n)
        if status == "dead":
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
) -> int:
    """追加一条故事账。涉及人非空且 check_dead 时跑死账校验。"""
    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(
            f"夜不存在：{night_id}", code="night_not_found",
        )
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
    tag_list = [str(t) for t in (tags or []) if str(t)]
    seq = _next_seq(db, night_id)
    cur = db.conn.execute(
        """
        INSERT INTO story_ledger_entries
            (night_id, seq, person_names, audibility, body, tags)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(night_id),
            seq,
            json.dumps(persons, ensure_ascii=False),
            audibility,
            body or "",
            json.dumps(tag_list, ensure_ascii=False),
        ),
    )
    if getattr(db, "owns_transaction", lambda: True)():
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
    """开夜：落夜实体 + 开夜账 + 常在员额入殿账。已有开夜则返回之（不叠开）。"""
    existing = get_open_night(db)
    if existing is not None and existing["status"] == NIGHT_STATUS_OPEN:
        return existing
    if existing is not None and existing["status"] == NIGHT_STATUS_CLOSING:
        # 收夜中：续跑收齐，不新开
        close_night(db, state, night_id=int(existing["id"]))
        existing = get_open_night(db)
        if existing is not None:
            return existing

    cur = db.conn.execute(
        """
        INSERT INTO audience_nights
            (turn, year, period, time_of_day, location, status, close_commit_cursor)
        VALUES (?, ?, ?, ?, ?, ?, 0)
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
    if getattr(db, "owns_transaction", lambda: True)():
        db.conn.commit()
    night_id = int(cur.lastrowid)

    open_body = body or (
        f"{location or '便殿'}·{time_of_day or '此时'}，召对夜启。"
    )
    append_ledger_entry(
        db, night_id,
        person_names=[],
        audibility=AUDIBILITY_PUBLIC,
        body=open_body,
        tags=[TAG_OPEN_NIGHT],
        check_dead=False,
    )

    for name in resolve_standing_roster(db):
        # 员额已按 active 过滤；再过死账校验是双重保险（status 非 dead）
        append_ledger_entry(
            db, night_id,
            person_names=[name],
            audibility=AUDIBILITY_PUBLIC,
            body=f"{name}随侍在侧。",
            tags=[TAG_ENTER, TAG_STANDING_ROSTER],
            check_dead=True,
        )

    night = get_night(db, night_id)
    assert night is not None
    return night


def summon_enter(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_XUANRU,
    body: str = "",
    audibility: str = AUDIBILITY_PUBLIC,
) -> int:
    """宣人入殿：一条账写清谁被召、怎么召的（召法在开放标签）。"""
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    method = str(method or METHOD_XUANRU).strip()
    if method not in SUMMON_METHODS:
        raise AudienceNightError(
            f"召法非法：{method!r}（须为 {'/'.join(sorted(SUMMON_METHODS))}）",
            code="bad_summon_method",
        )
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
    """本夜未完成回话：status=generating，或 active 但尚无大臣回话。"""
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
    timeout_s: float = DEFAULT_IN_FLIGHT_WAIT_S,
    poll_s: float = DEFAULT_IN_FLIGHT_POLL_S,
) -> None:
    """等在飞回话完成；超时则 fail-closed 中止收夜（夜保持开）。"""
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
    if getattr(db, "owns_transaction", lambda: True)():
        db.conn.commit()


def close_night(
    db: Any,
    state: GameState,
    *,
    night_id: Optional[int] = None,
    content: Any = None,
    registry: Any = None,
    auto: bool = False,
    body: str = "",
    wait_timeout_s: float = DEFAULT_IN_FLIGHT_WAIT_S,
    crash_after_step: Optional[int] = None,
    on_step: Optional[Callable[[int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """收夜：在飞守卫 → 提交游标幂等续跑 → 收夜账 → closed。

    crash_after_step：测试注入点——完成该步并推进游标后抛 AudienceNightError(code=close_crash)。
    重开时从 close_commit_cursor 续跑，不重复已提交步。
    """
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

    # 在飞回话：先等短窗；仍在飞 → fail-closed（不进入 closing 提交）
    if night["status"] == NIGHT_STATUS_OPEN:
        wait_in_flight_clear(db, night_id, timeout_s=wait_timeout_s)
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

    # Step 1: 任免
    if cursor < CLOSE_STEP_COMMIT_OFFICE:
        if hasattr(db, "commit_pending_actions"):
            db.commit_pending_actions(
                state, content=content, registry=registry, kind_filter="office",
            )
        _advance(CLOSE_STEP_COMMIT_OFFICE)

    # Step 2: 拟旨候选转档（0049：收夜提交即准旨；落 draft 候选档）
    if cursor < CLOSE_STEP_TRANSFER_CANDIDATES:
        if hasattr(db, "commit_pending_actions"):
            db.commit_pending_actions(
                state, content=content, registry=registry,
                kind_filter="directive", directive_status="draft",
            )
        _advance(CLOSE_STEP_TRANSFER_CANDIDATES)

    # Step 3: 收夜账 + closed
    if cursor < CLOSE_STEP_FINALIZE:
        tags = [TAG_CLOSE_NIGHT]
        if auto:
            tags.append(TAG_AUTO_CLOSE)
        close_body = body or (
            "王承恩代宣退朝，今夜召对到此。" if auto else "退朝，今夜召对到此。"
        )
        # 避免重复写收夜账（幂等：已有收夜标签则跳过）
        existing_tags = {
            t for e in list_ledger(db, night_id) for t in e.get("tags") or []
        }
        if TAG_CLOSE_NIGHT not in existing_tags:
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
    wait_timeout_s: float = DEFAULT_IN_FLIGHT_WAIT_S,
    crash_after_step: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """颁诏/过回合前：有开夜则顺势收夜；无开夜返回 None。"""
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
    )


def ensure_open_night_for_audience(
    db: Any,
    state: GameState,
    *,
    time_of_day: str = "",
    location: str = "",
) -> Dict[str, Any]:
    """进入召对时确保有开夜（幂等）。"""
    return open_night(db, state, time_of_day=time_of_day, location=location)


def persons_entered_tonight(db: Any, night_id: int) -> set[str]:
    """由入殿账推出的本夜已入殿人名（含常在员额）。"""
    names: set[str] = set()
    for entry in list_ledger(db, night_id):
        if TAG_ENTER in (entry.get("tags") or []):
            names.update(entry.get("person_names") or [])
    return names


def ensure_summon_enter(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_XUANRU,
) -> Optional[int]:
    """若此人尚未入殿账则落发起/入殿账；已在则 no-op 返回 None。"""
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    if name in persons_entered_tonight(db, night_id):
        return None
    return summon_enter(db, night_id, name, method=method)


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
) -> tuple[int, int]:
    """开夜（若需）+ 首次对话落宣入账 + 建 generating 对话轮挂 night_id。

    返回 (night_id, chat_turn_id)。
    """
    night = ensure_open_night_for_audience(
        db, state, time_of_day=time_of_day, location=location,
    )
    night_id = int(night["id"])
    ensure_summon_enter(db, night_id, minister_name, method=summon_method)
    chat_turn_id = db.create_chat_turn(
        state,
        minister_name,
        agno_session_id,
        agno_runs_before,
        night_id=night_id,
    )
    return night_id, int(chat_turn_id)
