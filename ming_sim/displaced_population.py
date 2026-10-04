"""人口守恒转移的**世界后果**计算：加派致流民入池、赈济／招抚屯田回流（#1901）。

从 `issues.py` 领域旧大块按职责拆出。归属：本模块只算并交
`entities.population.apply._apply_population_transfers` 守恒原语落账——世界后果归本处，实况效果的
单一领域分派与唯一世界记录写口归 #1815／#1835／#1889／#1813，本模块不另造派发。
回流单核住 `entities.population.recovery`，本模块不并行持有。

- 「加派基线」键名在此单定义：下旨写入口（`issues._apply_surcharge_decrees`）与
  月初消费口（本模块）共用同一真源名，不各持一份字面量。
- 幂等由调用方月链保证（月初旧账只消费一次 `opening_levy_done`；回流按
  (dossier_id, turn) 去重），本模块不另持恢复生命周期（ADR 0157）。
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Tuple

from ming_sim.constants import (
    LEVY_DISPLACEMENT_RATE,
)
from ming_sim.db import GameDB, POPULATION_UNIT_PERSONS
from ming_sim.applier import Provenance
from ming_sim.entities.population.apply import _apply_population_transfers

# #650/0089 明渠：下旨加派逐省累积账（万两/月，负额停征/蠲免、钳 ≥0）。
# 与 #649 饷率 seed 同址（settle._meta），restore 只读 DB 无损接续（P1）。
SETTLE_META_JIAPIAI_KEY = "加派基线"


def surcharge_population_pool_members(db: GameDB, region_id: str) -> set[str]:
    """Return the materialized provincial rows that make up a surcharge pool."""
    return {
        str(row["name"])
        for row in db.conn.execute(
            "SELECT name FROM classes WHERE region_id=? AND name IN ('农民', '流民')",
            (region_id,),
        ).fetchall()
    }

def apply_levy_driven_transfers(
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
        raw = meta.get(SETTLE_META_JIAPIAI_KEY, 0) if meta is not None else 0
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ValueError(f"{region_id}.settle._meta.{SETTLE_META_JIAPIAI_KEY} 必须是有限数值")
        base = max(0.0, float(raw))
        if base <= 0:
            continue
        pool_members = surcharge_population_pool_members(db, region_id)
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
