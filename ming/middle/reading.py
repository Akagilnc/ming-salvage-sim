"""Complete identity reads: resolution, visibility, opening view and projection."""

from collections import defaultdict
from collections.abc import Callable, Generator, Iterable, Sequence
from functools import partial
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Select, func, select

from ming.ledger import (
    ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS,
    FACT_ROWS, Item, Ledger,
)
from ming.middle import queries
from ming.middle.appointments import ALIASES, catalogue as names_and_aliases, office_pairs, incumbency_record
from ming.middle.calendar import calendar_row, journeys_due
from ming.middle.declaration import LandingMode
from ming.middle.night import known_people
from ming.middle.rules import matching_offices
from ming.middle.record_pages import RecordCursor, RecordScope
from ming.middle.record_queries import RecordQuery
from ming.middle.view import (
    EntityView, FactView, Identity, VISIBLE_IDS, MONTH_OPEN_QUERY,
    entities, fact_sources, identity_key, project_facts, visible_appointments,
    view_parameters,
)


def latest_detail(events: Sequence[Item], kind: str) -> Item | None:
    """Latest deliberation or choice of this month, the row both landing and interim use."""
    return next(
        (event["detail"] for event in reversed(events) if event["kind"] == kind),
        None,
    )


class Records:
    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def _opening(self, identity: Identity, *, snapshot: bool = False) -> Item | None:
        if identity != "emperor":
            return None
        query = MONTH_OPEN_QUERY.where(F.date == E.data)
        if snapshot:
            query = query.add_columns(F.detail)
        return next(iter(self._ledger.read(query)), None)

    def _sources(self, identity: Identity, *, snapshot: bool = False) -> tuple[Select[Any], Item | None]:
        opening = self._opening(identity, snapshot=snapshot)
        return fact_sources(identity, cutoff=opening["position"] if opening else None), opening

    def opening_snapshot(self) -> tuple[EntityView, ...] | None:
        """Capture the emperor's entities only if no current opening exists; never write."""
        if self._opening("emperor") is not None:
            return None
        return tuple(entities(self._ledger, "emperor"))

    def calendar(self) -> EntityView:
        return EntityView.model_validate(calendar_row(self._ledger))

    def catalogue(self) -> dict[str, dict[str, list[str]]]:
        return names_and_aliases(self._ledger.read(queries.CATALOGUE.with_only_columns(E.kind, E.key, ALIASES)))

    def office_names(self, identity: Identity) -> Select[Any]:
        return ENTITY_ROWS.with_only_columns(E.kind, E.key, ALIASES).where(
            E.kind.in_(("office", "territory")), E.id.in_(VISIBLE_IDS[identity_key(identity)]),
        ).params(**view_parameters(identity, "office"))

    def office_record(self, identity: Identity, key: str | list[str]) -> Item:
        records = list(self.office_records(identity, [key] if isinstance(key, str) else key))
        return records[0] if isinstance(key, str) or len(key) == 1 else {"offices": records}

    def office_records(
        self, identity: Identity, keys: list[str], *, office_view: Callable[[str], Iterable[EntityView]] | None = None,
    ) -> Generator[Item]:
        """Resolve lazily, sharing appointment and office projections within one request."""
        results: dict[str, Item] = {}
        resolved: dict[tuple[str, str], Item] = {}
        offices: dict[str, list[Item]] = {}
        names: dict[str, dict[str, list[str]]] | None = None
        for name in keys:
            if name not in results:
                pairs, resolution = office_pairs(self._ledger, name, partial(visible_appointments, self._ledger, identity))
                if resolution["status"] == "territory_required":
                    results[name] = resolution
                elif resolution["status"] == "office_not_found":
                    if names is None:
                        names = names_and_aliases(self._ledger.read(self.office_names(identity)))
                    results[name] = {"status": "office_not_found", "names_and_aliases": matching_offices(names, name)}
                elif pairs[0] in resolved:
                    results[name] = resolved[pairs[0]]
                else:
                    record_key, data = incumbency_record(pairs[0], [])
                    rows = self._ledger.entities(kind="incumbency", key=record_key)
                    visible = visible_appointments(self._ledger, identity, rows)
                    if rows and not visible:
                        results[name] = resolved[pairs[0]] = {"status": "not_found", "message": "未找到"}
                    else:
                        data = visible[0]["data"] if visible else data
                        results[name] = resolved[pairs[0]] = {
                            "status": "occupied" if data["holders"] else "acting" if data["acting"] else "vacant",
                            "appointments": [{**data, "entity_id": str(visible[0]["id"]) if visible else None}],
                            "entities": [], "facts": [],
                        }
            if "appointments" in results[name]:
                office = results[name]["appointments"][0]["office"]
                if office not in offices:
                    offices[office] = [e.model_dump(mode="json") for e in (
                        self.entities(identity, kind="office", key=office) if office_view is None else office_view(office)
                    )]
                results[name]["entities"] = offices[office]
            yield results[name]

    def query(
        self, identity: Identity, kind: str | None = None,
        key: str | list[str] | None = None, date: Item | None = None,
        *, options: tuple[RecordScope, bool] | None = None,
    ) -> Item:
        """The model query contract, independent of Agent transport and deps."""
        scope, numeric = options or (RecordScope(), False)
        cursor = (scope.read or RecordCursor()).model_copy(update=scope.after.model_dump(exclude_unset=True) if scope.after else {})
        return RecordQuery(self, self._ledger, identity, self._sources(identity), numeric=numeric).run(
            kind, key, date, scope=scope, cursor=cursor,
        )

    def read_records(
        self, identity: Identity, kind: str | None = None,
        key: str | list[str] | None = None, date: Item | None = None,
        *, replay: bool = False,
    ) -> Item:
        """Full material shares one opening read and, for replay, one reconstruction."""
        keys = list(dict.fromkeys(key)) if isinstance(key, list) else [key] if key is not None else None
        selection = {k: v for k, v in {"kind": kind, "keys": keys, "date": date}.items() if v is not None}
        with self._ledger.reading(replay) as ledger:
            reader = Records(ledger)
            return reader._material(identity, selection)

    def _material(self, identity: Identity, selection: Item) -> Item:
        query, opening = self._sources(identity, snapshot=True)
        query = query.where(E.kind == selection["kind"]) if "kind" in selection else query
        query = query.where(E.key.in_(selection["keys"])) if "keys" in selection else query
        return {
            "entities": [e.model_dump(mode="json") for e in entities(
                self._ledger, identity, {k: v for k, v in selection.items() if k != "date"}, opening=opening,
            )],
            "facts": [fact.model_dump(mode="json") for fact in project_facts(self._ledger, identity, {"date": selection.get("date")}, query)],
        }

    def facts(
        self, identity: Identity, *,
        entity_id: UUID | list[UUID] | None = None,
        kind: str | tuple[str, ...] | None = None, date: Item | None = None,
        detail: Item | None = None,
    ) -> tuple[FactView, ...]:
        if entity_id == [] or any(value == [] for value in (detail or {}).values()):
            return ()
        query, _ = self._sources(identity)
        query = query.where(*queries.matching_details(F.detail, detail or {}))
        return project_facts(self._ledger, identity, {"entity_id": entity_id, "kind": kind, "date": date}, query)

    def has_facts(
        self, entity_id: UUID, kind: str | tuple[str, ...], *, date: Item | None,
        detail: Item | None = None,
    ) -> bool:
        return bool(self._ledger.facts(
            entity_id=entity_id, kind=kind, date=date,
            query=FACT_ROWS.with_only_columns(F.position).where(
                *queries.matching_details(F.detail, detail or {}),
            ).order_by(None).limit(1),
        ))

    def entities(
        self, identity: Identity, *,
        kind: str | None = None, key: str | list[str] | None = None,
        ids: list[UUID] | None = None,
    ) -> tuple[EntityView, ...]:
        if ids == []:
            return ()
        selection: Item = {k: v for k, v in {"kind": kind, "keys" if isinstance(key, list) else "key": key, "ids": ids}.items() if v is not None}
        return tuple(entities(self._ledger, identity, selection, opening=self._opening(identity, snapshot=True)))

    def _unmatched_query(self, identity: Identity, kind: str, response: str, link: tuple[str, str]) -> Select[Any]:
        return fact_sources(identity).where(queries.unmatched(kind, response, link))

    def unmatched(
        self, identity: Identity, kind: str, response: str, link: tuple[str, str],
        *, detail: Item | None = None,
    ) -> tuple[FactView, ...]:
        """Facts whose reference has no matching response, ordered by event position."""
        query = self._unmatched_query(identity, kind, response, link).where(
            *queries.matching_details(F.detail, detail or {}),
        ).order_by(None).order_by(F.position)
        return project_facts(self._ledger, identity, {}, query)

    def has_unmatched(self, identity: Identity, kind: str, response: str, link: tuple[str, str]) -> bool:
        query = self._unmatched_query(identity, kind, response, link)
        return bool(self._ledger.read(query.with_only_columns(F.position).order_by(None).limit(1), view_parameters(identity)))

    def related_details(
        self, kind: str, related: str, link: tuple[str, str], *, date: Item, detail: Item,
    ) -> tuple[tuple[Item, Item], ...]:
        """Audit details joined by their recorded references, bounded before loading."""
        other = F.position.table.alias("related").c
        query = FACT_ROWS.with_only_columns(F.detail, other.detail.label("related")).join(
            other.position.table, F.detail[link[0]].as_string() == other.detail[link[1]].as_string(),
        ).where(other.kind == related, *queries.matching_details(other.detail, detail))
        return tuple((row["detail"], row["related"]) for row in self._ledger.facts(kind=kind, date=date, query=query))

    def without_events(self, kind: str, data: Item, event: str, date: Item) -> tuple[EntityView, ...]:
        """Audit rows without the specified event outside the supplied month."""
        query = queries.without_events(kind, data, event, date)
        return tuple(EntityView.model_validate(row) for row in self._ledger.read(query))

    def fact_ids(
        self, identity: Identity, kind: str, *, date: Item | None = None,
        has: str | None = None,
    ) -> tuple[UUID, ...]:
        query, _ = self._sources(identity)
        query = query.with_only_columns(F.entity_id)
        if has is not None:
            query = query.where(F.detail[has].as_string().is_not(None))
        return tuple(row["entity_id"] for row in self._ledger.facts(kind=kind, date=date, query=query, parameters=view_parameters(identity)))

    def journeys_due(self, date: Item) -> tuple[Item, ...]:
        return self._ledger.read(journeys_due(date).with_only_columns(
            E.key.label("person"), E.data["transit_to"].as_string().label("destination"), E.data["arrival_date"].label("date"),
        ))

    def public_decrees(self, date: Item) -> tuple[EntityView, ...]:
        """Public decrees issued this month; secret ones never take deliberation."""
        query = queries.decrees_with("decreed", date).where(E.data["secret"].as_boolean().is_(False))
        return tuple(EntityView.model_validate(row) for row in self._ledger.read(query))

    def levies_due(self, date: Item) -> list[Item]:
        due = self._ledger.entities(kind="historical_event", query=ENTITY_ROWS.where(
            E.data["category"].as_string() == "fiscal_levy",
            E.data["trigger_year"].as_integer() == date["year"],
            E.data["trigger_month"].as_integer() == date["month"],
            E.data["terminal_reason"].as_string().is_(None),
        ))
        gates = {subject.split(".")[1] for row in due for subject in row["data"]["trigger_gate"]}
        endings = {row["id"]: row["reason"] for row in self._ledger.entities(kind="historical_event", query=ENTITY_ROWS.with_only_columns(
            E.data["id"].as_string().label("id"), E.data["terminal_reason"].as_string().label("reason"),
        ).where(E.data["id"].as_string().in_(gates)))} if gates else {}
        return [
            {"entity": row["key"], "data": row["data"]} for row in due
            if all(endings[subject.split(".")[1]] == required.removeprefix("==")
                   for subject, required in row["data"]["trigger_gate"].items())
        ]

    def landing_sources(
        self, date: Item, *, include_history: bool = True,
    ) -> list[tuple[Item, LandingMode | None, list[Item], bool]]:
        """Ordered sources with decisions and the interim consequence resolved once."""
        records = self._ledger.entities(query=queries.landing_rows(date, include_history=include_history))
        if not records:
            return []
        decisions: dict[UUID, list[Item]] = defaultdict(list)
        for event in self._ledger.facts(entity_id=[row["id"] for row in records], kind=("deliberation", "choice"), date=date):
            decisions[event["entity_id"]].append(event)
        sources: list[tuple[Item, LandingMode | None, list[Item], bool]] = []
        for row in records:
            mode: LandingMode | None = "landed" if row.pop("errand") else None
            events = decisions[row["id"]]
            choice = latest_detail(events, "choice")
            forced = choice is not None and choice["disposition"] == "forced"
            if row.pop("deliberated"):
                verdict = latest_detail(events, "deliberation")
                mode = None
                if verdict and (verdict["verdict"] == "准" or forced):
                    mode = "landed"
                elif row["data"].get("interim"):
                    mode = "attempted"
            sources.append((row, mode, events, bool(row["data"].get("interim") or forced)))
        return sources

    def known_people(self, ids: list[UUID]) -> dict[UUID, list[str]]:
        readers = known_people(E.data).subquery()
        return {row["id"]: sorted(row["people"]) for row in self._ledger.read(select(
            E.id, select(func.json_group_array(readers.c.person, type_=JSON)).scalar_subquery().label("people"),
        ).where(E.id.in_(ids)))} if ids else {}

    def office_holders(self, offices: tuple[str, ...] | None = None) -> tuple[Item, ...]:
        query = ENTITY_ROWS.with_only_columns(E.key).where(E.kind == "person")
        if offices is not None:
            query = query.where(queries.CURRENT_APPOINTMENT.where(
                queries.APPOINTMENT.data["office"].as_string().in_(offices),
            ).exists())
        else:
            query = query.add_columns(E.data["faction"].as_string().label("faction")).where(queries.IN_OFFICE)
        return self._ledger.read(query)
