#!/usr/bin/env python3
"""#1847 w14 replay scanner — two open classes over VC executable code.

Class A (旧兼容及退役残余闭包): general predicates for unmarked-default /
compat / cutover / backfill / migration / identity-wrapper / dedicated tests.
Not limited to fiscal/population point-names. Roots = all version-controlled
executable sources (py/ts/tsx/js), excluding governance docs / frozen archive
evidence / vendored trees.

Class B (重复或闲置测试流程): every tests/ module-level non-fixture helper;
flag idle (no same-file load, no ImportFrom consumer) OR AST-identical to a
used helper elsewhere (called duplicate flow).
"""
from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "evidence",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    "archive",
    "artifacts",
    "docs",  # ADR/治理与史料不入机械候选；排除项在报告解释
}

# Extensions treated as version-controlled executable sources.
EXEC_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs"}


def iter_exec_files():
    """Full-repo VC executable enumeration via git ls-files (not a few dirs)."""
    out = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        text=False,
    )
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        p = ROOT / rel
        if p.suffix not in EXEC_SUFFIXES:
            continue
        parts = Path(rel).parts
        if any(part in SKIP_PARTS for part in parts):
            continue
        if not p.is_file():
            continue
        yield p


# --- Class A mechanical predicates (general; then semantic disposition in TSV) ---
A_PATS = [
    (
        r"缺标|无标默认|unmarked|缺省兼容|兼容旧|旧客户端|旧档|旧存档|"
        r"保留兼容|compatibility alias|compat(?:ibility)? alias|"
        r"cutover|backfill|_migrate_|migration|migrate_legacy|"
        r"ensure_column|ADD COLUMN|DROP COLUMN|"
        r"existing saves stay on legacy|legacy=0|fiscal_engine|"
        r"__fiscal_engine|__army_pay_source_cutover|population_unit|"
        r"is_army_pay_source_cutover|is_substrate_hub_fiscal_engine|"
        r"_mark_substrate|_mark_army_pay|_mark_population|"
        r"test_legacy_|test_old_save|keeps_legacy|dual.track.*legacy",
        "legacy_compat_or_migrate_marker",
    ),
]


def scan_class_a():
    members = []
    for f in iter_exec_files():
        rel = str(f.relative_to(ROOT))
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(src.splitlines(), 1):
            for pat, kind in A_PATS:
                if re.search(pat, line, flags=re.IGNORECASE):
                    members.append(
                        ("旧兼容及退役残余闭包", kind, rel, i, line.strip()[:160])
                    )
                    break
        if f.suffix != ".py":
            continue
        # AST: post-retire identity wrappers — body is solely `return <arg>`
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
                continue
            ret = node.body[0].value
            if not isinstance(ret, ast.Name):
                continue
            arg_names = [a.arg for a in node.args.args]
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if ret.id in arg_names and arg_names:
                members.append(
                    (
                        "旧兼容及退役残余闭包",
                        "identity_wrapper",
                        rel,
                        node.lineno,
                        f"def {node.name}(...) -> return {ret.id}",
                    )
                )
    return members


def _is_pytest_fixture(node: ast.AST) -> bool:
    for dec in getattr(node, "decorator_list", []):
        name = ""
        if isinstance(dec, ast.Name):
            name = dec.id
        elif isinstance(dec, ast.Attribute):
            name = dec.attr
        elif isinstance(dec, ast.Call):
            f = dec.func
            if isinstance(f, ast.Name):
                name = f.id
            elif isinstance(f, ast.Attribute):
                name = f.attr
        if name in {"fixture", "parametrize"}:
            return True
    return False


def _dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _module_of(rel: str) -> str:
    return rel[:-3].replace("/", ".")


def scan_class_b():
    """Enumerate all test helpers; idle OR AST-identical-to-used."""
    file_trees = []
    for f in iter_exec_files():
        rel = str(f.relative_to(ROOT))
        if not rel.startswith("tests/") or f.suffix != ".py":
            continue
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        file_trees.append((rel, src, tree))

    # ImportFrom consumers: module -> imported names -> importing files
    imports_to = defaultdict(lambda: defaultdict(set))
    for rel, src, tree in file_trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            mod = node.module
            if node.level:
                parts = rel.split("/")[:-1]
                base = parts[: len(parts) - (node.level - 1)] if node.level else parts
                mod = ".".join(base + ([node.module] if node.module else []))
            for alias in node.names:
                imports_to[mod][alias.name].add(rel)

    used_dumps = defaultdict(list)
    unused = []

    for rel, src, tree in file_trees:
        names_defined = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    continue
                if _is_pytest_fixture(node):
                    continue
                names_defined[node.name] = node

        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                called.add(node.id)

        mod = _module_of(rel)
        for name, node in names_defined.items():
            dump = _dump(node)
            used_here = name in called
            imported = bool(imports_to.get(mod, {}).get(name))
            if used_here or imported:
                used_dumps[dump].append((rel, name, node.lineno))
            else:
                unused.append((rel, name, node.lineno, dump))

    members = []
    for rel, name, lineno, dump in unused:
        twin = used_dumps.get(dump) or []
        twin = [(r, n, ln) for r, n, ln in twin if not (r == rel and n == name)]
        if twin:
            twin_s = ",".join(f"{r}:{n}" for r, n, _ in twin[:3])
            members.append(
                (
                    "重复或闲置测试流程",
                    "idle_duplicate_of_used",
                    rel,
                    lineno,
                    f"{name} IDENTICAL_TO {twin_s}",
                )
            )
        else:
            members.append(
                (
                    "重复或闲置测试流程",
                    "idle_unused_helper",
                    rel,
                    lineno,
                    name,
                )
            )

    # Called duplicates: used helpers whose AST equals another used helper
    seen_pairs = set()
    for dump, locs in used_dumps.items():
        if len(locs) < 2:
            continue
        key = tuple(sorted((r, n, ln) for r, n, ln in locs))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        for rel, name, lineno in locs[1:]:
            members.append(
                (
                    "重复或闲置测试流程",
                    "called_duplicate_flow",
                    rel,
                    lineno,
                    f"{name} IDENTICAL_USED_ALSO_IN {locs[0][0]}:{locs[0][1]}",
                )
            )
    return members


def main():
    a = scan_class_a()
    b = scan_class_b()
    print("A_hits", len(a), Counter(m[1] for m in a))
    print("B_hits", len(b), Counter(m[1] for m in b))
    for m in a + b:
        print("\t".join(map(str, m)))


if __name__ == "__main__":
    main()
