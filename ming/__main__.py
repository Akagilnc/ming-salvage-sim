"""Package entry: new game creates a fresh file; read/decree open an existing game."""

import argparse
import json
from pathlib import Path
from typing import get_args

from ming.middle.cli_model import ClaudeCliModel
from ming.middle.court import Court
from ming.middle.opening import CONTENT
from ming.middle.view import Identity


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ming")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser(
        "new", help="Create a new game without changing any existing save"
    )
    new.add_argument("--directory", type=Path, default=Path("saves"))
    new.add_argument("--content", type=Path, default=CONTENT)
    read = commands.add_parser("read", help="Read the selected existing game")
    decree = commands.add_parser(
        "decree", help="Land an order in the selected existing game"
    )
    decree.add_argument("emperor_words")
    decree.add_argument("--scene", default="")
    for sub in (read, decree):
        sub.add_argument("--db", type=Path, required=True)
    read.add_argument(
        "--replay",
        action="store_true",
        help="Rebuild entity states from events for audit",
    )
    for sub in (new, read, decree):
        sub.add_argument("--identity", choices=get_args(Identity), default="emperor")
    args = parser.parse_args(argv)
    model = ClaudeCliModel()
    court = (
        Court.new_game(args.directory, model, args.content)
        if args.command == "new"
        else Court(args.db, model)
    )
    try:
        if args.command == "decree":
            court.handle(args.emperor_words, args.scene)
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
