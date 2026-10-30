"""Package entry; JSONL schedules month and speculative night work without blocking."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import get_args
from uuid import UUID

from ming.game import Game
from ming.middle.invoke import Configuration, Settings
from ming.middle.court import Court
from ming.middle.opening import CONTENT, build_opening
from ming.middle.view import PublicIdentity


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ming")
    commands = result.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a new game")
    new.add_argument("--directory", type=Path, default=Path("saves"))
    build = commands.add_parser("build-opening", help="Rebuild the opening template")
    build.add_argument("--content", type=Path, default=CONTENT)
    build.add_argument("--output", type=Path)
    read = commands.add_parser("read", help="Read the selected game")
    audience = commands.add_parser(
        "audience", help="JSONL: say/dismiss/open/month/choose/drain/state"
    )
    month = commands.add_parser("month", help="Advance month or resume missing work")
    choose = commands.add_parser(
        "choose", help="Answer a petition by zero-based option"
    )
    choose.add_argument("--petition", type=UUID, required=True)
    choose.add_argument("--option", type=int, required=True)
    for sub in (read, audience, month, choose):
        sub.add_argument("--db", type=Path, required=True)
    read.add_argument("--replay", action="store_true")
    for sub in (new, read):
        sub.add_argument(
            "--identity", choices=get_args(PublicIdentity), default="emperor"
        )
    for sub in (new, read, audience, month, choose):
        for prefix in ("", "month-"):
            sub.add_argument(
                f"--{prefix}backend",
                choices=get_args(Settings.model_fields["backend"].annotation) + (("",) if prefix else ()),
                default="claude-cli" if not prefix else "",
                help=("Month channel falls back to the main channel unless complete"
                      if prefix else "Main channel for audience and night translation"),
            )
            for field in ("model", "base_url", "api_key", "effort"):
                sub.add_argument(
                    f"--{prefix}{field.replace('_', '-')}",
                    default=Settings.model_fields[field].default if not prefix else "",
                )
    return result


async def conversation(court: Court, settings: Configuration) -> None:
    game = Game(court, settings, month_model=settings.month_model)
    game.resume()
    await game.drain()
    state = court.presentation()
    night = state["night"]["id"] if state["night"] else None
    if state["face"] != "month" and not state["failure"]:
        game.start("open")
        night = str(game.audience.night_id)
    try:
        print(json.dumps({"night": night}), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            action = request.pop("action")
            scene = None
            if action == "drain":
                await game.drain()
            elif action != "state":
                task = game.start(action, request, failures=court.failures())
                if task is not None and action != "month":
                    scene = await asyncio.shield(task)
            state = court.presentation()
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
    game = Game(court, court.model, month_model=args.settings.month_model)
    await game.command(
        args.command,
        {"petition": str(args.petition), "option": args.option}
        if args.command == "choose"
        else {},
    )
    state = court.presentation()
    print(
        json.dumps(
            {"date": state["date"], "petitions": state["petitions"]}, ensure_ascii=False
        )
    )
    if state["failure"]:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "build-opening":
        print(json.dumps({"template": str(build_opening(args.content, args.output))}))
        return
    args.settings = Configuration.model_validate({
        **{key: getattr(args, key) for key in Settings.model_fields},
        "month_model": {key: getattr(args, f"month_{key}") for key in Settings.model_fields},
    })
    model = args.settings
    court = (
        Court.new_game(args.directory, model)
        if args.command == "new"
        else Court(args.db, model)
    )
    try:
        if args.command in {"month", "choose"}:
            asyncio.run(month_action(court, args))
            return
        if args.command == "audience":
            asyncio.run(conversation(court, model))
            return
        print(
            json.dumps(
                {
                    "db": str(court.db_path),
                    **court.read_records(args.identity, replay=getattr(args, "replay", False)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        court.close()


if __name__ == "__main__":
    main()
