"""The ledger's door: identity reads, event recording, translation and landing."""

import logging
from collections import Counter
from difflib import get_close_matches
from functools import partial
from collections.abc import Callable, Sequence
from pathlib import Path
from shutil import copyfileobj
from typing import Any, TypeVar
from uuid import UUID, uuid4

from pydantic_ai import Agent
from sqlalchemy import JSON, func, literal, select, tuple_
from ming.ledger import (
    ENTITY_COLUMNS as E,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
)
from ming.middle import queries
from ming.middle.appointments import office_pairs, incumbency_record, named

from ming.ledger import Entity, Item, Ledger
from ming.middle.dispatch import dispatch, landing_sources
from ming.middle.fiscal import Accounts, due_levies
from ming.middle.calendar import advance_month, calendar_row, journeys_due, settle_journeys
from ming.middle.declaration import (
    Declaration,
    LandingMode,
    PendingPetition,
    Unhandled,
)
from ming.middle.invoke import ModelSource
from ming.middle.records import TranslationMaterials
from ming.middle.rules import matching_names
from ming.middle.opening import opening_template
from ming.middle.night import NightView, dismiss, known_people, open_night, read_night
from ming.middle.scene import HallResult, set_hall
from ming.middle.translate import declaration_agent, translate
from ming.middle.translate import catalogue as names_and_aliases
from ming.middle.view import (
    EntityView,
    FactView,
    Identity,
    character_input,
    entities,
    FACT_SOURCES,
    identity_key,
    project,
    visible_appointments,
    view_parameters,
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
        calendar = self.calendar()
        for fact in self._ledger.facts(
            entity_id=calendar.id,
            kind="gazette",
            query=FACT_ROWS.order_by(None).order_by(F.position.desc()).limit(1),
        ):
            gazette = fact["detail"]["text"]
        return {
            "date": calendar.data,
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

    def unhandled_monthly(self, current: Item | None = None) -> list[Item]:
        """Last completed month's terminal failures, including the emperor's secrets."""
        current = self.calendar().data if current is None else current
        date = {
            "year": current["year"] - (current["month"] == 1),
            "month": (current["month"] - 2) % 12 + 1,
        }
        return [
            {"entity_id": str(fact["entity_id"])}
            for fact in self._ledger.facts(kind="unhandled", date=date, query=FACT_ROWS.where(
                F.detail["monthly"].as_string().is_not(None),
            ))
        ]

    def fiscal_events(self) -> list[Item]:
        return due_levies(self._ledger)

    def settle_accounts(self) -> None:
        Accounts(self._ledger).run()

    def arrivals_this_month(self) -> list[Item]:
        """Read the already determined arrival dates without landing them early."""
        return [
            {"person": row["key"], "destination": row["data"]["transit_to"], "date": row["data"]["arrival_date"]}
            for row in journeys_due(self._ledger)
        ]

    def settle_journeys(self) -> None:
        settle_journeys(self._ledger)

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
        date: Item | None = None,
    ) -> list[FactView]:
        query = queries.CURRENT_FACTS if current and date is None else FACT_ROWS
        return [
            FactView(**event)
            for event in self._ledger.facts(
                entity_id=entity_id, kind=kind, date=date if current else None, query=query,
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
        self, output_type: type[T], instructions: str,
        *, model: ModelSource | None = None,
    ) -> Agent[TranslationMaterials, T]:
        return declaration_agent(
            self.model if model is None else model, self._ledger, output_type, instructions
        )

    async def translate(
        self, agent: Agent[TranslationMaterials, T], prompt: str, source: UUID
    ) -> T | Unhandled:
        result = await translate(agent, prompt, TranslationMaterials(self, "world", source))
        self.log.info("translation output: %s", result.model_dump_json())
        return result

    def land(
        self,
        result: Declaration | Unhandled,
        source: UUID,
        *,
        monthly: LandingMode | None = None,
    ) -> None:
        dispatch(
            self._ledger, result, source, monthly,
            sources=[(d.id, mode) for d, mode in self.landing_sources()]
            if monthly and source == self.calendar().id else (),
        )

    def record_catalogue(
        self, identity: Identity, date: Item | None = None,
        kind: str | None = None, keys: list[str] | None = None,
    ) -> list[Item]:
        """Names and counts from the existing entity/fact projections, never prose."""
        matches = named(self._ledger, kind, keys) if keys is not None else None
        selection: Item = {"catalogue": True, **({"kind": kind} if kind is not None else {}),
                     **({"keys": [r["key"] for r in matches]} if matches is not None else {})}
        facts: Item = {"entity_id": [r["id"] for r in matches]} if matches is not None else {}
        source = FACT_SOURCES[identity_key(identity)]
        source = source.where(E.kind == kind) if kind is not None else source
        query = source
        visible: set[UUID] = {r["entity_id"] for r in self._ledger.facts(
            **facts, query=query.with_only_columns(F.entity_id).order_by(None).distinct(),
            parameters=view_parameters(identity),
        )} if date is not None and keys is not None else set()
        if date is not None:
            facts["date"] = date
        query = query.with_only_columns(
            F.entity_id, func.count().label("event_count"), maintain_column_froms=True,
        ).order_by(None).group_by(F.entity_id)
        counts = Counter({r["entity_id"]: r["event_count"] for r in self._ledger.facts(
            **facts, query=query, parameters=view_parameters(identity),
        )})
        visible |= counts.keys()
        if date is None or keys is not None:
            visible |= {e.id for e in entities(self._ledger, identity, selection)}
        names = ENTITY_ROWS.with_only_columns(E.id, E.kind, E.key)
        rows = self._ledger.entities(kind=kind, entity_id=list(visible), query=names)
        if date is not None and keys is None and kind is not None and not rows:
            visible = {e.id for e in entities(self._ledger, identity, selection, exists_only=True)}
            if not visible:
                visible = {r["entity_id"] for r in self._ledger.read(
                    source.with_only_columns(F.entity_id).order_by(None).limit(1), view_parameters(identity),
                )}
            rows = self._ledger.entities(kind=kind, entity_id=list(visible), query=names)
        return [{"kind": row["kind"], "key": row["key"], "event_count": counts[row["id"]]} for row in rows]

    def office_record(self, identity: Identity, key: str, date: Item | None = None) -> Item:
        pairs, resolution = office_pairs(self._ledger, key, partial(visible_appointments, self._ledger, identity))
        if resolution["status"] == "territory_required":
            return resolution
        if resolution["status"] == "office_not_found":
            names = self.catalogue([*self.record_catalogue(identity, kind="office"), *self.record_catalogue(identity, kind="territory")])
            prefix = max((label for name, aliases in names.get("territory", {}).items()
                          for label in [name, *aliases] if key.startswith(label)), key=len, default="")
            candidates = matching_names({"office": names.get("office", {})}, [key])
            if not candidates:
                candidates = {"office": {name: names["office"][name] for name in get_close_matches(
                    key[len(prefix):], list(names.get("office", {})), n=len(names.get("office", {})) + 1, cutoff=0.5
                )}}
                if not candidates["office"]:
                    candidates = {}
            return {"status": "office_not_found", "names_and_aliases": candidates}
        office = pairs[0][0]
        record_key, data = incumbency_record(pairs[0], [])
        rows = self._ledger.entities(kind="incumbency", key=record_key)
        visible = visible_appointments(self._ledger, identity, rows)
        if rows and not visible:
            return {"status": "not_found", "message": "未找到"}
        if visible:
            data = visible[0]["data"]
        return {
            "status": "occupied" if data["holders"] else "acting" if data["acting"] else "vacant",
            "appointments": [data],
            "entities": [e.model_dump(mode="json") for e in self.entities(identity, kind="office", key=office)],
            "facts": [f.model_dump(mode="json") for f in self.facts(identity, entity_id=[e["id"] for e in visible], date=date)],
        }

    async def read_records(
        self, identity: Identity, kind: str | None = None,
        key: str | list[str] | None = None, date: Item | None = None,
    ) -> Item:
        """Read the selected identity projection; the frontend retains its full read."""
        keys = list(dict.fromkeys(key)) if isinstance(key, list) else [key] if key is not None else None
        selection = {k: v for k, v in {"kind": kind, "keys": keys}.items() if v is not None}
        rows = entities(self._ledger, identity, selection)
        query = FACT_SOURCES[identity_key(identity)]
        query = query.where(E.kind == kind) if kind is not None else query
        query = query.where(E.key.in_(keys)) if keys is not None else query
        return {
            "entities": [e.model_dump(mode="json") for e in rows],
            "facts": [
                f.model_dump(mode="json")
                for f in project(self._ledger, identity, {"date": date} if date is not None else {}, query)
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
        key: str | list[str] | None = None,
        sourced: bool = False,
    ) -> list[EntityView]:
        selection: Item = {
            k: v for k, v in {"kind": kind, "key": key}.items() if v is not None
        }
        if isinstance(key, list):
            selection["keys"] = selection.pop("key")
        if sourced:
            selection["sourced"] = True
        with self._ledger.reading(replay) as ledger:
            return entities(ledger, identity, selection)

    def entity(self, entity_id: UUID) -> EntityView:
        return EntityView.model_validate(self._ledger.entities(entity_id=entity_id)[0])

    def pending_petitions(self, date: Item | None = None) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.read(queries.pending_petitions(self.calendar().data if date is None else date))
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

    def returned_petitions(self, *, visible: bool = False, date: Item | None = None) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.read(
                queries.returned_petitions((self.calendar().data if date is None else date) if visible else None)
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

    def month_petitions(self) -> list[FactView]:
        return [
            FactView(**f)
            for f in self._ledger.facts(
                kind="petition",
                date=self.calendar().data,
                query=FACT_ROWS.where(
                    F.detail["blocking"].as_boolean().is_(True),
                ),
            )
        ]

    def current_decrees(self, date: Item | None = None) -> list[EntityView]:
        return [
            EntityView.model_validate(e)
            for e in self._ledger.read(
                queries.decrees_with("decreed", self.calendar().data if date is None else date)
            )
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
        readers = known_people(literal(decree.data, type_=JSON)).subquery()
        return {row["person"] for row in self._ledger.read(select(readers.c.person))}

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

    def pending_pushes(self, date: Item | None = None) -> list[tuple[EntityView, Item]]:
        """Prior-month backing without its corresponding durable reconsideration."""
        endorsement = F.position.table.alias("backing").c
        verdict = F.position.table.alias("reconsideration").c
        date = self.calendar().data if date is None else date
        rows = ENTITY_ROWS.add_columns(endorsement.detail.label("backing")).join(
            endorsement.position.table, endorsement.entity_id == E.id,
        ).where(
            E.kind == "decree", endorsement.kind == "endorsed",
            endorsement.detail["decision_key"]["petition_id"].as_string().is_not(None),
            tuple_(endorsement.date["year"].as_integer(), endorsement.date["month"].as_integer())
            < (date["year"], date["month"]),
            ~select(verdict.position).where(
                verdict.entity_id == E.id, verdict.kind == "deliberation",
                verdict.detail["decision_key"] == endorsement.detail["decision_key"],
            ).exists(),
        )
        return [(EntityView.model_validate(row), row["backing"]["decision_key"])
                for row in self._ledger.read(rows)]

    def landing_sources(self, *, include_history: bool = True) -> list[tuple[EntityView, LandingMode | None]]:
        return [(EntityView.model_validate(row), mode)
                for row, mode in landing_sources(self._ledger, self.calendar().data, include_history=include_history)]

    def landing_materials(self, *, include_history: bool = True) -> list[Item]:
        """Monthly materials; translation also needs historical decree pointers."""
        materials: list[Item] = []
        for decree, mode in self.landing_sources(include_history=include_history):
            deliberations = self.products(decree.id, kind=("deliberation", "choice"))
            current = mode is not None or bool(deliberations)
            materials.append({
                "decree": decree.model_dump(mode="json") if current else {
                    "id": str(decree.id), "kind": decree.kind, "key": decree.key,
                    "data": {"secret": False},
                },
                "mode": mode,
                "deliberations": [f.model_dump(mode="json") for f in deliberations],
                "prior_interim": self.prior_interim(decree.id) if current else [],
                **({"known_people": sorted(self.known_people(decree))} if decree.data["secret"] else {}),
            })
        return materials

    def observe(self, on_change: Callable[[], None]) -> None:
        self._ledger.on_commit = on_change

    def close(self) -> None:
        self._ledger.on_commit = None
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
