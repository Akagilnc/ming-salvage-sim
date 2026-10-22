"""Audience user: scene rounds and the sole whole-night translation path."""

import asyncio
import json
from collections.abc import Callable
from functools import partial
from uuid import UUID

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from ming.middle.court import Court
from ming.middle.declaration import NightDeclaration
from ming.middle.invoke import ModelSource, build_agent, invoke, stream_text
from ming.middle.opening import CONTENT
from ming.middle.scene import HallResult, PersonView


class Audience:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self._night_id: UUID | None = None
        self._turn: asyncio.Task[str] | None = None
        self._dismiss_requested: UUID | None = None
        self.translation = court.translation_agent(NightDeclaration)

        async def read_person(ctx: RunContext[Audience], name: str) -> PersonView:
            """查某人的档案，姓名取账本正名。"""
            return ctx.deps.court.read_person(name)

        async def get_hall(ctx: RunContext[Audience]) -> list[str]:
            """看今夜殿上名单。"""
            return ctx.deps.court.night(ctx.deps.night_id).hall

        async def set_hall(
            ctx: RunContext[Audience], add: list[str], remove: list[str]
        ) -> HallResult:
            """有人入殿或退下时先改名单；不在京师的人加不进殿。"""
            return ctx.deps.court.set_hall(ctx.deps.night_id, add, remove)

        async def dismiss(ctx: RunContext[Audience]) -> None:
            """退朝：本轮回话落账后收夜，不等后台转译。"""
            ctx.deps.dismiss()

        self.scene = build_agent(
            model,
            name="scene",
            output_type=str,
            deps_type=Audience,
            instructions=(CONTENT / "prompts/scene_agent.md").read_text(),
            tools=[read_person, get_hall, set_hall, dismiss],
        )

    @property
    def night_id(self) -> UUID:
        if self._night_id is None:
            raise ValueError("open an audience night first")
        return self._night_id

    def open(self, night_id: UUID | None = None) -> UUID:
        self._night_id = night_id or self.court.open_night()
        if not self.court.night(self.night_id).closed and any(
            f.kind == "dismiss_requested" and f.entity_id == self.night_id
            for f in self.court.facts(
                "audit", entity_id=self.night_id, kind="dismiss_requested"
            )
        ):
            self._dismiss_requested = self.night_id
        return self.night_id

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
            self.court.dismiss(self._dismiss_requested)
            self._dismiss_requested = None

    async def translate_pending(self) -> None:
        while pending := self.court.pending_nights():
            night_id = pending[0]
            night = self.court.night(night_id)
            result = await self.court.translate(
                self.translation, night.model_dump_json()
            )
            self.court.land(result, night_id)

    async def say(
        self, words: str, turn_id: str, on_delta: Callable[[str], None] | None = None
    ) -> str:
        night = self.court.night(self.night_id)
        for turn in night.turns:
            if turn.id == turn_id:
                self._finish_dismiss()
                return turn.scene
        if night.closed:
            raise ValueError("night already closed")
        self._turn = asyncio.create_task(self._generate(words, turn_id, on_delta))
        return await self._turn

    async def _generate(
        self, words: str, turn_id: str, on_delta: Callable[[str], None] | None
    ) -> str:
        history: list[ModelMessage] = []
        for turn in self.court.night(self.night_id).turns:
            history.extend(
                [
                    ModelRequest(parts=[UserPromptPart(turn.emperor_words)]),
                    ModelResponse(parts=[TextPart(turn.scene)]),
                ]
            )
        try:
            result = await invoke(
                self.scene,
                [json.dumps(self.court.scene_material(), ensure_ascii=False), words],
                deps=self,
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
