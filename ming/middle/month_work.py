"""Shared model input and persisted product types, not a second month driver."""

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from ming.middle.court import Court
from ming.middle.declaration import Petition, StrictModel
from ming.middle.view import Identity, character_input


COST_RULES = """背书（含御笔手敕、御笔强推）本身不走代价轨，不等于中旨。
强颁与预先中旨共用代价轨：实际颁出才付皇威；相关派系／阶级满意度反应可正可负可零，中旨名声记在本旨。
预先中旨被驳也有满意度反应与中旨名声，但不执行旨意、不扣皇威；收回、留中不抹去已经发生的中旨尝试反应。
同旨背书与中旨并存只计一份代价。prior_interim 是本旨已记的中旨历史，重议不重复已付反应；后来获准或强颁只补实际颁出的皇威代价。
撤回成命交皇威、当事大臣与相关派系反应；收权罢差零毁约代价。正规被驳旨收回、留中中性。民心不是这些动作的固定代价。"""


class Deliberation(StrictModel):
    text: str
    verdict: Literal["准", "驳", "中旨亦不可颁"]


class Simulation(StrictModel):
    text: str
    petitions: list[Petition]
    month_end: bool


class RecordMonth(BaseModel):
    year: int
    month: int


@dataclass
class Materials:
    court: Court
    identity: Identity


async def read_records(
    ctx: RunContext[Materials], kind: str | None = None,
    key: str | list[str] | None = None, date: RecordMonth | None = None,
) -> dict[str, object]:
    """按输入 catalogue 取阅。须带类、正名或日期，不空参读全账。

    Args:
        kind: 实体类；只给类返回正名与事件数清单，不给全文。
        key: 一个或多个账本正名；只有点正名才取实体数据与可读事件全文。
        date: 月份（year、month，无须 id）；点名时限定事件月份，否则列该月有事件的实体与该月事件数。
    """
    if kind is None and not key and date is None:
        return {"status": "query_required", "message": "须带类、正名或日期之一，目录见输入"}
    month = date.model_dump() if date is not None else None
    catalogue = ctx.deps.court.record_catalogue(ctx.deps.identity, month)
    selected = [e for e in catalogue if kind is None or e["kind"] == kind]
    keys = [key] if isinstance(key, str) else key
    if (kind is not None and not selected) or (
        keys and not set(keys) <= {e["key"] for e in selected}
    ):
        return {
            "status": "not_found", "message": "未找到",
            "names_and_aliases": ctx.deps.court.catalogue(catalogue),
        }
    if not keys:
        return {"catalogue": [
            e for e in selected if date is None or e["event_count"]
        ]}
    return character_input(
        await ctx.deps.court.read_records(ctx.deps.identity, kind, keys, month)
    )


def prompt(court: Court, identity: Identity, context: Any) -> str:
    return json.dumps(
        character_input(
            {
                "date": court.calendar().data,
                "context": context,
                "catalogue": court.record_catalogue(identity),
            }
        ),
        ensure_ascii=False,
    )
