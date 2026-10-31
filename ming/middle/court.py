"""The ledger's door: identity reads, event recording, translation and landing."""

import logging
from collections.abc import Sequence
from pathlib import Path
from shutil import copyfileobj
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic_ai import Agent

from ming.ledger import (
    ENTITY_COLUMNS as E,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
    Entity, Item, Ledger,
)
from ming.middle import queries
from ming.middle.dispatch import dispatch
from ming.middle.fiscal import Accounts
from ming.middle.calendar import CAPITAL, calendar_row, journeys_due
from ming.middle.declaration import Declaration, LandingMode, Unhandled
from ming.middle.invoke import ModelSource
from ming.middle.records import TranslationMaterials
from ming.middle.reading import Records
from ming.middle.opening import opening_template
from ming.middle.night import INITIAL_HALL, NightView, change_hall, read_nights
from ming.middle.scene import HallResult
from ming.middle.travel import CLEARED_JOURNEY
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
        for row in self._ledger.entities(query=queries.LATEST_NIGHT.with_only_columns(E.id, E.data["closed"].as_boolean().label("closed"))):
            if not row["closed"]:
                return row["id"], False
        date = calendar_row(self._ledger)["data"]
        night = Entity(
            "night", str(uuid4()), "", {"closed": False, "hall": list(INITIAL_HALL), "date": {k: date[k] for k in ("year", "month")}}
        )
        self._ledger.commit([night])
        return night.id, True

    def set_hall(self, night_id: UUID, add: list[str], remove: list[str]) -> HallResult:
        night = self._ledger.get(night_id)
        people = {
            e["key"]: e
            for e in self._ledger.entities(kind="person", query=ENTITY_ROWS.with_only_columns(
                E.id, E.key, E.data["location"].as_string().label("location"),
                E.data["transit_to"].as_string().label("transit_to"),
                E.data["waiting_audience"].as_boolean().label("waiting_audience"),
            ).where(E.key.in_(add)))
        } if add else {}
        failures: list[Item] = []
        for name in add:
            person = people.get(name)
            if (
                person is None
                # ADR 0096: an empty location counts as in the capital (fail-open).
                or (person["location"] or CAPITAL) != CAPITAL
                or person["transit_to"]
            ):
                failures.append({
                    "name": name,
                    "found": person is not None,
                    "location": person["location"] if person else None,
                    "required_location": CAPITAL,
                })
        if failures or night.data["closed"]:
            return HallResult(ok=False, hall=night.data["hall"], failures=failures)
        hall = change_hall(night.data["hall"], add, remove)
        night.record("hall", "", {"add": add, "remove": remove}, {"hall": hall})
        admitted = [
            self._ledger.get(people[name]["id"])
            for name in dict.fromkeys(add)
            if name in hall and people[name]["waiting_audience"]
        ]
        for person in admitted:
            person.record("audience_admitted", "", {"night_id": str(night_id)}, {"waiting_audience": False})
        self._ledger.commit([night, *admitted])
        return HallResult(ok=True, hall=hall)

    def settle_journeys(self, date: Item) -> None:
        changed: list[Entity] = []
        for row in self._ledger.read(journeys_due(date).with_only_columns(E.id)):
            person = self._ledger.get(row["id"])
            destination = person.data["transit_to"]
            changes: Item = {
                **CLEARED_JOURNEY,
                "location": destination,
                "waiting_audience": destination == CAPITAL,
            }
            person.record("arrived", "", {"date": person.data["arrival_date"], **changes}, changes)
            changed.append(person)
        self._ledger.commit(changed)

    def night(self, night_id: UUID) -> NightView:
        return read_nights(self._ledger, self._ledger.entities(entity_id=night_id))[0]

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
                {"kind": "unhandled", "entity_id": str(entity_id)}
                for entity_id in self.read.fact_ids("emperor", "unhandled")
            ],
        }

    def settle_accounts(self, calendar: EntityView) -> None:
        if self.read.has_facts(calendar.id, "month_accounts", date=calendar.data):
            return
        accounts = Accounts(self._ledger)
        accounts.taxes()
        accounts.revenues()
        accounts.production()
        accounts.expenses()
        accounts.calendar.record("month_accounts", "", {"date": accounts.date})
        self._ledger.commit(accounts.rows)

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

    def returned_petitions(self, *, date: Item | None = None) -> tuple[FactView, ...]:
        return tuple(
            FactView(**f)
            for f in self._ledger.read(queries.returned_petitions(date))
        )

    def returned_petition_ids(self, ids: list[str] | None = None) -> set[str]:
        query = queries.returned_petitions().with_only_columns(F.detail["id"].as_string().label("id"))
        if ids is not None:
            query = query.where(F.detail["id"].as_string().in_(ids))
        return {row["id"] for row in self._ledger.read(query)}

    def interactions(self) -> dict[str, Item]:
        return {
            f["detail"]["key"]: f["detail"]
            for f in self._ledger.read(queries.interactions())
        }

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

    def presentation(self, calendar: EntityView, monthly: Item) -> Item:
        interactions = self.interactions()
        pending = next(iter(self.running(interactions)), None)
        month = interactions.get("month")
        if month and month["status"] == "running":
            pending = month
        nights = self.nights()
        night = nights[-1].model_dump(mode="json") if nights else None
        failures = self.failures(interactions=interactions, nights=nights)
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
            **monthly,
        }

    def close(self) -> None:
        self._ledger.close()
        self.log.removeHandler(self._log_handler)
        self._log_handler.close()
