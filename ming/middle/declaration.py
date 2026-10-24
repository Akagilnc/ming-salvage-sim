"""One entity/field declaration for immediate facts and monthly consequences."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


LandingMode = Literal["landed", "attempted"]


class Unhandled(BaseModel):
    model_text: str
    failure_point: str


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
    segment_id: UUID
    available: dict[str, Any]
    blocking: bool
    source: str
    signer: str | None = None
    target: str | None = None
    revision_of: UUID | None = None
    ordinal: int = 0


class FiscalEnd(StrictModel):
    year: int
    month: int = Field(ge=1, le=12)


class PaymentPolicy(StrictModel):
    factor: float = Field(
        default=1,
        strict=True,
        allow_inf_nan=False,
        description="应付保留比例；折半为0.5，减去部分不记欠。",
    )
    defer: float = Field(
        default=0, strict=True, allow_inf_nan=False, description="应付中暂欠的比例，未付仍记欠。"
    )
    until: FiscalEnd | None = Field(
        default=None, description="止期含当月；过期回原额，无止期一直有效。"
    )


class Change(StrictModel):
    field: str
    value: Any
    purpose: Literal["补欠", "当月饷", "犒赏", "专项"] | None = Field(
        default=None,
        description="账户付给军队或财政科目的款须写名目；value仍为带符号的两数。",
    )
    counterpart: EntityRef | None = Field(
        default=None,
        description="钱粮另一边的实体引用；每笔只声明付方一次，收方由引擎按实际金额记账，不必另写 fact。无出处收入可不填。",
    )


DecreeRef = Annotated[
    int | None,
    Field(
        default=None,
        description="来源旨意：整夜本份 decrees 的零基下标；月末本旨省略，使用当前旨意来源。",
    ),
]


class Fact(StrictModel):
    entity_type: str = Field(description="账本实体类型，如 person、army、affair")
    entity: str = Field(description="实体的账本正名或新实体的名字")
    create: bool = Field(description="是否新建；已有实体填 false")
    affair: str | None = Field(
        default=None,
        description="本条后果所属事务的正名；可指同份声明新建的 affair，无所属事务可省略。",
    )
    decree: DecreeRef
    discovered: bool = Field(
        default=False, description="是否为密令内部查获实情；不按有无字段变化判断。"
    )
    changes: list[Change]
    text: str = Field(
        description=(
            "发生的事实，原文记在这个实体上；没有字段变化也可以只记文字。"
            "物理实况正文只写后果，不写密令来源，密令来源只放在结构化来源关系里。"
        )
    )


class Report(EntityRef):
    text: str
    audience: Literal["public", "official"]


class DecreeEvent(StrictModel):
    decree: DecreeRef
    kind: Literal["handled", "completed"] = Field(
        description="handled：实际发生的一道传递、经办（转交、往返），每道各记一条；completed：推演已认定该差事办结，包括关联事务已成往事。无记录、接不住不算办结。没有新建事务也不算办结。"
    )
    text: str


class Declaration(StrictModel):
    facts: list[Fact]
    reports: list[Report] = Field(default_factory=list[Report])
    decree_events: list[DecreeEvent] = Field(default_factory=list[DecreeEvent])


class Endorsement(StrictModel):
    endorser: str = Field(description="背书人账本正名；皇帝亲担写御笔，担名不等于办事")
    form: Literal["会签", "当面站台", "御笔手敕"]
    source_chat_turn_id: str = Field(description="本夜实际背书发生的那一轮 id，不是夜 id")


class Decree(StrictModel):
    text: str = Field(description="皇帝已经认可的圣旨定稿全文，原样保留")
    origin: Literal["emperor", "minister"]
    secret: bool = Field(
        description="密令不明发、不经外廷。按皇帝怎么说与整夜上下文判断是否密令，不按事务类型或有没有密字判断。"
    )
    turn: int = Field(
        ge=1,
        description="皇帝认可定稿、成旨的轮次，按输入 turns 从 1 起数。只记已成旨。",
    )
    endorsements: list[Endorsement] = Field(default_factory=list[Endorsement])
    interim: bool = Field(default=False, description="皇帝明说中旨、不经内阁票拟；中旨仍是明发，经外廷议处。御笔手敕本身不等于中旨")
    people: list[str] = Field(
        description=(
            "旨意涉及的人：旨意所及对象，以及戏文中实际拟旨、宣读或领旨的经手者；"
            "均用账本正名，旨意事件记入这些人的履历（经手即知）。"
            "不按殿上名单扩散；仅旁听、被提到或拟在日后经手，不因此算实际经手者。"
        )
    )


class NightDeclaration(Declaration):
    decrees: list[Decree]
