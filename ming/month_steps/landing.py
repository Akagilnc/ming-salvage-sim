"""Translate the final monthly timeline once and land the complete declaration."""

import json

from ming.middle.court import Court
from ming.middle.concepts import ACTING, AUDIENCE, DECREE_EVENT, DISCOVERED, HANDLER, HELD, IMPERIAL_PUSH, INTERIM, MONTH_FINAL, SECRET
from ming.middle.invoke import ModelSource
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.month_work import COST_RULES


class Landing:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = court.translation_agent(
            Declaration,
            "\n".join(((CONTENT / "prompts/month_translate.md").read_text(), COST_RULES, SECRET, HANDLER, ACTING, INTERIM, DISCOVERED, AUDIENCE, DECREE_EVENT, HELD, MONTH_FINAL, IMPERIAL_PUSH)),
            model=model,
        )

    async def run(self) -> None:
        calendar = self.court.calendar()
        if self.court.products(calendar.id, kind=("landed", "unhandled")):
            return
        declarations = self.court.products(calendar.id, kind="declaration")
        if not declarations:
            result = await self.court.translate(
                self.agent,
                json.dumps({
                    "date": calendar.data, "scope": "month",
                    "month_final": self.court.products(calendar.id, kind="month_final")[0].detail["output"],
                    "decrees": self.court.landing_materials(),
                }, ensure_ascii=False),
                calendar.id,
            )
            self.court.record_product(calendar.id, "declaration", {
                "result": result.model_dump(mode="json"), "unhandled": isinstance(result, Unhandled),
            })
            declarations = self.court.products(calendar.id, kind="declaration")
        product = declarations[0].detail
        self.court.land(
            (Unhandled if product["unhandled"] else Declaration).model_validate(product["result"]),
            calendar.id, monthly="landed",
        )
