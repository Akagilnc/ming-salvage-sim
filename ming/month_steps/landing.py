"""Translate the final monthly timeline once and land the complete declaration."""

import json

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

    async def run(self, calendar: EntityView) -> None:
        if self.court.has_product(calendar.id, ("landed", "unhandled"), date=calendar.data):
            return
        declarations = self.court.products(calendar.id, kind="declaration", date=calendar.data)
        recorded = None
        if not declarations:
            result = await self.court.translate(
                self.agent,
                json.dumps({
                    "date": calendar.data, "scope": "month",
                    "month_final": self.court.products(calendar.id, kind="month_final", date=calendar.data)[0].detail["output"],
                    "decrees": self.court.landing_materials(date=calendar.data),
                }, ensure_ascii=False),
                calendar.id,
            )
            product: dict[str, object] = {"result": result.declaration.model_dump(mode="json"), "unhandled": isinstance(result.declaration, Unhandled)}
            recorded = self.court.record_product(calendar.id, "declaration", product)
        else:
            product = declarations[0].detail
            result = self.court.restore_declaration(
                (Unhandled if product["unhandled"] else Declaration).model_validate(product["result"]), calendar.id,
            )
        self.court.land(result, recorded=recorded, monthly="landed")
