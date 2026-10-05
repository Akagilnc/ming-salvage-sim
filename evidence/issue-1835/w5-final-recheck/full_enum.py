#!/usr/bin/env python3
"""Full-repo semantic enumeration for #1835 G1–G5 (final recheck). Not a test.

Fixes vs prior enum:
- G4 consumer_closure counts same-file ast.Name / ast.Attribute uses
  (definition line skipped; not path-filtered as external-only).
- G2 attaches try-body summary + source_hint for each broad wash/decl catch.
- G3 lists ALL identical_body groups (not path-filtered to entities/).
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5")
PROD = ROOT / "ming_sim"
TESTS = ROOT / "tests"
DOCS = ROOT / "docs"
OUT_DIR = Path("/tmp/1835-w5-final/enum")


def tracked_py(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None


def qual_funcs(tree: ast.AST):
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((f"{node.name}.{n.name}", n))
    return out


def except_types(handler: ast.ExceptHandler):
    if handler.type is None:
        return ["bare"]
    if isinstance(handler.type, ast.Tuple):
        return [ast.unparse(e) for e in handler.type.elts]
    return [ast.unparse(handler.type)]


def enclosing_func(tree: ast.AST, lineno: int):
    best = None
    for qname, fn in qual_funcs(tree):
        end = fn.end_lineno or fn.lineno
        if fn.lineno <= lineno <= end:
            if best is None or fn.lineno >= best[1].lineno:
                best = (qname, fn)
    return best


def try_for_handler(tree: ast.AST, handler: ast.ExceptHandler):
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and handler in node.handlers:
            return node
    return None


def summarize_try(try_node: ast.Try | None, max_chars: int = 280) -> str:
    if try_node is None:
        return ""
    try:
        src = ast.unparse(try_node)
    except Exception:
        return ""
    src = re.sub(r"\s+", " ", src).strip()
    return src[:max_chars]


def source_hint(try_src: str, handler_src: str, file_rel: str, symbol: str) -> str:
    """Heuristic for disposition — fixer still reads try bodies; this is enum aid."""
    blob = f"{try_src}\n{handler_src}\n{file_rel}\n{symbol}"
    persist_prims = re.compile(
        r"\b(execute|executemany|fetchone|fetchall|fetchmany|commit|rollback|"
        r"parse_engine_payload_json|payload_json|json\.loads|"
        r"get_|load_|read_|fetch_|select_|UPDATE |INSERT |DELETE |"
        r"set_fiscal|create_|adjust_|apply_.*_deltas|"
        r"conn\.|cursor\.|self\._conn|self\.conn)\b",
        re.I,
    )
    decl_field = re.compile(
        r"\b(int\(|float\(|str\(|bool\(|item\.get|raw\.get|payload\.get|"
        r"candidate\.get|stages|DeclarationDataError|require_|_parse_|"
        r"stage_|_coerce_|invalid_shape|invalid_enum)\b"
    )
    washes = bool(
        re.search(r"_reject|RejectedItem|invalid_shape|DeclarationDataError", handler_src)
    )
    if not washes and "json.loads" not in try_src and "parse_engine" not in try_src:
        if "in_decl_path" in blob:
            pass
    has_persist = bool(persist_prims.search(try_src))
    has_decl = bool(decl_field.search(try_src))
    if washes and has_persist and not has_decl:
        return "wash_persist_or_impl"
    if washes and has_persist and has_decl:
        return "mixed_decl_and_persist_try"
    if washes and has_decl and not has_persist:
        return "wash_decl_field_only"
    if washes:
        return "wash_needs_manual_read"
    if has_persist:
        return "broad_on_persist_no_reject_wash"
    if has_decl:
        return "broad_on_decl_field"
    return "broad_other"


# ── G1 ───────────────────────────────────────────────────────────────────
G1_SEMANTIC = re.compile(
    r"assess_foundation_tier|FOUNDATION_(HALFWAY|ROOTED|JUST_STARTED)|"
    r"record_dossier_execution|execution_outcome\s*=|"
    r"_apply_halfway_national_setback|HALFWAY_SETBACK|_HALFWAY_METRICS|"
    r"cancel_issue|stop_origin_commitment|finalize_persist|"
    r"breach_decree_dossier|apply_persist_revoke"
)


def enum_g1():
    members = []
    for path in tracked_py(PROD):
        tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for qname, node in qual_funcs(tree):
            try:
                src = ast.unparse(node)
            except Exception:
                src = ""
            if not (G1_SEMANTIC.search(src) or G1_SEMANTIC.search(qname)):
                continue
            members.append({
                "file": rel,
                "symbol": qname,
                "lineno": node.lineno,
                "kind": "g1_shape",
            })
    return members


# ── G2 ───────────────────────────────────────────────────────────────────
DECL_PATH_HINTS = re.compile(
    r"declaration_dispatch|action_materialize|stage_.*candidate|"
    r"prepare_.*material|materialize|_pending_action|dispatch_declaration|"
    r"parse_engine_payload|payload_json|settle_delta|delta_section|"
    r"entities/.*/apply"
)
BROAD = {"ValueError", "TypeError", "Exception", "BaseException", "bare", "OSError", "OverflowError", "KeyError"}


def enum_g2():
    members = []
    for path in tracked_py(PROD):
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        tree = parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            types = except_types(node)
            broad = [t for t in types if t.split(".")[-1] in BROAD or t in BROAD]
            if not broad:
                continue
            enc = enclosing_func(tree, node.lineno)
            enclosing = enc[0] if enc else f"<module>:{node.lineno}"
            try_node = try_for_handler(tree, node)
            try:
                handler_body = ast.unparse(node)
            except Exception:
                handler_body = ""
            try_src = summarize_try(try_node)
            washes_reject = bool(
                re.search(r"_reject|RejectedItem|invalid_shape|DeclarationDataError", handler_body)
            )
            jsonish = "json.loads" in (try_src + handler_body) or "parse_engine" in (try_src + handler_body)
            in_decl_path = bool(
                DECL_PATH_HINTS.search(rel) or DECL_PATH_HINTS.search(enclosing or "")
            )
            # Class membership: wash→reject OR decl/settle path broad OR json persist decode
            # NOT path-excluded by army/region — those stay if wash or on settle path.
            if washes_reject or jsonish or in_decl_path:
                hint = source_hint(try_src, handler_body, rel, enclosing)
                members.append({
                    "file": rel,
                    "symbol": enclosing,
                    "lineno": node.lineno,
                    "types": types,
                    "washes_reject": washes_reject,
                    "jsonish": jsonish,
                    "in_decl_path": in_decl_path,
                    "kind": "broad_except",
                    "try_summary": try_src,
                    "handler_summary": re.sub(r"\s+", " ", handler_body).strip()[:200],
                    "source_hint": hint,
                })
        for i, line in enumerate(text.splitlines(), 1):
            if "json.loads" in line:
                members.append({
                    "file": rel,
                    "symbol": f"json.loads@{i}",
                    "lineno": i,
                    "kind": "json_loads",
                    "line": line.strip()[:160],
                })
    return members


# ── G3 ───────────────────────────────────────────────────────────────────
def body_hash(node: ast.AST) -> str | None:
    class Norm(ast.NodeTransformer):
        def visit_FunctionDef(self, n):
            n = self.generic_visit(n)
            if (
                n.body
                and isinstance(n.body[0], ast.Expr)
                and isinstance(getattr(n.body[0], "value", None), ast.Constant)
                and isinstance(n.body[0].value.value, str)
            ):
                n.body = n.body[1:] or [ast.Pass()]
            n.name = "F"
            n.decorator_list = []
            n.returns = None
            for a in n.args.args:
                a.annotation = None
            return n

        def visit_AsyncFunctionDef(self, n):
            return self.visit_FunctionDef(n)  # type: ignore

    try:
        cloned = Norm().visit(ast.parse(ast.unparse(node)))
        dump = ast.dump(cloned, annotate_fields=False)
        return hashlib.sha256(dump.encode()).hexdigest()[:16]
    except Exception:
        return None


G3_POLICY_NAMES = re.compile(
    r"allegiance|amnesty|identity_title|pending_person|person_changes_block|"
    r"admission|preflight|require_origin|dossier_id|population_pool|_placed|_stored"
)


def enum_g3():
    members = []
    by_hash: dict[str, list] = defaultdict(list)
    for path in tracked_py(PROD):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        for qname, node in qual_funcs(tree):
            h = body_hash(node)
            if h is None:
                continue
            by_hash[h].append({"file": rel, "symbol": qname, "lineno": node.lineno})
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        if all(g["symbol"].endswith("__init__") for g in group):
            continue
        # skip trivial one-liner pass/return None noise only if body unparse tiny
        members.append({"kind": "identical_body", "hash": h, "group": group})

    for path in tracked_py(PROD):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        text = path.read_text(encoding="utf-8")
        for qname, node in qual_funcs(tree):
            try:
                src = ast.unparse(node)
            except Exception:
                src = ""
            if not (G3_POLICY_NAMES.search(qname) or G3_POLICY_NAMES.search(src)):
                continue
            if G3_POLICY_NAMES.search(qname) or (
                "allegiance_change_rejection" in src and qname != "allegiance_change_rejection"
            ):
                members.append({
                    "kind": "policy_shape",
                    "file": rel,
                    "symbol": qname,
                    "lineno": node.lineno,
                })
        for dead in (
            "_pending_person_changes_block_event_gate",
            "amnesty_conflict_power_ids",
            "identity_title_for_allegiance",
        ):
            if dead in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if dead in line:
                        members.append({
                            "kind": "named_residual",
                            "file": rel,
                            "symbol": dead,
                            "lineno": i,
                            "line": line.strip()[:160],
                        })
    return members


# ── G4: AST Name/Attr consumers INCLUDING same-file ─────────────────────
def ast_consumers(symbol: str):
    """Return production and test use sites via ast.Name / ast.Attribute.

    Same-file uses count. Definition `def symbol` / class method def skipped.
    Assignments that are field() defs counted separately.
    """
    prod_hits = []
    test_hits = []

    def scan(base: Path, bucket: list):
        for path in tracked_py(base):
            tree = parse(path)
            if tree is None:
                continue
            rel = str(path.relative_to(ROOT))
            # Collect def linenos for this symbol in this file
            def_lines = set()
            for qname, node in qual_funcs(tree):
                if qname.split(".")[-1] == symbol:
                    def_lines.add(node.lineno)
            for n in ast.walk(tree):
                hit = None
                if isinstance(n, ast.Name) and n.id == symbol:
                    hit = ("Name", n.lineno, getattr(n, "col_offset", 0))
                elif isinstance(n, ast.Attribute) and n.attr == symbol:
                    hit = ("Attr", n.lineno, getattr(n, "col_offset", 0))
                if hit is None:
                    continue
                kind, lineno, _ = hit
                if lineno in def_lines:
                    # only skip if this is the FunctionDef name itself
                    # FunctionDef.name is not an ast.Name child of the FunctionDef in walk
                    # for the def keyword — but annotated assign field defs may match.
                    # Skip FunctionDef/AsyncFunctionDef nodes' .name via lineno match
                    # when node is the function: walk yields Name only for uses.
                    # Actually FunctionDef.name is a str, not visited. So Name hits
                    # at def lineno are rare (decorators). Safe to keep Attr/Name
                    # unless the line is exactly `def symbol`.
                    line = path.read_text(encoding="utf-8").splitlines()[lineno - 1]
                    if re.search(rf"^\s*(async\s+)?def\s+{re.escape(symbol)}\b", line):
                        continue
                    if re.search(rf"^\s*{re.escape(symbol)}\s*[:=]", line) and "field(" in line:
                        bucket.append((rel, lineno, "field_def", line.strip()[:120]))
                        continue
                line = path.read_text(encoding="utf-8").splitlines()[lineno - 1]
                if line.lstrip().startswith("#"):
                    continue
                bucket.append((rel, lineno, kind, line.strip()[:120]))

    scan(PROD, prod_hits)
    scan(TESTS, test_hits)
    return prod_hits, test_hits


CANDIDATE_DEAD = [
    "_extract_secret_order",
    "_apply_authority_change_item",
    "_province_transport_ratio",
    "_province_collection_rate",
    "_fiscal_container_value",
    "_capture_one_interaction",
    "_target_active_officeholder",
    "target_progress_units",
    "current_audience_scene",
    "issue_applied_person_changes",
    "victory_status_of",
    "stamped_by_origin",
    "rejected_origin_ids",
    "_pending_person_changes_block_event_gate",
    "amnesty_conflict_power_ids",
    "_load_pending_gate_shadow_rows",
    "_load_pending_gate_power_shadow_rows",
    "pending_person_changes_for_gates",
]


def enum_g4():
    members = []
    def_index = []
    for path in tracked_py(PROD):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        for qname, node in qual_funcs(tree):
            simple = qname.split(".")[-1]
            if simple.startswith("__") and simple.endswith("__"):
                continue
            def_index.append((simple, qname, rel, node.lineno))

    focus = []
    for simple, qname, rel, lineno in def_index:
        if simple in CANDIDATE_DEAD or simple.startswith("_extract_") or (
            simple.startswith("_") and any(
                k in simple
                for k in (
                    "secret_order",
                    "authority_change",
                    "pending_gate",
                    "amnesty",
                    "person_changes_block",
                    "halfway",
                )
            )
        ):
            focus.append((simple, qname, rel, lineno))

    seen = set()
    for simple, qname, rel, lineno in focus:
        key = (simple, rel)
        if key in seen:
            continue
        seen.add(key)
        prod_hits, test_hits = ast_consumers(simple)
        # ALL production refs including same-file (not external-only)
        real_prod = [h for h in prod_hits if h[2] in {"Name", "Attr"}]
        same_file = [h for h in real_prod if h[0] == rel]
        other_file = [h for h in real_prod if h[0] != rel]
        if not real_prod and not test_hits:
            hint = "dead_no_consumer"
        elif not real_prod and test_hits:
            hint = "test_only"
        else:
            hint = "live"
        members.append({
            "kind": "consumer_closure",
            "symbol": simple,
            "defined": f"{rel}:{lineno}",
            "qual": qname,
            "prod_refs": len(real_prod),
            "same_file_refs": len(same_file),
            "other_file_refs": len(other_file),
            "test_refs": len(test_hits),
            "prod_sample": real_prod[:8],
            "same_file_sample": same_file[:8],
            "test_sample": test_hits[:5],
            "disposition_hint": hint,
        })

    run_path = PROD / "settlement" / "run.py"
    run_tree = parse(run_path)
    if run_tree:
        for node in run_tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "SettlementRun":
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        field = stmt.target.id
                        prod_hits, test_hits = ast_consumers(field)
                        reads = [h for h in prod_hits if h[2] in {"Name", "Attr"}]
                        # Exclude pure annotations on SettlementRun itself
                        reads = [
                            h
                            for h in reads
                            if not (
                                h[0] == "ming_sim/settlement/run.py"
                                and "field(" in h[3]
                            )
                        ]
                        if not reads:
                            members.append({
                                "kind": "unread_run_field",
                                "symbol": field,
                                "defined": f"ming_sim/settlement/run.py:{stmt.lineno}",
                                "test_refs": len(test_hits),
                                "disposition_hint": "unread_run_field",
                            })
    return members


# ── G5 ───────────────────────────────────────────────────────────────────
G5_CALLS = ("apply_event_terminal_states", "auto_trigger_seed_issues")


def _line_in_func(text: str, lineno: int, func: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return node.lineno <= lineno <= (node.end_lineno or node.lineno)
        if isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, ast.FunctionDef) and n.name == func:
                    return n.lineno <= lineno <= (n.end_lineno or n.lineno)
    return False


def enum_g5():
    members = []
    for path in list(tracked_py(PROD)) + list(DOCS.rglob("*.md")):
        if path.suffix not in {".py", ".md"}:
            continue
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        for sym in G5_CALLS:
            if sym not in text:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if sym in line:
                    members.append({
                        "file": rel,
                        "symbol": sym,
                        "lineno": i,
                        "line": line.strip()[:160],
                        "in_pre_settle": path.suffix == ".py"
                        and _line_in_func(text, i, "pre_settle"),
                    })
    return members


def main():
    report = {
        "G1": enum_g1(),
        "G2": enum_g2(),
        "G3": enum_g3(),
        "G4": enum_g4(),
        "G5": enum_g5(),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUT_DIR / "enum-post.json"
    out_txt = OUT_DIR / "enum-post.txt"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    for key, items in report.items():
        lines.append(f"== {key} count={len(items)} ==")
        if key == "G2":
            washes = [m for m in items if m.get("washes_reject")]
            decl = [
                m
                for m in items
                if m.get("in_decl_path") and m.get("kind") == "broad_except"
            ]
            loads = [m for m in items if m.get("kind") == "json_loads"]
            lines.append(f"  broad_except_washes_reject={len(washes)}")
            lines.append(f"  broad_except_in_decl_path={len(decl)}")
            lines.append(f"  json_loads={len(loads)}")
            by_hint = defaultdict(list)
            for m in washes:
                by_hint[m.get("source_hint", "?")].append(m)
            for hint, ms in sorted(by_hint.items()):
                lines.append(f"  -- source_hint={hint} n={len(ms)}")
            for m in washes:
                lines.append(
                    f"  WASH {m['file']}:{m['lineno']} {m['symbol']} "
                    f"types={m['types']} hint={m.get('source_hint')}"
                )
                lines.append(f"    TRY {m.get('try_summary', '')}")
                lines.append(f"    HDL {m.get('handler_summary', '')}")
            for m in decl:
                if m in washes:
                    continue
                lines.append(
                    f"  DECL {m['file']}:{m['lineno']} {m['symbol']} "
                    f"types={m['types']} hint={m.get('source_hint')}"
                )
                lines.append(f"    TRY {m.get('try_summary', '')}")
        elif key == "G3":
            idents = [m for m in items if m.get("kind") == "identical_body"]
            named = [m for m in items if m.get("kind") == "named_residual"]
            policy = [m for m in items if m.get("kind") == "policy_shape"]
            lines.append(f"  identical_body_groups={len(idents)}")
            lines.append(f"  named_residual={len(named)}")
            lines.append(f"  policy_shape={len(policy)}")
            for m in named:
                lines.append(
                    f"  NAMED {m['file']}:{m['lineno']} {m['symbol']} :: {m.get('line')}"
                )
            for m in policy:
                lines.append(f"  POLICY {m['file']}:{m['lineno']} {m['symbol']}")
            for m in idents:
                lines.append(
                    f"  IDENT {m['hash']} "
                    f"{[g['file'] + ':' + g['symbol'] for g in m['group']]}"
                )
        elif key == "G4":
            dead = [m for m in items if m.get("disposition_hint") == "dead_no_consumer"]
            test_only = [m for m in items if m.get("disposition_hint") == "test_only"]
            live = [m for m in items if m.get("disposition_hint") == "live"]
            unread = [m for m in items if m.get("kind") == "unread_run_field"]
            lines.append(
                f"  dead_no_consumer={len(dead)} test_only={len(test_only)} "
                f"live={len(live)} unread_run_field={len(unread)}"
            )
            for m in dead + test_only + unread:
                lines.append(
                    f"  {m.get('disposition_hint') or m['kind']} {m['symbol']} "
                    f"defined={m.get('defined')} prod={m.get('prod_refs')} "
                    f"same_file={m.get('same_file_refs')} other={m.get('other_file_refs')} "
                    f"test={m.get('test_refs')}"
                )
                for s in m.get("same_file_sample") or m.get("prod_sample") or []:
                    lines.append(f"    PROD {s}")
                for s in m.get("test_sample") or []:
                    lines.append(f"    TEST {s}")
            lines.append("  -- live (same-file or cross-file consumers) --")
            for m in live:
                lines.append(
                    f"  live {m['symbol']} defined={m.get('defined')} "
                    f"prod={m.get('prod_refs')} same_file={m.get('same_file_refs')} "
                    f"other={m.get('other_file_refs')} test={m.get('test_refs')}"
                )
                for s in (m.get("same_file_sample") or [])[:3]:
                    lines.append(f"    SAME {s}")
                for s in [h for h in (m.get("prod_sample") or []) if h[0] != m.get("defined", "").split(":")[0]][:3]:
                    lines.append(f"    OTHER {s}")
        elif key == "G5":
            in_pre = [m for m in items if m.get("in_pre_settle")]
            lines.append(f"  in_pre_settle={len(in_pre)}")
            for m in items:
                flag = "PRE" if m.get("in_pre_settle") else "ok"
                lines.append(
                    f"  [{flag}] {m['file']}:{m['lineno']} {m['symbol']} :: {m['line']}"
                )
        else:
            for m in items:
                lines.append(
                    f"  {m.get('file')}:{m.get('lineno')} {m.get('symbol')} {m.get('kind', '')}"
                )
        lines.append("")
    out_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(out_txt.read_text())


if __name__ == "__main__":
    main()
