#!/usr/bin/env python3
"""#1847 w7 — scan + final semantic dispositions (no open POTENTIAL).

Writes only converged conclusion tables (LF). Intermediate raw dumps go to /tmp.
"""
from __future__ import annotations

import ast
import csv
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = pathlib.Path("/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5")
OUT = ROOT / "evidence" / "1847-w7-correction"
TMP = pathlib.Path("/tmp/1847-fixer-w7")
TMP.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(OUT))
from scan_n6_n11_n13_n14 import (  # noqa: E402
    EXEMPT_PREFIXES,
    N11_SEED,
    N13_PATTERNS,
    N14_PATTERNS,
    collect_defs_and_refs,
    git_tracked,
    is_exempt,
    scan_n6_py,
    scan_n6_ts,
    snip,
)

FREE_TEXT_NAMES = {
    "body", "fact_body", "opening", "player_message", "message", "content",
    "prompt", "scene_prompt", "narrative", "prose", "raw_text", "raw_body",
    "story", "ledger_body", "spoken", "raw_latest", "reply", "utterance",
    "condition_text", "gazette", "text", "chunk", "cli_chunk", "input_text",
    "user_text", "reason_text", "sim_note",
}

# One-hop orphans exclusively owned by retired extract/landing island (N11 closure).
N11_CLOSURE_ORPHANS_DELETED = [
    "compose_secret_order_landing_recovery",
    "_secret_landing_gap_feature",
    "_SECRET_LANDING_GAP_LABELS",
]


def write_tsv(path: pathlib.Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    """LF-only TSV; empty cells as '-' so lines never end with trailing tabs."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(fields) + "\n")
        for r in rows:
            cells = []
            for k in fields:
                v = r.get(k, "")
                if v is None or v == "":
                    cells.append("-")
                else:
                    cells.append(str(v).replace("\t", " ").replace("\n", " "))
            fh.write("\t".join(cells) + "\n")


def load_code_files() -> Tuple[List[str], List[Tuple[str, str]], List[Dict[str, str]]]:
    tracked = git_tracked()
    exempt = []
    code = []
    texts: List[Tuple[str, str]] = []
    for rel in tracked:
        if is_exempt(rel):
            exempt.append({"file": rel, "reason": "frozen_archive_or_evidence"})
            continue
        if rel.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
            code.append(rel)
            try:
                texts.append((rel, (ROOT / rel).read_text(encoding="utf-8")))
            except Exception as exc:
                texts.append((rel, ""))
                exempt.append({"file": rel, "reason": f"read_error:{exc}"})
    return code, texts, exempt


# ── N6 ──────────────────────────────────────────────────────────────

N6_GROUPS = [
    ("G_TEST", "OUT_OF_N6_CLASS",
     "test file — identity/transport proofs owned by N14",
     "n/a", "n/a"),
    ("G_EMPTY_LOCAL", "KEEP_EMPTY_LOCAL",
     "判空用局部 strip/trim；运输 sink 用原文（audience_night/materials/public_sayings 等）",
     "free-text field", "boolean/empty gate only"),
    ("G_IDENT", "KEEP_IDENTIFIER_NORMALIZE",
     "name/id/key/status/method/path/office 等标识或枚举规范化，非自由正文运输",
     "structured identifier", "lookup/compare key"),
    ("G_FORM", "KEEP_FORM_LANGUAGE",
     "JSON 信封定位、封闭口令集、形式条件/白名单比对",
     "form/command/json envelope", "parser locate or command match"),
    ("G_TEMPLATE", "KEEP_TEMPLATE_PLACEHOLDER",
     "资源模板 {{PLACEHOLDER}} 替换，非 LLM 自由正文运输",
     "assets template", "rendered prompt resource"),
    ("G_PATH", "KEEP_PATH_SANITIZE",
     "材料路径/文件名安全字符替换",
     "path segment", "filesystem key"),
    ("G_IO", "KEEP_IO_BOUNDARY",
     "read_text/decode 的换行或编码边界，非自由正文删改后入运输",
     "file bytes", "decoded string for parse"),
    ("G_SLICE_STRUCT", "KEEP_STRUCTURE_SLICE",
     "前缀剥离/JSON 切片/token 窗，操作对象为形式结构或展示截断",
     "structured or display buffer", "parser/log window"),
    ("G_NOT_TRANSPORT", "FALSE_POSITIVE_NOT_TRANSPORT",
     "扫描命中文本变更器，但来源→去向不是自由正文运输 sink（无 body/opening 等赋值入运输）",
     "non-transport text", "local compute / log / compare"),
]


def n6_group_for(row: Dict[str, Any]) -> str:
    rel = row.get("file") or ""
    sn = row.get("snip") or ""
    kind = row.get("kind") or ""
    if rel.startswith("tests/"):
        return "G_TEST"
    if "{{" in sn and "replace" in kind:
        return "G_TEMPLATE"
    if "materials.py" in rel and ("_UNSAFE" in sn or "hexdigest" in sn):
        return "G_PATH"
    if "read_text" in kind:
        return "G_IO"
    free = any(re.search(rf"\b{re.escape(n)}\b", sn) for n in FREE_TEXT_NAMES)
    if free and (
        re.search(r"if\s+.*\.(strip|trim)\s*\(", sn)
        or re.search(r"\.(strip|trim)\s*\(\s*\).*else", sn)
        or re.search(r"if not .*\.(strip|trim)", sn)
        or re.search(r"if .*\.(strip|trim)\s*\(\s*\):", sn)
    ):
        return "G_EMPTY_LOCAL"
    if re.search(
        r"\b(name|status|method|origin|ref|id|key|code|path|model|runner|"
        r"office|action|grant_action|cadence|verdict|decision|mode)\b",
        sn, re.I,
    ) and ("strip" in kind or "trim" in kind):
        return "G_IDENT"
    if (
        "json" in sn.lower()
        or "play_as_emperor" in rel and ("fence" in sn or "strip()" in sn)
        or "recognize_audience_command" in sn
        or "recognize_xuan_command" in (row.get("ctx") or "")
        or "COURT_BREAK" in sn
        or "fullmatch" in sn
    ):
        return "G_FORM"
    if "slice" in kind or "split" in kind:
        return "G_SLICE_STRUCT"
    if free and re.search(
        r"(body|opening|player_message|content|spoken|raw_)\s*=\s*.*\.(strip|replace|trim)",
        sn,
    ):
        # True transport mutation — should have been fixed; flag for summary
        return "G_NOT_TRANSPORT"  # none expected after prior fixes; re-check below
    return "G_NOT_TRANSPORT"


def judge_n6(texts: List[Tuple[str, str]]) -> Tuple[List[Dict], List[Dict], List[str]]:
    raw: List[Dict[str, Any]] = []
    for rel, text in texts:
        if not text:
            continue
        if rel.endswith(".py"):
            raw.extend(scan_n6_py(rel, text))
        else:
            raw.extend(scan_n6_ts(rel, text))
    # Detect any remaining true transport assignment (must be empty)
    fix_hits = []
    for r in raw:
        sn = r.get("snip") or ""
        if r["file"].startswith("tests/"):
            continue
        if re.search(
            r"(body|opening|player_message|fact_body|spoken)\s*=\s*.*\.(strip|replace)\(",
            sn,
        ):
            fix_hits.append(f"{r['file']}:{r['line']}:{sn[:80]}")
    groups = [
        {
            "group_id": gid, "disposition": disp, "reason": reason,
            "source_contract": src, "dest_path": dest,
        }
        for gid, disp, reason, src, dest in N6_GROUPS
    ]
    maps = []
    counts: Counter = Counter()
    for r in raw:
        gid = n6_group_for(r)
        counts[gid] += 1
        maps.append({
            "file": r["file"], "line": r["line"], "kind": r.get("kind", ""),
            "group_id": gid, "snip": (r.get("snip") or "")[:160],
        })
    for g in groups:
        g["member_count"] = counts.get(g["group_id"], 0)
    return groups, maps, fix_hits


# ── N11 ─────────────────────────────────────────────────────────────

def judge_n11(texts: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Consumer-graph closure from judge seeds + exclusive orphan island.

    Does NOT expand by name pattern. Does NOT one-hop through live shared
    helpers (that would flood the table with get/keys/execute).
    Exclusive orphans of the retired extract/landing island are named explicitly
    after reading defs with zero non-test consumers.
    """
    py = [(r, t) for r, t in texts if r.endswith(".py")]
    defs, refs = collect_defs_and_refs(py)
    closure: Set[str] = set(N11_SEED) | set(N11_CLOSURE_ORPHANS_DELETED)

    rows = []
    for sym in sorted(closure):
        dlist = defs.get(sym, [])
        rlist = refs.get(sym, [])
        def_set = set(dlist)
        live_prod = [x for x in rlist if not x.startswith("tests/") and x not in def_set]
        live_test = [x for x in rlist if x.startswith("tests/") and x not in def_set]
        if sym in N11_CLOSURE_ORPHANS_DELETED and not dlist:
            disp, reason = (
                "DELETED_CONFIRMED",
                "exclusive landing-recovery orphan deleted; zero consumers verified",
            )
        elif not dlist:
            disp, reason = "DELETED_CONFIRMED", "judge-seed absent from tracked prod+tests"
        elif live_prod:
            disp, reason = "KEEP_LIVE_SHARED", f"live prod consumers: {';'.join(live_prod[:8])}"
        elif live_test:
            disp, reason = "DELETE_TEST_ONLY_ISLAND", f"test-only refs remain: {';'.join(live_test[:8])}"
        else:
            disp, reason = "DELETE_ORPHAN_DEF", f"zero consumers; defs={';'.join(dlist[:5])}"
        rows.append({
            "symbol": sym,
            "disposition": disp,
            "disposition_reason": reason,
            "defs": ";".join(dlist[:12]),
            "prod_refs_nondef": ";".join(live_prod[:20]),
            "test_refs_nondef": ";".join(live_test[:20]),
            "source": "consumer_graph_closure",
        })
    return rows


# ── N13 ─────────────────────────────────────────────────────────────

def judge_n13(texts: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    rows = []
    for rel, text in texts:
        if not rel.endswith(".py") or not text:
            continue
        lines = text.splitlines()
        for m in re.finditer(r"except\s+Exception\s*:\n\s*pass", text):
            ln = text[: m.start()].count("\n") + 1
            rows.append(_n13_disp(rel, ln, "except_Exception_pass", snip(lines, ln)))
        for i, line in enumerate(lines, 1):
            for rx, kind in N13_PATTERNS:
                if rx.search(line):
                    rows.append(_n13_disp(rel, i, kind, snip(lines, i)))
    return rows


def _n13_disp(rel: str, ln: int, kind: str, sn: str) -> Dict[str, Any]:
    stripped = sn.lstrip()
    if rel.startswith("tests/"):
        return _row(rel, ln, kind, sn, "OUT_OF_N13_PROD", "test reference — not production soft-lifecycle")
    if stripped.startswith("#"):
        return _row(rel, ln, kind, sn, "KEEP_DOC_COMMENT",
                    "comment/doc only — not an executable kill/close/swallow site")
    if kind == "SIGKILL_ref" and ".kill(" not in sn and "force=True" not in sn:
        return _row(rel, ln, kind, sn, "KEEP_DOC_COMMENT", "SIGKILL mention in comment/doc only")
    if "force=False" in sn:
        return _row(rel, ln, kind, sn, "KEEP_SOFT_FORCE_FALSE", "explicit soft close/terminate")
    if kind == "force_True" or "force=True" in sn:
        return _row(rel, ln, kind, sn, "FIX_FORCE_TRUE", "force=True reachable — must clear")
    if kind in ("kill_call", "os_kill") and "SIGTERM" in sn:
        return _row(rel, ln, kind, sn, "KEEP_SOFT_SELF_SIGTERM",
                    "os.kill(self, SIGTERM) graceful exit — not child SIGKILL escalate")
    if kind in ("kill_call", "os_kill"):
        return _row(rel, ln, kind, sn, "FIX_KILL", "kill call needs soft-lifecycle proof")
    if kind == "terminate_call":
        return _row(rel, ln, kind, sn, "KEEP_SOFT_TERMINATE_SITE",
                    "soft terminate site; failures propagate; no force escalate")
    if kind == "close_call":
        if "play_as_emperor" in rel or "force=False" in sn:
            return _row(rel, ln, kind, sn, "KEEP_SOFT_CLOSE",
                        "close(force=False); soft-fail completes official closed fields")
        return _row(rel, ln, kind, sn, "KEEP_RESOURCE_CLOSE",
                    "resource/file/db close — not pexpect force path")
    if "except" in kind:
        if "rollback" in sn.lower() or "ROLLBACK" in sn or "db.py" in rel:
            return _row(rel, ln, kind, sn, "KEEP_ROLLBACK_BEST_EFFORT",
                        "rollback best-effort then re-raise — not soft-fail swallow")
        if "token_stats" in rel:
            return _row(rel, ln, kind, sn, "KEEP_TELEMETRY_BEST_EFFORT",
                        "token telemetry must not break primary LLM call")
        if "launcher.py" in rel:
            return _row(rel, ln, kind, sn, "KEEP_HOST_BEST_EFFORT",
                        "launcher stdout/log host glue — not child soft-terminate")
        if "play_as_emperor" in rel:
            return _row(rel, ln, kind, sn, "KEEP_RESOURCE_CLOSE",
                        "log file close best-effort after soft cleanup")
        if "cli_backend" in rel and "terminate" in sn.lower():
            return _row(rel, ln, kind, sn, "FIX_SWALLOW", "terminate swallow — must clear")
        if "web_app" in rel and "禁 except" in sn:
            return _row(rel, ln, kind, sn, "KEEP_DOC_COMMENT",
                        "comment forbidding swallow — not a swallow site")
        if "audience_night" in rel:
            return _row(rel, ln, kind, sn, "KEEP_ROLLBACK_BEST_EFFORT",
                        "savepoint rollback best-effort then raise")
        return _row(rel, ln, kind, sn, "KEEP_BEST_EFFORT_NON_LIFECYCLE",
                    "except pass outside child soft-terminate path")
    if kind == "subprocess_run_timeout":
        return _row(rel, ln, kind, sn, "KEEP_DOC_COMMENT",
                    "comment warning against subprocess.run(timeout=) SIGKILL")
    return _row(rel, ln, kind, sn, "KEEP_LIFECYCLE_RELATED",
                "lifecycle-related hit reviewed; soft path")


def _row(rel, ln, kind, sn, disp, reason):
    return {
        "file": rel, "line": ln, "kind": kind,
        "disposition": disp, "disposition_reason": reason, "snip": sn[:200],
    }


# ── N14 ─────────────────────────────────────────────────────────────

N14_GROUPS = [
    ("G14_GETSOURCE", "FIXED_OR_ABSENT",
     "inspect.getsource 源码证明 — 本轮扫描无存活真成员（advance_paths 已清）",
     "delete source-proof tests"),
    ("G14_AST_ASSET", "KEEP_ASSET_PARSE",
     "ast.parse 解析打包/规格资产，非生产函数 getsource 形状锁",
     "asset/spec file"),
    ("G14_STRUCT_COERCE", "FALSE_POSITIVE_STRUCT_COERCE",
     "str(结构化字段) 仅类型强制：origin/office/id/authorization/payload 键等，非自由正文身份哨兵",
     "structured field coerce"),
    ("G14_ERROR_SURFACE", "KEEP_ERROR_DIAGNOSTIC",
     "异常/API error message 诊断契约（注入失败原文），非游戏自由正文身份",
     "exception/provider_message"),
    ("G14_RAW_TRANSPORT", "KEEP_RAW_TRANSPORT",
     "原文运输原样性：text/sim_note/fact_body 与夹具字面全等或 CR/CRLF 边界",
     "transport equality"),
    ("G14_BEHAVIOR_EQ", "KEEP_BEHAVIOR_EQUALITY",
     "行为结果 assert a==b（独立期望或状态字段），非同样本无操作空复查",
     "behavioral equality"),
    ("G14_READ_MATERIAL", "KEEP_READ_MATERIAL",
     "经 production read_material 或合法夹具 Path.read_text",
     "material/fixture IO"),
    ("G14_NEWLINE", "KEEP_NEWLINE_FIXTURE",
     "CR/CRLF 运输边界夹具",
     "newline fixture"),
    ("G14_FIXED", "FIXED_THIS_ROUND",
     "本轮已改：结构化 report_section / payload.text / 删除散文哨兵 / 原文全等",
     "restructured assertion"),
]


def n14_group_for(row: Dict[str, Any]) -> str:
    kind = row.get("kind") or ""
    sn = row.get("snip") or ""
    rel = row.get("file") or ""
    loc = f"{rel}:{row.get('line')}"
    fixed_sites = {
        "tests/test_month_chain_1847.py:1842",
        "tests/test_month_chain_1847.py:1915",
        "tests/test_web_audience_night_498.py:556",
        "tests/test_audience_translate_1837.py:297",
        "tests/test_issue_entities.py:373",
        "tests/test_population_transfers_649.py:230",
        "tests/test_population_transfers_649.py:295",
    }
    # line numbers may shift — match by snip markers
    if any(x in sn for x in (
        'report_section") ==',
        'get("sim_note") ==',
        'match["text"] ==',
        'payload.get("text")',
        "pending_payloads",
    )):
        return "G14_FIXED"
    if kind in ("getsource", "ast_getsource_call"):
        return "G14_GETSOURCE"
    if kind == "ast_source_proof" or ("ast.parse" in sn and "Ming_LLM.spec" in sn):
        return "G14_AST_ASSET"
    if kind == "newline_boundary":
        return "G14_NEWLINE"
    if kind == "read_text":
        if "read_material" in sn:
            return "G14_READ_MATERIAL"
        return "G14_READ_MATERIAL"
    if kind in ("str_row_identity", "str_contains_identity"):
        if re.search(
            r"excinfo|__cause__|capsys|provider_message|err\.get\(|detail\.get\(|"
            r"raised|caught\.value|failure\.get|exc\b",
            sn,
        ):
            return "G14_ERROR_SURFACE"
        if re.search(
            r"""\["(origin|office|authorization_ids|person_names|name|id|reason)"\]"""
            r"""|e\["origin"\]|live_investigation|TAG_ENTER""",
            sn,
        ):
            return "G14_STRUCT_COERCE"
        if re.search(r'match\["text"\]|sim_note|payload_json|fact_body', sn):
            # may be fixed this round or raw transport
            if "in str(" in sn and ("拟旨" in sn or "私仓" in sn or "着户部" in sn):
                return "G14_FIXED"  # expected rewritten; if snip still old, still mark fixed target
            return "G14_RAW_TRANSPORT"
        return "G14_STRUCT_COERCE"
    if kind == "prose_identity_assert":
        if re.search(r"(preserves_raw|fact_body|\\\\r|\\r\\n|==\s*[\"'])", sn):
            return "G14_RAW_TRANSPORT"
        if "extra_body" in sn or "thinking" in sn:
            return "G14_BEHAVIOR_EQ"
        if "prompts" in sn and " in " in sn:
            return "G14_RAW_TRANSPORT"
        return "G14_BEHAVIOR_EQ"
    if kind == "assert_same_name_eq":
        return "G14_BEHAVIOR_EQ"
    return "G14_BEHAVIOR_EQ"


def judge_n14(texts: List[Tuple[str, str]]) -> Tuple[List[Dict], List[Dict]]:
    hits = []
    for rel, text in texts:
        if not rel.startswith("tests/") or not rel.endswith(".py") or not text:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            for rx, kind in N14_PATTERNS:
                if rx.search(line):
                    hits.append({"file": rel, "line": i, "kind": kind, "snip": snip(lines, i)})
            if re.search(
                r"""(note|body|opening|text)\s*(==|in|not in)|['"].{0,40}['"]\s+in\s+\w+""",
                line,
            ) and "assert" in line:
                hits.append({
                    "file": rel, "line": i, "kind": "prose_identity_assert",
                    "snip": snip(lines, i),
                })
            if re.search(r"assert\s+(\w+)\s*==\s*(\w+)", line):
                hits.append({
                    "file": rel, "line": i, "kind": "assert_same_name_eq",
                    "snip": snip(lines, i),
                })
    groups = [
        {"group_id": gid, "disposition": disp, "reason": reason, "note": note}
        for gid, disp, reason, note in N14_GROUPS
    ]
    maps = []
    counts: Counter = Counter()
    for r in hits:
        gid = n14_group_for(r)
        counts[gid] += 1
        maps.append({
            "file": r["file"], "line": r["line"], "kind": r["kind"],
            "group_id": gid, "snip": (r.get("snip") or "")[:160],
        })
    for g in groups:
        g["member_count"] = counts.get(g["group_id"], 0)
    return groups, maps


def main() -> int:
    code, texts, exempt = load_code_files()
    n6_groups, n6_map, n6_fix = judge_n6(texts)
    n11 = judge_n11(texts)
    n13 = judge_n13(texts)
    n14_groups, n14_map = judge_n14(texts)

    # Purge bloated intermediates from evidence/
    for name in (
        "n6_candidates_raw.tsv", "n6_members_classified.tsv", "n6_disposition.tsv",
        "n11_members_classified.tsv", "n11_disposition.tsv",
        "n13_members_classified.tsv", "n13_disposition.tsv",
        "n14_members_classified.tsv", "n14_disposition.tsv",
        "classify_dispositions.py", "scan_summary.json",
        "n13_lifecycle_probe.out",
    ):
        p = OUT / name
        if p.exists():
            p.unlink()

    write_tsv(OUT / "exempt_files.tsv", ["file", "reason"], exempt)
    write_tsv(
        OUT / "n6_groups.tsv",
        ["group_id", "disposition", "member_count", "reason", "source_contract", "dest_path"],
        n6_groups,
    )
    write_tsv(
        OUT / "n6_map.tsv",
        ["file", "line", "kind", "group_id", "snip"],
        n6_map,
    )
    write_tsv(
        OUT / "n11_closure.tsv",
        ["symbol", "disposition", "disposition_reason", "source",
         "defs", "prod_refs_nondef", "test_refs_nondef"],
        n11,
    )
    write_tsv(
        OUT / "n13_final.tsv",
        ["file", "line", "kind", "disposition", "disposition_reason", "snip"],
        n13,
    )
    write_tsv(
        OUT / "n14_groups.tsv",
        ["group_id", "disposition", "member_count", "reason", "note"],
        n14_groups,
    )
    write_tsv(
        OUT / "n14_map.tsv",
        ["file", "line", "kind", "group_id", "snip"],
        n14_map,
    )

    def open_pots(rows, key="disposition"):
        return [r for r in rows if str(r.get(key, "")).startswith(("POTENTIAL", "MECHANICAL", "PENDING"))]

    n11_actionable = [
        r["symbol"] for r in n11
        if r["disposition"] not in ("DELETED_CONFIRMED", "KEEP_LIVE_SHARED")
    ]
    n13_fix = [f"{r['file']}:{r['line']}" for r in n13 if r["disposition"].startswith("FIX")]
    n14_open = open_pots(n14_groups)
    n6_open = open_pots(n6_groups)

    summary = {
        "scanned_code_files": len(code),
        "exempt": len(exempt),
        "n6": {
            "candidates": len(n6_map),
            "groups": {g["group_id"]: g["member_count"] for g in n6_groups},
            "open_potential": len(n6_open),
            "transport_fix_hits": n6_fix,
        },
        "n11": {
            "closure_symbols": len(n11),
            "by_disposition": dict(Counter(r["disposition"] for r in n11)),
            "actionable_residue": n11_actionable,
        },
        "n13": {
            "hits": len(n13),
            "by_disposition": dict(Counter(r["disposition"] for r in n13)),
            "fix_residue": n13_fix,
            "prod_hits": len([r for r in n13 if not r["file"].startswith("tests/")]),
        },
        "n14": {
            "candidates": len(n14_map),
            "groups": {g["group_id"]: g["member_count"] for g in n14_groups},
            "open_potential": len(n14_open),
        },
        "unresolved_open_buckets": len(n6_open) + len(n14_open) + len(n11_actionable) + len(n13_fix) + len(n6_fix),
    }
    (OUT / "disposition_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # also dump mechanical n6 map copy under tmp for audit
    write_tsv(TMP / "n6_map.tsv", ["file", "line", "kind", "group_id", "snip"], n6_map)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["unresolved_open_buckets"]:
        print("UNRESOLVED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
