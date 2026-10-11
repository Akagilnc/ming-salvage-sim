"""加派旨记账。调用方拥有事务，本核不提交。"""
from __future__ import annotations

from ming_sim.constants import _SETTLE_META_JIAPIAI_KEY as SETTLE_META_JIAPIAI_KEY

import json
import math
import re
from typing import TYPE_CHECKING, Dict, List, Tuple
if TYPE_CHECKING:
    from ming_sim.db import GameDB

from ming_sim.displaced_population import surcharge_population_pool_members as _surcharge_population_pool_members
from ming_sim.applier import Provenance, RejectedItem

SURCHARGE_DECREE_FIELDS = frozenset({"region_id", "monthly_amount", "reason", "origin_ref"})


def _apply_surcharge_decrees(
    db: GameDB,
    items: object,
    *,
    source: Provenance = Provenance.system_simulation,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """#650/0089 明渠：下旨加派 → 逐省加派量累积账当回合落库（P1）。

    canonical 段形＝list，每项 {region_id, monthly_amount, reason?, origin_ref}：
    monthly_amount 为月额增量（万两/月，带符号——正＝加派累加，负＝停征/蠲免），
    落在 regions.fiscal.settle._meta「加派基线」上（与 #649 饷率 seed 同址，
    钳制 ≥0）。钱面由 ming_sim.entities.fiscal.levy._apply_fiscal_levy_targets 把
    基线折入三饷应征/起运定额（明选有明账，公开代价＝真征收）；民面由
    _apply_levy_driven_transfers 按账机械入池。无旨不入账：段空＝账不动。

    逐项拒收面（ADR 0015/0008）：非 dict 项；region 未知/非明省/无 settle 基座；
    monthly_amount 非 bool 非有限数值或为 0（无操作不落，同 fiscal_changes 口径）；
    origin_ref 缺失/伪前缀/未颁案卷（复用 effect_origin_rejection 单一真源）；
    白名单外字段。坏项留痕、好项照落；数据拒收不中止事务。
    """
    from ming_sim.constants import _SETTLE_META_JIAPIAI_KEY
    applied: List[Dict[str, object]] = []
    rejected: List[RejectedItem] = []
    claimed_origins: set[tuple[str, str]] = set()
    for item in (items if isinstance(items, list) else []):
        if not isinstance(item, dict):
            rejected.append(RejectedItem(item={"raw_value": item}, reason="surcharge_decrees 项必须是 object(dict)", category="invalid_shape", source=source))
            continue

        def _reject(category: str, reason: str) -> None:
            rejected.append(RejectedItem(item=item, reason=reason, category=category, source=source))

        extra = sorted(set(item) - SURCHARGE_DECREE_FIELDS)
        if extra:
            _reject(
                "invalid_enum",
                f"surcharge_decrees 白名单外字段 {extra}（合法字段：region_id/monthly_amount/reason/origin_ref）",
            )
            continue
        region_id = str(item.get("region_id") or "").strip()
        row = db.conn.execute(
            "SELECT controlled_by, fiscal FROM regions WHERE id=?", (region_id,)
        ).fetchone() if region_id else None
        if row is None:
            _reject("missing_ref", f"surcharge_decrees 未知 region_id：{region_id!r}")
            continue
        if str(row["controlled_by"] or "") != "ming":
            _reject("missing_ref", f"surcharge_decrees 非明省不可加派：{region_id!r}")
            continue
        from ming_sim.db import GameDB
        fiscal = GameDB.parse_engine_payload_json(
            row["fiscal"],
        )
        settle = fiscal.get("settle")
        if settle is None:
            _reject(
                "missing_ref",
                f"surcharge_decrees {region_id!r} 无 settle 财政基座，逐省累积账无处落",
            )
            continue
        if _surcharge_population_pool_members(db, region_id) != {"农民", "流民"}:
            _reject("missing_ref", f"surcharge_decrees {region_id!r} 缺农民/流民省级人口池")
            continue
        raw_amount = item.get("monthly_amount")
        if raw_amount is None:
            _reject("invalid_enum", "surcharge_decrees monthly_amount 缺失")
            continue
        if isinstance(raw_amount, bool) or not isinstance(raw_amount, (int, float)):
            _reject("invalid_enum", f"surcharge_decrees monthly_amount 非数值：{raw_amount!r}")
            continue
        amount = float(raw_amount)
        if not math.isfinite(amount):
            _reject("invalid_enum", f"surcharge_decrees monthly_amount 非有限值(NaN/inf)：{raw_amount!r}")
            continue
        if amount == 0:
            continue  # 无操作不落拒（同 fiscal_changes 0-delta 口径）
        origin_ref = str(item.get("origin_ref") or "").strip()
        dossier_match = re.fullmatch(r"dossier:([1-9][0-9]*)", origin_ref)
        if dossier_match is None:
            _reject("missing_ref", "surcharge_decrees origin_ref 必须引用已物化旨意 dossier:<正整数>")
            continue
        origin_error = db.effect_origin_rejection(origin_ref)
        if origin_error:
            _reject(origin_error["category"], f"surcharge_decrees {origin_error['reason']}")
            continue
        claim = (origin_ref, region_id)
        if claim in claimed_origins:
            _reject("invalid_enum", "surcharge_decrees 同批同一旨意与省份只能成功一次")
            continue
        # Free prose surcharge reason: preserve raw; no length gate/crop (#1834 F16).
        reason = str(item.get("reason") or "")
        meta_raw = settle.get("_meta")
        meta = {} if meta_raw is None else {**meta_raw}
        old = max(0.0, float(meta.get(SETTLE_META_JIAPIAI_KEY, 0) or 0))
        new = max(0.0, old + amount)  # 负额停征/蠲免，账面钳 ≥0
        meta[_SETTLE_META_JIAPIAI_KEY] = new
        settle["_meta"] = meta
        db.conn.execute(
            "UPDATE regions SET fiscal = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(fiscal, ensure_ascii=False), region_id),
        )
        claimed_origins.add(claim)
        applied.append({
            "region_id": region_id,
            "monthly_amount": amount,
            "reason": reason,
            "origin_ref": origin_ref,
            "加派基线": new,
        })
    return applied, rejected
