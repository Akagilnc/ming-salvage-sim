"""Month-owned product assembly; the middle layer commits supplied facts only."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from ming.middle.court import Court, Entity
from ming.month_steps.materials import PendingPetition
from ming.middle.view import FactView


def record_product(
    court: Court, entity_id: UUID, kind: str, detail: dict[str, Any], *,
    petitions: Sequence[PendingPetition] = (),
) -> Entity:
    return court.record(entity_id, [(kind, detail)], related=[
        FactView(entity_id=p.entity_id, kind="petition", emperor_words="",
                 detail={**p.model_dump(mode="json"), "date": detail["date"]})
        for p in petitions
    ])
