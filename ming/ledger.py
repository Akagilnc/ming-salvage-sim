"""Entities own their events; ORM query rows and event streams commit together.

A single row shape holds people, accounts and other entities without duplicating
persistence rules. Opening data remains intact; this slice records nominal orders.
"""

from pathlib import Path
from typing import Any, cast
from uuid import UUID

from eventsourcing.application import Application
from eventsourcing.domain import Aggregate, event
from eventsourcing.system import NotificationLogReader
from eventsourcing_sqlalchemy.recorders import SQLAlchemyApplicationRecorder
from sqlalchemy import JSON, Engine, Uuid, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Item = dict[str, Any]


class Entity(Aggregate):
    @event("Created")
    def __init__(self, kind: str, key: str, source: str, data: Item) -> None:
        self.kind, self.key, self.source, self.data = kind, key, source, data
        self.events: list[Item] = []

    @event("Recorded")
    def record(self, kind: str, emperor_words: str, detail: Item) -> None:
        self.events.append(
            {"kind": kind, "emperor_words": emperor_words, "detail": detail}
        )

    def snapshot(self) -> Item:
        return {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "source": self.source,
            "data": self.data,
            "events": self.events,
        }


class Base(DeclarativeBase):
    pass


class EntityRow(Base):
    __tablename__ = "entities"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str]
    key: Mapped[str]
    source: Mapped[str]
    data: Mapped[Item] = mapped_column(JSON)
    events: Mapped[list[Item]] = mapped_column(JSON)

    def snapshot(self) -> Item:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Ledger(Application[UUID]):
    def __init__(self, db_path: Path) -> None:
        super().__init__(
            env={
                "PERSISTENCE_MODULE": "eventsourcing_sqlalchemy",
                "SQLALCHEMY_URL": f"sqlite:///{db_path}",
            }
        )
        self.sql = cast(SQLAlchemyApplicationRecorder, self.recorder)
        Base.metadata.create_all(cast(Engine, self.sql.datastore.engine))

    def commit(self, entities: list[Entity]) -> None:
        with self.sql.transaction() as session:
            for entity in entities:
                session.merge(EntityRow(**entity.snapshot()))
            self.save(*entities)

    def entities(self, replay: bool = False) -> list[Item]:
        if replay:
            notifications = NotificationLogReader(self.notification_log).read(start=1)
            ids = dict.fromkeys(cast(UUID, n.originator_id) for n in notifications)
            return [self.get(entity_id).snapshot() for entity_id in ids]
        with self.sql.transaction(commit=False) as session:
            return [r.snapshot() for r in session.scalars(select(EntityRow))]

    def get(self, entity_id: UUID) -> Entity:
        return self.repository.get(entity_id)
