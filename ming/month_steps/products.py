"""Month-owned product assembly; the middle layer commits supplied facts only."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.view import FactView


def as_petition(fact: FactView) -> PendingPetition:
    return PendingPetition.model_validate({k: v for k, v in fact.detail.items() if k != "date"})


def record_product(
    court: Court, entity_id: UUID, kind: str, detail: dict[str, Any], *,
    petitions: Sequence[PendingPetition] = (),
) -> None:
    court.record(entity_id, [(kind, detail)], related=[
        FactView(entity_id=p.entity_id, kind="petition", emperor_words="",
                 detail={**p.model_dump(mode="json"), "date": detail["date"]})
        for p in petitions
    ])
