#!/usr/bin/env python3
"""#1847 w13/w13-corr replay scanner — two open classes, full-repo predicates.

Class A (旧兼容及退役残余闭包): selectors, unmarked-default legacy branches,
R/W marker ends, parallel gates, post-retire identity wrappers, dedicated
legacy/cutover-off tests. Not limited to fiscal point-names.

Class B (重复或闲置测试流程): unused module-level helpers that duplicate a
used helper elsewhere (AST dump equal), or same-file unused flow helpers that
are not pytest fixtures / not imported across files.
"""
from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".git", ".venv", "node_modules", "evidence", "__pycache__", "dist", "build"}

# Full-repo roots (not just ming_sim/tests point names).
SCAN_ROOTS = ("ming_sim", "tests", "web_app.py", "cli", "scripts")


def iter_py_files():
    for root_name in SCAN_ROOTS:
        p = ROOT / root_name
        if p.is_file() and p.suffix == ".py":
            yield p
            continue
        if not p.is_dir():
            continue
        for f in p.rglob("*.py"):
            if any(part in SKIP for part in f.parts):
                continue
            yield f


# --- Class A mechanical candidates (then semantic disposition in members_classified.tsv) ---
A_PATS = [
    (
        r"def fiscal_engine\b|is_substrate_hub_fiscal_engine_enabled|"
        r"_FISCAL_ENGINE_|_mark_substrate_hub_fiscal_engine|__fiscal_engine",
        "fiscal_selector_or_marker",
    ),
    (
        r"def is_army_pay_source_cutover_enabled\b|_mark_army_pay_source_cutover|"
        r"_ARMY_PAY_SOURCE_CUTOVER_KEY|__army_pay_source_cutover|"
        r"is_army_pay_source_cutover_enabled\(",
        "army_pay_cutover_selector_or_gate",
    ),
    (r"calc_province_fiscal\s*\(", "legacy_exec_branch"),
    (
        r"_content_population_effect_for_save|"
        r"def \w+\([^)]*\)\s*:\s*\n\s*return \w+\s*$",
        "identity_wrapper_shape",
    ),
    (
        r"test_legacy_fiscal|_disable_army_pay_source_cutover|"
        r"fiscal_engine\(\)\s*==\s*['\"]legacy|keeps_legacy_calc|"
        r"test_legacy_engine|VALUES\s*\(\s*['\"]__army_pay_source_cutover['\"].*0|"
        r"existing saves stay on legacy",
        "dedicated_legacy_or_cutover_off",
    ),
    (
        r"scale_content_population_to_save_unit|POPULATION_UNIT_WAN|"
        r"save_meta.*population_unit|population_unit\s*=\s*['\"]万",
        "retired_population_unit_compat",
    ),
]


def scan_class_a():
    members = []
    # Simple line patterns (skip multiline identity shape — handled via AST below)
    line_pats = [(p, k) for p, k in A_PATS if "identity_wrapper_shape" not in k]
    for f in iter_py_files():
        rel = str(f.relative_to(ROOT))
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(src.splitlines(), 1):
            for pat, kind in line_pats:
                if re.search(pat, line):
                    members.append(
                        ("旧兼容及退役残余闭包", kind, rel, i, line.strip()[:160])
                    )
                    break
        # AST: post-retire identity wrappers — function body is solely `return <arg>`
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
                continue  # protocol methods e.g. __enter__ return self
            if ret.id in arg_names and len(arg_names) >= 1:
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


def scan_class_b():
    """Find unused non-fixture helpers; flag AST-identical duplicates of a used helper."""
    defs = []  # (rel, name, lineno, dump, used_in_file)
    imports_of = defaultdict(set)  # name -> set of importing files

    file_trees = []
    for f in iter_py_files():
        rel = str(f.relative_to(ROOT))
        if not rel.startswith("tests/"):
            continue
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        file_trees.append((rel, src, tree))

    # Cross-file imports of names from tests.*
    for rel, src, tree in file_trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("tests") or node.module.startswith("."):
                    for alias in node.names:
                        imports_of[alias.name].add(rel)

    members = []
    used_dumps = defaultdict(list)  # dump -> [(rel, name)] used
    unused = []  # (rel, name, lineno, dump)

    for rel, src, tree in file_trees:
        names_defined = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    continue
                if _is_pytest_fixture(node):
                    continue
                names_defined[node.name] = node

        # call/name loads in this file
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

        for name, node in names_defined.items():
            dump = _dump(node)
            used_here = name in called
            imported = bool(imports_of.get(name))
            if used_here or imported:
                used_dumps[dump].append((rel, name, node.lineno))
            else:
                unused.append((rel, name, node.lineno, dump))

    # Unused that duplicate a used helper elsewhere = real idle duplicate flow
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
            # Same-file unused non-fixture helper with no importers — idle flow candidate
            members.append(
                (
                    "重复或闲置测试流程",
                    "idle_unused_helper",
                    rel,
                    lineno,
                    name,
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
