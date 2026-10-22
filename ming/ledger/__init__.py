"""The event store and its synchronous, rebuildable query projection.

Calendar/night callers demonstrate the pattern: commit aggregates, then read only
matching rows/facts. No caller refreshes tables or carries a parallel event list.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from eventsourcing.system import SingleThreadedRunner, System
from eventsourcing.application import LRUCache
from eventsourcing_sqlalchemy.recorders import SQLAlchemyApplicationRecorder
from sqlalchemy import Engine, Integer, func, literal_column, or_, select, tuple_
from sqlalchemy.orm import aliased

from ming.ledger.domain import Entity as Entity, Item as Item
from ming.ledger.projection import Events, ReadModel
from ming.ledger.tables import Base, EntityRow, FactRow


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
            # A rollback must not leave uncommitted aggregate state in the cache.
            cache = self.events.repository.cache
            if isinstance(cache, LRUCache):
                cache.clear()
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

    def entities(
        self,
        *,
        kind: str | tuple[str, ...] | None = None,
        key: str | None = None,
        entity_id: UUID | None = None,
        night: str | None = None,
        sourced: bool = False,
    ) -> list[Item]:
        query = select(EntityRow)
        if kind is not None:
            query = query.where(
                EntityRow.kind.in_(kind)
                if isinstance(kind, tuple)
                else EntityRow.kind == kind
            )
        if key is not None:
            query = query.where(EntityRow.key == key)
        if entity_id is not None:
            query = query.where(EntityRow.id == entity_id)
        if sourced:
            query = query.where(EntityRow.source != "")
        if night == "pending":
            query = query.where(
                EntityRow.data["closed"].as_boolean().is_(True),
                ~select(FactRow.position)
                .where(
                    FactRow.entity_id == EntityRow.id,
                    FactRow.kind.in_(("translated", "unhandled")),
                )
                .exists(),
            )
        order = literal_column("rowid", type_=Integer())
        query = query.order_by(order.desc() if night == "latest" else order)
        if night == "latest":
            query = query.limit(1)
        with self.sql.transaction(commit=False) as session:
            return [r.snapshot() for r in session.scalars(query)]

    def facts(
        self,
        *,
        entity_id: UUID | None = None,
        kind: str | tuple[str, ...] | None = None,
        date: Item | None = None,
        visibility: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
        mode: str | None = None,
    ) -> list[Item]:
        query = (
            select(FactRow)
            .join(EntityRow, EntityRow.id == FactRow.entity_id)
            .order_by(literal_column("entities.rowid"), FactRow.position)
        )
        if entity_id is not None:
            query = query.where(FactRow.entity_id == entity_id)
        if kind is not None:
            query = query.where(
                FactRow.kind.in_(kind)
                if isinstance(kind, tuple)
                else FactRow.kind == kind
            )
        if date is not None:
            query = query.where(FactRow.date == date)
        if mode == "interactions":
            query = query.where(
                FactRow.position.in_(
                    select(func.max(FactRow.position))
                    .where(FactRow.kind == "interaction")
                    .group_by(FactRow.detail["key"].as_string())
                ),
                or_(
                    FactRow.detail["action"].as_string() != "choose",
                    FactRow.detail["status"].as_string() != "done",
                ),
            )
        if mode == "latest":
            query = query.order_by(None).order_by(FactRow.position.desc()).limit(1)
        if visibility is not None:
            query = query.where(
                or_(
                    FactRow.kind.in_(visibility[0]),
                    FactRow.detail["audience"].as_string().in_(visibility[1]),
                )
            )
        with self.sql.transaction(commit=False) as session:
            return [r.snapshot() for r in session.scalars(query)]

    def pending_petitions(self, date: Item) -> list[Item]:
        choice = aliased(FactRow)
        query = (
            select(FactRow)
            .join(EntityRow, EntityRow.id == FactRow.entity_id)
            .where(
                FactRow.kind == "petition",
                tuple_(
                    FactRow.detail["available"]["year"].as_integer(),
                    FactRow.detail["available"]["month"].as_integer(),
                )
                <= (date["year"], date["month"]),
                ~select(choice.position)
                .where(
                    choice.kind == "choice",
                    choice.detail["petition_id"].as_string()
                    == FactRow.detail["id"].as_string(),
                )
                .exists(),
            )
            .order_by(literal_column("entities.rowid"), FactRow.position)
        )
        with self.sql.transaction(commit=False) as session:
            return [row.snapshot() for row in session.scalars(query)]

    def catalogue(self) -> list[Item]:
        with self.sql.transaction(commit=False) as session:
            return [
                r.snapshot()
                for r in session.scalars(
                    select(EntityRow)
                    .where(
                        or_(
                            EntityRow.kind.in_(
                                select(EntityRow.kind)
                                .where(EntityRow.source != "")
                                .distinct()
                            ),
                            EntityRow.kind.in_(("affair", "decree")),
                        )
                    )
                    .order_by(literal_column("rowid"))
                )
            ]

    def get(self, entity_id: UUID) -> Entity:
        return self.events.repository.get(entity_id)
