"""Parallel translation, then ordered per-decree landing and world last."""

import json
from uuid import UUID

from ming.middle.court import Court
from ming.middle.invoke import ModelSource, gather_or_raise
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.month_work import COST_RULES
from ming.middle.view import EntityView


class Landing:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = court.translation_agent(
            Declaration, (CONTENT / "prompts/month_translate.md").read_text() + COST_RULES,
            model=model,
        )

    async def translate(
        self, source: EntityView, route: UUID, others: list[EntityView]
    ) -> None:
        if self.court.products(source.id, kind=("declaration", "landed", "attempted", "unhandled")):
            return
        result = await self.court.translate(
            self.agent,
            json.dumps(
                {
                    "date": self.court.calendar().data,
                    "source": source.model_dump(mode="json"),
                    "scope": "decree" if source.kind == "decree" else "world",
                    "prior_interim": self.court.prior_interim(source.id),
                    "deliberation": [
                        f.model_dump(mode="json")
                        for f in self.court.products(
                            source.id, kind=("deliberation", "choice")
                        )
                    ],
                    "others": [
                        {
                            "decree": other.model_dump(mode="json"),
                            "deliberation": [
                                f.model_dump(mode="json")
                                for f in self.court.products(
                                    other.id, kind=("deliberation", "choice")
                                )
                            ],
                        }
                        for other in others
                    ],
                    "simulation": [
                        f.detail["output"]
                        for f in self.court.products(route, kind="simulation")
                    ],
                },
                ensure_ascii=False,
            ),
            source.id,
        )
        self.court.record_product(
            source.id,
            "declaration",
            {
                "result": result.model_dump(),
                "unhandled": isinstance(result, Unhandled),
            },
        )

    async def run(self) -> None:
        sources = self.court.landing_sources()
        await gather_or_raise(
            *(
                self.translate(
                    source,
                    route,
                    [
                        other
                        for other, _other_route, _mode in sources
                        if other.kind == "decree" and other.id != source.id
                    ],
                )
                for source, route, _mode in sources
            )
        )
        for source, _route, mode in sources:
            if self.court.products(source.id, kind=("landed", "attempted", "unhandled")):
                continue
            declaration = self.court.products(source.id, kind="declaration")[0].detail
            self.court.land(
                (Unhandled if declaration["unhandled"] else Declaration).model_validate(
                    declaration["result"]
                ),
                source.id,
                monthly=mode,
            )
