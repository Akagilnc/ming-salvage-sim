"""Events and derived rows commit atomically; explicit replay shares the row writer."""

from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from eventsourcing.application import Application, LocalNotificationLog
from eventsourcing.persistence import Recording
from eventsourcing_sqlalchemy.recorders import SQLAlchemyApplicationRecorder
from sqlalchemy import Engine, Select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

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

    @contextmanager
    def reading(self, replay: bool) -> Generator["Ledger"]:
        if not replay:
            yield self
            return
        rebuilt = Ledger(Path(f"file:{uuid4().hex}?mode=memory&cache=shared&uri=true"))
        try:
            log = LocalNotificationLog(self.events.recorder, section_size=1000)
            start = 1
            # Read each source page outside the destination transaction: the
            # recorder's thread-scoped transaction otherwise selects that DB.
            while notifications := log.select(start=start, limit=1000):
                recordings = [Recording(self.events.mapper.to_domain_event(n), n) for n in notifications]
                entities = [self.get(r.domain_event.originator_id) for r in recordings
                            if isinstance(r.domain_event, Entity.Created)]
                with rebuilt.sql.transaction() as session:
                    rebuilt.write_rows(session, entities, recordings)
                start = notifications[-1].id + 1
            yield rebuilt
        finally:
            rebuilt.close()

    def read(self, query: Select[Any], parameters: Mapping[str, Any] | None = None) -> tuple[Item, ...]:
        """Query the committed read tables for this request."""
        with self.sql.transaction(commit=False) as session:
            return tuple(dict(row) for row in session.execute(query, parameters).mappings())

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
        return self.read(query, parameters)

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
        return self.read(query, parameters)

    def get(self, entity_id: UUID) -> Entity:
        return self.events.repository.get(entity_id)
