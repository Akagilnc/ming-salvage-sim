#!/usr/bin/env python3
"""#1900 J6 full-repo enumeration (本轮末份判词边界，不得收窄).

Class boundary (verbatim from judge fix.classes[J6]):
  必要失败行为、原故障来源与实际结果的证明遗漏，以及修理新增的非契约文字锁。

Direction (verbatim):
  区分诊断来源保真与固定字句；不能只凭无关诊断替换报红就结清修法。
  复用或修改既有最短真实行为案，保留必要失败、拒收及重试契约；
  删除非契约措辞锁、helper和重复伪证。不得以非空或状态断言替代必要结果，
  也不机械要求所有异常案检查身份。不另造生产机制、钩子或平行证明，
  不设真实并发测试及必要同步的笼统禁令。

Predicate covers definition全文:
  A. WEAK_DIAG_NONEMPTY — error/message 仅非空/truthy，未绑定故障来源
  B. WEAK_HTTP_STATUS_ONLY — HTTPException 失败案只验 status_code/类型，不验 detail.message 来源
  C. WEAK_STREAM_NO_ERROR — chat_stream/异步失败案只验 events 非空或 inflight 清零，不验 error 出口
  D. FIXED_DIAG_LOCK — 对 error/message 等诊断字段做固定中文/字面量等值（非注入对象/str）
  E. JUDGE_SAMPLE — 判词点名三样本强制入账
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
from collections import Counter

ROOT = pathlib.Path(".").resolve()
OUT = ROOT / "evidence/1900-j6-n2-rescan"

JUDGE_SAMPLES = {
    "test_spawn_pending_write_thread_start_failure_releases_ownership",
    "test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write",
    "test_mechanical_tail_missing_llm_config_surfaces_retry",
}

CN_LITERAL = re.compile(r"['\"][^'\"]*[\u4e00-\u9fff][^'\"]*['\"]")
DIAG_GET = re.compile(
    r"""(?:\.get\(\s*['"](?:error|message)['"]\s*\)|\[['\"](?:error|message)['\"]\])"""
)
NONEMPTY = re.compile(
    r"""assert\s+.+(?:\.get\(\s*['"](?:error|message)['"]\s*\)|(?:\[['"](?:error|message)['"]\]))"""
    r"""(?:\s*(?:or\s+['"]{2}|\.strip\(\)))?"""
    r"""\s*(?:#|$)|assert\s+str\([^)]*(?:error|message)[^)]*\)\.strip\(\)""",
    re.I,
)
HTTP_STATUS = re.compile(
    r"""status_code\s*==\s*\d+|raises\([^)]*HTTPException""",
    re.I,
)
STREAM_WEAK = re.compile(
    r"""assert\s+events\b|inflight_count\(\)\s*==\s*0|type.*=.*['"]end['"]""",
    re.I,
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
    s = line.strip()
    if not s.startswith("assert "):
        return False
    body = s[len("assert ") :]
    if "==" in body or " is " in body:
        return False
    if re.search(
        r"""\.get\(\s*['"](?:error|message)['"]\s*\)\s*(?:#|$)|"""
        r"""\.get\(\s*['"](?:error|message)['"]\s*\)\s*$""",
        body,
    ):
        return True
    if re.search(r"""(['"](?:message|error)['"]|\.message\b|\.error\b)""", body):
        if ("strip()" in body or re.search(r"""or\s+['"]{2}""", body)) and "==" not in body:
            return True
    return False


def line_fixed_diag_lock(line: str) -> bool:
    """Equality of error/message to a Chinese / fixed prose literal (not injected var)."""
    s = line.strip()
    if not s.startswith("assert "):
        return False
    if not DIAG_GET.search(s) and "error" not in s and "message" not in s:
        return False
    if "==" not in s:
        return False
    # bind to injected / fault / str(exc) / str(injected) → not fixed lock
    if re.search(
        r"""==\s*str\(\s*(?:injected|fault|exc|error|start_error|postprocess_error|"""
        r"""fiscal_fault|ei\.value|exc_info)""",
        s,
    ):
        return False
    if re.search(r"""==\s*(?:injected|fault|start_error|fiscal_fault|postprocess_error)\b""", s):
        return False
    # Chinese literal on RHS or LHS of == involving error/message
    if CN_LITERAL.search(s) and DIAG_GET.search(s):
        return True
    if CN_LITERAL.search(s) and re.search(r"""\b(?:error|message)\b""", s):
        # narrow: must look like diagnostic equality, not unrelated CN
        if re.search(
            r"""(?:error|message).*=.*=.*['\"][^'\"]*[\u4e00-\u9fff]|"""
            r"""['\"][^'\"]*[\u4e00-\u9fff][^'\"]*['\"].*==.*(?:error|message)""",
            s,
        ):
            return True
    return False


class FuncVisitor(ast.NodeVisitor):
    def __init__(self, src: str, path: str) -> None:
        self.src = src
        self.path = path
        self.lines = src.splitlines()
        self.hits: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_fn(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_fn(node)
        self.generic_visit(node)

    def _visit_fn(self, node: ast.AST) -> None:
        name = getattr(node, "name", "")
        if not name.startswith("test_"):
            return
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start) or start
        body_lines = self.lines[start - 1 : end]
        text = "\n".join(body_lines)
        tags: list[str] = []
        if name in JUDGE_SAMPLES:
            tags.append("JUDGE_SAMPLE")
        for i, line in enumerate(body_lines, start=start):
            if line_weak_diag(line):
                tags.append(f"WEAK_DIAG_NONEMPTY@{i}")
            if line_fixed_diag_lock(line):
                tags.append(f"FIXED_DIAG_LOCK@{i}")
        has_http = bool(HTTP_STATUS.search(text))
        has_detail_msg = bool(
            re.search(
                r"""detail(?:\.(?:get\(\s*)?['\"]message|\[.message)|\.detail.*message|"""
                r"""message.*=.*str\(""",
                text,
            )
        )
        if has_http and not has_detail_msg and (
            "HTTPException" in text or "status_code" in text
        ):
            # failure-path HTTP surface without message source bind
            if re.search(r"raises|status_code\s*==\s*5\d\d", text):
                tags.append("WEAK_HTTP_STATUS_ONLY")
        if (
            "chat_stream" in text
            and STREAM_WEAK.search(text)
            and not re.search(r"""['\"]error['\"].*message|type.*=.*['\"]error['\"]""", text)
            and ("Thread" in text or "start" in text or "spawn" in text or "highlight" in text)
        ):
            tags.append("WEAK_STREAM_NO_ERROR")
        if not tags:
            return
        self.hits.append(
            {
                "file": self.path,
                "test": name,
                "line": start,
                "tags": sorted(set(tags)),
                "snippet": body_lines[0].strip()[:160],
            }
        )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = tracked_test_paths()
    hits: list[dict] = []
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        p = ROOT / rel
        try:
            src = p.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        v = FuncVisitor(src, rel)
        v.visit(tree)
        hits.extend(v.hits)

    # force-include judge samples even if predicate missed (should not)
    seen = {(h["file"], h["test"]) for h in hits}
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        p = ROOT / rel
        try:
            src = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for sample in JUDGE_SAMPLES:
            key_file_test = None
            for m in re.finditer(rf"^def ({sample})\(", src, re.M):
                key_file_test = (rel, m.group(1))
                line = src[: m.start()].count("\n") + 1
                if key_file_test not in seen:
                    hits.append(
                        {
                            "file": rel,
                            "test": sample,
                            "line": line,
                            "tags": ["JUDGE_SAMPLE", "FORCE_INCLUDE"],
                            "snippet": f"def {sample}(",
                        }
                    )
                    seen.add(key_file_test)

    hits.sort(key=lambda h: (h["file"], h["line"], h["test"]))
    cand_path = OUT / "j6-candidates.jsonl"
    with cand_path.open("w", encoding="utf-8") as f:
        for h in hits:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")

    tag_counter: Counter[str] = Counter()
    file_counter: Counter[str] = Counter()
    for h in hits:
        file_counter[h["file"]] += 1
        for t in h["tags"]:
            tag_counter[t.split("@", 1)[0]] += 1

    summary = {
        "test_files_scanned": len([p for p in paths if p.endswith(".py")]),
        "hit_count": len(hits),
        "by_tag_family": dict(tag_counter),
        "by_file": dict(file_counter),
        "judge_samples": sorted(JUDGE_SAMPLES),
        "boundary": "必要失败行为、原故障来源与实际结果的证明遗漏，以及修理新增的非契约文字锁。",
    }
    (OUT / "j6-enum-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "enum-cmd.txt").write_text(
        "python3 evidence/1900-j6-n2-rescan/j6_enum.py\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
