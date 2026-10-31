"""Source-blind petition inbox: only petitions and emperor choices."""

from typing import Any
from uuid import UUID

from ming.middle.court import Court


class Inbox:
    def __init__(self, court: Court) -> None:
        self.court = court

    def choose(self, petition: dict[str, Any] | None, option: int, date: dict[str, Any]) -> None:
        if (
            petition is None
            or type(option) is not int
            or not 0 <= option < len(petition["options"])
        ):
            raise ValueError("not a petition option")
        entity_id = UUID(petition["entity_id"])
        decision = {"petition_id": petition["id"], "option": option}
        events = [("choice", {**decision, "text": petition["options"][option], "date": date})]
        changes = None
        if petition["source"] == "deliberation" and petition["options"][option] == "御笔强推":
            endorsement = {"endorser": "御笔", "form": "御笔手敕", "decision_key": decision}
            events.append(("endorsed", {**endorsement, "date": date}))
            changes = {"endorsements": [*self.court.read.entities("audit", ids=[entity_id])[0].data.get("endorsements", []), endorsement]}
        self.court.record(entity_id, events, changes)
