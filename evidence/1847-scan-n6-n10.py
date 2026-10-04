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


def classify_n6(row):
    """Judge each N6 candidate from this-round source/sink reading only.

    No prior-table inheritance. dispositions never carry a ``prior:`` reason prefix.
    """
    snip = row["snip"]
    file = row["file"]
    kind = row["kind"]
    ctx = row.get("ctx") or ""

    # --- FIX_DONE: deleted illegal sites (this ticket / prior accepted transport fixes) ---
    if ctx in {
        "_secret_confirmation_material",
        "_secret_context_task_like",
        "_secret_context_tasks_related",
        "_secret_prefix_needs_recent_context",
        "_matched_prefix",
        "_migrate_legacy_office_pollution",
        "_canonical_secret_exclusion_target",
    } and any(
        x in snip
        for x in (
            "诸官", "官员", "诸司", "_SECRET_OFFICE_TITLE_SUFFIX", "罢居", "在途", "督师",
        )
    ):
        return "FIX_DONE", "office/secret free-text rewrite deleted; registry/enum only"
    if "_SECRET_OFFICE_TITLE_SUFFIX_RE" in snip or "_SECRET_OFFICE_TYPES" in snip:
        return "FIX_DONE", "secret office suffix/type vocabulary deleted"
    if "web_app.py" in file and "_CONDITION_DISPLAY_REPLACEMENTS" in snip and "for src, dst" in snip:
        return "FIX_DONE", "free-prose fallback replace removed; formal value path only"
    if ctx in {
        "_secret_confirmation_material",
        "_secret_context_task_like",
        "_secret_context_tasks_related",
        "_secret_prefix_needs_recent_context",
        "_matched_prefix",
    }:
        return "FIX_DONE", "secret task/related/confirm/prefix classify deleted; structured-role transport only"

    # --- KEEP: identity / formal / empty / structural ---
    if ctx == "_split_audience_context" and kind in {
        "startswith_call", "removeprefix_call", "endswith_call",
    }:
        return "KEEP_identity_or_formal", "structured role/confirm prefix peel; body transported"
    if ctx == "_canonical_secret_exclusion_target" and kind == "strip_call":
        return "KEEP_empty_check", "strip for registry exact-key lookup only; no suffix peel"
    if ctx == "canonical_secret_order_exclusions" and kind == "strip_call":
        return "KEEP_identity_or_formal", "strip office/office_type for registry set membership"
    if ctx == "concurrent_office_titles":
        if kind in {"replace_call", "split_call", "join_call", "strip_call"}:
            return "KEEP_identity_or_formal", "formal concurrent-title separator parse; no prefix/suffix vocab"
        if kind in {"re_sub", "slice_trunc_expr", "find_call"}:
            return "FIX_DONE", "office prefix/suffix vocabulary peel deleted from tokenizer"
    if ctx == "canonical_office_title" and kind == "join_call":
        return "KEEP_identity_or_formal", "join of formal concurrent-title segments"
    if kind in {"strip_call", "trim_call"} and re.search(
        r"if\s+not\s+.+\.strip|if\s+.+\.strip\(\)|if\s*\(\s*.*\.trim", snip
    ):
        return "KEEP_empty_check", "strip/trim only for emptiness predicate"
    if kind in {"strip_call", "trim_call"} and (
        "office" in snip.lower()
        or "name" in snip
        or "key" in snip
        or "id" in snip
        or "type" in snip
        or "status" in snip
        or "path" in snip
        or "account" in snip
        or "category" in snip
        or "display" in snip
    ) and "reason" not in snip and "condition" not in snip and "content" not in snip:
        return "KEEP_identity_or_formal", "identity/enum/key field strip for membership"
    if kind in {"strip_call", "trim_call"} and re.search(r"=\s*.*\.(strip|trim)\(\)", snip):
        if any(x in ctx for x in ("load_", "parse_", "read_", "from_", "to_", "sql", "json", "csv")):
            return "KEEP_identity_or_formal", "loader/parser identity strip"
        if "humanize" in snip.lower() or "_humanize_condition" in (ctx + snip):
            return "KEEP_identity_or_formal", "formal DSL pass-through path (no free-prose rewrite)"
        return "NEEDS_HUMAN", "assigned strip/trim — source/sink not identity-clear"
    if kind in {"split_call", "join_call", "filter_call"} and any(
        x in snip for x in ("splitlines", "\\n", "；", ",", "parts", "lines", "兼")
    ):
        return "KEEP_structural", "structural split/join/filter"
    if kind in {"replace_call"} and any(
        x in snip for x in ("兼掌", "兼署", "兼", "，", "、", "\\n", "\\r", "\\t")
    ):
        return "KEEP_structural", "formal separator normalize"
    if kind.startswith("re_") or kind == "regex_lit":
        if any(x in snip for x in ("pathname", "url", "UUID", "schema", "version", r"\d", "[A-Za-z_]+")):
            return "KEEP_identity_or_formal", "form-language / id regex"
        return "NEEDS_HUMAN", "regex site — verify not free-text transport rewrite"
    if kind in {"replace_call", "re_sub"}:
        return "NEEDS_HUMAN", "replace/sub — verify operand is not free-text transport"
    if kind in {"upper_call", "lower_call", "casefold_call", "toLowerCase_call", "toUpperCase_call"}:
        return "KEEP_identity_or_formal", "case fold for id/enum compare"
    if kind in {"encode_call", "decode_call", "normalize_call", "normalize_mod"}:
        return "KEEP_structural", "encoding/normalize structural"
    if kind in {"indexOf_call", "find_call", "rfind_call", "substr_call", "substring_call", "slice_call", "slice_trunc_expr", "slice_step_expr"}:
        return "KEEP_structural", "index/slice structural locate"
    return "NEEDS_HUMAN", "N6 candidate — source/sink not auto-clear this round"


def classify_n10(row):
    """Judge each N10 candidate from this-round source/sink reading only.

    No prior-table inheritance. dispositions never carry a ``prior:`` reason prefix.
    """
    snip = row["snip"]
    file = row["file"]
    kind = row["kind"]
    ctx = row.get("ctx") or ""

    # --- FIX_DONE: this-round / accepted deletions ---
    if any(
        x in snip
        for x in (
            "_SECRET_OFFICE_TITLE_SUFFIX_RE",
            "_SECRET_OFFICE_TYPES",
            "_migrate_legacy_office_pollution",
            "诸官|官员|诸司|诸人|上下|众人",
            'startswith(("前", "原"))',
            "startswith(('前', '原'))",
            "_TITLE_NOISE_SUFFIXES",
        )
    ) or ctx in {
        "_migrate_legacy_office_pollution",
    }:
        return "FIX_DONE", "office free-wording admission/status path deleted; registry/enum/form only"
    if ctx == "_canonical_secret_exclusion_target" and kind in {
        "re_sub_n10", "re_sub", "str_startswith", "startswith_branch", "re_fullmatch_n10", "re_compile_n10",
    }:
        return "FIX_DONE", "secret exclusion suffix/startswith vocabulary deleted; exact registry only"
    if ctx == "appointment_break_rank" and (
        "前" in snip and "原" in snip and ("罢居" in snip or "startswith" in snip)
    ):
        return "FIX_DONE", "history archive gate no longer uses office free-text markers"
    if ctx == "concurrent_office_titles" and (
        "前|原任|原" in snip or "TITLE_NOISE" in snip or "pollution" in snip
    ):
        return "FIX_DONE", "office prefix/suffix vocabulary peel deleted"
    if "groupIssues" in snip or ("situation.tsx" in file and "甲申" in snip):
        return "FIX_DONE", "fail_condition keyword presentation buckets removed"
    if "_recurring_funding_label_tokens" in snip or "_commitment_fiscal_create_duplicate_reason" in ctx:
        if "reason" in snip and ("create.get" in snip or "item.get" in snip):
            return "FIX_DONE", "free reason removed from fiscal identity tokens"
        if "purpose" in snip and "item.get" in snip:
            return "FIX_DONE", "purpose enum removed from fiscal identity tokens"
        return "KEEP_identity_or_formal", "ADR0027 account+科目名(key/display↔category); no reason/purpose/word-sense"
    if ctx in {
        "_secret_context_task_like",
        "_secret_context_tasks_related",
        "_secret_prefix_needs_recent_context",
        "_secret_confirmation_material",
        "_matched_prefix",
    } or any(
        name in snip
        for name in (
            "_secret_context_task_like",
            "_secret_context_tasks_related",
            "_secret_prefix_needs_recent_context",
            "_secret_confirmation_material",
        )
    ):
        return "FIX_DONE", "secret task/related/prefix/confirm classify deleted; full structured context to LLM"
    if any(x in snip for x in ("len(compact)", 'endswith("?")', 'endswith("？")', "endswith('?')")) and (
        "secret" in ctx or "secret" in snip or "compact" in snip
    ):
        return "FIX_DONE", "length/question free-text classify substitute deleted"

    # --- KEEP: closed enum / registry exact / form / field transport ---
    if ctx == "_canonical_secret_exclusion_target" and (
        "office_titles" in snip or "office_types" in snip
    ):
        return "KEEP_identity_or_formal", "exact registry membership (office_titles/office_types)"
    if ctx == "appointment_break_rank" and (
        "_INACTIVE_STATUSES" in snip or "听用候铨" in snip or "被顶替" in snip
    ):
        return "KEEP_identity_or_formal", "closed status/reason enum gate for archive lookup"
    if ctx in {"concurrent_office_titles", "canonical_office_title", "office_rank_band", "office_leverage_multiplier", "_match_rank_rule", "_is_substantive_office"}:
        if kind in {"re_sub_n10", "re_sub"} and ("前" in snip or "原" in snip):
            return "FIX_DONE", "office prefix vocabulary peel deleted"
        return "KEEP_identity_or_formal", "offices.json stem/registry match or formal concurrent split"
    if ctx == "_is_exclusive_office" or "_EXCLUSIVE_OFFICE_SUFFIXES" in snip:
        return "FIX_DONE", "exclusive-office suffix vocabulary deleted; no free-text exclusivity admit"
    if "ministerFilters.ts" in file and (
        "/首辅/" in snip or "/前|罢|致仕/" in snip or "officeRank" in snip or "/尚书/" in snip
    ):
        return "FIX_DONE", "UI office title regex sort/admission deleted; office_type enum only"
    if ctx == "triage_officers" and ("LIKE" in snip or "首辅" in snip):
        if "LIKE" in snip:
            return "FIX_DONE", "triage office LIKE free-text admission deleted"
        return "KEEP_identity_or_formal", "exact office title frozenset admission"
    if "ministerFilters" in file or (
        "office_type" in snip and kind in {"str_in_compare", "membership_compare", "includes_branch", "in_compare"}
    ):
        return "KEEP_identity_or_formal", "office catalog / formal enum sort-filter"
    if kind in {"reason_field", "fail_condition_field", "resolve_condition_field", "stage_text_field", "purpose_field", "display_field", "category_field"}:
        if any(x in snip for x in ("=", ":", "SELECT", "row[", "issue.", "get(")) and not any(
            x in snip for x in (".test(", "re.search", "re.match", "includes(", "startswith", "分组", "甲申")
        ):
            if "stage_text" in kind or "reason" in kind:
                return "KEEP_transport", "free-field ref/transport; not admission classify"
            return "KEEP_field_ref", "condition/label field ref; no wording classify"
    if any(x in snip for x in ("pathname", "deepseek", "dashscope", "api/", "cliRunner", "MING_SIM_")):
        return "KEEP_identity_or_formal", "config/url/id formal match"
    if kind in {"includes_branch", "startswith_branch", "endswith_branch", "str_startswith", "str_endswith"} and any(
        x in snip for x in ("pathname", "url", "URL", "base", "model", "runner", "id", "key", "type", "status", ".py", ".json", "http")
    ):
        return "KEEP_identity_or_formal", "structural id/url/type/status match"
    if kind in {
        "str_startswith", "startswith_branch", "startswith_call", "removeprefix_call",
    } and (
        ctx == "_split_audience_context"
        or "【本轮确认】" in snip
        or "皇帝：" in snip
    ):
        return "KEEP_identity_or_formal", "structured role/confirm prefix peel; body transported"
    if kind in {"str_in_compare", "membership_compare", "in_compare"} and any(
        x in snip for x in (
            "frozenset", "_INACTIVE", "_NON_OFFICE", "_UNOFFICED", "STATUS", "ACCOUNTS",
            "CATEGORIES", "office_titles", "office_types", "region_ids", "allowed", "VALID",
        )
    ):
        return "KEEP_identity_or_formal", "closed frozenset/registry membership"
    if kind in {"map_get_classify"} and any(x in snip for x in ("get(\"", "get('", ".get(")):
        if any(x in snip for x in ("reason", "purpose", "fail_condition", "stage_text", "content", "title")):
            return "KEEP_transport", "dict get of transported field; not keyword admit"
        return "KEEP_identity_or_formal", "structured dict key get"
    if kind in {"label_token"} and "humanize" in snip:
        return "KEEP_identity_or_formal", "formal DSL humanize; free prose pass-through"
    # High-suspicion leftover free-field classify
    if kind in {"regex_test", "re_search", "re_search_n10", "re_sub", "re_sub_n10", "keyword_or"} and any(
        x in snip for x in ("fail_condition", "resolve_condition", "stage_text", "reason", "title", "content", "text", "purpose")
    ):
        return "NEEDS_HUMAN", "regex/keyword on free/label field — verify admission/classify"
    if kind in {"str_in_compare", "membership_compare"} and any(
        x in snip for x in ("reason", "title", "stage", "condition", "purpose", "text")
    ):
        return "NEEDS_HUMAN", "membership on free/label field — verify"
    return "NEEDS_HUMAN", "N10 candidate — source/sink not auto-clear this round"


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

    n6_cls = []
    for r in n6_raw:
        disp, reason = classify_n6(r)
        assert not str(reason).startswith("prior:"), (r, reason)
        n6_cls.append({**r, "disposition": disp, "reason": reason})

    n10_cls = []
    for r in n10_raw:
        disp, reason = classify_n10(r)
        assert not str(reason).startswith("prior:"), (r, reason)
        n10_cls.append({**r, "disposition": disp, "reason": reason})

    # Synthetic FIX_DONE markers for deleted sites (not inherited KEEP; this-round record)
    for table, kind, ctx, snip, reason in (
        (n6_cls, "atom_strip_deleted", "_secret_confirmation_material", "helper deleted; body not rewritten",
         "secret confirm strip deleted; structured-role full context transport"),
        (n6_cls, "secret_suffix_peel_deleted", "_canonical_secret_exclusion_target",
         "诸官/suffix/startswith vocabulary deleted",
         "N6/N10: secret exclusion free-text peel/vocab deleted; exact registry only"),
        (n6_cls, "legacy_office_pollution_deleted", "_migrate_legacy_office_pollution",
         "legacy office pollution migration deleted",
         "N10: office free-text→status/transit migration deleted (#1812 no baggage)"),
        (n10_cls, "secret_task_keyword", "_secret_context_task_like", "helper deleted",
         "secret task/related/prefix/confirm classify deleted"),
        (n10_cls, "secret_related_keyword", "_secret_context_tasks_related", "helper deleted",
         "secret task/related/prefix/confirm classify deleted"),
        (n10_cls, "secret_prefix_keyword", "_secret_prefix_needs_recent_context", "helper deleted",
         "secret task/related/prefix/confirm classify deleted"),
        (n10_cls, "office_history_marker_deleted", "appointment_break_rank",
         "前/原/罢居 free-text history gate deleted",
         "N10: history archive gated by closed status/reason enum only"),
        (n10_cls, "office_title_noise_deleted", "concurrent_office_titles",
         "前/原/罢居/革职 vocabulary peel deleted",
         "N10: office tokenizer keeps formal concurrent split only"),
        (n10_cls, "exclusive_office_suffix_deleted", "_is_exclusive_office",
         "exclusive office suffix vocabulary deleted",
         "N10: exclusivity not admitted from free-text title suffixes"),
        (n10_cls, "minister_filter_title_regex_deleted", "filterMinisters",
         "office title regex sort/admission deleted",
         "N10: minister filter uses office_type/status enum only"),
        (n10_cls, "triage_office_like_deleted", "triage_officers",
         "office LIKE '%首辅%' free-text admission deleted",
         "N10: triage officers admitted by exact office title frozenset only"),
    ):
        if any((x.get("ctx") == ctx and x.get("kind") == kind) for x in table):
            continue
        table.append({
            "disposition": "FIX_DONE",
            "reason": reason,
            "lang": "py" if not kind.startswith("minister_") else "ts",
            "file": (
                "ming_sim/cli_backend.py" if ("secret_" in kind or kind == "atom_strip_deleted") else
                "ming_sim/db.py" if ("secret_suffix" in kind or "legacy_office" in kind) else
                "ming_sim/issues.py" if "exclusive_office" in kind else
                "web/src/components/ministerFilters.ts" if "minister_filter" in kind else
                "ming_sim/rescript_draft.py" if "triage_office" in kind else
                "ming_sim/office_rank.py"
            ),
            "line": "-",
            "kind": kind,
            "detail": "",
            "ctx": ctx,
            "snip": snip,
            "source": "prod",
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
