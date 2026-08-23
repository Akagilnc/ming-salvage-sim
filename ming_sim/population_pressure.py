"""Role-scoped qualitative projection of provincial displaced-person pressure."""

from __future__ import annotations

from typing import Any


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
    latest_turn = int(db.conn.execute(
        "SELECT COALESCE(MAX(turn), -1) FROM turn_extractions"
    ).fetchone()[0])
    first_turn = max(0, latest_turn - max(1, int(recent_turns)) + 1)
    net_by_region: dict[str, int] = {}
    levy_net_by_region: dict[str, int] = {}
    if latest_turn >= 0:
        for turn in range(first_turn, latest_turn + 1):
            extraction = db.get_turn_extraction(turn) or {}
            applied = extraction.get("extractor_output") or {}
            if not isinstance(applied, dict):
                continue
            for item in applied.get("population_transfers") or []:
                if not isinstance(item, dict) or item.get("rejected"):
                    continue
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
