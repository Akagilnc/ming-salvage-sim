#!/usr/bin/env python3
"""F2-R10-1 full-repo mechanical enumeration (no in-repo scanner).

Class: 旧结算／simulator 独占支持及专属测试退役未闭合
Predicate (full class definition, not samples):
  From historically retired old-settlement/simulator consumers, chase exclusive
  support trees downward: assets, load bindings, fixtures, mutually-referencing
  dead trees, and tests that protect retired behavior. Retain live normalize /
  revise / prewrite / shared storage. Do not use zero-ref count or sample lists
  as the class boundary.

Outputs under /tmp/1843-f2-r10c/
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5")
OUT = Path("/tmp/1843-f2-r10c")
OUT.mkdir(parents=True, exist_ok=True)

# --- historically retired F2 consumers (union of R1–R10 sealed samples + R9 absence list) ---
# This is a SEED for downward chase, not a whitelist of work items.
HIST_RETIRED_CONSUMERS = sorted({
    # R1
    "execution_side_read_fields",
    "build_fiscal_fact_brief",
    "bind_decisions_to_candidate_events",
    # R2
    "season_option_contract_prompt",
    "season_simulator_prompt",
    # R4–R5 named
    "format_region_changes",
    "format_army_changes",
    "format_power_changes",
    "turn_region_summary",
    "turn_army_summary",
    "execution_distortion_weight",
    "command_power_rank",
    "build_secret_covert_effect_briefs",
    "has_player_visible_rejection",
    "faction_report",
    "create_rescript_draft_agent",
    "select_triage_actor",
    "generate_rescript_draft",
    "validate_rescript_draft_items",
    "RESCRIPT_OPTION_FIELD_HEAL_RETRIES",
    "_current_game_turn",
    "_apply_option_heal",
    # R8
    "list_arrived_unsettled_summons",
    "army_detail",
    "building_detail",
    "record_monthly_supervision_facts",
    "save_pending_promulgation_verdicts",
    "get_pending_promulgation_verdicts",
    "list_night_promulgated_directives",
    "list_promulgated_directives",
    "discard_pending_directives",
    "clear_resolve_context",
    "validate_delta_shape",
    "SUPERVISION_SURFACE_KEYS",
    # R9 storage
    "pending_promulgation_verdicts",
    # R10 assets / bindings / fixtures / retired behavior
    "rescript_draft_prompt",
    "rescript_draft",  # prompt stem
    "event_selector",
    "bind_from_candidate_snapshot_without_event_id",
    "candidate_events",  # old simulator board feed (producer retired)
})

# Live shared support that must NOT be deleted solely for being near retired trees
LIVE_SHARED_KEEP = {
    "normalize_appointment_tenure",
    "canonical_fields_for_delivery",
    "normalize_rescript_draft_items",
    "normalize_rescript_layer_a",
    "rescript_layer_a_prompt_contract",
    "_parse_rescript_json_strict",
    "save_rescript_drafts",
    "list_rescript_drafts",
    "save_resolve_context",
    "scene_agent_prompt",
    "revise_rescript",
    "prewrite",
    "gather_candidate_events",
    "_world_candidate_events",
}


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True)


def py_files() -> list[Path]:
    files: list[Path] = []
    for base in [ROOT / "ming_sim", ROOT / "scripts", ROOT / "tests"]:
        if base.exists():
            files.extend(base.rglob("*.py"))
    for name in ("web_app.py", "main.py", "launcher.py"):
        p = ROOT / name
        if p.exists():
            files.append(p)
    return [p for p in files if ".venv" not in p.parts and "__pycache__" not in p.parts]


def is_prod(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return not (rel.startswith("tests/") or "/tests/" in rel)


def is_test(path: Path) -> bool:
    return not is_prod(path)


# ---------- 1) git history: commits that deleted HIST seeds (no lower bound) ----------
hist_hits = []
for sym in HIST_RETIRED_CONSUMERS:
    try:
        log = run(["git", "log", "--all", "--diff-filter=D", "-S", sym, "--pretty=format:%H\t%s", "--", "*.py", "*.md"])
    except subprocess.CalledProcessError:
        log = ""
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, _, subj = line.partition("\t")
        hist_hits.append({"symbol": sym, "sha": sha, "subject": subj})

(OUT / "r10b-hist-deleted-seeds.json").write_text(
    json.dumps(hist_hits, ensure_ascii=False, indent=2), encoding="utf-8"
)


# ---------- 2) HEAD AST: defs + Name/Attribute loads for every seed ----------
class LoadCounter(ast.NodeVisitor):
    def __init__(self, names: set[str]):
        self.names = names
        self.loads: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.defs: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name in self.names:
            self.defs[node.name].append((self.rel, node.lineno))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)  # type: ignore

    def visit_ClassDef(self, node: ast.ClassDef):
        if node.name in self.names:
            self.defs[node.name].append((self.rel, node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in self.names:
                self.defs[t.id].append((self.rel, node.lineno))
            elif isinstance(t, ast.Attribute) and t.attr in self.names:
                self.defs[t.attr].append((self.rel, node.lineno))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        t = node.target
        if isinstance(t, ast.Name) and t.id in self.names:
            self.defs[t.id].append((self.rel, node.lineno))
        elif isinstance(t, ast.Attribute) and t.attr in self.names:
            self.defs[t.attr].append((self.rel, node.lineno))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id in self.names:
            self.loads[node.id].append((self.rel, node.lineno))

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.ctx, ast.Load) and node.attr in self.names:
            self.loads[node.attr].append((self.rel, node.lineno))
        self.generic_visit(node)


names = set(HIST_RETIRED_CONSUMERS) | LIVE_SHARED_KEEP
counter = LoadCounter(names)
for path in py_files():
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        continue
    counter.rel = path.relative_to(ROOT).as_posix()
    counter.visit(tree)

seed_status = {}
for sym in HIST_RETIRED_CONSUMERS:
    defs = counter.defs.get(sym, [])
    loads = counter.loads.get(sym, [])
    prod_loads = [x for x in loads if not x[0].startswith("tests/")]
    test_loads = [x for x in loads if x[0].startswith("tests/")]
    seed_status[sym] = {
        "defs": defs,
        "prod_loads": prod_loads,
        "test_loads": test_loads,
        "still_defined": bool(defs),
        "prod_consumers": len(prod_loads),
        "test_only_consumers": len(test_loads) > 0 and len(prod_loads) == 0,
    }

(OUT / "r10b-seed-status.json").write_text(
    json.dumps(seed_status, ensure_ascii=False, indent=2), encoding="utf-8"
)


# ---------- 3) GameContent *_prompt fields + load_text_asset bindings ----------
content_py = ROOT / "ming_sim" / "content.py"
content_src = content_py.read_text(encoding="utf-8")
content_tree = ast.parse(content_src)

prompt_fields: list[str] = []
for node in content_tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "GameContent":
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.target.id.endswith("_prompt"):
                    prompt_fields.append(item.target.id)
            if isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name) and t.id.endswith("_prompt"):
                        prompt_fields.append(t.id)

# load bindings: look for load_text_asset("prompts/...") and assignment to fields
load_map: dict[str, str] = {}
for m in re.finditer(
    r"(?:self\.)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:self\.)?load_text_asset\(\s*[\"']([^\"']+)[\"']",
    content_src,
):
    load_map[m.group(1)] = m.group(2)
for m in re.finditer(
    r"load_text_asset\(\s*[\"']([^\"']+)[\"']\s*\)",
    content_src,
):
    pass  # captured via assign above

# Also dataclass field list from load() body
load_fn = None
for node in content_tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "GameContent":
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "load":
                load_fn = item

# Attribute / getattr consumers of each *_prompt outside content.py
prompt_consumers: dict[str, dict] = {}
for field in sorted(set(prompt_fields) | set(load_map) | {"rescript_draft_prompt", "scene_agent_prompt", "faction_metrics"}):
    attr_hits = []
    getattr_hits = []
    for path in py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == "ming_sim/content.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        class V(ast.NodeVisitor):
            def visit_Attribute(self, node: ast.Attribute):
                if isinstance(node.ctx, ast.Load) and node.attr == field:
                    attr_hits.append((rel, node.lineno))
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == field:
                        getattr_hits.append((rel, node.lineno))
                self.generic_visit(node)

        V().visit(tree)
    prompt_consumers[field] = {
        "loaded_as": load_map.get(field),
        "attr": attr_hits,
        "getattr": getattr_hits,
        "prod_attr": [x for x in attr_hits if not x[0].startswith("tests/")],
        "prod_getattr": [x for x in getattr_hits if not x[0].startswith("tests/")],
        "test_attr": [x for x in attr_hits if x[0].startswith("tests/")],
        "test_getattr": [x for x in getattr_hits if x[0].startswith("tests/")],
    }

(OUT / "r10b-prompt-bindings.json").write_text(
    json.dumps(
        {"fields": sorted(set(prompt_fields)), "load_map": load_map, "consumers": prompt_consumers},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)


# ---------- 4) content/prompts/*.md LOADED vs UNLOADED ----------
prompts_dir = ROOT / "content" / "prompts"
prompt_files = sorted(p.name for p in prompts_dir.glob("*.md")) if prompts_dir.exists() else []
loaded_stems = set()
for asset in load_map.values():
    # asset like prompts/foo.md
    base = Path(asset).name
    loaded_stems.add(base)

# also any other load_text_asset("prompts/...")
for m in re.finditer(r"[\"']prompts/([^\"']+\.md)[\"']", content_src):
    loaded_stems.add(m.group(1))
# getattr/other loaders in repo
for path in py_files():
    if not is_prod(path):
        continue
    txt = path.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"[\"'](?:content/)?prompts/([^\"']+\.md)[\"']", txt):
        loaded_stems.add(m.group(1))

prompt_assets = []
for name in prompt_files:
    status = "LOADED" if name in loaded_stems else "UNLOADED"
    # py word-boundary refs
    refs = []
    stem = name[:-3]
    for path in py_files():
        rel = path.relative_to(ROOT).as_posix()
        txt = path.read_text(encoding="utf-8", errors="replace")
        if re.search(rf"\b{re.escape(stem)}\b|{re.escape(name)}", txt):
            refs.append(rel)
    prompt_assets.append(
        {
            "file": f"content/prompts/{name}",
            "status": status,
            "py_refs": refs,
            "prod_refs": [r for r in refs if not r.startswith("tests/")],
            "test_refs": [r for r in refs if r.startswith("tests/")],
        }
    )

(OUT / "r10b-prompt-assets.json").write_text(
    json.dumps(prompt_assets, ensure_ascii=False, indent=2), encoding="utf-8"
)


# ---------- 5) ALL tests: module-level helpers / fixtures with AST Load==0 ----------
# Full-repo: every tests/**/*.py — not limited to one file.
dead_fixtures = []
for path in sorted(p for p in py_files() if is_test(p)):
    rel = path.relative_to(ROOT).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        continue
    # module-level FunctionDef / Assign names that look like helpers/fixtures
    defined: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # skip test_* and fixtures named with pytest.fixture decorator still counted;
            # we want helpers that are never loaded
            defined[node.name] = node.lineno
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper() or (isinstance(t, ast.Name) and t.id.startswith("_")):
                    if isinstance(t, ast.Name):
                        defined[t.id] = node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.startswith("_") or node.target.id.isupper():
                defined[node.target.id] = node.lineno

    # count Loads of each defined name inside this module
    loads: dict[str, int] = defaultdict(int)
    hanging_parametrize = []

    class LV(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name):
            if isinstance(node.ctx, ast.Load) and node.id in defined:
                loads[node.id] += 1

        def visit_FunctionDef(self, node: ast.FunctionDef):
            # hanging parametrize: decorator pytest.mark.parametrize on non-test_
            for dec in node.decorator_list:
                call = dec
                if isinstance(dec, ast.Attribute):
                    continue
                if isinstance(dec, ast.Call):
                    func = dec.func
                    is_param = (
                        (isinstance(func, ast.Attribute) and func.attr == "parametrize")
                        or (isinstance(func, ast.Name) and func.id == "parametrize")
                    )
                    if is_param and not node.name.startswith("test_"):
                        hanging_parametrize.append(
                            {"func": node.name, "lineno": node.lineno, "file": rel}
                        )
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self.visit_FunctionDef(node)  # type: ignore

    LV().visit(tree)

    for name, lineno in defined.items():
        # skip actual tests
        if name.startswith("test_"):
            continue
        # skip pytest fixtures that are injected by name into tests (Load count may be 0)
        # We still report Load==0; semantic pass later decides.
        if loads.get(name, 0) == 0:
            dead_fixtures.append(
                {
                    "file": rel,
                    "name": name,
                    "lineno": lineno,
                    "loads": 0,
                    "kind": "module_def_load0",
                }
            )
    for hp in hanging_parametrize:
        dead_fixtures.append(
            {
                "file": hp["file"],
                "name": hp["func"],
                "lineno": hp["lineno"],
                "loads": "hanging_parametrize",
                "kind": "hanging_parametrize",
            }
        )

(OUT / "r10b-dead-fixtures.json").write_text(
    json.dumps(dead_fixtures, ensure_ascii=False, indent=2), encoding="utf-8"
)


# ---------- 6) Tests protecting retired candidate-title guess-bind / old simulator board ----------
RETIRED_BEHAVIOR_PATTERNS = [
    r"without_event_id",
    r"candidate_snapshot",
    r"bind.*candidate.*title",
    r"guess.?bind",
    r"标题猜绑",
    r"candidate_events",
    r"season_simulator",
    r"build_period_report",
    r"previous_turn_summary",
    r"format_region_changes",
    r"format_army_changes",
    r"turn_region_summary",
    r"turn_army_summary",
    r"execution_distortion_weight",
    r"build_secret_covert_effect_briefs",
    r"has_player_visible_rejection",
    r"generate_rescript_draft",
    r"create_rescript_draft_agent",
    r"select_triage_actor",
    r"pending_promulgation_verdicts",
    r"rescript_draft_prompt",
    r"event_selector",
]

retired_behavior_tests = []
for path in sorted(p for p in py_files() if is_test(p)):
    rel = path.relative_to(ROOT).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        continue
    src = path.read_text(encoding="utf-8", errors="replace")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            # function source segment
            try:
                seg = ast.get_source_segment(src, node) or ""
            except Exception:
                seg = ""
            hits = [p for p in RETIRED_BEHAVIOR_PATTERNS if re.search(p, node.name, re.I) or re.search(p, seg, re.I)]
            if hits:
                retired_behavior_tests.append(
                    {
                        "file": rel,
                        "test": node.name,
                        "lineno": node.lineno,
                        "pattern_hits": hits,
                    }
                )

(OUT / "r10b-retired-behavior-tests.json").write_text(
    json.dumps(retired_behavior_tests, ensure_ascii=False, indent=2), encoding="utf-8"
)


# ---------- 7) Mutual dead tree: defs whose only callers are other defs with zero prod consumers ----------
# BFS from still-defined seeds with test_only or zero consumers
still = [s for s, st in seed_status.items() if st["still_defined"]]
# Also include prompt fields with zero prod consumers
for field, info in prompt_consumers.items():
    if not info["prod_attr"] and not info["prod_getattr"] and (info["test_attr"] or info["test_getattr"] or info["loaded_as"]):
        if field not in still:
            still.append(field)

(OUT / "r10b-still-defined-or-orphan-bindings.json").write_text(
    json.dumps(
        {
            "still_defined_seeds": still,
            "prompt_orphan_candidates": [
                f
                for f, info in prompt_consumers.items()
                if not info["prod_attr"] and not info["prod_getattr"]
            ],
            "unloaded_prompts": [p for p in prompt_assets if p["status"] == "UNLOADED"],
            "dead_fixture_count": len(dead_fixtures),
            "retired_behavior_test_count": len(retired_behavior_tests),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

print("F2-R10-1 enum done")
print("hist_hits", len(hist_hits))
print("still_defined_seeds", len(still))
print("prompt_fields", len(prompt_fields))
print("unloaded_prompts", sum(1 for p in prompt_assets if p["status"] == "UNLOADED"))
print("dead_fixtures", len(dead_fixtures))
print("retired_behavior_tests", len(retired_behavior_tests))
print("OUT", OUT)
