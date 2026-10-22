"""Source-blind petition inbox: only petitions and emperor choices."""

from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition


class Inbox:
    def __init__(self, court: Court) -> None:
        self.court = court

    def petitions(self) -> list[PendingPetition]:
        facts = self.court.facts("audit")
        chosen = {f.detail["petition_id"] for f in facts if f.kind == "choice"}
        date = self.court.calendar().data
        return [
            PendingPetition.model_validate(
                {k: v for k, v in f.detail.items() if k != "date"}
            )
            for f in facts
            if f.kind == "petition"
            and f.detail["id"] not in chosen
            and (f.detail["available"]["year"], f.detail["available"]["month"])
            <= (date["year"], date["month"])
        ]

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
