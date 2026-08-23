"""模块级常量：路径、单位、字段表、别名映射、控制指令集。

L1：仅依赖 ming_sim.paths（L0）做 frozen-aware 路径解析。
"""

from __future__ import annotations

import os

from ming_sim.paths import bundled_path, bundled_root

# 只读资源根：源码=仓库根，frozen=_MEIPASS。
ROOT_DIR = str(bundled_root())
CONTENT_DIR = bundled_path("content")
WRAP = 88
MONEY_UNIT = "万两"
ECONOMY_ACCOUNTS = ("国库", "内库")
SCORE_METRICS = ("民心", "皇威")

# 默认开局时点是回合坐标的单一锚点：load_state 的调试跳月、seed 开局前刻度与
# 无 game_state 时的边事件默认时点必须共同引用，避免三处字面量漂移。
DEFAULT_OPENING_YEAR = 1627
DEFAULT_OPENING_PERIOD = 10

# 案卷关联的 Python 权威枚举；DDL CHECK 仅保留为持久层约束。
DOSSIER_LINK_TYPES = frozenset({"护卫", "稽核", "接应"})

# #44 边军史实月饷锚点（两/兵·月）：ming 军 salary_rate<=0 非法（=白嫖）时的兜底率。单一真源——
# 募兵默认（db._coerce_new_salary_rate）/ 旧档迁移兜底（db._backfill_salary_rate）/ 结算咽喉
# （flows.army_needed 对 ming+有兵+rate<=0 锚定）三处共用，避免 1.5 散落多处漂移（线上 sourcery+coderabbit）。
SALARY_RATE_ANCHOR = 1.5

# 一回合的时段单位字。改此处即可全局切换回合语义（月/旬/季）；
# prompts 用占位符 {{TURN_UNIT}}，代码渲染用 TURN_UNIT 变量。
TURN_UNIT = "月"

REGION_SCORE_FIELDS = ("public_support", "unrest", "gentry_resistance", "military_pressure")
REGION_QUANTITY_FIELDS = ("population", "registered_land", "hidden_land", "tax_per_turn", "grain_security")
REGION_TEXT_FIELDS = ("natural_disaster", "human_disaster", "status", "controlled_by")
# fiscal JSON 子字段白名单（0-100量表，存在 regions.fiscal 列里）
FISCAL_SCORE_FIELDS = ("corruption",)
ARMY_SCORE_FIELDS = ("supply", "morale", "training", "equipment", "arrears", "mobility", "loyalty",
                     "firearm_equipment", "cannon_equipment")
ARMY_QUANTITY_FIELDS = ("manpower",)  # #173：maintenance_per_turn 列已删（月饷由 army_needed 按兵力派生）
ARMY_TEXT_FIELDS = ("station", "commander", "controller", "troop_type", "status", "owner_power")
BUILDING_CATEGORIES = ("财政", "军事", "民生", "科技", "交通", "内廷")
BUILDING_OUTPUT_METRICS = ("国库", "内库", "民心", "皇威", "")
BUILDING_SCORE_FIELDS = ("condition", "risk")
BUILDING_QUANTITY_FIELDS = ("level", "maintenance", "output_amount")  # level 钳 1-5
BUILDING_TEXT_FIELDS = ("name", "output_metric", "status")
BUILDING_FIELD_LABELS = {
    "name": "名称",
    "category": "类别",
    "level": "等级",
    "condition": "完好",
    "maintenance": "维护费",
    "risk": "风险",
    "output_metric": "产出去向",
    "output_amount": "产出量",
    "status": "状态",
}
BUILDING_FIELD_ALIASES = {
    **{field: field for field in BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS + BUILDING_TEXT_FIELDS},
    "名称": "name",
    "等级": "level",
    "规模": "level",
    "完好": "condition",
    "维护费": "maintenance",
    "维护": "maintenance",
    "风险": "risk",
    "产出去向": "output_metric",
    "产出量": "output_amount",
    "产出": "output_amount",
    "状态": "status",
    "原因": "reason",
    "reason": "reason",
}
POWER_SCORE_FIELDS = ("leverage", "satisfaction", "military_strength", "cohesion", "supply")
POWER_TEXT_FIELDS = ("leader", "stance", "agenda", "status", "last_action")
CHARACTER_TEXT_FIELDS = (
    "office", "office_type", "faction", "style", "status", "status_reason",
    "reason_code", "power_id", "location", "transit_to",
)
POWER_FIELD_LABELS = {
    "leader": "首领",
    "stance": "立场",
    "leverage": "威望",
    "satisfaction": "顺遂",
    "military_strength": "实力",
    "cohesion": "内聚",
    "supply": "经济",
    "agenda": "所图",
    "status": "状态",
    "last_action": "近动",
}
POWER_FIELD_ALIASES = {
    **{field: field for field in POWER_SCORE_FIELDS + POWER_TEXT_FIELDS},
    "首领": "leader",
    "立场": "stance",
    "威胁": "leverage",
    "威望": "leverage",
    "影响力": "leverage",
    "顺遂": "satisfaction",
    "满意": "satisfaction",
    "兵势": "military_strength",
    "实力": "military_strength",
    "军势": "military_strength",
    "军事力量": "military_strength",
    "内聚": "cohesion",
    "凝聚": "cohesion",
    "粮饷": "supply",
    "经济": "supply",
    "补给": "supply",
    "所图": "agenda",
    "意图": "agenda",
    "状态": "status",
    "近动": "last_action",
    "近况": "last_action",
    "最近行动": "last_action",
    "原因": "reason",
    "reason": "reason",
}
REGION_FIELD_LABELS = {
    "population": "人口",
    "public_support": "民心",
    "unrest": "动乱",
    "natural_disaster": "天灾",
    "human_disaster": "人祸",
    "registered_land": "田亩",
    "hidden_land": "隐田",
    "tax_per_turn": "税收",
    "grain_security": "粮食",
    "gentry_resistance": "士绅阻力",
    "military_pressure": "军事压力",
    "status": "状态",
    "controlled_by": "控制",
    "corruption": "腐败度",
    "cannon": "城防炮",
}
ARMY_FIELD_LABELS = {
    "station": "驻扎地",
    "commander": "统帅",
    "controller": "主管",
    "troop_type": "兵种",
    "manpower": "人数",
    "supply": "补给",
    "morale": "士气",
    "training": "训练",
    "equipment": "装备",
    "arrears": "欠饷",
    "province_pay_arrears": "省源欠饷",
    "central_pay_arrears": "中央欠饷",
    "pay_source_region": "饷源省",
    "province_pay_share": "省份额",
    "central_pay_share": "中央份额",
    "is_tusi": "土司",
    "self_funded_pay": "自养军饷",
    "mobility": "机动",
    "loyalty": "忠诚",
    "firearm_equipment": "火器",
    "cannon_equipment": "随军大炮",
    "status": "状态",
    "owner_power": "归属",
}
REGION_FIELD_ALIASES = {
    **{field: field for field in REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + REGION_TEXT_FIELDS},
    "民心": "public_support",
    "动乱": "unrest",
    "粮食": "grain_security",
    "粮食安全": "grain_security",
    "士绅": "gentry_resistance",
    "士绅阻力": "gentry_resistance",
    "军事": "military_pressure",
    "军事压力": "military_pressure",
    "腐败": "corruption",
    "腐败度": "corruption",
    "人口": "population",
    "田亩": "registered_land",
    "登记田亩": "registered_land",
    "隐田": "hidden_land",
    "税收": "tax_per_turn",
    "月度税收": "tax_per_turn",
    "天灾": "natural_disaster",
    "人祸": "human_disaster",
    # 城防炮（城头红夷炮，另挂 region.cannon，上限 city_level×8）。与军队随军大炮 cannon_equipment 分域。
    "cannon": "cannon",
    "城防炮": "cannon",
    "城防大炮": "cannon",
    "状态": "status",
    "控制": "controlled_by",
    "控制权": "controlled_by",
    "归属": "controlled_by",
    "所属": "controlled_by",
    "势力": "controlled_by",
    "原因": "reason",
    "reason": "reason",
}
ARMY_FIELD_ALIASES = {
    **{field: field for field in ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS + ARMY_TEXT_FIELDS},
    "驻扎地": "station",
    "驻地": "station",
    "统帅": "commander",
    "统将": "commander",
    "主将": "commander",
    "将领": "commander",
    "主管": "controller",
    "管辖": "controller",
    "兵种": "troop_type",
    "人数": "manpower",
    "兵力": "manpower",
    "补给": "supply",
    "粮饷": "supply",
    "士气": "morale",
    "军心": "loyalty",  # ADR 0025 D1 / #313: 军心=loyalty（哗变轴），非 morale（士气/战斗轴）
    "训练": "training",
    "操练": "training",
    "装备": "equipment",
    "器械": "equipment",
    "火器": "firearm_equipment",
    "火器装备": "firearm_equipment",
    "随军大炮": "cannon_equipment",
    "大炮": "cannon_equipment",
    "大炮装备": "cannon_equipment",
    "欠饷": "arrears",
    "机动": "mobility",
    "忠诚": "loyalty",
    "听命": "loyalty",
    "状态": "status",
    "归属": "owner_power",
    "所属": "owner_power",
    "势力": "owner_power",
    "pay_source_region": "pay_source_region",
    "饷源省": "pay_source_region",
    "province_pay_share": "province_pay_share",
    "省份额": "province_pay_share",
    "省份额比例": "province_pay_share",
    "central_pay_share": "central_pay_share",
    "中央份额": "central_pay_share",
    "中央份额比例": "central_pay_share",
    "is_tusi": "is_tusi",
    "土司": "is_tusi",
    "self_funded_pay": "self_funded_pay",
    "自养军饷": "self_funded_pay",
    "原因": "reason",
    "reason": "reason",
}
EXIT_COMMANDS = {"exit", "退出游戏", "退出", "exit game"}
# #526 / #471 S10：收夜高置信封闭集（口令档确定性层；含「今日且到此」）
# 单一真源：前端/CLI 不得另复制词表或语义旁路。
COURT_BREAK_COMMANDS = {"q", "quit", "退朝", "下朝", "今日且到此"}
# #526：含糊收夜封闭集——戏内确认、不直接收夜（与高置信集互斥）
AMBIGUOUS_CLOSE_COMMANDS = {"今日就到这里吧？", "今日就到这里吧"}
# #526：留侍口令封闭集（叙事账、在场不变；「令退下」归 #500）
STAY_ATTEND_COMMANDS = {"留下听着"}
MINISTER_DISMISS_COMMANDS = {"done", "退下", "跪安", "退了", "下去"}

# 经济流水（economy_ledger）支出条目的结构化标签。
# 仅对支出（delta<0）有效；收入条目（税收/抄家入帑/纳贡）三项一律 NULL。
# flows 月固定支出（宗禄/官俸/工部/各军军饷/宫廷/建筑维护等）也一律 NULL，
# 只有 extractor 从诏书叙事抽出的 economy_moves 才填这三列。
ECONOMY_PURPOSES = {
    "补饷",   # 给军清欠饷；必须配 target_kind='army'+target_id=army_id；扣账上限 = 该军 arrears
    "其它",   # 其它一切支出（赏赐/赈灾/工程/犒赏/转账等），靠 reason 自由文本说明
}
ECONOMY_TARGET_KINDS = {
    "army",   # 给某支军（仅补饷场景必填，target_id = army_id）
}

# 人口守恒转移（#649/ADR 0087）：reason 枚举 × 合法方向对矩阵。
# 方向出阵即拒（invalid_enum）；跨省在途归 #475 预留；流民→贼兵源＝LLM 软判吃池顶，
# 不走确定性转移账、不设 reason 项（0087）。canonical 白名单字段见 DELTA_SCHEMA.md。
POPULATION_TRANSFER_REASONS: dict[str, frozenset[tuple[str, str]]] = {
    "加派": frozenset({("农民", "流民")}),          # 0087／0089 明渠
    "摊派": frozenset({("农民", "流民")}),          # 0087／0089 暗渠（0072 变形特例合流入池）
    "灾害": frozenset({("农民", "流民")}),          # 0087
    "兵灾": frozenset({("农民", "流民"), ("军户", "流民")}),  # 0087
    "逃亡": frozenset({("军户", "流民")}),          # 0087（军户逃亡）
    "回流": frozenset({("流民", "农民")}),          # 0087 出口／PRD US4 破局窄路（赈济招抚归农）
}
POPULATION_TRANSFER_FIELDS = frozenset({"source", "target", "amount", "reason", "origin_ref"})

# trigger_gate key 语法（content.py load 校验 + issues._eval_gate_key 求值共用，DRY，#12 Q3 fail-loud）：
# bare key（无 "."）须是已知 metric；点分 key 首段须是合法表名、末段可为聚合函数。
GATE_METRIC_KEYS = ("国库", "内库", "民心", "皇威")
GATE_TABLES = ("region", "army", "building", "power", "class", "faction", "character", "event")
GATE_AGG_FUNCS = ("max", "min", "sum", "avg")
