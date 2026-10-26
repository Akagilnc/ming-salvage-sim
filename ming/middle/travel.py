"""Physical journey arithmetic; game months have thirty days (ADR 0163)."""

from collections.abc import Callable
from math import ceil

from ming.ledger import Entity, Item, Ledger

SPEEDS = {"常速": 45, "加急": 85, "押运": 45}
CLEARED_JOURNEY = {
    "transit_to": "",
    "departure_date": None,
    "arrival_date": None,
    "travel_speed": None,
    "waiting_audience": False,
}


def journey_route(ledger: Ledger, data: Item, changes: Item) -> tuple[str, float] | None:
    """The sole departure decision and route lookup for validation and landing."""
    destination: str = changes.get("location", data.get("location", ""))
    if (not data.get("location") or data.get("transit_to")
            or changes.get("status") not in (None, "active") or destination == data["location"]):
        return None
    rows = ledger.entities(kind="distance", key=data["location"])
    distances: Item = rows[0]["data"] if rows else {}
    return destination, distances[destination]


def move_person(
    person: Entity,
    changes: dict[str, object],
    ledger: Ledger,
    record: Callable[[Entity, str, Item, Item], None],
    date: Item,
) -> None:
    route = journey_route(ledger, person.data, changes)
    day = changes.pop("departure_day", None)
    pace = changes.pop("travel_speed", "常速")
    # A first location is a fact, not a journey from an invented origin.
    if not person.data.get("location"):
        return
    changes.pop("location", None)
    if changes.get("status") not in (None, "active"):
        # Leaving active (卒/下狱/罢黜/归场) clears the journey like offstage does.
        changes.update(CLEARED_JOURNEY)
    elif route is not None:
        destination, distance = route
        departure = {"year": date["year"], "month": date["month"], "day": day}
        journey = {
            "transit_to": destination,
            "departure_date": departure,
            "arrival_date": arrival_date(departure, distance, str(pace)),
            "travel_speed": pace,
            "waiting_audience": False,
        }
        record(person, "departed", {"destination": destination, "distance": distance, **journey}, journey)
        changes["status"] = "active"
    elif person.data.get("transit_to"):
        changes["status"] = "active"


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
