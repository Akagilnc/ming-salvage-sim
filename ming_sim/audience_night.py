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
import re
import sqlite3
import time
import traceback
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ming_sim.applier import connection_owns_transaction
from ming_sim.db import normalize_office
from ming_sim.error_pack import error_packs_root
from ming_sim.models import GameState
from ming_sim.participant_roster import is_non_person_participant_name

logger = logging.getLogger(__name__)

# ── 引擎侧口令标签常量（ADR 0035：确定性写读）──────────────────────────
TAG_ENTER = "入殿"
TAG_STANDING_ROSTER = "常在员额"
TAG_MINGFA = "明发"  # 夜内定案的旨在公开层账上标已明发（#502 AC6，供 #459 扩散）
_MINGFA_ID_PREFIX = "明发#"  # 明发账挂 directive_id 的结构化标（逐条幂等续跑，#502 L6）

_INNER_COURT_ATTENDANT_OFFICES = frozenset({"信邸内官随驾", "御前近臣"})


def _character_field(character: object, field: str) -> object:
    if isinstance(character, Mapping) or hasattr(character, "keys"):
        try:
            return character[field]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return ""
    return getattr(character, field, "")


def is_inner_court_attendant(character: object) -> bool:
    """按御前近臣的职位识别近侍，不把具体姓名写死。

    开夜常在员额靠它；近臣资格由当前占据的槽位授予，而非职位描述中碰巧出现的词。
    """
    offices = normalize_office(str(_character_field(character, "office") or ""))
    return any(
        office in _INNER_COURT_ATTENDANT_OFFICES
        for office in offices.split(",")
    )


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
_SUMMON_TRAVEL_TONE_PREFIX = "行程语气:"


def _travel_tone_tag(value: object) -> str:
    from ming_sim.issues import normalize_travel_tone
    return f"{_SUMMON_TRAVEL_TONE_PREFIX}{normalize_travel_tone(value)}"


def _travel_tone_from_tags(tags: Sequence[Any]) -> str:
    from ming_sim.issues import TRAVEL_SPEED_BY_TONE, normalize_travel_tone
    tones = [
        normalize_travel_tone(str(tag)[len(_SUMMON_TRAVEL_TONE_PREFIX):])
        for tag in tags if str(tag).startswith(_SUMMON_TRAVEL_TONE_PREFIX)
    ]
    return max(tones or ["常行"], key=TRAVEL_SPEED_BY_TONE.__getitem__)
_SUMMON_ORIGIN_PREFIX = "传召源#"
# 结构化口令判词（引擎只认判词，不重解析散文；非 ACTION_CLUSTERS）
# 留侍／含糊收夜词表已退役（#1812 第5项）。
CMD_CLOSE_NIGHT = "close_night"
CMD_NONE = "none"
_CMD_VERDICTS = frozenset({CMD_CLOSE_NIGHT, CMD_NONE})

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
CLOSE_STEP_FINALIZE = 3
CLOSE_STEPS = (
    CLOSE_STEP_COMMIT_OFFICE,
    CLOSE_STEP_TRANSFER_CANDIDATES,
    CLOSE_STEP_FINALIZE,
)

# 在飞回话：轮询间隔；wait 只消费既有 chat turn/worker 终态，不按 elapsed 伪造失败（#1353 K10a）。
DEFAULT_IN_FLIGHT_POLL_S = 0.05

# 收夜提交的 night-domain kinds（密令应允即落地，不进收夜提交）
# #1842：背书随转译挂载荷、成案继承；不再有 endorsement-bound 水位。
# 草稿案卷前提（office/directive）先提交；consort 等终局效果在 FINALIZE。
_CLOSE_COMMIT_KINDS_OFFICE = frozenset({"office"})
_CLOSE_COMMIT_KINDS_DIRECTIVE = frozenset({"directive"})

# ── 夜内真实盘面直写白名单（ADR 0038 防坑不变式；#506 AC3；#1839 第四类）────────
# 撤回逆转干净的结构性前提：夜内对真实盘面的直写**只有**本表可枚举项，其余结构化
# 后果一律走 ADR 0006 待确认暂存、收夜才提交。每项映射其直写落地的真实盘面表；新增任何
# 夜内直写必须过设计审、显式扩本表，否则撤回逆转不净。
#
# ① 密令落地（应允即落地）。
# ② 转译声明的当场实况（#1821 / ADR 0038 后出注记第四类；原「未在册人物入册」与
#    「召对口关系边事件」并入此类）：人物生死/下狱/革职/在场、文字事实、公开说法、
#    边事件、入册；均带源轮，撤回以前像日志逆转。交办（任免/拨帑/明发）不在此列。
NIGHT_DIRECT_WRITE_WHITELIST: Dict[str, frozenset] = {
    "密令落地": frozenset({"secret_orders", "secret_order_briefs"}),
    "转译声明的当场实况": frozenset({
        "characters", "character_offices",  # 入册 + 生死/下狱/革职
        # set_character_status 的 leverage 重算副作用（#9）；前像快照已含 factions，
        # 撤回与人物状态同逆转——不把副作用另立直写类。
        "factions",
        "relation_edge_events",             # 边事件（含原召对口判官路径）
        "textual_facts",                   # 文字事实（ADR 0156）
        "public_sayings",                  # 公开说法（ADR 0153）
        "story_ledger_entries",            # 在场进出 / 说话人分段
    }),
}

# 夜内结构化写可能触及、且属真实盘面（非暂存/候选层）的表全集——审计据此判越权：落在此集
# 却不在白名单授权的直写 = 越权夜内直写。暂存/候选层（pending_actions/turn_directives）是
# 待确认层、收夜才提交，不算真实盘面直写，不在此集。
_REAL_BOARD_TABLES = frozenset({
    "characters", "character_offices", "dossier_reported_progress", "factions",
    "secret_orders", "secret_order_briefs", "relation_edge_events",
    "textual_facts", "public_sayings", "story_ledger_entries",
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
    """Durable ledger list JSON: vacuum→[]; corrupt/non-list raise (F39)."""
    from ming_sim.db import GameDB

    return list(
        GameDB._loads_stored_json_list(value, surface="story_ledger_entries.json_list")
    )


def _row_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _should_commit(db: Any) -> bool:
    """写前归属：是否由本调用方提交。须在任何 DML 之前调用并缓存结果。

    写后再问 owns_transaction() 会因自身隐式事务而恒 False；与 entity store /
    GameDB 写口同一契约——入口捕获，出口按缓存提交。
    """
    return connection_owns_transaction(db.conn)


def _commit_if_owns(db: Any, *, owns: bool) -> None:
    if owns:
        db.conn.commit()


def write_audience_error_pack(
    *,
    kind: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
    db: Any = None,
    exc: Optional[BaseException] = None,
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
    if exc is not None:
        (pack_dir / "traceback.txt").write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
    if db is not None:
        db.backup_to(str(pack_dir / "save_backup.db"))
    return str(pack_dir.resolve())


def resolve_standing_roster(db: Any) -> List[str]:
    """开夜时动态解析常在员额：在职且 active 的御前近臣槽位持有者。"""
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
        "protagonist_name": str(raw.get("protagonist_name") or ""),
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


def night_scroll_container(night: Dict[str, Any], ledgers: List[Dict[str, Any]], turns: List[Dict[str, Any]]) -> Dict[str, str]:
    return {
        "time_of_day": night["time_of_day"],
        "location": night["location"],
        "audience_type": night_archive_metadata(ledgers, turns)["audience_type"],
    }


def read_night_scroll(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """Read one audience night as the shared live/archive scroll contract.

    #1838 reopen：进出与气氛在场景戏文里，卷轴不再有开场/入殿旁白/收夜/余韵卡；
    分幕线只来自转译声明的 exit（有正文）。口令账仅保留有正文的 exit/scene。
    Memory consumers still read `list_ledger` directly and see every story fact.
    """
    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    ledgers = list_ledger(db, night_id)
    turns = list_chat_turns_for_night(db, night_id)
    # 召法已由引擎作为结构化常量 tag 落在入殿口令账上；它是当前夜容器可用的
    # 真实召对类型来源。抽取账的开放 tags 绝不参与该投影。
    container = night_scroll_container(night, ledgers, turns)

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
    translated: Dict[int, List[tuple[str, Dict[str, Any]]]] = {}
    for entry in ledgers:
        source_id = int(entry.get("source_chat_turn_id") or 0)
        role_tags = [tag.removeprefix("scroll_role:") for tag in entry.get("tags", [])
                     if tag.startswith("scroll_role:")]
        if source_id and len(role_tags) == 1 and role_tags[0] in {"user", "minister", "attendant", "scene"}:
            translated.setdefault(source_id, []).append((role_tags[0], entry))
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
            segments = translated.get(int(turn["id"]), []) if role == "minister" else []
            # Structural, byte-for-byte coverage check: a partial/altered translation
            # stays neutral rather than replacing any part of the original drama.
            if segments and "".join(entry["body"] for _, entry in segments) == content:
                for segment_role, entry in segments:
                    names = entry.get("person_names") or []
                    segment_speaker = "朕" if segment_role == "user" else (names[0] if names else "")
                    events.append((
                        float(int(turn.get("night_seq") or 0)), 21,
                        message(role=segment_role, speaker=segment_speaker,
                                audibility=entry["audibility"], time=row["created_at"],
                                content=entry["body"], beat="aside" if entry["audibility"] == AUDIBILITY_PRIVATE else "dialogue",
                                chat_turn_id=int(turn["id"]), highlights=hl),
                    ))
            else:
                events.append((
                    float(int(turn.get("night_seq") or 0)), 20 + rank,
                    message(role="scene" if role == "minister" else role,
                            speaker=speaker if role == "user" else "",
                            audibility=AUDIBILITY_PUBLIC, time=row["created_at"],
                            content=content, beat="dialogue",
                            chat_turn_id=int(turn["id"])),
                ))
    for entry in ledgers:
        tags = set(entry.get("tags") or [])
        # #1293a：非口令/框架账一律不上 live/档案同源卷轴；禁盯 body。
        if not _is_command_entry(entry):
            continue
        # #1838 reopen：入殿/开夜/收夜/交接/场外传召旁白账不再投影；
        # 只投影有正文的 exit / 其它 scene 口令账。
        if TAG_ENTER in tags:
            continue
        if (
            TAG_ENTER not in tags
            and (TAG_SUMMON_UNSETTLED in tags or TAG_IN_TRANSIT in tags)
            and any(method in tags for method in SUMMON_METHODS)
        ):
            continue
        if TAG_EXIT in tags:
            beat = "exit"
        else:
            beat = "aside" if entry["audibility"] == AUDIBILITY_PRIVATE else "scene"
        if not str(entry.get("body") or "").strip():
            continue
        person = (entry.get("person_names") or [""])[0] if entry.get("person_names") else ""
        speaker = person if beat == "aside" and person else ""
        events.append((
            _entry_order_key(entry), 10,
            message(role="attendant" if beat == "aside" else "scene",
                    speaker=speaker,
                    audibility=entry["audibility"], time=entry["created_at"],
                    content=entry["body"], beat=beat),
        ))

    # 分幕线只来自有正文的 exit（转译 presence exit 或 CLI 告退）。
    facts = sorted(ledgers, key=lambda e: (_entry_order_key(e), int(e["id"])))
    divided_identities: set[tuple[str, float]] = set()
    for index, entry in enumerate(facts):
        tags = set(entry.get("tags") or [])
        is_exit = (
            (_is_command_entry(entry) and TAG_EXIT in tags)
            or entry.get("presence_effect") == PRESENCE_EXIT
        )
        if not (is_exit and str(entry.get("body") or "").strip()):
            continue
        fact_order = _entry_order_key(entry)
        person = (entry.get("person_names") or [""])[0]
        identity_key = (person, fact_order)
        if identity_key in divided_identities:
            continue
        divided_identities.add(identity_key)
        next_name = ""
        for later in facts[index + 1:]:
            later_tags = set(later.get("tags") or [])
            if ((_is_command_entry(later) and TAG_ENTER in later_tags)
                    or later.get("presence_effect") == PRESENCE_ENTER):
                next_name = (later.get("person_names") or [""])[0]
                break
        events.append((fact_order, 90,
            message(role="scene", speaker=next_name, audibility=AUDIBILITY_PUBLIC,
                    time=entry["created_at"], content="", beat="divider", soft_boundary=True),
        ))

    events.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in events]
def _allocate_seq(db: Any, night_id: int) -> int:
    return int(db.allocate_night_seq(int(night_id)))


def _character_status(db: Any, name: str) -> str:
    status, _reason = db.get_character_status(name)
    return str(status or "")


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


def is_pending_source_round(db: Any, night_id: int, chat_turn_id: int, turn: int) -> bool:
    """封夜后只承接同月、同夜仍待补的既有回话，不开放新玩家输入。"""
    if chat_turn_id <= 0:
        return False
    return db.conn.execute(
        "SELECT 1 FROM chat_turns t JOIN game_state g ON g.id=1 "
        "WHERE t.id=? AND t.night_id=? AND t.status='active' "
        "AND t.minister_message_id>0 AND t.extract_status='pending' AND g.turn=?",
        (int(chat_turn_id), int(night_id), int(turn)),
    ).fetchone() is not None


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
    allow_closed_publication: bool = False,
) -> int:
    """追加一条故事账。commit=False 时由外层事务统一提交（开夜原子）。

    抽取账（#501）额外带溯源 `source_chat_turn_id`、机器可读 `presence_effect`
    （''/enter/exit）与时序键 `order_key`（绑定源对话轮原始时序，补跑落回原位）；
    口令/框架账三者取默认（0/''/NULL），读取端 order_key 缺省 COALESCE 回退 seq。

    `origin_chat_turn_id`（#506）：口令账由某一轮 attach 创建时绑该轮 chat_turn_id，供
    撤回按轮删除该轮所产的入殿/告退等口令账；0=开夜/员额/收夜等框架账，不随任一轮撤。

    CLOSING 拒绝玩家侧新账（默认 allow_closing=False）；收夜框架写显式
    allow_closing=True。唯有仍待转译的本月原对话轮可在封夜后补记抽取账。
    """
    owns = _should_commit(db) if commit else False
    night = get_night(db, night_id)
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    # A failed translation belongs to an already persisted source round, not to
    # a new player action. It may finish after the night seals, but never after
    # the month advances or after its source round has been completed/retracted.
    pending_source = False
    if night["status"] in {NIGHT_STATUS_CLOSING, NIGHT_STATUS_CLOSED} and source_chat_turn_id > 0:
        pending_source = (
            int(origin_chat_turn_id) == int(source_chat_turn_id)
            and is_pending_source_round(
                db, int(night_id), int(source_chat_turn_id), int(night["turn"]),
            )
        )
    if night["status"] == NIGHT_STATUS_CLOSED and not (pending_source or allow_closed_publication):
        raise AudienceNightError(
            f"夜已收，不能再落账：{night_id}", code="night_closed",
        )
    if night["status"] == NIGHT_STATUS_CLOSING and not (allow_closing or pending_source):
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
    if allow_closed_publication and not (
        source_chat_turn_id == 0 and origin_chat_turn_id == 0
        and TAG_MINGFA in tag_list
        and any(exact_mingfa_publication_directive_id(t) for t in tag_list)
    ):
        raise AudienceNightError("封夜后仅可补记引擎明发账", code="night_closed")
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
    if owns:
        db.conn.commit()
    return int(cur.lastrowid)


def open_night(
    db: Any,
    state: GameState,
    *,
    time_of_day: str = "",
    location: str = "",
) -> Dict[str, Any]:
    """开夜：夜实体 + 常在员额入殿账，单事务全有或全无。

    #1838 reopen：只记事实（谁常在）；不再写开夜旁白账。气氛由场景 LLM 第一轮戏文写。
    """
    existing = get_open_night(db)
    if existing is not None and existing["status"] == NIGHT_STATUS_OPEN:
        return existing
    if existing is not None and existing["status"] == NIGHT_STATUS_CLOSING:
        # 上一夜收夜中断（closing）。不在此隐式续收：open_night 无 content，
        # 隐式 close_night 会让缺依赖的已应允任免 terminal failed、夜仍被封=丢合法任免。
        # 响亮停住——续收必须走携 content 的显式 close/resume（resolve_turn/advance/
        # auto_close_open_night），不准开新夜、不准封夜。
        raise AudienceNightError(
            f"上一夜收夜未完（closing），须先携 content 显式续收再开新夜：{int(existing['id'])}",
            code="night_closing_incomplete",
            detail={"night_id": int(existing["id"])},
        )

    # 时地兜底在落库前统一定死（单一 seam）：真实入口缺玩家选值时也持久非空、可读（#498 AC）。
    time_of_day = str(time_of_day or "").strip() or DEFAULT_TIME_OF_DAY
    location = str(location or "").strip() or DEFAULT_LOCATION

    roster = resolve_standing_roster(db)
    owns = _should_commit(db)

    # 原子：实体 + 员额入殿账，SAVEPOINT 全有或全无。
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
        for name in roster:
            # 常在员额入殿账 body 恒空——只驱动在场，不写旁白。
            append_ledger_entry(
                db, night_id,
                person_names=[name],
                audibility=AUDIBILITY_PUBLIC,
                body="",
                tags=[TAG_ENTER, TAG_STANDING_ROSTER],
                check_dead=True,
                commit=False,
            )
        db.conn.execute(f"RELEASE SAVEPOINT {sp}")
        if owns:
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
    audibility: str = AUDIBILITY_PUBLIC,
    origin_chat_turn_id: int = 0,
    origin_ref: str = "",
    commit: bool = True,
) -> int:
    """落入殿事实账。#1838 reopen：正文恒空——入殿气氛由场景戏文写，不写旁白句。"""
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("宣召人名不能为空", code="empty_person")
    method = _validate_summon_method(method, default=METHOD_XUANRU)
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=audibility,
        body="",
        tags=[TAG_ENTER, method],
        check_dead=True,
        origin_chat_turn_id=origin_chat_turn_id,
        origin_ref=origin_ref,
        commit=commit,
    )


def list_in_flight_chat_turns(db: Any, night_id: int) -> List[Dict[str, Any]]:
    return db.list_in_flight_chat_turns(night_id=int(night_id))


def wait_in_flight_clear(
    db: Any,
    night_id: int,
    *,
    poll_s: float | None = None,
    write_gate: Any = None,
) -> None:
    """等在飞回话完成；只依 chat turn/worker 终态放行，不按 elapsed 伪造失败。

    #1353 K10a / ADR 0149：工人落 active/failed/interrupted 终态即续跑。
    真挂死终结属 provider/worker 接缝（硬超时 → 失败终态 → 本等待自然解除）；
    #1353 r7：每次轮询短持 write_gate 读共享 conn，sleep 必在闸外（禁持锁睡眠）。
    """
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
    owns = _should_commit(db)
    assignments = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [int(night_id)]
    db.conn.execute(
        f"UPDATE audience_nights SET {assignments} WHERE id = ?",
        params,
    )
    _commit_if_owns(db, owns=owns)


def _commit_night_approved(
    db: Any,
    state: GameState,
    night_id: int,
    *,
    kinds: frozenset,
    content: Any,
    directive_status: str = "draft",
) -> List[Dict[str, object]]:
    """收夜提交本夜已应允白名单。沿用 commit_pending_actions 既有 terminal 语义：
    落得了标 committed；业务拒收/软拒收标 failed；真异常留 pending 并上抛
    （#1853：原轮/月链 error_pack 与失败路径承接，不另造 failed 专属传输）。"""
    rows: List[Dict[str, object]] = []
    for kind in sorted(kinds):
        rows.extend(db.list_night_approved_pending(int(night_id), kind=kind))
    if not rows:
        return []
    action_ids = [int(r["id"]) for r in rows]
    from ming_sim.applier import RejectionCollector, mirror_rejections_after_commit
    from ming_sim.error_pack import rejections_jsonl_path
    collector = RejectionCollector()
    applied = db.commit_pending_actions(
        state,
        content=content,
        action_ids=action_ids,
        directive_status=directive_status,
        rejection_collector=collector,
    )
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return list(applied or [])


def publish_night_directives(db: Any, night_id: int) -> None:
    """成案后以同一入口幂等记本夜已成案拟旨的明发账。"""
    # 夜内定案的旨落公开层账、标已明发（#502 AC6）；#1842 背书已随载荷继承。
    already_ids = {
        str(did)
        for did in engine_command_mingfa_publication_ids(list_ledger(db, night_id))
    }
    _mingfa_candidates = db.conn.execute(
        """
        SELECT td.id AS directive_id, td.actor, td.text,
               MIN(d.id) AS dossier_id
        FROM pending_actions pa
        JOIN turn_directives td ON td.source_pending_action_id = pa.id
        JOIN decree_dossiers d ON d.pending_action_id = pa.id
        WHERE pa.night_id = ? AND pa.kind = 'directive'
          AND pa.status = 'committed'
        GROUP BY td.id, td.actor, td.text
        ORDER BY td.id
        """,
        (int(night_id),),
    ).fetchall()
    for _pd in _mingfa_candidates:
        _did_int = int(_pd["directive_id"] or 0)
        _did = str(_did_int)
        if not _did_int or _did in already_ids:
            continue
        dossier_id = int(_pd["dossier_id"] or 0)
        if dossier_id <= 0:
            continue
        origin_ref = f"dossier:{dossier_id}"
        append_ledger_entry(
            db, night_id,
            person_names=[str(_pd["actor"] or "")] if _pd["actor"] else [],
            audibility=AUDIBILITY_PUBLIC,
            body=str(_pd["text"] or ""),
            tags=[TAG_MINGFA, mingfa_publication_tag(_did_int)],
            check_dead=False,
            allow_closing=True,
            allow_closed_publication=True,
            origin_ref=origin_ref,
        )


def commit_late_night_approved(
    db: Any, state: GameState, *, content: Any,
    llm_config: Any = None, write_gate: Any = None,
) -> None:
    """过月 join 后沿收夜提交、明发入口补完迟到应允（#1842：背书随载荷，不另补批）。"""
    nights = db.conn.execute(
        "SELECT DISTINCT n.id FROM audience_nights n "
        "JOIN pending_actions pa ON pa.night_id=n.id "
        "WHERE n.turn=? AND n.status=? AND "
        "pa.status='pending' AND pa.night_approved=1 ORDER BY n.id",
        (int(state.turn), NIGHT_STATUS_CLOSED),
    ).fetchall()
    if not nights:
        return
    gate = _gate_cm(write_gate)
    for night in nights:
        nid = int(night["id"])
        with gate:
            for kinds in (
                _CLOSE_COMMIT_KINDS_OFFICE,
                _CLOSE_COMMIT_KINDS_DIRECTIVE,
            ):
                _commit_night_approved(
                    db, state, nid, kinds=kinds, content=content,
                )
            publish_night_directives(db, nid)


def _catch_up_night_translations(
    db: Any, night_id: int, *, llm_config: Any, write_gate: Any,
    game_state: GameState, translate_fn: Any = None, write_queue: Any = None,
) -> None:
    """收夜补跑转译待补（#1898：单次收夜只跑一次的唯一实现）。

    ADR 0036 后出注记 / #1842：待补不再 fail-closed 中止收夜。join/补跑后仍
    pending 的留给过月 join / 原地重试（0157）。

    #1898：调用方只跑一次——OPEN 冻结前那次；「进来时已是 CLOSING」的崩溃
    恢复口是另一次收夜尝试（那是恢复，不是同次第二处重复调用）。首次补跑耗尽
    时该轮保持待补，**不由本函数或任何同次收夜路径再自动调一次模型**——补跑权
    归 #1846 的玩家重试与过月 join。

    ``extract_status`` 由转译通路独占；未完成的轮次留给过月 join /
    原地重试，不再保留旧故事抽取通路。

    write_gate 必须是调用方原始锁（或 None）——禁传入 _gate_cm(nullcontext)。
    """
    # catch_up 契约：单轮失败标 pending、不抛；代码异常按 ADR 0005 上抛。
    # translate_fn=None 走默认 runner（#1842：收夜补跑不因缺注入而跳过）。
    if llm_config is None or write_gate is None or write_queue is None:
        return
    from ming_sim.audience_translation import catch_up_pending_translations
    catch_up_pending_translations(
        db, game_state,
        night_id=int(night_id),
        llm_config=llm_config,
        translate_fn=translate_fn,
        write_gate=write_gate,
        write_queue=write_queue,
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
    auto: bool = False,
    crash_after_step: Optional[int] = None,
    on_step: Optional[Callable[[int, Dict[str, Any]], None]] = None,
    on_closing: Optional[Callable[[], None]] = None,
    llm_config: Any = None,
    write_gate: Any = None,
    translate_fn: Any = None,
    write_queue: Any = None,
) -> Dict[str, Any]:
    """收夜：待补转译 → 短写前提 → 短写终局（#1842：背书随转译，无夜级批）。

    #1838 reopen：不再有收夜旁白 LLM 调用与收夜账；收讫只看 audience_nights.status。

    分相：
    1. 待补转译（无 DB transaction）：OPEN 期在冻结 CLOSING **之前**补跑；
       进来时已是 CLOSING 的崩溃恢复口在 on_closing **之后**补跑。两条分支
       互斥，同一次收夜不会补跑第二轮。
    2. 短写持 write_gate：提交 draft 前提（office → directive）。
    3. 短写持 write_gate：终局效果、明发、CLOSED。

    待补转译失败不阻断收夜：该轮保持待补（status/diagnostic 仍可查），由 #1846
    玩家重试或过月 join 承接，同次收夜不再自动调模型。
    """
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
    if night is None:
        raise AudienceNightError(f"夜不存在：{night_id}", code="night_not_found")
    if night["status"] == NIGHT_STATUS_CLOSED:
        return {"closed": True, "night_id": int(night_id), "already": True}

    # #1898：同次收夜只补跑一次。OPEN 分支在冻结 CLOSING 前补跑；进来时已是
    # CLOSING 的崩溃恢复口在 on_closing 后补跑（那是另一次收夜尝试）。两条分支
    # 互斥，收尾处不再有第二处调用——耗尽的那轮保持待补，交 #1846 玩家重试 /
    # 过月 join，不由同次收夜再自动调一次模型。
    if night["status"] == NIGHT_STATUS_OPEN:
        wait_in_flight_clear(
            db, night_id, write_gate=write_gate,
        )
        _catch_up_night_translations(
            db, int(night_id), llm_config=llm_config, write_gate=write_gate,
            game_state=state, translate_fn=translate_fn, write_queue=write_queue,
        )
        with gate:
            _set_night_fields(
                db, night_id, status=NIGHT_STATUS_CLOSING,
            )
            if on_closing is not None:
                on_closing()
            night = get_night(db, night_id)
        assert night is not None
    else:
        with gate:
            if on_closing is not None:
                on_closing()
            night = get_night(db, night_id) or night
        _catch_up_night_translations(
            db, int(night_id), llm_config=llm_config, write_gate=write_gate,
            game_state=state, translate_fn=translate_fn, write_queue=write_queue,
        )

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
        _commit_night_approved(
            db, state, int(night_id),
            kinds=_CLOSE_COMMIT_KINDS_OFFICE,
            content=content,
        )
        if cursor < CLOSE_STEP_COMMIT_OFFICE:
            _advance(CLOSE_STEP_COMMIT_OFFICE)

        _commit_night_approved(
            db, state, int(night_id),
            kinds=_CLOSE_COMMIT_KINDS_DIRECTIVE,
            content=content,
            directive_status="draft",
        )
        if cursor < CLOSE_STEP_TRANSFER_CANDIDATES:
            _advance(CLOSE_STEP_TRANSFER_CANDIDATES)

    # ── Phase 3: short writes — final effects, 明发, CLOSED ──
    with gate:
        night = get_night(db, night_id) or night
        cursor = int(night["close_commit_cursor"] or 0)
        if cursor < CLOSE_STEP_TRANSFER_CANDIDATES:
            fault_cursor = int(cursor)
            _set_night_fields(
                db, night_id, status=NIGHT_STATUS_OPEN, closed_at=None,
                close_commit_cursor=0,
            )
            raise AudienceNightError(
                f"收夜案卷前提未落定（night_id={int(night_id)}, cursor={fault_cursor}）",
                code="close_prerequisites_incomplete",
                detail={"night_id": int(night_id), "cursor": fault_cursor},
            )
        if cursor < CLOSE_STEP_FINALIZE:
            commit_fresh_summons_for_night(
                db, state, int(night_id), content=content,
            )
            publish_night_directives(db, int(night_id))
            # #1838 reopen：不写收夜旁白账与代码兜底句；收讫以 status=closed 为准。
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
    crash_after_step: Optional[int] = None,
    llm_config: Any = None,
    write_gate: Any = None,
    on_closing: Optional[Callable[[], None]] = None,
) -> Optional[Dict[str, Any]]:
    """颁诏/过回合前：有开夜则顺势收夜；无开夜返回 None。

    write_gate 应为真实 runtime Lock（或 CLI 下 None）；close_night 只在短写阶段持锁。
    调用方不得在外层持同一把非重入锁再传入 nullcontext。
    """
    with _gate_cm(write_gate):
        open_n = get_open_night(db)
    if open_n is None:
        return None
    return close_night(
        db, state,
        night_id=int(open_n["id"]),
        content=content,
        auto=True,
        crash_after_step=crash_after_step,
        llm_config=llm_config,
        write_gate=write_gate,
        on_closing=on_closing,
    )


def ensure_open_night_for_audience(
    db: Any,
    state: GameState,
    *,
    time_of_day: str = "",
    location: str = "",
) -> Dict[str, Any]:
    return open_night(db, state, time_of_day=time_of_day, location=location)


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
        # Story-ledger list columns: reuse _json_list → _loads_stored_json_list (F39).
        # Wrong object shape must not become empty unsettled-summon facts.
        tags = _json_list(row["tags"])
        if TAG_SUMMON_UNSETTLED not in tags or TAG_SUMMON_SETTLED in tags:
            continue
        origin = next(
            (str(tag)[len(_SUMMON_ORIGIN_PREFIX):] for tag in tags
             if str(tag).startswith(_SUMMON_ORIGIN_PREFIX)),
            "",
        )
        names = _json_list(row["person_names"])
        if not origin or not names:
            continue
        person_name = str(names[0])
        projected.append({
            "entry_id": int(row["id"]), "night_id": int(row["night_id"]),
            "person_name": person_name, "origin_id": origin,
            "kind": _project_unsettled_summon_kind(db, tags, person_name),
            **({"travel_tone": _travel_tone_from_tags(tags)}
               if any(str(tag).startswith(_SUMMON_TRAVEL_TONE_PREFIX) for tag in tags)
               else {}),
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
    owns = _should_commit(db)
    for item in items:
        entry_id = int(item["entry_id"])
        row = db.conn.execute(
            "SELECT tags FROM story_ledger_entries WHERE id=?", (entry_id,)
        ).fetchone()
        if row is None:
            continue
        tags = _json_list(row["tags"])
        if TAG_IN_TRANSIT in tags:
            continue
        tags.append(TAG_IN_TRANSIT)
        db.conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), entry_id),
        )
    if owns:
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
    owns = _should_commit(db) if commit else False
    origin = str(origin_id or "").strip()
    matches = [item for item in list_unsettled_summons(db) if item["origin_id"] == origin]
    if not matches:
        return False
    for item in matches:
        row = db.conn.execute(
            "SELECT tags FROM story_ledger_entries WHERE id=?", (item["entry_id"],)
        ).fetchone()
        tags = _json_list(row["tags"])
        tags = [tag for tag in tags if tag != TAG_SUMMON_UNSETTLED]
        tags.append(TAG_SUMMON_SETTLED)
        db.conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), item["entry_id"]),
        )
    if owns:
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
    origin_id: object = "",
    origin_chat_turn_id: int = 0,
    travel_tone: str = "常行",
) -> int:
    """落 fresh 场外传召账；带 origin 时，同一人物同一未结 origin 幂等。

    不同 origin 各留独立 ledger 行及各自 origin_chat_turn_id，供逐轮撤回；
    收夜启程仍由 commit_fresh_summons_for_night 按人聚合一次。
    机器事实只在 tags；戏文由场景 LLM 写。
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
    tags = [method, _travel_tone_tag(travel_tone)]
    if origin_tag:
        tags.extend([TAG_SUMMON_UNSETTLED, origin_tag])
    return append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body="",
        tags=tags,
        origin_chat_turn_id=int(origin_chat_turn_id or 0),
    )


def update_summon_travel_tone(
    db: Any,
    *,
    night_id: int,
    person_name: str,
    travel_tone: str,
    origin_chat_turn_id: int,
) -> int:
    """更新本夜该人未结传召账的行程语气（#1837 reopen / ADR 0096）。

    只改 tags 上的语气前缀，不另起行；无未结传召 → KeyError。
    """
    owns = _should_commit(db)
    name = str(person_name or "").strip()
    if not name:
        raise ValueError("传召人名不能为空")
    from ming_sim.issues import normalize_travel_tone
    tone = normalize_travel_tone(travel_tone)
    target = None
    for item in list_unsettled_summons(db):
        if int(item.get("night_id") or 0) != int(night_id):
            continue
        if item.get("person_name") != name:
            continue
        row = db.conn.execute(
            "SELECT origin_chat_turn_id FROM story_ledger_entries WHERE id=?",
            (int(item["entry_id"]),),
        ).fetchone()
        if row is None or int(row["origin_chat_turn_id"] or 0) != int(origin_chat_turn_id):
            continue
        target = item
        break
    if target is None:
        raise KeyError(f"本夜无此人未结传召：{name}")
    entry_id = int(target["entry_id"])
    row = db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE id=?",
        (entry_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"传召账不存在：{entry_id}")
    tags = [str(t) for t in _json_list(row["tags"])]
    tags = [t for t in tags if not str(t).startswith(_SUMMON_TRAVEL_TONE_PREFIX)]
    tags.append(_travel_tone_tag(tone))
    db.conn.execute(
        "UPDATE story_ledger_entries SET tags=? WHERE id=?",
        (json.dumps(tags, ensure_ascii=False), entry_id),
    )
    if owns:
        db.conn.commit()
    return entry_id


def ensure_inactive_office_summon(
    db: Any, pending_id: int, person_name: str, *, night_id: int,
    origin_chat_turn_id: int = 0,
) -> int:
    """Ensure the pre-close, inactive half of an appointment-plus-summon intent.

    Binds origin_chat_turn_id so #506 undo of the staging turn erases this row;
    still-inactive origins are also discarded on pending reject/withdraw.
    """
    origin = f"office:{int(pending_id)}"
    existing = _ledger_by_origin_ref(db, origin)
    if existing is not None:
        return int(existing["id"])
    if int(night_id) <= 0:
        raise AudienceNightError("任命后传召须在召对夜内落账", code="night_not_found")
    return append_ledger_entry(
        db, int(night_id), person_names=[str(person_name).strip()],
        tags=[METHOD_CHUANZHAO, _summon_origin_tag(origin)], origin_ref=origin,
        origin_chat_turn_id=int(origin_chat_turn_id or 0),
    )


def discard_inactive_office_summon(db: Any, pending_id: int) -> bool:
    """Delete still-inactive office:<pending_id> origin; refuse activated history.

    Matches withdraw/drop owns_transaction: do not commit over a caller-owned
    BEGIN/atomic, so outer rollback can restore pending + origin together.
    """
    conn = db.conn
    owns_transaction = connection_owns_transaction(conn)
    origin = f"office:{int(pending_id)}"
    entry = _ledger_by_origin_ref(db, origin)
    if entry is None:
        return False
    tags = list(entry.get("tags") or [])
    # Activated / in-transit / settled rows are post-promulgation history — keep.
    if TAG_SUMMON_UNSETTLED in tags or TAG_IN_TRANSIT in tags or TAG_SUMMON_SETTLED in tags:
        return False
    conn.execute(
        "DELETE FROM story_ledger_entries WHERE id=?",
        (int(entry["id"]),),
    )
    if owns_transaction:
        conn.commit()
    return True


def activate_office_summon(db: Any, pending_id: int) -> Optional[Dict[str, Any]]:
    """Activate the original inactive row; never append to a closed night."""
    origin = f"office:{int(pending_id)}"
    entry = _ledger_by_origin_ref(db, origin)
    if entry is None:
        return None
    tags = list(entry["tags"])
    if TAG_SUMMON_UNSETTLED not in tags:
        tags.append(TAG_SUMMON_UNSETTLED)
        db.conn.execute(
            "UPDATE story_ledger_entries SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), int(entry["id"])),
        )
    return {**entry, "tags": tags}


def commit_fresh_summons_for_night(
    db: Any,
    state: GameState,
    night_id: int,
    *,
    content: Any = None,
) -> List[str]:
    """收夜按人一次 canonical 启程；成功后标在途，origin 保持未结候见关联。

    已在同一 beizhili 旅程只附加 origin 并标在途；异目的地仍拒。
    """
    pending = [
        item for item in list_unsettled_summons(db)
        if item["kind"] == "fresh" and int(item["night_id"]) == int(night_id)
    ]
    if not pending:
        return []
    from ming_sim.decree import atomic_and_reload
    from ming_sim.issues import apply_person_changes_only

    # 历史多 origin 未结账：按人分组，apply 一次后全部标在途（兼容重试）。
    by_person: Dict[str, List[Dict[str, Any]]] = {}
    for item in pending:
        by_person.setdefault(str(item["person_name"]), []).append(item)

    from ming_sim.matching import is_capital_location

    origins: List[str] = []
    with atomic_and_reload(db, state, content=content):
        for person_name, items in by_person.items():
            row = db.conn.execute(
                "SELECT location, transit_to, status FROM characters WHERE name=?",
                (person_name,),
            ).fetchone()
            current_transit = str(row["transit_to"] or "").strip() if row is not None else ""
            location = str(row["location"] or "").strip() if row is not None else ""
            if current_transit:
                if current_transit != "beizhili":
                    raise AudienceNightError(
                        f"传召启程未落定：{person_name} 已在途赴 {current_transit}",
                        code="summon_departure_rejected",
                        detail={
                            "origin_id": str(items[0]["origin_id"]),
                            "transit_to": current_transit,
                        },
                    )
                # Same beizhili journey: attach origins only, no second departure write.
                _mark_summon_entries_in_transit(db, items)
                for item in items:
                    origins.append(str(item["origin_id"]))
                continue
            # 已在京且无在途：复用 capital matcher + 在途 tag → waiting 投影，
            # 不调同地行止 applier（#672 / #671 候见不变式）。
            if is_capital_location(location):
                _mark_summon_entries_in_transit(db, items)
                for item in items:
                    origins.append(str(item["origin_id"]))
                continue
            from ming_sim.issues import TRAVEL_SPEED_BY_TONE, normalize_travel_tone
            travel_tone = max(
                (normalize_travel_tone(item.get("travel_tone")) for item in items),
                key=TRAVEL_SPEED_BY_TONE.__getitem__,
            )
            applied = apply_person_changes_only(
                db,
                state,
                [{
                    "name": person_name,
                    "动作": "行止",
                    "transit_to": "beizhili",
                    "行程语气": travel_tone,
                    # Canonical applier only admits its established provenance vocabulary;
                    # the summon origin remains machine-linked in the story ledger.
                    "origin_ref": "盘面自发",
                }],
                content=content,
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
    origin_id: object = "",
    origin_chat_turn_id: int = 0,
) -> int:
    """落传召在途账；带 origin 时，同一人物同一未结 origin 幂等。

    机器事实只在 tags；戏文由场景 LLM 写。
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
        body="",
        tags=tags,
        origin_chat_turn_id=int(origin_chat_turn_id or 0),
    )


def dismiss_from_audience(
    db: Any,
    person_name: str,
    *,
    night_id: Optional[int] = None,
    origin_chat_turn_id: int = 0,
    allow_closing: bool = False,
) -> Optional[int]:
    """「令 X 退下」口令：确定性落告退账，即时反映于名单查询。

    不在场者令退 = 幂等 no-op（不落账、返 None）；名不填 → 响亮 empty_person。
    #1838 reopen：正文恒空（无旁白调用）；在场由 TAG_EXIT 驱动，戏文由场景 LLM 写。

    `origin_chat_turn_id`（#506 L1）：tool 触发的令退发生在某一对话轮内时绑该轮 chat_turn_id，
    使撤回本轮据 origin 删掉告退账、令退者在场复原。0=不属某轮的独立令退。
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
    return append_ledger_entry(
        db, int(nid),
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body="",
        tags=[TAG_EXIT],
        check_dead=False,
        origin_chat_turn_id=origin_chat_turn_id,
        allow_closing=allow_closing,
    )


def normalize_audience_command_verdict(raw: Any) -> str:
    """判词缝归一：只放行封闭判词，其余 → none（毒化/坏 shape 零机械面）。"""
    if isinstance(raw, str) and raw in _CMD_VERDICTS:
        return raw
    return CMD_NONE


def recognize_audience_command(message: str) -> str:
    """显式退朝口令结构化判词。

    确定性封闭集 COURT_BREAK；引擎不重解析散文。
    留侍／含糊收夜词表已退役，不在此识别。
    不进 ACTION_CLUSTERS；非第二 parser（无自由散文正则启发）。
    """
    from ming_sim.constants import COURT_BREAK_COMMANDS

    text = str(message or "").strip()
    if not text:
        return CMD_NONE
    lowered = text.lower()
    if lowered in COURT_BREAK_COMMANDS or text in COURT_BREAK_COMMANDS:
        return CMD_CLOSE_NIGHT
    return CMD_NONE


# #1836：一夜一场入口的「宣 X」口令——封闭前缀 + 人名片段；引擎落入殿账（ADR 0037），
# 不另立 summon 动作类型。后缀可有可无（「宣王绍徽」与「宣王绍徽来」同形）。
_XUAN_COMMAND_RE = re.compile(
    r"^(?:传召|传|召|宣|叫|带)(.{1,12}?)(?:来|到|入殿|上殿|面圣|见我)?$"
)

# 场景对话轮挂名：整场戏文不绑单人；归档 involved_people 投影会滤非人（#1331）。
SCENE_CHAT_SPEAKER = "殿上"


def recognize_xuan_command(message: str) -> Optional[str]:
    """解析皇帝「宣 X」口令，返回人名片段；非宣召口令 → None。

    #1836 / ADR 0035 / 0037：玩家口令确定性落账的前半——只认封闭前缀形状，
    不靠自由散文启发；人名解析交给调用方 match。
    """
    text = str(message or "").strip()
    if not text:
        return None
    # 显式退朝口令优先，避免被宣召形状误吞。
    if recognize_audience_command(text) != CMD_NONE:
        return None
    m = _XUAN_COMMAND_RE.match(text)
    if not m:
        return None
    name = str(m.group(1) or "").strip()
    return name or None


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


def person_night_experience(
    db: Any, night_id: int, person_name: str,
) -> List[Dict[str, Any]]:
    """人物经历：在场公开所闻，加本人说出的私密条目。

    只有大臣／近臣分段的首位人名是说话人；场景分段仅列涉及人。
    """
    name = str(person_name or "").strip()
    if not name:
        return []
    audible_ids = {entry["id"] for entry in audible_entries_for(db, int(night_id), name)}
    return [
        entry for entry in list_ledger(db, int(night_id))
        if entry["id"] in audible_ids
        or (entry.get("audibility") == AUDIBILITY_PRIVATE
            and any(tag in {"scroll_role:minister", "scroll_role:attendant"}
                    for tag in entry.get("tags", []))
            and (entry.get("person_names") or [None])[0] == name)
    ]


def set_night_protagonist(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    reason: str = "translation",
    commit: bool = True,
) -> str:
    """写下本夜御前主角（#1838 / ADR 0158 决定 4）。

    ``reason`` 仅作调用语义标注（``xuan`` = 皇帝亲口宣 X 当场先切；
    ``translation`` = 转译声明），不进库、不驱动规则。代码只存声明/口令给出
    的人名，不从戏文散文解析（ADR 0142）。
    """
    owns = _should_commit(db) if commit else False
    name = str(person_name or "").strip()
    if not name:
        raise AudienceNightError("御前主角人名不能为空", code="empty_protagonist")
    nid = int(night_id)
    night = get_night(db, nid)
    if night is None:
        raise AudienceNightError(f"夜不存在：{nid}", code="night_not_found")
    db.conn.execute(
        "UPDATE audience_nights SET protagonist_name=? WHERE id=?",
        (name, nid),
    )
    if owns:
        db.conn.commit()
    return name
def reproject_night_protagonist(db: Any, night_id: int) -> str:
    """按存活源轮时序重投影夜当前主角；调用方负责事务提交。"""
    row = db.conn.execute(
        "SELECT protagonist_name FROM chat_turns WHERE night_id=? "
        "AND status NOT IN ('undone','failed') AND protagonist_name != '' "
        "ORDER BY id DESC LIMIT 1",
        (int(night_id),),
    ).fetchone()
    name = str(row["protagonist_name"] or "") if row is not None else ""
    db.conn.execute(
        "UPDATE audience_nights SET protagonist_name=? WHERE id=?",
        (name, int(night_id)),
    )
    return name


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
    if not name:
        return ""
    nid = night_id
    if nid is None:
        open_n = get_open_night(db)
        if open_n is None:
            return ""
        nid = int(open_n["id"])
    bodies: List[str] = []
    for entry in audible_entries_for(db, int(nid), name):
        # Free prose body: preserve raw; strip only emptiness (#1834 F16).
        body = str(entry.get("body") or "")
        if body.strip():
            bodies.append(body)
    if not bodies:
        return ""
    return SCENE_RECAP_HEADER + "\n" + "\n".join(bodies)


def _is_command_entry(entry: Dict[str, Any]) -> bool:
    """口令/框架账（发起/进出/收夜/常在员额）由引擎侧确定性写入、`source_chat_turn_id==0`；
    抽取账（`>0`）的 tags 是 LLM 开放叙事标签。引擎口令常量标（TAG_ENTER/TAG_EXIT…）
    只在口令账上机器承重——抽取账开放 tags 不得驱动机器态（ADR 0035：在场等机器承重态输入
    不解析自由文本；否则 LLM 写「入殿」旁路死账、写「收夜」旁路收夜账幂等）。"""
    return int(entry.get("source_chat_turn_id") or 0) == 0


def persons_present_tonight(db: Any, night_id: int) -> set[str]:
    """当前在场名单 = 夜末在场态（#501 AC2/AC9）。

    与 `present_names_at` 共用单一在场步进 `_presence_delta`（ADR 0035 R2）——进=口令账
    TAG_ENTER（宣入/常在员额）**或**抽取账 presence_effect='enter'；出=口令账 TAG_EXIT
    （令退）**或**抽取账 presence_effect='exit'。抽取账开放 tags 不驱动在场（机器承重态不
    解析自由文本，与 settle `check_dead=(effect==enter)` 对称）。派生只认已落账（list_ledger
    只返回已 settle 的账），故待补期间缺账 = 尚未发生、不猜（AC9）；补账落地后自然校正。
    """
    return present_names_at(db, int(night_id))


def presence_roster(db: Any, night_id: int) -> List[Dict[str, Any]]:
    """Project everyone who entered this night, in first-entry order, with current presence."""
    present: set[str] = set()
    ordered: List[str] = []
    seen: set[str] = set()
    for entry in list_ledger(db, int(night_id)):
        delta = _presence_delta(entry)
        names = [str(name) for name in entry.get("person_names") or []]
        if delta == PRESENCE_ENTER:
            for name in names:
                if name not in seen:
                    seen.add(name)
                    ordered.append(name)
        _apply_presence(present, entry)
    return [{"name": name, "present": name in present} for name in ordered]


def ensure_summon_enter(
    db: Any,
    night_id: int,
    person_name: str,
    *,
    method: str = METHOD_XUANRU,
    origin_chat_turn_id: int = 0,
    origin_ref: str = "",
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
        db, night_id, name, method=method,
        origin_chat_turn_id=origin_chat_turn_id,
        origin_ref=origin_ref,
        commit=commit,
    )


def rescript_summon_origin_ref(source_turn: int, idx: int, revision_round: int) -> str:
    """#657 D.0 origin 公式唯一真源。"""
    return f"rescript_draft:{int(source_turn)}:{int(idx)}:summon:r{int(revision_round)}"


def rescript_summon_origin_consumed(
    entry: Optional[Mapping[str, Any]],
) -> bool:
    """#1838 reopen / #657：已消费 ≔ origin 行存在 ∧ TAG_ENTER∈tags。

    不再依赖旁白正文；入殿账正文恒空。
    """
    if entry is None:
        return False
    tags = [str(t) for t in _json_list(entry.get("tags"))]
    return TAG_ENTER in tags


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
    """#1838 reopen / #657：批红召见只落入殿事实账。

    返回 {entry_id, night_id, consumed: bool}。
    已消费 ≔ origin_ref 行存在 ∧ TAG_ENTER；不再建 generating 对话轮、不依赖旁白正文。
    幂等靠 origin_ref UNIQUE。
    """
    from ming_sim.applier import atomic

    name = str(person_name or "").strip()
    origin = str(origin_ref or "").strip()
    if not name or not origin:
        raise AudienceNightError("prepare_rescript_summon 缺 name/origin", code="bad_args")

    existing = _ledger_by_origin_ref(db, origin)
    if existing is not None:
        return {
            "entry_id": int(existing["id"]),
            "chat_turn_id": int(existing.get("origin_chat_turn_id") or 0),
            "night_id": int(existing["night_id"]),
            "consumed": rescript_summon_origin_consumed(existing),
        }

    try:
        with atomic(db):
            night = get_open_night(db)
            if night is None or str(night.get("status") or "") != NIGHT_STATUS_OPEN:
                night = open_night(
                    db, state,
                    time_of_day=time_of_day, location=location,
                )
            night_id = int(night["id"])
            entry_id = summon_enter(
                db, night_id, name,
                method=method,
                origin_ref=origin,
                commit=False,
            )
        return {
            "entry_id": int(entry_id),
            "chat_turn_id": 0,
            "night_id": night_id,
            "consumed": True,
        }
    except sqlite3.IntegrityError as exc:
        unique_codes = {
            getattr(sqlite3, "SQLITE_CONSTRAINT_UNIQUE", None),
            getattr(sqlite3, "SQLITE_CONSTRAINT", None),
        }
        unique_codes.discard(None)
        err_code = getattr(exc, "sqlite_errorcode", None)
        if unique_codes and err_code not in unique_codes:
            raise
        again = _ledger_by_origin_ref(db, origin)
        if again is None:
            raise
        return {
            "entry_id": int(again["id"]),
            "chat_turn_id": int(again.get("origin_chat_turn_id") or 0),
            "night_id": int(again["night_id"]),
            "consumed": rescript_summon_origin_consumed(again),
        }


def mark_actions_night_approved(
    db: Any, action_ids: Sequence[int], *, night_id: Optional[int] = None,
) -> int:
    """对话应允时：把暂存标为本夜已应允，收夜再提交（密令除外，调用方分流）。"""
    nid = night_id
    if nid is None:
        open_n = assert_night_accepts_player_input(db, what="应允暂存")
        nid = int(open_n["id"]) if open_n else None
    else:
        assert_night_accepts_player_input(db, int(nid), what="应允暂存")
    return int(db.mark_pending_night_approved(action_ids, night_id=nid) or 0)
