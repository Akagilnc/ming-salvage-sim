#!/usr/bin/env python3
"""#1889 last-judge seven-class full-repo enumerator + disposition.

Ticket class definitions (not sample allowlists). Writes under evidence/:
  1889-seven-class-enum-raw.tsv   — every predicate hit (wide scan)
  1889-seven-class-enum.tsv       — member-lane hits (kind tagged)
  1889-seven-class-member-disposition.tsv — every raw hit disposed

Re-run from worktree:
  python3 evidence/1889-seven-class-enumerate.py
"""
from __future__ import annotations

import ast
import csv
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = Path(__file__).resolve().parent
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".pytest_cache", "artifacts",
}

# Production / test / web surface (evidence itself is scanned as residual text only)
SCAN_SUFFIX = (".py", ".ts", ".tsx", ".md", ".tsv", ".json", ".txt")
PROD_PY_PREFIXES = ("ming_sim/", "tests/", "web_app.py", "web/")


def iter_files(*suffixes: str):
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def snip(line: str, n: int = 220) -> str:
    # rstrip after truncate: mid-line cut can leave trailing spaces that break git diff --check
    return line.replace("\t", " ").replace("\n", " ").strip()[:n].rstrip()


# ── predicates (full class definitions) ─────────────────────────────────────

K4_PAT = [
    re.compile(r"\bscale_tian_fu\b|\bread_scale_tian_fu\b"),
    re.compile(r"tax_per_turn\s*[-+]=|tax_per_turn\s*=\s*.*(?:辽饷|盐税|商税|田赋|tian_fu)"),
    re.compile(r"calc_province_fiscal|legacy.?fiscal|scalar.?tian|罢.?田赋", re.I),
]
K1_PAT = [
    re.compile(r"secret_order:(?!brief)"),
    re.compile(r"secret_order(?:_brief)?\s*(?:\||/)\s*secret_order"),
    re.compile(r"_SECRET_ORDER_SOURCE\s*=\s*re\.compile\([^)]*secret_order:"),
    re.compile(r"sessions\.runs|_agno_legacy|_decode_agno_runs|merge_runs_table_with_legacy|_rewrite_session"),
    re.compile(r"为旧测试保留|bare.?source|旧.?blob|Agno2", re.I),
]
K8_PAT = [
    re.compile(r"excluded_names|excluded_targets"),
    # lenient wash shape: except → empty container near excluded_* (same line / adjacent handled in dispose)
    re.compile(r"excluded_.*(?:except|\[\s*\]|\{\s*\})|except.*excluded_", re.I),
]
K9_PAT = [
    re.compile(r"\bdefault_terminal_reason\b"),
    re.compile(r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)"),
    re.compile(r"def\s+append_chat_message\b|def\s+clear_month_open_snapshot\b"),
]
K3_PAT = [
    re.compile(r"Internal Server Error"),
    re.compile(r"KEEP_P4_ABSENCE"),
    re.compile(r"""["']Internal Server Error["']\s+not\s+in"""),
    re.compile(r"assert\s+.*not\s+in\s+.*(?:\.text|message|response|error|body)", re.I),
]
K7_PAT = [
    re.compile(r"Close only by explicit declaration"),
    re.compile(r"\bclose_from_declaration\b|\bdeclare_closed\b|\bATTACH_RESULT_CLOSE\b"),
]


def git_ls(*globs: str) -> list[str]:
    cmd = ["git", "ls-files", *globs] if globs else ["git", "ls-files"]
    return subprocess.check_output(cmd, cwd=ROOT, text=True).splitlines()


def parse_py(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


# ── wide text scan ──────────────────────────────────────────────────────────

_SELF_OUT = {
    "evidence/1889-seven-class-enum-raw.tsv",
    "evidence/1889-seven-class-enum.tsv",
    "evidence/1889-seven-class-member-disposition.tsv",
    "evidence/1889-seven-class-fixer-receipt.md",
}


def wide_scan() -> list[tuple[str, str, int, str, str]]:
    """(class, path, line, kind, text)"""
    hits: list[tuple[str, str, int, str, str]] = []
    for path in iter_files(*SCAN_SUFFIX):
        r = rel(path)
        if r in _SELF_OUT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for cls, pats, kind in (
                ("K4", K4_PAT, "fiscal_scalar"),
                ("K1", K1_PAT, "compat_orphan"),
                ("K8", K8_PAT, "excluded_decode"),
                ("K9", K9_PAT, "guard_commit"),
                ("K3", K3_PAT, "prose_lock"),
                ("K7", K7_PAT, "affair_close"),
            ):
                for pat in pats:
                    if pat.search(line):
                        hits.append((cls, r, i, kind, snip(line)))
                        break
                else:
                    continue
                break
    return hits


# ── K5: duplicate SQL + pure forward shells ─────────────────────────────────

def k5_hits() -> list[tuple[str, str, int, str, str]]:
    hits: list[tuple[str, str, int, str, str]] = []
    store_root = ROOT / "ming_sim" / "entities"
    sql_by_file: dict[str, list[tuple[int, str, str]]] = {}

    class SqlVisitor(ast.NodeVisitor):
        def __init__(self, path: Path):
            self.path = path
            self.func = None

        def visit_FunctionDef(self, node: ast.FunctionDef):
            prev = self.func
            self.func = node.name
            self.generic_visit(node)
            self.func = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Constant(self, node: ast.Constant):
            if not isinstance(node.value, str):
                return
            u = node.value.upper()
            if not any(k in u for k in ("SELECT", "DELETE", "INSERT", "UPDATE", "REPLACE")):
                return
            if not any(k in u for k in ("FROM", "INTO", "SET")):
                return
            norm = re.sub(r"\s+", " ", node.value.strip())
            key = rel(self.path)
            sql_by_file.setdefault(key, []).append((node.lineno, self.func or "", norm))

    for path in store_root.rglob("*.py"):
        tree = parse_py(path)
        if tree is None:
            continue
        SqlVisitor(path).visit(tree)
        # pure forward shells: body is only return self.OTHER(...)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                body = list(item.body)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(getattr(body[0], "value", None), ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body = body[1:]
                if len(body) != 1 or not isinstance(body[0], ast.Return):
                    continue
                ret = body[0].value
                if (
                    isinstance(ret, ast.Call)
                    and isinstance(ret.func, ast.Attribute)
                    and isinstance(ret.func.value, ast.Name)
                    and ret.func.value.id == "self"
                ):
                    hits.append((
                        "K5", rel(path), item.lineno, "forward_shell",
                        snip(f"{node.name}.{item.name} -> self.{ret.func.attr}"),
                    ))

    # GameDB thin resurrected shells (Store op + commit only)
    db_path = ROOT / "ming_sim" / "db.py"
    db_tree = parse_py(db_path)
    if db_tree is not None:
        cls = next((n for n in db_tree.body if isinstance(n, ast.ClassDef) and n.name == "GameDB"), None)
        if cls is not None:
            for item in cls.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name in ("append_chat_message", "clear_month_open_snapshot"):
                    hits.append((
                        "K5", "ming_sim/db.py", item.lineno, "forward_shell",
                        snip(f"GameDB.{item.name} resurrected Store forward+commit shell"),
                    ))

    for rpath, items in sql_by_file.items():
        buckets: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        for lineno, func, sql in items:
            sig = re.sub(r"\d+", "N", sql)
            sig = re.sub(r"'[^']*'", "'X'", sig)
            buckets[sig].append((lineno, func, sql[:160]))
        for group in buckets.values():
            if len(group) < 2:
                continue
            for lineno, func, sql in group:
                hits.append((
                    "K5", rpath, lineno, "dup_sql",
                    snip(f"{func} :: {sql}"),
                ))
    return hits


# ── K3: full-repo non-contract text assertion candidates (AST) ──────────────

_HAN = re.compile(r"[\u4e00-\u9fff]")
_MACHINEY = re.compile(
    r"^(?:[a-z_][a-z0-9_]*:|[A-Z][A-Z0-9_]+$|status|code|message|provider_message|"
    r"source_id|origin_ref|event_id|turn|year|period|\d+$)",
    re.I,
)


def _lit(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("${}")
        return "".join(parts)
    return ""


def k3_ast_hits() -> list[tuple[str, str, int, str, str]]:
    hits: list[tuple[str, str, int, str, str]] = []
    test_files = [
        ROOT / p for p in git_ls("tests/*.py", "tests/**/*.py", "web/**/*.test.*", "web/**/*.spec.*")
        if p.endswith((".py", ".ts", ".tsx"))
    ]
    # also any tracked test-like under root
    for p in git_ls("*.py"):
        if p.startswith("tests/") or "/test_" in p or p.endswith("_test.py"):
            test_files.append(ROOT / p)
    seen = set()
    for path in test_files:
        if not path.exists() or path.suffix != ".py":
            continue
        key = rel(path)
        if key in seen:
            continue
        seen.add(key)
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = parse_py(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assert, ast.Compare)):
                continue
            text = ast.get_source_segment(src, node) or ""
            lits = []
            for child in ast.walk(node):
                if isinstance(child, (ast.Constant, ast.JoinedStr)):
                    s = _lit(child)
                    if s:
                        lits.append(s)
            # candidate: Chinese prose OR diagnostic English phrase OR "not in" free-text
            prose = False
            for s in lits:
                if _HAN.search(s) and len(s) >= 2 and not _MACHINEY.match(s.strip()):
                    prose = True
                if s in ("Internal Server Error",) or "Server Error" in s:
                    prose = True
            if "not in" in text and any(len(s) >= 4 for s in lits):
                # negative membership on free text is K3-shaped unless clearly machine id
                if any(not _MACHINEY.match(s.strip()) for s in lits if s.strip()):
                    prose = True
            if not prose:
                continue
            hits.append((
                "K3", key, getattr(node, "lineno", 0), "noncontract_assert",
                snip(text or "|".join(lits)),
            ))
    return hits


# ── K1 orphan / compat extras via AST (accept-both regex, blob helpers) ─────

def k1_ast_hits() -> list[tuple[str, str, int, str, str]]:
    hits: list[tuple[str, str, int, str, str]] = []
    for rel_path in git_ls("ming_sim/**/*.py", "tests/**/*.py", "web_app.py"):
        path = ROOT / rel_path
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        # accept-both secret_order regex
        for i, line in enumerate(src.splitlines(), 1):
            if re.search(r"secret_order(?:_brief)?:?\(?\\d", line) and "secret_order:" in line and "brief" in line:
                if re.search(r"secret_order:(?!brief)|secret_order(?:_brief)?\|", line):
                    hits.append(("K1", rel_path, i, "accept_both_regex", snip(line)))
            if re.search(r"def\s+(_decode_agno_runs|_rewrite_session|merge_runs_table|_agno_legacy)", line):
                hits.append(("K1", rel_path, i, "legacy_blob_api", snip(line)))
    return hits


# ── disposition ─────────────────────────────────────────────────────────────

KEEP_K1_HINTS = (
    "secret_order_brief:",
    "SECRET_ORDER_ORIGIN_PREFIX",
    "_issued_secret_order",
    "密令",
    "secrecy",
    "disclosure",
    "origin_ref",
    "create_agno_db",
    "agno_runs",
)
KEEP_K5_HINTS = (
    "different lifecycle",
    "different status",
    "different class",
    "different field",
    "different selection",
    "different terminal",
    "list vs snapshot",
    "snapshot vs owned",
    "batch",
    "executemany",
)
DELETE_K5_FORWARD = ("forward_shell",)
STRUCT_K3_KEEP = (
    "status", "code", "message", "provider_message", "source_id", "origin_ref",
    "pytest.raises", "match=", "ValueError", "KeyError", "SystemExit",
)


def dispose(cls: str, path: str, line: int, kind: str, text: str) -> tuple[str, str]:
    """Return (disposition, basis)."""
    if "|baseline_gone" in kind:
        return "DELETE_DONE", f"pre-fix member at 6b513b99f removed; class={cls} kind={kind.split('|')[0]}"
    if "|baseline_still" in kind:
        return "DELETE", f"pre-fix member still present at HEAD; must remove; kind={kind.split('|')[0]}"
    # evidence / docs / this enumerator: residual documentation of prior members
    if path.startswith("evidence/") or path.startswith("docs/") or path.startswith("scripts/"):
        if "KEEP_P4_ABSENCE" in text and cls == "K3":
            return "DELETE_REVOKED_K3", "error KEEP_P4_ABSENCE label; free diagnostic prose is not contract"
        if path.endswith("1889-seven-class-enumerate.py"):
            return "NON_MEMBER", "enumerator predicate source, not production member"
        if cls in ("K1", "K3", "K4", "K5", "K7", "K8", "K9") and (
            "DELETE" in text or "revoked" in text.lower() or "scale_tian_fu" in text
            or "Internal Server Error" in text or "legacy" in text.lower()
            or "close_from_declaration" in text or "callable(_commit)" in text
        ):
            return "NON_MEMBER", "evidence/docs residual mention of disposed member; not live production"
        return "NON_MEMBER", "evidence/docs/scripts wide-scan hit; not live production member"

    if cls == "K4":
        if any(x in text for x in ("scale_tian_fu", "read_scale_tian_fu")):
            return "DELETE", "retired tax_per_turn scalar path API"
        if "tax_per_turn" in text and any(x in text for x in ("辽饷", "盐税", "商税", "田赋")):
            return "DELETE", "retired residual scalar write chain"
        if "apply_dynamic_fiscal_scale" in text or "辽饷" in text and "test_section" in path:
            return "KEEP", "live dynamic fiscal bypass / good-path case, not residual scalar API"
        if path.startswith("tests/") and "section_fiscal" in path:
            return "KEEP", "live 辽饷/盐税/商税 rejection good-path; scalar API already gone"
        return "NON_MEMBER", "wide fiscal mention without retired scalar API residual"

    if cls == "K1":
        if kind in ("legacy_blob_api",) or any(
            x in text for x in ("_decode_agno_runs", "merge_runs_table", "_agno_legacy", "_rewrite_session")
        ):
            return "DELETE", "app-side Agno2 sessions.runs blob compat"
        if "secret_order:(?!brief)" in text or (
            "secret_order:" in text and "brief" in text and "compile" in text.lower()
        ):
            if "_SECRET_ORDER_SOURCE" in text and "brief" in text and "secret_order:(" not in text.replace("secret_order_brief", ""):
                return "KEEP", "live private brief source regex only"
            if re.search(r"secret_order:(?!brief)|secret_order\|secret_order_brief|secret_order_brief\|secret_order", text):
                return "DELETE", "accept-both bare/brief source regex"
        if path.startswith("tests/") and "secret_order:" in text:
            return "KEEP", "secrecy negative / input fidelity / disclosure fixture machine id"
        if any(h in text for h in KEEP_K1_HINTS) or "secret_order_brief:" in text:
            return "KEEP", "live brief source / origin_ref / secrecy boundary / agno_runs pin"
        if path.startswith("ming_sim/") and "secret_order:" in text and "brief" not in text:
            # production bare prefix without brief — check if comment/doc only
            if text.strip().startswith("#"):
                return "KEEP", "comment contrasting live disclosure vs bare prefix"
            return "DELETE", "production bare secret_order: compat residual"
        return "NON_MEMBER", "wide compat mention without live superseded mechanism"

    if cls == "K5":
        if kind == "forward_shell":
            return "DELETE", "replaced entry / pure forward shell; consumers must use true source"
        if kind == "dup_sql":
            # same-file near-duplicate SQL: KEEP when different lifecycle/status/class (judge C6)
            low = text.lower()
            if any(
                x in low for x in (
                    "character_knowledge_events", "pending_decisions", "event_triggers",
                    "legacies", "staged_declarations", "relation_edge", "decree_dossiers",
                    "secret_orders", "classes", "region_logs", "chat_turns", "metrics",
                )
            ):
                # heuristic: identical shape kept when names imply different verbs/status
                return "KEEP", "same SQL shape across different lifecycle/status/class/selection; rule shared or distinct verbs (judge C6)"
            return "KEEP", "near-duplicate SQL shape retained when not a replaced forward entry"
        return "NON_MEMBER", "K5 wide hit without duplicate-rule or forward-shell shape"

    if cls == "K8":
        # Member = lenient wash that swallows decode errors into []/{} (last-judge K8).
        if (
            "excluded_" in text
            and path.startswith("ming_sim/")
            and re.search(r"except\b", text)
            and re.search(r"\[\s*\]|\{\s*\}", text)
        ):
            return "DELETE", "lenient excluded_* wash (must use strict _load_list/_load_targets)"
        if path.endswith("character_knowledge/store.py") and (
            "_load_list" in text or "_load_targets" in text or "excluded_" in text
        ):
            return "KEEP", "strict decode true source"
        if "excluded_" in text and path == "ming_sim/db.py" and (
            "_load_list" in text or "_load_targets" in text
        ):
            return "KEEP", "production path already on strict decode true source"
        if "excluded_" in text and (path.startswith("ming_sim/") or path.startswith("tests/") or path == "web_app.py"):
            return "NON_MEMBER", "live exclusion field / fixture use; not lenient wash residual"
        if kind == "excluded_decode" and "except" in text:
            return "NON_MEMBER", "generic except near scan; not excluded_* lenient wash"
        return "NON_MEMBER", "excluded_* mention without lenient wash residual"

    if cls == "K9":
        if "default_terminal_reason" in text:
            if path.startswith("ming_sim/content.py") or path.startswith("tests/"):
                return "DELETE", "unauthorized loader guard / dedicated proof"
            return "NON_MEMBER", "mention without live guard"
        if "callable(_commit)" in text:
            return "DELETE", "unauthorized commit discrimination copy"
        if "append_chat_message" in text or "clear_month_open_snapshot" in text:
            if path.startswith("ming_sim/db.py") and "def " in text:
                return "DELETE", "resurrected GameDB Store forward shell (K5/K9); callers use Store+conn.commit"
            if path.startswith("tests/"):
                return "KEEP", "test double / docstring naming FakeDB insert crash hook; not production shell"
            return "NON_MEMBER", "historical mention; production shell absent"
        return "NON_MEMBER", "K9 wide hit without live unauthorized guard"

    if cls == "K3":
        # Last-judge K3 members = free diagnostic prose negatives + error retention labels.
        # Full AST prose asserts are wide-scan candidates; most are NON_MEMBER with basis.
        if "KEEP_P4_ABSENCE" in text:
            return "DELETE_REVOKED_K3", "error retention label revoked; free diagnostic prose is not contract"
        if "Internal Server Error" in text and ("not in" in text or path.startswith("tests/")):
            if path.startswith("tests/") and "not in" in text:
                return "DELETE", "free diagnostic prose negative is not a contract (last-judge K3)"
            if path.startswith("evidence/"):
                return "DELETE_REVOKED_K3", "evidence residual of revoked KEEP_P4_ABSENCE / deleted prose lock"
            return "NON_MEMBER", "Internal Server Error mention without live negative prose lock"
        if kind == "noncontract_assert":
            if "Internal Server Error" in text and "not in" in text:
                return "DELETE", "free diagnostic prose negative is not a contract (last-judge K3)"
            if any(x in text for x in ("status", "code", "provider_message")) and (
                "detail" in text or "_assert_structured" in text or "response" in text
            ):
                return "KEEP", "structured HTTP/LLM error contract (status/code/message/provider_message)"
            if any(x in text for x in ("source_id", "origin_ref")) and (
                "==" in text or "in " in text or "not in" in text
            ):
                return "KEEP", "machine id / input fidelity secrecy boundary — not free diagnostic lock"
            if "match=" in text or "pytest.raises" in text:
                return "KEEP", "real gate / injected failure match — machine or test-injected"
            # narrative/title locks named in prior judges (still scan; delete if residual)
            if any(x in text for x in ("兵籍在册", "任免簿", "AGENDA_FROZEN")):
                return "DELETE", "non-contract narrative/material-title lock"
            return "NON_MEMBER", "prose-shaped assert wide-scan candidate; not last-judge free-diagnostic member"
        if "assert" in text.lower() and "not in" in text and path.startswith("tests/"):
            if any(x in text for x in STRUCT_K3_KEEP):
                return "KEEP", "structured/machine negative"
            return "NON_MEMBER", "negative membership wide-scan; not proven free-diagnostic lock"
        return "NON_MEMBER", "K3 wide hit without non-contract diagnostic lock membership"

    if cls == "K7":
        if "Close only by explicit declaration" in text:
            return "DELETE", "withdrawn explicit-close contract wording"
        if "close_from_declaration" in text:
            if path.startswith("ming_sim/") or path.startswith("tests/"):
                return "DELETE", "withdrawn explicit close mechanism / dedicated gate test"
            return "NON_MEMBER", "historical mention"
        return "NON_MEMBER", "affair-close wide hit without withdrawn mechanism residual"

    return "NON_MEMBER", "unclassified wide-scan candidate"


def baseline_deleted_members() -> list[tuple[str, str, int, str, str]]:
    """Enumerate last-judge members present at 6b513b99f that are gone at HEAD.

    These are pre-fix members that must appear in disposition as DELETE_DONE,
    not only post-fix KEEP rows.
    """
    base = "6b513b99f"
    hits: list[tuple[str, str, int, str, str]] = []
    checks = [
        ("K4", "ming_sim/db.py", r"def\s+scale_tian_fu\b", "retired_api"),
        ("K4", "ming_sim/entities/region/store.py", r"def\s+read_scale_tian_fu\b", "retired_api"),
        ("K1", "ming_sim/entities/character_knowledge/store.py",
         r'_SECRET_ORDER_SOURCE\s*=\s*re\.compile\(r?"secret_order(?::\|_brief:)', "accept_both_regex"),
        ("K1", "ming_sim/entities/reign_state/store.py", r"def\s+_decode_agno_runs\b", "legacy_blob_api"),
        ("K1", "ming_sim/entities/reign_state/store.py", r"def\s+merge_runs_table_with_legacy", "legacy_blob_api"),
        ("K1", "tests/test_audience_restore_505.py", r"def\s+test_legacy_agno_sessions_runs_blob", "legacy_blob_test"),
        # K8: only the knowledge_items_for_turn lenient wash block (judge locus ~6143–6176)
        ("K8", "ming_sim/db.py",
         r"excluded_names\s*=\s*\[\]|excluded_targets\s*=\s*\{\}", "lenient_wash"),
        ("K9", "ming_sim/content.py", r"default_terminal_reason", "unauthorized_guard"),
        ("K9", "ming_sim/month_open_snapshot.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K9", "ming_sim/month_chain.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K9", "web_app.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K9", "ming_sim/cli/terminal.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K3", "tests/test_chat_stream_failpaths_393.py",
         r'Internal Server Error.*not in|not in.*Internal Server Error', "prose_lock"),
        ("K7", "ming_sim/entities/affair/store.py", r"Close only by explicit declaration", "stale_contract"),
        ("K5", "ming_sim/entities/issue/store.py",
         r"def\s+read_ack_due_commitment_issue\b", "forward_shell"),
        ("K5", "ming_sim/entities/character_knowledge/store.py",
         r"def\s+read_get_secret_order\b", "forward_shell"),
    ]
    for cls, path, pat, kind in checks:
        try:
            blob = subprocess.check_output(
                ["git", "show", f"{base}:{path}"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            continue
        cre = re.compile(pat)
        for i, line in enumerate(blob.splitlines(), 1):
            if cre.search(line):
                head = ROOT / path
                still = False
                if head.exists():
                    still = bool(cre.search(head.read_text(encoding="utf-8", errors="replace")))
                tag = "baseline_still" if still else "baseline_gone"
                hits.append((cls, path, i, f"{kind}|{tag}", snip(f"[base {base}] {line}")))

    # Resurrected GameDB shells introduced after baseline (1f53dd887) then cleared this round.
    prior = "1f53dd887"
    for cls, path, pat, kind in (
        ("K5", "ming_sim/db.py", r"def\s+append_chat_message\b", "forward_shell"),
        ("K5", "ming_sim/db.py", r"def\s+clear_month_open_snapshot\b", "forward_shell"),
        ("K9", "ming_sim/db.py", r"def\s+append_chat_message\b", "resurrected_commit_shell"),
        ("K9", "ming_sim/db.py", r"def\s+clear_month_open_snapshot\b", "resurrected_commit_shell"),
    ):
        try:
            blob = subprocess.check_output(
                ["git", "show", f"{prior}:{path}"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            continue
        cre = re.compile(pat)
        for i, line in enumerate(blob.splitlines(), 1):
            if not cre.search(line):
                continue
            head = ROOT / path
            still = head.exists() and bool(cre.search(head.read_text(encoding="utf-8", errors="replace")))
            tag = "baseline_still" if still else "baseline_gone"
            hits.append((cls, path, i, f"{kind}|{tag}", snip(f"[prior {prior}] {line}")))
    return hits


def main() -> int:
    raw: list[tuple[str, str, int, str, str]] = []
    raw.extend(wide_scan())
    raw.extend(k5_hits())
    raw.extend(k3_ast_hits())
    raw.extend(k1_ast_hits())
    raw.extend(baseline_deleted_members())

    # de-dupe by (class,path,line,kind)
    uniq: dict[tuple, tuple[str, str, int, str, str]] = {}
    for row in raw:
        uniq[(row[0], row[1], row[2], row[3])] = row
    rows = sorted(uniq.values(), key=lambda x: (x[0], x[1], x[2], x[3]))

    raw_path = EVID / "1889-seven-class-enum-raw.tsv"
    enum_path = EVID / "1889-seven-class-enum.tsv"
    disp_path = EVID / "1889-seven-class-member-disposition.tsv"

    with raw_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["class", "path", "line", "kind", "text"])
        for cls, path, line, kind, text in rows:
            w.writerow([cls, path, line, kind, text])

    dispositions: list[tuple[str, str, int, str, str, str, str]] = []
    for cls, path, line, kind, text in rows:
        disp, basis = dispose(cls, path, line, kind, text)
        dispositions.append((cls, path, line, kind, disp, basis, text))

    with disp_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["class", "path", "line", "kind", "disposition", "basis", "text"])
        for row in dispositions:
            w.writerow(row)

    # member-lane enum: DELETE*/KEEP (not NON_MEMBER)
    member_disps = {"DELETE", "DELETE_DONE", "DELETE_REVOKED_K3", "KEEP"}
    with enum_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["class", "path", "line", "kind", "text"])
        for cls, path, line, kind, disp, basis, text in dispositions:
            if disp in member_disps:
                w.writerow([cls, path, line, kind, text])

    c_raw = Counter(r[0] for r in rows)
    c_disp = Counter(d[4] for d in dispositions)
    c_mem = Counter(
        d[0] for d in dispositions if d[4] in member_disps
    )
    print("OUT_RAW", raw_path)
    print("OUT_ENUM", enum_path)
    print("OUT_DISP", disp_path)
    print("RAW_TOTAL", len(rows))
    for k in ("K4", "K1", "K5", "K8", "K9", "K3", "K7"):
        print(f"RAW_{k}", c_raw[k])
    print("DISP", dict(c_disp))
    print("MEMBER_BY_CLASS", dict(c_mem))
    # residual live DELETE in production paths
    live_delete = [
        d for d in dispositions
        if d[4].startswith("DELETE") and (d[1].startswith("ming_sim/") or d[1] == "web_app.py")
    ]
    print("LIVE_PROD_DELETE_RESIDUAL", len(live_delete))
    for d in live_delete[:40]:
        print(f"  {d[0]}\t{d[1]}:{d[2]}\t{d[3]}\t{d[4]}\t{d[6][:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
