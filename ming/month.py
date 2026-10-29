"""Month user: fill the first missing durable product on one monthly timeline."""

import asyncio
from collections.abc import Callable
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, TextUpdate, gather_or_raise
from ming.middle.view import EntityView
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

    def opened(self, calendar: EntityView | None = None) -> bool:
        calendar = self.court.calendar() if calendar is None else calendar
        return bool(self.court.products(calendar.id, kind="month_open", date=calendar.data))

    def open(self) -> None:
        calendar = self.court.calendar()
        if not self.opened(calendar):
            self.court.record_product(calendar.id, "month_open", {
                "entities": [e.model_dump(mode="json") for e in self.court.entities("emperor")],
            })

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    async def resume(self, *, speculative: bool = False) -> tuple[PendingPetition, ...]:
        date = self.court.calendar().data
        async with self.lock:
            calendar = self.court.calendar()
            if date != calendar.data:
                return self.court.pending_petitions(calendar.data)
            public = [d for d in self.court.current_decrees() if not d.data["secret"]]
            verdicts = await gather_or_raise(
                *(self.deliberations.run(d) for d in public),
                *(self.deliberations.run(d, decision) for d, decision in self.court.pending_pushes()),
            )
            if speculative or not self.opened(calendar):
                return self.court.pending_petitions(calendar.data)
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            pending = self.court.pending_petitions(calendar.data)
            drafted = self.court.products(calendar.id, kind="month_draft", date=calendar.data)
            if pending and not drafted:
                return pending
            if not drafted:
                # These are this stage's completed outputs, including newly
                # committed verdicts, not a cache of unchanged ledger reads.
                await self.simulations.draft(list(zip(public, verdicts[:len(public)], strict=True)))
            if not self.court.products(calendar.id, kind="month_final", date=calendar.data):
                self.simulations.speculate()
                if pending := self.court.pending_petitions(calendar.data):
                    return pending
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
