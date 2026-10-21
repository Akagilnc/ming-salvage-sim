"""Parallel translation, then ordered per-decree landing and world last."""

import asyncio
import json
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import Declaration, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.view import EntityView


class Landing:
    def __init__(self, court: Court) -> None:
        self.court = court
        self.agent = court.translation_agent(
            Declaration, (CONTENT / "prompts/month_translate.md").read_text()
        )

    def sources(self) -> list[tuple[EntityView, UUID]]:
        sources: list[tuple[EntityView, UUID]] = []
        for decree in self.court.entities("audit"):
            if decree.kind != "decree":
                continue
            products = self.court.products(decree.id)
            verdict = next(
                (f.detail for f in products if f.kind == "deliberation"), None
            )
            choice = next(
                (f.detail for f in reversed(products) if f.kind == "choice"), None
            )
            if verdict and (
                verdict["verdict"] == "准" or (choice and choice["text"] == "强颁")
            ):
                sources.append((decree, UUID(verdict["route_id"])))
        calendar = self.court.calendar()
        return sources + [(calendar, calendar.id)]

    async def translate(
        self, source: EntityView, route: UUID, others: list[EntityView]
    ) -> None:
        if any(
            f.kind in {"declaration", "landed", "unhandled"}
            for f in self.court.products(source.id)
        ):
            return
        result = await self.court.translate(
            self.agent,
            json.dumps(
                {
                    "date": self.court.calendar().data,
                    "source": source.model_dump(mode="json"),
                    "entities": [
                        e.model_dump(mode="json")
                        for e in self.court.entities("world")
                        if e.source
                    ],
                    "scope": "只交本旨后果"
                    if source.kind == "decree"
                    else "只交世界其余变化，别重复各道旨的后果",
                    "deliberation": [
                        f.model_dump(mode="json")
                        for f in self.court.products(source.id)
                        if f.kind in {"deliberation", "choice"}
                    ],
                    "others": [
                        {
                            "decree": other.model_dump(mode="json"),
                            "deliberation": [
                                f.model_dump(mode="json")
                                for f in self.court.products(other.id)
                                if f.kind in {"deliberation", "choice"}
                            ],
                        }
                        for other in others
                    ],
                    "simulation": [
                        f.detail["output"]
                        for f in self.court.products(route)
                        if f.kind == "simulation"
                    ],
                },
                ensure_ascii=False,
            ),
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
        sources = self.sources()
        results = await asyncio.gather(
            *(
                self.translate(
                    source,
                    route,
                    [
                        other
                        for other, other_route in sources
                        if other.id != source.id and other_route == route
                    ],
                )
                for source, route in sources
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        for source, _route in sources:
            products = self.court.products(source.id)
            if any(f.kind in {"landed", "unhandled"} for f in products):
                continue
            declaration = next(f.detail for f in products if f.kind == "declaration")
            self.court.land(
                (Unhandled if declaration["unhandled"] else Declaration).model_validate(
                    declaration["result"]
                ),
                source.id,
                monthly=True,
            )
