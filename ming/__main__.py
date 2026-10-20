"""Package entry; JSONL schedules month and speculative night work without blocking."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import get_args
from uuid import UUID

from pydantic_ai.models import Model, infer_model

from ming.audience import Audience
from ming.month import Month
from ming.middle.cli_model import ClaudeCliModel
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


def resolve_model(name: str) -> Model:
    return ClaudeCliModel() if name == "claude-cli" else infer_model(name)


async def conversation(court: Court, scene_model: Model) -> None:
    audience = Audience(court, scene_model)
    month = Month(court, scene_model)
    background: list[asyncio.Task[None]] = []
    advancing: asyncio.Task[object] | None = None

    async def precompute() -> None:
        await audience.drain()
        await asyncio.gather(
            *(month.prepare(e.id, background=True) for e in court.approved_decrees())
        )

    try:
        print(json.dumps({"night": str(audience.open())}), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            action = request["action"]
            scene = None
            if action == "say":
                scene = await audience.say(request["words"])
            elif action in {"dismiss", "open"}:
                {"dismiss": audience.dismiss, "open": audience.open}[action]()
            elif action == "month":
                if advancing is None or advancing.done():
                    advancing = asyncio.create_task(month.advance())
            elif action == "choose":
                await month.choose(
                    UUID(request["petition"]),
                    request["option"],
                    background=advancing is None
                    or (
                        advancing.done()
                        and advancing.exception() is None
                        and not advancing.result()
                    ),
                )
            elif action == "drain":
                await audience.drain()
                await asyncio.gather(*background)
                if advancing is not None:
                    await asyncio.gather(advancing, return_exceptions=True)
            elif action != "state":
                raise ValueError(f"unknown audience action: {action}")
            if court.night(audience.night_id).closed and action in {"say", "dismiss"}:
                background.append(asyncio.create_task(precompute()))
            error = (
                advancing.exception()
                if advancing is not None and advancing.done()
                else None
            )
            print(
                json.dumps(
                    {
                        "scene": scene,
                        "night": court.night(audience.night_id).model_dump(mode="json"),
                        "month_running": advancing is not None and not advancing.done(),
                        "month_error": {
                            "type": type(error).__name__,
                            "message": str(error),
                            "log": str(court.db_path.with_suffix(".errors.log")),
                        }
                        if error
                        else None,
                        "petitions": [
                            p.model_dump(mode="json") for p in court.petitions()
                        ],
                        "date": court.calendar().data,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        await audience.drain()
        await asyncio.gather(*background)
        if advancing is not None:
            await asyncio.gather(advancing, return_exceptions=True)


async def month_action(court: Court, args: argparse.Namespace) -> None:
    month = Month(court, resolve_model(args.model))
    if args.command == "choose":
        await month.choose(args.petition, args.option)
    else:
        await month.advance()
    print(
        json.dumps(
            {
                "date": court.calendar().data,
                "petitions": [p.model_dump(mode="json") for p in court.petitions()],
            },
            ensure_ascii=False,
        )
    )


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    model = resolve_model(args.translation_model)
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
            asyncio.run(conversation(court, resolve_model(args.scene_model)))
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
