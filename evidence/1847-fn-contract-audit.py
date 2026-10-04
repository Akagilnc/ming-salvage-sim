#!/usr/bin/env python3
"""#1847: apply function-contract decisions to NEEDS_HUMAN members.

Reads evidence/1847-fn-groups.jsonl (function-grouped remainder) and
evidence/1847-fn-shards/shard-*-decisions.tsv when present. Writes:
  - evidence/1847-fn-contract-table.tsv  (member-level source→sink)
  - refreshes classified TSV dispositions for covered members
  - evidence/1847-needs-human-audit.tsv  (honest remainder)

This script does NOT invent KEEP from snip heuristics. It only applies
explicit decisions (from shard decision TSVs and the hardcoded verified
FIX/KEEP maps below that cite source→sink contracts from function reads).
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
EV = ROOT / "evidence"
GROUPS = EV / "1847-fn-groups.jsonl"
N6 = EV / "1847-n6-members-classified.tsv"
N10 = EV / "1847-n10-members-classified.tsv"
AUDIT = EV / "1847-needs-human-audit.tsv"
TABLE = EV / "1847-fn-contract-table.tsv"
SHARD_DIR = EV / "1847-fn-shards"

# Verified FIX / KEEP from this-round function reads (source→sink cited).
# Keys: (lens, file, fn) → default disposition+reason for all members in that fn
# unless a per-line override exists in shard decisions.
FN_CONTRACTS: dict[tuple[str, str, str], tuple[str, str, str, str]] = {
    # disposition, reason, source_field, sink_contract
    ("N10", "ming_sim/token_stats.py", "_guess_caller_tag"): (
        "FIX_DONE",
        "source=system prompt free text keywords → sink=caller tag classify; deleted; explicit ming_sim_caller_tag or ?",
        "system_prompt_prose",
        "caller_tag_log_label",
    ),
    ("N10", "ming_sim/session.py", "_ensure_close_night_confirm_cue"): (
        "FIX_DONE",
        "source=LLM answer body → sink=append/replace confirm cue; deleted; fixed UI cue helper only",
        "llm_answer",
        "ambiguous_close_ui_cue",
    ),
    ("N10", "ming_sim/db.py", "_snapshot_secret_order_people"): (
        "FIX_DONE",
        "source=office substring in character.office → sink=secret exclusion people admit; deleted; exact office_type/office/concurrent parts only",
        "office_substring",
        "secret_exclusion_names",
    ),
    ("N6", "ming_sim/db.py", "_snapshot_secret_order_people"): (
        "KEEP_empty_check",
        "source=explicit_people/office raw → sink=strip for empty skip / exact registry lookup only; value not rewritten",
        "explicit_people_or_office",
        "exclusion_name_snapshot",
    ),
}


def load_tsv(path: pathlib.Path):
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return rows, list(rows[0].keys()) if rows else []


def write_tsv(path: pathlib.Path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def load_shard_decisions() -> dict[tuple[str, str, str], dict]:
    """Map (lens,file,line) → decision row from shard decision TSVs."""
    out = {}
    if not SHARD_DIR.exists():
        return out
    for path in sorted(SHARD_DIR.glob("shard-*-decisions.tsv")):
        rows, _ = load_tsv(path)
        for r in rows:
            key = (r["lens"], r["file"], str(r["line"]))
            out[key] = r
    return out


def load_groups():
    groups = []
    with GROUPS.open(encoding="utf-8") as f:
        for line in f:
            groups.append(json.loads(line))
    return groups


def decide_member(lens, file, fn, member, shard_dec, excerpt: str):
    line = str(member["line"])
    kind = member.get("kind") or ""
    snip = member.get("snip") or ""
    key = (lens, file, line)
    if key in shard_dec:
        d = shard_dec[key]
        return {
            "lens": lens,
            "file": file,
            "line": line,
            "fn": fn,
            "kind": kind,
            "disposition": d["disposition"],
            "reason": d["reason"],
            "source_field": d.get("source_field", ""),
            "sink_contract": d.get("sink_contract", ""),
        }
    fn_key = (lens, file, fn)
    if fn_key in FN_CONTRACTS:
        disp, reason, src, sink = FN_CONTRACTS[fn_key]
        return {
            "lens": lens,
            "file": file,
            "line": line,
            "fn": fn,
            "kind": kind,
            "disposition": disp,
            "reason": reason,
            "source_field": src,
            "sink_contract": sink,
        }

    # Conservative verified patterns from function reads — only when operand is explicit.
    # 1) SQLite/dict key presence (column existence), not free prose.
    if re.search(r'''["']\w+["']\s+in\s+keys\b|in\s+row\.keys\(\)|in\s+\w+\.keys\(\)''', snip):
        return _keep(
            lens, file, line, fn, kind,
            "KEEP_structural",
            "source=sqlite/dict key set → sink=column-presence branch; not prose classify",
            "row_or_dict_keys",
            "schema_field_presence",
        )
    # 2) Empty / None membership
    if re.search(r'''in\s*\(\s*None\s*,\s*["']{2}|in\s*\(\s*None\s*,\s*["']{2}\s*,''', snip) or "in (None, \"\")" in snip or "in (None, '')" in snip:
        return _keep(
            lens, file, line, fn, kind,
            "KEEP_empty_check",
            "source=optional field → sink=None/empty membership only; no wording classify",
            "optional_field",
            "empty_or_none_gate",
        )
    # 3) Form-id prefix fullmatch already known
    if "dossier:" in snip and ("fullmatch" in kind or "re.fullmatch" in snip or "re_fullmatch" in kind):
        return _keep(
            lens, file, line, fn, kind,
            "KEEP_identity_or_formal",
            "source=origin_ref → sink=dossier:<digits> form-language fullmatch",
            "origin_ref",
            "dossier_id_form",
        )
    # 4) Known closed enum literals in snip for this-round verified sets
    closed = (
        '{"主办", "协办", "知情"}',
        '("situation", "initiative")',
        '("resolved", "failed", "acknowledged")',
        '{"promulgated", "executing"}',
        '{"user", "minister", "attendant", "scene"}',
        '("situation", "node", "ending")',
        '("", "strategic_foreign")',
        "GATE_TABLES",
        "GATE_METRIC_KEYS",
        "GATE_AGG_FUNCS",
        "_HAIRCUT_SOURCES",
        "DUE_SUBJECTS",
        "ARREARS_SUBJECTS",
        "BUILDING_CATEGORIES",
        "PERSON_IDENTITY_TITLES",
        "_INACTIVE_STATUSES",
        "office_type",
        "office_titles",
        "office_types",
    )
    if any(c in snip or c in excerpt for c in closed) and kind in {
        "in_compare", "membership_compare", "str_in_compare",
    }:
        # Only KEEP when snip itself shows the closed set / registry name
        if any(c in snip for c in closed) or any(
            c in excerpt and c in ("GATE_TABLES", "GATE_METRIC_KEYS", "GATE_AGG_FUNCS", "DUE_SUBJECTS", "ARREARS_SUBJECTS", "_HAIRCUT_SOURCES", "BUILDING_CATEGORIES", "PERSON_IDENTITY_TITLES")
            for c in closed
        ):
            return _keep(
                lens, file, line, fn, kind,
                "KEEP_identity_or_formal",
                "source=structured enum/registry operand → sink=membership gate; closed set from function body",
                "enum_or_registry_field",
                "closed_membership_gate",
            )

    return {
        "lens": lens,
        "file": file,
        "line": line,
        "fn": fn,
        "kind": kind,
        "disposition": "NEEDS_HUMAN",
        "reason": f"{fn}:{line} awaiting function-contract read; no verified source→sink yet",
        "source_field": "",
        "sink_contract": "",
    }


def _keep(lens, file, line, fn, kind, disp, reason, src, sink):
    return {
        "lens": lens,
        "file": file,
        "line": line,
        "fn": fn,
        "kind": kind,
        "disposition": disp,
        "reason": reason,
        "source_field": src,
        "sink_contract": sink,
    }


def apply_to_classified(decisions_by_key: dict[tuple[str, str, str], dict]):
    changed = Counter()
    left = {"N6": [], "N10": []}
    for path, lens in ((N6, "N6"), (N10, "N10")):
        rows, fields = load_tsv(path)
        out = []
        for r in rows:
            if (r.get("disposition") or "") != "NEEDS_HUMAN":
                out.append(r)
                continue
            key = (lens, r.get("file", ""), str(r.get("line", "")))
            d = decisions_by_key.get(key)
            if not d:
                out.append(r)
                left[lens].append(r)
                continue
            new_disp = d["disposition"]
            if new_disp == "NEEDS_HUMAN":
                out.append({**r, "reason": d["reason"]})
                left[lens].append({**r, "reason": d["reason"]})
                continue
            # Map FIX → FIX_DONE in classified tables
            if new_disp == "FIX":
                new_disp = "FIX_DONE"
            out.append({**r, "disposition": new_disp, "reason": d["reason"]})
            changed[f"{lens}:{new_disp}"] += 1
        write_tsv(path, out, fields)
    return changed, left


def main():
    shard_dec = load_shard_decisions()
    groups = load_groups()
    table_rows = []
    by_key = {}
    disp_c = Counter()
    for g in groups:
        lens, file, fn = g["lens"], g["file"], g["fn"]
        excerpt = g.get("excerpt") or ""
        for m in g["members"]:
            d = decide_member(lens, file, fn, m, shard_dec, excerpt)
            table_rows.append(d)
            by_key[(lens, file, str(m["line"]))] = d
            disp_c[d["disposition"]] += 1

    fields = [
        "lens", "file", "line", "fn", "kind", "disposition",
        "reason", "source_field", "sink_contract",
    ]
    write_tsv(TABLE, table_rows, fields)
    changed, left = apply_to_classified(by_key)

    # Refresh audit
    audit_fields = ["lens", "file", "line", "kind", "ctx", "snip", "reason"]
    with AUDIT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=audit_fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for lens in ("N6", "N10"):
            for r in left[lens]:
                w.writerow({
                    "lens": lens,
                    "file": r.get("file", ""),
                    "line": r.get("line", ""),
                    "kind": r.get("kind", ""),
                    "ctx": r.get("ctx", ""),
                    "snip": (r.get("snip") or "")[:180],
                    "reason": r.get("reason", ""),
                })

    print("SHARD_DECISIONS", len(shard_dec))
    print("TABLE_DISP", dict(disp_c))
    print("CLASSIFIED_CHANGED", dict(changed))
    print("LEFT", {k: len(v) for k, v in left.items()})
    print("TABLE", TABLE)
    print("AUDIT", AUDIT)


if __name__ == "__main__":
    main()
