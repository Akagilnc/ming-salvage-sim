#!/usr/bin/env python3
"""#1889 K1/K2 full-class diagnostic enumerator (evidence only; no production side effects).

Universe = git ls-files (version-controlled prod/test Python + SQL-bearing files).
Baselines for deleted-entry extraction: fa0175a26 and ddf53881f → HEAD.

Outputs (under docs/ when --write):
  - 1889-k1-k2-deleted-entries.tsv
  - 1889-k1-k2-members.tsv
  - 1889-k1-k2-k2-hits.tsv

Does not invent deletion authority: marks candidates; humans/receipt decide disposition.
"""
from __future__ import annotations

import argparse
import ast
import csv
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ("fa0175a26", "ddf53881f")
PROD_PREFIXES = ("ming_sim/",)
PROD_FILES = {"web_app.py"}
TEST_PREFIX = "tests/"

SQL_DROP_RE = re.compile(
    r"\bDROP\s+(?:TABLE|VIEW|INDEX|TRIGGER)\s+(?:IF\s+EXISTS\s+)?([`\"']?\w+[`\"']?)",
    re.I,
)
SQL_ALTER_RE = re.compile(r"\bALTER\s+TABLE\s+([`\"']?\w+[`\"']?)", re.I)
SQL_CREATE_RE = re.compile(
    r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW|INDEX|TRIGGER)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([`\"']?\w+[`\"']?)",
    re.I,
)
# Migration / old-layout clues beyond DROP IF EXISTS
MIGRATE_NAME_RE = re.compile(
    r"(?i)(_migrate_|_backfill_|_drop_|_ensure_.*column|legacy_|old_layout|"
    r"dossier_progress_reports|IF\s+EXISTS)"
)


def git_ls_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [p for p in out.splitlines() if p]


def is_prod_py(path: str) -> bool:
    return path.endswith(".py") and (
        path.startswith(PROD_PREFIXES) or path in PROD_FILES
    )


def is_test_py(path: str) -> bool:
    return path.endswith(".py") and path.startswith(TEST_PREFIX)


def is_sqlish(path: str) -> bool:
    return path.endswith((".py", ".sql")) and (
        is_prod_py(path)
        or path.startswith(PROD_PREFIXES)
        or path.endswith(".sql")
    )


def deleted_def_names(base: str) -> dict[str, list[str]]:
    """Map deleted def name → list of files where a def line was removed in base..HEAD."""
    diff = subprocess.check_output(
        ["git", "diff", "-U0", f"{base}..HEAD", "--", "ming_sim/", "tests/", "web_app.py"],
        cwd=ROOT,
        text=True,
        errors="replace",
    )
    by_name: dict[str, list[str]] = defaultdict(list)
    cur = None
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            m = re.search(r" b/(.+)$", line)
            cur = m.group(1) if m else None
        elif line.startswith("-") and not line.startswith("---"):
            m = re.match(r"-\s*(?:async\s+)?def\s+(\w+)\s*\(", line)
            if m and cur:
                by_name[m.group(1)].append(cur)
    return dict(by_name)


def is_persistence_prod_file(path: str) -> bool:
    """GameDB / entity Store production paths — the consumer-retirement universe for K1/K2 cross."""
    if path == "ming_sim/db.py":
        return True
    if path.startswith("ming_sim/entities/") and path.endswith("store.py"):
        return True
    return False


# Builtin / stdlib / overly-common names that collide when crossing deleted_union with AST calls.
_NOISE_SYMBOLS = frozenset(
    {
        "join",
        "run",
        "start",
        "close",
        "open",
        "read",
        "write",
        "get",
        "set",
        "pop",
        "push",
        "call",
        "load",
        "save",
        "update",
        "delete",
        "clear",
        "copy",
        "bind",
        "chat",
        "claim",
        "complete",
        "resolve",
        "format",
        "items",
        "keys",
        "values",
        "append",
        "extend",
        "remove",
        "replace",
        "split",
        "strip",
        "lower",
        "upper",
        "encode",
        "decode",
        "count",
        "index",
        "sort",
        "filter",
        "map",
        "next",
        "iter",
        "len",
        "str",
        "int",
        "list",
        "dict",
        "set",
        "tuple",
        "type",
        "id",
        "name",
        "path",
        "value",
        "result",
        "data",
        "text",
        "json",
        "commit",
        "execute",
        "fetchall",
        "fetchone",
        "connect",
        "cursor",
        "rollback",
        "flush",
        "seek",
        "tell",
        "flush",
        "wait",
        "sleep",
        "lock",
        "unlock",
        "acquire",
        "release",
        "enter",
        "exit",
        "send",
        "recv",
        "parse",
        "dump",
        "dumps",
        "loads",
        "match",
        "search",
        "sub",
        "group",
        "groups",
        "add",
        "put",
        "post",
        "patch",
        "head",
        "options",
        "trace",
        "main",
        "test",
        "setup",
        "teardown",
        "fixture",
        "parametrize",
        "raises",
        "warns",
        "skip",
        "xfail",
        "mark",
        "monkeypatch",
        "tmpdir",
        "tmp_path",
        "capsys",
        "capfd",
        "request",
        "pytest",
        "mock",
        "MagicMock",
        "AsyncMock",
        "side_effect",
        "return_value",
        "assert_called",
        "assert_called_with",
        "assert_called_once",
        "assert_called_once_with",
        "assert_not_called",
        "call_args",
        "call_args_list",
        "reset_mock",
        "configure_mock",
        "attach_mock",
        "web_game",
        "bind_content",
        "resolve_turn",
        "write_decree",
        "update_directive",
        "minister_chat",
        "undo_last_chat",
        "chat_stream",
        "retry_interrupted_reply",
        "pending_action_failures_for",
    }
)


def parse_file(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


@dataclass
class MethodDef:
    file: str
    class_name: str
    name: str
    lineno: int
    end_lineno: int
    is_private: bool
    body_norm: str
    kind: str  # store | gamedb | other


@dataclass
class RefHit:
    file: str
    lineno: int
    kind: str  # attr | name | str | hasattr | monkeypatch | assert | call
    snippet: str


def normalize_body(src: str, name: str) -> str:
    body = src
    body = re.sub(rf"\bdef\s+{re.escape(name)}\s*\(", "def __NAME__(", body, count=1)
    body = re.sub(r"\s+", " ", body).strip()
    return body


def collect_methods(files: list[str]) -> list[MethodDef]:
    methods: list[MethodDef] = []
    for rel in files:
        path = ROOT / rel
        tree = parse_file(path)
        if tree is None:
            continue
        src = path.read_text(encoding="utf-8")
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            kind = (
                "store"
                if node.name.endswith("Store")
                else "gamedb"
                if node.name == "GameDB"
                else "other"
            )
            if kind == "other":
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                seg = ast.get_source_segment(src, item) or ""
                methods.append(
                    MethodDef(
                        file=rel,
                        class_name=node.name,
                        name=item.name,
                        lineno=item.lineno,
                        end_lineno=getattr(item, "end_lineno", item.lineno) or item.lineno,
                        is_private=item.name.startswith("_"),
                        body_norm=normalize_body(seg, item.name),
                        kind=kind,
                    )
                )
    return methods


def collect_refs(files: list[str]) -> dict[str, list[RefHit]]:
    """Index references by symbol name across prod+test."""
    refs: dict[str, list[RefHit]] = defaultdict(list)
    for rel in files:
        path = ROOT / rel
        tree = parse_file(path)
        if tree is None:
            continue
        src_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        class Visitor(ast.NodeVisitor):
            def visit_Attribute(self, node: ast.Attribute) -> None:
                refs[node.attr].append(
                    RefHit(rel, getattr(node, "lineno", 0), "attr", _snip(src_lines, node.lineno))
                )
                self.generic_visit(node)

            def visit_Name(self, node: ast.Name) -> None:
                refs[node.id].append(
                    RefHit(rel, getattr(node, "lineno", 0), "name", _snip(src_lines, node.lineno))
                )
                self.generic_visit(node)

            def visit_Constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, str):
                    # whole-string exact or token-like dynamic clue
                    val = node.value
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", val):
                        refs[val].append(
                            RefHit(
                                rel,
                                getattr(node, "lineno", 0),
                                "str",
                                _snip(src_lines, node.lineno),
                            )
                        )
                    else:
                        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", val):
                            refs[tok].append(
                                RefHit(
                                    rel,
                                    getattr(node, "lineno", 0),
                                    "str_token",
                                    _snip(src_lines, node.lineno),
                                )
                            )
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                # hasattr(obj, "name") / getattr(obj, "name")
                if isinstance(node.func, ast.Name) and node.func.id in {
                    "hasattr",
                    "getattr",
                    "setattr",
                    "delattr",
                }:
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        if isinstance(node.args[1].value, str):
                            refs[node.args[1].value].append(
                                RefHit(
                                    rel,
                                    getattr(node, "lineno", 0),
                                    f"dyn_{node.func.id}",
                                    _snip(src_lines, node.lineno),
                                )
                            )
                # monkeypatch.setattr(db, "name", ...)
                if isinstance(node.func, ast.Attribute) and node.func.attr == "setattr":
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        if isinstance(node.args[1].value, str):
                            refs[node.args[1].value].append(
                                RefHit(
                                    rel,
                                    getattr(node, "lineno", 0),
                                    "monkeypatch",
                                    _snip(src_lines, node.lineno),
                                )
                            )
                self.generic_visit(node)

        Visitor().visit(tree)
    return refs


def _snip(lines: list[str], lineno: int, width: int = 160) -> str:
    if not lineno or lineno < 1 or lineno > len(lines):
        return ""
    return lines[lineno - 1].strip()[:width]


def external_refs(
    name: str,
    def_file: str,
    def_lineno: int,
    def_end: int,
    refs: dict[str, list[RefHit]],
) -> list[RefHit]:
    out = []
    for hit in refs.get(name, []):
        if hit.file == def_file and def_lineno <= hit.lineno <= def_end:
            continue  # definition site
        out.append(hit)
    return out


def scan_sql_old_layout(files: list[str]) -> list[dict]:
    rows = []
    create_names: set[str] = set()
    texts: list[tuple[str, str]] = []
    for rel in files:
        if not is_sqlish(rel) and not is_prod_py(rel):
            continue
        if not (is_prod_py(rel) or rel.endswith(".sql")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        texts.append((rel, text))
        for m in SQL_CREATE_RE.finditer(text):
            create_names.add(m.group(1).strip("`\"'"))

    for rel, text in texts:
        for i, line in enumerate(text.splitlines(), 1):
            for m in SQL_DROP_RE.finditer(line):
                name = m.group(1).strip("`\"'")
                rows.append(
                    {
                        "lane": "K1",
                        "member": f"SQL_DROP:{name}",
                        "location": f"{rel}:{i}",
                        "class": "sql_old_layout",
                        "detail": line.strip()[:200],
                        "create_exists": str(name in create_names),
                        "ref_count": "n/a",
                        "retired_consumer": "n/a",
                        "suggested": "delete" if name not in create_names else "review",
                        "reason": (
                            "DROP without production CREATE peer — old-layout disposal"
                            if name not in create_names
                            else "DROP has CREATE peer — likely recreate/migrate; review"
                        ),
                    }
                )
            # ALTER TABLE in prod (not tests) — surface for review, not auto-delete
            if is_prod_py(rel) or rel.endswith(".sql"):
                for m in SQL_ALTER_RE.finditer(line):
                    if "ADD COLUMN" in line.upper() or "RENAME" in line.upper() or "DROP" in line.upper():
                        rows.append(
                            {
                                "lane": "K1",
                                "member": f"SQL_ALTER:{m.group(1).strip(chr(96)+chr(34)+chr(39))}",
                                "location": f"{rel}:{i}",
                                "class": "sql_alter",
                                "detail": line.strip()[:200],
                                "create_exists": "n/a",
                                "ref_count": "n/a",
                                "retired_consumer": "n/a",
                                "suggested": "review",
                                "reason": "ALTER TABLE migration/old-layout clue — not auto-authorized for delete",
                            }
                        )
            # Function-name migration clues already covered via deleted defs; skip noise
    return rows


def find_duplicate_bodies(methods: list[MethodDef]) -> list[tuple[MethodDef, MethodDef]]:
    by_body: dict[str, list[MethodDef]] = defaultdict(list)
    for m in methods:
        if len(m.body_norm) < 40:
            continue  # skip trivial stubs
        if m.name in {"__init__", "__repr__", "__str__"}:
            continue
        by_body[m.body_norm].append(m)
    pairs = []
    for group in by_body.values():
        if len(group) < 2:
            continue
        # report all combinations within group
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pairs.append((group[i], group[j]))
    return pairs


def find_duplicate_const_assignments(files: list[str]) -> list[dict]:
    """Same module-level constant name assigned in multiple prod files (not limited to POPULATION_*)."""
    assigns: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for rel in files:
        if not is_prod_py(rel):
            continue
        path = ROOT / rel
        tree = parse_file(path)
        if tree is None:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("__"):
                        assigns[t.id].append((rel, node.lineno, _snip(lines, node.lineno)))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                t = node.target
                if t.id.isupper() and not t.id.startswith("__"):
                    assigns[t.id].append((rel, node.lineno, _snip(lines, node.lineno)))
    rows = []
    for name, locs in sorted(assigns.items()):
        files_hit = {f for f, _, _ in locs}
        if len(files_hit) < 2:
            continue
        rows.append(
            {
                "lane": "K1",
                "member": f"CONST_DUP:{name}",
                "location": ";".join(f"{f}:{ln}" for f, ln, _ in locs),
                "class": "duplicate_const",
                "detail": " | ".join(s for _, _, s in locs)[:300],
                "create_exists": "n/a",
                "ref_count": str(len(locs)),
                "retired_consumer": "n/a",
                "suggested": "review",
                "reason": "Same UPPER constant assigned in multiple prod files — dual-source risk",
            }
        )
    return rows


def retired_consumer_match(method_name: str, deleted_union: set[str]) -> str | None:
    """Return deleted consumer name if this method is a leftover fragment of it."""
    if method_name in deleted_union:
        return method_name
    if method_name.startswith("read_") and method_name[5:] in deleted_union:
        return method_name[5:]
    # common fragment prefixes
    for prefix in ("read_", "write_", "get_", "list_", "save_"):
        if method_name.startswith(prefix):
            rest = method_name[len(prefix) :]
            if rest in deleted_union:
                return rest
    return None


@dataclass
class K2Hit:
    file: str
    lineno: int
    kind: str
    symbol: str
    snippet: str
    suggested: str
    reason: str


# Live domain world-slice keys: existing negative visibility contracts — NOT retirement proofs.
_LIVE_WORLD_NEGATIVE_KEYS = frozenset(
    {"personnel", "military", "treasury", "court", "region_id", "arrears", "noise"}
)


def enumerate_k2(
    test_files: list[str],
    deleted_persistence: set[str],
    live_gamedb: set[str],
    live_store: set[str],
) -> list[K2Hit]:
    """Cross test surfaces with production persistence deleted entries only.

    deleted_persistence = names removed from ming_sim/db.py or */store.py (not test helpers).
    """
    hits: list[K2Hit] = []
    # Internal retired-shape: _meta key absence specifically (standalone retirement proof)
    meta_retired = re.compile(
        r"""(?:assert\s+not\s+any\(.*['\"]standalone['\"].*_meta)"""
        r"""|(?:['\"]standalone['\"].*(?:not\s+in|_meta))"""
        r"""|(?:_meta.*['\"]standalone['\"])"""
    )
    inspect_source = re.compile(
        r"""inspect\.getsource|getsource\(|\bco_code\b|__code__"""
    )
    hasattr_absence = re.compile(
        r"""assert\s+not\s+hasattr|hasattr\([^,]+,\s*['\"](\w+)['\"]\)\s*is\s*False"""
    )

    # Substantial persistence entry names only for name-embedding checks
    substantial = {
        d
        for d in deleted_persistence
        if d not in _NOISE_SYMBOLS
        and (
            len(d) >= 12
            or d.startswith("turn_")
            or d.endswith("_report")
            or d.endswith("_summary")
            or d.endswith("_ledger")
            or "vacanc" in d
            or d.startswith("read_")
            or d.startswith("list_")
        )
    }

    for rel in test_files:
        path = ROOT / rel
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tree = parse_file(path)
        if tree is None:
            continue

        test_funcs: list[tuple[str, int]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                test_funcs.append((node.name, node.lineno))
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith(
                        "test_"
                    ):
                        test_funcs.append((item.name, item.lineno))

        for name, ln in test_funcs:
            for d in substantial:
                if d in name:
                    hits.append(
                        K2Hit(
                            rel,
                            ln,
                            "test_def_name",
                            d,
                            f"def {name}",
                            "rename_or_review",
                            f"test name embeds deleted persistence entry '{d}'",
                        )
                    )

        class V(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Attribute) and node.func.attr == "setattr":
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        sym = node.args[1].value
                        if isinstance(sym, str) and sym not in _NOISE_SYMBOLS:
                            snip = _snip(lines, node.lineno)
                            # Target object: first positional arg must be Name 'db' (not web_app).
                            target_is_db = (
                                len(node.args) >= 1
                                and isinstance(node.args[0], ast.Name)
                                and node.args[0].id == "db"
                            )
                            if (
                                sym in deleted_persistence
                                and sym not in live_gamedb
                                and sym not in live_store
                                and target_is_db
                            ):
                                hits.append(
                                    K2Hit(
                                        rel,
                                        node.lineno,
                                        "monkeypatch_deleted",
                                        sym,
                                        snip,
                                        "delete_hook",
                                        "monkeypatch db.<deleted persistence entry>",
                                    )
                                )
                            elif (
                                target_is_db
                                and sym not in live_gamedb
                                and sym not in live_store
                                and len(sym) >= 8
                            ):
                                hits.append(
                                    K2Hit(
                                        rel,
                                        node.lineno,
                                        "monkeypatch_missing_gamedb",
                                        sym,
                                        snip,
                                        "delete_hook_or_retarget",
                                        "monkeypatch db.<name> but name not on live GameDB/Store",
                                    )
                                )
                if isinstance(node.func, ast.Name) and node.func.id == "hasattr":
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        sym = node.args[1].value
                        if (
                            isinstance(sym, str)
                            and sym in deleted_persistence
                            and sym not in _NOISE_SYMBOLS
                        ):
                            hits.append(
                                K2Hit(
                                    rel,
                                    node.lineno,
                                    "hasattr_deleted",
                                    sym,
                                    _snip(lines, node.lineno),
                                    "review",
                                    "hasattr probes deleted persistence entry — may be absence proof",
                                )
                            )
                if isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                    if (
                        attr in deleted_persistence
                        and attr not in live_gamedb
                        and attr not in live_store
                        and attr not in _NOISE_SYMBOLS
                        and len(attr) >= 8
                    ):
                        hits.append(
                            K2Hit(
                                rel,
                                node.lineno,
                                "call_deleted",
                                attr,
                                _snip(lines, node.lineno),
                                "review_1873_gap",
                                "test calls truly-deleted persistence entry; may be #1873 gap — do not invent restore or delete behavioral coverage",
                            )
                        )
                self.generic_visit(node)

            def visit_Assert(self, node: ast.Assert) -> None:
                snip = _snip(lines, node.lineno)
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        val = sub.value
                        if (
                            val in deleted_persistence
                            and val not in live_gamedb
                            and val not in live_store
                            and val not in _NOISE_SYMBOLS
                            and val not in _LIVE_WORLD_NEGATIVE_KEYS
                            and len(val) >= 8
                        ):
                            hits.append(
                                K2Hit(
                                    rel,
                                    node.lineno,
                                    "assert_deleted_str",
                                    val,
                                    snip,
                                    "review",
                                    "assert string names deleted persistence entry",
                                )
                            )
                if inspect_source.search(snip):
                    hits.append(
                        K2Hit(
                            rel,
                            node.lineno,
                            "assert_source_shape",
                            "",
                            snip,
                            "review",
                            "assert inspects source — internal shape lock risk",
                        )
                    )
                if hasattr_absence.search(snip):
                    m = hasattr_absence.search(snip)
                    sym = m.group(1) if m and m.lastindex else ""
                    sug = (
                        "delete_if_retirement_proof"
                        if sym in deleted_persistence
                        else "review"
                    )
                    hits.append(
                        K2Hit(
                            rel,
                            node.lineno,
                            "assert_hasattr_absence",
                            sym or "",
                            snip,
                            sug,
                            "assert not hasattr — absence/retirement proof risk",
                        )
                    )
                if meta_retired.search(snip) or (
                    "_meta" in snip and "standalone" in snip and ("not" in snip or "any(" in snip)
                ):
                    hits.append(
                        K2Hit(
                            rel,
                            node.lineno,
                            "assert_meta_key_absence",
                            "standalone/_meta",
                            snip,
                            "delete_if_retirement_proof",
                            "assert on _meta standalone key absence — internal retired-shape",
                        )
                    )
                # Classify live world negative contracts as KEEP (still enumerate for evidence)
                if re.search(
                    r"""assert\s+['\"]?(personnel|military|treasury|court)['\"]?\s+not\s+in\s+.*world""",
                    snip,
                ):
                    hits.append(
                        K2Hit(
                            rel,
                            node.lineno,
                            "live_world_negative",
                            "",
                            snip,
                            "keep",
                            "现役公私可见边界负向契约 — 保留",
                        )
                    )
                self.generic_visit(node)

        V().visit(tree)

        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue
            if meta_retired.search(line) or (
                "_meta" in line and "standalone" in line and ("not" in line or "any(" in line)
            ):
                if not any(
                    h.file == rel and h.lineno == i and h.kind == "assert_meta_key_absence" for h in hits
                ):
                    hits.append(
                        K2Hit(
                            rel,
                            i,
                            "assert_meta_key_absence",
                            "standalone/_meta",
                            line.strip()[:160],
                            "delete_if_retirement_proof",
                            "line-level _meta/standalone absence proof",
                        )
                    )
            if "getsource" in line or "co_code" in line:
                if not any(h.file == rel and h.lineno == i and h.kind in {"source_probe", "assert_source_shape"} for h in hits):
                    hits.append(
                        K2Hit(
                            rel,
                            i,
                            "source_probe",
                            "",
                            line.strip()[:160],
                            "review",
                            "source/bytecode probe — internal shape lock risk",
                        )
                    )

    seen = set()
    uniq = []
    for h in hits:
        key = (h.file, h.lineno, h.kind, h.symbol)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Write TSV evidence under docs/")
    ap.add_argument("--quiet", action="store_true", help="Less stdout")
    args = ap.parse_args()

    all_files = git_ls_files()
    prod_py = [p for p in all_files if is_prod_py(p)]
    test_py = [p for p in all_files if is_test_py(p)]
    scan_py = prod_py + test_py

    deleted_by_base: dict[str, dict[str, list[str]]] = {
        b: deleted_def_names(b) for b in BASELINES
    }
    deleted_union: set[str] = set()
    deleted_persistence: set[str] = set()
    for mapping in deleted_by_base.values():
        deleted_union |= set(mapping)
        for name, files in mapping.items():
            if any(is_persistence_prod_file(f) for f in files):
                deleted_persistence.add(name)

    # Persist deleted-entry table (full union + persistence flag)
    deleted_rows = []
    for base, mapping in deleted_by_base.items():
        for name, files in sorted(mapping.items()):
            prod_files = sorted({f for f in files if is_prod_py(f) or f.startswith("ming_sim/")})
            test_files_hit = sorted({f for f in files if is_test_py(f)})
            deleted_rows.append(
                {
                    "baseline": base,
                    "name": name,
                    "prod_files": ",".join(prod_files) or "-",
                    "test_files": ",".join(test_files_hit) or "-",
                    "persistence_consumer": (
                        "1" if any(is_persistence_prod_file(f) for f in files) else "0"
                    ),
                    "in_fa0175a26": "1" if name in deleted_by_base["fa0175a26"] else "0",
                    "in_ddf53881f": "1" if name in deleted_by_base["ddf53881f"] else "0",
                }
            )

    methods = collect_methods(prod_py)
    refs = collect_refs(scan_py)
    live_gamedb = {m.name for m in methods if m.kind == "gamedb"}
    live_store = {m.name for m in methods if m.kind == "store"}
    # git diff -def includes rewritten methods that still exist; true retirement =
    # persistence-path deletion AND name absent from live GameDB/Store defs.
    truly_deleted = {
        n for n in deleted_persistence if n not in live_gamedb and n not in live_store
    }

    member_rows: list[dict] = []

    # --- All Store + GameDB methods ---
    for m in methods:
        ext = external_refs(m.name, m.file, m.lineno, m.end_lineno, refs)
        # Consumer-retirement matching uses truly-deleted persistence entries only.
        retired = retired_consumer_match(m.name, truly_deleted)
        ref_kinds = sorted({h.kind for h in ext})
        ref_files = sorted({h.file for h in ext})

        if retired and len(ext) == 0:
            suggested, reason = (
                "delete",
                f"fragment of deleted consumer '{retired}'; zero references (attr/name/str/dyn)",
            )
            cls = "retired_fragment_unref"
        elif retired and len(ext) > 0:
            suggested, reason = (
                "keep",
                f"name matches deleted consumer '{retired}' but still has {len(ext)} refs — live or pending wiring",
            )
            cls = "retired_name_still_referenced"
        elif len(ext) == 0 and m.kind == "store" and not m.is_private:
            suggested, reason = (
                "keep",
                "statically unreferenced public Store API — NOT auto-delete; may be pending family wiring (Vulture false-positive risk)",
            )
            cls = "unref_public_store"
        elif len(ext) == 0 and m.kind == "store" and m.is_private:
            # private with zero refs — still only review unless duplicate
            suggested, reason = (
                "review",
                "private Store helper with zero refs — review; no delete authority from static unref alone",
            )
            cls = "unref_private_store"
        elif len(ext) == 0 and m.kind == "gamedb":
            suggested, reason = (
                "review",
                "GameDB method with zero static refs — review; may be web/CLI dynamic entry",
            )
            cls = "unref_gamedb"
        else:
            suggested, reason = ("keep", f"referenced ({len(ext)} hits; kinds={ref_kinds})")
            cls = "referenced"

        member_rows.append(
            {
                "lane": "K1",
                "member": f"{m.class_name}.{m.name}",
                "location": f"{m.file}:{m.lineno}",
                "class": cls,
                "detail": f"kind={m.kind}; refs={len(ext)}; files={','.join(ref_files[:5])}",
                "create_exists": "n/a",
                "ref_count": str(len(ext)),
                "retired_consumer": retired or "",
                "suggested": suggested,
                "reason": reason,
            }
        )

    # --- Duplicate method bodies ---
    for a, b in find_duplicate_bodies(methods):
        a_refs = external_refs(a.name, a.file, a.lineno, a.end_lineno, refs)
        b_refs = external_refs(b.name, b.file, b.lineno, b.end_lineno, refs)
        if len(a_refs) == 0 and len(b_refs) > 0:
            dead, live = a, b
        elif len(b_refs) == 0 and len(a_refs) > 0:
            dead, live = b, a
        else:
            dead = live = None
        if dead and live:
            member_rows.append(
                {
                    "lane": "K1",
                    "member": f"DUP_BODY:{dead.class_name}.{dead.name}",
                    "location": f"{dead.file}:{dead.lineno}",
                    "class": "duplicate_body",
                    "detail": f"same body as {live.class_name}.{live.name}@{live.file}:{live.lineno} (live refs={len(external_refs(live.name, live.file, live.lineno, live.end_lineno, refs))})",
                    "create_exists": "n/a",
                    "ref_count": "0",
                    "retired_consumer": "",
                    "suggested": "delete",
                    "reason": "identical normalized body to a referenced twin; unreferenced duplicate",
                }
            )
        else:
            member_rows.append(
                {
                    "lane": "K1",
                    "member": f"DUP_BODY:{a.class_name}.{a.name}=={b.class_name}.{b.name}",
                    "location": f"{a.file}:{a.lineno};{b.file}:{b.lineno}",
                    "class": "duplicate_body_both_live_or_both_dead",
                    "detail": f"a_refs={len(a_refs)} b_refs={len(b_refs)}",
                    "create_exists": "n/a",
                    "ref_count": str(len(a_refs) + len(b_refs)),
                    "retired_consumer": "",
                    "suggested": "review",
                    "reason": "duplicate bodies but neither is clearly the dead twin — no auto-delete",
                }
            )

    # --- SQL old layout ---
    member_rows.extend(scan_sql_old_layout(all_files))

    # --- Duplicate constants ---
    member_rows.extend(find_duplicate_const_assignments(prod_py))

    # --- K2 ---
    k2_hits = enumerate_k2(test_py, truly_deleted, live_gamedb, live_store)
    # Annotate call_deleted when production still references the missing name.
    for h in k2_hits:
        if h.kind != "call_deleted" or not h.symbol:
            continue
        prod_refs = [
            r
            for r in refs.get(h.symbol, [])
            if r.file.startswith("ming_sim/") or r.file == "web_app.py"
        ]
        if prod_refs:
            h.suggested = "keep_escalate_1873"
            h.reason = (
                f"test+prod still call missing '{h.symbol}' "
                f"(prod hits={len(prod_refs)} e.g. {prod_refs[0].file}:{prod_refs[0].lineno}) "
                "— #1873 functional gap; not K2 retirement-shape cleanup"
            )
    k2_rows = [
        {
            "lane": "K2",
            "member": f"{h.kind}:{h.symbol or '-'}",
            "location": f"{h.file}:{h.lineno}",
            "class": h.kind,
            "detail": h.snippet,
            "create_exists": "n/a",
            "ref_count": "n/a",
            "retired_consumer": h.symbol,
            "suggested": h.suggested,
            "reason": h.reason,
        }
        for h in k2_hits
    ]

    # Summary counts
    def count(rows, pred):
        return sum(1 for r in rows if pred(r))

    store_n = sum(1 for m in methods if m.kind == "store")
    gamedb_n = sum(1 for m in methods if m.kind == "gamedb")
    k1_delete = count(member_rows, lambda r: r["lane"] == "K1" and r["suggested"] == "delete")
    k1_review = count(member_rows, lambda r: r["lane"] == "K1" and r["suggested"] == "review")
    k1_keep = count(member_rows, lambda r: r["lane"] == "K1" and r["suggested"] == "keep")
    retired_unref = count(member_rows, lambda r: r["class"] == "retired_fragment_unref")
    unref_public = count(member_rows, lambda r: r["class"] == "unref_public_store")
    dup_body_del = count(
        member_rows, lambda r: r["class"] == "duplicate_body" and r["suggested"] == "delete"
    )
    sql_drop = count(member_rows, lambda r: r["class"] == "sql_old_layout")
    const_dup = count(member_rows, lambda r: r["class"] == "duplicate_const")

    k2_deleteish = count(
        k2_rows,
        lambda r: r["suggested"]
        in {
            "delete_hook",
            "delete_if_retirement_proof",
            "delete_or_retarget",
            "delete_hook_or_retarget",
        },
    )
    k2_1873 = count(
        k2_rows,
        lambda r: r["suggested"] in {"keep_escalate_1873", "review_1873_gap"},
    )

    if not args.quiet:
        print("=== #1889 K1/K2 full enumeration ===")
        print(f"git_ls_files py prod={len(prod_py)} tests={len(test_py)} all_tracked={len(all_files)}")
        print(f"Store methods={store_n} GameDB methods={gamedb_n}")
        for b in BASELINES:
            print(f"deleted def names {b}..HEAD = {len(deleted_by_base[b])}")
        print(f"deleted_union unique names = {len(deleted_union)}")
        print(f"deleted_persistence (GameDB/Store) = {len(deleted_persistence)}")
        print(f"truly_deleted (persistence gone at HEAD) = {len(truly_deleted)}")
        print(
            f"K1 member rows={len(member_rows)} "
            f"suggested delete={k1_delete} review={k1_review} keep={k1_keep}"
        )
        print(
            f"  retired_fragment_unref={retired_unref} unref_public_store={unref_public} "
            f"dup_body_delete={dup_body_del} sql_drop={sql_drop} const_dup={const_dup}"
        )
        print(
            f"K2 hits={len(k2_rows)} deleteish={k2_deleteish} "
            f"1873_gap_annotated={k2_1873}"
        )
        print("--- K1 suggested=delete (actionable) ---")
        any_del = False
        for r in member_rows:
            if r["suggested"] == "delete":
                any_del = True
                print(f"  {r['member']} @ {r['location']} :: {r['reason'][:120]}")
        if not any_del:
            print("  (none)")
        print("--- K2 deleteish (authorized retirement-shape cleanup) ---")
        any_k2 = False
        for r in k2_rows:
            if r["suggested"] in {
                "delete_hook",
                "delete_if_retirement_proof",
                "delete_or_retarget",
                "delete_hook_or_retarget",
            }:
                any_k2 = True
                print(f"  {r['member']} @ {r['location']} :: {r['detail'][:100]}")
        if not any_k2:
            print("  (none)")
        print("--- K2 #1873 gap annotations (not deleted this round) ---")
        any_gap = False
        for r in k2_rows:
            if r["suggested"] in {"keep_escalate_1873", "review_1873_gap"}:
                any_gap = True
                print(f"  {r['member']} @ {r['location']} :: {r['reason'][:120]}")
        if not any_gap:
            print("  (none)")

    if args.write:
        docs = ROOT / "docs"
        write_tsv(
            docs / "1889-k1-k2-deleted-entries.tsv",
            [
                "baseline",
                "name",
                "prod_files",
                "test_files",
                "persistence_consumer",
                "in_fa0175a26",
                "in_ddf53881f",
            ],
            deleted_rows,
        )
        fields = [
            "lane",
            "member",
            "location",
            "class",
            "detail",
            "create_exists",
            "ref_count",
            "retired_consumer",
            "suggested",
            "reason",
        ]
        write_tsv(docs / "1889-k1-k2-members.tsv", fields, member_rows)
        write_tsv(docs / "1889-k1-k2-k2-hits.tsv", fields, k2_rows)
        print(
            f"wrote docs/1889-k1-k2-deleted-entries.tsv ({len(deleted_rows)}), "
            f"docs/1889-k1-k2-members.tsv ({len(member_rows)}), "
            f"docs/1889-k1-k2-k2-hits.tsv ({len(k2_rows)})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
