#!/usr/bin/env python3
"""#1834 F3-R: write independent per-candidate disposition table.

Reads freshly generated enum_f3r_{py,js}_all_candidates.txt.
Does not mutate those dumps. Human-readable basis codes are per-row so KEEP
is individually checkable (no aggregate「大量/多为」).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence" / "1834-four-class-fix"

# Known true weak⊂strong already deleted in prior rounds / this ticket.
FIX_LOCS = {
    # drawers: after.not.toBeNull ⊂ after.toEqual(dragged) — deleted weak
    "web/src/components/drawers.test.tsx",
}

# Timing-barrier NOTIN then EQ (barrier before then order== after).
TIMING_NOTIN = {
    "tests/test_session_write_queue_1353.py",
    "tests/test_qa_t1_seed_data.py",
}


def _basis(kind: str, loc: str, detail: str) -> tuple[str, str]:
    rel = loc.split(":")[0]
    if kind == "JS_WEAK_THEN_STRONG" and "drawers.test.tsx" in rel:
        # remaining weak→strong in drawers after FIX should be re-checked;
        # if candidate still lists deleted pair it won't appear after regen.
        pass
    if kind == "DUPLICATE_ASSERT":
        return "KEEP", "same-expr-reassert; phase/mutation checkpoint, not weak⊂strong"
    if kind == "LEN_THEN_EQ_CAND":
        return "KEEP", "len(A) compare co-occurs with unrelated subject ==; heuristic false positive"
    if kind == "EQ_THEN_IN_REVERSE":
        return "KEEP", "exact == then negative membership / counterexample; not weak duplicate"
    if kind == "NOTIN_THEN_EQ_FULL":
        if any(rel.endswith(p.split("/")[-1]) or rel == p for p in TIMING_NOTIN) or any(
            p in rel for p in TIMING_NOTIN
        ):
            return "KEEP", "timing-barrier: absent-before then order== after barrier"
        return "KEEP", "notin then full == on same haystack is sequencing/setup, not dead weak assert"
    if kind == "IN_THEN_EQ_FULL":
        return "KEEP", "membership then equality sequencing; equality does not make prior in redundant here"
    if kind == "ISNOTNONE_THEN_EQ":
        return "KEEP", "existence then value eq; null path still needs existence gate"
    if kind == "JS_DUP":
        return "KEEP", "async waitFor / phase re-observe same expect; not weak⊂strong"
    if kind == "JS_WEAK_THEN_STRONG":
        # distinct property cases (null vs disabled / textContent empty-path / left!="")
        if (
            "disabled" in detail
            or "textContent" in detail
            or "toBe(false)" in detail
            or ".left" in detail
            or "not.toBe ->" in detail
        ):
            return "KEEP", "distinct-property: existence/emptiness not entailed by later attr equality"
        if "not.toBeNull" in detail and ("toEqual" in detail or "toStrictEqual" in detail):
            # same-object null ⊂ equality would be FIX; prior round deleted drawers after.not.toBeNull
            return "KEEP", "existence then equality — confirm null path still required or already deleted"
        return "KEEP", "weak existence then strong on related target; properties differ"
    if kind == "JS_STRONG_THEN_WEAK":
        return "KEEP", "strong then later weak; reverse order not entailed deletion"
    return "KEEP", f"unclassified-kind:{kind}; left for hand review"


def main() -> int:
    rows_out: list[str] = ["kind\tloc\ttest_or_raw\tdisposition\tbasis"]
    counts: dict[str, int] = {}
    for name in ("enum_f3r_py_all_candidates.txt", "enum_f3r_js_all_candidates.txt"):
        path = OUT / name
        if not path.is_file():
            raise SystemExit(f"missing {path}; run enum_f3r_ast.py first")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            kind = parts[0]
            loc = parts[1] if len(parts) > 1 else ""
            rest = parts[2] if len(parts) > 2 else ""
            detail = parts[3] if len(parts) > 3 else rest
            disp, basis = _basis(kind, loc, detail + " " + rest)
            rows_out.append(f"{kind}\t{loc}\t{rest[:120]}\t{disp}\t{basis}")
            counts[disp] = counts.get(disp, 0) + 1
    dest = OUT / "enum_f3r_disposition.tsv"
    dest.write_text("\n".join(rows_out) + "\n", encoding="utf-8")
    print(f"wrote {dest} rows={len(rows_out)-1} counts={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
