"""Medium: read-table replay across generated ledger write sequences."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest
from hypothesis import settings, strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule
from sqlalchemy import event
from sqlalchemy.orm import Session

from ming.ledger import Entity, Ledger


class LedgerReplay(RuleBasedStateMachine):
    entities = Bundle("entities")
    values = st.integers(min_value=-10, max_value=10)

    def __init__(self):
        super().__init__()
        self.directory = TemporaryDirectory()
        self.ledger = Ledger(Path(self.directory.name) / "ledger.db")

    @rule(target=entities, value=values)
    def create_entity(self, value):
        entity = Entity("item", "", "", {"value": value})
        self.ledger.commit([entity])
        return entity.id

    @rule(entity_id=entities, value=values)
    def record_change(self, entity_id, value):
        entity = self.ledger.get(entity_id)
        entity.record("changed", "", {"value": value}, {"value": value})
        self.ledger.commit([entity])

    @rule(entity_id=entities, value=values)
    def record_fact(self, entity_id, value):
        entity = self.ledger.get(entity_id)
        entity.record("observed", "", {"date": {"turn": value}})
        self.ledger.commit([entity])

    @rule(entity_id=entities, values=st.lists(values, min_size=2, max_size=4))
    def record_batch(self, entity_id, values):
        entity = self.ledger.get(entity_id)
        for value in values:
            entity.record("changed", "", {"value": value}, {"value": value})
        self.ledger.commit([entity])

    @rule(entity_id=entities)
    def rollback_and_retry(self, entity_id):
        value = self.ledger.get(entity_id).data["value"] + 1
        # Fail at the database commit boundary, after event and read-row writes.
        interrupt = Mock(side_effect=RuntimeError("injected pre-commit failure"))
        event.listen(Session, "before_commit", interrupt)
        try:
            with pytest.raises(RuntimeError):
                self.record_change(entity_id, value)
        finally:
            event.remove(Session, "before_commit", interrupt)
        reopened = Ledger(Path(self.directory.name) / "ledger.db")
        try:
            assert reopened.entities() == self.ledger.entities()
            assert reopened.facts() == self.ledger.facts()
            assert reopened.get(entity_id).data["value"] == value - 1
        finally:
            reopened.close()
        self.rebuild_matches_live()
        self.record_change(entity_id, value)

    @invariant()
    def rebuild_matches_live(self):
        assert tuple(self.ledger.get(row["id"]).snapshot() for row in self.ledger.entities()) == self.ledger.entities()
        with self.ledger.reading(replay=True) as rebuilt:
            assert rebuilt.entities() == self.ledger.entities()
            assert rebuilt.facts() == self.ledger.facts()

    def teardown(self):
        self.ledger.close()
        self.directory.cleanup()


TestLedgerReplay = LedgerReplay.TestCase
# Short programs combine write paths without repeatedly growing long histories.
TestLedgerReplay.settings = settings(
    max_examples=20, stateful_step_count=10, deadline=None
)
