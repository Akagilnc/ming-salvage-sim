#!/usr/bin/env python3
"""#1853 Class1 / J8-R2 full-repo AST enumerator.

Predicate (class definition, not narrowed):
  After a successfully constructed GameDB is in hand, any hasattr / getattr(..., default)
  / callable soft-probe / AttributeError-compat branch that treats a GameDB-required
  attribute or method as optional (skip / empty / fallback) is IN_CLASS.

Not limited to:
  - symbol names literally equal to ``db`` / ``game_db``
  - production-only directories (whole tree scanned; tests/evidence/artifacts classified)
  - the sample attrs named in the judge evidence

KEEP (boundary from final verdict):
  - game_db is None / getattr(game, \"db\", None)  — no DB handed in
  - missing business rows / empty lists — real empty states
  - error_pack diagnostic getattr(db, \"path\", None)
  - runtime scratch attr cleanup (flows hasattr(db, attr); issues batch scratch)
"""
from __future__ import annotations

import ast
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent

SKIP_DIR_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "archive",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    "web/dist",
}

# GameDB construction-time / public surface treated as required capability once
# a live GameDB instance is held. Built from class body + known instance attrs.
GAMEDB_INSTANCE_ATTRS = {
    "path",
    "content",
    "conn",
    "llm_config",
}


def _skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR_PARTS:
        return True
    rel = path.relative_to(ROOT).as_posix()
    for prefix in ("web/node_modules/", "web/dist/", ".venv/", "archive/"):
        if rel.startswith(prefix):
            return True
    return False


def collect_gamedb_api(db_path: Path) -> set[str]:
    tree = ast.parse(db_path.read_text(encoding="utf-8"), filename=str(db_path))
    apis: set[str] = set(GAMEDB_INSTANCE_ATTRS)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "GameDB":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    apis.add(item.name)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            apis.add(t.id)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    apis.add(item.target.id)
    return apis


def expr_text(node: ast.AST, src: str) -> str:
    try:
        return ast.get_source_segment(src, node) or ast.unparse(node)
    except Exception:
        return type(node).__name__


def const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def walk_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if _skip(p):
            continue
        out.append(p)
    return sorted(out)


def looks_like_gamedb_receiver(obj: str, *, rel: str) -> bool:
    """Receiver may be any alias of a live GameDB — not limited to the name ``db``.

    Positive: db / game_db / gamedb / store / database / *.db (except agent.db) /
    self inside ming_sim/db.py.
    Negative: session/game/content/event/… holders that share attr names like content.
    """
    o = "".join(obj.split())
    ol = o.lower()

    if ol == "self" and rel == "ming_sim/db.py":
        return True

    # agent.db is Agno's session store, not GameDB
    if ol == "agent.db" or ol.endswith(".agent.db") or (ol.startswith("agent") and ol.endswith(".db")):
        return False

    positive_bares = {"db", "game_db", "gamedb", "store", "database"}
    if ol in positive_bares:
        return True
    if any(ol.endswith("." + b) for b in positive_bares):
        return True
    if "game_db" in ol:
        return True

    # Non-GameDB holders (including their dotted forms)
    negative_hints = (
        "session",
        "game.",
        "content.",
        "event",
        "character",
        "agent",
        "exc",
        "result",
        "state",
        "output",
        "run_output",
        "run_src",
        "prepared",
        "model",
        "cfg",
        "args",
        "residual",
        "init_exc",
        "rebuild_exc",
        "region",
        "army",
        "ticket",
        "fact",
    )
    bare = ol.split(".")[-1]
    if bare in positive_bares:
        return True
    if ol in {
        "game",
        "session",
        "content",
        "event",
        "character",
        "agent",
        "exc",
        "result",
        "state",
        "output",
        "m",
        "ch",
        "ev",
        "cfg",
        "args",
        "model",
        "prepared",
        "residual",
    }:
        return False
    if any(h in ol for h in negative_hints) and bare not in positive_bares:
        return False
    return False


def classify_hit(
    *,
    rel: str,
    kind: str,
    obj: str,
    attr: str | None,
    default: str,
    in_api: bool,
    snippet: str,
) -> str:
    """Semantic class label. Raw TSV keeps every hit; this only labels."""
    if kind == "attributeerror_compat":
        if rel.startswith(("tests/", "evidence/", "artifacts/", "docs/", "scripts/")):
            return "OUT_OF_PROD_ENUM_ONLY"
        return "ATTRERROR_COMPAT_REVIEW"

    if rel == "ming_sim/error_pack.py" and attr == "path" and looks_like_gamedb_receiver(obj, rel=rel):
        return "KEEP_error_pack_diag"
    if rel == "ming_sim/flows.py" and "hasattr(db, attr)" in snippet:
        return "KEEP_runtime_scratch"
    if attr and attr.startswith("_batch_"):
        return "NOT_GAMEDB_API_or_scratch"
    if attr and attr.startswith("_") and attr not in GAMEDB_INSTANCE_ATTRS:
        return "NOT_GAMEDB_API_or_scratch"
    if attr == "db" and kind in {"getattr", "hasattr"}:
        return "KEEP_unhanded_db_or_optional_holder"

    receiver = looks_like_gamedb_receiver(obj, rel=rel)
    if not receiver:
        return "NOT_GAMEDB_RECEIVER"
    if not in_api:
        return "NOT_GAMEDB_API_or_scratch"
    if rel.startswith(("tests/", "evidence/", "artifacts/", "docs/", "scripts/")):
        return "OUT_OF_PROD_ENUM_ONLY"

    if kind in {"getattr", "hasattr", "callable_probe"}:
        if kind == "getattr" and default == "":
            return "DIRECT_GETATTR_NO_DEFAULT"
        return "IN_CLASS_J8R2"
    return "OTHER"


def try_body_touches_gamedb_capability(try_node: ast.Try, src: str, apis: set[str]) -> list[str]:
    """Return API names referenced as db.<api> / <alias>.<api> inside a try body."""
    hits: list[str] = []
    for sub in ast.walk(try_node):
        if isinstance(sub, ast.Attribute):
            attr = sub.attr
            base = expr_text(sub.value, src)
            if looks_like_gamedb_receiver(base, rel="") and (
                attr in apis or attr == "conn" or attr in GAMEDB_INSTANCE_ATTRS
            ):
                hits.append(attr)
            # also bare db.conn style when receiver positive with empty rel
            ol = "".join(base.split()).lower()
            if ol in {"db", "game_db", "gamedb", "store", "database", "self"} or ol.endswith(".db"):
                if attr in apis or attr in GAMEDB_INSTANCE_ATTRS or attr == "conn":
                    hits.append(attr)
    return sorted(set(hits))


def scan_file(path: Path, apis: set[str], src: str, tree: ast.AST) -> list[dict]:
    rows: list[dict] = []
    rel = path.relative_to(ROOT).as_posix()
    lines = src.splitlines()

    def add(kind: str, node: ast.AST, obj: str, attr: str | None, default: str = "", extra_class: str | None = None) -> None:
        lineno = getattr(node, "lineno", 0) or 0
        snippet = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        in_api = bool(attr and attr in apis)
        label = extra_class or classify_hit(
            rel=rel, kind=kind, obj=obj, attr=attr, default=default, in_api=in_api, snippet=snippet
        )
        if rel == "ming_sim/flows.py" and kind == "hasattr" and "hasattr(db, attr)" in snippet:
            label = "KEEP_runtime_scratch"
        rows.append(
            {
                "file": rel,
                "line": lineno,
                "class": label,
                "kind": kind,
                "obj": obj,
                "attr": attr or "",
                "default": default,
                "in_api": "1" if in_api else "0",
                "snippet": snippet,
            }
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            if fname == "hasattr" and len(node.args) >= 2:
                obj = expr_text(node.args[0], src)
                attr = const_str(node.args[1])
                add("hasattr", node, obj, attr)
            elif fname == "getattr" and len(node.args) >= 2:
                obj = expr_text(node.args[0], src)
                attr = const_str(node.args[1])
                default = expr_text(node.args[2], src) if len(node.args) >= 3 else ""
                for kw in node.keywords:
                    if kw.arg in {None, "default"} or kw.arg == "default":
                        default = expr_text(kw.value, src)
                add("getattr", node, obj, attr, default)
            elif fname == "callable" and len(node.args) == 1:
                inner = node.args[0]
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "getattr"
                    and len(inner.args) >= 2
                ):
                    obj = expr_text(inner.args[0], src)
                    attr = const_str(inner.args[1])
                    default = expr_text(inner.args[2], src) if len(inner.args) >= 3 else ""
                    add("callable_probe", node, obj, attr, default)
                else:
                    obj = expr_text(inner, src)
                    add("callable", node, obj, None)
        elif isinstance(node, ast.Try):
            for handler in node.handlers:
                typ = handler.type
                names: list[str] = []
                if isinstance(typ, ast.Name):
                    names = [typ.id]
                elif isinstance(typ, ast.Tuple):
                    names = [elt.id for elt in typ.elts if isinstance(elt, ast.Name)]
                if "AttributeError" not in names:
                    continue
                touched = try_body_touches_gamedb_capability(node, src, apis)
                if touched and not rel.startswith(("tests/", "evidence/", "artifacts/", "docs/", "scripts/")):
                    # Capability-missing AttributeError compat on GameDB API → IN_CLASS
                    add(
                        "attributeerror_compat",
                        handler,
                        "db_try",
                        ",".join(touched),
                        "",
                        extra_class="IN_CLASS_J8R2",
                    )
                else:
                    add("attributeerror_compat", handler, "except", ",".join(touched) if touched else None)

    return rows


def main() -> int:
    apis = collect_gamedb_api(ROOT / "ming_sim" / "db.py")
    (OUT_DIR / "gamedb_api_names.txt").write_text(
        "\n".join(sorted(apis)) + "\n", encoding="utf-8"
    )

    raw_rows: list[dict] = []
    for path in walk_files():
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raw_rows.append(
                {
                    "file": path.relative_to(ROOT).as_posix(),
                    "line": 0,
                    "class": "PARSE_ERROR",
                    "kind": "parse",
                    "obj": "",
                    "attr": "",
                    "default": "",
                    "in_api": "0",
                    "snippet": str(exc),
                }
            )
            continue
        raw_rows.extend(scan_file(path, apis, src, tree))

    fields = ["file", "line", "class", "kind", "obj", "attr", "default", "in_api", "snippet"]
    raw_path = OUT_DIR / "class1-raw.tsv"
    post_path = OUT_DIR / "class1-post.tsv"
    with raw_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in raw_rows:
            w.writerow(row)

    # Post members of interest: IN_CLASS + KEEP boundary + any unresolved AttributeError
    interesting = {
        "IN_CLASS_J8R2",
        "KEEP_error_pack_diag",
        "KEEP_runtime_scratch",
        "KEEP_unhanded_db_or_optional_holder",
        "NOT_GAMEDB_API_or_scratch",
        "attributeerror_compat",  # kind may differ; class OTHER for bare excepts
    }
    post_rows = [
        r
        for r in raw_rows
        if r["class"] in interesting
        or r["kind"] == "attributeerror_compat"
        or (r["in_api"] == "1" and r["kind"] in {"getattr", "hasattr", "callable_probe"})
    ]
    with post_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in post_rows:
            w.writerow(row)

    # Summary to stdout
    from collections import Counter

    c = Counter(r["class"] for r in raw_rows)
    in_class = [r for r in raw_rows if r["class"] == "IN_CLASS_J8R2"]
    print(f"files_scanned={len(walk_files())}")
    print(f"gamedb_api_count={len(apis)}")
    print(f"raw_hits={len(raw_rows)}")
    print("class_counts:")
    for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k}: {v}")
    print(f"IN_CLASS_J8R2={len(in_class)}")
    for r in in_class:
        print(f"  {r['file']}:{r['line']} {r['kind']} {r['obj']}.{r['attr']} default={r['default']!r}")
    print(f"wrote {raw_path.relative_to(ROOT)}")
    print(f"wrote {post_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
