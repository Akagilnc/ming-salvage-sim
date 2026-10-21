"""The ledger's door: identity reads, event recording, translation and landing."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic_ai import Agent

from ming.ledger import Entity, Item, Ledger
from ming.middle.dispatch import dispatch
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.invoke import ModelSource
from ming.middle.opening import CONTENT, import_opening
from ming.middle.night import NightView, dismiss, open_night, read_night
from ming.middle.scene import HallResult, PersonView, read_person, set_hall
from ming.middle.translate import INSTRUCTIONS, declaration_agent, translate
from ming.middle.view import EntityView, FactView, Identity, entities, project

T = TypeVar("T", bound=Declaration)


class Court:
    def __init__(self, db_path: Path, model: ModelSource) -> None:
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        self.db_path = db_path
        self.model = model
        self.error_path = db_path.with_suffix(".errors.log")
        self.log = logging.getLogger(f"ming.{db_path.stem}")
        self._log_handler = logging.FileHandler(self.error_path, encoding="utf-8")
        self.log.addHandler(self._log_handler)
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        self._ledger = Ledger(db_path)

    @classmethod
    def new_game(
        cls, directory: Path, model: ModelSource, content: Path = CONTENT
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

    def read_person(self, name: str) -> PersonView:
        return read_person(self._ledger, name)

    def set_hall(self, night_id: UUID, add: list[str], remove: list[str]) -> HallResult:
        return set_hall(self._ledger, night_id, add, remove)

    def nights(self) -> list[NightView]:
        return [self.night(e.id) for e in self.entities("audit") if e.kind == "night"]

    def pending_nights(self) -> list[UUID]:
        return [n.id for n in self.nights() if n.closed and n.result is None]

    def scene_material(self) -> dict[str, object]:
        rows = self.entities("audit")
        gazette = next(e.data["text"] for e in rows if e.kind == "gazette")
        for fact in self.facts("audit"):
            if fact.entity_id == self.calendar().id and fact.kind == "gazette":
                gazette = fact.detail["text"]
        return {
            "date": self.calendar().data,
            "gazette": gazette,
            "unhandled": [
                {"kind": "unhandled", "entity_id": str(f.entity_id)}
                for f in self.facts("emperor")
                if f.kind == "unhandled"
            ],
        }

    def calendar(self) -> EntityView:
        return next(e for e in self.entities("audit") if e.kind == "calendar")

    def record(
        self,
        entity: UUID | tuple[str, str],
        events: list[tuple[str, Item]],
        changes: Item | None = None,
        *,
        words: str = "",
    ) -> UUID:
        """Record an event on an existing entity or an explicitly named new one."""
        if isinstance(entity, UUID):
            target = self._ledger.get(entity)
        else:
            row = next(
                (e for e in self.entities("audit") if (e.kind, e.key) == entity), None
            )
            target = self._ledger.get(row.id) if row else Entity(*entity, "", {})
        for kind, detail in events:
            target.record(kind, words, detail, changes)
        self._ledger.commit([target])
        return target.id

    def translation_agent(
        self, output_type: type[T], instructions: str = INSTRUCTIONS
    ) -> Agent[None, T]:
        return declaration_agent(self.model, self._ledger, output_type, instructions)

    async def translate(self, agent: Agent[None, T], prompt: str) -> T | Unhandled:
        result = await translate(agent, prompt)
        self.log.info("translation output: %s", result.model_dump_json())
        return result

    def land(
        self, result: Declaration | Unhandled, source: UUID, *, monthly: bool = False
    ) -> None:
        dispatch(self._ledger, result, source, monthly)

    async def read_records(
        self, identity: Identity, kind: str | None = None, key: str | None = None
    ) -> Item:
        """按类型与正名取本身份材料；空参取全部可读材料，含各衙门呈报的文字。"""
        rows = [
            e
            for e in self.entities(identity)
            if (kind is None or e.kind == kind) and (key is None or e.key == key)
        ]
        ids = {
            e.id
            for e in self.entities("audit")
            if (kind is None or e.kind == kind) and (key is None or e.key == key)
        }
        return {
            "entities": [e.model_dump(mode="json") for e in rows],
            "facts": [
                f.model_dump(mode="json")
                for f in self.facts(identity)
                if (kind is None and key is None) or f.entity_id in ids
            ],
        }

    def facts(self, identity: Identity, replay: bool = False) -> list[FactView]:
        return project(self._ledger, identity, replay)

    def entities(self, identity: Identity, replay: bool = False) -> list[EntityView]:
        return entities(self._ledger, identity, replay)

    def observe(self, on_change: Callable[[], None]) -> None:
        self._ledger.on_commit = on_change

    def close(self) -> None:
        self._ledger.on_commit = None
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
