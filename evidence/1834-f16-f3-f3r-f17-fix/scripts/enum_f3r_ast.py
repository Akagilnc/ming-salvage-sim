#!/usr/bin/env python3
"""#1834 F3-R one-shot AST candidate dump (evidence only — not a classifier).

Lists mechanical duplicate/entailment *candidates* for human disposition:
- Python: exact duplicate assert text; In/NotIn→Eq on same haystack (full fn, no window);
  Eq→In/NotIn reverse; is-not-None→Eq; len Gt/GtE/NotEq→later Eq; len==0↔x==[] ;
  x==y → len(x)==len(y). Farther same-function pairs included (no window cap).
- JS/TS tests: duplicate expect; weak existence then strong on related target; reverse.
Enumeration only — never writes disposition / KEEP.

Does NOT narrow by filename / CJK / prose heuristics / assert-window caps.
Writes under evidence/1834-f16-f3-f3r-f17-fix/. Does not rewrite historical probe stdout.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence" / "1834-f16-f3-f3r-f17-fix"


def _enum_py() -> list[str]:
    summary: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = path.relative_to(ROOT)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test_"):
                continue
            asserts: list[tuple[int, str, ast.AST]] = []
            for node in ast.walk(fn):
                if isinstance(node, ast.Assert):
                    txt = (ast.get_source_segment(src, node.test) or "").strip()
                    asserts.append((node.lineno, txt, node.test))
            seen: dict[str, int] = {}
            for ln, txt, _ in asserts:
                key = " ".join(txt.split())
                if key in seen:
                    summary.append(
                        f"DUPLICATE_ASSERT\t{rel}:{seen[key]},{ln}\t{fn.name}\t{key[:160]}"
                    )
                else:
                    seen[key] = ln
            for i, (ln, txt, test) in enumerate(asserts):
                if not isinstance(test, ast.Compare):
                    continue
                ops = test.ops
                left_s = ast.get_source_segment(src, test.left) or ""
                comps = [ast.get_source_segment(src, c) or "" for c in test.comparators]
                if any(isinstance(op, (ast.In, ast.NotIn)) for op in ops):
                    for ln2, txt2, t2 in asserts[i + 1 :]:
                        if isinstance(t2, ast.Compare) and any(
                            isinstance(op, ast.Eq) for op in t2.ops
                        ):
                            eq_left = ast.get_source_segment(src, t2.left) or ""
                            if comps and eq_left == comps[0]:
                                kind = (
                                    "IN_THEN_EQ_FULL"
                                    if isinstance(ops[0], ast.In)
                                    else "NOTIN_THEN_EQ_FULL"
                                )
                                summary.append(
                                    f"{kind}\t{rel}:{ln},{ln2}\t{fn.name}\t"
                                    f"{txt[:80]} -> {txt2[:80]}"
                                )
                if any(isinstance(op, ast.Eq) for op in ops):
                    for ln2, txt2, t2 in asserts[i + 1 :]:
                        if isinstance(t2, ast.Compare) and any(
                            isinstance(op, (ast.In, ast.NotIn)) for op in t2.ops
                        ):
                            in_comps = [
                                ast.get_source_segment(src, c) or ""
                                for c in t2.comparators
                            ]
                            if in_comps and left_s == in_comps[0]:
                                summary.append(
                                    f"EQ_THEN_IN_REVERSE\t{rel}:{ln},{ln2}\t{fn.name}\t"
                                    f"{txt[:80]} -> {txt2[:80]}"
                                )
                if any(isinstance(op, ast.IsNot) for op in ops):
                    if comps and comps[0] == "None":
                        for ln2, txt2, t2 in asserts[i + 1 :]:
                            if isinstance(t2, ast.Compare) and any(
                                isinstance(op, ast.Eq) for op in t2.ops
                            ):
                                eq_left = ast.get_source_segment(src, t2.left) or ""
                                if eq_left == left_s:
                                    summary.append(
                                        f"ISNOTNONE_THEN_EQ\t{rel}:{ln},{ln2}\t{fn.name}\t"
                                        f"{txt[:80]} -> {txt2[:80]}"
                                    )
                # len(x) op N then later Eq — include Eq so len==0→x==[] is visible.
                if isinstance(test.left, ast.Call) and getattr(
                    test.left.func, "id", None
                ) == "len" and test.left.args:
                    len_arg = ast.get_source_segment(src, test.left.args[0]) or ""
                    for ln2, txt2, t2 in asserts[i + 1 :]:
                        if not (
                            isinstance(t2, ast.Compare)
                            and any(isinstance(op, ast.Eq) for op in t2.ops)
                        ):
                            continue
                        eq_left = ast.get_source_segment(src, t2.left) or ""
                        eq_right = (
                            ast.get_source_segment(src, t2.comparators[0]) or ""
                            if t2.comparators
                            else ""
                        )
                        if (
                            any(isinstance(op, ast.Eq) for op in ops)
                            and comps
                            and comps[0] in {"0", "0.0"}
                            and eq_left == len_arg
                            and eq_right.replace(" ", "") in {"[]", "()", "{}"}
                        ):
                            summary.append(
                                f"LEN0_THEN_EMPTY_EQ\t{rel}:{ln},{ln2}\t{fn.name}\t"
                                f"{txt[:80]} -> {txt2[:80]}"
                            )
                        elif any(isinstance(op, (ast.Gt, ast.GtE, ast.NotEq)) for op in ops):
                            summary.append(
                                f"LEN_THEN_EQ_CAND\t{rel}:{ln},{ln2}\t{fn.name}\t"
                                f"{txt[:80]} -> {txt2[:80]}"
                            )
                # x == y then len(x) == len(y)
                if (
                    any(isinstance(op, ast.Eq) for op in ops)
                    and not (
                        isinstance(test.left, ast.Call)
                        and getattr(test.left.func, "id", None) == "len"
                    )
                ):
                    for ln2, txt2, t2 in asserts[i + 1 :]:
                        if not (
                            isinstance(t2, ast.Compare)
                            and any(isinstance(op, ast.Eq) for op in t2.ops)
                        ):
                            continue
                        t2_left = ast.get_source_segment(src, t2.left) or ""
                        t2_right = (
                            ast.get_source_segment(src, t2.comparators[0]) or ""
                            if t2.comparators
                            else ""
                        )
                        if not (
                            t2_left.startswith("len(") and t2_right.startswith("len(")
                        ):
                            continue
                        if left_s and (
                            left_s in t2_left
                            or left_s in t2_right
                            or (comps and comps[0] in t2_left)
                            or (comps and comps[0] in t2_right)
                        ):
                            summary.append(
                                f"EQ_THEN_LEN\t{rel}:{ln},{ln2}\t{fn.name}\t"
                                f"{txt[:80]} -> {txt2[:80]}"
                            )
    return summary


def _enum_js() -> list[str]:
    js_sum: list[str] = []
    expect_re = re.compile(r"expect\(([^)]+)\)\.([A-Za-z0-9_.]+)")
    web = ROOT / "web" / "src"
    paths = sorted(web.rglob("*.test.tsx")) + sorted(web.rglob("*.test.ts"))
    weak = {
        "not.toBeNull",
        "toBeTruthy",
        "toBeDefined",
        "not.toBeUndefined",
    }
    strong_prefixes = (
        "toContain",
        "toHaveTextContent",
        "toMatch",
        "toBe",
        "toEqual",
        "toStrictEqual",
    )
    for path in paths:
        rel = path.relative_to(ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        blocks: list[dict] = []
        cur: dict | None = None
        for i, line in enumerate(lines, 1):
            if re.search(r"\b(it|test)\s*\(", line):
                if cur:
                    blocks.append(cur)
                cur = {"start": i, "expects": []}
            if cur:
                for m in expect_re.finditer(line):
                    cur["expects"].append(
                        (i, m.group(1).strip(), m.group(2), line.strip()[:160])
                    )
        if cur:
            blocks.append(cur)
        for b in blocks:
            ex = b["expects"]
            seen: dict[tuple, int] = {}
            for ln, tgt, meth, raw in ex:
                key = (tgt, meth, raw)
                if key in seen:
                    js_sum.append(f"JS_DUP\t{rel}:{seen[key]},{ln}\t{raw}")
                else:
                    seen[key] = ln
            for i, (ln, tgt, meth, raw) in enumerate(ex):
                meth_base = meth.split("(")[0]
                is_weak = meth in weak or meth.startswith("not.toBe")
                is_strong = any(meth_base.startswith(s) for s in strong_prefixes)
                if is_weak:
                    for ln2, tgt2, meth2, _raw2 in ex[i + 1 :]:
                        meth2_base = meth2.split("(")[0]
                        if any(meth2_base.startswith(s) for s in strong_prefixes):
                            if tgt == tgt2 or tgt in tgt2 or tgt2 in tgt:
                                js_sum.append(
                                    f"JS_WEAK_THEN_STRONG\t{rel}:{ln},{ln2}\t"
                                    f"{tgt} .{meth} -> .{meth2}"
                                )
                if is_strong:
                    for ln2, tgt2, meth2, _raw2 in ex[i + 1 :]:
                        if meth2 in weak or meth2.startswith("not.toBe"):
                            if tgt == tgt2 or tgt in tgt2 or tgt2 in tgt:
                                js_sum.append(
                                    f"JS_STRONG_THEN_WEAK\t{rel}:{ln},{ln2}\t"
                                    f"{tgt} .{meth} -> .{meth2}"
                                )
    return js_sum


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    py_rows = _enum_py()
    js_rows = _enum_js()
    py_path = OUT / "enum_f3r_py_all_candidates.txt"
    js_path = OUT / "enum_f3r_js_all_candidates.txt"
    py_path.write_text("\n".join(py_rows) + ("\n" if py_rows else ""), encoding="utf-8")
    js_path.write_text("\n".join(js_rows) + ("\n" if js_rows else ""), encoding="utf-8")
    print(f"py candidates: {len(py_rows)} -> {py_path}")
    for k, v in Counter(r.split("\t")[0] for r in py_rows).most_common():
        print(f"  {k}: {v}")
    print(f"js candidates: {len(js_rows)} -> {js_path}")
    for k, v in Counter(r.split("\t")[0] for r in js_rows).most_common():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
