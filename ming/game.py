"""Shared action lifecycle between the transport adapters and the two users."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from ming.audience import Audience
from ming.middle.court import Court
from ming.middle.invoke import ModelSource
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
        emit: Callable[[dict[str, Any]], None] | None = None,
        *,
        month_model: ModelSource | None = None,
    ) -> None:
        self.court = court
        self.emit = emit
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
            self.audience.open(nights[-1].id)

    def notify(self, event: str, data: Any) -> None:
        if self.emit:
            self.emit({"event": event, "data": data})

    def interaction(
        self, action: str, status: str, payload: dict[str, Any],
        calendar: EntityView | None = None,
    ) -> None:
        key = f"choose:{payload['petition']}" if action == "choose" else action
        calendar = calendar if calendar is not None else self.court.calendar()
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

    def settle_month(self, date: dict[str, Any] | None = None, calendar: EntityView | None = None) -> None:
        calendar = calendar if calendar is not None else self.court.calendar()
        # A completed advance settles all failed callers of that work. On reopen,
        # a changed calendar is durable proof even if completion events were interrupted.
        for item in self.court.interactions().values():
            if (
                item["action"] in {"month", "choose"}
                and item["status"] == "failed"
                and (item["payload"]["date"] == date if date is not None
                     else item["payload"]["date"] != calendar.data)
            ):
                self.interaction(item["action"], "done", item["payload"], calendar)

    def resume(self) -> None:
        self.settle_month()
        interactions = self.court.interactions()
        failures = self.court.failures(interactions)
        pending = [i for i in self.court.running(interactions) if not failures or i["action"] == "choose"]
        if pending:
            self.active = asyncio.create_task(self._resume(pending))
        elif failures:
            return
        elif self.month.opened():
            # Missing products are decided by the ledger, not the showing face:
            # reopening fills them even while an audience is open, and the month
            # work itself translates any pending nights before advancing.
            self.recover_month()
        elif self.court.pending_nights():
            self.start_background()
        elif self.court.pending_petitions():
            self.start_background()

    def recover_month(self) -> None:
        """The one ledger-driven month gap-fill after a reopen, a recovery or a
        choice; the 请先退朝 gate only guards user clicks. Running or failed work
        keeps it from starting, so it never runs twice or silently retries."""
        if (
            not self.month.opened()
            or self.court.failures()
            or self.court.running()
        ):
            return
        payload = {"date": self.court.calendar().data}
        self.interaction("month", "running", payload)
        self.active = asyncio.create_task(self.execute("month", payload))
        # Started from inside other work, it replaces the task a drain is already
        # awaiting; tracking it keeps every drain waiting for the gap-fill too.
        self.track(self.active)

    async def _resume(self, pending: list[dict[str, Any]]) -> None:
        async def ordered() -> None:
            for item in pending:
                if item["action"] not in {"month", "choose"}:
                    await self.execute(item["action"], item["payload"])
                    if self.court.presentation()["failure"]:
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
        if self.court.presentation()["failure"]:
            return
        if not self.month.opened():
            self.start_background()
        elif all(item["action"] != "month" for item in pending):
            # Missing products are filled by the same ledger-driven month entry
            # as any other reopen (a recovered month already was that entry); the
            # speculative path stops before world products and would leave them.
            self.recover_month()

    async def command(self, action: str, payload: dict[str, Any]) -> None:
        date = self.court.calendar().data
        accepted = any(
            item["status"] == "running" and same_call(item, action, payload)
            for item in self.court.interactions().values()
        )
        self.resume()
        # A question — fresh or retrying its own failed call — is accepted at
        # once; draining unrelated in-flight work first would block it.
        if action == "choose" and not accepted:
            self.start(action, payload, repeat=True)
            await self.drain()
            return
        await self.drain()
        if not self.court.presentation()["failure"] and (
            accepted or (action == "month" and self.court.calendar().data != date)
        ):
            return
        self.start(action, payload, repeat=True)
        await self.drain()

    def busy(self) -> bool:
        return self.active is not None and not self.active.done()

    def start(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        repeat: bool = False,
    ) -> asyncio.Task[Any] | None:
        payload = dict(payload or {})
        state = self.court.presentation()
        failure = state["failure"]
        if repeat and (
            repeated := next(
                (
                    item
                    for item in self.court.failures()
                    if same_call(item, action, payload)
                ),
                None,
            )
        ):
            action, failure = "retry", repeated
        if action == "retry":
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
            self.interaction(action, "running", payload)
        else:
            if action == "dismiss":
                if state["night"] is None:
                    raise InvalidAction("请先召对")
                self.audience.dismiss()
                self.start_background()
                return None
            if action != "choose" and self.busy():
                raise InvalidAction("这一步还在进行")
            if action == "open":
                self.audience.open()
                return None
            payload = self.accept(action, payload, state)
        task = asyncio.create_task(self.execute(action, payload))
        if action == "translation":
            self.translation = task
            self.start_background()
        if action == "translation" or (action == "choose" and self.busy()):
            self.track(task)
            return None if action == "translation" else task
        self.active = task
        return task

    def accept(self, action: str, payload: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
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
        self.interaction(action, "running", payload)
        return payload

    def track(self, task: asyncio.Task[Any]) -> None:
        self.background.add(task)

    def start_background(self) -> None:
        task = asyncio.create_task(self.precompute())
        self.track(task)

    async def translate(self, calendar: EntityView | None = None) -> bool:
        if self.translation is None or self.translation.done():
            pending = self.court.pending_nights()
            if not pending:
                return True
            calendar = calendar if calendar is not None else self.court.calendar()
            payload = {"nights": [str(n) for n in pending]}
            self.interaction("translation", "running", payload, calendar)
            self.translation = asyncio.create_task(self.execute("translation", payload, calendar))
        # A failed callback can follow a committed translation. In that case
        # establish the actual remaining work, not a success guess from the task.
        return bool(await asyncio.shield(self.translation)) or not self.court.pending_nights()

    async def precompute(self) -> None:
        # Dismissal may be requested while the last accepted scene is still live.
        if self.active is not None and not self.active.done():
            await asyncio.shield(self.active)
        failure = self.court.presentation()["failure"]
        if failure:
            return
        if not await self.translate():
            return
        try:
            await self.month.resume(speculative=True)
        except Exception:
            # Night speculation has a documented non-blocking failure contract.
            self.court.log.exception("night precomputation failed")

    async def execute(self, action: str, payload: dict[str, Any], calendar: EntityView | None = None) -> str | bool | None:
        try:
            calendar = calendar if calendar is not None else self.court.calendar()
            output, current = await self.work(action, payload, calendar)
            if current is None:
                return None
            calendar = current
            if action in {"month", "choose"} and payload["date"] != calendar.data:
                self.settle_month(payload["date"], calendar)
            self.interaction(action, "done", payload, calendar)
            # The choice is complete before shared month work resumes. Reuse the
            # normal month action so its waiting and failures cannot belong to it.
            if action == "choose" and not self.court.pending_petitions():
                self.recover_month()
            return output
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
            return None
        finally:
            self.notify("done", None)

    async def work(self, action: str, payload: dict[str, Any], calendar: EntityView) -> tuple[str | bool | None, EntityView | None]:
        if action == "say":
            night = self.audience.open(UUID(payload["night_id"]))
            output, closed = await self.audience.say(
                payload["words"], payload["turn_id"], partial(self.notify, "delta"),
                night=night, calendar=calendar,
            )
            if closed:
                self.start_background()
            return output, calendar
        if action == "translation":
            await self.audience.translate_pending(tuple(UUID(n) for n in payload["nights"]), calendar)
            return True, calendar
        if payload["date"] != calendar.data:
            return None, calendar  # The prior month committed before the process stopped.
        if action == "choose":
            calendar, _ = await self.month.resume(calendar, petition_id=payload["petition"])
            return None, calendar
        if not await self.translate(calendar):
            return None, None
        calendar, _ = await self.month.advance(calendar)
        return None, calendar

    async def drain(self) -> None:
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

    async def close(self) -> None:
        try:
            await self.drain()
        finally:
            self.court.close()
