"""One entity/field declaration for immediate facts and monthly consequences."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Change(StrictModel):
    field: str
    value: Any


class Fact(StrictModel):
    entity_type: str = Field(description="账本实体类型，如 person、army、affair")
    entity: str = Field(description="实体的账本正名或新实体的名字")
    create: bool = Field(description="是否新建；已有实体填 false")
    changes: list[Change]
    text: str = Field(
        description="发生的事实，原文记在这个实体上；没有字段变化也可以只记文字"
    )


class Declaration(StrictModel):
    facts: list[Fact]


class Decree(StrictModel):
    text: str = Field(description="皇帝已经认可的圣旨定稿全文，原样保留")
    origin: Literal["emperor", "minister"]
    people: list[str] = Field(
        description="旨意涉及的人，账本正名；用于把旨意事件记在人身上"
    )


class NightDeclaration(Declaration):
    decrees: list[Decree]
