"""The physical hall boundary; all model material comes from the record projection."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from ming.ledger import Ledger
from ming.middle.calendar import CAPITAL
from ming.middle.night import change_hall


class HallResult(BaseModel):
    ok: bool
    hall: list[str]
    failures: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


def set_hall(
    ledger: Ledger, night_id: UUID, add: list[str], remove: list[str]
) -> HallResult:
    night = ledger.get(night_id)
    people = {
        e["key"]: e
        for name in dict.fromkeys(add)
        for e in ledger.entities(kind="person", key=name)
    }
    failures: list[dict[str, Any]] = []
    for name in add:
        person = people.get(name)
        if (
            person is None
            # ADR 0096: an empty location counts as in the capital (fail-open).
            or (person["data"].get("location") or CAPITAL) != CAPITAL
            or person["data"].get("transit_to")
        ):
            failures.append(
                {
                    "name": name,
                    "found": person is not None,
                    "location": person["data"].get("location") if person else None,
                    "required_location": CAPITAL,
                }
            )
    if failures or night.data["closed"]:
        return HallResult(ok=False, hall=night.data["hall"], failures=failures)
    hall = change_hall(night.data["hall"], add, remove)
    night.record("hall", "", {"add": add, "remove": remove}, {"hall": hall})
    admitted = [
        ledger.get(people[name]["id"])
        for name in dict.fromkeys(add)
        if name in hall and people[name]["data"].get("waiting_audience")
    ]
    for person in admitted:
        person.record(
            "audience_admitted",
            "",
            {"night_id": str(night_id)},
            {"waiting_audience": False},
        )
    ledger.commit([night, *admitted])
    return HallResult(ok=True, hall=hall)
