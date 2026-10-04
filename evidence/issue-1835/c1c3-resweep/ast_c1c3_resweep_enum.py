#!/usr/bin/env python3
"""#1835 w5 C1/C3 evidence investigation (NOT a test; no production constraints).

Single-pass AST index over the worktree. For each FunctionDef/AsyncFunctionDef in
situation_drift / displaced_population / issues:

1. list same-name defs in other modules
2. list resolved consumers (prod vs test)
3. never treat unresolved Attribute same-name hits as accurate consumers
4. flag uncertain Attribute hits; flag zero-prod / forwarder-shell candidates

Outputs under this directory:
  enumeration-resolved.txt
  cross-name-candidates.txt
  review-flags.txt
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

TARGETS = (
    "ming_sim/situation_drift.py",
    "ming_sim/displaced_population.py",
    "ming_sim/issues.py",
)
SKIP_PARTS = {"__pycache__", ".venv", "venv", "node_modules", ".git"}


@dataclass
class DefInfo:
    file: str
    lineno: int
    name: str
    nested: bool
    parent: str | None
    forwarder: bool = False
    forwarder_target: str | None = None


@dataclass
class RefHit:
    file: str
    lineno: int
    kind: str
    status: str
    detail: str = ""
    # for resolved ImportFrom / Name: which module the symbol came from
    from_module: str | None = None
    # for Attribute: resolved base module or None
    attr_base: str | None = None
    # local name used (may differ with asname)
    local_name: str | None = None


def is_test_path(rel: str) -> bool:
    return rel.startswith("tests/") or rel.startswith("test_")


def module_qualname_from_path(rel: str) -> str | None:
    if not rel.endswith(".py"):
        return None
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def resolve_from_module(node: ast.ImportFrom, file_mod: str) -> str | None:
    if node.module is None and not node.level:
        return None
    if node.level:
        pkg_parts = file_mod.split(".") if file_mod else []
        base = pkg_parts[: max(0, len(pkg_parts) - node.level)]
        if node.module:
            return ".".join(base + [node.module])
        return ".".join(base) if base else None
    return node.module


def attr_chain_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


_BUILTIN_CALLEES = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
# ensure common ones even if __builtins__ is a module
_BUILTIN_CALLEES |= {
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable",
    "chr", "classmethod", "compile", "complex", "delattr", "dict", "dir", "divmod",
    "enumerate", "eval", "exec", "filter", "float", "format", "frozenset", "getattr",
    "globals", "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max", "memoryview", "min",
    "next", "object", "oct", "open", "ord", "pow", "print", "property", "range",
    "repr", "reversed", "round", "set", "setattr", "slice", "sorted", "staticmethod",
    "str", "sum", "super", "tuple", "type", "vars", "zip",
}


def detect_forwarder(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, str | None]:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    body = [s for s in body if not isinstance(s, ast.Pass)]
    if not body:
        return False, None
    imports = [s for s in body if isinstance(s, (ast.Import, ast.ImportFrom))]
    rest = [s for s in body if not isinstance(s, (ast.Import, ast.ImportFrom))]
    if len(rest) != 1 or not isinstance(rest[0], ast.Return):
        return False, None
    ret = rest[0].value
    if not isinstance(ret, ast.Call):
        return False, None
    callee = ret.func
    if isinstance(callee, ast.Name):
        target = callee.id
    elif isinstance(callee, ast.Attribute):
        target = attr_chain_name(callee)
    else:
        target = None
    if not target:
        return False, None
    leaf = target.split(".")[-1]
    if leaf == fn.name:
        return False, target
    # builtins / trivial constructors are not forwarding shells
    if leaf in _BUILTIN_CALLEES and "." not in target:
        return False, target
    # forwarder shell: lazy import(s) + single return-call to another symbol,
    # or single-stmt wrapper with no other logic
    if imports and len(rest) == 1:
        return True, target
    if not imports and len(body) == 1:
        return True, target
    return False, target


def iter_py_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py") if not any(part in SKIP_PARTS for part in p.parts)
    )


@dataclass
class FileScan:
    rel: str
    module_aliases: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    imported_modules: set[str] = field(default_factory=set)
    # symbol_name -> list of ImportFrom hits (original imported name)
    import_from_hits: list[RefHit] = field(default_factory=list)
    # Name Load hits by local id
    name_loads: list[RefHit] = field(default_factory=list)
    # Attribute Load hits by attr
    attr_loads: list[RefHit] = field(default_factory=list)


def resolve_attr_base(node: ast.AST, scan: FileScan) -> str | None:
    if isinstance(node, ast.Name):
        aliases = scan.module_aliases.get(node.id)
        return max(aliases, key=len) if aliases else None
    chain = attr_chain_name(node)
    if chain and chain in scan.imported_modules:
        return chain
    if isinstance(node, ast.Attribute):
        base = resolve_attr_base(node.value, scan)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def scan_file(path: Path, root: Path, interesting: set[str]) -> tuple[FileScan | None, list[DefInfo]]:
    rel = str(path.relative_to(root))
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except Exception:
        return None, []
    scan = FileScan(rel=rel)
    file_mod = module_qualname_from_path(rel) or ""
    defs: list[DefInfo] = []
    # local aliases of interesting symbols (asname) — also watch Name Loads of these
    alias_locals: set[str] = set()
    # local -> original interesting symbol
    alias_to_orig: dict[str, str] = {}

    # Pass 1: imports anywhere (incl. nested) — needed before Attribute resolve
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                scan.imported_modules.add(alias.name)
                if alias.asname:
                    scan.module_aliases[alias.asname].add(alias.name)
                else:
                    scan.module_aliases[alias.name.split(".")[0]].add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = resolve_from_module(node, file_mod)
            if not mod:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                scan.module_aliases[local].add(f"{mod}.{alias.name}")
                scan.imported_modules.add(f"{mod}.{alias.name}")
                if alias.name in interesting:
                    detail = f"from {mod} import {alias.name}"
                    if alias.asname:
                        detail += f" as {alias.asname}"
                    scan.import_from_hits.append(
                        RefHit(
                            rel,
                            node.lineno,
                            "import_from",
                            "raw",
                            detail,
                            from_module=mod,
                            local_name=local,
                        )
                    )
                    if alias.asname:
                        alias_locals.add(alias.asname)
                        alias_to_orig[alias.asname] = alias.name

    # Pass 2: defs + Name/Attribute loads
    def walk_defs(node: ast.AST, parent: str | None, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fwd, fwd_t = detect_forwarder(child)
                defs.append(
                    DefInfo(
                        file=rel,
                        lineno=child.lineno,
                        name=child.name,
                        nested=depth > 0,
                        parent=parent,
                        forwarder=fwd,
                        forwarder_target=fwd_t,
                    )
                )
                walk_defs(child, child.name, depth + 1)
            elif isinstance(child, ast.ClassDef):
                walk_defs(child, child.name, depth + 1)
            else:
                walk_defs(child, parent, depth)

    walk_defs(tree, None, 0)

    name_watch = interesting | alias_locals
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in name_watch:
            # always key Name loads by the original target symbol when aliased
            orig = alias_to_orig.get(node.id, node.id)
            scan.name_loads.append(
                RefHit(
                    rel,
                    node.lineno,
                    "Name",
                    "raw",
                    "Name Load",
                    local_name=orig,
                )
            )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and node.attr in interesting
        ):
            base = resolve_attr_base(node.value, scan)
            detail = (
                f"Attribute {base}.{node.attr}"
                if base
                else f"unresolved Attribute *.{node.attr}"
            )
            scan.attr_loads.append(
                RefHit(
                    rel,
                    node.lineno,
                    "Attribute",
                    "resolved" if base else "uncertain",
                    detail,
                    attr_base=base,
                    local_name=node.attr,
                )
            )
    return scan, defs


def dedup(hits: list[RefHit]) -> list[RefHit]:
    seen: set[tuple] = set()
    out: list[RefHit] = []
    for h in hits:
        key = (h.file, h.lineno, h.kind, h.status, h.detail, h.from_module, h.attr_base, h.local_name)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def main() -> int:
    # First pass: discover target def names (need target files only)
    target_names: set[str] = set()
    bootstrap_defs: list[DefInfo] = []
    for rel in TARGETS:
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)

        def walk(node: ast.AST, parent: str | None, depth: int) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fwd, fwd_t = detect_forwarder(child)
                    info = DefInfo(
                        file=rel,
                        lineno=child.lineno,
                        name=child.name,
                        nested=depth > 0,
                        parent=parent,
                        forwarder=fwd,
                        forwarder_target=fwd_t,
                    )
                    bootstrap_defs.append(info)
                    target_names.add(child.name)
                    walk(child, child.name, depth + 1)
                elif isinstance(child, ast.ClassDef):
                    walk(child, child.name, depth + 1)
                else:
                    walk(child, parent, depth)

        walk(tree, None, 0)

    py_files = iter_py_files(ROOT)
    all_defs: list[DefInfo] = []
    scans: list[FileScan] = []
    for p in py_files:
        scan, defs = scan_file(p, ROOT, target_names)
        if scan is None:
            continue
        if not scan.rel.startswith("evidence/"):
            scans.append(scan)
        all_defs.extend(defs)

    by_name: dict[str, list[DefInfo]] = defaultdict(list)
    for d in all_defs:
        by_name[d.name].append(d)

    # Prefer bootstrap target defs (same as full scan of those files)
    target_defs = [d for d in all_defs if d.file in TARGETS]
    target_defs.sort(key=lambda d: (TARGETS.index(d.file), d.lineno))

    # Pre-index hits by symbol name for fast join
    imports_by_sym: dict[str, list[RefHit]] = defaultdict(list)
    names_by_sym: dict[str, list[RefHit]] = defaultdict(list)
    attrs_by_sym: dict[str, list[RefHit]] = defaultdict(list)
    for scan in scans:
        for h in scan.import_from_hits:
            # imported name is in detail; use local vs original
            # store under original symbol from detail
            # Recover original: from_module set; local_name is local
            # We need original imported name — parse from detail or store better.
            # Re-derive: detail "from M import NAME" / "as"
            imports_by_sym[h.local_name or ""].append(h)  # temporary; fix below
        for h in scan.name_loads:
            names_by_sym[h.local_name or ""].append(h)
        for h in scan.attr_loads:
            attrs_by_sym[h.local_name or ""].append(h)

    # Fix import index: key by original imported name (from detail)
    imports_by_orig: dict[str, list[RefHit]] = defaultdict(list)
    for scan in scans:
        for h in scan.import_from_hits:
            # detail: from MOD import ORIG [as LOCAL]
            parts = h.detail.split()
            # ['from', MOD, 'import', ORIG] optional as LOCAL
            orig = parts[3] if len(parts) >= 4 else (h.local_name or "")
            imports_by_orig[orig].append(h)

    reports = []
    for d in target_defs:
        tmod = module_qualname_from_path(d.file) or ""
        cross = [
            (x.file, x.lineno, x.nested, x.parent)
            for x in by_name[d.name]
            if x.file != d.file
        ]
        resolved: list[RefHit] = []
        uncertain: list[RefHit] = []
        same: list[RefHit] = []

        # ImportFrom of this name from target module
        local_aliases: dict[str, set[str]] = defaultdict(set)  # file -> locals
        for h in imports_by_orig.get(d.name, []):
            if h.from_module == tmod:
                hit = RefHit(h.file, h.lineno, "import_from", "resolved", h.detail, from_module=tmod)
                resolved.append(hit)
                if h.local_name:
                    local_aliases[h.file].add(h.local_name)

        # Name loads (keyed by original symbol; asname locals remapped in scan)
        for h in names_by_sym.get(d.name, []):
            if h.file == d.file:
                same.append(
                    RefHit(h.file, h.lineno, "Name", "same_module", "Name Load in defining file")
                )
            elif local_aliases.get(h.file):
                # file imported this symbol from target (any local alias)
                resolved.append(
                    RefHit(
                        h.file,
                        h.lineno,
                        "Name",
                        "resolved",
                        "Name Load after ImportFrom target",
                        from_module=tmod,
                    )
                )

        # Attributes
        for h in attrs_by_sym.get(d.name, []):
            if h.attr_base == tmod:
                resolved.append(
                    RefHit(
                        h.file,
                        h.lineno,
                        "Attribute",
                        "resolved",
                        f"Attribute {tmod}.{d.name}",
                        attr_base=tmod,
                    )
                )
            else:
                uncertain.append(
                    RefHit(
                        h.file,
                        h.lineno,
                        "Attribute",
                        "uncertain",
                        h.detail,
                        attr_base=h.attr_base,
                    )
                )

        resolved, uncertain, same = dedup(resolved), dedup(uncertain), dedup(same)
        reports.append(
            {
                "d": d,
                "cross": cross,
                "resolved_prod": [h for h in resolved if not is_test_path(h.file)],
                "resolved_test": [h for h in resolved if is_test_path(h.file)],
                "uncertain": uncertain,
                "same": same,
            }
        )

    enum_path = OUT / "enumeration-resolved.txt"
    lines = [
        "RESOLVED full-class enum (FunctionDef/AsyncFunctionDef top+nested)",
        f"ROOT={ROOT}",
        f"TARGETS={list(TARGETS)}",
        f"PY_FILES={len(py_files)} SCANS={len(scans)} ALL_DEFS={len(all_defs)} TARGET_DEFS={len(target_defs)}",
        "CONSUMER_RULE: resolved = ImportFrom(target_module.symbol) + Name after that import "
        "+ Attribute whose base resolves to target_module; "
        "same_module = Name Load in defining file; "
        "uncertain = Attribute same-name whose base does NOT resolve to target_module "
        "(NOT counted as accurate consumer).",
        "",
    ]
    for r in reports:
        d: DefInfo = r["d"]
        lines.append(
            f"DEF {d.file}:{d.lineno} {d.name} nested={d.nested} parent={d.parent} "
            f"forwarder={d.forwarder}"
            + (f"→{d.forwarder_target}" if d.forwarder_target else "")
            + f" cross_defs={len(r['cross'])} "
            f"resolved_prod={len(r['resolved_prod'])} resolved_test={len(r['resolved_test'])} "
            f"same_module={len(r['same'])} uncertain={len(r['uncertain'])}"
        )
        if r["cross"]:
            for f, ln, nested, parent in r["cross"]:
                lines.append(f"  CROSS_DEF {f}:{ln} nested={nested} parent={parent}")
        else:
            lines.append("  CROSS_DEF (none)")
        for hit in r["same"][:25]:
            lines.append(f"  SAME {hit.file}:{hit.lineno} {hit.kind} {hit.detail}")
        if len(r["same"]) > 25:
            lines.append(f"  SAME ... +{len(r['same']) - 25} more")
        shown = 0
        for hit in r["resolved_prod"] + r["resolved_test"]:
            if shown >= 40:
                break
            bucket = "PROD" if not is_test_path(hit.file) else "TEST"
            lines.append(f"  RESOLVED_{bucket} {hit.file}:{hit.lineno} {hit.kind} {hit.detail}")
            shown += 1
        total_res = len(r["resolved_prod"]) + len(r["resolved_test"])
        if total_res > shown:
            lines.append(f"  RESOLVED ... +{total_res - shown} more")
        for hit in r["uncertain"][:20]:
            lines.append(f"  UNCERTAIN {hit.file}:{hit.lineno} {hit.kind} {hit.detail}")
        if len(r["uncertain"]) > 20:
            lines.append(f"  UNCERTAIN ... +{len(r['uncertain']) - 20} more")

    with_cross = sum(1 for r in reports if r["cross"])
    zero_prod_and_same = [
        r for r in reports if (not r["d"].nested) and not r["resolved_prod"] and not r["same"]
    ]
    forwarders = [r for r in reports if (not r["d"].nested) and r["d"].forwarder]
    lines += [
        "",
        "=== SUMMARY ===",
        f"TARGET_DEFS={len(target_defs)}",
        f"WITH_CROSS_MODULE_SAME_NAME={with_cross}",
        f"TOPLEVEL_FORWARDER_FLAG={len(forwarders)}",
        f"TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME={len(zero_prod_and_same)}",
        "TOPLEVEL_ZERO_RESOLVED_PROD_ONLY="
        f"{sum(1 for r in reports if (not r['d'].nested) and not r['resolved_prod'])}",
    ]
    enum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cross_path = OUT / "cross-name-candidates.txt"
    cl = [
        "CROSS-MODULE same-name for all TARGET defs (complete)",
        f"TARGET_DEFS={len(target_defs)}",
        "Each TARGET def lists all other-module FunctionDef/AsyncFunctionDef with the same name.",
        "",
    ]
    for r in reports:
        d = r["d"]
        cl.append(f"TARGET {d.file}:{d.lineno} {d.name} nested={d.nested}")
        if not r["cross"]:
            cl.append("  CROSS_DEF (none)")
        else:
            for f, ln, nested, parent in r["cross"]:
                cl.append(f"  CROSS_DEF {f}:{ln} nested={nested} parent={parent}")
    cl.append("")
    cl.append("=== INDEX: names with ≥1 CROSS_DEF ===")
    seen: set[str] = set()
    for r in reports:
        if not r["cross"] or r["d"].name in seen:
            continue
        seen.add(r["d"].name)
        cl.append(
            f"{r['d'].name} @ {r['d'].file}:{r['d'].lineno} -> "
            + "; ".join(f"{f}:{ln}" for f, ln, _, _ in r["cross"])
        )
    if not seen:
        cl.append("(none)")
    cross_path.write_text("\n".join(cl) + "\n", encoding="utf-8")

    side = OUT / "review-flags.txt"
    sf = ["ZERO_PROD_AND_SAME"]
    for r in zero_prod_and_same:
        sf.append(
            f"{r['d'].file}:{r['d'].lineno}:{r['d'].name}:"
            f"test={len(r['resolved_test'])}:unc={len(r['uncertain'])}"
        )
    sf.append("FORWARDERS")
    for r in forwarders:
        sf.append(
            f"{r['d'].file}:{r['d'].lineno}:{r['d'].name}->{r['d'].forwarder_target}:"
            f"prod={len(r['resolved_prod'])}:same={len(r['same'])}"
        )
    sf.append("CROSS_NAMES")
    seen = set()
    for r in reports:
        if not r["cross"] or r["d"].name in seen:
            continue
        seen.add(r["d"].name)
        sf.append(
            r["d"].name
            + "\t"
            + ";".join(
                [f"{r['d'].file}:{r['d'].lineno}"]
                + [f"{f}:{ln}" for f, ln, _, _ in r["cross"]]
            )
        )
    side.write_text("\n".join(sf) + "\n", encoding="utf-8")

    print(f"wrote {enum_path.relative_to(ROOT)}")
    print(f"wrote {cross_path.relative_to(ROOT)}")
    print(f"wrote {side.relative_to(ROOT)}")
    print(f"TARGET_DEFS={len(target_defs)} WITH_CROSS={with_cross}")
    print(f"TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME={len(zero_prod_and_same)}")
    print(f"TOPLEVEL_FORWARDERS={len(forwarders)}")
    print("\n--- C3 review: toplevel zero resolved_prod AND zero same_module ---")
    print("  (none)" if not zero_prod_and_same else "")
    for r in zero_prod_and_same:
        print(
            f"  {r['d'].file}:{r['d'].lineno} {r['d'].name} "
            f"resolved_test={len(r['resolved_test'])} uncertain={len(r['uncertain'])}"
        )
    print("\n--- C1/C3 review: toplevel forwarder flag ---")
    print("  (none)" if not forwarders else "")
    for r in forwarders:
        print(
            f"  {r['d'].file}:{r['d'].lineno} {r['d'].name} → {r['d'].forwarder_target} "
            f"resolved_prod={len(r['resolved_prod'])} same={len(r['same'])} "
            f"resolved_test={len(r['resolved_test'])}"
        )
    print("\n--- C1 review: cross-module same-name names ---")
    if not seen:
        print("  (none)")
    else:
        seen2: set[str] = set()
        for r in reports:
            if not r["cross"] or r["d"].name in seen2:
                continue
            seen2.add(r["d"].name)
            locs = [(r["d"].file, r["d"].lineno)] + [(f, ln) for f, ln, _, _ in r["cross"]]
            print(f"  {r['d'].name}: {locs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
