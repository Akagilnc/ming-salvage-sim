"""局势惯性 + 灾害月损的**世界后果**每月结算（#1901，局势漂移腿）。

从 `issues.py` 领域旧大块按职责拆出。归属：本模块只算并交既有守恒原语落账——
国策持续效果的 metrics/economy 走实体核 `entities.metric` /
`entities.economy`，实体后果走 `entities.issue.effects`；
单一领域分派与唯一世界记录写口归 #1815／#1835／#1889／#1813，本模块不另造派发。

- 灾害月损与局势惯性同属一条每月漂移结算：灾害局势的 `ongoing_effects`
  （天灾类含国库赈济损耗）在此按月核销，bar 越高折扣越狠，与惯性漂移同事务。
- 承诺类（commitment）走同一循环但有独立核销口径：其 helper 随本腿迁出，
  因为它们只被本函数调用（AST 全量引用核验：各仅 1 个调用方）。
- 幂等由月链既有生命周期保证（`inertia_done` 段标记），本模块不另持恢复
  生命周期（ADR 0157）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, RejectedItem
from ming_sim.db import GameDB
from ming_sim.entities.economy.apply import _apply_economy_list
from ming_sim.entities.metric.apply import ISSUE_METRIC_KEYS
from ming_sim.flows import ISSUE_METRIC_LOCK_CAPS
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.issues import (
    _canonical_issue_origin,
    _commitment_arrears_gate_army_ids,
    _commitment_gate_references_arrears,
    _commitment_stop_gate,
    _gate_passed,
    _monthly_ongoing_effects_has_work,
)
import ming_sim.entities.issue.commitment_display as commitment_display
import ming_sim.entities.issue.effects as issue_effects
from ming_sim.models import GameState, loads_effect_dict
from ming_sim.token_stats import tlog


COLLAPSIBLE_SITUATION_KINDS = frozenset({
    "人祸", "兵变", "流寇", "民变", "抗税", "党争", "朝议", "外族", "边事",
})


def situation_terminal_effects(kind: str, severity: int, polarity: str):
    """situation 终结一锤子永久效果。按 severity 推量级（轻 50 / 中 65 / 重 80）。
    resolve：达成（bar→100）落永久回血/加成，所有 situation 都有。
    fail：仅「会崩坏」局势（COLLAPSIBLE_SITUATION_KINDS）有，崩坏（bar→0）落永久重创，幅度重于回血。
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
    effect_fail = {"metrics": _metrics(-5 * mag)} if kind in COLLAPSIBLE_SITUATION_KINDS else {}
    return effect_resolve, effect_fail


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

def apply_situation_monthly_drift(
    db: GameDB,
    state: GameState,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
    source: Provenance = Provenance.system_simulation,
) -> List[RejectedItem]:
    """返回 inertia 自然结案路产生的容忍拒收项（canonical RejectedItem），
    由调用方收进拒收报告。"""
    # inertia 是每月自然漂移基础量，对所有进行中 issue 都生效（含本月被 advance 触动的）。
    # advance 的 delta_bar 是皇帝本月实旨推动的额外量，与 inertia 叠加，互不顶替。
    inertia_rejections: List[RejectedItem] = []
    active = db.list_active_issues()
    commit_local = db.owns_transaction()
    # 累计单月 metric 落账，用于上限 clamp
    period_metric_acc: Dict[str, int] = {}

    for row in active:
        issue_id = int(row["id"])
        bar = int(row["bar_value"])
        inertia = int(row["inertia"])
        commitment_kind = str(row["commitment_kind"] or "").strip()
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
