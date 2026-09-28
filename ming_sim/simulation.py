"""声明形状与字段契约：EMPTY_EXTRACTION / aliases / sanitize helpers。L7。"""

from __future__ import annotations

from typing import Dict, List, Mapping

from ming_sim.token_stats import tlog


TOP_LEVEL_ALIASES = {
    "国势变化": "metric_delta",
    "钱粮收支": "economy_moves",
    "财政制度变化": "fiscal_changes",
    "新立月度收支": "fiscal_creates",
    "裁撤月度收支": "fiscal_removes",
    "派系变化": "faction_delta",
    "阶级变化": "class_delta",
    "人口转移": "population_transfers",
    "流民转移": "population_transfers",
    "加派": "surcharge_decrees",
    "加派旨": "surcharge_decrees",
    "地区变化": "region_delta",
    "军队变化": "army_delta",
    "势力变化": "power_updates",
    "流民投贼": "bandit_absorptions",
    "投贼吸收": "bandit_absorptions",
    "建军": "new_armies",
    "新建军队": "new_armies",
    "外交态度": "world_advance",
    "四方动向": "world_advance",
    "局势推进": "issue_advances",
    "新立局势": "new_issues",
    "事件结局": "事件结局",
    "event_outcomes": "事件结局",
    "撤销局势": "cancels",
    "结案局势": "close_issues",
    "案卷执行": "dossier_executions",
    "案卷参与人": "dossier_participants",
    "密令案卷参与人": "secret_dossier_participants",
    "拨帑对账": "dossier_reconciliations",
    "政敌检举": "faction_denunciations",
    "检举条目": "faction_denunciations",
    "授权变更": "authority_changes",
    "人事变更": "office_changes",
    "人物状态变化": "character_status_changes",
    "人物易主": "character_power_changes",
    "后宫册封": "appointments",
    "person_changes": "人物变更",
    "人物变更": "人物变更",
    "密令副作用": "secret_order_updates",
    "密令执行态": "covert_exec_selections",
    "崇祯结局": "emperor_fate",
    "大臣互动": "relation_edge_events",
    "事务声明": "affair_declarations",
}
TOP_LEVEL_LABELS = {value: key for key, value in TOP_LEVEL_ALIASES.items()}

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
ITEM_FIELD_LABELS = {
    "account": "账户",
    "delta": "增量",
    "category": "分类",
    "reason": "原因",
    "key": "键",
    "issue_id": "局势编号",
    "delta_bar": "进度增量",
    "stage_text": "阶段",
    "narrative": "叙述",
    "inertia_delta": "惯性增量",
    "origin_kind": "来源类型",
    "origin_ref": "来源引用",
    "affair_declaration": "事务声明",
    "id": "编号",
    "kind": "类型",
    "title": "标题",
    "bar_value": "当前进度",
    "expected_months": "预计月数",
    "end_turn": "到期回合",
    "commitment_kind": "承诺类型",
    "resolve_condition": "解决条件",
    "stop_condition": "停止条件",
    "fail_condition": "失败条件",
    "ongoing_effects": "持续效果",
    "effect_on_resolve": "解决效果",
    "effect_on_fail": "失败效果",
    "cancellable": "可撤销",
    "metrics": "国势",
    "economy": "钱粮",
    "factions": "派系",
    "buildings": "建筑",
    "legacy": "帝国修正",
    "duration": "时长",
    "modifiers": "修正",
    "narrative_hint": "叙事提示",
    "action": "动作",
    "region_id": "地区编号",
    "level": "等级",
    "condition": "完好",
    "maintenance": "维护费",
    "risk": "风险",
    "output_metric": "产出去向",
    "output_amount": "产出量",
    "applied_cost": "已付代价",
    "name": "姓名",
    "new_office": "新官职",
    "new_office_type": "新官署类别",
    "faction": "派系",
    "status": "状态",
    "office": "位号",
    "office_type": "官署类别",
    "approved": "准许",
    "order_id": "密令编号",
    "sim_note": "推演备注",
    "disclosed": "泄漏结论",
    "result": "结果",
    "stance": "立场",
    "impact": "影响",
    "intent": "意图",
    "satisfaction": "满意",
    "leverage": "影响力",
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
    "emperor_fate": None,  # 崇祯结局：abdicate(退位/禅让)/suicide(自尽/殉国)/null(无)
    "relation_edge_events": [],  # #633/ADR 0082 结算口：邸报大臣互动边事件
    "affair_declarations": [],
}

MODULE_FIELDS: Dict[str, set[str]] = {
    "internal": {"metric_delta", "economy_moves", "faction_delta", "class_delta", "population_transfers", "surcharge_decrees", "region_delta", "fiscal_changes", "fiscal_creates", "fiscal_removes"},
    "military_external": {
        "army_delta", "new_armies", "power_updates", "bandit_absorptions", "world_advance",
    },
    "issues": {
        "issue_advances", "new_issues", "事件结局", "cancels", "close_issues",
        "dossier_executions", "dossier_participants", "dossier_reconciliations",
        "faction_denunciations", "authority_changes", "affair_declarations",
    },
    "personnel_secret": {
        "人物变更", "new_issues", "secret_order_updates", "covert_exec_selections",
        "dossier_progress_reports", "secret_dossier_participants", "emperor_fate",
    },
    # #633：关系档房独占边事件槽；错放进其它模块由白名单 misroute 留痕剔除。
    "relations": {"relation_edge_events"},
}

# 字段 → 首要所属模块反向图。`new_issues` 由 issues 主持，同时允许 personnel_secret
# 为经常性密令拨款产承诺 issue；misroute 留痕仍指向首要 owner，避免重复 owner 噪音。
# 用于 #63 class 2：某模块 extractor 输出里若混进「属其它模块」的字段，
# _sanitize_module_output 会按白名单静默剔除——查此图即知它本该去哪，留痕不静默吞。
_FIELD_OWNER_MODULE: Dict[str, str] = {}
for _module, _fields in MODULE_FIELDS.items():
    for _field in _fields:
        _FIELD_OWNER_MODULE.setdefault(_field, _module)


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


AUTHORITY_CHANGE_FIELD_ALIASES = {
    "op": "op",
    "action": "op",
    "动作": "op",
}


def _canonical_authority_change_fields(value: object) -> object:
    canonical = _canonical_item_fields(value)
    if not isinstance(canonical, list):
        return canonical
    return [
        {
            AUTHORITY_CHANGE_FIELD_ALIASES.get(str(key).strip(), str(key).strip()): val
            for key, val in item.items()
        } if isinstance(item, dict) else item
        for item in canonical
    ]


def canonicalize_extraction(data: Dict[str, object]) -> Dict[str, object]:
    """delta 顶层 key 中文→英文 canonical 归一 + 逐项字段归一。公有 API：driver（ADR 0004）等
    跨模块复用此入口，别引私有名（#17）。`_canonicalize_extraction` 为历史私有别名（向后兼容）。"""
    canonical: Dict[str, object] = {}
    for raw_key, value in data.items():
        key = TOP_LEVEL_ALIASES.get(str(raw_key).strip(), str(raw_key).strip())
        if key == "authority_changes":
            canonical[key] = _canonical_authority_change_fields(value)
        else:
            canonical[key] = _canonical_item_fields(value)
    return canonical


# 历史私有别名：保留既有内部/外部 `_canonicalize_extraction` 引用（#17 公有化，不破调用方）。
_canonicalize_extraction = canonicalize_extraction


def _localized_item_fields(value: object, parent_key: str = "") -> object:
    if isinstance(value, list):
        return [_localized_item_fields(item, parent_key) for item in value]
    if not isinstance(value, dict):
        return value
    localized: Dict[str, object] = {}
    for key, val in value.items():
        key_str = str(key)
        if parent_key in {"world_advance", "后金", "蒙古", "朝鲜", "流寇"} and key_str == "action":
            label = "行动"
        else:
            label = ITEM_FIELD_LABELS.get(key_str, key_str)
        localized[label] = _localized_item_fields(val, key_str)
    return localized


def _localized_extraction(data: Dict[str, object]) -> Dict[str, object]:
    return {
        TOP_LEVEL_LABELS.get(str(key), str(key)): _localized_item_fields(value, str(key))
        for key, value in data.items()
    }


def _sanitize_module_output(module: str, data: Dict[str, object]) -> Dict[str, object]:
    allowed = MODULE_FIELDS[module]
    empty = {k: v for k, v in EMPTY_EXTRACTION.items() if k in allowed}
    if not isinstance(data, dict):
        return empty
    data = _canonicalize_extraction(data)
    cleaned = dict(empty)
    for key in allowed:
        if key in data:
            cleaned[key] = data[key]
    # #63 class 2：本模块 extractor 输出里混进「属其它模块」的合法字段会被上面的白名单
    # 静默剔除（合法 delta 无声蒸发）。留痕点名键 + 它本该去的模块（不 reroute，仅 surface，
    # 保持行为不变；无主/垃圾键不报，避免噪音）。
    misrouted = {
        key: _FIELD_OWNER_MODULE[key]
        for key in data
        if key in _FIELD_OWNER_MODULE and key not in allowed
    }
    if misrouted:
        tlog(f"[extractor/{module}] 字段错放进本模块、已按白名单剔除（misroute，应属对应模块）：{misrouted}")  # #63 surface
        cleaned["_module_rejections"] = [
            {
                "rejected": True,
                "item": {"field": key, "owner_module": owner, "value": data.get(key)},
                "reason": f"字段 {key} 属于 {owner} 模块，不能由 {module} 模块落库；已拒收且不猜测改路由",
                "category": "misrouted_field",
            }
            for key, owner in sorted(misrouted.items())
        ]
    if module == "internal":
        cleaned["economy_moves"] = _clean_economy_moves(cleaned.get("economy_moves"))
        cleaned["fiscal_changes"] = _clean_fiscal_changes(cleaned.get("fiscal_changes"))
        cleaned["fiscal_creates"] = _clean_fiscal_creates(cleaned.get("fiscal_creates"))
        cleaned["fiscal_removes"] = _clean_fiscal_removes(cleaned.get("fiscal_removes"))
    if module == "military_external":
        cleaned["world_advance"] = _clean_world_advance(cleaned.get("world_advance"))
    return cleaned


def _clean_world_advance(raw: object) -> Dict[str, str]:
    """Keep diplomacy as a compact power -> stance KV, tolerating the old verbose shape."""
    cleaned: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return cleaned
    for raw_key, raw_value in raw.items():
        key = str(raw_key).strip()
        if not key or key == "summary":
            continue
        if isinstance(raw_value, dict):
            value = (
                raw_value.get("stance")
                or raw_value.get("立场")
                or raw_value.get("attitude")
                or raw_value.get("态度")
                or ""
            )
        else:
            value = raw_value
        text = str(value).strip()
        if not text or text == "无新动":
            continue
        cleaned[key] = text[:40]
    return cleaned


def _copy_item_affair_declaration(
    item: Dict[str, object], entry: Dict[str, object],
) -> None:
    """Keep the same typed 事务声明 the issues module already owns."""
    if item.get("affair_declaration") is not None:
        entry["affair_declaration"] = item["affair_declaration"]


def _clean_economy_moves(raw: object) -> List[Dict[str, object]]:
    cleaned: List[Dict[str, object]] = []
    if not isinstance(raw, list):
        return cleaned
    for item in raw:
        if not isinstance(item, dict):
            continue
        item = _canonical_item_fields(item)
        if not isinstance(item, dict):
            continue
        account = str(item.get("account") or "").strip()
        # 账户非法 / delta 非整数(含 bool/float)不再静默丢——透传该项（_canonical_item_fields
        # 已归一字段别名；坏 account/delta 的原值故意保留，供 applier 逐项拒收留痕）给 apply
        # （#14 ADR0008 决定1，校验+拒收统一在 applier，cleaner 只规范化别名、不判值）。bool/float
        # 与 applier 的 _strict_int 同约判非整数（cleaner 不引 flows 避循环，故内联同款检查）。
        raw_delta = item.get("delta")
        if raw_delta in (None, ""):
            delta, bad_int = 0, False
        elif isinstance(raw_delta, bool) or isinstance(raw_delta, float):
            delta, bad_int = 0, True
        else:
            try:
                delta, bad_int = int(raw_delta), False
            except (TypeError, ValueError):
                delta, bad_int = 0, True
        if not bad_int and delta == 0:
            continue  # 0 / 缺 delta = no-op 空占位，静默跳（无论 account，免假拒收；codex r1 线上）
        if account not in {"国库", "内库"} or bad_int:
            cleaned.append(item)
            continue
        entry: Dict[str, object] = {
            "account": account,
            "delta": delta,
            "category": str(item.get("category") or item.get("reason") or "事项")[:40],
            "reason": str(item.get("reason") or "")[:80],
        }
        purpose = str(item.get("purpose") or "").strip()
        if purpose:
            entry["purpose"] = purpose
        target_kind = str(item.get("target_kind") or "").strip()
        if target_kind:
            entry["target_kind"] = target_kind
        target_id = str(item.get("target_id") or "").strip()
        if target_id:
            entry["target_id"] = target_id
        origin_ref = str(item.get("origin_ref") or "").strip()
        if origin_ref:
            entry["origin_ref"] = origin_ref
        if "transfer_to" in item:
            entry["transfer_to"] = item["transfer_to"]
        _copy_item_affair_declaration(item, entry)
        # #622：beyond_intent 无损透传。_canonical_item_fields 已把 旨外/旨外标记/旨外恶果
        # 归一到该键；cleaner 不判值（ADR 0008 决定1），真假判定归 flows 写端
        # GameDB.coerce_beyond_intent_flag。显式 False 亦透传——在场即原值放行，
        # 缺省与 False 在 coerce 侧同归 0，cleaner 不替判官省键。
        if "beyond_intent" in item:
            entry["beyond_intent"] = item["beyond_intent"]
        cleaned.append(entry)
    return cleaned


def _clean_fiscal_changes(raw: object) -> List[Dict[str, object]]:
    cleaned: List[Dict[str, object]] = []
    if not isinstance(raw, list):
        return cleaned
    for item in raw:
        if not isinstance(item, dict):
            continue
        item = _canonical_item_fields(item)
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key and "delta" not in item:
            continue  # 非空 key 且无 delta = 无操作项,照旧滤（applier 对 delta 缺省同语义）;
            # 空 key 的垃圾项无论有无 delta 都透传 applier 记拒（cmr S3 r8 退化角）。
        # 空 key 不再静默滤——透传 applier 记拒（cmr S3 r7:driver 路有痕、引擎路无痕=同输入两判）。
        # cleaner 只做无损规范化,不吞脏（cmr S3 r1,2/2:此处曾 coerce 3.7→3/True→1、
        # 静默丢脏串——引擎真路被预消毒,applier 的拒收契约对 fiscal 失明）。
        # 无损整数串照转;脏值（float/bool/坏串/null）原样透传,由 applier 拒收留痕。
        delta = item.get("delta")
        if isinstance(delta, str):
            try:
                delta = int(delta.strip())
            except ValueError:
                pass  # 坏串透传
        if key and isinstance(delta, int) and not isinstance(delta, bool) and delta == 0:
            continue  # 非空 key 的真 int 0 = 无操作,照旧滤;空 key 垃圾项透传记拒（cmr S3 r8）
        entry = {
            "key": key,
            "delta": delta,
            "reason": str(item.get("reason") or "")[:120],
        }
        origin_ref = str(item.get("origin_ref") or "").strip()
        if origin_ref:
            entry["origin_ref"] = origin_ref
        # #1260：beyond_intent 无损透传（别名已由 _canonical_item_fields 归一）。
        if "beyond_intent" in item:
            entry["beyond_intent"] = item["beyond_intent"]
        cleaned.append(entry)
    return cleaned


_DIRECTION_NORMALIZE = {
    "income": "income", "收": "income", "收入": "income", "进账": "income",
    "expense": "expense", "支": "expense", "支出": "expense", "出账": "expense",
}


def _clean_fiscal_creates(raw: object) -> List[Dict[str, object]]:
    """LLM 推演中凭空新立的月固定收支项（税是其一种）。

    本 cleaner 只做无损规范化（direction 同义词映射、整数串照转、缺省 init_value
    归 0）+ 非法值原样透传——枚举守门唯一落点在 apply_score_extraction（applier
    拒收留痕,cmr S3 r1/r2）。税种／数值由 LLM 全权裁夺，代码不预设税种白名单。
    """
    cleaned: List[Dict[str, object]] = []
    if not isinstance(raw, list):
        return cleaned
    for item in raw:
        if not isinstance(item, dict):
            continue
        item = _canonical_item_fields(item)
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        # 空 key 不再静默滤——透传 applier 记拒（cmr S3 r7）。
        # cleaner 只做无损规范化,不吞脏（cmr S3 r1,2/2）：非法 account/direction
        # 原样透传（applier 拒收留痕,不再静默丢）;direction 同义词（收/支出）仍映射。
        account = str(item.get("account") or "").strip()
        direction_raw = str(item.get("direction") or "").strip()
        direction = _DIRECTION_NORMALIZE.get(direction_raw, direction_raw)
        # init_value 缺省/null = 合法默认 0;在场脏值（float/bool/坏串）透传给 applier 拒。
        init_value = item.get("init_value")
        if init_value is None:
            init_value = 0
        elif isinstance(init_value, str):
            try:
                init_value = int(init_value.strip())
            except ValueError:
                pass  # 坏串透传
        # 负值不再 max(0,·) 有损钳制——原样透传,applier 按脏值拒留痕（cmr S3 r3）。
        # display 默认由 applier 统一派生（归一 stem,cmr S3 r12）——cleaner 不再
        # 预填,否则引擎路抢先用 raw-key 去 _base 的旧式默认=两路两值。
        display = str(item.get("display") or "").strip()
        entry = {
            "key": key,
            "account": account,
            "direction": direction,
            "display": display,
            "init_value": init_value,
            "reason": str(item.get("reason") or "")[:120],
        }
        origin_ref = str(item.get("origin_ref") or "").strip()
        if origin_ref:
            entry["origin_ref"] = origin_ref
        # #1260：beyond_intent 无损透传（别名已由 _canonical_item_fields 归一）。
        if "beyond_intent" in item:
            entry["beyond_intent"] = item["beyond_intent"]
        cleaned.append(entry)
    return cleaned


def _clean_fiscal_removes(raw: object) -> List[Dict[str, object]]:
    """LLM 推演中彻底裁撤一个月固定收支项（罢税/裁俸）。删项只需 key。
    完全放开——含 dynamic（田赋/辽饷/盐税/商税/皇庄），后果玩家自负。落库阶段删 base+rate 两行。
    """
    cleaned: List[Dict[str, object]] = []
    if not isinstance(raw, list):
        return cleaned
    for item in raw:
        if not isinstance(item, dict):
            continue
        item = _canonical_item_fields(item)
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        # 空 key 不再静默滤——透传 applier 记拒（cmr S3 r7）。
        entry = {
            "key": key,
            "reason": str(item.get("reason") or "")[:120],
        }
        origin_ref = str(item.get("origin_ref") or "").strip()
        if origin_ref:
            entry["origin_ref"] = origin_ref
        # #1260：beyond_intent 无损透传（别名已由 _canonical_item_fields 归一）。
        if "beyond_intent" in item:
            entry["beyond_intent"] = item["beyond_intent"]
        cleaned.append(entry)
    return cleaned


