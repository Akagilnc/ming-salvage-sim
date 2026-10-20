"""One entity/field declaration for immediate facts and monthly consequences."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityRef(StrictModel):
    entity_type: str
    entity: str


class Petition(StrictModel):
    text: str
    options: list[str] = Field(min_length=1)


class PendingPetition(Petition):
    id: UUID
    route_id: UUID
    entity_id: UUID
    round: int


class Change(StrictModel):
    field: str
    value: Any
    counterpart: EntityRef | None = Field(
        default=None,
        description="钱粮另一边；必须也在本份 facts 中，两边带符号增减成对。无出处收入可不填。",
    )


class Fact(StrictModel):
    entity_type: str = Field(description="账本实体类型，如 person、army、affair")
    entity: str = Field(description="实体的账本正名或新实体的名字")
    create: bool = Field(description="是否新建；已有实体填 false")
    affair: str | None = Field(
        default=None,
        description="本条后果所属事务的正名；可指同份声明新建的 affair，无所属事务可省略。",
    )
    changes: list[Change]
    audience: Literal["world", "public", "official"] = "world"
    text: str = Field(
        description="发生的事实，原文记在这个实体上；没有字段变化也可以只记文字"
    )


class Declaration(StrictModel):
    facts: list[Fact]


class Decree(StrictModel):
    text: str = Field(description="皇帝已经认可的圣旨定稿全文，原样保留")
    origin: Literal["emperor", "minister"]
    people: list[str] = Field(
        description=(
            "旨意涉及的人：旨意所及对象，以及戏文中实际拟旨、宣读或领旨的经手者；"
            "均用账本正名，旨意事件记入这些人的履历（经手即知）。"
            "不按殿上名单扩散；仅旁听、被提到或拟在日后经手，不因此算实际经手者。"
        )
    )


class NightDeclaration(Declaration):
    decrees: list[Decree]
