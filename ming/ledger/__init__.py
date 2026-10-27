"""The event store and its synchronous, rebuildable query projection.

Calendar/night callers demonstrate the pattern: commit aggregates, then read only
matching rows/facts. No caller refreshes tables or carries a parallel event list.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from eventsourcing.system import SingleThreadedRunner, System
from eventsourcing_sqlalchemy.recorders import SQLAlchemyApplicationRecorder
from sqlalchemy import Engine, Select

from ming.ledger.domain import Entity as Entity, Item as Item
from ming.ledger.projection import Events, ReadModel
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


class Ledger:
    def __init__(self, db_path: Path) -> None:
        self.runner: SingleThreadedRunner[UUID] = SingleThreadedRunner(
            System([[Events, ReadModel]]),
            env={
                "PERSISTENCE_MODULE": "eventsourcing_sqlalchemy",
                "SQLALCHEMY_URL": f"sqlite:///{db_path}",
                "AGGREGATE_CACHE_MAXSIZE": "10000",
            },
        )
        self.events = self.runner.get(Events)
        self.read_model = self.runner.get(ReadModel)
        self.read_model.source = self.events
        self.sql = cast(SQLAlchemyApplicationRecorder, self.events.recorder)
        Base.metadata.create_all(cast(Engine, self.sql.datastore.engine))
        self.on_commit: Callable[[], None] | None = None
        self.runner.start()
        # Follower uses tracking to catch up; row writes and tracking share this
        # outer transaction, including when opening an existing save.
        with self.sql.transaction():
            self.read_model.pull_and_process(self.events.name)

    def close(self) -> None:
        engines = [
            cast(
                Engine,
                cast(SQLAlchemyApplicationRecorder, app.recorder).datastore.engine,
            )
            for app in self.runner.apps.values()
        ]
        self.runner.stop()
        for engine in engines:
            engine.dispose()

    def commit(self, entities: list[Entity]) -> None:
        try:
            # eventsourcing-sqlalchemy's module ContextVar reuses this session in
            # the Leader, Follower policy, and ProcessRecorder tracking insert.
            with self.sql.transaction():
                self.events.save(*entities)
        except Exception:
            # A rollback must not leave uncommitted aggregate state in the cache:
            # the policy cached each saved aggregate at its uncommitted version.
            # LRUCache.clear() resets only its recency list, so evict each one.
            cache = self.events.repository.cache
            if cache is not None:
                for entity in entities:
                    with suppress(KeyError):
                        cache.get(entity.id, evict=True)
            raise
        if self.on_commit is not None:
            self.on_commit()

    @contextmanager
    def reading(self, replay: bool) -> Generator["Ledger"]:
        if not replay:
            yield self
            return
        # Existing --replay seam, with empty derived tables and the very same
        # policy pulling the original notification log. No alternate projector.
        rebuilt = Ledger(Path(f"file:{uuid4().hex}?mode=memory&cache=shared&uri=true"))
        try:
            rebuilt.read_model.source = self.events
            rebuilt.read_model.follow(self.events.name, self.events.notification_log)
            rebuilt.read_model.pull_and_process(self.events.name)
            yield rebuilt
        finally:
            rebuilt.close()

    def read(self, query: Select[Any], parameters: Item | None = None) -> list[Item]:
        """Execute a read-only SQLAlchemy selection; policy remains the writer."""
        with self.sql.transaction(commit=False) as session:
            return [dict(row) for row in session.execute(query, parameters or {}).mappings()]

    def entities(
        self,
        *,
        kind: str | tuple[str, ...] | None = None,
        key: str | None = None,
        entity_id: UUID | list[UUID] | None = None,
        query: Select[Any] = ENTITY_ROWS,
        parameters: Item | None = None,
    ) -> list[Item]:
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
        return self.read(query, parameters)

    def facts(
        self,
        *,
        entity_id: UUID | list[UUID] | None = None,
        kind: str | tuple[str, ...] | None = None,
        date: Item | None = None,
        query: Select[Any] = FACT_ROWS,
        parameters: Item | None = None,
    ) -> list[Item]:
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
        return self.read(query, parameters)

    def get(self, entity_id: UUID) -> Entity:
        return self.events.repository.get(entity_id)
