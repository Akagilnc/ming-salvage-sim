"""Month user: fill the first missing durable product on one monthly timeline."""

import asyncio
from collections.abc import Callable
from uuid import UUID
from typing import Any

from ming.middle.court import Court
from ming.middle.view import EntityView
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

    def opened(self, calendar: EntityView | None = None) -> bool:
        calendar = self.court.calendar() if calendar is None else calendar
        return bool(self.court.products(calendar.id, kind="month_open"))

    def open(self, calendar: EntityView) -> None:
        if not self.opened(calendar):
            self.court.record_product(calendar.id, "month_open", {
                "entities": [e.model_dump(mode="json") for e in self.court.entities("emperor")],
            }, date=calendar.data)

    def petitions(self, date: dict[str, Any] | None = None) -> list[PendingPetition]:
        return self.inbox.petitions(date)

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    async def resume(
        self, *, speculative: bool = False, petition_id: str | None = None,
        calendar: EntityView,
    ) -> list[PendingPetition] | EntityView:
        # A click records its choice immediately. Shared finalization belongs to
        # the month action, never to one question or a second round of choices.
        if petition_id is not None:
            return self.petitions(calendar.data)
        date = calendar.data
        waited = self.lock.locked()
        async with self.lock:
            calendar = self.court.calendar() if waited else calendar
            if date != calendar.data:
                return self.petitions(calendar.data)
            public = [d for d in self.court.current_decrees(calendar.data) if not d.data["secret"]]
            pushes = self.court.pending_pushes(calendar.data)
            verdicts: list[dict[str, Any]] = []
            if public or pushes:
                world = self.court.entities("audit", kind="world")[0]
                verdicts = await gather_or_raise(
                    *(self.deliberations.run(d, calendar, world) for d in public),
                    *(self.deliberations.run(d, calendar, world, decision) for d, decision in pushes),
                )
            if speculative or not self.opened(calendar):
                return self.petitions()
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            petitions = self.petitions(calendar.data)
            draft = self.court.products(calendar.id, kind="month_draft")
            if petitions and not draft:
                return petitions
            if not draft:
                await self.simulations.draft(calendar, list(zip(public, verdicts[:len(public)], strict=True)))
            if not self.court.products(calendar.id, kind="month_final"):
                month_petitions = self.simulations.speculate(calendar)
                petitions = self.petitions(calendar.data)
                if petitions:
                    return petitions
                await self.simulations.final(calendar, month_petitions)
            await self.landing.run(calendar)
            self.court.settle_accounts()
            self.court.settle_journeys()
            await gather_or_raise(
                self.gazette.run(calendar), self.sources.run(calendar),
                *(self.secrets.report(d, calendar) for d in self.court.errands(calendar.data)),
            )
            return self.court.advance_month()

    async def advance(self, calendar: EntityView) -> list[PendingPetition] | EntityView:
        self.open(calendar)
        return await self.resume(calendar=calendar)
