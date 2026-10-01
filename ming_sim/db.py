"""GameDB：所有 SQLite 持久化。L3。

init_schema 建表，seed_static_data 从 GameContent 初始化静态盘面。
GameDB 持有 self.content（GameContent），seed 类方法从中读人物/地区/军队等。
"""

from __future__ import annotations
from ming_sim.entities.army.store import ArmyStore
from ming_sim.entities.building.store import BuildingStore
from ming_sim.entities.character_knowledge.store import CharacterKnowledgeStore
from ming_sim.entities.character.store import CharacterStore
from ming_sim.entities.social_class.store import ClassStore
from ming_sim.entities.faction.store import FactionStore
from ming_sim.entities.fiscal_container.store import FiscalContainerStore
from ming_sim.entities.issue.store import IssueStore
from ming_sim.entities.person_log.store import PersonLogStore
from ming_sim.entities.power.store import PowerStore
from ming_sim.entities.region.store import RegionStore
from ming_sim.entities.reign_state.store import ReignStateStore

import contextlib
from dataclasses import replace
import json
import logging
import math
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from ming_sim.applier import (
    atomic, connection_owns_transaction, load_stored_json, load_stored_list,
    load_stored_object, safe_json_dumps, sanitize_sqlite_text,
)
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SQL_IN
from ming_sim.assets import format_money, format_money_delta, format_wanliang_amount
from ming_sim.constants import (
    ARMY_FIELD_ALIASES, ARMY_FIELD_LABELS, ARMY_QUANTITY_FIELDS, ARMY_SCORE_FIELDS, ARMY_TEXT_FIELDS,
    BUILDING_CATEGORIES, BUILDING_FIELD_LABELS, BUILDING_OUTPUT_METRICS,
    BUILDING_QUANTITY_FIELDS, BUILDING_SCORE_FIELDS, BUILDING_TEXT_FIELDS,
    ECONOMY_ACCOUNTS, POWER_FIELD_LABELS, POWER_SCORE_FIELDS,
    POWER_FIELD_ALIASES, POWER_TEXT_FIELDS, MONEY_UNIT, REGION_FIELD_LABELS, REGION_QUANTITY_FIELDS,
    FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES, REGION_SCORE_FIELDS, REGION_TEXT_FIELDS,
    DOSSIER_LINK_TYPES, SALARY_RATE_ANCHOR, TURN_UNIT,
    DEFAULT_OPENING_PERIOD, DEFAULT_OPENING_YEAR,
)
from ming_sim.content import GameContent
from ming_sim.decree_vocabulary import (
    DOSSIER_ACTION_TYPES, DIRECTIVE_ACTION_TYPES, dossier_action_policy,
)
from ming_sim.entities.dossier import (
    DOSSIER_EXECUTION_OUTCOMES,
    DOSSIER_REPORT_ORIGIN_MONTHLY,
    DOSSIER_REPORT_ORIGIN_NS,
    DOSSIER_REPORT_ORIGIN_VERDICT,
    DOSSIER_SCHEMA_SQL,
    DOSSIER_STATUSES,
    PROMULGATION_BLOCKED_LAYERS,
    DossierStore,
    has_execution_surface,
    hydrate_dossier_row,
    normalize_dossier_mode,
)
from ming_sim.matching import match_army_id_from_text, match_region_id_from_text
from ming_sim.office_rank import canonical_office_title
from ming_sim.schema import ensure_core_schema
from ming_sim.exceptions import LLMContractError, OfficeAppointmentRejection
from ming_sim.intelligence import OFFICE_SLOTS
from ming_sim.models import (
    FRONT_HALF_DONE_PHASES, Character, Event, GameState, is_vassal_prince,
    loads_effect_dict, monthly_amount, period_label, reign_period_label,
)
from ming_sim.relations import SUMMON_EDGE_ORIGIN_PREFIX
from ming_sim.participant_roster import (
    PARTICIPANT_TIERS,
    load_participant_roster,
    participant_roster_names,
    project_execution_liability_parties,
)
from ming_sim.person_archive_contract import PERSON_TITLE_KINDS
from ming_sim.qualitative import (
    building_output_effect,
    building_qualitative_fields,
    city_defense_description,
    gentry_resistance_band,
    military_pressure_band,
    population_wan_kou_label,
    power_band,
    public_support_band,
    qualitative_band,
    satisfaction_band,
)
from ming_sim.relations import (
    bind_origin_round,
    credit_events_as_edges,
    normalize_evidence,
    validate_edge_kind,
)
from ming_sim.strict_types import (
    strict_int, validate_affected_parties, validate_rejection_verdict,
    validate_verdict_affected_parties,
)
from ming_sim.token_stats import tlog

logger = logging.getLogger(__name__)

# ADR 0088 / #648 / #1889：人口存储一律「人」（与 armies.manpower 同刻度）。
# 新档仍在 save_meta 落标；无标不再改判万人，也不再把 content 人口 ÷10⁴。
POPULATION_UNIT_PERSONS = "人"
_POPULATION_UNIT_KEY = "population_unit"

# 落库字段白名单（模块级常量化——避免在 apply_region_deltas / apply_army_deltas /
# create_armies_from_extraction 的内循环每项重算同一常量集合，cmr PR2 R1 gemini perf）。
_REGION_DIRECT_TUPLE = REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + REGION_TEXT_FIELDS
_REGION_DIRECT_SET = frozenset(_REGION_DIRECT_TUPLE)
_REGION_NUMERIC_SET = frozenset(REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS)
_ARMY_VALID_SET = frozenset(ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS + ARMY_TEXT_FIELDS)
_ARMY_PAY_SOURCE_DELTA_FIELDS = frozenset((
    "owner_power", "pay_source_region", "province_pay_share", "central_pay_share",
    "is_tusi", "self_funded_pay",
))
_ARMY_OWNER_TRANSITION_PAY_KEYS = (
    "pay_source_region", "province_pay_share", "central_pay_share",
    "is_tusi", "self_funded_pay",
)
_SENTINEL = object()  # transition_army_owner_power 可选饷源参数「未提供」哨兵

def _army_owner_transition_pay_kwargs(normalized: Mapping[str, object]) -> Dict[str, object]:
    """从规范化 delta 组装 transition_army_owner_power 饷源/自养 kwargs。

    键出现 → 实值；未出现 → _SENTINEL（adapter 回落行内 / 缺饷源 fail-loud）。
    """
    return {
        key: (normalized[key] if key in normalized else _SENTINEL)
        for key in _ARMY_OWNER_TRANSITION_PAY_KEYS
    }
_COMMITMENT_STOP_CONDITION_RE = re.compile(r"character\.[^.]+\.loyalty\s*(?:>=|>)\s*\d+")

def mutiny_loyalty_cap(mutiny_count: int, redemption_count: int = 0) -> int:
    """ADR 0025 D6 唯一军心上限真源。"""
    return max(60, min(100, 100 - 20 * int(mutiny_count) + 10 * int(redemption_count)))

def latched_army_field_effect_permitted(
    field: str,
    raw_value: object,
    *,
    effect_delta: int | None = None,
) -> bool:
    """#319 ADR 0025 D4①：latched 军字段-效果白名单（写缝与战略 preflight 共用）。

    - manpower：仅 raw 严格负
    - loyalty：raw 严格正，且若已算 post-modifier effect 则 effect 也须严格正
    - 其余字段：一律不准
    """
    if field == "manpower":
        try:
            return int(raw_value) < 0
        except (TypeError, ValueError):
            return False
    if field == "loyalty":
        try:
            if int(raw_value) <= 0:
                return False
        except (TypeError, ValueError):
            return False
        if effect_delta is None:
            return True
        return int(effect_delta) > 0
    return False

# #320 / ADR 0025 D2：extractor loyalty 软调单事件 |Δ| 上限（全路径、无豁免）。
LOYALTY_SOFT_ADJUST_MAX = 15

def fold_loyalty_alias_delta(raw_changes: Mapping[str, object]) -> int | None:
    """同军同事件 loyalty 规范键/别名合法整数净合计。

    仅合计 alias→loyalty 且合法整数的叶；bool/float/非 int 不并入（非法叶仍由调用方逐叶拒收）。
    无任何合法 loyalty 叶时返回 None。
    """
    loyalty_canonical_delta: int | None = None
    for raw_field, value in raw_changes.items():
        if ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip()) != "loyalty":
            continue
        try:
            if isinstance(value, bool) or isinstance(value, float):
                raise ValueError("非整数 delta")
            leaf = int(value)
        except (TypeError, ValueError):
            continue
        loyalty_canonical_delta = (
            leaf if loyalty_canonical_delta is None else loyalty_canonical_delta + leaf
        )
    return loyalty_canonical_delta

def compute_loyalty_soft_adjust(
    old: int,
    net_delta: int,
    *,
    net_pct: int = 0,
    mutiny_count: int = 0,
    redemption_count: int = 0,
) -> tuple[int, int]:
    """唯一 loyalty 软调纯计算真源。

    顺序：net → legacy pct → ±LOYALTY_SOFT_ADJUST_MAX → mutiny_loyalty_cap 上界
    → [0, cap] → (new_value, actual_delta)。写核与战略预检共用，禁止平行公式。
    """
    delta = int(net_delta)
    if net_pct:
        delta = GameDB.apply_legacy_pct(delta, int(net_pct))
    delta = max(-LOYALTY_SOFT_ADJUST_MAX, min(LOYALTY_SOFT_ADJUST_MAX, delta))
    upper_bound = mutiny_loyalty_cap(mutiny_count, redemption_count)
    new_value = max(0, min(upper_bound, int(old) + delta))
    return new_value, new_value - int(old)

def _seed_guilt_storage_value(value: object) -> str:
    """Serialize the content-layer guilt mapping into the existing DB TEXT column."""
    if isinstance(value, Mapping):
        if not value:
            return ""
        crime = str(value.get("crime") or "").strip()
        severity = str(value.get("severity") or "无").strip()
        return safe_json_dumps({"crime": crime, "severity": severity}, ensure_ascii=False)
    return str(value or "")

def _public_support_description(value: object) -> str:
    return "民心" + public_support_band(value)

def _unrest_description(value: object) -> str:
    return "动乱" + qualitative_band(value, ("平静", "有患", "不安", "升高", "已炽"))

def _secret_order_exclusion_targets(
    people: Iterable[str], offices: Iterable[str],
) -> Dict[str, List[str]]:
    """Keep caller targets separate from the resolved institution snapshot."""
    return {
        "people": list(dict.fromkeys(str(value) for value in people)),
        "offices": list(dict.fromkeys(str(value) for value in offices)),
    }

def _snapshot_secret_order_people(
    content: Any, explicit_people: Iterable[str], offices: Iterable[str],
) -> List[str]:
    """Freeze institution membership without changing target provenance.

    ``excluded_names`` is the durable blacklist snapshot used for transfer and
    later-publication semantics.  ``excluded_targets`` remains the caller's
    original people/offices request, so a reader can distinguish "this person"
    from "everyone holding this office" instead of reconstructing that intent
    from the expanded names.
    """
    names = []
    for raw_name in explicit_people:
        name = str(raw_name).strip()
        if not name:
            continue
        canonical = next((character.name for character in getattr(content, "characters", {}).values()
                          if name == character.name or name in (character.aliases or [])), name)
        names.append(canonical)
    names = list(dict.fromkeys(names))
    if not offices or content is None:
        return names
    for character in content.characters.values():
        if character.office_type in offices or character.office in offices or any(
            office and (office in str(character.office or "") or str(character.office or "") in office)
            for office in offices
        ):
            names.append(character.name)
    return list(dict.fromkeys(names))

_SECRET_OFFICE_TYPES = (
    "吏部", "户部", "礼部", "兵部", "刑部", "工部", "都察院", "大理寺", "通政司",
    "司礼监", "内阁", "东厂", "锦衣卫", "翰林院", "詹事府",
)
_SECRET_OFFICE_TITLE_SUFFIX_RE = re.compile(
    r"[\u4e00-\u9fff]{0,12}(?:首辅|次辅|大学士|阁臣|辅臣|尚书|侍郎|郎中|员外郎|主事|"
    r"巡抚|总督|总兵|督师|经略|提督|都御史|御史|侍读学士|侍讲学士|侍读|侍讲|"
    r"编修|检讨|修撰|庶吉士|庶常|少詹事|詹事|中允|赞善)$"
)

def _canonical_secret_exclusion_target(
    target: str, office_types: set[str], office_titles: set[str],
) -> tuple[str, str]:
    """Classify a secrecy target using the shipped registry before fallback vocabulary."""
    target = re.sub(r"(?:诸官|官员|诸司|诸人|上下|众人)$", "", target).strip()
    if target in office_titles:
        return "office", target
    if target in office_types:
        return "office", target
    if _SECRET_OFFICE_TITLE_SUFFIX_RE.fullmatch(target):
        return "office", target
    for office_type in sorted(office_types | set(_SECRET_OFFICE_TYPES), key=len, reverse=True):
        if target.startswith(office_type):
            return "office", office_type if target != office_type else target
    return "", target

def canonical_secret_order_exclusions(
    content: Any, explicit_people: Iterable[str], explicit_offices: Iterable[str], text: object,
) -> tuple[List[str], List[str]]:
    """Canonicalize structured extractor targets before staging or DB.

    Player prose is not a machine contract.  Only typed people/offices reach
    this boundary; roster aliases and office titles are canonicalized here.
    ``text`` remains accepted for callers that also pass the order body, but is
    deliberately not consumed.
    """
    del text
    people = _snapshot_secret_order_people(content, explicit_people, [])
    office_types = {str(character.office_type).strip() for character in getattr(content, "characters", {}).values()
                    if character.office_type}
    office_titles = {str(character.office).strip() for character in getattr(content, "characters", {}).values()
                     if character.office}
    offices = []
    for value in explicit_offices:
        kind, target = _canonical_secret_exclusion_target(str(value), office_types, office_titles)
        if kind == "office":
            offices.append(target)
    return list(dict.fromkeys(people)), list(dict.fromkeys(offices))

class ProvinceFiscalTickOutcome(NamedTuple):
    region_id: str
    result: Any
    error: Optional[BaseException]

_CENTRAL_ARMY_PAY_ARREARS_CONTAINER_KEY = "central_army_pay_arrears"

_STRUCTURAL_FISCAL_MINIMUMS = {
    "central_taicang_sink_loss_rate": 1,
    "central_jingyun_sink_loss_rate": 1,
}
_CENTRAL_LOSS_RATE_PAIRS = {
    "central_taicang_human_loss_rate": (
        "central_taicang_human_loss_rate",
        "central_taicang_sink_loss_rate",
    ),
    "central_taicang_sink_loss_rate": (
        "central_taicang_human_loss_rate",
        "central_taicang_sink_loss_rate",
    ),
    "central_jingyun_human_loss_rate": (
        "central_jingyun_human_loss_rate",
        "central_jingyun_sink_loss_rate",
    ),
    "central_jingyun_sink_loss_rate": (
        "central_jingyun_human_loss_rate",
        "central_jingyun_sink_loss_rate",
    ),
}

# #287 S1 seed values: province share : central share. The region is the pay-source
# province, not the physical station.
_ARMY_PAY_SOURCE_SEED: Dict[str, Tuple[str, float, float, bool]] = {
    "jingying": ("beizhili", 0.0, 1.0, False),
    "guanning": ("liaodong", 0.0, 1.0, False),
    "shanhaiguan": ("beizhili", 0.0, 1.0, False),
    "xuan_da": ("shanxi", 0.55, 0.45, False),
    "jizhen": ("beizhili", 0.20, 0.80, False),
    "denglai": ("shandong", 0.80, 0.20, False),
    "dongjiang": ("liaodong", 0.0, 1.0, False),
    "shaanxi_army": ("shaanxi", 0.65, 0.35, False),
    "nanjing_garrison": ("nanzhili", 1.0, 0.0, False),
    "fujian_navy": ("fujian", 1.0, 0.0, False),
    "guangdong_navy": ("guangdong", 1.0, 0.0, False),
    "southwest_tusi": ("", 0.0, 0.0, True),
}

def _approx_wanliang(amount: object) -> str:
    """奏报口吻的万两近似数；军饷欠是真钱，但玩家不看 DB 精确账格。"""
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "无欠饷"
    if value < 10:
        return "欠饷不足十万两"
    if value < 20:
        rounded = _round_half_up_to_step(value, 5)
    else:
        rounded = _round_half_up_to_step(value, 10)
    rounded = max(1, rounded)
    return f"欠饷约{rounded}万两"

def _round_half_up_to_step(value: float, step: int) -> int:
    return int(math.floor(value / step + 0.5) * step)

def _approx_pay_months(arrears: object, monthly_pay: object) -> str:
    try:
        arr = float(arrears or 0)
        pay = float(monthly_pay or 0)
    except (TypeError, ValueError):
        return ""
    if arr <= 0 or pay <= 0:
        return ""
    months = arr / pay
    if months < 1:
        return "，不足一月军饷"
    if months < 3:
        return "，约两月军饷"
    if months < 6:
        return "，数月军饷"
    if months < 12:
        return "，约半年军饷"
    years = int(round(months / 12.0))
    if years <= 1:
        return "，逾一年军饷"
    return f"，约{years}年军饷"

_ARMY_QUALITATIVE_WORDS: Dict[str, Tuple[str, str, str, str, str]] = {
    "supply": ("断绝", "匮乏", "吃紧", "尚可", "充足"),
    "morale": ("涣散", "低迷", "不振", "尚稳", "高昂"),
    "training": ("散漫", "生疏", "粗疏", "尚可", "精熟"),
    "equipment": ("残破", "简陋", "短缺", "尚可", "精良"),
    "mobility": ("迟滞", "缓慢", "受限", "尚可", "灵便"),
}

def _qualitative_army_stat(field: str, value: object) -> str:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        n = 0
    words = _ARMY_QUALITATIVE_WORDS.get(field, ("极低", "偏低", "中等", "尚可", "优良"))
    if n >= 80:
        word = words[4]
    elif n >= 60:
        word = words[3]
    elif n >= 40:
        word = words[2]
    elif n >= 20:
        word = words[1]
    else:
        word = words[0]
    return f"{ARMY_FIELD_LABELS.get(field, field)}：{word}"

def _army_arrears_report_text(row: sqlite3.Row, monthly_pay: object) -> str:
    return _approx_wanliang(row["arrears"]) + _approx_pay_months(row["arrears"], monthly_pay)

def _player_army_situation(row, monthly_pay: object) -> Dict[str, str]:
    """#321 玩家军心/士气/欠饷唯一投影：复用 derive + qualitative/arrears helper。

    mutiny_tier 六档：哗变/鼓噪/不满/一般/优秀/死忠。
    derive 非「正常」时直接复用其档名；仅「正常」再按 L 切一般/优秀/死忠。
    """
    from ming_sim.flows import derive_army_mutiny_state

    derived = derive_army_mutiny_state(row)
    if derived == "正常":
        try:
            loyalty = int(row["loyalty"] or 0)
        except (TypeError, ValueError):
            loyalty = 0
        if loyalty >= 80:
            mutiny_tier = "死忠"
        elif loyalty >= 70:
            mutiny_tier = "优秀"
        else:
            mutiny_tier = "一般"
    else:
        mutiny_tier = derived
    return {
        "mutiny_tier": mutiny_tier,
        "morale_text": _qualitative_army_stat("morale", row["morale"]),
        "arrears_text": _army_arrears_report_text(row, monthly_pay),
    }

def _is_commitment_stop_condition(resolve_condition: object) -> bool:
    return bool(_COMMITMENT_STOP_CONDITION_RE.fullmatch(str(resolve_condition or "").strip()))

def _has_stop_condition(stop_condition: object) -> bool:
    """Only structured gates count; writable condition strings are opaque text."""
    if isinstance(stop_condition, (dict, list)):
        return bool(stop_condition)
    raw = str(stop_condition or "").strip()
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        # insert_issue also accepts symbolic/free-text conditions. This predicate
        # distinguishes those from structured gates; it is not a JSON reader.
        return False
    return isinstance(parsed, (dict, list)) and bool(parsed)

def _optional_positive_dossier_id(raw: object, *, field: str) -> Optional[int]:
    """#658：typed dossier id 单权威——真正缺省→None；一旦出现只接正整数。

    拒 0/负/bool/float/数字字符串。target 与 backing 共吃，禁第二份 optional-positive。
    """
    if raw in (None, ""):
        return None
    value = strict_int(raw, accept_numeric_strings=False)
    if value <= 0:
        raise ValueError(f"{field} 非法 shape：{raw!r}")
    return value

def imperial_push_target_dossier_id(payload: object) -> Optional[int]:
    """#658：解析合法御笔强推 target_dossier_id；缺省 → None；坏 shape 响亮失败。

    capture / session.add / db.update / extract 共吃本函数——禁第二份 int>0 分支。
    Mapping 同时认 target_dossier_id 与抽取原键 目标案卷ID。
    """
    if isinstance(payload, Mapping):
        if "target_dossier_id" in payload:
            raw = payload.get("target_dossier_id")
        elif "目标案卷ID" in payload:
            raw = payload.get("目标案卷ID")
        else:
            return None
    else:
        raw = payload
    return _optional_positive_dossier_id(raw, field="target_dossier_id")

def parse_backing_dossier_id(raw: object) -> Optional[int]:
    """#658：处置 backing_dossier_id 单权威解析；缺省→None；坏 shape 响亮失败。

    首写 stage 与 durable apply 共吃；禁 generic as_int clamp 成「未提供」。
    """
    return _optional_positive_dossier_id(raw, field="backing_dossier_id")

def require_backing_dossier_id(db: Any, raw: object) -> Optional[int]:
    """解析 + 存在性：有值则案卷必须在册；供 stage 首写与 apply 复用。

    存在性经案卷 store 判（ADR 0151：GameDB 侧不留转发 facade，故不探
    `db.get_decree_dossier`——那条 getattr 兜底正是 facade 存在的证据）。
    """
    backing = parse_backing_dossier_id(raw)
    if backing is None:
        return None
    if db.dossiers.get(backing) is None:
        raise ValueError(f"backing_dossier_id 所指案卷不存在：{backing}")
    return backing

def directive_payload_has_ordinary_triad(payload: Mapping[str, object]) -> bool:
    """普通旨意结构化 triad：动作类型 + 目标类型 + 目标ID。"""
    return all(
        str(payload.get(key) or "").strip()
        for key in ("dossier_action_type", "target_kind", "target_id")
    )

def classify_directive_structured_kind(payload: Mapping[str, object]) -> str:
    """#658 旨意结构化互斥权威：'push' | 'ordinary' | 'empty'；并存响亮拒绝。

    extract / capture / staging / merge / ensure 共吃——禁第二份 triad↔target 判定。
    """
    has_push = imperial_push_target_dossier_id(payload) is not None
    has_triad = directive_payload_has_ordinary_triad(payload)
    if has_push and has_triad:
        raise ValueError(
            "旨意不得同时带普通结构化 triad 与御笔强推 target_dossier_id"
        )
    if has_push:
        return "push"
    if has_triad:
        return "ordinary"
    return "empty"

def directive_payload_admits_structured_write(payload: Mapping[str, object]) -> bool:
    """旨意可落库：普通 triad，或 #658 御笔强推 typed target（互斥）。"""
    return classify_directive_structured_kind(payload) != "empty"

def _coerce_deadline_months(raw: object, *, default: int = 0) -> int:
    """解析密令期限；显式 0 是合法值，不能被缺省兜底吞掉。"""
    if raw is None:
        return int(default)
    if isinstance(raw, bool):
        raise TypeError("deadline_months cannot be a boolean")
    if isinstance(raw, str):
        raise TypeError("deadline_months cannot be a string")
    if not isinstance(raw, (int, float)):
        raise TypeError("deadline_months must be a numeric type")
    try:
        deadline = int(raw)
    except (ValueError, OverflowError) as exc:
        raise TypeError("deadline_months must be a finite numeric type") from exc
    return max(0, min(deadline, 36))

def _new_army_historically_applied(it: dict) -> bool:
    """建军必填字段（#173 PR2 后仅剩 manpower——维护费退役、不再必填）：manpower int() 成功
    = 历史可活（cmr S2 r4 整项谓词；模块级——避免每个 new_armies 项重定义，PR2 R1 gemini perf）。"""
    try:
        int(it["manpower"])
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        # OverflowError：int(float("inf"/"-inf")) 不在 (TypeError,ValueError) 内（线上 R2
        # CodeRabbit major）→ inf manpower 历史即崩（致命），判定历史不可活=严格。
        return False

def _coerce_new_salary_rate(raw, default: float = SALARY_RATE_ANCHOR) -> float:
    """#44 新军名义月饷率健壮解析：缺省/None/bool/0/负/非数 一律落边军史实锚点 1.5。
    salary_rate<=0 = 有兵无饷率 = 免费军 = 正是 #44 要堵的白嫖（游戏无自给/屯田军概念）；
    原 `item.get(...) or 1.5` 只挡 0/None、漏负值（-1 经 army_needed rate<=0 → 0 成免费军，
    cmr r3 codex medium）。salary_rate 非必填，脏值不拒整军、兜底锚点。"""
    if isinstance(raw, bool) or raw is None:
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    # 非有限值（inf/-inf/nan）也落锚点：inf>0 为真会漏过、经 army_needed 的 ceil(manpower×inf/10000)
    # 抛 OverflowError 崩结算（线上 gemini high + coderabbit inf 探针）。salary_rate 非必填、脏值兜底锚点，
    # 不 fail-loud 拒整军（#44 cmr R3 定的设计：不为一个非关键余饷字段拒绝建军）。
    return v if (math.isfinite(v) and v > 0) else default

def _coerce_bool_flag(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    if isinstance(raw, (int, float)):
        return raw != 0
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "是", "土司", "自养", "自养军饷"}

def _coerce_pay_source_float(raw: object, *, default: float = 0.0) -> float:
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        raise ValueError("布尔值不是合法比例")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("非有限数")
    return value

# #9 派系势力联动（全重算，offset 锚定钦定基线）：
# leverage(faction) = clamp(0,100, offset + 当前在朝(active)成员官职权重和)
# 其中 offset = 钦定基线 − 开局校准时的权重和（开局时两者相等 → leverage==钦定基线，保开局平衡）。
# 核心退场→当前和降→leverage 降（修 #9）；起复/升迁→升。绝对重算每次从公式现算、不累加 → 无漂移。
# 只对朝堂博弈派系；外族(后金/蒙古/朝鲜)/后宫(中宫/嫔妃/宠妃)/宗室/流寇不握明朝官职、leverage 另义、不联动。
_LEVERAGE_FACTIONS = {"阉党", "东林", "皇党", "中立", "军队", "西学"}

# office_type 域权重（陡梯：顶层中枢压倒、长尾近零）。数值可调（因 offset 锚定，权重只决定
# 「变化幅度」不决定开局水平）；结构（顶层压倒 + 品级调制）是硬要求。
_OFFICE_LEVERAGE_WEIGHT = {
    "司礼监": 20, "内阁": 18,                                  # 批红 / 票拟 中枢
    "兵部": 12, "吏部": 12, "户部": 10, "边镇": 10,            # 部院 / 督师边镇
    "锦衣卫": 8, "东厂": 8, "都察院": 8, "六科": 8,             # 厂卫 / 言官监察
    "礼部": 5, "刑部": 5, "工部": 5,                           # 中层部务（六部齐全：刑部勿漏）
    "内臣": 4, "内廷": 4,                                       # 宫廷宦官（御马监/内官监等，与内臣同档）
    "翰林院": 2, "地方": 2, "外臣": 1,                         # 长尾
    # 后宫 / 宗藩 / 未仕 → 0（不在朝堂博弈或无实权）；office_type 不在表里 → 权重 0。
}

# 品级档 multiplier 已迁到 content/offices.json rank_rules（#562）：
# faction leverage 与破格检测共用 ming_sim.office_rank 查表，不再在此维护第二套词干 parser。

# 退场类状态(削职)——与 active 互斥（set_character_status 据此清空 office）。
_OUSTED_STATES = {"offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}

def _office_rank_multiplier(office: str, already_normalized: bool = False) -> float:
    """从 office 头衔字串解析品级 multiplier。唯一真源=offices.json rank_rules。

    逗号分隔的多职取已识别分项中的最高档；整串无 leverage 词干时落默认 1.0。
    already_normalized=True 时入参已是 normalize_office 结果，跳过重复 normalize。
    """
    from ming_sim.office_rank import office_leverage_multiplier

    text = office or ""
    normalized = text if already_normalized else normalize_office(text)
    return office_leverage_multiplier(normalized, already_normalized=True)

def _member_office_weight(office_type: str, office: str) -> float:
    """单个在朝成员的官职权重 = 域权重 × 品级档 multiplier。
    域权重取 office 头衔【各分项里最高】的 domain：兼职跨 domain 时不漏更高的那个——魏忠贤
    司礼监秉笔(批红 20)+东厂提督(8) → 20、来宗道 礼部尚书(5)+东阁大学士(内阁 18) → 18。
    按 offices.json 词干表（_office_type_from_table）确定性映射分项→office_type（无 LLM，可在
    recompute 热路安全调用）；office_type 桶作下限兜底（分项均无已知 domain 关键词时）。
    （只看 office_type 单桶会把九千岁误算成东厂 8——「九千岁退场影响小」之误，用户挑战修。）
    office 规范化后为空（无实职）→ 0（#9 cmr R2 finding#3：不让 _office_rank_multiplier('') 的
    默认 1.0 把空职算成满权重，堵「active 且 office 空但 office_type 非空」边界）。"""
    office_n = normalize_office(office)
    if not office_n.strip():
        return 0.0
    domain = _OFFICE_LEVERAGE_WEIGHT.get(office_type, 0)  # office_type 桶下限
    for part in (p.strip() for p in office_n.split(",") if p.strip()):
        w = _OFFICE_LEVERAGE_WEIGHT.get(_office_type_from_table(part), 0)
        if w > domain:
            domain = w
    if domain == 0:
        return 0.0
    # #9 R1 finding#5：office_n 已 normalize，直接复用、不让 _office_rank_multiplier 再 normalize 一次。
    return domain * _office_rank_multiplier(office_n, already_normalized=True)

def normalize_office(office: str) -> str:
    """官职多职统一为半角逗号分隔：旧「兼/兼掌/兼署」与全角「，」「、」一律归一逗号，
    去空分项、去重、保序。是 office 字段落库的唯一规范化入口——所有写 characters.office
    的路径都过它，保证去重/顶缺时能按逗号分项匹配。"""
    s = (office or "").strip()
    if not s:
        return ""
    s = s.replace("兼掌", ",").replace("兼署", ",").replace("兼", ",")
    s = s.replace("，", ",").replace("、", ",")
    seen: set = set()
    parts: List[str] = []
    for p in (x.strip() for x in s.split(",")):
        if p and p not in seen:
            seen.add(p)
            parts.append(p)
    return ",".join(parts)

COURT_OFFICE_TYPES = {"内阁", "吏部", "户部", "礼部", "兵部", "刑部", "工部"}
MINISTRY_OFFICE_TYPES = {"吏部", "户部", "礼部", "兵部", "刑部", "工部"}

_OFFICES_TABLE: Optional[Dict[str, object]] = None
_OFFICE_TYPE_LLM_CACHE: Dict[str, str] = {}

def _offices_table() -> Dict[str, object]:
    """加载 content/offices.json（明代职官→office_type 参考表），缓存。失败返回空表。"""
    global _OFFICES_TABLE
    if _OFFICES_TABLE is None:
        try:
            from ming_sim.assets import load_json_asset
            data = load_json_asset("offices.json")
            _OFFICES_TABLE = data if isinstance(data, dict) else {}
        except Exception as exc:
            # 注：文件缺失 / JSON 损坏会在 load_json_asset 直接 SystemExit fail-loud（核心内容
            # 不该静默回空表），不经此分支；这里只兜 import / 意外错误（gemini-code-assist cmr）。
            tlog(f"[content] offices.json 意外加载失败，回空表：{exc}")  # #14 surface
            _OFFICES_TABLE = {}
    return _OFFICES_TABLE

def _office_type_from_table(text: str) -> str:
    """按 offices.json priority 顺序，首个命中词干者胜。无命中返回 ''。"""
    for entry in _offices_table().get("priority", []) or []:
        if not isinstance(entry, dict):
            continue
        for stem in entry.get("stems", []) or []:
            if stem and stem in text:
                return str(entry.get("type") or "")
    return ""

def _office_type_via_llm(text: str, llm_config: Any = None) -> str:
    """表查不中（生造/罕见官名）时，CLI 后端在场则交 LLM 判 office_type（取 allowed_types）。
    否则返回 ''。结果按官名缓存，避免重复调用。"""
    try:
        from ming_sim.cli_backend import cli_backend_active, _run_backend_for_config
    except Exception:
        return ""
    if not cli_backend_active(llm_config):
        return ""
    if text in _OFFICE_TYPE_LLM_CACHE:
        return _OFFICE_TYPE_LLM_CACHE[text]
    allowed = _offices_table().get("allowed_types") or []
    allowed_set = set(allowed)
    prompt = (
        "你是明代职官分类器，不扮演、不解释。判断下面这个明朝官名/身份属于哪一类，"
        "只输出一个类型词（不要任何别的字），必须严格取自：" + "、".join(allowed) + "。\n"
        "官名：" + text + "\n类型："
    )
    out = ""
    try:
        raw, _ = _run_backend_for_config(prompt, llm_config, tag="office_infer")
        cand = (raw or "").strip().splitlines()[0].strip() if raw else ""
        out = cand if cand in allowed_set else ""
    except Exception:
        out = ""
    _OFFICE_TYPE_LLM_CACHE[text] = out
    return out

def infer_office_type_from_office(
    office: str, current_type: str = "", llm_config: Any = None, use_llm: bool = True
) -> str:
    """用 office 文本判 office_type：先查 offices.json 参考表（明制权威、确定），
    表查不中且 CLI 后端在场再交 LLM 判（生造官名），都不中落『待铨』。
    取代旧版那串临时正则词表（脆、漏）。外藩(后金/蒙古/朝鲜)按 power_id≠ming 另处理，不入此路。

    use_llm=False：跳过 LLM 兜底。表查不中时直接信传入的 current_type（content/DB 既定值，
    含朝堂六部类）原样保留，仅空 kind 落「待铨」。静态名册接档（seed_static_data）与每回合
    DB sync（_sync_offices_from_db_impl）专用：content/DB 的 office_type 即权威，逐人现拉
    codex 判属纯浪费（开局慢 5 分钟根因），且若沿用动态路径的「朝堂类表查不中→待铨」降级，
    会把动态任命已落库的朝堂类 office_type 在每回合 sync 时悄悄降级、内存与 DB 不一致
    （cmr R2 codex）。动态生造官名（任免/issues）仍走默认 use_llm=True（保留 LLM 兜底 +
    朝堂类无确证则落待铨的谨慎语义）。"""
    kind = (current_type or "").strip()
    if kind == "后宫":
        return kind
    text = normalize_office(office)
    if not use_llm and kind:
        # Seed/sync callers carry a declared, durable office type, and that
        # declaration is authoritative even when there is no current office
        # string to match against — a 罢居/罢免 person has office='' yet still
        # belongs to a court knowledge domain (content states it outright).
        # A compound title such as “司礼监秉笔太监、东厂提督” can match more
        # than one table keyword; letting the first match overwrite the
        # declaration silently projects the person through the wrong knowledge
        # domain.
        return kind
    if not text:
        return "待铨" if kind in COURT_OFFICE_TYPES or not kind else kind
    t = _office_type_from_table(text)
    if t:
        return t
    if not use_llm:
        # Static callers without a declaration still use the reference table.
        return kind or "待铨"
    t = _office_type_via_llm(text, llm_config)
    if t:
        return t
    return "待铨" if kind in COURT_OFFICE_TYPES or not kind else kind

def resolve_office_type_preserving_title(
    office: str,
    declared: str,
    fallback: str = "",
    llm_config: Any = None,
    use_llm: bool = True,
) -> str:
    """名分守卫的单一入口：显式声明的名分（declared ∈ PERSON_TITLE_KINDS）是权威身份，
    office 文本反推不得覆盖它——例 office='诸生'（同为 offices.json 生员词干）会被
    infer_office_type_from_office 改写成 '生员'，令下游名分守卫失效、误建 offices 父行、
    写 character_offices 脏行（#1059 codex）。仅当**无显式名分声明**时才回落 declared or
    fallback 走 infer（授实职即脱名分——既有名分仅作 fallback、不短路，照常重推）。

    过去这条守卫散在 set_character_office / add_character / apply_appointment /
    apply_office_appointment / 事件闸预览 / preflight noop 六处各写各的，名分透传只覆到
    DB 写侧、漏在建 Character 与内存 re-infer 的接缝（#1059 codex l6h/l6k）。收敛到此一点，
    任何 seam 只要「有显式声明 + 可能 infer」就调它，名分透传不再逐 seam 漏。"""
    declared = (declared or "").strip()
    if declared in PERSON_TITLE_KINDS:
        return declared
    return infer_office_type_from_office(office, declared or fallback, llm_config, use_llm=use_llm)

# #567 / ADR 0054：押解实抵 clamp 界（北极星 30 两面值 → 无护 15-18 / 有护 22-25）。
# 代码只 clamp；软判提案落在界内原样收。比例相对 30 锚定，保证有护下界 > 无护上界。
_GRANT_ARRIVAL_SCALE = 30
_GRANT_ARRIVAL_BARE = (15, 18)
_GRANT_ARRIVAL_ESCORT = (22, 25)
_GRANT_ESCORT_RELATIONS = frozenset({"护卫", "稽核"})

def grant_arrival_bounds(ordered_amount: int, *, escorted: bool) -> Tuple[int, int]:
    """返回 (arrived_lo, arrived_hi)，含端点；ordered<=0 时 (0, 0)。"""
    ordered = int(ordered_amount)
    if ordered <= 0:
        return (0, 0)
    lo_n, hi_n = _GRANT_ARRIVAL_ESCORT if escorted else _GRANT_ARRIVAL_BARE
    lo = (ordered * lo_n) // _GRANT_ARRIVAL_SCALE
    hi = (ordered * hi_n) // _GRANT_ARRIVAL_SCALE
    if hi < lo:
        hi = lo
    if hi > ordered:
        hi = ordered
    return (lo, hi)

def clamp_grant_arrival_amount(
    ordered_amount: int, proposed_arrived: int, *, escorted: bool,
) -> int:
    """P2：软判提案 → 代码只 clamp 到护行口径界内。

    提案须已由调用方解析为 int；非法量字段在 record 侧逐项拒收，不入本函数。
    合法无提案中位默认仅经 record_monthly_grant_reconciliations 内联路径。
    """
    lo, hi = grant_arrival_bounds(int(ordered_amount), escorted=escorted)
    proposed = int(proposed_arrived)
    return max(lo, min(hi, proposed))


def _decision_json_fields(row: Any) -> Tuple[list, object, list]:
    """pending_decisions 三列 JSON。空白是空名单 / 未选；在场损坏即拒。"""
    options = load_stored_list(row["options_json"], label="options_json")
    prior = load_stored_list(row["prior_options_json"], label="prior_options_json")
    choice = load_stored_json(row["choice_json"], label="choice_json", blank=None)
    return options, choice, prior


class GameDB:
    def __init__(self, path: str, content: Optional[GameContent] = None, llm_config: Any = None):
        self.path = path
        # 静态设定来源。过渡期 content 可省略，省略时自行加载；
        # 步骤7 起由 GameSession 统一传入同一份 GameContent。
        self.content = content if content is not None else GameContent.load()
        self.llm_config = llm_config
        # check_same_thread=False：流式颁诏/召对 worker 与轮询读共用同一连接。
        # cached_statements=0：关掉 CPython sqlite3 statement cache，避免 3.12/3.13
        # 共享连接并发 fetch 的 InterfaceError（CPython #118172）。
        # factory=_SuspendableConnection：使 atomic() 能暂停全库 commit（ADR 0008 决定 2/8）。
        # 暂停标志默认 off，下面 init_schema 建表照常提交。
        from ming_sim.applier import _SuspendableConnection
        # #1749：connect 成功后 PRAGMA/init_schema 任一步失败须关连接，保留原异常；
        # GameSession 在 GameDB 返回前 self.db 仍为 None，无法代为清理半成品。
        self.conn = sqlite3.connect(
            path,
            check_same_thread=False,
            cached_statements=0,
            factory=_SuspendableConnection,
        )
        try:
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            if int(self.conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
            # 遗产修正符缓存：legacy_modifiers 在落账热路径被频繁调用，缓存聚合结果，
            # 仅在 active 遗产集变化（insert_legacy / expire_legacies）时失效。
            self._legacy_mod_cache: Optional[Dict[str, object]] = None
            self.init_schema()
        except Exception:
            try:
                self.conn.close()
            except Exception:
                logger.exception("GameDB init failed; conn.close failed")
            raise

    def owns_transaction(self) -> bool:
        """Return True when this GameDB call site should commit its own writes."""
        return connection_owns_transaction(self.conn)

    def init_schema(self) -> None:
        # game_state（朝局头）与 metrics（余额真源）的建表与写读口归 reign_state store
        # （#1889 按职责拆出）。放在最前：下方的标记读写都要先有这两张表。
        # 人物公私经历与知识来源两张账的建表与写读口归 character_knowledge store
        # （#1889 按职责拆出）。同样放最前：init 早段就会把带参与人的 issues 投影成
        # 共享知识来源，那时这两张表必须已在。
        from ming_sim.entities.character_knowledge import CharacterKnowledgeStore
        CharacterKnowledgeStore.ensure_schema(self.conn)
        self.character_knowledge = CharacterKnowledgeStore(self.conn)
        from ming_sim.entities.reign_state import ReignStateStore
        ReignStateStore.ensure_schema(self.conn)
        self.reign = ReignStateStore(self.conn)
        # 引擎自有的建表（表/视图/索引）归 ming_sim.schema（#1889 按职责拆出）；
        # 上面两个 store 各自的 DDL 由 store 自己带，这里不持第二份定义。
        ensure_core_schema(self.conn)
        # 案卷 store 的 schema 刚随上面脚本建好；此处即构造，后续 init_schema 的
        # 任何回填/校验都走它（ADR 0151：GameDB 侧不留转发 facade）。
        self.dossiers = DossierStore(self.conn)
        from ming_sim.entities.character import CharacterStore
        from ming_sim.entities.region import RegionStore
        from ming_sim.entities.army import ArmyStore
        self.characters = CharacterStore(self.conn)
        self.regions = RegionStore(self.conn)
        self.armies = ArmyStore(self.conn)
        from ming_sim.entities.building import BuildingStore
        from ming_sim.entities.faction import FactionStore
        from ming_sim.entities.fiscal_container import FiscalContainerStore
        from ming_sim.entities.issue import IssueStore
        from ming_sim.entities.power import PowerStore
        from ming_sim.entities.social_class import ClassStore
        self.buildings = BuildingStore(self.conn)
        self.factions = FactionStore(self.conn)
        self.fiscal_containers = FiscalContainerStore(self.conn)
        self.issues = IssueStore(self.conn)
        self.powers = PowerStore(self.conn)
        self.classes = ClassStore(self.conn)
        # 当前字段都在 ming_sim.schema 的 CREATE 里。不再为旧档 ALTER 补列。
        self._ensure_office_type_parents()
        self._ensure_event_parents()
        self._apply_region_city_levels()
        self.character_knowledge.register_issue_sources()
        self.conn.execute("DROP TABLE IF EXISTS dossier_progress_reports")
        from ming_sim.entities.person_log import PersonLogStore
        PersonLogStore.ensure_schema(self.conn)
        self.person_logs = PersonLogStore(self.conn)
        from ming_sim.entities.textual_fact import TextualFactStore
        from ming_sim.entities.affair import AffairStore
        TextualFactStore.ensure_schema(self.conn)
        self.textual_facts = TextualFactStore(self.conn)
        from ming_sim.entities.staged_declaration import StagedDeclarationStore
        StagedDeclarationStore.ensure_schema(self.conn)
        self.staged_declarations = StagedDeclarationStore(self.conn)
        AffairStore.ensure_schema(self.conn)
        self.affairs = AffairStore(self.conn)
        from ming_sim.entities.record_store import (
            ChatMessageStore,
            MonthOpenSnapshotStore,
            ResolveContextStore,
            TurnReportStore,
        )
        from ming_sim.entities.fiscal_container.config import FiscalConfigStore

        self.fiscal_config = FiscalConfigStore(self.conn)
        self.chat_messages = ChatMessageStore(self.conn)
        self.turn_reports = TurnReportStore(self.conn)
        self.resolve_contexts = ResolveContextStore(self.conn)
        self.month_open_snapshots = MonthOpenSnapshotStore(self.conn)
        self.conn.commit()
        self.init_fiscal_config()

    def init_fiscal_config(self) -> None:
        """从 content/fiscal_config.json（self.content.fiscal_items）seed 财政科目目录。

        base/rate 单位为【月度】万两/%。科目目录与元数据全走 JSON 设定（铁律：设定走 JSON）；
        新档加税源只改 JSON。

        #1889：只做**建库时整体 seed 一次**。已有 `__schema_version` 行的库一律不碰——
        玩家裁撤/裁改过的科目读档后保持原样（不被 JSON 复活），同版本存读档照常。
        旧档逐版差量升级（`_FISCAL_MIGRATIONS` 阶梯）已随旧形状兼容拆除：owner 明确
        不考虑旧存档兼容，也不得删除既存存档——既有存档仍可打开读用，只是不再被改写。
        """
        items = list(self.content.fiscal_items)
        if not items or "__schema_version" not in items[0]:
            raise SystemExit("init_fiscal_config: fiscal_items 缺 __schema_version 头，中止。")
        schema_version = int(items[0]["__schema_version"])
        rows = items[1:]

        if self.fiscal_config.row("__schema_version") is not None:
            return
        for rec in rows:
            self.fiscal_config.insert({
                "key": str(rec["key"]), "value": int(rec["value"]),
                "kind": str(rec["kind"]), "note": str(rec["note"]),
                "budget_role": str(rec.get("budget_role", "fixed")),
                "account": str(rec.get("account", "")),
                "direction": str(rec.get("direction", "")),
                "display": str(rec.get("display", "")),
                "sort_order": int(rec.get("order", 9999)),
            })
        self.fiscal_config.insert({
            "key": "__schema_version", "value": schema_version, "kind": "meta",
            "note": "财政默认值大版本号；建库时整体 seed 一次",
        })
        self.conn.commit()

    def iter_budget_items(self) -> "List[Dict[str, object]]":
        """返回 budget_role=fixed 的 base 科目（含 account/direction/display/sort_order）。

        flows.compute_budget_lines 据此动态生成固定收支预算行——加新税源不必改代码。
        每项配套的 *_rate 由调用方按 stem 自取（rate 项 budget_role 同 fixed 但 kind=rate，
        不在本列表里）。dynamic 项（田赋/辽饷/盐税/商税/皇庄）走省级公式，这里不返回。
        """
        rows = self.fiscal_config.budget_items()
        return [
            {
                "key": str(r["key"]),
                "account": str(r["account"]),
                "direction": str(r["direction"]),
                "display": str(r["display"]),
                "note": str(r["note"] or ""),
                "origin_ref": str(r["origin_ref"] or ""),
            }
            for r in rows
        ]

    def get_fiscal_config(self) -> Dict[str, int]:
        return self.fiscal_config.values()

    def fiscal_config_minimum_value(self, key: str) -> Optional[int]:
        raw = str(key or "").strip()
        if raw in _STRUCTURAL_FISCAL_MINIMUMS:
            return _STRUCTURAL_FISCAL_MINIMUMS[raw]
        stem = self._stem_of(raw)
        if not stem:
            return None
        return (
            _STRUCTURAL_FISCAL_MINIMUMS.get(f"{stem}_base")
            or _STRUCTURAL_FISCAL_MINIMUMS.get(f"{stem}_rate")
        )

    def is_structural_fiscal_config_key(self, key: str) -> bool:
        return self.fiscal_config_minimum_value(key) is not None

    def fiscal_config_loss_rate_pair(self, key: str) -> Optional[Tuple[str, str]]:
        raw = str(key or "").strip()
        pair = _CENTRAL_LOSS_RATE_PAIRS.get(raw)
        if pair is not None:
            return pair
        stem = self._stem_of(raw)
        if not stem:
            return None
        return (
            _CENTRAL_LOSS_RATE_PAIRS.get(f"{stem}_base")
            or _CENTRAL_LOSS_RATE_PAIRS.get(f"{stem}_rate")
        )

    def validate_fiscal_config_values(self, values: Dict[str, int]) -> None:
        if not values:
            return
        cfg = self.get_fiscal_config()
        overlay = dict(cfg)
        normalized: Dict[str, int] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key or "").strip()
            value = int(raw_value)
            minimum = self.fiscal_config_minimum_value(key)
            if minimum is not None and value < minimum:
                raise ValueError(f"fiscal_config.{key} 不得低于结构地板 {minimum}")
            pair = _CENTRAL_LOSS_RATE_PAIRS.get(key)
            if pair is not None and (value < 0 or value > 100):
                raise ValueError(f"fiscal_config.{key} 须在 0..100")
            normalized[key] = value
            overlay[key] = value

        checked_pairs = set()
        for key in normalized:
            pair = _CENTRAL_LOSS_RATE_PAIRS.get(key)
            if pair is None or pair in checked_pairs:
                continue
            checked_pairs.add(pair)
            human_key, sink_key = pair
            human = int(overlay.get(human_key, 0) or 0)
            sink = int(overlay.get(sink_key, 0) or 0)
            if human + sink > 100:
                raise ValueError(f"{human_key}+{sink_key} 不得超过 100%")

    def validate_fiscal_config_value(self, key: str, value: int) -> None:
        self.validate_fiscal_config_values({key: value})

    def set_fiscal_config(self, key: str, value: int, commit: bool = True) -> None:
        owns_transaction = self.owns_transaction() if commit else False
        self.validate_fiscal_config_value(key, value)
        self.fiscal_config.set_values({key: value})
        if commit and owns_transaction:
            self.conn.commit()

    def set_fiscal_config_batch(self, values: Dict[str, int], commit: bool = True) -> None:
        owns_transaction = self.owns_transaction() if commit else False
        normalized = {str(k or "").strip(): int(v) for k, v in values.items()}
        self.validate_fiscal_config_values(normalized)
        self.fiscal_config.set_values(normalized)
        if commit and owns_transaction:
            self.conn.commit()

    def create_fiscal_item(
        self,
        key: str,
        account: str,
        direction: str,
        display: str,
        init_value: int,
        note: str = "",
        origin_ref: str = "",
        turn: int = 0,
        beyond_intent: object = 0,
        commit: bool = True,
    ) -> Optional[str]:
        """LLM 推演中凭空新立一个月固定收支项（budget_role=fixed）。

        落 base+rate 两行：`<stem>_base`=init_value、`<stem>_rate`=100。
        既存 base key 直接返回 None（不覆盖，由 fiscal_changes 调增量）。
        返回新建的 base key；冲突或非法返回 None。元数据走 fixed 预算目录，
        flows.iter_budget_items 下{月}起自动遍历落账——零代码加新税种／新月俸。
        """
        # stem 归一与 remove_fiscal_item 同用 _stem_of（剥 _base/_rate 双后缀,
        # cmr S3 r3）：只剥 _base 时 key='田赋_rate' 查成 田赋_rate_base 漏撞既有
        # rate 行,建出冒牌科目。
        stem = self._stem_of(key)
        if not stem:
            return None
        base_key = f"{stem}_base"
        rate_key = f"{stem}_rate"
        # 存在性须覆盖 base+rate 双键（cmr S3 r2 codex）：田赋等 dynamic 税默认只有
        # _rate 行,只查 base 会放行「田赋_base」,第二条 INSERT 撞 rate 键 PK 崩整月。
        # 语义与 remove_fiscal_item 的 base-or-rate 对称。
        if self.fiscal_config.has_any((base_key, rate_key)):
            return None
        sort_order = self.fiscal_config.next_sort_order()
        for item_key, value, kind, item_note in (
            (base_key, max(0, init_value), "base", note),
            (rate_key, 100, "rate", f"{display}实收率%"),
        ):
            self.fiscal_config.insert({
                "key": item_key, "value": value, "kind": kind, "budget_role": "fixed",
                "account": account, "direction": direction, "display": display,
                "sort_order": sort_order, "note": item_note, "origin_ref": origin_ref,
            })
        # #1260：base+rate 两行 creations 同旗（any() 消费者安全；计数型会双计——勿据此改计数语义）。
        beyond_flag = self.coerce_beyond_intent_flag(beyond_intent)
        for item_key, value, kind in (
            (base_key, max(0, init_value), "base"), (rate_key, 100, "rate"),
        ):
            self.fiscal_config.append_history("create", {
                "turn": int(turn), "key": item_key, "value": value, "kind": kind,
                "origin_ref": origin_ref, "reason": note[:240], "beyond_intent": beyond_flag,
            })
        if commit:
            self.conn.commit()
        return base_key

    # dynamic 税科目 → regions.fiscal 子字段映射。
    # 读 region.fiscal（不读 fiscal_config 的 base），故对这些 key 做裁撤/调额必须同步改
    # 各省 fiscal 字段才真生效——否则只动目录不动钱（账目与叙事脱节）。
    #   田赋无独立字段（=tax_per_turn 减其余三税的残差），裁撤走 tax_per_turn 压低；
    #   皇庄收入真读 fiscal_config.皇庄_base，裁撤/调额改 config 即生效，不在本表。
    _DYNAMIC_REGION_FIELD = {
        "辽饷": "liao_xiang", "盐税": "salt_tax", "商税": "commerce_tax",
    }

    def _stem_of(self, key: str) -> str:
        # 单层剥后缀;剥后仍带后缀 = 多重后缀垃圾 key（田赋_rate_base），返 "" 标记
        # 非法——归一化它两头都危险：create 漏撞建幻影科目（cmr S3 r4），remove 把
        # 垃圾 key 归一到真 stem 误删科目+清零各省实收（cmr S3 r5,不可逆）。
        # create/remove 对 stem 为空一律 return None = 拒收留痕。
        if key.endswith("_base") or key.endswith("_rate"):
            key = key[:-5]
            if key.endswith("_base") or key.endswith("_rate"):
                return ""
        return key

    def apply_dynamic_fiscal_scale(self, stem: str, ratio: float, commit: bool = True) -> int:
        """按 ratio 缩放所有省 regions.fiscal 中该 dynamic 税字段（辽饷/盐税/商税）。

        ratio=0 即彻底罢废（字段归零）；0<ratio<1 即按比例削减。田赋走 _scale_tian_fu。
        返回被改动的省数。皇庄不在此（走 fiscal_config）。命中映射外的 stem 返回 0。
        """
        field = self._DYNAMIC_REGION_FIELD.get(stem)
        if field is None:
            return 0
        touched = 0
        for row in RegionStore(self.conn).read_apply_dynamic_fiscal_scale():
            fiscal: dict = load_stored_object(row["fiscal"], label='fiscal')
            old = int(fiscal.get(field, 0) or 0)
            if old <= 0:
                continue
            new = max(0, round(old * ratio))
            if new == old:
                continue
            fiscal[field] = new
            self.regions.update(str(row["id"]), {"fiscal": json.dumps(fiscal, ensure_ascii=False)})
            touched += 1
        if touched and commit:
            self.conn.commit()
        return touched

    def settle_province_tick(
        self, region_id: str, actions: Optional[List[Dict[str, Any]]] = None
    ):
        """省级月度财政 settle_tick 的 DB 桥（#66 slice2）：读 regions.fiscal['settle'] 的
        开账 st + 月参 p → 跑 settle_tick → 写回 new_st。返回 FiscalTickResult。

        **港口锁**（fiscal_tick.py §港口锁 / ADR 0008）：settle_tick 对坏输入(ValueError)/
        守恒破(FiscalConservationError) 一律 raise，异常在下方 UPDATE **之前**抛出 → FAIL
        tick 绝不持久化（毒态不钉进存档）。本方法只写 conn、不自带 commit——提交交调用方
        事务边界（slice3 的 applier.atomic 全有或全无）控制；异常上抛由其回滚。

        settle_tick 纯读 st（不就地改），故无需深拷贝；new_st 是全新 dict，覆盖回 settle.st。
        官民田/隐田（清丈重分类）只写进 settle.st，不同步顶层 registered_land/hidden_land——
        财政实收由 substrate hub 读取基座。
        """
        row = RegionStore(self.conn).read_settle_province_tick((region_id,))
        if row is None:
            raise ValueError(f"region {region_id!r} 不存在，无法 settle_tick")
        fiscal = load_stored_object(row["fiscal"], label='fiscal')
        return self._settle_province_tick_from_fiscal(region_id, fiscal, actions or [])

    def _current_settle_turn(self) -> int:
        """#653 override 期限判定用的当前绝对 turn（game_state 单行真源；无行=0＝永不到期）。"""
        row = ReignStateStore(self.conn).read_current_settle_turn()
        return int(row["turn"]) if row is not None and row["turn"] is not None else 0

    def settle_ming_province_substrate_ticks(
        self,
        actions_by_region: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        p_overrides_by_region: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ProvinceFiscalTickOutcome]:
        """一次扫描 Ming 省 fiscal payload 并推进已有 settle 基座。

        动态 shadow spine 用这个批量桥，避免 selector 先解析、单省 bridge 再 SELECT/解析。
        合法但无 settle 的 Ming 省按旧语义出列。持久 fiscal JSON 损坏直接拒绝。
        容器/settle st/p 与 settle_tick 的 ValueError/守恒错误作为 outcome.error 返回。
        其它异常继续上抛。
        """
        from .fiscal_tick import FiscalConservationError

        actions_by_region = actions_by_region or {}
        p_overrides_by_region = p_overrides_by_region or {}
        outcomes: List[ProvinceFiscalTickOutcome] = []
        rows = RegionStore(self.conn).read_settle_ming_province_substrate_ticks()
        for row in rows:
            region_id = str(row["id"])
            fiscal = load_stored_object(row["fiscal"], label=f"{region_id}.fiscal")
            if "settle" not in fiscal:
                continue
            try:
                result = self._settle_province_tick_from_fiscal(
                    region_id,
                    fiscal,
                    actions_by_region.get(region_id, []),
                    p_overrides_by_region.get(region_id),
                )
            except (ValueError, FiscalConservationError) as exc:
                outcomes.append(ProvinceFiscalTickOutcome(region_id, None, exc))
                continue
            outcomes.append(ProvinceFiscalTickOutcome(region_id, result, None))
        return outcomes

    def _settle_province_tick_from_fiscal(
        self,
        region_id: str,
        fiscal: object,
        actions: List[Dict[str, Any]],
        p_overrides: Optional[Dict[str, Any]] = None,
    ):
        from .fiscal_tick import settle_tick

        if not isinstance(fiscal, dict):  # fiscal JSON 非 dict（null/list）→ ValueError，否则 .get 抛 AttributeError 逃逸隔离（cmr R3 gemini）
            raise ValueError(f"region {region_id!r} fiscal 非字典")
        settle = fiscal.get("settle")
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            raise ValueError(f"region {region_id!r} 无 settle 财政基座（缺 st/p）")
        pay_rows = self._derive_region_army_pay_due(region_id, settle)
        tick_p = settle["p"]
        if p_overrides:
            tick_p = dict(tick_p)
            tick_p.update(p_overrides)
        # ── #653 / ADR 0090：偿还序 override ＋ 折发系数读取端（r2/r3 表示法）──
        # 无在位 override 键 → resolve 返 None → 零合并，结算逐字节走默认路径（回归不破）。
        from ming_sim.pay_order import resolve_pay_order_overrides
        overrides = resolve_pay_order_overrides(
            self.get_fiscal_config(), region_id, self._current_settle_turn()
        )
        if overrides is not None:
            tick_p = dict(tick_p)
            tick_p["due_order"] = list(overrides.due_order)
            tick_p["arrears_order"] = list(overrides.arrears_order)
            if overrides.haircut_bp:
                tick_p["due_haircut_bp"] = dict(overrides.haircut_bp)
        result = settle_tick(settle["st"], tick_p, actions)  # raise→下方不执行（港口锁）
        if pay_rows:
            self._apply_region_army_pay_tick(pay_rows, result)
        settle["st"] = result.new_st
        if pay_rows:
            self._reconcile_region_army_pay_container(region_id, settle)
        self.regions.update(region_id, {"fiscal": json.dumps(fiscal, ensure_ascii=False)})
        self._record_claim_flow_logs(region_id, result)
        return result

    def _record_claim_flow_logs(self, region_id: str, result: Any) -> None:
        """#653 F2.3（owner 拍板 r5）：省级结算桥同事务补记 官俸欠/宗禄欠 当回合
        NewDebt/Repaid 流量——复用现有结算留痕载体 region_logs（禁新表/平行推算器/
        第二 ledger），restore E2E 可恢复。军饷欠不经此缝（已有 per-source army 对账
        双累加器＋army_logs 留痕，0023）；零流量不写行。本方法只写 conn，提交归调用方
        事务边界（与 settle UPDATE 同事务、全有或全无）。"""
        breakdown = result.breakdown or {}
        new_debt = breakdown.get("NewDebt") or {}
        repaid = breakdown.get("Repaid") or {}
        state_row = ReignStateStore(self.conn).read_record_claim_flow_logs()
        if state_row is None:
            state = self.load_state("")
            log_turn, log_year, log_period = state.turn, state.year, state.period
        else:
            log_turn = int(state_row["turn"])
            log_year = int(state_row["year"])
            log_period = int(state_row["period"])
        origin_ref = f"region:{region_id}:settle_tick"
        for claim in ("官俸欠", "宗禄欠"):
            for flow, source in (("NewDebt", new_debt), ("Repaid", repaid)):
                try:
                    amount = float(source.get(claim, 0) or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                if not math.isfinite(amount) or abs(amount) <= 1e-9:
                    continue
                old_v = float(result.new_st.get(claim, 0) or 0)
                # 流量方向：NewDebt 增欠、Repaid 偿还；region_logs.delta 记有符号流量，
                # old/new_value 记月末 CLAIM 存量两端（留痕语义与其余 region_logs 一致）。
                delta = amount if flow == "NewDebt" else -amount
                self.regions.append_log({
                    "turn": log_turn,
                    "year": log_year,
                    "period": log_period,
                    "region_id": region_id,
                    "field": f"settle_{claim}_{flow}",
                    "old_value": str(old_v - delta),
                    "new_value": str(old_v),
                    "delta": delta,
                    "reason": (
                        f"{TURN_UNIT}省池结算{'新增欠' if flow == 'NewDebt' else '偿旧欠'}"
                        f"{format_wanliang_amount(amount)}万两"
                    ),
                    "actor": "户部",
                    "origin_ref": origin_ref,
                })

    def scale_tian_fu(self, ratio: float, commit: bool = True) -> int:
        """田赋无独立字段（=tax_per_turn 减辽饷/盐税/商税的残差）。按 ratio 缩放田赋部分：
        新 tax_per_turn = 三税之和 + 田赋残差×ratio。ratio=0 即罢田赋（仅留三税基）。
        返回被改动的省数。"""
        touched = 0
        for row in RegionStore(self.conn).read_scale_tian_fu():
            fiscal: dict = load_stored_object(row["fiscal"], label='fiscal')
            others = (int(fiscal.get("liao_xiang", 0) or 0)
                      + int(fiscal.get("salt_tax", 0) or 0)
                      + int(fiscal.get("commerce_tax", 0) or 0))
            tax = int(row["tax_per_turn"])
            tian_fu = max(0, tax - others)
            new_tax = others + max(0, round(tian_fu * ratio))
            if new_tax == tax:
                continue
            self.regions.update(str(row["id"]), {"tax_per_turn": new_tax})
            touched += 1
        if touched and commit:
            self.conn.commit()
        return touched

    def remove_fiscal_item(
        self, key: str, commit: bool = True, *, origin_ref: str = "",
        reason: str = "", turn: int = 0, beyond_intent: object = 0,
    ) -> Optional[str]:
        """彻底裁撤一个月固定收支项（罢税/裁俸）：删 base+rate 两行。

        完全放开——含 dynamic（田赋/辽饷/盐税/商税/皇庄），后果玩家自负。
        - fixed 项：删目录条目即停止逐月落账。
        - dynamic 税（辽饷/盐税/商税）：实收走 region.fiscal，故同步把各省该字段归零；
          田赋走 tax_per_turn 压到仅留三税基；皇庄收入读 fiscal_config，删 config 即停。
          这样「永久罢辽饷」当真停收，不再只动目录不动钱。
        删不存在的项返回 None。返回被删的 base key（按 stem 归一）。
        """
        stem = self._stem_of(key)
        if not stem:
            return None
        base_key = f"{stem}_base"
        rate_key = f"{stem}_rate"
        if (
            self.fiscal_config_loss_rate_pair(base_key) is not None
            or self.fiscal_config_loss_rate_pair(rate_key) is not None
        ):
            return None
        if base_key in _STRUCTURAL_FISCAL_MINIMUMS or rate_key in _STRUCTURAL_FISCAL_MINIMUMS:
            return None
        # 存在性查 base 或 rate 任一——田赋只有 田赋_rate（无 base），但仍是可裁撤的 dynamic 项。
        if not self.fiscal_config.has_any((base_key, rate_key)):
            return None
        # The live catalogue cannot retain provenance after DELETE.  Preserve the
        # removed rows in a narrow append-only audit so origin -> removal is a
        # single indexed lookup rather than an inference from unrelated logs.
        # #1260：INSERT...SELECT 显式列清单 + beyond_intent 常量（禁 SELECT * 位置漂移）。
        beyond_flag = self.coerce_beyond_intent_flag(beyond_intent)
        self.fiscal_config.remove_items(
            (base_key, rate_key), turn=int(turn), origin=origin_ref,
            reason=reason[:240], beyond=beyond_flag,
        )
        # dynamic 税：同步罢废各省实收字段（皇庄走 config 不在此）。
        if stem in self._DYNAMIC_REGION_FIELD:
            self.apply_dynamic_fiscal_scale(stem, 0.0, commit=commit)
        elif stem == "田赋":
            self.scale_tian_fu(0.0, commit=commit)
        if commit:
            self.conn.commit()
        return base_key


    # 城市等级 0-5（静态，史实分级；未列出的地区默认 0=游牧/孤岛/边荒）。
    # 用途：城防大炮上限(city_level×8) + 将来经济/内政。1627 实况，非现代省份概念。
    _CITY_LEVEL_TIERS = {
        "beizhili": 5,                                          # 京师·四聚之首
        "nanzhili": 4, "zhejiang": 4,                           # 江南经济心脏/陪都
        "shenyang_liaoyang": 4, "korea": 4, "japan": 4,         # 后金盛京/朝鲜汉城/日本江户
        "huguang": 3, "guangdong": 3, "fujian": 3,             # 汉口/佛山(四聚)·月港海贸
        "shandong": 2, "jiangxi": 2, "henan": 2, "shanxi": 2,  # 中等省
        "sichuan": 2, "shaanxi": 2, "liaodong": 2,             # 陕西旱灾衰/辽东宁锦设防
        "guangxi": 1, "guizhou": 1, "yunnan": 1,               # 边远省
        "jianzhou": 1, "taiwan": 1,                            # 后金兴京小堡/荷据小据点
    }

    def _apply_region_city_levels(self) -> None:
        """按史实分级写各 region 的 city_level（静态，故每次加载校准即可；未列出者保持默认 0）。"""
        for rid, level in self._CITY_LEVEL_TIERS.items():
            self.regions.update(rid, {"city_level": int(level)}, touch=False)

    def apply_region_cannon(self, state: "GameState", region_id: str, delta: int) -> int:
        """改某地城防大炮门数(城头红夷炮)。上限 = city_level×8；clamp [0, cap]。返回新值。
        全局严格：引用未入库地区抛错，不静默。"""
        row = RegionStore(self.conn).read_apply_region_cannon((region_id,))
        if row is None:
            raise ValueError(f"城防炮引用未入库地区 '{region_id}'")
        cap = int(row["city_level"]) * 8
        new_value = max(0, min(cap, int(row["cannon"]) + int(delta)))
        self.regions.update(region_id, {"cannon": new_value})
        return new_value

    def table_has_rows(self, table: str) -> bool:
        row = self.conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None

    def _ensure_office_type_parents(self) -> None:
        """Materialize every declared/referenced office type before FK-checked writes."""
        title_kinds = tuple(PERSON_TITLE_KINDS)
        placeholders = ",".join("?" for _ in title_kinds)
        CharacterStore(self.conn).write_ensure_office_type_parents_owned(title_kinds, placeholders)
        for office_type in sorted(self._canonical_office_types()):
            self._ensure_office_type_parent(office_type)
        # #1889：原此处每回合把 character_offices.office_type 镜像回 characters
        # （第二写口的记账机），随该列删除一并去掉。

    def _canonical_office_types(self) -> set[str]:
        # 名分（PERSON_TITLE_KINDS）按契约不入官职体系：静态 seed 人物的 office_type 可能是名分，
        # 若混进 canonical 集，_ensure_office_type_parents 会在删除名分父行后又把它 rematerialize
        # 成 offices 父行（#1058 接缝回归）。在唯一定义点排除，兼作 _ensure_office_type_parent 校验
        # 的防御——名分永不是合法父类。
        return (
            set(self.content.office_definitions)
            | {
                str(character.office_type).strip()
                for character in self.content.characters.values()
                if str(character.office_type).strip()
            }
            | {
                str(office_type).strip()
                for office_type in (_offices_table().get("allowed_types") or [])
                if str(office_type).strip()
            }
        ) - set(PERSON_TITLE_KINDS)

    def _ensure_office_type_parent(self, office_type: str) -> None:
        office_type = str(office_type or "").strip()
        if not office_type:
            return
        if CharacterStore(self.conn).read_ensure_office_type_parent((office_type,)) is not None:
            return
        if office_type not in self._canonical_office_types():
            raise ValueError(f"未定义官类 '{office_type}'")
        definition = self.content.office_definitions.get(office_type, {})
        CharacterStore(self.conn).write_ensure_office_type_parent((
                office_type,
                int(definition.get("power", 0)),
                int(definition.get("responsibility", 0)),
                int(definition.get("corruption_risk", 0)),
            ))
    def _record_character_office(
        self,
        name: str,
        office: str,
        office_type: str,
        source: str,
        region_id: str = "",
    ) -> None:
        """写实职备档。听用候铨等非实职不覆盖既有历史；实职则 upsert，与当前名分无关。

        ``region_id`` is the appointment's jurisdiction seat (一次任职), never location.
        """
        from ming_sim.office_rank import _is_substantive_office

        if not _is_substantive_office(office, office_type):
            return
        if office_type not in PERSON_TITLE_KINDS:
            self._ensure_office_type_parent(office_type)
        seat = str(region_id or "").strip()
        if office_type not in self._LOCAL_ARCHIVE_OFFICE_TYPES:
            seat = ""
        tenure = str(getattr(self.conn, "_appointment_tenure", "真除") or "真除")
        dossier_id = int(getattr(self.conn, "_materializing_dossier_id", 0) or 0)
        self.characters.upsert_office(
            name=name,
            office_title=office,
            source=source,
            dossier_id=dossier_id or None,
            appointment_tenure=tenure,
            region_id=seat,
        )
        if dossier_id > 0:
            self.characters.insert_office_change(
                name=name,
                office_title=office,
                office_type=office_type,
                source=source,
                dossier_id=dossier_id,
                appointment_tenure=tenure,
            )

    def _ensure_event_parents(self) -> None:
        event_ids = {
            str(event.id).strip()
            for event in (*self.content.events, *self.content.seed_events)
            if str(event.id).strip()
        }
        for event_id in sorted(event_ids):
            self._ensure_event_parent(event_id)

    def _ensure_event_parent(self, event_id: str) -> None:
        event_id = str(event_id or "").strip()
        if not event_id:
            return
        if IssueStore(self.conn).read_ensure_event_parent((event_id,)) is not None:
            return
        event = next(
            (
                candidate
                for candidate in (*self.content.events, *self.content.seed_events)
                if str(candidate.id) == event_id
            ),
            None,
        )
        if event is None:
            raise ValueError(f"未定义事件 '{event_id}'")
        IssueStore(self.conn).write_ensure_event_parent((
                event_id,
                str(event.title),
                str(event.kind),
                str(event.summary),
                int(event.urgency),
                int(event.severity),
                int(event.credibility),
                json.dumps(event.interests, ensure_ascii=False),
                json.dumps(event.audiences, ensure_ascii=False),
            ))

    @property
    def population_unit(self) -> str:
        """人口核算一律「人」。无标或旧万人标不再改写读写刻度（#1889）。"""
        return POPULATION_UNIT_PERSONS

    def _mark_population_unit_persons(self) -> None:
        """新档 classes 首次 seed 时落持久人口单位标「人」（commit 由 seed_static_data 末尾统一提交）。"""
        self.conn.execute(
            "INSERT OR REPLACE INTO save_meta (key, value) VALUES (?, ?)",
            (_POPULATION_UNIT_KEY, POPULATION_UNIT_PERSONS),
        )

    def seed_static_data(self) -> None:
        """Seed the opening world from content（#1889：实现归 ming_sim/opening_seed）。"""
        from ming_sim.opening_seed import seed_opening_world

        seed_opening_world(self)

    def list_office_vacancies(self) -> List[Dict[str, object]]:
        """Return the static督抚职位 view with current holders from characters."""
        rows = CharacterStore(self.conn).read_list_office_vacancies()
        return [dict(row) for row in rows]

    def _initialize_army_pay_source_spine(self, is_fresh_armies_seed: bool) -> None:
        """Fresh content seed writes province/central arrears once.

        An existing army ledger keeps its splits. Re-seeding must not
        recompute them from the lump-sum arrears column.
        """
        if not is_fresh_armies_seed:
            return
        rows = ArmyStore(self.conn).read_initialize_army_pay_source_spine()
        for row in rows:
            army_id = str(row["id"])
            owner = str(row["owner_power"] or "")
            content_source = str(row["pay_source_region"] or "")
            content_province_share = float(row["province_pay_share"] or 0)
            content_central_share = float(row["central_pay_share"] or 0)
            content_is_tusi = bool(row["is_tusi"])
            content_self_funded = bool(row["self_funded_pay"])
            has_content_pay_source = bool(
                content_source
                or content_province_share
                or content_central_share
                or content_is_tusi
                or content_self_funded
            )
            if has_content_pay_source:
                source = content_source
                province_share = content_province_share
                central_share = content_central_share
                is_tusi = content_is_tusi
                self_funded = content_self_funded
            else:
                source, province_share, central_share, is_tusi = _ARMY_PAY_SOURCE_SEED.get(
                    army_id, ("", 0.0, 0.0, False)
                )
                self_funded = bool(is_tusi)
            old_arrears = float(self.content.armies[army_id].arrears or 0)
            if owner != "ming" or self_funded:
                if self_funded and old_arrears > 0:
                    seed_state = GameState()
                    self.armies.append_log({
                        "turn": seed_state.turn,
                        "year": seed_state.year,
                        "period": seed_state.period,
                        "army_id": army_id,
                        "field": "arrears",
                        "old_value": str(old_arrears),
                        "new_value": "0.0",
                        "delta": -old_arrears,
                        "reason": "自养核销：土司/自养军欠饷不并入朝廷饷源双累加器",
                        "actor": "system",
                    })
                province_arrears = central_arrears = 0.0
                source = ""
                province_share = central_share = 0.0
            else:
                self._validate_pay_source_values(
                    army_id, owner, source, province_share, central_share,
                    False, False, 0.0, 0.0,
                )
                self._require_valid_pay_source_region(army_id, source)
                province_arrears = old_arrears * province_share
                central_arrears = old_arrears * central_share
            self.armies.update(
                army_id,
                {
                    "pay_source_region": source,
                    "province_pay_share": province_share,
                    "central_pay_share": central_share,
                    "province_pay_arrears": province_arrears,
                    "central_pay_arrears": central_arrears,
                    "is_tusi": 1 if is_tusi else 0,
                    "self_funded_pay": 1 if self_funded else 0,
                },
                touch=False,
            )
        self._reconcile_all_army_pay_source_regions()
        self._reconcile_central_army_pay_arrears_container()
        self.assert_army_pay_source_container_conservation()

    def get_central_army_pay_arrears_container(self) -> float:
        row = FiscalContainerStore(self.conn).read_get_central_army_pay_arrears_container((_CENTRAL_ARMY_PAY_ARREARS_CONTAINER_KEY,))
        return float(row["value"] or 0.0) if row is not None else 0.0

    def _reconcile_central_army_pay_arrears_container(self) -> float:
        total = ArmyStore(self.conn).read_reconcile_central_army_pay_arrears_container()["total"]
        value = float(total or 0.0)
        self.fiscal_containers.replace(
            _CENTRAL_ARMY_PAY_ARREARS_CONTAINER_KEY,
            value,
            "中央军饷欠账容器：Σ非自养明军 central_pay_arrears",
        )
        return value

    def _province_army_pay_container_total(self) -> float:
        total = 0.0
        rows = RegionStore(self.conn).read_province_army_pay_container_total()
        for row in rows:
            try:
                fiscal = load_stored_object(row["fiscal"], label='fiscal')
            except (TypeError, ValueError) as exc:
                raise ValueError(f"region {row['id']} fiscal JSON 非法，无法校验军饷容器守恒") from exc
            settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
            if settle is None:
                continue
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                raise ValueError(f"region {row['id']} settle.st 非法，无法校验军饷容器守恒")
            total += float(settle["st"].get("军饷欠", 0) or 0.0)
        return total

    def _has_complete_province_pay_containers(self) -> bool:
        rows = ArmyStore(self.conn).read_has_complete_province_pay_containers()
        for row in rows:
            region_id = str(row["pay_source_region"] or "")
            region = RegionStore(self.conn).read_require_valid_pay_source_region((region_id,))
            if region is None or str(region["controlled_by"] or "") != "ming":
                return False
            fiscal = load_stored_object(
                region["fiscal"], label=f"region {region_id} fiscal",
            )
            settle = fiscal.get("settle")
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                return False
        return True

    def assert_army_pay_source_container_conservation(self) -> None:
        exempt_bad = ArmyStore(self.conn).read_assert_army_pay_source_container_conservation()
        if exempt_bad is not None:
            raise ValueError(
                "army "
                f"{exempt_bad['id']} 自养/非明军双累加器必须为 0"
            )
        province_source_rows = ArmyStore(self.conn).read_assert_army_pay_source_container_conservation_id_pay_source_region()
        for province_source in province_source_rows:
            self._require_valid_pay_source_region(
                str(province_source["id"]),
                str(province_source["pay_source_region"] or ""),
            )
        derived_bad = ArmyStore(self.conn).read_assert_army_pay_source_container_conservation_id_arrears_province_pay_arrears_central_pay_arrears()
        if derived_bad is not None:
            expected = float(derived_bad["province_pay_arrears"] or 0.0) + float(
                derived_bad["central_pay_arrears"] or 0.0
            )
            raise ValueError(
                "军饷欠派生合计破："
                f"army={derived_bad['id']} arrears={derived_bad['arrears']} "
                f"province+central={expected}"
            )
        central_container = self.get_central_army_pay_arrears_container()
        row = ArmyStore(self.conn).read_assert_army_pay_source_container_conservation_COALESCE_SUM_province_pay_arrears_0_AS_province_total_COALESCE_SU()
        province_total = float(row["province_total"] or 0.0)
        central_total = float(row["central_total"] or 0.0)
        army_total = float(row["army_total"] or 0.0)
        if abs(central_container - central_total) > 1e-6:
            raise ValueError(
                f"中央军饷欠账容器守恒破：container={central_container} Σcentral={central_total}"
            )
        if not self._has_complete_province_pay_containers():
            return
        province_container = self._province_army_pay_container_total()
        if abs(province_container - province_total) > 1e-6:
            raise ValueError(
                "省级军饷欠容器守恒破："
                f"container={province_container} "
                f"Σprovince={province_total}"
            )
        expected_total = army_total
        if abs((province_container + central_container) - expected_total) > 1e-6:
            raise ValueError(
                "双容器守恒破："
                f"Σcontainer={province_container + central_container} "
                f"Σarmy={army_total}"
            )

    def _validate_pay_source_values(
        self,
        army_id: str,
        owner_power: str,
        pay_source_region: str,
        province_share: float,
        central_share: float,
        is_tusi: bool,
        self_funded: bool,
        province_arrears: float,
        central_arrears: float,
    ) -> None:
        for label, value in (
            ("province_pay_share", province_share),
            ("central_pay_share", central_share),
            ("province_pay_arrears", province_arrears),
            ("central_pay_arrears", central_arrears),
        ):
            if not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"army {army_id} {label} 非法：{value!r}")
        exempt = owner_power != "ming" or is_tusi or self_funded
        if exempt:
            if abs(province_share) > 1e-9 or abs(central_share) > 1e-9:
                raise ValueError(f"army {army_id} 自养/非明军饷源比例必须为 0")
            if abs(province_arrears) > 1e-9 or abs(central_arrears) > 1e-9:
                raise ValueError(f"army {army_id} 自养/非明军双累加器必须为 0")
            return
        if not pay_source_region:
            raise ValueError(f"army {army_id} 明军须有 pay_source_region")
        if abs((province_share + central_share) - 1.0) > 1e-9:
            raise ValueError(f"army {army_id} 饷源比例和必须为 1")

    def _require_valid_pay_source_region(self, army_id: str, pay_source_region: str) -> None:
        row = RegionStore(self.conn).read_require_valid_pay_source_region((pay_source_region,))
        if row is None:
            raise ValueError(f"army {army_id} pay_source_region 未入库：{pay_source_region}")
        if str(row["controlled_by"] or "") != "ming":
            raise ValueError(f"army {army_id} pay_source_region 非明控省：{pay_source_region}")
        try:
            fiscal = load_stored_object(row["fiscal"], label='fiscal')
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"army {army_id} pay_source_region 财政基座 JSON 非法：{pay_source_region}"
            ) from exc
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            raise ValueError(f"army {army_id} pay_source_region 无 settle st/p 基座：{pay_source_region}")

    def transition_army_owner_power(
        self,
        state: GameState,
        row: sqlite3.Row,
        new_owner: str,
        *,
        reason: str,
        actor: str,
        event_id: object = None,
        edict_id: int | None = None,
        origin_ref: str = "",
        require_origin: bool = False,
        pay_source_region: object = _SENTINEL,
        province_pay_share: object = _SENTINEL,
        central_pay_share: object = _SENTINEL,
        is_tusi: object = _SENTINEL,
        self_funded_pay: object = _SENTINEL,
        latched_escape: str | None = None,
        raw_item: Dict[str, object] | None = None,
    ) -> List[Dict[str, object]]:
        """唯一生产 owner_power 转出口（ADR 0025 D5/D7 + #318）。

        同事务顺序：核销欠饷 → 清 is_mutinied/probation → 改 owner。
        空来源对 1/2 振 latched 军 owner-OUT = 拒收；仅 latched_escape='third_strike'
        （确定性第 3 振）可转出。mutiny_count>=3 不得回 ming。
        """
        changes: List[Dict[str, object]] = []
        army_id = str(row["id"])
        old_owner = str(row["owner_power"] or "").strip()
        owner_power = str(new_owner or "").strip()
        item = raw_item if raw_item is not None else {"army_id": army_id}

        if not owner_power:
            changes.append({
                "army": row["name"], "field": "owner_power",
                "rejected": True, "category": "invalid_enum",
                "reason": "owner_power 不得为空",
                "item": item,
            })
            return changes

        owner_exists = PowerStore(self.conn).read_transition_army_owner_power((owner_power,))
        if owner_exists is None:
            changes.append({
                "army": row["name"], "field": "owner_power",
                "rejected": True, "category": "hallucinated_id",
                "reason": f"army_delta owner_power '{owner_power}' 不在 powers 表",
                "item": item,
            })
            return changes

        if owner_power == old_owner:
            return changes

        # 空来源：1/2 振 latched 倒戈一律拒收（#318 无 trusted_event_id 生产路径）
        if bool(row["is_mutinied"]) and latched_escape != "third_strike":
            changes.append({
                "army": row["name"], "field": "owner_power",
                "rejected": True, "category": "invalid_enum",
                "reason": "哗变锁存军空来源不得改归属（仅第3振确定性转流寇）",
                "item": item,
            })
            return changes

        mutiny_count = int(row["mutiny_count"] or 0)
        if owner_power == "ming" and mutiny_count >= 3:
            changes.append({
                "army": row["name"], "field": "owner_power",
                "rejected": True, "category": "invalid_enum",
                "reason": "mutiny_count>=3 永久流寇不可回明；招安须另建新军",
                "item": item,
            })
            return changes

        old_source = str(row["pay_source_region"] or "")
        try:
            if pay_source_region is _SENTINEL:
                pay_source_region_val = str(row["pay_source_region"] or "").strip()
            else:
                pay_source_region_val = str(pay_source_region or "").strip()
            if province_pay_share is _SENTINEL:
                province_share = _coerce_pay_source_float(row["province_pay_share"])
            else:
                province_share = _coerce_pay_source_float(province_pay_share)
            if central_pay_share is _SENTINEL:
                central_share = _coerce_pay_source_float(row["central_pay_share"])
            else:
                central_share = _coerce_pay_source_float(central_pay_share)
            if is_tusi is _SENTINEL:
                is_tusi_val = bool(row["is_tusi"])
            else:
                is_tusi_val = _coerce_bool_flag(is_tusi)
            if self_funded_pay is _SENTINEL:
                self_funded_val = bool(row["self_funded_pay"])
            else:
                self_funded_val = _coerce_bool_flag(self_funded_pay)

            province_arrears = float(row["province_pay_arrears"] or 0)
            central_arrears = float(row["central_pay_arrears"] or 0)

            exempt = owner_power != "ming" or is_tusi_val or self_funded_val
            if exempt:
                pay_source_region_val = ""
                province_share = central_share = 0.0
                province_arrears = central_arrears = 0.0
            self._validate_pay_source_values(
                army_id, owner_power, pay_source_region_val, province_share, central_share,
                is_tusi_val, self_funded_val, province_arrears, central_arrears,
            )
            if pay_source_region_val:
                self._require_valid_pay_source_region(army_id, pay_source_region_val)
        except (TypeError, ValueError) as exc:
            changes.append({
                "army": row["name"], "field": "pay_source",
                "rejected": True, "category": "invalid_enum",
                "reason": f"army_delta 饷源字段非法：{exc}",
                "item": item,
            })
            return changes

        origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
        if origin_error:
            changes.append({
                "army": row["name"], "field": "owner_power", **origin_error,
                "item": item,
            })
            return changes

        old_values = {
            "owner_power": old_owner,
            "pay_source_region": old_source,
            "province_pay_share": float(row["province_pay_share"] or 0),
            "central_pay_share": float(row["central_pay_share"] or 0),
            "is_tusi": int(row["is_tusi"] or 0),
            "self_funded_pay": int(row["self_funded_pay"] or 0),
            "province_pay_arrears": float(row["province_pay_arrears"] or 0),
            "central_pay_arrears": float(row["central_pay_arrears"] or 0),
            "arrears": float(row["arrears"] or 0),
            "is_mutinied": int(row["is_mutinied"] or 0),
            "mutiny_probation": int(row["mutiny_probation"] or 0),
        }
        new_values = {
            "owner_power": owner_power,
            "pay_source_region": pay_source_region_val,
            "province_pay_share": province_share,
            "central_pay_share": central_share,
            "is_tusi": 1 if is_tusi_val else 0,
            "self_funded_pay": 1 if self_funded_val else 0,
            "province_pay_arrears": province_arrears,
            "central_pay_arrears": central_arrears,
            "arrears": province_arrears + central_arrears,
            "is_mutinied": 0,
            "mutiny_probation": 0,
        }
        if exempt:
            new_values["arrears"] = 0.0

        # ① 核销欠饷（先于清 latch / 改 owner）
        wrote_writeoff = (
            old_owner == "ming"
            and owner_power != "ming"
            and float(old_values["arrears"] or 0) > 1e-9
        )
        if wrote_writeoff:
            self.armies.append_log({
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "army_id": army_id,
                "field": "arrears",
                "old_value": str(old_values["arrears"]),
                "new_value": "0.0",
                "delta": -float(old_values["arrears"]),
                "reason": f"owner易主核销：{reason}",
                "event_id": event_id,
                "edict_id": edict_id,
                "actor": actor,
                "origin_ref": origin_ref,
            })

        # ②+③ 清 latch/probation + 改 owner（唯一生产 UPDATE owner_power）
        self.armies.update(army_id, {
            "owner_power": owner_power,
            "pay_source_region": pay_source_region_val,
            "province_pay_share": province_share,
            "central_pay_share": central_share,
            "is_tusi": 1 if is_tusi_val else 0,
            "self_funded_pay": 1 if self_funded_val else 0,
            "province_pay_arrears": new_values["province_pay_arrears"],
            "central_pay_arrears": new_values["central_pay_arrears"],
            "is_mutinied": 0,
            "mutiny_probation": 0,
        })

        log_fields = [
            "is_mutinied", "mutiny_probation",
            "owner_power", "pay_source_region", "province_pay_share", "central_pay_share",
            "is_tusi", "self_funded_pay", "province_pay_arrears", "central_pay_arrears",
        ]
        if not wrote_writeoff:
            log_fields.append("arrears")
        for field in log_fields:
            if old_values[field] == new_values[field]:
                continue
            self.armies.append_log({
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "army_id": army_id,
                "field": field,
                "old_value": str(old_values[field]),
                "new_value": str(new_values[field]),
                "reason": reason,
                "event_id": event_id,
                "edict_id": edict_id,
                "actor": actor,
                "origin_ref": origin_ref,
            })
            changes.append({
                "army": row["name"], "field": field,
                "label": ARMY_FIELD_LABELS.get(field, field),
                "old": old_values[field], "new": new_values[field],
                "delta": None, "reason": reason,
            })

        if old_source != pay_source_region_val:
            self._reconcile_army_pay_source_region_container(old_source)
        self._reconcile_army_pay_source_region_container(pay_source_region_val)
        self._reconcile_central_army_pay_arrears_container()
        self.assert_army_pay_source_container_conservation()
        return changes

    def _apply_army_pay_source_delta(
        self,
        state: GameState,
        event: Event,
        edict_id: int | None,
        actor: str,
        row: sqlite3.Row,
        raw_changes: Dict[str, object],
        reason: str,
        changes: List[Dict[str, object]],
        origin_ref: str = "",
        require_origin: bool = False,
    ) -> None:
        normalized = {
            ARMY_FIELD_ALIASES.get(str(k).strip(), str(k).strip()): v
            for k, v in raw_changes.items()
        }
        present = _ARMY_PAY_SOURCE_DELTA_FIELDS.intersection(normalized)
        if not present:
            return

        army_id = str(row["id"])
        # owner 变更一律经唯一 adapter（含空来源 latched 拒收 / 第3振不可回明）
        if "owner_power" in normalized:
            proposed_owner = str(normalized.get("owner_power") or "").strip()
            if proposed_owner != str(row["owner_power"] or "").strip():
                changes.extend(self.transition_army_owner_power(
                    state,
                    row,
                    proposed_owner,
                    reason=reason,
                    actor=actor,
                    event_id=event.id,
                    edict_id=edict_id,
                    origin_ref=origin_ref,
                    require_origin=require_origin,
                    **_army_owner_transition_pay_kwargs(normalized),
                    raw_item={"army_id": army_id, "changes": raw_changes},
                ))
                return

        # #319 ADR 0025 D4①：先拒脏输入（fail-loud / invalid_enum），校验通过后
        # 再对 latched 军非 owner 饷源字段静默 no-op。写缝在主环 latch 门之前、
        # 且主环对 _ARMY_PAY_SOURCE_DELTA_FIELDS 直接 continue，故既有字段效果门
        # 看不到本缝；在此复用同一 latch 语义，不新开平行门/第二 adapter。
        # 真 owner 变更已由上方 return。禁止把 latch return 前移到校验之前。
        old_source = str(row["pay_source_region"] or "")
        owner_power = str(row["owner_power"] or "").strip()
        pay_source_region = str(normalized.get("pay_source_region", row["pay_source_region"]) or "").strip()
        try:
            province_share = _coerce_pay_source_float(
                normalized.get("province_pay_share", row["province_pay_share"])
            )
            central_share = _coerce_pay_source_float(
                normalized.get("central_pay_share", row["central_pay_share"])
            )
            is_tusi = (
                _coerce_bool_flag(normalized["is_tusi"])
                if "is_tusi" in normalized else bool(row["is_tusi"])
            )
            self_funded = (
                _coerce_bool_flag(normalized["self_funded_pay"])
                if "self_funded_pay" in normalized else bool(row["self_funded_pay"])
            )
            province_arrears = float(row["province_pay_arrears"] or 0)
            central_arrears = float(row["central_pay_arrears"] or 0)
            exempt = owner_power != "ming" or is_tusi or self_funded
            exempt_by_ming_flag = (
                owner_power == "ming"
                and not bool(row["is_tusi"])
                and not bool(row["self_funded_pay"])
                and (is_tusi or self_funded)
            )
            if exempt_by_ming_flag and (province_arrears + central_arrears) > 1e-9:
                raise ValueError(
                    "明军有欠饷时不得仅以自养/土司改隶清空饷源；须先走补饷或显式核销"
                )
            if exempt:
                pay_source_region = ""
                province_share = central_share = 0.0
                province_arrears = central_arrears = 0.0
            self._validate_pay_source_values(
                army_id, owner_power, pay_source_region, province_share, central_share,
                is_tusi, self_funded, province_arrears, central_arrears,
            )
            if pay_source_region:
                self._require_valid_pay_source_region(army_id, pay_source_region)
        except (TypeError, ValueError) as exc:
            changes.append({
                "army": row["name"], "field": "pay_source",
                "rejected": True, "category": "invalid_enum",
                "reason": f"army_delta 饷源字段非法：{exc}",
                "item": {"army_id": army_id, "changes": raw_changes},
            })
            return

        # 合法且被 deny 的饷源字段：静默 no-op，不写库、不留 rejected
        if bool(row["is_mutinied"]):
            return

        old_values = {
            "pay_source_region": row["pay_source_region"],
            "province_pay_share": float(row["province_pay_share"] or 0),
            "central_pay_share": float(row["central_pay_share"] or 0),
            "is_tusi": int(row["is_tusi"] or 0),
            "self_funded_pay": int(row["self_funded_pay"] or 0),
            "province_pay_arrears": float(row["province_pay_arrears"] or 0),
            "central_pay_arrears": float(row["central_pay_arrears"] or 0),
            "arrears": float(row["arrears"] or 0),
        }
        new_values = {
            "pay_source_region": pay_source_region,
            "province_pay_share": province_share,
            "central_pay_share": central_share,
            "is_tusi": 1 if is_tusi else 0,
            "self_funded_pay": 1 if self_funded else 0,
            "province_pay_arrears": province_arrears,
            "central_pay_arrears": central_arrears,
            "arrears": province_arrears + central_arrears,
        }
        changed_fields = [field for field, new in new_values.items() if old_values[field] != new]
        if not changed_fields:
            return
        origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
        if origin_error:
            changes.append({
                "army": row["name"], "field": "pay_source", **origin_error,
                "item": {"army_id": army_id, "changes": raw_changes},
            })
            return

        # 饷源-only 路径：不触 owner_power（唯一 owner 写口 = transition_army_owner_power）
        self.armies.update(army_id, {
            "pay_source_region": pay_source_region,
            "province_pay_share": province_share,
            "central_pay_share": central_share,
            "is_tusi": 1 if is_tusi else 0,
            "self_funded_pay": 1 if self_funded else 0,
            "province_pay_arrears": province_arrears,
            "central_pay_arrears": central_arrears,
        })
        for field in changed_fields:
            self.armies.append_log({
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "army_id": army_id,
                "field": field,
                "old_value": str(old_values[field]),
                "new_value": str(new_values[field]),
                "reason": reason,
                "event_id": event.id,
                "edict_id": edict_id,
                "actor": actor,
                "origin_ref": origin_ref,
            })
            changes.append({
                "army": row["name"], "field": field,
                "label": ARMY_FIELD_LABELS.get(field, field),
                "old": old_values[field], "new": new_values[field],
                "delta": None, "reason": reason,
            })
        if old_source != pay_source_region:
            self._reconcile_army_pay_source_region_container(old_source)
        self._reconcile_army_pay_source_region_container(pay_source_region)
        self._reconcile_central_army_pay_arrears_container()
        self.assert_army_pay_source_container_conservation()

    def _army_pay_source_rows_for_region(self, region_id: str) -> List[Dict[str, float | str]]:
        from ming_sim.flows import army_needed

        out: List[Dict[str, float | str]] = []
        rows = ArmyStore(self.conn).read_army_pay_source_rows_for_region((region_id,))
        for row in rows:
            self._validate_pay_source_values(
                str(row["id"]), str(row["owner_power"]), str(row["pay_source_region"]),
                float(row["province_pay_share"] or 0), float(row["central_pay_share"] or 0),
                bool(row["is_tusi"]), bool(row["self_funded_pay"]),
                float(row["province_pay_arrears"] or 0), float(row["central_pay_arrears"] or 0),
            )
            out.append({
                "id": str(row["id"]),
                "due": army_needed(row) * float(row["province_pay_share"] or 0),
                "total_due": army_needed(row),
                "morale": float(row["morale"]),
                "province_pay_arrears": float(row["province_pay_arrears"] or 0),
                "central_pay_arrears": float(row["central_pay_arrears"] or 0),
            })
        return out

    def _derive_region_army_pay_due(self, region_id: str, settle: Dict[str, Any]) -> List[Dict[str, float | str]]:
        rows = self._army_pay_source_rows_for_region(region_id)
        p = settle.get("p")
        if not isinstance(p, dict):
            raise ValueError("settle.p 非法")
        due_obj = p.get("Due")
        if not isinstance(due_obj, dict):
            raise ValueError("settle.p.Due 非法")
        st = settle.get("st")
        if not isinstance(st, dict):
            raise ValueError("settle.st 非法")
        # #1889：省级军饷账完全从「有饷源省份额的军队」派生（ADR 0023 D8/D2b）。
        # 不属任何军的省级欠饷（辽东/东江无军受领漏斗）已随旧实账删除，无第二个写口。
        due_obj["军饷"] = sum(float(row["due"]) for row in rows) if rows else 0
        st["军饷欠"] = (
            sum(float(row["province_pay_arrears"]) for row in rows) if rows else 0
        )
        return rows

    def _reconcile_all_army_pay_source_regions(self) -> None:
        rows = RegionStore(self.conn).read_settle_ming_province_substrate_ticks()
        for row in rows:
            fiscal = load_stored_object(row["fiscal"], label=f"region {row['id']} fiscal")
            settle = fiscal.get("settle")
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                    or not isinstance(settle.get("p"), dict):
                continue
            pay_rows = self._derive_region_army_pay_due(str(row["id"]), settle)
            if pay_rows:
                self._reconcile_region_army_pay_container(str(row["id"]), settle)
            self.regions.update(
                str(row["id"]),
                {"fiscal": json.dumps(fiscal, ensure_ascii=False)},
            )

    def _reconcile_army_pay_source_region_container(self, region_id: str) -> None:
        if not region_id:
            return
        row = RegionStore(self.conn).read_settle_province_tick((region_id,))
        if row is None:
            return
        fiscal = load_stored_object(row["fiscal"], label=f"region {region_id} fiscal")
        settle = fiscal.get("settle")
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            return
        self._derive_region_army_pay_due(region_id, settle)
        self.regions.update(
            region_id,
            {"fiscal": json.dumps(fiscal, ensure_ascii=False)},
        )

    def _apply_region_army_pay_tick(
        self,
        pay_rows: List[Dict[str, float | str]],
        result: Any,
    ) -> None:
        if not pay_rows:
            return
        from ming_sim.flows import army_pay_morale_delta

        breakdown = result.breakdown or {}
        new_debt = float((breakdown.get("NewDebt") or {}).get("军饷欠", 0) or 0)
        repaid = float((breakdown.get("Repaid") or {}).get("军饷欠", 0) or 0)
        action_paid = float((breakdown.get("action还") or {}).get("军饷欠", 0) or 0)
        balances = {str(row["id"]): float(row["province_pay_arrears"]) for row in pay_rows}
        due_by_component = {str(row["id"]): float(row["due"]) for row in pay_rows}
        action_repaid_by_army = {str(row["id"]): 0.0 for row in pay_rows}
        new_debt_by_army = {str(row["id"]): 0.0 for row in pay_rows}
        surplus_repaid_by_army = {str(row["id"]): 0.0 for row in pay_rows}
        province_shortfalls = {str(row["id"]): 0.0 for row in pay_rows}
        if action_paid > 0:
            basis = sum(balances.values())
            if basis > 0:
                paid = min(action_paid, basis)
                for army_id, bal in list(balances.items()):
                    share = paid * bal / basis
                    if army_id in action_repaid_by_army:
                        action_repaid_by_army[army_id] = share
                    balances[army_id] = max(0.0, bal - share)
        due_total = sum(due_by_component.values())
        if new_debt > 0 and due_total > 0:
            for component_id, due in due_by_component.items():
                shortfall = new_debt * due / due_total
                if component_id in province_shortfalls:
                    province_shortfalls[component_id] = shortfall
                    new_debt_by_army[component_id] = shortfall
                balances[component_id] += shortfall
        if repaid > 0:
            basis = sum(balances.values())
            if basis > 0:
                paid = min(repaid, basis)
                for army_id, bal in list(balances.items()):
                    share = paid * bal / basis
                    if army_id in surplus_repaid_by_army:
                        surplus_repaid_by_army[army_id] = share
                    balances[army_id] = max(0.0, bal - share)
        state_row = ReignStateStore(self.conn).read_record_claim_flow_logs()
        if state_row is None:
            state = self.load_state("")
            log_turn, log_year, log_period = state.turn, state.year, state.period
        else:
            log_turn = int(state_row["turn"])
            log_year = int(state_row["year"])
            log_period = int(state_row["period"])
        for row in pay_rows:
            army_id = str(row["id"])
            old_province_arrears = float(row["province_pay_arrears"])
            province_arrears = balances[army_id]
            central_arrears = float(row["central_pay_arrears"])
            central_shortfalls = getattr(self, "_current_month_central_pay_shortfalls", {})
            opening_arrears = getattr(self, "_current_month_pay_opening_arrears", {})
            total_shortfall = float(central_shortfalls.get(army_id, 0.0)) + province_shortfalls[army_id]
            old_total_arrears = float(
                opening_arrears.get(
                    army_id,
                    float(row["province_pay_arrears"]) + float(row["central_pay_arrears"]),
                )
            )
            old_morale = int(row["morale"])
            # D11 分母须为两源本月折后总应发。省侧按本次 settle 的军饷
            # 免除比例回算每军折后份额；中央侧由 flows 唯一折算后经月桥传入。
            raw_province_due_total = sum(due_by_component.values())
            effective_province_due_total = max(
                0.0,
                raw_province_due_total - float(breakdown.get("haircut_军饷", 0.0) or 0.0),
            )
            province_due = (
                float(row["due"]) * effective_province_due_total / raw_province_due_total
                if raw_province_due_total > 0 else 0.0
            )
            central_dues = getattr(self, "_current_month_central_pay_dues", {})
            total_due = province_due + float(central_dues.get(army_id, 0.0))
            morale_delta = army_pay_morale_delta(total_due, total_shortfall, old_total_arrears)
            new_morale = max(0, min(100, old_morale + morale_delta))
            month_row = ArmyStore(self.conn).read_apply_region_army_pay_tick((army_id,))
            shortfall_months = (
                int(month_row["consecutive_pay_shortfall_months"] or 0)
                if month_row is not None else 0
            )
            new_shortfall_months = shortfall_months + 1 if total_shortfall > 1e-9 else 0
            self.armies.update(army_id, {
                "province_pay_arrears": province_arrears,
                "morale": new_morale,
                "consecutive_pay_shortfall_months": new_shortfall_months,
            })
            province_delta = province_arrears - old_province_arrears
            reason = f"{TURN_UNIT}省源军饷分账"
            if abs(province_delta) > 1e-9:
                reason_parts = []
                if new_debt_by_army[army_id] > 1e-9:
                    reason_parts.append(
                        f"按本月省份额应付占比摊新增欠"
                        f"{format_wanliang_amount(new_debt_by_army[army_id])}万两"
                    )
                repaid_total = action_repaid_by_army[army_id] + surplus_repaid_by_army[army_id]
                if repaid_total > 1e-9:
                    reason_parts.append(
                        f"按省份额欠余额占比偿还"
                        f"{format_wanliang_amount(repaid_total)}万两"
                    )
                if reason_parts:
                    reason += "（" + "；".join(reason_parts) + "）"
                self.armies.append_log({
                    "turn": log_turn,
                    "year": log_year,
                    "period": log_period,
                    "army_id": army_id,
                    "field": "province_pay_arrears",
                    "old_value": str(old_province_arrears),
                    "new_value": str(province_arrears),
                    "delta": province_delta,
                    "reason": reason,
                    "actor": "户部",
                })
            morale_actual_delta = new_morale - old_morale
            if morale_actual_delta != 0:
                self.armies.append_log({
                    "turn": log_turn,
                    "year": log_year,
                    "period": log_period,
                    "army_id": army_id,
                    "field": "morale",
                    "old_value": str(old_morale),
                    "new_value": str(new_morale),
                    "delta": morale_actual_delta,
                    "reason": reason,
                    "actor": "户部",
                })

    def _reconcile_region_army_pay_container(self, region_id: str, settle: Dict[str, Any]) -> None:
        total = ArmyStore(self.conn).read_reconcile_region_army_pay_container((region_id,))["total"]
        row_arrears_total = float(total or 0)
        st = settle.get("st")
        if not isinstance(st, dict):
            raise ValueError("settle.st 非法")
        st["军饷欠"] = row_arrears_total

    def has_state(self) -> bool:
        return self.reign.exists()

    def save_state(self, state: GameState) -> None:
        """Write the reign header and balances. 持久写口归 reign_state store（#1889）。"""
        self.reign.save(
            year=state.year,
            period=state.period,
            turn=state.turn,
            turn_phase=state.turn_phase,
            ended=state.ended,
            ending_status=state.ending_status,
            metrics=state.metrics,
        )

    def load_state(self, start_ym: str = "") -> GameState:
        header = self.reign.read()
        if header is None:
            state = GameState()
            if start_ym:
                try:
                    y_str, m_str = start_ym.split(".")
                    y, m = int(y_str), int(m_str)
                except (ValueError, AttributeError):
                    raise SystemExit(f"--start-ym 格式非法：{start_ym!r}，应为 YYYY.MM（如 1629.04）。")
                if not (1627 <= y <= 1644 and 1 <= m <= 12):
                    raise SystemExit(f"--start-ym 超范围：{start_ym!r}，年须 1627-1644、月 1-12。")
                state.turn = (
                    (y - DEFAULT_OPENING_YEAR) * 12
                    + (m - DEFAULT_OPENING_PERIOD) + 1
                )
                state.year, state.period = y, m
                print(f"[调试] 跳到 {y}年{m}月起手（turn={state.turn}）。")
            # #1889：新档初始化是一个整体——期初账册、开局危机、开局见闻任一写不进去，
            # 这次初始化就不算成功（异常上抛，事务回滚）。否则 game_state 已落库而开局
            # 事实缺失，下次重开 has_state() 为真、再也不会补 seed，得到一份永久残缺的新档。
            with atomic(self):
                self.save_state(state)
                self.ensure_opening_ledger(state)
                self.seed_opening_crises(state)
                self.seed_opening_gazette(state)
            return state
        metrics = self.reign.read_metrics()
        state = GameState(**header)
        if metrics:
            # #1889：国库/内库余额真源就是 metrics，上面这一次 SELECT 已全部读入；
            # economy_accounts 是它的派生视图（读时算），回灌等于让镜像反向盖真源。
            # 回滚恢复（atomic_and_reload → load_state）也因此同源：DB 值直接覆盖
            # 事务内被改脏的内存余额，不必再补一次查询。
            # 只接当前 GameState 默认 dict 里有的 key，避免旧 DB 残留废弃 metric 灌入。
            valid_keys = set(state.metrics.keys())
            state.metrics.update({k: v for k, v in metrics.items() if k in valid_keys})
        self.ensure_opening_ledger(state)
        self.conn.commit()
        return state

    def ensure_opening_ledger(self, state: GameState) -> None:
        for account in ECONOMY_ACCOUNTS:
            exists = ReignStateStore(self.conn).read_ensure_opening_ledger((account,))
            if exists:
                continue
            balance = int(state.metrics[account])
            self.reign.insert_ledger({
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "account": account,
                "delta": balance,
                "balance_after": balance,
                "category": "期初",
                "reason": "登基初始账册",
                "actor": "内阁",
            })
        self.conn.commit()

    def seed_opening_gazette(self, state: GameState) -> None:
        """开局公共见闻（新君登基/倒魏）。

        #1356/#1292：不写入任何固定开局邸报文（P7 禁固定模板直显）。
        首份玩家可见邸报由第一个正常月末 LLM 结算产生。
        """
        # Keep the two opening facts addressable as public knowledge rather than
        # requiring a character to infer them from an undifferentiated gazette.
        self.record_public_knowledge_event(
            state, "新君登基", "崇祯帝于乾清宫即位，朝廷进入新君亲政的开局。",
            source_id="opening:accession",
        )
        self.record_public_knowledge_event(
            state, "倒魏旧案", "阉党专权与魏忠贤乱政是朝野公开议论的政局事实，倒魏为新君必须面对的公共政务。",
            source_id="opening:anti_eunuch",
        )
        self.conn.commit()

    def seed_opening_crises(self, state: GameState) -> None:
        """新档首次进入时塞 1627 即位即面对的危机为 active situation issue。
        数据源已并入 seed_events.json：取标了 auto_trigger 且 trigger_gate 为空（开局盘面无条件
        即达标）的 situation 事件，开局直接立项，使玩家召见前就看到三大危机。
        其余带 gate 的 seed 事件靠 auto_trigger_seed_issues 在 gate 达标的回合再硬立。

        #1889：整段开局危机立为**一个**事务，且任何一条写不进去就让初始化失败上抛
        （不再逐条 print WARN 后继续）。否则 load_state 照常返回一份「初始化成功」的盘面，
        而三件开局危机实际一条没落库——引擎声称记住的开局事实并不存在。"""
        if not getattr(self, "content", None):
            return
        pending = [
            ev for ev in self.content.seed_events
            if ev.auto_trigger
            and not ev.trigger_gate
            and ev.event_type == "situation"
            and self.find_any_issue_by_origin("event_pool", ev.id) is None
        ]
        if not pending:
            return
        with atomic(self):
            for ev in pending:
                # 推导默认 bar / inertia / ongoing / effect，与 event_to_issue 同口径；精调字段优先
                bar = ev.bar_value or max(20, min(60, 50 - int(ev.severity / 5)))
                self.insert_issue(
                    state,
                    kind="situation",
                    title=ev.title,
                    origin_kind="event_pool",
                    origin_ref=ev.id,
                    bar_value=bar,
                    bar_good_meaning=ev.bar_good_meaning or "已平",
                    bar_bad_meaning=ev.bar_bad_meaning or "失控",
                    inertia=ev.issue_inertia,  # 默认 0=不漂；要月漂在 seed 里显式填
                    stage_text=ev.stage_text or ev.summary[:80],
                    severity=int(ev.severity),
                    region_hint=ev.region_hint,
                    faction_hint=",".join(ev.interests[:2]),
                    tags=ev.issue_tags or [ev.kind],
                    ongoing_effects=ev.ongoing_effects,
                    cancellable="never",
                    effect_on_resolve=ev.effect_on_resolve,
                    effect_on_fail=ev.effect_on_fail,
                    resolve_condition=ev.resolve_condition,
                    fail_condition=ev.fail_condition,
                    commit=False,
                )
                # 触发起手同样是一条事件触发事实：由 mark_event_triggered 这唯一写口落
                # （不再靠旧档 backfill 从 event_pool issue 反推）。
                self.mark_event_triggered(
                    state, ev.id, source="opening_crises", commit=False,
                )

    def _canonicalize_character_location(self, raw: object) -> str:
        """#654 G：location 唯一写缝归一——精确 compact 等值；未知非空 fail-loud。"""
        from ming_sim.matching import canonical_region_id_exact

        text = "" if raw is None else str(raw)
        if not text.strip():
            return ""
        regions = getattr(self.content, "regions", None) or {}
        hit = canonical_region_id_exact(text, regions)
        if hit is None:
            raise ValueError(f"character location 未知：{text!r}")
        return hit

    def set_character_transit(
        self,
        name: str,
        *,
        transit_to: str = "",
        distance_remaining: float | None = None,
        speed_factor: float | None = None,
        start_turn: int = 0,
        location: str | None = None,
        content=None,
        commit: bool = True,
    ) -> None:
        """Write the complete transit ledger and its in-memory mirror at one seam."""
        fields: dict[str, object] = {
            "transit_to": transit_to,
            "transit_distance_remaining": distance_remaining,
            "transit_speed_factor": speed_factor,
            "transit_start_turn": start_turn,
        }
        if location is not None:
            location = self._canonicalize_character_location(location)
            fields["location"] = location
        self.characters.update(name, fields)
        if content is not None and name in content.characters:
            character = content.characters[name]
            if location is not None:
                character.location = location
            character.transit_to = transit_to
            character.transit_distance_remaining = distance_remaining
            character.transit_speed_factor = speed_factor
            character.transit_start_turn = start_turn
        if commit:
            self.conn.commit()

    def set_character_status(
        self,
        state: GameState,
        name: str,
        status: str,
        reason: str = "",
        reason_code: str | None = None,
        commit: bool = True,
        content=None,
    ) -> None:
        """改人物状态：active/offstage/dismissed/imprisoned/exiled/retired/dead。
        人物状态以 characters 表为准。
        #9：状态变更后全重算所属朝堂派系 leverage（在朝成员官职权重和 + offset；党魁倒台势力跟跌）。"""
        valid = {"active", "offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}
        if status not in valid:
            raise ValueError(f"character status 非法：{status}")
        # #9：UPDATE 前读旧派系（退场清 office 后仍按当前在朝成员现算，与旧职无关）。
        prev = CharacterStore(self.conn).read_displace_duplicate_offices_faction((name,))
        # 去职（下狱/革职/流放/致仕/出宫/死）即削职：清空 characters.office，
        # 原职仍留在 character_offices 备档可追溯。复职（active）不动 office。
        ousted = status in _OUSTED_STATES
        reason_code_value = str(reason_code or "")[:40]
        fields = {
            "status": status,
            "status_reason": reason[:200],
            "status_changed_turn": state.turn,
            "reason_code": reason_code_value,
        }
        if ousted:
            fields["office"] = ""
        self.characters.update(name, fields)
        if ousted:
            self.set_character_transit(name, content=content, commit=False)
        if content is not None and name in content.characters:
            character = content.characters[name]
            character.status = status
            character.status_reason = reason[:200]
            character.reason_code = reason_code_value
            if ousted:
                character.office = ""
        # #9：状态变更后全重算该人物所属朝堂派系 leverage（绝对值、读当前所有在朝成员 → 无漂移）。
        if prev is not None:
            self.recompute_faction_leverage(str(prev["faction"] or ""))
        if status in _OUSTED_STATES:
            self.interrupt_dossiers_for_character(
                state, name, f"人物终态：{status}；{reason}".rstrip("；"),
                commit=False,
            )
        if commit:
            self.conn.commit()

    def _faction_office_weight_sum(self, faction: str) -> float:
        """该 faction 当前所有 status='active' 的大明成员的官职权重和
        （每人 = office_type 域权重 × 品级档 multiplier）。只算大明朝臣（power_id='ming'）——
        外藩成员即便挂 ming 风格头衔也不握明官；白名单派系本就全 ming，此约束为防御。"""
        rows = CharacterStore(self.conn).read_faction_office_weight_sum((faction,))
        return sum(
            _member_office_weight(str(r["office_type"] or ""), str(r["office"] or ""))
            for r in rows
        )

    def recompute_faction_leverage(self, faction: str) -> None:
        """#9：全重算朝堂派系 leverage = clamp(0,100, offset + 当前在朝官职权重和)。
        绝对值（每次从公式现算、不累加）→ 无 clamp 漂移、时序无关（多次调用末值一致）。
        只对 _LEVERAGE_FACTIONS（外族/后宫/宗室不握明官、leverage 另义）；非白名单直接 return、不动。
        不在此 commit——由调用方统一提交（保事务原子性）。"""
        if faction not in _LEVERAGE_FACTIONS:
            return
        row = FactionStore(self.conn).read_recompute_faction_leverage((faction,))
        if row is None:
            return
        offset = float(row["leverage_offset"] or 0)
        weight_sum = self._faction_office_weight_sum(faction)
        new_lev = max(0, min(100, round(offset + weight_sum)))
        self.factions.set_leverage(faction, new_lev)

    def recompute_all_faction_leverage(self) -> None:
        """#9 cmr R2：全量重算所有白名单朝堂派系 leverage（集中化兜底层）。

        两层设计：
          (1) 即时 hook（set_character_status / set_character_office / _displace_duplicate_offices /
              add_character）——单个成员状态/官职/易主变动时就地重算其所属派系，保回合内即时联动。
          (2) 本方法（reconcile 兜底）——在月末结算尾（delta 全部
              落库且 inertia 推进之后、next_period 之前）扫一遍全部白名单派系，重算成公式末值。
              覆盖任何绕过 hook 的路径（裸 UPDATE 改 office_type、power_id 翻走的易主/降臣、
              放归赦还后任命被拒回滚、未挂 hook 的新建大臣 等），保末态与公式一致、无残留漂移。
        绝对重算（每个派系从 offset+当前在朝权重和现算、不累加）→ 幂等、时序无关、即便已被
        hook 重算过再扫一遍也得同值。不在此 commit——由调用方（结算 atomic）统一提交。"""
        for faction in _LEVERAGE_FACTIONS:
            self.recompute_faction_leverage(faction)

    def _calibrate_faction_offsets(self, is_fresh_factions_seed: bool) -> None:
        """Fresh-save offset = content baseline − current office weight.

        Reloading an existing save does not re-anchor. The marker and the offset
        rows commit with the caller's transaction.
        """
        if not is_fresh_factions_seed or self._has_meta_flag("__leverage_offsets_calibrated"):
            return
        for faction in _LEVERAGE_FACTIONS:
            row = FactionStore(self.conn).read_calibrate_faction_offsets((faction,))
            if row is None:
                continue
            content_faction = self.content.factions.get(faction)
            if content_faction is None:
                continue
            weight_sum = self._faction_office_weight_sum(faction)
            offset = int(content_faction.leverage) - weight_sum
            self.factions.set_leverage_offset(faction, offset)
            self.recompute_faction_leverage(faction)
        self._set_meta_flag("__leverage_offsets_calibrated")
        self._leverage_offsets_calibrated = True

    def _has_meta_flag(self, key: str) -> bool:
        """查 metrics 表里某持久标记是否存在（#9 R3 crash-safe 迁移标记用）。metrics 在 init_schema
        建表脚本里已建，故此调用安全。值约定 1=已置位。"""
        row = ReignStateStore(self.conn).read_has_meta_flag((key,))
        return row is not None and int(row["value"]) == 1

    def _set_meta_flag(self, key: str) -> None:
        """置 metrics 表里某持久标记=1（幂等 upsert）。不在此 commit——由调用方统一提交，
        与同事务的其它写一并落库或一并回滚。"""
        self.reign.upsert_metric(key, 1)

    def record_person_log(
        self,
        state: GameState,
        person_name: str,
        action: str,
        payload_summary: str = "",
        derived_from: str = "",
        normalized: str | Dict[str, object] = "",
        source: str = "",
        commit: bool = True,
        origin_ref: str = "",
    ) -> None:
        """Append one person event. 持久写口归 person_log store（#1889）。"""
        self.person_logs.append(
            turn=state.turn,
            year=state.year,
            period=state.period,
            person_name=person_name,
            action=action,
            payload_summary=payload_summary,
            derived_from=derived_from,
            normalized=normalized,
            source=source,
            origin_ref=origin_ref,
            commit=commit,
        )

    def get_character_status(self, name: str) -> Tuple[str, str]:
        row = CharacterStore(self.conn).read_get_character_status((name,))
        if row is None:
            return ("active", "")
        return (row["status"], row["status_reason"] or "")

    def current_court_roster_rows(
        self, state: GameState, names: Optional[Iterable[str]] = None,
    ) -> List[sqlite3.Row]:
        """Return the single current-court membership projection."""
        return self.characters.current_court_rows(int(state.year), int(state.period), names)

    def resolve_power_id(self, character) -> str:
        """人物所属势力 id 的权威解析：DB 行 power_id 优先，回退内存 power_id，默认 ming。

        DB 为准是关键：招抚归明者（流寇/降将 power_id 经 apply_character_power_changes 翻 ming，
        但 content/内存 power_id 仍是旧势力 bandits/houjin）必须认 DB——否则按内存会把已归明者
        误判为外藩、误拒在朝堂外（见 #125、web_app._character_power_id 同源）。"""
        row = CharacterStore(self.conn).read_resolve_power_id((character.name,))
        return (row["power_id"] if row else None) or getattr(character, "power_id", "ming") or "ming"

    def apply_character_power_changes(
        self,
        changes: List[Dict[str, object]],
        commit: bool = True,
    ) -> List[Dict[str, object]]:
        """据 extractor 输出改人物 power_id（降将/叛臣/归正）。new_power 须为合法 power id。"""
        applied: List[Dict[str, object]] = []
        if not isinstance(changes, list):
            return applied
        valid_powers = {r["id"] for r in PowerStore(self.conn).read_apply_character_power_changes()}
        for raw in changes:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or raw.get("姓名") or "").strip()
            new_power = str(raw.get("new_power") or raw.get("新势力") or "").strip()
            reason = str(raw.get("reason") or raw.get("原因") or "")[:120]
            if not name or not new_power:
                applied.append({
                    "rejected": True, "category": "invalid_enum",
                    "reason": "character_power_changes 缺 name/new_power",
                    "item": raw,
                })
                continue
            if new_power not in valid_powers:
                applied.append({
                    "name": name, "new_power": new_power, "rejected": True,
                    "category": "hallucinated_id",
                    "reason": f"character_power_changes new_power '{new_power}' 未在 powers",
                    "item": raw,
                })
                continue
            row = CharacterStore(self.conn).read_apply_character_power_changes((name,))
            if row is None:
                applied.append({
                    "name": name, "new_power": new_power, "rejected": True,
                    "category": "missing_ref",
                    "reason": f"character_power_changes 人物 '{name}' 未入库",
                    "item": raw,
                })
                continue
            old_power = row["power_id"] or "ming"
            if old_power == new_power:
                continue
            self.characters.update(name, {"power_id": new_power})
            # #177 R2: power_id 跨 ming 边界翻转后即时重算原派系 leverage
            # （与 set_character_status / set_character_office 钩子一致）。
            # sourcery R1：faction 为空跳过；只在真跨 ming 边界（old/new 有一方是 ming）时重算
            # —— _faction_office_weight_sum 按 power_id='ming' 过滤，非 ming↔非 ming 翻转不改权重和。
            faction = str(row["faction"] or "")
            if faction and (old_power == "ming" or new_power == "ming"):
                self.recompute_faction_leverage(faction)
            applied.append({"name": name, "old_power": old_power, "new_power": new_power, "reason": reason})
        if commit:
            self.conn.commit()
        return applied

    def set_character_office(
        self,
        name: str,
        office: str,
        office_type: str = "",
        source: str = "诏书调任",
        llm_config: Any = None,
        commit: bool = True,
        region_id: str = "",
    ) -> None:
        """既有官员调任/升迁：改 characters.office（office_type 给空则不动），
        同步 character_offices 备档。状态不变（仍 active）。
        地方职任所经 :meth:`_require_local_office_region`：显式 typed region
        原样消费；同人同职 identity 续任沿 character_offices.region_id；
        真正新建/改授缺 typed 任所才拒（不读 location/官名推断）。
        #9：授官改了 office_type/品级 → 末尾全重算所属朝堂派系 leverage（升迁也联动；
        起复路 set_character_status(active)→set_character_office(新职) 双 recompute，新职覆盖中间值）。"""
        office = normalize_office(office)
        current_type = (
            CharacterStore(self.conn).read_set_character_office((name,)) or {"office_type": ""}
        )["office_type"]
        if not current_type:
            raise ValueError(f"{name}不属大明朝廷，不能授予大明官职")
        # 显式声明的名分（office_type ∈ PERSON_TITLE_KINDS）是权威身份，office 文本反推不得
        # 覆盖它（例 office='诸生'→infer 改写成 '生员'，令名分守卫失效，#1059 codex 同源）；
        # office_type 留空回落 current_type 时仍照常重推（授实职即脱名分，不短路）。
        eff_type = resolve_office_type_preserving_title(
            office, office_type, current_type, llm_config or self.llm_config
        )
        is_person_title = eff_type in PERSON_TITLE_KINDS
        if not is_person_title:
            self._ensure_office_type_parent(eff_type)
        seat = self._require_local_office_region(
            name=name, office=office, office_type=eff_type, region_id=region_id,
        )
        fields = {"office": office}
        if office_type or eff_type != current_type:
            fields["office_type"] = eff_type
        self.characters.update(name, fields)
        self._record_character_office(name, office, eff_type, source, region_id=seat)
        # #9：授官改了 office_type/品级权重 → 全重算该人物所属朝堂派系 leverage（commit 前）。
        faction_row = CharacterStore(self.conn).read_displace_duplicate_offices_faction((name,))
        if faction_row is not None:
            self.recompute_faction_leverage(str(faction_row["faction"] or ""))
        if commit:
            self.conn.commit()
        if name in self.content.characters:
            self.content.characters[name].office = office
            self.content.characters[name].office_type = eff_type
            self.content.characters[name].office_region = seat

    def apply_historical_deaths(self, state: GameState) -> List[Dict[str, str]]:
        """月初 tick：只有仍 active 的人到点自然死。被玩家提前罢/狱/流/杀的不走此分支。
        只打讣闻、改 status=dead，不动派系/metric。是否升级 issue 由 LLM 看本月邸报判断。
        返回 [{name, office, faction}] 喂给 simulator 当月上下文。
        """
        rows = CharacterStore(self.conn).read_apply_historical_deaths()
        died: List[Dict[str, str]] = []
        for r in rows:
            year = int(r["historical_death_year"])
            month = int(r["historical_death_month"] or 0)
            triggered = state.year > year or (
                state.year == year and (month == 0 or state.period >= month)
            )
            if not triggered:
                continue
            name = r["name"]
            self.set_character_status(
                state, name, "dead", f"历史卒于 {year}年{month or '?'}月",
                reason_code="历史卒", content=self.content,
            )
            self.record_person_log(
                state, name, "处置",
                payload_summary=f"历史卒于 {year}年{month or '?'}月",
                derived_from="历史卒", source="system_simulation",
            )
            died.append({
                "name": name,
                "office": r["office"] or "重臣",
                "faction": r["faction"] or "",
            })
        return died

    def apply_historical_debuts(self, state: GameState) -> List[Dict[str, str]]:
        """月初 tick：offstage 人物到历史登场年月，自动转 active 并发"起用"讯息。
        debut_year=0 视为开局即在场（不会处于 offstage）。
        返回 [{name, office, faction}] 喂给 simulator 当月上下文，由 LLM 写进邸报。
        """
        rows = CharacterStore(self.conn).read_apply_historical_debuts()
        debuted: List[Dict[str, str]] = []
        for r in rows:
            year = int(r["debut_year"])
            month = int(r["debut_month"] or 0)
            triggered = state.year > year or (
                state.year == year and (month == 0 or state.period >= month)
            )
            if not triggered:
                continue
            name = r["name"]
            self.set_character_status(
                state, name, "active", f"历史登场 {year}年{month or '?'}月",
                reason_code="登场", content=self.content,
            )
            self.record_person_log(
                state, name, "处置",
                payload_summary=f"历史登场 {year}年{month or '?'}月",
                derived_from="登场", source="system_simulation",
            )
            debuted.append({
                "name": name,
                "office": r["office"] or "重臣",
                "faction": r["faction"] or "",
            })
        return debuted

    def apply_historical_power_renames(self, state: GameState) -> List[Dict[str, object]]:
        """月初 tick：历史国号/称谓变化。稳定 id 不变，只改展示名与别名。"""
        changes: List[Dict[str, object]] = []
        if state.year > 1636 or (state.year == 1636 and state.period >= 4):
            ev = self.content.event_by_id.get("huangtaiji_chengdi")
            if ev is None or not isinstance(ev.effect_on_trigger, dict):
                raise ValueError("历史改国号缺少事件真源 huangtaiji_chengdi.effect_on_trigger")
            power_renames = ev.effect_on_trigger.get("power_renames")
            if not isinstance(power_renames, list):
                raise ValueError("历史改国号缺少 power_renames 列表")
            for idx, item in enumerate(power_renames):
                if not isinstance(item, dict):
                    raise ValueError(f"历史改国号 power_renames[{idx}] 非 dict")
                power_id = str(item.get("power_id") or "").strip()
                new_name = str(item.get("new_name") or "").strip()
                if not power_id or not new_name:
                    raise ValueError(f"历史改国号 power_renames[{idx}] 缺少 power_id/new_name")
                changed = self.apply_power_rename(
                    state,
                    power_id,
                    new_name,
                    aliases=str(item.get("aliases") or ""),
                    reason=str(item.get("reason") or ""),
                    status=str(item.get("status") or ""),
                    last_action=str(item.get("last_action") or ""),
                )
                if changed:
                    changes.append(changed)
        return changes

    def next_pool_portrait_id(self, prefix: str = "minister_pool_") -> str:
        """分配下一个预设头像 ID（顺序递增，不循环）。
        minister_pool: 60 个槽；consort_pool: 20 个槽。
        实际可用槽位 = web/public/portraits/<prefix><N>.png 真存在的编号集合（中途删图会跳过缺号）。
        发行包只带 web/dist；public 不存在时回退扫 web/dist/portraits。
        全部用完后再回退到递增（前端 onError fallback 占位符）。"""
        rows = CharacterStore(self.conn).read_next_pool_portrait_id((prefix + "%",))
        used = set()
        for r in rows:
            try:
                used.add(int(r["portrait_id"].replace(prefix, "")))
            except ValueError:
                pass
        # 扫真实存在的图编号：源码优先 public；发行包只带 Vite 产物 dist。
        from pathlib import Path
        from ming_sim.paths import bundled_path
        available: set[int] = set()
        for portraits_dir in (
            Path(bundled_path("web", "public", "portraits")),
            Path(bundled_path("web", "dist", "portraits")),
        ):
            if not portraits_dir.is_dir():
                continue
            for p in portraits_dir.glob(f"{prefix}*.png"):
                suffix = p.stem[len(prefix):]
                if suffix.isdigit():
                    available.add(int(suffix))
            if available:
                break
        free = sorted(available - used)
        if free:
            return f"{prefix}{free[0]}"
        # 真实图全用完：递增分配，但跳过已知中途缺号（如手动删过的 consort_pool_14）。
        # 编号上限：available 最大值 + 缺号集；超出后继续递增（前端 onError fallback 占位符）。
        max_known = max(available, default=0)
        missing = {n for n in range(1, max_known + 1) if n not in available}
        n = 1
        while n in used or n in missing:
            n += 1
        return f"{prefix}{n}"

    def set_portrait_id(self, name: str, portrait_id: str) -> None:
        """改某人物的头像标识（如皇帝上传自定义立绘后落库）。"""
        self.characters.update(name, {"portrait_id": portrait_id})
        self.conn.commit()

    def add_character(
        self,
        state: GameState,
        character: "Character",
        source: str = "",
        llm_config: Any = None,
        commit: bool = True,
    ) -> None:
        """运行时新建人物（吏部任命/皇帝点名）。已存在同名则不动，避免覆盖既有状态。"""
        existing = CharacterStore(self.conn).read_apply_person_changes_name((character.name,))
        if existing is not None:
            return
        character.office = normalize_office(character.office)
        # 显式声明的名分（PERSON_TITLE_KINDS）是权威身份，office 文本反推不得覆盖它：
        # 例 office='诸生'（亦为 offices.json 生员词干）会被 infer 改写成 '生员'，令下方
        # 名分守卫失效、误建 offices 父行并写 character_offices 脏行（#1059 codex）。
        character.office_type = resolve_office_type_preserving_title(
            character.office,
            character.office_type,
            character.office_type,
            llm_config or self.llm_config,
        )
        # person-title 名分不入官职体系（镜像 set_character_office 守卫）：仅非名分才
        # 建 offices 父行——否则 #1056 严格官类校验对名分直接 ValueError 中止结算。
        if character.office_type not in PERSON_TITLE_KINDS:
            self._ensure_office_type_parent(character.office_type)
        # 若没有专属 portrait_id，按 office_type 分配预设池头像
        portrait_id = character.portrait_id
        if not portrait_id:
            prefix = "consort_pool_" if character.office_type == "后宫" else "minister_pool_"
            portrait_id = self.next_pool_portrait_id(prefix)
        source_label = source or ("吏部铨选任命" if character.office_type != "后宫" else "诏书纳妃")
        office_source = source or ("吏部任命" if character.office_type != "后宫" else "诏书纳妃")
        # Seat resolve/validate BEFORE characters INSERT — callers that catch
        # OfficeAppointmentRejection must not inherit an orphan character row
        # waiting on a later outer commit. SAVEPOINT isolation is complementary,
        # not a substitute for write order.
        seat = self._require_local_office_region(
            name=character.name,
            office=character.office,
            office_type=character.office_type,
            region_id=str(getattr(character, "office_region", "") or ""),
        )
        self.characters.insert({
            "name": character.name,
            "office": character.office,
            "office_type": character.office_type,
            "faction": character.faction,
            "aliases": json.dumps(character.aliases, ensure_ascii=False),
            "personal_skills": json.dumps(character.personal_skills, ensure_ascii=False),
            "loyalty": character.loyalty,
            "ability": character.ability,
            "integrity": character.integrity,
            "courage": character.courage,
            "style": character.style,
            "identity": character.identity,
            "seed_guilt": _seed_guilt_storage_value(character.seed_guilt),
            "birth_year": character.birth_year,
            "historical_death_year": character.historical_death_year,
            "historical_death_month": character.historical_death_month,
            "debut_year": character.debut_year,
            "debut_month": character.debut_month,
            "status": character.status,
            "status_reason": source_label,
            "status_changed_turn": state.turn,
            "portrait_id": portrait_id,
            "power_id": getattr(character, "power_id", "ming") or "ming",
            "location": getattr(character, "location", "") or "",
            "transit_to": getattr(character, "transit_to", "") or "",
            "summary": getattr(character, "summary", "") or "",
        })
        self._record_character_office(
            character.name, character.office, character.office_type, office_source,
            region_id=seat,
        )
        # #9 cmr R2 finding#2：新建大臣（经 apply_office_appointment→apply_appointment 任命的不在册者）
        # 入朝即联动其所属派系 leverage（与 set_character_office/status hook 一致，commit 前重算）。
        # 仅对 active + 大明 + 非后宫的朝臣——后宫(consort)不握明官、leverage 另义；非白名单派系
        # recompute 内部自会 return（幂等无害）。
        power_id = getattr(character, "power_id", "ming") or "ming"
        is_consort = character.office_type == "后宫" or character.faction == "后宫"
        if character.status == "active" and power_id == "ming" and not is_consort:
            self.recompute_faction_leverage(str(character.faction or ""))
        if commit:
            self.conn.commit()

    def treasury_budget_summary(self, state: "GameState | None" = None) -> str:
        # 三套口径统一：直接调 flows.compute_budget_lines（唯一定额源），此处只负责拼文本。
        from ming_sim.flows import compute_budget_lines  # 局部 import 避免与 flows 顶层循环依赖
        st = state if state is not None else self.load_state("")
        budget = compute_budget_lines(self, st)

        def _sum(acc: str, direction: str) -> int:
            return sum(int(it["amount"]) for it in budget[acc][direction])

        def _amt(acc: str, direction: str, name: str) -> int:
            return sum(int(it["amount"]) for it in budget[acc][direction] if it["name"] == name)

        def _amt_key(acc: str, direction: str, budget_key: str) -> int:
            return sum(
                int(it["amount"])
                for it in budget[acc][direction]
                if it.get("budget_key") == budget_key
            )

        def _names_key(acc: str, direction: str, budget_key: str) -> str:
            return "+".join(
                str(it["name"])
                for it in budget[acc][direction]
                if it.get("budget_key") == budget_key and int(it["amount"])
            )

        def _parts(acc: str, direction: str, names: tuple[str, ...]) -> str:
            present = [name for name in names if _amt(acc, direction, name)]
            return "+".join(present) if present else "无"

        gk_in, gk_out = _sum("国库", "income"), _sum("国库", "expense")
        nk_in, nk_out = _sum("内库", "income"), _sum("内库", "expense")
        army_pay_amt = _amt_key("国库", "expense", "army_pay")
        army_pay_label = _names_key("国库", "expense", "army_pay")
        gk_income_names = _parts(
            "国库", "income",
            ("起运", "田赋辽饷盐商", "盐税", "商税"),
        )
        # 军饷科目取数认 budget_key；呈现名跟预算行 name（玩家/摘要同源）。
        other_expense = (
            "中央军饷", "太仓亏空", "宗室禄米", "百官俸禄", "工部", "赈灾备用", "建筑维护",
        )
        expense_present = [
            army_pay_label if army_pay_amt else "",
            *(name for name in other_expense if _amt("国库", "expense", name)),
        ]
        gk_expense_names = "+".join(name for name in expense_present if name) or "无"
        return (
            f"{TURN_UNIT}度预算基准：国库入{format_money(gk_in)}"
            f"（{gk_income_names}；建筑产出{format_money(_amt('国库', 'income', '建筑产出'))}）"
            f"出{format_money(gk_out)}"
            f"（{gk_expense_names}；军饷"
            f"{format_money(army_pay_amt)}+"
            f"建筑维护{format_money(_amt('国库', 'expense', '建筑维护'))}）"
            f"净{format_money_delta(gk_in - gk_out)}；"
            f"内库入{format_money(nk_in)}"
            f"出{format_money(nk_out)}"
            f"（内廷维护{format_money(_amt('内库', 'expense', '建筑维护'))}）"
            f"净{format_money_delta(nk_in - nk_out)}。"
        )

    def treasury_hub_result(self, state: GameState) -> Optional[Dict[str, int]]:
        """已执行边饷 hub 三项结果；只读 ledger/container，不重算结算。"""
        # pre_settle 已在当月 state.turn 写 ledger/覆盖容器，settling/awaiting_decision
        # 相位下 next_period 尚未推进——此刻 state.turn 本身就是刚结算完的 turn（两者语义
        # 相同，见 FRONT_HALF_DONE_PHASES 单一真源）。换月后（summoning 等其它相位）
        # next_period 已推进，刚结算的 turn 退一位。前半段窗口内若仍按 turn-1 取 ledger，
        # 会把上一次结算的旧 turn 流水与本次刚覆盖的新 turn 容器拼在一起。
        front_half_done = str(getattr(state, "turn_phase", "") or "") in FRONT_HALF_DONE_PHASES
        settled_turn = max(0, int(state.turn) - (0 if front_half_done else 1))
        hub_debit = ReignStateStore(self.conn).read_treasury_hub_result((settled_turn,))
        containers = FiscalContainerStore(self.conn).read_treasury_hub_result()
        values = {str(row["key"]): float(row["value"] or 0) for row in containers}
        if len(values) != 3:
            return None
        return {
            "settled_turn": settled_turn,
            "treasury_disbursed": int(hub_debit["amount"] or 0),
            "actual_arrived": int(
                values.get("hub_京运实拨", 0) + values.get("hub_中央军饷实拨", 0)
            ),
            "transit_loss": int(values.get("hub_京运损耗", 0)),
        }

    def treasury_report(
        self, state: GameState, limit: int | None = 6, *,
        exclude_origin_prefix: str = "",
        exclude_dossier_ids: Optional[Iterable[int]] = None,
    ) -> str:
        account_rows = ReignStateStore(self.conn).read_treasury_report()
        if not account_rows:
            account_text = f"国库{format_money(state.metrics['国库'])}，内库{format_money(state.metrics['内库'])}"
        else:
            account_text = "，".join(f"{row['account']}{format_money(int(row['balance']))}" for row in account_rows)

        prefix = str(exclude_origin_prefix or "")
        dossier_ids = tuple(int(item) for item in (exclude_dossier_ids or ()) if int(item) > 0)
        period_rows = self.reign.ledger_totals(state.turn, prefix, dossier_ids)
        period_text = "；".join(
            f"{row['account']}入{format_money(int(row['income'] or 0))}出{format_money(int(row['expense'] or 0))}"
            for row in period_rows
        )
        if not period_text:
            period_text = f"本{TURN_UNIT}尚无新账"

        # limit=None：不截断（#1834 推演者盘面全量——与 region_rows/army_rows
        # 同一「None = 无 LIMIT 子句」约定，不是另造一套语义）。
        ledger_rows = self.reign.recent_ledger(prefix, dossier_ids, limit)
        recent = []
        for row in reversed(ledger_rows):
            delta = int(row["delta"])
            sign = "+" if delta > 0 else ""
            recent.append(
                f"{period_label(int(row['year']), int(row['period']))} {row['account']}{sign}{format_money(delta)} {row['category']}：{row['reason']}"
            )
        recent_text = "；".join(recent) if recent else "未见流水"
        hub_result_text = ""
        hub_result = self.treasury_hub_result(state)
        if hub_result is not None:
            hub_result_text = (
                f"边饷结算：国库实拨{format_money(hub_result['treasury_disbursed'])}，"
                f"实际到达{format_money(hub_result['actual_arrived'])}，"
                f"途中损耗{format_money(hub_result['transit_loss'])}。"
            )
        budget = self.treasury_budget_summary(state)
        return (
            f"{budget}账面：{account_text}。本{TURN_UNIT}收支：{period_text}。"
            f"{hub_result_text}近账：{recent_text}。"
        )

    def faction_satisfaction(self, faction: str) -> int:
        row = FactionStore(self.conn).read_faction_satisfaction((faction,))
        return int(row["satisfaction"]) if row else 50

    def faction_leverage(self, faction: str) -> int:
        row = FactionStore(self.conn).read_faction_leverage((faction,))
        return int(row["leverage"]) if row else 50

    def faction_report(self, *, audience: bool = False) -> str:
        """Render faction state for engine consumers or a minister-facing audience.

        The engine still needs the exact axes for settlement and simulation.
        A minister-facing report is a separate presentation contract: its
        satisfaction and leverage values are qualitative, never prompt data.
        """
        rows = FactionStore(self.conn).read_faction_report()
        if not rows:
            return "派系未建档。"
        if audience:
            return "；".join(
                f"{row['name']}满意{satisfaction_band(row['satisfaction'])}、"
                f"势力{power_band(row['leverage'])}，所求：{row['agenda']}"
                for row in rows
            )
        return "；".join(
            f"{row['name']}满意{row['satisfaction']}、势力{row['leverage']}，所求：{row['agenda']}"
            for row in rows
        )

    def class_rows(self, region_id: str = "") -> List[sqlite3.Row]:
        """region_id="" 取全国汇总行；其它取该省切片。"""
        return ClassStore(self.conn).read_class_rows((region_id,))

    def class_report(self, *, audience: bool = False) -> str:
        """全国汇总 + 各省紧张切片（sat<=30 且 lev>=60）。

        audience=True 时满意度/势力走既有定性档（与 faction_report 同词表），
        供 simulator 等玩家可感混合调用；机面默认仍给裸值。
        """
        national = self.class_rows("")
        if not national:
            return "阶级未建档。"
        if audience:
            head = "；".join(
                f"{row['name']}满意{satisfaction_band(row['satisfaction'])}、"
                f"势力{power_band(row['leverage'])}（{row['agenda']}）"
                for row in national
            )
        else:
            head = "；".join(
                f"{row['name']}满意{row['satisfaction']}、势力{row['leverage']}（{row['agenda']}）"
                for row in national
            )
        hot = ClassStore(self.conn).read_class_report()
        if not hot:
            return f"阶级总览：{head}。各省阶级暂无高压预警。"
        if audience:
            warn = "；".join(
                f"{row['region_name'] or row['region_id']} {row['name']}"
                f"满意{satisfaction_band(row['satisfaction'])}/"
                f"势力{power_band(row['leverage'])}"
                for row in hot
            )
        else:
            warn = "；".join(
                f"{row['region_name'] or row['region_id']} {row['name']}"
                f"满意{row['satisfaction']}/势力{row['leverage']}"
                for row in hot
            )
        return f"阶级总览：{head}。高压预警：{warn}。"

    def adjust_classes(
        self,
        deltas: Dict[str, Dict[str, int]],
        commit: bool = True,
    ) -> List[Dict[str, object]]:
        """deltas 结构：{ key: {satisfaction: +/-N, leverage: +/-N} }
        key 形式：'农民' (全国) 或 '农民@shaanxi' (省级)。

        查无此阶级（名/省不匹配）→ missing_ref 逐项拒收留痕（ADR 0008 决定 1，#14/#63
        死法 3）；入参经 _apply_class_dict 预清洗。返回拒收项列表，桥接自动收。
        """
        rejected: List[Dict[str, object]] = []
        for key, fields in deltas.items():
            if not fields:
                continue
            if "@" in key:
                name, region_id = key.split("@", 1)
            else:
                name, region_id = key, ""
            row = ClassStore(self.conn).read_adjust_classes((name.strip(), region_id.strip()))
            if not row:
                rejected.append({
                    "name": key, "rejected": True, "category": "missing_ref",
                    "reason": f"class_delta 查无此阶级「{key}」（未入 classes 表）",
                    "item": {key: fields},
                })
                continue
            sat = int(row["satisfaction"]) + int(fields.get("satisfaction", 0) or 0)
            lev = int(row["leverage"]) + int(fields.get("leverage", 0) or 0)
            sat = max(0, min(100, sat))
            lev = max(0, min(100, lev))
            self.classes.set_satisfaction_leverage(
                name=name.strip(),
                region_id=region_id.strip(),
                satisfaction=sat,
                leverage=lev,
            )
        if commit:
            self.conn.commit()
        return rejected

    def power_rows(self, exclude_self: bool = False) -> List[sqlite3.Row]:
        return self.powers.rows(exclude_self)

    def power_payload(self, exclude_self: bool = False) -> List[Dict[str, object]]:
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "leader": row["leader"],
                "stance": row["stance"],
                "leverage": int(row["leverage"]),
                "satisfaction": int(row["satisfaction"]),
                "military_strength": int(row["military_strength"]),
                "cohesion": int(row["cohesion"]),
                "supply": int(row["supply"]),
                "agenda": row["agenda"],
                "status": row["status"],
                "last_action": row["last_action"],
                "aliases": row["aliases"],
            }
            for row in self.power_rows(exclude_self=exclude_self)
        ]

    def power_report(
        self, exclude_self: bool = True, kinds: Optional[Iterable[str]] = None,
        *, audience: bool = False,
    ) -> str:
        rows = self.power_rows(exclude_self=exclude_self)
        if kinds is not None:
            allowed = {str(kind).strip().lower() for kind in kinds}
            # Callers may hold canonical power ids (the content contract) or
            # display kinds (the presentation contract); both denote the same
            # filtered report set.
            rows = [row for row in rows if (
                str(row["kind"] or "").strip().lower() in allowed
                or str(row["id"] or "").strip().lower() in allowed
            )]
        if not rows:
            return "势力未建档。"
        if audience:
            return "；".join(
                f"{row['name']}（{row['leader']}）：{row['stance']}，"
                f"威望{power_band(row['leverage'])}、"
                f"实力{power_band(row['military_strength'])}、"
                f"经济{qualitative_band(row['supply'], ('匮乏', '吃紧', '尚可', '充足', '丰裕'))}，"
                f"{row['status']}；近动：{row['last_action'] or '尚无新动'}"
                for row in rows
            )
        return "；".join(
            f"{row['name']}（{row['leader']}）：{row['stance']}，威望{row['leverage']}、"
            f"实力{row['military_strength']}、经济{row['supply']}，"
            f"{row['status']}；近动：{row['last_action'] or '尚无新动'}"
            for row in rows
        )

    def effect_origin_rejection(self, origin_ref: str) -> Dict[str, object] | None:
        """Authorize extractor provenance immediately before a durable write.

        When apply_score_extraction arms ``_batch_authorized_open_affair_ids``,
        ``affair:<id>`` must also sit in that frozen batch set — one authority
        for every durable-effect carrier (fiscal included).
        """
        value = str(origin_ref or "").strip()
        valid = value == "盘面自发"
        unauthorized_batch = False
        if value.startswith("dossier:"):
            try:
                dossier_id = int(value.split(":", 1)[1])
                valid = dossier_id > 0 and self.dossiers.get(dossier_id) is not None \
                    and self.dossiers.authorizes_effects(dossier_id)
            except (OverflowError, TypeError, ValueError):
                valid = False
        elif value.startswith("affair:"):
            try:
                from ming_sim.entities.affair.store import (
                    UnauthorizedAffairOriginRef,
                    parse_origin_ref,
                )
                kind, affair_id = parse_origin_ref(value)
                if kind == "affair" and affair_id is not None:
                    self.affairs.get(int(affair_id))
                    authorized = getattr(self, "_batch_authorized_open_affair_ids", None)
                    if authorized is not None and affair_id not in authorized:
                        valid = False
                        unauthorized_batch = True
                    else:
                        valid = True
                else:
                    valid = False
            except (KeyError, OverflowError, TypeError, ValueError):
                valid = False
        if valid:
            return None
        if unauthorized_batch:
            from ming_sim.entities.affair.store import UnauthorizedAffairOriginRef
            return {
                "rejected": True,
                # Distinct from missing/invalid existence — strategic preflight
                # must not envelope-fail this; apply paths still reject itemwise.
                "category": "unauthorized_affair_origin",
                "reason": str(UnauthorizedAffairOriginRef()),
            }
        return {
            "rejected": True,
            "category": "missing_origin_ref" if not value else "invalid_origin_ref",
            "reason": ("效果缺 origin_ref；盘面自然演化须显式标为「盘面自发」"
                       if not value else f"origin_ref 非法：{value}"),
        }

    def apply_power_deltas(
        self,
        state: GameState,
        updates: Dict[str, Dict[str, object]],
        commit: bool = True,
        origin_ref: str = "",
        require_origin: bool = False,
    ) -> List[Dict[str, object]]:
        allowed_fields = {"leverage", "military_strength", "supply"}
        changes: List[Dict[str, object]] = []
        for power_id, raw_changes in updates.items():
            if power_id == "ming":
                # prompt 明文禁止写 ming——按脏数据逐项拒收留痕，与同函数其余拒收
                # 路一致（cmr S1 r2，原 print 静默跳是迁契约漏网）。
                changes.append({
                    "power_id": power_id, "rejected": True,
                    "category": "invalid_enum",
                    "reason": "power_updates 不处理大明自身（ming），prompt 明文禁止",
                    "item": {"power_id": power_id, "changes": raw_changes},
                })
                continue
            row = PowerStore(self.conn).read_apply_power_rename((power_id,))
            if row is None:
                changes.append({
                    "power_id": power_id, "rejected": True,
                    "category": "hallucinated_id",
                    "reason": f"power_updates 引用未入库势力 '{power_id}'",
                    "item": {"power_id": power_id, "changes": raw_changes},
                })
                continue
            # reason 载体按别名表扫描（近况/最近行动 等与 近动/last_action 同义，
            # 硬编码键名会漏——cmr S1 r3）：先取 reason 义，再取 last_action 义。
            reason = ""
            for _canon in ("reason", "last_action"):
                for k, v in raw_changes.items():
                    mapped = POWER_FIELD_ALIASES.get(str(k).strip(), str(k).strip())
                    if mapped == _canon and str(v or "").strip():
                        reason = str(v).strip()
                        break
                if reason:
                    break
            reason = (reason or "势力推演")[:120]
            for raw_field, value in raw_changes.items():
                field = POWER_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "last_action", "origin_ref"):
                    # reason/last_action（含 近动 等别名）是本函数上方消费的 reason
                    # 载体键——跳过，不得记成 invalid_enum 假阳（cmr S1 r2）。
                    continue
                if field not in allowed_fields:
                    changes.append({
                        "power": row["name"], "field": str(raw_field),
                        "rejected": True, "category": "invalid_enum",
                        "reason": f"power_updates 只允许 威望/实力/经济，'{raw_field}' 非法",
                        "item": {"power_id": power_id, "field": str(raw_field), "value": value},
                    })
                    continue
                old_value = row[field]
                try:
                    # LLM 叶子值脏（null/"三成"/小数串）= 脏数据逐项拒，不崩整批
                    # （validate_delta_shape 只验容器、容忍 null 叶——cmr S1 r1，
                    # 同 secret_order order_id 非整数先例）。float/bool 显式拒：
                    # int(3.7)→3 静默截断、True→1 拟真，都不是 prompt 要的整数
                    # delta（cmr S1 r2；bool 是 int 子类须先判）。
                    if isinstance(value, bool) or isinstance(value, float):
                        raise ValueError("非整数 delta")
                    delta = int(value)
                except (TypeError, ValueError):
                    changes.append({
                        "power": row["name"], "field": str(raw_field),
                        "rejected": True, "category": "invalid_enum",
                        "reason": f"power_updates '{raw_field}' 值非整数：{value!r}",
                        "item": {"power_id": power_id, "field": str(raw_field), "value": value},
                    })
                    continue
                new_value = max(0, min(100, int(old_value) + delta))
                actual_delta = new_value - int(old_value)
                if actual_delta == 0:
                    continue
                origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
                if origin_error:
                    changes.append({
                        "power": row["name"], "field": str(raw_field),
                        **origin_error,
                        "item": {"power_id": power_id, "field": str(raw_field), "value": value},
                    })
                    continue
                stored_new: object = new_value
                log_delta: int | None = actual_delta
                self.powers.update(power_id, {field: stored_new})
                self.powers.append_log({
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "power_id": power_id,
                    "field": field,
                    "old_value": str(old_value),
                    "new_value": str(stored_new),
                    "delta": log_delta,
                    "reason": reason,
                    "origin_ref": origin_ref,
                })
                changes.append({
                    "power": row["name"],
                    "field": field,
                    "label": POWER_FIELD_LABELS.get(field, field),
                    "old": old_value,
                    "new": stored_new,
                    "delta": log_delta,
                    "reason": reason,
                })
        if commit:
            self.conn.commit()
        return changes

    def apply_power_rename(
        self,
        state: GameState,
        power_id: str,
        new_name: str,
        *,
        reason: str,
        aliases: str = "",
        status: str = "",
        last_action: str = "",
        commit: bool = True,
    ) -> Dict[str, object] | None:
        """Rename a power while keeping its stable id for references.

        Used for dynastic/name changes such as houjin 后金 -> 大清.
        """
        power_id = str(power_id or "").strip()
        new_name = str(new_name or "").strip()
        if not power_id or not new_name:
            return None
        row = PowerStore(self.conn).read_apply_power_rename((power_id,))
        if row is None:
            print(f"[WARN] power_rename 引用未入库势力 '{power_id}' → 跳过")
            return None
        old_name = str(row["name"] or "")
        old_aliases = str(row["aliases"] or "")
        merged_aliases = [x.strip() for x in (aliases or old_aliases).replace("，", ",").split(",") if x.strip()]
        for alias in (old_name, new_name):
            if alias and alias not in merged_aliases:
                merged_aliases.append(alias)
        new_aliases = "，".join(merged_aliases)
        new_status = str(status or row["status"] or "")[:200]
        new_last_action = str(last_action or reason or row["last_action"] or "")[:200]
        if old_name == new_name and old_aliases == new_aliases and row["status"] == new_status and row["last_action"] == new_last_action:
            return None
        self.powers.update(power_id, {
            "name": new_name,
            "aliases": new_aliases,
            "status": new_status,
            "last_action": new_last_action,
        })
        self.powers.append_name_log({
            "turn": state.turn,
            "year": state.year,
            "period": state.period,
            "power_id": power_id,
            "old_name": old_name,
            "new_name": new_name,
            "old_aliases": old_aliases,
            "new_aliases": new_aliases,
            "reason": reason[:200],
        })
        if commit:
            self.conn.commit()
        return {
            "power_id": power_id,
            "old_name": old_name,
            "new_name": new_name,
            "old_aliases": old_aliases,
            "new_aliases": new_aliases,
            "reason": reason,
        }

    def turn_power_summary(self, turn: int, limit: int = 10) -> str:
        rows = PowerStore(self.conn).read_turn_power_summary((turn, limit))
        if not rows:
            return f"本{TURN_UNIT}势力无明确变化。"
        parts = []
        for row in rows:
            label = POWER_FIELD_LABELS.get(str(row["field"]), str(row["field"]))
            delta = row["delta"]
            if delta is None:
                parts.append(f"{row['power_name']}{label}改为{row['new_value']}（{row['reason']}）")
            else:
                sign = "+" if int(delta) > 0 else ""
                parts.append(f"{row['power_name']}{label}{sign}{int(delta)}（{row['reason']}）")
        return "；".join(parts) + "。"

    def region_payload(self, limit: int | None = None, danger_order: bool = False) -> List[Dict[str, object]]:
        payload: List[Dict[str, object]] = []
        for row in self.regions.rows(limit=limit, danger_order=danger_order):
            payload.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "population": int(row["population"]),
                    "public_support": int(row["public_support"]),
                    "unrest": int(row["unrest"]),
                    "natural_disaster": row["natural_disaster"],
                    "human_disaster": row["human_disaster"],
                    "registered_land": int(row["registered_land"]),
                    "hidden_land": int(row["hidden_land"]),
                    "tax_per_turn": int(row["tax_per_turn"]),
                    "grain_security": int(row["grain_security"]),
                    "gentry_resistance": int(row["gentry_resistance"]),
                    "military_pressure": int(row["military_pressure"]),
                    "status": row["status"],
                    "controlled_by": row["controlled_by"],
                }
            )
        return payload

    def power_display_name(self, power_id: str) -> str:
        """power_id → 显示名（如 houjin→后金）。缺则回退 id。"""
        row = PowerStore(self.conn).read_power_display_name((str(power_id),))
        return str(row["name"]) if row else str(power_id)

    def region_report(self, limit: int = 5) -> str:
        rows = self.regions.rows(limit=limit, danger_order=True)
        if not rows:
            return "地区尚未建档。"
        total_tax = RegionStore(self.conn).read_region_report()
        total_tax_value = int(total_tax["total"] or 0)
        parts = []
        for row in rows:
            held = ""
            if str(row["controlled_by"]) != "ming":
                held = f"【已为{self.power_display_name(row['controlled_by'])}所据】"
            defense = f"，城防炮{int(row['cannon'])}门" if int(row["cannon"] or 0) > 0 else ""
            parts.append(
                f"{row['name']}{held}：{_public_support_description(row['public_support'])}，"
                f"{_unrest_description(row['unrest'])}，"
                f"粮情{qualitative_band(row['grain_security'], ('告急', '偏紧', '平稳', '充裕', '丰足'))}，"
                f"税{format_money(monthly_amount(int(row['tax_per_turn'])))}/{TURN_UNIT}{defense}，{row['status']}"
            )
        return f"地区警讯：{'；'.join(parts)}。两京十三省账面{TURN_UNIT}税合计{format_money(monthly_amount(total_tax_value))}。"

    def region_detail(self, raw_name: str, qualitative: bool = False) -> str:
        region_id = match_region_id_from_text(raw_name, self.content.regions)
        if region_id is None:
            raise ValueError(f"未找到地区：{raw_name}")
        row = self.regions.row(region_id)
        if row is None:
            raise ValueError(f"地区未入库：{raw_name}")
        held = ""
        if str(row["controlled_by"]) != "ming":
            held = f"，控制权：已为{self.power_display_name(row['controlled_by'])}所据（非大明辖治）"
        # 人口存储是人。玩家面投影「约N万口」；机面写裸人数。
        pop_qual = f"人口{population_wan_kou_label(row['population'])}"
        pop_raw = f"人口{row['population']}人"
        if qualitative:
            return (
                f"{row['name']}（{row['kind']}）{held}：{pop_qual}，"
                f"{_public_support_description(row['public_support'])}，"
                f"{_unrest_description(row['unrest'])}，粮食{row['grain_security']}万石，"
                f"田亩{row['registered_land']}万亩，隐田{row['hidden_land']}万亩，"
                f"账面税收{format_money(monthly_amount(int(row['tax_per_turn'])))}/{TURN_UNIT}，"
                f"士绅阻力{gentry_resistance_band(row['gentry_resistance'])}，"
                f"军事压力{military_pressure_band(row['military_pressure'])}，"
                f"城防{city_defense_description(row['city_level'])}，"
                f"城防大炮{int(row['cannon'])}门。天灾：{row['natural_disaster']}；"
                f"人祸：{row['human_disaster']}；状态：{row['status']}"
            )
        return (
            f"{row['name']}（{row['kind']}）{held}：{pop_raw}，"
            f"民心{row['public_support']}，动乱{row['unrest']}，粮食{row['grain_security']}万石，"
            f"田亩{row['registered_land']}万亩，隐田{row['hidden_land']}万亩，"
            f"账面税收{format_money(monthly_amount(int(row['tax_per_turn'])))}/{TURN_UNIT}，"
            f"士绅阻力{row['gentry_resistance']}，军事压力{row['military_pressure']}，"
            f"城市等级{int(row['city_level'])}（城防炮上限{int(row['city_level']) * 8}门），城防大炮{int(row['cannon'])}门。"
            f"天灾：{row['natural_disaster']}；人祸：{row['human_disaster']}；状态：{row['status']}"
        )

    def turn_region_summary(self, turn: int, limit: int = 10) -> str:
        rows = RegionStore(self.conn).read_turn_region_summary((turn, limit))
        if not rows:
            return f"本{TURN_UNIT}地区盘面无明确变化。"
        parts = []
        for row in rows:
            label = REGION_FIELD_LABELS.get(str(row["field"]), str(row["field"]))
            delta = row["delta"]
            if delta is None:
                parts.append(f"{row['region_name']}{label}改为{row['new_value']}（{row['reason']}）")
            else:
                sign = "+" if int(delta) > 0 else ""
                parts.append(f"{row['region_name']}{label}{sign}{int(delta)}（{row['reason']}）")
        return "；".join(parts) + "。"

    def apply_region_deltas(
        self,
        state: GameState,
        event: Event,
        edict_id: int | None,
        actor: str,
        region_deltas: Dict[str, Dict[str, object]],
        commit: bool = True,
        origin_ref: str = "",
        require_origin: bool = False,
    ) -> List[Dict[str, object]]:
        changes: List[Dict[str, object]] = []
        for region_id, raw_changes in region_deltas.items():
            row = self.regions.row(region_id)
            if row is None:
                # ADR 0008 决定 1:LLM 幻觉地区 id = 逐项拒收留痕,不再 print 静默跳;
                # 坏一项不带走整批(同信封好地区照落)。
                changes.append({
                    "region_id": region_id, "rejected": True,
                    "category": "missing_ref",
                    "reason": f"region_delta 引用未入库地区 '{region_id}'",
                    "item": {"region_id": region_id, "changes": raw_changes},
                    # 历史 print-skip → convention 一致补标（当前 issue 路不走 region,
                    # 防未来接入时误升级——cmr S2 r2 claude P3）。
                    "issue_strict": False,
                })
                continue
            reason = str(raw_changes.get("reason") or raw_changes.get("原因") or event.title).strip()[:80]
            for raw_field, value in raw_changes.items():
                field = REGION_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "origin_ref"):
                    continue

                # ── 城防炮（城头红夷炮）：另挂 region.cannon，走 apply_region_cannon（clamp city_level×8），
                #    不入通用 SCORE/QUANTITY 路径（通用路径不套城防上限，会破 P2 铁律）。──
                if field == "cannon":
                    # 脏炮值守门与通用数值路对称（cmr S2 r1，3票）：cannon 不在
                    # SCORE/QUANTITY 集,通用守门罩不到——此处先验再 dispatch,
                    # 否则裸 int(value) 让 null/"数十门" 崩整月、bool/float 静默拟真。
                    try:
                        if isinstance(value, bool) or isinstance(value, float):
                            raise ValueError("非整数 delta")
                        cannon_delta = int(value)
                    except (TypeError, ValueError):
                        changes.append({
                            "region": row["name"], "field": field,
                            "rejected": True, "category": "invalid_enum",
                            "reason": f"region_delta 'cannon'（地区 '{region_id}'）值非整数：{value!r}",
                            "item": {"region_id": region_id, "field": field, "value": value},
                            "issue_strict": not isinstance(value, (bool, float)),  # 同上 convention
                        })
                        continue
                    old_value = int(row["cannon"])
                    if cannon_delta != 0 and require_origin:
                        origin_error = self.effect_origin_rejection(origin_ref)
                        if origin_error:
                            changes.append({"region": row["name"], "field": field, **origin_error,
                                            "item": {"region_id": region_id, "field": field, "value": value}})
                            continue
                    new_value = self.apply_region_cannon(state, region_id, cannon_delta)
                    actual_delta = new_value - old_value
                    if actual_delta == 0:
                        # 请求非 0 却被 clamp 成 no-op：不能静默 continue——邸报叙述了改炮、盘面无变化、
                        # restore 只读 DB 接续不到这条决策＝违 P1 落库铁律（#18，issue #14 静默吞家族）。
                        # 记一条 delta=0 的 region_log 留痕。真 no-op 请求（cannon_delta==0）无须留痕避噪。
                        # 区分上/下限钳制（codex+CodeRabbit R1 concur）：请求加炮(>0)=撞 city_level×8 上限；
                        # 请求减炮(<0)却 no-op=已无炮可减（下限 0），缘由不能一律归「上限」。
                        if cannon_delta != 0:
                            _cap = int(row["city_level"]) * 8
                            if cannon_delta > 0:
                                _clamp_reason = (
                                    f"{reason}（城防炮请求+{cannon_delta}门被城防上限拦截："
                                    f"城市等级{int(row['city_level'])}→上限{_cap}门，已达上限无变化）"
                                )
                            else:
                                _clamp_reason = (
                                    f"{reason}（城防炮请求{cannon_delta}门但已无炮可减"
                                    f"（现{old_value}门），无变化）"
                                )
                            self.regions.append_log({
                                "turn": state.turn,
                                "year": state.year,
                                "period": state.period,
                                "region_id": region_id,
                                "field": field,
                                "old_value": str(old_value),
                                "new_value": str(new_value),
                                "delta": 0,
                                "reason": _clamp_reason,
                                "event_id": event.id,
                                "edict_id": edict_id,
                                "actor": actor,
                                "origin_ref": origin_ref,
                            })
                            changes.append({
                                "region": row["name"], "field": field,
                                "label": REGION_FIELD_LABELS.get(field, field),
                                "old": old_value, "new": new_value,
                                "delta": 0, "reason": _clamp_reason, "clamped": True,
                            })
                        continue
                    self.regions.append_log({
                        "turn": state.turn,
                        "year": state.year,
                        "period": state.period,
                        "region_id": region_id,
                        "field": field,
                        "old_value": str(old_value),
                        "new_value": str(new_value),
                        "delta": actual_delta,
                        "reason": reason,
                        "event_id": event.id,
                        "edict_id": edict_id,
                        "actor": actor,
                        "origin_ref": origin_ref,
                    })
                    changes.append({
                        "region": row["name"], "field": field,
                        "label": REGION_FIELD_LABELS.get(field, field),
                        "old": old_value, "new": new_value,
                        "delta": actual_delta, "reason": reason,
                    })
                    continue

                # ADR 0008 决定 1:LLM 引用非法地区字段 = 逐项拒收留痕(invalid_enum),
                # 不再 raise 崩整月;同地区的合法字段照落,坏一项不带走整批。
                if field not in _REGION_DIRECT_SET and field not in FISCAL_SCORE_FIELDS:
                    changes.append({
                        "region": row["name"], "field": str(raw_field),
                        "rejected": True, "category": "invalid_enum",
                        "reason": (
                            f"region_delta 引用非法地区字段 '{raw_field}'（地区 '{region_id}'）；"
                            f"合法字段：{_REGION_DIRECT_TUPLE + FISCAL_SCORE_FIELDS}"
                        ),
                        "item": {"region_id": region_id, "field": str(raw_field), "value": value},
                    })
                    continue

                # ADR 0008 决定 1:数值字段(fiscal/score/quantity)的脏叶子值
                # (null/字符串/float/bool)= LLM 脏数据,逐项拒收(invalid_enum),不让
                # 裸 int(value) 崩整月;bool 是 int 子类、float 静默截断,都非整数 delta
                # 须显式拒(对称 S1)。text 字段走 str(),不在此判。
                if field in _REGION_NUMERIC_SET or field in FISCAL_SCORE_FIELDS:
                    try:
                        if isinstance(value, bool) or isinstance(value, float):
                            raise ValueError("非整数 delta")
                        value = int(value)
                    except (TypeError, ValueError):
                        changes.append({
                            "region": row["name"], "field": field,
                            "rejected": True, "category": "invalid_enum",
                            "reason": f"region_delta '{raw_field}'（地区 '{region_id}'）值非整数：{value!r}",
                            "item": {"region_id": region_id, "field": field, "value": value},
                            # float/bool 历史静默套用=可活;None/串历史 int() 致命=严格
                            # （convention 对称 army,防未来 issue 路接入误升级;ship-pre r1）。
                            "issue_strict": not isinstance(value, (bool, float)),
                        })
                        continue

                # ── fiscal JSON 子字段（corruption 等）────────────────────────
                if field in FISCAL_SCORE_FIELDS:
                    fiscal: dict = load_stored_object(row["fiscal"], label='fiscal')
                    old_value = fiscal.get(field, 50)
                    delta = int(value)
                    # 帝国修正：该地区该字段若有 active 修正符，先放大/缩小 delta
                    net_pct = int(((self.legacy_modifiers(state).get("regions") or {})
                                   .get(region_id) or {}).get(field, 0) or 0)
                    if net_pct:
                        delta = self.apply_legacy_pct(delta, net_pct)
                    new_value = max(0, min(100, int(old_value) + delta))
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    if require_origin:
                        origin_error = self.effect_origin_rejection(origin_ref)
                        if origin_error:
                            changes.append({"region": row["name"], "field": field, **origin_error,
                                            "item": {"region_id": region_id, "field": field, "value": value}})
                            continue
                    fiscal[field] = new_value
                    self.regions.update(
                        region_id,
                        {"fiscal": json.dumps(fiscal, ensure_ascii=False)},
                    )
                    self.regions.append_log({
                        "turn": state.turn,
                        "year": state.year,
                        "period": state.period,
                        "region_id": region_id,
                        "field": field,
                        "old_value": str(old_value),
                        "new_value": str(new_value),
                        "delta": actual_delta,
                        "reason": reason,
                        "event_id": event.id,
                        "edict_id": edict_id,
                        "actor": actor,
                        "origin_ref": origin_ref,
                    })
                    changes.append({
                        "region": row["name"], "field": field,
                        "label": REGION_FIELD_LABELS.get(field, field),
                        "old": old_value, "new": new_value,
                        "delta": actual_delta, "reason": reason,
                    })
                    continue

                # ── 直接列字段 ────────────────────────────────────────────────
                old_value = row[field]
                if field in REGION_SCORE_FIELDS:
                    delta = int(value)
                    # 遗产百分比修正：该地区该字段若有 active 遗产修正符，先放大/缩小 delta
                    net_pct = int(((self.legacy_modifiers(state).get("regions") or {})
                                   .get(region_id) or {}).get(field, 0) or 0)
                    if net_pct:
                        delta = self.apply_legacy_pct(delta, net_pct)
                    new_value = max(0, min(100, int(old_value) + delta))
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new: object = new_value
                    log_delta: int | None = actual_delta
                elif field in REGION_QUANTITY_FIELDS:
                    delta = int(value)
                    new_value = max(0, int(old_value) + delta)
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                else:  # REGION_TEXT_FIELDS
                    text_value = str(value).strip()[:160]
                    if field == "controlled_by":
                        if (
                            value is None
                            or not text_value
                            or text_value.lower() == "null"
                            or PowerStore(self.conn).read_strategic_event_result_preflight_error((text_value,)) is None
                        ):
                            changes.append({
                                "region": row["name"], "field": field,
                                "rejected": True, "category": "invalid_enum",
                                "reason": (
                                    f"region_delta 'controlled_by'（地区 '{region_id}'）"
                                    f"必须是 powers.id 中的非空真实势力 id：{value!r}"
                                ),
                                "item": {"region_id": region_id, "field": field, "value": value},
                            })
                            continue
                    if not text_value or text_value == str(old_value):
                        continue
                    if require_origin:
                        origin_error = self.effect_origin_rejection(origin_ref)
                        if origin_error:
                            changes.append({"region": row["name"], "field": field, **origin_error,
                                            "item": {"region_id": region_id, "field": field, "value": value}})
                            continue
                    stored_new = text_value
                    log_delta = None
                if require_origin and field not in REGION_TEXT_FIELDS:
                    origin_error = self.effect_origin_rejection(origin_ref)
                    if origin_error:
                        changes.append({"region": row["name"], "field": field, **origin_error,
                                        "item": {"region_id": region_id, "field": field, "value": value}})
                        continue
                self.regions.update(region_id, {field: stored_new})
                self.regions.append_log({
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "region_id": region_id,
                    "field": field,
                    "old_value": str(old_value),
                    "new_value": str(stored_new),
                    "delta": log_delta,
                    "reason": reason,
                    "event_id": event.id,
                    "edict_id": edict_id,
                    "actor": actor,
                    "origin_ref": origin_ref,
                })
                changes.append(
                    {
                        "region": row["name"], "field": field,
                        "label": REGION_FIELD_LABELS.get(field, field),
                        "old": old_value, "new": stored_new,
                        "delta": log_delta, "reason": reason,
                    }
                )

                # ── 收复触发：controlled_by 由非 ming → ming，覆盖 on_restore 预置 ──
                if (
                    field == "controlled_by"
                    and str(stored_new) == "ming"
                    and str(old_value) != "ming"
                ):
                    extra = self._apply_on_restore(
                        state, region_id, event, edict_id, actor, reason,
                        origin_ref=origin_ref,
                    )
                    changes.extend(extra)
        if commit:
            self.conn.commit()
        return changes

    def _apply_on_restore(
        self,
        state: GameState,
        region_id: str,
        event: Event,
        edict_id: int | None,
        actor: str,
        reason: str,
        origin_ref: str = "",
    ) -> List[Dict[str, object]]:
        """收复瞬间用 region.on_restore 覆盖主字段，记 region_logs。"""
        region_def = self.content.regions.get(region_id)
        if region_def is None or not region_def.on_restore:
            return []
        preset = region_def.on_restore
        row = self.regions.row(region_id)
        if row is None:
            return []
        all_direct = REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + REGION_TEXT_FIELDS
        out: List[Dict[str, object]] = []
        for raw_field, value in preset.items():
            if raw_field == "fiscal":
                if not isinstance(value, dict):
                    continue
                fiscal = load_stored_object(row["fiscal"], label='fiscal')
                for sub_field, sub_val in value.items():
                    if sub_field not in FISCAL_SCORE_FIELDS:
                        continue
                    old_sub = fiscal.get(sub_field, 0)
                    new_sub = int(sub_val)
                    if int(old_sub) == new_sub:
                        continue
                    fiscal[sub_field] = new_sub
                    self.regions.append_log({
                        "turn": state.turn,
                        "year": state.year,
                        "period": state.period,
                        "region_id": region_id,
                        "field": sub_field,
                        "old_value": str(old_sub),
                        "new_value": str(new_sub),
                        "delta": new_sub - int(old_sub),
                        "reason": f"收复重置：{reason}",
                        "event_id": event.id,
                        "edict_id": edict_id,
                        "actor": actor,
                        "origin_ref": origin_ref,
                    })
                    out.append({
                        "region": row["name"], "field": sub_field,
                        "label": REGION_FIELD_LABELS.get(sub_field, sub_field),
                        "old": old_sub, "new": new_sub,
                        "delta": new_sub - int(old_sub), "reason": f"收复重置：{reason}",
                    })
                self.regions.update(
                    region_id,
                    {"fiscal": json.dumps(fiscal, ensure_ascii=False)},
                )
                continue
            if raw_field == "controlled_by":
                continue  # 控制权已写完，跳过
            if raw_field not in all_direct:
                continue
            old_val = row[raw_field]
            if raw_field in (REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS):
                new_val: object = int(value)
            else:
                new_val = str(value)
            if str(old_val) == str(new_val):
                continue
            self.regions.update(region_id, {raw_field: new_val})
            log_delta = (int(new_val) - int(old_val)) if raw_field in (REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS) else None
            self.regions.append_log({
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "region_id": region_id,
                "field": raw_field,
                "old_value": str(old_val),
                "new_value": str(new_val),
                "delta": log_delta,
                "reason": f"收复重置：{reason}",
                "event_id": event.id,
                "edict_id": edict_id,
                "actor": actor,
                "origin_ref": origin_ref,
            })
            out.append({
                "region": row["name"], "field": raw_field,
                "label": REGION_FIELD_LABELS.get(raw_field, raw_field),
                "old": old_val, "new": new_val,
                "delta": log_delta, "reason": f"收复重置：{reason}",
            })
        return out

    def _army_pay(self, row) -> int:
        """#173 显示口径：军「月饷」呈现统一取引擎实扣应发 army_needed（替退役 maintenance_per_turn）。
        懒 import 避免 db↔flows 顶层循环依赖（同 compute_budget_lines 先例）。非明军 → 0。"""
        from ming_sim.flows import army_needed
        return army_needed(row)

    def army_rows(self, limit: int | None = None, danger_order: bool = False) -> List[sqlite3.Row]:
        # #173：danger 排序的欠饷月数归一改按引擎实扣应发 army_needed（替退役 maintenance_per_turn）。
        # army_needed 是 Python 公式（ceil + ming-only + 锚点，SQL 难复现），故 danger 排序在 Python 做；
        # 非 danger 路只按 theater,name 排序、不涉 army_needed，仍走 SQL ORDER BY/LIMIT（线上 gemini perf）。
        if not danger_order:
            sql = "SELECT * FROM armies ORDER BY theater, name"
            params: Tuple[object, ...] = ()
            if limit is not None:
                sql += " LIMIT ?"
                params = (limit,)
            return self.conn.execute(sql, params).fetchall()
        def _danger_key(r):
            # arrears 累计欠饷万两，按月应发归一成"欠饷月数*10"（截至 100），与各 0-100 短板相加。
            # 用浮点归一（排序键，不截断小数；线上 gemini）；arrears 虽 NOT NULL 仍 `or 0` 防御。
            pay = self._army_pay(r)
            arr = float(r["arrears"] or 0)
            arrears_norm = min(100.0, arr * 10.0 / pay) if pay > 0 else 0.0
            danger = (arrears_norm + (100 - int(r["supply"])) + (100 - int(r["morale"]))
                      + (100 - int(r["loyalty"])) + (100 - int(r["training"])))
            return (-danger, str(r["name"]))  # danger 降序、name 升序（同原 SQL ... DESC, name）
        rows = sorted(ArmyStore(self.conn).read_army_rows(), key=_danger_key)
        return rows[:limit] if limit is not None else rows

    def army_payload(self, limit: int | None = None, danger_order: bool = False) -> List[Dict[str, object]]:
        payload: List[Dict[str, object]] = []
        for row in self.army_rows(limit=limit, danger_order=danger_order):
            pay = self._army_pay(row)
            sit = _player_army_situation(row, pay)
            payload.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "station": row["station"],
                    "theater": row["theater"],
                    "commander": row["commander"],
                    "controller": row["controller"],
                    "troop_type": row["troop_type"],
                    "manpower": int(row["manpower"]),
                    # #173：引擎实扣月应发（呈现层「月饷」唯一真源）。维护费列已删。
                    "army_needed": pay,
                    "supply": int(row["supply"]),
                    # #321：军心/士气/欠饷走玩家投影字符串；禁 raw morale/loyalty/arrears。
                    "morale_text": sit["morale_text"],
                    "training": int(row["training"]),
                    "equipment": int(row["equipment"]),
                    "arrears_text": sit["arrears_text"],
                    "mobility": int(row["mobility"]),
                    "mutiny_tier": sit["mutiny_tier"],
                    "firearm_equipment": int(row["firearm_equipment"]),
                    "cannon_equipment": int(row["cannon_equipment"]),
                    # #1501：军牌专属投影停携静态 status 句；
                    # DB armies.status 与共享读者 army_report 仍保留原句，不在此投影。
                    "owner_power": row["owner_power"],
                }
            )
        return payload

    def army_pay_theoretical_total(self) -> int:
        """全军（明军）月度名义应发军饷合计；army_report 文本与玩家户部结算前投影共用同一计算
        （#1366：户部「各军军饷」与警讯月应发口径不一致的根因即两处各自求和，改共用此源）。"""
        return monthly_amount(
            sum(self._army_pay(r) for r in ArmyStore(self.conn).read_army_rows())
        )

    def army_report(self, limit: int = 5) -> str:
        rows = self.army_rows(limit=limit, danger_order=True)
        if not rows:
            return "军队尚未建档。"
        total_manpower = ArmyStore(self.conn).read_army_report()
        # #173：月饷总额按引擎实扣应发 army_needed 之和（替退役 maintenance_per_turn 之和）。
        total_pay = self.army_pay_theoretical_total()
        parts = []
        for row in rows:
            pay = self._army_pay(row)
            sit = _player_army_situation(row, pay)
            parts.append(
                f"{row['name']}：驻{row['station']}，兵{row['manpower']}，"
                f"饷{format_money(monthly_amount(pay))} /{TURN_UNIT}，"
                f"{_qualitative_army_stat('supply', row['supply'])}，"
                f"{sit['morale_text']}，军心：{sit['mutiny_tier']}，"
                f"火器：{_qualitative_army_stat('equipment', row['firearm_equipment']).removeprefix('装备：')}，"
                f"炮{row['cannon_equipment']}门，{sit['arrears_text']}，{row['status']}"
            )
        return (
            f"军队警讯：{'；'.join(parts)}。"
            f"建档兵力合计{int(total_manpower['total'] or 0)}人，"
            f"{TURN_UNIT}名义应发军饷合计{format_money(monthly_amount(total_pay))}。"
        )

    def army_detail(self, raw_name: str) -> str:
        # 先按 DB id/name 直查（含动态 new_armies 建出的、不在静态 content.armies 的军队），
        # 再退回静态别名模糊匹配（如「关宁军」→ guanning）。SELECT * 渲染含火器/随军大炮，
        # 故新军详情 read 也闭合（CMR codexB/C：army render 收敛到此单一真源，杀 read 侧 whack-a-mole）。
        row = ArmyStore(self.conn).read_army_detail((raw_name, raw_name))
        if row is None:
            army_id = match_army_id_from_text(raw_name, self.content.armies)
            if army_id is not None:
                row = self.armies.row(army_id)
        if row is None:
            raise ValueError(f"未找到军队：{raw_name}")
        pay = self._army_pay(row)  # #173：月饷取引擎实扣应发
        sit = _player_army_situation(row, pay)
        return (
            f"{row['name']}：驻扎地{row['station']}，统帅{row['commander']}，"
            f"兵种{row['troop_type']}，人数{row['manpower']}人，"
            f"月应发军饷{format_money(monthly_amount(pay))} /{TURN_UNIT}，"
            f"{_qualitative_army_stat('supply', row['supply'])}，"
            f"{sit['morale_text']}，"
            f"{_qualitative_army_stat('training', row['training'])}，"
            f"{_qualitative_army_stat('equipment', row['equipment'])}，"
            f"火器{row['firearm_equipment']}，随军大炮{row['cannon_equipment']}门，"
            f"{sit['arrears_text']}，{_qualitative_army_stat('mobility', row['mobility'])}，"
            f"军心：{sit['mutiny_tier']}。"
            f"状态：{row['status']}"
        )

    def army_roster(
        self,
        filter_names: Optional[List[str]] = None,
        qualitative_equipment: bool = False,
    ) -> str:
        """全军名册；大臣上下文可将火器装备以定性词呈现。"""
        rows = ArmyStore(self.conn).read_army_roster()
        if filter_names:
            rows = [r for r in rows if r["name"] in filter_names or r["id"] in filter_names]
        if not rows:
            return ""
        own: List[str] = []
        other: List[str] = []
        for row in rows:
            # #173：月饷取引擎实扣应发 army_needed（替退役 maintenance_per_turn）。全按月度，不除 3。
            monthly_pay = self._army_pay(row)
            sit = _player_army_situation(row, monthly_pay)
            if str(row["owner_power"]) == "ming":
                # 列序见表头。兵力/月饷为真钱；士气/军心/欠饷走 #321 玩家投影。
                own.append(
                    "|".join(str(x) for x in (
                        row["name"], row["station"], row["commander"], row["troop_type"],
                        row["manpower"], monthly_pay,
                        _qualitative_army_stat("supply", row["supply"]),
                        sit["morale_text"],
                        _qualitative_army_stat("training", row["training"]),
                        _qualitative_army_stat("equipment", row["equipment"]),
                        _qualitative_army_stat("mobility", row["mobility"]),
                        sit["mutiny_tier"],
                        sit["arrears_text"], row["status"],
                        f"火器：{_qualitative_army_stat('equipment', row['firearm_equipment']).removeprefix('装备：')}"
                        if qualitative_equipment else row["firearm_equipment"],
                        row["cannon_equipment"],
                    ))
                )
            else:
                other.append(
                    "|".join(str(x) for x in (
                        row["name"], row["owner_power"], row["station"],
                        row["commander"], row["troop_type"], row["manpower"], row["status"],
                    ))
                )
        out = [
            "【全军名册（现状以此为准，谈某军欠饷/补给/士气直接据此；欠饷为奏报近似总额，不拆省/中央分账）】",
            (
                "大明各军（| 分隔，列序＝军名|驻地|统帅|兵种|兵力|月饷万两|补给|士气|训练|装备|机动|军心|欠饷奏报|状态|火器|随军大炮；补给…军心为定性奏报，火器为定性装备，随军大炮为门数0-12）："
                if qualitative_equipment else
                "大明各军（| 分隔，列序＝军名|驻地|统帅|兵种|兵力|月饷万两|补给|士气|训练|装备|机动|军心|欠饷奏报|状态|火器|随军大炮；补给…军心为定性奏报，火器为0-100，随军大炮为门数0-12）："
            ),
            *own,
        ]
        if other:
            out.append("敌对/外藩军（可见情报，列序＝军名|势力|驻地|统帅|兵种|兵力|状态）：")
            out.extend(other)
        return "\n".join(out)

    def turn_army_summary(self, turn: int, limit: int = 10) -> str:
        rows = ArmyStore(self.conn).read_turn_army_summary((turn, limit))
        if not rows:
            return f"本{TURN_UNIT}军队盘面无明确变化。"
        parts = []
        for row in rows:
            label = ARMY_FIELD_LABELS.get(str(row["field"]), str(row["field"]))
            delta = row["delta"]
            if delta is None:
                parts.append(f"{row['army_name']}{label}改为{row['new_value']}（{row['reason']}）")
            else:
                delta_num = float(delta)
                sign = "+" if delta_num > 0 else ""
                if row["field"] == "manpower":
                    parts.append(f"{row['army_name']}{label}{sign}{int(delta_num)}人（{row['reason']}）")
                else:
                    # #1383：非整数 delta（省源欠饷等）走万两收整单真源，杜绝 :g IEEE 残渣
                    delta_text = format_wanliang_amount(delta_num)
                    parts.append(f"{row['army_name']}{label}{sign}{delta_text}（{row['reason']}）")
        return "；".join(parts) + "。"

    def apply_army_deltas(
        self,
        state: GameState,
        event: Event,
        edict_id: int | None,
        actor: str,
        army_deltas: Dict[str, Dict[str, object]],
        commit: bool = True,
        origin_ref: str = "",
        require_origin: bool = False,
    ) -> List[Dict[str, object]]:
        changes: List[Dict[str, object]] = []
        for army_id, raw_changes in army_deltas.items():
            row = self.armies.row(army_id)
            if row is None:
                # ADR 0008 决定 1:LLM 幻觉军队 id = 逐项拒收留痕(missing_ref),不再
                # raise 崩整月;同信封好军队照落,坏一项不带走整批(原意「先建军」由
                # new_armies 段负责,此处只拒补兵/改属性的悬空引用)。
                changes.append({
                    "army_id": army_id, "rejected": True,
                    "category": "missing_ref",
                    "reason": f"army_delta 引用未入库军队 '{army_id}'（补兵/改属性落不了，先建军）",
                    "item": {"army_id": army_id, "changes": raw_changes},
                })
                continue
            reason = str(raw_changes.get("reason") or raw_changes.get("原因") or event.title).strip()[:80]
            self._apply_army_pay_source_delta(
                state, event, edict_id, actor, row, raw_changes, reason, changes,
                origin_ref=origin_ref, require_origin=require_origin,
            )
            row = self.armies.row(army_id)
            # #320：同军同事件内 loyalty 规范键与别名只消费一次——先合计合法整数增量，
            # 通用环内落地一次 ±15 软钳，避免 {loyalty:50, 军心:50} 双键绕过单事件预算。
            loyalty_canonical_delta = fold_loyalty_alias_delta(raw_changes)
            loyalty_soft_consumed = False
            for raw_field, value in raw_changes.items():
                field = ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "origin_ref"):
                    continue
                if field in _ARMY_PAY_SOURCE_DELTA_FIELDS:
                    continue
                if field not in _ARMY_VALID_SET:
                    # ADR 0008 决定 1:LLM 引用非法军队字段 = 逐项拒收留痕(invalid_enum),
                    # 不再 print 静默跳;同军队的合法字段照落,坏一项不带走整批。
                    changes.append({
                        "army": row["name"], "field": str(raw_field),
                        "rejected": True, "category": "invalid_enum",
                        "reason": f"army_delta 引用非法字段 '{raw_field}'",
                        "item": {"army_id": army_id, "field": str(raw_field), "value": value},
                        # 历史上此案是 print-skip（非 raise）——国策结案路不升级为
                        # 崩月（cmr S2 r1 claude:「维持原行为」当真）。
                        "issue_strict": False,
                    })
                    continue
                # ADR 0008 决定 1:数值字段的脏叶子值(null/字符串/float/bool)= LLM 脏数据,
                # 逐项拒收(invalid_enum),不让裸 int(value) 崩整月;bool 是 int 子类、float
                # 静默截断须显式拒(对称 S1/region)。text 字段走 str(),不在此判。
                if field not in ARMY_TEXT_FIELDS:
                    try:
                        if isinstance(value, bool) or isinstance(value, float):
                            raise ValueError("非整数 delta")
                        value = int(value)
                    except (TypeError, ValueError):
                        changes.append({
                            "army": row["name"], "field": field,
                            "rejected": True, "category": "invalid_enum",
                            "reason": f"army_delta '{raw_field}' 值非整数：{value!r}",
                            "item": {"army_id": army_id, "field": field, "value": value},
                            # float/bool 改前是静默套用（int(3.7)=3 照落）=历史可活,
                            # issue 路容忍;None/字符串历史就 raise,保持严格（cmr S2 r3,2/2）。
                            "issue_strict": not isinstance(value, (bool, float)),
                        })
                        continue
                current_row = self.armies.row(army_id)
                if current_row is not None:
                    row = current_row
                # #319 ADR 0025 D4①：latched 军字段-效果 deny-by-default。
                # 白名单：manpower 严格负增量、loyalty 正 raw（post-mod 方向见 score 分支）；
                # 其余已归一可写字段静默 no-op。owner_power 已由上方 adapter 处理，不重入本门。
                # 门在类型/合法字段校验之后，避免把 invalid_enum 伪装成 mutiny no-op。
                if bool(row["is_mutinied"]) and not latched_army_field_effect_permitted(field, value):
                    continue
                old_value = row[field]
                if field == "arrears":
                    delta = int(value)
                    if delta < 0:
                        changes.append({
                            "army": row["name"], "field": field,
                            "rejected": True, "category": "invalid_enum",
                            "reason": "army_delta.arrears 不接受负值核销；真补饷须走 economy_moves",
                            "item": {"army_id": army_id, "field": field, "value": value},
                            "issue_strict": False,
                        })
                        continue
                    if delta == 0:
                        continue
                    if (
                        str(row["owner_power"]) != "ming"
                        or bool(row["is_tusi"])
                        or bool(row["self_funded_pay"])
                    ):
                        changes.append({
                            "army": row["name"], "field": field,
                            "rejected": True, "category": "invalid_enum",
                            "reason": "army_delta.arrears 不接受自养/非明军加欠；双累加器恒为 0",
                            "item": {"army_id": army_id, "field": field, "value": value},
                            "issue_strict": False,
                        })
                        continue
                    if int(row["manpower"] or 0) <= 0:
                        changes.append({
                            "army": row["name"], "field": field,
                            "rejected": True, "category": "invalid_enum",
                            "reason": "army_delta.arrears 不接受零兵军队加欠；兵力归零欠饷已核销",
                            "item": {"army_id": army_id, "field": field, "value": value},
                            "issue_strict": False,
                        })
                        continue
                    self._validate_pay_source_values(
                        army_id, str(row["owner_power"]), str(row["pay_source_region"]),
                        float(row["province_pay_share"] or 0), float(row["central_pay_share"] or 0),
                        bool(row["is_tusi"]), bool(row["self_funded_pay"]),
                        float(row["province_pay_arrears"] or 0), float(row["central_pay_arrears"] or 0),
                    )
                    province_delta = delta * float(row["province_pay_share"] or 0)
                    central_delta = delta * float(row["central_pay_share"] or 0)
                    new_province = float(row["province_pay_arrears"] or 0) + province_delta
                    new_central = float(row["central_pay_arrears"] or 0) + central_delta
                    new_value = new_province + new_central
                    origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
                    if origin_error:
                        changes.append({"army": row["name"], "field": field, **origin_error,
                                        "item": {"army_id": army_id, "field": field, "value": value}})
                        continue
                    self.armies.update(army_id, {
                        "province_pay_arrears": new_province,
                        "central_pay_arrears": new_central,
                    })
                    self.armies.append_log({
                        "turn": state.turn,
                        "year": state.year,
                        "period": state.period,
                        "army_id": army_id,
                        "field": "arrears",
                        "old_value": str(old_value),
                        "new_value": str(new_value),
                        "delta": delta,
                        "reason": reason,
                        "event_id": event.id,
                        "edict_id": edict_id,
                        "actor": actor,
                        "origin_ref": origin_ref,
                    })
                    self._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                    self._reconcile_central_army_pay_arrears_container()
                    self.assert_army_pay_source_container_conservation()
                    changes.append({
                        "army": row["name"], "field": field,
                        "label": ARMY_FIELD_LABELS.get(field, field),
                        "old": old_value, "new": new_value,
                        "delta": delta, "reason": reason,
                    })
                    continue
                elif field == "cannon_equipment":
                    # 随军大炮=红夷级重炮门数(非 0-100 饱和度)：野战带不动几门，clamp 0-12。
                    # 城防炮(城头红夷炮)另挂 region.cannon(上限 city_level×8)；佛郎机轻炮归 firearm_equipment。
                    delta = int(value)
                    new_value = max(0, min(12, int(old_value) + delta))
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                elif field in ARMY_SCORE_FIELDS:
                    if field == "loyalty":
                        # 合法 loyalty 别名已在环前合计；非法叶子仍在上方逐项拒收。
                        # 同事件同军只落地一次，后续别名 key 跳过（不写库、不二次打日志）。
                        if loyalty_soft_consumed:
                            continue
                        loyalty_soft_consumed = True
                        net_delta = int(
                            loyalty_canonical_delta
                            if loyalty_canonical_delta is not None
                            else value
                        )
                        net_pct = int(((self.legacy_modifiers(state).get("armies") or {})
                                       .get(army_id) or {}).get(field, 0) or 0)
                        # #319：latched loyalty 以 post-modifier 实际方向为准（与 soft-adjust
                        # 同序先套 legacy pct）；legacy 翻负 / 净合计非正则静默 no-op。
                        effect_delta = int(net_delta)
                        if net_pct:
                            effect_delta = self.apply_legacy_pct(effect_delta, net_pct)
                        if bool(row["is_mutinied"]) and not latched_army_field_effect_permitted(
                            field, net_delta, effect_delta=effect_delta
                        ):
                            continue
                        # #320：±15 alias fold 与动态 cap 同一写缝
                        new_value, actual_delta = compute_loyalty_soft_adjust(
                            int(old_value),
                            net_delta,
                            net_pct=net_pct,
                            mutiny_count=int(row["mutiny_count"] or 0),
                            redemption_count=int(row["redemption_count"] or 0),
                        )
                        if actual_delta == 0:
                            continue
                        stored_new = new_value
                        log_delta = actual_delta
                    else:
                        delta = int(value)
                        # 遗产百分比修正：该军该字段若有 active 遗产修正符，先放大/缩小 delta
                        net_pct = int(((self.legacy_modifiers(state).get("armies") or {})
                                       .get(army_id) or {}).get(field, 0) or 0)
                        if net_pct:
                            delta = self.apply_legacy_pct(delta, net_pct)
                        # #319：latched 非 loyalty score 字段已由环前 deny-by-default 门裁掉；
                        # 此处仅非 latched / 已放行路径的普通 0-100 clamp。
                        new_value = max(0, min(100, int(old_value) + delta))
                        actual_delta = new_value - int(old_value)
                        if actual_delta == 0:
                            continue
                        stored_new = new_value
                        log_delta = actual_delta
                elif field == "manpower":
                    delta = int(value)
                    new_value = max(0, int(old_value) + delta)
                    actual_delta = new_value - int(old_value)
                    will_write_off_arrears = (
                        new_value == 0
                        and str(row["owner_power"]) == "ming"
                        and float(row["arrears"] or 0) > 1e-9
                    )
                    origin_error = self.effect_origin_rejection(origin_ref) if require_origin and (delta != 0 or will_write_off_arrears) else None
                    if origin_error:
                        changes.append({"army": row["name"], "field": field, **origin_error,
                                        "item": {"army_id": army_id, "field": field, "value": value}})
                        continue
                    if will_write_off_arrears:
                        old_arrears = float(row["arrears"] or 0)
                        old_source = str(row["pay_source_region"] or "")
                        self.armies.append_log({
                            "turn": state.turn,
                            "year": state.year,
                            "period": state.period,
                            "army_id": army_id,
                            "field": "arrears",
                            "old_value": str(old_arrears),
                            "new_value": "0.0",
                            "delta": -old_arrears,
                            "reason": f"兵力归零核销：{reason}",
                            "event_id": event.id,
                            "edict_id": edict_id,
                            "actor": actor,
                            "origin_ref": origin_ref,
                        })
                        self.armies.update(army_id, {
                            "province_pay_arrears": 0,
                            "central_pay_arrears": 0,
                        })
                        self._reconcile_army_pay_source_region_container(old_source)
                        self._reconcile_central_army_pay_arrears_container()
                    if actual_delta == 0:
                        # #44：请求非 0 但 clamp 后无净变化（如减兵超过现有兵力→clamp 到 0）留一条
                        # delta=0 army_log（参照 region cannon delta=0 留痕，#14 不静默吞）；真 no-op
                        # （delta==0）无须留痕避噪。
                        if delta != 0:
                            self.armies.append_log({
                                "turn": state.turn,
                                "year": state.year,
                                "period": state.period,
                                "army_id": army_id,
                                "field": "manpower",
                                "old_value": str(old_value),
                                "new_value": str(new_value),
                                "delta": 0,
                                "reason": f"{reason}（请求 {delta:+d} 经 clamp 后无净变化）",
                                "event_id": event.id,
                                "edict_id": edict_id,
                                "actor": actor,
                                "origin_ref": origin_ref,
                            })
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                elif field in ARMY_TEXT_FIELDS:
                    text_value = str(value).strip()[:160]
                    if not text_value or text_value == str(old_value):
                        continue
                    # #659：station_region 非空须为已入库 regions.id；禁止从 station 文本反推。
                    if field == "station_region":
                        exists = RegionStore(self.conn).read_add_building((text_value,))
                        if exists is None:
                            changes.append({
                                "army": row["name"], "field": field,
                                "rejected": True, "category": "invalid_enum",
                                "reason": (
                                    f"army_delta.station_region 未入库 region_id：{text_value}"
                                ),
                                "item": {
                                    "army_id": army_id, "field": field, "value": value,
                                },
                            })
                            continue
                    stored_new = text_value
                    log_delta = None
                else:
                    # field 已过 _ARMY_VALID_SET 校验，能落到此处=合法字段未被任一
                    # 分支处理=代码漏接(往 ARMY_*_FIELDS 加了字段却忘了 dispatch)。
                    # 按 ADR 0008 决定 1：代码 bug 响亮上抛触发回滚，不静默丢一个合法 delta。
                    raise RuntimeError(f"army_delta 合法字段 '{field}' 无落库分支（代码漏接）")
                origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
                if origin_error:
                    changes.append({"army": row["name"], "field": field, **origin_error,
                                    "item": {"army_id": army_id, "field": field, "value": value}})
                    continue
                self.armies.update(army_id, {field: stored_new})
                if field == "manpower":
                    self._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                self.armies.append_log({
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "army_id": army_id,
                    "field": field,
                    "old_value": str(old_value),
                    "new_value": str(stored_new),
                    "delta": log_delta,
                    "reason": reason,
                    "event_id": event.id,
                    "edict_id": edict_id,
                    "actor": actor,
                    "origin_ref": origin_ref,
                })
                changes.append(
                    {
                        "army": row["name"],
                        "field": field,
                        "label": ARMY_FIELD_LABELS.get(field, field),
                        "old": old_value,
                        "new": stored_new,
                        "delta": log_delta,
                        "reason": reason,
                    }
                )
        if commit:
            self.conn.commit()
        return changes

    def create_armies_from_extraction(
        self,
        state: GameState,
        new_armies: List[Dict[str, object]],
        actor: str = "档房",
        commit: bool = True,
        origin_ref: str = "",
        require_origin: bool = False,
    ) -> List[Dict[str, object]]:
        """据 extractor 输出建新军队。同 id/name 已存在 → 把 manpower 当扩军增量。owner_power 必须是已知 power。"""
        valid_powers = {r["id"] for r in PowerStore(self.conn).read_apply_character_power_changes()}
        created: List[Dict[str, object]] = []
        for raw in new_armies:
            if not isinstance(raw, dict):
                # 不再静默丢：留拒收记录（season 路本就被 validate_delta_shape 挡在
                # S6;issue 路历史即静默,容忍不升级——issue_strict=False,cmr S2 r1）。
                created.append({
                    "rejected": True, "category": "invalid_enum",
                    "reason": f"new_armies 含非 dict 项：{raw!r}",
                    "item": raw, "issue_strict": False,
                })
                continue
            item = {POWER_FIELD_ALIASES.get(k, k) if False else k: v for k, v in raw.items()}
            # 规范键：复用 ARMY_FIELD_ALIASES（兼容中文）
            from ming_sim.constants import ARMY_FIELD_ALIASES as _AA
            item = {_AA.get(str(k).strip(), str(k).strip()): v for k, v in raw.items()}
            aid = str(item.get("id") or "").strip()
            if not aid:
                # ADR 0008 决定 1:缺 id = LLM 脏数据,逐项拒收留痕(invalid_enum),
                # 不再 raise 崩整月;同信封好军照建,坏一项不带走整批。
                created.append({
                    "rejected": True, "category": "invalid_enum",
                    "reason": "new_armies 缺 id（无法建军）",
                    "item": raw,
                })
                continue
            owner = str(item.get("owner_power") or "ming").strip() or "ming"
            if owner not in valid_powers:
                # ADR 0008 决定 1:owner_power 幻觉 = 逐项拒收留痕(hallucinated_id)。
                created.append({
                    "id": aid, "owner_power": owner,
                    "rejected": True, "category": "hallucinated_id",
                    "reason": f"new_armies owner_power '{owner}' 不在 powers 表（无法建军 {aid}）",
                    "item": raw,
                })
                continue
            name = str(item.get("name") or aid).strip()
            # 查重：同 id 或 同 name → 转 manpower 扩军增量
            existing = ArmyStore(self.conn).read_create_armies_from_extraction((aid, name))
            if existing is not None:
                manpower = item.get("manpower")
                if manpower is None:
                    # ADR 0008 决定 1:命中已有军但无扩军增量 = 无意义项,逐项拒收留痕。
                    created.append({
                        "id": aid, "rejected": True, "category": "invalid_enum",
                        "reason": f"new_armies 重复 id/name '{aid}' 且无 manpower（无扩军增量）",
                        "item": raw, "issue_strict": False,  # 历史 print-skip,结案路容忍
                    })
                    continue
                try:
                    if isinstance(manpower, (bool, float)):
                        raise ValueError("非整数")
                    delta = int(manpower)
                except (TypeError, ValueError):
                    # ADR 0008 决定 1:扩军增量非整数 = LLM 脏数据,逐项拒收留痕。
                    created.append({
                        "id": aid, "rejected": True, "category": "invalid_enum",
                        "reason": f"new_armies '{aid}' manpower 非整数：{manpower!r}",
                        "item": raw, "issue_strict": False,  # 历史 print-skip,结案路容忍
                    })
                    continue
                if delta == 0:
                    continue
                reason = str(item.get("reason") or item.get("status") or "扩军")[:80]
                pseudo_event = type("E", (), {"id": "season", "title": reason})()
                merge_results = self.apply_army_deltas(
                    state,
                    pseudo_event,
                    None,
                    actor,
                    {existing["id"]: {"manpower": delta, "reason": reason}},
                    commit=False, origin_ref=origin_ref, require_origin=require_origin,
                )
                if any(result.get("rejected") for result in merge_results):
                    created.extend(result for result in merge_results if result.get("rejected"))
                else:
                    created.append({"army": existing["name"], "manpower_added": delta, "merged_into_existing": True})
                continue
            # 必填字段：manpower 缺/非法 = LLM 脏数据,逐项拒收留痕(invalid_enum),不再 raise
            # 崩整月(ADR 0008 决定 1);同信封好军照建。bool/float 显式拒(对称 S1)。
            # #173 PR2：维护费退役、不再必填——月饷由 army_needed(salary_rate×兵力)派生,不靠维护费。
            try:
                _mp = item["manpower"]
                if isinstance(_mp, (bool, float)):
                    raise ValueError("非整数")
                manpower = int(_mp)
            except (KeyError, TypeError, ValueError) as exc:
                created.append({
                    "id": aid, "rejected": True, "category": "invalid_enum",
                    "reason": f"new_armies '{aid}' 缺/非法 manpower（无法建军）：{exc}",
                    "item": raw,
                    # 历史谓词只看 manpower（#173 PR2 后唯一必填）：manpower int() 成功=历史可活,
                    # 缺键/TypeError/ValueError 即历史 raise → 保持严格。
                    "issue_strict": not _new_army_historically_applied(item),
                })
                continue
            # #173：maintenance_per_turn 列已删（月饷由 army_needed 按兵力派生）；LLM 若仍塞维护费/
            # 军费，经 ARMY_FIELD_ALIASES 已无该别名 → 当未知键忽略，不入库、不影响建军。
            # 可选数值字段「在场即须合法」（cmr S2 r1 codex P1）：在场脏值静默走默认
            # = 伪造军备（morale "高"→50、cannon "几门"→0）。None 视为缺省（LLM 习惯
            # 用 null 表「无」,validate_delta_shape 亦容忍 null 叶）；其余非整拒该项。
            # 守门集从字段表派生（cmr S2 r2,2/2:硬列漏 equipment/mobility/loyalty）
            # ——ARMY_SCORE_FIELDS 全量已含 arrears;字段表变守门自动跟。
            _dirty_field = None
            for _f in ARMY_SCORE_FIELDS:
                _v = item.get(_f)
                if _f in item and _v is not None:
                    if isinstance(_v, (bool, float)):
                        _dirty_field = (_f, _v)
                        break
                    try:
                        int(_v)
                    except (TypeError, ValueError):
                        _dirty_field = (_f, _v)
                        break
            if _dirty_field is not None:
                created.append({
                    "id": aid, "rejected": True, "category": "invalid_enum",
                    "reason": (f"new_armies '{aid}' 可选字段 '{_dirty_field[0]}' 值非整数："
                               f"{_dirty_field[1]!r}（在场即须合法，缺省才走默认）"),
                    "item": raw,
                    # 历史上此案静默走默认值（非 raise）——结案路容忍不升级。
                    "issue_strict": False,
                })
                continue
            def _score(field: str, default: int = 50) -> int:
                try:
                    return max(0, min(100, int(item.get(field, default))))
                except (TypeError, ValueError):
                    return default
            def _cannon() -> int:
                # 随军大炮=门数 clamp 0-12；LLM 给非 int(如"几门")兜底 0，不让 int() 抛崩建军（PR codex）
                try:
                    return max(0, min(12, int(item.get("cannon_equipment", 0) or 0)))
                except (TypeError, ValueError):
                    return 0
            def _arrears_init() -> int:
                # arrears 单位=累计欠饷万两，无上限；新军默认 0
                try:
                    return max(0, int(item.get("arrears", 0)))
                except (TypeError, ValueError):
                    return 0
            initial_arrears = _arrears_init()
            if initial_arrears > 0:
                created.append({
                    "id": aid, "rejected": True, "category": "invalid_enum",
                    "reason": (
                        f"new_armies '{aid}' 新军初始欠饷必须为 0；"
                        "外生加欠须走 army_delta.arrears 正值"
                    ),
                    "item": raw,
                })
                continue
            # #659：结构化实际驻地可选；非空须为已入库 region_id，缺省 "" 不 fail-loud。
            station_region = str(item.get("station_region") or "").strip()
            if station_region:
                exists = RegionStore(self.conn).read_add_building((station_region,))
                if exists is None:
                    created.append({
                        "id": aid, "rejected": True, "category": "invalid_enum",
                        "reason": (
                            f"new_armies '{aid}' station_region 未入库 region_id："
                            f"{station_region}"
                        ),
                        "item": raw,
                    })
                    continue
            pay_source_region = ""
            province_pay_share = central_pay_share = 0.0
            province_pay_arrears = central_pay_arrears = 0.0
            is_tusi = self_funded_pay = False
            try:
                pay_source_region = str(item.get("pay_source_region") or "").strip()
                province_pay_share = _coerce_pay_source_float(item.get("province_pay_share"))
                central_pay_share = _coerce_pay_source_float(item.get("central_pay_share"))
                is_tusi = _coerce_bool_flag(item.get("is_tusi"))
                self_funded_pay = _coerce_bool_flag(item.get("self_funded_pay"))
                exempt = owner != "ming" or is_tusi or self_funded_pay
                if exempt:
                    province_pay_arrears = central_pay_arrears = 0.0
                else:
                    province_pay_arrears = initial_arrears * province_pay_share
                    central_pay_arrears = initial_arrears * central_pay_share
                self._validate_pay_source_values(
                    aid, owner, pay_source_region, province_pay_share, central_pay_share,
                    is_tusi, self_funded_pay, province_pay_arrears, central_pay_arrears,
                )
                if pay_source_region:
                    self._require_valid_pay_source_region(aid, pay_source_region)
            except (TypeError, ValueError) as exc:
                created.append({
                    "id": aid, "rejected": True, "category": "invalid_enum",
                    "reason": f"new_armies '{aid}' 饷源字段非法：{exc}",
                    "item": raw,
                })
                continue
            origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
            if origin_error:
                created.append({"id": aid, **origin_error, "item": raw})
                continue
            commander = str(item.get("commander") or "")
            # #44 新军名义月饷率：缺省/None/0/负/非数 一律落锚点 1.5。
            try:
                self.armies.insert({
                    "id": aid,
                    "name": name,
                    "station": str(item.get("station") or ""),
                    "station_region": station_region,
                    "theater": str(item.get("theater") or ""),
                    "commander": commander,
                    "controller": str(item.get("controller") or commander),
                    "troop_type": str(item.get("troop_type") or ""),
                    "manpower": max(0, manpower),
                    "supply": _score("supply"),
                    "morale": _score("morale"),
                    "training": _score("training"),
                    "equipment": _score("equipment"),
                    "province_pay_arrears": province_pay_arrears,
                    "central_pay_arrears": central_pay_arrears,
                    "pay_source_region": pay_source_region,
                    "province_pay_share": province_pay_share,
                    "central_pay_share": central_pay_share,
                    "is_tusi": 1 if is_tusi else 0,
                    "self_funded_pay": 1 if self_funded_pay else 0,
                    "mobility": _score("mobility"),
                    "loyalty": _score("loyalty"),
                    "firearm_equipment": _score("firearm_equipment", 0),
                    "cannon_equipment": _cannon(),
                    "salary_rate": _coerce_new_salary_rate(item.get("salary_rate")),
                    "status": str(item.get("status") or "新立"),
                    "owner_power": owner,
                })
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"new_armies INSERT 失败 '{aid}'：{exc}") from exc
            self._reconcile_army_pay_source_region_container(pay_source_region)
            self._reconcile_central_army_pay_arrears_container()
            self.assert_army_pay_source_container_conservation()
            reason = str(item.get("reason") or item.get("status") or "新立军队")[:80]
            self.armies.append_log({
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "army_id": aid,
                "field": "created",
                "old_value": "",
                "new_value": str(manpower),
                "delta": manpower,
                "reason": reason,
                "event_id": "season",
                "actor": actor,
                "origin_ref": origin_ref,
            })
            created.append({
                "army": name,
                "id": aid,
                "owner_power": owner,
                "manpower": manpower,
                "created": True,
                "reason": reason,
            })
        if commit:
            self.conn.commit()
        return created

    # ── 建筑 ──────────────────────────────────────────────────────────────────

    def add_building(
        self,
        state: GameState,
        region_id: str,
        name: str,
        category: str,
        *,
        level: int = 1,
        condition: int = 60,
        maintenance: int = 0,
        risk: int = 30,
        output_metric: str = "",
        output_amount: int = 0,
        status: str = "",
        origin: str = "decree",
        commit: bool = True,
        origin_ref: str = "",
    ) -> str:
        """运行时新立建筑（玩家诏书）。category / output_metric 走白名单硬校验，违规 ValueError。"""
        if category not in BUILDING_CATEGORIES:
            raise ValueError(f"建筑 category 非法 '{category}'，白名单 {BUILDING_CATEGORIES}")
        if output_metric not in BUILDING_OUTPUT_METRICS:
            raise ValueError(f"建筑 output_metric 非法 '{output_metric}'，白名单 {BUILDING_OUTPUT_METRICS}")
        if RegionStore(self.conn).read_add_building((region_id,)) is None:
            raise ValueError(f"建筑 region_id 引用未入库地区 '{region_id}'")
        base = re.sub(r"[^a-z0-9]+", "", (region_id or "rgn").lower()) or "rgn"
        seq = self.buildings.count_in_region(region_id)
        building_id = f"{base}_b{int(seq) + 1}"
        while self.buildings.exists(building_id):
            seq += 1
            building_id = f"{base}_b{int(seq) + 1}"
        building_name = name.strip()[:60] or "无名建筑"
        self.buildings.insert({
            "id": building_id,
            "region_id": region_id,
            "name": building_name,
            "category": category,
            "level": max(1, min(5, int(level))),
            "condition": max(0, min(100, int(condition))),
            "maintenance": max(0, int(maintenance)),
            "risk": max(0, min(100, int(risk))),
            "output_metric": output_metric,
            "output_amount": max(0, int(output_amount)),
            "status": status.strip()[:160] or "新立，尚在筹建。",
            "origin": origin,
            "created_turn": state.turn,
        })
        self.buildings.append_log({
            "turn": state.turn,
            "year": state.year,
            "period": state.period,
            "building_id": building_id,
            "field": "create",
            "old_value": "",
            "new_value": building_name,
            "delta": None,
            "reason": "诏书新立建筑",
            "actor": "档房",
            "origin_ref": origin_ref,
        })
        if commit:
            self.conn.commit()
        return building_id

    def remove_building(
        self,
        state: GameState,
        building_id: str,
        reason: str = "",
        commit: bool = True,
        origin_ref: str = "",
    ) -> bool:
        """拆除/废止建筑（issue 失败或撤销结案）。返回是否真删了一行。"""
        row = self.buildings.get(building_id)
        if row is None:
            return False
        self.buildings.append_log({
            "turn": state.turn,
            "year": state.year,
            "period": state.period,
            "building_id": building_id,
            "field": "remove",
            "old_value": str(row["name"]),
            "new_value": "",
            "delta": None,
            "reason": (reason or "建筑废止").strip()[:80],
            "actor": "档房",
            "origin_ref": origin_ref,
        })
        self.buildings.delete(building_id)
        if commit:
            self.conn.commit()
        return True

    def apply_building_deltas(
        self,
        state: GameState,
        event: Event,
        edict_id: int | None,
        actor: str,
        building_deltas: Dict[str, Dict[str, object]],
        commit: bool = True,
        origin_ref: str = "",
    ) -> List[Dict[str, object]]:
        """改既有建筑。仿 apply_army_deltas。供 issue effect 落地复用。"""
        changes: List[Dict[str, object]] = []
        valid_fields = set(BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS + BUILDING_TEXT_FIELDS)
        for building_id, raw_changes in building_deltas.items():
            row = self.buildings.get(building_id)
            if row is None:
                print(f"[WARN] building_delta 引用未入库建筑 '{building_id}' → 跳过")
                continue
            reason = str(raw_changes.get("reason") or event.title).strip()[:80]
            for field, value in raw_changes.items():
                if field == "reason":
                    continue
                if field not in valid_fields:
                    print(f"[WARN] building_delta 引用非法字段 '{field}' → 跳过")
                    continue
                old_value = row[field]
                if field in BUILDING_SCORE_FIELDS:
                    new_value = max(0, min(100, int(old_value) + int(value)))
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new: object = new_value
                    log_delta: int | None = actual_delta
                elif field == "level":
                    new_value = max(1, min(5, int(old_value) + int(value)))
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                elif field in ("maintenance", "output_amount"):
                    new_value = max(0, int(old_value) + int(value))
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                elif field == "output_metric":
                    text_value = str(value).strip()
                    if text_value not in BUILDING_OUTPUT_METRICS:
                        print(f"[WARN] building_delta output_metric 非法 '{text_value}' → 跳过")
                        continue
                    if text_value == str(old_value):
                        continue
                    stored_new = text_value
                    log_delta = None
                elif field in BUILDING_TEXT_FIELDS:
                    text_value = str(value).strip()[:160]
                    if not text_value or text_value == str(old_value):
                        continue
                    stored_new = text_value
                    log_delta = None
                else:
                    print(f"[WARN] building_delta 未处理字段 '{field}' → 跳过")
                    continue
                self.buildings.update(building_id, {field: stored_new})
                self.buildings.append_log({
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "building_id": building_id,
                    "field": field,
                    "old_value": str(old_value),
                    "new_value": str(stored_new),
                    "delta": log_delta,
                    "reason": reason,
                    "event_id": event.id,
                    "edict_id": edict_id,
                    "actor": actor,
                    "origin_ref": origin_ref,
                })
                changes.append({
                    "building": row["name"],
                    "field": field,
                    "label": BUILDING_FIELD_LABELS.get(field, field),
                    "old": old_value,
                    "new": stored_new,
                    "delta": log_delta,
                    "reason": reason,
                })
        if commit:
            self.conn.commit()
        return changes

    def buildings_report(self, region_id: str = "", qualitative: bool = False) -> str:
        """月末奏报 / web 用建筑盘面摘要。region_id 为空取全国。"""
        if region_id:
            rows = BuildingStore(self.conn).read_buildings_report((region_id,))
        else:
            rows = BuildingStore(self.conn).read_buildings_report_()
        if not rows:
            return "（暂无建筑在册）"
        lines: List[str] = []
        for r in rows:
            metric = str(r["output_metric"])
            if metric in ("民心", "皇威") and qualitative:
                out = building_output_effect(metric, r["output_amount"])
            elif metric:
                out = f"产出{metric}{r['output_amount']}"
            else:
                out = "无结算产出"
            if qualitative:
                level, condition, risk = building_qualitative_fields(r)
                lines.append(
                    f"{r['name']}（{r['category']}·{r['region_id']}）规模{level}，"
                    f"{condition}，维护{r['maintenance']}{MONEY_UNIT}/{TURN_UNIT}，风险{risk}，{out}。{r['status']}"
                )
                continue
            lines.append(
                f"{r['name']}（{r['category']}·{r['region_id']}）等级{r['level']}，"
                f"完好{r['condition']}，维护{r['maintenance']}{MONEY_UNIT}/{TURN_UNIT}，"
                f"风险{r['risk']}，{out}。{r['status']}"
            )
        return "\n".join(lines)

    def building_payload(self, region_id: str = "") -> List[Dict[str, object]]:
        """建筑结构化清单，供 web。region_id 为空取全国。"""
        if region_id:
            rows = BuildingStore(self.conn).read_buildings_report((region_id,))
        else:
            rows = BuildingStore(self.conn).read_buildings_report_()
        return [
            {
                "id": str(r["id"]),
                "region_id": str(r["region_id"]),
                "name": str(r["name"]),
                "category": str(r["category"]),
                "level": int(r["level"]),
                "condition": int(r["condition"]),
                "maintenance": int(r["maintenance"]),
                "risk": int(r["risk"]),
                "output_metric": str(r["output_metric"]),
                "output_amount": int(r["output_amount"]),
                "status": str(r["status"]),
                "origin": str(r["origin"]),
            }
            for r in rows
        ]

    def building_detail(self, name_or_id: str, qualitative: bool = False) -> str:
        key = (name_or_id or "").strip()
        row = BuildingStore(self.conn).read_building_detail((key, key))
        if row is None:
            row = BuildingStore(self.conn).read_building_detail_((f"%{key}%",))
        if row is None:
            raise ValueError(f"未找到建筑 '{name_or_id}'")
        metric = str(row["output_metric"])
        if metric in ("民心", "皇威") and qualitative:
            out = building_output_effect(metric, row["output_amount"])
        else:
            out = f"产出{metric}{row['output_amount']}/{TURN_UNIT}" if metric else "无结算产出"
        if qualitative:
            level, condition, risk = building_qualitative_fields(row)
            return (
                f"{row['name']}（{row['category']}，{row['region_id']}，{row['origin']}）："
                f"规模{level}，{condition}，维护{row['maintenance']}{MONEY_UNIT}/{TURN_UNIT}，风险{risk}，{out}。\n"
                f"{row['status']}"
            )
        return (
            f"{row['name']}（{row['category']}，{row['region_id']}，{row['origin']}）："
            f"等级{row['level']}，完好{row['condition']}，"
            f"维护{row['maintenance']}{MONEY_UNIT}/{TURN_UNIT}，风险{row['risk']}，{out}。\n"
            f"{row['status']}"
        )

    def adjust_factions(self, deltas: Dict[str, object], commit: bool = True) -> List[Dict[str, object]]:
        """逐项落库；查无此派系名 → missing_ref 逐项拒收留痕（ADR 0008 决定 1，#14/#63
        死法 3）。入参经 _apply_faction_dict 预清洗（坏值已在那层拒），此处只余未知名一类。
        返回拒收项列表（{"rejected": True, ...}），桥接 _collect_inline_rejections 自动收。

        #9 cmr R5 finding#1：白名单朝堂派系（_LEVERAGE_FACTIONS）的 leverage 列由「offset+官职和」
        派生、结算尾 recompute_all_faction_leverage() 绝对幂等兜底。若此处对白名单直写 leverage 列，
        会被该 reconcile 抹回公式值 → LLM「影响力变化」静默蒸发、DB 与玩家可见「已落」分叉。
        故白名单的 leverage 增量改注入 **leverage_offset**（无形政治基线变动），再 recompute_faction_leverage
        立即令 leverage 体现（offset+官职和，含本次增量）；结算尾 reconcile 确认同值、不抹。
        offset 不 clamp（leverage 读时 clamp）。非白名单（宗室等）维持原样直写 leverage 列
        （reconcile 不碰非白名单）。satisfaction 两者都照旧 clamp 直写。"""
        rejected: List[Dict[str, object]] = []
        for faction, val in deltas.items():
            if isinstance(val, dict):
                sat_d = int(val.get("satisfaction") or 0)
                lev_d = int(val.get("leverage") or 0)
            else:
                try:
                    sat_d = int(val)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                lev_d = 0
            if sat_d == 0 and lev_d == 0:
                continue
            row = FactionStore(self.conn).read_adjust_factions((faction,))
            if not row:
                rejected.append({
                    "name": faction, "rejected": True, "category": "missing_ref",
                    "reason": f"faction_delta 查无此派系「{faction}」（未入 factions 表）",
                    "item": {faction: val},
                })
                continue
            new_sat = max(0, min(100, int(row["satisfaction"]) + sat_d))
            if faction in _LEVERAGE_FACTIONS:
                # 白名单：leverage 增量注入 offset（不被 reconcile 抹），satisfaction 仍直写。
                self.factions.add_leverage_offset(faction, new_sat, lev_d)
                # 立即令 leverage 体现 offset 变化（含本次增量）；reconcile 后确认同值。
                self.recompute_faction_leverage(faction)
            else:
                # 非白名单：维持原样直写 leverage 列（reconcile 不碰非白名单）。
                new_lev = max(0, min(100, int(row["leverage"]) + lev_d))
                self.factions.set_satisfaction_and_leverage(faction, new_sat, new_lev)
        if commit:
            self.conn.commit()
        return rejected

    def turn_economy_summary(self, turn: int) -> str:
        rows = ReignStateStore(self.conn).read_turn_economy_summary((turn,))
        if not rows:
            return f"本{TURN_UNIT}无新增收支。"
        parts = []
        for row in rows:
            income = int(row["income"] or 0)
            expense = int(row["expense"] or 0)
            net = int(row["net"] or 0)
            parts.append(
                f"{row['account']}收入{format_money(income)}、支出{format_money(expense)}、净变{format_money_delta(net)}"
            )
        return "；".join(parts) + "。"

    def treasury_ledger(self, account: str, turns: int = 6) -> str:
        """查国库或内库最近 N 回合流水明细。"""
        rows = ReignStateStore(self.conn).read_treasury_ledger((account, turns * 20))
        if not rows:
            return f"{account}无流水记录。"
        lines = [f"【{account}近{turns}回合流水（最新在前）】"]
        for r in rows:
            sign = "+" if int(r["delta"]) > 0 else ""
            lines.append(
                f"{r['year']}年{r['period']}月（turn{r['turn']}）"
                f" {sign}{format_money_delta(int(r['delta']))} → 余{format_money(int(r['balance_after']))} "
                f"[{r['category']}] {r['reason']}"
                + (f"（{r['actor']}）" if r["actor"] else "")
            )
        return "\n".join(lines)

    def previous_turn_summary(self, state: GameState) -> str:
        previous_turn = state.turn - 1
        # #1356：不再 seed turn=0 固定邸报；t0 / 无上月 → 空串（P7 禁固定空态文案）。
        if previous_turn < 0:
            return ""

        # 上回合奏报单独存在 turn_reports，直接取。
        # #1843 reopen：旧 turn_logs 回落随旧结算核删除；无邸报即真空。
        report = self.turn_reports.report_text(previous_turn)
        if report:
            return report
        return ""

    def previous_turn_reign_period_label(self, state: GameState) -> str:
        """邸报面报头年月 ≡ 所显示报文自身所属月（#1356）。

        与 previous_turn_summary 同源同口径：
        - 仅**非空** report 行才取其 year/period，经 reign_period_label 投影；
        - 空 report 行视同无报（不得因行在而贴 label）；
        - 无有效 report 时，仅当 logs 回落会产出 summary 才回推上一月；
        - t0 / 真空 summary → 空串（禁「九月残留」空报却有 label）。
        当前 turn 年号不得混充上月报头。
        """
        previous_turn = int(state.turn) - 1
        if previous_turn < 0:
            return ""
        # 与 previous_turn_summary / turn_reports.report_text 同口径：非空才算有报
        row = self.turn_reports.archive(previous_turn)
        if row is not None and (row["report"] or ""):
            try:
                return reign_period_label(int(row["year"]), int(row["period"]))
            except (TypeError, ValueError):
                return ""
        # #1843 reopen：无有效邸报则真空；旧 turn_logs 回落已删。
        return ""

    def append_chat_message(self, minister_name: str, turn: int, role: str, content: str) -> int:
        """召对聊天单条消息落库（chat_messages）。

        #976 不变式：分类落定前，**任何**召对行（不分 role）不得进入共享
        ``character_knowledge_sources``。此处只 insert + hold；投轨唯一出口是
        ``release_held_audience_knowledge``（分类后 / 月末）。续聊读
        ``chat_messages`` 本表，不依赖共享投影即时可见。

        Empty ``minister_name`` is allowed for non-audience bookkeeping rows but
        cannot be projected (release parks them as withheld — see N2).
        """
        message_id = self.chat_messages.insert(
            minister_name=minister_name, turn=turn, role=role, content=content,
        )
        self.conn.commit()
        return message_id

    def set_message_highlights(
        self, message_id: int, phrases: Sequence[Any],
    ) -> None:
        """#544：把判官短语清单落在 chat_messages 上（原样/已过滤皆可）。"""
        clean: List[str] = []
        for item in list(phrases or []):
            if not isinstance(item, str):
                continue
            phrase = item.strip()
            if phrase:
                clean.append(phrase)
        payload = json.dumps(clean, ensure_ascii=False)
        self.chat_messages.set_highlights_json(int(message_id), payload)
        self.conn.commit()

    def delete_chat_messages(self, message_ids: Iterable[int]) -> None:
        ids = [int(mid) for mid in message_ids if mid is not None]
        if not ids:
            return
        with self.conn:
            self.chat_messages.delete_ids(ids)
            self.character_knowledge.delete_by_source_ids(
                [f"chat_message:{mid}" for mid in ids], commit=False,
            )

    def build_chat_projection(self, minister_name: str, night_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """当前召对夜的 turn-identified 投影：user/minister 逐条带 chat_turn_id。

        消息行归 ChatMessageStore；chat_turns 身份留在召对投影。
        """
        if night_id is None:
            open_night = self.conn.execute(
                "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            night_id = int(open_night["id"]) if open_night else 0
        turns = self.conn.execute(
            "SELECT id, user_message_id, minister_message_id FROM chat_turns "
            "WHERE minister_name=? AND night_id=?",
            (minister_name, int(night_id)),
        ).fetchall()
        message_ids = [
            int(message_id)
            for turn in turns
            for message_id in (turn["user_message_id"], turn["minister_message_id"])
            if message_id is not None
        ]
        msgs = self.chat_messages.rows_by_ids(message_ids)
        msg_turn: Dict[int, int] = {}
        for t in turns:
            tid = int(t["id"])
            if t["user_message_id"] is not None:
                msg_turn[int(t["user_message_id"])] = tid
            if t["minister_message_id"] is not None:
                msg_turn[int(t["minister_message_id"])] = tid
        projection: List[Dict[str, Any]] = []
        for m in msgs:
            mid = int(m["id"])
            turn_id = msg_turn.get(mid, 0)
            role = m["role"]
            # #544：只大臣气泡携带判官清单；帝侧恒 []（SELECT 已点名 highlights_json）
            highlights = (
                self.chat_messages.parse_highlights(m["highlights_json"])
                if role == "minister"
                else []
            )
            projection.append({
                "role": role,
                "content": m["content"],
                "chat_turn_id": turn_id,
                "highlights": highlights,
            })
        return projection

    def list_hall_chat_turns(self, night_id: int) -> List[Dict[str, Any]]:
        """本夜殿上轮（#1849 reopen：只按「殿上」取，不再拼升级前按朝臣存储）。"""
        rows = self.conn.execute(
            "SELECT id, minister_name, status, user_message_id, minister_message_id FROM chat_turns "
            "WHERE night_id=? AND minister_name=? ORDER BY id",
            (int(night_id), "殿上"),
        ).fetchall()
        return [dict(row) for row in rows]

    # ----- chat_turns（本回合召对撤回）-----

    _ROLLBACK_TABLE_PK = {
        "turn_directives": "id",
        "secret_orders": "id",
        "decree_dossiers": "id",
        "decree_dossier_decisions": "id",
        "characters": "name",
        "character_offices": "character_name",
        "dossier_reported_progress": "id",
        # 动作闸门(ADR 0006)：召对暂存的结构化写动作。撤回召对须删本轮暂存,
        # 否则颁诏仍会落库,破坏 undo 保证(CMR P1)。
        "pending_actions": "id",
        # #9 R1 finding#4：leverage hook（set_character_status/set_character_office）会改 factions
        # .leverage(+offset)。chat office/dismiss 动作撤回须连 factions 一并还原，否则 characters
        # 被还原而 factions leverage 留脏。快照 SELECT * 含 leverage+offset，原位 UPDATE
        # 全列覆盖、二者同还原。
        "factions": "name",
        # #1839 C2 / ADR 0038 第四类：转译声明当场实况的前像表——文字事实 / 公开说法 /
        # 边事件。人物 status 变更走 characters；在场账走 origin_chat_turn_id 删（undo
        # 既有路径），不进本快照。
        "textual_facts": "id",
        "public_sayings": "id",
        "relation_edge_events": "id",
    }

    def _delete_turn_scoped_knowledge_sources_in_tx(self, chat_turn_id: int) -> None:
        self.character_knowledge.delete_sources_matching(
            f"%:chat_turn:{int(chat_turn_id)}", commit=False,
        )

    def _row_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def _json_dump_row(self, row: Dict[str, Any]) -> str:
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    def _json_load_row(self, raw: str) -> Dict[str, Any]:
        return load_stored_object(raw, label="rollback row")

    def _table_exists(self, table: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _snapshot_table(self, table: str, pk: str) -> Dict[str, Dict[str, Any]]:
        if table in ("secret_orders", "public_sayings"):
            rows = self.character_knowledge.snapshot_rows(table)
        elif table in ("characters", "character_offices"):
            rows = self.characters.snapshot_rows(table)
        elif table in ("decree_dossiers", "decree_dossier_decisions", "dossier_reported_progress"):
            rows = self.dossiers.snapshot_rows(table)
        elif table == "factions":
            rows = self.factions.snapshot_rows()
        elif table == "textual_facts":
            rows = self.textual_facts.snapshot_rows()
        elif table == "relation_edge_events":
            rows = self.person_logs.edge_snapshot_rows()
        else:
            rows = self.conn.execute(f"SELECT * FROM {table}").fetchall()
        snapshot = {str(row[pk]): self._row_dict(row) for row in rows}
        if table == "secret_orders":
            brief_pins = {
                str(row["order_id"]): str(row["origin_chat_message_ids"] or "[]")
                for row in self.character_knowledge.secret_brief_pins()
            }
            for order_id, row in snapshot.items():
                row["_rollback_brief_origin_chat_message_ids"] = brief_pins.get(order_id, "[]")
        return snapshot

    def capture_chat_rollback_snapshot(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """截取召对前后的可回滚业务表状态，用于撤回时做差异还原。"""
        return {
            table: self._snapshot_table(table, pk)
            for table, pk in self._ROLLBACK_TABLE_PK.items()
        }

    def allocate_night_seq(self, night_id: int) -> int:
        """夜内单调事件序：账本 seq 与 chat_turns.night_seq 共用（AC4 可合流对齐）。"""
        nid = int(night_id)
        if nid <= 0:
            return 0
        row = self.conn.execute(
            "SELECT next_event_seq FROM audience_nights WHERE id = ?",
            (nid,),
        ).fetchone()
        if row is None:
            raise ValueError(f"audience night not found: {nid}")
        nxt = int(row["next_event_seq"] or 0) + 1
        self.conn.execute(
            "UPDATE audience_nights SET next_event_seq = ? WHERE id = ?",
            (nxt, nid),
        )
        return nxt

    def complete_rescript_summon_scaffold_turn(self, chat_turn_id: int) -> None:
        """#657：空问话召见 scaffold 消费成功 → status=consumed（非在飞终态唯一写点）。

        list_in_flight 不含 consumed；与 failed（真失败）分立。body 已非空时
        再入走 consumed 短路，不走 ensure CAS。
        """
        ctid = int(chat_turn_id or 0)
        if ctid <= 0:
            return
        self.conn.execute(
            "UPDATE chat_turns SET status='consumed' "
            "WHERE id=? AND status='generating' AND user_message_id IS NULL",
            (ctid,),
        )
        if (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()

    def list_in_flight_chat_turns(
        self,
        *,
        night_id: Optional[int] = None,
        minister_name: Optional[str] = None,
        turn: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """未完成回话：generating，或 active 且尚无大臣回话。

        consumed / failed / interrupted / undone 均非在飞。
        WebGame / 收夜守卫走此接口，不直接摸 conn（测试替身可 stub）。
        """
        clauses = [
            "("
            "status = 'generating' OR "
            "(status = 'active' AND (minister_message_id IS NULL OR minister_message_id = 0))"
            ")"
        ]
        params: List[Any] = []
        if night_id is not None and int(night_id) > 0:
            clauses.append("night_id = ?")
            params.append(int(night_id))
        if minister_name is not None:
            clauses.append("minister_name = ?")
            params.append(str(minister_name))
        if turn is not None:
            clauses.append("turn = ?")
            params.append(int(turn))
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"SELECT * FROM chat_turns WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()
        return [self._row_dict(r) for r in rows]

    def reconcile_interrupted_chat_turns(self) -> List[Dict[str, Any]]:
        """重开对账（#505 / ADR 0036）：上一进程崩溃遗留的在飞回话轮（generating / active 无
        回话）终态化。生成半途被 kill 的轮：问话已持久、回话未落。恢复形态——

        - **有问话**（user_message_id 已链接）→ 标 'interrupted'（可重试终态）：问话原句保留、
          **不删任何账/记录**；解除在飞判定（不再挡续问/收夜）；最后一句上给重新生成回话。
        - **无问话**（连问话都没落，极窄崩溃窗）→ 标 'failed'：无可保留、无可重试，只解阻塞。

        幂等：只动 generating / active-无回话；'interrupted'/'active'/'failed' 不再重扫。**永不删账。**
        返回待重试轮列表（chat_turn_id/minister_name/turn/question）供恢复提示取数。

        「在飞」判据单一真源 = `list_in_flight_chat_turns`（无过滤 = 全库崩溃孤儿集）——
        与在飞守卫同缝，不另抄谓词。
        """
        rows = self.list_in_flight_chat_turns()
        interrupted: List[Dict[str, Any]] = []
        with self.conn:
            for row in rows:
                ctid = int(row["id"])
                uid = row.get("user_message_id")
                # #505 finding5：崩溃窗若 agent.run 已写入 Agno runs 而回话未 persist，
                # 截回本轮起点（agno_runs_before），避免 retry 时上下文双倍——与
                # fail_chat_turn/undo 同一 agno 截断缝。非删账：只丢没落完那半句的 LLM 工作态。
                self._truncate_agno_runs_in_tx(
                    str(row.get("agno_session_id") or ""),
                    int(row.get("agno_runs_before") or 0),
                )
                if uid:
                    self.conn.execute(
                        "UPDATE chat_turns SET status = 'interrupted' WHERE id = ?",
                        (ctid,),
                    )
                    question = self.chat_messages.content_of(int(uid))
                    interrupted.append({
                        "chat_turn_id": ctid,
                        "minister_name": str(row["minister_name"]),
                        "turn": int(row["turn"]),
                        "question": question or "",
                    })
                else:
                    self.conn.execute(
                        "UPDATE chat_turns SET status = 'failed' WHERE id = ?",
                        (ctid,),
                    )
        return interrupted

    def get_interrupted_reply_retries(
        self, minister_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """待重试的中断回话轮（status='interrupted'，问话已落、回话未落）——恢复提示 / 重试取数。"""
        clauses = ["t.status = 'interrupted'", "t.user_message_id IS NOT NULL"]
        params: List[Any] = []
        if minister_name is not None:
            clauses.append("t.minister_name = ?")
            params.append(str(minister_name))
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""
            SELECT id, minister_name, turn, error_pack_path, user_message_id
            FROM chat_turns t
            WHERE {where}
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            question = self.chat_messages.content_of(int(row["user_message_id"]))
            if question is None:
                continue
            out.append({
                "chat_turn_id": int(row["id"]),
                "minister_name": str(row["minister_name"]),
                "turn": int(row["turn"]),
                "question": question,
                "error_pack_path": str(row["error_pack_path"] or ""),
            })
        return out

    def get_post_reply_retries(self, minister_name: str) -> List[Dict[str, Any]]:
        """已落回话的尾随失败：保留原轮身份与错误包，不回到生成态。"""
        rows = self.conn.execute(
            """SELECT id, minister_name, turn, post_reply_recovery,
                      post_reply_error_pack_path, user_message_id, minister_message_id
               FROM chat_turns
               WHERE minister_name = ? AND status = 'active'
                 AND post_reply_recovery != ''
                 AND post_reply_recovery NOT LIKE 'recovering:%' ORDER BY id ASC""",
            (minister_name,),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            question = self.chat_messages.content_of(int(row["user_message_id"]))
            answer = self.chat_messages.content_of(int(row["minister_message_id"]))
            if question is None or answer is None:
                continue
            out.append({
                "chat_turn_id": int(row["id"]),
                "minister_name": str(row["minister_name"]),
                "turn": int(row["turn"]),
                "question": question,
                "answer": answer,
                "minister_message_id": int(row["minister_message_id"]),
                "recovery_phase": str(row["post_reply_recovery"]),
                "error_pack_path": str(row["post_reply_error_pack_path"] or ""),
            })
        return out

    def mark_post_reply_failure(self, chat_turn_id: int, phase: str, pack_path: str) -> None:
        self.conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = ?, post_reply_error_pack_path = ? "
            "WHERE id = ? AND status = 'active' AND minister_message_id IS NOT NULL",
            (phase, pack_path, int(chat_turn_id)),
        )
        self.conn.commit()

    def clear_post_reply_failure(self, chat_turn_id: int) -> None:
        self.conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = '', post_reply_error_pack_path = '' "
            "WHERE id = ? AND status = 'active'",
            (int(chat_turn_id),),
        )
        self.conn.commit()

    def claim_post_reply_recovery(self, chat_turn_id: int, phase: str) -> bool:
        """持运行时写闸调用；同一已落回话只允许一个尾随恢复者。"""
        cursor = self.conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = ? WHERE id = ? "
            "AND status = 'active' AND post_reply_recovery = ?",
            (f"recovering:{phase}", int(chat_turn_id), phase),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def release_post_reply_recovery(self, chat_turn_id: int, phase: str) -> None:
        self.conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = ? WHERE id = ? "
            "AND post_reply_recovery = ?",
            (phase, int(chat_turn_id), f"recovering:{phase}"),
        )
        self.conn.commit()

    def reconcile_post_reply_recovery(self) -> None:
        """仅启动时释放崩溃遗留 claim，保留原错误包供重试。"""
        self.conn.execute(
            "UPDATE chat_turns SET post_reply_recovery = substr(post_reply_recovery, 12) "
            "WHERE post_reply_recovery LIKE 'recovering:%'",
        )
        self.conn.commit()

    def reopen_interrupted_chat_turn_for_retry(self, chat_turn_id: int) -> bool:
        """重试起手：'interrupted' → 'generating'（重入生成态、与在飞守卫一致，回话落库后升 active）。
        仅当前确为 interrupted 才翻；返回是否翻动（防重复重试竞态）。"""
        cur = self.conn.execute(
            "UPDATE chat_turns SET status = 'generating' "
            "WHERE id = ? AND status = 'interrupted'",
            (int(chat_turn_id),),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def restore_interrupted_after_failed_retry(self, chat_turn_id: int) -> List[int]:
        """重试再失败的善后（#505 finding1）：回滚本次重试在 session.chat 落下的副作用
        （dismiss 账 / 拟旨 / 任免候选等，已由调用方 record_chat_turn_rollback_diffs 记为
        rollback items）+ 截断本轮 agno runs，把重入生成态的轮翻回 'interrupted' 保持可再
        重试——但**绝不删问话/回话**（恢复路径永不删账，AC3/AC4）。

        与 fail_chat_turn 同 rollback-items + agno 截断缝，差异仅三点：不删 chat_messages、
        终态=interrupted（非 failed）、消费后删本轮 rollback_items（轮继续存活，防将来重试
        成功→撤回时重放已还原的副作用 = 双还原）。仅动重入生成态且尚无回话的轮（幂等 / CAS 安全）。
        """
        row = self.conn.execute(
            "SELECT * FROM chat_turns WHERE id = ?", (int(chat_turn_id),)
        ).fetchone()
        if row is None:
            return []
        turn_row = self._row_dict(row)
        if turn_row["status"] != "generating" or turn_row.get("minister_message_id"):
            return []
        items = self.conn.execute(
            """
            SELECT * FROM chat_turn_rollback_items
            WHERE chat_turn_id = ?
            ORDER BY id DESC
            """,
            (int(chat_turn_id),),
        ).fetchall()
        restored_pending_action_ids: List[int] = []
        with self.conn:
            self._delete_turn_scoped_knowledge_sources_in_tx(chat_turn_id)
            self.conn.execute(
                "DELETE FROM story_ledger_entries "
                "WHERE source_chat_turn_id = ? OR origin_chat_turn_id = ?",
                (int(chat_turn_id), int(chat_turn_id)),
            )
            # 空 undone 消息集：只还原业务副作用，一句问话/回话都不删。
            restored_pending_action_ids = self._restore_chat_rollback_items_in_tx(items, [])
            self.conn.execute(
                "DELETE FROM chat_turn_rollback_items WHERE chat_turn_id = ?",
                (int(chat_turn_id),),
            )
            self._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )
            self.conn.execute(
                "UPDATE chat_turns SET status = 'interrupted' WHERE id = ?",
                (int(chat_turn_id),),
            )
        return restored_pending_action_ids

    def create_chat_turn(
        self,
        state: GameState,
        minister_name: str,
        agno_session_id: str,
        agno_runs_before: int,
        *,
        night_id: int = 0,
        status: Optional[str] = None,
        night_seq: Optional[int] = None,
    ) -> int:
        # #498：挂夜的对话轮以 generating 起笔，回话落库后 update_chat_turn_messages 升 active。
        # 未挂夜路径保持历史默认 active，避免旧调用方/测试面语义漂移。
        initial_status = status
        if initial_status is None:
            initial_status = "generating" if int(night_id or 0) else "active"
        if initial_status not in {"active", "generating", "failed", "undone", "consumed"}:
            raise ValueError(f"unsupported chat_turn status: {initial_status!r}")
        nid = int(night_id or 0)
        seq = int(night_seq) if night_seq is not None else (
            self.allocate_night_seq(nid) if nid > 0 else 0
        )
        cur = self.conn.execute(
            """
            INSERT INTO chat_turns
                (minister_name, turn, year, period, agno_session_id, agno_runs_before,
                 night_id, night_seq, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                minister_name,
                int(state.turn),
                int(state.year),
                int(state.period),
                agno_session_id,
                max(0, int(agno_runs_before)),
                nid,
                seq,
                initial_status,
            ),
        )
        if (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()
        return int(cur.lastrowid)

    def update_chat_turn_messages(
        self,
        chat_turn_id: int,
        user_message_id: Optional[int] = None,
        minister_message_id: Optional[int] = None,
    ) -> None:
        assignments: List[str] = []
        params: List[Any] = []
        if user_message_id is not None:
            assignments.append("user_message_id = ?")
            params.append(int(user_message_id))
        if minister_message_id is not None:
            assignments.append("minister_message_id = ?")
            params.append(int(minister_message_id))
            assignments.append("error_pack_path = ''")
            # 回话入档 = 轮完成：generating → active（#498 完成态）
            assignments.append("status = CASE WHEN status = 'generating' THEN 'active' ELSE status END")
        if not assignments:
            return
        params.append(int(chat_turn_id))
        self.conn.execute(
            f"UPDATE chat_turns SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        self.conn.commit()

    def mark_chat_turn_failed(self, chat_turn_id: int) -> None:
        self.conn.execute(
            "UPDATE chat_turns SET status = 'failed' "
            "WHERE id = ? AND status IN ('active', 'generating')",
            (int(chat_turn_id),),
        )
        self.conn.commit()

    def fail_chat_turn(self, chat_turn_id: int) -> List[int]:
        """Mark an incomplete audience turn failed and remove its partial user-visible writes."""
        row = self.conn.execute(
            "SELECT * FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
        if row is None:
            return []
        turn_row = self._row_dict(row)
        if turn_row["status"] not in {"active", "generating"}:
            self.conn.execute(
                "UPDATE chat_turns SET status = 'failed' WHERE id = ?",
                (int(chat_turn_id),),
            )
            self.conn.commit()
            return []
        items = self.conn.execute(
            """
            SELECT * FROM chat_turn_rollback_items
            WHERE chat_turn_id = ?
            ORDER BY id DESC
            """,
            (int(chat_turn_id),),
        ).fetchall()
        message_ids = [
            int(mid)
            for mid in (turn_row.get("user_message_id"), turn_row.get("minister_message_id"))
            if mid
        ]
        restored_pending_action_ids: List[int] = []
        with self.conn:
            self._delete_turn_scoped_knowledge_sources_in_tx(chat_turn_id)
            # Same family as undo_chat_turn: drop enter/exit placeholders bound to this
            # turn so failed attach/exit cannot freeze night presence or scene pads (T16/C11).
            self.conn.execute(
                "DELETE FROM story_ledger_entries "
                "WHERE source_chat_turn_id = ? OR origin_chat_turn_id = ?",
                (int(chat_turn_id), int(chat_turn_id)),
            )
            restored_pending_action_ids = self._restore_chat_rollback_items_in_tx(items, message_ids)
            if message_ids:
                self.chat_messages.delete_ids(message_ids)
                self.character_knowledge.delete_by_source_ids(
                    [f"chat_message:{mid}" for mid in message_ids], commit=False,
                )
            self.conn.execute(
                "UPDATE chat_turns SET status = 'failed' WHERE id = ?",
                (int(chat_turn_id),),
            )
            self._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )
        return restored_pending_action_ids

    def record_chat_turn_rollback_diffs(
        self,
        chat_turn_id: int,
        before: Dict[str, Dict[str, Dict[str, Any]]],
        after: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> None:
        rows: List[Tuple[int, str, str, str, str, str, str]] = []
        for table, before_rows in before.items():
            after_rows = after.get(table, {})
            all_ids = set(before_rows) | set(after_rows)
            for target_id in sorted(all_ids):
                before_row = before_rows.get(target_id)
                after_row = after_rows.get(target_id)
                if before_row == after_row:
                    continue
                if before_row is None and after_row is not None:
                    strategy = "delete_inserted_row"
                elif before_row is not None and after_row is None:
                    strategy = "restore_deleted_row"
                else:
                    strategy = "restore_row"
                rows.append(
                    (
                        int(chat_turn_id),
                        table,
                        table,
                        str(target_id),
                        self._json_dump_row(before_row or {}),
                        self._json_dump_row(after_row or {}),
                        strategy,
                    )
                )
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT INTO chat_turn_rollback_items
                (chat_turn_id, kind, target_table, target_id, before_json, after_json, rollback_strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()

    def _agno_session_columns(self) -> set:
        if not self._table_exists("agno_sessions"):
            return set()
        return {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(agno_sessions)").fetchall()
        }

    def agno_runs_length(self, session_id: str) -> int:
        """Count Agno run history for a session (single logical list).

        Authority is Agno's ``merge_runs_table_with_legacy_blob``: legacy blob
        order first (duplicates preserved); same run_id prefers the table copy;
        table-only rows append in ``(run_index, created_at, run_id)``. Missing
        tables/columns mean a fresh session with no history yet (length 0)—
        schema drift must not be swallowed via OperationalError→0.
        """
        if not session_id:
            return 0
        return len(self._agno_merged_runs(session_id))

    def truncate_agno_session_runs(self, session_id: str, keep_count: int) -> None:
        """截回 session 的 Agno 历史到 keep_count（transport 重试 per-attempt）。

        与 truncate_chat_turn_agno_runs 同接缝 ``_truncate_agno_runs_in_tx``；
        不改 chat_turn 状态、不碰游戏账/回话（≠ fail_chat_turn / 0036 落账）。
        """
        if not session_id:
            return
        with self.conn:
            self._truncate_agno_runs_in_tx(str(session_id), max(0, int(keep_count)))

    def truncate_chat_turn_agno_runs(self, chat_turn_id: int) -> None:
        """截回本轮起点的 Agno 历史（transport 重试 per-attempt）。

        复用 fail/undo/reconcile 同一 `_truncate_agno_runs_in_tx` 接缝；
        不改 chat_turn 状态、不碰游戏账/回话（≠ fail_chat_turn）。
        """
        if not chat_turn_id:
            return
        row = self.conn.execute(
            "SELECT * FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
        if row is None:
            return
        turn_row = self._row_dict(row)
        self.truncate_agno_session_runs(
            str(turn_row.get("agno_session_id") or ""),
            int(turn_row.get("agno_runs_before") or 0),
        )

    def _decode_agno_runs(self, raw: Any) -> Tuple[List[Any], bool]:
        if raw in (None, ""):
            return [], False
        from ming_sim.applier import load_stored_json

        decoded = load_stored_json(raw, label="agno runs", blank=[])
        encoded_as_string = isinstance(decoded, str)
        if encoded_as_string:
            decoded = load_stored_list(decoded, label="agno runs")
        if not isinstance(decoded, list) or any(not isinstance(run, dict) for run in decoded):
            raise ValueError("agno runs 须为对象名单")
        return decoded, encoded_as_string

    def _encode_agno_runs(self, runs: List[Any], encoded_as_string: bool) -> str:
        if encoded_as_string:
            return json.dumps(json.dumps(runs, ensure_ascii=False), ensure_ascii=False)
        return json.dumps(runs, ensure_ascii=False)

    def _agno_table_run_dicts(self, session_id: str) -> List[Dict[str, Any]]:
        if not self._table_exists("agno_runs"):
            return []
        rows = self.conn.execute(
            """
            SELECT run_id, run_data FROM agno_runs
            WHERE session_id = ?
            ORDER BY run_index ASC, created_at ASC, run_id ASC
            """,
            (session_id,),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            rid = row["run_id"]
            if rid is None:
                continue
            payload: Dict[str, Any] = {"run_id": str(rid)}
            raw = row["run_data"]
            if raw not in (None, ""):
                payload = load_stored_object(raw, label="agno run_data")
                payload["run_id"] = str(rid)
            out.append(payload)
        return out

    def _agno_legacy_runs_blob(self, session_id: str) -> Tuple[List[Any], bool]:
        """Legacy ``agno_sessions.runs`` list for one session (empty if absent)."""
        if "runs" not in self._agno_session_columns():
            return [], False
        row = self.conn.execute(
            "SELECT runs FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return [], False
        return self._decode_agno_runs(row["runs"])

    def _agno_merged_runs(self, session_id: str) -> List[Dict[str, Any]]:
        """Session run history in Agno merge order (single count/truncate domain)."""
        from agno.db.utils import merge_runs_table_with_legacy_blob

        table_runs = self._agno_table_run_dicts(session_id)
        legacy_runs, _encoded = self._agno_legacy_runs_blob(session_id)
        merged = merge_runs_table_with_legacy_blob(
            table_runs, legacy_runs if legacy_runs else None
        )
        if any(not isinstance(run, dict) for run in merged):
            raise ValueError("agno merged runs 须为对象名单")
        return merged

    def _rewrite_session_legacy_runs_blob(
        self, session_id: str, runs: List[Any]
    ) -> None:
        if "runs" not in self._agno_session_columns():
            return
        row = self.conn.execute(
            "SELECT runs FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return
        _old, encoded_as_string = self._decode_agno_runs(row["runs"])
        self.conn.execute(
            "UPDATE agno_sessions SET runs = ?, updated_at = strftime('%s','now') "
            "WHERE session_id = ?",
            (self._encode_agno_runs(list(runs), encoded_as_string), session_id),
        )

    def _truncate_agno_runs_in_tx(self, session_id: str, keep_count: int) -> None:
        """Truncate session run history back to keep_count (retry/undo/reconcile).

        Uses the same Agno-merged history as ``agno_runs_length``. Keeps the
        prefix as the new legacy blob and drops table rows whose run_id is not
        in that prefix, so a subsequent Agno merge read matches the prefix.
        Other sessions are untouched.
        """
        if not session_id:
            return
        keep = max(0, int(keep_count))
        merged = self._agno_merged_runs(session_id)
        if len(merged) <= keep:
            return
        kept = merged[:keep]
        kept_ids = {
            str(run["run_id"])
            for run in kept
            if run.get("run_id") is not None
        }
        if self._table_exists("agno_runs"):
            rows = self.conn.execute(
                "SELECT run_id FROM agno_runs WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            drop_ids = [
                str(r["run_id"])
                for r in rows
                if r["run_id"] is not None and str(r["run_id"]) not in kept_ids
            ]
            if drop_ids:
                self.conn.executemany(
                    "DELETE FROM agno_runs WHERE session_id = ? AND run_id = ?",
                    [(session_id, rid) for rid in drop_ids],
                )
        # Rewrite blob to the kept prefix so duplicate-id multiplicity and order
        # stay identical to what Agno merge would return for that prefix.
        self._rewrite_session_legacy_runs_blob(session_id, kept)

    def get_last_active_chat_turn(self, minister_name: str, turn: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT * FROM chat_turns
            WHERE minister_name = ? AND turn = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (minister_name, int(turn)),
        ).fetchone()
        return self._row_dict(row) if row is not None else None

    def persist_minister_reply(
        self,
        minister_name: str,
        turn: int,
        content: str,
        chat_turn_id: int,
    ) -> int:
        """**一个事务**内插入大臣回话、链接到 turn 并升为 active，返回 message_id。

        消息插入、turn 链接和状态升级同成同败，避免留下未关联的持久回话。
        知识轨纪律同 append_chat_message：insert 即 'held'，投轨唯一出口是 release（#976）。
        status 升级同 update_chat_turn_messages（#498 挂夜轮以 generating 起笔，回话落库后升 active）——
        本函数是 update_chat_turn_messages(minister_message_id=...) 的原子替代，须同做该升级。
        """
        with self.conn:  # 事务：成功提交、异常回滚（插入的回话一并撤销）；外层 atomic 内 commit 暂停
            message_id = self.chat_messages.insert(
                minister_name=minister_name, turn=int(turn), role="minister", content=content,
            )
            self.conn.execute(
                """
                UPDATE chat_turns
                SET minister_message_id = ?,
                    error_pack_path = '',
                    status = CASE WHEN status = 'generating' THEN 'active' ELSE status END
                WHERE id = ?
                """,
                (message_id, int(chat_turn_id)),
            )
        return message_id

    # ----- #634 召对判官水位（ADR 0082：逐轮标记即水位，无平行水位表）-----

    def delete_relation_edge_events_for_chat_turn(self, chat_turn_id: int) -> int:
        """撤回联动（ADR 0038 白名单③ / #1839 第四类）：删该轮源绑定的边事件行。

        事务归属调用方：undo_chat_turn 在其原子块内调（禁提前 commit）；origin 的
        chat_turn 段是唯一的源轮绑定真源——relations.summon_edge_origin
        与转译声明路径（declaration_dispatch 拼装
        ``转译声明|chat_turn:{id}``）共用同一段形态。
        """
        cid = int(chat_turn_id)
        total = 0
        for prefix in (SUMMON_EDGE_ORIGIN_PREFIX, "转译声明"):
            cur = PersonLogStore(self.conn).write_delete_relation_edge_events_for_chat_turn((f"{prefix}|chat_turn:{cid}|%",))
            total += int(cur.rowcount)
        return total

    # ----- #501 召对转译待补状态（沿用 extract_status）-----

    def get_story_extract_status(self, chat_turn_id: int) -> str:
        row = self.conn.execute(
            "SELECT extract_status FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
        return str(row["extract_status"] or "") if row is not None else ""

    def set_chat_turn_error_pack(self, chat_turn_id: int, path: str) -> None:
        self.conn.execute(
            "UPDATE chat_turns SET error_pack_path = ? WHERE id = ? AND status NOT IN ('failed', 'undone')",
            (path, int(chat_turn_id)),
        )
        self.conn.commit()

    def mark_story_extraction_pending(self, chat_turn_id: int) -> None:
        """转译失败 → 待补（'' / 'pending' → 'pending'）；不覆盖已 'done'。"""
        self.conn.execute(
            "UPDATE chat_turns SET extract_status = 'pending' "
            "WHERE id = ? AND extract_status IN ('', 'pending')",
            (int(chat_turn_id),),
        )
        self.conn.commit()

    def list_unextracted_replies(
        self, *, night_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """已持久化完整回话但账未抽（''/'pending'）的对话轮——补跑抽取的重试真源（ADR 0036）。

        完整回话 = minister_message_id 已链接且轮未 failed/undone。带回话正文与源轮夜内时序，
        供补跑落回原时序。挂夜（night_id>0）轮才进抽取链；未挂夜的旧路径不涉。
        """
        clauses = [
            "t.night_id > 0",
            "t.status = 'active'",
            "t.minister_message_id IS NOT NULL",
            "t.minister_message_id > 0",
            "t.extract_status IN ('', 'pending')",
        ]
        params: List[Any] = []
        if night_id is not None and int(night_id) > 0:
            clauses.append("t.night_id = ?")
            params.append(int(night_id))
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""
            SELECT t.id AS chat_turn_id, t.minister_name, t.night_id, t.night_seq,
                   t.extract_status, t.error_pack_path, t.minister_message_id
            FROM chat_turns t
            WHERE {where}
            ORDER BY night_id ASC, night_seq ASC, id ASC
            """,
            params,
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            reply = self.chat_messages.content_of(int(row["minister_message_id"]))
            if reply is None:
                continue
            item = self._row_dict(row)
            item.pop("minister_message_id", None)
            item["reply"] = reply
            out.append(item)
        return out

    def is_global_last_active_chat_turn(self, chat_turn_id: int) -> bool:
        row = self.conn.execute(
            "SELECT id FROM chat_turns WHERE status IN ('active', 'interrupted') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return bool(row and int(row["id"]) == int(chat_turn_id))

    def can_undo_last_chat_turn(self, minister_name: str, turn: int) -> bool:
        row = self.get_last_active_chat_turn(minister_name, turn)
        if row is None:
            return False
        if not row.get("user_message_id") or not row.get("minister_message_id"):
            return False
        return self.is_global_last_active_chat_turn(int(row["id"]))

    def _restore_row_in_tx(self, table: str, row: Dict[str, Any]) -> None:
        if not row:
            return
        row = {key: value for key, value in row.items() if not key.startswith("_rollback_")}
        if table in ("secret_orders", "public_sayings"):
            self.character_knowledge.restore_snapshot(table, row)
            return
        if table == "relation_edge_events":
            self.person_logs.restore_edge(row)
            return
        if table == "armies":
            self.armies.upsert({key: value for key, value in row.items() if key != "arrears"})
            return
        if table == "characters":
            self.characters.restore_row(row)
            return
        if table == "character_offices":
            self.characters.restore_office_row(row)
            return
        if table == "decree_dossiers":
            self.dossiers.restore_row(row)
            return
        if table == "decree_dossier_decisions":
            self.dossiers.restore_decision(row)
            return
        if table == "dossier_reported_progress":
            self.dossiers.restore_reported_progress(row)
            return
        if table == "factions":
            self.factions.restore_row(row)
            return
        if table == "textual_facts":
            self.textual_facts.restore_row(row)
            return
        pk = self._ROLLBACK_TABLE_PK.get(table)
        if not pk:
            raise ValueError(f"不支持回滚表：{table}")
        if self.conn.execute(
            f"SELECT 1 FROM {table} WHERE {pk} = ?", (row[pk],)
        ).fetchone() is not None:
            columns = [column for column in row if column != pk]
            assignments = ",".join(f"{column}=?" for column in columns)
            self.conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {pk}=?",
                [row[column] for column in columns] + [row[pk]],
            )
            return
        columns = list(row.keys())
        placeholders = ",".join("?" for _ in columns)
        column_sql = ",".join(columns)
        self.conn.execute(
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def _delete_row_in_tx(self, table: str, target_id: str) -> None:
        if table in ("secret_orders", "public_sayings"):
            self.character_knowledge.delete_snapshot(table, target_id)
            return
        if table == "relation_edge_events":
            self.person_logs.delete_edge(target_id)
            return
        if table == "characters":
            self.characters.delete(target_id)
            return
        if table == "character_offices":
            self.characters.delete_office(target_id)
            return
        if table == "decree_dossiers":
            self.dossiers.delete_dossier(target_id)
            return
        if table == "decree_dossier_decisions":
            self.dossiers.delete_decision(target_id)
            return
        if table == "dossier_reported_progress":
            self.dossiers.delete_reported_progress(target_id)
            return
        if table == "factions":
            self.factions.delete(target_id)
            return
        if table == "textual_facts":
            self.textual_facts.delete(target_id)
            return
        pk = self._ROLLBACK_TABLE_PK.get(table)
        if not pk:
            raise ValueError(f"不支持回滚表：{table}")
        self.conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (target_id,))

    def _restore_secret_order_brief_projection_in_tx(
        self, order_id: int, origin_chat_message_ids: Iterable[int],
    ) -> None:
        order = CharacterKnowledgeStore(self.conn).read_restore_secret_order_brief_projection_in_tx((int(order_id),))
        if order is None:
            return
        pins = self._coerce_positive_message_ids(origin_chat_message_ids)
        self.character_knowledge.upsert_secret_brief(
            order_id=int(order_id), turn=int(order["turn_issued"]),
            year=int(order["year_issued"]), period=int(order["period_issued"]),
            minister_name=str(order["minister_name"]), title=str(order["title"]),
            body=str(order["content"]), origin_chat_message_ids=safe_json_dumps(pins, ensure_ascii=False),
        )

    def _restore_chat_rollback_items_in_tx(
        self, items: Iterable[sqlite3.Row], undone_message_ids: Iterable[int],
    ) -> List[int]:
        undone = {int(message_id) for message_id in undone_message_ids}
        rollback_items = list(items)
        restored_directive_ids: set[int] = set()

        def dependency_order(item: sqlite3.Row) -> int:
            table = str(item["target_table"])
            strategy = str(item["rollback_strategy"])
            if strategy == "delete_inserted_row":
                return {
                    "decree_dossier_decisions": 0,
                    "decree_dossiers": 1,
                    "secret_orders": 2,
                }.get(table, 1)
            return {
                "secret_orders": 0,
                "decree_dossiers": 1,
                "decree_dossier_decisions": 2,
            }.get(table, 1)

        for item in sorted(rollback_items, key=dependency_order):
            table = str(item["target_table"])
            strategy = str(item["rollback_strategy"])
            target_id = str(item["target_id"])
            if strategy == "delete_inserted_row":
                if table == "pending_actions":
                    self._discard_deleted_directive_forecast(target_id)
                self._delete_row_in_tx(table, target_id)
            elif strategy in {"restore_row", "restore_deleted_row"}:
                before_row = self._json_load_row(item["before_json"])
                if table == "pending_actions" and before_row.get("kind") == "directive":
                    pending_id = int(before_row["id"])
                    restored_directive_ids.add(pending_id)
                    before_version = int(before_row.get("version") or 1)
                    current = self.conn.execute(
                        "SELECT version FROM pending_actions WHERE id=? AND kind='directive'",
                        (pending_id,),
                    ).fetchone()
                    current_version = int(current["version"] or 1) if current is not None else 0
                    self._discard_pending_decree_forecast(pending_id, before_version)
                    if current_version:
                        self._discard_pending_decree_forecast(pending_id, current_version)
                    # 0038 的恢复是一次新改草：身份号继续递增，不把已作废版本复活。
                    before_row["version"] = max(before_version, current_version) + 1
                self._restore_row_in_tx(table, before_row)
                if table == "secret_orders":
                    raw_pins = before_row.get("_rollback_brief_origin_chat_message_ids")
                    if raw_pins is None:
                        current = self._brief_origin_chat_message_ids(int(target_id))
                        pins = [pin for pin in current if int(pin) not in undone]
                    else:
                        pins = load_stored_list(raw_pins, label="rollback brief pins")
                    self._restore_secret_order_brief_projection_in_tx(int(target_id), pins)
            else:
                raise ValueError(f"不支持的回滚策略：{strategy}")
        if not restored_directive_ids:
            return []
        placeholders = ",".join("?" for _ in restored_directive_ids)
        rows = self.conn.execute(
            "SELECT id FROM pending_actions WHERE id IN (" + placeholders + ") "
            "AND kind='directive' AND action='拟旨' AND status='pending' "
            "AND night_approved=1 AND night_id>0",
            sorted(restored_directive_ids),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def undo_chat_turn(self, chat_turn_id: int) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
        if row is None:
            raise ValueError("召对轮次不存在。")
        turn_row = self._row_dict(row)
        if turn_row["status"] != "active":
            raise ValueError("该召对已经撤回或不可撤回。")
        if not self.is_global_last_active_chat_turn(int(chat_turn_id)):
            raise ValueError("只能撤回全局最后一轮召对。")
        # #506 封窗：收夜/颁诏封住撤回窗口（ADR 0038）。该轮所在夜一旦进入 closing/closed，
        # 撤回不跨已收的夜——已应允暂存已在收夜提交、账已成史，此后反悔按 ADR 0006 是新的
        # 游戏内命令而非 undo。phase 闸只守颁诏结算相位、守不住「夜已收但相位未变」的窗口。
        night_id = int(turn_row.get("night_id") or 0)
        if night_id > 0:
            nrow = self.conn.execute(
                "SELECT status FROM audience_nights WHERE id = ?", (night_id,),
            ).fetchone()
            if nrow is not None and str(nrow["status"] or "") in {"closing", "closed"}:
                raise ValueError("本夜已收（或颁诏封窗），撤回窗口已关，不能撤回该轮召对。")
        items = self.conn.execute(
            """
            SELECT * FROM chat_turn_rollback_items
            WHERE chat_turn_id = ?
            ORDER BY id DESC
            """,
            (int(chat_turn_id),),
        ).fetchall()
        message_ids = [
            int(mid)
            for mid in (turn_row.get("user_message_id"), turn_row.get("minister_message_id"))
            if mid
        ]
        # 颁诏 owning transaction 的 commit_pending_actions 可能在召对 diff 已记录之后
        # 才生成 turn_directives(status='draft')，因此那类行不会进入 rollback_items
        # （召对期直接更新的 turn_directives 仍会被快照捕获并还原）。
        # 删除前，从本召对触碰过的 pending_actions(kind='directive') 行读取
        # committed_directive_id，并且只删除那条 draft 行（BUG 3：旧实现按
        # (turn,actor) 删除，会连同同 actor 同回合的无关 draft 一起删掉）。
        # BUG（补充路径）：首次拟旨是 INSERT(delete_inserted_row)，补充（第 2 次拟旨）
        # 是 UPDATE 既有 pending 行，因此 diff 会变成 restore_row。若按 strategy 过滤，
        # 补充→颁诏→撤回流程会漏掉 committed_directive_id，残留 orphan draft 污染颁诏。
        # 所以不依赖 strategy，只要该行 kind=='directive' 就回收。
        draft_ids_to_delete: List[int] = []
        seen_draft_ids: set[int] = set()
        for item in items:
            if str(item["target_table"]) != "pending_actions":
                continue
            # restore_row 中 after 是补充后的状态，before 是补充前的状态。两侧都有 id，
            # kind 也相同，取任一侧即可。delete_inserted_row 只有 after，
            # restore_deleted_row 只有 before。
            after_data = self._json_load_row(item["after_json"] or "") or {}
            before_data = self._json_load_row(item["before_json"] or "") or {}
            kind = str(after_data.get("kind") or before_data.get("kind") or "")
            if kind != "directive":
                continue
            pa_id = after_data.get("id")
            if pa_id is None:
                pa_id = before_data.get("id")
            if pa_id is None:
                continue
            live = self.conn.execute(
                "SELECT committed_directive_id FROM pending_actions WHERE id=?",
                (int(pa_id),),
            ).fetchone()
            if live is not None and int(live["committed_directive_id"] or 0) > 0:
                did = int(live["committed_directive_id"])
                if did not in seen_draft_ids:
                    seen_draft_ids.add(did)
                    draft_ids_to_delete.append(did)
        with self.conn:
            self._delete_turn_scoped_knowledge_sources_in_tx(chat_turn_id)
            # #634 撤回联动（ADR 0038 白名单③）：删该轮源绑定的召对边事件；undone 轮
            # 天然出判官窗口（status != active），水位随逐轮标记失效自动回退。
            self.delete_relation_edge_events_for_chat_turn(chat_turn_id)
            # #506：删该轮所产故事账——抽取账走 source_chat_turn_id、该轮 attach 创建的
            # 入殿等口令账走 origin_chat_turn_id。晚落的补跑抽取账也按 source 删（不受
            # 前像快照时刻限制）；开夜/员额/收夜等框架账 origin==0、不随本轮撤。撤回后
            # 「按夜取数（账+在场）与该轮未发生等价」（ADR 0038）。
            self.conn.execute(
                "DELETE FROM story_ledger_entries "
                "WHERE source_chat_turn_id = ? OR origin_chat_turn_id = ?",
                (int(chat_turn_id), int(chat_turn_id)),
            )
            # 背书是该轮已说出口对话的派生事实；撤回来源轮时须同步失效。
            self.dossiers.delete_endorsements_for_chat_turn(int(chat_turn_id))
            restored_pending_action_ids = self._restore_chat_rollback_items_in_tx(
                items, message_ids,
            )
            # 只精确删除本召对 commit 出来的 draft 行（保留同 actor 的无关 draft）。
            for draft_id in draft_ids_to_delete:
                self.conn.execute(
                    "DELETE FROM turn_directives WHERE id=? AND status='draft'",
                    (int(draft_id),),
                )
            if message_ids:
                self.chat_messages.delete_ids(message_ids)
                self.character_knowledge.delete_by_source_ids(
                    [f"chat_message:{mid}" for mid in message_ids], commit=False,
                )
            self.conn.execute(
                """
                UPDATE chat_turns
                SET status = 'undone', undone_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(chat_turn_id),),
            )
            # #1838 / ADR 0155：夜当前主角是投影，不是独立真源。撤本轮后按该夜
            # 仍存活轮（status 非 undone/failed）最近一条非空 chat_turns.protagonist_name
            # 重投影 audience_nights.protagonist_name；无存活声明则回初态空值。
            # 覆盖转译绑定与宣 X 先切两个写口（二者都写同一夜级缓存）。
            if night_id > 0:
                from ming_sim.audience_night import reproject_night_protagonist
                reproject_night_protagonist(self, night_id)
            self._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )
        # P1-2：报告本召对删除了哪些 committed draft（write_decree 已 commit 的对话草案行）。
        # 上层据此让已生成的诏书正文（last_decree）失效——否则若另有 draft 残留，玩家仍能
        # 原样颁出含被撤回指令的陈旧诏书。无删除则为空，普通撤回不触发上层清稿。
        turn_row["deleted_committed_draft_ids"] = list(draft_ids_to_delete)
        turn_row["restored_pending_action_ids"] = restored_pending_action_ids
        return turn_row

    def save_turn_report(
        self, state: GameState, report: str,
        knowledge_items: Optional[Iterable[Mapping[str, object]]] = None,
        public_body: Optional[str] = None,
        *,
        attendant_message: str = "",
        title: str = "",
        commit: bool = True,
    ) -> None:
        """每回合月末奏报单独存档（turn_reports）。

        ``report`` is a presentation aggregate and is not used for access
        control.  Producers that mix public and restricted material may pass
        the source-scoped ``knowledge_items`` projection; each item is then
        durable independently for character reads.

        ``attendant_message``（#671）是王承恩独立递话，与官方 report 分栏同原子写。
        """
        self.persist_knowledge_items_for_turn(state, knowledge_items, commit=commit)
        items = [item for item in self.knowledge_items_for_turn(state.turn)
                 if not str(item.get("source_id") or "").startswith("turn_report:")]
        # #883/#976: private secret briefs never enter shared sources.  Shared
        # exclusions force source-scoped aggregation; active briefs alone do
        # not blank pure public prose (F3). Secret text is kept out by structure
        # (never in knowledge_items / public LLM inputs), not by needle strip.
        has_restricted_source = self._has_restricted_source_gate(
            any(item.get("excluded_names") for item in items)
        )
        source_snapshot_supplied = knowledge_items is not None
        settlement_items = [
            item for item in items
            if str(item.get("source_id") or "") == f"settlement:narrative:{state.turn}"
            and not item.get("excluded_names")
        ]
        if public_body is None:
            public_report = (
                "\n".join(str(item.get("body") or "") for item in settlement_items)
                if settlement_items else
                "\n".join(str(item.get("body") or item.get("title") or "")
                          for item in items if not item.get("excluded_names"))
                if source_snapshot_supplied or has_restricted_source else str(report or "")
            )
        else:
            public_report = str(public_body or "")
        # #976: no text-filter strip. Public archives trust the producer path
        # (public LLMs never preload secrets; private briefs are not knowledge_items).
        self.turn_reports.upsert(
            turn=state.turn,
            year=state.year,
            period=state.period,
            report=sanitize_sqlite_text(public_report),
            attendant_message=sanitize_sqlite_text(str(attendant_message or "")),
            title=sanitize_sqlite_text(str(title or "")),
        )
        # Aggregate prose cannot authorize an audience read: removing known
        # secret substrings is not safe against a paraphrase.  Persist a
        # separate public counterpart made from source-scoped public items.
        # Legacy callers with no restricted source retain their whole report.
        if public_report:
            self.record_public_knowledge_event(
                state, "邸报", sanitize_sqlite_text(public_report),
                source_id=f"turn_report:{state.turn}:public", commit=commit,
            )
        if commit:
            self.conn.commit()

    def previous_turn_attendant_message(self, state: GameState) -> str:
        """#671：状态口投影——仅上一已完成月的独立递话。"""
        previous_turn = int(state.turn) - 1
        if previous_turn < 0:
            return ""
        return self.turn_reports.attendant_message(previous_turn)

    def persist_knowledge_items_for_turn(
        self,
        state: GameState,
        knowledge_items: Optional[Iterable[Mapping[str, object]]] = None,
        *,
        default_title: str = "邸报事项",
        commit: bool = True,
    ) -> None:
        """Materialize every turn source before any aggregate archive is read.

        The gazette is derived prose, not an authorization boundary.
        Persisting the public projection of both unscoped and participant-scoped
        source rows first gives the read model an independent item boundary.  The
        operation is idempotent by ``(character_name, kind, source_id)`` and is
        deliberately callable from the real settlement transaction before the
        aggregate writers run.
        """
        items = knowledge_items
        if items is None:
            items = self.knowledge_items_for_turn(state.turn)
        for item in items:
            source_id = str(item.get("source_id") or "")
            existing_kind = self.character_knowledge.public_kind_for_source(source_id)
            # An explicit disclosure is the authoritative event for this
            # provenance.  Archive materialization may fill a missing ledger
            # row, but must never downgrade public back to roster-scoped.
            if existing_kind == "public":
                continue
            self.record_public_knowledge_event(
                state,
                str(item.get("title") or default_title),
                str(item.get("body") or ""),
                source_id=source_id,
                excluded_names=item.get("excluded_names") or (),
                kind="source_projection",
                commit=commit,
            )

    def knowledge_items_for_turn(self, turn: int) -> List[Dict[str, object]]:
        """Return source-scoped public material for archive projection.

        Aggregate archives are presentation artifacts.  Replaying the durable
        public rows here keeps source_id and explicit exclusions attached to
        each item when a turn report is saved.  Source rows are included as
        well: settlement producers may register a participating item before
        the report is rendered, and the archive write must
        not lose that item's access boundary.
        """
        rows = self.character_knowledge.public_events_for_turn(turn)
        by_source: Dict[str, Dict[str, object]] = {}
        for row in rows:
            excluded_names = load_stored_list(row["excluded_names"], label='excluded_names')
            if not isinstance(excluded_names, list):
                raise ValueError("excluded_names 不是名单")
            item = {
                "title": row["title"], "body": row["body"],
                "source_id": row["source_id"], "excluded_names": excluded_names,
            }
            by_source[str(row["source_id"] or "")] = item

        source_rows = self.character_knowledge.sources_for_turn(turn)
        characters = CharacterStore(self.conn).read_knowledge_items_for_turn()
        character_names = {str(row["name"]) for row in characters}
        for row in source_rows:
            participants = participant_roster_names(row["participant_roster"])
            excluded_names = load_stored_list(row["excluded_names"], label='excluded_names')
            if not isinstance(excluded_names, list):
                raise ValueError("excluded_names 不是名单")
            excluded_targets = load_stored_object(row["excluded_targets"], label='excluded_targets')
            if not isinstance(excluded_targets, dict):
                raise ValueError("excluded_targets 不是对象")
            target_people = {
                str(name) for name in excluded_targets.get("people", [])
            }
            target_offices = {
                str(office) for office in excluded_targets.get("offices", [])
            }
            excluded_names = list(dict.fromkeys(
                [*(str(name) for name in excluded_names),
                 *(str(item["name"]) for item in characters
                   if item["name"] in target_people
                   or item["office"] in target_offices
                   or item["office_type"] in target_offices)]
            ))
            # A participant-scoped source is materialized as a public ledger
            # row whose exclusion snapshot is stable across later transfers.
            # Empty rosters are genuinely public and therefore add no names.
            if participants:
                excluded_names = list(dict.fromkeys(
                    [*(str(name) for name in excluded_names),
                     *(sorted(character_names - participants))]
                ))
            # An explicit public event can describe a source after it becomes
            # public (for example, a disclosed secret order).  It is more
            # specific than the source's original private payload, so never
            # let archive materialization overwrite it merely because both
            # share provenance.
            by_source.setdefault(str(row["source_id"] or ""), {
                "title": row["title"], "body": row["body"],
                "source_id": row["source_id"], "excluded_names": excluded_names,
            })
        return list(by_source.values())

    # ── 结局总结 ──

    def save_ending_summary(
        self, state: GameState, ending_status: str, summary: str, timeline: List[Dict[str, object]]
    ) -> None:
        ReignStateStore(self.conn).write_save_ending_summary((
                state.turn, state.year, state.period, str(ending_status or ""),
                str(summary or ""), json.dumps(timeline or [], ensure_ascii=False),
            ))
        self.conn.commit()

    def get_ending_summary(self) -> Optional[Dict[str, object]]:
        """取最近一条结局总结（单库一局，按 turn 取最大）。无则 None。"""
        row = ReignStateStore(self.conn).read_get_ending_summary()
        if row is None:
            return None
        timeline = load_stored_json(
            row["timeline"], label=f"结局 timeline turn={row['turn']}", blank=[],
        )
        if not isinstance(timeline, list):
            raise ValueError(f"结局 timeline 必须为名单（turn={row['turn']}）")
        return {
            "turn": int(row["turn"]),
            "year": int(row["year"]),
            "period": int(row["period"]),
            "ending_status": row["ending_status"],
            "summary": row["summary"] or "",
            "timeline": timeline,
        }

    def list_monthly_archives(self) -> List[Dict[str, object]]:
        """每回合至多一条月档；召对场次绝不扩增月度时间线。"""
        by_turn: Dict[int, Dict[str, int]] = {}
        for row in self.turn_reports.presence_rows():
            turn = int(row["turn"])
            by_turn[turn] = {
                "year": int(row["year"] or 0),
                "period": int(row["period"] or 0),
                "has_report": int(row["has_report"] or 0),
                "has_attendant": int(row["has_attendant"] or 0),
                "has_directive": 0,
            }
        for row in self.conn.execute(
            "SELECT turn, year, period FROM turn_directives WHERE status = 'issued'"
        ).fetchall():
            turn = int(row["turn"])
            slot = by_turn.get(turn)
            year = int(row["year"] or 0)
            period = int(row["period"] or 0)
            if slot is None:
                by_turn[turn] = {
                    "year": year, "period": period,
                    "has_report": 0, "has_attendant": 0, "has_directive": 1,
                }
            else:
                slot["year"] = max(slot["year"], year)
                slot["period"] = max(slot["period"], period)
                slot["has_directive"] = 1
        return [{
            "kind": "month", "turn": turn,
            "year": slot["year"], "period": slot["period"],
            "has_report": bool(slot["has_report"]),
            "has_attendant": bool(slot["has_attendant"]),
            "has_directive": bool(slot["has_directive"]),
        } for turn, slot in sorted(by_turn.items())]

    def list_closed_night_archives(self) -> List[Dict[str, object]]:
        """逐场列出 closed audience night，并保留玩家可见命名所需的容器属性。"""
        rows = self.conn.execute(
            """
            SELECT id,turn,year,period,time_of_day,location,
                   ROW_NUMBER() OVER (
                       PARTITION BY turn, location, time_of_day ORDER BY id
                   ) AS scene_number,
                   COUNT(*) OVER (
                       PARTITION BY turn, location, time_of_day
                   ) AS scene_count
            FROM audience_nights WHERE status='closed' ORDER BY turn,id
            """
        ).fetchall()
        if not rows:
            return []

        from ming_sim.audience_night import _json_list, night_archive_metadata

        night_ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in night_ids)
        ledger_rows = self.conn.execute(
            f"SELECT night_id,person_names,tags,source_chat_turn_id "
            f"FROM story_ledger_entries WHERE night_id IN ({placeholders}) "
            "ORDER BY night_id,COALESCE(order_key,seq),id",
            night_ids,
        ).fetchall()
        turn_rows = self.conn.execute(
            f"SELECT night_id,minister_name FROM chat_turns "
            f"WHERE night_id IN ({placeholders}) "
            f"AND status NOT IN ('undone', 'failed', 'consumed') "
            "ORDER BY night_id,night_seq,id",
            night_ids,
        ).fetchall()
        ledgers_by_night: Dict[int, List[Dict[str, Any]]] = {night_id: [] for night_id in night_ids}
        turns_by_night: Dict[int, List[Dict[str, Any]]] = {night_id: [] for night_id in night_ids}
        for row in ledger_rows:
            ledgers_by_night[int(row["night_id"])].append({
                "person_names": [str(name) for name in _json_list(row["person_names"])],
                "tags": [str(tag) for tag in _json_list(row["tags"])],
                "source_chat_turn_id": int(row["source_chat_turn_id"] or 0),
            })
        for row in turn_rows:
            turns_by_night[int(row["night_id"])].append({
                "minister_name": str(row["minister_name"] or ""),
            })

        archives: List[Dict[str, object]] = []
        for r in rows:
            night_id = int(r["id"])
            metadata = night_archive_metadata(
                ledgers_by_night[night_id], turns_by_night[night_id],
            )
            scene_suffix = f" · 第{int(r['scene_number'])}场" if int(r["scene_count"]) > 1 else ""
            title = (
                f"{int(r['year'])}年{int(r['period'])}月 · "
                f"{str(r['time_of_day'] or '')}{str(r['location'] or '')} · "
                f"{metadata['audience_type']}{scene_suffix}"
            )
            archives.append({
                "kind": "night", "night_id": night_id, "turn": int(r["turn"]),
                "year": int(r["year"]), "period": int(r["period"]),
                "time_of_day": str(r["time_of_day"] or ""), "location": str(r["location"] or ""),
                "scene_number": int(r["scene_number"]), "scene_count": int(r["scene_count"]),
                "audience_type": metadata["audience_type"], "title": title,
                "involved_people": metadata["involved_people"],
            })
        return archives

    def list_archived_turns(self) -> List[Dict[str, object]]:
        """兼容组合读面：月档和场档保持独立条目，不再以 SQL join 互相复制。"""
        monthly = self.list_monthly_archives()
        nights = self.list_closed_night_archives()
        by_turn = {int(item["turn"]): item for item in monthly}
        combined = list(monthly)
        for night in nights:
            material = by_turn.get(int(night["turn"]), {})
            combined.append({
                **night,
                "has_report": bool(material.get("has_report", False)),
                "has_attendant": bool(material.get("has_attendant", False)),
                "has_directive": bool(material.get("has_directive", False)),
            })
        return sorted(combined, key=lambda item: (int(item["turn"]), 0 if item["kind"] == "month" else int(item["night_id"])))

    def list_directives_by_turn(self, turn: int) -> List[Dict[str, object]]:
        """读某回合已颁诏（issued）草案，按 id 升序。"""
        rows = IssueStore(self.conn).read_list_directives_by_turn_owned((int(turn),)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "event_id": r["event_id"] or "",
                "event_title": r["event_title"] or "",
                "actor": r["actor"] or "",
                "text": r["text"] or "",
                "source": r["source"] or "",
                "status": r["status"] or "",
                "notes": r["notes"] or "",
                "created_at": r["created_at"] or "",
                "updated_at": r["updated_at"] or "",
            }
            for r in rows
        ]

    def list_issued_directives(self) -> List[Dict[str, object]]:
        """读出所有已颁明发旨意，供跨回合公开见闻投影使用。"""
        rows = IssueStore(self.conn).read_list_issued_directives_owned(()).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "event_id": r["event_id"] or "",
                "event_title": r["event_title"] or "",
                "actor": r["actor"] or "",
                "text": r["text"] or "",
                "source": r["source"] or "",
                "status": r["status"] or "",
                "notes": r["notes"] or "",
            }
            for r in rows
        ]

    def save_pending_decisions(self, turn: int, decisions: List[Dict[str, object]]) -> None:
        """覆写本回合待裁 decision 行（先清后插），idx 按列表顺序。choice 初始空（待皇帝选）。

        #656 A6/F2 不变式：只清只写 kind='decision'（与 clear_pending_decisions/
        save_rescript_drafts 同款按 kind 收窄）——'rescript_draft' 票拟行跨月留存，
        不被 decision 盘面覆写连带清除。
        """
        turn = int(turn)
        # 两种 kind 共用 (turn, idx) 主键。先把保留的 draft 搬到负数暂存区，
        # 删除旧 decisions 后再按新盘面长度接续重排；draft 的内容与 event_id
        # 均不改，decision 数量增减也不会与旧 draft idx 相撞。
        self.conn.execute(
            "UPDATE pending_decisions SET idx = -idx - 1 "
            "WHERE turn = ? AND kind = 'rescript_draft'",
            (turn,),
        )
        draft_rows = self.conn.execute(
            "SELECT idx FROM pending_decisions "
            "WHERE turn = ? AND kind = 'rescript_draft' ORDER BY idx DESC",
            (turn,),
        ).fetchall()
        self.conn.execute(
            "DELETE FROM pending_decisions WHERE turn = ? AND kind = 'decision'",
            (turn,),
        )
        for idx, d in enumerate(decisions):
            self.conn.execute(
                """INSERT INTO pending_decisions
                   (turn, idx, event_id, title, context, rejection_reason, opposition,
                    options_json, choice_json, status, kind)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', 'pending', 'decision')""",
                (
                    turn, idx,
                    str(d.get("event_id") or ""),
                    str(d.get("title") or ""),
                    str(d.get("context") or ""),
                    str(d.get("rejection_reason") or ""),
                    str(d.get("opposition") or ""),
                    json.dumps(d.get("options") or [], ensure_ascii=False),
                ),
            )
        for offset, row in enumerate(draft_rows):
            self.conn.execute(
                "UPDATE pending_decisions SET idx = ? WHERE turn = ? AND idx = ?",
                (len(decisions) + offset, turn, int(row["idx"])),
            )
        self.conn.commit()

    def list_pending_decisions(self, turn: int) -> List[Dict[str, object]]:
        """读本回合决策点（按 idx）——HITL envelope 唯一读取缝。

        #656 A6：谓词收窄到 kind='decision'——persist-then-abort 后落库的
        rescript_draft 票拟行不再混进亲裁/刷新/all-decided/submit 消费面
        （急务只经 list_rescript_drafts 读，批红面归 #657）；调用方不再重复过滤。
        options 反序列化；choice 为已选则带出。
        #657：补 revision_round / prior_options_json 投影。
        """
        rows = self.conn.execute(
            "SELECT idx, event_id, title, context, rejection_reason, opposition, "
            "options_json, choice_json, status, kind, actor_name, actor_office, actor_faction, "
            "turn, revision_round, prior_options_json "
            "FROM pending_decisions WHERE turn = ? AND kind = 'decision' ORDER BY idx",
            (int(turn),),
        ).fetchall()
        out: List[Dict[str, object]] = []
        for r in rows:
            options, choice, prior = _decision_json_fields(r)
            source_turn = int(r["turn"])
            idx = int(r["idx"])
            kind = str(r["kind"] or "decision")
            out.append({
                "idx": idx,
                "decision_key": f"{kind}:{source_turn}:{idx}",
                "source_turn": source_turn,
                "turn": source_turn,
                "event_id": r["event_id"],
                "title": r["title"],
                "context": r["context"],
                "rejection_reason": r["rejection_reason"],
                "opposition": r["opposition"],
                "options": options,
                "choice": choice,
                "status": r["status"],
                "kind": kind,
                "actor_name": r["actor_name"],
                "actor_office": r["actor_office"],
                "actor_faction": r["actor_faction"],
                "revision_round": int(r["revision_round"] or 0),
                "prior_options_json": prior,
            })
        return out

    def clear_pending_decisions(self, turn: int) -> None:
        """#656：按 kind 过滤——只清 'decision' 行（既有生命周期一字不变）；
        'rescript_draft' 行跨月留存，终态清理归 #657 六动作裁决路径。"""
        self.conn.execute(
            "DELETE FROM pending_decisions WHERE turn = ? AND kind = 'decision'",
            (int(turn),),
        )
        self.conn.commit()

    def save_rescript_drafts(self, turn: int, drafts: List[Dict[str, object]]) -> None:
        """#656 / ADR 0093 前半：急务票拟行（kind='rescript_draft'）覆写本回合。

        与 save_pending_decisions 同款先清后插（只清同 kind，不碰 decision 行）；
        idx 从本回合保留的 decision 行最大 idx 之后续编（与 decision 行共占
        (turn, idx) 主键不撞）。event_id 缺失的急务在此确定性合成 `urgent:{turn}:{idx}`
        （票面 F2.2）。
        只写 conn 不 commit——提交交调用方事务（与 save_resolve_context 同事务序列，F2.5）。
        """
        # 先删后算 idx（#656 A3）：起始 idx 只由保留的 decision 行决定——相同
        # decision 盘面重复覆写得到相同 idx 与 `urgent:{turn}:{idx}`，合成身份不随
        # 被删旧行漂移。不新增 UUID/映射账。
        self.conn.execute(
            "DELETE FROM pending_decisions WHERE turn = ? AND kind = 'rescript_draft'",
            (int(turn),),
        )
        self._insert_rescript_draft_rows(int(turn), drafts)

    def append_rescript_drafts(self, turn: int, drafts: List[Dict[str, object]]) -> None:
        """#657：HITL phase2 续跑追加本回合新票拟，不 DELETE 既有急务行。

        保留 return_revise/decided/跨月 backlog；只在 max(idx)+1 后续插。
        只写 conn 不 commit——与 save_resolve_context 同事务。
        """
        self._insert_rescript_draft_rows(int(turn), drafts)

    def _insert_rescript_draft_rows(
        self, turn: int, drafts: List[Dict[str, object]],
    ) -> None:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(idx) + 1, 0) FROM pending_decisions WHERE turn = ?",
            (int(turn),),
        ).fetchone()
        idx = int(row[0] or 0)
        for d in drafts:
            actor_name = str(d.get("actor_name") or "")
            actor_office = str(d.get("actor_office") or "")
            actor_faction = str(d.get("actor_faction") or "")
            event_id = str(d.get("event_id") or "").strip()
            if not event_id:
                event_id = f"urgent:{int(turn)}:{idx}"
            self.conn.execute(
                """INSERT INTO pending_decisions
                   (turn, idx, event_id, title, context, options_json, choice_json,
                    status, kind, actor_name, actor_office, actor_faction)
                   VALUES (?, ?, ?, ?, ?, ?, '', 'pending', 'rescript_draft', ?, ?, ?)""",
                (
                    int(turn), idx,
                    event_id,
                    str(d.get("title") or ""),
                    str(d.get("context") or ""),
                    json.dumps(d.get("options") or [], ensure_ascii=False),
                    actor_name, actor_office, actor_faction,
                ),
            )
            idx += 1

    def list_rescript_drafts(self) -> List[Dict[str, object]]:
        """#656：全部急务票拟行（kind='rescript_draft'），跨月留存待 #657 批红面消费。

        #657：补 choice / revision_round / prior_options_json 投影（list 面保留）。
        """
        rows = self.conn.execute(
            "SELECT turn, idx, event_id, title, context, options_json, choice_json, status, "
            "actor_name, actor_office, actor_faction, revision_round, prior_options_json "
            "FROM pending_decisions WHERE kind = 'rescript_draft' ORDER BY turn, idx"
        ).fetchall()
        out: List[Dict[str, object]] = []
        for r in rows:
            options, choice, prior = _decision_json_fields(r)
            out.append({
                "turn": int(r["turn"]),
                "idx": int(r["idx"]),
                "event_id": r["event_id"],
                "title": r["title"],
                "context": r["context"],
                "options": options,
                "choice": choice,
                "status": r["status"],
                "actor_name": r["actor_name"],
                "actor_office": r["actor_office"],
                "actor_faction": r["actor_faction"],
                "revision_round": int(r["revision_round"] or 0),
                "prior_options_json": prior,
            })
        return out

    def list_rescript_desk(self, turn: int) -> List[Dict[str, object]]:
        """#657 批红案头唯一合并读出口。

        序：全部 pending 急务（跨月）ORDER BY turn, idx → 本月 pending decision ORDER BY idx。
        投影含 decision_key="{kind}:{source_turn}:{idx}"、options、choice、revision_round、
        status、actor；**不**持久窗 id/集合摘要/窗版本。
        list_rescript_drafts / list_pending_decisions 调用面保留；本方法是批红合并出口。
        """
        turn = int(turn)
        rows = self.conn.execute(
            """
            SELECT turn, idx, event_id, title, context, rejection_reason, opposition,
                   options_json, choice_json, status, kind,
                   actor_name, actor_office, actor_faction,
                   revision_round, prior_options_json
            FROM pending_decisions
            WHERE status = 'pending'
              AND (
                    kind = 'rescript_draft'
                    OR (kind = 'decision' AND turn = ?)
                  )
            ORDER BY
              CASE kind WHEN 'rescript_draft' THEN 0 ELSE 1 END,
              turn, idx
            """,
            (turn,),
        ).fetchall()
        return [self._project_rescript_desk_row(r) for r in rows]

    def _project_rescript_desk_row(self, r: Any) -> Dict[str, object]:
        """pending_decisions 行 → desk 投影（pending/decided 共用）。"""
        kind = str(r["kind"] or "decision")
        source_turn = int(r["turn"])
        idx = int(r["idx"])
        options, choice, prior = _decision_json_fields(r)
        return {
            "decision_key": f"{kind}:{source_turn}:{idx}",
            "kind": kind,
            "source_turn": source_turn,
            "turn": source_turn,
            "idx": idx,
            "event_id": r["event_id"],
            "title": r["title"],
            "context": r["context"],
            "rejection_reason": r["rejection_reason"] if "rejection_reason" in r.keys() else "",
            "opposition": r["opposition"] if "opposition" in r.keys() else "",
            "options": options,
            "choice": choice,
            "status": r["status"],
            "actor_name": r["actor_name"],
            "actor_office": r["actor_office"],
            "actor_faction": r["actor_faction"],
            "revision_round": int(r["revision_round"] or 0),
            "prior_options_json": prior,
        }

    def get_rescript_desk_rows_by_keys(
        self, keys: Sequence[str],
    ) -> List[Dict[str, object]]:
        """按 decision_key 取 desk 行（含 decided）——C1.1 崩溃重入 already_applied 用。"""
        out: List[Dict[str, object]] = []
        seen: set[str] = set()
        for raw in keys:
            key = str(raw or "").strip()
            if not key or key in seen:
                continue
            parts = key.split(":")
            if len(parts) != 3:
                continue
            kind, turn_s, idx_s = parts
            try:
                turn_i, idx_i = int(turn_s), int(idx_s)
            except (TypeError, ValueError):
                continue
            if kind not in {"rescript_draft", "decision"}:
                continue
            r = self.conn.execute(
                """
                SELECT turn, idx, event_id, title, context, rejection_reason, opposition,
                       options_json, choice_json, status, kind,
                       actor_name, actor_office, actor_faction,
                       revision_round, prior_options_json
                FROM pending_decisions
                WHERE turn = ? AND idx = ? AND kind = ?
                """,
                (turn_i, idx_i, kind),
            ).fetchone()
            if r is None:
                continue
            seen.add(key)
            out.append(self._project_rescript_desk_row(r))
        return out

    # ── 动作闸门：结构化聊天写动作暂存(ADR 0006) ──────────────────────────
    def _latest_held_user_chat_message_id(
        self, minister_name: str, turn: Optional[int] = None,
    ) -> Optional[int]:
        """Latest still-held user chat row for oral-decree pin (#976).

        * ``turn`` set (stage path): only that turn — stage-time pin of the
          utterance just spoken, so later confirmation user lines cannot steal.
        * ``turn`` omitted (classification auto-capture): any still-held user
          for this minister (covers F4 / zero-overlap cross-turn: hold at T,
          create at T+N without settle).
        """
        name = str(minister_name or "").strip()
        if not name:
            return None
        try:
            return self.chat_messages.latest_held_user_id(name, None if turn is None else int(turn))
        except sqlite3.OperationalError:
            return None

    def _parse_origin_chat_message_id(
        self, payload: Optional[Mapping[str, object]],
    ) -> Optional[int]:
        """Coerce pending/API ``origin_chat_message_id`` to a positive int pin."""
        if not payload:
            return None
        raw = payload.get("origin_chat_message_id")
        if raw is None:
            return None
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            return None
        return mid if mid > 0 else None

    def attach_secret_oral_pin(
        self,
        minister_name: str,
        turn: int,
        payload: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        """Pin latest held user for production non-create **更新** (#976).

        ``stage_pending_action`` only auto-pins 新建.  Non-create pure-public
        must not invent bloodline (催办/记进展/提交核议 leave pin unset).
        Callers that rewrite order body (extract「更新」) attach pin so the oral
        decree withholds and never settle-releases into shared
        character_knowledge_sources.
        """
        out: Dict[str, object] = dict(payload or {})
        if self._parse_origin_chat_message_id(out) is not None:
            return out
        mid = self._latest_held_user_chat_message_id(minister_name, int(turn))
        if mid is not None:
            out["origin_chat_message_id"] = int(mid)
        return out

    def _resolve_secret_oral_pins(
        self,
        state: GameState,
        *,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        origin_minister_name: Optional[str] = None,
        assignee_name: Optional[str] = None,
    ) -> List[int]:
        """Resolve oral-decree chat pins for secret-order classification (#976).

        Prefer explicit stage/API pins.  Auto-capture latest held user only when
        the caller provided **no** pin intent (both args None) — direct create
        without pending still withholds the oral line.  Explicit empty
        ``origin_chat_message_ids=[]`` means pin-mode with no new oral (do not
        invent pure-public bloodline).
        """
        has_explicit_pin_intent = (
            origin_chat_message_ids is not None or origin_chat_message_id is not None
        )
        explicit: List[object] = []
        if origin_chat_message_ids is not None:
            explicit.extend(origin_chat_message_ids)
        if origin_chat_message_id is not None:
            explicit.append(origin_chat_message_id)
        pinned_ids = self._coerce_positive_message_ids(explicit)
        if not pinned_ids and not has_explicit_pin_intent:
            # Auto-capture: any still-held user bloodline (cross-turn F4 included).
            # Prefer same-turn first so pure-public earlier-turn held is not
            # stolen when a fresh same-turn oral exists.
            for name in dict.fromkeys(
                n for n in (
                    str(origin_minister_name or "").strip(),
                    str(assignee_name or "").strip(),
                ) if n
            ):
                mid = self._latest_held_user_chat_message_id(name, int(state.turn))
                if mid is None:
                    mid = self._latest_held_user_chat_message_id(name)
                if mid is not None and mid not in pinned_ids:
                    pinned_ids.append(mid)
        return pinned_ids

    def _brief_origin_chat_message_ids(self, order_id: int) -> List[int]:
        """Durable oral pins already registered on this order's brief (may be empty)."""
        rows = self.character_knowledge.secret_brief_pins(int(order_id))
        if not rows:
            return []
        parsed = load_stored_list(rows[0]["origin_chat_message_ids"], label="origin_chat_message_ids")
        from ming_sim.strict_types import strict_int

        pins = [strict_int(pin) for pin in parsed]
        if any(pin <= 0 for pin in pins):
            raise ValueError("origin_chat_message_ids 必须为正整数")
        return list(dict.fromkeys(pins))

    def _classify_secret_order_audience(
        self,
        state: GameState,
        order_id: int,
        minister_name: str,
        title: str,
        body: str,
        *,
        origin_minister_name: Optional[str] = None,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        commit: bool = True,
    ) -> None:
        """Brief upsert + pin-mode oral withhold/release (create and non-create isomorphic)."""
        pins = self._resolve_secret_oral_pins(
            state,
            origin_chat_message_id=origin_chat_message_id,
            origin_chat_message_ids=origin_chat_message_ids,
            origin_minister_name=origin_minister_name,
            assignee_name=minister_name,
        )
        self.upsert_secret_order_brief(
            state, int(order_id), minister_name, title, body,
            origin_minister_name=origin_minister_name,
            origin_chat_message_ids=pins,
            commit=commit,
        )

    def _current_open_night_id(self) -> int:
        """当前开着（open/closing）的召对夜 id；无夜或旧档无表返回 0（#498）。"""
        try:
            row = self.conn.execute(
                "SELECT id FROM audience_nights "
                "WHERE status IN ('open', 'closing') ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["id"]) if row is not None else 0

    # ── #571 旨意案卷公共接口 ──────────────────────────────────────

    # #1889 / ADR 0151：status/迁移/关口/执行格四组闭集与 row codec 归案卷 store
    # （ming_sim.entities.dossier），此处不再留第二份。
    _DOSSIER_ACTION_TYPES = DOSSIER_ACTION_TYPES
    def _directive_dossier_action_type(cls, payload: Dict[str, object]) -> str:
        explicit = str(payload.get("dossier_action_type") or "").strip()
        if not explicit:
            raise ValueError("旨意缺少明确 action_type")
        if explicit not in DIRECTIVE_ACTION_TYPES:
            raise ValueError(f"旨意 action_type 非法：{explicit}")
        return explicit

    @staticmethod
    def _directive_executor(
        action_type: str, payload: Dict[str, object],
    ) -> Tuple[str, object]:
        if action_type not in {"assignment", "military_order", "authorization"}:
            return "", ""
        return (
            "character",
            payload.get("assignee_id")
            or payload.get("assignee")
            or payload.get("holder_id")
            or "",
        )

    def _normalize_directive_dossier_payload(
        self, payload: Dict[str, object], *, content=None, current_turn: int = 0,
    ) -> Dict[str, object]:
        """机械旨意的唯一结构边界；不完整载荷响亮拒绝。"""
        # #658：纯御笔强推不经 ordinary triad 归一（prepare/commit/ensure 共吃）。
        # text/actor 等会话字段须保留——pending payload 以它们为成案正文真源。
        if classify_directive_structured_kind(payload) == "push":
            push_id = imperial_push_target_dossier_id(payload)
            assert push_id is not None
            mode = normalize_dossier_mode(
                payload["mode"] if "mode" in payload else "ordinary"
            )
            out: Dict[str, object] = {
                "target_dossier_id": int(push_id), "mode": mode,
            }
            for key in ("text", "actor", "source_chat_turn_id"):
                if payload.get(key) not in (None, ""):
                    out[key] = payload[key]
            return out
        normalized = dict(payload)
        normalized["mode"] = normalize_dossier_mode(
            normalized["mode"] if "mode" in normalized else "ordinary"
        )
        action = str(normalized.get("dossier_action_type") or "").strip()
        if action == "grant_allocation":
            grant_action = str(normalized.get("grant_action") or "").strip()
            if grant_action in {"加衔", "荫叙"}:
                normalized.pop("delta", None)
            elif self._is_army_pay_grant_payload(normalized):
                # #1503：协饷先且只经 require_explicit_xiexang_fields，不经 amount/account 首错。
                normalized = self._normalize_army_pay_grant_payload(normalized)
            else:
                from ming_sim.action_clusters import field_population_allowed
                from ming_sim.action_materialize import require_grant_allocation_shape
                purpose = str(normalized.get("purpose") or "").strip()
                if purpose and not field_population_allowed(
                    "grant_allocation", "purpose", normalized,
                ):
                    raise ValueError(f"非协饷拨帑不得夹带 purpose={purpose}")
                # #1716：amount/account 唯一验形；分类默认 grant_action=「无」时只借金钱动作过 shape，不回写。
                # 普通/legacy fallback（缺/空 grant_action）须显式非空 account，禁默认国库。
                shape_ga = grant_action if grant_action not in {"", "无"} else "赏赉"
                if grant_action in {"", "无"}:
                    account_raw = normalized.get("account")
                    if account_raw is None or not str(account_raw).strip():
                        raise ValueError("拨帑旨意缺少 account")
                shaped = require_grant_allocation_shape(
                    grant_action=shape_ga,
                    amount=normalized.get("amount"),
                    account=normalized.get("account"),
                )
                normalized["amount"] = int(shaped["amount"])
                normalized["account"] = str(shaped["account"])
                surface = str(
                    normalized.get("execution_surface") or "in_transit"
                ).strip()
                if surface not in {"immediate", "in_transit"}:
                    raise ValueError("拨帑旨意 execution_surface 非法")
                normalized["execution_surface"] = surface
                normalized.pop("delta", None)
        elif action == "pay_order_override":
            # #653：结构化载荷 presence 在指令归一边界先验（键形/值域/幻影 region
            # 仍由成案点与物化点共 prepare_pay_order_entries 同一验形，不在此重复）。
            entries = normalized.get("entries")
            if not isinstance(entries, list) or not entries:
                raise ValueError("pay_order_override 旨意缺少 entries 结构化载荷")
        elif action in {
            "assignment", "authorization", "secret_authorization", "military_order",
        }:
            assignee = str(
                normalized.get("assignee_id")
                or normalized.get("assignee")
                or normalized.get("holder_id")
                or ""
            ).strip()
            if assignee and content is not None:
                from ming_sim.session import _find_existing_minister
                assignee = _find_existing_minister(content, assignee, self) or ""
            if not assignee and action in {"authorization", "secret_authorization"}:
                raise ValueError(f"{action} 旨意缺少 canonical assignee")
            if assignee:
                normalized["assignee_id"] = assignee
            else:
                normalized.pop("assignee_id", None)
            normalized.pop("assignee", None)
            # Authorization identity and applicability live exclusively in
            # authority_records; legacy dossier payload ids are not retained.
            normalized.pop("authorization_id", None)
            normalized.pop("authorization_ids", None)
        if action == "authorization":
            # #528 / #611：公开委任生产项必带 privilege + 典范 scope；授予判后走 authority_changes。
            from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET

            priv = str(normalized.get("privilege") or "").strip()
            if priv in {"", "无"}:
                priv = "便宜行事"
            if priv not in AUTHORITY_PRIVILEGE_SET:
                raise ValueError("委任授权 privilege 非法")
            normalized["privilege"] = priv
            scope = str(normalized.get("scope") or "").strip()
            if not scope or ":" not in scope:
                t_kind = str(normalized.get("target_kind") or "").strip()
                t_id = str(normalized.get("target_id") or "").strip()
                if t_id and ":" in t_id and not t_kind:
                    scope = t_id
                elif t_kind and t_id:
                    scope = f"{t_kind}:{t_id}"
            kind, separator, target = scope.partition(":")
            if not separator or not kind.strip() or not target.strip():
                raise ValueError("委任授权缺少典范 scope")
            normalized["scope"] = f"{kind.strip()}:{target.strip()}"
            normalized["target_kind"] = kind.strip()
            normalized["target_id"] = target.strip()
            holder = str(
                normalized.get("holder_id")
                or normalized.get("assignee_id")
                or normalized.get("name")
                or ""
            ).strip()
            if not holder:
                raise ValueError("委任授权缺少 holder_id")
            normalized["holder_id"] = holder
            normalized["name"] = holder
            normalized["assignee_id"] = holder
        if action == "revoke_authority":
            # #523 / #611：收权生产项必带现存 authority_records.id；不得从 payload 拼 id。
            try:
                aid = strict_int(
                    normalized.get("authority_id"), accept_numeric_strings=True,
                )
            except (TypeError, ValueError):
                aid = 0
            if aid <= 0:
                raise ValueError("收权旨意缺少 authority_id")
            normalized["authority_id"] = aid
            holder = str(
                normalized.get("holder_id")
                or normalized.get("name")
                or normalized.get("target_id")
                or ""
            ).strip()
            if holder:
                normalized["holder_id"] = holder
                normalized["name"] = holder
                normalized["target_kind"] = "character"
                normalized["target_id"] = holder
            try:
                grant_did = strict_int(
                    normalized.get("grant_dossier_id"), accept_numeric_strings=True,
                )
            except (TypeError, ValueError):
                grant_did = 0
            if grant_did > 0:
                normalized["grant_dossier_id"] = grant_did
            # 身份真源在 authority_records；禁保留并行 authorization_id(s)
            normalized.pop("authorization_id", None)
            normalized.pop("authorization_ids", None)
        if action == "revoke_decree":
            # #523：目标仅承诺/旨意；纯授权不得入撤回成命。
            raw_target = str(normalized.get("target_id") or "").strip()
            if raw_target.startswith("authority:"):
                raise ValueError("撤回成命目标不得为纯授权")
            revoke_did = 0
            revoke_iid = 0
            try:
                revoke_did = strict_int(
                    normalized.get("revoke_target_dossier_id"),
                    accept_numeric_strings=True,
                )
            except (TypeError, ValueError):
                revoke_did = 0
            try:
                revoke_iid = strict_int(
                    normalized.get("revoke_target_issue_id"),
                    accept_numeric_strings=True,
                )
            except (TypeError, ValueError):
                revoke_iid = 0
            if revoke_did <= 0 and revoke_iid <= 0:
                kind = str(normalized.get("target_kind") or "").strip()
                raw = raw_target
                if raw.startswith("dossier:"):
                    kind = "dossier"
                    raw = raw.split(":", 1)[1].strip()
                elif raw.startswith("issue:"):
                    kind = "issue"
                    raw = raw.split(":", 1)[1].strip()
                try:
                    tid = strict_int(raw, accept_numeric_strings=True) if raw else 0
                except (TypeError, ValueError):
                    tid = 0
                if tid <= 0:
                    raise ValueError("撤回成命缺少目标成命标识")
                if kind == "issue":
                    revoke_iid = tid
                else:
                    revoke_did = tid
                    kind = kind or "dossier"
                normalized["target_kind"] = kind or "dossier"
                normalized["target_id"] = str(tid)
            if revoke_did > 0:
                normalized["revoke_target_dossier_id"] = revoke_did
            if revoke_iid > 0:
                normalized["revoke_target_issue_id"] = revoke_iid
        if action == "punishment":
            # #517：与 grant_allocation / military_order 一致——合法非空动作在 admission 强制。
            # 枚举唯一真源 = ACTION_CLUSTERS punishment FieldSpec（经 punish_actions_effective）。
            from ming_sim.action_materialize import (
                issue_dispositions_allowed,
                punish_actions_effective,
            )
            punish_action = str(normalized.get("punish_action") or "").strip()
            issue_disposition = str(normalized.get("issue_disposition") or "").strip()
            if (
                not punish_action
                or (
                    punish_action not in punish_actions_effective()
                    and issue_disposition not in issue_dispositions_allowed()
                )
            ):
                raise ValueError(
                    f"惩处旨意 punish_action 非法或缺失：{punish_action or '(空)'}"
                )
            if issue_disposition == "办人" and punish_action != "拿问下狱":
                raise ValueError("弹劾潮办人须使用 canonical 拿问下狱动作")
            if issue_disposition == "压下" and punish_action != "无":
                raise ValueError("弹劾潮压下须使用 canonical 无动作")
            normalized["punish_action"] = punish_action
            # #517 r2：罚俸须正数 amount，成案前响亮拒绝（不得归零暂存后判后才炸）。
            if punish_action == "罚俸":
                try:
                    amount = strict_int(
                        normalized.get("amount"), accept_numeric_strings=False,
                    )
                except ValueError:
                    amount = 0
                if amount <= 0:
                    raise ValueError("罚俸旨意缺少正数 amount")
                normalized["amount"] = amount
        if action == "military_order":
            # #521 r1：仅限期出战（无 station 调驻面）强制未来 due_turn；
            # 调驻/移镇可无期限成案。显式期限字段若出现仍须落成未来 due。
            try:
                raw_due_turn = normalized.get("due_turn")
                raw_deadline = normalized.get("deadline_months")
                due_turn = strict_int(
                    raw_due_turn, accept_numeric_strings=False
                ) if raw_due_turn is not None else 0
                deadline = strict_int(
                    raw_deadline, accept_numeric_strings=False
                ) if raw_deadline is not None else 0
            except ValueError:
                due_turn = deadline = 0
            if due_turn <= 0 and deadline > 0 and current_turn > 0:
                due_turn = int(current_turn) + deadline
            station = str(normalized.get("station") or "").strip()
            has_deadline_intent = due_turn > 0 or deadline > 0
            requires_due = not station  # 限期出战：无调驻面，due 为限期载体
            if due_turn > int(current_turn or 0):
                normalized["due_turn"] = due_turn
                normalized.pop("deadline_months", None)
            elif requires_due or has_deadline_intent:
                raise ValueError("军令缺少有效未来 due_turn/deadline_months")
            else:
                # 无期限调驻/移镇：不写虚假 due
                normalized.pop("due_turn", None)
                normalized.pop("deadline_months", None)
        if action == "referral":
            # #524：下议=移交程序；必带未来 end_turn 与非空机关/职司列表。
            # 禁个人 owner/assignee（与交办互斥）——非空即 fail-loud，禁静默 pop。
            from ming_sim.action_materialize import (
                assert_responsible_bodies_org_only,
                character_person_names,
                parse_responsible_bodies,
            )
            for banned in ("owner", "assignee", "assignee_id"):
                if str(normalized.get(banned) or "").strip():
                    raise ValueError(f"下议旨意不得携带 {banned}")
            cleaned = parse_responsible_bodies(normalized.get("responsible_bodies"))
            if not cleaned:
                raise ValueError("下议旨意缺少 responsible_bodies")
            assert_responsible_bodies_org_only(
                cleaned,
                known_person_names=character_person_names(self),
                current_minister=str(
                    normalized.get("actor") or normalized.get("minister_name") or ""
                ),
            )
            normalized["responsible_bodies"] = cleaned
            try:
                end_turn = strict_int(
                    normalized.get("end_turn"), accept_numeric_strings=True,
                )
            except (TypeError, ValueError):
                end_turn = 0
            if end_turn <= 0 and current_turn > 0:
                try:
                    months = strict_int(
                        normalized.get("deadline_months"),
                        accept_numeric_strings=True,
                    )
                except (TypeError, ValueError):
                    months = 0
                if months > 0:
                    end_turn = int(current_turn) + months
            if end_turn <= int(current_turn or 0):
                raise ValueError("下议缺少有效未来 end_turn/deadline_months")
            normalized["end_turn"] = end_turn
            normalized.pop("deadline_months", None)
        target_kind = str(normalized.get("target_kind") or "").strip()
        target_id = str(normalized.get("target_id") or "").strip()
        if target_id in {"narrative", "policy"}:
            target_id = ""
        if target_kind == "character" and target_id and content is not None:
            if action == "pacification":
                target_id = self._find_pacification_target(content, target_id) or ""
            else:
                from ming_sim.session import _find_existing_minister
                target_id = _find_existing_minister(content, target_id, self) or ""
        if target_id:
            normalized["target_id"] = target_id
        else:
            normalized.pop("target_id", None)
            raise ValueError("旨意缺少 canonical target")
        if action == "military_order":
            # #521 r2：成案前验 target_kind=army 且军队存在（含无 station 催战）。
            # 不得静默改写错误 target_kind；不得等到判后才发现虚假 id。
            if target_kind != "army":
                raise ValueError("军令 target_kind 须为 army")
            existing_army = ArmyStore(self.conn).read_apply_military_order_station_effect((target_id,))
            if existing_army is None:
                raise ValueError(
                    f"军令引用未入库军队 '{target_id}'（成案前须存在）"
                )
            normalized["target_kind"] = "army"
        # #654 / owner A：locality_scope 三值 durable 归一；八值 target_kind 闭集直校验
        # （含结构目标 dossier）。region 缺省不暗升 single。
        from ming_sim.decree_vocabulary import TARGET_KINDS
        from ming_sim.execution_pressure import normalize_locality_scope
        final_kind = str(normalized.get("target_kind") or "").strip()
        if final_kind not in TARGET_KINDS:
            raise ValueError(f"target_kind 非法：{final_kind!r}")
        normalized["target_kind"] = final_kind
        normalized["locality_scope"] = normalize_locality_scope(
            normalized.get("locality_scope"),
        )
        return normalized

    def _find_pacification_target(self, content, name: str) -> Optional[str]:
        """Resolve living canonical 内乱 leader still needing 自新受抚 (敌对/潜伏 only)."""
        matched = None
        if name in content.characters:
            matched = name
        else:
            matched = next((
                key for key, character in content.characters.items()
                if name in (character.aliases or [])
            ), None)
        if not matched:
            return None
        row = CharacterStore(self.conn).read_find_pacification_target((matched,))
        if row is None or row["status"] != "active" or row["power_id"] in (None, "ming"):
            return None
        power = PowerStore(self.conn).read_find_pacification_target((row["power_id"],))
        if power is None or not (
            power["kind"] == "内乱"
            and power["stance"] in {"敌对", "潜伏"}
            and power["leader"] == matched
        ):
            return None
        return matched

    def _commit_dossier_write(self, commit: bool, owns: bool) -> None:
        """Commit only when the caller snapshotted ownership before its first DML."""
        if commit and owns:
            self.conn.commit()

    @classmethod
    def _normalize_dossier_report_origin(
        cls, origin: object, *, is_terminal: bool = False,
    ) -> str:
        raw = str(origin or "").strip()
        if not raw:
            return (
                DOSSIER_REPORT_ORIGIN_VERDICT
                if is_terminal
                else DOSSIER_REPORT_ORIGIN_MONTHLY
            )
        prefix = DOSSIER_REPORT_ORIGIN_NS
        if not raw.startswith(prefix) or not raw[len(prefix):].strip():
            raise ValueError("奏报 origin 须带 dossier-report 命名空间前缀")
        return raw

    @classmethod
    def _coerce_dossier_progress_row(
        cls, item: Mapping[str, object], *, dossier_id: int,
    ) -> Dict[str, object]:
        is_terminal = bool(item.get("is_terminal"))
        # Empty origin defaults live only in _normalize_dossier_report_origin.
        origin = cls._normalize_dossier_report_origin(
            item.get("origin"), is_terminal=is_terminal,
        )
        return {
            "id": int(item["id"]),
            "dossier_id": int(item.get("dossier_id") or dossier_id),
            "turn": int(item["turn"]),
            "progress_band": str(item["progress_band"]),
            "memorial_text": str(item["memorial_text"]),
            "is_terminal": is_terminal,
            "origin": origin,
        }

    def _record_secret_dossier_progress(
        self,
        dossier_id: int,
        order_id: int,
        turn: int,
        band: str,
        text: str,
        *,
        is_terminal: bool,
        origin: str,
        commit: bool,
    ) -> int:
        owns = self.owns_transaction()
        row = CharacterKnowledgeStore(self.conn).read_record_secret_dossier_progress((order_id,))
        if row is None:
            raise ValueError("密令不存在")
        reports = load_stored_list(row["dossier_progress_json"], label='dossier_progress_json')
        existing = next((item for item in reports if not item.get("is_terminal")
                         and int(item.get("turn", 0)) == int(turn)), None)
        if existing is None or is_terminal:
            report_id = max((int(item.get("id", 0)) for item in reports), default=0) + 1
            existing = {
                "id": report_id, "dossier_id": int(dossier_id), "turn": int(turn),
                "progress_band": band, "memorial_text": text,
                "is_terminal": bool(is_terminal), "origin": origin,
            }
            reports.append(existing)
        else:
            report_id = int(existing["id"])
            existing.update(
                progress_band=band, memorial_text=text, origin=origin,
            )
        reports.sort(key=lambda item: (int(item["turn"]), int(item["id"])))
        CharacterKnowledgeStore(self.conn).write_record_secret_dossier_progress((json.dumps(reports, ensure_ascii=False), order_id))
        self._commit_dossier_write(commit, owns)
        return report_id

    def record_dossier_progress(
        self,
        dossier_id: int,
        turn: int,
        progress_band: str,
        memorial_text: str,
        *,
        is_terminal: bool = False,
        origin: str = "",
        commit: bool = True,
    ) -> int:
        """Append one reported-progress entry; write path splits by physical track.

        Secret-order dossiers stay on secret_orders.dossier_progress_json (#566).
        Non-secret execution-surface dossiers use dossier_reported_progress (#619).
        Reported rows never enter apply (ADR 0073).
        """
        owns = self.owns_transaction()
        dossier = self.dossiers.get(int(dossier_id))
        band = str(progress_band or "").strip()
        text = str(memorial_text or "").strip()
        if dossier is None:
            raise ValueError("案卷不存在")
        if not band or not text:
            raise ValueError("进展档和密奏均不能为空")
        origin_norm = self._normalize_dossier_report_origin(
            origin, is_terminal=bool(is_terminal),
        )
        secret_order_id = dossier.get("secret_order_id")
        if secret_order_id:
            return self._record_secret_dossier_progress(
                int(dossier_id), int(secret_order_id), int(turn), band, text,
                is_terminal=bool(is_terminal), origin=origin_norm, commit=commit,
            )
        # dossiers.get 已按 hydrate_dossier_row 解析并 fail-loud 校验过 payload，直接复用，
        # 不在此对同一载荷二次解析或静默回退空对象。
        if not has_execution_surface(dossier.get("action_type"), dossier["payload"]):
            raise ValueError("非执行面案卷不可挂奏报")
        report_id = self.dossiers.upsert_reported_progress(
            int(dossier_id), int(turn), band=band, text=text, origin=origin_norm,
            is_terminal=bool(is_terminal),
        )
        self._commit_dossier_write(commit, owns)
        return report_id

    def list_dossier_progress(self, dossier_id: int) -> List[Dict[str, object]]:
        """Unified read seam over secret private rail and general reported rail."""
        dossier = self.dossiers.get(int(dossier_id))
        if dossier is None:
            return []
        if dossier.get("secret_order_id"):
            row = CharacterKnowledgeStore(self.conn).read_record_secret_dossier_progress((int(dossier["secret_order_id"]),))
            if row is None:
                return []
            return [
                self._coerce_dossier_progress_row(item, dossier_id=int(dossier_id))
                for item in load_stored_list(row["dossier_progress_json"], label='dossier_progress_json')
            ]
        return [
            self._coerce_dossier_progress_row(dict(row), dossier_id=int(dossier_id))
            for row in self.dossiers.reported_progress_rows(int(dossier_id))
        ]

    def _audit_fork_signals_for_source(self, source_dossier_id: int) -> List[Dict[str, object]]:
        """#622：稽核链在场时，月报输入面确定性携带被稽核案卷分叉信号。

        读端复用 store.links（relation_type=稽核）；无链则返回空——调用方不挂键。
        信号=奏报 progress_band 面 vs 执行格/实况 origin 面，供 extractor 读，不进密奏正文断言。
        """
        signals: List[Dict[str, object]] = []
        for link in self.dossiers.links(int(source_dossier_id), direction="outgoing"):
            if str(link.get("relation_type") or "").strip() != "稽核":
                continue
            target_id = int(link["target_dossier_id"])
            # #627：fork 判据单源（supervision.is_reported_actual_fork）；本读端只经 read_dossier_fork_state 装配。
            fork_state = self.read_dossier_fork_state(target_id)
            signals.append({
                "target_dossier_id": target_id,
                "relation_type": "稽核",
                "reported_bands": fork_state["reported_bands"],
                "execution_outcome": fork_state["execution_outcome"],
                "actual_effect_count": fork_state["actual_effect_count"],
                "beyond_intent": fork_state["beyond_intent"],
                "fork": fork_state["fork"],
            })
        return signals

    def read_dossier_fork_state(self, dossier_id: int) -> Dict[str, object]:
        """#627 public 读端：装配奏报/执行格/旨外输入，fork 谓词单源共调。"""
        from ming_sim.supervision import is_reported_actual_fork

        target = self.dossiers.get(int(dossier_id))
        reports = self.list_dossier_progress(int(dossier_id))
        reported_bands = [
            str(item.get("progress_band") or "").strip()
            for item in reports
            if str(item.get("progress_band") or "").strip()
        ]
        execution_outcome = (
            str(target.get("execution_outcome") or "").strip() if target else ""
        )
        # #1260：durable_effects / beyond 单源助手（economy+fiscal），禁再只扫 economy。
        # #1272：beyond 直接读已取的 durable，禁再调 dossier_has_beyond_intent 重扫 4 表。
        durable = self.list_dossier_durable_effects(int(dossier_id))
        actual_effect_count = len(durable)
        beyond = any(bool(row.get("beyond_intent")) for row in durable)
        fork = is_reported_actual_fork(
            reported_bands=reported_bands,
            beyond_intent=beyond,
            execution_outcome=execution_outcome,
        )
        return {
            "dossier_id": int(dossier_id),
            "reported_bands": reported_bands,
            "execution_outcome": execution_outcome,
            "actual_effect_count": int(actual_effect_count),
            "beyond_intent": bool(beyond),
            "fork": bool(fork),
        }

    def list_monthly_dossier_progress_nudges(self, turn: int | None = None) -> List[Dict[str, object]]:
        """#1504 / 0058：列出在办且关联密令 active 的案卷月报候选。

        在办状态为 promulgated/executing；不以 deadline/tag/发令月收缩候选，
        缺项由 record 侧完整覆盖失败。
        """
        _ = turn  # 签名保留；0058 候选不按结算回合收缩
        rows = self.dossiers.active_secret_order_dossiers()
        out: List[Dict[str, object]] = []
        for row in rows:
            dossier_id = int(row["id"])
            payload = load_stored_object(row["payload_json"], label="payload_json")
            item: Dict[str, object] = {
                "dossier_id": dossier_id,
                "secret_order_id": int(row["secret_order_id"]),
                "title": payload.get("title", ""),
                "progress": self.list_dossier_progress(dossier_id),
            }
            # #622 AC5：仅当稽核链在场时挂分叉信号键；无链则键不出现。
            fork_signals = self._audit_fork_signals_for_source(dossier_id)
            if fork_signals:
                item["audit_fork_signals"] = fork_signals
            out.append(item)
        return out

    def record_monthly_dossier_progress(
        self, turn: int, generated: object = None,
    ) -> List[Dict[str, object]]:
        """Persist one valid extractor-authored brief for every eligible dossier."""
        candidates = {
            int(item["dossier_id"]): item
            for item in self.list_monthly_dossier_progress_nudges(int(turn))
        }
        if not candidates:
            if generated is None or generated == []:
                return []
            raise ValueError("无合资格长差案卷却收到本月密奏")
        if generated is None or generated == []:
            raise ValueError("合资格长差案卷缺少本月密奏")
        if not isinstance(generated, list):
            raise ValueError("合资格长差案卷缺少本月密奏")
        supplied: Dict[int, Dict[str, object]] = {}
        for item in generated:
            if not isinstance(item, dict):
                raise ValueError("长差月报格式无效")
            try:
                dossier_id = strict_int(item.get("dossier_id", 0))
                if dossier_id <= 0:
                    raise ValueError("not positive")
            except (TypeError, ValueError) as exc:
                raise ValueError("长差月报案卷编号无效") from exc
            band = str(item.get("progress_band") or "").strip()
            text = str(item.get("memorial_text") or "").strip()
            if dossier_id not in candidates or dossier_id in supplied or not band or not text:
                raise ValueError("长差月报存在未知、重复或空白条目")
            supplied[dossier_id] = item
        if set(supplied) != set(candidates):
            raise ValueError("合资格长差案卷月报未完整覆盖")

        reports: List[Dict[str, object]] = []
        for dossier_id, item in supplied.items():
            # #625：有在场稽核时 origin 带同派/私货结构化标记（扩 origin，不加列）。
            origin = self.compose_supervision_report_origin(int(dossier_id), int(turn))
            self.record_dossier_progress(
                dossier_id, int(turn), str(item["progress_band"]).strip(),
                str(item["memorial_text"]).strip(),
                origin=origin,
                commit=False,
            )
            reports.append(self.list_dossier_progress(dossier_id)[-1])
        return reports

    def _grant_escort_presence(
        self, dossier_id: int,
    ) -> Tuple[bool, Optional[int], str]:
        """被护案卷侧查入链：护卫/稽核在场与否（0054 逐路独立）。"""
        for link in self.dossiers.links(int(dossier_id), direction="incoming"):
            relation = str(link.get("relation_type") or "").strip()
            if relation in _GRANT_ESCORT_RELATIONS:
                return True, int(link["source_dossier_id"]), relation
        return False, None, ""

    def list_monthly_grant_reconciliation_targets(self) -> List[Dict[str, object]]:
        """扫描面：executing 且仍在途的拨帑案卷（排除成案不足额已 failed+close）。"""
        rows = self.dossiers.in_transit_grants()
        targets: List[Dict[str, object]] = []
        for row in rows:
            payload = load_stored_object(row["payload_json"], label="payload_json")
            policy = dossier_action_policy("grant_allocation", payload)
            if policy.get("execution_surface") != "in_transit":
                continue
            if self._grant_allocation_is_monthly(payload):
                continue
            if self._grant_allocation_is_honorific(payload):
                continue
            try:
                ordered = int(payload.get("amount") or 0)
            except (TypeError, ValueError):
                ordered = 0
            if ordered <= 0:
                continue
            dossier_id = int(row["id"])
            escorted, source_id, relation = self._grant_escort_presence(dossier_id)
            targets.append({
                "dossier_id": dossier_id,
                "ordered_amount": ordered,
                "escorted": escorted,
                "escort_source_dossier_id": source_id,
                "relation_type": relation,
                "decree_text": str(row["decree_text"] or ""),
                "target_id": str(row["target_id"] or ""),
            })
        return targets

    def list_open_grant_reconciliations(self) -> List[Dict[str, object]]:
        """在途拨帑的最新对账快照，供 issues 软判读账打折。"""
        snapshots: List[Dict[str, object]] = []
        for target in self.list_monthly_grant_reconciliation_targets():
            history = self.dossiers.reconciliations(int(target["dossier_id"]))
            if history:
                latest = dict(history[-1])
            else:
                latest = {
                    "dossier_id": int(target["dossier_id"]),
                    "turn": 0,
                    "ordered_amount": int(target["ordered_amount"]),
                    "arrived_amount": None,
                    "loss_amount": None,
                    "escorted": bool(target["escorted"]),
                    "escort_source_dossier_id": target["escort_source_dossier_id"],
                    "relation_type": str(target["relation_type"] or ""),
                }
            latest["decree_text"] = target["decree_text"]
            latest["target_id"] = target["target_id"]
            snapshots.append(latest)
        return snapshots

    def record_monthly_grant_reconciliations(
        self, turn: int, generated: object = None, *,
        rejection_collector=None,
        source: object = None,
    ) -> List[Dict[str, object]]:
        """月度节拍：逐路软判实抵 → clamp → 落被护侧对账记录。

        无提案时用护行口径中位（无护行亦可机械落账，供 S10 结案合并）。
        不写 0058 进展、不二次扣库、不改原 economy_move。

        #1745 / ADR 0015-D6/D7：域级坏项逐项拒收；形状（非 list/非 dict 项）归
        sanitize_delta_shape 独家，本方法不平行净化。好项与未提案目标的中位落账
        仍在同一 atomic。拒收归属外层 RejectionCollector（flush/commit/mirror/
        rollback 由 settle 编排所有者负责；本方法不自建 collector）。
        """
        from ming_sim.applier import Provenance, RejectedItem

        targets = {
            int(item["dossier_id"]): item
            for item in self.list_monthly_grant_reconciliation_targets()
        }
        if generated is None:
            generated = []
        if not targets and generated in (None, []):
            return []

        # source 走 collector 归一；None 取 typed 默认 unknown（0008-D5）。
        if source is None:
            source = Provenance.unknown

        def _reject(raw_item: object, reason: str, category: str) -> None:
            # 无外层归属不得无痕继续（0150-D2/D3；#1745 删自有 collector 旁路）。
            if rejection_collector is None:
                from ming_sim.applier import RejectionCollectorRequired
                raise RejectionCollectorRequired(
                    "dossier_reconciliations 拒收须由外层 RejectionCollector 归属"
                )
            # ADR 0015 F1：RejectedItem.item 恒 dict；非 dict 包装 raw_value。
            # 域级拒收的 item 已是 dict；形状级（非 list/非 dict 项）归 sanitize_delta_shape
            # 独家（0015-D6/F1，#1745 删双 producer）。
            if isinstance(raw_item, dict):
                payload = dict(raw_item)
            else:
                payload = {"raw_value": raw_item}
            rejection_collector.record(
                "dossier_reconciliations",
                RejectedItem(
                    item=payload, reason=reason, category=category, source=source,
                ),
                int(turn),
            )

        # 形状净化归 sanitize_delta_shape 独家（0015-D6；#1745 删本段平行形状拒收）。
        # 非 list / 非 dict 项此处跳过域逻辑；settle 后半段 sanitize→collector 一次拒收。
        if not isinstance(generated, list):
            generated = []

        supplied: Dict[int, Tuple[object, str]] = {}
        for item in generated:
            if not isinstance(item, dict):
                continue
            try:
                dossier_id = strict_int(item.get("dossier_id", 0))
                if dossier_id <= 0:
                    raise ValueError("not positive")
            except (TypeError, ValueError):
                _reject(item, "对账提案案卷编号无效", "invalid_enum")
                continue
            if dossier_id not in targets:
                _reject(
                    item,
                    f"对账提案指向非在途拨帑案卷：{dossier_id}",
                    "missing_ref",
                )
                continue
            if dossier_id in supplied:
                _reject(item, "对账提案存在重复案卷", "invalid_enum")
                continue
            has_arrived = "arrived_amount" in item
            has_loss = "loss_amount" in item
            if has_arrived and has_loss:
                # DELTA_SCHEMA 二选一：两字段同在不猜优先，逐项拒收（0015-D4 不猜）
                _reject(
                    item,
                    "对账提案 arrived_amount 与 loss_amount 须二选一",
                    "invalid_enum",
                )
                continue
            if has_arrived:
                raw_amount = item.get("arrived_amount")
                amount_label = "实抵"
            elif has_loss:
                raw_amount = item.get("loss_amount")
                amount_label = "折损"
            else:
                _reject(item, "对账提案须含 arrived_amount 或 loss_amount", "missing_field")
                continue
            try:
                amount = strict_int(raw_amount)
            except (TypeError, ValueError):
                _reject(item, f"对账{amount_label}值无效", "invalid_enum")
                continue
            if amount_label == "实抵":
                proposed = amount
            else:
                proposed = int(targets[dossier_id]["ordered_amount"]) - amount
            note = str(item.get("note") or "").strip()
            supplied[dossier_id] = (proposed, note)

        # 无在途目标：坏提案已逐项拒收，不落假对账行。
        if not targets:
            return []

        reports: List[Dict[str, object]] = []
        for dossier_id, target in targets.items():
            ordered = int(target["ordered_amount"])
            escorted = bool(target["escorted"])
            if dossier_id in supplied:
                proposed, note = supplied[dossier_id]
                arrived = clamp_grant_arrival_amount(
                    ordered, proposed, escorted=escorted,
                )
            else:
                # 分段过月会多次调本写入。本次没有提案的路已有本回合行，不得用中位覆盖先前段落下的实抵。
                if self.dossiers.has_reconciliation(int(dossier_id), int(turn)):
                    continue
                lo, hi = grant_arrival_bounds(ordered, escorted=escorted)
                arrived = (lo + hi) // 2
                note = ""
            loss = ordered - arrived
            source_id = target["escort_source_dossier_id"]
            relation = str(target["relation_type"] or "")
            self.dossiers.upsert_reconciliation(
                int(dossier_id), int(turn), ordered=ordered, arrived=arrived,
                escorted=bool(escorted), escort_source_dossier_id=source_id,
                relation_type=relation, note=note,
            )
            history = self.dossiers.reconciliations(int(dossier_id))
            reports.append(history[-1])
        return reports

    # ── #625 / ADR 0077 supervision fact bottom ─────────────────────────

    def record_monthly_supervision_presence(
        self, turn: int, *, commit: bool = False,
    ) -> Dict[str, object]:
        """月度在场扫描：稽核链 → presence 行；同 turn UNIQUE 幂等不双计。

        settle 节拍：须先于月报 origin 标记调用（commit=False）。
        """
        from ming_sim.supervision import (
            SUPERVISION_RELATION,
            resolve_dossier_owner_name,
        )

        turn_i = int(turn)
        presence_written = 0
        # 入链：source=稽核方案卷，target=被稽案卷
        link_rows = self.dossiers.audit_link_rows(SUPERVISION_RELATION)
        for link in link_rows:
            source_status = str(link["source_status"] or "")
            target_status = str(link["target_status"] or "")
            # 双方仍在执行面（promulgated/executing）才记在场
            if source_status not in {"promulgated", "executing"}:
                continue
            if target_status not in {"promulgated", "executing"}:
                continue
            audit_dossier = self.dossiers.get(int(link["source_dossier_id"]))
            if audit_dossier is None:
                continue
            auditor = resolve_dossier_owner_name(audit_dossier)
            if not auditor:
                continue
            self.dossiers.upsert_presence(
                int(link["target_dossier_id"]), turn_i, auditor_name=auditor,
                audit_dossier_id=int(link["source_dossier_id"]),
                relation_type=SUPERVISION_RELATION,
            )
            presence_written += 1

        if commit:
            self.conn.commit()
        return {"presence_written": presence_written, "turn": turn_i}

    def record_monthly_loophole_exposures_from_reconciliations(
        self, turn: int, *, commit: bool = False,
    ) -> Dict[str, object]:
        """对账后暴露派生：本回合 loss>0 且该案卷当月稽核在场 → 暴露行。

        settle 节拍：须在 record_monthly_grant_reconciliations 之后调用。
        在场门与终值路共用 store.has_supervision_presence（统一口径）。
        """
        turn_i = int(turn)
        exposure_written = 0
        recon_rows = self.dossiers.reconciliation_loss_rows(turn_i)
        for row in recon_rows:
            did = int(row["dossier_id"])
            if not self.dossiers.has_supervision_presence(did, turn_i):
                continue
            action_type = (
                str(row["action_type"] or "grant_allocation").strip()
                or "grant_allocation"
            )
            if self.record_loophole_exposure(
                did, turn_i, action_type, "degraded", commit=False,
            ):
                exposure_written += 1

        if commit:
            self.conn.commit()
        return {"exposure_written": exposure_written, "turn": turn_i}

    def record_monthly_supervision_facts(
        self, turn: int, *, commit: bool = False,
    ) -> Dict[str, object]:
        """兼容组合：在场扫描 + 对账暴露派生（测试/restore 便捷口）。

        生产 settle 节拍应分调两单职责函数（origin 前 / 对账后）。
        """
        presence = self.record_monthly_supervision_presence(turn, commit=False)
        exposure = self.record_monthly_loophole_exposures_from_reconciliations(
            turn, commit=False,
        )
        if commit:
            self.conn.commit()
        return {
            "presence_written": int(presence.get("presence_written") or 0),
            "exposure_written": int(exposure.get("exposure_written") or 0),
            "turn": int(turn),
        }

    def record_loophole_exposure(
        self,
        dossier_id: int,
        turn: int,
        action_type: str,
        execution_form: str,
        *,
        commit: bool = True,
    ) -> bool:
        """逐次暴露一行；同 (dossier,turn,action_type,execution_form) 幂等。"""
        form = str(execution_form or "").strip()
        if form not in DOSSIER_EXECUTION_OUTCOMES:
            raise ValueError(f"空子暴露执行格形态非法：{form!r}")
        atype = str(action_type or "").strip()
        if not atype:
            raise ValueError("空子暴露 action_type 不能为空")
        if atype not in DOSSIER_ACTION_TYPES:
            # 允许既有枚举；未知响亮拒（禁自由文本类）
            raise ValueError(f"空子暴露 action_type 非法：{atype!r}")
        if self.dossiers.get(int(dossier_id)) is None:
            raise ValueError("案卷不存在")
        wrote = self.dossiers.record_loophole_exposure(
            int(dossier_id), int(turn), atype, form,
        )
        if commit:
            self.conn.commit()
        return wrote

    def list_supervision_history(
        self, dossier_id: int, *, as_of_turn: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """读端：在场行 + 连号派生 + 稽核人任期/派系/操守定性（不落钝化分）。"""
        from ming_sim.supervision import (
            character_faction_integrity,
            character_tenure,
            derive_consecutive_months,
            faction_relation,
            integrity_band,
            resolve_dossier_owner_name,
        )

        presence = self.dossiers.presence_rows(
            int(dossier_id), as_of_turn=as_of_turn,
        )
        if not presence:
            return []
        subject = self.dossiers.get(int(dossier_id)) or {}
        subject_name = resolve_dossier_owner_name(subject)
        subject_faction, _subj_integrity = character_faction_integrity(
            self, subject_name,
        )
        # 按稽核人聚合 turn 以派生连续月数
        turns_by_auditor: Dict[str, List[int]] = {}
        for row in presence:
            if not row["present"]:
                continue
            turns_by_auditor.setdefault(
                str(row["auditor_name"]), [],
            ).append(int(row["turn"]))

        end = int(as_of_turn) if as_of_turn is not None else max(
            int(r["turn"]) for r in presence
        )
        out: List[Dict[str, object]] = []
        for row in presence:
            auditor = str(row["auditor_name"] or "")
            a_faction, a_integrity = character_faction_integrity(self, auditor)
            months = derive_consecutive_months(
                turns_by_auditor.get(auditor, []), end_turn=end,
            )
            out.append({
                **row,
                "consecutive_months": months,
                "auditor_tenure": character_tenure(self, auditor),
                "auditor_faction": a_faction,
                "auditor_integrity_band": integrity_band(a_integrity),
                "subject_name": subject_name,
                "subject_faction": subject_faction,
                "subject_tenure": character_tenure(self, subject_name),
                "faction_relation": faction_relation(a_faction, subject_faction),
            })
        return out

    def build_supervision_judge_surface(
        self, dossier_id: int, *, as_of_turn: Optional[int] = None,
    ) -> Dict[str, object]:
        """观察槽：监督史 + 暴露史 + 变形倾向定性事实（禁钝化数值）。"""
        from ming_sim.supervision import build_transformation_tendency_facts

        history = self.list_supervision_history(
            int(dossier_id), as_of_turn=as_of_turn,
        )
        exposures = self.dossiers.exposure_rows(
            int(dossier_id), as_of_turn=as_of_turn,
        )
        return {
            "dossier_id": int(dossier_id),
            "supervision_history": history,
            "loophole_exposures": exposures,
            "transformation_tendency_facts": build_transformation_tendency_facts(
                supervision_history=history,
                loophole_exposures=exposures,
            ),
        }

    def compose_supervision_report_origin(
        self, dossier_id: int, turn: int,
    ) -> str:
        """按当月在场稽核派系关系给 #619 origin 打私货/同派标记（扩 origin，不加列）。"""
        from ming_sim.supervision import (
            ORIGIN_MARK_PRIVATE_GOODS,
            ORIGIN_MARK_SAME_FACTION_BLIND,
            compose_report_origin,
        )

        base = DOSSIER_REPORT_ORIGIN_MONTHLY
        history = self.list_supervision_history(
            int(dossier_id), as_of_turn=int(turn),
        )
        # 只看本 turn 在场行
        marks: List[str] = []
        for row in history:
            if int(row.get("turn") or 0) != int(turn):
                continue
            if not row.get("present"):
                continue
            rel = str(row.get("faction_relation") or "")
            if rel == "same":
                marks.append(ORIGIN_MARK_SAME_FACTION_BLIND)
            elif rel == "enemy":
                marks.append(ORIGIN_MARK_PRIVATE_GOODS)
        return compose_report_origin(base, marks)

    def trigger_supervision_countermeasures(
        self, state: GameState, *, commit: bool = False,
    ) -> List[Dict[str, object]]:
        """孤直稽核连续在场满 12 月 → 涌现缝立反制 issue（邸报前 auto_trigger 同缝）。

        禁 0099/0091 新机制；禁占 #623 entry_kind；明升暗调形态走既有 issue 载体，
        人事落地仍经 office_changes applier（本硬门只立局势）。
        """
        from ming_sim.supervision import (
            COUNTERMEASURE_ORIGIN_KIND,
            COUNTERMEASURE_PRESENCE_MONTHS,
            countermeasure_origin_ref,
            is_upright_integrity,
            pick_countermeasure_kind,
            character_faction_integrity,
            derive_consecutive_months,
        )

        # 全库在场行按 (auditor, dossier) 聚合
        rows = self.dossiers.presence_turns_by_auditor(min_months=0)
        grouped: Dict[Tuple[str, int], List[int]] = {}
        for row in rows:
            key = (str(row["auditor_name"]), int(row["dossier_id"]))
            grouped.setdefault(key, []).append(int(row["turn"]))

        triggered: List[Dict[str, object]] = []
        for (auditor, dossier_id), turns in grouped.items():
            months = derive_consecutive_months(turns)
            if months < COUNTERMEASURE_PRESENCE_MONTHS:
                continue
            _fac, integrity = character_faction_integrity(self, auditor)
            if not is_upright_integrity(integrity):
                continue
            origin_ref = countermeasure_origin_ref(auditor, dossier_id)
            existing = self.find_any_issue_by_origin(
                COUNTERMEASURE_ORIGIN_KIND, origin_ref,
            )
            if existing is not None:
                continue
            kind = pick_countermeasure_kind(auditor, dossier_id)
            title = f"针对{auditor}的{kind}"
            # 玩家可见 stage 禁系统词：崇祯朝口语，不写钝化/陋规化
            stage_text = f"{auditor}连月按核不贷，官场反噬已起，{kind}之议渐露。"
            issue_id = self.insert_issue(
                state,
                kind="situation",
                title=title,
                origin_kind=COUNTERMEASURE_ORIGIN_KIND,
                origin_ref=origin_ref,
                stage_text=stage_text,
                tags=["supervision_countermeasure", kind, auditor],
                participants=[auditor],
                bar_value=35,
                bar_good_meaning="反噬平息",
                bar_bad_meaning="反噬坐大",
                inertia=1,
                severity=55,
                faction_hint=str(_fac or ""),
                commit=False,
            )
            triggered.append({
                "issue_id": int(issue_id),
                "auditor_name": auditor,
                "dossier_id": int(dossier_id),
                "countermeasure_kind": kind,
                "origin_ref": origin_ref,
                "consecutive_months": months,
            })
        if commit and triggered:
            self.conn.commit()
        return triggered

    # ── #1726 奏疏收件箱（玩家面）──────────────────────────────────────
    # 两类：dossier_reported_progress（案卷进度）+ faction_denunciations（派系检举）。
    # 密令私轨不入此面（密令面板另管）。已读键绑具体奏报行，不绑案卷。

    MEMORIAL_READS_KV_KEY = "memorial_reads"
    MEMORIAL_AUTHOR_FALLBACK = "某臣"

    def _memorial_read_keys(self) -> Set[str]:
        raw = self.kv_get(self.MEMORIAL_READS_KV_KEY)
        if not raw:
            return set()
        data = load_stored_list(raw, label="memorial_reads")
        return {str(item) for item in data if str(item or "").strip()}

    def mark_memorials_read(self, keys: Iterable[str]) -> None:
        """标记奏报已读；键=progress:{id}|denunciation:{id}，随存档（kv_store）持久化。"""
        incoming = {str(k).strip() for k in keys if str(k or "").strip()}
        if not incoming:
            return
        merged = sorted(self._memorial_read_keys() | incoming)
        self.kv_set(self.MEMORIAL_READS_KV_KEY, json.dumps(merged, ensure_ascii=False))

    def list_player_memorials(self) -> List[Dict[str, object]]:
        """玩家奏疏收件箱：进度奏报 + 派系检举，含未读位；不夹带引擎结构化字段。"""
        from ming_sim.participant_roster import resolve_dossier_owner_name

        read_keys = self._memorial_read_keys()
        out: List[Dict[str, object]] = []

        progress_rows = self.dossiers.recent_reported_progress()
        # 承办人按案卷解析；同案卷多次奏报共用归属缓存。
        owner_cache: Dict[int, str] = {}
        for row in progress_rows:
            did = int(row["dossier_id"])
            if did not in owner_cache:
                dossier = self.dossiers.get(did)
                name = resolve_dossier_owner_name(dossier or {}) if dossier else ""
                owner_cache[did] = str(name or "").strip() or self.MEMORIAL_AUTHOR_FALLBACK
            key = f"progress:{int(row['id'])}"
            out.append({
                "key": key,
                "kind": "progress",
                "turn": int(row["turn"]),
                "author_name": owner_cache[did],
                "memorial_text": str(row["memorial_text"] or ""),
                "unread": key not in read_keys,
            })

        for row in self.dossiers.denunciations():
            key = f"denunciation:{int(row['id'])}"
            out.append({
                "key": key,
                "kind": "denunciation",
                "turn": int(row["turn"]),
                "author_name": str(row.get("accuser_name") or "").strip()
                or self.MEMORIAL_AUTHOR_FALLBACK,
                "memorial_text": str(row.get("memorial_text") or ""),
                "unread": key not in read_keys,
            })

        out.sort(key=lambda item: (int(item["turn"]), str(item["key"])), reverse=True)
        return out

    def unread_memorial_count(self) -> int:
        """未读奏报数（进度 + 检举）。"""
        return sum(1 for row in self.list_player_memorials() if row.get("unread"))

    def build_faction_denunciation_facts(self, *, exclude_dossier_ids: Optional[Set[int]] = None) -> Dict[str, object]:
        """#627 供事实：派系恩怨/分叉/处境/个性——注入既有叙事 LLM 步。

        输入不携真伪位、不设 quota、不报烈度。fork 物理事实经单源读端装配。
        """
        from ming_sim.participant_roster import resolve_dossier_owner_name
        from ming_sim.qualitative import (
            identity_band,
            power_band,
            qualitative_character_axis,
            satisfaction_band,
        )
        from ming_sim.supervision import (
            character_faction_integrity,
            faction_relation,
        )

        rows = self.dossiers.active_effect_facts()

        forked_dossiers: List[Dict[str, object]] = []
        subject_names: Set[str] = set()
        subject_factions: Set[str] = set()
        for row in rows:
            dossier_id = int(row["id"])
            if exclude_dossier_ids and dossier_id in exclude_dossier_ids:
                continue
            fork_state = self.read_dossier_fork_state(dossier_id)
            dossier = dict(row)
            subject_name = resolve_dossier_owner_name(dossier) or ""
            subject_faction, _ = character_faction_integrity(self, subject_name)
            # #655 reuses this canonical persona projection for every durable
            # transformed execution fact; forked_dossiers itself remains the
            # narrower denunciation/fork list.
            if str(row["execution_outcome"] or "") == "transformed":
                if subject_name:
                    subject_names.add(subject_name)
                if subject_faction:
                    subject_factions.add(subject_faction)
            # Closed transformed dossiers are a persona source for #655, not
            # open generic denunciation forks.
            if str(row["status"] or "") == "closed":
                continue
            if not fork_state["fork"]:
                continue
            case_summary = str(row["decree_text"] or "").strip()
            if len(case_summary) > 48:
                case_summary = case_summary[:48]
            # 物理事实：奏报面 / 执行格 / 旨外——直接复用 fork 读端（类型已保证）
            forked_dossiers.append({
                "dossier_id": dossier_id,
                "subject_name": subject_name,
                "subject_faction": subject_faction,
                "case_summary": case_summary,
                "reported_bands": fork_state["reported_bands"],
                "execution_outcome": fork_state["execution_outcome"],
                "beyond_intent": fork_state["beyond_intent"],
                "actual_effect_count": fork_state["actual_effect_count"],
            })
            if subject_name:
                subject_names.add(subject_name)
            if subject_faction:
                subject_factions.add(subject_faction)

        # 在朝人物（供敌对/个性）
        court_rows = CharacterStore(self.conn).read_build_faction_denunciation_facts()
        names_by_faction: Dict[str, List[str]] = {}
        char_meta: Dict[str, Dict[str, object]] = {}
        for crow in court_rows:
            name = str(crow["name"] or "").strip()
            fac = str(crow["faction"] or "").strip()
            if not name or not fac:
                continue
            names_by_faction.setdefault(fac, []).append(name)
            char_meta[name] = {
                "faction": fac,
                "integrity": crow["integrity"],
                "identity": crow["identity"],
            }

        all_factions = sorted({
            str(r["name"])
            for r in FactionStore(self.conn).read_build_faction_denunciation_facts()
            if str(r["name"] or "").strip()
        } | set(names_by_faction))

        # 敌对关系：仅涉及承办人派系的 enemy 对（无分叉月保持空列表，不退化全派系矩阵）
        focus_factions = set(subject_factions)
        enmities: List[Dict[str, object]] = []
        seen_pair: Set[Tuple[str, str]] = set()
        for fa in sorted(focus_factions):
            for fb in all_factions:
                if fa == fb:
                    continue
                if faction_relation(fa, fb) != "enemy":
                    continue
                pair = tuple(sorted((fa, fb)))
                if pair in seen_pair:
                    continue
                seen_pair.add(pair)  # type: ignore[arg-type]
                enmities.append({
                    "faction_a": pair[0],
                    "faction_b": pair[1],
                    "relation": "enemy",
                })

        related_factions = set(focus_factions)
        for item in enmities:
            related_factions.add(str(item["faction_a"]))
            related_factions.add(str(item["faction_b"]))

        situations: List[Dict[str, object]] = []
        for fac in sorted(related_factions):
            situations.append({
                "faction": fac,
                "leverage_band": power_band(self.faction_leverage(fac)),
                "satisfaction_band": satisfaction_band(
                    self.faction_satisfaction(fac),
                ),
            })

        # 个性：承办人 + 其敌派在朝人物（正向定性档）
        persona_names: Set[str] = set(subject_names)
        enemy_facs = {
            str(item["faction_a"]) for item in enmities
        } | {
            str(item["faction_b"]) for item in enmities
        }
        for fac in enemy_facs:
            for name in names_by_faction.get(fac, []):
                persona_names.add(name)
        personas: List[Dict[str, object]] = []
        for name in sorted(persona_names):
            meta = char_meta.get(name)
            if meta is None:
                fac, integrity = character_faction_integrity(self, name)
                if not fac:
                    continue
                row = CharacterStore(self.conn).read_build_faction_denunciation_facts_identity((name,))
                identity_val = row["identity"] if row is not None else None
                meta = {
                    "faction": fac,
                    "integrity": integrity,
                    "identity": identity_val,
                }
            personas.append({
                "name": name,
                "faction": str(meta.get("faction") or ""),
                "integrity_band": qualitative_character_axis(
                    "integrity", meta.get("integrity"),
                ),
                "identity_band": identity_band(meta.get("identity")),
            })

        return {
            "forked_dossiers": forked_dossiers,
            "faction_enmities": enmities,
            "faction_situations": situations,
            "character_personas": personas,
        }

    def accept_faction_denunciations(
        self,
        state: GameState,
        entries: object = None,
        *,
        commit: bool = False,
    ) -> List[Dict[str, object]]:
        """#627 承接落库：结构化检举条目 + clamp + 真伪底派生 + 去重。

        clamp 仅限：所指案卷须真实存在且非 closed；检举人须为在场 active 人物。
        真伪底：fork 单源读端机械对账 → compose_denunciation_origin。
        去重键=检举人×案卷×真伪类（不含 turn）；案情升级可再落；不写 loophole。
        正文原样落库（零引擎模板）。禁自动转案/改世界状态。
        """
        from ming_sim.participant_roster import resolve_dossier_owner_name
        from ming_sim.supervision import (
            character_faction_integrity,
            compose_denunciation_origin,
            denunciation_case_upgraded,
            derive_denunciation_is_true,
        )

        if entries is None:
            return []
        if not isinstance(entries, list):
            return []

        turn = int(state.turn)
        accepted: List[Dict[str, object]] = []

        for raw in entries:
            if not isinstance(raw, dict):
                continue
            # 仅 canonical / ITEM_FIELD_ALIASES 背书键（检举人/被检举人→*_name）
            accuser = str(raw.get("accuser_name") or "").strip()
            memorial = str(
                raw.get("memorial_text") or raw.get("body") or ""
            ).strip()
            if not accuser or not memorial:
                continue
            try:
                dossier_id = int(
                    raw.get("target_dossier_id")
                    if raw.get("target_dossier_id") is not None
                    else raw.get("dossier_id") or 0
                )
            except (TypeError, ValueError):
                continue
            if dossier_id <= 0:
                continue

            # clamp：检举人在场
            accuser_row = CharacterStore(self.conn).read_accept_faction_denunciations((accuser,))
            if accuser_row is None or str(accuser_row["status"] or "") != "active":
                continue
            accuser_faction = str(accuser_row["faction"] or "").strip()

            # clamp：案卷存在且非 closed
            dossier = self.dossiers.get(dossier_id)
            if dossier is None:
                continue
            if str(dossier.get("status") or "").strip() == "closed":
                continue

            subject_name = str(raw.get("subject_name") or "").strip()
            if not subject_name:
                subject_name = resolve_dossier_owner_name(dossier) or ""
            subject_faction, _ = character_faction_integrity(self, subject_name)

            fork_state = self.read_dossier_fork_state(dossier_id)
            is_true = derive_denunciation_is_true(fork=fork_state["fork"])
            origin = compose_denunciation_origin(is_true=is_true)

            # 去重键=检举人×案卷×真伪类（origin 含真伪 mark；不含 turn）
            # 单源 LIMIT 1：升级再落允许多行，无 UNIQUE 约束
            prior_row = self.dossiers.latest_denunciation_for(
                accuser_name=accuser, target_dossier_id=int(dossier_id), origin=origin,
            )
            if prior_row is not None:
                prev_payload = load_stored_object(
                    prior_row["payload_json"], label="payload_json",
                )
                if not denunciation_case_upgraded(prev_payload, fork_state):
                    continue

            entry_payload: Dict[str, object] = {
                "accuser_name": accuser,
                "accuser_faction": accuser_faction,
                "subject_name": subject_name,
                "subject_faction": subject_faction,
                "target_dossier_id": dossier_id,
                "fork": is_true,
                "actual_effect_count": fork_state["actual_effect_count"],
                "beyond_intent": fork_state["beyond_intent"],
            }
            if is_true:
                # 分叉暴露落检举条目自身（明文不写 loophole_exposures；不回注知识轨）
                entry_payload["fork_exposure"] = {
                    "reported_bands": fork_state["reported_bands"],
                    "execution_outcome": fork_state["execution_outcome"],
                    "beyond_intent": fork_state["beyond_intent"],
                    "actual_effect_count": fork_state["actual_effect_count"],
                    "fork": True,
                }

            entry_id = self.dossiers.insert_denunciation(
                turn=turn, accuser_name=accuser, accuser_faction=accuser_faction,
                subject_name=subject_name, subject_faction=subject_faction,
                target_dossier_id=int(dossier_id), origin=origin,
                payload=entry_payload, memorial_text=memorial,
            )
            accepted.append({
                "id": entry_id,
                "turn": turn,
                "accuser_name": accuser,
                "accuser_faction": accuser_faction,
                "subject_name": subject_name,
                "subject_faction": subject_faction,
                "target_dossier_id": dossier_id,
                "origin": origin,
                "is_true": is_true,
                "memorial_text": memorial,
                "payload": entry_payload,
            })

        if commit and accepted:
            self.conn.commit()
        return accepted

    def trigger_commitment_backlashes(
        self, state: GameState, *, commit: bool = False,
    ) -> List[Dict[str, object]]:
        """#626：事废/烂尾/变形暴露 → 承诺所系反噬 issue（邸报前 auto_trigger 同缝）。

        方案 a（#625 形制）：代码侧确定性硬门；直读执行格/哭谏消费/承诺；
        find_any_issue_by_origin 幂等；不碰 trigger_gate 求值器、不扩门表白名单。
        分档触发侧重算 assess_foundation_tier（零新列）；唯 halfway 触发。
        一拍差：判决 closed_turn < 当前 turn 才扫（判决在 delta、扫描在次回合前括号）。
        与 #623 立即倒退去重：本片只立承诺所系 issue＋本片具名 metrics 一锤子，不重放
        breach_halfway_setback / 民心-3·皇威-2 直击；不写 ongoing_effects.metrics 镜像。

        事废读源：todo.payload_json.verdict=='persist'（#623 finalize_persist 既判痕迹；
        consumed 有三源不可区分，单独不得作既判证据；常经 0056 先关案卷时
        execution_outcome 可能空，故不以执行格为事废唯一源）。
        烂尾：读执行格终值 failed（#621）。
        变形：execution_outcome==transformed 仅作候选；须经 #622 公开读端
        list_economy_moves_for_dossier + beyond_intent 确认分叉事实后才立案。
        """
        from ming_sim.commitment_backlash import (
            BACKLASH_NAMED_METRICS,
            BACKLASH_ORIGIN_KIND,
            SOURCE_BREACH_VERDICT,
            SOURCE_DEFORMATION_EXPOSURE,
            SOURCE_FAILED_TERMINAL,
            backlash_origin_ref,
            classify_backlash_source,
        )
        from ming_sim.breach_plea import (
            ENTRY_KIND_BREACH_PLEA,
            FOUNDATION_HALFWAY,
            PLEA_VERDICT_KEY,
            PLEA_VERDICT_PERSIST,
            assess_foundation_tier,
        )
        from ming_sim.flows import _apply_metric_dict

        candidates: List[Tuple[int, str, int]] = []  # (commitment_id, source_kind, dossier_id)

        # ① 事废判决：persist 既判结构化痕迹 ∧ 承诺 closed_turn 一拍差
        # 总纲：不从 consumed 反推；不读 execution_note 子串。
        for todo in self.list_next_audience_todos(status="consumed"):
            if str(todo.get("entry_kind") or "") != ENTRY_KIND_BREACH_PLEA:
                continue
            payload = todo.get("payload_json") or {}
            if not isinstance(payload, dict):
                continue
            if str(payload.get(PLEA_VERDICT_KEY) or "") != PLEA_VERDICT_PERSIST:
                continue
            cid = int(todo.get("commitment_ref") or 0)
            if cid <= 0:
                continue
            crow = IssueStore(self.conn).read_trigger_commitment_backlashes((cid,))
            if crow is None or not str(crow["commitment_kind"] or "").strip():
                continue
            judgment_turn = int(crow["closed_turn"] or 0)
            if judgment_turn <= 0 or judgment_turn >= int(state.turn):
                continue
            did = 0
            origin = str(crow["origin_ref"] or "")
            if origin.startswith("dossier:"):
                try:
                    did = int(origin.split(":", 1)[1])
                except (TypeError, ValueError):
                    did = 0
            candidates.append((cid, SOURCE_BREACH_VERDICT, did))

        breach_commitment_ids = {
            cid for cid, sk, _ in candidates if sk == SOURCE_BREACH_VERDICT
        }

        # ② 烂尾终值 / 变形暴露候选：执行格终值（closed_turn 一拍差）
        # 执行格 failed 默认 failed_terminal；事废已由 path ① 独占，同承诺不双立。
        # 变形不得仅凭 transformed 文本立案——须 #622 分叉读端确认 beyond_intent。
        rows = self.dossiers.closed_outcome_rows_before(int(state.turn))
        for row in rows:
            dossier_id = int(row["id"])
            source_kind = classify_backlash_source(
                execution_outcome=row["execution_outcome"],
            )
            if source_kind is None:
                continue
            if source_kind == SOURCE_DEFORMATION_EXPOSURE:
                # #1260：分叉确认扩为 economy+fiscal 单源（纯 fiscal 旨外亦可立案）。
                if not self.dossier_has_beyond_intent(dossier_id):
                    continue
            for commitment in self.list_commitments_for_dossier(dossier_id):
                if not str(commitment.get("commitment_kind") or "").strip():
                    continue
                cid = int(commitment["id"])
                # 仅交叉去重：path① 已入候选的事废承诺，执行格 failed 不再叠 failed_terminal。
                # origin_ref 仍按 source_kind 分键（非全局「一诺一源」）。
                if (
                    source_kind == SOURCE_FAILED_TERMINAL
                    and cid in breach_commitment_ids
                ):
                    continue
                candidates.append((cid, source_kind, dossier_id))

        triggered: List[Dict[str, object]] = []
        seen_origin: set[str] = set()
        for cid, source_kind, dossier_id in candidates:
            if assess_foundation_tier(self, cid) != FOUNDATION_HALFWAY:
                continue
            origin_ref = backlash_origin_ref(cid, source_kind)
            if origin_ref in seen_origin:
                continue
            seen_origin.add(origin_ref)
            existing = self.find_any_issue_by_origin(
                BACKLASH_ORIGIN_KIND, origin_ref,
            )
            if existing is not None:
                continue
            crow = IssueStore(self.conn).read_trigger_commitment_backlashes_title((cid,))
            # P7：硬门只落结构化事实；标题仅链接源承诺既有事实，不拼装新成句。
            # 玩家 stage/narrative 由叙事 LLM 步从特征化输入长出；bar 端标故意留空，
            # web 空串不渲染（#626 甲：不开 bar 写口）。
            title_c = str(crow["title"] if crow is not None else "").strip()
            # 一锤子：复用既有 _apply_metric_dict（ISSUE_METRIC_KEYS），不自建 clamp。
            applied_metrics = _apply_metric_dict(
                state, dict(BACKLASH_NAMED_METRICS), db=self,
            )
            issue_id = self.insert_issue(
                state,
                kind="situation",
                title=title_c,  # 源承诺事实链接；非 f-string 模板
                origin_kind=BACKLASH_ORIGIN_KIND,
                origin_ref=origin_ref,
                stage_text="",  # 玩家文案留给叙事 LLM 步
                tags=[],  # 机读身份仅 origin_kind/origin_ref；tags 不进玩家面
                bar_value=35,
                bar_good_meaning="",  # 空串；web 条件渲染，无 LLM bar 写口
                bar_bad_meaning="",
                inertia=-2,
                severity=55,
                ongoing_effects={},  # 一锤子，不镜像 metrics 到月扣
                commit=False,
            )
            self.advance_issue(
                state,
                int(issue_id),
                trigger_kind="commitment_backlash",
                trigger_ref=f"issue:{cid}",
                delta_bar=0,
                stage_text="",
                narrative="",  # 结构化账：metrics；叙述留给叙事步
                metric_delta=dict(applied_metrics),
                commit=False,
            )
            triggered.append({
                "issue_id": int(issue_id),
                "commitment_ref": cid,
                "dossier_id": int(dossier_id),
                "source_kind": source_kind,
                "origin_ref": origin_ref,
                "trigger_ref": f"issue:{cid}",
                "metrics_delta": dict(applied_metrics),
            })
        if commit and triggered:
            self.conn.commit()
        return triggered

    def merge_grant_reconciliation_into_execution_note(
        self, dossier_id: int, *, commit: bool = True,
    ) -> Optional[str]:
        """S10 结案消费对账真源：经 merge_execution_note 单一写口增补说明。"""
        history = self.dossiers.reconciliations(int(dossier_id))
        if not history:
            return None
        latest = history[-1]
        fragment = (
            f"押解对账：应解{int(latest['ordered_amount'])}两，"
            f"实抵{int(latest['arrived_amount'])}两"
        )
        return self.merge_execution_note(int(dossier_id), fragment, commit=commit)

    @staticmethod
    def _grant_allocation_is_monthly(payload: Optional[Dict[str, object]]) -> bool:
        return str((payload or {}).get("cadence") or "").strip() == "每月"

    @staticmethod
    def _grant_allocation_is_honorific(payload: Optional[Dict[str, object]]) -> bool:
        return str((payload or {}).get("grant_action") or "").strip() in {"加衔", "荫叙"}

    @staticmethod
    def _is_army_pay_grant_payload(payload: Optional[Dict[str, object]]) -> bool:
        """#1503：补饷身份只由显式 grant_action=协饷 决定。"""
        return str((payload or {}).get("grant_action") or "").strip() == "协饷"

    def _normalize_army_pay_grant_payload(
        self, payload: Dict[str, object],
    ) -> Dict[str, object]:
        """#1503：拨饷类成案载荷 — 五字段显式；缺则一次收集响亮；不补值。

        #1620：target_id 经 canonicalize_xiexang_army_target 取得 canonical army id
        （展示名关宁军→guanning）；与 capture 共用严格 helper，不改 apply 查询。
        """
        if not self._is_army_pay_grant_payload(payload):
            return payload
        if self._grant_allocation_is_honorific(payload):
            return payload
        from ming_sim.action_materialize import (
            canonicalize_xiexang_army_target,
            require_explicit_xiexang_fields,
        )

        normalized = dict(payload)
        explicit = require_explicit_xiexang_fields(
            amount=normalized.get("amount"),
            account=str(normalized.get("account") or ""),
            purpose=str(normalized.get("purpose") or ""),
            target_kind=str(normalized.get("target_kind") or ""),
            target_id=str(normalized.get("target_id") or ""),
            cadence=str(normalized.get("cadence") or ""),
        )
        explicit["target_id"] = canonicalize_xiexang_army_target(
            self, explicit["target_id"],
        )
        normalized.update(explicit)
        if self._grant_allocation_is_monthly(normalized):
            return normalized
        # #1503：非月度拨饷强制 immediate。覆盖 normalize 前置插入的 in_transit 默认，
        # 以及旧 pending/恢复载荷残留的在途面——在途只留叙事，不进机械对账轨。
        normalized["execution_surface"] = "immediate"
        return normalized

    def _apply_army_pay_grant_effect(
        self, state: GameState, row, payload: Dict[str, object], dossier_id: int,
    ) -> int:
        """#1503：颁布缝一次消费拨饷载荷 — 扣库+销欠同事务（ADR 0023 clamp）。"""
        from ming_sim.flows import _apply_economy_list

        amount = int(payload.get("amount") or 0)
        if amount <= 0:
            raise ValueError("拨饷案卷 amount 必须为正数")
        account = str(
            payload.get("account") or payload.get("target_account") or ""
        ).strip()
        if account not in {"国库", "内库"}:
            raise ValueError("拨饷案卷 account 仅可为国库或内库")
        target_id = str(
            payload.get("target_id") or row.get("target_id") or ""
        ).strip()
        if str(payload.get("target_kind") or row.get("target_kind") or "") != "army" or not target_id:
            raise ValueError("拨饷案卷须指定 target_kind=army 与 target_id")
        origin_ref = f"dossier:{int(dossier_id)}"
        # 幂等：同案已有补饷流水则不二扣（ready 重放 / 重复 settle 护栏）。
        existing = [
            m for m in self.list_economy_moves_for_dossier(int(dossier_id))
            if str(m.get("purpose") or "") == "补饷"
        ]
        if existing:
            return abs(int(existing[0].get("delta") or 0))
        move = {
            "account": account,
            "delta": -amount,
            "category": str(payload.get("category") or "奉旨拨饷"),
            "reason": str(payload.get("reason") or row["decree_text"]),
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": target_id,
            "origin_ref": origin_ref,
        }
        results = _apply_economy_list(
            self, state, [move], commit=False, require_origin=False,
        )
        spent = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("rejected"):
                raise ValueError(str(item.get("reason") or "拨饷落账被拒"))
            spent += abs(int(item.get("delta") or 0))
        return spent

    def _create_grant_fiscal_item(
        self, state: GameState, payload: Dict[str, object], dossier_id: int,
        *, account: str, amount: int, text: str,
    ) -> str:
        """#518：常项拨帑建月度科目；display 不含口谕数字（P4）。"""
        display = {
            "赏赉": "赏赉月拨",
            "发内帑": "内帑月拨",
            "赈灾": "赈灾月拨",
            "项目经费": "项目月拨",
            "协饷": "协饷月拨",
        }.get(str(payload.get("grant_action") or "").strip(), "奉旨月拨")
        # #1260：引擎确定性拨帑建项按定义旨内，显式留 beyond_intent=0（禁捏造旗值）。
        created = self.create_fiscal_item(
            f"奉旨月拨{int(dossier_id)}",
            account,
            "expense",
            display,
            int(amount),
            note=str(payload.get("reason") or text or display)[:240],
            origin_ref=f"dossier:{int(dossier_id)}",
            turn=int(state.turn),
            beyond_intent=0,
            commit=False,
        )
        if not created:
            raise ValueError("拨帑常项科目未能建项")
        return created

    def _apply_grant_honorific_effect(
        self, state: GameState, row, payload: Dict[str, object], dossier_id: int,
    ) -> None:
        """#518 interim：加衔/荫叙只落叙事开放标签，不改主官职。"""
        target = str(
            payload.get("target_id") or payload.get("name") or row.get("target_id") or ""
        ).strip()
        action = str(payload.get("grant_action") or "").strip()
        if not target or action not in {"加衔", "荫叙"}:
            raise ValueError("恩赏案卷缺少加衔/荫叙目标")
        origin_ref = f"dossier:{int(dossier_id)}"
        self.record_person_log(
            state, target, action,
            payload_summary="加衔示恩" if action == "加衔" else "荫叙示恩",
            source="grant_allocation", origin_ref=origin_ref, commit=False,
        )

    def create_decree_dossier(
        self,
        state: GameState,
        *,
        action_type: str,
        decree_text: str,
        target_kind: str = "",
        target_id: object = "",
        executor_kind: str = "",
        executor_id: object = "",
        source_chat_turn_id: int = 0,
        pending_action_id: int = 0,
        directive_id: int = 0,
        secret_order_id: Optional[int] = None,
        payload: Optional[Dict[str, object]] = None,
        status: str = "proposed",
        due_turn: int = 0,
        extension: Optional[Dict[str, object]] = None,
        participants: Optional[Iterable[object]] = None,
        commit: bool = True,
        _issued_secret_order: bool = False,
        region_id: str = "",
    ) -> int:
        """在成案点落一条独立案卷；幂等键只使用真实 (>0) 来源 id。

        #654：int ABI 给非 directive 消费者，直落单行内核；不经 locality oracle。
        属地行只来自 r5 三路 create_decree_dossiers 的 region 目标解析。
        """
        return self._create_decree_dossier_row(
            state,
            action_type=action_type,
            decree_text=decree_text,
            target_kind=target_kind,
            target_id=target_id,
            executor_kind=executor_kind,
            executor_id=executor_id,
            source_chat_turn_id=source_chat_turn_id,
            pending_action_id=pending_action_id,
            directive_id=directive_id,
            secret_order_id=secret_order_id,
            payload=payload,
            status=status,
            due_turn=due_turn,
            extension=extension,
            participants=participants,
            commit=commit,
            _issued_secret_order=_issued_secret_order,
            region_id=str(region_id or ""),
        )

    def create_decree_dossiers(
        self,
        state: GameState,
        *,
        action_type: str,
        decree_text: str,
        target_kind: str = "",
        target_id: object = "",
        executor_kind: str = "",
        executor_id: object = "",
        source_chat_turn_id: int = 0,
        pending_action_id: int = 0,
        directive_id: int = 0,
        secret_order_id: Optional[int] = None,
        payload: Optional[Dict[str, object]] = None,
        status: str = "proposed",
        due_turn: int = 0,
        extension: Optional[Dict[str, object]] = None,
        participants: Optional[Iterable[object]] = None,
        commit: bool = True,
        _issued_secret_order: bool = False,
    ) -> List[int]:
        """#654 批量成案 ABI：Plan → Validate-all → Write-once。

        #1778 决定 4：全国政令也是一份案卷，不按省拆——oracle 只对 region 目标
        给出属地行，其余（含 national）单行 region_id=''；与 create_decree_dossier
        共享单行内核。契约错抛 ValueError；复合键按 (source, region_id) 查补。
        """
        owns = self.owns_transaction()
        from ming_sim.execution_pressure import resolve_dossier_region_ids
        from ming_sim.executor_routing import (
            require_execution_lead_or_raise,
            resolve_lead_executors,
        )

        payload_map = dict(payload or {})
        # target_* 以行级参数为准并入 payload，供 oracle 读取
        if target_kind and not str(payload_map.get("target_kind") or "").strip():
            payload_map["target_kind"] = str(target_kind).strip()
        if target_id not in (None, "") and not str(payload_map.get("target_id") or "").strip():
            payload_map["target_id"] = str(target_id).strip()
        if not str(payload_map.get("dossier_action_type") or "").strip():
            payload_map["dossier_action_type"] = str(action_type or "").strip()

        # 密令不 fan-out；既有行整批返回
        if secret_order_id is not None:
            region_ids = [""]
            existing = self.dossiers.ids_for_secret_order(int(secret_order_id))
            if existing:
                return existing
        else:
            regions_content = getattr(self.content, "regions", None) if self.content else None
            # appointment 等历史行级 target_kind=person：仅 oracle 视作 character，不改 durable 载荷
            oracle_payload = dict(payload_map)
            if str(oracle_payload.get("target_kind") or "").strip() == "person":
                oracle_payload["target_kind"] = "character"
            region_ids = resolve_dossier_region_ids(
                self.conn,
                payload=oracle_payload,
                regions_content=regions_content,
            )

        # 点将名单：与单行内核同序归一 assignee 别名 / 旧式 executor 迁入，再判 named
        canonical_assignee = str(payload_map.get("assignee_id") or "").strip()
        if not canonical_assignee:
            canonical_assignee = str(payload_map.get("assignee") or "").strip()
        if canonical_assignee:
            from ming_sim.session import _find_existing_minister
            content = self.content
            canonical_assignee = (
                _find_existing_minister(content, canonical_assignee, self) or ""
                if content is not None else ""
            )
        if canonical_assignee:
            payload_map["assignee_id"] = canonical_assignee
        else:
            payload_map.pop("assignee_id", None)
        payload_map.pop("assignee", None)

        base_roster_source = participants
        if base_roster_source is None:
            base_roster_source = (
                payload_map.get("participant_roster")
                or payload_map.get("participants")
            )
        base_roster = self._normalize_participant_roster(
            base_roster_source, strict_structured=True,
        )
        has_canonical_lead = any(item.get("tier") == "主办" for item in base_roster)
        action_key = str(action_type or "").strip()
        if (
            action_key in {"assignment", "military_order"}
            and not canonical_assignee
            and not has_canonical_lead
            and str(executor_kind or "").strip() in {"", "character"}
            and str(executor_id or "").strip()
        ):
            base_roster.append({
                "character_id": str(executor_id).strip(), "tier": "主办",
                "role": "", "delegator_id": None,
            })
            base_roster = self._normalize_participant_roster(
                base_roster, strict_structured=True,
            )
        named_leads = [
            str(item.get("character_id") or "").strip()
            for item in base_roster
            if item.get("tier") == "主办"
            and str(item.get("character_id") or "").strip()
            and not str(item.get("delegator_id") or "").strip()
        ]
        if not named_leads and canonical_assignee:
            named_leads = [canonical_assignee]

        # ① 完整逐省 plan（零写库）
        plan: List[Dict[str, object]] = []
        for rid in region_ids:
            row_payload = dict(payload_map)
            row_participants = list(base_roster)
            row_executor_kind = str(executor_kind or "")
            row_executor_id = executor_id
            row_extension = dict(extension or {})
            if named_leads:
                existing_names = {
                    str(i.get("character_id") or "").strip()
                    for i in row_participants if i.get("tier") == "主办"
                }
                for lead in named_leads:
                    if lead not in existing_names:
                        row_participants.append({
                            "character_id": lead, "tier": "主办",
                            "role": "", "delegator_id": None,
                        })
                        existing_names.add(lead)
                # 与 duty-route 对称：0053 首名主办同步写 executor_*（#654 / ADR 0117）
                row_executor_kind = "character"
                row_executor_id = str(named_leads[0])
                route: Dict[str, object] = {
                    "coverage": None, "route": "named",
                    "leads": list(named_leads), "signal": None,
                }
            else:
                # 0117 ① 任免执行主体＝被任命者本人；其余无点将即空 leads。
                # #1778 决定 3：代码不按职司表配人（那条兜底已随本票删除）。
                route = resolve_lead_executors(
                    action_type=action_type,
                    target_id=str(target_id or row_payload.get("target_id") or ""),
                    payload=row_payload,
                    participant_roster=row_participants,
                )
                # #1778 乙：multi_month unassigned 不得静默成案（与单行共 require_*）。
                require_execution_lead_or_raise(route)
                for lead in route.get("leads") or []:
                    row_participants.append({
                        "character_id": str(lead), "tier": "主办",
                        "role": "", "delegator_id": None,
                    })
                if route.get("leads"):
                    row_executor_kind = "character"
                    row_executor_id = str(route["leads"][0])
                signal = route.get("signal")
                if signal is not None and "execution_signal" not in row_extension:
                    row_extension["execution_signal"] = signal
            plan.append({
                "region_id": str(rid or ""),
                "route": route,
                "participants": row_participants,
                "executor_kind": row_executor_kind,
                "executor_id": row_executor_id,
                "payload": row_payload,
                "extension": row_extension,
            })

        # ② 全量验证：校验名单引用（写库前）；失败上抛由三路成案点各自终态处理
        for entry in plan:
            roster = self._normalize_participant_roster(
                entry["participants"], strict_structured=True,
            )
            self._validate_participant_roster_references(roster)
            self._validate_dossier_delegations(roster)
            entry["participants"] = roster

        # ③ 复合键逐 (source, region_id) 查补（删「任一既存即返回」）
        existing_by_region: Dict[str, int] = {}
        if secret_order_id is None and (
            int(directive_id or 0) > 0 or int(pending_action_id or 0) > 0
        ):
            existing_by_region = self.dossiers.first_id_by_region(
                directive_id=int(directive_id or 0),
                pending_action_id=int(pending_action_id or 0),
            )

        # ④ 一次写入：仅 missing；commit 一次；返回 existing∪new 确定序
        new_ids_by_region: Dict[str, int] = {}
        for entry in plan:
            rid = str(entry["region_id"] or "")
            if rid in existing_by_region:
                self._attach_affair_from_payload(
                    state, entry["payload"], existing_by_region[rid],  # type: ignore[arg-type]
                )
                continue
            did = self._create_decree_dossier_row(
                state,
                action_type=action_type,
                decree_text=decree_text,
                target_kind=target_kind or str(entry["payload"].get("target_kind") or ""),  # type: ignore[union-attr]
                target_id=(
                    target_id if target_id not in (None, "")
                    else entry["payload"].get("target_id") or ""  # type: ignore[union-attr]
                ),
                executor_kind=str(entry.get("executor_kind") or ""),
                executor_id=entry.get("executor_id"),
                source_chat_turn_id=source_chat_turn_id,
                pending_action_id=pending_action_id,
                directive_id=directive_id,
                secret_order_id=secret_order_id,
                payload=entry["payload"],  # type: ignore[arg-type]
                status=status,
                due_turn=due_turn,
                extension=entry.get("extension") or None,  # type: ignore[arg-type]
                participants=entry["participants"],  # type: ignore[arg-type]
                commit=False,
                _issued_secret_order=_issued_secret_order,
                region_id=rid,
                _skip_lead_route=True,
            )
            new_ids_by_region[rid] = int(did)

        self._commit_dossier_write(commit, owns)

        merged: Dict[str, int] = dict(existing_by_region)
        merged.update(new_ids_by_region)
        # 按 plan 的 region 序，同 region 以 id 稳定
        ordered: List[int] = []
        seen_ids: set = set()
        for entry in plan:
            rid = str(entry["region_id"] or "")
            did = merged.get(rid)
            if did is not None and did not in seen_ids:
                ordered.append(int(did))
                seen_ids.add(int(did))
        # 若有既有多余 region 行（期望集外），按 region_id,id 附于末
        extras = sorted(
            (
                (rid, did) for rid, did in existing_by_region.items()
                if did not in seen_ids
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _, did in extras:
            ordered.append(int(did))
        return ordered

    def _resolve_affair_id_from_payload(
        self, state: GameState, payload: Mapping[str, object] | None,
    ) -> int:
        """Typed 拆旨声明 → 事务 id；无声明不自建；本阶段不消费了结。"""
        from ming_sim.entities.affair import (
            ATTACH_BIRTH,
            UnauthorizedAffairOriginRef,
            declaration_from_payload,
        )
        declaration = declaration_from_payload(payload, allowed=ATTACH_BIRTH)
        if declaration is None:
            return 0
        frozen = getattr(self, "_batch_frozen_open_affair_ids", None)
        if (
            declaration.get("attach") == "existing"
            and frozen is not None
            and int(declaration["affair_id"]) not in frozen
        ):
            raise UnauthorizedAffairOriginRef()
        affair_id = int(self.affairs.resolve_declaration(
            declaration,
            year=int(state.year),
            period=int(state.period),
            turn=int(state.turn),
            allowed=ATTACH_BIRTH,
        ))
        working = getattr(self, "_batch_authorized_open_affair_ids", None)
        if declaration.get("attach") == "new" and working is not None:
            working.add(affair_id)
        return affair_id

    def _attach_affair_from_payload(
        self, state: GameState, payload: Mapping[str, object] | None, dossier_id: int,
    ) -> None:
        from ming_sim.entities.affair import declaration_from_payload
        declaration = declaration_from_payload(payload)
        if declaration is None:
            return
        authority = (
            getattr(self, "_batch_frozen_open_affair_ids", None)
            if declaration.get("attach") == "existing"
            else getattr(self, "_batch_authorized_open_affair_ids", None)
        )
        self.affairs.attach_from_declaration(
            "decree_dossiers",
            int(dossier_id),
            declaration,
            year=int(state.year),
            period=int(state.period),
            turn=int(state.turn),
            authorized_ids=authority,
        )

    def _create_decree_dossier_row(
        self,
        state: GameState,
        *,
        action_type: str,
        decree_text: str,
        target_kind: str = "",
        target_id: object = "",
        executor_kind: str = "",
        executor_id: object = "",
        source_chat_turn_id: int = 0,
        pending_action_id: int = 0,
        directive_id: int = 0,
        secret_order_id: Optional[int] = None,
        payload: Optional[Dict[str, object]] = None,
        status: str = "proposed",
        due_turn: int = 0,
        extension: Optional[Dict[str, object]] = None,
        participants: Optional[Iterable[object]] = None,
        commit: bool = True,
        _issued_secret_order: bool = False,
        region_id: str = "",
        _skip_lead_route: bool = False,
    ) -> int:
        """单行案卷内核（#654 region_id）；create_decree_dossier(s) 共用。"""
        owns = self.owns_transaction()
        action = str(action_type or "").strip()
        text = str(decree_text or "")
        normalized_payload = dict(payload or {})
        # #1565：公开成案/旧入口只有 decree_text 时，正文无损承接到唯一正文槽 payload.text；
        # 不回填为题名，不建平行 body 真源。
        if not str(normalized_payload.get("text") or "").strip() and text:
            normalized_payload["text"] = text
        canonical_assignee = str(normalized_payload.get("assignee_id") or "").strip()
        if not canonical_assignee:
            canonical_assignee = str(normalized_payload.get("assignee") or "").strip()
        if canonical_assignee:
            normalized_payload["assignee_id"] = canonical_assignee
        normalized_payload.pop("assignee", None)
        normalized_payload["mode"] = normalize_dossier_mode(
            normalized_payload["mode"] if "mode" in normalized_payload else "ordinary"
        )
        if action == "appointment":
            from ming_sim.office_rank import appointment_break_rank
            normalized_payload["任别"] = appointment_tenure_from(normalized_payload)
            normalized_payload.pop("appointment_tenure", None)
            normalized_payload["break_rank"] = appointment_break_rank(
                self,
                normalized_payload.get("name") or target_id,
                normalized_payload.get("office") or normalized_payload.get("new_office"),
                normalized_payload.get("office_type")
                or normalized_payload.get("new_office_type"),
            )
        if not action or not text:
            raise ValueError("案卷 action_type/decree_text 不能为空")
        if action not in self._DOSSIER_ACTION_TYPES:
            raise ValueError(f"案卷 action_type 非法：{action}")
        # #653 / ADR 0090：偿还序 override 旨载荷成案点先验（fail-loud 拒整道旨）——
        # 非法键形/值域/幻影 region 在收夜即响亮拒，不等到颁布关才炸。与物化点共
        # prepare_pay_order_entries 同一验形（禁两套漂移）。
        if action == "pay_order_override":
            from ming_sim.pay_order import prepare_pay_order_entries
            entries = normalized_payload.get("entries")
            if not isinstance(entries, list) or not entries:
                raise ValueError("pay_order_override 案卷 payload.entries 须为非空列表")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError(f"pay_order_override entry 非字典：{entry!r}")
            prepare_pay_order_entries(self, entries)
        # #1503：拨饷类成案即规范化补饷载荷（缺字段 fail-loud）。
        if action == "grant_allocation":
            # target_* 可能只在行级参数、尚未入 payload — 先并入再校验。
            if not str(normalized_payload.get("target_kind") or "").strip() and target_kind:
                normalized_payload["target_kind"] = str(target_kind).strip()
            if not str(normalized_payload.get("target_id") or "").strip() and target_id:
                normalized_payload["target_id"] = str(target_id).strip()
            normalized_payload = self._normalize_army_pay_grant_payload(normalized_payload)
        canonical_payload = normalized_payload
        # Staging validates against the same policy later consumed by review,
        # simulation and materialization.  In particular, callers cannot invent
        # a terminal/immediate surface for an action whose canonical surface is
        # in-transit (grant_allocation is the sole payload-selected surface).
        policy = dossier_action_policy(action, canonical_payload)
        supplied_surface = str(canonical_payload.get("execution_surface") or "").strip()
        if action != "grant_allocation" and supplied_surface and supplied_surface != policy["execution_surface"]:
            raise ValueError(f"{action} execution_surface 与案卷动作策略不符")
        canonical_target_kind = str(
            target_kind or canonical_payload.get("target_kind") or ""
        ).strip()
        canonical_target_id = str(
            target_id or canonical_payload.get("target_id") or ""
        ).strip()
        immediate_allocation = (
            action == "grant_allocation" and policy["effect_owner"] == "immediate"
        )
        allocation_amount = 0
        if immediate_allocation:
            allocation_amount = strict_int(
                canonical_payload.get("amount"), accept_numeric_strings=False,
            )
            account = str(canonical_payload.get("account") or "").strip()
            if allocation_amount <= 0 or account != "内库":
                raise ValueError("内批拨帑案卷须含正数 amount 与内库 account")
        if not canonical_target_kind or not canonical_target_id:
            raise ValueError("案卷 target_kind/target_id 必须完整")
        if status not in DOSSIER_STATUSES:
            raise ValueError(f"案卷 status 非法：{status}")
        if status != "proposed" and not (
            _issued_secret_order and action == "secret_order" and status == "promulgated"
        ):
            raise ValueError("案卷公共成案点只能从 proposed 起步")
        # #654 region_id 写侧白名单：'' 或现存 regions.id
        rid = str(region_id or "").strip()
        if rid:
            ok = RegionStore(self.conn).read_assert_commission_grant_target_exists((rid,))
            if ok is None:
                raise ValueError(f"案卷 region_id 非法：{rid!r}")
        region_id = rid

        # 幂等键只使用真实 (>0) 来源 id；三类键的查法归案卷 store（ADR 0151）。
        existing_id = self.dossiers.find_existing_for_source(
            secret_order_id=secret_order_id, directive_id=int(directive_id or 0),
            pending_action_id=int(pending_action_id or 0), action=action,
            region_id=region_id,
        )
        if existing_id is not None:
            self._attach_affair_from_payload(state, canonical_payload, existing_id)
            return existing_id
        source_turn_id = int(source_chat_turn_id or 0)
        if source_turn_id <= 0 and int(pending_action_id or 0) > 0:
            origin = self.conn.execute(
                """
                SELECT chat_turn_id FROM chat_turn_rollback_items
                WHERE target_table='pending_actions' AND target_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (str(int(pending_action_id)),),
            ).fetchone()
            if origin is not None:
                source_turn_id = int(origin["chat_turn_id"])
        roster_source = participants
        if roster_source is None:
            roster_source = (
                canonical_payload.get("participant_roster")
                or canonical_payload.get("participants")
            )
        roster = self._normalize_participant_roster(roster_source, strict_structured=True)
        has_canonical_lead = any(item.get("tier") == "主办" for item in roster)
        if (
            action in {"assignment", "military_order"}
            and not canonical_assignee
            and not has_canonical_lead
            and str(executor_kind or "").strip() in {"", "character"}
            and str(executor_id or "").strip()
        ):
            roster.append({
                "character_id": str(executor_id).strip(), "tier": "主办", "role": "",
                "delegator_id": None,
            })
        self._validate_participant_roster_references(roster)
        self._validate_dossier_delegations(roster)

        # #721：承办路由属于 canonical 成案核，首次 INSERT 前只补内存 roster，
        # 最终仍由同一 INSERT 写一次；不存在成案后 JSON/UPDATE 平行写口。
        # #654 bulk 层已 Plan/Validate 并逐省 resolve，此处 _skip_lead_route 避免重复；
        # 单行直落路径仍走 resolver，并传 region_id 接缝。
        from ming_sim.executor_routing import (
            require_execution_lead_or_raise,
            resolve_lead_executors,
        )
        if _skip_lead_route:
            route = {
                "coverage": None, "route": "pre_resolved",
                "leads": [], "signal": None,
            }
        else:
            route = resolve_lead_executors(
                action_type=action, target_id=canonical_target_id,
                payload=canonical_payload, participant_roster=roster,
            )
        existing_leads = {
            str(item.get("character_id") or "").strip()
            for item in roster if item.get("tier") == "主办"
        }
        if not _skip_lead_route:
            require_execution_lead_or_raise(route)
        for lead in route["leads"]:
            if lead in existing_leads:
                continue
            # 任命候选可在成案时尚未进入 characters；0053 的人物外键真源
            # 不容为承办路由放宽。当前法源下只填已在册者，待有 durable 的
            # future-person 键形后再覆盖新臣任命，禁止另造平行身份轴。
            if action in {"appointment", "acting_appointment"} and CharacterStore(self.conn).read_assert_characters_exist((lead,)) is None:
                continue
            roster.append({
                "character_id": lead, "tier": "主办", "role": "",
                "delegator_id": None,
            })
            existing_leads.add(lead)
        # 自动补入者与调用方名单共走 0053 的引用、委派链单一校验口。
        roster = self._normalize_participant_roster(roster, strict_structured=True)
        self._validate_participant_roster_references(roster)
        self._validate_dossier_delegations(roster)

        durable_extension = dict(extension or {})
        signal = route.get("signal")
        if signal is not None:
            if "execution_signal" in durable_extension:
                raise ValueError("案卷 extension execution_signal 冲突")
            durable_extension["execution_signal"] = signal
        affair_id = self._resolve_affair_id_from_payload(state, canonical_payload)
        lead_names = [
            str(item.get("character_id") or "") for item in roster
            if item.get("tier") == "主办"
        ]
        archive_keys: set[str] = set()
        if action != "secret_order":
            for lead_name in lead_names:
                lead = CharacterStore(self.conn).read_list_referenceable_dossiers((lead_name,))
                if lead is None:
                    continue
                key = self._office_archive_key(
                    lead["office"], lead["office_type"],
                    location=lead["location"] if "location" in lead.keys() else "",
                    character_name=lead_name,
                )
                if key:
                    archive_keys.add(key)
        # 落库走案卷 store 的唯一 INSERT 写口（ADR 0151）；成案点的校验与
        # 效果物化仍归 settlement 侧，store 不反向调 GameDB。
        dossier_id = self.dossiers.insert_row(
            action=action,
            target_kind=canonical_target_kind,
            target_id=canonical_target_id,
            executor_kind=str(executor_kind or ""),
            executor_id=str(executor_id or ""),
            source_chat_turn_id=source_turn_id,
            pending_action_id=int(pending_action_id or 0),
            directive_id=int(directive_id or 0),
            secret_order_id=secret_order_id,
            region_id=region_id,
            decree_text=text,
            payload=canonical_payload,
            status=status,
            due_turn=due_turn,
            extension=durable_extension,
            participant_roster=roster,
            office_archive_keys=sorted(archive_keys),
            turn=int(state.turn), year=int(state.year), period=int(state.period),
            affair_id=int(affair_id),
        )
        if immediate_allocation:
            if self._grant_allocation_is_monthly(canonical_payload):
                self._create_grant_fiscal_item(
                    state, canonical_payload, dossier_id,
                    account="内库", amount=allocation_amount, text=text,
                )
            elif self._is_army_pay_grant_payload(canonical_payload):
                # #1503：内帑拨饷成案即扣库+销欠（豁免颁布关仍走补饷缝）。
                row_proxy = {
                    "decree_text": text,
                    "target_kind": canonical_target_kind,
                    "target_id": canonical_target_id,
                }
                self._apply_army_pay_grant_effect(
                    state, row_proxy, canonical_payload, dossier_id,
                )
            else:
                self.record_issue_economy_move(
                    state, "内库", -allocation_amount,
                    str(canonical_payload.get("category") or "奉旨拨帑"),
                    str(canonical_payload.get("reason") or text),
                    purpose=str(canonical_payload.get("purpose") or "") or None,
                    target_kind=canonical_target_kind, target_id=canonical_target_id,
                    origin_ref=f"dossier:{dossier_id}", commit=False,
                )
        if roster and action != "secret_order":
            self.register_character_knowledge_source(
                state, roster, "assignment", "旨意案卷", text,
                source_id=f"decree_dossier:{dossier_id}", commit=False,
            )
        self._commit_dossier_write(commit, owns)
        # 拒收镜像归外层 RejectionCollector owner（0150-D2；本核不自建不自镜像）。
        return dossier_id

    @staticmethod
    def _validate_dossier_delegations(roster: Iterable[Dict[str, object]]) -> None:
        entries = list(roster)
        responsible = {
            str(item.get("character_id") or "") for item in entries
            if item.get("tier") in {"主办", "协办"}
        }
        for item in entries:
            delegator = str(item.get("delegator_id") or "")
            character = str(item.get("character_id") or "")
            if delegator and (delegator == character or delegator not in responsible):
                raise ValueError("委派人须为同案主办/协办且不得自委派")

    def append_decree_dossier_participants(
        self, dossier_id: int, participants: Iterable[object], *,
        state: Optional[GameState] = None, commit: bool = True,
    ) -> List[Dict[str, object]]:
        """Append ADR 0053 roster entries without replacing durable members."""
        owns = self.owns_transaction()
        row = self.dossiers.participant_row(int(dossier_id))
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        existing_raw = load_stored_list(row["participant_roster"], label='participant_roster')
        if not isinstance(existing_raw, list):
            raise ValueError("participant_roster 不是名单")
        existing = self._normalize_participant_roster(existing_raw)
        additions = self._normalize_participant_roster(participants, strict_structured=True)
        self._validate_participant_roster_references(additions)
        by_character = {str(item["character_id"]): item for item in existing}
        added: List[Dict[str, object]] = []
        for item in additions:
            character_id = str(item["character_id"])
            prior = by_character.get(character_id)
            if prior is not None:
                if prior != item:
                    raise ValueError(f"参与人物已在案且机械档不同：{character_id}")
                continue
            by_character[character_id] = item
            added.append(item)
        merged = existing + added
        self._validate_dossier_delegations(merged)
        self._validate_participant_roster_references(merged)
        if added:
            archive_keys: set[str] = set()
            raw_keys_row = self.dossiers.archive_keys_row(int(dossier_id))
            raw_keys = raw_keys_row["office_archive_keys"] if raw_keys_row is not None else None
            parsed_keys = load_stored_list(raw_keys, label="office_archive_keys")
            archive_keys = {str(item) for item in parsed_keys}
            if str(row["action_type"] or "") != "secret_order":
                for item in added:
                    if str(item.get("tier") or "") != "主办":
                        continue
                    lead_name = str(item.get("character_id") or "")
                    lead = CharacterStore(self.conn).read_list_referenceable_dossiers((lead_name,))
                    if lead is None:
                        continue
                    key = self._office_archive_key(
                        lead["office"], lead["office_type"],
                        location=lead["location"] if "location" in lead.keys() else "",
                        character_name=lead_name,
                    )
                    if key:
                        archive_keys.add(key)
            self.dossiers.set_participants_and_archive(
                int(dossier_id), merged, sorted(archive_keys), commit=False,
            )
            if state is not None and str(row["action_type"] or "") != "secret_order":
                for item in added:
                    identity = ":".join(str(item.get(key) or "-") for key in (
                        "character_id", "tier", "role", "delegator_id",
                    ))
                    self.register_character_knowledge_source(
                        state, [item], "assignment", "旨意案卷追加参与",
                        str(row["decree_text"] or ""),
                        source_id=f"dossier:{int(dossier_id)}:participant:{identity}",
                        commit=False,
                    )
        self._commit_dossier_write(commit, owns)
        return added

    def _append_midzhi_stigma(
        self, dossier_id: int, *, decision: str, turn: int, commit: bool = True,
    ) -> None:
        """Append one marker per dossier semantic midzhi event, regardless of replay turn."""
        owns = self.owns_transaction()
        marker_fields = {
            "rejected": ("predeclared", "rejected"),
            "promulgated": ("predeclared", "promulgated"),
            "force_promulgated": ("rescript", "force_promulgated"),
        }
        if decision not in marker_fields:
            raise ValueError(f"中旨 stigma 判决非法：{decision}")
        row = self.dossiers.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        reason, source_action = marker_fields[decision]
        marker = {
            "kind": "midzhi", "reason": reason, "turn": int(turn),
            "source_action": source_action,
        }
        stigma = list(row["stigma"])
        event_key = (marker["kind"], marker["reason"])
        if not any(
            (item.get("kind"), item.get("reason")) == event_key
            for item in stigma if isinstance(item, dict)
        ):
            stigma.append(marker)
            self.dossiers.set_stigma(int(dossier_id), stigma, commit=False)
        self._commit_dossier_write(commit, owns)

    # Central yamen archive identity: offices.json allowed_types minus non-yamen
    # kinds. Never union characters.office_type (外臣/内臣/宗藩/未仕 would leak).
    _NON_CENTRAL_ARCHIVE_OFFICE_TYPES = frozenset({
        "地方", "督抚", "边镇", "内廷", "后宫",
        "生员", "乡绅", "富商", "布衣", "流寇", "待铨",
    })
    _LOCAL_ARCHIVE_OFFICE_TYPES = frozenset({"地方", "督抚", "边镇"})

    def _require_local_office_region(
        self,
        *,
        name: object,
        office: object,
        office_type: object,
        region_id: object = "",
    ) -> str:
        """Single typed 任所 resolver for appointment writes.

        - Non-local office types store empty seat (no field required).
        - Explicit payload/dossier region_id is consumed as-is (known → seat;
          unknown → missing_ref). Never inferred from title/location/other seat.
        - Same person + same local office identity continuing as no-op / 任别 /
          replay / 起复 reuses character_offices.region_id (may be empty).
        - Truly new or reassigned local seats without a typed region this call
          → missing_field.
        """
        kind = str(office_type or "").strip()
        if kind not in self._LOCAL_ARCHIVE_OFFICE_TYPES:
            return ""
        seat = str(region_id or "").strip()
        if seat:
            known = RegionStore(self.conn).read_assert_commission_grant_target_exists((seat,))
            if known is None:
                raise OfficeAppointmentRejection(
                    f"unknown region_id {seat!r} for office appointment",
                    category="missing_ref",
                )
            return seat
        # No typed region this call — only continue an existing same-office seat.
        person = str(name or "").strip()
        title = normalize_office(str(office or ""))
        if person and title and self._table_exists("character_offices"):
            row = CharacterStore(self.conn).read_require_local_office_region((person,))
            if row is not None and normalize_office(str(row["office_title"] or "")) == title:
                return str(row["region_id"] or "").strip()
        raise OfficeAppointmentRejection(
            f"地方任命缺 region_id 任所：{name} → {office}（{kind}）",
            category="missing_field",
        )

    def _central_archive_office_types(self) -> frozenset[str]:
        catalog = {
            str(kind).strip()
            for kind in (_offices_table().get("allowed_types") or ())
            if str(kind).strip()
        }
        return frozenset(catalog - self._NON_CENTRAL_ARCHIVE_OFFICE_TYPES)

    def character_office_region(self, character_name: object) -> str:
        """Jurisdiction of the character's current appointment (一次任职)."""
        name = str(character_name or "").strip()
        if not name or not hasattr(self, "conn") or not self._table_exists("character_offices"):
            return ""
        row = CharacterStore(self.conn).read_character_office_region((name,))
        return str(row["region_id"] or "").strip() if row is not None else ""

    def project_office_identity(
        self,
        office: object,
        office_type: object,
        *,
        location: object = "",
        region_id: object = "",
        character_name: object = "",
    ) -> Dict[str, object]:
        """Authoritative office → archive_key + region_ids.

        Shared by character materials scope and decree-dossier succession.
        Local jurisdiction binds to one appointment/seat identity: prefer the
        caller's typed ``region_id``, else the holder's ``character_offices.region_id``.
        Never derive from Character.location, free-text titles, or office_slots
        (same bare 巡抚 in two provinces must not collide). ``location`` remains
        accepted for call-site stability and is ignored.
        """
        del location  # physical presence ≠ posting jurisdiction
        title = normalize_office(str(office or ""))
        kind = str(office_type or "").strip()

        if kind and kind in self._central_archive_office_types():
            return {"archive_key": f"central:{kind}", "region_ids": ()}

        if kind not in self._LOCAL_ARCHIVE_OFFICE_TYPES:
            return {"archive_key": "", "region_ids": ()}

        rid = str(region_id or "").strip()
        if not rid and character_name:
            rid = self.character_office_region(character_name)

        region_ids: tuple[str, ...] = (rid,) if rid else ()
        archive_key = ""
        if title and rid:
            archive_key = f"slot:{title}@{rid}"
        return {"archive_key": archive_key, "region_ids": region_ids}

    def _office_archive_key(
        self,
        office: object,
        office_type: object,
        *,
        location: object = "",
        region_id: object = "",
        character_name: object = "",
    ) -> str:
        """Typed archive identity via :meth:`project_office_identity`."""
        projected = self.project_office_identity(
            office,
            office_type,
            location=location,
            region_id=region_id,
            character_name=character_name,
        )
        return str(projected.get("archive_key") or "")

    def list_referenceable_dossiers(
        self, character_name: str, current_turn: int,
    ) -> List[Dict[str, object]]:
        """Project candidates from the same durable character-knowledge truth."""
        from ming_sim.knowledge import knowledge_row_visible_to

        name = str(character_name or "")
        known_secret_ids: set[int] = set()
        known_dossier_ids: set[int] = set()
        knowledge_events = self._character_knowledge_events(name, include_exclusions=True)
        if name:
            knowledge_events += self._character_knowledge_events("", include_exclusions=True)
        for event in knowledge_events:
            if not knowledge_row_visible_to(self, event, name):
                continue
            source_id = str(event.get("source_id") or "")
            match = re.match(r"secret_order_(?:brief|disclosure):(\d+)(?::|$)", source_id)
            if match:
                known_secret_ids.add(int(match.group(1)))
            dossier_match = re.match(r"(?:decree_)?dossier:(\d+)(?::|$)", source_id)
            if dossier_match:
                known_dossier_ids.add(int(dossier_match.group(1)))
        office_row = CharacterStore(self.conn).read_list_referenceable_dossiers((name,))
        reader_archive_key = (
            self._office_archive_key(
                office_row["office"], office_row["office_type"],
                location=office_row["location"] if "location" in office_row.keys() else "",
                character_name=name,
            )
            if office_row is not None else ""
        )
        rows = self.dossiers.referenceable_rows(int(current_turn))
        visible: List[Dict[str, object]] = []
        for row in rows:
            admitted = (
                row["secret_order_id"] is None
                and (
                    str(row["promulgation_decision"] or "") == "promulgated"
                    or bool(row["was_force_promulgated"])
                    or int(row["id"]) in known_dossier_ids
                    or reader_archive_key in set(
                        load_stored_list(row["office_archive_keys"], label='office_archive_keys')
                    )
                )
            ) or (
                row["secret_order_id"] is not None
                and int(row["secret_order_id"]) in known_secret_ids
            )
            if not admitted:
                continue
            # Same hydrate contract as get/list decree rows (ADR 0005: fail loud).
            item = hydrate_dossier_row(row)
            item["was_force_promulgated"] = bool(row["was_force_promulgated"])
            visible.append(item)
        return visible

    def list_commitments_for_dossier(self, dossier_id: int) -> List[Dict[str, object]]:
        """承诺只从 issue.origin_ref 反查；案卷表不复制 commitment id。"""
        rows = IssueStore(self.conn).read_list_commitments_for_dossier((f"dossier:{int(dossier_id)}",))
        return [dict(row) for row in rows]

    def resolve_commitment_origin_ref(
        self, state: GameState, supplied_ref: str, *, origin_kind: str = "",
    ) -> str:
        """承诺创建写端：有本回合已颁案卷时，origin 单向归一到案卷。"""
        supplied = str(supplied_ref or "").strip()
        if supplied.startswith("dossier:"):
            try:
                dossier_id = int(supplied.split(":", 1)[1])
            except (TypeError, ValueError):
                raise ValueError("commitment origin_ref 案卷 id 非法")
            if self.dossiers.get(dossier_id) is None:
                raise ValueError("commitment origin_ref 指向不存在案卷")
            return supplied
        from ming_sim.materials import SECRET_ORDER_ORIGIN_PREFIX, is_secret_order_origin

        if is_secret_order_origin(supplied):
            try:
                secret_order_id = int(supplied[len(SECRET_ORDER_ORIGIN_PREFIX):])
            except (TypeError, ValueError):
                raise ValueError("commitment origin_ref 密令 id 非法")
            dossier = self.dossiers.get_for_secret_order(secret_order_id)
            if dossier is None:
                raise ValueError("commitment origin_ref 指向无案卷密令")
            return f"dossier:{int(dossier['id'])}"
        if str(origin_kind or "") == "decree":
            if self.dossiers.dossier_count_created_turn(int(state.turn)) > 0:
                raise ValueError(
                    "承诺 origin_ref 必须由产出它的明确案卷携带 dossier:<id>"
                )
        return supplied

    def record_dossier_decision(
        self, dossier_id: int, decision: str, *, reason: str = "",
        blocked_layer: str = "", legal_reason_code: str = "",
        primary_opponents: Optional[List[Dict[str, str]]] = None,
        gatekeeper_id: Optional[str] = None,
        criteria_snapshot: Optional[Dict[str, object]] = None,
        commit: bool = True,
    ) -> None:
        """颁布/批红组合态。rejected 与 hold 永不成为主链 status。"""
        owns = self.owns_transaction()
        if str(legal_reason_code or "").strip():
            raise ValueError("legal_reason_code 仅供尚未落地的依律集写入路径")
        decision = str(decision or "").strip()
        if decision not in {"promulgated", "rejected", "hold", "withdrawn"}:
            raise ValueError(f"案卷判决非法：{decision}")
        blocked_layer = str(blocked_layer or "")
        if blocked_layer not in PROMULGATION_BLOCKED_LAYERS:
            raise ValueError(f"颁布关口非法：{blocked_layer}")
        row = self.dossiers.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        slot_reason = str(reason or "")
        slot_legal_reason = str(legal_reason_code or "")
        if decision in {"hold", "withdrawn"}:
            if not blocked_layer:
                blocked_layer = str(row.get("promulgation_blocked_layer") or "")
            slot_reason = str(row.get("promulgation_reason") or "")
            slot_legal_reason = str(row.get("legal_reason_code") or "")
        turn_row = ReignStateStore(self.conn).read_record_dossier_decision()
        current_turn = int(turn_row["turn"] if turn_row else 0)
        if (
            decision in {"promulgated", "rejected"}
            and int(row.get("held_turn") or 0) > 0
            and current_turn <= int(row["held_turn"])
        ):
            raise ValueError("留中案卷只可在下月重判")
        if row["status"] != "proposed":
            raise ValueError("只有 proposed 案卷可写颁布/批红判决")
        if decision == "promulgated":
            status, promulgation, pending = "promulgated", "promulgated", 0
        elif decision == "rejected":
            status, promulgation, pending = "proposed", "rejected", 1
        elif decision == "hold":
            if row["promulgation_decision"] != "rejected" or not row["rescript_pending"]:
                raise ValueError("留中只可承接打回＋批红待抉择组合态")
            status, promulgation, pending = "proposed", "rejected", 0
        else:
            if row["promulgation_decision"] != "rejected" or not row["rescript_pending"]:
                raise ValueError("收回只可承接打回＋批红待抉择组合态")
            status, promulgation, pending = "closed", "rejected", 0
        held_turn = (
            current_turn
            if decision == "hold" else int(row.get("held_turn") or 0)
        )
        self.dossiers.set_promulgation(
            int(dossier_id), status=status, promulgation=promulgation,
            rescript_pending=pending, blocked_layer=blocked_layer,
            reason=slot_reason, legal_reason_code=slot_legal_reason,
            held_turn=held_turn, turn=current_turn,
        )
        self.dossiers.insert_decision(
            int(dossier_id), current_turn,
            decision=promulgation if decision != "hold" else "rejected",
            blocked_layer=blocked_layer,
            rescript_action=decision if decision in {"hold", "withdrawn"} else "",
            reason=str(reason or ""),
            legal_reason_code=slot_legal_reason,
            primary_opponents_json=safe_json_dumps(primary_opponents or []),
            gatekeeper_id=(
                str(gatekeeper_id).strip() if gatekeeper_id is not None else None
            ),
            criteria_snapshot_json=safe_json_dumps(criteria_snapshot or {}),
        )
        self._commit_dossier_write(commit, owns)

    def record_dossier_execution(
        self, dossier_id: int, outcome: str, note: str, turn: int, *,
        close: bool = True, commit: bool = True,
    ) -> None:
        owns = self.owns_transaction()
        row = self.dossiers.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        outcome = str(outcome or "").strip()
        if outcome not in DOSSIER_EXECUTION_OUTCOMES:
            raise ValueError(f"执行 outcome 非法：{outcome}")
        if outcome == "executing" and close:
            raise ValueError("executing 是非终态，必须以 close=False 记录")
        immediate = (
            row["status"] == "promulgated"
            and not has_execution_surface(row["action_type"], row["payload"])
        )
        if row["status"] != "executing" and not immediate:
            raise ValueError("执行格只能写入 executing 或无判定面已颁案卷")
        self.dossiers.set_execution(
            int(dossier_id), outcome=outcome, note=str(note or ""), turn=int(turn),
        )
        if close:
            self.dossiers.close(
                dossier_id,
                str(note or "") if outcome == "failed" else "",
                commit=False,
            )
        # #625：走样/变形/烂尾终值 → 空子暴露（与对账路统一：本 turn 稽核在场门）
        if outcome in {"degraded", "transformed", "failed"}:
            action_type = str(row.get("action_type") or "").strip()
            if (
                action_type in DOSSIER_ACTION_TYPES
                and self.dossiers.has_supervision_presence(int(dossier_id), int(turn))
            ):
                self.record_loophole_exposure(
                    int(dossier_id), int(turn), action_type, outcome,
                    commit=False,
                )
        self._commit_dossier_write(commit, owns)

    def apply_dossier_promulgation(
        self, state: GameState, dossier_id: int, decision: str, *,
        blocked_layer: str = "", reason: str = "", legal_reason_code: str = "",
        primary_opponents: Optional[List[Dict[str, str]]] = None,
        gatekeeper_id: Optional[str] = None,
        criteria_snapshot: Optional[Dict[str, object]] = None,
        content=None,
    ) -> None:
        """判决注入 seam：结构化载荷只在顺颁后从同一案卷物化。"""
        with atomic(self):
            row = self.dossiers.get(dossier_id)
            if row is None:
                raise KeyError(f"案卷不存在：{dossier_id}")
            predeclared_midzhi = row.get("mode") == "midzhi"
            if decision not in {"promulgated", "force_promulgated"}:
                self.record_dossier_decision(
                    dossier_id, decision, blocked_layer=blocked_layer,
                    reason=reason, legal_reason_code=legal_reason_code,
                    primary_opponents=primary_opponents,
                    gatekeeper_id=gatekeeper_id,
                    criteria_snapshot=criteria_snapshot, commit=False,
                )
                if predeclared_midzhi and decision == "rejected":
                    self._append_midzhi_stigma(
                        dossier_id, decision="rejected", turn=state.turn, commit=False,
                    )
                return
            if decision == "force_promulgated":
                turn_row = ReignStateStore(self.conn).read_record_dossier_decision()
                current_turn = int(turn_row["turn"] if turn_row else 0)
                if (
                    row["promulgation_decision"] != "rejected"
                    or row["status"] != "proposed"
                ):
                    raise ValueError("强颁只可承接同一打回/留中案卷")
                held_turn = int(row.get("held_turn") or 0)
                if held_turn > 0 and current_turn <= held_turn:
                    raise ValueError("留中案卷只可在下月重判或强颁")
                if not row["rescript_pending"]:
                    if held_turn > 0:
                        raise ValueError("留中案卷须先完成下月重判方可强颁")
                    raise ValueError("强颁只可承接首次打回或下月重判")
                # Evidence is a Judge verdict, never the player disposition row.
                # Ordinary force 须先校验 typed parties；midzhi 不猜派，跳过该证据链。
                if not predeclared_midzhi:
                    self._current_judge_affected_parties(dossier_id, current_turn)
                self.dossiers.force_promulgate(int(dossier_id))
                self.dossiers.insert_decision(
                    int(dossier_id), current_turn, decision="rejected",
                    blocked_layer="", rescript_action="force_promulgated",
                    reason="批红强颁", legal_reason_code="",
                    primary_opponents_json="[]", gatekeeper_id=None,
                    criteria_snapshot_json="{}",
                )
                # #657 §C.8：中旨当下不向派系扇出、不猜受影响派系（正式离心归 M12）。
                # 预声明 midzhi 打回只落 stigma；强颁只追加皇威。
                # Ordinary force 仍走 stigma + authority + typed parties。
                if not predeclared_midzhi:
                    self._append_midzhi_stigma(
                        dossier_id, decision="force_promulgated", turn=state.turn,
                        commit=False,
                    )
                self._apply_override_costs(
                    state, dossier_id, include_authority=True,
                    include_parties=not predeclared_midzhi,
                    stigma_reason="批红强颁", commit=False,
                )
            else:
                self.record_dossier_decision(
                    dossier_id, "promulgated", blocked_layer=blocked_layer,
                    reason=reason, legal_reason_code=legal_reason_code, commit=False,
                )
            if predeclared_midzhi and decision == "promulgated":
                self._append_midzhi_stigma(
                    dossier_id, decision="promulgated", turn=state.turn, commit=False,
                )
            payload = load_stored_object(row["payload_json"], label='payload_json')
            if not isinstance(payload, dict):
                raise ValueError("案卷 payload 非对象")
            policy = dossier_action_policy(row["action_type"], payload)
            signal = row.get("execution_signal") or {}
            if (
                row["action_type"] in {"assignment", "military_order"}
                and isinstance(signal, dict)
                and signal.get("code") == "idle_start"
            ):
                # Durable vacancy signal starts an executing dossier, but may
                # not pre-materialize work or invent a terminal outcome.
                self.dossiers.transition(
                    dossier_id, "executing", commit=False,
                )
                return
            # Narrative-owned effects are deliberately left to the
            # month-chain world segment and translation; immediate-owned effects were staged before
            # this gate.  Only payload-owned actions enter this dispatcher.
            if policy["effect_owner"] != "payload":
                if policy["effect_owner"] == "narrative":
                    self.dossiers.transition(
                        dossier_id, "executing", commit=False,
                    )
                elif row["action_type"] == "grant_allocation":
                    amount = int(payload.get("amount") or 0)
                    if self._grant_allocation_is_monthly(payload):
                        fiscal = self.list_fiscal_effects_for_dossier(dossier_id)
                        landed = any(
                            str(item.get("key") or "").endswith("_base")
                            and int(item.get("value") or 0) == amount
                            for item in fiscal
                        )
                        if not landed:
                            self.record_dossier_execution(
                                dossier_id, "failed",
                                "拨帑常项未建项",
                                state.turn, close=True, commit=False,
                            )
                        else:
                            self.record_dossier_execution(
                                dossier_id, "fulfilled", "成案时建月度科目",
                                state.turn, close=True, commit=False,
                            )
                    else:
                        moves = self.list_economy_moves_for_dossier(dossier_id)
                        actual = int(moves[0]["delta"]) if moves else 0
                        if actual != -amount:
                            if policy["execution_surface"] == "in_transit":
                                self.dossiers.transition(
                                    dossier_id, "executing", commit=False,
                                )
                            self.record_dossier_execution(
                                dossier_id, "failed",
                                f"拨帑不足额：应拨{amount}两，实拨{abs(actual)}两",
                                state.turn, close=True, commit=False,
                            )
                        elif policy["execution_surface"] == "in_transit":
                            self.dossiers.transition(
                                dossier_id, "executing", commit=False,
                            )
                        else:
                            self.record_dossier_execution(
                                dossier_id, "fulfilled", "成案时足额拨付",
                                state.turn, close=True, commit=False,
                            )
                else:
                    self.record_dossier_execution(
                        dossier_id, "fulfilled", "成案时即生效",
                        state.turn, close=True, commit=False,
                    )
                return
            if row["action_type"] in {"appointment", "dismiss_assignment"}:
                pa = {
                    "id": int(row["pending_action_id"]),
                    "kind": "office",
                    "action": str(payload.get("_office_action") or "任命"),
                    "minister_name": str(payload.get("_minister_name") or ""),
                    "target_id": None,
                }
                previous_materializing = getattr(
                    self.conn, "_materializing_dossier_id", 0
                )
                self.conn._materializing_dossier_id = int(dossier_id)
                try:
                    office_changes = self._commit_office_action(
                        state, pa, payload, content,
                    )
                    if not office_changes:
                        raise ValueError("任免案卷载荷物化失败")
                    if (
                        pa["action"] == "任命"
                        and str(payload.get("summon_after") or "否") == "是"
                    ):
                        from ming_sim.audience_night import activate_office_summon
                        entry = activate_office_summon(self, int(pa["id"]))
                        if entry is None:
                            raise ValueError("任命后传召缺原始故事账")
                        # Activate only here; #670 consumes once per night/person
                        # after the batch (apply_dossier_verdicts) or at the end of
                        # this single promulgation when not deferred.
                        nights = getattr(self.conn, "_deferred_office_summon_nights", None)
                        if nights is not None:
                            nights.add(int(entry["night_id"]))
                        else:
                            from ming_sim.audience_night import (
                                commit_fresh_summons_for_night,
                            )
                            commit_fresh_summons_for_night(
                                self, state, int(entry["night_id"]),
                                content=content,
                            )
                finally:
                    self.conn._materializing_dossier_id = previous_materializing
            elif row["action_type"] == "grant_allocation":
                if self._grant_allocation_is_honorific(payload):
                    self._apply_grant_honorific_effect(
                        state, row, payload, dossier_id,
                    )
                elif self._grant_allocation_is_monthly(payload):
                    amount = int(payload.get("amount") or 0)
                    if amount <= 0:
                        raise ValueError("拨帑案卷 amount 必须为正数")
                    account = str(
                        payload.get("account") or payload.get("target_account") or ""
                    ).strip()
                    if account not in {"国库", "内库"}:
                        raise ValueError("拨帑案卷 account 仅可为国库或内库")
                    self._create_grant_fiscal_item(
                        state, payload, dossier_id,
                        account=account, amount=amount,
                        text=str(row["decree_text"]),
                    )
                else:
                    amount = int(payload.get("amount") or 0)
                    if amount <= 0:
                        raise ValueError("拨帑案卷 amount 必须为正数")
                    # #1503：拨饷/协饷走补饷销欠缝（ADR 0023 clamp）；其它拨帑仍面额扣库。
                    if self._is_army_pay_grant_payload(payload):
                        spent = self._apply_army_pay_grant_effect(
                            state, row, payload, dossier_id,
                        )
                        # 欠资（库银不足且军仍欠）记 failed；超欠 clamp 军已清则仍 fulfilled。
                        # #1507-F5：删多余 spent<=0——军已清（still_owed==0）时 spent=0
                        # 仍属 clamp 成功终局，不得误判 failed。
                        if spent < amount:
                            target_id = str(
                                payload.get("target_id") or row.get("target_id") or ""
                            ).strip()
                            army = ArmyStore(self.conn).read_apply_dossier_promulgation((target_id,))
                            still_owed = (
                                float(army["arrears"] or 0) if army is not None else 0.0
                            )
                            if still_owed > 0:
                                self.record_dossier_execution(
                                    dossier_id, "failed",
                                    f"拨饷不足额：应拨{amount}两，实拨{spent}两",
                                    state.turn, close=True, commit=False,
                                )
                                return
                    else:
                        actual = self.record_issue_economy_move(
                            state,
                            str(payload.get("account") or payload.get("target_account") or ""),
                            -amount,
                            str(payload.get("category") or "奉旨拨帑"),
                            str(payload.get("reason") or row["decree_text"]),
                            purpose=str(payload.get("purpose") or "") or None,
                            target_kind=str(payload.get("target_kind") or "") or None,
                            target_id=str(payload.get("target_id") or "") or None,
                            origin_ref=f"dossier:{dossier_id}",
                            commit=False,
                        )
                        if actual != -amount:
                            if has_execution_surface(
                                row["action_type"], payload,
                            ):
                                self.dossiers.transition(
                                    dossier_id, "executing", commit=False,
                                )
                            self.record_dossier_execution(
                                dossier_id, "failed",
                                f"拨帑不足额：应拨{amount}两，实拨{abs(actual)}两",
                                state.turn, close=True, commit=False,
                            )
                            return
            elif row["action_type"] == "pay_order_override":
                # #653 / ADR 0055/0090：偿还序 override＋折发旨判后物化——顺颁/强颁
                # 走 materialize_pay_order_decree 唯一入口（真实案卷资格＋颁布门校验、
                # 整批先验后写 fail-loud、stale until 清理）；打回在上方 decision 分支
                # 早退零写。物化落在结算尾段 atomic 内（apply_dossier_verdicts 在
                # 玩家月链事务内、本月 fixed flow 已结束后）→ 自下一次结算起
                # 生效，当月已按旧序完成的结算不追溯（F1.3）。
                self._apply_pay_order_override_effect(state, row, payload, dossier_id)
            elif row["action_type"] == "punishment":
                # #517 / ADR 0055：结构化惩处效果自案卷物化，判决后才落人物/钱粮。
                previous_materializing = getattr(self.conn, "_materializing_dossier_id", 0)
                self.conn._materializing_dossier_id = int(dossier_id)
                try:
                    self._apply_punishment_verdict_effect(
                        state, row, payload, dossier_id, content=content,
                    )
                finally:
                    self.conn._materializing_dossier_id = previous_materializing
            elif row["action_type"] == "pacification":
                # #522 / ADR 0055：结构化招抚效果自案卷物化，交既有 #190 易主。
                # 反噬绑定目标当前原势力真实失方削弱（ADR 0009 决定 3）；禁止空对象。
                target = str(
                    payload.get("target_id") or row.get("target_id") or ""
                ).strip()
                if not target:
                    raise ValueError("招抚案卷缺少 canonical target")
                person_row = CharacterStore(self.conn).read_apply_dossier_promulgation((target,))
                if person_row is None:
                    raise ValueError(f"招抚案卷目标不存在：{target}")
                old_power = str(person_row["power_id"] or "").strip()
                if not old_power or old_power == "ming":
                    raise ValueError(
                        f"招抚案卷目标原势力不可反噬：{target}@{old_power or '∅'}"
                    )
                origin_ref = f"dossier:{int(dossier_id)}"
                item = {
                    "name": target,
                    "origin_ref": origin_ref,
                    "动作": "易主",
                    "new_power": "ming",
                    "方式": "主动归附",
                    "反噬": {
                        old_power: {
                            "military_strength": -1,
                            "reason": "受抚",
                        }
                    },
                    "reason": str(
                        payload.get("text") or row.get("decree_text") or "受抚归明"
                    ),
                }
                from ming_sim.issues import _apply_person_changes
                results = _apply_person_changes(
                    self,
                    state,
                    [item],
                    content=content,
                    origin_ref=origin_ref,
                    require_origin=True,
                    external_transaction=True,
                )
                accepted = [
                    r for r in results
                    if isinstance(r, dict) and not r.get("rejected")
                ]
                if not accepted:
                    reason = ""
                    if results and isinstance(results[0], dict):
                        reason = str(results[0].get("reason") or "")
                    raise ValueError(reason or "招抚案卷易主物化失败")
            elif row["action_type"] == "authorization":
                # #528 / #611：公开委任只接 authority_changes 授予槽；判后物化。
                if not self._apply_authorization_verdict_effect(
                    state, row, payload, dossier_id,
                ):
                    return
            elif row["action_type"] == "secret_authorization":
                # 密授不归本片（#528）；#611 privileges 仍只经 authority_changes 生产。
                pass
            elif row["action_type"] == "revoke_authority":
                # #523 / #611：收权只接 authority_changes 收回槽；判后物化。
                self._apply_revoke_authority_verdict_effect(
                    state, row, payload, dossier_id,
                )
            elif row["action_type"] == "revoke_decree":
                # #523：撤回成命=breach 目标 + 停 initiative；捆带授权走 authority_changes。
                self._apply_revoke_decree_verdict_effect(
                    state, row, payload, dossier_id,
                )
            elif row["action_type"] == "assignment":
                # #520 / ADR 0055：交办机械效果=initiative，顺颁后落。
                if not self._apply_assignment_verdict_effect(
                    state, row, payload, dossier_id,
                ):
                    return
            elif row["action_type"] == "referral":
                # #524 / ADR 0055：下议机械效果=initiative（机关 participants + end_turn）。
                if not self._apply_referral_verdict_effect(
                    state, row, payload, dossier_id,
                ):
                    return
            elif row["action_type"] == "military_order":
                # #521 / ADR 0055：军令 station/office 自案卷物化；due_turn 已在案卷。
                self._apply_military_order_verdict_effect(
                    state, row, payload, dossier_id,
                    content=content,
                )
            # #1783：仅 grant 回报期限未到 → 保持 executing；期限只挂原案卷，
            # 不另立承诺事项/不占在办名额。到期由 write_due 扫案卷 due_turn → 0076。
            # 其它类型终局路径不动。期限真源＝案卷列/payload.due_turn（军令同款单源）。
            if str(row.get("action_type") or "") == "grant_allocation":
                try:
                    due_turn = int(row.get("due_turn") or 0)
                except (TypeError, ValueError):
                    due_turn = 0
                if due_turn <= 0:
                    try:
                        due_turn = int(payload.get("due_turn") or 0)
                    except (TypeError, ValueError):
                        due_turn = 0
                if due_turn > int(state.turn):
                    self.dossiers.transition(
                        dossier_id, "executing", commit=False,
                    )
                    return
            if policy["execution_surface"] in {"terminal", "immediate"}:
                self.record_dossier_execution(
                    dossier_id, "fulfilled", "颁布即终局", state.turn,
                    close=True, commit=False,
                )
            else:
                self.dossiers.transition(
                    dossier_id, "executing", commit=False,
                )
        return

    _OVERRIDE_AUTHORITY_COST = -5
    _REACTION_INTENSITY = {"weak": 4, "strong": 8}
    _REACTION_SIGN = {"positive": 1, "negative": -1}
    _BREACH_FACTION_REACTION = {"direction": "negative", "intensity": "weak"}
    # #565 委派连坐：终值→程度档固定映射；cost_identity 钉死「连坐」。
    # 触发集单一真源＝intensity map 的 key 集（issues 适配器只引用本 frozenset）。
    _JOINT_LIABILITY_COST_IDENTITY = "连坐"
    _EXECUTION_OUTCOME_INTENSITY = {
        "failed": "strong", "transformed": "strong", "degraded": "weak",
    }
    _JOINT_LIABILITY_TRIGGERS = frozenset(_EXECUTION_OUTCOME_INTENSITY)
    _INTENSITY_DOWNGRADE = {"strong": "weak", "weak": None}

    def _current_judge_affected_parties(
        self, dossier_id: int, turn: int,
    ) -> List[Dict[str, str]]:
        """Read only this turn's latest promulgation Judge evidence."""
        parties_json = self.dossiers.latest_judge_parties_json(int(dossier_id), int(turn))
        if parties_json is None:
            raise ValueError("强颁缺少当前回合 Judge affected_parties")
        value = load_stored_list(parties_json, label="affected_parties")
        if not isinstance(value, list) or not value:
            raise ValueError("强颁当前回合 Judge affected_parties 必须为非空 typed 清单")
        validate_affected_parties(
            value,
            faction_names={str(item["name"]) for item in FactionStore(self.conn).read_names()},
            class_names={str(item["name"]) for item in ClassStore(self.conn).read_names()},
        )
        return value

    def _apply_authority_cost(
        self, state: GameState, dossier_id: int, reason: str, *, cost_identity: str,
    ) -> None:
        """Record and apply the shared authority event exactly once."""
        if not self.dossiers.record_cost_event(
            dossier_id, state.turn, "authority", "metric", "皇威",
            self._OVERRIDE_AUTHORITY_COST, reason, cost_identity=cost_identity,
        ):
            return
        state.metrics["皇威"] = max(
            0, int(state.metrics.get("皇威", 0)) + self._OVERRIDE_AUTHORITY_COST,
        )
        self.reign.upsert_metric("皇威", int(state.metrics["皇威"]))

    def _apply_override_costs(
        self, state: GameState, dossier_id: int, *, include_authority: bool,
        include_parties: bool, stigma_reason: str, commit: bool = True,
    ) -> None:
        """ADR 0056 narrow rail: authority and typed signed reactions."""
        if include_authority:
            self._apply_authority_cost(
                state, dossier_id, stigma_reason, cost_identity="override",
            )
        parties_already_applied = self.dossiers.has_override_party_cost(int(dossier_id))
        if include_parties and not parties_already_applied:
            for party in self._current_judge_affected_parties(dossier_id, state.turn):
                kind, key = str(party.get("kind") or ""), str(party.get("key") or "")
                magnitude = self._REACTION_INTENSITY.get(str(party.get("intensity") or ""))
                sign = self._REACTION_SIGN.get(str(party.get("direction") or ""))
                if kind not in {"faction", "class"} or magnitude is None or sign is None:
                    raise ValueError("反应代价只接受已校验 typed 清单")
                delta = sign * magnitude
                if not self.dossiers.record_cost_event(
                    dossier_id, state.turn, "satisfaction", kind, key, delta, stigma_reason,
                    cost_identity="override",
                ):
                    continue
                if kind == "faction":
                    self.adjust_factions(
                        {key: {"satisfaction": delta}}, commit=False,
                    )
                else:
                    self.adjust_classes(
                        {key: {"satisfaction": delta}}, commit=False,
                    )
        if commit:
            self.conn.commit()

    def breach_decree_dossier(
        self, state: GameState, dossier_id: int, *, reason: str = "撤回成命",
        commit: bool = True,
    ) -> bool:
        """Withdraw an issued promise; commit=False belongs wholly to its caller."""
        if commit:
            from ming_sim.decree import atomic_and_reload
            transaction = atomic_and_reload(self, state)
        else:
            transaction = contextlib.nullcontext()
        with transaction:
            dossier = self.dossiers.get(dossier_id)
            if dossier is None:
                raise KeyError(f"案卷不存在：{dossier_id}")
            was_closed = dossier["status"] == "closed"
            if dossier["status"] not in {"promulgated", "executing"} and not (
                was_closed and self.dossiers.authorizes_effects(dossier_id)
            ):
                return False
            if not self.dossiers.record_cost_event(
                dossier_id, state.turn, "breach", "dossier", str(dossier_id), 0, reason,
                cost_identity="breach",
            ):
                return False
            self._apply_authority_cost(
                state, dossier_id, reason, cost_identity="breach",
            )
            roster = dossier.get("participant_roster") or []
            ministers = set()
            for item in roster:
                if not isinstance(item, dict):
                    continue
                tier = item.get("tier")
                if tier == "主办":
                    ministers.add(str(item.get("character_id") or ""))
                if tier in {"主办", "协办"} and item.get("delegator_id"):
                    ministers.add(str(item["delegator_id"]))
            ministers.discard("")
            factions = set()
            for person in sorted(ministers):
                row = CharacterStore(self.conn).read_breach_decree_dossier((person,))
                if row is None:
                    continue
                if str(row["faction"] or ""):
                    factions.add(str(row["faction"]))
                if str(row["status"]) == "dead":
                    logging.getLogger(__name__).warning("跳过已故参与者%s", person)
                    continue
                self.record_relation_edge_event(
                    source="皇帝", target=person, event_kind="辜负", context=reason,
                    origin=f"dossier:{dossier_id}:breach", turn=state.turn,
                    year=state.year, period=state.period,
                )
            registered_factions = {
                str(row["name"])
                for row in FactionStore(self.conn).read_names()
            }
            factions.intersection_update(registered_factions)
            breach_delta = (
                self._REACTION_SIGN[self._BREACH_FACTION_REACTION["direction"]]
                * self._REACTION_INTENSITY[self._BREACH_FACTION_REACTION["intensity"]]
            )
            for faction in sorted(factions):
                if self.dossiers.record_cost_event(
                    dossier_id, state.turn, "satisfaction", "faction", faction,
                    breach_delta, reason, cost_identity="breach",
                ):
                    self.adjust_factions(
                        {faction: {"satisfaction": breach_delta}}, commit=False,
                    )
            if was_closed:
                self.dossiers.set_interruption_reason_if_empty(
                    int(dossier_id), reason,
                )
            else:
                self.dossiers.force_close(
                    int(dossier_id), turn=int(state.turn), reason=reason,
                )
        return True

    def list_execution_liability_parties(
        self, dossier_id: int,
    ) -> List[Dict[str, object]]:
        """连坐归属读端：与写路共用 project_execution_liability_parties；永不返回知情档。"""
        dossier = self.dossiers.get(dossier_id)
        if dossier is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        return project_execution_liability_parties(dossier.get("participant_roster"))

    def merge_execution_note(
        self, dossier_id: int, fragment: str, *, commit: bool = True,
    ) -> str:
        """下游说明片段合并写口（#565；S12/#567 消费方）。

        初写仍由 record_dossier_execution 落 judge note；本接口只做增补合并。
        """
        owns = self.owns_transaction()
        text = str(fragment or "").strip()
        if not text:
            raise ValueError("说明片段不能为空")
        row = self.dossiers.get(dossier_id)
        if row is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        existing = str(row.get("execution_note") or "").strip()
        if text in existing.split("；"):
            merged = existing
        elif existing:
            merged = f"{existing}；{text}"
        else:
            merged = text
        if merged != existing:
            self.dossiers.merge_execution_note(
                int(dossier_id), merged, commit=False,
            )
            self._commit_dossier_write(commit, owns)
        return merged

    def validate_joint_liability_affected_parties(
        self, affected_parties: object, outcome: str,
    ) -> None:
        """显式 affected_parties：validate_affected_parties 全键 + 档位贴合终值映射。

        仅作契约§5/AC⑥校验门闩，不驱动机械写路；适配器在落库前调用一次。
        """
        primary = self._EXECUTION_OUTCOME_INTENSITY.get(str(outcome or "").strip())
        if primary is None:
            raise ValueError("连坐 affected_parties 仅接受 degraded/failed/transformed 终值")
        allowed = {primary}
        downgraded = self._INTENSITY_DOWNGRADE.get(primary)
        if downgraded:
            allowed.add(downgraded)
        faction_names = {
            str(row["name"]) for row in FactionStore(self.conn).read_names()
        }
        class_names = {
            str(row["name"])
            for row in ClassStore(self.conn).read_names()
        }
        validate_affected_parties(
            affected_parties,
            faction_names=faction_names,
            class_names=class_names,
        )
        for party in affected_parties:  # type: ignore[union-attr]
            if str(party.get("intensity") or "") not in allowed:
                raise ValueError("affected_parties intensity 须与执行终值固定映射一致")

    def apply_execution_joint_liability(
        self,
        state: GameState,
        dossier_id: int,
        outcome: str,
        *,
        reason: str = "",
        commit: bool = True,
    ) -> bool:
        """#565 委派连坐：仅由 dossier_executions 适配器在落终值时调用。

        责任面由 project_execution_liability_parties 投影；写轨全经
        dossiers.record_cost_event + record_relation_edge_event；幂等键不含 turn。
        """
        outcome = str(outcome or "").strip()
        if outcome not in self._JOINT_LIABILITY_TRIGGERS:
            return False
        primary_intensity = self._EXECUTION_OUTCOME_INTENSITY[outcome]
        secondary_intensity = self._INTENSITY_DOWNGRADE[primary_intensity]
        reason_text = str(reason or "执行连坐").strip() or "执行连坐"
        identity = self._JOINT_LIABILITY_COST_IDENTITY
        origin = f"dossier:{int(dossier_id)}:{identity}"

        if commit:
            from ming_sim.decree import atomic_and_reload
            transaction = atomic_and_reload(self, state)
        else:
            transaction = contextlib.nullcontext()

        with transaction:
            dossier = self.dossiers.get(dossier_id)
            if dossier is None:
                raise KeyError(f"案卷不存在：{dossier_id}")
            # 整笔幂等门闩（含全员已故仅记说明的情形）；UNIQUE 不含 turn。
            if not self.dossiers.record_cost_event(
                dossier_id, state.turn, "liability", "dossier", str(dossier_id),
                0, reason_text, cost_identity=identity,
            ):
                return False

            registered_factions = {
                str(row["name"])
                for row in FactionStore(self.conn).read_names()
            }
            note_names: List[str] = []
            # 投影已先定档后去重（primary 胜）；同派系 UNIQUE 保留主责额度。
            for party in project_execution_liability_parties(
                dossier.get("participant_roster"),
            ):
                person = str(party["character_id"])
                if party["responsibility"] == "primary":
                    intensity = primary_intensity
                    role_label = "主办"
                else:
                    intensity = secondary_intensity
                    role_label = "委派"
                row = CharacterStore(self.conn).read_breach_decree_dossier((person,))
                if row is None:
                    continue
                note_names.append(f"{person}（{role_label}）")
                if str(row["status"] or "") == "dead":
                    logging.getLogger(__name__).warning("跳过已故连坐责任人%s", person)
                    continue
                if intensity is None:
                    # 执行人已是 weak 时次责无更低档→零机械扣、仍进走样说明。
                    continue
                magnitude = self._REACTION_INTENSITY[intensity]
                delta = self._REACTION_SIGN["negative"] * magnitude
                self.record_relation_edge_event(
                    source="皇帝", target=person, event_kind="连坐",
                    context=reason_text, origin=origin, turn=state.turn,
                    year=state.year, period=state.period,
                )
                faction = str(row["faction"] or "").strip()
                if faction and faction in registered_factions:
                    if self.dossiers.record_cost_event(
                        dossier_id, state.turn, "satisfaction", "faction", faction,
                        delta, reason_text, cost_identity=identity,
                    ):
                        self.adjust_factions(
                            {faction: {"satisfaction": delta}}, commit=False,
                        )

            if note_names:
                # P4：只写定性人名归属，不落 weak/strong/枚举裸词。
                self.merge_execution_note(
                    dossier_id,
                    "连坐归属：" + "、".join(note_names),
                    commit=False,
                )
        return True

    def save_pending_promulgation_verdicts(
        self, turn: int, verdicts: Iterable[Dict[str, object]],
    ) -> None:
        """Persist one complete turn-scoped batch before simulation starts."""
        rows = list(verdicts)
        with atomic(self):
            self.dossiers.save_pending_promulgation_verdicts(
                int(turn),
                [
                    (strict_int(v.get("dossier_id")),
                     safe_json_dumps(v, ensure_ascii=False))
                    for v in rows
                ],
            )

    def get_pending_promulgation_verdicts(
        self, turn: int,
    ) -> List[Dict[str, object]]:
        rows = [{"verdict_json": j} for j in self.dossiers.pending_promulgation_verdicts(int(turn))]
        result = []
        for row in rows:
            raw_value = row["verdict_json"]
            try:
                value = load_stored_object(raw_value, label="待应用颁布判决")
            except ValueError as exc:
                raise LLMContractError(
                    f"待应用颁布判决读取失败：{exc}", raw_value=raw_value,
                ) from exc
            result.append(value)
        return result

    def _apply_military_order_station_effect(
        self, state, *, army_id: str, station: str, actor: str, reason: str,
        origin_ref: str, station_region: str = "",
    ) -> None:
        """军令调驻面：既有军 station(+可选 station_region) → army 写核；不得 new_armies。

        #659：只改人读驻地/结构化驻地；不触 pay_source_region。仅 station 无 region
        时只改人读字段，region 保持原值（禁止从 station 文本反推）。
        """
        dest = str(station or "").strip()
        dest_region = str(station_region or "").strip()
        if not dest and not dest_region:
            return
        if not army_id:
            raise ValueError("军令调驻缺少军队 target")
        existing = ArmyStore(self.conn).read_apply_military_order_station_effect((army_id,))
        if existing is None:
            raise ValueError(
                f"军令调驻引用未入库军队 '{army_id}'（既有军调驻不得 new_armies）"
            )
        from ming_sim.models import Event
        pseudo = Event(
            id="military_order", title="军令调遣", kind="圣旨", summary="",
            urgency=0, severity=0, credibility=100, interests=[], audiences=[],
        )
        delta: Dict[str, object] = {"reason": reason[:80]}
        if dest:
            delta["station"] = dest
        if dest_region:
            delta["station_region"] = dest_region
        changes = self.apply_army_deltas(
            state, pseudo, None, actor or "军令",
            {army_id: delta},
            commit=False,
            origin_ref=origin_ref,
            require_origin=True,
        )
        # #521 r1：目标 station=当前站时 army 写核空接受=幂等 noop 成功，
        # 不得当硬失败以致同批职守变更回滚。
        rejected = [
            c for c in changes
            if isinstance(c, dict) and c.get("rejected")
        ]
        if rejected:
            fail_reason = str(rejected[0].get("reason") or "")
            raise ValueError(fail_reason or "军令调驻物化失败")

    @staticmethod
    def _affected_people_from_applied_rows(rows) -> set[str]:
        """Canonical applied rows → formal person names (appointee + displaced).

        Partial concurrent-office displacements live only on the row's displaced
        list (full 听用候铨 displacements are also synthesized as cascade rows).
        Used to report actual appointment changes, including partial displacements.
        """
        names: set[str] = set()
        for item in rows or ():
            if not isinstance(item, dict) or item.get("rejected"):
                continue
            person = str(item.get("name") or item.get("人物") or "").strip()
            if person:
                names.add(person)
            for part in item.get("displaced") or []:
                displaced_name = str(part).split(":", 1)[0].strip()
                if displaced_name:
                    names.add(displaced_name)
        return names

    def _apply_military_order_office_effect(
        self, state, payload, *, actor: str, reason: str, origin_ref: str,
        content=None,
    ) -> None:
        """军令职守面：payload.office / office_changes → 人物变更唯一核。"""
        office_items: List[Dict[str, object]] = []
        raw_changes = payload.get("office_changes")
        if isinstance(raw_changes, list):
            for raw in raw_changes:
                if isinstance(raw, dict):
                    office_items.append(dict(raw))
        office_title = str(payload.get("office") or "").strip()
        if office_title and actor:
            if not any(
                str(i.get("name") or "").strip() == actor
                and str(i.get("new_office") or i.get("office") or "").strip()
                for i in office_items
            ):
                office_item: Dict[str, object] = {
                    "name": actor,
                    "动作": "调任",
                    "new_office": office_title,
                    "office": office_title,
                    "reason": reason,
                }
                # Preserve typed 任所 from dossier/pending payload; do not invent.
                seat = str(
                    payload.get("region_id")
                    or payload.get("任所")
                    or payload.get("辖区")
                    or ""
                ).strip()
                if seat:
                    office_item["region_id"] = seat
                office_items.append(office_item)
        if not office_items:
            return
        from ming_sim.issues import _apply_person_changes
        prepared: List[Dict[str, object]] = []
        for item in office_items:
            entry = dict(item)
            entry.setdefault("origin_ref", origin_ref)
            entry.setdefault("动作", "调任")
            if not entry.get("new_office") and entry.get("office"):
                entry["new_office"] = entry["office"]
            prepared.append(entry)
        results = _apply_person_changes(
            self,
            state,
            prepared,
            content=content,
            origin_ref=origin_ref,
            require_origin=True,
            external_transaction=True,
        )
        accepted_p = [
            r for r in results
            if isinstance(r, dict) and not r.get("rejected")
        ]
        if not accepted_p:
            fail_reason = ""
            if results and isinstance(results[0], dict):
                fail_reason = str(results[0].get("reason") or "")
            raise ValueError(fail_reason or "军令职守变更物化失败")

    def _apply_authorization_verdict_effect(
        self, state, row, payload, dossier_id,
    ) -> bool:
        """#528：公开委任案卷顺颁后走 #611 authority_changes 授予槽。

        完整授予条目：动作=授予 + dossier_id + holder_id + privilege + scope。
        不直写 authority_records。
        Returns False when duplicate_active_authority was soft-rejected and
        terminal failure already recorded — caller must return early.
        Returns True when the grant landed.
        """
        from ming_sim.issues import apply_score_extraction

        holder = str(
            payload.get("holder_id")
            or payload.get("assignee_id")
            or payload.get("name")
            or row.get("executor_id")
            or ""
        ).strip()
        privilege = str(payload.get("privilege") or "").strip()
        scope = str(payload.get("scope") or "").strip()
        if not scope:
            t_kind = str(
                payload.get("target_kind") or row.get("target_kind") or ""
            ).strip()
            t_id = str(
                payload.get("target_id") or row.get("target_id") or ""
            ).strip()
            if t_kind and t_id:
                scope = f"{t_kind}:{t_id}"
        if not holder or not privilege or not scope:
            raise ValueError("委任授权案卷缺少 holder_id/privilege/scope")
        out = apply_score_extraction(
            self, state,
            {
                "authority_changes": [{
                    "动作": "授予",
                    "holder_id": holder,
                    "privilege": privilege,
                    "scope": scope,
                    "dossier_id": int(dossier_id),
                }],
            },
            content=None,
        )
        rows = out.get("authority_changes") or []
        item = rows[0] if rows else {"rejected": True, "reason": "授予未落"}
        if item.get("rejected"):
            reason = str(item.get("reason") or "授予被拒")
            # #1628 / 0150-D5-a：跨案 duplicate 接到 assignment 软通道，不得升格整批。
            if reason == "duplicate_active_authority":
                self.dossiers.transition(
                    dossier_id, "executing", commit=False,
                )
                self.record_dossier_execution(
                    dossier_id, "failed", reason, state.turn,
                    close=True, commit=False,
                )
                return False
            raise ValueError(reason)
        return True

    def _apply_revoke_authority_verdict_effect(
        self, state, row, payload, dossier_id,
    ) -> None:
        """#523：收权案卷顺颁后走 #611 authority_changes 收回槽。

        生产项显式携 authority_id + 本项 dossier_id；观感边由 #611 槽写入。
        不走 0056 毁约轨。
        """
        from ming_sim.issues import apply_score_extraction
        from ming_sim.strict_types import strict_int

        try:
            authority_id = strict_int(
                payload.get("authority_id"), accept_numeric_strings=True,
            )
        except (TypeError, ValueError):
            authority_id = 0
        if authority_id <= 0:
            raise ValueError("收权案卷缺少 authority_id")
        out = apply_score_extraction(
            self, state,
            {
                "authority_changes": [{
                    "动作": "收回",
                    "authority_id": authority_id,
                    "dossier_id": int(dossier_id),
                }],
            },
            content=None,
        )
        rows = out.get("authority_changes") or []
        item = rows[0] if rows else {"rejected": True, "reason": "收权未落"}
        if item.get("rejected"):
            reason = str(item.get("reason") or "收权被拒")
            raise ValueError(reason)

    def _apply_revoke_decree_verdict_effect(
        self, state, row, payload, dossier_id,
    ) -> None:
        """#523：撤回成命顺颁后终结目标承诺/旨意；捆带授权走 authority_changes。

        非 undo、不删旧账。代价归 ADR 0056（breach_decree_dossier）。
        """
        from ming_sim.issues import apply_score_extraction
        from ming_sim.strict_types import strict_int

        try:
            target_dossier_id = strict_int(
                payload.get("revoke_target_dossier_id"),
                accept_numeric_strings=True,
            )
        except (TypeError, ValueError):
            target_dossier_id = 0
        try:
            target_issue_id = strict_int(
                payload.get("revoke_target_issue_id"),
                accept_numeric_strings=True,
            )
        except (TypeError, ValueError):
            target_issue_id = 0

        if target_dossier_id <= 0 and target_issue_id <= 0:
            raw = str(payload.get("target_id") or row.get("target_id") or "").strip()
            kind = str(
                payload.get("target_kind") or row.get("target_kind") or ""
            ).strip()
            if raw.startswith("dossier:"):
                kind = "dossier"
                raw = raw.split(":", 1)[1].strip()
            elif raw.startswith("issue:"):
                kind = "issue"
                raw = raw.split(":", 1)[1].strip()
            try:
                tid = strict_int(raw, accept_numeric_strings=True) if raw else 0
            except (TypeError, ValueError):
                tid = 0
            if tid <= 0:
                raise ValueError("撤回成命案卷缺少目标")
            if kind == "issue":
                target_issue_id = tid
            else:
                target_dossier_id = tid

        # issue 目标：经 origin_ref 回指案卷；无合法案卷来源不得免代价终结
        if target_dossier_id <= 0 and target_issue_id > 0:
            issue_row = IssueStore(self.conn).read_apply_revoke_decree_verdict_effect((target_issue_id,))
            if issue_row is None:
                raise ValueError("撤回成命目标事项不存在")
            if str(issue_row["kind"] or "").strip() != "initiative":
                raise ValueError("撤回成命目标须为承诺/initiative")
            origin = str(issue_row["origin_ref"] or "").strip()
            if origin.startswith("dossier:"):
                try:
                    target_dossier_id = int(origin.split(":", 1)[1])
                except (TypeError, ValueError):
                    target_dossier_id = 0

        if target_dossier_id <= 0:
            # 删除 standalone issue 免代价旁路（dossier_id=0 仍 cancel_issue）
            raise ValueError("撤回成命目标无合法案卷来源，不得免代价终结")

        reason = str(
            payload.get("text") or row.get("decree_text") or "撤回成命"
        )[:400]

        # #623 / ADR 0075：目标挂 active 承诺 → 当回合只写挽留 todo，
        # 0056 名声笔与事轴结账延迟到坚持后（不顺颁即 breach+close）。
        from ming_sim.breach_plea import (
            apply_persist_revoke_tail,
            try_defer_revoke_to_breach_plea,
        )
        deferred = try_defer_revoke_to_breach_plea(
            self, state,
            target_dossier_id=int(target_dossier_id),
            target_issue_id=int(target_issue_id or 0),
            revoke_dossier_id=int(dossier_id),
            reason=reason,
            commit=False,
        )
        if deferred and deferred.get("deferred"):
            return

        # 立即路径收尾：0056 + 捆带授权收回 + 同源停 tick（与坚持落地共享）
        apply_persist_revoke_tail(
            self, state,
            target_dossier_id=int(target_dossier_id),
            reason=reason,
            apply_0056=True,
            commitment_ref=int(target_issue_id or 0),
            authority_source_dossier_id=int(dossier_id),
            revoke_dossier_id=int(dossier_id),
        )

    def _apply_military_order_verdict_effect(
        self, state, row, payload, dossier_id, *, content=None,
    ) -> None:
        """#521：军令案卷顺颁后的结构化效果（受判类，打回不进此函数）。

        - 既有军 station → army 写核（apply_army_deltas）；不得 new_armies
        - 真实职守变化 → 人物变更/任免唯一核（ADR 0009）
        - 期限只落案卷 due_turn（限期出战 admission 写入）；无胜负引擎
        """
        origin_ref = f"dossier:{int(dossier_id)}"
        army_id = str(
            payload.get("target_id") or row.get("target_id") or ""
        ).strip()
        station = str(payload.get("station") or "").strip()
        station_region = str(
            payload.get("station_region")
            or payload.get("实际驻地")
            or payload.get("驻地省")
            or ""
        ).strip()
        reason = str(
            payload.get("text") or row.get("decree_text") or "军令调遣"
        )
        from ming_sim.participant_roster import resolve_dossier_owner_name
        actor = resolve_dossier_owner_name(row)

        self._apply_military_order_station_effect(
            state,
            army_id=army_id,
            station=station,
            station_region=station_region,
            actor=actor,
            reason=reason,
            origin_ref=origin_ref,
        )
        # due_turn：admission/create_decree_dossier 已落案卷列；限期出战无另表。
        self._apply_military_order_office_effect(
            state,
            payload,
            actor=actor,
            reason=reason,
            origin_ref=origin_ref,
            content=content,
        )

    @staticmethod
    def _initiative_title_and_body(
        payload: Dict[str, object], row,
    ) -> tuple[str, str]:
        """#1565/0142：initiative 题名/正文单一规则（assignment/referral 共用）。

        题名只认结构化 title|target_id，不从 decree_text/正文/皇帝散文截取，
        不生成「交办差事/下议事项」默认题名冒充来源身份。
        正文唯一真源 payload.text；旧案卷无 text 时 decree_text 仅作正文承接，
        不得回填题名，不得以题名/target_id 冒充正文。
        真缺锚时 title 为空串——caller 复用既有 execution failed 接缝，保留案卷与正文。
        """
        title = str(payload.get("title") or "").strip()
        if not title:
            title = str(payload.get("target_id") or "").strip()
        body = str(payload.get("text") or row.get("decree_text") or "").strip()
        return title, body

    def _apply_referral_verdict_effect(
        self, state, row, payload, dossier_id,
    ) -> bool:
        """#524：下议案卷顺颁后创建 initiative（机关 participants + end_turn）。

        Returns False on soft-reject；True 时 caller 继续 executing 过渡。
        禁个人 owner：participants 仅 responsible_bodies 机关/职司名。
        """
        from ming_sim.action_materialize import (
            assert_responsible_bodies_org_only,
            character_person_names,
            parse_responsible_bodies,
        )
        from ming_sim.issues import apply_score_extraction

        # 与暂存/admission 同一解析；个人名不得落 participants。
        bodies = parse_responsible_bodies(payload.get("responsible_bodies"))
        if not bodies:
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", "下议缺少 responsible_bodies",
                state.turn, close=True, commit=False,
            )
            return False
        try:
            assert_responsible_bodies_org_only(
                bodies,
                known_person_names=character_person_names(self),
                current_minister=str(
                    row.get("executor_id")
                    or payload.get("actor")
                    or payload.get("assignee_id")
                    or payload.get("assignee")
                    or ""
                ),
            )
        except ValueError as exc:
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", str(exc) or "responsible_bodies 禁个人名",
                state.turn, close=True, commit=False,
            )
            return False

        title, stage_text = self._initiative_title_and_body(payload, row)
        if not title:
            # 保留案卷与正文；缺结构化锚走既有 execution failed（可见可恢复）。
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", "下议缺少结构化题名（title 或 target_id）",
                state.turn, close=True, commit=False,
            )
            return False

        try:
            end_turn = int(payload.get("end_turn") or 0)
        except (TypeError, ValueError):
            end_turn = 0
        if end_turn <= 0:
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", "下议缺少 end_turn",
                state.turn, close=True, commit=False,
            )
            return False

        origin_ref = f"dossier:{int(dossier_id)}"
        # end_turn 有值时既有 new_issues 契约要求 commitment_kind 标记
        # （否则被当成「承诺形态无 marker」拒）；议期=时限承诺，复用 until_stop + end_turn。
        ni: Dict[str, object] = {
            "origin_kind": "decree",
            "origin_ref": origin_ref,
            "kind": "initiative",
            "title": title,
            "stage_text": stage_text,
            # 机关/职司名字符串列表 → issues.participants JSON
            "participants": bodies,
            "end_turn": end_turn,
            "commitment_kind": "until_stop",
        }
        out = apply_score_extraction(
            self, state, {"new_issues": [ni]}, content=None,
        )
        created = (out.get("issue_summary") or {}).get("new_issues") or []
        item = created[0] if created else {"rejected": True, "reason": "下议 initiative 未落"}
        if item.get("rejected"):
            reason = str(item.get("reason") or "下议 initiative 被拒")
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", reason, state.turn, close=True, commit=False,
            )
            return False
        return True

    def _apply_assignment_verdict_effect(
        self, state, row, payload, dossier_id,
    ) -> bool:
        """#520：交办案卷顺颁后创建 initiative（owner + 可选军令状承诺）。

        Returns False when the item was soft-rejected (invalid commitment
        shape) and terminal failure already recorded — caller must return early.
        Returns True when initiative landed and caller should continue to the
        shared executing/terminal transition.
        """
        from ming_sim.issues import (
            _normalize_commitment_kind,
            apply_score_extraction,
        )

        from ming_sim.participant_roster import resolve_dossier_owner_name
        owner = resolve_dossier_owner_name(row)
        if not owner:
            raise ValueError("交办案卷缺少主办")

        title, stage_text = self._initiative_title_and_body(payload, row)
        if not title:
            # 保留案卷与正文；缺结构化锚走既有 execution failed（可见可恢复）。
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", "交办缺少结构化题名（title 或 target_id）",
                state.turn, close=True, commit=False,
            )
            return False

        origin_ref = f"dossier:{int(dossier_id)}"
        commitment_kind = _normalize_commitment_kind(payload.get("commitment_kind"))
        if commitment_kind == "无":
            commitment_kind = ""

        # 本接缝组装 new_issues item，经 apply_score_extraction 落地；
        # 逐项 rejected（毒形等）→ 案卷执行失败。#1790 废在办数量硬上限。
        # #520 只授权捕获与落库；不夹带民心等兑现效果（兑现归 #476）。
        ni: Dict[str, object] = {
            "origin_kind": "decree",
            "origin_ref": origin_ref,
            "kind": "initiative",
            "title": title,
            "stage_text": stage_text,
            "participant_roster": [{"character_id": owner, "tier": "主办"}],
        }
        # 形状保留：承诺字段原样交给 apply_score_extraction。
        # 缺 commitment_kind marker 的毒形不得在此洗掉后当普通 initiative 落地（#520）。
        if commitment_kind:
            ni["commitment_kind"] = commitment_kind
        # C.6 rescript stop_condition 为 str（payload 层保真）；结构化 commitment
        # 门仍只认 dict（#136 全局契约不动）。非 dict 不转发进 ni，避免 str 被
        # 结构化校验误拒；until_stop+end_turn 仍可落 initiative。
        stop_raw = payload.get("stop_condition")
        if isinstance(stop_raw, dict) and stop_raw:
            ni["stop_condition"] = stop_raw
        try:
            end_turn = int(payload.get("end_turn") or 0)
        except (TypeError, ValueError):
            end_turn = 0
        if end_turn > 0:
            ni["end_turn"] = end_turn
            # 与 stages 支对称：有绝对期限则须带 commitment marker，否则
            # end_turn 会被当成「承诺形态无 marker」拒（issues 既有契约）。
            if not commitment_kind:
                ni["commitment_kind"] = "until_stop"
        ongoing = payload.get("ongoing_effects")
        if isinstance(ongoing, dict) and ongoing:
            ni["ongoing_effects"] = ongoing
        # #620 扩展面：分段里程碑（#520 本体字段语义不动）
        from ming_sim.staged_commitment import capture_commitment_stages
        stages_norm = capture_commitment_stages(
            payload.get("stages") or payload.get("stages_json"),
        )
        if stages_norm:
            ni["stages"] = stages_norm
            if not commitment_kind:
                ni["commitment_kind"] = "until_stop"
        # ongoing_effects / end_turn 选择规则与缺 marker 拒收交既有校验。

        out = apply_score_extraction(
            self, state, {"new_issues": [ni]}, content=None,
        )
        created = (out.get("issue_summary") or {}).get("new_issues") or []
        item = created[0] if created else {"rejected": True, "reason": "交办 initiative 未落"}
        if item.get("rejected"):
            reason = str(item.get("reason") or "交办 initiative 被拒")
            # 校验失败逐项软拒，不掀整批。
            self.dossiers.transition(dossier_id, "executing", commit=False)
            self.record_dossier_execution(
                dossier_id, "failed", reason, state.turn, close=True, commit=False,
            )
            return False
        return True

    def _apply_punishment_verdict_effect(
        self, state, row, payload, dossier_id, *, content=None,
    ) -> None:
        """#517：惩处案卷顺颁后的结构化效果（受判类，打回不进此函数）。"""
        target = str(
            payload.get("target_id") or row.get("target_id") or ""
        ).strip()
        punish_action = str(payload.get("punish_action") or "").strip()
        issue_disposition = str(payload.get("issue_disposition") or "").strip()
        issue_id = int(payload.get("issue_id") or 0)
        issue = None
        if issue_id:
            issue = IssueStore(self.conn).read_apply_punishment_verdict_effect((issue_id,))
            if issue is None or issue["origin_kind"] != "impeachment_surge":
                raise ValueError("处置所指弹劾潮不存在")
            if issue["status"] != "active":
                return
            if issue_disposition == "办人":
                try:
                    roster = load_stored_list(issue["target_roster"], label='target_roster')
                except (TypeError, ValueError) as exc:
                    raise ValueError("弹劾潮 target_roster 非法") from exc
                if target not in roster:
                    raise ValueError("办人目标不在弹劾潮 target_roster")
        if issue_disposition == "压下" and issue is not None:
            faction = str(issue["faction_hint"] or "").strip()
            if self.dossiers.record_cost_event(
                dossier_id, state.turn, "authority", "metric", "皇威", -1,
                "压下弹劾", cost_identity="impeachment_suppression",
            ):
                state.metrics["皇威"] = max(0, int(state.metrics.get("皇威", 0)) - 1)
                self.reign.upsert_metric("皇威", int(state.metrics["皇威"]))
            if faction and self.dossiers.record_cost_event(
                dossier_id, state.turn, "satisfaction", "faction", faction, -1,
                "压下弹劾", cost_identity="impeachment_suppression",
            ):
                self.adjust_factions({faction: {"satisfaction": -1}}, commit=False)
            self.close_issue(state, issue_id, reason="resolved", commit=False)
            return
        if not target:
            raise ValueError("惩处案卷缺少 canonical target")
        origin_ref = f"dossier:{int(dossier_id)}"
        reason = str(
            payload.get("text") or row.get("decree_text") or punish_action
        )
        # #658：typed backing 单权威（与 stage 首写共吃）
        backing_id = int(require_backing_dossier_id(self, payload.get("backing_dossier_id")) or 0)
        status_by_action = {
            "拿问下狱": "imprisoned",
            "拿问去职": "imprisoned",
            "赐死": "dead",
            "流放": "exiled",
            "削籍": "dismissed",
        }
        if punish_action in status_by_action:
            item = {
                "name": target,
                "origin_ref": origin_ref,
                "动作": "处置",
                "status": status_by_action[punish_action],
                "reason": reason,
            }
            if punish_action == "削籍":
                item["reason_code"] = "获罪削籍"
                item["reason"] = "获罪削籍"
            from ming_sim.issues import _apply_person_changes
            results = _apply_person_changes(
                self,
                state,
                [item],
                content=content,
                origin_ref=origin_ref,
                require_origin=True,
                external_transaction=True,
            )
            accepted = [
                r for r in results
                if isinstance(r, dict) and not r.get("rejected")
            ]
            if not accepted:
                fail_reason = ""
                if results and isinstance(results[0], dict):
                    fail_reason = str(results[0].get("reason") or "")
                raise ValueError(fail_reason or "惩处案卷人物效果物化失败")
            self._maybe_write_backing_betray_credit(
                state, target=target, backing_id=backing_id, reason=reason,
            )
            if issue_id and issue_disposition == "办人":
                self.close_issue(state, issue_id, reason="resolved", commit=False)
            return
        if punish_action in {"放归", "昭雪"}:
            # #517：宥赦只回迁在世处置态；dead 等终态响亮拒绝，不得复活。
            current_status, _ = self.get_character_status(target)
            if current_status not in {"imprisoned", "dismissed", "exiled"}:
                raise ValueError(
                    f"宥赦不可回迁：{target} 当前状态={current_status or '(空)'}"
                )
            self.set_character_status(
                state, target, "active", reason, reason_code="", content=content, commit=False,
            )
            self.record_person_log(
                state, target, "处置", payload_summary=punish_action,
                source="punishment", origin_ref=origin_ref, commit=False,
            )
            # #658：放归/昭雪为非惩罚动作，成功亦不写 backing 辜负。
            return
        if punish_action == "罚俸":
            amount = int(payload.get("amount") or 0)
            if amount <= 0:
                raise ValueError("罚俸案卷缺少正数 amount")
            # #517 r2：消费 actual；不足额/零落账响亮失败，事务回滚，不得 fulfilled。
            # 方向保持减项（票面钱粮减项），不得改成国库正收入。
            actual = self.record_issue_economy_move(
                state,
                "国库",
                -amount,
                "罚俸",
                "罚俸示惩",
                purpose=None,
                target_kind="character",
                target_id=target,
                origin_ref=origin_ref,
                commit=False,
            )
            if actual != -amount:
                raise ValueError(
                    f"罚俸不足额：应减{amount}两，实减{abs(int(actual))}两"
                )
            self.record_person_log(
                state, target, "罚俸", payload_summary="罚俸示惩",
                source="punishment", origin_ref=origin_ref, commit=False,
            )
            self._maybe_write_backing_betray_credit(
                state, target=target, backing_id=backing_id, reason=reason,
            )
            return
        if punish_action == "廷杖":
            self.record_person_log(
                state, target, "廷杖", payload_summary="廷杖示惩",
                source="punishment", origin_ref=origin_ref, commit=False,
            )
            self._maybe_write_backing_betray_credit(
                state, target=target, backing_id=backing_id, reason=reason,
            )
            return
        raise ValueError(f"惩处案卷动作无法物化：{punish_action}")

    def _maybe_write_backing_betray_credit(
        self, state, *, target: str, backing_id: int, reason: str,
    ) -> None:
        """#658：处置成功且目标确为原案非御笔背书人时，经 ADR 0079 写辜负。

        origin 回指原 dossier。无 backing / 非站台者 / 御笔背书 → 零信用事件。
        """
        if int(backing_id or 0) <= 0:
            return
        person = str(target or "").strip()
        if not person:
            return
        endorsements = self.dossiers.endorsements(int(backing_id))
        hit = False
        for item in endorsements:
            if bool(item.get("imperial")):
                continue
            if str(item.get("form") or "") != "当面站台":
                continue
            if str(item.get("endorser_id") or "").strip() == person:
                hit = True
                break
        if not hit:
            return
        context = str(reason or "").strip() or "处置站台者"
        from ming_sim.credit_events import KIND_BETRAY, write_credit_event
        write_credit_event(
            self, state,
            person=person,
            event_kind=KIND_BETRAY,
            context=context,
            origin=f"dossier:{int(backing_id)}",
        )

    def _apply_pay_order_override_effect(
        self, state: GameState, row, payload: Dict[str, object], dossier_id: int,
    ) -> None:
        """#653 / ADR 0090：pay_order_override 案卷顺颁/强颁后自载荷物化 fiscal_config。

        唯一物化入口＝materialize_pay_order_decree（内部再验真实案卷资格＋颁布门）；
        打回案卷不进本分支（效果跟判决走，零写入）。物化即效果已落地（无执行判定面）
        → fulfilled 直达终局，与 punishment/pacification 同款 terminal 分支。"""
        from ming_sim.pay_order import materialize_pay_order_decree
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            raise ValueError("pay_order_override 案卷 payload.entries 须为非空列表")
        materialize_pay_order_decree(
            self,
            turn=int(state.turn),
            entries=entries,
            origin_ref=f"dossier:{int(dossier_id)}",
            reason=str(row["decree_text"] or "")[:240],
            commit=False,
        )
        # 终局由 dispatcher 尾部通用 terminal 分支统一写（fulfilled 颁布即终局），
        # 与 punishment/pacification 同款：效果 applier 不自带 close。

    def _record_dossier_verdict_metadata(
        self, state: GameState, dossier_id: int, verdict: Dict[str, object],
    ) -> None:
        """同判决事务落 typed 反应/禁强颁标记，顺颁中旨并记皇威。"""
        dossier = self.dossiers.get(dossier_id)
        # #657 §C.8：中旨不持久化猜派 affected_parties；打回仅 stigma。
        parties_json = (
            "[]" if dossier and dossier.get("mode") == "midzhi"
            else safe_json_dumps(verdict.get("affected_parties") or [], ensure_ascii=False)
        )
        self.dossiers.set_latest_decision_parties(
            int(dossier_id), parties_json,
            1 if verdict.get("midzhi_unpromulgatable") is True else 0,
        )
        if (dossier and dossier.get("mode") == "midzhi"
                and verdict.get("decision") == "promulgated"):
            self._apply_override_costs(
                state, dossier_id, include_authority=True, include_parties=False,
                stigma_reason="预先中旨直发", commit=False,
            )

    def apply_dossier_verdicts(
        self, state: GameState, verdicts: Iterable[Dict[str, object]], *,
        content=None,
    ) -> set[str]:
        """结算判决注入入口：批量、同事务消费每案结构化 verdict。"""
        # Validate the complete batch before the first write at this public seam.
        rows = list(verdicts)
        faction_names = {str(row["name"]) for row in FactionStore(self.conn).read_names()}
        class_names = {str(row["name"]) for row in ClassStore(self.conn).read_names()}
        character_ids = {str(row["name"]) for row in CharacterStore(self.conn).read_names()}
        for verdict in rows:
            if not isinstance(verdict, dict):
                raise ValueError("案卷 verdict 须为对象")
            dossier_id = strict_int(verdict.get("dossier_id"))
            dossier = self.dossiers.get(dossier_id)
            if dossier is None:
                raise KeyError(f"案卷不存在：{dossier_id}")
            decision = str(verdict.get("decision") or "")
            validate_verdict_affected_parties(
                verdict, str(dossier.get("mode") or "ordinary"),
                faction_names=faction_names, class_names=class_names,
            )
            if decision == "rejected":
                validate_rejection_verdict(
                    verdict, PROMULGATION_BLOCKED_LAYERS - {""},
                    faction_names=faction_names, class_names=class_names,
                    character_ids=character_ids,
                )

        # #1583：荐人快照以批前盘面统一校验——同批前序任免造成的中间态不得
        # 令后序案卷二次校验失败。validate_recommendation_snapshot 仍是唯一真源。
        prevalidate_rows: List[Dict[str, object]] = []
        for verdict in rows:
            decision = str(verdict.get("decision") or "")
            if decision not in {"promulgated", "force_promulgated"}:
                continue
            dossier = self.dossiers.get(strict_int(verdict.get("dossier_id")))
            if dossier is not None:
                prevalidate_rows.append(dossier)
        self._prevalidate_office_recommendation_snapshots(state, prevalidate_rows)

        # Reuse the settlement rollback primitive so failed later effects restore
        # both SQLite and the caller's in-memory GameState.
        from ming_sim.decree import atomic_and_reload

        # Defer #670 fresh-summon consumption until every office origin in this
        # batch has been activated — one departure write per person/night.
        previous_summon_nights = getattr(self.conn, "_deferred_office_summon_nights", None)
        previous_reco_prevalidated = getattr(
            self.conn, "_recommendation_snapshots_prevalidated", False,
        )
        self.conn._deferred_office_summon_nights = set()
        self.conn._recommendation_snapshots_prevalidated = True
        try:
            with atomic_and_reload(self, state, content=content):
                for verdict in rows:
                    decision = str(verdict.get("decision") or "")
                    opponents = verdict.get("primary_opponents")
                    snapshot = verdict.get("criteria_snapshot")
                    self.apply_dossier_promulgation(
                        state, strict_int(verdict.get("dossier_id")), decision,
                        blocked_layer=str(verdict.get("blocked_layer") or ""),
                        reason=str(verdict.get("reason") or ""),
                        legal_reason_code=str(verdict.get("legal_reason_code") or ""),
                        primary_opponents=opponents if isinstance(opponents, list) else None,
                        gatekeeper_id=(str(verdict["gatekeeper_id"]).strip()
                                       if verdict.get("gatekeeper_id") is not None else None),
                        criteria_snapshot=snapshot if isinstance(snapshot, dict) else None,
                        content=content,
                    )
                    self._record_dossier_verdict_metadata(
                        state, strict_int(verdict.get("dossier_id")), verdict,
                    )
                summon_nights = set(getattr(self.conn, "_deferred_office_summon_nights", set()) or set())
                if summon_nights:
                    from ming_sim.audience_night import commit_fresh_summons_for_night
                    for night_id in sorted(summon_nights):
                        commit_fresh_summons_for_night(
                            self, state, int(night_id),
                            content=content,
                        )
                # Consumption belongs to the same atomic unit as effect application;
                # an outer settlement rollback restores both effects and this batch.
                self.dossiers.clear_pending_promulgation_verdicts(int(state.turn))
        finally:
            self.conn._recommendation_snapshots_prevalidated = previous_reco_prevalidated
            if previous_summon_nights is None:
                if hasattr(self.conn, "_deferred_office_summon_nights"):
                    delattr(self.conn, "_deferred_office_summon_nights")
            else:
                self.conn._deferred_office_summon_nights = previous_summon_nights

    def interrupt_dossiers_for_character(
        self, state: GameState, character_name: str, reason: str, *,
        commit: bool = True,
    ) -> int:
        owns = self.owns_transaction()
        rows = self.dossiers.open_by_executor(str(character_name))
        materializing = int(getattr(self.conn, "_materializing_dossier_id", 0) or 0)
        rows = [row for row in rows if int(row["id"]) != materializing]
        for row in rows:
            dossier_id = int(row["id"])
            if row["status"] == "promulgated":
                self.dossiers.transition(dossier_id, "executing", commit=False)
            order_id = row["secret_order_id"]
            if order_id is not None:
                order = CharacterKnowledgeStore(self.conn).read_interrupt_dossiers_for_character((int(order_id),))
                if order is not None and order["status"] == "active":
                    previous = str(order["result"] or "")
                    result = "\n".join(x for x in (previous, reason) if x)
                    self.close_secret_order(
                        int(order_id), "failed", result, int(state.turn), commit=False,
                    )
                    continue
            self.record_dossier_execution(
                dossier_id, "failed", reason, state.turn,
                close=True, commit=False,
            )
        self._commit_dossier_write(commit, owns)
        return len(rows)

    def stage_pending_action(
        self, turn: int, kind: str, action: str, minister_name: str,
        payload: Dict[str, object], target_id: Optional[int] = None,
    ) -> int:
        """把一条结构化聊天写动作存进 pending_actions 暂存(status=pending)。返回行 id。
        颁诏时 commit_pending_actions 批量落库;颁诏前不动真实表。

        Secret oral provenance must be pinned by the source turn at the caller;
        another turn's held message is never a valid substitute.
        """
        payload_data: Dict[str, object] = dict(payload or {})
        # #498：开夜期间 stage 的暂存挂 night_id；收夜只交本夜已应允 id
        # CLOSING freezes new staged actions.
        from ming_sim.audience_night import assert_night_accepts_player_input
        open_n = assert_night_accepts_player_input(self, what="暂存")
        night_id = int(open_n["id"]) if open_n is not None else 0
        cur = self.conn.execute(
            """INSERT INTO pending_actions
               (turn, kind, action, target_id, minister_name, payload_json, status,
                night_id, night_approved)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 0)""",
            (
                int(turn), str(kind), str(action),
                None if target_id is None else int(target_id),
                str(minister_name or ""),
                json.dumps(payload_data, ensure_ascii=False),
                night_id,
            ),
        )
        # 与历史 stage 路径一致：非 suspended/atomic 嵌套时提交。
        # 不可用 owns_transaction()——INSERT 已打开隐式事务时它恒 False。
        if (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()
        return int(cur.lastrowid)

    def mark_pending_night_approved(
        self, action_ids: Iterable[int], *, night_id: Optional[int] = None,
        source_chat_turn_id: int = 0,
    ) -> int:
        """标本夜已应允（收夜提交白名单）。返回更新行数。"""
        from ming_sim.audience_night import (
            AudienceNightError,
            NIGHT_STATUS_CLOSED, NIGHT_STATUS_CLOSING,
            assert_night_accepts_player_input, get_night,
            is_pending_source_round,
        )
        night = get_night(self, int(night_id)) if night_id is not None else None
        pending_source = (
            night is not None
            and night["status"] in {NIGHT_STATUS_CLOSING, NIGHT_STATUS_CLOSED}
            and is_pending_source_round(
                self, int(night_id), int(source_chat_turn_id), int(night["turn"]),
            )
        )
        if night is not None and night["status"] == NIGHT_STATUS_CLOSED and not pending_source:
            raise AudienceNightError(
                f"夜已收，不能再应允暂存：{night_id}", code="night_closed",
            )
        if not pending_source:
            assert_night_accepts_player_input(
                self, int(night_id) if night_id is not None else None,
                what="应允暂存",
            )
        ids = [int(i) for i in action_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        params: List[Any] = list(ids)
        extra = ""
        if night_id is not None:
            extra = " AND night_id = ?"
            params.append(int(night_id))
        # #1842：背书随转译挂载荷，不再置 late_endorsement_pending。
        cur = self.conn.execute(
            f"UPDATE pending_actions SET night_approved = 1 "
            f"WHERE id IN ({placeholders}) AND status = 'pending'{extra}",
            params,
        )
        if (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()
        return int(cur.rowcount or 0)

    def attach_pending_action_endorsement(
        self, action_id: int, entry: Mapping[str, object], *, commit: bool = True,
    ) -> None:
        """#1842：把本轮背书挂进暂存载荷 endorsements 列表（不造待背书表）。"""
        aid = int(action_id)
        row = self.conn.execute(
            "SELECT payload_json, status FROM pending_actions WHERE id=?",
            (aid,),
        ).fetchone()
        if row is None:
            raise KeyError(f"暂存动作不存在：{aid}")
        if str(row["status"] or "") != "pending":
            raise ValueError(f"暂存动作状态不可挂背书：{row['status']}")
        payload = load_stored_object(row["payload_json"], label="payload_json")
        form = str(entry.get("form") or "").strip()
        endorser_id = str(entry.get("endorser_id") or "").strip()
        imperial = bool(entry.get("imperial", False))
        source_cid = int(entry.get("source_chat_turn_id") or 0)
        # 暂存阶段尚无 dossier：只验形式/人物/来源轮（与 _validate 同口径）。
        if form == "御笔手敕":
            imperial, endorser_id = True, ""
        if form not in {"会签", "当面站台", "御笔手敕"}:
            raise ValueError("背书形式非法")
        if form == "御笔手敕":
            if not imperial or endorser_id:
                raise ValueError("御笔手敕必须使用御笔标记且不得具名大臣")
        else:
            if imperial or not endorser_id:
                raise ValueError("会签/当面站台必须具名背书人")
            if CharacterStore(self.conn).read_assert_characters_exist((endorser_id,)) is None:
                raise ValueError("背书人物不存在")
        if source_cid <= 0:
            raise ValueError("背书来源对话轮 id 须为正整数")
        if self.conn.execute(
            "SELECT 1 FROM chat_turns WHERE id=?", (source_cid,),
        ).fetchone() is None:
            raise ValueError("背书来源对话轮不存在")
        items = list(payload.get("endorsements") or [])
        if not isinstance(items, list):
            items = []
        # 同轮同形同人去重（INSERT OR IGNORE 同语义）。
        key = (form, endorser_id, imperial, source_cid)
        kept = []
        for raw in items:
            if not isinstance(raw, Mapping):
                continue
            k = (
                str(raw.get("form") or "").strip(),
                str(raw.get("endorser_id") or "").strip(),
                bool(raw.get("imperial", False)),
                int(raw.get("source_chat_turn_id") or 0),
            )
            if k == key:
                continue
            kept.append(dict(raw))
        kept.append({
            "form": form, "endorser_id": endorser_id,
            "imperial": imperial, "source_chat_turn_id": source_cid,
        })
        payload["endorsements"] = kept
        self.conn.execute(
            "UPDATE pending_actions SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), aid),
        )
        if commit and (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()

    def inherit_payload_endorsements(
        self, dossier_id: int, payload: Mapping[str, object], *, commit: bool = False,
    ) -> List[int]:
        """#1842：成案时把载荷 endorsements 继承到案卷（来源仍为声明轮）。"""
        raw_items = payload.get("endorsements") if isinstance(payload, Mapping) else None
        if not isinstance(raw_items, list) or not raw_items:
            return []
        new_ids: List[int] = []
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                continue
            form = str(raw.get("form") or "").strip()
            endorser_id = str(raw.get("endorser_id") or "").strip()
            imperial = bool(raw.get("imperial", False))
            source_cid = int(raw.get("source_chat_turn_id") or 0)
            if form == "御笔手敕":
                imperial, endorser_id = True, ""
            if form not in {"会签", "当面站台", "御笔手敕"} or source_cid <= 0:
                continue
            eid = self.dossiers.add_endorsement(
                int(dossier_id),
                form=form,
                endorser_id=endorser_id,
                imperial=imperial,
                source_chat_turn_id=source_cid,
                commit=False,
            )
            new_ids.append(int(eid))
        if commit and new_ids and (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()
        return new_ids

    def list_night_approved_pending(
        self, night_id: int, *, kind: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        """本夜已应允且仍 pending 的暂存（收夜提交真源）。"""
        if kind is None:
            rows = self.conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, "
                "payload_json, status, night_id, night_approved "
                "FROM pending_actions "
                "WHERE night_id = ? AND night_approved = 1 AND status = 'pending' "
                "ORDER BY id",
                (int(night_id),),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, "
                "payload_json, status, night_id, night_approved "
                "FROM pending_actions "
                "WHERE night_id = ? AND night_approved = 1 AND status = 'pending' "
                "AND kind = ? ORDER BY id",
                (int(night_id), str(kind)),
            ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "kind": r["kind"],
                "action": r["action"],
                "target_id": r["target_id"],
                "minister_name": r["minister_name"],
                "payload_json": r["payload_json"],
                "status": r["status"],
                "night_id": int(r["night_id"] or 0),
                "night_approved": int(r["night_approved"] or 0),
            }
            for r in rows
        ]

    def upsert_pending_directive(
        self, turn: int, minister_name: str, payload: Dict[str, object],
    ) -> int:
        """暂存或原地更新(last-write-wins)一条 kind=directive 拟旨意图(ADR 0006)。
        同一回合同一大臣至多一条 pending directive——新意图覆盖旧(补充=原地更新,非新增态)。
        返回行 id。"""
        from ming_sim.audience_night import assert_night_accepts_player_input
        assert_night_accepts_player_input(self, what="暂存")
        row = self.conn.execute(
            "SELECT id FROM pending_actions "
            "WHERE turn=? AND minister_name=? AND kind='directive' AND status='pending'",
            (int(turn), str(minister_name)),
        ).fetchone()
        if row is not None:
            # #498：同回合可跨两夜（一月多夜）。旧夜遗留的 pending directive 被本夜复用更新时，
            # 必须把归属原子迁到当前开着的夜并清 night_approved，否则本夜应允的
            # WHERE night_id=当前夜 更新零行、收夜漏交、随后被默认同意旁路批交。
            # #502 L5（同缝）：合并保留下划线控制键，正文改草不抹待澄清/夜内态。
            existing_payload = self.conn.execute(
                "SELECT payload_json FROM pending_actions WHERE id=?", (int(row["id"]),),
            ).fetchone()
            merged = self._merge_directive_payload(
                existing_payload["payload_json"] if existing_payload else "{}", payload or {})
            self._discard_pending_decree_forecast(int(row["id"]))
            self.conn.execute(
                "UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0, "
                "version=version+1 WHERE id=?",
                (json.dumps(merged, ensure_ascii=False),
                 self._current_open_night_id(), int(row["id"])),
            )
            self.conn.commit()
            return int(row["id"])
        return self.stage_pending_action(
            turn, kind="directive", action="拟旨",
            minister_name=minister_name, target_id=None, payload=payload,
        )

    def stage_directive_candidate(
        self, turn: int, minister_name: str, payload: Dict[str, object],
    ) -> int:
        """多道模式（#502）：新拟一道**独立**圣旨候选——总是 INSERT 新行、不并进现有候选。
        与 upsert_pending_directive（同回合同大臣至多一条、last-write-wins）互补：本方法给
        「一夜拟多道各自独立」用，前者给「补充/修改当前草稿」用。返回新行 id。"""
        return self.stage_pending_action(
            turn, kind="directive", action="拟旨",
            minister_name=minister_name, target_id=None, payload=payload,
        )

    def update_office_candidate_payload(
        self, candidate_id: int, payload: Dict[str, object],
    ) -> int:
        """#529：原地更新某一道 pending office（任免）候选 payload（特旨/署理路径应答）。

        与 directive 改草同纪律——归属迁到当前开夜并清 night_approved；
        合并保留下划线控制键。返回该行 id（不存在/非 pending office 则 0）。
        """
        from ming_sim.audience_night import assert_night_accepts_player_input
        assert_night_accepts_player_input(self, what="任免路径应答")
        row = self.conn.execute(
            "SELECT id,payload_json,status FROM pending_actions "
            "WHERE id=? AND kind='office'",
            (int(candidate_id),),
        ).fetchone()
        if row is None:
            return 0
        if row["status"] != "pending":
            raise ValueError("已成案任免不得改路径")
        merged = self._merge_underscore_control_keys(row["payload_json"], payload)
        self.conn.execute(
            "UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0 WHERE id=?",
            (json.dumps(merged, ensure_ascii=False),
             self._current_open_night_id(), int(candidate_id)),
        )
        if (
            not bool(getattr(self.conn, "_commit_suspended", False))
            and int(getattr(self.conn, "_atomic_depth", 0) or 0) == 0
        ):
            self.conn.commit()
        return int(candidate_id)

    def update_directive_candidate(
        self, candidate_id: int, payload: Dict[str, object],
    ) -> int:
        """多道模式（#502）：原地更新某一道 pending directive 候选正文（补充/改草，不冻结）。
        与 upsert_pending_directive 更新分支同纪律——把归属迁到当前开着的夜并清 night_approved，
        使本夜应允（WHERE night_id=当前夜）命中、收夜不漏交。返回该行 id（不存在/非 pending 则 0）。
        **合并保留下划线控制键**（_needs_clarification / _directive_status 等）——正文改草不得
        静默抹掉待澄清/夜内态闸（#502 L5，与 flag_directive_needs_clarification 同纪律）。
        #612：player-facing draft mutation 统一走 assert_night_accepts_player_input，CLOSING 拒。"""
        from ming_sim.audience_night import assert_night_accepts_player_input
        assert_night_accepts_player_input(self, what="改草")
        row = self.conn.execute(
            "SELECT id,payload_json,status,version FROM pending_actions "
            "WHERE id=? AND kind='directive'",
            (int(candidate_id),),
        ).fetchone()
        if row is None:
            return 0
        if row["status"] != "pending":
            raise ValueError("已成案旨意不得改草")
        merged = self._merge_directive_payload(row["payload_json"], payload)
        self._discard_pending_decree_forecast(int(row["id"]), int(row["version"] or 1))
        self.conn.execute(
            "UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0, "
            "version=version+1 WHERE id=?",
            (json.dumps(merged, ensure_ascii=False),
             self._current_open_night_id(), int(candidate_id)),
        )
        self.conn.commit()
        return int(candidate_id)

    def _discard_deleted_directive_forecast(self, target_id: object) -> None:
        try:
            pending_id = int(target_id)
        except (TypeError, ValueError):
            return
        row = self.conn.execute(
            "SELECT kind, version FROM pending_actions WHERE id=?",
            (pending_id,),
        ).fetchone()
        if row is None or str(row["kind"] or "") != "directive":
            return
        self._discard_pending_decree_forecast(pending_id, int(row["version"] or 1))

    def _discard_pending_decree_forecast(
        self, candidate_id: int, version: Optional[int] = None,
    ) -> int:
        if version is None:
            row = self.conn.execute(
                "SELECT version FROM pending_actions WHERE id=? AND kind='directive'",
                (int(candidate_id),),
            ).fetchone()
            if row is None:
                return 0
            version = int(row["version"] or 1)
        from ming_sim.declaration_dispatch import (
            discard_staged_declaration, pending_action_decree_ref,
        )
        return discard_staged_declaration(
            self, pending_action_decree_ref(int(candidate_id), int(version)),
        )

    @staticmethod
    def _merge_underscore_control_keys(
        existing_json: object, new_payload: Dict[str, object],
    ) -> Dict[str, object]:
        """把新 payload 与旧 payload 里的下划线控制键（`_` 前缀）合并：新 payload 为主，
        旧的下划线键在新里缺席时保留。用于原地改草不抹夜内态/待澄清闸（#502 L5）。"""
        old = load_stored_object(existing_json, label="payload_json")
        merged: Dict[str, object] = dict(new_payload or {})
        for k, v in old.items():
            if str(k).startswith("_") and k not in merged:
                merged[k] = v
        return merged

    def _merge_directive_payload(
        self, existing_json: object, new_payload: Dict[str, object],
    ) -> Dict[str, object]:
        """改草保留未修改的机械字段；显式新值覆盖后统一校验。

        #658：普通 triad 与御笔 target 互斥生命周期——
        普通改草不得继承旧 target；纯强推改草不得继承旧 triad。
        """
        old = self._decode_directive_dossier_payload(existing_json)
        incoming = dict(new_payload or {})
        old_roster = self._normalize_participant_roster(old.get("participant_roster") or [])
        new_roster = self._normalize_participant_roster(incoming.get("participant_roster") or [])
        if not new_roster:
            incoming.pop("participant_roster", None)
        else:
            incoming["participant_roster"] = old_roster + [
                item for item in new_roster if item not in old_roster
            ]
        # 先对 incoming 互斥分类（并存即拒），再决定从 old 继承哪些字段
        incoming_kind = (
            classify_directive_structured_kind(incoming)
            if incoming else "empty"
        )
        merged = {**old, **incoming}
        if incoming_kind == "ordinary":
            merged.pop("target_dossier_id", None)
            merged.pop("目标案卷ID", None)
        elif incoming_kind == "push":
            # 只清互斥 ordinary triad，保留 text/actor 等非互斥字段
            for key in ("dossier_action_type", "target_kind", "target_id"):
                merged.pop(key, None)
            push_id = imperial_push_target_dossier_id(incoming)
            if push_id is None:
                push_id = imperial_push_target_dossier_id(merged)
            if push_id is not None:
                merged["target_dossier_id"] = push_id
                merged.pop("目标案卷ID", None)
        # 合并结果再过互斥权威（old 残留 + incoming 部分字段仍可能冲突）
        classify_directive_structured_kind(merged)
        requested = str(merged.get("dossier_action_type") or "")
        if incoming_kind == "push":
            # 复用既有 push 归一化（保留 text/actor/mode）
            return self._normalize_directive_dossier_payload(
                merged, content=self.content,
                current_turn=int(ReignStateStore(self.conn).read_record_dossier_decision()["turn"]),
            )
        normalized = self._normalize_directive_dossier_payload(
            merged, content=self.content,
            current_turn=int(ReignStateStore(self.conn).read_record_dossier_decision()["turn"]),
        )
        if requested and normalized.get("dossier_action_type") != requested:
            raise ValueError("旨稿机械载荷不完整或非法，拒绝改草")
        return normalized

    def clear_directive_needs_clarification(self, candidate_id: int) -> int:
        """清某道 pending directive 的「待澄清」标（#502 L4）：皇帝下一句指明并准驳后，
        含糊 episode 了结——被点名与其兄弟一并复位为普通 pending（未点名者重回「不回→默认同意」
        通道）。返回该行 id（不存在/非 pending 则 0）。
        #612：player-facing draft mutation，CLOSING 与改草同拒。"""
        from ming_sim.audience_night import assert_night_accepts_player_input
        assert_night_accepts_player_input(self, what="改草")
        row = self.conn.execute(
            "SELECT id, payload_json FROM pending_actions "
            "WHERE id=? AND kind='directive' AND status='pending'",
            (int(candidate_id),),
        ).fetchone()
        if row is None:
            return 0
        payload = load_stored_object(row["payload_json"], label="payload_json")
        if "_needs_clarification" not in payload:
            return int(candidate_id)
        payload.pop("_needs_clarification", None)
        self.conn.execute(
            "UPDATE pending_actions SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), int(candidate_id)),
        )
        self.conn.commit()
        return int(candidate_id)

    def list_night_promulgated_directives(self, night_id: int) -> List[Dict[str, object]]:
        """按夜取数（#502 AC6 / #612）：本夜已落公开层明发账的旨。

        只认唯一 exact engine-command publication-fact seam（口令账上的精确
        明发#directive_id），不以 pending_actions committed 等同已明发，也不认
        抽取账开放 tags 或畸形后缀。收夜可先落 draft 前提，抽取失败时那些
        committed 行仍非公开明发投影。机器辨识、零自由文本解析。"""
        from ming_sim.audience_night import (
            engine_command_mingfa_publication_ids,
            list_ledger,
        )
        ids = sorted(
            engine_command_mingfa_publication_ids(list_ledger(self, int(night_id)))
        )
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"""
            SELECT td.id AS directive_id, td.turn, td.year, td.period,
                   td.actor, td.text, td.status
            FROM turn_directives td
            WHERE td.id IN ({placeholders})
            ORDER BY td.id
            """,
            ids,
        ).fetchall()
        return [
            {
                "directive_id": int(r["directive_id"]), "turn": int(r["turn"]),
                "year": int(r["year"]), "period": int(r["period"]),
                "actor": r["actor"] or "", "text": r["text"] or "", "status": r["status"] or "",
            }
            for r in rows
        ]

    def list_promulgated_directives(
        self, turn_from: Optional[int] = None, turn_to: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """按区间取数（#502 AC6 / #612）：回合区间内已落公开层明发账的旨（含所属夜 id）。

        turn_from/to 为闭区间；留空则不设该端界。与 list_night_promulgated_directives
        同源：唯一 exact engine-command publication-fact seam，不以 committed
        pending_actions 等同明发，不认抽取账开放 tags 或畸形后缀。

        JSON 解码前按 audience_nights.turn 权威关系收窄 ledger；exact tag 仍只由
        现有 helper 判定。
        """
        from ming_sim.audience_night import (
            _json_list,
            engine_command_mingfa_publication_facts,
        )
        clauses = ["1=1"]
        params: List[object] = []
        if turn_from is not None:
            clauses.append("n.turn >= ?")
            params.append(int(turn_from))
        if turn_to is not None:
            clauses.append("n.turn <= ?")
            params.append(int(turn_to))
        where = " AND ".join(clauses)
        ledger_rows = self.conn.execute(
            f"""
            SELECT e.night_id AS night_id, e.tags AS tags,
                   e.source_chat_turn_id AS source_chat_turn_id,
                   n.turn AS night_turn
            FROM story_ledger_entries e
            JOIN audience_nights n ON n.id = e.night_id
            WHERE {where}
            """,
            params,
        ).fetchall()
        entries = [
            {
                "night_id": int(row["night_id"] or 0),
                "tags": [str(tag) for tag in _json_list(row["tags"])],
                "source_chat_turn_id": int(row["source_chat_turn_id"] or 0),
            }
            for row in ledger_rows
        ]
        night_turn_by_id = {
            int(row["night_id"] or 0): int(row["night_turn"] or 0)
            for row in ledger_rows
        }
        facts = engine_command_mingfa_publication_facts(entries)
        if not facts:
            return []
        ids = sorted({directive_id for _night_id, directive_id in facts})
        placeholders = ",".join("?" * len(ids))
        td_rows = self.conn.execute(
            f"""
            SELECT td.id AS directive_id, td.turn, td.actor, td.text, td.status
            FROM turn_directives td
            WHERE td.id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        by_id = {
            int(r["directive_id"]): {
                "directive_id": int(r["directive_id"]),
                "turn": int(r["turn"]),
                "actor": r["actor"] or "",
                "text": r["text"] or "",
                "status": r["status"] or "",
            }
            for r in td_rows
        }
        out: List[Dict[str, object]] = []
        for night_id, directive_id in sorted(
            facts,
            key=lambda item: (
                night_turn_by_id.get(item[0], by_id.get(item[1], {}).get("turn", 0)),
                item[1],
                item[0],
            ),
        ):
            base = by_id.get(directive_id)
            if base is None:
                continue
            # Prefer night.turn (SQL-narrowed authority); fall back to directive.turn.
            turn = int(night_turn_by_id.get(int(night_id), int(base["turn"])))
            out.append({
                "directive_id": int(base["directive_id"]),
                "turn": turn,
                "night_id": int(night_id),
                "actor": base["actor"],
                "text": base["text"],
                "status": base["status"],
            })
        return out

    def flag_directive_needs_clarification(self, candidate_id: int) -> int:
        """含糊准驳（#502 AC5）：给 pending directive 候选打「待澄清」标，使其**不被**颁诏/过回合
        「不回→默认同意」误提交（含糊口令 ≠ 未表态）。皇帝下一句指明后由确认路清标并准驳。
        返回该行 id（不存在/非 pending 则 0）。
        #612：player-facing draft mutation，CLOSING 与改草同拒。"""
        from ming_sim.audience_night import assert_night_accepts_player_input
        assert_night_accepts_player_input(self, what="改草")
        row = self.conn.execute(
            "SELECT id, payload_json FROM pending_actions "
            "WHERE id=? AND kind='directive' AND status='pending'",
            (int(candidate_id),),
        ).fetchone()
        if row is None:
            return 0
        payload = load_stored_object(row["payload_json"], label="payload_json")
        payload["_needs_clarification"] = True
        self.conn.execute(
            "UPDATE pending_actions SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), int(candidate_id)),
        )
        self.conn.commit()
        return int(candidate_id)

    def list_pending_actions(
        self, turn: int, status: str = "pending", minister_name: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        """读本回合待确认动作(默认 pending),按 id 序(=操作发生序)。
        minister_name 非空时只取该召对对象的暂存(对话确认按当前大臣过滤,不波及他人)。"""
        if minister_name is None:
            rows = self.conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
                "FROM pending_actions WHERE turn = ? AND status = ? ORDER BY id",
                (int(turn), str(status)),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
                "FROM pending_actions WHERE turn = ? AND status = ? AND minister_name = ? ORDER BY id",
                (int(turn), str(status), str(minister_name)),
            ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "kind": r["kind"],
                "action": r["action"],
                "target_id": None if r["target_id"] is None else int(r["target_id"]),
                "minister_name": r["minister_name"],
                "payload_json": r["payload_json"],
                "status": r["status"],
            }
            for r in rows
        ]

    def list_failed_secret_order_actions(
        self, minister_name: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        sql = (
            "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
            "FROM pending_actions WHERE status='failed' AND kind='secret_order'"
        )
        params: tuple[object, ...] = ()
        if minister_name is not None:
            sql += " AND minister_name=?"
            params = (str(minister_name),)
        sql += " ORDER BY turn DESC, id"
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "kind": r["kind"],
                "action": r["action"],
                "target_id": None if r["target_id"] is None else int(r["target_id"]),
                "minister_name": r["minister_name"],
                "payload_json": r["payload_json"],
                "status": r["status"],
            }
            for r in rows
        ]

    def _prepare_pending_directive(
        self, state: GameState, pa: Dict[str, object], *, content=None,
        allow_clarification: bool = False,
    ) -> Dict[str, object]:
        """Classify and, only when valid, project one staged directive."""
        if (
            pa.get("status") != "pending"
            or pa.get("kind") != "directive"
            or pa.get("action") != "拟旨"
        ):
            return {"classification": "invalid"}
        payload = load_stored_object(pa.get("payload_json"), label="payload_json")
        if payload.get("_needs_clarification") and not allow_clarification:
            return {"classification": "needs_clarification"}
        try:
            payload = self._normalize_directive_dossier_payload(
                payload, content=content, current_turn=int(state.turn),
            )
        except (TypeError, ValueError):
            return {"classification": "invalid"}
        text = str(payload.get("text") or "")
        if not text.strip():
            return {"classification": "invalid"}
        actor = str(payload.get("actor") or pa.get("minister_name") or "").strip()
        payload["text"] = text
        payload["actor"] = actor
        return {
            "classification": "valid",
            "id": -int(pa["id"]),
            "text": text,
            "turn": int(pa["turn"]),
            "status": "pending",
            "source": "pending_action",
            "actor": actor,
            "pending_action_id": int(pa["id"]),
            "payload": payload,
        }

    def preview_pending_directives(
        self, state: GameState, *, content=None,
    ) -> List[Dict[str, object]]:
        """Read-only default-approval view, using the commit owner's rules."""
        previews = []
        for pa in self.list_pending_actions(int(state.turn)):
            prepared = self._prepare_pending_directive(state, pa, content=content)
            if prepared["classification"] == "valid":
                preview = dict(prepared)
                preview.pop("classification", None)
                preview.pop("payload", None)
                previews.append(preview)
        return previews

    def commit_pending_actions(
        self, state: GameState, *, content=None, minister_name=None,
        kind_filter: Optional[str] = None, kind_filter_exclude: Optional[str] = None,
        directive_status: str = "draft", action_ids: Optional[Iterable[int]] = None,
        rejection_collector=None,
    ) -> List[Dict[str, object]]:
        """颁诏:把本回合 pending 暂存的结构化写动作批量落到真实表(不拒绝即允许),
        按 id 序(=操作发生序)apply。落得了标 committed、落不了标 failed(都不留 pending,
        故幂等:已 committed/失败/held_over 不在 pending 清单、不重跑)。
        #525：held_over 留中档由同表 durable 保留、本终端只读 pending，故默认提交跳过留中。
        在月链世界段之前调，使后续步骤读到已落账的聊天动作。
        content 用于任免落库；无聊天暂存时为 no-op。
        minister_name 非空=对话确认当场 commit:只落该召对对象的暂存(应允即落,不波及他人);
        action_ids 非空=进一步只落指定 pending_actions.id（召对确认只可作用于本轮开始前可见项）;
        默认 None=颁诏批量落全回合。
        kind_filter 非空=只 commit 指定 kind(如 'directive')的暂存,跳过其余 kind。
        kind_filter_exclude 非空=只 commit 该 kind 以外的暂存(召对确认应允放过 directive,BUG 1)。
        directive_status controls how kind=directive candidates enter turn_directives:
        "draft" for decree-checkpoint default approval, "pending" for chat-approved
        candidates that must still pass the later准/驳 interface.
        返回已落库动作摘要。"""
        if kind_filter is not None and kind_filter_exclude is not None:
            raise ValueError("kind_filter and kind_filter_exclude are mutually exclusive")
        if directive_status not in ("draft", "pending"):
            raise ValueError("directive_status must be 'draft' or 'pending'")
        # 0150-D2 / #1745：无 owns_rejection_collector 自建；外层传入则沿用，缺则嵌套拒收响亮。
        applied: List[Dict[str, object]] = []
        rows = self.list_pending_actions(
            int(state.turn), status="pending", minister_name=minister_name)
        if kind_filter is not None:
            rows = [r for r in rows if r["kind"] == kind_filter]
        if kind_filter_exclude is not None:
            rows = [r for r in rows if r["kind"] != kind_filter_exclude]
        if action_ids is not None:
            allowed_ids = {int(action_id) for action_id in action_ids}
            rows = [r for r in rows if int(r["id"]) in allowed_ids]
        owns_transaction = not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
        )
        for pa in rows:
            if pa["kind"] == "directive" and pa["action"] == "拟旨":
                prepared = self._prepare_pending_directive(
                    state, pa, content=content,
                    allow_clarification=action_ids is not None,
                )
                classification = prepared["classification"]
                if classification == "needs_clarification":
                    continue
                if classification == "invalid":
                    cm = atomic(self) if owns_transaction else contextlib.nullcontext()
                    with cm:
                        self.conn.execute(
                            "UPDATE pending_actions SET status='failed' WHERE id=?",
                            (int(pa["id"]),),
                        )
                    continue
                payload = dict(prepared["payload"])
                payload["_canonical_pending_directive"] = True
                committed = self._commit_conversational_draft(
                    state, pa, payload, content=content,
                    directive_status=directive_status,
                    rejection_collector=rejection_collector)
                if committed is not None:
                    applied.append(committed)
                continue
            payload = load_stored_object(pa["payload_json"], label="payload_json")
            # apply 抛错(如 催办 对已非 active 的密令)= 当 False:下面标 failed、
            # 不中断本轮其余动作、更不能崩整个结算(CMR P0)。
            cm = atomic(self) if owns_transaction else contextlib.nullcontext()
            with cm:
                savepoint = f"pending_action_apply_{int(pa['id'])}"
                ok = False
                office_memory_key = None
                office_memory_before = None
                office_memory_had_key = False
                if pa["kind"] == "office" and content is not None:
                    office_memory_key = str(payload.get("name") or "").strip()
                    if office_memory_key:
                        office_memory_had_key = office_memory_key in content.characters
                        office_memory_before = content.characters.get(office_memory_key)

                def restore_office_memory() -> None:
                    if not office_memory_key:
                        return
                    if office_memory_had_key:
                        content.characters[office_memory_key] = office_memory_before
                    else:
                        content.characters.pop(office_memory_key, None)

                self.conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    ok = self._apply_pending_action(
                        state, pa, payload, content=content,
                        rejection_collector=rejection_collector)
                    if ok:
                        self.conn.execute(
                            "UPDATE pending_actions SET status='committed' WHERE id=?", (int(pa["id"]),))
                    else:
                        self.conn.execute(f"ROLLBACK TO {savepoint}")
                        restore_office_memory()
                        # 落不了的(目标已非 active、未知动作、坏 payload)标 failed,不留 pending——
                        # 否则回合推进后成旧回合不可见死行,永不再处理(ship-pre CMR codex)。
                        self.conn.execute(
                            "UPDATE pending_actions SET status='failed' WHERE id=?", (int(pa["id"]),))
                except Exception as exc:
                    self.conn.execute(f"ROLLBACK TO {savepoint}")
                    restore_office_memory()
                    # 0150-D2 / #1745：typed 归属缺口不得吞成 pending failed。
                    from ming_sim.applier import RejectionCollectorRequired
                    if isinstance(exc, RejectionCollectorRequired):
                        raise
                    rejection = getattr(exc, "dossier_link_rejection", None)
                    if rejection is not None:
                        self.dossiers.record_link_rejection(
                            *rejection, pending_action_id=int(pa["id"]),
                        )
                    tlog(f"[pending_actions] 落库失败 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
                    ok = False
                    self.conn.execute(
                        "UPDATE pending_actions SET status='failed' WHERE id=?", (int(pa["id"]),))
                finally:
                    self.conn.execute(f"RELEASE {savepoint}")
                if rejection_collector is not None:
                    rejection_collector.flush_to_db(self)
            if ok:
                item: Dict[str, object] = {
                    "id": pa["id"],
                    "kind": pa["kind"],
                    "action": pa["action"],
                    "target_id": pa["target_id"],
                }
                # #1376：新建密令落库后把真实 order id 回传确认面（stage 时 target_id 为空）。
                if pa["kind"] == "secret_order" and str(pa["action"] or "") == "新建":
                    row = self.dossiers.secret_order_for_pending(int(pa["id"]))
                    if row is not None and row["secret_order_id"] is not None:
                        item["secret_order_id"] = int(row["secret_order_id"])
                    else:
                        from ming_sim.covert_progress import (
                            build_covert_task_contract,
                            covert_task_from_payload,
                            find_active_investigation_order_id,
                            _investigation_target_of,
                        )
                        raw_task = covert_task_from_payload(payload) or payload.get("covert_task")
                        if raw_task:
                            frozen = build_covert_task_contract(covert_task=raw_task) or {}
                            inv_target = _investigation_target_of(frozen)
                            if inv_target:
                                merged_oid = find_active_investigation_order_id(self, inv_target)
                                if merged_oid > 0:
                                    item["secret_order_id"] = int(merged_oid)
                applied.append(item)
        # 镜像归外层 collector owner（0150-D2；本方法不自建不自镜像）。
        return applied

    @staticmethod
    def _state_for_turn(state: GameState, turn: int) -> GameState:
        """按 turn 回推当时的 year/period；metrics 共享只读。"""
        delta = int(state.turn) - int(turn)
        year = int(state.year)
        period = int(state.period)
        for _ in range(max(0, delta)):
            period -= 1
            if period < 1:
                period = 12
                year -= 1
        return replace(state, year=year, period=period, turn=int(turn))

    def _commit_conversational_draft(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None, directive_status: str = "draft",
        rejection_collector=None,
    ) -> Optional[Dict[str, object]]:
        """提交一条对话式拟旨暂存，并让 draft 行与 pending 状态同事务落定。"""
        owns_transaction = not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
        )
        cm = atomic(self) if owns_transaction else contextlib.nullcontext()
        result = None
        try:
            with cm:
                savepoint = f"pending_action_directive_{int(pa['id'])}"
                self.conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    payload_for_apply = dict(payload)
                    payload_for_apply["_directive_status"] = directive_status
                    ok = self._apply_pending_action(
                        state, pa, payload_for_apply, content=content,
                        rejection_collector=rejection_collector)
                    if ok:
                        self.conn.execute(
                            "UPDATE pending_actions SET status='committed' WHERE id=?",
                            (int(pa["id"]),),
                        )
                        result = {"id": pa["id"], "kind": pa["kind"],
                                  "action": pa["action"], "target_id": pa["target_id"]}
                    else:
                        self.conn.execute(f"ROLLBACK TO {savepoint}")
                        self.conn.execute(
                            "UPDATE pending_actions SET status='failed' WHERE id=?",
                            (int(pa["id"]),),
                        )
                except Exception as exc:
                    # #654 r3-C.2 路1：directive 特路与通用分支同款——回滚后标 failed，不崩结算
                    self.conn.execute(f"ROLLBACK TO {savepoint}")
                    # 0150-D2 / #1745：typed 归属缺口不得吞成 pending failed。
                    from ming_sim.applier import RejectionCollectorRequired
                    if isinstance(exc, RejectionCollectorRequired):
                        raise
                    self.conn.execute(
                        "UPDATE pending_actions SET status='failed' WHERE id=?",
                        (int(pa["id"]),),
                    )
                    tlog(
                        f"[pending_actions] 落库失败标 failed id={pa['id']} "
                        f"{pa['kind']}/{pa['action']}：{exc}"
                    )
                    result = None
                finally:
                    self.conn.execute(f"RELEASE {savepoint}")
                if rejection_collector is not None:
                    rejection_collector.flush_to_db(self)
        except Exception as exc:
            tlog(f"[pending_actions] 落库异常 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
            raise
        return result

    def _apply_pending_action(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None, rejection_collector=None,
    ) -> bool:
        """把单条暂存动作落到真实表。未知 kind/action 或目标非 active 不落、返 False(由
        commit_pending_actions 标 failed,不静默丢——终态失败,不再重试)。
        office(任免)落库需 content；缺则返 False(标 failed,不静默)。"""
        if pa["kind"] == "office":
            return self._materialize_office_appointment_dossier(
                state, pa, payload, content=content,
            )
        if pa["kind"] == "secret_order":
            oid = pa["target_id"]
            if pa["action"] == "新建":
                title = str(payload.get("title") or "").strip()
                content_text = str(payload.get("content") or "")
                assignee = str(payload.get("assignee") or pa["minister_name"] or "").strip()
                if not title or not content_text.strip() or not assignee:
                    return False
                tags_raw = payload.get("tags") or []
                tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
                deadline = _coerce_deadline_months(payload.get("deadline_months"), default=0)
                excluded = payload.get("excluded_names") or []
                excluded = [str(t).strip() for t in excluded if str(t).strip()] if isinstance(excluded, list) else []
                excluded_offices = payload.get("excluded_offices") or []
                excluded_offices = [str(t).strip() for t in excluded_offices if str(t).strip()] if isinstance(excluded_offices, list) else []
                # pa["minister_name"] = audience speaker who captured the oral
                # decree; may differ from final assignee (跨人承办).
                # Stage-time pin: do not re-guess max(held) after confirm utterance.
                origin_mid = self._parse_origin_chat_message_id(payload)
                from ming_sim.covert_progress import (
                    CovertContractError,
                    build_covert_task_contract,
                    covert_task_from_payload,
                )
                raw_task = covert_task_from_payload(payload) or payload.get("covert_task")
                if not raw_task:
                    raise CovertContractError("密令确认缺少差务类型")
                frozen_task = build_covert_task_contract(covert_task=raw_task)
                order_id = self.create_secret_order(
                    state, assignee, title, content_text, tags, deadline_months=deadline,
                    excluded_names=excluded, excluded_offices=excluded_offices,
                    origin_minister_name=str(pa.get("minister_name") or "") or None,
                    origin_chat_message_id=origin_mid,
                    origin_chat_message_ids=[] if origin_mid is None else None,
                    pending_action_id=int(pa["id"]),
                    covert_task=frozen_task,
                )
                if order_id is not None and payload.get("dossier_links") is not None:
                    links = payload.get("dossier_links")
                    if not isinstance(links, list):
                        raise ValueError("密令案卷关联必须为列表")
                    dossier = self.dossiers.get_for_secret_order(int(order_id))
                    if dossier is None:
                        raise ValueError("密令成案后未找到案卷")
                    self.dossiers.add_links(
                        int(dossier["id"]), links, commit=False,
                    )
                return order_id is not None
            if oid is None:
                return False
            # Non-create: consume explicit stage/API pin only.  No auto-pin of
            # latest held (pure public must not become secret-origin withheld).
            # No pin → skip classify (do not invent bloodline; pure public stays
            # held until settle release, never withheld).
            origin_mid = self._parse_origin_chat_message_id(payload)
            origin_speaker = str(pa.get("minister_name") or "") or None
            if pa["action"] == "更新":
                deadline = _coerce_deadline_months(payload.get("deadline_months"), default=0)
                # No pin → update_secret_order_by_id preserves brief pins (no pure-public auto-capture).
                return self.update_secret_order_by_id(
                    state, int(oid),
                    str(payload.get("new_title") or ""),
                    str(payload.get("new_content") or ""),
                    tags=None, deadline_months=deadline,
                    origin_minister_name=origin_speaker,
                    origin_chat_message_id=origin_mid,
                )
            if pa["action"] == "催办":
                deadline = _coerce_deadline_months(payload.get("deadline_months", 1), default=1)
                self.rush_secret_order(
                    int(oid), state, deadline_months=deadline, reason=str(payload.get("reason") or ""))
                if origin_mid is not None:
                    order = self.get_secret_order(int(oid))
                    if order is not None:
                        self._classify_secret_order_audience(
                            state, int(oid), str(order["minister_name"]),
                            str(order.get("title") or ""), str(order.get("content") or ""),
                            origin_minister_name=origin_speaker,
                            origin_chat_message_id=origin_mid,
                        )
                return True
            if pa["action"] == "提交核议":
                ok = self.submit_secret_order_for_review(
                    int(oid), str(payload.get("claim") or ""), state.year, state.period)
                if ok and origin_mid is not None:
                    order = self.get_secret_order(int(oid))
                    if order is not None:
                        self._classify_secret_order_audience(
                            state, int(oid), str(order["minister_name"]),
                            str(order.get("title") or ""), str(order.get("content") or ""),
                            origin_minister_name=origin_speaker,
                            origin_chat_message_id=origin_mid,
                        )
                return ok
            if pa["action"] == "记进展":
                ok = self.update_secret_order_progress(
                    int(oid), str(payload.get("note") or ""), state.year, state.period)
                if ok and origin_mid is not None:
                    order = self.get_secret_order(int(oid))
                    if order is not None:
                        self._classify_secret_order_audience(
                            state, int(oid), str(order["minister_name"]),
                            str(order.get("title") or ""), str(order.get("content") or ""),
                            origin_minister_name=origin_speaker,
                            origin_chat_message_id=origin_mid,
                        )
                return ok
        # #624 / ADR 0078：分段承诺催办——经 pending_actions 确认闸门到唯一写口
        if pa["kind"] == "commitment" and pa["action"] == "催办":
            target_id = pa.get("target_id")
            if target_id is None:
                return False
            try:
                stage_idx = int(payload.get("stage_idx") if payload.get("stage_idx") is not None else 0)
            except (TypeError, ValueError):
                stage_idx = 0
            deadline = _coerce_deadline_months(payload.get("deadline_months", 1), default=1)
            from ming_sim.urge_lever import rush_staged_commitment_stage
            result = rush_staged_commitment_stage(
                self, state,
                commitment_ref=int(target_id),
                stage_idx=stage_idx,
                deadline_months=deadline,
                reason=str(payload.get("reason") or ""),
                commit=False,
                record_history=False,  # 本 pending 行标 committed 即史源，禁双插
            )
            # 史源字段写回本行 payload（commit_pending_actions 随后标 committed）
            merged = dict(payload)
            merged.update({
                "stage_idx": int(stage_idx),
                "old_due": int(result["old_due"]),
                "new_due": int(result["due_turn"]),
                "deadline_months": int(result["deadline_months"]),
                "tightness": max(0, int(result["old_due"]) - int(result["due_turn"])),
                "reason": str(result.get("reason") or ""),
            })
            self.conn.execute(
                "UPDATE pending_actions SET payload_json=? WHERE id=?",
                (
                    json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
                    int(pa["id"]),
                ),
            )
            return True
        if pa["kind"] == "directive" and pa["action"] == "拟旨":
            payload = dict(payload)
            if payload.pop("_canonical_pending_directive", False) is not True:
                payload = self._normalize_directive_dossier_payload(
                    payload, content=content, current_turn=int(state.turn),
                )
            text = str(payload.get("text") or "")
            actor = str(payload.get("actor") or pa["minister_name"] or "")
            if not text.strip():
                return False
            status = "pending" if str(payload.get("_directive_status") or "draft") == "pending" else "draft"
            # 不回到颁诏 checkpoint 时默认同意为 draft；召对里明确应允只表示接受为候选，
            # 仍写成 pending 交给既有准/驳界面，避免绕过后续颁诏流程（#412）。
            cur = self.conn.execute(
                """
                INSERT INTO turn_directives
                (turn, year, period, event_id, actor, text, source, status,
                 notes,dossier_payload_json)
                VALUES (?, ?, ?, NULL, ?, ?, '大臣拟旨', ?, ?, ?)
                """,
                (
                    state.turn, state.year, state.period, actor, text, status,
                    f"由{actor}拟旨入档",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            did = int(cur.lastrowid)
            # 回填本暂存产生的 draft 行 id，供 undo_chat_turn 精确删除（BUG 3）；turn_directives
            # 行时序晚于 chat 快照、不在 rollback_items，需此 id 才能只删本轮自产的草案。
            self.conn.execute(
                "UPDATE pending_actions SET committed_directive_id=? WHERE id=?",
                (int(did), int(pa["id"])),
            )
            # pending 只是皇帝核定前的候选，不是 ADR 0051 的成案点；默认同意进入
            # draft 时则已越过最终提交边界，应当立即取得案卷身份。
            # #658：与 free-form / confirm 共吃 _ensure_directive_dossier（含御笔强推）。
            if status == "draft":
                dossier_ids = self._ensure_directive_dossier(
                    state, did, text, payload, commit=False,
                )
                # conversational commit 的 pending_action_id 绑回案卷（push 复用路径
                # 只写 directive_id，普通 create 路径本就带 pending_action_id）
                self.dossiers.bind_pending_action(int(did), int(pa["id"]))
                # #1842：载荷背书随成案继承到案卷（来源仍为声明轮）。
                for dossier_id in dossier_ids or []:
                    self.inherit_payload_endorsements(
                        int(dossier_id), payload, commit=False,
                    )
                # ADR 0028 / #1837：组合载荷（拨帑±任免）同一份 pending 同时产任免案卷；
                # 任免字段只进 appointment 案卷，禁把 grant 的 execution_surface 带过去。
                if not self._materialize_combined_appointment_from_directive(
                    state, pa, payload, content=content,
                ):
                    return False
            return True
        return False

    @staticmethod
    def _appointment_slice_from_combined_payload(
        payload: Dict[str, object],
    ) -> Optional[Dict[str, object]]:
        """从组合 directive 载荷抽出任免字段；无任免声明返 None。

        只保留任免成案所需键，剥离 grant 的 execution_surface / amount 等，
        避免 appointment 案卷撞「execution_surface 与案卷动作策略不符」。
        """
        action = str(payload.get("appoint_action") or "").strip()
        name = str(payload.get("name") or "").strip()
        if action not in {"任命", "罢免"} or not name:
            return None
        office = str(payload.get("office") or "").strip()
        if action == "任命" and not office:
            return None
        sliced: Dict[str, object] = {
            "name": name, "office": office, "appoint_action": action,
        }
        for key in (
            "appointment_tenure", "任别", "faction", "summon_after",
            "text", "affair_id", "region_id", "endorsements", "reason", "recommendation",
        ):
            value = payload.get(key)
            if value not in (None, ""):
                sliced[key] = value
        return sliced

    def _materialize_combined_appointment_from_directive(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None,
    ) -> bool:
        """组合 directive 载荷上的任免 → 既有 office 成案核；无任免字段则 no-op 成功。"""
        sliced = self._appointment_slice_from_combined_payload(payload)
        if sliced is None:
            return True
        office_pa = {
            "id": pa["id"],
            "kind": "office",
            "action": str(sliced["appoint_action"]),
            "minister_name": str(
                pa.get("minister_name") or payload.get("actor") or ""
            ),
        }
        decree_text = str(payload.get("text") or sliced.get("text") or "")
        return self._materialize_office_appointment_dossier(
            state, office_pa, sliced, content=content,
            decree_text=decree_text if decree_text.strip() else None,
        )

    def _materialize_office_appointment_dossier(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None, decree_text: Optional[str] = None,
    ) -> bool:
        """任免案卷唯一成案核：kind=office 与组合 directive 同伴共用，不平行第二套。"""
        name = str(payload.get("name") or "").strip()
        office = str(payload.get("office") or "").strip()
        action = str(pa.get("action") or payload.get("appoint_action") or "").strip()
        if not name or (action == "任命" and not office):
            return False
        if content is None:
            return False
        from ming_sim.session import _find_existing_minister
        canonical = _find_existing_minister(content, name, self)
        if canonical:
            row = CharacterStore(self.conn).read_materialize_office_appointment_dossier((canonical,))
            if row is None or str(row["power_id"] or "ming") != "ming":
                return False
            if action == "任命" and row["status"] == "dead":
                return False
            if action == "罢免" and row["status"] != "active":
                return False
        elif action == "罢免":
            return False
        if canonical:
            name = canonical
        elif (
            action == "任命"
            and infer_office_type_from_office(office, "", self.llm_config) != "后宫"
        ):
            # 任命准旨成案前只登记朝臣身份。
            # 授官/激活仍只由顺颁后的
            # _commit_office_action -> apply_office_appointment 完成。
            from ming_sim.models import Character
            from ming_sim.session import canonical_new_appointment_person_fields
            character = Character(
                name=name, office="待选", office_type="未仕",
                aliases=[], personal_skills=[], power_id="ming",
                status="offstage",
                **canonical_new_appointment_person_fields(
                    content, payload.get("faction"),
                ),
            )
            content.characters[name] = character
            self.add_character(
                state, character,
                source="任命准旨身份登记", commit=False,
            )
        staged_payload = dict(payload)
        staged_payload["name"] = name
        staged_payload["_office_action"] = action
        staged_payload["_minister_name"] = str(pa.get("minister_name") or "")
        # 纯 office 与组合路径同核：优先声明/payload 原样 text（P7）。
        # 缺少唯一原文真源时拒绝物化；不得替 LLM 拼玩家可感正文。
        text = str(decree_text or staged_payload.get("text") or "")
        if not text.strip():
            return False
        dossier_id = self.create_decree_dossier(
            state,
            action_type=(
                "dismiss_assignment" if action == "罢免" else "appointment"
            ),
            decree_text=text,
            target_kind="character",
            target_id=name,
            executor_kind="character",
            executor_id=name,
            pending_action_id=int(pa["id"]),
            payload=staged_payload,
            status="proposed",
            commit=False,
        )
        if dossier_id:
            # #1842：office 成案同样继承载荷背书。
            self.inherit_payload_endorsements(
                int(dossier_id), staged_payload, commit=False,
            )
        return dossier_id != 0

    def _recommendation_snapshot_ready(
        self, state: GameState, payload: Dict[str, object], *, minister_name: str = "",
    ) -> bool:
        """载荷无荐人，或 staged 快照仍与当前盘面一致时为 True。

        #1583：唯一校验真源仍是 validate_recommendation_snapshot；本 helper 只
        组装 payload 形状，不复制第二套判断。
        """
        recommendation = payload.get("recommendation")
        if recommendation is None:
            return True
        if not isinstance(recommendation, dict):
            return False
        staged_candidate = recommendation.get("candidate")
        recommender = str(
            recommendation.get("recommender") or minister_name or ""
        ).strip()
        if not isinstance(staged_candidate, dict) or not recommender:
            return False
        name = str(payload.get("name") or "").strip()
        from ming_sim.recommendations import validate_recommendation_snapshot
        return (
            staged_candidate.get("name") == name
            and validate_recommendation_snapshot(
                self, state, recommender, staged_candidate,
            )
        )

    def _invalid_office_recommendation_snapshots(
        self, state: GameState, dossiers: Iterable[Dict[str, object]],
    ) -> set[int]:
        """返回批前盘面中确实不匹配的荐人快照案号；其他异常原样上抛。"""
        invalid = set()
        for row in dossiers:
            if str(row.get("action_type") or "") != "appointment":
                continue
            payload = load_stored_object(row.get("payload_json"), label="payload_json")
            if payload.get("recommendation") is None:
                continue
            minister = str(payload.get("_minister_name") or "")
            if not self._recommendation_snapshot_ready(
                state, payload, minister_name=minister,
            ):
                invalid.add(int(row["id"]))
        return invalid

    def _prevalidate_office_recommendation_snapshots(
        self, state: GameState, dossiers: Iterable[Dict[str, object]],
    ) -> None:
        """批前统一校验即将物化的任命荐人快照（#1583）。"""
        if self._invalid_office_recommendation_snapshots(state, dossiers):
            raise ValueError("任免案卷载荷物化失败")

    def _commit_office_action(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        content,
    ) -> set[str]:
        """任免(office)落库并返回 canonical applied 中受影响的正式人物。
        - 任命既有官 → 升迁/调任:set_character_office(改官、仍 active),不当新人(apply_appointment
          对在册者命中即拒、会标 failed);
        - 任命朝臣(新任/升迁/调任)→ person-only canonical adapter → apply_office_appointment
          唯一落地核(dead-reject / 非active→激活 / 顶替去重);
        - 罢免:_find_existing_minister 解 alias + ming-guard(外藩/后宫/不在册不接),dismissed+同步清内存 office。
        缺 content(无法查重/注册)→ 空集合标 failed,不静默。跨模块函数运行期 lazy import 避免 db↔session/issues 循环。"""
        if content is None:
            return set()
        from ming_sim.session import _find_existing_minister
        name = str(payload.get("name") or "").strip()
        if not name:
            return set()
        office = str(payload.get("office") or "")
        if pa["action"] == "任命":
            # 朝臣任命/升迁/调任 → person-only adapter（不经 full settlement recovery）。
            reason = str(payload.get("reason") or "奉旨任免").strip() or "奉旨任免"
            office_type = str(payload.get("office_type") or "").strip()
            try:
                appointment_tenure = appointment_tenure_from(payload)
            except ValueError:
                return set()
            recommendation = payload.get("recommendation")
            staged_candidate = recommendation.get("candidate") if isinstance(recommendation, dict) else None
            recommender = str(recommendation.get("recommender") or pa["minister_name"]) if isinstance(recommendation, dict) else ""
            # #1583：批内已在 apply_dossier_verdicts / 批红序前统一校验过荐人快照时，
            # 跳过二次校验，避免前序任免改盘面把后序同快照误判过期。
            if not getattr(self.conn, "_recommendation_snapshots_prevalidated", False):
                if recommendation is not None and (
                    not isinstance(staged_candidate, dict)
                    or not recommender
                ):
                    return set()
                if isinstance(staged_candidate, dict):
                    from ming_sim.recommendations import validate_recommendation_snapshot
                    if staged_candidate.get("name") != name or not validate_recommendation_snapshot(
                        self, state, recommender, staged_candidate
                    ):
                        return set()
            elif recommendation is not None and (
                not isinstance(staged_candidate, dict)
                or not recommender
                or staged_candidate.get("name") != name
            ):
                return set()
            # A recommendation event is provenance for this exact staged
            # candidate.  Keep the appointment and event in one transaction so
            # a failure while recording cannot leave the appointment adopted
            # without its auditable recommendation.
            recommendation_reason = ""
            if isinstance(recommendation, dict):
                recommendation_reason = str(payload.get("reason") or "")
                if not recommendation_reason.strip():
                    raise ValueError("荐人双边缺非空荐词语境：payload.reason 必填")
                reason = recommendation_reason
            from ming_sim.issues import apply_person_changes_only
            person_item = {
                "name": name, "动作": "任命", "office": office,
                "office_type": office_type, "任别": appointment_tenure,
                "reason": reason, "origin_ref": "盘面自发",
            }
            seat = str(
                payload.get("region_id")
                or payload.get("任所")
                or payload.get("辖区")
                or ""
            ).strip()
            if seat:
                person_item["region_id"] = seat
            applied = apply_person_changes_only(
                self, state,
                [person_item],
                content=content, llm_config=self.llm_config,
            )
            affected = self._affected_people_from_applied_rows(
                applied.get("applied_person_changes", []),
            )
            if recommendation_reason and name in affected:
                from ming_sim.recommendations import record_recommendation_edges
                event_id = self.record_recommendation(
                    state, recommender, staged_candidate, office,
                    recommendation_reason,
                )
                record_recommendation_edges(
                    self, state, recommender, name, event_id, recommendation_reason,
                )
            return affected
        if pa["action"] == "罢免":
            # 仅大明【在职】大臣可罢:_find_existing_minister 已 ming-guard + 解 alias;
            # 外藩(power_id≠ming)/后宫/不在册不接(无字面 fallback,免误黜皇太极,CMR R2);
            # 再校 active,免把已故/已黜/致仕者的终态改写成 dismissed(CMR R3 codex R2)。
            key = _find_existing_minister(content, name, self)
            if key is None or self.get_character_status(key)[0] != "active":
                return set()
            # 宗藩（就藩宗室）非朝堂命官，不可作朝臣罢免——_find_existing_minister 仍会解析到宗藩名
            # （任命核需解到名才能显式拒），故罢免侧单独守（cmr R6 cross-section）。
            _ch_key = content.characters.get(key)  # key 来自 _find_existing_minister 必在册，.get 防御一致（R2 gemini）
            if _ch_key is not None and is_vassal_prince(_ch_key):
                return set()
            self.set_character_status(
                state, key, "dismissed", reason="奉旨罢黜", content=content,
            )
            # 对话确认回合中落库,刷 Agent 让被罢者本回合后续不再以旧活跃态被召对(线上 gemini)。
            return {key}
        return set()

    def withdraw_pending_action(self, action_id: int, turn: int) -> bool:
        """皇帝复核:撤回本回合一条尚未落库的暂存动作(删 pending 行)。返回是否删了。
        已 committed / 非本回合 / 不存在 → False。
        仍 inactive 的 office:<id> 传召 origin 同步清掉（#672 颁前反悔）。"""
        owns_transaction = not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
            or self.conn.in_transaction
        )
        row = self.conn.execute(
            "SELECT id, kind, version FROM pending_actions "
            "WHERE id=? AND turn=? AND status='pending'",
            (int(action_id), int(turn)),
        ).fetchone()
        if row is None:
            return False
        if str(row["kind"] or "") == "directive":
            self._discard_pending_decree_forecast(
                int(action_id), int(row["version"] or 1),
            )
        cur = self.conn.execute(
            "DELETE FROM pending_actions WHERE id=? AND turn=? AND status='pending'",
            (int(action_id), int(turn)),
        )
        if cur.rowcount > 0 and str(row["kind"] or "") == "office":
            from ming_sim.audience_night import discard_inactive_office_summon
            discard_inactive_office_summon(self, int(action_id))
        if owns_transaction:
            self.conn.commit()
        return cur.rowcount > 0

    def hold_over_pending_actions(
        self, turn: int, minister_name: str,
        action_ids: Optional[Iterable[int]] = None,
    ) -> int:
        """#525 留中：点名候选移出 status=pending 活跃集，同表 durable 留中档 (held_over)。
        不删行；commit_pending_actions 只读 pending，故默认提交自然跳过、不成案。
        返回更新条数。action_ids 非空=只留中指定 id（#502 点名粒度）。"""
        owns_transaction = not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
            or self.conn.in_transaction
        )
        params: List[object] = [int(turn), str(minister_name)]
        where = "turn=? AND minister_name=? AND status='pending'"
        if action_ids is not None:
            allowed_ids = [int(action_id) for action_id in action_ids]
            if not allowed_ids:
                return 0
            placeholders = ",".join("?" for _ in allowed_ids)
            where += f" AND id IN ({placeholders})"
            params.extend(allowed_ids)
        cur = self.conn.execute(
            f"UPDATE pending_actions SET status='held_over', night_approved=0 "
            f"WHERE {where}",
            tuple(params),
        )
        if owns_transaction:
            self.conn.commit()
        return int(cur.rowcount or 0)

    def drop_pending_actions_for_minister(
        self, turn: int, minister_name: str, kind_filter_exclude: Optional[str] = None,
        action_ids: Optional[Iterable[int]] = None,
    ) -> int:
        """对话确认皇帝拒绝:丢弃该召对对象本回合尚未落库的暂存动作(删 pending 行)。
        返回删除条数。只动该大臣、只动 pending(已 committed 不动)。
        action_ids 非空=进一步只删指定 pending_actions.id（召对确认只可作用于本轮开始前可见项）。
        kind_filter_exclude 非空=不删该 kind(召对确认拒绝须放过 directive,BUG 1:拟旨搁置
        是颁诏期语义,不能被召对期拒绝静默删掉玩家草案)。
        仍 inactive 的 office:<id> 传召 origin 随 pending 同步清（#672 颁前拒绝）。"""
        owns_transaction = not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
            or self.conn.in_transaction
        )
        params: List[object] = [int(turn), str(minister_name)]
        where = "turn=? AND minister_name=? AND status='pending'"
        if action_ids is not None:
            allowed_ids = [int(action_id) for action_id in action_ids]
            if not allowed_ids:
                return 0
            placeholders = ",".join("?" for _ in allowed_ids)
            where += f" AND id IN ({placeholders})"
            params.extend(allowed_ids)
        if kind_filter_exclude is not None:
            where += " AND kind<>?"
            params.append(str(kind_filter_exclude))
        office_ids = [
            int(row["id"])
            for row in self.conn.execute(
                f"SELECT id FROM pending_actions WHERE {where} AND kind='office'",
                tuple(params),
            ).fetchall()
        ]
        directive_ids = [
            int(row["id"])
            for row in self.conn.execute(
                f"SELECT id FROM pending_actions WHERE {where} AND kind='directive'",
                tuple(params),
            ).fetchall()
        ]
        for pending_id in directive_ids:
            self._discard_deleted_directive_forecast(pending_id)
        cur = self.conn.execute(
            f"DELETE FROM pending_actions WHERE {where}",
            tuple(params),
        )
        if office_ids:
            from ming_sim.audience_night import discard_inactive_office_summon
            for pending_id in office_ids:
                discard_inactive_office_summon(self, pending_id)
        if owns_transaction:
            self.conn.commit()
        return cur.rowcount

    def discard_pending_directives(self, turn: int) -> int:
        """退朝无诏时丢弃本回合尚未落库的对话式拟旨暂存（kind=directive, status=pending）。
        须在 commit_pending_actions 之前调用，防止 commit 把草案插成孤儿 turn_directives
        行——退朝路不颁诏，孤儿 draft 永不经 extractor、不可见（codex r5 F2）。
        返回删除条数。"""
        rows = self.conn.execute(
            "SELECT id FROM pending_actions WHERE turn=? AND kind='directive' AND status='pending'",
            (int(turn),),
        ).fetchall()
        for row in rows:
            self._discard_deleted_directive_forecast(int(row["id"]))
        cur = self.conn.execute(
            "DELETE FROM pending_actions WHERE turn=? AND kind='directive' AND status='pending'",
            (int(turn),),
        )
        return cur.rowcount

    def discard_failed_secret_order_intents(self) -> int:
        """过回合前丢弃既有 failed secret-order intents（CONTEXT：未处理失败下达在过回合丢弃）。

        须在 commit_pending_actions 之前调用：清掉玩家已选择结束回合时仍未重试的旧 failure，
        再提交本轮 pending，使同次 commit 新产生的 failure 仍保留、可恢复。
        返回删除条数；不拥有 commit（嵌在 pre_settle owning transaction 内）。
        """
        cur = self.conn.execute(
            "DELETE FROM pending_actions WHERE status='failed' AND kind='secret_order'"
        )
        return cur.rowcount

    def save_resolve_context(
        self, turn: int, decree_text: str,
        simulator_payload: Dict[str, object],
        source: str = "system_simulation",
        attendant_message: str = "",
    ) -> None:
        """暂存本月过月上下文（诏书/payload/来源），供批红、月链相位与机械尾读回。

        #1846：不再持久化 ready=1 extractor delta；恢复真源是暂存声明与落账相位。
        """
        self.resolve_contexts.upsert(
            turn=int(turn),
            decree_text=sanitize_sqlite_text(decree_text),
            simulator_payload_json=safe_json_dumps(simulator_payload or {}, ensure_ascii=False),
            # source 显式归一为枚举「值」字符串：Provenance 是 (str, Enum)，str(member) 在多数
            # Python 版本落 'Provenance.player_decree' 而非 'player_decree'——重抽时
            # Provenance(...) 不匹配 → 静默退回 system_simulation 丢源（Sourcery #175 bug_risk）。
            # getattr(.,"value",.) 让枚举取 .value、普通字符串原样、None/空回落 system_simulation。
            source=str(getattr(source, "value", source) or "system_simulation"),
            attendant_message=sanitize_sqlite_text(str(attendant_message or "")),
        )
        self.conn.commit()

    def clear_resolve_context(self, turn: int) -> None:
        self.resolve_contexts.delete(int(turn))
        self.dossiers.clear_pending_promulgation_verdicts(int(turn))
        self.conn.commit()

    # ── #1234 月初快照（路③呈现投影）────────────────────────────────

    def capture_month_open_snapshot(self, state: GameState) -> bool:
        """点击受理：独立提交点击前四键 + 所属回合。已有本回合行则不覆盖（幂等）。

        必须在任何盘面突变之前调用，且不进 pre_settle 事务——否则回滚会毁掉刷新同脸。
        原子 INSERT ON CONFLICT DO NOTHING：返回 True 仅当本调用新建行（rowcount==1），
        供 accept 裁定创建者；禁 SELECT 预检/后置见行假 True。
        """
        turn = int(state.turn)
        m = state.metrics
        created = self.month_open_snapshots.insert_once(
            turn=turn,
            treasury=int(m.get("国库", 0)),
            inner_treasury=int(m.get("内库", 0)),
            public_support=int(m.get("民心", 0)),
            imperial_prestige=int(m.get("皇威", 0)),
        )
        self.conn.commit()
        return created

    def clear_month_open_snapshot(self, turn: int) -> None:
        """过期/清除本回合快照。atomic 内 commit 为 no-op，与 clear_resolve_context 同窗。"""
        self.month_open_snapshots.delete(int(turn))
        self.conn.commit()

    def get_authority(self, authority_id: int) -> Optional[Dict[str, object]]:
        row = CharacterStore(self.conn).read_get_authority((int(authority_id),))
        if row is None:
            return None
        result = dict(row)
        result["revoked"] = bool(result["revoked"])
        return result

    def list_active_authorities(
        self, turn: int, *, holder_id: str = "",
    ) -> List[Dict[str, object]]:
        params: List[object] = [int(turn), int(turn)]
        holder_sql = ""
        if holder_id:
            holder_sql = " AND holder_id=?"
            params.append(str(holder_id))
        rows = CharacterStore(self.conn).read_list_active_authorities_owned(params, holder_sql).fetchall()
        return [{**dict(row), "revoked": False} for row in rows]

    def find_authority_by_origin(
        self, dossier_id: int, *, holder_id: str, privilege: str, scope: str,
    ) -> Optional[Dict[str, object]]:
        """Return the stable row for an exact grant origin, regardless of status."""
        row = CharacterStore(self.conn).read_find_authority_by_origin((
                int(dossier_id), str(holder_id).strip(), str(privilege).strip(),
                str(scope).strip(),
            ))
        if row is None:
            return None
        result = dict(row)
        result["revoked"] = bool(result["revoked"])
        return result

    def find_active_authority(
        self, turn: int, *, holder_id: str, privilege: str, scope: str,
    ) -> Optional[Dict[str, object]]:
        """Return the in-hand row for the exact grant identity, if any."""
        holder_id = str(holder_id or "").strip()
        privilege = str(privilege or "").strip()
        scope = str(scope or "").strip()
        for row in self.list_active_authorities(turn, holder_id=holder_id):
            if (
                str(row.get("privilege") or "") == privilege
                and str(row.get("scope") or "") == scope
            ):
                return row
        return None

    def project_applicable_authorities(
        self, turn: int, dossier: Mapping[str, object],
    ) -> List[Dict[str, object]]:
        """#611 unique applicability projection over durable authority rows.

        Actors = character executor ∪ roster 主办/协办 (never payload assignee).
        Domains = only the typed canonical key target_kind:target_id.
        """
        actors: set[str] = set()
        executor_id = str(dossier.get("executor_id") or "").strip()
        executor_kind = str(dossier.get("executor_kind") or "").strip()
        if executor_id and executor_kind in {"", "character"}:
            actors.add(executor_id)
        roster = load_participant_roster(dossier.get("participant_roster"))
        if isinstance(roster, list):
            for entry in roster:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("tier") or "").strip() not in {"主办", "协办"}:
                    continue
                character_id = str(entry.get("character_id") or "").strip()
                if character_id:
                    actors.add(character_id)
        target_kind = str(dossier.get("target_kind") or "").strip()
        target_id = str(dossier.get("target_id") or "").strip()
        domains: set[str] = set()
        if target_kind and target_id:
            domains.add(f"{target_kind}:{target_id}")
        if not actors or not domains:
            return []
        projected: List[Dict[str, object]] = []
        for holder_id in sorted(actors):
            for row in self.list_active_authorities(int(turn), holder_id=holder_id):
                if str(row.get("scope") or "") not in domains:
                    continue
                projected.append({
                    "id": int(row["id"]),
                    "holder_id": str(row["holder_id"]),
                    "privilege": str(row["privilege"]),
                    "scope": str(row["scope"]),
                    "effective_turn": int(row["effective_turn"]),
                    **(
                        {"expires_turn": int(row["expires_turn"])}
                        if row.get("expires_turn") is not None else {}
                    ),
                })
        projected.sort(key=lambda item: int(item["id"]))
        return projected

    def list_office_effects_for_dossier(
        self, dossier_id: int,
    ) -> List[Dict[str, object]]:
        return [
            dict(row) for row in CharacterStore(self.conn).read_list_office_effects_for_dossier((int(dossier_id),))
        ]

    def add_directive(
        self,
        state: GameState,
        event: Event | None,
        text: str,
        source: str,
        actor: str = "",
        notes: str = "",
        status: str = "draft",
        dossier_payload: Optional[Dict[str, object]] = None,
    ) -> int:
        # status: 'draft'=已确认颁诏候选；'pending'=大臣拟旨待皇帝核定。
        with atomic(self):
            cursor = self.conn.execute(
                """
                INSERT INTO turn_directives
                (turn, year, period, event_id, actor, text, source, status,
                 notes,dossier_payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (state.turn, state.year, state.period, event.id if event else None,
                 actor or None, text, source, status, notes,
                 json.dumps(dossier_payload or {}, ensure_ascii=False)),
            )
            directive_id = int(cursor.lastrowid)
        return directive_id

    def _ensure_directive_dossier(
        self, state: GameState, directive_id: int, text: str,
        payload: Optional[Dict[str, object]] = None, *, commit: bool = True,
    ) -> List[int]:
        """旧式/新式旨稿共用的幂等成案口；返回已成案 dossier id 列表（#1778 起 national 亦单行）。

        #658：payload.target_dossier_id 指向 stalled 廷议时，复用该案卷并落御笔手敕，
        不新建第二案卷。directive identity = directive:<id>。
        """
        owns = self.owns_transaction()
        structured = dict(payload or {})
        if not structured:
            structured = {
                "dossier_action_type": "special_decree",
                "target_kind": "policy",
                "target_id": f"legacy-directive:{directive_id}",
                "locality_scope": "none",
            }
        # #658：互斥权威——push 与 ordinary 并存响亮拒绝；push 在 normalize 前短路
        kind = classify_directive_structured_kind(structured)
        target_did = (
            imperial_push_target_dossier_id(structured)
            if kind == "push" else None
        )
        if target_did is not None:
            # 同 directive↔目标 dossier 已绑定：幂等返回，不重跑 stalled 校验副作用
            bound = self.dossiers.bound_to_directive(int(target_did), int(directive_id))
            if bound is not None:
                self._attach_affair_from_payload(state, structured, int(target_did))
                self._commit_dossier_write(commit, owns)
                return [int(target_did)]
            from ming_sim.rescript_actions import apply_imperial_deliberation_push
            push_mode = normalize_dossier_mode(
                structured["mode"] if "mode" in structured else "ordinary"
            )
            pushed = apply_imperial_deliberation_push(
                self, state,
                target_dossier_id=int(target_did),
                directive_identity=f"directive:{int(directive_id)}",
                decree_text=str(text or ""),
                mode=push_mode,
                commit=False,
            )
            # 绑 directive_id 到既有案卷，供 restore/幂等
            self.dossiers.bind_directive(int(pushed), int(directive_id))
            self._attach_affair_from_payload(state, structured, int(pushed))
            self._commit_dossier_write(commit, owns)
            return [int(pushed)]
        structured = self._normalize_directive_dossier_payload(
            structured, content=self.content, current_turn=int(state.turn),
        )
        action_type = self._directive_dossier_action_type(structured)
        target_kind = str(structured.get("target_kind") or "").strip()
        target_id = str(structured.get("target_id") or "").strip()
        if not target_kind or not target_id:
            raise ValueError("普通旨意缺少受控目标，拒绝成案")
        executor_kind, executor_id = self._directive_executor(action_type, structured)
        pending = self.conn.execute(
            """
            SELECT id FROM pending_actions
            WHERE committed_directive_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (int(directive_id),),
        ).fetchone()
        return self.create_decree_dossiers(
            state,
            action_type=action_type,
            decree_text=text,
            target_kind=target_kind,
            target_id=target_id,
            executor_kind=executor_kind,
            executor_id=executor_id,
            source_chat_turn_id=int(structured.get("source_chat_turn_id") or 0),
            pending_action_id=0 if pending is None else int(pending["id"]),
            directive_id=int(directive_id),
            payload=structured,
            due_turn=int(structured.get("due_turn") or 0),
            commit=commit,
        )

    def list_directives(
        self, state: GameState, statuses: Tuple[str, ...] = ("draft",)
    ) -> List[sqlite3.Row]:
        # 默认只取 draft（颁诏候选）；UI 列表传 ('pending','draft') 一起取，前端按 status 分区。
        placeholders = ",".join("?" for _ in statuses)
        return IssueStore(self.conn).read_list_directives_owned((state.turn, state.turn, *statuses), placeholders).fetchall()

    def get_directive(self, directive_id: int) -> Optional[sqlite3.Row]:
        """按 id 读单条 turn_directives（#1769 补交读口；禁 session 手写 SELECT）。"""
        return self.conn.execute(
            "SELECT id, text, status, turn, dossier_payload_json "
            "FROM turn_directives WHERE id=?",
            (int(directive_id),),
        ).fetchone()

    @staticmethod
    def _decode_directive_dossier_payload(
        raw: object, *, directive_id: Optional[int] = None,
    ) -> Dict[str, object]:
        label = f"旨稿#{directive_id}" if directive_id is not None else "既有旨稿"
        return load_stored_object(raw, label=f"{label} 结构化载荷")

    def read_directive_dossier_payload(self, row: object) -> Dict[str, object]:
        """Strictly decode a durable turn_directives payload at the DB read seam."""
        return self._decode_directive_dossier_payload(
            row["dossier_payload_json"], directive_id=int(row["id"]),
        )

    def confirm_directive(self, directive_id: int, state: GameState) -> None:
        """大臣拟旨经皇帝核定：pending → draft（进入颁诏候选池）。

        #1769：只翻状态。成案/补交/耗尽唯一批缝 =
        ensure_dossiers_for_draft_directives + _resubmit_draft_admission_failures；
        禁止在 confirm 内 ensure、标 rejected 或另建重试。产物错 pending 入 draft
        后走 B 路；真代码故障仍由批缝 SettlementAbort（0005/0008）。
        """
        with atomic(self):
            self.conn.execute(
                """
                UPDATE turn_directives
                SET status = 'draft', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (directive_id,),
            )
            row = self.conn.execute(
                "SELECT id FROM turn_directives WHERE id=?",
                (int(directive_id),),
            ).fetchone()
            if row is None:
                raise KeyError(f"旨稿不存在：{directive_id}")

    def ensure_dossiers_for_draft_directives(
        self, state: GameState, *,
        record_rejections: bool = True,
    ) -> List[Dict[str, object]]:
        """结束边界成案：只读最新 draft 正文/载荷，按 directive_id 幂等创建。

        #654 r3-C.2 路3：每道旨独立 SAVEPOINT；单旨产物错记 rejection、保持 draft，不波及他旨。
        #1769：产物错（ValueError，含 PayOrderKeyError）逐项留痕；真代码故障不得洗成
        locality_fanout_failed——回滚后写错误包并 SettlementAbort（0005/0008 D1/D6）。
        #1778：create 不再 collector-only 返回零案卷；未成案形状＝抛 ValueError，
        保持 draft、进返回列表供补交、终态落痕。
        record_rejections=False：仅探测供补交，不落 rejection_reports（拒只在
        耗尽/终态后落痕，避免补交成功仍残留首轮拒收）。
        返回 [{directive_id, reason}, ...] 供结算路补交；成功旨不入列表。
        """
        from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
        from ming_sim.error_pack import (
            rejections_jsonl_path,
            settlement_abort_message,
            write_error_pack,
        )
        from ming_sim.exceptions import SettlementAbort

        collector = RejectionCollector()
        rejection_rows: List[Dict[str, object]] = []
        code_fault: BaseException | None = None
        try:
            with atomic(self):
                for row in self.list_directives(state, statuses=("draft",)):
                    did = int(row["id"])
                    # 已有案卷：幂等跳过（补交重跑 ensure 时不重复建）
                    if self.dossiers.get_for_directive(did) is not None:
                        continue
                    sp = f"ensure_directive_{did}"
                    self.conn.execute(f"SAVEPOINT {sp}")
                    try:
                        self._ensure_directive_dossier(
                            state, did, str(row["text"]),
                            self.read_directive_dossier_payload(row), commit=False,
                        )
                    except ValueError as exc:
                        # 产物/契约错：逐项隔离留痕，保持 draft（#1769 补交/耗尽入口）
                        self.conn.execute(f"ROLLBACK TO {sp}")
                        reason = str(exc)
                        rejection_rows.append({"directive_id": did, "reason": reason})
                        # P6：rejection 只存 directive_id，不裁剪/快照 LLM 旨文
                        if record_rejections:
                            collector.record(
                                "directive_locality",
                                RejectedItem(
                                    item={"directive_id": did},
                                    reason=reason,
                                    category="locality_fanout_failed",
                                    source=Provenance.player_decree,
                                ),
                                int(state.turn),
                            )
                        tlog(f"[ensure_dossiers] 旨#{did} 成案产物错：{exc}")
                    except Exception as exc:
                        # 真代码故障：不得当产物错洗白后继续（0005）
                        self.conn.execute(f"ROLLBACK TO {sp}")
                        code_fault = exc
                        tlog(f"[ensure_dossiers] 旨#{did} 成案代码故障：{exc}")
                        raise
                    finally:
                        self.conn.execute(f"RELEASE {sp}")
                if record_rejections:
                    collector.flush_to_db(self)
        except Exception as exc:
            if code_fault is None:
                code_fault = exc
            # atomic 已回滚；错误包须在事务外写（write_error_pack 约束）
            pack_path = write_error_pack(
                self, state, exc=code_fault, extracted=None, resolve_ctx=None,
            )
            raise SettlementAbort(
                settlement_abort_message(pack_path),
                turn=int(state.turn),
                stage="directive_ensure",
                error_pack_path=pack_path,
            ) from code_fault
        if record_rejections:
            from ming_sim.applier import mirror_rejections_after_commit
            mirror_rejections_after_commit(self, collector, rejections_jsonl_path)
        return rejection_rows

    def reject_directive(self, directive_id: int) -> None:
        """皇帝驳回大臣拟旨：pending → rejected。"""
        self.conn.execute(
            """
            UPDATE turn_directives
            SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
            """,
            (directive_id,),
        )
        self.conn.commit()

    def count_pending_directives(self, state: GameState) -> int:
        """本回合待核定（pending）的大臣拟旨数。颁诏前须为 0。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM turn_directives WHERE turn = ? AND status = 'pending'",
            (state.turn,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def update_directive_text(
        self, directive_id: int, text: str, *,
        dossier_payload: Optional[Dict[str, object]] = None,
        replace_payload: bool = False,
    ) -> None:
        """改草 draft 正文/载荷。

        replace_payload=True（#1769 结算补交）：整份采用新 payload，不经 merge——
        避免 pay_order entries 等旧键残留到新动作类型上。默认 False 保持改草合并语义。
        """
        if self.dossiers.get_for_directive(directive_id) is not None:
            raise ValueError("已成案旨意不得编辑")
        row = self.conn.execute(
            "SELECT dossier_payload_json FROM turn_directives WHERE id=?", (directive_id,)
        ).fetchone()
        if row is None:
            raise ValueError("旨意不存在")
        incoming = dict(dossier_payload or {})
        if replace_payload:
            payload = incoming
        else:
            payload = self._merge_directive_payload(
                row["dossier_payload_json"], incoming,
            )
        if not directive_payload_admits_structured_write(payload):
            raise ValueError("旨意编辑须提供完整结构化动作与目标")
        with atomic(self):
            self.conn.execute(
                """
                UPDATE turn_directives
                SET text=?,dossier_payload_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (text, json.dumps(payload, ensure_ascii=False), directive_id),
            )

    def delete_directive(self, directive_id: int) -> None:
        if self.dossiers.get_for_directive(directive_id) is not None:
            raise ValueError("已成案旨意不得删除；请撤回成命")
        self.conn.execute(
            """
            UPDATE turn_directives
            SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (directive_id,),
        )
        self.conn.commit()

    def mark_directives_issued(self, state: GameState) -> None:
        # #1889：哪些 directive 已成案由案卷 store 判定（ADR 0151），此模块不再
        # 在 turn_directives 的 UPDATE 里 EXISTS 查案卷表。
        issued = [
            int(r["id"]) for r in self.dossiers.directives_with_dossiers(int(state.turn))
        ]
        if issued:
            placeholders = ",".join("?" for _ in issued)
            self.conn.execute(
                f"UPDATE turn_directives SET status='issued', "
                f"updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders}) "
                f"AND status='draft'",
                issued,
            )
        self.conn.commit()

    # ----- issues (双类事项 + 双向进度条) -----

    def _derive_issue_phase(self, bar: int) -> str:
        if bar <= 0:
            return "终"
        if bar < 30:
            return "起"
        if bar < 70:
            return "中"
        if bar < 100:
            return "终前"
        return "终"

    def list_active_issues(self, kind: str | None = None) -> List[sqlite3.Row]:
        return self.issues.active_rows(kind)

    def list_closed_issues_at(self, closed_turn: int) -> List[sqlite3.Row]:
        """指定 turn 关闭（resolved / failed / dropped）的 issue。"""
        return IssueStore(self.conn).read_list_closed_issues_at((int(closed_turn),))

    def count_active_initiatives(self) -> int:
        row = IssueStore(self.conn).read_count_active_initiatives()
        return int(row["n"] or 0)

    def find_active_issue_by_origin(self, origin_kind: str, origin_ref: str) -> sqlite3.Row | None:
        return IssueStore(self.conn).read_find_active_issue_by_origin((origin_kind, origin_ref))

    def find_any_issue_by_origin(self, origin_kind: str, origin_ref: str) -> sqlite3.Row | None:
        """查任意状态（含 resolved/failed/dropped）的同源 issue，用于 spawn 去重。"""
        return IssueStore(self.conn).read_find_any_issue_by_origin((origin_kind, origin_ref))

    def has_event_triggered(self, event_id: str) -> bool:
        row = IssueStore(self.conn).read_has_event_triggered((event_id,))
        return row is not None

    def event_terminal_state(self, event_id: str) -> str | None:
        row = IssueStore(self.conn).read_event_terminal_state((event_id,))
        return row["terminal_state"] if row is not None else None

    def has_event_terminal_state(self, event_id: str, terminal_state: str) -> bool:
        row = IssueStore(self.conn).read_has_event_terminal_state((event_id, terminal_state))
        return row is not None


    def mark_event_triggered(
        self,
        state: GameState,
        event_id: str,
        source: str = "simulation",
        *,
        terminal_reason: str = "",
        commit: bool = True,
    ) -> None:
        self._ensure_event_parent(event_id)
        IssueStore(self.conn).write_mark_event_triggered_owned((event_id, state.turn, state.year, state.period, source, str(terminal_reason or '')[:200]))
        if commit:
            self.conn.commit()

    def mark_event_avoided(
        self,
        state: GameState,
        event_id: str,
        reason: str,
        source: str = "gate_avoided",
        *,
        commit: bool = True,
    ) -> None:
        self._ensure_event_parent(event_id)
        IssueStore(self.conn).write_mark_event_avoided_owned((event_id, state.turn, state.year, state.period, source, reason[:200]))
        if commit:
            self.conn.commit()

    def mark_event_obsolete(
        self,
        state: GameState,
        event_id: str,
        reason: str,
        source: str = "person_core_dead",
        *,
        commit: bool = True,
    ) -> None:
        self._ensure_event_parent(event_id)
        IssueStore(self.conn).write_mark_event_obsolete_owned((event_id, state.turn, state.year, state.period, source, reason[:200]))
        if commit:
            self.conn.commit()

    def mark_event_expired(self, state: GameState, event_id: str, *, commit: bool = True) -> None:
        self._ensure_event_parent(event_id)
        IssueStore(self.conn).write_mark_event_expired_owned((event_id, state.turn, state.year, state.period))
        if commit:
            self.conn.commit()

    def record_event_decision_choice(
        self,
        state: GameState,
        event_id: str,
        choice: Dict[str, object],
        *,
        source: str = "hitl_decision",
        commit: bool = True,
    ) -> None:
        """Persist the player's HITL choice for an event-backed decision in the event ledger."""
        eid = str(event_id or "").strip()
        if not eid:
            return
        self._ensure_event_parent(eid)
        payload = json.dumps(choice if isinstance(choice, dict) else {}, ensure_ascii=False)
        label = str((choice or {}).get("label") or "")[:200] if isinstance(choice, dict) else ""
        IssueStore(self.conn).write_record_event_decision_choice((eid, state.turn, state.year, state.period, source, label, payload))
        if commit:
            self.conn.commit()

    @staticmethod
    def _coerce_todo_payload_json(payload_json: object) -> str:
        """#624：引擎侧 payload_json 序列化；非法非空响亮拒绝，禁静默丢底。"""
        if payload_json is not None and not isinstance(payload_json, (str, dict)):
            raise ValueError(f"next_audience_todos.payload_json 类型非法：{type(payload_json).__name__}")
        data = load_stored_object(payload_json, label="next_audience_todos.payload_json")
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def parse_engine_payload_json(
        raw: object, *, surface: str = "payload_json",
    ) -> Dict[str, object]:
        """#624 / ADR 0005：引擎侧 payload 读路单一助手。

        真空/缺省 → {}；腐坏 JSON 或非对象 → 响亮 tlog + ValueError（禁静默吞成空底）。
        """
        try:
            return dict(load_stored_object(raw, label=surface))
        except ValueError as exc:
            tlog(f"[{surface}] {exc}")
            raise

    @classmethod
    def _parse_todo_payload_json(cls, raw: object) -> Dict[str, object]:
        return cls.parse_engine_payload_json(
            raw, surface="next_audience_todos.payload_json",
        )

    def insert_next_audience_todo(
        self,
        *,
        commitment_ref: int,
        stage_idx: int,
        due_turn: int,
        criterion_text: str = "",
        origin_context: str = "",
        status: str = "pending",
        entry_kind: str = "staged_commitment",
        created_turn: int = 0,
        payload_json: object = None,
        commit: bool = True,
    ) -> int:
        """#620 P2：次回合召对待办写端。UNIQUE(commitment_ref, stage_idx, entry_kind) 去重。

        #624：payload_json 引擎侧列（真伪底）；默认 '{}'。
        返回新建行 id；已存在则返回 0（幂等，不覆盖）。
        """
        payload_blob = self._coerce_todo_payload_json(payload_json)
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO next_audience_todos (
                commitment_ref, stage_idx, due_turn, criterion_text, origin_context,
                status, entry_kind, created_turn, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(commitment_ref),
                int(stage_idx),
                int(due_turn),
                sanitize_sqlite_text(str(criterion_text or "")),
                sanitize_sqlite_text(str(origin_context or "")),
                sanitize_sqlite_text(str(status or "pending") or "pending"),
                sanitize_sqlite_text(str(entry_kind or "staged_commitment") or "staged_commitment"),
                int(created_turn or 0),
                sanitize_sqlite_text(payload_blob),
            ),
        )
        if commit:
            self.conn.commit()
        if cur.rowcount <= 0:
            return 0
        return int(cur.lastrowid)

    def list_next_audience_todos(
        self,
        *,
        status: str | None = None,
        commitment_ref: int | None = None,
    ) -> List[Dict[str, object]]:
        """下一召对回合可读的待办条目（restore 只读 DB 接续）。"""
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status=?")
            params.append(str(status))
        if commitment_ref is not None:
            clauses.append("commitment_ref=?")
            params.append(int(commitment_ref))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT id, commitment_ref, stage_idx, due_turn, criterion_text,
                   origin_context, status, entry_kind, created_turn, payload_json
            FROM next_audience_todos
            {where}
            ORDER BY due_turn, commitment_ref, stage_idx, id
            """,
            tuple(params),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "commitment_ref": int(r["commitment_ref"]),
                "stage_idx": int(r["stage_idx"]),
                "due_turn": int(r["due_turn"]),
                "criterion_text": str(r["criterion_text"] or ""),
                "origin_context": str(r["origin_context"] or ""),
                "status": str(r["status"] or ""),
                "entry_kind": str(r["entry_kind"] or ""),
                "created_turn": int(r["created_turn"] or 0),
                "payload_json": self._parse_todo_payload_json(r["payload_json"]),
            }
            for r in rows
        ]

    def mark_next_audience_todo_status(
        self,
        todo_id: int,
        status: str,
        *,
        payload_patch: object = None,
        commit: bool = True,
    ) -> bool:
        """#621 P3：待办消费单写口 pending→consumed/rolled。

        幂等：目标态已是 status 且无 payload_patch，或非 pending 源态 → False。
        payload_patch：可选 dict，并入既有 payload_json；允许 pending 原位落判决痕迹。
        commit=False 可入外层事务。
        """
        allowed = {"consumed", "rolled", "pending"}
        new_status = str(status or "").strip()
        if new_status not in allowed:
            raise ValueError(f"next_audience_todos status 非法：{new_status}")
        patch: Dict[str, object] | None = None
        if payload_patch is not None:
            if not isinstance(payload_patch, dict):
                raise ValueError(
                    "next_audience_todos payload_patch 须为对象，得 "
                    f"{type(payload_patch).__name__}"
                )
            patch = dict(payload_patch)
        row = self.conn.execute(
            "SELECT id, status, payload_json FROM next_audience_todos WHERE id=?",
            (int(todo_id),),
        ).fetchone()
        if row is None:
            return False
        current = str(row["status"] or "")
        if current == new_status and patch is None:
            return False
        # pending 原位更新只用于在同一 durable todo 落 payload 事实；无 patch 不复活。
        if new_status == "pending" and current != "pending":
            return False
        if current != "pending":
            return False
        if patch is not None:
            existing = self._parse_todo_payload_json(row["payload_json"])
            merged = dict(existing)
            merged.update(patch)
            payload_blob = self._coerce_todo_payload_json(merged)
            cur = self.conn.execute(
                """
                UPDATE next_audience_todos
                SET status=?, payload_json=?
                WHERE id=? AND status='pending'
                """,
                (new_status, sanitize_sqlite_text(payload_blob), int(todo_id)),
            )
        else:
            cur = self.conn.execute(
                """
                UPDATE next_audience_todos
                SET status=?
                WHERE id=? AND status='pending'
                """,
                (new_status, int(todo_id)),
            )
        if commit:
            self.conn.commit()
        return int(cur.rowcount or 0) > 0

    def insert_issue(
        self,
        state: GameState,
        *,
        kind: str,
        title: str,
        origin_kind: str = "",
        origin_ref: str = "",
        bar_value: int = 40,
        bar_good_meaning: str = "已平",
        bar_bad_meaning: str = "失控",
        inertia: int = 0,
        stage_text: str = "",
        severity: int = 50,
        region_hint: str = "",
        faction_hint: str = "",
        tags: List[str] | None = None,
        participants: Iterable[str] | str | None = None,
        target_roster: Iterable[str] | None = None,
        ongoing_effects: Dict[str, object] | None = None,
        cancellable: str = "never",
        cancel_cost: Dict[str, object] | None = None,
        effect_on_resolve: Dict[str, object] | None = None,
        effect_on_fail: Dict[str, object] | None = None,
        resolve_condition: str = "",
        fail_condition: str = "",
        end_turn: int = 0,
        stop_condition: Dict[str, object] | str = "",
        commitment_kind: str = "",
        stages_json: str | list | None = None,
        commit: bool = True,
    ) -> int:
        if kind not in ("situation", "initiative"):
            raise ValueError(f"issue kind 非法：{kind}")
        if cancellable not in ("decree", "never", "by_progress"):
            raise ValueError(f"cancellable 非法：{cancellable}")
        bar_value = max(0, min(100, int(bar_value)))
        # severity 与 bar_value 同为 0-100 分值，同样 clamp：原仅 int(severity) 直绑 SQLite，
        # severity=10**100 这类（int() 过得了但绑定超 64-bit）会抛 OverflowError——new_issues 段
        # 移除 broad except 后会逃逸成 SettlementAbort（cmr ni r2 codex）。clamp 既治溢出又补齐与
        # bar_value 一致的值域不变式（出域静默归 0-100，同 bar_value，非拒整项）。
        severity = max(0, min(100, int(severity)))
        phase = self._derive_issue_phase(bar_value)
        participant_roster = self._normalize_participant_roster(participants)
        participant_names = [item["character_id"] for item in participant_roster]
        normalized_targets = list(dict.fromkeys(
            str(character_id).strip() for character_id in (target_roster or [])
            if str(character_id).strip()
        ))
        from ming_sim.staged_commitment import stages_to_json
        # 字符串面经 stages_to_json 正确解析或响亮拒绝，禁止 char-iterate 静默存 []
        stages_blob = stages_to_json([] if stages_json is None else stages_json)
        issue_id = self.issues.insert({
            "kind": sanitize_sqlite_text(kind),
            "title": sanitize_sqlite_text(title),
            "origin_kind": sanitize_sqlite_text(origin_kind),
            "origin_ref": sanitize_sqlite_text(origin_ref),
            "origin_turn": state.turn,
            "bar_value": bar_value,
            "bar_good_meaning": sanitize_sqlite_text(bar_good_meaning),
            "bar_bad_meaning": sanitize_sqlite_text(bar_bad_meaning),
            "inertia": int(inertia),
            "phase": phase,
            "stage_text": sanitize_sqlite_text(stage_text),
            "status": "active",
            "severity": severity,
            "region_hint": sanitize_sqlite_text(region_hint),
            "faction_hint": sanitize_sqlite_text(faction_hint),
            "tags": safe_json_dumps(tags or [], ensure_ascii=False),
            "participants": safe_json_dumps(participant_names, ensure_ascii=False),
            "participant_roster": safe_json_dumps(participant_roster, ensure_ascii=False),
            "target_roster": safe_json_dumps(normalized_targets, ensure_ascii=False),
            "ongoing_effects": safe_json_dumps(ongoing_effects or {}, ensure_ascii=False),
            "cancellable": sanitize_sqlite_text(cancellable),
            "cancel_cost": safe_json_dumps(cancel_cost or {}, ensure_ascii=False),
            "effect_on_resolve": safe_json_dumps(effect_on_resolve or {}, ensure_ascii=False),
            "effect_on_fail": safe_json_dumps(effect_on_fail or {}, ensure_ascii=False),
            "resolve_condition": sanitize_sqlite_text(resolve_condition),
            "fail_condition": sanitize_sqlite_text(fail_condition),
            "end_turn": int(end_turn),
            "stop_condition": (
                safe_json_dumps(stop_condition, ensure_ascii=False, separators=(",", ":"))
                if isinstance(stop_condition, dict)
                else sanitize_sqlite_text(str(stop_condition or ""))
            ),
            "commitment_kind": sanitize_sqlite_text(str(commitment_kind or "")),
            "stages_json": sanitize_sqlite_text(stages_blob),
            "last_advance_turn": state.turn,
        })
        self.affairs.bind_from_origin_ref("issues", issue_id, origin_ref)
        if commit:
            self.conn.commit()
        self.register_character_knowledge_source(
            state,
            participant_roster,
            "assignment",
            title,
            stage_text,
            f"issue:{issue_id}",
            commit=commit,
        )
        return issue_id

    def insert_issue_with_affair_declaration(
        self,
        state: GameState,
        *,
        affair_declaration: Mapping[str, object],
        authorized_ids: set[int] | None = None,
        commit: bool = True,
        **issue_kwargs: object,
    ) -> int:
        """Issue row + affair pointer as one GameDB-owned write (ADR 0150-D3).

        Outer atomic / suspended commit owns lifecycle when already in a batch
        transaction; otherwise ``atomic`` pairs the two writes. Exceptions
        propagate loud — no half product.
        """
        from ming_sim.applier import atomic

        def _paired() -> int:
            issue_id = self.insert_issue(state, commit=False, **issue_kwargs)  # type: ignore[arg-type]
            self.affairs.attach_from_declaration(
                "issues",
                issue_id,
                affair_declaration,
                year=int(state.year),
                period=int(state.period),
                turn=int(state.turn),
                authorized_ids=authorized_ids,
            )
            return issue_id

        outer_owns = bool(
            getattr(self.conn, "_commit_suspended", False) or self.conn.in_transaction
        )
        if outer_owns or not commit:
            return _paired()
        with atomic(self):
            return _paired()

    def advance_issue(
        self,
        state: GameState,
        issue_id: int,
        *,
        trigger_kind: str,
        trigger_ref: str = "",
        delta_bar: int = 0,
        stage_text: str = "",
        narrative: str = "",
        metric_delta: Dict[str, int] | None = None,
        inertia_delta: int = 0,
        commit: bool = True,
    ) -> sqlite3.Row | None:
        row = IssueStore(self.conn).read_ack_due_commitment_issue((issue_id,))
        if row is None or row["status"] != "active":
            return None
        # 崩坏能力由 effect_on_fail 是否非空判定：有崩坏效果=会崩坏（bar 能到 0、failed 终结）；
        # 空=不会崩坏（天灾/正面机遇等不可控或无失败态局势，bar 下限钳到 1，永不 failed，
        # 只靠 ongoing_effects 每月持续流血）。
        can_collapse = bool(loads_effect_dict(row["effect_on_fail"]))  # 非 dict→{}→False（#117 统一守门）
        floor = 0 if can_collapse else 1
        # clamp single advance
        delta_bar = max(-50, min(50, int(delta_bar)))
        from_value = int(row["bar_value"])
        to_value = max(floor, min(100, from_value + delta_bar))
        actual_delta = to_value - from_value
        from_stage_text = row["stage_text"]
        to_stage_text = stage_text or from_stage_text
        new_phase = self._derive_issue_phase(to_value)
        new_status = row["status"]
        closed_turn = row["closed_turn"]
        has_stop_condition = _has_stop_condition(row["stop_condition"])
        commitment_stop_condition = (
            bool(row["commitment_kind"])
            or has_stop_condition
            or _is_commitment_stop_condition(row["resolve_condition"])
        )
        if to_value >= 100 and not commitment_stop_condition:
            new_status = "resolved"
            closed_turn = state.turn
        elif to_value <= 0 and can_collapse:
            new_status = "failed"
            closed_turn = state.turn
        # inertia 可被本次行动改变（钳到 -10..+10 五档区间）
        new_inertia = int(row["inertia"]) + int(inertia_delta)
        new_inertia = max(-10, min(10, new_inertia))
        self.issues.update(issue_id, {
            "bar_value": to_value,
            "phase": new_phase,
            "stage_text": sanitize_sqlite_text(to_stage_text),
            "status": new_status,
            "inertia": new_inertia,
            "closed_turn": closed_turn,
            "last_advance_turn": state.turn,
        })
        self.issues.append_advance({
            "issue_id": issue_id,
            "turn": state.turn,
            "trigger_kind": sanitize_sqlite_text(trigger_kind),
            "trigger_ref": sanitize_sqlite_text(trigger_ref),
            "delta_bar": actual_delta,
            "from_value": from_value,
            "to_value": to_value,
            "from_stage_text": sanitize_sqlite_text(from_stage_text),
            "to_stage_text": sanitize_sqlite_text(to_stage_text),
            "narrative": sanitize_sqlite_text(narrative),
            "metric_delta": safe_json_dumps(metric_delta or {}, ensure_ascii=False),
        })
        if commit:
            self.conn.commit()
        return IssueStore(self.conn).read_ack_due_commitment_issue((issue_id,))

    def close_issue(
        self,
        state: GameState,
        issue_id: int,
        *,
        reason: str,
        narrative: str = "",
        commit: bool = True,
    ) -> sqlite3.Row | None:
        """LLM 主动通知收尾。reason 必须是 'resolved' 或 'failed'。不看 bar 门槛。"""
        if reason not in ("resolved", "failed"):
            raise ValueError(f"close_issue reason 非法：{reason}")
        row = IssueStore(self.conn).read_ack_due_commitment_issue((issue_id,))
        if row is None or row["status"] != "active":
            return None
        # 不可崩坏局势（effect_on_fail 空：天灾/不可控灾害）没有「失败终结」态——LLM 误判 failed
        # 时拒绝结案，留 active 继续靠 ongoing_effects 流血，只能靠 resolved（赈济平息）收尾。
        if reason == "failed" and not loads_effect_dict(row["effect_on_fail"]):  # #117 统一守门
            print(f"[INFO] close_issue 已拒：issue {issue_id}（{row['title']}）无 effect_on_fail，不可崩坏，保持 active。")
            return None
        from_value = int(row["bar_value"])
        # resolved → 抬到 100；failed → 压到 0；用于 inertia/UI 一眼看懂
        to_value = 100 if reason == "resolved" else 0
        actual_delta = to_value - from_value
        from_stage_text = row["stage_text"]
        to_stage_text = narrative or from_stage_text
        new_phase = self._derive_issue_phase(to_value)
        self.issues.update(issue_id, {
            "bar_value": to_value,
            "phase": new_phase,
            "stage_text": sanitize_sqlite_text(to_stage_text),
            "status": reason,
            "closed_turn": state.turn,
            "last_advance_turn": state.turn,
        })
        self.issues.append_advance({
            "issue_id": issue_id,
            "turn": state.turn,
            "trigger_kind": "close",
            "trigger_ref": sanitize_sqlite_text(reason),
            "delta_bar": actual_delta,
            "from_value": from_value,
            "to_value": to_value,
            "from_stage_text": sanitize_sqlite_text(from_stage_text),
            "to_stage_text": sanitize_sqlite_text(to_stage_text),
            "narrative": sanitize_sqlite_text(narrative),
            "metric_delta": "{}",
        })
        if commit:
            self.conn.commit()
        return IssueStore(self.conn).read_ack_due_commitment_issue((issue_id,))

    # ── 帝国修正（legacies 表）：结案留下的长期百分比修正符，落账层放大/缩小增量 ────
    def insert_legacy(
        self,
        state: GameState,
        *,
        name: str,
        modifiers: Dict[str, object],
        narrative_hint: str = "",
        duration_months: int = 24,
        source_issue_id: int | None = None,
        clear_gate: Dict[str, str] | None = None,
        legacy_key: str = "",
        commit: bool = True,
    ) -> int:
        """结案产生持续修正符。start_month=当前绝对月，duration_months=-1 为永久。
        clear_gate 非空时：靠程序按 _gate_passed 判定消除（见 issues.clear_gated_legacies），与时长无关。"""
        start_month = int(state.year) * 12 + int(state.period)
        cur = ReignStateStore(self.conn).write_insert_legacy((
                str(name)[:60], source_issue_id,
                json.dumps(modifiers, ensure_ascii=False),
                str(narrative_hint)[:200],
                start_month, int(duration_months),
                json.dumps(clear_gate or {}, ensure_ascii=False),
                str(legacy_key)[:60],
            ))
        if commit:
            self.conn.commit()
        self._legacy_mod_cache = None  # active 集变了，修正符缓存失效
        return int(cur.lastrowid)

    def list_active_legacies(self, state: GameState) -> List[sqlite3.Row]:
        """当前仍生效的帝国修正，顺手把已到期的失活。"""
        external_transaction = bool(getattr(self.conn, "_commit_suspended", False) or self.conn.in_transaction)
        self.expire_legacies(state, commit=not external_transaction)
        return ReignStateStore(self.conn).read_list_active_legacies()

    def expire_legacies(self, state: GameState, commit: bool = True) -> List[int]:
        """到期失活：当前月 >= start_month + duration_months（永久 -1 永不到期）。"""
        now = int(state.year) * 12 + int(state.period)
        rows = ReignStateStore(self.conn).read_expire_legacies()
        expired: List[int] = []
        for r in rows:
            dur = int(r["duration_months"])
            if dur < 0:
                continue
            if now >= int(r["start_month"]) + dur:
                expired.append(int(r["id"]))
        if expired:
            ReignStateStore(self.conn).write_expire_legacies([(i,) for i in expired])
            if commit:
                self.conn.commit()
            self._legacy_mod_cache = None  # active 集变了，修正符缓存失效
        return expired

    def legacy_remaining_months(self, row: sqlite3.Row, state: GameState) -> int:
        """剩余月数；-1=永久。"""
        dur = int(row["duration_months"])
        if dur < 0:
            return -1
        now = int(state.year) * 12 + int(state.period)
        return max(0, int(row["start_month"]) + dur - now)

    def legacy_modifiers(self, state: GameState) -> Dict[str, object]:
        """聚合所有 active 遗产的百分比修正符，同维度累加（A 方案）。返回：
        {
          "国库": net_pct, "内库": net_pct, "民心": net_pct, "皇威": net_pct,
          "regions": {region_id: {field: net_pct, ...}, ...},
          "armies":  {army_id:  {field: net_pct, ...}, ...},
        }
        net_pct 为带符号整数百分比；落账时 base>=0 用 ×(1+net/100)，base<0 用 ×(1-net/100)。
        结果缓存，active 遗产集变化时由 insert_legacy/expire_legacies 清空。
        """
        # expire 可能改变 active 集 → 先跑。若调用方已有外层事务，不能在读修正符时提交；
        # 且该未提交 active 集不可写入缓存，否则 rollback 后会留下脏 cache。
        cache_allowed = not (getattr(self.conn, "_commit_suspended", False) or self.conn.in_transaction)
        self.expire_legacies(state, commit=cache_allowed)
        if cache_allowed and self._legacy_mod_cache is not None:
            return self._legacy_mod_cache
        agg: Dict[str, object] = {"国库": 0, "内库": 0, "民心": 0, "皇威": 0, "regions": {}, "armies": {}}
        for lg in ReignStateStore(self.conn).read_legacy_modifiers():
            eff = load_stored_json(
                lg["modifiers"], label="遗产修正 modifiers", blank={},
            )
            if not isinstance(eff, dict):
                raise ValueError("遗产修正 modifiers 必须为对象")
            for acc in ("国库", "内库", "民心", "皇威"):
                v = eff.get(acc)
                if isinstance(v, (int, float)):
                    agg[acc] = int(agg[acc]) + int(v)
            for scope in ("regions", "armies"):
                block = eff.get(scope)
                if not isinstance(block, dict):
                    continue
                dst = agg[scope]  # type: ignore[assignment]
                for entity_id, fields in block.items():
                    if not isinstance(fields, dict):
                        continue
                    bucket = dst.setdefault(str(entity_id), {})  # type: ignore[union-attr]
                    for field, pct in fields.items():
                        if isinstance(pct, (int, float)):
                            bucket[str(field)] = int(bucket.get(str(field), 0)) + int(pct)
        if cache_allowed:
            self._legacy_mod_cache = agg
        return agg

    @staticmethod
    def apply_legacy_pct(base: int, net_pct: int) -> int:
        """遗产百分比修正：base>=0 → base×(1+net/100)；base<0 → base×(1-net/100)。net=0 原样。"""
        if net_pct == 0 or base == 0:
            return int(base)
        factor = (1 + net_pct / 100.0) if base >= 0 else (1 - net_pct / 100.0)
        return int(round(base * factor))

    def cancel_issue(
        self,
        state: GameState,
        issue_id: int,
        *,
        narrative: str = "",
        applied_cost: Dict[str, object] | None = None,
        commit: bool = True,
    ) -> sqlite3.Row | None:
        row = IssueStore(self.conn).read_ack_due_commitment_issue((issue_id,))
        if row is None or row["status"] != "active":
            return None
        self.issues.update(issue_id, {
            "status": "dropped",
            "closed_turn": state.turn,
            "last_advance_turn": state.turn,
        })
        self.issues.append_advance({
            "issue_id": issue_id,
            "turn": state.turn,
            "trigger_kind": "cancel",
            "delta_bar": 0,
            "from_value": int(row["bar_value"]),
            "to_value": int(row["bar_value"]),
            "narrative": narrative,
            "metric_delta": json.dumps(applied_cost or {}, ensure_ascii=False),
        })
        if commit:
            self.conn.commit()
        return IssueStore(self.conn).read_ack_due_commitment_issue((issue_id,))

    def list_recent_issue_advances(self, issue_id: int, limit: int = 3) -> List[sqlite3.Row]:
        return IssueStore(self.conn).read_list_recent_issue_advances((issue_id, limit))

    @staticmethod
    def coerce_beyond_intent_flag(value: object) -> int:
        """闭世界肯定识别器：仅契约内肯定表示 →1；缺席/否定/空/畸形一律 →0。

        肯定：True / 非零 int·float / 肯定串集 {"1","true","yes","on","是","有","真"}。
        开放兜底永不得回归——畸形输入不得捏造肯定标记（0072/0118 真相层）。
        """
        if value is None:
            return 0
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 1 if int(value) != 0 else 0
        text = str(value).strip().lower()
        return 1 if text in {"1", "true", "yes", "on", "是", "有", "真"} else 0

    def record_issue_economy_move(
        self,
        state: GameState,
        account: str,
        delta: int,
        category: str,
        reason: str,
        purpose: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        origin_ref: str = "",
        beyond_intent: object = 0,
        commit: bool = True,
        apply_income_modifier: bool = True,
    ) -> int:
        """记一笔经济流水到 economy_ledger，同步更新 metrics[account]。

        purpose/target_kind/target_id 仅对 extractor 抽出的 economy_moves（自由拨款）填，
        flows 月固定支出与所有收入一律 None。受控枚举见 constants.ECONOMY_PURPOSES。

        beyond_intent：#622 旨外恶果/受益同列标记（与 origin_ref 同载体，非平行轨）。

        遗产修正：account 上若有 active 遗产百分比修正符，先按 apply_legacy_pct 放大/缩小 delta
        再落账。修正折进本笔流水，不另立账行。
        category=='局势遗产' 时不再二次修正（避免自乘，且当前已无该类调用）。
        帝国修正只对收入（delta>0 正向流水）生效；支出（delta<0）按面值落账（issue #341）——
        即本路径仅以 delta>0 调 apply_legacy_pct（其 base>=0 ×(1+net/100) 分支）；
        apply_legacy_pct 自身的 base<0 ×(1-net/100) 分支由 region/army 等其它调用方使用，本路径不走。
        双边钱库转移的目标腿不属于外生收入，调用方以 apply_income_modifier=False
        禁止再次放大已从来源库实扣的数。
        """
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise TypeError("delta must be an integer")
        # #1889：account 必须在 ECONOMY_ACCOUNTS 内（替代原 FK→economy_accounts）。
        # 下面 state.metrics[account] 也会 KeyError，但那不是 fail-loud 的可读报错。
        if account not in ECONOMY_ACCOUNTS:
            raise ValueError(f"economy_ledger account 非法：{account!r}")
        if apply_income_modifier and category != "局势遗产":
            net_pct = int(self.legacy_modifiers(state).get(account, 0) or 0)  # type: ignore[arg-type]
            if net_pct and delta > 0:
                delta = self.apply_legacy_pct(int(delta), net_pct)
        before = int(state.metrics[account])
        after = max(0, before + int(delta))
        actual = after - before
        if actual == 0:
            return 0
        state.metrics[account] = after
        # #1889：活余额真源 = metrics 表。流水行与活余额必须**同一事务**落库，
        # 否则 DB 与内存会分叉：旧实现只改内存 state.metrics，落库全靠 save_state，
        # 而 economy_accounts 那张镜像表又由 load_state 反向盖回内存——两边各写各的。
        # 实测（#1490 批红整批回滚）：一笔已提交的 7 万两内帑发饷，内存 433 / DB 440。
        # 此处随流水同事务写 metrics，恢复（reload_state_from_db→load_state）与
        # 回滚都读到同一个真值。
        self.reign.upsert_metric(account, after)
        beyond_flag = self.coerce_beyond_intent_flag(beyond_intent)
        self.reign.insert_ledger({
            "turn": state.turn,
            "year": state.year,
            "period": state.period,
            "account": account,
            "delta": actual,
            "balance_after": after,
            "category": category,
            "reason": reason,
            "actor": "事项推演",
            "purpose": purpose,
            "target_kind": target_kind,
            "target_id": target_id,
            "origin_ref": origin_ref,
            "beyond_intent": beyond_flag,
        })
        if commit:
            self.conn.commit()
        return actual

    def record_fiscal_config_change(
        self, *, turn: int, key: str, old_value: int, new_value: int,
        origin_ref: str, reason: str = "", beyond_intent: object = 0,
    ) -> None:
        """Append immutable provenance for a fiscal value change.

        The caller owns the surrounding transaction so the history row and live
        configuration can never commit separately.

        beyond_intent：#1260 旨外恶果/受益同列标记（与 origin_ref 同载体，非平行轨）。
        """
        beyond_flag = self.coerce_beyond_intent_flag(beyond_intent)
        self.fiscal_config.append_history("change", {
            "turn": int(turn), "key": key, "old_value": int(old_value),
            "new_value": int(new_value), "delta": int(new_value) - int(old_value),
            "origin_ref": origin_ref, "reason": reason[:240], "beyond_intent": beyond_flag,
        })

    def list_fiscal_effects_for_dossier(self, dossier_id: int) -> List[Dict[str, object]]:
        origin = f"dossier:{int(dossier_id)}"
        rows: List[Dict[str, object]] = []
        for item in self.fiscal_config.effects(origin):
            item["beyond_intent"] = bool(self.coerce_beyond_intent_flag(item.get("beyond_intent")))
            rows.append(item)
        return rows

    def list_dossier_durable_effects(self, dossier_id: int) -> List[Dict[str, object]]:
        """#1260 单源：案卷 durable_effects = economy + fiscal（已归一 beyond_intent bool）。

        只供事实，不参与裁决形状。四读端改调此处，禁再各写一份合并。
        """
        return list(self.list_economy_moves_for_dossier(int(dossier_id))) + list(
            self.list_fiscal_effects_for_dossier(int(dossier_id))
        )

    def list_dossier_actual_rail(self, dossier_id: int) -> List[Dict[str, object]]:
        """实况合并读：durable_effects + actual_progress（due_review 形参数化共用）。

        不把 0058 奏报并入。actual_progress 行标 rail='actual_progress'。
        """
        out: List[Dict[str, object]] = []
        for item in self.list_dossier_durable_effects(int(dossier_id)):
            row = dict(item)
            row.setdefault("rail", "durable_effect")
            out.append(row)
        for item in self.dossiers.actual_progress(int(dossier_id)):
            row = dict(item)
            row["rail"] = "actual_progress"
            out.append(row)
        return out

    def dossier_has_beyond_intent(self, dossier_id: int) -> bool:
        """#1260 单源：案卷是否含任何旨外 durable effect（economy 或 fiscal）。

        只供事实，不另立裁决函数。
        """
        return any(
            bool(row.get("beyond_intent"))
            for row in self.list_dossier_durable_effects(int(dossier_id))
        )

    def list_economy_moves_for_dossier(self, dossier_id: int) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        for row in ReignStateStore(self.conn).read_list_economy_moves_for_dossier((f"dossier:{int(dossier_id)}",)):
            item = dict(row)
            # Normalize beyond_intent to bool for adjudicator consumers (#622).
            item["beyond_intent"] = bool(self.coerce_beyond_intent_flag(
                item.get("beyond_intent")
            ))
            rows.append(item)
        return rows

    def kv_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv_store(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, value),
        )
        self.conn.commit()

    # ----- secret_orders（密令系统）-----

    @staticmethod
    def _normalize_participant_roster(
        participants: Iterable[object] | str | None, *, strict_structured: bool = False,
    ) -> List[Dict[str, object]]:
        """Normalize ADR 0053 entries while retaining explicit legacy string input."""
        values = [participants] if isinstance(participants, str) else list(participants or [])
        roster: List[Dict[str, object]] = []
        for value in values:
            if isinstance(value, Mapping):
                if strict_structured:
                    character_id = str(value.get("character_id") or "").strip()
                    tier_value = value.get("tier")
                else:
                    character_id = str(value.get("character_id") or value.get("name") or "").strip()
                    tier_value = value.get("tier") if "tier" in value else value.get("档")
                if strict_structured and not character_id:
                    raise ValueError("参与人物 character_id 不能为空")
                if strict_structured and tier_value is None:
                    raise ValueError("参与人物 tier 必须显式提供")
                tier = str(tier_value or ("" if strict_structured else "知情")).strip()
                raw_role = str(value.get("role") or value.get("职分") or "")
                role = raw_role if raw_role.strip() else ""
                delegator = str(value.get("delegator_id") or value.get("delegator") or "").strip()
            else:
                if strict_structured:
                    raise ValueError("结构化参与人名单每项必须为对象")
                character_id, tier, role, delegator = str(value).strip(), "知情", "", ""
            if not character_id:
                continue
            if tier not in PARTICIPANT_TIERS:
                raise ValueError(f"参与人机械档非法：{tier}")
            item = {"character_id": character_id, "tier": tier, "role": role,
                    "delegator_id": delegator or None}
            if item not in roster:
                roster.append(item)
        return roster

    def _validate_participant_roster_references(
        self, roster: Iterable[Mapping[str, object]],
    ) -> None:
        """Enforce ADR 0053 character primary-key references at the DB write seam."""
        entries = list(roster)
        referenced = {
            str(value).strip()
            for item in entries
            for value in (item.get("character_id"), item.get("delegator_id"))
            if str(value or "").strip()
        }
        if not referenced:
            return
        known = {str(row["name"]) for row in self.characters.named_status_rows(referenced)}
        from ming_sim.participant_roster import is_non_person_participant_name

        def _roster_ref_error(label: str, name: str) -> ValueError:
            # #1380：拒「皇帝」等非人通称时给人话提示，禁裸「参与人物不存在：皇帝」
            if is_non_person_participant_name(name):
                return ValueError(
                    f"{label}不存在：{name}。"
                    f"人物参与人须为朝堂名册中的大臣姓名，"
                    f"不可填「{name}」等非人通称或机构名。"
                )
            return ValueError(
                f"{label}不存在：{name}。"
                f"请填写朝堂名册中已有的大臣姓名。"
            )

        for item in entries:
            character_id = str(item.get("character_id") or "").strip()
            delegator_id = str(item.get("delegator_id") or "").strip()
            if character_id not in known:
                raise _roster_ref_error("参与人物", character_id)
            if delegator_id and delegator_id not in known:
                raise _roster_ref_error("委派人", delegator_id)

    def _character_knowledge_events(self, character_name: str, *, include_exclusions: bool = False) -> List[Dict[str, object]]:
        result = []
        for item in self.character_knowledge.events_for(
            character_name, include_exclusions=include_exclusions,
        ):
            source_id = str(item["source_id"] or "")
            if (not character_name and (
                (source_id.startswith("turn_report:") and not source_id.endswith(":public"))
                or re.fullmatch(r"settlement:narrative:\d+", source_id)
            )):
                continue
            result.append(item)
        known_sources = {str(item["source_id"]) for item in result}
        # #883 contract: this is the sole private read seam for secret orders.
        # Briefs deliberately do not carry a shared source id and therefore
        # cannot be materialized into gazettes or public events.
        if character_name:
            for row in self.character_knowledge.secret_briefs_for(str(character_name)):
                source_id = f"secret_order_brief:{int(row['order_id'])}"
                if source_id in known_sources:
                    continue
                result.append({
                    "turn": int(row["turn"]), "year": int(row["year"]),
                    "period": int(row["period"]), "kind": "secret_order_brief",
                    "title": row["title"], "body": row["body"], "source_id": source_id,
                    **({"excluded_names": json.dumps(
                        self.knowledge_exclusions_for_source(source_id), ensure_ascii=False,
                    )} if include_exclusions else {}),
                })
                known_sources.add(source_id)
        for row in self.character_knowledge.all_sources():
            names = participant_roster_names(row["participant_roster"])
            if str(row["source_id"]) in known_sources or str(character_name) not in names:
                continue
            item = {"turn": int(row["turn"]), "year": int(row["year"]),
                    "period": int(row["period"]), "kind": row["kind"],
                    "title": row["title"], "body": row["body"], "source_id": row["source_id"]}
            if include_exclusions:
                item["excluded_names"] = row["excluded_names"] or "[]"
            result.append(item)
            known_sources.add(str(row["source_id"]))
        # Durable records are discovered by their participant_roster column,
        # not by record kind.  This keeps a new producer from needing a reader
        # branch (or a second adapter call) merely to become knowable.
        for table, columns in self._participant_roster_tables():
            quoted = '"' + table.replace('"', '""') + '"'
            selected = {name: name for name in columns}
            id_expr = selected.get("id", "rowid")
            source_expr = selected.get("source_id")
            # Legacy tables without source_id retain the conventional singular
            # table prefix (issues -> issue); newer records should persist the
            # explicit source_id in their own table.
            fallback_prefix = table[:-1] if table.endswith("s") else table
            source_sql = source_expr if source_expr else f"'{fallback_prefix}:' || {id_expr}"
            turn_expr = selected.get("turn") or selected.get("origin_turn") or selected.get("created_turn") or "0"
            year_expr = selected.get("year") or selected.get("created_year") or "0"
            period_expr = selected.get("period") or selected.get("created_period") or "0"
            kind_expr = selected.get("kind") or "'assignment'"
            title_expr = selected.get("title") or "''"
            body_expr = selected.get("body") or selected.get("stage_text") or selected.get("content") or selected.get("decree_text") or "''"
            query = (
                f"SELECT {turn_expr} AS turn, {year_expr} AS year, {period_expr} AS period, "
                f"{kind_expr} AS kind, {title_expr} AS title, {body_expr} AS body, "
                f"{source_sql} AS source_id, participant_roster "
                f"FROM {quoted} WHERE participant_roster <> '[]' ORDER BY turn, {id_expr}"
            )
            for row in self.conn.execute(query).fetchall():
                source_id = str(row["source_id"])
                if source_id in known_sources:
                    continue
                names = participant_roster_names(row["participant_roster"])
                if str(character_name) not in names:
                    continue
                result.append({
                    "turn": int(row["turn"] or 0), "year": int(row["year"] or 0),
                    "period": int(row["period"] or 0),
                    "kind": row["kind"] or "assignment", "title": row["title"],
                    "body": row["body"] or "", "source_id": source_id,
                    **({"excluded_names": "[]"} if include_exclusions else {}),
                })
                known_sources.add(source_id)
        return result

    def _participant_roster_tables(self) -> List[tuple[str, set[str]]]:
        """List durable user tables that expose the common roster column."""
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        result: List[tuple[str, set[str]]] = []
        for row in tables:
            table = str(row["name"])
            # #1889：decree_dossiers 不在此通用扫描面——案卷经
            # register_character_knowledge_source 投影进 character_knowledge_sources
            # （含密令可见性边界），案卷表本身不作为知识来源表被直读。
            if table in {"character_knowledge_sources", "decree_dossiers"}:
                continue
            columns = {
                str(column["name"])
                for column in self.conn.execute(
                    "PRAGMA table_info(\"" + table.replace('"', '""') + "\")"
                ).fetchall()
            }
            if "participant_roster" in columns:
                result.append((table, columns))
        return result

    def knowledge_exclusions_for_source(self, source_id: str) -> List[str]:
        """Return the durable secrecy boundary attached to a source record."""
        source = str(source_id or "")
        if self.character_knowledge.has_event_for_source(source):
            return self.character_knowledge.exclusions_for_source(source)
        # #883 CR R1 S2: bare ``secret_order:`` shared *sources* are no longer
        # produced (create/update → private briefs; production disclosure →
        # ``secret_order_disclosure:``; register gate rejects the prefix).
        # Retained: ``record_public_knowledge_event`` still inherits exclusions
        # by looking up secret_orders when source_id is ``secret_order:N`` —
        # exercised by AC harness paths (test_character_knowledge_489 /
        # test_minister_context / test_web_chat_serialization_393). Without
        # this branch those writes lose the blacklist. session.py only DELETEs
        # legacy sources with this prefix; no live production producer.
        order_id = self.character_knowledge.secret_order_id_in(source)
        if order_id is not None:
            order = CharacterKnowledgeStore(self.conn).read_knowledge_exclusions_for_source((order_id,))
            if order is not None:
                from ming_sim.entities.character_knowledge.store import _load_list

                return _load_list(order["excluded_names"])
        # #1829 reopen：公开说法排除名单与正文同表，按 public_saying:<id> 回查。
        saying_id = self.character_knowledge.public_saying_id_in(source)
        if saying_id is not None:
            saying = CharacterKnowledgeStore(self.conn).read_knowledge_exclusions_for_source_excluded_names((saying_id,))
            if saying is not None:
                from ming_sim.entities.character_knowledge.store import _load_list

                return _load_list(saying["excluded_names"])
            return []
        return self.character_knowledge.exclusions_for_source(source)

    def knowledge_exclusion_targets_for_source(self, source_id: str) -> Dict[str, List[str]]:
        from ming_sim.entities.character_knowledge.store import _load_targets

        source = str(source_id or "")
        # Private briefs and retained bare secret-order sources share the
        # canonical exclusions persisted on secret_orders.
        order_id = self.character_knowledge.secret_order_id_in(source)
        if order_id is not None:
            row = CharacterKnowledgeStore(self.conn).read_knowledge_exclusion_targets_for_source((order_id,))
            payload = _load_targets(row["excluded_targets"] if row else None)
            return {"people": payload.get("people", []), "offices": payload.get("offices", [])}
        # #1829 reopen：公开说法排除目标与正文同表。
        saying_id = self.character_knowledge.public_saying_id_in(source)
        if saying_id is not None:
            row = CharacterKnowledgeStore(self.conn).read_knowledge_exclusion_targets_for_source_excluded_targets((saying_id,))
            payload = _load_targets(row["excluded_targets"] if row else None)
            return {"people": payload.get("people", []), "offices": payload.get("offices", [])}
        payload = self.character_knowledge.exclusion_targets_for_source(source)
        return {"people": payload.get("people", []), "offices": payload.get("offices", [])}

    def record_participation_record(
        self, state: GameState, record: Mapping[str, object], *, kind: str,
        source_id: str = "", excluded_names: Optional[Iterable[str]] = None,
        commit: bool = True,
    ) -> None:
        """Adapt any durable record carrying participants into the knowledge ledger."""
        participants: List[str] = []
        roster = record.get("participant_roster")
        if isinstance(roster, (list, tuple)):
            for item in roster:
                if isinstance(item, Mapping):
                    name = item.get("character_id") or item.get("name")
                    if name:
                        participants.append(str(name))
        for key in ("participants", "participant_names", "actors"):
            value = record.get(key)
            if isinstance(value, str):
                participants.append(value)
            elif isinstance(value, Iterable):
                for item in value:
                    if isinstance(item, Mapping):
                        name = item.get("character_id") or item.get("name")
                        if name:
                            participants.append(str(name))
                    else:
                        participants.append(str(item))
        for key in ("assignee", "minister_name", "character_name", "actor"):
            value = record.get(key)
            if value:
                participants.append(str(value))
        roster = [{"character_id": name} for name in dict.fromkeys(participants) if name]
        self.register_character_knowledge_source(
            state, roster, kind, str(record.get("title") or kind),
            str(record.get("body") or record.get("content") or ""),
            source_id or str(record.get("source_id") or ""), excluded_names=excluded_names,
            commit=commit,
        )
        self.record_character_participation(
            state, participants, kind, str(record.get("title") or kind),
            str(record.get("body") or record.get("content") or ""),
            source_id or str(record.get("source_id") or ""), excluded_names, commit=commit,
        )

    @staticmethod
    def _is_audience_chat_shared_channel(kind: str = "", source_id: str = "") -> bool:
        """召对 chat → shared-ledger channel (#883/#976)."""
        return str(kind or "") == "audience" or str(source_id or "").startswith("chat_message:")

    def _is_active_secret_order_assignee(self, minister_name: str) -> bool:
        """True when this minister holds an active/pending private secret brief."""
        name = str(minister_name or "").strip()
        if not name:
            return False
        return self.character_knowledge.has_active_secret_brief(name)

    def _delete_shared_knowledge_source_ids(
        self, source_ids: Iterable[str], *, commit: bool = True,
    ) -> None:
        """Delete shared ledger rows by source_id (events + sources)."""
        self.character_knowledge.delete_by_source_ids(source_ids, commit=commit)

    def _coerce_positive_message_ids(
        self, message_ids: Optional[Iterable[Any]] = None,
    ) -> List[int]:
        """Normalize chat_message id pins to a stable unique positive list."""
        out: List[int] = []
        seen: set = set()
        for raw in message_ids or ():
            try:
                mid = int(raw)
            except (TypeError, ValueError):
                continue
            if mid > 0 and mid not in seen:
                seen.add(mid)
                out.append(mid)
        return out

    def _secret_origin_message_protection(self) -> Dict[int, bool]:
        """Canonical release-ban map for oral-decree chat-turn messages.

        Pending and failed secret actions retain the stage-time pin
        until they are committed or explicitly dropped.  The brief takes over
        that pin once classification succeeds.  A
        completed ``chat_turns`` row is the structural provenance for the full
        exchange, so its paired minister reply belongs to the same secret
        bloodline.  Release must never project either side into shared tracks.

        ``True`` means a durable brief owns the bloodline; ``False`` means a
        pending/failed stage pin still owns it.  This distinction is load-bearing for
        replies bound to a chat turn after classification: release is the first
        seam that can see and park those durable descendants as ``withheld``.
        """
        out: Dict[int, bool] = {}
        brief_rows = self.character_knowledge.secret_brief_pins()
        pending_rows = self.conn.execute(
            "SELECT payload_json FROM pending_actions "
            "WHERE kind='secret_order' AND status IN ('pending','failed')"
        ).fetchall()
        for row in brief_rows:
            for mid in self._brief_origin_chat_message_ids(int(row["order_id"])):
                out[mid] = True
        for row in pending_rows:
            payload = load_stored_object(row["payload_json"], label="payload_json")
            mid = self._parse_origin_chat_message_id(payload)
            if mid is not None:
                out.setdefault(mid, False)
        if out:
            placeholders = ",".join("?" for _ in out)
            try:
                turns = self.conn.execute(
                    f"SELECT user_message_id, minister_message_id FROM chat_turns "
                    f"WHERE user_message_id IN ({placeholders})",
                    tuple(sorted(out)),
                ).fetchall()
            except sqlite3.OperationalError:
                turns = []
            for turn in turns:
                durable = any(
                    out.get(int(raw), False)
                    for raw in (turn["user_message_id"], turn["minister_message_id"])
                    if raw is not None
                )
                for raw in (turn["user_message_id"], turn["minister_message_id"]):
                    try:
                        mid = int(raw)
                    except (TypeError, ValueError):
                        continue
                    if mid > 0:
                        out[mid] = bool(out.get(mid, False) or durable)
        return out

    def _withhold_origin_chat_messages(
        self,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        *,
        commit: bool = True,
    ) -> List[int]:
        """Withhold exact oral-decree message ids (#976 message-level provenance).

        Structural rule (id bloodline, never content matching): only the pinned
        chat_message rows are secret-origin.  Follows the message wherever it
        lives (speaker vs assignee, 跨人承办).  Confirmation user lines and
        pure-public same-window users are not guessed via (assignee, role=user).

        Also re-withholds already-projected (released/private) pinned rows and
        deletes any shared knowledge keyed by those source ids (id-based
        cleanup if anything leaked before classification).
        """
        pins = self._coerce_positive_message_ids(origin_chat_message_ids)
        if not pins:
            if commit:
                self.conn.commit()
            return []
        try:
            live_ids = self.chat_messages.existing_ids(pins)
        except sqlite3.OperationalError:
            live_ids = []
        source_ids: List[str] = []
        for mid in live_ids:
            self.chat_messages.set_knowledge_status(mid, "withheld")
            source_ids.append(f"chat_message:{mid}")
        self._delete_shared_knowledge_source_ids(source_ids, commit=False)
        if commit:
            self.conn.commit()
        return live_ids

    def _project_audience_chat_message(
        self,
        state: GameState,
        *,
        message_id: int,
        minister_name: str,
        content: str,
        origin_turn: Optional[int] = None,
        commit: bool = False,
    ) -> str:
        """Single projection seam for one held audience row (#976 DRY).

        Stamps knowledge with the message's original ``origin_turn`` (not the
        release-time state.turn).  Only message provenance decides the rail:
        a non-secret audience line is public even when its speaker separately
        holds an active secret order.
        """
        source_id = f"chat_message:{int(message_id)}"
        minister = str(minister_name or "").strip()
        body = str(content or "")
        proj_turn = int(origin_turn if origin_turn is not None else state.turn)
        proj_state = state if proj_turn == int(state.turn) else self._state_for_turn(state, proj_turn)
        self.record_participation_record(
            proj_state,
            {"participants": [minister], "title": "召对", "body": body},
            kind="audience", source_id=source_id, commit=False,
        )
        status = "released"
        self.chat_messages.set_knowledge_status(int(message_id), status)
        if commit:
            self.conn.commit()
        return status

    def release_held_audience_knowledge(
        self,
        *,
        minister_name: Optional[str] = None,
        minister_names: Optional[Iterable[str]] = None,
        exclude_message_ids: Optional[Iterable[int]] = None,
        commit: bool = True,
    ) -> int:
        """唯一投轨出口：held → shared 或 private（#976）。

        分类后（scoped，仅接令者/口谕 speaker）与月末 settle（全局）调用。
        withheld 永不放行。接令者 active brief 时只进私有事件轨，不进共享源。

        Message-level provenance: rows whose id is a registered secret-origin
        pin (or explicitly excluded) are **not** projected — they are parked as
        withheld so create(A) cannot smuggle B's yet-unclassified oral line into
        the shared ledger via unfiltered global release.
        """
        name_filter = str(minister_name or "").strip()
        name_set = {
            str(n).strip() for n in (minister_names or ()) if str(n or "").strip()
        }
        if name_filter:
            name_set.add(name_filter)
        explicit_exclude = set(self._coerce_positive_message_ids(exclude_message_ids))
        protection = self._secret_origin_message_protection()
        exclude = explicit_exclude | set(protection)
        try:
            rows = self.chat_messages.held_rows(sorted(name_set) if name_set else None)
        except sqlite3.OperationalError:
            return 0
        if not rows:
            return 0
        state = self.load_state()
        released = 0
        for row in rows:
            mid = int(row["id"])
            if mid in exclude:
                # Live pending/failed pins stay held so drop can make a later
                # release eligible. Durable descendants and caller-explicit
                # exclusions park permanently.
                if mid in explicit_exclude or protection.get(mid, False):
                    self.chat_messages.set_knowledge_status(mid, "withheld")
                continue
            minister = str(row["minister_name"] or "").strip()
            content = str(row["content"] or "")
            origin_turn = int(row["turn"] or state.turn)
            if not minister:
                # N2: empty minister_name cannot be projected; park as withheld
                # so the row does not remain stuck in held forever.
                self.chat_messages.set_knowledge_status(mid, "withheld")
                continue
            self._project_audience_chat_message(
                state, message_id=mid, minister_name=minister, content=content,
                origin_turn=origin_turn, commit=False,
            )
            released += 1
        if commit:
            self.conn.commit()
        return released

    def register_character_knowledge_source(
        self, state: GameState, participant_roster: Iterable[Mapping[str, object]],
        kind: str, title: str, body: str = "", source_id: str = "",
        excluded_names: Optional[Iterable[str]] = None,
        excluded_targets: Optional[Mapping[str, Iterable[str]]] = None,
        *, commit: bool = True,
    ) -> None:
        # #883 single rejection seam: secret orders and derivatives must not
        # enter the shared knowledge ledger.  Disclosure uses
        # ``secret_order_disclosure:`` (does not start with ``secret_order:``)
        # and remains the only publicization path.
        from ming_sim.materials import is_secret_order_origin

        source_id = str(source_id or "")
        kind_text = str(kind or "")
        if kind_text == "secret_order" or is_secret_order_origin(source_id):
            raise ValueError(
                "密令不得写入共享知识源；只允许本体表 + 接令者专用简报表（#883）"
            )
        roster = [
            dict(item) for item in participant_roster
            if item.get("character_id") or item.get("name")
        ]
        self.character_knowledge.register_source(
            turn=state.turn, year=state.year, period=state.period, kind=kind,
            title=title, body=body, source_id=source_id,
            participant_roster=roster, excluded_names=excluded_names,
            excluded_targets=excluded_targets, commit=commit,
        )

    def _has_restricted_source_gate(self, has_shared_exclusions: bool) -> bool:
        """Whether public-archive writers must use source-scoped aggregation only.

        Callers pass their local shared-exclusion predicate (item exclusions or
        non-audience restricted kinds).  Active secret-order briefs are private
        structure (#883) and do **not** by themselves poison pure public
        aggregates (F3).
        """
        return bool(has_shared_exclusions)

    def upsert_secret_order_brief(
        self, state: GameState, order_id: int, minister_name: str, title: str, body: str,
        *, origin_minister_name: Optional[str] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        commit: bool = True,
    ) -> None:
        """Write the assignee-only secret-order brief (#883 isolation seam).

        #976 classification (message-level provenance):
        1. Persist exact oral-decree ``origin_chat_message_ids`` on the brief.
        2. Withhold those message ids only (not (assignee, role=user) bulk).
        3. Scoped release: only pure-public held rows of the assignee and the
           origin audience speaker — **never** global unfiltered release that
           would project another minister's still-unclassified secret oral line
           into the shared ledger (disease root 1).
        """
        pins = self._coerce_positive_message_ids(origin_chat_message_ids)
        # Keep earlier oral provenance when a later approval/update names another pin.
        pins = list(dict.fromkeys([*self._brief_origin_chat_message_ids(int(order_id)), *pins]))
        pins_json = safe_json_dumps(pins, ensure_ascii=False)
        self.character_knowledge.upsert_secret_brief(
            order_id=int(order_id), turn=state.turn, year=state.year, period=state.period,
            minister_name=minister_name, title=title, body=body, origin_chat_message_ids=pins_json,
        )
        # Message-level withhold: exact ids only (speaker or assignee owned).
        self._withhold_origin_chat_messages(pins, commit=False)
        assignee = str(minister_name or "").strip()
        origin = str(origin_minister_name or "").strip()
        # Scoped release — only ministers touched by this classification.
        # Other ministers' held rows stay held until their own classify/settle.
        self.release_held_audience_knowledge(
            minister_names=[n for n in (assignee, origin) if n],
            exclude_message_ids=pins,
            commit=False,
        )
        if commit:
            self.conn.commit()

    def record_character_participation(self, state: GameState, participants: Iterable[str], kind: str, title: str, body: str = "", source_id: str = "", excluded_names: Optional[Iterable[str]] = None, *, commit: bool = True) -> None:
        from ming_sim.materials import is_secret_order_origin

        kind_text = str(kind or "")
        source_text = str(source_id or "")
        # #883: secret_order shape never becomes a participation event.
        if kind_text == "secret_order" or is_secret_order_origin(source_text):
            return
        self.character_knowledge.record_participation(
            turn=state.turn, year=state.year, period=state.period,
            participants=participants, kind=kind, title=title, body=body,
            source_id=source_id, excluded_names=excluded_names, commit=commit,
        )

    def record_public_knowledge_event(
        self,
        state: GameState,
        title: str,
        body: str = "",
        source_id: str = "",
        excluded_names: Optional[Iterable[str]] = None,
        kind: str = "public",
        *,
        commit: bool = True,
    ) -> None:
        source_id = source_id or f"public:{state.turn}:{title}"
        inherited = self.knowledge_exclusions_for_source(source_id)
        merged_exclusions = list(dict.fromkeys(
            [*inherited, *(str(name).strip() for name in (excluded_names or []) if str(name).strip())]
        ))
        self.character_knowledge.record_public_event(
            turn=state.turn, year=state.year, period=state.period, title=title,
            body=body, source_id=source_id, excluded_names=merged_exclusions,
            kind=kind, commit=commit,
        )

    def get_character_knowledge(self, state: GameState, character_name: str) -> Dict[str, object]:
        from ming_sim.knowledge import build_character_knowledge
        return build_character_knowledge(self, state, character_name)

    def list_recommendation_candidates(self, state: GameState, recommender: str) -> List[Dict[str, object]]:
        from ming_sim.recommendations import list_recommendation_candidates
        return list_recommendation_candidates(self, state, recommender)

    def record_recommendation(
        self, state: GameState, recommender: str, candidate: Dict[str, object],
        target_office: str, reason: str = "",
    ) -> int:
        from ming_sim.recommendations import record_recommendation
        event_id = record_recommendation(self, state, recommender, candidate, target_office, reason)
        if not bool(getattr(self.conn, "_commit_suspended", False)) and int(
            getattr(self.conn, "_atomic_depth", 0) or 0
        ) <= 0:
            self.conn.commit()
        return event_id

    def list_recommendation_events(
        self, state: GameState, recommender: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        from ming_sim.recommendations import list_recommendation_events
        return list_recommendation_events(self, state, recommender)

    def create_secret_order(
        self,
        state: GameState,
        minister_name: str,
        title: str,
        content: str,
        tags: List[str],
        importance: int = 4,
        deadline_months: int = 0,
        excluded_names: Optional[Iterable[str]] = None,
        excluded_offices: Optional[Iterable[str]] = None,
        origin_minister_name: Optional[str] = None,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        pending_action_id: int = 0,
        covert_task: Optional[Mapping[str, object]] = None,
    ) -> int:
        # 宗藩/外藩 非朝堂命官，不可受密令——密令创建的唯一 DB 写口，集中守此一处即覆盖
        # API / 大臣工具 / CLI 自然语言 / upsert 回落 create 全路（cmr R6 cross-section）。
        # 先经 _find_existing_minister 把别名（如「福王」）解到规范 key，再校资格、并以规范名落库——
        # 否则别名绕过资格闸（codex+CodeRabbit R2 concur），且按别名存会让后续按规范名查不到此令
        # （CodeRabbit R3 Major）。lazy import 避 db↔session 循环。
        if self.content is not None:
            from ming_sim.session import _find_existing_minister
            minister_name = _find_existing_minister(self.content, minister_name, self) or minister_name
            # 资格闸：known 在册者（按规范 key / 确切名 / 别名匹配）若是宗藩或外藩，不可受密令。
            # _find_existing_minister 只解 ming 在册者，解不到时须分辨「自由名/临时人(放行)」与
            # 「known-but-ineligible(皇太极等外藩/宗藩) raw 名绕闸」——后者按名/别名兜回显式拒，
            # 否则 `or 原名` 回退把不合资格者写进 secret_orders、重开本闸要堵的旁路（#125；CodeRabbit PR#130 R1 Major）。
            _raw = (minister_name or "").strip()
            _ch = self.content.characters.get(minister_name) or next(
                (c for c in self.content.characters.values()
                 if _raw == c.name or _raw in (c.aliases or [])),
                None,
            )
            if _ch is not None and is_vassal_prince(_ch):
                raise ValueError(f"{_ch.name}为就藩宗室，非朝廷命官，不可受密令。")
            if _ch is not None and self.resolve_power_id(_ch) != "ming":
                raise ValueError(f"{_ch.name}不属大明朝廷，不可受密令。")
        provenance_message_ids = self._coerce_positive_message_ids([
            *([] if origin_chat_message_id is None else [origin_chat_message_id]),
            *(origin_chat_message_ids or []),
        ])
        from ming_sim.covert_progress import (
            CONTRACT_KEY,
            build_covert_task_contract,
            find_active_investigation_order_id,
            merge_investigation_confirmation,
            _investigation_target_of,
        )
        covert_contract = build_covert_task_contract(covert_task=covert_task)
        inv_target = _investigation_target_of(covert_contract or {})
        if inv_target:
            existing_oid = find_active_investigation_order_id(self, inv_target)
            if existing_oid:
                return merge_investigation_confirmation(
                    self,
                    state,
                    existing_oid,
                    pending_action_id=int(pending_action_id or 0),
                    origin_chat_message_ids=provenance_message_ids,
                    commit=True,
                )
        active_count = CharacterKnowledgeStore(self.conn).read_create_secret_order()[0]
        if active_count >= 20:
            raise ValueError(f"进行中密令已达上限（20条），请先结案部分密令再下新令。当前：{active_count} 条。")
        raw_excluded_names, excluded_offices = canonical_secret_order_exclusions(
            self.content, excluded_names or [], excluded_offices or [], f"{title}\n{content}",
        )
        # Institution-level secrecy is resolved at issuance.  The current
        # office/type is only a lookup key; retaining the matched people makes
        # the blacklist stable when someone is transferred or the order later
        # becomes public.  Keep the original institution targets as provenance.
        snapshot_excluded_names = _snapshot_secret_order_people(
            self.content, raw_excluded_names, excluded_offices,
        )
        # ``excluded_targets.people`` is the caller's explicit person target;
        # the expanded institution snapshot lives in ``excluded_names`` so it
        # remains effective after transfers without changing target provenance.
        exclusion_targets_payload = _secret_order_exclusion_targets(
            raw_excluded_names, excluded_offices,
        )
        tags_json = json.dumps(tags, ensure_ascii=False)
        deadline = max(0, min(int(deadline_months or 0), 36))
        due_turn = int(state.turn) + deadline if deadline else 0
        source_chat_turn_id = 0
        if provenance_message_ids:
            placeholders = ",".join("?" for _ in provenance_message_ids)
            source_row = self.conn.execute(
                f"""
                SELECT id FROM chat_turns
                WHERE user_message_id IN ({placeholders})
                   OR minister_message_id IN ({placeholders})
                ORDER BY id DESC LIMIT 1
                """,
                [*provenance_message_ids, *provenance_message_ids],
            ).fetchone()
            if source_row is not None:
                source_chat_turn_id = int(source_row["id"])
        with atomic(self):
            cur = CharacterKnowledgeStore(self.conn).write_create_secret_order((state.turn, due_turn, deadline, state.year, state.period, minister_name, title, content, tags_json, importance,
                 json.dumps(snapshot_excluded_names, ensure_ascii=False),
                 json.dumps(exclusion_targets_payload, ensure_ascii=False)))
            order_id = int(cur.lastrowid)
            # Classification event and dossier identity share the issuance transaction.
            self._classify_secret_order_audience(
                state, order_id, minister_name, title, content,
                origin_minister_name=origin_minister_name,
                origin_chat_message_id=origin_chat_message_id,
                origin_chat_message_ids=origin_chat_message_ids,
                commit=False,
            )
            # #1504 Owner A：确认闸一次冻结 typed covert-task contract（动作轴/可数交付）。
            # 不解析 title/content/tags；轴与交付单位来自 #1376 候选显式字段。
            payload = {
                "title": title,
                "content": content,
                "tags": list(tags),
                "importance": int(importance),
                "excluded_names": list(raw_excluded_names),
                "excluded_offices": list(excluded_offices),
            }
            payload[CONTRACT_KEY] = covert_contract
            from ming_sim.covert_progress import (
                live_investigation_fact_keys,
                FACT_LANES_KEY,
            )
            if inv_target:
                payload[FACT_LANES_KEY] = [
                    {"fact_key": key, "progress": 0.0, "used": False}
                    for key in live_investigation_fact_keys(self, inv_target)
                ]
            dossier_id = self.create_decree_dossier(
                state,
                action_type="secret_order",
                decree_text=content,
                target_kind="secret_order",
                target_id=order_id,
                executor_kind="character",
                executor_id=minister_name,
                source_chat_turn_id=source_chat_turn_id,
                pending_action_id=int(pending_action_id or 0),
                secret_order_id=order_id,
                payload=payload,
                status="promulgated",
                due_turn=due_turn,
                commit=False,
                _issued_secret_order=True,
            )
            self.dossiers.set_promulgation(
                int(dossier_id), status="promulgated", promulgation="promulgated",
                rescript_pending=0, blocked_layer="palace_rescript",
                reason="内批自动顺颁", legal_reason_code="", held_turn=0,
                turn=int(state.turn),
            )
            self.dossiers.insert_decision(
                int(dossier_id), int(state.turn), decision="promulgated",
                blocked_layer="palace_rescript", rescript_action="",
                reason="内批自动顺颁", legal_reason_code="",
                primary_opponents_json="[]", gatekeeper_id=None,
                criteria_snapshot_json="{}",
            )
        tlog(f"[secret_order] create id={order_id} minister={minister_name} title={title[:20]}")
        return order_id

    def upsert_secret_order(
        self,
        state: GameState,
        minister_name: str,
        title: str,
        content: str,
        tags: List[str],
        importance: int = 4,
        deadline_months: int = 0,
        covert_task: Optional[Mapping[str, object]] = None,
    ) -> Tuple[int, bool]:
        """同一承办大臣已有 active 密令 → 更新其要旨(title/content/tags/限期)并记一条
        「奉旨更新」进展；否则新建。返回 (order_id, was_update)。
        补 CLI 后端无 function-calling 的缺口：原靠大臣 function-call 改密令，现失效；
        再次下密令给同一承办人即更新已有条，而非建重复（限期=0 表示不动原限期）。"""
        existing = CharacterKnowledgeStore(self.conn).read_upsert_secret_order((minister_name,))
        if existing is None:
            oid = self.create_secret_order(
                state, minister_name, title, content, tags, importance, deadline_months,
                covert_task=covert_task,
            )
            return oid, False
        oid = int(existing["id"])
        self.update_secret_order_by_id(state, oid, title, content, tags, deadline_months)
        return oid, True

    def update_secret_order_by_id(
        self,
        state: GameState,
        order_id: int,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        deadline_months: int = 0,
        *,
        origin_minister_name: Optional[str] = None,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
    ) -> bool:
        """按**精确 id** 更新 active 密令要旨（title/content/tags/限期），记一条「奉旨更新」进展。
        返回是否更新（id 存在且状态为 active）。

        与 upsert_secret_order 的区别：upsert 按「该大臣最新 active」改，会话动作「更新」已解析出
        确切 target id 时必须走本方法，否则大臣有多条 active 密令会改错条（CMR F1）。
        tags=None 保留原标签（会话更新不带 tags 时不清空）；传 list 则覆盖。

        Oral-decree pins (stage ``origin_chat_message_id`` / speaker) feed the same
        classification seam as create so non-create audience updates withhold口谕.
        When no pin intent is provided, preserve brief pins (do not auto-capture
        pure-public held as new secret-origin bloodline).
        """
        row = CharacterKnowledgeStore(self.conn).read_update_secret_order_by_id((int(order_id),))
        if row is None or row["status"] != "active":
            return False
        persisted_title = title
        tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else (row["tags"] or "[]")
        deadline = max(0, min(int(deadline_months or 0), 36))
        prior_targets = load_stored_object(row["excluded_targets"], label='excluded_targets')
        if not isinstance(prior_targets, dict):
            raise ValueError("excluded_targets 不是对象")
        legacy_people = load_stored_list(row["excluded_names"], label='excluded_names')
        if not isinstance(legacy_people, list):
            raise ValueError("excluded_names 不是名单")
        people, offices = canonical_secret_order_exclusions(
            self.content, [*legacy_people, *prior_targets.get("people", [])],
            prior_targets.get("offices", []),
            f"{title}\n{content}",
        )
        excluded_names = _snapshot_secret_order_people(self.content, people, offices)
        excluded_targets = _secret_order_exclusion_targets(people, offices)
        # Preserve create-time oral pins when caller did not name a new pin.
        classify_ids = origin_chat_message_ids
        if origin_chat_message_id is None and classify_ids is None:
            classify_ids = self._brief_origin_chat_message_ids(int(order_id))
        with atomic(self):
            if deadline:
                CharacterKnowledgeStore(self.conn).write_update_secret_order_by_id((persisted_title, content, tags_json, int(state.turn) + deadline, deadline,
                     json.dumps(excluded_names, ensure_ascii=False), json.dumps(excluded_targets, ensure_ascii=False), int(order_id)))
            else:
                CharacterKnowledgeStore(self.conn).write_update_secret_order_by_id_secret_orders((persisted_title, content, tags_json, json.dumps(excluded_names, ensure_ascii=False),
                     json.dumps(excluded_targets, ensure_ascii=False), int(order_id)))
            self._classify_secret_order_audience(
                state, int(order_id), str(row["minister_name"]), persisted_title, content,
                origin_minister_name=origin_minister_name,
                origin_chat_message_id=origin_chat_message_id,
                origin_chat_message_ids=classify_ids,
                commit=False,
            )
            dossier = self.dossiers.get_for_secret_order(int(order_id))
            if dossier is not None:
                payload = load_stored_object(dossier.get("payload_json"), label="stored JSON")
                if not isinstance(payload, dict):
                    raise ValueError("案卷 payload_json 不是对象")
                payload["title"] = persisted_title
                payload["content"] = content
                payload["tags"] = load_stored_list(tags_json, label="tags")
                self.dossiers.update_payload(int(dossier["id"]), payload, commit=False)
        tlog(f"[secret_order] update id={order_id} title={title[:20]}")
        self.update_secret_order_progress(int(order_id), f"奉旨更新密令要旨：{content}", state.year, state.period)
        return True

    def list_secret_orders(
        self,
        status: Optional[str] = None,
        minister_name: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        rows = self.character_knowledge.secret_order_rows(status, minister_name)
        return [
            {
                "id": int(r["id"]),
                "turn_issued": int(r["turn_issued"]),
                "due_turn": int(r["due_turn"] if "due_turn" in r.keys() else 0),
                "deadline_span": int(r["deadline_span"] if "deadline_span" in r.keys() else 0),
                "year_issued": int(r["year_issued"]),
                "period_issued": int(r["period_issued"]),
                "minister_name": r["minister_name"],
                "title": r["title"],
                "content": r["content"],
                "tags": load_stored_list(r["tags"], label='tags'),
                "importance": int(r["importance"]),
                "status": r["status"],
                "result": r["result"] or "",
                "sim_note": (r["sim_note"] if "sim_note" in r.keys() else "") or "",
                # Emperor-facing secret-order payload is an authorized private
                # product seam; expose the same canonical monthly rail used by
                # the personnel extractor and future dossier inquiry.
                "dossier_progress": (
                    self.list_dossier_progress(int(dossier["id"]))
                    if (dossier := self.dossiers.get_for_secret_order(int(r["id"])))
                    else []
                ),
                "excluded_names": load_stored_list(r["excluded_names"], label='excluded_names') if "excluded_names" in r.keys() else [],
                "excluded_targets": load_stored_object(r["excluded_targets"], label='excluded_targets') if "excluded_targets" in r.keys() else {},
                "turn_closed": r["turn_closed"],
            }
            for r in rows
        ]

    def get_active_secret_orders_for_minister(self, minister_name: str) -> List[Dict[str, object]]:
        """返回该大臣名下未结案密令（active）。done/failed 已结案不再返回。"""
        return self.list_secret_orders(status="active", minister_name=minister_name)

    def close_secret_order(
        self,
        order_id: int,
        status: str,
        result: str,
        turn_closed: int,
        *,
        commit: bool = True,
    ) -> None:
        owns = self.owns_transaction()

        def close_in_current_transaction() -> None:
            dossier = self.dossiers.get_for_secret_order(int(order_id))
            reports = (
                self.list_dossier_progress(int(dossier["id"]))
                if dossier is not None else []
            )
            has_progress_chain = bool(reports)
            close_text = str(result or "")
            CharacterKnowledgeStore(self.conn).write_close_in_current_transaction((status, close_text, turn_closed, int(order_id)))
            if dossier is not None and dossier["status"] != "closed":
                if dossier["status"] == "promulgated":
                    self.dossiers.transition(
                        int(dossier["id"]), "executing", commit=False,
                    )
                # 仅当结案正文是新增玩家叙事时追加终奏；不复写/复制既有 0058 奏报（P7）
                if has_progress_chain and close_text.strip():
                    last_memorial = ""
                    for item in reversed(reports):
                        text = str(item.get("memorial_text") or "").strip()
                        if text:
                            last_memorial = text
                            break
                    if close_text.strip() != last_memorial:
                        self.record_dossier_progress(
                            int(dossier["id"]), int(turn_closed), "结案",
                            close_text, is_terminal=True, commit=False,
                        )
                self.record_dossier_execution(
                    int(dossier["id"]),
                    "fulfilled" if str(status) == "done" else "failed",
                    close_text, int(turn_closed),
                    close=True, commit=False,
                )

        if not owns:
            savepoint = "close_secret_order_axes"
            self.conn.execute(f"SAVEPOINT {savepoint}")
            try:
                close_in_current_transaction()
            except BaseException:
                self.conn.execute(f"ROLLBACK TO {savepoint}")
                self.conn.execute(f"RELEASE {savepoint}")
                raise
            else:
                self.conn.execute(f"RELEASE {savepoint}")
        elif commit:
            with atomic(self):
                close_in_current_transaction()
        else:
            self.conn.execute("BEGIN")
            try:
                close_in_current_transaction()
            except BaseException:
                self.conn.rollback()
                raise
        tlog(f"[secret_order] close id={order_id} status={status}")

    def submit_secret_order_for_review(self, order_id: int, claim: str, year: int, period: int) -> bool:
        """#1504：大臣自认办结 → 缩 due_turn 至当月，月末机械对账。

        claim 按月戳追加进 result（奏报/陈词轨），不入实况对账真源。仅 active 可提交。
        """
        row = CharacterKnowledgeStore(self.conn).read_submit_secret_order_for_review((int(order_id),))
        if not row or row["status"] != "active":
            return False
        turn_row = ReignStateStore(self.conn).read_record_dossier_decision()
        current_turn = int(turn_row["turn"]) if turn_row is not None else int(row["turn_issued"] or 0)
        stamp = f"〔{period_label(year, period)}〕[提交核议] "
        note = (claim or "").strip()
        prev = CharacterKnowledgeStore(self.conn).read_submit_secret_order_for_review_result((int(order_id),))["result"] or ""
        lines = [ln for ln in prev.split("\n") if ln.strip()]
        lines.append(f"{stamp}{note}")
        with atomic(self):
            CharacterKnowledgeStore(self.conn).write_submit_secret_order_for_review((current_turn, "\n".join(lines), int(order_id)))
            self.mark_secret_order_in_progress(int(order_id), commit=False)
        tlog(f"[secret_order] submit_for_review id={order_id} due_now claim={note[:60]!r}")
        return True

    def _has_secret_order_period_line(self, order_id: int, column: str, year: int, period: int) -> bool:
        """本年月该列是否已有一行（用于一回合一步闸门）。"""
        stamp = f"〔{period_label(year, period)}〕"
        row = self.character_knowledge.secret_period_line(int(order_id), column)
        if row is None:
            return False
        return any(ln.startswith(stamp) for ln in str(row["v"] or "").split("\n"))

    def _append_secret_order_line(
        self, order_id: int, column: str, note: str, year: int, period: int,
        reject_if_same_period: bool = False,
        commit: bool = True,
    ) -> bool:
        """把一条带年月戳的进展/副作用追加进密令的 result/sim_note，存成历史时间线。
        reject_if_same_period=True 时，本年月已有行则拒写（返回 False，用于一回合一步）；
        否则同年月再写替换当月行。不同年月一律新增。返回是否实际写入。"""
        assert column in ("result", "sim_note")
        stamp = f"〔{period_label(year, period)}〕"
        row = self.character_knowledge.secret_period_line(int(order_id), column, active_only=True)
        if row is None:
            return False  # 已结案或不存在，不追加
        lines = [ln for ln in str(row["v"] or "").split("\n") if ln.strip()]
        if reject_if_same_period and any(ln.startswith(stamp) for ln in lines):
            return False  # 本回合已推过一步，拒
        lines = [ln for ln in lines if not ln.startswith(stamp)]  # 去掉当月旧行
        lines.append(f"{stamp}{note.strip()}")
        # 按〔年月〕戳排序，保证时间线顺序（同月替换后不致错位）
        def _stamp_key(ln: str):
            import re as _re
            m = _re.match(r"〔(\d+)年(\d+)月〕", ln)
            return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        lines.sort(key=_stamp_key)
        self.character_knowledge.set_secret_period_line(int(order_id), column, "\n".join(lines))
        if commit:
            self.conn.commit()
        return True

    def update_secret_order_progress(
        self,
        order_id: int,
        progress_note: str,
        year: int = 0,
        period: int = 0,
        *,
        commit: bool = True,
    ) -> bool:
        """承办人推进一步：按年月追加进 result 历史时间线，不改 status。
        同月再报则替换当月行（修改最新进度，不叠加多条）。"""
        with atomic(self):
            ok = self._append_secret_order_line(
                order_id,
                "result",
                progress_note,
                year,
                period,
                reject_if_same_period=False,
                commit=False,
            )
            if ok:
                self.mark_secret_order_in_progress(order_id, commit=False)
        tlog(f"[secret_order] progress id={order_id} ok={ok} note={progress_note[:40]!r}")
        return ok

    def update_secret_order_sim_note(
        self,
        order_id: int,
        sim_note: str,
        year: int = 0,
        period: int = 0,
        *,
        commit: bool = True,
    ) -> None:
        """推演写密令副作用（泄漏/反弹等），按年月追加进 sim_note 历史时间线，
        不动 result/status。同月再写替换（推演每月一次）。与承办人进展分列。"""
        if commit:
            with atomic(self):
                self._update_secret_order_sim_note_in_transaction(
                    order_id, sim_note, year, period,
                )
        else:
            self._update_secret_order_sim_note_in_transaction(
                order_id, sim_note, year, period,
            )
        tlog(f"[secret_order] sim_note id={order_id} note={sim_note[:40]!r}")

    def _update_secret_order_sim_note_in_transaction(
        self, order_id: int, sim_note: str, year: int, period: int,
    ) -> None:
        """调用方持有事务时写密令实况并同步案卷，不自行落定。"""
        self._append_secret_order_line(
            order_id, "sim_note", sim_note, year, period, commit=False,
        )
        self.mark_secret_order_in_progress(order_id, commit=False)

    def mark_secret_order_in_progress(
        self, order_id: int, *, commit: bool = True,
    ) -> None:
        """任何首次实际办理入口共用：密令轴在办时，案卷轴幂等进入 executing。"""
        owns = self.owns_transaction()
        dossier = self.dossiers.get_for_secret_order(order_id)
        if dossier is None:
            raise ValueError("密令进展缺少对应案卷")
        if dossier["status"] == "promulgated":
            self.dossiers.transition(
                int(dossier["id"]), "executing", commit=False,
            )
        elif dossier["status"] != "executing":
            raise ValueError("在办密令的案卷不处于可执行状态")
        self._commit_dossier_write(commit, owns)

    def rush_secret_order(
        self,
        order_id: int,
        state: GameState,
        deadline_months: int = 1,
        reason: str = "",
    ) -> Dict[str, object]:
        """缩短 active 密令期限。deadline_months<=0 表示本月到期对账。"""
        row = CharacterKnowledgeStore(self.conn).read_rush_secret_order((int(order_id),))
        if row is None:
            raise ValueError("密令不存在")
        if row["status"] != "active":
            raise ValueError(f"当前状态 {row['status']}，不能催办")
        try:
            months = max(0, min(int(deadline_months or 0), 36))
        except (TypeError, ValueError):
            months = 1
        target_turn = int(state.turn) + months
        old_due = int(row["due_turn"] or 0)
        stamp = f"〔{period_label(state.year, state.period)}〕"
        why = reason if str(reason or "").strip() else "奉旨加急"
        prev = row["result"] or ""
        lines = [ln for ln in prev.split("\n") if ln.strip()]
        with atomic(self):
            if months <= 0:
                lines.append(f"{stamp}[奉旨即核] {why}；本月到期按实进度对账。")
                CharacterKnowledgeStore(self.conn).write_rush_secret_order((int(state.turn), "\n".join(lines), int(order_id)))
                status = "active"
                due_turn = int(state.turn)
            else:
                due_turn = target_turn if old_due <= 0 else min(old_due, target_turn)
                lines.append(f"{stamp}[奉旨加急] {why}；御限改为 {months} 个月内核议。")
                CharacterKnowledgeStore(self.conn).write_rush_secret_order_secret_orders((
                        due_turn,
                        max(int(due_turn) - int(state.turn), 0),
                        "\n".join(lines),
                        int(order_id),
                    ))
                status = "active"
            self.mark_secret_order_in_progress(int(order_id), commit=False)
        tlog(f"[secret_order] rush id={order_id} old_due={old_due} due={due_turn} status={status}")
        return {"id": int(order_id), "title": row["title"], "status": status, "due_turn": due_turn}

    def get_secret_order(self, order_id: int) -> Optional[Dict[str, object]]:
        """单查一条密令（任意状态），给承办人查进度工具用。不存在返回 None。"""
        r = CharacterKnowledgeStore(self.conn).read_get_secret_order((int(order_id),))
        if not r:
            return None
        return {
            "id": int(r["id"]), "minister_name": r["minister_name"],
            "title": r["title"], "content": r["content"],
            "status": r["status"], "result": r["result"] or "",
            "sim_note": (r["sim_note"] if "sim_note" in r.keys() else "") or "",
            "turn_issued": int(r["turn_issued"]),
            "due_turn": int(r["due_turn"] if "due_turn" in r.keys() else 0),
            "turn_closed": r["turn_closed"],
        }

    def auto_submit_due_secret_orders(self, state: GameState) -> List[Dict[str, object]]:
        """#1504：到期只记 typed 机器事实，保持 active；玩家文字走 0058 密奏。"""

        rows = CharacterKnowledgeStore(self.conn).read_auto_submit_due_secret_orders((int(state.turn),))
        submitted: List[Dict[str, object]] = []
        with atomic(self):
            for row in rows:
                oid = int(row["id"])
                self.mark_secret_order_in_progress(oid, commit=False)
                submitted.append({
                    "id": oid,
                    "title": row["title"],
                    "status": "active",
                })
        if rows:
            tlog(
                f"[secret_order] due_typed count={len(submitted)} "
                f"ids={[x['id'] for x in submitted]} (status unchanged)"
            )
        return submitted

    # ── 调试用通用 CRUD（仅限白名单核心表）──────────────────────
    # 表名 → 主键列。只暴露核心几张，防误删元数据/日志表。
    ADMIN_TABLES: Dict[str, str] = {
        "game_state": "id",        # 局势
        "metrics": "key",          # 国家修正（国库/内库/民心/皇威）
        "regions": "id",           # 地区
        "armies": "id",            # 军队
        "characters": "name",      # 人物
        "buildings": "id",         # 建筑
    }

    def admin_check_table(self, table: str) -> str:
        pk = self.ADMIN_TABLES.get(table)
        if pk is None:
            raise ValueError(f"表 {table!r} 不在调试白名单")
        return pk

    def admin_columns(self, table: str) -> List[Dict[str, object]]:
        """PRAGMA 取列定义：name/type/notnull/pk/default。"""
        self.admin_check_table(table)
        cur = self.conn.execute(f"PRAGMA table_info({table})")
        return [
            {
                "name": r["name"],
                "type": r["type"],
                "notnull": bool(r["notnull"]),
                "pk": bool(r["pk"]),
                "default": r["dflt_value"],
            }
            for r in cur.fetchall()
        ]

    def admin_rows(self, table: str) -> List[Dict[str, object]]:
        pk = self.admin_check_table(table)
        readers = {
            "game_state": self.reign.header_rows,
            "metrics": self.reign.metric_rows,
            "regions": self.regions.rows,
            "armies": self.armies.read_army_rows,
            "characters": lambda: self.characters.snapshot_rows("characters"),
            "buildings": self.buildings.read_buildings_report_,
        }
        return [dict(row) for row in sorted(readers[table](), key=lambda row: row[pk])]

    def _admin_valid_cols(self, table: str) -> set:
        return {c["name"] for c in self.admin_columns(table)}

    def admin_upsert(self, table: str, values: Dict[str, object]) -> Dict[str, object]:
        """按主键原位 upsert，返回落库后的行。只接受表内有的列。"""
        pk = self.admin_check_table(table)
        valid = self._admin_valid_cols(table)
        data = {k: v for k, v in values.items() if k in valid}
        if pk not in data or data[pk] in (None, ""):
            raise ValueError(f"缺主键 {pk}")
        if table == "game_state":
            self.reign.upsert_header(data)
            read_row = self.reign.header_row
        elif table == "metrics":
            self.reign.upsert_metric(str(data["key"]), int(data["value"]))
            read_row = self.reign.metric_row
        elif table == "regions":
            self.regions.upsert(data)
            read_row = self.regions.row
        elif table == "armies":
            self.armies.upsert(data)
            read_row = self.armies.row
        elif table == "characters":
            self.characters.upsert(data)
            read_row = self.characters.row
        elif table == "buildings":
            self.buildings.upsert(data)
            read_row = self.buildings.get
        else:
            raise ValueError(f"表 {table!r} 不在调试白名单")
        # #1889：economy_accounts 已降级为 metrics 的派生视图，无需（也不能）再同步；
        # 改 metrics 即改真源。
        self.conn.commit()
        row = read_row(data[pk])
        return dict(row) if row else {}

    def admin_delete(self, table: str, pk_value: object) -> int:
        """按主键删行，返回受影响行数。"""
        pk = self.admin_check_table(table)
        if table == "game_state":
            deleted = self.reign.delete_header(pk_value)
        elif table == "metrics":
            deleted = self.reign.delete_metric(str(pk_value))
        elif table == "regions":
            deleted = self.regions.delete(str(pk_value))
        elif table == "armies":
            deleted = self.armies.delete(str(pk_value))
        elif table == "characters":
            deleted = self.characters.delete_by_name(str(pk_value))
        elif table == "buildings":
            deleted = self.buildings.delete(str(pk_value))
        else:
            raise ValueError(f"表 {table!r} 不在调试白名单")
        self.conn.commit()
        return deleted

    def record_relation_edge_event(
        self,
        *,
        source: str,
        target: str,
        event_kind: str,
        context: str,
        origin: str,
        turn: Optional[int] = None,
        year: Optional[int] = None,
        period: Optional[int] = None,
        evidence: Any = False,
    ) -> int:
        """唯一的边事件写入口；重复同一事件返回原 id，不生成第二笔。

        事务归属与 set_fiscal_config / withdraw_pending_action 一致：调用方已开
        事务（atomic 内或裸 BEGIN/DML 使 conn.in_transaction 为真）时不提前
        commit。不调 load_state()——其末尾 self.conn.commit() 会把调用方半成品
        落盘、破坏原子性（PR #804 P2）。仅需 turn/year/period 三个默认值，直读
        game_state 行即可。"""
        source = str(source or "").strip()
        target = str(target or "").strip()
        # #633 F1（庭裁 r1）：strip 只作非空谓词，存储值一律原样（含首尾空白与换行）；
        # 禁任何长度 clamp/裁剪/替换/归一——机械验收=全链字节相等。
        # 与 main #635 零改字同向：只以 strip 判空，非 str 立即 ValueError（不 str() 强转）。
        if not isinstance(context, str):
            raise ValueError("边事件语境必须为字符串")
        if not source or not target:
            raise ValueError("边事件 source/target 不能为空")
        if not context.strip():
            raise ValueError("边事件语境不能为空")
        kind = validate_edge_kind(event_kind)
        evidence_flag = normalize_evidence(evidence)
        owns_transaction = self.owns_transaction()
        state_row = ReignStateStore(self.conn).read_record_claim_flow_logs()
        if state_row is not None:
            default_turn, default_year, default_period = (
                int(state_row["turn"]), int(state_row["year"]), int(state_row["period"]),
            )
        else:
            default_turn, default_year, default_period = (
                1, DEFAULT_OPENING_YEAR, DEFAULT_OPENING_PERIOD,
            )
        effective_turn = int(turn if turn is not None else default_turn)
        effective_year = int(year if year is not None else default_year)
        effective_period = int(period if period is not None else default_period)
        bound_origin, origin_round = bind_origin_round(origin, effective_turn)
        PersonLogStore(self.conn).write_record_relation_edge_event((
                source, target, kind, context, bound_origin, origin_round,
                effective_turn, effective_year, effective_period, int(evidence_flag),
            ))
        if owns_transaction:
            self.conn.commit()
        row = PersonLogStore(self.conn).read_record_relation_edge_event((source, target, kind, context, bound_origin))
        return int(row["id"])

    # Names kept as narrow aliases for callers that describe the same seam differently.
    write_relation_edge_event = record_relation_edge_event
    insert_relation_edge_event = record_relation_edge_event

    def get_relation_edge_events(
        self,
        *,
        person: Optional[str] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        event_kind: Optional[str] = None,
        evidence: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if person is not None:
            clauses.append("(source = ? OR target = ?)")
            params.extend([str(person), str(person)])
        if source is not None:
            clauses.append("source = ?")
            params.append(str(source))
        if target is not None:
            clauses.append("target = ?")
            params.append(str(target))
        if event_kind is not None:
            clauses.append("event_kind = ?")
            params.append(validate_edge_kind(event_kind))
        if evidence is not None:
            clauses.append("evidence = ?")
            params.append(int(normalize_evidence(evidence)))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = PersonLogStore(self.conn).read_get_relation_edge_events_owned(params, where).fetchall()
        return [
            {
                **dict(row),
                "evidence": bool(row["evidence"]),
            }
            for row in rows
        ]

    def read_credit_events_as_edges(self, records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """0079 读侧契约适配；只返回边，不把 fixture 写入 0079 或本表。"""
        return credit_events_as_edges(records)

    # ------------------------------------------------------------------
    # #636 关系摘要层 S5：两段式存储＋月末增量重酿腿的持久化接缝。
    # 摘要文本机械原样存取（LLM 自由文本零删改，CLAUDE.md P6/ADR 0142）；
    # 奠基段只增不改、近况段覆盖式幂等由 apply 路机械保证。
    # ------------------------------------------------------------------

    def apply_seed_founding_segment(
        self,
        *,
        source: str,
        target: str,
        dimension: str,
        founding_segment: str,
    ) -> None:
        """#638 S7：seed 可选初始摘要落奠基段（只增不改；近况段/水位不动）。

        与 apply_relation_brew_result 的差异：本写只碰奠基段——近况段留空、
        last_event_id 留 0，seed 边因此仍在水位之上，该对首次真实月末酿制照常
        收取 seed 边作输入语境（ADR 0086 同一套酿制，不另立第二套腿）。幂等：
        同内容重放由调用方 merge_founding_segment 字节等去重保证字节不变。"""
        if dimension not in ("君臣", "大臣"):
            raise ValueError(f"未知关系维度: {dimension!r}")
        owns = self.owns_transaction()
        PersonLogStore(self.conn).write_apply_seed_founding_segment((str(source), str(target), dimension, str(founding_segment)))
        if owns:
            self.conn.commit()

    def get_relation_summary(self, source: str, target: str) -> Optional[Dict[str, Any]]:
        row = PersonLogStore(self.conn).read_get_relation_summary((str(source), str(target)))
        return dict(row) if row is not None else None

    def get_relation_summaries(self) -> List[Dict[str, Any]]:
        rows = PersonLogStore(self.conn).read_get_relation_summaries()
        return [dict(row) for row in rows]

    def apply_relation_brew_result(
        self,
        *,
        source: str,
        target: str,
        dimension: str,
        founding_segment: str,
        recent_segment: str,
        last_event_id: int,
        turn: int,
        year: int,
        period: int,
    ) -> None:
        """摘要落定＋该关系 pending 清除在同一 DB 事务内原子落定（庭裁 r2 F1）。

        近况段覆盖式幂等（禁半量累积）；奠基段由调用方拼好只增不改的结果传入。
        任意缝失败→整体回滚→pending 保留→下次结算补酿。"""
        if dimension not in ("君臣", "大臣"):
            raise ValueError(f"未知关系维度: {dimension!r}")
        owns = self.owns_transaction()
        try:
            PersonLogStore(self.conn).write_apply_relation_brew_result((
                    str(source), str(target), dimension,
                    str(founding_segment), str(recent_segment),
                    int(last_event_id), int(turn), int(year), int(period),
                ))
            PersonLogStore(self.conn).write_apply_relation_brew_result_relation_brew_pending((str(source), str(target)))
            if owns:
                self.conn.commit()
        except Exception:
            # 故障注入验收缝（庭裁 r3 F1①）：摘要已写、事务未提交即崩→整体回滚，
            # pending 仍在、摘要读回＝崩前旧值。
            if owns:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            raise

    def mark_relation_brew_pending(
        self,
        *,
        source: str,
        target: str,
        year: int,
        period: int,
        reason: str = "",
    ) -> None:
        """酿制失败的月份进持久 pending-backlog（庭裁 r1 F1）；保旧摘要、不阻塞结算。"""
        owns = self.owns_transaction()
        try:
            PersonLogStore(self.conn).write_mark_relation_brew_pending((str(source), str(target), int(year), int(period), str(reason)))
            if owns:
                self.conn.commit()
        except Exception:
            if owns:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            raise

    def claim_relation_brew_targets(self, *, year: int, period: int) -> int:
        """settled 年月入选关系先作 durable claim（庭裁 r2/r3 F1）。

        选中＝该年月新增边事件（id 在摘要水位之上）；已在册的 pending 原样保留
        （不覆盖原失败月份/原因）。事务归属与 mark_relation_brew_pending 一致：
        settle 事务内（atomic_depth>0）不提前 commit，认领与本月边事件同生共死——
        任意缝崩溃→两者一并回滚→重启重放再认领；独立调用则自成一体提交。
        返回本次新认领的关系数。"""
        owns = self.owns_transaction()
        cur = PersonLogStore(self.conn).write_claim_relation_brew_targets((int(year), int(period), int(year), int(period)))
        if owns:
            self.conn.commit()
        return max(int(cur.rowcount or 0), 0)

    def get_relation_brew_pending(self) -> List[Dict[str, Any]]:
        """关系对 pending（#636 语义原样）：只回 item_kind='关系' 的行。"""
        rows = PersonLogStore(self.conn).read_get_relation_brew_pending()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # #637 派系态势摘要 S6：持久化接缝（ADR 0084）。
    # 复用 #636 单一 durable claim/watermark/apply+clear 所有者（庭裁 r1 F2）：
    # pending 走同一 relation_brew_pending 表（item_kind='派系' 身份），apply 与
    # pending 清除同事务原子落定，与 apply_relation_brew_result 同构。
    # ------------------------------------------------------------------

    def get_faction_stance_summaries(self) -> List[Dict[str, Any]]:
        rows = FactionStore(self.conn).read_get_faction_stance_summaries()
        return [dict(row) for row in rows]

    def get_faction_stance_summary(self, faction: str) -> Optional[Dict[str, Any]]:
        row = FactionStore(self.conn).read_get_faction_stance_summary((str(faction),))
        return dict(row) if row is not None else None

    def claim_faction_brew_targets(self, *, year: int, period: int) -> int:
        """settled 年月涉派派系先作 durable claim（庭裁 r1 F2：复用既有认领机制）。

        选中＝canonical 党籍投影命中现存 factions 集合的涉派新事件（庭裁 r1 F1：
        任一端 characters.faction 归一后命中该派；表外党籍不入、不猜映射——投影
        即 JOIN 本身，不持久化任何映射表）。已在册的 pending 原样保留。事务归属与
        claim_relation_brew_targets 一致：settle 事务内不提前 commit，认领与本月
        边事件同生共死；独立调用则自成一体提交。返回本次新认领的派系数。"""
        owns = self.owns_transaction()
        cur = PersonLogStore(self.conn).write_claim_faction_brew_targets((int(year), int(period), int(year), int(period)))
        if owns:
            self.conn.commit()
        return max(int(cur.rowcount or 0), 0)

    def get_faction_brew_pending(self) -> List[Dict[str, Any]]:
        """派系工作项 pending：item_kind='派系' 行，target 即派系名。"""
        rows = PersonLogStore(self.conn).read_get_faction_brew_pending()
        return [
            {
                "faction": row["target"],
                "year": row["year"],
                "period": row["period"],
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def mark_faction_brew_pending(
        self,
        *,
        faction: str,
        year: int,
        period: int,
        reason: str = "",
    ) -> None:
        """派系酿制失败月进持久 pending-backlog（同表同机制，保旧摘要、不阻塞结算）。"""
        owns = self.owns_transaction()
        try:
            PersonLogStore(self.conn).write_mark_faction_brew_pending((str(faction), int(year), int(period), str(reason)))
            if owns:
                self.conn.commit()
        except Exception:
            if owns:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            raise

    def apply_faction_brew_result(
        self,
        *,
        faction: str,
        stance_segment: str,
        last_event_id: int,
        turn: int,
        year: int,
        period: int,
    ) -> None:
        """派系态势摘要落定＋该派 pending 清除在同一 DB 事务内原子落定。

        态势段覆盖式幂等；水位推进到本批最大事件 id。任意缝失败→整体回滚→
        pending 保留→下次结算补酿。唯一写面＝faction_stance_summaries 与
        relation_brew_pending（item_kind='派系'）；绝不触 factions 真源数值列
        （三不碰红线，F3 零写观察面）。"""
        owns = self.owns_transaction()
        try:
            FactionStore(self.conn).write_apply_faction_brew_result((
                    str(faction), str(stance_segment), int(last_event_id),
                    int(turn), int(year), int(period),
                ))
            PersonLogStore(self.conn).write_apply_faction_brew_result((str(faction),))
            if owns:
                self.conn.commit()
        except Exception:
            # 故障注入验收缝（与 apply_relation_brew_result 同构）：摘要已写、
            # 事务未提交即崩→整体回滚，pending 仍在、摘要读回＝崩前旧值。
            if owns:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            raise

    def close(self) -> None:
        self.conn.close()

    def backup_to(self, target_path: str) -> None:
        """SQLite backup API 热备到 target_path。不需关闭主连接。

        atomic() 内禁止调用：backup 走同连接 pager，会把未提交（可能随后回滚）
        的脏页备进文件（cmr S1 F3）。错误包备份必须在 rollback 之后、atomic 外做。
        """
        if getattr(self.conn, "_commit_suspended", False):
            raise RuntimeError(
                "backup_to 在 atomic 事务内禁止：备份会带上未提交脏页。"
                "请先 rollback/commit（退出 atomic）再备份。"
            )
        import os as _os
        _os.makedirs(_os.path.dirname(target_path) or ".", exist_ok=True)
        dest = sqlite3.connect(target_path)
        try:
            self.conn.commit()
            self.conn.backup(dest)
        finally:
            dest.close()
