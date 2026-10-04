"""Issue 系统：候选事件、issue 立项/推进/结案、tracker 输出落地、inertia 漂移。L6。

通过 bind_content() 注入 GameContent（取 EVENTS/SEED_EVENTS/EVENT_BY_ID）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

import copy
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from ming_sim.applier import atomic
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET
from ming_sim.constants import (
    TURN_UNIT, REGION_SCORE_FIELDS, REGION_QUANTITY_FIELDS, REGION_TEXT_FIELDS,
    ARMY_SCORE_FIELDS, ARMY_QUANTITY_FIELDS, ARMY_TEXT_FIELDS, FISCAL_SCORE_FIELDS,
    BUILDING_SCORE_FIELDS, BUILDING_QUANTITY_FIELDS, BUILDING_TEXT_FIELDS,
    POWER_SCORE_FIELDS, POWER_TEXT_FIELDS, CHARACTER_TEXT_FIELDS,
    REGION_FIELD_ALIASES, ARMY_FIELD_ALIASES, POWER_FIELD_ALIASES, GATE_TABLES,
    LEVY_DISPLACEMENT_RATE,
    BANDIT_ABSORPTION_FIELDS,
    BANDIT_ABSORPTION_PERSONS_PER_STRENGTH,
    RECOVERY_PERSONS_PER_WAN,
    RECOVERY_GRANT_ACTIONS,
    RECOVERY_OUTCOME_FACTORS,
)
from ming_sim.content import GameContent
from ming_sim.context import victory_status
from ming_sim.distance import DistanceMatrix
from ming_sim.paths import bundled_path
from ming_sim.db import (
    GameDB,
    POPULATION_UNIT_PERSONS,
    _LEVERAGE_FACTIONS,
    _approx_wanliang,
    compute_loyalty_soft_adjust,
    fold_loyalty_alias_delta,
    infer_office_type_from_office,
    latched_army_field_effect_permitted,
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
    _strict_int,
)
from ming_sim.models import Event, GameState, effect_dict_has_work, is_vassal_prince, loads_effect_dict
from ming_sim.participant_roster import project_execution_liability_parties
from ming_sim.person_archive_contract import (
    PERSON_ALLEGIANCE_CHANGE_WAYS,
    PERSON_IDENTITY_TITLES,
    PERSON_STATUSES,
    normalize_reason_code,
    resolve_person_transition,
)
from ming_sim.entities.character.normalize import normalize_person_changes
from ming_sim.entities.character import names as character_names
from ming_sim.token_stats import tlog


_CHARACTER_TEXT_GATE_RE = re.compile(r"^character\.([^.]+)\.([A-Za-z_][A-Za-z0-9_]*)$")
_PENDING_PERSON_GATE_FIELDS = {
    "status", "status_reason", "reason_code", "location", "transit_to", "power_id", "office", "office_type",
}
_PENDING_POWER_GATE_FIELDS = {"leverage", "military_strength", "supply"}
_TEXT_CONDITION_RE = re.compile(r"^\s*(==|!=)\s*([^\s]+)\s*$")
_NUMERIC_CONDITION_RE = re.compile(r"^\s*(>=|<=|>|<|==)\s*(-?\d+)\s*$")



def _load_pending_gate_shadow_rows(db: GameDB) -> Dict[str, Dict[str, str]]:
    shadow_rows: Dict[str, Dict[str, str]] = {}
    for row in db.conn.execute(
        "SELECT name, status, status_reason, reason_code, location, transit_to, "
        "power_id, office, office_type FROM characters"
    ).fetchall():
        shadow_rows[str(row["name"])] = {
            "status": str(row["status"] or "active"),
            "status_reason": str(row["status_reason"] or ""),
            "reason_code": str(row["reason_code"] or ""),
            "location": str(row["location"] or ""),
            "transit_to": str(row["transit_to"] or ""),
            "power_id": str(row["power_id"] or "ming"),
            "office": str(row["office"] or ""),
            "office_type": str(row["office_type"] or ""),
        }
    return shadow_rows


def _load_pending_gate_power_shadow_rows(db: GameDB) -> Dict[str, Dict[str, int]]:
    power_shadow_rows: Dict[str, Dict[str, int]] = {}
    for row in db.conn.execute("SELECT id, leverage, military_strength, supply FROM powers").fetchall():
        power_shadow_rows[str(row["id"])] = {
            "leverage": int(row["leverage"] or 0),
            "military_strength": int(row["military_strength"] or 0),
            "supply": int(row["supply"] or 0),
        }
    return power_shadow_rows


def _load_pending_gate_valid_regions(db: GameDB) -> set[str]:
    return {
        str(row["id"])
        for row in db.conn.execute("SELECT id FROM regions").fetchall()
    }


TRAVEL_SPEED_BY_TONE = {"常行": 1.0, "加急": 1.5, "星夜兼程": 2.0}
TravelTone = Literal[*TRAVEL_SPEED_BY_TONE]


def normalize_travel_tone(value: object) -> str:
    """Validate the canonical typed travel tone; never infer or downgrade it."""
    tone = "常行" if value is None else str(value).strip()
    if tone not in TRAVEL_SPEED_BY_TONE:
        raise DeclarationDataError("行程语气不在闭合枚举")
    return tone


def _admit_transit_departure(
    item: Dict[str, object],
    row: Dict[str, object],
    valid_regions: set[str],
) -> tuple[Optional[Dict[str, object]], Optional[tuple[str, str]]]:
    """Return the canonical, write-free departure projection or its item rejection."""
    if "location" in item:
        return None, ("行止只接受 transit_to 启程", "invalid_transition")
    transit_to = str(item.get("transit_to") or "").strip()
    if not transit_to:
        return None, ("transit_to 缺失", "missing_field")
    if str(row.get("status") or "active") != "active":
        return None, ("行止 仅适用于 active 人物", "invalid_transition")
    if transit_to not in valid_regions:
        return None, ("transit_to 地区不存在", "missing_ref")
    try:
        tone = normalize_travel_tone(item.get("行程语气"))
    except DeclarationDataError:
        return None, ("行程语气不在闭合枚举", "invalid_enum")
    previous_destination = str(row.get("transit_to") or "")
    if previous_destination and previous_destination != transit_to:
        return None, ("在途人物不可改道", "invalid_transition")
    location = str(row.get("location") or "")
    if location not in valid_regions:
        return None, None
    matrix = DistanceMatrix.from_file(bundled_path("content", "distance_matrix.json"))
    distance = matrix.travel_time(location, transit_to)
    if not math.isfinite(distance) or distance < 0 or (location != transit_to and distance <= 0):
        raise ValueError(f"invalid baked travel time: {location!r} -> {transit_to!r}")
    terminal_location = transit_to if distance == 0 else location
    terminal_transit_to = "" if distance == 0 else transit_to
    return {
        "location": terminal_location,
        "transit_to": terminal_transit_to,
        "distance": distance,
        "tone": tone,
        "speed": None if distance == 0 else TRAVEL_SPEED_BY_TONE[tone],
        "material": (
            terminal_location != location
            or terminal_transit_to != previous_destination
        ),
    }, None


def _pending_person_changes_block_event_gate(
    ev: Event,
    pending_person_changes: List[Dict[str, object]],
    db: GameDB,
    *,
    content: Optional[GameContent] = None,
    shadow_rows: Optional[Dict[str, Dict[str, str]]] = None,
    power_shadow_rows: Optional[Dict[str, Dict[str, int]]] = None,
    valid_regions: Optional[set[str]] = None,
) -> bool:
    """Re-check character status gates against accepted same-turn person changes.

    Status-changing person writes intentionally remain post-issue to preserve settlement
    ordering, but event_pool must not ignore a same-turn removal of an event actor.
    """
    from ming_sim.issues import _GATE_AGG_FUNCS, _gate_sql_field
    if not pending_person_changes or not ev.trigger_gate:
        return False
    from ming_sim.entities.character.appointment import _is_exclusive_office
    pending_fields: Dict[str, Dict[str, str]] = {}
    pending_power_fields: Dict[str, Dict[str, int]] = {}
    shadow_rows = (
        _load_pending_gate_shadow_rows(db)
        if shadow_rows is None
        else {name: dict(row) for name, row in shadow_rows.items()}
    )
    power_shadow_rows = (
        _load_pending_gate_power_shadow_rows(db)
        if power_shadow_rows is None
        else {power_id: dict(row) for power_id, row in power_shadow_rows.items()}
    )
    valid_regions = _load_pending_gate_valid_regions(db) if valid_regions is None else set(valid_regions)

    def row_value(row: Dict[str, str], field: str, default: str = "") -> str:
        return str(row.get(field) or default)

    def character_row(name: str) -> Optional[Dict[str, str]]:
        return shadow_rows.get(name)

    def overlay(name: str, field: str, value: object) -> None:
        value_text = str(value or "").strip()
        pending_fields.setdefault(name, {})[field] = value_text
        if name in shadow_rows:
            shadow_rows[name][field] = value_text

    def power_row(power_id: str) -> Optional[Dict[str, int]]:
        return power_shadow_rows.get(power_id)

    def overlay_power_delta(power_id: object, raw_changes: object) -> None:
        pid = str(power_id or "").strip()
        if not pid or not isinstance(raw_changes, dict):
            return
        row = power_row(pid)
        if row is None:
            return
        for raw_field, value in raw_changes.items():
            field = POWER_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
            if field in {"reason", "last_action"}:
                continue
            if field not in _PENDING_POWER_GATE_FIELDS:
                continue
            try:
                if isinstance(value, bool) or isinstance(value, float):
                    raise ValueError("非整数 delta")
                delta = int(value)
            except (TypeError, ValueError):
                continue
            old_value = int(row[field])
            new_value = max(0, min(100, old_value + delta))
            if new_value == old_value:
                continue
            row[field] = new_value
            pending_power_fields.setdefault(pid, {})[field] = new_value

    def pending_power_gate_value(key: str) -> Optional[int]:
        parts = key.split(".")
        if not parts or parts[0] != "power":
            return None
        agg = None
        if parts[-1] in _GATE_AGG_FUNCS:
            agg = parts[-1]
            parts = parts[:-1]
        if len(parts) != 3:
            return None
        _, id_segment, raw_field = parts
        field = _gate_sql_field("power", raw_field, key, kind="numeric")
        if field not in _PENDING_POWER_GATE_FIELDS:
            return None
        ids = [pid for pid in id_segment.split("|") if pid]
        if not ids or not any(field in pending_power_fields.get(pid, {}) for pid in ids):
            return None
        values: List[int] = []
        for pid in ids:
            row = power_row(pid)
            if row is None:
                return None
            values.append(int(row[field]))
        if len(values) == 1:
            return values[0]
        if agg is None:
            agg = "min"
        return int(_GATE_AGG_FUNCS[agg](values))

    def current_title_kind(row: Dict[str, str]) -> str:
        current_office = row_value(row, "office").strip()
        current_office_type = row_value(row, "office_type").strip()
        if (
            not current_office
            or current_office_type == "身名分"
            or current_office in PERSON_IDENTITY_TITLES
        ):
            return "身名分"
        return "职名分"

    def identity_title_for_allegiance(item: Dict[str, object], new_power: str) -> str:
        title = str(item.get("new_title") or item.get("title") or "").strip()
        if title:
            return title if title in PERSON_IDENTITY_TITLES else ""
        way = str(item.get("方式") or item.get("way") or "").strip()
        if new_power == "ming" or way == "主动归附":
            return "归附"
        return "降臣"

    for item in pending_person_changes:
        name = str(item.get("name") or "").strip()
        action = str(item.get("动作") or "").strip()
        if not name:
            continue
        if content is not None:
            from ming_sim.session import _find_existing_minister
            canon = _find_existing_minister(content, name, db)
            if canon:
                name = canon
        row = character_row(name)
        if row is None:
            continue
        cur_status = row_value(row, "status", "active")
        if action in {"罢黜", "处置"}:
            reason_text = str(item.get("reason") or item.get("status_reason") or "")
            reason_code = normalize_reason_code(item.get("reason_code"))
            if action == "罢黜":
                status = "dismissed"
            else:
                status = str(item.get("status") or "").strip()
                if status in {"active"}:
                    continue
            if status not in PERSON_STATUSES:
                continue
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=normalize_reason_code(item.get("reason_code")),
            )
            if transition.startswith("reject:"):
                continue
            overlay(name, "status", status)
            overlay(name, "status_reason", reason_text)
            overlay(name, "reason_code", reason_code if reason_code else "")
            overlay(name, "office", "")
            overlay(name, "transit_to", "")
        elif action == "行止":
            departure, _error = _admit_transit_departure(item, row, valid_regions)
            if departure is None:
                continue
            overlay(name, "location", departure["location"])
            overlay(name, "transit_to", departure["transit_to"])
        elif action == "易主":
            way = str(item.get("方式") or item.get("way") or "").strip()
            backlash = item.get("反噬", item.get("backlash"))
            if not way:
                continue
            if way not in PERSON_ALLEGIANCE_CHANGE_WAYS:
                continue
            if not isinstance(backlash, dict):
                continue
            if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
                continue
            new_power = str(item.get("new_power") or "").strip()
            if not new_power:
                continue
            if new_power not in power_shadow_rows:
                continue
            if row_value(row, "power_id", "ming").strip() == new_power:
                continue
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=str(row_value(row, "reason_code") or item.get("reason_code") or ""),
            )
            if transition.startswith("reject:"):
                continue
            new_title = identity_title_for_allegiance(item, new_power)
            if not new_title:
                continue
            overlay(name, "power_id", new_power)
            overlay(name, "status", "active")
            overlay(name, "status_reason", str(item.get("reason") or ""))
            overlay(name, "reason_code", "")
            overlay(name, "office", new_title)
            overlay(name, "office_type", "身名分")
            overlay(name, "transit_to", "")
            for power_id, raw_changes in backlash.items():
                overlay_power_delta(power_id, raw_changes)
        elif action in {"任命", "调任"}:
            new_office = str(item.get("office") or item.get("new_office") or "").strip()
            if not new_office:
                continue
            normalized_office = normalize_office(new_office)
            if content is not None:
                character = content.characters.get(name)
                if character is None or is_vassal_prince(character):
                    continue
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=str(row_value(row, "reason_code") or item.get("reason_code") or ""),
                current_title_kind=current_title_kind(row),
            )
            if transition.startswith("reject:"):
                continue
            if row_value(row, "power_id", "ming") not in {"", "ming"}:
                continue
            overlay(name, "status", "active")
            if cur_status == "active":
                overlay(name, "status_reason", "")
            else:
                overlay(name, "status_reason", str(item.get("reason") or "") or "诏书任命")
            overlay(name, "reason_code", "")
            overlay(name, "office", normalized_office)
            # 显式名分透传（#1059 codex 同族）：事件闸预览的 overlay 须与真实 apply 一致，
            # 显式名分（office='诸生'）不得被 infer 反推成 '生员'，否则 shadow 盘面与落库分岔。
            overlay(
                name,
                "office_type",
                resolve_office_type_preserving_title(
                    normalized_office,
                    str(item.get("office_type") or item.get("new_office_type") or ""),
                    row_value(row, "office_type"),
                    db.llm_config,
                ),
            )
            overlay(name, "transit_to", "")
            new_parts = [p for p in normalized_office.split(",") if _is_exclusive_office(p)]
            if new_parts:
                for other_name in set(shadow_rows):
                    if other_name == name:
                        continue
                    other_row = character_row(other_name)
                    if other_row is None:
                        continue
                    if row_value(other_row, "status", "active") != "active":
                        continue
                    if row_value(other_row, "power_id", "ming") not in {"", "ming"}:
                        continue
                    current_parts = [p.strip() for p in row_value(other_row, "office").split(",") if p.strip()]
                    kept = [p for p in current_parts if p not in new_parts]
                    if len(kept) == len(current_parts):
                        continue
                    displaced_office = "听用候铨" if not kept else ",".join(kept)
                    old_type = row_value(other_row, "office_type")
                    displaced_type = (
                        "身名分"
                        if not kept
                        else infer_office_type_from_office(displaced_office, old_type, db.llm_config)
                    )
                    overlay(other_name, "office", displaced_office)
                    overlay(other_name, "office_type", displaced_type)
                    if not kept:
                        overlay(other_name, "status_reason", "被顶替")
                        overlay(other_name, "reason_code", "被顶替")
                        overlay(other_name, "transit_to", "")
        else:
            continue

    if not pending_fields and not pending_power_fields:
        return False
    for key, cond in ev.trigger_gate.items():
        match = _CHARACTER_TEXT_GATE_RE.fullmatch(str(key))
        if not match:
            continue
        name, field = match.groups()
        if field not in _PENDING_PERSON_GATE_FIELDS:
            continue
        fields = pending_fields.get(name)
        if not fields or field not in fields:
            continue
        cond_match = _TEXT_CONDITION_RE.fullmatch(str(cond))
        if cond_match is None:
            continue
        op, expected = cond_match.groups()
        actual = fields[field]
        if op == "==" and actual != expected:
            return True
        if op == "!=" and actual == expected:
            return True
    for key, cond in ev.trigger_gate.items():
        actual = pending_power_gate_value(str(key))
        if actual is None:
            continue
        cond_match = _NUMERIC_CONDITION_RE.fullmatch(str(cond))
        if cond_match is None:
            continue
        op, expected_text = cond_match.groups()
        expected = int(expected_text)
        if op == ">=" and not actual >= expected:
            return True
        if op == "<=" and not actual <= expected:
            return True
        if op == ">" and not actual > expected:
            return True
        if op == "<" and not actual < expected:
            return True
        if op == "==" and not actual == expected:
            return True
    return False


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


def _event_outcome_label(raw_outcomes: object, event_id: str) -> str:
    if not isinstance(raw_outcomes, dict):
        return ""
    raw = raw_outcomes.get(event_id)
    if isinstance(raw, dict):
        raw = raw.get("结局") or raw.get("outcome") or raw.get("label")
    return str(raw or "").strip()


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
    legacy_mods = db.legacy_modifiers(state)
    region_valid_fields = set(REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + REGION_TEXT_FIELDS + FISCAL_SCORE_FIELDS)
    region_valid_fields.add("cannon")
    region_numeric_fields = set(REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + FISCAL_SCORE_FIELDS)
    region_numeric_fields.add("cannon")
    army_valid_fields = set(ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS + ARMY_TEXT_FIELDS)
    army_numeric_fields = set(ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS)

    def _int_delta_error(kind: str, target_id: str, raw_field: object, value: object) -> str:
        if isinstance(value, bool) or isinstance(value, float):
            return f"战略/外敌事件「{event_title or event_id}」战果 {kind}.{target_id}.{raw_field} 值非整数：{value!r}"
        try:
            int(value)
        except (TypeError, ValueError):
            return f"战略/外敌事件「{event_title or event_id}」战果 {kind}.{target_id}.{raw_field} 值非整数：{value!r}"
        return ""

    def _noop_error(kind: str, target_id: str, raw_field: object, value: object) -> str:
        return (
            f"战略/外敌事件「{event_title or event_id}」战果 {kind}.{target_id}.{raw_field} "
            f"无真实世界状态变化：{value!r}"
        )

    def _region_noop_error(region_id: str, row: sqlite3.Row, raw_field: object, value: object) -> str:
        field = REGION_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
        if field == "reason":
            return ""
        if field == "cannon":
            delta = int(value)
            cap = int(row["city_level"]) * 8
            old_value = int(row["cannon"])
            if max(0, min(cap, old_value + delta)) == old_value:
                return _noop_error("region", region_id, raw_field, value)
            return ""
        if field in FISCAL_SCORE_FIELDS:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
            old_value = int(fiscal.get(field, 50))
            delta = int(value)
            net_pct = int(((legacy_mods.get("regions") or {})
                           .get(region_id) or {}).get(field, 0) or 0)
            if net_pct:
                delta = db.apply_legacy_pct(delta, net_pct)
            if max(0, min(100, old_value + delta)) == old_value:
                return _noop_error("region", region_id, raw_field, value)
            return ""
        if field in REGION_SCORE_FIELDS:
            old_value = int(row[field])
            delta = int(value)
            net_pct = int(((legacy_mods.get("regions") or {})
                           .get(region_id) or {}).get(field, 0) or 0)
            if net_pct:
                delta = db.apply_legacy_pct(delta, net_pct)
            if max(0, min(100, old_value + delta)) == old_value:
                return _noop_error("region", region_id, raw_field, value)
            return ""
        if field in REGION_QUANTITY_FIELDS:
            old_value = int(row[field])
            if max(0, old_value + int(value)) == old_value:
                return _noop_error("region", region_id, raw_field, value)
            return ""
        if field in REGION_TEXT_FIELDS:
            return ""
        return ""

    def _army_noop_error(army_id: str, row: sqlite3.Row, raw_field: object, value: object) -> str:
        field = ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
        if field == "reason":
            return ""
        # #319：latched 静默 no-op 与写缝同口径——战略信封预检须拒整封，不得半落兄弟结果。
        # loyalty 不进此函数：caller 对 field=="loyalty" 先 continue，再走
        # fold_loyalty_alias_delta + latched_army_field_effect_permitted +
        # compute_loyalty_soft_adjust；勿在此再堆 loyalty 专属预测（死分支）。
        if bool(row["is_mutinied"]):
            if field == "manpower":
                if not latched_army_field_effect_permitted(field, value):
                    return _noop_error("army", army_id, raw_field, value)
            else:
                return _noop_error("army", army_id, raw_field, value)
        if field == "cannon_equipment":
            old_value = int(row[field])
            if max(0, min(12, old_value + int(value))) == old_value:
                return _noop_error("army", army_id, raw_field, value)
            return ""
        if field == "arrears":
            old_value = int(row[field])
            if max(0, old_value + int(value)) == old_value:
                return _noop_error("army", army_id, raw_field, value)
            return ""
        if field in ARMY_SCORE_FIELDS:
            old_value = int(row[field])
            delta = int(value)
            net_pct = int(((legacy_mods.get("armies") or {})
                           .get(army_id) or {}).get(field, 0) or 0)
            if net_pct:
                delta = db.apply_legacy_pct(delta, net_pct)
            if max(0, min(100, old_value + delta)) == old_value:
                return _noop_error("army", army_id, raw_field, value)
            return ""
        if field in ARMY_QUANTITY_FIELDS:
            old_value = int(row[field])
            if max(0, old_value + int(value)) == old_value:
                return _noop_error("army", army_id, raw_field, value)
            return ""
        if field in ARMY_TEXT_FIELDS:
            return ""
        return ""

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
    db.conn.execute("SAVEPOINT strategic_entity_result_preflight")
    try:
        for region_id, raw_changes in (ordered_region_items if ordered_region_items is not None else region_deltas.items()):
            row = db.conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
            if row is None:
                return f"战略/外敌事件「{event_title or event_id}」战果引用未入库地区：{region_id}"
            if not isinstance(raw_changes, dict):
                return f"战略/外敌事件「{event_title or event_id}」地区战果须为对象：{region_id}"
            for raw_field, value in raw_changes.items():
                field = REGION_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "origin_ref"):
                    continue
                if field not in region_valid_fields:
                    return f"战略/外敌事件「{event_title or event_id}」战果引用非法地区字段：{raw_field}"
                if field in region_numeric_fields:
                    err = _int_delta_error("region", region_id, raw_field, value)
                    if err:
                        return err
                if field == "controlled_by":
                    controller = str(value).strip() if value is not None else ""
                    if (
                        value is None
                        or not controller
                        or controller.lower() == "null"
                        or db.conn.execute(
                            "SELECT 1 FROM powers WHERE id = ? LIMIT 1",
                            (controller,),
                        ).fetchone() is None
                    ):
                        return (
                            f"战略/外敌事件「{event_title or event_id}」地区战果 controlled_by "
                            f"必须是 powers.id 中的非空真实势力 id：{value!r}"
                        )
                err = _region_noop_error(region_id, row, raw_field, value)
                if err:
                    return err

            db.apply_region_deltas(
                preview_state, preflight_event, None, "档房", {region_id: raw_changes}, commit=False,
            source=Provenance.system_simulation)

        for army_id, raw_changes in (ordered_army_items if ordered_army_items is not None else army_deltas.items()):
            row = db.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
            if row is None:
                return f"战略/外敌事件「{event_title or event_id}」战果引用未入库军队：{army_id}"
            if not isinstance(raw_changes, dict):
                return f"战略/外敌事件「{event_title or event_id}」军队战果须为对象：{army_id}"
            if "cannon_transfer_to" in raw_changes:
                target_id = raw_changes["cannon_transfer_to"]
                target = (db.conn.execute("SELECT cannon_equipment, is_mutinied FROM armies WHERE id=?", (target_id,)).fetchone()
                          if isinstance(target_id, str) and target_id else None)
                cannon_keys = [key for key in raw_changes
                               if ARMY_FIELD_ALIASES.get(key, key) == "cannon_equipment"]
                if (target is None or target_id == army_id or len(cannon_keys) != 1
                        or _int_delta_error("army", army_id, cannon_keys[0], raw_changes[cannon_keys[0]])
                        or _strict_int(raw_changes[cannon_keys[0]]) >= 0):
                    return f"战略/外敌事件「{event_title or event_id}」随军炮转移目标或负数拟转量非法：{army_id}"
                if int(target["cannon_equipment"]) >= 12:
                    return _noop_error("army", army_id, "cannon_transfer_to", target_id)
                if bool(target["is_mutinied"]) and not latched_army_field_effect_permitted(
                    "cannon_equipment", -_strict_int(raw_changes[cannon_keys[0]]),
                ):
                    return _noop_error("army", target_id, "cannon_transfer_to", target_id)
            # #320：loyalty 规范键/别名与写核同语义——先逐叶类型/字段校验，净合计后再一次
            # 软钳判 no-op；不得按 alias 分项拿旧值独立判 no-op。
            first_loyalty_raw_field: object | None = None
            for raw_field, value in raw_changes.items():
                field = ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
                if field in ("reason", "origin_ref"):
                    continue
                if field == "cannon_transfer_to":
                    continue
                if field not in army_valid_fields:
                    return f"战略/外敌事件「{event_title or event_id}」战果引用非法军队字段：{raw_field}"
                if field in army_numeric_fields:
                    err = _int_delta_error("army", army_id, raw_field, value)
                    if err:
                        return err
                if field == "loyalty":
                    if first_loyalty_raw_field is None:
                        first_loyalty_raw_field = raw_field
                    continue  # 净合计后统一 no-op 判定
                err = _army_noop_error(army_id, row, raw_field, value)
                if err:
                    return err
            loyalty_net = fold_loyalty_alias_delta(raw_changes)
            if loyalty_net is not None:
                net_pct = int(((legacy_mods.get("armies") or {})
                               .get(army_id) or {}).get("loyalty", 0) or 0)
                # #319+#320 同一写缝：post-mod 动态方向门 → ±15/cap 软调；任一步 no-op 则拒整封。
                effect_delta = int(loyalty_net)
                if net_pct:
                    effect_delta = db.apply_legacy_pct(effect_delta, net_pct)
                if bool(row["is_mutinied"]) and not latched_army_field_effect_permitted(
                    "loyalty", loyalty_net, effect_delta=effect_delta
                ):
                    return _noop_error(
                        "army",
                        army_id,
                        first_loyalty_raw_field if first_loyalty_raw_field is not None else "loyalty",
                        loyalty_net,
                    )
                _new_loyalty, actual_delta = compute_loyalty_soft_adjust(
                    int(row["loyalty"]),
                    loyalty_net,
                    net_pct=net_pct,
                    mutiny_count=int(row["mutiny_count"] or 0),
                    redemption_count=int(row["redemption_count"] or 0),
                )
                if actual_delta == 0:
                    return _noop_error(
                        "army",
                        army_id,
                        first_loyalty_raw_field if first_loyalty_raw_field is not None else "loyalty",
                        loyalty_net,
                    )

            db.apply_army_deltas(
                preview_state, preflight_event, None, "档房", {army_id: raw_changes}, commit=False,
            source=Provenance.system_simulation)

    finally:
        db.conn.execute("ROLLBACK TO SAVEPOINT strategic_entity_result_preflight")
        db.conn.execute("RELEASE SAVEPOINT strategic_entity_result_preflight")

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

        for result in results:
            for refusal in result.get("backlash_results") or []:
                return (
                    f"战略/外敌事件「{event_title or event_id}」人物战果反噬拒收："
                    f"{refusal.reason or refusal.category}"
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
                created_probe: List[Dict[str, object]] = []
                created_probe_rejections: List[RejectedItem] = []
                for raw in field_armies:
                    landed, refused = db.create_armies_from_extraction(
                        state, [raw], actor="档房", commit=False, require_origin=False,
                    source=Provenance.system_simulation)
                    created_probe.extend(landed)
                    created_probe_rejections.extend(refused)
            finally:
                db.conn.execute("ROLLBACK TO SAVEPOINT strategic_new_army_result_preflight")
                db.conn.execute("RELEASE SAVEPOINT strategic_new_army_result_preflight")
            for result in created_probe_rejections:
                if isinstance(result, RejectedItem):
                    return (
                        f"战略/外敌事件「{event_title or event_id}」新军战果拒收："
                        f"{result.reason or result.category}"
                    )
            if not any(_strategic_result_item_has_material_world_state(item) for item in created_probe):
                return f"战略/外敌事件「{event_title or event_id}」新军战果无真实世界状态变化"

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
        if _pending_person_changes_block_event_gate(event, people, db, content=content):
            rejected[event_id] = f"战略事件被同项人物变更阻断：{event_id}"
            continue
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


def sanitize_delta_shape(extracted: dict) -> tuple[dict, list[tuple[str, dict, str]]]:
    """Return (cleaned_delta, validate-layer rejections) per ADR 0015 (r4 终态)。

    分层终态（#649 票面 r3/r4）：顶层非 dict（连 section 都拆不出）仍 fail loud 整份
    重产；未知顶层 key＝可拆 section → 按段拒收留痕不整份退（原整份 ValueError 属
    ADR 0015 待施工纠正面，#649 纠正）；section/list/entity shape 缺陷逐项移除并
    返回拒收记录。Flat faction integers remain legal; flat class items reach the
    class adapter and are rejected per item as ``invalid_enum`` under the #564 contract.
    """
    from ming_sim.simulation import (  # 懒 import 避 issues↔simulation 循环
        DECLARATION_EFFECT_FIELDS,
    )

    if not isinstance(extracted, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(extracted).__name__}")
    cleaned = dict(extracted)
    rejections: list[tuple[str, dict, str]] = []
    for key, value in list(extracted.items()):
        if key == "_module_rejections":
            continue
        if key not in DECLARATION_EFFECT_FIELDS:
            # ADR 0015 r4：未知顶层 key＝可拆 section，拒该段留痕、其余段照落，不整份退。
            cleaned.pop(key, None)
            rejections.append(
                (key, {"raw_value": value},
                 f"未知 delta 顶层字段「{key}」(canonicalize 后)；疑拼写错(如 地区变更↔地区变化)。"
                 "apply 不会消费它＝静默无效，按段拒收留痕（ADR 0015），请改用合法 key。")
            )
            continue
        if value is None:
            continue
        expected = DECLARATION_EFFECT_FIELDS[key]
        if isinstance(expected, dict):
            if not isinstance(value, dict):
                cleaned[key] = {}
                rejections.append((key, {"raw_value": value}, f"delta 字段 {key} 必须是 object(dict)，实得 {type(value).__name__}"))
                continue
            if key in _NESTED_DICT_FIELDS:
                section_clean = dict(value)
                for ent, sub in value.items():
                    if not isinstance(sub, dict):
                        section_clean.pop(ent, None)
                        rejections.append((key, {"entity_id": str(ent), "raw_value": sub}, f"delta 字段 {key}.{ent} 必须是 object(dict)，实得 {type(sub).__name__}"))
                cleaned[key] = section_clean
        elif isinstance(expected, list):
            if not isinstance(value, list):
                cleaned[key] = []
                rejections.append((key, {"raw_value": value}, f"delta 字段 {key} 必须是 array(list)，实得 {type(value).__name__}"))
                continue
            section_clean = []
            for i, item in enumerate(value):
                if not isinstance(item, dict):
                    rejections.append((key, {"raw_value": item}, f"delta 字段 {key}[{i}] 必须是 object(dict)，实得 {type(item).__name__}"))
                else:
                    section_clean.append(item)
            cleaned[key] = section_clean
    return cleaned, rejections


def validate_delta_shape(extracted: dict) -> None:
    """Validate unsplittable delta shape; split-capable bad items are ADR0015 rejections."""
    sanitize_delta_shape(extracted)


