"""Library-driven, synchronous projection: the only read-table writer."""

from typing import cast
from uuid import UUID
from eventsourcing.application import ProcessingEvent
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.domain import DomainEventProtocol
from eventsourcing.persistence import Tracking
from eventsourcing.system import Leader, ProcessApplication
from eventsourcing_sqlalchemy.recorders import SQLAlchemyApplicationRecorder
from sqlalchemy.dialects.sqlite import insert
from ming.ledger.domain import Entity
from ming.ledger.tables import EntityRow, FactRow


class Events(Leader[UUID]):
    name = "Ledger"


class ReadModel(ProcessApplication[UUID]):
    source: Events
    projecting: Entity

    def process_event(
        self, domain_event: DomainEventProtocol[UUID], tracking: Tracking
    ) -> None:
        # Resolve source state before entering a different database's transaction
        # during --replay. In live saves this simply reuses the caller's session.
        self.projecting = self.source.repository.get(domain_event.originator_id)
        with cast(SQLAlchemyApplicationRecorder, self.recorder).transaction():
            super().process_event(domain_event, tracking)

    @singledispatchmethod
    def policy(
        self,
        domain_event: DomainEventProtocol[UUID],
        processing_event: ProcessingEvent[UUID],
    ) -> None:
        # save() has already populated the library aggregate cache. On catch-up,
        # the same repository reconstitutes final state from the authoritative log.
        # No event merging rule lives here: Entity's @event methods own all of it.
        entity = self.projecting
        sql = cast(SQLAlchemyApplicationRecorder, self.recorder)
        with sql.transaction() as session:
            statement = insert(EntityRow).values(**entity.snapshot())
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[EntityRow.id],
                    set_={
                        c: getattr(statement.excluded, c)
                        for c in ("kind", "key", "source", "data")
                    },
                )
            )
            if isinstance(domain_event, Entity.Recorded):
                assert processing_event.tracking is not None
                session.add(
                    FactRow(
                        position=processing_event.tracking.notification_id,
                        entity_id=entity.id,
                        kind=domain_event.kind,
                        date=domain_event.detail.get("date"),
                        emperor_words=domain_event.emperor_words,
                        detail=domain_event.detail,
                    )
                )
