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
from ming_sim.exceptions import OfficeAppointmentRejection, SettlementAbort
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
from ming_sim.person_delta_adapter import normalize_person_changes
from ming_sim.token_stats import tlog

import ming_sim.entities.character.names as character_names
import ming_sim.entities.issue.commitment_display as commitment_display
import ming_sim.entities.issue.effects as issue_effects

_content: Optional[GameContent] = None

COMMITMENT_KIND_UNTIL_STOP = "until_stop"
_FISCAL_LEVY_TARGET_ABS_TOL = 1e-9

# SQLite 有符号 64-bit 整数边界：超界 int 绑进 SQLite 会抛 OverflowError。
_SQLITE_INT_MIN, _SQLITE_INT_MAX = -(2 ** 63), 2 ** 63 - 1


def _parse_sqlite_id(raw: object) -> int:
    """解析将绑进 SQLite 的整型主键 id（secret_order / issue 等通用）：非整数/bool/float/超
    SQLite 64-bit 范围 → 抛 ValueError（调用方拒为 invalid_enum）。避免绑定超界 int 抛
    OverflowError 崩整月结算（#63.5 一坏项带走整批；cmr secret-order r2 / close-issues r1 codex）。"""
    val = _strict_int(raw)  # bool/float/非数 → ValueError
    if not (_SQLITE_INT_MIN <= val <= _SQLITE_INT_MAX):
        raise ValueError("id 超出 SQLite 64-bit 范围")
    return val



def _payload_owned_person_duplicate(
    db: GameDB,
    item: Dict[str, object],
    *,
    current_office_type: str = "",
    llm_config=None,
) -> bool:
    from ming_sim.entities.authority.apply import _payload_owned_dossier_for_origin
    from ming_sim.entities.character.appointment import (
        _canonical_appointment_fields,
        _resolve_appointment_seat,
    )
    dossier = _payload_owned_dossier_for_origin(db, item.get("origin_ref") or item.get("来源引用"))
    if dossier is None or dossier.get("action_type") not in {"appointment", "dismiss_assignment"}:
        return False
    payload = dossier["payload"]
    person = str(item.get("name") or item.get("人物") or "").strip()
    target = str(payload.get("_minister_name") or payload.get("minister_name") or dossier.get("target_id") or "").strip()
    payload_action = str(payload.get("_office_action") or "").strip()
    item_action = str(item.get("动作") or item.get("action") or "").strip()
    if not person or person != target:
        return False
    if payload_action == "罢免":
        return item_action in {"罢黜", "罢免"}
    if payload_action != "任命" or item_action not in {"任命", "调任"}:
        return False
    canonical_kwargs = {
        "current_office_type": current_office_type,
        "llm_config": llm_config,
    }

    def _fields(src: Dict[str, object]) -> tuple[str, str, str, str]:
        office, office_type, tenure, raw_seat = _canonical_appointment_fields(
            src, **canonical_kwargs,
        )
        if not office:
            return office, office_type, tenure, raw_seat
        try:
            seat = _resolve_appointment_seat(
                db,
                name=person,
                office=office,
                office_type=office_type,
                region_id=raw_seat,
            )
        except OfficeAppointmentRejection:
            # Typed seat reject only: missing/unknown region keeps raw for identity compare.
            seat = raw_seat
        return office, office_type, tenure, seat

    payload_fields = _fields(payload)
    return bool(payload_fields[0]) and payload_fields == _fields(item)


def _issue_condition_text(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    return str(raw).strip()


def _normalize_commitment_kind(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if value in {COMMITMENT_KIND_UNTIL_STOP, "until_condition", "recurring_until", "commitment"}:
        return COMMITMENT_KIND_UNTIL_STOP
    return ""


def _validate_commitment_stop_condition(raw: object, state: GameState, db: GameDB) -> str:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("stop_condition 须为非空 dict")
    for key, cond in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"stop_condition key 非法：{key!r}")
        key = key.strip()
        if "." not in key or key.split(".", 1)[0] not in GATE_TABLES:
            raise ValueError(f"stop_condition key 须带表前缀：{key!r}")
        if not isinstance(cond, str) or not cond.strip():
            raise ValueError(f"stop_condition value 须把比较算符写在字符串 value 内：{cond!r}")
        cond_text = cond.strip()
        sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond_text)
        if sm and (sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())):
            if _eval_gate_key_str(key, db) is None:
                raise ValueError(f"stop_condition key 无法寻址：{key!r}")
            continue
        if not re.match(r"^(>=|<=|>|<|==)\s*-?\d+$", cond_text):
            raise ValueError(f"stop_condition value 非法：{cond!r}")
        if _eval_gate_key(key, state.metrics, db) is None:
            raise ValueError(f"stop_condition key 无法寻址：{key!r}")
    return _issue_condition_text(raw)


# 给建筑/地区落库做 event 关联用的占位事件（issue 结案触发的副作用无真实 event）。
_ISSUE_PSEUDO_EVENT = Event(
    id="issue_resolution", title="局势结案", kind="月末", summary="",
    urgency=0, severity=0, credibility=100, interests=[], audiences=[],
)


def bind_content(content: GameContent) -> None:
    global _content
    _validate_strategic_foreign_node_outcome_targets(content)
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("issues.bind_content() 未调用：GameContent 未注入。")
    return _content


def _canonical_issue_origin(db: GameDB, row: sqlite3.Row) -> str:
    """Resolve and authorize one parent issue origin before applying its children."""
    stored_ref = str(row["origin_ref"] or "").strip()
    # Durable dossier references remain exact; legacy/event issues predate dossier
    # provenance and canonically represent simulation-originated consequences.
    origin_ref = stored_ref if stored_ref.startswith("dossier:") else "盘面自发"
    rejection = db.effect_origin_rejection(origin_ref)
    if rejection:
        raise ValueError(f"issue #{row['id']} canonical origin 非法：{rejection['reason']}")
    return origin_ref


def commitment_condition_role(resolve_condition: object, commitment_kind: object = "") -> Dict[str, str]:
    if str(commitment_kind or "").strip():
        return {
            "condition_role": "commitment_stop_condition",
            "condition_note": "承诺停止条件；不要按 resolve_condition 达标自动结案，自动完成属于 #136。",
        }
    text = str(resolve_condition or "").strip()
    if re.fullmatch(r"character\.[^.]+\.loyalty\s*(?:>=|>)\s*\d+", text):
        return {
            "condition_role": "commitment_stop_condition",
            "condition_note": "人物承诺停止条件；不要按 resolve_condition 达标自动结案，自动完成属于 #136。",
        }
    return {}


def _legacy_commitment_stop_gate(resolve_condition: object) -> Dict[str, str]:
    text = str(resolve_condition or "").strip()
    match = re.fullmatch(r"(character\.[^.]+\.loyalty)\s*((?:>=|>)\s*\d+)", text)
    if not match:
        return {}
    return {match.group(1): match.group(2).replace(" ", "")}


def _commitment_stop_gate(row: sqlite3.Row) -> Dict[str, str]:
    keys = row.keys() if hasattr(row, "keys") else []
    raw = row["stop_condition"] if "stop_condition" in keys else ""
    if raw:
        try:
            gate = json.loads(str(raw))
        except (TypeError, ValueError):
            gate = {}
        if isinstance(gate, dict) and gate:
            return gate
    return _legacy_commitment_stop_gate(row["resolve_condition"] if "resolve_condition" in keys else "")


def _commitment_remaining_from_gate(
    gate: Dict[str, str],
    state: GameState,
    db: GameDB,
) -> Optional[float]:
    remaining = 0.0
    found = False
    for key, cond in gate.items():
        cond_text = str(cond or "").strip()
        m = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+)$", cond_text)
        if not m:
            continue
        val = _eval_gate_key(str(key), state.metrics, db)
        if val is None:
            continue
        try:
            val_num = float(val)
        except (TypeError, ValueError):
            continue
        op, target = m.group(1), int(m.group(2))
        if op == "<=":
            need = max(0.0, val_num - target)
        elif op == "<":
            need = 0.0 if val_num < target else float(int(val_num - target) + 1)
        elif op == ">=":
            need = max(0.0, target - val_num)
        elif op == ">":
            need = 0.0 if val_num > target else float(int(target - val_num) + 1)
        else:
            need = abs(val_num - target)
        remaining += need
        found = True
    return remaining if found else None


def _latest_commitment_paid_total(db: GameDB, issue_id: int) -> int:
    rows = db.conn.execute(
        "SELECT metric_delta FROM issue_advances WHERE issue_id=? ORDER BY id DESC",
        (issue_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["metric_delta"] or "{}"))
        except (TypeError, ValueError):
            continue
        progress = payload.get("commitment_progress") if isinstance(payload, dict) else None
        if isinstance(progress, dict):
            try:
                return int(progress.get("paid_total") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _commitment_gate_references_arrears(row: sqlite3.Row) -> bool:
    return any(".arrears" in str(key) for key in _commitment_stop_gate(row))


def _commitment_arrears_gate_army_ids(row: sqlite3.Row) -> List[str]:
    ids: List[str] = []
    for key in _commitment_stop_gate(row):
        text = str(key)
        match = re.fullmatch(r"army\.([^.]+)\.arrears(?:\.sum)?", text)
        if not match:
            continue
        for army_id in match.group(1).split("|"):
            army_id = army_id.strip()
            if army_id and army_id not in ids:
                ids.append(army_id)
    return ids


def _commitment_ongoing_effects_for_settlement(row: sqlite3.Row, ongoing: Dict[str, object]) -> Dict[str, object]:
    if not _commitment_gate_references_arrears(row):
        return ongoing
    gate_army_ids = _commitment_arrears_gate_army_ids(row)
    normalized = dict(ongoing)
    for key in ("economy", "economy_moves"):
        economy = ongoing.get(key)
        if not isinstance(economy, list):
            continue
        normalized_economy: List[object] = []
        for move in economy:
            if not isinstance(move, dict):
                normalized_economy.append(move)
                continue
            item = dict(move)
            try:
                delta = _strict_int(item.get("delta"))
            except (TypeError, ValueError):
                delta = 0
            if delta < 0:
                item["purpose"] = "补饷"
                if (
                    len(gate_army_ids) == 1
                    and not str(item.get("target_id") or "").strip()
                    and not str(item.get("目标编号") or "").strip()
                    and not str(item.get("target_kind") or item.get("目标类型") or "").strip()
                ):
                    item["target_kind"] = "army"
                    item["target_id"] = gate_army_ids[0]
            normalized_economy.append(item)
        normalized[key] = normalized_economy
    return normalized


def _invalid_monthly_mapping_shape(
    field: str,
    entity_id: object,
    raw_value: object,
    source: Provenance = Provenance.system_simulation,
) -> Dict[str, object]:
    return RejectedItem(item={"field": field, "id": entity_id, "value": raw_value}, reason=f"{field}.{entity_id} 须为对象(dict)", category="invalid_shape", source=source)


def _monthly_mapping_effect(
    effect: Dict[str, object],
    *keys: str,
    source: Provenance = Provenance.system_simulation,
) -> tuple[Dict[str, Dict[str, object]], List[Dict[str, object]]]:
    merged: Dict[str, Dict[str, object]] = {}
    rejections: List[Dict[str, object]] = []
    for key in keys:
        raw = effect.get(key)
        if not isinstance(raw, dict):
            continue
        for entity_id, raw_changes in raw.items():
            if isinstance(raw_changes, dict):
                merged[entity_id] = raw_changes
                continue
            rejections.append(_invalid_monthly_mapping_shape(key, entity_id, raw_changes, source=source))
    return merged, rejections


def _merged_mapping_effect(effect: Dict[str, object], *keys: str) -> Dict[str, object]:
    merged: Dict[str, object] = {}
    for key in keys:
        raw = effect.get(key)
        if isinstance(raw, dict):
            merged.update(raw)
    return merged


def _monthly_economy_items(effect: Dict[str, object]) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for key in ("economy", "economy_moves"):
        raw = effect.get(key)
        if not isinstance(raw, list):
            continue
        items.extend(item for item in raw if isinstance(item, dict))
    return items


def _recurring_funding_label_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        key_stem = raw
        if key_stem.endswith("_base") or key_stem.endswith("_rate"):
            key_stem = key_stem.rsplit("_", 1)[0]
        normalized = re.sub(r"[\s，。、“”‘’：:；;,.·_\-（）()\[\]【】]+", "", key_stem)
        for word in (
            "同批extractor误产的重复",
            "同批误产的重复",
            "每月",
            "按月",
            "月度",
            "月支",
            "拨给",
            "拨付",
            "拨银",
            "拨",
            "给",
            "支给",
            "支出",
            "开支",
            "费用",
            "经费",
            "月",
            "万两",
            "银两",
            "银",
        ):
            normalized = normalized.replace(word, "")
        if normalized:
            tokens.add(normalized)
    return tokens


def _commitment_fiscal_create_duplicate_reason(
    create: Dict[str, object],
    commitment_economy: List[Dict[str, object]],
    db: GameDB,
) -> str:
    account = str(create.get("account") or "").strip()
    display = str(create.get("display") or "").strip() or (db._stem_of(str(create.get("key") or "")) or str(create.get("key") or ""))
    create_tokens = _recurring_funding_label_tokens(
        display,
        create.get("key"),
        create.get("reason"),
    )
    if not account or not create_tokens:
        return ""
    for item in commitment_economy:
        if str(item.get("account") or "").strip() != account:
            continue
        try:
            delta = _strict_int(item.get("delta"))
        except (TypeError, ValueError):
            continue
        if delta >= 0:
            continue
        item_tokens = _recurring_funding_label_tokens(
            item.get("category"),
            item.get("reason"),
            item.get("purpose"),
        )
        if create_tokens & item_tokens:
            return "同批已有承诺 issue ongoing_effects.economy 承载该经常性拨款，fiscal_create 已去重"
    return ""


def _commitment_carrier_same_account_unmatched(
    create: Dict[str, object],
    commitment_economy: List[Dict[str, object]],
) -> str:
    """ADR0027 残留观测：同批、同账户、有 decree 承诺月支，却**未按科目名匹配上**的
    fiscal_create —— 疑似异名漏匹（两模块给同一笔起不同名）。返回触发账户名供日志，
    无则空串。**仅作试玩观测信号、不改落库行为**：该 fiscal_create 仍照常落账。"""
    account = str(create.get("account") or "").strip()
    if not account:
        return ""
    for item in commitment_economy:
        if str(item.get("account") or "").strip() != account:
            continue
        try:
            delta = _strict_int(item.get("delta"))
        except (TypeError, ValueError):
            continue
        if delta < 0:
            return account
    return ""


def _monthly_person_rating_changes(effect: Dict[str, object]) -> List[Dict[str, object]]:
    raw_changes: List[Dict[str, object]] = []
    for key in ("人物变更", "person_changes"):
        raw = effect.get(key)
        if isinstance(raw, list):
            raw_changes.extend(item for item in raw if isinstance(item, dict))
    changes = [
        item
        for item in normalize_person_changes({"人物变更": raw_changes})
        if isinstance(item, dict)
        and str(item.get("动作") or "").strip() == "评定"
        and not isinstance(item.get("loyalty"), bool)
        and isinstance(item.get("loyalty"), int)
        and int(item.get("loyalty") or 0) != 0
    ]
    raw_character = effect.get("character")
    if isinstance(raw_character, list):
        for item in raw_character:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("人物") or "").strip()
            loyalty = item.get("loyalty")
            if not name or isinstance(loyalty, bool) or not isinstance(loyalty, int) or loyalty == 0:
                continue
            changes.append({
                "name": name,
                "动作": "评定",
                "loyalty": loyalty,
                "reason": str(item.get("reason") or item.get("原因") or ""),
            })
    return changes


def _invalid_monthly_person_rating_reason(effect: Dict[str, object]) -> str:
    for key in ("人物变更", "person_changes"):
        raw = effect.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("人物") or "").strip()
            action = str(item.get("动作") or item.get("action") or "").strip()
            if not name or action != "评定":
                continue
            loyalty = item.get("loyalty")
            if isinstance(loyalty, bool) or not isinstance(loyalty, int) or loyalty == 0:
                return f"{key}.评定 loyalty 须为非零整数增量"
    raw_character = effect.get("character")
    if isinstance(raw_character, list):
        for item in raw_character:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("人物") or "").strip()
            if not name or "loyalty" not in item:
                continue
            loyalty = item.get("loyalty")
            if isinstance(loyalty, bool) or not isinstance(loyalty, int) or loyalty == 0:
                return "character.loyalty 须为非零整数增量"
    return ""


def _person_change_has_unsupported_monthly_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("人物") or "").strip()
        action = str(item.get("动作") or item.get("action") or "").strip()
        if name and action and action != "评定":
            return True
    return False


def _unsupported_monthly_ongoing_fields(effect: Dict[str, object]) -> List[str]:
    unsupported: List[str] = []
    for key in (
        "buildings",
        "new_armies",
        "power_renames",
        "legacy",
    ):
        if effect_dict_has_work({key: effect.get(key)}):
            unsupported.append(key)
    for key in ("人物变更", "person_changes"):
        if _person_change_has_unsupported_monthly_work(effect.get(key)):
            unsupported.append(f"{key}(月度仅支持评定)")
    return unsupported


def _monthly_ongoing_effects_has_work(raw: object) -> bool:
    effect = loads_effect_dict(raw)
    if not effect:
        return False
    checks = (
        effect_dict_has_work({"metrics": effect.get("metrics")}),
        effect_dict_has_work({"economy": effect.get("economy")}),
        effect_dict_has_work({"economy_moves": effect.get("economy_moves")}),
        effect_dict_has_work({"factions": _merged_mapping_effect(effect, "factions", "faction_delta")}),
        effect_dict_has_work({"class_delta": _merged_mapping_effect(effect, "classes", "class_delta")}),
        effect_dict_has_work({"region_delta": _merged_mapping_effect(effect, "region_delta", "regions")}),
        effect_dict_has_work({"army_delta": _merged_mapping_effect(effect, "army_delta", "armies")}),
        effect_dict_has_work({"power_updates": effect.get("power_updates")}),
        bool(_monthly_person_rating_changes(effect)),
    )
    return any(checks)


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
) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    from ming_sim.entities.social_class.apply import _apply_class_dict
    from ming_sim.entities.faction.apply import _apply_faction_dict
    applied: Dict[str, object] = {}
    rejections: List[Dict[str, object]] = []

    factions, faction_shape_rejections = _monthly_mapping_effect(effect, "factions", "faction_delta", source=source)
    classes, class_shape_rejections = _monthly_mapping_effect(effect, "classes", "class_delta", source=source)
    region_delta, region_shape_rejections = _monthly_mapping_effect(effect, "region_delta", "regions", source=source)
    army_delta, army_shape_rejections = _monthly_mapping_effect(effect, "army_delta", "armies", source=source)
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
            applied["factions"] = faction_applied
        rejections.extend(faction_rejections)

    if classes:
        class_applied, class_rejections = _apply_class_dict(db, classes, source=source)
        if class_applied:
            applied["class_delta"] = class_applied
        rejections.extend(class_rejections)

    if region_delta:
        region_changes, region_changes_rejections = db.apply_region_deltas(
            state, _ISSUE_PSEUDO_EVENT, None, label, region_delta, origin_ref=origin_ref
        , source=source)
        applied_region = region_changes
        if applied_region:
            applied["region_delta"] = applied_region
        rejections.extend(region_changes_rejections)

    if army_delta:
        army_changes, army_changes_rejections = db.apply_army_deltas(
            state, _ISSUE_PSEUDO_EVENT, None, label, army_delta, origin_ref=origin_ref
        , source=source)
        applied_army = army_changes
        if applied_army:
            applied["army_delta"] = applied_army
        rejections.extend(army_changes_rejections)

    if power_updates:
        power_changes, power_changes_rejections = db.apply_power_deltas(state, power_updates, origin_ref=origin_ref, source=source)
        applied_power = power_changes
        if applied_power:
            applied["power_updates"] = applied_power
        rejections.extend(power_changes_rejections)

    person_changes = _monthly_person_rating_changes(effect)
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
            applied["人物变更"] = applied_people
        rejections.extend(results_rejections)
        for result in results:
            rejections.extend(result.pop("backlash_results", None) or [])
        if applied_person_changes is not None:
            applied_person_changes.extend(results)

    return applied, rejections


def _resolve_commitment_issue(
    db: GameDB,
    state: GameState,
    row: sqlite3.Row,
    *,
    commit: bool = True,
) -> None:
    issue_id = int(row["id"])
    from_value = int(row["bar_value"])
    progress = commitment_display.commitment_progress_payload(db, state, row) or {}
    metric_delta = {"commitment_progress": progress} if progress else {}
    db.conn.execute(
        """
        UPDATE issues SET bar_value=100, phase=?, status='resolved',
                          resolution_summary=?, closed_turn=?,
                          last_advance_turn=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            db._derive_issue_phase(100),
            "承诺停止条件已达成，自动结清。",
            state.turn,
            state.turn,
            issue_id,
        ),
    )
    db.conn.execute(
        """
        INSERT INTO issue_advances (
            issue_id, turn, trigger_kind, delta_bar,
            from_value, to_value, narrative, metric_delta
        ) VALUES (?, ?, 'commitment_resolve', ?, ?, 100, ?, ?)
        """,
        (
            issue_id,
            state.turn,
            100 - from_value,
            from_value,
            "承诺停止条件已达成，自动结清。",
            json.dumps(metric_delta, ensure_ascii=False),
        ),
    )
    if commit:
        db.conn.commit()


def _expire_commitment_issue(
    db: GameDB,
    state: GameState,
    row: sqlite3.Row,
    *,
    commit: bool = True,
) -> None:
    issue_id = int(row["id"])
    from_value = int(row["bar_value"])
    progress = commitment_display.commitment_progress_payload(db, state, row) or {}
    metric_delta = {"commitment_progress": progress} if progress else {}
    db.conn.execute(
        """
        UPDATE issues SET status='dropped', resolution_summary=?,
                          closed_turn=?, last_advance_turn=?,
                          updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            "承诺期限已至，停账收尾。",
            state.turn,
            state.turn,
            issue_id,
        ),
    )
    db.conn.execute(
        """
        INSERT INTO issue_advances (
            issue_id, turn, trigger_kind, delta_bar,
            from_value, to_value, narrative, metric_delta
        ) VALUES (?, ?, 'expire', 0, ?, ?, ?, ?)
        """,
        (
            issue_id,
            state.turn,
            from_value,
            from_value,
            "承诺期限已至，停账收尾。",
            json.dumps(metric_delta, ensure_ascii=False),
        ),
    )
    if commit:
        db.conn.commit()


def _ack_due_commitment_issue(
    db: GameDB,
    state: GameState,
    row: sqlite3.Row,
    *,
    narrative: str = "",
    commit: bool = True,
) -> sqlite3.Row:
    issue_id = int(row["id"])
    from_value = int(row["bar_value"])
    summary = narrative or "到期待裁承诺已由皇帝裁决确认。"
    db.conn.execute(
        """
        UPDATE issues SET status='dropped', resolution_summary=?,
                          closed_turn=?, last_advance_turn=?,
                          updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (summary, state.turn, state.turn, issue_id),
    )
    db.conn.execute(
        """
        INSERT INTO issue_advances (
            issue_id, turn, trigger_kind, delta_bar,
            from_value, to_value, narrative, metric_delta
        ) VALUES (?, ?, 'commitment_ack', 0, ?, ?, ?, '{}')
        """,
        (issue_id, state.turn, from_value, from_value, summary),
    )
    if commit:
        db.conn.commit()
    return db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()


def _event_issue_refs(db: GameDB) -> set:
    refs: set = set()
    for r in db.conn.execute("SELECT origin_ref FROM issues WHERE origin_kind='event_pool'").fetchall():
        if r["origin_ref"]:
            refs.add(r["origin_ref"])
    return refs


def _event_trigger_refs(db: GameDB) -> set:
    return set(_event_terminal_states(db))


def _event_terminal_states(db: GameDB) -> Dict[str, str]:
    states: Dict[str, str] = {}
    for r in db.conn.execute("SELECT event_id, terminal_state FROM event_triggers").fetchall():
        terminal_state = str(r["terminal_state"] or "")
        if r["event_id"] and terminal_state:
            states[str(r["event_id"])] = terminal_state
    return states


def _event_terminal_records(db: GameDB) -> Dict[str, Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    for r in db.conn.execute(
        "SELECT event_id, terminal_state, terminal_reason FROM event_triggers"
    ).fetchall():
        terminal_state = str(r["terminal_state"] or "")
        if r["event_id"] and terminal_state:
            records[str(r["event_id"])] = {
                "terminal_state": terminal_state,
                "terminal_reason": str(r["terminal_reason"] or ""),
            }
    return records


def _event_pending_choice_records(db: GameDB) -> Dict[str, Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    for r in db.conn.execute(
        """
        SELECT event_id, terminal_state, terminal_reason, source
        FROM event_triggers
        WHERE COALESCE(terminal_state, '') = ''
          AND COALESCE(terminal_reason, '') != ''
        """
    ).fetchall():
        if r["event_id"]:
            records[str(r["event_id"])] = {
                "terminal_state": "",
                "terminal_reason": str(r["terminal_reason"] or ""),
                "source": str(r["source"] or ""),
            }
    return records


FISCAL_LEVY_EVENT_CATEGORY = "fiscal_levy"
_LIAO_LEVY_RISE_EVENT_ID = "liao_levy_rise_1631"
_LIAN_LEVY_START_EVENT_ID = "lian_levy_start_1639"
_LIAO_LEVY_RISE_FACTOR = 4.0 / 3.0
_JIAO_LEVY_START_EVENT_ID = "jiao_levy_start_1637"
_JIAO_LEVY_STOP_EVENT_ID = "jiao_levy_stop_1640"
_JIAO_LEVY_NATIONAL_MONTHLY = 280.0 / 12.0
_LIAN_LEVY_NATIONAL_MONTHLY = 730.0 / 12.0
_SETTLE_META_BASE_TRANSPORT_KEY = "正赋起运基线"
_SETTLE_META_LIAO_SEED_KEY = "辽饷九厘基线"
_SETTLE_META_JIAO_SEED_KEY = "剿饷基线"
_SETTLE_META_LIAN_SEED_KEY = "练饷基线"
_SETTLE_META_LAND_DENOMINATOR_KEY = "饷率田亩分母基线"
# #650/0089 明渠：下旨加派逐省累积账（万两/月，负额停征/蠲免、钳 ≥0）。
# 与 #649 饷率 seed 同址（settle._meta），restore 只读 DB 无损接续（P1）。
_SETTLE_META_JIAPIAI_KEY = "加派基线"
_FISCAL_LEVY_PROVISIONAL_KEYS = {
    _SETTLE_META_BASE_TRANSPORT_KEY,
    _SETTLE_META_LIAO_SEED_KEY,
    _SETTLE_META_JIAO_SEED_KEY,
    _SETTLE_META_LIAN_SEED_KEY,
    _SETTLE_META_LAND_DENOMINATOR_KEY,
}
def _normalize_event_terminal_reason(ev: Event, raw: object) -> str:
    label = re.sub(r"\s+", "", str(raw or ""))
    if not label:
        return ""
    allowed = getattr(ev, "terminal_reason_labels", []) or []
    for canonical in allowed:
        if label == re.sub(r"\s+", "", canonical):
            return canonical
    return ""


def _fiscal_levy_default_terminal_reason(ev: Event, state: GameState) -> str:
    if not getattr(ev, "terminal_reason_labels", None):
        raise SettlementAbort(
            f"饷率事件 {ev.id} 缺 terminal_reason_labels 白名单",
            turn=state.turn,
            stage="fiscal_levy_config",
        )
    label = _normalize_event_terminal_reason(ev, getattr(ev, "default_terminal_reason", ""))
    if not label:
        raise SettlementAbort(
            f"饷率事件 {ev.id} default_terminal_reason 不可归一",
            turn=state.turn,
            stage="fiscal_levy_config",
        )
    return label


def _fiscal_levy_normalized_terminal_reason_or_abort(
    ev: Event,
    raw: object,
    state: GameState,
) -> str:
    label = _normalize_event_terminal_reason(ev, raw)
    if label:
        return label
    allowed = "/".join(getattr(ev, "terminal_reason_labels", []) or [])
    raise SettlementAbort(
        f"饷率事件 {ev.id} 结局标签无法归一：{raw!r}；合法标签：{allowed}",
        turn=state.turn,
        stage="fiscal_levy_config",
    )


def _canonicalize_existing_fiscal_levy_terminal_reason(
    ev: Event,
    record: Dict[str, str],
    state: GameState,
    db: GameDB,
) -> None:
    if record.get("terminal_state") != "triggered":
        return
    label = _fiscal_levy_normalized_terminal_reason_or_abort(
        ev,
        record.get("terminal_reason"),
        state,
    )
    if label != record.get("terminal_reason"):
        db.conn.execute(
            "UPDATE event_triggers SET terminal_reason=? WHERE event_id=?",
            (label, ev.id),
        )
        record["terminal_reason"] = label


def _as_float(raw: object, *, ctx: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{ctx} 非数值：{raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx} 非数值：{raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{ctx} 非有限数值：{raw!r}")
    return value


def _is_stored_number(raw: object) -> bool:
    return not isinstance(raw, bool) and isinstance(raw, (int, float))


def _fiscal_levy_liao_seed(meta: Dict[str, object], p: Dict[str, object], region_id: str) -> float:
    if _SETTLE_META_LIAO_SEED_KEY in meta:
        return _as_float(
            meta[_SETTLE_META_LIAO_SEED_KEY],
            ctx=f"{region_id}.settle._meta.{_SETTLE_META_LIAO_SEED_KEY}",
        )
    return _as_float(p.get("三饷应征"), ctx=f"{region_id}.settle.p.三饷应征")


def _fiscal_levy_base_transport(
    meta: Dict[str, object],
    p: Dict[str, object],
    liao_seed: float,
    region_id: str,
) -> float:
    if _SETTLE_META_BASE_TRANSPORT_KEY in meta:
        return max(
            0.0,
            _as_float(
                meta[_SETTLE_META_BASE_TRANSPORT_KEY],
                ctx=f"{region_id}.settle._meta.{_SETTLE_META_BASE_TRANSPORT_KEY}",
            ),
        )
    seed_transport = _as_float(p.get("起运定额"), ctx=f"{region_id}.settle.p.起运定额")
    return max(0.0, seed_transport - liao_seed)


def _load_region_fiscal_for_fiscal_levy(region_id: str, raw_fiscal: object) -> Optional[dict]:
    if isinstance(raw_fiscal, dict):
        return raw_fiscal
    if raw_fiscal is None or raw_fiscal == "":
        raw_fiscal = "{}"
    elif not isinstance(raw_fiscal, (str, bytes, bytearray)):
        tlog(f"[fiscal-levy] {region_id} fiscal 非字典，本{TURN_UNIT}饷率通道出列")
        return None
    try:
        fiscal = json.loads(raw_fiscal)
    except (TypeError, ValueError) as exc:
        tlog(f"[fiscal-levy] {region_id} fiscal 解析失败，本{TURN_UNIT}饷率通道出列：{type(exc).__name__}: {exc}")
        return None
    if not isinstance(fiscal, dict):
        tlog(f"[fiscal-levy] {region_id} fiscal 非字典，本{TURN_UNIT}饷率通道出列")
        return None
    return fiscal


def _fiscal_levy_event_by_id(event_id: str) -> Optional[Event]:
    return _ctx().event_by_id.get(event_id)


def _fiscal_levy_event_approved(
    terminal_records: Dict[str, Dict[str, str]],
    event_id: str,
) -> bool:
    record = terminal_records.get(event_id) or {}
    return (
        record.get("terminal_state") == "triggered"
        and record.get("terminal_reason") == "已准"
    )


def _fiscal_levy_stopped(
    terminal_records: Dict[str, Dict[str, str]],
    event_id: str,
) -> bool:
    record = terminal_records.get(event_id) or {}
    return (
        record.get("terminal_state") == "triggered"
        and record.get("terminal_reason") == "已停"
    )


def _fiscal_levy_land_share_amount(
    land: float,
    total_land: float,
    national_monthly: float,
) -> float:
    if total_land <= 0:
        return 0.0
    return max(0.0, land) / total_land * national_monthly


def _fiscal_levy_land_denominator(
    meta: Dict[str, object],
    parsed_total_land: float,
    *,
    denominator_complete: bool,
    region_id: str,
) -> float:
    if _SETTLE_META_LAND_DENOMINATOR_KEY in meta:
        return _as_float(
            meta[_SETTLE_META_LAND_DENOMINATOR_KEY],
            ctx=f"{region_id}.settle._meta.{_SETTLE_META_LAND_DENOMINATOR_KEY}",
        )
    if denominator_complete:
        return parsed_total_land
    return 0.0


def _fiscal_levy_share_seed(
    meta: Dict[str, object],
    key: str,
    land: float,
    total_land: float,
    national_monthly: float,
    region_id: str,
) -> float:
    if key in meta:
        return _as_float(meta[key], ctx=f"{region_id}.settle._meta.{key}")
    return _fiscal_levy_land_share_amount(land, total_land, national_monthly)


def _validate_fiscal_levy_share_meta(meta: Dict[str, object], region_id: str) -> None:
    for key in (
        _SETTLE_META_JIAO_SEED_KEY,
        _SETTLE_META_LIAN_SEED_KEY,
        _SETTLE_META_LAND_DENOMINATOR_KEY,
    ):
        if key in meta:
            _as_float(meta[key], ctx=f"{region_id}.settle._meta.{key}")


def _fiscal_levy_mark_provisional(meta: Dict[str, object]) -> None:
    raw = meta.get("provisional", [])
    if isinstance(raw, list):
        provisional = [str(item) for item in raw]
    else:
        provisional = []
    seen = set(provisional)
    for key in sorted(_FISCAL_LEVY_PROVISIONAL_KEYS):
        if key not in seen:
            provisional.append(key)
            seen.add(key)
    meta["provisional"] = provisional


def _jiao_levy_in_force(terminal_records: Dict[str, Dict[str, str]], state: GameState) -> bool:
    if _fiscal_levy_event_by_id(_JIAO_LEVY_START_EVENT_ID) is None:
        return False
    if _fiscal_levy_event_by_id(_JIAO_LEVY_STOP_EVENT_ID) is None:
        raise SettlementAbort(
            f"饷率事件 {_JIAO_LEVY_START_EVENT_ID} 已定义但缺停征链 {_JIAO_LEVY_STOP_EVENT_ID}",
            turn=state.turn,
            stage="fiscal_levy_config",
        )
    return (
        _fiscal_levy_event_approved(terminal_records, _JIAO_LEVY_START_EVENT_ID)
        and not _fiscal_levy_stopped(terminal_records, _JIAO_LEVY_STOP_EVENT_ID)
    )


def _apply_fiscal_levy_targets(
    db: GameDB,
    state: GameState,
    terminal_records: Dict[str, Dict[str, str]],
) -> int:
    liao_rise_approved = _fiscal_levy_event_approved(terminal_records, _LIAO_LEVY_RISE_EVENT_ID)
    jiao_in_force = _jiao_levy_in_force(terminal_records, state)
    lian_levy_approved = _fiscal_levy_event_approved(terminal_records, _LIAN_LEVY_START_EVENT_ID)
    region_entries: List[Dict[str, object]] = []
    denominator_complete = True
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        region_id = str(row["id"])
        fiscal = _load_region_fiscal_for_fiscal_levy(region_id, row["fiscal"])
        if fiscal is None:
            denominator_complete = False
            continue
        try:
            if "settle" not in fiscal:
                continue
            settle = fiscal.get("settle")
            if not isinstance(settle, dict):
                raise ValueError(f"{region_id}.settle 非字典")
            p = settle.get("p")
            st = settle.get("st")
            if not isinstance(p, dict):
                raise ValueError(f"{region_id}.settle.p 非字典")
            if not isinstance(st, dict):
                raise ValueError(f"{region_id}.settle.st 非字典")
            meta_raw = settle.get("_meta") or {}
            if not isinstance(meta_raw, dict):
                raise ValueError(f"{region_id}.settle._meta 非字典")
            meta = dict(meta_raw)
            liao_seed = _fiscal_levy_liao_seed(meta, p, region_id)
            land = _as_float(st.get("官民田"), ctx=f"{region_id}.settle.st.官民田")
            base_transport = _fiscal_levy_base_transport(meta, p, liao_seed, region_id)
            _validate_fiscal_levy_share_meta(meta, region_id)
        except ValueError as exc:
            denominator_complete = False
            tlog(f"[fiscal-levy] {region_id} settle 解析失败，本{TURN_UNIT}饷率通道出列：{type(exc).__name__}: {exc}")
            continue
        region_entries.append({
            "region_id": region_id,
            "fiscal": fiscal,
            "settle": settle,
            "p": p,
            "meta_raw": meta_raw,
            "meta": meta,
            "liao_seed": liao_seed,
            "land": land,
            "base_transport": base_transport,
        })
    total_land = sum(max(0.0, float(item["land"])) for item in region_entries)
    touched = 0
    for item in region_entries:
        region_id = str(item["region_id"])
        fiscal = item["fiscal"]
        settle = item["settle"]
        p = item["p"]
        meta_raw = item["meta_raw"]
        meta = item["meta"]
        liao_seed = float(item["liao_seed"])
        land = float(item["land"])
        land_denominator = _fiscal_levy_land_denominator(
            meta,
            total_land,
            denominator_complete=denominator_complete,
            region_id=region_id,
        )
        has_jiao_seed = _SETTLE_META_JIAO_SEED_KEY in meta
        has_lian_seed = _SETTLE_META_LIAN_SEED_KEY in meta
        jiao_seed = _fiscal_levy_share_seed(
            meta,
            _SETTLE_META_JIAO_SEED_KEY,
            land,
            land_denominator,
            _JIAO_LEVY_NATIONAL_MONTHLY,
            region_id,
        )
        lian_seed = _fiscal_levy_share_seed(
            meta,
            _SETTLE_META_LIAN_SEED_KEY,
            land,
            land_denominator,
            _LIAN_LEVY_NATIONAL_MONTHLY,
            region_id,
        )
        base_transport = float(item["base_transport"])
        target_liao = liao_seed * (_LIAO_LEVY_RISE_FACTOR if liao_rise_approved else 1.0)
        target_jiao = jiao_seed if jiao_in_force else 0.0
        target_lian = lian_seed if lian_levy_approved else 0.0
        # #650/0089 明渠：皇帝下旨加派逐省累积账（settle._meta「加派基线」）计入在征饷集——
        # 明选有明账，公开代价＝钱真被征上来；负额已在落账时钳 ≥0，停征即止收。
        jiapai_base = (
            max(0.0, _as_float(
                meta[_SETTLE_META_JIAPIAI_KEY],
                ctx=f"{region_id}.settle._meta.{_SETTLE_META_JIAPIAI_KEY}",
            ))
            if _SETTLE_META_JIAPIAI_KEY in meta else 0.0
        )
        target_sanxiang = target_liao + target_jiao + target_lian + jiapai_base
        raw_sanxiang = p.get("三饷应征")
        raw_transport = p.get("起运定额")
        current_targets_stored = _is_stored_number(raw_sanxiang) and _is_stored_number(raw_transport)
        current_sanxiang = current_transport = None
        if current_targets_stored:
            current_sanxiang = _as_float(raw_sanxiang, ctx=f"{region_id}.settle.p.三饷应征")
            current_transport = _as_float(raw_transport, ctx=f"{region_id}.settle.p.起运定额")
        target_transport = base_transport + target_sanxiang
        next_p = dict(p)
        next_p["三饷应征"] = target_sanxiang
        next_p["起运定额"] = target_transport
        meta[_SETTLE_META_LIAO_SEED_KEY] = liao_seed
        if has_jiao_seed or land_denominator > 0:
            meta[_SETTLE_META_JIAO_SEED_KEY] = jiao_seed
        if has_lian_seed or land_denominator > 0:
            meta[_SETTLE_META_LIAN_SEED_KEY] = lian_seed
        meta[_SETTLE_META_BASE_TRANSPORT_KEY] = base_transport
        if land_denominator > 0:
            meta[_SETTLE_META_LAND_DENOMINATOR_KEY] = land_denominator
        _fiscal_levy_mark_provisional(meta)
        if meta == meta_raw \
                and current_targets_stored \
                and math.isclose(current_sanxiang, target_sanxiang, rel_tol=0, abs_tol=_FISCAL_LEVY_TARGET_ABS_TOL) \
                and math.isclose(current_transport, target_transport, rel_tol=0, abs_tol=_FISCAL_LEVY_TARGET_ABS_TOL):
            continue
        settle["p"] = next_p
        settle["_meta"] = meta
        db.conn.execute(
            "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(fiscal, ensure_ascii=False), region_id),
        )
        touched += 1
    return touched


def apply_historical_fiscal_rates(
    state: GameState,
    db: GameDB,
    *,
    commit: bool = True,
) -> List[Dict[str, object]]:
    """饷率 effect 通道：同 tick 前置结局 stub + settle.p set-to-target。

    #259 shadow 阶段只处理 category=fiscal_levy 的历史事件；结局值必须经事件自身
    terminal_reason_labels 白名单归一。随后按事件账重算在征饷集并持久化省级
    settle.p，保证后续 settle_tick 当月读到目标值且重复运行不叠加。
    """
    c = _ctx()
    should_commit = commit and not db.conn.in_transaction
    applied: List[Dict[str, object]] = []

    def run_fiscal_levy_pass() -> None:
        terminal_records = _event_terminal_records(db)
        pending_choice_records = _event_pending_choice_records(db)
        for ev in c.events:
            if getattr(ev, "category", "") != FISCAL_LEVY_EVENT_CATEGORY:
                continue
            if ev.id in terminal_records:
                _canonicalize_existing_fiscal_levy_terminal_reason(
                    ev,
                    terminal_records[ev.id],
                    state,
                    db,
                )
            elif ev.id in pending_choice_records:
                if _event_window_expired(ev, state):
                    pass
                elif not _event_window_open(ev, state):
                    continue
                elif not _gate_passed(ev.trigger_gate, state.metrics, db):
                    continue
                else:
                    record = pending_choice_records[ev.id]
                    label = _fiscal_levy_normalized_terminal_reason_or_abort(
                        ev,
                        record.get("terminal_reason"),
                        state,
                    )
                    db.mark_event_triggered(
                        state,
                        ev.id,
                        source=record.get("source") or "fiscal_levy_shadow",
                        terminal_reason=label,
                        commit=False,
                    )
                    terminal_records[ev.id] = {
                        "terminal_state": "triggered",
                        "terminal_reason": label,
                    }
                    applied.append({
                        "id": ev.id,
                        "title": ev.title,
                        "terminal_state": "triggered",
                        "terminal_reason": label,
                    })
            if ev.id not in terminal_records:
                if _event_window_expired(ev, state):
                    db.mark_event_expired(state, ev.id, commit=False)
                    terminal_records[ev.id] = {
                        "terminal_state": "expired",
                        "terminal_reason": "过最晚触发时点仍未达成触发门",
                    }
                    applied.append({"id": ev.id, "title": ev.title, "terminal_state": "expired"})
                    continue
                if not _event_window_open(ev, state):
                    continue
                if not _gate_passed(ev.trigger_gate, state.metrics, db):
                    continue
                label = _fiscal_levy_default_terminal_reason(ev, state)
                db.mark_event_triggered(
                    state,
                    ev.id,
                    source="fiscal_levy_shadow",
                    terminal_reason=label,
                    commit=False,
                )
                terminal_records[ev.id] = {
                    "terminal_state": "triggered",
                    "terminal_reason": label,
                }
                applied.append({
                    "id": ev.id,
                    "title": ev.title,
                    "terminal_state": "triggered",
                    "terminal_reason": label,
                })
        _apply_fiscal_levy_targets(db, state, terminal_records)

    if should_commit:
        with atomic(db):
            run_fiscal_levy_pass()
    else:
        run_fiscal_levy_pass()
    return applied


_EVENT_GATE_KEY_RE = re.compile(r"^event\.([^.]+)\.(triggered|terminal_state|terminal_reason)$")


def _numeric_predicate_accepts(op: str, candidate: int, value: int) -> bool:
    if op == ">=":
        return candidate >= value
    if op == "<=":
        return candidate <= value
    if op == ">":
        return candidate > value
    if op == "<":
        return candidate < value
    if op == "==":
        return candidate == value
    return False


def _event_triggered_numeric_dependency_kind(op: str, value: int) -> str:
    """Classify event.<id>.triggered predicates over the boolean ledger domain {0, 1}."""
    accepts_false = _numeric_predicate_accepts(op, 0, value)
    accepts_true = _numeric_predicate_accepts(op, 1, value)
    if accepts_true and not accepts_false:
        return "positive"
    if accepts_false and not accepts_true:
        return "negative"
    if accepts_false and accepts_true:
        return "both"
    return "neither"


def _event_dependency_ids(ev: Event) -> set[str]:
    ids: set[str] = set()
    for key in (ev.trigger_gate or {}):
        m = _EVENT_GATE_KEY_RE.match(str(key))
        if m:
            ids.add(m.group(1))
    return ids


_EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE: set[tuple[tuple[str, tuple[str, ...]], ...]] = set()


def _validate_event_dependency_graph_acyclic(content: GameContent, state: GameState) -> None:
    raw_graph: Dict[str, set[str]] = {
        ev.id: _event_dependency_ids(ev)
        for ev in [*content.events, *content.seed_events]
        if getattr(ev, "id", "")
    }
    graph = {eid: {dep for dep in deps if dep in raw_graph} for eid, deps in raw_graph.items() if deps}
    cache_key = tuple(sorted((eid, tuple(sorted(deps))) for eid, deps in graph.items()))
    if cache_key in _EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE:
        return

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: List[str] = []

    def dfs(eid: str) -> None:
        if eid in visiting:
            cycle = stack[stack.index(eid):] + [eid] if eid in stack else [eid, eid]
            raise SettlementAbort(
                f"事件链依赖存在环：{' -> '.join(cycle)}",
                turn=state.turn,
                stage="event_chain_config",
            )
        if eid in visited:
            return
        visiting.add(eid)
        stack.append(eid)
        for dep in sorted(graph.get(eid, set())):
            dfs(dep)
        stack.pop()
        visiting.remove(eid)
        visited.add(eid)

    for eid in sorted(graph):
        dfs(eid)
    _EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE.add(cache_key)


def _event_chain_impossible_reason(ev: Event, terminal_records: Dict[str, Dict[str, str]], state: GameState) -> str:
    allowed_states: Dict[str, set[str]] = {}
    forbidden_states: Dict[str, set[str]] = {}
    allowed_outcomes: Dict[str, set[str]] = {}
    forbidden_outcomes: Dict[str, set[str]] = {}

    def _format_values(values: set[str]) -> str:
        return "|".join(sorted(values))

    def allow_states(upstream_id: str, state_names: set[str], *, raw_key: object, raw_cond: str) -> None:
        if not state_names:
            return
        existing = allowed_states.get(upstream_id)
        if existing is None:
            allowed_states[upstream_id] = set(state_names)
            return
        narrowed = existing & state_names
        if not narrowed:
            raise SettlementAbort(
                "事件链正向终态门互相矛盾："
                f"{upstream_id} 已要求 {{{_format_values(existing)}}}，"
                f"又要求 {{{_format_values(state_names)}}}（{raw_key} {raw_cond}）",
                turn=state.turn,
                stage="event_chain_config",
            )
        allowed_states[upstream_id] = narrowed

    def allow_state(upstream_id: str, state_name: str, *, raw_key: object, raw_cond: str) -> None:
        allow_states(upstream_id, {state_name}, raw_key=raw_key, raw_cond=raw_cond)

    def allow_outcomes(upstream_id: str, outcomes: set[str], *, raw_key: object, raw_cond: str) -> None:
        if not outcomes:
            return
        existing = allowed_outcomes.get(upstream_id)
        if existing is None:
            allowed_outcomes[upstream_id] = set(outcomes)
            return
        narrowed = existing & outcomes
        if not narrowed:
            raise SettlementAbort(
                "事件链正向结局门互相矛盾："
                f"{upstream_id} 已要求 {{{_format_values(existing)}}}，"
                f"又要求 {{{_format_values(outcomes)}}}（{raw_key} {raw_cond}）",
                turn=state.turn,
                stage="event_chain_config",
            )
        allowed_outcomes[upstream_id] = narrowed

    def forbid_state(upstream_id: str, state_name: str) -> None:
        forbidden_states.setdefault(upstream_id, set()).add(state_name)

    for raw_key, raw_cond in (ev.trigger_gate or {}).items():
        m = _EVENT_GATE_KEY_RE.match(str(raw_key))
        if not m:
            continue
        upstream_id, field = m.group(1), m.group(2)
        cond = str(raw_cond).strip()
        if field == "triggered":
            num = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+)$", cond)
            if not num:
                continue
            op, value = num.group(1), int(num.group(2))
            dependency_kind = _event_triggered_numeric_dependency_kind(op, value)
            if dependency_kind == "positive":
                allow_state(upstream_id, "triggered", raw_key=raw_key, raw_cond=cond)
            elif dependency_kind == "negative":
                forbid_state(upstream_id, "triggered")
            elif dependency_kind == "neither":
                raise SettlementAbort(
                    f"事件链 triggered 门在布尔域 {{0,1}} 上永不满足：{raw_key} {cond}",
                    turn=state.turn,
                    stage="event_chain_config",
                )
            continue
        text = re.match(r"^(==|!=|in=)\s*(.+)$", cond)
        if not text:
            continue
        op, value = text.group(1), text.group(2).strip()
        values = {part.strip() for part in value.split("|") if part.strip()}
        if field == "terminal_state":
            if op in ("==", "in="):
                allow_states(upstream_id, values, raw_key=raw_key, raw_cond=cond)
            elif op == "!=":
                forbidden_states.setdefault(upstream_id, set()).update(values)
        elif field == "terminal_reason":
            # Outcome labels are frozen only for triggered events; a positive outcome
            # predicate therefore implies terminal_state == triggered.
            if op in ("==", "in="):
                allow_state(upstream_id, "triggered", raw_key=raw_key, raw_cond=cond)
                allow_outcomes(upstream_id, values, raw_key=raw_key, raw_cond=cond)
            elif op == "!=":
                forbidden_outcomes.setdefault(upstream_id, set()).update(values)

    for upstream_id in sorted(_event_dependency_ids(ev)):
        record = terminal_records.get(upstream_id)
        if not record:
            continue
        state_val = record["terminal_state"]
        outcome = record["terminal_reason"]
        allowed = allowed_states.get(upstream_id, set())
        if allowed and state_val not in allowed:
            if allowed == {"triggered"}:
                return f"上游事件 {upstream_id} 已入非触发终态：{state_val}"
            return f"上游事件 {upstream_id} 终态不满足门：{state_val}"
        forbidden_states_for_upstream = forbidden_states.get(upstream_id, set())
        if state_val in forbidden_states_for_upstream:
            if forbidden_states_for_upstream == {"triggered"}:
                return f"上游事件 {upstream_id} 已触发"
            return f"上游事件 {upstream_id} 已入禁用终态：{state_val}"
        allowed_outcome_values = allowed_outcomes.get(upstream_id, set())
        if allowed_outcome_values and outcome and outcome not in allowed_outcome_values:
            return f"上游事件 {upstream_id} 已发其他结局：{outcome}"
        forbidden = forbidden_outcomes.get(upstream_id, set())
        if forbidden and state_val == "triggered" and outcome in forbidden:
            return f"上游事件 {upstream_id} 已发禁用结局：{outcome}"
    return ""


def apply_event_cascading_invalidations(
    state: GameState,
    db: GameDB,
    *,
    commit: bool = True,
) -> List[Dict[str, object]]:
    """Invalidate downstream historical events whose event-chain gates are now impossible.

    Only frozen event terminal/outcome ledger facts are invalidation grounds.  Other
    trigger_gate clauses (regions, locations, offices, etc.) remain soft gates and
    are deliberately ignored here because they may flip later.
    """
    content = _ctx()
    _validate_event_dependency_graph_acyclic(content, state)
    should_commit = commit and not db.conn.in_transaction
    terminalized: List[Dict[str, object]] = []
    terminal_records = _event_terminal_records(db)

    def run_cascade() -> None:
        while True:
            changed = False
            for ev in [*content.events, *content.seed_events]:
                if not getattr(ev, "id", "") or ev.id in terminal_records:
                    continue
                if not _event_dependency_ids(ev):
                    continue
                reason = _event_chain_impossible_reason(ev, terminal_records, state)
                if not reason:
                    continue
                db.mark_event_obsolete(
                    state,
                    ev.id,
                    reason=reason,
                    source="event_chain_invalidated",
                    commit=False,
                )
                row = db.find_active_issue_by_origin("event_pool", ev.id)
                if row is not None:
                    db.cancel_issue(state, int(row["id"]), narrative=f"事件链作废：{reason}", commit=False)
                item: Dict[str, object] = {"id": ev.id, "title": ev.title, "terminal_state": "obsolete", "reason": reason}
                terminalized.append(item)
                terminal_records[ev.id] = {"terminal_state": "obsolete", "terminal_reason": reason}
                changed = True
            if not changed:
                break

    if should_commit:
        with atomic(db):
            run_cascade()
    else:
        run_cascade()
    return terminalized


def _spawned_event_refs(db: GameDB) -> set:
    refs = _event_issue_refs(db)
    refs.update(_event_trigger_refs(db))
    return refs


def _event_window_open(ev: Event, state: GameState) -> bool:
    """Return True when the current date is inside an event's optional trigger window."""
    if ev.trigger_year > 0:
        if state.year < ev.trigger_year:
            return False
        if state.year == ev.trigger_year and ev.trigger_month > 0 and state.period < ev.trigger_month:
            return False
    if ev.open_window:
        return True
    if ev.trigger_end_year > 0:
        if state.year > ev.trigger_end_year:
            return False
        if state.year == ev.trigger_end_year and ev.trigger_end_month > 0 and state.period > ev.trigger_end_month:
            return False
    return True


def _event_window_expired(ev: Event, state: GameState) -> bool:
    """Return True once the current date is past an event's explicit latest point."""
    if ev.open_window:
        return False
    if ev.trigger_end_year <= 0:
        return False
    if state.year > ev.trigger_end_year:
        return True
    if ev.trigger_end_month > 0 and state.year == ev.trigger_end_year and state.period > ev.trigger_end_month:
        return True
    return False


def _dead_person_core_subjects(ev: Event, db: GameDB) -> List[str]:
    dead: List[str] = []
    for name in getattr(ev, "person_core_subjects", []) or []:
        row = db.conn.execute(
            "SELECT status FROM characters WHERE name = ?",
            (str(name),),
        ).fetchone()
        if row is not None and str(row["status"] or "") == "dead":
            dead.append(str(name))
    return dead


def _person_core_avoided_reason(ev: Event, state: GameState, db: GameDB) -> str:
    subjects = [str(name) for name in (getattr(ev, "person_core_subjects", []) or []) if str(name)]
    if not subjects:
        return ""
    gate = ev.trigger_gate or {}
    subject_prefixes = tuple(f"character.{name}." for name in subjects)
    subject_gate = {
        key: cond
        for key, cond in gate.items()
        if any(str(key).startswith(prefix) for prefix in subject_prefixes)
    }
    if not subject_gate:
        return ""
    if _gate_passed(subject_gate, state.metrics, db):
        return ""
    return f"人物核心前提已被玩家处理：{', '.join(subjects)}"


_GATE_AGG_FUNCS = {
    "max": max,
    "min": min,
    "sum": sum,
    "avg": lambda xs: sum(xs) / max(1, len(xs)),
}


_CHARACTER_NUMERIC_GATE_FIELDS = (
    "loyalty",
    "ability",
    "integrity",
    "courage",
    "birth_year",
    "historical_death_year",
    "historical_death_month",
    "debut_year",
    "debut_month",
    "status_changed_turn",
)
_GATE_NUMERIC_SQL_FIELDS = {
    "region": set(REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + ("city_level", "cannon")),
    "army": set(ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS),
    "building": set(BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS),
    "power": set(POWER_SCORE_FIELDS),
    "faction": {"satisfaction", "leverage"},
    "character": set(_CHARACTER_NUMERIC_GATE_FIELDS),
    "class": {"population", "satisfaction", "leverage"},
    "event": {"triggered"},
}
_GATE_TEXT_SQL_FIELDS = {
    "region": set(REGION_TEXT_FIELDS),
    "army": set(ARMY_TEXT_FIELDS),
    "power": set(POWER_TEXT_FIELDS),
    "character": set(CHARACTER_TEXT_FIELDS),
    "event": {"terminal_state", "terminal_reason"},
}
_GATE_SQL_FIELDS = {
    table: set(fields) | set(_GATE_TEXT_SQL_FIELDS.get(table, set()))
    for table, fields in _GATE_NUMERIC_SQL_FIELDS.items()
}
for _table, _fields in _GATE_TEXT_SQL_FIELDS.items():
    _GATE_SQL_FIELDS.setdefault(_table, set()).update(_fields)


def _gate_sql_field(table: str, field: str, key: str, *, kind: str) -> str:
    allowed = _GATE_SQL_FIELDS.get(table)
    if allowed is None or field not in allowed:
        raise ValueError(f"trigger_gate key「{key}」字段无效：{table}.{field}")
    typed_allowed = _GATE_NUMERIC_SQL_FIELDS if kind == "numeric" else _GATE_TEXT_SQL_FIELDS
    if field not in typed_allowed.get(table, set()):
        label = "非数值" if kind == "numeric" else "非文本"
        raise ValueError(f"trigger_gate key「{key}」字段{label}（比较类型不匹配）：{table}.{field}")
    return field


def _eval_gate_key(key: str, metrics: Dict[str, int], db: GameDB) -> Optional[float]:
    """把 gate key 解析成一个数值。形式：
      - 'metric_name'                           → metrics[key]
      - 'region.<id>.<field>'                   → regions 表
      - 'region.<id1>|<id2>|.<field>.<agg>'     → 多省聚合 (max/min/avg/sum)
      - 'army.<id>.<field>' / 多军 + agg
      - 'building.<id>.<field>' / 多建筑 + agg
      - 'power.<id>.<field>' / 多 + agg
      - 'character.<name>.<field>' / 多人物 + agg
      - 'event.<id>.terminal_state'               → event_triggers 表文本门专用
      - 'class.<name>.<field>'                  → classes 表全国汇总 (region_id='')
      - 'class.<name>@<region>.<field>'         → classes 表省级
      - 'class.<name>@<r1>|<r2>|.<field>.<agg>' → 多省同阶级聚合
      - 'event.<id>.triggered'                  → event_triggers 账，已发=1 未发=0
    解析失败/数据缺失返回 None（gate 视为不通过，由调用方处理）。
    """
    if "." not in key:
        if key in metrics:
            try:
                return int(metrics[key])
            except (TypeError, ValueError):
                return None
        return None
    parts = key.split(".")
    table = parts[0]
    if table not in GATE_TABLES:
        return None
    # 末段可能是 agg，先抽出
    agg = None
    if parts[-1] in _GATE_AGG_FUNCS:
        agg = parts[-1]
        parts = parts[:-1]
    if len(parts) < 3:
        return None
    field = parts[-1]
    id_segment = ".".join(parts[1:-1])
    field = _gate_sql_field(table, field, key, kind="numeric")
    if table == "class" and "@" in id_segment and "|" in id_segment.split("@", 1)[1]:
        # 简写：class.<name>@<r1>|<r2>|<r3>.<field> → 展开成 [name@r1, name@r2, name@r3]
        cname, rest = id_segment.split("@", 1)
        ids = [f"{cname}@{r}" for r in rest.split("|") if r]
    else:
        ids = id_segment.split("|") if "|" in id_segment else [id_segment]
        ids = [x for x in ids if x]
    if not ids:
        return None
    # class 表的 id 是 name 或 name@region；其它表 id 就是行 id
    values: List[float] = []
    for cid in ids:
        row = None
        if table == "event":
            if cid not in db.content.event_by_id:
                return None
            values.append(1 if db.has_event_terminal_state(cid, "triggered") else 0)
            continue
        if table == "region":
            row = db.conn.execute(f"SELECT {field} FROM regions WHERE id = ?", (cid,)).fetchone()
        elif table == "army":
            row = db.conn.execute(f"SELECT {field} FROM armies WHERE id = ?", (cid,)).fetchone()
        elif table == "building":
            row = db.conn.execute(f"SELECT {field} FROM buildings WHERE id = ?", (cid,)).fetchone()
        elif table == "power":
            row = db.conn.execute(f"SELECT {field} FROM powers WHERE id = ?", (cid,)).fetchone()
        elif table == "faction":
            # factions 表主键是 name（中文，如 阉党），field 取 leverage/satisfaction
            row = db.conn.execute(f"SELECT {field} FROM factions WHERE name = ?", (cid,)).fetchone()
        elif table == "character":
            row = db.conn.execute(f"SELECT {field} FROM characters WHERE name = ?", (cid,)).fetchone()
        elif table == "class":
            if "@" in cid:
                cname, rid = cid.split("@", 1)
            else:
                cname, rid = cid, ""
            row = db.conn.execute(
                f"SELECT {field} FROM classes WHERE name = ? AND region_id = ?",
                (cname, rid),
            ).fetchone()
        if row is None:
            return None
        try:
            values.append(float(row[0]))
        except ValueError as exc:
            # 非数值字符串 = 数值 cond 配了文本字段（如 region.x.controlled_by >=1）→ 数值转换不动。
            # fail-loud 成清晰 content 错误（#159；Q3：trigger_gate 字段类型错属静态 content schema 错，
            # 不静默回 None 当条件不满足）。NULL/None 走 TypeError 分支视同不达标（合法数据，非内容错）。
            raise ValueError(
                f"trigger_gate key「{key}」字段非数值（数值比较不可比文本字段）：{row[0]!r}"
            ) from exc
        except TypeError:
            return None
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    if agg is None:
        # 多 id 但没指明聚合 → 默认 min（最严苛，要全部满足）
        agg = "min"
    return _GATE_AGG_FUNCS[agg](values)


def _eval_gate_key_str(key: str, db: GameDB) -> Optional[str]:
    """取一个文本型字段值（如 region.<id>.controlled_by → 'ming'/'houjin'）。
    仅支持单 id 的 region/army/power/character/event 文本字段；解析失败返回 None。
    """
    parts = key.split(".")
    if len(parts) != 3:
        return None
    table, cid, field = parts
    field = _gate_sql_field(table, field, key, kind="text")
    sql = {
        "region": f"SELECT {field} FROM regions WHERE id = ?",
        "army": f"SELECT {field} FROM armies WHERE id = ?",
        "power": f"SELECT {field} FROM powers WHERE id = ?",
        "character": f"SELECT {field} FROM characters WHERE name = ?",
        "event": f"SELECT {field} FROM event_triggers WHERE event_id = ?",
    }.get(table)
    if sql is None:
        return None
    row = db.conn.execute(sql, (cid,)).fetchone()
    if row is None:
        return None
    return str(row[0])


def _gate_passed(gate: Dict[str, str], metrics: Dict[str, int], db: GameDB) -> bool:
    """trigger_gate 全部条件满足才返回 True。条件形如 '<=240'（数值）或 '==ming'（文本相等）。
    key 形式见 _eval_gate_key。gate=None（content JSON 显式 null）视同空门、恒过，不 .items()
    AttributeError 崩候选收集（PR#107 gemini；集中守 None，seed/历史两分支共用此函数同得保护）。
    """
    for key, cond in (gate or {}).items():
        cond = str(cond).strip()  # 非字符串条件值(JSON 漏引号写成 60/True)先 str 强转，不 .strip() 崩（PR#107 gemini）
        # 文本相等 / 枚举：==<word> / !=<word> / in=a|b（RHS 非纯数字）
        sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond)
        if sm and (sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())):
            sop, sval = sm.group(1), sm.group(2).strip()
            try:
                cur = _eval_gate_key_str(key, db)
            except sqlite3.OperationalError as exc:
                # typo'd 字段名 → SELECT 绑 SQLite 抛「no such column」；fail-loud 成清晰 content
                # 错误（#12 Q3：trigger_gate 字段错属静态 content schema 错）。其它 DB 错（锁/无表等）
                # 不误标字段，原样上抛（online sourcery）。
                if "no such column" in str(exc).lower():
                    raise ValueError(f"trigger_gate key「{key}」字段无效（DB 无此列）：{exc}") from exc
                raise
            if cur is None:
                return False
            if sop == "==" and cur != sval:
                return False
            if sop == "!=" and cur == sval:
                return False
            if sop == "in=" and cur not in {part.strip() for part in sval.split("|") if part.strip()}:
                return False
            continue
        m = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+)$", cond)
        if not m:
            return False
        op, num = m.group(1), int(m.group(2))
        try:
            val = _eval_gate_key(key, metrics, db)
        except sqlite3.OperationalError as exc:
            if "no such column" in str(exc).lower():
                raise ValueError(f"trigger_gate key「{key}」字段无效（DB 无此列）：{exc}") from exc
            raise  # 其它 DB 错不误标字段（online sourcery）
        if val is None:
            return False
        if op == ">=" and not val >= num:
            return False
        if op == "<=" and not val <= num:
            return False
        if op == ">" and not val > num:
            return False
        if op == "<" and not val < num:
            return False
        if op == "==" and not val == num:
            return False
    return True


def gather_impeachment_surge_candidates(state: GameState, db: GameDB) -> List[Dict[str, object]]:
    """Project canonical dynamic candidates from transformed dossier facts.

    Other disaster legs deliberately have no adapter until their owning producers
    provide a durable occurrence and responsibility interface.
    """
    facts = db.build_faction_denunciation_facts()
    situations = {
        str(item.get("faction") or ""): item
        for item in facts.get("faction_situations", [])
        if isinstance(item, dict)
    }
    personas_by_faction: Dict[str, List[Dict[str, object]]] = {}
    for item in facts.get("character_personas", []):
        if isinstance(item, dict):
            personas_by_faction.setdefault(str(item.get("faction") or ""), []).append(item)

    rows = db.conn.execute(
        "SELECT id,closed_turn,participant_roster,decree_text,execution_note,execution_outcome "
        "FROM decree_dossiers "
        "WHERE execution_outcome='transformed' AND closed_turn BETWEEN ? AND ? ORDER BY id",
        (max(0, int(state.turn) - 1), int(state.turn)),
    ).fetchall()
    candidates: List[Dict[str, object]] = []
    for row in rows:
        did = int(row["id"])
        # #622/#1260 单源：仅有旨外 durable 的变形才构成 deformation_exposure。
        if not db.dossier_has_beyond_intent(did):
            continue
        try:
            roster = json.loads(str(row["participant_roster"] or "[]"))
        except (TypeError, ValueError):
            continue
        if not isinstance(roster, list) or not roster:
            continue
        participant_ids = [
            str(item.get("character_id") or "").strip()
            for item in roster if isinstance(item, dict) and str(item.get("character_id") or "").strip()
        ]
        if len(participant_ids) != len(roster) or not participant_ids:
            continue
        liability = project_execution_liability_parties(roster)
        responsible_ids = [
            str(item.get("character_id") or "").strip() for item in liability
            if str(item.get("character_id") or "").strip()
        ]
        if not responsible_ids:
            continue
        # 存在门只看责任集；知情/协办离场不得 any() 否决整卷。
        placeholders = ",".join("?" for _ in responsible_ids)
        chars = db.conn.execute(
            f"SELECT name,faction,status FROM characters WHERE name IN ({placeholders})",
            responsible_ids,
        ).fetchall()
        char_by_name = {str(item["name"]): item for item in chars}
        if any(
            name not in char_by_name
            or str(char_by_name[name]["status"] or "") != "active"
            or not str(char_by_name[name]["faction"] or "").strip()
            for name in responsible_ids
        ):
            continue
        responsible_factions = list(dict.fromkeys(
            str(char_by_name[name]["faction"]) for name in responsible_ids
        ))
        # 闭集：在朝 participant ∪ 在朝 responsible（含仅 delegator_id 连坐）。
        union_ids = list(dict.fromkeys([*participant_ids, *responsible_ids]))
        missing = [name for name in union_ids if name not in char_by_name]
        if missing:
            missing_ph = ",".join("?" for _ in missing)
            for item in db.conn.execute(
                f"SELECT name,faction,status FROM characters WHERE name IN ({missing_ph})",
                missing,
            ).fetchall():
                char_by_name[str(item["name"])] = item
        eligible_target_ids = [
            name for name in union_ids
            if name in char_by_name
            and str(char_by_name[name]["status"] or "") == "active"
            and str(char_by_name[name]["faction"] or "").strip()
        ]
        if not eligible_target_ids:
            continue
        fork_state = db.read_dossier_fork_state(did)
        beyond_intent_effects = [
            dict(effect)
            for effect in db.list_dossier_durable_effects(did)
            if bool(effect.get("beyond_intent"))
        ]
        origin_ref = f"commitment:{did}:deformation_exposure"
        for faction in sorted(_LEVERAGE_FACTIONS):
            if faction in responsible_factions or db.faction_leverage(faction) < 60:
                continue
            situation = situations.get(faction)
            personas = personas_by_faction.get(faction, [])
            if not situation or not personas:
                continue
            if db.conn.execute(
                "SELECT 1 FROM issues WHERE origin_kind='impeachment_surge' "
                "AND origin_ref=? AND faction_hint=? LIMIT 1", (origin_ref, faction),
            ).fetchone():
                continue
            candidate_id = f"impeachment_surge:{origin_ref}:{faction}"
            candidates.append({
                "id": candidate_id,
                "origin_kind": "impeachment_surge",
                "origin_ref": origin_ref,
                "source_kind": "deformation_exposure",
                "occurred_turn": int(row["closed_turn"]),
                "faction_id": faction,
                "faction_persona": {
                    "faction_situations": [dict(situation)],
                    "character_personas": [dict(item) for item in personas],
                },
                "eligible_target_ids": eligible_target_ids,
                "participant_ids": participant_ids,
                "responsible_person_ids": responsible_ids,
                "responsible_faction_ids": responsible_factions,
                "dossier_id": did,
                "decree_text": str(row["decree_text"] or "").strip(),
                "execution_note": str(row["execution_note"] or "").strip(),
                "execution_outcome": str(row["execution_outcome"] or "").strip(),
                "beyond_intent": True,
                "reported_bands": list(fork_state.get("reported_bands") or []),
                "actual_effect_count": int(fork_state.get("actual_effect_count") or 0),
                "beyond_intent_effects": beyond_intent_effects,
            })
    return candidates


def gather_candidate_events(state: GameState, db: GameDB) -> List[Event]:
    """程序筛选：历史锚定事件按 trigger 时间到点、seed 情势按 trigger_gate 达标，
    都排除已触发过的。返回的候选清单交推演 agent 因果判定是否真触发。"""
    c = _ctx()
    spawned = _spawned_event_refs(db)
    candidates: List[Event] = []
    # 历史锚定 EVENTS：到点（含错过补出）即进候选
    for ev in c.events:
        if ev.id in spawned or ev.trigger_year <= 0:
            continue
        if _event_window_expired(ev, state):
            continue
        if ev.auto_trigger:
            continue
        dead_subjects = _dead_person_core_subjects(ev, db)
        if dead_subjects:
            continue
        if not _event_window_open(ev, state):
            continue
        # 历史事件带结构化前提门时也须达标（与 seed 情势同门）：纯日历窗口会放行前提已不成立
        # 的事件误触发（#12 毛文龙：已安抚/效顺仍按年月弹出）。无 gate（空 dict）→ 恒过、行为不变。
        if not _gate_passed(ev.trigger_gate, state.metrics, db):
            avoided_reason = _person_core_avoided_reason(ev, state, db)
            if avoided_reason:
                continue
            continue
        candidates.append(ev)
    # seed 情势：trigger_gate 阈值达标即进候选
    for ev in c.seed_events:
        if ev.id in spawned:
            continue
        if _event_window_expired(ev, state):
            continue
        # auto_trigger 事件只能由程序硬触发，绝不进 LLM 候选池
        if ev.auto_trigger:
            continue
        if not _event_window_open(ev, state):
            continue
        if _gate_passed(ev.trigger_gate, state.metrics, db):
            candidates.append(ev)
    return candidates


def apply_event_terminal_states(
    state: GameState,
    db: GameDB,
    *,
    commit: bool = True,
) -> List[Dict[str, object]]:
    """Persist deterministic event terminal states from the current board position."""
    c = _ctx()
    should_commit = commit and not db.conn.in_transaction
    terminal_refs = _event_trigger_refs(db)
    terminalized: List[Dict[str, object]] = []

    def run_terminal_state_pass() -> None:
        for ev in c.events:
            if ev.id in terminal_refs or ev.trigger_year <= 0:
                continue
            if _event_window_expired(ev, state):
                db.mark_event_expired(state, ev.id, commit=False)
                terminal_refs.add(ev.id)
                terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "expired"})
                continue
            dead_subjects = _dead_person_core_subjects(ev, db)
            if dead_subjects:
                reason = f"人物核心主体永久死亡：{', '.join(dead_subjects)}"
                db.mark_event_obsolete(state, ev.id, reason=reason, commit=False)
                terminal_refs.add(ev.id)
                terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "obsolete"})
                continue
            if not _event_window_open(ev, state):
                continue
            if not _gate_passed(ev.trigger_gate, state.metrics, db):
                avoided_reason = _person_core_avoided_reason(ev, state, db)
                if avoided_reason:
                    db.mark_event_avoided(state, ev.id, reason=avoided_reason, commit=False)
                    terminal_refs.add(ev.id)
                    terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "avoided"})

        for ev in c.seed_events:
            if ev.id in terminal_refs:
                continue
            if _event_window_expired(ev, state):
                db.mark_event_expired(state, ev.id, commit=False)
                terminal_refs.add(ev.id)
                terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "expired"})

        terminalized.extend(apply_event_cascading_invalidations(state, db, commit=False))

    if should_commit:
        with atomic(db):
            run_terminal_state_pass()
    else:
        run_terminal_state_pass()
    return terminalized


def auto_trigger_seed_issues(state: GameState, db: GameDB) -> List[Dict[str, object]]:
    """程序硬触发：seed_events 中标了 auto_trigger 的，trigger_gate 达标即由程序直接
    立 issue，绕过 LLM 因果判定（不进候选池等 extractor 决定）。event_to_issue 自带去重，
    已触发过返回 None 自动跳过。返回本回合硬触发的清单（供日志/邸报告知）。

    放在结算链 simulator 之前调用，使硬立的 issue 当回合即进盘面、被邸报叙述。"""
    with atomic(db):
        return _auto_trigger_seed_issues_in_atomic(state, db)


def _auto_trigger_seed_issues_in_atomic(state: GameState, db: GameDB) -> List[Dict[str, object]]:
    """auto_trigger_seed_issues 的事务体；由外层函数或 pre_settle 嵌套事务统一提交/回滚。"""
    c = _ctx()
    terminal_states = _event_terminal_states(db)
    triggered: List[Dict[str, object]] = []
    for ev in [*c.events, *c.seed_events]:
        historical_event = any(ev is item for item in c.events)
        if not ev.auto_trigger:
            continue
        terminal_state = terminal_states.get(ev.id)
        if terminal_state and (historical_event or terminal_state == "expired"):
            continue
        if _event_window_expired(ev, state):
            db.mark_event_expired(state, ev.id, commit=False)
            terminal_states[ev.id] = "expired"
            continue
        # trigger_gate 为空 = 开局即立的局势，只由 seed_opening_crises 立一次，绝不在此重立。
        # （空 gate 会被 _gate_passed 判为恒真，必须显式排除，否则每回合都试图重立。）
        if ev in c.seed_events and not ev.trigger_gate:
            continue
        if not _event_window_open(ev, state):
            continue
        if not _gate_passed(ev.trigger_gate, state.metrics, db):
            continue
        if ev.event_type != "situation":
            # 非 situation（node/ending）不转 issue，仅记触发避免重复
            if not db.has_event_triggered(ev.id):
                if ev.effect_on_trigger:
                    issue_effects._apply_issue_entities(
                        db,
                        state,
                        _content_population_effect_for_save(db, ev.effect_on_trigger),
                        f"事件#{ev.id}触发",
                        content=c,
                    source=Provenance.system_simulation)
                db.mark_event_triggered(state, ev.id)
                triggered.append({"id": ev.id, "title": ev.title, "kind": ev.event_type})
            continue
        issue_id = event_to_issue(db, state, ev, commit=False)
        created_issue = issue_id is not None
        if historical_event and issue_id is None:
            row = (
                db.find_active_issue_by_origin("event_pool", ev.id)
                if ev.trigger_gate
                else db.find_any_issue_by_origin("event_pool", ev.id)
            )
            if row is None:
                raise RuntimeError(f"历史事件 {ev.id} 未建局势且无法找到同源 issue")
            issue_id = int(row["id"])
        if historical_event:
            if ev.effect_on_trigger:
                issue_effects._apply_issue_entities(
                    db,
                    state,
                    _content_population_effect_for_save(db, ev.effect_on_trigger),
                    f"事件#{ev.id}触发",
                    content=c,
                source=Provenance.system_simulation)
            db.mark_event_triggered(state, ev.id)
        if issue_id is not None:
            triggered.append({"id": ev.id, "title": ev.title, "issue_id": issue_id})
            action = "硬立项" if created_issue else "补记"
            print(f"[AUTO-TRIGGER] gate 达标{action} #{issue_id} {ev.title}（{ev.trigger_gate}）")
    apply_event_cascading_invalidations(state, db, commit=False)
    return triggered


def _bar_ascii(value: int, width: int = 20) -> str:
    value = max(0, min(100, int(value)))
    pos = int(round(value / 100 * (width - 1)))
    return "●" + ("━" * pos) + "○" + ("━" * (width - 1 - pos))



def _format_inertia(inertia: int) -> str:
    if inertia > 0:
        return f"自然推进 +{inertia}/{TURN_UNIT}"
    if inertia < 0:
        return f"自然恶化 {inertia}/{TURN_UNIT}"
    return "势均力敌"


def show_active_issues(db: GameDB) -> None:
    issues = db.list_active_issues()
    if not issues:
        return
    state = db.load_state()
    initiatives = [i for i in issues if i["kind"] == "initiative"]
    situations = [i for i in issues if i["kind"] == "situation"][:12]
    print(f"─── 待办事项 (系统 {len(situations)}/12  玩家 {len(initiatives)}) ───")

    def _print_row(row, label: str) -> None:
        bar = _bar_ascii(int(row["bar_value"]))
        print(f"{label} #{row['id']} {row['title']}")
        print(f"  {row['bar_bad_meaning']:6s} {bar} {row['bar_good_meaning']:6s}  bar={int(row['bar_value']):3d}  {row['stage_text']}")
        inertia = int(row["inertia"])
        ongoing_txt = issue_effects._format_issue_ongoing(row["ongoing_effects"] or "{}")
        line_parts = [_format_inertia(inertia)]
        progress = commitment_display.commitment_progress_payload(db, state, row)
        if progress is not None:
            line_parts.append(commitment_display.commitment_display_text(progress, row))
        if ongoing_txt:
            line_parts.append(f"每{TURN_UNIT}固定：{ongoing_txt}")
        print(f"  {' | '.join(line_parts)}")

    for row in situations:
        cancel_tag = "不可撤" if row["cancellable"] == "never" else ("唯由进度" if row["cancellable"] == "by_progress" else "可撤旨")
        _print_row(row, f"[系统/{cancel_tag}]")
    for row in initiatives:
        _print_row(row, "[玩家/可撤旨]")
    print()


def event_to_issue(db: GameDB, state: GameState, ev: Event, *, commit: bool = True) -> Optional[int]:
    """把一个预设 event（EVENTS / SEED_EVENTS）落成一条 situation issue。供推演判定触发后调用。

    去重分两类：
    - 无 trigger_gate（开局局势）：查任意状态同源 issue，立过则永不重立。
    - 有 trigger_gate（条件触发危机）：只查 active 同源 issue，结案/撤销后 gate 再达标可重新触发。
    """
    if ev.trigger_gate:
        if db.find_active_issue_by_origin("event_pool", ev.id) is not None:
            return None
    else:
        if db.find_any_issue_by_origin("event_pool", ev.id) is not None:
            return None
    # 初值由 severity 推一个偏中性的 bar
    bar = max(20, min(60, 50 - int(ev.severity / 5)))
    # 默认 ongoing + inertia 五档（+10/+5/0/-5/-10），按 kind 取
    ongoing: Dict[str, object] = {}
    inertia = -5
    # 终结一锤子永久数值：达成（bar→100）落 effect_on_resolve，崩坏（bar→0 或 LLM 判失败）落
    # effect_on_fail。与 ongoing 过程效果区分——过程是每月漂移，终结是定局后的永久民心/皇威增减。
    polarity = "neg"  # neg=负面危机（平息回血/崩坏重创）；pos=正面机遇（把握加成/错失轻微）
    # 5 个原 metric（边防/民变/党争/执行/瞒报）已废除，ongoing_effects 按 kind 改用
    # 民心/皇威 或留空让 LLM 在推进时自定。结构性影响由 region/army/external/class delta 承担。
    if ev.kind in ("天灾", "灾情", "饥荒"):
        ongoing = {"metrics": {"民心": -2}, "economy": [{"account": "国库", "delta": -8, "category": "赈济损耗", "reason": ev.title}]}
        inertia = -10
    elif ev.kind in ("人祸", "兵变", "流寇", "民变", "抗税"):
        ongoing = {"metrics": {"民心": -2}}
        inertia = -10
    elif ev.kind in ("外族", "边事"):
        ongoing = {"metrics": {"皇威": -1}}
        inertia = -5
    elif ev.kind in ("党争", "朝议"):
        ongoing = {}
        inertia = -5
    elif ev.kind in ("丰收", "祥瑞", "民和"):
        ongoing = {"metrics": {"民心": 2}}
        inertia = +10
        polarity = "pos"
    elif ev.kind in ("友邦", "归附", "盟约"):
        ongoing = {"metrics": {"皇威": 1}}
        inertia = +5
        polarity = "pos"
    elif ev.kind in ("良策", "试点", "献宝", "科技"):
        inertia = +5
        polarity = "pos"
    elif ev.kind in ("战机", "敌乱"):
        ongoing = {"metrics": {"皇威": 1}}
        inertia = +10
        polarity = "pos"
    effect_resolve, effect_fail = _situation_terminal_effects(ev.kind, int(ev.severity), polarity)
    # 精调字段优先：合并自 opening_crises 的手调危机带 bar/ongoing/effect/meaning，直接用其值；
    # 缺省（0/空）则用上面按 severity/kind 推导的默认。
    if ev.bar_value:
        bar = ev.bar_value
    if ev.ongoing_effects:
        ongoing = ev.ongoing_effects
    if ev.issue_inertia:
        inertia = ev.issue_inertia
    if ev.effect_on_resolve:
        # #648：content 真源人口量已「人」，持久化进 issue 行前按本档口径换算，
        # 使后续结案/失败落账（读行内 effect）天然按档口径，无需在读取端再换算。
        effect_resolve = _content_population_effect_for_save(db, ev.effect_on_resolve)
    if ev.effect_on_fail:
        effect_fail = _content_population_effect_for_save(db, ev.effect_on_fail)
    # insert 的代码/DB 真异常上抛（ADR 0008 决定1 / ADR 0005 fail-loud），与 decree 路径
    # （apply_issue_tracker_output 的 new_issues 段）一致；旧 `except Exception: WARN; return None`
    # 把真异常吞成 None、调用方记普通 rejected，正是 #14/#63 catalog「该落没落无人知」实例
    # （cmr ni r7 codex high）。两种 None 来源已在上方分开：幂等去重经 find_*_by_origin 在此 try
    # 之外 early-return None（正常跳过），故此处无需也不应再兜真异常。
    issue_id = db.insert_issue(
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
        ongoing_effects=ongoing,
        cancellable="never",
        effect_on_resolve=effect_resolve,
        effect_on_fail=effect_fail,
        resolve_condition=ev.resolve_condition,
        fail_condition=ev.fail_condition,
        commit=False,
    )
    db.mark_event_triggered(state, ev.id, source="event_pool", commit=False)
    apply_event_cascading_invalidations(state, db, commit=False)
    if commit:
        db.conn.commit()
    return issue_id


_CHARACTER_TEXT_GATE_RE = re.compile(r"^character\.([^.]+)\.([A-Za-z_][A-Za-z0-9_]*)$")
_PENDING_PERSON_GATE_FIELDS = {
    "status", "status_reason", "reason_code", "location", "transit_to", "power_id", "office", "office_type",
}
_PENDING_POWER_GATE_FIELDS = {"leverage", "military_strength", "supply"}
_TEXT_CONDITION_RE = re.compile(r"^\s*(==|!=)\s*([^\s]+)\s*$")
_NUMERIC_CONDITION_RE = re.compile(r"^\s*(>=|<=|>|<|==)\s*(-?\d+)\s*$")


def _register_runtime_rollback_snapshot(
    db: GameDB,
    state: GameState,
    content: Optional[GameContent],
) -> None:
    """Restore process memory if the caller rolls back the surrounding DB transaction."""
    conn = db.conn
    callbacks = getattr(conn, "_runtime_rollback_callbacks", None)
    if callbacks is None:
        callbacks = []
        conn._runtime_rollback_callbacks = callbacks
    metrics_snapshot = dict(state.metrics)
    character_objects = dict(content.characters) if content is not None else {}
    character_attrs: Dict[str, Dict[str, object]] = {}
    for name, character in character_objects.items():
        try:
            character_attrs[name] = dict(vars(character))
        except TypeError:
            character_attrs[name] = {}
    def restore_runtime() -> None:
        state.metrics.clear()
        state.metrics.update(metrics_snapshot)
        if content is not None:
            for name in list(content.characters):
                if name not in character_objects:
                    del content.characters[name]
            for name, character in character_objects.items():
                content.characters[name] = character
                try:
                    for attr in list(vars(character)):
                        if attr not in character_attrs.get(name, {}):
                            delattr(character, attr)
                except TypeError:
                    pass
                for attr, value in character_attrs.get(name, {}).items():
                    setattr(character, attr, value)

    callbacks.append(restore_runtime)


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
        raise ValueError("行程语气不在闭合枚举")
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
    except ValueError:
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
_COLLAPSIBLE_KINDS = frozenset({
    "人祸", "兵变", "流寇", "民变", "抗税", "党争", "朝议", "外族", "边事",
})


def _situation_terminal_effects(kind: str, severity: int, polarity: str):
    """situation 终结一锤子永久效果。按 severity 推量级（轻 50 / 中 65 / 重 80）。
    resolve：达成（bar→100）落永久回血/加成，所有 situation 都有。
    fail：仅「会崩坏」局势（_COLLAPSIBLE_KINDS）有，崩坏（bar→0）落永久重创，幅度重于回血。
    民心/皇威由 kind 倾向决定（边事/外族偏皇威，灾害/民变偏民心，余者两者兼得）。"""
    mag = 1 if severity < 55 else (2 if severity < 70 else 3)
    if kind in ("外族", "边事", "友邦", "归附", "盟约", "战机", "敌乱"):
        axis = "皇威"
    elif kind in ("天灾", "灾情", "饥荒", "人祸", "兵变", "流寇", "民变", "抗税", "丰收", "祥瑞", "民和"):
        axis = "民心"
    else:
        axis = "both"

    def _metrics(amount: int) -> Dict[str, int]:
        if axis == "both":
            half = max(1, abs(amount) // 2)
            s = 1 if amount > 0 else -1
            return {"民心": s * half, "皇威": s * half}
        return {axis: amount}

    resolve_amt = (3 if polarity == "neg" else 4) * mag
    effect_resolve = {"metrics": _metrics(resolve_amt)}
    effect_fail = {"metrics": _metrics(-5 * mag)} if kind in _COLLAPSIBLE_KINDS else {}
    return effect_resolve, effect_fail


def _normalize_cancellable(raw: object) -> str:
    """LLM 偶发臆造 cancellable 值（by_policy 之类），归一到合法白名单。"""
    val = str(raw or "").strip().lower()
    if val in ("decree", "never", "by_progress"):
        return val
    # 常见臆造映射
    if val in ("by_policy", "policy"):
        return "decree"
    if val in ("none", "no", "false"):
        return "never"
    if val in ("yes", "true", "auto"):
        return "by_progress"
    return "by_progress"  # 默认


def _compute_inertia(ni: Dict[str, object]) -> int:
    """从 expected_months 算 inertia；兼容旧 inertia 直接填的写法。整数字段用 _strict_int 严格转换
    （拒 bool/float/非数/inf/nan，与 new_issues 其它整数字段一致，cmr ni r6 codex）——脏值抛
    ValueError/OverflowError，由唯一调用方 apply_issue_tracker_output 的预校验 try 拒整项。"""
    em_raw = ni.get("expected_months")
    if em_raw is not None:
        em = _strict_int(em_raw)  # bool/float（含 inf/nan）/非数 → ValueError
        if em != 0:
            return max(-10, min(10, round(100 / em)))
    legacy = ni.get("inertia")
    return max(-10, min(10, _strict_int(0 if legacy is None else legacy)))


# 离散时长档：LLM 只能给这几档（防乱填）；映射到月。
_LEGACY_DURATION_MONTHS = {"1年": 12, "2年": 24, "永久": -1}
_LEGACY_ACCOUNT_KEYS = ("国库", "内库", "民心", "皇威")  # 全局可被 % 修正的四项
_LEGACY_PCT_CAP = 5  # 单条帝国修正对某维度的百分比上限，防幅度过大

# 月固定收支项的合法账户 / 方向白名单（fiscal_creates 枚举守门，集中一处；
# applier 是唯一的枚举守门（cleaner 只做 direction 同义词映射等无损规范化,cmr S3 r2）。
_FISCAL_ACCOUNTS = ("国库", "内库")
_FISCAL_DIRECTIONS = ("income", "expense")
# #1843 reopen：方向同义词归一表从旧 extractor 清洗迁到本唯一使用处。
_DIRECTION_NORMALIZE = {
    "income": "income", "收": "income", "收入": "income", "进账": "income",
    "expense": "expense", "支": "expense", "支出": "expense", "出账": "expense",
}


def _clamp_pct(v: object) -> Optional[int]:
    try:
        pct = int(v)
    except (TypeError, ValueError):
        return None
    if pct == 0:
        return None
    return max(-_LEGACY_PCT_CAP, min(_LEGACY_PCT_CAP, pct))


def _spawn_legacy_from_effect(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    issue_id: int,
    issue_title: str,
    commit: bool = True,
) -> Optional[Dict[str, object]]:
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
    缺字段/非法档/空 effect 一律跳过（不抛断）；地区/军队非法字段或不存在 id 由落账层忽略。
    """
    legacy = effect.get("legacy")
    if not isinstance(legacy, dict):
        return None
    raw_legacy_name = legacy.get("name")
    name = (
        str(raw_legacy_name)
        if raw_legacy_name is not None and str(raw_legacy_name).strip()
        else f"{issue_title}遗留"
    )
    dur_key = str(legacy.get("duration") or "2年").strip()
    duration = _LEGACY_DURATION_MONTHS.get(dur_key)
    if duration is None:
        print(f"[WARN] legacy 时长档非法 '{dur_key}'，按 2年 处理。")
        duration = 24
    raw_eff = legacy.get("modifiers") or {}
    modifiers: Dict[str, object] = {}
    if isinstance(raw_eff, dict):
        for k in _LEGACY_ACCOUNT_KEYS:
            pct = _clamp_pct(raw_eff.get(k))
            if pct is not None:
                modifiers[k] = pct
        for scope, allowed, aliases in (
            ("regions", REGION_SCORE_FIELDS + FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES),
            ("armies", ARMY_SCORE_FIELDS, ARMY_FIELD_ALIASES),
        ):
            block = raw_eff.get(scope)
            if not isinstance(block, dict):
                continue
            scope_out: Dict[str, Dict[str, int]] = {}
            for entity_id, fields in block.items():
                if not isinstance(fields, dict):
                    continue
                fields_out: Dict[str, int] = {}
                for raw_field, v in fields.items():
                    field = aliases.get(str(raw_field).strip(), str(raw_field).strip())
                    if field not in allowed:
                        print(f"[INFO] legacy '{name}' {scope} 字段 '{raw_field}' 非法/不可修正，跳过。")
                        continue
                    pct = _clamp_pct(v)
                    if pct is not None:
                        fields_out[field] = pct
                if fields_out:
                    scope_out[str(entity_id)] = fields_out
            if scope_out:
                modifiers[scope] = scope_out
    if not modifiers:
        print(f"[INFO] legacy '{name}' 无有效 modifiers，跳过。")
        return None
    new_id = db.insert_legacy(
        state,
        name=name,
        modifiers=modifiers,
        narrative_hint=str(legacy.get("narrative_hint") or ""),
        duration_months=duration,
        source_issue_id=issue_id,
        commit=commit,
    )
    summary = {
        "legacy_id": new_id, "name": name,
        "duration_months": duration, "modifiers": modifiers,
    }
    dur_label = "永久" if duration < 0 else f"{duration}月"
    print(f"[帝国修正] 局势#{issue_id}「{issue_title}」落「{name}」({dur_label}) {modifiers}")
    return summary


def _content_population_effect_for_save(
    db: GameDB, effect: Dict[str, object]
) -> Dict[str, object]:
    """#648（ADR 0088/F4）：content 静态人口量已全线「人」，落本档前按存档口径换算。

    新档（人）原样；无标旧档（万人）region_delta.population ÷10⁴（迁移后 content
    人口值均为 10⁴ 整倍数，整除无损）。只换算 region_delta.*.population，其余段浅拷贝透传。
    只用于 content 事件真源（effect_on_trigger / event_to_issue 持久化）；LLM 产 delta
    已按本档口径写，不得经此换算。"""
    region_delta = effect.get("region_delta")
    if not isinstance(region_delta, dict) or not region_delta:
        return effect
    if db.population_unit == POPULATION_UNIT_PERSONS:
        return effect
    scaled: Dict[str, object] = {**effect}
    scaled_region_delta: Dict[str, object] = {}
    for rid, fields in region_delta.items():
        if isinstance(fields, dict) and "population" in fields:
            scaled_fields = {**fields}
            try:
                scaled_fields["population"] = db.scale_content_population_to_save_unit(
                    fields["population"]
                )
            except (TypeError, ValueError):
                pass  # 非整人口值交由下游 apply_region_deltas 既有拒收留痕，不在此静默改写
            scaled_region_delta[rid] = scaled_fields
        else:
            scaled_region_delta[rid] = fields
    scaled["region_delta"] = scaled_region_delta
    return scaled




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
        snapshot = _snapshot_person_write_state(db, content)
        results: List[Dict[str, object]] = []
        db.conn.execute("SAVEPOINT strategic_person_result_preflight")
        try:
            from ming_sim.entities.character.apply import apply_person_changes
            results, results_rejections = apply_person_changes(
                db,
                state,
                person_changes,
                content=content,
                llm_config=llm_config,
            source=Provenance.system_simulation)
        finally:
            db.conn.execute("ROLLBACK TO SAVEPOINT strategic_person_result_preflight")
            db.conn.execute("RELEASE SAVEPOINT strategic_person_result_preflight")
            _restore_person_content_from_snapshot(content, snapshot)
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
    content = db.content
    candidates = {event.id for event in gather_candidate_events(state, db)}
    rejected: dict[str, str] = {}
    pseudo_event = Event(id="season", title="月末整体推演", kind="月末", summary="",
                         urgency=0, severity=0, credibility=100, interests=[], audiences=[])
    for event_id, group in groups.items():
        event = content.event_by_id.get(event_id)
        if event is None or not _is_strategic_foreign_node_event(event):
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


def _restore_person_content_from_snapshot(
    content: Optional[GameContent],
    snapshot: object,
) -> None:
    if content is None:
        return
    try:
        content_rows = snapshot[3]  # shape from _snapshot_person_write_state
    except (IndexError, TypeError):
        return
    _restore_content_character_rows(content, content_rows)



def _snapshot_person_write_state(db: GameDB, content: Optional[GameContent]):
    character_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT name, status, office, office_type, status_reason, "
            "status_changed_turn, reason_code, transit_to, transit_distance_remaining, "
            "transit_speed_factor, transit_start_turn FROM characters"
        ).fetchall()
    ]
    office_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT character_name, office_title, office_type, source, dossier_id, "
            "appointment_tenure, region_id, updated_at FROM character_offices"
        ).fetchall()
    ]
    office_change_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT id, character_name, office_title, office_type, source, dossier_id, "
            "appointment_tenure, created_at FROM office_change_records"
        ).fetchall()
    ]
    # #9：起复路（apply_office_appointment）中途经 set_character_status/set_character_office 会
    # 全重算 factions.leverage；失败回滚必须连 leverage 一并还原，否则 leverage 凭空抬高（违「全有或全无」）。
    # #9 R1 finding#2：leverage 现由 offset+权重派生、二者是一个逻辑态；若包裹流里 offset 被改
    # （adjust_factions 白名单路改 offset）后回滚，须连 leverage_offset 一并还原，否则基线漂移。
    faction_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT name, leverage, leverage_offset FROM factions"
        ).fetchall()
    ]
    content_rows = _snapshot_content_character_rows(content)
    return character_rows, office_rows, faction_rows, content_rows, office_change_rows


def _snapshot_content_character_rows(content: Optional[GameContent]) -> Dict[str, Dict[str, object]]:
    if content is None:
        return {}
    return {
        name: copy.deepcopy(vars(ch))
        for name, ch in content.characters.items()
    }


def _restore_content_character_rows(
    content: Optional[GameContent],
    content_rows: Dict[str, Dict[str, object]],
) -> None:
    if content is None:
        return
    for name in list(content.characters):
        if name not in content_rows:
            del content.characters[name]
    for name, values in content_rows.items():
        ch = content.characters.get(name)
        if ch is None:
            continue
        for key in list(vars(ch)):
            if key not in values:
                delattr(ch, key)
        for key, value in values.items():
            setattr(ch, key, copy.deepcopy(value))


def _restore_person_write_state(
    db: GameDB,
    content: Optional[GameContent],
    snapshot,
    *,
    commit: bool = True,
) -> None:
    character_rows, office_rows, faction_rows, content_rows, office_change_rows = snapshot
    db.conn.execute("DELETE FROM character_offices")
    db.conn.execute("DELETE FROM office_change_records")
    snapshot_names = {str(row["name"]) for row in character_rows}
    for row in db.conn.execute("SELECT name FROM characters").fetchall():
        name = str(row["name"])
        if name not in snapshot_names:
            db.conn.execute("DELETE FROM characters WHERE name=?", (name,))
    db.conn.executemany(
        "UPDATE characters SET status=?, office=?, office_type=?, status_reason=?, "
        "status_changed_turn=?, reason_code=? WHERE name=?",
        [
            (
                row["status"], row["office"], row["office_type"],
                row["status_reason"], row["status_changed_turn"],
                row["reason_code"], row["name"],
            )
            for row in character_rows
        ],
    )
    for row in character_rows:
        db.set_character_transit(
            str(row["name"]),
            transit_to=str(row["transit_to"] or ""),
            distance_remaining=row.get("transit_distance_remaining"),
            speed_factor=row.get("transit_speed_factor"),
            start_turn=int(row.get("transit_start_turn", 0) or 0),
            content=content,
            commit=False,
        )
    db.conn.executemany(
        "INSERT INTO character_offices "
        "(character_name, office_title, office_type, source, dossier_id, "
        "appointment_tenure, region_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["character_name"],
                row["office_title"],
                row["office_type"],
                row["source"],
                row.get("dossier_id"),
                row["appointment_tenure"],
                str(row.get("region_id") or ""),
                row["updated_at"],
            )
            for row in office_rows
        ],
    )
    db.conn.executemany(
        "INSERT INTO office_change_records "
        "(id, character_name, office_title, office_type, source, dossier_id, "
        "appointment_tenure, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["id"], row["character_name"], row["office_title"],
                row["office_type"], row["source"], row.get("dossier_id"),
                row["appointment_tenure"],
                row["created_at"],
            )
            for row in office_change_rows
        ],
    )
    # #9：还原 factions.leverage + leverage_offset（起复路中途的全重算回滚，与 character 状态一并
    # 还原）。R1 finding#2：offset 是基线逻辑态，漏还原则即便 leverage 还原也会被后续 reconcile 用脏
    # offset 重算回去 → 基线漂移。
    db.conn.executemany(
        "UPDATE factions SET leverage=?, leverage_offset=? WHERE name=?",
        [(row["leverage"], row["leverage_offset"], row["name"]) for row in faction_rows],
    )
    if commit:
        db.conn.commit()
    if content is not None:
        _restore_content_character_rows(content, content_rows)


# 校验「二级非 dict 会让 apply 在**逐 entity 写 DB 的中途崩**,留下部分已写 + 回合照推 = 半落库」
# 的字段。这三者 apply 都逐项 UPDATE/INSERT,前面的 entity 先落库、坏的 entity 崩:
#   - region_delta / army_delta:apply 裸调,崩直接抛穿;
#   - power_updates:落库编排器虽裹 try/except,但只接住异常不回滚——前面已写的 power
#     行仍被后续 record_log/save_turn 提交 = 半落库(CMR R2 codex)。prompt 里 power_updates 恒为
#     嵌套 dict,无扁平标量形态,故二级非 dict = 真畸形,校验前置拦截正确。
# **不**列入（交给各自 adapter 按契约处理）:faction_delta 吃旧扁平 int
# {"阉党": -10}（prompt 允许、合法）；class_delta 的扁平 item 不合法，由 adapter 逐项
# `invalid_enum` 拒收（#564），而非 validate 层当 nested-dict shape 拒收。
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


def _apply_levy_driven_transfers(
    db: GameDB,
    *,
    commit: bool = True,
    source: Provenance = Provenance.system_simulation,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """#650/0089 环后半段：结算按账机械驱动农民→流民入池（0087「applier 机械转移」，
    P6 代码只供事实＋clamp）。

    口径（AC2 确定性可断言）：每明省读 settle._meta「加派基线」(万两/月)，
    入池(人) = 基线 × LEVY_DISPLACEMENT_RATE(人/万两·月) × (100−民心)/100。
    本机制只在 substrate_hub 新财政档启用；legacy 档不接受也不消费加派账。
    结果钳到农民@省余额后再交 _apply_population_transfers 守恒原语落账
    （reason=加派；累积账月效统一使用 `盘面自发`，不伪归最后一道改账旨）。基线 ≤0 或折算后
    ≤0 的省零入池——停加派/蠲免后入池止（AC5；出口回流归 S5 #652）。
    """
    from ming_sim.entities.population.apply import _apply_population_transfers
    if (not db.is_substrate_hub_fiscal_engine_enabled()
            or db.population_unit != POPULATION_UNIT_PERSONS):
        return [], []
    records: List[Dict[str, object]] = []
    rows = db.conn.execute(
        "SELECT id, fiscal, public_support FROM regions WHERE controlled_by='ming' ORDER BY id"
    ).fetchall()
    for row in rows:
        region_id = str(row["id"])
        try:
            fiscal = json.loads(str(row["fiscal"] or "{}"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{region_id}.fiscal 持久 JSON 损坏，无法结算加派账") from exc
        if not isinstance(fiscal, dict):
            raise ValueError(f"{region_id}.fiscal 必须是 object，无法结算加派账")
        settle = fiscal.get("settle")
        # 财政月效的动态成员只包括已有 settle 基座的明省；legacy/内容扩展中
        # 合法的无基座省自然出列，不能让任意 delta apply 因此失败。
        if settle is None:
            continue
        if not isinstance(settle, dict):
            raise ValueError(f"{region_id}.fiscal.settle 必须是 object，无法结算加派账")
        meta = settle.get("_meta")
        if meta is not None and not isinstance(meta, dict):
            raise ValueError(f"{region_id}.fiscal.settle._meta 必须是 object，无法结算加派账")
        raw = meta.get(_SETTLE_META_JIAPIAI_KEY, 0) if meta is not None else 0
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ValueError(f"{region_id}.settle._meta.{_SETTLE_META_JIAPIAI_KEY} 必须是有限数值")
        base = max(0.0, float(raw))
        if base <= 0:
            continue
        from ming_sim.entities.surcharge.apply import _surcharge_population_pool_members
        pool_members = _surcharge_population_pool_members(db, region_id)
        if pool_members == {"农民", "流民"}:
            pass  # 完整加派人口池
        elif "农民" not in pool_members:
            # 无农民源：空池或 #659 边镇仅军户/流民切片——无加派人口效应，不 soft-lock。
            continue
        else:
            # 有农民无流民＝农业省池残缺，fail-loud（#650 missing_pool）
            raise ValueError(f"{region_id} 有正加派账但仅有部分农民/流民省级人口行")
        support = max(0, min(100, int(row["public_support"] or 0)))
        raw_persons = base * LEVY_DISPLACEMENT_RATE * (100 - support) / 100.0
        amount = int(round(raw_persons))
        if amount <= 0:
            continue
        balance = int(db.conn.execute(
            "SELECT population FROM classes WHERE name='农民' AND region_id=?", (region_id,)
        ).fetchone()["population"])
        amount = min(amount, balance)  # clamp：原语超余额即拒，先钳免噪音
        if amount <= 0:
            continue
        records.append({
            "source": f"农民@{region_id}",
            "target": f"流民@{region_id}",
            "amount": amount,
            "reason": "加派",
            # 月度后果来自累积账，不伪归因给最后一道改变账额的旨。
            "origin_ref": "盘面自发",
        })
    if not records:
        return [], []
    applied, rejected = _apply_population_transfers(db, records, source=source)
    if commit:
        db.conn.commit()
    return applied, rejected



def _is_bandit_power_id(power_id: str) -> bool:
    """流寇总股与分股（bandits / bandit_*）；投贼吸收与正实力门控共用。"""
    pid = str(power_id or "").strip()
    return pid == "bandits" or pid.startswith("bandit_")


def _apply_bandit_absorptions(
    db: GameDB,
    state: GameState,
    absorptions: object,
    *,
    commit: bool = True,
    source: Provenance = Provenance.system_simulation,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    """#652/0087：流民投贼吸收原子 applier。

    LLM 只产 typed 请求；本核：actual=min(requested, 省池)→扣流民池（无农民对端，
    0087 兵源出口单侧出池）→仅 actual>0 允许实力正增（δ=actual//换算率，0–100 clamp
    走 apply_power_deltas）。超池/非法 id/零池正请求 → 逐项拒收留痕。
    返回 (applied_absorptions, rejections, power_changes)。
    """
    should_commit = bool(commit) and db.owns_transaction()
    applied: List[Dict[str, object]] = []
    rejected: List[Dict[str, object]] = []
    power_changes: List[Dict[str, object]] = []
    items = absorptions if isinstance(absorptions, list) else []
    # 仅 substrate 人口径新档开环；legacy 不误开（对齐 #649/#650）。
    if db.population_unit != POPULATION_UNIT_PERSONS:
        for item in items:
            rejected.append(RejectedItem(item=item if isinstance(item, dict) else {"raw_value": item}, reason="bandit_absorptions 仅适用于 population_unit='人' 的人口池档", category="invalid_enum", source=source))
        return applied, rejected, power_changes

    for item in items:
        if not isinstance(item, dict):
            rejected.append(RejectedItem(item={"raw_value": item}, reason="bandit_absorptions 项必须是 object(dict)", category="invalid_shape", source=source))
            continue

        def _reject(category: str, reason: str) -> None:
            rejected.append(RejectedItem(item=item, reason=reason, category=category, source=source))

        extra = sorted(set(item) - BANDIT_ABSORPTION_FIELDS)
        if extra:
            _reject(
                "invalid_enum",
                f"bandit_absorptions 白名单外字段 {extra}"
                f"（合法字段：region_id/power_id/requested_count/origin_ref）",
            )
            continue

        region_id = str(item.get("region_id") or "").strip()
        power_id = str(item.get("power_id") or "").strip()
        origin_ref = str(item.get("origin_ref") or "").strip()
        if not region_id:
            _reject("missing_ref", "bandit_absorptions 缺 region_id")
            continue
        region_row = db.conn.execute(
            "SELECT controlled_by FROM regions WHERE id=?", (region_id,)
        ).fetchone()
        if region_row is None:
            _reject("missing_ref", f"bandit_absorptions 未知 region_id：{region_id!r}")
            continue
        if str(region_row["controlled_by"] or "") != "ming":
            _reject("missing_ref", f"bandit_absorptions 非明省不可吸收：{region_id!r}")
            continue
        if not power_id or not _is_bandit_power_id(power_id):
            _reject(
                "invalid_enum",
                f"bandit_absorptions power_id 须为流寇股（bandits/bandit_*）：{power_id!r}",
            )
            continue
        power_row = db.conn.execute(
            "SELECT id FROM powers WHERE id=?", (power_id,)
        ).fetchone()
        if power_row is None:
            _reject("hallucinated_id", f"bandit_absorptions 引用未入库势力 '{power_id}'")
            continue
        raw_req = item.get("requested_count")
        try:
            requested = _strict_int(raw_req, accept_numeric_strings=False)
        except (TypeError, ValueError):
            _reject("invalid_enum", f"bandit_absorptions requested_count 非整数：{raw_req!r}")
            continue
        if requested <= 0:
            _reject("invalid_enum", f"bandit_absorptions requested_count 须为正整数：{requested!r}")
            continue
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejected.append(RejectedItem(item=item, reason=f"bandit_absorptions {origin_error['reason']}", category=origin_error["category"], source=source))
            continue
        pool_row = db.conn.execute(
            "SELECT population FROM classes WHERE name='流民' AND region_id=?",
            (region_id,),
        ).fetchone()
        if pool_row is None:
            _reject(
                "missing_ref",
                f"bandit_absorptions 查无流民省级行「流民@{region_id}」",
            )
            continue
        pool = int(pool_row["population"])
        actual = min(int(requested), pool)
        if actual <= 0:
            _reject(
                "invalid_enum",
                f"bandit_absorptions 省池为空，禁止正增贼势：流民@{region_id}=0",
            )
            continue
        # 单侧出池（0087 兵源出口无农民对端）+ 实力正增同事务。
        db.conn.execute(
            "UPDATE classes SET population = population - ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE name='流民' AND region_id=?",
            (actual, region_id),
        )
        strength_delta = actual // int(BANDIT_ABSORPTION_PERSONS_PER_STRENGTH)
        applied_item: Dict[str, object] = {
            "region_id": region_id,
            "power_id": power_id,
            "requested_count": requested,
            "actual_count": actual,
            "strength_delta": strength_delta,
            "origin_ref": origin_ref,
            "population_unit": db.population_unit,
        }
        if strength_delta > 0:
            landed, refused = db.apply_power_deltas(
                state,
                {power_id: {
                    "military_strength": strength_delta,
                    "reason": "流民投贼",
                    "origin_ref": origin_ref,
                }},
                commit=False,
                origin_ref=origin_ref,
                require_origin=True,
            source=source)
            power_changes.extend(landed)
            rejected.extend(refused)
        applied.append(applied_item)
    if should_commit:
        db.conn.commit()
    return applied, rejected, power_changes


def _recovery_effective_silver_wan(db: GameDB, dossier_id: int, turn: int) -> int:
    """回流成本面唯一读缝：只认实付证据。

    本回合对账实抵优先；否则累加该案已落 economy_moves 负向出账。
    **不**回退 payload.amount（ordered 非实付，零 ledger 不得假阳性出回流）。
    """
    history = db.list_dossier_reconciliations(int(dossier_id))
    arrived_this_turn = [
        int(row["arrived_amount"])
        for row in history
        if int(row.get("turn") or 0) == int(turn)
    ]
    if arrived_this_turn:
        return max(0, sum(arrived_this_turn))
    paid = 0
    for move in db.list_economy_moves_for_dossier(int(dossier_id)):
        try:
            delta = int(move.get("delta") or 0)
        except (TypeError, ValueError):
            continue
        if delta < 0:
            paid += -delta
    return max(0, paid)


def _apply_recovery_driven_transfers(
    db: GameDB,
    state: GameState,
    *,
    commit: bool = True,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """#652/0087：赈济/招抚屯田回流单核（确定性；LLM 零产回流）。

    触发：带 recovery 身份的 grant_allocation（赈灾/招抚屯田）+ 属地 region +
    本回合已付代价 + 已落结构化执行判决。基线=实抵万两×RECOVERY_PERSONS_PER_WAN，
    再经执行 outcome 成色折减；经 _apply_population_transfers reason=回流 唯一落库。
    幂等键 (dossier_id, turn)：同键不双扣池。立即开仓/#522 pacification 不在此列。
    """
    from ming_sim.entities.population.apply import _apply_population_transfers
    if db.population_unit != POPULATION_UNIT_PERSONS:
        return [], []
    turn = int(state.turn)
    # 月份推进事务只执行一次；同一案在本次扫描内仅回流一次。
    seen_keys: set[tuple[int, int]] = set()

    records: List[Dict[str, object]] = []
    remaining_by_region: Dict[str, int] = {}
    rows = db.conn.execute(
        """
        SELECT id, status, target_kind, target_id, payload_json,
               execution_outcome, closed_turn
        FROM decree_dossiers
        WHERE action_type='grant_allocation'
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        dossier_id = int(row["id"])
        if (dossier_id, turn) in seen_keys:
            continue
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        grant_action = str(payload.get("grant_action") or "").strip()
        if grant_action not in RECOVERY_GRANT_ACTIONS:
            continue
        target_kind = str(row["target_kind"] or payload.get("target_kind") or "").strip()
        region_id = str(row["target_id"] or payload.get("target_id") or "").strip()
        if target_kind != "region" or not region_id:
            continue
        if db.conn.execute("SELECT 1 FROM regions WHERE id=?", (region_id,)).fetchone() is None:
            continue
        outcome = str(row["execution_outcome"] or "").strip()
        if outcome not in RECOVERY_OUTCOME_FACTORS:
            continue
        cadence = str(payload.get("cadence") or "").strip()
        closed_turn = int(row["closed_turn"] or 0)
        if cadence != "每月" and closed_turn != turn:
            continue
        factor = float(RECOVERY_OUTCOME_FACTORS[outcome])
        if factor <= 0:
            seen_keys.add((dossier_id, turn))
            continue
        if cadence == "每月":
            reconciled = [
                int(item["arrived_amount"])
                for item in db.list_dossier_reconciliations(dossier_id)
                if int(item.get("turn") or 0) == turn
            ]
            if reconciled:
                silver = max(0, sum(reconciled))
            else:
                paid_row = db.conn.execute(
                    "SELECT COALESCE(SUM(-delta), 0) FROM economy_ledger "
                    "WHERE origin_ref=? AND turn=? AND delta<0",
                    (f"dossier:{dossier_id}", turn),
                ).fetchone()
                silver = max(0, int(paid_row[0] or 0))
        else:
            silver = _recovery_effective_silver_wan(db, dossier_id, turn)
        if silver <= 0:
            continue
        raw_persons = silver * RECOVERY_PERSONS_PER_WAN * factor
        amount = int(round(raw_persons))
        if amount <= 0:
            continue
        pool_row = db.conn.execute(
            "SELECT population FROM classes WHERE name='流民' AND region_id=?",
            (region_id,),
        ).fetchone()
        farmer_row = db.conn.execute(
            "SELECT 1 FROM classes WHERE name='农民' AND region_id=?",
            (region_id,),
        ).fetchone()
        if pool_row is None or farmer_row is None:
            continue
        remaining = remaining_by_region.setdefault(region_id, int(pool_row["population"]))
        amount = min(amount, remaining)
        if amount <= 0:
            continue
        records.append({
            "source": f"流民@{region_id}",
            "target": f"农民@{region_id}",
            "amount": amount,
            "reason": "回流",
            "origin_ref": f"dossier:{dossier_id}",
        })
        remaining_by_region[region_id] = remaining - amount
        seen_keys.add((dossier_id, turn))
    if not records:
        return [], []
    applied, rejected = _apply_population_transfers(db, records, source=Provenance.system_simulation)
    if commit:
        db.conn.commit()
    return applied, rejected


_COVERT_NEUTRALIZATION_REASON = "禁摊派：一次性撤销旧案暗渠财政效果"


def neutralize_covert_fiscal_effects(
    db: Any, state: Any, *, exposed_dossier_id: int, prohibition_dossier_id: int,
) -> int:
    """Undo one old case's beyond-intent fiscal contribution, once per live incarnation."""
    old_origin = f"dossier:{int(exposed_dossier_id)}"
    receipt_origin = f"dossier:{int(prohibition_dossier_id)}"
    rows = db.list_fiscal_effects_for_dossier(int(exposed_dossier_id))
    raw_keys = {str(row.get("key") or "").strip() for row in rows if row.get("beyond_intent")}
    keys: set[str] = set()
    for raw_key in raw_keys:
        stem = db._stem_of(raw_key)
        if not stem:
            continue
        if raw_key.endswith(("_base", "_rate")):
            keys.add(raw_key)
        else:
            keys.add(f"{stem}_base")

    written = 0
    for key in sorted(keys):
        stem = db._stem_of(key)
        base_key, rate_key = f"{stem}_base", f"{stem}_rate"
        receipt = db.conn.execute(
            """SELECT 1 FROM fiscal_config_changes
               WHERE origin_ref=? AND key=? AND reason=? LIMIT 1""",
            (receipt_origin, key, _COVERT_NEUTRALIZATION_REASON),
        ).fetchone()
        if receipt is None:
            receipt = db.conn.execute(
                """SELECT 1 FROM fiscal_config_tombstones
                   WHERE origin_ref=? AND key IN (?, ?) AND reason=? LIMIT 1""",
                (receipt_origin, base_key, rate_key, _COVERT_NEUTRALIZATION_REASON),
            ).fetchone()
        if receipt is not None:
            continue

        current = db.get_fiscal_config().get(key)
        if current is None:
            continue
        latest_remove = db.conn.execute(
            "SELECT removed_turn turn,id FROM fiscal_config_tombstones WHERE key=? ORDER BY removed_turn DESC,id DESC LIMIT 1",
            (key,),
        ).fetchone()
        latest_create = db.conn.execute(
            "SELECT turn,id,origin_ref,beyond_intent FROM fiscal_config_creations WHERE key=? ORDER BY turn DESC,id DESC LIMIT 1",
            (key,),
        ).fetchone()
        remove_mark = (int(latest_remove["turn"]), 0, int(latest_remove["id"])) if latest_remove else (-1, -1, -1)
        create_mark = (int(latest_create["turn"]), 1, int(latest_create["id"])) if latest_create else (-1, -1, -1)
        start = max(remove_mark, create_mark)

        if (
            latest_create is not None and create_mark > remove_mark
            and str(latest_create["origin_ref"]) == old_origin
            and bool(db.coerce_beyond_intent_flag(latest_create["beyond_intent"]))
        ):
            if key != base_key:
                continue
            if db.remove_fiscal_item(
                key, commit=False, origin_ref=receipt_origin,
                reason=_COVERT_NEUTRALIZATION_REASON, turn=int(state.turn),
            ) is not None:
                written += 1
            continue

        contribution = 0
        for row in db.conn.execute(
            """SELECT id,turn,delta,beyond_intent FROM fiscal_config_changes
               WHERE key=? AND origin_ref=? ORDER BY turn,id""",
            (key, old_origin),
        ).fetchall():
            mark = (int(row["turn"]), 2, int(row["id"]))
            if mark > start and bool(db.coerce_beyond_intent_flag(row["beyond_intent"])):
                contribution += int(row["delta"])
        floor = db.fiscal_config_minimum_value(key) or 0
        new_value = max(int(floor), int(current) - max(0, contribution))
        from ming_sim.entities.fiscal.config_writer import _write_fiscal_config_change
        _write_fiscal_config_change(
            db, turn=int(state.turn), key=key, old_value=int(current), new_value=new_value,
            origin_ref=receipt_origin, reason=_COVERT_NEUTRALIZATION_REASON,
        )
        written += 1
    return written


def apply_person_changes_only(
    db: GameDB,
    state: GameState,
    person_changes: List[Dict[str, object]],
    *,
    content=None,
    llm_config: Any = None,
    origin_ref: str = "盘面自发",
    require_origin: bool = False,
    source: Provenance = Provenance.system_simulation,
) -> Dict[str, object]:
    """Person-only canonical adapter：只走人物变更核，不经 full settlement recovery。

    任命授官、传召启程等单人物动作共用此口；禁止借落库编排器附带
    #652 recovery / bandit 等结算核。返回形状与 full applier 的 applied_person_changes 对齐。
    """
    runtime_content = content if content is not None else _ctx()
    caller_transaction = db.conn.in_transaction
    # 本入口是人物单笔的事务主人：外层已开事务时只登记回滚快照；
    # 否则快照 + atomic，成功提交、失败整笔回滚（含候见离京四侧）。
    _register_runtime_rollback_snapshot(db, state, runtime_content)
    changes = character_names._canonicalize_person_change_names(
        normalize_person_changes({"人物变更": list(person_changes or [])}),
        runtime_content,
        db,
    )
    from ming_sim.entities.character.apply import apply_person_changes

    def _write() -> List[Dict[str, object]]:
        return apply_person_changes(
            db,
            state,
            changes,
            content=runtime_content,
            llm_config=llm_config,
            origin_ref=origin_ref,
            require_origin=require_origin,
        source=source)

    if caller_transaction:
        results, results_rejections = _write()
    else:
        from ming_sim.applier import atomic

        with atomic(db):
            results, results_rejections = _write()
    return {"applied_person_changes": results, "rejected": results_rejections}


def record_secret_order_disclosure(
    db: Any,
    state: Any,
    order_id: int,
    sim_note: str,
    *,
    commit: bool = True,
) -> bool:
    """Record public knowledge event for secret order disclosure if not already disclosed (#883, ADR 0157).

    Returns True if a new public knowledge event was recorded, False otherwise.
    """
    order = db.get_secret_order(order_id)
    if order is None:
        return False
    # Disclosure is the only promotion from the assignee-only
    # brief into a public knowledge event (#883).
    # Cross-turn dedupe: disclosed is a state (prompt) not a monthly
    # event — re-true each month must not mint another public row.
    disclosure_prefix = f"secret_order_disclosure:{order_id}:"
    # LIKE treats `_`/`%` as wildcards; escape the literal prefix
    # (same ESCAPE idiom as db.py iter_budget_items / get_fiscal_config).
    like_prefix = (
        disclosure_prefix
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    already_disclosed = db.conn.execute(
        "SELECT 1 FROM character_knowledge_events "
        "WHERE character_name='' AND source_id LIKE ? ESCAPE '\\' LIMIT 1",
        (f"{like_prefix}%",),
    ).fetchone()
    if already_disclosed is not None:
        return False
    dossier = db.get_dossier_for_secret_order(order_id)
    progress = (
        db.list_dossier_progress(int(dossier["id"]))
        if dossier is not None else []
    )
    progress_text = format_public_progress_disclosure(progress)
    public_body = sim_note
    if progress_text:
        public_body = f"{sim_note}\n{progress_text}"
    db.record_public_knowledge_event(
        state, str(order["title"]), public_body,
        source_id=f"{disclosure_prefix}{state.turn}",
        commit=commit,
    )
    return True



def apply_issue_inertia_and_ongoing(
    db: GameDB,
    state: GameState,
    touched_ids: Optional[set] = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
    source: Provenance = Provenance.system_simulation,
) -> List[Dict[str, object]]:
    """返回 inertia 自然结案路产生的容忍拒收项——settle 在 inertia 之后补收进
    收集器(桥接跑在 inertia 前,只 tlog 等于这条路脱离 rejection_reports 管线,
    与 tracker-close 路同输入两判;ship-pre r1)。"""
    # inertia 是每月自然漂移基础量，对所有进行中 issue 都生效（含本月被 advance 触动的）。
    # advance 的 delta_bar 是皇帝本月实旨推动的额外量，与 inertia 叠加，互不顶替。
    from ming_sim.entities.economy.apply import _apply_economy_list
    from ming_sim.entities.faction.apply import _apply_faction_dict
    _ = touched_ids  # 保留入参不破坏调用方；inertia 漂移不再按它跳过
    inertia_rejections: List[Dict[str, object]] = []
    active = db.list_active_issues()
    commit_local = not bool(getattr(db.conn, "in_transaction", False))
    # 累计单月 metric 落账，用于上限 clamp
    period_metric_acc: Dict[str, int] = {}

    for row in active:
        issue_id = int(row["id"])
        bar = int(row["bar_value"])
        inertia = int(row["inertia"])
        commitment_kind = str(row["commitment_kind"] if "commitment_kind" in row.keys() else "").strip()
        commitment_stop_gate = _commitment_stop_gate(row)
        is_commitment = bool(commitment_kind or commitment_stop_gate)
        parent_origin_ref: Optional[str] = None

        # 1) inertia 漂移：每月对所有进行中 issue 都走一格
        if inertia != 0 and not is_commitment:
            if parent_origin_ref is None:
                parent_origin_ref = _canonical_issue_origin(db, row)
            new_bar = max(0, min(100, bar + inertia))
            actual = new_bar - bar
            if actual != 0:
                new_row = db.advance_issue(
                    state, issue_id,
                    trigger_kind="inertia",
                    delta_bar=actual,
                    stage_text=row["stage_text"],
                    narrative="局势自有其势，本月按其本然推移。",
                    metric_delta={},
                )
                if new_row is None:
                    continue
                if new_row["status"] == "resolved":
                    effect = loads_effect_dict(new_row["effect_on_resolve"])
                    issue_effects._emit_pairing_warnings(new_row, effect)  # inertia 路只 tlog（#45/#46）
                    _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
                    inertia_rejections.extend(_apply_economy_list(db, state, effect.get("economy") or [], origin_ref=parent_origin_ref, source=source)[1])
                    inertia_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}, source=source)[1])
                    _b_ops, _b_rej = issue_effects._apply_issue_buildings(
                        db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT,
                        f"局势#{issue_id}结案", origin_ref=parent_origin_ref,
                        source=source,
                    )
                    inertia_rejections.extend(_b_rej)
                    # 与 tracker advance/close 路径一致：自然结案也落实体后果 + 帝国修正，
                    # 否则靠 inertia 推到 100 的 issue 会丢 new_armies/army_delta/人物状态/legacy（codexB-P1）。
                    for _tr in issue_effects._apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}结案",
                        applied_person_changes=applied_person_changes,
                        origin_ref=parent_origin_ref,
                    source=source):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.reason}")
                        inertia_rejections.append(_tr)
                    _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
                    if commit_local:
                        db.conn.commit()
                    continue
                elif new_row["status"] == "failed":
                    effect = loads_effect_dict(new_row["effect_on_fail"])
                    _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
                    inertia_rejections.extend(_apply_economy_list(db, state, effect.get("economy") or [], origin_ref=parent_origin_ref, source=source)[1])
                    inertia_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}, source=source)[1])
                    _b_ops, _b_rej = issue_effects._apply_issue_buildings(
                        db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT,
                        f"局势#{issue_id}失败", origin_ref=parent_origin_ref,
                        source=source,
                    )
                    inertia_rejections.extend(_b_rej)
                    for _tr in issue_effects._apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}失败",
                        applied_person_changes=applied_person_changes,
                        origin_ref=parent_origin_ref,
                    source=source):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.reason}")
                        inertia_rejections.append(_tr)
                    _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
                    if commit_local:
                        db.conn.commit()
                    continue
                row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
                if row is None:
                    continue
                bar = int(row["bar_value"])

        ongoing = loads_effect_dict(row["ongoing_effects"])
        ongoing_has_work = _monthly_ongoing_effects_has_work(ongoing)
        if is_commitment:
            stop_gate = _commitment_stop_gate(row)
            if stop_gate and _gate_passed(stop_gate, state.metrics, db):
                _resolve_commitment_issue(db, state, row, commit=commit_local)
                continue
            end_turn = int(row["end_turn"] or 0)
            if ongoing_has_work and end_turn > 0 and end_turn <= state.turn:
                # 段派生展示 end_turn 不得驱动机械停账；独立 end_turn 仍 expire。
                from ming_sim.staged_commitment import is_stage_derived_end_turn
                if not is_stage_derived_end_turn(row["stages_json"], end_turn):
                    _expire_commitment_issue(db, state, row, commit=commit_local)
                    continue

        # 2) ongoing_effects：bar 高时折扣。经 loads_effect_dict 统一守（非 dict→{}，#117）。
        if is_commitment and ongoing_has_work:
            ongoing = _commitment_ongoing_effects_for_settlement(row, ongoing)
        metric_part: Dict[str, int] = {}
        economy_part: List[Dict[str, object]] = []
        applied_monthly_parts: Dict[str, object] = {}
        if _monthly_ongoing_effects_has_work(ongoing):
            if parent_origin_ref is None:
                parent_origin_ref = _canonical_issue_origin(db, row)
            # 折扣系数：bar 越高（越好）越少扣
            # bar=0~40 → 100%, bar=40~80 → 60%, bar=80~100 → 30%
            if bar >= 80:
                scale = 0.3
            elif bar >= 40:
                scale = 0.6
            else:
                scale = 1.0

            # metrics. Commitment issues represent a concrete monthly promise;
            # do not let the ordinary issue health discount erase it into a no-op.
            metric_scale = 1.0 if is_commitment else scale
            _om = ongoing.get("metrics")  # #117 同类：stored ongoing 的 metrics 真值非 dict 守卫
            for k, v in (_om if isinstance(_om, dict) else {}).items():
                if k not in ISSUE_METRIC_KEYS:
                    continue
                try:
                    raw = int(v)
                except (TypeError, ValueError):
                    continue
                scaled = int(round(raw * metric_scale))
                if scaled == 0:
                    continue
                cap = ISSUE_METRIC_LOCK_CAPS.get(k, 5)
                already = period_metric_acc.get(k, 0)
                remaining = cap - abs(already)
                if remaining <= 0:
                    continue
                if scaled > 0:
                    allowed = min(scaled, remaining)
                else:
                    allowed = max(scaled, -remaining)
                if allowed == 0:
                    continue
                state.metrics[k] = int(state.metrics.get(k, 0)) + allowed
                period_metric_acc[k] = already + allowed
                metric_part[k] = allowed

            # economy
            issue_monthly_rejections: List[Dict[str, object]] = []
            pay_arrears_pool_army_ids = (
                _commitment_arrears_gate_army_ids(row)
                if is_commitment and _commitment_gate_references_arrears(row)
                else None
            )
            allow_pay_arrears_pool = (
                is_commitment
                and (
                    not commitment_stop_gate
                    or bool(pay_arrears_pool_army_ids)
                )
            )
            _eco_out, _eco_out_rejections = _apply_economy_list(
                db,
                state,
                _monthly_economy_items(ongoing),
                allow_pay_arrears_pool=allow_pay_arrears_pool,
                pay_arrears_pool_army_ids=pay_arrears_pool_army_ids,
                origin_ref=parent_origin_ref,
            source=source)
            economy_rejections = _eco_out_rejections
            issue_monthly_rejections.extend(economy_rejections)
            inertia_rejections.extend(economy_rejections)  # economy 拒收不蒸发（#14）
            economy_part = _eco_out

            applied_monthly_parts, monthly_rejections = _apply_monthly_ongoing_entities(
                db,
                state,
                ongoing,
                f"局势#{issue_id}持续效果",
                applied_person_changes=applied_person_changes,
                origin_ref=parent_origin_ref,
            source=source)
            issue_monthly_rejections.extend(monthly_rejections)
            inertia_rejections.extend(monthly_rejections)
        else:
            issue_monthly_rejections = []

        paid_this_month = sum(
            abs(int(r.get("delta") or 0))
            for r in economy_part
            if int(r.get("delta") or 0) < 0
        )
        record_commitment_attempt = (
            is_commitment
            and ongoing_has_work
            and not (metric_part or economy_part or applied_monthly_parts)
            and not issue_monthly_rejections
        )
        commitment_progress = (
            commitment_display.commitment_progress_payload(
                db,
                state,
                row,
                paid_this_month=paid_this_month,
                include_current_month=bool(metric_part or economy_part or applied_monthly_parts or record_commitment_attempt),
            )
            if is_commitment
            else None
        )
        commitment_bar = commitment_display._commitment_bar_value(commitment_progress) if commitment_progress else None

        if metric_part or economy_part or applied_monthly_parts or record_commitment_attempt:
            from_bar = bar
            to_bar = commitment_bar if commitment_bar is not None else bar
            actual_bar = int(to_bar) - int(from_bar)
            if commitment_bar is not None and actual_bar != 0:
                db.conn.execute(
                    "UPDATE issues SET bar_value=?, phase=?, last_advance_turn=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (int(commitment_bar), db._derive_issue_phase(int(commitment_bar)), state.turn, issue_id),
                )
                bar = int(commitment_bar)
            metric_delta: Dict[str, object] = {"metrics": metric_part, "economy": economy_part}
            metric_delta.update(applied_monthly_parts)
            if commitment_progress is not None:
                metric_delta["commitment_progress"] = commitment_progress
            narrative = (
                "承诺持续效果本月核销；未产生额外数值变动。"
                if record_commitment_attempt
                else (
                    "承诺持续效果落账"
                    if is_commitment
                    else f"持续效果落账 (折扣 {int(scale*100)}%)"
                )
            )
            db.conn.execute(
                """
                    INSERT INTO issue_advances (
                        issue_id, turn, trigger_kind, delta_bar,
                        from_value, to_value, narrative, metric_delta
                    ) VALUES (?, ?, 'ongoing', ?, ?, ?, ?, ?)
                """,
                (
                    issue_id, state.turn, actual_bar, from_bar, int(to_bar),
                    narrative,
                    json.dumps(metric_delta, ensure_ascii=False),
                ),
            )
            if commit_local:
                db.conn.commit()

        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if row is None or row["status"] != "active":
            continue
        stop_gate = _commitment_stop_gate(row) if is_commitment else {}
        if stop_gate and _gate_passed(stop_gate, state.metrics, db):
            _resolve_commitment_issue(db, state, row, commit=commit_local)
            continue

    state.clamp()
    return inertia_rejections


# ── 开局负面帝国修正：不立 issue、不进推演，靠 clear_gate 程序判定消除 ──────────────

def clear_gated_legacies(db: GameDB, state: GameState) -> List[str]:
    """每月调一次：取所有 active 且带 clear_gate 的 legacy，gate 达标即置 'cleared'。
    返回被消除的 legacy 名称列表（供叙事/提示用，不强制使用）。"""
    rows = db.conn.execute(
        "SELECT id, name, clear_gate, narrative_hint FROM legacies "
        "WHERE status='active' AND clear_gate != '' AND clear_gate != '{}'"
    ).fetchall()
    cleared: List[str] = []
    for row in rows:
        try:
            gate = json.loads(str(row["clear_gate"] or "{}"))
        except (ValueError, TypeError):
            gate = {}
        if not gate:
            continue
        if _gate_passed(gate, state.metrics, db):
            db.conn.execute("UPDATE legacies SET status='cleared' WHERE id=?", (int(row["id"]),))
            cleared.append(str(row["name"]))
    if cleared:
        db.conn.commit()
        db._legacy_mod_cache = None  # active 集变了，修正符缓存失效
    return cleared


def sync_opening_legacies(db: GameDB, state: GameState) -> None:
    """开局负面帝国修正落库/校准。新档与读档都调（在 session.__init__ load_state 之后）：
    - 已达 clear_gate：不补；若残留 active 则置 cleared。
    - 未达标：该 legacy_key 不存在 active 行则 insert（永久 duration=-1，仅靠 gate 消除）。
    一个函数覆盖新档（全补）/旧档（补缺）/达标档（不补/清残）。"""
    for leg in _ctx().opening_legacies:
        passed = _gate_passed(leg.clear_gate, state.metrics, db)
        existing = db.conn.execute(
            "SELECT id FROM legacies WHERE legacy_key=? AND status='active'",
            (leg.key,),
        ).fetchone()
        if existing is not None:
            db.conn.execute(
                """UPDATE legacies
                   SET name=?, modifiers=?, narrative_hint=?, clear_gate=?
                   WHERE legacy_key=? AND status='active'""",
                (
                    leg.name,
                    json.dumps(leg.modifiers, ensure_ascii=False),
                    leg.narrative_hint,
                    json.dumps(leg.clear_gate, ensure_ascii=False),
                    leg.key,
                ),
            )
            db.conn.commit()
            db._legacy_mod_cache = None
        if passed:
            if existing is not None:
                db.conn.execute(
                    "UPDATE legacies SET status='cleared' WHERE legacy_key=? AND status='active'",
                    (leg.key,),
                )
                db.conn.commit()
                db._legacy_mod_cache = None
            continue
        # 未达标且无 active 行 → 补上
        if existing is None:
            db.insert_legacy(
                state,
                name=leg.name,
                modifiers=leg.modifiers,
                narrative_hint=leg.narrative_hint,
                duration_months=-1,
                clear_gate=leg.clear_gate,
                legacy_key=leg.key,
            )
