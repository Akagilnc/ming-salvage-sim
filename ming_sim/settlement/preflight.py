"""Issue 系统：候选事件、issue 立项/推进/结案、tracker 输出落地、inertia 漂移。L6。

通过 bind_content() 注入 GameContent（取 EVENTS/SEED_EVENTS/EVENT_BY_ID）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

import copy
import json
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ming_sim.applier import atomic
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET
from ming_sim.constants import (
    TURN_UNIT, REGION_SCORE_FIELDS, REGION_QUANTITY_FIELDS, REGION_TEXT_FIELDS,
    ARMY_SCORE_FIELDS, ARMY_QUANTITY_FIELDS, ARMY_TEXT_FIELDS, FISCAL_SCORE_FIELDS,
    BUILDING_SCORE_FIELDS, BUILDING_QUANTITY_FIELDS, BUILDING_TEXT_FIELDS,
    POWER_SCORE_FIELDS, POWER_TEXT_FIELDS, CHARACTER_TEXT_FIELDS,
    REGION_FIELD_ALIASES, ARMY_FIELD_ALIASES, GATE_TABLES,
    LEVY_DISPLACEMENT_RATE,
    BANDIT_ABSORPTION_FIELDS,
    BANDIT_ABSORPTION_PERSONS_PER_STRENGTH,
    RECOVERY_PERSONS_PER_WAN,
    RECOVERY_GRANT_ACTIONS,
    RECOVERY_OUTCOME_FACTORS,
)
from ming_sim.content import GameContent
from ming_sim.context import victory_status
from ming_sim.db import (
    GameDB,
    POPULATION_UNIT_PERSONS,
    _LEVERAGE_FACTIONS,
    _approx_wanliang,
    normalize_office,
    resolve_office_type_preserving_title,
)
from ming_sim.relations import EMPEROR_NODE
from ming_sim.decree_vocabulary import (
    dossier_action_policy,
    format_public_progress_disclosure,
    terminal_report_facade,
)
from ming_sim.exceptions import DeclarationDataError, OfficeAppointmentRejection, SettlementAbort
from ming_sim.entities.metric.apply import (
    ISSUE_METRIC_KEYS,
    apply_metric_dict as _apply_metric_dict,
)
from ming_sim.flows import (
    ISSUE_METRIC_LOCK_CAPS,
)
from ming_sim.models import Event, GameState, effect_dict_has_work, loads_effect_dict
from ming_sim.participant_roster import project_execution_liability_parties
from ming_sim.entities.character.normalize import normalize_person_changes
from ming_sim.entities.character import names as character_names
from ming_sim.token_stats import tlog


# 人物行程规则真源在 entities.character.transit；战略信封编排从此取用，不持有实现。
from ming_sim.entities.character.transit import (  # noqa: E402
    TRAVEL_SPEED_BY_TONE,
    TravelTone,
    admit_transit_departure as _admit_transit_departure,
    load_valid_regions as _load_pending_gate_valid_regions,
    normalize_travel_tone,
)



# 会崩坏的局势：人为可控、有明确「彻底失败」时刻——镇压不住/边镇沦陷/朝局崩坏。
# 它们 bar 能跌到 0、status 转 failed 终结，落 effect_on_fail 一锤子永久重创。
# 不在此集合的（天灾/饥荒等不可控天象、正面机遇）无失败态：bar 下限 1、永不 failed、
# effect_on_fail 留空，伤害全靠 ongoing_effects 持续累积。db.advance_issue 据 effect_on_fail
# 是否非空来判能否崩坏，故此处「会崩坏」与「非空 fail effect」必须一致。

_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS: Dict[str, Dict[str, frozenset[str]]] = {
    "jisi_lubian": {
        "regions": frozenset({"beizhili"}),
        "armies": frozenset({"jingying", "guanning", "jizhen", "xuan_da"}),
        "characters": frozenset(),
        "powers": frozenset({"houjin"}),
    },
    "dalingghe": {
        "regions": frozenset({"liaodong"}),
        "armies": frozenset({"guanning"}),
        "characters": frozenset({"祖大寿"}),
        "powers": frozenset({"houjin"}),
    },
    "lindan_xiqian": {
        "regions": frozenset({"mongol_chahar"}),
        "armies": frozenset({"mongol_chahar_host"}),
        "characters": frozenset({"林丹汗"}),
        "powers": frozenset({"mongol", "houjin"}),
    },
    "wuyin_lubian": {
        "regions": frozenset({"beizhili", "shandong"}),
        "armies": frozenset({"jingying", "guanning", "jizhen", "xuan_da"}),
        "characters": frozenset({"卢象升"}),
        "powers": frozenset({"houjin"}),
    },
    "songshan_battle": {
        "regions": frozenset({"liaodong"}),
        "armies": frozenset({"guanning"}),
        "characters": frozenset({"洪承畴"}),
        "powers": frozenset({"houjin"}),
    },
    "luoyang_fallen": {
        "regions": frozenset({"henan"}),
        "armies": frozenset({"shaanxi_army"}),
        "characters": frozenset({"朱常洵"}),
        "powers": frozenset({"bandit_li_zicheng"}),
    },
    "kaifeng_siege": {
        "regions": frozenset({"henan"}),
        "armies": frozenset({"shaanxi_army"}),
        "characters": frozenset(),
        "powers": frozenset({"bandit_li_zicheng"}),
    },
    "beijing_fallen": {
        "regions": frozenset({"beizhili"}),
        "armies": frozenset({"jingying", "jizhen", "xuan_da", "guanning"}),
        "characters": frozenset(),
        "powers": frozenset({"bandit_li_zicheng"}),
    },
}
_STRATEGIC_EVENT_OUTCOME_LABELS: Dict[str, frozenset[str]] = {
    "jisi_lubian": frozenset({"挡于边墙", "入塞被遏", "长驱直入"}),
}
_STRATEGIC_EVENT_OUTCOME_LABEL_ALIASES: Dict[str, Dict[str, str]] = {
    "jisi_lubian": {
        "挡于边墙外": "挡于边墙",
        "拒于边墙": "挡于边墙",
        "未能入塞": "挡于边墙",
        "入塞遭遏": "入塞被遏",
        "入塞受遏": "入塞被遏",
        "入塞后被遏": "入塞被遏",
        "入塞被阻": "入塞被遏",
        "长驱入京": "长驱直入",
        "兵临京师": "长驱直入",
    },
}
def _is_strategic_foreign_node_event(ev: Event) -> bool:
    return (
        getattr(ev, "event_type", "situation") != "situation"
        and getattr(ev, "trigger_class", "") == "strategic_foreign"
    )


def _validate_strategic_foreign_node_outcome_targets(content: GameContent) -> None:
    strategic_event_ids = {
        event_id
        for event_id, ev in content.event_by_id.items()
        if _is_strategic_foreign_node_event(ev)
    }
    target_event_ids = set(_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS)
    missing = sorted(strategic_event_ids - target_event_ids)
    if missing:
        raise SystemExit(
            f"strategic_foreign 事件 {', '.join(missing)} 缺 outcome target map。"
        )
    stale = sorted(target_event_ids - strategic_event_ids)
    if stale:
        raise SystemExit(
            f"outcome target map 含非 strategic_foreign 事件：{', '.join(stale)}。"
        )


def _event_pool_ids_for_strategic_foreign_nodes(
    extracted: Dict[str, object],
    content: GameContent,
) -> set[str]:
    ids: set[str] = set()
    for item in extracted.get("new_issues") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("origin_kind") or "").lower() != "event_pool":
            continue
        event_id = str(item.get("id") or item.get("origin_ref") or "").strip()
        ev = content.event_by_id.get(event_id)
        if ev is not None and _is_strategic_foreign_node_event(ev):
            ids.add(ev.id)
    return ids


_ORDERED_DELTA_FIELDS = (
    "metric_delta", "faction_delta", "class_delta",
    "region_delta", "army_delta", "power_updates",
)


def _derive_ordered_deltas(extracted: Dict[str, object]) -> Dict[str, list[tuple[str, object]]]:
    """缺省有序声明：按 extracted 字段原序派生，无声明归属。"""
    ordered: Dict[str, list[tuple[str, object]]] = {field: [] for field in _ORDERED_DELTA_FIELDS}
    for field in _ORDERED_DELTA_FIELDS:
        raw = extracted.get(field) or {}
        if isinstance(raw, dict):
            ordered[field] = list(raw.items())
    return ordered


def _effect_event_ids(
    field: str, index: int, event_ids: set[str],
    ordered_effect_event_ids: dict[str, list[str]] | None,
) -> set[str]:
    """效果归属只认转译声明的 event_id；未声明即独立效果。"""
    declared = (ordered_effect_event_ids or {}).get(field, [])
    event_id = declared[index] if index < len(declared) else ""
    return {event_id} & event_ids if event_id else set()



def _split_strategic_person_result_changes(
    changes: List[Dict[str, object]],
    strategic_event_ids: set[str],
    declared_event_by_item: dict[int, str],
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    strategic: List[Dict[str, object]] = []
    other: List[Dict[str, object]] = []
    for item in changes:
        event_id = declared_event_by_item.get(id(item), "")
        if event_id and event_id in strategic_event_ids:
            strategic.append(item)
        else:
            other.append(item)
    return strategic, other


def _event_result_delta_event_ids(
    strategic_event_ids: set[str],
    extracted: Dict[str, object],
    person_changes: List[Dict[str, object]],
    ordered_deltas: Dict[str, list[tuple[str, object]]],
    ordered_effect_event_ids: dict[str, list[str]] | None,
) -> set[str]:
    """收集本批声明归属到战略事件的效果所触及的事件 id。"""
    result_ids: set[str] = set()

    def _collect_field(field: str) -> None:
        items = ordered_deltas.get(field) or []
        for index, _pair in enumerate(items):
            result_ids.update(_effect_event_ids(
                field, index, strategic_event_ids, ordered_effect_event_ids,
            ))

    if isinstance(extracted.get("region_delta"), dict):
        _collect_field("region_delta")
    if isinstance(extracted.get("army_delta"), dict):
        _collect_field("army_delta")
    if isinstance(extracted.get("power_updates"), dict):
        _collect_field("power_updates")
    for index, item in enumerate(person_changes):
        event_id = str(item.get("_effect_event_id") or "")
        if event_id and event_id in strategic_event_ids:
            result_ids.add(event_id)
    if isinstance(extracted.get("new_armies"), list):
        declared = (ordered_effect_event_ids or {}).get("new_armies", [])
        for index, _item in enumerate(extracted.get("new_armies") or []):
            event_id = declared[index] if index < len(declared) else ""
            if event_id and event_id in strategic_event_ids:
                result_ids.add(event_id)
    return result_ids


def _normalize_event_outcome_label(event_id: str, label: str) -> str:
    allowed = _STRATEGIC_EVENT_OUTCOME_LABELS.get(event_id, frozenset())
    compact = re.sub(r"\s+", "", str(label or ""))
    if not compact:
        return ""
    for canonical in allowed:
        if compact == re.sub(r"\s+", "", canonical):
            return canonical
    return _STRATEGIC_EVENT_OUTCOME_LABEL_ALIASES.get(event_id, {}).get(compact, "")


def _strategic_event_outcome_label_or_error(
    event_id: str,
    extracted: Dict[str, object],
    content: GameContent,
) -> tuple[str, str]:
    # issues 真源；本文件不得再持同形副本（#1835 C1 DRY）。函数内 import 避 issues↔preflight 环。
    from ming_sim.issues import _event_outcome_label

    allowed = _STRATEGIC_EVENT_OUTCOME_LABELS.get(event_id, frozenset())
    if not allowed:
        return "", ""
    label = _event_outcome_label(extracted.get("事件结局") or {}, event_id)
    event_title = content.event_by_id[event_id].title if event_id in content.event_by_id else event_id
    if not label:
        return "", f"战略/外敌事件「{event_title}」缺事件结局标签"
    normalized = _normalize_event_outcome_label(event_id, label)
    if not normalized:
        raise ValueError(
            f"战略/外敌事件「{event_title}」事件结局标签无法归一：{label}；"
            f"合法标签：{'/'.join(sorted(allowed))}"
        )
    return normalized, ""


def _strategic_event_result_preflight_error(
    db: GameDB,
    state: GameState,
    event_id: str,
    event_title: str,
    outcome_label: str,
    region_deltas: Dict[str, object],
    army_deltas: Dict[str, object],
    power_updates: Dict[str, object],
    person_changes: List[Dict[str, object]],
    new_armies: List[object],
    content: Optional[GameContent],
    llm_config: Any,
    preflight_event: Event,
    ordered_region_items: Optional[list[tuple[str, object]]] = None,
    ordered_army_items: Optional[list[tuple[str, object]]] = None,
    ordered_power_items: Optional[list[tuple[str, object]]] = None,
) -> str:
    """ADR0014：战略事件战果是同一信封，落库前先拦整组可预见拒收项。

    归属已由转译 event_id 声明；本函数只验信封内容，不再从 reason 推断。
    """
    region_numeric_fields = set(REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + FISCAL_SCORE_FIELDS)
    region_numeric_fields.add("cannon")
    army_numeric_fields = set(ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS)

    def _noop_error(kind: str, target_id: str, raw_field: object, value: object) -> str:
        return (
            f"战略/外敌事件「{event_title or event_id}」战果 {kind}.{target_id}.{raw_field} "
            f"无真实世界状态变化：{value!r}"
        )

    def _jisi_outcome_profile_error() -> str:
        if event_id != "jisi_lubian" or outcome_label not in {"挡于边墙", "入塞被遏"}:
            return ""
        for region_id, raw_changes in (ordered_region_items if ordered_region_items is not None else region_deltas.items()):
            if region_id != "beizhili" or not isinstance(raw_changes, dict):
                continue
            for raw_field, value in raw_changes.items():
                field = REGION_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field != "controlled_by" or value is None:
                    continue
                new_controller = str(value).strip()
                if new_controller and new_controller != "ming":
                    return (
                        f"战略/外敌事件「{event_title or event_id}」事件结局「{outcome_label}」"
                        f"与北直隶控制权战果矛盾：{new_controller}"
                    )
        return ""

    outcome_profile_error = _jisi_outcome_profile_error()
    if outcome_profile_error:
        return outcome_profile_error

    preview_state = copy.deepcopy(state)
    region_items = list(
        ordered_region_items if ordered_region_items is not None else region_deltas.items()
    )
    army_items = list(
        ordered_army_items if ordered_army_items is not None else army_deltas.items()
    )
    # 懒 import：army.delta_section 反向依赖本模块 `_effect_event_ids`，忌模块顶 import。
    from ming_sim.entities.army.delta_section import (
        apply_army_delta_with_cannon_transfer,
    )

    def _region_world_value(region_id: str, field: str) -> object:
        row = db.conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
        if field in FISCAL_SCORE_FIELDS:
            return json.loads(str(row["fiscal"] or "{}")).get(field, 50)
        return row[field]

    def _army_world_value(army_id: str, field: str) -> object:
        row = db.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
        return row[field]

    def _reject_landed_or_unchanged(
        kind: str,
        default_target_id: str,
        landed: List[Dict[str, object]],
        snapshots: List[tuple[object, str, str, object, object]],
        reader,
    ) -> str:
        """按目标/字段拒收：写核已记的非 material，或数值字段写后世界值未变。

        文本字段（REGION/ARMY_TEXT_FIELDS）不计 noop——同旧 _region_noop_error /
        _army_noop_error；快照只收数值，故不在此另开文本判别层。
        """
        for result in landed:
            if _strategic_result_item_has_material_world_state(result):
                continue
            report_target = str(
                result.get("army_id")
                or result.get("region_id")
                or result.get("power_id")
                or default_target_id
            )
            report_field = result.get("field") or kind
            return _noop_error(kind, report_target, report_field, result.get("delta", result))
        for raw_field, read_id, field, before, report_value in snapshots:
            after = reader(read_id, field)
            if str(after) != str(before):
                continue
            return _noop_error(kind, read_id, raw_field, report_value)
        return ""

    db.conn.execute("SAVEPOINT strategic_entity_result_preflight")
    try:
        for region_id, raw_changes in region_items:
            if not isinstance(raw_changes, dict):
                return f"战略/外敌事件「{event_title or event_id}」地区战果须为对象：{region_id}"
            # #1835 S2：领域字段/整数/势力准入交写核；此处只组 noop 快照并消费写核拒收。
            snapshots: List[tuple[object, str, str, object, object]] = []
            seen_fields: set[str] = set()
            region_row = db.conn.execute(
                "SELECT 1 FROM regions WHERE id = ? LIMIT 1", (region_id,),
            ).fetchone()
            if region_row is not None:
                for raw_field, value in raw_changes.items():
                    field = REGION_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                    if field in ("reason", "origin_ref"):
                        continue
                    if field in REGION_TEXT_FIELDS or field in seen_fields:
                        continue
                    if field not in region_numeric_fields:
                        continue
                    seen_fields.add(field)
                    snapshots.append(
                        (raw_field, str(region_id), field, _region_world_value(str(region_id), field), value)
                    )

            landed, refused = db.apply_region_deltas(
                preview_state, preflight_event, None, "档房", {region_id: raw_changes}, commit=False,
            source=Provenance.system_simulation)
            for result in refused:
                if isinstance(result, RejectedItem):
                    return (
                        f"战略/外敌事件「{event_title or event_id}」地区战果拒收："
                        f"{result.reason or result.category}"
                    )
            err = _reject_landed_or_unchanged(
                "region", str(region_id), landed, snapshots, _region_world_value,
            )
            if err:
                return err

        for army_id, raw_changes in army_items:
            if not isinstance(raw_changes, dict):
                return f"战略/外敌事件「{event_title or event_id}」军队战果须为对象：{army_id}"
            # #1835 S2：炮转移/字段/整数准入复用 apply_army_delta_with_cannon_transfer。
            snapshots = []
            seen_fields = set()
            army_row = db.conn.execute(
                "SELECT 1 FROM armies WHERE id = ? LIMIT 1", (army_id,),
            ).fetchone()
            for raw_field, value in raw_changes.items():
                field = ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "origin_ref"):
                    continue
                if field == "cannon_transfer_to":
                    transfer_target = str(value)
                    target_row = db.conn.execute(
                        "SELECT 1 FROM armies WHERE id = ? LIMIT 1", (transfer_target,),
                    ).fetchone()
                    if target_row is not None:
                        snapshots.append(
                            (
                                raw_field,
                                transfer_target,
                                "cannon_equipment",
                                _army_world_value(transfer_target, "cannon_equipment"),
                                value,
                            )
                        )
                    continue
                if army_row is None:
                    continue
                if field in ARMY_TEXT_FIELDS or field in seen_fields:
                    continue
                if field not in army_numeric_fields:
                    continue
                seen_fields.add(field)
                snapshots.append(
                    (raw_field, str(army_id), field, _army_world_value(str(army_id), field), value)
                )

            # 与战略事件真写路同口径（issue/army delta_section）：含随军炮转移键。
            landed, refused = apply_army_delta_with_cannon_transfer(
                db, preview_state, preflight_event, str(army_id), raw_changes,
            source=Provenance.system_simulation)
            for result in refused:
                if isinstance(result, RejectedItem):
                    return (
                        f"战略/外敌事件「{event_title or event_id}」军队战果拒收："
                        f"{result.reason or result.category}"
                    )
            err = _reject_landed_or_unchanged(
                "army", str(army_id), landed, snapshots, _army_world_value,
            )
            if err:
                return err

    finally:
        db.conn.execute("ROLLBACK TO SAVEPOINT strategic_entity_result_preflight")
        db.conn.execute("RELEASE SAVEPOINT strategic_entity_result_preflight")

    # power：回旧跨势力聚合 any(material)；逐字段/快照拒属 a16d5804e 擅自新增口径。
    power_items = ordered_power_items if ordered_power_items is not None else list(power_updates.items())
    if power_items:
        for power_id, raw_changes in power_items:
            if not isinstance(raw_changes, dict):
                return f"战略/外敌事件「{event_title or event_id}」势力战果须为对象：{power_id}"
        power_results: List[Dict[str, object]] = []
        power_rejections: List[RejectedItem] = []
        db.conn.execute("SAVEPOINT strategic_power_result_preflight")
        try:
            for power_id, raw_changes in power_items:
                landed, refused = db.apply_power_deltas(
                    state,
                    {power_id: {key: value for key, value in raw_changes.items() if key != "origin_ref"}},
                    commit=False,
                source=Provenance.system_simulation)
                power_results.extend(landed)
                power_rejections.extend(refused)
        finally:
            db.conn.execute("ROLLBACK TO SAVEPOINT strategic_power_result_preflight")
            db.conn.execute("RELEASE SAVEPOINT strategic_power_result_preflight")
        for result in power_rejections:
            if isinstance(result, RejectedItem):
                return (
                    f"战略/外敌事件「{event_title or event_id}」势力战果拒收："
                    f"{result.reason or result.category}"
                )
        if not any(_strategic_result_item_has_material_world_state(result) for result in power_results):
            power_id, raw_changes = power_items[0]
            return _noop_error("power", str(power_id), "power_updates", raw_changes)

    if person_changes:
        for item in person_changes:
            action = str(item.get("动作") or item.get("action") or "").strip()
            name = character_names._person_change_name(item)
            if action in {"处置", "罢黜"}:
                target_status = "dismissed" if action == "罢黜" else str(item.get("status") or "").strip()
                row = db.conn.execute(
                    "SELECT status FROM characters WHERE name = ?",
                    (name,),
                ).fetchone()
                if row is not None and str(row["status"] or "") == target_status:
                    return _noop_error(
                        "person",
                        name,
                        action,
                        {"status": target_status},
                    )
            if action in {"任命", "调任"}:
                target_office = normalize_office(str(item.get("office") or item.get("new_office") or ""))
                if target_office:
                    row = db.conn.execute(
                        "SELECT c.office, c.office_type, "
                        "COALESCE(co.appointment_tenure, '真除') AS appointment_tenure "
                        "FROM characters c LEFT JOIN character_offices co "
                        "ON co.character_name = c.name WHERE c.name = ?",
                        (name,),
                    ).fetchone()
                    if row is not None:
                        current_office = normalize_office(str(row["office"] or ""))
                        current_type = str(row["office_type"] or "")
                        # 显式名分透传（#1059 codex 同族）：noop 判定须用与真实 apply 一致的
                        # 有效 office_type，否则显式名分（office='诸生'）被 infer 反推成 '生员'≠
                        # current '身名分'，把幂等再声明误判成非 noop。
                        target_type = resolve_office_type_preserving_title(
                            target_office,
                            str(item.get("office_type") or item.get("new_office_type") or ""),
                            current_type,
                            llm_config or db.llm_config,
                        )
                        current_tenure = str(row["appointment_tenure"] or "真除")
                        try:
                            target_tenure = appointment_tenure_from(item)
                        except ValueError:
                            return (
                                f"战略/外敌事件「{event_title or event_id}」人物战果拒收："
                                f"{name}{action} 任别非白名单"
                            )
                        if (
                            target_office == current_office
                            and target_type == current_type
                            and target_tenure == current_tenure
                        ):
                            return _noop_error(
                                "person",
                                name,
                                action,
                                {
                                    "office": target_office,
                                    "office_type": target_type,
                                    "appointment_tenure": target_tenure,
                                },
                            )
            if action != "行止":
                continue
            row = db.conn.execute(
                "SELECT status, location, transit_to FROM characters WHERE name = ?",
                (name,),
            ).fetchone()
            if row is not None:
                departure, departure_error = _admit_transit_departure(
                    item,
                    dict(row),
                    _load_pending_gate_valid_regions(db),
                )
                if departure_error is None and departure is not None and not departure["material"]:
                    return _noop_error("person", name, action, departure)
        probe_content = copy.copy(content)
        if probe_content is not None:
            probe_content.characters = copy.deepcopy(content.characters)
        results: List[Dict[str, object]] = []
        db.conn.execute("SAVEPOINT strategic_person_result_preflight")
        try:
            from ming_sim.entities.character.apply import apply_person_changes
            results, results_rejections = apply_person_changes(
                db,
                copy.deepcopy(state),
                person_changes,
                content=probe_content,
                llm_config=llm_config,
                source=Provenance.system_simulation,
            )
        finally:
            db.conn.execute("ROLLBACK TO SAVEPOINT strategic_person_result_preflight")
            db.conn.execute("RELEASE SAVEPOINT strategic_person_result_preflight")
        for result in results_rejections:
            if isinstance(result, RejectedItem):
                return (
                    f"战略/外敌事件「{event_title or event_id}」人物战果拒收："
                    f"{result.item.get('name') or ''}{result.item.get('动作') or ''} {result.reason}"
                )

    if new_armies:
        # Invisible origins are already itemwise. Do not field-probe them into
        # an envelope failure; the origin loop and the real write still own them.
        field_armies = [
            raw for raw in new_armies
            if not (
                isinstance(raw, dict)
                and (db.effect_origin_rejection(str(raw.get("origin_ref") or "").strip()) or {}).get("category")
                == "unauthorized_affair_origin"
            )
        ]
        if field_armies:
            db.conn.execute("SAVEPOINT strategic_new_army_result_preflight")
            try:
                for raw in field_armies:
                    landed, refused = db.create_armies_from_extraction(
                        state, [raw], actor="档房", commit=False, require_origin=False,
                    source=Provenance.system_simulation)
                    for result in refused:
                        if isinstance(result, RejectedItem):
                            return (
                                f"战略/外敌事件「{event_title or event_id}」新军战果拒收："
                                f"{result.reason or result.category}"
                            )
                    if not any(
                        _strategic_result_item_has_material_world_state(item)
                        for item in landed
                    ):
                        army_label = (
                            str(raw.get("id") or raw.get("name") or "new_army")
                            if isinstance(raw, dict)
                            else "new_army"
                        )
                        return _noop_error("army", army_label, "new_armies", raw)
            finally:
                db.conn.execute("ROLLBACK TO SAVEPOINT strategic_new_army_result_preflight")
                db.conn.execute("RELEASE SAVEPOINT strategic_new_army_result_preflight")

    origin_items = (
        [("地区", item) for _, item in (
            ordered_region_items if ordered_region_items is not None else region_deltas.items()
        )]
        + [("军队", item) for _, item in (
            ordered_army_items if ordered_army_items is not None else army_deltas.items()
        )]
        + [("势力", item) for _, item in power_items]
        + [("人物", item) for item in person_changes]
        + [("新军", item) for item in new_armies]
    )
    admissible_origin = False
    saw_unauthorized = False
    for kind, item in origin_items:
        origin_ref = item.get("origin_ref") if isinstance(item, dict) else None
        origin_error = db.effect_origin_rejection(origin_ref)
        if not origin_error:
            admissible_origin = True
            continue
        # A single unauthorized affair stays itemwise at apply so a sibling
        # result can still carry the event. If every world result is outside
        # the frozen visible set, the envelope has no admissible battle result.
        if origin_error.get("category") == "unauthorized_affair_origin":
            saw_unauthorized = True
            continue
        return (
            f"战略/外敌事件「{event_title or event_id}」{kind}战果来源拒收："
            f"{origin_error.get('reason') or origin_error.get('category') or ''}"
        )
    if origin_items and not admissible_origin and saw_unauthorized:
        return (
            f"战略/外敌事件「{event_title or event_id}」战果来源不在本段冻结可见引用内"
        )

    return ""


def preflight_declared_event_effects(
    db: GameDB, state: GameState, items: list[tuple[str, dict]],
    open_affair_ids: set[int] | None = None,
) -> dict[str, str]:
    """C3: decide an event-owned effect envelope before any of its fields write.

    Same judgment runs once here; the apply path does not re-gate after writes.
    ``open_affair_ids`` is the same frozen visible set apply will arm, so origin
    checks here and at write share one authority.
    """
    groups: dict[str, list[dict]] = {}
    for event_id, item in items:
        if event_id:
            groups.setdefault(event_id, []).append(item)
    if not groups:
        return {}
    previous_authorized = getattr(db, "_batch_authorized_open_affair_ids", None)
    previous_frozen = getattr(db, "_batch_frozen_open_affair_ids", None)
    if open_affair_ids is not None:
        frozen_affairs = set(open_affair_ids)
        db._batch_authorized_open_affair_ids = frozen_affairs
        db._batch_frozen_open_affair_ids = frozen_affairs
    try:
        return _preflight_declared_event_groups(db, state, groups)
    finally:
        if open_affair_ids is not None:
            db._batch_authorized_open_affair_ids = previous_authorized
            db._batch_frozen_open_affair_ids = previous_frozen


def _preflight_declared_event_groups(
    db: GameDB, state: GameState, groups: dict[str, list[dict]],
) -> dict[str, str]:
    from ming_sim.issues import gather_candidate_events
    content = db.content
    candidates = {event.id for event in gather_candidate_events(state, db)}
    rejected: dict[str, str] = {}
    pseudo_event = Event(id="season", title="月末整体推演", kind="月末", summary="",
                         urgency=0, severity=0, credibility=100, interests=[], audiences=[])
    from ming_sim.issues import (
        FISCAL_LEVY_EVENT_CATEGORY,
        _event_outcome_label,
        _fiscal_levy_normalized_terminal_reason_or_abort,
        _merge_first_event_outcome,
        petition_outcome_is_admissible,
    )
    for event_id, group in groups.items():
        event = content.event_by_id.get(event_id)
        if event is None:
            rejected[event_id] = f"效果归属的事件不存在：{event_id}"
            continue
        # #1892：三饷请旨的亲裁结局与战略节点信封不同路——它不要求世界状态主账结果
        # （三饷的征收由饷率通道按终局标签核算），只要求标签落在事件自声明的封闭集内，
        # 且事件账里已有请旨答复、终态仍空。归一失败响亮失败（ADR 0014），不静默丢弃亲裁。
        if getattr(event, "category", "") == FISCAL_LEVY_EVENT_CATEGORY:
            if not petition_outcome_is_admissible(state, db, event_id, content):
                rejected[event_id] = f"三饷事项当前不能由亲裁置定结局：{event_id}"
                continue
            outcome: dict[str, object] = {}
            for item in group:
                _merge_first_event_outcome(outcome, item.get("事件结局") or {}, event_id)
            raw_label = _event_outcome_label(outcome, event_id)
            if not raw_label:
                # 留中／未答毕：本疏已答而事件未终，不写终态（合法，不是缺项）。
                continue
            _fiscal_levy_normalized_terminal_reason_or_abort(event, raw_label, state)
            continue
        if not _is_strategic_foreign_node_event(event):
            rejected[event_id] = f"效果归属的战略事件不存在：{event_id}"
            continue
        if event_id not in candidates or db.event_terminal_state(event_id) or event.auto_trigger:
            rejected[event_id] = f"战略事件当前不能触发：{event_id}"
            continue
        if not any(
            isinstance(issue, dict)
            and str(issue.get("origin_kind") or "").lower() == "event_pool"
            and str(issue.get("id") or issue.get("origin_ref") or "").strip() == event_id
            for item in group for issue in (item.get("new_issues") or [])
        ):
            rejected[event_id] = f"战略事件缺 event_pool 声明：{event_id}"
            continue
        outcome = {}
        for item in group:
            outcome.update(item.get("事件结局") or {})
        label, error = _strategic_event_outcome_label_or_error(event_id, {"事件结局": outcome}, content)
        if error:
            rejected[event_id] = error
            continue
        region_items = [(key, value) for item in group for key, value in (item.get("region_delta") or {}).items()]
        army_items = [(key, value) for item in group for key, value in (item.get("army_delta") or {}).items()]
        power_items = [(key, value) for item in group for key, value in (item.get("power_updates") or {}).items()]
        people = character_names._canonicalize_person_change_names(
            [person for item in group for person in (item.get("人物变更") or [])], content, db,
        )
        new_armies = [army for item in group for army in (item.get("new_armies") or [])]
        if not (region_items or army_items or power_items or people or new_armies):
            rejected[event_id] = f"战略事件缺世界状态主账结果：{event_id}"
            continue
        error = _strategic_event_result_preflight_error(
            db, state, event_id, event.title, label, dict(region_items), dict(army_items),
            dict(power_items), people, new_armies, content, db.llm_config, pseudo_event,
            ordered_region_items=region_items, ordered_army_items=army_items,
            ordered_power_items=power_items,
        )
        if error:
            rejected[event_id] = error
    return rejected


def _strategic_result_item_has_material_world_state(item: Dict[str, object]) -> bool:
    if item.get("created"):
        return True
    for old_key, new_key in (
        ("old", "new"),
        ("old_status", "status"),
        ("old_office", "new_office"),
        ("old_office_type", "office_type"),
        ("old_loyalty", "new_loyalty"),
        ("old_power", "new_power"),
        ("old_style", "new_style"),
    ):
        if old_key in item and new_key in item and str(item.get(old_key)) != str(item.get(new_key)):
            return True
    action = str(item.get("动作") or item.get("action") or "").strip()
    if action in {"处置", "罢黜"} and item.get("status"):
        return True
    if action in {"任命", "调任"} and (
        item.get("new_office") or item.get("office")
    ):
        return True
    if action == "易主" and item.get("new_power"):
        return True
    if "delta" in item:
        delta = item.get("delta")
        if delta is None:
            return False
        try:
            return int(delta) != 0
        except (TypeError, ValueError):
            return bool(delta)
    return False



_NESTED_DICT_FIELDS = frozenset({"region_delta", "army_delta", "power_updates"})


def sanitize_delta_shape(
    extracted: dict,
    *,
    source: Provenance = Provenance.unknown,
) -> tuple[dict, list[tuple[str, RejectedItem]]]:
    """Return (cleaned_delta, validate-layer rejections) per ADR 0015 (r4 终态)。

    分层终态（#649 票面 r3/r4）：顶层非 dict（连 section 都拆不出）仍 fail loud 整份
    重产；未知顶层 key＝可拆 section → 按段拒收留痕不整份退（原整份 ValueError 属
    ADR 0015 待施工纠正面，#649 纠正）；section/list/entity shape 缺陷逐项移除并
    返回拒收记录。Flat faction integers remain legal; flat class items reach the
    class adapter and are rejected per item as ``invalid_enum`` under the #564 contract.

    拒收在产生处即为 canonical :class:`~ming_sim.applier.RejectedItem`；section 名作为
    框架上下文与项配对返回，不塞进项级四字段。
    """
    from ming_sim.simulation import (  # 懒 import 避 issues↔simulation 循环
        DECLARATION_EFFECT_FIELDS,
    )

    if not isinstance(extracted, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(extracted).__name__}")
    cleaned = dict(extracted)
    rejections: list[tuple[str, RejectedItem]] = []

    def _shape_reject(section: str, item: dict, reason: str) -> None:
        rejections.append((
            section,
            RejectedItem(item=item, reason=reason, category="invalid_shape", source=source),
        ))

    for key, value in list(extracted.items()):
        if key not in DECLARATION_EFFECT_FIELDS:
            # ADR 0015 r4：未知顶层 key＝可拆 section，拒该段留痕、其余段照落，不整份退。
            # #1835 S3：退役 `_module_rejections` 不再特免，与普通未知字段同形拒收。
            cleaned.pop(key, None)
            _shape_reject(
                key,
                {"raw_value": value},
                f"未知 delta 顶层字段「{key}」(canonicalize 后)；疑拼写错(如 地区变更↔地区变化)。"
                "apply 不会消费它＝静默无效，按段拒收留痕（ADR 0015），请改用合法 key。",
            )
            continue
        if value is None:
            continue
        expected = DECLARATION_EFFECT_FIELDS[key]
        if isinstance(expected, dict):
            if not isinstance(value, dict):
                cleaned[key] = {}
                _shape_reject(key, {"raw_value": value}, f"delta 字段 {key} 必须是 object(dict)，实得 {type(value).__name__}")
                continue
            if key in _NESTED_DICT_FIELDS:
                section_clean = dict(value)
                for ent, sub in value.items():
                    if not isinstance(sub, dict):
                        section_clean.pop(ent, None)
                        _shape_reject(
                            key,
                            {"entity_id": str(ent), "raw_value": sub},
                            f"delta 字段 {key}.{ent} 必须是 object(dict)，实得 {type(sub).__name__}",
                        )
                cleaned[key] = section_clean
        elif isinstance(expected, list):
            if not isinstance(value, list):
                cleaned[key] = []
                _shape_reject(key, {"raw_value": value}, f"delta 字段 {key} 必须是 array(list)，实得 {type(value).__name__}")
                continue
            section_clean = []
            for i, item in enumerate(value):
                if not isinstance(item, dict):
                    _shape_reject(
                        key,
                        {"raw_value": item},
                        f"delta 字段 {key}[{i}] 必须是 object(dict)，实得 {type(item).__name__}",
                    )
                else:
                    section_clean.append(item)
            cleaned[key] = section_clean
    return cleaned, rejections


def validate_delta_shape(extracted: dict) -> None:
    """Validate unsplittable delta shape; split-capable bad items are ADR0015 rejections."""
    sanitize_delta_shape(extracted)


