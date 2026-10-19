"""The ledger's one door: new game, continue game, land orders and read by identity."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from pydantic_ai.models import Model

from ming.ledger import Ledger
from ming.middle.dispatch import dispatch
from ming.middle.declaration import NightDeclaration
from ming.middle.opening import CONTENT, import_opening
from ming.middle.night import NightView, append_turn, dismiss, open_night, read_night
from ming.middle.scene import HallResult, PersonView, read_person, set_hall
from ming.middle.translate import build_agent, translate
from ming.middle.view import EntityView, FactView, Identity, entities, project


class Court:
    def __init__(self, db_path: Path, model: Model) -> None:
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        self.db_path = db_path
        self._ledger = Ledger(db_path)
        self._night_agent = build_agent(model, self._ledger, NightDeclaration)

    @classmethod
    def new_game(
        cls, directory: Path, model: Model, content: Path = CONTENT
    ) -> "Court":
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4()}.sqlite"
        path.touch(exist_ok=False)
        court = cls(path, model)
        try:
            import_opening(court._ledger, content)
        except Exception:
            court.close()
            raise
        return court

    def open_night(self) -> UUID:
        return open_night(self._ledger)

    def night(self, night_id: UUID) -> NightView:
        return read_night(self._ledger, night_id)

    def dismiss(self, night_id: UUID) -> None:
        dismiss(self._ledger, night_id)

    def append_turn(self, night_id: UUID, words: str, scene: str) -> str:
        return append_turn(self._ledger, night_id, words, scene)

    def read_person(self, name: str) -> PersonView:
        return read_person(self._ledger, name)

    def set_hall(self, night_id: UUID, add: list[str], remove: list[str]) -> HallResult:
        return set_hall(self._ledger, night_id, add, remove)

    def nights(self) -> list[NightView]:
        return [self.night(e.id) for e in self.entities("audit") if e.kind == "night"]

    def pending_nights(self) -> list[UUID]:
        return [n.id for n in self.nights() if n.closed and n.result is None]

    def decrees(self, night_id: UUID) -> list[EntityView]:
        return [
            e
            for e in self.approved_decrees()
            if e.data.get("night_id") == str(night_id)
        ]

    def approved_decrees(self) -> list[EntityView]:
        return [e for e in self.entities("audit") if e.kind == "decree"]

    def scene_material(self) -> dict[str, object]:
        rows = self.entities("audit")
        calendar = next(e for e in rows if e.kind == "calendar")
        gazette = next(e.data["text"] for e in rows if e.kind == "gazette")
        for fact in self.facts("audit"):
            if fact.entity_id == calendar.id and fact.kind == "gazette":
                gazette = fact.detail["text"]
        return {
            "date": {k: calendar.data[k] for k in ("year", "month")},
            "gazette": gazette,
            "unhandled": [
                {"kind": "unhandled", "night_id": str(n.id)}
                for n in self.nights()
                if n.result == "unhandled"
            ],
        }

    async def translate_night(self, night_id: UUID) -> None:
        night = self.night(night_id)
        if not night.closed or night.result is not None:
            return
        result = await translate(
            self._night_agent,
            json.dumps(night.model_dump(mode="json"), ensure_ascii=False),
        )
        dispatch(self._ledger, result, night_id)

    def facts(self, identity: Identity, replay: bool = False) -> list[FactView]:
        return project(self._ledger, identity, replay)

    def entities(self, identity: Identity, replay: bool = False) -> list[EntityView]:
        return entities(self._ledger, identity, replay)

    def close(self) -> None:
        self._ledger.close()
