"""Month user: fill the first missing durable product on one monthly timeline."""

import asyncio
from collections.abc import Callable
from typing import Any

from ming.middle.court import Court
from ming.middle.invoke import ModelSource, TextUpdate, gather_or_raise
from ming.middle.view import EntityView
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.simulation import Simulations
from ming.month_steps.petitions import Inbox
from ming.month_steps.landing import Landing
from ming.month_steps.gazette import Gazette
from ming.month_steps.sources import Sources
from ming.month_steps.secrets import Secrets
from ming.month_steps.products import record_product
from ming.month_steps.materials import PendingPetition, next_month, pending_petitions, pending_pushes, petition_officials


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
        snapshot = self.court.read.opening_snapshot()
        if snapshot is not None:
            record_product(self.court, calendar.id, "month_open", {
                "date": calendar.data,
                "entities": [e.model_dump(mode="json") for e in snapshot],
            })
        return calendar

    def choose(self, petition: dict[str, Any] | None, option: int, date: dict[str, Any]) -> None:
        self.inbox.choose(petition, option, date)

    def presentation(self, calendar: EntityView | None = None) -> dict[str, Any]:
        calendar = self.court.read.calendar() if calendar is None else calendar
        returned = self.court.returned_petitions(date=calendar.data)
        awaiting_drafter = bool(returned) and not petition_officials(self.court)
        previous = {"year": calendar.data["year"] - (calendar.data["month"] == 1),
                    "month": (calendar.data["month"] - 2) % 12 + 1}
        return self.court.presentation(calendar, {
            "unhandled_monthly": [{"entity_id": str(entity_id)} for entity_id in self.court.read.fact_ids(
                "audit", "unhandled", date=previous, has="monthly",
            )],
            "petitions": [p.model_dump(mode="json") for p in pending_petitions(self.court)],
            "returned_petitions": [{"petition": f.detail, "awaiting_drafter": awaiting_drafter} for f in returned],
        })

    async def resume(
        self, *, speculative: bool = False, date: dict[str, Any] | None = None, opened: bool = False,
    ) -> tuple[PendingPetition, ...]:
        date = self.court.read.calendar().data if date is None else date
        async with self.lock:
            calendar = self.court.read.calendar()
            # The lock can wait behind a month that advances the calendar.
            if date != calendar.data:
                return pending_petitions(self.court)
            public = [d for d in self.court.read.entities("audit", kind="decree", ids=list(self.court.read.fact_ids(
                "audit", "decreed", date=calendar.data, entity_kind="decree",
            ))) if not d.data["secret"]]
            verdicts = await self.deliberations.run(
                [(d, None) for d in public] + list(pending_pushes(self.court, calendar.data)), calendar.data,
            )
            if speculative or not (opened or self.opened(calendar)):
                return pending_petitions(self.court)
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            pending = pending_petitions(self.court)
            drafted = self.court.read.has_facts(calendar.id, "month_draft", date=calendar.data)
            if pending and not drafted:
                return pending
            produced = None
            if not drafted:
                # Reuse only this invocation's already committed complete product.
                produced = await self.simulations.draft(list(zip(public, verdicts[:len(public)], strict=True)), calendar)
                pending = produced
            final = None
            if not self.court.read.has_facts(calendar.id, "month_final", date=calendar.data):
                if pending:
                    self.simulations.speculate(calendar, pending, produced)
                    return pending
                final = await self.simulations.final(calendar)
            await self.landing.run(calendar, final)
            self.court.settle_accounts(calendar)
            self.court.settle_journeys(calendar.data)
            await gather_or_raise(
                self.gazette.run(calendar), self.sources.run(calendar),
                self.secrets.report(self.court.read.without_events("decree", {"secret": True}, "completed", calendar.data), calendar.data),
            )
            self.court.record(calendar.id, [("advanced", {"date": calendar.data})], next_month(calendar.data))
            return ()

    async def advance(self) -> tuple[PendingPetition, ...]:
        return await self.resume(date=self.open().data, opened=True)
