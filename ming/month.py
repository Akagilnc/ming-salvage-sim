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
        calendar = calendar if calendar is not None else self.court.calendar()
        return bool(self.court.products(calendar.id, kind="month_open", date=calendar.data))

    def open(self, calendar: EntityView) -> None:
        if not self.opened(calendar):
            self.court.record_product(calendar.id, "month_open", {
                "entities": [e.model_dump(mode="json") for e in self.court.entities("emperor", date=calendar.data)],
            }, date=calendar.data)

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    async def resume(
        self, calendar: EntityView | None = None, *, speculative: bool = False, petition_id: str | None = None,
    ) -> tuple[EntityView, tuple[PendingPetition, ...]]:
        # A click records its choice immediately. Shared finalization belongs to
        # the month action, never to one question or a second round of choices.
        calendar = calendar if calendar is not None else self.court.calendar()
        if petition_id is not None:
            return calendar, self.court.pending_petitions(calendar.data)
        waiting = self.lock.locked()
        async with self.lock:
            if waiting:
                current = self.court.calendar()
                if calendar.data != current.data:
                    return current, self.court.pending_petitions(current.data)
            public = [d for d in self.court.current_decrees(calendar.data) if not d.data["secret"]]
            verdicts = await self.deliberations.run(
                [*((d, None) for d in public), *self.court.pending_pushes(calendar.data)], calendar.data,
            )
            if speculative:
                return calendar, self.court.pending_petitions(calendar.data)
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            pending = self.court.pending_petitions(calendar.data)
            draft = self.court.products(calendar.id, kind="month_draft", date=calendar.data)
            if pending and not draft:
                return calendar, pending
            decrees = self.court.landing_materials(calendar.data)
            returned = self.court.returned_petitions()
            finished = self.court.products(calendar.id, kind="month_final", date=calendar.data)
            context = self.simulations.context(calendar, decrees, returned) if not draft or not finished else {}
            if draft:
                draft = draft[0].detail
            else:
                draft, pending = await self.simulations.draft(list(zip(public, verdicts[:len(public)], strict=True)), calendar, context)
            if not finished:
                petitions = self.court.month_petitions(calendar.data)
                products = self.court.petition_products([str(p.detail["id"]) for p in petitions], ("choice", "forecast"), date=calendar.data) if petitions else ()
                context = {**context, "draft": draft["output"]}
                self.simulations.speculate(petitions, calendar, context, products)
                if pending:
                    return calendar, pending
                final = await self.simulations.final(calendar, draft, petitions, products, context)
            else:
                final = finished[0].detail
            secrets = await self.landing.run(calendar, decrees, final)
            self.court.settle_accounts(calendar)
            self.court.settle_journeys(calendar.data)
            await gather_or_raise(
                self.gazette.run(calendar), self.sources.run(calendar, returned),
                self.secrets.run([d for d in secrets if d.data["secret"]], calendar),
            )
            return self.court.advance_month(calendar), ()

    async def advance(self, calendar: EntityView) -> tuple[EntityView, tuple[PendingPetition, ...]]:
        self.open(calendar)
        return await self.resume(calendar)
