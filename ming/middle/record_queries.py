"""Model navigation and row-wise reads through the existing identity projections."""

from collections.abc import Generator
from contextlib import ExitStack, closing
from functools import partial
from itertools import batched, islice
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Select, case, func, literal, or_, select, true, type_coerce, union_all

from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, ENTITY_ORDER, FACT_ROWS, Item, Ledger, facts_in_month
from ming.middle.appointments import ALIASES, catalogue, incumbency_record, named, office_pairs
from ming.middle.night import TURN_ROWS, turn_view
from ming.middle.record_pages import PageRow, RecordCursor, RecordScope, TextPage, record_page
from ming.middle.rules import matching_names
from ming.middle.view import ENTITY_EXPOSURE, ENTITY_SOURCES, VISIBLE_IDS, EntityView, character_input, entities, identity_key, project, view_parameters, visible_appointments

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
        if kind is None:
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
            page = record_page(partial(self.listing, query), cursor)
            if "next" not in page or field is None or getattr(scope, field) is not None:
                return {"status": "not_found"} if page == {"catalogue": []} and kind and date is None and not scope.after else page
            cursor = cursor.model_copy(update={"row": 0, "character": 0, "grouped": True})
        if field is None:
            return {"status": "invalid_cursor"}
        group = E.data[field].as_string()
        query = query.with_only_columns(group.label(field), func.count().label("count")).order_by(None).group_by(group).order_by(group)
        return record_page(partial(self.listing, query), cursor)

    def listing(self, query: Select[Any], cursor: RecordCursor) -> Generator[Item]:
        with closing(self.ledger.scan(query.offset(cursor.row))) as rows:
            yield from ({"catalogue": [row]} for row in rows)

    def office_material(self, names: list[str], date: Item | None, cursor: RecordCursor) -> Generator[PageRow]:
        if cursor.text is not None and cursor.row < len(names):
            yield {"status": "invalid_cursor"}
            return
        prepared: dict[str, Item] = {}
        for name in names[cursor.row:]:
            if name not in prepared:
                record = self.reader.office_record(self.identity, name)
                prepared[name] = record if self.numeric else character_input(record)
            yield {"offices": [prepared[name]]} if len(names) > 1 else prepared[name]
        # Header pages stop the generator above. History needs only resolved
        # appointment keys, not all earlier offices' complete descriptions.
        keys: list[str] = []
        for name in dict.fromkeys(names):
            if name in prepared:
                pairs = [(item["office"], item["territory"]) for item in prepared[name].get("appointments", ())]
            else:
                pairs, resolution = office_pairs(self.ledger, name, partial(visible_appointments, self.ledger, self.identity))
                if resolution["status"] != "resolved":
                    continue
            keys.extend(incumbency_record(pair, [])[0] for pair in pairs)
        yield from self.material("incumbency", keys, date, cursor, len(names))

    def material(self, kind: str | None, keys: list[str], date: Item | None, cursor: RecordCursor, prefix: int | None = None) -> Generator[PageRow]:
        visible = self.visible(kind, None)
        names = catalogue(named(self.ledger, kind, keys, query=visible.with_only_columns(E.id, E.kind, E.key, ALIASES)))
        canonical = {name for entries in names.values() for name in entries}
        resolved = {value: {value} if value in canonical else {
            name for entries in names.values() for name, aliases in entries.items() if value in aliases
        } for value in keys}
        if prefix is None and any(len(matches) != 1 for matches in resolved.values()):
            with closing(self.ledger.scan(visible.with_only_columns(E.kind, E.key, ALIASES))) as rows:
                candidates = matching_names(rows, keys)
            yield {"status": "not_found", **({"names_and_aliases": candidates} if candidates else {})}
            return
        ids = [row["id"] for row in self.ledger.read(visible.with_only_columns(E.id).where(
            E.key.in_({name for matches in resolved.values() for name in matches}),
        ))]
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
                page = TextPage(self.ledger, cursor, numeric=self.numeric)
                if category == "entity":
                    ids = [row["id"] for _, row in selected]
                    views = (entities(self.ledger, self.identity, {"ids": ids, "kind": kind, "night_turns": False}, prepare=page.clip)
                             if self.snapshot is None else (EntityView.model_validate(row) for row in self.ledger.read(page.clip(
                                 self.snapshot.where(self.snapshot.selected_columns.id.in_(ids)),
                             ))))
                    records = (({"entities": [entity.model_dump(mode="json")], "facts": []}, False) for entity in views)
                elif category == "turn":
                    records = (({"turns": [{"night_id": str(item["entity_id"]), **turn_view(item).model_dump(mode="json")}]}, False)
                               for item in self.ledger.read(page.clip(TURN_ROWS.where(F.position.in_([row["position"] for _, row in selected])))))
                else:
                    rows = stack.enter_context(closing(self.ledger.scan(page.clip(facts.where(
                        F.position.in_([row["position"] for _, row in selected]),
                    ).order_by(None).order_by(ENTITY_ORDER, F.position)), view_parameters(self.identity))))
                    records = (({"entities": [], "facts": [project(self.identity, item).model_dump(mode="json")]}, item["exposure"] == "full")
                               for item in rows)
                for (index, _row), (record, full) in zip(selected, records, strict=True):
                    page.cursor = cursor.model_copy(update={"row": index})
                    yield page.render(record if self.numeric else character_input(record), full=full)

    def run(
        self, kind: str | None, key: str | list[str] | None, date: Item | None,
        *, scope: RecordScope, cursor: RecordCursor,
    ) -> Item:
        if (scope.department is not None and kind != "office" or
                (scope.region is not None or scope.level is not None) and kind != "territory"):
            return {"status": "invalid_scope"}
        if key and kind in {"office", "incumbency"}:
            names = [key] if isinstance(key, str) else key
            source = partial(self.office_material, names, date)
        elif key:
            source = partial(self.material, kind, list(dict.fromkeys([key] if isinstance(key, str) else key)), date)
        else:
            return self.navigation(kind, date, scope, cursor)
        if cursor.text is not None:
            with closing(source(cursor)) as rows:
                # Field reads bypass row preparation in TextPage.render.
                result = cast(Item, next(rows, {"status": "invalid_cursor"}))
            return result if self.numeric else character_input(result)
        return record_page(source, cursor)
