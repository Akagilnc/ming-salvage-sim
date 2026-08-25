"""召对夜容器与故事账本地基（#498 / ADR 0035）。

公开 seam：开夜 → 宣人入殿账 → 对话轮锚定 → 收夜；按夜取账/对话；
廉价死账校验；常在员额动态解析；夜×结算顺势收夜；收夜提交幂等游标；
在飞/待补回话并入收夜流程处理完再结算，玩家无感；仅统一重试耗尽才走失败单源。

口令账标签由本模块引擎常量写入——确定性写读，restore 不解析自由文本。
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ming_sim.error_pack import error_packs_root
from ming_sim.mindreading import is_inner_court_attendant
from ming_sim.models import GameState
from ming_sim.participant_roster import is_non_person_participant_name

logger = logging.getLogger(__name__)

# ── 引擎侧口令标签常量（ADR 0035：确定性写读）──────────────────────────
TAG_OPEN_NIGHT = "开夜"
TAG_ENTER = "入殿"
TAG_CLOSE_NIGHT = "收夜"
TAG_STANDING_ROSTER = "常在员额"
TAG_AUTO_CLOSE = "顺势收夜"
TAG_MINGFA = "明发"  # 夜内定案的旨在公开层账上标已明发（#502 AC6，供 #459 扩散）
_MINGFA_ID_PREFIX = "明发#"  # 明发账挂 directive_id 的结构化标（逐条幂等续跑，#502 L6）


def mingfa_publication_tag(directive_id: int | str) -> str:
    """Canonical engine-command publication-fact tag for one directive."""
    return f"{_MINGFA_ID_PREFIX}{int(directive_id)}"


def exact_mingfa_publication_directive_id(tag: object) -> Optional[int]:
    """Exact 明发#<positive-int> only; rejects malformed suffix / non-decimal residue.

    Use str.isdecimal (not isdigit): superscript/compatibility digits like '²' are
    isdigit-true but int() rejects them, and must never alias as publication facts.
    """
    text = str(tag or "")
    if not text.startswith(_MINGFA_ID_PREFIX):
        return None
    rest = text[len(_MINGFA_ID_PREFIX):]
    if not rest.isdecimal():
        return None
    directive_id = int(rest)
    # Reject non-canonical forms (leading zeros, etc.) so CAST/prefix loosness cannot alias.
    if directive_id <= 0 or str(directive_id) != rest:
        return None
    return directive_id


def engine_command_mingfa_publication_facts(
    entries: Sequence[Dict[str, Any]],
) -> List[Tuple[int, int]]:
    """One exact engine-command 明发 publication-fact seam: (night_id, directive_id).

    Only engine-command ledger rows (`source_chat_turn_id==0`); only exact
    `明发#<positive-int>` tags. Shared by both promulgated readers and close_night
    already_ids. Extractor open tags and malformed suffixes are not publication facts.
    """
    seen: set[Tuple[int, int]] = set()
    out: List[Tuple[int, int]] = []
    for entry in entries:
        if int(entry.get("source_chat_turn_id") or 0) != 0:
            continue
        night_id = int(entry.get("night_id") or 0)
        for tag in entry.get("tags") or []:
            directive_id = exact_mingfa_publication_directive_id(tag)
            if directive_id is None:
                continue
            key = (night_id, directive_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def engine_command_mingfa_publication_ids(
    entries: Sequence[Dict[str, Any]],
) -> set[int]:
    """Directive ids from the one exact engine-command 明发 publication-fact seam."""
    return {directive_id for _night_id, directive_id in engine_command_mingfa_publication_facts(entries)}
# 进出账（ADR 0035：TAG_ENTER/TAG_EXIT 是机器承重的在场效果标识「进/出」）
TAG_EXIT = "告退"          # 出：离场；确定性「令 X 退下」口令落此账
TAG_IN_TRANSIT = "传召在途"  # 账在人不在场：传召已发、人在途（不落在场效果）
TAG_SUMMON_UNSETTLED = "传召未结"
TAG_SUMMON_SETTLED = "传召结清"
_SUMMON_ORIGIN_PREFIX = "传召源#"
# #526 / #471 S10：留侍叙事账标签——非进/出，不驱动在场（口径回灌 #500）
TAG_STAY_ATTEND = "留侍"

# #526 结构化口令判词（引擎只认判词，不重解析散文；非 ACTION_CLUSTERS）
CMD_CLOSE_NIGHT = "close_night"
CMD_AMBIGUOUS_CLOSE = "ambiguous_close"
CMD_STAY_ATTEND = "stay_attend"
CMD_NONE = "none"
_CMD_VERDICTS = frozenset({
    CMD_CLOSE_NIGHT, CMD_AMBIGUOUS_CLOSE, CMD_STAY_ATTEND, CMD_NONE,
})

METHOD_XUANRU = "宣入"
METHOD_CHUANZHAO = "传召"
METHOD_YUECI = "越次"
SUMMON_METHODS = frozenset({METHOD_XUANRU, METHOD_CHUANZHAO, METHOD_YUECI})

AUDIBILITY_PUBLIC = "殿上公开"
AUDIBILITY_PRIVATE = "御前低语"

# 夜容器时地兜底（#498 AC：时辰/地点须持久且可读）。真实入口（web/CLI attach）多不带玩家
# 选值——缺省时以 in-world 兜底落库（非空字符串），而非留空串成不可读的裸空。开夜账正文同用。
# #1339：默认须是时刻/更次口径，禁「此时」这类非时辰词进起居注标题。
DEFAULT_TIME_OF_DAY = "戌时"
DEFAULT_LOCATION = "便殿"

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
CLOSE_STEP_ENDORSEMENT_BOUND = 3
CLOSE_STEP_FINALIZE = 4
CLOSE_STEPS = (
    CLOSE_STEP_COMMIT_OFFICE,
    CLOSE_STEP_TRANSFER_CANDIDATES,
    CLOSE_STEP_ENDORSEMENT_BOUND,
    CLOSE_STEP_FINALIZE,
)

# 在飞回话：轮询间隔；wait 只消费既有 chat turn/worker 终态，不按 elapsed 伪造失败（#1353 K10a）。
# DEFAULT_IN_FLIGHT_WAIT_S 仅作签名/调用方兼容残留，不再驱动墙钟 409。
DEFAULT_IN_FLIGHT_WAIT_S = 30.0
DEFAULT_IN_FLIGHT_POLL_S = 0.05

# 收夜提交的 night-domain kinds（密令应允即落地，不进收夜提交）
# Pre-endorsement: only draft-dossier prerequisites (endorsement targets). Final
# gameplay effects such as consort cultivation run only after endorsement binding.
_CLOSE_COMMIT_KINDS_OFFICE = frozenset({"office"})
_CLOSE_COMMIT_KINDS_DIRECTIVE = frozenset({"directive"})
_CLOSE_COMMIT_KINDS_FINAL = frozenset({"consort"})

# ── 夜内真实盘面直写白名单（ADR 0038 防坑不变式；#506 AC3）───────────────────────
# 撤回逆转干净的结构性前提：夜内对真实盘面的直写**只有**这可枚举的两项，其余结构化
# 后果一律走 ADR 0006 待确认暂存、收夜才提交。每项映射其直写落地的真实盘面表；新增任何
# 夜内直写必须过设计审、显式扩本表，否则撤回逆转不净。〔白名单第三项「召对口关系边事件」
# 随 #479/ADR 0082 另片过审，不在本片。〕
# 夜内真实盘面直写白名单（ADR 0038 防坑不变式；#506 AC3）。第三项「召对口关系边
# 事件」随 #634/ADR 0082 落地：判官拍与收夜扫尾当场落库，边事件带源轮绑定
# （origin chat_turn 段），撤回按轮删＋水位回退，逆转干净。
NIGHT_DIRECT_WRITE_WHITELIST: Dict[str, frozenset] = {
    "密令落地": frozenset({"secret_orders", "secret_order_briefs"}),
    "未在册人物入册": frozenset({"characters", "character_offices"}),
    "召对口关系边事件": frozenset({"relation_edge_events"}),
}

# 夜内结构化写可能触及、且属真实盘面（非暂存/候选层）的表全集——审计据此判越权：落在此集
# 却不在白名单授权的直写 = 越权夜内直写。暂存/候选层（pending_actions/turn_directives）是
# 待确认层、收夜才提交，不算真实盘面直写，不在此集。
_REAL_BOARD_TABLES = frozenset({
    "characters", "character_offices", "consort_traits", "factions",
    "secret_orders", "secret_order_briefs", "relation_edge_events",
})


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


def night_endorsement_bound(night: Optional[Dict[str, Any]]) -> bool:
    """Endorsement-bound watermark is close_commit_cursor, not a parallel column."""
    if not night:
        return False
    return int(night.get("close_commit_cursor") or 0) >= CLOSE_STEP_ENDORSEMENT_BOUND


def assert_night_accepts_player_input(
    db: Any,
    night_id: Optional[int] = None,
    *,
    what: str = "写入",
) -> Optional[Dict[str, Any]]:
    """Freeze new dialogue / story / stage / approve while status=CLOSING.

    Close-owned short writes and close-owned story drain are not player input;
    they do not call this seam. Failure reopens OPEN so retries may proceed.
    """
    if night_id is not None and int(night_id) > 0:
        night = get_night(db, int(night_id))
    else:
        night = get_open_night(db)
    if night is None:
        return None
    if str(night.get("status") or "") == NIGHT_STATUS_CLOSING:
        # #1301：玩家面文案去裸 night_id（结构化 detail 已有）；diegetic 可读。
        raise AudienceNightError(
            f"本夜收夜中，暂不能{what}。",
            code="night_closing",
            detail={"night_id": int(night["id"]), "what": what},
        )
    return night


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
            "origin_chat_turn_id": int(raw.get("origin_chat_turn_id") or 0),
            "origin_ref": str(raw.get("origin_ref") or ""),
            "presence_effect": str(raw.get("presence_effect") or ""),
            "created_at": raw.get("created_at"),
            "kind": "ledger",
        })
    return out


def list_chat_turns_for_night(db: Any, night_id: int) -> List[Dict[str, Any]]:
    # 撤回的轮（status='undone'）从「按夜取数」隐去——与「该轮未发生」等价（#506）。
    # failed 半场轮 / consumed 空问话召见 scaffold 同样不计入夜时间线。
    rows = db.conn.execute(
        "SELECT * FROM chat_turns WHERE night_id = ? "
        "AND status NOT IN ('undone', 'failed', 'consumed') "
        "ORDER BY night_seq ASC, id ASC",
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


def night_archive_metadata(
    ledgers: List[Dict[str, Any]], turns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Purely derive archive labels from already-loaded durable-store rows."""
    summon_methods = [
        method
        for entry in ledgers if _is_command_entry(entry)
        for method in SUMMON_METHODS if method in (entry.get("tags") or [])
    ]
    # #1331/#1339：involved_people 投影缝复用 raw 非人判定（DRY 单真源）；
    # 禁 canon 后再滤（司礼监→王承恩）。写入侧 ledger 保留原文，投影侧只列真人。
    people: List[str] = []
    candidate_groups = [entry.get("person_names") or [] for entry in ledgers]
    candidate_groups.extend([turn.get("minister_name")] for turn in turns)
    for names in candidate_groups:
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name or name in people:
                continue
            if is_non_person_participant_name(name):
                continue
            people.append(name)
    summon_method = summon_methods[0] if summon_methods else ""
    return {
        # Summon methods remain machine tags; the container contract exposes the
        # player-facing audience type from this single production source.
        "audience_type": "越次召对" if summon_method == METHOD_YUECI else "召对",
        "involved_people": people,
    }


def read_night_scroll(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """Read one audience night as the shared live/archive scroll contract.

    The two durable stores remain untouched.  This projection merges them, omits
    extraction-derived ledger cards by structural provenance
    (`source_chat_turn_id>0`, same shape as cascade_echo production marks — no
    text-stare paraphrase detection), derives scene dividers from exit/next-entry
    facts, and leaves the coda generation slot empty. Memory consumers still read
    `list_ledger` directly and see every story fact.
    """
    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    ledgers = list_ledger(db, night_id)
    turns = list_chat_turns_for_night(db, night_id)
    # 召法已由引擎作为结构化常量 tag 落在入殿口令账上；它是当前夜容器可用的
    # 真实召对类型来源。抽取账的开放 tags 绝不参与该投影。
    audience_type = night_archive_metadata(ledgers, turns)["audience_type"]
    container = {
        "time_of_day": night["time_of_day"],
        "location": night["location"],
        "audience_type": audience_type,
    }

    def message(*, role: str, speaker: str, audibility: str, time: Any,
                content: str, beat: str, soft_boundary: bool = False,
                chat_turn_id: int = 0, record_id: int = 0,
                highlights: Optional[List[str]] = None) -> Dict[str, Any]:
        # #544：只大臣气泡带判官清单；其余角色恒 []
        hl: List[str] = list(highlights or []) if role == "minister" else []
        result = {
            "role": role, "speaker": speaker, "audibility": audibility,
            "time": time, "content": content, "soft_boundary": soft_boundary,
            "beat": beat, "highlights": hl, "container": dict(container),
        }
        if chat_turn_id:
            result["chat_turn_id"] = int(chat_turn_id)
        if record_id:
            result["record_id"] = int(record_id)
        return result

    events: List[tuple[float, int, Dict[str, Any]]] = []
    for turn in turns:
        for rank, (column, role, speaker) in enumerate((
            ("user_message_id", "user", "朕"),
            ("minister_message_id", "minister", str(turn.get("minister_name") or "")),
        )):
            message_id = int(turn.get(column) or 0)
            if not message_id:
                continue
            row = db.conn.execute(
                "SELECT content,created_at,highlights_json FROM chat_messages WHERE id=?",
                (message_id,),
            ).fetchone()
            if row is None:
                continue
            content = str(row["content"] or "")
            # #544：只走 GameDB._parse_highlights_json 唯一真源（SELECT 已点名该列）
            hl: List[str] = (
                list(db._parse_highlights_json(row["highlights_json"]))
                if role == "minister"
                else []
            )
            events.append((
                float(int(turn.get("night_seq") or 0)), 20 + rank,
                message(role=role, speaker=speaker, audibility=AUDIBILITY_PUBLIC,
                        time=row["created_at"], content=content, beat="dialogue",
                        chat_turn_id=int(turn["id"]), highlights=hl),
            ))
        # 递话/读心是对话轮的第三种持久消息，紧随该轮奏对归位；不并入故事账。
        if hasattr(db, "list_mindreading_records"):
            for record_index, record in enumerate(db.list_mindreading_records(int(turn["id"]))):
                narration = str(record.get("narration") or "").strip()
                if narration:
                    events.append((
                        float(int(turn.get("night_seq") or 0)), 30 + record_index,
                        message(role="attendant", speaker=str(record.get("reader") or "近臣"),
                                audibility=AUDIBILITY_PRIVATE, time=None,
                                content=narration, beat="aside", chat_turn_id=int(turn["id"]),
                                record_id=int(record.get("id") or 0)),
                    ))

    for entry in ledgers:
        tags = set(entry.get("tags") or [])
        # #1293a：非口令/框架账（_is_command_entry 补集，含抽取派生与其它
        # source>0 留痕如路径应答）一律不上 live/档案同源卷轴；禁盯 body。
        if not _is_command_entry(entry):
            continue
        if TAG_OPEN_NIGHT in tags:
            beat = "opening"
        elif TAG_CLOSE_NIGHT in tags:
            beat = "closing"
        elif TAG_ENTER in tags:
            beat = "entrance"
        elif TAG_EXIT in tags:
            beat = "exit"
        else:
            beat = "aside" if entry["audibility"] == AUDIBILITY_PRIVATE else "scene"
        # #657 S4/P7：OPEN/ENTER 口令账仅 body.strip() 非空才投影；
        # 空垫位不进 scroll（无空条、无人物锚、无固定句冒充）。
        if beat in {"opening", "entrance"} and not str(entry.get("body") or "").strip():
            continue
        events.append((
            _entry_order_key(entry), 10,
            message(role="attendant" if beat == "aside" else "scene",
                    speaker=(entry["person_names"][0] if beat == "aside" and entry["person_names"] else ""),
                    audibility=entry["audibility"], time=entry["created_at"],
                    content=entry["body"], beat=beat),
        ))

    # A divider belongs after each exit.  Its optional name is sourced only from
    # the next entry fact; an unmatched final exit deliberately remains unnamed.
    facts = sorted(ledgers, key=lambda e: (_entry_order_key(e), int(e["id"])))
    divided_exits: set[tuple[str, float]] = set()
    for index, entry in enumerate(facts):
        tags = set(entry.get("tags") or [])
        is_exit = (_is_command_entry(entry) and TAG_EXIT in tags) or entry.get("presence_effect") == PRESENCE_EXIT
        if not is_exit:
            continue
        person = (entry.get("person_names") or [""])[0]
        # Command and extractor facts can describe the same actual departure.
        # Their shared night order is the durable source-turn identity; a later
        # departure has a different order and must retain its own divider.
        exit_identity = (person, _entry_order_key(entry))
        if exit_identity in divided_exits:
            continue
        divided_exits.add(exit_identity)
        next_name = ""
        for following in facts[index + 1:]:
            following_tags = set(following.get("tags") or [])
            if ((_is_command_entry(following) and TAG_ENTER in following_tags)
                    or following.get("presence_effect") == PRESENCE_ENTER):
                next_name = (following.get("person_names") or [""])[0]
                break
        events.append((
            _entry_order_key(entry), 90,
            message(role="scene", speaker=next_name, audibility=AUDIBILITY_PUBLIC,
                    time=entry["created_at"], content="", beat="divider", soft_boundary=True),
        ))

    events.sort(key=lambda item: (item[0], item[1]))
    scroll = [item[2] for item in events]
    scroll.append(message(role="scene", speaker="", audibility=AUDIBILITY_PUBLIC,
                          time=night.get("closed_at") or night.get("opened_at"),
                          content="", beat="coda"))
    return scroll


def _night_direct_write_allowed_tables() -> frozenset:
    allowed: set[str] = set()
    for tables in NIGHT_DIRECT_WRITE_WHITELIST.values():
        allowed |= set(tables)
    return frozenset(allowed)


def audit_night_direct_writes(db: Any, night_id: int) -> set[str]:
    """审计一夜内对真实盘面的直写全部落在可枚举白名单内（ADR 0038 防坑不变式，#506 AC3）。

    撤回逆转干净的前提 = 夜内对真实盘面的直写只有白名单两项（密令落地、未在册人物入册），
    其余结构化后果全走待确认暂存、收夜才提交。经该夜各未撤/未失败轮的前像撤销日志
    （chat_turn_rollback_items 记录本轮触碰过的业务表）核真：任一真实盘面表被直写、却不属
    白名单授权 → 越权夜内直写，写错误包并响亮咬住（此类直写撤回逆转不净，是设计洞）。

    返回观测到的白名单操作名集（合法夜用于确认「密令落地/入册」确经白名单落地）。
    """
    allowed = _night_direct_write_allowed_tables()
    rows = db.conn.execute(
        """
        SELECT DISTINCT i.target_table
        FROM chat_turn_rollback_items i
        JOIN chat_turns t ON t.id = i.chat_turn_id
        WHERE t.night_id = ? AND t.status NOT IN ('undone', 'failed', 'consumed')
        """,
        (int(night_id),),
    ).fetchall()
    observed_ops: set[str] = set()
    violations: List[str] = []
    for row in rows:
        table = str(row["target_table"] if hasattr(row, "keys") else row[0])
        if table not in _REAL_BOARD_TABLES:
            continue  # 暂存/候选层非真实盘面直写，不审
        if table not in allowed:
            violations.append(table)
            continue
        for op, tables in NIGHT_DIRECT_WRITE_WHITELIST.items():
            if table in tables:
                observed_ops.add(op)
    if violations:
        tables_sorted = sorted(set(violations))
        message = (
            f"越权夜内直写：{('、'.join(tables_sorted))} 不在夜内直写白名单"
            f"（授权表：{sorted(allowed)}）——须走待确认暂存或过设计审扩白名单。"
        )
        pack = write_audience_error_pack(
            kind="unwhitelisted_night_write",
            message=message,
            detail={"night_id": int(night_id), "tables": tables_sorted},
        )
        raise AudienceNightError(
            message,
            code="unwhitelisted_night_write",
            error_pack_path=pack,
            detail={"night_id": int(night_id), "tables": tables_sorted},
        )
    return observed_ops


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
    origin_chat_turn_id: int = 0,
    origin_ref: str = "",
    allow_closing: bool = False,
) -> int:
    """追加一条故事账。commit=False 时由外层事务统一提交（开夜原子）。

    抽取账（#501）额外带溯源 `source_chat_turn_id`、机器可读 `presence_effect`
    （''/enter/exit）与时序键 `order_key`（绑定源对话轮原始时序，补跑落回原位）；
    口令/框架账三者取默认（0/''/NULL），读取端 order_key 缺省 COALESCE 回退 seq。

    `origin_chat_turn_id`（#506）：口令账由某一轮 attach 创建时绑该轮 chat_turn_id，供
    撤回按轮删除该轮所产的入殿/告退等口令账；0=开夜/员额/收夜等框架账，不随任一轮撤。

    CLOSING 一律拒绝玩家侧新账（默认 allow_closing=False）；收夜自有框架写与
    close-owned drain 仅显式 allow_closing=True，不得按 source/origin id 漏放。
    """
    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    if night["status"] == NIGHT_STATUS_CLOSED:
        raise AudienceNightError(
            f"夜已收，不能再落账：{night_id}", code="night_closed",
        )
    if night["status"] == NIGHT_STATUS_CLOSING and not allow_closing:
        raise AudienceNightError(
            f"本夜收夜中，不能再落故事账：{night_id}",
            code="night_closing",
            detail={"night_id": int(night_id)},
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
    origin = str(origin_ref or "").strip()
    cur = db.conn.execute(
        """
        INSERT INTO story_ledger_entries
            (night_id, seq, person_names, audibility, body, tags,
             source_chat_turn_id, presence_effect, order_key, origin_chat_turn_id,
             origin_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            int(origin_chat_turn_id or 0),
            origin,
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
    empty_scaffold: bool = False,
) -> Dict[str, Any]:
    """开夜：夜实体 + 开夜账 + 常在员额入殿账，单事务全有或全无。

    #657 empty_scaffold=True：registry/summon 开夜垫位路径——OPEN 与员额 ENTER
    只落 body=""，禁止固定开夜句/「随侍在侧」成功旁路。
    """
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

    # 时地兜底在落库前统一定死（单一 seam）：真实入口缺玩家选值时也持久非空、可读（#498 AC）。
    time_of_day = str(time_of_day or "").strip() or DEFAULT_TIME_OF_DAY
    location = str(location or "").strip() or DEFAULT_LOCATION

    roster = resolve_standing_roster(db)
    if empty_scaffold:
        # #657 P7/W1：垫位路径只许空 body；不叠复命场面、不用固定开夜句。
        open_body = ""
    else:
        open_body = body or f"{location}·{time_of_day}，召对启。"
        # #621：次回合召对顶出复命场面（pending todo 投影；P4 定性、不停轮）。
        # body 是开夜气氛层（含 LLM open-beat）；复命是召对顶出层——二者叠加，
        # 不得因调用方已供 body 而跳过（生产 ensure_open_night_for_audience 常带 body）。
        from ming_sim.due_review import list_due_review_scenes
        from ming_sim.urge_lever import list_urge_audience_scenes
        scenes = list_due_review_scenes(db, state)
        # #624 / ADR 0078：谏/宽限同款次回合召对顶出（不进 due-review 白名单、不占接管窗）
        scenes = list(scenes) + list(list_urge_audience_scenes(db, state))
        if scenes:
            scene_lines = [str(s.get("scene_text") or "").strip() for s in scenes]
            scene_lines = [line for line in scene_lines if line]
            if scene_lines:
                open_body = open_body + "\n" + "\n".join(scene_lines)

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
                time_of_day,
                location,
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
            # #657 P7/W3：registry 开夜垫位路径员额 ENTER 先落 body=""；
            # 禁止 generator 完成前落「随侍在侧」固定句。
            roster_body = "" if empty_scaffold else f"{name}随侍在侧。"
            append_ledger_entry(
                db, night_id,
                person_names=[name],
                audibility=AUDIBILITY_PUBLIC,
                body=roster_body,
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
    origin_chat_turn_id: int = 0,
    origin_ref: str = "",
    empty_scaffold: bool = False,
    commit: bool = True,
) -> int:
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    method = _validate_summon_method(method, default=METHOD_XUANRU)
    # #657 P7/W2：成功垫位只许 body=""；删固定入殿句成功旁路。
    # 非 scaffold 旧调用仍可 body or 固定句（兼容既有 attach 路径的非空 generator 正文）。
    if empty_scaffold:
        text = ""
    else:
        text = body or f"{method}{name}入殿。"
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=audibility,
        body=text,
        tags=[TAG_ENTER, method],
        check_dead=True,
        origin_chat_turn_id=origin_chat_turn_id,
        origin_ref=origin_ref,
        commit=commit,
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
    write_gate: Any = None,
) -> None:
    """等在飞回话完成；只依 chat turn/worker 终态放行，不按 elapsed 伪造失败。

    #1353 K10a / ADR 0149：工人落 active/failed/interrupted 终态即续跑。
    真挂死终结属 provider/worker 接缝（硬超时 → 失败终态 → 本等待自然解除）；
    timeout_s 保留调用方签名兼容，**不再**用于墙钟 409。
    #1353 r7：每次轮询短持 write_gate 读共享 conn，sleep 必在闸外（禁持锁睡眠）。
    """
    del timeout_s  # 签名兼容；禁 elapsed 伪造失败（K10a）
    if poll_s is None:
        poll_s = DEFAULT_IN_FLIGHT_POLL_S
    gate = _gate_cm(write_gate)
    while True:
        with gate:
            inflight = list_in_flight_chat_turns(db, night_id)
        if not inflight:
            return
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


def _pending_extraction_rows(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """#1353 单真源：挡收夜判定与 pending 呈现共用 list_unextracted_replies。"""
    if not hasattr(db, "list_unextracted_replies"):
        return []
    rows = db.list_unextracted_replies(night_id=int(night_id)) or []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if isinstance(r, Mapping):
            out.append(dict(r))
    return out


def _raise_pending_extraction(
    db: Any,
    night_id: int,
    *,
    rows: Optional[Sequence[Mapping[str, Any]]] = None,
    missing_deps: bool = False,
) -> None:
    """欠账抽取耗尽 → 既定失败单源（#1353 fold-in）。

    诊断细节进 error pack / provider_message；玩家 message 唯一走
    CLI_RUNNER_PLAYER_MESSAGE。禁玩家可见欠账拒绝面与手动补写入口。
    """
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    snap = list(rows) if rows is not None else _pending_extraction_rows(db, int(night_id))
    ids = [int(r.get("chat_turn_id") or 0) for r in snap]
    if missing_deps:
        technical = (
            f"收夜中止：本夜仍有 {len(ids)} 条待补抽取，且无 LLM/写锁可清空"
            f"（chat_turn_ids={ids}）。"
        )
    else:
        technical = (
            "收夜中止：本夜仍有未抽取落账的回话（待补），"
            f"chat_turn_ids={ids}。"
        )
    write_audience_error_pack(
        kind="pending_extraction", message=technical,
        detail={"night_id": int(night_id), "chat_turn_ids": ids},
    )
    # code 保留 pending_extraction 供引擎内 heal 重拍；玩家只见单源文案。
    raise LLMUnavailable(
        CLI_RUNNER_PLAYER_MESSAGE,
        code="pending_extraction",
        provider_message=technical,
    )


def _drain_story_extraction_or_fail_closed(
    db: Any, night_id: int, *, llm_config: Any, write_gate: Any,
    extractor_agent: Any = None,
) -> None:
    """收夜前清空普通待补抽取（ADR 0036）——并入过月/收夜流，玩家无感。

    只补 story/presence；不含 endorsement batch。有待补 → 强制同步补跑（内部静默，
    不推玩家可见 stage）；仍有 → 失败单源（LLMUnavailable）。LLM 在 write_gate
    外跑（drain 内 settle 才短持锁）。

    write_gate 必须是调用方原始锁（或 None）——禁传入 _gate_cm(nullcontext)，
    否则 `write_gate is None` 卫兵被架空（#1353 嫌疑缝②）。
    """
    if not hasattr(db, "count_pending_story_extractions"):
        return
    # #1353 r10：pending 计数与缺依赖时的 list 同持 gate（禁二相锁外裸读）。
    gate = _gate_cm(write_gate)
    with gate:
        pending = int(db.count_pending_story_extractions(night_id=int(night_id)) or 0)
        if pending <= 0:
            return
        missing_rows: Optional[List[Dict[str, Any]]] = None
        if llm_config is None or write_gate is None:
            missing_rows = _pending_extraction_rows(db, int(night_id))
    if missing_rows is not None:
        _raise_pending_extraction(
            db, int(night_id), rows=missing_rows, missing_deps=True,
        )
    from ming_sim.audience_extraction import drain_pending_before_close

    drain_pending_before_close(
        db=db, llm_config=llm_config, write_gate=write_gate, night_id=int(night_id),
        extractor_agent=extractor_agent,
    )


def _gate_cm(write_gate: Any):
    """Runtime write gate section. None → nullcontext (CLI single-writer)."""
    if write_gate is None:
        return contextlib.nullcontext()
    return write_gate


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
    on_closing: Optional[Callable[[], None]] = None,
    beat_generator: Any = None,
    knowledge_provider: Any = None,
    llm_config: Any = None,
    write_gate: Any = None,
    extractor_agent: Any = None,
    endorsement_extractor_agent: Any = None,
    scene_registry: Any = None,
    close_chat_turn_id: int = 0,
) -> Dict[str, Any]:
    """收夜：短写前提 → 无锁普通补抽 + 夜级 endorsement-only 批 → 短写终局。

    分相：
    1. OPEN 期：等在飞回话清；有限 join 普通抽取 single-flight owner 后重读 DB；
       经调用方既有 ChatTurnSceneRegistry start_close（不立即 join）；持 write_gate
       原子复查并冻结 CLOSING、提交 draft 前提。不得自建第二 registry/executor/Thread。
    2. 释放 gate：清空普通 story 待补（CLOSING restore drain 作崩溃恢复口）；
       endorsement-only LLM 与 close scene 并行（无 DB transaction / 无 runtime write
       gate）；终局写入前 join close scene。
    3. 重取 gate：原子落背书水位；consort/明发/收夜账/CLOSED。

    背书或 close scene 失败 → OPEN、cursor=0、draft identity 保留；scene 失败另走
    chat-turn abandon/fail。成功前不得判官/公开明发/终局效果/CLOSED。
    """
    if wait_timeout_s is None:
        wait_timeout_s = DEFAULT_IN_FLIGHT_WAIT_S
    # #1353 r7：共享 conn 读一律短持 runtime gate（禁闸外裸 SELECT）。
    gate = _gate_cm(write_gate)
    if night_id is None:
        with gate:
            open_n = get_open_night(db)
        if open_n is None:
            return {"closed": False, "reason": "no_open_night"}
        night_id = int(open_n["id"])

    with gate:
        night = get_night(db, night_id)
        source_night_roster = {
            row["name"] for row in db.current_court_roster_rows(state)
        }
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    if night["status"] == NIGHT_STATUS_CLOSED:
        return {"closed": True, "night_id": int(night_id), "already": True}

    close_body = str(body or "")
    close_ctid = int(close_chat_turn_id or 0)
    close_scaffold_owned = False
    close_started = False
    need_close_scene = (not close_body) and beat_generator is not None
    reg = scene_registry if (
        scene_registry is not None and hasattr(scene_registry, "start_close")
    ) else None

    def _start_close_scene() -> None:
        nonlocal close_ctid, close_scaffold_owned, close_started
        if not need_close_scene or reg is None or close_started:
            return
        from ming_sim import beat_orchestration as beats
        # #542 r6e: start_close 同步抛错时 helper 经异常交出 ctid；finally 置
        # close_started，使既有 abandon/fail/OPEN 清理必跑到。
        try:
            close_ctid, close_scaffold_owned = beats.start_close_scene_on_registry(
                db, state,
                night_id=int(night_id),
                scene_registry=reg,
                beat_generator=beat_generator,
                knowledge_provider=knowledge_provider,
                chat_turn_id=int(close_ctid or 0),
            )
        except BaseException as start_exc:
            owned = getattr(start_exc, "close_scene_ownership", None)
            if owned is not None:
                close_ctid = int(owned[0])
                close_scaffold_owned = bool(owned[1])
            raise
        finally:
            close_started = bool(close_ctid)

    def _cleanup_close_scene_early(primary_exc: BaseException) -> None:
        """T15: after start_close through phase-1, any failure drains/fails scaffold and reopens."""
        cleanup_exc: BaseException | None = None
        if close_started and reg is not None:
            try:
                if hasattr(reg, "abandon"):
                    reg.abandon(int(close_ctid))
                if close_scaffold_owned and hasattr(db, "fail_chat_turn"):
                    db.fail_chat_turn(int(close_ctid))
            except BaseException as exc:
                cleanup_exc = exc
        with gate:
            _set_night_fields(
                db, night_id, status=NIGHT_STATUS_OPEN, closed_at=None,
                close_commit_cursor=0,
            )
        if cleanup_exc is not None:
            raise primary_exc from cleanup_exc
        raise primary_exc

    try:
        if night["status"] == NIGHT_STATUS_OPEN:
            # In-flight wait：轮询短持 gate 读，sleep 闸外（禁持锁睡眠）。
            wait_in_flight_clear(
                db, night_id, timeout_s=wait_timeout_s, write_gate=write_gate,
            )
            # #1353：start_close 的 assemble/知识短读与置 CLOSING 同持 write_gate。
            # 禁闸外知识链读共享 conn——后于屏障领票的尾随若尚未 wait_prior，
            # 并发 SELECT 会 sqlite3.Row IndexError（tuple index out of range）。
            # start_close 只同步组 inputs + 提交 Future，不 join LLM。
            with gate:
                _start_close_scene()
                _set_night_fields(
                    db, night_id, status=NIGHT_STATUS_CLOSING,
                )
                if on_closing is not None:
                    on_closing()
                night = get_night(db, night_id)
            assert night is not None
        else:
            # Resume CLOSING：仍无 body 时 start 同一 registry 缝（不自建平行生命周期）。
            # CLOSING restore drain 留作 ADR 0036 崩溃恢复口（下方 phase-2 drain）。
            # 与 OPEN 同：start_close 短读持 gate；重读 night 同持。
            with gate:
                _start_close_scene()
                if on_closing is not None:
                    on_closing()
                night = get_night(db, night_id) or night

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

        # ── Phase 1: short writes for draft-dossier prerequisites only ─────────
        with gate:
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
                # Draft dossiers / turn_directives are durable prerequisites only.
                _advance(CLOSE_STEP_TRANSFER_CANDIDATES)
    except BaseException as early_exc:
        # Only clean when close scene was started; bare pre-start failures pass through.
        if close_started:
            _cleanup_close_scene_early(early_exc)
        raise

    # Prepare on the owner thread; only the gate-free provider call enters the
    # existing close bucket. Finalization happens after that bucket is joined.
    from ming_sim.relation_judge import (
        PreparedRelationJudge, abandon_summon_relation_judge,
        finalize_summon_relation_judge, invoke_summon_relation_judge_provider,
        prepare_summon_relation_judge,
    )
    judge_prepared = prepare_summon_relation_judge(
        db, state, write_gate=write_gate, night_id=int(night_id),
        allowed_endpoint_names=source_night_roster,
    )
    judge_future = None
    if isinstance(judge_prepared, PreparedRelationJudge):
        if not close_ctid and reg is not None:
            with gate:
                close_ctid = int(db.create_chat_turn(
                    state, "收夜", "close-judge", 0, night_id=int(night_id),
                ))
                close_scaffold_owned = True
                close_started = True
        if reg is not None and hasattr(reg, "start_relation_judge_provider"):
            judge_future = reg.start_relation_judge_provider(
                int(close_ctid),
                lambda: invoke_summon_relation_judge_provider(
                    judge_prepared, llm_config=llm_config,
                ),
            )
        else:
            # Library callers without a session registry still use the split phases;
            # importantly, only the provider call runs gate-free here.
            judge_provider_result = invoke_summon_relation_judge_provider(
                judge_prepared, llm_config=llm_config,
            )
            judge_result = finalize_summon_relation_judge(
                judge_prepared, judge_provider_result, write_gate=write_gate,
            )
            judge_prepared = judge_result

    # ── Phase 2: gate-free ordinary catch-up + endorsement-only LLM ────────
    # Ordinary story drain (LLM outside settle lock). CLOSING restore drain =
    # ADR 0036 崩溃恢复口；OPEN 期 join 已汇合在飞 owner，此处只清真欠账。
    # drain 失败走 abandon（与 early cleanup 同形），禁 join 拉长双源窗。
    try:
        _drain_story_extraction_or_fail_closed(
            db, int(night_id), llm_config=llm_config, write_gate=write_gate,
            extractor_agent=extractor_agent,
        )
    except Exception as drain_exc:
        from ming_sim.exceptions import LLMUnavailable
        if isinstance(judge_prepared, PreparedRelationJudge):
            abandon_summon_relation_judge(judge_prepared)

        cleanup_exc: BaseException | None = None
        if close_started and reg is not None:
            try:
                if hasattr(reg, "abandon"):
                    reg.abandon(int(close_ctid))
                if close_scaffold_owned and hasattr(db, "fail_chat_turn"):
                    db.fail_chat_turn(int(close_ctid))
            except BaseException as exc:
                cleanup_exc = exc
        with gate:
            _set_night_fields(
                db, night_id, status=NIGHT_STATUS_OPEN, closed_at=None,
                close_commit_cursor=0,
            )
        # 清理后按 list_unextracted 单真源重拍。欠账耗尽 → 失败单源（非玩家 CTA 409）。
        # 不递归重入；空集 → close_retry（竞态全愈，玩家重按过月）。
        is_pending_block = (
            isinstance(drain_exc, LLMUnavailable)
            and getattr(drain_exc, "code", None) == "pending_extraction"
        )
        if is_pending_block:
            # #1353 r7：失败重拍 pending 短持 gate（共享 conn 读）。
            with gate:
                still = _pending_extraction_rows(db, int(night_id))
            if still:
                try:
                    # 单点构造 escaping error：禁 `from drain_exc`（stale ids 经 cause 漏出）。
                    _raise_pending_extraction(db, int(night_id), rows=still)
                except LLMUnavailable as fresh:
                    if cleanup_exc is not None:
                        raise fresh from cleanup_exc
                    raise fresh
            retry_exc = AudienceNightError(
                "收夜中止：请原地重试收夜或颁诏。",
                code="close_retry",
                detail={"night_id": int(night_id)},
            )
            if cleanup_exc is not None:
                raise retry_exc from cleanup_exc
            raise retry_exc
        if cleanup_exc is not None:
            raise drain_exc from cleanup_exc
        raise

    # ── Phase 2: endorsement LLM ∥ close scene (join before finalize) ──────
    # Both branches end before finalize or reopen. No ExceptionGroup bus /
    # second registry/executor/Thread. First observed failure propagates;
    # sibling still drains; join/cleanup chains via __cause__.
    primary_exc: BaseException | None = None
    try:
        from ming_sim.audience_extraction import run_endorsement_batch_for_night

        # Endorsement LLM must not hold runtime write gate / DB transaction.
        run_endorsement_batch_for_night(
            db=db,
            night_id=int(night_id),
            llm_config=llm_config,
            write_gate=gate,
            extractor_agent=endorsement_extractor_agent,
        )
    except Exception as exc:
        primary_exc = exc

    join_exc: BaseException | None = None
    if close_started and reg is not None:
        try:
            from ming_sim import beat_orchestration as beats
            joined_body = beats.join_close_scene_on_registry(
                db,
                scene_registry=reg,
                chat_turn_id=int(close_ctid),
                scaffold_owned=bool(close_scaffold_owned),
            )
            if joined_body and not close_body:
                close_body = str(joined_body)
        except Exception as exc:
            join_exc = exc

    if judge_future is not None and join_exc is not None:
        abandon_summon_relation_judge(judge_prepared)

    if judge_future is not None and join_exc is None:
        _marker, judge_provider_result = judge_future.result()
        judge_result = finalize_summon_relation_judge(
            judge_prepared, judge_provider_result, write_gate=write_gate,
        )
        if judge_result.get("degraded"):
            logger.warning(
                "relation judge sweep degraded night_id=%s: %s",
                night_id, judge_result["degraded"],
            )

    if primary_exc is not None or join_exc is not None:
        with gate:
            _set_night_fields(
                db, night_id, status=NIGHT_STATUS_OPEN, closed_at=None,
                close_commit_cursor=0,
            )
        if primary_exc is not None:
            if join_exc is not None:
                raise primary_exc from join_exc
            raise primary_exc
        raise join_exc

    # ── Phase 3: short writes — final effects, 明发, close ledger, CLOSED ──
    # Close body joined above (or explicit body=); no generator under the runtime
    # gate (ADR 0005: no silent in-gate fallback).
    # #1353 r7：phase3 前 get_night 与终局写同持 gate（禁闸外裸读）。
    with gate:
        night = get_night(db, night_id) or night
        cursor = int(night["close_commit_cursor"] or 0)
        if cursor < CLOSE_STEP_ENDORSEMENT_BOUND:
            # settle path should have advanced this; missing watermark is a hard fault.
            # Restore OPEN so the player can retry (ADR 0036); keep code + diagnostics.
            fault_cursor = int(cursor)
            _set_night_fields(
                db, night_id, status=NIGHT_STATUS_OPEN, closed_at=None,
                close_commit_cursor=0,
            )
            raise AudienceNightError(
                f"收夜背书水位未落定（night_id={int(night_id)}, cursor={fault_cursor}）",
                code="endorsement_not_bound",
                detail={"night_id": int(night_id), "cursor": fault_cursor},
            )
        if cursor < CLOSE_STEP_FINALIZE:
            commit_fresh_summons_for_night(
                db, state, int(night_id), content=content, registry=registry,
            )
            _commit_night_approved(
                db, state, int(night_id),
                kinds=_CLOSE_COMMIT_KINDS_FINAL,
                content=content, registry=registry,
            )
            # 夜内定案的旨落公开层账、标已明发（#502 AC6）——仅 endorsement 成功之后。
            already_ids = {
                str(did)
                for did in engine_command_mingfa_publication_ids(list_ledger(db, night_id))
            }
            _mingfa_candidates = db.conn.execute(
                """
                SELECT td.id AS directive_id, td.actor, td.text
                FROM pending_actions pa
                JOIN turn_directives td ON td.id = pa.committed_directive_id
                WHERE pa.night_id = ? AND pa.kind = 'directive'
                  AND pa.status = 'committed' AND pa.committed_directive_id > 0
                ORDER BY td.id
                """,
                (int(night_id),),
            ).fetchall()
            for _pd in _mingfa_candidates:
                _did_int = int(_pd["directive_id"] or 0)
                _did = str(_did_int)
                if not _did_int or _did in already_ids:
                    continue
                append_ledger_entry(
                    db, night_id,
                    person_names=[str(_pd["actor"] or "")] if _pd["actor"] else [],
                    audibility=AUDIBILITY_PUBLIC,
                    body=f"明发旨意：{str(_pd['text'] or '')}",
                    tags=[TAG_MINGFA, mingfa_publication_tag(_did_int)],
                    check_dead=False,
                    allow_closing=True,
                )
            tags = [TAG_CLOSE_NIGHT]
            if auto:
                tags.append(TAG_AUTO_CLOSE)
            existing_tags = {
                t for e in list_ledger(db, night_id) if _is_command_entry(e)
                for t in e.get("tags") or []
            }
            if TAG_CLOSE_NIGHT not in existing_tags:
                final_close_body = close_body or (
                    "王承恩代宣退朝，召对到此。" if auto else "退朝，召对到此。"
                )
                append_ledger_entry(
                    db, night_id,
                    person_names=[],
                    audibility=AUDIBILITY_PUBLIC,
                    body=final_close_body,
                    tags=tags,
                    check_dead=False,
                    allow_closing=True,
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
    extractor_agent: Any = None,
    endorsement_extractor_agent: Any = None,
    scene_registry: Any = None,
    close_chat_turn_id: int = 0,
    body: str = "",
    on_closing: Optional[Callable[[], None]] = None,
) -> Optional[Dict[str, Any]]:
    """颁诏/过回合前：有开夜则顺势收夜；无开夜返回 None。

    write_gate 应为真实 runtime Lock（或 CLI 下 None）；close_night 只在短写阶段持锁，
    endorsement LLM 期间释放。调用方不得在外层持同一把非重入锁再传入 nullcontext。
    scene_registry：既有 ChatTurnSceneRegistry（session 持有）；start_close 后与
    endorsement 并行，终局写入前 join；不自建第二 registry/executor。
    #1353 fold-in r5：欠账补跑内部静默，不透传过月 SSE。
    #1353 r10：wrapper 入口 get_open_night 短持 gate（r7 修了 close_night 内、漏此处）。
    """
    with _gate_cm(write_gate):
        open_n = get_open_night(db)
    if open_n is None:
        return None
    return close_night(
        db, state,
        night_id=int(open_n["id"]),
        content=content,
        registry=registry,
        auto=True,
        body=body,
        wait_timeout_s=wait_timeout_s,
        crash_after_step=crash_after_step,
        beat_generator=beat_generator,
        knowledge_provider=knowledge_provider,
        llm_config=llm_config,
        write_gate=write_gate,
        extractor_agent=extractor_agent,
        endorsement_extractor_agent=endorsement_extractor_agent,
        scene_registry=scene_registry,
        close_chat_turn_id=int(close_chat_turn_id or 0),
        on_closing=on_closing,
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


def _summon_origin_tag(origin_id: object) -> str:
    origin = str(origin_id or "").strip()
    return f"{_SUMMON_ORIGIN_PREFIX}{origin}" if origin else ""


def _project_unsettled_summon_kind(
    db: Any, tags: Sequence[Any], person_name: str,
) -> str:
    """故事账 tags × 权威行止 → fresh | in_transit | waiting（只读推导，不落新 tag）。"""
    if TAG_IN_TRANSIT not in tags:
        return "fresh"
    from ming_sim.matching import is_capital_location

    row = db.conn.execute(
        "SELECT location, transit_to, status FROM characters WHERE name=?",
        (person_name,),
    ).fetchone()
    if row is None:
        return "in_transit"
    status = str(row["status"] or "active").strip() or "active"
    transit_to = str(row["transit_to"] or "").strip()
    location = str(row["location"] or "").strip()
    # ADR 0096 候见：在途 tag 且 active、无 transit、已在京 → waiting。
    if status == "active" and not transit_to and is_capital_location(location):
        return "waiting"
    return "in_transit"


def list_unsettled_summons(db: Any) -> List[Dict[str, Any]]:
    """从故事账确定性投影未结传召；不解析自由叙事正文。"""
    rows = db.conn.execute(
        "SELECT id, night_id, person_names, tags FROM story_ledger_entries ORDER BY id"
    ).fetchall()
    projected: List[Dict[str, Any]] = []
    for row in rows:
        tags = json.loads(row["tags"] or "[]")
        if TAG_SUMMON_UNSETTLED not in tags or TAG_SUMMON_SETTLED in tags:
            continue
        origin = next(
            (str(tag)[len(_SUMMON_ORIGIN_PREFIX):] for tag in tags
             if str(tag).startswith(_SUMMON_ORIGIN_PREFIX)),
            "",
        )
        names = json.loads(row["person_names"] or "[]")
        if not origin or not names:
            continue
        person_name = str(names[0])
        projected.append({
            "entry_id": int(row["id"]), "night_id": int(row["night_id"]),
            "person_name": person_name, "origin_id": origin,
            "kind": _project_unsettled_summon_kind(db, tags, person_name),
        })
    return projected


def _one_per_person(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """消费端投影：每人只供一份事实；ledger 多 origin 行仍独立保留供撤回。

    输入须已按 entry id 升序（list_unsettled_summons ORDER BY id），保留最早一条。
    """
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        name = str(item.get("person_name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(item)
    return out


def list_waiting_audience_summons(db: Any) -> List[Dict[str, Any]]:
    """未结候见投影：list_unsettled 中 kind=waiting 的薄封装（非第二真源）。

    每人每阶段只向读端供一份候见事实；多 origin ledger 行不合并。
    """
    from ming_sim.matching import is_capital_location

    waiting: List[Dict[str, Any]] = []
    for item in list_unsettled_summons(db):
        if item["kind"] != "waiting":
            continue
        row = db.conn.execute(
            "SELECT location FROM characters WHERE name=?",
            (item["person_name"],),
        ).fetchone()
        location = str(row["location"] or "").strip() if row is not None else ""
        # 防御：kind 已判定 waiting；location 仍回填权威行止供汇总读端。
        if location and not is_capital_location(location):
            location = ""
        waiting.append({
            "person_name": item["person_name"],
            "origin_id": item["origin_id"],
            "source_entry_id": item["entry_id"],
            "location": location,
        })
    return _one_per_person(waiting)


def list_arrived_unsettled_summons(db: Any) -> List[Dict[str, Any]]:
    """Project in-transit summons whose original non-capital journey has completed.

    waiting（抵京候见）不进续程 payload；inactive 由 retire 结清，不投续程。
    每人每阶段只向读端供一份续赴京事实；多 origin ledger 行不合并。
    """
    from ming_sim.matching import is_capital_location

    arrived: List[Dict[str, Any]] = []
    for item in list_unsettled_summons(db):
        if item["kind"] != "in_transit":
            continue
        row = db.conn.execute(
            "SELECT location, transit_to, status FROM characters WHERE name=?",
            (item["person_name"],),
        ).fetchone()
        if row is None or str(row["transit_to"] or "").strip():
            continue
        status = str(row["status"] or "active").strip() or "active"
        if status != "active":
            continue
        destination = str(row["location"] or "").strip()
        if not destination:
            continue
        # kind=in_transit 已排除 capital waiting；此处再挡一层同地续程。
        if is_capital_location(destination):
            continue
        arrived.append({
            "person_name": item["person_name"],
            "original_destination": destination,
            "origin_id": item["origin_id"],
            "source_entry_id": item["entry_id"],
            "required_fact": "抵原地后续赴京",
        })
    return _one_per_person(arrived)


def settle_applied_arrived_summons(
    db: Any, applied: Dict[str, Any],
) -> List[str]:
    """结清已由 canonical applier 成功续启赴京的在途召旨。

    只认 applied_person_changes 中未拒收且 transit_to=beizhili 的成功行止；
    同人全部 kind=in_transit 未结 origin 一并结清。失败/空 applied 为 no-op。
    外层 settle atomic 使行止与结清同成同败（_should_commit 已为 False）。
    """
    accepted = {
        str(item.get("name") or item.get("人物") or "").strip()
        for item in (applied.get("applied_person_changes") or [])
        if isinstance(item, dict)
        and not item.get("rejected")
        and str(item.get("transit_to") or item.get("去向") or "").strip() == "beizhili"
    }
    accepted.discard("")
    if not accepted:
        return []
    settled: List[str] = []
    for item in list_unsettled_summons(db):
        # 月度判官只收 in_transit origin；成功续启后 transit_to 已变，
        # 后置投影不再是 arrived，故按 person∈accepted 结清。
        if item["kind"] != "in_transit" or item["person_name"] not in accepted:
            continue
        origin = str(item["origin_id"])
        if settle_summon_origin(db, origin):
            settled.append(origin)
    return settled


def _mark_summon_entries_in_transit(db: Any, items: Sequence[Dict[str, Any]]) -> None:
    """启程成功后把未结 fresh 账标为在途；保留 TAG_SUMMON_UNSETTLED 与 origin。"""
    for item in items:
        entry_id = int(item["entry_id"])
        row = db.conn.execute(
            "SELECT tags FROM story_ledger_entries WHERE id=?", (entry_id,)
        ).fetchone()
        if row is None:
            continue
        tags = json.loads(row["tags"] or "[]")
        if TAG_IN_TRANSIT in tags:
            continue
        tags.append(TAG_IN_TRANSIT)
        db.conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), entry_id),
        )
    if _should_commit(db):
        db.conn.commit()


def settle_summon_origin(
    db: Any, origin_id: object, *, commit: bool = True,
) -> bool:
    """按 origin 结清未结传召；重复结清为幂等 no-op。

    结清点：宣入/在京 admission 消费；人物非 active 退役；
    候见中 active 再奉旨离京（canonical 行止写缝）；
    续启 applier 成功后按 origin（settle_applied_arrived_summons）。
    commit 由调用方事务所有权决定（与 append_story_ledger 同形）；
    行止接缝须传 commit=commit_person_change，避免 SAVEPOINT/外层事务中擅自提交。
    """
    origin = str(origin_id or "").strip()
    matches = [item for item in list_unsettled_summons(db) if item["origin_id"] == origin]
    if not matches:
        return False
    for item in matches:
        row = db.conn.execute(
            "SELECT tags FROM story_ledger_entries WHERE id=?", (item["entry_id"],)
        ).fetchone()
        tags = json.loads(row["tags"] or "[]")
        tags = [tag for tag in tags if tag != TAG_SUMMON_UNSETTLED]
        tags.append(TAG_SUMMON_SETTLED)
        db.conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), item["entry_id"]),
        )
    if commit and _should_commit(db):
        db.conn.commit()
    return True


def retire_unsettled_summons_for_inactive(db: Any) -> List[str]:
    """人物已非 active 时确定性结清其全部未结传召（ADR 0096 / ADR 0009）。"""
    settled: List[str] = []
    for item in list(list_unsettled_summons(db)):
        row = db.conn.execute(
            "SELECT status FROM characters WHERE name=?",
            (item["person_name"],),
        ).fetchone()
        status = str(row["status"] or "active").strip() or "active" if row is not None else "active"
        if status == "active":
            continue
        origin = str(item["origin_id"])
        if settle_summon_origin(db, origin):
            settled.append(origin)
    return settled


def settle_unsettled_summons_for_person(
    db: Any, person_name: str, *, commit: bool = True,
) -> List[str]:
    """宣入/在京 admission：结清该人全部未结传召 origin。

    commit 继承调用方事务所有权；canonical 行止离京接缝须显式传入。
    """
    name = str(person_name or "").strip()
    if not name:
        return []
    settled: List[str] = []
    for item in list(list_unsettled_summons(db)):
        if item["person_name"] != name:
            continue
        origin = str(item["origin_id"])
        if settle_summon_origin(db, origin, commit=commit):
            settled.append(origin)
    return settled


def record_summon_fresh(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_CHUANZHAO,
    body: str = "",
    origin_id: object = "",
    origin_chat_turn_id: int = 0,
) -> int:
    """落 fresh 场外传召账；带 origin 时，同一人物同一未结 origin 幂等。

    不同 origin 各留独立 ledger 行及各自 origin_chat_turn_id，供逐轮撤回；
    收夜启程仍由 commit_fresh_summons_for_night 按人聚合一次。
    默认 body 为空：机器事实只在 tags；玩家可见句由既有 LLM 特征路径生成（P7）。
    """
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("传召人名不能为空", code="empty_person")
    method = _validate_summon_method(method, default=METHOD_CHUANZHAO)
    origin_tag = _summon_origin_tag(origin_id)
    # #670 / ADR 0096：同人+同 origin 幂等；跨 origin 不得共享行（撤一轮不得误删另一轮）。
    if origin_tag:
        for item in list_unsettled_summons(db):
            if item["person_name"] == name and item["origin_id"] == str(origin_id).strip():
                return int(item["entry_id"])
    tags = [method]
    if origin_tag:
        tags.extend([TAG_SUMMON_UNSETTLED, origin_tag])
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body=str(body or ""),
        tags=tags,
        origin_chat_turn_id=int(origin_chat_turn_id or 0),
    )


def commit_fresh_summons_for_night(
    db: Any,
    state: GameState,
    night_id: int,
    *,
    content: Any = None,
    registry: Any = None,
) -> List[str]:
    """收夜按人一次 canonical 启程；成功后标在途，origin 保持未结候见关联。"""
    pending = [
        item for item in list_unsettled_summons(db)
        if item["kind"] == "fresh" and int(item["night_id"]) == int(night_id)
    ]
    if not pending:
        return []
    from ming_sim.decree import atomic_and_reload
    from ming_sim.issues import apply_score_extraction

    # 历史多 origin 未结账：按人分组，apply 一次后全部标在途（兼容重试）。
    by_person: Dict[str, List[Dict[str, Any]]] = {}
    for item in pending:
        by_person.setdefault(str(item["person_name"]), []).append(item)

    origins: List[str] = []
    with atomic_and_reload(db, state, content=content, registry=registry):
        for person_name, items in by_person.items():
            applied = apply_score_extraction(
                db,
                state,
                {"人物变更": [{
                    "name": person_name,
                    "动作": "行止",
                    "transit_to": "beizhili",
                    # Canonical applier only admits its established provenance vocabulary;
                    # the summon origin remains machine-linked in the story ledger.
                    "origin_ref": "盘面自发",
                }]},
                content=content,
                registry=registry,
            )
            results = list(applied.get("applied_person_changes") or [])
            if not results or any(result.get("rejected") for result in results):
                raise AudienceNightError(
                    f"传召启程未落定：{person_name}",
                    code="summon_departure_rejected",
                    detail={
                        "origin_id": str(items[0]["origin_id"]),
                        "results": results,
                    },
                )
            _mark_summon_entries_in_transit(db, items)
            for item in items:
                origins.append(str(item["origin_id"]))
    return origins


def record_summon_in_transit(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_CHUANZHAO,
    body: str = "",
    origin_id: object = "",
    origin_chat_turn_id: int = 0,
) -> int:
    """落传召在途账；带 origin 时，同一人物同一未结 origin 幂等。

    默认 body 为空：机器事实只在 tags（P7）。
    """
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("传召人名不能为空", code="empty_person")
    method = _validate_summon_method(method, default=METHOD_CHUANZHAO)
    origin_tag = _summon_origin_tag(origin_id)
    if origin_tag:
        for item in list_unsettled_summons(db):
            if item["person_name"] == name and item["origin_id"] == str(origin_id).strip():
                return int(item["entry_id"])
    tags = [TAG_IN_TRANSIT, method]
    if origin_tag:
        tags.extend([TAG_SUMMON_UNSETTLED, origin_tag])
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body=str(body or ""),
        tags=tags,
        origin_chat_turn_id=int(origin_chat_turn_id or 0),
    )


def dismiss_from_audience(
    db: Any,
    person_name: str,
    *,
    night_id: Optional[int] = None,
    body: str = "",
    origin_chat_turn_id: int = 0,
    state: Any = None,
    beat_generator: Any = None,
    knowledge_provider: Any = None,
) -> Optional[int]:
    """「令 X 退下」口令：确定性落告退账，即时反映于名单查询。

    不在场者令退 = 幂等 no-op（不落账、返 None）；名不填 → 响亮 empty_person。

    只落垫位/显式 body——exit 旁白由调用方登记本轮 ChatTurnSceneRegistry（#542）。
    `beat_generator` / `knowledge_provider` 形参保留兼容，**故意忽略**（禁止同步旁路）。

    `origin_chat_turn_id`（#506 L1）：tool 触发的令退发生在某一对话轮内时绑该轮 chat_turn_id，
    使撤回本轮据 origin 删掉告退账、令退者在场复原（否则告退账残留 → 按夜取数 ≠ 未发生，
    且被令退者永久差出）。0=不属某轮的独立令退（无撤回目标）。
    """
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
    # state/beat_generator/knowledge_provider: compatibility only — no sync LLM here.
    _ = (state, beat_generator, knowledge_provider)
    return append_ledger_entry(
        db, int(nid),
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body=body or f"帝令{name}退下，{name}告退。",
        tags=[TAG_EXIT],
        check_dead=False,
        origin_chat_turn_id=origin_chat_turn_id,
    )


def stay_attend_in_audience(
    db: Any,
    person_name: str,
    *,
    night_id: Optional[int] = None,
    body: str = "",
    origin_chat_turn_id: int = 0,
) -> Optional[int]:
    """「留下听着」口令：确定性落留侍叙事账，在场态不变（#526 / #500 口径）。

    不在场者 = 幂等 no-op（不落账、返 None）；名不填 → 响亮 empty_person。
    标签 TAG_STAY_ATTEND 不进 _presence_delta——不得制造进出事件。
    """
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("留侍人名不能为空", code="empty_person")
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
        body=body or f"帝令{name}留下听着，{name}殿侧侍立。",
        tags=[TAG_STAY_ATTEND],
        check_dead=False,
        origin_chat_turn_id=origin_chat_turn_id,
    )


def normalize_audience_command_verdict(raw: Any) -> str:
    """判词缝归一：只放行封闭判词，其余 → none（毒化/坏 shape 零机械面）。"""
    if isinstance(raw, str) and raw in _CMD_VERDICTS:
        return raw
    return CMD_NONE


def recognize_audience_command(message: str) -> str:
    """收夜/留侍口令结构化判词（#526）。

    确定性封闭集（COURT_BREAK / AMBIGUOUS_CLOSE / STAY_ATTEND）；引擎不重解析散文。
    不进 ACTION_CLUSTERS；非第二 parser（无自由散文正则启发）。
    无耗时软判——同步直调即可；坏 shape 由 normalize 归一，不在此宽吞异常。
    """
    from ming_sim.constants import (
        AMBIGUOUS_CLOSE_COMMANDS,
        COURT_BREAK_COMMANDS,
        STAY_ATTEND_COMMANDS,
    )

    text = str(message or "").strip()
    if not text:
        return CMD_NONE
    lowered = text.lower()
    if text in STAY_ATTEND_COMMANDS or lowered in STAY_ATTEND_COMMANDS:
        return CMD_STAY_ATTEND
    if lowered in COURT_BREAK_COMMANDS or text in COURT_BREAK_COMMANDS:
        return CMD_CLOSE_NIGHT
    if text in AMBIGUOUS_CLOSE_COMMANDS or lowered in AMBIGUOUS_CLOSE_COMMANDS:
        return CMD_AMBIGUOUS_CLOSE
    return CMD_NONE


def _presence_delta(entry: Dict[str, Any]) -> Optional[str]:
    """一条账对在场集的净效果：'enter' / 'exit' / None——**单一在场步进真源**（ADR 0035 R2）。

    进=口令账 TAG_ENTER（宣入/常在员额，引擎确定性写）**或**抽取账 presence_effect='enter'；
    出=口令账 TAG_EXIT（令退）**或**抽取账 presence_effect='exit'。抽取账开放 tags 不驱动
    在场（机器承重态不解析自由文本，与 settle `check_dead=(effect==enter)` 对称）；传召在途
    无在场效果。`present_names_at` / `audible_entries_for` / `persons_present_tonight` /
    `dismiss` 同走此核，杜绝双真源（#507：抽取 presence_effect=exit 后 recap 仍含退后公开对话，
    因旧 `_apply_presence` 只认 tags；command dismiss 的 TAG_EXIT 又漏于旧 `persons_present_tonight`）。
    `_is_command_entry` 定义在下方，运行时解析。"""
    effect = str(entry.get("presence_effect") or "")
    if effect == PRESENCE_ENTER:
        return PRESENCE_ENTER
    if effect == PRESENCE_EXIT:
        return PRESENCE_EXIT
    if _is_command_entry(entry):
        tags = entry.get("tags") or []
        if TAG_EXIT in tags:
            return PRESENCE_EXIT
        if TAG_ENTER in tags:
            return PRESENCE_ENTER
    return None


def _apply_presence(present: set[str], entry: Dict[str, Any]) -> None:
    """按一条账的净在场效果更新在场集（复用单一步进 _presence_delta）。"""
    delta = _presence_delta(entry)
    if delta is None:
        return
    persons = entry.get("person_names") or []
    if delta == PRESENCE_ENTER:
        present.update(persons)
    else:
        present.difference_update(persons)


def present_names_at(
    db: Any, night_id: int, *, at_seq: Optional[int] = None,
) -> set[str]:
    """确定性推导任一时刻在场名单：进出账累积到 at_seq（含）为止的净在场者。

    机器承重态只有在场/不在场；at_seq=None 取夜内末态。侍立/正对奏是叙事层次
    非硬状态，不影响本推导。走单一在场模型 `_apply_presence`。"""
    present: set[str] = set()
    for entry in list_ledger(db, night_id):
        # list_ledger 按时序键 COALESCE(order_key, seq) 排序：抽取账 order_key 可小于其自身
        # seq，若按裸 seq 截断会误在早排的抽取账处 break、漏掉其后命令账。比对同一时序键
        # `_entry_order_key`（口令/命令账 order_key 缺省 → 回退 seq，与 at_seq 语义对齐）。
        if at_seq is not None and _entry_order_key(entry) > float(at_seq):
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
    """当前在场名单 = 夜末在场态（#501 AC2/AC9）。

    与 `present_names_at` 共用单一在场步进 `_presence_delta`（ADR 0035 R2）——进=口令账
    TAG_ENTER（宣入/常在员额）**或**抽取账 presence_effect='enter'；出=口令账 TAG_EXIT
    （令退）**或**抽取账 presence_effect='exit'。抽取账开放 tags 不驱动在场（机器承重态不
    解析自由文本，与 settle `check_dead=(effect==enter)` 对称）。派生只认已落账（list_ledger
    只返回已 settle 的账），故待补期间缺账 = 尚未发生、不猜（AC9）；补账落地后自然校正。
    """
    return present_names_at(db, int(night_id))


def ensure_summon_enter(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_XUANRU,
    body: str = "",
    origin_chat_turn_id: int = 0,
    origin_ref: str = "",
    empty_scaffold: bool = False,
    commit: bool = True,
) -> Optional[int]:
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    # #657：带 origin_ref 的召见消费账即使人物已在场也必须落/复用独立 origin TAG_ENTER，
    # 不得 ensure_summon_enter 早退 None 当消费（S6）。
    if not origin_ref and name in present_names_at(db, night_id):
        return None
    return summon_enter(
        db, night_id, name, method=method, body=body,
        origin_chat_turn_id=origin_chat_turn_id,
        origin_ref=origin_ref,
        empty_scaffold=empty_scaffold,
        commit=commit,
    )


def rescript_summon_origin_ref(source_turn: int, idx: int, revision_round: int) -> str:
    """#657 D.0 origin 公式唯一真源。"""
    return f"rescript_draft:{int(source_turn)}:{int(idx)}:summon:r{int(revision_round)}"


def _ledger_by_origin_ref(db: Any, origin: str) -> Optional[Dict[str, Any]]:
    origin = str(origin or "").strip()
    if not origin:
        return None
    row = db.conn.execute(
        "SELECT * FROM story_ledger_entries WHERE origin_ref = ? LIMIT 1",
        (origin,),
    ).fetchone()
    if row is None:
        return None
    raw = _row_dict(row)
    return {
        "id": int(raw["id"]),
        "night_id": int(raw["night_id"]),
        "body": str(raw.get("body") or ""),
        "origin_chat_turn_id": int(raw.get("origin_chat_turn_id") or 0),
        "origin_ref": str(raw.get("origin_ref") or ""),
        "tags": [str(t) for t in _json_list(raw.get("tags"))],
        "person_names": [str(n) for n in _json_list(raw.get("person_names"))],
    }


def ensure_summon_scaffold_reenterable(
    db: Any,
    *,
    origin_ref: str,
    entry_id: int,
    chat_turn_id: int,
    expected_night_id: int,
) -> None:
    """#657 D.6：空垫位复用 CAS（failed→generating）。

    单短 atomic 内 §D.6.2 全谓词复核（含 TAG_ENTER、空 body、night 三方一致、
    minister_message 空）；generating no-op 与 failed→CAS 共用同一套谓词；
    interrupted/其它 raise。不调 reopen_interrupted；不改 reconcile。
    """
    from ming_sim.applier import atomic

    origin = str(origin_ref or "").strip()
    if not origin:
        raise AudienceNightError("ensure_summon_scaffold 缺 origin_ref", code="bad_origin")
    eid = int(entry_id)
    ctid = int(chat_turn_id)
    expect_night = int(expected_night_id)
    with atomic(db):
        # 事务内重新 SELECT，禁止信任事务前快照
        entry = db.conn.execute(
            "SELECT id, body, origin_ref, origin_chat_turn_id, night_id, tags "
            "FROM story_ledger_entries WHERE id = ?",
            (eid,),
        ).fetchone()
        if entry is None:
            raise AudienceNightError(
                f"summon 垫位不存在：entry={eid}", code="scaffold_missing",
            )
        ct = db.conn.execute(
            "SELECT id, status, user_message_id, minister_message_id, night_id "
            "FROM chat_turns WHERE id = ?",
            (ctid,),
        ).fetchone()
        if ct is None:
            raise AudienceNightError(
                f"summon scaffold chat_turn 不存在：{ctid}", code="scaffold_ct_missing",
            )
        if str(entry["origin_ref"] or "") != origin:
            raise AudienceNightError(
                f"summon 垫位 origin 漂移：entry={eid}", code="scaffold_origin_mismatch",
            )
        tags = [str(t) for t in _json_list(entry["tags"] if "tags" in entry.keys() else None)]
        if TAG_ENTER not in tags:
            raise AudienceNightError(
                f"summon 垫位缺 TAG_ENTER：entry={eid}", code="scaffold_no_enter_tag",
            )
        if str(entry["body"] or "").strip():
            raise AudienceNightError(
                f"summon 垫位已消费（body 非空）：entry={eid}", code="scaffold_consumed",
            )
        if int(entry["origin_chat_turn_id"] or 0) != ctid:
            raise AudienceNightError(
                f"summon 垫位 chat_turn 绑定漂移：entry={eid}", code="scaffold_ct_mismatch",
            )
        le_night = int(entry["night_id"] or 0)
        ct_night = int(ct["night_id"] or 0)
        if not (ct_night == le_night == expect_night):
            raise AudienceNightError(
                f"summon 垫位 night 不一致：ct={ct_night} le={le_night} expect={expect_night}",
                code="scaffold_night_mismatch",
            )
        night = get_night(db, le_night)
        if night is None or str(night.get("status") or "") not in {
            NIGHT_STATUS_OPEN, NIGHT_STATUS_CLOSING,
        }:
            raise AudienceNightError(
                f"summon 垫位夜不可用：night={le_night}", code="scaffold_night",
            )
        if ct["user_message_id"] is not None:
            raise AudienceNightError(
                f"summon scaffold 已有问话，不得 CAS：{ctid}", code="scaffold_has_user",
            )
        minister_mid = ct["minister_message_id"]
        if minister_mid is not None and int(minister_mid or 0) != 0:
            raise AudienceNightError(
                f"summon scaffold 已有大臣回复，不得 CAS：{ctid}",
                code="scaffold_has_minister",
            )
        status = str(ct["status"] or "")
        if status == "generating":
            return  # no-op；§D.6.2 谓词已在事务内复核
        if status == "failed":
            cur = db.conn.execute(
                "UPDATE chat_turns SET status = 'generating' "
                "WHERE id = ? AND status = 'failed' "
                "AND user_message_id IS NULL "
                "AND (minister_message_id IS NULL OR minister_message_id = 0)",
                (ctid,),
            )
            if cur.rowcount != 1:
                raise AudienceNightError(
                    f"summon scaffold CAS 失败：{ctid}", code="scaffold_cas_failed",
                )
            return
        if status == "interrupted":
            raise AudienceNightError(
                f"summon scaffold 为 interrupted，不得 CAS/reopen：{ctid}",
                code="scaffold_interrupted",
            )
        raise AudienceNightError(
            f"summon scaffold 状态不可复用：{status!r}", code="scaffold_bad_status",
        )


def prepare_rescript_summon_scaffold(
    db: Any,
    state: GameState,
    *,
    person_name: str,
    origin_ref: str,
    method: str = METHOD_XUANRU,
    time_of_day: str = "",
    location: str = "",
) -> Dict[str, Any]:
    """#657 D.4/D.5：新鲜空垫位 atomic 或复用已有空 origin 行。

    返回 {entry_id, chat_turn_id, night_id, consumed: bool}。
    UNIQUE 冲突：再 SELECT；非空=consumed；空=复用；禁冲突当成功。
    """
    from ming_sim.applier import atomic

    name = str(person_name or "").strip()
    origin = str(origin_ref or "").strip()
    if not name or not origin:
        raise AudienceNightError("prepare_rescript_summon 缺 name/origin", code="bad_args")

    existing = _ledger_by_origin_ref(db, origin)
    if existing is not None:
        if str(existing.get("body") or "").strip():
            return {
                "entry_id": int(existing["id"]),
                "chat_turn_id": int(existing.get("origin_chat_turn_id") or 0),
                "night_id": int(existing["night_id"]),
                "consumed": True,
            }
        # 空垫位复用
        entry_id = int(existing["id"])
        ctid = int(existing.get("origin_chat_turn_id") or 0)
        if ctid <= 0:
            raise AudienceNightError(
                f"空垫位缺 chat_turn 绑定：origin={origin}", code="scaffold_unbound",
            )
        night_id = int(existing["night_id"])
        night = get_night(db, night_id)
        night_ok = (
            night is not None
            and str(night.get("status") or "") in {NIGHT_STATUS_OPEN, NIGHT_STATUS_CLOSING}
        )
        if not night_ok:
            # §D.5/D.6：复用须同 origin/entry/chat_turn/**原夜**一致。
            # 禁跨夜改写 ledger/chat_turn.night_id。原夜已闭则重开同一夜（S5 重入）。
            with atomic(db):
                other = get_open_night(db)
                if other is not None and int(other["id"]) != night_id:
                    raise AudienceNightError(
                        f"summon 垫位原夜已闭且另有开夜：origin={origin}",
                        code="scaffold_night_conflict",
                    )
                cur = db.conn.execute(
                    "UPDATE audience_nights SET status = ?, closed_at = NULL "
                    "WHERE id = ? AND status = ?",
                    (NIGHT_STATUS_OPEN, night_id, NIGHT_STATUS_CLOSED),
                )
                if cur.rowcount != 1:
                    raise AudienceNightError(
                        f"summon 垫位原夜不可重开：night={night_id}",
                        code="scaffold_night",
                    )
        ensure_summon_scaffold_reenterable(
            db,
            origin_ref=origin,
            entry_id=entry_id,
            chat_turn_id=ctid,
            expected_night_id=night_id,
        )
        return {
            "entry_id": entry_id,
            "chat_turn_id": ctid,
            "night_id": night_id,
            "consumed": False,
        }

    # 新鲜垫位 D.4
    try:
        with atomic(db):
            night = get_open_night(db)
            if night is None or str(night.get("status") or "") != NIGHT_STATUS_OPEN:
                night = open_night(
                    db, state,
                    time_of_day=time_of_day, location=location,
                    empty_scaffold=True,
                )
            night_id = int(night["id"])
            entry_id = summon_enter(
                db, night_id, name,
                method=method,
                empty_scaffold=True,
                origin_ref=origin,
                commit=False,
            )
            chat_turn_id = db.create_chat_turn(
                state, name, f"rescript-summon:{origin}", 0,
                night_id=night_id, status="generating",
            )
            db.conn.execute(
                "UPDATE story_ledger_entries SET origin_chat_turn_id = ? WHERE id = ?",
                (int(chat_turn_id), int(entry_id)),
            )
        return {
            "entry_id": int(entry_id),
            "chat_turn_id": int(chat_turn_id),
            "night_id": night_id,
            "consumed": False,
        }
    except Exception as exc:
        # UNIQUE 冲突：再 SELECT
        msg = str(exc).lower()
        if "unique" not in msg and "constraint" not in msg:
            raise
        again = _ledger_by_origin_ref(db, origin)
        if again is None:
            raise
        if str(again.get("body") or "").strip():
            return {
                "entry_id": int(again["id"]),
                "chat_turn_id": int(again.get("origin_chat_turn_id") or 0),
                "night_id": int(again["night_id"]),
                "consumed": True,
            }
        # 空冲突 → 复用，非成功消费
        entry_id = int(again["id"])
        ctid = int(again.get("origin_chat_turn_id") or 0)
        night_id = int(again["night_id"])
        if ctid > 0:
            ensure_summon_scaffold_reenterable(
                db,
                origin_ref=origin,
                entry_id=entry_id,
                chat_turn_id=ctid,
                expected_night_id=night_id,
            )
        return {
            "entry_id": entry_id,
            "chat_turn_id": ctid,
            "night_id": night_id,
            "consumed": False,
        }


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
    # 入殿账须早于本轮对话轮落 seq（进殿在先、奏对在后，时序对齐）；chat_turn_id 此时尚未
    # 生成，故先落账后建轮，再回绑 origin_chat_turn_id——撤回本轮据此删该轮所产入殿账（#506）。
    # 三步（落入殿账 / 建轮 / 回绑 origin）整段原子（#506 L2）：中途崩溃则全回滚，绝不留
    # origin=0 的孤儿入殿账（否则撤回删不掉、与令退残留同形脏账）。seq 时序不变（enter 先 create
    # 后，各自单调分配）；atomic 暂停内层 commit、末尾一次落定或整体回滚。
    from ming_sim.applier import atomic
    with atomic(db):
        enter_entry_id = ensure_summon_enter(
            db, night_id, minister_name, method=summon_method, body=enter_body,
        )
        chat_turn_id = db.create_chat_turn(
            state,
            minister_name,
            agno_session_id,
            agno_runs_before,
            night_id=night_id,
        )
        if enter_entry_id:
            db.conn.execute(
                "UPDATE story_ledger_entries SET origin_chat_turn_id = ? WHERE id = ?",
                (int(chat_turn_id), int(enter_entry_id)),
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
        open_n = assert_night_accepts_player_input(db, what="应允暂存")
        nid = int(open_n["id"]) if open_n else None
    else:
        assert_night_accepts_player_input(db, int(nid), what="应允暂存")
    return int(db.mark_pending_night_approved(action_ids, night_id=nid) or 0)
