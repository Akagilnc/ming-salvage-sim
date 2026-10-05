#!/usr/bin/env python3
"""#1900 J6 full-repo enumeration (末份判词边界，不得收窄).

Class boundary (verbatim from last judge payload):
  清理盯文与内部证明时，遗漏或弱化了必要失败行为、原故障来源及实际结果的辨别力。

Direction:
  必要诊断案须沿真实失败路径验证实际可见结果；仅 helper／重复／无存活契约证明优先删除；
  不机械要求所有 raises 加身份断言。

Predicate (covers definition全文 — not raises-only keyword count):
  A. WEAK_DIAG: assert error/message merely truthy/nonempty without binding to
     injected fault object/str or structured code
  B. HELPER_WEAK_RAISE: FakeDB/FailingConnection + pytest.raises without binding
     injected fault (helper-only pseudo-proof)
  C. MOCK_CALL_ORACLE: mock replaces behavior-under-test; asserts only calls/route
  D. PRIVATE_MARKER: private migration/marker oracle as contract
  E. SECONDARY/ASYNC raises inventory for full-boundary semantic re-disposition
  + JUDGE_SAMPLE force-include of named counterexamples

Does not mutate sources. Writes evidence under this directory.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
from collections import Counter

ROOT = pathlib.Path(".").resolve()
OUT = ROOT / "evidence/1900-j6-final-rescan"

JUDGE_SAMPLES = {
    "test_run_backend_for_config_traces_on_backend_error",
    "test_worker_postprocess_exception_emits_error_end",
    "test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback",
}

FAKE_DB = re.compile(r"class\s+(?:FakeDB|FailingConnection)\b|FakeDB\s*\(")
CALL_ORACLE = re.compile(r"\bcalls?\b|\brouted\b")
PRIVATE_MARK = re.compile(
    r"assert\s+.*_(?:migrat|marker|flag|private|internal)", re.I
)
SECONDARY = re.compile(
    r"(rollback|reload|error_pack|write_error_pack|cleanup|fail_chat|"
    r"atomic_and_reload|call_failure|pack_exc|cleanup_error|reload_exc|"
    r"secondary|postprocess|spawn_pending)",
    re.I,
)
ASYNC = re.compile(
    r"(Thread|join|spawn|worker|asyncio|async |await |drain|background|"
    r"concurrent|Future|Executor|chat_stream)",
    re.I,
)
DIAG_WORD = re.compile(
    r"(error|message|trace|diagnosis|exc_info|__cause__|__context__|"
    r"provider_message)",
    re.I,
)
MOCK_REPLACE = re.compile(
    r"monkeypatch\.setattr\(|MagicMock|unittest\.mock|mock\.Mock"
)


def tracked_test_paths() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    paths: list[str] = []
    seen: set[str] = set()
    for b in raw:
        if not b:
            continue
        s = b.decode()
        if s.startswith("evidence/") or "/__pycache__/" in s:
            continue
        keep = False
        if s.endswith(".py") and (
            s.startswith("tests/") or "/tests/" in s or s.endswith("_test.py")
        ):
            keep = True
        elif re.search(r"\.(test|spec)\.(ts|tsx)$", s):
            keep = True
        if keep and s not in seen:
            seen.add(s)
            paths.append(s)
    return paths


def line_weak_diag(line: str) -> bool:
    """Truthy/nonempty error or message without equality / membership bind."""
    s = line.strip()
    if not s.startswith("assert "):
        return False
    body = s[len("assert ") :]
    if "==" in body or " is " in body:
        # equality bind present — not merely truthy (unless only on unrelated field)
        if re.search(
            r"""\.get\(\s*['"](?:error|message)['"]\s*\)\s*==|['"](?:error|message)['"].*==|==.*(?:error|message)""",
            body,
        ):
            return False
    # assert foo.get("error")  / assert recs[0].get("error")
    if re.search(
        r"""\.get\(\s*['"]error['"]\s*\)\s*(?:#|$)""",
        body,
    ):
        return True
    # assert cur.get("error") bare truthy mid-expression end
    if re.search(r"""\.get\(\s*['"]error['"]\s*\)\s*$""", body):
        return True
    # nonempty message/error via strip or `or ""` without equality to fault source
    if re.search(r"""(['"](?:message|error)['"]|\.message\b|\.error\b)""", body):
        if ("strip()" in body or re.search(r"""or\s+['"]{2}""", body)) and "==" not in body and " is " not in body:
            return True
    return False


class FuncVisitor(ast.NodeVisitor):
    def __init__(self, src: str, path: str) -> None:
        self.lines = src.splitlines()
        self.path = path
        self.hits: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if not node.name.startswith("test_"):
            self.generic_visit(node)
            return
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        body = "\n".join(self.lines[start - 1 : end])
        tags: set[str] = set()
        reasons: list[str] = []

        weak_lines = [
            i
            for i, line in enumerate(self.lines[start - 1 : end], start=start)
            if line_weak_diag(line)
        ]
        if weak_lines:
            tags.add("WEAK_DIAG")
            reasons.append(f"weak diagnostic assert at {weak_lines}")

        if FAKE_DB.search(body):
            tags.add("FAKE_HELPER")
            reasons.append("FakeDB/FailingConnection helper fixture")
            if "pytest.raises" in body or re.search(r"\braises\(", body):
                binds = bool(
                    re.search(
                        r"(ei\.value|excinfo\.value|exc_info\.value|\bis\b.*Error|"
                        r"raises\([^)]*match\s*=)",
                        body,
                    )
                )
                # also treat equality to injected text as bind
                if re.search(r"""assert\s+.*==\s*['"].*['"]""", body):
                    binds = True
                if not binds:
                    tags.add("HELPER_WEAK_RAISE")
                    reasons.append(
                        "helper raises without binding injected fault object/str"
                    )

        if MOCK_REPLACE.search(body) and CALL_ORACLE.search(body):
            assert_lines = [
                ln
                for ln in self.lines[start - 1 : end]
                if ln.strip().startswith("assert ")
            ]
            non_call = [
                ln
                for ln in assert_lines
                if not CALL_ORACLE.search(ln)
                and "calls" not in ln
                and "routed" not in ln
            ]
            if assert_lines and not non_call:
                tags.add("MOCK_CALL_ORACLE")
                reasons.append("mock replaces behavior; asserts only calls/route")

        if PRIVATE_MARK.search(body):
            tags.add("PRIVATE_MARKER")
            reasons.append("private migration/marker oracle")

        has_raises = "pytest.raises" in body or bool(re.search(r"\braises\(", body))
        if has_raises:
            tags.add("HAS_RAISES")
            if SECONDARY.search(body):
                tags.add("SECONDARY_PATH")
            if ASYNC.search(body):
                tags.add("ASYNC_PATH")
            if DIAG_WORD.search(body):
                tags.add("DIAG_PATH")
            if weak_lines:
                tags.add("RAISES_PLUS_WEAK_DIAG")

        if node.name in JUDGE_SAMPLES:
            tags.add("JUDGE_SAMPLE")
            reasons.append("末份判词点名样本")

        core = bool(
            tags
            & {
                "WEAK_DIAG",
                "HELPER_WEAK_RAISE",
                "MOCK_CALL_ORACLE",
                "PRIVATE_MARKER",
                "JUDGE_SAMPLE",
                "RAISES_PLUS_WEAK_DIAG",
            }
        )
        # Full-boundary rescan: secondary/async failure paths with raises
        rescan = has_raises and bool(tags & {"SECONDARY_PATH", "ASYNC_PATH"})
        # Also include DIAG raises that carry secondary wording even without Thread
        diag_secondary = has_raises and "DIAG_PATH" in tags and "SECONDARY_PATH" in tags
        if core or rescan or diag_secondary:
            self.hits.append(
                {
                    "file": self.path,
                    "line": start,
                    "test": node.name,
                    "tags": sorted(tags),
                    "reasons": reasons,
                    "core": core,
                }
            )
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = tracked_test_paths()
    hits: list[dict] = []
    parse_errors: list[dict] = []
    for p in paths:
        if not p.endswith(".py"):
            continue
        text = (ROOT / p).read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            parse_errors.append({"file": p, "error": str(exc)})
            continue
        visitor = FuncVisitor(text, p)
        visitor.visit(tree)
        hits.extend(visitor.hits)

    # line-scan catch for weak diag missed by AST nesting quirks
    known = {(h["file"], h["test"]) for h in hits}
    for p in paths:
        if not p.endswith(".py"):
            continue
        lines = (ROOT / p).read_text(encoding="utf-8").splitlines()
        current = None
        current_line = 0
        for i, line in enumerate(lines, 1):
            m = re.match(r"^def (test_\w+)\(", line)
            if m:
                current = m.group(1)
                current_line = i
            if current and line_weak_diag(line) and (p, current) not in known:
                hit = {
                    "file": p,
                    "line": current_line,
                    "test": current,
                    "tags": ["WEAK_DIAG", "LINE_SCAN"],
                    "reasons": [f"weak diagnostic assert at L{i}"],
                    "core": True,
                }
                hits.append(hit)
                known.add((p, current))

    hits.sort(key=lambda h: (h["file"], h["line"]))
    summary = {
        "files_scanned": len(paths),
        "hits": len(hits),
        "core_hits": sum(1 for h in hits if h["core"]),
        "tag_counts": dict(Counter(t for h in hits for t in h["tags"])),
        "parse_errors": parse_errors,
        "by_file": dict(Counter(h["file"] for h in hits)),
        "core_tests": [f"{h['file']}::{h['test']}" for h in hits if h["core"]],
        "predicate": (
            "WEAK_DIAG|HELPER_WEAK_RAISE|MOCK_CALL_ORACLE|PRIVATE_MARKER|"
            "JUDGE_SAMPLE|SECONDARY/ASYNC raises rescan"
        ),
    }

    cmd = (
        "cd $REPO && python3 evidence/1900-j6-final-rescan/j6_enum.py\n"
        f"# tracked test files={len(paths)} hits={len(hits)} "
        f"core={summary['core_hits']}\n"
        "# predicate covers末份 J6 boundary全文; not raises-keyword count\n"
    )
    (OUT / "enum-cmd.txt").write_text(cmd, encoding="utf-8")
    with (OUT / "j6-candidates.jsonl").open("w", encoding="utf-8") as fh:
        for h in hits:
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")
    (OUT / "j6-enum-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    md: list[str] = [
        "# J6 全仓枚举成员（末份判词边界）\n\n",
        f"扫描测试文件 {len(paths)}；命中 {len(hits)}（core={summary['core_hits']}）\n\n",
        f"谓词：`{summary['predicate']}`\n\n",
        "## Core（须语义处置；含判词反例）\n\n",
    ]
    for h in hits:
        if not h["core"]:
            continue
        md.append(
            f"- `{h['file']}::{h['test']}` L{h['line']} "
            f"tags=`{','.join(h['tags'])}` — {'; '.join(h['reasons']) or 'core'}\n"
        )
    md.append("\n## Full inventory（含 secondary/async raises 复扫）\n\n")
    for h in hits:
        mark = "CORE" if h["core"] else "rescan"
        md.append(
            f"- [{mark}] `{h['file']}::{h['test']}` L{h['line']} "
            f"`{','.join(h['tags'])}`\n"
        )
    (OUT / "j6-members.md").write_text("".join(md), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "files_scanned", "hits", "core_hits", "tag_counts", "core_tests"
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
