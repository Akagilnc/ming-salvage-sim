#!/usr/bin/env python3
"""#1847 w5 frozen dossier: N6/N11/N12/N13 mechanical rescan.

One-shot evidence generator (not a permanent runtime mechanism).
Re-run:

  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
    evidence/1847-w5-rescan/scan_classify_n6_n13.py

Writes LF TSVs under evidence/1847-w5-rescan/ and syncs mechanical tables to
evidence/1847-w5-n{6,11,12,13}-members.tsv (+ exempt).

CORRECTED CONTRACT (post dddd600bb self-check reject):
- Mechanical rules may ONLY emit POTENTIAL_* / PENDING_HUMAN / MECHANICAL_* /
  DELETED_KNOWN — never KEEP_* shape-guess verdicts.
- Human KEEP/DELETE lives only in evidence/1847-w5-correction/human_judgment.tsv
  (built by human review of live callers + source/sink cites).
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
    """Shape heuristics only → POTENTIAL/PENDING/MECHANICAL. Never KEEP.

    KEEP/DELETE for live production requires human_judgment.tsv with real
    source-contract + destination-path cites (see evidence/1847-w5-correction/).
    """
    s = snip
    dest_fn = fn
    stripped = s.lstrip()
    fields = field_from_snip(s)

    if "思考已截断" in s or "_THINKING_STREAM_CHAR_LIMIT" in s:
        return (
            "DELETED_KNOWN",
            "prior-round removal marker: thinking free-text char cap; confirm absent in live source",
        )
    if path.endswith("play_as_emperor.py") and "[:200]" in s:
        return (
            "DELETED_KNOWN",
            "prior-round removal marker: action[:200]→PTY; confirm absent in live source",
        )

    if (
        stripped.startswith("#")
        or stripped.startswith('"""')
        or stripped.startswith("'''")
    ):
        return (
            "MECHANICAL_DOC",
            f"shape=comment/doc @ {path}:{lineno} fn={dest_fn}; not a KEEP verdict",
        )

    if (
        path.startswith("tests/")
        or path.endswith(".test.ts")
        or path.endswith(".test.tsx")
        or ".test." in path
    ):
        return (
            "MECHANICAL_TEST",
            f"shape=tests/ path @ {path}:{lineno} fn={dest_fn}; not a KEEP verdict",
        )

    # Remaining: potential live mutate — pending human source→dest review.
    shape = kind if kind not in ("call", "js_call", "re") else detail
    if detail in ("strip", "lstrip", "rstrip") or ".strip(" in s or ".trim(" in s:
        shape = "strip/trim"
    elif kind in ("slice", "rg_slice") or "[:" in s:
        shape = "slice"
    elif detail == "split" or ".split(" in s:
        shape = "split"
    elif detail == "join" or ".join(" in s:
        shape = "join"
    note = (
        f"POTENTIAL live mutate shape={shape} fields={fields} "
        f"@ fn={dest_fn}:{path}:{lineno}; PENDING_HUMAN source→dest review "
        f"(auto rules must not invent formal-identity/KEEP)"
    )
    return "PENDING_HUMAN", note


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
    """Mechanical triage only. Soft-timeout/close KEEP requires human confirm."""
    if path.startswith("tests/"):
        return "MECHANICAL_TEST", "tests/ path hit; not a KEEP verdict"
    stripped = snip.lstrip()
    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
        return "MECHANICAL_DOC", "comment/doc shape; not a KEEP verdict"
    if kind == "SIGKILL_ref" or (
        "SIGKILL" in snip
        and ".kill(" not in snip
        and "os.kill" not in snip
        and "killpg" not in snip
    ):
        return "MECHANICAL_DOC", "SIGKILL word without kill call shape; not a KEEP verdict"
    if "_warm_keychain" in snip or "find-generic-password" in snip:
        return (
            "DELETED_KNOWN",
            "prior-round removal marker: keychain warmup hard guard",
        )
    if kind in ("kill_call", "ast_kill") or ".kill(" in snip or "os.kill" in snip:
        if "SIGTERM" in snip or "signal.SIGTERM" in snip:
            return (
                "PENDING_HUMAN",
                "POTENTIAL os.kill/SIGTERM — confirm soft stop, not SIGKILL escalate",
            )
        return "FIX_NEEDED_SIGKILL", "reachable kill/SIGKILL shape — must remove or human-clear"
    if "subprocess.run" in snip or kind == "subprocess_run" or "_RAW_RUN" in snip:
        if "timeout" in snip:
            return (
                "FIX_NEEDED_RUN_TIMEOUT",
                "subprocess.run(timeout) → stdlib process.kill=SIGKILL",
            )
        return (
            "PENDING_HUMAN",
            "subprocess.run/call without timeout kw — confirm natural exit, no later kill",
        )
    if kind in ("terminate_any", "ast_terminate") or ".terminate(" in snip:
        return (
            "PENDING_HUMAN",
            "terminate() hit — confirm SIGTERM-only and force=False",
        )
    if kind == "close_force" or "force=True" in snip:
        return "FIX_NEEDED_FORCE_CLOSE", "close(force=True) can escalate — must remove"
    if kind == "ast_close" or ".close(" in snip:
        if "force" in snip and "True" in snip:
            return "FIX_NEEDED_FORCE_CLOSE", "close(force=True)"
        return (
            "PENDING_HUMAN",
            "resource .close() hit — confirm not pexpect force-close / SIGKILL path",
        )
    if "timeout" in snip or kind in ("timeout_kw", "wait_timeout"):
        if "subprocess.run" in snip or "_RAW_RUN" in snip:
            return (
                "FIX_NEEDED_RUN_TIMEOUT",
                "subprocess.run(timeout) kill path",
            )
        return (
            "PENDING_HUMAN",
            f"timeout keyword @ {path}:{line} kind={kind} — confirm no process.kill on expiry",
        )
    return "PENDING_HUMAN", f"N13 hit @ {path}:{line} kind={kind}; pending human clear"


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
    """Symbol-list triage is incomplete for full N11 class.

    Named retired symbols → DELETED_KNOWN markers only.
    Vocabulary hits (legacy/compat/deprecated) → POTENTIAL_NOISE pending
    human exclusion with complete basis — never auto KEEP / auto EXCLUDED.
    """
    known_deleted = [
        ("_legacy_commitment_stop_gate", "resolve_condition prose→gate compat removed"),
        ("PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS", "unused legacy constant removed"),
        ("_infer_tag", "empty shell after keyword infer deleted"),
        ("_guess_caller_tag", "unused alt caller tag iface deleted"),
        ("ming_sim_caller_tag", "unused alt caller tag iface deleted"),
        ("__leverage_offsets_rank_rules_562", "retired migration marker write removed"),
    ]
    for sym, note in known_deleted:
        if sym in snip:
            return "DELETED_KNOWN", f"prior-round removal marker: {note}", sym
    if path.startswith("tests/") and (
        "test_legacy" in snip or "legacy_character" in snip
    ):
        return "DELETED_KNOWN", "dedicated legacy test removal marker", "test_legacy"
    # Specific live symbols still need human KEEP in human_judgment — not auto.
    for sym in (
        "__leverage_offsets_calibrated",
        "float_v2",
        "pairing_warnings",
        "decision_key",
    ):
        if sym in snip:
            return (
                "PENDING_HUMAN",
                f"named live-adjacent symbol {sym}; human must cite live contract or retire",
                sym,
            )
    return (
        "POTENTIAL_NOISE",
        "vocabulary hit (legacy/compat/deprecated/…) — incomplete symbol search; "
        "PENDING_HUMAN full-class exclusion basis (not auto-EXCLUDED)",
        "vocab",
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
    keepish = [r for r in n6 if str(r[5]).startswith("KEEP")]
    assert not keepish, f"auto classifier must not emit KEEP_* ({len(keepish)} rows)"
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

    # N11 mechanical table = all hits (no auto-EXCLUDED). Human KEEP/DELETE elsewhere.
    n11_members = list(n11_class)
    write_tsv(
        ROOT / "evidence" / "1847-w5-n11-members.tsv",
        ["path", "line", "symbol", "disposition", "note", "class"],
        [
            (
                a,
                b,
                c,
                d,
                e,
                "mechanical_only_not_verdict",
            )
            for a, b, c, d, e, _ in n11_members
        ],
    )
    excl = Counter(r[3] for r in n11_class)
    write_tsv(
        OUT / "n11_exclusion_summary.tsv",
        ["mechanical_disposition", "count"],
        sorted(excl.items(), key=lambda x: -x[1]),
    )

    # N12: mechanical literal hits are complete scan surface; curated actions are
    # historical markers only. Full-class KEEP/EXCLUDE requires human_judgment.
    n12_members = [
        (
            "ming_sim/token_stats.py",
            "—",
            "ming_sim_caller_tag / _guess_caller_tag",
            "DELETED_KNOWN",
            "prior-round unused alt iface marker",
            "多余替代接口",
        ),
        (
            "web/src/components/ministerFilters.ts",
            "—",
            "MINISTRY from COURT",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "web/src/components/drawers.tsx",
            "—",
            "inline court list→COURT_OFFICE_TYPE_ORDER",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "ming_sim/issues.py",
            "—",
            "_LEGACY_ACCOUNT_KEYS→GATE_METRIC_KEYS",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "ming_sim/db.py",
            "—",
            "MINISTRY_OFFICE_TYPES = COURT - {内阁}",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "ming_sim/db.py + issues.py",
            "—",
            "person status set→PERSON_STATUSES",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "ming_sim/fiscal_tick.py",
            "—",
            "_DUE/_ARREARS→pay_order subjects",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "web_app.py",
            "—",
            "_DEFAULT_FAVORITES single module const",
            "CONVERGED_KNOWN",
            "prior-round converge marker",
            "重复定义",
        ),
        (
            "spike_settle_tick.py",
            "—",
            "CASH/CLAIM/KNOWN_ACTIONS mirror fiscal_tick",
            "PENDING_HUMAN",
            "spike oracle mirror — human must re-affirm exemption; not auto KEEP",
            "spike镜像待人工",
        ),
        (
            "ming_sim/db.py + issues.py",
            "—",
            "power delta field set {leverage,military_strength,supply}",
            "PENDING_HUMAN",
            "subset-vs-full-enum — human must cite both definitions; not auto KEEP",
            "子集待人工",
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
                "literal_hits_are_scan_surface_not_verdict",
                f"n12_literal_hits={len(n12_hits)}; named-key/assign scan only — "
                "NOT full-class duplicate proof; exclusion requires per-hit second-definition check",
            ),
            (
                "no_auto_exclude_from_symbol_list",
                "smell without second definition ≠ EXCLUDED; remains in literal_hits for human",
            ),
            (
                "human_judgment_required",
                "KEEP/CONVERGED/spike exemption only in evidence/1847-w5-correction/human_judgment.tsv",
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
        "contract": "mechanical_only_no_auto_KEEP",
        "n6_raw": len(n6_raw),
        "n6_disp": dict(Counter(r[5] for r in n6)),
        "n6_pending_human": sum(1 for r in n6 if r[5] == "PENDING_HUMAN"),
        "n13": len(n13),
        "n13_disp": dict(Counter(r[3] for r in n13)),
        "n13_fix": len(fix_n13),
        "n11_raw": len(n11_raw),
        "n11_disp": dict(Counter(r[3] for r in n11_class)),
        "n11_pending_or_potential": sum(
            1 for r in n11_class if r[3] in ("PENDING_HUMAN", "POTENTIAL_NOISE")
        ),
        "n12_hits": len(n12_hits),
        "human_judgment": "evidence/1847-w5-correction/human_judgment.tsv",
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
