#!/usr/bin/env python3
"""F3 full-repo enum: free-text mechanical dependencies in tests (Python + Web).

Wide scan → classify with classify_f3_disposition.py. Tags each hit; does not delete.

Covers: assert in/==/truthy/len; list/tuple prose equality; vitest
toContain/toHaveTextContent/toMatch/toBe/toEqual positives and .not. negatives.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "evidence", "dist", "build"}
CJK = re.compile(r"[\u4e00-\u9fff]")
VITEST_POS = re.compile(
    r"\.(?:toContain|toHaveTextContent|toMatch|toBe|toEqual)\s*\("
)
VITEST_NEG = re.compile(
    r"\.not\.(?:toContain|toHaveTextContent|toMatch|toBe|toEqual)\s*\("
)


def is_prose(s: str) -> bool:
    if not s or len(s) < 2:
        return False
    if s.startswith(("密令/", "事务/", "盘面/", "人物/", "奏报/", "请旨/", "公开说法/")):
        return False
    if s.endswith((".txt", ".json", ".md", ".py", ".tsx", ".ts")):
        return False
    if "/" in s and " " not in s and not CJK.search(s):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:\-]+", s) and not CJK.search(s) and len(s) < 40:
        return False
    return bool(CJK.search(s) or (" " in s and len(s) >= 12))


def namey(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def lit(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def prose_lits_in(node: ast.AST) -> list[str]:
    out: list[str] = []
    if isinstance(node, (ast.List, ast.Tuple)):
        for el in node.elts:
            s = lit(el)
            if s is not None and is_prose(s):
                out.append(s)
    return out


class V(ast.NodeVisitor):
    def __init__(self):
        self.hits: list[tuple[int, str, str]] = []

    def visit_Assert(self, node: ast.Assert):
        t = node.test
        # X in Y
        if isinstance(t, ast.Compare) and any(isinstance(op, ast.In) for op in t.ops):
            left_s = lit(t.left)
            right = namey(t.comparators[0]) if t.comparators else ""
            material_body_rhs = (
                "read_material" in right
                or "tools[" in right
                or right.endswith("carrier")
                or ".carrier" in right
                or right == "blob"
                or right in {"disk", "direct", "api"}
                or right.endswith("[fact_rel]")
                or ("author_files[" in right)
            )
            path_rhs = (
                "author_files" in right
                or "list_materials" in right
                or right.endswith("paths")
                or "petition_paths" in right
            ) and "author_files[" not in right
            if any(isinstance(op, ast.NotIn) for op in t.ops):
                self.hits.append((node.lineno, "neg_membership", ast.unparse(t)[:160]))
            elif left_s is not None and is_prose(left_s):
                kind = "material_body_prose" if material_body_rhs else "assert_in_prose"
                self.hits.append((node.lineno, kind, f"{left_s!r} in {right}"))
            elif left_s is None and material_body_rhs:
                left_n = namey(t.left)
                if path_rhs or left_n.endswith(("_rel", "_path", "path", "rel")):
                    self.hits.append(
                        (node.lineno, "path_member_named", f"{left_n} in {right}")
                    )
                else:
                    self.hits.append(
                        (node.lineno, "material_body_named", f"{left_n} in {right}")
                    )
            elif left_s is None and path_rhs:
                left_n = namey(t.left)
                if left_n.endswith(("_rel", "_path", "path", "rel")) or "path" in left_n:
                    self.hits.append(
                        (node.lineno, "path_member_named", f"{left_n} in {right}")
                    )
            elif left_s is not None and path_rhs:
                self.hits.append(
                    (node.lineno, "path_member", f"{left_s!r} in {right}")
                )
        # == prose (scalar or list/tuple of prose)
        if isinstance(t, ast.Compare) and any(isinstance(op, ast.Eq) for op in t.ops):
            for side in [t.left, *t.comparators]:
                s = lit(side)
                if s is not None and is_prose(s):
                    other = namey(t.left if side is not t.left else t.comparators[0])
                    structured = any(
                        k in other
                        for k in (
                            "archive[",
                            "presented[",
                            '["body"]',
                            "['body']",
                            ".body",
                            "title",
                            "report",
                            "origin_ref",
                            "terminal_",
                            "status",
                        )
                    )
                    kind = "structured_field_eq_prose" if structured else "assert_eq_prose"
                    self.hits.append((node.lineno, kind, f"{other} == {s!r}"))
                for ps in prose_lits_in(side):
                    other = namey(t.left if side is not t.left else t.comparators[0])
                    self.hits.append(
                        (
                            node.lineno,
                            "assert_list_eq_prose",
                            f"{other} == [... {ps!r} ...]",
                        )
                    )
        # truthy / len on body-ish
        if isinstance(t, ast.Call) and isinstance(t.func, ast.Name) and t.func.id == "len":
            arg = namey(t.args[0]) if t.args else "?"
            if any(k in arg for k in ("text", "body", "carrier", "content", "report")):
                self.hits.append((node.lineno, "assert_len_body", arg))
        if isinstance(t, (ast.Name, ast.Attribute, ast.Subscript)):
            n = namey(t)
            if any(k in n for k in ("petition_paths", "text", "body", "carrier", "content")):
                if "petition_paths" in n:
                    self.hits.append((node.lineno, "assert_truthy_paths", n))
                elif any(k in n for k in ("text", "body", "carrier", "content", "report")):
                    self.hits.append((node.lineno, "assert_truthy_body", n))
        self.generic_visit(node)


def scan_py(path: Path) -> list[tuple[int, str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [(0, "syntax_error", str(exc))]
    v = V()
    v.visit(tree)
    return v.hits


def scan_vitest(path: Path) -> list[tuple[int, str, str]]:
    hits = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if VITEST_NEG.search(line):
            hits.append((i, "vitest_neg", line.strip()[:200]))
            continue
        if VITEST_POS.search(line):
            m = re.search(
                r"""(?:toContain|toHaveTextContent|toMatch|toBe|toEqual)\(\s*(['"`])(.*?)\1""",
                line,
            )
            lit_s = m.group(2) if m else ""
            matcher = "toBe" if ".toBe(" in line or ".toEqual(" in line else "toContain"
            gazetteish = any(
                k in path.name.lower()
                for k in ("gazette", "situation", "settlement", "modal", "durable")
            )
            if is_prose(lit_s):
                if matcher == "toBe":
                    kind = "vitest_eq_prose"
                else:
                    kind = (
                        "vitest_pos_prose_gazetteish"
                        if gazetteish
                        else "vitest_pos_prose"
                    )
            else:
                kind = "vitest_pos"
            hits.append((i, kind, line.strip()[:200]))
    return hits


def iter_hits():
    for path in sorted((ROOT / "tests").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        for lineno, kind, detail in scan_py(path):
            yield rel, lineno, kind, detail
    web = ROOT / "web"
    if web.exists():
        for path in sorted(web.rglob("*.test.*")):
            if any(p in SKIP for p in path.parts):
                continue
            rel = str(path.relative_to(ROOT))
            for lineno, kind, detail in scan_vitest(path):
                yield rel, lineno, kind, detail


def main() -> int:
    print("==== F3 FULL ENUM (free-text mechanical asserts) ====")
    print(f"ROOT={ROOT}")
    hits = 0
    material_body = 0
    for rel, lineno, kind, detail in iter_hits():
        print(f"{rel}:{lineno}:{kind}:{detail}")
        hits += 1
        if kind.startswith("material_body"):
            material_body += 1
    print(f"==== F3 MATERIAL_BODY_POSITIVE_COUNT={material_body} ====")
    print(f"==== F3 HIT_COUNT={hits} ====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
