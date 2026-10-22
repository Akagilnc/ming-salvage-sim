"""The only event-to-state rules, shared by live reads and replay."""

from typing import Any
from eventsourcing.domain import Aggregate, event

Item = dict[str, Any]


class Entity(Aggregate):
    @event("Created")
    def __init__(self, kind: str, key: str, source: str, data: Item) -> None:
        self.kind, self.key, self.source, self.data = (
            kind,
            key or str(self.id),
            source,
            data,
        )

    class Recorded(Aggregate.Event):
        kind: str
        emperor_words: str
        detail: Item
        changes: Item | None

    @event(Recorded)
    def record(
        self, kind: str, emperor_words: str, detail: Item, changes: Item | None = None
    ) -> None:
        if changes:
            self.data = {**self.data, **changes}

    def snapshot(self) -> Item:
        return {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "source": self.source,
            "data": self.data,
        }
