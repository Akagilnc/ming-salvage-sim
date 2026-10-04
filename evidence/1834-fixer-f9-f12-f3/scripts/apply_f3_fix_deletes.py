#!/usr/bin/env python3
"""Remove FIX assert/expect statements listed in f3_fix_list.txt.

Python: AST-span delete of whole Assert nodes (handles multiline).
Vitest/TS: delete the expect(...) line (and continued lines until ';' balance).
No non-empty/len/sentinel replacements.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIX_LIST = ROOT / "evidence/1834-fixer-f9-f12-f3/f3_fix_list.txt"


def _py_spans(src: str, kill_lines: set[int]) -> list[tuple[int, int]]:
    tree = ast.parse(src)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", None) or node.lineno
        if any(start <= k <= end for k in kill_lines):
            spans.append((start, end))
    # merge overlaps
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _ts_spans(lines: list[str], kill_lines: set[int]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for k in sorted(kill_lines):
        if k < 1 or k > len(lines):
            continue
        i = k - 1
        # walk back to start of expect( if needed
        while i > 0 and "expect(" not in lines[i] and "await" not in lines[i]:
            if lines[i].strip().startswith((".", "to")):
                i -= 1
                continue
            break
        j = i
        buf = lines[j]
        # extend until semicolon depth ok or line has ';'/');'
        depth = buf.count("(") - buf.count(")")
        while j + 1 < len(lines) and (depth > 0 or (";" not in buf and not buf.rstrip().endswith(";"))):
            # stop if next line starts a new statement at same indent with expect/const/it/
            nxt = lines[j + 1]
            if depth <= 0 and re.match(r"^\s*(expect|const|let|it|await act|//)", nxt):
                break
            j += 1
            buf += nxt
            depth = buf.count("(") - buf.count(")")
            if ";" in nxt and depth <= 0:
                break
        spans.append((i + 1, j + 1))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _apply_spans(path: Path, spans: list[tuple[int, int]]) -> int:
    if not spans:
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kill: set[int] = set()
    for s, e in spans:
        kill.update(range(s, e + 1))
    # also drop immediately-previous comment that only narrates the positive lock
    for s, _e in spans:
        prev = s - 1
        if prev >= 1:
            t = lines[prev - 1]
            if t.strip().startswith(("#", "//")) and any(
                k in t for k in ("正向", "措辞", "正文成员", "人读自由")
            ):
                kill.add(prev)
    new = [ln for i, ln in enumerate(lines, 1) if i not in kill]
    path.write_text("".join(new), encoding="utf-8")
    return len(kill)


def main() -> int:
    by_file: dict[str, set[int]] = defaultdict(set)
    for raw in FIX_LIST.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        path, line_s, _basis, _detail = raw.split(":", 3)
        by_file[path].add(int(line_s))

    total = 0
    for rel, kill_lines in sorted(by_file.items()):
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        if rel.endswith(".py"):
            try:
                spans = _py_spans(src, kill_lines)
            except SyntaxError as exc:
                print(f"SYNTAX {rel}: {exc}")
                continue
        else:
            spans = _ts_spans(src.splitlines(), kill_lines)
        n = _apply_spans(path, spans)
        total += n
        print(f"patched {rel}: spans={spans} removed_lines={n}")
    print(f"TOTAL_REMOVED_LINES={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
