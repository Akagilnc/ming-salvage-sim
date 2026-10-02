"""Issue 系统：候选事件、issue 立项/推进/结案、tracker 输出落地、inertia 漂移。L6。

通过 bind_content() 注入 GameContent（取 EVENTS/SEED_EVENTS/EVENT_BY_ID）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

import json
import math
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from ming_sim.applier import RejectionCollector, atomic, mirror_rejections_after_commit
from ming_sim.error_pack import rejections_jsonl_path
from ming_sim.constants import (
    _SETTLE_META_JIAPIAI_KEY, TURN_UNIT, REGION_SCORE_FIELDS, REGION_QUANTITY_FIELDS, REGION_TEXT_FIELDS,
    ARMY_SCORE_FIELDS, ARMY_QUANTITY_FIELDS, ARMY_TEXT_FIELDS, BUILDING_SCORE_FIELDS,
    BUILDING_QUANTITY_FIELDS, POWER_SCORE_FIELDS, POWER_TEXT_FIELDS,
    CHARACTER_TEXT_FIELDS, GATE_TABLES, LEVY_DISPLACEMENT_RATE,
)
from ming_sim.content import GameContent
from ming_sim.db import (
    GameDB,
    POPULATION_UNIT_PERSONS,
    _LEVERAGE_FACTIONS,
)
from ming_sim.decree_vocabulary import (
    format_public_progress_disclosure,
)
from ming_sim.exceptions import SettlementAbort
from ming_sim.entities.metric.apply import (
    ISSUE_METRIC_KEYS,
)
from ming_sim.flows import (
    ISSUE_METRIC_LOCK_CAPS,
    _strict_int,
)
from ming_sim.models import Event, GameState, effect_dict_has_work, loads_effect_dict
from ming_sim.participant_roster import project_execution_liability_parties
from ming_sim.entities.character.normalize import normalize_person_changes
from ming_sim.token_stats import tlog

from ming_sim.settlement.preflight import _validate_strategic_foreign_node_outcome_targets

import ming_sim.entities.issue.commitment_display as commitment_display
import ming_sim.entities.issue.effects as issue_effects

_content: Optional[GameContent] = None

COMMITMENT_KIND_UNTIL_STOP = "until_stop"
_FISCAL_LEVY_TARGET_ABS_TOL = 1e-9

# SQLite 有符号 64-bit 整数边界：超界 int 绑进 SQLite 会抛 OverflowError。







def _issue_condition_text(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    return str(raw)


def _normalize_commitment_kind(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if value in {COMMITMENT_KIND_UNTIL_STOP, "until_condition", "recurring_until", "commitment"}:
        return COMMITMENT_KIND_UNTIL_STOP
    return ""


def _validate_commitment_stop_condition(raw: object, state: GameState, db: GameDB) -> str:
    from ming_sim.exceptions import DeclarationDataError
    if not isinstance(raw, dict) or not raw:
        raise DeclarationDataError("stop_condition 须为非空 dict")
    for key, cond in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise DeclarationDataError(f"stop_condition key 非法：{key!r}")
        key = key.strip()
        if "." not in key or key.split(".", 1)[0] not in GATE_TABLES:
            raise DeclarationDataError(f"stop_condition key 须带表前缀：{key!r}")
        if not isinstance(cond, str) or not cond.strip():
            raise DeclarationDataError(f"stop_condition value 须把比较算符写在字符串 value 内：{cond!r}")
        cond_text = cond.strip()
        sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond_text)
        if sm and (sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())):
            if _eval_gate_key_str(key, db) is None:
                raise DeclarationDataError(f"stop_condition key 无法寻址：{key!r}")
            continue
        if not re.match(r"^(>=|<=|>|<|==)\s*-?\d+$", cond_text):
            raise DeclarationDataError(f"stop_condition value 非法：{cond!r}")
        if _eval_gate_key(key, state.metrics, db) is None:
            raise DeclarationDataError(f"stop_condition key 无法寻址：{key!r}")
    return _issue_condition_text(raw)


# 给建筑/地区落库做 event 关联用的占位事件（issue 结案触发的副作用无真实 event）。


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
        gate = json.loads(str(raw))
        if not isinstance(gate, dict):
            raise ValueError("持久化停止条件须为对象")
        if gate:
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
        payload = json.loads(str(row["metric_delta"] or "{}"))
        if not isinstance(payload, dict):
            raise ValueError("持久化局势推进后果须为对象")
        progress = payload.get("commitment_progress")
        if progress is not None:
            if not isinstance(progress, dict):
                raise ValueError("持久化承诺推进须为对象")
            raw_total = progress.get("paid_total", 0)
            return _strict_int(0 if raw_total is None else raw_total)
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
    for key in ("economy",):
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
                # 坏原项仍送经济段拒收；不得在此换成有效零值。
                normalized_economy.append(item)
                continue
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






def _monthly_person_rating_changes(effect: Dict[str, object]) -> List[Dict[str, object]]:
    raw_changes: List[Dict[str, object]] = []
    for key in ("人物变更",):
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
    return changes


def _invalid_monthly_person_rating_reason(effect: Dict[str, object]) -> str:
    for key in ("人物变更",):
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
    for key in ("人物变更",):
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
        effect_dict_has_work({"factions": effect.get("factions")}),
        effect_dict_has_work({"class_delta": effect.get("class_delta")}),
        effect_dict_has_work({"region_delta": effect.get("region_delta")}),
        effect_dict_has_work({"army_delta": effect.get("army_delta")}),
        effect_dict_has_work({"power_updates": effect.get("power_updates")}),
        bool(_monthly_person_rating_changes(effect)),
    )
    return any(checks)




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
    region_id: str,
) -> float:
    if _SETTLE_META_LAND_DENOMINATOR_KEY in meta:
        return _as_float(
            meta[_SETTLE_META_LAND_DENOMINATOR_KEY],
            ctx=f"{region_id}.settle._meta.{_SETTLE_META_LAND_DENOMINATOR_KEY}",
        )
    return parsed_total_land


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
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        region_id = str(row["id"])
        fiscal = db.parse_engine_payload_json(row["fiscal"], surface=f"{region_id} fiscal levy")
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
            return int(metrics[key])
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
        # NULL is the documented absent gate value; other conversion failures
        # belong to the stored value, not to a fabricated content error.
        if row[0] is None:
            return None
        values.append(float(row[0]))
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
            cur = _eval_gate_key_str(key, db)
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
        val = _eval_gate_key(key, metrics, db)
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
        roster = json.loads(str(row["participant_roster"] or "[]"))
        if not isinstance(roster, list) or any(not isinstance(item, dict) for item in roster):
            raise ValueError("持久案卷参与人须为对象列表")
        if not roster:
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
                "decree_text": str(row["decree_text"] or ""),
                "execution_note": str(row["execution_note"] or ""),
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
    collector = RejectionCollector()
    with atomic(db):
        triggered = _auto_trigger_seed_issues_in_atomic(state, db, collector)
        collector.flush_to_db(db)
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return triggered


def _auto_trigger_seed_issues_in_atomic(
    state: GameState, db: GameDB, collector: RejectionCollector,
) -> List[Dict[str, object]]:
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
        apply_trigger_effect = historical_event or (
            ev.event_type != "situation" and not db.has_event_triggered(ev.id)
        )
        if apply_trigger_effect and ev.effect_on_trigger:
            rejected = issue_effects._apply_issue_entities(
                db,
                state,
                _content_population_effect_for_save(db, ev.effect_on_trigger),
                f"事件#{ev.id}触发",
                content=c,
                source=Provenance.system_simulation,
            )
            for rejection in rejected:
                rejection.item = {"event_id": ev.id, "effect": rejection.item}
                collector.record("event_trigger", rejection, int(state.turn))
        if ev.event_type != "situation":
            # 非 situation（node/ending）不转 issue，仅记触发避免重复
            if apply_trigger_effect:
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
        stage_text=ev.stage_text or ev.summary,
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

# 月固定收支项的合法账户 / 方向白名单（fiscal_creates 枚举守门，集中一处；
# applier 是唯一的枚举守门（cleaner 只做 direction 同义词映射等无损规范化,cmr S3 r2）。







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
                value = int(fields["population"])
            except (TypeError, ValueError):
                pass  # 坏值原样交给领域核；持久读取不在此解析 catch 中。
            else:
                scaled_fields["population"] = db.scale_content_population_to_save_unit(value)
            scaled_region_delta[rid] = scaled_fields
        else:
            scaled_region_delta[rid] = fields
    scaled["region_delta"] = scaled_region_delta
    return scaled















# 校验「二级非 dict 会让 apply 在**逐 entity 写 DB 的中途崩**,留下部分已写 + 回合照推 = 半落库」
# 的字段。这三者 apply 都逐项 UPDATE/INSERT,前面的 entity 先落库、坏的 entity 崩:
#   - region_delta / army_delta:apply 裸调,崩直接抛穿;
#   - power_updates:落库编排器虽裹 try/except,但只接住异常不回滚——前面已写的 power
#     行仍被后续 record_log/save_turn 提交 = 半落库(CMR R2 codex)。prompt 里 power_updates 恒为
#     嵌套 dict,无扁平标量形态,故二级非 dict = 真畸形,校验前置拦截正确。
# **不**列入（交给各自 adapter 按契约处理）:faction_delta 吃旧扁平 int
# {"阉党": -10}（prompt 允许、合法）；class_delta 的扁平 item 不合法，由 adapter 逐项
# `invalid_enum` 拒收（#564），而非 validate 层当 nested-dict shape 拒收。
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
                    # 与 tracker advance/close 路径一致：自然结案也落实体后果 + 帝国修正，
                    # 否则靠 inertia 推到 100 的 issue 会丢 new_armies/army_delta/人物状态/legacy（codexB-P1）。
                    for _tr in issue_effects._apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}结案",
                        applied_person_changes=applied_person_changes,
                        issue_id=issue_id, issue_title=str(new_row["title"]),
                               origin_ref=parent_origin_ref,
                    source=source):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.reason}")
                        inertia_rejections.append(_tr)
                    if commit_local:
                        db.conn.commit()
                    continue
                elif new_row["status"] == "failed":
                    effect = loads_effect_dict(new_row["effect_on_fail"])
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
        if ongoing:
            issue_monthly_rejections: List[RejectedItem] = []
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
            _om = ongoing.get("metrics")
            if _om is not None and not isinstance(_om, dict):
                issue_monthly_rejections.append(RejectedItem(item={"field": "metrics", "raw_value": _om}, reason="月度指标须为对象", category="invalid_shape", source=source))
            for k, v in (_om if isinstance(_om, dict) else {}).items():
                if k not in ISSUE_METRIC_KEYS:
                    issue_monthly_rejections.append(RejectedItem(item={"field": k, "raw_value": v}, reason="月度指标不可执行", category="invalid_enum", source=source))
                    continue
                try:
                    raw = _strict_int(v)
                except (TypeError, ValueError):
                    issue_monthly_rejections.append(RejectedItem(item={"field": k, "raw_value": v}, reason="月度指标须为整数", category="invalid_enum", source=source))
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
                [] if ongoing.get("economy") is None else ongoing["economy"],
                allow_pay_arrears_pool=allow_pay_arrears_pool,
                pay_arrears_pool_army_ids=pay_arrears_pool_army_ids,
                origin_ref=parent_origin_ref,
            source=source)
            economy_rejections = _eco_out_rejections
            issue_monthly_rejections.extend(economy_rejections)
            economy_part = _eco_out

            monthly_result = issue_effects._apply_monthly_ongoing_entities(
                db,
                state,
                ongoing,
                f"局势#{issue_id}持续效果",
                applied_person_changes=applied_person_changes,
                origin_ref=parent_origin_ref,
            source=source)
            for applied_row in monthly_result.applied:
                applied_monthly_parts.update(applied_row)
            issue_monthly_rejections.extend(monthly_result.rejected)
            inertia_rejections.extend(issue_monthly_rejections)
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
        gate = db.parse_engine_payload_json(row["clear_gate"], surface="legacy clear gate")
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
