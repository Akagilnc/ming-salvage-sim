"""Translate the final monthly timeline once and land the complete declaration."""

import json
from typing import Any

from ming.middle.court import Court
from ming.middle.concepts import ACTING, AUDIENCE, DECREE_EVENT, DISCOVERED, HANDLER, HELD, IMPERIAL_PUSH, INTERIM, MONTH_FINAL, SECRET
from ming.middle.invoke import ModelSource
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.month_work import COST_RULES
from ming.middle.view import EntityView


class Landing:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = court.translation_agent(
            Declaration,
            "\n".join(((CONTENT / "prompts/month_translate.md").read_text(), COST_RULES, SECRET, HANDLER, ACTING, INTERIM, DISCOVERED, AUDIENCE, DECREE_EVENT, HELD, MONTH_FINAL, IMPERIAL_PUSH)),
            model=model,
        )

    async def run(self, calendar: EntityView, decrees: tuple[dict[str, Any], ...], final: dict[str, Any]) -> tuple[EntityView, ...]:
        if self.court.products(calendar.id, kind=("landed", "unhandled"), date=calendar.data):
            return tuple(EntityView.model_validate(d["decree"]) for d in decrees if d["mode"] is not None)
        declarations = self.court.products(calendar.id, kind="declaration", date=calendar.data)
        materials = None
        if not declarations:
            result, materials = await self.court.translate(
                self.agent,
                json.dumps({
                    "date": calendar.data, "scope": "month",
                    "month_final": final["output"],
                    "decrees": decrees,
                }, ensure_ascii=False),
                calendar=calendar, decrees=decrees,
            )
            product: dict[str, object] = {"result": result.model_dump(mode="json"), "unhandled": isinstance(result, Unhandled)}
            self.court.record_product(calendar.id, "declaration", product, date=calendar.data)
        else:
            product = declarations[0].detail
        return self.court.land(
            (Unhandled if product["unhandled"] else Declaration).model_validate(product["result"]),
            calendar.id, calendar=calendar, decrees=decrees, materials=materials,
        )
