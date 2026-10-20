"""Local ASGI boundary: four capabilities, no durable game state here."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from sse_starlette import EventSourceResponse
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ming.__main__ import precompute
from ming.audience import Audience
from ming.middle.cli_model import ClaudeCliModel
from ming.middle.court import Court
from ming.month import Month


class Settings(BaseModel):
    backend: Literal["api", "claude-cli"] = "api"
    model: str = "gpt-4.1"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""

    def build_model(self) -> Model:
        if self.backend == "claude-cli":
            return ClaudeCliModel(self.model)
        return OpenAIChatModel(
            self.model,
            provider=OpenAIProvider(
                base_url=self.base_url,
                api_key=self.api_key or "not-configured",
            ),
        )


class Action(BaseModel):
    action: Literal[
        "new",
        "load",
        "continue",
        "settings",
        "open",
        "say",
        "dismiss",
        "month",
        "choose",
        "retry",
    ]
    save: str = ""
    words: str = ""
    petition: UUID | None = None
    option: int = 0
    settings: Settings | None = None


class Web:
    def __init__(
        self, directory: Path, model_factory: Callable[[Settings], Model]
    ) -> None:
        self.directory = directory
        self.model_factory = model_factory
        self.court: Court | None = None
        self.audience: Audience | None = None
        self.month: Month | None = None
        self.active: asyncio.Task[None] | None = None
        self.background: set[asyncio.Task[None]] = set()
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    def settings(self) -> Settings:
        path = self.directory / "settings.json"
        return (
            Settings.model_validate_json(path.read_text())
            if path.exists()
            else Settings()
        )

    def saves(self) -> list[str]:
        return [
            p.name
            for p in sorted(
                self.directory.glob("*.sqlite"),
                key=lambda p: max(
                    f.stat().st_mtime_ns
                    for f in (p, p.with_name(p.name + "-wal"))
                    if f.exists()
                ),
                reverse=True,
            )
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "saves": self.saves(),
            "settings": self.settings().model_dump(),
            "save": self.court.db_path.name if self.court else None,
            "game": self.court.presentation() if self.court else None,
        }

    def emit(self, event: dict[str, Any]) -> None:
        if event["event"] == "delta":
            assert self.court is not None
            event = {
                **event,
                "data": {
                    "text": event["data"],
                    "hall": self.court.presentation()["night"]["hall"],
                },
            }
        for queue in self.listeners:
            queue.put_nowait(event)

    async def close(self, shutdown: bool = True) -> None:
        if shutdown:
            self.emit({"event": "close", "data": None})
        if self.active is not None:
            await asyncio.shield(self.active)
        if self.background:
            # Audience persists translation failures; background_done logs any
            # unexpected scheduling failure. Shutdown still waits for live work.
            await asyncio.gather(*self.background, return_exceptions=True)
        if self.audience is not None:
            try:
                await self.audience.close()
            finally:
                self.audience = None
                self.court = None

    async def select(self, action: str, save: str = "") -> dict[str, Any]:
        if action == "continue":
            if not self.saves():
                raise HTTPException(404, "没有存档")
            save = self.saves()[0]
        if action != "new":
            if Path(save).name != save or not save.endswith(".sqlite"):
                raise HTTPException(400, "无效的存档名")
            if not (self.directory / save).is_file():
                raise HTTPException(404, "存档不存在")
        await self.close(shutdown=False)
        model = self.model_factory(self.settings())
        self.court = (
            Court.new_game(self.directory, model)
            if action == "new"
            else Court(self.directory / save, model)
        )
        self.audience = Audience(self.court, model)
        self.month = Month(
            self.court,
            model,
            lambda text: self.emit({"event": "gazette", "data": text}),
        )
        self.court.observe(
            lambda: self.emit({"event": "state", "data": self.snapshot()})
        )
        nights = self.court.nights()
        if nights and not nights[-1].closed:
            self.audience.open()
        pending = self.court.presentation()["pending"]
        failure = self.court.presentation()["failure"]
        if pending and pending["action"] == "say":
            # A process died, not merely an HTTP connection. Retry only on request.
            self.court.interaction(
                "say",
                "failed",
                {
                    **pending["payload"],
                    "type": "InterruptedError",
                    "log": str(self.court.db_path.with_suffix(".errors.log")),
                },
            )
            self.court.log.error("process interrupted a scene round")
        elif not failure and (
            pending
            or (self.court.world_route(create=False) and not self.court.petitions())
        ):
            resume_action = pending["action"] if pending else "month"
            resuming = Action(
                action="retry" if resume_action == "translation" else resume_action
            )
            self.active = asyncio.create_task(self.execute(resuming))
        if self.court.pending_nights() and not failure and not pending:
            self.start_background()
        return {"save": self.court.db_path.name}

    async def state(self, request: Request) -> JSONResponse:
        return JSONResponse(self.snapshot())

    async def records(self, request: Request) -> JSONResponse:
        if self.court is None:
            raise HTTPException(409, "请先打开一局")
        return JSONResponse(await self.court.read_records("emperor"))

    async def stream(self, request: Request) -> EventSourceResponse:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.listeners.add(queue)
        queue.put_nowait({"event": "state", "data": self.snapshot()})
        return EventSourceResponse(self.consume(queue))

    async def consume(
        self, queue: asyncio.Queue[dict[str, Any]]
    ) -> AsyncIterator[dict[str, str]]:
        try:
            while True:
                event = await queue.get()
                if event["event"] == "close":
                    return
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
        finally:
            self.listeners.discard(queue)

    def start_background(self) -> None:
        assert self.audience is not None and self.month is not None
        task = asyncio.create_task(precompute(self.audience, self.month))
        self.background.add(task)
        task.add_done_callback(self.background_done)

    def background_done(self, task: asyncio.Task[None]) -> None:
        self.background.discard(task)
        assert self.court is not None
        if error := task.exception():
            # Audience persists its visible failure. Speculative month failures
            # are logged by Month.prepare, per its documented recovery contract.
            self.court.log.error("background translation failed", exc_info=error)
        self.emit({"event": "state", "data": self.snapshot()})

    async def execute(self, action: Action) -> None:
        assert (
            self.audience is not None
            and self.month is not None
            and self.court is not None
        )
        try:
            if action.action == "say":
                await self.audience.say(
                    action.words,
                    lambda text: self.emit({"event": "delta", "data": text}),
                )
                if self.court.night(self.audience.night_id).closed:
                    self.start_background()
            elif action.action == "choose":
                assert action.petition is not None
                await self.month.choose(action.petition, action.option)
                if self.court.world_route(create=False) is not None and (
                    self.active is None
                    or self.active.done()
                    or self.active is asyncio.current_task()
                ):
                    await self.month.advance()
            else:
                if action.action == "month":
                    # Retain the player's original action before waiting on translation.
                    self.court.interaction("month", "running")
                if self.court.pending_nights():
                    self.audience.retry_translation()
                await self.audience.drain()
                if self.court.pending_nights():
                    return  # The failed translation already has its persisted retry line.
                if action.action == "month":
                    await self.month.advance()
                    return
                self.start_background()
        except Exception:
            # The HTTP consumer may be gone; retain the real failure and log location.
            self.court.log.exception("action=%s", action.action)
            if not self.court.presentation()["failure"]:
                self.court.interaction(
                    action.action,
                    "failed",
                    {
                        "log": str(self.court.db_path.with_suffix(".errors.log")),
                    },
                )
        finally:
            self.emit({"event": "done", "data": self.snapshot()})

    async def actions(self, request: Request) -> Response:
        try:
            action = Action.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            raise HTTPException(400, "无效的动作") from error
        if action.action in {"new", "load", "continue"}:
            return JSONResponse(await self.select(action.action, action.save))
        if action.action == "settings":
            return await self.configure(action)
        return await self.play(action)

    async def play(self, action: Action) -> Response:
        if self.court is None or self.audience is None:
            raise HTTPException(409, "请先打开一局")
        if action.action == "dismiss":
            self.audience.dismiss()
            self.start_background()
            return JSONResponse(self.snapshot())
        if (
            action.action != "choose"
            and self.active is not None
            and not self.active.done()
        ):
            raise HTTPException(409, "这一步还在进行")
        if action.action == "open":
            self.audience.open()
            return JSONResponse(self.snapshot())
        if action.action == "retry":
            failure = self.court.presentation()["failure"]
            if not failure:
                raise HTTPException(409, "没有待重试的动作")
            pending = self.court.presentation()["pending"]
            resume_action = failure["action"]
            if resume_action == "translation":
                resume_action = (
                    "month" if pending and pending["action"] == "month" else "retry"
                )
            action = Action(action=resume_action, **failure["payload"])
        if action.action == "month" and self.court.presentation()["face"] == "audience":
            raise HTTPException(409, "请先退朝")
        if action.action == "say" and (
            not action.words.strip() or self.court.presentation()["face"] != "audience"
        ):
            raise HTTPException(409, "请在召对中说话")
        if action.action == "choose" and not any(
            p.id == action.petition and 0 <= action.option < len(p.options)
            for p in self.court.petitions()
        ):
            raise HTTPException(400, "无效的批红选项")
        task = asyncio.create_task(self.execute(action))
        if (
            action.action == "choose"
            and self.active is not None
            and not self.active.done()
        ):
            self.background.add(task)
            task.add_done_callback(self.background_done)
        else:
            self.active = task
        # The action outlives a disconnected POST; only /stream carries events.
        await asyncio.shield(task)
        return Response(status_code=204)

    async def configure(self, action: Action) -> JSONResponse:
        if action.settings is None:
            raise HTTPException(400, "缺少设置")
        if self.active is not None and not self.active.done():
            raise HTTPException(409, "请等当前动作结束")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "settings.json"
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(action.settings.model_dump_json())
        if self.court is not None:
            await self.select("load", self.court.db_path.name)
        return JSONResponse(self.snapshot())


def create_app(
    directory: Path,
    model_factory: Callable[[Settings], Model] = Settings.build_model,
    static: Path | None = None,
) -> Starlette:
    web = Web(directory, model_factory)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        yield
        await web.close()

    routes: list[Route | Mount] = [
        Route("/state", web.state),
        Route("/records", web.records),
        Route("/stream", web.stream),
        Route("/actions", web.actions, methods=["POST"]),
    ]
    if static is not None:
        routes.append(Mount("/", StaticFiles(directory=static, html=True)))
    app = Starlette(lifespan=lifespan, routes=routes)
    app.state.web = web
    return app
