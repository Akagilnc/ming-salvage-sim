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

# 一回合的时段单位字。改此处即可全局切换回合语义（月/旬/季）；
# prompts 用占位符 {{TURN_UNIT}}，代码渲染用 TURN_UNIT 变量。
TURN_UNIT = "月"

REGION_SCORE_FIELDS = ("public_support", "unrest", "gentry_resistance", "military_pressure")
REGION_QUANTITY_FIELDS = ("population", "registered_land", "hidden_land", "tax_per_turn", "grain_security")
REGION_TEXT_FIELDS = ("natural_disaster", "human_disaster", "status", "controlled_by")
# fiscal JSON 子字段白名单（0-100量表，存在 regions.fiscal 列里）
FISCAL_SCORE_FIELDS = ("corruption",)
ARMY_SCORE_FIELDS = ("supply", "morale", "training", "equipment", "arrears", "mobility", "loyalty")
ARMY_QUANTITY_FIELDS = ("manpower", "maintenance_per_turn")
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
}
ARMY_FIELD_LABELS = {
    "station": "驻扎地",
    "commander": "统帅",
    "controller": "主管",
    "troop_type": "兵种",
    "manpower": "人数",
    "maintenance_per_turn": "维护费",
    "supply": "补给",
    "morale": "士气",
    "training": "训练",
    "equipment": "装备",
    "arrears": "欠饷",
    "mobility": "机动",
    "loyalty": "忠诚",
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
    "维护费": "maintenance_per_turn",
    "军费": "maintenance_per_turn",
    "补给": "supply",
    "粮饷": "supply",
    "士气": "morale",
    "军心": "morale",
    "训练": "training",
    "操练": "training",
    "装备": "equipment",
    "器械": "equipment",
    "欠饷": "arrears",
    "机动": "mobility",
    "忠诚": "loyalty",
    "听命": "loyalty",
    "状态": "status",
    "归属": "owner_power",
    "所属": "owner_power",
    "势力": "owner_power",
    "原因": "reason",
    "reason": "reason",
}
EXIT_COMMANDS = {"exit", "退出游戏", "退出", "exit game"}
COURT_BREAK_COMMANDS = {"q", "quit", "退朝", "下朝"}
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
