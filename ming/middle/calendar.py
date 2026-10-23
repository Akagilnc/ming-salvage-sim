"""Monthly person movement and calendar advance share one ledger transaction."""

from ming.ledger import Entity, Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS


CAPITAL = "北直隶 / 京师"


def next_month(date: Item) -> Item:
    return {
        "year": date["year"] + (date["month"] == 12),
        "month": date["month"] % 12 + 1,
    }


def calendar_row(ledger: Ledger) -> Item | None:
    return next(iter(ledger.entities(kind="calendar")), None)


def petition_date(date: Item, *, ended: bool = True) -> Item:
    """When a petition can be chosen: this month, or next month once the segment ended."""
    opened = dict(date)
    if ended:
        opened.update(next_month(date))
    return opened


def advance_month(ledger: Ledger) -> None:
    rows = ledger.entities(
        kind="person", query=ENTITY_ROWS.where(E.data["transit_to"].as_string() != "")
    )
    row = calendar_row(ledger)
    if row is None:
        raise IndexError("calendar")
    calendar = ledger.get(row["id"])
    date = dict(calendar.data)
    changed: list[Entity] = []
    for row in rows:
        person = ledger.get(row["id"])
        remaining = person.data["remaining_distance"] - person.data.get(
            "travel_speed", 1
        )
        destination = person.data["transit_to"]
        changes: Item = {"remaining_distance": max(0, remaining)}
        if remaining <= 0:
            changes.update(
                location=destination,
                transit_to="",
                waiting_audience=destination == CAPITAL,
            )
        person.record(
            "arrived" if remaining <= 0 else "travelled",
            "",
            {"date": date, **changes},
            changes,
        )
        changed.append(person)
    calendar.record(
        "advanced",
        "",
        {"date": date},
        next_month(date),
    )
    ledger.commit([*changed, calendar])
