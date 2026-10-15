"""实体记账原语。"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState
from ming_sim.applier import RejectedItem, Provenance
from ming_sim.strict_types import strict_int as _strict_int


def _apply_economy_list(
    db: GameDB,
    state: GameState,
    economy: List[Dict[str, object]],
    *,
    allow_pay_arrears_pool: bool = False,
    pay_arrears_pool_army_ids: Optional[List[str]] = None,
    require_origin: bool = False,
    origin_ref: str = "",
    source: Provenance,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """落 extractor 抽出的 economy_moves 到 economy_ledger。

    支持结构化字段：
    - purpose='补饷' + target_kind='army' + target_id=army_id
      → 走真钱补饷路径：按该军当前省/中央欠额占比分销两累加器；
        同步把 armies.arrears 减掉 actual_pay；多余的钱留在 account 不扣。
    - 其它（purpose='其它' 或 NULL）：按常规扣账（现状）。

    LLM 写非法 purpose → 退化为'其它'常规扣账。
    purpose='补饷' 但目标缺失/不存在 → 逐项拒收，不得改付其它军队。
    allow_pay_arrears_pool=True 仅供承诺结算内部使用，表示该承诺的 arrears
    stop gate 已经给出范围，可在 pay_arrears_pool_army_ids 内按优先级池偿还。
    """
    rejections: List[RejectedItem] = []
    from ming_sim.army_pay import (
        _auto_pay_arrears_by_priority,
        _payable_army_arrears_cap,
        _pay_single_army_arrears,
    )
    from ming_sim.assets import format_wanliang_amount
    from ming_sim.constants import ECONOMY_ACCOUNTS, ECONOMY_PURPOSES, ECONOMY_TARGET_KINDS
    applied: List[Dict[str, object]] = []
    # Guard non-list input for all callers, including economy delta and dossier (#117).
    if not isinstance(economy, list):
        return [], [RejectedItem(item={"raw_value": economy}, reason="经济效果须为数组", category="invalid_shape", source=source)]
    for move in economy:
        if not isinstance(move, dict):
            rejections.append(RejectedItem(item={"raw_value": move}, reason="经济效果项须为对象", category="invalid_shape", source=source))
            continue
        # 先解析 delta：None/"" = 缺额 → 0 no-op；bool/float/坏串 → bad_delta（_strict_int 拒
        # bool/float，与 faction/region/army 同约）。no-op（可解析的 0/缺额）行无钱动 → 静默跳，
        # 不论 account（空占位行不当拒收，免噪声 + 假玩家提示，#14 cmr r1 线上 codex）。
        raw_delta = move.get("delta")
        delta_error = None
        try:
            delta = 0 if raw_delta in (None, "") else _strict_int(raw_delta)
        except (TypeError, ValueError) as exc:
            delta, delta_error = 0, str(exc)
        if delta_error is None and delta == 0:
            continue
        account = str(move.get("account") or "")
        if account not in ECONOMY_ACCOUNTS:
            # 账户非法不再静默丢——逐项拒收留痕（#14 ADR0008 决定1，统一拒收契约）。
            rejections.append(RejectedItem(item=move, reason=f"economy_moves 账户非法（须 国库/内库）：{account!r}", category="invalid_enum", source=source))
            continue
        if delta_error is not None:
            rejections.append(RejectedItem(item=move, reason=delta_error, category="invalid_enum", source=source))
            continue
        category_raw = move.get("category")
        if category_raw is None or not str(category_raw).strip():
            category_raw = move.get("reason")
        if category_raw is None or not str(category_raw).strip():
            category_raw = "事项"
        category = str(category_raw)
        reason_raw = move.get("reason")
        reason = "" if reason_raw is None else str(reason_raw)
        # 别名真源 ITEM_FIELD_ALIASES（#1917 C4：来源引用／诏书引用须入写口）。
        from ming_sim.simulation import _canonical_item_fields
        if isinstance(move, dict):
            move = _canonical_item_fields(move)
            if not isinstance(move, dict):
                rejections.append(RejectedItem(
                    item=move, reason="经济条目须为对象", category="invalid_shape", source=source,
                ))
                continue
        move_origin_ref = str(move.get("origin_ref") or "").strip()
        effective_origin_ref = str(origin_ref or move_origin_ref).strip()
        # #622：旨外标记与 origin_ref 同载体同寿命；路由前统一读取，三分支共用（不得在补饷分叉丢键）。
        # #1260：别名读取收敛 simulation 单源（嵌套通道不经 cleaner，须吃全套别名）。
        from ming_sim.simulation import read_beyond_intent_raw
        beyond_raw = read_beyond_intent_raw(move)
        from ming_sim.covert_levy import stopped_covert_effect
        if stopped_covert_effect(
            db, origin_ref=effective_origin_ref, beyond_intent=beyond_raw,
        ):
            rejections.append(RejectedItem(item=move, reason="该旧案暗渠摊派已奉旨禁绝", category="forbidden_effect", source=source))
            continue
        raw_purpose = str(move.get("purpose") or "").strip()
        raw_target_kind = str(move.get("target_kind") or "").strip()
        raw_target_id = str(move.get("target_id") or "").strip()
        # Closed enum membership KEEP（判词：形式标识/封闭枚举不作一律删除）.
        # #1847 N10：非法 purpose 不得再经 purpose or "其它" 静默改写成常规扣账；
        # 不为本票新增 invalid_enum 拒收护栏（无关非法输入契约维持既有落账路径）.
        purpose = raw_purpose if raw_purpose in ECONOMY_PURPOSES else None
        target_kind = raw_target_kind if raw_target_kind in ECONOMY_TARGET_KINDS else None
        if "transfer_to" in move:
            destination = move["transfer_to"]
            if (delta >= 0 or destination not in ECONOMY_ACCOUNTS
                    or destination == account or raw_purpose not in ("", "其它")
                    or raw_target_kind or raw_target_id):
                rejections.append(RejectedItem(item=move, reason="转库须从一账户扣款并指定另一账户", category="invalid_enum", source=source))
                continue

        # ── 补饷分发：按当前欠额占比分销两累加器 + 同步减 armies.arrears ───────
        # purpose=补饷 必须定向到具体 army_id；非定向补饷需要另立显式契约，
        # 不能把缺失/错拼目标 fallback 成改付其它军队。
        if purpose == "补饷" and delta < 0 and (target_kind != "army" or not raw_target_id):
            explicit_target = bool(raw_target_kind or raw_target_id)
            allowed_pool_ids = None
            if pay_arrears_pool_army_ids is not None:
                allowed_pool_ids = [
                    str(army_id) for army_id in pay_arrears_pool_army_ids
                    if str(army_id).strip()
                ]
            if (
                allow_pay_arrears_pool
                and not explicit_target
                and (pay_arrears_pool_army_ids is None or allowed_pool_ids)
            ):
                # The pooled path mutates treasury, both arrears ledgers and logs;
                # provenance must be authorized before the first of those writes.
                origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
                if origin_error:
                    rejections.append(RejectedItem(item=move, reason=origin_error["reason"], category=origin_error["category"], source=source))
                    continue
                budget = abs(delta)
                spent = _auto_pay_arrears_by_priority(
                    db,
                    state,
                    account,
                    budget,
                    category,
                    reason,
                    allowed_army_ids=allowed_pool_ids,
                    origin_ref=effective_origin_ref,
                    beyond_intent=beyond_raw,
                )
                from ming_sim.covert_levy import canonical_fiscal_result
                applied.append(canonical_fiscal_result(
                    db, move, applied=spent != 0,
                    effective_origin_ref=effective_origin_ref,
                    account=account, delta=-spent, reason=reason,
                ))
                continue
            rejections.append(RejectedItem(item=move, reason="economy_moves 补饷必须指定 target_kind='army' 与有效 target_id", category="missing_ref", source=source))
            continue
        if purpose == "补饷" and target_kind == "army" and delta < 0 and raw_target_id:
            row = db.armies.row(raw_target_id)
            if row is None:
                rejections.append(RejectedItem(item=move, reason=f"economy_moves 补饷目标军队未入库：{raw_target_id}", category="missing_ref", source=source))
                continue
            origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
            if origin_error:
                rejections.append(RejectedItem(item=move, reason=origin_error["reason"], category=origin_error["category"], source=source))
                continue
            payable_arrears = _payable_army_arrears_cap(row)
            if payable_arrears <= 0:
                # 可付额与事实文案均只认双源权威账；派生 arrears 列不得回读改判。
                current_arrears = (
                    float(row["province_pay_arrears"] or 0)
                    + float(row["central_pay_arrears"] or 0)
                )
                if current_arrears > 0:
                    reason_text = (
                        f"{row['name']}欠饷不足1万两，"
                        f"{format_wanliang_amount(abs(delta))}万两未拨"
                    )
                else:
                    reason_text = (
                        f"{row['name']}已无欠饷，"
                        f"{format_wanliang_amount(abs(delta))}万两未拨"
                    )
                from ming_sim.covert_levy import canonical_fiscal_result
                applied.append(canonical_fiscal_result(
                    db, move, applied=False,
                    effective_origin_ref=effective_origin_ref,
                    account=account, delta=0, reason=reason_text,
                ))
                continue
            spent = _pay_single_army_arrears(
                db, state, row, account, min(abs(delta), payable_arrears), category,
                reason, "诏拨补饷", origin_ref=effective_origin_ref,
                beyond_intent=beyond_raw,
            )
            if spent:
                db._reconcile_army_pay_source_region_container(str(row["pay_source_region"] or ""))
                db._reconcile_central_army_pay_arrears_container()
                from ming_sim.covert_levy import canonical_fiscal_result
                applied.append(canonical_fiscal_result(
                    db, move, applied=True,
                    effective_origin_ref=effective_origin_ref,
                    account=account, delta=-spent, reason=reason,
                ))
            continue

        # ── 常规扣账（其它/无 purpose）─────────────────────────────────────────
        origin_error = db.effect_origin_rejection(effective_origin_ref) if require_origin else None
        if origin_error:
            rejections.append(RejectedItem(item=move, reason=origin_error["reason"], category=origin_error["category"], source=source))
            continue
        if "transfer_to" in move:
            destination = move["transfer_to"]
            # A transfer is one declaration: the source ledger determines the amount.
            actual = db.record_issue_economy_move(
                state, account, delta, category, reason,
                purpose="其它", origin_ref=effective_origin_ref,
                beyond_intent=beyond_raw, commit=False,
            )
            received = 0
            if actual:
                received = db.record_issue_economy_move(
                    state, destination, -actual, category, reason,
                    origin_ref=effective_origin_ref, beyond_intent=beyond_raw,
                    commit=False, apply_income_modifier=False,
                )
                if received != -actual:
                    raise RuntimeError("钱库互拨双边实数不等")
            from ming_sim.covert_levy import canonical_fiscal_result
            for leg_account, leg_delta in ((account, actual), (destination, received)):
                applied.append(canonical_fiscal_result(
                    db, move, applied=actual != 0,
                    effective_origin_ref=effective_origin_ref,
                    account=leg_account, delta=leg_delta, reason=reason,
                ))
            continue
        # 空缺 purpose 的支出仍默认「其它」；非法 purpose（membership 未命中）保持 None，不改写。
        recorded_purpose = purpose
        if recorded_purpose is None and delta < 0 and not raw_purpose:
            recorded_purpose = "其它"
        actual = db.record_issue_economy_move(
            state, account, delta, category, reason,
            purpose=recorded_purpose,
            target_kind=None, target_id=None, origin_ref=effective_origin_ref,
            beyond_intent=beyond_raw,
            commit=False,
        )
        if actual:
            from ming_sim.covert_levy import canonical_fiscal_result
            applied.append(canonical_fiscal_result(
                db, move, applied=True,
                effective_origin_ref=effective_origin_ref,
                account=account, delta=actual, reason=reason,
            ))
    return applied, rejections
