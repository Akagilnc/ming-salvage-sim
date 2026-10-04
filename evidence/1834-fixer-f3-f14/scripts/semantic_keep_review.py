#!/usr/bin/env python3
"""Semantic re-review of OLD KEEP/FIX for #1834 F3 — not still-present auto-confirm.

Method honesty:
- Does NOT claim line-by-line human reading of all ~1900 KEEP rows.
- Re-classifies each retained assert by CURRENT source shape heuristics
  (call input / fixed UI / error code / transparent transport / structured field /
   length-or-truthy substitute / generated-prose risk).
- Presence is checked against current file text; old_basis is NEVER copied as
  confirmation — only recorded for mismatch detection.
- Flags: MISMATCH_OLD_BASIS, PROSE_RISK_RECHECK, LEN_OR_TRUTHY_SUBSTITUTE,
  MISSING_BUT_WAS_KEEP, DELETED_OK_FREE_PROSE, RESTORE_REQUIRED_STILL_MISSING.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("MING_ENUM_ROOT", ".")).resolve()
OUT = Path(os.environ.get("MING_ENUM_OUT", "/tmp/1834-fixer-f3-f14-enum-expand")).resolve()
OLD = ROOT / "evidence/1834-fixer-f9-f12-f3/f3_disposition.jsonl"
PREV_FULL = ROOT / "evidence/1834-fixer-f3-f14/f3_full_bidirectional_disposition.jsonl"

CJK = re.compile(r"[\u4e00-\u9fff]")

# Known restored legal contracts (judge F3) — verify present; not a construction whitelist for new work
RESTORED = [
    ("tests/test_scene_llm_1836.py", "边饷如何"),
    ("tests/test_material_directory_1830.py", "经历正文"),
    ("tests/test_material_directory_1830.py", "本月邸报"),
    ("tests/test_material_directory_1830.py", "original in tools"),
    ("tests/test_due_review_621.py", 'origin_context"] == "三年火器见眉目"'),
    ("tests/test_due_review_621.py", 'criterion_text"] == "火器见眉目"'),
    ("web/src/appDurableWiring.test.tsx", "天启七年九月"),
    ("web/src/components/modals.test.tsx", "洪承畴"),
    ("web/src/components/modals.test.tsx", "天启七年九月"),
    ("web/src/components/modals.test.tsx", "天启七年十二月"),
    ("web/src/components/settlementGazettePanel.test.tsx", "天启七年十月"),
    ("web/src/components/situation.test.tsx", "杨嗣昌"),
]

EMPTY_SHELLS = [
    ("tests/test_cli_runner_error_typed_1299.py", "test_clichat_normal_reply_still_returns"),
    ("tests/test_decree_commitment_settlement_229.py", "test_commitment_progress_contexts_are_structured"),
    ("web/src/components/modals.test.tsx", "does not treat an ordinary history reduction as a withdrawal"),
    ("web/src/components/modals.test.tsx", "shows the whole chronological night instead of a selected-minister window"),
    ("web/src/components/situation.test.tsx", "detail modal keeps parentheses when bar meanings are present"),
    ("web/src/staleGuard.test.tsx", "未切人时响应正常应用不被守卫误丢"),
    ("web/src/staleGuard.test.tsx", "未切人时历史正常加载不被误丢"),
]


def load_file(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def line_at(text: str, lineno: int) -> str:
    if lineno <= 0:
        return ""
    lines = text.splitlines()
    if lineno > len(lines):
        return ""
    return lines[lineno - 1]


def presence(rel: str, lineno: int, detail: str) -> tuple[str, str]:
    text = load_file(rel)
    if not text:
        return "FILE_MISSING", ""
    cur = line_at(text, lineno)
    # detail fragment match (old enum often stores short detail)
    frag = (detail or "")[:40]
    # strip wrapping quotes noise
    needles = [frag]
    m = re.search(r"['\"](.{2,40})['\"]", detail or "")
    if m:
        needles.append(m.group(1))
    if any(n and n in text for n in needles if n):
        # prefer same line if detail fragment on that line
        if any(n and n in cur for n in needles if n):
            return "PRESENT_AT_LINE", cur.strip()[:240]
        return "PRESENT_ELSEWHERE_OR_SHIFTED", cur.strip()[:240]
    # line still an assert/expect?
    if re.search(r"\bassert\b|\bexpect\(", cur):
        return "LINE_STILL_ASSERT_DETAIL_DRIFTED", cur.strip()[:240]
    return "MISSING", cur.strip()[:240]


def semantic_class(rel: str, kind: str, detail: str, cur_line: str) -> tuple[str, str]:
    """Classify by CURRENT shape — independent of old_basis."""
    s = f"{kind} {detail} {cur_line}"
    sl = s.lower()

    # length / truthy substitutes on body-ish
    if re.search(r"\blen\s*\(|assert_len|assert_truthy", s) and re.search(
        r"text|body|carrier|content|report|replies|message", sl
    ):
        return "LENGTH_OR_TRUTHY_SUBSTITUTE", "len/truthy on body-ish — illegal substitute risk"

    # call inputs
    if re.search(r"\bcalls\b|call_args|assert calls|宣\{|agent.*input|prompt_messages", s):
        return "DETERMINISTIC_CALL_INPUT", "agent/LLM call input equality"

    # disk / transparent transport
    if re.search(r"read_material|disk bytes|== \"|== '|original in tools", s) and re.search(
        r"read_material|carrier|blob|disk|direct|api", s
    ):
        # could still be prose lock on material body — split
        if re.search(r"read_material.*=|==.*read_material|original in tools", s):
            return "TRANSPARENT_TRANSPORT_OR_DISK", "fixed bytes / verbatim read contract"

    # fixed UI chrome (P7)
    if re.search(r"periodlabel|masthead|天启七年|菜单|标题|placeholder|aria-|role=", sl) or (
        "web/" in rel and re.search(r"toContain\([\"'].*[月年]", s)
    ):
        return "FIXED_UI_CHROME", "fixed UI field / periodLabel / chrome"

    # error codes / CLI fixed identifiers
    if re.search(r"reason|error|errcode|error_code|cli_|rejection|非对象|invalid|status_code", sl):
        if not CJK.search(detail or "") or re.search(r"reason|error|rej\[|item_json", sl):
            return "ERROR_CODE_OR_FIXED_IDENTIFIER", "error/reason/fixed CLI identifier"

    # structured identity / enum / DTO
    if re.search(
        r"origin_context|criterion_text|archive\[|presented\[|status|terminal_|item_json|effect_on_fail|speaker|role\b|character\.name|identity",
        sl,
    ):
        return "STRUCTURED_FIELD_OR_IDENTITY", "structured DTO / identity / enum field"

    # negative permission / source contracts
    if re.search(r"not in|toBeFalsy|not\.toContain|secret_order|projection:", sl):
        return "PERMISSION_OR_NEGATIVE_CONTRACT", "source permission / negative contract"

    # path structure
    if re.search(r"_rel\b|_path\b|list_materials|author_files|petition_paths", s):
        return "PATH_OR_DIRECTORY_STRUCTURE", "path/directory structure"

    # generated / fixture free prose risk: CJK long or narrative equality without structured lhs
    lit = ""
    m = re.search(r"['\"]([^'\"]{4,})['\"]", detail or "")
    if m:
        lit = m.group(1)
    if lit and CJK.search(lit) and len(lit) >= 4:
        # short identity-like names (<=4 han) may be identity
        han = len(CJK.findall(lit))
        if han <= 4 and re.search(r"name|speaker|author|title|textContent\)\.toBe", sl):
            return "STRUCTURED_FIELD_OR_IDENTITY", "short identity label"
        if re.search(r"in (text|body|carrier|content|report|html|textContent)", sl):
            return "GENERATED_OR_FIXTURE_PROSE_RISK", "prose membership in body/text — recheck"
        if re.search(r"==|toBe|toContain|toHaveTextContent|toMatch", sl) and not re.search(
            r"origin_context|criterion|archive|presented|item_json|masthead|period", sl
        ):
            return "GENERATED_OR_FIXTURE_PROSE_RISK", "free-prose equality/contain — recheck"

    if "vitest_neg" in (kind or "") or ".not." in s:
        return "PERMISSION_OR_NEGATIVE_CONTRACT", "negative matcher"

    if "vitest_pos" in (kind or "") and "web/" in rel:
        return "WEB_MATCHER_NEEDS_CONTEXT", "web matcher — need UI vs prose context"

    return "UNCLASSIFIED_NEEDS_CONTEXT", "insufficient mechanical signal; not auto-confirmed"


# Map old_basis buckets to expected semantic families for mismatch detection
OLD_TO_FAMILIES = {
    "structured_enum_or_identity_field": {
        "STRUCTURED_FIELD_OR_IDENTITY",
        "ERROR_CODE_OR_FIXED_IDENTIFIER",
        "FIXED_UI_CHROME",
        "PERMISSION_OR_NEGATIVE_CONTRACT",
        "PATH_OR_DIRECTORY_STRUCTURE",
        "TRANSPARENT_TRANSPORT_OR_DISK",
        "DETERMINISTIC_CALL_INPUT",
    },
    "cli_fixed_option_or_error_identifier": {
        "ERROR_CODE_OR_FIXED_IDENTIFIER",
        "STRUCTURED_FIELD_OR_IDENTITY",
        "PERMISSION_OR_NEGATIVE_CONTRACT",
        "PATH_OR_DIRECTORY_STRUCTURE",
    },
    "ui_identity_or_fixed_label_or_technical": {
        "FIXED_UI_CHROME",
        "STRUCTURED_FIELD_OR_IDENTITY",
        "WEB_MATCHER_NEEDS_CONTEXT",
        "PERMISSION_OR_NEGATIVE_CONTRACT",
    },
    "permission_or_negative_contract": {
        "PERMISSION_OR_NEGATIVE_CONTRACT",
        "PATH_OR_DIRECTORY_STRUCTURE",
        "STRUCTURED_FIELD_OR_IDENTITY",
    },
    "ui_fixed_chrome_p7": {"FIXED_UI_CHROME", "STRUCTURED_FIELD_OR_IDENTITY", "WEB_MATCHER_NEEDS_CONTEXT"},
    "verbatim_transmission_equality": {
        "TRANSPARENT_TRANSPORT_OR_DISK",
        "DETERMINISTIC_CALL_INPUT",
        "STRUCTURED_FIELD_OR_IDENTITY",
    },
    "structured_enum_identity_transport_or_contract": {
        "STRUCTURED_FIELD_OR_IDENTITY",
        "TRANSPARENT_TRANSPORT_OR_DISK",
        "DETERMINISTIC_CALL_INPUT",
        "PERMISSION_OR_NEGATIVE_CONTRACT",
    },
    "path_or_directory_structure": {"PATH_OR_DIRECTORY_STRUCTURE", "PERMISSION_OR_NEGATIVE_CONTRACT"},
}


def main() -> int:
    old = [json.loads(l) for l in OLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    keeps = [o for o in old if o.get("decision") == "KEEP"]
    fixes = [o for o in old if o.get("decision") == "FIX"]

    keep_rows = []
    for o in keeps:
        rel = o["path"]
        detail = o.get("detail", "")
        kind = o.get("kind", "")
        lineno = int(o.get("line") or 0)
        status, cur = presence(rel, lineno, detail)
        sem, sem_note = semantic_class(rel, kind, detail, cur)
        old_basis = o.get("basis") or ""
        fam = OLD_TO_FAMILIES.get(old_basis)
        mismatch = bool(fam and sem not in fam and sem not in {"UNCLASSIFIED_NEEDS_CONTEXT", "WEB_MATCHER_NEEDS_CONTEXT"})
        flags = []
        if status == "MISSING":
            flags.append("MISSING_BUT_WAS_KEEP")
        if status.startswith("PRESENT") or status.startswith("LINE_"):
            pass
        if sem == "GENERATED_OR_FIXTURE_PROSE_RISK":
            flags.append("PROSE_RISK_RECHECK")
        if sem == "LENGTH_OR_TRUTHY_SUBSTITUTE":
            flags.append("LEN_OR_TRUTHY_SUBSTITUTE")
        if mismatch:
            flags.append("MISMATCH_OLD_BASIS")
        if status in {"PRESENT_AT_LINE", "PRESENT_ELSEWHERE_OR_SHIFTED", "LINE_STILL_ASSERT_DETAIL_DRIFTED"} and not flags:
            # legal retain only if semantic class is a keep-family
            if sem in {
                "DETERMINISTIC_CALL_INPUT",
                "FIXED_UI_CHROME",
                "ERROR_CODE_OR_FIXED_IDENTIFIER",
                "TRANSPARENT_TRANSPORT_OR_DISK",
                "STRUCTURED_FIELD_OR_IDENTITY",
                "PERMISSION_OR_NEGATIVE_CONTRACT",
                "PATH_OR_DIRECTORY_STRUCTURE",
            }:
                action = "KEEP_SEMANTIC_OK"
            elif sem in {"UNCLASSIFIED_NEEDS_CONTEXT", "WEB_MATCHER_NEEDS_CONTEXT"}:
                action = "KEEP_NEEDS_CONTEXT_NOT_AUTO"
                flags.append("NEEDS_CONTEXT")
            else:
                action = "KEEP_FLAGGED_RECHECK"
        elif "MISSING_BUT_WAS_KEEP" in flags:
            action = "KEEP_MISSING_INVESTIGATE"
        else:
            action = "KEEP_FLAGGED_RECHECK"

        keep_rows.append(
            {
                "member_set": "OLD_KEEP_SEMANTIC",
                "path": rel,
                "line": lineno,
                "kind": kind,
                "detail": (detail or "")[:240],
                "old_decision": "KEEP",
                "old_basis": old_basis,
                "presence": status,
                "current_line": cur,
                "semantic_class": sem,
                "semantic_note": sem_note,
                "action": action,
                "flags": flags,
                "method": "shape_heuristic+presence; NOT line-by-line human read; old_basis not used as confirmation",
            }
        )

    fix_rows = []
    for o in fixes:
        rel = o["path"]
        detail = o.get("detail", "")
        kind = o.get("kind", "")
        lineno = int(o.get("line") or 0)
        status, cur = presence(rel, lineno, detail)
        old_basis = o.get("basis") or ""
        # known misclass restores
        if (rel, old_basis) in {
            ("tests/test_scene_llm_1836.py", "hand_round2_free_prose"),
            ("tests/test_due_review_621.py", "criterion_text_free_equality"),
        } or (rel == "tests/test_due_review_621.py" and "origin_context" in detail):
            if status.startswith("PRESENT") or "边饷" in load_file(rel) or "火器见眉目" in load_file(rel):
                action = "RECLASS_RESTORE_VERIFIED_PRESENT"
            else:
                action = "RESTORE_REQUIRED_STILL_MISSING"
            sem = "LEGAL_CONTRACT_WAS_MISCLASS_FIX"
        else:
            if status == "MISSING":
                action = "KEEP_DELETED_FREE_PROSE_OK"
                sem = "GENERATED_OR_FIXTURE_PROSE"
            else:
                action = "OLD_FIX_STILL_PRESENT_RECHECK"
                sem = "MAY_BE_RESIDUAL_PROSE_OR_LEGIT_RESTORE"
        fix_rows.append(
            {
                "member_set": "OLD_FIX_SEMANTIC",
                "path": rel,
                "line": lineno,
                "kind": kind,
                "detail": (detail or "")[:240],
                "old_decision": "FIX",
                "old_basis": old_basis,
                "presence": status,
                "current_line": cur,
                "semantic_class": sem,
                "action": action,
                "method": "presence+known-misclass map; not old_basis auto-confirm",
            }
        )

    restored_rows = []
    for rel, needle in RESTORED:
        text = load_file(rel)
        restored_rows.append(
            {
                "member_set": "RESTORED_LEGAL_CONTRACT",
                "path": rel,
                "needle": needle,
                "present": needle in text,
                "action": "RESTORE_VERIFIED" if needle in text else "RESTORE_MISSING",
            }
        )

    shell_rows = []
    for rel, test in EMPTY_SHELLS:
        text = load_file(rel)
        shell_rows.append(
            {
                "member_set": "EMPTY_SHELL_DELETED",
                "path": rel,
                "test": test,
                "gone": test not in text,
                "action": "SHELL_GONE" if test not in text else "SHELL_STILL_PRESENT",
            }
        )

    out_path = OUT / "f3_semantic_keep_fix_review.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in keep_rows + fix_rows + restored_rows + shell_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "old_keep": len(keeps),
        "old_fix": len(fixes),
        "keep_action_counts": dict(Counter(r["action"] for r in keep_rows)),
        "keep_semantic_counts": dict(Counter(r["semantic_class"] for r in keep_rows)),
        "keep_flag_counts": dict(Counter(flag for r in keep_rows for flag in r["flags"])),
        "keep_presence_counts": dict(Counter(r["presence"] for r in keep_rows)),
        "fix_action_counts": dict(Counter(r["action"] for r in fix_rows)),
        "restored_ok": sum(1 for r in restored_rows if r["present"]),
        "restored_missing": sum(1 for r in restored_rows if not r["present"]),
        "shells_gone": sum(1 for r in shell_rows if r["gone"]),
        "shells_still": sum(1 for r in shell_rows if not r["gone"]),
        "honesty": "shape-heuristic semantic pass over all KEEP rows; not claiming human line-by-line reading",
        "rejects_prior_method": "prior OLD_KEEP_BIDIR KEEP_CONFIRMED/STILL_PRESENT copying old_basis is insufficient",
    }
    (OUT / "f3_semantic_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
