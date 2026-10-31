"""The model's single identity-scoped record tool."""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext

from ming.middle.view import Identity

if TYPE_CHECKING:
    from ming.middle.court import Court
    from ming.ledger import Ledger


class RecordMonth(BaseModel):
    year: int
    month: int


@dataclass
class Materials:
    court: "Court"
    identity: Identity


@dataclass
class TranslationMaterials(Materials):
    source: UUID
    ledger: "Ledger"


async def read_records(
    ctx: RunContext[Materials], kind: str | None = None,
    key: str | list[str] | None = None, date: RecordMonth | None = None,
) -> dict[str, object]:
    """按输入 catalogue 取阅。须带类、正名或日期，不空参读全账。

    Args:
        kind: 实体类；只给类返回正名与事件数清单，不给全文。office 或 incumbency 点名查官职与现任。
        key: 一个或多个账本正名或别名；点名才取实体数据与可读事件全文。
        date: 月份（year、month）；点名时限定事件月份，否则列该月有事件的实体。
    官职结果 status：occupied 有正任，vacant 此缺现无人在任，acting 无正任而有暂署（暂署含义见共同概念）；
    appointments 给正任 holders、暂署 acting。territory_required 须带属地，territories 给候选属地，pairs 给已解析的官职/属地组合；
    office_not_found 无此官职，names_and_aliases 给相近候选；not_found 未找到，不表示空缺。
    """
    return ctx.deps.court.read.query(
        ctx.deps.identity, kind, key, date.model_dump() if date is not None else None,
        numeric=isinstance(ctx.deps, TranslationMaterials),
    )
