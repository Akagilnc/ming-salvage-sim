"""Role-scoped qualitative projection of provincial displaced-person pressure."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Tuple

from ming_sim.constants import RECOVERY_GRANT_ACTIONS
from ming_sim.db import POPULATION_UNIT_PERSONS


def displaced_pool_balance_rows(db: Any) -> List[Dict[str, object]]:
    """#652：机面结构化省级流民池清单（region_id + 余额 + population_unit）。

    复用 classes 主账流民行，不新建表。供 simulator / 投贼吸收软判吃池顶；
    玩家面 classes_brief 定性投影另走 regional_displaced_pressure_brief。
    """
    unit = str(getattr(db, "population_unit", "") or "")
    if unit != POPULATION_UNIT_PERSONS:
        return []
    return [
        {
            "region_id": str(row["region_id"]),
            "population": int(row["population"]),
            "population_unit": unit,
        }
        for row in db.conn.execute(
            "SELECT c.region_id, c.population FROM classes c "
            "JOIN regions r ON r.id=c.region_id "
            "WHERE c.name='流民' AND c.region_id <> '' AND r.controlled_by='ming' "
            "ORDER BY c.region_id"
        ).fetchall()
    ]


def iter_recent_population_transfers(
    db: Any, *, recent_turns: int = 3,
) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """近窗未 rejected 的 population_transfers 共享读核。

    唯一 latest_turn / 窗口 / transfers 扫描；brief 与回流原因投影共同消费。
    yield (turn, item)。
    """
    latest_turn = int(db.conn.execute(
        "SELECT COALESCE(MAX(turn), -1) FROM turn_extractions"
    ).fetchone()[0])
    if latest_turn < 0:
        return
    first_turn = max(0, latest_turn - max(1, int(recent_turns)) + 1)
    for turn in range(first_turn, latest_turn + 1):
        extraction = db.get_turn_extraction(turn) or {}
        applied = extraction.get("extractor_output") or {}
        if not isinstance(applied, dict):
            continue
        for item in applied.get("population_transfers") or []:
            if not isinstance(item, dict) or item.get("rejected"):
                continue
            yield turn, item


def recent_reflux_cause_rows(
    db: Any, *, recent_turns: int = 3,
) -> List[Dict[str, object]]:
    """#652：近窗回流原因投影（region_id + grant_action + origin_ref）。

    只报赈灾/招抚屯田案卷 provenance；不报口数、不改账本。
    去重键 (region_id, grant_action, origin_ref)。
    """
    rows: List[Dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for _turn, item in iter_recent_population_transfers(db, recent_turns=recent_turns):
        if item.get("reason") != "回流":
            continue
        source = str(item.get("source") or "")
        if not source.startswith("流民@"):
            continue
        region_id = source.split("@", 1)[1].strip()
        if not region_id:
            continue
        origin_ref = str(item.get("origin_ref") or "").strip()
        if not origin_ref.startswith("dossier:"):
            continue
        raw_id = origin_ref.removeprefix("dossier:")
        if not raw_id.isdigit():
            continue
        dossier = db.get_decree_dossier(int(raw_id))
        if dossier is None:
            continue
        try:
            payload = dossier.get("payload")
            if not isinstance(payload, dict):
                payload = json.loads(str(dossier.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        grant_action = str(payload.get("grant_action") or "").strip()
        if grant_action not in RECOVERY_GRANT_ACTIONS:
            continue
        key = (region_id, grant_action, origin_ref)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "region_id": region_id,
            "grant_action": grant_action,
            "origin_ref": origin_ref,
        })
    return rows


def regional_displaced_pressure_brief(db: Any, *, recent_turns: int = 3) -> str:
    """Describe current pressure and recent direction without exposing headcounts.

    Current class balances are the magnitude source; durable settlement extractions
    are the trend source.  This is a read model only and creates no public event.
    """
    rows = db.conn.execute(
        """
        SELECT r.id, r.name,
               COALESCE(f.population, 0) AS farmers,
               COALESCE(d.population, 0) AS displaced
        FROM regions r
        JOIN classes f ON f.region_id=r.id AND f.name='农民'
        JOIN classes d ON d.region_id=r.id AND d.name='流民'
        ORDER BY r.id
        """
    ).fetchall()
    net_by_region: dict[str, int] = {}
    levy_net_by_region: dict[str, int] = {}
    for _turn, item in iter_recent_population_transfers(db, recent_turns=recent_turns):
        amount = item.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        source = str(item.get("source") or "")
        target = str(item.get("target") or "")
        if target.startswith("流民@"):
            region_id = target.split("@", 1)[1]
            net_by_region[region_id] = net_by_region.get(region_id, 0) + amount
            if item.get("reason") == "加派":
                levy_net_by_region[region_id] = levy_net_by_region.get(region_id, 0) + amount
        if source.startswith("流民@"):
            region_id = source.split("@", 1)[1]
            net_by_region[region_id] = net_by_region.get(region_id, 0) - amount
            if item.get("reason") == "加派":
                levy_net_by_region[region_id] = levy_net_by_region.get(region_id, 0) - amount

    result: list[str] = []
    for row in rows:
        farmers, displaced = int(row["farmers"]), int(row["displaced"])
        total = farmers + displaced
        ratio = displaced / total if total > 0 else 0.0
        pressure = "高" if ratio >= 0.10 else "中" if ratio >= 0.03 else "低"
        net = net_by_region.get(str(row["id"]), 0)
        trend = "上升" if net > 0 else "回落" if net < 0 else "平稳"
        levy_net = levy_net_by_region.get(str(row["id"]), 0)
        levy_echo = "，期间加派致流民流入" if levy_net > 0 else ""
        result.append(f"{row['name']}：流民压力{pressure}，近月{trend}{levy_echo}")
    return "；".join(result)
