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
        self.court.record_product(
            petition.entity_id,
            "choice",
            {
                "petition_id": str(petition_id),
                "option": option,
                "text": petition.options[option],
            },
        )
