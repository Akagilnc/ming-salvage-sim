"""月末推演与打分提取：跑 simulator/extractor agent。L7。"""

from __future__ import annotations

import json
import copy
import re
import sqlite3
from types import SimpleNamespace
from typing import Callable, Dict, List, Mapping, Optional

from agno.agent import Agent

from ming_sim.agents import parse_agent_json, run_agent_stream_text, run_agent_text
from ming_sim.commitment_backlash import build_backlash_narrative_features
from ming_sim.constants import TURN_UNIT
from ming_sim.context import historical_anchor_for_month, victory_status
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.issues import (
    commitment_condition_role,
    commitment_display_text,
    commitment_progress_payload,
    fiscal_levy_memorial_estimates,
    gather_candidate_events,
    issue_to_payload,
    normalize_event_outcome_labels_or_error,
)
from ming_sim.models import GameState, loads_effect_dict, reign_period_label
from ming_sim.qualitative import (
    imperial_authority_band,
    power_band,
    progress_band,
    public_support_band,
    satisfaction_band,
)
from ming_sim.settlement_payload import (
    augment_secret_orders_with_due_commitments,
    iter_secret_order_ids,
)
from ming_sim.token_stats import tlog


TOP_LEVEL_ALIASES = {
    "国势变化": "metric_delta",
    "钱粮收支": "economy_moves",
    "财政制度变化": "fiscal_changes",
    "新立月度收支": "fiscal_creates",
    "裁撤月度收支": "fiscal_removes",
    "派系变化": "faction_delta",
    "阶级变化": "class_delta",
    "地区变化": "region_delta",
    "军队变化": "army_delta",
    "势力变化": "power_updates",
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
    "密令结案": "secret_order_closes",
    "密令执行态": "covert_exec_selections",
    "崇祯结局": "emperor_fate",
    "大臣互动": "relation_edge_events",
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


def _table(rows: List[Dict[str, object]], cols: List[str]) -> Dict[str, object]:
    """array-of-dicts → header + 二维数组。省掉每行重复的 key，体积约为 dict 形式的 1/3。"""
    return {
        "cols": cols,
        "rows": [[r.get(c) for c in cols] for r in rows],
    }


def _auto_table(rows: List[Dict[str, object]]) -> Dict[str, object]:
    """同 _table，但自动取首行 keys。空列表返回空 cols/rows。"""
    if not rows:
        return {"cols": [], "rows": []}
    cols = list(rows[0].keys())
    return _table(rows, cols)


_CHARACTER_AXIS_GATE_PATTERN = (
    r"character\.[^.]+\.(?:loyalty|ability|integrity|courage|identity|intrigue)"
    r"(?:\.(?:avg|min|max|sum))?"
)
_CHARACTER_AXIS_GATE_KEY = re.compile(rf"^{_CHARACTER_AXIS_GATE_PATTERN}$")
_CHARACTER_AXIS_LEGACY_GATE = re.compile(
    rf"^{_CHARACTER_AXIS_GATE_PATTERN}\s*(?:>=|<=|>|<|==|=)\s*-?\d+(?:\.\d+)?$"
)
_QUALITATIVE_CHARACTER_GATE = "人物属性条件由引擎按定性档位复核"
_CHARACTER_EFFECT_KEYS = ("人物变更", "person_changes", "character")
_CHARACTER_AXIS_MUTATION_FIELDS = frozenset({
    "loyalty", "ability", "integrity", "courage", "identity", "intrigue",
    "忠诚", "能力", "清廉", "胆略", "党派认同", "阴谋",
})


def _condition_has_character_axis(value: object) -> bool:
    parsed = value
    if isinstance(value, str):
        text = str(value or "").strip()
        if _CHARACTER_AXIS_LEGACY_GATE.fullmatch(text):
            return True
        if not text.startswith("{"):
            return False
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return False
    return isinstance(parsed, dict) and any(
        _CHARACTER_AXIS_GATE_KEY.fullmatch(str(key)) for key in parsed
    )


def _project_simulator_condition(value: object) -> object:
    """Hide exact character thresholds at the mixed simulator boundary."""
    parsed = value
    encoded = isinstance(value, str)
    if encoded:
        text = str(value or "").strip()
        if _CHARACTER_AXIS_LEGACY_GATE.fullmatch(text):
            return _QUALITATIVE_CHARACTER_GATE
        if not text.startswith("{"):
            return value
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return value
    if not isinstance(parsed, dict):
        return value
    projected = {
        str(key): condition
        for key, condition in parsed.items()
        if not _CHARACTER_AXIS_GATE_KEY.fullmatch(str(key))
    }
    if len(projected) == len(parsed):
        return value
    projected["人物属性条件"] = "由引擎按定性档位复核"
    return json.dumps(projected, ensure_ascii=False) if encoded else projected


def _project_simulator_current_state(metrics: object) -> Dict[str, object]:
    """#1356 / ADR 0143: 民心·皇威走 qualitative 单源；国库/内库等钱粮口径保留裸数。"""
    raw = dict(metrics or {})
    projected: Dict[str, object] = dict(raw)
    if "民心" in projected:
        projected["民心"] = public_support_band(projected["民心"])
    if "皇威" in projected:
        projected["皇威"] = imperial_authority_band(projected["皇威"])
    return projected


# season_simulator.md 钱粮诚实章：leverage<=30 → 不可写「势力熏天」。
# 阈值由代码预计算，以语义记号进 factions_brief；LLM 只消费记号、不自己数数。
_LEVERAGE_SUPPRESSION_LINE = 30
_LEVERAGE_BELOW_SUPPRESSION_MARK = "势力已跌破压制线"


def _simulator_factions_brief(db: GameDB) -> str:
    """Simulator 混合调用派系 brief：满意/势力定性 + leverage 压制线语义记号。

    #1483 / P4：玩家可见叙事输入不得进裸『满意32、势力25』。
    接口层：leverage<=30 规则确定性预计算，记号正向表述（势力已跌破压制线）。
    issues extractor 阈值裸数另走 extractor_context，不经此 brief。
    """
    rows = db.conn.execute(
        "SELECT name, satisfaction, leverage, agenda FROM factions ORDER BY name"
    ).fetchall()
    if not rows:
        return "派系未建档。"
    parts: List[str] = []
    for row in rows:
        try:
            lev = int(row["leverage"])
        except (TypeError, ValueError):
            lev = 0
        piece = (
            f"{row['name']}满意{satisfaction_band(row['satisfaction'])}、"
            f"势力{power_band(row['leverage'])}"
        )
        if lev <= _LEVERAGE_SUPPRESSION_LINE:
            piece += f"（{_LEVERAGE_BELOW_SUPPRESSION_MARK}）"
        piece += f"，所求：{row['agenda']}"
        parts.append(piece)
    return "；".join(parts)


def _population_wan_kou_label(persons: int) -> str:
    """ADR 0088/#648 玩家面投影：裸人数 → 「约N万口」定性（P4）。

    这是 LLM 输入的特征化投影（同 satisfaction_band 族），非玩家直出文本模板；
    叙事由 simulator 从此正向长出，严禁事后对 LLM 产文换算/改写（0142 零删改）。"""
    wan = int(persons) // 10000
    if wan <= 0:
        return "不足一万口"
    return f"约{wan}万口"


def _project_simulator_region_row(
    row: Dict[str, object], population_unit: str
) -> Dict[str, object]:
    """#1356: region public_support（民心）走 qualitative 单源；可数物照旧。

    #648（ADR 0088/F2）：新档（人）region population 在玩家可感 LLM 输入侧投影为
    「约N万口」定性——机面（extractor payload TSV）仍出裸人数；无标旧档（万人）
    沿 legacy 原样输出，不加换算。"""
    projected = dict(row)
    if "public_support" in projected:
        projected["public_support"] = public_support_band(projected["public_support"])
    if population_unit == POPULATION_UNIT_PERSONS and "population" in projected:
        projected["population"] = _population_wan_kou_label(int(projected["population"]))
    return projected


def _project_simulator_issue_conditions(issue: Dict[str, object]) -> Dict[str, object]:
    """Apply the simulator-only character gate + 局势进度 projection to one issue."""
    projected = dict(issue)
    has_character_gate = any(
        _condition_has_character_axis(projected.get(key))
        for key in ("结案条件", "失败条件", "resolve_condition", "fail_condition", "stop_condition")
    )
    for key in ("结案条件", "失败条件", "resolve_condition", "fail_condition", "stop_condition"):
        if key in projected:
            projected[key] = _project_simulator_condition(projected[key])
    # #1356 r6：局势进度 bar_value 裸分 → 既有 progress_band 定性档。
    if "进度" in projected:
        projected["进度"] = progress_band(projected["进度"])
    progress = projected.get("commitment_progress")
    if has_character_gate and isinstance(progress, dict):
        qualitative_progress = dict(progress)
        if "remaining_to_goal" in qualitative_progress:
            qualitative_progress["remaining_to_goal"] = "距达标仍有差距"
        projected["commitment_progress"] = qualitative_progress
    for key in (f"当前每{TURN_UNIT}效果", "成功效果", "失败效果"):
        effect = projected.get(key)
        if isinstance(effect, dict):
            projected[key] = _project_simulator_character_effect(effect)
    return projected


def _project_simulator_character_effect(effect: Dict[str, object]) -> Dict[str, object]:
    """Remove exact character-axis deltas while preserving the effect structure."""
    projected = dict(effect)
    for section in _CHARACTER_EFFECT_KEYS:
        items = projected.get(section)
        if not isinstance(items, list):
            continue
        projected[section] = [
            {
                key: value
                for key, value in item.items()
                if key not in _CHARACTER_AXIS_MUTATION_FIELDS
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
            }
            if isinstance(item, dict) else item
            for item in items
        ]
    return projected


def _talent_pool_rows(db: "GameDB", state: GameState) -> List[Dict[str, object]]:
    """ADR 0009 人才池视图（读取端闭环）：居家/致仕/削籍在世者皆可起复，带
    status + reason_code（机读）+ status_reason（可读），裁判与玩家才看得见
    「某公因忤逆案削籍居家」。simulator 盘面与 extractor 上下文共用此源、防两处漂移。
    键名沿用 offstage_ministers（prompt/dedup 已引；语义已扩为起复候选池）。

    ADR L104 池 = (active+身名分听用候铨) ∪ (offstage/retired/dismissed 在世)。active 半=
    顶替离任者（office='听用候铨'，仍 active 可即起复，S5 核心玩趣）。锚 身名分 office='听用候铨'
    （非 office_type=待铨——后者兼作分类失败 fallback、被污染，决定10/L94）。"""
    # roster scope（与 court_roster / active_ministers / tools.get_active_ministers /
    # tools.query_court_roster / registry.build_court_roster / web_app.in_talent_pool 同口径）：
    # 只放大明、非后宫、非宗藩、非未仕、非流寇，且已历史登场。否则混进非起复对象：
    # ① 流寇/后金 offstage（李自成等）——流寇按 faction 排除，招抚归明后 power_id 翻 ming
    #   （character_power_changes）、仅 power_id 闸漏（与 web_app.in_talent_pool 同 bug 类，cmr R1 A）；
    # ② 就藩宗藩（朱常洵，宗室不入仕，PR#121 隐藏宗藩——web 已挡、后端 roster 须同步，cmr R3 cross-section）；
    # ③ 未仕（史可法，未入仕非「可起复前臣」）；
    # ④ 未来才登场者（郑成功 1645 等，offstage 但尚未在世=剧透，cmr R3 gemini）。
    # 登场判据对齐 db.apply_historical_debuts（year+month），与 web in_talent_pool 一致。
    return [
        dict(r) for r in db.conn.execute(
            "SELECT name,office,office_type,faction,status,reason_code,status_reason,"
            "power_id,location,transit_to,debut_year,debut_month "
            "FROM characters WHERE (status IN ('offstage','retired','dismissed') "
            "OR (status='active' AND office='听用候铨' AND reason_code='被顶替')) "
            "AND power_id='ming' AND office_type NOT IN ('后宫','宗藩','未仕') AND faction!='流寇' "
            # debut_year/month 虽 schema NOT NULL DEFAULT 0，此处是唯一在 WHERE 比较 debut 的查询，
            # COALESCE 兜 NULL 防未来 schema 改动时静默漏人，并与 Python 侧 (… or 0) 回落一致（R3 gemini）。
            "AND NOT (COALESCE(debut_year,0) > ? OR (COALESCE(debut_year,0) = ? AND COALESCE(debut_month,0) > ?)) "
            "ORDER BY status, name",
            (state.year, state.year, state.period),
        ).fetchall()
    ]




def _army_rows_with_needed(
    db: GameDB, select_sql: str, drop: tuple[str, ...] = ("salary_rate",),
) -> List[Dict[str, object]]:
    """#173 cmr（codex high + Claude medium concur）：simulator/extractor 盘面军队行加引擎实扣
    army_needed 列（裁判/审计大臣读的「月饷」真源）。select_sql 须含 owner_power/manpower/salary_rate
    供 army_needed 计算；drop 列仅用于算、不进盘面（默认 salary_rate；调用方原本无 owner_power 的也一并
    drop 以最小化盘面列变化）。#173：maintenance_per_turn 列已删，盘面不再含维护费。"""
    from ming_sim.flows import army_needed
    if isinstance(drop, str):  # 防御：误传单字符串会被 for 逐字符迭代（线上 gemini）
        drop = (drop,)
    out: List[Dict[str, object]] = []
    for r in db.conn.execute(select_sql).fetchall():
        d = dict(r)
        d["army_needed"] = army_needed(r)
        for c in drop:
            d.pop(c, None)
        out.append(d)
    return out


def _build_transit_nudge(db: "GameDB", state: "GameState") -> List[Dict[str, object]]:
    """在途人物 nudge 列表，供 simulator 优先叙事到任（#346）。"""
    rows = db.conn.execute(
        "SELECT name, transit_to, transit_start_turn FROM characters "
        "WHERE COALESCE(transit_to, '') != '' AND status='active'"
    ).fetchall()
    result: List[Dict[str, object]] = []
    for row in rows:
        start = int(row["transit_start_turn"] or 0)
        months = (state.turn - start) if start > 0 else 0
        result.append({
            "name": str(row["name"]),
            "transit_to": str(row["transit_to"]),
            "months_in_transit": months,
        })
    return result


def project_monthly_progress_for_simulator(db: GameDB) -> List[Dict[str, object]]:
    """#569 A1: public-safe monthly progress from the #566 true source.

    Only dossier_id / turn / progress_band (and optional non-secret title_summary).
    Never memorial_text, secret body/title, or undisclosed order prose.
    """
    out: List[Dict[str, object]] = []
    for nudge in db.list_monthly_dossier_progress_nudges():
        dossier_id = int(nudge["dossier_id"])
        # title from secret payload is private — do not project as title_summary.
        for item in nudge.get("progress") or []:
            if not isinstance(item, dict):
                continue
            out.append({
                "dossier_id": dossier_id,
                "turn": int(item.get("turn") or 0),
                "progress_band": str(item.get("progress_band") or "").strip(),
            })
    return out


def build_simulator_payload(
    state: GameState,
    db: GameDB,
    decree_text: str,
    previous_narrative: str,
    deaths_this_turn: Optional[List[Dict[str, str]]] = None,
    debuts_this_turn: Optional[List[Dict[str, str]]] = None,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
    secret_orders: Optional[Dict[str, object]] = None,
    decree_dossiers: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    # #883: due commitments are public review work, unlike actual secret
    # orders.  Keep them on a separately named public rail; never pre-load
    # secret-order prose into the monthly judge.
    grouped_orders = augment_secret_orders_with_due_commitments(secret_orders, db, state)
    # Trust augment's Dict[str, list] contract — shape errors must fail loud.
    due_commitments = [
        item for group in grouped_orders.values()
        for item in group
        if item.get("entry_kind") == "due_commitment"
    ]
    active = db.list_active_issues()
    issues_payload = [
        _project_simulator_issue_conditions(
            issue_to_payload(
                row,
                db.list_recent_issue_advances(int(row["id"]), 1),
                db=db,
                state=state,
            )
        )
        for row in active
    ]
    # 帝国修正不进 simulator payload：它是纯机械的百分比修正符，由落账层自动放大/缩小增量，不进叙事。
    candidate_events = [
        {
            "id": ev.id,
            "title": ev.title,
            "kind": ev.kind,
            "summary": ev.summary,
            "interests": ev.interests,
            "is_historical": ev.trigger_year > 0,
            "resolve_condition": _project_simulator_condition(ev.resolve_condition),
            "fail_condition": _project_simulator_condition(ev.fail_condition),
            "precondition": _project_simulator_condition(ev.precondition),
        }
        for ev in gather_candidate_events(state, db)
    ]
    region_rows = [
        # #648：按档口径传单位——新档玩家面投影「约N万口」，旧档万人原样。
        _project_simulator_region_row(dict(r), db.population_unit)
        for r in db.conn.execute(
            "SELECT name,kind,population,public_support,unrest,natural_disaster,"
            "human_disaster,registered_land,hidden_land,tax_per_turn,grain_security,"
            "gentry_resistance,military_pressure,status,controlled_by,city_level,cannon,"
            "json_extract(fiscal,'$.corruption') as corruption FROM regions ORDER BY id"
        ).fetchall()
    ]
    army_rows = _army_rows_with_needed(
        db,
        "SELECT name,station,theater,commander,controller,troop_type,manpower,"
        "supply,morale,training,equipment,arrears,mobility,"
        "loyalty,firearm_equipment,cannon_equipment,status,owner_power,salary_rate "
        "FROM armies ORDER BY id",
    )
    # 在朝名单 = 目前当官的（active）：simulator 在朝盘面 + 任命查重。可起复者（居家/致仕/
    # 削籍）走 offstage_ministers 人才池，在押/流放者两份都不在（玩家下旨决定去留）。旧 status!=
    # 'offstage' 会把削籍/致仕/在押者也混进在朝名单、与人才池双重曝光自相矛盾。注：大臣 system 的
    # 现状参照名册（registry.build_court_roster）另有用途、故意含非 active 带状态标签，不在此口径。
    from ming_sim.qualitative import qualitative_character_axes

    court_rows = []
    for row in db.conn.execute(
        # roster scope：大明、非后宫、非宗藩、非未仕（#1317 r2 与 _is_summonable_court_minister /
        # web visible_in_court 同口径；宗室就藩非朝堂命官 PR#121；诸生待铨非在朝命官）。
        # #613：任别进盘面简报（character_offices；缺档按真除）。
        "SELECT c.name,c.office,c.office_type,c.faction,c.status,c.power_id,c.location,"
        "c.transit_to,c.loyalty,c.ability,c.integrity,c.courage,c.identity,"
        "COALESCE(co.appointment_tenure, '真除') AS appointment_tenure "
        "FROM characters c "
        "LEFT JOIN character_offices co ON co.character_name=c.name "
        "WHERE c.status='active' AND c.power_id='ming' "
        "AND c.office_type NOT IN ('后宫','宗藩','未仕') ORDER BY c.rowid"
    ).fetchall():
        raw = dict(row)
        raw.update(qualitative_character_axes(SimpleNamespace(**raw)))
        for field in ("loyalty", "ability", "integrity", "courage", "identity"):
            raw.pop(field)
        court_rows.append(raw)
    court_roster = _auto_table(court_rows)
    reign_label = reign_period_label(state.year, state.period)
    return {
        "year": state.year,
        "period": state.period,
        # #1344：年号纪年事实单真源；context/prompt 直喂，禁 LLM 自算
        "turn": {
            "year": state.year,
            "period": state.period,
            "turn": state.turn,
            "reign_period_label": reign_label,
        },
        "decree_text": decree_text,
        # ADR 0051/0055: structured dossier rows are the source; decree_text is
        # only a compatibility rendering derived by the settlement caller.
        "decree_dossiers": decree_dossiers or [],
        # #569 A1: same-batch public-safe progress; private memorial stays on
        # personnel_secret monthly_dossier_reports (#566).
        "monthly_progress": project_monthly_progress_for_simulator(db),
        # #569 D / #567 slot: empty until S12 wires reconciliation reads.
        "reconciliation_inputs": [],
        # #1356 r6 / ADR 0143：民心·皇威定性；国库/内库钱粮裸数保留。
        "current_state": _project_simulator_current_state(state.metrics),
        "treasury_brief": db.treasury_report(state),
        # #1483：factions_brief 回定性（P4 叙事输入）；leverage<=30 由代码预计算
        # 成「势力已跌破压制线」语义记号，禁裸数进混合调用。
        "factions_brief": _simulator_factions_brief(db),
        # 阶级总览 audience 定性；高压预警过滤在 SQL 侧用裸数。
        "classes_brief": db.class_report(audience=True),
        "powers_brief": db.power_report(exclude_self=True),
        "active_issues": issues_payload,
        "candidate_events": candidate_events,
        "fiscal_levy_memorial_estimates": fiscal_levy_memorial_estimates(state, db),
        "previous_narrative_tail": previous_narrative[-1500:] if previous_narrative else "",
        "historical_anchor": historical_anchor_for_month(state.year, state.period),
        "victory_status": victory_status(db, state),
        "regions": _auto_table(region_rows),
        "armies": _auto_table(army_rows),
        "buildings": _auto_table(db.building_payload()),
        "court_roster": court_roster,
        # ADR 0009 人才池视图（读取端闭环）：居家/致仕/削籍在世者带 reason_code，
        # 裁判与玩家看得见可起复之人。自动转 TSV（build_simulator_context 尾部兜底）。
        "offstage_ministers": _auto_table(_talent_pool_rows(db, state)),
        "deaths_this_turn": deaths_this_turn or [],
        "debuts_this_turn": debuts_this_turn or [],
        "relevant_memories": relevant_memories or [],
        "due_commitments": due_commitments,
        # LLM nudge：在途人物列表（#346）。simulator 优先产叙事到任（行止+location），
        # 代码在 pre_settle 中兜底强制（≥2月未到 → 强制；此 nudge 鼓励 LLM 主动叙事）。
        "transit_nudge": _build_transit_nudge(db, state),
        # #627：政敌检举供事实（零新增串行调用；不携真伪位/quota/烈度）
        "faction_denunciation_facts": db.build_faction_denunciation_facts(),
        # #626：承诺所系反噬——硬门只落结构化事实；玩家文案由叙事步从此特征包长出
        "commitment_backlash_facts": build_backlash_narrative_features(db),
        "data_note": (
            "盘面表（buildings/court_roster/armies/regions）在本输入的开头以 TSV 文本块给出"
            "（首行列名、tab 分隔、每行一条记录），不在本 JSON 内；本 JSON 只含其余字段"
            "（含 powers_brief/factions_brief/classes_brief 叙述串、active_issues 等）。"
            "due_commitments 是本月待复核的公开承诺（公开轨）。transit_nudge 为当前在途"
            "（transit_to 非空）人物，months_in_transit ≥1 者按惯例本月应抵达，请优先产行止叙事。"
            "faction_denunciation_facts 为派系恩怨/分叉案卷/处境/个性事实包，供朝堂弹劾叙事取材，不含真伪位。"
            "commitment_backlash_facts 为承诺所系反噬结构化事实包（源类/承诺链接/metrics），"
            "供叙事长出玩家可见文案；含与 #625 反制 bar 用语区分约束，不含成句模板。"
        ),
    }


def simulate_season_with_agno(
    agent: Agent,
    state: GameState,
    db: GameDB,
    decree_text: str,
    previous_narrative: str,
    deaths_this_turn: Optional[List[Dict[str, str]]] = None,
    debuts_this_turn: Optional[List[Dict[str, str]]] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
    on_text: Optional[Callable[[str], None]] = None,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
    secret_orders: Optional[Dict[str, object]] = None,
) -> str:
    """推演 agent: 全量盘面塞 user payload，无 tool。"""
    narrative, _payload = simulate_season_with_payload(
        agent,
        state,
        db,
        decree_text,
        previous_narrative,
        deaths_this_turn=deaths_this_turn,
        debuts_this_turn=debuts_this_turn,
        on_thinking=on_thinking,
        on_text=on_text,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders,
    )
    return narrative


def simulate_season_with_payload(
    agent: Agent,
    state: GameState,
    db: GameDB,
    decree_text: str,
    previous_narrative: str,
    deaths_this_turn: Optional[List[Dict[str, str]]] = None,
    debuts_this_turn: Optional[List[Dict[str, str]]] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
    on_text: Optional[Callable[[str], None]] = None,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
    secret_orders: Optional[Dict[str, object]] = None,
    simulator_payload: Optional[Dict[str, object]] = None,
) -> tuple[str, Dict[str, object]]:
    """推演 agent，同时返回本次推演 user payload，供 extractor 复用缓存前缀。"""
    payload = simulator_payload or build_simulator_payload(
        state, db, decree_text, previous_narrative,
        deaths_this_turn=deaths_this_turn,
        debuts_this_turn=debuts_this_turn,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders,
    )
    raw = run_agent_stream_text(
        agent,
        json.dumps({"instruction": "请根据 system 中的 simulator_payload 写本月月末奏章。"}, ensure_ascii=False),
        tag="simulator",
        on_thinking=on_thinking,
        on_text=on_text,
    )
    return raw.strip(), payload


# #633：relations（关系档房）并入同一并发装配——五模块共享同一 ThreadPoolExecutor，
# 不另建第二套编排。
EXTRACTION_MODULES = ("internal", "military_external", "issues", "personnel_secret", "relations")

EMPTY_EXTRACTION: Dict[str, object] = {
    "metric_delta": {},
    "economy_moves": [],
    "faction_delta": {},
    "class_delta": {},
    "region_delta": {},
    "army_delta": {},
    "new_armies": [],
    "power_updates": {},
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
    "secret_order_closes": [],
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
}

MODULE_FIELDS: Dict[str, set[str]] = {
    "internal": {"metric_delta", "economy_moves", "faction_delta", "class_delta", "region_delta", "fiscal_changes", "fiscal_creates", "fiscal_removes"},
    "military_external": {"army_delta", "new_armies", "power_updates", "world_advance"},
    "issues": {
        "issue_advances", "new_issues", "事件结局", "cancels", "close_issues",
        "dossier_executions", "dossier_participants", "dossier_reconciliations",
        "faction_denunciations", "authority_changes",
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


def _extractor_context_payload(
    db: GameDB,
    state: GameState,
    narrative: str,
    decree_text: str,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
    secret_orders: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    active = db.list_active_issues()

    def _issue_auto_economy(row) -> List[Dict[str, object]]:
        """该 issue 每回合 ongoing_effects 里的固定经济支出/收入。
        这些由 apply_issue_inertia_and_ongoing 程序自动落账（extractor 结算之后），
        extractor 看到此清单即知「邸报里提到的这笔是局势自动月支，已由程序扣，勿重抽 钱粮收支」。"""
        ongoing = loads_effect_dict(row["ongoing_effects"])  # 非 dict/解析失败→{}（#117 统一守）
        out: List[Dict[str, object]] = []
        _eco = ongoing.get("economy")
        for econ in (_eco if isinstance(_eco, list) else []):  # economy 值真值非 list 守卫（#117 codex）
            if not isinstance(econ, dict):  # 逐项守：econ.get 在非 dict 上抛 AttributeError
                continue
            try:
                delta = int(econ.get("delta"))
            except (TypeError, ValueError):
                continue
            if delta == 0:
                continue
            out.append({
                "账户": str(econ.get("account") or "国库"),
                "增量": delta,
                "分类": str(econ.get("category") or ""),
                "原因": str(econ.get("reason") or ""),
            })
        return out

    issues_brief: List[Dict[str, object]] = []
    for r in active:
        keys = r.keys() if hasattr(r, "keys") else []
        resolve_cond = (r["resolve_condition"] if "resolve_condition" in keys else "") or ""
        commitment_kind = (r["commitment_kind"] if "commitment_kind" in keys else "") or ""
        stop_condition = (r["stop_condition"] if "stop_condition" in keys else "") or ""
        issue = {
            "issue_id": int(r["id"]),
            "title": r["title"],
            "bar_value": int(r["bar_value"]),
            "inertia": int(r["inertia"]),
            "stage_text": r["stage_text"],
            "cancellable": r["cancellable"],
            "resolve_condition": resolve_cond or "(未填)",
            "fail_condition": (r["fail_condition"] if "fail_condition" in keys else "") or "(未填)",
            **commitment_condition_role(resolve_cond, commitment_kind),
        }
        if commitment_kind:
            issue["commitment_kind"] = commitment_kind
        if stop_condition:
            issue["stop_condition"] = stop_condition
        progress = commitment_progress_payload(db, state, r)
        if progress is not None:
            issue["commitment_progress"] = progress
            issue["待办未解进度"] = commitment_display_text(progress, r)
        issues_brief.append(issue)
    # 局势自动月支汇总（独立顶层字段，不随 active_issues 一起被 _MODULE_DROP_FIELDS 剔除）。
    # extractor 据此判重：邸报提到的局势常态月支若在此清单，是程序自动落账项，勿写 钱粮收支。
    issue_auto_economy: List[Dict[str, object]] = []
    for r in active:
        for econ in _issue_auto_economy(r):
            issue_auto_economy.append({"issue_id": int(r["id"]), "title": r["title"], **econ})
    region_rows = [
        dict(r) for r in db.conn.execute(
            "SELECT id,name,kind,population,public_support,unrest,natural_disaster,"
            "human_disaster,registered_land,hidden_land,tax_per_turn,grain_security,"
            "gentry_resistance,military_pressure,status,controlled_by,city_level,cannon,"
            "json_extract(fiscal,'$.corruption') as corruption FROM regions ORDER BY id"
        ).fetchall()
    ]
    army_rows = _army_rows_with_needed(
        db,
        "SELECT id,name,station,theater,commander,controller,troop_type,manpower,"
        "supply,morale,training,equipment,arrears,mobility,"
        "loyalty,status,owner_power,salary_rate FROM armies ORDER BY id",
        drop=("salary_rate", "owner_power"),  # extractor 盘面原无 owner_power，只新增 army_needed 列
    )
    active_ministers = [
        dict(r) for r in db.conn.execute(
            # roster scope（同 court_roster / _talent_pool_rows / tools.get_active_ministers）：
            # 大明、非后宫、非宗藩、非未仕（#1317 r2 可召单真源；PR #106 / PR#121）。
            "SELECT name,office,office_type,faction,power_id,location,transit_to "
            "FROM characters WHERE status='active' AND power_id='ming' "
            "AND office_type NOT IN ('后宫','宗藩','未仕') ORDER BY rowid"
        ).fetchall()
    ]
    # ADR 0009 人才池视图：与 simulator 盘面共用 _talent_pool_rows（防两处漂移）。
    offstage_ministers = _talent_pool_rows(db, state)
    return {
        "turn": {
            "year": state.year,
            "period": state.period,
            "turn": state.turn,
            "reign_period_label": reign_period_label(state.year, state.period),
        },
        "narrative": narrative,
        "decree_text": decree_text,
        "active_issues": issues_brief,
        "issue_auto_economy": issue_auto_economy,
        "candidate_events": [{"id": ev.id, "title": ev.title} for ev in gather_candidate_events(state, db)],
        "current_state": dict(state.metrics),
        "factions": db.faction_report(),
        "classes": db.class_report(),
        "powers": _auto_table(db.power_payload()),
        "regions": _auto_table(region_rows),
        "armies": _auto_table(army_rows),
        "buildings": _auto_table(db.building_payload()),
        "active_ministers": _auto_table(active_ministers),
        "offstage_ministers": _auto_table(offstage_ministers),
        "region_ids": [r["id"] for r in db.conn.execute("SELECT id FROM regions").fetchall()],
        "army_ids": [r["id"] for r in db.conn.execute("SELECT id FROM armies").fetchall()],
        "class_names": [r["name"] for r in db.conn.execute("SELECT DISTINCT name FROM classes ORDER BY name").fetchall()],
        "power_ids": [str(r["id"]) for r in db.conn.execute("SELECT id FROM powers").fetchall()],
        "fiscal_config": db.get_fiscal_config(),
        "relevant_memories": relevant_memories or [],
        "secret_orders": augment_secret_orders_with_due_commitments(secret_orders, db, state),
        "_format_note": "offstage_ministers（及未剔除时的盘面表）为 header+二维数组（cols 列名 + rows 数据）。",
    }


def _extractor_compat_payload(base: Dict[str, object]) -> Dict[str, object]:
    return {
        "turn": base["turn"],
        "narrative": base["narrative"],
        "decree_text": base["decree_text"],
        "active_issues": base["active_issues"],
        "issue_auto_economy": base["issue_auto_economy"],
        "candidate_events": base["candidate_events"],
        "current_state": base["current_state"],
        "factions": base["factions"],
        "classes": base["classes"],
        "powers": base["powers"],
        "regions": base["regions"],
        "armies": base["armies"],
        "buildings": base["buildings"],
        "active_ministers": base["active_ministers"],
        "offstage_ministers": base["offstage_ministers"],
        "region_ids": base["region_ids"],
        "army_ids": base["army_ids"],
        "class_names": base["class_names"],
        "power_ids": base["power_ids"],
        "fiscal_config": base["fiscal_config"],
        "relevant_memories": base["relevant_memories"],
        "secret_orders": base["secret_orders"],
        "_format_note": base["_format_note"],
    }


# module 模式专用：simulator_payload 已在同一 system 前缀给出全量盘面，这些字段同名同格式
# 重复，从补充上下文里剔除，省掉约一半 extractor system 体积。
#
# #1483：current_state/regions/active_issues 在 simulator_payload 侧已做 P4 定性投影；
# issues extractor 需要裸数做 resolve/fail 阈值对照——仅 module=='issues' 再注入
# （见 _ISSUES_THRESHOLD_FIELDS），其余 economy/military/personnel 模块不吃全量拷贝。
_MODULE_DROP_FIELDS = (
    # 同名同格式，simulator_payload 已全量给出（含 P4 定性投影后的同名轴）
    "regions", "armies", "buildings", "current_state",
    "active_issues", "candidate_events", "decree_text",
    "relevant_memories", "secret_orders",
    # 异名但同源：simulator_payload 已有等价视图，extractor prompt（score_extractor_shared.md:17、
    # personnel_secret.md:5）明确指向从 simulator_payload 读，这里的副本是死字段。
    #   active_ministers → court_roster TSV（在朝大臣）
    #   powers → powers_brief（势力态势叙述）；new_power 合法集另有 power_ids
    #   factions → factions_brief（定性 + 压制线语义记号；阈值裸数不经此）
    #   classes → classes_brief；class_delta key 取 class_names + region_ids 校验集
    "active_ministers", "powers", "factions", "classes",
)

# issues 模块专用：阈值对照所需精确数值（simulator_payload 同名是定性档）。
_ISSUES_THRESHOLD_FIELDS = ("current_state", "regions", "active_issues")



def secret_dossier_rosters_from_orders(
    db: GameDB, secret_orders: object,
) -> List[Dict[str, object]]:
    """#1252 private read seam: dossier_id + participant_roster for batch secrets.

    Same caliber as monthly_dossier_reports — personnel_secret only. Keyed by
    dossier_id (not order_id) so the write field can reuse the public roster
    identity space without a parallel order_id keyspace.
    """
    out: List[Dict[str, object]] = []
    for order_id in iter_secret_order_ids(secret_orders):
        dossier = db.get_dossier_for_secret_order(int(order_id))
        if dossier is None:
            continue
        out.append({
            "dossier_id": int(dossier["id"]),
            "participant_roster": list(dossier.get("participant_roster") or []),
        })
    return out


def build_extractor_shared_context(
    db: GameDB,
    state: GameState,
    narrative: str,
    decree_text: str,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
    secret_orders: Optional[Dict[str, object]] = None,
    module: str = "",
    decree_dossiers: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    """供模块 extractor 放入 system 前缀的共同结算补充上下文。

    盘面（regions/armies/buildings/current_state/active_issues/candidate_events…）
    已由同 system 前缀的 simulator_payload 全量给出，这里剔除重复，只留 extractor 独有的
    校验集（region_ids/army_ids/class_names/power_ids/fiscal_config）+ offstage_ministers
    （court_roster 不含离场，任命查重需要）+ turn/narrative。在朝大臣/势力/派系/阶级
    （active_ministers/powers/factions/classes）也剔除——simulator_payload 已有等价视图。

    #1483：current_state/regions/active_issues 在 simulator 侧是 P4 定性档；仅
    module=='issues' 再注入这三字段的 engine 裸数（阈值对照）。其余模块不吃全量拷贝。

    #1503：本回合已关闭拨饷案卷 provenance 仅 module=='internal' 合并
    （economy_moves 单写者）；其余 extractor 不新增 closed dossier 输入面。

    #883: only the secret-order extractor may receive order prose.  The public
    monthly judge and all other extractors must see a disclosure event after
    promotion, never an undisclosed order beforehand.
    """
    base = _extractor_context_payload(
        db, state, narrative, decree_text,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders,
    )
    compat = _extractor_compat_payload(base)
    slim = {k: v for k, v in compat.items() if k not in _MODULE_DROP_FIELDS}
    authorized_dossiers = (
        decree_dossiers
        if decree_dossiers is not None
        else db.list_decree_dossiers_for_simulation(state.turn)
    )
    # #1503：immediate 拨饷颁布即 close，模拟可见集不再含该案；仅 internal
    # （MODULE_FIELDS 独占 economy_moves）extractor 输入须仍见
    # origin_ref=dossier:<id>，使回声带 dossier 身份，由
    # _payload_owned_dossier_for_origin 单写者判重（勿把独立盘面自发一并吞掉）。
    # 同 #1495 issues-only 门控：其余模块不吃 closed 拨饷 provenance。
    # #1507-F1：删 decree_dossiers is None 死门——生产 settle 必预传 list
    # （见 decree.py extractor 装配），None 门使 provenance 永不可达；
    # 预传/现场拉取均按 module==internal 并入 closed 拨饷身份。
    if module == "internal":
        seen_ids = {int(row["id"]) for row in authorized_dossiers}
        extra = []
        for row in db.list_closed_army_pay_dossiers_for_provenance(state.turn):
            rid = int(row["id"])
            if rid not in seen_ids:
                seen_ids.add(rid)
                extra.append(row)
        if extra:
            authorized_dossiers = list(authorized_dossiers) + extra
    # #613：执行格读端字段随案卷进 extractor；优先沿用推演装配已写字段，缺则现场补投影。
    from ming_sim.decree import execution_side_read_fields

    slim_dossiers: List[Dict[str, object]] = []
    side_keys = (
        "appointment_tenure", "held_authorities", "authorization_ids",
        "command_power_rank", "distortion_weight",
    )
    # #625：监督三键仅 issues 模块申报（票面=simulator+score_extractor_issues）；
    # 其他 extractor 不得见未申报键。
    from ming_sim.supervision import SUPERVISION_SURFACE_KEYS, unpack_supervision_surface

    for row in authorized_dossiers:
        if row["action_type"] == "secret_order":
            continue
        entry: Dict[str, object] = {
            "id": int(row["id"]),
            "origin_ref": f"dossier:{int(row['id'])}",
            "action_type": str(row["action_type"]),
            "decree_text": str(row.get("decree_text") or ""),
            "status": str(row["status"]),
            "due_turn": int(row.get("due_turn") or 0),
            "participant_roster": list(row.get("participant_roster") or []),
        }
        if all(key in row for key in side_keys):
            for key in side_keys:
                entry[key] = row[key]
        else:
            # Need full dossier shape for projection (executor/roster/target).
            full = db.get_decree_dossier(int(row["id"])) or row
            entry.update(execution_side_read_fields(db, state, full))
        if module == "issues":
            # 监督事实底注入执行格面（只读；缺则现场读 DB）。
            if all(key in row for key in SUPERVISION_SURFACE_KEYS):
                for key in SUPERVISION_SURFACE_KEYS:
                    entry[key] = row[key]
            else:
                entry.update(
                    unpack_supervision_surface(
                        db.build_supervision_judge_surface(int(row["id"]))
                    )
                )
        slim_dossiers.append(entry)
    slim["decree_dossiers"] = slim_dossiers
    if module == "personnel_secret":
        slim["secret_orders"] = compat["secret_orders"]
        # #566/#883: monthly briefs travel only on the authorized secret rail.
        # This is also the canonical history read seam used after restore.
        slim["monthly_dossier_reports"] = db.list_monthly_dossier_progress_nudges()
        # #1252/#883: secret-dossier roster read seam — batch only, never public.
        slim["secret_dossier_rosters"] = secret_dossier_rosters_from_orders(
            db, compat["secret_orders"],
        )
        # #1504：机械底档带（纯函数快照）注入判官带内选态；结案真源不在此模块。
        from ming_sim.covert_progress import build_covert_floor_payload
        from ming_sim.settlement_payload import _select_secret_orders_for_sim
        slim["covert_exec_floors"] = build_covert_floor_payload(
            db, _select_secret_orders_for_sim(db),
        )
    if module == "issues":
        # #1483：阈值裸数仅 issues 档房——对照 resolve/fail（民心>60 / bar≥Y）。
        for key in _ISSUES_THRESHOLD_FIELDS:
            slim[key] = compat[key]
        # #567：在途拨帑对账读缝——赈济/拨付 issue 软判打折吃此账，非纯文字。
        slim["grant_reconciliations"] = db.list_open_grant_reconciliations()
        # #626：反噬事实包仅 issues 档房（与 #625 监督三键同格门控）；
        # 不在 _extractor_context_payload 无门副本，避免非 issues 模块误读。
        slim["commitment_backlash_facts"] = build_backlash_narrative_features(db)
    slim["_dedup_note"] = (
        "盘面、诏书、在朝大臣、势力/派系/阶级态势已在 system 的 simulator_payload 中给出"
        "（盘面表 regions/armies/buildings 走 TSV；court_roster 即在朝大臣；"
        "powers_brief/factions_brief/classes_brief 即势力/派系/阶级——factions_brief "
        "为定性档 +『势力已跌破压制线』语义记号），抽取时直接读 simulator_payload。"
        + (
            "阈值对照用裸数在本 extractor_context：current_state（民心/皇威等）、regions"
            "（含 public_support 整数）、active_issues（含 bar_value 整数与 resolve/fail 条件）；"
            "simulator_payload 同名是 P4 定性档，判结案以本 context 裸数为准。"
            if module == "issues"
            else "本 extractor_context 不含 current_state/regions/active_issues 裸数副本。"
        )
        + "另补：校验用 id 集（region_ids/army_ids/class_names/power_ids）、"
        "fiscal_config、offstage_ministers（离场名册，court_roster 不含，任命查重用）。"
    )
    # #648（ADR 0088/F4）：人口数量字段写端单位契约按档口径——新档「人」（与军队
    # 人数/manpower 同刻度），无标旧档「万人」legacy。判别只读本档 DB 持久标记。
    slim["population_unit"] = db.population_unit
    return slim


def _payload_for_module(
    base: Dict[str, object],
    module: str,
) -> Dict[str, object]:
    _ = base
    if module not in MODULE_FIELDS:
        raise ValueError(f"未知 extractor module: {module}")
    return {
        "module": module,
        "module_allowed_fields": sorted(MODULE_FIELDS[module]),
        "instruction": (
            "军队/建筑/候选事件等盘面看 system 的 simulator_payload。"
            + (
                "阈值对照用 current_state/regions/active_issues 裸数看 system 的 "
                "extractor_context（simulator_payload 同名是 P4 定性档）。"
                if module == "issues"
                else "extractor_context 只补 id 校验集与模块专属读缝。"
            )
            + "只输出当前模块允许的中文顶层字段 JSON object。"
        ),
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


def _sig_delta(raw: object) -> str:
    """签名用 delta 规范化：统一 float 再格式化，使 -20(int) 与 -20.0(float) 等价（#399 cmr R1 coderabbit）。"""
    try:
        return str(float(raw))
    except (TypeError, ValueError):
        return str(raw)


def _commitment_carrier_signature(item: Dict[str, object]) -> Optional[tuple]:
    """同源承诺去重签名 = (origin_kind, origin_ref, 月度 economy 归一签名)。只有同源【且】月度
    economy 等价才算真重复——同一密令/诏书下两笔【不同】月拨（同 origin_ref、不同 economy）各自
    保留（codex correctness：原先只按 origin_ref 去重太粗，prompt 规定同一密令编号写固定
    origin_ref=secret_order:N，会误删合法的多笔月拨）。空 origin_ref 无法识别 → 不去重（保守）。"""
    oref = str(item.get("origin_ref") or "").strip()
    if not oref:
        return None
    okind = str(item.get("origin_kind") or "").strip()
    ongoing = item.get("ongoing_effects")
    economy = ongoing.get("economy") if isinstance(ongoing, dict) else None
    eco_sig = frozenset(
        (
            str(e.get("account") or "").strip(),
            _sig_delta(e.get("delta")),
            str(e.get("category") or e.get("reason") or "").strip(),
        )
        for e in (economy if isinstance(economy, list) else []) if isinstance(e, dict)
    )
    # 只去重【经常性月拨】承诺——这套跨模块去重的唯一目的是消「月度 ongoing 双扣」（见调用处注释）。
    # 无月度 economy 的承诺（form③ 未来一次性：仅 end_turn / stop_condition，空 ongoing_effects）
    # 根本不产月度扣账、无双扣可消；却会因签名同收敛到 (okind, oref, frozenset()) 把同一诏书下两笔
    # 合法的不同 form③ 承诺（同 origin_ref、不同 title/end_turn）误删其一（#136 form③，codex correctness）。
    # 故空 economy 一律不参与去重（返 None，与空 origin_ref 同等保守）。
    if not eco_sig:
        return None
    return (okind, oref, eco_sig)


def _merge_module_outputs(outputs: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    merged = copy.deepcopy(EMPTY_EXTRACTION)
    module_rejections: List[Dict[str, object]] = []
    seen_commitment_sigs: set = set()  # 已合并承诺的 (origin, economy) 签名，去重避免月度双扣
    for module in EXTRACTION_MODULES:
        for key, val in outputs.get(module, {}).items():
            if key == "_module_rejections" and isinstance(val, list):
                module_rejections.extend(item for item in val if isinstance(item, dict))
                continue
            if key == "new_issues":
                # 共享字段：list 才追加；非 list（坏形状）绝不走下面的覆盖分支——否则后一个模块
                # （personnel_secret）输出非 list new_issues 会清掉 issues 已合并的承诺条目。坏形状
                # 不静默吞：留一条模块拒收，指明哪个模块产了坏形状（留痕不静默，codex correctness）。
                if isinstance(val, list):
                    for item in val:
                        # 同源【且同 economy】承诺跨模块去重（codex correctness）：issues 与
                        # personnel_secret 都能产 new_issues，若两模块对同一笔（同源+同月拨）各产
                        # 一条，apply 会建两条 active 承诺 → 月度 ongoing 双扣（#340 要消的）。只去
                        # 真重复，同一密令下不同月拨（同 origin_ref、不同 economy）各自保留。
                        if isinstance(item, dict):
                            sig = _commitment_carrier_signature(item)
                            if sig is not None:
                                if sig in seen_commitment_sigs:
                                    module_rejections.append({
                                        "module": module,
                                        "field": "new_issues",
                                        "reason": (
                                            f"同源同额承诺重复（origin_kind={sig[0]} "
                                            f"origin_ref={sig[1]}），已去重避免月度双扣"
                                        ),
                                    })
                                    continue
                                seen_commitment_sigs.add(sig)
                        merged["new_issues"].append(item)
                else:
                    module_rejections.append({
                        "module": module,
                        "field": "new_issues",
                        "reason": "new_issues 非 list（坏形状），已跳过、不覆盖已合并条目",
                        "raw_type": type(val).__name__,
                    })
                continue
            merged[key] = val
    if module_rejections:
        merged["_module_rejections"] = module_rejections
    return merged


def extract_scores_by_modules_with_agno(
    agents: Dict[str, Agent],
    db: GameDB,
    state: GameState,
    narrative: str,
    decree_text: str = "",
    sanitizer: Optional[Agent] = None,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
    secret_orders: Optional[Dict[str, object]] = None,
    parallel: bool = False,
    event_outcome_retry_limit: int = 1,
) -> tuple[Dict[str, object], str, str]:
    """四模块结算 extractor：内政财政、军务外势、局势、人事密令。

    parallel=True：4 个互不依赖的 extractor LLM 调用并发跑，wall-clock≈最慢单个而非串行总和。
    解析/sanitizer/合并仍串行按模块顺序——确定性不变、sanitizer 单实例不并发、输出与串行版字节一致。
    落库（apply_score_extraction）在本函数之外，仍串行单事务（ADR 0008）。
    调用方（decree 月末 settle）一律 parallel=True，不按 runner/模型退串行。"""
    base_payload = _extractor_context_payload(
        db, state, narrative, decree_text,
        relevant_memories=relevant_memories,
        secret_orders=secret_orders,
    )
    module_outputs: Dict[str, Dict[str, object]] = {}
    module_inputs: Dict[str, object] = {}

    # 各模块 payload 先串行备好（纯计算、确定性，不含 LLM 调用）。
    module_payload_json: Dict[str, str] = {}
    for module in EXTRACTION_MODULES:
        payload = _payload_for_module(base_payload, module)
        module_inputs[module] = payload
        module_payload_json[module] = json.dumps(payload, ensure_ascii=False, sort_keys=False)

    def _run_raw(module: str) -> str:
        payload_json = module_payload_json[module]
        tlog(f"[extractor/{module}] user payload total={len(payload_json)} chars (~{len(payload_json)//1.5:.0f} tok)")
        return run_agent_text(agents[module], payload_json, tag=f"extractor/{module}")

    def _parse_module(module: str, raw: str) -> Dict[str, object]:
        try:
            parsed = parse_agent_json(raw, f"结算抽取-{module}")
        except Exception as parse_err:
            if sanitizer is None:
                raise
            tlog(f"[extractor/{module}] 主输出解析失败：{parse_err}；调 sanitizer 重整")
            cleaned = run_agent_text(sanitizer, raw, tag=f"sanitizer/{module}")
            parsed = parse_agent_json(cleaned, f"结算抽取-{module}（sanitizer）")
        return _sanitize_module_output(module, parsed)

    if parallel and len(EXTRACTION_MODULES) > 1:
        # CLI 后端：4 个 LLM 调用并发取 raw（ThreadPoolExecutor.map 保序），再串行按模块顺序
        # 解析/sanitizer/净化（sanitizer 单实例不并发、确定性）。任一模块抛错经 map 迭代原样上抛
        # （with 块先等齐在跑线程再传播）→ 与串行同样触发上层 SettlementAbort。
        from concurrent.futures import ThreadPoolExecutor
        tlog(f"[extractor] 并发抽取 {len(EXTRACTION_MODULES)} 模块（wall-clock≈最慢单个）")
        with ThreadPoolExecutor(max_workers=len(EXTRACTION_MODULES)) as pool:
            raws = list(pool.map(_run_raw, EXTRACTION_MODULES))
        for module, raw in zip(EXTRACTION_MODULES, raws):
            module_outputs[module] = _parse_module(module, raw)
    else:
        # 串行（形态1/api 默认）：保持 run→parse 逐模块交错的原貌——含「run 失败即停、不跑后续」
        # 的旧时机，行为字节级不变（cmr #83 codex：并行不改串行路径）。
        for module in EXTRACTION_MODULES:
            module_outputs[module] = _parse_module(module, _run_raw(module))

    retry_attempt = 0
    while True:
        merged = _merge_module_outputs(module_outputs)
        try:
            normalize_event_outcome_labels_or_error(merged, db.content, db=db, state=state)
            break
        except ValueError as outcome_err:
            if retry_attempt >= max(0, event_outcome_retry_limit):
                raise
            retry_attempt += 1
            retry_hint = (
                "ADR0014 事件结局标签校验失败，请只重做 issues 模块抽取并返回完整 issues 模块 JSON；"
                "不要重写邸报叙事，不要重跑其它 extractor 模块。"
            )
            payload = dict(module_inputs["issues"])
            payload["event_outcome_retry"] = {
                "attempt": retry_attempt,
                "max_retries": event_outcome_retry_limit,
                "previous_error": str(outcome_err),
                "instruction": retry_hint,
            }
            module_inputs["issues"] = payload
            module_payload_json["issues"] = json.dumps(payload, ensure_ascii=False, sort_keys=False)
            tlog(f"[extractor/issues] 事件结局标签校验失败，局部重试 {retry_attempt}/{event_outcome_retry_limit}: {outcome_err}")
            module_outputs["issues"] = _parse_module("issues", _run_raw("issues"))
    localized_merged = _localized_extraction(merged)
    trace_input = {
        "mode": "modular",
        "system_context_note": "模块 agent 的 system instructions 先注入稳定 game_world，再注入 simulator_payload 以复用推演缓存，随后是 extractor 公共契约、extractor_context 与模块提示词；module payload 只含模块名和允许字段。",
        "extractor_context": _extractor_compat_payload(base_payload),
        "modules": module_inputs,
    }
    return (
        merged,
        json.dumps(localized_merged, ensure_ascii=False, sort_keys=False),
        json.dumps(trace_input, ensure_ascii=False, sort_keys=False),
    )
