"""The model's single identity-scoped record tool."""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext

from ming.middle.rules import matching_names
from ming.middle.view import Identity, character_input

if TYPE_CHECKING:
    from ming.middle.court import Court


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
    if kind is None and not key and date is None:
        return {"status": "query_required", "message": "须带类、正名或日期之一，目录见输入"}
    month = date.model_dump() if date is not None else None
    identity = ctx.deps.identity
    if kind in {"office", "incumbency"} and key:
        results = [ctx.deps.court.office_record(identity, name, month)
                   for name in ([key] if isinstance(key, str) else key)]
        return results[0] if len(results) == 1 else {"offices": results}
    keys = ([key] if isinstance(key, str) else key) or None
    catalogue = ctx.deps.court.record_catalogue(identity, month, kind, keys)
    selected = [e for e in catalogue if kind is None or e["kind"] == kind]
    names = ctx.deps.court.catalogue(selected)
    resolved = {
        value: ([value] if any(value in entries for entries in names.values()) else
                list(dict.fromkeys(name for entries in names.values() for name, aliases in entries.items()
                                   if value in aliases)))
        for value in keys or []
    }
    if (kind is not None and not selected) or any(len(v) != 1 for v in resolved.values()):
        candidates = matching_names(
            ctx.deps.court.catalogue(ctx.deps.court.record_catalogue(identity, month, kind)), keys or []
        )
        return {
            "status": "not_found", "message": "未找到",
            **({"names_and_aliases": candidates} if candidates else {}),
        }
    if not keys:
        return {"catalogue": [e for e in selected if date is None or e["event_count"]]}
    result = ctx.deps.court.read_records(identity, kind, [v[0] for v in resolved.values()], month)
    return result if isinstance(ctx.deps, TranslationMaterials) else character_input(result)
