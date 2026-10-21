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
        nights = court.nights()
        if nights:
            self.audience.open(nights[-1].id)

    def notify(self, event: str, data: Any) -> None:
        if self.emit:
            self.emit({"event": event, "data": data})

    def interactions(self) -> dict[str, dict[str, Any]]:
        return {
            f.detail["key"]: f.detail
            for f in self.court.facts("audit")
            if f.kind == "interaction"
        }

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

    def presentation(self) -> dict[str, Any]:
        interactions = list(self.interactions().values())
        pending = next((i for i in interactions if i["status"] == "running"), None)
        month = self.interactions().get("month")
        if month and month["status"] == "running":
            pending = month
        nights = self.court.nights()
        night = nights[-1].model_dump(mode="json") if nights else None
        failure = next(
            (
                i
                for i in interactions
                if i["status"] == "failed"
                and not (
                    i["action"] == "say"
                    and (
                        not night
                        or night["closed"]
                        or i["payload"]["night_id"] != night["id"]
                    )
                )
            ),
            None,
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

    def resume(self) -> None:
        if self.presentation()["failure"]:
            return
        pending = [i for i in self.interactions().values() if i["status"] == "running"]
        if pending:
            self.active = asyncio.create_task(self._resume(pending))
        elif self.court.pending_nights():
            self.start_background()
        elif self.month.opened() and not self.month.petitions():
            self.start("month")

    async def _resume(self, pending: list[dict[str, Any]]) -> None:
        for item in pending:
            await self.execute(item["action"], item["payload"])
            if self.presentation()["failure"]:
                return
        if not self.month.opened():
            self.start_background()

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
        if (
            repeat
            and failure
            and failure["action"] == action
            and all(
                failure["payload"].get(key) == value for key, value in payload.items()
            )
        ):
            action = "retry"
        if action == "retry":
            if self.busy():
                raise InvalidAction("这一步还在进行")
            failure = self.presentation()["failure"]
            if not failure:
                raise InvalidAction("没有待重试的动作")
            action, payload = failure["action"], dict(failure["payload"])
            pending = self.presentation()["pending"]
            if action == "translation" and pending and pending["action"] == "month":
                action, payload = "month", dict(pending["payload"])
            # Replay accepted parameters, not a second choice event.
            self.interaction(action, "running", payload)
        else:
            if action == "dismiss":
                if not self.court.nights():
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
        else:
            self.active = task
        return task

    def accept(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.presentation()
        if action == "month" and state["face"] == "audience":
            raise InvalidAction("请先退朝")
        if action == "say":
            if not payload.get("words", "").strip() or state["face"] != "audience":
                raise InvalidAction("请在召对中说话")
            payload.update(night_id=str(self.audience.night_id), turn_id=str(uuid4()))
        elif action == "choose":
            try:
                route = self.month.choose(UUID(payload["petition"]), payload["option"])
            except (ValueError, KeyError) as error:
                raise InvalidAction("无效的批红选项", 400) from error
            payload["route"] = str(route)
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
        if failure and failure["action"] == "translation":
            return
        await self.translate()
        if self.court.pending_nights():
            return
        results = await asyncio.gather(
            *(self.month.prepare(e.id) for e in self.month.decrees()),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                # Speculation alone has a documented non-blocking failure contract.
                self.court.log.error("night precomputation failed", exc_info=result)

    async def execute(self, action: str, payload: dict[str, Any]) -> str | None:
        try:
            output = await self.work(action, payload)
            if action == "month" and self.court.pending_nights():
                return None
            self.interaction(action, "done", payload)
            return output
        except Exception as error:
            self.court.log.exception("action=%s", action)
            key = f"choose:{payload['petition']}" if action == "choose" else action
            accepted = self.interactions()[key]["payload"]
            self.interaction(
                action,
                "failed",
                {
                    **accepted,
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
            return None  # The prior month committed before the process stopped.
        if action == "choose":
            await self.month.prepare(UUID(payload["route"]))
            if self.busy() and self.active is not asyncio.current_task():
                return None
            if not self.month.opened():
                return None
        await self.translate()
        if not self.court.pending_nights():
            await self.month.advance()
        return None

    async def drain(self) -> None:
        if self.active is not None:
            await asyncio.shield(self.active)
        while self.background:
            await asyncio.gather(*self.background)
        if self.translation is not None:
            await asyncio.shield(self.translation)

    async def close(self) -> None:
        try:
            await self.drain()
        finally:
            self.court.close()
