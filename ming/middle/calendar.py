"""Monthly person movement settles before reports; the calendar advances last."""

from ming.ledger import Entity, Item, Ledger, read_once
from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS
from ming.middle.travel import CLEARED_JOURNEY


CAPITAL = "北直隶 / 京师"


def next_month(date: Item) -> Item:
    return {
        "year": date["year"] + (date["month"] == 12),
        "month": date["month"] % 12 + 1,
    }


@read_once
def calendar_row(ledger: Ledger) -> Item:
    return ledger.entities(kind="calendar")[0]


@read_once
def journeys_due(ledger: Ledger) -> tuple[Item, ...]:
    """Stored journeys due this month, shared by the draft read and settlement."""
    date = calendar_row(ledger)["data"]
    return ledger.entities(
        kind="person", query=ENTITY_ROWS.where(
            E.data["transit_to"].as_string() != "",
            E.data["arrival_date"]["year"].as_integer() == date["year"],
            E.data["arrival_date"]["month"].as_integer() == date["month"],
        )
    )


def settle_journeys(ledger: Ledger) -> None:
    changed: list[Entity] = []
    for row in journeys_due(ledger):
        person = ledger.get(row["id"])
        destination = person.data["transit_to"]
        changes: Item = {
            **CLEARED_JOURNEY,
            "location": destination,
            "waiting_audience": destination == CAPITAL,
        }
        person.record("arrived", "", {"date": person.data["arrival_date"], **changes}, changes)
        changed.append(person)
    ledger.commit(changed)


def advance_month(ledger: Ledger) -> None:
    calendar = ledger.get(calendar_row(ledger)["id"])
    date = dict(calendar.data)
    calendar.record(
        "advanced",
        "",
        {"date": date},
        next_month(date),
    )
    ledger.commit([calendar])
