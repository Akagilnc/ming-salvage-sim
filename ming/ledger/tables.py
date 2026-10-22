"""Derived query schema. Only the projection policy writes these rows."""

from uuid import UUID
from sqlalchemy import JSON, Index, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ming.ledger.domain import Item


class Base(DeclarativeBase):
    pass


class EntityRow(Base):
    __tablename__ = "entities"
    __table_args__ = (Index("entity_kind_key", "kind", "key"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(index=True)
    key: Mapped[str]
    source: Mapped[str]
    data: Mapped[Item] = mapped_column(JSON)

    def snapshot(self) -> Item:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class FactRow(Base):
    __tablename__ = "facts"
    __table_args__ = (Index("fact_entity_kind_date", "entity_id", "kind", "date"),)
    position: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(index=True)
    date: Mapped[Item | None] = mapped_column(JSON)
    emperor_words: Mapped[str]
    detail: Mapped[Item] = mapped_column(JSON)

    def snapshot(self) -> Item:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "emperor_words": self.emperor_words,
            "detail": self.detail,
        }
