#!/usr/bin/env python3
"""Runnable membership enum for #1834 F15/F16/F13/F3-R. Evidence only — not a test."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MING = ROOT / "ming_sim"
TESTS = ROOT / "tests"
WEB = ROOT / "web" / "src"


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if ".venv" not in p.parts)


def enum_f16() -> list[str]:
    """Any [:N] / strip-then-slice on free-prose-like fields in ming_sim."""
    # Field names that are free prose or feed material-readable text.
    prose = re.compile(
        r"(reason|note|origin|criterion|title|summary|text|decree|content|"
        r"description|detail|memo|claim|prose|narrative|case_summary|"
        r"origin_context|stage_text|situation|body|report|purpose|"
        r"ongoing_effects|fail_condition|resolve_condition|status_reason)"
        r"[^\n]{0,80}\[:\d+\]",
        re.I,
    )
    slice_any = re.compile(r"\[:\d+\]")
    rows: list[str] = []
    for path in _py_files(MING):
        rel = path.relative_to(ROOT)
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "tlog(" in line or "print(" in line or "raise " in line:
                kind = "LOG_OR_RAISE"
            elif prose.search(line):
                kind = "PROSE_SLICE"
            elif slice_any.search(line) and any(
                k in line for k in ("strip()", "str(", "or \"", "or '")
            ):
                kind = "STRIP_OR_STR_SLICE"
            else:
                continue
            if not slice_any.search(line):
                continue
            rows.append(f"{kind}\t{rel}:{i}\t{line.strip()}")
    return rows


def enum_f15() -> list[str]:
    """Public supply exits + secret-source metadata paths."""
    patterns = (
        "prepare_gazette_author_materials",
        "prepare_world_materials",
        "_gazette_feed",
        "_month_fact_materials",
        "exclude_secret_order",
        "secret_order_dossier_ids",
        "secret_order_affair_ids",
        "public_feed",
        "affair.origin",
        "affair.name",
        "起因：",
        "is_secret_order_origin",
        "secret_order_id",
    )
    rows: list[str] = []
    for path in (MING / "materials.py", MING / "month_chain.py"):
        rel = path.relative_to(ROOT)
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(p in line for p in patterns):
                rows.append(f"{rel}:{i}\t{line.strip()}")
    # Parallel secret_order_id scans that re-decide secrecy (not dossier-id derive).
    for path in _py_files(MING):
        rel = path.relative_to(ROOT)
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "secret_order_affair_ids" in line:
                rows.append(f"PARALLEL_SECRET_FN\t{rel}:{i}\t{line.strip()}")
            if "secret_order_id" in line and "affair_id" in line:
                rows.append(f"SECRET_AFFAIR_DERIVE\t{rel}:{i}\t{line.strip()}")
    return rows


def enum_f13() -> list[str]:
    """Retired dynamic copies: object.__setattr__ / undeclared getattr mirrors."""
    rows: list[str] = []
    for path in _py_files(MING) + _py_files(TESTS):
        rel = path.relative_to(ROOT)
        if "evidence/" in str(rel):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "object.__setattr__" in line or "index_lines" in line:
                rows.append(f"{rel}:{i}\t{line.strip()}")
            if re.search(r'getattr\([^,]+,\s*["\']index_', line):
                rows.append(f"{rel}:{i}\t{line.strip()}")
    # Frozen dataclass with dynamic attrs elsewhere
    for path in _py_files(MING):
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if "@dataclass(frozen=True)" not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "object.__setattr__" in line or "__dict__[" in line:
                rows.append(f"FROZEN_DYNAMIC\t{rel}:{i}\t{line.strip()}")
    return rows


def _assert_expr_text(node: ast.AST, src: str) -> str:
    return ast.get_source_segment(src, node) or ""


def enum_f3r_py() -> list[str]:
    """Duplicate/entailed asserts: membership/substring covered by equality, etc."""
    rows: list[str] = []
    for path in _py_files(TESTS):
        rel = path.relative_to(ROOT)
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            rows.append(f"SYNTAX\t{rel}\t{exc}")
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            asserts: list[tuple[int, ast.Assert]] = []
            for node in ast.walk(fn):
                if isinstance(node, ast.Assert):
                    asserts.append((node.lineno, node))
            asserts.sort()
            for idx, (lineno, node) in enumerate(asserts):
                test = node.test
                # X in H  then later H == ...
                if isinstance(test, ast.Compare) and any(
                    isinstance(op, ast.In) for op in test.ops
                ):
                    left = _assert_expr_text(test.left, src)
                    comps = [_assert_expr_text(c, src) for c in test.comparators]
                    for later_line, later in asserts[idx + 1 : idx + 6]:
                        lt = later.test
                        if not isinstance(lt, ast.Compare):
                            continue
                        if not any(isinstance(op, ast.Eq) for op in lt.ops):
                            continue
                        eq_left = _assert_expr_text(lt.left, src)
                        eq_rights = [_assert_expr_text(c, src) for c in lt.comparators]
                        # substring: needle in haystack; haystack == full
                        if comps and eq_left == comps[0]:
                            rows.append(
                                f"IN_THEN_EQ\t{rel}:{lineno},{later_line}\t"
                                f"{left} in {comps[0]}  ⊂  {eq_left} == {eq_rights[0] if eq_rights else '?'}"
                            )
                        # membership: x in coll; coll == exact
                        if comps and eq_left == comps[0]:
                            pass
                        if left and eq_rights and left == eq_left:
                            # assert x == y after assert x in z — different
                            pass
                # key not in d then d == {...}
                if isinstance(test, ast.Compare) and any(
                    isinstance(op, ast.NotIn) for op in test.ops
                ):
                    comps = [_assert_expr_text(c, src) for c in test.comparators]
                    for later_line, later in asserts[idx + 1 : idx + 6]:
                        lt = later.test
                        if isinstance(lt, ast.Compare) and any(
                            isinstance(op, ast.Eq) for op in lt.ops
                        ):
                            eq_left = _assert_expr_text(lt.left, src)
                            if comps and eq_left == comps[0]:
                                rows.append(
                                    f"NOTIN_THEN_EQ\t{rel}:{lineno},{later_line}\t"
                                    f"not-in {comps[0]} ⊂ {eq_left} =="
                                )
    return rows


def enum_f3r_js() -> list[str]:
    """JS: not.toBeNull / toBeTruthy then same node toContain/textContent."""
    rows: list[str] = []
    files = sorted(WEB.rglob("*.test.tsx")) + sorted(WEB.rglob("*.test.ts"))
    null_re = re.compile(
        r"expect\(([^)]+)\)\.(not\.toBeNull|toBeTruthy|toBeDefined)\(\)"
    )
    content_re = re.compile(
        r"expect\(([^)]+)\)\.(toContain|toHaveTextContent|toMatch)|"
        r"expect\(([^)]+)\.textContent\)"
    )
    for path in files:
        rel = path.relative_to(ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = null_re.search(line)
            if not m:
                continue
            target = m.group(1).strip()
            # look ahead in same block (~8 lines), skip waitFor-only sync KEEP
            window = "\n".join(lines[i : i + 8])
            if "waitFor" in lines[max(0, i - 3) : i + 1].__str__() if False else False:
                pass
            wait_ctx = any("waitFor" in lines[j] for j in range(max(0, i - 5), i + 1))
            for j in range(i + 1, min(len(lines), i + 8)):
                cm = content_re.search(lines[j])
                if not cm:
                    continue
                other = (cm.group(1) or cm.group(3) or "").strip()
                if target in other or other in target or target.split(".")[0] == other.split(".")[0]:
                    tag = "JS_KEEP_WAITFOR" if wait_ctx else "JS_NULL_THEN_CONTENT"
                    rows.append(f"{tag}\t{rel}:{i+1},{j+1}\t{target}")
                    break
    return rows


def main() -> int:
    out_dir = ROOT / "evidence" / "1834-four-class-fix"
    sections = {
        "enum_f16_members.txt": enum_f16(),
        "enum_f15_members.txt": enum_f15(),
        "enum_f13_members.txt": enum_f13(),
        "enum_f3r_members.txt": enum_f3r_py() + enum_f3r_js(),
    }
    for name, rows in sections.items():
        path = out_dir / name
        path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
        print(f"{name}: {len(rows)} rows -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
