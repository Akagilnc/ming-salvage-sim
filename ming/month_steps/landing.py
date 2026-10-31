"""Translate the final monthly timeline once and land the complete declaration."""

import json
from collections.abc import Callable

from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.concepts import ACTING, AUDIENCE, DECREE_EVENT, DISCOVERED, HANDLER, HELD, IMPERIAL_PUSH, INTERIM, MONTH_FINAL, SECRET
from ming.middle.translate import declaration_agent
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.month_work import COST_RULES
from ming.middle.view import EntityView


class Landing:
    agent = declaration_agent(
        Declaration,
        "\n".join(((CONTENT / "prompts/month_translate.md").read_text(), COST_RULES, SECRET, HANDLER, ACTING, INTERIM, DISCOVERED, AUDIENCE, DECREE_EVENT, HELD, MONTH_FINAL, IMPERIAL_PUSH)),
    )

    def __init__(self, court: Court, model: Callable[[], Model]) -> None:
        self.court, self.model = court, model

    async def run(self, calendar: EntityView) -> None:
        if self.court.has_product(calendar.id, ("landed", "unhandled"), date=calendar.data):
            return
        declarations = self.court.products(calendar.id, kind="declaration", date=calendar.data)
        if not declarations:
            result = await self.court.translate(
                self.agent,
                json.dumps({
                    "date": calendar.data, "scope": "month",
                    "month_final": self.court.products(calendar.id, kind="month_final", date=calendar.data)[0].detail["output"],
                    "decrees": self.court.landing_materials(date=calendar.data),
                }, ensure_ascii=False),
                calendar.id, model=self.model(),
            )
            product: dict[str, object] = {"result": result.model_dump(mode="json"), "unhandled": isinstance(result, Unhandled)}
            self.court.record_product(calendar.id, "declaration", product)
        else:
            product = declarations[0].detail
        self.court.land(
            (Unhandled if product["unhandled"] else Declaration).model_validate(product["result"]),
            calendar.id, monthly="landed",
        )
