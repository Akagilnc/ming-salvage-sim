"""Translate the final monthly timeline once and land the complete declaration."""

import json

from ming.middle.court import Court
from ming.middle.invoke import ModelSource
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.month_work import COST_RULES


class Landing:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = court.translation_agent(
            Declaration, (CONTENT / "prompts/month_translate.md").read_text() + COST_RULES,
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
                    "decrees": [
                        {"decree": d.model_dump(mode="json"), "mode": mode,
                         "prior_interim": self.court.prior_interim(d.id),
                         "deliberations": [f.model_dump(mode="json") for f in self.court.products(d.id, kind=("deliberation", "choice"))]}
                        for d, mode in self.court.landing_sources()
                    ],
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
