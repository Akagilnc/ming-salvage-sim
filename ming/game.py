"""Shared action lifecycle between the transport adapters and the two users."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any, Literal, NamedTuple, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError

from ming.audience import Audience
from ming.middle.court import Court
from ming.middle.invoke import Settings, configured_model
from ming.middle.view import EntityView
from ming.middle.night import NightHeader
from ming.month import Month
from ming.month_steps.materials import has_pending_petitions


def same_call(item: dict[str, Any], action: str, payload: dict[str, Any]) -> bool:
    return item["action"] == action and all(
        item["payload"].get(key) == value for key, value in payload.items()
    )


class InvalidAction(ValueError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


type ActionName = Literal["open", "say", "dismiss", "month", "choose", "retry"]


class Action[Name](BaseModel):
    action: Name
    words: str = ""
    petition: UUID | None = None
    option: int = Field(default=-1, strict=True)

    @classmethod
    def parse(cls, data: str | bytes) -> Self:
        try:
            return cls.model_validate_json(data)
        except ValidationError as error:
            raise InvalidAction("无效的动作", 400) from error


class ActionFacts(NamedTuple):
    calendar: EntityView
    night: NightHeader | None
    interactions: dict[str, Any]
    pending_nights: tuple[UUID, ...] | None


class Game:
    def __init__(
        self,
        court: Court,
        model: Settings,
        *,
        month_model: Settings | None = None,
    ) -> None:
        self.court = court
        self.emit: Callable[[dict[str, Any]], None] | None = None
        self.live: dict[str, str] = {}
        self.audience = Audience(court, self.start_background)
        self.month = Month(court, partial(self.notify, "gazette"))
        self.configure(model, month_model=month_model)
        self.active: asyncio.Task[Any] | None = None
        self.background: set[asyncio.Task[Any]] = set()
        self.translation: asyncio.Task[Any] | None = None

    def configure(
        self, model: Settings, *, month_model: Settings | None = None,
    ) -> None:
        self.audience.model = configured_model(model)
        self.month.model = (
            configured_model(month_model)
            if month_model is not None else self.audience.model
        )

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
    ) -> None:
        key = f"choose:{payload['petition']}" if action == "choose" else action
        calendar = self.court.read.calendar() if calendar is None else calendar
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

    def actions(self, *, full_night: bool = False, pending_nights: tuple[UUID, ...] | None = None) -> ActionFacts:
        """Synchronous action materials; never carried into scheduled work."""
        calendar = self.court.read.calendar()
        items = self.court.interactions(calendar.data)
        night = (next(iter(self.court.nights()), None) if full_night else
                 self.court.latest_night() if "say" in items else None)
        if pending_nights is None and "translation" in items:
            pending_nights = self.court.pending_nights()
        pending = self.audience.pending_actions(
            items, night, pending_nights=pending_nights or (),
        ) | self.month.pending_actions(items)
        return ActionFacts(calendar, night, {key: item for key, item in items.items() if key in pending}, pending_nights)

    def failures(self, interactions: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        return tuple(sorted((i for i in interactions.values() if i["status"] == "failed"),
                            key=lambda i: i["action"] == "translation"))

    def running(self, interactions: dict[str, Any], *, waiting: bool) -> tuple[dict[str, Any], ...]:
        return tuple(i for i in interactions.values()
                     if i["status"] != "failed" and i["action"] != "translation"
                     and not (i["action"] == "month" and waiting))

    def presentation(
        self, facts: ActionFacts | None = None, monthly: dict[str, Any] | None = None,
        *, opened: bool | None = None,
    ) -> dict[str, Any]:
        calendar, latest, interactions, _ = self.actions(full_night=True) if facts is None else facts
        night = latest.model_dump(mode="json") if latest else None
        monthly = self.month.presentation(calendar) if monthly is None else monthly
        opened = self.month.opened(calendar) if opened is None else opened
        running = self.running(interactions, waiting=self.month.waiting(calendar, opened=opened, has_petitions=bool(monthly["petitions"])))
        pending = next((i for i in running if i["action"] == "month"), next(iter(running), None))
        failures = self.failures(interactions)
        failure = next(iter(failures), None)
        return {
            "face": "audience" if night and not night["closed"] else
                    "month" if opened or "month" in interactions else "desk",
            "night": night, "date": calendar.data,
            "running": pending is not None and failure is None,
            "failure": failure, "pending": pending, **monthly,
            "petitions": [p for p in monthly["petitions"] if f"choose:{p['id']}" not in interactions],
        }

    def refresh(self, *, reopening: bool = False) -> dict[str, Any] | None:
        """Resume and present one synchronous view, before scheduled work can run."""
        if self.emit is None:
            if reopening:
                self.reopen()
            else:
                self.resume()
            return None
        facts = self.actions(full_night=True)
        monthly = self.month.presentation(facts.calendar)
        opened = self.month.opened(facts.calendar)
        if reopening:
            self.reopen(facts, has_petitions=bool(monthly["petitions"]), opened=opened)
        else:
            self.resume(facts, has_petitions=bool(monthly["petitions"]), opened=opened)
        return self.presentation(facts, monthly, opened=opened)

    def reopen(self, facts: ActionFacts | None = None, *, has_petitions: bool | None = None, opened: bool | None = None) -> None:
        facts = self.actions() if facts is None else facts
        has_petitions = has_pending_petitions(self.court) if has_petitions is None else has_petitions
        self.resume(facts, has_petitions=has_petitions, opened=opened)
        if has_petitions or (facts.pending_nights if facts.pending_nights is not None else self.court.pending_nights()):
            self.start_background()

    def resume(self, facts: ActionFacts | None = None, *, has_petitions: bool | None = None, opened: bool | None = None) -> None:
        if self.busy():
            return
        facts = self.actions() if facts is None else facts
        calendar, _, interactions, _ = facts
        failures = self.failures(interactions)
        waiting = "month" in interactions and self.month.waiting(calendar, has_petitions=has_petitions, opened=opened)
        pending = [i for i in self.running(interactions, waiting=waiting) if not failures or i["action"] == "choose"]
        if pending:
            self.active = asyncio.create_task(self._resume(pending))

    async def _resume(self, pending: list[dict[str, Any]]) -> None:
        async def ordered() -> None:
            for item in pending:
                if item["action"] not in {"month", "choose"}:
                    await self.execute(item["action"], item["payload"])
                    if self.failures(self.actions().interactions):
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
        self.active = None
        self.resume()

    async def command(self, action: str, payload: dict[str, Any]) -> None:
        facts = self.actions()
        accepted = any(item["status"] != "failed" and same_call(item, action, payload)
                       for item in facts.interactions.values())
        self.reopen(facts)
        # Choices never wait for unrelated work. Other commands can consume the
        # recovery they just started instead of accepting the same action twice.
        if accepted or action != "choose":
            if self.busy() or self.background:
                await self.drain()
                facts = None
            if accepted:
                return
        self.start(action, payload, retry_same=True, facts=facts)
        await self.drain()

    def busy(self) -> bool:
        return self.active is not None and not self.active.done()

    def start(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        retry_same: bool = False,
        facts: ActionFacts | None = None,
    ) -> asyncio.Task[Any] | None:
        payload = dict(payload or {})
        if action in {"open", "dismiss"}:
            self.night_action(action)
            return None
        failure, night, failures = None, None, ()
        if action == "choose":
            calendar = facts.calendar if facts is not None else self.court.read.calendar()
        else:
            facts = self.actions() if facts is None else facts
            calendar, night, interactions, pending_nights = facts
            failures = self.failures(interactions)
            failure = (next(iter(failures), None) if action == "retry" else
                       next((i for i in failures if same_call(i, action, payload)), None) if retry_same else None)
            if action == "retry" and failure is None:
                raise InvalidAction("没有待重试的动作")
            if failure:
                action, payload = failure["action"], dict(failure["payload"])
                if action == "translation":
                    payload["nights"] = [str(n) for n in pending_nights or ()]
                    if pending := interactions.get("month"):
                        action, payload = "month", dict(pending["payload"])
        if action != "choose" and self.busy():
            raise InvalidAction("这一步还在进行")
        if not failure:
            self.accept(action, payload, calendar, night=night, failures=failures)
        self.interaction(action, "accepted", payload, calendar=calendar)
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
            if night.closed:
                return
            self.audience.open(night)
            self.audience.dismiss()
            if not self.busy():
                state = self.refresh()
                if not self.busy():
                    self.notify("state", state)
        else:
            if self.busy():
                raise InvalidAction("这一步还在进行")
            if self.audience.open():
                self.notify("state", None)

    def accept(
        self, action: str, payload: dict[str, Any], calendar: EntityView, *,
        night: NightHeader | None, failures: tuple[dict[str, Any], ...],
    ) -> None:
        payload["date"] = calendar.data
        if action == "choose":
            try:
                payload["petition"] = str(UUID(str(payload["petition"])))
                self.month.choose(payload, accept=True)
            except (ValueError, KeyError) as error:
                raise InvalidAction("无效的批红选项", 400) from error
        else:
            if any(action != "month" or i["action"] != "translation" for i in failures):
                raise InvalidAction("请重试未完成的动作")
            night = self.court.latest_night() if night is None else night
            opened = night is not None and not night.closed
            if action == "say":
                if not payload.get("words", "").strip() or night is None or not opened:
                    raise InvalidAction("请在召对中说话")
                payload.update(night_id=str(night.id), turn_id=str(uuid4()))
            elif opened:
                raise InvalidAction("请先退朝")

    def track(self, task: asyncio.Task[Any]) -> None:
        self.background.add(task)

    def start_background(self) -> None:
        task = asyncio.create_task(self.precompute())
        self.track(task)

    async def translate(
        self, *, starting: bool = False, calendar: EntityView | None = None,
        pending: tuple[UUID, ...] | None = None,
    ) -> EntityView | None:
        while True:
            if self.translation is None or self.translation.done():
                pending = self.court.pending_nights() if pending is None else pending
                if pending:
                    payload = {"nights": [str(n) for n in pending]}
                    self.interaction("translation", "accepted", payload, calendar=calendar)
                    self.translation = asyncio.create_task(self.execute("translation", payload))
            # Register translation retry before showing month acceptance.
            if starting:
                # Registration changes interactions, not the pending night set;
                # scheduled translation cannot run until the await below.
                facts = self.actions(full_night=True, pending_nights=pending)
                calendar = facts.calendar
                self.notify("state", self.presentation(facts))
                starting = False
            if self.translation is None or self.translation.done():
                return self.court.read.calendar() if calendar is None else calendar
            if not await asyncio.shield(self.translation):
                return None
            calendar, pending = None, None

    async def precompute(self) -> None:
        while self.active is not None and not self.active.done():
            await asyncio.shield(self.active)
        facts = self.actions()
        if self.failures(facts.interactions):
            return
        calendar = await self.translate(calendar=facts.calendar, pending=facts.pending_nights)
        if calendar is None:
            return
        try:
            await self.month.resume(speculative=True, date=calendar.data)
        except Exception:
            # Night speculation has a documented non-blocking failure contract.
            self.court.log.exception("night precomputation failed")

    async def execute(
        self, action: str, payload: dict[str, Any], *, starting: bool = False,
    ) -> str | bool | None:
        try:
            output = await self.work(action, payload, starting=starting)
            if output is False:
                return None
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
        if self.active is asyncio.current_task():
            self.active = None
        self.notify("state", self.refresh() if action != "translation" else None)
        return output

    async def work(
        self, action: str, payload: dict[str, Any], *, starting: bool = False,
    ) -> str | bool | None:
        if action == "say":
            night = self.court.night(UUID(payload["night_id"]), include_result=False)
            self.audience.open(night)
            return await self.audience.say(
                night, payload["words"],
                payload["turn_id"],
                partial(self.notify, "delta"),
            )
        if action == "translation":
            await self.audience.translate_pending()
            return True
        if action == "choose":
            self.month.choose(payload)
            return None
        calendar = await self.translate(starting=starting)
        if calendar is None:
            return False
        await self.month.advance(calendar)
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
