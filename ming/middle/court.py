"""The ledger's one door: new game, continue game, land orders and read by identity."""

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid4

from pydantic_ai.models import Model

from ming.ledger import Entity, Item, Ledger
from ming.middle.dispatch import dispatch
from ming.middle.declaration import (
    Declaration,
    NightDeclaration,
    PendingPetition,
    Petition,
)
from ming.middle.opening import CONTENT, import_opening
from ming.middle.night import NightView, append_turn, dismiss, open_night, read_night
from ming.middle.scene import HallResult, PersonView, read_person, set_hall
from ming.middle.translate import Unhandled, build_agent, translate
from ming.middle.view import EntityView, FactView, Identity, entities, project


class Court:
    def __init__(self, db_path: Path, model: Model) -> None:
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        self.db_path = db_path
        self.locks: defaultdict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.log = logging.getLogger(f"ming.{db_path.stem}")
        self._log_handler = logging.FileHandler(
            db_path.with_suffix(".errors.log"), encoding="utf-8"
        )
        self.log.addHandler(self._log_handler)
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        self._ledger = Ledger(db_path)
        self._night_agent = build_agent(model, self._ledger, NightDeclaration)
        self._month_agent = build_agent(
            model,
            self._ledger,
            Declaration,
            (CONTENT / "prompts/month_translate.md").read_text(),
        )

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
                {"kind": "unhandled", "entity_id": str(f.entity_id)}
                for f in self.facts("emperor")
                if f.kind == "unhandled"
            ],
        }

    async def translate_night(self, night_id: UUID) -> None:
        async with self.locks[night_id]:
            try:
                night = self.night(night_id)
                if not night.closed or night.result is not None:
                    return
                result = await translate(
                    self._night_agent,
                    json.dumps(night.model_dump(mode="json"), ensure_ascii=False),
                )
                self.log.info("night translation: %s", result.model_dump_json())
                dispatch(self._ledger, result, night_id)
            except Exception:
                self.log.exception("translate night=%s", night_id)
                raise

    def calendar(self) -> EntityView:
        return next(e for e in self.entities("audit") if e.kind == "calendar")

    def products(self, entity_id: UUID) -> list[FactView]:
        date = self.calendar().data
        return [
            f
            for f in self.facts("audit")
            if f.entity_id == entity_id and f.detail.get("date") == date
        ]

    def record_product(
        self, entity_id: UUID, kind: str, detail: Item, changes: Item | None = None
    ) -> None:
        entity = self._ledger.get(entity_id)
        entity.record(
            kind,
            "",
            {**detail, "date": self.calendar().data},
            changes,
        )
        self._ledger.commit([entity])

    def world_route(self, *, create: bool = True) -> EntityView | None:
        key = f"world:{self.calendar().data['year']}:{self.calendar().data['month']}"
        for entity in self.entities("audit"):
            if entity.kind == "affair" and entity.key == key:
                return entity
        if not create:
            return None
        entity = Entity("affair", key, "", {"text": "世界局势"})
        self._ledger.commit([entity])
        return next(e for e in self.entities("audit") if e.id == entity.id)

    async def translate_month(
        self, prompt: str, background: bool = False
    ) -> Declaration | Unhandled:
        result = await translate(self._month_agent, prompt, background)
        self.log.info("translation output: %s", result.model_dump_json())
        return result

    def store_declaration(
        self, route_id: UUID, result: Declaration | Unhandled, round_number: int | None
    ) -> None:
        if round_number is None:
            dispatch(self._ledger, result, route_id, monthly=True)
            return
        route = self._ledger.get(route_id)
        changed = {route.id: route}
        existing = {(e.kind, e.key): e for e in self.entities("audit")}
        date = self.calendar().data
        if isinstance(result, Declaration):
            for fact in result.facts:
                for change in fact.changes:
                    if change.field != "petition":
                        continue
                    pair = fact.entity_type, fact.entity
                    row = existing.get(pair)
                    entity = (
                        (changed.get(row.id) or self._ledger.get(row.id))
                        if row
                        else Entity(*pair, "", {})
                    )
                    changed[entity.id] = entity
                    existing[pair] = EntityView.model_validate(entity.snapshot())
                    petition = PendingPetition(
                        **Petition.model_validate(change.value).model_dump(),
                        id=uuid4(),
                        route_id=route_id,
                        entity_id=entity.id,
                        round=round_number,
                    )
                    entity.record(
                        "petition",
                        "",
                        {**petition.model_dump(mode="json"), "date": date},
                    )
        route.record(
            "declaration",
            "",
            {
                "result": result.model_dump(),
                "unhandled": isinstance(result, Unhandled),
                "round": round_number,
                "date": date,
            },
        )
        self._ledger.commit(list(changed.values()))

    def petitions(self) -> list[PendingPetition]:
        facts = self.facts("audit")
        chosen = {f.detail["petition_id"] for f in facts if f.kind == "choice"}
        return [
            PendingPetition.model_validate(
                {k: v for k, v in f.detail.items() if k != "date"}
            )
            for f in facts
            if f.kind == "petition" and f.detail["id"] not in chosen
        ]

    def choose(self, petition_id: UUID, option: int) -> UUID:
        petition = next((p for p in self.petitions() if p.id == petition_id), None)
        if (
            petition is None
            or type(option) is not int
            or not 0 <= option < len(petition.options)
        ):
            raise ValueError("not an unanswered petition option")
        self.record_product(
            petition.route_id,
            "choice",
            {
                "petition_id": str(petition_id),
                "option": option,
                "round": petition.round,
                "text": petition.options[option],
            },
        )
        return petition.route_id

    async def read_records(
        self, identity: Identity, kind: str | None = None, key: str | None = None
    ) -> Item:
        """按类型与正名取本身份材料；空参取全部可读材料，含各衙门呈报的文字。"""
        rows = [
            e
            for e in self.entities(identity)
            if (kind is None or e.kind == kind) and (key is None or e.key == key)
        ]
        # Target resolution is not permission: a hidden physical row can still
        # carry reports this identity is allowed to read.
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

    def interaction(
        self, action: str, status: str, payload: Item | None = None
    ) -> None:
        """Persist a player action/outcome, not a parallel copy of world products."""
        self.record_product(
            self.calendar().id,
            "interaction",
            {
                "action": action,
                "status": status,
                "payload": payload or {},
            },
        )

    def presentation(self) -> Item:
        """The emperor's landing point and records share the identity projection."""
        date = self.calendar().data
        interactions = {
            f.detail["action"]: f.detail
            for f in self.facts("emperor")
            if f.kind == "interaction" and f.detail["date"] == date
        }
        nights = [e for e in self.entities("emperor") if e.kind == "night"]
        night = nights[-1].data if nights else None
        say = interactions.get("say")
        if say and (
            not night
            or night["closed"]
            or (
                say["status"] != "done"
                and say["payload"].get("night_id") != night["id"]
            )
        ):
            interactions.pop("say", None)
        pending = next(
            (item for item in interactions.values() if item["status"] == "running"),
            None,
        )
        failure = next(
            (item for item in interactions.values() if item["status"] == "failed"), None
        )
        world = self.world_route(create=False)
        return {
            "face": "audience"
            if night and not night["closed"]
            else ("month" if world else "desk"),
            "night": night,
            "date": date,
            "running": pending is not None,
            "failure": failure,
            "pending": pending,
            "petitions": [p.model_dump(mode="json") for p in self.petitions()],
        }

    def close(self) -> None:
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
