"""The ledger's door: identity reads, event recording, translation and landing."""

import logging
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from shutil import copyfileobj
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic_ai import Agent
from sqlalchemy import JSON, func, select, tuple_
from ming.ledger import (
    ENTITY_COLUMNS as E,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
    facts_in_month,
    Entity, Item, Ledger,
)
from ming.middle import queries
from ming.middle.dispatch import dispatch, landing_sources
from ming.middle.fiscal import Accounts, due_levies
from ming.middle.calendar import advance_month, journeys_due, settle_journeys
from ming.middle.declaration import Declaration, LandingMode, Unhandled
from ming.middle.invoke import ModelSource
from ming.middle.records import TranslationMaterials
from ming.middle.reading import Records
from ming.middle.opening import opening_template
from ming.middle.night import NightView, dismiss, known_people, open_night, read_nights
from ming.middle.scene import HallResult, set_hall
from ming.middle.translate import declaration_agent, translate
from ming.middle.view import EntityView, FactView, character_input

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
        self.read = Records(self._ledger)

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
        gazette = self.read.entities("audit", kind="gazette")[0].data["text"]
        calendar = self.read.calendar()
        for fact in self._ledger.facts(
            entity_id=calendar.id,
            kind="gazette",
            query=FACT_ROWS.order_by(None).order_by(F.position.desc()).limit(1),
        ):
            gazette = fact["detail"]["text"]
        return {
            "date": calendar.data,
            "imperial_prestige": character_input(
                self.read.entities("audit", kind="world")[0].data
            )["imperial_prestige"],
            "waiting_audience": [row["key"] for row in rows],
            "gazette": gazette,
            "unhandled": [
                {"kind": "unhandled", "entity_id": str(fact.entity_id)}
                for fact in self.read.facts("emperor", kind="unhandled")
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

    def record(
        self,
        entity: UUID | tuple[str, str],
        events: list[tuple[str, Item]],
        changes: Item | None = None,
        *,
        words: str = "",
        related: Sequence[FactView] = (),
    ) -> UUID:
        """Commit all supplied events together, including related entities."""
        if isinstance(entity, UUID):
            target = self._ledger.get(entity)
        else:
            row = next(iter(self._ledger.entities(kind=entity[0], key=entity[1], query=ENTITY_ROWS.with_only_columns(E.id))), None)
            target = self._ledger.get(row["id"]) if row else Entity(*entity, "", {})
        targets = {target.id: target}
        for fact in related:
            if fact.entity_id not in targets:
                targets[fact.entity_id] = self._ledger.get(fact.entity_id)
            targets[fact.entity_id].record(fact.kind, fact.emperor_words, fact.detail)
        for kind, detail in events:
            target.record(kind, words, detail, changes)
        self._ledger.commit(list(targets.values()))
        return target.id

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

    def pending_petitions(self, date: Item) -> tuple[FactView, ...]:
        return tuple(FactView(**f) for f in self._ledger.read(queries.pending_petitions(date)))

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

    def month_petitions(self, date: Item) -> tuple[FactView, ...]:
        query = FACT_ROWS.where(F.kind == "petition", facts_in_month(date),
                               F.detail["blocking"].as_boolean().is_(True))
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
        calendar = self.read.calendar() if calendar is None else calendar
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
                if self.read.has_facts(calendar.id, "month_open", date=calendar.data)
                or (month and month["status"] != "done")
                else "desk"
            ),
            "night": night,
            "date": calendar.data,
            "running": pending is not None and failure is None,
            "failure": failure,
            "pending": pending,
            "unhandled_monthly": self.unhandled_monthly(calendar.data),
            "petitions": [{k: v for k, v in f.detail.items() if k != "date"} for f in self.pending_petitions(calendar.data)],
            "returned_petitions": [
                {"petition": f.detail, "awaiting_drafter": awaiting_drafter}
                for f in returned
            ],
        }

    def close(self) -> None:
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
