"""Shared action lifecycle between the transport adapters and the two users."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any, Literal, NamedTuple, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from ming.audience import Audience
from ming.middle.court import Court
from ming.middle.invoke import ModelSource, build_agent
from ming.middle.view import EntityView
from ming.middle.night import NightHeader
from ming.month import Month


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
    option: int = -1

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
        model: ModelSource,
        *,
        month_model: ModelSource | None = None,
    ) -> None:
        self.court = court
        self.emit: Callable[[dict[str, Any]], None] | None = None
        self.live: dict[str, str] = {}
        self.audience = Audience(court, model, self.start_background)
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
    ) -> None:
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

    def actions(self, *, night: NightHeader | None = None) -> ActionFacts:
        """Request-local materials; never retained on Game across operations."""
        calendar = self.court.calendar()
        items = self.court.interactions(calendar.data)
        if night is None and "say" in items:
            night = self.court.latest_night()
        pending_nights = self.court.pending_nights() if "translation" in items else None
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

    def presentation(self) -> dict[str, Any]:
        latest = next(iter(self.court.nights()), None)
        calendar, _, interactions, _ = self.actions(night=latest)
        night = latest.model_dump(mode="json") if latest else None
        petitions = self.court.pending_petitions(calendar.data)
        opened = self.month.opened(calendar)
        running = self.running(interactions, waiting=self.month.waiting(calendar, opened=opened, has_petitions=bool(petitions)))
        pending = next((i for i in running if i["action"] == "month"), next(iter(running), None))
        failures = self.failures(interactions)
        failure = next(iter(failures), None)
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

    def reopen(self, facts: ActionFacts | None = None) -> ActionFacts:
        facts = self.actions() if facts is None else facts
        has_petitions = self.court.has_pending_petitions(facts.calendar.data)
        if not has_petitions and facts.pending_nights is None:
            facts = facts._replace(pending_nights=self.court.pending_nights())
        self.resume(facts, has_petitions=has_petitions)
        if has_petitions or facts.pending_nights:
            self.start_background(facts)
        return facts

    def resume(self, facts: ActionFacts | None = None, *, has_petitions: bool | None = None) -> None:
        if self.busy():
            return
        facts = self.actions() if facts is None else facts
        calendar, _, interactions, _ = facts
        failures = self.failures(interactions)
        waiting = "month" in interactions and self.month.waiting(calendar, has_petitions=has_petitions)
        pending = [i for i in self.running(interactions, waiting=waiting) if not failures or i["action"] == "choose"]
        if pending:
            self.active = asyncio.create_task(self._resume(pending, facts))

    async def _resume(self, pending: list[dict[str, Any]], facts: ActionFacts) -> None:
        async def ordered() -> None:
            current = facts
            for item in pending:
                if item["action"] not in {"month", "choose"}:
                    await self.execute(item["action"], item["payload"])
                    current = self.actions()
                    if self.failures(current.interactions):
                        return
            for item in pending:
                if item["action"] == "month":
                    await self.execute(item["action"], item["payload"], facts=current)

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
        facts = self.reopen(facts)
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
            calendar = facts.calendar if facts is not None else self.court.calendar()
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
        task = asyncio.create_task(self.execute(action, payload, starting=action == "month", facts=facts))
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
            self.resume()
            if not self.busy():
                self.notify("state", None)
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

    def start_background(self, facts: ActionFacts | None = None) -> None:
        task = asyncio.create_task(self.precompute(facts))
        self.track(task)

    async def translate(
        self, *, starting: bool = False, pending: tuple[UUID, ...] | None = None,
        calendar: EntityView | None = None,
    ) -> bool:
        while True:
            if self.translation is None or self.translation.done():
                pending = self.court.pending_nights() if pending is None else pending
                if pending:
                    payload = {"nights": [str(n) for n in pending]}
                    self.interaction("translation", "accepted", payload, calendar=calendar)
                    self.translation = asyncio.create_task(self.execute("translation", payload))
            # Register translation retry before showing month acceptance.
            if starting:
                self.notify("state", None)
                starting = False
            if self.translation is None or self.translation.done():
                return True
            if not await asyncio.shield(self.translation):
                return False
            # Other nights may have closed while this batch was in flight.
            pending, calendar = None, None

    async def precompute(self, facts: ActionFacts | None = None) -> None:
        while self.active is not None and not self.active.done():
            await asyncio.shield(self.active)
            facts = None
        calendar, _, interactions, pending_nights = self.actions() if facts is None else facts
        if self.failures(interactions) or not await self.translate(pending=pending_nights, calendar=calendar):
            return
        try:
            await self.month.resume(speculative=True, date=calendar.data)
        except Exception:
            # Night speculation has a documented non-blocking failure contract.
            self.court.log.exception("night precomputation failed")

    async def execute(
        self, action: str, payload: dict[str, Any], *, starting: bool = False, facts: ActionFacts | None = None,
    ) -> str | bool | None:
        try:
            output = await self.work(action, payload, starting=starting, facts=facts)
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
        if action != "translation":
            self.resume()
        self.notify("state", None)
        return output

    async def work(
        self, action: str, payload: dict[str, Any], *, starting: bool = False, facts: ActionFacts | None = None,
    ) -> str | bool | None:
        if action == "say":
            night = self.court.night(UUID(payload["night_id"]))
            self.audience.open(night)
            return await self.audience.say(
                night, payload["words"],
                payload["turn_id"],
                partial(self.notify, "delta"),
            )
        if action == "translation":
            await self.audience.translate_pending(tuple(UUID(n) for n in payload["nights"]))
            return True
        if action == "choose":
            self.month.choose(payload)
            return None
        if not await self.translate(starting=starting, pending=facts.pending_nights if facts else None,
                                    calendar=facts.calendar if facts else None):
            return False
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
