"""实体记账原语。"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple
if TYPE_CHECKING:
    from ming_sim.db import GameDB
from ming_sim.applier import RejectedItem, Provenance
from ming_sim.strict_types import strict_int as _strict_int


def _apply_population_transfers(
    db: GameDB,
    transfers: object,
    *,
    source: Provenance,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """#649/ADR 0087：人口守恒转移原语（delta 段 population_transfers 的唯一落库核）。

    canonical 段形＝转移记录 list；每条记录**同时表达两条腿**（源阶级减 N、目标阶级
    增 N），本核读一条合法记录后在同一事务内机械完成两次写——LLM 不提交双腿，
    系统不建配平器（单记录双写从形状上消灭合法路径的单侧变动）。两侧更新复用调用方
    事务边界。本核不提交。

    校验分层（ADR 0015，r4 终态）：section 非 list 已由 sanitize_delta_shape 拒段；
    list 内坏记录逐项拒收留痕（非 dict 项按 0015 F1 {'raw_value':…} 包装），好记录照落。
    逐项拒收面：方向不在矩阵（constants.POPULATION_TRANSFER_REASONS）；reason 枚举
    非法；requested amount 非 int/≤0；region 未知或两侧不同省；source/target 触及全国
    行；origin_ref 缺失/伪前缀/未颁案卷；白名单外字段。数据拒收永不中止事务；代码
    异常照常上抛由 applier.atomic 回滚（两轴分立）。

    返回 (applied list, rejections list)：前者供当前声明落账反馈，
    后者为 canonical RejectedItem，由段适配器并入 SectionResult.rejected。
    """
    from ming_sim.constants import (
        POPULATION_TRANSFER_FIELDS,
        POPULATION_TRANSFER_REASONS,
    )
    from ming_sim.db import POPULATION_UNIT_PERSONS

    applied: List[Dict[str, object]] = []
    rejected: List[RejectedItem] = []
    items = transfers if isinstance(transfers, list) else []
    for item in items:
        if not isinstance(item, dict):
            rejected.append(RejectedItem(item={"raw_value": item}, reason="population_transfers 项必须是 object(dict)", category="invalid_shape", source=source))
            continue

        def _reject(category: str, reason: str) -> None:
            rejected.append(RejectedItem(item=item, reason=reason, category=category, source=source))

        extra = sorted(set(item) - POPULATION_TRANSFER_FIELDS)
        if extra:
            _reject(
                "invalid_enum",
                f"population_transfers 白名单外字段 {extra}（绝对值覆写不合法；"
                "人口只经单记录守恒转移变动）",
            )
            continue
        row_source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if row_source.count("@") != 1 or target.count("@") != 1:
            _reject(
                "invalid_shape",
                f"source/target 须为 阶级@region_id 省级行：{row_source!r} / {target!r}",
            )
            continue
        src_cls, src_region = (part.strip() for part in row_source.split("@", 1))
        dst_cls, dst_region = (part.strip() for part in target.split("@", 1))
        if not src_cls or not dst_cls or not src_region or not dst_region:
            _reject(
                "invalid_shape",
                f"source/target 须为非空 阶级@region_id 省级行（全国行不合法）：{row_source!r} / {target!r}",
            )
            continue
        if src_region != dst_region:
            _reject(
                "invalid_shape",
                f"跨省转移本票不做（#475 预留）：{row_source!r} → {target!r} 须同省",
            )
            continue
        if (
            db.regions.read_assert_commission_grant_target_exists(
                (src_region,)
            )
            is None
        ):
            _reject("missing_ref", f"population_transfers 未知 region_id：{src_region!r}")
            continue
        # 枚举查键用 strip 副本；落库/回执保留声明原文（F5）。
        raw_reason = str(item.get("reason") or "")
        reason = raw_reason.strip()
        matrix = POPULATION_TRANSFER_REASONS.get(reason)
        if matrix is None:
            _reject(
                "invalid_enum",
                f"population_transfers reason 非法（枚举：{'/'.join(POPULATION_TRANSFER_REASONS)}）：{raw_reason!r}",
            )
            continue
        if (src_cls, dst_cls) not in matrix:
            _reject(
                "invalid_enum",
                f"population_transfers 方向出阵：reason={raw_reason!r} 不允许 {src_cls}→{dst_cls}"
                f"（合法：{'、'.join(f'{a}→{b}' for a, b in sorted(matrix))}）",
            )
            continue
        raw_amount = item.get("amount")
        try:
            # 数量契约＝严格 int（含拒无损整数串）：extractor 提示明令直接输出数字，
            # 转移账不沿用 fiscal 的整数串宽容（#649 票面：amount 非 int 即拒）。
            amount = _strict_int(raw_amount, accept_numeric_strings=False)
        except (TypeError, ValueError) as exc:
            _reject("invalid_enum", str(exc))
            continue
        if amount <= 0:
            _reject("invalid_enum", f"population_transfers amount 须为正整数：{amount!r}")
            continue
        origin_ref = str(item.get("origin_ref") or "").strip()
        from ming_sim.covert_levy import active_prohibition_dossier
        prohibited_population_levy = False
        if reason == "摊派" and origin_ref.startswith("dossier:"):
            raw_dossier_id = origin_ref.removeprefix("dossier:")
            prohibited_population_levy = (
                raw_dossier_id.isdigit()
                and active_prohibition_dossier(db, int(raw_dossier_id)) is not None
            )
        if prohibited_population_levy:
            _reject("forbidden_effect", "该旧案暗渠摊派已奉旨禁绝")
            continue
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejected.append(RejectedItem(item=item, reason=f"population_transfers {origin_error['reason']}", category=origin_error["category"], source=source))
            continue
        src_row = db.classes.read_apply_population_transfers(
            (src_cls, src_region)
        )
        dst_row = db.classes.read_apply_population_transfers(
            (dst_cls, dst_region)
        )
        if src_row is None or dst_row is None:
            missing = row_source if src_row is None else target
            _reject(
                "missing_ref",
                f"population_transfers 查无此阶级省级行「{missing}」"
                f"（流民池＝classes 省级行，全国行不参与守恒主账）",
            )
            continue
        # The declaration is a proposed amount. The classes ledger owns the actual
        # transfer: cap to current source stock, then write the same actual on both
        # sides. A depleted source is a legal zero actual, not an invalid declaration;
        # keep it in the applied feedback even though there is no ledger write.
        amount = min(amount, int(src_row["population"]))
        if amount > 0:
            # 单记录双写：同一事务内源减目标增，任一腿失败整体回滚（ADR 0008 决定 2）。
            db.classes.record_population_transfer(
                src_cls, src_region, dst_cls, dst_region, amount,
                turn=int(db.reign.read_current_settle_turn(())[0]),
                source=row_source, target=target, reason=raw_reason, origin_ref=origin_ref,
            )
        region_name = str(
            db.regions.field_row('name', src_region)["name"]
            or ""
        )
        applied.append({
            "source": row_source,
            "target": target,
            "amount": amount,
            "reason": raw_reason,
            "origin_ref": origin_ref,
            "region_id": src_region,
            # #649 F2（判词）：省名随 applied 记录入摘要——applied 记录省名
            # 而非裸 region_id；真源＝既有 regions 表，不另建映射。
            "region_name": region_name,
            "population_unit": POPULATION_UNIT_PERSONS,
        })
    return applied, rejected
