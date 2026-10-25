"""Month user: resume the first missing ledger product, including after choices."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, TextUpdate, enlist, gather_or_raise
from ming.middle.view import EntityView
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.simulation import Simulations, continuing_options
from ming.month_steps.petitions import Inbox
from ming.month_steps.landing import Landing
from ming.month_steps.gazette import Gazette
from ming.month_steps.sources import Sources
from ming.month_steps.secrets import Secrets


class Month:
    def __init__(
        self,
        court: Court,
        model: ModelSource,
        on_delta: Callable[[TextUpdate], None] | None = None,
    ) -> None:
        self.court = court
        self.deliberations = Deliberations(court, model)
        self.simulations = Simulations(court, model, self.deliberations.run)
        self.inbox = Inbox(court)
        self.landing = Landing(court, model)
        self.gazette = Gazette(court, model, on_delta)
        self.sources = Sources(court, model)
        self.secrets = Secrets(court, model)
        self.lock = asyncio.Lock()
        self.originals: dict[UUID, asyncio.Task[bool]] = {}

    def opened(self) -> bool:
        return bool(self.court.products(self.court.calendar().id, kind="month_open"))

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
                },
            )

    def petitions(self) -> list[PendingPetition]:
        return self.inbox.petitions()

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    async def night(self, night: EntityView, decrees: list[EntityView]) -> bool:
        public = [d for d in decrees if not d.data["secret"]]
        verdicts = dict(zip([d.id for d in public], await self.verdicts(public, night.id)))
        return await self.simulations.run(
            night,
            {
                "scope": "旨意推演",
                "decrees": [
                    d.model_dump(mode="json")
                    for d in decrees
                    if d.data["secret"] or verdicts[d.id]["verdict"] == "准"
                ],
                "deliberations": [
                    {"decree": d.model_dump(mode="json"), **verdicts[d.id],
                     "prior_interim": self.court.prior_interim(d.id)}
                    for d in public
                ],
            },
        )

    async def verdicts(self, decrees: list[EntityView], route: UUID) -> list[dict[str, Any]]:
        """A segment's own verdicts; a push's reconsideration is its petition's."""
        return await gather_or_raise(
            *(self.deliberations.run(d, route) for d in decrees)
        )

    async def resume(
        self, *, speculative: bool = False, petition_id: str | None = None
    ) -> list[PendingPetition]:
        date = self.court.calendar().data
        # A failed task is not missing work. Only its owner entering recovery
        # may discard it; never discard it while reporting the fresh failure.
        if not speculative:
            self.simulations.discard_failed(petition_id)
        while date == self.court.calendar().data:
            if petition_id is None:
                pending = await self._resume(speculative=speculative)
            else:
                recorded = self.court.petition(petition_id)
                petition = self.court.as_petition(recorded)
                detail = recorded.detail
                choice = next(
                    (
                        f.detail
                        for f in self.court.petition_products([petition_id], "choice")
                    ),
                    None,
                )
                # Only a choice that continues the segment depends on its parent
                # original; 收回/留中 consume no continuation and never wait for it.
                if (
                    choice is not None
                    and choice["option"] in continuing_options(petition, self.court)
                    and detail["date"] == self.court.calendar().data
                    and not self.court.products(petition.route_id, kind="simulation")
                ):
                    await self.original(petition.route_id)
                self.simulations.progress(petition.route_id, petition_id)
                pending = self.petitions()
            if date != self.court.calendar().data:
                return pending
            waiting, continuing = self.gaps(petition_id)
            pushes = self.simulations.open_pushes(petition_id)
            if not waiting and not continuing and not pushes:
                return pending
            # Only the caller's selected work waits here, outside the month lock.
            # An in-flight push reconsideration waits with the selected continuations.
            jobs: list[Awaitable[object]] = [
                *(
                    self.simulations.wait_for_choice(key)
                    if petition_id is not None
                    else asyncio.shield(self.simulations.tasks[key])
                    for key in waiting
                ),
                *(
                    asyncio.shield(self.simulations.continuations[key])
                    for key in continuing
                ),
                *(asyncio.shield(self.simulations.pushes[pid]) for pid in pushes),
            ]
            await gather_or_raise(*jobs)
        return self.petitions()

    def gaps(
        self, petition_id: str | None
    ) -> tuple[list[tuple[UUID, str, int]], list[tuple[UUID, str]]]:
        """Unfinished selected work; one question waits only for its own chain."""
        facts = (
            self.court.petition_products(
                [petition_id], ("choice", "simulation"), current=True
            )
            if petition_id is not None
            else self.court.facts(
                "audit", kind=("choice", "simulation"), date=self.court.calendar().data
            )
        )
        choices = {
            (f.detail["petition_id"], f.detail["option"])
            for f in facts
            if f.kind == "choice"
        }
        published = {
            f.detail.get("petition_id") for f in facts if f.kind == "simulation"
        }
        waiting = [
            key
            for key in self.simulations.tasks
            if key[1:] in choices
            and key[1] not in published
            and (petition_id is None or key[1] == petition_id)
        ]
        chain: set[str] | None = None
        if petition_id is not None:
            chain = self.simulations.chain(petition_id)
        continuing = [
            key
            for key, task in self.simulations.continuations.items()
            if not (task.done() and task.exception() is None)
            and (chain is None or key[1] in chain)
        ]
        return waiting, continuing

    def nights(self, decrees: list[EntityView]) -> list[EntityView]:
        return [
            self.court.entity(UUID(night_id))
            for night_id in dict.fromkeys(d.data["night_id"] for d in decrees)
        ]

    def original(self, route: UUID) -> asyncio.Task[bool]:
        """One shared in-flight production of a route's original segment.

        A finished task is replaced on the next call so every pass re-checks
        the ledger; a failed one is rerun only when a caller enters again.
        """
        async def produce() -> bool:
            entity = self.court.entity(route)
            decrees = self.court.current_decrees()
            if entity.kind == "night":
                return await self.night(
                    entity, [d for d in decrees if d.data["night_id"] == str(route)]
                )
            return await self.world(self.nights(decrees), decrees)

        return enlist(self.originals, route, produce, replace=True)

    async def world(self, nights: list[EntityView], decrees: list[EntityView]) -> bool:
        """Verdicts on held decrees, then this month's world simulation."""
        calendar = self.court.calendar()
        old = [d for d in self.court.due_decrees() if d not in decrees]
        verdicts = await self.verdicts(old, calendar.id)
        # World simulation precedes this month's sources: returned originals are unrevised.
        returned = {str(f.detail["id"]) for f in self.court.returned_petitions()}
        return await self.simulations.run(
            calendar,
            {
                "scope": "世界推演",
                "fiscal_events": self.court.fiscal_events(),
                "nights": [
                    {
                        "night_id": str(n.id),
                        "segments": [
                            f.detail["output"]
                            for f in self.court.products(n.id, kind="simulation")
                        ],
                    }
                    for n in nights
                ],
                "reconsidered": [
                    {"decree": d.model_dump(mode="json"), "deliberation": v,
                     "prior_interim": self.court.prior_interim(d.id)}
                    for d, v in zip(old, verdicts)
                ],
                "prior_choices": [
                    {
                        **f.detail,
                        "petition": self.court.petition(f.detail["petition_id"]).detail,
                    }
                    for f in self.court.facts(
                        "audit", kind="choice", date=self.court.calendar().data
                    )
                    if f.detail["petition_id"] not in returned
                ],
            },
        )

    async def _resume(self, *, speculative: bool) -> list[PendingPetition]:
        date = self.court.calendar().data
        async with self.lock:
            if date != self.court.calendar().data:
                return self.petitions()
            nights = self.nights(self.court.current_decrees())
            results = await gather_or_raise(
                *(self.original(night.id) for night in nights)
            )
            if not all(results) or speculative or not self.opened():
                return self.petitions()
            if any(
                p.route_id in {n.id for n in nights}
                or (
                    not p.blocking
                    and not self.court.products(
                        self.court.calendar().id, kind="simulation"
                    )
                )
                for p in self.petitions()
            ):
                return self.petitions()
            ready = await self.original(self.court.calendar().id)
            pending = self.petitions()
            if not ready or pending:
                return pending
            await self.landing.run()
            self.court.settle_accounts()
            self.secrets.accumulate()
            await gather_or_raise(
                self.gazette.run(),
                self.sources.urgent(),
                *(
                    self.sources.impeach(f)
                    for f in self.court.entities("audit", kind="faction")
                ),
                *(self.secrets.report(d) for d in self.court.errands()),
            )
            self.court.advance_month()
            return self.petitions()

    async def advance(self) -> list[PendingPetition]:
        self.open()
        return await self.resume()
