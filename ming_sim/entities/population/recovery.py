"""Recovery population accounting, owned by the population domain."""
from __future__ import annotations
from typing import Dict, List, Tuple
from ming_sim.db import GameDB
from ming_sim.models import GameState
from ming_sim.applier import Provenance, RejectedItem
from ming_sim.constants import (
    RECOVERY_GRANT_ACTIONS, RECOVERY_OUTCOME_FACTORS,
    RECOVERY_PERSONS_PER_WAN,
)

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
        delta = int(move.get("delta") or 0)
        if delta < 0:
            paid += -delta
    return max(0, paid)


def _apply_recovery_driven_transfers(
    db: GameDB,
    state: GameState,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    """#652/0087：赈济/招抚屯田回流单核（确定性；LLM 零产回流）。

    触发：带 recovery 身份的 grant_allocation（赈灾/招抚屯田）+ 属地 region +
    本回合已付代价 + 已落结构化执行判决。基线=实抵万两×RECOVERY_PERSONS_PER_WAN，
    再经执行 outcome 成色折减；经 _apply_population_transfers reason=回流 唯一落库。
    幂等键 (dossier_id, turn)：同键不双扣池。立即开仓/#522 pacification 不在此列。
    """
    from ming_sim.entities.population.apply import _apply_population_transfers
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
        payload = db.get_decree_dossier(dossier_id)["payload"]
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
    applied, rejected = _apply_population_transfers(db, records, source=Provenance.system_simulation)
    return applied, rejected

