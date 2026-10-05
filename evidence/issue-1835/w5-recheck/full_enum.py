#!/usr/bin/env python3
"""Full-repo semantic enumeration for #1835 G1–G5 (recheck). Not a test."""
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


def tracked_py(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
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


def name_hits(tree: ast.AST, names: set[str]):
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in names:
            hits.append(("Name", n.id, getattr(n, "lineno", None)))
        elif isinstance(n, ast.Attribute) and n.attr in names:
            hits.append(("Attr", n.attr, getattr(n, "lineno", None)))
    return hits


# ── G1: code substitutes model 撤诺 / world disposal ─────────────────────
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
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        for qname, node in qual_funcs(tree):
            try:
                src = ast.unparse(node)
            except Exception:
                src = ""
            if not (G1_SEMANTIC.search(src) or G1_SEMANTIC.search(qname)):
                continue
            # Class def: any production symbol matching 撤诺/世界处置 shapes
            members.append({
                "file": rel,
                "symbol": qname,
                "lineno": node.lineno,
                "kind": "g1_shape",
            })
    return members


# ── G2: persist/impl faults washed into declaration rejection ────────────
DECL_PATH_HINTS = re.compile(
    r"declaration_dispatch|action_materialize|stage_.*candidate|"
    r"prepare_.*material|materialize|_pending_action|dispatch_declaration|"
    r"parse_engine_payload|payload_json"
)
BROAD = {"ValueError", "TypeError", "Exception", "BaseException", "bare", "OSError"}


def enum_g2():
    members = []
    for path in tracked_py(PROD):
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        tree = parse(path)
        if tree is None:
            continue
        # Broad catches
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            types = except_types(node)
            broad = [t for t in types if t.split(".")[-1] in BROAD or t in BROAD]
            if not broad:
                continue
            # Classify by enclosing function
            # Find enclosing function via line scan of qual_funcs
            enclosing = None
            for qname, fn in qual_funcs(tree):
                if fn.lineno <= node.lineno <= (fn.end_lineno or fn.lineno):
                    enclosing = qname
            try:
                body = ast.unparse(node)
            except Exception:
                body = ""
            washes_reject = bool(
                re.search(r"_reject|RejectedItem|invalid_shape|DeclarationDataError", body)
            )
            jsonish = "json.loads" in body or "JSONDecodeError" in body or "parse_engine" in body
            in_decl_path = bool(DECL_PATH_HINTS.search(rel) or DECL_PATH_HINTS.search(enclosing or ""))
            if washes_reject or jsonish or in_decl_path or any(
                t.split(".")[-1] in {"ValueError", "TypeError", "Exception", "bare"} for t in broad
            ):
                members.append({
                    "file": rel,
                    "symbol": enclosing or f"<module>:{node.lineno}",
                    "lineno": node.lineno,
                    "types": types,
                    "washes_reject": washes_reject,
                    "jsonish": jsonish,
                    "in_decl_path": in_decl_path,
                    "kind": "broad_except",
                })
        # json.loads sites (persist / payload)
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


# ── G3: parallel domain admission / business rule authority ──────────────
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
    # 1) identical function bodies (duplicate authority candidates)
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
        # filter tiny stubs
        if all(g["symbol"].endswith("__init__") for g in group):
            continue
        members.append({"kind": "identical_body", "hash": h, "group": group})

    # 2) remaining parallel person-admission / title / pending shadows by name+shape
    for path in tracked_py(PROD):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        text = path.read_text(encoding="utf-8")
        for qname, node in qual_funcs(tree):
            if not G3_POLICY_NAMES.search(qname) and not G3_POLICY_NAMES.search(
                ast.unparse(node) if hasattr(ast, "unparse") else qname
            ):
                continue
            if G3_POLICY_NAMES.search(qname) or (
                "allegiance_change_rejection" in (ast.unparse(node) if hasattr(ast, "unparse") else "")
                and qname != "allegiance_change_rejection"
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


# ── G4: replaced mechanisms / exclusive old tests / no-consumer state ────
# Semantic: defs with zero production consumers; test-only production helpers;
# retired secret-order extractors; SettlementRun unread fields.
def consumer_closure(symbol: str):
    prod_hits = []
    test_hits = []
    for path in tracked_py(PROD):
        text = path.read_text(encoding="utf-8")
        if symbol in text:
            rel = str(path.relative_to(ROOT))
            for i, line in enumerate(text.splitlines(), 1):
                if symbol in line and not line.lstrip().startswith("#"):
                    # skip definition line itself loosely
                    if re.search(rf"\bdef\s+{re.escape(symbol)}\b", line):
                        continue
                    if re.search(rf"\b{re.escape(symbol)}\s*=", line) and "field(" in line:
                        prod_hits.append((rel, i, "field_def", line.strip()[:120]))
                        continue
                    prod_hits.append((rel, i, "ref", line.strip()[:120]))
    for path in tracked_py(TESTS):
        text = path.read_text(encoding="utf-8")
        if symbol in text:
            rel = str(path.relative_to(ROOT))
            for i, line in enumerate(text.splitlines(), 1):
                if symbol in line and not line.lstrip().startswith("#"):
                    test_hits.append((rel, i, line.strip()[:120]))
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
    # Scan ALL production function defs; flag those with zero name refs outside defining file
    def_index = []  # (symbol, file, lineno)
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

    # Focus: private helpers (_*) and named dead candidates + SettlementRun fields
    focus = []
    for simple, qname, rel, lineno in def_index:
        if simple in CANDIDATE_DEAD or simple.startswith("_extract_") or (
            simple.startswith("_") and any(k in simple for k in (
                "secret_order", "authority_change", "pending_gate", "amnesty",
                "person_changes_block", "halfway",
            ))
        ):
            focus.append((simple, qname, rel, lineno))

    seen = set()
    for simple, qname, rel, lineno in focus:
        key = (simple, rel)
        if key in seen:
            continue
        seen.add(key)
        prod_hits, test_hits = consumer_closure(simple)
        # filter self-file definition-only
        external_prod = [h for h in prod_hits if h[0] != rel]
        members.append({
            "kind": "consumer_closure",
            "symbol": simple,
            "defined": f"{rel}:{lineno}",
            "qual": qname,
            "external_prod_refs": len(external_prod),
            "test_refs": len(test_hits),
            "prod_sample": external_prod[:5],
            "test_sample": test_hits[:5],
            "disposition_hint": (
                "dead_no_consumer" if not external_prod and not test_hits else
                "test_only" if not external_prod and test_hits else
                "live"
            ),
        })

    # SettlementRun unread fields via AST
    run_path = PROD / "settlement" / "run.py"
    run_tree = parse(run_path)
    for node in run_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SettlementRun":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field = stmt.target.id
                    prod_hits, test_hits = consumer_closure(field)
                    # reads: attribute access SettlementRun or run.field outside field def
                    reads = [h for h in prod_hits if "field(" not in h[3] and f"{field}:" not in h[3]]
                    if not reads:
                        members.append({
                            "kind": "unread_run_field",
                            "symbol": field,
                            "defined": f"ming_sim/settlement/run.py:{stmt.lineno}",
                            "test_refs": len(test_hits),
                        })
    return members


# ── G5: resurrected pre-edict event consumption path ─────────────────────
G5_CALLS = ("apply_event_terminal_states", "auto_trigger_seed_issues")


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
                        "in_pre_settle": "pre_settle" in rel or (
                            path.suffix == ".py" and "def pre_settle" in text and
                            _line_in_func(text, i, "pre_settle")
                        ),
                    })
    return members


def _line_in_func(text: str, lineno: int, func: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return node.lineno <= lineno <= (node.end_lineno or node.lineno)
    return False


def main():
    report = {
        "G1": enum_g1(),
        "G2": enum_g2(),
        "G3": enum_g3(),
        "G4": enum_g4(),
        "G5": enum_g5(),
    }
    out_json = Path("/tmp/1835-w5-recheck/enum/enum-post.json")
    out_txt = Path("/tmp/1835-w5-recheck/enum/enum-post.txt")
    # Also copy into evidence later
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    for key, items in report.items():
        lines.append(f"== {key} count={len(items)} ==")
        if key == "G2":
            washes = [m for m in items if m.get("washes_reject")]
            decl = [m for m in items if m.get("in_decl_path") and m.get("kind") == "broad_except"]
            loads = [m for m in items if m.get("kind") == "json_loads"]
            lines.append(f"  broad_except_washes_reject={len(washes)}")
            lines.append(f"  broad_except_in_decl_path={len(decl)}")
            lines.append(f"  json_loads={len(loads)}")
            for m in washes[:40]:
                lines.append(f"  WASH {m['file']}:{m['lineno']} {m['symbol']} types={m['types']}")
            for m in decl[:40]:
                if m in washes:
                    continue
                lines.append(f"  DECL {m['file']}:{m['lineno']} {m['symbol']} types={m['types']}")
        elif key == "G3":
            idents = [m for m in items if m.get("kind") == "identical_body"]
            named = [m for m in items if m.get("kind") == "named_residual"]
            policy = [m for m in items if m.get("kind") == "policy_shape"]
            lines.append(f"  identical_body_groups={len(idents)}")
            lines.append(f"  named_residual={len(named)}")
            lines.append(f"  policy_shape={len(policy)}")
            for m in named:
                lines.append(f"  NAMED {m['file']}:{m['lineno']} {m['symbol']} :: {m.get('line')}")
            for m in policy:
                lines.append(f"  POLICY {m['file']}:{m['lineno']} {m['symbol']}")
            # show domain-relevant identical bodies (skip bind_content noise somewhat)
            for m in idents:
                files = {g["file"] for g in m["group"]}
                if any("entities/" in f or "settlement/" in f or "displaced" in f for f in files):
                    lines.append(f"  IDENT {m['hash']} {[g['file']+':'+g['symbol'] for g in m['group']]}")
        elif key == "G4":
            dead = [m for m in items if m.get("disposition_hint") == "dead_no_consumer"]
            test_only = [m for m in items if m.get("disposition_hint") == "test_only"]
            unread = [m for m in items if m.get("kind") == "unread_run_field"]
            lines.append(f"  dead_no_consumer={len(dead)} test_only={len(test_only)} unread_run_field={len(unread)}")
            for m in dead + test_only + unread:
                lines.append(
                    f"  {m.get('disposition_hint') or m['kind']} {m['symbol']} "
                    f"defined={m.get('defined')} prod={m.get('external_prod_refs')} test={m.get('test_refs')}"
                )
        elif key == "G5":
            in_pre = [m for m in items if m.get("in_pre_settle")]
            lines.append(f"  in_pre_settle={len(in_pre)}")
            for m in items:
                flag = "PRE" if m.get("in_pre_settle") else "ok"
                lines.append(f"  [{flag}] {m['file']}:{m['lineno']} {m['symbol']} :: {m['line']}")
        else:
            for m in items[:80]:
                lines.append(f"  {m.get('file')}:{m.get('lineno')} {m.get('symbol')} {m.get('kind','')}")
        lines.append("")
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(out_txt.read_text())


if __name__ == "__main__":
    main()
