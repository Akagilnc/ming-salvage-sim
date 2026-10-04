#!/usr/bin/env python3
"""#1889 K1/K2 minimal enumerator — AST + csv + git only. Evidence for humans; no auto-delete.

Universe: git ls-files '*.py' (and *.sql for DROP/CREATE). Baselines: fa0175a26, ddf53881f → HEAD.
Writes (with --write): docs/1889-k1-k2-{deleted-entries,members,k2-hits}.tsv
"""
from __future__ import annotations

import argparse
import ast
import csv
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ("fa0175a26", "ddf53881f")
FIELDS = (
    "lane", "member", "location", "class", "detail",
    "create_exists", "ref_count", "retired_consumer", "suggested", "reason",
)

SQL_DROP_RE = re.compile(
    r"\bDROP\s+(?:TABLE|VIEW|INDEX|TRIGGER)\s+(?:IF\s+EXISTS\s+)?([`\"']?\w+[`\"']?)",
    re.I,
)
SQL_CREATE_RE = re.compile(
    r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW|INDEX|TRIGGER)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([`\"']?\w+[`\"']?)",
    re.I,
)


def git_ls(*globs: str) -> list[str]:
    cmd = ["git", "ls-files", *globs] if globs else ["git", "ls-files"]
    return subprocess.check_output(cmd, cwd=ROOT, text=True).splitlines()


def parse_py(rel: str) -> ast.AST | None:
    try:
        return ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def snip(rel: str, lineno: int) -> str:
    lines = (ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()[:160]
    return ""


def deleted_defs(base: str) -> dict[str, list[str]]:
    diff = subprocess.check_output(
        ["git", "diff", "-U0", f"{base}..HEAD", "--"],
        cwd=ROOT, text=True, errors="replace",
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


def is_persistence(path: str) -> bool:
    return path == "ming_sim/db.py" or (
        path.startswith("ming_sim/entities/") and path.endswith("store.py")
    )


def collect_methods(py_files: list[str]) -> list[tuple[str, str, str, int, int, str]]:
    """(kind, class, name, lineno, end, file)"""
    out = []
    for rel in py_files:
        tree = parse_py(rel)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name == "GameDB":
                kind = "gamedb"
            elif node.name.endswith("Store"):
                kind = "store"
            else:
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(item, "end_lineno", item.lineno) or item.lineno
                    out.append((kind, node.name, item.name, item.lineno, end, rel))
    return out


def collect_attr_refs(py_files: list[str]) -> dict[str, list[tuple[str, int]]]:
    refs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for rel in py_files:
        tree = parse_py(rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                refs[node.attr].append((rel, getattr(node, "lineno", 0)))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"hasattr", "getattr", "setattr", "delattr"}
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                refs[node.args[1].value].append((rel, getattr(node, "lineno", 0)))
    return refs


def external_ref_count(
    name: str, def_file: str, start: int, end: int,
    refs: dict[str, list[tuple[str, int]]],
) -> tuple[int, list[str]]:
    hits = []
    for rel, ln in refs.get(name, []):
        if rel == def_file and start <= ln <= end:
            continue
        hits.append(f"{rel}:{ln}")
    files = sorted({h.rsplit(":", 1)[0] for h in hits})
    return len(hits), files[:5]


def identical_assigns(py_files: list[str]) -> list[dict]:
    """Module-level Name assigns with identical AST dump across ≥2 files."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rel in py_files:
        # Production dual-source risk only; scripts/spike/docs harness mirrors are out of K1 scope.
        if not rel.startswith("ming_sim/"):
            continue
        tree = parse_py(rel)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            name = tgt.id
            if not (name.isupper() or name.startswith("_")):
                continue
            groups[(name, ast.dump(node.value))].append(f"{rel}:{node.lineno}")
    rows = []
    for (name, dump), locs in sorted(groups.items()):
        files = {l.split(":")[0] for l in locs}
        if len(files) < 2:
            continue
        # Same-name schema column tuples differ by table — keep only truly identical dumps (already keyed).
        # Flag exact-identical reference rules / shared values for human review.
        rows.append({
            "lane": "K1",
            "member": f"CONST_DUP:{name}",
            "location": ";".join(locs),
            "class": "duplicate_const",
            "detail": dump[:200],
            "create_exists": "n/a",
            "ref_count": str(len(locs)),
            "retired_consumer": "n/a",
            "suggested": "review",
            "reason": "identical assign across files — human: merge if same rule; keep if different-table schema",
        })
    return rows


def sql_old_layout(files: list[str]) -> list[dict]:
    creates: set[str] = set()
    texts: list[tuple[str, str]] = []
    for rel in files:
        if not (rel.endswith(".sql") or rel.endswith(".py")):
            continue
        if rel.startswith("tests/") or rel.startswith("docs/"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        texts.append((rel, text))
        for m in SQL_CREATE_RE.finditer(text):
            creates.add(m.group(1).strip("`\"'"))
    rows = []
    for rel, text in texts:
        for i, line in enumerate(text.splitlines(), 1):
            for m in SQL_DROP_RE.finditer(line):
                name = m.group(1).strip("`\"'")
                rows.append({
                    "lane": "K1",
                    "member": f"SQL_DROP:{name}",
                    "location": f"{rel}:{i}",
                    "class": "sql_drop",
                    "detail": line.strip()[:160],
                    "create_exists": "1" if name in creates else "0",
                    "ref_count": "n/a",
                    "retired_consumer": "n/a",
                    "suggested": "review" if name not in creates else "keep",
                    "reason": "DROP without CREATE peer" if name not in creates else "DROP with CREATE peer",
                })
    return rows


def k2_hits(test_files: list[str], truly_deleted: set[str]) -> list[dict]:
    rows = []
    for rel in test_files:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            loc = f"{rel}:{i}"
            if "assert not hasattr" in s:
                rows.append(_k2(loc, "hasattr_absence", s, "review",
                                "assert not hasattr — absence/retirement proof risk"))
            if any(tok in s for tok in ("__code__", "co_names", "co_consts", "getsource")):
                rows.append(_k2(loc, "bytecode_source", s, "review",
                                "bytecode/source probe — internal shape risk"))
            if "_meta" in s and "assert" in s and ("not in" in s or "not any" in s):
                rows.append(_k2(loc, "meta_absence", s, "review",
                                "_meta key absence assert — review live vs retired-shape"))
            if re.search(r"""['\"]standalone['\"]""", s) and "assert" in s:
                rows.append(_k2(loc, "standalone_assert", s, "review",
                                "standalone token in assert — retirement-shape risk"))
            for name in truly_deleted:
                if len(name) < 8 or name not in s:
                    continue
                if any(k in s for k in ("monkeypatch", "setattr", f".{name}", f"'{name}'", f'"{name}"')):
                    kind = "patch_deleted" if "setattr" in s or "monkeypatch" in s else "call_deleted"
                    rows.append(_k2(
                        loc, kind, s, "review",
                        f"test references deleted persistence entry '{name}'",
                        retired=name,
                    ))
    return rows


def _k2(loc, cls, detail, suggested, reason, retired=""):
    return {
        "lane": "K2",
        "member": f"{cls}:{retired or '-'}",
        "location": loc,
        "class": cls,
        "detail": detail[:160],
        "create_exists": "n/a",
        "ref_count": "n/a",
        "retired_consumer": retired,
        "suggested": suggested,
        "reason": reason,
    }


def write_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    all_py = [p for p in git_ls() if p.endswith(".py")]
    sqlish = [p for p in git_ls() if p.endswith((".py", ".sql"))]
    test_py = [p for p in all_py if p.startswith("tests/") or "/tests/" in p]
    # include web vitest paths if any tracked
    web_tests = [p for p in git_ls() if re.search(r"\.(test|spec)\.(ts|tsx|js)$", p)]

    methods = collect_methods(all_py)
    refs = collect_attr_refs(all_py)
    defined = {m[2] for m in methods}

    del_union: dict[str, list[str]] = defaultdict(list)
    for base in BASELINES:
        for name, files in deleted_defs(base).items():
            del_union[name].extend(files)

    deleted_rows = []
    truly_deleted: set[str] = set()
    for name, files in sorted(del_union.items()):
        pers = [f for f in files if is_persistence(f)]
        flag = "1" if pers else "0"
        if pers and name not in defined:
            truly_deleted.add(name)
        deleted_rows.append({
            "lane": "K1",
            "member": name,
            "location": ";".join(sorted(set(files))[:8]),
            "class": "deleted_def",
            "detail": f"persistence={flag}; truly_gone={int(name not in defined and bool(pers))}",
            "create_exists": "n/a",
            "ref_count": "n/a",
            "retired_consumer": ",".join(sorted(set(pers))[:4]),
            "suggested": "n/a",
            "reason": "git deleted def",
            # remap to deleted-entries schema below
            "_baseline": "union",
            "_prod": ",".join(sorted({f for f in files if not f.startswith("tests/")})[:6]) or "-",
            "_test": ",".join(sorted({f for f in files if f.startswith("tests/")})[:6]) or "-",
            "_pers": flag,
        })

    member_rows = []
    for kind, cls, name, start, end, rel in methods:
        nrefs, sample = external_ref_count(name, rel, start, end, refs)
        if nrefs == 0 and not name.startswith("_"):
            if kind == "store":
                mclass = "unref_public_store"
                reason = "zero Attribute refs — human duty review (not auto-delete)"
                suggested = "review"
            else:
                mclass = "unref_gamedb"
                reason = "zero Attribute refs — human duty review"
                suggested = "review"
        else:
            mclass = "referenced"
            reason = f"refs={nrefs}; sample={','.join(sample)}"
            suggested = "keep"
        member_rows.append({
            "lane": "K1",
            "member": f"{cls}.{name}",
            "location": f"{rel}:{start}",
            "class": mclass,
            "detail": f"kind={kind}; refs={nrefs}",
            "create_exists": "n/a",
            "ref_count": str(nrefs),
            "retired_consumer": "",
            "suggested": suggested,
            "reason": reason,
        })

    member_rows.extend(sql_old_layout(sqlish))
    member_rows.extend(identical_assigns(all_py))

    k2_rows = k2_hits(test_py, truly_deleted)
    for wt in web_tests:
        k2_rows.append(_k2(wt, "web_test_file", "tracked web test", "review",
                           "web test present — include in K2 universe; not Python AST"))

    print(f"git-tracked py={len(all_py)} tests={len(test_py)} web_tests={len(web_tests)}")
    print(f"Store/GameDB methods={len(methods)}")
    print(f"deleted union names={len(del_union)} truly_deleted_persistence={len(truly_deleted)}")
    print(f"K1 members={len(member_rows)} (unref_store="
          f"{sum(1 for r in member_rows if r['class']=='unref_public_store')} "
          f"unref_gamedb={sum(1 for r in member_rows if r['class']=='unref_gamedb')} "
          f"dup_const={sum(1 for r in member_rows if r['class']=='duplicate_const')})")
    print(f"K2 hits={len(k2_rows)}")

    if args.write:
        # deleted-entries uses a slightly different header historically
        del_path = ROOT / "docs/1889-k1-k2-deleted-entries.tsv"
        with del_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "baseline", "name", "prod_files", "test_files",
                    "persistence_consumer", "in_fa0175a26", "in_ddf53881f",
                ],
                delimiter="\t",
                lineterminator="\n",
            )
            w.writeheader()
            fa = deleted_defs(BASELINES[0])
            dd = deleted_defs(BASELINES[1])
            for name in sorted(del_union):
                files = del_union[name]
                prod = [f for f in sorted(set(files)) if not f.startswith("tests/")]
                test = [f for f in sorted(set(files)) if f.startswith("tests/")]
                pers = any(is_persistence(f) for f in files)
                w.writerow({
                    "baseline": "union",
                    "name": name,
                    "prod_files": ",".join(prod[:8]) or "-",
                    "test_files": ",".join(test[:8]) or "-",
                    "persistence_consumer": "1" if pers else "0",
                    "in_fa0175a26": "1" if name in fa else "0",
                    "in_ddf53881f": "1" if name in dd else "0",
                })
        write_tsv(ROOT / "docs/1889-k1-k2-members.tsv", member_rows)
        write_tsv(ROOT / "docs/1889-k1-k2-k2-hits.tsv", k2_rows)
        print("wrote docs/1889-k1-k2-*.tsv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
