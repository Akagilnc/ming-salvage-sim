"""Month user: fill the first missing durable product on one monthly timeline."""

import asyncio
from collections.abc import Callable
from typing import Any

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
from ming.month_steps.products import as_petition, record_product


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
        calendar = self.court.read.calendar() if calendar is None else calendar
        return self.court.read.has_facts(calendar.id, "month_open", date=calendar.data)

    def open(self) -> EntityView:
        calendar = self.court.read.calendar()
        if not self.opened(calendar):
            record_product(self.court, calendar.id, "month_open", {
                "date": calendar.data,
                "entities": [e.model_dump(mode="json") for e in self.court.read.entities("emperor")],
            })
        return calendar

    def choose(self, petition: dict[str, Any] | None, option: int, date: dict[str, Any]) -> None:
        self.inbox.choose(petition, option, date)

    async def resume(self, *, speculative: bool = False, date: dict[str, Any] | None = None) -> tuple[PendingPetition, ...]:
        date = self.court.read.calendar().data if date is None else date
        async with self.lock:
            calendar = self.court.read.calendar()
            if date != calendar.data:
                return tuple(map(as_petition, self.court.pending_petitions(calendar.data)))
            public = [d for d in self.court.current_decrees(calendar.data) if not d.data["secret"]]
            verdicts = await self.deliberations.run(
                [(d, None) for d in public] + list(self.court.pending_pushes(calendar.data)), calendar.data,
            )
            if speculative or not self.opened(calendar):
                return tuple(map(as_petition, self.court.pending_petitions(calendar.data)))
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            pending = tuple(map(as_petition, self.court.pending_petitions(calendar.data)))
            drafted = self.court.read.has_facts(calendar.id, "month_draft", date=calendar.data)
            if pending and not drafted:
                return pending
            if not drafted:
                # These are this stage's completed outputs, including newly
                # committed verdicts, not a cache of unchanged ledger reads.
                await self.simulations.draft(list(zip(public, verdicts[:len(public)], strict=True)), calendar)
                pending = tuple(map(as_petition, self.court.pending_petitions(calendar.data)))
            if not self.court.read.has_facts(calendar.id, "month_final", date=calendar.data):
                if pending:
                    self.simulations.speculate(calendar, pending)
                    return pending
                await self.simulations.final(calendar)
            await self.landing.run(calendar)
            self.court.settle_accounts()
            self.court.settle_journeys(calendar.data)
            await gather_or_raise(
                self.gazette.run(calendar), self.sources.run(calendar),
                self.secrets.report(self.court.errands(calendar.data), calendar.data),
            )
            self.court.advance_month(calendar.id)
            return ()

    async def advance(self) -> tuple[PendingPetition, ...]:
        return await self.resume(date=self.open().data)
