"""人口守恒转移的**世界后果**计算：加派致流民入池、赈济／招抚屯田回流（#1901）。

从 `issues.py` 领域旧大块按职责拆出。归属：本模块只算并交
`flows._apply_population_transfers` 守恒原语落账——世界后果归本处，实况效果的
单一领域分派与唯一世界记录写口归 #1815／#1835／#1889／#1813，本模块不另造派发。

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
    RECOVERY_GRANT_ACTIONS,
    RECOVERY_OUTCOME_FACTORS,
    RECOVERY_PERSONS_PER_WAN,
)
from ming_sim.db import GameDB
from ming_sim.flows import _apply_population_transfers
from ming_sim.models import GameState

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
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """#650/0089 环后半段：结算按账机械驱动农民→流民入池（0087「applier 机械转移」，
    P6 代码只供事实＋clamp）。

    口径（AC2 确定性可断言）：每明省读 settle._meta「加派基线」(万两/月)，
    入池(人) = 基线 × LEVY_DISPLACEMENT_RATE(人/万两·月) × (100−民心)/100。
    结果钳到农民@省余额后再交 _apply_population_transfers 守恒原语落账
    （reason=加派；累积账月效统一使用 `盘面自发`，不伪归最后一道改账旨）。基线 ≤0 或折算后
    ≤0 的省零入池——停加派/蠲免后入池止（AC5；出口回流归 S5 #652）。
    """
    records: List[Dict[str, object]] = []
    rows = db.conn.execute(
        "SELECT id, fiscal, public_support FROM regions WHERE controlled_by='ming' ORDER BY id"
    ).fetchall()
    for row in rows:
        region_id = str(row["id"])
        try:
            from ming_sim.db import GameDB
            fiscal = GameDB.parse_engine_payload_json(
                row["fiscal"], surface=f"regions.fiscal:{region_id}",
            )
        except ValueError as exc:
            raise ValueError(f"{region_id}.fiscal 持久 JSON 损坏，无法结算加派账") from exc
        # 财政月效的动态成员只包括已有 settle 基座的明省；legacy/内容扩展中
        # 合法的无基座省自然出列，不能让任意 delta apply 因此失败。
        settle = GameDB.optional_object(
            fiscal.get("settle"), surface=f"{region_id}.fiscal.settle",
        )
        if settle is None:
            continue
        meta = GameDB.optional_object(
            settle.get("_meta"), surface=f"{region_id}.fiscal.settle._meta",
        )
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
    return _apply_population_transfers(db, records, commit=commit)

def _recovery_effective_silver_wan(db: GameDB, dossier_id: int, turn: int) -> int:
    """回流成本面唯一读缝：只认实付证据。

    本回合对账实抵优先；否则累加该案已落 economy_moves 负向出账。
    **不**回退 payload.amount（ordered 非实付，零 ledger 不得假阳性出回流）。
    """
    history = db.list_dossier_reconciliations(int(dossier_id))
    arrived_this_turn = [
        int(row["arrived_amount"])
        for row in history
        if int(row.get("turn") or 0) == int(turn)
    ]
    if arrived_this_turn:
        return max(0, sum(arrived_this_turn))
    paid = 0
    for move in db.list_economy_moves_for_dossier(int(dossier_id)):
        # economy_ledger.delta 是持久账本列，腐值必须响亮失败交外层事务回滚——
        # 静默跳过会把实付证据算少、凭空缩掉回流人口转移。
        delta = int(move.get("delta") or 0)
        if delta < 0:
            paid += -delta
    return max(0, paid)


def apply_recovery_driven_transfers(
    db: GameDB,
    state: GameState,
    *,
    commit: bool = True,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """#652/0087：赈济/招抚屯田回流单核（确定性；LLM 零产回流）。

    触发：带 recovery 身份的 grant_allocation（赈灾/招抚屯田）+ 属地 region +
    本回合已付代价 + 已落结构化执行判决。基线=实抵万两×RECOVERY_PERSONS_PER_WAN，
    再经执行 outcome 成色折减；经 _apply_population_transfers reason=回流 唯一落库。
    幂等键 (dossier_id, turn)：同键不双扣池。立即开仓/#522 pacification 不在此列。
    """
    turn = int(state.turn)
    # 月份推进事务只执行一次；同一案在本次扫描内仅回流一次。
    seen_keys: set[tuple[int, int]] = set()

    records: List[Dict[str, object]] = []
    remaining_by_region: Dict[str, int] = {}
    rows = db.conn.execute(
        """
        SELECT id, status, target_kind, target_id, payload_json,
               execution_outcome, closed_turn
        FROM decree_dossiers
        WHERE action_type='grant_allocation'
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        dossier_id = int(row["id"])
        if (dossier_id, turn) in seen_keys:
            continue
        # payload_json 是引擎自己写的持久列，解析失败＝账本腐值，必须响亮失败
        # 交外层事务回滚；静默 continue 会让这案赈济回流无声消失（#1897 E1）。
        from ming_sim.db import GameDB
        try:
            payload = GameDB.parse_engine_payload_json(
                row["payload_json"],
                surface=f"displaced.dossier#{dossier_id}.payload_json",
            )
        except ValueError as exc:
            raise ValueError(
                f"dossier {dossier_id}.payload_json 持久 JSON 损坏，无法结算回流"
            ) from exc
        grant_action = str(payload.get("grant_action") or "").strip()
        if grant_action not in RECOVERY_GRANT_ACTIONS:
            continue
        target_kind = str(row["target_kind"] or payload.get("target_kind") or "").strip()
        region_id = str(row["target_id"] or payload.get("target_id") or "").strip()
        if target_kind != "region" or not region_id:
            continue
        if db.conn.execute("SELECT 1 FROM regions WHERE id=?", (region_id,)).fetchone() is None:
            continue
        outcome = str(row["execution_outcome"] or "").strip()
        if outcome not in RECOVERY_OUTCOME_FACTORS:
            continue
        cadence = str(payload.get("cadence") or "").strip()
        closed_turn = int(row["closed_turn"] or 0)
        if cadence != "每月" and closed_turn != turn:
            continue
        factor = float(RECOVERY_OUTCOME_FACTORS[outcome])
        if factor <= 0:
            seen_keys.add((dossier_id, turn))
            continue
        if cadence == "每月":
            reconciled = [
                int(item["arrived_amount"])
                for item in db.list_dossier_reconciliations(dossier_id)
                if int(item.get("turn") or 0) == turn
            ]
            if reconciled:
                silver = max(0, sum(reconciled))
            else:
                paid_row = db.conn.execute(
                    "SELECT COALESCE(SUM(-delta), 0) FROM economy_ledger "
                    "WHERE origin_ref=? AND turn=? AND delta<0",
                    (f"dossier:{dossier_id}", turn),
                ).fetchone()
                silver = max(0, int(paid_row[0] or 0))
        else:
            silver = _recovery_effective_silver_wan(db, dossier_id, turn)
        if silver <= 0:
            continue
        raw_persons = silver * RECOVERY_PERSONS_PER_WAN * factor
        amount = int(round(raw_persons))
        if amount <= 0:
            continue
        pool_row = db.conn.execute(
            "SELECT population FROM classes WHERE name='流民' AND region_id=?",
            (region_id,),
        ).fetchone()
        farmer_row = db.conn.execute(
            "SELECT 1 FROM classes WHERE name='农民' AND region_id=?",
            (region_id,),
        ).fetchone()
        if pool_row is None or farmer_row is None:
            continue
        remaining = remaining_by_region.setdefault(region_id, int(pool_row["population"]))
        amount = min(amount, remaining)
        if amount <= 0:
            continue
        records.append({
            "source": f"流民@{region_id}",
            "target": f"农民@{region_id}",
            "amount": amount,
            "reason": "回流",
            "origin_ref": f"dossier:{dossier_id}",
        })
        remaining_by_region[region_id] = remaining - amount
        seen_keys.add((dossier_id, turn))
    if not records:
        return [], []
    return _apply_population_transfers(db, records, commit=commit)
