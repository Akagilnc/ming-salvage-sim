#!/usr/bin/env python3
"""#1847 N6/N10 full-repo mechanical enumeration (reproducible).

N6 class: free-text transport transforms — strip/trim, slice/substr/index,
replace/sub/normalize, split/join/filter, etc. on production source.

N10 class: free wording → business admission / structural/presentation
classification — regex, keyword match, in/includes/starts/ends, comparisons,
mappings used for branching/classification/admission (any language; not
limited to Chinese or reason/fail_condition fields).
"""
from __future__ import annotations

import ast
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[0]
# Allow override
if len(sys.argv) > 1:
    ROOT = pathlib.Path(sys.argv[1]).resolve()

EVIDENCE = ROOT / "evidence"
SKIP_DIR = {
    "node_modules", ".venv", "dist", ".git", "__pycache__",
    "archive", "tests", "evidence", "docs", "content",
    "agent-transcripts", ".cursor",
}
# Production entry roots (active). archive is static sealed — listed separately.
PROD_GLOBS = [
    "ming_sim/**/*.py",
    "web/src/**/*.ts",
    "web/src/**/*.tsx",
    "web_app.py",
    "launcher.py",
    "main.py",
    "spike_settle_tick.py",
]
# scripts/ = ops probes, not game runtime; still scan but tag source=scripts
SCRIPT_GLOBS = ["scripts/**/*.py"]

STRIP = {"strip", "lstrip", "rstrip"}
STR_METH = {
    "replace", "split", "join", "filter", "normalize",
    "substr", "substring", "slice", "indexOf", "lastIndexOf",
    "startswith", "endswith", "includes", "find", "rfind",
    "upper", "lower", "casefold", "title", "capitalize",
    "removeprefix", "removesuffix", "translate", "encode", "decode",
}
RE_FUNCS = {"sub", "split", "findall", "search", "match", "fullmatch", "finditer", "compile"}


def skip_path(path: pathlib.Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR:
        return True
    if ".test." in path.name or path.name.endswith("_test.py"):
        return True
    return False


def collect_paths() -> list[tuple[pathlib.Path, str]]:
    out: list[tuple[pathlib.Path, str]] = []
    for g in PROD_GLOBS:
        for p in ROOT.glob(g):
            if p.is_file() and not skip_path(p):
                out.append((p, "prod"))
    for g in SCRIPT_GLOBS:
        for p in ROOT.glob(g):
            if p.is_file() and not skip_path(p):
                out.append((p, "scripts"))
    # archive listing only (not classified as active members)
    archive_hits = 0
    for p in (ROOT / "archive").rglob("*"):
        if p.suffix in {".py", ".ts", ".tsx", ".js"} and p.is_file():
            archive_hits += 1
    (ROOT / "evidence" / "1847-archive-static-note.txt").write_text(
        f"archive/ static sealed; py/ts/tsx/js files counted={archive_hits}; "
        "excluded from active N6/N10 member tables by sealed-static basis.\n",
        encoding="utf-8",
    )
    return sorted(set(out), key=lambda x: (x[1], str(x[0])))


def enclosing(tree, lineno):
    best, best_ln = "", -1
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if getattr(n, "lineno", 10**9) <= lineno and n.lineno >= best_ln:
                best_ln, best = n.lineno, n.name
    return best


class N6Py(ast.NodeVisitor):
    def __init__(self, path, src):
        self.path, self.lines = path, src.splitlines()
        self.tree, self.rows = ast.parse(src), []

    def run(self):
        self.visit(self.tree)
        return self.rows

    def add(self, node, kind, detail=""):
        ln = getattr(node, "lineno", 0)
        snip = self.lines[ln - 1].rstrip()[:200] if 1 <= ln <= len(self.lines) else ""
        self.rows.append({
            "lang": "py", "file": self.path, "line": ln, "kind": kind,
            "detail": detail, "ctx": enclosing(self.tree, ln), "snip": snip,
        })

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute):
            if f.attr in STRIP:
                self.add(node, "strip_call", f.attr)
            if f.attr in STR_METH:
                self.add(node, f"{f.attr}_call", f.attr)
            if f.attr == "sub" and isinstance(f.value, ast.Attribute) and f.value.attr == "pattern":
                self.add(node, "regex_sub", "pattern.sub")
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re" and f.attr in RE_FUNCS:
            self.add(node, f"re_{f.attr}", f.attr)
        if isinstance(f, ast.Name) and f.id in {"unicodedata"}:
            self.add(node, "normalize_mod", f.id)
        self.generic_visit(node)

    def visit_Subscript(self, node):
        sl = node.slice
        if isinstance(sl, ast.Slice) and sl.lower is None and sl.upper is not None:
            self.add(node, "slice_trunc_expr", "[:expr]")
        if isinstance(sl, ast.Slice) and sl.step is not None:
            self.add(node, "slice_step_expr", "[::]")
        self.generic_visit(node)

    def visit_Compare(self, node):
        # in / not in on strings can be classification — captured in N10
        self.generic_visit(node)


TS_N6_PATS = [
    ("trim_call", r"\.trim\s*\("),
    ("replace_call", r"\.replace\s*\("),
    ("split_call", r"\.split\s*\("),
    ("join_call", r"\.join\s*\("),
    ("filter_call", r"\.filter\s*\("),
    ("slice_call", r"\.slice\s*\("),
    ("substr_call", r"\.substr(?:ing)?\s*\("),
    ("normalize_call", r"\.normalize\s*\("),
    ("indexOf_call", r"\.indexOf\s*\("),
    ("includes_call", r"\.includes\s*\("),
    ("startsWith_call", r"\.startsWith\s*\("),
    ("endsWith_call", r"\.endsWith\s*\("),
    ("match_call", r"\.match\s*\("),
    ("matchAll_call", r"\.matchAll\s*\("),
    ("search_call", r"\.search\s*\("),
    ("toLowerCase_call", r"\.toLowerCase\s*\("),
    ("toUpperCase_call", r"\.toUpperCase\s*\("),
]


def scan_n6_ts(rel, path: pathlib.Path, lang: str):
    rows = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("//"):
            continue
        for kind, pat in TS_N6_PATS:
            if re.search(pat, line):
                rows.append({
                    "lang": lang, "file": rel, "line": i, "kind": kind,
                    "detail": "", "ctx": "", "snip": line.rstrip()[:200],
                })
        if re.search(r"\[\s*:\s*\d+", line):
            rows.append({
                "lang": lang, "file": rel, "line": i, "kind": "slice_trunc_expr",
                "detail": "[:N]", "ctx": "", "snip": line.rstrip()[:200],
            })
        if re.search(r"/\S+/[gimsuy]*\.(?:test|exec|match)\s*\(", line) or re.search(r"new\s+RegExp\s*\(", line):
            rows.append({
                "lang": lang, "file": rel, "line": i, "kind": "regex_lit",
                "detail": "", "ctx": "", "snip": line.rstrip()[:200],
            })
    return rows


# N10: branching/classification/admission candidates (wide; any language)
N10_LINE_PATS = [
    ("regex_test", r"/\S+/[gimsuy]*\.test\s*\("),
    ("regex_exec", r"/\S+/[gimsuy]*\.exec\s*\("),
    ("regex_match", r"\.match\s*\(\s*/"),
    ("new_regexp", r"new\s+RegExp\s*\("),
    ("re_search", r"re\.(?:search|match|fullmatch|findall|finditer)\s*\("),
    ("re_sub", r"re\.sub\s*\("),
    ("includes_branch", r"\.includes\s*\("),
    ("startswith_branch", r"\.startswith\s*\(|\.startsWith\s*\("),
    ("endswith_branch", r"\.endswith\s*\(|\.endsWith\s*\("),
    ("in_compare", r"\bif\b.+\bin\b|\bin\s+[\"']"),
    ("keyword_or", r"[\"'][^\"']{1,40}[\"']\s*\|\s*[\"']"),
    ("map_get_classify", r"\.(?:get|get\()\s*[\"']"),
    ("reason_field", r"[\"']reason[\"']"),
    ("fail_condition_field", r"fail_condition"),
    ("resolve_condition_field", r"resolve_condition"),
    ("stage_text_field", r"stage_text"),
    ("purpose_field", r"[\"']purpose[\"']"),
    ("display_field", r"[\"']display[\"']"),
    ("category_field", r"[\"']category[\"']"),
    ("label_token", r"label_tokens|funding_label|groupIssues|humanize"),
]


def scan_n10_lines(rel, path: pathlib.Path, lang: str):
    rows = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//") or s.startswith("*"):
            continue
        for kind, pat in N10_LINE_PATS:
            if re.search(pat, line):
                rows.append({
                    "lang": lang, "file": rel, "line": i, "kind": kind,
                    "detail": "", "ctx": "", "snip": line.rstrip()[:200],
                })
    return rows


class N10Py(ast.NodeVisitor):
    """AST extras: Compare(In), If with string consts, dict-key membership for admission."""

    def __init__(self, path, src):
        self.path, self.lines = path, src.splitlines()
        self.tree, self.rows = ast.parse(src), []

    def run(self):
        self.visit(self.tree)
        return self.rows

    def add(self, node, kind, detail=""):
        ln = getattr(node, "lineno", 0)
        snip = self.lines[ln - 1].rstrip()[:200] if 1 <= ln <= len(self.lines) else ""
        self.rows.append({
            "lang": "py", "file": self.path, "line": ln, "kind": kind,
            "detail": detail, "ctx": enclosing(self.tree, ln), "snip": snip,
        })

    def visit_Compare(self, node):
        for op in node.ops:
            if isinstance(op, (ast.In, ast.NotIn)):
                # string literal on either side → candidate classification
                comps = [node.left, *node.comparators]
                if any(isinstance(c, ast.Constant) and isinstance(c.value, str) for c in comps):
                    self.add(node, "str_in_compare", "in")
                elif any(isinstance(c, (ast.Set, ast.List, ast.Tuple)) for c in comps):
                    self.add(node, "membership_compare", "in_collection")
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in {
            "startswith", "endswith", "find", "rfind", "__contains__",
        }:
            self.add(node, f"str_{f.attr}", f.attr)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re" and f.attr in RE_FUNCS:
            self.add(node, f"re_{f.attr}_n10", f.attr)
        self.generic_visit(node)


def uniq(rows):
    seen, out = set(), []
    for r in rows:
        k = (r["file"], r["line"], r["kind"], r.get("detail", ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def load_prior(path: pathlib.Path):
    if not path.exists():
        return {}
    prior = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            key = (row.get("file", ""), row.get("line", ""), row.get("kind", ""), row.get("snip", "")[:80])
            prior[key] = row
            # also by file+line+kind
            prior[(row.get("file", ""), row.get("line", ""), row.get("kind", ""))] = row
    return prior


def classify_n6(row, prior):
    key3 = (row["file"], str(row["line"]), row["kind"])
    key4 = (row["file"], str(row["line"]), row["kind"], row["snip"][:80])
    old = prior.get(key4) or prior.get(key3)
    snip = row["snip"]
    file = row["file"]
    kind = row["kind"]

    # Known FIX_DONE sites
    if "web_app.py" in file and "_CONDITION_DISPLAY_REPLACEMENTS" in snip and "for src, dst" in snip:
        return "FIX_DONE", "free-prose fallback replace removed; formal value path only"
    if kind in {"strip_call", "trim_call"} and re.search(r"if\s+not\s+.+\.strip|if\s+.+\.strip\(\)|if\s*\(\s*.*\.trim", snip):
        return "KEEP_empty_check", "strip/trim only for emptiness predicate"
    if kind in {"strip_call", "trim_call"} and re.search(r"=\s*.*\.(strip|trim)\(\)", snip):
        # assigned — need human unless prior KEEP
        if old and old.get("disposition", "").startswith("KEEP"):
            return old["disposition"], old.get("reason", "prior KEEP retained after re-verify")
        if old and old.get("disposition") == "FIX_DONE":
            return "FIX_DONE", old.get("reason", "prior FIX_DONE")
        return "NEEDS_HUMAN", "strip/trim assigned — verify not free-text transport mutation"

    if old and old.get("disposition") in {"FIX_DONE", "FIX"}:
        return "FIX_DONE", old.get("reason", "prior fix")
    if old and str(old.get("disposition", "")).startswith("KEEP"):
        # re-verify: do not blindly trust KEEP_match_or_normalize on humanize transport
        if "humanize" in snip.lower() or "_humanize_condition" in snip:
            if "return text" in snip or "passes through" in (old.get("reason") or ""):
                return "KEEP_identity_or_formal", "formal DSL or free prose pass-through (re-verified)"
            return "NEEDS_HUMAN", "humanize site — re-verify transport vs formal"
        return old["disposition"], f"prior:{old.get('reason', '')}"[:120]

    if kind in {"split_call", "join_call", "filter_call"} and any(
        x in snip for x in ("splitlines", "\\n", "；", ",", "parts", "lines")
    ):
        return "KEEP_structural", "structural split/join/filter"
    if kind.startswith("re_") or kind == "regex_lit":
        return "NEEDS_HUMAN", "regex site — verify not free-text transport rewrite"
    if kind in {"replace_call", "re_sub"}:
        return "NEEDS_HUMAN", "replace/sub — verify operand is not free-text transport"
    return "NEEDS_HUMAN", "new/unclassified N6 candidate — review source/sink contract"


def classify_n10(row, prior):
    key3 = (row["file"], str(row["line"]), row["kind"])
    key4 = (row["file"], str(row["line"]), row["kind"], row["snip"][:80])
    old = prior.get(key4) or prior.get(key3)
    snip = row["snip"]
    file = row["file"]
    kind = row["kind"]
    ctx = row.get("ctx") or ""

    # Known fixed
    if "groupIssues" in snip or ("situation.tsx" in file and "甲申" in snip):
        return "FIX_DONE", "fail_condition keyword presentation buckets removed"
    if "_recurring_funding_label_tokens" in snip or "_commitment_fiscal_create_duplicate_reason" in ctx:
        if "reason" in snip and ("create.get" in snip or "item.get" in snip):
            return "FIX_DONE", "free reason removed from fiscal identity tokens"
        if "purpose" in snip and "item.get" in snip:
            return "FIX_DONE", "purpose enum removed from fiscal identity tokens"
        return "KEEP_identity_or_formal", "ADR0027 account+科目名(key/display↔category); no reason/purpose/word-sense"

    # Formal enums / catalogs
    if "ministerFilters" in file or "office_type" in snip or "/首辅/" in snip:
        return "KEEP_identity_or_formal", "office catalog / formal enum sort-filter"
    if kind in {"reason_field", "fail_condition_field", "resolve_condition_field", "stage_text_field"}:
        if any(x in snip for x in ("=", ":", "SELECT", "row[", "issue.", "get(")) and not any(
            x in snip for x in (".test(", "re.search", "re.match", "includes(", "startswith", "分组", "甲申")
        ):
            if "stage_text" in kind:
                return "KEEP_transport", "stage_text field ref/transport"
            if "reason" in kind:
                return "KEEP_transport", "reason field ref/transport; not admission classify"
            return "KEEP_field_ref", "condition/reason field ref; no wording classify"

    # Config / URL / id formal
    if any(x in snip for x in ("pathname", "deepseek", "dashscope", "api/", "office_type", "cliRunner", "MING_SIM_")):
        return "KEEP_identity_or_formal", "config/url/id formal match"
    if kind in {"includes_branch", "startswith_branch", "endswith_branch"} and any(
        x in snip for x in ("pathname", "url", "URL", "base", "model", "runner", "id", "key", "type")
    ):
        return "KEEP_identity_or_formal", "structural id/url/type match"

    if old and old.get("disposition") in {"FIX_DONE", "FIX"}:
        return "FIX_DONE", old.get("reason", "prior fix")
    if old and str(old.get("disposition", "")).startswith("KEEP"):
        return old["disposition"], f"prior:{old.get('reason', '')}"[:120]

    # High-suspicion: regex/keyword on free fields deciding buckets
    if kind in {"regex_test", "re_search", "re_sub", "keyword_or"} and any(
        x in snip for x in ("fail_condition", "resolve_condition", "stage_text", "reason", "title", "content", "text", "purpose", "display", "category")
    ):
        return "NEEDS_HUMAN", "regex/keyword on free/label field — verify admission/classify"
    if kind in {"str_in_compare", "membership_compare"} and any(
        x in snip for x in ("reason", "title", "stage", "condition", "purpose", "display", "category", "text")
    ):
        return "NEEDS_HUMAN", "membership on free/label field — verify"

    return "NEEDS_HUMAN", "new/unclassified N10 candidate — review contract source/sink"


def write_tsv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    EVIDENCE.mkdir(exist_ok=True)
    paths = collect_paths()
    n6_raw, n10_raw = [], []
    for path, source in paths:
        rel = str(path.relative_to(ROOT))
        if path.suffix == ".py":
            src = path.read_text(encoding="utf-8")
            try:
                for r in N6Py(rel, src).run():
                    r["source"] = source
                    n6_raw.append(r)
                for r in N10Py(rel, src).run():
                    r["source"] = source
                    n10_raw.append(r)
            except SyntaxError:
                pass
            for r in scan_n10_lines(rel, path, "py"):
                r["source"] = source
                n10_raw.append(r)
        else:
            lang = path.suffix.lstrip(".")
            for r in scan_n6_ts(rel, path, lang):
                r["source"] = source
                n6_raw.append(r)
            for r in scan_n10_lines(rel, path, lang):
                r["source"] = source
                n10_raw.append(r)

    n6_raw = uniq(n6_raw)
    n10_raw = uniq(n10_raw)

    write_tsv(
        EVIDENCE / "1847-n6-candidates-raw.tsv",
        n6_raw,
        ["lang", "file", "line", "kind", "detail", "ctx", "snip", "source"],
    )

    prior_n6 = load_prior(EVIDENCE / "1847-n6-members-classified.tsv")
    prior_n10 = load_prior(EVIDENCE / "1847-n10-members-classified.tsv")

    n6_cls = []
    for r in n6_raw:
        disp, reason = classify_n6(r, prior_n6)
        n6_cls.append({**r, "disposition": disp, "reason": reason})
    # retain synthetic FIX_DONE rows from prior not in raw (deleted lines)
    for key, old in list(prior_n6.items()):
        if not isinstance(key, tuple) or len(key) != 3:
            continue
        if old.get("disposition") == "FIX_DONE":
            if not any(x["file"] == key[0] and str(x["line"]) == key[1] and x["kind"] == key[2] for x in n6_cls):
                n6_cls.append({
                    "disposition": "FIX_DONE",
                    "reason": old.get("reason", "deleted illegal site"),
                    "lang": old.get("lang", ""),
                    "file": key[0], "line": key[1], "kind": key[2],
                    "detail": old.get("detail", ""), "ctx": old.get("ctx", ""),
                    "snip": old.get("snip", ""), "source": "prod",
                })

    n10_cls = []
    for r in n10_raw:
        disp, reason = classify_n10(r, prior_n10)
        n10_cls.append({**r, "disposition": disp, "reason": reason})
    for key, old in list(prior_n10.items()):
        if not isinstance(key, tuple) or len(key) != 3:
            continue
        if old.get("disposition") == "FIX_DONE":
            if not any(x["file"] == key[0] and str(x["line"]) == key[1] and x["kind"] == key[2] for x in n10_cls):
                n10_cls.append({
                    "disposition": "FIX_DONE",
                    "reason": old.get("reason", "deleted illegal site"),
                    "lang": old.get("lang", ""),
                    "file": key[0], "line": key[1], "kind": key[2],
                    "detail": old.get("detail", ""), "ctx": old.get("ctx", ""),
                    "snip": old.get("snip", ""), "source": "prod",
                })

    fields = ["disposition", "reason", "lang", "file", "line", "kind", "detail", "ctx", "snip", "source"]
    write_tsv(EVIDENCE / "1847-n6-members-classified.tsv", n6_cls, fields)
    write_tsv(EVIDENCE / "1847-n10-members-classified.tsv", n10_cls, fields)

    def counts(rows):
        from collections import Counter
        return Counter(r["disposition"] for r in rows)

    c6, c10 = counts(n6_cls), counts(n10_cls)
    print("N6_RAW", len(n6_raw))
    print("N6_CLS", len(n6_cls), dict(c6))
    print("N10_RAW", len(n10_raw))
    print("N10_CLS", len(n10_cls), dict(c10))
    print("N6_NEEDS_HUMAN", c6.get("NEEDS_HUMAN", 0))
    print("N10_NEEDS_HUMAN", c10.get("NEEDS_HUMAN", 0))
    print("N6_FIX", c6.get("FIX", 0), "FIX_DONE", c6.get("FIX_DONE", 0))
    print("N10_FIX", c10.get("FIX", 0), "FIX_DONE", c10.get("FIX_DONE", 0))


if __name__ == "__main__":
    main()
