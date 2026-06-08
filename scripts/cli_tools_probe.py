"""探针：验证「独立进程重建 context → 大臣只读工具输出正确」这一关键假设。

不改任何原逻辑，纯包装 ming_sim/tools.py 的 build_minister_tools，
指向现有存档（默认 data/probe.db），按工具名 dispatch、打印输出。

这是路 B（预解析注入）的地基：先证明工具能在 GameSession 之外忠实复现，
再谈把这些输出塞进给 codex/agy 的 prompt。

用法:
    .venv/bin/python -m scripts.cli_tools_probe --db data/probe.db list_regions
    .venv/bin/python -m scripts.cli_tools_probe --db data/probe.db --all
"""

from __future__ import annotations

import argparse
import sys

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.models import CourtContext
from ming_sim.tools import build_minister_tools


def build_tools(db_path: str):
    content = GameContent.load()
    bind_content(content)  # _ctx() 依赖：注入静态设定
    db = GameDB(db_path, content)
    state = db.load_state()  # 回合开始时的盘面 == DB 真相
    context = CourtContext(state=state, db=db)
    # 挑一个户部大臣以激活全部工具（治世/钱粮工具 gated 在 office_type）
    character = None
    for c in content.characters.values():
        if c.office_type == "户部":
            character = c
            break
    if character is None:
        character = next(iter(content.characters.values()))
    tools = build_minister_tools(
        character, context, use_roster_tool=True, use_army_tool=True
    )
    by_name = {getattr(t, "__name__", str(t)): t for t in tools}
    return by_name, character, state


def main() -> None:
    parser = argparse.ArgumentParser(description="大臣只读工具独立复现探针")
    parser.add_argument("--db", default="data/probe.db")
    parser.add_argument("tool", nargs="?", help="工具名，省略则列出全部工具名")
    parser.add_argument("args", nargs="*", help="工具参数")
    parser.add_argument("--all", action="store_true", help="跑所有无参只读工具")
    ns = parser.parse_args()

    by_name, character, state = build_tools(ns.db)
    print(f"[ctx] 存档={ns.db} 大臣={character.name}({character.office_type}) "
          f"turn={state.turn} {state.year}年{state.period}月 国库={state.metrics.get('国库')}")

    if ns.all:
        readonly_noarg = [
            "list_memorials", "list_regions", "list_buildings",
            "query_court_roster", "query_army_roster", "inspect_treasury_ledger",
        ]
        for name in readonly_noarg:
            fn = by_name.get(name)
            print(f"\n===== {name} =====")
            if fn is None:
                print("(工具不存在)")
                continue
            try:
                print(fn())
            except Exception as exc:  # noqa: BLE001 — 探针要看清每个工具的真实失败
                print(f"!! {type(exc).__name__}: {exc}")
        return

    if not ns.tool:
        print("可用工具：", ", ".join(sorted(by_name)))
        return

    fn = by_name.get(ns.tool)
    if fn is None:
        print(f"无此工具：{ns.tool}", file=sys.stderr)
        sys.exit(1)
    # 参数尽量按 int 解析，失败保留字符串
    parsed = []
    for a in ns.args:
        try:
            parsed.append(int(a))
        except ValueError:
            parsed.append(a)
    print(fn(*parsed))


if __name__ == "__main__":
    main()
