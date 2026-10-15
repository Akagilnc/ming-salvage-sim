"""势力领域核算原语。"""
from __future__ import annotations
from typing import Dict, List, Tuple
from ming_sim.applier import RejectedItem, Provenance
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.models import GameState
from ming_sim.constants import BANDIT_ABSORPTION_FIELDS, BANDIT_ABSORPTION_PERSONS_PER_STRENGTH
from ming_sim.strict_types import strict_int as _strict_int


def _is_bandit_power_id(power_id: str) -> bool:
    """流寇总股与分股（bandits / bandit_*）；投贼吸收与正实力门控共用。"""
    pid = str(power_id or "").strip()
    return pid == "bandits" or pid.startswith("bandit_")


def _apply_bandit_absorptions(
    db: GameDB,
    state: GameState,
    absorptions: object,
    *,
    source: Provenance = Provenance.system_simulation,
) -> Tuple[List[Dict[str, object]], List[RejectedItem], List[Dict[str, object]]]:
    """#652/0087：流民投贼吸收原子 applier。

    LLM 只产 typed 请求；本核：actual=min(requested, 省池)→扣流民池（无农民对端，
    0087 兵源出口单侧出池）→仅 actual>0 允许实力正增（δ=actual//换算率，0–100 clamp
    走 apply_power_deltas）。非法 id/零池正请求 → 逐项拒收留痕。
    返回 (applied_absorptions, rejections, power_changes)。
    """
    applied: List[Dict[str, object]] = []
    rejected: List[RejectedItem] = []
    power_changes: List[Dict[str, object]] = []
    items = absorptions if isinstance(absorptions, list) else []
    from ming_sim.simulation import _canonical_item_fields

    for item in items:
        if not isinstance(item, dict):
            rejected.append(RejectedItem(item={"raw_value": item}, reason="bandit_absorptions 项必须是 object(dict)", category="invalid_shape", source=source))
            continue
        item = _canonical_item_fields(item)
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
        region_row = db.regions.row(region_id, fields="controlled_by")
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
        power_row = db.powers.row(power_id, fields="id")
        if power_row is None:
            _reject("hallucinated_id", f"bandit_absorptions 引用未入库势力 '{power_id}'")
            continue
        raw_req = item.get("requested_count")
        try:
            requested = _strict_int(raw_req, accept_numeric_strings=False)
        except (TypeError, ValueError) as exc:
            _reject("invalid_enum", str(exc))
            continue
        if requested <= 0:
            _reject("invalid_enum", f"bandit_absorptions requested_count 须为正整数：{requested!r}")
            continue
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            rejected.append(RejectedItem(item=item, reason=f"bandit_absorptions {origin_error['reason']}", category=origin_error["category"], source=source))
            continue
        pool_row = db.classes.row(("流民", region_id), fields="population")
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
        db.classes.subtract_population(actual, "流民", region_id)
        strength_delta = actual // int(BANDIT_ABSORPTION_PERSONS_PER_STRENGTH)
        applied_item: Dict[str, object] = {
            "region_id": region_id,
            "power_id": power_id,
            "requested_count": requested,
            "actual_count": actual,
            "strength_delta": strength_delta,
            "origin_ref": origin_ref,
            "population_unit": POPULATION_UNIT_PERSONS,
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
    return applied, rejected, power_changes
