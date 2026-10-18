"""账本：五类事实，各一个 Aggregate、各一条 @event；只管存取，不知道模型存在。

一局一个 SQLite 文件，文件就是这一局。每类在本局第一次写入时建一个实例，id 由类名定。
读出的是聚合从事件重放出的状态（投影）。
"""

from pathlib import Path
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from eventsourcing.application import AggregateNotFoundError, Application
from eventsourcing.domain import Aggregate, event

Item = dict[str, Any]


class Facts(Aggregate):
    @staticmethod
    def create_id(name: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"ming/{name}")

    @event("Created")
    def __init__(self, name: str) -> None:
        self.name = name
        self.items: list[Item] = []


class NumberLedger(Facts):
    """数值账。"""

    @event("Recorded")
    def record(self, item: str, amount: int, emperor_words: str, detail: dict[str, str]) -> None:
        self.items.append({"item": item, "amount": amount, "emperor_words": emperor_words, "detail": detail})


class TextFacts(Facts):
    """文字事实。"""

    @event("Recorded")
    def record(self, kind: str, emperor_words: str, detail: dict[str, str]) -> None:
        self.items.append({"kind": kind, "emperor_words": emperor_words, "detail": detail})


class Affairs(Facts):
    """事务。"""

    @event("Recorded")
    def record(self, assignees: list[str], emperor_words: str, detail: dict[str, str]) -> None:
        self.items.append({"assignees": assignees, "emperor_words": emperor_words, "detail": detail})


class PublicStatements(Facts):
    """公开说法。本片只定义。"""

    @event("Recorded")
    def record(self, speaker: str, text: str) -> None:
        self.items.append({"speaker": speaker, "text": text})


class Sightings(Facts):
    """人物见闻。本片只定义。"""

    @event("Recorded")
    def record(self, person: str, text: str) -> None:
        self.items.append({"person": person, "text": text})


F = TypeVar("F", bound=Facts)


class Ledger(Application[UUID]):
    def __init__(self, db_path: Path) -> None:
        super().__init__(env={"PERSISTENCE_MODULE": "eventsourcing.sqlite", "SQLITE_DBNAME": str(db_path)})

    def _facts(self, cls: type[F]) -> F:
        try:
            return self.repository.get(Facts.create_id(cls.__name__))
        except AggregateNotFoundError:
            return cls(cls.__name__)

    def record_number(self, item: str, amount: int, emperor_words: str, detail: dict[str, str]) -> None:
        numbers = self._facts(NumberLedger)
        numbers.record(item, amount, emperor_words, detail)
        self.save(numbers)

    def record_text(self, kind: str, emperor_words: str, detail: dict[str, str]) -> None:
        texts = self._facts(TextFacts)
        texts.record(kind, emperor_words, detail)
        self.save(texts)

    def record_affair(self, assignees: list[str], emperor_words: str, detail: dict[str, str]) -> None:
        affairs = self._facts(Affairs)
        affairs.record(assignees, emperor_words, detail)
        self.save(affairs)

    def numbers(self) -> list[Item]:
        return list(self._facts(NumberLedger).items)

    def texts(self) -> list[Item]:
        return list(self._facts(TextFacts).items)

    def affairs(self) -> list[Item]:
        return list(self._facts(Affairs).items)
