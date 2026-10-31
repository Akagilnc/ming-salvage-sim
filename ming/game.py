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
from ming.middle.night import NightView
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

    def interactions(
        self, calendar: EntityView | None = None, *, nights: tuple[NightView | EntityView, ...] | None = None,
    ) -> dict[str, Any]:
        calendar = self.court.calendar() if calendar is None else calendar
        items = self.court.interactions(calendar.data)
        night = (next(iter(nights), None) if nights is not None else
                 self.court.latest_night() if "say" in items else None)
        pending = self.audience.pending_actions(items, night) | self.month.pending_actions(items, calendar)
        return {key: item for key, item in items.items() if key in pending}

    def failures(self, interactions: dict[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
        interactions = self.interactions() if interactions is None else interactions
        return tuple(i for i in interactions.values() if i["status"] == "failed")

    def running(
        self, interactions: dict[str, Any], *, waiting: bool | None = None,
        calendar: EntityView | None = None,
    ) -> tuple[dict[str, Any], ...]:
        if waiting is None and "month" in interactions:
            calendar = self.court.calendar() if calendar is None else calendar
            waiting = self.month.opened(calendar) and self.court.has_pending_petitions(calendar.data)
        return tuple(i for i in interactions.values()
                     if i["status"] != "failed" and i["action"] != "translation"
                     and not (i["action"] == "month" and waiting))

    def presentation(self) -> dict[str, Any]:
        calendar = self.court.calendar()
        nights = self.court.nights()
        night = nights[-1].model_dump(mode="json") if nights else None
        interactions = self.interactions(calendar, nights=nights)
        petitions = self.court.pending_petitions(calendar.data)
        opened = self.month.opened(calendar)
        running = self.running(interactions, waiting=opened and bool(petitions))
        pending = next((i for i in running if i["action"] == "month"), next(iter(running), None))
        failures = self.failures(interactions)
        failure = next((i for i in failures if i["action"] != "translation"), next(iter(failures), None))
        returned = self.court.returned_petitions(date=calendar.data)
        awaiting_drafter = bool(returned) and not self.court.petition_officials()
        return {
            "face": "audience" if night and not night["closed"] else
                    "month" if opened or "month" in interactions else "desk",
            "night": night, "date": calendar.data,
            "running": pending is not None and failure is None,
            "failure": failure, "pending": pending,
            "unhandled_monthly": self.court.unhandled_monthly(calendar.data),
            "petitions": [p.model_dump(mode="json") for p in petitions
                          if f"choose:{p.id}" not in interactions],
            "returned_petitions": [
                {"petition": f.detail, "awaiting_drafter": awaiting_drafter} for f in returned
            ],
        }

    def resume(
        self, calendar: EntityView | None = None, interactions: dict[str, Any] | None = None,
    ) -> None:
        calendar = self.court.calendar() if calendar is None else calendar
        interactions = self.interactions(calendar) if interactions is None else interactions
        failures = self.failures(interactions)
        pending = [i for i in self.running(interactions, calendar=calendar) if not failures or i["action"] == "choose"]
        if pending:
            self.active = asyncio.create_task(self._resume(pending))
        elif not failures and self.court.pending_nights():
            self.start_background()

    def recover_month(self, calendar: EntityView) -> bool:
        """The one ledger-driven month gap-fill after a reopen, a recovery or a
        choice; the 请先退朝 gate only guards user clicks. Running or failed work
        keeps it from starting, so it never runs twice or silently retries."""
        if not self.month.opened(calendar) or self.court.has_pending_petitions(calendar.data):
            return False
        interactions = self.interactions(calendar)
        if self.failures(interactions) or any(
            i["action"] != "month" for i in self.running(interactions, waiting=False)
        ) or (self.busy() and self.active is not asyncio.current_task()):
            return False
        payload = {"date": calendar.data}
        self.active = asyncio.create_task(self.execute("month", payload))
        # Started from inside other work, it replaces the task a drain is already
        # awaiting; tracking it keeps every drain waiting for the gap-fill too.
        self.track(self.active)
        return True

    async def _resume(self, pending: list[dict[str, Any]]) -> None:
        async def ordered() -> None:
            for item in pending:
                if item["action"] not in {"month", "choose"}:
                    await self.execute(item["action"], item["payload"])
                    if self.failures():
                        return
            for item in pending:
                if item["action"] == "month":
                    await self.execute(item["action"], item["payload"])

        # Each question resumes on its own chain; it never waits for an audience
        # turn, a night translation or the month work recovered beside it.
        await asyncio.gather(
            ordered(),
            *(
                self.execute(item["action"], item["payload"])
                for item in pending
                if item["action"] == "choose"
            ),
        )
        if not self.failures() and all(i["action"] != "month" for i in pending):
            self.recover_month(self.court.calendar())

    async def command(self, action: str, payload: dict[str, Any]) -> None:
        calendar = self.court.calendar() if action == "month" else None
        interactions = self.interactions(calendar)
        accepted = any(item["status"] != "failed" and same_call(item, action, payload)
                       for item in interactions.values())
        self.resume(calendar, interactions)
        # A question — fresh or retrying its own failed call — is accepted at
        # once; draining unrelated in-flight work first would block it.
        if action == "choose" and not accepted:
            self.start(action, payload, failures=self.failures(interactions))
            await self.drain()
            return
        await self.drain()
        failures = self.failures()
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
        failures: tuple[dict[str, Any], ...] | None = None,
        calendar: EntityView | None = None,
    ) -> asyncio.Task[Any] | None:
        payload = dict(payload or {})
        failure = next((item for item in failures or () if same_call(item, action, payload)), None)
        if failure:
            action = "retry"
        if action == "retry":
            calendar = self.court.calendar() if calendar is None else calendar
            interactions = self.interactions(calendar)
            failed = self.failures(interactions)
            failure = failure or next((i for i in failed if i["action"] != "translation"), next(iter(failed), None))
            if not failure:
                raise InvalidAction("没有待重试的动作")
            action, payload = failure["action"], dict(failure["payload"])
            pending = interactions.get("month")
            if action == "translation" and pending and pending["action"] == "month":
                action, payload = "month", dict(pending["payload"])
            # A retry redoes its own failed call; per-question work keeps the
            # same rule as a fresh start instead of waiting for unrelated work.
            if action != "choose" and self.busy():
                raise InvalidAction("这一步还在进行")
            # Replay accepted parameters, not a second choice event.
            self.interaction(action, "accepted", payload, calendar=calendar)
        else:
            if action in {"open", "dismiss"}:
                self.night_action(action)
                return None
            if action != "choose" and self.busy():
                raise InvalidAction("这一步还在进行")
            payload = self.accept(action, payload, calendar=calendar, failures=failures)
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
            night = self.court.latest_night()
            if night is None:
                raise InvalidAction("请先召对")
            if night.data["closed"]:
                return
            self.audience.open(night)
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
        failures: tuple[dict[str, Any], ...] | None = None,
    ) -> dict[str, Any]:
        calendar = self.court.calendar() if calendar is None else calendar
        payload["date"] = calendar.data
        if action == "choose":
            try:
                payload["petition"] = str(UUID(str(payload["petition"])))
                self.month.choose(payload, accept=True)
            except (ValueError, KeyError) as error:
                raise InvalidAction("无效的批红选项", 400) from error
        else:
            night = self.court.latest_night()
            if failures is None:
                failures = self.failures(self.interactions(calendar, nights=(night,) if night else ()))
            if any(action != "month" or i["action"] != "translation" for i in failures):
                raise InvalidAction("请重试未完成的动作")
            opened = night is not None and not night.data["closed"]
            if action == "say":
                if not isinstance(payload.get("words"), str) or not payload["words"].strip() or night is None or not opened:
                    raise InvalidAction("请在召对中说话")
                payload.update(night_id=str(night.id), turn_id=str(uuid4()))
            elif action != "month":
                raise InvalidAction("无效的动作", 400)
            elif opened:
                raise InvalidAction("请先退朝")
        self.interaction(action, "accepted", payload, calendar=calendar)
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
                self.interaction("translation", "accepted", payload)
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
        if self.failures():
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
        self, action: str, payload: dict[str, Any], *, starting: bool = False,
    ) -> str | None:
        try:
            output = await self.work(action, payload, starting=starting)
            if action == "month" and self.court.pending_nights():
                return None
            # The choice is complete before shared month work resumes. Reuse the
            # normal month action so its waiting and failures cannot belong to it.
            if action == "choose":
                self.recover_month(self.court.calendar())
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
        if action in {"say", "month"}:
            self.live.pop("delta" if action == "say" else "gazette", None)
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
            return None  # The prior month committed before the process stopped.
        if action == "choose":
            self.month.choose(payload)
            return None
        await self.translate(starting=starting)
        if not self.court.pending_nights():
            await self.month.advance()
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
