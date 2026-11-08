"""Model navigation and row-wise reads through the existing identity projections."""

from collections.abc import Callable, Collection, Generator
from contextlib import ExitStack, closing
from functools import partial
from itertools import batched, islice
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import Select, case, func, literal, or_, select, true, type_coerce, union_all

from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, ENTITY_ORDER, FACT_ROWS, Item, Ledger, facts_in_month
from ming.middle.appointments import ALIASES, incumbency_record, named, office_pairs
from ming.middle.night import TURN_ROWS, turn_view
from ming.middle.record_pages import PAGE_BYTES, PageRow, RecordCursor, RecordScope, TextPage, record_page
from ming.middle.rules import matching_names
from ming.middle.view import ENTITY_EXPOSURE, ENTITY_SOURCES, VISIBLE_IDS, character_input, entities, identity_key, project, view_parameters, visible_appointments

if TYPE_CHECKING:
    from ming.middle.reading import Records
    from ming.middle.view import Identity


class RecordQuery:
    def __init__(self, reader: "Records", ledger: Ledger, identity: "Identity", sources: tuple[Select[Any], Item | None], *, numeric: bool = False) -> None:
        self.reader = reader
        self.ledger = ledger
        self.identity: Identity = identity
        self.facts, opening = sources
        self.numeric = numeric
        self.budget = PAGE_BYTES
        self.snapshot: Select[Any] | None = None
        if opening is not None:
            items = func.json_each(F.detail, "$.entities").table_valued("key", "value")
            columns = [type_coerce(func.replace(func.json_extract(items.c.value, "$.id"), "-", ""), E.id.type).label("id")]
            columns.extend(type_coerce(func.json_extract(items.c.value, f"$.{field}"), E[field].type).label(field)
                           for field in ("kind", "key", "source", "data"))
            self.snapshot = select(*columns).select_from(F.position.table.join(items, true())).where(
                F.position == opening["position"],
            ).correlate(None)

    def visible(self, kind: str | None, date: Item | None) -> Select[Any]:
        facts = self.facts
        if date is not None:
            facts = facts.where(facts_in_month(date))
        ids = facts.with_only_columns(F.entity_id).order_by(None)
        eligible = E.id.in_(ids)
        if date is None:
            eligible = or_(eligible, E.id.in_(VISIBLE_IDS[identity_key(self.identity)]))
        query = ENTITY_ROWS.where(eligible)
        if kind is not None:
            query = query.where(E.kind == kind)
        # Explicit catalogue reads already permit both reference-table kinds.
        return query.params(**view_parameters(self.identity, kind or "office"))

    def directory(self, kind: str | None, date: Item | None, scope: RecordScope) -> Select[Any]:
        query = self.visible(kind, date)
        if kind is None and date is None:
            return query.with_only_columns(E.kind).order_by(None).distinct().order_by(E.kind)
        for field, value in scope.model_dump(exclude_none=True, include={"department", "region", "level"}).items():
            query = query.where(E.data[field].as_string() == value)
        return query.with_only_columns(E.kind, E.key, case(
            (ENTITY_EXPOSURE[identity_key(self.identity)] == "full",
             func.coalesce(E.data["description"].as_string(), E.data["distinction"].as_string())),
        ).label("description")).params(**view_parameters(self.identity, kind))

    def navigation(self, kind: str | None, date: Item | None, scope: RecordScope, cursor: RecordCursor) -> Item:
        if cursor.text is not None:
            return {"status": "invalid_cursor"}
        query = self.directory(kind, date, scope)
        field = "department" if kind == "office" else (
            "region" if kind == "territory" and scope.region is None else "level" if kind == "territory" else None
        )
        if not cursor.grouped:
            page = record_page(partial(self.listing, query), cursor, budget=self.budget)
            if "next" not in page or field is None or getattr(scope, field) is not None:
                return {"status": "not_found"} if page == {"catalogue": []} and kind and date is None and not scope.after else page
            cursor = cursor.model_copy(update={"row": 0, "character": 0, "grouped": True})
        if field is None:
            return {"status": "invalid_cursor"}
        group = E.data[field].as_string()
        query = query.with_only_columns(group.label(field), func.count().label("count")).order_by(None).group_by(group).order_by(group)
        return record_page(partial(self.listing, query), cursor, budget=self.budget)

    def listing(self, query: Select[Any], cursor: RecordCursor) -> Generator[Item]:
        with closing(self.ledger.scan(query.offset(cursor.row))) as rows:
            yield from ({"catalogue": [row]} for row in rows)

    def additional_ids(self, visible: Select[Any], keys: Collection[str], known: Collection[UUID]) -> Generator[UUID]:
        yield from (row["id"] for row in self.ledger.read(visible.with_only_columns(E.id).where(
            E.key.in_(keys), ~E.id.in_(known),
        )))

    def candidate_fields(self, page: TextPage, candidates: Item) -> Item:
        """Locate paths only for candidates already selected by the visible read."""
        result: Item = {}
        for kind, names in candidates.items():
            for key, aliases in names.items():
                if aliases:
                    aliases = page.whole("aliases", entity=(kind, key), payload=(
                        aliases, aliases, ENTITY_ROWS.where(E.kind == kind, E.key == key).with_only_columns(ALIASES),
                    ))
                    aliases = cast(list[str], []) if aliases.get("value") == [] else aliases
                result.setdefault(kind, {})[key] = aliases
        return result

    def office_material(self, names: list[str], date: Item | None, cursor: RecordCursor) -> Generator[PageRow]:
        page = TextPage(self.ledger, cursor, numeric=self.numeric, budget=self.budget)
        ids: dict[UUID, None] = {}
        previous = dict.fromkeys(names[:cursor.row])
        for index, record in enumerate(self.reader.office_records(self.identity, names[cursor.row:], office_view=lambda office: (
            entity if self.numeric else entity.model_copy(update={"data": character_input(entity.data)}) for entity in entities(
                self.ledger, self.identity, {"kind": "office", "key": office}, opening=self.snapshot, prepare=page,
            )
        ), prepare=page.clip), start=cursor.row):
            previous.pop(names[index], None)
            ids.update((UUID(item["entity_id"]), None) for item in record.get("appointments", ()) if item["entity_id"] is not None)
            page.cursor = page.cursor.model_copy(update={"row": index})
            if "names_and_aliases" in record:
                # Identifier-only candidates share prepared fields in the reader's request cache.
                record["names_and_aliases"] = self.candidate_fields(page, record["names_and_aliases"])
            yield page.render({"offices": [record]} if len(names) > 1 else record)
            page.cursor = page.cursor.model_copy(update={"clipped": False})
        # Prior-page headers need only a batch of visible IDs, not their bodies.
        keys: list[str] = []
        for name in previous:
            pairs, resolution = office_pairs(self.ledger, name, partial(visible_appointments, self.ledger, self.identity))
            if resolution["status"] == "resolved":
                keys.extend(incumbency_record(pair, [])[0] for pair in pairs)
        if keys:
            ids.update((entity_id, None) for entity_id in self.additional_ids(self.visible("incumbency", None), keys, ids))
        yield from self.material("incumbency", list(ids), date, cursor, len(names))

    def material(self, kind: str | None, ids: list[UUID], date: Item | None, cursor: RecordCursor, prefix: int | None = None) -> Generator[PageRow]:
        if not ids:
            return
        facts = self.facts.where(F.entity_id.in_(ids))
        if date is not None:
            facts = facts.where(facts_in_month(date))
        sources: list[Select[Any]] = []
        if prefix is None:
            entity_ids = ids if self.snapshot is None else self.snapshot.with_only_columns(self.snapshot.selected_columns.id).where(
                self.snapshot.selected_columns.id.in_(ids),
            )
            source = ENTITY_SOURCES[identity_key(self.identity)] if self.snapshot is None else ENTITY_ROWS
            sources.append(source.where(E.id.in_(entity_ids)).with_only_columns(
                literal("entity").label("type"), E.id.label("id"), literal(0).label("position"), E.kind, ENTITY_ORDER.label("entity_order"),
            ).order_by(None))
            if self.identity not in ("audit", "world") and self.snapshot is None:
                nights = ENTITY_SOURCES[identity_key(self.identity)].where(E.kind == "night", E.id.in_(ids)).with_only_columns(E.id).order_by(None)
                sources.append(FACT_ROWS.where(F.entity_id.in_(nights), F.kind == "turn").with_only_columns(
                    literal("turn").label("type"), F.entity_id.label("id"), F.position, E.kind, ENTITY_ORDER.label("entity_order"),
                ).order_by(None))
                facts = facts.where(~(F.entity_id.in_(nights) & (F.kind == "turn")))
        sources.append(facts.with_only_columns(
            literal("fact").label("type"), F.entity_id.label("id"), F.position, E.kind, ENTITY_ORDER.label("entity_order"),
        ).order_by(None))
        source = (union_all(*sources) if len(sources) > 1 else sources[0]).subquery()
        prefix = prefix or 0
        query = select(source).order_by(source.c.type, source.c.entity_order, source.c.position).offset(max(0, cursor.row - prefix)).params(
            **view_parameters(self.identity, kind or "office"),
        )
        with closing(self.ledger.scan(query)) as rows:
            positions = enumerate(rows, start=max(cursor.row, prefix))
            if cursor.clipped:
                # A previously measured row that did not fit the preceding page.
                yield from self.pieces(tuple(islice(positions, 1)), cursor, facts, kind)
                cursor = cursor.model_copy(update={"clipped": False})
            for batch in batched(positions, 1 if cursor.text or cursor.character else 64):
                yield from self.pieces(batch, cursor, facts, kind)

    def pieces(self, batch: tuple[tuple[int, Item], ...], cursor: RecordCursor, facts: Select[Any], kind: str | None) -> Generator[PageRow]:
        with ExitStack() as stack:
            for category in ("entity", "fact", "turn"):
                selected = [(index, row) for index, row in batch if row["type"] == category]
                if not selected:
                    continue
                page = TextPage(self.ledger, cursor, numeric=self.numeric, budget=self.budget)
                if category == "entity":
                    ids = [row["id"] for _, row in selected]
                    views = stack.enter_context(closing(entities(
                        self.ledger, self.identity, {"ids": ids, "kind": kind, "night_turns": False}, opening=self.snapshot, prepare=page,
                    )))
                    records = (({"entities": [entity.model_dump(mode="json")], "facts": []}, None) for entity in views)
                elif category == "turn":
                    records = (({"turns": [{"night_id": str(item["entity_id"]), **turn_view(item).model_dump(mode="json")}]}, item)
                               for item in self.ledger.read(page.clip(TURN_ROWS.where(F.position.in_([row["position"] for _, row in selected])))))
                else:
                    rows = stack.enter_context(closing(self.ledger.scan(page.clip(facts.where(
                        F.position.in_([row["position"] for _, row in selected]),
                    ).order_by(None).order_by(ENTITY_ORDER, F.position).params(**view_parameters(self.identity))))))
                    records = (({"entities": [], "facts": [project(self.identity, item).model_dump(mode="json")]}, item)
                               for item in rows)
                for (index, _row), (record, original) in zip(selected, records, strict=True):
                    page.cursor = cursor.model_copy(update={"row": index})
                    if original is not None:
                        projected = record["turns" if category == "turn" else "facts"][0]
                        source = cast(Select[Any], page.source).where(F.position == _row["position"])
                        projected["emperor_words"] = page.whole("emperor_words", payload=(projected["emperor_words"], original["emperor_words"], source))
                        if category == "turn":
                            projected["scene"] = page.whole("detail", payload=(projected["scene"], original["detail"]["scene"], source), path="$.scene")
                        else:
                            projected["detail"] = page.whole("detail", payload=(projected["detail"], original["detail"], source))
                    yield page.render(record if self.numeric else character_input(record))

    def run(
        self, kind: str | None, key: str | list[str] | None, date: Item | None,
        *, scope: RecordScope, cursor: RecordCursor,
    ) -> Item:
        # PAGE_BYTES already reserves pagination keys; outer tool envelopes deduct via scope.wrap.
        self.budget = max(0, PAGE_BYTES - (scope.wrap or 0))
        if (scope.department is not None and kind != "office" or
                (scope.region is not None or scope.level is not None) and kind != "territory"):
            return {"status": "invalid_scope"}
        source: Callable[[RecordCursor], Generator[PageRow]]
        if key and cursor.text is not None and cursor.text.entity is not None:
            entity = cursor.text.entity
            page = TextPage(self.ledger, cursor, numeric=self.numeric, budget=self.budget)
            if cursor.text.column == "aliases":
                visible = self.reader.office_names(self.identity) if kind in {"office", "incumbency"} else self.visible(kind, None)
                source = lambda _: (page.render(row) for row in self.ledger.read(page.clip(visible.where(
                    E.kind == entity[0], E.key == entity[1],
                ).with_only_columns(ALIASES))))
            elif cursor.text.column == "data" and entity[0] == "office" and kind in {None, "office", "incumbency"}:
                source = lambda _: (page.render({"entities": [row.model_dump(mode="json")]}) for row in entities(
                    self.ledger, self.identity, {"kind": "office", "key": entity[1]}, opening=self.snapshot, prepare=page,
                ))
            else:
                return {"status": "invalid_cursor"}
        elif key and kind in {"office", "incumbency"}:
            names = [key] if isinstance(key, str) else key
            source = partial(self.office_material, names, date)
        elif key:
            keys = list(dict.fromkeys([key] if isinstance(key, str) else key))
            visible = self.visible(kind, None)
            names = named(self.ledger, kind, keys, query=visible.with_only_columns(E.id, E.kind, E.key))
            canonical = {row["key"] for row in names}
            resolved = {value: {value} if value in canonical else {
                row["key"] for row in names if value in row["matches"]
            } for value in keys}
            if any(len(matches) != 1 for matches in resolved.values()):
                page = TextPage(self.ledger, cursor, numeric=self.numeric, budget=self.budget)
                candidates = matching_names(visible.with_only_columns(E.kind, E.key, ALIASES), keys, ledger=self.ledger, prepare=page.clip)
                result = {"status": "not_found", **({"names_and_aliases": self.candidate_fields(page, candidates)} if candidates else {})}
                return record_page(lambda position: (page.render(row) for row in (result,)[position.row:]), cursor, budget=self.budget) if candidates else result
            ids = [row["id"] for row in names if any(row["key"] in matches for matches in resolved.values())]
            # Unscoped aliases also select other visible kinds sharing the canonical
            # key (e.g. a person's dossier), but never read an already resolved ID.
            aliases = {name for matches in resolved.values() for name in matches} - set(keys)
            if kind is None and aliases:
                ids.extend(self.additional_ids(visible, aliases, ids))
            source = partial(self.material, kind, ids, date)
        else:
            return self.navigation(kind, date, scope, cursor)
        if cursor.text is not None:
            with closing(source(cursor)) as rows:
                # Field reads bypass row preparation in TextPage.render.
                result = cast(Item, next(rows, {"status": "invalid_cursor"}))
            return result
        return record_page(source, cursor, budget=self.budget)
