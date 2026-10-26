"""Month user: fill the first missing durable product on one monthly timeline."""

import asyncio
from collections.abc import Callable
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, TextUpdate, gather_or_raise
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.simulation import Simulations
from ming.month_steps.petitions import Inbox
from ming.month_steps.landing import Landing
from ming.month_steps.gazette import Gazette
from ming.month_steps.sources import Sources
from ming.month_steps.secrets import Secrets


class Month:
    def __init__(
        self, court: Court, model: ModelSource,
        on_delta: Callable[[TextUpdate], None] | None = None,
    ) -> None:
        self.court = court
        self.deliberations = Deliberations(court, model)
        self.simulations = Simulations(court, model)
        self.inbox = Inbox(court)
        self.landing = Landing(court, model)
        self.gazette = Gazette(court, model, on_delta)
        self.sources = Sources(court, model)
        self.secrets = Secrets(court, model)
        self.lock = asyncio.Lock()

    def opened(self) -> bool:
        return bool(self.court.products(self.court.calendar().id, kind="month_open"))

    def open(self) -> None:
        if not self.opened():
            self.court.record_product(self.court.calendar().id, "month_open", {
                "entities": [e.model_dump(mode="json") for e in self.court.entities("emperor")],
            })

    def petitions(self) -> list[PendingPetition]:
        return self.inbox.petitions()

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    async def resume(
        self, *, speculative: bool = False, petition_id: str | None = None,
    ) -> list[PendingPetition]:
        # A click records its choice immediately. Shared finalization belongs to
        # the month action, never to one question or a second round of choices.
        if petition_id is not None:
            return self.petitions()
        date = self.court.calendar().data
        async with self.lock:
            if date != self.court.calendar().data:
                return self.petitions()
            calendar = self.court.calendar()
            public = [d for d in self.court.current_decrees() if not d.data["secret"]]
            pushes = self.court.pending_pushes()
            await gather_or_raise(
                *(self.deliberations.run(d, calendar.id) for d in public),
                *(self.deliberations.run(d, calendar.id, decision) for d, decision in pushes),
            )
            if speculative or not self.opened():
                return self.petitions()
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            if self.petitions() and not self.court.products(calendar.id, kind="month_draft"):
                return self.petitions()
            await self.simulations.draft()
            self.simulations.speculate()
            if self.petitions():
                return self.petitions()
            await self.simulations.final()
            await self.landing.run()
            self.court.settle_accounts()
            self.court.settle_journeys()
            self.secrets.accumulate()
            await gather_or_raise(
                self.gazette.run(), self.sources.urgent(),
                *(self.sources.impeach(f) for f in self.court.entities("audit", kind="faction")),
                *(self.secrets.report(d) for d in self.court.errands()),
            )
            self.court.advance_month()
            return self.petitions()

    async def advance(self) -> list[PendingPetition]:
        self.open()
        return await self.resume()
