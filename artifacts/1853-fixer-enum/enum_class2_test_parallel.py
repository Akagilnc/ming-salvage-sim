#!/usr/bin/env python3
"""#1853 Class2 / TEST-PARALLEL full-repo AST enumerator.

Predicate (class definition, not narrowed):
  Test doubles that re-implement persistence / rollback behavior under test,
  or dedicated tests that keep feeding a retired lightweight / connless interface.

Not limited to sample method names (fail_chat_turn / append_chat_message / …).
Boundary: negative admission, single-writer, queue, concurrency contracts KEEP;
collaboration stubs that only inject faults / observe gates without copying
rollback business rules KEEP.
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
}

# Persistence / rollback surface names used by GameDB chat turn lifecycle.
# Enumerating defs of these in tests is the primary Class2 candidate set;
# classification then decides copy vs collab.
PERSIST_ROLLBACK_METHODS = {
    "fail_chat_turn",
    "append_chat_message",
    "persist_minister_reply",
    "capture_chat_rollback_snapshot",
    "create_chat_turn",
    "undo_chat_turn",
    "rollback_chat_turn",
    "restore_chat_rollback_snapshot",
    "delete_chat_message",
    "update_chat_message",
}

# Markers that historically signalled retired lightweight / connless paths.
RETIRED_MARKERS = (
    "lightweight",
    "without_durable_identity",
    "connless",
    "_noop_atomic",
    "_atomic_connless",
)


def _skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR_PARTS:
        return True
    rel = path.relative_to(ROOT).as_posix()
    for prefix in ("web/node_modules/", "web/dist/", ".venv/", "archive/"):
        if rel.startswith(prefix):
            return True
    return False


def walk_test_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if _skip(p):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel:
            out.append(p)
    return sorted(out)


def snippet_at(src: str, lineno: int) -> str:
    lines = src.splitlines()
    if 0 < lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def method_body_copies_rollback(fn: ast.FunctionDef, src: str) -> bool:
    """True if body mutates message lists / deletes last user msg / empties atomic."""
    text = ast.get_source_segment(src, fn) or ""
    needles = (
        "msgs[:-1]",
        "messages[:-1]",
        "messages = msgs",
        "del self.messages",
        "pop()",
        "ROLLBACK",
        "rollback(",
        "DELETE FROM chat_messages",
        "delete from chat_messages",
    )
    return any(n in text for n in needles)


def classify_method_def(
    *,
    rel: str,
    name: str,
    fn: ast.FunctionDef,
    src: str,
    class_name: str | None,
) -> str:
    body_copy = method_body_copies_rollback(fn, src)
    if body_copy:
        return "COPY_ROLLBACK_LOGIC"
    # Known KEEP collaborator files from prior disposition + boundary
    if rel.endswith("test_chat_stream_failpaths_393.py"):
        return "KEEP_negative_gate_contract"
    if rel.endswith("test_menu_lifecycle_drain_396.py"):
        return "KEEP_queue_concurrency_contract"
    if rel.endswith("test_web_chat_serialization_393.py"):
        return "KEEP_concurrency_collaborator"
    if name == "_noop_atomic" or name == "_atomic_connless_test_shell_compat":
        if "conftest" in rel:
            return "KEEP_fixture_for_queue_concurrency_collaborators"
        return "REVIEW_noop_atomic"
    # bare list_pending_actions-only helper
    if class_name == "Db" and name not in PERSIST_ROLLBACK_METHODS:
        return "KEEP_other"
    if name in PERSIST_ROLLBACK_METHODS:
        return "REVIEW_persist_method_stub"
    return "OTHER_TEST_DEF"


def classify_retired_test(name: str, src_seg: str) -> str:
    low = (name + "\n" + src_seg).lower()
    if "lightweight" in low or "without_durable_identity" in low:
        return "RETIRED_LIGHTWEIGHT_TEST"
    if "connless" in low:
        return "CONNLESS_FIXTURE_USE"
    return "OTHER"


def scan_file(path: Path) -> list[dict]:
    rel = path.relative_to(ROOT).as_posix()
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        return [
            {
                "file": rel,
                "line": 0,
                "label": "PARSE_ERROR",
                "disposition": str(exc),
                "kind": "parse",
                "name": "",
                "snippet": str(exc),
            }
        ]
    rows: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.class_stack.append(node.name)
            defined = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            persist_hit = sorted(set(defined) & PERSIST_ROLLBACK_METHODS)
            lname = node.name.lower()
            looks_stub = any(x in lname for x in ("db", "stub", "fake", "recording", "double"))
            if persist_hit:
                copies = []
                for n in node.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in PERSIST_ROLLBACK_METHODS:
                        if method_body_copies_rollback(n, src):
                            copies.append(n.name)
                if copies:
                    disp = "COPY_ROLLBACK_LOGIC"
                elif any(
                    rel.endswith(x)
                    for x in (
                        "test_chat_stream_failpaths_393.py",
                        "test_menu_lifecycle_drain_396.py",
                        "test_web_chat_serialization_393.py",
                    )
                ):
                    disp = {
                        "test_chat_stream_failpaths_393.py": "KEEP_negative_gate_contract",
                        "test_menu_lifecycle_drain_396.py": "KEEP_queue_concurrency_contract",
                        "test_web_chat_serialization_393.py": "KEEP_concurrency_collaborator",
                    }[rel.rsplit("/", 1)[-1]]
                else:
                    disp = "REVIEW_persist_stub_class"
                rows.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "label": "db_stub_class",
                        "disposition": disp,
                        "kind": "class",
                        "name": f"{node.name}{{{','.join(persist_hit)}}}",
                        "snippet": snippet_at(src, node.lineno),
                    }
                )
            elif looks_stub:
                # FakeAgent / FakeSession / etc. — not persistence-copy unless methods above
                rows.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "label": "db_stub_class",
                        "disposition": "KEEP_non_persist_collaborator_or_agent_double",
                        "kind": "class",
                        "name": node.name,
                        "snippet": snippet_at(src, node.lineno),
                    }
                )
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_fn(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_fn(node)
            self.generic_visit(node)

        def _visit_fn(self, node: ast.AST) -> None:
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            name = node.name
            cls = self.class_stack[-1] if self.class_stack else None
            snip = snippet_at(src, node.lineno)

            if name in PERSIST_ROLLBACK_METHODS or name in {
                "_noop_atomic",
                "_atomic_connless_test_shell_compat",
            }:
                disp = classify_method_def(
                    rel=rel, name=name, fn=node, src=src, class_name=cls  # type: ignore[arg-type]
                )
                label = (
                    "copy_rollback_logic"
                    if disp == "COPY_ROLLBACK_LOGIC"
                    else (
                        "lightweight_or_noop_atomic"
                        if name.startswith("_") or "atomic" in name
                        else f"reimpl_{name}"
                    )
                )
                rows.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "label": label,
                        "disposition": disp,
                        "kind": "def",
                        "name": name if cls is None else f"{cls}.{name}",
                        "snippet": snip,
                    }
                )

            # retired lightweight dedicated tests
            if name.startswith("test_") and any(m in name.lower() for m in ("lightweight", "without_durable")):
                disp = classify_retired_test(name, ast.get_source_segment(src, node) or "")
                rows.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "label": "retired_lightweight_test",
                        "disposition": disp,
                        "kind": "test",
                        "name": name,
                        "snippet": snip,
                    }
                )

            # decorator / fixture markers
            for dec in node.decorator_list:
                seg = ast.get_source_segment(src, dec) or ""
                if "_atomic_connless_test_shell_compat" in seg or "connless" in seg.lower():
                    rows.append(
                        {
                            "file": rel,
                            "line": node.lineno,
                            "label": "lightweight_or_noop_atomic",
                            "disposition": "KEEP_queue_concurrency_contract"
                            if "drain" in rel or "serialization" in rel or "menu_lifecycle" in rel
                            else "CONNLESS_FIXTURE_USE",
                            "kind": "fixture_use",
                            "name": name,
                            "snippet": snip,
                        }
                    )

        def visit_Assign(self, node: ast.Assign) -> None:
            seg = ast.get_source_segment(src, node) or ""
            if "msgs[:-1]" in seg or "messages = msgs[:-1]" in seg or "messages=msgs[:-1]" in seg.replace(" ", ""):
                rows.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "label": "copy_rollback_logic",
                        "disposition": "COPY_ROLLBACK_LOGIC",
                        "kind": "assign",
                        "name": "",
                        "snippet": snippet_at(src, node.lineno),
                    }
                )
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            seg = ast.get_source_segment(src, node) or ""
            # monkeypatch atomic → noop
            if "monkeypatch" in seg and ("atomic" in seg) and (
                "_noop_atomic" in seg or "noop" in seg.lower()
            ):
                rows.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "label": "lightweight_or_noop_atomic",
                        "disposition": "REVIEW_noop_atomic",
                        "kind": "monkeypatch",
                        "name": "",
                        "snippet": snippet_at(src, node.lineno),
                    }
                )
            self.generic_visit(node)

    Visitor().visit(tree)

    # Textual sweep for retired markers not caught by AST name alone
    for i, line in enumerate(src.splitlines(), 1):
        low = line.lower()
        if any(m in low for m in RETIRED_MARKERS):
            # skip if already captured at this line
            if any(r["line"] == i for r in rows):
                continue
            if line.strip().startswith("#") and "connless" in low:
                rows.append(
                    {
                        "file": rel,
                        "line": i,
                        "label": "lightweight_or_noop_atomic",
                        "disposition": "KEEP_queue_concurrency_contract"
                        if any(x in rel for x in ("drain", "serialization", "menu_lifecycle", "conftest"))
                        else "REVIEW_marker_comment",
                        "kind": "comment_or_text",
                        "name": "",
                        "snippet": line.strip(),
                    }
                )
            elif "def test_" in low and ("lightweight" in low or "without_durable" in low):
                rows.append(
                    {
                        "file": rel,
                        "line": i,
                        "label": "retired_lightweight_test",
                        "disposition": "RETIRED_LIGHTWEIGHT_TEST",
                        "kind": "test_text",
                        "name": "",
                        "snippet": line.strip(),
                    }
                )
    return rows


def main() -> int:
    all_rows: list[dict] = []
    for path in walk_test_files():
        all_rows.extend(scan_file(path))

    fields = ["file", "line", "label", "disposition", "kind", "name", "snippet"]
    raw_path = OUT_DIR / "class2-raw.tsv"
    post_path = OUT_DIR / "class2-post.tsv"
    with raw_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in sorted(all_rows, key=lambda r: (r["file"], r["line"], r["label"])):
            w.writerow(row)

    # Post: everything, with disposition (already classified)
    with post_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in sorted(all_rows, key=lambda r: (r["file"], r["line"], r["label"])):
            w.writerow(row)

    from collections import Counter

    c = Counter(r["disposition"] for r in all_rows)
    bad = [
        r
        for r in all_rows
        if r["disposition"]
        in {
            "COPY_ROLLBACK_LOGIC",
            "RETIRED_LIGHTWEIGHT_TEST",
            "REVIEW_noop_atomic",
            "REVIEW_persist_method_stub",
            "REVIEW_stub_class",
        }
    ]
    print(f"test_files_scanned={len(walk_test_files())}")
    print(f"raw_hits={len(all_rows)}")
    print("disposition_counts:")
    for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k}: {v}")
    print(f"needs_attention={len(bad)}")
    for r in bad:
        print(
            f"  {r['file']}:{r['line']} [{r['disposition']}] {r['label']} {r['name']} :: {r['snippet'][:120]}"
        )
    print(f"wrote {raw_path.relative_to(ROOT)}")
    print(f"wrote {post_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
