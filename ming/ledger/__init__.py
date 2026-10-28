"""Events and derived rows commit atomically; explicit replay shares the row writer."""

from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import cache, lru_cache, partial, wraps
from itertools import product
from inspect import signature
from pathlib import Path
from threading import RLock
from typing import Any, ParamSpec, TypeVar, cast
from uuid import UUID, uuid4

import networkx as nx
from cachetools import LRUCache, cached
from eventsourcing.application import Application, LocalNotificationLog
from eventsourcing.persistence import Recording
from eventsourcing.domain import CanMutateAggregate
from eventsourcing_sqlalchemy.recorders import SQLAlchemyApplicationRecorder
from sqlalchemy import Engine, Select
from sqlalchemy.dialects.sqlite import dialect, insert
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, build_scope, find_all_in_scope
from sqlglot.optimizer.simplify import simplify
from sqlalchemy.orm import Session
from sqlalchemy.sql.cache_key import CacheKey
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.functions import Function
from sqlalchemy.sql.visitors import iterate, replacement_traverse
from frozendict import deepfreeze, frozendict
from pydantic import BaseModel

from ming.ledger.domain import Entity as Entity, Item as Item
from ming.ledger.tables import Base, EntityRow, FactRow
from ming.ledger.tables import (
    ENTITY_ROWS as ENTITY_ROWS,
    FACT_ROWS as FACT_ROWS,
    ENTITY_ORDER as ENTITY_ORDER,
    facts_in_month as facts_in_month,
)

# Native SQLAlchemy columns for read expressions, not ORM constructors/sessions.
ENTITY_COLUMNS = EntityRow.__table__.c
FACT_COLUMNS = FactRow.__table__.c
EMPTY_PARAMETERS = frozendict[str, Any]()


P = ParamSpec("P")
R = TypeVar("R")


def read_key(value: Any, *, include_values: bool = True) -> Any:
    """Keep immutable inputs; use native SQL identity and freeze only mutable keys."""
    if isinstance(value, Select):
        key = cast(CacheKey, cast(Any, value)._generate_cache_key())
        return (key.key, deepfreeze(tuple(p.value for p in key.bindparams))) if include_values else key.key
    try:
        hash(value)
    except TypeError:
        return deepfreeze(value.model_dump() if isinstance(value, BaseModel) else value)
    return value


@dataclass(frozen=True)
class ReadScope:
    table: str
    filters: tuple[tuple[str, frozenset[Any]], ...]
    data: frozenset[str] | None
    creates: bool = True
    output: bool = False

    def changed(self, table: str, row: Item, fields: Item | None) -> bool:
        if table != self.table or (fields is None and not self.creates):
            return False
        if table == "entities" and fields is not None and (not fields or (self.data is not None and self.data.isdisjoint(fields))):
            return False
        for field, values in self.filters:
            column, _, member = field.partition(":")
            value = row[column].get(member) if member else row[column]
            # SQL JSON scalar comparisons do not constrain object/array values.
            if not isinstance(value, (dict, list)) and value not in values:
                return False
        return True


def column_source(scope: Scope, column: exp.Column) -> tuple[Scope, str]:
    while column.table not in scope.selected_sources and scope.parent is not None:
        scope = scope.parent
    return scope, column.table


def query_terms(node: exp.Expr, *, nonnull: bool = False) -> list[list[exp.Expr]]:
    """Expose alternative selectors without copying or mutating the SQL tree."""
    node = node.unnest()
    if nonnull:
        if isinstance(node, exp.Case):
            # Null-producing branches cannot contribute rows. Conditions that
            # reject an earlier branch remain in the original SQL permission.
            return [left + right for branch in node.args["ifs"]
                    for left, right in product(query_terms(branch.this), query_terms(branch.args["true"], nonnull=True))] + query_terms(
                        node.args.get("default") or exp.Null(), nonnull=True)
        return [] if isinstance(node, exp.Null) else [[]]
    if isinstance(node, exp.And):
        return [left + right for left, right in product(query_terms(node.this), query_terms(node.expression))]
    if isinstance(node, exp.Or):
        return query_terms(node.this) + query_terms(node.expression)
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is) and isinstance(node.this.expression, exp.Null):
        return query_terms(node.this.this, nonnull=True)
    return [[node]]


@lru_cache
def json_path(value: str) -> exp.JSONPath:
    return cast(exp.JSONPath, parse_one("JSON_EXTRACT(data, " + exp.convert(value).sql() + ")", dialect="sqlite").expression)


def query_selector(scope: Scope, node: exp.Expr, parameters: Mapping[str, Any]) -> tuple[tuple[Scope, str, str], frozenset[Any]] | None:
    """Only immutable columns and facts' JSON members may select dependencies."""
    if not isinstance(node, (exp.EQ, exp.In)):
        return None
    column = node.this
    field = column.name
    if isinstance(column, (exp.JSONExtract, exp.JSONExtractScalar)) and isinstance(column.this, exp.Column) and column.this.name == "detail":
        path = column.expression
        if isinstance(path, exp.Placeholder):
            path = json_path(parameters[path.name])
        if not isinstance(path, exp.JSONPath) or len(path.expressions) != 2 or not isinstance(path.expressions[1], exp.JSONPathKey):
            return None
        field, column = "detail:" + path.expressions[1].name, column.this
    elif field not in {"id", "entity_id", "kind", "key", "source", "position"}:
        return None
    if isinstance(node, exp.In) and (query := node.args.get("query")) is not None:
        where = query.this.args.get("where")
        if (isinstance(column, exp.Column) and where is not None
                and not any(where.this.find_all(exp.Column, exp.Placeholder, exp.Subquery))
                and simplify(where.this.copy()) == exp.false()):
            return (*column_source(scope, column), field), frozenset()
    values = node.expressions if isinstance(node, exp.In) else [node.expression]
    if not isinstance(column, exp.Column) or not values or not all(isinstance(v, (exp.Placeholder, exp.Literal)) for v in values):
        return None
    return (*column_source(scope, column), field), frozenset(parameters[v.name] if isinstance(v, exp.Placeholder) else v.to_py() for v in values)


def query_graph(
    roots: dict[Scope, list[exp.Expr]],
    selector: Callable[[Scope, exp.Expr], tuple[tuple[Scope, str, str], frozenset[Any]] | None],
) -> nx.Graph[tuple[Scope, str, str]]:
    """Link unconditional equalities; alternative branch values stay separate."""
    graph: nx.Graph[tuple[Scope, str, str]] = nx.Graph()
    for scope, conditions in roots.items():
        for node in (node for root in conditions for node in (root.flatten() if isinstance(root, exp.And) else [root])):
            if isinstance(node, exp.EQ) and isinstance(node.this, exp.Column) and isinstance(node.expression, exp.Column):
                left = (*column_source(scope, node.this), node.this.name)
                right = (*column_source(scope, node.expression), node.expression.name)
                graph.add_edge(left, right)
                for entity, fact in ((left, right), (right, left)):
                    if entity[2] == "id" and fact[2] == "entity_id":
                        for field in ("kind", "key", "source"):
                            graph.add_edge((*entity[:2], field), (*fact[:2], "entity_" + field))
            elif selected := selector(scope, node):
                key, values = selected
                graph.add_node(key, values=values & graph.nodes[key].get("values", values) if key in graph else values)
    return graph


def query_filters(sources: list[Scope], parameters: Mapping[str, Any]) -> dict[tuple[Scope, str], set[tuple[tuple[str, frozenset[Any]], ...]]]:
    """Propagate immutable selectors through SQL equality joins/correlation."""
    roots: dict[Scope, list[exp.Expr]] = {}
    for scope in sources:
        where = scope.expression.args.get("where")
        joins = cast(list[exp.Join], scope.expression.args.get("joins") or [])
        roots[scope] = ([where.this] if where is not None else []) + [j.args["on"] for j in joins if "on" in j.args and not j.args.get("side")]
    selector = cache(partial(query_selector, parameters=parameters))
    graph = query_graph(roots, selector)
    inherited: dict[tuple[Scope, str, str], frozenset[Any]] = {}
    connected: dict[tuple[Scope, str, str], set[tuple[Scope, str, str]]] = {}
    for component in nx.connected_components(graph):
        values = [graph.nodes[n]["values"] for n in component if "values" in graph.nodes[n]]
        allowed = values[0].intersection(*values[1:]) if values else None
        for node in component:
            connected[node] = component
            if allowed is not None:
                inherited[node] = allowed
    predicates: dict[tuple[Scope, str], set[tuple[tuple[str, frozenset[Any]], ...]]] = {}
    for scope, conditions in roots.items():
        for terms in product(*(query_terms(root) for root in conditions)):
            term = [node for nodes in terms for node in nodes]
            selectors = dict(inherited)
            for node in term:
                if selected := selector(scope, node):
                    key, values = selected
                    for target in connected.get(key, {key}):
                        selectors[target] = values & selectors.get(target, values)
            for alias in scope.selected_sources:
                filters = tuple(sorted((field, values) for (owner, name, field), values in selectors.items() if owner is scope and name == alias))
                if all(values for _, values in filters):
                    predicates.setdefault((scope, alias), set()).add(filters)
    return predicates


@cached(LRUCache(maxsize=128), key=partial(read_key, include_values=False), lock=RLock())
def query_compiler(query: Select[Any]) -> SQLCompiler:
    """Keep SQL compilation independent of bound values, as SQLAlchemy does."""
    key = cast(CacheKey, cast(Any, query)._generate_cache_key())
    # SQLGlot requires literal JSON object keys; values remain SQL parameters.
    json_keys = {key for node in iterate(query) if isinstance(node, Function) and node.name == "json_object"
                 for key in cast(Function[Any], node).clauses.clauses[::2]}
    query = cast(Select[Any], replacement_traverse(query, {}, lambda element, **kw:
                 cast(BindParameter[Any], element).render_literal_execute()
                 if isinstance(element, BindParameter) and element in json_keys else None))
    return query.compile(dialect=dialect(paramstyle="named"), cache_key=key)


@lru_cache
def sql_scope(statement: str) -> Scope:
    """Parse a SQL shape once, independent of query arguments and game state."""
    root = build_scope(parse_one(statement, dialect="sqlite"))
    assert root is not None
    return root


def query_scopes(ledger: "Ledger", query: Select[Any], parameters: Mapping[str, Any]) -> frozenset[ReadScope]:
    """Resolve SQL's own sources with SQLGlot, retaining unconstrained inputs.

    Immutable equality/IN selectors narrow a dependency. Other predicates keep
    broader dependencies, never a second implementation of permission rules.
    """
    compiler = query_compiler(query)
    expanded = compiler.construct_expanded_state(compiler.construct_params(
        parameters, extracted_parameters=cast(CacheKey, cast(Any, query)._generate_cache_key()).bindparams,
    ))
    root = sql_scope(expanded.statement)
    sources = list(root.traverse())
    predicates = query_filters(sources, expanded.parameters)
    data: dict[tuple[Scope, str], set[str] | None] = {}
    outputs: set[tuple[Scope, str]] = set()
    for scope in sources:
        for column in find_all_in_scope(scope.expression, exp.Column):
            if column.name != "data":
                continue
            key = column_source(scope, column)
            parent = column.parent
            if isinstance(parent, (exp.JSONExtract, exp.JSONExtractScalar)) and isinstance(parent.expression, exp.Placeholder):
                fields = data.setdefault(key, set())
                if fields is not None:
                    path = json_path(expanded.parameters[parent.expression.name])
                    data[key] = fields | {path.expressions[1].name} if len(path.expressions) > 1 and isinstance(path.expressions[1], exp.JSONPathKey) else None
            elif (scope is root and column in root.expression.expressions
                  and any(isinstance(c, exp.Column) and c.table == column.table and c.name == "id" for c in root.expression.expressions)):
                outputs.add(key)
            else:
                data[key] = None
    scopes: set[ReadScope] = set()
    for scope in sources:
        joins = cast(list[exp.Join], scope.expression.args.get("joins") or [])
        for alias, (_, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table) or source.name not in {"entities", "facts"}:
                continue
            primary = "id" if source.name == "entities" else "position"
            # A row fetched by an existing foreign key / derived primary key
            # cannot enter by insertion alone; its selecting source must change.
            fetched = any(
                isinstance(on := join.args.get("on"), exp.EQ)
                and isinstance(on.this, exp.Column) and isinstance(on.expression, exp.Column)
                and on.this.table == alias and on.this.name == primary
                and on.expression.table in scope.selected_sources
                and (not isinstance(scope.selected_sources[on.expression.table][1], exp.Table)
                     or (source.name == "entities" and on.expression.name == "entity_id"))
                for join in joins if not join.args.get("side")
            )
            fields = data.get((scope, alias), set())
            for filters in predicates.get((scope, alias), ()):
                scopes.add(ReadScope(source.name, filters,
                                     None if fields is None else frozenset(fields), not fetched, (scope, alias) in outputs))
    return frozenset(scopes)


def read_once(reader: Callable[P, R]) -> Callable[P, R]:
    """Reuse reads while their transitive SQL inputs have not changed."""
    parameters = signature(reader)

    @wraps(reader)
    def reuse(owner: Any, *args: Any, **kwargs: Any) -> R:
        ledger: Ledger = getattr(owner, "_ledger", owner)
        bound = parameters.bind(owner, *args, **kwargs)
        bound.apply_defaults()
        key = (reader, tuple(read_key(value) for value in tuple(bound.arguments.values())[1:]))
        with ledger.read_lock:
            if key not in ledger.read_results:
                ledger.read_stack.append(set())
                try:
                    result = cast(Any, reader)(owner, *args, **kwargs)
                    ledger.read_results[key] = result, frozenset(ledger.read_stack[-1])
                finally:
                    ledger.read_stack.pop()
            result, scopes = ledger.read_results[key]
            if ledger.read_stack:
                ledger.read_stack[-1].update(scopes)
            return cast(R, result)
    return cast(Callable[P, R], reuse)


query_scopes = read_once(query_scopes)


class Events(Application[UUID]):
    name = "Ledger"


class Ledger:
    def __init__(self, db_path: Path) -> None:
        self.events = Events(env={
            "PERSISTENCE_MODULE": "eventsourcing_sqlalchemy",
            "SQLALCHEMY_URL": f"sqlite:///{db_path}",
            "AGGREGATE_CACHE_MAXSIZE": "10000",
            "AGGREGATE_CACHE_FASTFORWARD": "n",
        })
        self.sql = cast(SQLAlchemyApplicationRecorder, self.events.recorder)
        Base.metadata.create_all(cast(Engine, self.sql.datastore.engine))
        self.on_commit: Callable[[], None] | None = None
        self.read_results: LRUCache[Any, tuple[Any, frozenset[ReadScope]]] = LRUCache(maxsize=10000)
        self.read_stack: list[set[ReadScope]] = []
        self.read_lock = RLock()

    def close(self) -> None:
        self.events.close()
        cast(Engine, self.sql.datastore.engine).dispose()

    def write_rows(
        self, session: Session, entities: Iterable[Entity], recordings: Iterable[Recording[UUID]],
    ) -> None:
        rows = [entity.snapshot() for entity in entities]
        if rows:
            statement = insert(EntityRow)
            session.execute(statement.on_conflict_do_update(
                index_elements=[EntityRow.id],
                set_={c: getattr(statement.excluded, c) for c in ("kind", "key", "source", "data")},
            ), rows)
        session.add_all(FactRow(
            position=recording.notification.id,
            entity_id=recording.domain_event.originator_id,
            kind=recording.domain_event.kind,
            date=recording.domain_event.detail.get("date"),
            emperor_words=recording.domain_event.emperor_words,
            detail=recording.domain_event.detail,
        ) for recording in recordings if isinstance(recording.domain_event, Entity.Recorded))

    def commit(self, entities: list[Entity]) -> None:
        # Readers include worker-thread validators. Keep SQL, derived results
        # and invalidation in one state; nested read_once calls reenter this lock.
        with self.read_lock:
            try:
                # The recorder's documented outer transaction includes ORM rows.
                with self.sql.transaction() as session:
                    recordings = self.events.save(*entities)
                    saved = {r.domain_event.originator_id for r in recordings}
                    self.write_rows(session, (e for e in entities if e.id in saved), recordings)
                    session.flush()
            except Exception:
                # save() has already cached these aggregates. Evict rolled-back
                # versions so a retry reconstructs committed state.
                cache = self.events.repository.cache
                if cache is not None:
                    for entity in entities:
                        with suppress(KeyError):
                            cache.get(entity.id, evict=True)
                raise
            changed_entities = {e.id: {"id": e.id, "kind": e.kind, "key": e.key, "source": e.source} for e in entities}
            changes: list[tuple[str, Item, Item | None]] = []
            for recording in recordings:
                change = recording.domain_event
                changes.append(("entities", changed_entities[change.originator_id],
                                (change.changes or {}) if isinstance(change, Entity.Recorded) else None))
                if isinstance(change, Entity.Recorded):
                    changes.append(("facts", {"position": recording.notification.id, "entity_id": change.originator_id, "kind": change.kind, "detail": change.detail,
                                              **{"entity_" + field: value for field, value in changed_entities[change.originator_id].items() if field != "id"}}, None))
            invalid = {scope for scope in set[ReadScope]().union(*(s for _, s in self.read_results.values()))
                       if any(scope.changed(*change) for change in changes)}
            for key, (_, scopes) in list(self.read_results.items()):
                if not scopes.isdisjoint(invalid):
                    del self.read_results[key]
        if self.on_commit is not None:
            self.on_commit()

    @contextmanager
    def reading(self, replay: bool) -> Generator["Ledger"]:
        if not replay:
            yield self
            return
        rebuilt = Ledger(Path(f"file:{uuid4().hex}?mode=memory&cache=shared&uri=true"))
        try:
            states: dict[UUID, Entity] = {}
            log = LocalNotificationLog(self.events.recorder, section_size=1000)
            start = 1
            # Read each source page outside the destination transaction: the
            # recorder's thread-scoped transaction otherwise selects that DB.
            while notifications := log.select(start=start, limit=1000):
                recordings: list[Recording[UUID]] = []
                for notification in notifications:
                    domain_event = self.events.mapper.to_domain_event(notification)
                    entity_id = domain_event.originator_id
                    states[entity_id] = cast(Entity, cast(CanMutateAggregate[UUID], domain_event).mutate(states.get(entity_id)))
                    recordings.append(Recording(domain_event, notification))
                with rebuilt.sql.transaction() as session:
                    rebuilt.write_rows(session, (), recordings)
                start = notifications[-1].id + 1
            with rebuilt.sql.transaction() as session:
                rebuilt.write_rows(session, states.values(), ())
            yield rebuilt
        finally:
            rebuilt.close()

    @read_once
    def read(self, query: Select[Any], parameters: Mapping[str, Any] = EMPTY_PARAMETERS) -> tuple[Item, ...]:
        """Rows are deeply immutable; consumers project without editing the source."""
        scopes = query_scopes(self, query, parameters)
        with self.sql.transaction(commit=False) as session:
            rows = deepfreeze([dict(row) for row in session.execute(query, parameters).mappings()])
        self.read_stack[-1].update(scopes)
        if any(scope.output for scope in scopes):
            self.read_stack[-1].add(ReadScope("entities", (("id", frozenset(row["id"] for row in rows)),), None, False))
        return rows

    @read_once
    def entities(
        self,
        *,
        kind: str | tuple[str, ...] | None = None,
        key: str | None = None,
        entity_id: UUID | list[UUID] | None = None,
        query: Select[Any] = ENTITY_ROWS,
        parameters: Item | None = None,
    ) -> tuple[Item, ...]:
        if kind is not None:
            query = query.where(
                EntityRow.kind.in_(kind)
                if isinstance(kind, tuple)
                else EntityRow.kind == kind
            )
        if key is not None:
            query = query.where(EntityRow.key == key)
        if entity_id is not None:
            query = query.where(
                EntityRow.id.in_(entity_id)
                if isinstance(entity_id, list)
                else EntityRow.id == entity_id
            )
        return self.read(query, parameters or EMPTY_PARAMETERS)

    @read_once
    def facts(
        self,
        *,
        entity_id: UUID | list[UUID] | None = None,
        kind: str | tuple[str, ...] | None = None,
        date: Item | None = None,
        query: Select[Any] = FACT_ROWS,
        parameters: Item | None = None,
    ) -> tuple[Item, ...]:
        if entity_id is not None:
            query = query.where(
                FactRow.entity_id.in_(entity_id)
                if isinstance(entity_id, list)
                else FactRow.entity_id == entity_id
            )
        if kind is not None:
            query = query.where(
                FactRow.kind.in_(kind)
                if isinstance(kind, tuple)
                else FactRow.kind == kind
            )
        if date is not None:
            query = query.where(facts_in_month(date))
        return self.read(query, parameters or EMPTY_PARAMETERS)

    def get(self, entity_id: UUID) -> Entity:
        return self.events.repository.get(entity_id)
