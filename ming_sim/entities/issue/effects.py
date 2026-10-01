"""局势效果：建筑、实体、配对守门与持续影响的呈现短句。

求值器、惯性与摊派仍留在 issues。本模块不提交事务。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, RejectedItem, SectionResult
from ming_sim.db import GameDB
from ming_sim.constants import REGION_SCORE_FIELDS, FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES, ARMY_SCORE_FIELDS, ARMY_FIELD_ALIASES
from ming_sim.models import Event, GameState

_ISSUE_PSEUDO_EVENT = Event(
    id="issue_resolution", title="局势结案", kind="月末", summary="",
    urgency=0, severity=0, credibility=100, interests=[], audiences=[],
)
_ISSUE_ENTITY_FIELDS = {
    "region_delta": dict, "army_delta": dict, "new_armies": list,
    "power_renames": list, "人物变更": list,
}
_RETIRED_NESTED_PERSON_KEYS = (
    "character_status_changes", "character_power_changes", "office_changes", "appointments",
)



def _apply_issue_buildings(
    db: GameDB,
    state: GameState,
    ops: object,
    pseudo_event: Event,
    reason: str,
    origin_ref: str = "盘面自发",
    source: Provenance = Provenance.system_simulation,
) -> tuple[List[Dict[str, object]], List[RejectedItem]]:
    """落地 issue effect 里的 buildings。不可执行项进入拒收，不记成成功操作。"""
    applied: List[Dict[str, object]] = []
    rejected: List[RejectedItem] = []
    if ops is None:
        return applied, rejected
    if not isinstance(ops, list):
        rejected.append(RejectedItem(
            item={"raw_value": ops},
            reason="局势建筑效果须为数组",
            category="invalid_shape",
            source=source,
        ))
        return applied, rejected
    for op in ops:
        if not isinstance(op, dict):
            rejected.append(RejectedItem(
                item={"raw_value": op},
                reason="局势建筑效果项须为对象",
                category="invalid_shape",
                source=source,
            ))
            continue
        action = str(op.get("action") or "").lower()
        if action == "create":
            from ming_sim.strict_types import strict_int
            from ming_sim.exceptions import DeclarationDataError
            try:
                values = {key: strict_int(op.get(key, default), accept_numeric_strings=True)
                          for key, default in (("level", 1), ("condition", 60), ("maintenance", 0), ("risk", 30), ("output_amount", 0))}
            except (TypeError, ValueError):
                rejected.append(RejectedItem(item=op, reason="建筑数值非整数", category="invalid_enum", source=source))
                continue
            try:
                bid = db.add_building(
                state,
                region_id=str(op.get("region_id") or ""),
                name=str(op.get("name") or ""),
                category=str(op.get("category") or ""),
                level=values["level"],
                condition=values["condition"],
                maintenance=values["maintenance"],
                risk=values["risk"],
                output_metric=str(op.get("output_metric") or ""),
                output_amount=values["output_amount"],
                status=str(op.get("status") or ""),
                origin="issue",
                commit=False,
                origin_ref=origin_ref,
                )
            except DeclarationDataError as exc:
                rejected.append(RejectedItem(item=op, reason=str(exc), category="invalid_enum", source=source))
                continue
            applied.append({"action": "create", "building_id": bid, "name": str(op.get("name") or "")})
        elif action == "modify":
            bid = str(op.get("building_id") or "")
            fields = {k: v for k, v in op.items() if k not in ("action", "building_id", "origin_ref")}
            fields.setdefault("reason", reason)
            changes, refused = db.apply_building_deltas(
                state, pseudo_event, None, "档房", {bid: fields},
                commit=False, origin_ref=origin_ref, source=source,
            )
            rejected.extend(refused)
            if changes:
                applied.append({"action": "modify", "building_id": bid, "changes": changes})
        elif action == "remove":
            bid = str(op.get("building_id") or "")
            removed = db.remove_building(
                state, bid, reason=reason, commit=False, origin_ref=origin_ref,
            )
            if removed:
                applied.append({"action": "remove", "building_id": bid, "removed": True})
            else:
                rejected.append(RejectedItem(
                    item=op, reason="拆除目标建筑不存在", category="missing_ref", source=source,
                ))
        else:
            rejected.append(RejectedItem(
                item=op,
                reason=f"建筑动作不可执行：{action}",
                category="invalid_enum",
                source=source,
            ))
    return applied, rejected

def _monthly_economy_items(effect: Dict[str, object]) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for key in ("economy",):
        raw = effect.get(key)
        if isinstance(raw, list):
            items.extend(item for item in raw if isinstance(item, dict))
    return items


def _format_issue_ongoing(ongoing_raw: str) -> str:
    """简短描述每月固定影响。"""
    from ming_sim.models import loads_effect_dict
    eff = loads_effect_dict(ongoing_raw)  # 非 dict/解析失败→{}（#117 统一守）
    parts: List[str] = []
    # isinstance 守卫：eff 读自已存 JSON（源自 enrich/extractor，未必清洗），metrics/economy 可能
    # 是真值非 dict/list（`or {}`/`or []` 兜不住）→ .items()/迭代 抛错。本函数是展示用 brief，守住免崩（#117 同类）。
    _m = eff.get("metrics")
    metrics = _m if isinstance(_m, dict) else {}
    for key, val in metrics.items():
        if isinstance(val, (int, float)) and val:
            parts.append(f"{key}{'+' if val > 0 else ''}{int(val)}")
    _eco = eff.get("economy")
    for econ in (_eco if isinstance(_eco, list) else []):
        if isinstance(econ, dict):
            delta = econ.get("delta")
            acc = econ.get("account")
            if isinstance(delta, (int, float)) and delta and acc:
                parts.append(f"{acc}{'+' if delta > 0 else ''}{int(delta)}万")
    return "、".join(parts)

def _apply_issue_entities(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    label: str,
    content=None,
    llm_config: Any = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
    applied_buildings: Optional[List[Dict[str, object]]] = None,
    issue_id: Optional[int] = None,
    issue_title: str = "",
    origin_ref: str = "盘面自发",
    source: Provenance = Provenance.system_simulation,
) -> List[RejectedItem]:
    """落地结案后果；数据逐项拒收，代码及持久故障上抛。"""
    from ming_sim.issues import _ctx
    from ming_sim.entities.character.normalize import normalize_person_changes

    from ming_sim.entities.metric.apply import declare_metric_pairs
    from ming_sim.entities.economy.apply import _apply_economy_list
    from ming_sim.entities.faction.apply import _apply_faction_dict

    tolerated: List[RejectedItem] = []
    unknown = effect.keys() - (_ISSUE_ENTITY_FIELDS.keys() | set(_RETIRED_NESTED_PERSON_KEYS) | {"metrics", "economy", "factions", "buildings", "legacy"})
    for key in unknown:
        tolerated.append(RejectedItem(item={"field": key, "raw_value": effect[key]}, reason="局势效果字段不可执行", category="invalid_shape", source=source))
    building_rows, building_rejections = _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, label, origin_ref=origin_ref, source=source)
    tolerated.extend(building_rejections)
    if applied_buildings is not None:
        applied_buildings.extend(building_rows)
    _, legacy_rejections = _spawn_legacy_from_effect(db, state, effect, issue_id, issue_title or label, source=source)
    tolerated.extend(legacy_rejections)
    metrics = {} if effect.get("metrics") is None else effect["metrics"]
    if isinstance(metrics, dict):
        _, refused = declare_metric_pairs(state, list(metrics.items()), db=db)
        tolerated.extend(RejectedItem(item={"field": key, "raw_value": value}, reason=reason,
                                      category=category, source=source)
                         for key, value, reason, category in refused)
    else:
        tolerated.append(RejectedItem(item={"field": "metrics", "raw_value": metrics}, reason="指标效果须为对象", category="invalid_shape", source=source))
    tolerated.extend(_apply_economy_list(db, state, [] if effect.get("economy") is None else effect["economy"], origin_ref=origin_ref, source=source)[1])
    tolerated.extend(_apply_faction_dict(db, {} if effect.get("factions") is None else effect["factions"], source=source)[1])
    for key, container in _ISSUE_ENTITY_FIELDS.items():
        if key in effect and effect[key] is not None and not isinstance(effect[key], container):
            tolerated.append(RejectedItem(
                item={"field": key, "raw_value": effect[key]},
                reason=f"局势效果 {key} 容器类型非法", category="invalid_shape", source=source,
            ))
    def effective_content():
        return content if content is not None else _ctx()

    def _collect_result(result) -> None:
        _landed, refused = result
        tolerated.extend(refused)


    region_delta = effect.get("region_delta")
    if isinstance(region_delta, dict) and region_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _collect_result(
            db.apply_region_deltas(state, pseudo, None, label, region_delta, commit=False,
                                   origin_ref=origin_ref, require_origin=True, source=source)
        )
    new_armies = effect.get("new_armies")
    if isinstance(new_armies, list) and new_armies:
        _collect_result(
            db.create_armies_from_extraction(state, new_armies, actor=label, commit=False,
                                              origin_ref=origin_ref, require_origin=True, source=source)
        )
    army_delta = effect.get("army_delta")
    if isinstance(army_delta, dict) and army_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _collect_result(
            db.apply_army_deltas(state, pseudo, None, label, army_delta, commit=False,
                                 origin_ref=origin_ref, require_origin=True, source=source)
        )
    power_renames = effect.get("power_renames")
    if isinstance(power_renames, list):
        for item in power_renames:
            if not isinstance(item, dict):
                tolerated.append(RejectedItem(item={"raw_value": item}, reason="势力更名项须为对象", category="invalid_shape", source=source))
                continue
            power_id = str(item.get("power_id") or "").strip()
            new_name = str(item.get("new_name") or "")
            if not power_id or not new_name.strip():
                tolerated.append(RejectedItem(item=item, reason="势力更名缺 power_id/new_name", category="missing_field", source=source))
                continue
            if db.conn.execute("SELECT 1 FROM powers WHERE id=?", (power_id,)).fetchone() is None:
                tolerated.append(RejectedItem(item=item, reason="势力更名目标未入库", category="missing_ref", source=source))
                continue
            db.apply_power_rename(
                state,
                power_id,
                new_name,
                aliases=str(item.get("aliases") or ""),
                reason=str(item.get("reason") or label),
                status=str(item.get("status") or ""),
                last_action=str(item.get("last_action") or ""),
                commit=False,
            )
    for retired_key in _RETIRED_NESTED_PERSON_KEYS:
        raw_retired = effect.get(retired_key)
        if raw_retired is None or raw_retired == [] or raw_retired == {}:
            continue
        entries = raw_retired if isinstance(raw_retired, list) else [raw_retired]
        for entry in entries:
            if isinstance(entry, dict):
                entity_id = entry.get("entity_id") or entry.get("id") or entry.get("character_id") or entry.get("name")
                item = {"raw_value": entry}
                if entity_id not in (None, ""):
                    item["entity_id"] = entity_id
            else:
                item = {"raw_value": entry}
            tolerated.append(RejectedItem(
                item=item,
                reason=f"局势嵌套效果 {retired_key} 已退役，不可执行",
                category="invalid_shape",
                source=source,
            ))
    raw_person_changes = effect.get("人物变更")
    person_items = []
    if isinstance(raw_person_changes, list):
        for it in raw_person_changes:
            if not isinstance(it, dict):
                tolerated.append(RejectedItem(item={"raw_value": it}, reason="人物变更项须为对象", category="invalid_shape", source=source))
            else:
                person_items.append(it)
    person_changes = normalize_person_changes({"人物变更": person_items})
    if person_changes:
        from ming_sim.entities.character.apply import apply_person_changes
        results, results_rejections = apply_person_changes(
            db,
            state,
            person_changes,
            content=effective_content(),
            llm_config=llm_config,
            source=source,
            derived_from=label,
            origin_ref=origin_ref,
            require_origin=True,
        )
        tolerated.extend(results_rejections)
        for result in results:
            tolerated.extend(result.pop("backlash_results", None) or [])
        if applied_person_changes is not None:
            applied_person_changes.extend(results)
    return tolerated

# #45/#46（M1 状态可信链路）：国策结案实体后果强制配对守门。语义命中练军/募营/调将却无
# new_armies/office_changes、或命月经费/俸/饷却无月度 economy 时响亮告警，堵「只推进度条、
# 实体后果只活邸报」的半落库（#45 太学府月经费没立账、#46 天雄军没建军籍真踩坑）。
# warn-only：列入结果供 surface、不阻断结算；检查国策自身 effect_on_resolve/ongoing_effects
# 是否带应有实体（正解就该挂在这两处、enrich 也如此填），不跨引顶层、保持纯函数可测。
_MILITARY_RAISE_PHRASES = (
    "练军", "练兵", "练成", "募营", "募兵", "募军", "建军", "新军", "成军",
    "团练", "编练", "立营", "组建", "扩军",
)
_MILITARY_MOVE_PHRASES = ("调将", "调防", "移镇", "督师", "镇守", "调任主将")
_FISCAL_RECURRING_PHRASES = (
    "月经费", "经费", "月俸", "俸禄", "岁俸", "军饷", "粮饷", "月饷", "岁支",
    "廪", "养兵", "养廉", "月银",
)


def _nonempty_list(v: object) -> bool:
    return isinstance(v, list) and len(v) > 0


def _nonempty_dict(v: object) -> bool:
    return isinstance(v, dict) and len(v) > 0

def _has_economy_entry(d: object) -> bool:
    """是否含「flows 会真正立账」的月度 economy 项：account∈(国库,内库) + delta 经 int() 强转非零
    ——与 flows._apply_economy_list 同口径（它只对 国库/内库 立账、`int(delta or 0)` 强转、跳过
    零额/非数/它账）。空壳/它账/零额/非数不算配对，数字串 delta 同 flows 认账（CMR codex+claude）。
    economy 非 list（畸形 JSON：int/str/bool）→ 安全返 False，不 TypeError 崩结算（PR#107 gemini）。"""
    if not isinstance(d, dict):
        return False
    eco = d.get("economy")
    if not isinstance(eco, list):
        return False
    for item in eco:
        if not isinstance(item, dict):
            continue
        if str(item.get("account") or "") not in ("国库", "内库"):
            continue
        try:
            delta = int(item.get("delta") or 0)
        except (TypeError, ValueError):
            continue
        if delta != 0:
            return True
    return False


def _initiative_resolve_pairing_warnings(
    title: str, tags: object, ongoing_effects: object, effect: object,
) -> List[str]:
    """国策结案实体后果强制配对守门（#45/#46）——仅在 initiative 结案处调用。
    返回缺配对的告警串列表（空=无缺漏）。warn-only，调用方 surface、不阻断。"""
    tag_list = tags if isinstance(tags, (list, tuple)) else []
    blob = str(title or "") + " " + " ".join(str(t) for t in tag_list)
    effect = effect if isinstance(effect, dict) else {}
    warns: List[str] = []

    # 练军/募营 须落 new_armies；调将 须落人物变更——分别判，不混为一谈（练军只挂调任仍缺军籍、
    # 调将只挂建军仍缺主将调任，混判会互相消音，CMR codex）。office_changes 是 ADR 0009 死键、
    # _apply_issue_entities 不读，不纳入 has_office（纳入会消音本该响的告警，CMR gemini）。
    needs_army = any(p in blob for p in _MILITARY_RAISE_PHRASES)
    needs_office = any(p in blob for p in _MILITARY_MOVE_PHRASES)
    if needs_army or needs_office:
        # 形对：_apply_issue_entities 只落 list 的 new_armies/人物变更、dict 的
        # army_delta；畸形容器（字符串/错类型）不算真配对，不该消音告警（PR#107 codex）。
        has_army = _nonempty_list(effect.get("new_armies")) or _nonempty_dict(effect.get("army_delta"))
        has_office = _nonempty_list(effect.get("人物变更"))
        if needs_army and not has_army:
            warns.append(
                f"军事国策「{str(title)}」结案无 new_armies 配对（练军/募营疑未建军籍，#46）"
            )
        if needs_office and not has_office:
            warns.append(
                f"军事国策「{str(title)}」结案无人物变更配对（调将疑未落主将调任，#46）"
            )

    if any(p in blob for p in _FISCAL_RECURRING_PHRASES):
        # 只查国策自身 effect/ongoing 的月度 economy；顶层 fiscal_creates 不在本纯函数视野内，
        # 故告警文案不声称查了它——若另经 fiscal_creates 立账可忽略本提示（CMR claude）。
        if not _has_economy_entry(effect) and not _has_economy_entry(ongoing_effects):
            warns.append(
                f"经制国策「{str(title)}」结案无月度 economy 配对"
                "（疑月经费/俸饷未立常设月支；若已另经 fiscal_creates 立账可忽略，#45）"
            )
    return warns


def _emit_pairing_warnings(new_row, effect: object, sink: Optional[List[str]] = None) -> None:
    """在 initiative 结案处调配对守门：tlog 响亮告警（#14/#27 风格）；sink 给定时再收进供
    程序 surface（inertia 自然结案路只 tlog、不收 sink）。仅对 kind=initiative 生效；
    可缺省的行字段取缺省值；持久 JSON 损坏上抛。"""
    def _g(key, default):
        try:
            return new_row[key]
        except (KeyError, IndexError):
            return default
    if str(_g("kind", "") or "") != "initiative":
        return
    # tags/ongoing_effects 在 DB row 里是 JSON 串，但调用方（test/mock/上游预解析）可能已传
    # 解析好的 list/dict——此时 json.loads(容器) 抛 TypeError 被 except 吞成空，会静默丢有效
    # 数据、把本该响的告警消音 / 把有效月支误判成缺失（PR#107 R3 gemini medium，与下游
    # _initiative_resolve_pairing_warnings 的 isinstance 防御同向）。先认已解析的容器。
    raw_tags = _g("tags", "[]")
    if isinstance(raw_tags, (list, tuple)):
        tags = list(raw_tags)
    else:
        tags = json.loads(raw_tags or "[]")
        if not isinstance(tags, list):
            raise ValueError("持久化局势 tags 须为列表")
    # ongoing_effects 经统一守门 loads_effect_dict；损坏不冒作无效果。
    from ming_sim.models import loads_effect_dict
    from ming_sim.token_stats import tlog

    ongoing = loads_effect_dict(_g("ongoing_effects", "{}"))
    for w in _initiative_resolve_pairing_warnings(str(_g("title", "") or ""), tags, ongoing, effect):
        tlog(f"[pairing] {w}")
        if sink is not None:
            sink.append(w)


_LEGACY_PCT_CAP = 5


_LEGACY_ACCOUNT_KEYS = ("国库", "内库", "民心", "皇威")


_LEGACY_DURATION_MONTHS = {"1年": 12, "2年": 24, "永久": -1}


def _clamp_pct(v: object) -> Optional[int]:
    from ming_sim.strict_types import strict_int
    pct = strict_int(v, accept_numeric_strings=True)
    if pct == 0:
        return None
    return max(-_LEGACY_PCT_CAP, min(_LEGACY_PCT_CAP, pct))



def _spawn_legacy_from_effect(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    issue_id: Optional[int],
    issue_title: str,
    *,
    source: Provenance,
) -> tuple[Optional[Dict[str, object]], List[RejectedItem]]:
    """结案 effect 里若带 legacy（帝国修正）段，落 legacies 表。返回落地摘要供日志。
    legacy schema:
      {"name": str,
       "duration": "1年"|"2年"|"永久",
       "modifiers": {                         # 各维度带符号百分比修正符
         "国库": +10, "内库": -5,                    # 账户增量
         "regions": {"shaanxi": {"unrest": -20}},   # 地区分数字段（仅 REGION_SCORE_FIELDS）
         "armies":  {"jizhou": {"morale": 15}}      # 军队分数字段（仅 ARMY_SCORE_FIELDS）
       },
       "narrative_hint": str}
    各 pct 带符号整数；落账时同维度累加，base>=0 ×(1+net/100)、base<0 ×(1-net/100)。
    不可执行字段逐项拒收，合法同批字段仍落地；本核不提交事务。
    """
    legacy = effect.get("legacy")
    rejected: List[RejectedItem] = []
    if legacy is None:
        return None, rejected
    if not isinstance(legacy, dict):
        return None, [RejectedItem(item={"field": "legacy", "raw_value": legacy}, reason="帝国修正须为对象", category="invalid_shape", source=source)]

    def refuse(item: dict, reason: str, category: str = "invalid_enum") -> None:
        rejected.append(RejectedItem(item=item, reason=reason, category=category, source=source))
    for key in legacy.keys() - {"name", "duration", "modifiers", "narrative_hint"}:
        refuse({"field": key, "raw_value": legacy[key]}, "帝国修正字段不可执行")
    for field in ("name", "narrative_hint"):
        if legacy.get(field) is not None and not isinstance(legacy[field], str):
            refuse(legacy, "帝国修正文段须为字符串", "invalid_shape")
            return None, rejected
    raw_legacy_name = legacy.get("name")
    name = (
        str(raw_legacy_name)
        if raw_legacy_name is not None and str(raw_legacy_name).strip()
        else f"{issue_title}遗留"
    )
    dur_key = str(legacy.get("duration") or "2年").strip()
    duration = _LEGACY_DURATION_MONTHS.get(dur_key)
    if duration is None:
        refuse(legacy, "帝国修正时长非法")
        return None, rejected
    raw_eff = {} if legacy.get("modifiers") is None else legacy["modifiers"]
    if not isinstance(raw_eff, dict):
        refuse({"field": "modifiers", "raw_value": raw_eff}, "帝国修正 modifiers 须为对象", "invalid_shape")
        return None, rejected
    for key in raw_eff.keys() - {*_LEGACY_ACCOUNT_KEYS, "regions", "armies"}:
        refuse({"field": key, "raw_value": raw_eff[key]}, "帝国修正字段不可执行")
    modifiers: Dict[str, object] = {}
    for key in _LEGACY_ACCOUNT_KEYS:
        if key not in raw_eff:
            continue
        try:
            pct = _clamp_pct(raw_eff[key])
        except (TypeError, ValueError):
            refuse({"field": key, "raw_value": raw_eff[key]}, "帝国修正百分比须为整数")
            continue
        if pct is not None:
            modifiers[key] = pct
    for scope, allowed, aliases in (
        ("regions", REGION_SCORE_FIELDS + FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES),
        ("armies", ARMY_SCORE_FIELDS, ARMY_FIELD_ALIASES),
    ):
        if scope not in raw_eff:
            continue
        block = raw_eff[scope]
        if not isinstance(block, dict):
            refuse({"field": scope, "raw_value": block}, "帝国修正实体容器须为对象", "invalid_shape")
            continue
        scope_out: Dict[str, Dict[str, int]] = {}
        for entity_id, fields in block.items():
            item = {"entity_id": entity_id, "field": scope, "raw_value": fields}
            if not isinstance(fields, dict):
                refuse(item, "帝国修正实体项须为对象", "invalid_shape")
                continue
            if db.conn.execute(f"SELECT 1 FROM {scope} WHERE id=?", (entity_id,)).fetchone() is None:
                refuse(item, "帝国修正实体未入库", "missing_ref")
                continue
            fields_out: Dict[str, int] = {}
            for raw_field, value in fields.items():
                field = aliases.get(str(raw_field).strip(), str(raw_field).strip())
                item = {"entity_id": entity_id, "field": raw_field, "raw_value": value}
                if field not in allowed:
                    refuse(item, "帝国修正实体字段不可执行")
                    continue
                try:
                    pct = _clamp_pct(value)
                except (TypeError, ValueError):
                    refuse(item, "帝国修正百分比须为整数")
                    continue
                if pct is not None:
                    fields_out[field] = pct
            if fields_out:
                scope_out[str(entity_id)] = fields_out
        if scope_out:
            modifiers[scope] = scope_out
    if not modifiers:
        return None, rejected
    new_id = db.insert_legacy(
        state,
        name=name,
        modifiers=modifiers,
        narrative_hint=str(legacy.get("narrative_hint") or ""),
        duration_months=duration,
        source_issue_id=issue_id,
        commit=False,
    )
    summary = {
        "legacy_id": new_id, "name": name,
        "duration_months": duration, "modifiers": modifiers,
    }
    dur_label = "永久" if duration < 0 else f"{duration}月"
    print(f"[帝国修正] 局势#{issue_id}「{issue_title}」落「{name}」({dur_label}) {modifiers}")
    return summary, rejected



def _invalid_monthly_mapping_shape(
    field: str,
    entity_id: object,
    raw_value: object,
    source: Provenance = Provenance.system_simulation,
) -> RejectedItem:
    return RejectedItem(item={"field": field, "id": entity_id, "value": raw_value}, reason=f"{field}.{entity_id} 须为对象(dict)", category="invalid_shape", source=source)


def _monthly_mapping_effect(
    effect: Dict[str, object],
    *keys: str,
    source: Provenance = Provenance.system_simulation,
) -> tuple[Dict[str, Dict[str, object]], List[RejectedItem]]:
    merged: Dict[str, Dict[str, object]] = {}
    rejections: List[RejectedItem] = []
    for key in keys:
        raw = effect.get(key)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            rejections.append(RejectedItem(item={"field": key, "raw_value": raw}, reason="月度实体容器须为对象", category="invalid_shape", source=source))
            continue
        for entity_id, raw_changes in raw.items():
            if isinstance(raw_changes, dict):
                merged[entity_id] = raw_changes
                continue
            rejections.append(_invalid_monthly_mapping_shape(key, entity_id, raw_changes, source=source))
    return merged, rejections


def _apply_monthly_ongoing_entities(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    label: str,
    *,
    content=None,
    llm_config: Any = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
    origin_ref: str = "盘面自发",
    source: Provenance = Provenance.system_simulation,
) -> SectionResult:
    from ming_sim.entities.social_class.apply import _apply_class_dict
    from ming_sim.entities.faction.apply import _apply_faction_dict
    from ming_sim.entities.character.normalize import normalize_person_changes
    from ming_sim.issues import _ctx
    applied: List[dict] = []
    rejections: List[RejectedItem] = []
    for key in effect.keys() - {"metrics", "economy", "factions", "class_delta", "region_delta", "army_delta", "power_updates", "人物变更"}:
        rejections.append(RejectedItem(item={"field": key, "raw_value": effect[key]}, reason="月度效果字段不可执行", category="invalid_shape", source=source))

    factions, faction_shape_rejections = _monthly_mapping_effect(effect, "factions", source=source)
    classes, class_shape_rejections = _monthly_mapping_effect(effect, "class_delta", source=source)
    region_delta, region_shape_rejections = _monthly_mapping_effect(effect, "region_delta", source=source)
    army_delta, army_shape_rejections = _monthly_mapping_effect(effect, "army_delta", source=source)
    power_updates, power_shape_rejections = _monthly_mapping_effect(effect, "power_updates", source=source)
    rejections.extend(
        faction_shape_rejections
        + class_shape_rejections
        + region_shape_rejections
        + army_shape_rejections
        + power_shape_rejections
    )

    if factions:
        faction_applied, faction_rejections = _apply_faction_dict(db, factions, source=source)
        if faction_applied:
            applied.append({"factions": faction_applied})
        rejections.extend(faction_rejections)

    if classes:
        class_applied, class_rejections = _apply_class_dict(db, classes, source=source)
        if class_applied:
            applied.append({"class_delta": class_applied})
        rejections.extend(class_rejections)

    if region_delta:
        region_changes, region_changes_rejections = db.apply_region_deltas(
            state, _ISSUE_PSEUDO_EVENT, None, label, region_delta,
            origin_ref=origin_ref, source=source, commit=False,
        )
        applied_region = region_changes
        if applied_region:
            applied.append({"region_delta": applied_region})
        rejections.extend(region_changes_rejections)

    if army_delta:
        army_changes, army_changes_rejections = db.apply_army_deltas(
            state, _ISSUE_PSEUDO_EVENT, None, label, army_delta,
            origin_ref=origin_ref, source=source, commit=False,
        )
        applied_army = army_changes
        if applied_army:
            applied.append({"army_delta": applied_army})
        rejections.extend(army_changes_rejections)

    if power_updates:
        power_changes, power_changes_rejections = db.apply_power_deltas(state, power_updates, origin_ref=origin_ref, source=source, commit=False)
        applied_power = power_changes
        if applied_power:
            applied.append({"power_updates": applied_power})
        rejections.extend(power_changes_rejections)

    raw_people = effect.get("人物变更")
    people = []
    if raw_people is not None and not isinstance(raw_people, list):
        rejections.append(RejectedItem(item={"field": "人物变更", "raw_value": raw_people}, reason="月度人物效果须为列表", category="invalid_shape", source=source))
    for item in raw_people if isinstance(raw_people, list) else []:
        if not isinstance(item, dict):
            rejections.append(RejectedItem(item={"raw_value": item}, reason="月度人物项须为对象", category="invalid_shape", source=source))
        elif str(item.get("动作") or item.get("action") or "").strip() != "评定" or not isinstance(item.get("loyalty"), int) or isinstance(item.get("loyalty"), bool) or item["loyalty"] == 0:
            rejections.append(RejectedItem(item=item, reason="月度人物效果仅支持非零整数忠诚评定", category="invalid_enum", source=source))
        elif not str(item.get("name") or item.get("人物") or "").strip():
            rejections.append(RejectedItem(item=item, reason="月度人物效果缺姓名", category="missing_field", source=source))
        else:
            people.append(item)
    person_changes = normalize_person_changes({"人物变更": people})
    if person_changes:
        effective_content = content if content is not None else _ctx()
        from ming_sim.entities.character.apply import apply_person_changes
        results, results_rejections = apply_person_changes(
            db,
            state,
            person_changes,
            content=effective_content,
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
            origin_ref=origin_ref,
        )
        applied_people = results
        if applied_people:
            applied.append({"人物变更": applied_people})
        rejections.extend(results_rejections)
        for result in results:
            rejections.extend(result.pop("backlash_results", None) or [])
        if applied_person_changes is not None:
            applied_person_changes.extend(results)

    return SectionResult(applied=applied, rejected=rejections)

