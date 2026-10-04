#!/usr/bin/env python3
"""#1902 D5：基线 0ca77fecc→HEAD 授权范围内全部测试删改机械枚举（Python）。

谓词 = 基线到 HEAD 间 tests/ 下任意 test_* 函数新增／删除，或独立断言／异常
上下文集合变化。不以点名例子或窄正则为成员白名单。
"""
from __future__ import annotations

import ast
import collections
import json
import subprocess
from pathlib import Path

BASE = "0ca77fecc"
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def functions(source: str) -> dict[str, ast.AST]:
    result: dict[str, ast.AST] = {}

    def walk(nodes, parents=()):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = ".".join((*parents, node.name))
                result[name] = node
                walk(node.body, (*parents, node.name))
            elif isinstance(node, ast.ClassDef):
                walk(node.body, (*parents, node.name))

    if source.strip():
        try:
            walk(ast.parse(source).body)
        except SyntaxError:
            pass
    return result


def assertions(fn) -> list[str]:
    if fn is None:
        return []
    return [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Assert)]


def contexts(fn) -> list[str]:
    if fn is None:
        return []
    return [
        ast.unparse(n)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"raises", "warns"}
    ]


def main() -> None:
    paths = git("diff", "--name-only", BASE, "--", "tests").splitlines()
    members = []
    for file in paths:
        if not file.endswith(".py"):
            continue
        try:
            subprocess.check_call(
                ["git", "cat-file", "-e", f"{BASE}:{file}"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            old = git("show", f"{BASE}:{file}")
        except subprocess.CalledProcessError:
            old = ""
        new_path = ROOT / file
        new = new_path.read_text(encoding="utf-8") if new_path.exists() else ""
        oldf, newf = functions(old), functions(new)
        for name in sorted(oldf.keys() | newf.keys()):
            if not name.split(".")[-1].startswith("test_"):
                continue
            before, after = oldf.get(name), newf.get(name)
            removed = list(
                (collections.Counter(assertions(before)) - collections.Counter(assertions(after))).elements()
            )
            added = list(
                (collections.Counter(assertions(after)) - collections.Counter(assertions(before))).elements()
            )
            removed_contexts = list(
                (collections.Counter(contexts(before)) - collections.Counter(contexts(after))).elements()
            )
            added_contexts = list(
                (collections.Counter(contexts(after)) - collections.Counter(contexts(before))).elements()
            )
            if before is None:
                kind = "function_added"
            elif after is None:
                kind = "function_deleted"
            elif removed or added or removed_contexts or added_contexts:
                kind = "independent_assertions_or_exception_contract_changed"
            else:
                continue
            current_src = (
                ast.get_source_segment(new, after) if after and new else ""
            ) or ""
            old_src = (
                ast.get_source_segment(old, before) if before and old else ""
            ) or ""
            members.append(
                {
                    "member": f"{file}::{name}",
                    "kind": kind,
                    "removedAssertions": removed,
                    "addedAssertions": added,
                    "removedExceptionContexts": removed_contexts,
                    "addedExceptionContexts": added_contexts,
                    "currentAssertions": assertions(after),
                    "currentExceptionContexts": contexts(after),
                    "callsPendingFactsHelper": "_scene_pending_audience_facts" in current_src,
                    "entersSceneConsumer": (
                        "_scene_opening_text" in current_src
                        or "prepare_scene_materials" in current_src
                    ),
                    "hadSceneConsumer": (
                        "_scene_opening_text" in old_src
                        or "prepare_scene_materials" in old_src
                    ),
                    "hasPrintCollect": "printed" in current_src or "blob =" in current_src,
                    "usesPrintCollectInAssert": any(
                        "blob" in a or "printed" in a for a in assertions(after)
                    ),
                    "removedNoteReasonSource": any(
                        "reason" in a
                        and ("json.loads" in a or "read_text" in a or "note" in a)
                        for a in removed
                    ),
                    "removedSelectionRosterAssert": any(
                        any(n in a for n in ("史可法", "温体仁", "毕自严")) for a in removed
                    ),
                }
            )

    out = OUT / "d5-python-members.json"
    out.write_text(json.dumps(members, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    deleted = sum(1 for m in members if m["kind"] == "function_deleted")
    print(f"D5 Python members {len(members)} deleted_functions {deleted}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
