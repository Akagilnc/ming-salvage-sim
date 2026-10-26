"""Physical journey arithmetic; game months have thirty days (ADR 0163)."""

from math import ceil

from ming.ledger import Item

SPEEDS = {"常速": 45, "加急": 85, "押运": 45}


def travel_days(distance: float) -> Item:
    """Derived values are read projections, never a second stored distance table."""
    return {
        "distance": distance,
        "days": {pace: distance / speed for pace, speed in SPEEDS.items()},
        "delivery_days": distance / 300,
        "deadline_days": distance / SPEEDS["常速"],
    }


def arrival_date(departure: Item, distance: float, pace: str) -> Item:
    """Round a partial travelling day up so arrival never precedes completion."""
    months, day = divmod(departure["day"] - 1 + ceil(travel_days(distance)["days"][pace]), 30)
    years, month = divmod(departure["month"] - 1 + months, 12)
    return {"year": departure["year"] + years, "month": month + 1, "day": day + 1}
