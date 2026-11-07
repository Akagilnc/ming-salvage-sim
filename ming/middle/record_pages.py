"""Bounded model delivery, separate from complete UI and audit reads."""

import json
from bisect import bisect_right
from collections.abc import Callable, Generator
from contextlib import closing
from functools import partial
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import JSON, LargeBinary, Select, case, cast as sql_cast, func, literal, select, true, type_coerce
from sqlalchemy.sql.elements import ColumnElement

from ming.ledger import Item, Ledger
from ming.middle.view import CHARACTER_BANDS, character_input


class RecordText(BaseModel):
    column: Literal["data", "detail", "emperor_words", "aliases"]
    path: str | None = None
    container: bool = False
    dossier: bool = False
    entity: tuple[str, str] | None = Field(default=None, description="Alias or office field's (kind, canonical key), returned by read.")


class RecordPosition(BaseModel):
    row: int = Field(default=0, ge=0)
    character: int = Field(default=0, ge=0)
    grouped: bool = False
    item: int = Field(default=0, ge=0)
    clipped: bool = Field(default=False, description="Resume the pending row with its whole-detail reference; returned by next.")


class RecordCursor(RecordPosition):
    text: RecordText | None = None


class RecordScope(BaseModel):
    department: str | None = None
    region: str | None = None
    level: str | None = None
    read: RecordCursor | None = None
    after: RecordPosition | None = None


MAX_BYTES = 20_000
PAGE_BYTES = MAX_BYTES - 1024
PageRow = Item | tuple[Item, str, int, bool]


def large_field(column: ColumnElement[Any]) -> ColumnElement[bool]:
    return func.length(column) > 2000


class TextPage:
    """Measure projected delivery first; bound rereads and expose only surviving references."""

    def __init__(self, ledger: Ledger, cursor: RecordCursor, *, numeric: bool = False) -> None:
        self.ledger = ledger
        self.cursor = cursor
        self.numeric = numeric
        self.prefix = uuid4().hex
        self.allowed: list[RecordText] = []
        self.full: list[Item] = []
        self.sources: list[tuple[Select[Any], Any]] = []
        self.source: Select[Any] | None = None
        self.dossier_source: Select[Any] | None = None

    def whole(
        self, column: str, dossier: bool = False, entity: tuple[str, str] | None = None,
        *, payload: tuple[Any, Any, Select[Any]] | None = None, path: str | None = None,
    ) -> Item:
        """Carry projected values and their source until actual delivery measurement."""
        result: Item = {self.prefix: self.prefix + RecordText.model_validate({
            "column": column, "path": path or (None if column == "emperor_words" else "$"),
            "container": isinstance(payload[0], (dict, list)) if payload else column != "emperor_words",
            "dossier": dossier, "entity": entity,
        }).model_dump_json(exclude_none=True)}
        if payload is not None:
            self.sources.append((payload[2], payload[1]))
            result.update(value=payload[0], source=len(self.sources) - 1, complete=payload[0] == payload[1])
        return result

    def entity(self, row: Item, original: Item) -> Item:
        assert self.source is not None
        return {**row, "data": self.whole("data", entity=(row["kind"], row["key"]) if row["kind"] == "office" else None,
                                        payload=(row["data"], original["data"], self.source.where(self.source.selected_columns.id == row["id"])))}

    def clip(self, query: Select[Any], dossier: bool = False) -> Select[Any]:
        if dossier:
            self.dossier_source = query
        else:
            self.source = query
        if self.cursor.text is None and not self.cursor.clipped:
            return query
        columns = list(query.selected_columns)
        for index, column in enumerate(columns):
            if column.key == "aliases" and self.cursor.text is not None:
                columns[index] = literal(self.whole("aliases", entity=self.cursor.text.entity), type_=JSON).label("aliases")
                continue
            if column.key not in {"data", "detail", "emperor_words"}:
                continue
            if dossier:
                clipped = literal(self.whole(column.key, dossier), type_=JSON)
            elif column.key == "emperor_words":
                clipped = self.prefix + func.json_object("column", column.key)
            else:
                children = func.json_each(column).table_valued("key", "value", "type", "fullkey")
                marker = self.prefix + func.json_object(
                    "column", column.key, "path", children.c.fullkey, "container", children.c.type.in_(("object", "array")), "dossier", dossier,
                    "entity", func.json(case((query.selected_columns.kind == "office", func.json_array(
                        query.selected_columns.kind, query.selected_columns.key,
                    )))) if column.key == "data" else None,
                )
                encoded = case(
                    (large_field(children.c.value), func.json_quote(marker)),
                    (children.c.type == "text", func.json_quote(children.c.value)),
                    (children.c.type.in_(("true", "false", "null")), children.c.type),
                    else_=children.c.value,
                )
                clipped = select(func.json_group_object(children.c.key, func.json(encoded))).correlate_except(children).scalar_subquery()
            clipped = case((large_field(column), clipped), else_=column)
            if column.key == "detail" and "exposure" in query.selected_columns:
                clipped = case((query.selected_columns.exposure == "full", literal(self.whole(column.key), type_=JSON)), else_=clipped)
            columns[index] = type_coerce(clipped, column.type).label(column.key)
        return query.with_only_columns(*columns)

    def replace(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith(self.prefix):
            reference = RecordText.model_validate_json(value[len(self.prefix):])
            self.allowed.append(reference)
            return {"read": {"row": self.cursor.row, "character": 0, "text": reference.model_dump(exclude_none=True)}}
        if isinstance(value, dict):
            if self.prefix in value:
                if "value" in value:
                    self.full.append(cast(Item, value))
                    if value["complete"]:
                        self.allowed.append(RecordText.model_validate_json(cast(str, value[self.prefix])[len(self.prefix):]))
                    return self.replace(value["value"])
                return self.replace(value[self.prefix])
            return {key: self.replace(item) for key, item in cast(dict[str, Any], value).items()}
        if isinstance(value, list):
            return [self.replace(item) for item in cast(list[Any], value)]
        return value

    def container(self, metadata: Item, cursor: RecordCursor) -> Generator[PageRow]:
        assert self.source is not None and self.cursor.text is not None
        reference = self.cursor.text
        children = func.json_each(self.source.selected_columns[reference.column], reference.path).table_valued("key", "value", "type", "fullkey")
        query = self.source.with_only_columns(
            children.c.key, children.c.type, children.c.fullkey,
            # Stored JSON may use six-character Unicode escapes. This is only
            # an upper read bound; decoded values still use the normal pager.
            case((case((children.c.type == "text", func.length(sql_cast(children.c.value, LargeBinary)) > PAGE_BYTES),
                       else_=func.length(children.c.value) > PAGE_BYTES * 6), None), else_=children.c.value).label("value"), maintain_column_froms=True,
        ).join(children, true()).order_by(None).offset(cursor.row)
        with closing(self.ledger.scan(query)) as rows:
            for row in rows:
                # json_each preserves JSON null's type; other NULLs were clipped.
                if row["value"] is None and row["type"] != "null":
                    target = reference.model_copy(update={"path": row["fullkey"], "container": row["type"] in {"object", "array"}})
                    value = {"read": self.cursor.model_copy(update={"character": 0, "item": 0, "text": target}).model_dump(exclude_none=True)}
                else:
                    value = (json.loads(cast(str, row["value"])) if row["type"] in {"object", "array"} else
                             bool(row["value"]) if row["type"] in {"true", "false"} else row["value"])
                if not self.numeric:
                    value = (character_input({"field": metadata["field"], "value": value})["value"]
                             if row["key"] == "value" and metadata["field"] is not None else character_input({row["key"]: value})[row["key"]])
                page = TextPage(self.ledger, self.cursor.model_copy(update={"text": None, "character": 0}), numeric=self.numeric)
                if row["value"] is not None:
                    value = page.whole(reference.column, reference.dossier, reference.entity,
                                       payload=(value, value, self.source), path=row["fullkey"])
                yield page.render({"object": {row["key"]: value}} if metadata["container"] == "object" else {"items": [value]})

    def shrink(self, value: Any, field: Item, keys: tuple[str | int, ...] = (), original: Any = None) -> Any:
        """Keep fitting children inline; only unchanged source values may become references."""
        pieces: Callable[[RecordCursor], Generator[Item]]
        complete = value == original if keys else field["complete"]
        if isinstance(value, dict) and self.prefix not in value:
            reduced = {key: self.shrink(item, field, (*keys, key), cast(Item, original).get(key) if isinstance(original, dict) else None)
                       for key, item in cast(Item, value).items()}
            pieces = lambda _: ({"object": {key: self.replace(item)}} for key, item in reduced.items())
            if "next" not in record_page(pieces, RecordCursor(), empty={"object": {}}):
                return reduced
            value = reduced
        elif isinstance(value, list):
            items = [self.shrink(item, field, (*keys, index), cast(list[Any], original)[index] if isinstance(original, list) and index < len(cast(list[Any], original)) else None)
                     for index, item in enumerate(cast(list[Any], value))]
            pieces = lambda _: ({"items": [self.replace(item)]} for item in items)
            if "next" not in record_page(pieces, RecordCursor(), empty={"items": []}):
                return items
            value = items
        elif not isinstance(value, str) or fit_text(value, 0, PAGE_BYTES) == len(value):
            return cast(Any, value)
        if not complete:
            return value
        if not keys:
            return field[self.prefix]
        if "paths" not in field:
            field["reference"] = RecordText.model_validate_json(field[self.prefix][len(self.prefix):])
            source = self.sources[cast(int, field["source"])][0]
            tree = func.json_tree(source.selected_columns[field["reference"].column], field["reference"].path).table_valued("id", "parent", "key", "fullkey")
            # Ask SQLite for native paths only when a child needs a reference.
            field["paths"] = {(row["parent"], row["key"]): row for row in self.ledger.read(
                source.with_only_columns(*tree.c, maintain_column_froms=True).join(tree, true()).order_by(None),
            )}
        node = next(node for (parent, _), node in field["paths"].items() if parent is None)
        for key in keys:
            node = field["paths"][node["id"], key]
        reference: RecordText = field["reference"]
        return self.prefix + reference.model_copy(update={
            "path": node["fullkey"], "container": isinstance(value, (dict, list)),
        }).model_dump_json(exclude_none=True)

    def compact(self, value: Item, prepared: tuple[Item, str, int, bool]) -> PageRow:
        fields = self.full[:]
        changed = False
        for field in fields:
            reduced = self.shrink(field["value"], field, original=self.sources[field["source"]][1])
            changed |= reduced != field["value"]
            field["value"] = reduced
        if changed:
            self.full.clear()
            prepared = page_row(self.replace(value), clipped=True)
        if prepared[2] <= PAGE_BYTES:
            return prepared
        # Each field is now bounded. If their combination still cannot fit,
        # defer only the largest necessary fields, not every sibling.
        for field in sorted((field for field in fields if field["complete"]),
                            key=lambda field: page_row({"value": self.replace(field["value"])})[2], reverse=True):
            del field["value"]
            self.full.clear()
            prepared = page_row(self.replace(value), clipped=True)
            if prepared[2] <= PAGE_BYTES:
                break
        return prepared

    def render(self, value: Item) -> PageRow:
        self.allowed.clear()
        self.full.clear()
        result = self.replace(value)
        if self.cursor.text is None:
            prepared = page_row(result, clipped=self.cursor.clipped)
            return self.compact(value, prepared) if self.full and prepared[2] > PAGE_BYTES else prepared
        reference = self.cursor.text
        self.source = self.dossier_source if reference.dossier else self.source
        if reference not in self.allowed or self.source is None:
            if self.source is None or not any(parent.container and parent.column == reference.column and parent.dossier == reference.dossier and reference.path and parent.path
                       and reference.path.startswith((parent.path + ".", parent.path + "[")) for parent in self.allowed):
                return {"status": "invalid_cursor"}
            tree = func.json_tree(self.source.selected_columns[reference.column]).table_valued("fullkey", "type")
            if not self.ledger.read(self.source.with_only_columns(tree.c.type, maintain_column_froms=True).join(tree, true()).where(
                tree.c.fullkey == reference.path, tree.c.type.in_(("array", "object") if reference.container else ("text",)),
            )):
                return {"status": "invalid_cursor"}
        column = self.source.selected_columns[reference.column]
        text = column if reference.path is None else func.json_extract(column, reference.path)
        if reference.container:
            field = func.json_extract(text, "$.field")
            metadata = self.ledger.read(self.source.with_only_columns(
                case((field.in_(CHARACTER_BANDS), field)).label("field"), func.json_type(text).label("container"),
                maintain_column_froms=True,
            ))[0]
            result = record_page(partial(self.container, metadata), RecordCursor(row=self.cursor.item, character=self.cursor.character),
                                 empty={"object": {}} if metadata["container"] == "object" else {"items": []})
            if "next" in result:
                after = result["next"]
                result["next"] = self.cursor.model_copy(update={"item": after["row"], "character": after["character"]}).model_dump(exclude={"text"})
            return result
        query = self.source.with_only_columns(
            func.substr(text, self.cursor.character + 1, MAX_BYTES).label("text"), func.length(text).label("length"),
            maintain_column_froms=True,
        )
        return record_page(lambda _: self.ledger.scan(query), self.cursor, raw=True)


def fit_text(text: str, start: int, budget: int) -> int:
    return start + bisect_right(
        range(start + 1, min(len(text), start + budget) + 1), budget,
        key=lambda end: len(json.dumps(text[start:end], ensure_ascii=False).encode()),
    )


def page_row(row: Item, *, raw: bool = False, clipped: bool = False) -> tuple[Item, str, int, bool]:
    """Carry the measured serialization into the one page assembler."""
    text = row["text"] if raw else json.dumps(row, ensure_ascii=False, indent=2)
    return row, text, len(text.encode()), clipped


def record_page(
    rows: Callable[[RecordCursor], Generator[PageRow]], cursor: RecordCursor,
    *, empty: Item | None = None, raw: bool = False,
) -> Item:
    """Validate positions and combine bounded pieces (or a raw field substring).

    Only after an empty read, check the preceding row to distinguish EOF from
    an invalid offset. JSON fragments are valid only for a row that cannot fit
    whole, unlike raw field substrings.
    """
    result: Item = {}
    empty = empty or {"catalogue": []}
    remaining = PAGE_BYTES - 2
    empty_sizes: dict[tuple[tuple[str, bool], ...], int] = {}
    with closing(rows(cursor)) as pieces:
        for index, piece in enumerate(pieces, start=cursor.row):
            piece = piece if isinstance(piece, tuple) else page_row(piece, raw=raw)
            row, text = piece[:2]
            cost = piece[2] - (3 if result else 2)
            start = cursor.character if index == cursor.row else 0
            if start > (row["length"] if raw else len(text)) or (start and not raw and cost <= remaining):
                return {"status": "invalid_cursor"}
            if raw:
                low = fit_text(text, 0, remaining)
                return {"text": text[:low], **({
                    "next": cursor.model_copy(update={"character": start + low}).model_dump(exclude={"text"}),
                } if start + low < row["length"] else {})}
            if row.keys() <= result.keys() and all(isinstance(value, (list, dict)) for value in row.values()):
                shape = tuple((field, isinstance(value, list)) for field, value in row.items())
                if shape not in empty_sizes:
                    empty_sizes[shape] = page_row({field: [] if array else {} for field, array in shape})[2]
                cost = piece[2] - empty_sizes[shape] - 2 * sum(bool(value) and bool(result[field]) for field, value in row.items())
            if not start and cost <= remaining:
                for field, value in row.items():
                    if isinstance(value, list):
                        result.setdefault(field, []).extend(value)
                    elif isinstance(value, dict):
                        result.setdefault(field, {}).update(value)
                    else:
                        result[field] = value
                remaining -= cost
                continue
            if result:
                result["next"] = cursor.model_copy(update={"row": index, "character": start, "clipped": piece[3]}).model_dump(exclude={"text"})
                break
            low = fit_text(text, start, remaining)
            result["fragment"] = {"row": index, "character": start, "text": text[start:low]}
            result["next"] = cursor.model_copy(update={
                "row": index if low < len(text) else index + 1, "character": low if low < len(text) else 0,
                "clipped": piece[3] and low < len(text),
            }).model_dump(exclude={"text"})
            break
        if not result and not raw and cursor.row and not cursor.character:
            with closing(rows(cursor.model_copy(update={"row": cursor.row - 1}))) as previous:
                result = empty if next(previous, None) is not None else {"status": "invalid_cursor"}
    return result or ({"status": "invalid_cursor"} if cursor.character or raw else empty)
