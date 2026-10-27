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

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    async def resume(
        self, *, speculative: bool = False, petition_id: str | None = None,
    ) -> tuple[PendingPetition, ...]:
        # A click records its choice immediately. Shared finalization belongs to
        # the month action, never to one question or a second round of choices.
        if petition_id is not None:
            return self.court.pending_petitions()
        date = self.court.calendar().data
        async with self.lock:
            if date != self.court.calendar().data:
                return self.court.pending_petitions()
            public = [d for d in self.court.current_decrees() if not d.data["secret"]]
            verdicts = await gather_or_raise(
                *(self.deliberations.run(d) for d in public),
                *(self.deliberations.run(d, decision) for d, decision in self.court.pending_pushes()),
            )
            if speculative or not self.opened():
                return self.court.pending_petitions()
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            if self.court.pending_petitions() and not self.court.products(self.court.calendar().id, kind="month_draft"):
                return self.court.pending_petitions()
            if not self.court.products(self.court.calendar().id, kind="month_draft"):
                # These are this stage's completed outputs, including newly
                # committed verdicts, not a cache of unchanged ledger reads.
                await self.simulations.draft(list(zip(public, verdicts[:len(public)], strict=True)))
            if not self.court.products(self.court.calendar().id, kind="month_final"):
                self.simulations.speculate()
                if self.court.pending_petitions():
                    return self.court.pending_petitions()
                await self.simulations.final()
            await self.landing.run()
            self.court.settle_accounts()
            self.court.settle_journeys()
            await gather_or_raise(
                self.gazette.run(), self.sources.run(),
                *(self.secrets.report(d) for d in self.court.errands()),
            )
            self.court.advance_month()
            return ()

    async def advance(self) -> tuple[PendingPetition, ...]:
        self.open()
        return await self.resume()
