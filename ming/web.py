"""Local HTTP adapter; action rules live in Game, shared with the CLI."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
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
from ming.middle.invoke import Configuration, REQUIRED_SETTINGS


class Action(BaseModel):
    action: Literal[
        "new",
        "load",
        "continue",
        "menu",
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
    option: int = -1
    settings: Configuration | None = None


class Web:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.game: Game | None = None
        self.navigation = 0
        path = directory / "settings.json"
        self.configuration = (
            Configuration.model_validate_json(path.read_text())
            if path.exists() else Configuration()
        )
        self.departed: dict[str, Game] = {}
        self.retiring: dict[Game, asyncio.Task[None]] = {}
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()

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

    def snapshot(self, saves: list[str] | None = None) -> dict[str, Any]:
        return {
            "navigation": self.navigation,
            "saves": self.saves() if saves is None else saves,
            "settings": self.configuration.model_dump(),
            "required_settings": REQUIRED_SETTINGS,
            "save": self.game.court.db_path.name if self.game else None,
            "game": {**self.game.court.presentation(), "live": dict(self.game.live)}
            if self.game else None,
        }

    def emit(
        self, event: dict[str, Any] | None = None, *, source: Game | None = None,
        saves: list[str] | None = None,
    ) -> None:
        if source is not None and source is not self.game:
            return
        event = event or {"event": "state", "data": None}
        if event["event"] == "delta":
            assert self.game is not None
            event = {
                **event,
                "data": {
                    "text": event["data"],
                    "hall": list(
                        self.game.court.entity(self.game.audience.night_id).data["hall"]
                    ),
                },
            }
        elif event["event"] == "state":
            event = {**event, "data": self.snapshot(saves)}
        for queue in self.listeners:
            queue.put_nowait(event)

    def menu(self) -> None:
        game, self.game = self.game, None
        if game is not None:
            self.navigation += 1
            save = game.court.db_path.name
            self.departed[save] = game
            if game not in self.retiring:
                self.retiring[game] = asyncio.create_task(self.retire(game))

    async def retire(self, game: Game) -> None:
        try:
            await game.drain()
        finally:
            del self.retiring[game]
            save = game.court.db_path.name
            if self.departed.get(save) is game:
                del self.departed[save]
                game.court.close()

    async def close(self) -> None:
        self.emit({"event": "close", "data": None})
        self.menu()
        if self.retiring:
            await asyncio.gather(*self.retiring.values())

    async def select(self, action: str, save: str = "") -> dict[str, Any]:
        saves = self.saves() if action == "continue" else None
        if action == "continue":
            if not saves:
                raise HTTPException(404, "没有存档")
            save = saves[0]
        if action != "new":
            if Path(save).name != save or not save.endswith(".sqlite"):
                raise HTTPException(400, "无效的存档名")
            if not (self.directory / save).is_file():
                raise HTTPException(404, "存档不存在")
        if self.game is not None and self.game.court.db_path.name == save:
            navigation = self.navigation
            await self.game.drain()
            return {"save": save, "navigation": navigation}
        model = self.configuration
        game = self.departed.pop(save, None)
        opening = game is None
        if game is not None:
            game.configure(model, month_model=model.month_model)
        else:
            if action == "new":
                try:
                    court = Court.new_game(self.directory)
                except FileNotFoundError as error:
                    raise HTTPException(503, str(error)) from error
            else:
                court = Court(self.directory / save)
            game = Game(court, model, month_model=model.month_model)
            game.emit = partial(self.emit, source=game)
        self.menu()
        self.game = game
        self.navigation += 1
        if opening:
            game.resume()
        self.emit(saves=saves)
        return {"save": game.court.db_path.name, "navigation": self.navigation}

    async def state(self, request: Request) -> JSONResponse:
        return JSONResponse(self.snapshot())

    async def records(self, request: Request) -> JSONResponse:
        if self.game is None:
            raise HTTPException(409, "请先打开一局")
        return JSONResponse(self.game.court.read_records("emperor"))

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
        if action.action == "menu":
            if self.game is not None:
                self.menu()
                self.emit()
            return Response(status_code=204)
        if action.action == "settings":
            return self.configure(action)
        if self.game is None:
            raise HTTPException(409, "请先打开一局")
        try:
            task = self.game.start(
                action.action,
                action.model_dump(mode="json", include={"words", "petition", "option"}),
            )
        except InvalidAction as error:
            raise HTTPException(error.status, str(error)) from error
        if task is not None:
            await asyncio.shield(task)
        return Response(status_code=204)

    def configure(self, action: Action) -> Response:
        if action.settings is None:
            raise HTTPException(400, "缺少设置")
        if self.game is not None and self.game.busy():
            raise HTTPException(409, "请等当前动作结束")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "settings.json"
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(action.settings.model_dump_json())
        self.configuration = action.settings
        if self.game is not None:
            self.game.configure(action.settings, month_model=action.settings.month_model)
        self.emit()
        return Response(status_code=204)


def create_app(
    directory: Path,
    static: Path | None = None,
) -> Starlette:
    web = Web(directory)

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
