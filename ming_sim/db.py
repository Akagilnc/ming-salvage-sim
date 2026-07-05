"""GameDB：所有 SQLite 持久化。L3。

init_schema 建表，seed_static_data 从 GameContent 初始化静态盘面。
GameDB 持有 self.content（GameContent），seed 类方法从中读人物/地区/军队等。
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import json
import math
import re
import sqlite3
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from ming_sim.applier import atomic, safe_json_dumps, sanitize_sqlite_text
from ming_sim.assets import format_money, format_money_delta
from ming_sim.constants import (
    ARMY_FIELD_ALIASES, ARMY_FIELD_LABELS, ARMY_QUANTITY_FIELDS, ARMY_SCORE_FIELDS, ARMY_TEXT_FIELDS,
    BUILDING_CATEGORIES, BUILDING_FIELD_LABELS, BUILDING_OUTPUT_METRICS,
    BUILDING_QUANTITY_FIELDS, BUILDING_SCORE_FIELDS, BUILDING_TEXT_FIELDS,
    ECONOMY_ACCOUNTS, POWER_FIELD_LABELS, POWER_SCORE_FIELDS,
    POWER_FIELD_ALIASES, POWER_TEXT_FIELDS, MONEY_UNIT, REGION_FIELD_LABELS, REGION_QUANTITY_FIELDS,
    FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES, REGION_SCORE_FIELDS, REGION_TEXT_FIELDS,
    SALARY_RATE_ANCHOR, TURN_UNIT,
)
from ming_sim.content import GameContent
from ming_sim.matching import match_army_id_from_text, match_region_id_from_text
from ming_sim.models import (
    FRONT_HALF_DONE_PHASES, Character, Event, GameState, is_vassal_prince,
    loads_effect_dict, monthly_amount, period_label,
)
from ming_sim.token_stats import tlog

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
_COMMITMENT_STOP_CONDITION_RE = re.compile(r"character\.[^.]+\.loyalty\s*(?:>=|>)\s*\d+")


class ProvinceFiscalTickOutcome(NamedTuple):
    region_id: str
    result: Any
    error: Optional[BaseException]


_ARMY_PAY_SOURCE_CUTOVER_KEY = "__army_pay_source_cutover"
_FISCAL_ENGINE_KEY = "__fiscal_engine"
_FISCAL_ENGINE_LEGACY = 0
_FISCAL_ENGINE_SUBSTRATE_HUB = 1
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
    "loyalty": ("危殆", "浮动", "不稳", "尚稳", "稳固"),
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


def _is_commitment_stop_condition(resolve_condition: object) -> bool:
    return bool(_COMMITMENT_STOP_CONDITION_RE.fullmatch(str(resolve_condition or "").strip()))


def _has_stop_condition(stop_condition: object) -> bool:
    if isinstance(stop_condition, (dict, list)):
        return bool(stop_condition)
    raw = str(stop_condition or "").strip()
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, (dict, list)) and bool(parsed)


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
    "锦衣卫": 8, "东厂": 8, "都察院": 8,                       # 厂卫 / 监察
    "礼部": 5, "刑部": 5, "工部": 5,                           # 中层部务（六部齐全：刑部勿漏）
    "内臣": 4, "内廷": 4,                                       # 宫廷宦官（御马监/内官监等，与内臣同档）
    "翰林院": 2, "地方": 2, "外臣": 1,                         # 长尾
    # 后宫 / 宗藩 / 未仕 → 0（不在朝堂博弈或无实权）；office_type 不在表里 → 权重 0。
}

# 品级档 multiplier：从 office 头衔字串解析（同一 office_type 内 尚书 vs 职方 权力天差地别）。
# 关键词按档分组；一个头衔逐档命中（堂官档优先于佐贰、佐贰优先于属官）。未识别 → 默认 1.0（保守，
# 避免漏算堂官）。词序在档内不影响（只判是否含子串）。
_OFFICE_RANK_TIERS = (
    (1.0, (  # 堂官 / 主官
        "尚书", "掌印", "秉笔", "提督", "首辅", "督师", "总督", "巡抚",
        "总兵", "都督", "都指挥使", "都御史",
    )),
    (0.5, (  # 佐贰
        "侍郎", "次辅", "大学士", "副总兵", "参政", "佥都御史", "少卿",
        # #9 线上 R3（codex P2）审计补全：offices.json 里「含某 1.0 档关键词作子串」的佐贰官名，
        # 经 min-within-part 会与 1.0 子串共同命中、取 min 落 0.5（与 副总兵⊃总兵 同治）。逐个：
        #   副都御史 ⊃ 都御史（本 finding 核心：都察院佐贰，左/右副都御史，非堂官）；
        #   同知 ⊃（都督同知⊃都督、府同知、卫指挥同知）——通治 generic 佐贰词干「同知」；
        #   佥事 ⊃（都督佥事⊃都督、按察佥事）——通治 generic 佐贰词干「佥事」（佥都御史已在上）。
        # 不加 左/右都御史（都察院堂官、是主官非副）、提督/总督 类（主官）——它们正职档 1.0 不动。
        "副都御史", "同知", "佥事",
    )),
    (0.25, (  # 属官 / 微员
        "郎中", "主事", "职方", "司属", "编修", "检讨", "游击", "守备",
        "候补", "候用", "随堂", "信邸内官",
    )),
)
_DEFAULT_OFFICE_RANK_MULTIPLIER = 1.0  # 未识别头衔的保守默认（避免漏算堂官）

# 退场类状态(削职)——与 active 互斥（set_character_status 据此清空 office）。
_OUSTED_STATES = {"offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}


def _office_rank_multiplier(office: str, already_normalized: bool = False) -> float:
    """从 office 头衔字串解析品级 multiplier。逗号分隔的多职取**已识别分项中的最高档**。
    只在整串无任何识别词时才落默认 1.0（保守，避免漏算堂官）——故描述性尾缀（如「兵部职方,
    火器西法」的「火器西法」）不会把默认 1.0 拉进 max 污染掉真实品级。
    #9 R1 finding#5：already_normalized=True 时入参已是 normalize_office 结果，跳过重复 normalize
    （热路 _member_office_weight 已归一过，避免二次 normalize 冗余）。

    #9 线上 R2 finding（品级子串误匹配）：**单个分项取「所有命中档里最低的 multiplier」**——
    因为副职关键词更长（副总兵⊃总兵、佥都御史⊃都御史），与正职子串会共同命中，取 min 自然落到
    副职档（0.5）；纯正职（如单独「总兵」「都御史」）只命中 1.0 档 → 仍 1.0。这样通治所有
    「子串包含」overlap（不止副总兵/佥都御史两例）。跨分项仍取 max（身兼数职取最高官）。"""
    text = office or ""
    if not text.strip():
        return _DEFAULT_OFFICE_RANK_MULTIPLIER
    normalized = text if already_normalized else normalize_office(text)
    best: Optional[float] = None
    for part in (p.strip() for p in normalized.split(",")):
        if not part:
            continue
        # 该分项命中的所有档取最低 multiplier（副职关键词更长、与正职子串共同命中时取 min 落副职）。
        part_mult: Optional[float] = None
        for mult, keywords in _OFFICE_RANK_TIERS:
            if any(kw in part for kw in keywords):
                if part_mult is None or mult < part_mult:
                    part_mult = mult
        if part_mult is None:
            continue  # 该分项无任何识别词 → 不贡献（沿用整体兜底语义）
        if best is None or part_mult > best:
            best = part_mult  # 跨分项取最高官
    # 整串无任一识别词 → 保守默认（避免把生造/罕见堂官头衔误判成低档）
    return best if best is not None else _DEFAULT_OFFICE_RANK_MULTIPLIER


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
    if not text:
        return "待铨" if kind in COURT_OFFICE_TYPES or not kind else kind
    t = _office_type_from_table(text)
    if t:
        return t
    if not use_llm:
        # 静态 seed / DB sync：content/DB 既定 office_type 即权威，表查不中原样保留(含朝堂类)，
        # 不降级——否则每回合 sync 把动态任命落库的朝堂类 office_type 悄悄降级成待铨(cmr R2)。
        return kind or "待铨"
    t = _office_type_via_llm(text, llm_config)
    if t:
        return t
    return "待铨" if kind in COURT_OFFICE_TYPES or not kind else kind


class GameDB:
    def __init__(self, path: str, content: Optional[GameContent] = None, llm_config: Any = None):
        self.path = path
        # 静态设定来源。过渡期 content 可省略，省略时自行加载；
        # 步骤7 起由 GameSession 统一传入同一份 GameContent。
        self.content = content if content is not None else GameContent.load()
        self.llm_config = llm_config
        # check_same_thread=False：流式颁诏在 worker 线程跑 resolve_turn，
        # 复用同一 GameDB 连接。游戏单写者、无并发写，跨线程安全。
        # factory=_SuspendableConnection：使 atomic() 能暂停全库 commit（ADR 0008 决定 2/8）。
        # 暂停标志默认 off，下面 init_schema 建表照常提交。
        from ming_sim.applier import _SuspendableConnection
        self.conn = sqlite3.connect(path, check_same_thread=False, factory=_SuspendableConnection)
        self.conn.row_factory = sqlite3.Row
        # 遗产修正符缓存：legacy_modifiers 在落账热路径被频繁调用，缓存聚合结果，
        # 仅在 active 遗产集变化（insert_legacy / expire_legacies）时失效。
        self._legacy_mod_cache: Optional[Dict[str, object]] = None
        self.init_schema()

    def owns_transaction(self) -> bool:
        """Return True when this GameDB call site should commit its own writes."""
        return not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
            or self.conn.in_transaction
        )

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                turn_phase TEXT NOT NULL DEFAULT 'summoning'
            );

            CREATE TABLE IF NOT EXISTS metrics (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS offices (
                office_type TEXT PRIMARY KEY,
                skills TEXT NOT NULL,
                tools TEXT NOT NULL,
                authority_scope TEXT NOT NULL,
                power INTEGER NOT NULL,
                responsibility INTEGER NOT NULL,
                corruption_risk INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS characters (
                name TEXT PRIMARY KEY,
                office TEXT NOT NULL,
                office_type TEXT NOT NULL,
                faction TEXT NOT NULL,
                personal_skills TEXT NOT NULL,
                loyalty INTEGER NOT NULL,
                ability INTEGER NOT NULL,
                integrity INTEGER NOT NULL,
                courage INTEGER NOT NULL,
                style TEXT NOT NULL,
                birth_year INTEGER NOT NULL DEFAULT 0,
                historical_death_year INTEGER NOT NULL DEFAULT 0,
                historical_death_month INTEGER NOT NULL DEFAULT 0,
                debut_year INTEGER NOT NULL DEFAULT 0,
                debut_month INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                status_reason TEXT NOT NULL DEFAULT '',
                reason_code TEXT NOT NULL DEFAULT '',
                status_changed_turn INTEGER NOT NULL DEFAULT 0,
                power_id TEXT NOT NULL DEFAULT 'ming',
                location TEXT NOT NULL DEFAULT '',
                transit_to TEXT NOT NULL DEFAULT '',
                transit_start_turn INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS character_offices (
                character_name TEXT PRIMARY KEY,
                office_title TEXT NOT NULL,
                office_type TEXT NOT NULL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(character_name) REFERENCES characters(name),
                FOREIGN KEY(office_type) REFERENCES offices(office_type)
            );

            CREATE TABLE IF NOT EXISTS person_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_summary TEXT NOT NULL DEFAULT '',
                derived_from TEXT NOT NULL DEFAULT '',
                normalized TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(person_name) REFERENCES characters(name)
            );

            CREATE TABLE IF NOT EXISTS factions (
                name TEXT PRIMARY KEY,
                satisfaction INTEGER NOT NULL,
                leverage INTEGER NOT NULL,
                agenda TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS powers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                leader TEXT NOT NULL,
                stance TEXT NOT NULL,
                leverage INTEGER NOT NULL,
                satisfaction INTEGER NOT NULL,
                military_strength INTEGER NOT NULL,
                cohesion INTEGER NOT NULL,
                supply INTEGER NOT NULL,
                agenda TEXT NOT NULL,
                status TEXT NOT NULL,
                last_action TEXT NOT NULL DEFAULT '',
                aliases TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS power_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                power_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                delta INTEGER,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(power_id) REFERENCES powers(id)
            );

            CREATE TABLE IF NOT EXISTS power_name_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                power_id TEXT NOT NULL,
                old_name TEXT NOT NULL,
                new_name TEXT NOT NULL,
                old_aliases TEXT NOT NULL DEFAULT '',
                new_aliases TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(power_id) REFERENCES powers(id)
            );

            CREATE TABLE IF NOT EXISTS regions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                population INTEGER NOT NULL,
                public_support INTEGER NOT NULL,
                unrest INTEGER NOT NULL,
                natural_disaster TEXT NOT NULL,
                human_disaster TEXT NOT NULL,
                registered_land INTEGER NOT NULL,
                hidden_land INTEGER NOT NULL,
                tax_per_turn INTEGER NOT NULL,
                grain_security INTEGER NOT NULL,
                gentry_resistance INTEGER NOT NULL,
                military_pressure INTEGER NOT NULL,
                status TEXT NOT NULL,
                controlled_by TEXT NOT NULL DEFAULT 'ming',
                city_level INTEGER NOT NULL DEFAULT 0,
                cannon INTEGER NOT NULL DEFAULT 0,
                fiscal TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(controlled_by) REFERENCES powers(id)
            );

            CREATE TABLE IF NOT EXISTS region_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                region_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                delta INTEGER,
                reason TEXT NOT NULL,
                event_id TEXT,
                edict_id INTEGER,
                actor TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(region_id) REFERENCES regions(id)
            );

            CREATE TABLE IF NOT EXISTS armies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                station TEXT NOT NULL,
                theater TEXT NOT NULL,
                commander TEXT NOT NULL,
                controller TEXT NOT NULL,
                troop_type TEXT NOT NULL,
                manpower INTEGER NOT NULL,
                supply INTEGER NOT NULL,
                morale INTEGER NOT NULL,
                training INTEGER NOT NULL,
                equipment INTEGER NOT NULL,
                arrears INTEGER NOT NULL,
                province_pay_arrears REAL NOT NULL DEFAULT 0,
                central_pay_arrears REAL NOT NULL DEFAULT 0,
                pay_source_region TEXT NOT NULL DEFAULT '',
                province_pay_share REAL NOT NULL DEFAULT 0,
                central_pay_share REAL NOT NULL DEFAULT 0,
                is_tusi INTEGER NOT NULL DEFAULT 0,
                self_funded_pay INTEGER NOT NULL DEFAULT 0,
                mutiny_status TEXT NOT NULL DEFAULT '',
                mobility INTEGER NOT NULL,
                loyalty INTEGER NOT NULL,
                firearm_equipment INTEGER NOT NULL DEFAULT 0,
                cannon_equipment INTEGER NOT NULL DEFAULT 0,
                salary_rate REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                owner_power TEXT NOT NULL DEFAULT 'ming',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(owner_power) REFERENCES powers(id)
            );

            CREATE TABLE IF NOT EXISTS army_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                army_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                delta INTEGER,
                reason TEXT NOT NULL,
                event_id TEXT,
                edict_id INTEGER,
                actor TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(army_id) REFERENCES armies(id)
            );

            CREATE TABLE IF NOT EXISTS buildings (
                id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                level INTEGER NOT NULL,
                condition INTEGER NOT NULL,
                maintenance INTEGER NOT NULL,
                risk INTEGER NOT NULL,
                output_metric TEXT NOT NULL DEFAULT '',
                output_amount INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'preset',
                created_turn INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(region_id) REFERENCES regions(id)
            );

            CREATE TABLE IF NOT EXISTS building_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                building_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                delta INTEGER,
                reason TEXT NOT NULL,
                event_id TEXT,
                edict_id INTEGER,
                actor TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(building_id) REFERENCES buildings(id)
            );

            CREATE TABLE IF NOT EXISTS economy_accounts (
                account TEXT PRIMARY KEY,
                metric_key TEXT NOT NULL UNIQUE,
                balance INTEGER NOT NULL,
                note TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS economy_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                account TEXT NOT NULL,
                delta INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                category TEXT NOT NULL,
                reason TEXT NOT NULL,
                event_id TEXT,
                edict_id INTEGER,
                actor TEXT,
                purpose TEXT,
                target_kind TEXT,
                target_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(account) REFERENCES economy_accounts(account)
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                urgency INTEGER NOT NULL,
                severity INTEGER NOT NULL,
                credibility INTEGER NOT NULL,
                interests TEXT NOT NULL,
                audiences TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_triggers (
                event_id TEXT PRIMARY KEY,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'simulation',
                terminal_state TEXT NOT NULL DEFAULT 'triggered',
                terminal_reason TEXT NOT NULL DEFAULT '',
                choice_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS turn_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS turn_reports (
                turn INTEGER PRIMARY KEY,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                report TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- 推演链每回合一行：extractor_input 留原输入，extractor_output 留 applied 可见结果。
            CREATE TABLE IF NOT EXISTS turn_extractions (
                turn INTEGER PRIMARY KEY,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                decree_text TEXT NOT NULL DEFAULT '',
                narrative TEXT NOT NULL DEFAULT '',
                extractor_input TEXT NOT NULL DEFAULT '',
                extractor_output TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- HITL 重大决策点：simulator 邸报里产出的待皇帝亲裁抉择。每回合 ≤5 条。
            -- phase1 存入待选，phase2 读回皇帝选择拼进 narrative 喂 extractor。
            CREATE TABLE IF NOT EXISTS pending_decisions (
                turn INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                event_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                context TEXT NOT NULL DEFAULT '',
                options_json TEXT NOT NULL DEFAULT '[]',
                choice_json TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (turn, idx)
            );

            -- phase1→phase2 之间暂存推演上下文，避免决策暂停后重算 simulator。
            -- 每回合至多一行（turn 主键），phase2 跑完即删。
            CREATE TABLE IF NOT EXISTS pending_resolve_context (
                turn INTEGER PRIMARY KEY,
                decree_text TEXT NOT NULL DEFAULT '',
                narrative TEXT NOT NULL DEFAULT '',
                simulator_payload_json TEXT NOT NULL DEFAULT '{}',
                secret_orders_json TEXT NOT NULL DEFAULT '[]',
                relevant_memories_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- 动作闸门(ADR 0006)：结构化聊天写动作(密令/任命/后宫)召对期进此暂存表，
            -- 不动真实表；颁诏时 commit_pending_actions 在结算最前批量落库(不拒绝即允许)。
            -- 撤回 = 删本表对应行(任意一条、免快照)。restore 仍可无损接续(P1)。
            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                kind TEXT NOT NULL,                       -- secret_order | office | consort
                action TEXT NOT NULL,                     -- 更新 | 催办 | 提交核议 | 记进展 | 创建 …
                target_id INTEGER,                        -- 操作既有实体时其 id；新建为 NULL
                minister_name TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',    -- pending | committed | failed
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- 召对聊天记录持久化，每条消息一行，进程重启不丢。
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minister_name TEXT NOT NULL,
                turn INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_minister
                ON chat_messages(minister_name, id);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_turn
                ON chat_messages(turn);

            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minister_name TEXT NOT NULL,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                user_message_id INTEGER,
                minister_message_id INTEGER,
                agno_session_id TEXT NOT NULL DEFAULT '',
                agno_runs_before INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                undone_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chat_turns_minister_turn
                ON chat_turns(minister_name, turn, status, id);
            CREATE INDEX IF NOT EXISTS idx_chat_turns_status_id
                ON chat_turns(status, id);

            CREATE TABLE IF NOT EXISTS chat_turn_rollback_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_turn_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                target_table TEXT NOT NULL,
                target_id TEXT NOT NULL,
                before_json TEXT NOT NULL DEFAULT '',
                after_json TEXT NOT NULL DEFAULT '',
                rollback_strategy TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(chat_turn_id) REFERENCES chat_turns(id)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_turn_rollback_items_turn
                ON chat_turn_rollback_items(chat_turn_id, id);

            CREATE TABLE IF NOT EXISTS secret_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_issued INTEGER NOT NULL,
                due_turn INTEGER NOT NULL DEFAULT 0,
                year_issued INTEGER NOT NULL,
                period_issued INTEGER NOT NULL,
                minister_name TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                importance INTEGER NOT NULL DEFAULT 4,
                status TEXT NOT NULL DEFAULT 'active',
                result TEXT NOT NULL DEFAULT '',
                sim_note TEXT NOT NULL DEFAULT '',
                turn_closed INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_secret_orders_minister
                ON secret_orders(minister_name, status);
            CREATE INDEX IF NOT EXISTS idx_secret_orders_turn
                ON secret_orders(turn_issued, status);
            CREATE INDEX IF NOT EXISTS idx_secret_orders_status
                ON secret_orders(status);

            CREATE TABLE IF NOT EXISTS skill_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_name TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                granted_by TEXT NOT NULL,
                source_turn INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(character_name) REFERENCES characters(name)
            );

            CREATE TABLE IF NOT EXISTS turn_directives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                event_id TEXT,
                actor TEXT,
                skill_id TEXT,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES events(id),
                FOREIGN KEY(actor) REFERENCES characters(name)
            );

            CREATE INDEX IF NOT EXISTS idx_economy_ledger_turn
            ON economy_ledger(turn, account);

            CREATE TABLE IF NOT EXISTS fiscal_config (
                key   TEXT PRIMARY KEY,
                value INTEGER NOT NULL,
                kind  TEXT NOT NULL,
                note  TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS fiscal_containers (
                key   TEXT PRIMARY KEY,
                value REAL NOT NULL,
                note  TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_turn_directives_turn
            ON turn_directives(turn, status);

            CREATE INDEX IF NOT EXISTS idx_region_logs_turn
            ON region_logs(turn, region_id);

            CREATE INDEX IF NOT EXISTS idx_army_logs_turn
            ON army_logs(turn, army_id);

            CREATE INDEX IF NOT EXISTS idx_building_logs_turn
            ON building_logs(turn, building_id);

            CREATE INDEX IF NOT EXISTS idx_power_logs_turn
            ON power_logs(turn, power_id);

            CREATE INDEX IF NOT EXISTS idx_person_logs_turn
            ON person_logs(turn, person_name);

            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                origin_kind TEXT NOT NULL DEFAULT '',
                origin_ref TEXT NOT NULL DEFAULT '',
                origin_turn INTEGER NOT NULL,
                bar_value INTEGER NOT NULL DEFAULT 40,
                bar_good_meaning TEXT NOT NULL DEFAULT '已平',
                bar_bad_meaning TEXT NOT NULL DEFAULT '失控',
                inertia INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL DEFAULT '起',
                stage_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                severity INTEGER NOT NULL DEFAULT 50,
                region_hint TEXT NOT NULL DEFAULT '',
                faction_hint TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                ongoing_effects TEXT NOT NULL DEFAULT '{}',
                cancellable TEXT NOT NULL DEFAULT 'never',
                cancel_cost TEXT NOT NULL DEFAULT '{}',
                effect_on_resolve TEXT NOT NULL DEFAULT '{}',
                effect_on_fail TEXT NOT NULL DEFAULT '{}',
                resolve_condition TEXT NOT NULL DEFAULT '',
                fail_condition TEXT NOT NULL DEFAULT '',
                end_turn INTEGER NOT NULL DEFAULT 0,
                stop_condition TEXT NOT NULL DEFAULT '',
                commitment_kind TEXT NOT NULL DEFAULT '',
                resolution_summary TEXT NOT NULL DEFAULT '',
                last_advance_turn INTEGER NOT NULL DEFAULT 0,
                closed_turn INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS issue_advances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                trigger_kind TEXT NOT NULL,
                trigger_ref TEXT NOT NULL DEFAULT '',
                delta_bar INTEGER NOT NULL DEFAULT 0,
                from_value INTEGER NOT NULL DEFAULT 0,
                to_value INTEGER NOT NULL DEFAULT 0,
                from_stage_text TEXT NOT NULL DEFAULT '',
                to_stage_text TEXT NOT NULL DEFAULT '',
                narrative TEXT NOT NULL DEFAULT '',
                metric_delta TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(issue_id) REFERENCES issues(id)
            );

            CREATE TABLE IF NOT EXISTS legacies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_issue_id INTEGER,                    -- 产生它的 issue（可空）
                modifiers TEXT NOT NULL DEFAULT '{}',  -- 各维度带符号百分比修正符 {"国库":10,"regions":{...},"armies":{...}}
                narrative_hint TEXT NOT NULL DEFAULT '',    -- 一句话说明（仅展示用，不喂 simulator）
                start_month INTEGER NOT NULL,               -- 绝对月 = year*12+period
                duration_months INTEGER NOT NULL DEFAULT 24,-- 时长；-1=永久
                status TEXT NOT NULL DEFAULT 'active',      -- active / expired / cleared
                clear_gate TEXT NOT NULL DEFAULT '{}',      -- 机器消除条件（同 _gate_passed 语法）；非空=靠程序判定消除而非时长
                legacy_key TEXT NOT NULL DEFAULT '',        -- 开局负面修正对应 opening_legacies.key，去重用
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_legacies_active
            ON legacies(status);

            CREATE INDEX IF NOT EXISTS idx_issues_active
            ON issues(kind, status, severity DESC);

            CREATE INDEX IF NOT EXISTS idx_issue_advances_issue
            ON issue_advances(issue_id, turn);

            CREATE TABLE IF NOT EXISTS classes (
                name TEXT NOT NULL,
                region_id TEXT NOT NULL DEFAULT '',
                population INTEGER NOT NULL,
                satisfaction INTEGER NOT NULL,
                leverage INTEGER NOT NULL,
                agenda TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (name, region_id)
            );

            CREATE INDEX IF NOT EXISTS idx_classes_region
            ON classes(region_id, name);

            CREATE TABLE IF NOT EXISTS event_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                cause TEXT NOT NULL DEFAULT '',
                process TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT '',
                sentiment TEXT NOT NULL DEFAULT 'neutral',
                importance INTEGER NOT NULL DEFAULT 3,
                tags TEXT NOT NULL DEFAULT '[]',
                source_kind TEXT NOT NULL,
                source_id TEXT NOT NULL,
                expires_turn INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subject_type, subject_id, event_type, source_kind, source_id)
            );

            CREATE INDEX IF NOT EXISTS idx_event_memories_subject
            ON event_memories(subject_type, subject_id, turn);

            CREATE INDEX IF NOT EXISTS idx_event_memories_turn
            ON event_memories(turn, importance);

            CREATE INDEX IF NOT EXISTS idx_event_memories_expiry
            ON event_memories(expires_turn, turn);


            CREATE TABLE IF NOT EXISTS event_memory_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL,
                source_kind TEXT NOT NULL,
                source_id TEXT NOT NULL,
                excerpt TEXT NOT NULL DEFAULT '',
                locator TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(memory_id) REFERENCES event_memories(id) ON DELETE CASCADE,
                UNIQUE(memory_id, source_kind, source_id, locator)
            );

            CREATE INDEX IF NOT EXISTS idx_event_memory_sources_memory
            ON event_memory_sources(memory_id);

            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        for column, definition in {
            "military_strength": "INTEGER NOT NULL DEFAULT 50",
            "cohesion": "INTEGER NOT NULL DEFAULT 50",
            "supply": "INTEGER NOT NULL DEFAULT 50",
            "last_action": "TEXT NOT NULL DEFAULT ''",
            "kind": "TEXT NOT NULL DEFAULT '敌国'",
            "aliases": "TEXT NOT NULL DEFAULT ''",
        }.items():
            self.ensure_column("powers", column, definition)
        self.ensure_column("armies", "owner_power", "TEXT NOT NULL DEFAULT 'ming'")
        self.ensure_column("armies", "province_pay_arrears", "REAL NOT NULL DEFAULT 0")
        self.ensure_column("armies", "central_pay_arrears", "REAL NOT NULL DEFAULT 0")
        self.ensure_column("armies", "pay_source_region", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("armies", "province_pay_share", "REAL NOT NULL DEFAULT 0")
        self.ensure_column("armies", "central_pay_share", "REAL NOT NULL DEFAULT 0")
        self.ensure_column("armies", "is_tusi", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("armies", "self_funded_pay", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("armies", "mutiny_status", "TEXT NOT NULL DEFAULT ''")
        # 火器装备(鸟铳,野战+守城)/大炮装备(红夷炮,守城攻城、不利野战)：simulator 软判用的两条军备轴
        self.ensure_column("armies", "firearm_equipment", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("armies", "cannon_equipment", "INTEGER NOT NULL DEFAULT 0")
        # #44 名义月饷率(两/兵·月)。仅列**首次 ADD** 时回填一次（gemini high：避免每次启动重扫/
        # 误覆盖动态态）；列已存在的后续 load 跳过（army_needed 的 rate<=0 锚定兜底 runtime 漏网）。
        if self.ensure_column("armies", "salary_rate", "REAL NOT NULL DEFAULT 0"):
            self._backfill_salary_rate()
        # #173：维护费列退役迁移——**必须在每个打开路径跑**。driver 开现存档只走 GameDB.__init__→
        # init_schema、不走 seed_static_data；若只挂 seed，现存档（probe.db: maintenance INTEGER
        # NOT NULL 无 default）永不删列 → 删列后建新军 INSERT（已不含该列）崩（cmr drop R1 codex high）。
        # 现存档此刻维护费列在：先确保 arrears 换算读完维护费（幂等 version gate），再 drop；新档此时
        # armies 空（CREATE TABLE 已无该列）→ 两步皆 no-op，seed 路再正常建。
        if self.table_has_rows("armies"):
            self._migrate_arrears_unit_to_silver(is_fresh_armies_seed=False)
        self._drop_maintenance_column()
        self.ensure_column("regions", "controlled_by", "TEXT NOT NULL DEFAULT 'ming'")
        # 城市等级 0-5(静态,史实分级,将来供经济/内政)+ 城防大炮门数(城头红夷炮,上限 city_level×8)
        self.ensure_column("regions", "city_level", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("regions", "cannon", "INTEGER NOT NULL DEFAULT 0")
        self._apply_region_city_levels()
        self.ensure_column("characters", "power_id", "TEXT NOT NULL DEFAULT 'ming'")
        self.ensure_column("characters", "location", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "transit_to", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "transit_start_turn", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("issues", "resolve_condition", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("issues", "fail_condition", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("issues", "end_turn", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("issues", "stop_condition", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("issues", "commitment_kind", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "birth_year", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("characters", "historical_death_year", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("characters", "historical_death_month", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("characters", "debut_year", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("characters", "debut_month", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("characters", "status", "TEXT NOT NULL DEFAULT 'active'")
        self.ensure_column("characters", "status_reason", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "reason_code", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "status_changed_turn", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("characters", "portrait_id", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "court_role", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "summary", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("characters", "aliases", "TEXT NOT NULL DEFAULT '[]'")
        self._backfill_person_core_character_static_fields()
        self._backfill_bandit_power_split()
        self.ensure_column("event_triggers", "terminal_state", "TEXT NOT NULL DEFAULT 'triggered'")
        self.ensure_column("event_triggers", "terminal_reason", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("event_triggers", "choice_json", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("pending_decisions", "event_id", "TEXT NOT NULL DEFAULT ''")
        self._backfill_event_triggers_from_event_pool_issues()
        # 步骤7：回合阶段（旧库迁移，schema 升级非 fallback）
        self.ensure_column("game_state", "turn_phase", "TEXT NOT NULL DEFAULT 'summoning'")
        # 结局：ended=1 时游戏终结；ending_status 为 context.ENDING_* 类型。
        self.ensure_column("game_state", "ended", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column("game_state", "ending_status", "TEXT NOT NULL DEFAULT ''")
        # 密令推演副作用列（result 留给承办人进展，sim_note 给推演写泄漏/反弹，互不覆盖）
        self.ensure_column("secret_orders", "sim_note", "TEXT NOT NULL DEFAULT ''")
        # 密令期限：0=无硬期限；到 due_turn 时自动转入待核议，由推演当月判 done/failed。
        self.ensure_column("secret_orders", "due_turn", "INTEGER NOT NULL DEFAULT 0")
        # BUG 3：directive 暂存 commit 成 turn_directives draft 时回填该 draft 行 id，
        # 使 undo_chat_turn 能精确删本轮自产的那条 draft（旧实现按 (turn,actor) 删，
        # 会连带删掉同 actor 同回合的无关 draft）。0=未 commit / 非 directive。
        self.ensure_column(
            "pending_actions", "committed_directive_id", "INTEGER NOT NULL DEFAULT 0")
        # fiscal_config 科目元数据列（数据驱动预算目录）：budget_role=fixed 的 base 项靠
        # account/direction/display 由 flows.compute_budget_lines 动态生成预算行；
        # dynamic 项（田赋/辽饷/盐税/商税/皇庄）走省级公式/皇庄专路，这三列留空。
        self.ensure_column("fiscal_config", "budget_role", "TEXT NOT NULL DEFAULT 'fixed'")
        self.ensure_column("fiscal_config", "account", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("fiscal_config", "direction", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("fiscal_config", "display", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column("fiscal_config", "sort_order", "INTEGER NOT NULL DEFAULT 9999")
        # economy_ledger 支出结构化标签：仅 extractor 抽出的 economy_moves 填这三列；
        # flows 月固定支出与所有收入留 NULL。purpose 受控枚举见 constants.ECONOMY_PURPOSES。
        self.ensure_column("economy_ledger", "purpose", "TEXT")
        self.ensure_column("economy_ledger", "target_kind", "TEXT")
        self.ensure_column("economy_ledger", "target_id", "TEXT")
        # 开局负面帝国修正：clear_gate(机器消除条件)、legacy_key(对应 opening_legacies.key，开局修正去重用)
        self.ensure_column("legacies", "clear_gate", "TEXT NOT NULL DEFAULT '{}'")
        self.ensure_column("legacies", "legacy_key", "TEXT NOT NULL DEFAULT ''")
        # #9 派系势力 offset 锚点：leverage = clamp(offset + 在朝官职权重和)。开局校准时
        # offset = 钦定基线 − 开局权重和（见 _calibrate_faction_offsets）。老档缺省 0，由该校准回填。
        # #9 cmr R3：记下「本次 init 是否刚 ADD 该列」——老档反推 offset 只许在列刚迁移那一次跑，
        # 之后每次 load 不再碰 offset（否则 leverage 被 clamp 后再 load，offset 被重锚成
        # round(clamped − weight_sum)≠原值 → 基线永久腐蚀）。该 flag 传给 _calibrate_faction_offsets。
        self._leverage_offset_col_added = self.ensure_column(
            "factions", "leverage_offset", "REAL NOT NULL DEFAULT 0"
        )
        # #9 线上 R3（codex P2）crash-safety：单靠「列刚 ADD」内存 flag 不够——若上次进程崩在
        # 『ensure_column 已 ADD 列、_calibrate_faction_offsets 未执行』之间，重启见列已存在 →
        # ensure_column 返 False → flag False → 跳过校准 → offset 全留 0 → 下次 reconcile 把白名单
        # leverage 重写成裸权重和(非锚定钦定基线)=平衡崩。故另立**持久校准标记**(metrics 表的
        # __leverage_offsets_calibrated)：校准成功时由 _calibrate_faction_offsets 写入；开档时只要
        # 标记缺失就补校准（与 flag 取或）。标记写入与 offset/leverage 写入同事务提交(见 1041 行的
        # commit)——崩在校准中途则标记未落、下次开档重做，二者全有或全无(原子)。
        self._leverage_offsets_calibrated = self._has_meta_flag("__leverage_offsets_calibrated")
        # 章节记忆正文：event_type='chapter_summary' 用，存整段叙事章节（不受 outcome 80 字限）。
        self.ensure_column("event_memories", "body", "TEXT NOT NULL DEFAULT ''")
        # extractor 产出的 canonical delta：resolve_context 无条件持久化的重跑真源（ADR 0008 S2）。
        # 老存档此列缺省 '{}'（HITL 暂停时 phase1 尚无 delta，亦填 '{}'）。
        self.ensure_column("pending_resolve_context", "extracted_delta_json", "TEXT NOT NULL DEFAULT '{}'")
        # 判别位：1=extractor 真产出过（'{}' 即真空 delta），0=占位（phase1 未跑/失败未存）。
        # 没有它 '{}' 三义不可分，恢复入口会把占位当真 delta 重放（cmr S2+S3 F1）。
        self.ensure_column("pending_resolve_context", "extracted_ready", "INTEGER NOT NULL DEFAULT 0")
        # 拒收 provenance source（#144 / ADR 0008 决定 5）：崩溃恢复重放须用原始来源，否则玩家
        # 来源(player_decree/hitl)的拒收被恢复路记成 system_simulation、静默不提示。老档缺省
        # 'system_simulation'（与原 resolve_settling_recovery 硬编值一致，行为不变）。
        self.ensure_column("pending_resolve_context", "source", "TEXT NOT NULL DEFAULT 'system_simulation'")
        # 后宫调教记录
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS consort_traits (
                name TEXT PRIMARY KEY,
                extra_skills TEXT NOT NULL DEFAULT '',
                extra_traits TEXT NOT NULL DEFAULT '',
                updated_turn INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 结局总结：每局结局触发时落一条（单 campaign 一库，turn 为主键，对齐 turn_reports）。
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ending_summary (
                turn INTEGER PRIMARY KEY,
                year INTEGER NOT NULL,
                period INTEGER NOT NULL,
                ending_status TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                timeline TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
        self._migrate_legacy_office_pollution()
        # #9 R1 finding#1 [P1]：老档迁移校准须放在「seed 路 + driver 路」都过的点。driver.open_game
        # 只 GameDB()（→ init_schema）+ load_state、不调 seed_static_data，故若校准仅在 seed 末尾，
        # driver 路老档的 offset 永远停在默认 0 → leverage=0+权重和（未锚定钦定基线、错值）。
        # 因此：leverage_offset 列**本次刚 ADD**且 factions 表已有行（=老档，characters 此刻亦已持久化、
        # 权重和可算）时，在此立即一次性反推校准（offset_col_added=True 走老档分支：offset=当前 DB
        # leverage − 权重和）。放在 _migrate_legacy_office_pollution 之后，使权重和按【已清洗】的 office
        # 算（与 seed 路 _migrate→_calibrate 同序；pre-0009 污染 office 在迁移前会算错权重和）。
        # 校准后 flag 被消费置 False（见 _calibrate_faction_offsets），seed 路再调时直接 return、不重锚。
        # fresh 新档此时 factions 表空（行在 seed_static_data 才 INSERT）→ 这里跳过，仍走 seed 末尾的
        # fresh 校准（从 content.factions 取钦定基线）。
        # #9 线上 R3 crash-safety：触发条件 = 列刚 ADD **或** 持久标记缺失（崩在加列/校准之间的老档）。
        # #9 线上 R4（codex P2）：「标记缺失」有两源——(a) 真崩在『加列/校准』之间（offset 仍全 0，须
        # 反推校准）；(b) 旧版 #9 代码已校准、当时尚无持久标记（offset 已非 0）。后者若被当崩溃态强制
        # 重锚，会把已被 clamp 偏离基线的 leverage 烙进 offset、永久腐蚀基线。故按 offset 是否全 0 区分：
        # 全 0=未校准（真崩溃/列刚 ADD）→ 反推校准；非全 0=已校准 → 只补持久标记、绝不重锚。
        if self.table_has_rows("factions") and (
            self._leverage_offset_col_added or not self._leverage_offsets_calibrated
        ):
            if self._leverage_offset_col_added or self._faction_offsets_all_zero():
                self._calibrate_faction_offsets(
                    is_fresh_factions_seed=False, offset_col_added=True
                )
            else:
                # 已校准缺标记（旧版遗留）：只补持久标记，offset 维持原校准值、不重锚。
                self._set_meta_flag("__leverage_offsets_calibrated")
                self._leverage_offsets_calibrated = True
                self._leverage_offset_col_added = False
            self.conn.commit()
        # #177 R1 finding#1（codex P2）：一次性 v2 迁移——旧版 #9 校准 round 了 offset（存整数），
        # R4 只修新校准、已 marked 老档 early-return 照漂。本迁移把整数 offset 重算成精确 float
        # （current_leverage − weight_sum），保持当前 leverage 不变、仅修存储精度防未来漂。
        # 只对 leverage 与 round(offset+权重和) 一致的 faction 跑（未手动 clamp/改），防把 clamp
        # 后的脏 leverage 烙进 offset（腐蚀基线）。幂等：v2 标记一旦落库就不再跑。
        if (
            self.table_has_rows("factions")
            and getattr(self, "_leverage_offsets_calibrated", False)
            and not self._has_meta_flag("__leverage_offsets_float_v2")
        ):
            self._migrate_offsets_to_float_precision()
            self._set_meta_flag("__leverage_offsets_float_v2")
            self.conn.commit()
        self.init_fiscal_config()
        self._migrate_missing_fiscal_engine_from_pay_source_cutover()

    def _migrate_legacy_office_pollution(self) -> None:
        """ADR 0009 决定9/L94 一次性数据清洗（幂等，init 时跑）：pre-0009 存档把状态词塞在
        office 串里（「前X，罢居Y」「…(在途)」），归位到 status/reason_code/location/transit_to，
        使其正确进人才池（G1）。**条件触发**（office 含污染标记才动）——不误降已被玩家起复的
        active 旧臣（其 office 已是真职、无标记，跳过）；幂等（清洗后再跑无标记可清）。"""
        import re
        # location 是 region_id；罢居地名（松江/高阳等府名）多非 region_id，只在解析出合法 region_id
        # 才写 location（同下方在途循环口径，不把府名硬塞进 region_id 列）；罢居地信息留在 status_reason。
        region_ids = {row["id"] for row in self.conn.execute("SELECT id FROM regions").fetchall()}
        # 罢居=居家可起复：钱谦益 天启科场案削籍 → dismissed（→昭雪，B 口径）；其余罢居 → offstage（→起复）。
        DISMISSED_OVERRIDE = {"钱谦益": "获罪削籍"}
        for r in self.conn.execute(
            "SELECT name, office FROM characters WHERE office LIKE '%罢居%' AND status='active'"
        ).fetchall():
            name = r["name"]
            office = str(r["office"] or "")
            m = re.search(r"罢居([^，,]+)", office)
            loc = m.group(1).strip() if m else ""
            loc_region = loc if loc in region_ids else ""
            if name in DISMISSED_OVERRIDE:
                status, rc = "dismissed", DISMISSED_OVERRIDE[name]
            else:
                status, rc = "offstage", "自请"
            self.conn.execute(
                "UPDATE characters SET status=?, reason_code=?, status_reason=?, office='', "
                "location=CASE WHEN COALESCE(location,'')='' THEN ? ELSE location END, transit_to='' "
                "WHERE name=?",
                (status, rc, office, loc_region, name),
            )
        # office 带「(在途)」→ 清串保留 active；transit_to 仅当解析出合法 region_id 才落（保守，不瞎猜目的地）。
        for r in self.conn.execute(
            "SELECT name, office FROM characters WHERE office LIKE '%在途%'"
        ).fetchall():
            name = r["name"]
            office = str(r["office"] or "")
            cleaned = office.replace("（在途）", "").replace("(在途)", "").strip().rstrip(",，")
            # 目的地是中文地名（辽东/陕西），region_id 是英文（liaodong/shaanxi）——直接
            # `in region_ids` 恒 False、transit_to 永不落（死分支，5b r6 Gemini high）。用
            # match_region_id_from_text 把中文解析成 region_id（同 db.py:2626 口径），解析得到才落。
            dest = ""
            for kw in ("督师", "镇守", "赴", "之任"):
                mm = re.search(kw + r"([一-龥]{2,4})", office)
                if mm:
                    rid = match_region_id_from_text(mm.group(1), self.content.regions)
                    if rid:
                        dest = rid
                        break
            if dest:
                self.conn.execute(
                    "UPDATE characters SET office=?, transit_to=? WHERE name=?", (cleaned, dest, name)
                )
            else:
                self.conn.execute(
                    "UPDATE characters SET office=? WHERE name=?", (cleaned, name)
                )
        self.conn.commit()

    def init_fiscal_config(self) -> None:
        """从 content/fiscal_config.json（self.content.fiscal_items）seed 财政科目目录。

        base/rate 单位为【月度】万两/%。科目目录与元数据全走 JSON 设定（铁律：设定走 JSON）；
        新档加税源只改 JSON；若老档也要补新 key，必须登记对应 schema_version 的差量迁移。

        ── 版本迁移策略（铁律：fiscal_config 只在建库时整体 seed 一次）──
        每个库带 `__schema_version`。本函数按它与 JSON schema_version 比对，分三种走法：

        - `cur == 0`（全新库，无版本行）：整体 seed JSON 全表 → 版本号置 JSON 版。仅此一次。
        - `cur < json`（老档升版）：逐版跑 `_FISCAL_MIGRATIONS[cur+1 .. json]` 的差量动作。
          新 schema 若要给老档补 key，必须在对应版本登记；未声明的 key 一律不碰
          （玩家削减/裁撤全保留）。未登记版本不再按当前 JSON 全表补缺；新 schema 正常迁移
          必须登记显式版本步。
        - `cur >= json`：**啥都不做**。已是最新，玩家状态神圣。

        ⇒ 玩家裁撤的科目读档后保持删除（不再被旧 INSERT OR IGNORE 复活）。
           JSON 加新税种【必须】同步升 schema_version，否则老档拿不到（CLAUDE.md 已要求）。
        """
        items = list(self.content.fiscal_items)
        if not items or "__schema_version" not in items[0]:
            raise SystemExit("init_fiscal_config: fiscal_items 缺 __schema_version 头，中止。")
        schema_version = int(items[0]["__schema_version"])
        rows = items[1:]

        def _meta(rec: Dict[str, object]) -> tuple:
            return (
                str(rec["key"]), int(rec["value"]), str(rec["kind"]), str(rec["note"]),
                str(rec.get("budget_role", "fixed")),
                str(rec.get("account", "")), str(rec.get("direction", "")),
                str(rec.get("display", "")), int(rec.get("order", 9999)),
            )

        cols = "(key, value, kind, note, budget_role, account, direction, display, sort_order)"

        def _seed_missing() -> None:
            """未登记版本步不补当前 JSON 全表；新增 key 必须走显式版本迁移。"""
            return None

        def _seed_keys(keys: "tuple[str, ...]") -> None:
            wanted = set(keys)
            self.conn.executemany(
                f"INSERT OR IGNORE INTO fiscal_config {cols} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_meta(rec) for rec in rows if str(rec["key"]) in wanted],
            )

        # 每版迁移：从 N-1 → N，只动那版真正变的东西。键＝目标版本号 N。
        # 将来要改某 key 默认 / 删某 key / 加新 key，就在这里登记一条 lambda，只动那一项，
        # 别动其它——这样玩家改过的全保住。未登记版本只保留旧兼容兜底，不作为正常迁移路径。
        _FISCAL_MIGRATIONS: "Dict[int, Any]" = {
            8: lambda: _seed_keys((
                "central_taicang_human_loss_rate",
                "central_taicang_sink_loss_rate",
                "central_jingyun_human_loss_rate",
                "central_jingyun_sink_loss_rate",
            )),
        }

        cur_ver_row = self.conn.execute(
            "SELECT value FROM fiscal_config WHERE key = '__schema_version'"
        ).fetchone()
        cur_ver = int(cur_ver_row["value"]) if cur_ver_row else 0

        if cur_ver >= schema_version:
            return  # 已最新，玩家状态神圣，碰都不碰

        if cur_ver == 0:
            # 全新库：整体 seed 一次。
            self.conn.executemany(
                f"INSERT INTO fiscal_config {cols} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_meta(rec) for rec in rows],
            )
        else:
            # 老档升版：逐版跑差量；未登记的版本步只补缺 key。
            for v in range(cur_ver + 1, schema_version + 1):
                (_FISCAL_MIGRATIONS.get(v) or _seed_missing)()

        self.conn.execute(
            "INSERT INTO fiscal_config (key, value, kind, note) VALUES "
            "('__schema_version', ?, 'meta', '财政默认值大版本号；老档升版逐版迁移，只动差量') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (schema_version,),
        )
        self.conn.commit()

    def iter_budget_items(self) -> "List[Dict[str, object]]":
        """返回 budget_role=fixed 的 base 科目（含 account/direction/display/sort_order）。

        flows.compute_budget_lines 据此动态生成固定收支预算行——加新税源不必改代码。
        每项配套的 *_rate 由调用方按 stem 自取（rate 项 budget_role 同 fixed 但 kind=rate，
        不在本列表里）。dynamic 项（田赋/辽饷/盐税/商税/皇庄）走省级公式，这里不返回。
        """
        rows = self.conn.execute(
            "SELECT key, account, direction, display, note, sort_order FROM fiscal_config "
            "WHERE budget_role = 'fixed' AND kind = 'base' AND key LIKE '%\\_base' ESCAPE '\\' "
            "ORDER BY sort_order, key"
        ).fetchall()
        return [
            {
                "key": str(r["key"]),
                "account": str(r["account"]),
                "direction": str(r["direction"]),
                "display": str(r["display"]),
                "note": str(r["note"] or ""),
            }
            for r in rows
        ]

    def get_fiscal_config(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT key, value FROM fiscal_config WHERE key NOT LIKE '\\_\\_%' ESCAPE '\\'"
        ).fetchall()
        return {str(r["key"]): int(r["value"]) for r in rows}

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
        self.conn.execute(
            "UPDATE fiscal_config SET value = ? WHERE key = ?", (value, key)
        )
        if commit and owns_transaction:
            self.conn.commit()

    def set_fiscal_config_batch(self, values: Dict[str, int], commit: bool = True) -> None:
        owns_transaction = self.owns_transaction() if commit else False
        normalized = {str(k or "").strip(): int(v) for k, v in values.items()}
        self.validate_fiscal_config_values(normalized)
        self.conn.executemany(
            "UPDATE fiscal_config SET value = ? WHERE key = ?",
            [(value, key) for key, value in normalized.items()],
        )
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
        exists = self.conn.execute(
            "SELECT 1 FROM fiscal_config WHERE key IN (?, ?)", (base_key, rate_key)
        ).fetchone()
        if exists is not None:
            return None
        sort_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 10 FROM fiscal_config"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO fiscal_config "
            "(key, value, kind, budget_role, account, direction, display, sort_order, note) "
            "VALUES (?, ?, 'base', 'fixed', ?, ?, ?, ?, ?)",
            (base_key, max(0, init_value), account, direction, display, sort_order, note),
        )
        self.conn.execute(
            "INSERT INTO fiscal_config "
            "(key, value, kind, budget_role, account, direction, display, sort_order, note) "
            "VALUES (?, 100, 'rate', 'fixed', ?, ?, ?, ?, ?)",
            (rate_key, account, direction, display, sort_order, f"{display}实收率%"),
        )
        if commit:
            self.conn.commit()
        return base_key

    # dynamic 税科目 → regions.fiscal 子字段映射。dynamic 税实收走 calc_province_fiscal
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
        for row in self.conn.execute("SELECT id, fiscal FROM regions").fetchall():
            fiscal: dict = json.loads(str(row["fiscal"] or "{}"))
            old = int(fiscal.get(field, 0) or 0)
            if old <= 0:
                continue
            new = max(0, round(old * ratio))
            if new == old:
                continue
            fiscal[field] = new
            self.conn.execute(
                "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(fiscal, ensure_ascii=False), str(row["id"])),
            )
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
        基座 dormant 期与旧 calc_province_fiscal 解耦，接入并轨在 slice3。
        """
        row = self.conn.execute(
            "SELECT fiscal FROM regions WHERE id = ?", (region_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"region {region_id!r} 不存在，无法 settle_tick")
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        return self._settle_province_tick_from_fiscal(region_id, fiscal, actions or [])

    def settle_ming_province_substrate_ticks(
        self,
        actions_by_region: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        p_overrides_by_region: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ProvinceFiscalTickOutcome]:
        """一次扫描 Ming 省 fiscal payload 并推进已有 settle 基座。

        动态 shadow spine 用这个批量桥，避免 selector 先解析、单省 bridge 再 SELECT/解析。
        合法但无 settle 的 Ming 省按旧语义出列；坏 JSON/容器/settle st/p 与 settle_tick
        ValueError/守恒错误作为 outcome.error 返回，供 shadow 调用方隔离 tlog。其它异常继续上抛，
        保持桥接 bug fail-loud。
        """
        from .fiscal_tick import FiscalConservationError

        actions_by_region = actions_by_region or {}
        p_overrides_by_region = p_overrides_by_region or {}
        outcomes: List[ProvinceFiscalTickOutcome] = []
        rows = self.conn.execute(
            "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
        ).fetchall()
        for row in rows:
            region_id = str(row["id"])
            try:
                fiscal = json.loads(str(row["fiscal"] or "{}"))
                if isinstance(fiscal, dict) and "settle" not in fiscal:
                    continue
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
        pay_rows: List[Dict[str, float | str]] = []
        standalone_pay_component: Optional[Dict[str, float]] = None
        if self.is_army_pay_source_cutover_enabled():
            pay_rows = self._derive_region_army_pay_due(region_id, settle)
            if pay_rows:
                primary_source_due = self._primary_source_army_pay_due(settle)
                if self._has_standalone_army_pay_funnel(settle, primary_source_due):
                    row_due_total = sum(float(row["due"]) for row in pay_rows)
                    row_arrears_total = sum(float(row["province_pay_arrears"]) for row in pay_rows)
                    standalone_pay_component = {
                        "due": self._standalone_army_pay_due_component(
                            settle,
                            row_due_total,
                            primary_source_due,
                        ),
                        "province_pay_arrears": self._standalone_army_pay_arrears_component(
                            settle,
                            row_arrears_total,
                            primary_source_due,
                        ),
                    }
        tick_p = settle["p"]
        if p_overrides:
            tick_p = dict(tick_p)
            tick_p.update(p_overrides)
        result = settle_tick(settle["st"], tick_p, actions)  # raise→下方不执行（港口锁）
        if pay_rows:
            self._apply_region_army_pay_tick(pay_rows, result, standalone_pay_component)
        settle["st"] = result.new_st
        if self.is_army_pay_source_cutover_enabled():
            self._refresh_standalone_army_pay_arrears_component(region_id, settle)
            if pay_rows:
                self._reconcile_region_army_pay_container(region_id, settle)
        self.conn.execute(
            "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(fiscal, ensure_ascii=False), region_id),
        )
        return result

    def scale_tian_fu(self, ratio: float, commit: bool = True) -> int:
        """田赋无独立字段（=tax_per_turn 减辽饷/盐税/商税的残差）。按 ratio 缩放田赋部分：
        新 tax_per_turn = 三税之和 + 田赋残差×ratio。ratio=0 即罢田赋（仅留三税基）。
        返回被改动的省数。"""
        touched = 0
        for row in self.conn.execute(
            "SELECT id, tax_per_turn, fiscal FROM regions"
        ).fetchall():
            fiscal: dict = json.loads(str(row["fiscal"] or "{}"))
            others = (int(fiscal.get("liao_xiang", 0) or 0)
                      + int(fiscal.get("salt_tax", 0) or 0)
                      + int(fiscal.get("commerce_tax", 0) or 0))
            tax = int(row["tax_per_turn"])
            tian_fu = max(0, tax - others)
            new_tax = others + max(0, round(tian_fu * ratio))
            if new_tax == tax:
                continue
            self.conn.execute(
                "UPDATE regions SET tax_per_turn = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_tax, str(row["id"])),
            )
            touched += 1
        if touched and commit:
            self.conn.commit()
        return touched

    def remove_fiscal_item(self, key: str, commit: bool = True) -> Optional[str]:
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
        exists = self.conn.execute(
            "SELECT 1 FROM fiscal_config WHERE key IN (?, ?)", (base_key, rate_key)
        ).fetchone()
        if exists is None:
            return None
        self.conn.execute(
            "DELETE FROM fiscal_config WHERE key IN (?, ?)", (base_key, rate_key)
        )
        # dynamic 税：同步罢废各省实收字段（皇庄走 config 不在此）。
        if stem in self._DYNAMIC_REGION_FIELD:
            self.apply_dynamic_fiscal_scale(stem, 0.0, commit=commit)
        elif stem == "田赋":
            self.scale_tian_fu(0.0, commit=commit)
        if commit:
            self.conn.commit()
        return base_key

    def ensure_column(self, table: str, column: str, definition: str) -> bool:
        """确保 table.column 存在。返回 True=本次新增了该列（真·一次性迁移），
        False=列已存在（后续 load 的常态）。多数 caller 忽略返回值即可。"""
        columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            return True
        return False

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
            self.conn.execute("UPDATE regions SET city_level=? WHERE id=?", (int(level), rid))

    def _backfill_salary_rate(self) -> None:
        """#44 旧档迁移（仅 salary_rate 列**首次 ADD** 时跑一次，见调用点 gate——线上 gemini high：
        避免每次启动重扫；与 army_needed 的 rate<=0 锚定互为兜底，迁移负责持久化合理率供显示/欠饷，
        army_needed 负责 runtime 漏网的 charge 防白嫖）。ensure_column 给 salary_rate 默认 0，但
        army_needed 判 rate<=0 → 锚定后才算，旧存档明军若不回填则显示/欠饷口径错（cmr r1 codex high）。
        回填 salary_rate<=0 的明军：
          ① static 军（在 content 且率>0）→ content.armies[id].salary_rate；
          ② 动态旧军（不在 content）且维护费列仍在 → 从 maintenance_per_turn 反推率
             = maint×10000/manpower（保旧档应发量级/欠饷连续，线上 codex P2）；
          ③ 维护费列已删（新档/已删档）或值不可用 → 边军史实锚点 SALARY_RATE_ANCHOR。
        #173 cmr drop R4（codex medium）：backfill 在 _drop_maintenance_column 之前跑，**直接升级
        老档**（salary_rate 首次 ADD 时维护费列仍在）须保留②反推保真——drop 后旧 pay 源无可恢复，
        若一律落锚点会把 5000 兵 maint=20 的军重定价成 ceil(5000×1.5/10000)=1、20→1 腐蚀旧档预算。
        故用 column-exists gate：列在走②反推，列不在（新档 CREATE 已无该列）走③锚点（SELECT 不读
        维护费、不崩）。该回填仅 salary_rate 列首次 ADD 时跑一次。只补 <=0 的、不覆盖已设正值（幂等）。"""
        has_maint = "maintenance_per_turn" in {
            r["name"] for r in self.conn.execute("PRAGMA table_info(armies)").fetchall()
        }
        # 两条完整字面 SQL 二选一（不 f-string 拼列名）：列在时多取 manpower/维护费供②反推。两 query 都
        # 无外部输入、纯字面常量（Sourcery R1 security：消除 raw-query 字符串拼接的 SQLi 告警面）。
        if has_maint:
            rows = self.conn.execute(
                "SELECT id, manpower, maintenance_per_turn FROM armies "
                "WHERE owner_power='ming' AND salary_rate <= 0"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM armies WHERE owner_power='ming' AND salary_rate <= 0"
            ).fetchall()
        for r in rows:
            aid = str(r["id"])
            army = self.content.armies.get(aid)
            if army is not None and army.salary_rate > 0:
                rate = float(army.salary_rate)                       # ① content 史实率
            elif has_maint:                                          # ② 直接升级老档：从维护费反推
                manpower = int(r["manpower"] or 0)
                maint = float(r["maintenance_per_turn"] or 0)
                rate = (maint * 10000 / manpower) if (manpower > 0 and maint > 0) else SALARY_RATE_ANCHOR
            else:                                                    # ③ 列已删/值不可用：锚点
                rate = SALARY_RATE_ANCHOR
            self.conn.execute("UPDATE armies SET salary_rate=? WHERE id=?", (rate, aid))

    def apply_region_cannon(self, state: "GameState", region_id: str, delta: int) -> int:
        """改某地城防大炮门数(城头红夷炮)。上限 = city_level×8；clamp [0, cap]。返回新值。
        全局严格：引用未入库地区抛错，不静默。"""
        row = self.conn.execute(
            "SELECT city_level, cannon FROM regions WHERE id=?", (region_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"城防炮引用未入库地区 '{region_id}'")
        cap = int(row["city_level"]) * 8
        new_value = max(0, min(cap, int(row["cannon"]) + int(delta)))
        self.conn.execute(
            "UPDATE regions SET cannon=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_value, region_id),
        )
        return new_value

    def table_has_rows(self, table: str) -> bool:
        row = self.conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None

    def seed_static_data(self) -> None:
        if not self.table_has_rows("offices"):
            for office_type, definition in self.content.office_definitions.items():
                self.conn.execute(
                    """
                    INSERT INTO offices
                    (office_type, skills, tools, authority_scope, power, responsibility, corruption_risk)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        office_type,
                        json.dumps(definition["skills"], ensure_ascii=False),
                        json.dumps(definition["tools"], ensure_ascii=False),
                        str(definition["authority_scope"]),
                        int(definition["power"]),
                        int(definition["responsibility"]),
                        int(definition["corruption_risk"]),
                    ),
                )

        if not self.table_has_rows("characters"):
            for character in self.content.characters.values():
                office = normalize_office(character.office)
                # 静态名册接档：content 已写好 office_type，表查不中也不逐人现拉 codex
                # （开局 LLM 风暴根因，~28 外藩/宗藩/平民官名 × 串行 codex ≈ 5 分钟）。
                office_type = infer_office_type_from_office(
                    office, character.office_type, self.llm_config, use_llm=False
                )
                self.conn.execute(
                    """
                    INSERT INTO characters
                    (name, office, office_type, faction, aliases, personal_skills, loyalty, ability, integrity, courage, style,
                     birth_year, historical_death_year, historical_death_month, debut_year, debut_month,
                     status, status_reason, status_changed_turn, portrait_id, power_id, location, transit_to, summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        character.name,
                        office,
                        office_type,
                        character.faction,
                        json.dumps(character.aliases, ensure_ascii=False),
                        json.dumps(character.personal_skills, ensure_ascii=False),
                        character.loyalty,
                        character.ability,
                        character.integrity,
                        character.courage,
                        character.style,
                        character.birth_year,
                        character.historical_death_year,
                        character.historical_death_month,
                        character.debut_year,
                        character.debut_month,
                        character.status,
                        "",
                        0,
                        character.portrait_id,
                        character.power_id,
                        character.location,
                        character.transit_to,
                        character.summary,
                    ),
                )
        if not self.table_has_rows("character_offices"):
            for row in self.conn.execute("SELECT name, office, office_type FROM characters").fetchall():
                self.conn.execute(
                    """
                    INSERT INTO character_offices (character_name, office_title, office_type, source)
                    VALUES (?, ?, ?, ?)
                    """,
                    (row["name"], row["office"], row["office_type"], "存档迁移"),
                )

        is_fresh_factions_seed = not self.table_has_rows("factions")
        if is_fresh_factions_seed:
            for faction in self.content.factions.values():
                self.conn.execute(
                    """
                    INSERT INTO factions (name, satisfaction, leverage, agenda)
                    VALUES (?, ?, ?, ?)
                    """,
                    (faction.name, faction.satisfaction, faction.leverage, faction.agenda),
                )
        if not self.table_has_rows("classes"):
            for cls in self.content.classes.values():
                self.conn.execute(
                    """
                    INSERT INTO classes (name, region_id, population, satisfaction, leverage, agenda)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cls.name, cls.region_id, cls.population, cls.satisfaction, cls.leverage, cls.agenda),
                )
        for power in self.content.powers.values():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO powers
                (id, name, kind, leader, stance, leverage, satisfaction, military_strength,
                 cohesion, supply, agenda, status, last_action, aliases)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    power.id,
                    power.name,
                    power.kind,
                    power.leader,
                    power.stance,
                    power.leverage,
                    power.satisfaction,
                    power.military_strength,
                    power.cohesion,
                    power.supply,
                    power.agenda,
                    power.status,
                    power.last_action,
                    json.dumps(power.aliases, ensure_ascii=False)
                    if isinstance(power.aliases, list)
                    else power.aliases,
                ),
            )
        for region in self.content.regions.values():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO regions
                (id, name, kind, population, public_support, unrest, natural_disaster, human_disaster,
                 registered_land, hidden_land, tax_per_turn, grain_security, gentry_resistance,
                 military_pressure, status, controlled_by, fiscal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    region.id,
                    region.name,
                    region.kind,
                    region.population,
                    region.public_support,
                    region.unrest,
                    region.natural_disaster,
                    region.human_disaster,
                    region.registered_land,
                    region.hidden_land,
                    region.tax_per_turn,
                    region.grain_security,
                    region.gentry_resistance,
                    region.military_pressure,
                    region.status,
                    region.controlled_by,
                    json.dumps(region.fiscal, ensure_ascii=False),
                ),
            )
        is_fresh_armies_seed = not self.table_has_rows("armies")
        if is_fresh_armies_seed:
            for army in self.content.armies.values():
                self.conn.execute(
                    """
                    INSERT INTO armies
                    (id, name, station, theater, commander, controller, troop_type, manpower,
                     supply, morale, training, equipment, arrears,
                     province_pay_arrears, central_pay_arrears, pay_source_region,
                     province_pay_share, central_pay_share, is_tusi, self_funded_pay,
                     mobility, loyalty, firearm_equipment, cannon_equipment, salary_rate, status, owner_power)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        army.id,
                        army.name,
                        army.station,
                        army.theater,
                        army.commander,
                        army.controller,
                        army.troop_type,
                        army.manpower,
                        army.supply,
                        army.morale,
                        army.training,
                        army.equipment,
                        army.arrears,
                        army.province_pay_arrears,
                        army.central_pay_arrears,
                        army.pay_source_region,
                        army.province_pay_share,
                        army.central_pay_share,
                        army.is_tusi,
                        army.self_funded_pay,
                        army.mobility,
                        army.loyalty,
                        army.firearm_equipment,   # 新档贯通火器/随军大炮（CMR codexB）
                        army.cannon_equipment,
                        army.salary_rate,         # #44 名义月饷率(两/兵·月)
                        army.status,
                        army.owner_power,
                    ),
                )
        if not self.table_has_rows("buildings"):
            for building in self.content.buildings.values():
                self.conn.execute(
                    """
                    INSERT INTO buildings
                    (id, region_id, name, category, level, condition, maintenance, risk,
                     output_metric, output_amount, status, origin, created_turn)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'preset', 0)
                    """,
                    (
                        building.id,
                        building.region_id,
                        building.name,
                        building.category,
                        building.level,
                        building.condition,
                        building.maintenance,
                        building.risk,
                        building.output_metric,
                        building.output_amount,
                        building.status,
                    ),
                )
        if not self.table_has_rows("events"):
            for event in (*self.content.events, *self.content.seed_events):
                self.conn.execute(
                    """
                    INSERT INTO events
                    (id, title, kind, summary, urgency, severity, credibility, interests, audiences)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.title,
                        event.kind,
                        event.summary,
                        event.urgency,
                        event.severity,
                        event.credibility,
                        json.dumps(event.interests, ensure_ascii=False),
                        json.dumps(event.audiences, ensure_ascii=False),
                    ),
                )
        self._migrate_arrears_unit_to_silver(is_fresh_armies_seed)
        self._initialize_army_pay_source_spine(is_fresh_armies_seed)
        # #173：维护费列退役 drop 已上移至 init_schema（每个打开路径都跑，含 driver 开现存档的纯
        # init_schema 路径，见 cmr drop R1）；此处新档 seed INSERT 后该列本就不存在，无需再 drop。
        self._apply_region_city_levels()  # 新档 region 此时才 INSERT 完，按史实补 city_level
        # 新档罢居/在途 office 污染清洗：init_schema 路径在空表上 no-op（构造在 seed 前），
        # 故 seed 后须再跑一次才对新档生效（决定9/L94 一次性清洗；幂等，老档由 init_schema
        # 路径已处理）。此刻 characters + regions 均已 INSERT，location region_id 校验可用。
        # 5b r4（Claude + codex-b concur, P1）：漏此调用则新档 7 名罢居旧臣留 active+污染、不进人才池。
        self._migrate_legacy_office_pollution()
        # #9：派系势力 offset 校准。此刻 factions + characters 均已 INSERT、office 污染已洗。
        # cmr R3：传 offset 列「本次是否刚 ADD」——老档反推只在迁移那次跑，常规 load 不碰 offset。
        self._calibrate_faction_offsets(
            is_fresh_factions_seed, getattr(self, "_leverage_offset_col_added", False)
        )
        self.conn.commit()

    def is_army_pay_source_cutover_enabled(self) -> bool:
        row = self.conn.execute(
            "SELECT value FROM fiscal_config WHERE key = ?",
            (_ARMY_PAY_SOURCE_CUTOVER_KEY,),
        ).fetchone()
        return bool(row and int(row["value"] or 0) == 1)

    def fiscal_engine(self) -> str:
        row = self.conn.execute(
            "SELECT value FROM fiscal_config WHERE key = ?",
            (_FISCAL_ENGINE_KEY,),
        ).fetchone()
        value = int(row["value"] or 0) if row is not None else _FISCAL_ENGINE_LEGACY
        return "substrate_hub" if value == _FISCAL_ENGINE_SUBSTRATE_HUB else "legacy"

    def is_substrate_hub_fiscal_engine_enabled(self) -> bool:
        return self.fiscal_engine() == "substrate_hub"

    def _migrate_missing_fiscal_engine_from_pay_source_cutover(self) -> None:
        if self.conn.execute(
            "SELECT 1 FROM fiscal_config WHERE key = ?",
            (_FISCAL_ENGINE_KEY,),
        ).fetchone():
            return
        if not self.is_army_pay_source_cutover_enabled():
            return
        self._mark_substrate_hub_fiscal_engine_enabled()
        self.conn.commit()

    def _mark_army_pay_source_cutover_enabled(self) -> None:
        self.conn.execute(
            """
            INSERT INTO fiscal_config (key, value, kind, note)
            VALUES (?, 1, 'meta', 'army pay source per-source accumulator cutover')
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, kind=excluded.kind, note=excluded.note
            """,
            (_ARMY_PAY_SOURCE_CUTOVER_KEY,),
        )

    def _mark_substrate_hub_fiscal_engine_enabled(self) -> None:
        self.conn.execute(
            """
            INSERT INTO fiscal_config (key, value, kind, note)
            VALUES (?, ?, 'meta', 'fiscal_engine=substrate_hub; legacy=0 substrate_hub=1')
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, kind=excluded.kind, note=excluded.note
            """,
            (_FISCAL_ENGINE_KEY, _FISCAL_ENGINE_SUBSTRATE_HUB),
        )

    def _initialize_army_pay_source_spine(self, is_fresh_armies_seed: bool) -> None:
        """Fresh-save cutover for #287 S1; existing saves stay on legacy army-pay flow."""
        if not is_fresh_armies_seed:
            return
        rows = self.conn.execute(
            """
            SELECT id, owner_power, arrears, pay_source_region,
                   province_pay_share, central_pay_share, is_tusi, self_funded_pay
            FROM armies
            ORDER BY id
            """
        ).fetchall()
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
            old_arrears = float(row["arrears"] or 0)
            if owner != "ming" or self_funded:
                if self_funded and old_arrears > 0:
                    seed_state = GameState()
                    self.conn.execute(
                        """
                        INSERT INTO army_logs
                        (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                        VALUES (?, ?, ?, ?, 'arrears', ?, '0.0', ?, ?, NULL, NULL, 'system')
                        """,
                        (
                            seed_state.turn, seed_state.year, seed_state.period, army_id,
                            str(old_arrears), -old_arrears,
                            "自养核销：土司/自养军欠饷不并入朝廷饷源双累加器",
                        ),
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
            self.conn.execute(
                """
                UPDATE armies
                SET pay_source_region = ?, province_pay_share = ?, central_pay_share = ?,
                    province_pay_arrears = ?, central_pay_arrears = ?, arrears = ?,
                    is_tusi = ?, self_funded_pay = ?
                WHERE id = ?
                """,
                (
                    source, province_share, central_share,
                    province_arrears, central_arrears, total_arrears,
                    1 if is_tusi else 0, 1 if self_funded else 0, army_id,
                ),
            )
        self._mark_army_pay_source_cutover_enabled()
        self._mark_substrate_hub_fiscal_engine_enabled()
        self._reconcile_all_army_pay_source_regions()
        self._reconcile_central_army_pay_arrears_container()
        self.assert_army_pay_source_container_conservation()

    def get_central_army_pay_arrears_container(self) -> float:
        row = self.conn.execute(
            "SELECT value FROM fiscal_containers WHERE key = ?",
            (_CENTRAL_ARMY_PAY_ARREARS_CONTAINER_KEY,),
        ).fetchone()
        return float(row["value"] or 0.0) if row is not None else 0.0

    def _reconcile_central_army_pay_arrears_container(self) -> float:
        total = self.conn.execute(
            """
            SELECT COALESCE(SUM(central_pay_arrears), 0) AS total
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
            """
        ).fetchone()["total"]
        value = float(total or 0.0)
        self.conn.execute(
            """
            INSERT INTO fiscal_containers (key, value, note)
            VALUES (?, ?, '中央军饷欠账容器：Σ非自养明军 central_pay_arrears')
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              note = excluded.note,
              updated_at = CURRENT_TIMESTAMP
            """,
            (_CENTRAL_ARMY_PAY_ARREARS_CONTAINER_KEY, value),
        )
        return value

    def _province_army_pay_container_total(self) -> float:
        total = 0.0
        rows = self.conn.execute(
            "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'"
        ).fetchall()
        for row in rows:
            try:
                fiscal = json.loads(str(row["fiscal"] or "{}"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"region {row['id']} fiscal JSON 非法，无法校验军饷容器守恒") from exc
            settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
            if settle is None:
                continue
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                raise ValueError(f"region {row['id']} settle.st 非法，无法校验军饷容器守恒")
            total += float(settle["st"].get("军饷欠", 0) or 0.0)
        return total

    def _is_seeded_military_pay_funnel(self, settle: Dict[str, Any]) -> bool:
        meta = settle.get("_meta")
        if not isinstance(meta, dict):
            return False
        postures = meta.get("postures")
        return isinstance(postures, list) and "纯军饷漏斗" in postures

    def _has_standalone_army_pay_funnel(
        self,
        settle: Dict[str, Any],
        primary_source_due: Optional[float] = None,
    ) -> bool:
        return primary_source_due is not None or self._is_seeded_military_pay_funnel(settle)

    def _standalone_army_pay_due_component(
        self,
        settle: Dict[str, Any],
        row_due_total: float,
        primary_source_due: Optional[float],
    ) -> float:
        if primary_source_due is not None:
            return primary_source_due
        if not self._is_seeded_military_pay_funnel(settle):
            return 0.0
        meta = settle.setdefault("_meta", {})
        if not isinstance(meta, dict):
            raise ValueError("_meta 非字典")
        existing = meta.get("standalone_military_pay_due")
        if isinstance(existing, bool):
            raise ValueError("standalone_military_pay_due 非法")
        if isinstance(existing, (int, float)):
            value = float(existing)
        else:
            p_obj = settle.get("p")
            if not isinstance(p_obj, dict):
                raise ValueError("settle.p 非法")
            due_obj = p_obj.get("Due")
            if not isinstance(due_obj, dict):
                raise ValueError("settle.p.Due 非法")
            value = float(due_obj.get("军饷", 0) or 0) - row_due_total
        if not math.isfinite(value) or value < -1e-9:
            raise ValueError("standalone_military_pay_due 非法")
        value = max(0.0, value)
        meta["standalone_military_pay_due"] = value
        return value

    def _standalone_army_pay_arrears_component(
        self,
        settle: Dict[str, Any],
        row_arrears_total: float,
        primary_source_due: Optional[float],
    ) -> float:
        if not self._has_standalone_army_pay_funnel(settle, primary_source_due):
            return 0.0
        meta = settle.setdefault("_meta", {})
        if not isinstance(meta, dict):
            raise ValueError("_meta 非字典")
        existing = meta.get("standalone_military_pay_arrears")
        if isinstance(existing, bool):
            raise ValueError("standalone_military_pay_arrears 非法")
        if isinstance(existing, (int, float)):
            value = float(existing)
        else:
            st = settle.get("st")
            if not isinstance(st, dict):
                raise ValueError("settle.st 非法")
            value = float(st.get("军饷欠", 0) or 0) - row_arrears_total
        if not math.isfinite(value) or value < -1e-9:
            raise ValueError("standalone_military_pay_arrears 非法")
        value = max(0.0, value)
        meta["standalone_military_pay_arrears"] = value
        return value

    def _refresh_standalone_army_pay_arrears_component(
        self,
        region_id: str,
        settle: Dict[str, Any],
    ) -> None:
        primary_source_due = self._primary_source_army_pay_due(settle)
        if not self._has_standalone_army_pay_funnel(settle, primary_source_due):
            return
        row_arrears_total = sum(
            float(row["province_pay_arrears"])
            for row in self._army_pay_source_rows_for_region(region_id)
        )
        st = settle.get("st")
        if not isinstance(st, dict):
            raise ValueError("settle.st 非法")
        current_total = float(st.get("军饷欠", 0) or 0)
        standalone_arrears = max(0.0, current_total - row_arrears_total)
        meta = settle.setdefault("_meta", {})
        if not isinstance(meta, dict):
            raise ValueError("_meta 非字典")
        meta["standalone_military_pay_arrears"] = standalone_arrears

    def _standalone_army_pay_container_total(self) -> float:
        total = 0.0
        rows = self.conn.execute(
            "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming'"
        ).fetchall()
        for row in rows:
            region_id = str(row["id"])
            try:
                fiscal = json.loads(str(row["fiscal"] or "{}"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"region {region_id} fiscal JSON 非法，无法校验军饷容器守恒") from exc
            settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                continue
            primary_source_due = self._primary_source_army_pay_due(settle)
            if not self._has_standalone_army_pay_funnel(settle, primary_source_due):
                continue
            row_arrears_total = sum(
                float(row["province_pay_arrears"])
                for row in self._army_pay_source_rows_for_region(region_id)
            )
            total += self._standalone_army_pay_arrears_component(
                settle,
                row_arrears_total,
                primary_source_due,
            )
        return total

    def _primary_source_only_army_pay_container_total(self) -> float:
        return self._standalone_army_pay_container_total()

    def _has_complete_province_pay_containers(self) -> bool:
        rows = self.conn.execute(
            """
            SELECT DISTINCT pay_source_region
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
              AND pay_source_region != ''
              AND (province_pay_share > 0 OR province_pay_arrears > 0)
            """
        ).fetchall()
        for row in rows:
            region_id = str(row["pay_source_region"] or "")
            region = self.conn.execute(
                "SELECT controlled_by, fiscal FROM regions WHERE id = ?", (region_id,)
            ).fetchone()
            if region is None or str(region["controlled_by"] or "") != "ming":
                return False
            try:
                fiscal = json.loads(str(region["fiscal"] or "{}"))
            except (TypeError, ValueError):
                return False
            settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict):
                return False
        return True

    def assert_army_pay_source_container_conservation(self) -> None:
        if not self.is_army_pay_source_cutover_enabled():
            return
        exempt_bad = self.conn.execute(
            """
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
            """
        ).fetchone()
        if exempt_bad is not None:
            raise ValueError(
                "army "
                f"{exempt_bad['id']} 自养/非明军双累加器必须为 0"
            )
        if self.is_substrate_hub_fiscal_engine_enabled():
            province_source_rows = self.conn.execute(
                """
                SELECT id, pay_source_region
                FROM armies
                WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
                  AND (
                    ABS(COALESCE(province_pay_share, 0)) > 1e-9 OR
                    ABS(COALESCE(province_pay_arrears, 0)) > 1e-9
                  )
                ORDER BY id
                """
            ).fetchall()
            for province_source in province_source_rows:
                self._require_valid_pay_source_region(
                    str(province_source["id"]),
                    str(province_source["pay_source_region"] or ""),
                )
        derived_bad = self.conn.execute(
            """
            SELECT id, arrears, province_pay_arrears, central_pay_arrears
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
              AND ABS(
                COALESCE(arrears, 0)
                - (COALESCE(province_pay_arrears, 0) + COALESCE(central_pay_arrears, 0))
              ) > 1e-6
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
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
        row = self.conn.execute(
            """
            SELECT
              COALESCE(SUM(province_pay_arrears), 0) AS province_total,
              COALESCE(SUM(central_pay_arrears), 0) AS central_total,
              COALESCE(SUM(arrears), 0) AS army_total
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
            """
        ).fetchone()
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
        standalone_total = self._standalone_army_pay_container_total()
        expected_province_container = province_total + standalone_total
        if abs(province_container - expected_province_container) > 1e-6:
            raise ValueError(
                "省级军饷欠容器守恒破："
                f"container={province_container} "
                f"Σprovince={province_total} "
                f"Σstandalone={standalone_total}"
            )
        expected_total = army_total + standalone_total
        if abs((province_container + central_container) - expected_total) > 1e-6:
            raise ValueError(
                "双容器守恒破："
                f"Σcontainer={province_container + central_container} "
                f"Σarmy={army_total} "
                f"Σstandalone={standalone_total}"
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
        row = self.conn.execute(
            "SELECT controlled_by, fiscal FROM regions WHERE id = ?", (pay_source_region,)
        ).fetchone()
        if row is None:
            raise ValueError(f"army {army_id} pay_source_region 未入库：{pay_source_region}")
        if str(row["controlled_by"] or "") != "ming":
            raise ValueError(f"army {army_id} pay_source_region 非明控省：{pay_source_region}")
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"army {army_id} pay_source_region 财政基座 JSON 非法：{pay_source_region}"
            ) from exc
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            raise ValueError(f"army {army_id} pay_source_region 无 settle st/p 基座：{pay_source_region}")

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
    ) -> None:
        normalized = {
            ARMY_FIELD_ALIASES.get(str(k).strip(), str(k).strip()): v
            for k, v in raw_changes.items()
        }
        present = _ARMY_PAY_SOURCE_DELTA_FIELDS.intersection(normalized)
        if not present:
            return

        army_id = str(row["id"])
        if "owner_power" in normalized:
            proposed_owner = str(normalized.get("owner_power") or "").strip()
            owner_exists = self.conn.execute(
                "SELECT 1 FROM powers WHERE id = ?", (proposed_owner,)
            ).fetchone()
            if owner_exists is None:
                changes.append({
                    "army": row["name"], "field": "owner_power",
                    "rejected": True, "category": "hallucinated_id",
                    "reason": f"army_delta owner_power '{proposed_owner}' 不在 powers 表",
                    "item": {"army_id": army_id, "changes": raw_changes},
                })
                return
        old_source = str(row["pay_source_region"] or "")
        owner_power = str(normalized.get("owner_power", row["owner_power"]) or "").strip()
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
                str(row["owner_power"] or "") == "ming"
                and owner_power == "ming"
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

        old_values = {
            "owner_power": row["owner_power"],
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
            "owner_power": owner_power,
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
        wrote_owner_transfer_writeoff = (
            str(old_values["owner_power"]) == "ming"
            and owner_power != "ming"
            and float(old_values["arrears"] or 0) > 1e-9
            and float(new_values["arrears"] or 0) == 0.0
        )
        if wrote_owner_transfer_writeoff:
            self.conn.execute(
                """
                INSERT INTO army_logs
                (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                VALUES (?, ?, ?, ?, 'arrears', ?, '0.0', ?, ?, ?, ?, ?)
                """,
                (
                    state.turn, state.year, state.period, army_id,
                    str(old_values["arrears"]), -float(old_values["arrears"]),
                    f"owner易主核销：{reason}",
                    event.id, edict_id, actor,
                ),
            )
            changed_fields = [field for field in changed_fields if field != "arrears"]

        self.conn.execute(
            """
            UPDATE armies
            SET owner_power = ?, pay_source_region = ?,
                province_pay_share = ?, central_pay_share = ?,
                is_tusi = ?, self_funded_pay = ?,
                province_pay_arrears = ?, central_pay_arrears = ?,
                arrears = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                owner_power, pay_source_region, province_share, central_share,
                1 if is_tusi else 0, 1 if self_funded else 0,
                province_arrears, central_arrears, province_arrears + central_arrears,
                army_id,
            ),
        )
        for field in changed_fields:
            self.conn.execute(
                """
                INSERT INTO army_logs
                (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    state.turn, state.year, state.period, army_id, field,
                    str(old_values[field]), str(new_values[field]), reason,
                    event.id, edict_id, actor,
                ),
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
        from ming_sim.flows import army_needed

        out: List[Dict[str, float | str]] = []
        rows = self.conn.execute(
            """
            SELECT id, name, manpower, salary_rate, owner_power, pay_source_region, morale,
                   province_pay_share, central_pay_share, province_pay_arrears,
                   central_pay_arrears, is_tusi, self_funded_pay
            FROM armies
            WHERE pay_source_region = ? AND owner_power = 'ming'
              AND is_tusi = 0 AND self_funded_pay = 0
              AND province_pay_share > 0
            ORDER BY id
            """,
            (region_id,),
        ).fetchall()
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

    def _primary_source_army_pay_due(self, settle: Dict[str, Any]) -> Optional[float]:
        meta = settle.get("_meta")
        if not isinstance(meta, dict):
            return None
        primary_source = meta.get("primary_source")
        if not isinstance(primary_source, dict):
            return None
        refined = primary_source.get("fields_refined")
        if not isinstance(refined, list) or "军饷" not in refined:
            return None
        if "现额银两_年" not in primary_source:
            return None
        raw_annual = primary_source.get("现额银两_年")
        if isinstance(raw_annual, bool) or not isinstance(raw_annual, (int, float)):
            raise ValueError("primary_source 现额银两_年 非法，无法派生 Due.军饷")
        value = float(raw_annual) / 10000 / 12
        if not math.isfinite(value) or value < 0:
            raise ValueError("primary_source 现额银两_年 非法，无法派生 Due.军饷")
        return value

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
        primary_source_due = self._primary_source_army_pay_due(settle)
        row_due_total = sum(float(row["due"]) for row in rows)
        row_arrears_total = sum(float(row["province_pay_arrears"]) for row in rows)
        if self._has_standalone_army_pay_funnel(settle, primary_source_due):
            standalone_due = self._standalone_army_pay_due_component(
                settle,
                row_due_total,
                primary_source_due,
            )
            due_obj["军饷"] = standalone_due + row_due_total
        elif rows:
            due_obj["军饷"] = row_due_total
        else:
            due_obj["军饷"] = 0
        if self._has_standalone_army_pay_funnel(settle, primary_source_due):
            standalone_arrears = self._standalone_army_pay_arrears_component(
                settle,
                row_arrears_total,
                primary_source_due,
            )
            st["军饷欠"] = standalone_arrears + row_arrears_total
        elif rows:
            st["军饷欠"] = row_arrears_total
        else:
            st["军饷欠"] = 0
        return rows

    def _reconcile_all_army_pay_source_regions(self) -> None:
        rows = self.conn.execute(
            "SELECT id, fiscal FROM regions WHERE controlled_by = 'ming' ORDER BY id"
        ).fetchall()
        for row in rows:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
            settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
            if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                    or not isinstance(settle.get("p"), dict):
                continue
            pay_rows = self._derive_region_army_pay_due(str(row["id"]), settle)
            if pay_rows:
                self._reconcile_region_army_pay_container(str(row["id"]), settle)
            self.conn.execute(
                "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(fiscal, ensure_ascii=False), str(row["id"])),
            )

    def _reconcile_army_pay_source_region_container(self, region_id: str) -> None:
        if not region_id or not self.is_army_pay_source_cutover_enabled():
            return
        row = self.conn.execute(
            "SELECT fiscal FROM regions WHERE id = ?", (region_id,)
        ).fetchone()
        if row is None:
            return
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError):
            return
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if not isinstance(settle, dict) or not isinstance(settle.get("st"), dict) \
                or not isinstance(settle.get("p"), dict):
            return
        self._derive_region_army_pay_due(region_id, settle)
        self.conn.execute(
            "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(fiscal, ensure_ascii=False), region_id),
        )

    def _apply_region_army_pay_tick(
        self,
        pay_rows: List[Dict[str, float | str]],
        result: Any,
        standalone_pay_component: Optional[Dict[str, float]] = None,
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
        standalone_id = "__standalone_military_pay_funnel__"
        if standalone_pay_component is not None:
            standalone_due = float(standalone_pay_component.get("due", 0.0) or 0.0)
            standalone_arrears = float(
                standalone_pay_component.get("province_pay_arrears", 0.0) or 0.0
            )
            if standalone_due > 0 or standalone_arrears > 0:
                balances[standalone_id] = standalone_arrears
                due_by_component[standalone_id] = standalone_due
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
        state_row = self.conn.execute(
            "SELECT turn, year, period FROM game_state WHERE id = 1"
        ).fetchone()
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
            total_due = float(row["total_due"])
            morale_delta = army_pay_morale_delta(total_due, total_shortfall, old_total_arrears)
            new_morale = max(0, min(100, old_morale + morale_delta))
            self.conn.execute(
                """
                UPDATE armies
                SET province_pay_arrears = ?, arrears = ?, morale = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (province_arrears, province_arrears + central_arrears, new_morale, army_id),
            )
            province_delta = province_arrears - old_province_arrears
            reason = f"{TURN_UNIT}省源军饷分账"
            if abs(province_delta) > 1e-9:
                reason_parts = []
                if new_debt_by_army[army_id] > 1e-9:
                    reason_parts.append(
                        f"按本月省份额应付占比摊新增欠{new_debt_by_army[army_id]:g}万两"
                    )
                repaid_total = action_repaid_by_army[army_id] + surplus_repaid_by_army[army_id]
                if repaid_total > 1e-9:
                    reason_parts.append(
                        f"按省份额欠余额占比偿还{repaid_total:g}万两"
                    )
                if reason_parts:
                    reason += "（" + "；".join(reason_parts) + "）"
                self.conn.execute(
                    """
                    INSERT INTO army_logs
                    (turn, year, period, army_id, field, old_value, new_value, delta,
                     reason, event_id, edict_id, actor)
                    VALUES (?, ?, ?, ?, 'province_pay_arrears', ?, ?, ?, ?, NULL, NULL, '户部')
                    """,
                    (
                        log_turn, log_year, log_period, army_id,
                        str(old_province_arrears), str(province_arrears),
                        province_delta, reason,
                    ),
                )
            morale_actual_delta = new_morale - old_morale
            if morale_actual_delta != 0:
                self.conn.execute(
                    """
                    INSERT INTO army_logs
                    (turn, year, period, army_id, field, old_value, new_value, delta,
                     reason, event_id, edict_id, actor)
                    VALUES (?, ?, ?, ?, 'morale', ?, ?, ?, ?, NULL, NULL, '户部')
                    """,
                    (
                        log_turn, log_year, log_period, army_id,
                        str(old_morale), str(new_morale), morale_actual_delta, reason,
                    ),
                )

    def _reconcile_region_army_pay_container(self, region_id: str, settle: Dict[str, Any]) -> None:
        total = self.conn.execute(
            """
            SELECT COALESCE(SUM(province_pay_arrears), 0) AS total
            FROM armies
            WHERE pay_source_region = ? AND owner_power = 'ming'
              AND is_tusi = 0 AND self_funded_pay = 0
            """,
            (region_id,),
        ).fetchone()["total"]
        row_arrears_total = float(total or 0)
        primary_source_due = self._primary_source_army_pay_due(settle)
        standalone_arrears = self._standalone_army_pay_arrears_component(
            settle,
            row_arrears_total,
            primary_source_due,
        )
        st = settle.get("st")
        if not isinstance(st, dict):
            raise ValueError("settle.st 非法")
        st["军饷欠"] = standalone_arrears + row_arrears_total

    def _drop_maintenance_column(self) -> None:
        """#173：物理移除退役的 armies.maintenance_per_turn 列（月饷由 army_needed 按兵力派生）。
        幂等：列存在才 DROP（SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN，本仓 3.53）。调用点保证排在
        所有读维护费的迁移之后（见 init_schema：salary_rate backfill + arrears 换算之后）：老档此刻列
        仍在、迁移已读完，drop 安全；新档/已删档无此列，PRAGMA 查不到 → no-op。"""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(armies)").fetchall()}
        if "maintenance_per_turn" in cols:
            self.conn.execute("ALTER TABLE armies DROP COLUMN maintenance_per_turn")
            self.conn.commit()  # DDL 显式提交，保证 drop 跨打开/环境持久（Gemini PR R3；init_schema
                                # 末尾另有 commit 兜底，此处显式化事务边界、不依赖后续步骤的提交时机）

    def _migrate_arrears_unit_to_silver(self, is_fresh_armies_seed: bool) -> None:
        """一次性迁移：armies.arrears 从 0-100 抽象分换成累计欠饷万两。
        旧档按 arrears * maintenance_per_turn / 25 估算（粗略：旧分数 ≈ 4 倍欠饷月数）。

        区分新老档：
        - 新档（is_fresh_armies_seed=True）：armies 由本版 seed_armies 刚刚写入，arrears
          已经是万两。直接打 version=1，跳过换算。
        - 老档（is_fresh_armies_seed=False）：armies 表早已存在数据；若 fiscal_config 中
          无 __arrears_unit_version 标记，说明从未跑过本迁移 → 走换算逻辑。
        """
        ARREARS_UNIT_VERSION = 1
        row = self.conn.execute(
            "SELECT value FROM fiscal_config WHERE key = '__arrears_unit_version'"
        ).fetchone()
        cur = int(row["value"]) if row else 0
        if cur >= ARREARS_UNIT_VERSION:
            return
        if not is_fresh_armies_seed:
            # 真老档：换算分数 → 万两。#173：换算读 maintenance_per_turn，仅在列仍在时跑（调用点排在
            # _drop_maintenance_column 之前，老档此刻列必在；加 column-exists gate 是防御未来顺序变化/
            # 已删档误入此路——列没了则跳过换算、只打 version，arrears 保持原值）。
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(armies)").fetchall()}
            if "maintenance_per_turn" in cols:
                self.conn.execute(
                    "UPDATE armies SET arrears = CAST(arrears * maintenance_per_turn / 25.0 AS INTEGER) "
                    "WHERE maintenance_per_turn > 0"
                )
        # 无论新老档，都把 version 打上，下次启动直接跳过
        self.conn.execute(
            "INSERT INTO fiscal_config (key, value, kind, note) VALUES "
            "('__arrears_unit_version', ?, 'meta', 'arrears 单位由 0-100 分迁至累计欠饷万两的版本号') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, note = excluded.note",
            (ARREARS_UNIT_VERSION,),
        )

    def _backfill_person_core_character_static_fields(self) -> None:
        mao = self.content.characters.get("毛文龙")
        if mao and mao.location:
            self.conn.execute(
                """
                UPDATE characters
                SET location = ?
                WHERE name = '毛文龙'
                  AND COALESCE(location, '') = ''
                  AND COALESCE(transit_to, '') = ''
                """,
                (mao.location,),
            )
        for name in ("李自成", "张献忠"):
            ch = self.content.characters.get(name)
            if not ch or ch.debut_year <= 0:
                continue
            self.conn.execute(
                """
                UPDATE characters
                SET debut_year = ?, debut_month = ?
                WHERE name = ?
                  AND status = 'offstage'
                  AND COALESCE(debut_year, 0) = 0
                  AND COALESCE(debut_month, 0) = 0
                """,
                (ch.debut_year, ch.debut_month, name),
            )
        self.conn.commit()

    def _backfill_bandit_power_split(self) -> None:
        for power_id in ("bandit_li_zicheng", "bandit_zhang_xianzhong"):
            power = self.content.powers.get(power_id)
            if not power:
                continue
            self.conn.execute(
                """
                INSERT OR IGNORE INTO powers
                (id, name, kind, leader, stance, leverage, satisfaction, military_strength,
                 cohesion, supply, agenda, status, last_action, aliases)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    power.id,
                    power.name,
                    power.kind,
                    power.leader,
                    power.stance,
                    power.leverage,
                    power.satisfaction,
                    power.military_strength,
                    power.cohesion,
                    power.supply,
                    power.agenda,
                    power.status,
                    power.last_action,
                    json.dumps(power.aliases, ensure_ascii=False)
                    if isinstance(power.aliases, list)
                    else power.aliases,
                ),
            )
        for name in ("李自成", "张献忠"):
            ch = self.content.characters.get(name)
            if not ch or not ch.power_id or ch.power_id == "bandits":
                continue
            if self.conn.execute("SELECT 1 FROM powers WHERE id=?", (ch.power_id,)).fetchone() is None:
                continue
            self.conn.execute(
                """
                UPDATE characters
                SET power_id = ?
                WHERE name = ?
                  AND COALESCE(power_id, '') IN ('', 'bandits')
                """,
                (ch.power_id, name),
            )
        self.conn.commit()

    def _backfill_event_triggers_from_event_pool_issues(self) -> None:
        pending_core_effect_ids = {
            ev.id for ev in (*self.content.events, *self.content.seed_events)
            if ev.auto_trigger and bool(ev.effect_on_trigger)
        }
        rows = self.conn.execute(
            """
            WITH legacy AS (
                SELECT origin_ref AS event_id, MIN(origin_turn) AS turn
                FROM issues
                WHERE origin_kind = 'event_pool' AND origin_ref <> ''
                GROUP BY origin_ref
            )
            SELECT
                legacy.event_id AS event_id,
                legacy.turn AS turn,
                COALESCE(turn_reports.year, game_state.year, 0) AS year,
                COALESCE(turn_reports.period, game_state.period, 0) AS period
            FROM legacy
            LEFT JOIN turn_reports ON turn_reports.turn = legacy.turn
            LEFT JOIN game_state ON game_state.id = 1
            """,
        ).fetchall()
        for row in rows:
            event_id = str(row["event_id"] or "")
            if event_id in pending_core_effect_ids:
                continue
            self.conn.execute(
                """
                INSERT OR IGNORE INTO event_triggers
                    (event_id, turn, year, period, source, terminal_state, terminal_reason)
                VALUES (?, ?, ?, ?, 'legacy_event_pool', 'triggered', '')
                """,
                (event_id, row["turn"], row["year"], row["period"]),
            )
        self.conn.commit()

    def has_state(self) -> bool:
        row = self.conn.execute("SELECT 1 FROM game_state WHERE id = 1").fetchone()
        return row is not None

    def save_state(self, state: GameState) -> None:
        self.conn.execute(
            """
            INSERT INTO game_state (id, year, period, turn, turn_phase, ended, ending_status)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET year = excluded.year, period = excluded.period,
                turn = excluded.turn, turn_phase = excluded.turn_phase,
                ended = excluded.ended, ending_status = excluded.ending_status
            """,
            (
                state.year, state.period, state.turn, state.turn_phase,
                1 if state.ended else 0, state.ending_status,
            ),
        )
        for key, value in state.metrics.items():
            self.conn.execute(
                """
                INSERT INTO metrics (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
        self.sync_economy_accounts(state)
        self.conn.commit()

    def load_state(self, start_ym: str = "") -> GameState:
        row = self.conn.execute(
            "SELECT year, period, turn, turn_phase, ended, ending_status FROM game_state WHERE id = 1"
        ).fetchone()
        if row is None:
            state = GameState()
            if start_ym:
                try:
                    y_str, m_str = start_ym.split(".")
                    y, m = int(y_str), int(m_str)
                except (ValueError, AttributeError):
                    raise SystemExit(f"--start-ym 格式非法：{start_ym!r}，应为 YYYY.MM（如 1629.04）。")
                if not (1627 <= y <= 1644 and 1 <= m <= 12):
                    raise SystemExit(f"--start-ym 超范围：{start_ym!r}，年须 1627-1644、月 1-12。")
                state.turn = (y - 1627) * 12 + (m - 10) + 1
                state.year, state.period = y, m
                print(f"[调试] 跳到 {y}年{m}月起手（turn={state.turn}）。")
            self.save_state(state)
            self.ensure_opening_ledger(state)
            self.seed_opening_crises(state)
            self.seed_opening_gazette(state)
            return state
        metrics = {
            metric["key"]: int(metric["value"])
            for metric in self.conn.execute("SELECT key, value FROM metrics").fetchall()
        }
        state = GameState(
            year=int(row["year"]), period=int(row["period"]), turn=int(row["turn"]),
            turn_phase=str(row["turn_phase"] or "summoning"),
            ended=bool(row["ended"]) if "ended" in row.keys() else False,
            ending_status=str(row["ending_status"] or "") if "ending_status" in row.keys() else "",
        )
        if metrics:
            # 只接当前 GameState 默认 dict 里有的 key，避免旧 DB 残留废弃 metric 灌入。
            valid_keys = set(state.metrics.keys())
            state.metrics.update({k: v for k, v in metrics.items() if k in valid_keys})
        account_rows = self.conn.execute("SELECT account, balance FROM economy_accounts").fetchall()
        for account in account_rows:
            account_name = str(account["account"])
            balance = int(account["balance"])
            state.metrics[account_name] = balance
        self.sync_economy_accounts(state)
        self.ensure_opening_ledger(state)
        self.conn.commit()
        return state

    def sync_economy_accounts(self, state: GameState) -> None:
        notes = {
            "国库": "朝廷公开财政，用于军饷、赈济、官俸和工程。",
            "内库": "皇帝可直接调度的钱物，用于救急、密支和政治缓冲。",
        }
        for account in ECONOMY_ACCOUNTS:
            self.conn.execute(
                """
                INSERT INTO economy_accounts (account, metric_key, balance, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account) DO UPDATE SET
                    balance = excluded.balance,
                    note = excluded.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (account, account, int(state.metrics[account]), notes[account]),
            )

    def ensure_opening_ledger(self, state: GameState) -> None:
        for account in ECONOMY_ACCOUNTS:
            exists = self.conn.execute(
                "SELECT 1 FROM economy_ledger WHERE account = ? LIMIT 1",
                (account,),
            ).fetchone()
            if exists:
                continue
            balance = int(state.metrics[account])
            self.conn.execute(
                """
                INSERT INTO economy_ledger
                (turn, year, period, account, delta, balance_after, category, reason, actor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (state.turn, state.year, state.period, account, balance, balance, "期初", "登基初始账册", "内阁"),
            )
        self.conn.commit()

    def seed_opening_gazette(self, state: GameState) -> None:
        """新档塞一份「即位前一月」邸报（turn=state.turn-1），让大臣首回合即可经 read_past_report
        查到开局朝局速览，不必凭空臆议。已存在则不覆盖。文本来自 content/opening_gazette.md。"""
        prev_turn = state.turn - 1
        prev_year, prev_period = state.year, state.period - 1
        if prev_period < 1:
            prev_period = 12
            prev_year -= 1
        exists = self.conn.execute(
            "SELECT 1 FROM turn_reports WHERE turn = ?",
            (prev_turn,),
        ).fetchone()
        if exists is not None:
            return
        from pathlib import Path
        from ming_sim.paths import bundled_path
        gazette_path = Path(bundled_path("content", "opening_gazette.md"))
        if not gazette_path.is_file():
            return
        text = gazette_path.read_text(encoding="utf-8").strip()
        if not text:
            return
        self.conn.execute(
            "INSERT INTO turn_reports (turn, year, period, report) VALUES (?, ?, ?, ?)",
            (prev_turn, prev_year, prev_period, text),
        )
        self.conn.commit()

    def seed_opening_crises(self, state: GameState) -> None:
        """新档首次进入时塞 1627 即位即面对的危机为 active situation issue。
        数据源已并入 seed_events.json：取标了 auto_trigger 且 trigger_gate 为空（开局盘面无条件
        即达标）的 situation 事件，开局直接立项，使玩家召见前就看到三大危机。
        其余带 gate 的 seed 事件靠 auto_trigger_seed_issues 在 gate 达标的回合再硬立。"""
        if not getattr(self, "content", None):
            return
        for ev in self.content.seed_events:
            if not ev.auto_trigger or ev.trigger_gate:
                continue
            if ev.event_type != "situation":
                continue
            if self.find_any_issue_by_origin("event_pool", ev.id) is not None:
                continue
            # 推导默认 bar / inertia / ongoing / effect，与 event_to_issue 同口径；精调字段优先
            bar = ev.bar_value or max(20, min(60, 50 - int(ev.severity / 5)))
            inertia = ev.issue_inertia  # 默认 0=不漂；要月漂在 seed 里显式填
            try:
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
                )
            except Exception as exc:
                print(f"[WARN] 开局危机落库失败：{exc}；跳过 {ev.title}")

    def set_character_status(
        self,
        state: GameState,
        name: str,
        status: str,
        reason: str = "",
        reason_code: str | None = None,
        commit: bool = True,
    ) -> None:
        """改人物状态：active/offstage/dismissed/imprisoned/exiled/retired/dead。
        大臣走 characters 表；后宫（consorts）走内存对象 + consort_traits 备档。
        #9：状态变更后全重算所属朝堂派系 leverage（在朝成员官职权重和 + offset；党魁倒台势力跟跌）。"""
        valid = {"active", "offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}
        if status not in valid:
            raise ValueError(f"character status 非法：{status}")
        # #9：UPDATE 前读旧派系（退场清 office 后仍按当前在朝成员现算，与旧职无关）。
        prev = self.conn.execute(
            "SELECT faction FROM characters WHERE name=?", (name,)
        ).fetchone()
        # 去职（下狱/革职/流放/致仕/出宫/死）即削职：清空 characters.office，
        # 原职仍留在 character_offices 备档可追溯。复职（active）不动 office。
        ousted = status in _OUSTED_STATES
        reason_code_value = str(reason_code or "")[:40]
        if ousted:
            self.conn.execute(
                "UPDATE characters SET status=?, status_reason=?, "
                "status_changed_turn=?, office='', transit_to='', transit_start_turn=0, reason_code=? WHERE name=?",
                (status, reason[:200], state.turn, reason_code_value, name),
            )
        else:
            self.conn.execute(
                "UPDATE characters SET status=?, status_reason=?, status_changed_turn=?, reason_code=? WHERE name=?",
                (status, reason[:200], state.turn, reason_code_value, name),
            )
        # #9：状态变更后全重算该人物所属朝堂派系 leverage（绝对值、读当前所有在朝成员 → 无漂移）。
        if prev is not None:
            self.recompute_faction_leverage(str(prev["faction"] or ""))
        if commit:
            self.conn.commit()

    def _faction_office_weight_sum(self, faction: str) -> float:
        """该 faction 当前所有 status='active' 的大明成员的官职权重和
        （每人 = office_type 域权重 × 品级档 multiplier）。只算大明朝臣（power_id='ming'）——
        外藩成员即便挂 ming 风格头衔也不握明官；白名单派系本就全 ming，此约束为防御。"""
        rows = self.conn.execute(
            "SELECT office_type, office FROM characters "
            "WHERE faction=? AND status='active' AND power_id='ming'",
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
        row = self.conn.execute(
            "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
        ).fetchone()
        if row is None:
            return
        offset = float(row["leverage_offset"] or 0)
        weight_sum = self._faction_office_weight_sum(faction)
        new_lev = max(0, min(100, round(offset + weight_sum)))
        self.conn.execute("UPDATE factions SET leverage=? WHERE name=?", (new_lev, faction))

    def recompute_all_faction_leverage(self) -> None:
        """#9 cmr R2：全量重算所有白名单朝堂派系 leverage（集中化兜底层）。

        两层设计：
          (1) 即时 hook（set_character_status / set_character_office / _displace_duplicate_offices /
              add_character）——单个成员状态/官职/易主变动时就地重算其所属派系，保回合内即时联动。
          (2) 本方法（reconcile 兜底）——在月末结算尾（settle_with_delta 的 atomic 内、delta 全部
              落库且 inertia 推进之后、next_period 之前）扫一遍全部白名单派系，重算成公式末值。
              覆盖任何绕过 hook 的路径（裸 UPDATE 改 office_type、power_id 翻走的易主/降臣、
              放归赦还后任命被拒回滚、未挂 hook 的新建大臣 等），保末态与公式一致、无残留漂移。
        绝对重算（每个派系从 offset+当前在朝权重和现算、不累加）→ 幂等、时序无关、即便已被
        hook 重算过再扫一遍也得同值。不在此 commit——由调用方（结算 atomic）统一提交。"""
        for faction in _LEVERAGE_FACTIONS:
            self.recompute_faction_leverage(faction)

    def _faction_offsets_all_zero(self) -> bool:
        """白名单派系的 leverage_offset 是否全为 0。用于区分「列已存在但缺持久校准标记」的两态
        （#9 线上 R4 codex P2）：全 0 = 校准从未跑过（真崩在『加列/校准』之间，或列刚 ADD 默认 0）
        → 须反推校准；任一非 0 = 已校准过（旧版 #9 代码遗留、当时尚无持久标记）→ 只补标记、绝不
        重锚（重锚会把 clamp 后偏离基线的 leverage 烙进 offset、永久腐蚀基线）。
        安全性论证（线上 R4 双 reviewer concur 复核后修正）：leverage_offset = 钦定基线 − 开局权重和；
        要全六派系恰为 0 需每派系『钦定基线==开局权重和』——实际 content 下各派系基线与开局权重和
        有显著差（offset 均非 0），故「已校准却全 0」这一误判窗口对真实存档不可达。安全性据此
        （已校准态不可能与『offset 全 0』共存），**不**依赖『全 0 ⇒ leverage 未 clamp 故重校准幂等』
        的假设——该假设在玩过多回合、weight_sum 漂移触 clamp 后并不恒成立（codex R4 指出的缺口，
        但其触发前提『全派系 offset 同时为 0』本身不可达，故不构成真实风险）。

        逐派系单参数查询（白名单仅 6 项）——不拼 IN(...) 动态占位串（线上 R5 sourcery opengrep
        把 .format 拼 SQL 标为注入面；虽只拼 `?` 占位、值仍参数绑定无注入，此写法更干净地避开）。"""
        for faction in _LEVERAGE_FACTIONS:
            row = self.conn.execute(
                "SELECT leverage_offset FROM factions WHERE name=?", (faction,)
            ).fetchone()
            if row is not None and float(row["leverage_offset"] or 0) != 0:
                return False
        return True

    def _calibrate_faction_offsets(
        self, is_fresh_factions_seed: bool, offset_col_added: bool = False
    ) -> None:
        """#9 offset 校准：offset = 基线 leverage − 当前在朝官职权重和。每个 DB 生命周期最多跑一次。
        新档（is_fresh_factions_seed）：基线取**钦定 content.factions[f].leverage**（不读 DB——
        污染清洗的 set_character_status 已用 offset=0 把 DB leverage 改脏，读 DB 会把脏值烙进 offset），
        校准后立即 recompute 令 DB leverage 自洽（开局权重和稳定 → leverage 复现钦定基线、保开局平衡）。
        老档且 offset 列**本次刚 ADD**（真·一次性迁移）：基线取**当前 DB leverage**（玩过后的真值），
        offset 令首次 recompute 不跳变（幂等迁移）；不 recompute（避免把老档当前值改动）。
        否则（列已存在的常规后续 load）：**直接 return、什么都不碰**——offset 已校准。
        cmr R3：缺这一闸，老档每次 load 都重锚 offset；leverage 被 clamp 到 0/100 后再 load，
        offset 会被重锚成 round(clamped − weight_sum)≠原值，基线永久腐蚀。
        只校准白名单 faction；非白名单 offset 留 0、leverage 永不被 recompute 触碰。
        不在此 commit——由 seed_static_data 末尾统一提交。
        #9 线上 R3 crash-safety：校准成功后写持久标记 __leverage_offsets_calibrated；该标记已存在
        （已校准过）则直接 return、绝不再碰 offset——比内存 flag 更强（跨进程/跨实例、崩溃可检测）。"""
        # 持久标记已在（上一生命周期校准成功落库）且**列非本次刚 ADD**（offset 数据仍在）：绝不再碰
        # offset——堵「已校准的 leverage 被 clamp 后再重锚成 round(clamped−weight) 腐蚀基线」。
        # 注意须排除 offset_col_added：列若刚被 DROP+重 ADD（offset 数据已丢），即便 metrics 里残留
        # 旧标记也必须重校准（数据真没了），否则 offset 全留 0、leverage 被重写成裸权重和。
        if not offset_col_added and self._has_meta_flag("__leverage_offsets_calibrated"):
            self._leverage_offset_col_added = False
            return
        # 老档常规 load（列早已存在、offset 已校准）：绝不再碰 offset。
        if not is_fresh_factions_seed and not offset_col_added:
            return
        # #9 R1 finding#3：一次性迁移 flag 用后即消费置 False（无论本次走老档反推还是 fresh 校准，
        # 都已锚定完毕）。否则同实例第二次 seed_static_data 仍见 flag=True、再进老档迁移分支，把
        # 已 clamp 的 leverage 重锚成 round(clamped − weight_sum)≠原值 → 基线腐蚀。
        self._leverage_offset_col_added = False
        for faction in _LEVERAGE_FACTIONS:
            row = self.conn.execute(
                "SELECT leverage FROM factions WHERE name=?", (faction,)
            ).fetchone()
            if row is None:
                continue  # 该白名单派系不在本档 factions 表（数据缺失）→ 跳过
            if is_fresh_factions_seed:
                content_faction = self.content.factions.get(faction)
                if content_faction is None:
                    continue
                baseline = int(content_faction.leverage)
            else:
                baseline = int(row["leverage"])
            weight_sum = self._faction_office_weight_sum(faction)
            offset = baseline - weight_sum
            self.conn.execute(
                "UPDATE factions SET leverage_offset=? WHERE name=?", (offset, faction)
            )
            if is_fresh_factions_seed:
                # 立即 recompute 令 DB leverage 与公式自洽（修污染清洗用 offset=0 写脏的中间值）。
                self.recompute_faction_leverage(faction)
        # 校准成功：落持久标记。与上面 offset/leverage 的写在同一事务（调用方统一 commit），
        # 崩在校准中途则标记一并未落、下次开档重做（原子：offset+标记 全有或全无）。
        self._set_meta_flag("__leverage_offsets_calibrated")
        self._leverage_offsets_calibrated = True
        # #177 R1 finding#1（codex P2）：当前校准已存精确 float offset → 同时落 v2 标记，
        # 使 init_schema 的 v2 迁移跳过（免对已正确存 float 的档重复扫）。
        self._set_meta_flag("__leverage_offsets_float_v2")

    def _migrate_offsets_to_float_precision(self) -> None:
        """#177 R1 finding#1（codex P2）：一次性 v2 迁移——旧版 #9 校准 round 了 offset（存整数），
        R4 修了新校准、但已 marked 老档 early-return 照漂。本方法把 offset 重算成精确 float
        （current_leverage − weight_sum），**保持当前 leverage 不变**、仅修存储精度防未来漂移。
        只对 leverage 与 round(offset+权重和) 一致的 faction 跑——不一致 = leverage 被手动
        clamp/改过，不碰 offset（保 baseline 信息、防腐蚀，同 _calibrate_faction_offsets 安全论证）。"""
        for faction in _LEVERAGE_FACTIONS:
            row = self.conn.execute(
                "SELECT leverage, leverage_offset FROM factions WHERE name=?", (faction,)
            ).fetchone()
            if row is None:
                continue
            current_lev = int(row["leverage"])
            weight_sum = self._faction_office_weight_sum(faction)
            current_offset = float(row["leverage_offset"] or 0)
            # 只在 raw 公式值未越界 [0,100] 且 leverage 与之一致时重算——否则跳过保 baseline。
            # 先判 raw 越界（不 clamp）：raw 越界时 clamp 后的 expected_lev 可能巧合等于
            # current_lev（一个本身被 clamp 的脏值），被误判「一致」而错误迁移——但 clamped
            # 脏值反推不出真实 offset、不该碰（cmr R2 CodeRabbit 精修）。
            raw_lev = current_offset + weight_sum
            if raw_lev < 0 or raw_lev > 100:
                continue
            expected_lev = round(raw_lev)
            if expected_lev != current_lev:
                continue
            new_offset = current_lev - weight_sum
            self.conn.execute(
                "UPDATE factions SET leverage_offset=? WHERE name=?", (new_offset, faction)
            )

    def _has_meta_flag(self, key: str) -> bool:
        """查 metrics 表里某持久标记是否存在（#9 R3 crash-safe 迁移标记用）。metrics 在 init_schema
        建表脚本里已建，故此调用安全。值约定 1=已置位。"""
        row = self.conn.execute(
            "SELECT value FROM metrics WHERE key=?", (key,)
        ).fetchone()
        return row is not None and int(row["value"]) == 1

    def _set_meta_flag(self, key: str) -> None:
        """置 metrics 表里某持久标记=1（幂等 upsert）。不在此 commit——由调用方统一提交，
        与同事务的其它写一并落库或一并回滚。"""
        self.conn.execute(
            "INSERT INTO metrics(key, value) VALUES(?, 1) "
            "ON CONFLICT(key) DO UPDATE SET value=1",
            (key,),
        )

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
    ) -> None:
        if isinstance(normalized, dict):
            normalized_text = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        else:
            normalized_text = str(normalized or "")
        self.conn.execute(
            """
            INSERT INTO person_logs
            (turn, year, period, person_name, action, payload_summary, derived_from, normalized, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.turn,
                state.year,
                state.period,
                person_name,
                action,
                str(payload_summary or "")[:200],
                str(derived_from or "")[:120],
                normalized_text,  # 全量存：normalized 是结构化审计 JSON，[:500] 会从中间切断成不可解析（PR #106 CodeRabbit）
                str(source or "")[:80],
            ),
        )
        if commit:
            self.conn.commit()

    def get_character_status(self, name: str) -> Tuple[str, str]:
        row = self.conn.execute(
            "SELECT status, status_reason FROM characters WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return ("active", "")
        return (row["status"], row["status_reason"] or "")

    def resolve_power_id(self, character) -> str:
        """人物所属势力 id 的权威解析：DB 行 power_id 优先，回退内存 power_id，默认 ming。

        DB 为准是关键：招抚归明者（流寇/降将 power_id 经 apply_character_power_changes 翻 ming，
        但 content/内存 power_id 仍是旧势力 bandits/houjin）必须认 DB——否则按内存会把已归明者
        误判为外藩、误拒在朝堂外（见 #125、web_app._character_power_id 同源）。"""
        row = self.conn.execute(
            "SELECT power_id FROM characters WHERE name=?", (character.name,)
        ).fetchone()
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
        valid_powers = {r["id"] for r in self.conn.execute("SELECT id FROM powers").fetchall()}
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
            row = self.conn.execute(
                "SELECT power_id, faction FROM characters WHERE name=?", (name,)
            ).fetchone()
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
            self.conn.execute(
                "UPDATE characters SET power_id = ? WHERE name = ?",
                (new_power, name),
            )
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
    ) -> None:
        """既有官员调任/升迁：改 characters.office（office_type 给空则不动），
        同步 character_offices 备档。状态不变（仍 active）。
        #9：授官改了 office_type/品级 → 末尾全重算所属朝堂派系 leverage（升迁也联动；
        起复路 set_character_status(active)→set_character_office(新职) 双 recompute，新职覆盖中间值）。"""
        office = normalize_office(office)
        current_type = (
            self.conn.execute(
                "SELECT office_type FROM characters WHERE name=? AND power_id='ming'", (name,)
            ).fetchone() or {"office_type": ""}
        )["office_type"]
        if not current_type:
            raise ValueError(f"{name}不属大明朝廷，不能授予大明官职")
        eff_type = infer_office_type_from_office(office, office_type or current_type, llm_config or self.llm_config)
        if office_type or eff_type != current_type:
            self.conn.execute(
                "UPDATE characters SET office=?, office_type=? WHERE name=?",
                (office, eff_type, name),
            )
        else:
            self.conn.execute(
                "UPDATE characters SET office=? WHERE name=?",
                (office, name),
            )
        self.conn.execute(
            """
            INSERT INTO character_offices (character_name, office_title, office_type, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(character_name) DO UPDATE SET
                office_title = excluded.office_title,
                office_type = excluded.office_type,
                source = excluded.source,
                updated_at = CURRENT_TIMESTAMP
            """,
            (name, office, eff_type, source),
        )
        # #9：授官改了 office_type/品级权重 → 全重算该人物所属朝堂派系 leverage（commit 前）。
        faction_row = self.conn.execute(
            "SELECT faction FROM characters WHERE name=?", (name,)
        ).fetchone()
        if faction_row is not None:
            self.recompute_faction_leverage(str(faction_row["faction"] or ""))
        if commit:
            self.conn.commit()
        if name in self.content.characters:
            self.content.characters[name].office = office
            self.content.characters[name].office_type = eff_type

    def apply_historical_deaths(self, state: GameState) -> List[Dict[str, str]]:
        """月初 tick：只有仍 active 的人到点自然死。被玩家提前罢/狱/流/杀的不走此分支。
        只打讣闻、改 status=dead，不动派系/metric。是否升级 issue 由 LLM 看本月邸报判断。
        返回 [{name, office, faction}] 喂给 simulator 当月上下文。
        """
        rows = self.conn.execute(
            """SELECT name, office, faction, historical_death_year, historical_death_month
               FROM characters
               WHERE status = 'active' AND historical_death_year > 0"""
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
                state, name, "dead", f"历史卒于 {year}年{month or '?'}月", reason_code="历史卒"
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
        rows = self.conn.execute(
            """SELECT name, office, faction, debut_year, debut_month
               FROM characters
               WHERE status = 'offstage' AND debut_year > 0"""
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
                state, name, "active", f"历史登场 {year}年{month or '?'}月", reason_code="登场"
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

    # ── 后宫调教 ──────────────────────────────────────────────────────────

    def get_consort_traits(self, name: str) -> dict:
        """返回 {extra_skills: [...], extra_traits: [...]}，不存在时返回空。"""
        row = self.conn.execute(
            "SELECT extra_skills, extra_traits FROM consort_traits WHERE name=?", (name,)
        ).fetchone()
        if not row:
            return {"extra_skills": [], "extra_traits": []}
        skills = [s.strip() for s in row["extra_skills"].split("，") if s.strip()]
        traits = [t.strip() for t in row["extra_traits"].split("，") if t.strip()]
        return {"extra_skills": skills, "extra_traits": traits}

    def cultivate_consort(self, name: str, turn: int, skill: str = "", trait: str = "") -> dict:
        """追加技能或性格词，去重后持久化。返回最新值。"""
        current = self.get_consort_traits(name)
        skills = current["extra_skills"]
        traits = current["extra_traits"]
        if skill and skill not in skills:
            skills.append(skill)
        if trait and trait not in traits:
            traits.append(trait)
        self.conn.execute(
            """INSERT INTO consort_traits(name, extra_skills, extra_traits, updated_turn)
               VALUES(?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 extra_skills=excluded.extra_skills,
                 extra_traits=excluded.extra_traits,
                 updated_turn=excluded.updated_turn,
                 updated_at=CURRENT_TIMESTAMP""",
            (name, "，".join(skills), "，".join(traits), turn),
        )
        self.conn.commit()
        return {"extra_skills": skills, "extra_traits": traits}

    def next_pool_portrait_id(self, prefix: str = "minister_pool_") -> str:
        """分配下一个预设头像 ID（顺序递增，不循环）。
        minister_pool: 60 个槽；consort_pool: 20 个槽。
        实际可用槽位 = web/public/portraits/<prefix><N>.png 真存在的编号集合（中途删图会跳过缺号）。
        发行包只带 web/dist；public 不存在时回退扫 web/dist/portraits。
        全部用完后再回退到递增（前端 onError fallback 占位符）。"""
        rows = self.conn.execute(
            "SELECT portrait_id FROM characters WHERE portrait_id LIKE ?",
            (prefix + "%",),
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

    def set_portrait_id(self, name: str, portrait_id: str) -> None:
        """改某人物的头像标识（如皇帝上传自定义立绘后落库）。"""
        self.conn.execute(
            "UPDATE characters SET portrait_id=? WHERE name=?",
            (portrait_id, name),
        )
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
        existing = self.conn.execute(
            "SELECT name FROM characters WHERE name=?", (character.name,)
        ).fetchone()
        if existing is not None:
            return
        character.office = normalize_office(character.office)
        character.office_type = infer_office_type_from_office(
            character.office,
            character.office_type,
            llm_config or self.llm_config,
        )
        # 若没有专属 portrait_id，按 office_type 分配预设池头像
        portrait_id = character.portrait_id
        if not portrait_id:
            prefix = "consort_pool_" if character.office_type == "后宫" else "minister_pool_"
            portrait_id = self.next_pool_portrait_id(prefix)
        source_label = source or ("吏部铨选任命" if character.office_type != "后宫" else "诏书纳妃")
        office_source = source or ("吏部任命" if character.office_type != "后宫" else "诏书纳妃")
        self.conn.execute(
            """
            INSERT INTO characters
            (name, office, office_type, faction, aliases, personal_skills, loyalty, ability, integrity, courage, style,
             birth_year, historical_death_year, historical_death_month, debut_year, debut_month,
             status, status_reason, status_changed_turn, portrait_id, power_id, location, transit_to, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                character.name,
                character.office,
                character.office_type,
                character.faction,
                json.dumps(character.aliases, ensure_ascii=False),
                json.dumps(character.personal_skills, ensure_ascii=False),
                character.loyalty,
                character.ability,
                character.integrity,
                character.courage,
                character.style,
                character.birth_year,
                character.historical_death_year,
                character.historical_death_month,
                character.debut_year,
                character.debut_month,
                character.status,
                source_label,
                state.turn,
                portrait_id,
                getattr(character, "power_id", "ming") or "ming",
                getattr(character, "location", "") or "",
                getattr(character, "transit_to", "") or "",
                getattr(character, "summary", "") or "",
            ),
        )
        self.conn.execute(
            """
            INSERT INTO character_offices (character_name, office_title, office_type, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(character_name) DO UPDATE SET
                office_title = excluded.office_title,
                office_type = excluded.office_type,
                source = excluded.source,
                updated_at = CURRENT_TIMESTAMP
            """,
            (character.name, character.office, character.office_type, office_source),
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

    def record_economy_moves(
        self,
        state: GameState,
        event: Event,
        edict_id: int,
        actor: str,
        moves: List[Dict[str, object]],
    ) -> None:
        if not moves:
            self.sync_economy_accounts(state)
            self.conn.commit()
            return
        for move in moves:
            self.conn.execute(
                """
                INSERT INTO economy_ledger
                (turn, year, period, account, delta, balance_after, category, reason, event_id, edict_id, actor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.turn,
                    state.year,
                    state.period,
                    str(move["account"]),
                    int(move["delta"]),
                    int(move["balance_after"]),
                    str(move["category"]),
                    str(move["reason"]),
                    event.id,
                    edict_id,
                    actor,
                ),
            )
        self.sync_economy_accounts(state)
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

        def _parts(acc: str, direction: str, names: tuple[str, ...]) -> str:
            present = [name for name in names if _amt(acc, direction, name)]
            return "+".join(present) if present else "无"

        gk_in, gk_out = _sum("国库", "income"), _sum("国库", "expense")
        nk_in, nk_out = _sum("内库", "income"), _sum("内库", "expense")
        gk_income_names = _parts(
            "国库", "income",
            ("起运", "田赋辽饷盐商", "盐税", "商税"),
        )
        if self.is_substrate_hub_fiscal_engine_enabled():
            expense_present = [
                "边饷hub" if _amt("国库", "expense", "各军军饷") else "",
                *(
                    name for name in (
                        "中央军饷", "太仓亏空", "宗室禄米", "百官俸禄", "工部",
                        "赈灾备用", "建筑维护",
                    )
                    if _amt("国库", "expense", name)
                ),
            ]
            gk_expense_names = "+".join(name for name in expense_present if name) or "无"
        else:
            gk_expense_names = _parts(
                "国库", "expense",
                ("各军军饷", "宗室禄米", "百官俸禄", "工部", "赈灾备用", "建筑维护"),
            )
        return (
            f"{TURN_UNIT}度预算基准：国库入{format_money(gk_in)}"
            f"（{gk_income_names}；建筑产出{format_money(_amt('国库', 'income', '建筑产出'))}）"
            f"出{format_money(gk_out)}"
            f"（{gk_expense_names}；军饷"
            f"{format_money(_amt('国库', 'expense', '各军军饷') + _amt('国库', 'expense', '边饷hub'))}+"
            f"建筑维护{format_money(_amt('国库', 'expense', '建筑维护'))}）"
            f"净{format_money_delta(gk_in - gk_out)}；"
            f"内库入{format_money(nk_in)}"
            f"出{format_money(nk_out)}"
            f"（内廷维护{format_money(_amt('内库', 'expense', '建筑维护'))}）"
            f"净{format_money_delta(nk_in - nk_out)}。"
        )

    def treasury_report(self, state: GameState, limit: int = 6) -> str:
        account_rows = self.conn.execute(
            "SELECT account, balance FROM economy_accounts ORDER BY account DESC"
        ).fetchall()
        if not account_rows:
            account_text = f"国库{format_money(state.metrics['国库'])}，内库{format_money(state.metrics['内库'])}"
        else:
            account_text = "，".join(f"{row['account']}{format_money(int(row['balance']))}" for row in account_rows)

        period_rows = self.conn.execute(
            """
            SELECT account,
                   SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS income,
                   SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS expense
            FROM economy_ledger
            WHERE turn = ?
            GROUP BY account
            ORDER BY account DESC
            """,
            (state.turn,),
        ).fetchall()
        period_text = "；".join(
            f"{row['account']}入{format_money(int(row['income'] or 0))}出{format_money(int(row['expense'] or 0))}"
            for row in period_rows
        )
        if not period_text:
            period_text = f"本{TURN_UNIT}尚无新账"

        ledger_rows = self.conn.execute(
            """
            SELECT year, period, account, delta, category, reason, actor
            FROM economy_ledger
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        recent = []
        for row in reversed(ledger_rows):
            delta = int(row["delta"])
            sign = "+" if delta > 0 else ""
            recent.append(
                f"{period_label(int(row['year']), int(row['period']))} {row['account']}{sign}{format_money(delta)} {row['category']}：{row['reason']}"
            )
        recent_text = "；".join(recent) if recent else "未见流水"
        budget = self.treasury_budget_summary(state)
        return f"{budget}账面：{account_text}。本{TURN_UNIT}收支：{period_text}。近账：{recent_text}。"

    def faction_satisfaction(self, faction: str) -> int:
        row = self.conn.execute("SELECT satisfaction FROM factions WHERE name = ?", (faction,)).fetchone()
        return int(row["satisfaction"]) if row else 50

    def faction_leverage(self, faction: str) -> int:
        row = self.conn.execute("SELECT leverage FROM factions WHERE name = ?", (faction,)).fetchone()
        return int(row["leverage"]) if row else 50

    def faction_report(self) -> str:
        rows = self.conn.execute(
            "SELECT name, satisfaction, leverage, agenda FROM factions ORDER BY name"
        ).fetchall()
        if not rows:
            return "派系未建档。"
        return "；".join(
            f"{row['name']}满意{row['satisfaction']}、势力{row['leverage']}，所求：{row['agenda']}"
            for row in rows
        )

    def class_rows(self, region_id: str = "") -> List[sqlite3.Row]:
        """region_id="" 取全国汇总行；其它取该省切片。"""
        return self.conn.execute(
            "SELECT name, region_id, population, satisfaction, leverage, agenda "
            "FROM classes WHERE region_id = ? ORDER BY name",
            (region_id,),
        ).fetchall()

    def class_report(self) -> str:
        """全国汇总 + 各省紧张切片（sat<=30 且 lev>=60）。"""
        national = self.class_rows("")
        if not national:
            return "阶级未建档。"
        head = "；".join(
            f"{row['name']}满意{row['satisfaction']}、势力{row['leverage']}（{row['agenda']}）"
            for row in national
        )
        hot = self.conn.execute(
            """
            SELECT c.name, c.region_id, c.satisfaction, c.leverage, r.name AS region_name
            FROM classes c
            LEFT JOIN regions r ON r.id = c.region_id
            WHERE c.region_id <> '' AND c.satisfaction <= 30 AND c.leverage >= 60
            ORDER BY c.satisfaction ASC, c.leverage DESC
            """
        ).fetchall()
        if not hot:
            return f"阶级总览：{head}。各省阶级暂无高压预警。"
        warn = "；".join(
            f"{row['region_name'] or row['region_id']} {row['name']}满意{row['satisfaction']}/势力{row['leverage']}"
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
            row = self.conn.execute(
                "SELECT satisfaction, leverage FROM classes WHERE name = ? AND region_id = ?",
                (name.strip(), region_id.strip()),
            ).fetchone()
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
            self.conn.execute(
                "UPDATE classes SET satisfaction = ?, leverage = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE name = ? AND region_id = ?",
                (sat, lev, name.strip(), region_id.strip()),
            )
        if commit:
            self.conn.commit()
        return rejected

    def power_rows(self, exclude_self: bool = False) -> List[sqlite3.Row]:
        where = "WHERE id != 'ming'" if exclude_self else ""
        return self.conn.execute(
            f"""
            SELECT *
            FROM powers
            {where}
            ORDER BY CASE id
                WHEN 'ming' THEN 0
                WHEN 'houjin' THEN 1
                WHEN 'mongol' THEN 2
                WHEN 'korea' THEN 3
                WHEN 'japan' THEN 4
                WHEN 'dutch' THEN 5
                WHEN 'bandits' THEN 6
                ELSE 9
            END, name
            """
        ).fetchall()

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

    def power_report(self, exclude_self: bool = True) -> str:
        rows = self.power_rows(exclude_self=exclude_self)
        if not rows:
            return "势力未建档。"
        return "；".join(
            f"{row['name']}（{row['leader']}）：{row['stance']}，威望{row['leverage']}、"
            f"实力{row['military_strength']}、经济{row['supply']}，"
            f"{row['status']}；近动：{row['last_action'] or '尚无新动'}"
            for row in rows
        )

    def apply_power_deltas(
        self,
        state: GameState,
        updates: Dict[str, Dict[str, object]],
        commit: bool = True,
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
            row = self.conn.execute("SELECT * FROM powers WHERE id = ?", (power_id,)).fetchone()
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
                if field in ("reason", "last_action"):
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
                stored_new: object = new_value
                log_delta: int | None = actual_delta
                self.conn.execute(
                    f"UPDATE powers SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (stored_new, power_id),
                )
                self.conn.execute(
                    """
                    INSERT INTO power_logs
                    (turn, year, period, power_id, field, old_value, new_value, delta, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.turn,
                        state.year,
                        state.period,
                        power_id,
                        field,
                        str(old_value),
                        str(stored_new),
                        log_delta,
                        reason,
                    ),
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
        row = self.conn.execute("SELECT * FROM powers WHERE id = ?", (power_id,)).fetchone()
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
        self.conn.execute(
            """
            UPDATE powers
            SET name=?, aliases=?, status=?, last_action=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (new_name, new_aliases, new_status, new_last_action, power_id),
        )
        self.conn.execute(
            """
            INSERT INTO power_name_logs
            (turn, year, period, power_id, old_name, new_name, old_aliases, new_aliases, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (state.turn, state.year, state.period, power_id, old_name, new_name, old_aliases, new_aliases, reason[:200]),
        )
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
        rows = self.conn.execute(
            """
            SELECT pl.*, p.name AS power_name
            FROM power_logs pl
            JOIN powers p ON p.id = pl.power_id
            WHERE pl.turn = ?
            ORDER BY pl.id
            LIMIT ?
            """,
            (turn, limit),
        ).fetchall()
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

    def region_rows(self, limit: int | None = None, danger_order: bool = False) -> List[sqlite3.Row]:
        order = (
            "(unrest + military_pressure + gentry_resistance + (100 - public_support)) DESC, name"
            if danger_order
            else "kind DESC, name"
        )
        sql = f"""
            SELECT *
            FROM regions
            ORDER BY {order}
        """
        params: Tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self.conn.execute(sql, params).fetchall()

    def region_payload(self, limit: int | None = None, danger_order: bool = False) -> List[Dict[str, object]]:
        payload: List[Dict[str, object]] = []
        for row in self.region_rows(limit=limit, danger_order=danger_order):
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
        row = self.conn.execute(
            "SELECT name FROM powers WHERE id = ?", (str(power_id),)
        ).fetchone()
        return str(row["name"]) if row else str(power_id)

    def region_report(self, limit: int = 5) -> str:
        rows = self.region_rows(limit=limit, danger_order=True)
        if not rows:
            return "地区尚未建档。"
        total_tax = self.conn.execute("SELECT SUM(tax_per_turn) AS total FROM regions").fetchone()
        total_tax_value = int(total_tax["total"] or 0)
        parts = []
        for row in rows:
            held = ""
            if str(row["controlled_by"]) != "ming":
                held = f"【已为{self.power_display_name(row['controlled_by'])}所据】"
            defense = f"、城防炮{int(row['cannon'])}门" if int(row["cannon"] or 0) > 0 else ""
            parts.append(
                f"{row['name']}{held}：民心{row['public_support']}、动乱{row['unrest']}、"
                f"粮食{row['grain_security']}万石、税{format_money(monthly_amount(int(row['tax_per_turn'])))}/{TURN_UNIT}{defense}，{row['status']}"
            )
        return f"地区警讯：{'；'.join(parts)}。两京十三省账面{TURN_UNIT}税合计{format_money(monthly_amount(total_tax_value))}。"

    def region_detail(self, raw_name: str) -> str:
        region_id = match_region_id_from_text(raw_name, self.content.regions)
        if region_id is None:
            raise ValueError(f"未找到地区：{raw_name}")
        row = self.conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
        if row is None:
            raise ValueError(f"地区未入库：{raw_name}")
        held = ""
        if str(row["controlled_by"]) != "ming":
            held = f"，控制权：已为{self.power_display_name(row['controlled_by'])}所据（非大明辖治）"
        return (
            f"{row['name']}（{row['kind']}）{held}：人口{row['population']}万人，"
            f"民心{row['public_support']}，动乱{row['unrest']}，粮食{row['grain_security']}万石，"
            f"田亩{row['registered_land']}万亩，隐田{row['hidden_land']}万亩，"
            f"账面税收{format_money(monthly_amount(int(row['tax_per_turn'])))}/{TURN_UNIT}，"
            f"士绅阻力{row['gentry_resistance']}，军事压力{row['military_pressure']}，"
            f"城市等级{int(row['city_level'])}（城防炮上限{int(row['city_level']) * 8}门），城防大炮{int(row['cannon'])}门。"
            f"天灾：{row['natural_disaster']}；人祸：{row['human_disaster']}；状态：{row['status']}"
        )

    def turn_region_summary(self, turn: int, limit: int = 10) -> str:
        rows = self.conn.execute(
            """
            SELECT rl.*, r.name AS region_name
            FROM region_logs rl
            JOIN regions r ON r.id = rl.region_id
            WHERE rl.turn = ?
            ORDER BY rl.id
            LIMIT ?
            """,
            (turn, limit),
        ).fetchall()
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
    ) -> List[Dict[str, object]]:
        changes: List[Dict[str, object]] = []
        for region_id, raw_changes in region_deltas.items():
            row = self.conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
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
                if field == "reason":
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
                            self.conn.execute(
                                """
                                INSERT INTO region_logs
                                (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (state.turn, state.year, state.period, region_id,
                                 field, str(old_value), str(new_value), 0,
                                 _clamp_reason, event.id, edict_id, actor),
                            )
                            changes.append({
                                "region": row["name"], "field": field,
                                "label": REGION_FIELD_LABELS.get(field, field),
                                "old": old_value, "new": new_value,
                                "delta": 0, "reason": _clamp_reason, "clamped": True,
                            })
                        continue
                    self.conn.execute(
                        """
                        INSERT INTO region_logs
                        (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (state.turn, state.year, state.period, region_id,
                         field, str(old_value), str(new_value), actual_delta,
                         reason, event.id, edict_id, actor),
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
                    fiscal: dict = json.loads(str(row["fiscal"] or "{}"))
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
                    fiscal[field] = new_value
                    self.conn.execute(
                        "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(fiscal, ensure_ascii=False), region_id),
                    )
                    self.conn.execute(
                        """
                        INSERT INTO region_logs
                        (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (state.turn, state.year, state.period, region_id,
                         field, str(old_value), str(new_value), actual_delta,
                         reason, event.id, edict_id, actor),
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
                            or self.conn.execute(
                                "SELECT 1 FROM powers WHERE id = ? LIMIT 1",
                                (text_value,),
                            ).fetchone() is None
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
                    stored_new = text_value
                    log_delta = None
                self.conn.execute(
                    f"UPDATE regions SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (stored_new, region_id),
                )
                self.conn.execute(
                    """
                    INSERT INTO region_logs
                    (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.turn, state.year, state.period, region_id,
                        field, str(old_value), str(stored_new), log_delta,
                        reason, event.id, edict_id, actor,
                    ),
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
                    extra = self._apply_on_restore(state, region_id, event, edict_id, actor, reason)
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
    ) -> List[Dict[str, object]]:
        """收复瞬间用 region.on_restore 覆盖主字段，记 region_logs。"""
        region_def = self.content.regions.get(region_id)
        if region_def is None or not region_def.on_restore:
            return []
        preset = region_def.on_restore
        row = self.conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
        if row is None:
            return []
        all_direct = REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + REGION_TEXT_FIELDS
        out: List[Dict[str, object]] = []
        for raw_field, value in preset.items():
            if raw_field == "fiscal":
                if not isinstance(value, dict):
                    continue
                fiscal = json.loads(str(row["fiscal"] or "{}"))
                for sub_field, sub_val in value.items():
                    if sub_field not in FISCAL_SCORE_FIELDS:
                        continue
                    old_sub = fiscal.get(sub_field, 0)
                    new_sub = int(sub_val)
                    if int(old_sub) == new_sub:
                        continue
                    fiscal[sub_field] = new_sub
                    self.conn.execute(
                        "INSERT INTO region_logs (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (state.turn, state.year, state.period, region_id,
                         sub_field, str(old_sub), str(new_sub), new_sub - int(old_sub),
                         f"收复重置：{reason}", event.id, edict_id, actor),
                    )
                    out.append({
                        "region": row["name"], "field": sub_field,
                        "label": REGION_FIELD_LABELS.get(sub_field, sub_field),
                        "old": old_sub, "new": new_sub,
                        "delta": new_sub - int(old_sub), "reason": f"收复重置：{reason}",
                    })
                self.conn.execute(
                    "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(fiscal, ensure_ascii=False), region_id),
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
            self.conn.execute(
                f"UPDATE regions SET {raw_field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_val, region_id),
            )
            log_delta = (int(new_val) - int(old_val)) if raw_field in (REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS) else None
            self.conn.execute(
                "INSERT INTO region_logs (turn, year, period, region_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (state.turn, state.year, state.period, region_id,
                 raw_field, str(old_val), str(new_val), log_delta,
                 f"收复重置：{reason}", event.id, edict_id, actor),
            )
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
        rows = sorted(self.conn.execute("SELECT * FROM armies").fetchall(), key=_danger_key)
        return rows[:limit] if limit is not None else rows

    def army_payload(self, limit: int | None = None, danger_order: bool = False) -> List[Dict[str, object]]:
        payload: List[Dict[str, object]] = []
        for row in self.army_rows(limit=limit, danger_order=danger_order):
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
                    "army_needed": self._army_pay(row),
                    "supply": int(row["supply"]),
                    "morale": int(row["morale"]),
                    "training": int(row["training"]),
                    "equipment": int(row["equipment"]),
                    "arrears": float(row["arrears"]),
                    "mobility": int(row["mobility"]),
                    "loyalty": int(row["loyalty"]),
                    "firearm_equipment": int(row["firearm_equipment"]),
                    "cannon_equipment": int(row["cannon_equipment"]),
                    "status": row["status"],
                    "owner_power": row["owner_power"],
                }
            )
        return payload

    def army_report(self, limit: int = 5) -> str:
        rows = self.army_rows(limit=limit, danger_order=True)
        if not rows:
            return "军队尚未建档。"
        total_manpower = self.conn.execute("SELECT SUM(manpower) AS total FROM armies").fetchone()
        # #173：月饷总额按引擎实扣应发 army_needed 之和（替退役 maintenance_per_turn 之和）。
        total_pay = sum(self._army_pay(r) for r in self.conn.execute("SELECT * FROM armies").fetchall())
        parts = []
        for row in rows:
            pay = self._army_pay(row)
            arr_text = _army_arrears_report_text(row, pay)
            parts.append(
                f"{row['name']}：驻{row['station']}，兵{row['manpower']}，"
                f"饷{format_money(monthly_amount(pay))} /{TURN_UNIT}，"
                f"{_qualitative_army_stat('supply', row['supply'])}、"
                f"{_qualitative_army_stat('morale', row['morale'])}、"
                f"火器{row['firearm_equipment']}、炮{row['cannon_equipment']}、{arr_text}，{row['status']}"
            )
        return (
            f"军队警讯：{'；'.join(parts)}。"
            f"建档兵力合计{int(total_manpower['total'] or 0)}人，{TURN_UNIT}应发军饷合计{format_money(monthly_amount(total_pay))}。"
        )

    def army_detail(self, raw_name: str) -> str:
        # 先按 DB id/name 直查（含动态 new_armies 建出的、不在静态 content.armies 的军队），
        # 再退回静态别名模糊匹配（如「关宁军」→ guanning）。SELECT * 渲染含火器/随军大炮，
        # 故新军详情 read 也闭合（CMR codexB/C：army render 收敛到此单一真源，杀 read 侧 whack-a-mole）。
        row = self.conn.execute(
            "SELECT * FROM armies WHERE id = ? OR name = ?", (raw_name, raw_name)
        ).fetchone()
        if row is None:
            army_id = match_army_id_from_text(raw_name, self.content.armies)
            if army_id is not None:
                row = self.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
        if row is None:
            raise ValueError(f"未找到军队：{raw_name}")
        pay = self._army_pay(row)  # #173：月饷取引擎实扣应发
        arr_text = _army_arrears_report_text(row, pay)
        return (
            f"{row['name']}：驻扎地{row['station']}，统帅{row['commander']}，"
            f"兵种{row['troop_type']}，人数{row['manpower']}人，"
            f"月应发军饷{format_money(monthly_amount(pay))} /{TURN_UNIT}，"
            f"{_qualitative_army_stat('supply', row['supply'])}，"
            f"{_qualitative_army_stat('morale', row['morale'])}，"
            f"{_qualitative_army_stat('training', row['training'])}，"
            f"{_qualitative_army_stat('equipment', row['equipment'])}，"
            f"火器{row['firearm_equipment']}，随军大炮{row['cannon_equipment']}门，"
            f"{arr_text}，{_qualitative_army_stat('mobility', row['mobility'])}，"
            f"{_qualitative_army_stat('loyalty', row['loyalty'])}。"
            f"状态：{row['status']}"
        )

    def army_roster(self, filter_names: Optional[List[str]] = None, index_only: bool = False) -> str:
        """全军名册。filter_names 非空则只返回指定军队；index_only=True 只返回军名+欠饷+状态索引。"""
        rows = self.conn.execute(
            "SELECT * FROM armies ORDER BY owner_power='ming' DESC, theater, name"
        ).fetchall()
        if filter_names:
            rows = [r for r in rows if r["name"] in filter_names or r["id"] in filter_names]
        if index_only:
            # 军队超 30 时用索引：仅显示军名+欠饷+状态，完整信息由 query_army_roster tool 提供
            lines = []
            for row in rows:
                if str(row["owner_power"]) == "ming":
                    lines.append(f"{row['name']}：{_approx_wanliang(row['arrears'])}，{row['status']}")
            return (
                "【全军名册索引（涉及军队欠饷/补给/士气时先调 query_army_roster 查完整信息）】\n"
                + "\n".join(lines)
            ) if lines else ""
        if not rows:
            return ""
        own: List[str] = []
        other: List[str] = []
        for row in rows:
            # #173：月饷取引擎实扣应发 army_needed（替退役 maintenance_per_turn）。全按月度，不除 3。
            monthly_pay = self._army_pay(row)
            arrears_text = _army_arrears_report_text(row, monthly_pay)
            if str(row["owner_power"]) == "ming":
                # 列序见表头。兵力/月饷/欠饷为真钱；补给…忠诚以奏报定性呈现。
                own.append(
                    "|".join(str(x) for x in (
                        row["name"], row["station"], row["commander"], row["troop_type"],
                        row["manpower"], monthly_pay,
                        _qualitative_army_stat("supply", row["supply"]),
                        _qualitative_army_stat("morale", row["morale"]),
                        _qualitative_army_stat("training", row["training"]),
                        _qualitative_army_stat("equipment", row["equipment"]),
                        _qualitative_army_stat("mobility", row["mobility"]),
                        _qualitative_army_stat("loyalty", row["loyalty"]),
                        arrears_text, row["status"],
                        row["firearm_equipment"], row["cannon_equipment"],
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
            "大明各军（| 分隔，列序＝军名|驻地|统帅|兵种|兵力|月饷万两|补给|士气|训练|装备|机动|忠诚|欠饷奏报|状态|火器|随军大炮；补给…忠诚为定性奏报，火器为0-100，随军大炮为门数0-12）：",
            *own,
        ]
        if other:
            out.append("敌对/外藩军（可见情报，列序＝军名|势力|驻地|统帅|兵种|兵力|状态）：")
            out.extend(other)
        return "\n".join(out)

    def turn_army_summary(self, turn: int, limit: int = 10) -> str:
        rows = self.conn.execute(
            """
            SELECT al.*, a.name AS army_name
            FROM army_logs al
            JOIN armies a ON a.id = al.army_id
            WHERE al.turn = ?
            ORDER BY CASE
                       WHEN al.delta IS NULL THEN 0
                       WHEN al.delta != 0 THEN 0
                       ELSE 1
                     END, al.id
            LIMIT ?
            """,
            (turn, limit),
        ).fetchall()
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
                delta_text = str(int(delta_num)) if delta_num.is_integer() else f"{delta_num:g}"
                sign = "+" if delta_num > 0 else ""
                if row["field"] == "manpower":
                    parts.append(f"{row['army_name']}{label}{sign}{int(delta_num)}人（{row['reason']}）")
                else:
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
    ) -> List[Dict[str, object]]:
        changes: List[Dict[str, object]] = []
        for army_id, raw_changes in army_deltas.items():
            row = self.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
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
            if self.is_army_pay_source_cutover_enabled():
                self._apply_army_pay_source_delta(
                    state, event, edict_id, actor, row, raw_changes, reason, changes
                )
                row = self.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
            for raw_field, value in raw_changes.items():
                field = ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field == "reason":
                    continue
                if self.is_army_pay_source_cutover_enabled() and field in _ARMY_PAY_SOURCE_DELTA_FIELDS:
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
                current_row = self.conn.execute(
                    "SELECT * FROM armies WHERE id = ?", (army_id,)
                ).fetchone()
                if current_row is not None:
                    row = current_row
                old_value = row[field]
                if field == "arrears":
                    if self.is_army_pay_source_cutover_enabled():
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
                        self.conn.execute(
                            """
                            UPDATE armies
                            SET province_pay_arrears = ?, central_pay_arrears = ?,
                                arrears = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (new_province, new_central, new_value, army_id),
                        )
                        self.conn.execute(
                            """
                            INSERT INTO army_logs
                            (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                            VALUES (?, ?, ?, ?, 'arrears', ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                state.turn, state.year, state.period, army_id,
                                str(old_value), str(new_value), delta,
                                reason, event.id, edict_id, actor,
                            ),
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
                    # arrears 单位=累计欠饷万两，无上限，按需累加。
                    # 正常情况由 flows 唯一变更；此处兜底允许 extractor 在战损/裁军等
                    # 非现金原因下写入（提示词已禁，但保留兜底以防 LLM 越界不至于截断）。
                    delta = int(value)
                    new_value = max(0, int(old_value) + delta)
                    actual_delta = new_value - int(old_value)
                    if actual_delta == 0:
                        continue
                    stored_new: object = new_value
                    log_delta: int | None = actual_delta
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
                    delta = int(value)
                    # 遗产百分比修正：该军该字段若有 active 遗产修正符，先放大/缩小 delta
                    net_pct = int(((self.legacy_modifiers(state).get("armies") or {})
                                   .get(army_id) or {}).get(field, 0) or 0)
                    if net_pct:
                        delta = self.apply_legacy_pct(delta, net_pct)
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
                    if (
                        self.is_army_pay_source_cutover_enabled()
                        and new_value == 0
                        and str(row["owner_power"]) == "ming"
                        and float(row["arrears"] or 0) > 1e-9
                    ):
                        old_arrears = float(row["arrears"] or 0)
                        old_source = str(row["pay_source_region"] or "")
                        self.conn.execute(
                            """
                            INSERT INTO army_logs
                            (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                            VALUES (?, ?, ?, ?, 'arrears', ?, '0.0', ?, ?, ?, ?, ?)
                            """,
                            (
                                state.turn, state.year, state.period, army_id,
                                str(old_arrears), -old_arrears,
                                f"兵力归零核销：{reason}",
                                event.id, edict_id, actor,
                            ),
                        )
                        self.conn.execute(
                            """
                            UPDATE armies
                            SET province_pay_arrears = 0,
                                central_pay_arrears = 0,
                                arrears = 0,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (army_id,),
                        )
                        self._reconcile_army_pay_source_region_container(old_source)
                        self._reconcile_central_army_pay_arrears_container()
                    if actual_delta == 0:
                        # #44：请求非 0 但 clamp 后无净变化（如减兵超过现有兵力→clamp 到 0）留一条
                        # delta=0 army_log（参照 region cannon delta=0 留痕，#14 不静默吞）；真 no-op
                        # （delta==0）无须留痕避噪。
                        if delta != 0:
                            self.conn.execute(
                                """
                                INSERT INTO army_logs
                                (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                                VALUES (?, ?, ?, ?, 'manpower', ?, ?, 0, ?, ?, ?, ?)
                                """,
                                (state.turn, state.year, state.period, army_id,
                                 str(old_value), str(new_value),
                                 f"{reason}（请求 {delta:+d} 经 clamp 后无净变化）", event.id, edict_id, actor),
                            )
                        continue
                    stored_new = new_value
                    log_delta = actual_delta
                elif field in ARMY_TEXT_FIELDS:
                    text_value = str(value).strip()[:160]
                    if not text_value or text_value == str(old_value):
                        continue
                    stored_new = text_value
                    log_delta = None
                else:
                    # field 已过 _ARMY_VALID_SET 校验，能落到此处=合法字段未被任一
                    # 分支处理=代码漏接(往 ARMY_*_FIELDS 加了字段却忘了 dispatch)。
                    # 按 ADR 0008 决定 1：代码 bug 响亮上抛触发回滚，不静默丢一个合法 delta。
                    raise RuntimeError(f"army_delta 合法字段 '{field}' 无落库分支（代码漏接）")
                self.conn.execute(
                    f"UPDATE armies SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (stored_new, army_id),
                )
                if field == "manpower" and self.is_army_pay_source_cutover_enabled():
                    self._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                self.conn.execute(
                    """
                    INSERT INTO army_logs
                    (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.turn,
                        state.year,
                        state.period,
                        army_id,
                        field,
                        str(old_value),
                        str(stored_new),
                        log_delta,
                        reason,
                        event.id,
                        edict_id,
                        actor,
                    ),
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
        return changes

    def create_armies_from_extraction(
        self,
        state: GameState,
        new_armies: List[Dict[str, object]],
        actor: str = "档房",
        commit: bool = True,
    ) -> List[Dict[str, object]]:
        """据 extractor 输出建新军队。同 id/name 已存在 → 把 manpower 当扩军增量。owner_power 必须是已知 power。"""
        valid_powers = {r["id"] for r in self.conn.execute("SELECT id FROM powers").fetchall()}
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
            existing = self.conn.execute(
                "SELECT id, name FROM armies WHERE id = ? OR name = ?", (aid, name)
            ).fetchone()
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
                self.apply_army_deltas(
                    state,
                    pseudo_event,
                    None,
                    actor,
                    {existing["id"]: {"manpower": delta, "reason": reason}},
                    commit=False,
                )
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
            if self.is_army_pay_source_cutover_enabled() and initial_arrears > 0:
                created.append({
                    "id": aid, "rejected": True, "category": "invalid_enum",
                    "reason": (
                        f"new_armies '{aid}' 新军初始欠饷必须为 0；"
                        "外生加欠须走 army_delta.arrears 正值"
                    ),
                    "item": raw,
                })
                continue
            pay_source_region = ""
            province_pay_share = central_pay_share = 0.0
            province_pay_arrears = central_pay_arrears = 0.0
            is_tusi = self_funded_pay = False
            stored_arrears = float(initial_arrears)
            if self.is_army_pay_source_cutover_enabled():
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
                except (TypeError, ValueError) as exc:
                    created.append({
                        "id": aid, "rejected": True, "category": "invalid_enum",
                        "reason": f"new_armies '{aid}' 饷源字段非法：{exc}",
                        "item": raw,
                    })
                    continue
            commander = str(item.get("commander") or "")
            row = (
                aid,
                name,
                str(item.get("station") or ""),
                str(item.get("theater") or ""),
                commander,
                str(item.get("controller") or commander),
                str(item.get("troop_type") or ""),
                max(0, manpower),
                _score("supply"),
                _score("morale"),
                _score("training"),
                _score("equipment"),
                stored_arrears,
                province_pay_arrears,
                central_pay_arrears,
                pay_source_region,
                province_pay_share,
                central_pay_share,
                1 if is_tusi else 0,
                1 if self_funded_pay else 0,
                _score("mobility"),
                _score("loyalty"),
                _score("firearm_equipment", 0),
                _cannon(),  # 随军大炮=门数，clamp 0-12，非 int 兜底 0
                # #44 新军名义月饷率：缺省/None/0/负/非数 一律落锚点 1.5（salary_rate<=0=免费军=白嫖，禁；
                # 游戏无自给/屯田军概念）。原 `or 1.5` 漏负值（-1→免费军），改健壮 helper（cmr r3 codex）。
                _coerce_new_salary_rate(item.get("salary_rate")),
                str(item.get("status") or "新立"),
                owner,
            )
            try:
                self.conn.execute(
                    """
                    INSERT INTO armies
                    (id, name, station, theater, commander, controller, troop_type, manpower,
                     supply, morale, training, equipment, arrears,
                     province_pay_arrears, central_pay_arrears, pay_source_region,
                     province_pay_share, central_pay_share, is_tusi, self_funded_pay,
                     mobility, loyalty, firearm_equipment, cannon_equipment, salary_rate, status, owner_power)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"new_armies INSERT 失败 '{aid}'：{exc}") from exc
            self._reconcile_army_pay_source_region_container(pay_source_region)
            self._reconcile_central_army_pay_arrears_container()
            self.assert_army_pay_source_container_conservation()
            reason = str(item.get("reason") or item.get("status") or "新立军队")[:80]
            self.conn.execute(
                """
                INSERT INTO army_logs
                (turn, year, period, army_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                VALUES (?, ?, ?, ?, 'created', '', ?, ?, ?, 'season', NULL, ?)
                """,
                (state.turn, state.year, state.period, aid, str(manpower), manpower, reason, actor),
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
    ) -> str:
        """运行时新立建筑（玩家诏书）。category / output_metric 走白名单硬校验，违规 ValueError。"""
        if category not in BUILDING_CATEGORIES:
            raise ValueError(f"建筑 category 非法 '{category}'，白名单 {BUILDING_CATEGORIES}")
        if output_metric not in BUILDING_OUTPUT_METRICS:
            raise ValueError(f"建筑 output_metric 非法 '{output_metric}'，白名单 {BUILDING_OUTPUT_METRICS}")
        if self.conn.execute("SELECT 1 FROM regions WHERE id = ?", (region_id,)).fetchone() is None:
            raise ValueError(f"建筑 region_id 引用未入库地区 '{region_id}'")
        base = re.sub(r"[^a-z0-9]+", "", (region_id or "rgn").lower()) or "rgn"
        seq = self.conn.execute(
            "SELECT COUNT(*) FROM buildings WHERE region_id = ?", (region_id,)
        ).fetchone()[0]
        building_id = f"{base}_b{int(seq) + 1}"
        while self.conn.execute("SELECT 1 FROM buildings WHERE id = ?", (building_id,)).fetchone():
            seq += 1
            building_id = f"{base}_b{int(seq) + 1}"
        self.conn.execute(
            """
            INSERT INTO buildings
            (id, region_id, name, category, level, condition, maintenance, risk,
             output_metric, output_amount, status, origin, created_turn)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                building_id,
                region_id,
                name.strip()[:60] or "无名建筑",
                category,
                max(1, min(5, int(level))),
                max(0, min(100, int(condition))),
                max(0, int(maintenance)),
                max(0, min(100, int(risk))),
                output_metric,
                max(0, int(output_amount)),
                status.strip()[:160] or "新立，尚在筹建。",
                origin,
                state.turn,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO building_logs
            (turn, year, period, building_id, field, old_value, new_value, delta, reason, actor)
            VALUES (?, ?, ?, ?, 'create', '', ?, NULL, ?, '档房')
            """,
            (state.turn, state.year, state.period, building_id, name.strip()[:60], "诏书新立建筑"),
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
    ) -> bool:
        """拆除/废止建筑（issue 失败或撤销结案）。返回是否真删了一行。"""
        row = self.conn.execute("SELECT name FROM buildings WHERE id = ?", (building_id,)).fetchone()
        if row is None:
            return False
        self.conn.execute(
            """
            INSERT INTO building_logs
            (turn, year, period, building_id, field, old_value, new_value, delta, reason, actor)
            VALUES (?, ?, ?, ?, 'remove', ?, '', NULL, ?, '档房')
            """,
            (state.turn, state.year, state.period, building_id,
             str(row["name"]), (reason or "建筑废止").strip()[:80]),
        )
        self.conn.execute("DELETE FROM buildings WHERE id = ?", (building_id,))
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
    ) -> List[Dict[str, object]]:
        """改既有建筑。仿 apply_army_deltas。供 issue effect 落地复用。"""
        changes: List[Dict[str, object]] = []
        valid_fields = set(BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS + BUILDING_TEXT_FIELDS)
        for building_id, raw_changes in building_deltas.items():
            row = self.conn.execute("SELECT * FROM buildings WHERE id = ?", (building_id,)).fetchone()
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
                self.conn.execute(
                    f"UPDATE buildings SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (stored_new, building_id),
                )
                self.conn.execute(
                    """
                    INSERT INTO building_logs
                    (turn, year, period, building_id, field, old_value, new_value, delta, reason, event_id, edict_id, actor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.turn, state.year, state.period, building_id, field,
                        str(old_value), str(stored_new), log_delta, reason,
                        event.id, edict_id, actor,
                    ),
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
        return changes

    def buildings_report(self, region_id: str = "") -> str:
        """月末奏报 / web 用建筑盘面摘要。region_id 为空取全国。"""
        if region_id:
            rows = self.conn.execute(
                "SELECT * FROM buildings WHERE region_id = ? ORDER BY category, name", (region_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM buildings ORDER BY region_id, category, name"
            ).fetchall()
        if not rows:
            return "（暂无建筑在册）"
        lines: List[str] = []
        for r in rows:
            metric = str(r["output_metric"])
            if metric:
                out = f"产出{metric}{r['output_amount']}"
            else:
                out = "无结算产出"
            lines.append(
                f"{r['name']}（{r['category']}·{r['region_id']}）等级{r['level']}，"
                f"完好{r['condition']}，维护{r['maintenance']}{MONEY_UNIT}/{TURN_UNIT}，"
                f"风险{r['risk']}，{out}。{r['status']}"
            )
        return "\n".join(lines)

    def building_payload(self, region_id: str = "") -> List[Dict[str, object]]:
        """建筑结构化清单，供 web。region_id 为空取全国。"""
        if region_id:
            rows = self.conn.execute(
                "SELECT * FROM buildings WHERE region_id = ? ORDER BY category, name", (region_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM buildings ORDER BY region_id, category, name"
            ).fetchall()
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

    def building_detail(self, name_or_id: str) -> str:
        key = (name_or_id or "").strip()
        row = self.conn.execute(
            "SELECT * FROM buildings WHERE id = ? OR name = ?", (key, key)
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM buildings WHERE name LIKE ?", (f"%{key}%",)
            ).fetchone()
        if row is None:
            raise ValueError(f"未找到建筑 '{name_or_id}'")
        metric = str(row["output_metric"])
        out = f"产出{metric}{row['output_amount']}/{TURN_UNIT}" if metric else "无结算产出"
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
            row = self.conn.execute(
                "SELECT satisfaction, leverage FROM factions WHERE name = ?", (faction,)
            ).fetchone()
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
                self.conn.execute(
                    "UPDATE factions SET satisfaction = ?, leverage_offset = leverage_offset + ? "
                    "WHERE name = ?",
                    (new_sat, lev_d, faction),
                )
                # 立即令 leverage 体现 offset 变化（含本次增量）；reconcile 后确认同值。
                self.recompute_faction_leverage(faction)
            else:
                # 非白名单：维持原样直写 leverage 列（reconcile 不碰非白名单）。
                new_lev = max(0, min(100, int(row["leverage"]) + lev_d))
                self.conn.execute(
                    "UPDATE factions SET satisfaction = ?, leverage = ? WHERE name = ?",
                    (new_sat, new_lev, faction),
                )
        if commit:
            self.conn.commit()
        return rejected

    def turn_economy_summary(self, turn: int) -> str:
        rows = self.conn.execute(
            """
            SELECT account,
                   SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS income,
                   SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS expense,
                   SUM(delta) AS net
            FROM economy_ledger
            WHERE turn = ? AND category <> '期初'
            GROUP BY account
            ORDER BY account DESC
            """,
            (turn,),
        ).fetchall()
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
        rows = self.conn.execute(
            """
            SELECT turn, year, period, delta, balance_after, category, reason, actor
            FROM economy_ledger
            WHERE account = ? AND category <> '期初'
            ORDER BY id DESC
            LIMIT ?
            """,
            (account, turns * 20),
        ).fetchall()
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
        # turn=0 是开局即位邸报（seed_opening_gazette 落库）；turn<0 才算未登基前。
        if previous_turn < 0:
            return f"登基伊始，尚无上{TURN_UNIT}回奏。"

        # 上回合奏报单独存在 turn_reports，直接取。
        report = self.get_turn_report(previous_turn)
        if report:
            return report
        if previous_turn == 0:
            return f"登基伊始，尚无上{TURN_UNIT}回奏。"

        logs = self.conn.execute(
            "SELECT message FROM turn_logs WHERE turn = ? ORDER BY id",
            (previous_turn,),
        ).fetchall()
        if not logs:
            return f"上{TURN_UNIT}未见正式记录。"

        lines = [
            f"上{TURN_UNIT}回顾：",
            f"钱粮：{self.turn_economy_summary(previous_turn)}",
            f"地区：{self.turn_region_summary(previous_turn)}",
            f"军队：{self.turn_army_summary(previous_turn)}",
            f"势力：{self.turn_power_summary(previous_turn)}",
        ]
        return "\n".join(lines)

    def record_log(self, state: GameState, message: str) -> None:
        self.conn.execute(
            "INSERT INTO turn_logs (turn, year, period, message) VALUES (?, ?, ?, ?)",
            (state.turn, state.year, state.period, message),
        )
        self.conn.commit()

    def append_chat_message(self, minister_name: str, turn: int, role: str, content: str) -> int:
        """召对聊天单条消息落库（chat_messages）。"""
        cur = self.conn.execute(
            "INSERT INTO chat_messages (minister_name, turn, role, content) VALUES (?, ?, ?, ?)",
            (minister_name, turn, role, content),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_chat_messages(self, message_ids: Iterable[int]) -> None:
        ids = [int(mid) for mid in message_ids if mid is not None]
        if not ids:
            return
        with self.conn:
            self.conn.executemany(
                "DELETE FROM chat_messages WHERE id = ?",
                [(mid,) for mid in ids],
            )

    def load_all_chat_history(self) -> Dict[str, List[Dict[str, str]]]:
        """读出全部召对记录，按大臣分组，供进程启动时恢复内存缓存。"""
        rows = self.conn.execute(
            "SELECT minister_name, role, content FROM chat_messages ORDER BY id"
        ).fetchall()
        history: Dict[str, List[Dict[str, str]]] = {}
        for row in rows:
            history.setdefault(row["minister_name"], []).append(
                {"role": row["role"], "content": row["content"]}
            )
        return history

    # ----- chat_turns（本回合召对撤回）-----

    _ROLLBACK_TABLE_PK = {
        "turn_directives": "id",
        "secret_orders": "id",
        "characters": "name",
        "character_offices": "character_name",
        "consort_traits": "name",
        # 动作闸门(ADR 0006)：召对暂存的结构化写动作。撤回召对须删本轮暂存,
        # 否则颁诏仍会落库,破坏 undo 保证(CMR P1)。
        "pending_actions": "id",
        # #9 R1 finding#4：leverage hook（set_character_status/set_character_office）会改 factions
        # .leverage(+offset)。chat office/dismiss 动作撤回须连 factions 一并还原，否则 characters
        # 被还原而 factions leverage 留脏。快照 SELECT * 含 leverage+offset，restore INSERT OR REPLACE
        # 全列覆盖、二者同还原。
        "factions": "name",
    }

    def _row_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def _json_dump_row(self, row: Dict[str, Any]) -> str:
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    def _json_load_row(self, raw: str) -> Dict[str, Any]:
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    def _table_exists(self, table: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _snapshot_table(self, table: str, pk: str) -> Dict[str, Dict[str, Any]]:
        rows = self.conn.execute(f"SELECT * FROM {table}").fetchall()
        return {str(row[pk]): self._row_dict(row) for row in rows}

    def capture_chat_rollback_snapshot(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """截取召对前后的可回滚业务表状态，用于撤回时做差异还原。"""
        return {
            table: self._snapshot_table(table, pk)
            for table, pk in self._ROLLBACK_TABLE_PK.items()
        }

    def create_chat_turn(
        self,
        state: GameState,
        minister_name: str,
        agno_session_id: str,
        agno_runs_before: int,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO chat_turns
                (minister_name, turn, year, period, agno_session_id, agno_runs_before)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                minister_name,
                int(state.turn),
                int(state.year),
                int(state.period),
                agno_session_id,
                max(0, int(agno_runs_before)),
            ),
        )
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
            "UPDATE chat_turns SET status = 'failed' WHERE id = ? AND status = 'active'",
            (int(chat_turn_id),),
        )
        self.conn.commit()

    def fail_chat_turn(self, chat_turn_id: int) -> None:
        """Mark an incomplete audience turn failed and remove its partial user-visible writes."""
        row = self.conn.execute(
            "SELECT * FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
        if row is None:
            return
        turn_row = self._row_dict(row)
        if turn_row["status"] != "active":
            self.conn.execute(
                "UPDATE chat_turns SET status = 'failed' WHERE id = ?",
                (int(chat_turn_id),),
            )
            self.conn.commit()
            return
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
        with self.conn:
            for item in items:
                table = str(item["target_table"])
                strategy = str(item["rollback_strategy"])
                target_id = str(item["target_id"])
                if strategy == "delete_inserted_row":
                    self._delete_row_in_tx(table, target_id)
                elif strategy in {"restore_row", "restore_deleted_row"}:
                    before_row = self._json_load_row(item["before_json"])
                    self._restore_row_in_tx(table, before_row)
                else:
                    raise ValueError(f"不支持的回滚策略：{strategy}")
            if message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                self.conn.execute(
                    f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
                    message_ids,
                )
            self.conn.execute(
                "UPDATE chat_turns SET status = 'failed' WHERE id = ?",
                (int(chat_turn_id),),
            )
            self._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )

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

    def agno_runs_length(self, session_id: str) -> int:
        if not session_id or not self._table_exists("agno_sessions"):
            return 0
        row = self.conn.execute(
            "SELECT runs FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return 0
        runs, _encoded_as_string = self._decode_agno_runs(row["runs"])
        return len(runs)

    def _decode_agno_runs(self, raw: Any) -> Tuple[List[Any], bool]:
        if raw in (None, ""):
            return [], False
        try:
            decoded = json.loads(raw)
            encoded_as_string = isinstance(decoded, str)
            if encoded_as_string:
                decoded = json.loads(decoded or "[]")
            return (decoded if isinstance(decoded, list) else []), encoded_as_string
        except (TypeError, ValueError):
            return [], False

    def _encode_agno_runs(self, runs: List[Any], encoded_as_string: bool) -> str:
        if encoded_as_string:
            return json.dumps(json.dumps(runs, ensure_ascii=False), ensure_ascii=False)
        return json.dumps(runs, ensure_ascii=False)

    def _truncate_agno_runs_in_tx(self, session_id: str, keep_count: int) -> None:
        if not session_id or not self._table_exists("agno_sessions"):
            return
        row = self.conn.execute(
            "SELECT runs FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return
        runs, encoded_as_string = self._decode_agno_runs(row["runs"])
        kept = runs[: max(0, int(keep_count))]
        self.conn.execute(
            "UPDATE agno_sessions SET runs = ?, updated_at = strftime('%s','now') WHERE session_id = ?",
            (self._encode_agno_runs(kept, encoded_as_string), session_id),
        )

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

    def is_global_last_active_chat_turn(self, chat_turn_id: int) -> bool:
        row = self.conn.execute(
            "SELECT id FROM chat_turns WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return bool(row and int(row["id"]) == int(chat_turn_id))

    def can_undo_last_chat_turn(self, minister_name: str, turn: int) -> bool:
        row = self.get_last_active_chat_turn(minister_name, turn)
        if row is None:
            return False
        if not row.get("user_message_id") or not row.get("minister_message_id"):
            return False
        return self.is_global_last_active_chat_turn(int(row["id"]))

    def retire_chat_turn_for_pending_action_retry(self, action_id: int) -> int:
        """Make the confirmation turn for a successfully retried action non-undoable.

        Manual retry happens after the original chat rollback diff was recorded. Keeping
        that chat turn active would let undo restore the pre-retry pending row while the
        retried durable write remains, so retire only the turn that marked this action
        failed. Chat messages stay persisted; only the undo affordance is removed.
        """
        rows = self.conn.execute(
            """
            SELECT i.chat_turn_id, i.after_json
            FROM chat_turn_rollback_items i
            JOIN chat_turns t ON t.id = i.chat_turn_id
            WHERE t.status = 'active'
              AND i.target_table = 'pending_actions'
              AND i.target_id = ?
            ORDER BY i.chat_turn_id DESC, i.id DESC
            """,
            (str(int(action_id)),),
        ).fetchall()
        retired_ids: List[int] = []
        for row in rows:
            after_row = self._json_load_row(row["after_json"] or "")
            if not isinstance(after_row, dict):
                continue
            if str(after_row.get("kind") or "") != "secret_order":
                continue
            if str(after_row.get("status") or "") not in {"pending", "failed"}:
                continue
            chat_turn_id = int(row["chat_turn_id"])
            if chat_turn_id in retired_ids:
                continue
            self.conn.execute(
                "UPDATE chat_turns SET status = 'failed' WHERE id = ? AND status = 'active'",
                (chat_turn_id,),
            )
            retired_ids.append(chat_turn_id)
        if retired_ids:
            if not bool(getattr(self.conn, "_commit_suspended", False)) and int(
                getattr(self.conn, "_atomic_depth", 0) or 0
            ) <= 0:
                self.conn.commit()
            return retired_ids[0]
        return 0

    def _restore_row_in_tx(self, table: str, row: Dict[str, Any]) -> None:
        if not row:
            return
        if table not in self._ROLLBACK_TABLE_PK:
            raise ValueError(f"不支持回滚表：{table}")
        columns = list(row.keys())
        placeholders = ",".join("?" for _ in columns)
        column_sql = ",".join(columns)
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    def _delete_row_in_tx(self, table: str, target_id: str) -> None:
        pk = self._ROLLBACK_TABLE_PK.get(table)
        if not pk:
            raise ValueError(f"不支持回滚表：{table}")
        self.conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (target_id,))

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
        # write_decree() 的 commit_pending_actions(kind_filter="directive") 可能在召对
        # diff 已记录之后才生成 turn_directives(status='draft')，因此那类行不会进入
        # rollback_items（召对期直接更新的 turn_directives 仍会被快照捕获并还原）。
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
            for item in items:
                table = str(item["target_table"])
                strategy = str(item["rollback_strategy"])
                target_id = str(item["target_id"])
                if strategy == "delete_inserted_row":
                    self._delete_row_in_tx(table, target_id)
                elif strategy in {"restore_row", "restore_deleted_row"}:
                    before_row = self._json_load_row(item["before_json"])
                    self._restore_row_in_tx(table, before_row)
                else:
                    raise ValueError(f"不支持的回滚策略：{strategy}")
            # 只精确删除本召对 commit 出来的 draft 行（保留同 actor 的无关 draft）。
            for draft_id in draft_ids_to_delete:
                self.conn.execute(
                    "DELETE FROM turn_directives WHERE id=? AND status='draft'",
                    (int(draft_id),),
                )
            if message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                self.conn.execute(
                    f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
                    message_ids,
                )
            self.conn.execute(
                """
                UPDATE chat_turns
                SET status = 'undone', undone_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(chat_turn_id),),
            )
            self._truncate_agno_runs_in_tx(
                str(turn_row.get("agno_session_id") or ""),
                int(turn_row.get("agno_runs_before") or 0),
            )
        # P1-2：报告本召对删除了哪些 committed draft（write_decree 已 commit 的对话草案行）。
        # 上层据此让已生成的诏书正文（last_decree）失效——否则若另有 draft 残留，玩家仍能
        # 原样颁出含被撤回指令的陈旧诏书。无删除则为空，普通撤回不触发上层清稿。
        turn_row["deleted_committed_draft_ids"] = list(draft_ids_to_delete)
        return turn_row

    # ----- event memories（渐进式记忆：摘要卡 + 来源摘录） -----

    def upsert_event_memory(
        self,
        state: GameState,
        subject_type: str,
        subject_id: str,
        event_type: str,
        title: str,
        cause: str = "",
        process: str = "",
        outcome: str = "",
        sentiment: str = "neutral",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        source_kind: str = "system",
        source_id: str = "",
        expires_turn: Optional[int] = None,
    ) -> int:
        """写入/更新一张事件记忆摘要卡，按主体+类型+来源去重。"""
        subject_type = (subject_type or "").strip()
        subject_id = (subject_id or "").strip()
        event_type = (event_type or "").strip()
        source_kind = (source_kind or "system").strip()
        source_id = str(source_id or "").strip()
        if not subject_type or not subject_id or not event_type or not source_id:
            return 0
        importance = max(1, min(5, int(importance or 3)))
        if expires_turn is None:
            # 按重要度自动衰减；importance=5 永久保留（None）
            _ttl = {1: 6, 2: 12, 3: 24, 4: 48}
            ttl = _ttl.get(importance)
            if ttl is not None:
                expires_turn = int(state.turn) + ttl
        clean_tags = []
        for tag in tags or []:
            t = str(tag).strip()
            if t and t not in clean_tags:
                clean_tags.append(t[:40])
        existed = self.conn.execute(
            """
            SELECT id FROM event_memories
            WHERE subject_type=? AND subject_id=? AND event_type=? AND source_kind=? AND source_id=?
            """,
            (subject_type, subject_id, event_type, source_kind, source_id),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO event_memories
                (subject_type, subject_id, turn, year, period, event_type, title,
                 cause, process, outcome, sentiment, importance, tags,
                 source_kind, source_id, expires_turn)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject_type, subject_id, event_type, source_kind, source_id)
            DO UPDATE SET
                turn = excluded.turn,
                year = excluded.year,
                period = excluded.period,
                title = excluded.title,
                cause = excluded.cause,
                process = excluded.process,
                outcome = excluded.outcome,
                sentiment = excluded.sentiment,
                importance = excluded.importance,
                tags = excluded.tags,
                expires_turn = excluded.expires_turn,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                subject_type, subject_id, state.turn, state.year, state.period,
                event_type, str(title or "")[:40], str(cause or "")[:80],
                str(process or "")[:80], str(outcome or "")[:80],
                sentiment if sentiment in {"positive", "neutral", "negative", "mixed"} else "neutral",
                importance, json.dumps(clean_tags, ensure_ascii=False),
                source_kind, source_id, expires_turn,
            ),
        )
        row = self.conn.execute(
            """
            SELECT id FROM event_memories
            WHERE subject_type=? AND subject_id=? AND event_type=? AND source_kind=? AND source_id=?
            """,
            (subject_type, subject_id, event_type, source_kind, source_id),
        ).fetchone()
        self.conn.commit()
        action = "更新" if existed else "保存"
        tlog(
            f"[memory/{action}] #{int(row['id']) if row else '?'} "
            f"{subject_type}:{subject_id} {event_type}《{str(title or '')[:24]}》"
            f" imp={importance} src={source_kind}:{source_id}"
        )
        tlog(
            f"[MEM-IO/db.upsert/BODY] #{int(row['id']) if row else '?'} "
            f"title={str(title or '')!r} cause={str(cause or '')!r} "
            f"process={str(process or '')!r} outcome={str(outcome or '')!r} "
            f"sentiment={sentiment} tags={clean_tags} expires_turn={expires_turn}"
        )
        return int(row["id"]) if row else 0

    def add_event_memory_source(
        self,
        memory_id: int,
        source_kind: str,
        source_id: str,
        excerpt: str = "",
        locator: Optional[Dict[str, object]] = None,
    ) -> None:
        if not memory_id:
            return
        locator_json = json.dumps(locator or {}, ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO event_memory_sources
                (memory_id, source_kind, source_id, excerpt, locator)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(memory_id, source_kind, source_id, locator)
            DO UPDATE SET
                excerpt = excluded.excerpt,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(memory_id), str(source_kind or "system"), str(source_id or ""),
                str(excerpt or "")[:200], locator_json,
            ),
        )
        self.conn.commit()
        tlog(
            f"[memory/source] memory=#{int(memory_id)} {source_kind}:{source_id} "
            f"excerpt={str(excerpt or '')[:48]}"
        )

    def prune_event_memories_for_turn(self, turn: int, per_subject: int = 3) -> None:
        """同一主体同回合只保留若干高价值摘要卡，避免记忆膨胀。"""
        rows = self.conn.execute(
            """
            SELECT id, subject_type, subject_id, importance, updated_at
            FROM event_memories
            WHERE turn = ?
            ORDER BY subject_type, subject_id, importance DESC, id DESC
            """,
            (int(turn),),
        ).fetchall()
        seen: Dict[Tuple[str, str], int] = {}
        delete_ids: List[int] = []
        for row in rows:
            key = (row["subject_type"], row["subject_id"])
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > per_subject:
                delete_ids.append(int(row["id"]))
        if delete_ids:
            placeholders = ",".join("?" for _ in delete_ids)
            self.conn.execute(f"DELETE FROM event_memory_sources WHERE memory_id IN ({placeholders})", delete_ids)
            self.conn.execute(f"DELETE FROM event_memories WHERE id IN ({placeholders})", delete_ids)
            self.conn.commit()
            tlog(f"[memory/prune] turn={turn} deleted={delete_ids}")

    def get_relevant_event_memories(
        self,
        character_name: str,
        faction: str,
        office_type: str,
        turn: int,
        limit: int = 5,
        ignore_expiry: bool = False,
    ) -> List[Dict[str, object]]:
        """召见前取少量相关旧事摘要；纯结构化检索，不走向量库。
        ignore_expiry=True 时按历史时点查，不受 expires_turn 过滤。
        """
        active_issues = self.list_active_issues()
        active_issue_tags: List[str] = []
        for issue in active_issues[:12]:
            active_issue_tags.append(f"#{int(issue['id'])}")
            if issue["title"]:
                active_issue_tags.append(str(issue["title"])[:20])
        tag_needles = [character_name, faction, office_type] + active_issue_tags
        expiry_clause = "" if ignore_expiry else "AND (expires_turn IS NULL OR expires_turn >= ?)"
        params: list = [int(turn)]
        if not ignore_expiry:
            params.append(int(turn))
        params += [character_name, faction, f"%{character_name}%", f"%{faction}%", f"%{office_type}%"]
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM event_memories
            WHERE turn <= ?
              {expiry_clause}
              AND (
                (subject_type='character' AND subject_id=?)
                OR (subject_type='faction' AND subject_id=?)
                OR (subject_type='court' AND importance>=4)
                OR tags LIKE ?
                OR tags LIKE ?
                OR tags LIKE ?
              )
            """,
            params,
        ).fetchall()
        scored: List[Tuple[int, sqlite3.Row, List[str]]] = []
        for row in rows:
            age = max(0, int(turn) - int(row["turn"]))
            if int(row["importance"]) <= 1 and not (
                row["subject_type"] == "character" and row["subject_id"] == character_name and age <= 3
            ):
                continue
            try:
                tags = json.loads(row["tags"] or "[]")
            except Exception as exc:
                tlog(f"[db] tags JSON 损坏，回空（subject={row['subject_id']}）：{exc}")  # #14 surface
                tags = []
            tag_matches = [t for t in tag_needles if t and any(str(t) in str(tag) or str(tag) in str(t) for tag in tags)]
            exact = row["subject_type"] == "character" and row["subject_id"] == character_name
            active_hit = any(str(t).startswith("#") or t in active_issue_tags for t in tag_matches)
            score = (
                int(row["importance"]) * 10
                + (20 if exact else 0)
                + len(tag_matches) * 4
                + max(0, 10 - age)
                + (12 if active_hit else 0)
            )
            scored.append((score, row, tags))  # 存已解析 tags（含损坏回退 []）供 result 复用，免二次 json.loads（#14）
        scored.sort(key=lambda item: (item[0], int(item[1]["turn"]), int(item[1]["id"])), reverse=True)
        result: List[Dict[str, object]] = []
        for _score, row, tags in scored[:limit]:
            result.append({
                "id": int(row["id"]),
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "turn": int(row["turn"]),
                "year": int(row["year"]),
                "period": int(row["period"]),
                "event_type": row["event_type"],
                "title": row["title"],
                "cause": row["cause"],
                "process": row["process"],
                "outcome": row["outcome"],
                "sentiment": row["sentiment"],
                "importance": int(row["importance"]),
                "tags": tags,  # 复用评分循环已解析的 tags（损坏行回退 []，不再二次 json.loads 崩库，#14 cmr）
            })
        if result:
            ids = ",".join(str(item["id"]) for item in result)
            tlog(f"[memory/recall] {character_name} hit={len(result)} ids={ids}")
            tlog(f"[MEM-IO/db.recall/OUTPUT] {character_name} full={json.dumps(result, ensure_ascii=False)}")
        else:
            tlog(f"[memory/recall] {character_name} hit=0")
        return result

    def get_recent_event_memories(
        self,
        turn: int,
        window: int = 5,
        limit: int = 100,
    ) -> List[Dict[str, object]]:
        """取近 window 回合内所有 event_memories，按 turn/id 升序，上限 limit 条。"""
        since = max(1, turn - window + 1)
        rows = self.conn.execute(
            """
            SELECT id, subject_type, subject_id, turn, year, period,
                   event_type, title, cause, process, outcome, sentiment, importance, tags
            FROM event_memories
            WHERE turn >= ? AND turn <= ?
            ORDER BY turn ASC, id ASC
            LIMIT ?
            """,
            (since, turn, limit),
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "id": int(row["id"]),
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "turn": int(row["turn"]),
                "year": int(row["year"]),
                "period": int(row["period"]),
                "event_type": row["event_type"],
                "title": row["title"],
                "cause": row["cause"],
                "process": row["process"],
                "outcome": row["outcome"],
                "sentiment": row["sentiment"],
                "importance": int(row["importance"]),
                "tags": json.loads(row["tags"] or "[]"),
            })
        tlog(f"[memory/recent] turn={turn} window={window} hit={len(result)}")
        if result:
            tlog(f"[MEM-IO/db.recent/OUTPUT] turn={turn} window={window} full={json.dumps(result, ensure_ascii=False)}")
        return result

    def get_memories_by_keywords(
        self,
        keywords: List[str],
        turn: int,
        limit: int = 10,
        ignore_expiry: bool = False,
    ) -> List[Dict[str, object]]:
        """推演前按关键词集合检索相关记忆，供 simulator/extractor 注入。

        keywords 来自 memory_retrieval agent 抽取的人名/地区/军队/势力/操作词。
        每个词对 tags JSON 做 LIKE 匹配，命中任一词即入候选，按 importance+时效评分。
        ignore_expiry=True 时按历史时点查，不受 expires_turn 过滤。
        """
        if not keywords:
            return []
        active_issue_tags = [
            f"#{int(r['id'])}"
            for r in self.conn.execute(
                "SELECT id FROM issues WHERE status='active'"
            ).fetchall()
        ]
        needles = list(dict.fromkeys([k for k in keywords if k] + active_issue_tags))
        like_clauses = " OR ".join(["tags LIKE ?" for _ in needles])
        like_params = [f"%{n}%" for n in needles]
        expiry_clause = "" if ignore_expiry else "AND (expires_turn IS NULL OR expires_turn >= ?)"
        base_params: list = [int(turn)]
        if not ignore_expiry:
            base_params.append(int(turn))

        rows = self.conn.execute(
            f"""
            SELECT * FROM event_memories
            WHERE turn <= ?
              {expiry_clause}
              AND ({like_clauses})
            ORDER BY importance DESC, turn DESC
            LIMIT ?
            """,
            base_params + like_params + [limit * 3],
        ).fetchall()

        scored: List[tuple] = []
        for row in rows:
            age = max(0, int(turn) - int(row["turn"]))
            try:
                tags = json.loads(row["tags"] or "[]")
            except Exception as exc:
                tlog(f"[db] tags JSON 损坏，回空（turn={row['turn']}）：{exc}")  # #14 surface
                tags = []
            hit_count = sum(
                1 for n in needles
                if any(n in str(t) or str(t) in n for t in tags)
            )
            score = int(row["importance"]) * 10 + hit_count * 5 + max(0, 8 - age)
            scored.append((score, row, tags))  # 带上已解析 tags（含损坏回退 []）供 result 复用（#14）

        scored.sort(key=lambda x: x[0], reverse=True)
        result = []
        for _score, row, tags in scored[:limit]:
            result.append({
                "id": int(row["id"]),
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "turn": int(row["turn"]),
                "year": int(row["year"]),
                "period": int(row["period"]),
                "title": row["title"],
                "cause": row["cause"],
                "outcome": row["outcome"],
                "importance": int(row["importance"]),
                "tags": tags,  # 复用评分循环已解析的 tags（损坏行回退 []，不再二次 json.loads 崩库，#14 cmr）
                "source_kind": row["source_kind"],  # 演算记忆 vs 大臣记忆
            })
        tlog(f"[memory/keywords] needles={len(needles)} hit={len(result)}")
        tlog(f"[MEM-IO/db.keywords/INPUT] keywords={keywords} turn={turn} ignore_expiry={ignore_expiry} needles={needles}")
        if result:
            tlog(f"[MEM-IO/db.keywords/OUTPUT] full={json.dumps(result, ensure_ascii=False)}")
        return result

    def event_memory_detail(self, memory_id: int) -> str:
        tlog(f"[memory/detail] request=#{int(memory_id)}")
        memory = self.conn.execute(
            "SELECT * FROM event_memories WHERE id = ?",
            (int(memory_id),),
        ).fetchone()
        if memory is None:
            return f"未找到旧事记忆 #{memory_id}。"
        sources = self.conn.execute(
            """
            SELECT source_kind, source_id, excerpt, locator
            FROM event_memory_sources
            WHERE memory_id = ?
            ORDER BY id
            """,
            (int(memory_id),),
        ).fetchall()
        header = (
            f"旧事 #{memory['id']}：{memory['year']}年{memory['period']}月，{memory['title']}。"
            f"起因：{memory['cause']}。经过：{memory['process']}。结果：{memory['outcome']}。"
        )
        if not sources:
            return header + "\n未存原始摘录。"
        lines = [header, "来源摘录："]
        for idx, row in enumerate(sources, 1):
            locator = row["locator"] or "{}"
            lines.append(
                f"{idx}. [{row['source_kind']}:{row['source_id']}] {row['excerpt']}"
                + (f"（定位 {locator}）" if locator and locator != "{}" else "")
            )
        out = "\n".join(lines)
        tlog(f"[MEM-IO/db.detail/OUTPUT] #{memory_id} ({len(out)}字):\n{out}")
        return out

    def save_turn_report(self, state: GameState, report: str) -> None:
        """每回合月末奏报单独存档（turn_reports），与 turn_logs 日志解耦。"""
        self.conn.execute(
            """
            INSERT INTO turn_reports (turn, year, period, report)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(turn) DO UPDATE SET
                year = excluded.year,
                period = excluded.period,
                report = excluded.report
            """,
            (state.turn, state.year, state.period, sanitize_sqlite_text(report)),
        )
        self.conn.commit()

    def get_turn_report(self, turn: int) -> str:
        row = self.conn.execute(
            "SELECT report FROM turn_reports WHERE turn = ?",
            (turn,),
        ).fetchone()
        return (row["report"] if row else "") or ""

    # ── 章节记忆（event_memories 的 chapter_summary 类，每回合一条，importance=5 永久）──

    def save_chapter_memory(
        self, state: GameState, title: str, body: str, tags: Optional[List[str]] = None
    ) -> int:
        """落本回合章节记忆。subject 固定 court/chapter，event_type=chapter_summary，
        source_id=turn 保证每回合唯一。body 存整段叙事章节（不受 outcome 80 字限）。

        tags：除固定的 `章节`/`turnN` 外，并入 LLM 抽出的人物/地点/派系/事件召回标签，
        供 recall_memories 按人名/派系命中本章。"""
        base_tags = ["章节", f"turn{state.turn}"]
        for t in tags or []:
            t = str(t).strip()
            if t and t not in base_tags:
                base_tags.append(t)
        memory_id = self.upsert_event_memory(
            state,
            subject_type="court",
            subject_id="chapter",
            event_type="chapter_summary",
            title=str(title or f"崇祯{state.year}年{state.period}月")[:40],
            outcome=str(title or "")[:80],
            sentiment="neutral",
            importance=5,
            tags=base_tags,
            source_kind="turn_report",
            source_id=str(state.turn),
            expires_turn=None,
        )
        if memory_id:
            self.conn.execute(
                "UPDATE event_memories SET body = ? WHERE id = ?",
                (str(body or ""), memory_id),
            )
            self.conn.commit()
        return memory_id

    def list_chapter_memories(
        self, upto_turn: Optional[int] = None, recent: Optional[int] = None
    ) -> List[Dict[str, object]]:
        """取章节记忆，按 turn 升序。upto_turn 限上界；recent 只取最近 N 回合（喂大臣/推演用）。"""
        clauses = ["event_type = 'chapter_summary'"]
        params: list = []
        if upto_turn is not None:
            clauses.append("turn <= ?")
            params.append(int(upto_turn))
        if recent is not None and upto_turn is not None:
            clauses.append("turn >= ?")
            params.append(max(1, int(upto_turn) - int(recent) + 1))
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"SELECT turn, year, period, title, body FROM event_memories "
            f"WHERE {where} ORDER BY turn ASC",
            params,
        ).fetchall()
        return [
            {
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "title": r["title"] or "",
                "body": r["body"] or "",
            }
            for r in rows
        ]

    # ── 结局总结 ──

    def save_ending_summary(
        self, state: GameState, ending_status: str, summary: str, timeline: List[Dict[str, object]]
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO ending_summary (turn, year, period, ending_status, summary, timeline)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn) DO UPDATE SET
                year = excluded.year, period = excluded.period,
                ending_status = excluded.ending_status,
                summary = excluded.summary, timeline = excluded.timeline
            """,
            (
                state.turn, state.year, state.period, str(ending_status or ""),
                str(summary or ""), json.dumps(timeline or [], ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def get_ending_summary(self) -> Optional[Dict[str, object]]:
        """取最近一条结局总结（单库一局，按 turn 取最大）。无则 None。"""
        row = self.conn.execute(
            "SELECT turn, year, period, ending_status, summary, timeline "
            "FROM ending_summary ORDER BY turn DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        try:
            timeline = json.loads(row["timeline"] or "[]")
        except Exception as exc:
            tlog(f"[db] timeline JSON 损坏，回空：{exc}")  # #14 surface
            timeline = []
        return {
            "turn": int(row["turn"]),
            "year": int(row["year"]),
            "period": int(row["period"]),
            "ending_status": row["ending_status"],
            "summary": row["summary"] or "",
            "timeline": timeline,
        }

    def list_archived_turns(self) -> List[Dict[str, object]]:
        """所有已存档回合（turn_reports/turn_extractions/turn_directives 任一有数据）。
        返回按 turn 升序的元信息列表，每项含 turn/year/period 与各来源是否存在。"""
        rows = self.conn.execute(
            """
            SELECT t.turn AS turn,
                   MAX(t.year) AS year,
                   MAX(t.period) AS period,
                   MAX(t.has_report) AS has_report,
                   MAX(t.has_extraction) AS has_extraction,
                   MAX(t.has_directive) AS has_directive
            FROM (
                SELECT turn, year, period, 1 AS has_report, 0 AS has_extraction, 0 AS has_directive
                FROM turn_reports
                UNION ALL
                SELECT turn, year, period, 0, 1, 0 FROM turn_extractions
                UNION ALL
                SELECT turn, year, period, 0, 0, 1 FROM turn_directives
                WHERE status = 'issued'
            ) AS t
            GROUP BY t.turn
            ORDER BY t.turn
            """
        ).fetchall()
        return [
            {
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "has_report": bool(r["has_report"]),
                "has_extraction": bool(r["has_extraction"]),
                "has_directive": bool(r["has_directive"]),
            }
            for r in rows
        ]

    def list_directives_by_turn(self, turn: int) -> List[Dict[str, object]]:
        """读某回合已颁诏（issued）草案，按 id 升序。"""
        rows = self.conn.execute(
            """
            SELECT d.id, d.turn, d.year, d.period, d.event_id, d.actor,
                   d.skill_id, d.text, d.source, d.status, d.notes,
                   d.created_at, d.updated_at,
                   e.title AS event_title
            FROM turn_directives d
            LEFT JOIN events e ON e.id = d.event_id
            WHERE d.turn = ? AND d.status = 'issued'
            ORDER BY d.id
            """,
            (int(turn),),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn": int(r["turn"]),
                "year": int(r["year"]),
                "period": int(r["period"]),
                "event_id": r["event_id"] or "",
                "event_title": r["event_title"] or "",
                "actor": r["actor"] or "",
                "skill_id": r["skill_id"] or "",
                "text": r["text"] or "",
                "source": r["source"] or "",
                "status": r["status"] or "",
                "notes": r["notes"] or "",
                "created_at": r["created_at"] or "",
                "updated_at": r["updated_at"] or "",
            }
            for r in rows
        ]

    def save_turn_extraction(
        self,
        state: GameState,
        decree_text: str = "",
        narrative: str = "",
        extractor_input: str = "",
        extractor_output: str = "",
    ) -> None:
        """推演链留痕（turn_extractions）：输入 + applied 可见输出。"""
        self.conn.execute(
            """
            INSERT INTO turn_extractions
                (turn, year, period, decree_text, narrative, extractor_input, extractor_output)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn) DO UPDATE SET
                year = excluded.year,
                period = excluded.period,
                decree_text = excluded.decree_text,
                narrative = excluded.narrative,
                extractor_input = excluded.extractor_input,
                extractor_output = excluded.extractor_output
            """,
            (state.turn, state.year, state.period,
             sanitize_sqlite_text(decree_text), sanitize_sqlite_text(narrative),
             sanitize_sqlite_text(extractor_input), sanitize_sqlite_text(extractor_output)),
        )
        self.conn.commit()

    # ── HITL 决策点 ─────────────────────────────────────────────────────
    def save_pending_decisions(self, turn: int, decisions: List[Dict[str, object]]) -> None:
        """覆写本回合待裁决策点（先清后插），idx 按列表顺序。choice 初始空（待皇帝选）。"""
        self.conn.execute("DELETE FROM pending_decisions WHERE turn = ?", (int(turn),))
        for idx, d in enumerate(decisions):
            self.conn.execute(
                """INSERT INTO pending_decisions
                   (turn, idx, event_id, title, context, options_json, choice_json, status)
                   VALUES (?, ?, ?, ?, ?, ?, '', 'pending')""",
                (
                    int(turn), idx,
                    str(d.get("event_id") or ""),
                    str(d.get("title") or ""),
                    str(d.get("context") or ""),
                    json.dumps(d.get("options") or [], ensure_ascii=False),
                ),
            )
        self.conn.commit()

    def list_pending_decisions(self, turn: int) -> List[Dict[str, object]]:
        """读本回合决策点（按 idx）。options 反序列化；choice 为已选则带出。"""
        rows = self.conn.execute(
            "SELECT idx, event_id, title, context, options_json, choice_json, status "
            "FROM pending_decisions WHERE turn = ? ORDER BY idx",
            (int(turn),),
        ).fetchall()
        out: List[Dict[str, object]] = []
        for r in rows:
            try:
                options = json.loads(r["options_json"] or "[]")
            except Exception as exc:
                tlog(f"[db] options_json 损坏，回空：{exc}")  # #14 surface
                options = []
            choice_raw = (r["choice_json"] or "").strip()
            try:
                choice = json.loads(choice_raw) if choice_raw else None
            except Exception as exc:
                tlog(f"[db] choice_json 损坏，回 None（idx={r['idx']}）：{exc}")  # #14 surface
                choice = None
            out.append({
                "idx": int(r["idx"]),
                "event_id": r["event_id"],
                "title": r["title"],
                "context": r["context"],
                "options": options if isinstance(options, list) else [],
                "choice": choice,
                "status": r["status"],
            })
        return out

    def clear_pending_decisions(self, turn: int) -> None:
        self.conn.execute("DELETE FROM pending_decisions WHERE turn = ?", (int(turn),))
        self.conn.commit()

    # ── 动作闸门：结构化聊天写动作暂存(ADR 0006) ──────────────────────────
    def stage_pending_action(
        self, turn: int, kind: str, action: str, minister_name: str,
        payload: Dict[str, object], target_id: Optional[int] = None,
    ) -> int:
        """把一条结构化聊天写动作存进 pending_actions 暂存(status=pending)。返回行 id。
        颁诏时 commit_pending_actions 批量落库;颁诏前不动真实表。"""
        cur = self.conn.execute(
            """INSERT INTO pending_actions
               (turn, kind, action, target_id, minister_name, payload_json, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (
                int(turn), str(kind), str(action),
                None if target_id is None else int(target_id),
                str(minister_name or ""),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def upsert_pending_directive(
        self, turn: int, minister_name: str, payload: Dict[str, object],
    ) -> int:
        """暂存或原地更新(last-write-wins)一条 kind=directive 拟旨意图(ADR 0006)。
        同一回合同一大臣至多一条 pending directive——新意图覆盖旧(补充=原地更新,非新增态)。
        返回行 id。"""
        row = self.conn.execute(
            "SELECT id FROM pending_actions "
            "WHERE turn=? AND minister_name=? AND kind='directive' AND status='pending'",
            (int(turn), str(minister_name)),
        ).fetchone()
        if row is not None:
            self.conn.execute(
                "UPDATE pending_actions SET payload_json=? WHERE id=?",
                (json.dumps(payload or {}, ensure_ascii=False), int(row["id"])),
            )
            self.conn.commit()
            return int(row["id"])
        return self.stage_pending_action(
            turn, kind="directive", action="拟旨",
            minister_name=minister_name, target_id=None, payload=payload,
        )

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

    def commit_pending_actions(
        self, state: GameState, *, content=None, registry=None, minister_name=None,
        kind_filter: Optional[str] = None, kind_filter_exclude: Optional[str] = None,
        directive_status: str = "draft", action_ids: Optional[Iterable[int]] = None,
    ) -> List[Dict[str, object]]:
        """颁诏:把本回合 pending 暂存的结构化写动作批量落到真实表(不拒绝即允许),
        按 id 序(=操作发生序)apply。落得了标 committed、落不了标 failed(都不留 pending,
        故幂等:已 committed/失败 不在 pending 清单、不重跑)。
        在 resolve_turn 最前、跑 LLM 结算管线之前调,使盘面时序与旧"召对期直写"一致。
        content/registry 仅 office(任免)落库需要(注册新臣 Agent);密令/后宫不需,故可选——
        探针 driver 路径无聊天暂存,传 None 即 no-op。
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
            try:
                payload = json.loads(pa["payload_json"] or "{}")
                if not isinstance(payload, dict):   # 坏 payload(JSON 数组/串)→ 当空,apply 必 False 标 failed
                    payload = {}
            except (ValueError, TypeError):
                payload = {}
            if pa["kind"] == "directive" and pa["action"] == "拟旨":
                committed = self._commit_conversational_draft(
                    state, pa, payload, content=content, registry=registry,
                    directive_status=directive_status)
                if committed is not None:
                    applied.append(committed)
                continue
            # apply 抛错(如 催办 对已转 pending_review 的密令)= 当 False:下面标 failed、
            # 不中断本轮其余动作、更不能崩整个结算(CMR P0)。
            cm = atomic(self) if owns_transaction else contextlib.nullcontext()
            with cm:
                savepoint = f"pending_action_apply_{int(pa['id'])}"
                ok = False
                self.conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    ok = self._apply_pending_action(
                        state, pa, payload, content=content, registry=registry)
                    if ok:
                        self.conn.execute(
                            "UPDATE pending_actions SET status='committed' WHERE id=?", (int(pa["id"]),))
                    else:
                        self.conn.execute(f"ROLLBACK TO {savepoint}")
                        # 落不了的(目标已转 pending_review、未知动作、坏 payload)标 failed,不留 pending——
                        # 否则回合推进后成旧回合不可见死行,永不再处理(ship-pre CMR codex)。
                        self.conn.execute(
                            "UPDATE pending_actions SET status='failed' WHERE id=?", (int(pa["id"]),))
                except Exception as exc:
                    self.conn.execute(f"ROLLBACK TO {savepoint}")
                    tlog(f"[pending_actions] 落库失败 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
                    ok = False
                    self.conn.execute(
                        "UPDATE pending_actions SET status='failed' WHERE id=?", (int(pa["id"]),))
                finally:
                    self.conn.execute(f"RELEASE {savepoint}")
            if ok:
                applied.append({"id": pa["id"], "kind": pa["kind"], "action": pa["action"],
                                "target_id": pa["target_id"]})
        return applied

    def retry_failed_pending_action(
        self, state: GameState, action_id: int, *, content=None, registry=None,
    ) -> Dict[str, object]:
        """重试 failed 的密令暂存动作，用原 payload 再走正常 durable 落库路径。"""
        row = self.conn.execute(
            "SELECT id, turn, kind, action, target_id, minister_name, payload_json, status "
            "FROM pending_actions WHERE id=?",
            (int(action_id),),
        ).fetchone()
        if row is None:
            raise KeyError("该待确认动作不存在。")
        pa = {
            "id": int(row["id"]),
            "turn": int(row["turn"]),
            "kind": row["kind"],
            "action": row["action"],
            "target_id": None if row["target_id"] is None else int(row["target_id"]),
            "minister_name": row["minister_name"],
            "payload_json": row["payload_json"],
            "status": row["status"],
        }
        if int(pa["turn"]) > int(state.turn):
            raise ValueError("该失败动作来自未来回合，不能重试。")
        if pa["status"] != "failed":
            raise ValueError("只有 failed 的待确认动作可以重试。")
        if pa["kind"] != "secret_order":
            raise ValueError("当前只支持重试失败的密令下达。")
        if getattr(state, "turn_phase", None) in FRONT_HALF_DONE_PHASES:
            raise ValueError("结算未完成，暂不能重试密令；请先完成或恢复本次结算。")
        try:
            payload = json.loads(pa["payload_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        apply_state = state
        if int(pa["turn"]) < int(state.turn):
            apply_state = self._state_for_pending_action_turn(state, int(pa["turn"]))
        with atomic(self):
            savepoint = f"pending_action_retry_{int(pa['id'])}"
            self.conn.execute(f"SAVEPOINT {savepoint}")
            try:
                try:
                    ok = self._apply_pending_action(
                        apply_state, pa, payload, content=content, registry=registry)
                    if not ok:
                        self.conn.execute(f"ROLLBACK TO {savepoint}")
                except Exception as exc:
                    try:
                        self.conn.execute(f"ROLLBACK TO {savepoint}")
                    except Exception as rollback_exc:
                        tlog(
                            "[pending_actions] 重试回滚失败 "
                            f"id={pa['id']} {pa['kind']}/{pa['action']}：{rollback_exc}"
                        )
                        raise RuntimeError("pending action retry rollback failed") from exc
                    tlog(f"[pending_actions] 重试落库失败 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
                    ok = False
                self.conn.execute(
                    "UPDATE pending_actions SET status=? WHERE id=?",
                    ("committed" if ok else "failed", int(pa["id"])),
                )
            finally:
                self.conn.execute(f"RELEASE {savepoint}")
        return {
            "id": pa["id"],
            "kind": pa["kind"],
            "action": pa["action"],
            "target_id": pa["target_id"],
            "committed": bool(ok),
        }

    @staticmethod
    def _state_for_pending_action_turn(state: GameState, turn: int) -> GameState:
        """给旧回合 failed 动作重试用的签发态；按月回推 year/period，metrics 共享只读。"""
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
        *, content=None, registry=None, directive_status: str = "draft",
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
                    stored_status = str(payload_for_apply.get("_directive_status") or "").strip()
                    payload_for_apply["_directive_status"] = (
                        stored_status if stored_status in {"draft", "pending"} else directive_status
                    )
                    ok = self._apply_pending_action(
                        state, pa, payload_for_apply, content=content, registry=registry)
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
                except Exception:
                    self.conn.execute(f"ROLLBACK TO {savepoint}")
                    raise
                finally:
                    self.conn.execute(f"RELEASE {savepoint}")
        except Exception as exc:
            tlog(f"[pending_actions] 落库异常 id={pa['id']} {pa['kind']}/{pa['action']}：{exc}")
            raise
        return result

    def _apply_pending_action(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        *, content=None, registry=None,
    ) -> bool:
        """把单条暂存动作落到真实表。未知 kind/action 或目标非 active 不落、返 False(由
        commit_pending_actions 标 failed,不静默丢——终态失败,不再重试)。
        office(任免)落库需 content/registry(注册新臣);缺则返 False(标 failed,不静默)。"""
        if pa["kind"] == "office":
            return self._commit_office_action(state, pa, payload, content, registry)
        if pa["kind"] == "secret_order":
            oid = pa["target_id"]
            if pa["action"] == "新建":
                title = str(payload.get("title") or "").strip()
                content_text = str(payload.get("content") or "").strip()
                assignee = str(payload.get("assignee") or pa["minister_name"] or "").strip()
                if not title or not content_text or not assignee:
                    return False
                tags_raw = payload.get("tags") or []
                tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
                deadline = _coerce_deadline_months(payload.get("deadline_months"), default=0)
                order_id = self.create_secret_order(
                    state, assignee, title, content_text, tags, deadline_months=deadline)
                if registry is not None:
                    try:
                        registry.refresh(assignee)
                    except Exception as exc:
                        tlog(f"[pending_actions] 密令已落库但刷新 Agent 失败 assignee={assignee}：{exc}")
                return order_id is not None
            if oid is None:
                return False
            if pa["action"] == "更新":
                deadline = _coerce_deadline_months(payload.get("deadline_months"), default=0)
                return self.update_secret_order_by_id(
                    state, int(oid),
                    str(payload.get("new_title") or ""),
                    str(payload.get("new_content") or ""),
                    tags=None, deadline_months=deadline,
                )
            if pa["action"] == "催办":
                deadline = _coerce_deadline_months(payload.get("deadline_months", 1), default=1)
                self.rush_secret_order(
                    int(oid), state, deadline_months=deadline, reason=str(payload.get("reason") or ""))
                return True
            if pa["action"] == "提交核议":
                return self.submit_secret_order_for_review(
                    int(oid), str(payload.get("claim") or ""), state.year, state.period)
            if pa["action"] == "记进展":
                return self.update_secret_order_progress(
                    int(oid), str(payload.get("note") or ""), state.year, state.period)
        if pa["kind"] == "consort" and pa["action"] == "调教":
            skill = str(payload.get("skill") or "")
            trait = str(payload.get("trait") or "")
            if not (skill or trait):
                return False
            name = str(payload.get("name") or pa["minister_name"])
            self.cultivate_consort(name, int(state.turn), skill, trait)
            # 对话确认是【回合中】落库,刷 Agent 让本回合后续对话即用上新技能/性格(线上 gemini);
            # 颁诏路在回合末、次回合本就重建,刷一下无害。
            if registry is not None:
                registry.refresh(name)
            return True
        if pa["kind"] == "directive" and pa["action"] == "拟旨":
            text = str(payload.get("text") or "").strip()
            actor = str(payload.get("actor") or pa["minister_name"] or "")
            if not text:
                return False
            status = "pending" if str(payload.get("_directive_status") or "draft") == "pending" else "draft"
            # 不回到颁诏 checkpoint 时默认同意为 draft；召对里明确应允只表示接受为候选，
            # 仍写成 pending 交给既有准/驳界面，避免绕过后续颁诏流程（#412）。
            cur = self.conn.execute(
                """
                INSERT INTO turn_directives
                (turn, year, period, event_id, actor, skill_id, text, source, status, notes)
                VALUES (?, ?, ?, '', ?, '', ?, '大臣拟旨', ?, ?)
                """,
                (state.turn, state.year, state.period, actor, text, status, f"由{actor}拟旨入档"),
            )
            did = int(cur.lastrowid)
            # 回填本暂存产生的 draft 行 id，供 undo_chat_turn 精确删除（BUG 3）；turn_directives
            # 行时序晚于 chat 快照、不在 rollback_items，需此 id 才能只删本轮自产的草案。
            self.conn.execute(
                "UPDATE pending_actions SET committed_directive_id=? WHERE id=?",
                (int(did), int(pa["id"])),
            )
            return True
        return False

    def _commit_office_action(
        self, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
        content, registry,
    ) -> bool:
        """任免(office)落库,按被任者是否在册分流(CMR R1 补全):
        - 任命既有官 → 升迁/调任:set_character_office(改官、仍 active),不当新人(apply_appointment
          对在册者命中即拒、会标 failed);
        - 任命朝臣(新任/升迁/调任)→ apply_office_appointment(与 extractor office_changes 共用的【唯一落地核】,
          自带 dead-reject / 非active→激活 / 顶替去重 / 内存+registry 同步,CMR R2 归一);
        - 任命纳妃(office 推断为后宫)→ 语义不同,走 apply_appointment 的 consort 路;
        - 罢免:_find_existing_minister 解 alias + ming-guard(外藩/后宫/不在册不接),dismissed+同步清内存 office。
        缺 content(无法查重/注册)→ False 标 failed,不静默。跨模块函数运行期 lazy import 避免 db↔session/issues 循环。"""
        if content is None:
            return False
        from ming_sim.session import _find_existing_minister
        name = str(payload.get("name") or "").strip()
        if not name:
            return False
        office = str(payload.get("office") or "")
        if pa["action"] == "任命":
            # 纳妃(后宫)语义不同,不走朝臣落地核:推断为后宫则走 apply_appointment 的 consort 路。
            if infer_office_type_from_office(office, "", self.llm_config) == "后宫":
                from ming_sim.session import apply_appointment
                data = {"name": name, "office": office, "office_type": "后宫", "approved": True}
                appointed, _displaced = apply_appointment(
                    self, state, content, registry, data, llm_config=self.llm_config)
                return bool(appointed)
            # 朝臣任命/升迁/调任 → 唯一落地核(在册激活授官 / 不在册建档 / dead 拒 / 空 office 拒)。
            from ming_sim.issues import apply_office_appointment
            faction = str(payload.get("faction") or "中立").strip() or "中立"
            reason = str(payload.get("reason") or "奉旨任免").strip() or "奉旨任免"
            office_type = str(payload.get("office_type") or "").strip()
            res = apply_office_appointment(
                self, state, content, registry, name, office,
                reason=reason, new_office_type=office_type, faction=faction, llm_config=self.llm_config)
            return not res.get("rejected")
        if pa["action"] == "罢免":
            # 仅大明【在职】大臣可罢:_find_existing_minister 已 ming-guard + 解 alias;
            # 外藩(power_id≠ming)/后宫/不在册不接(无字面 fallback,免误黜皇太极,CMR R2);
            # 再校 active,免把已故/已黜/致仕者的终态改写成 dismissed(CMR R3 codex R2)。
            key = _find_existing_minister(content, name, self)
            if key is None or self.get_character_status(key)[0] != "active":
                return False
            # 宗藩（就藩宗室）非朝堂命官，不可作朝臣罢免——_find_existing_minister 仍会解析到宗藩名
            # （任命核需解到名才能显式拒），故罢免侧单独守（cmr R6 cross-section）。
            _ch_key = content.characters.get(key)  # key 来自 _find_existing_minister 必在册，.get 防御一致（R2 gemini）
            if _ch_key is not None and is_vassal_prince(_ch_key):
                return False
            self.set_character_status(state, key, "dismissed", reason="奉旨罢黜")
            ch = content.characters.get(key)
            if ch is not None:
                ch.status = "dismissed"
                ch.office = ""   # set_character_status 已清 DB office,内存须跟上(roster 读 c.office)
                ch.transit_to = ""
            # 对话确认回合中落库,刷 Agent 让被罢者本回合后续不再以旧活跃态被召对(线上 gemini)。
            if registry is not None:
                registry.refresh(key)
            return True
        return False

    def withdraw_pending_action(self, action_id: int, turn: int) -> bool:
        """皇帝复核:撤回本回合一条尚未落库的暂存动作(删 pending 行)。返回是否删了。
        已 committed / 非本回合 / 不存在 → False。"""
        owns_transaction = not (
            bool(getattr(self.conn, "_commit_suspended", False))
            or int(getattr(self.conn, "_atomic_depth", 0) or 0) > 0
            or self.conn.in_transaction
        )
        cur = self.conn.execute(
            "DELETE FROM pending_actions WHERE id=? AND turn=? AND status='pending'",
            (int(action_id), int(turn)),
        )
        if owns_transaction:
            self.conn.commit()
        return cur.rowcount > 0

    def drop_pending_actions_for_minister(
        self, turn: int, minister_name: str, kind_filter_exclude: Optional[str] = None,
        action_ids: Optional[Iterable[int]] = None,
    ) -> int:
        """对话确认皇帝拒绝:丢弃该召对对象本回合尚未落库的暂存动作(删 pending 行)。
        返回删除条数。只动该大臣、只动 pending(已 committed 不动)。
        action_ids 非空=进一步只删指定 pending_actions.id（召对确认只可作用于本轮开始前可见项）。
        kind_filter_exclude 非空=不删该 kind(召对确认拒绝须放过 directive,BUG 1:拟旨搁置
        是颁诏期语义,不能被召对期拒绝静默删掉玩家草案)。"""
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
            cur = self.conn.execute(
                f"DELETE FROM pending_actions WHERE {where}",
                tuple(params),
            )
        else:
            cur = self.conn.execute(
                f"DELETE FROM pending_actions WHERE {where}",
                tuple(params),
            )
        if owns_transaction:
            self.conn.commit()
        return cur.rowcount

    def discard_pending_directives(self, turn: int) -> int:
        """退朝无诏时丢弃本回合尚未落库的对话式拟旨暂存（kind=directive, status=pending）。
        须在 commit_pending_actions 之前调用，防止 commit 把草案插成孤儿 turn_directives
        行——退朝路不颁诏，孤儿 draft 永不经 extractor、不可见（codex r5 F2）。
        返回删除条数。"""
        cur = self.conn.execute(
            "DELETE FROM pending_actions WHERE turn=? AND kind='directive' AND status='pending'",
            (int(turn),),
        )
        return cur.rowcount

    def save_resolve_context(
        self, turn: int, decree_text: str, narrative: str,
        simulator_payload: Dict[str, object],
        # #48：分组承载 dict {在办,待核议} 为正形；运行期仍兼容旧档/占位的 list（json 落库不挑类型），
        # 故注解取两者并集，不窄化成 dict-only（否则误判恢复路 list 调用为类型错）。
        secret_orders: Optional[Dict[str, object] | List[Dict[str, object]]] = None,
        relevant_memories: Optional[List[Dict[str, object]]] = None,
        extracted: Optional[Dict[str, object]] = None,
        source: str = "system_simulation",
    ) -> None:
        """暂存 phase1 推演结果，供 phase2 读回（决策暂停期间不重算 simulator）。

        extracted：extractor 产出的 canonical delta（ADR 0008 S2 无条件持久化的重跑真源）。
        传 None = 占位（HITL phase1 尚未跑 extractor）→ ready=0，get 时 extracted 不可见；
        显式传 dict（含空 {} = 真空 delta）→ ready=1。判别位防恢复入口把占位当真 delta 重放。
        """
        self.conn.execute(
            """INSERT INTO pending_resolve_context
               (turn, decree_text, narrative, simulator_payload_json,
                secret_orders_json, relevant_memories_json, extracted_delta_json,
                extracted_ready, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(turn) DO UPDATE SET
                   decree_text = excluded.decree_text,
                   narrative = excluded.narrative,
                   simulator_payload_json = excluded.simulator_payload_json,
                   secret_orders_json = excluded.secret_orders_json,
                   relevant_memories_json = excluded.relevant_memories_json,
                   extracted_delta_json = excluded.extracted_delta_json,
                   extracted_ready = excluded.extracted_ready,
                   source = excluded.source""",
            (
                int(turn), sanitize_sqlite_text(decree_text), sanitize_sqlite_text(narrative),
                safe_json_dumps(simulator_payload or {}, ensure_ascii=False),
                # #48：分组承载是 dict；空 dict 也按 dict 存（`or []` 会把 {} 退成 []，
                # 与 Dict 契约不符）。显式传 list（旧档/占位）仍原样存，None→{}。
                safe_json_dumps(secret_orders if secret_orders is not None else {}, ensure_ascii=False),
                safe_json_dumps(relevant_memories or [], ensure_ascii=False),
                safe_json_dumps(extracted if extracted is not None else {}, ensure_ascii=False),
                1 if extracted is not None else 0,
                # source 显式归一为枚举「值」字符串：Provenance 是 (str, Enum)，str(member) 在多数
                # Python 版本落 'Provenance.player_decree' 而非 'player_decree'——重抽时
                # Provenance(...) 不匹配 → 静默退回 system_simulation 丢源（Sourcery #175 bug_risk）。
                # getattr(.,"value",.) 让枚举取 .value、普通字符串原样、None/空回落 system_simulation。
                str(getattr(source, "value", source) or "system_simulation"),
            ),
        )
        self.conn.commit()

    def get_resolve_context(self, turn: int) -> Optional[Dict[str, object]]:
        """读回 phase1 暂存的推演上下文。无则 None。"""
        row = self.conn.execute(
            "SELECT decree_text, narrative, simulator_payload_json, "
            "secret_orders_json, relevant_memories_json, extracted_delta_json, "
            "extracted_ready, source "
            "FROM pending_resolve_context WHERE turn = ?",
            (int(turn),),
        ).fetchone()
        if row is None:
            return None
        def _load(text: str, default, label: str):
            try:
                return json.loads(text) if text else default
            except Exception as exc:
                tlog(f"[db] resolve_context {label} JSON 损坏，回退默认、恢复将丢该段（turn={turn}）：{exc}")  # #14 surface
                return default
        def _load_extracted():
            # ready=0 占位不可见；ready=1 但 JSON 损坏也回 None（逼「重跑 extractor」）——
            # 吞成 {} 会复活判别位刚消掉的歧义：重放空 delta=整月效果静默丢（cmr r4）。
            if not row["extracted_ready"]:
                return None
            try:
                parsed = json.loads(row["extracted_delta_json"])
            except Exception as exc:
                tlog(f"[db] resolve_context extracted_delta JSON 损坏，回 None 逼重抽（turn={turn}）：{exc}")  # #14 surface
                return None
            # 合法 JSON 非 dict（type-corrupt）同样回 None（重抽）：原样返回会让恢复叉
            # 抛 LLMContractError 绕过逃生口=corruption 软死锁（ship-pre r1）。
            return parsed if isinstance(parsed, dict) else None
        return {
            "decree_text": row["decree_text"],
            "narrative": row["narrative"],
            "simulator_payload": _load(row["simulator_payload_json"], {}, "simulator_payload"),
            # secret_orders 是 dict-first 承载（#48：save 时 None→{}），损坏 fallback 也用 {} 对齐
            # 契约——回 [] 会把分组 dict 退成 list、破坏 secret_orders.在办 式 dict 消费者（cmr CodeRabbit）。
            "secret_orders": _load(row["secret_orders_json"], {}, "secret_orders"),
            "relevant_memories": _load(row["relevant_memories_json"], [], "relevant_memories"),
            "extracted": _load_extracted(),
            "source": row["source"] or "system_simulation",  # 拒收来源，恢复重放用（#144）
        }

    def clear_resolve_context(self, turn: int) -> None:
        self.conn.execute("DELETE FROM pending_resolve_context WHERE turn = ?", (int(turn),))
        self.conn.commit()

    def get_turn_extraction(self, turn: int) -> Optional[Dict[str, object]]:
        """读 turn_extractions 一行；extractor_output JSON 解析失败时原样回字符串。"""
        row = self.conn.execute(
            "SELECT turn, year, period, decree_text, narrative, extractor_input, extractor_output "
            "FROM turn_extractions WHERE turn = ?",
            (int(turn),),
        ).fetchone()
        if row is None:
            return None
        def _parse(text: str) -> object:
            text = (text or "").strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except Exception:
                pass
            # LLM 多输出一个 }，顶层提前关闭，trailing 是被截出的字段。
            # 去掉多余 }，接回 trailing（trailing 本身以顶层 } 结尾）。
            try:
                dec = json.JSONDecoder()
                obj, end = dec.raw_decode(text)
                trailing = text[end:].strip()
                if trailing.startswith(","):
                    prefix = text[:end].rstrip()
                    if prefix.endswith("}"):
                        fixed = prefix[:-1] + trailing
                        try:
                            return json.loads(fixed)
                        except Exception:
                            pass
                return obj
            except Exception:
                pass
            return text
        return {
            "turn": int(row["turn"]),
            "year": int(row["year"]),
            "period": int(row["period"]),
            "decree_text": row["decree_text"] or "",
            "narrative": row["narrative"] or "",
            "extractor_input": _parse(row["extractor_input"] or ""),
            "extractor_output": _parse(row["extractor_output"] or ""),
        }

    def grant_skill(self, state: GameState, character_name: str, skill_id: str, granted_by: str = "皇帝") -> bool:
        exists = self.conn.execute(
            """
            SELECT 1 FROM skill_grants
            WHERE character_name = ? AND skill_id = ? AND active = 1
            LIMIT 1
            """,
            (character_name, skill_id),
        ).fetchone()
        if exists:
            return False
        self.conn.execute(
            """
            INSERT INTO skill_grants (character_name, skill_id, granted_by, source_turn, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (character_name, skill_id, granted_by, state.turn),
        )
        self.conn.commit()
        return True

    def revoke_skill(self, character_name: str, skill_id: str) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE skill_grants
            SET active = 0
            WHERE character_name = ? AND skill_id = ? AND active = 1
            """,
            (character_name, skill_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def active_skill_grants(self, character_name: str) -> List[str]:
        rows = self.conn.execute(
            """
            SELECT skill_id FROM skill_grants
            WHERE character_name = ? AND active = 1
            ORDER BY id
            """,
            (character_name,),
        ).fetchall()
        return [str(row["skill_id"]) for row in rows]

    def add_directive(
        self,
        state: GameState,
        event: Event | None,
        text: str,
        source: str,
        actor: str = "",
        skill_id: str = "",
        notes: str = "",
        status: str = "draft",
    ) -> int:
        # status: 'draft'=已确认颁诏候选；'pending'=大臣拟旨待皇帝核定。
        cursor = self.conn.execute(
            """
            INSERT INTO turn_directives
            (turn, year, period, event_id, actor, skill_id, text, source, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (state.turn, state.year, state.period, event.id if event else "",
             actor, skill_id, text, source, status, notes),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_directives(
        self, state: GameState, statuses: Tuple[str, ...] = ("draft",)
    ) -> List[sqlite3.Row]:
        # 默认只取 draft（颁诏候选）；UI 列表传 ('pending','draft') 一起取，前端按 status 分区。
        placeholders = ",".join("?" for _ in statuses)
        return self.conn.execute(
            f"""
            SELECT d.*, e.title AS event_title
            FROM turn_directives d
            LEFT JOIN events e ON e.id = d.event_id
            WHERE d.turn = ? AND d.status IN ({placeholders})
            ORDER BY d.id
            """,
            (state.turn, *statuses),
        ).fetchall()

    def confirm_directive(self, directive_id: int) -> None:
        """大臣拟旨经皇帝核定：pending → draft（进入颁诏候选池）。"""
        self.conn.execute(
            """
            UPDATE turn_directives
            SET status = 'draft', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
            """,
            (directive_id,),
        )
        self.conn.commit()

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

    def update_directive_text(self, directive_id: int, text: str) -> None:
        self.conn.execute(
            """
            UPDATE turn_directives
            SET text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (text, directive_id),
        )
        self.conn.commit()

    def update_directive(
        self,
        directive_id: int,
        event: Event,
        actor: str,
        skill_id: str,
        text: str,
        notes: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE turn_directives
            SET event_id = ?,
                actor = ?,
                skill_id = ?,
                text = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (event.id, actor, skill_id, text, notes, directive_id),
        )
        self.conn.commit()

    def delete_directive(self, directive_id: int) -> None:
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
            WHERE turn = ? AND status = 'draft'
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

    def list_active_issues(self, kind: str | None = None) -> List[sqlite3.Row]:
        sql = "SELECT * FROM issues WHERE status = 'active'"
        args: List[object] = []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        sql += " ORDER BY severity DESC, id ASC"
        return self.conn.execute(sql, args).fetchall()

    def list_closed_issues_at(self, closed_turn: int) -> List[sqlite3.Row]:
        """指定 turn 关闭（resolved / failed / dropped）的 issue。"""
        return self.conn.execute(
            "SELECT * FROM issues WHERE closed_turn = ? AND status IN ('resolved','failed','dropped') ORDER BY id",
            (int(closed_turn),),
        ).fetchall()

    def count_active_initiatives(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM issues WHERE kind='initiative' AND status='active'"
        ).fetchone()
        return int(row["n"] or 0)

    def find_active_issue_by_origin(self, origin_kind: str, origin_ref: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? AND status='active' LIMIT 1",
            (origin_kind, origin_ref),
        ).fetchone()

    def find_any_issue_by_origin(self, origin_kind: str, origin_ref: str) -> sqlite3.Row | None:
        """查任意状态（含 resolved/failed/dropped）的同源 issue，用于 spawn 去重。"""
        return self.conn.execute(
            "SELECT * FROM issues WHERE origin_kind=? AND origin_ref=? LIMIT 1",
            (origin_kind, origin_ref),
        ).fetchone()

    def has_event_triggered(self, event_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered' LIMIT 1",
            (event_id,),
        ).fetchone()
        return row is not None

    def event_terminal_state(self, event_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT terminal_state FROM event_triggers WHERE event_id=? LIMIT 1",
            (event_id,),
        ).fetchone()
        return row["terminal_state"] if row is not None else None

    def has_event_terminal_state(self, event_id: str, terminal_state: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state=? LIMIT 1",
            (event_id, terminal_state),
        ).fetchone()
        return row is not None

    def _event_terminal_upgrade_assignments(self, *, fill_triggered_reason: bool = False) -> str:
        reason_fill = ""
        pending_reason_expr = "COALESCE(NULLIF(event_triggers.terminal_reason, ''), excluded.terminal_reason)"
        if fill_triggered_reason:
            pending_reason_expr = "COALESCE(NULLIF(excluded.terminal_reason, ''), event_triggers.terminal_reason)"
            reason_fill = """
                    WHEN event_triggers.terminal_state = 'triggered'
                      AND COALESCE(event_triggers.terminal_reason, '') = ''
                      AND excluded.terminal_reason <> ''
                    THEN excluded.terminal_reason
            """
        return f"""
                turn = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.turn
                    ELSE event_triggers.turn
                END,
                year = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.year
                    ELSE event_triggers.year
                END,
                period = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.period
                    ELSE event_triggers.period
                END,
                source = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.source
                    ELSE event_triggers.source
                END,
                terminal_state = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN excluded.terminal_state
                    ELSE event_triggers.terminal_state
                END,
                terminal_reason = CASE
                    WHEN COALESCE(event_triggers.terminal_state, '') = ''
                    THEN {pending_reason_expr}
{reason_fill}                    ELSE event_triggers.terminal_reason
                END
        """

    def mark_event_triggered(
        self,
        state: GameState,
        event_id: str,
        source: str = "simulation",
        *,
        terminal_reason: str = "",
        commit: bool = True,
    ) -> None:
        self.conn.execute(
            f"""
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason)
            VALUES (?, ?, ?, ?, ?, 'triggered', ?)
            ON CONFLICT(event_id) DO UPDATE SET
                {self._event_terminal_upgrade_assignments(fill_triggered_reason=True)}
            """,
            (event_id, state.turn, state.year, state.period, source, str(terminal_reason or "")[:200]),
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
        self.conn.execute(
            f"""
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason)
            VALUES (?, ?, ?, ?, ?, 'avoided', ?)
            ON CONFLICT(event_id) DO UPDATE SET
                {self._event_terminal_upgrade_assignments()}
            """,
            (event_id, state.turn, state.year, state.period, source, reason[:200]),
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
        self.conn.execute(
            f"""
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason)
            VALUES (?, ?, ?, ?, ?, 'obsolete', ?)
            ON CONFLICT(event_id) DO UPDATE SET
                {self._event_terminal_upgrade_assignments()}
            """,
            (event_id, state.turn, state.year, state.period, source, reason[:200]),
        )
        if commit:
            self.conn.commit()

    def mark_event_expired(self, state: GameState, event_id: str, *, commit: bool = True) -> None:
        self.conn.execute(
            f"""
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason)
            VALUES (?, ?, ?, ?, 'window_expired', 'expired', '过最晚触发时点仍未达成触发门')
            ON CONFLICT(event_id) DO UPDATE SET
                {self._event_terminal_upgrade_assignments()}
            """,
            (event_id, state.turn, state.year, state.period),
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
        payload = json.dumps(choice if isinstance(choice, dict) else {}, ensure_ascii=False)
        label = str((choice or {}).get("label") or "")[:200] if isinstance(choice, dict) else ""
        self.conn.execute(
            """
            INSERT INTO event_triggers
                (event_id, turn, year, period, source, terminal_state, terminal_reason, choice_json)
            VALUES (?, ?, ?, ?, ?, '', ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                -- 终态账不可逆（codex correctness）：HITL 选择只暂存 choice_json；新行不抢先
                -- 写 triggered，待 phase2 的 event_pool 正常立局势后再由 mark_event_triggered 补终态。
                -- 冲突时**保留**已有 terminal_state——
                -- HITL 选择只补 choice_json，绝不把已有的 expired/avoided/obsolete 翻成
                -- triggered。source 同理：只有空终态暂存行或已是 triggered 的行才更新成
                -- hitl_decision，expired/avoided/obsolete 不被误标。
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
        cur = self.conn.execute(
            """
            INSERT INTO issues (
                kind, title, origin_kind, origin_ref, origin_turn,
                bar_value, bar_good_meaning, bar_bad_meaning, inertia,
                phase, stage_text, status, severity, region_hint, faction_hint,
                tags, ongoing_effects, cancellable, cancel_cost,
                effect_on_resolve, effect_on_fail, resolve_condition, fail_condition,
                end_turn, stop_condition, commitment_kind, last_advance_turn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sanitize_sqlite_text(kind), sanitize_sqlite_text(title),
                sanitize_sqlite_text(origin_kind), sanitize_sqlite_text(origin_ref), state.turn,
                bar_value, sanitize_sqlite_text(bar_good_meaning), sanitize_sqlite_text(bar_bad_meaning), int(inertia),
                phase, sanitize_sqlite_text(stage_text), severity,
                sanitize_sqlite_text(region_hint), sanitize_sqlite_text(faction_hint),
                safe_json_dumps(tags or [], ensure_ascii=False),
                safe_json_dumps(ongoing_effects or {}, ensure_ascii=False),
                sanitize_sqlite_text(cancellable),
                safe_json_dumps(cancel_cost or {}, ensure_ascii=False),
                safe_json_dumps(effect_on_resolve or {}, ensure_ascii=False),
                safe_json_dumps(effect_on_fail or {}, ensure_ascii=False),
                sanitize_sqlite_text(resolve_condition), sanitize_sqlite_text(fail_condition),
                int(end_turn),
                (
                    safe_json_dumps(stop_condition, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(stop_condition, dict)
                    else sanitize_sqlite_text(str(stop_condition or ""))
                ),
                sanitize_sqlite_text(str(commitment_kind or "")),
                state.turn,
            ),
        )
        if commit:
            self.conn.commit()
        return int(cur.lastrowid)

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
        row = self.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
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
        self.conn.execute(
            """
            UPDATE issues SET bar_value=?, phase=?, stage_text=?, status=?, inertia=?,
                              closed_turn=?, last_advance_turn=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (to_value, new_phase, sanitize_sqlite_text(to_stage_text), new_status, new_inertia, closed_turn, state.turn, issue_id),
        )
        self.conn.execute(
            """
            INSERT INTO issue_advances (
                issue_id, turn, trigger_kind, trigger_ref,
                delta_bar, from_value, to_value,
                from_stage_text, to_stage_text, narrative, metric_delta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id, state.turn,
                sanitize_sqlite_text(trigger_kind), sanitize_sqlite_text(trigger_ref),
                actual_delta, from_value, to_value,
                sanitize_sqlite_text(from_stage_text), sanitize_sqlite_text(to_stage_text),
                sanitize_sqlite_text(narrative),
                safe_json_dumps(metric_delta or {}, ensure_ascii=False),
            ),
        )
        if commit:
            self.conn.commit()
        return self.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()

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
        row = self.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
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
        self.conn.execute(
            """
            UPDATE issues SET bar_value=?, phase=?, stage_text=?, status=?,
                              closed_turn=?, last_advance_turn=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (to_value, new_phase, sanitize_sqlite_text(to_stage_text), reason, state.turn, state.turn, issue_id),
        )
        self.conn.execute(
            """
            INSERT INTO issue_advances (
                issue_id, turn, trigger_kind, trigger_ref,
                delta_bar, from_value, to_value,
                from_stage_text, to_stage_text, narrative, metric_delta
            ) VALUES (?, ?, 'close', ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                issue_id, state.turn, sanitize_sqlite_text(reason),
                actual_delta, from_value, to_value,
                sanitize_sqlite_text(from_stage_text), sanitize_sqlite_text(to_stage_text),
                sanitize_sqlite_text(narrative),
            ),
        )
        if commit:
            self.conn.commit()
        return self.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()

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
        cur = self.conn.execute(
            """INSERT INTO legacies
               (name, source_issue_id, modifiers, narrative_hint,
                start_month, duration_months, status, clear_gate, legacy_key)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (
                str(name)[:60], source_issue_id,
                json.dumps(modifiers, ensure_ascii=False),
                str(narrative_hint)[:200],
                start_month, int(duration_months),
                json.dumps(clear_gate or {}, ensure_ascii=False),
                str(legacy_key)[:60],
            ),
        )
        if commit:
            self.conn.commit()
        self._legacy_mod_cache = None  # active 集变了，修正符缓存失效
        return int(cur.lastrowid)

    def list_active_legacies(self, state: GameState) -> List[sqlite3.Row]:
        """当前仍生效的帝国修正，顺手把已到期的失活。"""
        external_transaction = bool(getattr(self.conn, "_commit_suspended", False) or self.conn.in_transaction)
        self.expire_legacies(state, commit=not external_transaction)
        return self.conn.execute(
            "SELECT * FROM legacies WHERE status='active' ORDER BY id"
        ).fetchall()

    def expire_legacies(self, state: GameState, commit: bool = True) -> List[int]:
        """到期失活：当前月 >= start_month + duration_months（永久 -1 永不到期）。"""
        now = int(state.year) * 12 + int(state.period)
        rows = self.conn.execute(
            "SELECT id, start_month, duration_months FROM legacies WHERE status='active'"
        ).fetchall()
        expired: List[int] = []
        for r in rows:
            dur = int(r["duration_months"])
            if dur < 0:
                continue
            if now >= int(r["start_month"]) + dur:
                expired.append(int(r["id"]))
        if expired:
            self.conn.executemany(
                "UPDATE legacies SET status='expired' WHERE id=?",
                [(i,) for i in expired],
            )
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
        for lg in self.conn.execute(
            "SELECT modifiers FROM legacies WHERE status='active' ORDER BY id"
        ).fetchall():
            try:
                eff = json.loads(str(lg["modifiers"] or "{}"))
            except Exception as exc:
                tlog(f"[db] legacy modifiers JSON 损坏，跳过该 legacy：{exc}")  # #14 surface
                continue
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
        row = self.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if row is None or row["status"] != "active":
            return None
        self.conn.execute(
            "UPDATE issues SET status='dropped', closed_turn=?, last_advance_turn=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (state.turn, state.turn, issue_id),
        )
        self.conn.execute(
            """
            INSERT INTO issue_advances (
                issue_id, turn, trigger_kind, delta_bar,
                from_value, to_value, narrative, metric_delta
            ) VALUES (?, ?, 'cancel', 0, ?, ?, ?, ?)
            """,
            (
                issue_id, state.turn,
                int(row["bar_value"]), int(row["bar_value"]),
                narrative,
                json.dumps(applied_cost or {}, ensure_ascii=False),
            ),
        )
        if commit:
            self.conn.commit()
        return self.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()

    def list_recent_issue_advances(self, issue_id: int, limit: int = 3) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM issue_advances WHERE issue_id=? ORDER BY id DESC LIMIT ?",
            (issue_id, limit),
        ).fetchall()

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
        commit: bool = True,
    ) -> int:
        """记一笔经济流水到 economy_ledger，同步更新 metrics[account]。

        purpose/target_kind/target_id 仅对 extractor 抽出的 economy_moves（自由拨款）填，
        flows 月固定支出与所有收入一律 None。受控枚举见 constants.ECONOMY_PURPOSES。

        遗产修正：account 上若有 active 遗产百分比修正符，先按 apply_legacy_pct 放大/缩小 delta
        再落账。修正折进本笔流水，不另立账行。
        category=='局势遗产' 时不再二次修正（避免自乘，且当前已无该类调用）。
        帝国修正只对收入（delta>0 正向流水）生效；支出（delta<0）按面值落账（issue #341）——
        即本路径仅以 delta>0 调 apply_legacy_pct（其 base>=0 ×(1+net/100) 分支）；
        apply_legacy_pct 自身的 base<0 ×(1-net/100) 分支由 region/army 等其它调用方使用，本路径不走。
        """
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise TypeError("delta must be an integer")
        if category != "局势遗产":
            net_pct = int(self.legacy_modifiers(state).get(account, 0) or 0)  # type: ignore[arg-type]
            if net_pct and delta > 0:
                delta = self.apply_legacy_pct(int(delta), net_pct)
        before = int(state.metrics[account])
        after = max(0, before + int(delta))
        actual = after - before
        if actual == 0:
            return 0
        state.metrics[account] = after
        self.conn.execute(
            """
            INSERT INTO economy_ledger
            (turn, year, period, account, delta, balance_after, category, reason,
             event_id, edict_id, actor, purpose, target_kind, target_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '事项推演', ?, ?, ?)
            """,
            (state.turn, state.year, state.period, account, actual, after,
             category, reason, purpose, target_kind, target_id),
        )
        self.sync_economy_accounts(state)
        if commit:
            self.conn.commit()
        return actual

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

    def create_secret_order(
        self,
        state: GameState,
        minister_name: str,
        title: str,
        content: str,
        tags: List[str],
        importance: int = 4,
        deadline_months: int = 0,
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
        active_count = self.conn.execute(
            "SELECT COUNT(*) FROM secret_orders WHERE status='active'"
        ).fetchone()[0]
        if active_count >= 20:
            raise ValueError(f"进行中密令已达上限（20条），请先结案部分密令再下新令。当前：{active_count} 条。")
        tags_json = json.dumps(tags, ensure_ascii=False)
        deadline = max(0, min(int(deadline_months or 0), 36))
        due_turn = int(state.turn) + deadline if deadline else 0
        cur = self.conn.execute(
            """
            INSERT INTO secret_orders
                (turn_issued, due_turn, year_issued, period_issued, minister_name, title, content, tags, importance, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (state.turn, due_turn, state.year, state.period, minister_name, title[:20], content, tags_json, importance),
        )
        self.conn.commit()
        tlog(f"[secret_order] create id={cur.lastrowid} minister={minister_name} title={title[:20]}")
        return cur.lastrowid  # type: ignore[return-value]

    def upsert_secret_order(
        self,
        state: GameState,
        minister_name: str,
        title: str,
        content: str,
        tags: List[str],
        importance: int = 4,
        deadline_months: int = 0,
    ) -> Tuple[int, bool]:
        """同一承办大臣已有 active 密令 → 更新其要旨(title/content/tags/限期)并记一条
        「奉旨更新」进展；否则新建。返回 (order_id, was_update)。
        补 CLI 后端无 function-calling 的缺口：原靠大臣 function-call 改密令，现失效；
        再次下密令给同一承办人即更新已有条，而非建重复（限期=0 表示不动原限期）。"""
        existing = self.conn.execute(
            "SELECT id FROM secret_orders WHERE minister_name=? AND status='active' ORDER BY id DESC LIMIT 1",
            (minister_name,),
        ).fetchone()
        if existing is None:
            oid = self.create_secret_order(
                state, minister_name, title, content, tags, importance, deadline_months
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
    ) -> bool:
        """按**精确 id** 更新 active 密令要旨（title/content/tags/限期），记一条「奉旨更新」进展。
        返回是否更新（id 存在且状态为 active）。

        与 upsert_secret_order 的区别：upsert 按「该大臣最新 active」改，会话动作「更新」已解析出
        确切 target id 时必须走本方法，否则大臣有多条 active 密令会改错条（CMR F1）。
        tags=None 保留原标签（会话更新不带 tags 时不清空）；传 list 则覆盖。"""
        row = self.conn.execute(
            "SELECT status, tags FROM secret_orders WHERE id=?", (int(order_id),)
        ).fetchone()
        if row is None or row["status"] != "active":
            return False
        tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else (row["tags"] or "[]")
        deadline = max(0, min(int(deadline_months or 0), 36))
        if deadline:
            self.conn.execute(
                "UPDATE secret_orders SET title=?, content=?, tags=?, due_turn=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title[:20], content, tags_json, int(state.turn) + deadline, int(order_id)),
            )
        else:
            self.conn.execute(
                "UPDATE secret_orders SET title=?, content=?, tags=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title[:20], content, tags_json, int(order_id)),
            )
        self.conn.commit()
        tlog(f"[secret_order] update id={order_id} title={title[:20]}")
        self.update_secret_order_progress(int(order_id), f"奉旨更新密令要旨：{content[:60]}", state.year, state.period)
        return True

    def list_secret_orders(
        self,
        status: Optional[str] = None,
        minister_name: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if minister_name:
            clauses.append("minister_name = ?")
            params.append(minister_name)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM secret_orders {where} ORDER BY id DESC",
            params,
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "turn_issued": int(r["turn_issued"]),
                "due_turn": int(r["due_turn"] if "due_turn" in r.keys() else 0),
                "year_issued": int(r["year_issued"]),
                "period_issued": int(r["period_issued"]),
                "minister_name": r["minister_name"],
                "title": r["title"],
                "content": r["content"],
                "tags": json.loads(r["tags"] or "[]"),
                "importance": int(r["importance"]),
                "status": r["status"],
                "result": r["result"] or "",
                "sim_note": (r["sim_note"] if "sim_note" in r.keys() else "") or "",
                "turn_closed": r["turn_closed"],
            }
            for r in rows
        ]

    def get_active_secret_orders_for_minister(self, minister_name: str) -> List[Dict[str, object]]:
        """返回该大臣名下未结案密令（active + pending_review）。done/failed 已结案不再返回。"""
        active = self.list_secret_orders(status="active", minister_name=minister_name)
        pending = self.list_secret_orders(status="pending_review", minister_name=minister_name)
        return active + pending

    def close_secret_order(
        self,
        order_id: int,
        status: str,
        result: str,
        turn_closed: int,
        *,
        commit: bool = True,
    ) -> None:
        self.conn.execute(
            """
            UPDATE secret_orders
            SET status = ?, result = ?, turn_closed = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, result, turn_closed, int(order_id)),
        )
        if commit:
            self.conn.commit()
        tlog(f"[secret_order] close id={order_id} status={status}")

    def submit_secret_order_for_review(self, order_id: int, claim: str, year: int, period: int) -> bool:
        """大臣提交密令待推演核议：active → pending_review。
        claim 按月戳追加进 result 时间线（与 progress 同列，但带 "[提交核议]" 标记），
        让推演看时同时知道大臣自述。仅 active 状态可提交。"""
        row = self.conn.execute(
            "SELECT status FROM secret_orders WHERE id = ?", (int(order_id),)
        ).fetchone()
        if not row or row["status"] != "active":
            return False
        stamp = f"〔{period_label(year, period)}〕[提交核议] "
        note = (claim or "").strip()
        prev = self.conn.execute(
            "SELECT result FROM secret_orders WHERE id = ?", (int(order_id),)
        ).fetchone()["result"] or ""
        lines = [ln for ln in prev.split("\n") if ln.strip()]
        lines.append(f"{stamp}{note[:300]}")
        self.conn.execute(
            """
            UPDATE secret_orders
            SET status = 'pending_review', result = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ("\n".join(lines), int(order_id)),
        )
        self.conn.commit()
        tlog(f"[secret_order] submit_for_review id={order_id} claim={note[:60]!r}")
        return True

    def _has_secret_order_period_line(self, order_id: int, column: str, year: int, period: int) -> bool:
        """本年月该列是否已有一行（用于一回合一步闸门）。"""
        stamp = f"〔{period_label(year, period)}〕"
        row = self.conn.execute(
            f"SELECT {column} AS v FROM secret_orders WHERE id = ?", (int(order_id),)
        ).fetchone()
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
        row = self.conn.execute(
            f"SELECT {column} AS v FROM secret_orders WHERE id = ? AND status = 'active'",
            (int(order_id),),
        ).fetchone()
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
        self.conn.execute(
            f"UPDATE secret_orders SET {column} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("\n".join(lines), int(order_id)),
        )
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
        ok = self._append_secret_order_line(
            order_id,
            "result",
            progress_note,
            year,
            period,
            reject_if_same_period=False,
            commit=commit,
        )
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
        self._append_secret_order_line(order_id, "sim_note", sim_note, year, period, commit=commit)
        tlog(f"[secret_order] sim_note id={order_id} note={sim_note[:40]!r}")

    def rush_secret_order(
        self,
        order_id: int,
        state: GameState,
        deadline_months: int = 1,
        reason: str = "",
    ) -> Dict[str, object]:
        """缩短 active 密令期限。deadline_months<=0 表示本月立即送核议。"""
        row = self.conn.execute(
            "SELECT id, title, status, result, due_turn FROM secret_orders WHERE id = ?",
            (int(order_id),),
        ).fetchone()
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
        why = (reason or "").strip()[:120] or "奉旨加急"
        prev = row["result"] or ""
        lines = [ln for ln in prev.split("\n") if ln.strip()]
        if months <= 0:
            lines.append(f"{stamp}[奉旨即核] {why}；本月即移交密旨核议。")
            self.conn.execute(
                """
                UPDATE secret_orders
                SET status = 'pending_review', due_turn = ?, result = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(state.turn), "\n".join(lines), int(order_id)),
            )
            status = "pending_review"
            due_turn = int(state.turn)
        else:
            due_turn = target_turn if old_due <= 0 else min(old_due, target_turn)
            lines.append(f"{stamp}[奉旨加急] {why}；御限改为 {months} 个月内核议。")
            self.conn.execute(
                """
                UPDATE secret_orders
                SET due_turn = ?, result = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (due_turn, "\n".join(lines), int(order_id)),
            )
            status = "active"
        self.conn.commit()
        tlog(f"[secret_order] rush id={order_id} old_due={old_due} due={due_turn} status={status}")
        return {"id": int(order_id), "title": row["title"], "status": status, "due_turn": due_turn}

    def get_secret_order(self, order_id: int) -> Optional[Dict[str, object]]:
        """单查一条密令（任意状态），给承办人查进度工具用。不存在返回 None。"""
        r = self.conn.execute(
            "SELECT * FROM secret_orders WHERE id = ?", (int(order_id),)
        ).fetchone()
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
        """把到期 active 密令自动转入 pending_review，保证当月推演必须给终判。"""
        rows = self.conn.execute(
            """
            SELECT id, title, result FROM secret_orders
            WHERE status = 'active' AND due_turn > 0 AND due_turn <= ?
            ORDER BY id
            """,
            (int(state.turn),),
        ).fetchall()
        submitted: List[Dict[str, object]] = []
        for row in rows:
            stamp = f"〔{period_label(state.year, state.period)}〕[期限届满] "
            note = "御限已至，移交月末密旨核议；据既有查办、风声与盘面定成败。"
            prev = row["result"] or ""
            lines = [ln for ln in prev.split("\n") if ln.strip()]
            if not any("[期限届满]" in ln for ln in lines):
                lines.append(f"{stamp}{note}")
            self.conn.execute(
                """
                UPDATE secret_orders
                SET status = 'pending_review', result = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ("\n".join(lines), int(row["id"])),
            )
            submitted.append({"id": int(row["id"]), "title": row["title"]})
        if rows:
            self.conn.commit()
            tlog(f"[secret_order] auto_submit_due count={len(submitted)} ids={[x['id'] for x in submitted]}")
        return submitted

    def get_secret_orders_by_keywords(
        self, keywords: List[str], limit: int = 5, current_turn: int = 0
    ) -> List[Dict[str, object]]:
        """检索进行中（active）密令，tags LIKE 匹配，供推演 secret_orders 字段注入。
        完结/失败密令靠 event_memory（chat_message 来源）进入 relevant_memories，不在此返回。"""
        if not keywords:
            return self.list_secret_orders(status="active")[:limit]
        like_clauses = " OR ".join(["tags LIKE ?" for _ in keywords])
        like_params = [f"%{k}%" for k in keywords]
        rows = self.conn.execute(
            f"""
            SELECT * FROM secret_orders
            WHERE status = 'active' AND ({like_clauses})
            ORDER BY importance DESC, id DESC
            LIMIT ?
            """,
            like_params + [limit],
        ).fetchall()
        if not rows:
            return self.list_secret_orders(status="active")[:limit]
        return [
            {
                "id": int(r["id"]),
                "turn_issued": int(r["turn_issued"]),
                "year_issued": int(r["year_issued"]),
                "period_issued": int(r["period_issued"]),
                "minister_name": r["minister_name"],
                "title": r["title"],
                "content": r["content"],
                "tags": json.loads(r["tags"] or "[]") if isinstance(r["tags"], str) else (r["tags"] or []),
                "importance": int(r["importance"]),
                "status": r["status"],
                "result": r["result"] or "",
            }
            for r in rows
        ]

    # ----- chat_messages 补充查询 -----

    def get_chat_messages_for_turn(self, turn: int) -> Dict[str, List[Dict[str, str]]]:
        """查当月所有召对，按大臣分组，供 chat_memory agent 按人提取。"""
        rows = self.conn.execute(
            "SELECT minister_name, role, content FROM chat_messages WHERE turn = ? ORDER BY id",
            (int(turn),),
        ).fetchall()
        result: Dict[str, List[Dict[str, str]]] = {}
        for row in rows:
            result.setdefault(row["minister_name"], []).append(
                {"role": row["role"], "content": row["content"]}
            )
        return result

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
        cur = self.conn.execute(f"SELECT * FROM {table} ORDER BY {pk}")
        return [dict(r) for r in cur.fetchall()]

    def _admin_valid_cols(self, table: str) -> set:
        return {c["name"] for c in self.admin_columns(table)}

    def admin_upsert(self, table: str, values: Dict[str, object]) -> Dict[str, object]:
        """按主键 INSERT OR REPLACE，返回落库后的行。只接受表内有的列。"""
        pk = self.admin_check_table(table)
        valid = self._admin_valid_cols(table)
        data = {k: v for k, v in values.items() if k in valid}
        if pk not in data or data[pk] in (None, ""):
            raise ValueError(f"缺主键 {pk}")
        cols = list(data.keys())
        placeholders = ",".join("?" for _ in cols)
        collist = ",".join(cols)
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} ({collist}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        # 国库/内库同时落在 economy_accounts.balance，load_state 会用后者盖回 metrics。
        # 只改 metrics 表会在下回合被覆盖，故此处同步 economy_accounts。
        if table == "metrics" and data.get("key") in ("国库", "内库") and "value" in data:
            self.conn.execute(
                "UPDATE economy_accounts SET balance = ? WHERE account = ?",
                (int(data["value"]), data["key"]),
            )
        self.conn.commit()
        row = self.conn.execute(f"SELECT * FROM {table} WHERE {pk}=?", (data[pk],)).fetchone()
        return dict(row) if row else {}

    def admin_delete(self, table: str, pk_value: object) -> int:
        """按主键删行，返回受影响行数。"""
        pk = self.admin_check_table(table)
        cur = self.conn.execute(f"DELETE FROM {table} WHERE {pk}=?", (pk_value,))
        self.conn.commit()
        return cur.rowcount

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
