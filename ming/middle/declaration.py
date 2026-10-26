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
    entity_id: UUID
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


class MonthlyFunding(StrictModel):
    amount: float = Field(strict=True, allow_inf_nan=False, description="每月从出款库付出的正数专款，两数；零为停拨。")
    account: str = Field(description="出款账户的账本正名。")
    until: FiscalEnd | None = Field(default=None, description="止于此月（含）；过期不再应付，无止期一直付。")


class PaymentPolicy(StrictModel):
    factor: float = Field(
        default=1,
        strict=True,
        allow_inf_nan=False,
        description="应付保留比例；折半为0.5，减去部分不记欠。",
    )
    defer: float = Field(
        default=0, strict=True, allow_inf_nan=False, description="先应用 factor，再将应付中此比例暂欠；未付仍记欠。factor、defer 均由引擎夹到0–1。"
    )
    until: FiscalEnd | None = Field(
        default=None, description="止期含当月；过期回原额，无止期一直有效。"
    )


class Change(StrictModel):
    field: str
    value: Any = Field(description="任意 JSON 值；按输入 allowed_fields 中（实体类型, field）对应行的含义、单位、mode（value 新值、delta 增减）、bounds（落账范围）与 numeric 填写。")
    purpose: Literal["补欠", "当月饷", "犒赏", "专项"] | None = Field(
        default=None,
        description="账户付军队或财政科目必填：补欠冲减欠额且以欠额封顶；当月饷计当月已付且以本月未付封顶；犒赏、专项不按义务封顶。",
    )
    counterpart: EntityRef | None = Field(
        default=None,
        description="钱粮另一边的实体引用；每笔只声明付方一次，收方由引擎按实际金额记账，不必另写 fact。无出处收入可不填。",
    )


DecreeRef = Annotated[
    int | None,
    Field(
        default=None,
        description="来源旨意：整夜本份 decrees 的零基下标；月末输入 decrees 的零基下标，无所属旨意省略。",
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
        default=False, description="布尔值，含义见 discovered。"
    )
    changes: list[Change]
    text: str = Field(
        description=(
            "发生的事实，原文记在这个实体上；没有字段变化也可以只记文字。密令实况见 discovered。"
        )
    )


class Report(EntityRef):
    text: str
    audience: Literal["public", "official"] = Field(description="可见范围，含义见 audience。")


class DecreeEvent(StrictModel):
    decree: DecreeRef
    kind: Literal["handled", "completed"] = Field(
        description="经办或办结，含义见 DecreeEvent。"
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
    text: str = Field(description="定稿全文，原样保留；含义见成旨。")
    origin: Literal["emperor", "minister"] = Field(description="旨意来历，见字段表 decree.origin。")
    secret: bool = Field(
        description="布尔值，含义见密令。"
    )
    handler: str | None = Field(
        default=None,
        description="密令承办人的人物账本正名，明发旨意为 null；含义见承办人。",
    )
    turn: int = Field(
        ge=1,
        description="成旨轮次，按输入 turns 从 1 起数；引擎取此轮殿上名单记知情。",
    )
    endorsements: list[Endorsement] = Field(default_factory=list[Endorsement])
    interim: bool = Field(default=False, description="布尔值，含义见中旨。")
    people: list[str] = Field(
        description="人物账本正名列表，含义见知情。"
    )


class NightDeclaration(Declaration):
    decrees: list[Decree]
