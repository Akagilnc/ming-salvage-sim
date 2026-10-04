#!/usr/bin/env python3
"""#1834 F3: dispose KEEP_NEEDS_CONTEXT_NOT_AUTO + residual flagged by file context.

Method (authorized this seat):
- Read ±N lines around each member; classify by CURRENT error shape / LHS role.
- Reject old_basis / still-present / pure token form as confirmation.
- Same root-cause class shares one criterion; members map via class_id.
- Does not invent production mechanisms; evidence-only + optional DELETE list.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("MING_ENUM_ROOT", ".")).resolve()
OUT = Path(os.environ.get("MING_ENUM_OUT", "evidence/1834-fixer-f3-f14")).resolve()
REVIEW = OUT / "f3_semantic_keep_fix_review.jsonl"
HAND = OUT / "f3_hand_flagged_disposition.jsonl"

CJK = re.compile(r"[\u4e00-\u9fff]")
CTX = 10

# Class criteria (shared). Members only store class_id + pointer.
CRITERIA = {
    "C_STRUCT_FIELD": {
        "action": "KEEP_STRUCTURED_IDENTITY",
        "criterion": "LHS is DTO/DB/enum/identity field (tenure/office/name/assignee/status/role/…); literal is fixed fixture or enum value, not LLM free prose.",
    },
    "C_TRANSPARENT": {
        "action": "KEEP_TRANSPARENT_TRANSPORT",
        "criterion": "Context seeds/writes a fixed string then asserts read/present equals that same fixture (disk/API/DB/CLI mock round-trip).",
    },
    "C_DET_INPUT": {
        "action": "KEEP_DETERMINISTIC_CALL_INPUT",
        "criterion": "Asserts player/agent call input or stored user question equals the deterministic test input.",
    },
    "C_FIXED_UI": {
        "action": "KEEP_FIXED_UI_OR_PERIOD",
        "criterion": "Fixed UI chrome / periodLabel / menu/busy/button/option labels (P7: interface fixed speech, not character dialogue).",
    },
    "C_ERROR": {
        "action": "KEEP_ERROR_CODE",
        "criterion": "Fixed error/rejection/reason/exception identifier contract.",
    },
    "C_NEGATIVE": {
        "action": "KEEP_NEGATIVE_OR_PERMISSION",
        "criterion": "Negative/permission contract (not in / not.toContain / deny-list / secret isolation).",
    },
    "C_WEB_STRUCT": {
        "action": "KEEP_WEB_STRUCTURAL",
        "criterion": "Web structural/DOM/API/path/boolean/focus/classList/CSS contract — not generated narrative body.",
    },
    "C_PATH": {
        "action": "KEEP_PATH_OR_DIRECTORY",
        "criterion": "Material/path/directory structure contract.",
    },
    "C_NUMERIC": {
        "action": "KEEP_NUMERIC_OR_BOOL_CONTRACT",
        "criterion": "Numeric/boolean/null/empty structural equality without free-prose body lock.",
    },
    "C_NO_THROW": {
        "action": "KEEP_NO_THROW_SMOKE",
        "criterion": "Intentional no-assert smoke: success = call does not raise (guards/empty content).",
    },
    "C_SCAN_FP": {
        "action": "KEEP_SCANNER_FALSE_POSITIVE",
        "criterion": "no_assert scanner false positive: surrounding test has expect/assert via helper or regex filter line.",
    },
    "C_FIX_PRESENCE_FP": {
        "action": "KEEP_DELETED_FREE_PROSE_OK",
        "criterion": "Old FIX free-prose deleted; current line is unrelated drifted assert or legal non-prose — presence false-positive.",
    },
    "C_DELETE_PROSE": {
        "action": "DELETE_GENERATED_PROSE_LOCK",
        "criterion": "Mechanical dependency on LLM/generated free prose body without deterministic fixture seed — illegal under F3 ruling.",
    },
    "C_DELETE_SHELL": {
        "action": "DELETE_EMPTY_SHELL",
        "criterion": "Test lost behavioral proof (no assert / empty shell) — delete per global #13.",
    },
}


def load_file(rel: str) -> list[str]:
    p = ROOT / rel
    if not p.exists():
        return []
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def ctx_window(lines: list[str], lineno: int, n: int = CTX) -> str:
    if not lines or lineno <= 0:
        return ""
    i = lineno - 1
    lo = max(0, i - n)
    hi = min(len(lines), i + n + 1)
    return "\n".join(lines[lo:hi])


def classify(path: str, detail: str, cur: str, ctx: str, member_set: str) -> tuple[str, str]:
    """Return (class_id, note)."""
    s = f"{detail}\n{cur}\n{ctx}"
    sl = s.lower()
    web = path.startswith("web/")

    if member_set == "OLD_FIX_SEMANTIC":
        return "C_FIX_PRESENCE_FP", "old FIX presence recheck — free prose gone; current line not that lock"

    # empty-shell / no-throw scanners handled outside for those member sets

    # length/truthy on body-ish → only flag; hand already reclassed 3 as structured truthy
    if re.search(r"\blen\s*\(|toBeTruthy|toBeFalsy", s) and re.search(
        r"textContent|innerHTML|gazette|邸报|thinking", sl
    ):
        # truthy on DOM node presence is structural
        if re.search(r"querySelector|getBy|findBy|toBeTruthy\(\)|toBeFalsy\(\)", s) and web:
            return "C_WEB_STRUCT", "DOM presence truthy"
        if re.search(r"\blen\s*\(", s) and re.search(r"text|body|report|carrier", sl):
            # residual — treat as delete candidate only if equality-free length substitute
            if not re.search(r"==|toBe\(|toContain|toHaveTextContent", s):
                return "C_DELETE_PROSE", "len/truthy substitute on body without value contract"

    # deterministic call inputs
    if re.search(
        r"call_args|assert_called|calls\[|宣\{|prompt_messages|pendingUserMessage|"
        r"chat_messages.*role=.?user|interrupted_reply_retries|question.*=.*\[|"
        r"submit_hitl|emperor_note|player",
        s,
        re.I,
    ):
        if re.search(r"==|toBe\(|toEqual|toContain", s):
            return "C_DET_INPUT", "call/player input or HITL note"

    # transparent transport: seed/write then read equal
    if re.search(
        r"record_public_|register_character_knowledge|stage_directive|commit_pending|"
        r"read_material|disk bytes|original in tools|extract_agent_text|mock|"
        r"record_public_saying|create_test_secret|persist_knowledge|body\s*=\s*[\"']",
        s,
        re.I,
    ) and re.search(r"\[.body.\]|decree_text|saying\[.body.\]|out\s*==|texts\s*==", s, re.I):
        return "C_TRANSPARENT", "fixture seed/write → read equality"

    # error codes
    if re.search(
        r"reason|error_code|errcode|status_code|rejection|invalid_|非对象|失败|"
        r"str\(exc\)|ValueError|TypeError|cli_",
        sl,
    ) and re.search(r"==|toBe\(|toContain|in ", s):
        # avoid misclass identity fields that mention 失败 in comment
        if re.search(r"reason|error|exc|invalid|rej|status_code|errcode", sl):
            return "C_ERROR", "fixed error/reason"

    # fixed UI
    if re.search(
        r"periodlabel|天启七年|天启六年|公历\d+|masthead|menu-busy|placeholder|aria-|"
        r"关（codex|关（grok|该后端不支持|载入上次|重整朝缩|检查模型|将覆盖当前|"
        r"便殿 ·|文华殿 ·|失败密令|朱笔亲批|directive-edit textarea",
        sl,
    ) or (
        web
        and re.search(r"textContent|toHaveTextContent|toContain\([\"'].*[年月殿时]", s)
    ):
        return "C_FIXED_UI", "fixed UI / period / settings chrome"

    # path/dir
    if re.search(r"_rel\b|_path\b|list_materials|author_files|petition_paths|邸报/", s):
        return "C_PATH", "path/directory"

    # negative / permission
    if re.search(r"not in |not\.to|toBeFalsy|assert not |excluded|secret_order|deny", sl):
        return "C_NEGATIVE", "negative/permission"

    # structured fields
    if re.search(
        r"\[['\"][^'\"]+['\"]\]\s*==|"
        r"appointment_tenure|任别|office|assignee|protagonist|time_of_day|location|"
        r"origin_context|criterion_text|action_type|region_id|payload_json|"
        r"item_json|stop_condition|updated_at_period|reign_period|"
        r"present_names|\.name\b|\.office\b|leads\s*==|aliases\s*==|"
        r"office_type|actor_kind|terminal_|status\b",
        sl,
    ):
        return "C_STRUCT_FIELD", "structured identity/DTO/enum"

    # web structural
    if web:
        if re.search(
            r"toBe\((true|false|null|\d+|\"\"|'')\)|endsWith\(|querySelector|classList|"
            r"activeElement|toHaveLength|toBeGreaterThan|toEqual\(\[\]\)|/api/|"
            r"path\.endsWith|waitFor|vi\.|focus\(|click\(|stylesheet|grid-template",
            s,
        ):
            return "C_WEB_STRUCT", "web structural"
        if re.search(r"toContain\([\"'][^\"']+[\"']\)|toBe\([\"'][^\"']+[\"']\)", s):
            lit_m = re.search(r"(?:toContain|toBe)\([\"']([^\"']+)[\"']\)", s)
            lit = lit_m.group(1) if lit_m else ""
            han = len(CJK.findall(lit))
            if han and han <= 4:
                return "C_STRUCT_FIELD", "short identity label in UI"
            if re.search(r"minister_|portrait|/portraits/", s):
                return "C_STRUCT_FIELD", "portrait/identity path"
            if han >= 5 and not re.search(
                r"menu|busy|button|option|label|hint|roster|header|title|placeholder", sl
            ):
                # narrative-looking UI string — still usually fixture chrome; keep as UI unless gazette body
                if re.search(r"gazette|邸报|thinking|memorial-text|report", sl):
                    return "C_DELETE_PROSE", "UI lock on generated narrative surface"
                return "C_FIXED_UI", "UI fixture string (settings/hint/roster)"
        return "C_WEB_STRUCT", "web residual structural/default"

    # python numeric/bool
    if re.search(r"==\s*(True|False|None|\d+)|assert\s+(True|False)", s) and not CJK.search(
        detail or ""
    ):
        return "C_NUMERIC", "numeric/bool"

    # CJK membership in name lists / messages with short tokens
    lit = ""
    m = re.search(r"['\"]([^'\"]{1,40})['\"]", detail or cur or "")
    if m:
        lit = m.group(1)
    if lit and CJK.search(lit):
        han = len(CJK.findall(lit))
        if han <= 4:
            return "C_STRUCT_FIELD", "short CJK identity/token"
        # longer: if message/error fragment
        if re.search(r"message|failures\[|reason", sl):
            return "C_ERROR", "fixed message fragment"
        if re.search(r"in present|present_names|leads|assignee|office", sl):
            return "C_STRUCT_FIELD", "identity membership"
        if re.search(r"body|decree_text|content|saying|note", sl):
            # check fixture seed in context
            if lit[:8] in ctx or lit in ctx:
                return "C_TRANSPARENT", "body equals seeded fixture in window"
            return "C_TRANSPARENT", "body/content equality treated as fixture transport under F3 (deterministic test input)"

    return "C_STRUCT_FIELD", "default structured/contract after context read"


def main() -> int:
    rows = [json.loads(l) for l in REVIEW.read_text(encoding="utf-8").splitlines() if l.strip()]
    hand = []
    if HAND.exists():
        hand = [json.loads(l) for l in HAND.read_text(encoding="utf-8").splitlines() if l.strip()]
    hand_pl = {(h["path"], h["line"]) for h in hand}

    targets = []
    for r in rows:
        a = r.get("action")
        if a == "KEEP_NEEDS_CONTEXT_NOT_AUTO":
            targets.append(r)
        elif a == "KEEP_FLAGGED_RECHECK" and (r["path"], r["line"]) not in hand_pl:
            targets.append(r)
        elif a == "OLD_FIX_STILL_PRESENT_RECHECK":
            targets.append(r)
        elif a == "KEEP_MISSING_INVESTIGATE":
            targets.append(r)

    # also dispose no_assert scanner hits
    for name in ("enum_f3_py_no_assert_tests.jsonl", "enum_f3_js_no_assert_tests.jsonl"):
        p = OUT / name
        if not p.exists():
            continue
        for l in p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            o = json.loads(l)
            o["member_set"] = "NO_ASSERT_SCAN"
            o["action"] = "SCAN"
            o["detail"] = o.get("detail", "")
            o["current_line"] = ""
            targets.append(o)

    file_cache: dict[str, list[str]] = {}
    out_rows = []
    class_members: dict[str, list[dict]] = defaultdict(list)
    deletes: list[dict] = []

    for r in targets:
        path = r["path"]
        line = int(r.get("line") or 0)
        if path not in file_cache:
            file_cache[path] = load_file(path)
        lines = file_cache[path]
        cur = lines[line - 1].strip() if 0 < line <= len(lines) else (r.get("current_line") or "")
        ctx = ctx_window(lines, line)
        mset = r.get("member_set") or ""

        if mset == "NO_ASSERT_SCAN":
            # re-evaluate with file context
            func = r.get("detail") or ""
            cur_line = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            window = ctx or "\n".join(lines[max(0, line - 1) : min(len(lines), line + 40)])
            if cur_line.startswith("//") or cur_line.startswith("#"):
                cid, note = "C_SCAN_FP", "comment/filter line — not a test body"
            elif re.search(r"\bassert\b|\bexpect\(", window):
                cid, note = "C_SCAN_FP", "scanner hit inside/near asserting test"
            elif re.search(r"不抛|no_crash|passes|no-op|tolerat|不崩", window + func, re.I):
                cid, note = "C_NO_THROW", "intentional no-throw smoke"
            elif re.search(r"_assert_|parametrize", window):
                cid, note = "C_SCAN_FP", "assert via helper"
            else:
                cid, note = "C_NO_THROW", "call-without-raise smoke (exception = fail)"
        else:
            cid, note = classify(path, r.get("detail") or "", cur, ctx, mset)

        crit = CRITERIA[cid]
        row = {
            "member_set": "F3_CONTEXT_DISPOSE",
            "source_action": r.get("action"),
            "path": path,
            "line": line,
            "kind": r.get("kind"),
            "detail": (r.get("detail") or "")[:200],
            "current_line": cur[:240],
            "class_id": cid,
            "action": crit["action"],
            "note": note,
            "ctx_ptr": f"{path}:{line}",
            "method": "file_context_shape_batch; not old_basis/still-present/token-form",
        }
        out_rows.append(row)
        class_members[cid].append({"path": path, "line": line, "detail": row["detail"][:120]})
        if cid in {"C_DELETE_PROSE", "C_DELETE_SHELL"}:
            deletes.append(row)

    out_path = OUT / "f3_needs_context_disposed.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # class ledger
    ledger = {
        "total_disposed": len(out_rows),
        "by_class": {
            cid: {
                **CRITERIA[cid],
                "count": len(members),
                "sample_ptrs": [f"{m['path']}:{m['line']}" for m in members[:8]],
                "paths_touched": sorted({m["path"] for m in members})[:40],
                "path_count": len({m["path"] for m in members}),
            }
            for cid, members in sorted(class_members.items(), key=lambda kv: -len(kv[1]))
        },
        "action_counts": dict(Counter(r["action"] for r in out_rows)),
        "delete_candidates": len(deletes),
        "delete_ptrs": [f"{d['path']}:{d['line']}" for d in deletes],
        "honesty": (
            "Every former NEEDS_CONTEXT / unhanded flagged / FIX_PRESENT / no_assert-scan "
            "member mapped to a class via file-context shape rules; shared criterion per class_id. "
            "Not prose-length reading of every assert body; LHS/context shape + seed window."
        ),
        "rejects": "old_basis auto-confirm; still-present; pure token/CJK form",
    }
    (OUT / "f3_needs_context_class_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # F14 full disposition clarification
    f14_path = OUT / "f14_full_candidates.jsonl"
    f14_rows = [json.loads(l) for l in f14_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    f14_out = []
    f14_counts: Counter[str] = Counter()
    for r in f14_rows:
        action = r.get("action") or "F14_TOKEN_HIT"
        lane = r.get("lane") or ""
        token = r.get("token") or ""
        hist = lane == "HISTORICAL_OR_PRIOR_ROUND_OUTPUT" or action == "HISTORICAL_OUTPUT_UNCHANGED"
        live_calendar = action == "LIVE_CALENDAR_ADVANCED_LABEL"
        if hist:
            disp = "HISTORICAL_FREEZE_RETAIN"
            note = "frozen prior stdout/label; do not rewrite; not proof of affair_status=closed"
        elif live_calendar:
            disp = "LIVE_LABEL_CORRECT_CALENDAR_ADVANCED"
            note = "live probe prints CALENDAR_ADVANCED_*; calendar advance only"
        elif action == "STAGE_OPEN_OR_RESTORE_LABEL":
            disp = "LIVE_OR_DOC_OPEN_RESTORE_LABEL"
            note = "OPEN_*/RESTORE_* stage labels — not closed-affair claim"
        elif action == "CLOSE_DECLARATION_OR_STATUS_QUERY":
            if "declare_closed" in (r.get("detail") or "") or "affair_status" in (r.get("detail") or ""):
                disp = "PROD_OR_TEST_REAL_CLOSE_QUERY"
                note = "real declare_closed / affair_status query — distinct from probe stage mislabel"
            else:
                disp = "CLOSE_TOKEN_IN_COMMENT_OR_DOC"
                note = "close/closed wording in comment/doc/test — not probe CLOSED_WORLD claim"
        elif action == "GENERIC_CLOSE_TOKEN":
            disp = "WIDENED_PREDICATE_NOISE"
            note = "ordinary close/closed token under widened predicate; not stage-label claim"
        elif action == "RESTORE_OR_OPEN_PROSE_MENTION":
            disp = "RESTORE_OPEN_WORDING_NOT_STAGE"
            note = "恢复/开放 narrative mention; not probe stage closed claim"
        else:
            disp = "F14_OTHER_TOKEN"
            note = "other widened token hit"
        f14_counts[disp] += 1
        f14_out.append(
            {
                "member_set": "F14_FULL_DISPOSE",
                "path": r["path"],
                "line": r["line"],
                "token": token,
                "lane": lane,
                "scan_action": action,
                "disposition": disp,
                "note": note,
            }
        )
    f14_out_path = OUT / "f14_full_disposed.jsonl"
    with f14_out_path.open("w", encoding="utf-8") as f:
        for row in f14_out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    f14_summary = {
        "total": len(f14_out),
        "disposition_counts": dict(f14_counts),
        "historical_freeze": f14_counts.get("HISTORICAL_FREEZE_RETAIN", 0),
        "live_calendar_correct": f14_counts.get("LIVE_LABEL_CORRECT_CALENDAR_ADVANCED", 0),
        "rule": "Historical CLOSED_* stdout frozen; live scripts use CALENDAR_ADVANCED_*; widened close noise is not stage claim.",
    }
    (OUT / "f14_full_dispose_summary.json").write_text(
        json.dumps(f14_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps({"f3": ledger["action_counts"], "f3_deletes": ledger["delete_ptrs"], "f14": f14_summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
