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
        return self.court.has_product(calendar.id, "month_open", date=calendar.data)

    def open(self) -> EntityView:
        calendar = self.court.calendar()
        if not self.opened(calendar):
            self.court.record_product(calendar.id, "month_open", {
                "entities": [e.model_dump(mode="json") for e in self.court.entities("emperor", current=calendar.data)],
            })
        return calendar

    def waiting(
        self, calendar: EntityView, *, opened: bool | None = None,
        has_petitions: bool | None = None,
    ) -> bool:
        opened = self.opened(calendar) if opened is None else opened
        return opened and (has_petitions if has_petitions is not None else self.court.has_pending_petitions(calendar.data))

    def pending_actions(self, items: dict[str, Any]) -> dict[str, Any]:
        choices = [i["payload"]["petition"] for i in items.values() if i["action"] == "choose"]
        chosen = {f.detail["petition_id"] for f in self.court.petition_products(choices, "choice", date=None)}
        return {
            key: item for key, item in items.items()
            if item["action"] in {"month", "choose"}
            and (item["action"] == "month" or item["payload"]["petition"] not in chosen)
        }

    def choose(self, payload: dict[str, Any], *, accept: bool = False) -> None:
        self.inbox.choose(payload, accept=accept)

    async def resume(self, *, speculative: bool = False, date: dict[str, Any] | None = None) -> tuple[PendingPetition, ...]:
        date = self.court.calendar().data if date is None else date
        async with self.lock:
            calendar = self.court.calendar()
            if date != calendar.data:
                return self.court.pending_petitions(calendar.data)
            public = [d for d in self.court.current_decrees(calendar.data) if not d.data["secret"]]
            verdicts = await self.deliberations.run(
                [(d, None) for d in public] + list(self.court.pending_pushes(calendar.data)), calendar.data,
            )
            if speculative or not self.opened(calendar):
                pending = self.court.pending_petitions(calendar.data)
                if pending and self.court.has_product(calendar.id, "month_draft", date=calendar.data):
                    self.simulations.speculate(calendar)
                return pending
            # Opening urgent petitions must be answered before drafting, since
            # their choices are inputs to this month's single timeline.
            pending = self.court.pending_petitions(calendar.data)
            drafted = self.court.has_product(calendar.id, "month_draft", date=calendar.data)
            if pending and not drafted:
                return pending
            if not drafted:
                # These are this stage's completed outputs, including newly
                # committed verdicts, not a cache of unchanged ledger reads.
                await self.simulations.draft(list(zip(public, verdicts[:len(public)], strict=True)), calendar)
                pending = self.court.pending_petitions(calendar.data)
            if not self.court.has_product(calendar.id, "month_final", date=calendar.data):
                if pending:
                    self.simulations.speculate(calendar)
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
