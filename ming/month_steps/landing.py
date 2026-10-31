"""Translate the final monthly timeline once and land the complete declaration."""

import json
from collections.abc import Callable
from typing import Any

from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.concepts import ACTING, AUDIENCE, DECREE_EVENT, DISCOVERED, HANDLER, HELD, IMPERIAL_PUSH, INTERIM, MONTH_FINAL, SECRET
from ming.middle.translate import declaration_agent
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.month_steps.materials import COST_RULES, landing_materials
from ming.middle.view import EntityView
from ming.month_steps.products import record_product


class Landing:
    agent = declaration_agent(
        Declaration,
        "\n".join(((CONTENT / "prompts/month_translate.md").read_text(), COST_RULES, SECRET, HANDLER, ACTING, INTERIM, DISCOVERED, AUDIENCE, DECREE_EVENT, HELD, MONTH_FINAL, IMPERIAL_PUSH)),
    )

    def __init__(self, court: Court, model: Callable[[], Model]) -> None:
        self.court, self.model = court, model

    async def run(self, calendar: EntityView, month_final: dict[str, Any] | None = None) -> None:
        if self.court.read.has_facts(calendar.id, ("landed", "unhandled"), date=calendar.data):
            return
        declarations = self.court.read.facts("audit", entity_id=calendar.id, kind="declaration", date=calendar.data)
        recorded = None
        if not declarations:
            result = await self.court.translate(
                self.agent,
                json.dumps({
                    "date": calendar.data, "scope": "month",
                    "month_final": month_final if month_final is not None else self.court.read.facts("audit", entity_id=calendar.id, kind="month_final", date=calendar.data)[0].detail["output"],
                    "decrees": landing_materials(self.court, date=calendar.data),
                }, ensure_ascii=False),
                calendar.id, model=self.model(),
            )
            product: dict[str, object] = {"result": result.declaration.model_dump(mode="json"), "unhandled": isinstance(result.declaration, Unhandled)}
            recorded = record_product(self.court, calendar.id, "declaration", {**product, "date": calendar.data})
        else:
            product = declarations[0].detail
            result = self.court.restore_declaration(
                (Unhandled if product["unhandled"] else Declaration).model_validate(product["result"]), calendar.id,
            )
        self.court.land(result, recorded=recorded, monthly="landed")
