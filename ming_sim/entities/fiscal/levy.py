"""财政加派（辽饷/剿饷/练饷）与历史税率的落库实现：由 issues.py 清算迁入（ADR 0150 决定 8）。"""

from __future__ import annotations

import ming_sim.issues as issues

import json
import math
import re
from typing import Dict, List, Optional

from ming_sim.applier import (
    atomic,
)
from ming_sim.constants import (
    _SETTLE_META_JIAPIAI_KEY,
    TURN_UNIT,
)
from ming_sim.db import (
    GameDB,
)
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import Event, GameState
from ming_sim.token_stats import tlog


_FISCAL_LEVY_TARGET_ABS_TOL = 1e-9


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


def _normalize_event_terminal_reason(ev: Event, raw: object) -> str:
    label = re.sub(r"\s+", "", str(raw or ""))
    if not label:
        return ""
    allowed = getattr(ev, "terminal_reason_labels", []) or []
    for canonical in allowed:
        if label == re.sub(r"\s+", "", canonical):
            return canonical
    return ""


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


def _fiscal_levy_liao_seed(
    meta: Dict[str, object], p: Dict[str, object], region_id: str
) -> float:
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
    return issues._ctx().event_by_id.get(event_id)


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
    denominator_complete: bool = True,
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


def _load_region_fiscal_for_fiscal_levy(
    region_id: str, raw_fiscal: object
) -> Optional[dict]:
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
        tlog(
            f"[fiscal-levy] {region_id} fiscal 解析失败，本{TURN_UNIT}饷率通道出列：{type(exc).__name__}: {exc}"
        )
        return None
    if not isinstance(fiscal, dict):
        tlog(f"[fiscal-levy] {region_id} fiscal 非字典，本{TURN_UNIT}饷率通道出列")
        return None
    return fiscal


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


def _jiao_levy_in_force(
    terminal_records: Dict[str, Dict[str, str]], state: GameState
) -> bool:
    if _fiscal_levy_event_by_id(_JIAO_LEVY_START_EVENT_ID) is None:
        return False
    if _fiscal_levy_event_by_id(_JIAO_LEVY_STOP_EVENT_ID) is None:
        raise SettlementAbort(
            f"饷率事件 {_JIAO_LEVY_START_EVENT_ID} 已定义但缺停征链 {_JIAO_LEVY_STOP_EVENT_ID}",
            turn=state.turn,
            stage="fiscal_levy_config",
        )
    return _fiscal_levy_event_approved(
        terminal_records, _JIAO_LEVY_START_EVENT_ID
    ) and not _fiscal_levy_stopped(terminal_records, _JIAO_LEVY_STOP_EVENT_ID)


def _apply_fiscal_levy_targets(
    db: GameDB,
    state: GameState,
    terminal_records: Dict[str, Dict[str, str]],
) -> int:
    liao_rise_approved = _fiscal_levy_event_approved(
        terminal_records, _LIAO_LEVY_RISE_EVENT_ID
    )
    jiao_in_force = _jiao_levy_in_force(terminal_records, state)
    lian_levy_approved = _fiscal_levy_event_approved(
        terminal_records, _LIAN_LEVY_START_EVENT_ID
    )
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
            tlog(
                f"[fiscal-levy] {region_id} settle 解析失败，本{TURN_UNIT}饷率通道出列：{type(exc).__name__}: {exc}"
            )
            continue
        region_entries.append(
            {
                "region_id": region_id,
                "fiscal": fiscal,
                "settle": settle,
                "p": p,
                "meta_raw": meta_raw,
                "meta": meta,
                "liao_seed": liao_seed,
                "land": land,
                "base_transport": base_transport,
            }
        )
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
        target_liao = liao_seed * (
            _LIAO_LEVY_RISE_FACTOR if liao_rise_approved else 1.0
        )
        target_jiao = jiao_seed if jiao_in_force else 0.0
        target_lian = lian_seed if lian_levy_approved else 0.0
        # #650/0089 明渠：皇帝下旨加派逐省累积账（settle._meta「加派基线」）计入在征饷集——
        # 明选有明账，公开代价＝钱真被征上来；负额已在落账时钳 ≥0，停征即止收。
        jiapai_base = (
            max(
                0.0,
                _as_float(
                    meta[_SETTLE_META_JIAPIAI_KEY],
                    ctx=f"{region_id}.settle._meta.{_SETTLE_META_JIAPIAI_KEY}",
                ),
            )
            if _SETTLE_META_JIAPIAI_KEY in meta
            else 0.0
        )
        target_sanxiang = target_liao + target_jiao + target_lian + jiapai_base
        raw_sanxiang = p.get("三饷应征")
        raw_transport = p.get("起运定额")
        current_targets_stored = _is_stored_number(raw_sanxiang) and _is_stored_number(
            raw_transport
        )
        current_sanxiang = current_transport = None
        if current_targets_stored:
            current_sanxiang = _as_float(
                raw_sanxiang, ctx=f"{region_id}.settle.p.三饷应征"
            )
            current_transport = _as_float(
                raw_transport, ctx=f"{region_id}.settle.p.起运定额"
            )
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
        if (
            meta == meta_raw
            and current_targets_stored
            and math.isclose(
                current_sanxiang,
                target_sanxiang,
                rel_tol=0,
                abs_tol=_FISCAL_LEVY_TARGET_ABS_TOL,
            )
            and math.isclose(
                current_transport,
                target_transport,
                rel_tol=0,
                abs_tol=_FISCAL_LEVY_TARGET_ABS_TOL,
            )
        ):
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
    c = issues._ctx()
    should_commit = commit and db.owns_transaction()
    applied: List[Dict[str, object]] = []

    def run_fiscal_levy_pass() -> None:
        terminal_records = issues._event_terminal_records(db)
        for ev in c.events:
            if getattr(ev, "category", "") != issues.FISCAL_LEVY_EVENT_CATEGORY:
                continue
            if ev.id in terminal_records:
                _canonicalize_existing_fiscal_levy_terminal_reason(
                    ev,
                    terminal_records[ev.id],
                    state,
                    db,
                )
            # #1892：三饷是皇帝亲裁，结局**不经本通道**从原始选项标签旁路代批。
            # 终态只由 apply_petition_event_outcome（#1815 单一语义写口）置定；本通道
            # 只做三件事：归一已落终态的标签、按 settle.p 落征收、过窗口者落过期。
            # 「留中」不写终态，因此不进 terminal_records，本循环自然不动它——事件
            # 仍在请旨候选里等下次呈报。
            if ev.id not in terminal_records and issues._event_window_expired(
                ev, state
            ):
                db.mark_event_expired(state, ev.id, commit=False)
                terminal_records[ev.id] = {
                    "terminal_state": "expired",
                    "terminal_reason": "过最晚触发时点仍未达成触发门",
                }
                applied.append(
                    {"id": ev.id, "title": ev.title, "terminal_state": "expired"}
                )
        _apply_fiscal_levy_targets(db, state, terminal_records)

    if should_commit:
        with atomic(db):
            run_fiscal_levy_pass()
    else:
        run_fiscal_levy_pass()
    return applied
