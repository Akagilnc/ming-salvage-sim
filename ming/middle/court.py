"""The ledger's door: identity reads, event recording, translation and landing."""

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from shutil import copyfileobj
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

from pydantic_ai import Agent
from sqlalchemy import tuple_
from ming.ledger import (
    ENTITY_COLUMNS as E,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
)
from ming.middle import queries
from ming.middle.appointments import held_by

from ming.ledger import Entity, Item, Ledger
from ming.middle.dispatch import dispatch, latest_detail
from ming.middle.fiscal import Accounts, due_levies
from ming.middle.calendar import advance_month, calendar_row
from ming.middle.declaration import (
    Declaration,
    LandingMode,
    PendingPetition,
    Unhandled,
)
from ming.middle.invoke import ModelSource
from ming.middle.records import TranslationMaterials
from ming.middle.opening import opening_template
from ming.middle.night import NightView, dismiss, known_people, open_night, read_night
from ming.middle.scene import HallResult, PersonView, read_person, set_hall
from ming.middle.translate import INSTRUCTIONS, declaration_agent, translate
from ming.middle.translate import catalogue as names_and_aliases
from ming.middle.view import (
    EntityView,
    FactView,
    Identity,
    character_input,
    entities,
    project,
)

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
        cls, directory: Path, model: ModelSource, template: Path | None = None
    ) -> "Court":
        template = template if template is not None else opening_template()
        try:
            source = template.open("rb")
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"{template}: run `python -m ming build-opening` first"
            ) from exc
        with source:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{uuid4()}.sqlite"
            with path.open("xb") as destination:
                copyfileobj(source, destination)
        return cls(path, model)

    def open_night(self) -> UUID:
        return open_night(self._ledger)

    def night(self, night_id: UUID) -> NightView:
        return read_night(self._ledger, night_id)

    def dismiss(self, night_id: UUID) -> None:
        dismiss(self._ledger, night_id)

    def read_person(self, name: str) -> PersonView:
        return read_person(self._ledger, name)

    def appointments(self, name: str) -> list[Item]:
        return [r["data"] for r in held_by(self._ledger, [name])]

    def set_hall(self, night_id: UUID, add: list[str], remove: list[str]) -> HallResult:
        return set_hall(self._ledger, night_id, add, remove)

    def nights(self) -> list[NightView]:
        return [self.night(e["id"]) for e in self._ledger.read(queries.LATEST_NIGHT)]

    def pending_nights(self) -> list[UUID]:
        return [
            e["id"]
            for e in self._ledger.read(
                queries.NIGHT_ROWS.where(
                    E.data["closed"].as_boolean().is_(True),
                    queries.NIGHT_RESULT.is_(None),
                )
            )
        ]

    def scene_material(self) -> dict[str, object]:
        rows = self._ledger.entities(
            kind="person",
            query=ENTITY_ROWS.where(E.data["waiting_audience"].as_boolean().is_(True)),
        )
        gazette = self.entities("audit", kind="gazette")[0].data["text"]
        for fact in self._ledger.facts(
            entity_id=self.calendar().id,
            kind="gazette",
            query=FACT_ROWS.order_by(None).order_by(F.position.desc()).limit(1),
        ):
            gazette = fact["detail"]["text"]
        return {
            "date": self.calendar().data,
            "imperial_prestige": character_input(
                self.entities("audit", kind="world")[0].data
            )["imperial_prestige"],
            "waiting_audience": [row["key"] for row in rows],
            "gazette": gazette,
            "unhandled": [
                {"kind": "unhandled", "entity_id": str(f.entity_id)}
                for f in self.facts("emperor", kind="unhandled")
            ],
        }

    def unhandled_monthly(self) -> list[Item]:
        """Last completed month's terminal failures, including the emperor's secrets."""
        current = self.calendar().data
        date = {
            "year": current["year"] - (current["month"] == 1),
            "month": (current["month"] - 2) % 12 + 1,
        }
        result: list[Item] = []
        for fact in self._ledger.facts(kind="unhandled", date=date, query=FACT_ROWS.where(
            F.detail["monthly"].as_string().is_not(None),
        )):
            source = self._ledger.get(fact["entity_id"])
            result.append({
                "entity_id": str(source.id),
                "kind": "decree" if source.kind == "decree" else "world",
                "text": source.data["text"] if source.kind == "decree" else None,
            })
        return result

    def fiscal_events(self) -> list[Item]:
        return due_levies(self._ledger)

    def settle_accounts(self) -> None:
        Accounts(self._ledger).run()

    def advance_month(self) -> None:
        advance_month(self._ledger)

    def calendar(self) -> EntityView:
        return EntityView.model_validate(calendar_row(self._ledger))

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
            row = next(iter(self._ledger.entities(kind=entity[0], key=entity[1])), None)
            target = self._ledger.get(row["id"]) if row else Entity(*entity, "", {})
        for kind, detail in events:
            target.record(kind, words, detail, changes)
        self._ledger.commit([target])
        return target.id

    def products(
        self,
        entity_id: UUID,
        *,
        current: bool = True,
        kind: str | tuple[str, ...] | None = None,
    ) -> list[FactView]:
        date = self.calendar().data
        return [
            FactView(**event)
            for event in self._ledger.facts(
                entity_id=entity_id, kind=kind, date=date if current else None
            )
        ]

    def prior_interim(self, entity_id: UUID) -> list[Item]:
        return [f.detail for f in self.products(entity_id, current=False, kind="interim")]

    def as_petition(self, fact: FactView) -> PendingPetition:
        return PendingPetition.model_validate(
            {k: v for k, v in fact.detail.items() if k != "date"}
        )

    def deliberation(
        self, entity_id: UUID, decision: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        return next(
            (
                f.detail
                for f in self.products(entity_id, kind="deliberation")
                if f.detail["decision_key"] == decision
            ),
            None,
        )

    def record_product(
        self,
        entity_id: UUID,
        kind: str,
        detail: dict[str, object],
        *,
        petitions: Sequence[PendingPetition] = (),
    ) -> None:
        """Commit a complete product and its petitions in the same transaction."""
        date = self.calendar().data
        targets = {
            key: self._ledger.get(key)
            for key in {entity_id, *(p.entity_id for p in petitions)}
        }
        for petition in petitions:
            targets[petition.entity_id].record(
                "petition", "", {**petition.model_dump(mode="json"), "date": date}
            )
        targets[entity_id].record(kind, "", {**detail, "date": date})
        self._ledger.commit(list(targets.values()))

    def translation_agent(
        self, output_type: type[T], instructions: str = INSTRUCTIONS,
        *, model: ModelSource | None = None,
    ) -> Agent[TranslationMaterials, T]:
        return declaration_agent(
            self.model if model is None else model, self._ledger, output_type, instructions
        )

    async def translate(
        self, agent: Agent[TranslationMaterials, T], prompt: str, source: UUID
    ) -> T | Unhandled:
        result = await translate(agent, prompt, TranslationMaterials(self, "translation", source))
        self.log.info("translation output: %s", result.model_dump_json())
        return result

    def land(
        self,
        result: Declaration | Unhandled,
        source: UUID,
        *,
        monthly: LandingMode | None = None,
        baselines: dict[tuple[str, str, str], Any] | None = None,
    ) -> None:
        dispatch(self._ledger, result, source, monthly, baselines)

    def record_catalogue(self, identity: Identity, date: Item | None = None) -> list[Item]:
        """Names and counts from the existing entity/fact projections, never prose."""
        counts = Counter(f.entity_id for f in self.facts(identity))
        visible = {e.id for e in self.entities(identity)} | counts.keys()
        if date is not None:
            counts = Counter(f.entity_id for f in self.facts(identity, date=date))
        return [
            {
                "kind": row["kind"],
                "key": row["key"],
                "event_count": counts[row["id"]],
            }
            for row in self._ledger.entities(entity_id=list(visible))
        ]

    async def read_records(
        self, identity: Identity, kind: str | None = None,
        key: str | list[str] | None = None, date: Item | None = None,
    ) -> Item:
        """Read the selected identity projection; the frontend retains its full read."""
        keys = list(dict.fromkeys(key)) if isinstance(key, list) else [key]
        rows = [e for name in keys for e in self.entities(identity, kind=kind, key=name)]
        ids = (
            [e.id for name in keys for e in self.entities("audit", kind=kind, key=name)]
            if kind is not None or key is not None
            else []
        )
        return {
            "entities": [e.model_dump(mode="json") for e in rows],
            "facts": [
                f.model_dump(mode="json")
                for f in (
                    self.facts(identity, date=date)
                    if kind is None and key is None
                    else self.facts(identity, entity_id=ids, date=date)
                )
            ],
        }

    def facts(
        self,
        identity: Identity,
        replay: bool = False,
        *,
        entity_id: UUID | list[UUID] | None = None,
        kind: str | tuple[str, ...] | None = None,
        date: Item | None = None,
    ) -> list[FactView]:
        selection = {
            k: v
            for k, v in {"entity_id": entity_id, "kind": kind, "date": date}.items()
            if v is not None
        }
        with self._ledger.reading(replay) as ledger:
            return project(ledger, identity, selection)

    def entities(
        self,
        identity: Identity,
        replay: bool = False,
        *,
        kind: str | None = None,
        key: str | None = None,
        sourced: bool = False,
    ) -> list[EntityView]:
        selection: Item = {
            k: v for k, v in {"kind": kind, "key": key}.items() if v is not None
        }
        if sourced:
            selection["sourced"] = True
        with self._ledger.reading(replay) as ledger:
            return entities(ledger, identity, selection)

    def entity(self, entity_id: UUID) -> EntityView:
        return EntityView.model_validate(self._ledger.entities(entity_id=entity_id)[0])

    def pending_petitions(self) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.read(queries.pending_petitions(self.calendar().data))
        ]

    def petition_officials(self, faction: str | None = None) -> list[EntityView]:
        return [
            EntityView.model_validate(e)
            for e in self._ledger.entities(
                kind="person",
                query=ENTITY_ROWS.where(
                    queries.IN_OFFICE,
                    E.data["faction"].as_string() == faction
                    if faction is not None
                    else queries.CURRENT_APPOINTMENT.where(
                        queries.APPOINTMENT.data["office"].as_string().in_(("内阁首辅", "司礼监掌印太监"))
                    ).exists(),
                ),
            )
        ]

    def catalogue(self, records: list[Item] | None = None) -> dict[str, dict[str, list[str]]]:
        if records is None:
            return names_and_aliases(self._ledger)
        return names_and_aliases(
            self._ledger,
            ENTITY_ROWS.where(
                tuple_(E.kind, E.key).in_([(e["kind"], e["key"]) for e in records])
            ),
        )

    def returned_petitions(self, *, visible: bool = False) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.read(
                queries.returned_petitions(self.calendar().data if visible else None)
            )
        ]

    def interactions(self) -> dict[str, Item]:
        return {
            f["detail"]["key"]: f["detail"]
            for f in self._ledger.read(queries.interactions())
        }

    def petition(self, petition_id: str) -> FactView:
        return FactView(
            **self._ledger.facts(
                kind="petition",
                query=FACT_ROWS.where(F.detail["id"].as_string() == petition_id),
            )[0]
        )

    def petition_products(
        self,
        petition_ids: list[str],
        kind: str | tuple[str, ...],
        *,
        current: bool = False,
    ) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.facts(
                kind=kind,
                date=self.calendar().data if current else None,
                query=FACT_ROWS.where(
                    F.detail["petition_id"].as_string().in_(petition_ids)
                ),
            )
        ]

    def route_petitions(self, route: UUID) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.facts(
                kind="petition",
                date=self.calendar().data,
                query=FACT_ROWS.where(
                    F.detail["route_id"].as_string() == str(route),
                    F.detail["blocking"].as_boolean().is_(True),
                ),
            )
        ]

    def current_decrees(self) -> list[EntityView]:
        return [
            EntityView.model_validate(e)
            for e in self._ledger.read(
                queries.decrees_with("decreed", self.calendar().data)
            )
        ]

    def due_decrees(self) -> list[EntityView]:
        return [
            EntityView.model_validate(e)
            for e in self._ledger.read(queries.due_decrees(self.calendar().data))
        ]

    def secret_decrees(self) -> list[EntityView]:
        return [
            EntityView.model_validate(e)
            for e in self._ledger.read(queries.SECRET_DECREES)
        ]

    def errands(self) -> list[EntityView]:
        return [
            EntityView.model_validate(e)
            for e in self._ledger.read(queries.errands(self.calendar().data))
        ]

    def known_people(self, decree: EntityView) -> set[str]:
        return known_people(self._ledger, decree.model_dump())

    def consequences(self, decree: UUID) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.facts(
                query=FACT_ROWS.where(
                    F.detail["origin_ref"].as_string() == str(decree)
                ),
                kind=("changed", "received", "reported", "unhandled"),
                date=self.calendar().data,
            )
        ]

    def landing_sources(self) -> list[tuple[EntityView, UUID, LandingMode]]:
        # A secret errand lands each month until done: in its decree month from
        # its night's simulation, afterwards from the world's.
        calendar = self.calendar()
        current = {d.id for d in self.current_decrees()}
        sources: list[tuple[EntityView, UUID, LandingMode]] = [
            (d, UUID(d.data["night_id"]) if d.id in current else calendar.id, "landed")
            for d in self.errands()
        ]
        for row in self._ledger.read(
            queries.decrees_with("deliberation", self.calendar().data)
        ):
            decree = EntityView.model_validate(row)
            products = self.products(decree.id, kind=("deliberation", "choice"))
            events = [(f.kind, f.detail) for f in products]
            verdict = cast(Item, latest_detail(events, "deliberation"))
            choice = latest_detail(events, "choice")
            if verdict["verdict"] == "准" or (choice and choice["text"] == "强颁"):
                sources.append((decree, UUID(verdict["route_id"]), "landed"))
            elif decree.data.get("interim"):
                sources.append((decree, UUID(verdict["route_id"]), "attempted"))
        # Completion order is entities.rowid, the order ENTITY_ROWS already uses.
        order = {
            row["id"]: index
            for index, row in enumerate(self._ledger.entities(kind="decree"))
        }
        sources.sort(key=lambda item: order[item[0].id])
        return sources + [(calendar, calendar.id, "landed")]

    def observe(self, on_change: Callable[[], None]) -> None:
        self._ledger.on_commit = on_change

    def close(self) -> None:
        self._ledger.on_commit = None
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
