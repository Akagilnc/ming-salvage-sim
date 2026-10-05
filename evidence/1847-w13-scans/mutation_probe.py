#!/usr/bin/env python3
"""#1847 w13-corr temporary mutation probe (NOT a permanent test).

Replay:
  cd <worktree>
  export MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \\
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w13-scans/mutation_probe.py | tee evidence/1847-w13-scans/mutation-probe.out

Evidence rules:
  - Real GameDB.seed_static_data + apply_fixed_period_flows / compute_budget_lines entries.
  - Old fiscal selector + calc_province_fiscal / compute_budget_lines legacy branch
    extracted from git parent 80aea7cd3 (pre-w13), not handwritten stubs.
  - Old army-pay cutover selector extracted from the same parent (unmarked → False).
  - Process-local monkeypatch only; restores modules; cleans temp dirs.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

for k in ("AGY", "CODEX", "CLAUDE", "CURSOR", "KIMI", "GROK", "PI"):
    os.environ[f"MING_SIM_{k}_BIN"] = "/usr/bin/false"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[2]
OLD_BASE = "80aea7cd3"  # pre-w13 fiscal_engine still present
sys_path_note = str(ROOT)

import sys

sys.path.insert(0, sys_path_note)

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.flows import apply_fixed_period_flows, compute_budget_lines
import ming_sim.flows as flows_mod
import ming_sim.issues as issues_mod
import ming_sim.db as db_mod


def log(msg: str) -> None:
    print(msg)


def git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{OLD_BASE}:{path}"],
        cwd=ROOT,
        text=True,
    )


def extract_function(src: str, name: str) -> str:
    """Extract a top-level `def name` block by indentation (module body)."""
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        raise RuntimeError(f"def {name} not found in extracted source")
    start = m.start()
    lines = src[start:].splitlines(True)
    body = [lines[0]]
    for line in lines[1:]:
        if line.startswith("def ") or line.startswith("class "):
            break
        body.append(line)
    return "".join(body)


def extract_method(src: str, name: str) -> str:
    """Extract an indented class method `def name` (4-space class body)."""
    m = re.search(rf"^    def {re.escape(name)}\(", src, re.M)
    if not m:
        raise RuntimeError(f"method {name} not found")
    start = m.start()
    lines = src[start:].splitlines(True)
    body = [lines[0]]
    for line in lines[1:]:
        if re.match(r"^    def ", line) or re.match(r"^class ", line):
            break
        body.append(line)
    # dedent 4 spaces for exec into module then bind as method
    dedented = []
    for line in body:
        if line.startswith("    "):
            dedented.append(line[4:])
        else:
            dedented.append(line)
    return "".join(dedented)


def fresh_db(prefix: str):
    td = Path(tempfile.mkdtemp(prefix=prefix))
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    path = td / "probe.db"
    db = GameDB(str(path), content)
    db.seed_static_data()
    state = db.load_state()
    return db, state, td, content


def income_names(budget) -> list[str]:
    return [str(r.get("name") or "") for r in budget["国库"]["income"]]


def flow_categories(flows) -> set[str]:
    return {str(f.get("category") or "") for f in flows}


def main() -> int:
    failed = False
    tmp = Path(tempfile.mkdtemp(prefix="1847-w13-mut-"))
    log(f"TMP {tmp}")
    log(f"OLD_BASE {OLD_BASE}")

    # --- CURRENT: properly seeded new save ---
    db, state, td, content = fresh_db("1847-w13-cur-")
    budget = compute_budget_lines(db, state)
    names = income_names(budget)
    log(f"CURRENT_fresh_budget_income {names[:6]}")
    has_qiyun_budget = "起运" in names
    gk_before = int(state.metrics.get("国库", 0) or 0)
    flows = apply_fixed_period_flows(db, state)
    cats = flow_categories(flows)
    log(
        f"CURRENT_fresh_has_qiyun_budget {has_qiyun_budget} "
        f"has_qiyun_flow {'起运' in cats} "
        f"has_legacy_tax_line {'田赋辽饷盐商' in cats or '田赋辽饷盐商' in names}"
    )
    log(f"CURRENT_fresh_gk_delta {int(state.metrics.get('国库', 0)) - gk_before}")
    # army pay selector gone
    log(
        f"CURRENT_army_pay_selector_absent "
        f"{not hasattr(GameDB, 'is_army_pay_source_cutover_enabled')}"
    )
    log(
        f"CURRENT_fiscal_engine_absent "
        f"{not hasattr(GameDB, 'fiscal_engine') and not hasattr(GameDB, 'is_substrate_hub_fiscal_engine_enabled')}"
    )
    # strip markers and reopen — must still hub (no fiscal selector; spine already seeded)
    marked = tmp / "strip.db"
    shutil.copy2(db.path, marked)
    db.conn.close()
    import sqlite3

    conn = sqlite3.connect(marked)
    conn.execute(
        "DELETE FROM fiscal_config WHERE key IN ('__fiscal_engine','__army_pay_source_cutover')"
    )
    conn.commit()
    conn.close()
    db2 = GameDB(str(marked), content)
    state2 = db2.load_state()
    budget2 = compute_budget_lines(db2, state2)
    names2 = income_names(budget2)
    flows2 = apply_fixed_period_flows(db2, state2)
    cats2 = flow_categories(flows2)
    log(f"CURRENT_unmarked_budget_income {names2[:6]}")
    log(
        f"CURRENT_unmarked_has_qiyun_budget {'起运' in names2} "
        f"has_qiyun_flow {'起运' in cats2} "
        f"has_legacy_tax_line {'田赋辽饷盐商' in cats2 or '田赋辽饷盐商' in names2}"
    )
    db2.conn.close()
    shutil.rmtree(td)

    if not (has_qiyun_budget and "起运" in cats and "起运" in names2 and "起运" in cats2):
        failed = True
        log("FAIL CURRENT hub path missing 起运 in budget and/or flows")

    # --- MUTATION A: restore real old fiscal_engine + compute_budget_lines + calc_province_fiscal ---
    old_db_src = git_show("ming_sim/db.py")
    old_flows_src = git_show("ming_sim/flows.py")
    fiscal_engine_src = extract_method(old_db_src, "fiscal_engine")
    is_hub_src = extract_method(old_db_src, "is_substrate_hub_fiscal_engine_enabled")
    # Constants used by fiscal_engine
    ns = {
        "_FISCAL_ENGINE_KEY": "__fiscal_engine",
        "_FISCAL_ENGINE_LEGACY": 0,
        "_FISCAL_ENGINE_SUBSTRATE_HUB": 1,
    }
    exec(fiscal_engine_src, ns)
    exec(is_hub_src, ns)
    GameDB.fiscal_engine = ns["fiscal_engine"]  # type: ignore[method-assign,assignment]
    GameDB.is_substrate_hub_fiscal_engine_enabled = ns[  # type: ignore[method-assign,assignment]
        "is_substrate_hub_fiscal_engine_enabled"
    ]

    # Extract real old helpers + calc_province_fiscal + compute_budget_lines from parent.
    # Contiguous defs from _province_efficiency through calc_province_fiscal, then compute.
    def extract_between(src: str, start_name: str, end_name: str) -> str:
        m0 = re.search(rf"^def {re.escape(start_name)}\(", src, re.M)
        m1 = re.search(rf"^def {re.escape(end_name)}\(", src, re.M)
        if not m0 or not m1 or m1.start() <= m0.start():
            raise RuntimeError(f"cannot slice {start_name}..{end_name}")
        # include end_name full function
        rest = src[m1.start():]
        lines = rest.splitlines(True)
        body = [lines[0]]
        for line in lines[1:]:
            if line.startswith("def ") or line.startswith("class "):
                break
            body.append(line)
        return src[m0.start():m1.start()] + "".join(body)

    legacy_block = extract_between(old_flows_src, "_province_efficiency", "calc_province_fiscal")
    compute_src = extract_function(old_flows_src, "compute_budget_lines")
    exec_ns = dict(flows_mod.__dict__)
    # Constants referenced by the extracted legacy helpers (from OLD_BASE flows.py head).
    exec_ns.setdefault("_HUANG_TIAN_RENT_PER_WAN_MU", 0.57)
    exec_ns.setdefault(
        "_FIXED_FLOW_NUMERIC_FIELDS",
        ("huang_tian", "liao_xiang", "salt_tax", "commerce_tax", "corruption"),
    )
    exec(legacy_block, exec_ns)
    exec(compute_src, exec_ns)
    for name in (
        "_province_efficiency",
        "_fixed_flow_scalars_are_numeric",
        "_load_region_fiscal_for_fixed_flow",
        "calc_province_fiscal",
    ):
        setattr(flows_mod, name, exec_ns[name])
    old_compute = exec_ns["compute_budget_lines"]
    real_compute = flows_mod.compute_budget_lines
    flows_mod.compute_budget_lines = old_compute

    db3, state3, td3, _ = fresh_db("1847-w13-mut-fiscal-")
    # delete fiscal marker so old selector returns legacy
    db3.conn.execute("DELETE FROM fiscal_config WHERE key='__fiscal_engine'")
    db3.conn.commit()
    log(
        f"MUTATED_selector_unmarked {db3.fiscal_engine()} "
        f"hub_enabled {db3.is_substrate_hub_fiscal_engine_enabled()}"
    )
    b_mut = flows_mod.compute_budget_lines(db3, state3)
    mut_names = income_names(b_mut)
    log(f"MUTATED_budget_income {mut_names[:3]}")
    mut_legacy = "田赋辽饷盐商" in mut_names
    mut_hub = "起运" in mut_names
    log(f"MUTATED_legacy_tax_line {mut_legacy} MUTATED_has_qiyun {mut_hub}")
    if not (db3.fiscal_engine() == "legacy" and mut_legacy and not mut_hub):
        failed = True
        log("FAIL mutated fiscal path did not take legacy budget")
    db3.conn.close()
    shutil.rmtree(td3)

    # restore compute
    flows_mod.compute_budget_lines = real_compute
    if hasattr(flows_mod, "calc_province_fiscal"):
        delattr(flows_mod, "calc_province_fiscal")
    del GameDB.fiscal_engine
    del GameDB.is_substrate_hub_fiscal_engine_enabled

    # --- MUTATION B: restore real old army-pay cutover selector (unmarked → False) ---
    army_sel_src = extract_method(old_db_src, "is_army_pay_source_cutover_enabled")
    army_ns = {"_ARMY_PAY_SOURCE_CUTOVER_KEY": "__army_pay_source_cutover"}
    exec(army_sel_src, army_ns)
    GameDB.is_army_pay_source_cutover_enabled = army_ns[  # type: ignore[method-assign,assignment]
        "is_army_pay_source_cutover_enabled"
    ]
    db4, state4, td4, _ = fresh_db("1847-w13-mut-army-")
    # fresh seed still writes marker in OLD code; CURRENT seed no longer writes it.
    # Delete marker to simulate old unmarked save under restored selector.
    db4.conn.execute("DELETE FROM fiscal_config WHERE key='__army_pay_source_cutover'")
    db4.conn.commit()
    enabled = db4.is_army_pay_source_cutover_enabled()
    log(f"MUTATED_army_pay_selector_unmarked_enabled {enabled}")
    if enabled is not False:
        failed = True
        log("FAIL mutated army-pay selector should be False when unmarked")
    # CURRENT after restore-delete: method must be gone again
    del GameDB.is_army_pay_source_cutover_enabled
    log(
        f"RESTORED_army_pay_selector_absent "
        f"{not hasattr(GameDB, 'is_army_pay_source_cutover_enabled')}"
    )
    db4.conn.close()
    shutil.rmtree(td4)

    # --- Identity wrapper (population) still absent; process-local identity shape red ---
    log(
        f"CURRENT_wrapper_absent "
        f"{not hasattr(issues_mod, '_content_population_effect_for_save')}"
    )

    def _content_population_effect_for_save(db, effect):
        return effect

    issues_mod._content_population_effect_for_save = _content_population_effect_for_save
    eff = {"x": 1}
    log(
        f"MUTATED_wrapper_identity "
        f"{issues_mod._content_population_effect_for_save(None, eff) is eff}"
    )
    del issues_mod._content_population_effect_for_save
    log(
        f"RESTORED_wrapper_absent "
        f"{not hasattr(issues_mod, '_content_population_effect_for_save')}"
    )

    shutil.rmtree(tmp)
    log(f"TMP_CLEANED {not tmp.exists()}")
    log("MUTATION_PROBE_DONE " + ("PASS" if not failed else "FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
