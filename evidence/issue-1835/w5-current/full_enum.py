#!/usr/bin/env python3
"""Full-class enumeration for #1835 G1–G5. Predicate covers class defs, not sample symbols."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1835-w5")
PROD = ROOT / "ming_sim"
TESTS = ROOT / "tests"
DOCS = ROOT / "docs"


def iter_py(base: Path):
    for p in base.rglob("*.py"):
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
            out.append((node.name, node, False, None))
        elif isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((f"{node.name}.{n.name}", n, False, node.name))
    return out


def body_dump(node: ast.AST) -> str:
    # Normalize: drop docstrings, clear lineno
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

        def visit_arg(self, n):
            n.annotation = None
            return n

    try:
        cloned = Norm().visit(ast.parse(ast.unparse(node)))
        return ast.dump(cloned, annotate_fields=True)
    except Exception:
        return ast.dump(node)


def name_refs(tree: ast.AST, names: set[str]):
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in names:
            hits.append(("Name", n.id, getattr(n, "lineno", None)))
        elif isinstance(n, ast.Attribute) and n.attr in names:
            hits.append(("Attr", n.attr, getattr(n, "lineno", None)))
    return hits


# ── G1: code substitutes model judgment on 撤诺 / world disposal ─────────
G1_SHAPES = {
    "tier_assess": re.compile(r"assess_foundation_tier|FOUNDATION_(HALFWAY|ROOTED|JUST_STARTED)"),
    "write_exec_final": re.compile(r"record_dossier_execution|execution_outcome\s*="),
    "halfway_setback": re.compile(r"_apply_halfway_national_setback|HALFWAY_SETBACK|_HALFWAY_METRICS"),
    "indiscriminate_cancel": re.compile(r"cancel_issue|stop_origin_commitment"),
}


def enum_g1():
    members = []
    # Functions that implement 撤诺 code-judgment shapes in breach/revoke path
    for path in iter_py(PROD):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        for qname, node, _, _ in qual_funcs(tree):
            src = ast.unparse(node) if hasattr(ast, "unparse") else ""
            tags = [k for k, rx in G1_SHAPES.items() if rx.search(src) or rx.search(qname)]
            # Scope: 撤诺 / breach / revoke / persist path — not expand to all 松手
            in_scope = (
                "breach" in rel
                or "breach" in qname.lower()
                or "revoke" in qname.lower()
                or "persist" in qname.lower()
                or "foundation" in qname.lower()
                or "halfway" in qname.lower()
                or "stop_origin" in qname.lower()
            )
            if tags and in_scope:
                members.append({
                    "file": rel,
                    "symbol": qname,
                    "lineno": node.lineno,
                    "shapes": tags,
                })
        # Also flag tracker cancels→finalize_persist call site
        if "finalize_persist" in text and "tracker" in rel:
            for i, line in enumerate(text.splitlines(), 1):
                if "finalize_persist" in line:
                    members.append({
                        "file": rel, "symbol": f"call:finalize_persist@{i}",
                        "lineno": i, "shapes": ["call_site"],
                    })
    return members


# ── G2: persistence/impl faults washed into declaration rejection ────────
def enum_g2():
    members = []
    # Broad except ValueError/TypeError in declaration_dispatch that can catch JSONDecodeError / persist ValueError
    path = PROD / "declaration_dispatch.py"
    tree = parse(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            types = []
            if isinstance(node.type, ast.Tuple):
                for e in node.type.elts:
                    types.append(ast.unparse(e) if hasattr(ast, "unparse") else getattr(e, "id", str(e)))
            elif node.type is not None:
                types.append(ast.unparse(node.type) if hasattr(ast, "unparse") else getattr(node.type, "id", str(node.type)))
            joined = " ".join(types)
            if "ValueError" in joined or "TypeError" in joined:
                # Check if handler rejects / _reject
                body = ast.unparse(node) if hasattr(ast, "unparse") else ""
                if "_reject" in body or "invalid_shape" in body or "rejected" in body:
                    members.append({
                        "file": "ming_sim/declaration_dispatch.py",
                        "lineno": node.lineno,
                        "except_types": types,
                        "snippet": lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                        "washes": True,
                    })
    # Persistence load helpers using raw json.loads (JSONDecodeError ⊂ ValueError)
    for path in iter_py(PROD):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        for qname, node, _, _ in qual_funcs(tree):
            src = ast.unparse(node) if hasattr(ast, "unparse") else ""
            if "json.loads" in src and ("payload_json" in src or "payload" in qname.lower()):
                if "parse_engine_payload_json" not in src:
                    members.append({
                        "file": rel,
                        "symbol": qname,
                        "lineno": node.lineno,
                        "kind": "raw_json_loads_payload",
                    })
    return members


# ── G3: parallel domain admission / business rule authorities ────────────
def enum_g3():
    members = {"person_admission": [], "duplicate_bodies": [], "dossier_parse": [], "outcome_merge": []}
    # Person admission: functions that decide character admissibility / faction / affiliation checks
    person_rx = re.compile(
        r"(person|character).*(admit|accept|reject|valid|exist|power|faction|归属|归附)|"
        r"_pending_person|_assert_character|character.*exist|power_id|active_affiliation|"
        r"person_change.*reject|invalid_origin|招安|amnest",
        re.I,
    )
    # Collect function body digests for exact duplicates
    digests = defaultdict(list)
    for path in iter_py(PROD):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        if tree is None:
            continue
        for qname, node, _, _ in qual_funcs(tree):
            src = ast.unparse(node) if hasattr(ast, "unparse") else ""
            # person admission policy sites (named by reviewer samples + shape)
            if person_rx.search(qname) or person_rx.search(src[:500]):
                # Heuristic: look for actual gate/reject logic
                if any(k in src for k in ("reject", "Reject", "hallucinated", "power_id", "status", "active")):
                    members["person_admission"].append({
                        "file": rel, "symbol": qname, "lineno": node.lineno,
                    })
            if "dossier" in qname.lower() and ("parse" in qname.lower() or "parse_dossier" in src):
                members["dossier_parse"].append({
                    "file": rel, "symbol": qname, "lineno": node.lineno,
                })
            dump = body_dump(node)
            # Skip tiny
            if len(dump) < 80:
                continue
            digests[hashlib.sha1(dump.encode()).hexdigest()].append({
                "file": rel, "symbol": qname, "lineno": node.lineno, "dump_len": len(dump),
            })
        # outcome merge helpers
        text = path.read_text(encoding="utf-8")
        if "SectionResult" in text and ("outcomes" in text):
            for qname, node, _, _ in qual_funcs(tree):
                src = ast.unparse(node) if hasattr(ast, "unparse") else ""
                if "outcomes" in src and ("SectionResult" in src or "applied" in src) and (
                    "placed" in qname or "stored" in qname or "merge" in qname.lower() or qname.startswith("_")
                ):
                    if "outcomes" in src and ("[" in src or ".append" in src or "extend" in src):
                        members["outcome_merge"].append({
                            "file": rel, "symbol": qname, "lineno": node.lineno,
                        })
    for h, group in digests.items():
        if len(group) >= 2:
            # Same body across ≥2 symbols
            members["duplicate_bodies"].append({"hash": h[:12], "members": group})
    return members


# ── G4: replaced old mechanisms, exclusive old tests, no-consumer state ───
DEAD_CANDIDATE_NAMES = [
    "_extract_secret_order",
    "_collect_compliant_promulgation_items",
    "_merge_compliant_promulgation_items",
    "_promulgable_proposed_dossiers",
    "_dossier_ids_from_simulator_payload",
    "_open_affair_ids_from_payload",
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
    "person_changes",  # SettlementRun field — need read check
    "stamped_by_origin",
    "rejected_origin_ids",
]


def enum_g4():
    # Build def sites and reference counts across prod+tests
    defs = {}  # name -> list of def sites
    refs = defaultdict(list)  # name -> (file, lineno, kind)
    for base in (PROD, TESTS):
        for path in iter_py(base):
            rel = str(path.relative_to(ROOT))
            tree = parse(path)
            if tree is None:
                continue
            for qname, node, _, parent in qual_funcs(tree):
                short = qname.split(".")[-1]
                if short in DEAD_CANDIDATE_NAMES or qname in DEAD_CANDIDATE_NAMES:
                    defs.setdefault(short, []).append({"file": rel, "symbol": qname, "lineno": node.lineno})
            for kind, name, lineno in name_refs(tree, set(DEAD_CANDIDATE_NAMES)):
                refs[name].append({"file": rel, "lineno": lineno, "kind": kind})
    # SettlementRun fields
    run_path = PROD / "settlement/run.py"
    run_text = run_path.read_text(encoding="utf-8")
    field_members = []
    for fname in ("person_changes", "stamped_by_origin", "rejected_origin_ids"):
        # assignments vs reads
        assign = len(re.findall(rf"\.{fname}\s*=", run_text)) + len(re.findall(rf"{fname}\s*=", run_text))
        # reads as attribute elsewhere
        read_sites = [r for r in refs.get(fname, []) if not r["file"].endswith("settlement/run.py") or True]
        field_members.append({"field": fname, "assignish": assign, "refs": refs.get(fname, [])})
    # character delta_section phase del
    phase_sites = []
    for path in iter_py(PROD):
        text = path.read_text(encoding="utf-8")
        if "phase" in text and "del " in text and "delta_section" in str(path):
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"\bdel\b.*phase|phase.*\bdel\b", line):
                    phase_sites.append({"file": str(path.relative_to(ROOT)), "lineno": i, "line": line.strip()})
    # _extract_secret_order consumer closure
    extract_refs = refs.get("_extract_secret_order", [])
    members = []
    for name in DEAD_CANDIDATE_NAMES:
        def_sites = defs.get(name, [])
        ref_sites = [r for r in refs.get(name, [])]
        # exclude def lines themselves roughly
        prod_refs = [r for r in ref_sites if r["file"].startswith("ming_sim/")]
        test_refs = [r for r in ref_sites if r["file"].startswith("tests/")]
        members.append({
            "symbol": name,
            "defs": def_sites,
            "prod_refs": prod_refs,
            "test_refs": test_refs,
            "prod_ref_count": len(prod_refs),
            "test_ref_count": len(test_refs),
        })
    return {
        "dead_or_test_only": members,
        "settlement_run_fields": field_members,
        "phase_del": phase_sites,
        "extract_secret_order_refs": extract_refs,
    }


# ── G5: pre-edict event consumption revived parallel path ────────────────
def enum_g5():
    members = []
    for path in (PROD / "decree.py", PROD / "month_chain.py"):
        rel = str(path.relative_to(ROOT))
        tree = parse(path)
        text = path.read_text(encoding="utf-8")
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                src = ast.unparse(node)
                calls = []
                for n in ast.walk(node):
                    if isinstance(n, ast.Call):
                        fn = n.func
                        name = fn.id if isinstance(fn, ast.Name) else (
                            fn.attr if isinstance(fn, ast.Attribute) else None
                        )
                        if name in {
                            "apply_event_terminal_states",
                            "auto_trigger_seed_issues",
                            "_consume_event_gates_after_edicts",
                        }:
                            calls.append({"name": name, "lineno": n.lineno})
                if calls:
                    members.append({
                        "file": rel, "function": node.name, "lineno": node.lineno, "calls": calls,
                    })
    # docs
    flow = (DOCS / "SETTLEMENT_FLOW.md").read_text(encoding="utf-8")
    members.append({
        "file": "docs/SETTLEMENT_FLOW.md",
        "mentions_pre_settle_events": "事件终态" in flow and "pre_settle" in flow,
        "line5": flow.splitlines()[4] if len(flow.splitlines()) > 4 else "",
    })
    return members


def main():
    out = {
        "G1": enum_g1(),
        "G2": enum_g2(),
        "G3": enum_g3(),
        "G4": enum_g4(),
        "G5": enum_g5(),
    }
    dest = Path("/tmp/1835-w5-current/enum/full.json")
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    # summaries
    print("G1 members", len(out["G1"]))
    for m in out["G1"]:
        print(" ", m)
    print("G2 wash handlers", sum(1 for m in out["G2"] if m.get("washes")))
    print("G2 raw json.loads", sum(1 for m in out["G2"] if m.get("kind") == "raw_json_loads_payload"))
    for m in out["G2"]:
        print(" ", m)
    print("G3 person_admission", len(out["G3"]["person_admission"]))
    for m in out["G3"]["person_admission"][:40]:
        print(" ", m)
    print("G3 duplicate_body groups", len(out["G3"]["duplicate_bodies"]))
    for g in out["G3"]["duplicate_bodies"][:30]:
        print(" ", g["hash"], [(x["file"], x["symbol"]) for x in g["members"]])
    print("G3 dossier_parse", out["G3"]["dossier_parse"])
    print("G3 outcome_merge", out["G3"]["outcome_merge"])
    print("G4 symbols")
    for m in out["G4"]["dead_or_test_only"]:
        print(f"  {m['symbol']}: defs={len(m['defs'])} prod_refs={m['prod_ref_count']} test_refs={m['test_ref_count']}")
    print("G4 phase_del", out["G4"]["phase_del"])
    print("G5", json.dumps(out["G5"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
