"""入口：python -m ming "皇帝这一句" [--scene 上文] [--db 本局文件] [--identity emperor|audit]

只经中间层：落一句，再按身份把已落事实原样打印。
"""

import argparse
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter

from ming.middle.cli_model import ClaudeCliModel
from ming.middle.court import Court
from ming.middle.view import FactView, Identity


def main() -> None:
    parser = argparse.ArgumentParser(prog="ming")
    parser.add_argument("emperor_words")
    parser.add_argument("--scene", default="")
    parser.add_argument("--db", type=Path, default=Path("ming_game.sqlite"))
    parser.add_argument("--identity", choices=get_args(Identity), default="emperor")
    args = parser.parse_args()
    court = Court(args.db, ClaudeCliModel())
    court.handle(args.emperor_words, args.scene)
    print(TypeAdapter(list[FactView]).dump_json(court.facts(args.identity), indent=2).decode())


main()
