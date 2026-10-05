#!/usr/bin/env python3
"""#1889 last-judge seven-class full-repo enumerator + disposition.

Ticket class definitions (not sample allowlists). Writes under evidence/:
  1889-seven-class-enum-raw.tsv   — every predicate hit (wide scan)
  1889-seven-class-enum.tsv       — member-lane hits (kind tagged)
  1889-seven-class-member-disposition.tsv — every raw hit disposed

Re-run from worktree:
  python3 evidence/1889-seven-class-enumerate.py

Full-repo means production surfaces are not excluded by file-prefix allowlists
(root/scripts/spike/launcher included). tests/web evidence scanned for residual
and K3 text contracts. Disposition requires a per-hit semantic basis — no batch
KEEP default.
"""
from __future__ import annotations

import ast
import csv
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = Path(__file__).resolve().parent
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".pytest_cache", "artifacts",
}

SCAN_SUFFIX = (".py", ".ts", ".tsx", ".md", ".tsv", ".json", ".txt")

_SELF_OUT = {
    "evidence/1889-seven-class-enum-raw.tsv",
    "evidence/1889-seven-class-enum.tsv",
    "evidence/1889-seven-class-member-disposition.tsv",
    "evidence/1889-seven-class-fixer-receipt.md",
}


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


def git_ls(*globs: str) -> list[str]:
    cmd = ["git", "ls-files", *globs] if globs else ["git", "ls-files"]
    return subprocess.check_output(cmd, cwd=ROOT, text=True).splitlines()


def parse_py(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def is_production_py(r: str) -> bool:
    """All production Python — not tests/web UI/docs/evidence. Includes root/scripts/spike."""
    if not r.endswith(".py"):
        return False
    if r.startswith((
        "tests/", "evidence/", "docs/", "web/", "node_modules/",
        ".venv/", "venv/",
    )):
        return False
    return True


def is_test_py(r: str) -> bool:
    if not r.endswith(".py"):
        return False
    name = Path(r).name
    return (
        r.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in r
    )


def is_test_ts(r: str) -> bool:
    return r.endswith((".ts", ".tsx")) and (
        ".test." in r or ".spec." in r or "/__tests__/" in r
    )


# ── predicates (full class definitions, not sample allowlists) ──────────────

K4_PAT = [
    re.compile(r"\bscale_tian_fu\b|\bread_scale_tian_fu\b"),
    re.compile(r"tax_per_turn\s*[-+]=|tax_per_turn\s*=\s*.*(?:辽饷|盐税|商税|田赋|tian_fu)"),
    re.compile(r"calc_province_fiscal|legacy.?fiscal|scalar.?tian|罢.?田赋", re.I),
]

# K1: superseded source / app-side old storage compat / replaced orphan mechanisms.
# Broader than blob+bare samples; dispose distinguishes live domain (遗产/alias fold/
# secrecy brief/agno_runs) from retired accept-both / sessions.runs blob paths.
K1_PAT = [
    re.compile(r"secret_order:(?!brief)"),
    re.compile(r"secret_order(?:_brief)?\s*(?:\||/)\s*secret_order"),
    re.compile(r"_SECRET_ORDER_SOURCE\s*=\s*re\.compile\([^)]*secret_order:"),
    re.compile(
        r"sessions\.runs|_agno_legacy|_decode_agno_runs|merge_runs_table_with_legacy|"
        r"_rewrite_session|agno2|Agno2|runs\s*blob|old.?blob",
        re.I,
    ),
    re.compile(r"为旧测试保留|bare.?source|旧.?blob|accept.?both|双源兼容|旧入口兼容", re.I),
    re.compile(
        r"\b(?:compat(?:ibility)?|legacy_path|fallback_path|alias_source|deprecated_path)\b",
        re.I,
    ),
    re.compile(r"\b(?:_legacy_|legacy_)(?:decode|merge|rewrite|blob|migrate|compat)\w*\b", re.I),
    re.compile(r"\b(?:load_stored_list|load_stored_json)\b.*except|except.*(?:\[\]|\{\})", re.I),
]

K8_PAT = [
    re.compile(r"excluded_names|excluded_targets"),
    re.compile(r"excluded_.*(?:except|\[\s*\]|\{\s*\})|except.*excluded_", re.I),
]

K9_PAT = [
    re.compile(r"\bdefault_terminal_reason\b"),
    re.compile(r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)"),
    # thin GameDB commit shells that previously resurrected — scan defs, not whitelist-only
    re.compile(r"def\s+append_chat_message\b|def\s+clear_month_open_snapshot\b"),
    re.compile(r"callable\(.*commit.*\).*not\s+callable\(.*conn", re.I),
]

# K3 text seed: free diagnostic negatives + revoked labels. Full AST/TS scan below
# covers wording/titles/internal labels/match= across the test corpus.
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


# ── wide text scan ──────────────────────────────────────────────────────────

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


# ── SQL helpers ─────────────────────────────────────────────────────────────

_SQL_VERB = re.compile(
    r"\b(SELECT|DELETE|INSERT(?:\s+OR\s+REPLACE)?|UPDATE|REPLACE)\b", re.I,
)
_SQL_TABLE = re.compile(
    r"\b(?:FROM|INTO|UPDATE|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I,
)


def _norm_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip())


def _sql_sig(sql: str) -> str:
    sig = _norm_sql(sql)
    sig = re.sub(r"\d+", "N", sig)
    sig = re.sub(r"'[^']*'", "'X'", sig)
    sig = re.sub(r'"[^"]*"', '"X"', sig)
    return sig


def _sql_table(sql: str) -> str:
    m = _SQL_TABLE.search(sql)
    return (m.group(1) if m else "").lower()


def _sql_verb(sql: str) -> str:
    m = _SQL_VERB.search(sql)
    return (m.group(1) if m else "").upper().split()[0]


# Tables / shapes where near-duplicate SQL is different lifecycle/status/class
# (judge C6) — used as *hints* for basis text, never as silent batch KEEP.
_LIFECYCLE_TABLES = frozenset({
    "character_knowledge_events", "pending_decisions", "event_triggers",
    "legacies", "staged_declarations", "relation_edge_events", "decree_dossiers",
    "secret_orders", "classes", "region_logs", "chat_turns", "metrics",
    "pending_promulgation_verdicts", "army_logs",
})


def _k5_sql_group_basis(sig: str, items: list[tuple[str, int, str, str]]) -> tuple[str, str]:
    """Return (kind_tag, basis_seed) for a duplicate-SQL group — never default KEEP."""
    paths = {p for p, _, _, _ in items}
    funcs = [f for _, _, f, _ in items if f]
    tables = {_sql_table(sql) for *_, sql in items}
    verbs = {_sql_verb(sql) for *_, sql in items}
    table = next(iter(tables)) if len(tables) == 1 else ",".join(sorted(tables))
    cross = len(paths) > 1
    kind = "dup_sql_cross" if cross else "dup_sql_same"

    # Shared constant / batch+single same rule (metrics upsert)
    if table == "metrics" and "INSERT" in verbs:
        return (
            f"{kind}|shared_rule_batch_single",
            "metrics upsert shared rule (batch executemany vs single); not dual authority",
        )
    # pending_decisions: decision vs rescript_draft lifecycle
    if table == "pending_decisions":
        kinds_mentioned = set()
        for *_, sql in items:
            if "rescript_draft" in sql:
                kinds_mentioned.add("rescript_draft")
            if "decision" in sql or "kind = 'decision'" in sql or 'kind = "decision"' in sql:
                kinds_mentioned.add("decision")
        if len(kinds_mentioned) >= 2 or any("rescript" in f or "decision" in f for f in funcs):
            return (
                f"{kind}|lifecycle_kind",
                "pending_decisions different kind/lifecycle (decision vs rescript_draft); judge C6",
            )
        if any(f.startswith("_delete_") or f.startswith("clear_") or f.startswith("save_") for f in funcs):
            return (
                f"{kind}|single_delete_rule",
                "pending_decisions clear/save share one delete helper — verify not dual DELETE authority",
            )
    # event_triggers terminal states
    if table == "event_triggers":
        return (
            f"{kind}|terminal_state_variants",
            "event_triggers terminal-state variants (triggered/avoided/obsolete/expired); shared upgrade rule shape",
        )
    # character_knowledge participation vs public
    if table == "character_knowledge_events":
        return (
            f"{kind}|lifecycle_source",
            "character_knowledge_events participation vs public — different source/lifecycle (judge C6)",
        )
    # legacies cleared vs expired
    if table == "legacies":
        return (
            f"{kind}|lifecycle_status",
            "legacies status transitions (cleared vs expired) — different terminal status, shared table shape",
        )
    # staged_declarations discarded vs settled
    if table == "staged_declarations":
        return (
            f"{kind}|lifecycle_status",
            "staged_declarations discarded vs settled — different status verbs on same table",
        )
    # secret_orders field updates
    if table == "secret_orders":
        return (
            f"{kind}|field_selection",
            "secret_orders field/selection variants — different columns or assignment sets, not dual rule",
        )
    # region_logs / classes displacement
    if table in ("region_logs", "classes", "army_logs"):
        return (
            f"{kind}|field_selection",
            f"{table} different field/selection filters — not the same business rule authority",
        )
    # chat_turns message-id lookups
    if table == "chat_turns":
        return (
            f"{kind}|selection_variant",
            "chat_turns selection variants (list vs latest) — different selection, shared table",
        )
    # decree_dossiers list vs snapshot
    if table == "decree_dossiers":
        return (
            f"{kind}|list_vs_snapshot",
            "decree_dossiers list vs snapshot read — different consumer lifecycle, shared row shape",
        )
    # relation_edge
    if table == "relation_edge_events":
        return (
            f"{kind}|list_vs_snapshot",
            "relation_edge_events snapshot vs owned read — different consumer path",
        )
    # sqlite_master / SELECT 1 existence probes
    if "sqlite_master" in sig.lower() or sig.upper().startswith("SELECT N FROM") or "SELECT 1 FROM" in sig.upper():
        if cross:
            return (
                f"{kind}|schema_probe",
                "local schema/existence probe helper across modules — not domain dual write authority",
            )
        return (
            f"{kind}|existence_probe",
            "existence/probe SELECT shape — not a replaced persistence rule",
        )
    # scripts gate boards
    if any(p.startswith("scripts/") for p in paths):
        return (
            f"{kind}|script_fixture",
            "scripts gate/fixture board SQL — not production dual Store authority",
        )
    # generic lifecycle table hint
    if table in _LIFECYCLE_TABLES:
        return (
            f"{kind}|lifecycle_table_hint",
            f"{table} near-duplicate SQL — review siblings for distinct status/class/selection before KEEP",
        )
    # True residual candidate: identical cross-file domain rule without lifecycle excuse
    if cross and table and table not in ("",):
        return (
            f"{kind}|cross_authority_candidate",
            f"cross-file duplicate SQL on {table} — candidate dual authority; dispose per retirement relation",
        )
    return (
        f"{kind}|shape_dup_review",
        "near-duplicate SQL shape — requires sibling function/status review; not auto-KEEP",
    )


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(getattr(body[0], "value", None), ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


_CONN_ATTRS = frozenset({"_conn", "conn", "connection", "_connection"})


def _is_store_ctor_call(call: ast.AST) -> bool:
    """True only for XxxStore(...).method(...) — not self._conn.execute (true SQL authority)."""
    if not isinstance(call, ast.Call):
        return False
    f = call.func
    if isinstance(f, ast.Name) and f.id.endswith("Store"):
        return True
    if isinstance(f, ast.Attribute):
        cur: ast.AST = f.value
        # XxxStore(conn).method(...)
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name) and cur.func.id.endswith("Store"):
            return True
        # self.<store_attr>.method(...) where store_attr is not the connection
        if isinstance(cur, ast.Attribute) and isinstance(cur.value, ast.Name) and cur.value.id == "self":
            if cur.attr in _CONN_ATTRS or cur.attr.startswith("_"):
                return False
            # heuristic store property names
            if cur.attr.endswith("s") or cur.attr in {
                "reign", "issues", "dossiers", "army", "region", "character",
                "fiscal_config", "chat_messages", "month_open_snapshots",
                "resolve_contexts", "textual_facts", "affairs", "staged",
            }:
                return True
    return False


def _is_self_method_alias(call: ast.AST) -> str | None:
    """return self.other_method(...) — one-level method alias, not self._conn.execute."""
    if not isinstance(call, ast.Call):
        return None
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
        if f.attr in _CONN_ATTRS:
            return None
        return f.attr
    return None

def _is_commit_call(call: ast.AST) -> bool:
    if not isinstance(call, ast.Call):
        return False
    u = ast.unparse(call)
    return u.endswith(".commit()") or u == "self.conn.commit()"


def _forward_kind_for(path: str, cls_name: str, meth: str, shape: str, target: str) -> tuple[str, str]:
    """Classify thin forward → (kind, basis_seed)."""
    # Store-internal return self.OTHER — replaced entry shell (judge K5 samples)
    if shape == "return_self_other" and "/entities/" in path and path.endswith("store.py"):
        if meth.startswith("read_") and any(
            x in meth for x in ("ack_due", "get_secret_order", "get_issue")
        ):
            return "forward_shell|store_replaced", "Store-internal replaced entry forwarding to true source"
        return (
            "forward_shell|store_self_alias",
            f"{cls_name}.{meth} -> self.{target}: Store self-alias; delete only if superseded entry",
        )
    # GameDB / facade -> Store(+commit)
    if path.endswith("ming_sim/db.py") or cls_name == "GameDB":
        if meth in ("append_chat_message", "clear_month_open_snapshot"):
            return (
                "forward_shell|gamedb_resurrected",
                "GameDB Store+commit resurrected shell — must delete; callers use Store+conn.commit",
            )
        # Internal GameDB method alias (self._helper / self.other) — not a Store dual entry
        if shape == "return_self_other" and "Store(" not in target:
            return (
                "forward_shell|gamedb_internal_alias",
                "GameDB internal method alias — not Store dual-authority forward shell",
            )
        return (
            "forward_shell|gamedb_facade_pending",
            "GameDB thin Store forward — pending domain relocation (票面待接), not auto-deleted facade wipe",
        )
    # Other modules constructing Store for a one-liner
    if "Store(" in target or shape in ("return_store", "store_commit"):
        return (
            "forward_shell|module_store_forward",
            f"{cls_name}.{meth} thin Store forward outside GameDB — review if superseded entry",
        )
    # Non-persistence method aliases (async wrappers, queue gates) — not K5 members
    return (
        "forward_shell|non_persist_alias",
        f"{cls_name}.{meth} non-persistence method alias shape={shape}; not Store dual authority",
    )

# ── K5: full-repo SQL + real thin forwards ──────────────────────────────────

def k5_hits() -> list[tuple[str, str, int, str, str]]:
    hits: list[tuple[str, str, int, str, str]] = []
    # (sig) -> list[(path, line, func, sql)]
    sql_items: list[tuple[str, str, int, str, str]] = []
    # method defs for orphan scan: name -> list[(path, line, cls)]
    store_defs: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    attr_refs: Counter[str] = Counter()

    prod_files = [p for p in git_ls("*.py") if is_production_py(p)]
    # also catch any production py walk missed by sparse git globs
    for path in iter_files(".py"):
        r = rel(path)
        if is_production_py(r) and r not in prod_files:
            prod_files.append(r)

    class Visitor(ast.NodeVisitor):
        def __init__(self, path: str):
            self.path = path
            self.func: str | None = None
            self.cls: str | None = None

        def visit_ClassDef(self, node: ast.ClassDef):
            prev = self.cls
            self.cls = node.name
            self.generic_visit(node)
            self.cls = prev

        def visit_FunctionDef(self, node: ast.FunctionDef):
            prev = self.func
            self.func = node.name
            if self.cls and self.path.endswith("store.py") and "/entities/" in self.path:
                store_defs[node.name].append((self.path, node.lineno, self.cls))
            self.generic_visit(node)
            self._detect_forward(node)
            self.func = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Attribute(self, node: ast.Attribute):
            attr_refs[node.attr] += 1
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name):
            attr_refs[node.id] += 1

        def visit_Constant(self, node: ast.Constant):
            if not isinstance(node.value, str):
                return
            u = node.value.upper()
            if not any(k in u for k in ("SELECT", "DELETE", "INSERT", "UPDATE", "REPLACE")):
                return
            if not any(k in u for k in ("FROM", "INTO", "SET", "TABLE")):
                return
            # skip huge schema DDL blobs as dup noise (CREATE TABLE scripts)
            if u.lstrip().startswith("CREATE TABLE") or "CREATE TABLE IF NOT EXISTS" in u:
                return
            norm = _norm_sql(node.value)
            if len(norm) < 12:
                return
            sig = _sql_sig(norm)
            sql_items.append((sig, self.path, node.lineno, self.func or "", norm[:180]))

        def _detect_forward(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
            body = _strip_docstring(list(node.body))
            if not body:
                return
            cls_name = self.cls or ""
            # Store classes that only `return self._conn.execute(...)` ARE the authority —
            # never classify those as forward shells.
            if "/entities/" in self.path and self.path.endswith("store.py"):
                # Only Store-internal self.OTHER method aliases (replaced entries).
                if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
                    alias = _is_self_method_alias(body[0].value)
                    if alias and alias not in _CONN_ATTRS:
                        kind, _basis = _forward_kind_for(
                            self.path, cls_name, node.name, "return_self_other", alias,
                        )
                        hits.append((
                            "K5", self.path, node.lineno, kind,
                            snip(f"{cls_name}.{node.name} -> self.{alias}"),
                        ))
                return

            # 1) pure return self.OTHER(...) method alias (non-Store modules)
            if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
                call = body[0].value
                alias = _is_self_method_alias(call)
                if alias:
                    kind, _basis = _forward_kind_for(
                        self.path, cls_name, node.name, "return_self_other", alias,
                    )
                    hits.append((
                        "K5", self.path, node.lineno, kind,
                        snip(f"{cls_name}.{node.name} -> self.{alias}"),
                    ))
                    return
                # return XxxStore(...).meth(...)
                if _is_store_ctor_call(call):
                    target = ast.unparse(call)[:160]
                    kind, _basis = _forward_kind_for(
                        self.path, cls_name, node.name, "return_store", target,
                    )
                    hits.append((
                        "K5", self.path, node.lineno, kind,
                        snip(f"{cls_name}.{node.name} -> {target}"),
                    ))
                    return
            # 2) Store ctor op(s) + optional commit only (GameDB / non-entity facades)
            ops = 0
            commits = 0
            other = 0
            targets: list[str] = []
            for st in body:
                if isinstance(st, ast.Return):
                    if st.value is None:
                        continue
                    if isinstance(st.value, ast.Call) and (
                        _is_store_ctor_call(st.value) or _is_commit_call(st.value)
                    ):
                        if _is_commit_call(st.value):
                            commits += 1
                        else:
                            ops += 1
                            targets.append(ast.unparse(st.value)[:80])
                        continue
                    if isinstance(st.value, ast.Name):
                        continue
                    other += 1
                    continue
                if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
                    if _is_commit_call(st.value):
                        commits += 1
                    elif _is_store_ctor_call(st.value):
                        ops += 1
                        targets.append(ast.unparse(st.value)[:80])
                    else:
                        other += 1
                elif isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and _is_store_ctor_call(st.value):
                    ops += 1
                    targets.append(ast.unparse(st.value)[:80])
                elif isinstance(st, ast.Pass):
                    continue
                else:
                    other += 1
            if ops >= 1 and other == 0 and len(body) <= 4:
                if self.path.endswith("ming_sim/db.py") or cls_name == "GameDB" or (
                    "/entities/" not in self.path and "Store(" in "|".join(targets)
                ):
                    kind, _basis = _forward_kind_for(
                        self.path, cls_name, node.name, "store_commit", "|".join(targets),
                    )
                    hits.append((
                        "K5", self.path, node.lineno, kind,
                        snip(
                            f"{cls_name}.{node.name} thin Store forward ops={ops} "
                            f"commits={commits} :: {' | '.join(targets)}"
                        ),
                    ))
    for rpath in prod_files:
        path = ROOT / rpath
        if not path.exists():
            continue
        tree = parse_py(path)
        if tree is None:
            continue
        Visitor(rpath).visit(tree)

    # Group SQL globally (cross-file)
    by_sig: dict[str, list[tuple[str, int, str, str]]] = defaultdict(list)
    for sig, path, line, func, sql in sql_items:
        by_sig[sig].append((path, line, func, sql))

    for sig, items in by_sig.items():
        if len(items) < 2:
            continue
        kind_tag, basis_seed = _k5_sql_group_basis(sig, items)
        for path, line, func, sql in items:
            hits.append((
                "K5", path, line, kind_tag,
                snip(f"{func} :: {sql} || BASIS:{basis_seed}"),
            ))

    # Static orphan Store methods that look like replaced/compat leftovers.
    # Exclude live 遗产 domain (legacy_modifiers / insert_legacy / apply_legacy_pct).
    orphan_name_pat = re.compile(
        r"^(?:read_|write_|_)?(?:compat_|deprecated_|old_|bare_|agno_|"
        r"scale_tian|ack_due_commitment|get_secret_order|close_from_declaration|"
        r"decode_agno|merge_runs|rewrite_session|_decode_agno|_agno_legacy)",
        re.I,
    )
    live_legacy_domain = re.compile(
        r"(?:legacy_modifiers|insert_legacy|expire_legacies|apply_legacy_pct|"
        r"write_insert_legacy|read_legacy_modifiers|legacy_remaining)",
        re.I,
    )
    for name, locs in store_defs.items():
        if live_legacy_domain.search(name):
            continue
        if not orphan_name_pat.search(name):
            continue
        if attr_refs.get(name, 0) <= len(locs):
            for path, line, cls_name in locs:
                hits.append((
                    "K5", path, line, "orphan_method_candidate",
                    snip(
                        f"{cls_name}.{name} static orphan candidate "
                        f"(no external attr ref; retirement-review)"
                    ),
                ))
                if re.search(r"compat|agno|bare|old_|deprecated|decode_agno|merge_runs", name, re.I):
                    hits.append((
                        "K1", path, line, "orphan_compat_method",
                        snip(f"{cls_name}.{name} orphan compat/storage-legacy method candidate"),
                    ))
    return hits


# ── K3: full-repo test text assertions (Python AST + TS regex) ──────────────

_HAN = re.compile(r"[\u4e00-\u9fff]")
_MACHINEY = re.compile(
    r"^(?:[a-z_][a-z0-9_]*:|[A-Z][A-Z0-9_]+$|status|code|message|provider_message|"
    r"source_id|origin_ref|event_id|turn|year|period|\d+$|"
    r"SUMMON_FRESH|AGENDA_FROZEN|draft|pending|active|closed|excluded|open)",
    re.I,
)

_TS_EXPECT = re.compile(
    r"""expect\s*\((?P<sub>[^;]{0,200}?)\)\s*\.\s*(?:not\s*\.\s*)?(?P<asserter>to(?:Contain|Match|Equal|Be|HaveTextContent|StrictEqual|MatchObject))\s*\(\s*(?P<arg>(['"`]).*?\4|/[^\n]+?/|true|false|null|\d+)""",
    re.S,
)
_TS_STRING = re.compile(r"""(['"`])(?P<body>(?:\\.|(?!\1).)*)\1""")


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


def _prose_lit(s: str) -> bool:
    s = s.strip()
    if not s or len(s) < 2:
        return False
    if _MACHINEY.match(s):
        return False
    if _HAN.search(s):
        return True
    if s in ("Internal Server Error",) or "Server Error" in s:
        return True
    # English diagnostic / title-ish free text (≥2 words, spaces, not identifiers)
    if " " in s and len(s) >= 8 and not re.match(r"^[a-z_./:-]+$", s):
        return True
    return False


def k3_ast_hits() -> list[tuple[str, str, int, str, str]]:
    hits: list[tuple[str, str, int, str, str]] = []
    test_files: list[str] = []
    for p in git_ls():
        if is_test_py(p) or is_test_ts(p):
            test_files.append(p)
    # walk fallback for untracked local tests (still full-repo intent)
    for path in iter_files(".py", ".ts", ".tsx"):
        r = rel(path)
        if (is_test_py(r) or is_test_ts(r)) and r not in test_files:
            test_files.append(r)

    seen_py: set[str] = set()
    for rpath in test_files:
        path = ROOT / rpath
        if not path.exists():
            continue
        if path.suffix == ".py":
            if rpath in seen_py:
                continue
            seen_py.add(rpath)
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = parse_py(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                # Assert / Compare
                if isinstance(node, (ast.Assert, ast.Compare)):
                    text = ast.get_source_segment(src, node) or ""
                    lits = [
                        _lit(child)
                        for child in ast.walk(node)
                        if isinstance(child, (ast.Constant, ast.JoinedStr)) and _lit(child)
                    ]
                    prose = any(_prose_lit(s) for s in lits)
                    if "not in" in text and any(len(s) >= 4 for s in lits):
                        if any(not _MACHINEY.match(s.strip()) for s in lits if s.strip()):
                            prose = True
                    if not prose:
                        continue
                    kind = "noncontract_assert"
                    if "match" in text and ("raises" in text or "pytest" in text or "Error" in text):
                        kind = "match_assert"
                    if any(x in text for x in ("title", "标题", "headline")):
                        kind = "title_assert"
                    hits.append((
                        "K3", rpath, getattr(node, "lineno", 0), kind,
                        snip(text or "|".join(lits)),
                    ))
                # pytest.raises(..., match=...)
                if isinstance(node, ast.Call):
                    call_src = ast.get_source_segment(src, node) or ""
                    if "match=" not in call_src and "match =" not in call_src:
                        continue
                    lits = [
                        _lit(child)
                        for child in ast.walk(node)
                        if isinstance(child, (ast.Constant, ast.JoinedStr)) and _lit(child)
                    ]
                    if not any(_prose_lit(s) or _HAN.search(s) for s in lits):
                        continue
                    hits.append((
                        "K3", rpath, getattr(node, "lineno", 0), "match_assert",
                        snip(call_src or "|".join(lits)),
                    ))
        elif path.suffix in (".ts", ".tsx"):
            src = path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(src.splitlines(), 1):
                if "expect(" not in line and "toContain" not in line and "toHaveTextContent" not in line:
                    # multi-line expect — still catch prose string literals near expect
                    if not (_HAN.search(line) and ("expect" in line or "to" in line)):
                        continue
                # extract string literals on the line
                lits = [m.group("body") for m in _TS_STRING.finditer(line)]
                prose_lits = [s for s in lits if _prose_lit(s.replace("\\n", " "))]
                if not prose_lits and "Internal Server Error" not in line:
                    # machine-id expects still recorded when Chinese absent but free English diagnostic
                    if re.search(r"not\.to(?:Contain|Match|Equal|Be)", line) and lits:
                        if any(not _MACHINEY.match(s.strip()) and len(s) >= 4 for s in lits):
                            prose_lits = lits
                    else:
                        continue
                kind = "ts_expect"
                if "not." in line or ".not." in line:
                    kind = "ts_negative_expect"
                if any(x in line for x in ("title", "标题", "heading", "label")):
                    kind = "ts_title_label"
                hits.append((
                    "K3", rpath, i, kind,
                    snip(line if line.strip() else "|".join(prose_lits)),
                ))
    return hits


# ── K1 AST extras (accept-both, blob helpers, orphan compat defs) ───────────

def k1_ast_hits() -> list[tuple[str, str, int, str, str]]:
    hits: list[tuple[str, str, int, str, str]] = []
    paths = [
        p for p in git_ls("*.py")
        if is_production_py(p) or is_test_py(p)
    ]
    for rel_path in paths:
        path = ROOT / rel_path
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src.splitlines(), 1):
            if re.search(r"secret_order(?:_brief)?:?\(?\\d", line) and "secret_order:" in line and "brief" in line:
                if re.search(r"secret_order:(?!brief)|secret_order(?:_brief)?\|", line):
                    hits.append(("K1", rel_path, i, "accept_both_regex", snip(line)))
            if re.search(r"def\s+(_decode_agno_runs|_rewrite_session|merge_runs_table|_agno_legacy)", line):
                hits.append(("K1", rel_path, i, "legacy_blob_api", snip(line)))
            if re.search(
                r"def\s+\w*(?:legacy_decode|legacy_merge|compat_load|fallback_decode|old_blob)\w*",
                line, re.I,
            ):
                hits.append(("K1", rel_path, i, "compat_def_candidate", snip(line)))
    return hits


# ── disposition ─────────────────────────────────────────────────────────────

STRUCT_K3_KEEP = (
    "status", "code", "message", "provider_message", "source_id", "origin_ref",
    "pytest.raises", "match=", "ValueError", "KeyError", "SystemExit",
    "ApiRequestError", "detail.code", "detail.message",
)


def _basis_from_text_marker(text: str) -> str | None:
    if "|| BASIS:" in text:
        return text.split("|| BASIS:", 1)[1].strip()
    return None


def dispose(cls: str, path: str, line: int, kind: str, text: str) -> tuple[str, str]:
    """Return (disposition, basis). Every branch returns an explicit semantic basis."""
    if "|baseline_gone" in kind:
        return "DELETE_DONE", f"pre-fix member at 6b513b99f removed; class={cls} kind={kind.split('|')[0]}"
    if "|baseline_still" in kind:
        return "DELETE", f"pre-fix member still present at HEAD; must remove; kind={kind.split('|')[0]}"

    # evidence / docs / enumerator scripts: residual documentation — not live production
    if (
        path.startswith("evidence/")
        or path.startswith("docs/")
        or path.endswith("1889-seven-class-enumerate.py")
        or path.endswith("1889_six_class_enumerate.py")
        or ("1889" in path and path.endswith("enumerate.py"))
    ):
        if "enumerate" in Path(path).name:
            return "NON_MEMBER", "enumerator predicate source, not production member"
        if "KEEP_P4_ABSENCE" in text and cls == "K3":
            return "DELETE_REVOKED_K3", "error KEEP_P4_ABSENCE label; free diagnostic prose is not contract"
        if cls in ("K1", "K3", "K4", "K5", "K7", "K8", "K9") and (
            "DELETE" in text or "revoked" in text.lower() or "scale_tian_fu" in text
            or "Internal Server Error" in text or "legacy" in text.lower()
            or "close_from_declaration" in text or "callable(_commit)" in text
            or "forward_shell" in text or "BASIS:" in text
        ):
            return "NON_MEMBER", "evidence/docs residual mention of disposed member; not live production"
        return "NON_MEMBER", "evidence/docs wide-scan hit; not live production member"

    # scripts: production-adjacent probes — members only when they host retired APIs
    if path.startswith("scripts/"):
        if "enumerate" in Path(path).name:
            return "NON_MEMBER", "scripts enumerator predicate source, not production member"
        if cls == "K5" and kind.startswith("dup_sql"):
            return "KEEP", _basis_from_text_marker(text) or (
                "scripts gate/fixture SQL — not production Store dual authority"
            )
        # Retired API symbols inside gate probes that still *call* them live
        if cls in ("K4", "K1", "K7", "K9") and any(
            x in text for x in ("scale_tian_fu", "_decode_agno", "close_from_declaration", "default_terminal_reason")
        ) and "re.compile" not in text and "r\"" not in text and "r'" not in text:
            return "DELETE", "scripts still calling retired mechanism — clear with production residual"
        return "NON_MEMBER", "scripts wide-scan without retired live mechanism residual"

    if cls == "K4":
        if any(x in text for x in ("scale_tian_fu", "read_scale_tian_fu")):
            return "DELETE", "retired tax_per_turn scalar path API"
        if "tax_per_turn" in text and any(x in text for x in ("辽饷", "盐税", "商税", "田赋")):
            return "DELETE", "retired residual scalar write chain"
        if "apply_dynamic_fiscal_scale" in text or ("辽饷" in text and "test_section" in path):
            return "KEEP", "live dynamic fiscal bypass / good-path case, not residual scalar API"
        if path.startswith("tests/") and "section_fiscal" in path:
            return "KEEP", "live 辽饷/盐税/商税 rejection good-path; scalar API already gone"
        return "NON_MEMBER", "wide fiscal mention without retired scalar API residual"

    if cls == "K1":
        if kind in ("legacy_blob_api",) or any(
            x in text for x in ("_decode_agno_runs", "merge_runs_table", "_agno_legacy", "_rewrite_session")
        ):
            return "DELETE", "app-side Agno2 sessions.runs blob compat"
        if kind == "orphan_compat_method":
            return "DELETE", "orphan Store compat/legacy method with no external refs — superseded mechanism"
        if kind == "compat_def_candidate":
            if path.startswith("tests/"):
                return "KEEP", "test names historical compat seam for negative/restore fidelity"
            return "DELETE", "production compat/legacy def candidate — superseded storage path"
        if "secret_order:(?!brief)" in text or (
            "secret_order:" in text and "brief" in text and "compile" in text.lower()
        ):
            if "_SECRET_ORDER_SOURCE" in text and "brief" in text and "secret_order:(" not in text.replace(
                "secret_order_brief", ""
            ):
                return "KEEP", "live private brief source regex only"
            if re.search(
                r"secret_order:(?!brief)|secret_order\|secret_order_brief|secret_order_brief\|secret_order",
                text,
            ):
                return "DELETE", "accept-both bare/brief source regex"
        if path.startswith("tests/") and "secret_order:" in text:
            return "KEEP", "secrecy negative / input fidelity / disclosure fixture machine id"
        # Live domain: 遗产 modifiers, alias→loyalty fold, agno_runs pin, brief source
        if any(
            x in text
            for x in (
                "secret_order_brief:",
                "SECRET_ORDER_ORIGIN_PREFIX",
                "_issued_secret_order",
                "密令",
                "secrecy",
                "disclosure",
                "origin_ref",
                "create_agno_db",
                "agno_runs",
                "legacy_modifiers",
                "apply_legacy_pct",
                "insert_legacy",
                "fold_loyalty_alias",
                "aliases",
            )
        ):
            return "KEEP", "live brief/origin_ref/secrecy/agno_runs/遗产·alias domain — not superseded storage compat"
        if "fallback" in text.lower() and path.startswith("ming_sim/"):
            # vocabulary/office fallback is live domain inference, not storage compat
            if any(x in text for x in ("office", "vocabulary", "infer", "portrait", "grant_action", "account")):
                return "KEEP", "live domain fallback (office/vocab/account) — not retired storage compat"
            return "NON_MEMBER", "fallback wording without retired storage-compat mechanism"
        if "compat" in text.lower() or "deprecated" in text.lower():
            if path.startswith("ming_sim/") and any(
                x in text.lower() for x in ("sessions.runs", "blob", "bare source", "旧测试", "accept")
            ):
                return "DELETE", "app-side old storage compat residual"
            return "NON_MEMBER", "compat/deprecated mention without superseded storage mechanism"
        if path.startswith("ming_sim/") and "secret_order:" in text and "brief" not in text:
            if text.strip().startswith("#"):
                return "KEEP", "comment contrasting live disclosure vs bare prefix"
            return "DELETE", "production bare secret_order: compat residual"
        return "NON_MEMBER", "wide compat mention without live superseded mechanism"

    if cls == "K5":
        basis_seed = _basis_from_text_marker(text)
        if kind.startswith("forward_shell|gamedb_resurrected") or (
            "append_chat_message" in text or "clear_month_open_snapshot" in text
        ) and path.endswith("ming_sim/db.py") and "def " in text:
            return "DELETE", "resurrected GameDB Store+commit shell; callers use Store+conn.commit"
        if kind.startswith("forward_shell|store_replaced"):
            return "DELETE", "replaced Store entry / pure forward shell; consumers must use true source"
        if kind.startswith("forward_shell|gamedb_internal_alias"):
            return (
                "NON_MEMBER",
                "GameDB internal method alias — not Store dual-authority forward shell",
            )
        if kind.startswith("forward_shell|gamedb_facade_pending"):
            return (
                "KEEP",
                "GameDB thin Store forward — 票面待接领域职责/现役调用入口; not superseded orphan shell "
                "(contrast deleted append_chat_message/read_ack_* shells)",
            )
        if kind.startswith("forward_shell|store_self_alias"):
            # Only delete when clearly a replaced read_* alias; else pending review NON_MEMBER/KEEP
            if any(x in text for x in ("read_ack_due", "read_get_secret_order", "-> self.row", "-> self.secret_order_row")):
                return "DELETE", "Store-internal replaced forward alias to true source"
            return (
                "KEEP",
                "Store self-alias retained when it is the named authority method, not a superseded duplicate entry",
            )
        if kind.startswith("forward_shell|module_store_forward"):
            return (
                "KEEP",
                "module-level Store one-liner — domain helper pending ownership review; not proven replaced entry",
            )
        if kind.startswith("forward_shell|non_persist_alias"):
            return (
                "NON_MEMBER",
                "non-persistence method alias (async/queue/wrapper) — not Store dual-authority shell",
            )
        if kind.startswith("forward_shell"):
            return "DELETE", "replaced entry / pure forward shell; consumers must use true source"
        if kind.startswith("dup_sql"):
            # Per-group basis was attached at scan time — use it; never silent KEEP.
            if basis_seed:
                if "cross_authority_candidate" in kind:
                    # Cross-file domain rule without lifecycle excuse → DELETE only if
                    # one side is a superseded facade; else KEEP with explicit review basis.
                    if any(x in text.lower() for x in ("scale_tian", "legacy_blob", "sessions.runs")):
                        return "DELETE", basis_seed + " — retired path residual"
                    return "KEEP", basis_seed + " — retained pending Store ownership consolidation (not auto-merge)"
                if "single_delete_rule" in kind:
                    return "KEEP", basis_seed + " — single helper shared by save/clear (judge: do not dual-delete)"
                if any(
                    tag in kind
                    for tag in (
                        "lifecycle_", "shared_rule", "field_selection", "selection_variant",
                        "list_vs_snapshot", "terminal_state", "schema_probe", "existence_probe",
                        "script_fixture",
                    )
                ):
                    return "KEEP", basis_seed
                if "shape_dup_review" in kind or "lifecycle_table_hint" in kind:
                    return "KEEP", basis_seed + " — sibling review: distinct verbs/status/selection"
                return "KEEP", basis_seed
            return "NON_MEMBER", "dup_sql hit missing group basis — enumerator bug, not silent KEEP"
        if kind == "orphan_method_candidate":
            # Orphans that are migrated read_/write_ seams still used via string/getattr
            # or pending wiring — KEEP as 待接; only retired-named ones DELETE via K1 path.
            if re.search(r"scale_tian|ack_due_commitment|get_secret_order|close_from_declaration", text):
                return "DELETE", "orphan method named for retired/replaced entry"
            return (
                "KEEP",
                "static orphan Store method candidate — 待接领域职责 or getattr/string call; not proven dead dual rule",
            )
        return "NON_MEMBER", "K5 wide hit without duplicate-rule or forward-shell shape"

    if cls == "K8":
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
        if "excluded_" in text and (
            path.startswith("ming_sim/") or path.startswith("tests/") or path == "web_app.py"
        ):
            return "NON_MEMBER", "live exclusion field / fixture use; not lenient wash residual"
        if kind == "excluded_decode" and "except" in text:
            return "NON_MEMBER", "generic except near scan; not excluded_* lenient wash"
        return "NON_MEMBER", "excluded_* mention without lenient wash residual"

    if cls == "K9":
        if "default_terminal_reason" in text:
            if path.startswith("ming_sim/content.py") or path.startswith("tests/"):
                return "DELETE", "unauthorized loader guard / dedicated proof"
            return "NON_MEMBER", "mention without live guard"
        if "callable(_commit)" in text or re.search(r"callable\(.*commit", text):
            return "DELETE", "unauthorized commit discrimination copy"
        if "append_chat_message" in text or "clear_month_open_snapshot" in text:
            if path.startswith("ming_sim/db.py") and "def " in text:
                return "DELETE", "resurrected GameDB Store forward shell (K5/K9); callers use Store+conn.commit"
            if path.startswith("tests/"):
                return "KEEP", "test double / docstring naming FakeDB insert crash hook; not production shell"
            return "NON_MEMBER", "historical mention; production shell absent"
        return "NON_MEMBER", "K9 wide hit without live unauthorized guard"

    if cls == "K3":
        if "KEEP_P4_ABSENCE" in text:
            return "DELETE_REVOKED_K3", "error retention label revoked; free diagnostic prose is not contract"
        if "Internal Server Error" in text and ("not in" in text or "not.to" in text or path.startswith("tests/")):
            if (path.startswith("tests/") or is_test_ts(path)) and (
                "not in" in text or "not.to" in text or "not.toContain" in text
            ):
                return "DELETE", "free diagnostic prose negative is not a contract (last-judge K3)"
            if path.startswith("evidence/"):
                return "DELETE_REVOKED_K3", "evidence residual of revoked KEEP_P4_ABSENCE / deleted prose lock"
            return "NON_MEMBER", "Internal Server Error mention without live negative prose lock"

        if kind in ("noncontract_assert", "match_assert", "title_assert", "ts_expect", "ts_negative_expect", "ts_title_label"):
            if "Internal Server Error" in text and ("not in" in text or "not.to" in text):
                return "DELETE", "free diagnostic prose negative is not a contract (last-judge K3)"
            # Structured HTTP/LLM error contract
            if any(x in text for x in ("status", "code", "provider_message", "detail.code", "detail.message", "ApiRequestError")) and (
                "detail" in text or "_assert_structured" in text or "response" in text or "error.detail" in text
            ):
                return "KEEP", "structured HTTP/LLM error contract (status/code/message/provider_message)"
            if any(x in text for x in ("source_id", "origin_ref")) and (
                "==" in text or "in " in text or "not in" in text or ".toBe" in text or ".toEqual" in text
            ):
                return "KEEP", "machine id / input fidelity secrecy boundary — not free diagnostic lock"
            if kind == "match_assert" or "match=" in text or "pytest.raises" in text:
                # Distinguish injected/machine vs free Chinese diagnostic lock
                if any(x in text for x in ("ValueError", "KeyError", "SystemExit", "SettlementAbort", "PayOrder")):
                    return "KEEP", "real gate / injected failure match — machine or test-injected exception type"
                if _HAN.search(text) and "not in" not in text:
                    return "KEEP", "raises match on production error identifier/machine wording — gate fidelity"
                return "KEEP", "match= assertion — machine or test-injected (not free diagnostic absence lock)"
            if any(x in text for x in ("兵籍在册", "任免簿", "AGENDA_FROZEN")):
                return "DELETE", "non-contract narrative/material-title lock"
            if kind in ("title_assert", "ts_title_label"):
                # Titles/labels: only DELETE when free narrative lock; KEEP chrome enums/machine
                if _HAN.search(text) and any(x in text for x in ("toContain", "in ", "not in", "toHaveTextContent")):
                    return (
                        "NON_MEMBER",
                        "title/label assert candidate — not last-judge free-diagnostic member; no batch KEEP",
                    )
                return "NON_MEMBER", "title/label chrome assert without free-diagnostic membership"
            if kind in ("ts_negative_expect",) and _prose_lit(
                text.strip().strip("'\"")
            ):
                return (
                    "NON_MEMBER",
                    "TS negative expect prose-shaped — not proven free-diagnostic ISE-class lock; no batch KEEP",
                )
            return (
                "NON_MEMBER",
                "prose-shaped assert wide-scan candidate; not last-judge free-diagnostic member — no batch KEEP",
            )
        if "assert" in text.lower() and "not in" in text and path.startswith("tests/"):
            if any(x in text for x in STRUCT_K3_KEEP):
                return "KEEP", "structured/machine negative"
            return "NON_MEMBER", "negative membership wide-scan; not proven free-diagnostic lock"
        return "NON_MEMBER", "K3 wide hit without non-contract diagnostic lock membership"

    if cls == "K7":
        if "Close only by explicit declaration" in text:
            return "DELETE", "withdrawn explicit-close contract wording"
        if "close_from_declaration" in text or "declare_closed" in text or "ATTACH_RESULT_CLOSE" in text:
            if path.startswith("ming_sim/") or path.startswith("tests/"):
                return "DELETE", "withdrawn explicit close mechanism / dedicated gate test"
            return "NON_MEMBER", "historical mention"
        return "NON_MEMBER", "affair-close wide hit without withdrawn mechanism residual"

    return "NON_MEMBER", "unclassified wide-scan candidate"


def baseline_deleted_members() -> list[tuple[str, str, int, str, str]]:
    """Enumerate last-judge members present at 6b513b99f that are gone at HEAD."""
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
        ("K8", "ming_sim/db.py",
         r"excluded_names\s*=\s*\[\]|excluded_targets\s*=\s*\{\}", "lenient_wash"),
        ("K9", "ming_sim/content.py", r"default_terminal_reason", "unauthorized_guard"),
        ("K9", "ming_sim/month_open_snapshot.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K9", "ming_sim/month_chain.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K9", "web_app.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K9", "ming_sim/cli/terminal.py", r"callable\(_commit\)\s+and\s+not\s+callable\(_conn\)", "commit_discrim"),
        ("K3", "tests/test_chat_stream_failpaths_393.py",
         r"Internal Server Error.*not in|not in.*Internal Server Error", "prose_lock"),
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

    member_disps = {"DELETE", "DELETE_DONE", "DELETE_REVOKED_K3", "KEEP"}
    with enum_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["class", "path", "line", "kind", "text"])
        for cls, path, line, kind, disp, basis, text in dispositions:
            if disp in member_disps:
                w.writerow([cls, path, line, kind, text])

    c_raw = Counter(r[0] for r in rows)
    c_disp = Counter(d[4] for d in dispositions)
    c_mem = Counter(d[0] for d in dispositions if d[4] in member_disps)
    print("OUT_RAW", raw_path)
    print("OUT_ENUM", enum_path)
    print("OUT_DISP", disp_path)
    print("RAW_TOTAL", len(rows))
    for k in ("K4", "K1", "K5", "K8", "K9", "K3", "K7"):
        print(f"RAW_{k}", c_raw[k])
    print("DISP", dict(c_disp))
    print("MEMBER_BY_CLASS", dict(c_mem))

    # KEEP basis uniqueness check (no single default basis dominating)
    keep_bases = Counter(d[5] for d in dispositions if d[4] == "KEEP")
    print("KEEP_BASIS_DISTINCT", len(keep_bases))
    print("KEEP_BASIS_TOP5", keep_bases.most_common(5))

    live_delete = [
        d for d in dispositions
        if d[4] == "DELETE" and (d[1].startswith("ming_sim/") or d[1] == "web_app.py" or d[1].startswith("scripts/"))
    ]
    print("LIVE_PROD_DELETE_RESIDUAL", len(live_delete))
    for d in live_delete[:60]:
        print(f"  {d[0]}\t{d[1]}:{d[2]}\t{d[3]}\t{d[4]}\t{d[6][:100]}")

    # Coverage sanity: SQL from non-entities production files
    k5_paths = {d[1] for d in dispositions if d[0] == "K5"}
    non_entity_sql = sorted(
        p for p in k5_paths
        if is_production_py(p) and "/entities/" not in p
    )
    print("K5_NONEENTITY_PROD_PATHS", len(non_entity_sql))
    for p in non_entity_sql[:30]:
        print(f"  {p}")

    k3_ts = sum(1 for d in dispositions if d[0] == "K3" and d[1].endswith((".ts", ".tsx")))
    print("K3_TS_HITS", k3_ts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
