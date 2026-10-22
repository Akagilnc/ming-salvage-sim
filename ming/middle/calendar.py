"""Monthly person movement and calendar advance share one ledger transaction."""

from ming.ledger import Entity, Item, Ledger


CAPITAL = "北直隶 / 京师"


def advance_month(ledger: Ledger) -> None:
    rows = ledger.entities()
    calendar = ledger.get(next(r["id"] for r in rows if r["kind"] == "calendar"))
    date = dict(calendar.data)
    changed: list[Entity] = []
    for row in rows:
        if row["kind"] != "person" or not row["data"].get("transit_to"):
            continue
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
        {
            "year": date["year"] + (date["month"] == 12),
            "month": date["month"] % 12 + 1,
        },
    )
    ledger.commit([*changed, calendar])
