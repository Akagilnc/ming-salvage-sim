"""局势效果：建筑、实体、配对守门与持续影响的呈现短句。

求值器、惯性与摊派仍留在 issues。本模块不提交事务。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, RejectedItem
from ming_sim.db import GameDB
from ming_sim.models import Event, GameState



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
            bid = db.add_building(
                state,
                region_id=str(op.get("region_id") or ""),
                name=str(op.get("name") or ""),
                category=str(op.get("category") or ""),
                level=int(op.get("level", 1)),
                condition=int(op.get("condition", 60)),
                maintenance=int(op.get("maintenance", 0)),
                risk=int(op.get("risk", 30)),
                output_metric=str(op.get("output_metric") or ""),
                output_amount=int(op.get("output_amount", 0)),
                status=str(op.get("status") or ""),
                origin="issue",
                commit=False,
                origin_ref=origin_ref,
            )
            applied.append({"action": "create", "building_id": bid, "name": str(op.get("name") or "")})
        elif action == "modify":
            bid = str(op.get("building_id") or "")
            fields = {k: v for k, v in op.items() if k not in ("action", "building_id", "origin_ref")}
            fields.setdefault("reason", reason)
            changes = db.apply_building_deltas(
                state, pseudo_event, None, "档房", {bid: fields},
                commit=False, origin_ref=origin_ref,
            )
            if changes:
                applied.append({"action": "modify", "building_id": bid, "changes": changes})
            else:
                rejected.append(RejectedItem(
                    item=op, reason="建筑变更未落地", category="missing_ref", source=source,
                ))
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
    origin_ref: str = "盘面自发",
    source: Provenance = Provenance.system_simulation,
) -> List[Dict[str, object]]:
    """国策结案的实体后果：建军 / 补兵改属性 / 人物状态(死/流放/下狱/罢/致仕)。
    全局严格、不静默——非法 delta 直接抛错中断当回合，绝不无声丢失。
    （effect_on_resolve 原本只支持 metrics/economy/buildings/legacy，这里补 army/人事两线。）"""
    # ADR 0008 决定 1（PR2-S2）后,底层 db 方法对 LLM 脏项改「逐项拒收留痕」而非
    # raise——国策结案路（本函数）把拒收项升级回 ValueError 中断当回合，**仅限历史上
    # 本就 raise 的类别**（查无此军/owner 幻觉/缺必填等）。历史上 print-skip 或静默
    # 走默认的案（army 非法字段/重复无 manpower/重复非整/可选脏值/非 dict 项）带
    # issue_strict=False 标——容忍不升级,否则历史可活的脏数据变成新的崩月路
    # （cmr S2 r1）。两类都留拒收记录,不无声丢。
    from ming_sim.issues import _ctx
    from ming_sim.person_delta_adapter import normalize_person_changes

    tolerated: List[Dict[str, object]] = []
    def effective_content():
        return content if content is not None else _ctx()

    def _collect_result(result, what: str) -> None:
        _landed, refused = result
        tolerated.extend(refused)


    region_delta = effect.get("region_delta")
    if isinstance(region_delta, dict) and region_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _collect_result(
            db.apply_region_deltas(state, pseudo, None, label, region_delta, commit=False,
                                   origin_ref=origin_ref, require_origin=True, strict_effect=True, source=source), "地区变化"
        )
    new_armies = effect.get("new_armies")
    if isinstance(new_armies, list) and new_armies:
        _collect_result(
            db.create_armies_from_extraction(state, new_armies, actor=label, commit=False,
                                              origin_ref=origin_ref, require_origin=True, strict_effect=True, source=source), "建军"
        )
    army_delta = effect.get("army_delta")
    if isinstance(army_delta, dict) and army_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _collect_result(
            db.apply_army_deltas(state, pseudo, None, label, army_delta, commit=False,
                                 origin_ref=origin_ref, require_origin=True, strict_effect=True, source=source), "补兵/改属性"
        )
    power_renames = effect.get("power_renames")
    if power_renames is not None:
        if not isinstance(power_renames, list):
            raise ValueError(f"{label} power_renames 非法（全局严格，不静默）：必须是 list")
        for idx, item in enumerate(power_renames):
            if not isinstance(item, dict):
                raise ValueError(f"{label} power_renames 非法（全局严格，不静默）：第 {idx} 项非 dict")
            power_id = str(item.get("power_id") or "").strip()
            new_name = str(item.get("new_name") or "").strip()
            if not power_id or not new_name:
                raise ValueError(f"{label} power_renames 非法（全局严格，不静默）：power_id/new_name 缺失")
            if db.conn.execute("SELECT 1 FROM powers WHERE id=?", (power_id,)).fetchone() is None:
                raise ValueError(f"{label} power_renames 引用未入库势力 '{power_id}'")
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
    _RETIRED_NESTED_PERSON_KEYS = (
        "character_status_changes",
        "character_power_changes",
        "office_changes",
        "appointments",
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
    if raw_person_changes is not None:
        if not isinstance(raw_person_changes, list):
            raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：必须是 list")
        for idx, it in enumerate(raw_person_changes):
            if not isinstance(it, dict):
                raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：第 {idx} 项非 dict")
    person_changes = normalize_person_changes({"人物变更": raw_person_changes or []})
    if person_changes:
        from ming_sim.entities.character.apply import apply_person_changes
        results, results_rejections = apply_person_changes(
            db,
            state,
            person_changes,
            content=effective_content(),
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
            origin_ref=origin_ref,
            require_origin=True,
        )
        if results_rejections:
            raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：" + "；".join(r.reason for r in results_rejections))
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
                f"军事国策「{str(title)[:16]}」结案无 new_armies 配对（练军/募营疑未建军籍，#46）"
            )
        if needs_office and not has_office:
            warns.append(
                f"军事国策「{str(title)[:16]}」结案无人物变更配对（调将疑未落主将调任，#46）"
            )

    if any(p in blob for p in _FISCAL_RECURRING_PHRASES):
        # 只查国策自身 effect/ongoing 的月度 economy；顶层 fiscal_creates 不在本纯函数视野内，
        # 故告警文案不声称查了它——若另经 fiscal_creates 立账可忽略本提示（CMR claude）。
        if not _has_economy_entry(effect) and not _has_economy_entry(ongoing_effects):
            warns.append(
                f"经制国策「{str(title)[:16]}」结案无月度 economy 配对"
                "（疑月经费/俸饷未立常设月支；若已另经 fiscal_creates 立账可忽略，#45）"
            )
    return warns


def _emit_pairing_warnings(new_row, effect: object, sink: Optional[List[str]] = None) -> None:
    """在 initiative 结案处调配对守门：tlog 响亮告警（#14/#27 风格）；sink 给定时再收进供
    程序 surface（inertia 自然结案路只 tlog、不收 sink）。仅对 kind=initiative 生效；
    row 字段缺失/JSON 畸形一律安全降级、不阻断结算。"""
    def _g(key, default):
        try:
            return new_row[key]
        except (KeyError, IndexError, TypeError):
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
        try:
            tags = json.loads(raw_tags or "[]")
        except (TypeError, ValueError):
            tags = []
    # ongoing_effects 经统一守门 loads_effect_dict（已解析 dict 原样 / JSON 串解析 / 非 dict→{}，
    # 含调用方预解析容器的兼容，#117 R5 chokepoint 一致）。
    from ming_sim.models import loads_effect_dict
    from ming_sim.token_stats import tlog

    ongoing = loads_effect_dict(_g("ongoing_effects", "{}"))
    for w in _initiative_resolve_pairing_warnings(str(_g("title", "") or ""), tags, ongoing, effect):
        tlog(f"[pairing] {w}")
        if sink is not None:
            sink.append(w)

