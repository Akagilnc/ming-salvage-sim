"""Month user: fill the first missing durable product on one monthly timeline."""

import asyncio
from collections.abc import Callable
from typing import Any

from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.invoke import TextUpdate, gather_or_raise
from ming.middle.view import EntityView
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.simulation import Simulations
from ming.month_steps.petitions import Inbox
from ming.month_steps.landing import Landing
from ming.month_steps.gazette import Gazette
from ming.month_steps.sources import Sources
from ming.month_steps.secrets import Secrets
from ming.month_steps.products import record_product
from ming.month_steps.materials import PETITION_OFFICES, PendingPetition, has_pending_petitions, next_month, pending_petitions, pending_pushes


class Month:
    def __init__(
        self, court: Court,
        on_delta: Callable[[TextUpdate], None] | None = None,
    ) -> None:
        self.court = court
        self.model: Model
        model = lambda: self.model
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

    def waiting(
        self, calendar: EntityView, *, opened: bool | None = None,
        has_petitions: bool | None = None,
    ) -> bool:
        opened = self.opened(calendar) if opened is None else opened
        return opened and (has_petitions if has_petitions is not None else has_pending_petitions(self.court))

    def pending_actions(self, items: dict[str, Any]) -> dict[str, Any]:
        choices = [i["payload"]["petition"] for i in items.values() if i["action"] == "choose"]
        chosen = {f.detail["petition_id"] for f in self.court.read.facts("audit", kind="choice", detail={"petition_id": choices})}
        return {
            key: item for key, item in items.items()
            if item["action"] in {"month", "choose"}
            and (item["action"] == "month" or item["payload"]["petition"] not in chosen)
        }

    def choose(self, payload: dict[str, Any], *, accept: bool = False) -> None:
        self.inbox.choose(payload, accept=accept)

    def presentation(self, calendar: EntityView) -> dict[str, Any]:
        """The month's share of the screen; Game owns the action state around it."""
        returned = self.court.returned_petitions(date=calendar.data)
        awaiting_drafter = bool(returned) and not self.court.read.office_holders(PETITION_OFFICES)
        previous = {"year": calendar.data["year"] - (calendar.data["month"] == 1),
                    "month": (calendar.data["month"] - 2) % 12 + 1}
        return {
            "unhandled_monthly": [{"entity_id": str(entity_id)} for entity_id in self.court.read.fact_ids(
                "audit", "unhandled", date=previous, has="monthly",
            )],
            "petitions": [p.model_dump(mode="json") for p in pending_petitions(self.court)],
            "returned_petitions": [{"petition": f.detail, "awaiting_drafter": awaiting_drafter} for f in returned],
        }

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
                pending = pending_petitions(self.court)
                if pending and self.court.read.has_facts(calendar.id, "month_draft", date=calendar.data):
                    self.simulations.speculate(calendar, pending, None)
                return pending
            final = None
            if not self.court.read.has_facts(calendar.id, "month_final", date=calendar.data):
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
                    pending = produced.petitions
                if pending:
                    self.simulations.speculate(calendar, pending, produced)
                    return pending
                final = await self.simulations.final(calendar, produced)
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
