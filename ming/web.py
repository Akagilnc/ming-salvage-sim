"""Local HTTP adapter; action rules live in Game, shared with the CLI."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from sse_starlette import EventSourceResponse
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ming.game import Game, InvalidAction
from ming.middle.court import Court
from ming.middle.invoke import ModelSource, Settings as Settings


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
        self, directory: Path, model_factory: Callable[[Settings], ModelSource]
    ) -> None:
        self.directory = directory
        self.model_factory = model_factory
        self.game: Game | None = None
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
            "save": self.game.court.db_path.name if self.game else None,
            "game": self.game.presentation() if self.game else None,
        }

    def emit(self, event: dict[str, Any]) -> None:
        if event["event"] == "delta":
            assert self.game is not None
            event = {
                **event,
                "data": {
                    "text": event["data"],
                    "hall": self.game.presentation()["night"]["hall"],
                },
            }
        elif event["event"] == "done":
            event = {**event, "data": self.snapshot()}
        for queue in self.listeners:
            queue.put_nowait(event)

    async def close(self, shutdown: bool = True) -> None:
        if shutdown:
            self.emit({"event": "close", "data": None})
        if self.game is not None:
            await self.game.close()
            self.game = None

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
        court = (
            Court.new_game(self.directory, model)
            if action == "new"
            else Court(self.directory / save, model)
        )
        self.game = Game(court, model, self.emit)
        court.observe(lambda: self.emit({"event": "state", "data": self.snapshot()}))
        self.game.resume()
        return {"save": court.db_path.name}

    async def state(self, request: Request) -> JSONResponse:
        return JSONResponse(self.snapshot())

    async def records(self, request: Request) -> JSONResponse:
        if self.game is None:
            raise HTTPException(409, "请先打开一局")
        return JSONResponse(await self.game.court.read_records("emperor"))

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

    async def actions(self, request: Request) -> Response:
        try:
            action = Action.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            raise HTTPException(400, "无效的动作") from error
        if action.action in {"new", "load", "continue"}:
            return JSONResponse(await self.select(action.action, action.save))
        if action.action == "settings":
            return await self.configure(action)
        if self.game is None:
            raise HTTPException(409, "请先打开一局")
        try:
            task = self.game.start(
                action.action,
                action.model_dump(mode="json", include={"words", "petition", "option"}),
            )
        except InvalidAction as error:
            raise HTTPException(error.status, str(error)) from error
        if task is None:
            return JSONResponse(self.snapshot())
        await asyncio.shield(task)
        return Response(status_code=204)

    async def configure(self, action: Action) -> JSONResponse:
        if action.settings is None:
            raise HTTPException(400, "缺少设置")
        if self.game is not None and self.game.busy():
            raise HTTPException(409, "请等当前动作结束")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "settings.json"
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(action.settings.model_dump_json())
        if self.game is not None:
            await self.select("load", self.game.court.db_path.name)
        return JSONResponse(self.snapshot())


def create_app(
    directory: Path,
    model_factory: Callable[[Settings], ModelSource] = lambda settings: settings,
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
