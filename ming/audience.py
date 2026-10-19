"""Audience user: persistent scene rounds, one background translation after dismissal."""

import asyncio
import json

from uuid import UUID

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.opening import CONTENT
from ming.middle.scene import HallResult, PersonView


class Audience:
    def __init__(self, court: Court, scene_model: Model) -> None:
        self.court = court
        self._night_id: UUID | None = None
        self._worker: asyncio.Task[None] | None = None
        self._turn: asyncio.Task[str] | None = None
        self._dismiss_requested: UUID | None = None
        self._scene = Agent(
            scene_model,
            deps_type=UUID,
            output_type=str,
            instructions=(CONTENT / "prompts/scene_agent.md").read_text(),
        )

        @self._scene.tool_plain
        async def read_person(name: str) -> PersonView:
            """查某人的档案，姓名取账本正名。"""
            return self.court.read_person(name)

        @self._scene.tool
        async def get_hall(ctx: RunContext[UUID]) -> list[str]:
            """看今夜殿上名单。"""
            return self.court.night(ctx.deps).hall

        @self._scene.tool
        async def set_hall(
            ctx: RunContext[UUID], add: list[str], remove: list[str]
        ) -> HallResult:
            """有人入殿或退下时先改名单；不在京师的人加不进殿。"""
            return self.court.set_hall(ctx.deps, add, remove)

        @self._scene.tool
        async def dismiss(ctx: RunContext[UUID]) -> None:
            """退朝：本轮回话落账后收夜，不等后台转译。"""
            self.dismiss(ctx.deps)

    @property
    def night_id(self) -> UUID:
        if self._night_id is None:
            raise ValueError("open an audience night first")
        return self._night_id

    def open(self) -> UUID:
        self._night_id = self.court.open_night()
        self._start_worker()
        return self.night_id

    def dismiss(self, night_id: UUID | None = None) -> None:
        night_id = night_id or self.night_id
        self._dismiss_requested = night_id
        if self._turn is None or self._turn.done():
            self._finish_dismiss(night_id)

    def _finish_dismiss(self, night_id: UUID) -> None:
        if self._dismiss_requested == night_id:
            self.court.dismiss(night_id)
            self._dismiss_requested = None
            self._start_worker()

    def _start_worker(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._translate_pending())
        elif self._worker.done():
            self._worker.result()  # Unexpected failures stay failures; never relabel them.
            self._worker = asyncio.create_task(self._translate_pending())

    async def _translate_pending(self) -> None:
        while pending := self.court.pending_nights():
            for night_id in pending:
                await self.court.translate_night(night_id)

    async def say(self, emperor_words: str) -> str:
        self._start_worker()
        night_id = self.night_id
        night = self.court.night(night_id)
        if night.closed:
            raise ValueError("night already closed")
        if self._turn is not None and not self._turn.done():
            raise ValueError("a scene round is already generating")
        self._turn = asyncio.create_task(self._generate(night_id, emperor_words))
        return await asyncio.shield(self._turn)

    async def _generate(self, night_id: UUID, emperor_words: str) -> str:
        night = self.court.night(night_id)
        history: list[ModelMessage] = []
        for turn in night.turns:
            history.extend(
                [
                    ModelRequest(parts=[UserPromptPart(turn.emperor_words)]),
                    ModelResponse(parts=[TextPart(turn.scene)]),
                ]
            )
        try:
            result = await self._scene.run(
                [
                    json.dumps(self.court.scene_material(), ensure_ascii=False),
                    emperor_words,
                ],
                message_history=history,
                deps=night_id,
            )
        except Exception:
            # Model failure is still raised; only the requested dismissal proceeds.
            self._finish_dismiss(night_id)
            raise
        self.court.append_turn(night_id, emperor_words, result.output)
        self._finish_dismiss(night_id)
        return result.output

    async def drain(self) -> None:
        try:
            if self._turn is not None:
                await asyncio.shield(self._turn)
        finally:
            self._start_worker()
            assert self._worker is not None
            await asyncio.shield(self._worker)

    async def close(self) -> None:
        try:
            await self.drain()
        finally:
            self.court.close()
