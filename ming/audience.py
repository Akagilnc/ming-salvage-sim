"""Audience user: scene rounds and the sole whole-night translation path."""

import asyncio
import json
from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import UUID

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from ming.middle.court import Court
from ming.middle.concepts import ACTING, AUDIENCE, DECREE, DECREE_EVENT, DISCOVERED, HANDLER, HELD, INTERIM, PEOPLE, SECRET
from ming.middle.translate import INSTRUCTIONS, declaration_agent
from ming.middle.declaration import NightDeclaration
from ming.middle.invoke import TextUpdate, invoke, stream_text
from ming.middle.night import NightHeader, NightView
from ming.middle.opening import CONTENT
from ming.middle.scene import HallResult
from ming.middle.records import read_records
from ming.middle.view import Officials


class Audience:
    translation = declaration_agent(
        NightDeclaration,
        "\n".join((INSTRUCTIONS, DECREE, SECRET, HANDLER, PEOPLE, ACTING, INTERIM, DISCOVERED, AUDIENCE, DECREE_EVENT, HELD)),
    )

    def __init__(self, court: Court, on_dismiss: Callable[[], None], on_hall: Callable[[list[str]], None]) -> None:
        self.court = court
        self.on_dismiss = on_dismiss
        self.on_hall = on_hall
        self.model: Model
        self._night_id: UUID | None = None
        self._turn: asyncio.Task[str] | None = None
        self._dismiss_requested: UUID | None = None

    @property
    def identity(self) -> Officials:
        return Officials(people=self.court.read.entities("audit", ids=[self.night_id])[0].data["hall"])

    @property
    def night_id(self) -> UUID:
        if self._night_id is None:
            raise ValueError("open an audience night first")
        return self._night_id

    def pending_actions(
        self, items: dict[str, Any], night: NightHeader | None, *, pending_nights: tuple[UUID, ...],
    ) -> dict[str, Any]:
        pending: dict[str, Any] = {}
        if item := items.get("say"):
            payload = item["payload"]
            if night and not night.closed and str(night.id) == payload["night_id"]:
                said = (any(t.id == payload["turn_id"] for t in night.turns) if isinstance(night, NightView)
                        else self.court.read.has_facts(night.id, "turn", date=None, detail={"id": payload["turn_id"]}))
                if not said or self.court.read.has_facts(night.id, "dismiss_requested", date=None):
                    pending["say"] = item
        if item := items.get("translation"):
            if set(item["payload"]["nights"]) & {str(n) for n in pending_nights}:
                pending["translation"] = item
        return pending

    def open(self, night: NightHeader | None = None, *, date: dict[str, Any] | None = None) -> bool:
        if night is None:
            self._night_id, created = self.court.open_night(date=date)
            closed = False
        else:
            self._night_id, created, closed = night.id, False, night.closed
        if not closed and not created and self.court.read.has_facts(self.night_id, "dismiss_requested", date=None):
            self._dismiss_requested = self.night_id
        return created

    def dismiss(self) -> None:
        if (
            self._turn is not None
            and not self._turn.done()
            and self._dismiss_requested is None
        ):
            self.court.record(self.night_id, [("dismiss_requested", {})])
        self._dismiss_requested = self.night_id
        if self._turn is None or self._turn.done():
            self._finish_dismiss()

    def _finish_dismiss(self) -> None:
        if self._dismiss_requested is not None:
            self.court.record(self._dismiss_requested, [("dismissed", {})], {"closed": True})
            self._dismiss_requested = None
            self.on_dismiss()

    async def translate_pending(self) -> None:
        for night_id in self.court.pending_nights():
            night = self.court.night(night_id)
            result = await self.court.translate(
                self.translation, night.model_dump_json(), night_id,
                model=self.model,
            )
            self.court.land(result)

    async def say(
        self, night: NightView, words: str, turn_id: str, on_delta: Callable[[TextUpdate], None] | None = None
    ) -> str:
        for turn in night.turns:
            if turn.id == turn_id:
                self._finish_dismiss()
                return turn.scene
        if night.closed:
            raise ValueError("night already closed")
        self._turn = asyncio.create_task(self._generate(words, turn_id, on_delta, night))
        return await self._turn

    async def _generate(
        self, words: str, turn_id: str, on_delta: Callable[[TextUpdate], None] | None,
        night: NightView,
    ) -> str:
        history: list[ModelMessage] = []
        for turn in night.turns:
            history.extend(
                [
                    ModelRequest(parts=[UserPromptPart(turn.emperor_words)]),
                    ModelResponse(parts=[TextPart(turn.scene)]),
                ]
            )
        try:
            result = await invoke(
                scene,
                [json.dumps({**self.court.scene_material(), "catalogue": self.court.read.record_catalogue(Officials(people=list(night.hall)))}, ensure_ascii=False), words],
                deps=self, model=self.model,
                message_history=history,
                event_stream_handler=partial(stream_text, on_delta)
                if on_delta
                else None,
            )
            self.court.record(
                self.night_id,
                [("turn", {"id": turn_id, "scene": result.output})],
                words=words,
            )
            return result.output
        finally:
            self._finish_dismiss()


async def get_hall(ctx: RunContext[Audience]) -> tuple[str, ...]:
    """看今夜殿上名单。"""
    return tuple(ctx.deps.identity.people)


async def set_hall(
    ctx: RunContext[Audience], add: list[str], remove: list[str]
) -> HallResult:
    """有人入殿或退下时先改名单；不在京师的人加不进殿。"""
    result = ctx.deps.court.set_hall(ctx.deps.night_id, add, remove)
    ctx.deps.on_hall(result.hall)
    return result


async def dismiss(ctx: RunContext[Audience]) -> None:
    """退朝：结束今夜召对。"""
    ctx.deps.dismiss()


scene = Agent(
    name="scene",
    output_type=str,
    deps_type=Audience,
    instructions="\n".join(((CONTENT / "prompts/scene_agent.md").read_text(), DECREE, SECRET, HANDLER, PEOPLE, ACTING, INTERIM)),
    tools=[read_records, get_hall, set_hall, dismiss],
)
