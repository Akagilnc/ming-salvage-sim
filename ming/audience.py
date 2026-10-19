"""Audience user: free scene text in front, ordered translation behind it."""

import asyncio
import json

from uuid import UUID

from pydantic_ai import Agent
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
        self._scene = Agent(
            scene_model,
            output_type=str,
            instructions=(CONTENT / "prompts/scene_agent.md").read_text(),
        )

        @self._scene.tool_plain
        async def read_person(name: str) -> PersonView:
            """查某人的档案，姓名取账本正名。"""
            return self.court.read_person(name)

        @self._scene.tool_plain
        async def get_hall() -> list[str]:
            """看今夜殿上名单。"""
            return self.court.night(self.night_id).hall

        @self._scene.tool_plain
        async def set_hall(add: list[str], remove: list[str]) -> HallResult:
            """有人入殿或退下时先改名单；不在京师的人加不进殿。"""
            return self.court.set_hall(self.night_id, add, remove)

    @property
    def night_id(self) -> UUID:
        if self._night_id is None:
            raise ValueError("open an audience night first")
        return self._night_id

    def open(self) -> UUID:
        self._night_id = self.court.open_night()
        self._start_worker()
        return self.night_id

    def dismiss(self) -> None:
        self.court.dismiss(self.night_id)
        self._start_worker()

    def _start_worker(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._translate_pending())
        elif self._worker.done():
            self._worker.result()  # Unexpected failures stay failures; never relabel them.
            self._worker = asyncio.create_task(self._translate_pending())

    async def _translate_pending(self) -> None:
        while pending := self.court.pending_turns():
            for night_id, turn_id in pending:
                await self.court.translate_turn(night_id, turn_id)

    async def say(self, emperor_words: str) -> str:
        self._start_worker()
        night = self.court.night(self.night_id)
        if night.closed:
            raise ValueError("night already closed")
        history: list[ModelMessage] = []
        for turn in night.turns:
            history.extend(
                [
                    ModelRequest(parts=[UserPromptPart(turn.emperor_words)]),
                    ModelResponse(parts=[TextPart(turn.scene)]),
                ]
            )
        result = await self._scene.run(
            [
                json.dumps(
                    self.court.scene_material(self.night_id), ensure_ascii=False
                ),
                emperor_words,
            ],
            message_history=history,
        )
        self.court.append_turn(self.night_id, emperor_words, result.output)
        self._start_worker()
        return result.output

    async def drain(self) -> None:
        self._start_worker()
        assert self._worker is not None
        await self._worker

    async def close(self) -> None:
        try:
            await self.drain()
        finally:
            self.court.close()
