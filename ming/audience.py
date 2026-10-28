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
from ming.middle.concepts import ACTING, AUDIENCE, DECREE, DECREE_EVENT, DISCOVERED, HANDLER, HELD, INTERIM, PEOPLE, SECRET
from ming.middle.translate import INSTRUCTIONS
from ming.middle.declaration import NightDeclaration
from ming.middle.invoke import ModelSource, TextUpdate, build_agent, invoke, stream_text
from ming.middle.opening import CONTENT
from ming.middle.scene import HallResult
from ming.middle.night import NightView
from ming.middle.records import read_records
from ming.middle.view import EntityView, Officials


class Audience:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self._night_id: UUID | None = None
        self._turn: asyncio.Task[tuple[str, bool]] | None = None
        self._dismiss_requested: UUID | None = None
        self.translation = court.translation_agent(
            NightDeclaration,
            "\n".join((INSTRUCTIONS, DECREE, SECRET, HANDLER, PEOPLE, ACTING, INTERIM, DISCOVERED, AUDIENCE, DECREE_EVENT, HELD)),
        )

        async def get_hall(ctx: RunContext[Audience]) -> tuple[str, ...]:
            """看今夜殿上名单。"""
            return tuple(ctx.deps.identity.people)

        async def set_hall(
            ctx: RunContext[Audience], add: list[str], remove: list[str]
        ) -> HallResult:
            """有人入殿或退下时先改名单；不在京师的人加不进殿。"""
            return ctx.deps.court.set_hall(ctx.deps.night_id, add, remove)

        async def dismiss(ctx: RunContext[Audience]) -> None:
            """退朝：结束今夜召对。"""
            ctx.deps.dismiss()

        self.scene = build_agent(
            model,
            name="scene",
            output_type=str,
            deps_type=Audience,
            instructions="\n".join(((CONTENT / "prompts/scene_agent.md").read_text(), DECREE, SECRET, HANDLER, PEOPLE, ACTING, INTERIM)),
            tools=[read_records, get_hall, set_hall, dismiss],
        )

    @property
    def identity(self) -> Officials:
        return Officials(people=self.court.entity(self.night_id).data["hall"])

    @property
    def night_id(self) -> UUID:
        if self._night_id is None:
            raise ValueError("open an audience night first")
        return self._night_id

    def open(self, night_id: UUID | None = None) -> NightView:
        night = self.court.night(night_id or self.court.open_night())
        self._night_id = night.id
        if not night.closed and self.court.facts(
            "audit", entity_id=self.night_id, kind="dismiss_requested"
        ):
            self._dismiss_requested = self.night_id
        return night

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

    def _finish_dismiss(self) -> bool:
        if self._dismiss_requested is None:
            return False
        self.court.dismiss(self._dismiss_requested)
        self._dismiss_requested = None
        return True

    async def translate_pending(self, pending: tuple[UUID, ...], calendar: EntityView) -> None:
        while pending:
            for night_id in pending:
                night = self.court.night(night_id)
                if night.result is not None:
                    continue
                result, materials = await self.court.translate(
                    self.translation, night.model_dump_json(), night, calendar=calendar,
                )
                self.court.land(result, night_id, calendar=calendar, materials=materials)
            pending = self.court.pending_nights()

    async def say(
        self, words: str, turn_id: str, on_delta: Callable[[TextUpdate], None] | None,
        *, night: NightView, calendar: EntityView,
    ) -> tuple[str, bool]:
        for turn in night.turns:
            if turn.id == turn_id:
                closed = self._finish_dismiss()
                return turn.scene, night.closed or closed
        if night.closed:
            raise ValueError("night already closed")
        self._turn = asyncio.create_task(self._generate(words, turn_id, on_delta, night=night, calendar=calendar))
        return await self._turn

    async def _generate(
        self, words: str, turn_id: str, on_delta: Callable[[TextUpdate], None] | None,
        *, night: NightView, calendar: EntityView,
    ) -> tuple[str, bool]:
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
                self.scene,
                [json.dumps({**self.court.scene_material(calendar), "catalogue": self.court.record_catalogue(Officials(people=list(night.hall)))}, ensure_ascii=False), words],
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
        finally:
            closed = self._finish_dismiss()
        return result.output, closed
