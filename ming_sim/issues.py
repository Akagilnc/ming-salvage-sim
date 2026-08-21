"""Issue 系统：候选事件、issue 立项/推进/结案、tracker 输出落地、inertia 漂移。L6。

通过 bind_content() 注入 GameContent（取 EVENTS/SEED_EVENTS/EVENT_BY_ID）。
"""

from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from ming_sim.applier import atomic
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET
from ming_sim.constants import (
    TURN_UNIT, REGION_SCORE_FIELDS, REGION_QUANTITY_FIELDS, REGION_TEXT_FIELDS,
    ARMY_SCORE_FIELDS, ARMY_QUANTITY_FIELDS, ARMY_TEXT_FIELDS, FISCAL_SCORE_FIELDS,
    BUILDING_SCORE_FIELDS, BUILDING_QUANTITY_FIELDS, BUILDING_TEXT_FIELDS,
    POWER_SCORE_FIELDS, POWER_TEXT_FIELDS, CHARACTER_TEXT_FIELDS,
    REGION_FIELD_ALIASES, ARMY_FIELD_ALIASES, POWER_FIELD_ALIASES, GATE_TABLES,
)
from ming_sim.content import GameContent
from ming_sim.context import victory_status
from ming_sim.db import (
    GameDB,
    _approx_wanliang,
    infer_office_type_from_office,
    normalize_office,
    resolve_office_type_preserving_title,
)
from ming_sim.relations import EMPEROR_NODE
from ming_sim.decree_vocabulary import (
    dossier_action_policy,
    format_public_progress_disclosure,
    terminal_report_facade,
)
from ming_sim.exceptions import SettlementAbort
from ming_sim.flows import (
    ISSUE_METRIC_KEYS,
    ISSUE_METRIC_LOCK_CAPS,
    _apply_class_dict,
    _apply_economy_list,
    _apply_faction_dict,
    _apply_metric_dict,
    army_needed,
    _strict_int,
)
from ming_sim.models import Event, GameState, effect_dict_has_work, is_vassal_prince, loads_effect_dict
from ming_sim.person_archive_contract import (
    PERSON_ALLEGIANCE_CHANGE_WAYS,
    PERSON_IDENTITY_TITLES,
    PERSON_STATUSES,
    normalize_reason_code,
    resolve_person_transition,
)
from ming_sim.person_delta_adapter import normalize_person_changes
from ming_sim.token_stats import tlog

_content: Optional[GameContent] = None

INITIATIVE_ACTIVE_CAP = 15
INITIATIVE_ACTIVE_CAP_LABEL = "十五"
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


_AUTHORITY_GRANT_OPS = frozenset({"授予", "grant"})
_AUTHORITY_REVOKE_OPS = frozenset({"收回", "revoke"})


def _apply_authority_change_item(
    db: GameDB, state: GameState, item: Dict[str, object],
) -> Dict[str, object]:
    """Apply one production-slot authority grant/revoke under the #611 contract."""
    if "dossier_id" not in item or item.get("dossier_id") in (None, ""):
        raise ValueError("missing_dossier_source")
    try:
        dossier_id = _parse_sqlite_id(item.get("dossier_id"))
    except (TypeError, ValueError):
        raise ValueError("missing_dossier_source") from None
    if dossier_id <= 0 or db.get_decree_dossier(dossier_id) is None:
        raise ValueError("missing_dossier_source")
    if not db.dossier_authorizes_effects(dossier_id):
        raise ValueError("dossier_not_effect_eligible")
    op = str(item.get("动作") or item.get("op") or "").strip()
    if op not in _AUTHORITY_GRANT_OPS | _AUTHORITY_REVOKE_OPS:
        raise ValueError("授权变更动作只收授予/收回")

    if op in _AUTHORITY_GRANT_OPS:
        holder_id = str(item.get("holder_id") or "").strip()
        privilege = str(item.get("privilege") or item.get("权项") or "").strip()
        scope = str(item.get("scope") or item.get("事域") or "").strip()
        if not holder_id or not privilege or not scope:
            raise ValueError("授予项必须含 holder_id/privilege/scope")
        if privilege not in AUTHORITY_PRIVILEGE_SET:
            raise ValueError("授权权项不在首批枚举")
        kind, separator, target_id = scope.partition(":")
        if not separator or not kind or not target_id:
            raise ValueError("invalid_authority_scope")
        if not db.conn.execute(
            "SELECT 1 FROM characters WHERE name=?", (holder_id,)
        ).fetchone():
            raise ValueError("授权对象不在人物档")
        origin = db.find_authority_by_origin(
            dossier_id, holder_id=holder_id, privilege=privilege, scope=scope,
        )
        if origin is not None:
            # Origin idempotency is independent of current applicability: a
            # revoked or expired grant remains the same durable authority row.
            return {
                "动作": "授予",
                "authority_id": int(origin["id"]),
                "dossier_id": dossier_id,
                "holder_id": holder_id,
                "privilege": privilege,
                "scope": scope,
                "reason": "same_dossier_replay",
            }
        effective_raw = item.get("effective_turn", item.get("生效回合"))
        expires_raw = item.get("expires_turn", item.get("失效回合"))
        effective_turn = (
            int(state.turn) if effective_raw in (None, "")
            else _parse_sqlite_id(effective_raw)
        )
        expires_turn = (
            None if expires_raw in (None, "")
            else _parse_sqlite_id(expires_raw)
        )
        if expires_turn is not None and expires_turn < effective_turn:
            raise ValueError("授权失效回合不得早于生效回合")
        existing = db.find_active_authority(
            state.turn, holder_id=holder_id, privilege=privilege, scope=scope,
        )
        if existing is not None:
            raise ValueError("duplicate_active_authority")
        cursor = db.conn.execute(
            "INSERT INTO authority_records "
            "(holder_id,privilege,scope,effective_turn,expires_turn,dossier_id) "
            "VALUES (?,?,?,?,?,?)",
            (
                holder_id, privilege, scope, effective_turn, expires_turn,
                dossier_id,
            ),
        )
        authority_id = int(cursor.lastrowid)
        return {
            "动作": "授予",
            "authority_id": authority_id,
            "dossier_id": dossier_id,
            "holder_id": holder_id,
            "privilege": privilege,
            "scope": scope,
        }

    try:
        authority_id = _parse_sqlite_id(item.get("authority_id"))
    except (TypeError, ValueError):
        raise ValueError("unknown_authority_id") from None
    if authority_id <= 0:
        raise ValueError("unknown_authority_id")
    record = db.get_authority(authority_id)
    if record is None:
        raise ValueError("unknown_authority_id")
    if bool(record.get("revoked")):
        return {
            "动作": "收回",
            "authority_id": authority_id,
            "dossier_id": dossier_id,
            "reason": "already_revoked",
        }
    revoked = db.conn.execute(
        "UPDATE authority_records SET revoked=1,revoked_turn=? "
        "WHERE id=? AND revoked=0", (int(state.turn), authority_id),
    )
    if revoked.rowcount <= 0:
        raise ValueError("unknown_authority_id")
    privilege = str(record.get("privilege") or "")
    scope = str(record.get("scope") or "")
    holder_id = str(record.get("holder_id") or "")
    db.record_relation_edge_event(
        source=holder_id,
        target=EMPEROR_NODE,
        event_kind="结怨",
        context=f"收权·罢差·{privilege}·{scope}",
        origin=f"authority_revoke:{authority_id}",
        turn=int(state.turn),
        year=int(state.year),
        period=int(state.period),
        evidence=False,
    )
    return {
        "动作": "收回",
        "authority_id": authority_id,
        "dossier_id": dossier_id,
        "holder_id": holder_id,
        "privilege": privilege,
        "scope": scope,
    }


def _payload_owned_dossier_for_origin(db: GameDB, origin_ref: object) -> Optional[Dict[str, object]]:
    """Resolve an authorized dossier through the canonical ownership policy."""
    text = str(origin_ref or "").strip()
    if not text.startswith("dossier:"):
        return None
    try:
        dossier_id = _parse_sqlite_id(text.split(":", 1)[1])
    except ValueError:
        return None
    row = db.get_decree_dossier(dossier_id)
    if row is None or not db.dossier_authorizes_effects(dossier_id):
        return None
    try:
        payload = row.get("payload") or json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if dossier_action_policy(row.get("action_type"), payload)["effect_owner"] != "payload":
        return None
    return {**row, "payload": payload}


def _canonical_appointment_fields(
    payload: Dict[str, object], *, current_office_type: str = "", llm_config=None,
) -> tuple[str, str, str]:
    """Canonical fields consumed by both appointment apply and payload dedup."""
    office = normalize_office(str(payload.get("office") or payload.get("new_office") or ""))
    office_type = resolve_office_type_preserving_title(
        office,
        str(payload.get("office_type") or payload.get("new_office_type") or ""),
        current_office_type,
        llm_config,
    )
    return office, office_type, appointment_tenure_from(payload)


def _payload_owned_person_duplicate(
    db: GameDB,
    item: Dict[str, object],
    *,
    current_office_type: str = "",
    llm_config=None,
) -> bool:
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
    payload_fields = _canonical_appointment_fields(payload, **canonical_kwargs)
    return bool(payload_fields[0]) and payload_fields == _canonical_appointment_fields(
        item, **canonical_kwargs
    )


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


def _apply_issue_buildings(
    db: GameDB,
    state: GameState,
    ops: object,
    pseudo_event: Event,
    reason: str,
    commit: bool = True,
    origin_ref: str = "盘面自发",
) -> List[Dict[str, object]]:
    """落地 issue effect 里的 buildings 段：建筑随局势结案而新建/改数值/废止。

    每项 op 一个 dict，`action` ∈ create/modify/remove：
      - create：`region_id`/`name`/`category` 必填，其余可选（level/condition/maintenance/risk/output_metric/output_amount/status）
      - modify：`building_id` 必填 + 增量字段（走 apply_building_deltas）
      - remove：`building_id` 必填
    建筑的新建/变更唯一入口——不存在顶层 building_delta/new_buildings。
    """
    applied: List[Dict[str, object]] = []
    if not isinstance(ops, list):
        return applied
    for op in ops:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action") or "").lower()
        try:
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
                    commit=commit,
                    origin_ref=origin_ref,
                )
                applied.append({"action": "create", "building_id": bid,
                                 "name": str(op.get("name") or "")})
            elif action == "modify":
                bid = str(op.get("building_id") or "")
                fields = {k: v for k, v in op.items()
                          if k not in ("action", "building_id", "origin_ref")}
                fields.setdefault("reason", reason)
                ch = db.apply_building_deltas(
                    state, pseudo_event, None, "档房", {bid: fields},
                    commit=commit, origin_ref=origin_ref,
                )
                applied.append({"action": "modify", "building_id": bid, "changes": ch})
            elif action == "remove":
                bid = str(op.get("building_id") or "")
                ok = db.remove_building(
                    state, bid, reason=reason, commit=commit,
                    origin_ref=origin_ref,
                )
                applied.append({"action": "remove", "building_id": bid, "removed": ok})
            else:
                print(f"[WARN] issue effect buildings: action 非法 '{action}'，跳过。")
        except Exception as exc:
            print(f"[WARN] issue effect buildings 落库失败：{exc}；op={op}")
            raise
    return applied


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


def commitment_progress_payload(
    db: GameDB,
    state: GameState,
    row: sqlite3.Row,
    *,
    paid_this_month: int = 0,
    include_current_month: bool = False,
) -> Optional[Dict[str, object]]:
    keys = row.keys() if hasattr(row, "keys") else []
    if not str(row["commitment_kind"] if "commitment_kind" in keys else "").strip():
        return None
    gate = _commitment_stop_gate(row)
    remaining = _commitment_remaining_from_gate(gate, state, db) if gate else None
    paid_total = _latest_commitment_paid_total(db, int(row["id"])) + max(0, int(paid_this_month))
    # Fall back to state.turn (→ 0 elapsed) when origin_turn is unset — whether the
    # key is absent OR present-but-NULL/0. `int(row["origin_turn"] or 0)` would collapse
    # a NULL/0 to 0 and leak the absolute turn number into months_elapsed (#380 cmr:
    # gemini + coderabbit). Only a positive origin_turn is a real anchor.
    origin_turn_raw = row["origin_turn"] if "origin_turn" in keys else None
    try:
        origin_turn = int(origin_turn_raw)
    except (TypeError, ValueError):
        origin_turn = 0
    if origin_turn <= 0:
        origin_turn = int(state.turn)
    months_elapsed = max(0, int(state.turn) - origin_turn)
    if include_current_month:
        months_elapsed = int(months_elapsed) + 1
    payload: Dict[str, object] = {
        "months_elapsed": int(months_elapsed),
        "paid_total": int(paid_total),
    }
    if remaining is not None:
        if _commitment_gate_references_arrears(row):
            payload["remaining_arrears"] = float(remaining)
        else:
            payload["remaining_to_goal"] = int(remaining)
    return payload


def _commitment_arrears_remaining_text(amount: object) -> str:
    text = _approx_wanliang(amount)
    if text.startswith("欠饷"):
        return "尚欠" + text[len("欠饷"):]
    return text


def commitment_display_text(progress: Dict[str, object], row: sqlite3.Row) -> str:
    keys = row.keys() if hasattr(row, "keys") else []
    ongoing = loads_effect_dict(row["ongoing_effects"] if "ongoing_effects" in keys else {})
    end_turn = int(row["end_turn"] or 0) if "end_turn" in keys else 0
    origin_turn = int(row["origin_turn"] or 0) if "origin_turn" in keys else 0
    stop_gate = _commitment_stop_gate(row)
    months = int(progress.get("months_elapsed") or 0)
    duration = max(0, end_turn - origin_turn) if end_turn > 0 else 0

    if not _monthly_ongoing_effects_has_work(ongoing) and end_turn > 0:
        return f"限{duration}月·到期待裁"

    if stop_gate and _commitment_gate_references_arrears(row):
        parts = [f"已第{months}月"]
        if "remaining_arrears" in progress:
            parts.append(_commitment_arrears_remaining_text(progress["remaining_arrears"]))
        parts.append("直到补齐")
        return "·".join(parts)

    if stop_gate:
        parts = [f"已履行{months}月"]
        if "remaining_to_goal" in progress:
            parts.append("距达标仍有差距")
        parts.append("直到达标")
        return "·".join(parts)

    if end_turn > 0:
        remaining = max(0, duration - months)
        return f"限{duration}月·已履行{months}月·还剩{remaining}月"

    return f"已履行{months}月·开放承诺"


def commitment_timed_bar_value(progress: Dict[str, object], row: sqlite3.Row) -> Optional[int]:
    """Time-based bar for auto-expiring timed commitments (ongoing effects + end_turn + no gate).

    Returns None for bar-driven (stop_gate), arrears, or passive (no ongoing effects) commitments.
    When non-None, bar = wall-clock months_elapsed / (end_turn - origin_turn) * 100, clamped 0-100.
    """
    keys = row.keys() if hasattr(row, "keys") else []
    end_turn = int(row["end_turn"] or 0) if "end_turn" in keys else 0
    if end_turn <= 0:
        return None
    if _commitment_stop_gate(row):
        return None
    ongoing = loads_effect_dict(row["ongoing_effects"] if "ongoing_effects" in keys else {})
    if not _monthly_ongoing_effects_has_work(ongoing):
        return None
    origin_turn = int(row["origin_turn"] or 0) if "origin_turn" in keys else 0
    duration = end_turn - origin_turn
    if duration <= 0:
        return None
    months = int(progress.get("months_elapsed") or 0)
    return max(0, min(100, int(round(months * 100 / duration))))


def _commitment_bar_value(progress: Dict[str, object]) -> Optional[int]:
    if "remaining_arrears" not in progress:
        return None
    paid = max(0, int(progress.get("paid_total") or 0))
    try:
        remaining = max(0.0, float(progress.get("remaining_arrears") or 0))
    except (TypeError, ValueError):
        remaining = 0.0
    total = paid + remaining
    if total <= 0:
        return 100
    return max(0, min(100, int(round(paid * 100 / total))))


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
) -> Dict[str, object]:
    return {
        "rejected": True,
        "category": "invalid_shape",
        "reason": f"{field}.{entity_id} 须为对象(dict)",
        "item": {"field": field, "id": entity_id, "value": raw_value},
        "issue_strict": False,
    }


def _monthly_mapping_effect(
    effect: Dict[str, object],
    *keys: str,
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
            rejections.append(_invalid_monthly_mapping_shape(key, entity_id, raw_changes))
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
        "character_status_changes",
        "character_power_changes",
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
    registry=None,
    llm_config: Any = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
    origin_ref: str = "盘面自发",
) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    applied: Dict[str, object] = {}
    rejections: List[Dict[str, object]] = []

    factions, faction_shape_rejections = _monthly_mapping_effect(effect, "factions", "faction_delta")
    classes, class_shape_rejections = _monthly_mapping_effect(effect, "classes", "class_delta")
    region_delta, region_shape_rejections = _monthly_mapping_effect(effect, "region_delta", "regions")
    army_delta, army_shape_rejections = _monthly_mapping_effect(effect, "army_delta", "armies")
    power_updates, power_shape_rejections = _monthly_mapping_effect(effect, "power_updates")
    rejections.extend(
        faction_shape_rejections
        + class_shape_rejections
        + region_shape_rejections
        + army_shape_rejections
        + power_shape_rejections
    )

    if factions:
        faction_result = _apply_faction_dict(db, factions)
        if faction_result.applied:
            applied["factions"] = faction_result.applied
        rejections.extend(faction_result.rejections)

    if classes:
        class_result = _apply_class_dict(db, classes)
        if class_result.applied:
            applied["class_delta"] = class_result.applied
        rejections.extend(class_result.rejections)

    if region_delta:
        region_changes = db.apply_region_deltas(
            state, _ISSUE_PSEUDO_EVENT, None, label, region_delta, origin_ref=origin_ref
        )
        applied_region = [item for item in region_changes if not item.get("rejected")]
        if applied_region:
            applied["region_delta"] = applied_region
        rejections.extend(item for item in region_changes if item.get("rejected"))

    if army_delta:
        army_changes = db.apply_army_deltas(
            state, _ISSUE_PSEUDO_EVENT, None, label, army_delta, origin_ref=origin_ref
        )
        applied_army = [item for item in army_changes if not item.get("rejected")]
        if applied_army:
            applied["army_delta"] = applied_army
        rejections.extend(item for item in army_changes if item.get("rejected"))

    if power_updates:
        power_changes = db.apply_power_deltas(state, power_updates, origin_ref=origin_ref)
        applied_power = [item for item in power_changes if not item.get("rejected")]
        if applied_power:
            applied["power_updates"] = applied_power
        rejections.extend(item for item in power_changes if item.get("rejected"))

    person_changes = _monthly_person_rating_changes(effect)
    if person_changes:
        effective_content = content if content is not None else _ctx()
        results = _apply_person_changes(
            db,
            state,
            person_changes,
            content=effective_content,
            registry=registry,
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
            origin_ref=origin_ref,
        )
        applied_people = [item for item in results if not item.get("rejected")]
        if applied_people:
            applied["人物变更"] = applied_people
        rejections.extend(item for item in results if item.get("rejected"))
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
    progress = commitment_progress_payload(db, state, row) or {}
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
    progress = commitment_progress_payload(db, state, row) or {}
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


def issue_to_payload(
    row: sqlite3.Row,
    recent_advances: List[sqlite3.Row],
    db: Optional[GameDB] = None,
    state: Optional[GameState] = None,
) -> Dict[str, object]:
    """喂给推演 agent 的事项精简视图：状态、进度、效果、最近一次推进。"""
    keys = row.keys() if hasattr(row, "keys") else []
    resolve_cond = row["resolve_condition"] if "resolve_condition" in keys else ""
    fail_cond = row["fail_condition"] if "fail_condition" in keys else ""
    commitment_kind = row["commitment_kind"] if "commitment_kind" in keys else ""
    stop_condition = row["stop_condition"] if "stop_condition" in keys else ""
    end_turn = int(row["end_turn"]) if "end_turn" in keys else 0
    payload = {
        "issue_id": int(row["id"]),
        "kind": row["kind"],
        "title": row["title"],
        "状态": row["stage_text"],
        "进度": int(row["bar_value"]),
        "局势走向": int(row["inertia"]),
        f"当前每{TURN_UNIT}效果": loads_effect_dict(row["ongoing_effects"]),
        "失败效果": loads_effect_dict(row["effect_on_fail"]),
        "成功效果": loads_effect_dict(row["effect_on_resolve"]),
        "结案条件": resolve_cond or "(未填)",
        "失败条件": fail_cond or "(未填)",
        "cancellable": row["cancellable"],
        f"上{TURN_UNIT}推进": (
            {
                "delta_bar": int(recent_advances[0]["delta_bar"]),
                "narrative": recent_advances[0]["narrative"],
            }
            if recent_advances else None
        ),
        **commitment_condition_role(resolve_cond, commitment_kind),
    }
    if commitment_kind:
        payload["commitment_kind"] = commitment_kind
    if stop_condition:
        payload["stop_condition"] = stop_condition
    if end_turn:
        payload["end_turn"] = end_turn
    if db is not None and state is not None:
        progress = commitment_progress_payload(db, state, row)
        if progress is not None:
            payload["commitment_progress"] = progress
            payload["待办未解进度"] = commitment_display_text(progress, row)
    return payload


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
_FISCAL_LEVY_PROVISIONAL_KEYS = {
    _SETTLE_META_BASE_TRANSPORT_KEY,
    _SETTLE_META_LIAO_SEED_KEY,
    _SETTLE_META_JIAO_SEED_KEY,
    _SETTLE_META_LIAN_SEED_KEY,
    _SETTLE_META_LAND_DENOMINATOR_KEY,
}
_FISCAL_LEVY_PRESENTATION_INSTRUCTION = (
    "以奏疏口吻给出万两量级的加征估算与可补军费程度；"
    "可写史实加征语和各省约略分解。"
)


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
        target_sanxiang = target_liao + target_jiao + target_lian
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


def _round_half_up(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step + 0.5) * step


def _wanliang_range(amount: float, *, unit: str = "万两/月") -> Dict[str, object]:
    value = max(0.0, float(amount))
    lower = _round_half_up(value * 0.9, 1.0)
    upper = _round_half_up(value * 1.1, 1.0)
    midpoint = round(value, 1)
    lower = min(lower, midpoint)
    upper = max(upper, midpoint)
    if upper < lower:
        upper = lower
    if value > 0 and upper == lower:
        upper = round(lower + 1.0, 1)
    return {
        "lower": round(lower, 1),
        "midpoint": midpoint,
        "upper": round(upper, 1),
        "unit": unit,
        "text": f"约{lower:g}至{upper:g}{unit}",
    }


def _plain_wanliang_approx(amount: float) -> str:
    value = max(0.0, float(amount))
    if value <= 0:
        return "无明显缺口"
    if value < 10:
        return "不足十万两"
    step = 5.0 if value < 20 else 10.0
    rounded = max(step, _round_half_up(value, step))
    return f"约{rounded:g}万两"


def _fiscal_levy_coverage_text(monthly_added: float, gap: float, basis: str) -> tuple[float, str]:
    if gap <= 0:
        return 0.0, "军费缺口暂不显，新增饷源可作缓冲"
    coverage_cheng = round(max(0.0, monthly_added) / gap * 10.0, 1)
    if coverage_cheng < 0.5:
        coverage = "不足半成"
    elif coverage_cheng < 1.0:
        coverage = "约半成"
    else:
        coverage = f"约{coverage_cheng:g}成"
    return coverage_cheng, f"按{basis}{_plain_wanliang_approx(gap)}估，可补军费{coverage}"


def _current_army_gap(db: GameDB) -> tuple[float, str, str]:
    rows = db.conn.execute(
        """
        SELECT *
        FROM armies
        WHERE owner_power='ming' AND is_tusi=0 AND self_funded_pay=0
        """
    ).fetchall()
    arrears = sum(float(row["arrears"] or 0.0) for row in rows)
    if arrears > 0:
        return arrears, "全军累计欠饷", "万两"
    monthly_due = sum(float(army_needed(row)) for row in rows)
    return monthly_due, "本月应发军饷", "万两/月"


def _region_fiscal_levy_components(db: GameDB) -> List[Dict[str, object]]:
    rows = db.conn.execute(
        "SELECT id, name, controlled_by, fiscal FROM regions ORDER BY id"
    ).fetchall()
    total_land = 0.0
    parsed_rows: List[Dict[str, object]] = []
    denominator_complete = True
    for row in rows:
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
            st = settle.get("st")
            p = settle.get("p")
            if not isinstance(st, dict):
                raise ValueError(f"{region_id}.settle.st 非字典")
            if not isinstance(p, dict):
                raise ValueError(f"{region_id}.settle.p 非字典")
            land = _as_float(st.get("官民田"), ctx=f"{region_id}.settle.st.官民田")
        except ValueError as exc:
            denominator_complete = False
            tlog(f"[fiscal-levy] {region_id} settle 解析失败，本{TURN_UNIT}饷率通道出列：{type(exc).__name__}: {exc}")
            continue
        total_land += max(0.0, land)
        parsed_rows.append({
            "row": row,
            "fiscal": fiscal,
            "settle": settle,
            "p": p,
            "land": land,
        })
    components: List[Dict[str, object]] = []
    for parsed in parsed_rows:
        row = parsed["row"]
        if str(row["controlled_by"]) != "ming":
            continue
        region_id = str(row["id"])
        p = parsed["p"]
        land = float(parsed["land"])
        settle = parsed["settle"]
        try:
            meta_raw = settle.get("_meta") or {}
            if not isinstance(meta_raw, dict):
                raise ValueError(f"{region_id}.settle._meta 非字典")
            meta = dict(meta_raw)
            liao_seed = _fiscal_levy_liao_seed(meta, p, region_id)
            land_denominator = _fiscal_levy_land_denominator(
                meta,
                total_land,
                denominator_complete=denominator_complete,
                region_id=region_id,
            )
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
        except ValueError as exc:
            tlog(f"[fiscal-levy] {region_id} settle 解析失败，本{TURN_UNIT}饷率通道出列：{type(exc).__name__}: {exc}")
            continue
        components.append({
            "region_id": region_id,
            "region_name": str(row["name"]),
            "liao_seed": liao_seed,
            "jiao_seed": jiao_seed,
            "lian_seed": lian_seed,
        })
    return components


def _fiscal_levy_event_added_amount(event_id: str, components: List[Dict[str, object]]) -> float:
    total = 0.0
    for item in components:
        liao_seed = float(item["liao_seed"])
        jiao_seed = float(item["jiao_seed"])
        lian_seed = float(item["lian_seed"])
        if event_id == _LIAO_LEVY_RISE_EVENT_ID:
            total += liao_seed * (_LIAO_LEVY_RISE_FACTOR - 1.0)
        elif event_id == _JIAO_LEVY_START_EVENT_ID:
            total += jiao_seed
        elif event_id == _LIAN_LEVY_START_EVENT_ID:
            total += lian_seed
        elif event_id == _JIAO_LEVY_STOP_EVENT_ID:
            total -= jiao_seed
    return total


def fiscal_levy_memorial_estimates(state: GameState, db: GameDB) -> List[Dict[str, object]]:
    """Return court-facing levy estimates for fiscal events resolved this turn.

    This is the #259 shadow/#260 seam: callers read event outcomes from the same
    event ledger regardless of whether the terminal reason came from the current
    shadow stub (`source=fiscal_levy_shadow`) or a future real edict route.
    """
    c = _ctx()
    rows = db.conn.execute(
        """
        SELECT event_id, terminal_reason, source
        FROM event_triggers
        WHERE turn=? AND terminal_state='triggered'
        """,
        (state.turn,),
    ).fetchall()
    if not rows:
        return []
    row_by_event_id = {str(row["event_id"]): row for row in rows}
    terminal_records = _event_terminal_records(db)
    components = _region_fiscal_levy_components(db)
    army_gap, gap_basis, gap_unit = _current_army_gap(db)
    estimates: List[Dict[str, object]] = []
    for ev in c.events:
        if getattr(ev, "category", "") != FISCAL_LEVY_EVENT_CATEGORY:
            continue
        row = row_by_event_id.get(ev.id)
        if row is None:
            continue
        if ev.id == _JIAO_LEVY_START_EVENT_ID and not _jiao_levy_in_force(terminal_records, state):
            continue
        added = _fiscal_levy_event_added_amount(ev.id, components)
        if added <= 0:
            continue
        if str(row["terminal_reason"] or "") != "已准":
            continue
        coverage_cheng, coverage_text = _fiscal_levy_coverage_text(added, army_gap, gap_basis)
        estimates.append({
            "event_id": ev.id,
            "event_title": ev.title,
            "terminal_reason": str(row["terminal_reason"] or ""),
            "source": str(row["source"] or ""),
            "scope": "国总口径",
            "presentation_instruction": _FISCAL_LEVY_PRESENTATION_INSTRUCTION,
            "national_added_wanliang": _wanliang_range(added),
            "national_army_gap_wanliang": _wanliang_range(army_gap, unit=gap_unit),
            "army_gap_basis": gap_basis,
            "army_gap_coverage_cheng": coverage_cheng,
            "army_gap_coverage_text": coverage_text,
        })
    return estimates


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
                    _apply_issue_entities(
                        db,
                        state,
                        ev.effect_on_trigger,
                        f"事件#{ev.id}触发",
                        content=c,
                    )
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
                _apply_issue_entities(
                    db,
                    state,
                    ev.effect_on_trigger,
                    f"事件#{ev.id}触发",
                    content=c,
                )
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


def _format_issue_ongoing(ongoing_raw: str) -> str:
    """简短描述每月固定影响。"""
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
    print(f"─── 待办事项 (系统 {len(situations)}/12  玩家 {len(initiatives)}/{INITIATIVE_ACTIVE_CAP}) ───")

    def _print_row(row, label: str) -> None:
        bar = _bar_ascii(int(row["bar_value"]))
        print(f"{label} #{row['id']} {row['title']}")
        print(f"  {row['bar_bad_meaning']:6s} {bar} {row['bar_good_meaning']:6s}  bar={int(row['bar_value']):3d}  {row['stage_text']}")
        inertia = int(row["inertia"])
        ongoing_txt = _format_issue_ongoing(row["ongoing_effects"] or "{}")
        line_parts = [_format_inertia(inertia)]
        progress = commitment_progress_payload(db, state, row)
        if progress is not None:
            line_parts.append(commitment_display_text(progress, row))
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
        effect_resolve = ev.effect_on_resolve
    if ev.effect_on_fail:
        effect_fail = ev.effect_on_fail
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
    registry: object = None,
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
    registry_agents = getattr(registry, "agents", None)
    registry_session_ids = getattr(registry, "session_ids", None)
    registry_agents_snapshot = dict(registry_agents) if isinstance(registry_agents, dict) else None
    registry_session_ids_snapshot = (
        dict(registry_session_ids) if isinstance(registry_session_ids, dict) else None
    )

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
        if registry_agents_snapshot is not None and isinstance(registry_agents, dict):
            registry_agents.clear()
            registry_agents.update(registry_agents_snapshot)
        if registry_session_ids_snapshot is not None and isinstance(registry_session_ids, dict):
            registry_session_ids.clear()
            registry_session_ids.update(registry_session_ids_snapshot)

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


def _pending_person_changes_block_event_gate(
    ev: Event,
    pending_person_changes: List[Dict[str, object]],
    db: GameDB,
    *,
    allow_legacy_partial_power: bool = False,
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
                if status in {"active", "candidate"}:
                    continue
            if status not in PERSON_STATUSES:
                continue
            if item.get("legacy_gate") and cur_status != "active":
                continue
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=normalize_reason_code(item.get("reason_code")),
            )
            if transition.startswith("reject:"):
                continue
            overlay(name, "status", status)
            overlay(name, "status_reason", reason_text[:200])
            overlay(name, "reason_code", reason_code if reason_code else "")
            overlay(name, "office", "")
            overlay(name, "transit_to", "")
        elif action == "行止":
            if cur_status != "active":
                continue
            new_location = str(item.get("location") or "").strip()
            transit_to = str(item.get("transit_to") or "").strip()
            if not new_location and not transit_to:
                continue
            valid = True
            for region_id in (new_location, transit_to):
                if region_id and region_id not in valid_regions:
                    valid = False
                    break
            if not valid:
                continue
            overlay(name, "location", new_location or row_value(row, "location"))
            overlay(name, "transit_to", transit_to)
        elif action == "易主":
            way = str(item.get("方式") or item.get("way") or "").strip()
            backlash = item.get("反噬", item.get("backlash"))
            legacy_partial = allow_legacy_partial_power and bool(item.get("legacy_partial"))
            if not way:
                continue
            if way not in PERSON_ALLEGIANCE_CHANGE_WAYS and not legacy_partial:
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
            overlay(name, "status_reason", str(item.get("reason") or "")[:200])
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
                overlay(name, "status_reason", str(item.get("reason") or "")[:200] or "诏书任命")
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
    name = str(legacy.get("name") or "").strip() or f"{issue_title}遗留"
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
        narrative_hint=str(legacy.get("narrative_hint") or "")[:200],
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


def _apply_issue_entities(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    label: str,
    content=None,
    registry=None,
    llm_config: Any = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
    commit: bool = True,
    origin_ref: str = "盘面自发",
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
    tolerated: List[Dict[str, object]] = []
    def effective_content():
        return content if content is not None else _ctx()

    def _raise_on_rejected(results, what: str) -> None:
        strict = [r for r in (results or [])
                  if isinstance(r, dict) and r.get("rejected")
                  and r.get("issue_strict", True)]
        if strict:
            reasons = "；".join(str(r.get("reason") or "") for r in strict)
            raise ValueError(f"{label} {what} 非法（全局严格，不静默）：{reasons}")
        # 容忍项（issue_strict=False）留痕不蒸发（cmr S2 r2,2/2:改前是 print,
        # 不留比 print 更静默）：收集返回,tracker-output 路挂 issue_summary 进
        # rejection_reports,inertia 路由 caller tlog。
        tolerated.extend(
            {**r, "label": label}
            for r in (results or [])
            if isinstance(r, dict) and r.get("rejected") and not r.get("issue_strict", True)
        )

    region_delta = effect.get("region_delta")
    if isinstance(region_delta, dict) and region_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _raise_on_rejected(
            db.apply_region_deltas(state, pseudo, None, label, region_delta, commit=commit,
                                   origin_ref=origin_ref, require_origin=True), "地区变化"
        )
    new_armies = effect.get("new_armies")
    if isinstance(new_armies, list) and new_armies:
        _raise_on_rejected(
            db.create_armies_from_extraction(state, new_armies, actor=label, commit=commit,
                                              origin_ref=origin_ref, require_origin=True), "建军"
        )
    army_delta = effect.get("army_delta")
    if isinstance(army_delta, dict) and army_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _raise_on_rejected(
            db.apply_army_deltas(state, pseudo, None, label, army_delta, commit=commit,
                                 origin_ref=origin_ref, require_origin=True), "补兵/改属性"
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
                commit=commit,
            )
    raw_person_changes = effect.get("人物变更")
    if raw_person_changes is not None:
        if not isinstance(raw_person_changes, list):
            raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：必须是 list")
        for idx, it in enumerate(raw_person_changes):
            if not isinstance(it, dict):
                raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：第 {idx} 项非 dict")
    person_changes = normalize_person_changes({"人物变更": raw_person_changes or []})
    csc = effect.get("character_status_changes")
    if not person_changes and isinstance(csc, list) and csc:
        for it in csc:
            if not isinstance(it, dict):
                # 全局严格（不静默）：非 dict 项直接抛错，不无声丢（CMR F7）。
                raise ValueError(f"{label} character_status_changes 含非法非 dict 项：{it!r}")
        status_person_changes = normalize_person_changes({"character_status_changes": csc})
        for item in status_person_changes:
            if isinstance(item, dict):
                item.pop("legacy_gate", None)
        results = _apply_person_changes(
            db,
            state,
            status_person_changes,
            content=effective_content(),
            registry=registry,
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
            external_transaction=not commit,
            origin_ref=origin_ref,
            require_origin=True,
        )
        _raise_on_rejected(results, "character_status_changes")
        if applied_person_changes is not None:
            applied_person_changes.extend(results)
    if person_changes:
        results = _apply_person_changes(
            db,
            state,
            person_changes,
            content=effective_content(),
            registry=registry,
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
            external_transaction=not commit,
            origin_ref=origin_ref,
            require_origin=True,
        )
        _raise_on_rejected(results, "人物变更")
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
_STRATEGIC_FOREIGN_NODE_PERSON_ANCHORS: Dict[str, frozenset[str]] = {
    "jisi_lubian": frozenset({"己巳", "喜峰口", "龙井关", "德胜门", "左安门"}),
    "dalingghe": frozenset({"大凌河", "祖大寿"}),
    "lindan_xiqian": frozenset({"林丹汗", "察哈尔", "蒙古", "青海", "漠南"}),
    "wuyin_lubian": frozenset({"戊寅", "墙子岭", "青山口", "巨鹿", "贾庄", "畿南"}),
    "songshan_battle": frozenset({"松锦", "松山", "锦州", "杏山", "塔山", "援锦"}),
    "luoyang_fallen": frozenset({"洛阳陷", "洛阳陷落", "攻陷洛阳", "福王", "朱常洵"}),
    "kaifeng_siege": frozenset({"开封三围", "围攻开封", "开封围城", "黄河决口", "决河"}),
    "beijing_fallen": frozenset({"甲申", "北京", "京师", "居庸关", "煤山"}),
}
_STRATEGIC_FOREIGN_NODE_DIRECT_EVENT_ANCHORS: Dict[str, frozenset[str]] = {
    "jisi_lubian": frozenset({"己巳"}),
    "dalingghe": frozenset({"大凌河"}),
    "lindan_xiqian": frozenset({"林丹汗", "察哈尔"}),
    "wuyin_lubian": frozenset({"戊寅"}),
    "songshan_battle": frozenset({"松锦", "援锦"}),
    "luoyang_fallen": frozenset({"洛阳陷"}),
    "kaifeng_siege": frozenset({"开封三围"}),
    "beijing_fallen": frozenset({"甲申", "北京陷", "李自成攻北京"}),
}
_STRATEGIC_FOREIGN_NODE_BATTLE_CONTEXT_ANCHORS = frozenset({
    "之变", "虏变", "入塞", "入寇", "犯阙", "战损", "战死", "战败", "战胜",
    "交战", "大战", "决战", "战果", "战事", "战役", "阵亡", "伤亡",
    "后金", "清军", "勤王", "围城", "攻城", "破关", "破口", "陷落", "失守",
    "大掠", "软判", "主力", "边墙", "逼京", "降金", "西迁", "城破", "决河",
    "流寇", "闯军", "大顺",
})
_STRATEGIC_FOREIGN_NODE_PERSON_ROLE_ANCHORS = frozenset({"替补", "主帅", "督师", "统帅", "主将"})
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
_STRATEGIC_ENTITY_OUTCOME_FIELDS: Dict[str, frozenset[str]] = {
    "regions": frozenset({"military_pressure", "controlled_by", "军事压力", "控制方", "控制"}),
    "armies": frozenset({
        "manpower", "morale", "supply", "loyalty", "commander", "controller", "owner_power",
        "station", "status", "人数", "兵力", "士气", "补给", "忠诚", "统帅", "主将",
        "控制", "归属", "驻地", "驻扎地", "状态",
    }),
    "powers": frozenset({
        "leverage", "military_strength", "supply", "威望", "威胁", "影响力",
        "实力", "兵势", "军势", "军事力量", "经济", "补给",
    }),
}
_STRATEGIC_NEW_ARMY_CONTEXT_ANCHORS = frozenset({
    "己巳", "戊寅", "松锦", "松山", "锦州", "入塞", "入寇", "后金", "清军",
    "建虏", "虏骑", "喜峰口", "龙井关", "遵化", "京畿", "边墙", "大凌河",
    "察哈尔", "林丹汗", "洛阳", "开封", "北京", "甲申", "闯军", "大顺",
})


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


def _strategic_event_outcome_targets(event_id: str) -> Dict[str, frozenset[str]]:
    return _STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS.get(
        event_id,
        {"regions": frozenset(), "armies": frozenset(), "characters": frozenset(), "powers": frozenset()},
    )


def _target_union(event_ids: set[str], target_key: str) -> set[str]:
    targets: set[str] = set()
    for event_id in event_ids:
        targets.update(_strategic_event_outcome_targets(event_id).get(target_key, frozenset()))
    return targets


def _unambiguous_unanchored_event_ids(event_ids: set[str]) -> set[str]:
    return set(event_ids) if len(event_ids) == 1 else set()


def _split_mapping_by_keys(
    raw: object,
    target_keys: set[str],
) -> tuple[Dict[str, object], Dict[str, object]]:
    if not isinstance(raw, dict):
        return {}, {}
    targeted: Dict[str, object] = {}
    other: Dict[str, object] = {}
    for key, value in raw.items():
        (targeted if str(key) in target_keys else other)[key] = value
    return targeted, other


def _person_change_name(item: Dict[str, object]) -> str:
    return str(
        item.get("name")
        or item.get("姓名")
        or item.get("character")
        or item.get("person")
        or ""
    ).strip()


def _canonicalize_person_change_names(
    changes: List[Dict[str, object]],
    content: Optional[GameContent],
    db: GameDB,
) -> List[Dict[str, object]]:
    if content is None:
        return changes
    from ming_sim.session import _find_existing_minister

    canonicalized: List[Dict[str, object]] = []
    for item in changes:
        name = _person_change_name(item)
        canon = _find_existing_minister(content, name, db) if name else None
        if canon and canon != name:
            copied = dict(item)
            copied["name"] = canon
            canonicalized.append(copied)
        else:
            canonicalized.append(item)
    return canonicalized


def _is_strategic_person_result_change(item: Dict[str, object]) -> bool:
    return str(item.get("动作") or item.get("action") or "").strip() != "评定"


def _person_change_reason_text(item: Dict[str, object]) -> str:
    parts = [
        str(item.get(key) or "")
        for key in ("reason", "原因", "event_id", "source_event_id", "origin_ref", "derived_from", "narrative", "summary", "说明")
    ]
    return " ".join(part.strip() for part in parts if part)


def _change_reason_text(raw_changes: object) -> str:
    if not isinstance(raw_changes, dict):
        return ""
    parts = [
        str(raw_changes.get(key) or "")
        for key in ("reason", "原因", "event_id", "source_event_id", "origin_ref", "derived_from", "narrative", "summary", "说明")
    ]
    return " ".join(part.strip() for part in parts if part)


def _change_mentions_strategic_event(raw_changes: object, event_id: str) -> bool:
    reason_text = _change_reason_text(raw_changes)
    anchors = _STRATEGIC_FOREIGN_NODE_PERSON_ANCHORS.get(event_id, frozenset())
    if event_id in reason_text:
        return True
    direct_anchors = _STRATEGIC_FOREIGN_NODE_DIRECT_EVENT_ANCHORS.get(event_id, frozenset())
    if any(anchor in reason_text for anchor in direct_anchors):
        return True
    return (
        any(anchor in reason_text for anchor in anchors)
        and any(anchor in reason_text for anchor in _STRATEGIC_FOREIGN_NODE_BATTLE_CONTEXT_ANCHORS)
    )


def _change_has_strategic_outcome_field(raw_changes: object, target_key: str) -> bool:
    if not isinstance(raw_changes, dict):
        return False
    fields = _STRATEGIC_ENTITY_OUTCOME_FIELDS.get(target_key, frozenset())
    return any(str(key) in fields for key in raw_changes.keys())


def _strategic_entity_delta_event_ids(
    entity_id: str,
    raw_changes: object,
    target_key: str,
    strategic_event_ids: set[str],
    unanchored_event_ids: set[str] | None = None,
) -> set[str]:
    unanchored_event_ids = unanchored_event_ids or set()
    event_ids: set[str] = set()
    for event_id in strategic_event_ids:
        targets = _strategic_event_outcome_targets(event_id)
        if entity_id not in targets[target_key]:
            continue
        if _change_mentions_strategic_event(raw_changes, event_id):
            event_ids.add(event_id)
            continue
        if event_id in unanchored_event_ids and _change_has_strategic_outcome_field(raw_changes, target_key):
            event_ids.add(event_id)
    return event_ids


def _split_strategic_entity_deltas(
    raw: object,
    target_key: str,
    strategic_event_ids: set[str],
    unanchored_event_ids: set[str] | None = None,
) -> tuple[Dict[str, object], Dict[str, object]]:
    if not isinstance(raw, dict):
        return {}, {}
    strategic: Dict[str, object] = {}
    other: Dict[str, object] = {}
    for entity_id, raw_changes in raw.items():
        if _strategic_entity_delta_event_ids(
            str(entity_id),
            raw_changes,
            target_key,
            strategic_event_ids,
            unanchored_event_ids,
        ):
            strategic[entity_id] = raw_changes
        else:
            other[entity_id] = raw_changes
    return strategic, other


def _entity_deltas_for_strategic_event(
    raw: object,
    target_key: str,
    event_id: str,
    *,
    allow_unanchored: bool = True,
) -> Dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    unanchored_event_ids = {event_id} if allow_unanchored else set()
    return {
        entity_id: raw_changes
        for entity_id, raw_changes in raw.items()
        if event_id in _strategic_entity_delta_event_ids(
            str(entity_id),
            raw_changes,
            target_key,
            {event_id},
            unanchored_event_ids,
        )
    }


def _new_army_has_strategic_shape(item: Dict[str, object]) -> bool:
    owner_power = str(item.get("owner_power") or item.get("controller") or "").strip().lower()
    if owner_power and owner_power not in {"ming", "明", "明军"}:
        return True
    blob = " ".join(
        str(item.get(key) or "")
        for key in ("id", "name", "station", "status", "commander", "troop_type", "owner_power")
    )
    return any(anchor in blob for anchor in _STRATEGIC_NEW_ARMY_CONTEXT_ANCHORS)


def _strategic_new_army_result_event_ids(
    item: object,
    strategic_event_ids: set[str],
    unanchored_event_ids: set[str] | None = None,
) -> set[str]:
    if not isinstance(item, dict):
        return set()
    unanchored_event_ids = unanchored_event_ids or set()
    return {
        event_id
        for event_id in strategic_event_ids
        if _change_mentions_strategic_event(item, event_id)
        or (event_id in unanchored_event_ids and _new_army_has_strategic_shape(item))
    }


def _split_strategic_new_armies(
    raw: object,
    strategic_event_ids: set[str],
    unanchored_event_ids: set[str] | None = None,
) -> tuple[List[object], List[object]]:
    if not isinstance(raw, list):
        return [], []
    strategic: List[object] = []
    other: List[object] = []
    for item in raw:
        if _strategic_new_army_result_event_ids(item, strategic_event_ids, unanchored_event_ids):
            strategic.append(item)
        else:
            other.append(item)
    return strategic, other


def _new_armies_for_strategic_event(
    raw: object,
    event_id: str,
    *,
    allow_unanchored: bool = True,
) -> List[object]:
    if not isinstance(raw, list):
        return []
    unanchored_event_ids = {event_id} if allow_unanchored else set()
    return [
        item
        for item in raw
        if event_id in _strategic_new_army_result_event_ids(item, {event_id}, unanchored_event_ids)
    ]


def _strategic_event_target_commanders(db: GameDB, event_id: str) -> set[str]:
    target_armies = _strategic_event_outcome_targets(event_id).get("armies", frozenset())
    if not target_armies:
        return set()
    rows = []
    for army_id in sorted(target_armies):
        row = db.conn.execute(
            "SELECT commander FROM armies WHERE id=?",
            (army_id,),
        ).fetchone()
        if row is not None:
            rows.append(row)
    return {str(row["commander"] or "").strip() for row in rows if str(row["commander"] or "").strip()}


def _strategic_person_matches_event_target(
    name: str,
    event_id: str,
    db: GameDB,
    reason_text: str,
) -> bool:
    if not name:
        return False
    targets = _strategic_event_outcome_targets(event_id)
    if name in targets.get("characters", frozenset()):
        return True
    if name in _strategic_event_target_commanders(db, event_id):
        return True
    return any(anchor in reason_text for anchor in _STRATEGIC_FOREIGN_NODE_PERSON_ROLE_ANCHORS)


def _strategic_person_result_event_ids(
    item: Dict[str, object],
    strategic_event_ids: set[str],
    db: GameDB,
) -> set[str]:
    if not _is_strategic_person_result_change(item):
        return set()
    name = _person_change_name(item)
    reason_text = _person_change_reason_text(item)
    event_ids: set[str] = set()
    for event_id in strategic_event_ids:
        anchors = _STRATEGIC_FOREIGN_NODE_PERSON_ANCHORS.get(event_id, frozenset())
        if (
            (event_id in reason_text or any(anchor in reason_text for anchor in anchors))
            and _strategic_person_matches_event_target(name, event_id, db, reason_text)
        ):
            event_ids.add(event_id)
    return event_ids


def _split_strategic_person_result_changes(
    changes: List[Dict[str, object]],
    strategic_event_ids: set[str],
    db: GameDB,
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    strategic: List[Dict[str, object]] = []
    other: List[Dict[str, object]] = []
    for item in changes:
        if _strategic_person_result_event_ids(item, strategic_event_ids, db):
            strategic.append(item)
        else:
            other.append(item)
    return strategic, other


def _event_result_delta_event_ids(
    strategic_event_ids: set[str],
    strategic_event_pool_ids: set[str],
    extracted: Dict[str, object],
    person_changes: List[Dict[str, object]],
    db: GameDB,
) -> set[str]:
    unanchored_event_ids = _unambiguous_unanchored_event_ids(strategic_event_pool_ids)
    region_result_event_ids: set[str] = set()
    if isinstance(extracted.get("region_delta"), dict):
        for region_id, raw_changes in (extracted.get("region_delta") or {}).items():
            region_result_event_ids.update(
                _strategic_entity_delta_event_ids(
                    str(region_id),
                    raw_changes,
                    "regions",
                    strategic_event_ids,
                    unanchored_event_ids,
                )
            )
    army_result_event_ids: set[str] = set()
    if isinstance(extracted.get("army_delta"), dict):
        for army_id, raw_changes in (extracted.get("army_delta") or {}).items():
            army_result_event_ids.update(
                _strategic_entity_delta_event_ids(
                    str(army_id),
                    raw_changes,
                    "armies",
                    strategic_event_ids,
                    unanchored_event_ids,
                )
            )
    power_result_event_ids: set[str] = set()
    if isinstance(extracted.get("power_updates"), dict):
        for power_id, raw_changes in (extracted.get("power_updates") or {}).items():
            power_result_event_ids.update(
                _strategic_entity_delta_event_ids(
                    str(power_id),
                    raw_changes,
                    "powers",
                    strategic_event_ids,
                    unanchored_event_ids,
                )
            )
    person_result_event_ids: set[str] = set()
    for item in person_changes:
        person_result_event_ids.update(_strategic_person_result_event_ids(item, strategic_event_ids, db))
    new_army_result_event_ids: set[str] = set()
    if isinstance(extracted.get("new_armies"), list):
        for item in extracted.get("new_armies") or []:
            new_army_result_event_ids.update(
                _strategic_new_army_result_event_ids(item, strategic_event_ids, unanchored_event_ids)
            )
    result_ids: set[str] = set()
    for event_id in strategic_event_ids:
        if (
            event_id in region_result_event_ids
            or event_id in army_result_event_ids
            or event_id in power_result_event_ids
            or event_id in person_result_event_ids
            or event_id in new_army_result_event_ids
        ):
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


def normalize_event_outcome_labels_or_error(
    extracted: Dict[str, object],
    content: GameContent,
    db: Optional[GameDB] = None,
    state: Optional[GameState] = None,
    candidate_event_ids: Optional[set[str]] = None,
) -> None:
    """Normalize closed historical-event outcome labels in-place, or fail loud.

    This is the extractor-side whitelist gate for ADR0014/#193.  Retry/fail-loud
    applies only to strategic events that are actually landable now: the issues
    extractor selected a current candidate event and another ledger in the same
    envelope carries a material strategic result for that event.  A hallucinated
    static event id that the issue adapter would reject later must not abort the
    whole extractor round and lose unrelated module deltas.
    """
    event_ids = _event_pool_ids_for_strategic_foreign_nodes(extracted, content)
    if not event_ids:
        return
    if db is not None:
        new_person_changes = normalize_person_changes({"人物变更": extracted.get("人物变更") or []})
        legacy_person_changes = [] if new_person_changes else normalize_person_changes({
            "appointments": extracted.get("appointments") or [],
            "character_status_changes": extracted.get("character_status_changes") or [],
            "character_power_changes": extracted.get("character_power_changes") or [],
            "office_changes": extracted.get("office_changes") or [],
        })
        person_changes = _canonicalize_person_change_names(
            new_person_changes or legacy_person_changes,
            content,
            db,
        )
        result_event_ids = _event_result_delta_event_ids(
            set(_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS),
            event_ids,
            extracted,
            person_changes,
            db,
        )
        event_ids &= result_event_ids
    if candidate_event_ids is None and db is not None and state is not None:
        candidate_event_ids = {candidate.id for candidate in gather_candidate_events(state, db)}
    if candidate_event_ids is not None:
        event_ids &= set(candidate_event_ids)
    if not event_ids:
        return
    raw_outcomes = extracted.get("事件结局")
    outcomes: Dict[str, object] = dict(raw_outcomes) if isinstance(raw_outcomes, dict) else {}
    for event_id in sorted(event_ids):
        normalized, error = _strategic_event_outcome_label_or_error(event_id, extracted, content)
        if error:
            raise ValueError(error)
        if normalized:
            outcomes[event_id] = normalized
    extracted["事件结局"] = outcomes


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
    legacy_person_mode: bool,
) -> str:
    """ADR0014：战略事件战果是同一信封，落库前先拦整组可预见拒收项。"""
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
        raw_changes = region_deltas.get("beizhili")
        if not isinstance(raw_changes, dict):
            return ""
        controlled_by = None
        for raw_field, value in raw_changes.items():
            field = REGION_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
            if field == "controlled_by":
                controlled_by = value
                break
        if controlled_by is None:
            return ""
        new_controller = str(controlled_by).strip()
        if new_controller and new_controller != "ming":
            return (
                f"战略/外敌事件「{event_title or event_id}」事件结局「{outcome_label}」"
                f"与北直隶控制权战果矛盾：{new_controller}"
            )
        return ""

    outcome_profile_error = _jisi_outcome_profile_error()
    if outcome_profile_error:
        return outcome_profile_error

    for region_id, raw_changes in region_deltas.items():
        row = db.conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
        if row is None:
            return f"战略/外敌事件「{event_title or event_id}」战果引用未入库地区：{region_id}"
        if not isinstance(raw_changes, dict):
            return f"战略/外敌事件「{event_title or event_id}」地区战果须为对象：{region_id}"
        if not _change_mentions_strategic_event(raw_changes, event_id):
            return f"战略/外敌事件「{event_title or event_id}」地区战果缺 reason/原因 事件锚点：{region_id}"
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
                controller = str(value).strip()[:160] if value is not None else ""
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

    for army_id, raw_changes in army_deltas.items():
        row = db.conn.execute("SELECT * FROM armies WHERE id = ?", (army_id,)).fetchone()
        if row is None:
            return f"战略/外敌事件「{event_title or event_id}」战果引用未入库军队：{army_id}"
        if not isinstance(raw_changes, dict):
            return f"战略/外敌事件「{event_title or event_id}」军队战果须为对象：{army_id}"
        if not _change_mentions_strategic_event(raw_changes, event_id):
            return f"战略/外敌事件「{event_title or event_id}」军队战果缺 reason/原因 事件锚点：{army_id}"
        for raw_field, value in raw_changes.items():
            field = ARMY_FIELD_ALIASES.get(str(raw_field).strip(), str(raw_field).strip())
            if field in ("reason", "origin_ref"):
                continue
            if field not in army_valid_fields:
                return f"战略/外敌事件「{event_title or event_id}」战果引用非法军队字段：{raw_field}"
            if field in army_numeric_fields:
                err = _int_delta_error("army", army_id, raw_field, value)
                if err:
                    return err
            err = _army_noop_error(army_id, row, raw_field, value)
            if err:
                return err

    if power_updates:
        for power_id, raw_changes in power_updates.items():
            if not isinstance(raw_changes, dict):
                return f"战略/外敌事件「{event_title or event_id}」势力战果须为对象：{power_id}"
            if not _change_mentions_strategic_event(raw_changes, event_id):
                return f"战略/外敌事件「{event_title or event_id}」势力战果缺 reason/原因 事件锚点：{power_id}"
        power_results: List[Dict[str, object]] = []
        clean_power_updates = {
            power_id: {key: value for key, value in raw_changes.items() if key != "origin_ref"}
            for power_id, raw_changes in power_updates.items()
        }
        db.conn.execute("SAVEPOINT strategic_power_result_preflight")
        try:
            power_results = db.apply_power_deltas(
                state,
                clean_power_updates,
                commit=False,
            )
        finally:
            db.conn.execute("ROLLBACK TO SAVEPOINT strategic_power_result_preflight")
            db.conn.execute("RELEASE SAVEPOINT strategic_power_result_preflight")
        for result in power_results:
            if result.get("rejected"):
                return (
                    f"战略/外敌事件「{event_title or event_id}」势力战果拒收："
                    f"{result.get('reason') or result.get('category') or ''}"
                )
        if not any(_strategic_result_item_has_material_world_state(result) for result in power_results):
            power_id = next(iter(power_updates))
            return _noop_error("power", str(power_id), "power_updates", power_updates.get(power_id))

    if person_changes:
        for item in person_changes:
            action = str(item.get("动作") or item.get("action") or "").strip()
            name = _person_change_name(item)
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
                "SELECT location, transit_to FROM characters WHERE name = ?",
                (name,),
            ).fetchone()
            if row is None:
                continue
            new_location = str(item.get("location") or "").strip()
            new_transit_to = str(item.get("transit_to") or "").strip()
            old_location = str(row["location"] or "")
            old_transit_to = str(row["transit_to"] or "")
            target_location = new_location or old_location
            if target_location == old_location and new_transit_to == old_transit_to:
                return _noop_error(
                    "person",
                    name,
                    "行止",
                    {"location": target_location, "transit_to": new_transit_to},
                )
        snapshot = _snapshot_person_write_state(db, content)
        results: List[Dict[str, object]] = []
        db.conn.execute("SAVEPOINT strategic_person_result_preflight")
        try:
            results = _apply_person_changes(
                db,
                state,
                person_changes,
                content=content,
                registry=None,
                llm_config=llm_config,
                allow_legacy_partial_power=legacy_person_mode,
                external_transaction=True,
            )
        finally:
            db.conn.execute("ROLLBACK TO SAVEPOINT strategic_person_result_preflight")
            db.conn.execute("RELEASE SAVEPOINT strategic_person_result_preflight")
            _restore_person_content_from_snapshot(content, snapshot)
        for result in results:
            if result.get("rejected"):
                return (
                    f"战略/外敌事件「{event_title or event_id}」人物战果拒收："
                    f"{result.get('name') or ''}{result.get('动作') or ''} {result.get('reason') or ''}"
                )
            backlash_results = result.get("backlash_results")
            if isinstance(backlash_results, list):
                for backlash_result in backlash_results:
                    if isinstance(backlash_result, dict) and backlash_result.get("rejected"):
                        return (
                            f"战略/外敌事件「{event_title or event_id}」人物战果反噬拒收："
                            f"{backlash_result.get('reason') or backlash_result.get('category') or ''}"
                        )

    for raw in new_armies:
        if not isinstance(raw, dict):
            return f"战略/外敌事件「{event_title or event_id}」新军战果须为对象"
        if not _change_mentions_strategic_event(raw, event_id):
            return f"战略/外敌事件「{event_title or event_id}」新军战果缺 reason/原因 事件锚点"
        item = {ARMY_FIELD_ALIASES.get(str(k).strip(), str(k).strip()): v for k, v in raw.items()}
        army_id = str(item.get("id") or "").strip()
        if not army_id:
            return f"战略/外敌事件「{event_title or event_id}」新军战果缺 id"
        army_name = str(item.get("name") or army_id).strip()
        existing_army = db.conn.execute(
            "SELECT id, name FROM armies WHERE id = ? OR name = ?",
            (army_id, army_name),
        ).fetchone()
        if existing_army is not None:
            return (
                f"战略/外敌事件「{event_title or event_id}」新军战果 id/name 已存在："
                f"{army_id}/{army_name}（扩编既有军队请走 army_delta）"
            )
        owner = str(item.get("owner_power") or "ming").strip() or "ming"
        if db.conn.execute("SELECT 1 FROM powers WHERE id = ?", (owner,)).fetchone() is None:
            return f"战略/外敌事件「{event_title or event_id}」新军战果 owner_power 未入库：{owner}"
        if "manpower" not in item:
            return f"战略/外敌事件「{event_title or event_id}」新军战果缺 manpower"
        err = _int_delta_error("new_army", army_id, "manpower", item.get("manpower"))
        if err:
            return err
        manpower = int(item.get("manpower"))
        if manpower <= 0:
            return (
                f"战略/外敌事件「{event_title or event_id}」新军战果 manpower 须为正整数："
                f"{manpower}"
            )
        for field in army_numeric_fields:
            if field == "manpower":
                continue
            if field in item and item.get(field) is not None:
                err = _int_delta_error("new_army", army_id, field, item.get(field))
                if err:
                    return err

    origin_items = (
        [("地区", item) for item in region_deltas.values()]
        + [("军队", item) for item in army_deltas.values()]
        + [("势力", item) for item in power_updates.values()]
        + [("人物", item) for item in person_changes]
        + [("新军", item) for item in new_armies]
    )
    for kind, item in origin_items:
        origin_ref = item.get("origin_ref") if isinstance(item, dict) else None
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            return (
                f"战略/外敌事件「{event_title or event_id}」{kind}战果来源拒收："
                f"{origin_error.get('reason') or origin_error.get('category') or ''}"
            )

    return ""


def _strategic_result_item_has_material_world_state(item: Dict[str, object]) -> bool:
    if item.get("rejected"):
        return False
    if item.get("created"):
        return True
    for old_key, new_key in (
        ("old", "new"),
        ("old_status", "status"),
        ("old_office", "new_office"),
        ("old_office_type", "office_type"),
        ("old_loyalty", "new_loyalty"),
        ("old_power", "new_power"),
    ):
        if old_key in item and new_key in item and str(item.get(old_key)) != str(item.get(new_key)):
            return True
    action = str(item.get("动作") or item.get("action") or "").strip()
    if action in {"处置", "罢黜"} and item.get("status"):
        return True
    if action in {"任命", "调任", "册封"} and (
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
        # 形对：_apply_issue_entities 只落 list 的 new_armies/人物变更/character_status_changes、
        # dict 的 army_delta；畸形容器（字符串/错类型）不算真配对，不该消音告警（PR#107 codex）。
        has_army = _nonempty_list(effect.get("new_armies")) or _nonempty_dict(effect.get("army_delta"))
        has_office = (
            _nonempty_list(effect.get("人物变更"))
            or _nonempty_list(effect.get("character_status_changes"))
        )
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
    ongoing = loads_effect_dict(_g("ongoing_effects", "{}"))
    for w in _initiative_resolve_pairing_warnings(str(_g("title", "") or ""), tags, ongoing, effect):
        tlog(f"[pairing] {w}")
        if sink is not None:
            sink.append(w)


def apply_issue_tracker_output(
    db: GameDB,
    state: GameState,
    tracker_output: Dict[str, object],
    llm_config: Any = None,
    content=None,
    pending_person_changes_for_gates: Optional[List[Dict[str, object]]] = None,
    allow_legacy_partial_power_for_gates: bool = False,
    candidate_event_ids_at_input: Optional[set[str]] = None,
    candidate_event_ids_authoritative: bool = False,
    event_result_delta_event_ids: Optional[set[str]] = None,
    defer_event_trigger_ids: Optional[set[str]] = None,
) -> Dict[str, object]:
    touched_ids: set = set()
    applied_advances: List[Dict[str, object]] = []
    pairing_warnings: List[str] = []  # #45/#46 国策结案实体后果强制配对告警（warn-only）
    applied_new: List[Dict[str, object]] = []
    applied_cancels: List[Dict[str, object]] = []
    # issue 实体后果的容忍拒收项（issue_strict=False）——挂进返回 summary,
    # S0 桥接一层下探自动收进 rejection_reports（留痕不蒸发,cmr S2 r2）。
    entity_rejections: List[Dict[str, object]] = []
    issue_person_changes: List[Dict[str, object]] = []
    runtime_content = content if content is not None else _ctx()
    event_by_id = runtime_content.event_by_id
    external_transaction = db.conn.in_transaction
    commit_now = not external_transaction
    if external_transaction:
        _register_runtime_rollback_snapshot(db, state, runtime_content)
    candidate_snapshot_authoritative = (
        candidate_event_ids_at_input is not None and candidate_event_ids_authoritative
    )
    candidate_event_ids = (
        set(candidate_event_ids_at_input)
        if candidate_event_ids_at_input is not None
        else {candidate.id for candidate in gather_candidate_events(state, db)}
    )
    event_result_delta_event_ids = set(event_result_delta_event_ids or set())
    defer_event_trigger_ids = set(defer_event_trigger_ids or set())
    consumed_event_ids: set[str] = set()
    current_candidate_event_ids: set[str] = set()
    candidates_dirty = True
    shared_shadow_rows: Optional[Dict[str, Dict[str, str]]] = None
    shared_power_shadow_rows: Optional[Dict[str, Dict[str, int]]] = None
    shared_valid_regions: Optional[set[str]] = None
    has_event_pool_new_issue = any(
        isinstance(item, dict) and str(item.get("origin_kind") or "").lower() == "event_pool"
        for item in (tracker_output.get("new_issues", []) or [])
    )
    if pending_person_changes_for_gates and has_event_pool_new_issue:
        shared_shadow_rows = _load_pending_gate_shadow_rows(db)
        shared_power_shadow_rows = _load_pending_gate_power_shadow_rows(db)
        shared_valid_regions = _load_pending_gate_valid_regions(db)

    # 1) advances（ADR 0008 决定1：LLM 脏数据逐项拒收留痕，不裸 continue 静默丢；db.advance_issue
    #    的代码/DB 异常上抛 SettlementAbort，同 close_issues / new_issues 段，#63）
    for adv in tracker_output.get("advances", []) or []:
        if not isinstance(adv, dict):
            # 非 dict 项（advances:[null]/标量，_sanitize 不清列表项可达）：adv.get 抛 AttributeError
            # 崩整月——逐项拒收守门（同 close_issues 非 dict 守卫）。注：真实 settle 路
            # validate_delta_shape 已前置 abort 非 dict list 项（结构畸形＝响亮失败防半落库），故此
            # 守卫是 defense-in-depth——直接调 apply / 绕过 validate 时才生效（codex advances r2 P2：
            # 非 dict 主路径走 validate abort、非逐项拒收，是 validate 层「结构畸形前置 abort」vs
            # 「值脏逐项拒收」的两层分工；改 validate 让非 dict 亦逐项拒收＝跨所有 list 段的设计决策，
            # defer #63 validate 层通用切片）。
            applied_advances.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"advances 条目非对象（应为 dict）：{adv!r}", "item": adv,
            })
            continue
        try:
            # _parse_sqlite_id：非整数/bool/float/超 SQLite 64-bit → ValueError（含 10**100 这类
            # int() 过得了但绑定 SQLite 抛 OverflowError 的脏 id，避免上抛崩整月，同 close_issues）。
            issue_id = _parse_sqlite_id(adv.get("issue_id"))
        except (TypeError, ValueError):
            applied_advances.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"advances issue_id 非法（非整数或超 SQLite 范围）：{adv.get('issue_id')!r}",
                "item": adv,
            })
            continue
        try:
            # delta_bar/inertia_delta 用 _strict_int（拒 bool/float/inf/非数）：原裸 int() 在此 try
            # 之外，int("高")/int(1e309) 直接逃逸成 SettlementAbort、int(True)=1 静默截断。缺省/null → 0。
            _db_raw = adv.get("delta_bar")
            delta_bar = _strict_int(0 if _db_raw is None else _db_raw)
            _id_raw = adv.get("inertia_delta")
            inertia_delta = _strict_int(0 if _id_raw is None else _id_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            applied_advances.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"advances 字段强转失败（delta_bar/inertia_delta 脏数据）：{exc}",
                "item": adv,
            })
            continue
        stage_text = str(adv.get("stage_text") or "")[:120]
        narrative = str(adv.get("narrative") or "")[:400]
        # 先验 issue 存在且 active（与 db.advance_issue 的 None 条件 row is None / status!=active 一致）：
        # 未找到/已非 active → missing_ref 逐项拒收留痕（陈旧/幻觉引用，同 close_issues None 归类，#63），
        # 不裸 continue 静默丢。**必须先验、再应用 metric**：原序先 _apply_metric_dict（就地 mutate
        # state.metrics）后判 None，会让拒收项的 metric_delta 副作用已落 state、与「未落地」矛盾且结算
        # commit 无 rollback（cmr advances r1 codex high + claude concur）。
        _chk = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
        if _chk is None or _chk["status"] != "active":
            applied_advances.append({
                "rejected": True, "category": "missing_ref",
                "reason": f"advances 引用未找到或已非 active 的 issue {issue_id}", "item": adv,
            })
            continue
        # 确认 active 后才应用 metric（单线程内 _apply_metric_dict 不改 issue 表 status，故下方
        # advance_issue 必非 None——pre-check 与其内部判定同条件）。
        metric_delta_raw = adv.get("metric_delta") or {}
        applied_metrics = _apply_metric_dict(state, metric_delta_raw if isinstance(metric_delta_raw, dict) else {}, db=db)
        new_row = db.advance_issue(
            state, issue_id,
            trigger_kind="decree",
            delta_bar=delta_bar,
            stage_text=stage_text,
            narrative=narrative,
            metric_delta=applied_metrics,
            inertia_delta=inertia_delta,
            commit=not external_transaction,
        )
        touched_ids.add(issue_id)
        # 终结结算：bar 自然推到 100/0 触发的 resolved/failed，与 close_issues 一样落终结效果（含建筑）
        if new_row["status"] == "resolved":
            effect = loads_effect_dict(new_row["effect_on_resolve"])
            _emit_pairing_warnings(new_row, effect, pairing_warnings)
            parent_origin_ref = _canonical_issue_origin(db, new_row)
            _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
            entity_rejections.extend(r for r in _apply_economy_list(
                db, state, effect.get("economy") or [], commit=commit_now,
                origin_ref=parent_origin_ref,
            ) if r.get("rejected"))  # economy 拒收不蒸发（#14）
            entity_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}, commit=commit_now).rejections)  # 派系拒收不蒸发（#14/#63 cmr r2）
            _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}结案", commit=commit_now, origin_ref=parent_origin_ref)
            entity_rejections.extend(
                _apply_issue_entities(
                    db,
                    state,
                    effect,
                    f"局势#{issue_id}结案",
                    content=runtime_content,
                    llm_config=llm_config,
                    applied_person_changes=issue_person_changes,
                    commit=commit_now,
                    origin_ref=parent_origin_ref,
                ))
            _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]), commit=commit_now)
        elif new_row["status"] == "failed":
            effect = loads_effect_dict(new_row["effect_on_fail"])
            parent_origin_ref = _canonical_issue_origin(db, new_row)
            _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
            entity_rejections.extend(r for r in _apply_economy_list(
                db, state, effect.get("economy") or [], commit=commit_now,
                origin_ref=parent_origin_ref,
            ) if r.get("rejected"))  # economy 拒收不蒸发（#14）
            entity_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}, commit=commit_now).rejections)  # 派系拒收不蒸发（#14/#63 cmr r2）
            _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}失败", commit=commit_now, origin_ref=parent_origin_ref)
            entity_rejections.extend(
                _apply_issue_entities(
                    db,
                    state,
                    effect,
                    f"局势#{issue_id}失败",
                    content=runtime_content,
                    llm_config=llm_config,
                    applied_person_changes=issue_person_changes,
                    commit=commit_now,
                    origin_ref=parent_origin_ref,
                ))
            _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]), commit=commit_now)
        applied_advances.append({
            "issue_id": issue_id,
            "title": new_row["title"],
            "from_value": int(new_row["bar_value"]) - delta_bar,
            "to_value": int(new_row["bar_value"]),
            "stage_text": new_row["stage_text"],
            "status": new_row["status"],
            "narrative": narrative,
        })

    # 2) new_issues：接两种来源——
    #    decree     —— 玩家诏书强推，由 LLM 给字段新立 issue
    #    event_pool —— 预设事件（EVENTS/SEED_EVENTS）被推演判定触发，按预设 event 立 issue
    #    其它来源一律拒。
    initiative_active = db.count_active_initiatives()
    for ni in tracker_output.get("new_issues", []) or []:
        if not isinstance(ni, dict):
            # 非 dict 项（new_issues:[null]/标量）：ni.get 会抛 AttributeError。真实 settle 路
            # validate_delta_shape 已在 apply 前拦非 dict list 项，此为 defense-in-depth（直接调
            # apply_issue_tracker_output / 绕过 validate 时生效）——逐项拒收，不让坏项带走整批
            # （ADR 0008 决定 1，同 close_issues 非 dict 守卫，cmr ni r1 Claude）。
            applied_new.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"new_issues 条目非对象（应为 dict）：{ni!r}", "item": ni,
            })
            continue
        title = str(ni.get("title") or "")
        origin_kind = str(ni.get("origin_kind") or "").lower()
        if origin_kind == "event_pool":
            # 预设事件触发：id 必须是真实预设 event，照预设字段立 issue（不用 LLM 给的字段）
            event_id = str(ni.get("id") or ni.get("origin_ref") or "").strip()
            ev = event_by_id.get(event_id)
            if ev is None:
                print(f"[INFO] new_issue 已拒：event_pool id={event_id!r} 非预设事件，疑似臆造。")
                applied_new.append({"id": event_id, "title": title or event_id, "rejected": True, "reason": "event_pool id 非预设事件"})
                continue
            if getattr(ev, "auto_trigger", False):
                # auto_trigger 事件只能程序硬触发，LLM 不准从候选池立项
                print(f"[INFO] new_issue 已拒：event {event_id} 标了 auto_trigger，只能程序硬触发。")
                applied_new.append({"id": ev.id, "title": ev.title, "rejected": True, "reason": "auto_trigger 事件仅程序可触发"})
                continue
            if db.event_terminal_state(ev.id) == "expired":
                print(f"[INFO] new_issue 已拒：event {event_id} 已过期终态，不再从 event_pool 立项。")
                applied_new.append({"id": ev.id, "title": ev.title, "rejected": True, "reason": "事件已过期终态"})
                continue
            if (
                ev.id not in candidate_event_ids
                or ev.id in consumed_event_ids
            ):
                # LLM 只能从本回合候选池中挑选事件；落库端重验窗口、trigger_gate 与已触发状态，
                # 避免陈旧/伪造 id 穿透候选层后直接应用确定性后果（#203 CMR）。
                print(f"[INFO] new_issue 已拒：事件 {event_id} 当前未进 event_pool 候选池。")
                applied_new.append({
                    "id": ev.id,
                    "title": ev.title,
                    "rejected": True,
                    "reason": "事件当前未进候选池（窗口/前提门/已触发不满足）",
                })
                continue
            terminal_state = db.event_terminal_state(ev.id)
            if terminal_state:
                terminal_reason = {
                    "obsolete": "事件已作废终态",
                    "avoided": "事件已避过终态",
                    "triggered": "事件已触发终态",
                }.get(str(terminal_state), f"事件已有终态：{terminal_state}")
                print(f"[INFO] new_issue 已拒：event {event_id} 已有终态 {terminal_state!r}，不再从 event_pool 立项。")
                applied_new.append({"id": ev.id, "title": ev.title, "rejected": True, "reason": terminal_reason})
                continue
            # 重查候选：级联作废 / 新满足前提门的事件可能新进/退出候选池。
            # 权威快照（authoritative）只增不减——union 进新候选、不缩窄初始绑定（#399 cmr R1 codex P2）；
            # 非权威快照额外过滤——advances/前置事件效果关门后，已退出候选的事件不得沿用旧快照触发。
            if candidates_dirty:
                current_candidate_event_ids = {candidate.id for candidate in gather_candidate_events(state, db)}
                candidates_dirty = False
                if candidate_snapshot_authoritative:
                    candidate_event_ids |= current_candidate_event_ids
            if not candidate_snapshot_authoritative and ev.id not in current_candidate_event_ids:
                print(f"[INFO] new_issue 已拒：事件 {event_id} 当前未进 event_pool 候选池。")
                applied_new.append({
                    "id": ev.id,
                    "title": ev.title,
                    "rejected": True,
                    "reason": "事件当前未进候选池（窗口/前提门/已触发不满足）",
                })
                continue
            if _pending_person_changes_block_event_gate(
                ev,
                pending_person_changes_for_gates or [],
                db,
                allow_legacy_partial_power=allow_legacy_partial_power_for_gates,
                content=runtime_content,
                shadow_rows=shared_shadow_rows,
                power_shadow_rows=shared_power_shadow_rows,
                valid_regions=shared_valid_regions,
            ):
                print(f"[INFO] new_issue 已拒：事件 {event_id} 被同回合人物变更阻断。")
                applied_new.append({
                    "id": ev.id,
                    "title": ev.title,
                    "rejected": True,
                    "reason": "事件当前未进候选池（同回合人物变更后前提门不满足）",
                })
                continue
            if (
                _is_strategic_foreign_node_event(ev)
                and ev.id not in event_result_delta_event_ids
            ):
                print(f"[INFO] new_issue 已拒：战略/外敌事件 {event_id} 缺世界状态主账结果。")
                applied_new.append({
                    "id": ev.id,
                    "title": ev.title,
                    "rejected": True,
                    "reason": "战略/外敌战事缺世界状态主账结果（地区/军队/人物变更/新建军队）",
                })
                continue
            if ev.event_type != "situation":
                if ev.id in defer_event_trigger_ids:
                    consumed_event_ids.add(ev.id)
                    candidates_dirty = True
                    print(f"[INFO] new_issue 已接收：事件 {event_id} 为 {ev.event_type}，待软判结果落主账后记触发。")
                    applied_new.append({
                        "id": ev.id,
                        "title": ev.title,
                        "rejected": False,
                        "deferred_trigger": True,
                        "reason": f"event_type={ev.event_type} 待软判结果落主账后记触发",
                    })
                    continue
                if ev.effect_on_trigger:
                    entity_rejections.extend(
                        _apply_issue_entities(
                            db,
                            state,
                            ev.effect_on_trigger,
                            f"事件#{ev.id}触发",
                            content=runtime_content,
                            llm_config=llm_config,
                            applied_person_changes=issue_person_changes,
                            commit=commit_now,
                        )
                    )
                db.mark_event_triggered(state, ev.id, commit=not external_transaction)
                apply_event_cascading_invalidations(state, db, commit=not external_transaction)
                consumed_event_ids.add(ev.id)
                candidates_dirty = True
                print(f"[INFO] new_issue 已拒：事件 {event_id} 为 {ev.event_type}，不转 issue。")
                applied_new.append({"id": ev.id, "title": ev.title, "rejected": False, "reason": f"event_type={ev.event_type} 已记为触发"})
                continue
            issue_id = event_to_issue(db, state, ev, commit=not external_transaction)
            if issue_id is None:
                # event_to_issue 移除 broad except 后，返回 None 只剩一种语义：同源 issue 已存在的
                # 幂等去重跳过（在其 insert try 之外 early-return）；insert 的真代码/DB 异常现已上抛、
                # 不再走此 None 分支（cmr ni r7 codex high），故 reason 不再含「或落库失败」。
                applied_new.append({"id": ev.id, "title": ev.title, "rejected": True, "reason": "事件已触发过（同源局势已立，幂等跳过）"})
            else:
                consumed_event_ids.add(ev.id)
                candidates_dirty = True
                applied_new.append({"id": ev.id, "issue_id": issue_id, "kind": "situation", "title": ev.title, "rejected": False})
            continue
        if origin_kind != "decree":
            print(f"[INFO] new_issue 已拒：'{title}'（origin_kind={origin_kind!r}，仅接 decree / event_pool）。")
            applied_new.append({"title": title, "rejected": True, "reason": "来源非 decree/event_pool 不许新立"})
            continue
        # kind 缺省/null/空串 → 默认 initiative；present 非法值（含 false/0/[] 这类 falsy 非串，
        # 原 `or "initiative"` 会把它们静默默认、绕过白名单，cmr ni r6 codex）→ 留给白名单拒收。
        _kind_raw = ni.get("kind")
        kind = "initiative" if _kind_raw in (None, "") else str(_kind_raw)
        if kind not in ("situation", "initiative"):
            # 脏 kind（LLM 偶给 "reform"/"policy"/"局势" 等，见 DELTA_SCHEMA.md）→ insert_issue 会
            # 抛 ValueError；本刀移除 broad except 后会逃逸成 SettlementAbort，故须在此预检拒整项
            # （与 4 个脏强转同口径，cmr ni r1 Claude+codex concur）。
            applied_new.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"new_issue kind 非法 '{kind}'（须 situation/initiative）",
                "item": ni, "title": title,
            })
            continue
        if kind == "initiative" and initiative_active >= INITIATIVE_ACTIVE_CAP:
            applied_new.append({
                "title": title,
                "rejected": True,
                "reason": f"已有{INITIATIVE_ACTIVE_CAP_LABEL}事在办，朝廷分身乏术，难再添新工。",
            })
            continue
        # LLM 可能把效果字段给成非 dict（字符串/数组）；isinstance 守门归 {}，
        # 不让 dict("乱填") 抛 ValueError 越过单条拒绝、崩整月落库（codexB-P1）。
        def _eff_dict(v):
            return v if isinstance(v, dict) else {}
        ongoing_eff = _eff_dict(ni.get("ongoing_effects"))
        resolve_eff = _eff_dict(ni.get("effect_on_resolve"))
        fail_eff = _eff_dict(ni.get("effect_on_fail"))
        semantic_ongoing_has_work = effect_dict_has_work(ongoing_eff)
        ongoing_has_work = _monthly_ongoing_effects_has_work(ongoing_eff)
        unsupported_ongoing_fields = _unsupported_monthly_ongoing_fields(ongoing_eff)
        # cancel_cost 同属 dict 字段，与上 3 个统一走 _eff_dict 容忍归 {}（cmr ni r9 codex medium）：
        # 旧 `dict(ni.get("cancel_cost") or {})` 对 list-of-pairs 静默 garble（dict([["民心",-5]])=
        # {'民心':-5}、dict(["ab"])={'a':'b'}）、对标量串 raise 拒整项——而 cancel_cost 是次要字段，
        # 脏不该丢掉整个 issue 决策后果（违 P1 落库铁律）。容忍归 {} 既不 garble、又保 issue 主体。
        cancel_cost = _eff_dict(ni.get("cancel_cost"))
        origin_ref = str(ni.get("origin_ref") or "").strip()
        stop_condition_raw = ni.get("stop_condition")
        stop_condition = _issue_condition_text(stop_condition_raw)
        commitment_kind = _normalize_commitment_kind(ni.get("commitment_kind"))
        try:
            end_turn_marker_shape = _strict_int(
                0 if ni.get("end_turn", 0) in (None, "") else ni.get("end_turn", 0)
            ) > 0
        except (TypeError, ValueError, OverflowError):
            end_turn_marker_shape = False
        legacy_resolve_text = _issue_condition_text(ni.get("resolve_condition"))
        if not legacy_resolve_text and isinstance(stop_condition_raw, str):
            legacy_resolve_text = stop_condition
        legacy_resolve_commitment_shape = (
            commitment_condition_role(legacy_resolve_text).get("condition_role")
            == "commitment_stop_condition"
        )
        commitment_shape_without_marker = (
            not commitment_kind
            and kind == "initiative"
            and (
                end_turn_marker_shape
                or legacy_resolve_commitment_shape
                or (isinstance(stop_condition_raw, (dict, list)) and bool(stop_condition))
                or (
                    isinstance(stop_condition_raw, str)
                    and bool(stop_condition)
                    and bool(origin_ref)
                    and not resolve_eff
                    and not fail_eff
                )
                or (semantic_ongoing_has_work and not resolve_eff and not fail_eff and bool(origin_ref))
            )
        )
        if commitment_shape_without_marker:
            applied_new.append({
                "rejected": True,
                "category": "invalid_enum",
                "reason": "new_issue commitment_kind 必填（承诺形态不得靠 origin_kind/字段形状推断）",
                "item": ni,
                "title": title,
            })
            continue
        is_commitment = bool(commitment_kind)
        if is_commitment:
            try:
                if kind != "initiative":
                    raise ValueError("kind 须为 initiative")
                if not origin_ref:
                    raise ValueError("origin_ref 必填，须指回诏书")
                _et_raw = ni.get("end_turn", 0)
                end_turn_for_commitment = _strict_int(0 if _et_raw in (None, "") else _et_raw)
                if (
                    ongoing_has_work
                    and end_turn_for_commitment > 0
                    and end_turn_for_commitment <= int(state.turn)
                ):
                    raise ValueError(
                        f"end_turn 必须大于当前 turn（{state.turn}）；"
                        "有月度持续动作的承诺不能立项即到期"
                    )
                invalid_person_rating = _invalid_monthly_person_rating_reason(ongoing_eff)
                if invalid_person_rating:
                    raise ValueError(f"ongoing_effects {invalid_person_rating}")
                if unsupported_ongoing_fields:
                    raise ValueError(
                        "ongoing_effects 含非月度持续字段："
                        + ", ".join(unsupported_ongoing_fields)
                    )
                from ming_sim.staged_commitment import (
                    capture_commitment_stages,
                    stages_source_from_issue_item,
                )
                stages_for_commitment = capture_commitment_stages(
                    stages_source_from_issue_item(ni),
                    narrative_text=str(ni.get("stage_text") or ni.get("title") or ""),
                    origin_turn=int(state.turn),
                )
                has_stages = bool(stages_for_commitment)
                if not ongoing_has_work and end_turn_for_commitment <= 0 and not has_stages:
                    raise ValueError("ongoing_effects、end_turn 或 stages 至少一项必填")
                if stop_condition_raw in (None, "", {}):
                    if end_turn_for_commitment <= 0 and not ongoing_has_work and not has_stages:
                        raise ValueError("stop_condition 须为非空 dict，除非承诺带 end_turn 或 stages")
                    stop_condition = ""
                else:
                    stop_condition = _validate_commitment_stop_condition(stop_condition_raw, state, db)
                origin_ref = db.resolve_commitment_origin_ref(
                    state, origin_ref, origin_kind=str(ni.get("origin_kind") or ""),
                )
                origin_error = db.effect_origin_rejection(origin_ref)
                if origin_error:
                    raise ValueError(str(origin_error["reason"]))
            except (TypeError, ValueError, OverflowError) as exc:
                applied_new.append({
                    "rejected": True, "category": "invalid_enum",
                    "reason": f"new_issue commitment 字段非法（origin_ref/ongoing_effects/stop_condition）：{exc}",
                    "item": ni, "title": title,
                })
                continue
        # 校验：国策必须有「办成回报」。CLI 后端(agy)一贯不填效果字段（实测 0/4），
        # 空则聚焦补全，保证「国策跑完有实质后果」(A 方案)；floor 兜底，绝不入空壳。
        if kind == "initiative" and not resolve_eff and not is_commitment:
            from ming_sim.cli_backend import cli_backend_active, enrich_initiative_effects
            if cli_backend_active(llm_config):
                try:
                    enr = enrich_initiative_effects(
                        title,
                        str(ni.get("stage_text") or ""),
                        llm_config=llm_config,
                    )
                    resolve_eff = enr.get("effect_on_resolve") or resolve_eff
                    ongoing_eff = enr.get("ongoing_effects") or ongoing_eff
                    fail_eff = enr.get("effect_on_fail") or fail_eff
                    print(f"[issue/enrich] 国策「{title[:16]}」补效果 resolve={bool(resolve_eff)} ongoing={bool(ongoing_eff)}")
                except Exception as exc:
                    print(f"[issue/enrich] 补全失败，沿用空效果：{exc}")
                # floor 在 try 外：即便 enrich 抛错或没补上，CLI 后端国策也绝不入空壳（codexB）。
                if not resolve_eff:
                    resolve_eff = {"metrics": {"民心": 1}}
        # 字段强转脏数据 → 拒整项（ADR 0008 决定 1：new_issue 即「项」，坏字段令该项无法洁净构造
        # → 拒留痕，非默认掩盖）。这些强转会因脏 LLM 数据抛：bar_value/severity 的 int()、
        # cancel_cost 的 dict("脏")、tags 的 list(5)、_compute_inertia 的 legacy `int(inertia)`
        # 回退（其 expected_months 路自带兜底，但旧 inertia 字段在 try 外，cmr ni r2 codex）。
        # _normalize_cancellable / 各 str() 自带兜底不抛。原 except Exception WARN-skip 整项保留为
        # 「拒收留痕」，insert 的代码/DB 异常分出去上抛。
        try:
            # 整数字段用 _strict_int（与 region/army/faction 段一致）：拒 bool/float（int(3.7)=3 截断、
            # int(True)=1 都非合法整数 delta，cmr ni r6 codex）+ 非数串/inf/nan/超界。缺省/null → 默认，
            # 0 须保留（原 `or 50` 把合法 severity=0 静默改 50=保真 bug，cmr ni r4）；脏值落 except 拒整项。
            _bv = ni.get("bar_value", 25)
            bar_value = _strict_int(25 if _bv is None else _bv)
            _sv = ni.get("severity", 50)
            severity = _strict_int(50 if _sv is None else _sv)
            _et = ni.get("end_turn", 0)
            end_turn = _strict_int(0 if _et in (None, "") else _et)
            # cancel_cost 已在 try 外随 effect 字段走 _eff_dict 容忍归 {}（cmr ni r9）——不在此强转、
            # 不进 except 拒收路。
            # tags 严格化（cmr ni r8 codex medium，与上方 int 字段同一字段校验 class）：缺省/null/
            # 空串 → []；present 必须是 list/tuple 且元素全为 str。原 `list(ni.get("tags") or [])`
            # 把标量串拆字（list("募营")=['募','营']）——既污染 DB tags，又让 _initiative_resolve_
            # pairing_warnings 的整词子串匹配（"募营" in blob）失配 → bypass #45/#46 new_armies 配对
            # 守门；非串元素（list([5])=[5]）也静默落库。脏值落 except 拒整项。
            _tags_raw = ni.get("tags")
            if _tags_raw is None or _tags_raw == "":
                tags = []
            elif isinstance(_tags_raw, (list, tuple)) and all(isinstance(t, str) for t in _tags_raw):
                tags = list(_tags_raw)
            else:
                raise ValueError(f"tags 须为字符串列表（拒标量串拆字 / 非串元素）：{_tags_raw!r}")
            inertia = _compute_inertia(ni)
            if is_commitment:
                inertia = 0
        except (TypeError, ValueError, OverflowError) as exc:
            # OverflowError：JSON 里 1e309 解析成 float('inf')，超界 int 绑定亦抛；_strict_int 已把
            # float（含 inf/nan）归 ValueError，OverflowError 兜超大 int 等残余路（cmr ni r3 codex）。
            applied_new.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"new_issue 字段强转失败（bar_value/severity/end_turn/tags/inertia 脏数据）：{exc}",
                "item": ni, "title": title,
            })
            continue
        resolve_condition = _issue_condition_text(ni.get("resolve_condition"))
        if not resolve_condition and isinstance(ni.get("stop_condition"), str):
            resolve_condition = stop_condition
        # A structured roster is an item-level contract.  In particular a
        # mapping is not an iterable roster: iterating it would persist its
        # keys (\"character_id\", \"tier\") as phantom participants.
        roster_input = next(
            (ni.get(key) for key in ("participant_roster", "participants", "participant_names", "actors")
             if ni.get(key) is not None),
            None,
        )
        if roster_input is not None:
            try:
                if not isinstance(roster_input, (list, tuple)):
                    raise ValueError("participant_roster 须为列表")
                for participant in roster_input:
                    if isinstance(participant, str):
                        if not participant.strip():
                            raise ValueError("participant_roster 人名不得为空")
                        continue
                    if not isinstance(participant, dict):
                        raise ValueError("participant_roster 每项须为对象或人名")
                    if not str(participant.get("character_id") or participant.get("name") or "").strip():
                        raise ValueError("participant_roster 每项须有 character_id")
                    tier = str(participant.get("tier") or participant.get("档") or "知情").strip()
                    if tier not in {"主办", "协办", "知情"}:
                        raise ValueError(f"participant_roster tier 非法：{tier}")
            except ValueError as exc:
                applied_new.append({"rejected": True, "category": "invalid_participant_roster",
                                    "reason": str(exc), "item": ni, "title": title})
                continue
        # insert_issue 不再裹 broad except：代码/DB 异常上抛 → SettlementAbort（ADR 0005 fail-loud），
        # 不再当 WARN 吞（那会半落库 + 丢决策，违 P1 铁律）。
        # 注：字符串字段含孤代理（JSON 解析出的 "\\ud800"）会在 SQLite bind 抛 UnicodeEncodeError。
        # #63 已在 SQLite-bind 序列化点统一用「保中文、净孤代理」helper 治理；本段不局部吞
        # UnicodeEncodeError，仍让非编码类代码/DB 异常按 ADR 0005 fail-loud 上抛。
        # Validate provenance only after item-shape validation, so malformed
        # fields retain their precise rejection category without ever reaching a write.
        origin_error = db.effect_origin_rejection(origin_ref)
        if not re.fullmatch(r"dossier:[1-9][0-9]*", origin_ref) or origin_error:
            applied_new.append({
                "rejected": True, "category": "missing_ref", "item": ni,
                "title": title,
                "reason": (origin_error or {}).get(
                    "reason", "new decree issue origin_ref 须为已颁 dossier:<id>"
                ),
            })
            continue
        from ming_sim.staged_commitment import (
            capture_commitment_stages,
            stages_source_from_issue_item,
        )
        stages_norm = (
            capture_commitment_stages(
                stages_source_from_issue_item(ni),
                narrative_text=str(ni.get("stage_text") or ni.get("title") or ""),
                origin_turn=int(state.turn),
            )
            if is_commitment
            else []
        )
        # 段派生 end_turn（max stage due）不落 DB；落库会在末段到期 + ongoing 时误走 mechanical expire（#620）。
        issue_id = db.insert_issue(
            state,
            kind=kind,
            title=title[:60] or "无名事项",
            origin_kind="decree",
            origin_ref=origin_ref,
            bar_value=bar_value,
            bar_good_meaning=str(ni.get("bar_good_meaning") or "已成"),
            bar_bad_meaning=str(ni.get("bar_bad_meaning") or "废止"),
            inertia=inertia,
            stage_text=str(ni.get("stage_text") or "")[:120],
            severity=severity,
            region_hint=str(ni.get("region_hint") or ""),
            faction_hint=str(ni.get("faction_hint") or ""),
            tags=tags,
            # Keep ADR 0053's structured roster intact.  insert_issue writes the
            # compatibility name list and the durable roster together; reducing
            # dict entries to str(dict) creates phantom character names.
            participants=roster_input or [],
            ongoing_effects=ongoing_eff,
            cancellable="decree" if is_commitment else _normalize_cancellable(ni.get("cancellable")),
            cancel_cost=cancel_cost,
            effect_on_resolve=resolve_eff,
            effect_on_fail=fail_eff,
            resolve_condition=resolve_condition[:300],
            fail_condition=str(ni.get("fail_condition") or "")[:300],
            end_turn=end_turn,
            stop_condition=stop_condition,
            commitment_kind=commitment_kind,
            stages_json=stages_norm,
            commit=commit_now,
        )
        if kind == "initiative":
            initiative_active += 1
        applied_item = {"issue_id": issue_id, "kind": kind, "title": title, "rejected": False}
        if commitment_kind:
            applied_item["commitment_kind"] = commitment_kind
        if stages_norm:
            applied_item["stages"] = stages_norm
        applied_new.append(applied_item)

    # 3) closes（LLM 主动结案/失败，不看 bar 门槛）
    applied_closes: List[Dict[str, object]] = []
    for cl in tracker_output.get("close_issues", []) or []:
        # ADR 0008 决定 1：LLM 脏数据逐项拒收留痕（坏 id/reason/陈旧引用），不静默丢；
        # db.close_issue 的代码/DB 异常不再 WARN 吞，上抛触发 SettlementAbort（ADR 0005 fail-loud）。
        if not isinstance(cl, dict):
            # 非 dict 项（如 close_issues:[null]/标量，_sanitize 不清列表项可达）：cl.get 会抛
            # AttributeError（不在下方 except 内）崩整月——逐项拒收，不让坏项带走整批（codex r4）。
            applied_closes.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"close_issues 条目非对象（应为 dict）：{cl!r}",
                "item": cl,
            })
            continue
        try:
            # _parse_sqlite_id：非整数/bool/float/超 SQLite 64-bit 范围 → ValueError（含 10**100
            # 这类 int() 过得了但绑定 SQLite 抛 OverflowError 的脏 id，避免上抛崩整月，codex r1）。
            issue_id = _parse_sqlite_id(cl.get("issue_id"))
        except (TypeError, ValueError):
            applied_closes.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"close_issues issue_id 非法（非整数或超 SQLite 范围）：{cl.get('issue_id')!r}",
                "item": cl,
            })
            continue
        reason = str(cl.get("reason") or "").strip().lower()
        if reason not in ("resolved", "failed", "acknowledged"):
            applied_closes.append({
                "rejected": True, "category": "invalid_enum",
                "reason": f"close_issues reason 非法 '{reason}'（须 resolved/failed/acknowledged），issue {issue_id}",
                "item": cl,
            })
            continue
        narrative = str(cl.get("narrative") or "")[:400]
        chk = db.conn.execute(
            "SELECT * FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        if reason == "acknowledged":
            from ming_sim.staged_commitment import is_stage_derived_end_turn
            if chk is None:
                category, why = "missing_ref", f"close_issues 引用未找到的 issue {issue_id}"
            elif chk["status"] != "active":
                category, why = "missing_ref", f"close_issues 引用已非 active（{chk['status']}）的 issue {issue_id}"
            elif not str(chk["commitment_kind"] or "").strip():
                category, why = "invalid_enum", f"close_issues acknowledged 只允许到期待裁承诺 issue {issue_id}"
            elif effect_dict_has_work(chk["ongoing_effects"]):
                category, why = "invalid_enum", f"close_issues acknowledged 不允许收尾持续承诺 issue {issue_id}"
            elif int(chk["end_turn"] or 0) <= 0 or int(chk["end_turn"] or 0) > int(state.turn):
                category, why = "invalid_enum", f"close_issues acknowledged 只允许已到期承诺 issue {issue_id}"
            elif is_stage_derived_end_turn(chk["stages_json"], int(chk["end_turn"] or 0)):
                category, why = (
                    "invalid_enum",
                    f"close_issues acknowledged 不得收尾段派生 end_turn 承诺 issue {issue_id}",
                )
            else:
                new_row = _ack_due_commitment_issue(
                    db,
                    state,
                    chk,
                    narrative=narrative,
                    commit=not external_transaction,
                )
                touched_ids.add(issue_id)
                applied_closes.append({
                    "issue_id": issue_id,
                    "title": new_row["title"],
                    "reason": reason,
                    "narrative": narrative,
                    "rejected": False,
                })
                continue
            applied_closes.append({
                "rejected": True,
                "category": category,
                "reason": why,
                "item": cl,
            })
            continue
        if (
            reason in ("resolved", "failed")
            and chk is not None
            and chk["status"] == "active"
            and (
                chk["commitment_kind"]
                or commitment_condition_role(chk["resolve_condition"] or "").get("condition_role")
                == "commitment_stop_condition"
            )
        ):
            applied_closes.append({
                "rejected": True,
                "category": "invalid_enum",
                "reason": f"close_issues 对承诺型 issue {issue_id} 误判 {reason}（须走专门完成闭环）",
                "item": cl,
            })
            continue
        new_row = db.close_issue(
            state,
            issue_id,
            reason=reason,
            narrative=narrative,
            commit=not external_transaction,
        )
        if new_row is None:
            # close_issue 回 None 有三态，回查 status 精确归类（cmr Claude high）：
            #   ① 未找到 / ② 已非 active → 陈旧/幻觉引用（missing_ref）；
            #   ③ 找到且仍 active 却被拒 → close_issue 唯一剩余 None 路径＝reason=failed 用于
            #      不可崩坏局势（无 effect_on_fail，保持 active）＝LLM 语义误判（invalid_enum），非「未找到」。
            chk = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
            if chk is None:
                category, why = "missing_ref", f"close_issues 引用未找到的 issue {issue_id}"
            elif chk["status"] != "active":
                category, why = "missing_ref", f"close_issues 引用已非 active（{chk['status']}）的 issue {issue_id}"
            elif reason == "failed":
                # 找到且 active 却被拒，今天 close_issue 唯一这条 active-None 路径＝reason=failed
                # 用于无 effect_on_fail 的不可崩坏局势（LLM 语义误判，保持 active）。
                category, why = "invalid_enum", (
                    f"close_issues 对不可崩坏局势 issue {issue_id} 误判 failed"
                    "（无 effect_on_fail，拒结案、保持 active）"
                )
            else:
                # reason=resolved 对 active issue 今天必返回非 None（不可达此分支）；留通用兜底
                # 防 close_issue 未来新增 active-None 路径时消息说谎（gemini-code-assist）。
                category, why = "invalid_enum", f"close_issues 结案被拒、issue {issue_id} 保持 active"
            applied_closes.append({"rejected": True, "category": category, "reason": why, "item": cl})
            continue
        touched_ids.add(issue_id)
        # 终结效果：以 issue 立项时预设的 effect 为底，叠加 LLM 在本次结案项 cl 里现给的 effect。
        # 现给优先——event_pool 预设 issue（如阉党之祸）立项时 effect 多为空，帝国修正只能结案当下给。
        if reason == "resolved":
            effect = loads_effect_dict(new_row["effect_on_resolve"])
            cl_effect = cl.get("effect_on_resolve")
        else:
            effect = loads_effect_dict(new_row["effect_on_fail"])
            cl_effect = cl.get("effect_on_fail")
        if isinstance(cl_effect, dict):
            # 浅合并：metrics/economy/factions/buildings/legacy 等顶层段，现给覆盖预设
            effect = {**effect, **cl_effect}
        if reason == "resolved":
            _emit_pairing_warnings(new_row, effect, pairing_warnings)
        parent_origin_ref = _canonical_issue_origin(db, new_row)
        _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
        entity_rejections.extend(r for r in _apply_economy_list(
            db, state, effect.get("economy") or [], commit=commit_now,
            origin_ref=parent_origin_ref,
        ) if r.get("rejected"))  # economy 拒收不蒸发（#14）
        entity_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}, commit=commit_now).rejections)  # 派系拒收不蒸发（#14/#63 cmr r2）
        building_ops = _apply_issue_buildings(
            db, state, effect.get("buildings"),
            _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}{'结案' if reason == 'resolved' else '失败'}",
            commit=commit_now, origin_ref=parent_origin_ref,
        )
        close_person_changes: List[Dict[str, object]] = []
        entity_rejections.extend(_apply_issue_entities(
            db,
            state,
            effect,
            f"局势#{issue_id}{'结案' if reason == 'resolved' else '失败'}",
            content=runtime_content,
            llm_config=llm_config,
            applied_person_changes=close_person_changes,
            commit=commit_now,
            origin_ref=parent_origin_ref,
        ))
        issue_person_changes.extend(close_person_changes)
        _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]), commit=commit_now)
        close_record = {
            "issue_id": issue_id,
            "title": new_row["title"],
            "reason": reason,
            "narrative": narrative,
            "building_ops": building_ops,
        }
        if close_person_changes:
            close_record["applied_person_changes"] = close_person_changes
        applied_closes.append(close_record)

    # 4) cancels
    for cn in tracker_output.get("cancels", []) or []:
        try:
            issue_id = int(cn.get("issue_id"))
        except (TypeError, ValueError):
            continue
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if row is None or row["status"] != "active":
            continue
        if row["cancellable"] != "decree":
            # 不可撤：当作 advance 处理（皇威 -2）
            db.advance_issue(
                state, issue_id,
                trigger_kind="decree",
                delta_bar=0,
                stage_text=row["stage_text"],
                narrative=str(cn.get("narrative") or "陛下欲罢，然此事非诏可消。")[:400],
                metric_delta={"皇威": -2},
                commit=not external_transaction,
            )
            state.metrics["皇威"] = max(0, int(state.metrics.get("皇威", 0)) - 2)
            touched_ids.add(issue_id)
            applied_cancels.append({
                "issue_id": issue_id, "rejected": True, "title": row["title"],
                # 拒收行必须带人读原因（ADR 0008 决定 5）；此拒收有部分落库副作用
                # （已转强推+皇威-2），category 区分于纯丢弃（cmr S0 r2）。
                "reason": "此事非诏可消（不可撤国策），已转强行推进并损皇威 2 点。",
                "category": "non_cancellable_converted",
            })
            continue
        # #623 / ADR 0075：active 承诺松手不得顺 cancel 即 breach+close——
        # cancel=改弦信号：primary∪absorbed 含改弦即认并 finalize 该 merged 条；
        # 其它类 pending 则并入改弦条。禁「报 persist 不执行」。
        if str(row["commitment_kind"] or "").strip():
            from ming_sim.breach_plea import (
                BREACH_KIND_POLICY_REVERSAL,
                finalize_persist,
                find_pending_plea,
                parse_dossier_id,
                write_breach_plea_todo,
            )
            origin_ref_c = str(row["origin_ref"] or "").strip()
            # 统一 primary∪absorbed：has_pending 与 todo 检索同一读口
            plea_todo = find_pending_plea(
                db, issue_id, breach_kind=BREACH_KIND_POLICY_REVERSAL,
            )
            if plea_todo is not None:
                finalize_persist(db, state, plea_todo, commit=False)
                applied_cancels.append({
                    "issue_id": issue_id,
                    "rejected": False,
                    "title": row["title"],
                    "breach_plea_decision": "persist",
                })
                touched_ids.add(issue_id)
                continue
            # 无改弦 pending：写/并入改弦挽留条（同回合他类松手走 merge，不静默吞）
            write_breach_plea_todo(
                db, state,
                commitment_ref=issue_id,
                breach_kind=BREACH_KIND_POLICY_REVERSAL,
                reason=str(cn.get("narrative") or "撤回成命")[:400],
                target_dossier_id=int(parse_dossier_id(origin_ref_c) or 0),
            )
            applied_cancels.append({
                "issue_id": issue_id,
                "rejected": False,
                "title": row["title"],
                "deferred_breach_plea": True,
            })
            touched_ids.add(issue_id)
            continue
        # 可撤成命：若事项来自已颁案卷，ADR 0056 的确定性毁约轨取代
        # extractor/default by_progress cancel_cost，防同一次撤旨双罚。
        linked_dossier = None
        origin_ref = str(row["origin_ref"] or "").strip()
        if re.fullmatch(r"dossier:[1-9][0-9]*", origin_ref) and db.effect_origin_rejection(origin_ref) is None:
            linked_dossier = db.get_decree_dossier(int(origin_ref.split(":", 1)[1]))
        deterministic_breach = bool(
            linked_dossier
            and (
                linked_dossier["status"] in {"promulgated", "executing"}
                or (
                    linked_dossier["status"] == "closed"
                    and bool(row["commitment_kind"])
                    and db.dossier_authorizes_effects(int(linked_dossier["id"]))
                )
            )
        )
        if deterministic_breach:
            db.breach_decree_dossier(
                state, int(linked_dossier["id"]),
                reason=str(cn.get("narrative") or "撤回成命")[:400], commit=False,
            )
        cost = {} if deterministic_breach else (cn.get("applied_cost") or {})
        if isinstance(cost, dict):
            _apply_metric_dict(state, cost.get("metrics") or {}, db=db)
            parent_origin_ref = _canonical_issue_origin(db, row)
            entity_rejections.extend(r for r in _apply_economy_list(
                db, state, cost.get("economy") or [], commit=commit_now,
                origin_ref=parent_origin_ref, require_origin=True,
            ) if r.get("rejected"))  # economy 拒收不蒸发（#14）
            entity_rejections.extend(_apply_faction_dict(db, cost.get("factions") or {}, commit=commit_now).rejections)  # 派系拒收不蒸发（#14/#63 cmr r2）
        db.cancel_issue(
            state, issue_id,
            narrative=str(cn.get("narrative") or "")[:400],
            applied_cost=cost if isinstance(cost, dict) else {},
            commit=not external_transaction,
        )
        touched_ids.add(issue_id)
        applied_cancels.append({"issue_id": issue_id, "rejected": False, "title": row["title"]})

    state.clamp()
    return {
        "advances": applied_advances,
        "new_issues": applied_new,
        "closes": applied_closes,
        "cancels": applied_cancels,
        "entity_rejections": entity_rejections,
        "applied_person_changes": issue_person_changes,
        "touched_ids": sorted(touched_ids),
        "pairing_warnings": pairing_warnings,
    }


# 独占实职关键词：office 分项以此结尾者视为「一人一缺」，须顶替去重。
# 群体职（大学士/侍郎/郎中/主事/御史/翰林等）不在内，可多员并存。
_EXCLUSIVE_OFFICE_SUFFIXES = (
    "首辅", "次辅", "尚书", "总督", "巡抚", "总兵", "督师", "经略", "提督",
)


def _is_exclusive_office(part: str) -> bool:
    """office 单个分项是否独占实职。南京XX为留都缺，与京职互不冲突，单独算一缺。"""
    return any(part.endswith(suf) for suf in _EXCLUSIVE_OFFICE_SUFFIXES)


def _displace_duplicate_offices(
    db: GameDB,
    content: Optional[GameContent],
    new_holder: str,
    new_office: str,
    *,
    commit: bool = True,
) -> List[str]:
    """新任者 new_holder 拿到 new_office 后，把其中每个独占实职分项从其他 active 官员
    office 里剔除，避免双缺官。返回被腾出的 (旧任者:职) 描述列表。
    纯按 office 文字匹配——不依赖 court_role，对存量档同样生效。"""
    new_parts = [p for p in normalize_office(new_office).split(",") if _is_exclusive_office(p)]
    if not new_parts:
        return []
    displaced: List[str] = []
    displaced_names: set[str] = set()  # #9 cmr R1：被顶替者去重，循环后逐派系重算 leverage。
    rows = db.conn.execute(
        "SELECT name, office FROM characters WHERE status='active' AND power_id='ming' AND name!=?",
        (new_holder,),
    ).fetchall()
    for row in rows:
        holder_parts = [p.strip() for p in str(row["office"]).split(",") if p.strip()]
        kept = [p for p in holder_parts if p not in new_parts]
        if len(kept) == len(holder_parts):
            continue  # 此人不占同名独缺
        displaced_names.add(row["name"])
        for lost in (p for p in holder_parts if p in new_parts):
            displaced.append(f"{row['name']}:{lost}")
        fully_displaced = not kept
        new_holder_office = "听用候铨" if fully_displaced else ",".join(kept)
        # 剔掉一个分项后,保留官职对应的 office_type 可能变了(如剔「兵部尚书」后只剩「左都御史」=都察院)。
        # 若独占实职被完全腾空,旧任仍 active,但其名分必须落入人才池的「听用候铨」,
        # 不能留下 active + 空 office 的半身份（ADR 0009 S5）。
        old_type_row = db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?", (row["name"],)).fetchone()
        old_type = old_type_row["office_type"] if old_type_row else ""
        new_type = (
            "身名分"
            if fully_displaced
            else infer_office_type_from_office(new_holder_office, old_type, db.llm_config)
        )
        if fully_displaced:
            db.conn.execute(
                "UPDATE characters SET office=?, office_type=?, status_reason=?, reason_code=?, "
                "transit_to='', transit_start_turn=0 WHERE name=?",
                (new_holder_office, new_type, "被顶替", "被顶替", row["name"]),
            )
        else:
            db.conn.execute(
                "UPDATE characters SET office=?, office_type=? WHERE name=?",
                (new_holder_office, new_type, row["name"]),
            )
        if content is not None and row["name"] in content.characters:
            ch = content.characters[row["name"]]
            ch.office = new_holder_office
            ch.office_type = new_type
            if fully_displaced:
                ch.status_reason = "被顶替"
                ch.reason_code = "被顶替"
                ch.transit_to = ""
    # #9 cmr R1：被顶替者的 office_type 经上方裸 UPDATE 改了（全顶替→身名分=0 权重），绕过了
    # set_character_office 钩子，故其所属派系（常与新任者异派系）的 leverage 须在此补重算，否则
    # 残留偏高、违 #9 不变式。新任者自身派系已由 set_character_office 钩子重算，这里只补被顶替者。
    # commit 前调用——recompute 读当前在朝成员、不内部 commit，正反映刚改完的 office_type；
    # 绝对幂等（非白名单 return、重复无害）。去重后逐派系各调一次。
    displaced_factions = set()
    for dn in displaced_names:
        frow = db.conn.execute(
            "SELECT faction FROM characters WHERE name=?", (dn,)
        ).fetchone()
        # 空/None faction 提前滤掉（recompute_faction_leverage("") 虽被白名单校验 no-op，
        # 但提前过滤免去无意义调用，集合也不残留空串。线上 R5 gemini medium。
        if frow is not None and frow["faction"]:
            displaced_factions.add(str(frow["faction"]))
    for fac in displaced_factions:
        db.recompute_faction_leverage(fac)
    if commit:
        db.conn.commit()
    return displaced


def _snapshot_person_write_state(db: GameDB, content: Optional[GameContent]):
    character_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT name, status, office, office_type, status_reason, "
            "status_changed_turn, reason_code, transit_to, transit_start_turn FROM characters"
        ).fetchall()
    ]
    office_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT character_name, office_title, office_type, source, dossier_id, "
            "appointment_tenure, updated_at FROM character_offices"
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
        "status_changed_turn=?, reason_code=?, transit_to=?, transit_start_turn=? WHERE name=?",
        [
            (
                row["status"],
                row["office"],
                row["office_type"],
                row["status_reason"],
                row["status_changed_turn"],
                row["reason_code"],
                row["transit_to"],
                row.get("transit_start_turn", 0),
                row["name"],
            )
            for row in character_rows
        ],
    )
    db.conn.executemany(
        "INSERT INTO character_offices "
        "(character_name, office_title, office_type, source, dossier_id, "
        "appointment_tenure, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["character_name"],
                row["office_title"],
                row["office_type"],
                row["source"],
                row.get("dossier_id"),
                row["appointment_tenure"],
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
                row["appointment_tenure"], row["created_at"],
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
#   - power_updates:apply_score_extraction 虽裹 try/except,但只接住异常不回滚——前面已写的 power
#     行仍被后续 record_log/save_turn 提交 = 半落库(CMR R2 codex)。prompt 里 power_updates 恒为
#     嵌套 dict,无扁平标量形态,故二级非 dict = 真畸形,校验前置拦截正确。
# **不**列入（交给各自 adapter 按契约处理）:faction_delta 吃旧扁平 int
# {"阉党": -10}（prompt 允许、合法）；class_delta 的扁平 item 不合法，由 adapter 逐项
# `invalid_enum` 拒收（#564），而非 validate 层当 nested-dict shape 拒收。
_NESTED_DICT_FIELDS = frozenset({"region_delta", "army_delta", "power_updates"})


def sanitize_delta_shape(extracted: dict) -> tuple[dict, list[tuple[str, dict, str]]]:
    """Return (cleaned_delta, validate-layer rejections) per ADR 0015.

    Unknown top-level keys / non-dict top-level payloads still fail loud because
    no section can be safely split. Split-capable section/list/entity shape
    defects are removed item-by-item and returned as rejection records. Flat
    faction integers remain legal; flat class items reach the class adapter and
    are rejected per item as ``invalid_enum`` under the #564 contract.
    """
    from ming_sim.simulation import EMPTY_EXTRACTION  # 懒 import 避 issues↔simulation 循环

    if not isinstance(extracted, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(extracted).__name__}")
    cleaned = dict(extracted)
    rejections: list[tuple[str, dict, str]] = []
    for key, value in list(extracted.items()):
        if key == "_module_rejections":
            continue
        if key not in EMPTY_EXTRACTION:
            raise ValueError(
                f"未知 delta 顶层字段「{key}」(canonicalize 后)；疑拼写错(如 地区变更↔地区变化)，"
                "apply 不会消费它 = 静默无效。请改用合法 key。"
            )
        if value is None:
            continue
        expected = EMPTY_EXTRACTION[key]
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


@contextmanager
def _appointment_tenure_scope(db: GameDB, appointment_tenure: str):
    previous_tenure = getattr(db.conn, "_appointment_tenure", "真除")
    db.conn._appointment_tenure = appointment_tenure
    try:
        yield
    finally:
        db.conn._appointment_tenure = previous_tenure


def apply_office_appointment(
    db: GameDB,
    state: GameState,
    content,
    registry,
    name: str,
    new_office: str,
    *,
    reason: str = "",
    new_office_type: str = "",
    faction: str = "中立",
    appointment_tenure: str = "真除",
    llm_config: Any = None,
    commit: bool = True,
) -> Dict[str, object]:
    """朝臣任命/调任的【唯一落地核】：在册且未死 → 改 active + 授官 + 顶替去重 + 同步内存/registry；
    不在册 → apply_appointment 建新档。extractor 的 office_changes 与 CLI 自然语言任免 commit
    共用此核，杜绝两份会漂的 copy（CMR R2 reground）。后宫纳妃语义不同，不走此核（见 appointments）。
    返回结果 dict（rejected / kind=transfer|appoint / displaced 等）。"""
    name = str(name or "").strip()
    new_office = str(new_office or "").strip()
    if not name or not new_office:
        return {"name": name, "new_office": new_office, "rejected": True, "reason": "name 或 new_office 空"}
    # 别名归一：自然语言/LLM 可能用别名（韩老、温首辅、史宪之、福王…），解析到在册规范 key，
    # 否则 in_roster 按确切 key 漏判 → 误走新建档（CMR R3 gemini；#1317 r2 身份归一含未仕/宗藩）。
    # _find_existing_minister 吃在册身份归一（非后宫∧非 candidate∧ming，**含宗藩/未仕**）；
    # candidate/不在册返 None → name 不变（candidate 仍由 in_roster 确切 key 命中走激活分支）。
    if content is not None:
        from ming_sim.session import _find_existing_minister
        canon = _find_existing_minister(content, name, db)
        if canon:
            name = canon
    in_roster = content is not None and name in content.characters
    cur_status = db.get_character_status(name)[0] if in_roster else ""
    current_office_type = content.characters[name].office_type if in_roster else ""
    if in_roster:
        if cur_status == "dead":
            return {"name": name, "new_office": new_office, "rejected": True, "reason": "人物已故，不能重新启用"}
        # 宗藩（就藩宗室）非朝堂命官，不可授官（PR#121）。这是任命落地核——授官会把 office_type
        # 从「宗藩」改成新官署、反解掉所有 roster 隐藏，故必须在此写侧拒（extractor office_changes
        # 与 CLI/pending 任免都经本核，集中守一处，cmr R5 cross-section）。宗藩在册数据保持不变。
        _appointee = content.characters.get(name)  # name 经 in_roster 必在册，.get 防御一致（R3 gemini）
        if _appointee is not None and is_vassal_prince(_appointee):
            return {"name": name, "new_office": new_office, "rejected": True,
                    "reason": "宗藩（就藩宗室）非朝堂命官，不可授官"}
        old_office = content.characters[name].office
        snapshot = _snapshot_person_write_state(db, content)
        try:
            new_office, new_office_type, appointment_tenure = _canonical_appointment_fields(
                {
                    "office": new_office,
                    "office_type": new_office_type,
                    "任别": appointment_tenure,
                },
                current_office_type=current_office_type,
                llm_config=llm_config or db.llm_config,
            )
            if cur_status != "active":
                db.set_character_status(
                    state,
                    name,
                    "active",
                    reason[:200] or "诏书任命",
                    commit=commit,
                )
            with _appointment_tenure_scope(db, appointment_tenure):
                db.set_character_office(
                    name, new_office, new_office_type,
                    source=reason[:60] or "诏书调任", llm_config=llm_config,
                    commit=commit,
                )
            if cur_status == "active":
                db.conn.execute(
                    "UPDATE characters SET status_reason='', reason_code='' WHERE name=?",
                    (name,),
                )
                if commit:
                    db.conn.commit()
            displaced_parts = _displace_duplicate_offices(
                db, content, name, new_office, commit=commit
            )
            ch = content.characters[name]
            ch.status = "active"
            # 三面同步（决定6）：DB 写已定 status_reason/reason_code（active 路上方清空；
            # 非 active 起复路由 set_character_status 写入起复缘由）——回读刷回内存 Character，
            # 否则非 active 起复后内存滞留旧削籍/下狱缘由，DB 与内存不一致（5b r3 codex-b R1）。
            _reason_row = db.conn.execute(
                "SELECT status_reason, reason_code FROM characters WHERE name=?", (name,)
            ).fetchone()
            if _reason_row is not None:
                ch.status_reason = str(_reason_row["status_reason"] or "")
                ch.reason_code = str(_reason_row["reason_code"] or "")
            ch.office = new_office
            ch.office_type = new_office_type
            if registry is not None:
                registry.refresh(name)
                # 被顶替者 office/office_type 也变了,一并刷 Agent,免本回合后续用陈旧身份/工具(线上 gemini)。
                for dp in displaced_parts:
                    registry.refresh(dp.split(":")[0])
        except Exception as exc:
            _restore_person_write_state(db, content, snapshot, commit=commit)
            return {"name": name, "new_office": new_office, "rejected": True, "reason": f"落库失败：{exc}"}
        return {
            "name": name, "old_status": cur_status, "old_office": old_office, "new_office": new_office,
            "kind": "transfer", "reason": reason,
            **({"displaced": displaced_parts} if displaced_parts else {}),
        }
    # ── 新任：建新档 ──
    # 不变式（#1317 r2 重立）：经身份归一后若 name 仍不在 content.characters，才建档。
    # 在册者（含未仕诸生/宗藩及其别名）必经上方 in_roster 分支——未仕入仕走授官，
    # 宗藩撞硬闸 rejected；不得落到此，否则别名建重档 / 福王别名绕宗藩闸。
    # apply_appointment 对身份归一命中者亦拒新建，双保险。
    if content is None:
        return {"name": name, "new_office": new_office, "rejected": True, "reason": "无 content，跳过建档"}
    from ming_sim.session import apply_appointment  # 延迟导入避循环
    # office_type 必须透传：apply_appointment→add_character 靠它走 person-title 守卫（名分不建
    # offices 父行、不写 character_offices）。漏传则 infer 兜成「待铨」→ 名分人物被当普通官职、
    # 建脏 character_offices 行（#1058 接缝回归；transfer 分支已带 new_office_type，此处对称补齐）。
    # 建档抛错(DB 锁/唯一约束/注册失败)不得上抛崩月末结算致半落库(P1 铁律);
    # 与 in_roster 分支同样兜成 rejected、把 exc 记进 reason(不静默吞)(线上 gemini high)。
    snapshot = _snapshot_person_write_state(db, content)
    try:
        new_office, new_office_type, appointment_tenure = _canonical_appointment_fields(
            {
                "office": new_office,
                "office_type": new_office_type,
                "任别": appointment_tenure,
            },
            llm_config=llm_config or db.llm_config,
        )
        appt = {"name": name, "office": new_office, "office_type": new_office_type,
                "faction": faction, "reason": reason, "approved": True}
        with _appointment_tenure_scope(db, appointment_tenure):
            appointed, _ = apply_appointment(
                db,
                state,
                content,
                registry,
                appt,
                llm_config=llm_config,
                commit=commit,
            )
        if appointed:
            # 新任也按 office 文字去重(与 transfer 分支对称):新人占独占实职,从他人剔同名分项,
            # 免占缺旧任者留旧官成双缺官(CMR R4：去 replaces 后新任分支漏了顶替)。
            # displaced 统一取 _displace_duplicate_offices 的 List[str](apply_appointment 的单名
            # displaced 在去 replaces 后恒空,留着会让本字段时而 str 时而 list,故弃)(线上 gemini)。
            displaced_parts = _displace_duplicate_offices(
                db, content, appointed, new_office, commit=commit
            )
            # 被顶替者一并刷 Agent(新任者 apply_appointment 内已注册)(线上 gemini)。
            if registry is not None:
                for dp in displaced_parts:
                    registry.refresh(dp.split(":")[0])
            return {"name": appointed, "new_office": new_office, "kind": "appoint", "reason": reason,
                    **({"displaced": displaced_parts} if displaced_parts else {})}
    except Exception as exc:
        _restore_person_write_state(db, content, snapshot, commit=commit)
        return {"name": name, "new_office": new_office, "rejected": True, "kind": "appoint",
                "reason": f"落库失败：{exc}；原 status={cur_status or '不在册'}"}
    # apply_appointment 返回假值（查重拒/approved false/字段空——现均改库前早退）：防御性还原快照、
    # 与 except 路对称，确保此分支在任何 apply_appointment 行为下都不留半落库（P1 第一铁律，线上 gemini R3）。
    _restore_person_write_state(db, content, snapshot, commit=commit)
    return {"name": name, "new_office": new_office, "rejected": True, "kind": "appoint",
            "reason": f"建档失败（查重/字段不合）；原 status={cur_status or '不在册'}"}


def _apply_person_changes(
    db: GameDB,
    state: GameState,
    changes: List[Dict[str, object]],
    content=None,
    registry=None,
    llm_config: Any = None,
    source: str = "system_simulation",
    derived_from: str = "",
    allow_legacy_partial_power: bool = False,
    external_transaction: bool | None = None,
    origin_ref: str = "",
    require_origin: bool = False,
) -> List[Dict[str, object]]:
    if external_transaction is None:
        external_transaction = db.conn.in_transaction
    commit_person_change = not external_transaction

    def rejected(
        item: Dict[str, object],
        reason: str,
        category: str,
        *,
        status: str | None = None,
    ) -> Dict[str, object]:
        result: Dict[str, object] = {
            "name": str(item.get("name") or "").strip(),
            "动作": str(item.get("动作") or "").strip(),
            "rejected": True,
            "reason": reason,
            "category": category,
            "item": dict(item),
        }
        if status is not None:
            result["status"] = status
        return result

    def origin_rejected(item: Dict[str, object]) -> Dict[str, object] | None:
        error = db.effect_origin_rejection(origin_ref) if require_origin else None
        return rejected(item, str(error["reason"]), str(error["category"])) if error else None

    def character_row(name: str):
        return db.conn.execute(
            "SELECT name, status, office, office_type, power_id, status_reason, "
            "status_changed_turn, reason_code, transit_to, transit_start_turn "
            "FROM characters WHERE name=?",
            (name,),
        ).fetchone()

    def log_applied(
        result: Dict[str, object],
        item: Dict[str, object],
        *,
        commit: bool | None = None,
    ) -> None:
        if result.get("rejected"):
            return
        name = str(result.get("name") or "").strip()
        action = str(result.get("动作") or result.get("action") or "").strip()
        if not name or not action:
            return
        if db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone() is None:
            return
        summary = (
            str(result.get("reason") or item.get("reason") or "")
            or str(result.get("new_office") or result.get("office") or "")
            or str(result.get("status") or result.get("new_power") or result.get("transit_to") or "")
        )
        normalized = {
            key: value
            for key, value in result.items()
            if key not in {"rejected", "category", "item"}
        }
        db.record_person_log(
            state,
            name,
            action,
            payload_summary=summary,
            derived_from=str(result.get("derived_from") or derived_from or ""),
            normalized=normalized,
            source=source,
            commit=commit_person_change if commit is None else commit,
            origin_ref=origin_ref,
        )

    def identity_title_for_allegiance(item: Dict[str, object], new_power: str) -> str:
        title = str(item.get("new_title") or item.get("title") or "").strip()
        if title:
            return title if title in PERSON_IDENTITY_TITLES else ""
        way = str(item.get("方式") or item.get("way") or "").strip()
        if new_power == "ming" or way == "主动归附":
            return "归附"
        return "降臣"

    def displaced_talent_pool_results(displaced_parts: object) -> List[Dict[str, object]]:
        if not isinstance(displaced_parts, list):
            return []
        results: List[Dict[str, object]] = []
        for part in displaced_parts:
            name_part = str(part).split(":", 1)[0].strip()
            if not name_part:
                continue
            row = character_row(name_part)
            if row is None:
                continue
            if str(row["office"] or "") != "听用候铨" or str(row["reason_code"] or "") != "被顶替":
                continue
            results.append(
                {
                    "name": name_part,
                    "动作": "处置",
                    "status": "active",
                    "reason": "被顶替",
                    "reason_code": "被顶替",
                    "office": "听用候铨",
                    "office_type": "身名分",
                    "derived_from": "被顶替",
                    # applier 合成级联回声：信用写端只消费 extractor 宣告本体行。
                    "cascade_echo": True,
                }
            )
        return results

    applied: List[Dict[str, object]] = []
    needs_person_change_commit = False
    person_statuses = {
        "active",
        "candidate",
        "offstage",
        "dismissed",
        "imprisoned",
        "exiled",
        "retired",
        "dead",
    }
    disposition_statuses = person_statuses - {"active", "candidate"}
    for item in changes:
        name = str(item.get("name") or "").strip()
        action = str(item.get("动作") or "").strip()
        if not name or not action:
            applied.append(rejected(item, "name 或 动作 缺失", "missing_field"))
            continue
        if content is not None:
            from ming_sim.session import _find_existing_minister
            canon = _find_existing_minister(content, name, db)
            if canon:
                name = canon

        if action == "评定":
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = db.conn.execute(
                "SELECT name, loyalty FROM characters WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            raw_delta = item.get("loyalty")
            if isinstance(raw_delta, bool) or not isinstance(raw_delta, int) or raw_delta == 0:
                applied.append(rejected(item, "评定 loyalty 须为非零整数增量", "invalid_enum"))
                continue
            old_loyalty = int(row["loyalty"])
            new_loyalty = max(0, min(100, old_loyalty + raw_delta))
            origin_error = origin_rejected(item)
            if origin_error:
                applied.append(origin_error)
                continue
            db.conn.execute(
                "UPDATE characters SET loyalty=? WHERE name=?",
                (new_loyalty, name),
            )
            if content is not None and name in content.characters:
                content.characters[name].loyalty = new_loyalty
            result = {
                "name": name,
                "动作": action,
                "loyalty": raw_delta,
                "old_loyalty": old_loyalty,
                "new_loyalty": new_loyalty,
                "reason": str(item.get("reason") or ""),
            }
            applied.append(result)
            log_applied(result, item, commit=False)
            needs_person_change_commit = True
            continue

        if action in {"处置", "罢黜"}:
            status = "dismissed" if action == "罢黜" else str(item.get("status") or "").strip()
            reason_text = str(item.get("reason") or item.get("status_reason") or "")
            if status not in person_statuses:
                applied.append(rejected(item, "status 非白名单", "invalid_enum", status=status))
                continue
            if status not in disposition_statuses:
                applied.append(
                    rejected(
                        item,
                        "处置 不直接迁入 active/candidate，走任命/册封级联",
                        "invalid_transition",
                        status=status,
                    )
                )
                continue
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id", status=status))
                continue
            row = db.conn.execute("SELECT name FROM characters WHERE name=?", (name,)).fetchone()
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id", status=status))
                continue
            cur_status, _ = db.get_character_status(name)
            if item.get("legacy_gate") and cur_status != "active":
                reject_reason = f"当前非 active（{cur_status}）"
                if cur_status == "dead" and status != "dead":
                    reject_reason = "dead 无 status 出边"
                applied.append(
                    rejected(
                        item,
                        reject_reason,
                        "invalid_transition",
                        status=status,
                    )
                )
                continue
            reason_code = normalize_reason_code(item.get("reason_code"))
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=reason_code,
            )
            if transition.startswith("reject:"):
                reject_reason = f"{cur_status} 无 {action} 出边"
                if cur_status == "dead" and status != "dead":
                    reject_reason = "dead 无 status 出边"
                applied.append(
                    rejected(
                        item,
                        reject_reason,
                        transition.removeprefix("reject:") or "invalid_transition",
                        status=status,
                    )
                )
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                applied.append(origin_error)
                continue
            if action == "罢黜" and _payload_owned_person_duplicate(db, item):
                continue
            db.set_character_status(
                state,
                name,
                status,
                reason_text,
                reason_code=reason_code if reason_code else None,
                commit=commit_person_change,
            )
            if content is not None and name in content.characters:
                ch = content.characters[name]
                ch.status = status
                ch.status_reason = reason_text
                ch.reason_code = str(reason_code or "")
                if status in {"offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}:
                    ch.office = ""
                    ch.transit_to = ""
            result = {
                "name": name,
                "动作": action,
                "status": status,
                "reason": reason_text,
            }
            if reason_code:
                result["reason_code"] = reason_code
            applied.append(result)
            log_applied(result, item)
            continue

        if action in {"任命", "调任"}:
            # 别名归一已在动作分派前统一完成，确保任命与处置/行止/易主同口径。
            try:
                appointment_tenure = appointment_tenure_from(item)
            except ValueError:
                applied.append(rejected(item, "任别非白名单", "invalid_enum"))
                continue
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = character_row(name)
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            current_office = str(row["office"] or "").strip()
            current_office_type = str(row["office_type"] or "").strip()
            current_title_kind = (
                "身名分"
                if not current_office
                or current_office_type == "身名分"
                or current_office in PERSON_IDENTITY_TITLES
                else "职名分"
            )
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                action,
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
                current_title_kind=current_title_kind,
            )
            if transition.startswith("reject:"):
                applied.append(
                    rejected(
                        item,
                        f"{row['status']} 无 {action} 出边",
                        transition.removeprefix("reject:") or "invalid_transition",
                    )
                )
                continue
            derive_label = transition.removeprefix("derive:") if transition.startswith("derive:") else ""
            effective_action = transition.removeprefix("normalize:") if transition.startswith("normalize:") else action
            new_office = str(item.get("office") or item.get("new_office") or "")
            if not new_office.strip():
                result = rejected(item, "name 或 new_office 空", "missing_field")
                result["new_office"] = new_office
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            if content is None:
                if _payload_owned_person_duplicate(
                    db,
                    item,
                    current_office_type=current_office_type,
                    llm_config=llm_config or db.llm_config,
                ):
                    continue
                result = {
                    "动作": effective_action,
                    **apply_office_appointment(
                        db,
                        state,
                        content,
                        registry,
                        name,
                        new_office,
                        reason=str(item.get("reason") or ""),
                        new_office_type=str(item.get("office_type") or item.get("new_office_type") or ""),
                        faction=str(item.get("faction") or "中立"),
                        appointment_tenure=appointment_tenure,
                        llm_config=llm_config,
                        commit=commit_person_change,
                    ),
                }
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            row_power_id = str(row["power_id"] or "").strip()
            content_power_id = ""
            if content is not None and name in content.characters:
                content_power_id = str(getattr(content.characters[name], "power_id", "") or "").strip()
            effective_power_id = row_power_id or content_power_id or "ming"
            if effective_power_id != "ming":
                result = rejected(
                    item,
                    f"{name}不属大明朝廷，不能授予大明官职",
                    "invalid_transition",
                )
                result["new_office"] = new_office.strip()
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                applied.append(origin_error)
                continue
            if _payload_owned_person_duplicate(
                db,
                item,
                current_office_type=str(content.characters[name].office_type or ""),
                llm_config=llm_config or db.llm_config,
            ):
                continue
            if derive_label:
                release_status = "offstage" if derive_label in {"放归", "赦还"} else "active"
                # 必要前置（放归/赦还）执行 status 迁移原语（→offstage 居家），再由任命级联置 active。
                # 政治标记（起复/昭雪/夺情）为纯审计记录、不迁移 status（决定4）——status→active+绑名分
                # 由下面 apply_office_appointment 原子完成，避免「先置 active、名分未绑」的中间态（不变式1 全程成立）。
                if derive_label in {"放归", "赦还"}:
                    db.set_character_status(
                        state,
                        name,
                        release_status,
                        derive_label,
                        reason_code="",
                        commit=commit_person_change,
                    )
                    if content is not None and name in content.characters:
                        ch = content.characters[name]
                        ch.status = release_status
                        ch.office = ""
                        ch.transit_to = ""
                release_result = {
                    "name": name,
                    "动作": "处置",
                    "status": release_status,
                    "reason": derive_label,
                    "derived_from": derive_label,
                    # applier 合成级联回声（放归/赦还/起复/昭雪/夺情）：
                    # 信用写端只消费 extractor 宣告本体行，禁盯 derived_from 文本特判。
                    "cascade_echo": True,
                }
            result = apply_office_appointment(
                db,
                state,
                content,
                registry,
                name,
                new_office,
                reason=str(item.get("reason") or ""),
                new_office_type=str(item.get("office_type") or item.get("new_office_type") or ""),
                faction=str(item.get("faction") or "中立"),
                appointment_tenure=appointment_tenure,
                llm_config=llm_config,
                commit=commit_person_change,
            )
            wrapped = {"动作": effective_action, **result}
            if derive_label:
                wrapped["derived_from"] = derive_label
                if wrapped.get("rejected"):
                    # transit_start_turn 与 transit_to 成对回滚：派生任命前置 set_character_status
                    # （放归/赦还→offstage 属 ousted）现会清 transit_start_turn=0，回滚须对称还原，
                    # 否则留「transit_to 非空 + start=0」被兜底当 legacy-overdue 误判（CMR r2 防御）。
                    db.conn.execute(
                        "UPDATE characters SET status=?, office=?, office_type=?, "
                        "status_reason=?, status_changed_turn=?, reason_code=?, transit_to=?, "
                        "transit_start_turn=? WHERE name=?",
                        (
                            row["status"],
                            row["office"],
                            row["office_type"],
                            row["status_reason"],
                            row["status_changed_turn"],
                            row["reason_code"],
                            row["transit_to"],
                            row["transit_start_turn"],
                            name,
                        ),
                    )
                    if commit_person_change:
                        db.conn.commit()
                    if content is not None and name in content.characters:
                        ch = content.characters[name]
                        ch.status = str(row["status"] or "")
                        ch.office = str(row["office"] or "")
                        ch.office_type = str(row["office_type"] or ch.office_type)
                        ch.transit_to = str(row["transit_to"] or "")
                        # 对称 DB 侧回滚（上方 UPDATE 已还原全 7 字段）：内存也还原缘由/码，
                        # 守三面同步（决定6），免前置步刷过内存缘由后此路回滚留脏值（PR#106 R2 gemini）。
                        ch.status_reason = str(row["status_reason"] or "")
                        ch.reason_code = str(row["reason_code"] or "")
                else:
                    applied.append(release_result)
                    log_applied(release_result, item)
            elif transition.startswith("normalize:"):
                wrapped["normalized"] = f"{action}->{effective_action}"
            applied.append(wrapped)
            log_applied(wrapped, item)
            for displacement_result in displaced_talent_pool_results(wrapped.get("displaced")):
                applied.append(displacement_result)
                log_applied(displacement_result, item)
            continue

        if action == "易主":
            way = str(item.get("方式") or item.get("way") or "").strip()
            backlash = item.get("反噬", item.get("backlash"))
            legacy_partial = allow_legacy_partial_power and bool(item.get("legacy_partial"))
            if not way:
                applied.append(rejected(item, "易主 缺 方式", "missing_field"))
                continue
            if way not in PERSON_ALLEGIANCE_CHANGE_WAYS and not legacy_partial:
                applied.append(rejected(item, "易主 方式非白名单", "invalid_enum"))
                continue
            if not isinstance(backlash, dict):
                applied.append(rejected(item, "易主 缺 反噬", "missing_field"))
                continue
            if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
                applied.append(rejected(item, "易主 反噬 项必须是 object(dict)", "invalid_enum"))
                continue
            row = character_row(name)
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                action,
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
            )
            if transition.startswith("reject:"):
                applied.append(
                    rejected(
                        item,
                        f"{row['status']} 无 {action} 出边",
                        transition.removeprefix("reject:") or "invalid_transition",
                    )
                )
                continue
            requested_new_power = str(item.get("new_power") or "")
            old_power = str(row["power_id"] or "").strip()
            if way == "主动归附" and requested_new_power == "ming":
                backlash_power_ids = {
                    str(power_id).strip()
                    for power_id in backlash.keys()
                    if str(power_id).strip()
                }
                if any(power_id != old_power for power_id in backlash_power_ids):
                    applied.append(
                        rejected(
                            item,
                            f"主动归附反噬只能指向原势力股 {old_power}",
                            "invalid_transition",
                        )
                    )
                    continue
            new_title = identity_title_for_allegiance(item, requested_new_power)
            if not new_title:
                applied.append(
                    rejected(
                        item,
                        "易主 new_title 非身名分白名单",
                        "invalid_enum",
                    )
                )
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                applied.append(origin_error)
                continue
            # #522：招抚案卷效果绑定 canonical target；generic special_decree
            # 不得授权招抚式易主。其它 dossier/盘面自发路径保持既有授权。
            if require_origin and str(origin_ref or "").startswith("dossier:"):
                try:
                    dossier_id = _parse_sqlite_id(str(origin_ref).split(":", 1)[1])
                except ValueError:
                    dossier_id = 0
                dossier = db.get_decree_dossier(dossier_id) if dossier_id else None
                if dossier is not None:
                    action_type = str(dossier.get("action_type") or "").strip()
                    if (
                        action_type == "special_decree"
                        and way == "主动归附"
                        and requested_new_power == "ming"
                    ):
                        applied.append(
                            rejected(
                                item,
                                "special_decree 不得授权招抚易主",
                                "invalid_origin_ref",
                            )
                        )
                        continue
                    if action_type == "pacification":
                        try:
                            payload = dossier.get("payload") or json.loads(
                                str(dossier.get("payload_json") or "{}")
                            )
                        except (TypeError, ValueError):
                            payload = {}
                        if not isinstance(payload, dict):
                            payload = {}
                        bound_target = str(
                            payload.get("target_id") or dossier.get("target_id") or ""
                        ).strip()
                        if not bound_target or name != bound_target:
                            applied.append(
                                rejected(
                                    item,
                                    f"招抚案卷仅可易主 {bound_target or '案卷目标'}，不得易主 {name}",
                                    "invalid_origin_ref",
                                )
                            )
                            continue
            power_results = db.apply_character_power_changes(
                [
                    {
                        "name": name,
                        "new_power": requested_new_power,
                        "reason": str(item.get("reason") or ""),
                    }
                ],
                commit=commit_person_change,
            )
            if not power_results:
                applied.append(rejected(item, "易主 未产生变更", "noop"))
                continue
            accepted_power_results = [r for r in power_results if not r.get("rejected")]
            if not accepted_power_results:
                for result in power_results:
                    wrapped = {"动作": action, "方式": way, "反噬": backlash, **result}
                    if wrapped.get("rejected"):
                        wrapped["item"] = dict(item)
                    applied.append(wrapped)
                continue
            backlash_results = db.apply_power_deltas(
                state,
                backlash,
                commit=commit_person_change,
                origin_ref=origin_ref,
                require_origin=True,
            ) if backlash else []
            for result in power_results:
                new_power = str(result.get("new_power") or "")
                if (
                    not result.get("rejected")
                    and content is not None
                    and result.get("name") in content.characters
                ):
                    ch = content.characters[str(result["name"])]
                    ch.power_id = new_power
                    ch.office = new_title
                    ch.office_type = "身名分"
                    ch.status = "active"
                    ch.transit_to = ""
                    ch.reason_code = ""
                    ch.status_reason = str(item.get("reason") or "")
                # 易主后人仍 active（在新主任事，持身名分=降臣/归附），不变式1 不破；清原 reason_code/
                # status_reason（如陷虏「松山兵败被执」）——已投敌、不再是本朝在押，旧因不能滞留（决定3）；
                # status_changed_turn 记本回合（易主即状态变更）。
                db.conn.execute(
                    "UPDATE characters SET office=?, office_type=?, status='active', "
                    "reason_code='', status_reason=?, status_changed_turn=?, transit_to='', transit_start_turn=0 WHERE name=?",
                    (new_title, "身名分", str(item.get("reason") or ""), state.turn, name),
                )
                if commit_person_change:
                    db.conn.commit()
                wrapped = {"动作": action, "方式": way, "反噬": backlash, **result}
                wrapped["new_title"] = new_title
                if any(r.get("rejected") for r in backlash_results if isinstance(r, dict)):
                    wrapped["backlash_results"] = backlash_results
                applied.append(wrapped)
                log_applied(wrapped, item)
            continue

        if action == "册封":
            if content is None:
                applied.append(rejected(item, "无 content，跳过册封", "missing_ref"))
                continue
            office = str(item.get("office") or item.get("位号") or "").strip()
            office_type = str(item.get("office_type") or item.get("官署类别") or "后宫").strip()
            if office_type != "后宫":
                applied.append(rejected(item, "册封 仅适用于后宫 office_type", "invalid_transition"))
                continue
            from ming_sim.session import _find_candidate_by_name, apply_appointment

            if _find_candidate_by_name(content, name) is None:
                if item.get("legacy_appointment"):
                    applied.append(rejected(item, "册封建档被拒", "appointment_rejected"))
                else:
                    applied.append(rejected(item, "非既有 candidate", "hallucinated_id"))
                continue

            approved = item.get("approved", item.get("准许", True))
            origin_error = origin_rejected(item)
            if origin_error:
                applied.append(origin_error)
                continue
            appointed, displaced = apply_appointment(
                db,
                state,
                content,
                registry,
                {
                    "name": name,
                    "office": office,
                    "office_type": "后宫",
                    "faction": "后宫",
                    "reason": str(item.get("reason") or ""),
                    "approved": approved,
                },
                llm_config=llm_config,
                commit=commit_person_change,
            )
            if appointed:
                result: Dict[str, object] = {
                    "name": appointed,
                    "动作": action,
                    "office": office,
                    "office_type": "后宫",
                    "reason": str(item.get("reason") or ""),
                }
                if displaced:
                    result["displaced"] = displaced
                applied.append(result)
                log_applied(result, item)
            else:
                applied.append(rejected(item, "册封建档被拒", "appointment_rejected"))
            continue

        if action == "行止":
            new_location = str(item.get("location") or "").strip()
            transit_to = str(item.get("transit_to") or "").strip()
            if not new_location and not transit_to:
                applied.append(rejected(item, "location 或 transit_to 缺失", "missing_field"))
                continue
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = db.conn.execute(
                "SELECT status, location, transit_to, transit_start_turn "
                "FROM characters WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            if row["status"] != "active":
                applied.append(
                    rejected(item, "行止 仅适用于 active 人物", "invalid_transition")
                )
                continue
            for field_name, region_id in (
                ("location", new_location),
                ("transit_to", transit_to),
            ):
                if not region_id:
                    continue
                region_row = db.conn.execute(
                    "SELECT 1 FROM regions WHERE id=?", (region_id,)
                ).fetchone()
                if region_row is None:
                    applied.append(
                        rejected(item, f"{field_name} 地区不存在", "missing_ref")
                    )
                    break
            else:
                location = new_location or str(row["location"] or "")
                if location == str(row["location"] or "") and transit_to == str(row["transit_to"] or ""):
                    continue
                origin_error = origin_rejected(item)
                if origin_error:
                    applied.append(origin_error)
                    continue
                # transit_start_turn 记启程回合，供 force_transit_arrivals 计在途时长。
                # re-emit 同一在途目的地时保留原启程回合，否则逐月刷新会使
                # `turn - start >= 2` 永不成立、兜底失效、永久在途（CMR P2 / #346）。
                # 保留须含 prev_start==0 的旧数据哨兵：0 表「启程未知，按超期处理」，
                # 同目的地 re-emit 不得把它刷成 state.turn，否则旧数据反被「洗白」成
                # 新在途、逃过 force_transit_arrivals 的 0 兜底（CMR 跨片复审）。
                if transit_to:
                    prev_transit_to = str(row["transit_to"] or "")
                    prev_start = int(row["transit_start_turn"] or 0)
                    if transit_to == prev_transit_to:
                        new_transit_start_turn = prev_start
                    else:
                        new_transit_start_turn = state.turn
                else:
                    new_transit_start_turn = 0
                db.conn.execute(
                    "UPDATE characters SET location=?, transit_to=?, transit_start_turn=? WHERE name=?",
                    (location, transit_to, new_transit_start_turn, name),
                )
                if commit_person_change:
                    db.conn.commit()
                if content is not None and name in content.characters:
                    ch = content.characters[name]
                    ch.location = location
                    ch.transit_to = transit_to
                applied.append(
                    result := {
                        "name": name,
                        "动作": action,
                        "location": location,
                        "transit_to": transit_to,
                    }
                )
                log_applied(result, item)
            continue

        applied.append(
            rejected(item, "人物变更动作写路径未接", "invalid_transition")
        )
    if needs_person_change_commit and commit_person_change:
        db.conn.commit()
    return applied


def _legacy_person_report_section(result: Dict[str, object]) -> str:
    item = result.get("item")
    source = item if isinstance(item, dict) else result
    action = str(source.get("动作") or source.get("action") or result.get("动作") or "").strip()
    if source.get("legacy_gate"):
        return "character_status_changes"
    if source.get("legacy_partial"):
        return "character_power_changes"
    if source.get("legacy_spillover"):
        return "office_changes"
    if action == "册封":
        return "appointments"
    if action in {"任命", "调任"}:
        return "office_changes"
    return ""


def _apply_dossier_participant_items(
    db: GameDB,
    state: GameState,
    extracted: Dict[str, object],
    *,
    items_key: str,
    authority_set: set,
    not_in_batch_msg: str,
) -> List[Dict[str, object]]:
    """Shared control flow for public/secret roster apply; fields stay separate.

    items_key / authority_set / not_in_batch_msg stay caller-owned — never union
    the two closed authority sets, never share a field-name or result slot.
    Missing authority is an empty closed set; never reconstruct from live DB.
    """
    results: List[Dict[str, object]] = []
    if not isinstance(authority_set, set):
        authority_set = set()
    for item in extracted.get(items_key) or []:
        if not isinstance(item, dict):
            results.append({
                "rejected": True, "category": "invalid_shape", "item": item,
            })
            continue
        try:
            dossier_id = _parse_sqlite_id(item.get("dossier_id"))
            if dossier_id not in authority_set:
                raise ValueError(not_in_batch_msg)
            character_id = str(item.get("character_id") or "").strip()
            delegator_id = str(item.get("delegator_id") or "").strip()
            tier = str(item.get("tier") or "").strip()
            if not character_id:
                raise ValueError("追加参与人物不能为空")
            if tier not in {"主办", "协办", "知情"}:
                raise ValueError("追加参与层级必须为主办/协办/知情")
            if not delegator_id:
                raise ValueError("追加参与人必须注明委派人")
            added = db.append_decree_dossier_participants(dossier_id, [{
                "character_id": character_id,
                "tier": tier,
                "role": str(item.get("role") or "").strip(),
                "delegator_id": delegator_id,
            }], state=state, commit=False)
            if not added:
                # Exact durable duplicate is the only no-write success case.
                existing = db.get_decree_dossier(dossier_id) or {}
                if not any(
                    row.get("character_id") == character_id
                    and row.get("tier") == tier
                    and row.get("role") == str(item.get("role") or "").strip()
                    and row.get("delegator_id") == delegator_id
                    for row in existing.get("participant_roster", [])
                ):
                    raise ValueError("参与人未实际加入案卷")
            persisted = added[0] if added else {
                "character_id": character_id, "tier": tier,
            }
            results.append({
                "dossier_id": dossier_id,
                "character_id": persisted["character_id"], "tier": persisted["tier"],
            })
        except (TypeError, ValueError, KeyError) as exc:
            results.append({
                "rejected": True, "category": "invalid_participant_roster",
                "reason": str(exc), "item": item,
            })
    return results


def apply_score_extraction(
    db: GameDB,
    state: GameState,
    extracted: Dict[str, object],
    content=None,
    registry=None,
    llm_config: Any = None,
    candidate_event_ids_at_input: Optional[set[str]] = None,
    dossier_ids_at_input: Optional[set[int]] = None,
    secret_dossier_ids_at_input: Optional[set[int]] = None,
) -> Dict[str, object]:
    """落地结算 agent 输出的 JSON 到 state 与 db。

    content/registry：若传入则处理 `appointments`——把诏书任命的新人建档入朝。
    缺省则跳过（向后兼容老调用）。"""
    caller_transaction = db.conn.in_transaction
    commit_now = not caller_transaction
    if caller_transaction:
        _register_runtime_rollback_snapshot(db, state, content, registry)
    # #633 T1 r5 owner 裁决（B 案）：结算口边事件端点资格＝批内瞬态 canonical
    # 名册并集。此处取 pre-roster 观察点（任何人物变更 apply 前）；post-roster
    # 在人物变更全部落定后、relations 解析前另取。不建持久 snapshot、不新增
    # 编排：atomic 回滚重试重新进入本函数时由同一 pre-state 自然重算。
    _relation_pre_roster = {
        row["name"] for row in db.current_court_roster_rows(state)
    }
    # 0) 落库前校验/净化容器与可拆项；ADR0015 下可拆坏项逐项拒收，不再整批 abort。
    extracted, validate_rejections = sanitize_delta_shape(extracted)
    # #623：召对 extraction 真入口——反悔/坚持消费哭谏条（须先于 cancels 物化，
    # 使 persist 先结账，cancels 环看到已非 active 而跳过，防双路径）。
    from ming_sim.breach_plea import resolve_breach_pleas_from_extraction
    breach_plea_resolutions = resolve_breach_pleas_from_extraction(
        db, state, extracted, commit=False,
    )
    # #628 / 0079：信用事件写端后置于各模块校验落格之后（见 return 前），
    # 只消费未 rejected 项——禁为被拒 fulfilled/人事立伪信用档。
    # Only the caller's frozen simulator input grants roster-write authority.
    # Public/secret field names and authority sets stay separate (no union).
    dossier_participant_results = _apply_dossier_participant_items(
        db, state, extracted,
        items_key="dossier_participants",
        authority_set=dossier_ids_at_input if isinstance(dossier_ids_at_input, set) else set(),
        not_in_batch_msg="案卷不在本批可见输入",
    )
    # #1252: independent secret-dossier roster field (field name = provenance).
    secret_dossier_participant_results = _apply_dossier_participant_items(
        db, state, extracted,
        items_key="secret_dossier_participants",
        authority_set=(
            secret_dossier_ids_at_input
            if isinstance(secret_dossier_ids_at_input, set) else set()
        ),
        not_in_batch_msg="密令案卷不在本批可见输入",
    )

    dossier_execution_results: List[Dict[str, object]] = []
    # #621 接管窗：正式复核所辖案卷禁 extractor 并行终值（防第二真源）。
    # 所有权查询失败须响亮上抛——不得 fail-open 成空集放行第二真源（ADR 0005 / 0076）。
    from ming_sim.due_review import dossiers_with_pending_due_review
    _due_review_owned = dossiers_with_pending_due_review(db, state)
    for item in extracted.get("dossier_executions") or []:
        if not isinstance(item, dict):
            dossier_execution_results.append({
                "rejected": True, "category": "invalid_shape", "item": item,
            })
            continue
        try:
            dossier_id = _parse_sqlite_id(item.get("dossier_id"))
            if int(dossier_id) in _due_review_owned:
                raise ValueError("正式复核接管：extractor 不得并行写执行格终值")
            dossier = db.get_decree_dossier(dossier_id)
            if dossier is None or dossier["status"] != "executing":
                raise ValueError("案卷不存在或不在 executing")
            outcome = str(item.get("outcome") or "").strip()
            if outcome not in {"fulfilled", "degraded", "failed", "transformed"}:
                raise ValueError(
                    "执行结果必须为 fulfilled/degraded/failed/transformed"
                )
            note = str(item.get("note") or "").strip()
            if not note:
                raise ValueError("执行说明不能为空")
            # #565：显式 affected_parties 仅校验门闩（契约§5），不驱动机械写路。
            raw_parties = (
                item["affected_parties"] if "affected_parties" in item else None
            )
            if (
                raw_parties is not None
                and outcome in GameDB._JOINT_LIABILITY_TRIGGERS
            ):
                db.validate_joint_liability_affected_parties(raw_parties, outcome)
            db.record_dossier_execution(
                dossier_id, outcome, note, state.turn, close=True, commit=False,
            )
            # #567：S10 结案同源读被护侧对账，经 merge_execution_note 增补（单写口）。
            db.merge_grant_reconciliation_into_execution_note(
                dossier_id, commit=False,
            )
            # #619/#622：表报终值旁路——仅 degraded/transformed 挂奏报行；
            # 变形案载承办人假象（不得回填判官真值）；progress_band 定性中文。
            if outcome in {"degraded", "transformed"}:
                prior = list(db.list_dossier_progress(int(dossier_id)))
                band, memorial = terminal_report_facade(
                    outcome, prior_reports=prior,
                )
                db.record_dossier_progress(
                    dossier_id, state.turn, band, memorial,
                    is_terminal=True,
                    origin=GameDB.DOSSIER_REPORT_ORIGIN_VERDICT,
                    commit=False,
                )
            # 连坐挂载点＝本适配器落终值笔；禁对 execution_outcome 列事后扫描。
            # 触发过滤由 apply 内 _JOINT_LIABILITY_TRIGGERS 单一真源承担。
            db.apply_execution_joint_liability(
                state, dossier_id, outcome, reason=note, commit=False,
            )
            dossier_execution_results.append({
                "dossier_id": dossier_id, "outcome": outcome,
            })
        except (TypeError, ValueError, KeyError) as exc:
            dossier_execution_results.append({
                "rejected": True, "category": "invalid_transition",
                "reason": str(exc), "item": item,
            })

    authority_change_results: List[Dict[str, object]] = []
    for item in extracted.get("authority_changes") or []:
        if not isinstance(item, dict):
            authority_change_results.append({
                "rejected": True, "category": "invalid_shape", "item": item,
                "reason": "授权变更项必须为对象",
            })
            continue
        try:
            authority_change_results.append(
                _apply_authority_change_item(db, state, item)
            )
        except (TypeError, ValueError, KeyError) as exc:
            reason = str(exc)
            category = "invalid_authority_change"
            if reason in {
                "missing_dossier_source",
                "dossier_not_effect_eligible",
                "duplicate_active_authority",
                "invalid_authority_scope",
                "unknown_authority_id",
                "already_revoked",
            }:
                category = reason
            authority_change_results.append({
                "rejected": True, "category": category,
                "reason": reason, "item": item,
            })

    runtime_content = content if content is not None else _ctx()
    candidate_event_ids_authoritative = candidate_event_ids_at_input is not None
    if candidate_event_ids_at_input is None:
        candidate_event_ids_at_input = {candidate.id for candidate in gather_candidate_events(state, db)}
    else:
        candidate_event_ids_at_input = set(candidate_event_ids_at_input)
    new_person_changes = normalize_person_changes({"人物变更": extracted.get("人物变更") or []})
    legacy_person_changes = [] if new_person_changes else normalize_person_changes({
        "appointments": extracted.get("appointments") or [],
        "character_status_changes": extracted.get("character_status_changes") or [],
        "character_power_changes": extracted.get("character_power_changes") or [],
        "office_changes": extracted.get("office_changes") or [],
    })
    person_changes = _canonicalize_person_change_names(
        new_person_changes or legacy_person_changes,
        runtime_content,
        db,
    )
    use_legacy_person_keys = not person_changes
    legacy_person_mode = bool(legacy_person_changes)
    strategic_event_pool_ids = _event_pool_ids_for_strategic_foreign_nodes(extracted, runtime_content)
    strategic_event_result_delta_event_ids = _event_result_delta_event_ids(
        set(_STRATEGIC_FOREIGN_NODE_OUTCOME_TARGETS),
        strategic_event_pool_ids,
        extracted,
        person_changes,
        db,
    )
    strategic_event_label_gate_ids = (
        strategic_event_pool_ids
        & strategic_event_result_delta_event_ids
        & candidate_event_ids_at_input
    )
    for event_id in sorted(strategic_event_label_gate_ids):
        # Missing labels are rejected per deferred event; this early pass fail-louds
        # only unknown labels for event outcomes that can actually pass the static
        # candidate/result gates.  Non-candidate hallucinations are rejected later
        # as ordinary event_pool rejects so unrelated deltas can still land.
        _strategic_event_outcome_label_or_error(event_id, extracted, runtime_content)
    strategic_event_delta_ids = set(strategic_event_result_delta_event_ids)
    strategic_event_referenced_ids = strategic_event_pool_ids | strategic_event_delta_ids
    unambiguous_strategic_event_pool_ids = _unambiguous_unanchored_event_ids(strategic_event_pool_ids)

    def _split_pre_issue_person_changes(changes: List[Dict[str, object]]) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        pre_issue: List[Dict[str, object]] = []
        post_issue: List[Dict[str, object]] = []
        for item in changes:
            if str(item.get("动作") or "").strip() == "评定":
                pre_issue.append(item)
            else:
                post_issue.append(item)
        return pre_issue, post_issue

    pre_issue_person_changes, post_issue_person_changes = _split_pre_issue_person_changes(person_changes)
    strategic_pre_issue_person_changes, pre_issue_person_changes = _split_strategic_person_result_changes(
        pre_issue_person_changes,
        strategic_event_referenced_ids,
        db,
    )
    strategic_post_issue_person_changes, post_issue_person_changes = _split_strategic_person_result_changes(
        post_issue_person_changes,
        strategic_event_referenced_ids,
        db,
    )
    strategic_person_result_changes = strategic_pre_issue_person_changes + strategic_post_issue_person_changes

    def _amnesty_conflict_power_ids(changes: List[Dict[str, object]]) -> set[str]:
        power_ids: set[str] = set()
        for item in changes:
            if str(item.get("动作") or "").strip() != "易主":
                continue
            if str(item.get("方式") or item.get("way") or "").strip() != "主动归附":
                continue
            if str(item.get("new_power") or "").strip() != "ming":
                continue
            backlash = item.get("反噬", item.get("backlash"))
            if not isinstance(backlash, dict):
                continue
            if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
                continue
            name = str(item.get("name") or "").strip()
            if content is not None:
                from ming_sim.session import _find_existing_minister
                name = _find_existing_minister(content, name, db) or name
            row = db.conn.execute(
                "SELECT status, power_id, reason_code FROM characters WHERE name=?",
                (name,),
            ).fetchone()
            if row is None:
                continue
            old_power = str(row["power_id"] or "").strip()
            if old_power in {"", "ming"}:
                continue
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                "易主",
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
            )
            if transition.startswith("reject:"):
                continue
            backlash_power_ids = {
                str(power_id).strip()
                for power_id in backlash.keys()
                if str(power_id).strip()
            }
            if any(power_id != old_power for power_id in backlash_power_ids):
                continue
            explicit_title = str(item.get("new_title") or item.get("title") or "").strip()
            if explicit_title and explicit_title not in PERSON_IDENTITY_TITLES:
                continue
            # Same-period amnesty claims the old stock even if the LLM forgot to put
            # the weakening in 反噬; a top-level update would be suppression ledgering.
            power_ids.add(old_power)
        return power_ids

    amnesty_conflict_power_ids = _amnesty_conflict_power_ids(person_changes)

    def _annotate_legacy_person_rejections(results: List[Dict[str, object]]) -> None:
        for result in results:
            if isinstance(result, dict) and result.get("rejected"):
                report_section = _legacy_person_report_section(result)
                if report_section:
                    result["report_section"] = report_section
                    if (
                        report_section == "character_power_changes"
                        and result.get("category") == "hallucinated_id"
                    ):
                        result["report_category"] = "missing_ref"

    applied_person_changes: List[Dict[str, object]] = []

    def _apply_normalized_person_changes(
        changes: List[Dict[str, object]],
        *,
        legacy: bool,
        origin_ref: str = "",
        require_origin: bool = True,
    ) -> List[Dict[str, object]]:
        if not changes:
            return []
        results = _apply_person_changes(
            db,
            state,
            changes,
            content=content,
            registry=registry,
            llm_config=llm_config,
            allow_legacy_partial_power=legacy,
            external_transaction=caller_transaction,
            origin_ref=origin_ref,
            require_origin=require_origin,
        )
        if legacy:
            _annotate_legacy_person_rejections(results)
        if origin_ref:
            for result in results:
                result.setdefault("origin_ref", origin_ref)
        applied_person_changes.extend(results)
        return results

    # 1) metric_delta
    applied_metric = _apply_metric_dict(state, extracted.get("metric_delta") or {}, db=db)
    # 2) economy_moves
    # 拒收项拆到独立 economy_moves_rejections 段（不污染玩家可见 economy_moves list；
    # 同 faction_delta_rejections 治理，#14 cmr r1 codex/P4）。
    economy_moves = []
    for move in extracted.get("economy_moves") or []:
        if not isinstance(move, dict):
            economy_moves.append(move)
            continue
        origin_ref = str(
            move.get("origin_ref") or move.get("来源引用") or ""
        ).strip()
        # #1503 单写者：仅按 origin_ref=dossier:<id> 复用既有 payload 案卷 provenance
        # 判重（_payload_owned_dossier_for_origin）。不得按 army+turn 吞掉同回合
        # 独立「盘面自发」补饷；已消费案卷身份由 extractor 输入接缝保留。
        if not origin_ref.startswith("dossier:"):
            economy_moves.append(move)
            continue
        try:
            prefix, raw_id = origin_ref.split(":")
            if prefix != "dossier":
                raise ValueError("案卷 origin_ref 前缀非法")
            dossier_id = _parse_sqlite_id(raw_id)
        except (TypeError, ValueError):
            # Malformed provenance is not a duplicate-allocation candidate;
            # retain it for the durable-write seam to reject and report.
            economy_moves.append(move)
            continue
        dossier = _payload_owned_dossier_for_origin(db, origin_ref)
        if dossier is None or str(dossier.get("action_type") or "") != "grant_allocation":
            economy_moves.append(move)
            continue
        # ADR 0055: structured allocation effects are materialized from the
        # dossier payload.  The extractor may repeat the same non-empty delta,
        # but origin-bound apply must not debit it twice.  Narrative dossiers
        # remain on the extractor rail.
    _eco_out = _apply_economy_list(
        db,
        state,
        economy_moves,
        commit=commit_now,
        require_origin=True,
    )
    applied_economy = [r for r in _eco_out if not r.get("rejected")]
    economy_rejections = [r for r in _eco_out if r.get("rejected")]
    # 3) faction_delta + class_delta（朝堂派系 + 社会阶级；联动靠 LLM，不在代码做）
    # 返回 (已落 delta dict, 拒收项列表)：dict 供 web 面板（形状不变），拒收列表置于
    # 独立 *_rejections 段供桥接收集器（ADR 0008 决定 1，#14/#63）——不复用 *_delta key
    # 覆盖面板数据（cmr r1 claude：复用同 key 会令面板把拒收项当 dict 误渲染）。
    applied_factions, faction_rejections = _apply_faction_dict(
        db,
        extracted.get("faction_delta") or {},
        commit=commit_now,
    )
    applied_classes, class_rejections = _apply_class_dict(
        db,
        extracted.get("class_delta") or {},
        commit=commit_now,
    )
    # 4) new_armies → region_delta / army_delta (复用旧 db 方法)
    region_deltas_raw = extracted.get("region_delta") or {}
    army_deltas_raw = extracted.get("army_delta") or {}
    power_updates_raw = extracted.get("power_updates") or {}
    new_armies_raw = extracted.get("new_armies") or []
    strategic_region_deltas_raw, ordinary_region_deltas_raw = _split_strategic_entity_deltas(
        region_deltas_raw,
        "regions",
        strategic_event_referenced_ids,
        unambiguous_strategic_event_pool_ids,
    )
    strategic_army_deltas_raw, ordinary_army_deltas_raw = _split_strategic_entity_deltas(
        army_deltas_raw,
        "armies",
        strategic_event_referenced_ids,
        unambiguous_strategic_event_pool_ids,
    )
    strategic_power_updates_raw, ordinary_power_updates_raw = _split_strategic_entity_deltas(
        power_updates_raw,
        "powers",
        strategic_event_referenced_ids,
        unambiguous_strategic_event_pool_ids,
    )
    strategic_new_armies_raw, ordinary_new_armies_raw = _split_strategic_new_armies(
        new_armies_raw,
        strategic_event_referenced_ids,
        unambiguous_strategic_event_pool_ids,
    )

    pseudo_event = Event(
        id="season",
        title="月末整体推演",
        kind="月末",
        summary="",
        urgency=0,
        severity=0,
        credibility=100,
        interests=[],
        audiences=[],
    )
    region_changes: List[Dict[str, object]] = []
    army_changes: List[Dict[str, object]] = []
    created_armies: List[Dict[str, object]] = []
    # 先建军：避免同回合 army_delta 引用新军被跳过。
    # ADR 0008 决定 1（PR2-S2）：LLM 脏数据（查无此地/此军、字段非法、值不可解析）在
    # 三个 db 方法内逐项拒收留痕（返回列表含 {"rejected": True, ...}，桥接自动收进
    # rejection_reports），好项照落、坏一项不带走整批；代码异常（bug 类）仍上抛到 settle
    # 层回滚整批，绝不吞。clamp 语义（城防炮 city_level×8、随军炮 cap12、火器 0-100）不变。
    for army_item in ordinary_new_armies_raw:
        origin_ref = str(army_item.get("origin_ref") or "").strip()
        created_armies.extend(db.create_armies_from_extraction(
            state, [army_item], actor="档房", commit=commit_now, origin_ref=origin_ref, require_origin=True,
        ))
    for region_id, raw_changes in ordinary_region_deltas_raw.items():
        origin_ref = str(raw_changes.get("origin_ref") or "").strip()
        payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
        region_changes.extend(db.apply_region_deltas(
            state, pseudo_event, None, "档房", {region_id: payload}, commit=commit_now, origin_ref=origin_ref, require_origin=True,
        ))
    for army_id, raw_changes in ordinary_army_deltas_raw.items():
        origin_ref = str(raw_changes.get("origin_ref") or "").strip()
        payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
        army_changes.extend(db.apply_army_deltas(
            state, pseudo_event, None, "档房", {army_id: payload}, commit=commit_now, origin_ref=origin_ref, require_origin=True,
        ))

    # 注：建筑的新建/变更/废止不走顶层字段，全由 issue 的 effect_on_resolve /
    #     effect_on_fail 里的 `buildings` 段在局势结案时落地（见 _apply_issue_buildings）。

    # 5) power_updates：非明势力三项简表（威望/实力/经济）落库
    # ADR 0008 决定 1:不再整段吞——LLM 脏数据(未知 power id/字段非法)在
    # apply_power_deltas 内逐项拒收留痕(返回列表含 {"rejected": True, ...});
    # 代码异常(KeyError/AttributeError 等)上抛到 settle 层回滚整批,绝不吞。
    power_changes: List[Dict[str, object]] = []
    if ordinary_power_updates_raw:
        power_updates_to_apply = dict(ordinary_power_updates_raw)
        for power_id in sorted(set(power_updates_to_apply) & amnesty_conflict_power_ids):
            raw_changes = power_updates_to_apply.pop(power_id)
            power_changes.append({
                "power_id": power_id,
                "rejected": True,
                "category": "invalid_transition",
                "reason": "同一股同一时段已有招安易主，拒绝顶层 power_updates 剿股；削股须随易主反噬一处落账",
                "item": {"power_id": power_id, "changes": raw_changes},
            })
        for power_id, raw_changes in power_updates_to_apply.items():
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            power_changes.extend(db.apply_power_deltas(
                state, {power_id: payload}, commit=commit_now, origin_ref=origin_ref, require_origin=True,
            ))

    for person_change in pre_issue_person_changes:
        origin_ref = str(person_change.get("origin_ref") or "").strip()
        clean_change = dict(person_change)
        _apply_normalized_person_changes([clean_change], legacy=legacy_person_mode, origin_ref=origin_ref)

    # 6) issue_advances / new_issues / close_issues / cancels (复用旧 tracker 落地)
    issue_summary = apply_issue_tracker_output(db, state, {
        "advances": extracted.get("issue_advances") or [],
        "new_issues": extracted.get("new_issues") or [],
        "close_issues": extracted.get("close_issues") or [],
        "cancels": extracted.get("cancels") or [],
    }, llm_config=llm_config, content=content,
        pending_person_changes_for_gates=post_issue_person_changes,
        allow_legacy_partial_power_for_gates=legacy_person_mode,
        candidate_event_ids_at_input=candidate_event_ids_at_input,
        candidate_event_ids_authoritative=candidate_event_ids_authoritative,
        event_result_delta_event_ids=strategic_event_result_delta_event_ids,
        defer_event_trigger_ids=strategic_event_pool_ids)

    commitment_economy_carriers: List[Dict[str, object]] = []
    for item in issue_summary.get("new_issues") or []:
        if not (
            isinstance(item, dict)
            and not item.get("rejected")
            and str(item.get("commitment_kind") or "").strip()
            and item.get("issue_id") is not None
        ):
            continue
        row = db.conn.execute("SELECT ongoing_effects FROM issues WHERE id=?", (int(item["issue_id"]),)).fetchone()
        if row is None:
            continue
        ongoing = loads_effect_dict(row["ongoing_effects"])
        commitment_economy_carriers.extend(_monthly_economy_items(ongoing))

    def _reject_suppressed_strategic_results(event_id: str, event_title: str, reason: str = "") -> None:
        event_region_deltas = _entity_deltas_for_strategic_event(
            strategic_region_deltas_raw,
            "regions",
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        event_army_deltas = _entity_deltas_for_strategic_event(
            strategic_army_deltas_raw,
            "armies",
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        event_power_updates = _entity_deltas_for_strategic_event(
            strategic_power_updates_raw,
            "powers",
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        event_person_changes = [
            item
            for item in strategic_person_result_changes
            if event_id in _strategic_person_result_event_ids(item, {event_id}, db)
        ]
        event_new_armies = _new_armies_for_strategic_event(
            strategic_new_armies_raw,
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        reason = reason or f"战略/外敌事件「{event_title or event_id}」未触发，战果不落主账"
        for region_id, raw_changes in event_region_deltas.items():
            region_changes.append({
                "region_id": region_id,
                "rejected": True,
                "category": "event_rejected",
                "reason": reason,
                "item": {"event_id": event_id, "region_id": region_id, "changes": raw_changes},
            })
        for army_id, raw_changes in event_army_deltas.items():
            army_changes.append({
                "army_id": army_id,
                "rejected": True,
                "category": "event_rejected",
                "reason": reason,
                "item": {"event_id": event_id, "army_id": army_id, "changes": raw_changes},
            })
        for power_id, raw_changes in event_power_updates.items():
            power_changes.append({
                "power_id": power_id,
                "rejected": True,
                "category": "event_rejected",
                "reason": reason,
                "item": {"event_id": event_id, "power_id": power_id, "changes": raw_changes},
            })
        for item in event_person_changes:
            applied_person_changes.append({
                "name": _person_change_name(item),
                "动作": str(item.get("动作") or item.get("action") or "").strip(),
                "rejected": True,
                "category": "event_rejected",
                "reason": reason,
                "item": dict(item),
            })
        for item in event_new_armies:
            raw_item = dict(item) if isinstance(item, dict) else item
            created_armies.append({
                "id": str(item.get("id") or "").strip() if isinstance(item, dict) else "",
                "rejected": True,
                "category": "event_rejected",
                "reason": reason,
                "item": {"event_id": event_id, "new_army": raw_item},
            })

    strategic_event_issue_ids_seen: set[str] = set()
    for new_issue in (issue_summary.get("new_issues") or []):
        if isinstance(new_issue, dict):
            event_id = str(new_issue.get("id") or "").strip()
            if event_id in strategic_event_referenced_ids:
                strategic_event_issue_ids_seen.add(event_id)
        if not isinstance(new_issue, dict) or not new_issue.get("rejected"):
            continue
        event_id = str(new_issue.get("id") or "").strip()
        if event_id not in strategic_event_referenced_ids:
            continue
        _reject_suppressed_strategic_results(event_id, str(new_issue.get("title") or ""))

    for event_id in sorted(strategic_event_delta_ids - strategic_event_issue_ids_seen):
        ev = runtime_content.event_by_id.get(event_id)
        _reject_suppressed_strategic_results(event_id, ev.title if ev is not None else event_id)

    for new_issue in (issue_summary.get("new_issues") or []):
        if not (
            isinstance(new_issue, dict)
            and new_issue.get("deferred_trigger")
            and not new_issue.get("rejected")
        ):
            continue
        event_id = str(new_issue.get("id") or "").strip()
        if event_id not in strategic_event_pool_ids:
            continue
        outcome_label, outcome_error = _strategic_event_outcome_label_or_error(
            event_id,
            extracted,
            runtime_content,
        )
        if outcome_error:
            new_issue["rejected"] = True
            new_issue["category"] = "missing_event_outcome"
            new_issue["reason"] = outcome_error
            _reject_suppressed_strategic_results(event_id, str(new_issue.get("title") or ""))
            continue
        event_region_deltas = _entity_deltas_for_strategic_event(
            strategic_region_deltas_raw,
            "regions",
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        event_army_deltas = _entity_deltas_for_strategic_event(
            strategic_army_deltas_raw,
            "armies",
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        event_power_updates = _entity_deltas_for_strategic_event(
            strategic_power_updates_raw,
            "powers",
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        event_person_changes = [
            item
            for item in strategic_person_result_changes
            if event_id in _strategic_person_result_event_ids(item, {event_id}, db)
        ]
        event_new_armies = _new_armies_for_strategic_event(
            strategic_new_armies_raw,
            event_id,
            allow_unanchored=event_id in unambiguous_strategic_event_pool_ids,
        )
        result_preflight_error = _strategic_event_result_preflight_error(
            db,
            state,
            event_id,
            str(new_issue.get("title") or ""),
            outcome_label,
            event_region_deltas,
            event_army_deltas,
            event_power_updates,
            event_person_changes,
            event_new_armies,
            content,
            llm_config,
            legacy_person_mode,
        )
        if result_preflight_error:
            new_issue["rejected"] = True
            new_issue["category"] = "invalid_event_result_delta"
            new_issue["reason"] = result_preflight_error
            _reject_suppressed_strategic_results(
                event_id,
                str(new_issue.get("title") or ""),
                reason=f"{result_preflight_error}；整组战果不落主账",
            )
            continue
        event_region_changes: List[Dict[str, object]] = []
        event_army_changes: List[Dict[str, object]] = []
        event_person_results: List[Dict[str, object]] = []
        event_created_armies: List[Dict[str, object]] = []
        event_power_changes: List[Dict[str, object]] = []
        for item in event_new_armies:
            origin_ref = str(item.get("origin_ref") or "").strip()
            event_created_armies.extend(db.create_armies_from_extraction(
                state, [item], actor="档房", commit=commit_now,
                origin_ref=origin_ref, require_origin=True,
            ))
        created_armies.extend(event_created_armies)
        for region_id, raw_changes in event_region_deltas.items():
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            event_region_changes.extend(db.apply_region_deltas(
                state, pseudo_event, None, "档房", {region_id: payload},
                commit=commit_now, origin_ref=origin_ref, require_origin=True,
            ))
        region_changes.extend(event_region_changes)
        for army_id, raw_changes in event_army_deltas.items():
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            event_army_changes.extend(db.apply_army_deltas(
                state, pseudo_event, None, "档房", {army_id: payload},
                commit=commit_now, origin_ref=origin_ref, require_origin=True,
            ))
        army_changes.extend(event_army_changes)
        for item in event_person_changes:
            origin_ref = str(item.get("origin_ref") or "").strip()
            clean_item = dict(item)
            event_person_results.extend(_apply_normalized_person_changes(
                [clean_item], legacy=legacy_person_mode, origin_ref=origin_ref, require_origin=True,
            ))
        for power_id, raw_changes in event_power_updates.items():
            origin_ref = str(raw_changes.get("origin_ref") or "").strip()
            payload = {k: v for k, v in raw_changes.items() if k != "origin_ref"}
            event_power_changes.extend(db.apply_power_deltas(
                state, {power_id: payload}, commit=commit_now,
                origin_ref=origin_ref, require_origin=True,
            ))
        power_changes.extend(event_power_changes)
        result_items = (
            event_created_armies
            + event_region_changes
            + event_army_changes
            + event_person_results
            + event_power_changes
        )
        if any(_strategic_result_item_has_material_world_state(item) for item in result_items):
            db.mark_event_triggered(state, event_id, terminal_reason=outcome_label, commit=commit_now)
            apply_event_cascading_invalidations(state, db, commit=commit_now)
            new_issue["reason"] = "事件已记为触发，软判结果已落主账"
        else:
            new_issue["rejected"] = True
            new_issue["category"] = "missing_world_state_delta"
            new_issue["reason"] = "战略/外敌战事缺世界状态主账结果（地区/军队/人物变更/新建军队均未成功）"
            _reject_suppressed_strategic_results(event_id, str(new_issue.get("title") or ""), reason=new_issue["reason"])
    for person_change in post_issue_person_changes:
        origin_ref = str(person_change.get("origin_ref") or "").strip()
        clean_change = dict(person_change)
        _apply_normalized_person_changes([clean_change], legacy=legacy_person_mode, origin_ref=origin_ref)

    def _norm_int_leaf(v):
        """无损整数串归一（cmr S3 r10,2/2）：strip 后能精确 int 的 str 转 int,
        其余原样返回。无损归一在 cleaner（引擎路）与此处（driver 路）各一次,
        **判定语义只在 applier**（ship-pre r1 措辞修正:cleaner 残留的同式转换
        与本函数同结果,见 S3 disposition「无害重复」）。"""
        if isinstance(v, str):
            try:
                return int(v.strip())
            except ValueError:
                return v
        return v

    # 6.4) fiscal_removes：推演彻底裁撤月固定收支项（罢税/裁俸），优先级最高，先于 creates/changes。
    #      含 dynamic（田赋/辽饷/盐税/商税/皇庄），后果玩家自负。删 base+rate 两行。
    applied_fiscal_removes: List[Dict[str, object]] = []
    for remove in extracted.get("fiscal_removes") or []:
        key = str(remove.get("key") or "").strip()
        if not key:
            # 空 key = 脏项,记拒留痕(不再纯静默 continue;ADR 决定 1 / S3)。
            applied_fiscal_removes.append({
                "rejected": True, "reason": "fiscal_removes 缺 key,无法定位裁撤目标。",
                "category": "invalid_enum", "item": remove,
            })
            continue
        if db._stem_of(key) == "":
            # 多重后缀垃圾 key = 非法,与 create 段同口径 invalid_enum——误标
            # missing_ref「不存在」会让机读聚合失真（cmr S3 r10）。
            applied_fiscal_removes.append({
                "rejected": True, "reason": f"裁撤 key「{key}」非法（多重 _base/_rate 后缀）。",
                "category": "invalid_enum", "item": remove,
            })
            continue
        if db.fiscal_config_loss_rate_pair(key) is not None:
            applied_fiscal_removes.append({
                "rejected": True,
                "reason": f"裁撤目标「{key}」是中央损耗率成对配置，不可裁撤。",
                "category": "invalid_enum", "item": remove,
            })
            continue
        if db.is_structural_fiscal_config_key(key):
            applied_fiscal_removes.append({
                "rejected": True,
                "reason": f"裁撤目标「{key}」是结构性财政地板，不可裁撤。",
                "category": "invalid_enum", "item": remove,
            })
            continue
        fiscal_config = db.get_fiscal_config()
        stem = db._stem_of(key)
        if key not in fiscal_config and not any(
            candidate in fiscal_config for candidate in (f"{stem}_base", f"{stem}_rate")
        ):
            applied_fiscal_removes.append({
                "rejected": True, "reason": f"裁撤目标「{key}」不存在,跳过。",
                "category": "missing_ref", "item": remove,
            })
            continue
        origin_ref = str(remove.get("origin_ref") or "").strip()
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            applied_fiscal_removes.append({**origin_error, "item": remove})
            continue
        removed_key = db.remove_fiscal_item(
            key, commit=commit_now, origin_ref=origin_ref,
            reason=str(remove.get("reason") or ""), turn=state.turn,
            beyond_intent=remove.get("beyond_intent"),
        )
        if removed_key is None:
            # 查无此项 = 正常业务拒绝,逐项拒收留痕(不再 print 静默跳;ADR 决定 1 / S3)。
            applied_fiscal_removes.append({
                "rejected": True, "reason": f"裁撤目标「{key}」不存在,跳过。",
                "category": "missing_ref", "item": remove,
            })
            continue
        applied_fiscal_removes.append({
            "key": removed_key, "reason": str(remove.get("reason") or ""),
        })

    # 6.5) fiscal_creates：推演凭空新立月固定收支项（税是其一种）。先于 fiscal_changes，
    #      使同{月}「新立关税 + 立即调率」可一气落地。
    applied_fiscal_creates: List[Dict[str, object]] = []
    for create in extracted.get("fiscal_creates") or []:
        # direction 同义词在唯一守门人处归一（cmr S3 r9:归一放 driver 不经过的
        # cleaner 层=同输入两判;DELTA_SCHEMA 明言吃中文别名）。表与 cleaner 共用
        # simulation._DIRECTION_NORMALIZE（懒 import 避循环）。先归一再去重：ADR0027
        # 承诺载体都是月度【支出】(delta<0)，dedup/残留观测只对【支出】fiscal_create 生效；
        # 同名的【收入】新科目(如新税)与承诺无关，绝不可被误去重或误报残留(codex correctness)。
        from ming_sim.simulation import _DIRECTION_NORMALIZE
        direction_raw = str(create.get("direction") or "").strip()
        direction = _DIRECTION_NORMALIZE.get(direction_raw, direction_raw)
        key = str(create.get("key") or "").strip()
        account = str(create.get("account") or "").strip()
        # key 空 / account / direction 非法 = 脏枚举,原先纯静默 continue,改记拒留痕
        # （ADR 决定 1 / S3；「在场即须合法」对称 S1/S2）。
        if not key or account not in _FISCAL_ACCOUNTS or direction not in _FISCAL_DIRECTIONS:
            applied_fiscal_creates.append({
                "rejected": True,
                "reason": f"新立项枚举非法（key={key!r} account={account!r} direction={direction!r}）。",
                "category": "invalid_enum", "item": create,
            })
            continue
        # init_value 缺省/null = 0 合法；在场脏值（字符串/float/bool/负值）显式拒，不静默归 0。
        # bool 是 int 子类，先于 int 判（对称 S1/S2）。
        init_raw = _norm_int_leaf(create.get("init_value"))  # 无损整数串归一（cmr S3 r10）
        if init_raw is None:
            init_value = 0
        elif isinstance(init_raw, bool) or not isinstance(init_raw, int) or init_raw < 0:
            # 负值同拒：静默 clamp 0 = 又一面「凭空建零值项」（cmr S3 r3）。
            applied_fiscal_creates.append({
                "rejected": True,
                "reason": f"新立项「{key}」初值 init_value 非法（{init_raw!r}，须非负整数），不静默归 0。",
                "category": "invalid_enum", "item": create,
            })
            continue
        else:
            init_value = init_raw
        # display 缺省=归一 stem（与落库同源——raw key 去 _base 会把「关税_rate」
        # 显示成「关税_rate」,cmr S3 r11;DELTA_SCHEMA 契约「缺省=key 去后缀」）。
        display = str(create.get("display") or "").strip() or (db._stem_of(key) or key)
        origin_ref = str(create.get("origin_ref") or "").strip()
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            applied_fiscal_creates.append({**origin_error, "item": create})
            continue
        # Dedup is a business rule, not an authorization gate.  It must only see
        # a shape-valid, canonically authorized carrier; otherwise it can hide a
        # missing/forged origin behind deduped_commitment_carrier.
        if direction == "expense":
            dedup_reason = _commitment_fiscal_create_duplicate_reason(
                create, commitment_economy_carriers, db
            )
            if dedup_reason:
                applied_fiscal_creates.append({
                    "rejected": True, "reason": dedup_reason,
                    "category": "deduped_commitment_carrier", "item": create,
                })
                continue
            residual_account = _commitment_carrier_same_account_unmatched(
                create, commitment_economy_carriers
            )
            if residual_account:
                residual_display = (
                    str(create.get("display") or "").strip()
                    or (db._stem_of(key) or key) or "无名月支"
                )
                tlog(
                    f"[commitment-dedup] ADR0027 残留观测：同批{residual_account}已有 decree 承诺月支，"
                    f"但 fiscal_create「{residual_display}」未按科目名匹配上、照常落账——疑似异名漏匹，试玩留意。"
                )
        new_key = db.create_fiscal_item(
            key, account, direction, display, init_value,
            note=str(create.get("reason") or "")[:120],
            origin_ref=origin_ref,
            turn=state.turn,
            beyond_intent=create.get("beyond_intent"),
            commit=commit_now,
        )
        if new_key is None:
            # 已存在 / db 拒 = 正常业务拒绝,逐项拒收留痕（不再 print 静默跳）。
            applied_fiscal_creates.append({
                "rejected": True,
                "reason": f"新立项「{key}」已存在或被落库拒绝,跳过。",
                "category": "invalid_enum", "item": create,
            })
            continue
        applied_fiscal_creates.append({
            "key": new_key, "account": account, "direction": direction,
            "display": display, "init_value": max(0, init_value),
            "reason": str(create.get("reason") or ""),
        })

    # 7) fiscal_changes：调整月度固定收支系数
    applied_fiscal: List[Dict[str, object]] = []
    fiscal_config_snapshot = db.get_fiscal_config()
    deferred_loss_pair_changes: List[Dict[str, object]] = []
    loss_pair_running: Dict[str, int] = {}
    loss_pair_final_by_pair: Dict[Tuple[str, str], Dict[str, int]] = {}
    for change in extracted.get("fiscal_changes") or []:
        key = str(change.get("key") or "").strip()
        if not key:
            # 空 key = 脏项,先于一切无操作短路记拒——否则 delta 0/null 的空 key 项
            # 被短路吞掉无痕（与 falsy 短路同类序错,cmr S3 r2）。
            applied_fiscal.append({
                "rejected": True,
                "reason": "调率项缺 key,无法定位科目。",
                "category": "invalid_enum", "item": change,
            })
            continue
        if db._stem_of(key) == "":
            # 多重后缀垃圾 key 与 create/remove 同口径 invalid_enum——标 missing_ref
            # 「不存在」会让机读聚合失真（ship-pre r5,三段补齐）。
            applied_fiscal.append({
                "rejected": True,
                "reason": f"调率 key「{key}」非法（多重 _base/_rate 后缀）。",
                "category": "invalid_enum", "item": change,
            })
            continue
        delta_raw = _norm_int_leaf(change.get("delta"))  # 无损整数串归一（cmr S3 r10）
        # delta 缺省 = 无操作,静默放过不记拒（免得每月刷无意义拒收行）。
        if delta_raw is None:
            continue
        # 脏值判定必须先于「==0 无操作」短路——False==0 / 0.0==0 为真,放后面会把
        # 脏 bool/float 静默吞掉（cmr S3 r1,顺序与 S1 对称）。
        # delta 在场但脏（字符串/float/bool）= LLM 脏数据,原裸 int() 静默 continue（吞），
        # 改显式拒留痕；bool 是 int 子类,先于 int 判（对称 S1/S2 / S3）。
        if isinstance(delta_raw, bool) or not isinstance(delta_raw, int):
            applied_fiscal.append({
                "rejected": True,
                "reason": f"调率 delta 非整数（{delta_raw!r}），不静默吞。",
                "category": "invalid_enum", "item": change,
            })
            continue
        if delta_raw == 0:
            # 显式 int 0 = 无操作（脏值已在上方拒掉,此处只剩真 int;空 key 已在循环顶记拒）。
            continue
        delta = delta_raw
        current = db.get_fiscal_config().get(key)
        if current is None:
            # 未知 key = 正常业务拒绝,逐项拒收留痕（不再 print 静默跳）。
            applied_fiscal.append({
                "rejected": True, "reason": f"调率目标「{key}」不存在,跳过。",
                "category": "missing_ref", "item": change,
            })
            continue
        origin_ref = str(change.get("origin_ref") or "").strip()
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            applied_fiscal.append({**origin_error, "item": change})
            continue
        loss_pair = db.fiscal_config_loss_rate_pair(key)
        if loss_pair is not None:
            current = loss_pair_running.get(key, fiscal_config_snapshot.get(key, current))
            new_val = max(0, current + delta)
            loss_pair_running[key] = new_val
            human_key, sink_key = loss_pair
            pair_values = loss_pair_final_by_pair.setdefault(loss_pair, {
                human_key: loss_pair_running.get(
                    human_key, fiscal_config_snapshot.get(human_key, 0)
                ),
                sink_key: loss_pair_running.get(
                    sink_key, fiscal_config_snapshot.get(sink_key, 0)
                ),
            })
            pair_values[key] = new_val
            deferred_loss_pair_changes.append({
                "pair": loss_pair,
                "key": key,
                "old": current,
                "new": new_val,
                "delta": delta,
                "reason": str(change.get("reason") or ""),
                "origin_ref": origin_ref,
                "item": change,
            })
            continue
        new_val = max(0, current + delta)
        try:
            db.validate_fiscal_config_value(key, new_val)
        except ValueError as exc:
            applied_fiscal.append({
                "rejected": True,
                "reason": f"调率目标「{key}」非法：{exc}",
                "category": "invalid_enum", "item": change,
            })
            continue
        db.set_fiscal_config(key, new_val, commit=False)
        db.conn.execute("UPDATE fiscal_config SET origin_ref=? WHERE key=?", (origin_ref, key))
        db.record_fiscal_config_change(
            turn=state.turn, key=key, old_value=current, new_value=new_val,
            origin_ref=origin_ref, reason=str(change.get("reason") or ""),
            beyond_intent=change.get("beyond_intent"),
        )
        # dynamic 税（辽饷/盐税/商税/田赋）实收走 region.fiscal，改 fiscal_config 不生效；
        # 按 new/old 比例同步缩放各省实收字段，使调额当真改变下月入账。皇庄读 config，无需联动。
        stem = db._stem_of(key)
        if stem in db._DYNAMIC_REGION_FIELD or stem == "田赋":
            ratio = (new_val / current) if current > 0 else (1.0 if new_val == 0 else 0.0)
            if stem == "田赋":
                db.scale_tian_fu(ratio, commit=False)
            else:
                db.apply_dynamic_fiscal_scale(stem, ratio, commit=False)
        applied_fiscal.append({
            "key": key, "old": current, "new": new_val, "delta": delta,
            "reason": str(change.get("reason") or ""),
        })
    for loss_pair, final_values in loss_pair_final_by_pair.items():
        pair_changes = [
            change for change in deferred_loss_pair_changes
            if change["pair"] == loss_pair
        ]
        try:
            db.set_fiscal_config_batch(final_values, commit=False)
        except ValueError as exc:
            for change in pair_changes:
                applied_fiscal.append({
                    "rejected": True,
                    "reason": f"调率目标「{change['key']}」非法：{exc}",
                    "category": "invalid_enum",
                    "item": change["item"],
                })
            continue
        for change in pair_changes:
            db.conn.execute(
                "UPDATE fiscal_config SET origin_ref=? WHERE key=?",
                (change["origin_ref"], change["key"]),
            )
            db.record_fiscal_config_change(
                turn=state.turn, key=str(change["key"]),
                old_value=int(change["old"]), new_value=int(change["new"]),
                origin_ref=str(change["origin_ref"]), reason=str(change["reason"]),
                beyond_intent=change["item"].get("beyond_intent")
                if isinstance(change.get("item"), dict) else 0,
            )
            applied_fiscal.append({
                "key": change["key"],
                "old": change["old"],
                "new": change["new"],
                "delta": change["delta"],
                "reason": change["reason"],
            })
    successful_authority_changes = [
        item for item in authority_change_results
        if isinstance(item, dict) and item.get("rejected") is not True
    ]
    if commit_now and (
        applied_fiscal or deferred_loss_pair_changes or successful_authority_changes
    ):
        db.conn.commit()

    # ADR0009 legacy aliases are canonicalized above and written only through
    # the canonical person-change applier.  Keep response keys for compatibility,
    # but do not retain a second set of direct writers here.
    applied_appointments: List[Dict[str, object]] = []
    applied_status_changes: List[Dict[str, object]] = []
    applied_power_changes: List[Dict[str, object]] = []
    applied_office_changes: List[Dict[str, object]] = []

    # 11) secret_order_updates：推演写 active 密令副作用（泄漏/反弹）到 sim_note。结案不走这里。
    applied_secret_orders: List[Dict[str, object]] = []
    for item in extracted.get("secret_order_updates") or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("order_id")
        sim_note = str(item.get("sim_note") or item.get("result") or "").strip()
        disclosed = item.get("disclosed") is True
        if raw_id is None or not sim_note:
            applied_secret_orders.append({"order_id": raw_id, "rejected": True,
                                          "category": "invalid_enum",
                                          "reason": "order_id 或 sim_note 缺失"})
            continue
        try:
            real_id = _parse_sqlite_id(raw_id)
        except (TypeError, ValueError):
            applied_secret_orders.append({"order_id": raw_id, "rejected": True,
                                          "category": "invalid_enum", "reason": "order_id 非整数或超界"})
            continue
        # 未知/非 active 密令的副作用写不进（_append_secret_order_line 静默返 False）→ 须显式拒收，
        # 否则未知 id 被无脑 append 成功 = 静默报「已应用」（cmr secret-order r1 codex，#14）。
        # 与 secret_order_closes 同结构对齐。
        order = db.get_secret_order(real_id)
        if order is None:
            applied_secret_orders.append({"order_id": real_id, "rejected": True,
                                          "category": "missing_ref", "reason": "密令不存在"})
            continue
        if order["status"] != "active":
            applied_secret_orders.append({"order_id": real_id, "rejected": True,
                                          "category": "invalid_enum",
                                          "reason": f"密令当前 {order['status']}，非 active，不写推演副作用"})
            continue
        try:
            db.update_secret_order_sim_note(
                real_id,
                sim_note,
                year=state.year,
                period=state.period,
                commit=commit_now,
            )
            if disclosed:
                # Disclosure is the only promotion from the assignee-only
                # brief into a public knowledge event (#883).
                # Cross-turn dedupe: disclosed is a state (prompt) not a monthly
                # event — re-true each month must not mint another public row.
                disclosure_prefix = f"secret_order_disclosure:{real_id}:"
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
                if already_disclosed is None:
                    dossier = db.get_dossier_for_secret_order(real_id)
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
                        commit=commit_now,
                    )
            print(f"[secret_order] 推演副作用 id={real_id} note={sim_note[:60]!r}")
            applied_secret_orders.append({
                "order_id": real_id, "sim_note": sim_note, "disclosed": disclosed,
            })
        except Exception as exc:
            applied_secret_orders.append({"order_id": real_id, "rejected": True, "reason": str(exc)})

    # 12) secret_order_closes：#1504 退役。结案真源改 settle 尾部机械对账；此处一律拒收。
    applied_secret_closes: List[Dict[str, object]] = []
    for item in extracted.get("secret_order_closes") or []:
        if not isinstance(item, dict):
            continue
        applied_secret_closes.append({
            "order_id": item.get("order_id"),
            "rejected": True,
            "retired": True,
            "category": "retired_source",
            "reason": "secret_order_closes 真源已退役；到期由实进度对账结案",
        })

    validate_rejection_items = [
        {
            "rejected": True,
            "item": item,
            "reason": reason,
            "category": "invalid_shape",
        }
        for _section, item, reason in validate_rejections
    ]
    raw_module_rejections = extracted.get("_module_rejections")
    module_rejections = [
        item for item in raw_module_rejections if isinstance(item, dict)
    ] if isinstance(raw_module_rejections, list) else []

    # #628 / 0079：校验后未 rejected 落格 → 信用事件同缝只写不读。
    # economy/fiscal 落格摘要会丢 purpose/issue_id；对拒收项（带 item=源对象）求差，
    # 保留源项叙事字段供识别，且不把被拒项喂进信用写端。
    from ming_sim.credit_events import resolve_credit_events_from_extraction

    def _credit_source_minus_rejections(
        originals: object, rejections: object,
    ) -> List[Dict[str, object]]:
        rejected_obj_ids = {
            id(r.get("item"))
            for r in (rejections or [])
            if isinstance(r, dict) and isinstance(r.get("item"), dict)
        }
        out: List[Dict[str, object]] = []
        for item in originals or []:
            if not isinstance(item, dict):
                continue
            if id(item) in rejected_obj_ids:
                continue
            out.append(item)
        return out

    _issue_sum = issue_summary if isinstance(issue_summary, dict) else {}
    _credit_applied: Dict[str, object] = {
        # 返回契约仅 {dossier_id, outcome}；兑付语境承接 extracted 源项
        # （含 note）minus 被拒项，与 economy_moves 同形，禁外溢返回契约。
        # dossier_executions rejected 单一保护点（credit_events 不再二次滤）。
        "dossier_executions": _credit_source_minus_rejections(
            extracted.get("dossier_executions"), dossier_execution_results,
        ),
        # 人物变更 rejected 单一保护点（credit_events 不再二次滤）。
        # cascade_echo：applier 合成级联回声（放归/被顶替等）在生产点打标，
        # 此处唯一滤除；禁在 credit_events 另设第二闸或盯 derived_from 文本。
        "人物变更": [
            r for r in applied_person_changes
            if isinstance(r, dict)
            and not r.get("rejected")
            and not r.get("cascade_echo")
        ],
        "economy_moves": _credit_source_minus_rejections(
            extracted.get("economy_moves"), economy_rejections,
        ),
        "fiscal_creates": _credit_source_minus_rejections(
            extracted.get("fiscal_creates"),
            [r for r in applied_fiscal_creates if isinstance(r, dict) and r.get("rejected")],
        ),
        "fiscal_changes": _credit_source_minus_rejections(
            extracted.get("fiscal_changes"),
            [r for r in applied_fiscal if isinstance(r, dict) and r.get("rejected")],
        ),
        "cancels": [
            r for r in (_issue_sum.get("cancels") or [])
            if isinstance(r, dict) and not r.get("rejected")
        ],
    }
    credit_event_resolutions = resolve_credit_events_from_extraction(
        db, state, _credit_applied, commit=False,
    )

    # #633 / ADR 0082 结算口：邸报大臣互动 → 边事件，同 atomic 当场落库（TD-1）。
    # 走 record_relation_edge_event 唯一写口；坏项逐条拒收留痕，不阻塞其它 section。
    from ming_sim.relations import resolve_relation_edge_events_from_extraction
    relation_edge_event_resolutions = resolve_relation_edge_events_from_extraction(
        db, state, extracted,
        # V2：dossier 来源锁本批冻结输入闭集（None/缺集按空闭集 fail-closed）。
        dossier_ids_at_input=dossier_ids_at_input,
        # T1 B 案：端点 ∈ 批内 pre∪post 名册并集——同批退场者与同批入场者的
        # 互动都落；前后均不合格（幻觉/皇帝入大臣端）仍拒收。此处已在该批人物
        # 变更全部 apply 之后，live 投影即 post-roster。
        allowed_endpoint_names=_relation_pre_roster | {
            row["name"] for row in db.current_court_roster_rows(state)
        },
    )

    state.clamp()
    return {
        "metric_delta": applied_metric,
        "validate_shape_rejections": validate_rejection_items,
        "module_misroute_rejections": module_rejections,
        "economy_moves": applied_economy,
        "economy_moves_rejections": economy_rejections,  # 拒收独立段（#14 cmr r1）；玩家可见输出会 pop
        "faction_delta": applied_factions,
        "class_delta": applied_classes,
        # 拒收项独立段（list）：供 _collect_inline_rejections 扫记 rejection_reports；
        # 与上面 *_delta（dict，web 面板数据）分开，互不污染（cmr r1，#14/#63）。
        "faction_delta_rejections": faction_rejections,
        "class_delta_rejections": class_rejections,
        "region_changes": region_changes,
        "army_changes": army_changes,
        "created_armies": created_armies,
        "power_changes": power_changes,
        "issue_summary": issue_summary,
        "dossier_executions": dossier_execution_results,
        "dossier_participants": dossier_participant_results,
        "secret_dossier_participants": secret_dossier_participant_results,
        "breach_plea_resolutions": breach_plea_resolutions,
        "credit_event_resolutions": credit_event_resolutions,
        "relation_edge_event_resolutions": relation_edge_event_resolutions,
        "authority_changes": authority_change_results,
        "world_advance": extracted.get("world_advance") or {},
        "fiscal_changes": applied_fiscal,
        "fiscal_creates": applied_fiscal_creates,
        "fiscal_removes": applied_fiscal_removes,
        "appointments": applied_appointments,
        "person_changes": person_changes,
        "applied_person_changes": applied_person_changes,
        "character_status_changes": applied_status_changes,
        "character_power_changes": applied_power_changes,
        "office_changes": applied_office_changes,
        "secret_order_updates": applied_secret_orders,
        "secret_order_closes": applied_secret_closes,
        "pairing_warnings": (issue_summary or {}).get("pairing_warnings") or [],
        "victory_status": _resolve_victory(db, state, extracted),
    }


def _resolve_victory(db: GameDB, state: GameState, extracted: Dict[str, object]) -> Dict[str, object]:
    """结局判定：叙事型（崇祯退位/自尽，extractor 抽 emperor_fate）优先于数值型（京畿失守）。
    20 年到期（timeout）在 decree 结局收口判，不在此。"""
    fate = extracted.get("emperor_fate")
    if fate in ("abdicate", "suicide"):
        if fate == "abdicate":
            return {"status": "emperor_abdicate", "summary": "崇祯帝退位逊国，大明皇统中绝。"}
        return {"status": "emperor_suicide", "summary": "崇祯帝自尽殉国，煤山一缢，大明社稷俱亡。"}
    return victory_status(db, state)


def apply_issue_inertia_and_ongoing(
    db: GameDB,
    state: GameState,
    touched_ids: Optional[set] = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """返回 inertia 自然结案路产生的容忍拒收项——settle 在 inertia 之后补收进
    收集器(桥接跑在 inertia 前,只 tlog 等于这条路脱离 rejection_reports 管线,
    与 tracker-close 路同输入两判;ship-pre r1)。"""
    # inertia 是每月自然漂移基础量，对所有进行中 issue 都生效（含本月被 advance 触动的）。
    # advance 的 delta_bar 是皇帝本月实旨推动的额外量，与 inertia 叠加，互不顶替。
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
                    _emit_pairing_warnings(new_row, effect)  # inertia 路只 tlog（#45/#46）
                    _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
                    inertia_rejections.extend(r for r in _apply_economy_list(db, state, effect.get("economy") or [], origin_ref=parent_origin_ref) if r.get("rejected"))  # economy 拒收不蒸发（#14）
                    inertia_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}).rejections)  # 派系拒收不蒸发（#14/#63 cmr r2）
                    _apply_issue_buildings(
                        db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT,
                        f"局势#{issue_id}结案", origin_ref=parent_origin_ref,
                    )
                    # 与 tracker advance/close 路径一致：自然结案也落实体后果 + 帝国修正，
                    # 否则靠 inertia 推到 100 的 issue 会丢 new_armies/army_delta/人物状态/legacy（codexB-P1）。
                    for _tr in _apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}结案",
                        applied_person_changes=applied_person_changes,
                        origin_ref=parent_origin_ref,
                    ):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.get('reason')}")
                        inertia_rejections.append(_tr)
                    _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
                    continue
                elif new_row["status"] == "failed":
                    effect = loads_effect_dict(new_row["effect_on_fail"])
                    _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
                    inertia_rejections.extend(r for r in _apply_economy_list(db, state, effect.get("economy") or [], origin_ref=parent_origin_ref) if r.get("rejected"))  # economy 拒收不蒸发（#14）
                    inertia_rejections.extend(_apply_faction_dict(db, effect.get("factions") or {}).rejections)  # 派系拒收不蒸发（#14/#63 cmr r2）
                    _apply_issue_buildings(
                        db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT,
                        f"局势#{issue_id}失败", origin_ref=parent_origin_ref,
                    )
                    for _tr in _apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}失败",
                        applied_person_changes=applied_person_changes,
                        origin_ref=parent_origin_ref,
                    ):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.get('reason')}")
                        inertia_rejections.append(_tr)
                    _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
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
            _eco_out = _apply_economy_list(
                db,
                state,
                _monthly_economy_items(ongoing),
                allow_pay_arrears_pool=allow_pay_arrears_pool,
                pay_arrears_pool_army_ids=pay_arrears_pool_army_ids,
                origin_ref=parent_origin_ref,
            )
            economy_rejections = [r for r in _eco_out if r.get("rejected")]
            issue_monthly_rejections.extend(economy_rejections)
            inertia_rejections.extend(economy_rejections)  # economy 拒收不蒸发（#14）
            economy_part = [r for r in _eco_out if not r.get("rejected")]

            applied_monthly_parts, monthly_rejections = _apply_monthly_ongoing_entities(
                db,
                state,
                ongoing,
                f"局势#{issue_id}持续效果",
                applied_person_changes=applied_person_changes,
                origin_ref=parent_origin_ref,
            )
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
            commitment_progress_payload(
                db,
                state,
                row,
                paid_this_month=paid_this_month,
                include_current_month=bool(metric_part or economy_part or applied_monthly_parts or record_commitment_attempt),
            )
            if is_commitment
            else None
        )
        commitment_bar = _commitment_bar_value(commitment_progress) if commitment_progress else None

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
