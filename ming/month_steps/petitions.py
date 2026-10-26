"""Source-blind petition inbox: only petitions and emperor choices."""

from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition


class Inbox:
    def __init__(self, court: Court) -> None:
        self.court = court

    def petitions(self) -> list[PendingPetition]:
        return [self.court.as_petition(f) for f in self.court.pending_petitions()]

    def choose(self, petition_id: UUID, option: int) -> None:
        petition = next((p for p in self.petitions() if p.id == petition_id), None)
        if (
            petition is None
            or type(option) is not int
            or not 0 <= option < len(petition.options)
        ):
            raise ValueError("not a petition option")
        date = self.court.calendar().data
        decision = {"petition_id": str(petition_id), "option": option}
        events = [("choice", {**decision, "text": petition.options[option], "date": date})]
        changes = None
        if petition.source == "deliberation" and petition.options[option] == "御笔强推":
            endorsement = {"endorser": "御笔", "form": "御笔手敕", "decision_key": decision}
            events.append(("endorsed", {**endorsement, "date": date}))
            changes = {"endorsements": [*self.court.entity(petition.entity_id).data.get("endorsements", []), endorsement]}
        self.court.record(petition.entity_id, events, changes)
