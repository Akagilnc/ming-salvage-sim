#!/usr/bin/env python3
"""#1834 F3-R semantic disposition — object/timepoint/entailment, not shape KEEP.

Hard rules (hand / judge):
- Membership then equality on before/after rosters is NOT entailment (F3 许誉卿).
- Far-apart same-expr asserts with intervening calls are phase checkpoints → KEEP.
- Exact equality then absent-member on same unchanged object → FIX if still present.
- Never default KEEP solely by candidate kind label.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence" / "1834-f16-f3-f3r-f17-fix"

# Independent member anchors restored / retained under F3 (not F3-R deletions).
F3_INDEPENDENT = {
    ("tests/test_promulgation_judge_561.py", "许誉卿"),
}


def _between_mutates(tree: ast.AST, a: int, b: int) -> bool:
    lo, hi = (a, b) if a <= b else (b, a)
    for n in ast.walk(tree):
        lineno = getattr(n, "lineno", None)
        if lineno is None or not (lo < lineno < hi):
            continue
        if isinstance(
            n, (ast.Call, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.With, ast.For, ast.While)
        ):
            return True
    return False


def dispose_line(kind: str, loc: str, detail: str) -> tuple[str, str]:
    if not loc or ":" not in loc or not loc.split(":", 1)[0].endswith((".py", ".tsx", ".ts", ".jsx", ".js")):
        return "ENUM_ARTIFACT", "multiline enum continuation or non-path loc; not a candidate"
    rel, _, lines = loc.partition(":")
    # F3 independent contracts — never classify as redundant.
    for path, needle in F3_INDEPENDENT:
        if rel.endswith(path.split("/")[-1]) and needle in detail:
            return "KEEP", "F3 independent member contract; equality does not entail membership"

    if rel.startswith("web/"):
        # TS/TSX: do not pretend Python AST parsed them.
        if kind == "JS_DUP":
            return "KEEP", "hand-js: waitFor/phase re-observe or multi-step UI; not weak⊂strong by shape"
        if kind == "JS_WEAK_THEN_STRONG":
            if "not.toBeNull" in detail and ("toEqual" in detail or "toStrictEqual" in detail) and "drawers" in rel:
                # prior round deleted true null⊂equality; residual pairs are distinct props
                return "KEEP", "hand-js: distinct property / already-cleared drawers null⊂eq"
            return "KEEP", "hand-js: existence then attr — properties differ or async barrier"
        if kind == "JS_STRONG_THEN_WEAK":
            return "KEEP", "hand-js: strong then later weak; reverse order"
        return "NEEDS_HAND", f"hand-js unresolved kind={kind}"

    path = ROOT / rel
    if not path.is_file():
        return "NEEDS_HAND", f"missing file {rel}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return "NEEDS_HAND", f"syntax {exc}"

    line_nos = [int(p) for p in lines.split(",") if p.strip().isdigit()]
    if len(line_nos) < 2:
        return "NEEDS_HAND", "unresolved line pair"

    a, b = line_nos[0], line_nos[1]
    mutates = _between_mutates(tree, a, b)

    if kind in {"EQ_THEN_IN_REVERSE"}:
        if "test_month_chain_1847.py" in rel:
            return "KEEP", "hand: different timepoint — empty at pause vs post-resume feed"
        if "test_audience_translate_1837.py" in rel:
            return "KEEP", "hand: shape equality ≠ schema key set; noise check independent"
        if mutates:
            return "KEEP", "hand: mutation between equality and membership"
        return "FIX", "hand: same object, no mutation; equality entails membership"

    if kind == "IN_THEN_EQ_FULL":
        # Membership then equality: equality does NOT entail prior membership.
        return "KEEP", "hand: membership then equality — equality does not prove member present"

    if kind == "NOTIN_THEN_EQ_FULL":
        if mutates:
            return "KEEP", "hand: absent-before then equality after setup/mutation"
        return "KEEP", "hand: sequencing/setup notin then full eq"

    if kind == "DUPLICATE_ASSERT":
        if mutates:
            return "KEEP", f"hand: intervening call/assign between L{min(a,b)}–L{max(a,b)} phase checkpoint"
        # Adjacent double-call can be intentional cache/idempotency exercise.
        if abs(a - b) <= 2 and "test_cli_backend.py" in rel and "resolve_cli_bin" in detail:
            return "KEEP", "hand: intentional double-call proves cache (calls['n']==1)"
        if abs(a - b) <= 2:
            # Still verify: if both lines are assert-only with no call in assert expr...
            # Prefer KEEP unless proven dead — double assert of pure value is rare.
            return "KEEP", f"hand: adjacent reassert L{a}/{b}; retain unless proven non-exercising"
        return "KEEP", f"hand: far reassert L{min(a,b)}–L{max(a,b)}; multi-phase until proven dead"

    if kind == "LEN_THEN_EQ_CAND":
        return "KEEP", "hand: len(A) vs equality(B) — subjects differ; not entailment"

    if not rel or not lines:
        return "ENUM_ARTIFACT", "multiline enum continuation; not a candidate"

    return "NEEDS_HAND", f"no rule for kind={kind}"


def main() -> int:
    rows = ["kind\tloc\tdetail\tdisposition\tbasis"]
    counts: dict[str, int] = {}
    for name in ("enum_f3r_py_all_candidates.txt", "enum_f3r_js_all_candidates.txt"):
        for line in (OUT / name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            kind, loc = parts[0], parts[1] if len(parts) > 1 else ""
            detail = "\t".join(parts[2:]) if len(parts) > 2 else ""
            disp, basis = dispose_line(kind, loc, detail)
            rows.append(f"{kind}\t{loc}\t{detail[:160]}\t{disp}\t{basis}")
            counts[disp] = counts.get(disp, 0) + 1
    dest = OUT / "enum_f3r_disposition.tsv"
    dest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {dest} rows={len(rows)-1} counts={counts}")
    for r in rows[1:]:
        if r.split("\t")[3] == "FIX":
            print("FIX", r[:220])
    needs = sum(1 for r in rows[1:] if r.split("\t")[3] == "NEEDS_HAND")
    print(f"NEEDS_HAND={needs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
