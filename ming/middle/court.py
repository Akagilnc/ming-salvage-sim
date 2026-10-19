"""The ledger's one door: new game, continue game, land orders and read by identity."""

from pathlib import Path
from uuid import uuid4

from pydantic_ai.models import Model

from ming.ledger import Ledger
from ming.middle.dispatch import dispatch
from ming.middle.opening import CONTENT, import_opening
from ming.middle.translate import build_agent, translate
from ming.middle.view import EntityView, FactView, Identity, entities, project


class Court:
    def __init__(self, db_path: Path, model: Model) -> None:
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        self.db_path = db_path
        self._ledger = Ledger(db_path)
        self._agent = build_agent(model, self._ledger)

    @classmethod
    def new_game(
        cls, directory: Path, model: Model, content: Path = CONTENT
    ) -> "Court":
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4()}.sqlite"
        path.touch(exist_ok=False)
        court = cls(path, model)
        try:
            import_opening(court._ledger, content)
        except Exception:
            court.close()
            raise
        return court

    def handle(self, emperor_words: str, scene: str = "") -> None:
        dispatch(
            self._ledger, translate(self._agent, emperor_words, scene), emperor_words
        )

    def facts(self, identity: Identity, replay: bool = False) -> list[FactView]:
        return project(self._ledger, identity, replay)

    def entities(self, identity: Identity, replay: bool = False) -> list[EntityView]:
        return entities(self._ledger, identity, replay)

    def close(self) -> None:
        self._ledger.close()
