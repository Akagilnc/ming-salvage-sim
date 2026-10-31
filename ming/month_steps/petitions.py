"""Fixed petition options and their recorded dispositions belong to Month."""

from typing import Any
from uuid import UUID

from ming.middle.court import Court
from ming.middle.view import EntityView
from ming.month_steps.materials import pending_petitions


DELIBERATION_OPTIONS = {
    "forced": "强颁", "withdrawn": "收回", "held": "留中", "endorsed": "御笔强推",
}
URGENT_OPTIONS = {"returned": "发回改票"}


def deliberation_options(decree: EntityView, verdict: dict[str, Any]) -> list[str]:
    dispositions = (["forced"] if verdict["verdict"] == "驳" else []) + ["withdrawn", "held"]
    if verdict["verdict"] == "驳" and not decree.data.get("endorsements"):
        dispositions.append("endorsed")
    return [DELIBERATION_OPTIONS[disposition] for disposition in dispositions]


def urgent_options(proposed: list[str]) -> list[str]:
    return [*proposed, *URGENT_OPTIONS.values()]


class Inbox:
    def __init__(self, court: Court) -> None:
        self.court = court

    def choose(self, payload: dict[str, Any], *, accept: bool = False) -> None:
        petition_id, option, date = payload["petition"], payload["option"], payload["date"]
        petition = next(iter(pending_petitions(self.court, petition_id)), None)
        petition = petition.model_dump(mode="json") if petition else None
        if petition is None or not 0 <= option < len(petition["options"]):
            raise ValueError("not a petition option")
        if accept:
            return
        entity_id = UUID(petition["entity_id"])
        decision = {"petition_id": petition["id"], "option": option}
        text = petition["options"][option]
        disposition = None
        if petition["source"] == "urgent":
            offset: int = option - (len(petition["options"]) - len(URGENT_OPTIONS))
            if offset >= 0:
                disposition = list(URGENT_OPTIONS)[offset]
        elif petition["source"] == "deliberation":
            disposition = next((key for key, label in DELIBERATION_OPTIONS.items() if label == text), None)
        events = [("choice", {**decision, "text": text, "date": date, "disposition": disposition})]
        changes = None
        if disposition == "endorsed":
            endorsement = {"endorser": "御笔", "form": "御笔手敕", "decision_key": decision}
            events.append(("endorsed", {**endorsement, "date": date}))
            changes = {"endorsements": [*self.court.read.entities("audit", ids=[entity_id])[0].data.get("endorsements", []), endorsement]}
        self.court.record(entity_id, events, changes)
