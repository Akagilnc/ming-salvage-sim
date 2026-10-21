"""Scene-facing material: named people, their own history and the hall, never world truth."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from ming.ledger import Ledger
from ming.middle.calendar import CAPITAL


class PersonView(BaseModel):
    found: bool
    person: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class HallResult(BaseModel):
    ok: bool
    hall: list[str]
    failures: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


PERSON_FIELDS = {
    "name",
    "office",
    "office_type",
    "office_region",
    "location",
    "status",
    "faction",
    "personal_skills",
    "style",
    "status_reason",
    "transit_to",
    "waiting_audience",
}


def read_person(ledger: Ledger, name: str) -> PersonView:
    rows = ledger.entities()
    person = next((e for e in rows if e["kind"] == "person" and e["key"] == name), None)
    if person is None:
        return PersonView(found=False)
    data = {k: v for k, v in person["data"].items() if k in PERSON_FIELDS}
    for row in rows:
        if row["kind"] == "dossier" and row["key"] == name:
            data.update(row["data"])
    decrees = {
        str(e["id"]): {
            k: v for k, v in e["data"].items() if k in {"text", "origin", "people"}
        }
        for e in rows
        if e["kind"] == "decree"
    }
    events = [
        {
            "kind": e["kind"],
            **(
                {"decree": decrees[e["detail"]["decree_id"]]}
                if e["kind"] == "decreed"
                else {}
            ),
            **{
                k: v
                for k, v in e["detail"].items()
                if k in {"date", "text", "decree_id", "successor"}
            },
        }
        for e in person["events"]
    ]
    return PersonView(found=True, person=data, events=events)


def set_hall(
    ledger: Ledger, night_id: UUID, add: list[str], remove: list[str]
) -> HallResult:
    night = ledger.get(night_id)
    people = {e["key"]: e for e in ledger.entities() if e["kind"] == "person"}
    failures: list[dict[str, Any]] = []
    for name in add:
        person = people.get(name)
        if (
            person is None
            or person["data"].get("location") != CAPITAL
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
    hall = list(dict.fromkeys(p for p in night.data["hall"] + add if p not in remove))
    night.record("hall", "", {"add": add, "remove": remove}, {"hall": hall})
    admitted = [
        ledger.get(people[name]["id"])
        for name in add
        if people[name]["data"].get("waiting_audience")
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
