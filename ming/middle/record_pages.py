"""Bounded model delivery, separate from complete UI and audit reads."""

import json
from bisect import bisect_right
from collections.abc import Generator, Iterable
from contextlib import closing
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Select, case, func, select, true, type_coerce
from sqlalchemy.sql.elements import ColumnElement

from ming.ledger import Item, Ledger
from ming.middle.view import CHARACTER_BANDS, character_input


class RecordText(BaseModel):
    column: Literal["data", "detail", "emperor_words"]
    path: str | None = None
    container: bool = False
    dossier: bool = False


class RecordPosition(BaseModel):
    row: int = Field(default=0, ge=0)
    character: int = Field(default=0, ge=0)
    grouped: bool = False
    item: int = Field(default=0, ge=0)


class RecordCursor(RecordPosition):
    text: RecordText | None = None


class RecordScope(BaseModel):
    department: str | None = None
    region: str | None = None
    level: str | None = None
    read: RecordCursor | None = None
    after: RecordPosition | None = None


MAX_BYTES = 20_000


class TextPage:
    """Bound stored fields before projection; expose only surviving references."""

    def __init__(self, ledger: Ledger, cursor: RecordCursor, *, numeric: bool = False) -> None:
        self.ledger = ledger
        self.cursor = cursor
        self.numeric = numeric
        self.prefix = uuid4().hex
        self.allowed: list[RecordText] = []
        self.source: Select[Any] | None = None
        self.dossier_source: Select[Any] | None = None

    def clip(self, query: Select[Any], dossier: bool = False) -> Select[Any]:
        if dossier:
            self.dossier_source = query
        else:
            self.source = query
        columns = list(query.selected_columns)
        for index, column in enumerate(columns):
            if column.key not in {"data", "detail", "emperor_words"}:
                continue
            if dossier:
                clipped = func.json_quote(self.prefix + func.json_object(
                    "column", column.key, "path", "$", "container", True, "dossier", True,
                ))
            elif column.key == "emperor_words":
                clipped = self.prefix + func.json_object("column", column.key)
            else:
                children = func.json_each(column).table_valued("key", "value", "type", "fullkey")
                marker = self.prefix + func.json_object(
                    "column", column.key, "path", children.c.fullkey, "container", children.c.type.in_(("object", "array")), "dossier", dossier,
                )
                encoded = case(
                    (func.length(children.c.value) > 2000, func.json_quote(marker)),
                    (children.c.type == "text", func.json_quote(children.c.value)),
                    (children.c.type.in_(("true", "false", "null")), children.c.type),
                    else_=children.c.value,
                )
                clipped = select(func.json_group_object(children.c.key, func.json(encoded))).correlate_except(children).scalar_subquery()
            columns[index] = type_coerce(case((func.length(column) > 2000, clipped), else_=column), column.type).label(column.key)
        return query.with_only_columns(*columns)

    def replace(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith(self.prefix):
            reference = RecordText.model_validate_json(value[len(self.prefix):])
            self.allowed.append(reference)
            return {"read": {"row": self.cursor.row, "character": 0, "text": reference.model_dump()}}
        if isinstance(value, dict):
            return {key: self.replace(item) for key, item in cast(dict[str, Any], value).items()}
        if isinstance(value, list):
            return [self.replace(item) for item in cast(list[Any], value)]
        return value

    def container(self, text: ColumnElement[Any]) -> Generator[Item]:
        assert self.source is not None and self.cursor.text is not None
        reference = self.cursor.text
        children = func.json_each(self.source.selected_columns[reference.column], reference.path).table_valued("key", "value", "type", "fullkey")
        field = func.json_extract(text, "$.field")
        metadata = self.ledger.read(self.source.with_only_columns(
            case((field.in_(CHARACTER_BANDS), field)).label("field"), func.json_type(text).label("container"),
            maintain_column_froms=True,
        ))[0]
        query = self.source.with_only_columns(
            children.c.key, children.c.type, children.c.fullkey,
            case((func.length(children.c.value) > 2000, None), else_=children.c.value).label("value"),
            (func.length(children.c.value) > 2000).label("large"), maintain_column_froms=True,
        ).join(children, true()).order_by(None).offset(self.cursor.item)
        found = False
        with closing(self.ledger.scan(query)) as rows:
            for row in rows:
                found = True
                if row["large"]:
                    target = RecordText(column=reference.column, path=row["fullkey"], container=row["type"] in {"object", "array"}, dossier=reference.dossier)
                    value = {"read": self.cursor.model_copy(update={"character": 0, "item": 0, "text": target}).model_dump(exclude_none=True)}
                else:
                    value = (json.loads(row["value"]) if row["type"] in {"object", "array"} else
                             bool(row["value"]) if row["type"] in {"true", "false"} else row["value"])
                if not self.numeric and row["key"] == "value" and metadata["field"] is not None:
                    value = character_input({"field": metadata["field"], "value": value})["value"]
                yield ({"object": {row["key"]: value}} if metadata["container"] == "object" else {"items": [value]})
        if not found:
            invalid = self.cursor.character or self.cursor.item and not self.ledger.read(
                query.offset(self.cursor.item - 1).limit(1),
            )
            yield {"status": "invalid_cursor"} if invalid else {"object": {}} if metadata["container"] == "object" else {"items": []}

    def render(self, value: Item) -> Item:
        result = self.replace(value)
        if self.cursor.text is None:
            return result
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
            pieces = self.container(text)
            with closing(pieces):
                result = record_page(pieces, RecordCursor(row=self.cursor.item, character=self.cursor.character))
            if "next" in result:
                after = result["next"]
                result["next"] = self.cursor.model_copy(update={"item": after["row"], "character": after["character"]}).model_dump(exclude={"text"})
            return result
        rows = self.ledger.read(self.source.with_only_columns(
            func.substr(text, self.cursor.character + 1, MAX_BYTES).label("text"), func.length(text).label("length"),
            maintain_column_froms=True,
        ))
        if not rows or self.cursor.character > rows[0]["length"]:
            return {"status": "invalid_cursor"}
        row = rows[0]
        allowance = MAX_BYTES - len(json.dumps(self.cursor.model_dump(exclude={"text"}), ensure_ascii=True, indent=2).encode()) - 128
        length = fit_text(row["text"], 0, allowance)
        result = {"text": row["text"][:length]}
        end = self.cursor.character + length
        if end < row["length"]:
            result["next"] = self.cursor.model_copy(update={"character": end}).model_dump(exclude={"text"})
        return result


def fit_text(text: str, start: int, budget: int) -> int:
    return start + bisect_right(
        range(start + 1, min(len(text), start + budget) + 1), budget,
        key=lambda end: len(json.dumps(text[start:end], ensure_ascii=True).encode()),
    )


def record_page(rows: Iterable[dict[str, Any]], cursor: RecordCursor) -> dict[str, Any]:
    """Combine a bounded sequence of record pieces, or continue one JSON piece.

    Size includes ASCII escaping and indentation, not Python object memory.
    A fragment is JSON text; concatenate its text before decoding that piece.
    """
    result: dict[str, Any] = {}
    remaining = MAX_BYTES - 1024 - 2
    empty_sizes: dict[tuple[tuple[str, bool], ...], int] = {}
    for index, row in enumerate(rows, start=cursor.row):
        text = json.dumps(row, ensure_ascii=True, indent=2)
        size = len(text.encode())
        cost = size - (3 if result else 2)
        if row.keys() <= result.keys() and all(isinstance(value, (list, dict)) for value in row.values()):
            shape = tuple((field, isinstance(value, list)) for field, value in row.items())
            if shape not in empty_sizes:
                empty_sizes[shape] = len(json.dumps({field: [] if array else {} for field, array in shape}, ensure_ascii=True, indent=2).encode())
            # The shared outer object and container delimiters are emitted once.
            cost = size - empty_sizes[shape] - 2 * sum(bool(value) and bool(result[field]) for field, value in row.items())
        start = cursor.character if index == cursor.row else 0
        if start > len(text):
            return {"status": "invalid_cursor"}
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
            result["next"] = cursor.model_copy(update={"row": index, "character": start}).model_dump(exclude={"text"})
            break
        low = fit_text(text, start, remaining)
        result["fragment"] = {"row": index, "character": start, "text": text[start:low]}
        result["next"] = cursor.model_copy(update={
            "row": index if low < len(text) else index + 1, "character": low if low < len(text) else 0,
        }).model_dump(exclude={"text"})
        break
    return result or {"catalogue": []}
