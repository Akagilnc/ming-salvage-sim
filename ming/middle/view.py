"""往外的口：按字段、按身份交回已落事实，不摘要。

皇帝身份只见一条「接不住」，不含模型原文与失败点；对账身份见全量字段。
"""

from typing import Literal

from pydantic import BaseModel

from ming.ledger import Ledger

Identity = Literal["emperor", "audit"]


class FactView(BaseModel):
    kind: str
    emperor_words: str
    detail: dict[str, str | int | list[str]]


def project(ledger: Ledger, identity: Identity) -> list[FactView]:
    affairs = [
        FactView(
            kind="affair",
            emperor_words=a["emperor_words"],
            detail={"assignees": a["assignees"], **a["detail"]},
        )
        for a in ledger.affairs()
    ]
    numbers = [
        FactView(
            kind=n["item"],
            emperor_words=n["emperor_words"],
            detail={"amount": n["amount"], **n["detail"]},
        )
        for n in ledger.numbers()
    ]
    texts = [
        FactView(
            kind=t["kind"],
            emperor_words=t["emperor_words"],
            detail=t["detail"] if identity == "audit" else {},
        )
        for t in ledger.texts()
    ]
    return affairs + numbers + texts
