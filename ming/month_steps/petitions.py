"""Source-blind petition inbox: only petitions and emperor choices."""

from typing import Any
from uuid import UUID

from ming.middle.court import Court


class Inbox:
    def __init__(self, court: Court) -> None:
        self.court = court

    def choose(self, payload: dict[str, Any], *, accept: bool = False) -> None:
        petition_id, option, date = payload["petition"], payload["option"], payload["date"]
        petition = next(iter(self.court.pending_petitions(date, petition_id)), None)
        petition = petition.model_dump(mode="json") if petition else None
        if (
            petition is None
            or type(option) is not int
            or not 0 <= option < len(petition["options"])
        ):
            raise ValueError("not a petition option")
        if accept:
            return
        entity_id = UUID(petition["entity_id"])
        decision = {"petition_id": petition["id"], "option": option}
        events = [("choice", {**decision, "text": petition["options"][option], "date": date})]
        changes = None
        if petition["source"] == "deliberation" and petition["options"][option] == "御笔强推":
            endorsement = {"endorser": "御笔", "form": "御笔手敕", "decision_key": decision}
            events.append(("endorsed", {**endorsement, "date": date}))
            changes = {"endorsements": [*self.court.entity(entity_id).data.get("endorsements", []), endorsement]}
        self.court.record(entity_id, events, changes)
