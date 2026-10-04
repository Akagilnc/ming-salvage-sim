#!/usr/bin/env python3
"""Second-pass dispositions for #1847 w7 — source/sink & consumer closure.

Mechanical discovery TSVs remain the full set. This file writes disposition
tables with explicit evidence, no KEEP-by-name-guess on retired islands.
"""
from __future__ import annotations

import ast
import csv
import json
import pathlib
import re
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = pathlib.Path("/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5")
OUT = ROOT / "evidence" / "1847-w7-correction"

# Free-text field / variable names from class definition + prior tickets
FREE_TEXT_NAMES = {
    "body", "fact_body", "opening", "player_message", "message", "content",
    "prompt", "scene_prompt", "narrative", "prose", "raw_text", "raw_body",
    "story", "ledger_body", "spoken", "raw_latest", "reply", "utterance",
    "condition_text", "condition", "gazette", "邸报", "text", "chunk",
    "cli_chunk", "action", "input_text", "user_text", "reason_text",
}

JUDGE_N11_SEEDS = [
    "rescript_summon_origin_ref",
    "rescript_summon_origin_consumed",
    "prepare_rescript_summon_scaffold",
    "RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES",
    "find_deliberation_dossier_by_decision_key",
    "_extract_secret_order",
    "assemble_secret_order_content",
    "_DRAFT_PREFIXES",
    "_SECRET_PREFIXES",
    "_CLAUSE_SPLIT",
    "confirm_dossier_links",
    "_ledger_by_origin_ref",
    "_so_json",
]


def load_tsv(name: str) -> List[Dict[str, str]]:
    with (OUT / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(name: str, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def n6_disposition(row: Dict[str, str]) -> Tuple[str, str]:
    rel = row["file"]
    sn = row.get("snip") or ""
    kind = row.get("kind") or ""
    ctx = row.get("ctx") or ""
    if rel.startswith("tests/"):
        return "OUT_OF_N6_CLASS", "test file — identity proofs owned by N14"
    # scripts play_as_emperor: form/json envelope vs free text
    if "play_as_emperor" in rel and "json" in sn.lower():
        return "KEEP_FORM_LANGUAGE", "JSON envelope / form locate; not free-text transport sink"
    # free-text name involvement
    free = any(
        re.search(rf"\b{re.escape(n)}\b", sn) or re.search(rf"['\"]b?{re.escape(n)}['\"]", sn)
        for n in FREE_TEXT_NAMES
    )
    if not free and kind.startswith("call.strip"):
        # id/name/status/method strips — identifiers, not 自由正文
        if re.search(r"\b(name|status|method|origin|ref|id|key|code|path|model|runner)\b", sn, re.I):
            return "KEEP_IDENTIFIER_NORMALIZE", "identifier/enum normalize — not free-text body transport"
    if row.get("mech_bucket") == "POTENTIAL_EMPTY_LOCAL" and free:
        return "KEEP_EMPTY_LOCAL", "empty-local strip/trim on free text; transport must use original"
    if free and ("strip" in kind or "trim" in kind or "replace" in kind or "slice" in kind):
        # assignment into transport?
        if re.search(r"(body|opening|player_message|content|spoken|raw_)\s*=\s*.*\.(strip|replace|trim)", sn):
            return "FIX_TRANSPORT_MUTATION", "free-text assigned from mutating call — clear or prove non-transport"
        if re.search(r"\.(strip|replace|trim)\s*\(.*\).*append|append\(.*\.(strip|replace)", sn):
            return "FIX_TRANSPORT_MUTATION", "free-text mutated then appended to transport"
        if "replace" in kind and free:
            return "POTENTIAL_FREE_REPLACE", "free-text replace — verify sink"
        return "POTENTIAL_FREE_TEXT", "free-text mutator nearby — verify source→sink"
    if "read_text" in kind:
        return "POTENTIAL_READ_TEXT", "read_text transform — verify newline/raw boundary"
    return "MECHANICAL_OTHER", "mutator without free-text field cue — not auto-FIX"


def classify_n6() -> List[Dict[str, Any]]:
    rows = load_tsv("n6_members_classified.tsv")
    out = []
    for r in rows:
        disp, reason = n6_disposition(r)
        out.append({**r, "disposition": disp, "disposition_reason": reason})
    return out


def classify_n11() -> List[Dict[str, Any]]:
    """Seed + one-hop callees from seed defs only. Name-pattern orphans ≠ retired."""
    raw = {r["symbol"]: r for r in load_tsv("n11_members_classified.tsv")}
    out = []
    for sym in JUDGE_N11_SEEDS:
        r = raw.get(sym, {
            "symbol": sym, "disposition": "ABSENT", "reason": "missing from scan",
            "def_count": "0", "prod_ref_count": "0", "test_ref_count": "0",
            "defs": "", "prod_refs_nondef": "", "test_refs_nondef": "",
        })
        # Re-label with closure semantics
        if r.get("disposition") == "ABSENT" or r.get("def_count") == "0":
            disp = "DELETED_CONFIRMED"
            reason = "judge-seed retired symbol absent from tracked prod+tests"
        elif int(r.get("prod_ref_count") or 0) > 0:
            disp = "KEEP_LIVE_SHARED"
            reason = f"live production consumers: {r.get('prod_refs_nondef')}"
        elif int(r.get("test_ref_count") or 0) > 0:
            disp = "DELETE_TEST_ONLY_ISLAND"
            reason = f"test-only refs remain: {r.get('test_refs_nondef')}"
        else:
            disp = "DELETE_ORPHAN_DEF"
            reason = f"defs with zero consumers: {r.get('defs')}"
        out.append({
            "symbol": sym,
            "disposition": disp,
            "disposition_reason": reason,
            "defs": r.get("defs", ""),
            "prod_refs_nondef": r.get("prod_refs_nondef", ""),
            "test_refs_nondef": r.get("test_refs_nondef", ""),
            "source": "judge_seed_closure",
        })
    # Name-pattern expansions that are NOT in seed: mark as NOT_AUTO_RETIRE
    for sym, r in sorted(raw.items()):
        if sym in JUDGE_N11_SEEDS:
            continue
        out.append({
            "symbol": sym,
            "disposition": "NOT_AUTO_RETIRE_NAME_PATTERN",
            "disposition_reason": (
                "discovered by name cue only; not in judge seed closure — "
                f"mech={r.get('disposition')} defs={r.get('def_count')} "
                f"prod={r.get('prod_ref_count')} test={r.get('test_ref_count')}"
            ),
            "defs": r.get("defs", ""),
            "prod_refs_nondef": r.get("prod_refs_nondef", ""),
            "test_refs_nondef": r.get("test_refs_nondef", ""),
            "source": "name_pattern_expansion_not_authority",
        })
    return out


def classify_n13() -> List[Dict[str, Any]]:
    rows = load_tsv("n13_members_classified.tsv")
    out = []
    for r in rows:
        rel, kind, sn = r["file"], r["kind"], r.get("snip") or ""
        if rel.startswith("tests/"):
            disp, reason = "TEST_HIT", "test reference"
        elif kind == "SIGKILL_ref" and r.get("mech_bucket") == "MECHANICAL_DOC":
            disp, reason = "KEEP_DOC_COMMENT", "SIGKILL word in comment/doc — not a call"
        elif "force=False" in sn or "force = False" in sn:
            disp, reason = "KEEP_SOFT_FORCE_FALSE", "explicit soft close/terminate"
        elif kind == "force_True" or "force=True" in sn:
            disp, reason = "FIX_FORCE_TRUE", "force=True can escalate to SIGKILL"
        elif kind in ("kill_call", "os_kill") and "SIGTERM" in sn:
            disp, reason = "POTENTIAL_SOFT_KILL_SIGTERM", "os.kill/SIGTERM — confirm not escalate"
        elif kind in ("kill_call", "os_kill"):
            disp, reason = "POTENTIAL_KILL", "kill call — confirm soft lifecycle"
        elif kind == "terminate_call":
            if "cli_backend" in rel or "play_as_emperor" in rel:
                disp, reason = "KEEP_SOFT_TERMINATE_SITE", "soft terminate site under N13 fix"
            else:
                disp, reason = "POTENTIAL_TERMINATE", "terminate call — verify no force escalate"
        elif kind == "close_call":
            if "force=False" in sn:
                disp, reason = "KEEP_SOFT_CLOSE", "close(force=False)"
            elif "play_as_emperor" in rel:
                disp, reason = "KEEP_SOFT_CLOSE", "play_as_emperor soft close path"
            else:
                disp, reason = "KEEP_RESOURCE_CLOSE", "generic close — not pexpect force path"
        elif "except" in kind or "SWALLOW" in r.get("mech_bucket", ""):
            if "cli_backend" in rel and "terminate" in sn.lower():
                disp, reason = "FIX_SWALLOW", "terminate swallow"
            else:
                disp, reason = "POTENTIAL_SWALLOW", "except pass — verify not soft-fail swallow"
        else:
            disp, reason = "POTENTIAL_N13", "lifecycle-related hit"
        out.append({**r, "disposition": disp, "disposition_reason": reason})
    return out


def classify_n14() -> List[Dict[str, Any]]:
    rows = load_tsv("n14_members_classified.tsv")
    out = []
    for r in rows:
        kind, sn, rel = r["kind"], r.get("snip") or "", r["file"]
        if kind in ("getsource", "ast_getsource_call"):
            disp, reason = "FIX_DELETE_GETSOURCE", "inspect.getsource proof test"
        elif kind == "ast_source_proof":
            disp, reason = "POTENTIAL_AST_PROOF", "AST source proof — verify necessity"
        elif kind in ("str_row_identity", "str_contains_identity"):
            disp, reason = "FIX_STR_IDENTITY", "str(row)/str() identity sentinel"
        elif kind == "prose_identity_assert":
            # raw transport equality is allowed by boundary
            if re.search(r"(preserves_raw|byte_equal|raw_equal|fact_body|\\\\r|\\r\\n)", sn):
                disp, reason = "KEEP_RAW_TRANSPORT_ASSERT", "原文运输原样性 — not identity stare"
            else:
                disp, reason = "POTENTIAL_PROSE_SENTINEL", "prose/note identity — verify structured field"
        elif kind == "assert_same_name_eq":
            disp, reason = "POTENTIAL_SAME_VALUE", "assert a==b — verify not vacuous same-sample recheck"
        elif kind == "read_text":
            if "read_material" in sn:
                disp, reason = "KEEP_READ_MATERIAL", "uses production read_material"
            else:
                disp, reason = "POTENTIAL_BYPASS_READ", "Path.read_text — verify not bypassing read_material"
        elif kind == "newline_boundary":
            disp, reason = "KEEP_NEWLINE_FIXTURE", "CR/CRLF boundary fixture for transport"
        else:
            disp, reason = "POTENTIAL_N14", kind
        out.append({**r, "disposition": disp, "disposition_reason": reason})
    return out


def main() -> int:
    n6 = classify_n6()
    n11 = classify_n11()
    n13 = classify_n13()
    n14 = classify_n14()
    write_tsv(
        "n6_disposition.tsv",
        ["file", "line", "kind", "ctx", "disposition", "disposition_reason", "snip"],
        n6,
    )
    write_tsv(
        "n11_disposition.tsv",
        ["symbol", "disposition", "disposition_reason", "source", "defs",
         "prod_refs_nondef", "test_refs_nondef"],
        n11,
    )
    write_tsv(
        "n13_disposition.tsv",
        ["file", "line", "kind", "disposition", "disposition_reason", "snip"],
        n13,
    )
    write_tsv(
        "n14_disposition.tsv",
        ["file", "line", "kind", "disposition", "disposition_reason", "snip"],
        n14,
    )

    def count(rows, key="disposition"):
        from collections import Counter
        return dict(Counter(r[key] for r in rows))

    summary = {
        "n6": count(n6),
        "n11_seed": count([r for r in n11 if r["source"] == "judge_seed_closure"]),
        "n11_name_pattern_not_authority": len([r for r in n11 if r["source"] != "judge_seed_closure"]),
        "n13": count(n13),
        "n14": count(n14),
        "n6_fix_transport": [
            f"{r['file']}:{r['line']}" for r in n6 if r["disposition"] == "FIX_TRANSPORT_MUTATION"
        ],
        "n11_seed_actionable": [
            r["symbol"] for r in n11
            if r["source"] == "judge_seed_closure"
            and r["disposition"] not in ("DELETED_CONFIRMED", "KEEP_LIVE_SHARED")
        ],
        "n13_fix": [f"{r['file']}:{r['line']}:{r['kind']}" for r in n13 if r["disposition"].startswith("FIX")],
        "n14_fix": [f"{r['file']}:{r['line']}:{r['kind']}" for r in n14 if r["disposition"].startswith("FIX")],
    }
    (OUT / "disposition_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
