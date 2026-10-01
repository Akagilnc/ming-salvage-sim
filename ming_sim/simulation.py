"""声明形状与字段契约：EMPTY_EXTRACTION / aliases / sanitize helpers。L7。"""

from __future__ import annotations

from typing import Dict, List, Mapping


ITEM_FIELD_ALIASES = {
    "account": "account", "账户": "account",
    "direction": "direction", "方向": "direction",
    "display": "display", "显示名": "display", "名称": "display",
    "init_value": "init_value", "初值": "init_value", "初始值": "init_value",
    "delta": "delta", "增量": "delta",
    "category": "category", "分类": "category",
    "reason": "reason", "原因": "reason",
    "purpose": "purpose", "用途": "purpose",
    "target_kind": "target_kind", "目标类型": "target_kind",
    "target_id": "target_id", "目标编号": "target_id", "目标id": "target_id",
    "key": "key", "键": "key",
    "issue_id": "issue_id", "局势编号": "issue_id",
    "delta_bar": "delta_bar", "进度增量": "delta_bar",
    "stage_text": "stage_text", "阶段": "stage_text",
    "narrative": "narrative", "叙述": "narrative",
    "inertia_delta": "inertia_delta", "惯性增量": "inertia_delta",
    "origin_kind": "origin_kind", "来源类型": "origin_kind",
    "origin_ref": "origin_ref", "来源引用": "origin_ref", "诏书引用": "origin_ref",
    "affair_declaration": "affair_declaration", "事务声明": "affair_declaration",
    # #649 人口守恒转移 item 字段（canonical 白名单见 constants.POPULATION_TRANSFER_FIELDS）
    "source": "source", "源": "source", "源阶级": "source",
    "target": "target", "目标": "target", "目标阶级": "target",
    "amount": "amount", "数额": "amount", "口数": "amount",
    # #652 投贼吸收 item（region_id 别名见下方 surcharge 段共用）
    "requested_count": "requested_count", "请求口数": "requested_count",
    "请求人数": "requested_count", "拟吸口数": "requested_count",
    "power_id": "power_id", "势力编号": "power_id", "势力id": "power_id",
    # #649 §1.4：class_delta 人口键 canonical 化，使 _apply_class_dict population guard
    # 对中英文拼写统一整项拒收（人口只经 population_transfers 守恒转移变动）。
    "population": "population", "人口": "population",
    # #622：旨外恶果/受益同列标记（效果行注解，非平行轨）
    # #1260：别名表全仓一份——flows/due_review 读端改调 read_beyond_intent_raw，禁手抄子集。
    "beyond_intent": "beyond_intent", "旨外": "beyond_intent",
    "旨外标记": "beyond_intent", "旨外恶果": "beyond_intent",
    "id": "id", "编号": "id",
    "kind": "kind", "类型": "kind",
    "title": "title", "标题": "title",
    "bar_value": "bar_value", "当前进度": "bar_value",
    "expected_months": "expected_months", "预计月数": "expected_months",
    "end_turn": "end_turn", "到期回合": "end_turn", "到期月": "end_turn",
    "commitment_kind": "commitment_kind", "承诺类型": "commitment_kind", "承诺标记": "commitment_kind",
    "resolve_condition": "resolve_condition", "解决条件": "resolve_condition",
    "stop_condition": "stop_condition", "停止条件": "stop_condition",
    "fail_condition": "fail_condition", "失败条件": "fail_condition",
    "ongoing_effects": "ongoing_effects", "持续效果": "ongoing_effects",
    "effect_on_resolve": "effect_on_resolve", "解决效果": "effect_on_resolve",
    "effect_on_fail": "effect_on_fail", "失败效果": "effect_on_fail",
    "cancellable": "cancellable", "可撤销": "cancellable",
    "metrics": "metrics", "国势": "metrics",
    "economy": "economy", "钱粮": "economy",
    "factions": "factions", "派系": "factions",
    "buildings": "buildings", "建筑": "buildings",
    # 帝国修正（旧称遗产）子字段
    "legacy": "legacy", "帝国修正": "legacy", "遗产": "legacy",
    "duration": "duration", "时长": "duration",
    "modifiers": "modifiers", "修正": "modifiers",
    "narrative_hint": "narrative_hint", "叙事提示": "narrative_hint",
    # 帝国修正的 regions/armies 维度块（值是 {entity_id: {field: pct}}，原样透传）
    "regions": "regions", "地区": "regions",
    "armies": "armies", "军队": "armies",
    "action": "action", "动作": "action",
    "region_id": "region_id", "地区编号": "region_id",
    "任所": "region_id", "辖区": "region_id", "任所编号": "region_id",
    "monthly_amount": "monthly_amount", "月增额": "monthly_amount", "月额": "monthly_amount",
    "building_id": "building_id", "建筑编号": "building_id",
    "category": "category", "类别": "category",
    "level": "level", "等级": "level",
    "condition": "condition", "完好": "condition",
    "maintenance": "maintenance", "维护费": "maintenance",
    "risk": "risk", "风险": "risk",
    "output_metric": "output_metric", "产出去向": "output_metric",
    "output_amount": "output_amount", "产出量": "output_amount",
    "applied_cost": "applied_cost", "已付代价": "applied_cost",
    "name": "name", "姓名": "name", "名称": "name",
    "new_office": "new_office", "新官职": "new_office",
    "new_office_type": "new_office_type", "新官署类别": "new_office_type",
    "faction": "faction", "派系": "faction",
    "status": "status", "状态": "status",
    "office": "office", "位号": "office", "官职": "office",
    "office_type": "office_type", "官署类别": "office_type",
    "approved": "approved", "准许": "approved",
    "order_id": "order_id", "密令编号": "order_id",
    "fidelity": "fidelity", "执行态": "fidelity", "state": "fidelity",
    "sim_note": "sim_note", "推演备注": "sim_note",
    "disclosed": "disclosed", "泄漏结论": "disclosed",
    "result": "result", "结果": "result",
    "dossier_id": "dossier_id", "案卷编号": "dossier_id",
    "target_dossier_id": "target_dossier_id", "所指案卷": "target_dossier_id",
    "accuser_name": "accuser_name", "检举人": "accuser_name",
    "subject_name": "subject_name", "被检举人": "subject_name",
    "memorial_text": "memorial_text", "弹章正文": "memorial_text",
    "body": "body", "正文": "body",
    "outcome": "outcome", "执行结果": "outcome",
    "note": "note", "执行说明": "note",
    "arrived_amount": "arrived_amount", "实抵": "arrived_amount", "到银": "arrived_amount",
    "loss_amount": "loss_amount", "折损": "loss_amount",
    "holder_id": "holder_id", "授予对象": "holder_id", "持有人": "holder_id",
    "privilege": "privilege", "权项": "privilege",
    "scope": "scope", "事域": "scope",
    "authority_id": "authority_id", "授权编号": "authority_id",
    "effective_turn": "effective_turn", "生效回合": "effective_turn",
    "expires_turn": "expires_turn", "失效回合": "expires_turn",
    "character_id": "character_id", "人物": "character_id",
    "tier": "tier", "档位": "tier",
    "role": "role", "职分": "role",
    "delegator_id": "delegator_id", "委派人": "delegator_id",
    "stance": "stance", "立场": "stance",
    "action": "action", "行动": "action",
    "impact": "impact", "影响": "impact",
    "intent": "intent", "意图": "intent",
    "satisfaction": "satisfaction", "满意": "satisfaction",
    "leverage": "leverage", "影响力": "leverage", "势力": "leverage",
    # new_armies 子字段（建军）
    "owner_power": "owner_power", "归属": "owner_power", "所属": "owner_power",
    # character_power_changes 子字段（人物易主）
    "new_power": "new_power", "新势力": "new_power",
    "station": "station", "驻扎地": "station", "驻地": "station",
    "station_region": "station_region", "实际驻地": "station_region", "驻地省": "station_region",
    "theater": "theater", "战区": "theater",
    "commander": "commander", "统帅": "commander", "统将": "commander", "主将": "commander",
    "controller": "controller", "主管": "controller",
    "troop_type": "troop_type", "兵种": "troop_type",
    "manpower": "manpower", "人数": "manpower", "兵力": "manpower",
    "supply": "supply", "补给": "supply", "粮饷": "supply",
    "morale": "morale", "士气": "morale",
    "training": "training", "训练": "training",
    "equipment": "equipment", "装备": "equipment",
    "arrears": "arrears", "欠饷": "arrears",
    "pay_source_region": "pay_source_region", "饷源省": "pay_source_region",
    "province_pay_share": "province_pay_share", "省份额": "province_pay_share", "省份额比例": "province_pay_share",
    "central_pay_share": "central_pay_share", "中央份额": "central_pay_share", "中央份额比例": "central_pay_share",
    "is_tusi": "is_tusi", "土司": "is_tusi",
    "self_funded_pay": "self_funded_pay", "自养军饷": "self_funded_pay",
    "mobility": "mobility", "机动": "mobility",
    "loyalty": "loyalty", "忠诚": "loyalty",
}

EMPTY_EXTRACTION: Dict[str, object] = {
    "metric_delta": {},
    "economy_moves": [],
    "faction_delta": {},
    "class_delta": {},
    "population_transfers": [],  # #649/0087：人口守恒转移（单记录双写，源减目标增）
    "surcharge_decrees": [],  # #650/0089 明渠：下旨加派（逐省累积账，月额万两、负=停征）
    "region_delta": {},
    "army_delta": {},
    "new_armies": [],
    "power_updates": {},
    "bandit_absorptions": [],  # #652/0087：流民投贼吸收请求（吃池顶→实力正增）
    "world_advance": {},
    "issue_advances": [],
    "new_issues": [],
    "事件结局": {},
    "cancels": [],
    "close_issues": [],
    "fiscal_changes": [],
    "fiscal_creates": [],
    "fiscal_removes": [],
    "office_changes": [],
    "appointments": [],
    "character_status_changes": [],
    "character_power_changes": [],
    "人物变更": [],
    "secret_order_updates": [],
    "covert_exec_selections": [],
    "dossier_executions": [],
    "dossier_participants": [],
    "secret_dossier_participants": [],
    "dossier_reconciliations": [],
    "faction_denunciations": [],
    "authority_changes": [],
    "dossier_progress_reports": [],
    "emperor_fate": None,  # 已声明的皇帝终态。abdicate/suicide 保留原状态号；被废/暴毙及其它非空声明同样终局；null 不终局
    "relation_edge_events": [],  # #633/ADR 0082 结算口：邸报大臣互动边事件
    "affair_declarations": [],
}

def read_beyond_intent_raw(item: object) -> object:
    """#1260 旨外别名读取单源：真源=ITEM_FIELD_ALIASES 中映射到 beyond_intent 的键。

    返回第一个在场别名的原值；皆无 → None。不判真假（coerce 归写端/读端）。
    flows 嵌套通道与 due_review 效果行共用，禁再手抄 旨外 子集。
    """
    if not isinstance(item, Mapping):
        return None
    # 稳定顺序：canonical 键优先，其余按别名表声明序。
    aliases = [
        key for key, canon in ITEM_FIELD_ALIASES.items()
        if canon == "beyond_intent"
    ]
    ordered: List[str] = []
    if "beyond_intent" in aliases:
        ordered.append("beyond_intent")
    for key in aliases:
        if key not in ordered:
            ordered.append(key)
    for key in ordered:
        if key in item:
            return item[key]
    return None

def _canonical_item_fields(value: object) -> object:
    if isinstance(value, list):
        return [_canonical_item_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        ITEM_FIELD_ALIASES.get(str(key).strip(), str(key).strip()): _canonical_item_fields(val)
        for key, val in value.items()
    }
