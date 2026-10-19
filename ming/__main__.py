"""Package entry; audience JSONL keeps a live scene and background translator."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import get_args

from pydantic_ai.models import Model, infer_model

from ming.audience import Audience
from ming.middle.cli_model import ClaudeCliModel
from ming.middle.court import Court
from ming.middle.opening import CONTENT
from ming.middle.view import Identity


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ming")
    commands = result.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a new game")
    new.add_argument("--directory", type=Path, default=Path("saves"))
    new.add_argument("--content", type=Path, default=CONTENT)
    read = commands.add_parser("read", help="Read the selected game")
    audience = commands.add_parser(
        "audience",
        help="Audience JSONL: say/dismiss/open/drain/state; EOF drains and exits",
    )
    audience.add_argument(
        "--scene-model",
        required=True,
        help="Pydantic AI model id (openai-chat: for Chat Completions); native text and tools required",
    )
    for sub in (read, audience):
        sub.add_argument("--db", type=Path, required=True)
    read.add_argument("--replay", action="store_true")
    for sub in (new, read):
        sub.add_argument("--identity", choices=get_args(Identity), default="emperor")
    for sub in (new, read, audience):
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
    try:
        print(json.dumps({"night": str(audience.open())}), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            action = request["action"]
            scene = None
            if action == "say":
                scene = await audience.say(request["words"])
            elif action == "dismiss":
                audience.dismiss()
            elif action == "open":
                audience.open()
            elif action == "drain":
                await audience.drain()
            elif action != "state":
                raise ValueError(f"unknown audience action: {action}")
            print(
                json.dumps(
                    {
                        "scene": scene,
                        "night": court.night(audience.night_id).model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        await audience.drain()


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    model = resolve_model(args.translation_model)
    court = (
        Court.new_game(args.directory, model, args.content)
        if args.command == "new"
        else Court(args.db, model)
    )
    try:
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
