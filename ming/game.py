"""Shared action lifecycle between the transport adapters and the two users."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from ming.audience import Audience
from ming.middle.court import Court
from ming.middle.invoke import ModelSource, build_agent
from ming.middle.view import EntityView
from ming.month import Month


def same_call(item: dict[str, Any], action: str, payload: dict[str, Any]) -> bool:
    return item["action"] == action and all(
        item["payload"].get(key) == value for key, value in payload.items()
    )


class InvalidAction(ValueError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class Game:
    def __init__(
        self,
        court: Court,
        model: ModelSource,
        *,
        month_model: ModelSource | None = None,
    ) -> None:
        self.court = court
        self.emit: Callable[[dict[str, Any]], None] | None = None
        self.live: dict[str, str] = {}
        self.audience = Audience(court, model)
        self.month = Month(
            court, month_model if month_model is not None else model,
            partial(self.notify, "gazette"),
        )
        self.active: asyncio.Task[Any] | None = None
        self.background: set[asyncio.Task[Any]] = set()
        self.translation: asyncio.Task[Any] | None = None
        nights = court.nights()
        if nights:
            self.audience.open(nights[-1])

    def configure(
        self, model: ModelSource, *, month_model: ModelSource | None = None,
    ) -> None:
        self.court.model = model
        for agent in (self.audience.scene, self.audience.translation):
            build_agent(model, agent=agent)
        month_model = month_model if month_model is not None else model
        for agent in (
            self.month.deliberations.agent, self.month.simulations.draft_agent,
            self.month.simulations.final_agent, self.month.landing.agent,
            self.month.gazette.agent, self.month.secrets.agent,
        ):
            build_agent(month_model, agent=agent)
        self.month.sources.model = month_model

    def notify(self, event: str, data: Any) -> None:
        if event != "state":
            self.live[event] = (
                data["replace"] if isinstance(data, dict)
                else self.live.get(event, "") + data
            )
        if self.emit:
            self.emit({"event": event, "data": data})

    def interaction(
        self, action: str, status: str, payload: dict[str, Any], *, calendar: EntityView | None = None,
    ) -> EntityView:
        key = f"choose:{payload['petition']}" if action == "choose" else action
        if status != "running" and action in {"say", "month"}:
            self.live.pop("delta" if action == "say" else "gazette", None)
        calendar = self.court.calendar() if calendar is None else calendar
        self.court.record(
            calendar.id,
            [
                (
                    "interaction",
                    {
                        "key": key,
                        "action": action,
                        "status": status,
                        "payload": payload,
                        "date": calendar.data,
                    },
                )
            ],
        )
        return calendar

    def settle_month(
        self, date: dict[str, Any] | None = None, *, interactions: dict[str, Any] | None = None,
        calendar: EntityView | None = None,
    ) -> bool:
        # A completed advance settles all failed callers of that work. On reopen,
        # a changed calendar is durable proof even if completion events were interrupted.
        interactions = self.court.interactions() if interactions is None else interactions
        failed = [i for i in interactions.values() if i["action"] in {"month", "choose"} and i["status"] == "failed"]
        if failed and date is None and calendar is None:
            calendar = self.court.calendar()
        current = calendar.data if calendar else None
        settled = [i for i in failed if (i["payload"]["date"] == date if date is not None else i["payload"]["date"] != current)]
        for item in settled:
            calendar = calendar or self.court.calendar()
            self.interaction(item["action"], "done", item["payload"], calendar=calendar)
        return bool(settled)

    def resume(
        self, calendar: EntityView | None = None, interactions: dict[str, Any] | None = None,
    ) -> None:
        interactions = self.court.interactions() if interactions is None else interactions
        if self.settle_month(interactions=interactions, calendar=calendar):
            interactions = self.court.interactions()
        failures = self.court.failures(interactions=interactions)
        pending = [i for i in self.court.running(interactions) if not failures or i["action"] == "choose"]
        if pending:
            self.active = asyncio.create_task(self._resume(pending))
        elif not failures:
            calendar = self.court.calendar() if calendar is None else calendar
            # Recovery belongs to the ledger, not to the currently showing face.
            if not self.recover_month(calendar, ready=True) and (
                self.court.pending_nights() or self.court.pending_petitions(calendar.data)
            ):
                self.start_background()

    def recover_month(self, calendar: EntityView | None = None, *, ready: bool | None = None) -> bool:
        """The one ledger-driven month gap-fill after a reopen, a recovery or a
        choice; the 请先退朝 gate only guards user clicks. Running or failed work
        keeps it from starting, so it never runs twice or silently retries."""
        calendar = self.court.calendar() if calendar is None else calendar
        if not self.month.opened(calendar):
            return False
        if ready is None:
            interactions = self.court.interactions()
            ready = not self.court.failures(interactions=interactions) and not self.court.running(interactions)
        if not ready:
            return False
        payload = {"date": calendar.data}
        self.interaction("month", "running", payload, calendar=calendar)
        self.active = asyncio.create_task(self.execute("month", payload))
        # Started from inside other work, it replaces the task a drain is already
        # awaiting; tracking it keeps every drain waiting for the gap-fill too.
        self.track(self.active)
        return True

    async def _resume(self, pending: list[dict[str, Any]]) -> None:
        resume_month = all(item["action"] != "month" for item in pending)

        async def ordered() -> None:
            for item in pending:
                if item["action"] not in {"month", "choose"}:
                    await self.execute(item["action"], item["payload"], resume_month=resume_month)
                    if self.court.failures():
                        return
            for item in pending:
                if item["action"] == "month":
                    await self.execute(item["action"], item["payload"])

        # Each question resumes on its own chain; it never waits for an audience
        # turn, a night translation or the month work recovered beside it.
        await asyncio.gather(
            ordered(),
            *(
                self.execute(item["action"], item["payload"], resume_month=resume_month)
                for item in pending
                if item["action"] == "choose"
            ),
        )
        if self.court.failures():
            return
        if not self.month.opened():
            self.start_background()

    async def command(self, action: str, payload: dict[str, Any]) -> None:
        calendar = self.court.calendar() if action == "month" else None
        interactions = self.court.interactions()
        accepted = any(
            item["status"] == "running" and same_call(item, action, payload)
            for item in interactions.values()
        )
        self.resume(calendar, interactions)
        # A question — fresh or retrying its own failed call — is accepted at
        # once; draining unrelated in-flight work first would block it.
        if action == "choose" and not accepted:
            self.start(action, payload, failures=self.court.failures())
            await self.drain()
            return
        await self.drain()
        failures = self.court.failures()
        if not failures and accepted:
            return
        current = None
        if not failures and calendar is not None:
            current = self.court.calendar()
            if current.data != calendar.data:
                return
        self.start(action, payload, failures=failures, calendar=current)
        await self.drain()

    def busy(self) -> bool:
        return self.active is not None and not self.active.done()

    def start(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        failures: tuple[dict[str, Any], ...] = (),
        calendar: EntityView | None = None,
    ) -> asyncio.Task[Any] | None:
        payload = dict(payload or {})
        failure = next((item for item in failures if same_call(item, action, payload)), None)
        if failure:
            action = "retry"
        if action == "retry":
            calendar = self.court.calendar() if calendar is None else calendar
            state = self.court.presentation(calendar)
            failure = failure or state["failure"]
            if not failure:
                raise InvalidAction("没有待重试的动作")
            action, payload = failure["action"], dict(failure["payload"])
            pending = state["pending"]
            if action == "translation" and pending and pending["action"] == "month":
                action, payload = "month", dict(pending["payload"])
            # A retry redoes its own failed call; per-question work keeps the
            # same rule as a fresh start instead of waiting for unrelated work.
            if action != "choose" and self.busy():
                raise InvalidAction("这一步还在进行")
            # Replay accepted parameters, not a second choice event.
            self.interaction(action, "running", payload, calendar=calendar)
        else:
            if action in {"open", "dismiss"}:
                self.night_action(action)
                return None
            if action != "choose" and self.busy():
                raise InvalidAction("这一步还在进行")
            payload = self.accept(action, payload, calendar=calendar)
        task = asyncio.create_task(self.execute(action, payload, starting=action == "month"))
        if action == "translation":
            self.translation = task
            self.start_background()
        if action == "translation" or (action == "choose" and self.busy()):
            self.track(task)
            self.notify("state", None)
            return None if action == "translation" else task
        self.active = task
        if action != "month":
            self.notify("state", None)
        return task

    def night_action(self, action: str) -> None:
        if action == "dismiss":
            nights = self.court.nights()
            if not nights:
                raise InvalidAction("请先召对")
            if nights[-1].closed:
                return
            self.audience.dismiss()
            self.start_background()
            if not self.busy():
                self.notify("state", None)
        else:
            if self.busy():
                raise InvalidAction("这一步还在进行")
            if self.audience.open():
                self.notify("state", None)

    def accept(
        self, action: str, payload: dict[str, Any], *, calendar: EntityView | None = None,
    ) -> dict[str, Any]:
        calendar = self.court.calendar() if calendar is None else calendar
        state = self.court.presentation(calendar)
        if (
            state["failure"]
            and action != "choose"
            and not (action == "month" and state["failure"]["action"] == "translation")
        ):
            raise InvalidAction("请重试未完成的动作")
        if action == "month" and state["face"] == "audience":
            raise InvalidAction("请先退朝")
        if action == "say":
            if not payload.get("words", "").strip() or state["face"] != "audience":
                raise InvalidAction("请在召对中说话")
            payload.update(night_id=str(self.audience.night_id), turn_id=str(uuid4()))
        elif action == "choose":
            try:
                self.month.choose(UUID(str(payload["petition"])), payload["option"])
            except (ValueError, KeyError) as error:
                raise InvalidAction("无效的批红选项", 400) from error
        elif action != "month":
            raise InvalidAction("无效的动作", 400)
        payload["date"] = state["date"]
        self.interaction(action, "running", payload, calendar=calendar)
        return payload

    def track(self, task: asyncio.Task[Any]) -> None:
        self.background.add(task)

    def start_background(self) -> None:
        task = asyncio.create_task(self.precompute())
        self.track(task)

    async def translate(self, *, starting: bool = False) -> None:
        if self.translation is None or self.translation.done():
            pending = self.court.pending_nights()
            if pending:
                payload = {"nights": [str(n) for n in pending]}
                self.interaction("translation", "running", payload)
                self.translation = asyncio.create_task(self.execute("translation", payload))
        # Month acceptance includes its prerequisite translation retry: register
        # both before showing the start, so the old failure is no longer shown.
        if starting:
            self.notify("state", None)
        if self.translation is not None and not self.translation.done():
            await asyncio.shield(self.translation)

    async def precompute(self) -> None:
        # Dismissal may be requested while the last accepted scene is still live.
        if self.active is not None and not self.active.done():
            await asyncio.shield(self.active)
        if self.court.failures():
            return
        await self.translate()
        if self.court.pending_nights():
            return
        try:
            await self.month.resume(speculative=True)
        except Exception:
            # Night speculation has a documented non-blocking failure contract.
            self.court.log.exception("night precomputation failed")

    async def execute(
        self, action: str, payload: dict[str, Any], *, resume_month: bool = False, starting: bool = False,
    ) -> str | None:
        try:
            output = await self.work(action, payload, starting=starting)
            if action == "month" and self.court.pending_nights():
                return None
            calendar = self.interaction(action, "done", payload)
            # The choice is complete before shared month work resumes. Reuse the
            # normal month action so its waiting and failures cannot belong to it.
            if resume_month or (action == "choose" and not self.court.pending_petitions(calendar.data)):
                self.recover_month(calendar)
        except Exception as error:
            self.court.log.exception("action=%s", action)
            self.interaction(
                action,
                "failed",
                {
                    **payload,
                    "type": type(error).__name__,
                    "message": str(error),
                    "log": str(self.court.error_path),
                },
            )
            output = None
        self.notify("state", None)
        return output

    async def work(self, action: str, payload: dict[str, Any], *, starting: bool = False) -> str | None:
        if action == "say":
            night = self.court.night(UUID(payload["night_id"]))
            self.audience.open(night)
            output = await self.audience.say(
                night, payload["words"],
                payload["turn_id"],
                partial(self.notify, "delta"),
            )
            if self.court.entity(self.audience.night_id).data["closed"]:
                self.start_background()
            return output
        if action == "translation":
            await self.audience.translate_pending()
            return None
        calendar = self.court.calendar()
        if payload["date"] != calendar.data:
            if starting:
                self.notify("state", None)
            self.settle_month(payload["date"], calendar=calendar)
            return None  # The prior month committed before the process stopped.
        if action == "choose":
            return None
        await self.translate(starting=starting)
        if not self.court.pending_nights():
            await self.month.advance()
            self.settle_month(payload["date"])
        return None

    async def drain(self) -> None:
        while True:
            if self.active is not None:
                await asyncio.shield(self.active)
            while self.background:
                tasks = list(self.background)
                try:
                    await asyncio.gather(*tasks)
                finally:
                    # Drain itself retires what it awaited: gather over finished tasks
                    # returns without yielding, so a done callback could never run.
                    self.background.difference_update(t for t in tasks if t.done())
            if self.translation is not None:
                await asyncio.shield(self.translation)
            await self.month.simulations.drain()
            # Reentry can accept work in an earlier lane while a later one waits.
            # No await separates this completion check from the caller's close.
            if not self.busy() and not self.background and (
                self.translation is None or self.translation.done()
            ):
                return

    async def close(self) -> None:
        try:
            await self.drain()
        finally:
            self.court.close()
