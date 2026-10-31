"""Deterministic arrival settlement against stored journey dates."""

from typing import Any

from sqlalchemy import Select

from ming.ledger import Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS


CAPITAL = "北直隶 / 京师"


def calendar_row(ledger: Ledger) -> Item:
    return ledger.entities(kind="calendar")[0]


def journeys_due(date: Item) -> Select[Any]:
    """Stored journeys due this month, shared by the draft read and settlement."""
    return ENTITY_ROWS.where(
        E.kind == "person",
        E.data["transit_to"].as_string() != "",
        E.data["arrival_date"]["year"].as_integer() == date["year"],
        E.data["arrival_date"]["month"].as_integer() == date["month"],
    )
