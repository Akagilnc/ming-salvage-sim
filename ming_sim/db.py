"""GameDB：所有 SQLite 持久化。L3。

init_schema 建表，opening_seed.seed_opening_world 从 GameContent 初始化静态盘面。
GameDB 持有 self.content（GameContent），seed 类方法从中读人物/地区/军队等。
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from ming_sim.applier import (
    atomic,
    connection_owns_transaction,
    item_savepoint_scope,
    ItemAtomicReject,
    coerce_beyond_intent_flag,
    parse_engine_payload_json,
    Provenance,
    RejectedItem,
    safe_json_dumps,
)
from ming_sim.entities.character_knowledge import (
    ensure_schema as ensure_character_knowledge_schema,
)
from ming_sim.entities.person_log import ensure_schema as ensure_person_log_schema
from ming_sim.entities.person_log.store import PersonLogStore
from ming_sim.entities.reign_state import ensure_schema as ensure_reign_schema
from ming_sim.entities.reign_state.store import POPULATION_UNIT_PERSONS as POPULATION_UNIT_PERSONS
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.assets import format_money, format_money_delta, format_wanliang_amount
from ming_sim.constants import (
    ARMY_FIELD_ALIASES, ARMY_FIELD_LABELS, ARMY_QUANTITY_FIELDS, ARMY_SCORE_FIELDS, ARMY_TEXT_FIELDS,
    BUILDING_CATEGORIES, BUILDING_FIELD_LABELS, BUILDING_OUTPUT_METRICS,
    BUILDING_QUANTITY_FIELDS, BUILDING_SCORE_FIELDS, BUILDING_TEXT_FIELDS,
    ECONOMY_ACCOUNTS, GATE_METRIC_KEYS, POWER_FIELD_LABELS, POWER_FIELD_ALIASES, MONEY_UNIT, REGION_FIELD_LABELS, REGION_QUANTITY_FIELDS,
    FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES, REGION_SCORE_FIELDS, REGION_TEXT_FIELDS,
    SALARY_RATE_ANCHOR, TURN_UNIT,
    DEFAULT_OPENING_PERIOD, DEFAULT_OPENING_YEAR,
)
from ming_sim.content import GameContent
from ming_sim.office_rank import normalize_office
from ming_sim.decree_vocabulary import (
    DOSSIER_ACTION_TYPES, DIRECTIVE_ACTION_TYPES, dossier_action_policy,
)
from ming_sim.matching import match_region_id_from_text
from ming_sim.exceptions import (
    DeclarationDataError,
    OfficeAppointmentRejection,
    PendingActionRefusal,
    RevokeOriginUnresolved,
)
from ming_sim.entities.dossier import (
    DossierStore,
    DOSSIER_REPORT_ORIGIN_NS,
    DOSSIER_REPORT_ORIGIN_VERDICT,
    DOSSIER_REPORT_ORIGIN_MONTHLY,
    DOSSIER_REPORT_ORIGIN_REVIEW,
    DOSSIER_REPORT_ORIGIN_RUSH,
    DOSSIER_STATUSES,
    hydrate_dossier_row,
    normalize_dossier_mode,
)
from ming_sim.schema import ensure_core_schema
from ming_sim.models import (
    FRONT_HALF_DONE_PHASES, Character, Event, GameState, is_vassal_prince,
    loads_effect_dict, _load_durable_json_object,
    monthly_amount, period_label, reign_period_label,
)
from ming_sim.participant_roster import (
    PARTICIPANT_TIERS,
    decode_durable_participant_roster,
    participant_roster_names,
    project_execution_liability_parties,
)
from ming_sim.person_archive_contract import (
    PERSON_OUSTED_STATUSES,
    PERSON_STATUSES,
    PERSON_TITLE_KINDS,
)
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
    normalize_evidence,
    validate_edge_kind,
)
from ming_sim.strict_types import (
    strict_sqlite_id, strict_int, validate_affected_parties,
)
from ming_sim.token_stats import tlog

logger = logging.getLogger(__name__)

# 结构化 id 字段入库前归一（trim）；其余 TEXT 字段（灾情/状况/番号等）原值入库。
_STRUCTURED_ID_FIELDS = frozenset({"controlled_by", "station_region", "owner_power"})

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
    `_apply_army_pay_source_delta` / transition_army_owner_power 共用，防再分叉。
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
        crime = str(value.get("crime") or "")
        severity = str(value.get("severity") or "无").strip()
        return safe_json_dumps({"crime": crime, "severity": severity}, ensure_ascii=False)
    return str(value or "")

def _public_support_description(value: object) -> str:
    return "民心" + public_support_band(value)

def _unrest_description(value: object) -> str:
    return "动乱" + qualitative_band(value, ("平静", "有患", "不安", "升高", "已炽"))

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
    value = float(amount or 0)
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
    arr = float(arrears or 0)
    pay = float(monthly_pay or 0)
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
    n = int(value or 0)
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
    from ming_sim.army_pay import derive_army_mutiny_state

    derived = derive_army_mutiny_state(row)
    if derived == "正常":
        loyalty = int(row["loyalty"] or 0)
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


def _has_stop_condition(stop_condition: object) -> bool:
    """True when durable stop_condition object has work.

    Legal empty (None/''/{}) → False. Any non-object root raises.
    Condition DSL lives inside the object values; root is never free text.
    """
    if isinstance(stop_condition, dict):
        return bool(stop_condition)
    if stop_condition is None:
        return False
    raw = str(stop_condition).strip()
    if not raw or raw == "{}":
        return False
    data = _load_durable_json_object(raw, surface="issues.stop_condition")
    return bool(data)

def _optional_positive_dossier_id(raw: object, *, field: str) -> Optional[int]:
    """#658：typed dossier id 单权威——真正缺省→None；一旦出现只接正整数。

    拒 0/负/bool/float/数字字符串/超 SQLite 64-bit。target 与 backing 共吃，
    禁第二份 optional-positive（#1897 C1）。
    """
    if raw in (None, ""):
        return None
    try:
        value = strict_int(raw, accept_numeric_strings=False)
    except (TypeError, ValueError) as exc:
        raise DeclarationDataError(f"{field} 非法 shape：{raw!r}") from exc
    if value <= 0:
        raise DeclarationDataError(f"{field} 非法 shape：{raw!r}")
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

def require_backing_dossier_id(db: object, raw: object) -> Optional[int]:
    """解析 + 存在性：有值则案卷必须在册；供 stage 首写与 apply 复用。

    形状／不存在 → 结构化领域拒收（#1897 E1）；getter 真读故障原样上抛，
    不按 ValueError 文案猜类别。
    """
    from ming_sim.action_materialize import DecreeMaterializationValidationError

    try:
        backing = parse_backing_dossier_id(raw)
    except ValueError as exc:
        raise DecreeMaterializationValidationError(
            str(exc),
            failed_fields=("backing_dossier_id",),
            category="invalid_shape",
        ) from exc
    if backing is None:
        return None
    dossier = db.dossiers.get(backing)  # 读故障不包装
    if dossier is None:
        raise DecreeMaterializationValidationError(
            f"backing_dossier_id 所指案卷不存在：{backing}",
            failed_fields=("backing_dossier_id",),
            category="hallucinated_id",
        )
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
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        raise DecreeMaterializationValidationError(
            "旨意不得同时带普通结构化 triad 与御笔强推 target_dossier_id",
            failed_fields=("target_dossier_id", "target_kind"),
        )
    if has_push:
        return "push"
    if has_triad:
        return "ordinary"
    return "empty"

def directive_payload_admits_structured_write(payload: Mapping[str, object]) -> bool:
    """旨意可落库：普通 triad，或 #658 御笔强推 typed target（互斥）。"""
    return classify_directive_structured_kind(payload) != "empty"

def _coerce_deadline_months(
    raw: object, *, default: int = 0, durable: bool = False,
) -> int:
    """解析密令/催办期限；显式 0 是合法值，不能被缺省兜底吞掉。

    durable=False（声明/准入）：可辨识脏类型走 DecreeMaterializationValidationError
    领域拒收（#1897 C1 / ADR 0015 per-item），不带走同批合法同行。
    durable=True（已持久载荷）：类型/解码腐坏裸 ValueError，事务回滚、pending 保待重试
    （#1897 E1 错误来源分流），不得伪装业务 failed。
    """
    from ming_sim.action_materialize import DecreeMaterializationValidationError

    def _reject(message: str) -> None:
        if durable:
            raise ValueError(f"持久字段 deadline_months：{message}")
        raise DecreeMaterializationValidationError(
            message,
            failed_fields=("deadline_months",),
            category="invalid_shape",
        )

    if raw is None:
        return int(default)
    if isinstance(raw, bool):
        _reject("deadline_months cannot be a boolean")
    if isinstance(raw, str):
        _reject("deadline_months cannot be a string")
    if not isinstance(raw, (int, float)):
        _reject("deadline_months must be a numeric type")
    try:
        deadline = int(raw)
    except (ValueError, OverflowError) as exc:
        if durable:
            raise ValueError(
                "持久字段 deadline_months：deadline_months must be a finite numeric type",
            ) from exc
        raise DecreeMaterializationValidationError(
            str(exc),
            failed_fields=("deadline_months",),
            category="invalid_shape",
        ) from exc
    return max(0, min(deadline, 36))

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
        raise DeclarationDataError("布尔值不是合法比例")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise DeclarationDataError(str(exc)) from exc
    if not math.isfinite(value):
        raise DeclarationDataError("非有限数")
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

def _office_rank_multiplier(office: str, already_normalized: bool = False) -> float:
    """从 office 头衔字串解析品级 multiplier。唯一真源=offices.json rank_rules。

    逗号分隔的多职取已识别分项中的最高档；整串无 leverage 词干时落默认 1.0。
    already_normalized=True 时入参已是 normalize_office 结果，跳过重复 normalize。
    """
    from ming_sim.office_rank import office_leverage_multiplier

    text = office or ""
    normalized = text if already_normalized else normalize_office(text)
    return office_leverage_multiplier(normalized)

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


COURT_OFFICE_TYPES = {"内阁", "吏部", "户部", "礼部", "兵部", "刑部", "工部"}

_OFFICES_TABLE: Optional[Dict[str, object]] = None
_OFFICE_TYPE_LLM_CACHE: Dict[str, str] = {}

def _offices_table() -> Dict[str, object]:
    """加载 content/offices.json（明代职官→office_type 参考表），缓存；加载失败原样交出。"""
    global _OFFICES_TABLE
    if _OFFICES_TABLE is None:
        from ming_sim.assets import load_json_asset
        _OFFICES_TABLE = load_json_asset("offices.json")
    return _OFFICES_TABLE

def _office_type_from_table(text: str) -> str:
    """按 offices.json priority 顺序，首个命中词干者胜。无命中返回 ''。"""
    from ming_sim.assets import require_dict, require_list, str_field, string_list
    for raw in require_list(_offices_table().get("priority", []), "offices.json.priority"):
        entry = require_dict(raw, "offices.json.priority[]")
        for stem in string_list(entry.get("stems", []), "offices.json.priority[].stems"):
            if stem and stem in text:
                return str_field(entry, "type", "offices.json.priority[]")
    return ""

def _office_type_via_llm(text: str, llm_config: Any = None) -> str:
    """表查不中（生造/罕见官名）时，CLI 后端在场则交 LLM 判 office_type（取 allowed_types）。
    否则返回 ''。结果按官名缓存，避免重复调用。"""
    from ming_sim.cli_backend import cli_backend_active, _run_backend_for_config
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
    raw, _ = _run_backend_for_config(prompt, llm_config, tag="office_infer")
    cand = (raw or "").strip().splitlines()[0].strip() if raw else ""
    out = cand if cand in allowed_set else ""
    _OFFICE_TYPE_LLM_CACHE[text] = out
    return out

def infer_office_type_from_office(
    office: str, current_type: str = "", llm_config: Any = None, use_llm: bool = True
) -> str:
    """用 office 文本判 office_type：先查 offices.json 参考表（明制权威、确定），
    表查不中且 CLI 后端在场再交 LLM 判（生造官名），都不中落『待铨』。
    取代旧版那串临时正则词表（脆、漏）。外藩(后金/蒙古/朝鲜)按 power_id≠ming 另处理，不入此路。

    use_llm=False：跳过 LLM 兜底。表查不中时直接信传入的 current_type（content/DB 既定值，
    含朝堂六部类）原样保留，仅空 kind 落「待铨」。静态名册接档（seed_opening_world）与每回合
    DB sync（_sync_offices_from_db_impl）专用：content/DB 的 office_type 即权威，逐人现拉
    codex 判属纯浪费（开局慢 5 分钟根因），且若沿用动态路径的「朝堂类表查不中→待铨」降级，
    会把动态任命已落库的朝堂类 office_type 在每回合 sync 时悄悄降级、内存与 DB 不一致
    （cmr R2 codex）。动态生造官名（任免/issues）仍走默认 use_llm=True（保留 LLM 兜底 +
    朝堂类无确证则落待铨的谨慎语义）。"""
    kind = (current_type or "").strip()
    if kind == "后宫" or (not use_llm and kind):
        # Seed/sync declarations are authoritative even before debut (empty
        # office), and must not be overwritten by compound-title table matches.
        return kind
    text = normalize_office(office)
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

# Engine-owned arrival bounds (#567 / #1900), scaled from 30; escorted minimum exceeds bare maximum.
_GRANT_ARRIVAL_SCALE = 30
_GRANT_ARRIVAL_BARE = (15, 18)
_GRANT_ARRIVAL_ESCORT = (22, 25)

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


def payload_declares_escort(payload: object) -> bool:
    """拨银载荷是否自带押解安排。未成案与已成案共用这一判据，只是取数位置不同。"""
    if not isinstance(payload, dict):
        return False
    escort = payload.get("escort")
    if not isinstance(escort, dict):
        return False
    escortees = escort.get("escortees")
    return isinstance(escortees, list) and any(
        str(name or "").strip() for name in escortees
    )


def _load_durable_json(raw: object, *, default: str = "{}") -> Any:
    """Decode stored JSON (or consume an already decoded value); NULL uses the column default."""
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(default if raw is None else raw)


def _load_durable_str_list(raw: object, *, surface: str = "stored name list") -> list[str]:
    """Name/identity lists are semantic data, including secrecy exclusions; never coerce members."""
    values = _load_durable_json(raw, default="[]")
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise TypeError(f"{surface} must be a list of strings, got {values!r}")
    return values


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


    def init_schema(self) -> None:
        # game_state（朝局头）与 metrics（余额真源）的建表与写读口归 reign_state store
        # （#1889 按职责拆出）。放在最前：下方的标记读写都要先有这两张表。
        # 人物公私经历与知识来源两张账的建表与写读口归 character_knowledge store
        # （#1889 按职责拆出）。同样放最前：init 早段就会把带参与人的 issues 投影成
        # 共享知识来源，那时这两张表必须已在。
        from ming_sim.entities.character_knowledge import CharacterKnowledgeStore
        ensure_character_knowledge_schema(self.conn)
        self.character_knowledge = CharacterKnowledgeStore(self.conn)
        from ming_sim.entities.reign_state import ReignStateStore
        ensure_reign_schema(self.conn)
        self.reign = ReignStateStore(self.conn)
        # 引擎自有的建表（表/视图/索引）归 ming_sim.schema（#1889 按职责拆出）；
        # 上面两个 store 各自的 DDL 由 store 自己带，这里不持第二份定义。
        ensure_core_schema(self.conn)
        # 案卷 store 的 schema 刚随上面脚本建好；此处即构造，后续 init_schema 的
        # 任何回填/校验都走它（ADR 0151：GameDB 侧不留转发 facade）。
        self.dossiers = DossierStore(self.conn)
        # #1890 source_pending_action_id：列在 ming_sim.schema CREATE（#1889 不再 ALTER 补列）。

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
        ensure_person_log_schema(self.conn)
        self.person_logs = PersonLogStore(self.conn)
        # 当前字段都在 ming_sim.schema 的 CREATE 里。不再为旧档 ALTER 补列。
        self._ensure_office_type_parents()
        self._ensure_event_parents()
        self._apply_region_city_levels()
        # #1843：不再从存量 issues 回填 character_knowledge_sources。
        # 正常 insert_issue 写端登记来源；见闻读口可按持久记录 participant_roster 发现。
        from ming_sim.entities.textual_fact import TextualFactStore
        from ming_sim.entities.affair import AffairStore
        TextualFactStore.ensure_schema(self.conn)
        self.textual_facts = TextualFactStore(self.conn)
        self._rollback_stores = {
            table: store
            for store in (
                self.issues,
                self.character_knowledge,
                self.dossiers,
                self.characters,
                self.factions,
                self.textual_facts,
                self.person_logs,
                self.reign,
            )
            for table in store.TABLES
        }
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
        """从 content/fiscal_config.json seed 财政科目目录。

        #1812/#1835：无旧档差量回填。已有 `__schema_version` 的库不改科目、不补 key；
        新档 cur==0 时整体 INSERT 一次并落版本号。
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
        cfg = self.fiscal_config.values()
        overlay = dict(cfg)
        normalized: Dict[str, int] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key or "").strip()
            value = int(raw_value)
            minimum = self.fiscal_config_minimum_value(key)
            if minimum is not None and value < minimum:
                raise DeclarationDataError(f"fiscal_config.{key} 不得低于结构地板 {minimum}")
            pair = _CENTRAL_LOSS_RATE_PAIRS.get(key)
            if pair is not None and (value < 0 or value > 100):
                raise DeclarationDataError(f"fiscal_config.{key} 须在 0..100")
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
                raise DeclarationDataError(f"{human_key}+{sink_key} 不得超过 100%")

    def validate_fiscal_config_value(self, key: str, value: int) -> None:
        self.validate_fiscal_config_values({key: value})

    def set_fiscal_config(self, key: str, value: int, commit: bool = True) -> None:
        owns_transaction = connection_owns_transaction(self.conn) if commit else False
        self.validate_fiscal_config_value(key, value)
        self.fiscal_config.set_values({key: value})
        if commit and owns_transaction:
            self.conn.commit()

    def set_fiscal_config_batch(self, values: Dict[str, int], commit: bool = True) -> None:
        owns_transaction = connection_owns_transaction(self.conn) if commit else False
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
        exists = self.fiscal_config.item_presence(base_key, rate_key)
        if exists is not None:
            return None
        # #1899：重立已 seed 过的 dynamic 赋饷（田赋/辽饷/盐税/商税/皇庄）必须按其
        # **seed 声明的 budget_role** 落行，不得一律落 fixed。dynamic 赋饷的实收走省级
        # 公式（regions.fiscal / settle.p），account/direction 只喂 flows 的中央定额预算
        # 行；误落 fixed 会让 iter_budget_items 把它当独立中央收入再记一条，与省级那条
        # **同一税项两条收入**（全局硬规 #12/#14 单一机制）。seed 真源是 content/
        # fiscal_config.json 的 budget_role，未 seed 过的 stem（真新科目）仍落 fixed。
        seeded = self._seeded_fiscal_item_meta(stem)
        if seeded is not None and str(seeded.get("budget_role") or "") == "dynamic":
            budget_role = "dynamic"
            item_account = item_direction = item_display = ""
            item_sort_order = int(seeded.get("sort_order", 9999) or 9999)
        else:
            budget_role = "fixed"
            item_account, item_direction, item_display = account, direction, display
            item_sort_order = self.fiscal_config.next_sort_order()
        self.fiscal_config.insert(
            {
                "key": base_key,
                "value": max(0, init_value),
                "kind": "base",
                "budget_role": budget_role,
                "account": item_account,
                "direction": item_direction,
                "display": item_display,
                "sort_order": item_sort_order,
                "note": note,
                "origin_ref": origin_ref,
            }
        )
        self.fiscal_config.insert(
            {
                "key": rate_key,
                "value": 100,
                "kind": "rate",
                "budget_role": budget_role,
                "account": item_account,
                "direction": item_direction,
                "display": item_display,
                "sort_order": item_sort_order,
                "note": f"{display}实收率%",
                "origin_ref": origin_ref,
            }
        )
        # #1260：base+rate 两行 creations 同旗（any() 消费者安全；计数型会双计——勿据此改计数语义）。
        beyond_flag = coerce_beyond_intent_flag(beyond_intent)
        for key, value, kind in (
            (base_key, max(0, init_value), "base"), (rate_key, 100, "rate"),
        ):
            self.fiscal_config.append_history(
                "create",
                {
                    "turn": int(turn),
                    "key": key,
                    "value": value,
                    "kind": kind,
                    "origin_ref": origin_ref,
                    "reason": note,
                    "beyond_intent": beyond_flag,
                },
            )
        if commit:
            self.conn.commit()
        return base_key

    # dynamic 税科目 → regions.fiscal 子字段映射。盐/商等旁路与省级 settle 读 region.fiscal
    # （不读 fiscal_config 的 base），故对这些 key 做裁撤/调额必须同步改各省 fiscal
    # 字段才真生效——否则只动目录不动钱（账目与叙事脱节）。
    #   田赋无独立字段（=tax_per_turn 减其余三税的残差），裁撤走 tax_per_turn 压低；
    #   皇庄收入真读 fiscal_config.皇庄_base，裁撤/调额改 config 即生效，不在本表。
    # Live salt/commerce side channels only. 辽饷 is catalogue/settle driven;
    # do not write retired regions.fiscal.liao_xiang from scale/remove.
    _DYNAMIC_REGION_FIELD = {
        "盐税": "salt_tax", "商税": "commerce_tax",
    }
    _SIDE_CHANNEL_REGION_FIELD = _DYNAMIC_REGION_FIELD

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

    def _seeded_fiscal_item_meta(self, stem: str) -> Optional[Dict[str, object]]:
        """seed 目录（content/fiscal_config.json）里该 stem 任一行的元数据；未 seed 过返 None。

        #1899：复征 dynamic 赋饷时，budget_role 必须回到 seed 声明值（dynamic），
        否则重立行会被 flows 当中央 fixed 收入，与省级那条叠成同一税项两条收入。
        seed 里 dynamic 赋饷**未必有 base 行**（田赋只有 田赋_rate、辽饷/盐税/商税
        才有 _base），故按 stem 归任一行、不挑 kind——本方法只为取回 seed 声明的
        budget_role，不复现 base 值（重立值由调用方给）。
        seed 是静态内容（开局加载一次不变），故按 stem 缓存整张表避免逐键重扫。
        """
        cache = getattr(self, "_seed_fiscal_meta_cache", None)
        if cache is None:
            cache = {}
            for rec in list(self.content.fiscal_items or ()):
                key = str(rec.get("key") or "")
                if not key or key.startswith("__"):
                    continue
                rec_stem = self._stem_of(key)
                if rec_stem and rec_stem not in cache:
                    cache[rec_stem] = dict(rec)
            self._seed_fiscal_meta_cache = cache
        return cache.get(stem)

    def _seeded_fiscal_config_value(self, key: str) -> Optional[int]:
        """seed 目录里**该确切键**的默认值（如 `辽饷_rate`→100）；未 seed 过返 None。

        与 `_seeded_fiscal_item_meta` 分工：后者按 stem 归任一行、只取 budget_role 等
        声明字段，**其 value 属那一行的键**（stem 下先命中的通常是 `<stem>_base`）。
        复征按键调回常态值时若拿它当 `<stem>_rate` 的默认值，会把 rate 写成 base 的数
        （辽饷 100 误成 43）。故此处按 key 精确取，不跨键借值。
        """
        cache = getattr(self, "_seed_fiscal_value_cache", None)
        if cache is None:
            cache = {}
            for rec in list(self.content.fiscal_items or ()):
                rec_key = str(rec.get("key") or "")
                if not rec_key or rec_key.startswith("__"):
                    continue
                try:
                    cache[rec_key] = int(rec.get("value"))
                except (TypeError, ValueError):
                    continue
            self._seed_fiscal_value_cache = cache
        return cache.get(str(key))

    def apply_dynamic_fiscal_scale(self, stem: str, ratio: float, commit: bool = True) -> int:
        """Scale live salt/commerce side-channel income; return changed province count."""
        field = self._SIDE_CHANNEL_REGION_FIELD.get(stem)
        if field is None:
            return 0
        touched = 0
        for row in self.conn.execute('SELECT id, fiscal FROM regions', ()).fetchall():
            fiscal: dict = _load_durable_json(row["fiscal"], default='{}')
            old = int(fiscal.get(field, 0) or 0)
            if old <= 0:
                continue
            new = max(0, round(old * ratio))
            if new == old:
                continue
            fiscal[field] = new
            self.regions.update(
                str(row["id"]), {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
            )
            touched += 1
        if touched and commit:
            self.conn.commit()
        return touched


    def settle_ming_province_substrate_ticks(
        self,
        actions_by_region: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        p_overrides_by_region: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ProvinceFiscalTickOutcome]:
        """一次扫描 Ming 省 fiscal payload 并推进已有 settle 基座。

        批量桥推进已有 settle 基座。合法但无 settle 的 Ming 省出列；坏 JSON/容器/settle
        st/p 与 settle_tick ValueError/守恒错误作为 outcome.error 返回，由调用方 fail-loud。
        其它异常继续上抛。
        """
        from .fiscal_tick import FiscalConservationError

        actions_by_region = actions_by_region or {}
        p_overrides_by_region = p_overrides_by_region or {}
        outcomes: List[ProvinceFiscalTickOutcome] = []
        rows = self.regions.ordered_ming_fiscal_rows()
        for row in rows:
            region_id = str(row["id"])
            fiscal = _load_durable_json_object(
                row["fiscal"], surface=f"regions[{region_id}].fiscal",
            )
            if "settle" not in fiscal:
                continue
            try:
                result = self._settle_province_tick_from_fiscal(
                    region_id,
                    fiscal,
                    actions_by_region.get(region_id, []),
                    p_overrides_by_region.get(region_id),
                )
            except (AttributeError, KeyError, TypeError, ValueError, FiscalConservationError) as exc:
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
            self.fiscal_config.values(), region_id, self.reign.current_settle_turn()
        )
        tick_p = settle["p"]
        if p_overrides or overrides is not None:
            tick_p = {**tick_p}
        if p_overrides:
            tick_p.update(p_overrides)
        if overrides is not None:
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
        self.regions.update(
            region_id, {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
        )
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
        state_row = self.reign.row(1, fields="turn, year, period", table="game_state")
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
                amount = float(source.get(claim, 0) or 0)
                if not math.isfinite(amount) or abs(amount) <= 1e-9:
                    continue
                old_v = float(result.new_st.get(claim, 0) or 0)
                # 流量方向：NewDebt 增欠、Repaid 偿还；region_logs.delta 记有符号流量，
                # old/new_value 记月末 CLAIM 存量两端（留痕语义与其余 region_logs 一致）。
                delta = amount if flow == "NewDebt" else -amount
                self.regions.append_log(
                    {
                        "turn": log_turn,
                        "year": log_year,
                        "period": log_period,
                        "region_id": region_id,
                        "field": f"settle_{claim}_{flow}",
                        "old_value": str(old_v - delta),
                        "new_value": str(old_v),
                        "delta": delta,
                        "reason": f"{TURN_UNIT}省池结算{'新增欠' if flow == 'NewDebt' else '偿旧欠'}"
                        f"{format_wanliang_amount(amount)}万两",
                        "event_id": None,
                        "edict_id": None,
                        "actor": "户部",
                        "origin_ref": origin_ref,
                    }
                )

    def remove_fiscal_item(
        self, key: str, commit: bool = True, *, origin_ref: str = "",
        reason: str = "", turn: int = 0, beyond_intent: object = 0,
    ) -> Optional[str]:
        """彻底裁撤一个月固定收支项（罢税/裁俸）：删 base+rate 两行。

        完全放开——含 dynamic（田赋/辽饷/盐税/商税/皇庄），后果玩家自负。
        - fixed 项：删目录条目即停止逐月落账。
        - 田赋／辽饷由现役饷率 applier 读目录推进省级 tick；皇庄也直接读目录。
        - 盐税／商税仍由现役旁路读取省字段，裁撤须将其归零。
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
        exists = self.fiscal_config.item_presence(base_key, rate_key)
        if exists is None:
            return None
        # The live catalogue cannot retain provenance after DELETE.  Preserve the
        # removed rows in a narrow append-only audit so origin -> removal is a
        # single indexed lookup rather than an inference from unrelated logs.
        # #1260：INSERT...SELECT 显式列清单 + beyond_intent 常量（禁 SELECT * 位置漂移）。
        beyond_flag = coerce_beyond_intent_flag(beyond_intent)
        self.fiscal_config.remove_items(
            (base_key, rate_key),
            turn=int(turn),
            origin=origin_ref,
            reason=reason,
            beyond=beyond_flag,
        )
        # Only the live salt/commerce side channels need region-field writes.
        if stem in self._SIDE_CHANNEL_REGION_FIELD:
            self.apply_dynamic_fiscal_scale(stem, 0.0, commit=commit)
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
        row = self.conn.execute('SELECT city_level, cannon FROM regions WHERE id=?', (region_id,)).fetchone()
        if row is None:
            raise ValueError(f"城防炮引用未入库地区 '{region_id}'")
        cap = int(row["city_level"]) * 8
        new_value = max(0, min(cap, int(row["cannon"]) + int(delta)))
        self.regions.update(region_id, {"cannon": new_value})
        return new_value

    def _ensure_office_type_parents(self) -> None:
        """Materialize every declared/referenced office type before FK-checked writes."""
        for office_type in sorted(self._canonical_office_types()):
            self._ensure_office_type_parent(office_type)
        # #1889：原此处每回合把 character_offices.office_type 镜像回 characters
        # （第二写口的记账机），随该列删除一并去掉。

    def _canonical_office_types(self) -> set[str]:
        # 名分（PERSON_TITLE_KINDS）按契约不入官职体系：静态 seed 人物的 office_type 可能是名分，
        # 不得混进 canonical 集被 materialize 成 offices 父行（#1058）。在唯一定义点排除，
        # 兼作 _ensure_office_type_parent 校验的防御——名分永不是合法父类。
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
        if (
            self.conn.execute(
                'SELECT 1 FROM offices WHERE office_type=?',
                (office_type,),
            ).fetchone()
            is not None
        ):
            return
        if office_type not in self._canonical_office_types():
            raise ValueError(f"未定义官类 '{office_type}'")
        definition = self.content.office_definitions.get(office_type, {})
        self.conn.execute(
            """
            INSERT OR IGNORE INTO offices
            (office_type, power, responsibility, corruption_risk)
            VALUES (?, ?, ?, ?)
            """,
            (
                office_type,
                int(definition.get('power', 0)),
                int(definition.get('responsibility', 0)),
                int(definition.get('corruption_risk', 0)),
            ),
        )

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
        if self.conn.execute(
            'SELECT 1 FROM events WHERE id=?',
            (event_id,),
        ).fetchone() is not None:
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
        self.conn.execute(
            """
            INSERT OR IGNORE INTO events
            (id, title, kind, summary, urgency, severity, credibility, interests, audiences)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(event.title),
                str(event.kind),
                str(event.summary),
                int(event.urgency),
                int(event.severity),
                int(event.credibility),
                json.dumps(event.interests, ensure_ascii=False),
                json.dumps(event.audiences, ensure_ascii=False),
            ),
        )


    def _initialize_army_pay_source_spine(self, is_fresh_armies_seed: bool) -> None:
        """Army pay source spine seed for #287 S1（现役唯一路径）。"""
        if not is_fresh_armies_seed:
            return
        rows = self.conn.execute("""
            SELECT id, owner_power, arrears, pay_source_region,
                   province_pay_share, central_pay_share, is_tusi, self_funded_pay
            FROM armies
            ORDER BY id
        """, ()).fetchall()
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
                    self.armies.append_log(
                        {
                            "turn": seed_state.turn,
                            "year": seed_state.year,
                            "period": seed_state.period,
                            "army_id": army_id,
                            "field": "arrears",
                            "old_value": str(old_arrears),
                            "new_value": "0.0",
                            "delta": -old_arrears,
                            "reason": "自养核销：土司/自养军欠饷不并入朝廷饷源双累加器",
                            "event_id": None,
                            "edict_id": None,
                            "actor": "system",
                        }
                    )
                province_arrears = central_arrears = total_arrears = 0.0
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
                total_arrears = province_arrears + central_arrears
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

    def _reconcile_central_army_pay_arrears_container(self) -> float:
        total = self.conn.execute("""
            SELECT COALESCE(SUM(central_pay_arrears), 0) AS total
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
        """, ()).fetchone()["total"]
        value = float(total or 0.0)
        self.fiscal_containers.replace(
            _CENTRAL_ARMY_PAY_ARREARS_CONTAINER_KEY,
            value,
            "中央军饷欠账容器：Σ非自养明军 central_pay_arrears",
        )
        return value

    def _province_army_pay_container_total(self) -> float:
        total = 0.0
        rows = self.regions.ming_fiscal_rows()
        for row in rows:
            try:
                fiscal = _load_durable_json(row["fiscal"], default='{}')
            except (TypeError, ValueError) as exc:
                raise ValueError(f"region {row['id']} fiscal JSON 非法，无法校验军饷容器守恒：{exc}") from exc
            settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
            if settle is None:
                continue
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                raise ValueError(f"region {row['id']} settle.st 非法，无法校验军饷容器守恒")
            total += float(settle["st"].get("军饷欠", 0.0))
        return total

    def _has_complete_province_pay_containers(self) -> bool:
        rows = self.conn.execute("""
            SELECT DISTINCT pay_source_region
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
              AND pay_source_region != ''
              AND (province_pay_share > 0 OR province_pay_arrears > 0)
        """, ()).fetchall()
        for row in rows:
            region_id = str(row["pay_source_region"] or "")
            region = self.regions.row(region_id, fields="controlled_by, fiscal")
            if region is None or str(region["controlled_by"] or "") != "ming":
                return False
            # 持久财政 JSON / settle 坏态响亮上抛，不洗成「不完整」而跳过守恒（ADR 0005）。
            fiscal = _load_durable_json(region["fiscal"], default='{}')
            settle = fiscal.get("settle")
            if settle is None:
                return False
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                raise ValueError(f"region {region_id} settle.st 持久坏态")
        return True

    def assert_army_pay_source_container_conservation(self) -> None:
        exempt_bad = self.conn.execute("""
            SELECT id, province_pay_share, central_pay_share,
                   province_pay_arrears, central_pay_arrears, arrears
            FROM armies
            WHERE (owner_power != 'ming' OR is_tusi != 0 OR self_funded_pay != 0)
              AND (
                ABS(COALESCE(province_pay_share, 0)) > 1e-9 OR
                ABS(COALESCE(central_pay_share, 0)) > 1e-9 OR
                ABS(COALESCE(province_pay_arrears, 0)) > 1e-9 OR
                ABS(COALESCE(central_pay_arrears, 0)) > 1e-9 OR
                ABS(COALESCE(arrears, 0)) > 1e-9
              )
            ORDER BY id
            LIMIT 1
        """, ()).fetchone()
        if exempt_bad is not None:
            raise ValueError(
                "army "
                f"{exempt_bad['id']} 自养/非明军双累加器必须为 0"
            )
        province_source_rows = self.conn.execute("""
            SELECT id, pay_source_region
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
              AND (
                ABS(COALESCE(province_pay_share, 0)) > 1e-9 OR
                ABS(COALESCE(province_pay_arrears, 0)) > 1e-9
              )
            ORDER BY id
        """, ()).fetchall()
        for province_source in province_source_rows:
            self._require_valid_pay_source_region(
                str(province_source["id"]),
                str(province_source["pay_source_region"] or ""),
            )
        derived_bad = self.conn.execute("""
            SELECT id, arrears, province_pay_arrears, central_pay_arrears
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
              AND ABS(
                COALESCE(arrears, 0)
                - (COALESCE(province_pay_arrears, 0) + COALESCE(central_pay_arrears, 0))
              ) > 1e-6
            ORDER BY id
            LIMIT 1
        """, ()).fetchone()
        if derived_bad is not None:
            expected = float(derived_bad["province_pay_arrears"] or 0.0) + float(
                derived_bad["central_pay_arrears"] or 0.0
            )
            raise ValueError(
                "军饷欠派生合计破："
                f"army={derived_bad['id']} arrears={derived_bad['arrears']} "
                f"province+central={expected}"
            )
        central_container = self.fiscal_containers.value("central_army_pay_arrears")
        row = self.conn.execute("""
            SELECT
              COALESCE(SUM(province_pay_arrears), 0) AS province_total,
              COALESCE(SUM(central_pay_arrears), 0) AS central_total,
              COALESCE(SUM(arrears), 0) AS army_total
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
        """, ()).fetchone()
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
                raise DeclarationDataError(f"army {army_id} {label} 非法：{value!r}")
        exempt = owner_power != "ming" or is_tusi or self_funded
        if exempt:
            if abs(province_share) > 1e-9 or abs(central_share) > 1e-9:
                raise DeclarationDataError(f"army {army_id} 自养/非明军饷源比例必须为 0")
            if abs(province_arrears) > 1e-9 or abs(central_arrears) > 1e-9:
                raise DeclarationDataError(f"army {army_id} 自养/非明军双累加器必须为 0")
            return
        if not pay_source_region:
            raise DeclarationDataError(f"army {army_id} 明军须有 pay_source_region")
        if abs((province_share + central_share) - 1.0) > 1e-9:
            raise DeclarationDataError(f"army {army_id} 饷源比例和必须为 1")

    def _require_valid_pay_source_region(self, army_id: str, pay_source_region: str) -> None:
        row = self.regions.row(pay_source_region, fields="controlled_by, fiscal")
        if row is None:
            raise DeclarationDataError(f"army {army_id} pay_source_region 未入库：{pay_source_region}")
        if str(row["controlled_by"] or "") != "ming":
            raise DeclarationDataError(f"army {army_id} pay_source_region 非明控省：{pay_source_region}")
        fiscal = parse_engine_payload_json(row["fiscal"])
        settle = fiscal.get("settle")
        if settle is not None and not isinstance(settle, dict):
            raise ValueError("持久地区财政 settle 须为对象")
        if isinstance(settle, dict):
            for key in ("st", "p"):
                if settle.get(key) is not None and not isinstance(settle[key], dict):
                    raise ValueError(f"持久地区财政 settle.{key} 须为对象")
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            raise DeclarationDataError(f"army {army_id} pay_source_region 无 settle st/p 基座：{pay_source_region}")

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
            source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        """唯一生产 owner_power 转出口（ADR 0025 D5/D7 + #318）。

        同事务顺序：核销欠饷 → 清 is_mutinied/probation → 改 owner。
        空来源对 1/2 振 latched 军 owner-OUT = 拒收；仅 latched_escape='third_strike'
        （确定性第 3 振）可转出。mutiny_count>=3 不得回 ming。
        """
        changes: List[Dict[str, object]] = []
        rejections: List[RejectedItem] = []
        army_id = str(row["id"])
        old_owner = str(row["owner_power"] or "").strip()
        owner_power = str(new_owner or "").strip()
        item = raw_item if raw_item is not None else {"army_id": army_id}

        if not owner_power:
            rejections.append(RejectedItem(item=item, reason="owner_power 不得为空", category="invalid_enum", source=source))
            return changes, rejections

        owner_exists = self.powers.row(owner_power, fields="1")
        if owner_exists is None:
            rejections.append(RejectedItem(item=item, reason=f"army_delta owner_power '{owner_power}' 不在 powers 表", category="hallucinated_id", source=source))
            return changes, rejections

        if owner_power == old_owner:
            return changes, rejections

        # 空来源：1/2 振 latched 倒戈一律拒收（#318 无 trusted_event_id 生产路径）
        if bool(row["is_mutinied"]) and latched_escape != "third_strike":
            rejections.append(RejectedItem(item=item, reason="哗变锁存军空来源不得改归属（仅第3振确定性转流寇）", category="invalid_enum", source=source))
            return changes, rejections

        mutiny_count = int(row["mutiny_count"] or 0)
        if owner_power == "ming" and mutiny_count >= 3:
            rejections.append(RejectedItem(item=item, reason="mutiny_count>=3 永久流寇不可回明；招安须另建新军", category="invalid_enum", source=source))
            return changes, rejections

        old_source = str(row["pay_source_region"] or "")
        # 持久行的饷源列是存档真源（NOT NULL DEFAULT 0）：坏值在 try 之外上抛，
        # 不并入模型条目的 invalid_enum 拒收（ADR0005 / 0008）。
        row_region = str(row["pay_source_region"] or "").strip()
        row_province_share = _coerce_pay_source_float(row["province_pay_share"])
        row_central_share = _coerce_pay_source_float(row["central_pay_share"])
        row_is_tusi = bool(row["is_tusi"])
        row_self_funded = bool(row["self_funded_pay"])
        row_province_arrears = float(row["province_pay_arrears"] or 0)
        row_central_arrears = float(row["central_pay_arrears"] or 0)
        row_total_arrears = float(row["arrears"] or 0)
        try:
            pay_source_region_val = (
                row_region if pay_source_region is _SENTINEL
                else str(pay_source_region or "").strip()
            )
            province_share = (
                row_province_share if province_pay_share is _SENTINEL
                else _coerce_pay_source_float(province_pay_share)
            )
            central_share = (
                row_central_share if central_pay_share is _SENTINEL
                else _coerce_pay_source_float(central_pay_share)
            )
            is_tusi_val = row_is_tusi if is_tusi is _SENTINEL else _coerce_bool_flag(is_tusi)
            self_funded_val = (
                row_self_funded if self_funded_pay is _SENTINEL
                else _coerce_bool_flag(self_funded_pay)
            )
            province_arrears = row_province_arrears
            central_arrears = row_central_arrears
            total_arrears = row_total_arrears
            total_arrears = max(total_arrears, province_arrears + central_arrears)

            exempt = owner_power != "ming" or is_tusi_val or self_funded_val
            if exempt:
                pay_source_region_val = ""
                province_share = central_share = 0.0
                province_arrears = central_arrears = 0.0
                total_arrears = 0.0
            self._validate_pay_source_values(
                army_id, owner_power, pay_source_region_val, province_share, central_share,
                is_tusi_val, self_funded_val, province_arrears, central_arrears,
            )
            if pay_source_region_val:
                self._require_valid_pay_source_region(army_id, pay_source_region_val)
        except DeclarationDataError as exc:
            rejections.append(RejectedItem(item=item, reason=f"army_delta 饷源字段非法：{exc}", category="invalid_enum", source=source))
            return changes, rejections

        origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
        if origin_error:
            rejections.append(RejectedItem(item=item, reason=origin_error["reason"], category=origin_error["category"], source=source))
            return changes, rejections

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

        # ① 核销欠饷（先于清 latch / 改 owner）；额度只认双源权威账。
        old_dual_arrears = (
            float(old_values["province_pay_arrears"] or 0)
            + float(old_values["central_pay_arrears"] or 0)
        )
        wrote_writeoff = (
            old_owner == "ming"
            and owner_power != "ming"
            and old_dual_arrears > 1e-9
        )
        if wrote_writeoff:
            self.armies.append_log(
                {
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "army_id": army_id,
                    "field": "arrears",
                    "old_value": str(old_dual_arrears),
                    "new_value": "0.0",
                    "delta": -float(old_dual_arrears),
                    "reason": f"owner易主核销：{reason}",
                    "event_id": event_id,
                    "edict_id": edict_id,
                    "actor": actor,
                    "origin_ref": origin_ref,
                }
            )

        # ②+③ 清 latch/probation + 改 owner（唯一生产 UPDATE owner_power）
        self.armies.update(
            army_id,
            {
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
            },
        )

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
            self.armies.append_log(
                {
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "army_id": army_id,
                    "field": field,
                    "old_value": str(old_values[field]),
                    "new_value": str(new_values[field]),
                    "delta": None,
                    "reason": reason,
                    "event_id": event_id,
                    "edict_id": edict_id,
                    "actor": actor,
                    "origin_ref": origin_ref,
                }
            )
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
        return changes, rejections

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
        rejections: List[RejectedItem],
        origin_ref: str = "",
        require_origin: bool = False,
            source: Provenance = Provenance.system_simulation,
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
                landed, refused = self.transition_army_owner_power(
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
                source=source)
                changes.extend(landed)
                rejections.extend(refused)
                return

        # #319 ADR 0025 D4①：先拒脏输入（fail-loud / invalid_enum），校验通过后
        # 再对 latched 军非 owner 饷源字段静默 no-op。写缝在主环 latch 门之前、
        # 且主环对 _ARMY_PAY_SOURCE_DELTA_FIELDS 直接 continue，故既有字段效果门
        # 看不到本缝；在此复用同一 latch 语义，不新开平行门/第二 adapter。
        # 真 owner 变更已由上方 return。禁止把 latch return 前移到校验之前。
        old_source = str(row["pay_source_region"] or "")
        owner_power = str(row["owner_power"] or "").strip()
        pay_source_region = str(normalized.get("pay_source_region", row["pay_source_region"]) or "").strip()
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
        try:
            province_share = (
                _coerce_pay_source_float(normalized["province_pay_share"])
                if "province_pay_share" in normalized else old_values["province_pay_share"]
            )
            central_share = (
                _coerce_pay_source_float(normalized["central_pay_share"])
                if "central_pay_share" in normalized else old_values["central_pay_share"]
            )
            is_tusi = (
                _coerce_bool_flag(normalized["is_tusi"])
                if "is_tusi" in normalized else bool(row["is_tusi"])
            )
            self_funded = (
                _coerce_bool_flag(normalized["self_funded_pay"])
                if "self_funded_pay" in normalized else bool(row["self_funded_pay"])
            )
            province_arrears = old_values["province_pay_arrears"]
            central_arrears = old_values["central_pay_arrears"]
            exempt = owner_power != "ming" or is_tusi or self_funded
            exempt_by_ming_flag = (
                owner_power == "ming"
                and not bool(row["is_tusi"])
                and not bool(row["self_funded_pay"])
                and (is_tusi or self_funded)
            )
            if exempt_by_ming_flag and (province_arrears + central_arrears) > 1e-9:
                raise DeclarationDataError(
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
        except DeclarationDataError as exc:
            rejections.append(RejectedItem(item={"army_id": army_id, "changes": raw_changes}, reason=f"army_delta 饷源字段非法：{exc}", category="invalid_enum", source=source))
            return

        # 合法且被 deny 的饷源字段：静默 no-op，不写库、不留 rejected
        if bool(row["is_mutinied"]):
            return

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
            rejections.append(RejectedItem(item={"army_id": army_id, "changes": raw_changes}, reason=origin_error["reason"], category=origin_error["category"], source=source))
            return

        # 饷源-only 路径：不触 owner_power（唯一 owner 写口 = transition_army_owner_power）
        self.armies.update(
            army_id,
            {
                "pay_source_region": pay_source_region,
                "province_pay_share": province_share,
                "central_pay_share": central_share,
                "is_tusi": 1 if is_tusi else 0,
                "self_funded_pay": 1 if self_funded else 0,
                "province_pay_arrears": province_arrears,
                "central_pay_arrears": central_arrears,
            },
        )
        for field in changed_fields:
            self.armies.append_log(
                {
                    "turn": state.turn,
                    "year": state.year,
                    "period": state.period,
                    "army_id": army_id,
                    "field": field,
                    "old_value": str(old_values[field]),
                    "new_value": str(new_values[field]),
                    "delta": None,
                    "reason": reason,
                    "event_id": event.id,
                    "edict_id": edict_id,
                    "actor": actor,
                    "origin_ref": origin_ref,
                }
            )
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
        from ming_sim.army_pay import army_needed

        out: List[Dict[str, float | str]] = []
        rows = self.conn.execute("""
            SELECT id, name, manpower, salary_rate, owner_power, pay_source_region, morale,
                   province_pay_share, central_pay_share, province_pay_arrears,
                   central_pay_arrears, is_tusi, self_funded_pay
            FROM armies
            WHERE pay_source_region = ? AND owner_power = 'ming'
              AND is_tusi = 0 AND self_funded_pay = 0
              AND province_pay_share > 0
            ORDER BY id
        """, (region_id,)).fetchall()
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
        """逐军省份额为军饷唯一真源；无对应军份额的省旁账不另立。"""
        rows = self._army_pay_source_rows_for_region(region_id)
        p = settle.get("p")
        due_obj = p.get("Due")
        st = settle.get("st")
        if not isinstance(st, dict):
            raise ValueError("settle.st 非法")
        row_due_total = sum(float(row["due"]) for row in rows)
        row_arrears_total = sum(float(row["province_pay_arrears"]) for row in rows)
        due_obj["军饷"] = row_due_total if rows else 0
        st["军饷欠"] = row_arrears_total if rows else 0
        return rows

    def _reconcile_all_army_pay_source_regions(self) -> None:
        rows = self.regions.ordered_ming_fiscal_rows()
        for row in rows:
            fiscal = _load_durable_json(row["fiscal"], default='{}')
            settle = fiscal.get("settle")
            if settle is None:
                continue
            pay_rows = self._derive_region_army_pay_due(str(row["id"]), settle)
            if pay_rows:
                self._reconcile_region_army_pay_container(str(row["id"]), settle)
            self.regions.update(
                str(row["id"]), {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
            )

    def _reconcile_army_pay_source_region_container(self, region_id: str) -> None:
        if not region_id:
            return
        row = self.regions.row(region_id, fields="fiscal")
        if row is None:
            return
        fiscal = _load_durable_json(row["fiscal"], default='{}')
        settle = fiscal.get("settle")
        if settle is None:
            return
        self._derive_region_army_pay_due(region_id, settle)
        self.regions.update(
            region_id, {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
        )

    def _apply_region_army_pay_tick(
        self,
        pay_rows: List[Dict[str, float | str]],
        result: Any,
    ) -> None:
        if not pay_rows:
            return
        from ming_sim.army_pay import army_pay_morale_delta

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
        state_row = self.reign.row(1, fields="turn, year, period", table="game_state")
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
            self.conn.execute("""
                UPDATE armies
                SET province_pay_arrears = ?,  morale = ?,
                    consecutive_pay_shortfall_months = CASE
                        WHEN ? > 1e-9 THEN consecutive_pay_shortfall_months + 1 ELSE 0 END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (province_arrears, new_morale, total_shortfall, army_id))
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
                self.armies.append_log(
                    {
                        "turn": log_turn,
                        "year": log_year,
                        "period": log_period,
                        "army_id": army_id,
                        "field": "province_pay_arrears",
                        "old_value": str(old_province_arrears),
                        "new_value": str(province_arrears),
                        "delta": province_delta,
                        "reason": reason,
                        "event_id": None,
                        "edict_id": None,
                        "actor": "户部",
                    }
                )
            morale_actual_delta = new_morale - old_morale
            if morale_actual_delta != 0:
                self.armies.append_log(
                    {
                        "turn": log_turn,
                        "year": log_year,
                        "period": log_period,
                        "army_id": army_id,
                        "field": "morale",
                        "old_value": str(old_morale),
                        "new_value": str(new_morale),
                        "delta": morale_actual_delta,
                        "reason": reason,
                        "event_id": None,
                        "edict_id": None,
                        "actor": "户部",
                    }
                )

    def _reconcile_region_army_pay_container(self, region_id: str, settle: Dict[str, Any]) -> None:
        total = self.conn.execute("""
            SELECT COALESCE(SUM(province_pay_arrears), 0) AS total
            FROM armies
            WHERE pay_source_region = ? AND owner_power = 'ming'
              AND is_tusi = 0 AND self_funded_pay = 0
        """, (region_id,)).fetchone()["total"]
        row_arrears_total = float(total or 0)
        st = settle.get("st")
        if not isinstance(st, dict):
            raise ValueError("settle.st 非法")
        # 军饷欠唯一来源 = 军籍省侧累加器；不另加独立漏斗。
        st["军饷欠"] = row_arrears_total


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
            # 事实缺失，下次重开 reign.exists() 为真、再也不会补 seed，得到一份永久残缺的新档。
            with atomic(self):
                self.reign.save_game_state(state)
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
            exists = self.conn.execute(
                'SELECT 1 FROM economy_ledger WHERE account = ? LIMIT 1',
                (account,),
            ).fetchone()
            if exists:
                continue
            balance = int(state.metrics[account])
            self.reign.insert_economy_move(
                state.turn,
                state.year,
                state.period,
                account,
                balance,
                balance,
                "期初",
                "登基初始账册",
                None,
                None,
                "内阁",
                None,
                None,
                None,
                None,
                "",
                0,
            )
        self.conn.commit()


    def seed_opening_gazette(self, state: GameState) -> None:
        """开局公共见闻（新君登基/倒魏）。

        #1356/#1292：不再写入固定开局邸报文到 turn_reports（P7 禁固定模板直显）。
        首份玩家可见邸报由第一个正常月末 LLM 结算产生；content/opening_gazette.md 不进玩家面。
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
        其余带 gate 的 seed 事件靠 auto_trigger_seed_issues 在 gate 达标的回合再硬立。"""
        for ev in self.content.seed_events:
            if not ev.auto_trigger or ev.trigger_gate:
                continue
            if ev.event_type != "situation":
                continue
            if self.issues.by_origin("event_pool", ev.id) is not None:
                continue
            # 推导默认 bar / inertia / ongoing / effect，与 event_to_issue 同口径；精调字段优先
            bar = ev.bar_value or max(20, min(60, 50 - int(ev.severity / 5)))
            inertia = ev.issue_inertia  # 默认 0=不漂；要月漂在 seed 里显式填
            self.insert_issue(
                state,
                kind="situation",
                title=ev.title,
                origin_kind="event_pool",
                origin_ref=ev.id,
                bar_value=bar,
                bar_good_meaning=ev.bar_good_meaning or "已平",
                bar_bad_meaning=ev.bar_bad_meaning or "失控",
                inertia=inertia,
                stage_text=ev.stage_text or ev.summary,
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
        fields = {
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
        if status not in PERSON_STATUSES:
            raise ValueError(f"character status 非法：{status}")
        # #9：UPDATE 前读旧派系（退场清 office 后仍按当前在朝成员现算，与旧职无关）。
        prev = self.characters.row(name, fields="faction")
        # 去职（下狱/革职/流放/致仕/出宫/死）即削职：清空 characters.office，
        # 原职仍留在 character_offices 备档可追溯。复职（active）不动 office。
        ousted = status in PERSON_OUSTED_STATUSES
        reason_code_value = str(reason_code or "")
        if ousted:
            self.characters.update(
                name,
                {
                    "status": status,
                    "status_reason": reason,
                    "status_changed_turn": state.turn,
                    "office": "",
                    "reason_code": reason_code_value,
                },
            )
            self.set_character_transit(name, content=content, commit=False)
        else:
            self.characters.update(
                name,
                {
                    "status": status,
                    "status_reason": reason,
                    "status_changed_turn": state.turn,
                    "reason_code": reason_code_value,
                },
            )
        if content is not None and name in content.characters:
            character = content.characters[name]
            character.status = status
            character.status_reason = reason
            character.reason_code = reason_code_value
            if ousted:
                character.office = ""
        # #9：状态变更后全重算该人物所属朝堂派系 leverage（绝对值、读当前所有在朝成员 → 无漂移）。
        if prev is not None:
            self.recompute_faction_leverage(str(prev["faction"] or ""))
        if ousted:
            # Free prose status reason: preserve raw separators (#1834 F21).
            note = f"人物终态：{status}；{reason}" if str(reason or "") else f"人物终态：{status}"
            self.interrupt_dossiers_for_character(
                state, name, note,
                commit=False,
            )
        if commit:
            self.conn.commit()

    def _faction_office_weight_sum(self, faction: str) -> float:
        """该 faction 当前所有 status='active' 的大明成员的官职权重和
        （每人 = office_type 域权重 × 品级档 multiplier）。只算大明朝臣（power_id='ming'）——
        外藩成员即便挂 ming 风格头衔也不握明官；白名单派系本就全 ming，此约束为防御。"""
        rows = self.conn.execute(
            'SELECT office_type, office FROM characters WHERE faction=? AND '
            "status='active' AND power_id='ming'",
            (faction,),
        ).fetchall()
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
        row = self.factions.row(faction, fields="leverage_offset")
        if row is None:
            return
        offset = float(row["leverage_offset"] or 0)
        weight_sum = self._faction_office_weight_sum(faction)
        new_lev = max(0, min(100, round(offset + weight_sum)))
        self.conn.execute('UPDATE factions SET leverage=? WHERE name=?', (new_lev, faction))

    def recompute_all_faction_leverage(self) -> None:
        """#9 cmr R2：全量重算所有白名单朝堂派系 leverage（集中化兜底层）。

        两层设计：
          (1) 即时 hook（set_character_status / set_character_office /
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
        """#9 offset 校准：offset = 基线 leverage − 当前在朝官职权重和。

        新档（is_fresh_factions_seed）：基线取钦定 content.factions[f].leverage，
        校准后立即 recompute。#1843：老档反推校准已退役——非 fresh 直接 return。
        只校准白名单 faction。不在此 commit——由 seed_opening_world 末尾统一提交。
        """
        if not is_fresh_factions_seed:
            return
        if self.reign.has_meta_flag("__leverage_offsets_calibrated"):
            return
        for faction in _LEVERAGE_FACTIONS:
            row = self.conn.execute('SELECT 1 FROM factions WHERE name=?', (faction,)).fetchone()
            if row is None:
                continue
            content_faction = self.content.factions.get(faction)
            if content_faction is None:
                continue
            baseline = int(content_faction.leverage)
            weight_sum = self._faction_office_weight_sum(faction)
            offset = baseline - weight_sum
            self.conn.execute('UPDATE factions SET leverage_offset=? WHERE name=?', (offset, faction))
            self.recompute_faction_leverage(faction)
        self.reign.upsert_metric("__leverage_offsets_calibrated", 1)

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
        if isinstance(source, Provenance):
            source = source.value
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


    def resolve_power_id(self, character) -> str:
        """人物所属势力 id 的权威解析：DB 行 power_id 优先，回退内存 power_id，默认 ming。

        DB 为准是关键：招抚归明者（流寇/降将 power_id 经 apply_character_power_changes 翻 ming，
        但 content/内存 power_id 仍是旧势力 bandits/houjin）必须认 DB——否则按内存会把已归明者
        误判为外藩、误拒在朝堂外（见 #125、web_app._character_power_id 同源）。"""
        row = self.characters.row(character.name, fields="power_id")
        return (row["power_id"] if row else None) or getattr(character, "power_id", "ming") or "ming"

    def apply_character_power_changes(
        self,
        changes: List[Dict[str, object]],
        commit: bool = True,
            source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        """据 extractor 输出改人物 power_id（降将/叛臣/归正）。new_power 须为合法 power id。"""
        rejections: List[RejectedItem] = []
        applied: List[Dict[str, object]] = []
        if not isinstance(changes, list):
            return applied, rejections
        valid_powers = {r["id"] for r in self.powers.ids()}
        for raw in changes:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or raw.get("姓名") or "").strip()
            new_power = str(raw.get("new_power") or raw.get("新势力") or "").strip()
            reason = str(raw.get("reason") or raw.get("原因") or "")
            if not name or not new_power:
                rejections.append(RejectedItem(item=raw, reason="易主项缺 name/new_power", category="invalid_enum", source=source))
                continue
            if new_power not in valid_powers:
                rejections.append(RejectedItem(item=raw, reason=f"易主 new_power '{new_power}' 未在 powers", category="hallucinated_id", source=source))
                continue
            row = self.conn.execute(
                'SELECT power_id, faction FROM characters WHERE name=?',
                (name,),
            ).fetchone()
            if row is None:
                rejections.append(RejectedItem(item=raw, reason=f"易主 人物 '{name}' 未入库", category="missing_ref", source=source))
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
        return applied, rejections

    def set_character_office(
        self,
        name: str,
        office: str,
        office_type: str = "",
        source: str = "诏书调任",
        llm_config: Any = None,
        commit: bool = True,
        region_id: str = "",
        use_llm: bool = True,
    ) -> None:
        """既有官员调任/升迁：改 characters.office（office_type 给空则不动），
        同步 character_offices 备档。状态不变（仍 active）。
        地方职任所经 :meth:`_require_local_office_region`：显式 typed region
        原样消费；同人同职 identity 续任沿 character_offices.region_id；
        真正新建/改授缺 typed 任所才拒（不读 location/官名推断）。
        #9：授官改了 office_type/品级 → 末尾全重算所属朝堂派系 leverage（升迁也联动；
        起复路 set_character_status(active)→set_character_office(新职) 双 recompute，新职覆盖中间值）。
        use_llm：与 :func:`infer_office_type_from_office` 同义；静态名册/历史登场等
        已有结构化 office_type 的路径传 False，避免表查/LLM 覆盖既有元数据。"""
        office = normalize_office(office)
        current_type = (
            self.conn.execute(
                "SELECT office_type FROM characters WHERE name=? AND power_id='ming'",
                (name,),
            ).fetchone()
            or {"office_type": ""}
        )["office_type"]
        if not current_type:
            raise ValueError(f"{name}不属大明朝廷，不能授予大明官职")
        # 显式声明的名分（office_type ∈ PERSON_TITLE_KINDS）是权威身份，office 文本反推不得
        # 覆盖它（例 office='诸生'→infer 改写成 '生员'，令名分守卫失效，#1059 codex 同源）；
        # office_type 留空回落 current_type 时仍照常重推（授实职即脱名分，不短路）。
        eff_type = resolve_office_type_preserving_title(
            office, office_type, current_type, llm_config or self.llm_config,
            use_llm=use_llm,
        )
        is_person_title = eff_type in PERSON_TITLE_KINDS
        if not is_person_title:
            self._ensure_office_type_parent(eff_type)
        seat = self._require_local_office_region(
            name=name, office=office, office_type=eff_type, region_id=region_id,
        )
        if office_type or eff_type != current_type:
            self.characters.update(
                name, {"office": office, "office_type": eff_type}
            )
        else:
            self.characters.update(name, {"office": office})
        self._record_character_office(name, office, eff_type, source, region_id=seat)
        # #9：授官改了 office_type/品级权重 → 全重算该人物所属朝堂派系 leverage（commit 前）。
        faction_row = self.characters.row(name, fields="faction")
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
        rows = self.conn.execute(
            """
            SELECT name, office, faction, historical_death_year, historical_death_month
                           FROM characters
                           WHERE status = 'active' AND historical_death_year > 0
            """,
            (),
        ).fetchall()
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
                "office": r["office"] or "",
                "faction": r["faction"] or "",
            })
        return died

    def apply_historical_debuts(self, state: GameState) -> List[Dict[str, str]]:
        """月初 tick：offstage 人物到历史登场年月，自动转 active 并发"起用"讯息。
        debut_year=0 视为开局即在场（不会处于 offstage）。
        返回 [{name, office, faction}] 喂给 simulator 当月上下文，由 LLM 写进邸报。
        """
        rows = self.conn.execute(
            """
            SELECT name, office, faction, debut_year, debut_month
                           FROM characters
                           WHERE status = 'offstage' AND debut_year > 0
            """,
            (),
        ).fetchall()
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
            # Offstage keeps office empty (ADR 0009 ①). Debut title comes from
            # explicit content.debut_office — never status_reason, never「重臣」.
            office = str(r["office"] or "").strip()
            if not office:
                ch = (
                    self.content.characters.get(name)
                    if self.content is not None else None
                )
                office = str(getattr(ch, "debut_office", "") or "").strip()
                if office:
                    # Structured content.office_type + use_llm=False：与 opening_seed
                    # 静态接档同契约，不让表查/LLM 改写既有元数据。
                    office_type = str(getattr(ch, "office_type", "") or "").strip()
                    region_id = str(
                        getattr(ch, "office_region", "") or ""
                    ).strip()
                    self.set_character_office(
                        name, office, office_type,
                        region_id=region_id,
                        source="历史登场", commit=True, use_llm=False,
                    )
            # Debut fact reads the persisted office (normalize_office may differ
            # from content.debut_office, e.g. fullwidth comma → ASCII).
            office_row = self.characters.row(name, fields="office")
            office = str(
                (office_row["office"] if office_row is not None else "") or ""
            ).strip()
            debuted.append({
                "name": name,
                "office": office,
                "faction": r["faction"] or "",
            })
        return debuted

    def next_pool_portrait_id(self, prefix: str = "minister_pool_") -> str:
        """分配下一个预设头像 ID（顺序递增，不循环）。
        minister_pool: 60 个槽；consort_pool: 20 个槽。
        实际可用槽位 = web/public/portraits/<prefix><N>.png 真存在的编号集合（中途删图会跳过缺号）。
        发行包只带 web/dist；public 不存在时回退扫 web/dist/portraits。
        全部用完后再回退到递增（前端 onError fallback 占位符）。"""
        rows = self.conn.execute(
            'SELECT portrait_id FROM characters WHERE portrait_id LIKE ?',
            (prefix + '%',),
        ).fetchall()
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


    def add_character(
        self,
        state: GameState,
        character: "Character",
        source: str = "",
        llm_config: Any = None,
        commit: bool = True,
    ) -> None:
        """运行时新建人物（吏部任命/皇帝点名）。已存在同名则不动，避免覆盖既有状态。"""
        existing = self.characters.row(character.name, fields="name")
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
        self.characters.insert(
            {
                "name": character.name,
                "office": character.office,
                "office_type": character.office_type,
                "faction": character.faction,
                "aliases": json.dumps(character.aliases, ensure_ascii=False),
                "personal_skills": json.dumps(
                    character.personal_skills, ensure_ascii=False
                ),
                "loyalty": character.loyalty,
                "ability": character.ability,
                "integrity": character.integrity,
                "courage": character.courage,
                "style": character.style,
                "identity": character.identity,
                "intrigue": character.intrigue,
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
            }
        )
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
            "中央军饷", "太仓亏空", "宗室禄米", "百官俸禄", "工部", "赈灾备用", "建筑维护"
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
        hub_debit = self.conn.execute(
            """
            SELECT COALESCE(SUM(-delta), 0) AS amount
            FROM economy_ledger
            WHERE turn = ? AND account = '国库' AND category = '边饷hub'
            """,
            (settled_turn,),
        ).fetchone()
        containers = self.conn.execute("""
            SELECT key, value FROM fiscal_containers
            WHERE key IN ('hub_京运实拨', 'hub_中央军饷实拨', 'hub_京运损耗')
        """, ()).fetchall()
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
        public_only: bool = False,
    ) -> str:
        account_rows = self.conn.execute(
            'SELECT account, balance FROM economy_accounts ORDER BY account DESC',
            (),
        ).fetchall()
        if not account_rows:
            account_text = f"国库{format_money(state.metrics['国库'])}，内库{format_money(state.metrics['内库'])}"
        else:
            account_text = "，".join(f"{row['account']}{format_money(int(row['balance']))}" for row in account_rows)

        from ming_sim.knowledge import origin_visible_to

        excluded_ids = (
            tuple(
                int(row["id"])
                for row in self.conn.execute(
                    'SELECT id, origin_ref, dossier_id FROM economy_ledger ORDER BY id',
                    (),
                )
                if public_only
                and not origin_visible_to(
                    self,
                    row["origin_ref"],
                    linked_dossier_id=int(row["dossier_id"] or 0),
                )
            )
            if public_only
            else ()
        )
        period_rows = self.reign.ledger_totals(state.turn, excluded_ids)
        period_text = "；".join(
            f"{row['account']}入{format_money(int(row['income'] or 0))}出{format_money(int(row['expense'] or 0))}"
            for row in period_rows
        )
        if not period_text:
            period_text = f"本{TURN_UNIT}尚无新账"

        # limit=None：不截断（#1834 推演者盘面全量——与 region_rows/army_rows
        # 同一「None = 无 LIMIT 子句」约定，不是另造一套语义）。
        ledger_rows = self.reign.recent_ledger(excluded_ids, limit)
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


    def class_report(self, *, audience: bool = False) -> str:
        """全国汇总 + 各省紧张切片（sat<=30 且 lev>=60）。

        audience=True 时满意度/势力走既有定性档（与派系满意/势力定性词表同），
        供 simulator 等玩家可感混合调用；机面默认仍给裸值。
        """
        national = self.conn.execute(
            'SELECT name, region_id, population, satisfaction, leverage, agenda FROM '
            'classes WHERE region_id = ? ORDER BY name',
            ('',),
        ).fetchall()
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
        hot = self.conn.execute("""
            SELECT c.name, c.region_id, c.satisfaction, c.leverage, r.name AS region_name
            FROM classes c
            LEFT JOIN regions r ON r.id = c.region_id
            WHERE c.region_id <> '' AND c.satisfaction <= 30 AND c.leverage >= 60
            ORDER BY c.satisfaction ASC, c.leverage DESC
        """, ()).fetchall()
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
            source: Provenance = Provenance.system_simulation,
    ) -> List[RejectedItem]:
        """deltas 结构：{ key: {satisfaction: +/-N, leverage: +/-N} }
        key 形式：'农民' (全国) 或 '农民@shaanxi' (省级)。

        查无此阶级（名/省不匹配）→ missing_ref 逐项拒收留痕（ADR 0008 决定 1，#14/#63
        死法 3）；入参经 _apply_class_dict 预清洗。返回 RejectedItem 列表，由调用方收进拒收报告。
        """
        rejected: List[RejectedItem] = []
        for key, fields in deltas.items():
            if not fields:
                continue
            if "@" in key:
                name, region_id = key.split("@", 1)
            else:
                name, region_id = key, ""
            row = self.conn.execute(
                'SELECT satisfaction, leverage FROM classes WHERE name = ? AND '
                'region_id = ?',
                (name.strip(), region_id.strip()),
            ).fetchone()
            if not row:
                rejected.append(RejectedItem(item={key: fields}, reason=f"class_delta 查无此阶级「{key}」（未入 classes 表）", category="missing_ref", source=source))
                continue
            sat = int(row["satisfaction"]) + int(fields.get("satisfaction", 0) or 0)
            lev = int(row["leverage"]) + int(fields.get("leverage", 0) or 0)
            sat = max(0, min(100, sat))
            lev = max(0, min(100, lev))
            self.conn.execute(
                'UPDATE classes SET satisfaction = ?, leverage = ?, updated_at = '
                'CURRENT_TIMESTAMP WHERE name = ? AND region_id = ?',
                (sat, lev, name.strip(), region_id.strip()),
            )
        if commit:
            self.conn.commit()
        return rejected

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
            for row in self.powers.rows(exclude_self=exclude_self)
        ]

    def power_report(
        self, exclude_self: bool = True, kinds: Optional[Iterable[str]] = None,
        *, audience: bool = False,
    ) -> str:
        rows = self.powers.rows(exclude_self=exclude_self)
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

        When the settlement orchestrator arms ``_batch_authorized_open_affair_ids``,
        ``affair:<id>`` must also sit in that frozen batch set — one authority
        for every durable-effect carrier (fiscal included).

        Only identity-shape faults are absorbed as invalid_origin_ref. Durable
        getter / store decode errors propagate loud (#1897 E1).
        """
        value = str(origin_ref or "").strip()
        valid = value == "盘面自发"
        unauthorized_batch = False
        reason = None
        if value.startswith("dossier:"):
            raw_id = value.split(":", 1)[1]
            try:
                dossier_id = strict_sqlite_id(raw_id)
            except (TypeError, ValueError) as exc:
                valid = False
                reason = str(exc)
            else:
                if dossier_id <= 0:
                    valid = False
                else:
                    dossier = self.dossiers.get(dossier_id)
                    valid = (
                        dossier is not None
                        and self.dossiers.authorizes_effects(dossier_id)
                    )
        elif value.startswith("affair:"):
            from ming_sim.entities.affair.store import (
                UnauthorizedAffairOriginRef,
                parse_origin_ref,
            )
            try:
                kind, affair_id = parse_origin_ref(value)
            except (OverflowError, TypeError, ValueError) as exc:
                valid = False
                reason = str(exc)
            else:
                if kind == "affair" and affair_id is not None:
                    try:
                        self.affairs.get(int(affair_id))
                    except KeyError as exc:
                        valid = False
                        reason = str(exc)
                    else:
                        authorized = getattr(
                            self, "_batch_authorized_open_affair_ids", None,
                        )
                        if authorized is not None and affair_id not in authorized:
                            valid = False
                            unauthorized_batch = True
                        else:
                            valid = True
                else:
                    valid = False
        if valid:
            return None
        if unauthorized_batch:
            from ming_sim.entities.affair.store import UnauthorizedAffairOriginRef
            return {"category": "unauthorized_affair_origin", "reason": str(UnauthorizedAffairOriginRef())}
        return {"category": "missing_origin_ref" if not value else "invalid_origin_ref", "reason": "效果缺 origin_ref；盘面自然演化须显式标为「盘面自发」"
                       if not value else f"origin_ref 非法：{value}"}

    def apply_power_deltas(
        self,
        state: GameState,
        updates: Dict[str, Dict[str, object]],
        commit: bool = True,
        origin_ref: str = "",
        require_origin: bool = False,
            source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        rejections: List[RejectedItem] = []
        allowed_fields = {"leverage", "military_strength", "supply"}
        changes: List[Dict[str, object]] = []
        for power_id, raw_changes in updates.items():
            if power_id == "ming":
                # prompt 明文禁止写 ming——按脏数据逐项拒收留痕，与同函数其余拒收
                # 路一致（cmr S1 r2，原 print 静默跳是迁契约漏网）。
                rejections.append(RejectedItem(item={"power_id": power_id, "changes": raw_changes}, reason="power_updates 不处理大明自身（ming），prompt 明文禁止", category="invalid_enum", source=source))
                continue
            row = self.powers.row(power_id)
            if row is None:
                rejections.append(RejectedItem(item={"power_id": power_id, "changes": raw_changes}, reason=f"power_updates 引用未入库势力 '{power_id}'", category="hallucinated_id", source=source))
                continue
            # reason 载体按别名表扫描（近况/最近行动 等与 近动/last_action 同义，
            # 硬编码键名会漏——cmr S1 r3）：先取 reason 义，再取 last_action 义。
            # Free prose reason/last_action: preserve raw; emptiness on local copy.
            reason = ""
            for _canon in ("reason", "last_action"):
                for k, v in raw_changes.items():
                    mapped = POWER_FIELD_ALIASES.get(str(k).strip(), str(k).strip())
                    if mapped == _canon and str(v or "").strip():
                        reason = str(v)
                        break
                if reason.strip():
                    break
            if not reason.strip():
                reason = "势力推演"
            for raw_field, value in raw_changes.items():
                field = POWER_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "last_action", "origin_ref"):
                    # reason/last_action（含 近动 等别名）是本函数上方消费的 reason
                    # 载体键——跳过，不得记成 invalid_enum 假阳（cmr S1 r2）。
                    continue
                if field not in allowed_fields:
                    rejections.append(RejectedItem(item={"power_id": power_id, "field": str(raw_field), "value": value}, reason=f"power_updates 只允许 威望/实力/经济，'{raw_field}' 非法", category="invalid_enum", source=source))
                    continue
                old_value = row[field]
                try:
                    # LLM 叶子值脏（null/"三成"/小数串）= 脏数据逐项拒，不崩整批
                    # （sanitize_delta_shape 只验容器、容忍 null 叶——cmr S1 r1，
                    # 同 secret_order order_id 非整数先例）。float/bool 显式拒：
                    # int(3.7)→3 静默截断、True→1 拟真，都不是 prompt 要的整数
                    # delta（cmr S1 r2；bool 是 int 子类须先判）。
                    if isinstance(value, bool) or isinstance(value, float):
                        raise ValueError("非整数 delta")
                    delta = int(value)
                except (TypeError, ValueError) as exc:
                    rejections.append(RejectedItem(item={"power_id": power_id, "field": str(raw_field), "value": value}, reason=str(exc), category="invalid_enum", source=source))
                    continue
                new_value = max(0, min(100, int(old_value) + delta))
                actual_delta = new_value - int(old_value)
                if actual_delta == 0:
                    continue
                origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
                if origin_error:
                    rejections.append(RejectedItem(item={"power_id": power_id, "field": str(raw_field), "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                    continue
                stored_new: object = new_value
                log_delta: int | None = actual_delta
                self.powers.update(power_id, {field: stored_new})
                self.powers.append_log(
                    {
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
                    }
                )
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
        return changes, rejections

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
        new_name = str(new_name or "")
        if not power_id or not new_name.strip():
            return None
        row = self.powers.row(power_id)
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
        new_status = str(status or row["status"] or "")
        new_last_action = str(last_action or reason or row["last_action"] or "")
        if old_name == new_name and old_aliases == new_aliases and row["status"] == new_status and row["last_action"] == new_last_action:
            return None
        self.powers.update(
            power_id,
            {
                "name": new_name,
                "aliases": new_aliases,
                "status": new_status,
                "last_action": new_last_action,
            },
        )
        self.conn.execute("""
            INSERT INTO power_name_logs
            (turn, year, period, power_id, old_name, new_name, old_aliases, new_aliases, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (state.turn, state.year, state.period, power_id, old_name, new_name, old_aliases, new_aliases, str(reason or '')))
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

    def region_report(self, limit: int = 5) -> str:
        rows = self.regions.rows(limit=limit, danger_order=True)
        if not rows:
            return "地区尚未建档。"
        total_tax = self.conn.execute('SELECT SUM(tax_per_turn) AS total FROM regions', ()).fetchone()
        total_tax_value = int(total_tax["total"] or 0)
        parts = []
        for row in rows:
            held = ""
            if str(row["controlled_by"]) != "ming":
                held = f"【已为{self.powers.display_name(row['controlled_by'])}所据】"
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
            held = f"，控制权：已为{self.powers.display_name(row['controlled_by'])}所据（非大明辖治）"
        # ADR 0088/#648 / #1835：现役唯一人口径——玩家面「约N万口」（P4），机面裸人数。
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
            source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        rejections: List[RejectedItem] = []
        changes: List[Dict[str, object]] = []
        for region_id, raw_changes in region_deltas.items():
            row = self.regions.row(region_id)
            if row is None:
                # ADR 0008 决定 1:LLM 幻觉地区 id = 逐项拒收留痕,不再 print 静默跳;
                # 坏一项不带走整批(同信封好地区照落)。
                rejections.append(RejectedItem(item={"region_id": region_id, "changes": raw_changes}, reason=f"region_delta 引用未入库地区 '{region_id}'", category="missing_ref", source=source))
                continue
            # Free prose delta reason → logs / turn summaries: raw bytes (#1834 F16).
            raw_reason = str(raw_changes.get("reason") or raw_changes.get("原因") or "")
            reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")
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
                    except (TypeError, ValueError) as exc:
                        rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=str(exc), category="invalid_enum", source=source))
                        continue
                    old_value = int(row["cannon"])
                    if cannon_delta != 0 and require_origin:
                        origin_error = self.effect_origin_rejection(origin_ref)
                        if origin_error:
                            rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
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
                            self.regions.append_log(
                                {
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
                                }
                            )
                            changes.append({
                                "region": row["name"], "field": field,
                                "label": REGION_FIELD_LABELS.get(field, field),
                                "old": old_value, "new": new_value,
                                "delta": 0, "reason": _clamp_reason, "clamped": True,
                            })
                        continue
                    self.regions.append_log(
                        {
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
                        }
                    )
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
                    rejections.append(RejectedItem(item={"region_id": region_id, "field": str(raw_field), "value": value}, reason=f"region_delta 引用非法地区字段 '{raw_field}'（地区 '{region_id}'）；"
                            f"合法字段：{_REGION_DIRECT_TUPLE + FISCAL_SCORE_FIELDS}", category="invalid_enum", source=source))
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
                    except (TypeError, ValueError) as exc:
                        rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=str(exc), category="invalid_enum", source=source))
                        continue

                # ── fiscal JSON 子字段（corruption 等）────────────────────────
                if field in FISCAL_SCORE_FIELDS:
                    fiscal: dict = _load_durable_json(row["fiscal"], default='{}')
                    old_value = fiscal.get(field, 50)
                    delta = value
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
                            rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                            continue
                    fiscal[field] = new_value
                    self.regions.update(
                        region_id, {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
                    )
                    self.regions.append_log(
                        {
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
                        }
                    )
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
                    delta = value
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
                    delta = value
                    new_value = max(0, int(old_value) + delta)
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                else:  # REGION_TEXT_FIELDS
                    text_value = str(value).strip()
                    # 判等/入库同一口径：结构化 id 比归一值，自由文本比原值（trim 只供判空）。
                    kept = text_value if field in _STRUCTURED_ID_FIELDS else str(value)
                    if field == "controlled_by":
                        if (
                            value is None
                            or not text_value
                            or text_value.lower() == "null"
                            or self.powers.row(text_value, fields="1") is None
                        ):
                            rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=f"region_delta 'controlled_by'（地区 '{region_id}'）"
                                    f"必须是 powers.id 中的非空真实势力 id：{value!r}", category="invalid_enum", source=source))
                            continue
                    if not text_value or kept == str(old_value):
                        continue
                    if require_origin:
                        origin_error = self.effect_origin_rejection(origin_ref)
                        if origin_error:
                            rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                            continue
                    # 结构化 id 字段归一后入库；自由文本（灾情/状况）原值入库。
                    stored_new = kept
                    log_delta = None
                if require_origin and field not in REGION_TEXT_FIELDS:
                    origin_error = self.effect_origin_rejection(origin_ref)
                    if origin_error:
                        rejections.append(RejectedItem(item={"region_id": region_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                        continue
                self.regions.update(region_id, {field: stored_new})
                self.regions.append_log(
                    {
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
                    }
                )
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
        return changes, rejections

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
                fiscal = _load_durable_json(row["fiscal"])
                for sub_field, sub_val in value.items():
                    if sub_field not in FISCAL_SCORE_FIELDS:
                        continue
                    old_sub = fiscal.get(sub_field, 0)
                    new_sub = int(sub_val)
                    if int(old_sub) == new_sub:
                        continue
                    fiscal[sub_field] = new_sub
                    self.regions.append_log(
                        {
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
                        }
                    )
                    out.append({
                        "region": row["name"], "field": sub_field,
                        "label": REGION_FIELD_LABELS.get(sub_field, sub_field),
                        "old": old_sub, "new": new_sub,
                        "delta": new_sub - int(old_sub), "reason": f"收复重置：{reason}",
                    })
                self.regions.update(
                    region_id, {"fiscal": json.dumps(fiscal, ensure_ascii=False)}
                )
                continue
            if raw_field == "controlled_by":
                continue
            if raw_field not in all_direct:
                continue
            old_val = row[raw_field]
            if raw_field in (REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS):
                # #648（ADR 0088）：population 已全线「人」；#1843 旧档万人换算已退役。
                new_val: object = int(value)
            else:
                new_val = str(value)
            if str(old_val) == str(new_val):
                continue
            self.regions.update(region_id, {raw_field: new_val})
            log_delta = (int(new_val) - int(old_val)) if raw_field in (REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS) else None
            self.regions.append_log(
                {
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
                }
            )
            out.append({
                "region": row["name"], "field": raw_field,
                "label": REGION_FIELD_LABELS.get(raw_field, raw_field),
                "old": old_val, "new": new_val,
                "delta": log_delta, "reason": f"收复重置：{reason}",
            })
        return out


    def army_rows(self, limit: int | None = None, danger_order: bool = False) -> List[sqlite3.Row]:
        # #173：danger 排序的欠饷月数归一改按引擎实扣应发 army_needed（替退役 maintenance_per_turn）。
        # army_needed 是 Python 公式（ceil + ming-only + 锚点，SQL 难复现），故 danger 排序在 Python 做；
        # 非 danger 路只按 theater,name 排序、不涉 army_needed，仍走 SQL ORDER BY/LIMIT（线上 gemini perf）。
        if not danger_order:
            return self.armies.ordered_rows(limit=limit)

        def _danger_key(r):
            # arrears 累计欠饷万两，按月应发归一成"欠饷月数*10"（截至 100），与各 0-100 短板相加。
            # 用浮点归一（排序键，不截断小数；线上 gemini）；arrears 虽 NOT NULL 仍 `or 0` 防御。
            from ming_sim.army_pay import army_needed
            pay = army_needed(r)
            arr = float(r["arrears"] or 0)
            arrears_norm = min(100.0, arr * 10.0 / pay) if pay > 0 else 0.0
            danger = (arrears_norm + (100 - int(r["supply"])) + (100 - int(r["morale"]))
                      + (100 - int(r["loyalty"])) + (100 - int(r["training"])))
            return (-danger, str(r["name"]))  # danger 降序、name 升序（同原 SQL ... DESC, name）

        rows = sorted(self.armies.rows(), key=_danger_key)
        return rows[:limit] if limit is not None else rows

    def army_payload(self, limit: int | None = None, danger_order: bool = False) -> List[Dict[str, object]]:
        from ming_sim.army_pay import army_needed
        payload: List[Dict[str, object]] = []
        for row in self.army_rows(limit=limit, danger_order=danger_order):
            pay = army_needed(row)
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
        from ming_sim.army_pay import army_needed
        return monthly_amount(sum(army_needed(r) for r in self.armies.rows()))

    def army_report(self, limit: int = 5) -> str:
        from ming_sim.army_pay import army_needed
        rows = self.army_rows(limit=limit, danger_order=True)
        if not rows:
            return "军队尚未建档。"
        total_manpower = self.conn.execute('SELECT SUM(manpower) AS total FROM armies', ()).fetchone()
        # #173：月饷总额按引擎实扣应发 army_needed 之和（替退役 maintenance_per_turn 之和）。
        total_pay = self.army_pay_theoretical_total()
        parts = []
        for row in rows:
            pay = army_needed(row)
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


    def army_roster(
        self,
        filter_names: Optional[List[str]] = None,
        qualitative_equipment: bool = False,
    ) -> str:
        """全军名册；大臣上下文可将火器装备以定性词呈现。"""
        from ming_sim.army_pay import army_needed
        rows = self.conn.execute("SELECT * FROM armies ORDER BY owner_power='ming' DESC, theater, name", ()).fetchall()
        if filter_names:
            rows = [r for r in rows if r["name"] in filter_names or r["id"] in filter_names]
        if not rows:
            return ""
        own: List[str] = []
        other: List[str] = []
        for row in rows:
            # #173：月饷取引擎实扣应发 army_needed（替退役 maintenance_per_turn）。全按月度，不除 3。
            monthly_pay = army_needed(row)
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
            source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        rejections: List[RejectedItem] = []
        changes: List[Dict[str, object]] = []
        for army_id, raw_changes in army_deltas.items():
            row = self.armies.row(army_id)
            if row is None:
                # ADR 0008 决定 1:LLM 幻觉军队 id = 逐项拒收留痕(missing_ref),不再
                # raise 崩整月;同信封好军队照落,坏一项不带走整批(原意「先建军」由
                # new_armies 段负责,此处只拒补兵/改属性的悬空引用)。
                rejections.append(RejectedItem(item={"army_id": army_id, "changes": raw_changes}, reason=f"army_delta 引用未入库军队 '{army_id}'（补兵/改属性落不了，先建军）", category="missing_ref", source=source))
                continue
            reason = str(raw_changes.get("reason") or raw_changes.get("原因") or event.title)
            # owner_power / 饷源字段唯一写口＝_apply_army_pay_source_delta →
            # transition_army_owner_power；主环对 _ARMY_PAY_SOURCE_DELTA_FIELDS 直接跳过。
            self._apply_army_pay_source_delta(
                state, event, edict_id, actor, row, raw_changes, reason, changes, rejections,
                origin_ref=origin_ref, require_origin=require_origin, source=source,
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
                # owner_power 经唯一 adapter，禁止 text 直写旁路
                if field == "owner_power":
                    current_row = self.armies.row(army_id)
                    if current_row is None:
                        continue
                    changes.extend(self.transition_army_owner_power(
                        state,
                        current_row,
                        str(value or "").strip(),
                        reason=reason,
                        actor=actor,
                        event_id=event.id,
                        edict_id=edict_id,
                        origin_ref=origin_ref,
                        require_origin=require_origin,
                        raw_item={"army_id": army_id, "changes": raw_changes},
                    ))
                    continue
                if field not in _ARMY_VALID_SET:
                    # ADR 0008 决定 1:LLM 引用非法军队字段 = 逐项拒收留痕(invalid_enum),
                    # 不再 print 静默跳;同军队的合法字段照落,坏一项不带走整批。
                    rejections.append(RejectedItem(item={"army_id": army_id, "field": str(raw_field), "value": value}, reason=f"army_delta 引用非法字段 '{raw_field}'", category="invalid_enum", source=source))
                    continue
                # ADR 0008 决定 1:数值字段的脏叶子值(null/字符串/float/bool)= LLM 脏数据,
                # 逐项拒收(invalid_enum),不让裸 int(value) 崩整月;bool 是 int 子类、float
                # 静默截断须显式拒(对称 S1/region)。text 字段走 str(),不在此判。
                if field not in ARMY_TEXT_FIELDS:
                    try:
                        if isinstance(value, bool) or isinstance(value, float):
                            raise ValueError("非整数 delta")
                        value = int(value)
                    except (TypeError, ValueError) as exc:
                        rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason=str(exc), category="invalid_enum", source=source))
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
                    delta = value
                    if delta < 0:
                        rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason="army_delta.arrears 不接受负值核销；真补饷须走 economy_moves", category="invalid_enum", source=source))
                        continue
                    if delta == 0:
                        continue
                    if (
                        str(row["owner_power"]) != "ming"
                        or bool(row["is_tusi"])
                        or bool(row["self_funded_pay"])
                    ):
                        rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason="army_delta.arrears 不接受自养/非明军加欠；双累加器恒为 0", category="invalid_enum", source=source))
                        continue
                    if int(row["manpower"] or 0) <= 0:
                        rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason="army_delta.arrears 不接受零兵军队加欠；兵力归零欠饷已核销", category="invalid_enum", source=source))
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
                        rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                        continue
                    self.armies.update(
                        army_id,
                        {
                            "province_pay_arrears": new_province,
                            "central_pay_arrears": new_central,
                        },
                    )
                    self.armies.append_log(
                        {
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
                        }
                    )
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
                    delta = value
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
                        effect_delta = net_delta
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
                        delta = value
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
                    delta = value
                    new_value = max(0, int(old_value) + delta)
                    actual_delta = new_value - int(old_value)
                    will_write_off_arrears = (
                        new_value == 0
                        and str(row["owner_power"]) == "ming"
                        and float(row["arrears"] or 0) > 1e-9
                    )
                    origin_error = self.effect_origin_rejection(origin_ref) if require_origin and (delta != 0 or will_write_off_arrears) else None
                    if origin_error:
                        rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                        continue
                    if will_write_off_arrears:
                        old_arrears = float(row["arrears"] or 0)
                        old_source = str(row["pay_source_region"] or "")
                        self.armies.append_log(
                            {
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
                            }
                        )
                        self.armies.update(
                            army_id,
                            {"province_pay_arrears": 0, "central_pay_arrears": 0},
                        )
                        self._reconcile_army_pay_source_region_container(old_source)
                        self._reconcile_central_army_pay_arrears_container()
                    if actual_delta == 0:
                        # #44：请求非 0 但 clamp 后无净变化（如减兵超过现有兵力→clamp 到 0）留一条
                        # delta=0 army_log（参照 region cannon delta=0 留痕，#14 不静默吞）；真 no-op
                        # （delta==0）无须留痕避噪。
                        if delta != 0:
                            self.armies.append_log(
                                {
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
                                }
                            )
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                elif field in ARMY_TEXT_FIELDS:
                    text_value = str(value).strip()
                    kept = text_value if field in _STRUCTURED_ID_FIELDS else str(value)
                    if not text_value or kept == str(old_value):
                        continue
                    # #659：station_region 非空须为已入库 regions.id；禁止从 station 文本反推。
                    if field == "station_region":
                        exists = self.regions.row(text_value, fields="1")
                        if exists is None:
                            rejections.append(RejectedItem(item={
                                    "army_id": army_id, "field": field, "value": value,
                                }, reason=f"army_delta.station_region 未入库 region_id：{text_value}", category="invalid_enum", source=source))
                            continue
                    stored_new = kept
                    log_delta = None
                else:
                    # field 已过 _ARMY_VALID_SET 校验，能落到此处=合法字段未被任一
                    # 分支处理=代码漏接(往 ARMY_*_FIELDS 加了字段却忘了 dispatch)。
                    # 按 ADR 0008 决定 1：代码 bug 响亮上抛触发回滚，不静默丢一个合法 delta。
                    raise RuntimeError(f"army_delta 合法字段 '{field}' 无落库分支（代码漏接）")
                origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
                if origin_error:
                    rejections.append(RejectedItem(item={"army_id": army_id, "field": field, "value": value}, reason=origin_error["reason"], category=origin_error["category"], source=source))
                    continue
                self.armies.update(army_id, {field: stored_new})
                if field == "manpower":
                    self._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                self.armies.append_log(
                    {
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
                    }
                )
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
        return changes, rejections

    def create_armies_from_extraction(
        self,
        state: GameState,
        new_armies: List[Dict[str, object]],
        actor: str = "档房",
        commit: bool = True,
        origin_ref: str = "",
        require_origin: bool = False,
            source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        """据 extractor 输出建新军队。同 id/name 已存在 → 把 manpower 当扩军增量。owner_power 必须是已知 power。"""
        rejections: List[RejectedItem] = []
        valid_powers = {r["id"] for r in self.powers.ids()}
        created: List[Dict[str, object]] = []
        for raw in new_armies:
            if not isinstance(raw, dict):
                # 不再静默丢：留拒收记录（season 路本就被 sanitize_delta_shape 挡在
                # S6;issue 路历史即静默,容忍不升级——issue_strict=False,cmr S2 r1）。
                rejections.append(RejectedItem(item={"raw_value": raw}, reason=f"new_armies 含非 dict 项：{raw!r}", category="invalid_enum", source=source))
                continue
            # 规范键：复用 ARMY_FIELD_ALIASES（兼容中文）
            from ming_sim.constants import ARMY_FIELD_ALIASES as _AA
            item = {_AA.get(str(k).strip(), str(k).strip()): v for k, v in raw.items()}
            aid = str(item.get("id") or "").strip()
            if not aid:
                # ADR 0008 决定 1:缺 id = LLM 脏数据,逐项拒收留痕(invalid_enum),
                # 不再 raise 崩整月;同信封好军照建,坏一项不带走整批。
                rejections.append(RejectedItem(item=raw, reason="new_armies 缺 id（无法建军）", category="invalid_enum", source=source))
                continue
            owner = str(item.get("owner_power") or "ming").strip() or "ming"
            if owner not in valid_powers:
                # ADR 0008 决定 1:owner_power 幻觉 = 逐项拒收留痕(hallucinated_id)。
                rejections.append(RejectedItem(item=raw, reason=f"new_armies owner_power '{owner}' 不在 powers 表（无法建军 {aid}）", category="hallucinated_id", source=source))
                continue
            name = str(item.get("name") or aid)
            # 查重：同 id 或 同 name → 转 manpower 扩军增量
            existing = self.conn.execute('SELECT id, name FROM armies WHERE id = ? OR name = ?', (aid, name)).fetchone()
            if existing is not None:
                manpower = item.get("manpower")
                if manpower is None:
                    # ADR 0008 决定 1:命中已有军但无扩军增量 = 无意义项,逐项拒收留痕。
                    rejections.append(RejectedItem(item=raw, reason=f"new_armies 重复 id/name '{aid}' 且无 manpower（无扩军增量）", category="invalid_enum", source=source))
                    continue
                try:
                    if isinstance(manpower, (bool, float)):
                        raise ValueError("非整数")
                    delta = int(manpower)
                except (TypeError, ValueError) as exc:
                    # ADR 0008 决定 1:扩军增量非整数 = LLM 脏数据,逐项拒收留痕。
                    rejections.append(RejectedItem(item=raw, reason=str(exc), category="invalid_enum", source=source))
                    continue
                if delta == 0:
                    continue
                reason = str(item.get("reason") or item.get("status") or "扩军")
                pseudo_event = type("E", (), {"id": "season", "title": reason})()
                merge_results, merge_results_rejections = self.apply_army_deltas(
                    state,
                    pseudo_event,
                    None,
                    actor,
                    {existing["id"]: {"manpower": delta, "reason": reason}},
                    commit=False, origin_ref=origin_ref, require_origin=require_origin,
                source=source)
                if merge_results_rejections:
                    rejections.extend(merge_results_rejections)
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
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                rejections.append(RejectedItem(item=raw, reason=f"new_armies '{aid}' 缺/非法 manpower（无法建军）：{exc}", category="invalid_enum", source=source))
                continue
            # #173：maintenance_per_turn 列已删（月饷由 army_needed 按兵力派生）；LLM 若仍塞维护费/
            # 军费，经 ARMY_FIELD_ALIASES 已无该别名 → 当未知键忽略，不入库、不影响建军。
            # 可选数值字段「在场即须合法」（cmr S2 r1 codex P1）：在场脏值静默走默认
            # = 伪造军备（morale "高"→50、cannon "几门"→0）。None 视为缺省（LLM 习惯
            # 用 null 表「无」,sanitize_delta_shape 亦容忍 null 叶）；其余非整拒该项。
            # 守门集从字段表派生（cmr S2 r2,2/2:硬列漏 equipment/mobility/loyalty）
            # ——ARMY_SCORE_FIELDS 全量已含 arrears;字段表变守门自动跟。
            _dirty_reason = None
            for _f in ARMY_SCORE_FIELDS:
                _v = item.get(_f)
                if _f in item and _v is not None:
                    if isinstance(_v, (bool, float)):
                        _dirty_reason = (
                            f"new_armies '{aid}' 可选字段 '{_f}' 值非整数："
                            f"{_v!r}（在场即须合法，缺省才走默认）"
                        )
                        break
                    try:
                        item[_f] = int(_v)
                    except (TypeError, ValueError) as exc:
                        _dirty_reason = str(exc)
                        break
            if _dirty_reason is not None:
                rejections.append(RejectedItem(item=raw, reason=_dirty_reason, category="invalid_enum", source=source))
                continue
            # 上方已拒在场脏可选字段；此处只读缺省/已验整数，不再 except→默认洗白。
            def _score(field: str, default: int = 50) -> int:
                return max(0, min(100, item.get(field, default)))
            def _cannon() -> int:
                # 随军大炮=门数 clamp 0-12；LLM 给非 int(如"几门")兜底 0，不让 int() 抛崩建军（PR codex）
                return max(0, min(12, item.get("cannon_equipment", 0) or 0))
            def _arrears_init() -> int:
                # arrears 单位=累计欠饷万两，无上限；新军默认 0
                return max(0, item.get("arrears", 0))
            initial_arrears = _arrears_init()
            if initial_arrears > 0:
                rejections.append(RejectedItem(item=raw, reason=f"new_armies '{aid}' 新军初始欠饷必须为 0；"
                        "外生加欠须走 army_delta.arrears 正值", category="invalid_enum", source=source))
                continue
            # #659：结构化实际驻地可选；非空须为已入库 region_id，缺省 "" 不 fail-loud。
            station_region = str(item.get("station_region") or "").strip()
            if station_region:
                exists = self.regions.row(station_region, fields="1")
                if exists is None:
                    rejections.append(RejectedItem(item=raw, reason=f"new_armies '{aid}' station_region 未入库 region_id："
                            f"{station_region}", category="invalid_enum", source=source))
                    continue
            pay_source_region = ""
            province_pay_share = central_pay_share = 0.0
            province_pay_arrears = central_pay_arrears = 0.0
            is_tusi = self_funded_pay = False
            stored_arrears = float(initial_arrears)
            try:
                pay_source_region = str(item.get("pay_source_region") or "").strip()
                province_pay_share = _coerce_pay_source_float(item.get("province_pay_share"))
                central_pay_share = _coerce_pay_source_float(item.get("central_pay_share"))
                is_tusi = _coerce_bool_flag(item.get("is_tusi"))
                self_funded_pay = _coerce_bool_flag(item.get("self_funded_pay"))
                exempt = owner != "ming" or is_tusi or self_funded_pay
                if exempt:
                    stored_arrears = province_pay_arrears = central_pay_arrears = 0.0
                else:
                    province_pay_arrears = initial_arrears * province_pay_share
                    central_pay_arrears = initial_arrears * central_pay_share
                    stored_arrears = province_pay_arrears + central_pay_arrears
                self._validate_pay_source_values(
                    aid, owner, pay_source_region, province_pay_share, central_pay_share,
                    is_tusi, self_funded_pay, province_pay_arrears, central_pay_arrears,
                )
                if pay_source_region:
                    self._require_valid_pay_source_region(aid, pay_source_region)
            except DeclarationDataError as exc:
                rejections.append(RejectedItem(item=raw, reason=f"new_armies '{aid}' 饷源字段非法：{exc}", category="invalid_enum", source=source))
                continue
            origin_error = self.effect_origin_rejection(origin_ref) if require_origin else None
            if origin_error:
                rejections.append(RejectedItem(item=raw, reason=origin_error["reason"], category=origin_error["category"], source=source))
                continue
            commander = str(item.get("commander") or "")
            row = {
                'id': aid,
                'name': name,
                'station': str(item.get("station") or ""),
                'station_region': station_region,
                'theater': str(item.get("theater") or ""),
                'commander': commander,
                'controller': str(item.get("controller") or commander),
                'troop_type': str(item.get("troop_type") or ""),
                'manpower': max(0, manpower),
                'supply': _score("supply"),
                'morale': _score("morale"),
                'training': _score("training"),
                'equipment': _score("equipment"),
                'province_pay_arrears': province_pay_arrears,
                'central_pay_arrears': central_pay_arrears,
                'pay_source_region': pay_source_region,
                'province_pay_share': province_pay_share,
                'central_pay_share': central_pay_share,
                'is_tusi': 1 if is_tusi else 0,
                'self_funded_pay': 1 if self_funded_pay else 0,
                'mobility': _score("mobility"),
                'loyalty': _score("loyalty"),
                'firearm_equipment': _score("firearm_equipment", 0),
                'cannon_equipment': _cannon(),
                'salary_rate': _coerce_new_salary_rate(item.get("salary_rate")),
                'status': str(item.get("status") or "新立"),
                'owner_power': owner,
            }
            try:
                self.armies.insert(row)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"new_armies INSERT 失败 '{aid}'：{exc}") from exc
            self._reconcile_army_pay_source_region_container(pay_source_region)
            self._reconcile_central_army_pay_arrears_container()
            self.assert_army_pay_source_container_conservation()
            reason = str(item.get("reason") or item.get("status") or "新立军队")
            self.armies.append_log(
                {
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
                    "edict_id": None,
                    "actor": actor,
                    "origin_ref": origin_ref,
                }
            )
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
        return created, rejections

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
            raise DeclarationDataError(f"建筑 category 非法 '{category}'，白名单 {BUILDING_CATEGORIES}")
        if output_metric not in BUILDING_OUTPUT_METRICS:
            raise DeclarationDataError(f"建筑 output_metric 非法 '{output_metric}'，白名单 {BUILDING_OUTPUT_METRICS}")
        if self.regions.row(region_id, fields="1") is None:
            raise DeclarationDataError(f"建筑 region_id 引用未入库地区 '{region_id}'")
        building_id = self.buildings.insert_new(
            {
                "region_id": region_id,
                "name": name if name.strip() else "无名建筑",
                "category": category,
                "level": max(1, min(5, int(level))),
                "condition": max(0, min(100, int(condition))),
                "maintenance": max(0, int(maintenance)),
                "risk": max(0, min(100, int(risk))),
                "output_metric": output_metric,
                "output_amount": max(0, int(output_amount)),
                "status": status if status.strip() else "新立，尚在筹建。",
                "origin": origin,
                "created_turn": state.turn,
            }
        )
        self.buildings.append_log(
            {
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "building_id": building_id,
                "field": "create",
                "old_value": "",
                "new_value": str(name or ""),
                "delta": None,
                "reason": "诏书新立建筑",
                "actor": "档房",
                "origin_ref": origin_ref,
            }
        )
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
        row = self.buildings.row(building_id, fields="name")
        if row is None:
            return False
        self.buildings.append_log(
            {
                "turn": state.turn,
                "year": state.year,
                "period": state.period,
                "building_id": building_id,
                "field": "remove",
                "old_value": str(row["name"]),
                "new_value": "",
                "delta": None,
                "reason": str(reason or "")
                if str(reason or "").strip()
                else "建筑废止",
                "actor": "档房",
                "origin_ref": origin_ref,
            }
        )
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
        source: Provenance = Provenance.system_simulation,
    ) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
        """改既有建筑；不可执行字段逐项返回 canonical 拒收。"""
        changes: List[Dict[str, object]] = []
        rejected: List[RejectedItem] = []
        valid_fields = set(BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS + BUILDING_TEXT_FIELDS)
        for building_id, raw_changes in building_deltas.items():
            row = self.buildings.row(building_id)
            if row is None:
                rejected.append(RejectedItem(item={"entity_id": building_id, "raw_value": raw_changes}, reason="建筑未入库", category="missing_ref", source=source))
                continue
            # Free prose building delta reason: raw bytes (#1834 F16).
            raw_reason = str(raw_changes.get("reason") or "")
            reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")
            for field, value in raw_changes.items():
                if field == "reason":
                    continue
                if field not in valid_fields:
                    rejected.append(RejectedItem(item={"entity_id": building_id, "field": field, "raw_value": value}, reason="建筑字段不可执行", category="invalid_enum", source=source))
                    continue
                if field in BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS:
                    try:
                        value = strict_int(value, accept_numeric_strings=True)
                    except (TypeError, ValueError):
                        rejected.append(RejectedItem(item={"entity_id": building_id, "field": field, "raw_value": value}, reason="建筑数值非整数", category="invalid_enum", source=source))
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
                        rejected.append(RejectedItem(item={"entity_id": building_id, "field": field, "raw_value": value}, reason="建筑产出指标非法", category="invalid_enum", source=source))
                        continue
                    if text_value == str(old_value):
                        continue
                    stored_new = text_value
                    log_delta = None
                elif field in BUILDING_TEXT_FIELDS:
                    text_value = str(value).strip()
                    if not text_value or str(value) == str(old_value):
                        continue
                    stored_new = str(value)
                    log_delta = None
                else:
                    print(f"[WARN] building_delta 未处理字段 '{field}' → 跳过")
                    continue
                self.buildings.update(building_id, {field: stored_new})
                self.buildings.append_log(
                    {
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
                    }
                )
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
        return changes, rejected

    def buildings_report(self, region_id: str = "", qualitative: bool = False) -> str:
        """月末奏报 / web 用建筑盘面摘要。region_id 为空取全国。"""
        if region_id:
            rows = self.buildings.region_rows(region_id)
        else:
            rows = self.buildings.rows()
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
            rows = self.buildings.region_rows(region_id)
        else:
            rows = self.buildings.rows()
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


    def adjust_factions(self, deltas: Dict[str, object], commit: bool = True, source: Provenance = Provenance.system_simulation) -> List[RejectedItem]:
        """逐项落库；查无此派系名 → missing_ref 逐项拒收留痕（ADR 0008 决定 1，#14/#63
        死法 3）。入参经 _apply_faction_dict 预清洗（坏值已在那层拒），此处只余未知名一类。
        返回 RejectedItem 列表，由调用方收进拒收报告。

        #9 cmr R5 finding#1：白名单朝堂派系（_LEVERAGE_FACTIONS）的 leverage 列由「offset+官职和」
        派生、结算尾 recompute_all_faction_leverage() 绝对幂等兜底。若此处对白名单直写 leverage 列，
        会被该 reconcile 抹回公式值 → LLM「影响力变化」静默蒸发、DB 与玩家可见「已落」分叉。
        故白名单的 leverage 增量改注入 **leverage_offset**（无形政治基线变动），再 recompute_faction_leverage
        立即令 leverage 体现（offset+官职和，含本次增量）；结算尾 reconcile 确认同值、不抹。
        offset 不 clamp（leverage 读时 clamp）。非白名单（宗室等）维持原样直写 leverage 列
        （reconcile 不碰非白名单）。satisfaction 两者都照旧 clamp 直写。"""
        rejected: List[RejectedItem] = []
        for faction, val in deltas.items():
            if isinstance(val, dict):
                sat_d = int(val.get("satisfaction") or 0)
                lev_d = int(val.get("leverage") or 0)
            else:
                sat_d = int(val)  # type: ignore[arg-type]
                lev_d = 0
            if sat_d == 0 and lev_d == 0:
                continue
            row = self.conn.execute('SELECT satisfaction, leverage FROM factions WHERE name = ?', (faction,)).fetchone()
            if not row:
                rejected.append(RejectedItem(item={faction: val}, reason=f"faction_delta 查无此派系「{faction}」（未入 factions 表）", category="missing_ref", source=source))
                continue
            new_sat = max(0, min(100, int(row["satisfaction"]) + sat_d))
            if faction in _LEVERAGE_FACTIONS:
                # 白名单：leverage 增量注入 offset（不被 reconcile 抹），satisfaction 仍直写。
                self.conn.execute(
                    'UPDATE factions SET satisfaction = ?, leverage_offset = '
                    'leverage_offset + ? WHERE name = ?',
                    (new_sat, lev_d, faction),
                )
                # 立即令 leverage 体现 offset 变化（含本次增量）；reconcile 后确认同值。
                self.recompute_faction_leverage(faction)
            else:
                # 非白名单：维持原样直写 leverage 列（reconcile 不碰非白名单）。
                new_lev = max(0, min(100, int(row["leverage"]) + lev_d))
                self.conn.execute(
                    'UPDATE factions SET satisfaction = ?, leverage = ? WHERE name = '
                    '?',
                    (new_sat, new_lev, faction),
                )
        if commit:
            self.conn.commit()
        return rejected


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
        # 与 previous_turn_summary / get_turn_report 同口径：非空才算有报
        row = self.conn.execute(
            'SELECT year, period, report FROM turn_reports WHERE turn = ?',
            (previous_turn,),
        ).fetchone()
        if row is not None and (row["report"] or ""):
            return reign_period_label(int(row["year"]), int(row["period"]))
        # #1843 reopen：无有效邸报则真空；旧 turn_logs 回落已删。
        return ""


    def build_chat_projection(self, minister_name: str, night_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """当前召对夜的 turn-identified 投影：user/minister 逐条带 chat_turn_id。

        单一真源：以 chat_messages（与 load_all_chat_history 同基）为骨架，join
        chat_turns 打 turn 身份。前端据此一投影渲染。
        """
        if night_id is None:
            open_night = self.conn.execute(
                "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1",
                (),
            ).fetchone()
            night_id = int(open_night["id"]) if open_night else 0
        turns = self.conn.execute(
            'SELECT id, user_message_id, minister_message_id FROM chat_turns WHERE '
            'minister_name=? AND night_id=?',
            (minister_name, int(night_id)),
        ).fetchall()
        message_ids = [
            int(message_id)
            for turn in turns
            for message_id in (turn["user_message_id"], turn["minister_message_id"])
            if message_id is not None
        ]
        if message_ids:
            msgs = self.chat_messages.rows_by_ids(message_ids)
        else:
            msgs = []
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


    # ----- chat_turns（本回合召对撤回）-----

    def _row_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def _json_dump_row(self, row: Dict[str, Any]) -> str:
        return json.dumps(row, ensure_ascii=False, sort_keys=True)


    def capture_chat_rollback_snapshot(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """截取召对前后的可回滚业务表状态，用于撤回时做差异还原。"""
        return {table: self._snapshot_table(table) for table in self._rollback_stores}


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
        rows = self.reign.list_in_flight_chat_turns()
        interrupted: List[Dict[str, Any]] = []
        with self.conn:
            for row in rows:
                ctid = int(row["id"])
                uid = row.get("user_message_id")
                # #505 finding5：崩溃窗若 agent.run 已写入 Agno runs 而回话未 persist，
                # 截回本轮起点（agno_runs_before），避免 retry 时上下文双倍——与
                # fail_chat_turn/undo 同一 agno 截断缝。非删账：只丢没落完那半句的 LLM 工作态。
                self.reign._truncate_agno_runs_in_tx(
                    str(row.get("agno_session_id") or ""),
                    int(row.get("agno_runs_before") or 0),
                )
                if uid:
                    self.reign.set_chat_turn_status("interrupted", ctid)
                    qrow = self.chat_messages.row(int(uid), fields="content")
                    interrupted.append({
                        "chat_turn_id": ctid,
                        "minister_name": str(row["minister_name"]),
                        "turn": int(row["turn"]),
                        "question": str(qrow["content"]) if qrow is not None else "",
                    })
                else:
                    self.reign.set_chat_turn_status("failed", ctid)
        return interrupted


    def restore_interrupted_after_failed_retry(self, chat_turn_id: int) -> List[int]:
        """重试再失败的善后（#505 finding1）：回滚本次重试在 session.chat 落下的副作用
        （dismiss 账 / 拟旨 / 任免候选等，已由调用方 record_chat_turn_rollback_diffs 记为
        rollback items）+ 截断本轮 agno runs，把重入生成态的轮翻回 'interrupted' 保持可再
        重试——但**绝不删问话/回话**（恢复路径永不删账，AC3/AC4）。

        与 fail_chat_turn 同 rollback-items + agno 截断缝，差异仅三点：不删 chat_messages、
        终态=interrupted（非 failed）、消费后删本轮 rollback_items（轮继续存活，防将来重试
        成功→撤回时重放已还原的副作用 = 双还原）。仅动重入生成态且尚无回话的轮（幂等 / CAS 安全）。
        """
        row = self.reign.row(int(chat_turn_id))
        if row is None:
            return []
        turn_row = self._row_dict(row)
        if turn_row["status"] != "generating" or turn_row.get("minister_message_id"):
            return []
        items = self.reign.chat_turn_rollback_rows(int(chat_turn_id))
        restored_pending_action_ids: List[int] = []
        with self.conn:
            self.character_knowledge.delete_sources_matching(f"%:chat_turn:{int(chat_turn_id)}", commit=False)
            self.reign.delete_chat_turn_ledger(int(chat_turn_id), int(chat_turn_id))
            # 空 undone 消息集：只还原业务副作用，一句问话/回话都不删。
            restored_pending_action_ids = self._restore_chat_rollback_items_in_tx(items, [])
            self.conn.execute(
                'DELETE FROM chat_turn_rollback_items WHERE chat_turn_id = ?',
                (int(chat_turn_id),),
            )
            self.reign._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )
            self.reign.set_chat_turn_status("interrupted", int(chat_turn_id))
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
        # 首次写入（含 allocate_night_seq）前取归属：外层 BEGIN/atomic 不抢提交；
        # 无外层时本方法落盘（避免 close 回滚吞 generating 孤儿轮）。
        owns = connection_owns_transaction(self.conn)
        seq = int(night_seq) if night_seq is not None else (
            self.reign.allocate_night_seq(nid) if nid > 0 else 0
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
        if owns:
            self.conn.commit()
        return int(cur.lastrowid)


    def fail_chat_turn(self, chat_turn_id: int) -> List[int]:
        """Mark an incomplete audience turn failed and remove its partial user-visible writes."""
        row = self.reign.row(int(chat_turn_id))
        if row is None:
            return []
        turn_row = self._row_dict(row)
        if turn_row["status"] not in {"active", "generating"}:
            self.reign.set_chat_turn_status("failed", int(chat_turn_id))
            self.conn.commit()
            return []
        items = self.reign.chat_turn_rollback_rows(int(chat_turn_id))
        message_ids = [
            int(mid)
            for mid in (turn_row.get("user_message_id"), turn_row.get("minister_message_id"))
            if mid
        ]
        restored_pending_action_ids: List[int] = []
        with self.conn:
            self.character_knowledge.delete_sources_matching(f"%:chat_turn:{int(chat_turn_id)}", commit=False)
            # Same family as undo_chat_turn: drop enter/exit placeholders bound to this
            # turn so failed attach/exit cannot freeze night presence or scene pads (T16/C11).
            self.reign.delete_chat_turn_ledger(int(chat_turn_id), int(chat_turn_id))
            restored_pending_action_ids = self._restore_chat_rollback_items_in_tx(items, message_ids)
            if message_ids:
                self.chat_messages.delete_ids(message_ids)
            self.reign.set_chat_turn_status("failed", int(chat_turn_id))
            self.reign._truncate_agno_runs_in_tx(
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

    def persist_minister_reply(
        self,
        minister_name: str,
        turn: int,
        content: str,
        chat_turn_id: int,
    ) -> int:
        """**一个事务**内插入大臣回话、链接到 turn 并升为 active，返回 message_id。

        消息插入、turn 链接和状态升级同成同败，避免留下未关联的持久回话。
        status 升级同 update_chat_turn_messages（#498 挂夜轮以 generating 起笔，回话落库后升 active）——
        本函数是 update_chat_turn_messages(minister_message_id=...) 的原子替代，须同做该升级。
        """
        with self.conn:  # 事务：成功提交、异常回滚（插入的回话一并撤销）；外层 atomic 内 commit 暂停
            message_id = self.chat_messages.insert(
                minister_name=minister_name,
                turn=int(turn),
                content=content,
                role='minister',
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


    # ----- #501 召对转译待补状态（沿用 extract_status）-----


    def can_undo_last_chat_turn(self, minister_name: str, turn: int) -> bool:
        row = self.reign.get_last_active_chat_turn(minister_name, turn)
        if row is None:
            return False
        if not row.get("user_message_id") or not row.get("minister_message_id"):
            return False
        return self.reign.is_global_last_active_chat_turn(int(row["id"]))


    def _restore_chat_rollback_items_in_tx(
        self, items: Iterable[sqlite3.Row], undone_message_ids: Iterable[int],
        *, retract_context: bool = False,
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
                    # #1890：只在**撤回**上下文里，本轮首次落下的交办改由统一
                    # 身份作废（voided 墓碑），不在这条删行路上再写一遍同一事实。
                    # 判据与 void_pending_actions_for_chat_turn 逐字相同：同源轮
                    # 且仍 pending；owned 但已非 pending 的行不在作废范围内，
                    # 必须照旧删掉（否则这里跳过、那边又不作废，多出一条
                    # 「既不删也不废」的新路径）。
                    #
                    # 失败/重试善后（fail_chat_turn、restore_interrupted_after_
                    # failed_retry）走同一核但不是撤回：那里的暂存必须删掉，
                    # 轮才可再试；把它们一并作废等于让可重试轮永久出局。
                    if retract_context and self.dossiers.is_pending_owned_by_turn(
                        target_id, int(item["chat_turn_id"] or 0),
                    ):
                        continue
                    self._discard_deleted_directive_forecast(target_id)
                self._delete_row_in_tx(table, target_id)
            elif strategy in {"restore_row", "restore_deleted_row"}:
                before_row = _load_durable_json(item["before_json"])
                if table == "pending_actions" and before_row.get("kind") == "directive":
                    pending_id = int(before_row["id"])
                    restored_directive_ids.add(pending_id)
                    before_version = int(before_row.get("version") or 1)
                    current = self.dossiers.directive_version(pending_id)
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
                        brief = self.character_knowledge.brief_origin_message_ids(
                            int(target_id)
                        )
                        # 已持久 brief 源身份：响亮解码（#1897 E1）。
                        current = self._load_durable_origin_message_ids(
                            None if brief is None else brief[0],
                            surface=f"secret_order_briefs#{int(target_id)}.origin_chat_message_ids",
                        )
                        pins = [pin for pin in current if int(pin) not in undone]
                    else:
                        pins = self._load_durable_origin_message_ids(
                            raw_pins,
                            surface=f"rollback.secret_orders#{int(target_id)}.brief_pins",
                        )
                    self.character_knowledge.restore_secret_order_brief_projection(
                        int(target_id), self._coerce_positive_message_ids(pins),
                    )
            else:
                raise ValueError(f"不支持的回滚策略：{strategy}")
        if not restored_directive_ids:
            return []
        return self.dossiers.night_approved_directive_ids(restored_directive_ids)

    def undo_chat_turn(self, chat_turn_id: int) -> Dict[str, Any]:
        row = self.reign.row(int(chat_turn_id))
        if row is None:
            raise DeclarationDataError("召对轮次不存在。")
        turn_row = self._row_dict(row)
        if turn_row["status"] != "active":
            raise DeclarationDataError("该召对已经撤回或不可撤回。")
        if not self.reign.is_global_last_active_chat_turn(int(chat_turn_id)):
            raise DeclarationDataError("只能撤回全局最后一轮召对。")
        # #506 封窗：收夜/颁诏封住撤回窗口（ADR 0038）。该轮所在夜一旦进入 closing/closed，
        # 撤回不跨已收的夜——已应允暂存已在收夜提交、账已成史，此后反悔按 ADR 0006 是新的
        # 游戏内命令而非 undo。phase 闸只守颁诏结算相位、守不住「夜已收但相位未变」的窗口。
        night_id = int(turn_row.get("night_id") or 0)
        if night_id > 0:
            nrow = self.conn.execute(
                'SELECT status FROM audience_nights WHERE id = ?',
                (night_id,),
            ).fetchone()
            if nrow is not None and str(nrow["status"] or "") in {"closing", "closed"}:
                raise DeclarationDataError("本夜已收（或颁诏封窗），撤回窗口已关，不能撤回该轮召对。")
        items = self.reign.chat_turn_rollback_rows(int(chat_turn_id))
        message_ids = [
            int(mid)
            for mid in (turn_row.get("user_message_id"), turn_row.get("minister_message_id"))
            if mid
        ]
        # 颁诏 owning transaction 的 commit_pending_actions 可能在召对 diff 已记录之后
        # 才生成 turn_directives(status='draft')，因此那类行不会进入 rollback_items
        # （召对期直接更新的 turn_directives 仍会被快照捕获并还原）。
        # 删除前，取本轮该回收的拟旨 draft 行（BUG 3：旧实现按 (turn,actor)
        # 删除，会连同同 actor 同回合的无关 draft 一起删掉）。
        #
        # #1890：判据改成按身份列读，不再扫 rollback_items 反查「本轮碰过哪些
        # 交办」——那道回溯链是票面与陛下所拒的「回头去找具体哪句话」。两类行
        # 都由 source_chat_turn_id 认出：
        #   a) 本轮首次落下的交办：身份就是本轮 → 直接按列取。
        #   b) 前轮已存在、本轮补充改稿的交办：身份仍是前轮的，扫不到；但它
        #      正是票面要求「以前像恢复该轮对先前对象的变更」的那一类，逆转
        #      归前像日志负责（下方 restore 分支），其 committed draft 仍需回收，
        #      故对身份列取不到的行保留一次窄口径扫描（只看前轮身份的行）。
        draft_ids_to_delete: List[int] = []

        def _reclaim(pa_ids: Sequence[object]) -> None:
            """回收这些交办各自落下的 draft 拟旨行。

            #1890 / ADR 0054：按 turn_directives.source_pending_action_id 从新指旧
            读，不再读 pending_actions.committed_directive_id（先落实体反指后生）。
            """
            ids: List[int] = []
            for raw in pa_ids:
                pid = int(raw)  # type: ignore[arg-type]
                if pid > 0:
                    ids.append(pid)
            if not ids:
                return
            draft_ids_to_delete.extend(
                self.issues.directive_ids_for_pending_actions(ids)
            )

        # a) 本轮首次落下的交办：按身份列直取，不经回溯日志。
        _reclaim(
            [
                int(row["id"])
                for row in self.conn.execute(
                    'SELECT id FROM pending_actions WHERE source_chat_turn_id = ? ORDER BY id',
                    (int(chat_turn_id),),
                ).fetchall()
            ]
        )

        # b) 前轮身份、本轮改稿的行：扫日志只为取这些行的 id（不改前像语义）。
        prior_ids: List[object] = []
        for item in items:
            if str(item["target_table"]) != "pending_actions":
                continue
            after_data = _load_durable_json(item["after_json"])
            before_data = parse_engine_payload_json(item["before_json"])
            pa_id = after_data.get("id")
            if pa_id is None:
                pa_id = before_data.get("id")
            if pa_id is None:
                continue
            owner = self.dossiers.row(
                int(pa_id), fields="source_chat_turn_id", table="pending_actions"
            )
            # 本轮身份的行已在 a) 收过，不重复；只补身份属前轮的那些。
            if owner is None or int(owner["source_chat_turn_id"] or 0) == int(chat_turn_id):
                continue
            prior_ids.append(pa_id)
        _reclaim(prior_ids)
        with self.conn:
            self.character_knowledge.delete_sources_matching(f"%:chat_turn:{int(chat_turn_id)}", commit=False)
            # #634 撤回联动（ADR 0038 白名单③）：删该轮源绑定的召对边事件；undone 轮
            # 天然出判官窗口（status != active），水位随逐轮标记失效自动回退。
            self.person_logs.delete_relation_edge_events_for_chat_turn(chat_turn_id)
            # #506：删该轮所产故事账——抽取账走 source_chat_turn_id、该轮 attach 创建的
            # 入殿等口令账走 origin_chat_turn_id。晚落的补跑抽取账也按 source 删（不受
            # 前像快照时刻限制）；开夜/员额/收夜等框架账 origin==0、不随本轮撤。撤回后
            # 「按夜取数（账+在场）与该轮未发生等价」（ADR 0038）。
            self.reign.delete_chat_turn_ledger(int(chat_turn_id), int(chat_turn_id))
            # 背书是该轮已说出口对话的派生事实；撤回来源轮时须同步失效。
            self.conn.execute(
                'DELETE FROM decree_dossier_endorsements WHERE source_chat_turn_id = ?',
                (int(chat_turn_id),),
            )
            restored_pending_action_ids = self._restore_chat_rollback_items_in_tx(
                items, message_ids, retract_context=True,
            )
            # #1890：按统一身份整轮作废本轮的交办暂存。放在前像还原之后——
            # 还原可能把本轮改动过的「前轮已存在」暂存恢复成 pending，那些行的
            # source_chat_turn_id 是前轮的，不在本轮作废范围内（判据只有一列）。
            # 本轮首次落下的交办则在此盖 voided 墓碑，迟到的写入/补跑不会复活它。
            voided_pending_action_ids = self.void_pending_actions_for_chat_turn(
                chat_turn_id,
            )
            # 只精确删除本召对 commit 出来的 draft 行（保留同 actor 的无关 draft）。
            for draft_id in dict.fromkeys(draft_ids_to_delete):
                self.conn.execute(
                    "DELETE FROM turn_directives WHERE id=? AND status='draft'",
                    (int(draft_id),),
                )
            if message_ids:
                self.chat_messages.delete_ids(message_ids)
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
            self.reign._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )
        # P1-2：报告本召对删除了哪些 committed draft（拟诏已 commit 的对话草案行）。
        # 上层据此让已生成的诏书正文（last_decree）失效——否则若另有 draft 残留，玩家仍能
        # 原样颁出含被撤回指令的陈旧诏书。无删除则为空，普通撤回不触发上层清稿。
        turn_row["deleted_committed_draft_ids"] = list(dict.fromkeys(draft_ids_to_delete))
        turn_row["restored_pending_action_ids"] = restored_pending_action_ids
        # #1890：本轮被作废的交办暂存 id（按 source_chat_turn_id 整轮作废所得）。
        turn_row["voided_pending_action_ids"] = list(voided_pending_action_ids)
        return turn_row

    def save_turn_report(
        self, state: GameState, report: str,
        public_body: Optional[str] = None,
        *,
        attendant_message: str = "",
        title: str = "",
        commit: bool = True,
    ) -> None:
        """每回合月末奏报单独存档（turn_reports）。

        ``report`` 是呈现正文；``public_body`` 可独立提供公开版本。
        来源记录由原账本持有，本档案不复制来源、不生成权限快照。
        ``attendant_message``（#671）是王承恩独立递话，与官方 report 分栏同原子写。
        """
        public_report = str((report if public_body is None else public_body) or "")
        self.turn_reports.upsert(
            turn=state.turn,
            year=state.year,
            period=state.period,
            report=public_report,
            attendant_message=str(attendant_message or ""),
            title=str(title or ""),
        )
        if commit:
            self.conn.commit()

    def previous_turn_attendant_message(self, state: GameState) -> str:
        """#671：状态口投影——仅上一已完成月的独立递话。"""
        previous_turn = int(state.turn) - 1
        if previous_turn < 0:
            return ""
        return self.turn_reports.attendant_message(previous_turn)


    # ── 结局总结 ──


    def list_monthly_archives(self) -> List[Dict[str, object]]:
        """每回合至多一条月档；召对场次绝不扩增月度时间线。"""
        rows = self.conn.execute(
            """
            SELECT turn, MAX(year) AS year, MAX(period) AS period,
                   MAX(has_report) AS has_report,
                   MAX(has_attendant) AS has_attendant,
                   MAX(has_directive) AS has_directive
            FROM (
                SELECT turn, year, period,
                       CASE WHEN length(trim(COALESCE(report, ''), char(9)||char(10)||char(13)||' ')) > 0 THEN 1 ELSE 0 END AS has_report,
                       CASE WHEN length(trim(COALESCE(attendant_message, ''), char(9)||char(10)||char(13)||' ')) > 0 THEN 1 ELSE 0 END AS has_attendant,
                       0 AS has_directive
                FROM turn_reports
                UNION ALL
                SELECT turn, year, period, 0, 0, 1 FROM turn_directives WHERE status = 'issued'
            )
            GROUP BY turn ORDER BY turn
            """,
            (),
        ).fetchall()
        return [{
            "kind": "month", "turn": int(r["turn"]), "year": int(r["year"]),
            "period": int(r["period"]), "has_report": bool(r["has_report"]),
            "has_attendant": bool(r["has_attendant"]),
            "has_directive": bool(r["has_directive"]),
        } for r in rows]

    def list_closed_night_archives(self) -> List[Dict[str, object]]:
        """逐场列出 closed audience night，并保留玩家可见命名所需的容器属性。"""
        rows = self.reign.closed_nights_archive_rows()
        if not rows:
            return []

        from ming_sim.audience_night import night_archive_metadata

        night_ids = [int(row["id"]) for row in rows]
        ledger_rows = self.reign.ledger_archive_rows_for_nights(night_ids)
        turn_rows = self.reign.chat_turn_archive_rows_for_nights(night_ids)
        ledgers_by_night: Dict[int, List[Dict[str, Any]]] = {night_id: [] for night_id in night_ids}
        turns_by_night: Dict[int, List[Dict[str, Any]]] = {night_id: [] for night_id in night_ids}
        for row in ledger_rows:
            ledgers_by_night[int(row["night_id"])].append({
                "person_names": _load_durable_str_list(row["person_names"], surface="story_ledger_entries.person_names"),
                "tags": _load_durable_str_list(row["tags"], surface="story_ledger_entries.tags"),
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


    # ── 动作闸门：结构化聊天写动作暂存(ADR 0006) ──────────────────────────
    def _parse_origin_chat_message_id(
        self, payload: Optional[Mapping[str, object]],
    ) -> Optional[int]:
        """Read a durable origin pin without washing malformed values into absence."""
        if not payload:
            return None
        if "origin_chat_message_id" not in payload:
            return None
        raw = payload.get("origin_chat_message_id")
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"origin_chat_message_id 须为正整，得 {type(raw).__name__}")
        if raw <= 0:
            raise ValueError("origin_chat_message_id 须为正整")
        return raw

    def _resolve_secret_oral_pins(
        self,
        *,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
    ) -> List[int]:
        """Resolve oral-decree chat pins for secret-order classification (#976).

        Explicit stage/API pins and already-durable brief pins only.
        Explicit empty ``origin_chat_message_ids=[]`` means pin-mode with no new
        oral.  No implicit source capture (#1897 J820-E2).
        """
        explicit: List[object] = []
        if origin_chat_message_ids is not None:
            explicit.extend(origin_chat_message_ids)
        if origin_chat_message_id is not None:
            explicit.append(origin_chat_message_id)
        return self._coerce_positive_message_ids(explicit)

    def _brief_origin_chat_message_ids(self, order_id: int) -> List[int]:
        """Durable oral pins already registered on this order's brief (may be empty).

        源身份 JSON 腐坏响亮，禁 or "[]"/except 静默跳过（#1897 E1 P1）。
        """
        row = self.character_knowledge.brief_origin_message_ids(int(order_id))
        if row is None:
            return []
        return self._load_durable_origin_message_ids(
            row["origin_chat_message_ids"],
            surface=f"secret_order_briefs#{int(order_id)} origin_chat_message_ids",
        )

    def _classify_secret_order_audience(
        self,
        state: GameState,
        order_id: int,
        minister_name: str,
        title: str,
        body: str,
        *,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        commit: bool = True,
    ) -> None:
        """Brief upsert with exact oral provenance for create and non-create actions."""
        pins = self._resolve_secret_oral_pins(
            origin_chat_message_id=origin_chat_message_id,
            origin_chat_message_ids=origin_chat_message_ids,
        )
        self.upsert_secret_order_brief(
            state, int(order_id), minister_name, title, body,
            origin_chat_message_ids=pins,
            commit=commit,
        )


    # ── #571 旨意案卷公共接口 ──────────────────────────────────────

    # #1889 / ADR 0151：status/迁移/关口/执行格四组闭集与 row codec 归案卷 store
    # （ming_sim.entities.dossier），此处不再留第二份。
    _DOSSIER_ACTION_TYPES = DOSSIER_ACTION_TYPES
    @classmethod
    def _directive_dossier_action_type(cls, payload: Dict[str, object]) -> str:
        explicit = str(payload.get("dossier_action_type") or "").strip()
        if not explicit:
            raise DeclarationDataError("旨意缺少明确 action_type")
        if explicit not in DIRECTIVE_ACTION_TYPES:
            raise DeclarationDataError(f"旨意 action_type 非法：{explicit}")
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
        """机械旨意的唯一结构边界；领域不完整 → DMVE；真实读取故障原样上抛。"""
        from ming_sim.action_materialize import DecreeMaterializationValidationError
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
                    raise DecreeMaterializationValidationError(f"非协饷拨帑不得夹带 purpose={purpose}")
                # #1716：amount/account 唯一验形；分类默认 grant_action=「无」时只借金钱动作过 shape，不回写。
                # 普通/legacy fallback（缺/空 grant_action）须显式非空 account，禁默认国库。
                shape_ga = grant_action if grant_action not in {"", "无"} else "赏赉"
                if grant_action in {"", "无"}:
                    account_raw = normalized.get("account")
                    if account_raw is None or not str(account_raw).strip():
                        raise DecreeMaterializationValidationError("拨帑旨意缺少 account")
                try:
                    shaped = require_grant_allocation_shape(
                        grant_action=shape_ga,
                        amount=normalized.get("amount"),
                        account=normalized.get("account"),
                    )
                except ValueError as exc:
                    raise DecreeMaterializationValidationError(str(exc)) from exc
                normalized["amount"] = shaped["amount"]
                normalized["account"] = shaped["account"]
                surface = str(
                    normalized.get("execution_surface") or "in_transit"
                ).strip()
                if surface not in {"immediate", "in_transit"}:
                    raise DecreeMaterializationValidationError("拨帑旨意 execution_surface 非法")
                normalized["execution_surface"] = surface
                normalized.pop("delta", None)
        elif action == "pay_order_override":
            # #653：结构化载荷 presence 在指令归一边界先验（键形/值域/幻影 region
            # 仍由成案点与物化点共 prepare_pay_order_entries 同一验形，不在此重复）。
            entries = normalized.get("entries")
            if not isinstance(entries, list) or not entries:
                raise DecreeMaterializationValidationError("pay_order_override 旨意缺少 entries 结构化载荷")
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
                raise DecreeMaterializationValidationError(f"{action} 旨意缺少 canonical assignee")
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
                raise DecreeMaterializationValidationError("委任授权 privilege 非法")
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
                raise DecreeMaterializationValidationError("委任授权缺少典范 scope")
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
                raise DecreeMaterializationValidationError("委任授权缺少 holder_id")
            normalized["holder_id"] = holder
            normalized["name"] = holder
            normalized["assignee_id"] = holder
        if action == "revoke_authority":
            # #523 / #611：收权生产项必带现存 authority_records.id；不得从 payload 拼 id。
            # LLM 声明：缺席→DeclarationDataError；在场脏→同错。
            raw_aid = normalized.get("authority_id")
            if raw_aid in (None, ""):
                raise DecreeMaterializationValidationError("收权旨意缺少 authority_id")
            try:
                aid = strict_int(raw_aid, accept_numeric_strings=True)
            except (TypeError, ValueError) as exc:
                raise DecreeMaterializationValidationError(str(exc)) from exc
            if aid <= 0:
                raise DecreeMaterializationValidationError("收权旨意缺少 authority_id")
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
            raw_grant = normalized.get("grant_dossier_id")
            if raw_grant not in (None, ""):
                try:
                    grant_did = strict_int(raw_grant, accept_numeric_strings=True)
                except (TypeError, ValueError) as exc:
                    raise DecreeMaterializationValidationError(str(exc)) from exc
                if grant_did > 0:
                    normalized["grant_dossier_id"] = grant_did
            # 身份真源在 authority_records；禁保留并行 authorization_id(s)
            normalized.pop("authorization_id", None)
            normalized.pop("authorization_ids", None)
        if action == "revoke_decree":
            # #523：目标仅承诺/旨意；纯授权不得入撤回成命。
            raw_target = str(normalized.get("target_id") or "").strip()
            if raw_target.startswith("authority:"):
                raise DecreeMaterializationValidationError("撤回成命目标不得为纯授权")
            revoke_did = 0
            revoke_iid = 0
            try:
                raw_revoke_did = normalized.get("revoke_target_dossier_id")
                if raw_revoke_did not in (None, ""):
                    revoke_did = strict_int(
                        raw_revoke_did, accept_numeric_strings=True,
                    )
                raw_revoke_iid = normalized.get("revoke_target_issue_id")
                if raw_revoke_iid not in (None, ""):
                    revoke_iid = strict_int(
                        raw_revoke_iid, accept_numeric_strings=True,
                    )
            except (TypeError, ValueError) as exc:
                raise DecreeMaterializationValidationError(str(exc)) from exc
            if revoke_did <= 0 and revoke_iid <= 0:
                kind = str(normalized.get("target_kind") or "").strip()
                raw = raw_target
                if raw.startswith("dossier:"):
                    kind = "dossier"
                    raw = raw.split(":", 1)[1].strip()
                elif raw.startswith("issue:"):
                    kind = "issue"
                    raw = raw.split(":", 1)[1].strip()
                if not raw:
                    raise DecreeMaterializationValidationError("撤回成命缺少目标成命标识")
                try:
                    tid = strict_int(raw, accept_numeric_strings=True)
                except (TypeError, ValueError) as exc:
                    raise DecreeMaterializationValidationError(
                        f"撤回成命目标标识非法：{raw!r}"
                    ) from exc
                if tid <= 0:
                    raise DecreeMaterializationValidationError("撤回成命缺少目标成命标识")
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
                raise DecreeMaterializationValidationError(
                    f"惩处旨意 punish_action 非法或缺失：{punish_action or '(空)'}"
                )
            if issue_disposition == "办人" and punish_action != "拿问下狱":
                raise DecreeMaterializationValidationError("弹劾潮办人须使用 canonical 拿问下狱动作")
            if issue_disposition == "压下" and punish_action != "无":
                raise DecreeMaterializationValidationError("弹劾潮压下须使用 canonical 无动作")
            normalized["punish_action"] = punish_action
            # #517 r2：罚俸须正数 amount；缺席拒收，在场脏值 → DeclarationDataError 逐项拒收。
            if punish_action == "罚俸":
                raw_amount = normalized.get("amount")
                if raw_amount in (None, ""):
                    raise DecreeMaterializationValidationError("罚俸旨意缺少正数 amount")
                try:
                    amount = strict_int(raw_amount, accept_numeric_strings=False)
                except (TypeError, ValueError) as exc:
                    raise DecreeMaterializationValidationError(
                        f"罚俸旨意 amount 非法：{raw_amount!r}"
                    ) from exc
                if amount <= 0:
                    raise DecreeMaterializationValidationError("罚俸旨意缺少正数 amount")
                normalized["amount"] = amount
        if action == "military_order":
            # #521 r1：仅限期出战（无 station 调驻面）强制未来 due_turn；
            # 调驻/移镇可无期限成案。显式期限字段若出现仍须落成未来 due。
            # LLM 声明：缺席 → 0；在场脏值 → DeclarationDataError。
            raw_due_turn = normalized.get("due_turn")
            raw_deadline = normalized.get("deadline_months")
            try:
                due_turn = (
                    0 if raw_due_turn in (None, "")
                    else strict_int(raw_due_turn, accept_numeric_strings=False)
                )
                deadline = (
                    0 if raw_deadline in (None, "")
                    else strict_int(raw_deadline, accept_numeric_strings=False)
                )
            except (TypeError, ValueError) as exc:
                raise DecreeMaterializationValidationError(str(exc)) from exc
            if due_turn <= 0 and deadline > 0 and current_turn > 0:
                due_turn = int(current_turn) + deadline
            station = str(normalized.get("station") or "")  # Free prose place name F21
            has_deadline_intent = due_turn > 0 or deadline > 0
            requires_due = not station.strip()  # 判空用副本；原串照存
            if due_turn > int(current_turn or 0):
                normalized["due_turn"] = due_turn
                normalized.pop("deadline_months", None)
            elif requires_due or has_deadline_intent:
                raise DecreeMaterializationValidationError("军令缺少有效未来 due_turn/deadline_months")
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
                    raise DecreeMaterializationValidationError(f"下议旨意不得携带 {banned}")
            cleaned = parse_responsible_bodies(normalized.get("responsible_bodies"))
            if not cleaned:
                raise DecreeMaterializationValidationError("下议旨意缺少 responsible_bodies")
            assert_responsible_bodies_org_only(
                cleaned,
                known_person_names=character_person_names(self),
                current_minister=str(
                    normalized.get("actor") or normalized.get("minister_name") or ""
                ),
            )
            normalized["responsible_bodies"] = cleaned
            raw_end = normalized.get("end_turn")
            try:
                end_turn = (
                    0 if raw_end in (None, "")
                    else strict_int(raw_end, accept_numeric_strings=True)
                )
                if end_turn <= 0 and current_turn > 0:
                    raw_months = normalized.get("deadline_months")
                    months = (
                        0 if raw_months in (None, "")
                        else strict_int(raw_months, accept_numeric_strings=True)
                    )
                    if months > 0:
                        end_turn = int(current_turn) + months
            except (TypeError, ValueError) as exc:
                raise DecreeMaterializationValidationError(str(exc)) from exc
            if end_turn <= int(current_turn or 0):
                raise DecreeMaterializationValidationError("下议缺少有效未来 end_turn/deadline_months")
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
            raise DecreeMaterializationValidationError("旨意缺少 canonical target")
        if action == "military_order":
            # #521 r2：成案前验 target_kind=army 且军队存在（含无 station 催战）。
            # 不得静默改写错误 target_kind；不得等到判后才发现虚假 id。
            if target_kind != "army":
                raise DecreeMaterializationValidationError("军令 target_kind 须为 army")
            existing_army = self.armies.row(target_id, fields="id")
            if existing_army is None:
                raise DecreeMaterializationValidationError(
                    f"军令引用未入库军队 '{target_id}'（成案前须存在）"
                )
            normalized["target_kind"] = "army"
        # #654 / owner A：locality_scope 三值 durable 归一；八值 target_kind 闭集直校验
        # （含结构目标 dossier）。region 缺省不暗升 single。
        from ming_sim.decree_vocabulary import TARGET_KINDS
        from ming_sim.execution_pressure import normalize_locality_scope
        final_kind = str(normalized.get("target_kind") or "").strip()
        if final_kind not in TARGET_KINDS:
            raise DecreeMaterializationValidationError(f"target_kind 非法：{final_kind!r}")
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
        row = self.characters.row(matched, fields="status, power_id")
        if row is None or row["status"] != "active" or row["power_id"] in (None, "ming"):
            return None
        power = self.conn.execute('SELECT kind, leader, stance FROM powers WHERE id=?', (row['power_id'],)).fetchone()
        if power is None or not (
            power["kind"] == "内乱"
            and power["stance"] in {"敌对", "潜伏"}
            and power["leader"] == matched
        ):
            return None
        return matched

    def _commit_dossier_write(self, commit: bool, *, owns_transaction: bool) -> None:
        if commit and owns_transaction:
            self.conn.commit()


    # #619 / ADR 0073 reported-progress origin namespace (ID-11 open append).
    DOSSIER_REPORT_ORIGIN_NS = DOSSIER_REPORT_ORIGIN_NS
    DOSSIER_REPORT_ORIGIN_MONTHLY = DOSSIER_REPORT_ORIGIN_MONTHLY
    DOSSIER_REPORT_ORIGIN_VERDICT = DOSSIER_REPORT_ORIGIN_VERDICT
    DOSSIER_REPORT_ORIGIN_RUSH = DOSSIER_REPORT_ORIGIN_RUSH
    DOSSIER_REPORT_ORIGIN_REVIEW = DOSSIER_REPORT_ORIGIN_REVIEW

    def _audit_fork_signals_for_source(self, source_dossier_id: int) -> List[Dict[str, object]]:
        """#622：稽核链在场时，月报输入面确定性携带被稽核案卷分叉信号。

        读端复用 list_dossier_links（relation_type=稽核）；无链则返回空——调用方不挂键。
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
        reports = self.dossiers.list_dossier_progress(int(dossier_id))
        reported_bands = []
        for item in reports:
            raw_band = str(item.get("progress_band") or "")
            if raw_band.strip():
                reported_bands.append(raw_band)
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

    def list_monthly_dossier_progress_nudges(self) -> List[Dict[str, object]]:
        """#1504 / 0058：列出在办且关联密令 active 的案卷月报候选。

        在办状态为 promulgated/executing；不以 deadline/tag/发令月收缩候选，
        缺项由 record 侧完整覆盖失败。
        """
        rows = self.conn.execute(
            """
            SELECT d.*, s.title AS secret_title, s.content AS secret_content,
                   s.due_turn AS secret_due_turn
            FROM decree_dossiers d
            JOIN secret_orders s ON s.id=d.secret_order_id
            WHERE d.status IN ('promulgated','executing') AND s.status='active'
            ORDER BY d.id
            """,
            (),
        ).fetchall()
        out: List[Dict[str, object]] = []
        for row in rows:
            dossier_id = int(row["id"])
            # #1897 S2：题名／现行要旨／期限读 secret_orders，不读案卷 payload 平行副本。
            item: Dict[str, object] = {
                "dossier_id": dossier_id,
                "secret_order_id": int(row["secret_order_id"]),
                "title": str(row["secret_title"] or ""),
                "due_turn": int(row["secret_due_turn"] or 0),
                "progress": self.dossiers.list_dossier_progress(dossier_id),
            }
            # #622 AC5：仅当稽核链在场时挂分叉信号键；无链则键不出现。
            fork_signals = self._audit_fork_signals_for_source(dossier_id)
            if fork_signals:
                item["audit_fork_signals"] = fork_signals
            out.append(item)
        return out

    def monthly_dossier_report_supply(
        self, generated: object,
    ) -> Optional[Dict[int, Dict[str, object]]]:
        """校验本月密奏覆盖。无合资格案卷且产物为空时返回 None；不写库。"""
        candidates = {
            int(item["dossier_id"]): item
            for item in self.list_monthly_dossier_progress_nudges()
        }
        if not candidates:
            if generated is None or generated == []:
                return []
            raise DeclarationDataError("无合资格长差案卷却收到本月密奏")
        if generated is None or generated == []:
            raise DeclarationDataError("合资格长差案卷缺少本月密奏")
        if not isinstance(generated, list):
            raise DeclarationDataError("合资格长差案卷缺少本月密奏")
        supplied: Dict[int, Dict[str, object]] = {}
        for item in generated:
            if not isinstance(item, dict):
                raise DeclarationDataError("长差月报条目须为对象")
            try:
                dossier_id = strict_int(item.get("dossier_id", 0))
                if dossier_id <= 0:
                    raise ValueError("not positive")
            except (TypeError, ValueError) as exc:
                raise DeclarationDataError("长差月报案卷编号无效") from exc
            if dossier_id not in candidates or dossier_id in supplied:
                raise DeclarationDataError("长差月报存在未知或重复条目")
            for field in ("progress_band", "memorial_text"):
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise DeclarationDataError(f"长差月报 {field} 须为非空字符串")
            supplied[dossier_id] = item
        if set(supplied) != set(candidates):
            raise DeclarationDataError("合资格长差案卷月报未完整覆盖")
        return supplied


    def record_monthly_dossier_progress(
        self, turn: int, generated: object = None,
    ) -> List[Dict[str, object]]:
        """Persist one valid extractor-authored brief for every eligible dossier."""
        supplied = self.monthly_dossier_report_supply(generated)
        if not supplied:
            return []

        reports: List[Dict[str, object]] = []
        for dossier_id, item in supplied.items():
            # 派系同／敌只留在监督史。origin 只承接本条密奏里声明的行动。
            from ming_sim.supervision import declared_report_action_origin
            origin = declared_report_action_origin(
                item.get("origin"), base=self.DOSSIER_REPORT_ORIGIN_MONTHLY,
            )
            self.dossiers.record_dossier_progress(
                dossier_id, int(turn), item["progress_band"], item["memorial_text"],
                origin=origin,
                commit=False,
            )
            reports.append(self.dossiers.list_dossier_progress(dossier_id)[-1])
        return reports

    def dossier_declares_escort(self, dossier_id: int) -> bool:
        """该道拨银旨自身是否声明了押解护送（#1900 押解默认随拨银旨）。

        押解人、随行护卫写在**同一道拨银交办**里即成安排，不另立密令、不另挂
        关联——这是 owner 2026-09-30 裁定的常态口径。案卷载荷里的 ``escort`` 是
        参与人名单 ``participant_roster`` 的押解投影（ADR 0053 单一真源），此处只
        判「有没有押解安排」，不重解名单。
        已持久 payload 解码走单一权威；腐坏响亮，不 catch-to-False（#1897 E1）。
        """
        row = self.conn.execute(
            'SELECT payload_json FROM decree_dossiers WHERE id=?',
            (int(dossier_id),),
        ).fetchone()
        if row is None:
            return False
        payload = parse_engine_payload_json(row["payload_json"])
        return payload_declares_escort(payload)

    def list_monthly_grant_reconciliation_targets(
        self, turn: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """扫描面：在途的拨帑案卷 ＋ **本回合已经出库**的结案拨帑。

        正常结案不免除本次核账（#1900）：世界段同段提交 fulfilled 的那道拨帑，
        结案后 status 已离开 executing，若只扫 executing 就整趟漏账。带 ``turn``
        时把本回合结案且已经有银两离开账本的路一并纳入——办理失败不抹掉已经
        离开账本的那笔。核账基数是实付：足额时与面额相同；不足额但已出库时按
        实付，未付面额不算损耗。真正零出库的 failed 不进扫描面。不带 ``turn``
        （供料读侧）只看在途，不翻历史结案。

        押解认定复用同一道拨银交办的声明；不另立护送账本。
        """
        if turn is None:
            rows = self.conn.execute(
                """
                SELECT * FROM decree_dossiers
                WHERE status='executing' AND action_type='grant_allocation'
                ORDER BY id
                """,
                (),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM decree_dossiers
                WHERE action_type='grant_allocation'
                  AND (
                    status='executing'
                    OR (status='closed' AND closed_turn=?)
                  )
                ORDER BY id
                """,
                (int(turn),),
            ).fetchall()
        from ming_sim.materials import dossier_paid_amount
        targets: List[Dict[str, object]] = []
        for row in rows:
            dossier_id = int(row["id"])
            dossier = self.dossiers.get(dossier_id)
            if dossier is None:
                raise ValueError(f"案卷不存在：{dossier_id}")
            payload = dossier["payload"]
            policy = dossier_action_policy("grant_allocation", payload)
            if policy.get("execution_surface") != "in_transit":
                continue
            if self._grant_allocation_is_monthly(payload):
                continue
            if self._grant_allocation_is_honorific(payload):
                continue
            ordered = int(payload.get("amount") or 0)
            if ordered <= 0:
                continue
            basis = ordered
            if (
                str(row["status"] or "") == "closed"
                and str(row["execution_outcome"] or "") == "failed"
            ):
                paid = dossier_paid_amount(self, dossier_id)
                if paid <= 0:
                    continue
                basis = paid
            targets.append({
                "dossier_id": dossier_id,
                "ordered_amount": basis,
                "escorted": payload_declares_escort(payload),
                "escort_source_dossier_id": None,
                "relation_type": "",
                "escort_note": "",
                "decree_text": str(row["decree_text"] or ""),
                "target_id": str(row["target_id"] or ""),
            })
        return targets


    def record_monthly_grant_reconciliations(
        self, turn: int,
    ) -> List[Dict[str, object]]:
        """Monthly tick: derive grant arrivals/losses from engine bounds and persist reconciliation.

        #1900：沿途损耗归引擎（#1820 后出，取代 0054 的「LLM 软判实抵＋clamp」）。
        本方法不再接任何提案——实抵取该路护行口径区间的中位。
        不写 0058 进展、不二次扣库、不改原 economy_move。

        分段过月会多次调本写入：已有本回合行的路不再覆盖（不拿后段中位盖前段实抵）。
        """
        targets = {
            int(item["dossier_id"]): item
            for item in self.list_monthly_grant_reconciliation_targets(int(turn))
        }
        if not targets:
            return []

        reports: List[Dict[str, object]] = []
        for dossier_id, target in targets.items():
            ordered = int(target["ordered_amount"])
            escorted = bool(target["escorted"])
            lo, hi = grant_arrival_bounds(ordered, escorted=escorted)
            arrived = (lo + hi) // 2
            loss = ordered - arrived
            note = ""
            source_id = target["escort_source_dossier_id"]
            relation = str(target["relation_type"] or "")
            report = self.dossiers.record_monthly_grant_reconciliation(
                int(dossier_id),
                int(turn),
                ordered,
                arrived,
                loss,
                1 if escorted else 0,
                int(source_id) if source_id is not None else None,
                relation,
                note,
            )
            if report is not None:
                reports.append(report)
        return reports

    # ── #625 / ADR 0077 supervision fact bottom ─────────────────────────


    def list_supervision_history(
        self, dossier_id: int, *, as_of_turn: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """读端：在场行 + 连号派生 + 稽核人任期/派系/操守定性（不落钝化分）。"""
        from ming_sim.participant_roster import resolve_dossier_owner_name
        from ming_sim.supervision import (
            character_faction_integrity,
            character_tenure,
            derive_consecutive_months,
            faction_relation,
            integrity_band,
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


    # ── #1726 奏疏收件箱（玩家面）──────────────────────────────────────
    # 两类：dossier_reported_progress（案卷进度）+ faction_denunciations（派系检举）。
    # 密令私轨不入此面（密令面板另管）。已读键绑具体奏报行，不绑案卷。

    MEMORIAL_AUTHOR_FALLBACK = "某臣"


    def list_player_memorials(self) -> List[Dict[str, object]]:
        """玩家奏疏收件箱：进度奏报 + 派系检举，含未读位；不夹带引擎结构化字段。"""
        from ming_sim.participant_roster import resolve_dossier_owner_name

        read_keys = self.reign.memorial_read_keys()
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
            # Free decree body for material feed: carry full original (P6 / ADR 0142).
            # No strip-assign, no fixed-length clip — next model reads the real 旨文.
            case_summary = str(row["decree_text"] or "")
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
        court_rows = self.conn.execute(
            """
            SELECT name, faction, integrity, identity, status
            FROM characters
            WHERE status='active' AND COALESCE(faction,'') <> ''
            ORDER BY name
            """,
            (),
        ).fetchall()
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

        all_factions = sorted(
            {
                str(r["name"])
                for r in self.conn.execute('SELECT name FROM factions ORDER BY name', ()).fetchall()
                if str(r["name"] or "").strip()
            }
            | set(names_by_faction)
        )

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
            situations.append(
                {
                    "faction": fac,
                    "leverage_band": power_band(self.factions.faction_leverage(fac)),
                    "satisfaction_band": satisfaction_band(
                        self.factions.faction_satisfaction(fac),
                    ),
                }
            )

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
                row = self.characters.row(name, fields="identity")
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
        source: Optional[Provenance] = None,
    ) -> SectionResult:
        """#627 承接落库：结构化检举条目 + clamp + 真伪底派生 + 去重。

        clamp 仅限：所指案卷须真实存在且非 closed；检举人须为在场 active 人物。
        真伪底：fork 单源读端机械对账 → compose_denunciation_origin。
        去重键=检举人×案卷×真伪类（不含 turn）；案情升级可再落；不写 loophole。
        正文原样落库（零引擎模板）。禁自动转案/改世界状态。
        """
        from ming_sim.applier import Provenance, RejectedItem, SectionResult
        from ming_sim.strict_types import strict_sqlite_id
        from ming_sim.participant_roster import resolve_dossier_owner_name
        from ming_sim.supervision import (
            character_faction_integrity,
            compose_denunciation_origin,
            denunciation_case_upgraded,
            derive_denunciation_is_true,
        )

        effective_source = source or Provenance.system_simulation

        if entries is None:
            return SectionResult([], [])
        if not isinstance(entries, list):
            payload = entries if isinstance(entries, dict) else {"raw_value": entries}
            return SectionResult([], [
                RejectedItem(
                    item=payload,
                    reason=f"检举条目容器须为 list: {entries!r}",
                    category="invalid_shape",
                    source=effective_source,
                )
            ])

        turn = int(state.turn)
        accepted: List[Dict[str, object]] = []
        rejected_list: List[RejectedItem] = []

        def _refuse(raw_item: object, reason: str, category: str = "invalid_shape") -> None:
            payload = raw_item if isinstance(raw_item, dict) else {"raw_value": raw_item}
            rejected_list.append(
                RejectedItem(
                    item=payload,
                    reason=reason,
                    category=category,
                    source=effective_source,
                )
            )

        for raw in entries:
            if not isinstance(raw, dict):
                _refuse(raw, f"检举条目非 dict: {raw!r}", "invalid_shape")
                continue
            # 仅 canonical / ITEM_FIELD_ALIASES 背书键（检举人/被检举人→*_name）
            accuser = str(raw.get("accuser_name") or "").strip()
            memorial = str(
                raw.get("memorial_text") or raw.get("body") or ""
            )
            if not accuser:
                _refuse(raw, "检举条目缺 accuser_name", "invalid_shape")
                continue
            if not memorial.strip():
                _refuse(raw, "检举条目缺 memorial_text 或 body", "invalid_shape")
                continue
            target_val = raw.get("target_dossier_id")
            if target_val is None:
                target_val = raw.get("dossier_id")
            try:
                dossier_id = strict_sqlite_id(target_val)
            except ValueError as exc:
                _refuse(raw, str(exc), "invalid_shape")
                continue
            if dossier_id <= 0:
                _refuse(raw, f"检举条目 target_dossier_id 非法 ({target_val!r})", "invalid_shape")
                continue

            # clamp：检举人在场
            accuser_row = self.conn.execute(
                'SELECT name, faction, status FROM characters WHERE name=?',
                (accuser,),
            ).fetchone()
            if accuser_row is None or str(accuser_row["status"] or "") != "active":
                _refuse(raw, f"检举人 '{accuser}' 不在场或非 active", "missing_ref")
                continue
            accuser_faction = str(accuser_row["faction"] or "").strip()

            # clamp：案卷存在且非 closed
            dossier = self.dossiers.get(dossier_id)
            if dossier is None:
                _refuse(raw, f"案卷 #{dossier_id} 不存在", "missing_ref")
                continue
            if str(dossier.get("status") or "").strip() == "closed":
                _refuse(raw, f"案卷 #{dossier_id} 已 closed", "invalid_status")
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
            prior_row = self.conn.execute(
                """
                SELECT id, turn, payload_json FROM faction_denunciations
                WHERE accuser_name=? AND target_dossier_id=? AND origin=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (accuser, dossier_id, origin),
            ).fetchone()
            if prior_row is not None:
                prev_payload = parse_engine_payload_json(prior_row["payload_json"])
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

            cur = self.conn.execute(
                """
                INSERT INTO faction_denunciations
                    (turn, accuser_name, accuser_faction, subject_name,
                     subject_faction, target_dossier_id, origin,
                     payload_json, memorial_text)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    turn,
                    accuser,
                    accuser_faction,
                    subject_name,
                    subject_faction,
                    dossier_id,
                    origin,
                    json.dumps(entry_payload, ensure_ascii=False),
                    memorial,
                ),
            )
            entry_id = int(cur.lastrowid)
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
        return SectionResult(applied=accepted, rejected=rejected_list)


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
            note=str(payload.get("reason") or text or display),
            origin_ref=f"dossier:{int(dossier_id)}",
            turn=int(state.turn),
            beyond_intent=0,
            commit=False,
        )
        if not created:
            raise ValueError("拨帑常项科目未能建项")
        return created


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
        owns_transaction = connection_owns_transaction(self.conn) if commit else False
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
            existing = self.conn.execute(
                'SELECT id FROM decree_dossiers WHERE secret_order_id=? ORDER BY region_id, id',
                (int(secret_order_id),),
            ).fetchall()
            if existing:
                return [int(r["id"]) for r in existing]
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
        if secret_order_id is None and int(directive_id or 0) > 0:
            for row in self.conn.execute(
                'SELECT id, region_id FROM decree_dossiers WHERE directive_id=? ORDER BY region_id, id',
                (int(directive_id),),
            ).fetchall():
                key = str(row["region_id"] or "")
                if key not in existing_by_region:
                    existing_by_region[key] = int(row["id"])
        elif secret_order_id is None and int(pending_action_id or 0) > 0:
            for row in self.conn.execute(
                'SELECT id, region_id FROM decree_dossiers WHERE pending_action_id=? '
                'ORDER BY region_id, id',
                (int(pending_action_id),),
            ).fetchall():
                key = str(row["region_id"] or "")
                if key not in existing_by_region:
                    existing_by_region[key] = int(row["id"])

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

        self._commit_dossier_write(commit, owns_transaction=owns_transaction)

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
        affair_id = self.affairs.resolve_declaration(
            declaration,
            year=int(state.year),
            period=int(state.period),
            turn=int(state.turn),
            allowed=ATTACH_BIRTH,
        )
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
        owns_transaction = connection_owns_transaction(self.conn) if commit else False
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
            raise DeclarationDataError("案卷 action_type/decree_text 不能为空")
        if action not in DOSSIER_ACTION_TYPES:
            raise DeclarationDataError(f"案卷 action_type 非法：{action}")
        # #653 / ADR 0090：偿还序 override 旨载荷成案点先验（fail-loud 拒整道旨）——
        # 非法键形/值域/幻影 region 在收夜即响亮拒，不等到颁布关才炸。与物化点共
        # prepare_pay_order_entries 同一验形（禁两套漂移）。
        if action == "pay_order_override":
            from ming_sim.pay_order import prepare_pay_order_entries
            from ming_sim.action_materialize import DecreeMaterializationValidationError
            entries = normalized_payload.get("entries")
            if not isinstance(entries, list) or not entries:
                raise DecreeMaterializationValidationError(
                    "pay_order_override 案卷 payload.entries 须为非空列表",
                    failed_fields=("entries",),
                )
            for entry in entries:
                if not isinstance(entry, dict):
                    raise DecreeMaterializationValidationError(
                        f"pay_order_override entry 非字典：{entry!r}",
                        failed_fields=("entries",),
                    )
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
            raise DeclarationDataError(f"{action} execution_surface 与案卷动作策略不符")
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
                raise DeclarationDataError("内批拨帑案卷须含正数 amount 与内库 account")
        if not canonical_target_kind or not canonical_target_id:
            raise DeclarationDataError("案卷 target_kind/target_id 必须完整")
        if status not in DOSSIER_STATUSES:
            raise DeclarationDataError(f"案卷 status 非法：{status}")
        if status != "proposed" and not (
            _issued_secret_order and action == "secret_order" and status == "promulgated"
        ):
            raise DeclarationDataError("案卷公共成案点只能从 proposed 起步")
        # #654 region_id 写侧白名单：'' 或现存 regions.id
        rid = str(region_id or "").strip()
        if rid:
            ok = self.regions.row(rid, fields="1")
            if ok is None:
                raise DeclarationDataError(f"案卷 region_id 非法：{rid!r}")
        region_id = rid

        dossier_id = self.dossiers.find_existing_for_source(
            secret_order_id=secret_order_id,
            directive_id=int(directive_id or 0),
            pending_action_id=int(pending_action_id or 0),
            action=action,
            region_id=region_id,
        )
        if dossier_id is not None:
            self._attach_affair_from_payload(state, canonical_payload, dossier_id)
            return dossier_id
        source_turn_id = int(source_chat_turn_id or 0)
        if source_turn_id <= 0 and int(pending_action_id or 0) > 0:
            # #1890：来源轮直接读交办自己的身份列，不再回溯
            # chat_turn_rollback_items（那道「回头去找是哪句话写的」链本票拆除）。
            # 0 = 非召对来源，participant_roster 走载荷既有口径。
            origin = self.dossiers.row(
                int(pending_action_id),
                fields="source_chat_turn_id",
                table="pending_actions",
            )
            if origin is not None:
                source_turn_id = int(origin["source_chat_turn_id"] or 0)
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
            if (
                action in {"appointment", "acting_appointment"}
                and self.characters.row(lead, fields="1") is None
            ):
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
                raise DeclarationDataError("案卷 extension execution_signal 冲突")
            durable_extension["execution_signal"] = signal
        affair_id = self._resolve_affair_id_from_payload(state, canonical_payload)
        lead_names = [
            str(item.get("character_id") or "") for item in roster
            if item.get("tier") == "主办"
        ]
        archive_keys: set[str] = set()
        if action != "secret_order":
            for lead_name in lead_names:
                lead = self.characters.row(
                    lead_name, fields="office,office_type,location"
                )
                if lead is None:
                    continue
                key = self._office_archive_key(
                    lead["office"], lead["office_type"],
                    character_name=lead_name,
                )
                if key:
                    archive_keys.add(key)
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
            due_turn=int(due_turn or 0),
            extension=durable_extension,
            participant_roster=roster,
            office_archive_keys=sorted(archive_keys),
            turn=int(state.turn),
            year=int(state.year),
            period=int(state.period),
            affair_id=int(affair_id),
        )

        if immediate_allocation:
            if self._grant_allocation_is_monthly(canonical_payload):
                self._create_grant_fiscal_item(
                    state, canonical_payload, dossier_id,
                    account="内库", amount=allocation_amount, text=text,
                )
            elif not self._is_army_pay_grant_payload(canonical_payload):
                self.record_issue_economy_move(
                    state, "内库", -allocation_amount,
                    str(canonical_payload.get("category") or "奉旨拨帑"),
                    str(canonical_payload.get("reason") or text),
                    purpose=str(canonical_payload.get("purpose") or "") or None,
                    target_kind=canonical_target_kind, target_id=canonical_target_id,
                    origin_ref=f"dossier:{dossier_id}", commit=False,
                )
        self._commit_dossier_write(commit, owns_transaction=owns_transaction)
        # 拒收镜像归外层 RejectionCollector owner（0150-D2；本核不自建不自镜像）。
        return dossier_id

    @staticmethod
    def _validate_dossier_delegations(
        roster: Iterable[Dict[str, object]],
        *,
        only: Optional[Iterable[Dict[str, object]]] = None,
        as_declaration: bool = False,
    ) -> None:
        """委派链校验。only 限定检查对象（追加项）；as_declaration 时抛 DMVE。"""
        entries = list(roster)
        responsible = {
            str(item.get("character_id") or "") for item in entries
            if item.get("tier") in {"主办", "协办"}
        }
        checked = list(only) if only is not None else entries
        for item in checked:
            delegator = str(item.get("delegator_id") or "")
            character = str(item.get("character_id") or "")
            if delegator and (delegator == character or delegator not in responsible):
                if as_declaration:
                    from ming_sim.action_materialize import (
                        DecreeMaterializationValidationError,
                    )
                    raise DecreeMaterializationValidationError(
                        "委派人须为同案主办/协办且不得自委派",
                        category="invalid_participant_roster",
                    )
                raise ValueError("委派人须为同案主办/协办且不得自委派")


    def append_decree_dossier_participants(
        self, dossier_id: int, participants: Iterable[object], *, commit: bool = True,
    ) -> List[Dict[str, object]]:
        """Append ADR 0053 roster entries without replacing durable members.

        来源分界（#1897 E1/K2 / ADR0005）：
        - 本次追加项领域错误 → DMVE（调用方可逐项拒收）
        - 已持久名册 schema/引用腐坏 → 裸 ValueError（内部故障，不记声明拒收）
        """
        from ming_sim.action_materialize import DecreeMaterializationValidationError

        owns_transaction = connection_owns_transaction(self.conn) if commit else False
        # —— 1. 本次追加项准入（声明侧）——
        additions = self._normalize_participant_roster(
            participants, strict_structured=True,
        )
        self._validate_participant_roster_references(additions)

        # —— 2. 已持久名册响亮读取（内部）——
        dossier = self.dossiers.get(int(dossier_id))
        if dossier is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        existing_raw = dossier.get("participant_roster") or []
        existing = self._normalize_participant_roster(
            existing_raw, strict_structured=True, as_durable=True,
        )
        self._validate_participant_roster_references(existing, as_durable=True)
        # 旧名册委派链：同一权威规则，内部故障出口（裸 ValueError），不跳过。
        self._validate_dossier_delegations(existing)

        # —— 3. 合并：冲突/委派只归责追加项 ——
        by_character = {str(item["character_id"]): item for item in existing}
        added: List[Dict[str, object]] = []
        for item in additions:
            character_id = str(item["character_id"])
            prior = by_character.get(character_id)
            if prior is not None:
                if prior != item:
                    raise DecreeMaterializationValidationError(
                        f"参与人物已在案且机械档不同：{character_id}",
                        category="invalid_participant_roster",
                    )
                continue
            by_character[character_id] = item
            added.append(item)
        merged = existing + added
        # 追加项委派相对合并后主协办集；领域拒收（DMVE）。
        self._validate_dossier_delegations(
            merged, only=added, as_declaration=True,
        )
        if added:
            raw_keys_row = self.conn.execute(
                'SELECT office_archive_keys FROM decree_dossiers WHERE id=?',
                (int(dossier_id),),
            ).fetchone()
            raw_keys = (
                raw_keys_row["office_archive_keys"] if raw_keys_row is not None else None
            )
            parsed_keys = _load_durable_str_list(raw_keys)
            archive_keys = set(parsed_keys)
            if str(dossier.get("action_type") or "") != "secret_order":
                for item in added:
                    if str(item.get("tier") or "") != "主办":
                        continue
                    lead_name = str(item.get("character_id") or "")
                    lead = self.characters.row(
                        lead_name, fields="office,office_type,location"
                    )
                    if lead is None:
                        continue
                    key = self._office_archive_key(
                        lead["office"], lead["office_type"],
                        character_name=lead_name,
                    )
                    if key:
                        archive_keys.add(key)
            self.dossiers.set_participants_and_archive(
                int(dossier_id), merged, sorted(archive_keys), commit=False
            )
        self._commit_dossier_write(commit, owns_transaction=owns_transaction)
        return added


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
            known = self.regions.row(seat, fields="1")
            if known is None:
                raise OfficeAppointmentRejection(
                    f"unknown region_id {seat!r} for office appointment",
                    category="missing_ref",
                )
            return seat
        # No typed region this call — only continue an existing same-office seat.
        # character_offices is required schema (init_schema); missing table
        # surfaces as SQL error (ADR 0005 / #1853).
        person = str(name or "").strip()
        title = normalize_office(str(office or ""))
        if person and title:
            row = self.conn.execute(
                'SELECT office_title, region_id FROM character_offices WHERE character_name=?',
                (person,),
            ).fetchone()
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

    def project_office_identity(
        self,
        office: object,
        office_type: object,
        *,
        region_id: object = "",
        character_name: object = "",
    ) -> Dict[str, object]:
        """Authoritative office → archive_key + region_ids.

        Shared by character materials scope and decree-dossier succession.
        Local jurisdiction binds to one appointment/seat identity: prefer the
        caller's typed ``region_id``, else the holder's ``character_offices.region_id``.
        Never derive from Character.location, free-text titles, or office_slots
        (same bare 巡抚 in two provinces must not collide).
        """
        title = normalize_office(str(office or ""))
        kind = str(office_type or "").strip()

        if kind and kind in self._central_archive_office_types():
            return {"archive_key": f"central:{kind}", "region_ids": ()}

        if kind not in self._LOCAL_ARCHIVE_OFFICE_TYPES:
            return {"archive_key": "", "region_ids": ()}

        rid = str(region_id or "").strip()
        if not rid and character_name:
            rid = self.characters.office_region(character_name)

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
        region_id: object = "",
        character_name: object = "",
    ) -> str:
        """Typed archive identity via :meth:`project_office_identity`."""
        projected = self.project_office_identity(
            office,
            office_type,
            region_id=region_id,
            character_name=character_name,
        )
        return str(projected.get("archive_key") or "")

    def list_referenceable_dossiers(
        self, character_name: str, current_turn: int,
    ) -> List[Dict[str, object]]:
        """Project candidates from the same durable character-knowledge truth."""
        from ming_sim.knowledge import knowledge_row_visible_to, origin_visible_to
        from ming_sim.materials import dossier_id_in_origin

        name = str(character_name or "")
        known_dossier_ids: set[int] = set()
        knowledge_events = self._character_knowledge_events(name)
        if name:
            knowledge_events += self._character_knowledge_events("")
        for event in knowledge_events:
            if not knowledge_row_visible_to(self, event, name):
                continue
            source_id = str(event.get("source_id") or "")
            dossier_id = dossier_id_in_origin(source_id)
            if dossier_id is not None:
                known_dossier_ids.add(dossier_id)
        office_row = self.characters.row(name, fields="office,office_type,location")
        reader_archive_key = (
            self._office_archive_key(
                office_row["office"], office_row["office_type"],
                character_name=name,
            )
            if office_row is not None else ""
        )
        rows = self.conn.execute(
            """
            SELECT d.*,
                                      s.title AS secret_title,
                                      EXISTS(
                                          SELECT 1 FROM decree_dossier_decisions h
                                          WHERE h.dossier_id=d.id
                                            AND h.rescript_action='force_promulgated'
                                      ) AS was_force_promulgated
                               FROM decree_dossiers d
                               LEFT JOIN secret_orders s ON s.id=d.secret_order_id
                               WHERE d.created_turn <= ?
                               ORDER BY d.id DESC
            """,
            (int(current_turn),),
        ).fetchall()
        visible: List[Dict[str, object]] = []
        for row in rows:
            admitted = (
                row["secret_order_id"] is None
                and (
                    str(row["promulgation_decision"] or "") == "promulgated"
                    or bool(row["was_force_promulgated"])
                    or int(row["id"]) in known_dossier_ids
                    or reader_archive_key in set(
                        _load_durable_str_list(row['office_archive_keys'])
                    )
                )
            ) or (
                row["secret_order_id"] is not None
                and origin_visible_to(self, f"dossier:{row['id']}", name)
            )
            if not admitted:
                continue
            # Same hydrate contract as get/list decree rows (ADR 0005: fail loud).
            item = hydrate_dossier_row(row)
            item["was_force_promulgated"] = bool(row["was_force_promulgated"])
            visible.append(item)
        return visible


    def resolve_commitment_origin_ref(
        self, state: GameState, supplied_ref: str, *, origin_kind: str = "",
    ) -> str:
        """承诺创建写端：有本回合已颁案卷时，origin 单向归一到案卷。"""
        supplied = str(supplied_ref or "").strip()
        if supplied.startswith("dossier:"):
            try:
                dossier_id = int(supplied.split(":", 1)[1])
            except (TypeError, ValueError) as exc:
                raise KeyError(str(exc)) from exc
            # 缺行/越界 id=模型坏引用→KeyError 逐项拒（同 effect_origin_rejection
            # 捕 OverflowError）；hydrate_dossier_row 解码故障 RuntimeError 穿透
            try:
                dossier = self.dossiers.get(dossier_id)
            except OverflowError as exc:
                raise KeyError(str(exc)) from exc
            if dossier is None:
                raise KeyError("commitment origin_ref 指向不存在案卷")
            return supplied
        from ming_sim.materials import SECRET_ORDER_ORIGIN_PREFIX, is_secret_order_origin

        if is_secret_order_origin(supplied):
            try:
                secret_order_id = int(supplied[len(SECRET_ORDER_ORIGIN_PREFIX):])
            except (TypeError, ValueError) as exc:
                raise KeyError(str(exc)) from exc
            try:
                dossier = self.dossiers.get_for_secret_order(secret_order_id)
            except OverflowError as exc:
                raise KeyError(str(exc)) from exc
            if dossier is None:
                raise KeyError("commitment origin_ref 指向无案卷密令")
            return f"dossier:{int(dossier['id'])}"
        if str(origin_kind or "") == "decree":
            row = self.conn.execute(
                'SELECT COUNT(*) AS n FROM decree_dossiers WHERE created_turn=?',
                (int(state.turn),),
            ).fetchone()
            if row is not None and int(row["n"] or 0) > 0:
                raise KeyError(
                    "承诺 origin_ref 必须由产出它的明确案卷携带 dossier:<id>"
                )
        return supplied


    def record_dossier_promulgation(
        self, state: GameState, dossier_id: int, decision: str, *,
        blocked_layer: str = "", reason: str = "", legal_reason_code: str = "",
        primary_opponents: Optional[List[Dict[str, str]]] = None,
        gatekeeper_id: Optional[str] = None,
        criteria_snapshot: Optional[Dict[str, object]] = None,
    ) -> Optional[Dict[str, object]]:
        """Record only the verdict; hand its dossier payload to settlement."""
        with atomic(self):
            row = self.dossiers.get(dossier_id)
            if row is None:
                raise KeyError(f"案卷不存在：{dossier_id}")
            predeclared_midzhi = row.get("mode") == "midzhi"
            if decision not in {"promulgated", "force_promulgated"}:
                self.dossiers.record_dossier_decision(
                    dossier_id, decision, blocked_layer=blocked_layer,
                    reason=reason, legal_reason_code=legal_reason_code,
                    primary_opponents=primary_opponents,
                    gatekeeper_id=gatekeeper_id,
                    criteria_snapshot=criteria_snapshot, commit=False,
                )
                if predeclared_midzhi and decision == "rejected":
                    self.dossiers.append_midzhi_stigma(
                        dossier_id, decision="rejected", turn=state.turn, commit=False,
                    )
                return
            if decision == "force_promulgated":
                turn_row = self.reign.row(1, fields="turn", table="game_state")
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
                self.conn.execute(
                    """
                    UPDATE decree_dossiers
                    SET status='promulgated',rescript_pending=0,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (int(dossier_id),),
                )
                self.dossiers.insert_decision(
                    int(dossier_id),
                    current_turn,
                    decision="rejected",
                    rescript_action="force_promulgated",
                    reason="批红强颁",
                )
                # #657 §C.8：中旨当下不向派系扇出、不猜受影响派系（正式离心归 M12）。
                # 预声明 midzhi 打回只落 stigma；强颁只追加皇威。
                # Ordinary force 仍走 stigma + authority + typed parties。
                if not predeclared_midzhi:
                    self.dossiers.append_midzhi_stigma(
                        dossier_id, decision="force_promulgated", turn=state.turn,
                        commit=False,
                    )

            else:
                self.dossiers.record_dossier_decision(
                    dossier_id, "promulgated", blocked_layer=blocked_layer,
                    reason=reason, legal_reason_code=legal_reason_code, commit=False,
                )
            if predeclared_midzhi and decision == "promulgated":
                self.dossiers.append_midzhi_stigma(
                    dossier_id, decision="promulgated", turn=state.turn, commit=False,
                )
            return row

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
        row = self.conn.execute(
            """
            SELECT affected_parties_json FROM decree_dossier_decisions
                               WHERE dossier_id=? AND turn=? AND rescript_action=''
                               ORDER BY id DESC LIMIT 1
            """,
            (int(dossier_id), int(turn)),
        ).fetchone()
        if row is None:
            raise ValueError("强颁缺少当前回合 Judge affected_parties")
        value = _load_durable_json(row["affected_parties_json"], default='[]')
        if not value:
            raise ValueError("强颁当前回合 Judge affected_parties 必须为非空 typed 清单")
        validate_affected_parties(
            value,
            faction_names={str(item["name"]) for item in self.factions.names()},
            class_names={str(item["name"]) for item in self.classes.names()},
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
        self.reign.upsert_metric(
            "皇威",
            state.metrics["皇威"],
        )

    def _apply_override_costs(
        self, state: GameState, dossier_id: int, *, include_authority: bool,
        include_parties: bool, stigma_reason: str, commit: bool = True,
    ) -> None:
        """ADR 0056 narrow rail: authority and typed signed reactions."""
        if include_authority:
            self._apply_authority_cost(
                state, dossier_id, stigma_reason, cost_identity="override",
            )
        parties_already_applied = (
            self.conn.execute(
                """
                SELECT 1 FROM decree_cost_events
                                   WHERE dossier_id=? AND cost_kind='satisfaction' AND cost_identity='override'
                                   LIMIT 1
                """,
                (int(dossier_id),),
            ).fetchone()
            is not None
        )
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
        """Withdraw an issued promise; commit=False belongs wholly to its caller.

        只落 0056 名声代价（毁约判定、皇威、当事大臣观感、派系），**不**代
        模型把目标案卷结案——案卷的终局由执行格判官的 ``dossier_executions``
        声明落（撤令当月见办理结果）。
        """
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
            roster = decode_durable_participant_roster(
                dossier.get("participant_roster") or [],
                )
            ministers = set()
            for item in roster:
                tier = item.get("tier")
                if tier == "主办":
                    ministers.add(str(item.get("character_id") or ""))
                if tier in {"主办", "协办"} and item.get("delegator_id"):
                    ministers.add(str(item["delegator_id"]))
            ministers.discard("")
            factions = set()
            for person in sorted(ministers):
                row = self.characters.row(person, fields="faction,status")
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
                str(row["name"]) for row in self.factions.names()
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
                self.conn.execute(
                    'UPDATE decree_dossiers SET interruption_reason=CASE WHEN '
                    "interruption_reason='' THEN ? ELSE interruption_reason END WHERE"
                    ' id=?',
                    (reason, int(dossier_id)),
                )
            else:
                # 只记毁约账；结案留给执行格判官的声明——无代码关案分支。
                logger.info(
                    "breach recorded without closing dossier=%s reason=%s",
                    int(dossier_id), reason,
                )
        return True


    def validate_joint_liability_affected_parties(
        self, affected_parties: object, outcome: str,
    ) -> None:
        """显式 affected_parties：validate_affected_parties 全键 + 档位贴合终值映射。

        仅作契约§5/AC⑥校验门闩，不驱动机械写路；适配器在落库前调用一次。
        """
        primary = self._EXECUTION_OUTCOME_INTENSITY.get(str(outcome or "").strip())
        if primary is None:
            raise DeclarationDataError("连坐 affected_parties 仅接受 degraded/failed/transformed 终值")
        allowed = {primary}
        downgraded = self._INTENSITY_DOWNGRADE.get(primary)
        if downgraded:
            allowed.add(downgraded)
        faction_names = {
            str(row["name"]) for row in self.factions.names()
        }
        class_names = {str(row["name"]) for row in self.classes.names()}
        try:
            validate_affected_parties(
                affected_parties,
                faction_names=faction_names,
                class_names=class_names,
            )
        except ValueError as exc:
            raise DeclarationDataError(str(exc)) from exc
        for party in affected_parties:  # type: ignore[union-attr]
            if str(party.get("intensity") or "") not in allowed:
                raise DeclarationDataError("affected_parties intensity 须与执行终值固定映射一致")

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
        _record_decree_cost + record_relation_edge_event；幂等键不含 turn。
        """
        outcome = str(outcome or "").strip()
        if outcome not in self._JOINT_LIABILITY_TRIGGERS:
            return False
        primary_intensity = self._EXECUTION_OUTCOME_INTENSITY[outcome]
        secondary_intensity = self._INTENSITY_DOWNGRADE[primary_intensity]
        # reason 常承接 execution_note 原文：空白只判定，落边/费用语境不 strip。
        reason_raw = str(reason or "")
        reason_text = reason_raw if reason_raw.strip() else "执行连坐"
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
                str(row["name"]) for row in self.factions.names()
            }
            # 投影已先定档后去重（primary 胜）；同派系 UNIQUE 保留主责额度。
            # #1900：连坐归属留在关系边结构化账，
            # 不向 execution_note 模板增补（P6 / ADR 0142 原文零删改）。
            for party in project_execution_liability_parties(
                dossier.get("participant_roster"),
            ):
                person = str(party["character_id"])
                if party["responsibility"] == "primary":
                    intensity = primary_intensity
                else:
                    intensity = secondary_intensity
                row = self.characters.row(person, fields="faction,status")
                if row is None:
                    continue
                if str(row["status"] or "") == "dead":
                    logging.getLogger(__name__).warning("跳过已故连坐责任人%s", person)
                    continue
                if intensity is None:
                    # 执行人已是 weak 时次责无更低档→零机械扣。
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
        return True


    def resolve_revoke_decree_target_ids(
        self, payload: object, row: object = None,
    ) -> tuple[int, int]:
        """撤令目标解析唯一实现：(dossier_id, issue_id)。

        撤令的三处读者共用本函数——判后物化（#523）、判前供料
        （materials.revoke_target_facts）。读同一组结构化身份字段
        ``revoke_target_dossier_id`` / ``revoke_target_issue_id``；两者皆无
        时才按案卷行 ``target_kind``/``target_id`` 解析（接受 ``dossier:``/
        ``issue:`` 前缀），issue 再经 ``origin_ref`` 回指案卷。两个字段可同时
        在场（撤的是某道旨下出的承诺），**不得**读到其一即止。

        无合法案卷来源时以 ValueError 声明；只读供料方仅捕获该无目标合同，
        不得吞没 AttributeError/TypeError 等代码异常。
        """
        from ming_sim.strict_types import strict_int

        source = payload if isinstance(payload, Mapping) else {}
        fields = row if isinstance(row, Mapping) else {}

        def _id(key: str) -> int:
            raw = source.get(key)
            return 0 if raw in (None, "") else strict_int(raw, accept_numeric_strings=True)

        target_dossier_id = _id("revoke_target_dossier_id")
        target_issue_id = _id("revoke_target_issue_id")

        if target_dossier_id <= 0 and target_issue_id <= 0:
            raw = str(
                source.get("target_id") or fields.get("target_id") or ""
            ).strip()
            kind = str(
                source.get("target_kind") or fields.get("target_kind") or ""
            ).strip()
            if raw.startswith("dossier:"):
                kind, raw = "dossier", raw.split(":", 1)[1].strip()
            elif raw.startswith("issue:"):
                kind, raw = "issue", raw.split(":", 1)[1].strip()
            tid = strict_int(raw, accept_numeric_strings=True) if raw else 0
            if tid <= 0:
                raise ValueError("撤回成命案卷缺少目标")
            if kind == "issue":
                target_issue_id = tid
            else:
                target_dossier_id = tid

        # issue 目标：经 origin_ref 回指案卷；无合法案卷来源不得免代价终结
        if target_dossier_id <= 0 and target_issue_id > 0:
            issue_row = self.conn.execute(
                'SELECT kind, status, origin_ref FROM issues WHERE id=?',
                (int(target_issue_id),),
            ).fetchone()
            if issue_row is None:
                raise ValueError("撤回成命目标事项不存在")
            if str(issue_row["kind"] or "").strip() != "initiative":
                raise ValueError("撤回成命目标须为承诺/initiative")
            origin = str(issue_row["origin_ref"] or "").strip()
            if origin.startswith("dossier:"):
                target_dossier_id = int(origin.split(":", 1)[1])

        if target_dossier_id <= 0:
            # 删除 standalone issue 免代价旁路（dossier_id=0 仍 cancel_issue）
            raise RevokeOriginUnresolved("撤回成命目标无合法案卷来源，不得免代价终结")
        return int(target_dossier_id), int(target_issue_id)


    def _record_dossier_verdict_metadata(
        self, state: GameState, dossier_id: int, verdict: Dict[str, object],
    ) -> None:
        """Record typed verdict metadata without consuming its effects."""
        dossier = self.dossiers.get(dossier_id)
        # #657 §C.8：中旨不持久化猜派 affected_parties；打回仅 stigma。
        parties_json = (
            "[]" if dossier and dossier.get("mode") == "midzhi"
            else safe_json_dumps(verdict.get("affected_parties") or [], ensure_ascii=False)
        )
        self.conn.execute(
            """
            UPDATE decree_dossier_decisions
                               SET affected_parties_json=?, midzhi_unpromulgatable=?
                               WHERE id=(SELECT MAX(id) FROM decree_dossier_decisions WHERE dossier_id=?)
            """,
            (
                parties_json,
                1 if verdict.get('midzhi_unpromulgatable') is True else 0,
                dossier_id,
            ),
        )

    def interrupt_dossiers_for_character(
        self, state: GameState, character_name: str, reason: str, *,
        commit: bool = True,
    ) -> int:
        owns_transaction = connection_owns_transaction(self.conn) if commit else False
        rows = self.conn.execute(
            """
            SELECT id,secret_order_id,status FROM decree_dossiers
            WHERE executor_kind='character' AND executor_id=?
              AND status IN ('promulgated','executing')
            ORDER BY id
            """,
            (str(character_name),),
        ).fetchall()
        materializing = int(getattr(self.conn, "_materializing_dossier_id", 0) or 0)
        rows = [row for row in rows if int(row["id"]) != materializing]
        for row in rows:
            dossier_id = int(row["id"])
            if row["status"] == "promulgated":
                self.dossiers.transition(dossier_id, "executing", commit=False)
            order_id = row["secret_order_id"]
            if order_id is not None:
                order = self.character_knowledge.secret_order_row(int(order_id))
                if order is not None and order["status"] == "active":
                    from ming_sim.covert_progress import player_facing_secret_order_close_text
                    result = player_facing_secret_order_close_text(
                        dict(order), self.dossiers.list_dossier_progress(dossier_id),
                    )
                    self.close_secret_order(
                        int(order_id), "failed", result, int(state.turn),
                        execution_note=reason, commit=False,
                    )
                    continue
            self.dossiers.record_execution(
                dossier_id, "failed", reason, state.turn,
                close=True, commit=False,
            )
        self._commit_dossier_write(commit, owns_transaction=owns_transaction)
        return len(rows)

    def _night_id_for_staged_write(
        self, night_id: Optional[int], *, what: str, source_chat_turn_id: int = 0,
    ) -> int:
        """声明已持有源夜时盖源夜；未持有则盖当前开放夜。

        封夜后的迟到转译传入已封源夜：CLOSED 原样放行，不改挂落账当下的开放夜。
        CLOSING 在 source_chat_turn_id 为迟到源轮时放行（与 assert 同源）。
        night_id 缺或 <=0 维持开夜查找（无开放夜则为 0）。
        """
        from ming_sim.audience_night import assert_night_accepts_player_input
        requested = int(night_id) if night_id is not None else 0
        ctid = int(source_chat_turn_id or 0)
        if requested > 0:
            bound = assert_night_accepts_player_input(
                self, requested, what=what, source_chat_turn_id=ctid,
            )
        else:
            bound = assert_night_accepts_player_input(
                self, what=what, source_chat_turn_id=ctid,
            )
        return int(bound["id"]) if bound is not None else 0

    def stage_pending_action(
        self, turn: int, kind: str, action: str, minister_name: str,
        payload: Dict[str, object], target_id: Optional[int] = None,
        *,
        night_id: Optional[int] = None,
        source_chat_turn_id: int = 0,
    ) -> int:
        """把一条结构化聊天写动作存进 pending_actions 暂存(status=pending)。返回行 id。
        颁诏时 commit_pending_actions 批量落库;颁诏前不动真实表。

        Secret oral provenance must be pinned by the source turn at the caller;
        another turn's held message is never a valid substitute.

        ``night_id``：显式承接的源夜（ADR 0038 后出注记的迟到转译）。夜已收时
        ``get_open_night`` 返 None 会把补译暂存挂成 night_id=0，随后应允按
        「不属本夜暂存清单」missing_ref——补译交办因此接不上源夜。给出源夜时
        仍走同一条 CLOSING 冻结校验，只是不再取「当前开着的夜」。
        ``source_chat_turn_id``（#1890）：本道交办的来源对话轮——统一身份=
        本行 id + 这一列；撤回该轮按此列整轮作废。同时用于迟到转译放行收夜
        持闸窗口（判据唯一真源见 :func:`assert_night_accepts_player_input`）。
        0 = 非召对来源（过月世界段 / 框架写入），不随任何召对轮撤回。
        """
        payload_data: Dict[str, object] = dict(payload or {})
        # #498：未持源夜时挂当前开放夜。#1900：声明路径传入源夜则盖源夜。
        # CLOSING freezes new staged actions.
        night_id = self._night_id_for_staged_write(
            night_id, what="暂存",
            source_chat_turn_id=int(source_chat_turn_id or 0),
        )
        # 写前捕获归属：INSERT 后 in_transaction 会使 owns_transaction() 恒 False。
        owns = connection_owns_transaction(self.conn)
        cur = self.dossiers.insert_pending_action(
            int(turn),
            str(kind),
            str(action),
            None if target_id is None else int(target_id),
            str(minister_name or ""),
            json.dumps(payload_data, ensure_ascii=False),
            "pending",
            night_id,
            0,
            int(source_chat_turn_id or 0),
        )
        if owns:
            self.conn.commit()
        return int(cur.lastrowid)


    def stage_directive_candidate(
        self, turn: int, minister_name: str, payload: Dict[str, object],
        *,
        night_id: Optional[int] = None,
        source_chat_turn_id: int = 0,
    ) -> int:
        """多道模式（#502）：新拟一道**独立**圣旨候选——总是 INSERT 新行、不并进现有候选。
        改草走 :meth:`update_directive_candidate`。同臣同月 last-write-wins upsert 已退役（#1897 D2）。

        ``night_id``：与 :meth:`stage_pending_action` 同义——显式承接的源夜，供
        间接暂存入口（``action_materialize.stage_*_candidate``）把 ADR 0038
        迟到转译的归属夜传下去，不再退回「当前开着的夜」。``source_chat_turn_id``
        同义：迟到转译的源轮，放行收夜持闸窗口。
        """
        return self.stage_pending_action(
            turn, kind="directive", action="拟旨",
            minister_name=minister_name, target_id=None, payload=payload,
            night_id=night_id,
            source_chat_turn_id=source_chat_turn_id,
        )

    def update_office_candidate_payload(
        self, candidate_id: int, payload: Dict[str, object],
        *,
        night_id: Optional[int] = None,
        source_chat_turn_id: int = 0,
    ) -> int:
        """#529：原地更新某一道 pending office（任免）候选 payload（特旨/署理路径应答）。

        与 directive 改草同纪律——未持源夜时归属迁到当前开夜并清 night_approved；
        声明路径传入源夜则盖源夜。合并保留下划线控制键。
        ``source_chat_turn_id``：迟到转译源轮，放行收夜持闸窗口。
        返回该行 id（不存在/非 pending office 则 0）。
        """
        stamp = self._night_id_for_staged_write(
            night_id, what="任免路径应答",
            source_chat_turn_id=int(source_chat_turn_id or 0),
        )
        owns = connection_owns_transaction(self.conn)
        row = self.conn.execute(
            "SELECT id,payload_json,status FROM pending_actions WHERE id=? AND kind='office'",
            (int(candidate_id),),
        ).fetchone()
        if row is None:
            return 0
        if row["status"] != "pending":
            raise ValueError("已成案任免不得改路径")
        merged = self._merge_underscore_control_keys(row["payload_json"], payload)
        self.conn.execute(
            'UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0 WHERE id=?',
            (json.dumps(merged, ensure_ascii=False), stamp, int(candidate_id)),
        )
        if owns:
            self.conn.commit()
        return int(candidate_id)

    def update_directive_candidate(
        self, candidate_id: int, payload: Dict[str, object],
        *,
        night_id: Optional[int] = None,
        source_chat_turn_id: int = 0,
    ) -> int:
        """多道模式（#502）：原地更新某一道 pending directive 候选正文（补充/改草，不冻结）。
        未持源夜时把归属迁到当前开着的夜并清 night_approved；声明路径传入源夜则盖源夜。
        返回该行 id。``source_chat_turn_id``：迟到转译源轮，放行收夜持闸窗口。
        """
        stamp = self._night_id_for_staged_write(
            night_id, what="改草",
            source_chat_turn_id=int(source_chat_turn_id or 0),
        )
        row = self.conn.execute(
            "SELECT id,payload_json,status,version FROM pending_actions WHERE id=? AND kind='directive'",
            (int(candidate_id),),
        ).fetchone()
        if row is None:
            return 0
        if row["status"] != "pending":
            raise ValueError("已成案旨意不得改草")
        merged = self._merge_directive_payload(row["payload_json"], payload)
        self._discard_pending_decree_forecast(int(row["id"]), int(row["version"] or 1))
        self.conn.execute(
            'UPDATE pending_actions SET payload_json=?, night_id=?, night_approved=0,'
            ' version=version+1 WHERE id=?',
            (json.dumps(merged, ensure_ascii=False), stamp, int(candidate_id)),
        )
        self.conn.commit()
        return int(candidate_id)

    @staticmethod
    def _is_typed_business_refusal(exc: BaseException) -> bool:
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        from ming_sim.exceptions import OfficeAppointmentRejection, PendingActionRefusal

        return isinstance(
            exc,
            (PendingActionRefusal, OfficeAppointmentRejection, DecreeMaterializationValidationError),
        )

    def _dispose_pending_action_apply_exception(
        self, pa: Dict[str, object], exc: BaseException, *, rejection_collector=None,
    ) -> None:
        """暂存提交异常的共同分流政策（#1853 J4）。

        调用方已 ROLLBACK TO savepoint（及必要的输入/内存恢复）。
        业务拒收终态该项后返回；RejectionCollectorRequired 与真异常一律上抛。
        """
        from ming_sim.applier import RejectionCollectorRequired

        if isinstance(exc, RejectionCollectorRequired):
            raise
        rejection = getattr(exc, "dossier_link_rejection", None)
        if rejection is not None:
            # 业务拒收（模型指向不存在案卷）：durable 审计 + 终态 failed，
            # 不是代码故障，不上抛。类别随 typed 拒收贯通 promises 缝。
            self.dossiers.record_link_rejection(
                *rejection, pending_action_id=int(pa["id"]),
            )
            self._record_typed_business_refusal(pa, exc, rejection_collector)
            self.dossiers.set_pending_action_status("failed", int(pa["id"]))
            tlog(f"[pending_actions] 业务拒收 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
            return
        if self._is_typed_business_refusal(exc):
            self._record_typed_business_refusal(pa, exc, rejection_collector)
            self.dossiers.set_pending_action_status("failed", int(pa["id"]))
            tlog(f"[pending_actions] 业务拒收 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
            return
        # #1853：真异常留 pending，停止本批；由原轮/月链 error_pack 与失败路径上抛。
        tlog(f"[pending_actions] 落库失败上抛 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
        raise

    def _run_pending_action_commit_lifecycle(
        self,
        state: GameState,
        pa: Dict[str, object],
        payload: Dict[str, object],
        *,
        content=None,
        rejection_collector=None,
        owns_transaction: Optional[bool] = None,
        restore_on_rollback=None,
        savepoint_prefix: str = "pending_action_apply",
    ) -> bool:
        """暂存提交的唯一共同生命周期（#1853 J4-R）。

        atomic → savepoint → apply → committed/failed → 异常分流 → release → collector flush。
        拟旨输入准备与 office 内存恢复由调用方在前后处理；本方法不复制第二套生命周期。
        返回 True 表示已 committed；软失败返回 False；真异常经既有出口上抛。
        """
        if owns_transaction is None:
            owns_transaction = connection_owns_transaction(self.conn)
        cm = atomic(self) if owns_transaction else contextlib.nullcontext()
        ok = False
        with cm:
            savepoint = f"{savepoint_prefix}_{int(pa['id'])}"
            try:
                with item_savepoint_scope(self, savepoint):
                    ok = self._apply_pending_action(state, pa, payload, content=content)
                    if not ok:
                        raise ItemAtomicReject(
                            "领域条件不成立，该暂存已失败",
                            "invalid_state",
                        )
                    self.dossiers.set_pending_action_status("committed", int(pa["id"]))
            except ItemAtomicReject as exc:
                if restore_on_rollback is not None:
                    restore_on_rollback()
                self.dossiers.set_pending_action_status("failed", int(pa["id"]))
                self._record_pending_domain_rejection(
                    rejection_collector,
                    state,
                    pa,
                    payload,
                    reason=exc.reason,
                    category=exc.category,
                )
            except Exception as exc:
                if restore_on_rollback is not None:
                    restore_on_rollback()
                self._dispose_pending_action_apply_exception(
                    pa,
                    exc,
                    rejection_collector=rejection_collector,
                )
            if rejection_collector is not None:
                rejection_collector.flush_to_db(self)
        return ok

    def _record_typed_business_refusal(
        self, pa: Dict[str, object], exc: BaseException, rejection_collector,
    ) -> None:
        if rejection_collector is None:
            return
        from ming_sim.applier import Provenance, RejectedItem

        rejection_collector.note_commit_rejection(int(pa["id"]), exc)
        raw_item = getattr(exc, "item", None)
        item = dict(raw_item) if isinstance(raw_item, dict) else {}
        item.update({
            "pending_action_id": int(pa["id"]),
            "kind": str(pa.get("kind") or ""),
            "action": str(pa.get("action") or ""),
        })
        rejection_collector.record(
            "pending_actions",
            RejectedItem(
                item=item,
                reason=str(exc),
                category=str(getattr(exc, "category", "") or "business_refusal"),
                source=(Provenance.secret_order if pa["kind"] == "secret_order"
                        else Provenance.player_decree),
            ),
            int(pa.get("turn") or 0),
        )

    def _discard_deleted_directive_forecast(self, target_id: object) -> None:
        pending_id = int(target_id)
        row = self.conn.execute(
            'SELECT kind, version FROM pending_actions WHERE id=?',
            (pending_id,),
        ).fetchone()
        if row is None or str(row["kind"] or "") != "directive":
            return
        self._discard_pending_decree_forecast(pending_id, int(row["version"] or 1))

    def _discard_pending_decree_forecast(
        self, candidate_id: int, version: Optional[int] = None,
    ) -> int:
        if version is None:
            row = self.dossiers.directive_version(int(candidate_id))
            if row is None:
                return 0
            version = row["version"] or 1
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
        # 已持久候选 JSON 腐坏响亮，不洗成空底丢控制键（#1897 E1）。
        old = _load_durable_json(existing_json)
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
        old = _load_durable_json(existing_json)
        incoming = dict(new_payload or {})
        roster = self.merge_decode_durable_participant_roster(
            old.get("participant_roster"), incoming.get("participant_roster"),
        )
        if not roster:
            incoming.pop("participant_roster", None)
        else:
            incoming["participant_roster"] = roster

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
                merged,
                content=self.content,
                current_turn=int(
                    self.reign.row(1, fields="turn", table="game_state")["turn"]
                ),
            )
        normalized = self._normalize_directive_dossier_payload(
            merged,
            content=self.content,
            current_turn=int(
                self.reign.row(1, fields="turn", table="game_state")["turn"]
            ),
        )
        if requested and normalized.get("dossier_action_type") != requested:
            raise ValueError("旨稿机械载荷不完整或非法，拒绝改草")
        return normalized


    def _prepare_pending_directive(
        self, state: GameState, pa: Dict[str, object], *, content=None,
    ) -> Dict[str, object]:
        """Classify and, only when valid, project one staged directive.

        Persistence decode is outside product-rejection catch (loud). Model/
        business field faults stay per-item invalid with a real refusal reason.
        """
        if (
            pa.get("status") != "pending"
            or pa.get("kind") != "directive"
            or pa.get("action") != "拟旨"
        ):
            return {"classification": "invalid"}
        # 已持久候选 JSON 腐坏响亮上抛（#1897 E1）。
        payload = parse_engine_payload_json(pa.get("payload_json"))
        # 归一内真实查询／未分类故障原样上抛；仅 typed 领域拒收归 invalid
        # （与 _apply_pending_action / _commit_conversational_draft 同缝，#1897 E1）。
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        try:
            normalized = self._normalize_directive_dossier_payload(
                payload, content=content, current_turn=int(state.turn),
            )
        except DecreeMaterializationValidationError as exc:
            return {"classification": "invalid", "payload": payload, "reason": str(exc)}
        payload = normalized
        # 已持久正文：类型／空缺 schema 故障响亮，不记领域 invalid（#1897 E1）。
        text = payload.get("text")
        if not text.strip():
            raise TypeError(f"pending_actions#{pa['id']}.payload.text must be nonempty text, got {text!r}")
        actor_raw = payload.get("actor", pa.get("minister_name") or "")
        if actor_raw is None:
            actor_raw = ""
        if not isinstance(actor_raw, str):
            raise ValueError(f"持久字段 actor 须为字符串，得 {type(actor_raw).__name__}")
        actor = actor_raw.strip()
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
        for pa in self.dossiers.list_pending_actions(int(state.turn)):
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
        按 id 序(=操作发生序)apply。落得了标 committed、业务拒收标 failed(都不留 pending,
        故幂等:已 committed/失败/held_over 不在 pending 清单、不重跑)。
        #525：held_over 留中档由同表 durable 保留、本终端只读 pending，故默认提交跳过留中。
        在月链世界段之前调，使后续步骤读到已落账的聊天动作。
        content 用于任免落库；无聊天暂存时为 no-op。
        minister_name 非空=对话确认当场 commit:只落该召对对象的暂存(应允即落,不波及他人);
        action_ids 非空=进一步只落指定 pending_actions.id（召对确认只可作用于本轮开始前可见项）;
        默认 None=颁诏批量落全回合。
        kind_filter 非空=只 commit 指定 kind(如 'directive')的暂存,跳过其余 kind。
        kind_filter_exclude 非空=只 commit 该 kind 以外的暂存(召对确认应允放过 directive,BUG 1)。
        真异常（#1853 / ADR 0005 / ADR 0008）：回滚本动作后留 pending 并上抛，停止本批。
        业务拒收只认案卷关联拒收属性、PendingActionRefusal、OfficeAppointmentRejection：
        只终态该项并继续其余项。返回 False 的数据拒收同样只终态该项。
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
        rows = self.dossiers.list_pending_actions(
            int(state.turn), status="pending", minister_name=minister_name)
        if kind_filter is not None:
            rows = [r for r in rows if r["kind"] == kind_filter]
        if kind_filter_exclude is not None:
            rows = [r for r in rows if r["kind"] != kind_filter_exclude]
        if action_ids is not None:
            allowed_ids = {int(action_id) for action_id in action_ids}
            rows = [r for r in rows if int(r["id"]) in allowed_ids]
        owns_transaction = connection_owns_transaction(self.conn)
        for pa in rows:
            if pa["kind"] == "directive" and pa["action"] == "拟旨":
                prepared = self._prepare_pending_directive(
                    state, pa, content=content,
                )
                classification = prepared["classification"]
                if classification == "invalid":
                    cm = atomic(self) if owns_transaction else contextlib.nullcontext()
                    with cm:
                        self.dossiers.set_pending_action_status("failed", int(pa["id"]))
                        self._record_pending_domain_rejection(
                            rejection_collector, state, pa, prepared["payload"],
                            reason=prepared["reason"],
                            category="invalid_shape",
                        )
                        if rejection_collector is not None:
                            rejection_collector.flush_to_db(self)
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
            # 已持久候选解码故障响亮，不洗成空载荷续 apply（#1897 E1）。
            payload = parse_engine_payload_json(pa.get("payload_json"))
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

            ok = self._run_pending_action_commit_lifecycle(
                state, pa, payload,
                content=content,
                rejection_collector=rejection_collector,
                owns_transaction=owns_transaction,
                restore_on_rollback=restore_office_memory if office_memory_key else None,
            )
            if ok:
                item: Dict[str, object] = {
                    "id": pa["id"],
                    "kind": pa["kind"],
                    "action": pa["action"],
                    "target_id": pa["target_id"],
                }
                # #1376：新建密令落库后把真实 order id 回传确认面（stage 时 target_id 为空）。
                if pa["kind"] == "secret_order" and str(pa["action"] or "") == "新建":
                    row = self.conn.execute(
                        'SELECT secret_order_id FROM decree_dossiers WHERE '
                        'pending_action_id=? AND secret_order_id IS NOT NULL ORDER BY'
                        ' id DESC LIMIT 1',
                        (int(pa['id']),),
                    ).fetchone()
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

    def _commit_conversational_draft(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None, directive_status: str = "draft",
        rejection_collector=None,
    ) -> Optional[Dict[str, object]]:
        """提交一条对话式拟旨暂存；输入准备保留，共同生命周期走唯一实现。"""
        payload_for_apply = dict(payload)
        payload_for_apply["_directive_status"] = directive_status
        ok = self._run_pending_action_commit_lifecycle(
            state, pa, payload_for_apply,
            content=content,
            rejection_collector=rejection_collector,
            savepoint_prefix="pending_action_directive",
        )
        if not ok:
            return None
        return {
            "id": pa["id"], "kind": pa["kind"],
            "action": pa["action"], "target_id": pa["target_id"],
        }

    def _record_pending_domain_rejection(
        self,
        rejection_collector: Any,
        state: GameState,
        pa: Mapping[str, object],
        payload: Mapping[str, object],
        exc: BaseException | None = None,
        *,
        reason: str | None = None,
        category: str | None = None,
    ) -> None:
        """领域坏项进既有 rejection_reports；内存 sideband 只供同步应允读回原因。

        覆盖 typed 异常、classification=invalid、_apply 返回 False 三类出口。
        真故障不经此路（调用方已 re-raise）。失败 status 不能代替法定拒收留痕。
        """
        if rejection_collector is None:
            return
        from ming_sim.applier import Provenance, RejectedItem
        if exc is not None:
            rejection_collector.note_commit_rejection(int(pa["id"]), exc)
            cat = str(
                category
                or getattr(exc, "category", "")
                or "invalid_state"
            )
            why = str(reason if reason is not None else exc)
        else:
            cat = str(category or "invalid_state")
            why = str(reason or "领域条件不成立，该暂存已失败")
        item = {
            "id": int(pa["id"]),
            "kind": str(pa.get("kind") or ""),
            "action": str(pa.get("action") or ""),
            "target_id": pa.get("target_id"),
            "minister_name": str(pa.get("minister_name") or ""),
            "payload": dict(payload) if isinstance(payload, Mapping) else {},
        }
        rejection_collector.record(
            f"pending_{item['kind'] or 'action'}",
            RejectedItem(
                item=item,
                reason=why,
                category=cat,
                # 与 _record_typed_business_refusal 同一来源规则（#1897 L1）。
                source=(
                    Provenance.secret_order
                    if str(pa.get("kind") or "") == "secret_order"
                    else Provenance.player_decree
                ),
            ),
            int(state.turn),
        )

    def _apply_pending_action(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None,
    ) -> bool:
        """把单条暂存动作落到真实表。

        明确业务目标失效返 False（commit 标 failed + 业务拒收轨）。
        未知 kind/action 及坏持久 schema 裸 ValueError 上抛（#1897 E1），
        不得标 failed/invalid_state 伪装业务拒收。
        office(任免)落库需 content；缺则返 False(标 failed,不静默)。
        """
        if pa["kind"] == "office":
            return self._materialize_office_appointment_dossier(
                state, pa, payload, content=content,
            )
        if pa["kind"] == "secret_order":
            oid = pa["target_id"]
            action = pa["action"]
            _SECRET_ORDER_ACTIONS = {
                "新建", "更新", "催办", "提交核议", "记进展",
            }
            # 未知内部动作先于目标缺省检查；禁 oid is None 把 schema 故障洗成业务 False（#1897 E1）。
            if action not in _SECRET_ORDER_ACTIONS:
                raise ValueError(f"未知内部动作 secret_order/{action}")
            if action == "新建":
                # 自由文本零删改（CLAUDE.md P6）：判空在副本上做，存的仍是原文。
                # 已持久散文：禁 str() 洗类型；空缺／非 str 响亮（#1897 E1）。
                title = payload.get("title")
                content_text = payload.get("content")
                if "assignee" in payload and payload.get("assignee") is not None:
                    assignee = payload.get("assignee").strip()
                else:
                    assignee = str(pa["minister_name"] or "").strip()
                if not assignee:
                    raise ValueError("持久字段 assignee 不得为空")
                # 可选集合：缺省合法空；present 非 list/非 str 成员响亮（#1897 E1）。
                # 禁 payload.get(key) or [] 的 falsy 洗空。
                lists = {}
                for field in ("tags", "excluded_names", "excluded_offices"):
                    value = payload.get(field)
                    if value is None:
                        value = []
                    surface = f"pending_actions#{pa['id']}.payload.{field}"
                    if not isinstance(value, list):
                        raise TypeError(f"{surface} must be a list, got {value!r}")
                    lists[field] = _load_durable_str_list(value, surface=surface)
                tags = lists["tags"]
                # 已持久期限：类型腐坏响亮，不伪装领域拒收（#1897 E1）。
                deadline = _coerce_deadline_months(
                    payload.get("deadline_months"), default=0, durable=True,
                )
                # pa["minister_name"] = audience speaker who captured the oral
                # decree; may differ from final assignee (跨人承办).
                # 已持久暂存载荷：源钉 durable 解码（#1897 E1）。
                origin_mid = self._parse_origin_chat_message_id(
                    payload,
                )
                from ming_sim.covert_progress import (
                    CovertContractError,
                    build_covert_task_contract,
                    covert_task_from_payload,
                )
                raw_task = covert_task_from_payload(payload) or payload.get("covert_task")
                # 准入已要求 covert_task；已持久缺/坏 = schema 腐坏，裸 ValueError（#1897 E1）。
                if not raw_task:
                    raise ValueError("持久密令缺 covert_task")
                try:
                    frozen_task = build_covert_task_contract(covert_task=raw_task)
                except CovertContractError as exc:
                    raise ValueError(
                        f"持久 covert_task 契约腐坏：{exc}",
                    ) from exc
                order_id = self.create_secret_order(
                    state, assignee, title, content_text, tags, deadline_months=deadline,
                    origin_chat_message_id=origin_mid,
                    origin_chat_message_ids=[] if origin_mid is None else None,
                    pending_action_id=int(pa["id"]),
                    covert_task=frozen_task,
                    # 各自所属事务（ADR 0154）：声明的事务归属随暂存载荷进成案
                    # payload，由既有绑定核（_resolve_affair_id_from_payload）落
                    # pointer——不在密令路上另实现一份绑定。
                    affair_declaration=(
                        payload.get("affair_declaration")
                        if isinstance(payload.get("affair_declaration"), Mapping)
                        else None
                    ),
                )
                if order_id is not None and payload.get("dossier_links") is not None:
                    links = payload.get("dossier_links")
                    if not isinstance(links, list):
                        raise ValueError("持久密令 dossier_links 须为列表")
                    dossier = self.dossiers.get_for_secret_order(int(order_id))
                    if dossier is None:
                        raise ValueError("密令成案后未找到案卷")
                    self.dossiers.add_links(
                        int(dossier["id"]), links, commit=False,
                    )
                return order_id is not None
            if oid is None:
                return False
            # Non-create actions consume only explicit source pins.
            # 已持久暂存载荷：源钉 durable 解码（#1897 E1）。
            origin_mid = self._parse_origin_chat_message_id(
                payload,
            )
            if action == "更新":
                deadline = _coerce_deadline_months(
                    payload.get("deadline_months"), default=0, durable=True,
                )
                # 已持久更新正文禁 str() 洗类型（#1897 E1）。
                new_title = payload.get("new_title")
                new_content = payload.get("new_content")
                # No pin → update_secret_order_by_id preserves brief pins (no pure-public auto-capture).
                return self.update_secret_order_by_id(
                    state, int(oid),
                    new_title,
                    new_content,
                    tags=None, deadline_months=deadline,
                    origin_chat_message_id=origin_mid,
                )
            if action == "催办":
                deadline = _coerce_deadline_months(
                    payload.get("deadline_months", 1), default=1, durable=True,
                )
                # 已持久催办理由：空陈词合法；坏类型响亮（#1897 J820-E1）。
                rush_reason = payload.get("reason", "")
                self.rush_secret_order(
                    int(oid), state, deadline_months=deadline, reason=rush_reason)
                if origin_mid is not None:
                    order = self.character_knowledge.get_secret_order(int(oid))
                    if order is not None:
                        self._classify_secret_order_audience(
                            state, int(oid), str(order["minister_name"]),
                            str(order.get("title") or ""), str(order.get("content") or ""),
                            origin_chat_message_id=origin_mid,
                        )
                return True
            if action == "提交核议":
                # 已持久核议陈词：空串只缩期限；坏类型 schema 故障（#1897 J820-E1）。
                claim = payload.get("claim", "")
                ok = self.submit_secret_order_for_review(
                    int(oid), claim)
                if ok and origin_mid is not None:
                    order = self.character_knowledge.get_secret_order(int(oid))
                    if order is not None:
                        self._classify_secret_order_audience(
                            state, int(oid), str(order["minister_name"]),
                            str(order.get("title") or ""), str(order.get("content") or ""),
                            origin_chat_message_id=origin_mid,
                        )
                return ok
            if action == "记进展":
                # 已持久进展正文：空串按写口合同不落条；坏类型响亮（#1897 J820-E1）。
                note = payload.get("note", "")
                ok = self.update_secret_order_progress(
                    int(oid), note)
                if ok and origin_mid is not None:
                    order = self.character_knowledge.get_secret_order(int(oid))
                    if order is not None:
                        self._classify_secret_order_audience(
                            state, int(oid), str(order["minister_name"]),
                            str(order.get("title") or ""), str(order.get("content") or ""),
                            origin_chat_message_id=origin_mid,
                        )
                return ok
        # #624 / ADR 0078：分段承诺催办——经 pending_actions 确认闸门到唯一写口
        if pa["kind"] == "commitment" and pa["action"] == "催办":
            target_id = pa.get("target_id")
            if target_id is None:
                return False
            raw_stage = payload.get("stage_idx")
            # 已持久 stage_idx：缺省／类型腐坏一律裸 ValueError，不发明身份 0（#1897 G）。
            # 准入侧坏值仍走声明路径 DecreeMaterializationValidationError。
            # 拒收形状复用 strict_int（含 None／空串），不另造前置或重包文案。
            stage_idx = strict_int(raw_stage, accept_numeric_strings=False)
            deadline = _coerce_deadline_months(
                payload.get("deadline_months", 1), default=1, durable=True,
            )
            # 已持久催办理由：空陈词合法；坏类型响亮（#1897 J820-E1）。
            commitment_reason = payload.get("reason", "")
            if not isinstance(commitment_reason, str):
                raise TypeError(
                    f"pending_actions#{pa['id']}.payload.reason must be text, got {commitment_reason!r}"
                )
            from ming_sim.urge_lever import rush_staged_commitment_stage
            result = rush_staged_commitment_stage(
                self, state,
                commitment_ref=int(target_id),
                stage_idx=stage_idx,
                deadline_months=deadline,
                reason=commitment_reason,
                record_history=False,  # 本 pending 行标 committed 即史源，禁双插
            )
            # 史源字段写回本行 payload（commit_pending_actions 随后标 committed）。
            # reason 回写已校验的 staged 原文，不吃写口缺省替换（#1897 空白原文）。
            merged = dict(payload)
            merged.update({
                "stage_idx": int(stage_idx),
                "old_due": int(result["old_due"]),
                "new_due": int(result["due_turn"]),
                "deadline_months": int(result["deadline_months"]),
                "tightness": max(0, int(result["old_due"]) - int(result["due_turn"])),
                "reason": commitment_reason,
            })
            self.dossiers.set_pending_payload(
                int(pa["id"]),
                json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
            )
            return True
        if pa["kind"] == "directive" and pa["action"] == "拟旨":
            payload = dict(payload)
            if payload.pop("_canonical_pending_directive", False) is not True:
                payload = self._normalize_directive_dossier_payload(
                    payload, content=content, current_turn=int(state.turn),
                )
            text = payload.get("text")
            actor_raw = payload.get("actor", pa["minister_name"] or "")
            if actor_raw is None:
                actor_raw = ""
            actor = actor_raw.strip()
            # actor FK → characters(name)：空串/非名册不得落库（SQLite FK 不接受空串）。
            if actor and self.characters.row(actor, fields="1") is None:
                actor = ""
            actor_db = actor or None
            status = "pending" if str(payload.get("_directive_status") or "draft") == "pending" else "draft"
            # 不回到颁诏 checkpoint 时默认同意为 draft；召对里明确应允只表示接受为候选，
            # 仍写成 pending 交给既有准/驳界面，避免绕过后续颁诏流程（#412）。
            cur = self.issues.insert_directive(
                state.turn,
                state.year,
                state.period,
                None,
                actor_db,
                text,
                "大臣拟旨",
                status,
                f"由{actor}拟旨入档" if actor else "拟旨入档",
                json.dumps(payload, ensure_ascii=False),
                int(pa["id"]),
            )
            # #1890 / ADR 0054：拟旨行（后生）单向指回它所落的交办暂存（先落）。
            # 旧实现把 draft 行 id 回填进 pending_actions.committed_directive_id，
            # 那是「先落的实体反指后生」——族规禁双向互写，且两处可写会漂移。
            # 撤回要精确删本轮自产草案时，按这一列从新指旧读，不再反查。
            did = int(cur.lastrowid)
            # pending 只是皇帝核定前的候选，不是 ADR 0051 的成案点；默认同意进入
            # draft 时则已越过最终提交边界，应当立即取得案卷身份。
            # #658：与 free-form / confirm 共吃 _ensure_directive_dossier（含御笔强推）。
            if status == "draft":
                dossier_ids = self._ensure_directive_dossier(
                    state, did, text, payload, commit=False,
                )
                # conversational commit 的 pending_action_id 绑回案卷（push 复用路径
                # 只写 directive_id，普通 create 路径本就带 pending_action_id）
                self.conn.execute(
                    'UPDATE decree_dossiers SET pending_action_id=? WHERE '
                    'directive_id=? AND (pending_action_id IS NULL OR '
                    'pending_action_id=0 OR pending_action_id=?)',
                    (int(pa['id']), did, int(pa['id'])),
                )
                # #1842：载荷背书随成案继承到案卷（来源仍为声明轮）。
                for dossier_id in dossier_ids or []:
                    self.dossiers.inherit_payload_endorsements(
                        int(dossier_id), payload, commit=False,
                    )
                # ADR 0028 / #1837：组合载荷（拨帑±任免）同一份 pending 同时产任免案卷；
                # 任免字段只进 appointment 案卷，禁把 grant 的 execution_surface 带过去。
                if not self._materialize_combined_appointment_from_directive(
                    state, pa, payload, content=content,
                ):
                    return False
            return True
        # 未知 kind/action 是内部 schema 故障，不得标 failed+业务 invalid_state（#1897 E1）。
        raise ValueError(
            f"未知内部动作 {pa.get('kind')}/{pa.get('action')}"
        )

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
            "appointment_tenure", "任别", "faction",
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
        # #1897：声明正文原样；仅真正空串才视作缺省，禁 strip 判空改 None。
        return self._materialize_office_appointment_dossier(
            state, office_pa, sliced, content=content,
            decree_text=decree_text if decree_text else None,
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
            row = self.characters.row(canonical, fields="status, power_id")
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
            # settlement.dossier._commit_office_action -> apply_office_appointment 完成。
            from ming_sim.models import Character
            from ming_sim.session import canonical_new_appointment_person_fields
            character = Character(
                name=name, office="待选", office_type="未仕",
                aliases=[], personal_skills=[], power_id="ming",
                status="offstage",
                **canonical_new_appointment_person_fields(payload.get("faction")),
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
            self.dossiers.inherit_payload_endorsements(
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
        """返回批前盘面中确实不匹配的荐人快照案号；其他异常原样上抛。

        dossiers 须为 canonical 案卷行（DossierStore.get/list_dossiers 已解码 payload）。
        """
        invalid = set()
        for row in dossiers:
            if str(row.get("action_type") or "") != "appointment":
                continue
            payload = row["payload"]
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


    def void_pending_actions_for_chat_turn(self, chat_turn_id: int) -> List[int]:
        """#1890：按来源轮整轮作废该轮的交办暂存，返回被作废的 id。

        这是本票要的「暂存一张表存着，拿到统一的 id 就知道撤回了谁」：判据
        只有 ``pending_actions.source_chat_turn_id``，不扫
        ``chat_turn_rollback_items``、不比对前像、也不问是哪句话说的。

        作废而非删行（ADR 0038 2026-09-29 owner 裁定）：行留着当墓碑，
        迟到的写入或补跑读它只会看到 ``voided``，不会把已撤回的交办复活。
        仍可应允的 ``pending`` 之外的终态（committed / failed / held_over）
        一律不动——它们已不是「暂存」，逆转归 ``undo_chat_turn`` 的前像日志。

        不 commit：调用方（撤回事务）持有边界，本方法只在其事务内写。
        """
        ctid = int(chat_turn_id or 0)
        if ctid <= 0:
            return []
        # 与 _pending_action_owned_by_turn_in_tx 同一判据（同源轮 + 仍 pending）。
        rows = self.conn.execute(
            'SELECT id, kind, version FROM pending_actions WHERE source_chat_turn_id '
            "= ? AND status = 'pending' ORDER BY id",
            (ctid,),
        ).fetchall()
        voided: List[int] = []
        for row in rows:
            action_id = int(row["id"])
            if str(row["kind"] or "") == "directive":
                # 该道拟旨的夜里预推产物随交办一起作废（预推生命周期归 #1816，
                # 但它挂在这一道交办的身份下，不作废就会在过月时复活）。
                self._discard_pending_decree_forecast(
                    action_id, int(row["version"] or 1),
                )
            self.conn.execute(
                "UPDATE pending_actions SET status='voided', night_approved=0 WHERE "
                "id=? AND status='pending'",
                (action_id,),
            )
            voided.append(action_id)
        return voided


    def withdraw_pending_action(self, action_id: int, turn: int) -> bool:
        """皇帝复核:撤回本回合一条尚未落库的暂存动作(删 pending 行)。返回是否删了。
        已 committed / 非本回合 / 不存在 → False。"""
        owns_transaction = connection_owns_transaction(self.conn)
        row = self.conn.execute(
            "SELECT id, kind, version FROM pending_actions WHERE id=? AND turn=? AND status='pending'",
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
        if owns_transaction:
            self.conn.commit()
        return cur.rowcount > 0


    def list_world_effect_history(
        self, origin: str,
    ) -> Dict[str, object]:
        """Read landed effects for a world affair file; never include staged verdicts.

        Dossier callers retain the existing actual rail. Audit log / person_logs
        whole-row dumps stay out of material supply (#1834 F12); four textual-fact
        rails remain #1873's job.
        """
        from ming_sim.entities.affair.store import parse_origin_ref

        kind, target = parse_origin_ref(origin)
        actual = self.list_durable_effects_for_origin(origin)
        if kind == "dossier":
            actual = [dict(row, rail="durable_effect") for row in actual]
            actual.extend(
                dict(row, rail="actual_progress")
                for row in self.conn.execute(
                    'SELECT * FROM dossier_actual_progress WHERE dossier_id=? ORDER BY turn, id',
                    (target,),
                ).fetchall()
            )
        history: Dict[str, object] = {"实况轨": actual}
        if kind == "affair":
            for table, store in (
                ("issues", self.issues),
                ("characters", self.characters),
                ("relation_edge_events", self.person_logs),
            ):
                # Person details already have their P4-safe roster/experience files.
                # Keep only the affair membership, not an unprojected character dump.

                history[table] = [dict(row) for row in store.rows_for_affair(target)]
            for row in history["issues"]:
                for field in ("tags", "participants", "target_roster"):
                    row[field] = _load_durable_str_list(row[field], surface=f"issues#{row['id']}.{field}")
                from ming_sim.participant_roster import decode_durable_participant_roster
                row["participant_roster"] = decode_durable_participant_roster(
                    row["participant_roster"], require_tier=False,
                )
                from ming_sim.staged_commitment import load_commitment_stages
                row["stages_json"] = load_commitment_stages(row["stages_json"])
                for field in (
                    "ongoing_effects", "effect_on_resolve", "effect_on_fail",
                ):
                    row[field] = loads_effect_dict(row[field])
                # The numeric stop gate is an execution detail, not a second
                # explanation of the issue's human resolve/fail conditions.
                row.pop("stop_condition", None)
        return history

    def list_durable_effects_for_origin(self, origin: str) -> List[Dict[str, object]]:
        """Economy/fiscal merge shared by dossier and direct affair origins."""
        return self.reign.list_economy_moves_for_origin(origin) + self.fiscal_config.effects_for_origin(origin)

    def capture_month_open_snapshot(self, state: GameState) -> bool:
        """点击受理：独立提交点击前四键 + 所属回合。已有本回合行则不覆盖（幂等）。

        必须在任何盘面突变之前调用，且不进 pre_settle 事务——否则回滚会毁掉刷新同脸。
        原子 INSERT ON CONFLICT DO NOTHING：返回 True 仅当本调用新建行（rowcount==1），
        供 accept 裁定创建者；禁 SELECT 预检/后置见行假 True。
        """
        turn = int(state.turn)
        m = state.metrics
        cur = self.month_open_snapshots.insert_once(
            turn=turn,
            treasury=int(m.get("国库", 0)),
            inner_treasury=int(m.get("内库", 0)),
            public_support=int(m.get("民心", 0)),
            imperial_prestige=int(m.get("皇威", 0)),
        )
        self.conn.commit()
        return cur

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
        for entry in decode_durable_participant_roster(dossier.get("participant_roster")):
            if entry["tier"] not in {"主办", "协办"}:
                continue
            actors.add(entry["character_id"])
        target_kind = str(dossier.get("target_kind") or "").strip()
        target_id = str(dossier.get("target_id") or "").strip()
        domains: set[str] = set()
        if target_kind and target_id:
            domains.add(f"{target_kind}:{target_id}")
        if not actors or not domains:
            return []
        projected: List[Dict[str, object]] = []
        for holder_id in sorted(actors):
            for row in self.characters.list_active_authorities(int(turn), holder_id=holder_id):
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


    def _load_directive_pending_source(
        self, directive_id: int,
    ) -> Tuple[int, int]:
        """持久读 turn_directives→pending 来源身份；(pending_action_id, source_chat_turn_id)。

        整段查询与列解码任一失败均为账本/代码故障（RuntimeError），不得落入
        ensure 产物 ValueError 捕获（F39）。无 pending 关联 → (0, 0)。
        """
        try:
            pending = self.conn.execute(
                """
                SELECT pa.id, pa.source_chat_turn_id
                FROM turn_directives td
                JOIN pending_actions pa ON pa.id = td.source_pending_action_id
                WHERE td.id = ?
                ORDER BY pa.id DESC LIMIT 1
                """,
                (int(directive_id),),
            ).fetchone()
            if pending is None:
                return 0, 0
            return int(pending["id"]), int(pending["source_chat_turn_id"] or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"旨稿#{directive_id} pending 来源持久读失败"
            ) from exc

    def _ensure_directive_dossier(
        self, state: GameState, directive_id: int, text: str,
        payload: Optional[Dict[str, object]] = None, *,
        pending_source: Optional[Tuple[int, int]] = None,
        commit: bool = True,
    ) -> List[int]:
        """旧式/新式旨稿共用的幂等成案口；返回已成案 dossier id 列表（#1778 起 national 亦单行）。

        御笔强推归批红原案 decision_key，本口不再接自由下旨的旧旁路。
        """
        owns_transaction = connection_owns_transaction(self.conn) if commit else False
        structured = dict(payload or {})
        if not structured:
            raise ValueError("旨意缺少结构化载荷，拒绝成案")
        if classify_directive_structured_kind(structured) == "push":
            raise ValueError("御笔强推须从批红以原案 decision_key 提交，不经手拟或召对成案")
        structured = self._normalize_directive_dossier_payload(
            structured, content=self.content, current_turn=int(state.turn),
        )
        action_type = self._directive_dossier_action_type(structured)
        target_kind = str(structured.get("target_kind") or "").strip()
        target_id = str(structured.get("target_id") or "").strip()
        if not target_kind or not target_id:
            from ming_sim.action_materialize import DecreeMaterializationValidationError
            raise DecreeMaterializationValidationError(
                "普通旨意缺少受控目标，拒绝成案",
                failed_fields=("target_kind", "target_id"),
            )
        executor_kind, executor_id = self._directive_executor(action_type, structured)
        # 来源身份只认 pending_actions，不回落载荷副本。
        if pending_source is None:
            pending_source = self._load_directive_pending_source(int(directive_id))
        pending_action_id, dossier_source_turn = pending_source
        return self.create_decree_dossiers(
            state,
            action_type=action_type,
            decree_text=text,
            target_kind=target_kind,
            target_id=target_id,
            executor_kind=executor_kind,
            executor_id=executor_id,
            source_chat_turn_id=dossier_source_turn,
            pending_action_id=pending_action_id,
            directive_id=int(directive_id),
            payload=structured,
            due_turn=int(structured.get("due_turn") or 0),
            commit=commit,
        )


    def ensure_dossiers_for_draft_directives(
        self, state: GameState, *,
        record_rejections: bool = True,
    ) -> List[Dict[str, object]]:
        """结束边界成案：只读最新 draft 正文/载荷，按 directive_id 幂等创建。

        #654 r3-C.2 路3：每道旨独立 SAVEPOINT；单旨产物错记 rejection、保持 draft，不波及他旨。
        #1769/#1897 E1：产物错（ValueError，含 DMVE/PayOrderKeyError）逐项留痕；
        已持久载荷损坏与真代码故障不得洗成 locality_fanout_failed——回滚后写错误包
        并 SettlementAbort（0005/0008 D1/D6）。
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
                for row in self.issues.list_directives(state.turn, statuses=('draft',)):
                    did = int(row["id"])
                    # 已有案卷：幂等跳过（补交重跑 ensure 时不重复建）
                    if self.dossiers.get_for_directive(did) is not None:
                        continue
                    # 持久读全部在产物 ValueError 捕获之外（F39）：载荷、pending 来源。
                    payload = self.issues.directive_dossier_payload(row)
                    pending_source = self._load_directive_pending_source(did)
                    sp = f"ensure_directive_{did}"
                    from ming_sim.action_materialize import is_declaration_domain_error

                    try:
                        with item_savepoint_scope(self, sp):
                            # Only existing domain contract errors become item refusals.
                            self._ensure_directive_dossier(
                                state,
                                did,
                                str(row["text"]),
                                payload,
                                pending_source=pending_source,
                                commit=False,
                            )
                    except Exception as exc:
                        if is_declaration_domain_error(exc):
                            reason = str(exc)
                            rejection_rows.append(
                                {"directive_id": did, "reason": reason},
                            )
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
                        else:
                            code_fault = exc
                            tlog(f"[ensure_dossiers] 旨#{did} 成案系统故障：{exc}")
                            raise
                if record_rejections:
                    collector.flush_to_db(self)
        except Exception as exc:
            if code_fault is None:
                code_fault = exc
            # atomic 已回滚；错误包须在事务外写（write_error_pack 约束）
            pack_path = write_error_pack(
                self, state, exc=code_fault,
            )
            raise SettlementAbort(
                settlement_abort_message(pack_path, reason=str(code_fault)),
                turn=int(state.turn),
                stage="directive_ensure",
                error_pack_path=pack_path,
            ) from code_fault
        if record_rejections:
            from ming_sim.applier import mirror_rejections_after_commit
            mirror_rejections_after_commit(self, collector, rejections_jsonl_path)
        return rejection_rows


    def update_directive_text(
        self, directive_id: int, text: str, *,
        dossier_payload: Optional[Dict[str, object]] = None,
        replace_payload: bool = False,
    ) -> None:
        """改草 draft 正文/载荷。

        replace_payload=True（#1769 结算补交）：整份采用新 payload，不经 merge——
        避免 pay_order entries 等旧键残留到新动作类型上。默认 False 保持改草合并语义。
        """
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        if self.dossiers.get_for_directive(directive_id) is not None:
            raise DecreeMaterializationValidationError("已成案旨意不得编辑")
        row = self.conn.execute(
            'SELECT dossier_payload_json FROM turn_directives WHERE id=?',
            (directive_id,),
        ).fetchone()
        if row is None:
            raise DecreeMaterializationValidationError("旨意不存在")
        incoming = dict(dossier_payload or {})
        if replace_payload:
            payload = incoming
        else:
            payload = self._merge_directive_payload(
                row["dossier_payload_json"], incoming,
            )
        if not directive_payload_admits_structured_write(payload):
            raise DecreeMaterializationValidationError(
                "旨意编辑须提供完整结构化动作与目标",
            )
        with atomic(self):
            self.conn.execute(
                "UPDATE turn_directives SET text=?, dossier_payload_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (text, json.dumps(payload, ensure_ascii=False), directive_id)
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
        self.conn.execute(
            """
            UPDATE turn_directives
            SET status = 'issued', updated_at = CURRENT_TIMESTAMP
            WHERE turn <= ? AND status = 'draft'
              AND EXISTS (
                  SELECT 1 FROM decree_dossiers d
                  WHERE d.directive_id=turn_directives.id
              )
            """,
            (state.turn,),
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
        self.issues.record_event_terminal(
            event_id, turn=state.turn, year=state.year, period=state.period,
            source=source, terminal_state="triggered", terminal_reason=str(terminal_reason or ""),
        )
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
        self.issues.record_event_terminal(
            event_id, turn=state.turn, year=state.year, period=state.period,
            source=source, terminal_state="avoided", terminal_reason=reason,
        )
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
        self.issues.record_event_terminal(
            event_id, turn=state.turn, year=state.year, period=state.period,
            source=source, terminal_state="obsolete", terminal_reason=reason,
        )
        if commit:
            self.conn.commit()

    def mark_event_expired(self, state: GameState, event_id: str, *, commit: bool = True) -> None:
        self._ensure_event_parent(event_id)
        self.issues.record_event_terminal(
            event_id, turn=state.turn, year=state.year, period=state.period,
            source="window_expired", terminal_state="expired", terminal_reason="过最晚触发时点仍未达成触发门",
        )
        if commit:
            self.conn.commit()


    def record_event_petition_answer(
        self,
        state: GameState,
        event_id: str,
        answer: Dict[str, object],
        presented: Dict[str, object],
        *,
        commit: bool = True,
    ) -> None:
        """三饷请旨：把「已呈奏疏 + 皇帝原批语」整份 durable 落进事件账（#1892）。

        本方法是请旨答复的**唯一**持久写口，且**只记账、不置结局**：

        - 落 ``choice_json`` 的 ``petition`` 段（呈疏原文、选项、皇帝 label/hint/note），
          供后续世界段据 :meth:`list_event_petition_records` 取回复呈（#1891 供料契约）。
        - ``terminal_state`` 恒留空、``terminal_reason`` 恒留空：亲笔准驳的**结局标签由
          语义转译写口置定**（:func:`ming_sim.entities.issue.event_terminal.apply_petition_event_outcome`），
          不由这里的原始选项标签旁路代批（ADR 0153:5、#1891 亲裁契约）。
        - 「留中」是本疏已答而事件未终：不写终态，事件仍留在请旨候选里等下次呈报。

        冲突时**只**补 ``choice_json``，绝不把既有 avoided/expired/obsolete/triggered
        终态翻动——与 :meth:`record_event_decision_choice` 同款终态不可逆纪律。
        """
        eid = str(event_id or "").strip()
        if not eid:
            return
        self._ensure_event_parent(eid)
        payload = json.dumps(
            {
                **{
                    key: value for key, value in (answer or {}).items()
                    if isinstance(answer, dict)
                },
                "petition": {
                    "presented_turn": int(state.turn),
                    "presented_year": int(state.year),
                    "presented_period": int(state.period),
                    **{key: value for key, value in (presented or {}).items()},
                },
            },
            ensure_ascii=False,
        )
        self.conn.execute(
            """
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason, choice_json)
            VALUES (?, ?, ?, ?, 'petition', '', '', ?)
            ON CONFLICT(event_id) DO UPDATE SET
                -- 请旨账只补 choice_json（已呈奏疏 + 原批语）；终态与来源一律沿用既有行，
                -- 空终态行也不在此写 terminal_reason：结局标签归语义写口，不归原始选项标签。
                choice_json = excluded.choice_json
            """,
            (eid, state.turn, state.year, state.period, payload),
        )
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
        label = str((choice or {}).get("label") or "") if isinstance(choice, dict) else ""
        self.conn.execute(
            """
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason, choice_json)
            VALUES (?, ?, ?, ?, ?, '', ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                -- 普通事件选择暂存；终态不可逆。三饷亲裁不走本写口。
                source = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') IN ('', 'triggered')
                    THEN excluded.source
                    ELSE event_triggers.source
                END,
                terminal_state = event_triggers.terminal_state,
                terminal_reason = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.terminal_reason
                    WHEN COALESCE(event_triggers.terminal_reason, '') = ''
                    THEN excluded.terminal_reason
                    ELSE event_triggers.terminal_reason
                END,
                choice_json = excluded.choice_json
            """,
            (eid, state.turn, state.year, state.period, source, label, payload),
        )
        if commit:
            self.conn.commit()


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
        cur = self.conn.execute(
            """
            INSERT INTO issues (
                kind, title, origin_kind, origin_ref, origin_turn,
                bar_value, bar_good_meaning, bar_bad_meaning, inertia,
                phase, stage_text, status, severity, region_hint, faction_hint,
                tags, participants, participant_roster, target_roster, ongoing_effects, cancellable,
                effect_on_resolve, effect_on_fail, resolve_condition, fail_condition,
                end_turn, stop_condition, commitment_kind, stages_json, last_advance_turn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                title,
                origin_kind,
                origin_ref,
                state.turn,
                bar_value,
                bar_good_meaning,
                bar_bad_meaning,
                int(inertia),
                phase,
                stage_text,
                severity,
                region_hint,
                faction_hint,
                safe_json_dumps(tags or [], ensure_ascii=False),
                safe_json_dumps(participant_names, ensure_ascii=False),
                safe_json_dumps(participant_roster, ensure_ascii=False),
                safe_json_dumps(normalized_targets, ensure_ascii=False),
                safe_json_dumps(ongoing_effects or {}, ensure_ascii=False),
                cancellable,
                safe_json_dumps(effect_on_resolve or {}, ensure_ascii=False),
                safe_json_dumps(effect_on_fail or {}, ensure_ascii=False),
                resolve_condition,
                fail_condition,
                int(end_turn),
                safe_json_dumps(stop_condition, ensure_ascii=False, separators=(',', ':')) if isinstance(stop_condition, dict) else '' if not str(stop_condition or '').strip() else str(stop_condition),
                str(commitment_kind or ''),
                stages_blob,
                state.turn,
            ),
        )
        issue_id = int(cur.lastrowid)
        self.affairs.bind_from_origin_ref("issues", issue_id, origin_ref)
        if commit:
            self.conn.commit()
        return int(cur.lastrowid)

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

        outer_owns = not connection_owns_transaction(self.conn)
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
        row = self.issues.row(issue_id)
        if row is None or row["status"] != "active":
            return None
        # 崩坏能力由 effect_on_fail 是否非空判定：有崩坏效果=会崩坏（bar 能到 0、failed 终结）；
        # 空=不会崩坏（天灾/正面机遇等不可控或无失败态局势，bar 下限钳到 1，永不 failed，
        # 只靠 ongoing_effects 每月持续流血）。
        can_collapse = bool(loads_effect_dict(row["effect_on_fail"]))
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
        # commitment_kind / structured stop_condition JSON only (#1847 N11: retired
        # resolve_condition prose→gate regex half deleted with issues.py write half).
        commitment_stop_condition = bool(row["commitment_kind"]) or has_stop_condition
        if to_value >= 100 and not commitment_stop_condition:
            new_status = "resolved"
            closed_turn = state.turn
        elif to_value <= 0 and can_collapse:
            new_status = "failed"
            closed_turn = state.turn
        # inertia 可被本次行动改变（钳到 -10..+10 五档区间）
        new_inertia = int(row["inertia"]) + int(inertia_delta)
        new_inertia = max(-10, min(10, new_inertia))
        self.issues.update(
            issue_id,
            {
                "bar_value": to_value,
                "phase": new_phase,
                "stage_text": to_stage_text,
                "status": new_status,
                "inertia": new_inertia,
                "closed_turn": closed_turn,
                "last_advance_turn": state.turn,
            },
        )
        self.issues.insert_advance(
            issue_id,
            state.turn,
            trigger_kind,
            trigger_ref,
            actual_delta,
            from_value,
            to_value,
            from_stage_text,
            to_stage_text,
            narrative,
            safe_json_dumps(metric_delta or {}, ensure_ascii=False),
        )
        if commit:
            self.conn.commit()
        return self.issues.row(issue_id)

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
        row = self.issues.row(issue_id)
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
        self.issues.update(
            issue_id,
            {
                "bar_value": to_value,
                "phase": new_phase,
                "stage_text": to_stage_text,
                "status": reason,
                "closed_turn": state.turn,
                "last_advance_turn": state.turn,
            },
        )
        self.issues.insert_advance(
            issue_id,
            state.turn,
            "close",
            reason,
            actual_delta,
            from_value,
            to_value,
            from_stage_text,
            to_stage_text,
            narrative,
            "{}",
        )
        if commit:
            self.conn.commit()
        return self.issues.row(issue_id)

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
        clear_gate 非空时：靠程序按 _gate_passed 判定消除（见 ming_sim.entities.issue.legacy.clear_gated_legacies），与时长无关。"""
        start_month = int(state.year) * 12 + int(state.period)
        cur = self.reign.insert_legacy(
            str(name or ""),
            source_issue_id,
            json.dumps(modifiers, ensure_ascii=False),
            str(narrative_hint or ""),
            start_month,
            int(duration_months),
            json.dumps(clear_gate or {}, ensure_ascii=False),
            str(legacy_key or ""),
        )
        if commit:
            self.conn.commit()
        self._legacy_mod_cache = None  # active 集变了，修正符缓存失效
        return int(cur.lastrowid)

    def list_active_legacies(self, state: GameState) -> List[sqlite3.Row]:
        """当前仍生效的帝国修正，顺手把已到期的失活。"""
        external_transaction = not connection_owns_transaction(self.conn)
        self.expire_legacies(state, commit=not external_transaction)
        return self.conn.execute(
            "SELECT * FROM legacies WHERE status='active' ORDER BY id",
            (),
        ).fetchall()

    def expire_legacies(self, state: GameState, commit: bool = True) -> List[int]:
        """到期失活：当前月 >= start_month + duration_months（永久 -1 永不到期）。"""
        now = int(state.year) * 12 + int(state.period)
        rows = self.conn.execute(
            "SELECT id, start_month, duration_months FROM legacies WHERE status='active'",
            (),
        ).fetchall()
        expired: List[int] = []
        for r in rows:
            dur = int(r["duration_months"])
            if dur < 0:
                continue
            if now >= int(r["start_month"]) + dur:
                expired.append(int(r["id"]))
        if expired:
            self.reign.set_legacy_statuses("expired", expired)
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
        cache_allowed = connection_owns_transaction(self.conn)
        self.expire_legacies(state, commit=cache_allowed)
        if cache_allowed and self._legacy_mod_cache is not None:
            return self._legacy_mod_cache
        agg: Dict[str, object] = {k: 0 for k in GATE_METRIC_KEYS}
        agg["regions"] = {}
        agg["armies"] = {}
        for lg in self.conn.execute(
            "SELECT modifiers FROM legacies WHERE status='active' ORDER BY id",
            (),
        ).fetchall():
            eff = _load_durable_json(lg["modifiers"], default='{}')
            for acc in ("国库", "内库", "民心", "皇威"):
                v = eff.get(acc)
                if v is not None:
                    agg[acc] = int(agg[acc]) + int(v)
            for scope in ("regions", "armies"):
                block = _load_durable_json_object(eff.get(scope), surface=f"legacies.modifiers.{scope}")
                dst = agg[scope]  # type: ignore[assignment]
                for entity_id, fields in block.items():
                    bucket = dst.setdefault(str(entity_id), {})  # type: ignore[union-attr]
                    for field, pct in fields.items():
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
        row = self.issues.row(issue_id)
        if row is None or row["status"] != "active":
            return None
        self.issues.update(
            issue_id,
            {
                "status": "dropped",
                "closed_turn": state.turn,
                "last_advance_turn": state.turn,
            },
        )
        self.issues.insert_advance(
            issue_id,
            state.turn,
            "cancel",
            "",
            0,
            int(row["bar_value"]),
            int(row["bar_value"]),
            "",
            "",
            narrative,
            json.dumps(applied_cost or {}, ensure_ascii=False),
        )
        if commit:
            self.conn.commit()
        return self.issues.row(issue_id)


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
        if apply_income_modifier and category != "局势遗产":
            net_pct = int(self.legacy_modifiers(state).get(account, 0) or 0)  # type: ignore[arg-type]
            if net_pct and delta > 0:
                delta = self.apply_legacy_pct(int(delta), net_pct)
        if account not in ECONOMY_ACCOUNTS:
            raise ValueError(f"economy_ledger account 非法：{account!r}")
        before = int(state.metrics[account])
        after = max(0, before + int(delta))
        actual = after - before
        if actual == 0:
            return 0
        state.metrics[account] = after
        beyond_flag = coerce_beyond_intent_flag(beyond_intent)
        self.reign.insert_economy_move(
            state.turn,
            state.year,
            state.period,
            account,
            actual,
            after,
            category,
            reason,
            None,
            None,
            "事项推演",
            purpose,
            target_kind,
            target_id,
            None,
            origin_ref,
            beyond_flag,
        )
        self.reign.upsert_metric(account, after)
        if commit:
            self.conn.commit()
        return actual


    def list_dossier_durable_effects(self, dossier_id: int) -> List[Dict[str, object]]:
        """#1260 单源：案卷 durable_effects = economy + fiscal（已归一 beyond_intent bool）。

        只供事实，不参与裁决形状。构造 origin 后委托合并权威，禁再各写一份合并。
        """
        return self.list_durable_effects_for_origin(f"dossier:{int(dossier_id)}")


    def dossier_has_beyond_intent(self, dossier_id: int) -> bool:
        """#1260 单源：案卷是否含任何旨外 durable effect（economy 或 fiscal）。

        只供事实，不另立裁决函数。
        """
        return any(
            bool(row.get("beyond_intent"))
            for row in self.list_dossier_durable_effects(int(dossier_id))
        )


    # ----- secret_orders（密令系统）-----

    @staticmethod
    def _normalize_participant_roster(
        participants: Iterable[object] | str | None, *,
        strict_structured: bool = False, as_durable: bool = False,
    ) -> List[Dict[str, object]]:
        """Normalize ADR 0053 entries while retaining explicit legacy string input.

        as_durable=True：已持久名册 schema 腐坏 → 裸 ValueError（内部故障）；
        声明严格面 schema 错误 → DMVE（#1897 E1）。
        """
        from ming_sim.action_materialize import DecreeMaterializationValidationError

        if as_durable:
            participants = decode_durable_participant_roster(participants)

        def _schema_error(message: str):
            if as_durable:
                return ValueError(f"已持久名册{message}")
            return DecreeMaterializationValidationError(
                message,
                failed_fields=("participant_roster",),
                category="invalid_participant_roster",
            )

        values = [participants] if isinstance(participants, str) else list(participants or [])
        roster: List[Dict[str, object]] = []
        for value in values:
            if isinstance(value, Mapping):
                if strict_structured:
                    character_raw = value.get("character_id")
                    if not isinstance(character_raw, str):
                        raise _schema_error("参与人物 character_id 须为字符串")
                    character_id = character_raw.strip()
                    tier_value = value.get("tier")
                else:
                    character_id = str(value.get("character_id") or value.get("name") or "").strip()
                    tier_value = value.get("tier") if "tier" in value else value.get("档")
                if strict_structured and not character_id:
                    raise _schema_error("参与人物 character_id 不能为空")
                if strict_structured and tier_value is None:
                    raise _schema_error("参与人物 tier 必须显式提供")
                tier = str(tier_value or ("" if strict_structured else "知情")).strip()
                # 职分是自由文字：原值持久；strip 只作局部判空，不改写（#1897 E2）。
                if "role" in value:
                    role_raw = value.get("role")
                elif "职分" in value:
                    role_raw = value.get("职分")
                else:
                    role_raw = ""
                if role_raw is None:
                    role = ""
                elif not isinstance(role_raw, str):
                    if strict_structured or as_durable:
                        raise _schema_error(
                            f"参与人 role 须为字符串，得 {type(role_raw).__name__}"
                        )
                    role = str(role_raw)
                else:
                    role = role_raw
                delegator_raw = value.get("delegator_id")
                if delegator_raw is None:
                    delegator_raw = value.get("delegator")
                if delegator_raw is None:
                    delegator_raw = ""
                if strict_structured and not isinstance(delegator_raw, str):
                    raise _schema_error("参与人 delegator_id 须为字符串")
                delegator = str(delegator_raw).strip()
            else:
                if strict_structured:
                    raise _schema_error("结构化参与人名单每项必须为对象")
                character_id, tier, role, delegator = str(value).strip(), "知情", "", ""
            if not character_id:
                continue
            if tier not in PARTICIPANT_TIERS:
                # 声明严格面 → 领域拒收；持久/宽松读侧裸 VE（#1897 E1）。
                if strict_structured:
                    raise _schema_error(f"参与人机械档非法：{tier}")
                raise ValueError(f"参与人机械档非法：{tier}")
            item = {"character_id": character_id, "tier": tier, "role": role,
                    "delegator_id": delegator or None}
            if item not in roster:
                roster.append(item)
        return roster

    @staticmethod
    def merge_decode_durable_participant_roster(
        existing: Iterable[object] | None,
        incoming: Iterable[object] | None,
    ) -> List[Dict[str, object]]:
        """载荷侧名单合并：既存持久成员经权威投影校验，incoming 严格规范化后追加。

        与 ``_merge_directive_payload`` 名册分支同一条规则；不按 character_id
        静默丢后项。持久化案卷追加冲突（同人异档）仍走
        ``append_decree_dossier_participants``。既存损坏为内部故障，新声明为领域拒收；
        通用字符串规范化仍由 ``_normalize_participant_roster`` 服务 create_issue
        等合法接缝，本合并口不猜补历史裸名。
        """
        base = GameDB._normalize_participant_roster(
            existing, strict_structured=True, as_durable=True,
        )
        add = GameDB._normalize_participant_roster(
            incoming, strict_structured=True,
        )
        return base + [item for item in add if item not in base]

    def _validate_participant_roster_references(
        self, roster: Iterable[Mapping[str, object]], *,
        as_durable: bool = False,
    ) -> None:
        """Enforce ADR 0053 character primary-key references at the DB write seam.

        as_durable=True：已持久名册坏引用 → 裸 ValueError（内部故障）；
        False：本次声明项 → DMVE（领域拒收）。二者不混（#1897 E1/K2）。
        """
        entries = list(roster)
        referenced = {
            str(value).strip()
            for item in entries
            for value in (item.get("character_id"), item.get("delegator_id"))
            if str(value or "").strip()
        }
        if not referenced:
            return
        known = {
            str(row["name"]) for row in self.characters.named_status_rows(referenced)
        }
        from ming_sim.participant_roster import (
            UnknownParticipantRefError,
            is_non_person_participant_name,
        )

        def _roster_ref_error(label: str, name: str):
            # #1380：拒「皇帝」等非人通称时给人话提示；控制面认类型不认词面（#1902 T2）。
            if is_non_person_participant_name(name):
                msg = (
                    f"{label}不存在：{name}。"
                    f"人物参与人须为朝堂名册中的大臣姓名，"
                    f"不可填「{name}」等非人通称或机构名。"
                    if is_non_person_participant_name(name)
                    else f"请填写朝堂名册中已有的大臣姓名。"
                )
            else:
                msg = (
                    f"{label}不存在：{name}。"
                    f"请填写朝堂名册中已有的大臣姓名。"
                )
            if as_durable:
                return ValueError(f"已持久名册坏引用：{msg}")
            return UnknownParticipantRefError(label, name, msg)


        for item in entries:
            character_id = str(item.get("character_id") or "").strip()
            delegator_id = str(item.get("delegator_id") or "").strip()
            if character_id not in known:
                raise _roster_ref_error("参与人物", character_id)
            if delegator_id and delegator_id not in known:
                raise _roster_ref_error("委派人", delegator_id)

    def _character_knowledge_events(self, character_name: str) -> List[Dict[str, object]]:
        rows = (
            self.conn.execute(
                'SELECT turn, year, period, kind, title, body, source_id FROM '
                "character_knowledge_events WHERE character_name='' ORDER BY turn, id",
                (),
            ).fetchall()
            if not character_name
            else []
        )
        result = []
        for row in rows:
            item = {"turn": int(row["turn"]), "year": int(row["year"]), "period": int(row["period"]),
                    "kind": row["kind"], "title": row["title"], "body": row["body"], "source_id": row["source_id"]}
            result.append(item)
        # #883 contract: this is the sole private read seam for secret orders.
        # Briefs deliberately do not carry a shared source id and therefore
        # cannot be materialized into gazettes or public events.
        if character_name:
            for row in self.conn.execute(
                'SELECT turn, year, period, title, body, order_id FROM '
                'secret_order_briefs WHERE minister_name=? ORDER BY turn, order_id',
                (str(character_name),),
            ).fetchall():
                source_id = f"secret_order_brief:{int(row['order_id'])}"
                result.append({
                    "turn": int(row["turn"]), "year": int(row["year"]),
                    "period": int(row["period"]), "kind": "secret_order_brief",
                    "title": row["title"], "body": row["body"], "source_id": source_id,
                })
        for row in self.conn.execute(
            'SELECT turn, year, period, kind, title, body, source_id, '
            'participant_roster FROM character_knowledge_sources ORDER BY turn, id',
            (),
        ).fetchall():
            names = participant_roster_names(row["participant_roster"])
            if row["kind"] == "public" or not names:
                if character_name:
                    continue
            elif str(character_name) not in names:
                continue
            item = {"turn": int(row["turn"]), "year": int(row["year"]), "period": int(row["period"]),
                    "kind": row["kind"], "title": row["title"], "body": row["body"], "source_id": row["source_id"]}
            result.append(item)
        # Durable records are discovered by their participant_roster column,
        # not by record kind.  This keeps a new producer from needing a reader
        # branch (or a second adapter call) merely to become knowable.
        for row in self.character_knowledge.participant_record_rows():
            source_id = str(row["source_id"])
            names = participant_roster_names(row["participant_roster"])
            if str(character_name) not in names:
                continue
            result.append(
                {
                    "turn": int(row["turn"] or 0),
                    "year": int(row["year"] or 0),
                    "period": int(row["period"] or 0),
                    "kind": row["kind"] or "assignment",
                    "title": row["title"],
                    "body": row["body"] or "",
                    "source_id": source_id,
                }
            )

        return result


    def _coerce_positive_message_ids(
        self, message_ids: Optional[Iterable[Any]] = None,
    ) -> List[int]:
        """Normalize chat_message id pins to a stable unique positive list.

        声明/调用侧宽松：坏成员跳过。已持久 brief 源身份用
        ``_load_durable_origin_message_ids`` 响亮解码（#1897 E1）。
        """
        out: List[int] = []
        seen: set = set()
        for raw in message_ids or ():
            mid = int(raw)
            if mid > 0 and mid not in seen:
                seen.add(mid)
                out.append(mid)
        return out

    def _load_durable_origin_message_ids(
        self, raw: object, *, surface: str,
    ) -> List[int]:
        """Durable brief/pin message-id array: corrupt / non-int members fail loud."""
        values = _load_durable_json(raw, default='[]')
        if not isinstance(values, list):
            raise TypeError(f"{surface} must be a list of message ids, got {values!r}")
        out: List[int] = []
        seen: set = set()
        for index, item in enumerate(values):
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(
                    f"{surface}[{index}] 须为正整 message id，"
                    f"得 {type(item).__name__}"
                )
            if item <= 0:
                raise ValueError(f"{surface}[{index}] 须为正整 message id")
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def _secret_origin_message_ids(self, character_name: str = "") -> set[int]:
        """Secret oral pins inaccessible to this reader, including paired replies.

        Briefs and pending/failed declarations own the same message provenance.
        Empty reader selects all secret pins for the public author.
        """
        from ming_sim.knowledge import origin_visible_to

        out: set[int] = set()
        brief_rows = self.character_knowledge.secret_brief_pins()
        pending_rows = self.conn.execute(
            'SELECT minister_name, payload_json FROM pending_actions WHERE '
            "kind='secret_order' AND status IN ('pending','failed')",
            (),
        ).fetchall()
        for row in brief_rows:
            # Durable source identities keep their existing fail-loud decoding.
            pins = self._load_durable_origin_message_ids(
                row["origin_chat_message_ids"] if row is not None else None,
                surface="secret_order_briefs.origin_chat_message_ids",
            )
            if not origin_visible_to(self, f"secret_order:{int(row['order_id'])}", character_name):
                out.update(pins)
        for row in pending_rows:
            payload = parse_engine_payload_json(
                row["payload_json"],
            )
            mid = self._parse_origin_chat_message_id(payload)
            if mid is not None and (not character_name or character_name != row["minister_name"]):
                out.add(mid)
        if out:
            turns = self.reign.chat_turns_for_messages(sorted(out))
            for turn in turns:
                for raw in (turn["user_message_id"], turn["minister_message_id"]):
                    if raw is None:
                        continue
                    mid = int(raw)
                    if mid > 0:
                        out.add(mid)
        return out

    def register_character_knowledge_source(
        self, state: GameState, participant_roster: Iterable[Mapping[str, object]],
        kind: str, title: str, body: str = "", source_id: str = "",
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
        if not source_id:
            source_id = f"{kind}:{state.turn}:{title}"
        self.conn.execute(
            'INSERT OR REPLACE INTO character_knowledge_sources '
            '(turn,year,period,kind,title,body,source_id,participant_roster) VALUES '
            '(?,?,?,?,?,?,?,?)',
            (
                state.turn,
                state.year,
                state.period,
                kind,
                title,
                body,
                source_id,
                safe_json_dumps(roster, ensure_ascii=False),
            ),
        )
        if commit:
            self.conn.commit()


    def upsert_secret_order_brief(
        self, state: GameState, order_id: int, minister_name: str, title: str, body: str,
        *,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        commit: bool = True,
    ) -> None:
        """Persist the assignee's brief and exact oral source identities."""
        pins = self._coerce_positive_message_ids(origin_chat_message_ids)
        # Keep earlier oral provenance when a later approval/update names another pin.
        pins = list(dict.fromkeys([*self._brief_origin_chat_message_ids(int(order_id)), *pins]))
        pins_json = safe_json_dumps(pins, ensure_ascii=False)
        self.character_knowledge.upsert_secret_order_brief(
            int(order_id),
            state.turn,
            state.year,
            state.period,
            minister_name,
            title,
            body,
            pins_json,
        )
        if commit:
            self.conn.commit()

    def record_public_knowledge_event(
        self,
        state: GameState,
        title: str,
        body: str = "",
        source_id: str = "",
        kind: str = "public",
        *,
        commit: bool = True,
    ) -> None:
        source_id = source_id or f"public:{state.turn}:{title}"
        self.conn.execute(
            'INSERT OR REPLACE INTO character_knowledge_events '
            '(turn,year,period,character_name,kind,title,body,source_id) VALUES '
            '(?,?,?,?,?,?,?,?)',
            (state.turn, state.year, state.period, '', kind, title, body, source_id),
        )
        if commit:
            self.conn.commit()



    def record_recommendation(
        self, state: GameState, recommender: str, candidate: Dict[str, object],
        target_office: str, reason: str = "",
    ) -> int:
        from ming_sim.recommendations import record_recommendation
        owns = connection_owns_transaction(self.conn)
        event_id = record_recommendation(self, state, recommender, candidate, target_office, reason)
        if owns:
            self.conn.commit()
        return event_id

    def create_secret_order(
        self,
        state: GameState,
        minister_name: str,
        title: str,
        content: str,
        tags: List[str],
        importance: int = 4,
        deadline_months: int = 0,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
        pending_action_id: int = 0,
        covert_task: Optional[Mapping[str, object]] = None,
        affair_declaration: Optional[Mapping[str, object]] = None,
    ) -> int:
        # 宗藩/外藩 非朝堂命官，不可受密令——密令创建的唯一 DB 写口，集中守此一处即覆盖
        # API / 大臣工具 / CLI 自然语言全路（cmr R6 cross-section）。
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
            from ming_sim.exceptions import PendingActionRefusal
            if _ch is not None and is_vassal_prince(_ch):
                raise PendingActionRefusal(
                    f"{_ch.name}为就藩宗室，非朝廷命官，不可受密令。",
                    category="ineligible_vassal",
                    item={"assignee": _ch.name},
                )
            if _ch is not None and self.resolve_power_id(_ch) != "ming":
                raise PendingActionRefusal(
                    f"{_ch.name}不属大明朝廷，不可受密令。",
                    category="ineligible_power",
                    item={"assignee": _ch.name},
                )
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
            _investigation_fact_of,
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
                    fact_key=_investigation_fact_of(covert_contract or {}),
                )
        active_count = self.conn.execute(
            "SELECT COUNT(*) FROM secret_orders WHERE status='active'",
            (),
        ).fetchone()[
            0
        ]
        if active_count >= 20:
            from ming_sim.exceptions import PendingActionRefusal
            raise PendingActionRefusal(
                f"进行中密令已达上限（20条），请先结案部分密令再下新令。当前：{active_count} 条。",
                category="active_cap",
                item={"active_count": int(active_count)},
            )
        tags_json = json.dumps(tags, ensure_ascii=False)
        deadline = max(0, min(int(deadline_months or 0), 36))
        due_turn = int(state.turn) + deadline if deadline else 0
        source_chat_turn_id = 0
        if provenance_message_ids:
            source_row = next(
                iter(self.reign.chat_turns_for_messages(provenance_message_ids)), None
            )
            if source_row is not None:
                source_chat_turn_id = int(source_row["id"])
        with atomic(self):
            cur = self.conn.execute(
                """
                INSERT INTO secret_orders
                    (turn_issued, due_turn, deadline_span, year_issued, period_issued, minister_name, title, content, tags, importance, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    state.turn,
                    due_turn,
                    deadline,
                    state.year,
                    state.period,
                    minister_name,
                    title,
                    content,
                    tags_json,
                    importance,
                ),
            )
            order_id = int(cur.lastrowid)
            # Classification event and dossier identity share the issuance transaction.
            self._classify_secret_order_audience(
                state, order_id, minister_name, title, content,
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
            }
            payload[CONTRACT_KEY] = covert_contract
            if affair_declaration is not None:
                # 事务归属由成案核 _resolve_affair_id_from_payload 消费并落 pointer。
                payload["affair_declaration"] = dict(affair_declaration)
            # #1896：开案 lane 只由下方 seed_investigation_fact_lanes 写一次并冻结
            # 难度；禁在此预写旧 progress/used 形状（缺 difficulty → 读口填 0 →
            # seed 见 seen 跳过，难度永久钉死为 0）。
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
            self.conn.execute(
                """
                UPDATE decree_dossiers
                SET promulgation_decision='promulgated',
                    promulgation_blocked_layer='palace_rescript',
                    promulgation_reason='内批自动顺颁'
                WHERE id=?
                """,
                (int(dossier_id),),
            )
            self.dossiers.insert_decision(
                int(dossier_id),
                int(state.turn),
                decision="promulgated",
                rescript_action="",
                reason="内批自动顺颁",
                blocked_layer="palace_rescript",
            )
            if inv_target:
                # #1896：开案即铺 lane 集并冻结逐证难度——唯一开 lane 的口在
                # covert_progress.seed_investigation_fact_lanes，案卷 payload 不再
                # 另写一份（曾在此手写旧 progress 形状，成了第二个 lane 写口）。
                # 开案这条来源自身也是一条真实线索，与汇案来源同一条接线（R6）。
                from ming_sim.covert_progress import (
                    record_investigation_source_clue,
                    seed_investigation_fact_lanes,
                    _investigation_fact_of,
                )

                seed_investigation_fact_lanes(
                    self, int(dossier_id), inv_target,
                    investigator=str(minister_name),
                )
                record_investigation_source_clue(
                    self, int(dossier_id),
                    fact_key=_investigation_fact_of(covert_contract or {}),
                    turn=int(state.turn),
                )
        tlog(f"[secret_order] create id={order_id} minister={minister_name} title={title}")
        return order_id

    def update_secret_order_by_id(
        self,
        state: GameState,
        order_id: int,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        deadline_months: int = 0,
        *,
        origin_chat_message_id: Optional[int] = None,
        origin_chat_message_ids: Optional[Iterable[int]] = None,
    ) -> bool:
        """按**精确 id** 更新 active 密令要旨（title/content/tags/限期）。
        返回是否更新（id 存在且状态为 active）。不写月度奏报。


        tags=None 保留原标签（会话更新不带 tags 时不清空）；传 list 则覆盖。

        Oral-decree pins (stage ``origin_chat_message_id`` / speaker) feed the same
        provenance seam as create for non-create audience updates.
        When no pin intent is provided, preserve brief pins (do not auto-capture
        pure-public messages as new secret-origin bloodline).
        """
        row = self.character_knowledge.secret_order_row(int(order_id))
        if row is None or row["status"] != "active":
            return False
        persisted_title = title
        for field, value in (("title", persisted_title), ("content", content)):
            if not isinstance(value, str):
                raise TypeError(f"secret_orders#{order_id}.{field} must be text, got {value!r}")
        if tags is not None:
            if not isinstance(tags, list):
                raise ValueError(
                    f"secret_orders#{int(order_id)} tags 须为列表，"
                    f"得 {type(tags).__name__}"
                )
            tags_json = json.dumps(
                tags,
                ensure_ascii=False,
            )
        else:
            # 保留原标签：空串/腐坏响亮，不 or "[]" 洗（#1897 E1）。
            tags_json = json.dumps(
                _load_durable_str_list(row['tags']),
                ensure_ascii=False,
            )
        deadline = max(0, min(int(deadline_months or 0), 36))
        # Preserve create-time oral pins when caller did not name a new pin.
        classify_ids = origin_chat_message_ids
        if origin_chat_message_id is None and classify_ids is None:
            classify_ids = self._brief_origin_chat_message_ids(int(order_id))
        with atomic(self):
            self.character_knowledge.update_secret_order(
                int(order_id), persisted_title, content, tags_json,
                due_turn=int(state.turn) + deadline if deadline else None,
                deadline_span=deadline if deadline else None,
            )
            self._classify_secret_order_audience(
                state, int(order_id), str(row["minister_name"]), persisted_title, content,
                origin_chat_message_id=origin_chat_message_id,
                origin_chat_message_ids=classify_ids,
                commit=False,
            )
            # #1897 S2：现行要旨／期限权威面＝secret_orders；案卷 decree_text／
            # payload.text 保留发令历史原诏，不再平行改写 payload.content 等现行副本。
        tlog(f"[secret_order] update id={order_id} title={title[:20]}")
        return True


    def close_secret_order(
        self,
        order_id: int,
        status: str,
        result: str,
        turn_closed: int,
        *,
        execution_note: Optional[str] = None,
        commit: bool = True,
    ) -> None:
        def close_in_current_transaction() -> None:
            dossier = self.dossiers.get_for_secret_order(int(order_id))
            if dossier is None:
                # #1897 / ADR0005：在办密令缺必需案卷是内部故障，不得半截结案。
                raise ValueError("密令进展缺少对应案卷")
            # 结案正文：禁 str()/or 洗白；空串合法（#1897 J820-E1）。
            close_text = result
            if not isinstance(close_text, str):
                raise TypeError(f"secret_orders#{order_id}.result must be text, got {close_text!r}")
            # execution_note=None＝缺省空串合同；已提供则须为字符串。
            if execution_note is None:
                exec_note_text = ""
            else:
                exec_note_text = execution_note
            self.conn.execute(
                """
                UPDATE secret_orders
                SET status = ?, result = ?, turn_closed = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, close_text, turn_closed, int(order_id)),
            )
            if dossier["status"] != "closed":
                if dossier["status"] == "promulgated":
                    self.dossiers.transition(
                        int(dossier["id"]), "executing", commit=False,
                    )
                # #1897 / ADR0073：执行格只吃实况 note；奏报正文(result)不得回填。
                self.dossiers.record_execution(
                    int(dossier["id"]),
                    "fulfilled" if str(status) == "done" else "failed",
                    exec_note_text,
                    int(turn_closed), close=True, commit=False,
                )

        if self.conn.in_transaction:
            with item_savepoint_scope(self, "close_secret_order_axes"):
                close_in_current_transaction()
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

    def _current_game_turn(self, fallback: int = 0) -> int:
        row = self.reign.row(1, fields="turn", table="game_state")
        return int(row["turn"]) if row is not None else int(fallback)

    def _note_secret_order_report(
        self, order_id: int, text: str, *, band: str, origin: str,
    ) -> bool:
        """把一条奏报原文写入 0058 密令轨。月份身份是当前 game_state.turn。

        正文原样入库。判空只用副本。调用方持有事务。
        """
        # 已持久/调用方正文：禁 str()/or 洗白；空陈词不落条（#1897 J820-E1）。
        raw = text
        if not raw.strip():
            return False
        row = self.character_knowledge.secret_order_row(int(order_id))
        if row is None or row["status"] != "active":
            # 未知／非 active：领域拒收（调用方见 False），不是内部故障。
            return False
        dossier = self.dossiers.get_for_secret_order(int(order_id))
        if dossier is None:
            # #1897 / ADR0005：已准入 active 密令缺案卷 → 响亮故障；不得洗成 False 终结暂存。
            raise ValueError("密令进展缺少对应案卷")
        self.dossiers.record_dossier_progress(
            int(dossier["id"]), self._current_game_turn(), band, raw,
            origin=origin, commit=False,
        )
        return True

    def submit_secret_order_for_review(self, order_id: int, claim: str) -> bool:
        """#1504：大臣自认办结 → 缩 due_turn 至当月，月末按实况对账。

        claim 是自由文本，原样进入奏报轨的核议 origin，不改实况、不改御限以外的世界。
        空陈词只缩短到期回合。
        坏类型 schema 故障，不洗成空陈词（#1897 J820-E1）。
        """
        row = self.character_knowledge.secret_order_row(int(order_id))
        if not row or row["status"] != "active":
            return False
        current_turn = self._current_game_turn(int(row["turn_issued"] or 0))
        claim_text = claim
        with atomic(self):
            self.conn.execute(
                'UPDATE secret_orders SET due_turn = ?, updated_at = '
                "CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
                (current_turn, int(order_id)),
            )
            if claim_text.strip():
                self._note_secret_order_report(
                    int(order_id), claim_text, band="核议",
                    origin=self.DOSSIER_REPORT_ORIGIN_REVIEW,
                )
            self.dossiers.mark_secret_order_in_progress(int(order_id), commit=False)
        tlog(f"[secret_order] submit_for_review id={order_id} due_now claim={claim_text[:60]!r}")
        return True

    def update_secret_order_progress(
        self,
        order_id: int,
        progress_note: str,
        *,
        commit: bool = True,
    ) -> bool:
        """承办人推进一步：写入当月奏报轨，不改 status、不改实况。

        同月再报替换同一条月度奏报。正文里的日期不另立月份。
        坏类型 schema 故障，不洗成空串领域拒收（#1897 J820-E1）。
        """
        note = progress_note
        if commit:
            with atomic(self):
                ok = self._note_secret_order_report(
                    order_id, note, band="进展",
                    origin=self.DOSSIER_REPORT_ORIGIN_MONTHLY,
                )
                if ok:
                    self.dossiers.mark_secret_order_in_progress(order_id, commit=False)
        else:
            ok = self._note_secret_order_report(
                order_id, note, band="进展",
                origin=self.DOSSIER_REPORT_ORIGIN_MONTHLY,
            )
            if ok:
                self.dossiers.mark_secret_order_in_progress(order_id, commit=False)
        tlog(f"[secret_order] progress id={order_id} ok={ok} note={progress_note!r}")
        return ok

    def update_secret_order_sim_note(
        self,
        order_id: int,
        sim_note: str,
        *,
        commit: bool = True,
    ) -> None:
        """推演写本月推进实况。原文进入实况轨当月 note，不覆盖单位。

        月份身份是当前 game_state.turn。正文日期不另立月份。
        不进奏报轨。
        """
        if commit:
            with atomic(self):
                self._update_secret_order_sim_note_in_transaction(order_id, sim_note)
        else:
            self._update_secret_order_sim_note_in_transaction(order_id, sim_note)
        tlog(f"[secret_order] actual note id={order_id} note={str(sim_note)[:40]!r}")

    def _update_secret_order_sim_note_in_transaction(
        self, order_id: int, sim_note: str,
    ) -> None:
        """调用方持有事务时把实况原文写入当月实况轨，并同步案卷在办。

        只写 note，不改 units。显式传入的正文（含空白）原样写入，不以
        strip/TRIM 仲裁旧／新（P6 / #1897 N2）。数值写口见
        DossierStore.record_actual_progress；本口只替换正文，保留数值实况。
        坏类型 schema 故障，禁 str()/or 洗白（#1897 J820-E1）。
        """
        raw = sim_note
        if not isinstance(raw, str):
            raise TypeError(f"secret_orders#{order_id}.sim_note must be text, got {raw!r}")
        row = self.character_knowledge.secret_order_row(int(order_id), active_only=True)
        if row is None:
            return
        dossier = self.dossiers.get_for_secret_order(int(order_id))
        if dossier is None:
            raise ValueError("密令进展缺少对应案卷")
        did = int(dossier["id"])
        turn = self._current_game_turn()
        self.dossiers.set_actual_progress_note(did, turn, raw)
        self.dossiers.mark_secret_order_in_progress(order_id, commit=False)


    def rush_secret_order(
        self,
        order_id: int,
        state: GameState,
        deadline_months: int = 1,
        reason: str = "",
    ) -> Dict[str, object]:
        """缩短 active 密令期限。deadline_months<=0 表示本月到期对账。"""
        row = self.character_knowledge.secret_order_row(int(order_id))
        if row is None:
            raise PendingActionRefusal(
                "密令不存在",
                category="missing_order",
                item={"order_id": int(order_id)},
            )
        if row["status"] != "active":
            raise PendingActionRefusal(
                f"当前状态 {row['status']}，不能催办",
                category="not_active",
                item={"order_id": int(order_id), "status": row["status"]},
            )
        months = max(0, min(int(deadline_months or 0), 36))
        target_turn = int(state.turn) + months
        old_due = int(row["due_turn"] or 0)
        # #1897 J820-E1：催办理由已是/须是字符串；坏类型响亮；仅真正空串回落缺省。
        raw_reason = reason
        if not isinstance(raw_reason, str):
            raise TypeError(f"secret_orders#{order_id}.rush.reason must be text, got {raw_reason!r}")
        why = raw_reason if raw_reason else "奉旨加急"
        with atomic(self):
            if months <= 0:
                self.character_knowledge.set_secret_order_deadline(
                    int(state.turn), 0, int(order_id)
                )
                status = "active"
                due_turn = int(state.turn)
            else:
                due_turn = target_turn if old_due <= 0 else min(old_due, target_turn)
                self.character_knowledge.set_secret_order_deadline(
                    due_turn, max(due_turn - int(state.turn), 0), int(order_id)
                )
                status = "active"
            self._note_secret_order_report(
                int(order_id), why, band="催办",
                origin=self.DOSSIER_REPORT_ORIGIN_RUSH,
            )
            self.dossiers.mark_secret_order_in_progress(int(order_id), commit=False)
        tlog(f"[secret_order] rush id={order_id} old_due={old_due} due={due_turn} status={status}")
        return {"id": int(order_id), "title": row["title"], "status": status, "due_turn": due_turn}


    def auto_submit_due_secret_orders(self, state: GameState) -> List[Dict[str, object]]:
        """#1504：到期只记 typed 机器事实，保持 active；玩家文字走 0058 密奏。"""

        rows = self.conn.execute(
            """
            SELECT id, title, result FROM secret_orders
            WHERE status = 'active' AND due_turn > 0 AND due_turn <= ?
            ORDER BY id
            """,
            (int(state.turn),),
        ).fetchall()
        submitted: List[Dict[str, object]] = []
        with atomic(self):
            for row in rows:
                oid = int(row["id"])
                self.dossiers.mark_secret_order_in_progress(oid, commit=False)
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
            raise DeclarationDataError("边事件语境必须为字符串")
        if not source or not target:
            raise DeclarationDataError("边事件 source/target 不能为空")
        if not context.strip():
            raise DeclarationDataError("边事件语境不能为空")
        kind = validate_edge_kind(event_kind)
        evidence_flag = normalize_evidence(evidence)
        owns_transaction = connection_owns_transaction(self.conn)
        state_row = self.reign.row(1, fields="turn, year, period", table="game_state")
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
        edge_id = self.person_logs.record_relation_edge_event(
            source,
            target,
            kind,
            context,
            bound_origin,
            origin_round,
            effective_turn,
            effective_year,
            effective_period,
            int(evidence_flag),
        )
        if owns_transaction:
            self.conn.commit()
        return edge_id


    # ------------------------------------------------------------------
    # #637 派系态势摘要 S6：持久化接缝（ADR 0084）。
    # 复用 #636 单一 durable claim/watermark/apply+clear 所有者（庭裁 r1 F2）：
    # pending 走同一 relation_brew_pending 表（item_kind='派系' 身份），apply 与
    # pending 清除同事务原子落定，与 apply_relation_brew_result 同构。
    # ------------------------------------------------------------------


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
        owns = connection_owns_transaction(self.conn)
        try:
            self.conn.execute("""
                INSERT INTO faction_stance_summaries
                    (faction, stance_segment, last_event_id,
                     last_brewed_turn, last_brewed_year, last_brewed_period)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(faction) DO UPDATE SET
                    stance_segment = excluded.stance_segment,
                    last_event_id = excluded.last_event_id,
                    last_brewed_turn = excluded.last_brewed_turn,
                    last_brewed_year = excluded.last_brewed_year,
                    last_brewed_period = excluded.last_brewed_period,
                    updated_at = CURRENT_TIMESTAMP
            """, (str(faction), str(stance_segment), int(last_event_id), int(turn), int(year), int(period)))
            self.conn.execute(
                "DELETE FROM relation_brew_pending WHERE item_kind = '派系' AND target = ?",
                (str(faction),),
            )
            if owns:
                self.conn.commit()
        except Exception:
            # 故障注入验收缝（与 apply_relation_brew_result 同构）：摘要已写、
            # 事务未提交即崩→整体回滚，pending 仍在、摘要读回＝崩前旧值。
            if owns:
                self.conn.rollback()
            raise

    def backup_to(self, target_path: str) -> None:
        """SQLite backup API 热备到 target_path。不需关闭主连接。

        外层事务（atomic / BEGIN）内禁止调用：backup 走同连接 pager，会把未提交
        （可能随后回滚）的脏页备进文件（cmr S1 F3）。错误包备份必须在 rollback
        之后、atomic 外做。调用前须无未提交写入（本调用方已拥有提交权）。
        """
        if not connection_owns_transaction(self.conn):
            raise RuntimeError(
                "backup_to 在外层事务内禁止：备份会带上未提交脏页。"
                "请先 rollback/commit（退出 atomic/外层事务）再备份。"
            )
        import os as _os
        _os.makedirs(_os.path.dirname(target_path) or ".", exist_ok=True)
        dest = sqlite3.connect(target_path)
        try:
            self.conn.commit()
            self.conn.backup(dest)
        finally:
            dest.close()

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
        owns = connection_owns_transaction(self.conn)
        count = self.dossiers.mark_pending_night_approved(action_ids, night_id=night_id)
        if owns:
            self.conn.commit()
        return count

    def _snapshot_table(self, table: str) -> Dict[str, Dict[str, Any]]:
        if (
            table == "rejection_reports"
            and self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rejection_reports'",
            ).fetchone()
            is None
        ):
            return {}
        if table not in self._rollback_stores:
            raise ValueError(f"不支持回滚表：{table}")
        store = self._rollback_stores[table]
        pk = store.TABLES[table]
        rows = store.snapshot_rows(table)
        snapshot = {str(row[pk]): self._row_dict(row) for row in rows}
        if table == "secret_orders":
            brief_pins = {
                str(row["order_id"]): str(row["origin_chat_message_ids"] or "[]")
                for row in self.character_knowledge.secret_brief_pins()
            }
            for order_id, row in snapshot.items():
                row["_rollback_brief_origin_chat_message_ids"] = brief_pins.get(order_id, "[]")
        return snapshot

    def _restore_row_in_tx(self, table: str, row: Dict[str, Any]) -> None:
        if not row:
            return
        row = {key: value for key, value in row.items() if not key.startswith("_rollback_")}
        if table not in self._rollback_stores:
            raise ValueError(f"不支持回滚表：{table}")
        self._rollback_stores[table].restore_snapshot(table, row)

    def _delete_row_in_tx(self, table: str, target_id: str) -> None:
        if table not in self._rollback_stores:
            raise ValueError(f"不支持回滚表：{table}")
        self._rollback_stores[table].delete(target_id, table=table)
