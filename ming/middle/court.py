"""The ledger's door: identity reads, event recording, translation and landing."""

import logging
from functools import partial
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from shutil import copyfileobj
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic_ai import Agent
from sqlalchemy import JSON, func, or_, select, tuple_
from ming.ledger import (
    ENTITY_COLUMNS as E,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    ENTITY_ORDER,
    FACT_ROWS,
    facts_in_month,
)
from ming.middle import queries
from ming.middle.appointments import ALIASES, office_pairs, incumbency_record, named

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
from ming.middle.rules import matching_offices
from ming.middle.opening import opening_template
from ming.middle.night import NightView, dismiss, known_people, open_night, read_nights
from ming.middle.scene import HallResult, set_hall
from ming.middle.translate import declaration_agent, translate
from ming.middle.translate import catalogue as names_and_aliases
from ming.middle.view import (
    EntityView,
    FactView,
    Identity,
    character_input,
    entities,
    fact_sources,
    ENTITY_SOURCES,
    identity_key,
    month_open,
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

    def open_night(self) -> tuple[UUID, bool]:
        return open_night(self._ledger)

    def night(self, night_id: UUID) -> NightView:
        return read_nights(self._ledger, self._ledger.entities(entity_id=night_id))[0]

    def dismiss(self, night_id: UUID) -> None:
        dismiss(self._ledger, night_id)

    def set_hall(self, night_id: UUID, add: list[str], remove: list[str]) -> HallResult:
        return set_hall(self._ledger, night_id, add, remove)

    def nights(self) -> tuple[NightView, ...]:
        return read_nights(self._ledger, self._ledger.read(queries.LATEST_NIGHT))

    def pending_nights(self) -> tuple[UUID, ...]:
        return tuple(
            e["id"]
            for e in self._ledger.read(
                queries.NIGHT_ROWS.with_only_columns(E.id).where(
                    E.data["closed"].as_boolean().is_(True),
                    queries.NIGHT_RESULT.is_(None),
                )
            )
        )

    def scene_material(self) -> dict[str, object]:
        rows = self._ledger.entities(
            kind="person",
            query=ENTITY_ROWS.with_only_columns(E.key).where(E.data["waiting_audience"].as_boolean().is_(True)),
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
                {"kind": "unhandled", "entity_id": str(row["entity_id"])}
                for row in self._ledger.read(fact_sources(self._ledger, "emperor", cutoff=month_open(calendar.data))
                                             .with_only_columns(F.entity_id).where(F.kind == "unhandled"))
            ],
        }

    def unhandled_monthly(self, current: Item) -> list[Item]:
        """Last completed month's terminal failures, including the emperor's secrets."""
        date = {
            "year": current["year"] - (current["month"] == 1),
            "month": (current["month"] - 2) % 12 + 1,
        }
        return [
            {"entity_id": str(fact["entity_id"])}
            for fact in self._ledger.facts(kind="unhandled", date=date, query=FACT_ROWS.with_only_columns(F.entity_id).where(
                F.detail["monthly"].as_string().is_not(None),
            ))
        ]

    def fiscal_events(self, date: Item) -> list[Item]:
        return due_levies(self._ledger, date)

    def settle_accounts(self) -> None:
        Accounts(self._ledger).run()

    def arrivals_this_month(self, date: Item) -> list[Item]:
        """Read the already determined arrival dates without landing them early."""
        return [
            {"person": row["key"], "destination": row["data"]["transit_to"], "date": row["data"]["arrival_date"]}
            for row in journeys_due(self._ledger, date)
        ]

    def settle_journeys(self, date: Item) -> None:
        settle_journeys(self._ledger, date)

    def advance_month(self, calendar_id: UUID) -> None:
        advance_month(self._ledger, calendar_id)

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
            row = next(iter(self._ledger.entities(kind=entity[0], key=entity[1], query=ENTITY_ROWS.with_only_columns(E.id))), None)
            target = self._ledger.get(row["id"]) if row else Entity(*entity, "", {})
        for kind, detail in events:
            target.record(kind, words, detail, changes)
        self._ledger.commit([target])
        return target.id

    def products(
        self,
        entity_id: UUID,
        *,
        kind: str | tuple[str, ...] | None = None,
        date: Item | None,
    ) -> tuple[FactView, ...]:
        return tuple(
            FactView(**event)
            for event in self._ledger.facts(
                entity_id=entity_id, kind=kind,
                date=date,
            )
        )

    def has_product(self, entity_id: UUID, kind: str | tuple[str, ...], *, date: Item | None) -> bool:
        return bool(self._ledger.facts(
            entity_id=entity_id, kind=kind, date=date,
            query=FACT_ROWS.with_only_columns(F.position).order_by(None).limit(1),
        ))

    def as_petition(self, fact: FactView) -> PendingPetition:
        return PendingPetition.model_validate(
            {k: v for k, v in fact.detail.items() if k != "date"}
        )

    def record_product(
        self,
        entity_id: UUID,
        kind: str,
        detail: dict[str, object],
        *,
        petitions: Sequence[PendingPetition] = (),
        date: Item | None = None,
    ) -> None:
        """Commit a complete product and its petitions in the same transaction."""
        targets = {
            key: self._ledger.get(key)
            for key in {entity_id, *(p.entity_id for p in petitions)}
        }
        source = targets[entity_id]
        if date is None:
            date = source.data if source.kind == "calendar" else self.calendar().data
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
        dispatch(self._ledger, result, source, monthly)

    def record_catalogue(
        self, identity: Identity, date: Item | None = None,
        kind: str | None = None, keys: list[str] | None = None,
    ) -> tuple[Item, ...]:
        """Names and counts from the existing entity/fact projections, never prose."""
        matches = named(self._ledger, kind, keys) if keys is not None else None
        cutoff = month_open(calendar_row(self._ledger)["data"]) if identity == "emperor" else None
        source = fact_sources(self._ledger, identity, cutoff=cutoff)
        visible = ENTITY_SOURCES[identity_key(identity)].with_only_columns(E.id).order_by(None)
        if cutoff is not None:
            opening = FACT_ROWS.with_only_columns(F.detail["entities"]).where(
                F.position == cutoff,
            ).order_by(None).scalar_subquery()
            snapshot = func.json_each(opening).table_valued("value")
            visible = select(E.id).where(or_(
                E.id.in_(select(func.replace(func.json_extract(snapshot.c.value, "$.id"), "-", ""))),
                cutoff.is_(None) & E.id.in_(visible.correlate(None)),
            ))
        if kind is not None:
            source, visible = source.where(E.kind == kind), visible.where(E.kind == kind)
        if matches is not None:
            source = source.where(F.entity_id.in_([r["id"] for r in matches]))
            visible = visible.where(E.id.in_([r["id"] for r in matches]))
        query = source
        if date is not None:
            query = query.where(facts_in_month(date))
        counts = query.with_only_columns(
            F.entity_id, func.count().label("event_count"), maintain_column_froms=True,
        ).order_by(None).group_by(F.entity_id).subquery()
        visible_entities = visible.order_by(None).distinct().subquery()
        eligible = or_(visible_entities.c.id.is_not(None), (
            counts.c.entity_id.is_not(None) if date is None else E.id.in_(
                source.with_only_columns(F.entity_id).order_by(None).limit(None if keys is not None else 1).correlate(None),
            )
        ))
        names = ENTITY_ROWS.outerjoin(counts, counts.c.entity_id == E.id).outerjoin(
            visible_entities, visible_entities.c.id == E.id,
        ).with_only_columns(
            E.kind, E.key, func.coalesce(counts.c.event_count, 0).label("event_count"),
        )
        parameters = view_parameters(identity, kind)
        result = self._ledger.read(
            names.where(eligible if date is None or keys is not None else counts.c.entity_id.is_not(None)),
            parameters,
        )
        if date is not None and keys is None and kind is not None and not result:
            result = self._ledger.read(
                names.where(eligible).order_by(None).order_by(visible_entities.c.id.is_(None), ENTITY_ORDER).limit(1),
                parameters,
            )
        return result

    def office_record(self, identity: Identity, key: str | list[str], date: Item | None = None) -> Item:
        results: dict[str, Item] = {}
        resolved: dict[tuple[str, str], Item] = {}
        offices: dict[str, list[Item]] = {}
        names: dict[str, dict[str, list[str]]] | None = None
        for name in dict.fromkeys([key] if isinstance(key, str) else key):
            pairs, resolution = office_pairs(self._ledger, name, partial(visible_appointments, self._ledger, identity))
            if resolution["status"] == "territory_required":
                results[name] = resolution
            elif resolution["status"] == "office_not_found":
                if names is None:
                    names = self.catalogue([*self.record_catalogue(identity, kind="office"), *self.record_catalogue(identity, kind="territory")])
                results[name] = {"status": "office_not_found", "names_and_aliases": matching_offices(names, name)}
            else:
                if pairs[0] in resolved:
                    results[name] = resolved[pairs[0]]
                    continue
                record_key, data = incumbency_record(pairs[0], [])
                rows = self._ledger.entities(kind="incumbency", key=record_key)
                visible = visible_appointments(self._ledger, identity, rows)
                if rows and not visible:
                    results[name] = resolved[pairs[0]] = {"status": "not_found", "message": "未找到"}
                    continue
                if visible:
                    data = visible[0]["data"]
                if pairs[0][0] not in offices:
                    offices[pairs[0][0]] = [e.model_dump(mode="json") for e in self.entities(identity, kind="office", key=pairs[0][0])]
                results[name] = resolved[pairs[0]] = {
                    "status": "occupied" if data["holders"] else "acting" if data["acting"] else "vacant",
                    "appointments": [data],
                    "entities": offices[pairs[0][0]],
                    "facts": [f.model_dump(mode="json") for f in self.facts(identity, entity_id=[e["id"] for e in visible], date=date)],
                }
        return results[key] if isinstance(key, str) else results[key[0]] if len(key) == 1 else {"offices": [results[name] for name in key]}

    def read_records(
        self, identity: Identity, kind: str | None = None,
        key: str | list[str] | None = None, date: Item | None = None,
        *, replay: bool = False,
    ) -> Item:
        """Read one identity projection, sharing one reconstruction for --replay."""
        keys = list(dict.fromkeys(key)) if isinstance(key, list) else [key] if key is not None else None
        selection = {k: v for k, v in {"kind": kind, "keys": keys}.items() if v is not None}
        with self._ledger.reading(replay) as ledger:
            cutoff = month_open(calendar_row(ledger)["data"]) if identity == "emperor" else None
            query = fact_sources(ledger, identity, cutoff=cutoff)
            query = query.where(E.kind == kind) if kind is not None else query
            query = query.where(E.key.in_(keys)) if keys is not None else query
            return {
                "entities": [e.model_dump(mode="json") for e in entities(ledger, identity, selection, cutoff=cutoff)],
                "facts": [
                    f.model_dump(mode="json")
                    for f in project(ledger, identity, {"date": date} if date is not None else {}, query)
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
    ) -> tuple[FactView, ...]:
        if entity_id == []:
            return ()
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
        current: Item | None = None,
    ) -> tuple[EntityView, ...]:
        selection: Item = {
            k: v for k, v in {"kind": kind, "key": key}.items() if v is not None
        }
        if isinstance(key, list):
            selection["keys"] = selection.pop("key")
        with self._ledger.reading(replay) as ledger:
            return entities(ledger, identity, selection, cutoff=month_open(current) if identity == "emperor" and current is not None else None)

    def entity(self, entity_id: UUID) -> EntityView:
        return EntityView.model_validate(self._ledger.entities(entity_id=entity_id)[0])

    def pending_petitions(self, date: Item) -> tuple[PendingPetition, ...]:
        return tuple(
            self.as_petition(FactView(**f))
            for f in self._ledger.read(queries.pending_petitions(date))
        )

    def has_pending_petitions(self, date: Item) -> bool:
        return bool(self._ledger.read(queries.pending_petitions(date)
                                      .with_only_columns(F.position).order_by(None).limit(1)))

    def petition_officials(self, faction: str | None = None) -> tuple[str, ...]:
        return tuple(
            e["key"]
            for e in self._ledger.entities(
                kind="person",
                query=ENTITY_ROWS.with_only_columns(E.key).where(
                    queries.IN_OFFICE,
                    E.data["faction"].as_string() == faction
                    if faction is not None
                    else queries.CURRENT_APPOINTMENT.where(
                        queries.APPOINTMENT.data["office"].as_string().in_(("内阁首辅", "司礼监掌印太监"))
                    ).exists(),
                ),
            )
        )

    def catalogue(self, records: Sequence[Item] | None = None) -> dict[str, dict[str, list[str]]]:
        query = queries.CATALOGUE if records is None else ENTITY_ROWS.where(
            tuple_(E.kind, E.key).in_([(e["kind"], e["key"]) for e in records])
        )
        return names_and_aliases(self._ledger.read(query.with_only_columns(E.kind, E.key, ALIASES)))

    def returned_petitions(self, *, date: Item | None = None) -> tuple[FactView, ...]:
        return tuple(
            FactView(**f)
            for f in self._ledger.read(queries.returned_petitions(date))
        )

    def returned_petition_ids(self) -> set[str]:
        return {row["id"] for row in self._ledger.read(queries.returned_petitions().with_only_columns(
            F.detail["id"].as_string().label("id"),
        ))}

    def interactions(self) -> dict[str, Item]:
        return {
            f["detail"]["key"]: f["detail"]
            for f in self._ledger.read(queries.interactions())
        }

    def prior_choices(self, date: Item) -> list[Item]:
        petition = F.position.table.alias("chosen_petition").c
        rows = FACT_ROWS.with_only_columns(F.detail.label("choice"), petition.detail.label("petition")).join(
            petition.position.table, petition.detail["id"].as_string() == F.detail["petition_id"].as_string(),
        ).where(petition.kind == "petition", petition.detail["source"].as_string().in_(("urgent", "impeachment")),
                F.detail["petition_id"].as_string().not_in(queries.returned_petitions().with_only_columns(
                    F.detail["id"].as_string(),
                ).order_by(None).correlate(None)))
        return [{**row["choice"], "petition": row["petition"]} for row in self._ledger.facts(kind="choice", date=date, query=rows)]

    def petition_products(
        self,
        petition_ids: list[str],
        kind: str | tuple[str, ...],
        *,
        date: Item | None,
    ) -> tuple[FactView, ...]:
        if not petition_ids:
            return ()
        return tuple(
            FactView(**f)
            for f in self._ledger.facts(
                kind=kind,
                date=date,
                query=FACT_ROWS.where(
                    F.detail["petition_id"].as_string().in_(petition_ids)
                ),
            )
        )

    def month_petitions(self, date: Item, *, single_pending: bool = False) -> tuple[FactView, ...]:
        query = FACT_ROWS.where(F.kind == "petition", facts_in_month(date),
                               F.detail["blocking"].as_boolean().is_(True))
        if single_pending:
            query = query.where(
                query.with_only_columns(func.count()).order_by(None).correlate(None).scalar_subquery() == 1,
                F.position.in_(queries.pending_petitions({}).with_only_columns(F.position).order_by(None)),
            )
        return tuple(FactView(**row) for row in self._ledger.read(query))

    def current_decrees(self, date: Item) -> tuple[EntityView, ...]:
        return tuple(
            EntityView.model_validate(e)
            for e in self._ledger.entities(
                query=queries.decrees_with("decreed", date)
            )
        )

    def errands(self, date: Item) -> tuple[EntityView, ...]:
        return tuple(
            EntityView.model_validate(e)
            for e in self._ledger.entities(query=queries.errands(date))
        )

    def consequences(self, decree: UUID, date: Item) -> tuple[FactView, ...]:
        return tuple(
            FactView(**f)
            for f in self._ledger.facts(
                query=FACT_ROWS.where(
                    F.detail["origin_ref"].as_string() == str(decree)
                ),
                kind=("changed", "received", "reported", "unhandled"),
                date=date,
            )
        )

    def pending_pushes(self, date: Item) -> tuple[tuple[EntityView, Item], ...]:
        """Prior-month backing without its corresponding durable reconsideration."""
        endorsement = F.position.table.alias("backing").c
        verdict = F.position.table.alias("reconsideration").c
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
        return tuple((EntityView.model_validate(row), row["backing"]["decision_key"])
                     for row in self._ledger.read(rows))

    def landing_materials(self, *, include_history: bool = True, date: Item) -> tuple[Item, ...]:
        """Monthly materials; translation also needs historical decree pointers."""
        materials: list[Item] = []
        sources = landing_sources(self._ledger, date, include_history=include_history)
        readers = known_people(E.data).subquery()
        secret_ids = [row["id"] for row, _mode, _events in sources if row["data"]["secret"]]
        known = {row["id"]: sorted(row["people"]) for row in self._ledger.read(select(
            E.id, select(func.json_group_array(readers.c.person, type_=JSON)).scalar_subquery().label("people"),
        ).where(E.id.in_(secret_ids)))} if secret_ids else {}
        prior: dict[UUID, list[Item]] = defaultdict(list)
        if current_ids := [row["id"] for row, mode, events in sources if mode is not None or events]:
            for event in self._ledger.facts(entity_id=current_ids, kind="interim"):
                prior[event["entity_id"]].append(event["detail"])
        for row, mode, events in sources:
            decree = EntityView.model_validate(row)
            deliberations = [FactView(**event) for event in events]
            current = mode is not None or bool(deliberations)
            materials.append({
                "decree": decree.model_dump(mode="json") if current else {
                    "id": str(decree.id), "kind": decree.kind, "key": decree.key,
                    "data": {"secret": False},
                },
                "mode": mode,
                "deliberations": [f.model_dump(mode="json") for f in deliberations],
                "prior_interim": prior[decree.id] if current else [],
                **({"known_people": known[decree.id]} if decree.data["secret"] else {}),
            })
        return tuple(materials)

    def failures(
        self, *, interactions: dict[str, Item] | None = None,
        nights: tuple[NightView, ...] | None = None,
    ) -> tuple[Item, ...]:
        interactions = self.interactions() if interactions is None else interactions
        failed: list[Item] = []
        for item in interactions.values():
            if item["status"] != "failed":
                continue
            if item["action"] == "say":
                latest = ([(nights[-1].id, nights[-1].closed)] if nights else []) if nights is not None else [
                    (row["id"], row["closed"]) for row in self._ledger.read(queries.LATEST_NIGHT.with_only_columns(
                        E.id, E.data["closed"].as_boolean().label("closed"),
                    ))
                ]
                if not latest or latest[0][1] or item["payload"]["night_id"] != str(latest[0][0]):
                    continue
            failed.append(item)
        return tuple(failed)

    def running(self, interactions: dict[str, Item] | None = None) -> tuple[Item, ...]:
        interactions = self.interactions() if interactions is None else interactions
        return tuple(
            i
            for i in interactions.values()
            if i["status"] == "running" and i["action"] != "translation"
        )

    def presentation(self, calendar: EntityView | None = None) -> Item:
        calendar = self.calendar() if calendar is None else calendar
        interactions = self.interactions()
        pending = next(iter(self.running(interactions)), None)
        month = interactions.get("month")
        if month and month["status"] == "running":
            pending = month
        nights = self.nights()
        night = nights[-1].model_dump(mode="json") if nights else None
        failures = self.failures(interactions=interactions, nights=nights)
        returned = self.returned_petitions(date=calendar.data)
        awaiting_drafter = bool(returned) and not self.petition_officials()
        # The translation-to-month exception must not bypass another failed action.
        failure = next(
            (i for i in failures if i["action"] != "translation"),
            next(iter(failures), None),
        )
        return {
            "face": "audience"
            if night and not night["closed"]
            else (
                "month"
                if self.has_product(calendar.id, "month_open", date=calendar.data)
                or (month and month["status"] != "done")
                else "desk"
            ),
            "night": night,
            "date": calendar.data,
            "running": pending is not None and failure is None,
            "failure": failure,
            "pending": pending,
            "unhandled_monthly": self.unhandled_monthly(calendar.data),
            "petitions": [p.model_dump(mode="json") for p in self.pending_petitions(calendar.data)],
            "returned_petitions": [
                {"petition": f.detail, "awaiting_drafter": awaiting_drafter}
                for f in returned
            ],
        }

    def close(self) -> None:
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
