"""GameSession：CLI 与 Web 共用的统一回合流转层。L8。

不含 input()/print()——只持有状态、跑底层逻辑、返回 dataclass。
召见对话的 tool 截获、拟旨 draft 流转、诏书结算都收在这里，
CLI 和 Web 各自只做 I/O 包装。
"""

from __future__ import annotations

import json
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
from ming_sim.db import GameDB, infer_office_type_from_office, normalize_office
from ming_sim.decree import (
    ResolveResult,
    _provenance_from_stored,
    advance_without_edict,
    resolve_decisions_phase2,
    resolve_directives,
    resolve_settling_recovery,
    write_decree_with_agno,
)
from ming_sim.issues import bind_content as _bind_issues
from ming_sim.issues import sync_opening_legacies
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
    office_type = (
        "后宫" if is_consort
        else infer_office_type_from_office(office, str(data.get("office_type") or "待铨").strip(), llm_config)
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


def _sync_offices_from_db_impl(content: GameContent, db: "GameDB", llm_config: Optional[LLMConfig] = None) -> None:
    """启动/读档时以 DB characters 表重建内存人物表。
    DB 是持久化真相；不要在这里修写 DB。"""
    rows = db.conn.execute(
        """
        SELECT name, office, office_type, faction, aliases, personal_skills,
               loyalty, ability, integrity, courage, style,
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
        """注入近几回合章节记忆，让大臣知道近来朝局大事。章节记忆是回合粒度全局摘要，
        直接取最近 N 回合，不再按关键词检索（旧原子记忆已废）。"""
        from ming_sim.token_stats import tlog
        try:
            chapters = self.db.list_chapter_memories(upto_turn=self.state.turn, recent=4)
            if not chapters:
                return message
            lines = ["【近来朝局（近几月章节）】"]
            for c in chapters:
                body = (c.get("body") or "").strip()
                if not body:
                    continue
                lines.append(f"- {c['year']}年{c['period']}月：{body}")
            if len(lines) == 1:
                return message
            new_msg = "\n".join(lines) + "\n\n" + message
            tlog(f"[chat/chapter-recall] hit={len(chapters)} ({len(new_msg)}字)")
            return new_msg
        except Exception as exc:
            tlog(f"[chat/chapter-recall] 失败跳过：{exc}")
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
        confirm_targets = [p for p in pend_for_minister if p["kind"] != "directive"]
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

    def _finish_cli_action_intent(self, future: Optional[Future]) -> Optional[Dict[str, Any]]:
        if future is None:
            return None
        try:
            result = future.result()
        except Exception:
            return {"kind": "none"}
        return result if isinstance(result, dict) else {"kind": "none"}

    def chat(self, minister_name: str, message: str) -> ChatTurnResult:
        """与大臣对话一轮，统一处理 court tool 截获。
        大臣 propose_directive 产生的草案以 status='pending' 入库，
        作为 proposed_directive 返回，确认/驳回由调用方下达。"""
        if self.registry is None:
            raise RuntimeError("GameSession.begin_turn() 未调用。")
        character = self._character(minister_name)
        # 控制指令（退下/换人/技能）由 CLI 层 parse_court_command 处理；
        # GameSession.chat 只负责与 agent 对话与 tool 截获。
        agent = self.registry.get(character)
        augmented = self._retrieve_memories_for_message(message)
        # 本回合已核定草案随大臣议事滚动累加，agent system 在月初冻结拿不到——
        # 每次 chat 前置实时 draft_line 到 user message 头，确保大臣看得到兄弟大臣最新动作。
        draft_line = self.registry.build_draft_line()
        if draft_line and draft_line != "无":
            augmented = f"【本{TURN_UNIT}已核定草案】{draft_line}\n\n{augmented}"
        action_intent_future = self._start_cli_action_intent(character, message)
        run_output = agent.run(augmented)
        _dump_llm_messages(run_output, f"大臣对话/{minister_name}")
        answer = extract_agent_text(run_output)
        result = ChatTurnResult(answer=answer)
        for tool_exec in getattr(run_output, "tools", None) or []:
            tool_name = getattr(tool_exec, "tool_name", "")
            tool_result = str(getattr(tool_exec, "result", "") or "")
            if tool_name == "dismiss_minister" or tool_result == "__dismiss__":
                result.court_action = "dismiss"
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
                draft_text = tool_result.removeprefix("__pending_directive__").strip()
                if not draft_text:
                    args = getattr(tool_exec, "tool_args", {}) or {}
                    draft_text = (args.get("decree_text") or "").strip()
                if draft_text and self._proposal_blocked(self.state):
                    draft_text = ""  # 恢复窗婉拒：不入档（见 _proposal_blocked）
                if draft_text:
                    directive_id = self.db.add_directive(
                        self.state, None, draft_text, "大臣拟旨",
                        actor=character.name, notes=f"由{character.name}拟旨入档", status="pending",
                    )
                    result.proposed_directive = DirectiveView(
                        id=directive_id, text=draft_text, status="pending",
                        source="大臣拟旨", notes=f"由{character.name}拟旨入档",
                    )
            elif tool_name == "propose_appointment" or tool_result.startswith("__pending_appointment__"):
                payload = tool_result.removeprefix("__pending_appointment__").strip()
                appointed, displaced = self._apply_appointment(payload, character)
                if appointed:
                    result.appointed_minister = appointed
                    result.refresh_ministers.append(appointed)
                if displaced:
                    result.displaced_minister = displaced
                    result.refresh_ministers.append(displaced)
            elif tool_name == "register_unlisted_person" or tool_result.startswith("__pending_unlisted_person__"):
                payload = tool_result.removeprefix("__pending_unlisted_person__").strip()
                registered, summon_after = self._apply_unlisted_person_registration(payload)
                if registered:
                    result.registered_minister = registered
                    result.refresh_ministers.append(registered)
                    if summon_after:
                        result.court_action = "summon"
                        result.next_minister = registered
            elif tool_name == "secret_order" or tool_result.startswith("__secret_order_registered__"):
                if tool_result.startswith("__secret_order_registered__"):
                    try:
                        order_id = int(tool_result.split("__")[3])
                    except Exception:
                        order_id = 0
                    if order_id:
                        result.secret_order_id = order_id
        # CLI 后端（agy/codex）：玩家用拟旨/密令按钮（消息带前缀）时，把大臣这句回话原文入档。
        self._cli_backend_fallback_actions(
            result, character, message,
            preclassified_intent=self._finish_cli_action_intent(action_intent_future),
        )
        return result

    def apply_cli_conversation_actions(
        self, character: Character, player_message: str, answer: str,
        has_directive: bool, secret_order_id: Optional[int],
        preclassified_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """CLI 后端（无 function-calling）会话落地的【唯一真源】，session.chat 非流式路径与
        web streaming 路径共用，杜绝两边逻辑漂移（CMR F3 / codexC-1）。

        做三件事：① 前缀「拟旨」→ add_directive；② 前缀「密令」→ upsert + refresh；
        ③ 无前缀时让 LLM 判会话动作（更新/催办/提交核议/记进展/调教妃嫔）并落地。
        入参 has_directive / secret_order_id 表示 agno 工具路径是否已产出（已产则不重复）。
        返回 {"directive": {id,text,status,notes}|None, "secret_order_id": int|None}。"""
        from ming_sim.cli_backend import (
            _DRAFT_PREFIXES, _SECRET_PREFIXES,
            cli_backend_from_env, resolve_minister_actions, extract_minister_actions,
            extract_appointment_action, extract_confirmation_intent, extract_draft_intent,
        )
        out: Dict[str, Any] = {"directive": None, "secret_order_id": secret_order_id}
        intent = preclassified_intent if isinstance(preclassified_intent, dict) else None
        intent_kind = str((intent or {}).get("kind") or "none")
        channel = (getattr(getattr(self, "llm_config", None), "channel", "") or "").strip().lower()
        if channel != "cli" and (channel == "api" or cli_backend_from_env() is None):
            return out
        minister_name = character.name
        reply = (answer or "").strip()
        llm_config = getattr(self, "llm_config", None)
        # 显式前缀(拟旨如下:/密令如下:)= 皇帝已明示动作，由 resolve_minister_actions 零 LLM 落地。
        # 单一真源在此前置判定，统一把门【所有】后置 LLM 抽取器（确认/密令/调教/拟旨/任免），
        # 杜绝前缀路多跑任何 LLM extractor（#344 US3「按钮前缀路零 LLM」）。确认闸门尤其要跳过：
        # 否则前缀消息在有 pending 待确认动作时既多跑 extract_confirmation_intent(LLM)，还可能被
        # 误判「应允/拒绝」提前 return、把这道前缀拟旨/密令整个吞掉（确认句本无前缀，跳过无损）。
        explicit_prefixed = (message_text := (player_message or "").strip()).startswith(
            _DRAFT_PREFIXES) or message_text.startswith(_SECRET_PREFIXES)
        # 对话确认(ADR 0006 重设计)：本召对的大臣有上一轮经领命确认、尚未落库的暂存动作时，
        # 皇帝这句应允 → 当场 commit、拒绝 → 丢、未表态 → 留(颁诏对没回的算同意)。
        # 只在该大臣有 outstanding 暂存时才判(省 token)，commit/drop 按该大臣过滤、不波及他人。
        pend_for_minister = self.db.list_pending_actions(
            self.state.turn, minister_name=minister_name)
        # 召对确认闸门只管【召对期】暂存（密令/任免/调教）；kind=directive 拟旨的接受/搁置是
        # 颁诏期语义（不回=颁诏默认同意，ADR 0006），不能被召对期的应允/拒绝裹挟（BUG 1）：
        # 否则同大臣后一轮对【别的】暂存的应允会把对话草案提前 commit 成 draft，拒绝会静默删草案。
        # 故确认闸门用排除 directive 的视图，且 commit/drop 都带 kind_filter 排除 directive，
        # 让对话式拟旨穿过本闸门、活到颁诏。
        confirm_targets = [p for p in pend_for_minister if p["kind"] != "directive"]
        if confirm_targets and not explicit_prefixed:
            summaries = [_pending_action_brief(p) for p in confirm_targets]
            if intent is not None:
                confirm = str(intent.get("confirmation") or "无") if intent_kind == "confirmation" else "无"
                if confirm not in ("应允", "拒绝", "无"):
                    confirm = "无"
            else:
                confirm = extract_confirmation_intent(
                    player_message, reply, summaries, llm_config=llm_config)
            if confirm == "应允":
                if self.state.turn_phase in FRONT_HALF_DONE_PHASES:
                    # 恢复窗确认不即时落库（事务外落真表，后续 settle 中止不回滚=半写）。
                    # 动作留 pending，由推进回合的终端 atomic 统一落（所有权规则，ship-pre r2）。
                    pass
                else:
                    self.db.commit_pending_actions(
                        self.state, minister_name=minister_name,
                        kind_filter_exclude="directive",
                        content=getattr(self, "content", None),
                        registry=getattr(self, "registry", None))
            elif confirm == "拒绝":
                self.db.drop_pending_actions_for_minister(
                    self.state.turn, minister_name, kind_filter_exclude="directive")
            if confirm in ("应允", "拒绝"):
                # 本轮是对暂存的确认：大臣回话已【复述】该动作(领命 prompt 所致),若继续走下面的
                # 抽取,会把刚 commit 的动作从复述里重抽成新暂存→颁诏二次落库,或重建刚拒的动作。
                # 故确认轮直接返回,不再抽新动作(线上 codex P2)。确认句无前缀,前缀路无损失。
                return out
        if GameSession._proposal_blocked(self.state):
            # 恢复窗总闸（PR #90 R1/R2/R3 收束为单一出口）：前缀拟旨/密令与自然语言
            # 抽取的新暂存（密令动作/调教/任免）一并婉拒——窗内新写在 settle 重试事务
            # 边界外，窗内新 stage 则会被重试 settle 的 commit_pending_actions 落进
            # 「保存的 delta 推演时并不知道」的旧回合。上方对话确认块（应允延迟提交/
            # 拒绝丢弃）针对的是窗前已暂存的 pending，保持可用（ship-pre r2 设计）。
            # 抽取器（LLM 调用）一并跳过。
            return out
        acts = resolve_minister_actions(
            reply, player_message, default_assignee=minister_name, llm_config=llm_config)
        if not has_directive and acts["decree_text"]:
            text = acts["decree_text"]
            did = self.db.add_directive(
                self.state, None, text, "大臣拟旨",
                actor=minister_name, notes=f"由{minister_name}拟旨入档", status="pending",
            )
            out["directive"] = {"id": did, "text": text, "status": "pending",
                                "notes": f"由{minister_name}拟旨入档"}
        if not out["secret_order_id"] and acts["secret_order"]:
            so = acts["secret_order"]
            assignee = so.get("assignee") or minister_name
            oid, _ = self.db.upsert_secret_order(
                self.state, assignee, so["title"], so["content"],
                so.get("tags") or [], deadline_months=so.get("deadline_months", 0),
            )
            if oid:
                out["secret_order_id"] = oid
                if self.registry is not None:
                    self.registry.refresh(assignee)
        # 会话动作：本轮未经前缀落密令时，LLM 判皇帝对密令/妃嫔的意图再落地。
        # 前缀消息一律跳过（explicit_prefixed 已在顶部单一判定，统一把门所有后置 LLM 抽取器）。
        conversation_intent_handled = False
        if not out["secret_order_id"] and not explicit_prefixed:
            is_consort = getattr(character, "office_type", "") == "后宫"
            active = self.db.get_active_secret_orders_for_minister(minister_name)
            if active or is_consort:
                if intent is not None:
                    act = intent if intent_kind in ("secret", "cultivate") else {
                        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
                        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": ""}
                else:
                    act = extract_minister_actions(
                        player_message, reply, active, is_consort, llm_config=llm_config)
                sa = act["secret_action"]
                if sa and sa != "无":
                    conversation_intent_handled = True
                target = None
                if act["order_id"]:
                    target = next((o for o in active if int(o["id"]) == act["order_id"]), None)
                if target is None and len(active) == 1:
                    target = active[0]
                if target is not None and sa and sa != "无":
                    oid = int(target["id"])
                    # 只对 active 目标 stage:pending_review/已结的密令,更新/催办/提交核议/记进展
                    # 落库都会失败,stage 了只会成孤儿暂存行(ship-pre CMR codex)。非 active 一律不接。
                    target_active = str(target.get("status") or "active") == "active"
                    if target_active and sa == "更新":
                        # 动作闸门(ADR 0006)：进暂存，不动真实表；颁诏批量落库。
                        out["pending_action_id"] = self.db.stage_pending_action(
                            self.state.turn, kind="secret_order", action="更新",
                            minister_name=minister_name, target_id=oid,
                            payload={
                                "new_title": act["new_title"] or str(target.get("title") or ""),
                                "new_content": act["new_content"] or str(target.get("content") or ""),
                                "deadline_months": act["deadline_months"],
                            },
                        )
                    elif target_active and sa == "催办":
                        out["pending_action_id"] = self.db.stage_pending_action(
                            self.state.turn, kind="secret_order", action="催办",
                            minister_name=minister_name, target_id=oid,
                            payload={"reason": player_message[:80]})
                    elif target_active and sa == "提交核议":
                        out["pending_action_id"] = self.db.stage_pending_action(
                            self.state.turn, kind="secret_order", action="提交核议",
                            minister_name=minister_name, target_id=oid,
                            payload={"claim": reply[:200]})
                    elif target_active and sa == "记进展" and int(target.get("turn_issued") or 0) != int(self.state.turn):
                        out["pending_action_id"] = self.db.stage_pending_action(
                            self.state.turn, kind="secret_order", action="记进展",
                            minister_name=minister_name, target_id=oid,
                            payload={"note": reply[:200]})
                    # 注:密令会话动作走闸门后只暂存(out["pending_action_id"]),不再当场改真实表,
                    # 故无 secret_order_id、无需 refresh registry——暂存动作颁诏前对他臣不可见
                    # (ADR 0006),且 commit 在月末 next_period 前、次回合 agent 本就重建,无须刷新。
                if is_consort and (act["cultivate_skill"] or act["cultivate_trait"]):
                    conversation_intent_handled = True
                    # 后宫调教也是结构化聊天写动作,走动作闸门(ADR 0006):暂存,颁诏批量落库。
                    out["pending_action_id"] = self.db.stage_pending_action(
                        self.state.turn, kind="consort", action="调教",
                        minister_name=character.name, target_id=None,
                        payload={"name": character.name,
                                 "skill": act["cultivate_skill"], "trait": act["cultivate_trait"]})
        draft_probe_done = False
        draft_staged = False

        def _mentions_draft_request(text: str) -> bool:
            if not text:
                return False
            return any(
                token in text
                for token in ("拟旨", "拟一道旨", "起草", "草拟", "拟诏", "圣旨", "这道旨", "道旨")
            )

        def _stage_conversational_draft() -> bool:
            nonlocal draft_probe_done
            draft_probe_done = True
            if explicit_prefixed or has_directive or out.get("pending_action_id"):
                return False
            _has_pending_draft = any(p["kind"] == "directive" for p in pend_for_minister)
            _committed_draft = None
            if not _has_pending_draft:
                for _directive in reversed(self.db.list_directives(self.state, statuses=("draft",))):
                    if str(_directive["actor"] or "") == minister_name:
                        _committed_draft = _directive
                        break
            _has_existing_draft = _has_pending_draft or _committed_draft is not None
            # 补充模式：提取现有草案文本喂给 extract_draft_intent，让 LLM 合并新旧草案；
            # 直接用大臣回话（可能是确认语）会覆盖原草案（codex r6 F1）。
            _existing_draft_text = ""
            if _has_pending_draft:
                _pdir = next((p for p in pend_for_minister if p["kind"] == "directive"), None)
                if _pdir:
                    try:
                        _val = _pdir["payload_json"] or "{}"
                        _payload = (
                            _val if isinstance(_val, (list, dict))
                            else json.loads(_val)
                        )
                    except (ValueError, TypeError):
                        _payload = {}
                    if isinstance(_payload, dict):
                        _existing_draft_text = str(_payload.get("text") or "")
            elif _committed_draft is not None:
                _existing_draft_text = str(_committed_draft["text"] or "")
            if intent is not None and intent_kind == "draft" and not _has_existing_draft:
                # 全新草案：大臣回话即草案原文，零额外 LLM（#344）。
                draft_res = {"draft_action": "拟旨", "draft_text": reply}
            elif intent is not None and not _has_existing_draft:
                # 无现存草案 + 分类器判非拟旨 → 零额外 LLM（#344 常见消息秒回）。
                draft_res = {"draft_action": "无", "draft_text": ""}
            else:
                # 【已有草案（pending/committed）的任何后续】或 intent is None（旧路）：一律走
                # extract_draft_intent 合并新旧草案，绝不用 raw reply 覆盖已有草案——分类器看不到
                # committed draft，无论它判 none 还是 draft，直接拿回话覆盖都会丢掉原草案内容
                # （codex correctness：none 半与 draft 半是同一覆盖丢失的两面，统一收敛到 merge）。
                # 额外 LLM 只在「已有草案」这一动作场景发生，普通无草案消息不受影响。
                draft_res = extract_draft_intent(
                    player_message, reply, llm_config=llm_config,
                    has_pending_draft=_has_existing_draft,
                    existing_draft_text=_existing_draft_text,
                )
            if draft_res["draft_action"] == "拟旨" and draft_res["draft_text"]:
                if _committed_draft is not None and not _has_pending_draft:
                    did = int(_committed_draft["id"])
                    self.db.update_directive_text(did, draft_res["draft_text"])
                    out["directive"] = {
                        "id": did,
                        "text": draft_res["draft_text"],
                        "status": "draft",
                        "notes": f"由{minister_name}拟旨入档",
                    }
                else:
                    pid = self.db.upsert_pending_directive(
                        self.state.turn, minister_name,
                        payload={"text": draft_res["draft_text"], "actor": minister_name},
                    )
                    out["pending_action_id"] = pid
                return True
            return False

        # 若皇帝话里已明确「拟旨/起草/圣旨」，先让拟旨抽取器判；否则「帮我拟旨，
        # 授某人为某官」会被任免抽取抢成 office pending，丢失诏书草案路径。
        has_pending_directive = any(p["kind"] == "directive" for p in pend_for_minister)
        has_committed_directive = False
        if not has_pending_directive:
            for _directive in reversed(self.db.list_directives(self.state, statuses=("draft",))):
                if str(_directive["actor"] or "") == minister_name:
                    has_committed_directive = True
                    break
        # 已有草案（pending 或 committed）时，无论并发分类器判什么都要进 _stage 合并：分类器只读
        # 皇帝本条消息、且看不到 committed draft 上下文，会把「再补一条…随行」这类后续补充误判成
        # none → 静默丢掉草案补充（违背 #344 US6「动作仍正确落库」，codex correctness）。无草案时
        # 仍按原逻辑（intent=='draft' 或旧路 _mentions/pending）触发，普通无动作消息零额外 LLM 不变。
        if (
            (intent is not None and intent_kind == "draft")
            or has_pending_directive
            or has_committed_directive
            or (intent is None and _mentions_draft_request(player_message))
        ):
            draft_staged = _stage_conversational_draft()

        # 任免(office)独立检测：与密令无关，随召对触发(ungated)，覆盖大臣+太监。
        # 口头任命/罢免 → 暂存 kind=office；颁诏前不动 characters 表。
        # 显式前缀(拟旨/密令)是皇帝已明示的动作，按既定例外直接走(拟旨里的任免随诏书
        # 走 extractor 的 office_changes)，不在此自然语言路径重复 stage。
        appt = {"appoint_action": "无"}
        if (
            not explicit_prefixed and not draft_staged
            and not out.get("pending_action_id") and not conversation_intent_handled
        ):
            if intent is not None:
                appt = intent if intent_kind == "appointment" else {"appoint_action": "无"}
            else:
                appt = extract_appointment_action(player_message, reply, llm_config=llm_config)
        if appt["appoint_action"] in ("任命", "罢免") and appt["name"]:
            # minister_name = 召对对象(发起这道任免的大臣/太监),非被任者——对话确认按召对的
            # 大臣过滤暂存,故须以召对对象为键;被任者姓名在 payload["name"]。
            out["pending_action_id"] = self.db.stage_pending_action(
                self.state.turn, kind="office", action=appt["appoint_action"],
                minister_name=minister_name, target_id=None,
                payload={"name": appt["name"], "office": appt["office"],
                         "appointer": minister_name})
        # 对话式拟旨意图(ADR 0006 自然语言路径)：非显式前缀、尚无 draft、且本轮未 stage 其他动作时，
        # 判皇帝是否口头请拟旨；检测到则 upsert pending directive（last-write-wins，同大臣同回合至多一条）。
        # 挂在任免之后、以"无其他 pending 动作"为守门：前缀/密令更新/任免等已处理的情形语义上
        # 与拟旨互斥，跳过可省一次 LLM 调用；余下的才是真正口头请拟旨的情形。
        # _has_pending_draft：此大臣本回合已有 kind=directive 暂存时为 True（confirm=="无"後仍在）。
        # pend_for_minister snapshot 此处仍有效：confirm=="应允"/"拒绝"会在上方提前 return，
        # 能到这里说明 directive 未 commit/drop，snapshot 与 DB 一致（codex r5 F1 修复）。
        return out

    def _cli_backend_fallback_actions(
        self, result: "ChatTurnResult", character: Character, player_message: str = "",
        preclassified_intent: Optional[Dict[str, Any]] = None,
    ) -> None:
        """session.chat 非流式路径：调共享会话落地，映射回 ChatTurnResult（agno 工具不触发时）。"""
        res = self.apply_cli_conversation_actions(
            character, player_message, result.answer or "",
            has_directive=result.proposed_directive is not None,
            secret_order_id=result.secret_order_id,
            preclassified_intent=preclassified_intent,
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
        title = str(data.get("title") or "").strip()[:20]
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
        return self.db.create_secret_order(self.state, assignee, title, content, tags, deadline_months=deadline)

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
        self.db.confirm_directive(directive_id)

    def reject_directive(self, directive_id: int) -> None:
        self._refuse_if_settling()
        self.db.reject_directive(directive_id)

    def add_directive(self, text: str, notes: str = "") -> DirectiveView:
        self._refuse_if_settling()
        directive_id = self.db.add_directive(self.state, None, text, "手动新增", notes=notes)
        return DirectiveView(id=directive_id, text=text, status="draft",
                             source="手动新增", notes=notes)

    def update_directive(self, directive_id: int, text: str) -> None:
        self._refuse_if_settling()
        self.db.update_directive_text(directive_id, text)

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
        # 守门须早于 commit（BUG 2）：有未核定的显式 pending directive 时，先响亮拒绝，
        # 再 commit 对话式拟旨——否则被拒的调用已把对话草案落成 draft 副作用、无回滚。
        if self.pending_count() > 0:
            raise ValueError(f"尚有 {self.pending_count()} 道大臣拟旨待陛下核定（准/驳），不能颁诏。")
        # "不回=默认同意"（ADR 0006）：把对话式拟旨暂存（pending_actions kind=directive）
        # 提交为 draft，使 list_directives(status='draft') 能拾取——这是 web「拟诏」按钮
        # 的真实入口路径，不经过 resolve_turn 的 auto-commit。幂等，无副作用。
        self.db.commit_pending_actions(
            self.state, kind_filter="directive",
            content=getattr(self, "content", None),
            registry=getattr(self, "registry", None))
        directives = self.db.list_directives(self.state, statuses=("draft",))
        if not directives:
            raise ValueError("无草案不能拟诏。")
        decree = write_decree_with_agno(self.llm_config, self.agno_db, self.state, directives, db=self.db)
        self.last_decree = decree
        # P1-1：记下本份生成稿覆盖的 draft 集指纹。颁诏时若 draft 集已变（玩家拟诏后又新建
        # 草案），凭此判定 last_decree 已陈旧、强制重生成纳入新 draft，不许把新 draft 标记
        # 为已颁却不进诏书正文。
        self._decree_draft_fingerprint = self._draft_fingerprint(directives)
        return decree

    def set_decree(self, text: str) -> str:
        """皇帝手动改定诏书正文（拟诏后、颁诏前）。颁诏时 resolve_turn 用此 last_decree。"""
        self._refuse_if_settling()
        text = (text or "").strip()
        if not text:
            raise ValueError("诏书正文不能为空。")
        self.last_decree = text
        directives = self.db.list_directives(self.state, statuses=("draft",))
        self._decree_draft_fingerprint = self._draft_fingerprint(directives)
        return self.last_decree

    def resolve_turn(self, decree: str = "", on_event=None, cheat_directive: str = "") -> ResolveResult:
        """颁诏并推演本回合（phase1）。要求无 pending 残留、≥1 条 draft。

        on_event(kind, data): 推演过程实时回调，透传给 resolve_directives。
        cheat_directive: 作弊控制台强制结算项，一次性透传给 resolve_directives。

        返回 ResolveResult：含决策点 → awaiting=True，置 awaiting_decision 态，回合未推进，
        调用方据 result.decisions 弹窗，皇帝裁完调 submit_decisions。无决策点 → awaiting=False，
        回合已结算推进，置 issued 态。
        """
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
            if ctx is not None and ctx.get("extracted") is not None:
                # 与正常路同守门：恢复期大臣新拟的 pending 旨未核定不得推进——
                # 重放跳过守门会把它孤儿在旧回合（cmr S7 r8）。
                if self.pending_count() > 0:
                    raise ValueError(
                        f"尚有 {self.pending_count()} 道大臣拟旨待陛下核定（准/驳），不能颁诏。")
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
        # 守门须早于 commit（BUG 2）：有未核定的显式 pending directive 时先响亮拒绝，
        # 再 commit 对话式拟旨——否则被拒的颁诏已把对话草案落成 draft 副作用、无回滚。
        # draft 不计入 pending_count（后者只计 turn_directives.status='pending'），守门只看显式 pending。
        if self.pending_count() > 0:
            raise ValueError(f"尚有 {self.pending_count()} 道大臣拟旨待陛下核定（准/驳），不能颁诏。")
        # "不回=默认同意"（ADR 0006）：颁诏前先把对话式拟旨暂存（pending_actions kind=directive）
        # 提交为 draft，使 list_directives(status='draft') 能拾取、进入本次诏书。
        committed_directives = self.db.commit_pending_actions(
            self.state, kind_filter="directive",
            content=getattr(self, "content", None),
            registry=getattr(self, "registry", None))
        if committed_directives and recovered_source is None and (decree or "").strip():
            # 外部传入的 decree 早于本次 auto-commit 出来的对话草案；若继续使用，会把新 draft
            # 标为 issued 却不进诏书正文/extractor 输入。强制按当前 draft 集重拟。
            decree = ""
            self.last_decree = ""
            self._decree_draft_fingerprint = ()
        directives = self.db.list_directives(self.state, statuses=("draft",))
        if not directives:
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
        # 注：上方的 commit_pending_actions(kind_filter='directive') 已提前把对话式拟旨
        # 提交为 draft；下方 resolve_directives 内的 commit_pending_actions 再次调用时
        # 对已 committed 行是幂等 no-op，不重复落库。
        decree_text = decree or self.last_decree or write_decree_with_agno(
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
        # 与 resolve_turn 同守门（cmr S7 r8/r9 对称面）：暂停期大臣新拟的 pending 旨
        # 未核定不得推进——phase2（重放或重抽）随 next_period 会把它孤儿在旧回合。
        if self.pending_count() > 0:
            raise ValueError(
                f"尚有 {self.pending_count()} 道大臣拟旨待陛下核定（准/驳），不能颁诏。")
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
                if event_id:
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

    def advance_without_decree(self) -> None:
        """CLI 退朝无草案：仅财政 tick + 推进。"""
        advance_without_edict(
            self.state, self.db, content=self.content, registry=self.registry)
        self.state.turn_phase = TurnPhase.SUMMONING.value
        self.db.save_state(self.state)

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
