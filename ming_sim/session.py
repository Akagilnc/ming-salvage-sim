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
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from ming_sim.applier import Provenance, atomic
from ming_sim.decree import (
    ResolveResult,
    _provenance_from_stored,
    _requires_full_settlement,
    resolve_decisions_phase2,
    resolve_directives,
    resolve_settling_recovery,
    write_decree_with_agno,
)
from ming_sim.error_pack import clear_for_resimulation
from ming_sim.issues import bind_content as _bind_issues
from ming_sim.issues import sync_opening_legacies
from ming_sim.decree_vocabulary import render_referenceable_dossier_brief
from ming_sim.knowledge import render_character_knowledge
from ming_sim.mindreading import is_inner_court_attendant
from ming_sim.llm_model import create_agno_db, extract_agent_text
from ming_sim.models import Character, CourtContext, GameState, LLMConfig, is_vassal_prince, is_weishi
from ming_sim.paths import user_data_path
from ming_sim.registry import MinisterRegistry, bind_content as _bind_registry
from ming_sim.settlement_payload import (
    bind_decisions_to_candidate_events,
    decision_has_rescript_capability,
    parse_rescript_capability_pair,
)
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


class AudienceAdmission(str, Enum):
    """召对入口唯一的地点分流结果（#670 / ADR 0096）。"""

    IN_CAPITAL = "IN_CAPITAL"
    SUMMON_FRESH = "SUMMON_FRESH"
    SUMMON_IN_TRANSIT = "SUMMON_IN_TRANSIT"


@dataclass(frozen=True)
class AudienceAdmissionDecision:
    result: Optional[AudienceAdmission]
    reason: str = ""
    location: str = ""
    transit_to: str = ""
    allowed: bool = False


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


def _is_ming_court_minister_character(
    character: Any,
    *,
    power_id: Optional[str] = None,
    resolve_power_id: Optional[Callable[[Any], str]] = None,
) -> bool:
    """在册身份归一（ming-guard / 别名 canonical）：非后宫 ∧ 非 candidate ∧ power=ming。

    #1317 r2：与「在朝可召资格」拆成两条单真源——身份解析必须认识所有在册者
    （含宗藩/未仕），否则史宪之/福王别名 _find_existing_minister→None→建重档/绕宗藩闸。
    可召面请用 _is_summonable_court_minister（= 本谓词 ∧ 非宗藩 ∧ 非未仕）。

    power_id 传入则用之（DB resolve 权威，#125）；否则若给 resolve_power_id 则惰性解析
    （仅过 office/status 闸后才调用，避 N+1 / 禁第二份类型短路表）；再否则读 content
    静态 character.power_id（与 seed 一致；招抚 live 翻转属既有 #125 口径，无 db 调用方不扩）。
    """
    if character is None:
        return False
    if getattr(character, "office_type", None) == "后宫":
        return False
    if getattr(character, "status", None) == "candidate":
        return False
    if power_id is None and resolve_power_id is not None:
        power_id = resolve_power_id(character)
    pid = power_id if power_id is not None else getattr(character, "power_id", None)
    return str(pid or "") == "ming"


def _is_summonable_court_minister(
    character: Any,
    *,
    power_id: Optional[str] = None,
    resolve_power_id: Optional[Callable[[Any], str]] = None,
) -> bool:
    """在朝可召资格 = 在册身份归一 ∧ 非宗藩 ∧ 非未仕（#1317 r2 单真源）。

    受守面清单见 models.is_weishi / is_vassal_prince；list_ministers / can_summon（朝臣支）/
    visible_in_court / CLI choose_minister / 拟诏事实块共吃本谓词。禁另造过滤表。
    resolve 成本规避走 resolve_power_id 惰性入参——类型短路不得与本谓词条件并存。
    """
    if character is None or is_vassal_prince(character) or is_weishi(character):
        return False
    return _is_ming_court_minister_character(
        character, power_id=power_id, resolve_power_id=resolve_power_id,
    )


def _find_existing_minister(content: GameContent, name: str, db: "GameDB") -> Optional[str]:
    """铨选查重 / 别名身份归一：拟任者是否已在册（非 candidate）。精确名 → aliases 命中。
    不做子串互含——'李标' vs '标' 那种巧合会误拒同义改写。
    后宫人物不在此查（走 _find_candidate_by_name）。返回在册原始 key，无则 None。

    吃「在册身份归一」(_is_ming_court_minister_character)，**含宗藩/未仕**——五处解析
    （本函数 / db._commit_office_action / create_secret_order / apply_office_appointment 别名归一 /
    _apply_unlisted_person_registration）共吃，禁与可召谓词混用（#1317 r2）。
    power_id 用 db.resolve_power_id 惰性入参（DB 权威，#125）：招抚归明者可召即可罢/可任；
    外藩(皇太极) resolve≠ming 仍不接。"""
    resolve = db.resolve_power_id
    if name in content.characters:
        c = content.characters[name]
        if _is_ming_court_minister_character(c, resolve_power_id=resolve):
            return name
    for key, c in content.characters.items():
        # 别名命中后才进谓词；谓词内后宫/candidate 先闸再惰性 resolve——禁第二份类型表。
        if name not in (c.aliases or []):
            continue
        if _is_ming_court_minister_character(c, resolve_power_id=resolve):
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
                  AND t.status NOT IN ('failed', 'undone', 'consumed')
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


def canonical_new_appointment_person_fields(
    content: GameContent,
    faction: object,
    *,
    is_consort: bool = False,
) -> Dict[str, object]:
    """Return the single canonical identity defaults for a newly appointed person."""
    normalized_faction = "后宫" if is_consort else str(faction or "中立").strip()
    if not is_consort and normalized_faction not in content.factions:
        normalized_faction = "中立"
    return {
        "faction": normalized_faction,
        "loyalty": 60,
        "ability": 55,
        "integrity": 60,
        "courage": 50,
        "style": "新入宫闱" if is_consort else "新任未详",
    }


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
    # 身份归一认识未仕/宗藩——在册者（含史可法诸生）由此拒新建，走 apply_office_appointment。
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
                content=content,
                commit=commit,
            )
            displaced = replaces

    person_fields = canonical_new_appointment_person_fields(
        content, data.get("faction"), is_consort=is_consort,
    )
    character = Character(
        name=name,
        office=office,
        office_type=office_type,
        aliases=[],
        personal_skills=[],
        power_id="ming",
        status="active",
        **person_fields,
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


def coalesce_pending_action_id(prior: int, staged: int) -> int:
    """Same-turn tool aggregation: non-zero staged wins; zero must not erase prior success."""
    staged_id = int(staged or 0)
    if staged_id > 0:
        return staged_id
    return int(prior or 0)


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
        dat = str(payload.get("dossier_action_type") or "").strip()
        if dat == "assignment":
            title = str(
                payload.get("title") or payload.get("target_id") or ""
            ).strip()
            if title:
                return f"交办「{title[:30]}」"
        text = str(payload.get("text") or "")
        return f"草拟圣旨：{text[:30]}"
    # secret_order：带 title/content 线索，供 confirmation 列表区分多候选（#1509）
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    cue = title or content[:30]
    return f"{action}密令" + (f"：{cue}" if cue else "")


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


_AMEND_PREFIXES = ("修改：", "修改:", "改：", "改:")
_AMEND_ORDINAL_PREFIX_RE = re.compile(
    r"^(?:修改|改)\s*第[一二三四五六七八九十百零0-9]+(?:道|条|件|个)?\s*[：:]\s*"
)
_CONFIRM_ENUM = frozenset({"应允", "拒绝", "留中", "修改", "无"})


def _strip_secret_amendment_prefix(message: str) -> str:
    """Strip 修改：/改：/修改第N道： so amendment text does not re-enter content."""
    text = (message or "").strip()
    for prefix in _AMEND_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    m = _AMEND_ORDINAL_PREFIX_RE.match(text)
    if m:
        return text[m.end():].strip()
    return text


def _coerce_confirmation_result(raw: Any) -> Tuple[str, List[int]]:
    """Normalize extract_confirmation_intent / stub → (确认枚举, 合法目标 id 列表)。

    生产契约返回 dict；既有测试 stub 可仍返回纯字符串（目标 id 视为空）。
    """
    if isinstance(raw, str):
        v = raw.strip()
        return (v if v in _CONFIRM_ENUM else "无"), []
    if isinstance(raw, dict):
        v = str(raw.get("confirmation") or raw.get("确认") or "无").strip()
        if v not in _CONFIRM_ENUM:
            v = "无"
        tids: List[int] = []
        for key in ("target_ids", "目标编号"):
            blob = raw.get(key)
            if blob is None:
                continue
            seq = blob if isinstance(blob, list) else [blob]
            for t in seq:
                try:
                    i = int(t)
                except (TypeError, ValueError):
                    digits = "".join(ch for ch in str(t) if ch.isdigit())
                    if not digits:
                        continue
                    i = int(digits)
                if i > 0 and i not in tids:
                    tids.append(i)
            break
        return v, tids
    return "无", []


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
               portrait_id, power_id, location, transit_to,
               transit_distance_remaining, transit_speed_factor, transit_start_turn, summary
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
            transit_distance_remaining=row["transit_distance_remaining"],
            transit_speed_factor=row["transit_speed_factor"],
            transit_start_turn=int(row["transit_start_turn"] or 0),
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
        start_ym: str = "",
    ) -> None:
        self.content = content if content is not None else GameContent.load()
        _bind_all_content(self.content)
        self.llm_config = llm_config
        from ming_sim.beat_orchestration import ChatTurnSceneRegistry, create_llm_beat_generator
        self._beat_generator = create_llm_beat_generator(llm_config)
        # Scene lifecycle lives in beat_orchestration; session only holds the registry handle.
        # No dedicated scene executor (C6 rejected); open/enter share the action-intent pool.
        self._scene_registry = ChatTurnSceneRegistry(_CLI_ACTION_INTENT_EXECUTOR)
        self.db = GameDB(db_path, content=self.content, llm_config=llm_config)
        # #638 S7：新开档判据必须在 load_state 建 game_state 行之前取（行在＝旧档，
        # 关系 seed 导入一律不触；验收条「只对新开档生效，旧档不受影响」的机械口径）。
        fresh_save = not self.db.has_state()
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
        # 新档的 game_state 与关系 seed 必须同成同败：load_state 内部虽有多个
        # commit，atomic 会统一推迟到 seed 校验及落库全部成功之后。旧档仍只载入。
        with atomic(self.db):
            self.state = self.db.load_state(start_ym)
            # #638 S7：新开档导入关系 seed（ADR 0086 机械面）：奠基边事件（开局前时间戳）
            # ＋可选初始摘要。边走 record_relation_edge_event 唯一写口、摘要只落奠基段
            # 且水位留 0（seed 边照常进日后首次月末酿制输入）；重复导入幂等不双写。
            seed_report = None
            if fresh_save:
                from ming_sim.relation_seed import import_bundled_relationship_seed
                seed_report = import_bundled_relationship_seed(
                    self.db,
                    opening_year=int(self.state.year),
                    opening_period=int(self.state.period),
                )
        _t, _e = time.monotonic(), time.monotonic() - _t
        tlog(f"[载入] 3/4 状态载入 {_e:.1f}s")
        if seed_report:
            tlog(
                "[载入] 关系 seed 导入："
                f"{seed_report['events_imported']}/{seed_report['events_total']} 笔奠基边事件，"
                f"{seed_report['summaries_written']} 份初始摘要"
            )
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
        # #1353：per-session 单写者票据队列（CLI/Web 共用）；write_gate 并入队列。
        from ming_sim.session_write_queue import SessionWriteQueue
        self._write_queue = SessionWriteQueue()
        self._write_gate = self._write_queue.write_gate

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
        # 可召资格单真源 _is_summonable_court_minister（#1317 r2：身份归一∧非宗藩∧非未仕；
        # 与 can_summon/visible_in_court/CLI/事实块同口径。resolve 惰性入参，禁第二份类型表）。
        views: List[MinisterView] = []
        resolve = self.db.resolve_power_id
        for c in self.content.characters.values():
            if not _is_summonable_court_minister(c, resolve_power_id=resolve):
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
        # #670 / ADR 0038：临时内存人物不得自动获朝臣资格；须先持久入册再过本闸与 admission。
        if character.name in self.temporary_characters:
            return (False, f"{character.name}未入本局人物档，须先补档后方可召见。")
        # 宗藩（就藩宗室）非朝堂命官，不可召见——与 web _require_active_minister / 各 roster 同口径
        # （PR#121 隐藏宗藩）。can_summon 是 summon_minister 工具链（session + web 流式两路）的共用闸，
        # 集中守此一处即覆盖两路，否则裁判可绕列表按名召宗藩（cmr R4 cross-section）。
        if is_vassal_prince(character):
            return (False, f"{character.name}为就藩宗室，非朝廷命官，无法召见。")
        # 非大明势力（后金/蒙古/朝鲜/流寇）非朝廷命官，即便 active 也不可召见——皇帝召的是
        # 大明朝廷之臣，不召敌酋（皇太极等）。按 DB 权威 power_id 判：招抚归明者 DB 已翻 ming
        # 但内存仍旧势力，认 DB 才不会误拒归明者（#125；与 web_app 朝堂可见性同口径）。
        power_id = self.db.resolve_power_id(character)
        if power_id != "ming":
            return (False, f"{character.name}不属大明朝廷，无法召见。")
        status, reason = self.db.get_character_status(character.name)
        if status != "active":
            label = {
                "offstage": "尚未登场",
                "dismissed": "已罢黜",
                "imprisoned": "下狱",
                "exiled": "流放",
                "retired": "致仕",
                "dead": "已故",
            }.get(status, status)
            return (False, f"{character.name}{label}，无法召见。" + (reason or ""))
        # 后宫 active+ming 可召（既有契约：嫔妃 chat 复用本闸，不经朝臣可召谓词；cmr 后宫反向锁）。
        if getattr(character, "office_type", None) == "后宫":
            return (True, "")
        # 朝臣可召：与 list_ministers / visible_in_court / CLI / 事实块同吃 _is_summonable_court_minister
        # （#1317 r2：未仕诸生等身名分在册不得以在朝命官入可召；power 已解析，直传）。
        if not _is_summonable_court_minister(character, power_id=power_id):
            return (False, f"{character.name}尚未入仕，非朝廷命官，无法召见。")
        return (True, "")

    def admit_audience(self, character: Character) -> AudienceAdmissionDecision:
        """先复用人物资格，再从 DB 权威行止投影作召对地点分流。"""
        from ming_sim.matching import canonicalize_location_region_id

        eligible, reason = self.can_summon(character)
        if not eligible:
            return AudienceAdmissionDecision(None, reason=reason)
        row = self.db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?",
            (character.name,),
        ).fetchone()
        # #670：无 DB 行不得 blank fail-open 入殿；在册空 location 仍 fail-open 在京。
        if row is None:
            return AudienceAdmissionDecision(
                None,
                reason=f"{character.name}未入本局人物档，须先补档后方可召见。",
            )
        raw_location = str(row["location"] or "")
        location = canonicalize_location_region_id(raw_location)
        transit_to = str(row["transit_to"] or "")
        if transit_to:
            result = AudienceAdmission.SUMMON_IN_TRANSIT
        elif not location or location == "beizhili":
            result = AudienceAdmission.IN_CAPITAL
        else:
            result = AudienceAdmission.SUMMON_FRESH
        # 成功记召不写固定承旨句；玩家经故事账 tags / 月度机器事实与 LLM 自由生成得知。
        # 资格失败仍走 can_summon 的非空 reason。
        return AudienceAdmissionDecision(
            result, reason="", location=location, transit_to=transit_to,
            allowed=result is AudienceAdmission.IN_CAPITAL,
        )

    def consume_audience_admission(
        self,
        character: Character,
        *,
        origin_id: str,
        state: Optional[GameState] = None,
        origin_chat_turn_id: int = 0,
    ) -> AudienceAdmissionDecision:
        """Consume the shared audience gate before any turn/entrance/reply is created.

        Offsite people get a durable story-ledger summons instead of entering the
        audience.  Ledger failures propagate, so callers cannot accidentally proceed.
        在京放行时结清该人未结传召（候见→宣入）。开夜与传召账同事务全成全败。
        """
        from ming_sim.applier import atomic
        from ming_sim.audience_night import (
            get_open_night, open_night, record_summon_fresh,
            record_summon_in_transit, settle_unsettled_summons_for_person,
        )

        decision = self.admit_audience(character)
        if decision.result is AudienceAdmission.IN_CAPITAL:
            with atomic(self.db):
                settle_unsettled_summons_for_person(self.db, character.name)
            return decision
        if decision.result not in {
            AudienceAdmission.SUMMON_FRESH,
            AudienceAdmission.SUMMON_IN_TRANSIT,
        }:
            return decision
        if not str(origin_id or "").strip():
            raise ValueError("传召 origin_id 不能为空。")
        active_state = state or getattr(self, "state", None)
        if active_state is None:
            raise ValueError("传召须有当前局面。")
        recorder = (
            record_summon_fresh
            if decision.result is AudienceAdmission.SUMMON_FRESH
            else record_summon_in_transit
        )
        with atomic(self.db):
            night = get_open_night(self.db) or open_night(self.db, active_state)
            recorder(
                self.db, int(night["id"]), character.name,
                origin_id=str(origin_id).strip(),
                origin_chat_turn_id=int(origin_chat_turn_id or 0),
            )
        return decision

    def _start_cli_action_intent(self, character: Character, message: str) -> Optional[Future]:
        """召对动作判断只读皇帝消息，可与大臣回话并发。

        #1502：API 与 CLI 非前缀自然语言均并行提交既有 classifier；
        显式前缀仍跳过（#344）。无可用通道时不启动。
        """
        from ming_sim.cli_backend import (
            _DRAFT_PREFIXES, _SECRET_PREFIXES, classify_cli_action_intent,
            cli_backend_from_env,
        )
        channel = (getattr(getattr(self, "llm_config", None), "channel", "") or "").strip().lower()
        # API/CLI 可跑预分类；其它通道仍需 CLI backend 在场
        if channel not in {"cli", "api"} and cli_backend_from_env() is None:
            return None
        # CLI 动作分类器与大臣回话一律并发；不按 runner 退串行。
        text = (message or "").strip()
        if text.startswith(_DRAFT_PREFIXES) or text.startswith(_SECRET_PREFIXES):
            return None
        minister_name = character.name
        pend_for_minister = self.db.list_pending_actions(self.state.turn, minister_name=minister_name)
        confirm_targets = _confirmation_targets_for_message(pend_for_minister, text)
        if GameSession._proposal_blocked(self.state) and not confirm_targets:
            return None
        # 本夜已暂存（含 id）供跨轮指代/改草填 target_candidate；确认优先仍由 prompt 规则约束。
        summaries = [
            f"#{int(p['id'])} {_pending_action_brief(p)}"
            for p in pend_for_minister
        ]
        is_consort = getattr(character, "office_type", "") == "后宫"
        active_orders = [] if GameSession._proposal_blocked(self.state) else self.db.get_active_secret_orders_for_minister(minister_name)
        has_pending_draft = any(p["kind"] == "directive" for p in pend_for_minister)
        recent_context = _recent_audience_context_for_secret_order(
            self.db, minister_name, int(self.state.turn), text,
        )
        return _CLI_ACTION_INTENT_EXECUTOR.submit(
            classify_cli_action_intent,
            text,
            active_orders,
            is_consort,
            has_pending_draft,
            summaries,
            getattr(self, "llm_config", None),
            recent_context,
            int(self.state.turn),
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

    def _recognize_audience_command_verdict(self, message: str) -> str:
        """#526：同步识别收夜/留侍/含糊口令。纯封闭集匹配，无 Future/宽降级。"""
        from ming_sim.audience_night import (
            normalize_audience_command_verdict,
            recognize_audience_command,
        )

        return normalize_audience_command_verdict(recognize_audience_command(message))

    def _apply_audience_command_verdict(
        self,
        result: "ChatTurnResult",
        character: Character,
        message: str,
        *,
        verdict: str,
        chat_turn_id: int = 0,
    ) -> None:
        """#526：按结构化判词落收夜/留侍/含糊确认。引擎不重解析 message 散文。"""
        from ming_sim.audience_night import (
            CMD_AMBIGUOUS_CLOSE,
            CMD_CLOSE_NIGHT,
            CMD_STAY_ATTEND,
            close_night,
            stay_attend_in_audience,
        )

        if verdict == CMD_STAY_ATTEND:
            stay_attend_in_audience(
                self.db, character.name,
                origin_chat_turn_id=int(chat_turn_id or 0),
            )
            result.court_action = "stay_attend"
            return
        if verdict == CMD_AMBIGUOUS_CLOSE:
            result.answer = GameSession._ensure_close_night_confirm_cue(result.answer or "")
            return
        if verdict != CMD_CLOSE_NIGHT:
            return
        # 本轮仍 generating 时由调用方（Web epilogue）在回话落库后收夜，避免自锁 in-flight。
        # chat_turn_id==0（无生命周期/单测）路径当场收夜=封窗=提交；失败响亮上抛，不假成功。
        if int(chat_turn_id or 0) != 0:
            result.court_action = "court_break"
            return
        close_night(
            self.db, self.state,
            content=getattr(self, "content", None),
            registry=getattr(self, "registry", None),
            wait_timeout_s=0.0,
            llm_config=getattr(self, "llm_config", None),
            write_gate=getattr(self, "_write_gate", None),
            scene_registry=getattr(self, "_scene_registry", None),
        )
        result.court_action = "court_break"

    @staticmethod
    def _ensure_close_night_confirm_cue(answer: str) -> str:
        """含糊收夜：大臣戏内确认（不出戏），不直接收夜。"""
        text = (answer or "").strip()
        ask = "陛下是要退朝么？"
        if ask in text:
            return text or ask
        if not text:
            return ask
        return text + "\n" + ask

    def _write_gate_if_free(self) -> Any:
        """#1353 fold-in r8：resolve_turn 收夜用——仅当既有唯一 write_gate 空闲时传入。

        Web 入口在 write_cm 内调 resolve_turn 时外层已持同一把非重入锁；若仍传入，
        close_night 短写 `with gate` 会自锁。探测：非阻塞 acquire 成功=空闲（立刻
        release，close 自己短持）；失败=外层持锁中，回落 None（夜应已在闸外收完）。
        CLI 单写者不持外层锁 → 恒传入真锁，欠账 drain 同流。禁第二锁。
        """
        gate = getattr(self, "_write_gate", None)
        if gate is None:
            return None
        try:
            acquired = bool(gate.acquire(blocking=False))
        except Exception:
            return None
        if not acquired:
            return None
        try:
            gate.release()
        except Exception:
            pass
        return gate

    def close_night_after_chat_if_needed(
        self,
        court_action: str,
        *,
        write_gate: Any = None,
    ) -> None:
        """#526：回话落库后由 Web/CLI epilogue 触发高置信收夜（收夜=封窗=提交）。

        失败按 ADR 0005 响亮上抛——不得静默当成已退朝；夜保持可恢复。
        write_gate：既有 runtime 写锁（Web `_runtime_write_gate` / CLI `_cli_write_gate`）；
        未显式传入时回落 session._write_gate。禁第二锁；缺锁由 close_night 卫兵响亮。

        #1353：经 session 队列屏障入队——须等已领尾随票清零后再 close（调用方不得
        在仍持本线程票据时调用，否则自等待死锁）。
        """
        if str(court_action or "") != "court_break":
            return
        from ming_sim.audience_night import close_night, get_open_night
        from ming_sim.session_write_queue import get_session_write_queue

        gate = write_gate if write_gate is not None else getattr(self, "_write_gate", None)
        # #1353 r7：入口探测开夜短持 gate（共享 conn 读；无 gate 时 CLI 单写者）。
        if gate is not None:
            with gate:
                open_n = get_open_night(self.db)
        else:
            open_n = get_open_night(self.db)
        if open_n is None:
            return

        def _do_close() -> None:
            close_night(
                self.db, self.state,
                content=getattr(self, "content", None),
                registry=getattr(self, "registry", None),
                wait_timeout_s=0.0,
                llm_config=getattr(self, "llm_config", None),
                write_gate=gate,
                scene_registry=getattr(self, "_scene_registry", None),
            )

        # 屏障只等前序票工人终态/空放行（K10a：无 elapsed 熔断）。
        get_session_write_queue(self).barrier(_do_close)

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
        summaries = [
            f"[{int(p['id'])}] {_pending_action_brief(p)}" for p in confirm_targets
        ]
        confirm, named = _coerce_confirmation_result(
            extract_confirmation_intent(
                player_message, reply, summaries,
                llm_config=getattr(self, "llm_config", None),
            )
        )
        # #1376：修改同属确认族（原地改候选，屏蔽同轮新建推断）
        # #1509 r3：同次 confirmation 的目标编号必须随 candidate 过缝，
        # 不得在此丢弃——下游 apply 在 intent 非 None 时不再二调 extractor。
        if confirm in ("应允", "拒绝", "留中", "修改"):
            payload: Dict[str, Any] = {
                "kind": "confirmation", "confirmation": confirm,
            }
            if named:
                payload["target_ids"] = list(named)
            # target_ids 仅经 payload→normalize_one_candidate 单一路径保留（#1509）
            cand = normalize_one_candidate(payload, soft=False)
            return [cand]
        return candidates

    def start_chat_turn_scene(self, minister_name: str, chat_turn_id: int) -> None:
        """委托编排层启动本轮 open/enter scene（与回话并行，join 后原子落账）。"""
        self._scene_registry.start_open_enter(
            self.db, self.state,
            minister_name=minister_name,
            chat_turn_id=int(chat_turn_id or 0),
            beat_generator=self._beat_generator,
        )

    def start_chat_turn_exit_scene(
        self, person_name: str, chat_turn_id: int, entry_id: int, *,
        night_id: int = 0,
    ) -> None:
        """令退垫位账已落后，登记 exit 生成进本轮同一 scene registry。"""
        if not night_id and chat_turn_id:
            row = self.db.conn.execute(
                "SELECT night_id FROM chat_turns WHERE id = ?", (int(chat_turn_id),),
            ).fetchone()
            night_id = int(row["night_id"] or 0) if row is not None else 0
        self._scene_registry.start_exit(
            self.db, self.state,
            person_name=person_name,
            chat_turn_id=int(chat_turn_id or 0),
            entry_id=int(entry_id or 0),
            night_id=int(night_id or 0),
            beat_generator=self._beat_generator,
        )

    def start_exit_scene_from_dismiss_tools(
        self,
        person_name: str,
        chat_turn_id: int,
        tools: Any,
    ) -> bool:
        """tools 契约已含 dismiss 时立刻落垫位；有 chat_turn_id 则登记本轮 exit（#542）。

        在仍可与回话流 / action_intent / open-enter 重叠的最早可知点调用。
        幂等：人已不在场时 dismiss_from_audience 返 None，不重复 start_exit。
        chat_turn_id=0 仍落告退账（#500 名单即时去人），只是不进 scene registry。
        返回是否新登记了 exit。
        """
        if not hasattr(self.db, "conn"):
            return False
        has_dismiss = False
        for tool_exec in tools or []:
            tool_name = getattr(tool_exec, "tool_name", "") or ""
            tool_result = str(getattr(tool_exec, "result", "") or "")
            if tool_name == "dismiss_minister" or tool_result == "__dismiss__":
                has_dismiss = True
                break
        if not has_dismiss:
            return False
        from ming_sim.audience_night import dismiss_from_audience
        entry_id = dismiss_from_audience(
            self.db, person_name, origin_chat_turn_id=int(chat_turn_id or 0),
            state=self.state,
        )
        if not entry_id or not chat_turn_id:
            return False
        self.start_chat_turn_exit_scene(
            person_name, int(chat_turn_id), int(entry_id),
        )
        return True

    def join_chat_turn_scene(self, chat_turn_id: int) -> list[tuple[int, str]]:
        """委托编排层等待本轮 scene；调用方在短事务内 persist。"""
        return self._scene_registry.join(int(chat_turn_id or 0))

    def join_rescript_summon_scene(self, chat_turn_id: int) -> list[tuple[int, str]]:
        """#657 summon 等待：retain claim 直至 finish durable 终态后 release。"""
        return self._scene_registry.join_retained(int(chat_turn_id or 0))

    def release_rescript_summon_scene(self, chat_turn_id: int) -> None:
        """#657 summon 终态释放 registry claim（consumed/failed 写后）。"""
        self._scene_registry.release(int(chat_turn_id or 0))

    def persist_chat_turn_scene(self, generated: list[tuple[int, str]]) -> None:
        """委托编排层短写已 join 的 scene 正文。"""
        from ming_sim.beat_orchestration import persist_chat_turn_scene as _persist
        _persist(self.db, generated)

    def abandon_chat_turn_scene(self, chat_turn_id: int) -> None:
        """委托编排层排空本轮 scene（cancel 或 join drain，不落库）。"""
        self._scene_registry.abandon(int(chat_turn_id or 0))

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
        # #526：收夜/留侍口令为确定性封闭集，同步识别（无耗时软判，不建 Future）。
        audience_command_verdict = self._recognize_audience_command_verdict(message)
        run_output = agent.run(augmented)
        _dump_llm_messages(run_output, f"大臣对话/{minister_name}")
        answer = extract_agent_text(run_output)
        result = ChatTurnResult(answer=answer)
        # #542：run_output.tools 已含 dismiss → 立刻 start_exit，与仍在飞的
        # action_intent 和/或本轮 open/enter 重叠；不得等 finish action_intent。
        self.start_exit_scene_from_dismiss_tools(
            character.name, int(chat_turn_id or 0),
            getattr(run_output, "tools", None) or [],
        )
        preexisting_pending_action_ids = {
            int(p["id"]) for p in self.db.list_pending_actions(self.state.turn, minister_name=character.name)
        }
        # #526：先落口令机械面（收夜/留侍/含糊确认），再 finish 动作分类。
        self._apply_audience_command_verdict(
            result, character, message,
            verdict=audience_command_verdict,
            chat_turn_id=int(chat_turn_id or 0),
        )
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
                # AC1（#500）：令退单缝；垫位+exit 已在 tools 可知时启动（上），
                # 此处再调 start_exit_scene_from_dismiss_tools 幂等（人已退 → no-op）。
                self.start_exit_scene_from_dismiss_tools(
                    character.name, int(chat_turn_id or 0), [tool_exec],
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
                        decision = self.consume_audience_admission(
                            target,
                            origin_id=f"session:tool:{int(chat_turn_id or 0)}:{target.name}",
                            origin_chat_turn_id=int(chat_turn_id or 0),
                        )
                        if decision.allowed:
                            result.court_action = "summon"
                            result.next_minister = target.name
                        # #670 P6'/P7：拒入殿只不设 court_action/next_minister；闸文不进 LLM answer。
            elif tool_name == "propose_directive" or tool_result.startswith("__pending_directive__"):
                if confirmation_turn or explicit_secret_prefix:
                    continue
                args = getattr(tool_exec, "arguments", {}) or getattr(tool_exec, "tool_args", {}) or {}
                if not isinstance(args, dict):
                    args = {}
                draft_text = tool_result.removeprefix("__pending_directive__").strip()
                if not draft_text:
                    draft_text = (args.get("decree_text") or "").strip()
                if draft_text and self._proposal_blocked(self.state):
                    draft_text = ""  # 恢复窗婉拒：不入档（见 _proposal_blocked）
                if draft_text:
                    # #502 L2 / #522 / #517：tool 拟旨与 CLI 共用候选 seam；
                    # 惩处结构化字段只从 tool arguments 交付，不扫散文。
                    stage_failures: List[Dict[str, Any]] = []
                    result.pending_action_id = coalesce_pending_action_id(
                        result.pending_action_id,
                        self._stage_directive_tool_candidate(
                            draft_text, character.name, message_text,
                            failures_out=stage_failures,
                            punish_action=args.get("punish_action"),
                            target_id=args.get("target_id"),
                            name=args.get("name"),
                            amount=args.get("amount"),
                            transaction_category=args.get("transaction_category"),
                        ),
                    )
                    if stage_failures:
                        result.pending_action_failures = list(
                            result.pending_action_failures or []
                        ) + stage_failures
            elif (tool_name == "propose_appointment"
                  or tool_result.startswith("__pending_appointment__")
                  or tool_result.startswith("__pending_recommendation__")):
                if confirmation_turn or explicit_draft_prefix or explicit_secret_prefix:
                    continue
                payload = tool_result.removeprefix("__pending_recommendation__")
                payload = payload.removeprefix("__pending_appointment__").strip()
                result.pending_action_id = coalesce_pending_action_id(
                    result.pending_action_id,
                    self._stage_appointment_candidate(
                        payload, character, message_text,
                    ),
                )
            elif tool_name == "register_unlisted_person" or tool_result.startswith("__pending_unlisted_person__"):
                if confirmation_turn or explicit_draft_prefix or explicit_secret_prefix:
                    continue
                payload = tool_result.removeprefix("__pending_unlisted_person__").strip()
                registered, summon_after = self._apply_unlisted_person_registration(payload)
                if registered:
                    result.registered_minister = registered
                    result.refresh_ministers.append(registered)
                    # #670 / ADR 0038+0096：补档已落 DB 后须走共享 admission；仅 allowed 换人。
                    if summon_after:
                        target = self.content.characters.get(registered)
                        if target is not None:
                            decision = self.consume_audience_admission(
                                target,
                                origin_id=f"session:tool:{int(chat_turn_id or 0)}:{target.name}",
                                origin_chat_turn_id=int(chat_turn_id or 0),
                            )
                            if decision.allowed:
                                result.court_action = "summon"
                                result.next_minister = target.name
            elif (
                tool_name == "rush_staged_commitment"
                or tool_result.startswith("__commitment_rush__")
            ):
                if confirmation_turn or explicit_draft_prefix:
                    continue
                if self._proposal_blocked(self.state):
                    continue
                payload_json = tool_result.removeprefix("__commitment_rush__").strip()
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except (ValueError, TypeError):
                    payload = {}
                if isinstance(payload, dict):
                    try:
                        issue_id = int(payload.get("issue_id") or 0)
                    except (TypeError, ValueError):
                        issue_id = 0
                    if issue_id > 0:
                        result.pending_action_id = coalesce_pending_action_id(
                            result.pending_action_id,
                            self.db.stage_pending_action(
                                self.state.turn,
                                kind="commitment",
                                action="催办",
                                minister_name=character.name,
                                target_id=issue_id,
                                payload={
                                    "stage_idx": int(payload.get("stage_idx") or 0),
                                    "deadline_months": payload.get("deadline_months", 1),
                                    "reason": str(payload.get("reason") or "")[:120],
                                },
                            ),
                        )
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
                            result.pending_action_id = coalesce_pending_action_id(
                                result.pending_action_id,
                                self.db.stage_pending_action(
                                    self.state.turn, kind="secret_order", action=action,
                                    minister_name=character.name, target_id=order_id,
                                    payload=payload,
                                ),
                            )
                elif tool_result.startswith("__secret_order__"):
                    payload_json = tool_result.removeprefix("__secret_order__").strip()
                    try:
                        payload = json.loads(payload_json) if payload_json else {}
                    except (ValueError, TypeError):
                        payload = {}
                    if isinstance(payload, dict):
                        result.pending_action_id = coalesce_pending_action_id(
                            result.pending_action_id,
                            self.db.stage_pending_action(
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
                            ),
                        )
                elif tool_result.startswith("__secret_order_registered__"):
                    try:
                        order_id = int(
                            tool_result.removeprefix("__secret_order_registered__").split("__", 1)[0]
                        )
                    except Exception:
                        order_id = 0
                    if order_id:
                        result.pending_action_id = coalesce_pending_action_id(
                            result.pending_action_id,
                            self._stage_legacy_registered_secret_order(
                                order_id, character.name),
                        )
        # CLI 后端（agy/codex）：玩家用拟旨/密令按钮（消息带前缀）时，把大臣这句回话原文入档。
        # #568：chat_turn_id 经 session 作用域透传至 materialize（apply 签名不动）。
        self._cli_backend_fallback_actions(
            result, character, message,
            preclassified_intent=preclassified_intent,
            confirm_target_ids=preexisting_pending_action_ids,
            chat_turn_id=int(chat_turn_id or 0),
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
            brief = render_character_knowledge(
                knowledge, character.name, db=self.db, state=self.state,
            )
        except Exception:
            return "【近臣回奏暂不可用：见闻投影失败；不得据此臆答事实。】\n\n" + message
        if brief:
            augmented = brief + "\n\n" + augmented
        candidates = self.db.list_referenceable_dossiers(character.name, self.state.turn)
        dossier_brief = render_referenceable_dossier_brief(candidates)
        if dossier_brief:
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
        None = 分类器未跑（CLI 串行回落；API 早退）；[] = 已跑无动作（零 classifier 写入）。
        #1502：API 在 classifier 已跑（含 []）时进入既有 materialize，不再无条件 passthrough。
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
        # #1502：API 仅在 classifier 未运行（preclassified is None）时 passthrough 早退；
        # 已跑（含 []）则交既有 materialize 消费 structured candidates。
        # 显式前缀仍走前缀/resolve 路（#344）。确认块在本闸之前，位置与所有权不动。
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
            summaries = [
                f"[{int(p['id'])}] {_pending_action_brief(p)}" for p in confirm_targets
            ]
            confirm_named_ids: List[int] = []
            if intent is not None:
                # #1509 r3：preclassification 已跑过同次 confirmation 抽取时，
                # 确认枚举与目标编号均取自 intent（禁二调 extractor / 禁散文机械解析）。
                if cluster_effect(intent_kind) == EFFECT_ANSWER_EXISTING:
                    confirm, confirm_named_ids = _coerce_confirmation_result(intent)
                else:
                    confirm = "无"
            else:
                confirm, confirm_named_ids = _coerce_confirmation_result(
                    extract_confirmation_intent(
                        player_message, reply, summaries, llm_config=llm_config)
                )
            # 多道并存（#502 AC4/AC5）：≥2 道 directive 候选时，口头准驳/留中须指向具体某道。
            # 点名指认 → 只作用那几道 + 清全组待澄清标（含糊 episode 了结）；否则（含糊/无/
            # 空指向）一律按含糊处置——结构化含糊态 + 追问 + 标待澄清 + **本轮不再 stage 新拟旨**，
            # 直接 return（L1：删 else free-fall，杜绝纯准驳口令误建第三道）。
            # #525：留中复用同一 target_ids/含糊规则，未点名兄弟仍走默认准。
            if confirm in ("应允", "拒绝", "留中") and len(directive_confirm_targets) >= 2:
                dir_cands = [
                    {"id": int(p["id"]), "summary": _pending_action_brief(p)}
                    for p in directive_confirm_targets
                ]
                res = extract_directive_confirmation(
                    player_message, reply, dir_cands, llm_config=llm_config)
                decision = res.get("decision")
                tids = {int(i) for i in (res.get("target_ids") or [])}
                named = decision in ("应允", "拒绝", "留中") and bool(tids)
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
                    applied: List[Dict[str, Any]] = []
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
                            applied = self.db.commit_pending_actions(
                                self.state, minister_name=minister_name,
                                action_ids=immediate_ids,
                                content=getattr(self, "content", None),
                                registry=getattr(self, "registry", None))
                    else:
                        applied = self.db.commit_pending_actions(
                            self.state, minister_name=minister_name,
                            directive_status="pending" if directive_confirm_targets else "draft",
                            action_ids=confirm_action_ids,
                            content=getattr(self, "content", None),
                            registry=getattr(self, "registry", None))
                    # #1376：应允即落地的新建密令须把真实 order id 回填确认响应
                    # （内容在 stage 时已定文，落行不经 LLM；此处只取 commit 回执）。
                    if not out.get("secret_order_id"):
                        for item in applied or []:
                            if (
                                item.get("kind") == "secret_order"
                                and str(item.get("action") or "") == "新建"
                            ):
                                oid = item.get("secret_order_id") or item.get("target_id")
                                try:
                                    oid_i = int(oid or 0)
                                except (TypeError, ValueError):
                                    oid_i = 0
                                if oid_i > 0:
                                    out["secret_order_id"] = oid_i
                                    break
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
            elif confirm == "留中":
                # #525：显式留中 → durable held_over 档，移出 pending 活跃集；
                # commit_pending_actions 只读 pending，默认提交跳过、不成案。
                self.db.hold_over_pending_actions(
                    self.state.turn, minister_name,
                    action_ids=confirm_action_ids)
            elif confirm == "修改":
                # #1376 owner：修改=更新同一 pending 密令候选内容（id 不变），不 commit、不新建。
                # 仅 secret_order/新建；非密令整改不得吞掉既有 kind 物化缝（回落 confirm=无）。
                # P5：不二次串行 _extract_secret_order——正文取去前缀御旨材料，元数据仅在
                # 修改句显式给出时覆盖（保留未提及字段）。
                # #1509：多候选目标只信同次 confirmation JSON 的合法「目标编号」，
                # 禁 regex/序数/title 机械读玩家散文；无唯一合法编号 → ambiguity。
                from ming_sim.cli_backend import (
                    _extract_imperative_assignee,
                    _secret_metadata_from_command,
                )
                secret_new = [
                    p for p in confirm_targets
                    if (
                        p.get("kind") == "secret_order"
                        and str(p.get("action") or "") == "新建"
                    )
                ]
                if not secret_new:
                    # 非密令「修改」：不提前 return，放行既有 directive/office 等补充路径。
                    confirm = "无"
                else:
                    if len(secret_new) == 1:
                        resolved = list(secret_new)
                    else:
                        allowed = {int(p["id"]) for p in secret_new}
                        named_set = {
                            i for i in confirm_named_ids if i in allowed
                        }
                        # #1509-F1：修改只更新「同一」候选；0 个或多于 1 个合法编号
                        # 一律 ambiguous，禁止整族批量覆写（复用应允/拒绝含糊缝）。
                        if len(named_set) != 1:
                            out["directive_confirmation_ambiguous"] = {
                                "candidates": [
                                    {
                                        "id": int(p["id"]),
                                        "summary": _pending_action_brief(p),
                                    }
                                    for p in secret_new
                                ],
                            }
                            return out
                        resolved = [
                            p for p in secret_new if int(p["id"]) in named_set
                        ]
                    material = _strip_secret_amendment_prefix(player_message)
                    meta_tags, meta_deadline = _secret_metadata_from_command(material)
                    named_assignee = _extract_imperative_assignee(material)
                    for pending in resolved:
                        try:
                            payload = json.loads(pending.get("payload_json") or "{}")
                        except (ValueError, TypeError):
                            payload = {}
                        if not isinstance(payload, dict):
                            payload = {}
                        # 正文：去「修改：」后的御旨材料；空材料不覆写。
                        if material:
                            payload["content"] = material
                        # 仅修改句显式给出的字段才覆盖；未提及保留原候选。
                        if named_assignee:
                            payload["assignee"] = named_assignee
                        if meta_tags:
                            payload["tags"] = meta_tags
                        if meta_deadline:
                            payload["deadline_months"] = meta_deadline
                        encoded = json.dumps(payload, ensure_ascii=False)
                        cur = self.db.conn.execute(
                            "UPDATE pending_actions SET payload_json=? "
                            "WHERE id=? AND status='pending'",
                            (encoded, int(pending["id"])),
                        )
                        if cur.rowcount != 1:
                            continue
                        pending["payload_json"] = encoded
                        out["pending_action_id"] = int(pending["id"])
                    if not bool(getattr(self.db.conn, "_commit_suspended", False)) and int(
                        getattr(self.db.conn, "_atomic_depth", 0) or 0
                    ) <= 0:
                        self.db.conn.commit()
                    # 密令修改已落地：确认族提前返回，屏蔽同轮新建 materialize。
                    return out
            if confirm in ("应允", "拒绝", "留中"):
                # 本轮是对暂存的确认：大臣回话已【复述】该动作(领命 prompt 所致),若继续走下面的
                # 抽取,会把刚 commit 的动作从复述里重抽成新暂存→颁诏二次落库,或重建刚拒的动作。
                # 故确认轮直接返回,不再抽新动作(线上 codex P2)。确认句无前缀,前缀路无损失。
                return out
        # #1502：classifier 未跑 → API 仍早退；已跑（list，含空）→ 进入 materialize
        if api_or_no_cli_passthrough and intent_candidates is None:
            return out
        if GameSession._proposal_blocked(self.state):
            # 恢复窗总闸（PR #90 R1/R2/R3 收束为单一出口）：前缀拟旨/密令与自然语言
            # 抽取的新暂存（密令动作/调教/任免）一并婉拒——窗内新写在 settle 重试事务
            # 边界外，窗内新 stage 则会被重试 settle 的 commit_pending_actions 落进
            # 「保存的 delta 推演时并不知道」的旧回合。上方对话确认块（应允延迟提交/
            # 拒绝丢弃）针对的是窗前已暂存的 pending，保持可用（ship-pre r2 设计）。
            # 抽取器（LLM 调用）一并跳过。
            return out
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
        # ADR 0028：案卷正文与分类同源，取最近相关召对上下文（复用密令喂料 helper，不平行）。
        recent_context = _recent_audience_context_for_secret_order(
            getattr(self, "db", None), minister_name, int(self.state.turn), message_text,
        )
        # #568：点策 origin 排除当前轮——chat_turn_id 由 session.chat/web/CLI 写入
        # _active_chat_turn_id 作用域，apply 签名不增参。
        try:
            active_chat_turn_id = int(getattr(self, "_active_chat_turn_id", 0) or 0)
        except (TypeError, ValueError):
            active_chat_turn_id = 0
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
            recent_context=recent_context,
            chat_turn_id=active_chat_turn_id,
        )
        run_materialize_pipeline(mat_ctx)
        return out

    @staticmethod
    def _ensure_unknown_participant_report_cue(answer: str, report: str) -> str:
        """#1274 V-1：附上 LLM 已产的查无此人回禀（报告正文本身禁在此写死台词）。"""
        text = (answer or "").strip()
        body = (report or "").strip()
        if not body:
            return text
        if body in text:
            return text
        if not text:
            return body
        return text + "\n" + body

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
        self, pending_action_id: int, minister_name: str, player_message: str,
    ) -> None:
        """Tool/API/哨兵 staged 新密令：与抽取路同一结构化 content 装配（御旨+既有 schema 内容）。

        #1274 K1 / ADR 0142：reply 永不入 content 拼装；大臣实质补充须已在 payload.content
        （extractor/tool 显式字段）。承办人只取御旨祈使 + 结构化字段（ADR 0117 不接自由文本）。
        """
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
        from ming_sim.cli_backend import (
            _choose_assignee,
            _secret_metadata_from_command,
            assemble_secret_order_content,
        )
        # 与 _extract_secret_order 同口径：content = 御旨 + 既有 schema 内容；reply 不入。
        assembled = assemble_secret_order_content(
            emperor_intent=command,
            extractor_content=content,
        )
        changed = False
        if assembled != content:
            payload["content"] = assembled
            changed = True

        # ADR 0117/0142：承办人只读结构化字段 + 御旨祈使，不接 minister_reply 散文。
        assignee = _choose_assignee(
            str(payload.get("assignee") or ""),
            command,
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
        chat_turn_id: int = 0,
    ) -> None:
        """session.chat 非流式路径：调共享会话落地，映射回 ChatTurnResult（agno 工具不触发时）。"""
        preexisting_pending_id = int(getattr(result, "pending_action_id", 0) or 0)
        # #568：当前轮 id 写入作用域供 apply→materialize 结构化排除点策轮（apply 签名不动）。
        prev_turn = getattr(self, "_active_chat_turn_id", 0)
        self._active_chat_turn_id = int(chat_turn_id or 0)
        try:
            res = self.apply_cli_conversation_actions(
                character, player_message, result.answer or "",
                has_directive=result.proposed_directive is not None or bool(result.pending_action_id),
                secret_order_id=result.secret_order_id,
                preclassified_intent=preclassified_intent,
                confirm_target_ids=confirm_target_ids,
            )
        finally:
            self._active_chat_turn_id = prev_turn
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
                )
        if res.get("pending_action_failures"):
            # Preserve tool-stage diagnostics (e.g. #522 招抚未知/歧义) then append
            # confirmation-commit failures from the shared CLI seam.
            prior = list(result.pending_action_failures or [])
            result.pending_action_failures = prior + list(res["pending_action_failures"])
        # #502 AC5：把结构化含糊态透到 ChatTurnResult，供大臣当场追问哪一道（表面契约可达）。
        if res.get("directive_confirmation_ambiguous"):
            result.directive_confirmation_ambiguous = res["directive_confirmation_ambiguous"]
            result.answer = GameSession._ensure_clarification_cue(
                result.answer or "", res["directive_confirmation_ambiguous"])
        # #1274 V-1：查无此人耗尽 → 大臣戏内回禀；草案不落、对话保留。
        esc = res.get("unknown_participant_escalate") or {}
        report = str(esc.get("report") or "").strip()
        if report:
            result.answer = GameSession._ensure_unknown_participant_report_cue(
                result.answer or "", report,
            )

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

    _PACIFICATION_TOOL_CUES = ("招抚", "招安", "受抚", "抚贼", "抚寇")

    def _mentioned_pacification_target(self, text: str) -> Optional[str]:
        """Pick the single eligible canonical mentioned for a 招抚 tool draft.

        Each name/alias hit is resolved through db._find_pacification_target;
        only qualified canonicals aggregate. Exactly one stages; zero or many
        fail loud (None). Nested aliases of one canonical collapse to one hit.
        """
        blob = str(text or "")
        if not blob or getattr(self, "content", None) is None:
            return None
        hit_canonicals: set[str] = set()
        for name, character in self.content.characters.items():
            needles = [name, *list(getattr(character, "aliases", None) or [])]
            for needle in needles:
                token = str(needle or "").strip()
                if not token or token not in blob:
                    continue
                matched = self.db._find_pacification_target(self.content, token)
                if matched:
                    hit_canonicals.add(matched)
        if len(hit_canonicals) == 1:
            return next(iter(hit_canonicals))
        # Zero qualified → unknown; multiple qualified canonicals → ambiguous.
        return None

    def _stage_directive_tool_candidate(
        self, draft_text: str, minister_name: str, message_text: str,
        *, failures_out: Optional[List[Dict[str, Any]]] = None,
        punish_action: object = None,
        target_id: object = None,
        name: object = None,
        amount: object = None,
        transaction_category: object = None,
    ) -> int:
        """API/stream/CLI tool propose_directive → structured candidate seam (#522/#517).

        Pacification cue/target still reads the tool draft. Punishment facts
        (punish_action / single target / positive fine amount) come only from
        explicit tool/action-candidate fields — never prose keyword or number
        guessing. Incomplete structured punishment fails loud and never degrades
        to special_decree; ordinary prose discussion keeps the special_decree path.
        """
        text = str(draft_text or "").strip()
        if not text:
            return 0
        # Cue + target bind only to propose_directive draft_text — never message_text.
        if any(cue in text for cue in GameSession._PACIFICATION_TOOL_CUES):
            target = self._mentioned_pacification_target(text)
            if not target:
                failure = {
                    "id": 0,
                    "kind": "directive",
                    "action": "pacification",
                    "minister_name": str(minister_name or ""),
                    "retryable": True,
                    "message": (
                        "招抚目标未知或歧义，未能拟旨入档；"
                        "请指明单一可招抚对象后再拟。"
                    ),
                }
                if failures_out is not None:
                    failures_out.append(failure)
                return 0
            from ming_sim.action_materialize import stage_pacification_candidate
            pending_id = stage_pacification_candidate(
                self.db,
                self.state.turn,
                minister_name,
                text=text,
                target_id=target,
                emperor_text=message_text,
            )
            return int(pending_id or 0)

        # #517 r3：惩处只认 ACTION_CLUSTERS 同名显式字段，不扫散文关键词/数字。
        from ming_sim.action_materialize import (
            punish_actions_effective,
            stage_punishment_candidate,
        )
        action = str(punish_action or "").strip()
        if action in punish_actions_effective():
            raw_target = str(target_id or name or "").strip()
            target = (
                _find_existing_minister(self.content, raw_target, self.db)
                if raw_target and getattr(self, "content", None) is not None
                else None
            )
            try:
                n = int(amount) if amount is not None and amount != "" else 0
            except (TypeError, ValueError):
                n = 0
            if not target or (action == "罚俸" and n <= 0):
                if not target:
                    message = (
                        "惩处目标未知或歧义，未能拟旨入档；"
                        "请指明单一在册对象后再拟。"
                    )
                else:
                    message = (
                        "罚俸缺少正数金额，未能拟旨入档；"
                        "请写明罚俸两数后再拟。"
                    )
                failure = {
                    "id": 0,
                    "kind": "directive",
                    "action": "punishment",
                    "minister_name": str(minister_name or ""),
                    "retryable": True,
                    "message": message,
                }
                if failures_out is not None:
                    failures_out.append(failure)
                return 0
            pending_id = stage_punishment_candidate(
                self.db,
                self.state.turn,
                minister_name,
                text=text,
                target_id=target,
                punish_action=action,
                emperor_text=message_text,
                amount=n if action == "罚俸" else 0,
                transaction_category=transaction_category,
            )
            if not pending_id:
                failure = {
                    "id": 0,
                    "kind": "directive",
                    "action": "punishment",
                    "minister_name": str(minister_name or ""),
                    "retryable": True,
                    "message": "惩处拟旨载荷不足，未能入档；请补全后再拟。",
                }
                if failures_out is not None:
                    failures_out.append(failure)
                return 0
            return int(pending_id)

        return self.db.stage_explicit_directive(
            self.state.turn, minister_name, text, mode=message_text,
        )

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
        # #635 r3/Y2：荐词原句逐字搬运，strip 仅作判空谓词、不成为持久化值。
        # 此处不设第二道荐词非空准入（唯一所有者在 recommend_person）；
        # 绕过/旧坏载荷由 db.py 物化期 r3 守门同事务回滚。
        raw_reason = data.get("reason") or data.get(metadata_aliases["reason"])
        if isinstance(raw_reason, str) and raw_reason.strip():
            staged_payload["reason"] = raw_reason
        for key in ("office_type", "faction", "replaces"):
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
            if self.db.get_dossier_for_directive(int(r["id"])) is None
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
        """未核定 turn_directives + staged 政务候选（#1376/#1380 投影可见性）。

        计入 pending_actions 中 directive/office/secret_order（#1380 语义洞：
        拟旨/任免 staged 时不得假 0）。确认闸门/落库时序不动。
        """
        n = self.db.count_pending_directives(self.state)
        pending_actions = self.db.list_pending_actions(self.state.turn)
        n += sum(
            1 for a in pending_actions
            if a["kind"] in {"secret_order", "directive", "office"}
        )
        return n

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
        # （resolve_turn / advance_without_decree）发生。夜内可拟多道旨并继续斟酌（#497/#502）。
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

    # #1341/#1338：set_decree 已删——裸设总诏正文绕过逐道草案结构化，违 P1；
    # Web PATCH /api/decree 同步拆除。改稿只走 add_directive / update_directive。

    def resolve_turn(self, decree: str = "", on_event=None, cheat_directive: str = "",
                     inflight_wait_s: float | None = None,
                     *, allow_empty_decree: bool = False) -> ResolveResult:
        """颁诏并推演本回合（phase1）。

        on_event(kind, data): 推演过程实时回调，透传给 resolve_directives。
        cheat_directive: 作弊控制台强制结算项，一次性透传给 resolve_directives。
        allow_empty_decree: 退朝无旨入口（#1274）置 True——directives=[] 仍走完整结算链
            （source=system_simulation）；颁诏 issue 路径保持默认 False（无草案 → 400）。

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
            # #657：返回合并 desk（急务 backlog ∪ 本月 decision），与 pending_decisions 同缝。
            return ResolveResult(
                awaiting=True,
                decisions=self.db.list_rescript_desk(int(self.state.turn)),
            )
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
        # #1234/#1235：点击受理即独立提交月初快照（不进 pre_settle 事务）。
        # accept_settlement_period：FRONT_HALF_DONE 跳过（恢复态已有快照/半程活值不可重写）。
        # Web 入口另在 await/close 前先 capture（点即入时序）；此处幂等兜底 CLI/直调。
        from ming_sim.audience_night import AudienceNightError, auto_close_open_night
        from ming_sim.exceptions import LLMUnavailable
        from ming_sim.month_open_snapshot import (
            accept_settlement_period,
            exit_settlement_display_on_failure,
        )
        accept_settlement_period(self.db, self.state)
        # #503/#542：收夜与开夜、入殿、退侍共用真实 scene LLM adapter。
        # Close-night owns short write sections + gate-free endorsement LLM.
        # Web 入口先在闸外 free-close（issue/stream/no-edict），再持闸跑 resolve；
        # 此处幂等兜底 CLI/直调。
        # #1353 fold-in r8：穿既有唯一 write_gate（session._write_gate）。
        # 若调用方已持同一把非重入锁（Web write_cm 内），不得再传入——否则 close
        # 短写 with gate 自锁；闸已被外层持时回落 None（夜应已在闸外收完）。
        # 闸空闲（CLI）→ 传入真锁，欠账 drain 同流；耗尽走 LLMUnavailable 失败单源。
        try:
            auto_close_open_night(
                self.db, self.state,
                content=getattr(self, "content", None),
                registry=getattr(self, "registry", None),
                wait_timeout_s=inflight_wait_s,
                beat_generator=self._beat_generator,
                llm_config=getattr(self, "llm_config", None),
                write_gate=self._write_gate_if_free(),
                scene_registry=self._scene_registry,
            )
        except (AudienceNightError, LLMUnavailable):
            # #1235 真失败另形：收夜中止后人话 + 出展示态（欠账耗尽=失败单源）。
            exit_settlement_display_on_failure(self.db, self.state)
            raise
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
        # Pending non-directive actions (secret orders etc.) enter resolve_directives
        # so pre_settle owns materialization with the rest of the settlement spine.
        pending_action_due = bool(self.db.list_pending_actions(self.state.turn))
        if not directives and not settlement_due and not pending_action_due:
            # 恢复态且有存诏：免草案要求（零草案 settling=driver 档/逃生口降级后是真实态，
            # 而 add 已冻结——硬要草案=循环死路，ship-pre r5）。directives 仅作非空哨兵。
            if (self.state.turn_phase in FRONT_HALF_DONE_PHASES
                    and (self.last_decree or "").strip()):
                directives = [{"text": self.last_decree}]
            elif allow_empty_decree or recovered_source is not None:
                # #1274：无旨月 / 结算中恢复 — decrees=[] 走完整链，不拒。
                pass
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
        # #1274 退朝无旨：allow_empty_decree + 无草案 → system_simulation（世界自演变静默）。
        resolve_kwargs = {}
        if recovered_source is not None:
            resolve_kwargs["source"] = recovered_source
        elif allow_empty_decree and not directives and not (decree_text or "").strip():
            resolve_kwargs["source"] = Provenance.system_simulation
        result = resolve_directives(
            self.state, self.db, self.agno_db, self.llm_config,
            directives, decree_text, deaths_this_turn=self.deaths_this_turn,
            debuts_this_turn=self.debuts_this_turn,
            on_event=on_event,
            content=self.content, registry=self.registry,
            cheat_directive=cheat_directive,
            scene_registry=self._scene_registry,
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
        """本回合待裁/已裁决策点（awaiting_decision 态下供前端弹窗/刷新恢复）。

        #657：批红案头合并读——急务 rescript_draft ∪ 本月 decision（list_rescript_desk）。
        """
        return self.db.list_rescript_desk(int(self.state.turn))

    def _assert_awaiting_decision_submit(self) -> None:
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

    def _normalize_rescript_request_choices(
        self,
        choices: List[Dict[str, object]],
        desk: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        """把 idx 序旧载荷或 decision_key 新载荷统一成带 decision_key 的 choice 列表。"""
        if not choices:
            return []
        if any(isinstance(c, dict) and c.get("decision_key") for c in choices):
            return [dict(c) for c in choices if isinstance(c, dict)]
        # 旧形：按 desk 中 decision 行 idx 对齐；急务缺省 hold
        by_idx = {
            int(r["idx"]): r for r in desk if str(r.get("kind")) == "decision"
        }
        out: List[Dict[str, object]] = []
        for idx, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            row = by_idx.get(idx)
            if row is None:
                continue
            item = dict(choice)
            item["decision_key"] = row["decision_key"]
            out.append(item)
        return out

    def prepare_rescript_prewrite(
        self, choices: List[Dict[str, object]],
    ) -> Dict[str, object]:
        """#657 PREWRITE（gate 外）：validate_all + run_prewrite_llms；失败零写。"""
        from ming_sim import rescript_actions as ra
        from ming_sim.agents import (
            create_rescript_deliberate_agent,
            create_rescript_revise_agent,
        )
        from ming_sim.rescript_draft import (
            _parse_rescript_json_strict,
            normalize_rescript_layer_a_option,
        )

        self._assert_awaiting_decision_submit()
        desk = list(self.db.list_rescript_desk(int(self.state.turn)))
        req = self._normalize_rescript_request_choices(choices, desk)
        # C1.1：① 已落 decided、③ phase2 未写 extracted 的崩溃重入——
        # list_rescript_desk 只 pending，须把请求键对应 decided 行并入 desk
        # 供 validate already_applied；ready_replay（extracted 非空）仍短路。
        desk_keys = {str(r.get("decision_key") or "") for r in desk}
        missing_keys = [
            str(c.get("decision_key") or "").strip()
            for c in req
            if isinstance(c, dict)
            and str(c.get("decision_key") or "").strip()
            and str(c.get("decision_key") or "").strip() not in desk_keys
        ]
        if missing_keys:
            desk.extend(self.db.get_rescript_desk_rows_by_keys(missing_keys))
        ctx = self.db.get_resolve_context(self.state.turn)
        ready_replay = ctx is not None and ctx.get("extracted") is not None
        if ready_replay:
            return {
                "ready_replay": True,
                "batch": None,
                "prewrite": None,
                "desk": desk,
                "choices": req,
            }

        def _rescript_can_summon(name: str):
            """validate_all 唯一资格出口：str→Character→can_summon；成功回 canonical。"""
            raw = str(name or "").strip()
            if not raw:
                return False, "summon_target 为空"
            canon = _find_existing_minister(self.content, raw, self.db)
            character = None
            if canon and canon in self.content.characters:
                character = self.content.characters[canon]
            elif raw in self.content.characters:
                character = self.content.characters[raw]
                canon = raw
            else:
                for key, ch in self.content.characters.items():
                    if raw in (getattr(ch, "aliases", None) or []):
                        character = ch
                        canon = key
                        break
            if character is None:
                return False, f"人物未建档，无法召见：{raw}"
            ok, reason = self.can_summon(character)
            if not ok:
                return False, reason or f"不可召见：{raw}"
            return True, str(canon or character.name)

        batch = ra.validate_all(
            desk, req, default_hold_missing=True, can_summon=_rescript_can_summon,
        )

        def _revise_runner(item: ra.ValidatedItem) -> List[Dict[str, object]]:
            # 单行改票：专用 agent + 唯一 {"options":[...]} shape；禁 monthly items[] / drafts[0]
            agent = create_rescript_revise_agent(self.llm_config, self.agno_db)
            payload = {
                "mode": "single_row_revise",
                "title": item.row.get("title"),
                "context": item.row.get("context"),
                "prior_options": item.row.get("options"),
                "note": item.choice.get("note") or "",
            }
            from ming_sim.agents import run_agent_text
            raw = run_agent_text(
                agent, json.dumps(payload, ensure_ascii=False), tag="rescript-revise",
            )
            data = _parse_rescript_json_strict(raw)
            if not isinstance(data, dict) or "items" in data:
                raise ValueError("改票 LLM 须输出 {\"options\":[...]}，禁 monthly items[]")
            options_raw = data.get("options")
            if not isinstance(options_raw, list) or not options_raw:
                raise ValueError("改票 LLM 未产出非空 options")
            return [normalize_rescript_layer_a_option(opt) for opt in options_raw]

        def _deliberate_runner(item: ra.ValidatedItem) -> Dict[str, object]:
            # 站台意愿：专用 agent + 整串严格 JSON {title,body,stance}；禁 regex 抽对象
            from ming_sim.agents import run_agent_text
            agent = create_rescript_deliberate_agent(self.llm_config, self.agno_db)
            prompt = (
                "请为以下急务拟定下部议/廷议的站台意愿（JSON："
                "{\"title\":\"...\",\"body\":\"...\",\"stance\":\"...\"}）。\n"
                f"标题：{item.row.get('title')}\n语境：{item.row.get('context')}\n"
                f"批语：{item.choice.get('note') or ''}"
            )
            raw = run_agent_text(agent, prompt, tag="rescript-deliberate")
            obj = _parse_rescript_json_strict(str(raw or ""))
            if not isinstance(obj, dict):
                raise ValueError("deliberate LLM 意愿须为 object")
            title = str(obj.get("title") or "").strip()
            body = str(obj.get("body") or "").strip()
            stance = str(obj.get("stance") or "").strip()
            if not (title and body and stance):
                raise ValueError("deliberate LLM 意愿缺 title/body/stance")
            return {"title": title, "body": body, "stance": stance}

        prewrite = ra.run_prewrite_llms(
            batch,
            revise_runner=_revise_runner if any(i.needs_revise_llm for i in batch.items) else None,
            deliberate_runner=_deliberate_runner if any(i.needs_deliberate_llm for i in batch.items) else None,
        )
        return {
            "ready_replay": False,
            "batch": batch,
            "prewrite": prewrite,
            "desk": desk,
            "choices": req,
        }

    def commit_rescript_phase1(self, prewrite_state: Dict[str, object]) -> Dict[str, object]:
        """#657 ① 短写（调用方已持 write_gate）：C1 apply + summon 垫位/CAS + 全 start。

        内部不 join。无急务 summon 时 summon 段空转。
        """
        from ming_sim import rescript_actions as ra
        from ming_sim.audience_night import (
            prepare_rescript_summon_scaffold,
            rescript_summon_origin_ref,
        )

        if prewrite_state.get("ready_replay"):
            return {
                "ready_replay": True,
                "apply": None,
                "summons": [],
                "revise_keys": [],
            }

        batch: ra.ValidatedBatch = prewrite_state["batch"]  # type: ignore[assignment]
        prewrite: ra.PrewriteResults = prewrite_state["prewrite"]  # type: ignore[assignment]
        apply = ra.apply_rescript_batch(
            self.db, self.state, batch, prewrite, content=self.content,
        )

        # 未消费 summon：垫位/CAS + discover/BeatInputs + 全部 start
        summons: List[Dict[str, object]] = []
        for key in apply.summon_keys:
            item = next((i for i in batch.items if i.decision_key == key), None)
            if item is None:
                continue
            target = str(item.choice.get("summon_target") or "").strip()
            origin = rescript_summon_origin_ref(
                item.source_turn, item.idx, int(item.row.get("revision_round") or 0),
            )
            scaffold = prepare_rescript_summon_scaffold(
                self.db, self.state,
                person_name=target,
                origin_ref=origin,
            )
            if scaffold.get("consumed"):
                summons.append({
                    "decision_key": key,
                    "origin_ref": origin,
                    "consumed": True,
                    **scaffold,
                })
                continue
            ctid = int(scaffold["chat_turn_id"])
            # discover + start（零 LLM 在 discover；LLM 在 registry Future）
            self._scene_registry.start_open_enter(
                self.db, self.state,
                minister_name=target,
                chat_turn_id=ctid,
                beat_generator=self._beat_generator,
            )
            summons.append({
                "decision_key": key,
                "origin_ref": origin,
                "consumed": False,
                "target": target,
                **scaffold,
            })
        return {
            "ready_replay": False,
            "apply": apply,
            "summons": summons,
            "revise_keys": list(apply.revise_keys),
            "batch": batch,
        }

    def join_rescript_summons(
        self, phase1_state: Dict[str, object],
    ) -> Dict[str, object]:
        """#657 ② 无锁等待：join 全部 summon target Future。不得持 write_gate。"""
        if phase1_state.get("ready_replay"):
            return {"joined": [], "ready_replay": True}
        joined: List[Dict[str, object]] = []
        for sc in phase1_state.get("summons") or []:
            if sc.get("consumed"):
                joined.append({**sc, "generated": []})
                continue
            ctid = int(sc.get("chat_turn_id") or 0)
            try:
                # retain claim across wait so concurrent same-body retry coalesces
                generated = self.join_rescript_summon_scene(ctid)
            except Exception as exc:
                # §D.1 ② 无锁等待：只汇合 Future / 记 error，**零写库**。
                # failed 持久化挪到 ③ finish（持 write_gate）——禁无锁② UPDATE+commit。
                joined.append({**sc, "generated": [], "error": str(exc)})
                continue
            joined.append({**sc, "generated": list(generated)})
        return {"joined": joined, "ready_replay": False}

    def finish_rescript_phase2(
        self,
        phase1_state: Dict[str, object],
        join_state: Dict[str, object],
        *,
        on_event=None,
        cheat_directive: str = "",
    ) -> str:
        """#657 ③ 短写（调用方已持 write_gate）：persist + 门闩 + phase2。

        return_revise 清锚在 settle_with_delta 单一终态完成（与 next_period 同 atomic）。
        """
        from ming_sim.applier import atomic

        if not phase1_state.get("ready_replay"):
            # ③ 持 write_gate：成功则 persist；失败状态统一在门闩后唯一写点落 failed。
            with atomic(self.db):
                for item in join_state.get("joined") or []:
                    if item.get("error"):
                        continue
                    generated = item.get("generated") or []
                    if generated:
                        self.persist_chat_turn_scene(list(generated))

            # D.8 门闩：未消费 summon → 响亮失败（§D.0 唯一谓词）
            # 权威=行事实：先扫本次 join，再扫 durable decided summon（共享迭代器）。
            from ming_sim.audience_night import rescript_summon_origin_consumed
            unconsumed: List[str] = []
            seen_origins: set[str] = set()
            for item in join_state.get("joined") or []:
                origin = str(item.get("origin_ref") or "")
                if origin:
                    seen_origins.add(origin)
                row = self.db.conn.execute(
                    "SELECT body, tags FROM story_ledger_entries WHERE origin_ref = ?",
                    (origin,),
                ).fetchone()
                entry = None
                if row is not None:
                    entry = {
                        "body": str(row["body"] or ""),
                        "tags": str(row["tags"] or "[]"),
                    }
                if item.get("error"):
                    ok = False
                elif item.get("consumed"):
                    # 既有消费：prepare 已判；门闩仍复核 TAG_ENTER+非空 body
                    ok = rescript_summon_origin_consumed(entry)
                else:
                    generated_bodies = [
                        str(b)
                        for _eid, b in (item.get("generated") or [])
                        if str(b).strip()
                    ]
                    ok = rescript_summon_origin_consumed(
                        entry, expected_bodies=generated_bodies,
                    )
                if not ok:
                    unconsumed.append(
                        f"{item.get('decision_key')}:{item.get('target') or ''}:{origin}"
                    )
            # join_state 空/残缺时仍以 durable 行事实挡 phase2（S5/D.8）
            for fact in self._iter_unconsumed_decided_summons():
                origin = str(fact.get("origin_ref") or "")
                if origin in seen_origins:
                    continue
                unconsumed.append(
                    f"{fact.get('decision_key')}:{fact.get('target') or ''}:{origin}"
                )
            if unconsumed:
                # 唯一失败写点：generator error 与门闩未消费同形
                # generating 空问话 → failed，供 CAS 重入（#657 Spec4 重试）。
                with atomic(self.db):
                    for item in join_state.get("joined") or []:
                        if item.get("consumed"):
                            continue
                        ctid_fail = int(item.get("chat_turn_id") or 0)
                        if ctid_fail > 0:
                            self.db.conn.execute(
                                "UPDATE chat_turns SET status='failed' "
                                "WHERE id=? AND status='generating' "
                                "AND user_message_id IS NULL",
                                (ctid_fail,),
                            )
                # durable failed 已写 → 唯一 release，允许合法重入
                for item in join_state.get("joined") or []:
                    ctid_rel = int(item.get("chat_turn_id") or 0)
                    if ctid_rel > 0:
                        self.release_rescript_summon_scene(ctid_rel)
                raise ValueError(
                    "召见尚未消费，不得推进 phase2：" + "; ".join(unconsumed)
                )
            # 消费成功 / 已消费短路：空问话 scaffold → status=consumed
            # （含 retry 时 origin 已 consumed 但 scaffold 仍 generating 的可恢复终态）
            for item in join_state.get("joined") or []:
                if item.get("error"):
                    continue
                ctid = int(item.get("chat_turn_id") or 0)
                if ctid > 0:
                    self.db.complete_rescript_summon_scaffold_turn(ctid)
                    # durable consumed 已写 → 唯一 release
                    self.release_rescript_summon_scene(ctid)

        if not (self.last_decree or "").strip():
            ctx0 = self.db.get_resolve_context(self.state.turn)
            if ctx0 is not None:
                self.last_decree = str(ctx0.get("decree_text") or "")

        report = resolve_decisions_phase2(
            self.state, self.db, self.agno_db, self.llm_config,
            on_event=on_event, content=self.content, registry=self.registry,
            cheat_directive=cheat_directive,
        )
        # return_revise 清锚已纳入 settle_with_delta 单一终态（与 next_period 同 atomic）

        self.last_report = report
        self.state.turn_phase = TurnPhase.ISSUED.value
        self.db.save_state(self.state)
        return report

    def resolve_rescript_decisions(
        self,
        choices: List[Dict[str, object]],
        *,
        write_gate: Any,
        on_event=None,
        cheat_directive: str = "",
    ) -> str:
        """#657 急务/keyed 唯一编排出口。

        PRE 锁外 → ① 持 write_gate → ② 无锁 join → ③ 再持同一 write_gate。
        调用方只注入既有 write_gate / on_event；禁平行复制本配方。
        """
        if write_gate is None:
            raise ValueError("resolve_rescript_decisions 须注入既有 write_gate")
        pre = self.prepare_rescript_prewrite(choices)
        with write_gate:
            p1 = self.commit_rescript_phase1(pre)
        joined = self.join_rescript_summons(p1)
        with write_gate:
            return self.finish_rescript_phase2(
                p1, joined, on_event=on_event, cheat_directive=cheat_directive,
            )

    def _iter_unconsumed_decided_summons(self) -> List[Dict[str, object]]:
        """#657 D.8 未消费 durable decided summon 行事实唯一权威（跨月不收窄）。

        每项：decision_key / origin_ref / target / choice（行上既有 choice + C1 key）。
        恢复批与 finish 门闩共用；不新建表/API。
        """
        from ming_sim.audience_night import (
            rescript_summon_origin_consumed,
            rescript_summon_origin_ref,
        )

        out: List[Dict[str, object]] = []
        for draft in self.db.list_rescript_drafts():
            if str(draft.get("status") or "") != "decided":
                continue
            choice = draft.get("choice")
            if not isinstance(choice, dict):
                continue
            if str(choice.get("action") or "") != "summon":
                continue
            source_turn = int(draft.get("turn") or 0)
            idx = int(draft.get("idx") or 0)
            rev = int(draft.get("revision_round") or 0)
            origin = rescript_summon_origin_ref(source_turn, idx, rev)
            row = self.db.conn.execute(
                "SELECT body, tags FROM story_ledger_entries WHERE origin_ref = ?",
                (origin,),
            ).fetchone()
            entry = None
            if row is not None:
                entry = {
                    "body": str(row["body"] or ""),
                    "tags": str(row["tags"] or "[]"),
                }
            if rescript_summon_origin_consumed(entry):
                continue
            recovered = dict(choice)
            dk = str(recovered.get("decision_key") or "").strip()
            if not dk:
                dk = f"rescript_draft:{source_turn}:{idx}"
            recovered["decision_key"] = dk
            out.append({
                "decision_key": dk,
                "origin_ref": origin,
                "target": str(recovered.get("summon_target") or "").strip(),
                "choice": recovered,
            })
        return out

    def _unconsumed_decided_summon_choices(self) -> List[Dict[str, object]]:
        """恢复批投影：权威 `_iter_unconsumed_decided_summons` → request choices。"""
        return [dict(fact["choice"]) for fact in self._iter_unconsumed_decided_summons()]

    def submit_hitl_choices(
        self,
        choices: List[Dict[str, object]],
        *,
        write_gate: Any,
        on_event=None,
        cheat_directive: str = "",
    ) -> str:
        """#657 HITL 公共入口：急务/keyed → resolve_rescript_decisions；纯 decision → gate 内 submit_decisions。

        空 choices 且 desk 无 pending 急务时：若仍有未消费 durable decided summon，
        交回同一 resolve_rescript_decisions（C1 already_applied → scaffold/registry），
        不得直 submit_decisions 越过召见。
        """
        if write_gate is None:
            raise ValueError("submit_hitl_choices 须注入既有 write_gate")
        keyed = any(
            isinstance(c, dict) and str(c.get("decision_key") or "").strip()
            for c in (choices or [])
        )
        has_urgent = False
        list_desk = getattr(getattr(self, "db", None), "list_rescript_desk", None)
        if callable(list_desk):
            desk = list_desk(int(self.state.turn))
            has_urgent = any(str(r.get("kind")) == "rescript_draft" for r in (desk or []))
        if has_urgent or keyed:
            return self.resolve_rescript_decisions(
                choices,
                write_gate=write_gate,
                on_event=on_event,
                cheat_directive=cheat_directive,
            )
        # 无 key / 无 pending 急务：未消费 durable summon 仍走同一 resolver
        if not keyed:
            recovery = self._unconsumed_decided_summon_choices()
            if recovery:
                return self.resolve_rescript_decisions(
                    recovery,
                    write_gate=write_gate,
                    on_event=on_event,
                    cheat_directive=cheat_directive,
                )
        with write_gate:
            return self.submit_decisions(
                choices, on_event=on_event, cheat_directive=cheat_directive,
            )

    def submit_decisions(
        self, choices: List[Dict[str, object]], on_event=None, cheat_directive: str = ""
    ) -> str:
        """皇帝亲裁完决策点，续跑 phase2 结算。

        #657：本方法**仅**纯 decision/#1490 路径（不内部 join LLM）。
        急务/keyed 批必须走 resolve_rescript_decisions / submit_hitl_choices
        （调用方注入既有 write_gate）。
        """
        self._assert_awaiting_decision_submit()

        # ── #1490 / 纯 decision 路径 ──────────────────────────────────
        stored = self.db.list_pending_decisions(self.state.turn)
        ctx_for_event_binding = self.db.get_resolve_context(self.state.turn)
        ready_replay = (
            ctx_for_event_binding is not None
            and ctx_for_event_binding.get("extracted") is not None
        )
        if ctx_for_event_binding is not None:
            stored = bind_decisions_to_candidate_events(
                stored, ctx_for_event_binding.get("simulator_payload")
            )
        if not ready_replay:
            import json as _json
            rebuilt_by_idx: Dict[int, Dict[str, object]] = {}
            for d in stored:
                if str(d.get("status") or "") == "decided":
                    continue
                if not str(d.get("event_id") or "").startswith("dossier:"):
                    continue
                if not decision_has_rescript_capability(d):
                    continue
                options = [
                    option for option in (d.get("options") or [])
                    if isinstance(option, dict)
                ]
                idx = int(d["idx"])
                choice = choices[idx] if idx < len(choices) else None
                option_by_pair: Dict[tuple, Dict[str, object]] = {}
                for option in options:
                    pair = parse_rescript_capability_pair(option)
                    if pair is not None:
                        option_by_pair[pair] = option
                allowed = set(option_by_pair)
                selected = (
                    parse_rescript_capability_pair(choice)
                    if isinstance(choice, dict) else None
                )
                if selected is None or selected not in allowed:
                    raise ValueError("批红选择必须是本案提供的强颁、收回或留中选项")
                matched = option_by_pair[selected]
                rebuilt: Dict[str, object] = {
                    "label": matched.get("label"),
                    "hint": matched.get("hint") or "",
                    "dossier_id": selected[0],
                    "dossier_decision": selected[1],
                }
                if isinstance(choice, dict) and choice.get("note") is not None:
                    rebuilt["note"] = choice.get("note")
                rebuilt_by_idx[idx] = rebuilt
            for d in stored:
                if str(d.get("status") or "") == "decided":
                    continue
                idx = int(d["idx"])
                if idx in rebuilt_by_idx:
                    choice = rebuilt_by_idx[idx]
                else:
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

    def advance_without_decree(self, inflight_wait_s: float | None = None):
        """CLI/web 退朝；无旨月亦走完整结算链（#1274 / owner B-2）。

        有草案/pending → 视同颁诏 resolve_turn。
        无草案 → allow_empty_decree，source=system_simulation，pre_settle+simulator+
        settle_with_delta 全链照跑（邸报/种子局势/议题惯性/结局判定）；16ms 快路已废。
        """
        if self.db.list_directives(self.state, statuses=("pending", "draft")):
            return self.resolve_turn(inflight_wait_s=inflight_wait_s)
        return self.resolve_turn(
            inflight_wait_s=inflight_wait_s, allow_empty_decree=True,
        )

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
        for chat_turn_id in self._scene_registry.active_turn_ids():
            self.abandon_chat_turn_scene(chat_turn_id)
        self.db.close()
