"""GameSession：CLI 与 Web 共用的统一回合流转层。L8。

不含 input()/print()——只持有状态、跑底层逻辑、返回 dataclass。
召见对话的 tool 截获、拟旨 draft 流转、诏书结算都收在这里，
CLI 和 Web 各自只做 I/O 包装。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from ming_sim.materials import PreparedMaterials

from ming_sim.agents import bind_content as _bind_agents
from ming_sim.agents import _dump_llm_messages
from ming_sim.constants import TURN_UNIT
from ming_sim.content import GameContent
from ming_sim.materials import prepare_scene_materials
from ming_sim.registry import create_scene_agent
from ming_sim.context import (
    bind_content as _bind_context,
    character_from_name,
    match_minister_from_text,
    victory_status,
)
from ming_sim.db import (
    GameDB,
    directive_payload_admits_structured_write,
    infer_office_type_from_office,
    normalize_office,
    resolve_office_type_preserving_title,
)
from ming_sim.applier import (
    Provenance,
    atomic,
    connection_owns_transaction,
    register_runtime_outcome_callbacks,
)
from ming_sim.decree import (
    ResolveResult,
    _provenance_from_stored,
    _requires_full_settlement,
    resolve_decisions_phase2,
    resolve_directives,
    write_decree_with_agno,
)
from ming_sim.issues import bind_content as _bind_issues
from ming_sim.issues import sync_opening_legacies
from ming_sim.audience_night import is_inner_court_attendant
from ming_sim.llm_model import create_agno_db, extract_agent_text
from ming_sim.models import Character, CourtContext, GameState, LLMConfig, is_vassal_prince, is_weishi
from ming_sim.paths import user_data_path

logger = logging.getLogger(__name__)


AUTO_SAVE_PREFIX = "auto_"
AUTO_SAVE_KEEP_TURNS = 3  # 每个 campaign 保留最近 N 个 turn 的全部自动存档（每 turn 含 begin + preresolve）
# #1769 成案补交：原抽 + LLM 重写 N 次 = 总计 N+1（owner：N=2 → 总计 3，与召对「第一次不叫重试」同形状）。
# 与 DRAFT_PARTICIPANT_HEAL_RETRIES（组合/名册内部 heal）独立；内部 heal 不冒充成案补交次数。
DRAFT_ADMISSION_RESUBMIT_REWRITES = 2


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
    # #1842：ctid>0 时 scene_chat 只暂存转译参数；回话 persist 后由
    # schedule_pending_scene_translation 启动（ADR 0155 / 0036：回话落定后起）。
    pending_audience_translation: Optional[Dict[str, Any]] = None


@dataclass
class TurnSnapshot:
    year: int
    period: int
    turn: int
    phase: str
    metrics: Dict[str, int]
    deaths_this_turn: List[Dict[str, str]] = field(default_factory=list)
    previous_summary: str = ""


def _is_ming_court_minister_character(
    character: Any,
    *,
    power_id: Optional[str] = None,
    resolve_power_id: Optional[Callable[[Any], str]] = None,
) -> bool:
    """在册身份归一（ming-guard / 别名 canonical）：非后宫 ∧ power=ming。

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
    """铨选查重 / 别名身份归一：拟任者是否已在册。精确名 → aliases 命中。
    不做子串互含——'李标' vs '标' 那种巧合会误拒同义改写。
    后宫人物不在此查。返回在册原始 key，无则 None。

    吃「在册身份归一」(_is_ming_court_minister_character)，**含宗藩/未仕**——五处解析
    （本函数 / db._commit_office_action / create_secret_order / apply_office_appointment 别名归一 /
    转译入册）共吃，禁与可召谓词混用（#1317 r2）。
    power_id 用 db.resolve_power_id 惰性入参（DB 权威，#125）：招抚归明者可召即可罢/可任；
    外藩(皇太极) resolve≠ming 仍不接。"""
    resolve = db.resolve_power_id
    if name in content.characters:
        c = content.characters[name]
        if _is_ming_court_minister_character(c, resolve_power_id=resolve):
            return name
    for key, c in content.characters.items():
        # 别名命中后才进谓词；谓词内后宫先闸再惰性 resolve——禁第二份类型表。
        if name not in (c.aliases or []):
            continue
        if _is_ming_court_minister_character(c, resolve_power_id=resolve):
            return key
    return None


def register_unlisted_person_record(
    db: "GameDB",
    state: "GameState",
    content: GameContent,
    *,
    name: str,
    office: str,
    office_type: str,
    faction: str = "",
    aliases: Sequence[str] = (),
    source_label: str = "名册外人物补档",
    style: str = "",
    loyalty: int = 55,
    summary: str = "",
    region_id: str = "",
    llm_config: Any = None,
) -> Optional[Character]:
    """登记名册外人物的唯一权威构档：查重（`_find_existing_minister`，姓名与
    别名both查）+ `db.add_character` 落库 + portrait_id 回填。

    转译声明分派复用本函数，不另维护查重规则。

    本函数不替 LLM 生成 `style`（人物材料上的可感文字，P7：玩家可感文本模板
    违宪）——`style` 原样存调用方传入的值，缺省是空字符串，不合成占位文案。
    转译声明原样透传 style，未提供则留空。

    `region_id` 是调用方显式传入的 typed 任所（声明/工具 payload 的 `region_id`/
    `任所`/`office_region`），原样写入 `Character.office_region` 供
    `db.add_character` → `_require_local_office_region` 消费。不从官名、
    location 或其它字段推断；地方/督抚/边镇缺 seat 由下游 typed
    `OfficeAppointmentRejection` 拒收。

    返回新建的 `Character`；字段缺失或已在册（含别名命中）→ ``None``。
    """
    name = str(name or "").strip()
    office = str(office or "").strip()
    office_type = str(office_type or "").strip()
    if not name or not office or not office_type:
        return None
    alias_list = [str(a).strip() for a in (aliases or ()) if str(a).strip()]
    if _find_existing_minister(content, name, db) is not None:
        return None
    for alias in alias_list:
        if _find_existing_minister(content, alias, db) is not None:
            return None
    faction_value = str(faction or "中立").strip()
    if faction_value not in content.factions:
        faction_value = "中立"
    seat = str(region_id or "").strip()
    character = Character(
        name=name,
        office=office,
        office_type=office_type,
        faction=faction_value,
        aliases=alias_list,
        personal_skills=[],
        loyalty=int(loyalty),
        ability=55,
        integrity=60,
        courage=55,
        style=str(style or ""),
        power_id="ming",
        status="active",
        summary=str(summary or ""),
        office_region=seat,
    )
    content.characters[name] = character
    added_name = name
    roster = content.characters

    def _drop_runtime_registration(
        target: str = added_name, bag: Dict[str, Character] = roster,
    ) -> None:
        bag.pop(target, None)

    register_runtime_outcome_callbacks(db, on_rollback=_drop_runtime_registration)
    # SAVEPOINT：add_character 写前已完成 seat 校验，但 characters + character_offices
    # 仍须整项原子；外层 _item_savepoint_scope / atomic 嵌套仍合法。commit 必须在
    # RELEASE 之后、且仅当本核拥有事务时发生——否则 SAVEPOINT 期内 commit 会把
    # 整个事务提前提交，随后 RELEASE 无点。
    owns_transaction = connection_owns_transaction(db.conn)
    savepoint = f"register_unlisted_{abs(id(character)) & 0xFFFFFFFF:x}"
    db.conn.execute(f"SAVEPOINT {savepoint}")
    try:
        db.add_character(
            state, character,
            source=str(source_label or "").strip(),
            llm_config=llm_config,
            commit=False,
        )
    except Exception:
        db.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        roster.pop(added_name, None)
        raise
    else:
        db.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        if owns_transaction:
            db.conn.commit()
    row = db.conn.execute(
        "SELECT portrait_id FROM characters WHERE name=?", (name,),
    ).fetchone()
    if row:
        character.portrait_id = str(row["portrait_id"])
    return character




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




def canonical_new_appointment_person_fields(
    content: GameContent,
    faction: object,
) -> Dict[str, object]:
    """Return the single canonical identity defaults for a newly appointed person."""
    normalized_faction = str(faction or "中立").strip()
    if normalized_faction not in content.factions:
        normalized_faction = "中立"
    return {
        "faction": normalized_faction,
        "loyalty": 60,
        "ability": 55,
        "integrity": 60,
        "courage": 50,
        "style": "新任未详",
    }


def apply_appointment(
    db: GameDB,
    state: GameState,
    content: GameContent,
    data: Optional[Dict[str, object]] = None,
    llm_config: Optional[LLMConfig] = None,
    commit: bool = True,
) -> Tuple[str, str]:
    """诏书任命共用落地：建档入库，本回合即可召见。"""
    if not data:
        return ("", "")
    if "approved" in data and not bool(data.get("approved")):
        return ("", "")
    name = str(data.get("name") or "").strip()
    office = str(data.get("office") or "").strip()
    if not name or not office:
        return ("", "")
    office = normalize_office(office)
    # 显式名分（office_type ∈ PERSON_TITLE_KINDS）在此建 Character 前就得保住：add_character 的
    # 名分守卫看的是 character.office_type，若这里先被 infer 反推成官职（office='诸生'→'生员'），
    # 守卫永远见不到名分、误建 offices/character_offices（#1059 codex l6h）。
    office_type = resolve_office_type_preserving_title(
        office,
        str(data.get("office_type") or "").strip(),
        "待铨",
        llm_config or db.llm_config,
    )
    if office_type == "后宫":
        return ("", "")

    # ── 查重：精确名 + aliases 命中即拒，不重复建档 ──────────
    # 身份归一认识未仕/宗藩——在册者（含史可法诸生）由此拒新建，走 apply_office_appointment。
    if name in content.characters:
        return ("", "")
    existing = _find_existing_minister(content, name, db)
    if existing is not None:
        return ("", "")

    # ── 职位替换：腾缺现任者 → dismissed ───────────────────────────
    displaced = ""
    replaces = str(data.get("replaces") or "").strip()
    if replaces and replaces in content.characters:
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
        content, data.get("faction"),
    )
    character = Character(
        name=name,
        office=office,
        office_type=office_type,
        aliases=[],
        personal_skills=[],
        power_id="ming",
        status="active",
        office_region=str(
            data.get("office_region") or data.get("region_id") or ""
        ).strip(),
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
    return (name, displaced)








def _pending_action_failure_payload(pa: Dict[str, Any]) -> Dict[str, Any]:
    """把落库失败的暂存动作翻成可给玩家看的失败状态。"""
    kind = str(pa.get("kind") or "")
    action = str(pa.get("action") or "")
    noun = {
        "secret_order": "密令",
        "office": "任免",
        "directive": "拟旨",
    }.get(kind, "政务动作")
    # #1765 ②：坏 payload 重放入口已删——系统层只报「未落库」这一件事，
    # 不再承诺重试、也不按失败来源分类交代（0046 薄系统层）。
    message = f"{noun}未能正式落库，已记录为失败；若暂不处理，也不会阻断继续召对。"
    return {
        "id": int(pa.get("id") or 0),
        "kind": kind,
        "action": action,
        "minister_name": str(pa.get("minister_name") or ""),
        "message": message,
    }


def _sync_offices_from_db_impl(content: GameContent, db: "GameDB", llm_config: Optional[LLMConfig] = None) -> None:
    """启动/读档时以 DB characters 表重建内存人物表。
    DB 是持久化真相；不要在这里修写 DB。"""
    rows = db.conn.execute(
        """
        SELECT c.name, c.office, c.office_type, c.faction, c.aliases, c.personal_skills,
               c.loyalty, c.ability, c.integrity, c.courage, c.style, c.identity, c.intrigue,
               c.seed_guilt,
               c.birth_year, c.historical_death_year, c.historical_death_month,
               c.debut_year, c.debut_month, c.status, c.status_reason, c.reason_code,
               c.portrait_id, c.power_id, c.location, c.transit_to,
               c.transit_distance_remaining, c.transit_speed_factor, c.transit_start_turn,
               c.summary,
               COALESCE(co.region_id, '') AS office_region
        FROM characters c
        LEFT JOIN character_offices co ON co.character_name = c.name
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
            intrigue=int(row["intrigue"]),
            seed_guilt={str(key): str(value) for key, value in seed_guilt.items()},
            # 任所 thrives only on character_offices; restore into Character for
            # runtime projection (materials scope / travel gate / seat identity).
            office_region=str(row["office_region"] or "").strip(),
        )
    content.characters = characters


def _bind_all_content(content: GameContent) -> None:
    """把 GameContent 注入所有 bind_content 模块。GameSession 启动时调一次。"""
    _bind_context(content)
    _bind_agents(content)
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
        # #1749：db/agno 打开后构造任一步失败须关闭，禁泄漏连接（load_state 等）。
        self.db = None  # type: ignore[assignment]
        self.agno_db = None  # type: ignore[assignment]
        try:
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
            self.previous_summary = ""
            self.last_decree = ""
            # P1-1：last_decree 所覆盖的 draft 指纹（write_decree 时记，颁诏时校验是否已陈旧）。
            self._decree_draft_fingerprint: Tuple[Tuple[int, str], ...] = ()
            self._begun = False
            # #1353：per-session 单写者票据队列（CLI/Web 共用）；write_gate 并入队列。
            from ming_sim.session_write_queue import SessionWriteQueue
            self._write_queue = SessionWriteQueue()
            self._write_gate = self._write_queue.write_gate
            from ming_sim.decree_forecast import bind_forecast_owner
            bind_forecast_owner(self)
            if fresh_save:
                self.auto_save("begin")
        except Exception as init_exc:
            # #1749 B：半构造清理——close 成功才清空引用；close 失败保留 db/agno，
            # 经 residual_session 携回同一 holder/CloseOp，禁无主活连接。
            residual = False
            agno = getattr(self, "agno_db", None)
            if agno is not None:
                close_fn = getattr(agno, "close", None)
                if callable(close_fn):
                    try:
                        close_fn()
                        self.agno_db = None  # type: ignore[assignment]
                    except Exception:
                        logger.exception("GameSession init failed; agno_db.close failed")
                        residual = True
                else:
                    self.agno_db = None  # type: ignore[assignment]
            db = getattr(self, "db", None)
            if db is not None:
                try:
                    db.close()
                    self.db = None  # type: ignore[assignment]
                except Exception:
                    logger.exception("GameSession init failed; db.close failed")
                    residual = True
            if residual:
                try:
                    setattr(init_exc, "residual_session", self)
                except Exception:
                    logger.exception("GameSession init failed; attach residual_session failed")
            raise

    # ── 回合生命周期 ──────────────────────────────────────────────────────

    def begin_turn(self) -> TurnSnapshot:
        """加载/刷新本回合：历史卒、上回合奏报。幂等。

        """
        # 接档/刷新阶段计时（#84）：begin_turn 是「继续」载入的慢段所在，
        # 原零日志=进度盲区；逐阶段 tlog 用时定位慢点。
        from ming_sim.token_stats import tlog
        _t = time.monotonic()
        self.state = self.db.load_state()
        self.deaths_this_turn = self.db.apply_historical_deaths(self.state)
        self.debuts_this_turn = self.db.apply_historical_debuts(self.state)
        _sync_offices_from_db_impl(self.content, self.db, self.llm_config)
        self.previous_summary = self.db.previous_turn_summary(self.state) or ""
        tlog(f"[接档] begin_turn 读档+历史 tick+人物同步+奏报 {time.monotonic() - _t:.1f}s")
        self.last_decree = ""
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
        """新回合建立（resolve 已推进 state.turn）；阶段回 summoning 并留月初档。"""
        self.state.turn_phase = TurnPhase.SUMMONING.value
        self.db.save_state(self.state)
        self.auto_save("begin")

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
        """撤回召对副作用后，用 DB 真相刷新内存人物表。"""
        self.state = self.db.load_state()
        _sync_offices_from_db_impl(self.content, self.db, self.llm_config)

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
        return character_from_name(name)

    def summon_character(
        self,
        name_or_text: str,
        current: Optional[Character] = None,
    ) -> Character:
        """召见人物：只认正式名册。"""
        target = match_minister_from_text(name_or_text, current)
        if target is not None:
            return target
        clean_name = str(name_or_text or "").strip()
        if clean_name in self.content.characters:
            return self.content.characters[clean_name]
        raise ValueError(f"人物未建档：{clean_name}")

    def can_summon(self, character: Character) -> Tuple[bool, str]:
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
        travel_tone: str = "常行",
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
        opened_new_night = False
        with atomic(self.db):
            night = get_open_night(self.db)
            if night is None:
                night = open_night(self.db, active_state)
                opened_new_night = True
            recorder(
                self.db, int(night["id"]), character.name,
                origin_id=str(origin_id).strip(),
                origin_chat_turn_id=int(origin_chat_turn_id or 0),
                **({"travel_tone": travel_tone} if recorder is record_summon_fresh else {}),
            )
        if opened_new_night:
            from ming_sim.decree_forecast import schedule_held_decree_forecasts
            schedule_held_decree_forecasts(self)
        return decision



    def _recognize_audience_command_verdict(self, message: str) -> str:
        """#526：同步识别收夜口令。纯封闭集匹配，无 Future/宽降级。"""
        from ming_sim.audience_night import (
            normalize_audience_command_verdict,
            recognize_audience_command,
        )

        return normalize_audience_command_verdict(recognize_audience_command(message))


    def close_night_after_chat_if_needed(
        self,
        court_action: str,
        *,
        write_gate: Any = None,
        barrier_ticket: Any = None,
    ) -> None:
        """#526：回话落库后由 Web/CLI epilogue 触发高置信收夜（收夜=封窗=提交）。

        失败按 ADR 0005 响亮上抛——不得静默当成已退朝；夜保持可恢复。
        write_gate：既有 runtime 写锁（Web `_runtime_write_gate` / CLI `_cli_write_gate`）；
        未显式传入时回落 session._write_gate。禁第二锁；缺锁由 close_night 卫兵响亮。

        #1353：经 session 队列屏障入队——须等已领尾随票清零后再 close（调用方不得
        在仍持本线程票据时调用，否则自等待死锁）。

        barrier_ticket：#1727 可选预领屏障票（done 前 claim_barrier，使 has_open_barrier
        对玩家写入口立刻可见）。传入则复用该票 wait→close→complete，不再另领。
        """
        from ming_sim.session_write_queue import get_session_write_queue

        q = get_session_write_queue(self)
        try:
            if str(court_action or "") != "court_break":
                return
            from ming_sim.audience_night import close_night, get_open_night

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
                    llm_config=getattr(self, "llm_config", None),
                    write_gate=gate,
                    write_queue=self._write_queue,
                )

            # 屏障只等前序票工人终态/空放行（K10a：无 elapsed 熔断）。
            # #1727：预领票复用 barrier，禁再领第二张 barrier。
            q.barrier(_do_close, ticket=barrier_ticket)
            barrier_ticket = None  # barrier 已 complete
        finally:
            # 早退/异常：预领票仍须归还，避免 has_open_barrier 永真（complete 幂等）。
            if barrier_ticket is not None:
                q.complete(barrier_ticket)

    def schedule_close_night_after_chat_if_needed(
        self,
        court_action: str,
        *,
        write_gate: Any = None,
    ) -> Optional[threading.Thread]:
        """#1842：court_break 前台先返回；预领屏障后既有队列 FIFO 转译 join→封夜。

        与 stream done 前 claim_barrier 同形——不改转译发生时间/次序，只是不挡前台。
        非 court_break 为空操作。后台失败 logger.exception 留痕（ADR 0005），票仍归还。
        """
        if str(court_action or "") != "court_break":
            return None
        from ming_sim.session_write_queue import get_session_write_queue

        q = get_session_write_queue(self)
        barrier_ticket = q.claim_barrier()
        gate = write_gate if write_gate is not None else getattr(self, "_write_gate", None)

        def _run() -> None:
            try:
                self.close_night_after_chat_if_needed(
                    court_action,
                    write_gate=gate,
                    barrier_ticket=barrier_ticket,
                )
            except Exception:
                logger.exception(
                    "background close_night_after_chat failed court_action=%s",
                    court_action,
                )
            finally:
                # 幂等：真路径已在 close_night_after_chat_if_needed 归还；
                # stub/早退漏还时仍须清 has_open_barrier。
                if barrier_ticket is not None:
                    q.complete(barrier_ticket)

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name="close-night-after-chat",
        )
        thread.start()
        return thread

    def _mark_control_turn_translation_done(self, chat_turn_id: int) -> None:
        """口令早退轮：复用转译水位单真源，避免假 pending 进 list_pending_translations。"""
        from ming_sim.audience_translation import mark_turn_translation_done

        mark_turn_translation_done(self.db, chat_turn_id, commit=True)

    def scene_chat(
        self, message: str, *, chat_turn_id: int = 0,
        stream_emit: Any = None,
        minister_name: str = "",
        on_protagonist_changed: Any = None,
    ) -> ChatTurnResult:
        """#1836 T1 / #1837 C1a / #1842 T2：一夜一场入口——一个场景 LLM 演整场。

        - 皇帝「宣 X」→ 引擎落入殿账（ADR 0037）→ 起一次场景调用
        - 「退朝」口令 → 收夜（与既有 command-verdict 同缝）
        - 一条对话轮 = 整段自由戏文（可含多人）；生成链零动作工具
        - 回话落定后一次转译（完整声明）；后台按轮串行、前台不等（#1842）。
          须 chat_turn_id>0（生产不变式；无对话轮的同步转译已删）。
        - 退役与回话并行的意图分类器 / 应允判读 / 故事抽取 / 边事件判官 /
          代码触发读心（转译承接）；按大臣 chat() 入口已退役。
        - stream_emit 非空：同核走 transport 流式（SSE delta / 重试 / 失败路径）
        """
        from ming_sim.audience_night import (
            CMD_CLOSE_NIGHT,
            CMD_NONE,
            SCENE_CHAT_SPEAKER,
            close_night,
            ensure_open_night_for_audience,
            ensure_summon_enter,
            get_open_night,
            recognize_xuan_command,
        )
        from ming_sim.llm_model import extract_agent_text

        # Free prose message: preserve raw; strip only emptiness (#1834 F16).
        message_text = str(message or "")
        if not message_text.strip():
            raise ValueError("问话不能为空。")
        from ming_sim.decree_forecast import bind_forecast_owner
        bind_forecast_owner(self)

        # 开夜（若需）；一夜一场不绑单人 minister 入口。
        night = get_open_night(self.db)
        opened_new_night = night is None
        if opened_new_night:
            night = ensure_open_night_for_audience(self.db, self.state)
            from ming_sim.decree_forecast import schedule_held_decree_forecasts
            schedule_held_decree_forecasts(self)
        night_id = int(night["id"])

        # 收夜口令。先兑现既有确定性效果，再把无需转译的源轮标 done：
        # - 退朝：chat_turn_id==0 当场收夜；非 0 只标 court_break 由 epilogue 收
        # - #1812 §5 / #1834 F18：旧「留下听着」「今日就到这里吧」不再代码裁断；
        #   走下方场景调用＋统一转译。
        audience_command_verdict = self._recognize_audience_command_verdict(message_text)
        result = ChatTurnResult(answer="")
        if audience_command_verdict and audience_command_verdict != CMD_NONE:
            ctid = int(chat_turn_id or 0)
            if audience_command_verdict == CMD_CLOSE_NIGHT:
                # 生产：退朝只标 court_break，由 epilogue 收夜（join 转译）。
                # ctid==0 的当场收夜分支随同步转译一并删除。
                if ctid > 0:
                    self._mark_control_turn_translation_done(ctid)
                    result.court_action = "court_break"
                    return result
                close_night(
                    self.db, self.state,
                    content=getattr(self, "content", None),
                    llm_config=getattr(self, "llm_config", None),
                    write_gate=getattr(self, "_write_gate", None),
                    write_queue=self._write_queue,
                )
                result.court_action = "court_break"
                return result

        # 「宣 X」→ 确定性落入殿账，再起场景调用（X 开不开口由 LLM 演）。
        xuan_fragment = recognize_xuan_command(message_text)
        if xuan_fragment:
            fragment = str(xuan_fragment).strip()
            chars = getattr(getattr(self, "content", None), "characters", None) or {}
            target = chars.get(fragment) or match_minister_from_text(fragment)
            if target is None:
                try:
                    target = self.summon_character(fragment)
                except ValueError:
                    target = None
            if target is not None:
                decision = self.consume_audience_admission(
                    target,
                    origin_id=f"scene:xuan:{int(chat_turn_id or 0)}:{target.name}",
                    origin_chat_turn_id=int(chat_turn_id or 0),
                )
                if decision.allowed:
                    ensure_summon_enter(
                        self.db, night_id, target.name,
                        origin_chat_turn_id=int(chat_turn_id or 0),
                    )
                    # #1838 / ADR 0158：宣 X 当场先切御前主角（不等转译）。
                    # 夜当前值是投影；ctid>0 时同步写 chat_turns.protagonist_name
                    # 作按源轮真源，供 undo 按存活最近轮重投影（ADR 0038 / 0155）。
                    # ctid==0：无源轮场景（单测/无生命周期），只写夜表、不参与撤回联动
                    # ——与入殿账 origin_chat_turn_id==0 框架账不随轮撤同语义。
                    from ming_sim.audience_night import set_night_protagonist
                    set_night_protagonist(
                        self.db, night_id, target.name, reason="xuan",
                    )
                    xuan_ctid = int(chat_turn_id or 0)
                    if xuan_ctid > 0:
                        self.db.conn.execute(
                            "UPDATE chat_turns SET protagonist_name=? WHERE id=?",
                            (target.name, xuan_ctid),
                        )
                        if (
                            not bool(getattr(self.db.conn, "_commit_suspended", False))
                            and int(getattr(self.db.conn, "_atomic_depth", 0) or 0) == 0
                        ):
                            self.db.conn.commit()
                    if on_protagonist_changed is not None:
                        on_protagonist_changed()
            # 被拒的宣召仍是一轮殿上戏文；只在合法入殿时先写入殿账。
            # #1838 reopen：不再等入殿旁白。

        # 材料目录：在场诸人各一份；开场最小集 + 只读工具。
        prepared = prepare_scene_materials(self.db, self.state)
        llm_config = getattr(self, "llm_config", None)
        if llm_config is None:
            raise RuntimeError("scene_chat 需要 llm_config。")
        agent = self._resolve_scene_agent(prepared, night_id=night_id)

        # opening 已在 create_scene_agent instructions；run 输入只传本轮皇帝原话。
        agent_prompt = message_text
        transport_attempts_box: list = []
        if stream_emit is not None:
            answer, transport_attempts_box = self._run_scene_agent_transport(
                agent, agent_prompt, stream_emit,
                chat_turn_id=int(chat_turn_id or 0),
            )
        else:
            from ming_sim.llm_transport import (
                audience_transport_policy, bind_transport_sdk_budget,
                empty_output_failure, run_with_transport,
                transport_attempts_public, transport_failure_unavailable,
            )
            policy = audience_transport_policy(llm_config)
            def _run_nonstream() -> Any:
                output = agent.run(agent_prompt)
                extracted = extract_agent_text(output)
                if not extracted:
                    raise transport_failure_unavailable(
                        empty_output_failure(), attempts=1, exhausted=False,
                    )
                return output
            with bind_transport_sdk_budget(getattr(agent, "model", None), policy):
                run_output, attempts = run_with_transport(
                    _run_nonstream, policy=policy,
                )
            _dump_llm_messages(run_output, f"场景召对/{SCENE_CHAT_SPEAKER}")
            answer = extract_agent_text(run_output)
            transport_attempts_box = transport_attempts_public(attempts)
        result = ChatTurnResult(answer=answer)
        if transport_attempts_box:
            # 结构化 attempts 账挂结果，供流式 payload 回指（非 prose）。
            result.transport_attempts = transport_attempts_box  # type: ignore[attr-defined]

        # #1842：ctid>0 → 暂存转译参数（persist 后 schedule）；ctid==0 → 同步落定。
        # 不跑并行分类器 / 故事抽取 / 边事件判官 / 读心——转译一次承接。
        self._apply_scene_turn_translation(
            result, message_text, answer, night_id=night_id,
            chat_turn_id=int(chat_turn_id or 0),
        )
        return result

    def _resolve_scene_agent(self, prepared: Any, *, night_id: int) -> Any:
        """生产 create_scene_agent；测试经 monkeypatch 此工厂缝注入，禁实例双桩属性。"""
        llm_config = getattr(self, "llm_config", None)
        return create_scene_agent(
            llm_config,
            prepared,
            agno_db=getattr(self, "agno_db", None),
            content=getattr(self, "content", None),
            session_id=f"scene-night-{night_id}",
        )

    def _run_scene_agent_transport(
        self,
        agent: Any,
        agent_prompt: str,
        stream_emit: Any,
        *,
        chat_turn_id: int = 0,
    ) -> tuple[str, list]:

        """场景 agent 的 transport 流式核——零动作工具；材料只读工具不进 court_action。"""

        from ming_sim.llm_model import extract_agent_text, fail_if_llm_error
        from ming_sim.llm_transport import (
            bind_transport_sdk_budget,
            empty_output_failure,
            is_stream_activity_event,
            map_run_error_event,
            audience_transport_policy,
            run_transport_stream,
            transport_attempts_public,
            transport_failure_unavailable,
        )

        llm_cfg = getattr(self, "llm_config", None)
        policy = audience_transport_policy(llm_cfg)
        chunks: list[str] = []
        run_output_box: list = []
        stream_attempt_n = {"n": 0}

        def _on_event(event: Any) -> None:
            name = type(event).__name__
            if name == "RunContent" or getattr(event, "event", None) == "RunContent":
                piece = str(getattr(event, "content", "") or "")
                if piece:
                    chunks.append(piece)
                    stream_emit(piece)
            if name in ("RunOutput", "RunCompletedEvent"):
                run_output_box.clear()
                run_output_box.append(event)

        def _after_stream():
            run_output = run_output_box[0] if run_output_box else None
            _dump_llm_messages(
                run_output, f"场景召对/{getattr(agent, 'name', '殿上')}", agent=agent,
            )
            # P6 / #671：流式拼装不得 strip；玩家可见原文（含首尾空白）原样保留。
            answer = "".join(chunks)
            if run_output is not None:
                extracted = extract_agent_text(run_output)
                if not answer:
                    answer = extracted
            else:
                fail_if_llm_error(answer, "LLM 调用")
            if not answer:
                raise transport_failure_unavailable(
                    empty_output_failure(), attempts=1, exhausted=False,
                )
            return answer, run_output

        def _start_stream():
            chunks.clear()
            run_output_box.clear()
            if stream_attempt_n["n"] > 0:
                stream_emit("", replace=True)
                if int(chat_turn_id or 0) > 0:
                    self.db.truncate_chat_turn_agno_runs(int(chat_turn_id))
            stream_attempt_n["n"] += 1
            return agent.run(
                agent_prompt, stream=True, stream_events=True, yield_run_output=True,
            )

        with bind_transport_sdk_budget(getattr(agent, "model", None), policy):
            (answer, _run_output), attempts_box = run_transport_stream(
                _start_stream,
                on_event=_on_event,
                is_activity_event=is_stream_activity_event,
                map_error_event=map_run_error_event,
                after_stream=_after_stream,
                policy=policy,
            )
        public = transport_attempts_public(attempts_box) if attempts_box else []
        return str(answer or ""), list(public)

    def _apply_scene_turn_translation(
        self,
        result: "ChatTurnResult",
        emperor_message: str,
        reply: str,
        *,
        night_id: int,
        chat_turn_id: int = 0,
    ) -> None:
        """#1837/#1842：场景入口只暂存转译参数；persist 后 schedule 后台唯一路径。"""
        if GameSession._proposal_blocked(self.state):
            return
        ctid = int(chat_turn_id or 0)
        if ctid <= 0:
            return
        result.pending_audience_translation = {
            "emperor_message": emperor_message,
            "reply": reply,
            "night_id": int(night_id or 0),
            "chat_turn_id": ctid,
            "minister_name": "",
        }

    def schedule_pending_scene_translation(
        self, result: "ChatTurnResult",
    ) -> Optional["Future"]:
        """#1842：回话已 persist 后冲刷 scene_chat 暂存的后台转译。

        无暂存则 no-op。调用方须先落大臣回话（generating→active + minister_message_id）。
        """
        pending = getattr(result, "pending_audience_translation", None)
        if not pending:
            return None
        result.pending_audience_translation = None
        from ming_sim.audience_translation import schedule_audience_turn_translation
        from ming_sim.session_write_queue import get_session_write_queue

        write_queue = get_session_write_queue(self)
        from ming_sim.decree_forecast import bind_forecast_owner
        bind_forecast_owner(self)

        return schedule_audience_turn_translation(
            self.db,
            self.state,
            emperor_message=str(pending.get("emperor_message") or ""),
            reply=str(pending.get("reply") or ""),
            night_id=int(pending.get("night_id") or 0),
            chat_turn_id=int(pending.get("chat_turn_id") or 0),
            minister_name=str(pending.get("minister_name") or ""),
            llm_config=getattr(self, "llm_config", None),
            write_gate=getattr(self, "_write_gate", None),
            write_queue=write_queue,
            admitted_ticket=getattr(result, "_admitted_write_ticket", None),
        )



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
        if not directive_payload_admits_structured_write(payload):
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

    def _resubmit_draft_admission_failures(
        self, rejections: List[Dict[str, object]],
        carry_over: Optional[Dict[int, Dict[str, object]]] = None,
    ) -> Dict[int, Dict[str, object]]:
        """#1769 结算路 B：产物错 draft 把失败事实与原产物告诉 LLM 重交 payload。

        单轮批处理：对当前失败旨各重写一次；外层 resolve_turn 按
        DRAFT_ADMISSION_RESUBMIT_REWRITES 循环本方法（原抽 + 重写 2 = 总计 3）。
        与组合/名册 heal_retries 独立。产物错 ValueError 视为本轮该旨仍失败；
        其它异常走错误包 + SettlementAbort（0005/0008）。
        独立失败旨并行调 LLM（P5，复用 ThreadPoolExecutor；DB 写仍串行）。

        carry_over（上一轮返回值）：写回被拒时 DB 里仍是旧载荷，光按 DB 重问 =
        拿旧拒因问第二遍。故把**本次**产物与**本次**写回失败事实带到下一次重写；
        返回值即下一轮的 carry_over（写回成功的旨不入内，改按 ensure 新拒因走）。
        """
        from ming_sim.cli_backend import resubmit_draft_admission_payload
        from ming_sim.error_pack import settlement_abort_message, write_error_pack
        from ming_sim.exceptions import SettlementAbort

        carried = dict(carry_over or {})
        jobs: List[Dict[str, object]] = []
        for item in rejections or []:
            try:
                did = int(item.get("directive_id"))
            except (TypeError, ValueError):
                continue
            if self.db.get_dossier_for_directive(did) is not None:
                continue
            row = self.db.get_directive(did)
            if row is None or str(row["status"] or "") != "draft":
                continue
            try:
                bad_payload = self.db.read_directive_dossier_payload(row)
            except ValueError:
                continue
            reason = str(item.get("reason") or "")
            prior = carried.get(did)
            if prior is not None:
                # 上一轮写回被拒：DB 仍是旧载荷，须以上一轮产物 + 写回拒因回喂。
                bad_payload = dict(prior.get("bad_payload") or bad_payload)
                reason = str(prior.get("reason") or reason)
            jobs.append({
                "directive_id": did,
                "text": str(row["text"] or ""),
                "bad_payload": bad_payload,
                "reason": reason,
                "existing_mode": bad_payload.get("mode"),
            })
        if not jobs:
            return {}

        llm_config = getattr(self, "llm_config", None)
        content = getattr(self, "content", None)

        def _llm_one(
            job: Dict[str, object],
        ) -> Tuple[Dict[str, object], Optional[Dict[str, object]], Optional[Exception]]:
            try:
                payload = resubmit_draft_admission_payload(
                    str(job["text"]),
                    bad_payload=job["bad_payload"],  # type: ignore[arg-type]
                    failure_reason=str(job["reason"] or ""),
                    llm_config=llm_config,
                    db=self.db,
                    content=content,
                    existing_mode=job.get("existing_mode"),
                )
                return job, payload, None
            except Exception as exc:
                # 与 ensure / relation_brew 同形：只收 Exception；KeyboardInterrupt/
                # SystemExit 不得洗成 SettlementAbort。
                return job, None, exc

        # P5：批内独立失败旨并行 LLM；单条不建 pool。
        if len(jobs) > 1:
            workers = len(jobs)
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="draft-admission-resubmit",
            ) as pool:
                outcomes = list(pool.map(_llm_one, jobs))
        else:
            outcomes = [_llm_one(jobs[0])]

        # DB 相串行：产物 ValueError 耗尽该旨；其它异常错误包中止整月。
        next_carry: Dict[int, Dict[str, object]] = {}
        for job, new_payload, exc in outcomes:
            did = int(job["directive_id"])
            if exc is not None:
                if isinstance(exc, ValueError):
                    # 本轮重写自身的产物错（含名册 escalate 归一）：DB 载荷未动，
                    # 光靠下一轮 ensure 重探只会拿回旧拒因——把本轮失败事实带过去，
                    # 否则同一句话问三遍（0150-D5-b：告诉 LLM 事实）。
                    logger.warning(
                        "[1769] draft#%s admission resubmit product exhaust: %s",
                        did, exc,
                    )
                    next_carry[did] = {
                        "bad_payload": dict(job["bad_payload"]),  # type: ignore[arg-type]
                        "reason": str(exc),
                    }
                    continue
                pack_path = write_error_pack(
                    self.db, self.state, exc=exc, extracted=None, resolve_ctx=None,
                )
                raise SettlementAbort(
                    settlement_abort_message(pack_path),
                    turn=int(self.state.turn),
                    stage="directive_admission_resubmit",
                    error_pack_path=pack_path,
                ) from exc
            assert new_payload is not None
            try:
                self.db.update_directive_text(
                    did,
                    str(job["text"] or ""),
                    dossier_payload=new_payload,
                    replace_payload=True,
                )
            except ValueError as write_exc:
                # 写回被拒也是产物错：本次产物 + 本次写回拒因带进下一次重写，
                # 否则下一轮只能拿 DB 里的旧载荷/旧拒因重问同一遍。
                logger.warning(
                    "[1769] draft#%s admission resubmit write-back rejected: %s",
                    did, write_exc,
                )
                next_carry[did] = {
                    "bad_payload": dict(new_payload),
                    "reason": str(write_exc),
                }
            except Exception as write_exc:
                pack_path = write_error_pack(
                    self.db, self.state, exc=write_exc,
                    extracted=None, resolve_ctx=None,
                )
                raise SettlementAbort(
                    settlement_abort_message(pack_path),
                    turn=int(self.state.turn),
                    stage="directive_admission_resubmit",
                    error_pack_path=pack_path,
                ) from write_exc
        return next_carry

    def await_translations_before_month(
        self, after_drain=None, *, write_gate_already_held: bool = False,
    ) -> None:
        """过月前转译：join 等到清空 → catch-up → 真耗尽走 0157。

        #1842 / ADR 0155 两态：① 未完成则过月等（join 缝系统内等待后自动续跑，
        不得 SettlementAbort/409）；② 耗尽才 write_error_pack+SettlementAbort。
        hang 切断：join 未清空不进阻塞 catch-up。

        **闸外契约**（同 close_night「join 在闸外」、HITL「禁整段 gate 盖 join」）：
        调用方不得在持非重入 write_gate 时进入本方法的等待路径。web 受理样板在
        hold_write_for_body 之前调用本方法；resolve_turn 再调一次时 join 已清空、
        立即放行。本方法**绝不** release/acquire write_gate（不猜锁所有权、不偷放）。
        调用方已持闸时须显式声明；其余路径始终传递真实 gate，
        不得把“他线程正持有”误判为本线程可无锁访问 SQLite。
        """
        from ming_sim.mechanical_tail import ensure_mechanical_tails
        ensure_mechanical_tails(self)
        from ming_sim.audience_translation import (
            catch_up_pending_translations,
            list_pending_translations,
        )
        from ming_sim.session_write_queue import get_session_write_queue
        from ming_sim.error_pack import settlement_abort_message, write_error_pack
        from ming_sim.exceptions import SettlementAbort

        # ① SessionWriteQueue 是唯一在飞真源；同一 barrier 连续覆盖
        # 既受理转译、欠账补跑和调用方收夜，不留重新准入窗口。
        write_queue = get_session_write_queue(self)
        def _drain_catch_up_and_continue() -> None:
            # 票的完成只表示本次 worker 已终止，不代表机械尾已终结。
            # 屏障等完票后复查持久状态；非耗尽异常留下 pending 时不能过月。
            from ming_sim.mechanical_tail import _pending_mechanical_tails
            from ming_sim.mechanical_tail import failed_mechanical_tail
            failure = failed_mechanical_tail(self.db, self.state)
            pending_tails = _pending_mechanical_tails(
                self.db, current_turn=int(self.state.turn),
            )
            if failure or pending_tails:
                exc = RuntimeError(
                    f"机械尾未终结，不能过月：{[turn for turn, _ in pending_tails]}"
                )
                pack_path = (
                    str(failure[1]["error_pack_path"])
                    if failure and failure[1].get("error_pack_path") else None
                )
                if pack_path is None:
                    try:
                        raise exc
                    except RuntimeError as pending_exc:
                        pack_path = write_error_pack(
                            self.db, self.state, exc=pending_exc,
                            extracted=None, resolve_ctx=None,
                        )
                raise SettlementAbort(
                    settlement_abort_message(pack_path),
                    turn=int(self.state.turn),
                    stage="mechanical_tail_pending",
                    error_pack_path=pack_path,
                ) from exc
            catch_gate = None if write_gate_already_held else self._write_gate
            catch_up_pending_translations(
                self.db, self.state,
                llm_config=getattr(self, "llm_config", None),
                write_gate=catch_gate,
                write_queue=write_queue,
                within_barrier=True,
            )
            still_pending = list_pending_translations(self.db)
            if still_pending:
                exc = RuntimeError(
                    f"召对转译重试耗尽，待补 {len(still_pending)} 轮"
                )
                pack_path = write_error_pack(
                    self.db, self.state, exc=exc, extracted=None, resolve_ctx=None,
                )
                raise SettlementAbort(
                    settlement_abort_message(pack_path),
                    turn=int(self.state.turn),
                    stage="audience_translation_exhausted",
                    error_pack_path=pack_path,
                ) from exc
            from ming_sim.audience_night import commit_late_night_approved
            commit_late_night_approved(
                self.db, self.state,
                content=getattr(self, "content", None),
                llm_config=getattr(self, "llm_config", None),
                write_gate=catch_gate,
            )
            if after_drain is not None:
                after_drain()

        write_queue.barrier(_drain_catch_up_and_continue)

    def resolve_turn(self, decree: str = "", cheat_directive: str = "",
                     *, allow_empty_decree: bool = False,
                     write_gate_already_held: bool = False) -> ResolveResult:
        """颁诏并推演本回合（phase1）。

        cheat_directive: 作弊控制台强制结算项，一次性透传给 resolve_directives。
        allow_empty_decree: 退朝无旨入口（#1274）置 True——directives=[] 仍走完整结算链
            （source=system_simulation）；颁诏 issue 路径保持默认 False（无草案 → 400）。

        返回 ResolveResult：含决策点 → awaiting=True，置 awaiting_decision 态，回合未推进，
        调用方据 result.decisions 弹窗，皇帝裁完调 submit_decisions。无决策点但邸报
        尚未归档时 awaiting=False、advanced=False，仍停 settling；归档后才置 issued。
        """
        # #1842：过月前转译 join/catch-up/耗尽判定（闸外契约，见 await_translations_before_month）。
        # #1845：未完机械尾由 await_translations_before_month 续接后再进 barrier，不在此重复认领。
        if not write_gate_already_held:
            self.await_translations_before_month()
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
                decisions=self.pending_decisions(),
                advanced=False,
            )
        # settling 仅证明前半段已提交；#1846 恢复真源是暂存声明与落账相位，
        # 从 context 恢复来源和原诏后续跑月链，财政不二落。
        recovered_source = None
        if self.state.turn_phase == TurnPhase.SETTLING.value:
            ctx = self.db.get_resolve_context(self.state.turn)
            if ctx is not None:
                recovered_source = _provenance_from_stored(ctx.get("source"))
                # Free prose decree_text: preserve raw; strip only emptiness.
                stored = str(ctx.get("decree_text") or "")
                if stored.strip():
                    self.last_decree = stored
                    decree = stored
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
        # Close-night owns short write sections + gate-free pending translations.
        # Web 入口先在闸外 free-close（issue/stream/no-edict），再持闸跑 resolve；
        # 此处幂等兜底 CLI/直调。
        # 调用方显式声明已持同一把非重入锁时不得再传入，避免 close 短写自锁；
        # CLI/直调未持闸则始终传真实 gate，不用“抢不到”猜测所有权。
        try:
            if not write_gate_already_held:
                auto_close_open_night(
                    self.db, self.state,
                    content=getattr(self, "content", None),
                    llm_config=getattr(self, "llm_config", None),
                    write_gate=self._write_gate,
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
        # #658：Web/CLI free-form draft 在真实颁诏链进入唯一成案接缝（confirm/commit
        # 已各自 ensure；本口覆盖 add_directive 直落 draft 的路径，幂等）。
        # #1769：产物错 → 告诉 LLM 失败事实与原产物后重交；耗尽保持 draft、月照过
        # （替代 #1591「产物错即整月不推进 + 引擎串透传」；真故障仍 SettlementAbort）。
        # 成案补交边界 = 原抽 + 重写 DRAFT_ADMISSION_RESUBMIT_REWRITES 次（总计 3）；
        # 与组合/名册 heal_retries 独立。首轮/中间 ensure 只探测，拒只在末轮耗尽落痕。
        dossier_rejections = self.db.ensure_dossiers_for_draft_directives(
            self.state, record_rejections=False,
        )
        resubmit_carry: Dict[int, Dict[str, object]] = {}
        for rewrite_i in range(DRAFT_ADMISSION_RESUBMIT_REWRITES):
            if not dossier_rejections:
                break
            resubmit_carry = self._resubmit_draft_admission_failures(
                dossier_rejections, resubmit_carry,
            )
            is_last = rewrite_i == DRAFT_ADMISSION_RESUBMIT_REWRITES - 1
            dossier_rejections = self.db.ensure_dossiers_for_draft_directives(
                self.state, record_rejections=is_last,
            )
        dossiered_directives = list(self.db.list_dossiered_draft_directives(self.state))
        # DB owner supplies the canonical read-only default-approval projection.
        # Negative preview ids participate in stale-decree fingerprinting without
        # colliding with durable turn_directives ids.
        pending_directives = self.db.preview_pending_directives(
            self.state, content=getattr(self, "content", None),
        )
        directives = list(dossiered_directives)
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
        # #1769 耗尽：产物错 draft 留到下月；不得把引擎拒因串透传给皇帝，不得挡月份。
        # 真拒因已在 rejection_reports 留痕（#1591 保留面）。
        product_exhaust = bool(dossier_rejections)
        # #1769 零成案耗尽与退朝无旨同形：不把 last_decree/显式 decree 当本月已颁。
        # 混合好旨（dossiered 非空）仍走 player_decree、仍计已颁。
        if product_exhaust and not dossiered_directives:
            decree = ""
            self.last_decree = ""
            self._decree_draft_fingerprint = ()
        if not directives and not settlement_due and not pending_action_due:
            # 恢复态且有存诏：免草案要求（零草案 settling 属真实恢复态，
            # 而 add 已冻结——硬要草案=循环死路，ship-pre r5）。directives 仅作非空哨兵。
            if (self.state.turn_phase in FRONT_HALF_DONE_PHASES
                    and (self.last_decree or "").strip()):
                directives = [{"text": self.last_decree}]
            elif allow_empty_decree or recovered_source is not None or product_exhaust:
                # #1274：无旨月 / 结算中恢复 — decrees=[] 走完整链，不拒。
                # #1769：补交耗尽仍无成案旨 — 月照过，draft 跨月保留。
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
        # #1769 补交耗尽无成案旨：同走 system_simulation，月照过。
        resolve_kwargs = {}
        if recovered_source is not None:
            resolve_kwargs["source"] = recovered_source
        elif (
            (allow_empty_decree or product_exhaust)
            and not directives
            and not (decree_text or "").strip()
        ):
            resolve_kwargs["source"] = Provenance.system_simulation
        result = resolve_directives(
            self.state, self.db, self.agno_db, self.llm_config,
            directives, decree_text, deaths_this_turn=self.deaths_this_turn,
            debuts_this_turn=self.debuts_this_turn,
            content=self.content,
            cheat_directive=cheat_directive,
            **resolve_kwargs,
        )
        if result.advanced and not result.awaiting:
            # 主链已推进；阶段标 issued。未推进的批红/邸报交接保持 settling，重入接着跑。
            self.state.turn_phase = TurnPhase.ISSUED.value
        elif result.awaiting:
            # 决策点暂停：回合未推进，存 awaiting 态供刷新恢复；待 submit_decisions 续跑。
            self.state.turn_phase = TurnPhase.AWAITING_DECISION.value
        else:
            self.state.turn_phase = TurnPhase.SETTLING.value
        # 机械尾已在推进后占用同一条连接。这次落相位走写队列那把闸
        # （与尾部读写票同一对象）；调用方已持闸时不再重入。
        if write_gate_already_held:
            self.db.save_state(self.state)
        else:
            from ming_sim.session_write_queue import get_session_write_queue
            with get_session_write_queue(self).write_gate:
                self.db.save_state(self.state)
        return result

    def pending_decisions(self) -> List[Dict[str, object]]:
        """玩家案头：急务 ∪ 本月 decision。已应用改票锚不是新待裁。

        原始行仍在 list_rescript_desk，供同 body 重交核对。
        """
        from ming_sim.rescript_actions import row_is_applied_return_revise

        return [
            row for row in self.db.list_rescript_desk(int(self.state.turn))
            if not row_is_applied_return_revise(row)
        ]

    def _assert_awaiting_decision_submit(self) -> None:
        if self.current_phase() != TurnPhase.AWAITING_DECISION:
            raise ValueError("当前不在待裁决策阶段，无法提交亲裁。")

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
            _assert_army_targets_grounded,
            _parse_rescript_json_strict,
            normalize_rescript_layer_a_option,
        )

        self._assert_awaiting_decision_submit()
        desk = list(self.db.list_rescript_desk(int(self.state.turn)))
        ctx = self.db.get_resolve_context(self.state.turn)
        # #389：event_id 缺失/回显越权（越出本回合候选快照）时以候选快照重绑——
        # 迁自旧 submit_decisions 的绑定步（与 choices[idx] 位置写协议无关，非
        # 猜绑，唯一权威仍是 bind_decisions_to_candidate_events）；scope 与旧
        # list_pending_decisions 同款只收 kind='decision'，rescript_draft 行不动。
        if ctx is not None:
            from ming_sim.settlement_payload import bind_decisions_to_candidate_events
            decision_rows = [r for r in desk if str(r.get("kind") or "") == "decision"]
            other_rows = [r for r in desk if str(r.get("kind") or "") != "decision"]
            desk = other_rows + bind_decisions_to_candidate_events(
                decision_rows, ctx.get("simulator_payload"),
            )
        # #1589：位置补键/猜绑协议已删——choice 须显式携带 decision_key；
        # 缺键/重复键/desk 外键/非 object 项由 validate_request_keys（内存）
        # 在领域写前整批拒，此处不再静默丢非 object 项。
        req = list(choices)
        # C1.1：① 已落 decided、③ phase2 崩溃重入——
        # list_rescript_desk 只 pending，须把请求键对应 decided 行并入 desk
        # 供 validate already_applied；已落选择不再二次写。
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
            army_targets = [
                dict(row) for row in self.db.conn.execute(
                    "SELECT id, name, station FROM armies WHERE owner_power='ming' ORDER BY name"
                )
            ]
            payload = {
                "mode": "single_row_revise",
                "title": item.row.get("title"),
                "context": item.row.get("context"),
                "prior_options": item.row.get("options"),
                "note": item.choice.get("note") or "",
                "army_targets": army_targets,
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
            options = [
                normalize_rescript_layer_a_option(opt, generation_admission=True)
                for opt in options_raw
            ]
            _assert_army_targets_grounded(
                [{"options": options}], {str(row["id"]) for row in army_targets},
            )
            return options

        def _deliberate_runner(item: ra.ValidatedItem) -> Dict[str, object]:
            # #658：站台意愿 + typed supporter_ids；读关系账/派系态势切片，禁第二 roster
            from ming_sim.agents import run_agent_text
            from ming_sim.relation_read import project_relation_ledger
            candidates = ra.list_deliberation_candidate_ids(self.db, self.content)
            relation_slice = project_relation_ledger(self.db, viewer=None)
            # 仅保留候选相关边，避免整账灌入
            cand_set = set(candidates)
            relation_slice = [
                row for row in relation_slice
                if str(row.get("source") or "") in cand_set
                or str(row.get("target") or "") in cand_set
            ]
            # #658：派系态势只保留候选人物 canonical faction 相关行，不灌全表
            characters = getattr(self.content, "characters", {}) or {}
            cand_factions = {
                str(getattr(characters.get(name), "faction", "") or "").strip()
                for name in candidates
            }
            cand_factions.discard("")
            faction_rows = [
                row for row in self.db.get_faction_stance_summaries()
                if str(row.get("faction") or "") in cand_factions
            ]
            agent = create_rescript_deliberate_agent(self.llm_config, self.agno_db)
            prompt = (
                "请为以下急务拟定下部议/廷议站台（JSON："
                "{\"title\":\"...\",\"body\":\"...\",\"stance\":\"...\","
                "\"supporter_ids\":[\"...\"]}）。\n"
                f"标题：{item.row.get('title')}\n语境：{item.row.get('context')}\n"
                f"批语：{item.choice.get('note') or ''}\n"
                f"候选大臣（只可从中选 supporter_ids，可空）：{json.dumps(candidates, ensure_ascii=False)}\n"
                f"关系账切片：{json.dumps(relation_slice, ensure_ascii=False)}\n"
                f"派系态势：{json.dumps(faction_rows, ensure_ascii=False)}"
            )
            raw = run_agent_text(agent, prompt, tag="rescript-deliberate")
            obj = _parse_rescript_json_strict(str(raw or ""))
            if not isinstance(obj, dict):
                raise ValueError("deliberate LLM 意愿须为 object")
            # Free prose deliberate title/body/stance: preserve raw; emptiness on copy (#1834 F16).
            title = str(obj.get("title") or "")
            body = str(obj.get("body") or "")
            stance = str(obj.get("stance") or "")
            if not (title.strip() and body.strip() and stance.strip()):
                raise ValueError("deliberate LLM 意愿缺 title/body/stance")
            # shape 初检；身份合法性在 apply 事务内再核（整批零写）
            supporters = obj.get("supporter_ids", [])
            if supporters is None:
                supporters = []
            if not isinstance(supporters, list):
                raise ValueError("deliberate supporter_ids 须为数组")
            return {
                "title": title, "body": body, "stance": stance,
                "supporter_ids": supporters,
            }

        prewrite = ra.run_prewrite_llms(
            batch,
            revise_runner=_revise_runner if any(i.needs_revise_llm for i in batch.items) else None,
            deliberate_runner=_deliberate_runner if any(i.needs_deliberate_llm for i in batch.items) else None,
        )
        return {
            "batch": batch,
            "prewrite": prewrite,
            "desk": desk,
            "choices": req,
        }

    def commit_rescript_phase1(self, prewrite_state: Dict[str, object]) -> Dict[str, object]:
        """#657 ① 短写（调用方已持 write_gate）：C1 apply + 召见入殿事实账。

        #1838 reopen：召见只落入殿账，不建旁白对话轮、不 start scene。
        """
        from ming_sim import rescript_actions as ra
        from ming_sim.audience_night import (
            prepare_rescript_summon_scaffold,
            rescript_summon_origin_ref,
        )

        batch: ra.ValidatedBatch = prewrite_state["batch"]  # type: ignore[assignment]
        prewrite: ra.PrewriteResults = prewrite_state["prewrite"]  # type: ignore[assignment]
        apply = ra.apply_rescript_batch(
            self.db, self.state, batch, prewrite, content=self.content,
        )

        summons: List[Dict[str, object]] = []
        for key in apply.summon_keys:
            item = next((i for i in batch.items if i.decision_key == key), None)
            if item is None:
                continue
            target = str(item.choice.get("summon_target") or "").strip()
            origin = rescript_summon_origin_ref(
                item.source_turn, item.idx, int(item.row.get("revision_round") or 0),
            )
            entry = prepare_rescript_summon_scaffold(
                self.db, self.state,
                person_name=target,
                origin_ref=origin,
            )
            summons.append({
                "decision_key": key,
                "origin_ref": origin,
                "target": target,
                **entry,
            })
        return {
            "apply": apply,
            "summons": summons,
            "revise_keys": list(apply.revise_keys),
            "batch": batch,
        }

    def join_rescript_summons(
        self, phase1_state: Dict[str, object],
    ) -> Dict[str, object]:
        """#1838 reopen：召见无旁白 Future 可等；原样透传 phase1 summons。"""
        if phase1_state.get("ready_replay"):
            return {"joined": [], "ready_replay": True}
        return {"joined": list(phase1_state.get("summons") or []), "ready_replay": False}

    def finish_rescript_phase2(
        self,
        phase1_state: Dict[str, object],
        join_state: Dict[str, object],
        *,
        cheat_directive: str = "",
    ) -> str:
        """#657 ③ 短写（调用方已持 write_gate）：召见消费门闩 + phase2。

        #1838 reopen：已消费 ≔ origin_ref + TAG_ENTER；不再读取旁白正文。
        """
        if not phase1_state.get("ready_replay"):
            from ming_sim.audience_night import rescript_summon_origin_consumed
            unconsumed: List[str] = []
            seen_origins: set[str] = set()
            for item in join_state.get("joined") or []:
                origin = str(item.get("origin_ref") or "")
                if origin:
                    seen_origins.add(origin)
                row = self.db.conn.execute(
                    "SELECT tags FROM story_ledger_entries WHERE origin_ref = ?",
                    (origin,),
                ).fetchone()
                entry = {"tags": str(row["tags"] or "[]")} if row is not None else None
                if not rescript_summon_origin_consumed(entry):
                    unconsumed.append(
                        f"{item.get('decision_key')}:{item.get('target') or ''}:{origin}"
                    )
            for fact in self._iter_unconsumed_decided_summons():
                origin = str(fact.get("origin_ref") or "")
                if origin in seen_origins:
                    continue
                unconsumed.append(
                    f"{fact.get('decision_key')}:{fact.get('target') or ''}:{origin}"
                )
            if unconsumed:
                raise ValueError(
                    "召见尚未消费，不得推进 phase2：" + "; ".join(unconsumed)
                )

        if not (self.last_decree or "").strip():
            ctx0 = self.db.get_resolve_context(self.state.turn)
            if ctx0 is not None:
                self.last_decree = str(ctx0.get("decree_text") or "")

        before_turn = int(self.state.turn)
        report = resolve_decisions_phase2(
            self.state, self.db, self.agno_db, self.llm_config,
            content=self.content,
            cheat_directive=cheat_directive,
        )
        self.state.turn_phase = (
            TurnPhase.ISSUED.value
            if int(self.state.turn) != before_turn or self.state.ended
            else TurnPhase.SETTLING.value
        )
        self.db.save_state(self.state)
        return report

    def resolve_rescript_decisions(
        self,
        choices: List[Dict[str, object]],
        *,
        write_gate: Any,
        cheat_directive: str = "",
    ) -> str:
        """#657 急务/keyed 唯一编排出口。

        PRE 锁外 → ① 持 write_gate → ② 无锁 join → ③ 再持同一 write_gate。
        调用方只注入既有 write_gate；禁平行复制本配方。
        """
        if write_gate is None:
            raise ValueError("resolve_rescript_decisions 须注入既有 write_gate")
        pre = self.prepare_rescript_prewrite(choices)
        with write_gate:
            p1 = self.commit_rescript_phase1(pre)
        joined = self.join_rescript_summons(p1)
        with write_gate:
            return self.finish_rescript_phase2(
                p1, joined, cheat_directive=cheat_directive,
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
                "SELECT tags FROM story_ledger_entries WHERE origin_ref = ?",
                (origin,),
            ).fetchone()
            entry = {"tags": str(row["tags"] or "[]")} if row is not None else None
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
        cheat_directive: str = "",
    ) -> str:
        """#657 HITL 公共入口：desk 非空或 choices 非空 → resolve_rescript_decisions；
        desk 与 choices 均空 → gate 内 submit_decisions。

        #1589：choice 缺 decision_key / 非 object 的位置序载荷不再被受理——
        desk 非空或原始 choices 非空一律经 resolve_rescript_decisions →
        validate_request_keys（内存，唯一 envelope/key membership 权威）在
        领域写前整批拒；不在此处平行探测 keyed 或另拒空-desk 非空批。
        仅 desk 空且原始 choices 真空时（含 #1322 空 choices 续跑）仍走
        submit_decisions；desk 无 pending 急务但仍有未消费 durable decided
        summon 时，交回同一 resolve_rescript_decisions（C1 already_applied →
        scaffold/registry），不得直 submit_decisions 越过召见。
        """
        if write_gate is None:
            raise ValueError("submit_hitl_choices 须注入既有 write_gate")
        from ming_sim.rescript_actions import row_is_applied_return_revise

        desk = [
            row for row in self.db.list_rescript_desk(int(self.state.turn))
            if not row_is_applied_return_revise(row)
        ]
        if desk or choices:
            return self.resolve_rescript_decisions(
                choices,
                write_gate=write_gate,
                cheat_directive=cheat_directive,
            )
        # 空 desk 且无 key：未消费 durable summon 仍走同一 resolver
        recovery = self._unconsumed_decided_summon_choices()
        if recovery:
            return self.resolve_rescript_decisions(
                recovery,
                write_gate=write_gate,
                cheat_directive=cheat_directive,
            )
        with write_gate:
            return self.submit_decisions(
                choices, cheat_directive=cheat_directive,
            )

    def submit_decisions(
        self, choices: List[Dict[str, object]], cheat_directive: str = ""
    ) -> str:
        """空 desk 续跑：复算既有 decided 行，零新增领域写。

        #657/#1589：本方法仅接受空 choices——旧 choices[idx] 位置补键/猜绑写协议
        已删；已裁批（含纯 decision/#1490）一律须经 resolve_rescript_decisions /
        submit_hitl_choices（keyed，调用方注入既有 write_gate），desk 空亦无例外。
        """
        self._assert_awaiting_decision_submit()
        if choices:
            raise ValueError(
                "submit_decisions 仅续跑空 choices；已裁批须经 submit_hitl_choices/"
                "resolve_rescript_decisions 显式携 decision_key"
            )
        if not (self.last_decree or "").strip():
            ctx0 = self.db.get_resolve_context(self.state.turn)
            if ctx0 is not None:
                self.last_decree = str(ctx0.get("decree_text") or "")
        before_turn = int(self.state.turn)
        report = resolve_decisions_phase2(
            self.state, self.db, self.agno_db, self.llm_config,
            content=self.content,
            cheat_directive=cheat_directive,
        )
        self.state.turn_phase = (
            TurnPhase.ISSUED.value
            if int(self.state.turn) != before_turn or self.state.ended
            else TurnPhase.SETTLING.value
        )
        self.db.save_state(self.state)
        return report

    def advance_without_decree(
        self, *, write_gate_already_held: bool = False,
    ):
        """CLI/web 退朝；无旨月亦走完整结算链（#1274 / owner B-2）。

        有草案/pending → 视同颁诏 resolve_turn。
        无草案 → allow_empty_decree，source=system_simulation，仍走玩家月链
        （邸报/种子局势/议题惯性/结局判定）；16ms 快路已废。
        """
        if self.db.list_directives(self.state, statuses=("pending", "draft")):
            return self.resolve_turn(
                write_gate_already_held=write_gate_already_held,
            )
        return self.resolve_turn(
            allow_empty_decree=True,
            write_gate_already_held=write_gate_already_held,
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

    def close(self, *, write_gate_already_held: bool = False) -> None:
        """排空本会话已受理工作，再关闭全部数据库资源。"""
        if write_gate_already_held:
            self._close_resources()
            return
        from ming_sim.session_write_queue import drain_and_close_session

        drain_and_close_session(self)

    def _close_resources(self) -> None:
        """关闭主库连接，并释放 agno SqliteDb 连接池（#1749）。

        主库与 agno 共路径；只关 GameDB 就归档/搬移文件时，agno 仍持 WAL 句柄，
        进程 fd 会钉在 drained_*.db 上，活局写路径可落到 readonly。

        次序：registry 材料目录 → scene → agno → db。仅由
        ``drain_and_close_session`` 在 SessionWriteQueue 已 seal、barrier 已排空且
        持 write_gate 时调用。材料清理失败不得阻断后续 agno/db 释放，但必须诚实上抛
        （ADR 0005，不得 ignore_errors 洗白）。agno 失败则立即上抛、不碰 db
        （两侧仍完整可恢复）。agno 已成功后 ``_close_epoch`` 递增——此后即使
        db.close 失败/conn 仍可探测，也不得恢复为活局（registry 已失 agno）。
        """
        materials_error: BaseException | None = None
        agno = getattr(self, "agno_db", None)
        if agno is not None:
            close_fn = getattr(agno, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except BaseException:
                    logger.exception("GameSession.agno_db.close failed")
                    raise
                self._close_epoch = int(getattr(self, "_close_epoch", 0) or 0) + 1
        try:
            self.db.close()
        except BaseException:
            logger.exception("GameSession.db.close failed")
            raise
        self._close_epoch = int(getattr(self, "_close_epoch", 0) or 0) + 1
        if materials_error is not None:
            raise materials_error
