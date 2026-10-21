"""Month user: resume the first missing ledger product, including after choices."""

import asyncio
from collections.abc import Callable
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource
from ming.middle.view import EntityView
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.simulation import Simulations
from ming.month_steps.petitions import Inbox
from ming.month_steps.landing import Landing
from ming.month_steps.gazette import Gazette


class Month:
    def __init__(
        self,
        court: Court,
        model: ModelSource,
        on_delta: Callable[[str], None] | None = None,
    ) -> None:
        self.court = court
        self.deliberations = Deliberations(court, model)
        self.simulations = Simulations(court, model)
        self.inbox = Inbox(court)
        self.landing = Landing(court)
        self.gazette = Gazette(court, model, on_delta)
        self.lock = asyncio.Lock()

    def opened(self) -> bool:
        return any(
            f.kind == "month_open"
            for f in self.court.products(self.court.calendar().id)
        )

    def open(self) -> None:
        if not self.opened():
            self.court.record_product(
                self.court.calendar().id,
                "month_open",
                {
                    "entities": [
                        e.model_dump(mode="json")
                        for e in self.court.entities("emperor")
                    ],
                    "facts": [
                        f.model_dump(mode="json") for f in self.court.facts("emperor")
                    ],
                },
            )

    def petitions(self) -> list[PendingPetition]:
        return self.inbox.petitions()

    def choose(self, petition_id: UUID, option: int) -> UUID:
        return self.inbox.choose(petition_id, option)

    def current_decrees(self) -> list[EntityView]:
        return [
            e
            for e in self.court.entities("audit")
            if e.kind == "decree"
            and any(f.kind == "decreed" for f in self.court.products(e.id))
        ]

    async def night(self, night: EntityView, decrees: list[EntityView]) -> None:
        results = await asyncio.gather(
            *(self.deliberations.run(d, night.id) for d in decrees),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        approved = [
            d.model_dump(mode="json")
            for d in decrees
            if any(
                f.kind == "deliberation" and f.detail["verdict"] == "准"
                for f in self.court.products(d.id)
            )
        ]
        await self.simulations.run(
            night,
            {
                "scope": "旨意推演",
                "decrees": approved,
                "deliberations": [
                    f.detail
                    for d in decrees
                    for f in self.court.products(d.id)
                    if f.kind == "deliberation"
                ],
            },
        )

    async def resume(self, *, speculative: bool = False) -> list[PendingPetition]:
        date = self.court.calendar().data
        async with self.lock:
            if date != self.court.calendar().data:
                return self.petitions()
            decrees = self.current_decrees()
            nights = [
                e
                for e in self.court.entities("audit")
                if e.kind == "night"
                and any(d.data["night_id"] == str(e.id) for d in decrees)
            ]
            results = await asyncio.gather(
                *(
                    self.night(
                        n, [d for d in decrees if d.data["night_id"] == str(n.id)]
                    )
                    for n in nights
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            if speculative or not self.opened():
                return self.petitions()
            if any(
                p.route_id in {n.id for n in nights}
                or (
                    not p.blocking
                    and not any(
                        f.kind == "simulation"
                        for f in self.court.products(self.court.calendar().id)
                    )
                )
                for p in self.petitions()
            ):
                return self.petitions()
            calendar = self.court.calendar()
            old = [d for d in self.deliberations.due() if d not in decrees]
            results = await asyncio.gather(
                *(self.deliberations.run(d, calendar.id) for d in old),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            await self.simulations.run(
                calendar,
                {
                    "scope": "世界推演",
                    "nights": [
                        {
                            "night_id": str(n.id),
                            "segments": [
                                f.detail["output"]
                                for f in self.court.products(n.id)
                                if f.kind == "simulation"
                            ],
                        }
                        for n in nights
                    ],
                    "reconsidered": [
                        {"decree": d.model_dump(mode="json"), "deliberation": f.detail}
                        for d in old
                        for f in self.court.products(d.id)
                        if f.kind == "deliberation" and f.detail["verdict"] == "准"
                    ],
                    "prior_choices": [
                        f.detail
                        for f in self.court.facts("audit")
                        if f.kind == "choice" and f.detail["date"] == date
                    ],
                },
            )
            if pending := self.petitions():
                return pending
            await self.landing.run()
            await self.gazette.run()
            self.court.advance_month()
            return self.petitions()

    async def advance(self) -> list[PendingPetition]:
        self.open()
        return await self.resume()
