"""中间层门面：一句皇帝原话进（转译→分派→落账），往外的口按身份出。"""

from pathlib import Path

from pydantic_ai.models import Model

from ming.ledger import Ledger
from ming.middle.dispatch import dispatch
from ming.middle.translate import build_agent, translate
from ming.middle.view import FactView, Identity, project


class Court:
    def __init__(self, db_path: Path, model: Model) -> None:
        self._ledger = Ledger(db_path)
        self._agent = build_agent(model)

    def handle(self, emperor_words: str, scene: str = "") -> None:
        dispatch(self._ledger, translate(self._agent, emperor_words, scene), emperor_words)

    def facts(self, identity: Identity) -> list[FactView]:
        return project(self._ledger, identity)
