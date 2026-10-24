"""Scene-facing material: named people, their own history and the hall, never world truth."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from ming.ledger import Ledger
from ming.middle.calendar import CAPITAL
from ming.middle.night import change_hall
from ming.middle.view import EntityView, Officials, entities, journey, project
from ming.middle.appointments import held_by


class PersonView(BaseModel):
    found: bool
    person: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    appointments: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    accounts: list[EntityView] = Field(default_factory=list[EntityView])


class HallResult(BaseModel):
    ok: bool
    hall: list[str]
    failures: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


PERSON_FIELDS = {
    "name",
    "identity_description",
    "historical_office",
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
    person = next(iter(ledger.entities(kind="person", key=name)), None)
    if person is None:
        return PersonView(found=False)
    data = {k: v for k, v in person["data"].items() if k in PERSON_FIELDS}
    history = ledger.facts(entity_id=person["id"])
    if travel := journey(person["data"], history):
        data["journey"] = travel
    for row in ledger.entities(kind="dossier", key=name):
        data.update(row["data"])
    identity = Officials(people=[name])
    decrees = {e.id: e.data for e in entities(ledger, identity, {"kind": "decree"})}
    events = [
        {
            "kind": e.kind,
            **({"decree": decrees[e.entity_id]} if e.kind == "decreed" else {}),
            **(
                {"decree": decrees[UUID(e.detail["decree_id"])]}
                if e.kind == "endorsed" and UUID(e.detail["decree_id"]) in decrees
                else {}
            ),
            **{
                k: v
                for k, v in e.detail.items()
                if k in {"date", "text", "office", "territory", "holders", "decree_id", "endorser", "form", "source_chat_turn_id"}
            },
        }
        for e in project(ledger, identity, {"entity_id": [person["id"], *decrees]})
    ]
    return PersonView(found=True, person=data, events=events,
                      appointments=[r["data"] for r in held_by(ledger, [name])],
                      accounts=entities(ledger, identity, {"kind": "account"}))


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
