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
        kind: 实体类；只给类返回正名与事件数清单，不给全文。
        key: 一个或多个账本正名或别名；点名才取实体数据与可读事件全文。
        date: 月份（year、month）；点名时限定事件月份，否则列该月有事件的实体。
    """
    if kind is None and not key and date is None:
        return {"status": "query_required", "message": "须带类、正名或日期之一，目录见输入"}
    month = date.model_dump() if date is not None else None
    catalogue = ctx.deps.court.record_catalogue(ctx.deps.identity, month)
    selected = [e for e in catalogue if kind is None or e["kind"] == kind]
    keys = [key] if isinstance(key, str) else key
    names = ctx.deps.court.catalogue(selected)
    resolved = {
        value: ([value] if any(value in entries for entries in names.values()) else
                list(dict.fromkeys(name for entries in names.values() for name, aliases in entries.items()
                                   if value in aliases)))
        for value in keys or []
    }
    if (kind is not None and not selected) or any(len(v) != 1 for v in resolved.values()) or (
        ctx.deps.identity == "translation" and date is not None
    ):
        candidates = matching_names(names, keys or [])
        return {
            "status": "not_found", "message": "未找到",
            **({"names_and_aliases": candidates} if candidates else {}),
        }
    if not keys:
        return {"catalogue": [e for e in selected if date is None or e["event_count"]]}
    return character_input(
        await ctx.deps.court.read_records(ctx.deps.identity, kind, [v[0] for v in resolved.values()], month)
    )
