#!/usr/bin/env python3
"""#1835 S1–S4 full-class enumeration (NOT a test).

Class definitions (from judge fix summary; enumerate by definition, not samples):

S1: typed-result producers + consumer closures still using old dict/response shapes
    (get / items / subscript / old response fields). Use existing typed contract;
    no dict compat layer.

S2: domain quantity / clamp / cap / admission rules AND stages parse/validate
    consumers; compare with write kernels; merge parallel implementations.
    Keep legal physical rules and whole-event reject; no new preview framework.

S3: by actual consumers — old stop-condition compat chains, exclusive tests/docs,
    tests that lost claimed detection power, unused fixtures. Keep typed stop
    and legal negative contracts; do not invent replacement proof tests.

S4: all code-fabricated political-benefit defaults/fallbacks and their tests;
    not limited to 民心 literals. Empty from model stays empty.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
SKIP = {".git", "web", "node_modules", "evidence", ".venv", "venv", "__pycache__"}

TYPED_RESULT_NAMES = {
    "SectionResult",
    "IssueSectionResult",
    "FiscalSectionResult",
    "SettlementOutcome",
    "DeclarationDispatchResult",
    "ProtagonistResult",
    "ResolveResult",
    "FiscalTickResult",
    "ApplyResult",
    "ChatTurnResult",
    "ChatResult",
}

# Political / authority metrics that code must not invent as floors.
POLITICAL_METRIC_KEYS = {
    "民心",
    "皇威",
    "士气",
    "军心",
    "官声",
    "legitimacy",
    "authority",
    "morale",
    "loyalty_reward",
    "political",
}


def tracked_py(base: Path):
    for p in sorted(base.rglob("*.py")):
        if any(part in SKIP for part in p.parts):
            continue
        if "__pycache__" in p.parts:
            continue
        yield p


def parse(path: Path):
    try:
        src = path.read_text(encoding="utf-8")
        return src, ast.parse(src, filename=str(path))
    except Exception:
        return None, None


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


def ann_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return ann_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ── S1 ───────────────────────────────────────────────────────────────────


def enum_s1():
    """Producers of typed results + consumer closures via dataflow (not name/key filters).

    Consumer predicate: within a function, names bound from typed producers / typed
    params / settle_delta|dispatch_declaration|apply_issue_tracker_output returns,
    then dict-shaped access (subscript / get / items / keys / values / pop) on those
    bindings or their section attributes. Old response field keys are listed without
    base-name filtering for disposition.
    """
    producers = []
    producer_leaves: set[str] = set()
    entry_leaves = {
        "settle_delta",
        "dispatch_declaration",
        "apply_issue_tracker_output",
        "settle_with_delta",
    }
    for path in tracked_py(ROOT / "ming_sim"):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for qname, fn in qual_funcs(tree):
            ret = ann_name(fn.returns)
            constructs = False
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and call_name(n.func) in TYPED_RESULT_NAMES:
                    constructs = True
            if ret in TYPED_RESULT_NAMES or constructs:
                leaf = qname.split(".")[-1]
                producer_leaves.add(leaf)
                producers.append(
                    {
                        "file": rel,
                        "symbol": qname,
                        "lineno": fn.lineno,
                        "kind": "producer",
                        "return_ann": ret,
                        "constructs": constructs,
                    }
                )

    consumers = []
    for path in list(tracked_py(ROOT / "ming_sim")) + list(tracked_py(ROOT / "tests")):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for fn_name, fn in qual_funcs(tree):
            bound: dict[str, str] = {}
            for a in fn.args.args:
                if ann_name(a.annotation) in TYPED_RESULT_NAMES:
                    bound[a.arg] = f"param:{ann_name(a.annotation)}"
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                    leaf = call_name(n.value.func)
                    if leaf in producer_leaves or leaf in entry_leaves or leaf in TYPED_RESULT_NAMES:
                        for t in n.targets:
                            if isinstance(t, ast.Name):
                                bound[t.id] = leaf or "?"
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    if ann_name(n.annotation) in TYPED_RESULT_NAMES:
                        bound[n.target.id] = f"ann:{ann_name(n.annotation)}"
                    elif isinstance(n.value, ast.Call):
                        leaf = call_name(n.value.func)
                        if leaf in producer_leaves or leaf in entry_leaves:
                            bound[n.target.id] = leaf or "?"
            if not bound:
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(
                    n.slice.value, str
                ):
                    base = n.value
                    if isinstance(base, ast.Name) and base.id in bound:
                        consumers.append(
                            {
                                "file": rel,
                                "lineno": n.lineno,
                                "kind": "dict_shape_consumer",
                                "access": "subscript",
                                "target": base.id,
                                "bound_from": bound[base.id],
                                "key": n.slice.value,
                                "src": ast.get_source_segment(src, n),
                            }
                        )
                    elif (
                        isinstance(base, ast.Attribute)
                        and isinstance(base.value, ast.Name)
                        and base.value.id in bound
                    ):
                        consumers.append(
                            {
                                "file": rel,
                                "lineno": n.lineno,
                                "kind": "dict_shape_consumer",
                                "access": "subscript_attr",
                                "target": f"{base.value.id}.{base.attr}",
                                "bound_from": bound[base.value.id],
                                "key": n.slice.value,
                                "src": ast.get_source_segment(src, n),
                            }
                        )
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    meth = n.func.attr
                    if meth not in {"get", "items", "keys", "values", "pop", "setdefault", "update"}:
                        continue
                    base = n.func.value
                    key = None
                    if meth == "get" and n.args and isinstance(n.args[0], ast.Constant):
                        key = n.args[0].value
                    if isinstance(base, ast.Name) and base.id in bound:
                        consumers.append(
                            {
                                "file": rel,
                                "lineno": n.lineno,
                                "kind": "dict_shape_consumer",
                                "access": f"call_{meth}",
                                "target": base.id,
                                "bound_from": bound[base.id],
                                "key": key,
                                "src": ast.get_source_segment(src, n),
                            }
                        )
                    elif (
                        isinstance(base, ast.Attribute)
                        and isinstance(base.value, ast.Name)
                        and base.value.id in bound
                    ):
                        consumers.append(
                            {
                                "file": rel,
                                "lineno": n.lineno,
                                "kind": "dict_shape_consumer",
                                "access": f"call_{meth}_attr",
                                "target": f"{base.value.id}.{base.attr}",
                                "bound_from": bound[base.value.id],
                                "key": key,
                                "src": ast.get_source_segment(src, n),
                            }
                        )

    # Old response field keys — no base-name filter; disposition classifies.
    OLD_RESPONSE_KEYS = {
        "appointments",
        "character_status_changes",
        "character_power_changes",
        "office_changes",
        "person_changes",
        "pairing_warnings",
        "touched_ids",
        "issue_summary",
        "metric_delta",
        "economy_moves",
        "faction_delta",
        "class_delta",
        "applied_person_changes",
        "new_armies",
        "region_changes",
        "army_changes",
        "power_changes",
        "fiscal_creates",
        "fiscal_removes",
        "fiscal_changes",
        "authority_changes",
    }
    old_field_hits = []
    for path in list(tracked_py(ROOT / "ming_sim")) + list(tracked_py(ROOT / "tests")):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for n in ast.walk(tree):
            key = None
            kind = None
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
                if isinstance(n.slice.value, str):
                    key = n.slice.value
                    kind = "subscript"
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
                if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    key = n.args[0].value
                    kind = "get"
            if key is None:
                continue
            is_old = key in OLD_RESPONSE_KEYS or (
                isinstance(key, str) and key.endswith("_rejections") and key != "shape_rejections"
            )
            if not is_old:
                continue
            base_src = ""
            if isinstance(n, ast.Subscript):
                base_src = ast.get_source_segment(src, n.value) or ""
            elif isinstance(n, ast.Call):
                base_src = ast.get_source_segment(src, n.func.value) or ""
            old_field_hits.append(
                {
                    "file": rel,
                    "lineno": n.lineno,
                    "kind": "old_response_field",
                    "access": kind,
                    "key": key,
                    "base": base_src,
                    "src": ast.get_source_segment(src, n),
                }
            )

    return {
        "producers": producers,
        "dict_shape_consumers": consumers,
        "old_response_field_accesses": old_field_hits,
    }


# ── S2 ───────────────────────────────────────────────────────────────────

CLAMP_PAT = re.compile(
    r"max\s*\(\s*0\s*,\s*min\s*\(|"
    r"min\s*\(\s*12\s*,|"
    r"min\s*\(\s*100\s*,|"
    r"city_level\s*\)\s*\*\s*8|"
    r"\*\s*8\b|"
    r"clamp|封顶|钳制|下限|上限|cap\b|noop",
    re.I,
)
ADMISSION_PAT = re.compile(
    r"unknown_person|person_not_found|not in characters|controlled_by|"
    r"admission|准入|whitelist|allowlist|reject.*person|person.*reject|"
    r"invalid_person|missing_person|人物不存在|势力不存在",
    re.I,
)
STAGES_PAT = re.compile(
    r"stages_to_json|capture_commitment_stages|stages_json|stages_list|"
    r"stage_idx|due_turn|criterion_text|origin_context|"
    r"json\.loads\(.*stages|stages.*json\.loads|parse.*stages|stages.*parse",
    re.I,
)
WRITE_KERNEL_HINT = re.compile(
    r"apply_region_deltas|apply_army_deltas|apply_power_deltas|"
    r"apply_metric|set_firearm|set_cannon|cannon_equipment|firearm_equipment|"
    r"city_level|loyalty",
    re.I,
)


def func_body_src(fn: ast.AST) -> str:
    try:
        return ast.unparse(fn)
    except Exception:
        return ""


def enum_s2():
    members = []
    body_hashes: dict[str, list[dict]] = defaultdict(list)
    for path in tracked_py(ROOT / "ming_sim"):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for qname, fn in qual_funcs(tree):
            body = func_body_src(fn)
            tags = []
            if CLAMP_PAT.search(body) or CLAMP_PAT.search(qname):
                tags.append("quantity_clamp_cap")
            if ADMISSION_PAT.search(body) or ADMISSION_PAT.search(qname):
                tags.append("admission")
            if STAGES_PAT.search(body) or STAGES_PAT.search(qname):
                tags.append("stages_parse_validate")
            if not tags:
                continue
            h = hashlib.sha1(re.sub(r"\s+", " ", body).strip().encode()).hexdigest()[:12]
            rec = {
                "file": rel,
                "symbol": qname,
                "lineno": fn.lineno,
                "tags": tags,
                "body_hash": h,
                "write_kernel_hint": bool(WRITE_KERNEL_HINT.search(body)),
            }
            members.append(rec)
            body_hashes[h].append(rec)

        # Also line-level clamp formulas outside function names (module level / nested)
        for i, line in enumerate(src.splitlines(), 1):
            if re.search(r"max\s*\(\s*0\s*,\s*min\s*\(", line) or re.search(
                r"city_level\s*\)\s*\*\s*8|min\s*\(\s*12\s*,", line
            ):
                members.append(
                    {
                        "file": rel,
                        "symbol": f"<line:{i}>",
                        "lineno": i,
                        "tags": ["quantity_clamp_cap_line"],
                        "body_hash": None,
                        "write_kernel_hint": bool(WRITE_KERNEL_HINT.search(line)),
                        "line": line.strip()[:160],
                    }
                )

    parallels = {h: group for h, group in body_hashes.items() if len(group) > 1}
    # Stages call sites (consumers of parse/validate), not limited to named helper
    stages_consumers = []
    for path in list(tracked_py(ROOT / "ming_sim")) + list(tracked_py(ROOT / "tests")):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for i, line in enumerate(src.splitlines(), 1):
            if STAGES_PAT.search(line):
                stages_consumers.append(
                    {"file": rel, "lineno": i, "line": line.strip()[:200]}
                )

    return {
        "rule_members": members,
        "identical_body_groups": {
            h: [{"file": g["file"], "symbol": g["symbol"], "lineno": g["lineno"]} for g in group]
            for h, group in parallels.items()
        },
        "stages_line_hits": stages_consumers,
    }


# ── S3 ───────────────────────────────────────────────────────────────────

STOP_COMPAT_PAT = re.compile(
    r"resolve_condition|stop_condition|stop_gate|commitment_stop|"
    r"legacy_resolve|falls_back|fallback.*stop|stop.*fallback|"
    r"condition_role|whitespace_resolve",
    re.I,
)
LOST_DETECT_PAT = re.compile(
    r"reports_no_legacy|no_legacy_person_response|accepts_flat_faction|"
    r"assert True|pass\s*$|断言.*删|失去|legacy.*response.*key",
    re.I,
)


def build_load_index() -> dict[str, list[dict]]:
    """One-pass Load/Attribute index for consumer closure counts."""
    idx: dict[str, list[dict]] = defaultdict(list)
    for path in list(tracked_py(ROOT / "ming_sim")) + list(tracked_py(ROOT / "tests")):
        _src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        bucket = "test" if rel.startswith("tests/") else "prod"
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                idx[n.id].append({"file": rel, "lineno": n.lineno, "bucket": bucket})
            elif isinstance(n, ast.Attribute):
                idx[n.attr].append({"file": rel, "lineno": n.lineno, "bucket": bucket})
    return idx


def count_name_refs(name: str, idx: dict[str, list[dict]] | None = None) -> dict:
    hits = (idx or build_load_index()).get(name, [])
    prod = sum(1 for h in hits if h["bucket"] == "prod")
    test = sum(1 for h in hits if h["bucket"] == "test")
    return {"prod": prod, "test": test, "hits": hits}


def enum_s3():
    stop_members = []
    py_paths = list(tracked_py(ROOT / "ming_sim")) + list(tracked_py(ROOT / "tests"))
    for path in py_paths:
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for qname, fn in qual_funcs(tree):
            body = func_body_src(fn)
            if not STOP_COMPAT_PAT.search(body) and not STOP_COMPAT_PAT.search(qname):
                continue
            # Classify: legacy compat vs typed stop consumer
            legacyish = bool(
                re.search(
                    r"legacy|_legacy|fallback|falls_back|resolve_condition.*stop_condition|"
                    r"stop_condition.*resolve_condition|whitespace",
                    body + qname,
                    re.I,
                )
            )
            stop_members.append(
                {
                    "file": rel,
                    "symbol": qname,
                    "lineno": fn.lineno,
                    "kind": "legacy_stop_compat" if legacyish else "stop_condition_touch",
                    "legacyish": legacyish,
                }
            )
    # Docs mentioning legacy stop/resolve compat (md under docs/ and root contract docs)
    for path in sorted((ROOT / "docs").rglob("*.md")):
        if any(part in SKIP for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = str(path.relative_to(ROOT))
        for i, line in enumerate(text.splitlines(), 1):
            if STOP_COMPAT_PAT.search(line) and re.search(
                r"legacy|兼容|fallback|旧.*stop|resolve_condition.*stop", line, re.I
            ):
                stop_members.append(
                    {
                        "file": rel,
                        "lineno": i,
                        "kind": "doc_legacy_stop",
                        "line": line.strip()[:200],
                    }
                )

    # Tests with empty/weak assertions (lost detection)
    weak_tests = []
    for path in tracked_py(ROOT / "tests"):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for qname, fn in qual_funcs(tree):
            if not qname.startswith("test_"):
                continue
            body = func_body_src(fn)
            asserts = [
                n
                for n in ast.walk(fn)
                if isinstance(n, ast.Assert)
                or (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr.startswith("assert")
                )
                or (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id.startswith("assert")
                )
            ]
            # lost detection heuristics: zero asserts, or only "does not raise", or LOST_DETECT patterns
            only_no_raise = bool(
                re.search(r"does not raise|不抛|no longer|reports_no_legacy|accepts_flat", body, re.I)
            ) and len(asserts) <= 1
            if len(asserts) == 0 or only_no_raise or LOST_DETECT_PAT.search(qname):
                # Only flag if also related to settle/legacy/response/score — avoid flooding all empty tests
                if re.search(
                    r"legacy|score_extraction|response_key|faction_scalar|stop_condition|"
                    r"resolve_condition|apply_score|person_delta|flat_faction",
                    body + qname,
                    re.I,
                ):
                    weak_tests.append(
                        {
                            "file": rel,
                            "symbol": qname,
                            "lineno": fn.lineno,
                            "kind": "weak_or_lost_detection_test",
                            "assert_count": len(asserts),
                        }
                    )

    # Unused fixtures: test helper defs with zero Load refs outside their def
    dead_fixtures = []
    fixture_defs = []
    for path in tracked_py(ROOT / "tests"):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for qname, fn in qual_funcs(tree):
            if qname.startswith("test_") or qname.startswith("_test"):
                continue
            if not (
                qname.startswith("_")
                or "seed" in qname.lower()
                or "fixture" in qname.lower()
                or "scenario" in qname.lower()
            ):
                if not qname.startswith("_"):
                    continue
            fixture_defs.append((rel, qname, fn.lineno))

    load_idx = build_load_index()
    for rel, name, lineno in fixture_defs:
        leaf = name.split(".")[-1]
        refs = count_name_refs(leaf, load_idx)
        # Name Load count; definition is Store so shouldn't count
        if refs["prod"] + refs["test"] == 0:
            dead_fixtures.append(
                {
                    "file": rel,
                    "symbol": name,
                    "lineno": lineno,
                    "kind": "unused_fixture",
                    "refs": refs["prod"] + refs["test"],
                }
            )

    return {
        "stop_touch_members": stop_members,
        "weak_or_lost_tests": weak_tests,
        "unused_fixtures": dead_fixtures,
    }


# ── S4 ───────────────────────────────────────────────────────────────────

FLOOR_PAT = re.compile(
    r"floor|兜底|兜最小|绝不入空壳|default.*reward|initiative_floor|"
    r"空则|没补出|enrich.*empty|empty.*enrich|保底|默认.*民心|默认.*皇威|"
    r"metrics.*=.*\{|effect_on_resolve\s*=\s*\{",
    re.I,
)


def enum_s4():
    members = []
    for path in list(tracked_py(ROOT / "ming_sim")) + list(tracked_py(ROOT / "tests")):
        src, tree = parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        for i, line in enumerate(src.splitlines(), 1):
            # Any political metric literal in assignment/default context
            has_metric = any(k in line for k in POLITICAL_METRIC_KEYS)
            has_floor = bool(FLOOR_PAT.search(line))
            if not (has_metric or has_floor):
                continue
            # Focus on code inventing defaults: assignment of metrics dict, or floor comments
            if not (
                has_floor
                or re.search(r"metrics\"\s*:\s*\{|metrics'\s*:\s*\{", line)
                or re.search(r"effect_on_resolve\s*=", line)
                or re.search(r"ongoing_effects\s*=", line)
                or re.search(r"default|fallback|floor|兜", line, re.I)
            ):
                continue
            members.append(
                {
                    "file": rel,
                    "lineno": i,
                    "kind": "political_default_candidate",
                    "has_floor_language": has_floor,
                    "metrics_present": [k for k in POLITICAL_METRIC_KEYS if k in line],
                    "line": line.strip()[:220],
                }
            )
        for qname, fn in qual_funcs(tree):
            body = func_body_src(fn)
            if FLOOR_PAT.search(body) or FLOOR_PAT.search(qname):
                if any(k in body for k in POLITICAL_METRIC_KEYS) or "enrich" in body.lower() or "floor" in (body + qname).lower():
                    members.append(
                        {
                            "file": rel,
                            "symbol": qname,
                            "lineno": fn.lineno,
                            "kind": "political_default_function",
                            "line": None,
                        }
                    )
    return {"members": members}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    out = {
        "mode": mode,
        "S1": enum_s1(),
        "S2": enum_s2(),
        "S3": enum_s3(),
        "S4": enum_s4(),
    }
    json_path = OUT_DIR / f"enum-{mode}.json"
    txt_path = OUT_DIR / f"enum-{mode}.txt"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    lines.append(f"=== S1 typed producers ({len(out['S1']['producers'])}) ===")
    for p in out["S1"]["producers"]:
        lines.append(
            f"{p['file']}:{p['lineno']}\t{p['symbol']}\tann={p['return_ann']}\tconstructs={p['constructs']}"
        )
    lines.append(
        f"=== S1 dict_shape_consumers ({len(out['S1']['dict_shape_consumers'])}) ==="
    )
    for c in out["S1"]["dict_shape_consumers"]:
        lines.append(
            f"{c['file']}:{c['lineno']}\t{c['access']}\t{c['target']}[{c['key']!r}]\t{c['src']}"
        )
    lines.append(
        f"=== S1 old_response_field_accesses ({len(out['S1']['old_response_field_accesses'])}) ==="
    )
    for c in out["S1"]["old_response_field_accesses"]:
        lines.append(
            f"{c['file']}:{c['lineno']}\t{c['access']}\tbase={c['base']}\tkey={c['key']!r}\t{c['src']}"
        )

    lines.append(f"=== S2 rule_members ({len(out['S2']['rule_members'])}) ===")
    for m in out["S2"]["rule_members"]:
        extra = m.get("line") or ""
        lines.append(
            f"{m['file']}:{m['lineno']}\t{m['symbol']}\ttags={','.join(m['tags'])}\tkernel={m['write_kernel_hint']}\t{extra}"
        )
    lines.append(
        f"=== S2 identical_body_groups ({len(out['S2']['identical_body_groups'])}) ==="
    )
    for h, group in out["S2"]["identical_body_groups"].items():
        lines.append(f"HASH {h} n={len(group)}")
        for g in group:
            lines.append(f"  {g['file']}:{g['lineno']}\t{g['symbol']}")
    lines.append(f"=== S2 stages_line_hits ({len(out['S2']['stages_line_hits'])}) ===")
    for m in out["S2"]["stages_line_hits"]:
        lines.append(f"{m['file']}:{m['lineno']}\t{m['line']}")

    lines.append(
        f"=== S3 stop_touch_members ({len(out['S3']['stop_touch_members'])}) ==="
    )
    for m in out["S3"]["stop_touch_members"]:
        if "symbol" in m:
            lines.append(
                f"{m['file']}:{m['lineno']}\t{m['symbol']}\t{m['kind']}\tlegacyish={m.get('legacyish')}"
            )
        else:
            lines.append(f"{m['file']}:{m['lineno']}\t{m['kind']}\t{m.get('line','')}")
    lines.append(
        f"=== S3 weak_or_lost_tests ({len(out['S3']['weak_or_lost_tests'])}) ==="
    )
    for m in out["S3"]["weak_or_lost_tests"]:
        lines.append(
            f"{m['file']}:{m['lineno']}\t{m['symbol']}\tasserts={m['assert_count']}"
        )
    lines.append(f"=== S3 unused_fixtures ({len(out['S3']['unused_fixtures'])}) ===")
    for m in out["S3"]["unused_fixtures"]:
        lines.append(f"{m['file']}:{m['lineno']}\t{m['symbol']}\trefs={m['refs']}")

    lines.append(f"=== S4 political_default_candidates ({len(out['S4']['members'])}) ===")
    for m in out["S4"]["members"]:
        if m.get("symbol"):
            lines.append(f"{m['file']}:{m['lineno']}\t{m['symbol']}\t{m['kind']}")
        else:
            lines.append(
                f"{m['file']}:{m['lineno']}\tfloor={m.get('has_floor_language')}\tmetrics={m.get('metrics_present')}\t{m.get('line')}"
            )

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {txt_path}")
    print(
        "COUNTS",
        {
            "S1_producers": len(out["S1"]["producers"]),
            "S1_dict_consumers": len(out["S1"]["dict_shape_consumers"]),
            "S1_old_fields": len(out["S1"]["old_response_field_accesses"]),
            "S2_rules": len(out["S2"]["rule_members"]),
            "S2_parallel_groups": len(out["S2"]["identical_body_groups"]),
            "S2_stages_lines": len(out["S2"]["stages_line_hits"]),
            "S3_stop": len(out["S3"]["stop_touch_members"]),
            "S3_weak": len(out["S3"]["weak_or_lost_tests"]),
            "S3_dead_fixtures": len(out["S3"]["unused_fixtures"]),
            "S4": len(out["S4"]["members"]),
        },
    )


if __name__ == "__main__":
    main()
