"""Shared action lifecycle between the transport adapters and the two users."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from ming.audience import Audience
from ming.middle.court import Court
from ming.middle.invoke import ModelSource
from ming.month import Month


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
    ) -> None:
        self.court = court
        self.emit = emit
        self.audience = Audience(court, model)
        self.month = Month(court, model, partial(self.notify, "gazette"))
        self.active: asyncio.Task[Any] | None = None
        self.background: set[asyncio.Task[Any]] = set()
        self.translation: asyncio.Task[Any] | None = None
        nights = court.nights(latest=True)
        if nights:
            self.audience.open(nights[-1].id)

    def notify(self, event: str, data: Any) -> None:
        if self.emit:
            self.emit({"event": event, "data": data})

    def interaction(self, action: str, status: str, payload: dict[str, Any]) -> None:
        key = f"choose:{payload['petition']}" if action == "choose" else action
        self.court.record(
            self.court.calendar().id,
            [
                (
                    "interaction",
                    {
                        "key": key,
                        "action": action,
                        "status": status,
                        "payload": payload,
                        "date": self.court.calendar().data,
                    },
                )
            ],
        )

    def failures(self) -> list[dict[str, Any]]:
        nights = self.court.nights(latest=True)
        night = nights[-1] if nights else None
        return [
            i
            for i in self.court.interactions().values()
            if i["status"] == "failed"
            and not (
                i["action"] == "say"
                and (
                    night is None
                    or night.closed
                    or i["payload"]["night_id"] != str(night.id)
                )
            )
        ]

    def presentation(self) -> dict[str, Any]:
        interactions = list(self.court.interactions().values())
        pending = next((i for i in interactions if i["status"] == "running"), None)
        month = self.court.interactions().get("month")
        if month and month["status"] == "running":
            pending = month
        nights = self.court.nights(latest=True)
        night = nights[-1].model_dump(mode="json") if nights else None
        failures = self.failures()
        # The translation-to-month exception must not bypass another failed action.
        failure = next(
            (i for i in failures if i["action"] != "translation"),
            next(iter(failures), None),
        )
        return {
            "face": "audience"
            if night and not night["closed"]
            else (
                "month"
                if self.month.opened() or (month and month["status"] != "done")
                else "desk"
            ),
            "night": night,
            "date": self.court.calendar().data,
            "running": pending is not None and failure is None,
            "failure": failure,
            "pending": pending,
            "petitions": [p.model_dump(mode="json") for p in self.month.petitions()],
        }

    def settle_month(self, date: dict[str, Any] | None = None) -> None:
        # A completed advance settles all failed callers of that work. On reopen,
        # a changed calendar is durable proof even if completion events were interrupted.
        for item in self.court.interactions().values():
            if (
                item["action"] in {"month", "choose"}
                and item["status"] == "failed"
                and (
                    item["payload"]["date"] == date
                    if date is not None
                    else item["payload"]["date"] != self.court.calendar().data
                )
            ):
                self.interaction(item["action"], "done", item["payload"])

    def resume(self) -> None:
        self.settle_month()
        pending = [
            i
            for i in self.court.interactions().values()
            if i["status"] == "running"
            and (not self.failures() or i["action"] == "choose")
        ]
        if pending:
            self.active = asyncio.create_task(self._resume(pending))
        elif self.presentation()["failure"]:
            return
        elif self.month.opened():
            # Missing products are decided by the ledger, not the showing face:
            # reopening fills them even while an audience is open, and the month
            # work itself translates any pending nights before advancing.
            self.recover_month()
        elif self.court.pending_nights():
            self.start_background()
        elif self.month.petitions():
            self.start_background()

    def recover_month(self) -> None:
        """The one ledger-driven month gap-fill after a reopen, a recovery or a
        choice; the 请先退朝 gate only guards user clicks. Running or failed work
        keeps it from starting, so it never runs twice or silently retries."""
        if (
            not self.month.opened()
            or self.failures()
            or any(i["status"] == "running" for i in self.court.interactions().values())
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
                    if self.presentation()["failure"]:
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
        if self.presentation()["failure"]:
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
            item["status"] == "running"
            and item["action"] == action
            and all(item["payload"].get(k) == v for k, v in payload.items())
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
        if not self.presentation()["failure"] and (
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
        failure = self.presentation()["failure"]
        if repeat and (
            repeated := next(
                (
                    item
                    for item in self.failures()
                    if item["action"] == action
                    and all(
                        item["payload"].get(key) == value
                        for key, value in payload.items()
                    )
                ),
                None,
            )
        ):
            action, failure = "retry", repeated
        if action == "retry":
            if not failure:
                raise InvalidAction("没有待重试的动作")
            action, payload = failure["action"], dict(failure["payload"])
            pending = self.presentation()["pending"]
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
                if not self.court.nights(latest=True):
                    raise InvalidAction("请先召对")
                self.audience.dismiss()
                self.start_background()
                return None
            if action != "choose" and self.busy():
                raise InvalidAction("这一步还在进行")
            if action == "open":
                self.audience.open()
                return None
            payload = self.accept(action, payload)
        task = asyncio.create_task(self.execute(action, payload))
        if action == "choose" and self.busy():
            self.track(task)
            return task
        self.active = task
        if action == "translation":
            self.start_background()
        return task

    def accept(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.presentation()
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
        payload["date"] = self.court.calendar().data
        self.interaction(action, "running", payload)
        return payload

    def track(self, task: asyncio.Task[Any]) -> None:
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    def start_background(self) -> None:
        task = asyncio.create_task(self.precompute())
        self.track(task)

    async def translate(self) -> None:
        if self.translation is not None and not self.translation.done():
            await asyncio.shield(self.translation)
            return
        if not self.court.pending_nights():
            return
        payload = {"nights": [str(n) for n in self.court.pending_nights()]}
        self.interaction("translation", "running", payload)
        self.translation = asyncio.create_task(self.execute("translation", payload))
        await asyncio.shield(self.translation)

    async def precompute(self) -> None:
        # Dismissal may be requested while the last accepted scene is still live.
        if self.active is not None and not self.active.done():
            await asyncio.shield(self.active)
        failure = self.presentation()["failure"]
        if failure:
            return
        await self.translate()
        if self.court.pending_nights():
            return
        try:
            await self.month.resume(speculative=True)
        except Exception:
            # Night speculation has a documented non-blocking failure contract.
            self.court.log.exception("night precomputation failed")

    async def execute(self, action: str, payload: dict[str, Any]) -> str | None:
        try:
            output = await self.work(action, payload)
            if action == "month" and self.court.pending_nights():
                return None
            self.interaction(action, "done", payload)
            # The choice is complete before shared month work resumes. Reuse the
            # normal month action so its waiting and failures cannot belong to it.
            if action == "choose" and not self.month.petitions():
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

    async def work(self, action: str, payload: dict[str, Any]) -> str | None:
        if action == "say":
            self.audience.open(UUID(payload["night_id"]))
            output = await self.audience.say(
                payload["words"],
                payload["turn_id"],
                partial(self.notify, "delta"),
            )
            if self.court.night(self.audience.night_id).closed:
                self.start_background()
            return output
        if action == "translation":
            await self.audience.translate_pending()
            return None
        if payload["date"] != self.court.calendar().data:
            self.settle_month(payload["date"])
            return None  # The prior month committed before the process stopped.
        if action == "choose":
            await self.month.resume(petition_id=payload["petition"])
            if payload["date"] != self.court.calendar().data:
                self.settle_month(payload["date"])
            return None
        await self.translate()
        if not self.court.pending_nights():
            await self.month.advance()
            self.settle_month(payload["date"])
        return None

    async def drain(self) -> None:
        if self.active is not None:
            await asyncio.shield(self.active)
        while self.background:
            await asyncio.gather(*self.background)
        if self.translation is not None:
            await asyncio.shield(self.translation)
        await self.month.simulations.drain()

    async def close(self) -> None:
        try:
            await self.drain()
        finally:
            self.court.close()
