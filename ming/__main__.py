"""Package entry; JSONL schedules month and speculative night work without blocking."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import get_args
from uuid import UUID

from ming.game import Game
from ming.middle.invoke import ModelSource
from ming.middle.court import Court
from ming.middle.opening import CONTENT
from ming.middle.view import PublicIdentity


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ming")
    commands = result.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a new game")
    new.add_argument("--directory", type=Path, default=Path("saves"))
    new.add_argument("--content", type=Path, default=CONTENT)
    read = commands.add_parser("read", help="Read the selected game")
    audience = commands.add_parser(
        "audience", help="JSONL: say/dismiss/open/month/choose/drain/state"
    )
    audience.add_argument(
        "--scene-model",
        required=True,
        help="Pydantic AI model id; native text and tools required",
    )
    month = commands.add_parser("month", help="Advance month or resume missing work")
    choose = commands.add_parser(
        "choose", help="Answer a petition by zero-based option"
    )
    choose.add_argument("--petition", type=UUID, required=True)
    choose.add_argument("--option", type=int, required=True)
    for sub in (month, choose):
        sub.add_argument("--model", required=True)
    for sub in (read, audience, month, choose):
        sub.add_argument("--db", type=Path, required=True)
    read.add_argument("--replay", action="store_true")
    for sub in (new, read):
        sub.add_argument(
            "--identity", choices=get_args(PublicIdentity), default="emperor"
        )
    for sub in (new, read, audience, month, choose):
        sub.add_argument(
            "--translation-model",
            default="claude-cli",
            help="claude-cli or a Pydantic AI model id",
        )
    return result


async def conversation(court: Court, scene_model: ModelSource) -> None:
    game = Game(court, scene_model)
    game.resume()
    await game.drain()
    if game.presentation()["face"] != "month" and not game.presentation()["failure"]:
        game.start("open")
    try:
        night = game.presentation()["night"]
        print(json.dumps({"night": night["id"] if night else None}), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            action = request.pop("action")
            scene = None
            if action == "drain":
                await game.drain()
            elif action != "state":
                task = game.start(action, request, repeat=True)
                if task is not None and action != "month":
                    scene = await asyncio.shield(task)
            state = game.presentation()
            failure = state["failure"]
            print(
                json.dumps(
                    {
                        "scene": scene,
                        "night": state["night"],
                        "month_running": state["running"]
                        and state["pending"]["action"] in {"month", "choose"},
                        "month_error": {
                            key: failure["payload"][key]
                            for key in ("type", "message", "log")
                        }
                        if failure
                        else None,
                        "petitions": state["petitions"],
                        "date": state["date"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        await game.drain()


async def month_action(court: Court, args: argparse.Namespace) -> None:
    game = Game(court, args.model)
    await game.command(
        args.command,
        {"petition": str(args.petition), "option": args.option}
        if args.command == "choose"
        else {},
    )
    state = game.presentation()
    print(
        json.dumps(
            {"date": state["date"], "petitions": state["petitions"]}, ensure_ascii=False
        )
    )
    if state["failure"]:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    model = args.translation_model
    court = (
        Court.new_game(args.directory, model, args.content)
        if args.command == "new"
        else Court(args.db, model)
    )
    try:
        if args.command in {"month", "choose"}:
            asyncio.run(month_action(court, args))
            return
        if args.command == "audience":
            asyncio.run(conversation(court, args.scene_model))
            return
        print(
            json.dumps(
                {
                    "db": str(court.db_path),
                    "entities": [
                        e.model_dump(mode="json")
                        for e in court.entities(
                            args.identity, getattr(args, "replay", False)
                        )
                    ],
                    "facts": [
                        f.model_dump(mode="json")
                        for f in court.facts(
                            args.identity, getattr(args, "replay", False)
                        )
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        court.close()


if __name__ == "__main__":
    main()
