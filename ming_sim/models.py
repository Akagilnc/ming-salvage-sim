"""数据类：游戏实体与状态容器。L0 叶子模块。

CourtContext 的 state/db 注解用字符串前向引用，避免 import db.py。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from ming_sim.constants import (
    ARMY_FIELD_ALIASES,
    ARMY_QUANTITY_FIELDS,
    ARMY_SCORE_FIELDS,
    ARMY_TEXT_FIELDS,
    BUILDING_CATEGORIES,
    BUILDING_FIELD_ALIASES,
    BUILDING_QUANTITY_FIELDS,
    BUILDING_SCORE_FIELDS,
    BUILDING_TEXT_FIELDS,
    ECONOMY_ACCOUNTS,
    FISCAL_SCORE_FIELDS,
    POWER_FIELD_ALIASES,
    REGION_FIELD_ALIASES,
    REGION_QUANTITY_FIELDS,
    REGION_SCORE_FIELDS,
    REGION_TEXT_FIELDS,
    SCORE_METRICS,
)
from ming_sim.person_archive_contract import PERSON_ACTIONS


def loads_effect_dict(raw: object) -> Dict[str, object]:
    """读 effect_on_resolve / effect_on_fail / ongoing_effects 等存库 effect-JSON 的单一入口（#117）：
    - 已是 dict（调用方传解析过的对象）→ 原样返回；
    - JSON 字符串 → 解析；解析失败或真值非 dict（脏库/历史写路径/标量）→ {}。
    所有 effect-列读取统一经此，下游 .get/.items 永不在非 dict 上崩回合。放 models（leaf，只依赖 json）
    避免 db↔issues 循环——db / issues / simulation / web_app 都从这里取（cmr #117 R4）。"""
    if isinstance(raw, dict):
        return raw
    if not raw:  # None / 空串等常见空值：快速返 {}，免 json.loads 解析开销（gemini PR#127 R2）
        return {}
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def _nonzero_int(raw: object) -> bool:
    if raw in (None, "") or isinstance(raw, (bool, float)):
        return False
    try:
        return int(raw) != 0  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return False


def _nonempty_text(raw: object) -> bool:
    return isinstance(raw, str) and bool(raw.strip())


def _metric_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    return any(key in SCORE_METRICS and _nonzero_int(value) for key, value in raw.items())


def _economy_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        account = str(item.get("account") or "").strip()
        if account in ECONOMY_ACCOUNTS and _nonzero_int(item.get("delta")):
            return True
    return False


def _faction_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    for value in raw.values():
        if isinstance(value, dict):
            if any(
                field in ("satisfaction", "leverage") and _nonzero_int(delta)
                for field, delta in value.items()
            ):
                return True
        elif _nonzero_int(value):
            return True
    return False


def _class_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    for value in raw.values():
        if not isinstance(value, dict):
            continue
        if any(
            field in ("satisfaction", "leverage") and _nonzero_int(delta)
            for field, delta in value.items()
        ):
            return True
    return False


def _entity_delta_has_work(
    raw: object,
    *,
    aliases: Dict[str, str],
    numeric_fields: tuple[str, ...],
    text_fields: tuple[str, ...] = (),
) -> bool:
    if not isinstance(raw, dict):
        return False
    numeric = set(numeric_fields)
    text = set(text_fields)
    for changes in raw.values():
        if not isinstance(changes, dict):
            continue
        for raw_field, value in changes.items():
            field = aliases.get(str(raw_field).strip(), str(raw_field).strip())
            if field in numeric and _nonzero_int(value):
                return True
            if field in text and _nonempty_text(value):
                return True
    return False


def _building_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    numeric = set(BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS)
    text = set(BUILDING_TEXT_FIELDS)
    for op in raw:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action") or "").strip().lower()
        if action == "create":
            category = str(op.get("category") or "").strip()
            if category in BUILDING_CATEGORIES and _nonempty_text(op.get("region_id")):
                return True
            continue
        if action == "remove":
            if _nonempty_text(op.get("building_id")):
                return True
            continue
        if action != "modify" or not _nonempty_text(op.get("building_id")):
            continue
        for raw_field, value in op.items():
            field = BUILDING_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
            if field in numeric and _nonzero_int(value):
                return True
            if field in text and _nonempty_text(value):
                return True
    return False


def _new_armies_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        mapped = {ARMY_FIELD_ALIASES.get(str(k).strip(), str(k).strip()): v for k, v in item.items()}
        if _nonempty_text(mapped.get("id")) and _nonzero_int(mapped.get("manpower")):
            return True
    return False


def _person_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("人物") or "").strip()
        action = str(item.get("动作") or item.get("action") or "").strip()
        if not name or action not in PERSON_ACTIONS:
            continue
        if action == "评定":
            loyalty = item.get("loyalty")
            if (
                not isinstance(loyalty, bool)
                and isinstance(loyalty, int)
                and loyalty != 0
            ):
                return True
            continue
        if action == "性情":
            style = item.get("style")
            if isinstance(style, str) and style.strip():
                return True
            continue
        return True
    return False


def _character_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not _nonempty_text(item.get("name")):
            continue
        loyalty = item.get("loyalty")
        if (
            not isinstance(loyalty, bool)
            and isinstance(loyalty, int)
            and loyalty != 0
        ):
            return True
    return False


def _character_status_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        if _nonempty_text(item.get("name")) and _nonempty_text(item.get("status")):
            return True
    return False


def _character_power_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        if _nonempty_text(item.get("name")) and (
            _nonempty_text(item.get("new_power")) or _nonempty_text(item.get("power_id"))
        ):
            return True
    return False


def _power_renames_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        if _nonempty_text(item.get("power_id")) and _nonempty_text(item.get("new_name")):
            return True
    return False


def _legacy_effect_has_work(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    modifiers = raw.get("modifiers")
    if not isinstance(modifiers, dict):
        return False
    for key in ("国库", "内库", "民心", "皇威"):
        if _nonzero_int(modifiers.get(key)):
            return True
    if _entity_delta_has_work(
        modifiers.get("regions"),
        aliases=REGION_FIELD_ALIASES,
        numeric_fields=REGION_SCORE_FIELDS + FISCAL_SCORE_FIELDS,
    ):
        return True
    return _entity_delta_has_work(
        modifiers.get("armies"),
        aliases=ARMY_FIELD_ALIASES,
        numeric_fields=ARMY_SCORE_FIELDS,
    )


def effect_dict_has_work(raw: object) -> bool:
    """Return whether an effect/ongoing payload has semantic work, not just a non-empty shell."""
    effect = loads_effect_dict(raw)
    if not effect:
        return False
    checks = (
        _metric_effect_has_work(effect.get("metrics")),
        _economy_effect_has_work(effect.get("economy")),
        _economy_effect_has_work(effect.get("economy_moves")),
        _faction_effect_has_work(effect.get("factions")),
        _faction_effect_has_work(effect.get("faction_delta")),
        _class_effect_has_work(effect.get("classes")),
        _class_effect_has_work(effect.get("class_delta")),
        _entity_delta_has_work(
            effect.get("region_delta") or effect.get("regions"),
            aliases=REGION_FIELD_ALIASES,
            numeric_fields=REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + FISCAL_SCORE_FIELDS + ("cannon",),
            text_fields=REGION_TEXT_FIELDS,
        ),
        _entity_delta_has_work(
            effect.get("army_delta") or effect.get("armies"),
            aliases=ARMY_FIELD_ALIASES,
            numeric_fields=ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS,
            text_fields=ARMY_TEXT_FIELDS,
        ),
        _entity_delta_has_work(
            effect.get("power_updates"),
            aliases=POWER_FIELD_ALIASES,
            numeric_fields=("leverage", "military_strength", "supply"),
        ),
        _building_effect_has_work(effect.get("buildings")),
        _new_armies_effect_has_work(effect.get("new_armies")),
        _person_effect_has_work(effect.get("人物变更")),
        _person_effect_has_work(effect.get("person_changes")),
        _character_effect_has_work(effect.get("character")),
        _character_status_effect_has_work(effect.get("character_status_changes")),
        _character_power_effect_has_work(effect.get("character_power_changes")),
        _power_renames_effect_has_work(effect.get("power_renames")),
        _legacy_effect_has_work(effect.get("legacy")),
    )
    return any(checks)


class TurnPhase(str, Enum):
    """回合相位单一真源（原住 session.py；decree 也要用，session import decree 会循环，
    故下沉至此，session 保持 re-export 兼容旧 import 路径）。"""

    SUMMONING = "summoning"   # 召见中：召见、对话、大臣拟旨产 pending
    REVIEWING = "reviewing"   # 核定草案：增删改、确认/驳回 pending、写诏书
    AWAITING_DECISION = "awaiting_decision"  # HITL：simulator 出决策点，暂停等皇帝亲裁
    SETTLING = "settling"     # ADR 0008 S4：pre_settle 前半段已提交，崩溃重进不重跑前半段（中间态）
    ISSUED = "issued"         # 已颁诏：resolve 完成，待 end_turn


# 「前半段已提交」相位集：pre_settle 守门/粘滞/skip 跳过判定的单一真源（cmr S4 r3 集中化）。
# AWAITING 只可能在 pre_settle 事务提交后出现（HITL 暂停在 resolve 中段），语义同 settling。
FRONT_HALF_DONE_PHASES = (TurnPhase.SETTLING.value, TurnPhase.AWAITING_DECISION.value)


@dataclass
class ChatResult:
    action: str
    next_minister: str = ""
    refresh_ministers: List[str] = field(default_factory=list)


# LLM 后端默认值 / 通道集合的单一真源——放 L0 叶子 models，llm_config 与 cli_backend 都从此处
# import（两者皆 import models），彻底消除 llm_config↔cli_backend 的懒-import（#60）。旧址
# （llm_config.CLI_DEFAULT_TIMEOUT_SECONDS/VALID_CHANNELS、cli_backend.CODEX/CLAUDE_DEFAULT_MODEL）
# 改为从这里 re-export，保留既有 import 路径。
CODEX_DEFAULT_MODEL = "gpt-5.5"
CLAUDE_DEFAULT_MODEL = "claude-opus-4-8"
CLI_DEFAULT_TIMEOUT_SECONDS = 300.0  # CLI 子进程默认超时（秒），与 API 的 timeout_seconds 区分
MINISTER_CHAT_CLI_TIMEOUT_SECONDS = 90.0  # 实时召对大臣回话专用短超时（#353），与月末结算 300s 解耦
VALID_CHANNELS = frozenset({"api", "cli"})  # 合法执行通道集合，新增通道只改这里
API_DEFAULT_TIMEOUT_SECONDS = 180.0  # API 请求默认超时（秒）单一真源（#58）
# #1465 transport 统一策略默认值（单真源；次数/超时/空转进 runtime 可覆盖，代码零硬编码）
TRANSPORT_DEFAULT_MAX_ATTEMPTS = 3  # 总计 3 attempts（初试 1 + 重试 2；第一次不叫重试）
TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS = 30.0  # 每 attempt 独立整份超时（owner：每次 30 秒）
TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS = 30.0  # 空转：距上次输出静默阈值（票面不定数值，与 attempt 同量级）


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = API_DEFAULT_TIMEOUT_SECONDS
    thinking_level: str = ""  # 空=沿用旧逻辑；否则原样传给 reasoning_effort
    advanced_model: str = ""  # 空=fallback model；非空=推演/打分专用更强模型（如 deepseek-reasoner / gpt-5）
    advanced_base_url: str = ""  # 空=复用主 base_url；非空=advanced 角色专用网关
    advanced_api_key: str = ""  # 空=复用主 api_key；非空=advanced 角色专用 key
    advanced_thinking_level: str = ""  # legacy input only; unified reasoning_strength owns reasoning
    reasoning_strength: str = ""  # 抽象推理强度：off/low/medium/high；空=沿用后端默认/旧配置
    channel: str = ""  # ""=沿用旧 env 探针；api=OpenAI 兼容 API；cli=本地 CLI runner
    cli_runner: str = ""  # agy | codex | claude | cursor | kimi | grok | pi（名单真源=_CLI_BACKENDS）
    cli_model: str = ""  # CLI runner 的模型名/档位，由具体后端解释
    cli_timeout_seconds: float = CLI_DEFAULT_TIMEOUT_SECONDS  # CLI 子进程超时，同模块常量直接引用


@dataclass
class Character:
    name: str
    office: str
    office_type: str
    faction: str
    aliases: List[str]
    personal_skills: List[str]
    loyalty: int
    ability: int
    integrity: int
    courage: int
    style: str
    power_id: str
    location: str = ""
    transit_to: str = ""
    transit_distance_remaining: float | None = None
    transit_speed_factor: float | None = None
    transit_start_turn: int = 0
    birth_year: int = 0  # 历史生年（公历，0=未填）
    historical_death_year: int = 0  # 历史卒年（公历，0=未填）
    historical_death_month: int = 0  # 1-12，0=未指定
    debut_year: int = 0  # 历史登场年（公历，0=开局即在场）
    debut_month: int = 0  # 1-12，0=不限月
    status: str = "active"  # active | offstage | dismissed | imprisoned | exiled | retired | dead
    status_reason: str = ""  # 人读去职/迁移缘由（ADR 0009 三面同步；DB characters.status_reason 真源）
    reason_code: str = ""  # 机读缘由枚举（ADR 0009；人才池/起复派生用；DB characters.reason_code 真源）
    summary: str = ""  # 人物简介，后宫/大臣均有
    portrait_id: str = ""  # 头像文件标识：空=无专属；"minister_pool_3"=用第3号预设头像
    seed_guilt: Dict[str, str] = field(default_factory=dict)  # 开局罪谱；引擎内部值，不进入人物呈现上下文
    identity: int = 50  # 党派认同度；引擎内部值，不进入人物呈现上下文


VASSAL_PRINCE_OFFICE_TYPE = "宗藩"
WEISHI_OFFICE_TYPE = "未仕"


def is_vassal_prince(character: "Character") -> bool:
    """宗藩（就藩宗室）非朝堂命官——召见/任免/密令/名册一律排除（用户 2026-06-14 拍：宗室隐藏）。

    单一定义，所有面引用此规则（PR#121，cmr R3–R5 cross-section coverage-drift 收敛于此）。
    受守面清单（新增同类面时一并加，勿漏）：
    - web_app: visible_in_court / in_talent_pool / _require_active_minister / api_create_secret_order
    - simulation: court_roster / active_ministers / _talent_pool_rows（SQL office_type NOT IN(…'宗藩'…)）
    - tools: get_active_ministers / query_court_roster
    - registry: build_court_roster / build_court_roster_index
    - session: can_summon（召对 choke）/ list_ministers（召见阶段名册）
    - issues: apply_office_appointment（任命落地核 choke——授官会改 office_type、反解 roster 隐藏，必守）
    - session: can_summon（召对 choke，覆盖 session/web/CLI choose_minister 三路）
    - db: create_secret_order（密令唯一 DB 写口 choke）/ _commit_office_action 罢免（玩家罢免）
    roster 类同时排 后宫/未仕，用 office_type in ('后宫','宗藩','未仕')；本 helper 只判宗藩这一面。

    **规则边界（玩家动作 vs 世界事件，cmr R7 拍）**：守的是「皇帝把宗室当朝堂命官来召见/任免/
    罢免/下密令」这类玩家动作面。**simulator/extractor 叙事处置故意不守**——宗室可因世界事件
    死/被俘/废为庶人（史实如福王 1641 被李自成所杀），extractor character_status_changes 的
    罢黜/处置路（issues.apply_person_status_changes）应允许改宗藩状态；况且 dismiss/dead 不改
    office_type，宗藩照旧不入任何 roster。勿在叙事处置路加宗藩闸（会掐掉合法 diegetic 事件）。

    容 None（防御，R3 gemini）：传 None 返 False，使本判据不比调用点的存在性检查更严。"""
    return character is not None and character.office_type == VASSAL_PRINCE_OFFICE_TYPE


def is_weishi(character: "Character") -> bool:
    """未仕（诸生/童生等身名分）——可在册待铨，但非在朝可召命官（#1317 r2）。

    与「在册身份归一」分离：别名/查重必须认识未仕（史宪之→史可法不得建重档）；
    「在朝可召资格」= 身份归一 ∧ 非宗藩 ∧ 非未仕，由可召/名册面共吃。
    受守面清单（新增同类面时一并加，勿漏；形制同 is_vassal_prince）：
    - session: list_ministers / can_summon（朝臣支；后宫走专路）
    - web_app: visible_in_court
    - cli: terminal.choose_minister
    - cli_backend: _draft_intent_character_roster_facts（拟诏事实块）
    - simulation: court_roster / active_ministers（SQL office_type NOT IN(…'未仕')）
    - tools: get_active_ministers
    - registry: build_court_roster / build_court_roster_index
    - db: current_court_roster_rows（已排）
    - web_app: in_talent_pool / simulation._talent_pool_rows（未入仕非「可起复前臣」）
    任命写路径（apply_office_appointment）**不**守本闸——未仕入仕是合法铨选。
    同型 seed 先例：郑成功/张煌言等诸生童生 offstage（非钱谦益——钱为罢居礼部、非未仕）。
    容 None：传 None 返 False。"""
    return character is not None and getattr(character, "office_type", None) == WEISHI_OFFICE_TYPE


@dataclass
class Event:
    id: str
    title: str
    kind: str
    summary: str
    urgency: int
    severity: int
    credibility: int
    interests: List[str]
    audiences: List[str]
    resolve_condition: str = ""
    fail_condition: str = ""
    trigger_year: int = 0   # 历史锚定触发年（公历，0=非历史锚定，靠 trigger_gate）
    trigger_month: int = 0  # 1-12，0=年内任意月
    trigger_end_year: int = 0   # 候选窗口结束年（0=不设上限）
    trigger_end_month: int = 0  # 候选窗口结束月（0=年内任意月）
    open_window: bool = False  # True=显式开放窗，永不过期
    precondition: str = ""  # 触发前提+改写口子人话说明，喂 simulator 由 LLM 据盘面判断是否改写/跳过（见 season_simulator.md 候选情势触发判定）
    event_type: str = "situation"  # situation=转 bar issue；node=只播报不转 issue；ending=交结局判定
    trigger_class: str = ""  # strategic_foreign=战略/外敌类：点名将按席位顶替，不因将领死亡作废
    category: str = ""  # 事件机制分类；fiscal_levy 等特化确定性通道按此识别，不硬编 id
    person_core_subjects: List[str] = field(default_factory=list)  # 人物核心事件主体：这些人永久死亡→事件作废退候选
    trigger_gate: Dict[str, str] = field(default_factory=dict)  # seed 候选门槛：{metric: 比较式}，全满足才进候选
    auto_trigger: bool = False  # True=gate 达标即由程序硬立项，绕过 LLM 因果判定（不进候选池等 extractor 决定）
    terminal_reason_labels: List[str] = field(default_factory=list)  # 封闭结局标签集；空=无专用白名单
    default_terminal_reason: str = ""  # shadow / deterministic stub 默认结局，必须属于 terminal_reason_labels
    # 以下为可选「精调 issue 字段」：原 opening_crises 那种手调危机用，立项时 event_to_issue 优先读这些，
    # 缺省（0/空）则按 severity/kind 自动推导。合并 opening_crises → seed_events 后承接其手调值。
    bar_value: int = 0                                            # 0=自动推导
    bar_good_meaning: str = ""
    bar_bad_meaning: str = ""
    issue_inertia: int = 0                                        # 立项时初始 inertia（默认 0=不漂；要每月漂移就在 seed/event 里显式填）
    stage_text: str = ""                                          # issue 阶段文案（空=用 summary）
    region_hint: str = ""
    issue_tags: List[str] = field(default_factory=list)           # 空=用 [kind]
    ongoing_effects: Dict[str, object] = field(default_factory=dict)
    effect_on_trigger: Dict[str, object] = field(default_factory=dict)
    effect_on_resolve: Dict[str, object] = field(default_factory=dict)
    effect_on_fail: Dict[str, object] = field(default_factory=dict)


@dataclass
class Faction:
    name: str
    satisfaction: int
    leverage: int
    agenda: str


@dataclass
class SocialClass:
    """阶级人口：朝堂外的社会基本盘。
    region_id="" 表示全国汇总；非空表示该省切片（key 与 regions.id 对应）。
    机制：lev 高 + sat 低 → 易触发该省/该阶级骚乱事件，由 LLM 在推演中判定。
    """
    name: str            # 农民/士绅/官僚/军户/商人/匠户/宗藩/流民
    region_id: str       # "" = 全国汇总；否则匹配 regions.id
    population: int      # 人（ADR 0088，与 manpower 同刻度；全国汇总=各省合计的参考值）
    satisfaction: int    # 0-100
    leverage: int        # 0-100
    agenda: str          # 一句话诉求


@dataclass
class Region:
    id: str
    name: str
    kind: str
    population: int
    public_support: int
    unrest: int
    natural_disaster: str
    human_disaster: str
    registered_land: int
    hidden_land: int
    tax_per_turn: int
    grain_security: int
    gentry_resistance: int
    military_pressure: int
    status: str
    controlled_by: str
    city_level: int = 0   # 城市等级 0-5（静态，史实分级；城防炮上限=×8，将来供经济/内政）
    cannon: int = 0       # 城防大炮门数（城头红夷炮，上限 city_level×8）
    fiscal: dict = field(default_factory=dict)
    on_restore: dict = field(default_factory=dict)
    # fiscal JSON 字段说明（万亩/万两/0-100）：
    # huang_tian    皇庄（万亩），产出→内库，仅北直隶有
    # wang_tian     藩王庄田（万亩），免税，禄米→国库支出
    # guan_min_tian 官民田（万亩），田赋→国库
    # liao_xiang    辽饷月摊派额（万两）
    # salt_tax      盐税月基数（万两），产盐省才>0
    # commerce_tax  商税月基数（万两）
    # corruption    腐败度 0-100，影响解运比
    # on_restore    收复时（controlled_by 非 ming → ming）覆盖到主字段的预置盘面


@dataclass
class Army:
    id: str
    name: str
    station: str
    theater: str
    commander: str
    controller: str
    troop_type: str
    manpower: int
    supply: int
    morale: int
    training: int
    equipment: int
    arrears: int
    mobility: int
    loyalty: int
    status: str
    owner_power: str
    firearm_equipment: int = 0  # 火器装备 0-100：鸟铳/三眼铳，野战+守城
    cannon_equipment: int = 0   # 随军大炮门数(clamp 0-12)：红夷炮，守城/攻城，不利野战；城防炮另挂 region.cannon
    salary_rate: float = 0.0    # #44 名义月饷率(两/兵·月)：应发=ceil(manpower×rate/10000)，仅 ming；新军默认见 db 建军
    station_region: str = ""  # #659 结构化实际驻地=regions.id；station 仅人读细地点
    pay_source_region: str = ""
    province_pay_share: float = 0.0
    central_pay_share: float = 0.0
    province_pay_arrears: float = 0.0
    central_pay_arrears: float = 0.0
    is_tusi: int = 0
    self_funded_pay: int = 0
    mutiny_status: str = ""
    is_mutinied: int = 0
    mutiny_count: int = 0
    mutiny_probation: int = 0


@dataclass
class Building:
    id: str
    region_id: str
    name: str
    category: str          # 财政/军事/民生/科技/交通/内廷
    level: int             # 规模 1-5
    condition: int         # 完好 0-100，产出折算系数
    maintenance: int       # 每月维护费 万两
    risk: int              # 0-100
    output_metric: str     # 国库/内库/军备/民心 或 "" 表示纯叙事
    output_amount: int     # 每月产出量
    status: str


@dataclass
class Power:
    id: str
    name: str
    kind: str
    leader: str
    stance: str
    leverage: int
    satisfaction: int
    military_strength: int
    cohesion: int
    supply: int
    agenda: str
    status: str
    last_action: str = "尚无新动"
    aliases: str = ""


@dataclass
class OpeningLegacy:
    """开局即存在的负面帝国修正：永久 legacy（duration=-1），靠 clear_gate 程序判定消除。
    不立 issue、不进推演。见 content/opening_legacies.json 与 db.sync_opening_legacies。"""
    key: str
    name: str
    modifiers: Dict[str, object]
    narrative_hint: str
    clear_gate: Dict[str, str]
    clear_narrative: str = ""


@dataclass
class GameState:
    year: int = 1627
    period: int = 10
    turn: int = 1
    turn_phase: str = "summoning"  # summoning | reviewing | awaiting_decision | settling | issued —— 见本模块 TurnPhase
    ended: bool = False  # 结局已触发：游戏终结，拒绝继续召见/结算
    ending_status: str = ""  # 结局类型（context.ENDING_*），ended=True 时有值
    metrics: Dict[str, int] = field(
        default_factory=lambda: {
            "国库": 320,
            "内库": 440,
            "民心": 50,
            "皇威": 20,
        }
    )
    log: List[str] = field(default_factory=list)

    def clamp(self) -> None:
        for key, value in list(self.metrics.items()):
            if key in ECONOMY_ACCOUNTS:
                self.metrics[key] = max(0, value)
            else:
                self.metrics[key] = max(0, min(100, value))

    def next_period(self) -> None:
        self.turn += 1
        self.period += 1
        if self.period > 12:
            self.period = 1
            self.year += 1


@dataclass
class CourtContext:
    state: "GameState"
    db: "object"  # GameDB；用 object 注解避免 import db.py 造成环
    previous_summary: str = ""


def period_label(year: int, month: int) -> str:
    return f"{year}年{month}月"


# 年号纪年：西历年 → 天启/崇祯汉字年号。state.year 是西历（开局 1627=天启七年）；
# 崇祯改元逾年，元年=1628。章节记忆/邸报 title 单一真源，禁「崇祯{year}年」字面拼接。
_CN_DIGITS = "零一二三四五六七八九"
_CN_MONTH_ORDINAL = {
    1: "正", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六",
    7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二",
}
# 天启元年=1621；崇祯元年=1628（改元逾年，开局 1627 仍天启七年）。
_TIANQI_EPOCH_YEAR = 1621
_CHONGZHEN_EPOCH_YEAR = 1628


def _chinese_era_ordinal(n: int) -> str:
    """年号序数：1→元，2→二，…，10→十，11→十一，17→十七，20→二十。"""
    n = int(n)
    if n <= 0:
        raise ValueError(f"era ordinal must be positive, got {n}")
    if n == 1:
        return "元"
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" if n == 10 else f"十{_CN_DIGITS[n - 10]}"
    tens, ones = divmod(n, 10)
    head = f"{_CN_DIGITS[tens]}十"
    return head if ones == 0 else f"{head}{_CN_DIGITS[ones]}"


def reign_period_label(year: int, month: int) -> str:
    """西历年月 → 年号纪年呈现（天启七年十月 / 崇祯元年正月 / 崇祯二年三月）。

    映射：1621..1627 → 天启（1621=元年）；year≥1628 → 崇祯（1628=元年）；
    1621 前回落公历标签，不伪造年号。
    元年不写「1年」；月份用正/二/…/十二，与票面「十月」「正月」口径对齐。
    """
    y = int(year)
    m = int(month)
    if m not in _CN_MONTH_ORDINAL:
        raise ValueError(f"month must be 1..12, got {m}")
    if y >= _CHONGZHEN_EPOCH_YEAR:
        era = "崇祯"
        ordinal = y - _CHONGZHEN_EPOCH_YEAR + 1
    elif y >= _TIANQI_EPOCH_YEAR:
        era = "天启"
        ordinal = y - _TIANQI_EPOCH_YEAR + 1
    else:
        return f"公历{y}年{_CN_MONTH_ORDINAL[m]}月"
    return f"{era}{_chinese_era_ordinal(ordinal)}年{_CN_MONTH_ORDINAL[m]}月"


def monthly_amount(amount: int) -> int:
    # 全盘已按月度：base/maint/tax 都是月值，不再除 3。保留函数仅为兼容旧调用点（恒等）。
    return max(0, int(amount))
