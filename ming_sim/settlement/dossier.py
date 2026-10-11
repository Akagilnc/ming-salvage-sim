"""Consume dossier effect intents above the persistence layer."""

from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

from ming_sim.applier import Provenance, atomic
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.db import require_backing_dossier_id
from ming_sim.decree_vocabulary import dossier_action_policy
from ming_sim.exceptions import DeclarationDataError
from ming_sim.models import GameState, is_vassal_prince
from ming_sim.strict_types import (
    strict_int, validate_rejection_verdict, validate_verdict_affected_parties,
)


def apply_dossier_promulgation(
    db, state: GameState, dossier_id: int, decision: str, *,
    blocked_layer: str = "", reason: str = "", legal_reason_code: str = "",
    primary_opponents: Optional[List[Dict[str, str]]] = None,
    gatekeeper_id: Optional[str] = None,
    criteria_snapshot: Optional[Dict[str, object]] = None,
    content=None,
) -> None:
    """Record the verdict and consume its payload in the same transaction."""
    with atomic(db):
        row = db.record_dossier_promulgation(
            state, dossier_id, decision,
            blocked_layer=blocked_layer, reason=reason,
            legal_reason_code=legal_reason_code,
            primary_opponents=primary_opponents, gatekeeper_id=gatekeeper_id,
            criteria_snapshot=criteria_snapshot,
        )
        if row is None:
            return
        predeclared_midzhi = row.get("mode") == "midzhi"
        if decision == "force_promulgated":
            db._apply_override_costs(
                state, dossier_id, include_authority=True,
                include_parties=not predeclared_midzhi,
                stigma_reason="批红强颁", commit=False,
            )
        payload = json.loads(str(row["payload_json"] or "{}"))
        if not isinstance(payload, dict):
            raise ValueError("案卷 payload 非对象")
        policy = dossier_action_policy(row["action_type"], payload)
        signal = row.get("execution_signal") or {}
        if (
            row["action_type"] in {"assignment", "military_order"}
            and isinstance(signal, dict)
            and signal.get("code") == "idle_start"
        ):
            # Durable vacancy signal starts an executing dossier, but may
            # not pre-materialize work or invent a terminal outcome.
            db.transition_decree_dossier(
                dossier_id, "executing", commit=False,
            )
            return
        # Narrative-owned effects are deliberately left to the
        # month-chain world segment and translation. Exempt army-pay grants
        # consume their intent here, not while storage creates their dossier.
        if policy["effect_owner"] != "payload":
            if policy["effect_owner"] == "narrative":
                db.transition_decree_dossier(
                    dossier_id, "executing", commit=False,
                )
            elif row["action_type"] == "grant_allocation":
                amount = int(payload.get("amount") or 0)
                if db._is_army_pay_grant_payload(payload):
                    _apply_army_pay_grant_effect(db, state, row, payload, dossier_id)
                if db._grant_allocation_is_monthly(payload):
                    fiscal = db.list_fiscal_effects_for_dossier(dossier_id)
                    landed = any(
                        str(item.get("key") or "").endswith("_base")
                        and int(item.get("value") or 0) == amount
                        for item in fiscal
                    )
                    if not landed:
                        db.record_dossier_execution(
                            dossier_id, "failed",
                            "拨帑常项未建项",
                            state.turn, close=True, commit=False,
                        )
                    else:
                        db.record_dossier_execution(
                            dossier_id, "fulfilled", "成案时建月度科目",
                            state.turn, close=True, commit=False,
                        )
                else:
                    moves = db.list_economy_moves_for_dossier(dossier_id)
                    actual = int(moves[0]["delta"]) if moves else 0
                    if actual != -amount:
                        if policy["execution_surface"] == "in_transit":
                            db.transition_decree_dossier(
                                dossier_id, "executing", commit=False,
                            )
                        db.record_dossier_execution(
                            dossier_id, "failed",
                            f"拨帑不足额：应拨{amount}两，实拨{abs(actual)}两",
                            state.turn, close=True, commit=False,
                        )
                    elif policy["execution_surface"] == "in_transit":
                        db.transition_decree_dossier(
                            dossier_id, "executing", commit=False,
                        )
                    else:
                        db.record_dossier_execution(
                            dossier_id, "fulfilled", "成案时足额拨付",
                            state.turn, close=True, commit=False,
                        )
            else:
                db.record_dossier_execution(
                    dossier_id, "fulfilled", "成案时即生效",
                    state.turn, close=True, commit=False,
                )
            return
        if row["action_type"] in {"appointment", "dismiss_assignment"}:
            pa = {
                "id": int(row["pending_action_id"]),
                "kind": "office",
                "action": str(payload.get("_office_action") or "任命"),
                "minister_name": str(payload.get("_minister_name") or ""),
                "target_id": None,
            }
            previous_materializing = getattr(
                db.conn, "_materializing_dossier_id", 0
            )
            db.conn._materializing_dossier_id = int(dossier_id)
            try:
                office_changes = _commit_office_action(db,
                    state, pa, payload, content,
                )
                if not office_changes:
                    raise ValueError("任免案卷载荷物化失败")
                if (
                    pa["action"] == "任命"
                    and str(payload.get("summon_after") or "否") == "是"
                ):
                    from ming_sim.audience_night import activate_office_summon
                    entry = activate_office_summon(db, int(pa["id"]))
                    if entry is None:
                        raise ValueError("任命后传召缺原始故事账")
                    # Activate only here; #670 consumes once per night/person
                    # after the batch (apply_dossier_verdicts) or at the end of
                    # this single promulgation when not deferred.
                    nights = getattr(db.conn, "_deferred_office_summon_nights", None)
                    if nights is not None:
                        nights.add(int(entry["night_id"]))
                    else:
                        from ming_sim.audience_night import (
                            commit_fresh_summons_for_night,
                        )
                        commit_fresh_summons_for_night(
                            db, state, int(entry["night_id"]),
                            content=content,
                        )
            finally:
                db.conn._materializing_dossier_id = previous_materializing
        elif row["action_type"] == "grant_allocation":
            if db._grant_allocation_is_honorific(payload):
                _apply_grant_honorific_effect(db,
                    state, row, payload, dossier_id,
                )
            elif db._grant_allocation_is_monthly(payload):
                amount = int(payload.get("amount") or 0)
                if amount <= 0:
                    raise ValueError("拨帑案卷 amount 必须为正数")
                account = str(
                    payload.get("account") or payload.get("target_account") or ""
                ).strip()
                if account not in {"国库", "内库"}:
                    raise ValueError("拨帑案卷 account 仅可为国库或内库")
                db._create_grant_fiscal_item(
                    state, payload, dossier_id,
                    account=account, amount=amount,
                    text=str(row["decree_text"]),
                )
            else:
                amount = int(payload.get("amount") or 0)
                if amount <= 0:
                    raise ValueError("拨帑案卷 amount 必须为正数")
                # #1503：拨饷/协饷走补饷销欠缝（ADR 0023 clamp）；其它拨帑仍面额扣库。
                if db._is_army_pay_grant_payload(payload):
                    spent = _apply_army_pay_grant_effect(db,
                        state, row, payload, dossier_id,
                    )
                    # 欠资（库银不足且军仍欠）记 failed；超欠 clamp 军已清则仍 fulfilled。
                    # #1507-F5：删多余 spent<=0——军已清（still_owed==0）时 spent=0
                    # 仍属 clamp 成功终局，不得误判 failed。
                    if spent < amount:
                        target_id = str(
                            payload.get("target_id") or row.get("target_id") or ""
                        ).strip()
                        army = db.conn.execute(
                            "SELECT arrears FROM armies WHERE id=?",
                            (target_id,),
                        ).fetchone()
                        still_owed = (
                            float(army["arrears"] or 0) if army is not None else 0.0
                        )
                        if still_owed > 0:
                            db.record_dossier_execution(
                                dossier_id, "failed",
                                f"拨饷不足额：应拨{amount}两，实拨{spent}两",
                                state.turn, close=True, commit=False,
                            )
                            return
                else:
                    actual = db.record_issue_economy_move(
                        state,
                        str(payload.get("account") or payload.get("target_account") or ""),
                        -amount,
                        str(payload.get("category") or "奉旨拨帑"),
                        str(payload.get("reason") or row["decree_text"]),
                        purpose=str(payload.get("purpose") or "") or None,
                        target_kind=str(payload.get("target_kind") or "") or None,
                        target_id=str(payload.get("target_id") or "") or None,
                        origin_ref=f"dossier:{dossier_id}",
                        commit=False,
                    )
                    if actual != -amount:
                        if db._dossier_has_execution_surface(
                            row["action_type"], payload,
                        ):
                            db.transition_decree_dossier(
                                dossier_id, "executing", commit=False,
                            )
                        db.record_dossier_execution(
                            dossier_id, "failed",
                            f"拨帑不足额：应拨{amount}两，实拨{abs(actual)}两",
                            state.turn, close=True, commit=False,
                        )
                        return
        elif row["action_type"] == "pay_order_override":
            # #653 / ADR 0055/0090：偿还序 override＋折发旨判后物化——顺颁/强颁
            # 走 materialize_pay_order_decree 唯一入口（真实案卷资格＋颁布门校验、
            # 整批先验后写 fail-loud、stale until 清理）；打回在上方 decision 分支
            # 早退零写。物化落在结算尾段 atomic 内（apply_dossier_verdicts 在
            # 玩家月链事务内、本月 fixed flow 已结束后）→ 自下一次结算起
            # 生效，当月已按旧序完成的结算不追溯（F1.3）。
            _apply_pay_order_override_effect(db, state, row, payload, dossier_id)
        elif row["action_type"] == "punishment":
            # #517 / ADR 0055：结构化惩处效果自案卷物化，判决后才落人物/钱粮。
            previous_materializing = getattr(db.conn, "_materializing_dossier_id", 0)
            db.conn._materializing_dossier_id = int(dossier_id)
            try:
                _apply_punishment_verdict_effect(db,
                    state, row, payload, dossier_id, content=content,
                )
            finally:
                db.conn._materializing_dossier_id = previous_materializing
        elif row["action_type"] == "pacification":
            # #522 / ADR 0055：结构化招抚效果自案卷物化，交既有 #190 易主。
            # 反噬绑定目标当前原势力真实失方削弱（ADR 0009 决定 3）；禁止空对象。
            target = str(
                payload.get("target_id") or row.get("target_id") or ""
            ).strip()
            if not target:
                raise ValueError("招抚案卷缺少 canonical target")
            person_row = db.conn.execute(
                "SELECT power_id FROM characters WHERE name = ?",
                (target,),
            ).fetchone()
            if person_row is None:
                raise ValueError(f"招抚案卷目标不存在：{target}")
            old_power = str(person_row["power_id"] or "").strip()
            if not old_power or old_power == "ming":
                raise ValueError(
                    f"招抚案卷目标原势力不可反噬：{target}@{old_power or '∅'}"
                )
            origin_ref = f"dossier:{int(dossier_id)}"
            item = {
                "name": target,
                "origin_ref": origin_ref,
                "动作": "易主",
                "new_power": "ming",
                "方式": "主动归附",
                "反噬": {
                    old_power: {
                        "military_strength": -1,
                        "reason": "受抚",
                    }
                },
                "reason": str(
                    payload.get("text") or row.get("decree_text") or "受抚归明"
                ),
            }
            from ming_sim.entities.character.apply import apply_person_changes as _apply_person_changes
            results, person_rejections = _apply_person_changes(
                db,
                state,
                [item],
                content=content,
                origin_ref=origin_ref,
                require_origin=True,
            source=Provenance.system_simulation)
            accepted = results
            if not accepted:
                reason = ""
                if person_rejections:
                    reason = person_rejections[0].reason
                raise ValueError(reason or "招抚案卷易主物化失败")
        elif row["action_type"] == "authorization":
            # #528 / #611：公开委任只接 authority_changes 授予槽；判后物化。
            if not _apply_authorization_verdict_effect(db,
                state, row, payload, dossier_id,
            ):
                return
        elif row["action_type"] == "secret_authorization":
            # 密授不归本片（#528）；#611 privileges 仍只经 authority_changes 生产。
            pass
        elif row["action_type"] == "revoke_authority":
            # #523 / #611：收权只接 authority_changes 收回槽；判后物化。
            _apply_revoke_authority_verdict_effect(db,
                state, row, payload, dossier_id,
            )
        elif row["action_type"] == "revoke_decree":
            # #523：撤回成命=breach 目标 + 停 initiative；捆带授权走 authority_changes。
            _apply_revoke_decree_verdict_effect(db,
                state, row, payload, dossier_id,
            )
        elif row["action_type"] == "assignment":
            # #520 / ADR 0055：交办机械效果=initiative，顺颁后落。
            if not _apply_assignment_verdict_effect(db,
                state, row, payload, dossier_id,
            ):
                return
        elif row["action_type"] == "referral":
            # #524 / ADR 0055：下议机械效果=initiative（机关 participants + end_turn）。
            if not _apply_referral_verdict_effect(db,
                state, row, payload, dossier_id,
            ):
                return
        elif row["action_type"] == "military_order":
            # #521 / ADR 0055：军令 station/office 自案卷物化；due_turn 已在案卷。
            _apply_military_order_verdict_effect(db,
                state, row, payload, dossier_id,
                content=content,
            )
        # #1783：仅 grant 回报期限未到 → 保持 executing；期限只挂原案卷，
        # 不另立承诺事项/不占在办名额。到期由 write_due 扫案卷 due_turn → 0076。
        # 其它类型终局路径不动。期限真源＝案卷列/payload.due_turn（军令同款单源）。
        if str(row.get("action_type") or "") == "grant_allocation":
            due_turn = int(row.get("due_turn") or 0)
            if due_turn <= 0:
                due_turn = int(payload.get("due_turn") or 0)
            if due_turn > int(state.turn):
                db.transition_decree_dossier(
                    dossier_id, "executing", commit=False,
                )
                return
        if policy["execution_surface"] in {"terminal", "immediate"}:
            db.record_dossier_execution(
                dossier_id, "fulfilled", "颁布即终局", state.turn,
                close=True, commit=False,
            )
        else:
            db.transition_decree_dossier(
                dossier_id, "executing", commit=False,
            )
    return


def _apply_army_pay_grant_effect(
    db, state: GameState, row, payload: Dict[str, object], dossier_id: int,
) -> int:
    """#1503：颁布缝一次消费拨饷载荷 — 扣库+销欠同事务（ADR 0023 clamp）。"""
    from ming_sim.entities.economy.apply import _apply_economy_list

    amount = int(payload.get("amount") or 0)
    if amount <= 0:
        raise DeclarationDataError("拨饷案卷 amount 必须为正数")
    account = str(
        payload.get("account") or payload.get("target_account") or ""
    ).strip()
    if account not in {"国库", "内库"}:
        raise DeclarationDataError("拨饷案卷 account 仅可为国库或内库")
    target_id = str(
        payload.get("target_id") or row.get("target_id") or ""
    ).strip()
    if str(payload.get("target_kind") or row.get("target_kind") or "") != "army" or not target_id:
        raise DeclarationDataError("拨饷案卷须指定 target_kind=army 与 target_id")
    origin_ref = f"dossier:{int(dossier_id)}"
    # 幂等：同案已有补饷流水则不二扣（ready 重放 / 重复 settle 护栏）。
    existing = [
        m for m in db.list_economy_moves_for_dossier(int(dossier_id))
        if str(m.get("purpose") or "") == "补饷"
    ]
    if existing:
        return abs(int(existing[0].get("delta") or 0))
    move = {
        "account": account,
        "delta": -amount,
        "category": str(payload.get("category") or "奉旨拨饷"),
        "reason": str(payload.get("reason") or row["decree_text"]),
        "purpose": "补饷",
        "target_kind": "army",
        "target_id": target_id,
        "origin_ref": origin_ref,
    }
    results, results_rejections = _apply_economy_list(
        db, state, [move], require_origin=False,
    source=Provenance.system_simulation)
    if results_rejections:
        raise DeclarationDataError(results_rejections[0].reason)
    spent = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        spent += abs(int(item.get("delta") or 0))
    return spent


def _apply_grant_honorific_effect(
    db, state: GameState, row, payload: Dict[str, object], dossier_id: int,
) -> None:
    """#518 interim：加衔/荫叙只落叙事开放标签，不改主官职。"""
    target = str(
        payload.get("target_id") or payload.get("name") or row.get("target_id") or ""
    ).strip()
    action = str(payload.get("grant_action") or "").strip()
    if not target or action not in {"加衔", "荫叙"}:
        raise ValueError("恩赏案卷缺少加衔/荫叙目标")
    origin_ref = f"dossier:{int(dossier_id)}"
    db.record_person_log(
        state, target, action,
        payload_summary="加衔示恩" if action == "加衔" else "荫叙示恩",
        source="grant_allocation", origin_ref=origin_ref, commit=False,
    )


def _apply_military_order_station_effect(
    db, state, *, army_id: str, station: str, actor: str, reason: str,
    origin_ref: str, station_region: str = "",
) -> None:
    """军令调驻面：既有军 station(+可选 station_region) → army 写核；不得 new_armies。

    #659：只改人读驻地/结构化驻地；不触 pay_source_region。仅 station 无 region
    时只改人读字段，region 保持原值（禁止从 station 文本反推）。
    """
    dest = str(station or "").strip()
    dest_region = str(station_region or "").strip()
    if not dest and not dest_region:
        return
    if not army_id:
        raise ValueError("军令调驻缺少军队 target")
    existing = db.conn.execute(
        "SELECT id FROM armies WHERE id = ?", (army_id,),
    ).fetchone()
    if existing is None:
        raise ValueError(
            f"军令调驻引用未入库军队 '{army_id}'（既有军调驻不得 new_armies）"
        )
    from ming_sim.models import Event
    pseudo = Event(
        id="military_order", title="军令调遣", kind="圣旨", summary="",
        urgency=0, severity=0, credibility=100, interests=[], audiences=[],
    )
    delta: Dict[str, object] = {"reason": reason}
    if dest:
        delta["station"] = dest
    if dest_region:
        delta["station_region"] = dest_region
    changes, changes_rejections = db.apply_army_deltas(
        state, pseudo, None, actor or "军令",
        {army_id: delta},
        commit=False,
        origin_ref=origin_ref,
        require_origin=True,
    source=Provenance.system_simulation)
    # #521 r1：目标 station=当前站时 army 写核空接受=幂等 noop 成功，
    # 不得当硬失败以致同批职守变更回滚。
    rejected = changes_rejections
    if rejected:
        fail_reason = rejected[0].reason
        raise ValueError(fail_reason or "军令调驻物化失败")


def _affected_people_from_applied_rows(rows) -> set[str]:
    """Canonical applied rows → formal person names (appointee + displaced).

    Partial concurrent-office displacements live only on the row's displaced
    list (full 听用候铨 displacements are also synthesized as cascade rows).
    Used to report actual appointment changes, including partial displacements.
    """
    names: set[str] = set()
    for item in rows or ():
        if not isinstance(item, dict):
            continue
        person = str(item.get("name") or item.get("人物") or "").strip()
        if person:
            names.add(person)
        for part in item.get("displaced") or []:
            displaced_name = str(part).split(":", 1)[0].strip()
            if displaced_name:
                names.add(displaced_name)
    return names


def _apply_military_order_office_effect(
    db, state, payload, *, actor: str, reason: str, origin_ref: str,
    content=None,
) -> None:
    """军令职守面：payload.office / office_changes → 人物变更唯一核。"""
    office_items: List[Dict[str, object]] = []
    raw_changes = payload.get("office_changes")
    if isinstance(raw_changes, list):
        for raw in raw_changes:
            if isinstance(raw, dict):
                office_items.append(dict(raw))
    office_title = str(payload.get("office") or "").strip()
    if office_title and actor:
        if not any(
            str(i.get("name") or "").strip() == actor
            and str(i.get("new_office") or i.get("office") or "").strip()
            for i in office_items
        ):
            office_item: Dict[str, object] = {
                "name": actor,
                "动作": "调任",
                "new_office": office_title,
                "office": office_title,
                "reason": reason,
            }
            # Preserve typed 任所 from dossier/pending payload; do not invent.
            seat = str(
                payload.get("region_id")
                or payload.get("任所")
                or payload.get("辖区")
                or ""
            ).strip()
            if seat:
                office_item["region_id"] = seat
            office_items.append(office_item)
    if not office_items:
        return
    from ming_sim.entities.character.apply import apply_person_changes as _apply_person_changes
    prepared: List[Dict[str, object]] = []
    for item in office_items:
        entry = dict(item)
        entry.setdefault("origin_ref", origin_ref)
        entry.setdefault("动作", "调任")
        if not entry.get("new_office") and entry.get("office"):
            entry["new_office"] = entry["office"]
        prepared.append(entry)
    results, person_rejections = _apply_person_changes(
        db,
        state,
        prepared,
        content=content,
        origin_ref=origin_ref,
        require_origin=True,
    source=Provenance.system_simulation)
    accepted_p = results
    if not accepted_p:
        fail_reason = ""
        if person_rejections:
            fail_reason = person_rejections[0].reason
        raise ValueError(fail_reason or "军令职守变更物化失败")


def _apply_authorization_verdict_effect(
    db, state, row, payload, dossier_id,
) -> bool:
    """#528：公开委任案卷顺颁后走 #611 authority_changes 授予槽。

    完整授予条目：动作=授予 + dossier_id + holder_id + privilege + scope。
    不直写 authority_records。
    Returns False when duplicate_active_authority was soft-rejected and
    terminal failure already recorded — caller must return early.
    Returns True when the grant landed.
    """
    from ming_sim.settlement import SettlementContext, settle_delta

    holder = str(
        payload.get("holder_id")
        or payload.get("assignee_id")
        or payload.get("name")
        or row.get("executor_id")
        or ""
    ).strip()
    privilege = str(payload.get("privilege") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    if not scope:
        t_kind = str(
            payload.get("target_kind") or row.get("target_kind") or ""
        ).strip()
        t_id = str(
            payload.get("target_id") or row.get("target_id") or ""
        ).strip()
        if t_kind and t_id:
            scope = f"{t_kind}:{t_id}"
    if not holder or not privilege or not scope:
        raise ValueError("委任授权案卷缺少 holder_id/privilege/scope")
    outcome = settle_delta(
        state, db,
        {
            "authority_changes": [{
                "动作": "授予",
                "holder_id": holder,
                "privilege": privilege,
                "scope": scope,
                "dossier_id": int(dossier_id),
            }],
        },
        SettlementContext(),
    )
    if outcome.authority.rejected:
        reason = outcome.authority.rejected[0].reason or "授予被拒"
    elif not outcome.authority.applied:
        reason = "授予未落"
    else:
        reason = ""
    if reason:
        # #1628 / 0150-D5-a：跨案 duplicate 接到 assignment 软通道，不得升格整批。
        if reason == "duplicate_active_authority":
            db.transition_decree_dossier(
                dossier_id, "executing", commit=False,
            )
            db.record_dossier_execution(
                dossier_id, "failed", reason, state.turn,
                close=True, commit=False,
            )
            return False
        raise ValueError(reason)
    return True


def _apply_revoke_authority_verdict_effect(
    db, state, row, payload, dossier_id,
) -> None:
    """#523：收权案卷顺颁后走 #611 authority_changes 收回槽。

    生产项显式携 authority_id + 本项 dossier_id；只落收回事实。
    人物是否结怨走既有关系声明口（#1895），不走 0056 毁约轨。
    """
    from ming_sim.settlement import SettlementContext, settle_delta
    from ming_sim.strict_types import strict_int

    raw_aid = payload.get("authority_id")
    if raw_aid in (None, ""):
        raise ValueError("收权案卷缺少 authority_id")
    authority_id = strict_int(raw_aid, accept_numeric_strings=True)
    if authority_id <= 0:
        raise ValueError("收权案卷缺少 authority_id")
    outcome = settle_delta(
        state, db,
        {
            "authority_changes": [{
                "动作": "收回",
                "authority_id": authority_id,
                "dossier_id": int(dossier_id),
            }],
        },
        SettlementContext(),
    )
    if outcome.authority.rejected:
        raise ValueError(outcome.authority.rejected[0].reason or "收权被拒")
    if not outcome.authority.applied:
        raise ValueError("收权未落")


def _apply_revoke_decree_verdict_effect(
    db, state, row, payload, dossier_id,
) -> None:
    """#523：撤回成命顺颁后终结目标承诺/旨意；捆带授权走 authority_changes。

    非 undo、不删旧账。代价归 ADR 0056（breach_decree_dossier）。
    """
    from ming_sim.breach_plea import apply_persist_revoke_tail

    target_dossier_id, target_issue_id = db.resolve_revoke_decree_target_ids(
        payload, row,
    )

    raw_reason = str(payload.get("text") or row.get("decree_text") or "")
    reason = raw_reason if raw_reason.strip() else "撤回成命"

    # #1894：撤旨照常过外廷。外廷（0055 颁布判决）准行即当月落实，
    # 不再把撤令延后到下一次召对等一场挽留——旧 ADR 0075「先顶哭谏、
    # 坚持撤才落账」的等待已退役（撤令/原旨/已落实况由既有材料目录供
    # 外廷人物读，是否求情归模型，不设代码求情探测）。
    # 立即路径收尾：0056 + 捆带授权收回 + 同源停 tick。
    # 0056 只落名声账；原案卷结案由执行格判官本月 dossier_executions 落。
    apply_persist_revoke_tail(
        db, state,
        target_dossier_id=int(target_dossier_id),
        reason=reason,
        apply_0056=True,
        commitment_ref=int(target_issue_id or 0),
        authority_source_dossier_id=int(dossier_id),
        revoke_dossier_id=int(dossier_id),
    )


def _apply_military_order_verdict_effect(
    db, state, row, payload, dossier_id, *, content=None,
) -> None:
    """#521：军令案卷顺颁后的结构化效果（受判类，打回不进此函数）。

    - 既有军 station → army 写核（apply_army_deltas）；不得 new_armies
    - 真实职守变化 → 人物变更/任免唯一核（ADR 0009）
    - 期限只落案卷 due_turn（限期出战 admission 写入）；无胜负引擎
    """
    origin_ref = f"dossier:{int(dossier_id)}"
    army_id = str(
        payload.get("target_id") or row.get("target_id") or ""
    ).strip()
    station = str(payload.get("station") or "").strip()
    station_region = str(
        payload.get("station_region")
        or payload.get("实际驻地")
        or payload.get("驻地省")
        or ""
    ).strip()
    reason = str(
        payload.get("text") or row.get("decree_text") or "军令调遣"
    )
    from ming_sim.participant_roster import resolve_dossier_owner_name
    actor = resolve_dossier_owner_name(row)

    _apply_military_order_station_effect(db,
        state,
        army_id=army_id,
        station=station,
        station_region=station_region,
        actor=actor,
        reason=reason,
        origin_ref=origin_ref,
    )
    # due_turn：admission/create_decree_dossier 已落案卷列；限期出战无另表。
    _apply_military_order_office_effect(db,
        state,
        payload,
        actor=actor,
        reason=reason,
        origin_ref=origin_ref,
        content=content,
    )


def _initiative_title_and_body(
    payload: Dict[str, object], row,
) -> tuple[str, str]:
    """#1565/0142：initiative 题名/正文单一规则（assignment/referral 共用）。

    题名只认结构化 title|target_id，不从 decree_text/正文/皇帝散文截取，
    不生成「交办差事/下议事项」默认题名冒充来源身份。
    正文唯一真源 payload.text；旧案卷无 text 时 decree_text 仅作正文承接，
    不得回填题名，不得以题名/target_id 冒充正文。
    真缺锚时 title 为空串——caller 复用既有 execution failed 接缝，保留案卷与正文。
    """
    title = str(payload.get("title") or "")
    if not title:
        title = str(payload.get("target_id") or "").strip()
    body = str(payload.get("text") or row.get("decree_text") or "")
    return title, body


def _apply_referral_verdict_effect(
    db, state, row, payload, dossier_id,
) -> bool:
    """#524：下议案卷顺颁后创建 initiative（机关 participants + end_turn）。

    Returns False on soft-reject；True 时 caller 继续 executing 过渡。
    禁个人 owner：participants 仅 responsible_bodies 机关/职司名。
    """
    from ming_sim.action_materialize import (
        assert_responsible_bodies_org_only,
        character_person_names,
        parse_responsible_bodies,
    )
    from ming_sim.settlement import SettlementContext, settle_delta

    # 与暂存/admission 同一解析；个人名不得落 participants。
    bodies = parse_responsible_bodies(payload.get("responsible_bodies"))
    if not bodies:
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", "下议缺少 responsible_bodies",
            state.turn, close=True, commit=False,
        )
        return False
    try:
        assert_responsible_bodies_org_only(
            bodies,
            known_person_names=character_person_names(db),
            current_minister=str(
                row.get("executor_id")
                or payload.get("actor")
                or payload.get("assignee_id")
                or payload.get("assignee")
                or ""
            ),
        )
    except DeclarationDataError as exc:
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", str(exc) or "responsible_bodies 禁个人名",
            state.turn, close=True, commit=False,
        )
        return False

    title, stage_text = _initiative_title_and_body(payload, row)
    if not title:
        # 保留案卷与正文；缺结构化锚走既有 execution failed（可见可恢复）。
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", "下议缺少结构化题名（title 或 target_id）",
            state.turn, close=True, commit=False,
        )
        return False

    end_turn = int(payload.get("end_turn") or 0)
    if end_turn <= 0:
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", "下议缺少 end_turn",
            state.turn, close=True, commit=False,
        )
        return False

    origin_ref = f"dossier:{int(dossier_id)}"
    # end_turn 有值时既有 new_issues 契约要求 commitment_kind 标记
    # （否则被当成「承诺形态无 marker」拒）；议期=时限承诺，复用 until_stop + end_turn。
    ni: Dict[str, object] = {
        "origin_kind": "decree",
        "origin_ref": origin_ref,
        "kind": "initiative",
        "title": title,
        "stage_text": stage_text,
        # 机关/职司名字符串列表 → issues.participants JSON
        "participants": bodies,
        "end_turn": end_turn,
        "commitment_kind": "until_stop",
    }
    outcome = settle_delta(
        state, db, {"new_issues": [ni]}, SettlementContext(),
    )
    created = outcome.issue.new_issues if outcome.issue is not None else []
    rejected = outcome.issue.rejected if outcome.issue is not None else []
    if rejected or not created:
        reason = (rejected[0].reason if rejected else "") or "下议 initiative 被拒"
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", reason, state.turn, close=True, commit=False,
        )
        return False
    return True


def _apply_assignment_verdict_effect(
    db, state, row, payload, dossier_id,
) -> bool:
    """#520：交办案卷顺颁后创建 initiative（owner + 可选军令状承诺）。

    Returns False when the item was soft-rejected (invalid commitment
    shape) and terminal failure already recorded — caller must return early.
    Returns True when initiative landed and caller should continue to the
    shared executing/terminal transition.
    """
    from ming_sim.entities.issue.records import _normalize_commitment_kind
    from ming_sim.settlement import SettlementContext, settle_delta

    from ming_sim.participant_roster import resolve_dossier_owner_name
    owner = resolve_dossier_owner_name(row)
    if not owner:
        raise ValueError("交办案卷缺少主办")

    title, stage_text = _initiative_title_and_body(payload, row)
    if not title:
        # 保留案卷与正文；缺结构化锚走既有 execution failed（可见可恢复）。
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", "交办缺少结构化题名（title 或 target_id）",
            state.turn, close=True, commit=False,
        )
        return False

    origin_ref = f"dossier:{int(dossier_id)}"
    commitment_kind = _normalize_commitment_kind(payload.get("commitment_kind"))
    if commitment_kind == "无":
        commitment_kind = ""

    # 本接缝组装 new_issues item，交落库编排器的局势段落地；
    # 逐项 rejected（毒形等）→ 案卷执行失败。#1790 废在办数量硬上限。
    # #520 只授权捕获与落库；不夹带民心等兑现效果（兑现归 #476）。
    ni: Dict[str, object] = {
        "origin_kind": "decree",
        "origin_ref": origin_ref,
        "kind": "initiative",
        "title": title,
        "stage_text": stage_text,
        "participant_roster": [{"character_id": owner, "tier": "主办"}],
    }
    # 形状保留：承诺字段原样交给局势段。
    # 缺 commitment_kind marker 的毒形不得在此洗掉后当普通 initiative 落地（#520）。
    if commitment_kind:
        ni["commitment_kind"] = commitment_kind
    # C.6 rescript stop_condition 为 str（payload 层保真）；结构化 commitment
    # 门仍只认 dict（#136 全局契约不动）。非 dict 不转发进 ni，避免 str 被
    # 结构化校验误拒；until_stop+end_turn 仍可落 initiative。
    stop_raw = payload.get("stop_condition")
    if isinstance(stop_raw, dict) and stop_raw:
        ni["stop_condition"] = stop_raw
    end_turn = int(payload.get("end_turn") or 0)
    if end_turn > 0:
        ni["end_turn"] = end_turn
        # 与 stages 支对称：有绝对期限则须带 commitment marker，否则
        # end_turn 会被当成「承诺形态无 marker」拒（issues 既有契约）。
        if not commitment_kind:
            ni["commitment_kind"] = "until_stop"
    ongoing = payload.get("ongoing_effects")
    if isinstance(ongoing, dict) and ongoing:
        ni["ongoing_effects"] = ongoing
    # #620 扩展面：分段里程碑（#520 本体字段语义不动）
    from ming_sim.staged_commitment import stages_to_json
    # 分段承诺是机械事实，只认显式结构化 stages：非 JSON 散文串响亮 ValueError。
    # 引擎不再从已归一正文（stage_text）里正则抠年份（ADR 0142 / 御批 2026-09-30）。
    stages_norm = json.loads(stages_to_json(
        payload.get("stages") or payload.get("stages_json"),
    ))
    if stages_norm:
        ni["stages"] = stages_norm
        if not commitment_kind:
            ni["commitment_kind"] = "until_stop"
    # ongoing_effects / end_turn 选择规则与缺 marker 拒收交既有校验。

    outcome = settle_delta(
        state, db, {"new_issues": [ni]}, SettlementContext(),
    )
    created = outcome.issue.new_issues if outcome.issue is not None else []
    rejected = outcome.issue.rejected if outcome.issue is not None else []
    if rejected or not created:
        reason = (rejected[0].reason if rejected else "") or "交办 initiative 被拒"
        # 校验失败逐项软拒，不掀整批。
        db.transition_decree_dossier(dossier_id, "executing", commit=False)
        db.record_dossier_execution(
            dossier_id, "failed", reason, state.turn, close=True, commit=False,
        )
        return False
    return True


def _apply_punishment_verdict_effect(
    db, state, row, payload, dossier_id, *, content=None,
) -> None:
    """#517：惩处案卷顺颁后的结构化效果（受判类，打回不进此函数）。"""
    target = str(
        payload.get("target_id") or row.get("target_id") or ""
    ).strip()
    punish_action = str(payload.get("punish_action") or "").strip()
    issue_disposition = str(payload.get("issue_disposition") or "").strip()
    issue_id = int(payload.get("issue_id") or 0)
    issue = None
    if issue_id:
        issue = db.conn.execute(
            "SELECT status,origin_kind,faction_hint,target_roster FROM issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if issue is None or issue["origin_kind"] != "impeachment_surge":
            raise ValueError("处置所指弹劾潮不存在")
        if issue["status"] != "active":
            return
        if issue_disposition == "办人":
            try:
                roster = json.loads(str(issue["target_roster"] or "[]"))
            except (TypeError, ValueError) as exc:
                raise ValueError("弹劾潮 target_roster 非法") from exc
            if target not in roster:
                raise ValueError("办人目标不在弹劾潮 target_roster")
    if issue_disposition == "压下" and issue is not None:
        faction = str(issue["faction_hint"] or "").strip()
        if db._record_decree_cost(
            dossier_id, state.turn, "authority", "metric", "皇威", -1,
            "压下弹劾", cost_identity="impeachment_suppression",
        ):
            state.metrics["皇威"] = max(0, int(state.metrics.get("皇威", 0)) - 1)
            db.conn.execute(
                "INSERT INTO metrics(key,value) VALUES('皇威',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (state.metrics["皇威"],),
            )
        if faction and db._record_decree_cost(
            dossier_id, state.turn, "satisfaction", "faction", faction, -1,
            "压下弹劾", cost_identity="impeachment_suppression",
        ):
            db.adjust_factions({faction: {"satisfaction": -1}}, commit=False)
        db.close_issue(state, issue_id, reason="resolved", commit=False)
        return
    if not target:
        raise ValueError("惩处案卷缺少 canonical target")
    origin_ref = f"dossier:{int(dossier_id)}"
    reason = str(
        payload.get("text") or row.get("decree_text") or punish_action
    )
    # #658：typed backing 单权威（与 stage 首写共吃）
    backing_id = int(require_backing_dossier_id(db, payload.get("backing_dossier_id")) or 0)
    status_by_action = {
        "拿问下狱": "imprisoned",
        "拿问去职": "imprisoned",
        "赐死": "dead",
        "流放": "exiled",
        "削籍": "dismissed",
    }
    if punish_action in status_by_action:
        item = {
            "name": target,
            "origin_ref": origin_ref,
            "动作": "处置",
            "status": status_by_action[punish_action],
            "reason": reason,
        }
        if punish_action == "削籍":
            item["reason_code"] = "获罪削籍"
            item["reason"] = "获罪削籍"
        from ming_sim.entities.character.apply import apply_person_changes as _apply_person_changes
        results, person_rejections = _apply_person_changes(
            db,
            state,
            [item],
            content=content,
            origin_ref=origin_ref,
            require_origin=True,
        source=Provenance.system_simulation)
        accepted = results
        if not accepted:
            fail_reason = ""
            if person_rejections:
                fail_reason = person_rejections[0].reason
            raise ValueError(fail_reason or "惩处案卷人物效果物化失败")
        _maybe_write_backing_betray_credit(db,
            state, target=target, backing_id=backing_id, reason=reason,
        )
        if issue_id and issue_disposition == "办人":
            db.close_issue(state, issue_id, reason="resolved", commit=False)
        return
    if punish_action in {"放归", "昭雪"}:
        # #517：宥赦只回迁在世处置态；dead 等终态响亮拒绝，不得复活。
        current_status, _ = db.get_character_status(target)
        if current_status not in {"imprisoned", "dismissed", "exiled"}:
            raise ValueError(
                f"宥赦不可回迁：{target} 当前状态={current_status or '(空)'}"
            )
        db.set_character_status(
            state, target, "active", reason, reason_code="", content=content, commit=False,
        )
        db.record_person_log(
            state, target, "处置", payload_summary=punish_action,
            source="punishment", origin_ref=origin_ref, commit=False,
        )
        # #658：放归/昭雪为非惩罚动作，成功亦不写 backing 辜负。
        return
    if punish_action == "罚俸":
        amount = int(payload.get("amount") or 0)
        if amount <= 0:
            raise ValueError("罚俸案卷缺少正数 amount")
        # #517 r2：消费 actual；不足额/零落账响亮失败，事务回滚，不得 fulfilled。
        # 方向保持减项（票面钱粮减项），不得改成国库正收入。
        actual = db.record_issue_economy_move(
            state,
            "国库",
            -amount,
            "罚俸",
            "罚俸示惩",
            purpose=None,
            target_kind="character",
            target_id=target,
            origin_ref=origin_ref,
            commit=False,
        )
        if actual != -amount:
            raise ValueError(
                f"罚俸不足额：应减{amount}两，实减{abs(int(actual))}两"
            )
        db.record_person_log(
            state, target, "罚俸", payload_summary="罚俸示惩",
            source="punishment", origin_ref=origin_ref, commit=False,
        )
        _maybe_write_backing_betray_credit(db,
            state, target=target, backing_id=backing_id, reason=reason,
        )
        return
    if punish_action == "廷杖":
        db.record_person_log(
            state, target, "廷杖", payload_summary="廷杖示惩",
            source="punishment", origin_ref=origin_ref, commit=False,
        )
        _maybe_write_backing_betray_credit(db,
            state, target=target, backing_id=backing_id, reason=reason,
        )
        return
    raise ValueError(f"惩处案卷动作无法物化：{punish_action}")


def _maybe_write_backing_betray_credit(
    db, state, *, target: str, backing_id: int, reason: str,
) -> None:
    """#658：处置成功且目标确为原案非御笔背书人时，经 ADR 0079 写辜负。

    origin 回指原 dossier。无 backing / 非站台者 / 御笔背书 → 零信用事件。
    """
    if int(backing_id or 0) <= 0:
        return
    person = str(target or "").strip()
    if not person:
        return
    endorsements = db.list_dossier_endorsements(int(backing_id))
    hit = False
    for item in endorsements:
        if bool(item.get("imperial")):
            continue
        if str(item.get("form") or "") != "当面站台":
            continue
        if str(item.get("endorser_id") or "").strip() == person:
            hit = True
            break
    if not hit:
        return
    raw_context = str(reason or "")
    context = raw_context if raw_context.strip() else "处置站台者"
    from ming_sim.credit_events import KIND_BETRAY, write_credit_event
    write_credit_event(
        db, state,
        person=person,
        event_kind=KIND_BETRAY,
        context=context,
        origin=f"dossier:{int(backing_id)}",
    )


def _apply_pay_order_override_effect(
    db, state: GameState, row, payload: Dict[str, object], dossier_id: int,
) -> None:
    """#653 / ADR 0090：pay_order_override 案卷顺颁/强颁后自载荷物化 fiscal_config。

    唯一物化入口＝materialize_pay_order_decree（内部再验真实案卷资格＋颁布门）；
    打回案卷不进本分支（效果跟判决走，零写入）。物化即效果已落地（无执行判定面）
    → fulfilled 直达终局，与 punishment/pacification 同款 terminal 分支。"""
    from ming_sim.pay_order import materialize_pay_order_decree
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("pay_order_override 案卷 payload.entries 须为非空列表")
    materialize_pay_order_decree(
        db,
        turn=int(state.turn),
        entries=entries,
        origin_ref=f"dossier:{int(dossier_id)}",
        reason=str(row["decree_text"] or ""),
        commit=False,
    )


def _commit_office_action(
    db, state: GameState, pa: Dict[str, object], payload: Dict[str, object],
    content,
) -> set[str]:
    """任免(office)落库并返回 canonical applied 中受影响的正式人物。
    - 任命既有官 → 升迁/调任:set_character_office(改官、仍 active),不当新人(apply_appointment
      对在册者命中即拒、会标 failed);
    - 任命朝臣(新任/升迁/调任)→ person-only canonical adapter → apply_office_appointment
      唯一落地核(dead-reject / 非active→激活 / 顶替去重);
    - 罢免:_find_existing_minister 解 alias + ming-guard(外藩/后宫/不在册不接),dismissed+同步清内存 office。
    缺 content(无法查重/注册)→ 空集合标 failed,不静默。领域核在调用时加载。"""
    if content is None:
        return set()
    from ming_sim.session import _find_existing_minister
    name = str(payload.get("name") or "").strip()
    if not name:
        return set()
    office = str(payload.get("office") or "")
    if pa["action"] == "任命":
        # 朝臣任命/升迁/调任 → person-only adapter（不经 full settlement recovery）。
        raw_reason = str(payload.get("reason") or "")
        reason = raw_reason if raw_reason.strip() else "奉旨任免"
        office_type = str(payload.get("office_type") or "").strip()
        try:
            appointment_tenure = appointment_tenure_from(payload)
        except DeclarationDataError:
            return set()
        recommendation = payload.get("recommendation")
        staged_candidate = recommendation.get("candidate") if isinstance(recommendation, dict) else None
        recommender = str(recommendation.get("recommender") or pa["minister_name"]) if isinstance(recommendation, dict) else ""
        # #1583：批内已在 apply_dossier_verdicts / 批红序前统一校验过荐人快照时，
        # 跳过二次校验，避免前序任免改盘面把后序同快照误判过期。
        if not getattr(db.conn, "_recommendation_snapshots_prevalidated", False):
            if recommendation is not None and (
                not isinstance(staged_candidate, dict)
                or not recommender
            ):
                return set()
            if isinstance(staged_candidate, dict):
                from ming_sim.recommendations import validate_recommendation_snapshot
                if staged_candidate.get("name") != name or not validate_recommendation_snapshot(
                    db, state, recommender, staged_candidate
                ):
                    return set()
        elif recommendation is not None and (
            not isinstance(staged_candidate, dict)
            or not recommender
            or staged_candidate.get("name") != name
        ):
            return set()
        # A recommendation event is provenance for this exact staged
        # candidate.  Keep the appointment and event in one transaction so
        # a failure while recording cannot leave the appointment adopted
        # without its auditable recommendation.
        recommendation_reason = ""
        if isinstance(recommendation, dict):
            recommendation_reason = str(payload.get("reason") or "")
            if not recommendation_reason.strip():
                raise ValueError("荐人双边缺非空荐词语境：payload.reason 必填")
            reason = recommendation_reason
        from ming_sim.settlement.run import apply_person_changes_only
        person_item = {
            "name": name, "动作": "任命", "office": office,
            "office_type": office_type, "任别": appointment_tenure,
            "reason": reason, "origin_ref": "盘面自发",
        }
        seat = str(
            payload.get("region_id")
            or payload.get("任所")
            or payload.get("辖区")
            or ""
        ).strip()
        if seat:
            person_item["region_id"] = seat
        applied = apply_person_changes_only(
            db, state,
            [person_item],
            content=content, llm_config=db.llm_config,
        source=Provenance.system_simulation)
        affected = _affected_people_from_applied_rows(
            applied.applied,
        )
        if recommendation_reason and name in affected:
            from ming_sim.recommendations import record_recommendation_edges
            event_id = db.record_recommendation(
                state, recommender, staged_candidate, office,
                recommendation_reason,
            )
            record_recommendation_edges(
                db, state, recommender, name, event_id, recommendation_reason,
            )
        return affected
    if pa["action"] == "罢免":
        # 仅大明【在职】大臣可罢:_find_existing_minister 已 ming-guard + 解 alias;
        # 外藩(power_id≠ming)/后宫/不在册不接(无字面 fallback,免误黜皇太极,CMR R2);
        # 再校 active,免把已故/已黜/致仕者的终态改写成 dismissed(CMR R3 codex R2)。
        key = _find_existing_minister(content, name, db)
        if key is None or db.get_character_status(key)[0] != "active":
            return set()
        # 宗藩（就藩宗室）非朝堂命官，不可作朝臣罢免——_find_existing_minister 仍会解析到宗藩名
        # （任命核需解到名才能显式拒），故罢免侧单独守（cmr R6 cross-section）。
        _ch_key = content.characters.get(key)  # key 来自 _find_existing_minister 必在册，.get 防御一致（R2 gemini）
        if _ch_key is not None and is_vassal_prince(_ch_key):
            return set()
        db.set_character_status(
            state, key, "dismissed", reason="奉旨罢黜", content=content,
        )
        # 对话确认回合中落库,刷 Agent 让被罢者本回合后续不再以旧活跃态被召对(线上 gemini)。
        return {key}
    return set()


def apply_dossier_verdicts(
    db, state: GameState, verdicts: Iterable[Dict[str, object]], *,
    content=None,
) -> None:
    """结算判决注入入口：批量、同事务消费每案结构化 verdict。"""
    # Validate the complete batch before the first write at this public seam.
    rows = list(verdicts)
    faction_names = {str(row["name"]) for row in db.conn.execute("SELECT name FROM factions")}
    class_names = {str(row["name"]) for row in db.conn.execute("SELECT DISTINCT name FROM classes")}
    character_ids = {str(row["name"]) for row in db.conn.execute("SELECT name FROM characters")}
    for verdict in rows:
        if not isinstance(verdict, dict):
            raise ValueError("案卷 verdict 须为对象")
        dossier_id = strict_int(verdict.get("dossier_id"))
        dossier = db.get_decree_dossier(dossier_id)
        if dossier is None:
            raise KeyError(f"案卷不存在：{dossier_id}")
        decision = str(verdict.get("decision") or "")
        validate_verdict_affected_parties(
            verdict, str(dossier.get("mode") or "ordinary"),
            faction_names=faction_names, class_names=class_names,
        )
        if decision == "rejected":
            validate_rejection_verdict(
                verdict, db._PROMULGATION_BLOCKED_LAYERS - {""},
                faction_names=faction_names, class_names=class_names,
                character_ids=character_ids,
            )

    # #1583：荐人快照以批前盘面统一校验——同批前序任免造成的中间态不得
    # 令后序案卷二次校验失败。validate_recommendation_snapshot 仍是唯一真源。
    prevalidate_rows: List[Dict[str, object]] = []
    for verdict in rows:
        decision = str(verdict.get("decision") or "")
        if decision not in {"promulgated", "force_promulgated"}:
            continue
        dossier = db.get_decree_dossier(strict_int(verdict.get("dossier_id")))
        if dossier is not None:
            prevalidate_rows.append(dossier)
    db._prevalidate_office_recommendation_snapshots(state, prevalidate_rows)

    # Reuse the settlement rollback primitive so failed later effects restore
    # both SQLite and the caller's in-memory GameState.
    from ming_sim.decree import atomic_and_reload

    # Defer #670 fresh-summon consumption until every office origin in this
    # batch has been activated — one departure write per person/night.
    previous_summon_nights = getattr(db.conn, "_deferred_office_summon_nights", None)
    previous_reco_prevalidated = getattr(
        db.conn, "_recommendation_snapshots_prevalidated", False,
    )
    db.conn._deferred_office_summon_nights = set()
    db.conn._recommendation_snapshots_prevalidated = True
    try:
        with atomic_and_reload(db, state, content=content):
            for verdict in rows:
                decision = str(verdict.get("decision") or "")
                opponents = verdict.get("primary_opponents")
                snapshot = verdict.get("criteria_snapshot")
                apply_dossier_promulgation(db,
                    state, strict_int(verdict.get("dossier_id")), decision,
                    blocked_layer=str(verdict.get("blocked_layer") or ""),
                    reason=str(verdict.get("reason") or ""),
                    legal_reason_code=str(verdict.get("legal_reason_code") or ""),
                    primary_opponents=opponents if isinstance(opponents, list) else None,
                    gatekeeper_id=(str(verdict["gatekeeper_id"]).strip()
                                   if verdict.get("gatekeeper_id") is not None else None),
                    criteria_snapshot=snapshot if isinstance(snapshot, dict) else None,
                    content=content,
                )
                apply_dossier_verdict_metadata(db,
                    state, strict_int(verdict.get("dossier_id")), verdict,
                )
            summon_nights = set(getattr(db.conn, "_deferred_office_summon_nights", set()) or set())
            if summon_nights:
                from ming_sim.audience_night import commit_fresh_summons_for_night
                for night_id in sorted(summon_nights):
                    commit_fresh_summons_for_night(
                        db, state, int(night_id),
                        content=content,
                    )
    finally:
        db.conn._recommendation_snapshots_prevalidated = previous_reco_prevalidated
        if previous_summon_nights is None:
            if hasattr(db.conn, "_deferred_office_summon_nights"):
                delattr(db.conn, "_deferred_office_summon_nights")
        else:
            db.conn._deferred_office_summon_nights = previous_summon_nights


def apply_dossier_verdict_metadata(db, state, dossier_id, verdict) -> None:
    """Record verdict metadata and settle predeclared override costs."""
    db._record_dossier_verdict_metadata(state, dossier_id, verdict)
    dossier = db.get_decree_dossier(dossier_id)
    if (dossier and dossier.get("mode") == "midzhi"
            and verdict.get("decision") == "promulgated"):
        db._apply_override_costs(
            state, dossier_id, include_authority=True, include_parties=False,
            stigma_reason="预先中旨直发", commit=False,
        )
