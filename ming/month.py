"""Month user: resume the first missing ledger product, including after choices."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource
from ming.middle.view import EntityView
from ming.month_steps.deliberation import Deliberations
from ming.month_steps.simulation import Simulations, continuing_options
from ming.month_steps.petitions import Inbox
from ming.month_steps.landing import Landing
from ming.month_steps.gazette import Gazette


class Month:
    def __init__(
        self,
        court: Court,
        model: ModelSource,
        on_delta: Callable[[str], None] | None = None,
    ) -> None:
        self.court = court
        self.deliberations = Deliberations(court, model)
        self.simulations = Simulations(court, model)
        self.inbox = Inbox(court)
        self.landing = Landing(court)
        self.gazette = Gazette(court, model, on_delta)
        self.lock = asyncio.Lock()
        self.originals: dict[UUID, asyncio.Task[bool]] = {}

    def opened(self) -> bool:
        return any(
            f.kind == "month_open"
            for f in self.court.products(self.court.calendar().id, kind="month_open")
        )

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
                    "facts": [
                        f.model_dump(mode="json") for f in self.court.facts("emperor")
                    ],
                },
            )

    def petitions(self) -> list[PendingPetition]:
        return self.inbox.petitions()

    def choose(self, petition_id: UUID, option: int) -> None:
        self.inbox.choose(petition_id, option)

    def current_decrees(self) -> list[EntityView]:
        return [
            e
            for e in self.court.entities("audit", kind="decree")
            if e.kind == "decree"
            and any(f.kind == "decreed" for f in self.court.products(e.id))
        ]

    async def night(self, night: EntityView, decrees: list[EntityView]) -> bool:
        results = await asyncio.gather(
            *(self.deliberations.run(d, night.id) for d in decrees),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        approved = [
            d.model_dump(mode="json")
            for d in decrees
            if any(
                f.kind == "deliberation" and f.detail["verdict"] == "准"
                for f in self.court.products(d.id)
            )
        ]
        return await self.simulations.run(
            night,
            {
                "scope": "旨意推演",
                "decrees": approved,
                "deliberations": [
                    f.detail
                    for d in decrees
                    for f in self.court.products(d.id)
                    if f.kind == "deliberation"
                ],
            },
        )

    async def resume(
        self, *, speculative: bool = False, petition_id: str | None = None
    ) -> list[PendingPetition]:
        date = self.court.calendar().data
        # A failed task is not missing work. Only its owner entering recovery
        # may discard it; never discard it while reporting the fresh failure.
        if not speculative:
            chain = self.simulations.chain(petition_id)
            for key, task in list(self.simulations.continuations.items()):
                owned = (
                    key[1] in chain if petition_id is not None else key[1] not in chain
                )
                if owned and task.done() and task.exception() is not None:
                    del self.simulations.continuations[key]
        while date == self.court.calendar().data:
            if petition_id is None:
                pending = await self._resume(speculative=speculative)
            else:
                detail = next(
                    f.detail
                    for f in self.court.facts("audit", kind="petition")
                    if f.kind == "petition" and f.detail["id"] == petition_id
                )
                route = UUID(detail["route_id"])
                petition = PendingPetition.model_validate(
                    {k: v for k, v in detail.items() if k != "date"}
                )
                choice = next(
                    (
                        f.detail
                        for f in self.court.facts("audit", kind="choice")
                        if f.kind == "choice" and f.detail["petition_id"] == petition_id
                    ),
                    None,
                )
                # Only a choice that continues the segment depends on its parent
                # original; 收回/留中 consume no continuation and never wait for it.
                if (
                    choice is not None
                    and choice["option"] in continuing_options(petition, route)
                    and detail["date"] == self.court.calendar().data
                    and not self.court.products(route, kind="simulation")
                ):
                    await self.original(route)
                self.simulations.progress(route, petition_id)
                pending = self.petitions()
            if date != self.court.calendar().data:
                return pending
            waiting, continuing = self.gaps(petition_id)
            if not waiting and not continuing:
                return pending
            # Only the caller's selected work waits here, outside the month lock.
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
            ]
            results = await asyncio.gather(*jobs, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        return self.petitions()

    def gaps(
        self, petition_id: str | None
    ) -> tuple[list[tuple[UUID, str, int]], list[tuple[UUID, str]]]:
        """Unfinished selected work; one question waits only for its own chain."""
        facts = self.court.facts("audit", kind=("choice", "simulation"))
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
        task = self.originals.get(route)
        if task is None or task.done():
            entity = self.court.entity(route)
            decrees = self.current_decrees()
            produce = (
                self.night(
                    entity, [d for d in decrees if d.data["night_id"] == str(route)]
                )
                if entity.kind == "night"
                else self.world(self.nights(decrees), decrees)
            )
            task = self.originals[route] = asyncio.create_task(produce)
        return task

    async def world(self, nights: list[EntityView], decrees: list[EntityView]) -> bool:
        """Verdicts on held decrees, then this month's world simulation."""
        calendar = self.court.calendar()
        old = [d for d in self.deliberations.due() if d not in decrees]
        results = await asyncio.gather(
            *(self.deliberations.run(d, calendar.id) for d in old),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return await self.simulations.run(
            calendar,
            {
                "scope": "世界推演",
                "nights": [
                    {
                        "night_id": str(n.id),
                        "segments": [
                            f.detail["output"]
                            for f in self.court.products(n.id)
                            if f.kind == "simulation"
                        ],
                    }
                    for n in nights
                ],
                "reconsidered": [
                    {"decree": d.model_dump(mode="json"), "deliberation": f.detail}
                    for d in old
                    for f in self.court.products(d.id)
                    if f.kind == "deliberation" and f.detail["verdict"] == "准"
                ],
                "prior_choices": [
                    f.detail
                    for f in self.court.facts(
                        "audit", kind="choice", date=self.court.calendar().data
                    )
                    if f.kind == "choice"
                    and f.detail["date"] == self.court.calendar().data
                ],
            },
        )

    async def _resume(self, *, speculative: bool) -> list[PendingPetition]:
        date = self.court.calendar().data
        async with self.lock:
            if date != self.court.calendar().data:
                return self.petitions()
            nights = self.nights(self.current_decrees())
            results = await asyncio.gather(
                *(self.original(night.id) for night in nights),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            if not all(results) or speculative or not self.opened():
                return self.petitions()
            if any(
                p.route_id in {n.id for n in nights}
                or (
                    not p.blocking
                    and not any(
                        f.kind == "simulation"
                        for f in self.court.products(self.court.calendar().id)
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
            await self.gazette.run()
            self.court.advance_month()
            return self.petitions()

    async def advance(self) -> list[PendingPetition]:
        self.open()
        return await self.resume()
