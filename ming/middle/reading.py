"""Complete identity reads: resolution, visibility, opening view and projection."""

from collections import defaultdict
from collections.abc import Sequence
from functools import partial
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Select, func, or_, select, tuple_

from ming.ledger import (
    ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, ENTITY_ORDER,
    FACT_ROWS, Item, Ledger, facts_in_month,
)
from ming.middle import queries
from ming.middle.appointments import ALIASES, catalogue as names_and_aliases, office_pairs, incumbency_record, named
from ming.middle.calendar import calendar_row, journeys_due
from ming.middle.declaration import LandingMode
from ming.middle.night import known_people
from ming.middle.rules import matching_names, matching_offices
from ming.middle.view import (
    EntityView, FactView, Identity, VISIBLE_IDS, MONTH_OPEN_QUERY,
    character_input, entities, fact_sources, identity_key, project, visible_appointments,
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
        return entities(self._ledger, "emperor")

    def calendar(self) -> EntityView:
        return EntityView.model_validate(calendar_row(self._ledger))

    def record_catalogue(
        self, identity: Identity, date: Item | None = None, kind: str | None = None,
    ) -> tuple[Item, ...]:
        source = fact_sources(identity)
        visible = VISIBLE_IDS[identity_key(identity)]
        if kind is not None:
            source, visible = source.where(E.kind == kind), visible.where(E.kind == kind)
        query = source.where(facts_in_month(date)) if date is not None else source
        counts = query.with_only_columns(
            F.entity_id, func.count().label("event_count"), maintain_column_froms=True,
        ).order_by(None).group_by(F.entity_id).subquery()
        visible_entities = visible.order_by(None).distinct().subquery()
        eligible = or_(visible_entities.c.id.is_not(None), (
            counts.c.entity_id.is_not(None) if date is None else E.id.in_(
                source.with_only_columns(F.entity_id).order_by(None).limit(1).correlate(None),
            )
        ))
        names = ENTITY_ROWS.outerjoin(counts, counts.c.entity_id == E.id).outerjoin(
            visible_entities, visible_entities.c.id == E.id,
        ).with_only_columns(
            E.kind, E.key, func.coalesce(counts.c.event_count, 0).label("event_count"),
        )
        parameters = view_parameters(identity, kind)
        result = self._ledger.read(
            names.where(eligible if date is None else counts.c.entity_id.is_not(None)), parameters,
        )
        if date is not None and kind is not None and not result:
            result = self._ledger.read(
                names.where(eligible).order_by(None).order_by(visible_entities.c.id.is_(None), ENTITY_ORDER).limit(1),
                parameters,
            )
        return result

    def catalogue(self, records: Sequence[Item] | None = None) -> dict[str, dict[str, list[str]]]:
        query = queries.CATALOGUE if records is None else ENTITY_ROWS.where(
            tuple_(E.kind, E.key).in_([(e["kind"], e["key"]) for e in records])
        )
        return names_and_aliases(self._ledger.read(query.with_only_columns(E.kind, E.key, ALIASES)))

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

    def query(
        self, identity: Identity, kind: str | None = None,
        key: str | list[str] | None = None, date: Item | None = None,
        *, numeric: bool = False,
    ) -> Item:
        """The model query contract, independent of Agent transport and deps."""
        if kind is None and not key and date is None:
            return {"status": "query_required", "message": "须带类、正名或日期之一，目录见输入"}
        if kind in {"office", "incumbency"} and key:
            return self.office_record(identity, key, date)
        keys = list(dict.fromkeys([key] if isinstance(key, str) else key or [])) or None
        if keys:
            source = fact_sources(identity)
            visible = VISIBLE_IDS[identity_key(identity)]
            rows = ENTITY_ROWS.with_only_columns(E.kind, E.key, ALIASES)
            selected = named(self._ledger, kind, keys, query=rows.where(or_(
                E.id.in_(visible), E.id.in_(source.with_only_columns(F.entity_id).order_by(None)),
            )).params(**view_parameters(identity, kind)))
        else:
            selected = self.record_catalogue(identity, date, kind)
        names = names_and_aliases(selected) if keys else {}
        resolved = {
            value: ([value] if any(value in entries for entries in names.values()) else
                    list(dict.fromkeys(name for entries in names.values() for name, aliases in entries.items()
                                       if value in aliases)))
            for value in keys or []
        }
        if (kind is not None and not selected) or any(len(v) != 1 for v in resolved.values()):
            candidates = matching_names(
                self.catalogue(self.record_catalogue(identity, date, kind)), keys,
            ) if keys else {}
            return {"status": "not_found", "message": "未找到",
                    **({"names_and_aliases": candidates} if candidates else {})}
        if not keys:
            return {"catalogue": [e for e in selected if date is None or e["event_count"]]}
        selection = {k: v for k, v in {
            "kind": kind, "keys": list(dict.fromkeys(v[0] for v in resolved.values())), "date": date,
        }.items() if v is not None}
        result = self._material(identity, selection)
        return result if numeric else character_input(result)

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
            "facts": [f.model_dump(mode="json") for f in project(
                self._ledger, identity, {"date": selection["date"]} if "date" in selection else {}, query,
            )],
        }

    def facts(
        self, identity: Identity, *,
        entity_id: UUID | list[UUID] | None = None,
        kind: str | tuple[str, ...] | None = None, date: Item | None = None,
        detail: Item | None = None,
    ) -> tuple[FactView, ...]:
        if entity_id == [] or any(value == [] for value in (detail or {}).values()):
            return ()
        selection = {k: v for k, v in {"entity_id": entity_id, "kind": kind, "date": date}.items() if v is not None}
        query, _ = self._sources(identity)
        query = query.where(*queries.matching_details(F.detail, detail or {}))
        return project(self._ledger, identity, selection, query)

    def has_facts(self, entity_id: UUID, kind: str | tuple[str, ...], *, date: Item | None) -> bool:
        return bool(self._ledger.facts(
            entity_id=entity_id, kind=kind, date=date,
            query=FACT_ROWS.with_only_columns(F.position).order_by(None).limit(1),
        ))

    def entities(
        self, identity: Identity, *,
        kind: str | None = None, key: str | list[str] | None = None,
        ids: list[UUID] | None = None,
    ) -> tuple[EntityView, ...]:
        if ids == []:
            return ()
        selection: Item = {k: v for k, v in {"kind": kind, "keys" if isinstance(key, list) else "key": key, "ids": ids}.items() if v is not None}
        return entities(self._ledger, identity, selection, opening=self._opening(identity, snapshot=True))

    def _unmatched_query(self, identity: Identity, kind: str, response: str, link: tuple[str, str]) -> Select[Any]:
        return fact_sources(identity).where(queries.unmatched(kind, response, link))

    def unmatched(
        self, identity: Identity, kind: str, response: str, link: tuple[str, str],
    ) -> tuple[FactView, ...]:
        """Facts whose reference has no matching response, ordered by event position."""
        query = self._unmatched_query(identity, kind, response, link).order_by(None).order_by(F.position)
        return project(self._ledger, identity, {}, query)

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
        has: str | None = None, entity_kind: str | None = None,
    ) -> tuple[UUID, ...]:
        query, _ = self._sources(identity)
        query = query.with_only_columns(F.entity_id)
        if has is not None:
            query = query.where(F.detail[has].as_string().is_not(None))
        if entity_kind is not None:
            query = query.where(E.kind == entity_kind)
        return tuple(row["entity_id"] for row in self._ledger.facts(kind=kind, date=date, query=query, parameters=view_parameters(identity)))

    def journeys_due(self, date: Item) -> tuple[Item, ...]:
        return self._ledger.read(journeys_due(date))

    def levies_due(self, date: Item) -> list[Item]:
        events = {row["data"]["id"]: row for row in self._ledger.entities(kind="historical_event")}
        return [
            {"entity": row["key"], "data": row["data"]}
            for row in events.values()
            if row["data"].get("category") == "fiscal_levy"
            and (row["data"]["trigger_year"], row["data"]["trigger_month"])
            == (date["year"], date["month"])
            and row["data"].get("terminal_reason") is None
            and all(
                events[subject.split(".")[1]]["data"].get("terminal_reason")
                == required.removeprefix("==")
                for subject, required in row["data"]["trigger_gate"].items()
            )
        ]

    def landing_sources(
        self, date: Item, *, include_history: bool = True,
    ) -> list[tuple[Item, LandingMode | None, list[Item]]]:
        """Ordered sources, retaining decisions already read while resolving their mode."""
        records = self._ledger.entities(query=queries.landing_rows(date, include_history=include_history))
        if not records:
            return []
        decisions: dict[UUID, list[Item]] = defaultdict(list)
        for event in self._ledger.facts(entity_id=[row["id"] for row in records], kind=("deliberation", "choice"), date=date):
            decisions[event["entity_id"]].append(event)
        sources: list[tuple[Item, LandingMode | None, list[Item]]] = []
        for row in records:
            mode: LandingMode | None = "landed" if row.pop("errand") else None
            events = decisions[row["id"]]
            if row.pop("deliberated"):
                verdict = latest_detail(events, "deliberation")
                choice = latest_detail(events, "choice")
                mode = None
                if verdict and (verdict["verdict"] == "准" or (choice and choice["text"] == "强颁")):
                    mode = "landed"
                elif row["data"].get("interim"):
                    mode = "attempted"
            sources.append((row, mode, events))
        return sources

    def known_people(self, ids: list[UUID]) -> dict[UUID, list[str]]:
        readers = known_people(E.data).subquery()
        return {row["id"]: sorted(row["people"]) for row in self._ledger.read(select(
            E.id, select(func.json_group_array(readers.c.person, type_=JSON)).scalar_subquery().label("people"),
        ).where(E.id.in_(ids)))} if ids else {}

    def office_holders(self, offices: tuple[str, ...] | None = None, *, faction: str | None = None) -> tuple[str, ...]:
        query = ENTITY_ROWS.with_only_columns(E.key).where(E.kind == "person", queries.IN_OFFICE)
        if offices is not None:
            query = query.where(queries.CURRENT_APPOINTMENT.where(
                queries.APPOINTMENT.data["office"].as_string().in_(offices),
            ).exists())
        if faction is not None:
            query = query.where(E.data["faction"].as_string() == faction)
        return tuple(row["key"] for row in self._ledger.read(query))
