"""Shared model input and persisted product types, not a second month driver."""

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import RunContext

from ming.middle.court import Court
from ming.middle.declaration import Petition, StrictModel
from ming.middle.view import Identity, character_input


class Deliberation(StrictModel):
    text: str
    verdict: Literal["准", "驳", "中旨亦不可颁"]


class Simulation(StrictModel):
    text: str
    petitions: list[Petition]
    month_end: bool


@dataclass
class Materials:
    court: Court
    identity: Identity


async def read_records(
    ctx: RunContext[Materials], kind: str | None = None, key: str | None = None
) -> dict[str, object]:
    """按类型与正名取本身份材料；空参取全部可读材料，含各衙门呈报的文字。"""
    return character_input(
        await ctx.deps.court.read_records(ctx.deps.identity, kind, key)
    )


def prompt(court: Court, identity: Identity, context: Any) -> str:
    return json.dumps(
        character_input(
            {
                "date": court.calendar().data,
                "context": context,
                "catalogue": [
                    {"kind": e.kind, "key": e.key} for e in court.entities(identity)
                ],
            }
        ),
        ensure_ascii=False,
    )
