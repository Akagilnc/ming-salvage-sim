"""GameSession：统一回合流转层。L8。

不含 input()/print()——只持有状态、跑底层逻辑、返回 dataclass。
召见对话的 tool 截获、拟旨 draft 流转、诏书结算都收在这里，
Web 只做 I/O 包装。
"""

from __future__ import annotations
from ming_sim.entities.character.store import CharacterStore
from ming_sim.exceptions import DeclarationDataError

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ming_sim.agents import bind_content as _bind_agents
from ming_sim.agents import _dump_llm_messages
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
    infer_office_type_from_office,
    normalize_office,
    resolve_office_type_preserving_title,
)
from ming_sim.applier import (
    Provenance,
    atomic,
    connection_owns_transaction,
    load_stored_list,
    load_stored_object,
    register_runtime_outcome_callbacks,
)
from ming_sim.decree import (
    ResolveResult,
    _provenance_from_stored,
    _requires_full_settlement,
    resolve_decisions_phase2,
    resolve_directives,
)
from ming_sim.issues import bind_content as _bind_issues
from ming_sim.entities.issue.legacy import sync_opening_legacies
from ming_sim.llm_model import create_agno_db
from ming_sim.models import Character, GameState, LLMConfig, is_vassal_prince, is_weishi
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
    # #1847 N16：只按当前 campaign 保留策略清理；不跨归属扫除旧命名存档。
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
                logger.exception(
                    "prune_auto_saves failed to remove %s", stale,
                )


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
class AudienceChatTurn:
    """#1902：一轮召对的入口无关句柄（建轮/快照/问话 id），两端入口共用同一生命周期。"""

    chat_turn_id: int
    accepted_turn: int
    night_id: int
    before_snapshot: Dict[str, Any]
    user_message_id: int


class AudienceChatUndoError(Exception):
    """撤回资格失败：结构化码供入口映射，不靠正文子串判别。"""

    def __init__(self, detail: str, *, code: str = "conflict") -> None:
        super().__init__(detail)
        self.detail = detail
        # code: conflict | not_found（入口映射 409 / 404）
        self.code = code


class PostReplyRecoveryError(Exception):
    """已落回话尾随恢复失败：结构化码供入口映射。"""

    def __init__(self, detail: str, *, code: str = "conflict") -> None:
        super().__init__(detail)
        self.detail = detail
        # code: conflict（入口映射 409）
        self.code = code


class TranslationRetryError(Exception):
    """指定源轮转译恢复失败：结构化码供入口映射 HTTP。"""

    def __init__(self, detail: str, *, code: str = "not_found") -> None:
        super().__init__(detail)
        self.detail = detail
        # code: invalid | not_found | settling
        self.code = code


class AudienceChatAdmissionError(Exception):
    """召对开轮/重试业务资格失败：结构化码供入口映射。"""

    def __init__(self, detail: str, *, code: str) -> None:
        super().__init__(detail)
        self.detail = detail
        # code: settling | night_closing | in_flight（已有拒绝理由，不新立）
        self.code = code


@dataclass(frozen=True)
class AudienceChatUndoResult:
    """撤回业务结果；呈现字段（history/directives 投影）由入口补。"""

    minister_name: str
    night_id: int
    undone_chat_turn_id: int
    campaign_id: str = ""


@dataclass
class ChatTurnResult:
    """场景召对一轮结果（#1902 T6：只保留现役产者字段）。

    旧入口（按大臣 chat / 分类器 / 拟旨当场落）曾产 appointed/registered/displaced/
    proposed_directive / secret_order_id / pending_action_* / 含糊准驳 / 密令 landing
    等字段；场景入口只产 answer + court_action（+ 转译暂存）。无产者字段与死消费者
    已清退，不复活旧产者。
    """
    answer: str
    court_action: str = ""   # "" | court_break（场景口令）；其余旧动作已随入口退役
    # #1842：ctid>0 时 scene_chat 只暂存转译参数；回话 persist 后由
    # schedule_pending_scene_translation 启动（ADR 0155 / 0036：回话落定后起）。
    pending_audience_translation: Optional[Dict[str, Any]] = None


@dataclass
class TurnSnapshot:
    year: int
    period: int
    turn: int
    phase: str


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

    受守面清单见 models.is_weishi / is_vassal_prince；can_summon（朝臣支）/
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
    （本函数 / settlement.dossier._commit_office_action / create_secret_order / apply_office_appointment 别名归一 /
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
    # #1847 N10：未知派系不得静默改写为「中立」（自由措辞→结构分类）。
    # 空缺才默认中立（只判空）；已声明非空值原样透传，不新增拒收护栏。
    faction_value = str(faction or "").strip() or "中立"
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
    # 仍须整项原子；外层 item_savepoint_scope / atomic 嵌套仍合法。commit 必须在
    # RELEASE 之后、且仅当本核拥有事务时发生——否则 SAVEPOINT 期内 commit 会把
    # 整个事务提前提交，随后 RELEASE 无点。
    owns_transaction = connection_owns_transaction(db.conn)
    savepoint = f"register_unlisted_{abs(id(character)) & 0xFFFFFFFF:x}"
    db.conn.execute(f"SAVEPOINT {savepoint}")
    try:
        db.add_character(
            state, character,
            source=str(source_label or ""),
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
    row = db.characters.read_register_unlisted_person_record((name,))
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
    row = CharacterStore(conn).read_sponsor_transferred((canonical,))
    if row is None or str(row["status"] or "") != "active":
        return False
    current = normalize_office(str(row["office"] or ""))
    if not current:
        return False
    desired_parts = {p for p in desired.split(",") if p}
    current_parts = {p for p in current.split(",") if p}
    return bool(desired_parts) and desired_parts.issubset(current_parts)


def canonical_new_appointment_person_fields(
    faction: object,
) -> Dict[str, object]:
    """Return the single canonical identity defaults for a newly appointed person.

    #1847 N10 同形：未知派系不得静默改写为「中立」；空缺才默认中立（只判空）。
    """
    normalized_faction = str(faction or "").strip() or "中立"
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

    person_fields = canonical_new_appointment_person_fields(data.get("faction"))
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
    row = db.characters.read_register_unlisted_person_record((name,))
    if row:
        character.portrait_id = str(row["portrait_id"])
    return (name, displaced)


def _sync_offices_from_db_impl(content: GameContent, db: "GameDB", llm_config: Optional[LLMConfig] = None) -> None:
    """启动/读档时以 DB characters 表重建内存人物表。
    DB 是持久化真相；不要在这里修写 DB。"""
    rows = db.characters.read_sync_offices_from_db_impl(())
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
        from ming_sim.db import _load_durable_str_list

        aliases = _load_durable_str_list(row["aliases"], surface="characters.aliases")
        personal_skills = _load_durable_str_list(
            row["personal_skills"], surface="characters.personal_skills",
        )
        from ming_sim.covert_progress import _parse_seed_guilt
        seed_guilt = _parse_seed_guilt(row["seed_guilt"])
        for guilt_key, guilt_value in seed_guilt.items():
            if not isinstance(guilt_value, str):
                raise ValueError(
                    f"characters.seed_guilt[{guilt_key!r}] 须为字符串，得 {type(guilt_value).__name__}"
                )
        characters[name] = Character(
            name=name,
            office=row["office"],
            office_type=office_type,
            faction=row["faction"],
            aliases=list(aliases),
            personal_skills=list(personal_skills),
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
            seed_guilt=dict(seed_guilt),
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
    """一局游戏的核心状态机。Web 与探针通过它驱动回合。"""

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
            fresh_save = not self.db.reign.exists()
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
                # 开局负面帝国修正：新档补全、旧档补缺、已达消除条件的不补/清残。不立 issue、不进推演。
                sync_opening_legacies(self.db, self.state)
            _t, _e = time.monotonic(), time.monotonic() - _t
            tlog(f"[载入] 3/4 状态载入 {_e:.1f}s")
            if seed_report:
                tlog(
                    "[载入] 关系 seed 导入："
                    f"{seed_report['events_imported']}/{seed_report['events_total']} 笔奠基边事件，"
                    f"{seed_report['summaries_written']} 份初始摘要"
                )
            tlog(f"[载入] 4/4 开局修正 {time.monotonic() - _t:.1f}s")
            self.deaths_this_turn: List[Dict[str, str]] = []
            self.debuts_this_turn: List[Dict[str, str]] = []
            self.previous_summary = ""
            self.last_decree = ""
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
        # awaiting_decision 必须保活：刷新页时仍要弹决策点续跑结算，不可重置成 summoning。
        # settling 同样保活（ADR 0008 S4）：pre_settle 前半段已提交，重载若被重置回 summoning，
        # 守门失效=恢复入口认不出「前半段已完成」会二次重跑前半段（白名单外即被重置）。
        if self.state.turn_phase not in (
            TurnPhase.SUMMONING.value, TurnPhase.REVIEWING.value,
            TurnPhase.AWAITING_DECISION.value, TurnPhase.SETTLING.value,
        ):
            self.state.turn_phase = TurnPhase.SUMMONING.value
            self.db.reign.save_game_state(self.state)
        return self.turn_snapshot()

    def current_phase(self) -> TurnPhase:
        return TurnPhase(self.state.turn_phase)

    def _set_phase(self, phase: TurnPhase) -> None:
        self.state.turn_phase = phase.value
        self.db.reign.save_game_state(self.state)

    def turn_snapshot(self) -> TurnSnapshot:
        return TurnSnapshot(
            year=self.state.year,
            period=self.state.period,
            turn=self.state.turn,
            phase=self.state.turn_phase,
        )

    def end_turn(self) -> None:
        """新回合建立（resolve 已推进 state.turn）；阶段回 summoning 并留月初档。"""
        self.state.turn_phase = TurnPhase.SUMMONING.value
        self.db.reign.save_game_state(self.state)
        self.auto_save("begin")

    def note_chat_rollback(self, deleted_committed_draft_ids: Optional[List[int]] = None) -> None:
        """P1-2：撤回召对若删了拟诏已 commit 的对话草案（committed draft），
        本份生成的诏书正文（last_decree）含被撤回的指令——必须作废，使颁诏须重生成，
        不能原样颁出。普通撤回（未删 committed draft）不动有效生成稿。"""
        if deleted_committed_draft_ids:
            self.last_decree = ""

    def refresh_runtime_after_chat_rollback(self) -> None:
        """撤回召对副作用后，用 DB 真相刷新内存人物表。"""
        self.state = self.db.load_state()
        _sync_offices_from_db_impl(self.content, self.db, self.llm_config)

    # ── 召见阶段 ──────────────────────────────────────────────────────────


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
        raise DeclarationDataError(f"人物未建档：{clean_name}")

    def can_summon(self, character: Character) -> Tuple[bool, str]:
        # 宗藩（就藩宗室）非朝堂命官，不可召见——与各 roster 同口径（PR#121 隐藏宗藩）。
        # can_summon 是 summon_minister 工具链（session + web 流式两路）的共用闸，
        # 集中守此一处即覆盖两路，否则裁判可绕列表按名召宗藩（cmr R4 cross-section）。
        if is_vassal_prince(character):
            return (False, f"{character.name}为就藩宗室，非朝廷命官，无法召见。")
        # 非大明势力（后金/蒙古/朝鲜/流寇）非朝廷命官，即便 active 也不可召见——皇帝召的是
        # 大明朝廷之臣，不召敌酋（皇太极等）。按 DB 权威 power_id 判：招抚归明者 DB 已翻 ming
        # 但内存仍旧势力，认 DB 才不会误拒归明者（#125；与 web_app 朝堂可见性同口径）。
        power_id = self.db.resolve_power_id(character)
        if power_id != "ming":
            return (False, f"{character.name}不属大明朝廷，无法召见。")
        status, reason = self.db.characters.get_character_status(character.name)
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
        # 朝臣可召：与 visible_in_court / CLI / 事实块同吃 _is_summonable_court_minister
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
        row = self.db.characters.read_admit_audience((character.name,))
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
        """同步识别明确退朝口令。纯封闭集匹配，无 Future/宽降级。"""
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
            # 交接后 barrier finally 唯一归还；本腿不再 complete 同一票。
            handed = barrier_ticket
            barrier_ticket = None
            q.barrier(_do_close, ticket=handed)
        finally:
            # 仅未交到 barrier 的早退路径归还预领票（未交接自还）。
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
            # 票一次性交给 close_night_after_chat_if_needed（早退自还或 barrier 归还）；
            # 调度侧不维护第二份归还。
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

    # ── 召对话轮生命周期（#1902：Web 与 CLI 入口共核，入口不再各编排一份）────────
    # 入口只做输入／呈现适配；建轮、快照、问话与回话落库、回滚与失败终态全在
    # 这里。两端曾各写一份同形编排（WebGame._start_chat_turn/_fail_chat_turn_and_reload
    # 与 cli/terminal.py 内联的同一段），那份副本随本方法落地删除。

    def reconcile_crashed_audience_turns(self) -> None:
        """启动／换库共核：崩溃遗留在飞回话终态化 + post_reply 恢复对账（ADR 0036）。

        #1902 T4：Web 建局／rebuild 与 CLI 起手／读档重建曾各抄同一两句；生命周期
        归本会话核，入口只在适当时机调用。宿主资源（写闸／呈现缓存）仍由入口适配。
        GameSession 恒持真实 GameDB；无 conn 壳旁路已清退。
        """
        self.db.reconcile_interrupted_chat_turns()
        self.db.reign.reconcile_post_reply_recovery()

    def list_startup_translation_catch_up(self) -> List[Any]:
        """启动恢复：是否仍有未承接转译的已持久回话（#1902 T4 共核取数）。

        无待补 → 正常空列表；直接走持久库契约，不经可选方法／缺 conn 壳。
        """
        return list(self.db.reign.list_unextracted_replies() or [])

    def run_startup_translation_catch_up(
        self, *,
        write_gate: Any = None,
        write_queue: Any = None,
    ) -> None:
        """启动恢复共核：补跑已持久回话的待承接转译（ADR 0036 / #1842）。

        #1902 T4：生命周期归会话核；Web 票据／后台线程、CLI 同步调用只是宿主适配。
        单轮模型失败由 catch_up 标待补、不锁档；查询／代码故障按 ADR 0005 上抛，
        不另加启动层非致命宽吞。
        """
        from ming_sim.audience_translation import catch_up_pending_translations

        if not self.list_startup_translation_catch_up():
            return
        catch_up_pending_translations(
            db=self.db,
            state=self.state,
            llm_config=getattr(self, "llm_config", None),
            write_gate=write_gate,
            write_queue=write_queue,
        )

    def scene_model_session_anchor(self, night_id: int) -> tuple[str, int]:
        """现役夜的模型会话身份与实际历史前像水位——生成／建轮／恢复唯一真源。

        #1902 SCENE-ANCHOR：入口不得自行拼名、独立取水位或无事实默认；
        真实夜确定后只由此核提供，与 ``_resolve_scene_agent`` 共用同一公式。
        """
        session_id = f"scene-night-{int(night_id)}"
        return session_id, int(self.db.reign.agno_runs_length(session_id))

    def assert_audience_chat_admission(self, *, what: str = "召对") -> None:
        """召对开轮/重试已有业务资格：月末相位、收夜冻结、本夜在飞未落。

        #1902：资格真源在会话共核；Web/CLI 入口只映射呈现，不各持业务副本。
        不添加新状态、新拒绝理由或资源机制——承接既有规则原文。
        """
        if getattr(self.state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
            raise AudienceChatAdmissionError(
                "月末结算/亲裁进行中，暂不能召对。",
                code="settling",
            )
        from ming_sim.audience_night import (
            AudienceNightError,
            assert_night_accepts_player_input,
            get_open_night,
        )
        try:
            assert_night_accepts_player_input(self.db, what=what)
        except AudienceNightError as err:
            code = str(getattr(err, "code", "") or "night_closing")
            raise AudienceChatAdmissionError(
                str(err) or f"本夜收夜中，暂不能{what}。",
                code=code,
            ) from err
        night = get_open_night(self.db)
        if night is None:
            return
        if self.db.reign.list_in_flight_chat_turns(night_id=int(night["id"])):
            raise AudienceChatAdmissionError(
                "本夜上一轮回奏仍在进行，请稍候再问。",
                code="in_flight",
            )

    def begin_audience_chat_turn(self, message: str) -> AudienceChatTurn:
        """建一轮召对：业务资格 → 确保开夜 → 建 chat_turn → 落问话。返回句柄供收口/回滚。

        建轮与问话归属均为 ``SCENE_CHAT_SPEAKER``「殿上」，与本夜历史读取一致。

        模型会话身份与前像水位由 ``scene_model_session_anchor`` 在真实夜确定后
        提供，入口不再传入。召见入殿由 ``scene_chat`` 认原口令落地，建轮不另
        开 ensure_summon 旁路。

        建轮、问话、问话关联在同一 ``atomic`` 里提交。关联写失败则整段回滚，
        不留下无所属的问话，也不留下仍占着本夜的半成品轮。
        """
        from ming_sim.applier import atomic
        from ming_sim.audience_night import (
            SCENE_CHAT_SPEAKER,
            get_open_night,
            open_night,
        )
        from ming_sim.decree_forecast import schedule_held_decree_forecasts

        # #1902：相位／收夜／在飞资格在共核；入口不得再持业务权威副本。
        GameSession.assert_audience_chat_admission(self, what="召对")
        owner = SCENE_CHAT_SPEAKER
        accepted_turn = int(self.state.turn)
        before_snapshot = self.db.capture_chat_rollback_snapshot()
        night_was_open = get_open_night(self.db) is not None
        night = get_open_night(self.db) or open_night(
            self.db, self.state,
        )
        if not night_was_open:
            schedule_held_decree_forecasts(self)
        night_id = int(night["id"])
        # 未绑定调用（与 begin 自身同形）：测试壳只持 db，不必自带锚点方法。
        agno_session_id, runs_before = GameSession.scene_model_session_anchor(
            self, night_id,
        )
        with atomic(self.db):
            chat_turn_id = self.db.create_chat_turn(
                self.state,
                owner,
                agno_session_id,
                runs_before,
                night_id=night_id,
                status="generating",
            )
            user_message_id = self.db.chat_messages.insert(minister_name=owner, turn=accepted_turn, role='user', content=message)
            if chat_turn_id:
                self.db.reign.update_chat_turn_messages(
                    chat_turn_id, user_message_id=user_message_id,
                )
        return AudienceChatTurn(
            chat_turn_id=int(chat_turn_id or 0),
            accepted_turn=accepted_turn,
            night_id=night_id,
            before_snapshot=before_snapshot,
            user_message_id=int(user_message_id or 0),
        )

    def complete_audience_chat_turn(
        self, turn: AudienceChatTurn, message_speaker: str, reply: str,
    ) -> int:
        """回话落定：persist 回话与回滚差异同一事务。回传回话消息 id。

        ``message_speaker`` 是 chat_messages 的归属；chat_turn 靠 turn 句柄定位，
        不按名字反查，恢复时保留原回话归属。

        落回话与记回滚差异在同一个 ``atomic`` 里提交。差异写失败则回话一并回滚，
        轮仍停在 generating、没有 minister_message_id，既有 ``fail_audience_chat_turn``
        才能标 interrupted。已提交的回话不在失败收口里删。
        转译由 Web 在闸外、挂票后安排，落库与回滚差异只走这一条路。
        Web 外层若已持有 ``atomic``，这里的内层是扁平嵌套，由外层提交。

        生产消费者均持真实持久轮；未建轮取消的合法 no-op 属于
        ``fail_audience_chat_turn``，本方法不设零轮早退旁路。
        """
        from ming_sim.applier import atomic

        with atomic(self.db):
            minister_message_id = int(self.db.persist_minister_reply(
                message_speaker, turn.accepted_turn, reply, turn.chat_turn_id,
            ) or 0)
            self.db.record_chat_turn_rollback_diffs(
                turn.chat_turn_id, turn.before_snapshot,
                self.db.capture_chat_rollback_snapshot(),
            )
        return minister_message_id

    def _hall_turn_ids_for_night(self, night_id: Optional[int] = None) -> "set[int]":
        """殿上轮 id 集——中断回话与尾随失败共用的夜域筛选单源（#1902 M1）。

        night_id 缺省＝当前开夜；显式 night_id 供 scroll 历史夜读面复用同一筛选，
        不在 Web 另写一份资格查询。
        """
        from ming_sim.audience_night import get_open_night

        nid = int(night_id) if night_id is not None and int(night_id) > 0 else 0
        if nid <= 0:
            night = get_open_night(self.db)
            if night is None:
                return set()
            nid = int(night["id"])
        return {
            int(row["id"]) for row in self.db.reign.list_hall_chat_turns(nid)
        }

    def pending_audience_reply_retries(
        self, *, night_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """本夜召对轮里待重试的中断回话（问话已落、回话未落）——两端共核取数。

        #1902 F2：建轮归属恒为「殿上」（见 begin_audience_chat_turn 的 T1 说明），
        而问话/回话挂被召大臣名。此前 CLI 拿大臣名去查 ``get_interrupted_reply_retries``
        ——按 ``chat_turns.minister_name`` 过滤永远查不到殿上建的轮，实际中断问话
        不可重试（探针：hall 1 / selected_minister 0）。

        取数与归属判定的落差只此一处：按建轮归属在本夜轮里取，并给回话带回原问话的
        归属（``message_speaker``），供重试时把回话挂回同一位大臣。入口只读。
        """
        from ming_sim.audience_night import SCENE_CHAT_SPEAKER

        hall_ids = self._hall_turn_ids_for_night(night_id)
        if not hall_ids:
            return []
        retries = [
            row for row in self.db.reign.get_interrupted_reply_retries(SCENE_CHAT_SPEAKER)
            if int(row["chat_turn_id"]) in hall_ids
        ]
        out: List[Dict[str, Any]] = []
        for row in retries:
            item = dict(row)
            item["message_speaker"] = self._chat_message_speaker(
                int(row.get("user_message_id") or 0),
            ) or SCENE_CHAT_SPEAKER
            out.append(item)
        return sorted(out, key=lambda item: int(item["chat_turn_id"]))

    def pending_post_reply_retries(
        self, *, night_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """本夜殿上已落回话的尾随失败——两端共核取数（#1902 L1）。

        与 ``pending_audience_reply_retries`` 同形：共用 ``_hall_turn_ids_for_night``
        夜域筛选；状态源仍是 ``get_post_reply_retries``，不与中断回话合并语义。
        """
        from ming_sim.audience_night import SCENE_CHAT_SPEAKER

        hall_ids = self._hall_turn_ids_for_night(night_id)
        if not hall_ids:
            return []
        return sorted(
            [
                dict(row)
                for row in self.db.reign.get_post_reply_retries(SCENE_CHAT_SPEAKER)
                if int(row["chat_turn_id"]) in hall_ids
            ],
            key=lambda item: int(item["chat_turn_id"]),
        )

    def pending_audience_recovery_retries(
        self, *, night_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """中断回话 + 已落回话尾随失败，本夜共核合并取数（#1902 L1）。

        Web 恢复面板／scroll 读此；CLI「重试回话」仍只读 ``pending_audience_reply_retries``
        （不新增 CLI 尾随玩法）。night_id 显式传入时筛该夜，缺省＝开夜。
        """
        return sorted(
            [
                *self.pending_audience_reply_retries(night_id=night_id),
                *self.pending_post_reply_retries(night_id=night_id),
            ],
            key=lambda item: int(item["chat_turn_id"]),
        )

    def list_pending_translation_retries(
        self,
        *,
        night_id: Optional[int] = None,
        chat_turn_id: Optional[int] = None,
        write_queue: Any = None,
    ) -> List[Dict[str, Any]]:
        """转译待补投影；真源 audience_translation.list_pending_translations。

        无待补 → 正常空列表；直接引用真实库，不经缺 conn 壳。
        """
        from ming_sim.audience_translation import list_pending_translations

        return list_pending_translations(
            self.db, night_id=night_id, chat_turn_id=chat_turn_id,
            write_queue=write_queue,
        )

    def retry_pending_translation(
        self,
        chat_turn_id: int,
        *,
        write_gate: Any = None,
        write_queue: Any = None,
    ) -> Dict[str, Any]:
        """指定源轮转译恢复共核（#1902 M1）：待补资格 → 相位准入 → catch_up → 水位。

        入口只做 HTTP／票据／写闸／呈现映射；不在 Web 自办恢复编排。
        """
        ctid = int(chat_turn_id or 0)
        if ctid <= 0:
            raise TranslationRetryError("chat_turn_id 无效", code="invalid")
        from ming_sim.audience_translation import catch_up_pending_translations

        pending_before = self.list_pending_translation_retries(
            chat_turn_id=ctid, write_queue=write_queue,
        )
        if not pending_before:
            raise TranslationRetryError(
                f"chat_turn_id={ctid} 没有待补转译。", code="not_found",
            )
        if self.state.turn_phase in FRONT_HALF_DONE_PHASES:
            raise TranslationRetryError(
                "月末结算/亲裁进行中，暂不能召对。", code="settling",
            )
        summary = catch_up_pending_translations(
            self.db, self.state,
            chat_turn_id=ctid,
            llm_config=getattr(self, "llm_config", None),
            write_gate=write_gate,
            write_queue=write_queue,
        )
        still = self.list_pending_translation_retries(
            chat_turn_id=ctid, write_queue=write_queue,
        )
        status = self.db.reign.get_story_extract_status(ctid)
        return {
            "chat_turn_id": ctid,
            "extract_status": status,
            "retryable": bool(still),
            "kind": "translation_pending" if still else "translation_done",
            "summary": summary,
        }

    def resume_post_reply_recovery(
        self,
        target: Dict[str, Any],
        *,
        write_gate: Any = None,
        after_reply: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """已落回话尾随恢复共核（#1902 L1）：claim → 相位编排 → clear；失败 release。

        ``court_break`` → ``close_night_after_chat_if_needed``。
        ``after_reply`` → 入口呈现钩（高亮等），共核不持呈现／票据。
        ``write_gate`` 为宿主短写闸；未传则无闸上下文。
        claim 未赢 → ``PostReplyRecoveryError(conflict)``，入口映射 409。
        """
        import contextlib

        chat_turn_id = int(target["chat_turn_id"])
        phase = str(target.get("recovery_phase") or "")
        gate_cm = write_gate if write_gate is not None else contextlib.nullcontext()
        with gate_cm:
            if not self.db.reign.claim_post_reply_recovery(chat_turn_id, phase):
                raise PostReplyRecoveryError(
                    "本轮后续处理已在恢复，请稍候。", code="conflict",
                )
        try:
            if phase == "court_break":
                self.close_night_after_chat_if_needed(
                    "court_break", write_gate=write_gate,
                )
            elif after_reply is not None:
                after_reply(target)
            with gate_cm:
                self.db.reign.clear_post_reply_failure(chat_turn_id)
        except BaseException:
            with gate_cm:
                self.db.reign.release_post_reply_recovery(chat_turn_id, phase)
            raise
        return {
            "answer": str(target.get("answer") or ""),
            "chat_turn_id": chat_turn_id,
        }

    def _chat_message_speaker(self, message_id: int) -> str:
        """chat_messages 某行的归属大臣名；无此行时返回空串。"""
        if not message_id:
            return ""
        row = self.db.chat_messages.read_chat_message_speaker(
            (int(message_id),)
        )
        return str(row["minister_name"] or "") if row else ""

    def fail_audience_chat_turn(
        self, turn: AudienceChatTurn, *, replied: bool = False,
        error: Optional[BaseException] = None,
        translation_dispatched: bool = False,
        court_action: str = "",
    ) -> bool:
        """召对失败收口。已提交的回话不删、不回滚。

        账上 ``active`` 且已挂 ``minister_message_id`` = 回话已提交。此时：
        转译尚未派出且抽取未完成 → 既有 ``extract_status=pending`` 与 translation
        错误包；否则既有 ``post_reply_recovery``（``court_break`` / ``after_reply``）。
        ``replied`` 表示调用方已有回话对象。对象在、账上无回话（落库事务回滚）
        与对象尚未产生，都走未完成收口：记回滚差异，问话留下并标 interrupted。
        账上已有回话而调用方还没拿到 payload（调度在返回前抛）同样不得回滚。

        返回是否按已落回话记下了恢复相位。
        """
        from ming_sim.decree_forecast import schedule_restored_decree_forecasts
        from ming_sim.exceptions import LLMUnavailable

        if not turn.chat_turn_id:
            return False
        row = self.db.reign.read_fail_audience_chat_turn(
            (turn.chat_turn_id,)
        )
        reply_landed = bool(
            row is not None
            and row["status"] == "active"
            and row["minister_message_id"]
        )
        # 账上已落优先于 ``replied``。调用方看见对象但事务未提交时 replied 为真、
        # reply_landed 为假，落入下面的未完成收口，不假装已落。
        if reply_landed:
            return self._record_persisted_audience_reply_failure(
                turn, row, error,
                translation_dispatched=translation_dispatched,
                court_action=court_action,
            )
        # 回滚真源：capture → record diffs → restore。快照／宿主故障须原错上抛，
        # 不 catch 洗白、不伪造 before==after、不谎称已安全收口（#1902 T4）。
        self.db.record_chat_turn_rollback_diffs(
            turn.chat_turn_id, turn.before_snapshot,
            self.db.capture_chat_rollback_snapshot(),
        )
        if not turn.user_message_id:
            user_row = self.db.reign.chat_turn_user_message_id(
                turn.chat_turn_id
            )
            turn.user_message_id = int(user_row["user_message_id"] or 0) if user_row else 0
        if turn.user_message_id:
            restored_ids = self.db.restore_interrupted_after_failed_retry(turn.chat_turn_id)
            schedule_restored_decree_forecasts(self, restored_ids)
            if error is not None and not isinstance(error, LLMUnavailable):
                from ming_sim.audience_night import write_audience_error_pack
                pack = write_audience_error_pack(
                    kind="reply", message=str(error),
                    detail={"chat_turn_id": turn.chat_turn_id}, db=self.db, exc=error,
                )
                self.db.reign.set_chat_turn_error_pack(turn.chat_turn_id, pack)
        else:
            restored_ids = self.db.fail_chat_turn(turn.chat_turn_id)
            schedule_restored_decree_forecasts(self, restored_ids)
        return False

    def _record_persisted_audience_reply_failure(
        self, turn: AudienceChatTurn, row, error: Optional[BaseException], *,
        translation_dispatched: bool, court_action: str,
    ) -> bool:
        """已落回话的失败相位。不新增恢复列，不删已提交的回话。"""
        from ming_sim.audience_night import write_audience_error_pack

        translation_pending = (
            not translation_dispatched
            and str(row["extract_status"] or "") != "done"
        )
        detail = {"chat_turn_id": turn.chat_turn_id, "phase": "post_reply"}
        if translation_pending:
            self.db.reign.mark_story_extraction_pending(turn.chat_turn_id)
            if error is not None:
                pack = write_audience_error_pack(
                    kind="translation", message=str(error), detail=detail,
                    db=self.db, exc=error,
                )
                self.db.reign.set_chat_turn_error_pack(turn.chat_turn_id, pack)
            return True
        pack = ""
        if error is not None:
            pack = write_audience_error_pack(
                kind="reply", message=str(error), detail=detail,
                db=self.db, exc=error,
            )
        phase = "court_break" if court_action == "court_break" else "after_reply"
        self.db.reign.mark_post_reply_failure(turn.chat_turn_id, phase, pack)
        return True

    def can_undo_last_audience_chat(self, minister_name: str) -> bool:
        """撤回资格共核（#1902 J3）：相位 + 全局末轮完整回话。入口只读。

        #1902 K1：建轮归属恒为「殿上」（或具名大臣个人轮）；不按旧跨身份 owner 转交。
        """
        if self.state.turn_phase not in (
            TurnPhase.SUMMONING.value, TurnPhase.REVIEWING.value,
        ):
            return False
        return self.db.can_undo_last_chat_turn(minister_name, self.state.turn)

    def undo_last_audience_chat(
        self,
        minister_name: str,
        *,
        gate_held: bool = False,
        write_queue: Any = None,
    ) -> AudienceChatUndoResult:
        """撤回最近一轮完整召对的业务编排共核（#1902 J3 / #1816）。

        资格判定、取消在飞票据／转译、DB 逆转、作废旧草案、重排恢复预推、
        刷新运行时均在此。入口只做 HTTP 异常映射与呈现投影。
        不新增取消机制或领域规则；复用既有 write_queue / translation / DB 原语。

        #1902 K1：殿上轮读写契约固定 minister_name=「殿上」；删除不可达的
        旧 owner 跨身份转交／递归兼容分支。
        """
        from ming_sim.audience_night import get_open_night
        from ming_sim.audience_translation import cancel_turn_translation
        from ming_sim.session_write_queue import get_session_write_queue

        target = str(minister_name or "").strip()
        if self.state.turn_phase not in (
            TurnPhase.SUMMONING.value, TurnPhase.REVIEWING.value,
        ):
            raise AudienceChatUndoError(
                "本回合已经进入颁诏结算，不能撤回召对。", code="conflict",
            )
        row = self.db.reign.get_last_active_chat_turn(target, self.state.turn)
        if row is None:
            raise AudienceChatUndoError(
                "本回合没有可撤回的召对。", code="not_found",
            )
        if not self.db.reign.is_global_last_active_chat_turn(int(row["id"])):
            raise AudienceChatUndoError(
                "只能撤回全局最后一轮召对。", code="conflict",
            )
        if not row.get("user_message_id") or not row.get("minister_message_id"):
            raise AudienceChatUndoError(
                "该召对尚未完整完成，不能撤回。", code="conflict",
            )

        queue = write_queue if write_queue is not None else get_session_write_queue(self)
        turn_id = int(row["id"])
        # #1353 / ADR 0038：撤回轮取消其在飞票据（空放行、不复活写库）。
        # #1842 / ADR 0155：同步终结该轮在飞转译 Future。
        queue.cancel_key(("turn", turn_id))
        cancel_turn_translation(
            turn_id, write_queue=queue, gate_held=gate_held,
        )
        try:
            undone = self.db.undo_chat_turn(turn_id)
        except ValueError as exc:
            raise AudienceChatUndoError(str(exc), code="conflict") from exc

        self.note_chat_rollback(
            deleted_committed_draft_ids=undone.get("deleted_committed_draft_ids"),
        )
        restored_ids = [
            int(item) for item in (undone.get("restored_pending_action_ids") or [])
        ]
        if restored_ids:
            from ming_sim.decree_forecast import (
                bind_forecast_owner, schedule_pending_decree_forecast,
            )
            bind_forecast_owner(self)
            open_night_row = get_open_night(self.db)
            if open_night_row is not None:
                for pending_id in restored_ids:
                    schedule_pending_decree_forecast(
                        self, pending_id, night_id=int(open_night_row["id"]),
                    )
        self.refresh_runtime_after_chat_rollback()
        campaign_id = str(self.db.reign.kv_get("campaign_id") or "")
        return AudienceChatUndoResult(
            minister_name=target,
            night_id=int(row.get("night_id") or 0),
            undone_chat_turn_id=int(undone["id"]),
            campaign_id=campaign_id,
        )

    def execute_interrupted_reply_retry(
        self,
        *,
        chat_turn_id: int,
        question: str,
        message_speaker: str,
        accepted_turn: int,
        user_message_id: int = 0,
        stream_emit: Optional[Callable[..., None]] = None,
        write_gate: Any = None,
    ) -> Optional[Tuple[AudienceChatTurn, "ChatTurnResult", int]]:
        """中断回话恢复共核：reopen CAS → 快照 → scene_chat → 落回话／失败收口。

        #1902 T4：Web 入口只做输入、呈现与宿主资源适配，生命周期编排只此一处。
        reopen CAS 未赢 → 返回 ``None``（沿用 ``reopen_interrupted_chat_turn_for_retry``
        的 False 语义；入口译成 409／提示；未进 generating）。不借用 LookupError——
        KeyError／IndexError 亦为其子类，scene／snapshot／落库可抛，不得当 CAS 未赢。
        reopen 已赢后的任何失败（含快照）→ ``fail_audience_chat_turn`` 后原错上抛，
        不遗留 generating。
        成功返回 ``(turn, result, minister_message_id)``；转译由入口在闸外挂票后安排，
        收夜须先放行 pending write，再调 ``schedule_close_night_after_chat_if_needed``。
        ``write_gate`` 可选：宿主短写闸（reopen／落库／失败收口）；LLM 生成在闸外。
        """
        import contextlib

        gate_cm = write_gate if write_gate is not None else contextlib.nullcontext()
        turn: Optional[AudienceChatTurn] = None
        result: Optional[ChatTurnResult] = None
        with gate_cm:
            # #1902：与建轮同核资格（相位／收夜／在飞）；CAS 前拒绝，不留 generating。
            GameSession.assert_audience_chat_admission(self, what="召对")
            if not self.db.reign.reopen_interrupted_chat_turn_for_retry(chat_turn_id):
                return None
            # reopen 已赢即建 turn 句柄，保证后续任意失败（含快照）能走 fail 收口。
            turn = AudienceChatTurn(
                chat_turn_id=int(chat_turn_id),
                accepted_turn=int(accepted_turn),
                night_id=0,
                before_snapshot={},
                user_message_id=int(user_message_id or 0),
            )
        try:
            with gate_cm:
                turn.before_snapshot = self.db.capture_chat_rollback_snapshot()
            result = self.scene_chat(
                question,
                chat_turn_id=chat_turn_id,
                stream_emit=stream_emit,
            )
            with gate_cm:
                minister_message_id = self.complete_audience_chat_turn(
                    turn,
                    message_speaker,
                    str(getattr(result, "answer", "") or ""),
                )
            return turn, result, int(minister_message_id or 0)
        except Exception as exc:
            if turn is not None:
                try:
                    with gate_cm:
                        self.fail_audience_chat_turn(
                            turn,
                            replied=result is not None,
                            error=exc,
                            court_action=str(getattr(result, "court_action", "") or ""),
                        )
                except Exception:
                    logger.exception(
                        "interrupted reply retry fail_audience_chat_turn failed chat_turn_id=%s",
                        chat_turn_id,
                    )
            raise

    def scene_chat(
        self, message: str, *, chat_turn_id: int = 0,
        stream_emit: Any = None,
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
            CMD_NONE,
            SCENE_CHAT_SPEAKER,
            ensure_summon_enter,
            get_open_night,
            open_night,
            recognize_xuan_command,
        )
        from ming_sim.llm_model import extract_agent_text

        # Free emperor prose: empty-check without mutating carried body (P6).
        message_text = str(message or "")
        if not message_text.strip():
            raise ValueError("问话不能为空。")
        from ming_sim.decree_forecast import bind_forecast_owner
        bind_forecast_owner(self)

        # 开夜（若需）；一夜一场不绑单人 minister 入口。
        night = get_open_night(self.db)
        opened_new_night = night is None
        if opened_new_night:
            night = open_night(self.db, self.state)
            from ming_sim.decree_forecast import schedule_held_decree_forecasts
            schedule_held_decree_forecasts(self)
        night_id = int(night["id"])

        result = ChatTurnResult(answer="")
        if self._recognize_audience_command_verdict(message_text) == CMD_CLOSE_NIGHT:
            ctid = int(chat_turn_id or 0)
            # 生产：退朝只标 court_break，由 epilogue／schedule_close_night 收夜。
            # 零轮当场 close_night 旁路已清退（注释曾称已删、代码残留）。
            if ctid > 0:
                self._mark_control_turn_translation_done(ctid)
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
                        self.db, night_id, target.name,
                    )
                    xuan_ctid = int(chat_turn_id or 0)
                    if xuan_ctid > 0:
                        self.db.reign.set_chat_turn_protagonist(
                            xuan_ctid, target.name
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
        """生产 create_scene_agent；测试经 monkeypatch 此工厂缝注入，禁实例双桩属性。

        session_id 与建轮／恢复同一 ``scene_model_session_anchor`` 事实。
        """
        llm_config = getattr(self, "llm_config", None)
        session_id, _runs_before = GameSession.scene_model_session_anchor(
            self, night_id,
        )
        return create_scene_agent(
            llm_config,
            prepared,
            agno_db=getattr(self, "agno_db", None),
            content=getattr(self, "content", None),
            session_id=session_id,
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

        from ming_sim.llm_model import extract_agent_text
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
            # #1902 T2：无 RunOutput 时仍以已拼正文为准；不从词面判认证故障。
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
                    self.db.reign.truncate_chat_turn_agno_runs(int(chat_turn_id))
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
        # 说话人是源轮上已落的结构化身份。空串会把查访/进展闸当成殿上整场放行。
        minister_name = ""
        if hasattr(self.db, "conn"):
            row = self.db.reign.read_apply_scene_turn_translation(
                (ctid,)
            )
            if row is not None:
                minister_name = str(row["minister_name"] or "")
        result.pending_audience_translation = {
            "emperor_message": emperor_message,
            "reply": reply,
            "night_id": int(night_id or 0),
            "chat_turn_id": ctid,
            "minister_name": minister_name,
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
        rows = self.db.issues.list_directives(self.state.turn, statuses=statuses)
        return [
            DirectiveView(
                id=int(r["id"]), text=str(r["text"]), status=str(r["status"]),
                source=str(r["source"] or ""), notes=str(r["notes"] or ""),
                actor=str(r["actor"] or ""),
            )
            for r in rows
            if self.db.dossiers.get_for_directive(int(r["id"])) is None
        ]

    @staticmethod
    def _proposal_blocked(state) -> bool:
        """FRONT_HALF_DONE 时 chat 提案不得插 pending directive（ship-pre r2 软死锁环源头）：
        pending>0 让推进口全拒「请准/驳」而 confirm/reject 已冻结=互相指对方死锁且落盘。
        正常入 settling 时 pending 必为 0（resolve 口有门），源头堵死即环断。"""
        return state.turn_phase in FRONT_HALF_DONE_PHASES

    def _refuse_if_settling(self) -> None:
        """Freeze decree changes once the month's front half has committed."""
        if self.state.turn_phase in FRONT_HALF_DONE_PHASES:
            raise DeclarationDataError("月末结算进行中（恢复态），请先完成结算再改诏稿。")

    # #1902：add_directive / update_directive 随拟诏台手写入口（CLI add/edit、
    # Web POST|PATCH /api/directives）一并退役——旨意只从召对来（#1772）。
    # 落库与改稿的引擎面仍是 db.issues.add_directive / db.update_directive_text；
    # 共享抽取核（成案准入补交）未动。

    def delete_directive(self, directive_id: int) -> None:
        self._refuse_if_settling()
        self.db.delete_directive(directive_id)

    def pending_count(self) -> int:
        """未核定 turn_directives + staged 政务候选（#1376/#1380 投影可见性）。

        计入 pending_actions 中 directive/office/secret_order（#1380 语义洞：
        拟旨/任免 staged 时不得假 0）。确认闸门/落库时序不动。
        """
        n = self.db.issues.count_pending_directives_for_turn(self.state.turn)
        pending_actions = self.db.dossiers.list_pending_actions(self.state.turn)
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
        from ming_sim.draft_intent import resubmit_draft_admission_payload
        from ming_sim.error_pack import settlement_abort_message, write_error_pack
        from ming_sim.exceptions import SettlementAbort

        carried = dict(carry_over or {})
        jobs: List[Dict[str, object]] = []
        for item in rejections or []:
            did = int(item.get("directive_id"))
            if self.db.dossiers.get_for_directive(did) is not None:
                continue
            row = self.db.issues.directive(did)
            if row is None or str(row["status"] or "") != "draft":
                continue
            bad_payload = self.db.issues.read_directive_dossier_payload(row)
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

        # DB 相串行：仅既有领域契约异常耗尽；未识别异常错误包中止（#1897 E1）。
        from ming_sim.action_materialize import is_declaration_domain_error

        next_carry: Dict[int, Dict[str, object]] = {}
        for job, new_payload, exc in outcomes:
            did = int(job["directive_id"])
            if exc is not None:
                if isinstance(exc, DeclarationDataError):
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
                    self.db, self.state, exc=exc,
                )
                raise SettlementAbort(
                    settlement_abort_message(pack_path, reason=str(exc)),
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
            except Exception as write_exc:
                if is_declaration_domain_error(write_exc):
                    logger.warning(
                        "[1769] draft#%s admission resubmit write-back rejected: %s",
                        did, write_exc,
                    )
                    next_carry[did] = {
                        "bad_payload": dict(new_payload),
                        "reason": str(write_exc),
                    }
                    continue
                pack_path = write_error_pack(
                    self.db, self.state, exc=write_exc,
                )
                raise SettlementAbort(
                    settlement_abort_message(pack_path, reason=str(write_exc)),
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
            from ming_sim.decree_forecast import failed_decree_forecast
            forecast_failure = failed_decree_forecast(self)
            if forecast_failure is not None:
                raise SettlementAbort(
                    str(forecast_failure["message"]), turn=int(self.state.turn),
                    stage=str(forecast_failure["step"]),
                    error_pack_path=forecast_failure.get("error_pack_path"),
                )
            # 票的完成只表示本次 worker 已终止，不代表机械尾已终结。
            # 屏障等完票后复查持久状态；非耗尽异常留下 pending 时不能过月。
            from ming_sim.mechanical_tail import _pending_mechanical_tails
            from ming_sim.mechanical_tail import failed_mechanical_tail
            failure = failed_mechanical_tail(self.db)
            pending_tails = _pending_mechanical_tails(self.db)
            if failure or pending_tails:
                exc = RuntimeError(
                    str(failure[1]["error"]) if failure else
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
                        )
                raise SettlementAbort(
                    settlement_abort_message(pack_path, reason=str(exc)),
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
                    self.db, self.state, exc=exc,
                )
                raise SettlementAbort(
                    settlement_abort_message(pack_path, reason=str(exc)),
                    turn=int(self.state.turn),
                    stage="audience_translation_exhausted",
                    error_pack_path=pack_path,
                ) from exc
            from ming_sim.audience_night import commit_late_night_approved
            commit_late_night_approved(
                self.db, self.state,
                content=getattr(self, "content", None),
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
            self.db.issues.list_directives(self.state.turn, statuses=('pending',))
            or any(
                row.get("kind") == "directive"
                for row in self.db.dossiers.list_pending_actions(self.state.turn)
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
            ctx = self.db.resolve_contexts.get(self.state.turn)
            if ctx is not None:
                recovered_source = _provenance_from_stored(ctx.get("source"))
                # Free decree body on settle recovery: carry stored 旨文 as-is (P6).
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
        for pending in self.db.issues.list_directives(self.state.turn, statuses=('pending',)):
            self.db.confirm_directive(int(pending["id"]))
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
        dossiered_directives = self.db.issues.list_dossiered_draft_directives(self.state.turn)
        # DB owner supplies the canonical read-only default-approval projection.
        # Negative preview ids stay distinct from durable turn_directives ids.
        pending_directives = self.db.preview_pending_directives(
            self.state, content=getattr(self, "content", None),
        )
        directives = list(dossiered_directives)
        directives.extend(pending_directives)
        if pending_directives and recovered_source is None and (decree or "").strip():
            # 显式 decree 早于 durable 候选；清空以免把未入档旨当已颁。
            decree = ""
            self.last_decree = ""
        settlement_due = _requires_full_settlement(self.state, self.db)
        # Pending non-directive actions (secret orders etc.) enter resolve_directives
        # so pre_settle owns materialization with the rest of the settlement spine.
        pending_action_due = bool(self.db.dossiers.list_pending_actions(self.state.turn))
        # #1769 耗尽：产物错 draft 留到下月；不得把引擎拒因串透传给皇帝，不得挡月份。
        product_exhaust = bool(dossier_rejections)
        # #1769 零成案耗尽与退朝无旨同形：不把 last_decree/显式 decree 当本月已颁。
        if product_exhaust and not dossiered_directives:
            decree = ""
            self.last_decree = ""
        if not directives and not settlement_due and not pending_action_due:
            if (self.state.turn_phase in FRONT_HALF_DONE_PHASES
                    and (self.last_decree or "").strip()):
                directives = [{"text": self.last_decree}]
            elif not (allow_empty_decree or recovered_source is not None or product_exhaust):
                raise ValueError("网页/CLI 端不允许跳过回合：至少一条草案才能颁诏。")
        # 结算前先存一份：LLM 推演有可能崩，留个回滚锚点
        self.auto_save("preresolve")
        # #1816/#1812：旧合并诏文 LLM 前置已撤；decree_text 仅显式/恢复存稿，不另造生成器。
        decree_text = decree or self.last_decree or ""
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
            self.state, self.db, self.agno_db, self.llm_config, decree_text,
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
            self.db.reign.save_game_state(self.state)
        else:
            from ming_sim.session_write_queue import get_session_write_queue
            with get_session_write_queue(self).write_gate:
                self.db.reign.save_game_state(self.state)
        return result

    def pending_decisions(self) -> List[Dict[str, object]]:
        return self.db.issues.list_rescript_desk(int(self.state.turn))

    def deferred_rescripts(self) -> List[Dict[str, object]]:
        """Original returned memorials, including months with vacant offices."""
        return self.db.issues.list_rescript_drafts(status="revision_pending")

    def _assert_awaiting_decision_submit(self) -> None:
        if self.current_phase() != TurnPhase.AWAITING_DECISION:
            raise DeclarationDataError("当前不在待裁决策阶段，无法提交亲裁。")

    def submit_hitl_choices(
        self, choices: List[Dict[str, object]], *, write_gate: Any,
        cheat_directive: str = "",
    ) -> str:
        """Record raw answers in a short transaction, then resume the same month run."""
        from ming_sim.rescript_actions import persist_answers
        if write_gate is None:
            raise ValueError("submit_hitl_choices 须注入既有 write_gate")
        self._assert_awaiting_decision_submit()
        with write_gate:
            persist_answers(self.db, self.state, choices, content=self.content)
        before_turn = int(self.state.turn)
        try:
            report = resolve_decisions_phase2(
                self.state, self.db, self.agno_db, self.llm_config,
                content=self.content, cheat_directive=cheat_directive,
            )
        except Exception:
            from ming_sim.month_chain import month_chain_call_failure
            self.state.turn_phase = (
                TurnPhase.SETTLING.value if month_chain_call_failure(self.db, before_turn)
                else TurnPhase.AWAITING_DECISION.value
            )
            with write_gate:
                self.db.reign.save_game_state(self.state)
            raise
        self.state.turn_phase = (
            TurnPhase.ISSUED.value
            if int(self.state.turn) != before_turn or self.state.ended
            else TurnPhase.AWAITING_DECISION.value if self.pending_decisions()
            else TurnPhase.SETTLING.value
        )
        with write_gate:
            self.db.reign.save_game_state(self.state)
        return report

    def advance_without_decree(
        self, *, write_gate_already_held: bool = False,
    ):
        """CLI/web 退朝；无旨月亦走完整结算链（#1274 / owner B-2）。

        有草案/pending → 视同颁诏 resolve_turn。
        无草案 → allow_empty_decree，source=system_simulation，仍走玩家月链
        （邸报/种子局势/议题惯性/结局判定）；16ms 快路已废。
        """
        if self.db.issues.list_directives(self.state.turn, statuses=("pending", "draft")):
            return self.resolve_turn(
                write_gate_already_held=write_gate_already_held,
            )
        return self.resolve_turn(
            allow_empty_decree=True,
            write_gate_already_held=write_gate_already_held,
        )

    def victory(self) -> Dict[str, object]:
        return victory_status(self.db)

    def auto_save(self, tag: str) -> str:
        """每回合 begin/end 自动热备一份。每个 campaign 保留最近 AUTO_SAVE_KEEP_TURNS 个回合，旧的删。
        文件名 auto_<campaign_id>_<year>_<period>_<turn>_<tag>.db；prune 只动同 campaign 的自动档，
        不碰用户手动存档。备份失败原样交出，不伪装成已经存档。"""
        import os as _os
        saves_dir = user_data_path("saves", "_keep")  # 确保父目录建好
        saves_dir = _os.path.dirname(saves_dir)
        campaign_id = (self.db.reign.kv_get("campaign_id") or "").strip()
        if not campaign_id:
            campaign_id = uuid.uuid4().hex[:12]
            self.db.reign.kv_set("campaign_id", campaign_id)
        fname = (
            f"{AUTO_SAVE_PREFIX}{campaign_id}_{self.state.year:04d}_"
            f"{self.state.period:02d}_t{self.state.turn:04d}_{tag}.db"
        )
        target = _os.path.join(saves_dir, fname)
        self.db.backup_to(target)
        prune_auto_saves(saves_dir, campaign_id)
        return target

    def save_to(self, name: str) -> Dict[str, object]:
        """手动存档到 ``saves/<name>.db``（#1902：两端共用；入口只管取名与呈现）。

        存档名清洗与路径拼装真源在 ``paths.save_slot_path``，Web 菜单、CLI 入口与
        会话层同用一份（Web 对外仍把自己的非法名翻成 400）。
        """
        from ming_sim.paths import safe_save_name, save_slot_path

        safe = safe_save_name(str(name or "").strip())
        target = save_slot_path(safe)
        self.db.backup_to(target)
        return {"name": safe, "path": target}

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

        次序：agno → db。仅由
        ``drain_and_close_session`` 在 SessionWriteQueue 已 seal、barrier 已排空且
        持 write_gate 时调用。agno 失败则立即上抛、不碰 db
        （两侧仍完整可恢复）。agno 已成功后 ``_close_epoch`` 递增——此后即使
        db.close 失败/conn 仍可探测，也不得恢复为活局（agno 已失）。
        """
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

from ming_sim.audience_night import CMD_CLOSE_NIGHT
