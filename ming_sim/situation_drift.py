"""局势惯性 + 灾害月损的**世界后果**每月结算（#1901，局势漂移腿）。

从 `issues.py` 领域旧大块按职责拆出。归属：本模块只算并交既有守恒原语落账——
国策持续效果的 metrics/economy 仍走 `flows._apply_metric_dict` /
`_apply_economy_list`，实体后果仍走 `issues._apply_issue_entities`；
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

from ming_sim.db import GameDB
from ming_sim.flows import (
    ISSUE_METRIC_KEYS,
    ISSUE_METRIC_LOCK_CAPS,
    _apply_class_dict,
    _apply_economy_list,
    _apply_faction_dict,
    _apply_metric_dict,
    _strict_int,
)
from ming_sim.issues import (
    _ISSUE_PSEUDO_EVENT,
    _apply_issue_buildings,
    _apply_issue_entities,
    _apply_person_changes,
    _canonical_issue_origin,
    _commitment_arrears_gate_army_ids,
    _commitment_gate_references_arrears,
    _commitment_stop_gate,
    _ctx,
    _emit_pairing_warnings,
    _gate_passed,
    _invalid_monthly_mapping_shape,
    _merged_mapping_effect,
    _monthly_economy_items,
    _monthly_mapping_effect,
    _monthly_ongoing_effects_has_work,
    _monthly_person_rating_changes,
    _spawn_legacy_from_effect,
    commitment_progress_payload,
)
from ming_sim.models import GameState, loads_effect_dict
from ming_sim.staged_commitment import is_stage_derived_end_turn
from ming_sim.token_stats import tlog


# 会崩坏的局势：人为可控、有明确「彻底失败」时刻——镇压不住/边镇沦陷/朝局崩坏。
# 它们 bar 能跌到 0、status 转 failed 终结，落 effect_on_fail 一锤子永久重创。
# 不在此集合的（天灾/饥荒等不可控天象、正面机遇）无失败态：bar 下限 1、永不 failed、
# effect_on_fail 留空，伤害全靠 ongoing_effects 持续累积。db.advance_issue 据 effect_on_fail
# 是否非空来判能否崩坏，故此处「会崩坏」与「非空 fail effect」必须一致。
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


def default_situation_shape(kind: str, title: str):
    """局势开局形状：kind → (ongoing 过程效果, inertia 档, polarity)。

    灾害月损（天灾/灾情/饥荒的国库赈济损耗）与惯性档同属一条每月漂移结算，
    故与消费它们的 `apply_situation_monthly_drift` 同处一地，不各持一份 kind 表。
    polarity：neg=负面危机（平息回血/崩坏重创）；pos=正面机遇（把握加成/错失轻微）。
    5 个原 metric（边防/民变/党争/执行/瞒报）已废除，ongoing 按 kind 改用
    民心/皇威 或留空让 LLM 在推进时自定。结构性影响由 region/army/external/class delta 承担。
    """
    if kind in ("天灾", "灾情", "饥荒"):
        return (
            {"metrics": {"民心": -2},
             "economy": [{"account": "国库", "delta": -8, "category": "赈济损耗", "reason": title}]},
            -10, "neg",
        )
    if kind in ("人祸", "兵变", "流寇", "民变", "抗税"):
        return {"metrics": {"民心": -2}}, -10, "neg"
    if kind in ("外族", "边事"):
        return {"metrics": {"皇威": -1}}, -5, "neg"
    if kind in ("党争", "朝议"):
        return {}, -5, "neg"
    if kind in ("丰收", "祥瑞", "民和"):
        return {"metrics": {"民心": 2}}, +10, "pos"
    if kind in ("友邦", "归附", "盟约"):
        return {"metrics": {"皇威": 1}}, +5, "pos"
    if kind in ("良策", "试点", "献宝", "科技"):
        return {}, +5, "pos"
    if kind in ("战机", "敌乱"):
        return {"metrics": {"皇威": 1}}, +10, "pos"
    return {}, -5, "neg"


def _commitment_bar_value(progress: Dict[str, object]) -> Optional[int]:
    if "remaining_arrears" not in progress:
        return None
    paid = max(0, int(progress.get("paid_total") or 0))
    # remaining_arrears 由 commitment_progress_payload 从持久账本派生，非自由文本；
    # 腐值响亮失败，不得静默当作「零欠」把履约进度顶到 100。
    remaining = max(0.0, float(progress.get("remaining_arrears") or 0))
    total = paid + remaining
    if total <= 0:
        return 100
    return max(0, min(100, int(round(paid * 100 / total))))

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

def apply_situation_monthly_drift(
    db: GameDB,
    state: GameState,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """返回 inertia 自然结案路产生的容忍拒收项——settle 在 inertia 之后补收进
    收集器(桥接跑在 inertia 前,只 tlog 等于这条路脱离 rejection_reports 管线,
    与 tracker-close 路同输入两判;ship-pre r1)。"""
    # inertia 是每月自然漂移基础量，对所有进行中 issue 都生效（含本月被 advance 触动的）。
    # advance 的 delta_bar 是皇帝本月实旨推动的额外量，与 inertia 叠加，互不顶替。
    inertia_rejections: List[Dict[str, object]] = []
    active = db.list_active_issues()
    commit_local = db.owns_transaction()
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
                # 持久 ongoing_effects.metrics 的数值腐坏必须响亮失败交外层事务回滚；
                # 静默跳过会让 bar 照涨而该项世界后果无声消失（#1901 J5）。
                raw = int(v)
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
