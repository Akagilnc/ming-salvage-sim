"""Audience user: persistent scene rounds, one background translation after dismissal."""

import asyncio
import json
from collections.abc import AsyncIterable, Callable

from uuid import UUID

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    AgentStreamEvent,
    PartStartEvent,
    PartDeltaEvent,
    TextPartDelta,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.invoke import invoke, transport_model
from ming.middle.opening import CONTENT
from ming.middle.scene import HallResult, PersonView


class Audience:
    def __init__(self, court: Court, scene_model: Model) -> None:
        self.court = court
        self._night_id: UUID | None = None
        self._worker: asyncio.Task[None] | None = None
        self._turn: asyncio.Task[str] | None = None
        self._dismiss_requested: UUID | None = None
        async def read_person(name: str) -> PersonView:
            """查某人的档案，姓名取账本正名。"""
            return self.court.read_person(name)

        async def get_hall() -> list[str]:
            """看今夜殿上名单。"""
            return self.court.night(self.night_id).hall

        async def set_hall(add: list[str], remove: list[str]) -> HallResult:
            """有人入殿或退下时先改名单；不在京师的人加不进殿。"""
            return self.court.set_hall(self.night_id, add, remove)

        async def dismiss() -> None:
            """退朝：本轮回话落账后收夜，不等后台转译。"""
            self.dismiss()

        tools = [read_person, get_hall, set_hall, dismiss]
        self._scene = Agent(
            transport_model(scene_model, tools),
            output_type=str,
            instructions=(CONTENT / "prompts/scene_agent.md").read_text(),
            tools=tools,
        )

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
        try:
            while pending := self.court.pending_nights():
                for night_id in pending:
                    await self.court.translate_night(night_id)
        except Exception as error:
            self.court.interaction(
                "translation",
                "failed",
                {
                    "type": type(error).__name__,
                    "log": str(self.court.db_path.with_suffix(".errors.log")),
                },
            )
            raise
        else:
            attempts = [
                f.detail
                for f in self.court.products(self.court.calendar().id)
                if f.kind == "interaction" and f.detail["action"] == "translation"
            ]
            if attempts and attempts[-1]["status"] != "done":
                self.court.interaction("translation", "done")

    async def say(
        self, emperor_words: str, on_delta: Callable[[str], None] | None = None
    ) -> str:
        self._start_worker()
        night_id = self.night_id
        night = self.court.night(night_id)
        if night.closed:
            raise ValueError("night already closed")
        if self._turn is not None and not self._turn.done():
            raise ValueError("a scene round is already generating")
        self.court.interaction(
            "say", "running", {"words": emperor_words, "night_id": str(night_id)}
        )
        self._turn = asyncio.create_task(
            self._generate(night_id, emperor_words, on_delta)
        )
        return await asyncio.shield(self._turn)

    async def _generate(
        self,
        night_id: UUID,
        emperor_words: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        async def events(
            _ctx: RunContext[None], stream: AsyncIterable[AgentStreamEvent]
        ) -> None:
            async for event in stream:
                if (
                    on_delta
                    and isinstance(event, PartStartEvent)
                    and isinstance(event.part, TextPart)
                ):
                    on_delta(event.part.content)
                elif (
                    on_delta
                    and isinstance(event, PartDeltaEvent)
                    and isinstance(event.delta, TextPartDelta)
                ):
                    on_delta(event.delta.content_delta)

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
            result = await invoke(
                self._scene,
                [
                    json.dumps(self.court.scene_material(), ensure_ascii=False),
                    emperor_words,
                ],
                message_history=history,
                event_stream_handler=events if on_delta else None,
            )
        except Exception as error:
            self.court.interaction(
                "say",
                "failed",
                {
                    "words": emperor_words,
                    "night_id": str(night_id),
                    "type": type(error).__name__,
                    "log": str(self.court.db_path.with_suffix(".errors.log")),
                },
            )
            self.court.log.exception("audience night=%s", night_id)
            # Model failure is still raised; only the requested dismissal proceeds.
            self._finish_dismiss(night_id)
            raise
        self.court.append_turn(night_id, emperor_words, result.output)
        self.court.interaction("say", "done")
        self._finish_dismiss(night_id)
        return result.output

    def retry_translation(self) -> None:
        """Explicitly acknowledge the failed worker before retrying its missing work."""
        if self._worker is not None and self._worker.done():
            self._worker = None
        self.court.interaction("translation", "running")
        self._start_worker()

    async def drain(self) -> None:
        try:
            if self._turn is not None and not self._turn.done():
                await asyncio.shield(self._turn)
        finally:
            self._start_worker()
            assert self._worker is not None
            await asyncio.shield(self._worker)

    async def close(self, acknowledge_failure: bool = False) -> None:
        try:
            await self.drain()
        except Exception as error:
            # Selecting another backend/game acknowledges only the exact worker
            # failure already logged and persisted. Cleanup failures still escape.
            if not (
                acknowledge_failure
                and self._worker is not None
                and self._worker.done()
                and self._worker.exception() is error
            ):
                raise
        finally:
            self.court.close()
