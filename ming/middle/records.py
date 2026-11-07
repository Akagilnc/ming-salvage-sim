"""The model's single identity-scoped record tool."""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext

from ming.middle.view import Identity
from ming.middle.record_pages import RecordScope

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
    *, scope: RecordScope | None = None,
) -> dict[str, object]:
    """空参查根目录，按类别和既有上层筛选，或点正名直达；超出单次预算可续取。

    kind 是实体类：office 官职，territory 属地，person 人物，account 账户，night 起居录；其他可查类见根目录。office 或 incumbency 点名查官职与现任。
    key 是一个或多个账本正名或别名；点名才取实体数据与可读事件全文。date 是月份（year、month）；点名时限定事件月份，否则列该月有事件的实体。
    scope 在给定 kind 下筛目录：office 用 department（衙门），territory 用 region（账本地区）、level（属地级别）；与 key 分开，其他组合返回 invalid_scope。
    字段的 read 放入 scope.read 取大字段；next 放入 scope.after 续页，保留 scope.read 及其他查询参数不变；换字段时换 read 并清空 after。没有 next 即本次取阅结束。
    字符串以 text 接齐，数组以 items 追加，对象以 object 合并；fragment.text 是单条 JSON 的片段，接齐再解码。
    官职结果 status：occupied 有正任，vacant 此缺现无人在任，acting 无正任而有暂署（暂署含义见共同概念）；
    appointments 给正任 holders、暂署 acting 及对应历史的 entity_id；批查的 facts 按 entity_id 对应官缺。territory_required 须带属地，territories 给候选属地，pairs 给已解析的官职/属地组合；
    office_not_found 无此官职，names_and_aliases 给相近候选；not_found 未找到，不表示空缺。
    """
    return ctx.deps.court.read.query(
        ctx.deps.identity, kind, key, date.model_dump() if date is not None else None,
        options=(scope or RecordScope(), isinstance(ctx.deps, TranslationMaterials)),
    )
