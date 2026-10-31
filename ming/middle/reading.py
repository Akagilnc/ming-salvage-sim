"""Complete identity reads: resolution, visibility, opening view and projection."""

from collections.abc import Sequence
from functools import partial
from uuid import UUID

from sqlalchemy import func, or_, select, tuple_

from ming.ledger import (
    ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, ENTITY_ORDER,
    FACT_ROWS, Item, Ledger, facts_in_month,
)
from ming.middle import queries
from ming.middle.appointments import ALIASES, catalogue as names_and_aliases, office_pairs, incumbency_record, named
from ming.middle.calendar import calendar_row
from ming.middle.rules import matching_names, matching_offices
from ming.middle.view import (
    EntityView, FactView, Identity, ENTITY_EXPOSURE, ENTITY_SOURCES, MONTH_OPEN_QUERY,
    character_input, entities, fact_sources, identity_key, project, visible_appointments,
    view_parameters,
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

    def calendar(self) -> EntityView:
        return EntityView.model_validate(calendar_row(self._ledger))

    def entity(self, entity_id: UUID) -> EntityView:
        return EntityView.model_validate(self._ledger.entities(entity_id=entity_id)[0])

    def _visible(self, identity: Identity, opening: Item | None):
        if opening is None:
            return ENTITY_SOURCES[identity_key(identity)].with_only_columns(E.id).order_by(None)
        if "detail" in opening:
            return select(E.id).where(E.id.in_([UUID(e["id"]) for e in opening["detail"]["entities"]]))
        snapshot = func.json_each(FACT_ROWS.with_only_columns(F.detail["entities"]).where(
            F.position == opening["position"],
        ).order_by(None).scalar_subquery()).table_valued("value")
        return select(E.id).where(E.id.in_(select(
            func.replace(func.json_extract(snapshot.c.value, "$.id"), "-", ""),
        )))

    def record_catalogue(
        self, identity: Identity, date: Item | None = None, kind: str | None = None,
    ) -> tuple[Item, ...]:
        return self._catalogue(identity, date, kind, self._opening(identity))

    def _catalogue(
        self, identity: Identity, date: Item | None, kind: str | None, opening: Item | None,
    ) -> tuple[Item, ...]:
        source = fact_sources(identity, cutoff=opening["position"] if opening else None)
        visible = self._visible(identity, opening)
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
        opening = self._opening(identity, snapshot=bool(keys))
        if keys:
            source = fact_sources(identity, cutoff=opening["position"] if opening else None)
            visible = self._visible(identity, opening)
            rows = (ENTITY_ROWS.with_only_columns(E.kind, E.key, ALIASES) if opening else
                    ENTITY_ROWS.add_columns(ALIASES, ENTITY_EXPOSURE[identity_key(identity)].label("exposure")))
            selected = named(self._ledger, kind, keys, query=rows.where(or_(
                E.id.in_(visible), E.id.in_(source.with_only_columns(F.entity_id).order_by(None)),
            )).params(**view_parameters(identity, kind)))
        else:
            selected = self._catalogue(identity, date, kind, opening)
        names = names_and_aliases(selected) if keys else {}
        resolved = {
            value: ([value] if any(value in entries for entries in names.values()) else
                    list(dict.fromkeys(name for entries in names.values() for name, aliases in entries.items()
                                       if value in aliases)))
            for value in keys or []
        }
        if (kind is not None and not selected) or any(len(v) != 1 for v in resolved.values()):
            candidates = matching_names(
                self.catalogue(self._catalogue(identity, date, kind, opening)), keys,
            ) if keys else {}
            return {"status": "not_found", "message": "未找到",
                    **({"names_and_aliases": candidates} if candidates else {})}
        if not keys:
            return {"catalogue": [e for e in selected if date is None or e["event_count"]]}
        selection = {k: v for k, v in {
            "kind": kind, "keys": list(dict.fromkeys(v[0] for v in resolved.values())), "date": date,
        }.items() if v is not None}
        result = self._material(identity, selection, opening, rows=[
            row for row in selected if row.get("exposure") is not None and row["key"] in selection["keys"]
        ])
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
            reader = self if ledger is self._ledger else Records(ledger)
            return reader._material(identity, selection, reader._opening(identity, snapshot=True))

    def _material(
        self, identity: Identity, selection: Item, opening: Item | None, *, rows: Sequence[Item] | None = None,
    ) -> Item:
        query = fact_sources(identity, cutoff=opening["position"] if opening else None)
        query = query.where(E.kind == selection["kind"]) if "kind" in selection else query
        query = query.where(E.key.in_(selection["keys"])) if "keys" in selection else query
        return {
            "entities": [e.model_dump(mode="json") for e in entities(
                self._ledger, identity, {k: v for k, v in selection.items() if k != "date"}, opening=opening, rows=rows,
            )],
            "facts": [f.model_dump(mode="json") for f in project(
                self._ledger, identity, {"date": selection["date"]} if "date" in selection else {}, query,
            )],
        }

    def facts(
        self, identity: Identity, replay: bool = False, *,
        entity_id: UUID | list[UUID] | None = None,
        kind: str | tuple[str, ...] | None = None, date: Item | None = None,
    ) -> tuple[FactView, ...]:
        if entity_id == []:
            return ()
        selection = {k: v for k, v in {"entity_id": entity_id, "kind": kind, "date": date}.items() if v is not None}
        with self._ledger.reading(replay) as ledger:
            reader = self if ledger is self._ledger else Records(ledger)
            opening = reader._opening(identity)
            return project(ledger, identity, selection, fact_sources(identity, cutoff=opening["position"] if opening else None))

    def has_facts(self, entity_id: UUID, kind: str | tuple[str, ...], *, date: Item | None) -> bool:
        return bool(self._ledger.facts(
            entity_id=entity_id, kind=kind, date=date,
            query=FACT_ROWS.with_only_columns(F.position).order_by(None).limit(1),
        ))

    def entities(
        self, identity: Identity, replay: bool = False, *,
        kind: str | None = None, key: str | list[str] | None = None,
    ) -> tuple[EntityView, ...]:
        selection: Item = {k: v for k, v in {"kind": kind, "keys" if isinstance(key, list) else "key": key}.items() if v is not None}
        with self._ledger.reading(replay) as ledger:
            reader = self if ledger is self._ledger else Records(ledger)
            return entities(ledger, identity, selection, opening=reader._opening(identity, snapshot=True))
