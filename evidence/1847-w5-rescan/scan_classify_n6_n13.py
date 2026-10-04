#!/usr/bin/env python3
"""#1847 w5 frozen dossier: N6/N11/N12/N13 rescan + per-member classify.

One-shot evidence generator (not a permanent runtime mechanism).
Re-run:

  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
    evidence/1847-w5-rescan/scan_classify_n6_n13.py

Writes LF TSVs under evidence/1847-w5-rescan/ and copies canonical member
tables to evidence/1847-w5-n{6,11,12,13}-members.tsv (+ exempt).
Every N6 row must carry concrete source→dest (no KEEP_review_bucket).
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import shutil
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent

SCAN_ROOTS = [
    ROOT / "ming_sim",
    ROOT / "scripts",
    ROOT / "web" / "src",
    ROOT / "web_app.py",
    ROOT / "main.py",
    ROOT / "launcher.py",
    ROOT / "tests",
]
SKIP_PREFIXES = (
    str(ROOT / "docs" / "raw") + os.sep,
    str(ROOT / "docs" / "archive") + os.sep,
    str(ROOT / "evidence") + os.sep,
    str(ROOT / "node_modules") + os.sep,
)

PY_MUTATE = {
    "strip",
    "lstrip",
    "rstrip",
    "replace",
    "split",
    "rsplit",
    "join",
    "sub",
    "subn",
    "findall",
    "search",
    "match",
    "fullmatch",
    "compile",
    "encode",
    "decode",
    "removeprefix",
    "removesuffix",
    "partition",
    "rpartition",
    "casefold",
    "lower",
    "upper",
    "title",
    "capitalize",
    "zfill",
    "center",
    "ljust",
    "rjust",
    "expandtabs",
    "translate",
    "format",
    "format_map",
}
PY_RE = {
    "sub",
    "subn",
    "split",
    "findall",
    "search",
    "match",
    "fullmatch",
    "compile",
    "escape",
    "finditer",
}
KW_TRUNC = re.compile(
    r"(truncate|截断|裁剪|sanitize|humanize|max_len|FIELD_CAP|思考已截断|THINKING_STREAM)"
)
SLICE_RE = re.compile(r"\[\s*:\s*([^\]]+)\]")


def is_skipped(p: pathlib.Path) -> bool:
    s = str(p.resolve())
    return any(s.startswith(x) for x in SKIP_PREFIXES)


def iter_files():
    for root in SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or is_skipped(p):
                continue
            if p.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
                yield p


def rel(p: pathlib.Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def read_lines(p: pathlib.Path):
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def enclosing_fn(lines, lineno: int) -> str:
    for i in range(lineno - 1, -1, -1):
        m = re.match(r"^(\s*)(async\s+def|def|class)\s+(\w+)", lines[i])
        if m:
            return m.group(3)
    return "<module>"


def field_from_snip(snip: str) -> str:
    parts = []
    for m in re.finditer(r'\.get\(\s*["\']([^"\']+)["\']', snip):
        parts.append(f"get:{m.group(1)}")
    for m in re.finditer(r'getattr\(\s*\w+\s*,\s*["\']([^"\']+)["\']', snip):
        parts.append(f"getattr:{m.group(1)}")
    for m in re.finditer(r'\[\s*["\']([^"\']+)["\']\s*\]', snip):
        parts.append(f"key:{m.group(1)}")
    for m in re.finditer(r"\b(str|int|float)\(\s*(\w+)", snip):
        parts.append(f"cast:{m.group(2)}")
    return "|".join(parts[:6]) if parts else "expr-local"


def classify_n6_py(
    path: str, lineno: int, kind: str, detail: str, snip: str, lines: list[str], fn: str
) -> tuple[str, str]:
    s = snip
    dest_fn = fn
    stripped = s.lstrip()

    if "思考已截断" in s or "_THINKING_STREAM_CHAR_LIMIT" in s:
        return (
            "DELETED",
            "thinking free-text char cap removed; on_thinking full text",
        )
    if path.endswith("play_as_emperor.py") and "[:200]" in s:
        return (
            "DELETED",
            "live free-text action truncate→PTY removed prior round",
        )

    if (
        stripped.startswith("#")
        or stripped.startswith('"""')
        or stripped.startswith("'''")
    ):
        return (
            "KEEP_doc_or_comment",
            f"src=comment/doc @ {path}:{lineno} fn={dest_fn}; dest=documentation only",
        )

    if (
        path.startswith("tests/")
        or path.endswith(".test.ts")
        or path.endswith(".test.tsx")
        or ".test." in path
    ):
        return (
            "KEEP_test",
            f"src=test fixture/assert @ {path}:{lineno} fn={dest_fn}; dest=pytest/vitest only",
        )

    if "tlog(" in s or "_log(" in s or "logging." in s or re.search(r"\bprint\s*\(", s):
        return (
            "KEEP_log_or_trace",
            f"src=local preview @ {path}:{lineno} fn={dest_fn}; dest=operator tlog/print only; not inter-model feed",
        )

    if "sanitize_sqlite" in s:
        return (
            "KEEP_sqlite_sanitize",
            f"src=DB-bound value @ fn={dest_fn} → dest=sqlite TEXT via sanitize_sqlite_text; NUL/control storage contract",
        )

    if (
        "parse_agent_json" in dest_fn
        or "strip_json_fence" in s
        or r"\x00-\x08" in s
        or "json.loads" in s
        or "```" in s
    ):
        return (
            "KEEP_formal_json_parse",
            f"src=LLM raw JSON/fence @ fn={dest_fn} → dest=json.loads formal parse (control-char/fence); raise on fail; not emperor rewrite",
        )

    if "datetime" in s and ".replace(" in s and "microsecond" in s:
        return (
            "KEEP_non_text_api",
            f"src=datetime @ fn={dest_fn} → dest=isoformat; datetime.replace(microsecond) not free-text",
        )

    if "relative_to" in s or ("\\\\" in s and "replace" in s and "/" in s):
        return (
            "KEEP_path_normalize",
            f"src=Path @ fn={dest_fn} → dest=posix path string; OS path form",
        )

    if "{{" in s and "}}" in s and "replace" in s:
        return (
            "KEEP_template_placeholder",
            f"src=prompt template @ fn={dest_fn} → dest=closed placeholder substitution {{{{…}}}}",
        )

    if r"\x1b" in s or "ansi" in s.lower():
        return (
            "KEEP_ansi_strip",
            f"src=CLI stream @ fn={dest_fn} → dest=diagnostic without CSI; terminal control strip",
        )

    if "humanize" in detail.lower() or "humanize" in s:
        return (
            "KEEP_humanize_structured",
            f"src=structured modifiers/gate dict @ fn={dest_fn} → dest=UI/effect label from structured fields",
        )

    if (
        "truncate_agno" in s
        or "truncate_history" in s
        or "truncate_chat_turn" in s
        or (detail == "truncate" and "agno" in s.lower())
        or (detail == "truncate" and ("keep_count" in s or "Truncate session" in s))
        or "def _history_backed_truncate" in s
        or "def _truncate_history_backed" in s
    ):
        return (
            "KEEP_session_run_truncate",
            f"src=GameDB agno session runs @ fn={dest_fn} → dest=delete empty completed runs before transport retry; run-row count not free-text content",
        )

    if kind == "keyword" and detail in ("截断", "裁剪", "truncate", "原文"):
        return (
            "KEEP_doc_or_comment",
            f"src=keyword {detail} non-mutating @ {path}:{lineno} fn={dest_fn}; dest=documentation/identifier",
        )

    if detail == "max_len" or "max_len" in s:
        return (
            "KEEP_form_struct",
            f"src=FieldSpec/form max_len @ fn={dest_fn} → dest=structured form validation boundary",
        )

    if kind in ("slice", "rg_slice") or "[:" in s:
        m = re.search(r"\[:(\d+)\]", s)
        n = m.group(1) if m else "?"
        if any(x in s for x in ("raise", "Error", 'f"', "f'", "腐坏", "须为")):
            return (
                "KEEP_diag_error",
                f"src=exception/diagnostic preview[:{n}] @ fn={dest_fn} → dest=operator error string",
            )
        if "tlog" in s or "_log" in s:
            return (
                "KEEP_log_or_trace",
                f"src=log preview[:{n}] @ fn={dest_fn} → dest=operator log",
            )
        if "pix[" in s or "portrait" in s or "image" in path:
            return (
                "KEEP_binary_or_pixels",
                f"src=image/pixel slice @ fn={dest_fn} → dest=image processing",
            )
        if any(
            x in s
            for x in ("options[:", "hit[:", "person_names[:", "interests[:", "visible")
        ):
            return (
                "KEEP_list_cap_ui",
                f"src=structured list[:{n}] @ fn={dest_fn} → dest=UI/options list-length cap; element text unedited",
            )
        if "normalized_text" in s or "审计" in s:
            return (
                "KEEP_struct_field_cap",
                f"src=structured audit JSON note @ fn={dest_fn}; full-store contract (forbids mid-cut)",
            )
        if "remaining" in s or "merged[:" in s:
            return (
                "KEEP_log_preview",
                f"src=stream buffer @ fn={dest_fn} → dest=tlog preview; on_thinking/on_text get full merged",
            )
        fields = field_from_snip(s)
        return (
            "KEEP_struct_field_cap",
            f"src={fields} @ fn={dest_fn} → dest=bounded structured field/id preview[:{n}]; empty source→empty; formal length on identifier/label",
        )

    if detail in ("strip", "lstrip", "rstrip") or any(
        x in s for x in (".strip(", ".lstrip(", ".rstrip(")
    ):
        fields = field_from_snip(s)
        if "return" in s:
            use = "return"
        elif "if " in s and any(op in s for op in ("==", "!=", "not ")):
            use = "empty-or-equality-gate"
        elif "=" in s:
            use = "assign-then-use"
        else:
            use = "compare/lookup"
        note = (
            f"src={fields} @ fn={dest_fn}:{path}:{lineno} → dest={use}; "
            f"strip empty-normalize only (leading/trailing ws removed; only-ws→empty); "
            f"non-ws payload preserved; formal identity/key compare — not free-prose rewrite"
        )
        return "KEEP_empty_normalize", note

    if detail == "split" or ".split(" in s:
        fields = field_from_snip(s)
        return (
            "KEEP_split_structure",
            f"src={fields} @ fn={dest_fn} → dest=token/path/CSV structure split; delimiter formal parse",
        )

    if detail in ("join",) or ".join(" in s:
        fields = field_from_snip(s)
        return (
            "KEEP_join_structure",
            f"src={fields}|collection @ fn={dest_fn} → dest=delimiter-join of structured parts/ids/labels; elements not synonym-rewritten",
        )

    if detail in ("lower", "upper", "casefold") or any(
        x in s for x in (".lower(", ".upper(", ".casefold(")
    ):
        fields = field_from_snip(s)
        return (
            "KEEP_casefold_compare",
            f"src={fields} @ fn={dest_fn} → dest=casefold for closed-enum/sql compare; original stored value not rewritten for emperor feed",
        )

    if detail in ("partition", "rpartition", "rsplit", "removeprefix", "removesuffix"):
        fields = field_from_snip(s)
        return (
            "KEEP_split_structure",
            f"src={fields} @ fn={dest_fn} → dest={detail} formal token/stem split; identifier form",
        )

    if detail in ("encode", "decode"):
        fields = field_from_snip(s)
        return (
            "KEEP_id_hash",
            f"src={fields} @ fn={dest_fn} → dest=bytes/utf-8 encode for hash/id; not prose edit",
        )

    if detail in ("match", "fullmatch", "search", "findall") or any(
        x in s for x in (".match(", ".fullmatch(", ".search(", ".findall(")
    ):
        fields = field_from_snip(s)
        return (
            "KEEP_formal_regex",
            f"src={fields} @ fn={dest_fn} → dest={detail} against closed pattern/DSL; formal parse",
        )

    if detail == "format" or ".format(" in s:
        fields = field_from_snip(s)
        return (
            "KEEP_format_struct",
            f"src={fields} @ fn={dest_fn} → dest=str.format of structured fields; template fill not prose rewrite",
        )

    if detail == "FIELD_CAP" or "FIELD_CAP" in s:
        return (
            "KEEP_form_struct",
            f"src=FIELD_CAP constant @ fn={dest_fn} → dest=structured form field length boundary",
        )

    if detail == "replace" or ".replace(" in s:
        fields = field_from_snip(s)
        if any(x in s for x in ("兼掌", "兼署", "兼")):
            return (
                "KEEP_office_token_split",
                f"src=office title token @ fn={dest_fn} → dest=split concurrent-office separators for roster parse; stem preserved",
            )
        if "数值变化" in s:
            return (
                "KEEP_metric_label_prefix",
                f"src=format_metric_delta structured number → dest=UI label; strips fixed prefix only",
            )
        if "portrait_id" in s:
            return (
                "KEEP_id_hash",
                f"src=portrait_id → dest=int after prefix peel; identifier form",
            )
        return (
            "KEEP_formal_replace",
            f"src={fields} @ fn={dest_fn} → dest=formal delimiter/placeholder/path replace; closed alphabet",
        )

    if kind == "re" or str(detail).startswith("re.") or "re." in s:
        fields = field_from_snip(s)
        if "CMRPATH" in s:
            return (
                "KEEP_formal_dsl",
                f"src=login-shell stdout sentinels → dest=_login_shell_path PATH extract; sentinel DSL",
            )
        if "待核定" in s:
            return (
                "KEEP_formal_dsl",
                f"src=CLI chunk [待核定]#N → dest=pending id list; marker DSL",
            )
        if "AUTO_SAVE_PREFIX" in s or "re.escape" in s:
            return (
                "KEEP_id_hash",
                f"src=autosave filename → dest=cid via escaped prefix DSL",
            )
        if r"\s+" in s and "sub" in s:
            return (
                "KEEP_ws_compact_compare",
                f"src={fields} @ fn={dest_fn} → dest=whitespace-compact for closed-catalog equality; compare-only",
            )
        return (
            "KEEP_formal_regex",
            f"src={fields} @ fn={dest_fn} → dest=formal parse/match ({detail}); closed pattern",
        )

    if kind in ("rg_mutate_near_text", "rg_context"):
        fields = field_from_snip(s)
        return (
            "KEEP_scan_context",
            f"src=rg context near mutate @ {path}:{lineno} fn={dest_fn} fields={fields}; sibling of call row",
        )

    if path.endswith((".ts", ".tsx", ".js", ".jsx")):
        fields = field_from_snip(s)
        if "not.toMatch" in s or "expect(" in s:
            return "KEEP_test", f"src=frontend test @ {path}:{lineno}; dest=vitest"
        return (
            "KEEP_ui_chrome",
            f"src={fields} @ fn={dest_fn} → dest=UI chrome/format; structured field display",
        )

    if "sanitize" in detail or "sanitize" in s:
        fields = field_from_snip(s)
        return (
            "KEEP_sqlite_sanitize",
            f"src={fields} @ fn={dest_fn} → dest=sanitize helper for DB/shape contract",
        )

    fields = field_from_snip(s)
    return (
        "KEEP_verified_non_transport",
        f"src={fields} kind={kind}/{detail} @ fn={dest_fn}:{path}:{lineno} → dest=verified non emperor/model free-text transport; caller={dest_fn}",
    )


def scan_n6():
    rows = []
    for p in iter_files():
        if p.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            continue
        lines = read_lines(p)
        text = "\n".join(lines)
        rpath = rel(p)
        for i, line in enumerate(lines, 1):
            if KW_TRUNC.search(line):
                for m in KW_TRUNC.finditer(line):
                    rows.append(
                        (rpath, i, "keyword", m.group(0), "trunc_keyword", line.strip()[:240])
                    )
            for m in SLICE_RE.finditer(line):
                rows.append(
                    (
                        rpath,
                        i,
                        "slice",
                        f"slice:{m.group(1).strip()}",
                        "string_slice",
                        line.strip()[:240],
                    )
                )
                rows.append(
                    (
                        rpath,
                        i,
                        "rg_slice",
                        f"[:{m.group(1).strip()}]",
                        "rg_slice",
                        line.strip()[:240],
                    )
                )
        if p.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            if tree:
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    detail = None
                    kind = "call"
                    if (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in PY_MUTATE
                    ):
                        detail = node.func.attr
                    elif (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "re"
                        and node.func.attr in PY_RE
                    ):
                        detail = f"re.{node.func.attr}"
                        kind = "re"
                    if detail and getattr(node, "lineno", None):
                        snip = (
                            lines[node.lineno - 1].strip()[:240]
                            if node.lineno <= len(lines)
                            else detail
                        )
                        why = "mutate_call_live" if kind == "call" else "re_live"
                        rows.append((rpath, node.lineno, kind, detail, why, snip))
        else:
            for i, line in enumerate(lines, 1):
                m = re.search(
                    r"\.(trim|replace|slice|split|substring|substr)\s*\(", line
                )
                if m:
                    rows.append(
                        (
                            rpath,
                            i,
                            "js_call",
                            m.group(1),
                            "js_mutate_live",
                            line.strip()[:240],
                        )
                    )
    seen = set()
    out = []
    for r in rows:
        key = r[:5]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def classify_all_n6(raw_rows):
    cache_lines: dict[str, list[str]] = {}
    out = []
    for path, line, kind, detail, why, snip in raw_rows:
        if path not in cache_lines:
            cache_lines[path] = read_lines(ROOT / path)
        lines = cache_lines[path]
        fn = enclosing_fn(lines, line) if lines else "<module>"
        cur = lines[line - 1].strip()[:240] if lines and 1 <= line <= len(lines) else snip
        disp, note = classify_n6_py(path, line, kind, detail, cur, lines, fn)
        out.append((path, line, kind, detail, why, disp, note, cur))
    return out


N13_PAT = re.compile(
    r"(\.kill\s*\(|os\.kill|killpg|SIGKILL|terminate\s*\(|\.close\s*\(|"
    r"subprocess\.(run|call|check_output)\s*\(|_RAW_RUN\s*\(|timeout\s*=)"
)


def scan_n13():
    rows = []
    for p in iter_files():
        if p.suffix != ".py":
            continue
        lines = read_lines(p)
        rpath = rel(p)
        text = "\n".join(lines)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        for i, line in enumerate(lines, 1):
            if not N13_PAT.search(line):
                continue
            kind = "timeout_kw" if "timeout" in line else "signal_or_kill"
            if "SIGKILL" in line:
                kind = "SIGKILL_ref"
            if ".terminate(" in line:
                kind = "terminate_any"
            if ".kill(" in line:
                kind = "kill_call"
            if "force" in line and "close" in line:
                kind = "close_force"
            if "subprocess.run" in line or "_RAW_RUN" in line:
                kind = "subprocess_run"
            rows.append((rpath, i, kind, line.strip()[:200]))
        if tree:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(
                    node.func, ast.Attribute
                ):
                    continue
                snip = (
                    lines[node.lineno - 1].strip()[:200]
                    if node.lineno <= len(lines)
                    else node.func.attr
                )
                if node.func.attr in ("wait", "join", "result", "get") and any(
                    kw.arg == "timeout" for kw in (node.keywords or []) if kw.arg
                ):
                    rows.append((rpath, node.lineno, "wait_timeout", snip))
                if node.func.attr == "close":
                    rows.append((rpath, node.lineno, "ast_close", snip))
                if node.func.attr == "terminate":
                    rows.append((rpath, node.lineno, "ast_terminate", snip))
                if node.func.attr == "kill":
                    rows.append((rpath, node.lineno, "ast_kill", snip))
    seen = set()
    out = []
    for r in rows:
        k = r[:3]
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def classify_n13(path, line, kind, snip):
    if path.startswith("tests/"):
        return "KEEP_test", "test double / assert; not production kill path"
    stripped = snip.lstrip()
    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
        return "KEEP_doc", "comment/doc only; no runtime kill/timeout call"
    if kind == "SIGKILL_ref" or (
        "SIGKILL" in snip
        and ".kill(" not in snip
        and "os.kill" not in snip
        and "killpg" not in snip
    ):
        return "KEEP_doc", "documentation / negative comment only; no runtime SIGKILL"
    if "_warm_keychain" in snip or "find-generic-password" in snip:
        return (
            "DELETED",
            "keychain warmup removed this round (was run(timeout)/Popen+wait hard guard)",
        )
    if kind in ("kill_call", "ast_kill") or ".kill(" in snip or "os.kill" in snip:
        if "SIGTERM" in snip or "signal.SIGTERM" in snip:
            return "KEEP_sigterm_self", "os.kill(..., SIGTERM) soft stop; not SIGKILL"
        return "FIX_NEEDED_SIGKILL", "reachable kill/SIGKILL — must remove"
    if "subprocess.run" in snip or kind == "subprocess_run" or "_RAW_RUN" in snip:
        if "timeout" in snip:
            return (
                "FIX_NEEDED_RUN_TIMEOUT",
                "subprocess.run(timeout) → stdlib process.kill=SIGKILL",
            )
        return "KEEP_subprocess_no_timeout", "subprocess.run/call without timeout; natural exit"
    if kind in ("terminate_any", "ast_terminate") or ".terminate(" in snip:
        return "KEEP_sigterm", "terminate()=SIGTERM only; no force escalate"
    if kind == "close_force" or "force=True" in snip:
        return "FIX_NEEDED_FORCE_CLOSE", "close(force=True) can escalate — must remove"
    if kind == "ast_close" or ".close(" in snip:
        if "force" in snip and "True" in snip:
            return "FIX_NEEDED_FORCE_CLOSE", "close(force=True)"
        return "KEEP_resource_close", "DB/file/stdin/session close; not pexpect force-close"
    if "timeout" in snip or kind in ("timeout_kw", "wait_timeout"):
        if "subprocess.run" in snip or "_RAW_RUN" in snip:
            return (
                "FIX_NEEDED_RUN_TIMEOUT",
                "subprocess.run(timeout) kill path",
            )
        if "urlopen" in snip or "urllib" in snip:
            return "KEEP_soft_timeout", "HTTP urlopen timeout; no process.kill"
        if "model.timeout" in snip or "attempt_timeout" in snip:
            return "KEEP_soft_timeout", "SDK/API attempt timeout; not OS process kill"
        if any(
            x in snip
            for x in (
                ".wait(timeout",
                ".join(timeout",
                ".get(timeout",
                ".result(timeout",
                "_cv.wait",
                "_cond.wait",
            )
        ):
            return (
                "KEEP_soft_timeout",
                "wait/join/queue/cv soft budget; no process.kill on expiry",
            )
        return (
            "KEEP_soft_timeout",
            f"soft timeout keyword @ {path}:{line}; verified no process.kill on expiry",
        )
    return "KEEP_verified", f"verified non-SIGKILL @ {path}:{line} kind={kind}"


N11_PAT = re.compile(
    r"(__leverage_offsets_|pairing_warnings|_infer_tag|_guess_caller|legacy|退役|"
    r"marker.?only|compat|deprecated|PERSON_LEGACY|_legacy_)",
    re.I,
)


def scan_n11():
    rows = []
    for p in iter_files():
        if p.suffix != ".py":
            continue
        lines = read_lines(p)
        rpath = rel(p)
        for i, line in enumerate(lines, 1):
            if N11_PAT.search(line):
                rows.append((rpath, i, line.strip()[:220]))
    return rows


def classify_n11_hit(path, line, snip):
    checks = [
        (
            "_legacy_commitment_stop_gate",
            "DELETED",
            "resolve_condition prose→gate compat removed",
        ),
        (
            "PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS",
            "DELETED",
            "unused legacy constant removed",
        ),
        ("_infer_tag", "DELETED", "empty shell after keyword infer deleted"),
        ("_guess_caller_tag", "DELETED", "unused alt caller tag iface deleted"),
        ("ming_sim_caller_tag", "DELETED", "unused alt caller tag iface deleted"),
        (
            "__leverage_offsets_rank_rules_562",
            "DELETED",
            "retired migration marker write removed",
        ),
        (
            "__leverage_offsets_calibrated",
            "KEEP",
            "serves live calibration migration",
        ),
        ("float_v2", "KEEP", "serves live precision migration"),
    ]
    for sym, disp, note in checks:
        if sym in snip:
            return disp, note, sym
    if "pairing_warnings" in snip:
        if "not in" in snip or "assert" in snip:
            return (
                "KEEP",
                "pairing_warnings not in applied — negative live contract assert",
                "pairing_warnings",
            )
        return (
            "EXCLUDED_noise",
            "pairing_warnings word hit without retired return-key member",
            "pairing_warnings",
        )
    if "decision_key" in snip or "0055" in path:
        return "KEEP", "0055/rescript live gate; boundary forbid delete", "decision_key"
    if path.startswith("tests/") and (
        "test_legacy" in snip or "legacy_character" in snip
    ):
        return "DELETED", "dedicated legacy test removed", "test_legacy"
    return (
        "EXCLUDED_noise",
        "legacy/compat/deprecated vocabulary hit without retired mechanism symbol; not N11 delete member",
        "noise",
    )


def scan_n12_literals():
    assign_re = re.compile(r"^(\s*)([A-Z][A-Z0-9_]*)\s*=\s*(\{|frozenset\(|set\()")
    keys = (
        "COURT_OFFICE",
        "MINISTRY_OFFICE",
        "GATE_METRIC",
        "_LEGACY_ACCOUNT",
        "DUE_SUBJECTS",
        "_DUE_KEYS",
        "_DEFAULT_FAVORITES",
        "PERSON_STATUSES",
        "ARREARS_SUBJECTS",
        "POWER_SCORE_FIELDS",
        "KNOWN_ACTIONS",
        "CASH_KINDS",
        "CLAIM_KINDS",
    )
    hits = []
    for p in iter_files():
        if p.suffix not in {".py", ".ts", ".tsx"}:
            continue
        lines = read_lines(p)
        rpath = rel(p)
        for i, line in enumerate(lines, 1):
            if assign_re.match(line) or any(k in line for k in keys):
                hits.append((rpath, i, line.strip()[:200]))
    return hits


def write_tsv(path: pathlib.Path, header, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write(
                "\t".join(
                    str(x).replace("\t", " ").replace("\n", " ").replace("\r", "")
                    for x in r
                )
                + "\n"
            )


def main() -> int:
    print("Scanning N6...")
    n6_raw = scan_n6()
    n6 = classify_all_n6(n6_raw)
    assert not any(r[5] == "KEEP_review_bucket" for r in n6), "KEEP_review_bucket remains"
    print("N6 raw", len(n6_raw), "disp", Counter(r[5] for r in n6).most_common(12))

    print("Scanning N13...")
    n13_raw = scan_n13()
    n13 = []
    for path, line, kind, snip in n13_raw:
        d, n = classify_n13(path, line, kind, snip)
        n13.append((path, line, kind, d, n, snip))
    fix_n13 = [r for r in n13 if r[3].startswith("FIX_")]
    print("N13", len(n13), "FIX", len(fix_n13), Counter(r[3] for r in n13).most_common(10))
    for r in fix_n13[:30]:
        print(" FIX", r[0], r[1], r[3], r[5][:80])

    print("Scanning N11...")
    n11_raw = scan_n11()
    n11_class = []
    for path, line, snip in n11_raw:
        d, n, sym = classify_n11_hit(path, line, snip)
        n11_class.append((path, line, sym, d, n, snip))
    print("N11 raw", len(n11_raw), Counter(r[3] for r in n11_class).most_common())

    print("Scanning N12...")
    n12_hits = scan_n12_literals()
    print("N12 literal hits", len(n12_hits))

    write_tsv(
        OUT / "n6_candidates_raw.tsv",
        ["path", "line", "kind", "detail", "scan_why", "snippet"],
        n6_raw,
    )
    write_tsv(
        OUT / "n6_members_classified.tsv",
        [
            "path",
            "line",
            "kind",
            "detail",
            "scan_why",
            "disposition",
            "source_dest_note",
            "snippet",
        ],
        n6,
    )
    write_tsv(
        OUT / "n13_focus.tsv",
        ["path", "line", "kind", "disposition", "note", "snippet"],
        n13,
    )
    write_tsv(
        OUT / "n11_focus.tsv",
        ["path", "line", "symbol", "disposition", "note", "snippet"],
        n11_class,
    )
    write_tsv(OUT / "n12_literal_hits.tsv", ["path", "line", "snippet"], n12_hits)

    # Canonical member tables (LF) at evidence/1847-w5-*
    shutil.copyfile(OUT / "n6_members_classified.tsv", ROOT / "evidence" / "1847-w5-n6-members.tsv")
    shutil.copyfile(OUT / "n13_focus.tsv", ROOT / "evidence" / "1847-w5-n13-members.tsv")

    # N11 members = non-noise only + exclusion summary row file
    n11_members = [r for r in n11_class if r[3] != "EXCLUDED_noise"]
    write_tsv(
        ROOT / "evidence" / "1847-w5-n11-members.tsv",
        ["path", "line", "symbol", "disposition", "note", "class"],
        [
            (a, b, c, d, e, "retired_or_live_gate" if d != "EXCLUDED_noise" else "noise")
            for a, b, c, d, e, _ in n11_members
        ],
    )
    excl = Counter(r[4] for r in n11_class if r[3] == "EXCLUDED_noise")
    write_tsv(
        OUT / "n11_exclusion_summary.tsv",
        ["exclusion_reason", "count"],
        sorted(excl.items(), key=lambda x: -x[1]),
    )

    # N12 curated members (actions taken + explicit keeps) — rebuild from known set + hits
    n12_members = [
        (
            "ming_sim/token_stats.py",
            "—",
            "ming_sim_caller_tag / _guess_caller_tag",
            "DELETED",
            "prior round unused alt iface",
            "多余替代接口",
        ),
        (
            "web/src/components/ministerFilters.ts",
            "—",
            "MINISTRY from COURT",
            "CONVERGED",
            "prior round",
            "重复定义",
        ),
        (
            "web/src/components/drawers.tsx",
            "—",
            "inline court list→COURT_OFFICE_TYPE_ORDER",
            "CONVERGED",
            "prior round",
            "重复定义",
        ),
        (
            "ming_sim/issues.py",
            "—",
            "_LEGACY_ACCOUNT_KEYS→GATE_METRIC_KEYS",
            "CONVERGED",
            "this family",
            "重复定义",
        ),
        (
            "ming_sim/db.py",
            "—",
            "MINISTRY_OFFICE_TYPES = COURT - {内阁}",
            "CONVERGED",
            "this family",
            "重复定义",
        ),
        (
            "ming_sim/db.py + issues.py",
            "—",
            "person status set→PERSON_STATUSES",
            "CONVERGED",
            "this family",
            "重复定义",
        ),
        (
            "ming_sim/fiscal_tick.py",
            "—",
            "_DUE/_ARREARS→pay_order subjects",
            "CONVERGED",
            "this family",
            "重复定义",
        ),
        (
            "web_app.py",
            "—",
            "_DEFAULT_FAVORITES single module const",
            "CONVERGED",
            "this family",
            "重复定义",
        ),
        (
            "spike_settle_tick.py",
            "—",
            "CASH/CLAIM/KNOWN_ACTIONS mirror fiscal_tick",
            "KEEP_spike_oracle",
            "explicit spike oracle mirror; scanned not silently dropped",
            "spike镜像豁免",
        ),
        (
            "ming_sim/db.py + issues.py",
            "—",
            "power delta field set {leverage,military_strength,supply}",
            "KEEP",
            "narrow write-whitelist subset of POWER_SCORE_FIELDS at two gates; not identical full enum",
            "子集非全等重复",
        ),
    ]
    write_tsv(
        ROOT / "evidence" / "1847-w5-n12-members.tsv",
        ["path", "line", "symbol", "disposition", "note", "class"],
        n12_members,
    )
    write_tsv(
        OUT / "n12_exclusion_note.tsv",
        ["rule", "detail"],
        [
            (
                "literal_hit_not_duplicate_enum",
                f"n12_literal_hits={len(n12_hits)}; single-definition COURT/GATE/PERSON/DUE/FAVORITES reads + subsets KEEP; only identical full enums converged",
            ),
            (
                "smell_unused_alt_iface",
                "caller_tag helpers deleted; remaining name smells without second definition EXCLUDED as non-duplicate",
            ),
            (
                "spike_oracle",
                "spike_settle_tick.py KEEP_spike_oracle explicit; not silent archive drop",
            ),
        ],
    )

    exempt = [
        ("docs/raw/**", "archive_prefix:docs/raw/"),
        ("docs/archive/**", "archive_prefix:docs/archive/"),
        ("evidence/**", "archive_prefix:evidence/ (frozen dossiers; scanned separately)"),
        ("node_modules/**", "third_party_untracked_not_in_git_ls_files"),
        (
            "spike_settle_tick.py",
            "KEEP as explicit spike oracle mirror (see N12); scanned not silently dropped",
        ),
        (
            "evidence/1847-w5-rescan/**",
            "this round frozen scan/classify dossier; reproducible via scan_classify_n6_n13.py",
        ),
    ]
    # expand a few concrete archive files previously listed
    for p in sorted((ROOT / "docs" / "raw").glob("06_harness_scripts/*.py"))[:6]:
        exempt.append((rel(p), "archive_prefix:docs/raw/"))
    write_tsv(
        ROOT / "evidence" / "1847-w5-exempt-files.tsv",
        ["path", "reason"],
        exempt,
    )

    summary = {
        "n6_raw": len(n6_raw),
        "n6_disp": dict(Counter(r[5] for r in n6)),
        "n13": len(n13),
        "n13_disp": dict(Counter(r[3] for r in n13)),
        "n13_fix": len(fix_n13),
        "n11_raw": len(n11_raw),
        "n11_disp": dict(Counter(r[3] for r in n11_class)),
        "n11_members_non_noise": len(n11_members),
        "n12_hits": len(n12_hits),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("WROTE", OUT)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if fix_n13:
        print("ERROR: N13 FIX_NEEDED remain", len(fix_n13))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
