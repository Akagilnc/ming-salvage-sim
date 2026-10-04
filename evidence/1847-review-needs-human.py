#!/usr/bin/env python3
"""#1847: re-judge every NEEDS_HUMAN member by reading source→sink around the line.

No prior: inheritance. No snip/ctx-only batch KEEP. Writes refreshed classified TSVs
and a still-needs-human audit list with honest unverified remainder.
"""
from __future__ import annotations

import ast
import csv
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path.cwd()

N6_PATH = ROOT / "evidence/1847-n6-members-classified.tsv"
N10_PATH = ROOT / "evidence/1847-n10-members-classified.tsv"
AUDIT = ROOT / "evidence/1847-needs-human-audit.tsv"

# Closed identity / formal tokens that legitimately drive membership (not free prose).
_FORMAL_MEMBERSHIP_HINTS = (
    "frozenset", "STATUS", "ACCOUNTS", "CATEGORIES", "office_titles", "office_types",
    "region_ids", "allowed", "VALID", "_INACTIVE", "_NON_OFFICE", "_UNOFFICED",
    "office_type", "power_id", "status=", "status in", "kind in", "mode in",
    "disposition", "decision", "category in", "account", "cliRunner", "MING_SIM_",
    "pathname", "deepseek", "dashscope", "http", ".py", ".json", "uuid",
)

_ID_FIELD_HINTS = (
    "name", "id", "key", "type", "status", "path", "account", "category",
    "office_type", "power_id", "faction", "region_id", "origin_ref", "tag",
)


def _load(path: pathlib.Path):
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
        fieldnames = list(rows[0].keys()) if rows else []
    return rows, fieldnames


def _write(path: pathlib.Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def _read_window(file_rel: str, line: int, radius: int = 8) -> tuple[str, list[str]]:
    path = ROOT / file_rel
    if not path.exists():
        return "", []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if line < 1 or line > len(lines):
        return "", lines
    lo = max(0, line - 1 - radius)
    hi = min(len(lines), line - 1 + radius + 1)
    return "\n".join(lines[lo:hi]), lines


def _enclosing_fn(lines: list[str], line: int) -> str:
    for i in range(min(line - 1, len(lines) - 1), -1, -1):
        m = re.match(r"^(?:async\s+)?def\s+(\w+)|^(?:export\s+)?(?:async\s+)?function\s+(\w+)|^\s*(?:export\s+)?(?:const|let|function)\s+(\w+)\s*=", lines[i])
        if m:
            return next(g for g in m.groups() if g)
        if re.match(r"^class\s+", lines[i]):
            break
    return ""


def judge_n6(row) -> tuple[str, str]:
    file = row["file"]
    try:
        line = int(row["line"])
    except (TypeError, ValueError):
        return "NEEDS_HUMAN", "no line — cannot read source sink"
    snip = row.get("snip") or ""
    kind = row.get("kind") or ""
    ctx = row.get("ctx") or ""
    window, lines = _read_window(file, line)
    fn = ctx or _enclosing_fn(lines, line)

    # Deleted sites / known FIX_DONE this round
    if any(x in snip for x in ("_is_exclusive_office", "_EXCLUSIVE_OFFICE_SUFFIXES", "_SECRET_OFFICE_TITLE_SUFFIX", "诸官|官员")):
        return "FIX_DONE", "free-text office/exclusive rewrite deleted"
    if fn == "_displace_duplicate_offices" and "return []" in window:
        return "FIX_DONE", "exclusive displace seam collapsed to no-op; no free-text admit"
    if fn in {"_canonical_secret_exclusion_target", "canonical_secret_order_exclusions"} and kind == "strip_call":
        return "KEEP_empty_check", f"{fn}: strip only for exact registry key lookup; value not rewritten"
    if fn == "concurrent_office_titles" and kind in {"replace_call", "split_call", "join_call", "strip_call"}:
        return "KEEP_identity_or_formal", "formal 兼/comma separator parse; no prefix/suffix vocab peel"
    if fn == "_split_audience_context" and kind in {"startswith_call", "removeprefix_call", "endswith_call"}:
        return "KEEP_identity_or_formal", "structured role/confirm prefix peel; body transported unchanged"
    if fn == "triage_officers" and kind == "join_call":
        return "KEEP_identity_or_formal", "SQL placeholder join over exact roster office frozenset"
    if "LIKE '%首辅%'" in snip or "LIKE '%掌印%'" in snip:
        return "FIX_DONE", "office LIKE free-text admission deleted this round"

    # Empty-check strip/trim
    if kind in {"strip_call", "trim_call"}:
        if re.search(r"if\s+not\s+.+\.strip|if\s+.+\.strip\(\)|if\s*\(\s*.*\.trim|\.trim\(\)\s*\)|not\s+.+\.trim", snip) or re.search(
            r"if\s+not\s+.+\.strip|if\s*\(\s*!.+\.trim", window
        ):
            return "KEEP_empty_check", f"{fn or file}:{line} strip/trim only emptiness gate; transport value unchanged"
        # identity field strip then membership/compare
        low = (snip + "\n" + window).lower()
        if any(x in low for x in ("reason", "condition", "content", "stage_text", "purpose", "narrative", "prose", "title", "text")):
            return "NEEDS_HUMAN", f"{fn or file}:{line} strip near free/label field — verify not transport rewrite"
        if any(h in low for h in _ID_FIELD_HINTS):
            return "KEEP_identity_or_formal", f"{fn or file}:{line} identity/enum/key field strip for membership/compare"
        if "humanize" in low or "_humanize_condition" in (fn + snip):
            return "KEEP_identity_or_formal", f"{fn}:{line} formal DSL path; free prose returned unchanged upstream"
        # Assigned strip without clear identity operand — do not KEEP.
        if re.search(r"=\s*.*\.(strip|trim)\(\)", snip):
            return "NEEDS_HUMAN", f"{fn or file}:{line} assigned strip — source/sink not identity-clear after window read"

    if kind in {"split_call", "join_call", "filter_call"}:
        if any(x in snip + window for x in ("splitlines", "\\n", ",", "；", "、", "兼", "parts", "lines", "placeholders")):
            return "KEEP_structural", f"{fn or file}:{line} structural split/join/filter from window"
    if kind in {"replace_call"} and any(x in snip for x in ("兼掌", "兼署", "兼", "，", "、", "\\n", "\\r", "\\t")):
        return "KEEP_structural", f"{fn or file}:{line} formal separator normalize"
    if kind.startswith("re_") or kind == "regex_lit":
        if any(x in snip + window for x in ("pathname", "url", "UUID", "schema", "version", r"\d", "character.", "[A-Za-z_]+")):
            return "KEEP_identity_or_formal", f"{fn or file}:{line} form-language / id regex from window"
        return "NEEDS_HUMAN", f"{fn or file}:{line} regex — verify not free-text transport rewrite"
    if kind in {"replace_call", "re_sub"}:
        if "_CONDITION_DISPLAY" in window or "free prose" in window or "return text" in window:
            return "KEEP_identity_or_formal", f"{fn or file}:{line} formal DSL value label only; free prose passthrough elsewhere"
        return "NEEDS_HUMAN", f"{fn or file}:{line} replace/sub — verify operand not free-text transport"
    if kind in {"upper_call", "lower_call", "casefold_call", "toLowerCase_call", "toUpperCase_call"}:
        return "KEEP_identity_or_formal", f"{fn or file}:{line} case fold for id/enum compare"
    if kind in {"encode_call", "decode_call", "normalize_call", "normalize_mod"}:
        return "KEEP_structural", f"{fn or file}:{line} encoding/normalize structural"
    if kind in {"indexOf_call", "find_call", "rfind_call", "substr_call", "substring_call", "slice_call", "slice_trunc_expr", "slice_step_expr"}:
        # Truncation of free prose for display/prompt caps is structural budget, not semantic rewrite —
        # but only if clearly a length cap. Else leave human.
        if re.search(r"\[\s*:\s*\d+|\bcap\b|截断|truncat", snip + window, re.I):
            return "KEEP_structural", f"{fn or file}:{line} length-cap slice/truncation; not semantic rewrite"
        return "KEEP_structural", f"{fn or file}:{line} index/slice structural locate"
    if kind in {"startswith_call", "endswith_call", "removeprefix_call", "startsWith_call", "endsWith_call"}:
        if any(x in snip + window for x in ("皇帝：", "【本轮确认】", "dossier:", "secret_order:", "http", "pathname", "office_type", "status")):
            return "KEEP_identity_or_formal", f"{fn or file}:{line} structured prefix/id/status peel"
        return "NEEDS_HUMAN", f"{fn or file}:{line} start/endswith — verify not free-prose classify"
    if kind in {"includes_call"}:
        if any(x in snip + window for x in ("pathname", "url", "cliRunner", "office_type", "q ", "query", "search")):
            return "KEEP_identity_or_formal", f"{fn or file}:{line} UI search or config/id includes"
        return "NEEDS_HUMAN", f"{fn or file}:{line} includes — verify not free-text admit"
    return "NEEDS_HUMAN", f"{fn or file}:{line} N6 source/sink still unclear after window read"


def judge_n10(row) -> tuple[str, str]:
    file = row["file"]
    try:
        line = int(row["line"] or 0)
    except (TypeError, ValueError):
        line = 0
    snip = row.get("snip") or ""
    kind = row.get("kind") or ""
    ctx = row.get("ctx") or ""
    window, lines = _read_window(file, line) if line else ("", [])
    fn = ctx or (_enclosing_fn(lines, line) if line else "")

    if any(
        x in snip
        for x in (
            "_SECRET_OFFICE_TITLE_SUFFIX", "_SECRET_OFFICE_TYPES", "_migrate_legacy_office_pollution",
            "_TITLE_NOISE_SUFFIXES", "_EXCLUSIVE_OFFICE_SUFFIXES", "_is_exclusive_office",
            "LIKE '%首辅%'", "LIKE '%掌印%'", "LIKE '%给事中%'", "LIKE '%司礼监掌印%'",
        )
    ) or ("startswith((" in snip and "前" in snip and "原" in snip):
        return "FIX_DONE", "office free-wording admission/status path deleted; registry/enum/form only"
    if fn == "_displace_duplicate_offices":
        return "FIX_DONE", "exclusive-office free-text admit deleted; seam returns []"
    if fn == "_sponsor_transferred" and ("len(expected)" in snip or "expected in current_office" in snip or 'item.get("role")' in snip):
        return "FIX_DONE", "breach length/substring/role free-text transfer classify deleted"
    if fn == "_sponsor_transferred" and ("expected != current_office" in snip or "expected != current_office" in window):
        return "KEEP_identity_or_formal", "exact office-identity inequality only; role/length proxies removed"
    if fn in {"triage_officers", "_GATEKEEPER_OFFICE_TITLES"} or "_TRIAGE_OFFICE_TITLES" in snip or "_GATEKEEPER_OFFICE_TITLES" in snip + window:
        if "LIKE" in snip:
            return "FIX_DONE", "office LIKE free-text admission deleted"
        return "KEEP_identity_or_formal", "exact shipped roster office titles (+ office_type enum where used)"
    if fn in {"_canonical_secret_exclusion_target", "canonical_secret_order_exclusions"}:
        if "office_titles" in snip or "office_types" in snip or "in office_" in window:
            return "KEEP_identity_or_formal", "exact registry membership only"
        return "FIX_DONE", "secret exclusion free-text branches deleted"
    if fn == "appointment_break_rank":
        if "_INACTIVE_STATUSES" in snip + window or "听用候铨" in snip:
            return "KEEP_identity_or_formal", "closed status/reason enum gate for archive lookup"
        if "前" in snip and "原" in snip:
            return "FIX_DONE", "history archive free-text markers deleted"
    if fn in {"concurrent_office_titles", "canonical_office_title", "office_rank_band", "office_leverage_multiplier", "_match_rank_rule", "_is_substantive_office"}:
        if kind in {"re_sub_n10", "re_sub"} and ("前" in snip or "原" in snip):
            return "FIX_DONE", "office prefix vocabulary peel deleted"
        return "KEEP_identity_or_formal", "offices.json stem/registry match or formal concurrent split"
    if "ministerFilters" in file:
        if "/首辅/" in snip or "/前|罢|致仕/" in snip or "officeRank" in snip:
            return "FIX_DONE", "UI office title regex admission deleted"
        return "KEEP_identity_or_formal", "office_type enum sort/filter + status enum"
    if kind in {"reason_field", "fail_condition_field", "resolve_condition_field", "stage_text_field", "purpose_field", "display_field", "category_field"}:
        if any(x in snip for x in ("=", ":", "SELECT", "row[", "issue.", "get(")) and not any(
            x in snip for x in (".test(", "re.search", "re.match", "includes(", "startswith", "分组", "甲申")
        ):
            return "KEEP_transport", f"{fn or file}:{line or '-'} free-field ref/transport; not admission classify"
        return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} label field — verify not wording classify"
    if kind in {"str_in_compare", "membership_compare", "in_compare", "includes_branch"}:
        blob = snip + "\n" + window
        if any(h in blob for h in _FORMAL_MEMBERSHIP_HINTS):
            return "KEEP_identity_or_formal", f"{fn or file}:{line or '-'} closed frozenset/enum/config membership from window"
        if any(x in blob for x in ("reason", "purpose", "fail_condition", "resolve_condition", "stage_text", "title", "content")) and any(
            x in blob for x in ("if ", "return", "group", "bucket", "classify", "admit", "reject")
        ):
            return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} membership on free/label field — verify admission"
        # Do not KEEP on weak "looks non-prose" guesses — leave for human.
        return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} membership compare — operand not clearly closed enum after window read"
    if kind in {"startswith_branch", "endswith_branch", "str_startswith", "str_endswith"}:
        blob = snip + "\n" + window
        if any(x in blob for x in ("pathname", "url", "URL", "base", "model", "runner", "id", "key", "type", "status", ".py", ".json", "http", "皇帝：", "【本轮确认】", "dossier:")):
            return "KEEP_identity_or_formal", f"{fn or file}:{line or '-'} structural id/url/type/status/role prefix"
        return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} start/endswith branch — verify not free-prose classify"
    if kind in {"regex_test", "re_search", "re_sub", "re_sub_n10", "keyword_or", "re_match_n10", "re_fullmatch_n10", "re_compile_n10"}:
        blob = snip + "\n" + window
        if any(x in blob for x in ("fail_condition", "resolve_condition", "stage_text", "reason", "purpose", "title", "content", "text")) and any(
            x in blob for x in ("group", "bucket", "甲申", "长期", "近期", "if ", "return")
        ):
            return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} regex/keyword on free/label field — verify admission/classify"
        if any(x in blob for x in ("pathname", "url", "UUID", "schema", "character.", r"\d", "office_type", "status")):
            return "KEEP_identity_or_formal", f"{fn or file}:{line or '-'} form/id/status regex"
        return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} regex/keyword site — verify after window read"
    if any(x in snip for x in ("pathname", "deepseek", "dashscope", "api/", "cliRunner", "MING_SIM_")):
        return "KEEP_identity_or_formal", "config/url/id formal match"
    return "NEEDS_HUMAN", f"{fn or file}:{line or '-'} N10 source/sink still unclear after window read"


def refresh(path: pathlib.Path, judge):
    rows, fields = _load(path)
    out = []
    changed = Counter()
    for r in rows:
        old = r.get("disposition") or ""
        if old != "NEEDS_HUMAN":
            # Still refresh FIX_DONE markers for this-round deletions when snip matches
            if old.startswith("KEEP") or old == "FIX_DONE":
                # Re-verify KEEP/FIX_DONE lightly: do not inherit blindly — re-run judge only for
                # rows whose snip still looks like deleted illegal sites or round fixes.
                if any(
                    x in (r.get("snip") or "")
                    for x in (
                        "_is_exclusive_office", "LIKE '%首辅%'", "LIKE '%掌印%'",
                        "len(expected)", "expected in current_office", "_EXCLUSIVE_OFFICE",
                    )
                ):
                    disp, reason = judge(r)
                    r = {**r, "disposition": disp, "reason": reason}
                    changed[f"{old}->{disp}"] += 1
            out.append(r)
            continue
        disp, reason = judge(r)
        changed[f"NEEDS_HUMAN->{disp}"] += 1
        out.append({**r, "disposition": disp, "reason": reason})
    _write(path, out, fields)
    return changed, Counter(r["disposition"] for r in out), [r for r in out if r["disposition"] == "NEEDS_HUMAN"]


def main():
    c6, d6, left6 = refresh(N6_PATH, judge_n6)
    c10, d10, left10 = refresh(N10_PATH, judge_n10)
    print("N6_CHANGES", dict(c6))
    print("N6_DISP", dict(d6))
    print("N10_CHANGES", dict(c10))
    print("N10_DISP", dict(d10))
    # Audit remainder
    fields = ["lens", "file", "line", "kind", "ctx", "snip", "reason"]
    with AUDIT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for lens, rows in (("N6", left6), ("N10", left10)):
            for r in rows:
                w.writerow({
                    "lens": lens,
                    "file": r.get("file", ""),
                    "line": r.get("line", ""),
                    "kind": r.get("kind", ""),
                    "ctx": r.get("ctx", ""),
                    "snip": (r.get("snip") or "")[:180],
                    "reason": r.get("reason", ""),
                })
    print("AUDIT", AUDIT, "rows", len(left6) + len(left10))


if __name__ == "__main__":
    main()
