"""GameSession：CLI 与 Web 共用的统一回合流转层。L8。

不含 input()/print()——只持有状态、跑底层逻辑、返回 dataclass。
召见对话的 tool 截获、拟旨 draft 流转、诏书结算都收在这里，
CLI 和 Web 各自只做 I/O 包装。
"""

from __future__ import annotations

import json
import inspect
import re
import sqlite3
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ming_sim.agents import bind_content as _bind_agents
from ming_sim.agents import _dump_llm_messages
from ming_sim.constants import TURN_UNIT
from ming_sim.content import GameContent
from ming_sim.context import (
    bind_content as _bind_context,
    character_from_name,
    match_minister_from_text,
    victory_status,
)
from ming_sim.db import (
    GameDB,
    infer_office_type_from_office,
    normalize_office,
    resolve_office_type_preserving_title,
)
from ming_sim.decree import (
    ResolveResult,
    _provenance_from_stored,
    _requires_full_settlement,
    advance_without_edict,
    resolve_decisions_phase2,
    resolve_directives,
    resolve_settling_recovery,
    write_decree_with_agno,
)
from ming_sim.error_pack import clear_for_resimulation
from ming_sim.issues import bind_content as _bind_issues
from ming_sim.issues import sync_opening_legacies
from ming_sim.knowledge import render_character_knowledge
from ming_sim.mindreading import is_inner_court_attendant
from ming_sim.llm_model import create_agno_db, extract_agent_text, verify_llm_available
from ming_sim.models import Character, CourtContext, GameState, LLMConfig, is_vassal_prince
from ming_sim.paths import user_data_path
from ming_sim.registry import MinisterRegistry, bind_content as _bind_registry
from ming_sim.settlement_payload import bind_decisions_to_candidate_events
from ming_sim.skills import bind_content as _bind_skills


AUTO_SAVE_PREFIX = "auto_"
AUTO_SAVE_KEEP_TURNS = 3  # 每个 campaign 保留最近 N 个 turn 的全部自动存档（每 turn 含 begin + preresolve）
_CLI_ACTION_INTENT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cli-action-intent")


def prune_auto_saves(saves_dir: str, campaign_id: str, keep_turns: int = AUTO_SAVE_KEEP_TURNS) -> None:
    """清理自动存档：只清同一个 campaign_id，按 turn 分组，绝不碰手动存档。"""
    import os as _os
    import re as _re

    if not _os.path.isdir(saves_dir):
        return
    legacy_auto = _re.compile(rf"^{_re.escape(AUTO_SAVE_PREFIX)}\d{{4}}_\d{{2}}_t\d{{4}}_.+\.db$")
    for f in _os.listdir(saves_dir):
        if legacy_auto.match(f):
            try:
                _os.remove(_os.path.join(saves_dir, f))
            except OSError:
                pass
    campaign_id = (campaign_id or "").strip()
    if not campaign_id:
        return
    buckets: Dict[int, List[str]] = {}
    for f in _os.listdir(saves_dir):
        if not (f.startswith(f"{AUTO_SAVE_PREFIX}{campaign_id}_") and f.endswith(".db")):
            continue
        m = _re.search(r"_t(\d+)_", f)
        if not m:
            continue
        buckets.setdefault(int(m.group(1)), []).append(f)
    keep = max(1, int(keep_turns or 1))
    keep_turn_nums = set(sorted(buckets.keys(), reverse=True)[:keep])
    for turn_num, files in buckets.items():
        if turn_num in keep_turn_nums:
            continue
        for stale in files:
            try:
                _os.remove(_os.path.join(saves_dir, stale))
            except OSError:
                pass


# TurnPhase 单一真源已下沉 models.py（decree 也要用，import session 会循环）；
# 此处 re-export 保持旧 import 路径（terminal/web_app/tests 的 from session import TurnPhase）兼容。
from ming_sim.models import FRONT_HALF_DONE_PHASES, TurnPhase  # noqa: F401  (re-export)


@dataclass
class DirectiveView:
    id: int
    text: str
    status: str          # pending | draft | issued | rejected | deleted
    source: str
    notes: str
    actor: str = ""


@dataclass
class MinisterView:
    name: str
    office: str
    office_type: str
    faction: str
    status: str


@dataclass
class ChatTurnResult:
    answer: str
    court_action: str = ""   # "" | dismiss | summon | court_break | handled
    next_minister: str = ""
    proposed_directive: Optional[DirectiveView] = None
    appointed_minister: str = ""   # 吏部本轮铨选新任的人物姓名（已可召见）
    registered_minister: str = ""  # 名册外史实/用户确认人物建档后可召见
    displaced_minister: str = ""   # 因新任腾缺被罢黜（dismissed）的原任者姓名
    refresh_ministers: List[str] = field(default_factory=list)
    secret_order_id: int = 0       # 本轮新建密令 id（0=未下密令）
    pending_action_id: int = 0     # 本轮暂存的待颁诏动作 id（动作闸门 ADR 0006，0=无）
    pending_action_failures: List[Dict[str, Any]] = field(default_factory=list)
    # #502 AC5：多道并存时口头准驳含糊 → 结构化含糊态（含候选集），驱动大臣当场追问哪一道。
    directive_confirmation_ambiguous: Optional[Dict[str, Any]] = None


@dataclass
class TurnSnapshot:
    year: int
    period: int
    turn: int
    phase: str
    metrics: Dict[str, int]
    deaths_this_turn: List[Dict[str, str]] = field(default_factory=list)
    previous_summary: str = ""


def _find_candidate_by_name(content: GameContent, name: str) -> Optional[str]:
    """后宫 candidate 升格时，extractor 输出的称呼（如'李氏雪凝'）可能与原名（'李雪凝'）
    不完全一致。在 content.characters 里找：精确匹配 → aliases 含 name → name 含原名/原名含 name。
    返回 content.characters 里的原始 key，找不到返回 None。
    只对 office_type='后宫' 且 status='candidate' 的人物做匹配。"""
    # 精确匹配
    if name in content.characters:
        c = content.characters[name]
        if c.office_type == "后宫" and c.status == "candidate":
            return name
    # aliases 匹配 & 子串匹配
    for key, c in content.characters.items():
        if c.office_type != "后宫" or c.status != "candidate":
            continue
        if name in (c.aliases or []):
            return key
        # 子串匹配（直接）
        if key in name or name in key:
            return key
    return None


def _find_existing_minister(content: GameContent, name: str, db: "GameDB") -> Optional[str]:
    """铨选查重：拟任者是否已在册（非 candidate）。精确名 → aliases 命中。
    不做子串互含——'李标' vs '标' 那种巧合会误拒同义改写。
    后宫人物不在此查（走 _find_candidate_by_name）。返回在册原始 key，无则 None。

    power_id 用 db.resolve_power_id（DB 权威，#125）而非 content 静态值：本函数是罢黜/任命去重/
    密令 canonical 等 live court action 的 ming-guard（db._commit_office_action / apply_appointment /
    create_secret_order / apply_office_appointment 别名归一），与 can_summon/list_ministers 必须同口径——
    招抚归明者(DB翻ming但content仍旧势力)可召就必须可罢/可任，否则可召不可罢、跨切面不自洽（cmr #125 R2 codex high）。
    外藩(皇太极 DB houjin)resolve_power_id≠ming 仍不接，防误黜外藩的保护不丢。"""
    if name in content.characters:
        c = content.characters[name]
        if c.office_type != "后宫" and c.status != "candidate" and db.resolve_power_id(c) == "ming":
            return name
    for key, c in content.characters.items():
        # 先 in-memory 短路（office/candidate/别名命中），别名命中才查库 resolve_power_id——
        # 避免对每个人物都打一次 DB（N+1，gemini PR#130 R1 medium）。
        if c.office_type == "后宫" or c.status == "candidate":
            continue
        if name in (c.aliases or []) and db.resolve_power_id(c) == "ming":
            return key
    return None


def _recent_audience_context_for_secret_order(
    db: Any, minister_name: str, turn: int, current_message: str, limit: int = 8,
) -> str:
    """取当前大臣最近召对正文，供“密令”按钮确认短句补足任务上下文。

    #504 AC2「按夜取回」：喂料按**当前开着的夜**取回——只认本夜该大臣的对话轮
    （撤回/失败轮排除），不让同回合上一夜的密谋正文串进本夜（接缝④「密令喂料按夜
    从账/记录取回」）。无开着的夜（旧档/无夜路径）才回落 turn 域取回，语义不变。"""
    conn = getattr(db, "conn", None)
    if conn is None:
        return ""
    night_id = 0
    night_getter = getattr(db, "_current_open_night_id", None)
    if callable(night_getter):
        try:
            night_id = int(night_getter() or 0)
        except Exception:
            night_id = 0
    try:
        if night_id > 0:
            # 本夜该大臣对话轮的用户/大臣消息（撤回 undone_at / failed·undone 轮排除）；
            # 一轮两条消息各成一行，按 message id 序取最近 limit 条。
            rows = conn.execute(
                """
                SELECT m.role AS role, m.content AS content
                FROM chat_turns t
                JOIN chat_messages m
                  ON m.id IN (t.user_message_id, t.minister_message_id)
                WHERE t.night_id = ?
                  AND t.minister_name = ?
                  AND t.undone_at IS NULL
                  AND t.status NOT IN ('failed', 'undone')
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (int(night_id), str(minister_name or ""), int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT role, content FROM chat_messages
                WHERE minister_name = ? AND turn = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(minister_name or ""), int(turn), int(limit)),
            ).fetchall()
    except Exception:
        return ""
    current = (current_message or "").strip()
    lines: List[str] = []
    for row in reversed(rows):
        role = str(row["role"] if "role" in row.keys() else "")
        content = str(row["content"] if "content" in row.keys() else "").strip()
        if not content or content == current:
            continue
        label = "皇帝" if role == "user" else "大臣"
        lines.append(f"{label}：{content}")
    return "\n".join(lines[-limit:])


def _canonical_minister_key(content: Any, name: str, db: "GameDB") -> str:
    """姓名归一到在册原始 key（别名→原名）；无 content / 查不到时返回去空白原名。

    与 apply_appointment / no-op 判定 / 对冲同一口径。_find_existing_minister 不吞异常
    （ADR 0005：失败须响亮，不静默兜底——apply_appointment 亦直呼不 guard）。"""
    n = str(name or "").strip()
    if content is None or not n:
        return n
    canon = _find_existing_minister(content, n, db)
    return str(canon) if canon else n


def _appointment_intent_is_current_office_noop(
    db: Any, name: str, office: str, content: Any = None,
) -> bool:
    """任命目标已在该职时是背景复述，不生成待确认任免动作。

    姓名按 canonical 口径归一（与真正落任命 apply_office_appointment 同口径）：LLM 抽到的可能是
    别名（『韩阁老』而非『韩爌』），精确名查不到行会漏判成假任免（cmr #354 correctness）。先
    归一到在册原始名，再查当前 office。"""
    conn = getattr(db, "conn", None)
    clean_name = str(name or "").strip()
    desired = normalize_office(str(office or ""))
    if conn is None or not clean_name or not desired:
        return False
    canonical = _canonical_minister_key(content, clean_name, db)
    try:
        row = conn.execute(
            "SELECT status, office FROM characters WHERE name = ?",
            (canonical,),
        ).fetchone()
    except sqlite3.Error:
        return False
    if row is None or str(row["status"] or "") != "active":
        return False
    current = normalize_office(str(row["office"] or ""))
    if not current:
        return False
    desired_parts = {p for p in desired.split(",") if p}
    current_parts = {p for p in current.split(",") if p}
    return bool(desired_parts) and desired_parts.issubset(current_parts)


def _target_active_officeholder(db: Any, name: str, content: Any = None) -> bool:
    """目标当前是否为在职且有实职的名册人（有可罢之职）。

    R2「免去暂存任命」形——被任者尚未落库、非 active，无职可罢，撤掉暂存任命即净空；
    而在职改任者（active + 有 office）被再革职时，撤暂存任命后仍须落真罢免（不能吞）。"""
    conn = getattr(db, "conn", None)
    clean = str(name or "").strip()
    if conn is None or not clean:
        return False
    key = _canonical_minister_key(content, clean, db)
    try:
        row = conn.execute(
            "SELECT status, office FROM characters WHERE name = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return False
    if row is None:
        return False
    return str(row["status"] or "") == "active" and bool(str(row["office"] or "").strip())


def _cancel_staged_opposing_office(
    db: Any, opposing_action: str, target_name: str, turn: int, content: Any = None,
) -> Optional[int]:
    """撤销同回合针对同一人的一条【反向暂存任免】，返回其 id；无则 None（对冲，ADR 0028
    R1/R2 双向对称）。

    这是「名册 ⊕ 暂存」比对真基准的落地：暂存免职/任命未提交时名册仍是旧态，皇帝反悔
    （留任冲免职、免去冲任命）若只比名册会被误判 no-op 丢弃或另 stage 孤儿。姓名按 canonical
    口径归一，别名/新候选按同一原名兜底比对，两侧同名即相抵。撤销走 withdraw_pending_action
    （只删 pending，已 committed 不动），night_approved 但未收夜提交的暂存仍属 pending、照样对冲。"""
    conn = getattr(db, "conn", None)
    clean = str(target_name or "").strip()
    if conn is None or not clean or opposing_action not in ("任命", "罢免"):
        return None
    target_key = _canonical_minister_key(content, clean, db)
    for pa in db.list_pending_actions(int(turn)):
        if pa.get("kind") != "office" or pa.get("action") != opposing_action:
            continue
        try:
            payload = json.loads(pa.get("payload_json") or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        staged = str(payload.get("name") or "").strip()
        if staged and _canonical_minister_key(content, staged, db) == target_key:
            if db.withdraw_pending_action(int(pa["id"]), int(turn)):
                return int(pa["id"])
    return None


def apply_appointment(
    db: GameDB,
    state: GameState,
    content: GameContent,
    registry: Optional[MinisterRegistry],
    data: Dict[str, object],
    llm_config: Optional[LLMConfig] = None,
    commit: bool = True,
) -> Tuple[str, str]:
    """诏书任命/吏部铨选共用落地：建档入库 + 注册 Agent，本回合即可召见。
    LLM（吏部 propose_appointment 或档房 appointments 三道闸）已判过史实合理性；
    代码端只做姓名查重与字段兜底，不做历史校验。
    返回 (新任者姓名, 被腾缺罢黜者姓名)；任一无则该位留空串。
    payload 不合法、重名、approved=false 则返回 ("", "")。

    职位替换：data["replaces"] 填现任者姓名时，把其 status 改 dismissed 腾缺
    （由吏部 LLM 判定占缺者，代码端不做职位字面校验，符合无 fallback 约束）。

    后宫纳妃：data 含 office_type="后宫" 时走后宫路径——office 记称号（贵妃/嫔/才人等），
    faction 留空（填"后宫"），注册 Agent 以 consort_agent_prompt 为底。

    candidate 升格：若 name 能匹配现有 candidate（含 aliases/子串），
    走 UPDATE（保留原 style/skills/portrait_id），不新建记录。
    """
    if not data:
        return ("", "")
    if "approved" in data and not bool(data.get("approved")):
        return ("", "")
    name = str(data.get("name") or "").strip()
    office = str(data.get("office") or "").strip()
    if not name or not office:
        return ("", "")
    is_consort = str(data.get("office_type") or "").strip() == "后宫"
    # 朝臣多职统一逗号分隔（后宫记称号，不动）；与 db 层 normalize_office 同源。
    if not is_consort:
        office = normalize_office(office)
    # 显式名分（office_type ∈ PERSON_TITLE_KINDS）在此建 Character 前就得保住：add_character 的
    # 名分守卫看的是 character.office_type，若这里先被 infer 反推成官职（office='诸生'→'生员'），
    # 守卫永远见不到名分、误建 offices/character_offices（#1059 codex l6h）。
    office_type = (
        "后宫" if is_consort
        else resolve_office_type_preserving_title(
            office,
            str(data.get("office_type") or "").strip(),
            "待铨",
            llm_config or db.llm_config,
        )
    )

    # ── 后宫 candidate 升格路径 ──────────────────────────────────────
    if is_consort:
        original_key = _find_candidate_by_name(content, name)
        if original_key is not None:
            # 升格：UPDATE DB 里的记录，保留原 style/skills/portrait_id
            character = content.characters[original_key]
            character.office = office
            character.faction = "后宫"
            character.status = "active"
            # 若还没有 portrait_id，补分配
            if not character.portrait_id:
                character.portrait_id = db.next_pool_portrait_id("consort_pool_")
            db.conn.execute(
                """UPDATE characters SET office=?, office_type='后宫', faction='后宫',
                   status='active', status_reason='诏书册封', status_changed_turn=?,
                   portrait_id=CASE WHEN portrait_id='' THEN ? ELSE portrait_id END
                   WHERE name=?""",
                (office, state.turn, character.portrait_id, original_key),
            )
            db.conn.execute(
                """INSERT INTO character_offices (character_name, office_title, office_type, source)
                   VALUES (?, ?, '后宫', '诏书册封')
                   ON CONFLICT(character_name) DO UPDATE SET
                       office_title=excluded.office_title,
                       office_type=excluded.office_type,
                       source=excluded.source,
                       updated_at=CURRENT_TIMESTAMP""",
                (original_key, office),
            )
            if commit:
                db.conn.commit()
            # 若 extractor 用了新称呼，在 content 里建别名指向原对象
            if name != original_key:
                content.characters[name] = character
            if registry is not None:
                registry.register(character)
            return (original_key, "")  # 返回原始 key，保持一致

    # ── 普通路径查重：精确名 + aliases 命中即拒，不重复建档 ──────────
    if not is_consort:
        existing = _find_existing_minister(content, name, db)
        if existing is not None:
            return ("", "")
    elif name in content.characters and content.characters[name].status != "candidate":
        return ("", "")

    # ── 职位替换：腾缺现任者 → dismissed ───────────────────────────
    displaced = ""
    replaces = str(data.get("replaces") or "").strip()
    if not is_consort and replaces and replaces in content.characters:
        old = content.characters[replaces]
        if old.status == "active":
            db.set_character_status(
                state, replaces, "dismissed",
                reason=f"{office}改授{name}，原任去职",
                commit=commit,
            )
            old.status = "dismissed"
            old.transit_to = ""
            displaced = replaces

    faction = "后宫" if is_consort else str(data.get("faction") or "中立").strip()
    if not is_consort and faction not in content.factions:
        faction = "中立"
    character = Character(
        name=name,
        office=office,
        office_type=office_type,
        faction=faction,
        aliases=[],
        personal_skills=[],
        loyalty=60, ability=55, integrity=60, courage=50,
        style="新入宫闱" if is_consort else "新任未详",
        power_id="ming",
        status="active",
    )
    content.characters[name] = character
    db.add_character(state, character, llm_config=llm_config, commit=commit)
    # add_character 已写入并分配 portrait_id，回写到内存对象
    row = db.conn.execute(
        "SELECT portrait_id FROM characters WHERE name=?", (name,)
    ).fetchone()
    if row:
        character.portrait_id = str(row["portrait_id"])
    if registry is not None:
        registry.register(character)
    return (name, displaced)


def _pending_action_brief(pa: Dict[str, Any]) -> str:
    """暂存动作的一句话摘要，供对话确认意图判定时告诉 LLM『有哪些待皇帝定夺』。"""
    import json as _json
    kind = pa.get("kind")
    action = pa.get("action")
    try:
        payload = _json.loads(pa.get("payload_json") or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if kind == "office":
        who = payload.get("name") or ""
        office = payload.get("office") or ""
        return f"{action}「{who}」" + (f"为「{office}」" if office else "")
    if kind == "consort":
        return f"调教「{payload.get('name') or ''}」"
    if kind == "directive":
        text = str(payload.get("text") or "")
        return f"草拟圣旨：{text[:30]}"
    return f"{action}密令"


def _confirmation_targets_for_message(pending_actions: List[Dict[str, Any]], message: str) -> List[Dict[str, Any]]:
    """Choose which pending action family this chat confirmation can affect."""
    text = message or ""
    secret = [p for p in pending_actions if p["kind"] == "secret_order"]
    office = [p for p in pending_actions if p["kind"] == "office"]
    consort = [p for p in pending_actions if p["kind"] == "consort"]
    non_directive = [p for p in pending_actions if p["kind"] != "directive"]
    directive = [p for p in pending_actions if p["kind"] == "directive"]
    all_mentioned = (
        any(token in text for token in ("全都", "全部", "一并", "一概", "尽数"))
        or re.search(r"都(?:准了|准(?!备)|照办|作罢|驳回|驳了|拒绝|拒了|不准|不允|撤了|撤回)", text) is not None
    )
    family_targets: List[Dict[str, Any]] = []
    if any(token in text for token in ("密令", "密旨", "密谕")):
        family_targets.extend(secret)
    if any(token in text for token in ("任免", "任命", "罢免", "罢黜", "起用", "升任", "调任", "撤职")):
        family_targets.extend(office)
    if any(token in text for token in ("调教", "后宫", "妃嫔", "嫔妃")):
        family_targets.extend(consort)
    directive_mentioned = any(token in text for token in ("圣旨", "旨意", "拟旨", "诏书", "诏文", "草案"))
    if directive_mentioned and directive:
        family_targets.extend(directive)
    if family_targets:
        return family_targets
    if all_mentioned:
        return pending_actions
    return non_directive or directive


def _pending_action_failure_payload(pa: Dict[str, Any], state: Optional[GameState] = None) -> Dict[str, Any]:
    """把落库失败的暂存动作翻成可给玩家看的失败状态。"""
    kind = str(pa.get("kind") or "")
    action = str(pa.get("action") or "")
    noun = {
        "secret_order": "密令",
        "office": "任免",
        "consort": "后宫安排",
        "directive": "拟旨",
    }.get(kind, "政务动作")
    retryable = kind == "secret_order" and (
        state is None or getattr(state, "turn_phase", None) not in FRONT_HALF_DONE_PHASES
    )
    if kind == "secret_order" and retryable:
        message = f"{noun}未能正式落库，请重试；若暂不处理，也不会阻断继续召对。"
    elif kind == "secret_order":
        message = f"{noun}未能正式落库，已记录为失败；稍后可在恢复入口处理。"
    else:
        message = f"{noun}未能正式落库，已记录为失败；若暂不处理，也不会阻断继续召对。"
    return {
        "id": int(pa.get("id") or 0),
        "kind": kind,
        "action": action,
        "minister_name": str(pa.get("minister_name") or ""),
        "retryable": retryable,
        "message": message,
    }


def _sync_offices_from_db_impl(content: GameContent, db: "GameDB", llm_config: Optional[LLMConfig] = None) -> None:
    """启动/读档时以 DB characters 表重建内存人物表。
    DB 是持久化真相；不要在这里修写 DB。"""
    rows = db.conn.execute(
        """
        SELECT name, office, office_type, faction, aliases, personal_skills,
               loyalty, ability, integrity, courage, style, identity, seed_guilt,
               birth_year, historical_death_year, historical_death_month,
               debut_year, debut_month, status, status_reason, reason_code,
               portrait_id, power_id, location, transit_to, summary
        FROM characters
        """
    ).fetchall()
    characters: Dict[str, Character] = {}
    for row in rows:
        name = row["name"]
        # DB 是真相：表查不中时按库里存的 office_type 原样落回内存（含朝堂类，仅空落待铨——
        # use_llm=False 契约），不每回合现拉 codex 重判、也不降级。否则全员逐人判 office_type，
        # 外藩/宗藩/平民官名表查不中 → 启动/每 begin_turn 都触发 ~28 串行 codex（开局慢 5 分钟
        # 的同源风暴）；且若降级朝堂类，动态任免落库的 礼部/兵部 等会被每回合 sync 悄悄抹成待铨
        # （cmr R2）。任免变更本身走动态路径仍 LLM。
        office_type = infer_office_type_from_office(
            row["office"], row["office_type"], llm_config, use_llm=False
        )
        import json as _json

        try:
            aliases = _json.loads(row["aliases"] or "[]")
        except (TypeError, ValueError):
            aliases = []
        if not isinstance(aliases, list):
            aliases = []
        try:
            personal_skills = _json.loads(row["personal_skills"] or "[]")
        except (TypeError, ValueError):
            personal_skills = []
        if not isinstance(personal_skills, list):
            personal_skills = []
        try:
            seed_guilt = _json.loads(row["seed_guilt"] or "{}")
        except (TypeError, ValueError):
            seed_guilt = {}
        if not isinstance(seed_guilt, dict):
            seed_guilt = {}
        characters[name] = Character(
            name=name,
            office=row["office"],
            office_type=office_type,
            faction=row["faction"],
            aliases=[str(item) for item in aliases if str(item).strip()],
            personal_skills=[str(item) for item in personal_skills if str(item).strip()],
            loyalty=int(row["loyalty"]),
            ability=int(row["ability"]),
            integrity=int(row["integrity"]),
            courage=int(row["courage"]),
            style=row["style"],
            birth_year=int(row["birth_year"]),
            historical_death_year=int(row["historical_death_year"]),
            historical_death_month=int(row["historical_death_month"]),
            debut_year=int(row["debut_year"]),
            debut_month=int(row["debut_month"]),
            status=row["status"],
            status_reason=row["status_reason"] or "",
            reason_code=row["reason_code"] or "",
            power_id=row["power_id"],
            location=row["location"],
            transit_to=row["transit_to"] or "",
            portrait_id=row["portrait_id"],
            summary=row["summary"],
            identity=int(row["identity"]),
            seed_guilt={str(key): str(value) for key, value in seed_guilt.items()},
        )
    content.characters = characters


def _bind_all_content(content: GameContent) -> None:
    """把 GameContent 注入所有 bind_content 模块。GameSession 启动时调一次。"""
    _bind_skills(content)
    _bind_context(content)
    _bind_agents(content)
    _bind_registry(content)
    _bind_issues(content)


class GameSession:
    """一局游戏的核心状态机。CLI / Web 都通过它驱动回合。"""

    def __init__(
        self,
        db_path: str,
        llm_config: LLMConfig,
        content: Optional[GameContent] = None,
        verify_llm: bool = True,
        start_ym: str = "",
    ) -> None:
        self.content = content if content is not None else GameContent.load()
        _bind_all_content(self.content)
        self.llm_config = llm_config
        from ming_sim.beat_orchestration import create_llm_beat_generator
        self._beat_generator = create_llm_beat_generator(llm_config)
        if verify_llm:
            verify_llm_available(llm_config)
        self.db = GameDB(db_path, content=self.content, llm_config=llm_config)
        # 接档载入阶段计时（#84）：原为零日志盲区，群友以为死机；逐阶段 tlog 用时，
        # 自部署者在 server 控制台看得见进度、定位慢阶段。
        from ming_sim.token_stats import tlog
        _t = time.monotonic()
        self.db.seed_static_data()
        _t, _e = time.monotonic(), time.monotonic() - _t
        tlog(f"[载入] 1/4 静态盘面 seed {_e:.1f}s")
        _sync_offices_from_db_impl(self.content, self.db, llm_config)
        self.agno_db = create_agno_db(db_path)
        _t, _e = time.monotonic(), time.monotonic() - _t
        tlog(f"[载入] 2/4 官职同步 + agno {_e:.1f}s")
        self.state = self.db.load_state(start_ym)
        _t, _e = time.monotonic(), time.monotonic() - _t
        tlog(f"[载入] 3/4 状态载入 {_e:.1f}s")
        # 开局负面帝国修正：新档补全、旧档补缺、已达消除条件的不补/清残。不立 issue、不进推演。
        sync_opening_legacies(self.db, self.state)
        tlog(f"[载入] 4/4 开局修正 {time.monotonic() - _t:.1f}s")
        self.deaths_this_turn: List[Dict[str, str]] = []
        self.debuts_this_turn: List[Dict[str, str]] = []
        self.power_renames_this_turn: List[Dict[str, object]] = []
        self.previous_summary = ""
        self.registry: Optional[MinisterRegistry] = None
        self.temporary_characters: Dict[str, Character] = {}
        self.last_decree = ""
        self.last_report = ""
        # P1-1：last_decree 所覆盖的 draft 指纹（write_decree 时记，颁诏时校验是否已陈旧）。
        self._decree_draft_fingerprint: Tuple[Tuple[int, str], ...] = ()
        self._begun = False

    # ── 回合生命周期 ──────────────────────────────────────────────────────

    def begin_turn(self) -> TurnSnapshot:
        """加载/刷新本回合：历史卒、上回合奏报、重建 registry。幂等。"""
        # 接档/刷新阶段计时（#84）：begin_turn 是「继续」载入的慢段所在（大臣 registry 重建可触发
        # office_type 推断等 LLM 调用），原零日志=进度盲区；逐阶段 tlog 用时定位慢点。
        from ming_sim.token_stats import tlog
        _t = time.monotonic()
        self.state = self.db.load_state()
        self.deaths_this_turn = self.db.apply_historical_deaths(self.state)
        self.debuts_this_turn = self.db.apply_historical_debuts(self.state)
        self.power_renames_this_turn = self.db.apply_historical_power_renames(self.state)
        _sync_offices_from_db_impl(self.content, self.db, self.llm_config)
        self.previous_summary = self.db.previous_turn_summary(self.state) or ""
        tlog(f"[接档] begin_turn 读档+历史 tick+人物同步+奏报 {time.monotonic() - _t:.1f}s")
        _t = time.monotonic()
        context = CourtContext(state=self.state, db=self.db, previous_summary=self.previous_summary)
        self.registry = MinisterRegistry(self.llm_config, self.agno_db, context)
        tlog(f"[接档] begin_turn 大臣 registry 重建 {time.monotonic() - _t:.1f}s")
        self.last_decree = ""
        self.last_report = ""
        self._decree_draft_fingerprint = ()
        # awaiting_decision 必须保活：刷新页时仍要弹决策点续跑结算，不可重置成 summoning。
        # settling 同样保活（ADR 0008 S4）：pre_settle 前半段已提交，重载若被重置回 summoning，
        # 守门失效=恢复入口认不出「前半段已完成」会二次重跑前半段（白名单外即被重置）。
        if self.state.turn_phase not in (
            TurnPhase.SUMMONING.value, TurnPhase.REVIEWING.value,
            TurnPhase.AWAITING_DECISION.value, TurnPhase.SETTLING.value,
        ):
            self.state.turn_phase = TurnPhase.SUMMONING.value
            self.db.save_state(self.state)
        self._begun = True
        self.auto_save("begin")
        return self.turn_snapshot()

    def current_phase(self) -> TurnPhase:
        return TurnPhase(self.state.turn_phase)

    def _set_phase(self, phase: TurnPhase) -> None:
        self.state.turn_phase = phase.value
        self.db.save_state(self.state)

    def turn_snapshot(self) -> TurnSnapshot:
        return TurnSnapshot(
            year=self.state.year,
            period=self.state.period,
            turn=self.state.turn,
            phase=self.state.turn_phase,
            metrics=dict(self.state.metrics),
            deaths_this_turn=list(self.deaths_this_turn),
            previous_summary=self.previous_summary,
        )

    def end_turn(self) -> None:
        """回合结束（resolve 已推进 state.turn）；阶段回 summoning。"""
        self.state.turn_phase = TurnPhase.SUMMONING.value
        self.db.save_state(self.state)

    def note_chat_rollback(self, deleted_committed_draft_ids: Optional[List[int]] = None) -> None:
        """P1-2：撤回召对若删了 write_decree 已 commit 的对话草案（committed draft），
        本份生成的诏书正文（last_decree）含被撤回的指令——必须作废，使颁诏须重生成，
        不能原样颁出。普通撤回（未删 committed draft）不动有效生成稿。"""
        if deleted_committed_draft_ids:
            self.last_decree = ""
            self._decree_draft_fingerprint = ()

    def _draft_fingerprint(self, directives) -> Tuple[Tuple[int, str], ...]:
        def _has_mapping_key(row, key: str) -> bool:
            if isinstance(row, dict):
                return key in row
            keys = getattr(row, "keys", None)
            return callable(keys) and key in keys()

        def _mapping_get(row, key: str, default=None):
            if isinstance(row, dict):
                return row.get(key, default)
            return row[key] if _has_mapping_key(row, key) else default

        return tuple(
            sorted(
                (int(_mapping_get(d, "id")), str(_mapping_get(d, "text", "") or ""))
                for d in directives
                if _has_mapping_key(d, "id") and _mapping_get(d, "id") is not None
            )
        )

    def refresh_runtime_after_chat_rollback(self) -> None:
        """撤回召对副作用后，用 DB 真相刷新内存人物表和本回合 Agent registry。"""
        self.state = self.db.load_state()
        _sync_offices_from_db_impl(self.content, self.db, self.llm_config)
        if self.registry is not None:
            context = CourtContext(
                state=self.state,
                db=self.db,
                previous_summary=self.previous_summary,
            )
            self.registry = MinisterRegistry(self.llm_config, self.agno_db, context)

    # ── 召见阶段 ──────────────────────────────────────────────────────────

    def list_ministers(self) -> List[MinisterView]:
        # 状态以 DB 为准（历史卒/登场/罢黜均落 DB）；offstage 未登场者不进名单。
        views: List[MinisterView] = []
        for c in self.content.characters.values():
            # 先 in-memory 短路（宗藩），再查库——避免对宗藩也打一次 resolve_power_id DB 查询
            # （gemini PR#130 R1 medium）。宗藩（就藩宗室）非朝堂命官，同各 roster 排除（PR#121，cmr R5）。
            if is_vassal_prince(c):
                continue
            # DB 权威 power_id：招抚归明者(DB翻ming/content仍旧势力)须入召见名册，否则可召(can_summon
            # 认 DB)却不在册，两端不一致（#125；与 can_summon/court_roster 同口径）。
            if self.db.resolve_power_id(c) != "ming":
                continue
            status, _ = self.db.get_character_status(c.name)
            if status == "offstage":
                continue
            views.append(MinisterView(
                name=c.name, office=c.office, office_type=c.office_type,
                faction=c.faction, status=status,
            ))
        return views

    def _character(self, name: str) -> Character:
        if name in self.temporary_characters:
            return self.temporary_characters[name]
        return character_from_name(name)

    def _retrieve_memories_for_message(self, message: str) -> str:
        """Compatibility shim; character context owns all historical reads."""
        return message

    def _temporary_character(self, name: str) -> Character:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("临时召见姓名不能为空。")
        existing = self.temporary_characters.get(clean_name)
        if existing is not None:
            return existing
        character = Character(
            name=clean_name,
            office="御前临时召见",
            office_type="临时召见",
            faction="未定",
            aliases=[clean_name],
            personal_skills=[],
            loyalty=50,
            ability=50,
            integrity=50,
            courage=50,
            style="身份未详，奉旨临时入殿",
            power_id="ming",
            status="active",
            summary="此人未入本局人物档，奉旨临时召对。若史实有官职/身份，照实奏对；若无，亦不得编造。所属势力、现任差遣以本人据实交代为准。",
        )
        self.temporary_characters[clean_name] = character
        if self.registry is not None:
            self.registry.register_runtime(character)
        return character

    def summon_character(
        self,
        name_or_text: str,
        current: Optional[Character] = None,
        allow_temporary: bool = True,
    ) -> Tuple[Character, bool]:
        """召见人物：优先匹配正式名册；匹配不到则创建运行时临时人物。返回 (人物, 是否临时)。"""
        target = match_minister_from_text(name_or_text, current)
        if target is not None:
            return (target, False)
        clean_name = str(name_or_text or "").strip()
        if clean_name in self.content.characters:
            return (self.content.characters[clean_name], False)
        if not allow_temporary:
            raise ValueError(f"人物未建档：{clean_name}")
        return (self._temporary_character(clean_name), True)

    def can_summon(self, character: Character) -> Tuple[bool, str]:
        if character.name in self.temporary_characters:
            return (True, "")
        # 宗藩（就藩宗室）非朝堂命官，不可召见——与 web _require_active_minister / 各 roster 同口径
        # （PR#121 隐藏宗藩）。can_summon 是 summon_minister 工具链（session + web 流式两路）的共用闸，
        # 集中守此一处即覆盖两路，否则裁判可绕列表按名召宗藩（cmr R4 cross-section）。后宫不在此拒。
        if is_vassal_prince(character):
            return (False, f"{character.name}为就藩宗室，非朝廷命官，无法召见。")
        # 非大明势力（后金/蒙古/朝鲜/流寇）非朝廷命官，即便 active 也不可召见——皇帝召的是
        # 大明朝廷之臣，不召敌酋（皇太极等）。按 DB 权威 power_id 判：招抚归明者 DB 已翻 ming
        # 但内存仍旧势力，认 DB 才不会误拒归明者（#125；与 web_app 朝堂可见性同口径）。
        if self.db.resolve_power_id(character) != "ming":
            return (False, f"{character.name}不属大明朝廷，无法召见。")
        status, reason = self.db.get_character_status(character.name)
        if status == "active":
            return (True, "")
        label = {
            "offstage": "尚未登场",
            "dismissed": "已罢黜",
            "imprisoned": "下狱",
            "exiled": "流放",
            "retired": "致仕",
            "dead": "已故",
        }.get(status, status)
        return (False, f"{character.name}{label}，无法召见。" + (reason or ""))

    def _start_cli_action_intent(self, character: Character, message: str) -> Optional[Future]:
        """CLI 召对动作判断只读皇帝消息，可与大臣回话并发。"""
        from ming_sim.cli_backend import (
            _DRAFT_PREFIXES, _SECRET_PREFIXES, classify_cli_action_intent,
            cli_backend_from_env, cli_backend_parallel_safe,
        )
        channel = (getattr(getattr(self, "llm_config", None), "channel", "") or "").strip().lower()
        if channel != "cli" and (channel == "api" or cli_backend_from_env() is None):
            return None
        # 并发安全白名单守门（cmr Gate2）：只有 _PARALLEL_SAFE_CLI_RUNNERS（仅 codex，--ephemeral
        # 隔离）才能把动作分类器与大臣回话并发跑；agy（keychain auth-race）/claude（rate-limit）
        # 并发未验证——并发两个子进程会撞 auth/session race。非安全 runner 返 None → preclassified
        # 为空 → apply_cli_conversation_actions 回落到回话后串行抽取（extract_minister_actions 等），
        # 动作不丢、只是不并发（与月末 4-extractor 并行同一口径，cli_backend.cli_backend_parallel_safe）。
        if not cli_backend_parallel_safe(getattr(self, "llm_config", None)):
            return None
        text = (message or "").strip()
        if text.startswith(_DRAFT_PREFIXES) or text.startswith(_SECRET_PREFIXES):
            return None
        minister_name = character.name
        pend_for_minister = self.db.list_pending_actions(self.state.turn, minister_name=minister_name)
        confirm_targets = _confirmation_targets_for_message(pend_for_minister, text)
        if GameSession._proposal_blocked(self.state) and not confirm_targets:
            return None
        summaries = [_pending_action_brief(p) for p in confirm_targets]
        is_consort = getattr(character, "office_type", "") == "后宫"
        active_orders = [] if GameSession._proposal_blocked(self.state) else self.db.get_active_secret_orders_for_minister(minister_name)
        has_pending_draft = any(p["kind"] == "directive" for p in pend_for_minister)
        return _CLI_ACTION_INTENT_EXECUTOR.submit(
            classify_cli_action_intent,
            text,
            active_orders,
            is_consort,
            has_pending_draft,
            summaries,
            getattr(self, "llm_config", None),
        )

    def _finish_cli_action_intent(self, future: Optional[Future]) -> Optional[List[Dict[str, Any]]]:
        """Join concurrent classifier. None=did not run; list (possibly empty)=ran.

        #515: classifier output contract is a candidate list. Failure → [] (zero writes).
        """
        if future is None:
            return None
        from ming_sim.action_clusters import normalize_intent_candidates
        try:
            result = future.result()
        except Exception:
            return []
        # normalize_intent_candidates(None) is None; non-None raw → list (soft).
        normalized = normalize_intent_candidates(result)
        return [] if normalized is None else normalized

    def _confirmation_intent_for_preexisting_pending(
        self,
        minister_name: str,
        player_message: str,
        reply: str,
        preclassified_intent: Optional[Any],
        confirm_target_ids: set[int],
    ) -> Optional[Any]:
        """Classify confirmation before consuming same-turn write tools.

        Confirmation rounds are intentionally terminal for new inferred writes:
        the minister's reply may restate or tool-emit the same order, but that
        output must not stage a fresh pending action before the old visible one
        is committed/rejected.

        #515: accepts dict or list; returns list (or None if classifier did not run).
        """
        from ming_sim.cli_backend import _DRAFT_PREFIXES, _SECRET_PREFIXES, extract_confirmation_intent
        from ming_sim.action_clusters import (
            EFFECT_ANSWER_EXISTING,
            cluster_effect,
            normalize_intent_candidates,
            normalize_one_candidate,
            resolve_primary_intent,
        )

        if preclassified_intent is None:
            candidates: Optional[List[Dict[str, Any]]] = None
        else:
            candidates = normalize_intent_candidates(preclassified_intent)
            if candidates is None:
                candidates = []

        intent = resolve_primary_intent(candidates)
        message_text = (player_message or "").strip()
        if message_text.startswith(_DRAFT_PREFIXES) or message_text.startswith(_SECRET_PREFIXES):
            return candidates
        if not confirm_target_ids:
            return candidates
        if intent is not None and cluster_effect(
            str(intent.get("kind") or "")
        ) == EFFECT_ANSWER_EXISTING:
            return candidates if candidates is not None else []
        pend_for_minister = self.db.list_pending_actions(
            self.state.turn, minister_name=minister_name)
        allowed_confirm_ids = {int(pid) for pid in confirm_target_ids}
        pend_for_minister = [p for p in pend_for_minister if int(p["id"]) in allowed_confirm_ids]
        confirm_targets = _confirmation_targets_for_message(pend_for_minister, message_text)
        if not confirm_targets:
            return candidates
        summaries = [_pending_action_brief(p) for p in confirm_targets]
        confirm = extract_confirmation_intent(
            player_message, reply, summaries, llm_config=getattr(self, "llm_config", None))
        if confirm in ("应允", "拒绝"):
            cand = normalize_one_candidate(
                {"kind": "confirmation", "confirmation": confirm},
                soft=False,
            )
            return [cand]
        return candidates

    def chat(self, minister_name: str, message: str, *, chat_turn_id: int = 0) -> ChatTurnResult:
        """与大臣对话一轮，统一处理 court tool 截获。
        大臣 propose_directive 产生的草案先进 pending_actions 闸门，
        作为 pending_action_id 返回，确认/驳回由对话或颁诏 checkpoint 处理。"""
        if self.registry is None:
            raise RuntimeError("GameSession.begin_turn() 未调用。")
        character = self._character(minister_name)
        # 控制指令（退下/换人/技能）由 CLI 层 parse_court_command 处理；
        # GameSession.chat 只负责与 agent 对话与 tool 截获。
        agent = self.registry.get(character)
        # Keep the public seam compatible with lightweight web/test session
        # doubles that predate the optional character-aware audience context.
        audience_prompt = self._audience_prompt_for_message
        try:
            prompt_signature = inspect.signature(audience_prompt)
        except (TypeError, ValueError):
            # The production bound method has an inspectable signature.  For
            # opaque callables, preserve the character-aware production call;
            # do not catch its runtime TypeError as a signature fallback.
            augmented = audience_prompt(message, character, chat_turn_id=chat_turn_id)
        else:
            try:
                prompt_signature.bind(message, character, chat_turn_id=chat_turn_id)
            except TypeError:
                prompt_signature.bind(message)
                augmented = audience_prompt(message)
            else:
                augmented = audience_prompt(message, character, chat_turn_id=chat_turn_id)
        action_intent_future = self._start_cli_action_intent(character, message)
        run_output = agent.run(augmented)
        _dump_llm_messages(run_output, f"大臣对话/{minister_name}")
        answer = extract_agent_text(run_output)
        result = ChatTurnResult(answer=answer)
        preexisting_pending_action_ids = {
            int(p["id"]) for p in self.db.list_pending_actions(self.state.turn, minister_name=character.name)
        }
        preclassified_intent = self._finish_cli_action_intent(action_intent_future)
        preclassified_intent = self._confirmation_intent_for_preexisting_pending(
            character.name, message, answer, preclassified_intent, preexisting_pending_action_ids)
        message_text = (message or "").strip()
        from ming_sim.cli_backend import _DRAFT_PREFIXES, _SECRET_PREFIXES
        from ming_sim.action_clusters import is_confirmation_decision, resolve_primary_intent
        explicit_draft_prefix = message_text.startswith(_DRAFT_PREFIXES)
        explicit_secret_prefix = message_text.startswith(_SECRET_PREFIXES)
        confirmation_turn = is_confirmation_decision(
            resolve_primary_intent(preclassified_intent))
        for tool_exec in getattr(run_output, "tools", None) or []:
            tool_name = getattr(tool_exec, "tool_name", "")
            tool_result = str(getattr(tool_exec, "result", "") or "")
            if tool_name == "dismiss_minister" or tool_result == "__dismiss__":
                result.court_action = "dismiss"
                # AC1（#500）：令退在此单缝落确定性告退账，一切经 session.chat 的消费者
                # （CLI 召对 / 非流式 web /api/ministers/{name}/chat）自动闭合，名单查询即时去人；
                # 不在场/无开夜时既有 no-op。stream 路 tool 环另处同调 dismiss_from_audience。
                if hasattr(self.db, "conn"):
                    from ming_sim.audience_night import dismiss_from_audience
                    # #506 L1：告退账绑本轮，撤回本轮据 origin 删账、令退者在场复原。
                    dismiss_from_audience(
                        self.db, character.name, origin_chat_turn_id=chat_turn_id,
                    )
            elif tool_name == "summon_minister" or tool_result.startswith("__summon__"):
                next_name = tool_result.removeprefix("__summon__").strip()
                if next_name not in self.content.characters:
                    args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                    next_name = args.get("name", "")
                if next_name:
                    try:
                        target, _is_temporary = self.summon_character(next_name, character, allow_temporary=False)
                    except ValueError:
                        target = None
                    if target is not None:
                        ok, _reason = self.can_summon(target)
                        if ok:
                            result.court_action = "summon"
                            result.next_minister = target.name
            elif tool_name == "propose_directive" or tool_result.startswith("__pending_directive__"):
                if confirmation_turn or explicit_secret_prefix:
                    continue
                draft_text = tool_result.removeprefix("__pending_directive__").strip()
                if not draft_text:
                    args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                    draft_text = (args.get("decree_text") or "").strip()
                if draft_text and self._proposal_blocked(self.state):
                    draft_text = ""  # 恢复窗婉拒：不入档（见 _proposal_blocked）
                if draft_text:
                    # #502 L2：显式拟旨走单一 seam——已有候选则新拟独立一道，不 upsert 压扁前一道。
                    result.pending_action_id = self.db.stage_explicit_directive(
                        self.state.turn, character.name, draft_text, mode=message_text)
            elif (tool_name == "propose_appointment"
                  or tool_result.startswith("__pending_appointment__")
                  or tool_result.startswith("__pending_recommendation__")):
                if confirmation_turn or explicit_draft_prefix or explicit_secret_prefix:
                    continue
                payload = tool_result.removeprefix("__pending_recommendation__")
                payload = payload.removeprefix("__pending_appointment__").strip()
                result.pending_action_id = self._stage_appointment_candidate(
                    payload, character, message_text,
                )
            elif tool_name == "register_unlisted_person" or tool_result.startswith("__pending_unlisted_person__"):
                if confirmation_turn or explicit_draft_prefix or explicit_secret_prefix:
                    continue
                payload = tool_result.removeprefix("__pending_unlisted_person__").strip()
                registered, summon_after = self._apply_unlisted_person_registration(payload)
                if registered:
                    result.registered_minister = registered
                    result.refresh_ministers.append(registered)
                    if summon_after:
                        result.court_action = "summon"
                        result.next_minister = registered
            elif (
                tool_name == "secret_order"
                or tool_result.startswith("__secret_order_registered__")
                or tool_result.startswith("__secret_order__")
                or tool_result.startswith("__secret_action__")
            ):
                if confirmation_turn or explicit_draft_prefix:
                    continue
                if self._proposal_blocked(self.state):
                    continue
                if tool_result.startswith("__secret_action__"):
                    payload_json = tool_result.removeprefix("__secret_action__").strip()
                    try:
                        data = json.loads(payload_json) if payload_json else {}
                    except (ValueError, TypeError):
                        data = {}
                    if isinstance(data, dict):
                        action = str(data.get("action") or "").strip()
                        try:
                            order_id = int(data.get("order_id") or 0)
                        except (TypeError, ValueError):
                            order_id = 0
                        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                        if action and order_id:
                            # Pin only when non-create carries new oral body (更新).
                            # 催办/记进展/提交核议 must not auto-pin pure-public held.
                            if action == "更新":
                                payload = self.db.attach_secret_oral_pin(
                                    character.name, int(self.state.turn), payload,
                                )
                            result.pending_action_id = self.db.stage_pending_action(
                                self.state.turn, kind="secret_order", action=action,
                                minister_name=character.name, target_id=order_id,
                                payload=payload,
                            )
                elif tool_result.startswith("__secret_order__"):
                    payload_json = tool_result.removeprefix("__secret_order__").strip()
                    try:
                        payload = json.loads(payload_json) if payload_json else {}
                    except (ValueError, TypeError):
                        payload = {}
                    if isinstance(payload, dict):
                        result.pending_action_id = self.db.stage_pending_action(
                            self.state.turn, kind="secret_order", action="新建",
                            minister_name=character.name, target_id=None,
                            payload={
                                "title": str(payload.get("title") or "").strip(),
                                "content": str(payload.get("content") or "").strip(),
                                "assignee": str(payload.get("assignee") or character.name).strip(),
                                "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
                                "deadline_months": payload.get("deadline_months") or 0,
                                "excluded_names": payload.get("excluded_names") if isinstance(payload.get("excluded_names"), list) else [],
                                "excluded_offices": payload.get("excluded_offices") if isinstance(payload.get("excluded_offices"), list) else [],
                                "dossier_links": __import__(
                                    "ming_sim.cli_backend", fromlist=["confirm_dossier_links"]
                                ).confirm_dossier_links(
                                    answer,
                                    self.db.list_referenceable_dossiers(character.name, self.state.turn),
                                    payload.get("dossier_links"),
                                    llm_config=self.llm_config,
                                ),
                            },
                        )
                elif tool_result.startswith("__secret_order_registered__"):
                    try:
                        order_id = int(
                            tool_result.removeprefix("__secret_order_registered__").split("__", 1)[0]
                        )
                    except Exception:
                        order_id = 0
                    if order_id:
                        result.pending_action_id = self._stage_legacy_registered_secret_order(
                            order_id, character.name)
        # CLI 后端（agy/codex）：玩家用拟旨/密令按钮（消息带前缀）时，把大臣这句回话原文入档。
        self._cli_backend_fallback_actions(
            result, character, message,
            preclassified_intent=preclassified_intent,
            confirm_target_ids=preexisting_pending_action_ids,
        )
        return result

    def _audience_prompt_for_message(self, message: str, character: Character, *, chat_turn_id: int = 0) -> str:
        # Chapter summaries are a global narrative cache and may contain secret
        # or off-stage facts.  Character knowledge is the only audience input
        # allowed to cross this boundary; public reports are projected there
        # with their source-level exclusions applied.
        augmented = message
        try:
            knowledge = self.db.get_character_knowledge(self.state, character.name)
        except Exception:
            # Legacy projection trouble may fall back to ordinary chat, but it
            # must be visible rather than silently authorising a factual reply.
            return "【近臣回奏暂不可用：见闻记录读取失败；不得据此臆答事实。】\n\n" + message
        if (
            is_inner_court_attendant(character)
            and any(word in message for word in ("官缺", "巡抚", "总督", "督抚", "欠饷", "军情", "敌情", "流寇", "贼情", "查访"))
        ):
            try:
                # The report is written to the durable, character-scoped
                # knowledge source before rebuilding the projection.  This
                # prevents a keyword hit from injecting a global snapshot into
                # every minister's prompt and leaves restore with the same
                # source/audience boundary.
                self.db.persist_return_report(
                    self.state, character.name, message,
                    chat_turn_id=chat_turn_id,
                )
                knowledge = self.db.get_character_knowledge(self.state, character.name)
            except Exception:
                return "【近臣回奏暂不可用：查访未能持久留档；不得据此臆答事实。】\n\n" + message
        try:
            brief = render_character_knowledge(knowledge, character.name)
        except Exception:
            return "【近臣回奏暂不可用：见闻投影失败；不得据此臆答事实。】\n\n" + message
        if brief:
            augmented = brief + "\n\n" + augmented
        candidates = self.db.list_referenceable_dossiers(character.name, self.state.turn)
        if candidates:
            dossier_brief = "【可参考既有旨意（若有关联，请按标题或事项复述；勿向陛下念内部编号）】\n" + "\n".join(
                f"- [内部键 {int(row['id'])}] {row.get('secret_title') or row.get('decree_text') or row.get('action_type') or ''}"
                for row in candidates
            )
            augmented = dossier_brief + "\n\n" + augmented
        # 连场 presence-aware（#507 / ADR 0035）：宣下一个不断场、前一位留殿侧侍立时，
        # 对话流按在场名单送入组装——在场者补话可引用其在场时段殿上公开对话，未在场者
        # 的组装输入不含殿内对话（区间取数复用 audible_entries_for，御前低语不流入）。
        try:
            from ming_sim.audience_night import audience_scene_recap
            recap = audience_scene_recap(self.db, character.name)
        except Exception:
            recap = ""
        if recap:
            augmented = recap + "\n\n" + augmented
        # 未明发草案不属于公开层；参与者/知情圈须通过持久见闻事件投影进入提示。
        # 这里不能直接读取 registry 的全局草案列表，否则未参与大臣会越过排除边界获知密事。
        return augmented

    def apply_cli_conversation_actions(
        self, character: Character, player_message: str, answer: str,
        has_directive: bool, secret_order_id: Optional[int],
        preclassified_intent: Optional[Any] = None,
        confirm_target_ids: Optional[set[int]] = None,
    ) -> Dict[str, Any]:
        """CLI 后端（无 function-calling）会话落地的【唯一真源】，session.chat 非流式路径与
        web streaming 路径共用，杜绝两边逻辑漂移（CMR F3 / codexC-1）。

        做三件事：① 前缀「拟旨」→ pending directive；② 前缀「密令」→ pending
        secret_order 新建候选；③ 无前缀时只按 LLM 结构化判词物化会话动作并暂存。
        入参 has_directive / secret_order_id 表示 agno 工具路径是否已产出（已产则不重复）。
        返回 {"directive": {id,text,status,notes}|None, "secret_order_id": int|None}。

        #515：preclassified_intent 接受 list（生产契约）或 dict（测试/旧注入）；
        None = 分类器未跑（串行回落）；[] = 已跑无动作（零 classifier 写入）。
        """
        from ming_sim.cli_backend import (
            _DRAFT_PREFIXES, _SECRET_PREFIXES,
            cli_backend_from_env, resolve_minister_actions,
            extract_confirmation_intent,
            extract_directive_confirmation,
        )
        from ming_sim.action_clusters import (
            EFFECT_ANSWER_EXISTING,
            cluster_effect,
            normalize_intent_candidates,
            resolve_primary_intent,
        )
        out: Dict[str, Any] = {
            "directive": None,
            "secret_order_id": secret_order_id,
            "pending_action_failures": [],
        }
        intent_candidates = normalize_intent_candidates(preclassified_intent)
        intent = resolve_primary_intent(intent_candidates)
        # intent is None only when classifier did not run; [] → primary {kind:none}.
        intent_kind = str((intent or {}).get("kind") or "none")
        minister_name = character.name
        reply = (answer or "").strip()
        llm_config = getattr(self, "llm_config", None)
        # 显式前缀(拟旨如下:/密令如下:)= 皇帝已明示动作，由 resolve_minister_actions 零 LLM 落地。
        # 单一真源在此前置判定，统一把门【所有】后置 LLM 抽取器（确认/密令/调教/拟旨/任免），
        # 杜绝前缀路多跑任何 LLM extractor（#344 US3「按钮前缀路零 LLM」）。确认闸门尤其要跳过：
        # 否则前缀消息在有 pending 待确认动作时既多跑 extract_confirmation_intent(LLM)，还可能被
        # 误判「应允/拒绝」提前 return、把这道前缀拟旨/密令整个吞掉（确认句本无前缀，跳过无损）。
        message_text = (player_message or "").strip()
        explicit_prefixed = message_text.startswith(_DRAFT_PREFIXES) or message_text.startswith(_SECRET_PREFIXES)
        channel = (getattr(getattr(self, "llm_config", None), "channel", "") or "").strip().lower()
        api_explicit_prefix = channel == "api" and explicit_prefixed
        api_or_no_cli_passthrough = (
            channel != "cli" and (channel == "api" or cli_backend_from_env() is None) and not api_explicit_prefix
        )
        # 对话确认(ADR 0006 重设计)：本召对的大臣有上一轮经领命确认、尚未落库的暂存动作时，
        # 皇帝这句应允 → 当场 commit、拒绝 → 丢、未表态 → 留(颁诏对没回的算同意)。
        # 只在该大臣有 outstanding 暂存时才判(省 token)，commit/drop 按该大臣过滤、不波及他人。
        pend_for_minister = self.db.list_pending_actions(
            self.state.turn, minister_name=minister_name)
        if confirm_target_ids is not None:
            allowed_confirm_ids = {int(pid) for pid in confirm_target_ids}
            pend_for_minister = [p for p in pend_for_minister if int(p["id"]) in allowed_confirm_ids]
        # 同一大臣同时有非 directive 暂存与 directive 草案时，普通确认仍优先处理非 directive；
        # 明说拟旨/圣旨则只处理 directive，明说“都/一并”或同时点名两族才同句处理两族。
        confirm_targets = _confirmation_targets_for_message(pend_for_minister, message_text)
        directive_confirm_targets = [p for p in confirm_targets if p["kind"] == "directive"]
        if confirm_targets and not explicit_prefixed:
            confirm_action_ids = {int(p["id"]) for p in confirm_targets}
            summaries = [_pending_action_brief(p) for p in confirm_targets]
            if intent is not None:
                confirm = (
                    str(intent.get("confirmation") or "无")
                    if cluster_effect(intent_kind) == EFFECT_ANSWER_EXISTING
                    else "无"
                )
                if confirm not in ("应允", "拒绝", "无"):
                    confirm = "无"
            else:
                confirm = extract_confirmation_intent(
                    player_message, reply, summaries, llm_config=llm_config)
            # 多道并存（#502 AC4/AC5）：≥2 道 directive 候选时，口头准驳须指向具体某道。
            # 点名指认 → 只作用那几道 + 清全组待澄清标（含糊 episode 了结）；否则（含糊/无/
            # 空指向）一律按含糊处置——结构化含糊态 + 追问 + 标待澄清 + **本轮不再 stage 新拟旨**，
            # 直接 return（L1：删 else free-fall，杜绝纯准驳口令误建第三道）。
            if confirm in ("应允", "拒绝") and len(directive_confirm_targets) >= 2:
                dir_cands = [
                    {"id": int(p["id"]), "summary": _pending_action_brief(p)}
                    for p in directive_confirm_targets
                ]
                res = extract_directive_confirmation(
                    player_message, reply, dir_cands, llm_config=llm_config)
                decision = res.get("decision")
                tids = {int(i) for i in (res.get("target_ids") or [])}
                named = decision in ("应允", "拒绝") and bool(tids)
                if named:
                    # 指明了哪道：清全组待澄清标（未点名兄弟复位普通 pending、重回「不回→默认同意」；
                    # L4 兑现 docstring「下一句指明后清标」），confirm 收窄为点名那几道。
                    for p in directive_confirm_targets:
                        self.db.clear_directive_needs_clarification(int(p["id"]))
                    confirm = decision
                    directive_confirm_targets = [
                        p for p in directive_confirm_targets if int(p["id"]) in tids]
                    confirm_targets = [
                        p for p in confirm_targets
                        if p["kind"] != "directive" or int(p["id"]) in tids]
                    confirm_action_ids = {int(p["id"]) for p in confirm_targets}
                else:
                    out["directive_confirmation_ambiguous"] = {"candidates": dir_cands}
                    for p in directive_confirm_targets:
                        self.db.flag_directive_needs_clarification(int(p["id"]))
                    return out
            if confirm == "应允":
                # 确认轮仍是皇帝权威：只为有效对象补确认元数据；载荷有效性及失败状态
                # 仍由 commit_pending_actions 拥有，坏 JSON/非对象必须原样交给该终端。
                from ming_sim.cli_backend import resolve_directive_mode
                from ming_sim.audience_night import get_open_night, mark_actions_night_approved
                recovery_confirmation = self.state.turn_phase in FRONT_HALF_DONE_PHASES
                open_n = None if recovery_confirmation else get_open_night(self.db)
                valid_payloads = {}
                for pending in confirm_targets:
                    if pending["kind"] not in {"directive", "office"}:
                        continue
                    try:
                        payload = json.loads(pending.get("payload_json"))
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    payload["mode"] = resolve_directive_mode(
                        player_message, existing=payload.get("mode"),
                    )
                    if pending["kind"] == "directive" and (
                            recovery_confirmation or open_n is not None):
                        payload["_directive_status"] = "pending"
                        payload.pop("_needs_clarification", None)
                    valid_payloads[int(pending["id"])] = (pending, payload)
                for pending_id, (pending, payload) in valid_payloads.items():
                    encoded_payload = json.dumps(payload, ensure_ascii=False)
                    self.db.conn.execute(
                        "UPDATE pending_actions SET payload_json=? WHERE id=?",
                        (encoded_payload, pending_id),
                    )
                    pending["payload_json"] = encoded_payload
                if valid_payloads:
                    self.db.conn.commit()

                if not recovery_confirmation:
                    # 恢复窗确认不进此分支：动作留 pending，由推进回合的终端 atomic 统一落，
                    # 避免事务外落真表后 settle 中止造成半写（所有权规则，ship-pre r2）。
                    # #498 / ADR 0038：开夜期间 office/consort/directive 应允 = 标 night_approved，
                    # 收夜才提交；密令仍应允即落地（白名单直写）。无开夜则保持历史即时 commit。
                    if open_n is not None:
                        defer_ids = {
                            int(p["id"]) for p in confirm_targets
                            if p["kind"] in {"office", "consort", "directive"}
                        }
                        immediate_ids = confirm_action_ids - defer_ids
                        if defer_ids:
                            mark_actions_night_approved(
                                self.db, sorted(defer_ids), night_id=int(open_n["id"]))
                        if immediate_ids:
                            self.db.commit_pending_actions(
                                self.state, minister_name=minister_name,
                                action_ids=immediate_ids,
                                content=getattr(self, "content", None),
                                registry=getattr(self, "registry", None))
                    else:
                        self.db.commit_pending_actions(
                            self.state, minister_name=minister_name,
                            directive_status="pending" if directive_confirm_targets else "draft",
                            action_ids=confirm_action_ids,
                            content=getattr(self, "content", None),
                            registry=getattr(self, "registry", None))
                    failures = [
                        _pending_action_failure_payload(p)
                        for p in self.db.list_pending_actions(
                            int(self.state.turn), status="failed", minister_name=minister_name)
                        if int(p["id"]) in confirm_action_ids
                    ]
                    if failures:
                        out["pending_action_failures"] = failures
            elif confirm == "拒绝":
                self.db.drop_pending_actions_for_minister(
                    self.state.turn, minister_name,
                    action_ids=confirm_action_ids)
            if confirm in ("应允", "拒绝"):
                # 本轮是对暂存的确认：大臣回话已【复述】该动作(领命 prompt 所致),若继续走下面的
                # 抽取,会把刚 commit 的动作从复述里重抽成新暂存→颁诏二次落库,或重建刚拒的动作。
                # 故确认轮直接返回,不再抽新动作(线上 codex P2)。确认句无前缀,前缀路无损失。
                return out
        if api_or_no_cli_passthrough:
            return out
        if GameSession._proposal_blocked(self.state):
            # 恢复窗总闸（PR #90 R1/R2/R3 收束为单一出口）：前缀拟旨/密令与自然语言
            # 抽取的新暂存（密令动作/调教/任免）一并婉拒——窗内新写在 settle 重试事务
            # 边界外，窗内新 stage 则会被重试 settle 的 commit_pending_actions 落进
            # 「保存的 delta 推演时并不知道」的旧回合。上方对话确认块（应允延迟提交/
            # 拒绝丢弃）针对的是窗前已暂存的 pending，保持可用（ship-pre r2 设计）。
            # 抽取器（LLM 调用）一并跳过。
            return out
        active_orders = self.db.get_active_secret_orders_for_minister(minister_name)
        is_consort = getattr(character, "office_type", "") == "后宫"
        from ming_sim.cli_backend import cli_backend_active, cli_backend_parallel_safe
        if (
            intent is None
            and not explicit_prefixed
            and cli_backend_active(llm_config)
            and not cli_backend_parallel_safe(llm_config)
        ):
            # 非并发安全 CLI runner（agy/claude）不在回话同时启动 classifier；
            # 故回话完成后串行跑同一结构化判词缝。是否串行只由实际 runtime
            # route 决定，不能让既有密令/妃嫔等业务状态吞掉 fresh action。
            from ming_sim.cli_backend import classify_cli_action_intent

            has_pending_draft = any(p["kind"] == "directive" for p in pend_for_minister)
            serial_candidates = classify_cli_action_intent(
                message_text,
                active_orders,
                is_consort,
                has_pending_draft,
                [_pending_action_brief(p) for p in confirm_targets],
                llm_config,
            )
            # 空判词仍保留既有任免结构化 extractor 兜底；只有 classifier
            # 真给出候选时才阻断后续类别专用 extractor。
            if serial_candidates:
                intent_candidates = serial_candidates
                intent = resolve_primary_intent(intent_candidates)
                intent_kind = str((intent or {}).get("kind") or "none")
        needs_draft_fallback = not has_directive and message_text.startswith(_DRAFT_PREFIXES)
        needs_secret_fallback = (
            not has_directive
            and not out["secret_order_id"]
            and message_text.startswith(_SECRET_PREFIXES)
        )
        secret_context = ""
        if needs_secret_fallback:
            secret_context = _recent_audience_context_for_secret_order(
                getattr(self, "db", None), minister_name, int(self.state.turn), message_text)
        if needs_draft_fallback or needs_secret_fallback:
            acts = resolve_minister_actions(
                reply, player_message, default_assignee=minister_name, llm_config=llm_config,
                secret_context=secret_context,
                dossier_candidates=self.db.list_referenceable_dossiers(
                    minister_name, self.state.turn))
        else:
            acts = {"decree_text": None, "secret_order": None}
        if not has_directive and acts["decree_text"]:
            # #502 L2：前缀「拟旨如下：」显式拟旨走单一 seam——已有候选则新拟独立一道，不压扁前道。
            out["pending_action_id"] = self.db.stage_explicit_directive(
                self.state.turn, minister_name, acts["decree_text"], mode=message_text)
        def _stage_secret_order_candidate(so: Dict[str, Any]) -> int:
            assignee = so.get("assignee") or minister_name
            return self.db.stage_pending_action(
                self.state.turn, kind="secret_order", action="新建",
                minister_name=minister_name, target_id=None,
                payload={
                    "title": so["title"],
                    "content": so["content"],
                    "assignee": assignee,
                    "tags": so.get("tags") or [],
                    "deadline_months": so.get("deadline_months", 0),
                    "excluded_names": so.get("excluded_names") or [],
                    "excluded_offices": so.get("excluded_offices") or [],
                    # The extractor emits only links explicitly narrowed in the
                    # minister's confirmation; carry that immutable set to commit.
                    "dossier_links": so.get("dossier_links") or [],
                },
            )
        if not out["secret_order_id"] and acts["secret_order"]:
            out["pending_action_id"] = _stage_secret_order_candidate(acts["secret_order"])

        # #515：登记表驱动物化——handler 挂在 ACTION_CLUSTERS 行上；pipeline 只读表。
        import ming_sim.action_materialize  # noqa: F401 — install catalog
        from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
        mat_ctx = MaterializeCtx(
            session=self,
            character=character,
            player_message=player_message,
            reply=reply,
            message_text=message_text,
            explicit_prefixed=explicit_prefixed,
            has_directive=has_directive,
            pend_for_minister=pend_for_minister,
            out=out,
            intent=intent,
            intent_kind=intent_kind,
            llm_config=llm_config,
            intent_candidates=intent_candidates,
        )
        run_materialize_pipeline(mat_ctx)
        return out

    @staticmethod
    def _ensure_confirmation_cue(answer: str) -> str:
        """Pending chat actions must visibly ask the emperor to approve/reject."""
        text = (answer or "").strip()
        if not text:
            return "臣已拟妥，请陛下定夺准驳。"
        if any(term in text for term in (
            "定夺", "准驳", "准否", "准不准", "请旨", "是否准",
        )):
            return text
        return text + "\n请陛下定夺准驳。"

    @staticmethod
    def _ensure_clarification_cue(answer: str, ambiguous: Dict[str, Any]) -> str:
        """#502 AC5：多道并存、准驳指称含糊时，大臣当场追问是哪一道（确定性 post-pass 句，
        不串 LLM）。列出候选摘要供皇帝指名，避免被静默当「不回」。"""
        text = (answer or "").strip()
        cands = (ambiguous or {}).get("candidates") or []
        briefs = "；".join(
            f"其一「{str(c.get('summary') or '')}」" if i == 0 else f"其{'二三四五六七八九十'[i-1] if i <= 9 else i}「{str(c.get('summary') or '')}」"
            for i, c in enumerate(cands)
        )
        ask = f"陛下方才所指，是这几道中的哪一道？（{briefs}）请明示，臣好照办。" if briefs else "陛下方才所指是哪一道？请明示。"
        if not text:
            return ask
        return text + "\n" + ask

    @staticmethod
    def _normalized_content_key(text: str) -> str:
        return "".join(ch for ch in (text or "") if ch.isalnum())

    @staticmethod
    def _secret_order_command_material(player_message: str) -> str:
        from ming_sim.cli_backend import _SECRET_PREFIXES

        text = (player_message or "").strip()
        for prefix in _SECRET_PREFIXES:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    def _merge_staged_new_secret_order_content(
        self, pending_action_id: int, minister_name: str, player_message: str, minister_reply: str,
    ) -> None:
        """Tool/API staged new secret orders still need the reply-merge content contract."""
        if not pending_action_id:
            return
        row = self.db.conn.execute(
            "SELECT * FROM pending_actions WHERE id=?",
            (int(pending_action_id),),
        ).fetchone()
        if row is None:
            return
        if (
            row["status"] != "pending"
            or row["kind"] != "secret_order"
            or row["action"] != "新建"
            or str(row["minister_name"] or "") != str(minister_name or "")
        ):
            return
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            return
        content = str(payload.get("content") or "").strip()
        command = GameSession._secret_order_command_material(player_message)
        reply = (minister_reply or "").strip()
        existing_key = GameSession._normalized_content_key(content)
        parts = [content]
        changed = False
        for material in (command, reply):
            material_key = GameSession._normalized_content_key(material)
            if material_key and material_key not in existing_key:
                parts.append(material)
        if len(parts) > 1:
            from ming_sim.cli_backend import _merge_secret_content

            payload["content"] = _merge_secret_content(*parts)
            changed = True
        from ming_sim.cli_backend import _choose_assignee, _secret_metadata_from_command

        assignee = _choose_assignee(
            str(payload.get("assignee") or ""),
            command,
            reply,
            str(payload.get("content") or ""),
            minister_name,
        )
        if assignee and assignee != str(payload.get("assignee") or ""):
            payload["assignee"] = assignee
            changed = True

        fallback_tags, fallback_deadline = _secret_metadata_from_command(command)
        tags = payload.get("tags")
        if fallback_tags and not (isinstance(tags, list) and any(str(t).strip() for t in tags)):
            payload["tags"] = fallback_tags
            changed = True
        raw_deadline = payload.get("deadline_months")
        explicit_zero_deadline = raw_deadline in (0, "0")
        try:
            deadline = int(raw_deadline or 0)
        except (TypeError, ValueError):
            deadline = 0
        if fallback_deadline and not deadline and not explicit_zero_deadline:
            payload["deadline_months"] = fallback_deadline
            changed = True
        if not changed:
            return
        self.db.conn.execute(
            "UPDATE pending_actions SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), int(row["id"])),
        )
        if not bool(getattr(self.db.conn, "_commit_suspended", False)) and int(
            getattr(self.db.conn, "_atomic_depth", 0) or 0
        ) <= 0:
            self.db.conn.commit()

    def _cli_backend_fallback_actions(
        self, result: "ChatTurnResult", character: Character, player_message: str = "",
        preclassified_intent: Optional[Any] = None,
        confirm_target_ids: Optional[set[int]] = None,
    ) -> None:
        """session.chat 非流式路径：调共享会话落地，映射回 ChatTurnResult（agno 工具不触发时）。"""
        preexisting_pending_id = int(getattr(result, "pending_action_id", 0) or 0)
        res = self.apply_cli_conversation_actions(
            character, player_message, result.answer or "",
            has_directive=result.proposed_directive is not None or bool(result.pending_action_id),
            secret_order_id=result.secret_order_id,
            preclassified_intent=preclassified_intent,
            confirm_target_ids=confirm_target_ids,
        )
        if result.proposed_directive is None and res["directive"]:
            d = res["directive"]
            result.proposed_directive = DirectiveView(
                id=d["id"], text=d["text"], status=d["status"],
                source="大臣拟旨", notes=d["notes"],
            )
        if res["secret_order_id"]:
            result.secret_order_id = res["secret_order_id"]
        if res.get("pending_action_id"):
            # 非流式路径与流式同 surface 暂存信号,杜绝两边漂移(ship-pre CMR)。
            result.pending_action_id = res["pending_action_id"]
        if getattr(result, "pending_action_id", 0):
            if preexisting_pending_id:
                self._merge_staged_new_secret_order_content(
                    preexisting_pending_id,
                    character.name,
                    player_message,
                    result.answer or "",
                )
            result.answer = GameSession._ensure_confirmation_cue(result.answer or "")
        if res.get("pending_action_failures"):
            result.pending_action_failures = list(res["pending_action_failures"])
        # #502 AC5：把结构化含糊态透到 ChatTurnResult，供大臣当场追问哪一道（表面契约可达）。
        if res.get("directive_confirmation_ambiguous"):
            result.directive_confirmation_ambiguous = res["directive_confirmation_ambiguous"]
            result.answer = GameSession._ensure_clarification_cue(
                result.answer or "", res["directive_confirmation_ambiguous"])

    def _apply_appointment(self, payload: str, appointer: Character) -> Tuple[str, str]:
        """吏部 propose_appointment 落地：建档入库 + 注册 Agent，本回合即可召见。
        吏部尚书 LLM 已判过史实合理性；代码端只做姓名查重与字段兜底，不做历史校验。
        返回 (新任者姓名, 被腾缺罢黜者姓名)；payload 不合法或重名则返回 ("", "")。

        恢复窗婉拒（PR #90 R2 codex P2）：FRONT_HALF_DONE 时不落地——此写在 settle
        重试事务边界外，重放中止回滚不会回滚它=恢复窗改盘。session.chat 与 web
        流式路都委托本方法，顶部守门一处覆盖两路（与 draft 的 _proposal_blocked 同例）。"""
        if self._proposal_blocked(self.state):
            return ("", "")
        import json as _json
        try:
            data = _json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            return ("", "")
        return apply_appointment(self.db, self.state, self.content, self.registry, data, llm_config=self.llm_config)

    def _stage_appointment_candidate(
        self, payload: str, appointer: Character, message_text: str,
    ) -> int:
        """把吏部 propose_appointment 工具结果接入与口头任免相同的确认闸门。"""
        if GameSession._proposal_blocked(self.state):
            return 0
        import json as _json
        try:
            data = _json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            return 0
        if not isinstance(data, dict):
            return 0
        name = str(data.get("name") or data.get("姓名") or "").strip()[:20]
        office = str(data.get("office") or data.get("官职") or "").strip()[:40]
        action = str(data.get("action") or data.get("任免动作") or "任命").strip()
        if action not in {"任命", "罢免"}:
            action = "任命"
        if not name:
            return 0
        if action == "任命" and not office:
            return 0
        staged_payload = {"name": name, "office": office, "appointer": appointer.name}
        from ming_sim.cli_backend import resolve_directive_mode
        staged_payload["mode"] = resolve_directive_mode(
            message_text, data.get("mode") or data.get("颁布方式"),
        )
        metadata_aliases = {
            "office_type": "官署类别",
            "faction": "派系",
            "reason": "理由",
            "replaces": "腾缺",
        }
        for key in ("office_type", "faction", "reason", "replaces"):
            value = str(data.get(key) or data.get(metadata_aliases[key]) or "").strip()
            if value:
                staged_payload[key] = value
        recommendation = data.get("recommendation")
        if isinstance(recommendation, dict):
            staged_payload["recommendation"] = recommendation
        return self.db.stage_pending_action(
            self.state.turn,
            kind="office",
            action=action,
            minister_name=appointer.name,
            target_id=None,
            payload=staged_payload,
        )

    def _apply_unlisted_person_registration(self, payload: str) -> Tuple[str, bool]:
        """登记史实未预设/用户确认背景的人物，进入本局正式可召见人物池。

        恢复窗婉拒（PR #90 R2 codex P2）：同 _apply_appointment，事务边界外直写一律冻。"""
        if self._proposal_blocked(self.state):
            return ("", False)
        import json as _json
        try:
            data = _json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            return ("", False)
        if not isinstance(data, dict):
            return ("", False)
        name = str(data.get("name") or "").strip()
        office = str(data.get("office") or "").strip()
        office_type = str(data.get("office_type") or "").strip()
        if not name or not office or not office_type:
            return ("", False)
        aliases_raw = data.get("aliases") or []
        aliases = [str(alias).strip() for alias in aliases_raw if str(alias).strip()] if isinstance(aliases_raw, list) else []
        if _find_existing_minister(self.content, name, self.db) is not None:
            return ("", False)
        for alias in aliases:
            if _find_existing_minister(self.content, alias, self.db) is not None:
                return ("", False)
        faction = str(data.get("faction") or "中立").strip()
        if faction not in self.content.factions:
            faction = "中立"
        source_kind = str(data.get("source") or "historical").strip()
        if source_kind == "historical":
            source_label = "史实人物补档"
            style = "史实补档，待召对细察"
            loyalty = 62
        elif source_kind == "user_confirmed":
            source_label = "皇帝确认背景补档"
            style = "陛下点名，底细待察"
            loyalty = 60
        else:
            source_label = "名册外人物补档"
            style = "名册外补档，待召对细察"
            loyalty = 60
        character = Character(
            name=name,
            office=office,
            office_type=office_type,
            faction=faction,
            aliases=aliases,
            personal_skills=[],
            loyalty=loyalty,
            ability=55,
            integrity=60,
            courage=55,
            style=style,
            power_id="ming",
            status="active",
            summary=str(data.get("summary") or "").strip(),
        )
        self.content.characters[name] = character
        self.db.add_character(self.state, character, source=source_label, llm_config=self.llm_config)
        row = self.db.conn.execute(
            "SELECT portrait_id FROM characters WHERE name=?", (name,)
        ).fetchone()
        if row:
            character.portrait_id = str(row["portrait_id"])
        if self.registry is not None:
            self.registry.register(character)
        self.temporary_characters.pop(name, None)
        return (name, bool(data.get("summon_after", True)))

    def _apply_secret_order(self, payload: str, minister_name: str) -> int:
        """issue_secret_order 哨兵落库，返回新建密令 id（失败返回 0）。"""
        import json as _json
        try:
            data = _json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            return 0
        if not isinstance(data, dict):
            return 0
        # No formal title hard-cap (align with tools/web extract paths).
        title = str(data.get("title") or "").strip()
        content = str(data.get("content") or "").strip()
        if not title or not content:
            return 0
        tags_raw = data.get("tags") or []
        tags = [str(k).strip() for k in tags_raw if str(k).strip()] if isinstance(tags_raw, list) else []
        assignee = str(data.get("assignee") or "").strip() or minister_name
        try:
            deadline = max(0, min(int(data.get("deadline_months") or 0), 36))
        except (TypeError, ValueError):
            deadline = 0
        print(f"[secret_order] 截获密令 minister={minister_name} assignee={assignee} title={title!r} tags={tags}")
        excluded = data.get("excluded_names") if isinstance(data.get("excluded_names"), list) else []
        excluded_offices = data.get("excluded_offices") if isinstance(data.get("excluded_offices"), list) else []
        return self.db.create_secret_order(
            self.state, assignee, title, content, tags, deadline_months=deadline,
            excluded_names=excluded, excluded_offices=excluded_offices,
            # minister_name = audience speaker (may differ from assignee).
            origin_minister_name=minister_name,
        )

    def _stage_legacy_registered_secret_order(self, order_id: int, fallback_minister: str) -> int:
        """Convert a legacy already-registered same-turn secret order into a pending candidate.

        Older tool results used `__secret_order_registered__<id>__` after directly creating
        `secret_orders`. #413 requires those requests to pass through audience confirmation.
        """
        if GameSession._proposal_blocked(self.state):
            return 0
        row = self.db.conn.execute(
            "SELECT * FROM secret_orders WHERE id=?", (int(order_id),)
        ).fetchone()
        if row is None:
            return 0
        if str(row["status"] or "") != "active" or int(row["turn_issued"] or 0) != int(self.state.turn):
            return 0
        try:
            tags = json.loads(row["tags"] or "[]")
        except (ValueError, TypeError):
            tags = []
        if not isinstance(tags, list):
            tags = []
        try:
            excluded_names = json.loads(row["excluded_names"] or "[]")
        except (ValueError, TypeError):
            excluded_names = []
        if not isinstance(excluded_names, list):
            excluded_names = []
        try:
            excluded_targets = json.loads(row["excluded_targets"] or "{}")
        except (ValueError, TypeError):
            excluded_targets = {}
        if not isinstance(excluded_targets, dict):
            excluded_targets = {}
        excluded_offices = excluded_targets.get("offices") or []
        if not isinstance(excluded_offices, list):
            excluded_offices = []
        due_turn = int(row["due_turn"] or 0)
        deadline = max(0, due_turn - int(self.state.turn)) if due_turn else 0
        from ming_sim.applier import atomic

        with atomic(self.db):
            pending_id = self.db.stage_pending_action(
                self.state.turn, kind="secret_order", action="新建",
                minister_name=str(fallback_minister or row["minister_name"] or ""),
                target_id=None,
                payload={
                    "title": str(row["title"] or "").strip(),
                    "content": str(row["content"] or "").strip(),
                    "assignee": str(row["minister_name"] or fallback_minister or "").strip(),
                    "tags": [str(t).strip() for t in tags if str(t).strip()],
                    "deadline_months": deadline,
                    "excluded_names": [str(name).strip() for name in excluded_names if str(name).strip()],
                    "excluded_offices": [str(office).strip() for office in excluded_offices if str(office).strip()],
                },
            )
            cur = self.db.conn.execute(
                "DELETE FROM secret_orders WHERE id=? AND status='active' AND turn_issued=?",
                (int(order_id), int(self.state.turn)),
            )
            if cur.rowcount != 1:
                raise RuntimeError("legacy secret order conversion lost source row")
            self.db.conn.execute(
                "DELETE FROM character_knowledge_sources WHERE source_id=?",
                (f"secret_order:{int(order_id)}",),
            )
            self.db.conn.execute(
                "DELETE FROM secret_order_briefs WHERE order_id=?", (int(order_id),)
            )
        return pending_id

    def _apply_close_secret_order(self, payload: str) -> None:
        """report_secret_order_result 哨兵落库。"""
        import json as _json
        try:
            data = _json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        order_id = int(data.get("order_id") or 0)
        status = str(data.get("status") or "")
        result = str(data.get("result") or "")
        if order_id and status in {"done", "failed"}:
            print(f"[secret_order] 结案 id={order_id} status={status} result={result!r}")
            self.db.close_secret_order(order_id, status, result, self.state.turn)

    # ── 拟旨 / 草案阶段 ───────────────────────────────────────────────────

    def list_directives(self, include_pending: bool = True) -> List[DirectiveView]:
        statuses = ("pending", "draft") if include_pending else ("draft",)
        rows = self.db.list_directives(self.state, statuses=statuses)
        return [
            DirectiveView(
                id=int(r["id"]), text=str(r["text"]), status=str(r["status"]),
                source=str(r["source"] or ""), notes=str(r["notes"] or ""),
                actor=str(r["actor"] or ""),
            )
            for r in rows
        ]

    @staticmethod
    def _proposal_blocked(state) -> bool:
        """FRONT_HALF_DONE 时 chat 提案不得插 pending directive（ship-pre r2 软死锁环源头）：
        pending>0 让推进口全拒「请准/驳」而 confirm/reject 已冻结=互相指对方死锁且落盘。
        正常入 settling 时 pending 必为 0（resolve 口有门），源头堵死即环断。"""
        return state.turn_phase in FRONT_HALF_DONE_PHASES

    def _refuse_if_settling(self) -> None:
        """FRONT_HALF_DONE 冻结诏稿变更：恢复窗口新增/确认的 draft 会被 settle 的
        mark_directives_issued 连带标 issued，而重放 delta 不含它们=幽灵颁布（ship-pre r1）。"""
        if self.state.turn_phase in FRONT_HALF_DONE_PHASES:
            raise ValueError("月末结算进行中（恢复态），请先完成结算再改诏稿。")

    def confirm_directive(self, directive_id: int) -> None:
        self._refuse_if_settling()
        self.db.confirm_directive(directive_id, self.state)

    def reject_directive(self, directive_id: int) -> None:
        self._refuse_if_settling()
        self.db.reject_directive(directive_id)

    def add_directive(
        self, text: str, notes: str = "",
        dossier_payload: Optional[Dict[str, object]] = None,
    ) -> DirectiveView:
        self._refuse_if_settling()
        payload = dict(dossier_payload or {})
        if not all(str(payload.get(key) or "").strip() for key in (
            "dossier_action_type", "target_kind", "target_id",
        )):
            raise ValueError("新增旨意须由上游提供完整结构化动作与目标")
        directive_id = self.db.add_directive(
            self.state, None, text, "手动新增", notes=notes,
            dossier_payload=payload,
        )
        return DirectiveView(id=directive_id, text=text, status="draft",
                             source="手动新增", notes=notes)

    def update_directive(
        self, directive_id: int, text: str, *,
        dossier_payload: Optional[Dict[str, object]] = None,
    ) -> None:
        self._refuse_if_settling()
        self.db.update_directive_text(
            directive_id, text, dossier_payload=dossier_payload,
        )

    def delete_directive(self, directive_id: int) -> None:
        self._refuse_if_settling()
        self.db.delete_directive(directive_id)

    def pending_count(self) -> int:
        return self.db.count_pending_directives(self.state)

    # ── 诏书阶段 ──────────────────────────────────────────────────────────

    def enter_review(self) -> None:
        # 前半段已提交相位粘滞（FRONT_HALF_DONE_PHASES 单一真源）：被抹成 reviewing 会让
        # pre_settle 守门失效=同回合二次财政 tick，awaiting 还会令 submit_decisions 拒收
        # =决策搁浅（cmr S4 r1/r3）。只能由 settle 完成路径复位。
        if self.state.turn_phase in FRONT_HALF_DONE_PHASES:
            return
        self._set_phase(TurnPhase.REVIEWING)

    def back_to_summoning(self) -> None:
        if self.state.turn_phase in FRONT_HALF_DONE_PHASES:
            return
        self._set_phase(TurnPhase.SUMMONING)

    def write_decree(self) -> str:
        """生成诏书。要求无 pending 残留、≥1 条 draft。"""
        if self.state.turn_phase == TurnPhase.AWAITING_DECISION.value:
            # -> str 契约：亲裁期不能拟诏，响亮拒绝走既有 ValueError 错误路径
            # （web 映射 400 / terminal 打印拟诏失败）。幂等返回决策点的守门在 resolve_turn。
            raise ValueError("当前在月末亲裁阶段，请先裁决已存决策点，不能拟诏。")
        self._refuse_if_settling()
        # #498 AC8：拟诏（write_decree）不是收夜触发器——收夜只在真实颁诏/过回合边界
        # （resolve_turn / advance_without_edict）发生。夜内可拟多道旨并继续斟酌（#497/#502）。
        # 守门须早于 commit（BUG 2）：有未核定的显式 pending directive 时，先响亮拒绝，
        # 再 commit 对话式拟旨——否则被拒的调用已把对话草案落成 draft 副作用、无回滚。
        # 拟诏是 preview：只据已 draft 的候选生成诏书，绝不在此把未表态 pending 默认同意成 draft
        # （#497：未表态只到真实颁诏/过回合才 default-agree；拟诏改 pending status = 制造持久副作用）。
        # 无 draft 可预览 → 响亮拒绝，不为 preview 造持久态。
        directives = self.db.list_directives(self.state, statuses=("draft",))
        if not directives:
            raise ValueError("无草案不能拟诏（未表态拟旨须先准驳，或于颁诏时默认同意）。")
        decree = write_decree_with_agno(self.llm_config, self.agno_db, self.state, directives, db=self.db)
        self.last_decree = decree
        # P1-1：记下本份生成稿覆盖的 draft 集指纹。颁诏时若 draft 集已变（玩家拟诏后又新建
        # 草案），凭此判定 last_decree 已陈旧、强制重生成纳入新 draft，不许把新 draft 标记
        # 为已颁却不进诏书正文。
        self._decree_draft_fingerprint = self._draft_fingerprint(directives)
        return decree

    def set_decree(self, text: str) -> str:
        """兼容入口：非空最终正文一律拒绝；须由逐道旨意入口新增或修改旨稿。"""
        self._refuse_if_settling()
        text = (text or "").strip()
        if not text:
            raise ValueError("诏书正文不能为空。")
        raise ValueError("最终诏书正文不可单独设置；请使用逐道旨意入口新增或修改旨稿。")

    def resolve_turn(self, decree: str = "", on_event=None, cheat_directive: str = "",
                     inflight_wait_s: float | None = None) -> ResolveResult:
        """颁诏并推演本回合（phase1）。要求无 pending 残留、≥1 条 draft。

        on_event(kind, data): 推演过程实时回调，透传给 resolve_directives。
        cheat_directive: 作弊控制台强制结算项，一次性透传给 resolve_directives。

        返回 ResolveResult：含决策点 → awaiting=True，置 awaiting_decision 态，回合未推进，
        调用方据 result.decisions 弹窗，皇帝裁完调 submit_decisions。无决策点 → awaiting=False，
        回合已结算推进，置 issued 态。
        """
        if self.state.turn_phase in FRONT_HALF_DONE_PHASES and (
            self.db.list_directives(self.state, statuses=("pending",))
            or any(
                row.get("kind") == "directive"
                for row in self.db.list_pending_actions(self.state.turn)
            )
        ):
            raise ValueError("月末结算恢复期新增拟旨须先核定，不能并入已冻结的结算")
        if self.state.turn_phase == TurnPhase.AWAITING_DECISION.value:
            # HITL 暂停期重发 issue：幂等返回已存决策点，不二跑 simulator——二跑会覆盖
            # pending_decisions，或第二次输出无决策块时绕过亲裁直接结算（cmr S4 r3 F3）。
            return ResolveResult(
                awaiting=True, decisions=self.db.list_pending_decisions(self.state.turn))
        # ADR 0008 S7（决定 3）：settling 态崩溃恢复分流。settling 只意味着「前半段已完成」，
        # 不意味着后半段就绪——查 resolve_context 判别：
        #   有 ready context（extractor 已产出并 persist）→ 直入 apply，不重跑贵的 simulator/
        #     extractor（验收③的对偶：跨进程恢复从真源重灌）。完成后照常置 ISSUED。
        #   无 ready context（崩在推演/抽取期间，LLM 产出本就没持久化）→ 落到下方正常流程
        #     重跑推演（pre_settle 被 settling 守门跳过=前半段不二跑，simulator/extractor 重跑，
        #     = ADR「重跑是唯一选择」，即验收③）。
        # 恢复 fallthrough 用：仅当来自非 ready SETTLING ctx 时被赋真源（#146 cmr r2）；
        # 正常颁诏路保持 None → 下方 resolve_directives 走默认 player_decree。
        recovered_source = None
        if self.state.turn_phase == TurnPhase.SETTLING.value:
            ctx = self.db.get_resolve_context(self.state.turn)
            if (
                ctx is not None
                and ctx.get("extracted") is not None
                and int(ctx.get("resolve_contract_version") or 0) == 0
            ):
                clear_for_resimulation(self.db, self.state.turn)
                ctx = self.db.get_resolve_context(self.state.turn)
            if ctx is not None and ctx.get("extracted") is not None:
                # 与正常路同守门：恢复期大臣新拟的 pending 旨未核定不得推进——
                # 重放跳过守门会把它孤儿在旧回合（cmr S7 r8）。
                # 重试新传的 decree/cheat 在重放叉被忽略（重放使用崩溃前真源），留痕（cmr S7 r4）。
                if (decree or "").strip() or (cheat_directive or "").strip():
                    from ming_sim.token_stats import tlog
                    tlog("[恢复重放] 本次传入的 decree/cheat_directive 被忽略（重放使用崩溃前真源）。")
                # 跨进程恢复时内存 last_decree 已被 begin_turn 清空——web 成功响应读它
                # 作诏书展示，从真源恢复（cmr S7 r7）。
                self.last_decree = str(ctx.get("decree_text") or "")
                result = resolve_settling_recovery(
                    self.state, self.db, self.agno_db, self.llm_config, ctx,
                    on_event=on_event, content=self.content, registry=self.registry,
                )
                self.last_report = result.report
                self.state.turn_phase = TurnPhase.ISSUED.value
                self.db.save_state(self.state)
                return result
            # 无 ready context：fallthrough 到正常流程重跑推演（前半段被守门跳过）。
            # 来源按构造保真（#146 cmr r2）：恢复 fallthrough 把存档 ctx['source'] 经
            # _provenance_from_stored 穿透传入下方 resolve_directives，provenance 不依赖
            # 「非 ready SETTLING ctx 恒 player」这一脆弱不变式（clear_for_resimulation 会把
            # ready ctx 降级为 ready=0 且保留 source、driver 也能 persist system 来源 ctx，
            # 都能留下非 ready SETTLING 占位）。system 来源重跑仍记 system、对玩家静默。
            # 占位真源补诏（ship-pre r5）：begin_turn 已清内存 last_decree，跨进程恢复
            # 用存的原诏，不让 LLM 重新生成顶替玩家手改稿。
            if ctx is not None:
                # 仅恢复态（来自非 ready SETTLING ctx）才覆盖默认 player——正常颁诏路不进此分支。
                recovered_source = _provenance_from_stored(ctx.get("source"))
                if not (self.last_decree or "").strip():
                    stored = str(ctx.get("decree_text") or "").strip()
                    if stored:
                        self.last_decree = stored
        # #498 AC8：颁诏入口顺势收夜（等在飞入档 / 超时 fail-closed），再提交候选与拟诏。
        # inflight_wait_s：web 入口已在 gate 外先等在飞落档（web_app._await_audience_inflight_clear），
        # 再持 gate 传 0.0 让此处只做即时复查——避免持 gate 轮询把回话 epilogue 挡在门外
        # （AC10 gate 自锁）。CLI/单线程调用方留默认（None→DEFAULT）自等。
        from ming_sim.audience_night import auto_close_open_night
        # #503/#542：收夜与开夜、入殿、退侍共用真实 scene LLM adapter。
        auto_close_open_night(
            self.db, self.state,
            content=getattr(self, "content", None),
            registry=getattr(self, "registry", None),
            wait_timeout_s=inflight_wait_s,
            beat_generator=self._beat_generator,
        )
        # 结束回合才执行“不回=默认同意”；旧式 turn_directives 沿用既有确认口。
        # pending_actions directive 则保持 durable pending，直到 resolve_directives 的
        # pre_settle owning transaction 与财政等副作用一起物化。
        for pending in self.db.list_directives(self.state, statuses=("pending",)):
            self.db.confirm_directive(int(pending["id"]), self.state)
        directives = list(self.db.list_directives(self.state, statuses=("draft",)))
        # DB owner supplies the canonical read-only default-approval projection.
        # Negative preview ids participate in stale-decree fingerprinting without
        # colliding with durable turn_directives ids.
        pending_directives = self.db.preview_pending_directives(
            self.state, content=getattr(self, "content", None),
        )
        directives.extend(pending_directives)
        if pending_directives and recovered_source is None and (decree or "").strip():
            # The supplied decree predates these durable candidates; regenerate from
            # the complete read-only view rather than issuing unseen directives.
            decree = ""
            self.last_decree = ""
            self._decree_draft_fingerprint = ()
        settlement_due = _requires_full_settlement(self.state, self.db)
        # The no-edict fast rail may have speculatively materialized a pending
        # non-directive action, discovered that it requires full settlement, and
        # rolled that transaction back.  The pending row is then the durable reason
        # to enter resolve_directives, whose owning transaction materializes it again.
        pending_action_due = bool(self.db.list_pending_actions(self.state.turn))
        if not directives and not settlement_due and not pending_action_due:
            # 恢复态且有存诏：免草案要求（零草案 settling=driver 档/逃生口降级后是真实态，
            # 而 add 已冻结——硬要草案=循环死路，ship-pre r5）。directives 仅作非空哨兵。
            if (self.state.turn_phase in FRONT_HALF_DONE_PHASES
                    and (self.last_decree or "").strip()):
                directives = [{"text": self.last_decree}]
            else:
                raise ValueError("网页/CLI 端不允许跳过回合：至少一条草案才能颁诏。")
        # P1-1（不变式：不许颁发早于尚未纳入草案的生成稿）：玩家拟诏后又回对话新建草案时，
        # last_decree 只覆盖旧 draft 集，会把新 draft 标记为已颁却不进诏书正文。此处比对
        # 当前 draft 集与 last_decree 覆盖的指纹——不一致则作废陈旧生成稿，强制下方重生成
        # 纳入全部 draft。recovered_source 恢复路用存档真源、不在此列（指纹空、不触发）。
        if recovered_source is None and (self.last_decree or "").strip():
            current_fingerprint = self._draft_fingerprint(directives)
            if (current_fingerprint
                    and current_fingerprint != getattr(self, "_decree_draft_fingerprint", ())):
                self.last_decree = ""
                self._decree_draft_fingerprint = ()
        # 结算前先存一份：LLM 推演有可能崩，留个回滚锚点
        self.auto_save("preresolve")
        decree_text = decree or self.last_decree
        if not decree_text and directives:
            decree_text = write_decree_with_agno(
                self.llm_config, self.agno_db, self.state, directives, db=self.db
            )
        self.last_decree = decree_text
        # 恢复 fallthrough 把存档真源穿透传入（#146 cmr r2）；正常颁诏 recovered_source is None
        # → 省略 source 参数走默认 player_decree（行为不变）。
        resolve_kwargs = {}
        if recovered_source is not None:
            resolve_kwargs["source"] = recovered_source
        result = resolve_directives(
            self.state, self.db, self.agno_db, self.llm_config,
            directives, decree_text, deaths_this_turn=self.deaths_this_turn,
            debuts_this_turn=self.debuts_this_turn,
            on_event=on_event,
            content=self.content, registry=self.registry,
            cheat_directive=cheat_directive,
            **resolve_kwargs,
        )
        if result.awaiting:
            # 决策点暂停：回合未推进，存 awaiting 态供刷新恢复；待 submit_decisions 续跑。
            self.state.turn_phase = TurnPhase.AWAITING_DECISION.value
            self.db.save_state(self.state)
            return result
        self.last_report = result.report
        # resolve_directives 已 next_period + save_state；阶段标 issued
        self.state.turn_phase = TurnPhase.ISSUED.value
        self.db.save_state(self.state)
        return result

    def pending_decisions(self) -> List[Dict[str, object]]:
        """本回合待裁/已裁决策点（awaiting_decision 态下供前端弹窗/刷新恢复）。"""
        return self.db.list_pending_decisions(self.state.turn)

    def submit_decisions(
        self, choices: List[Dict[str, object]], on_event=None, cheat_directive: str = ""
    ) -> str:
        """皇帝亲裁完决策点，续跑 phase2 结算。choices 按决策点 idx 顺序，每项
        {label, hint?, note?}；先回写到 pending_decisions.choice，再读回拼进 narrative。
        要求当前处于 awaiting_decision 态。返回完整结算报告，置 issued。"""
        if self.current_phase() != TurnPhase.AWAITING_DECISION:
            raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")
        if (
            self.db.list_directives(self.state, statuses=("pending",))
            or any(
                row.get("kind") == "directive"
                for row in self.db.list_pending_actions(self.state.turn)
            )
        ):
            raise ValueError("月末亲裁期新增拟旨须先核定，不能并入已冻结的结算")
        # 与 resolve_turn 同守门（cmr S7 r8/r9 对称面）：暂停期大臣新拟的 pending 旨
        # 未核定不得推进——phase2（重放或重抽）随 next_period 会把它孤儿在旧回合。
        # 回写选择
        stored = self.db.list_pending_decisions(self.state.turn)
        ctx_for_event_binding = self.db.get_resolve_context(self.state.turn)
        # ready context = 上次 phase2 已抽取并持久化、settle 曾中止：phase2 会直入「恢复重放」、
        # 用崩溃前真源（旧选择已拼进 ready delta），明示**忽略**本次重交的亲裁选择（decree.py
        # 恢复重放叉）。此时绝不能覆写 event_triggers.choice_json——否则事件账记成新选择 B，而
        # 重放的世界状态来自旧选择 A，durable 账实不符（cmr Gate2 r4 Finding2）。跳过整段回写，
        # 让原选择留在账上、与即将重放的 delta 一致。pending_decisions 随后 phase2 会 clear。
        ready_replay = (
            ctx_for_event_binding is not None
            and ctx_for_event_binding.get("extracted") is not None
        )
        if ctx_for_event_binding is not None:
            stored = bind_decisions_to_candidate_events(
                stored, ctx_for_event_binding.get("simulator_payload")
            )
        if not ready_replay:
            # Dossier rescript choices are capability-bearing options.  Validate the
            # complete batch before persisting any decision so malformed/cross-dossier
            # payloads leave the retry state untouched.
            for d in stored:
                if not str(d.get("event_id") or "").startswith("dossier:"):
                    continue
                idx = int(d["idx"])
                choice = choices[idx] if idx < len(choices) else None
                options = d.get("options") or []
                allowed = {
                    (option.get("dossier_id"), option.get("dossier_decision"))
                    for option in options if isinstance(option, dict)
                }
                selected = (
                    choice.get("dossier_id"), choice.get("dossier_decision")
                ) if isinstance(choice, dict) else (None, None)
                if selected not in allowed:
                    raise ValueError("批红选择必须是本案提供的强颁、收回或留中选项")
            import json as _json
            for d in stored:
                idx = int(d["idx"])
                choice = choices[idx] if idx < len(choices) else None
                if not isinstance(choice, dict):
                    choice = {}
                self.db.conn.execute(
                    "UPDATE pending_decisions SET choice_json=?, status='decided' WHERE turn=? AND idx=?",
                    (_json.dumps(choice, ensure_ascii=False), self.state.turn, idx),
                )
                event_id = str(d.get("event_id") or "").strip()
                if event_id and not event_id.startswith("dossier:"):
                    self.db.record_event_decision_choice(
                        self.state, event_id, choice, commit=False)
            self.db.conn.commit()
        if not (self.last_decree or "").strip():
            # 跨进程恢复：phase2 结算后 context 即清，趁前从真源补回诏书展示字段（cmr S7 r7）。
            ctx0 = self.db.get_resolve_context(self.state.turn)
            if ctx0 is not None:
                self.last_decree = str(ctx0.get("decree_text") or "")
        report = resolve_decisions_phase2(
            self.state, self.db, self.agno_db, self.llm_config,
            on_event=on_event, content=self.content, registry=self.registry,
            cheat_directive=cheat_directive,
        )
        self.last_report = report
        self.state.turn_phase = TurnPhase.ISSUED.value
        self.db.save_state(self.state)
        return report

    def advance_without_decree(self):
        """CLI 退朝；fast 内核以事务内 DB 真源决定是否转完整结算。"""
        if self.db.list_directives(self.state, statuses=("pending", "draft")):
            return self.resolve_turn()
        advanced = advance_without_edict(
            self.state, self.db,
            content=getattr(self, "content", None),
            registry=getattr(self, "registry", None),
        )
        if not advanced:
            return self.resolve_turn()
        self.state.turn_phase = TurnPhase.SUMMONING.value
        self.db.save_state(self.state)
        return None

    def victory(self) -> Dict[str, object]:
        return victory_status(self.db, self.state)

    def auto_save(self, tag: str) -> Optional[str]:
        """每回合 begin/end 自动热备一份。每个 campaign 保留最近 AUTO_SAVE_KEEP_TURNS 个回合，旧的删。
        文件名 auto_<campaign_id>_<year>_<period>_<turn>_<tag>.db；prune 只动同 campaign 的自动档，
        不碰用户手动存档。失败静默（自动存档不应阻断游戏）。"""
        try:
            import os as _os
            saves_dir = user_data_path("saves", "_keep")  # 确保父目录建好
            saves_dir = _os.path.dirname(saves_dir)
            campaign_id = (self.db.kv_get("campaign_id") or "").strip()
            if not campaign_id:
                campaign_id = uuid.uuid4().hex[:12]
                self.db.kv_set("campaign_id", campaign_id)
            fname = (
                f"{AUTO_SAVE_PREFIX}{campaign_id}_{self.state.year:04d}_"
                f"{self.state.period:02d}_t{self.state.turn:04d}_{tag}.db"
            )
            target = _os.path.join(saves_dir, fname)
            self.db.backup_to(target)
            prune_auto_saves(saves_dir, campaign_id)
            return target
        except Exception:
            return None

    def close(self) -> None:
        self.db.close()
