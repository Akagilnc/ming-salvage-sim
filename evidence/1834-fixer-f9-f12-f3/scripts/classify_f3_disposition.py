#!/usr/bin/env python3
"""Classify every F3 enum hit → FIX|KEEP with basis.

Judge F3 + owner: delete human-readable free-text mechanical deps
(dialogue / LLM body / CLI free output / qualitative display / note prose).
Keep structured fields, verbatim transport, fixed UI chrome (P7), permission
negatives, typed error identifiers. Dialogue/CLI are not wholesale exempt.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enum_f3_free_text_asserts import iter_hits, is_prose  # noqa: E402

OUT_JSON = ROOT / "evidence/1834-fixer-f9-f12-f3/f3_disposition.json"
OUT_FIX = ROOT / "evidence/1834-fixer-f9-f12-f3/f3_fix_list.txt"

UI_FIXED_EXACT = {
    "重试", "邸报", "上月抄报", "奏疏", "召对记录", "群臣奏对", "大臣思索中",
    "关闭", "确定", "取消", "退朝", "批红", "颁布", "拟旨", "密令", "局势",
    "人物", "军队", "地区", "存档", "读档", "设置", "结束", "继续",
    "奏疏：1 件待览", "三月邸报", "大臣拟旨", "越次召对", "离开等待",
    "检查模型后端", "重整朝堂名册", "载入上次进度", "本月无疏", "承诺进度",
    "未知进度", "· 核账", "· 待批", "递话", "起居注", "御前低语",
}

UI_FIXED_PREFIX = (
    "奏疏：", "1627 年", "关（", "便殿", "文华殿", "乾清宫",
)

UI_FIXED_CONTAIN = (
    "不支持推理强度", "将覆盖当前主进度", "模型调用耗尽", "召对记录读取失败",
    "回话已保存，后续处理失败", "失败密令未处理", "请交给作者",
)

SPEECH_RE = re.compile(
    r"(臣|奴婢|卿|朕|奏：|回话|问话|递话|领旨|遵旨|愚见|谨奏|"
    r"已知悉|陈辽饷|重奏|隐瞒|公开传话|殿门|搁笔|据实|核账。"
    r"|烛影|低声|边报已至|迟到递话|撤回前|公共卷|公共答复|非流式新答|"
    r"御前低语|神色凝重|辽饷何解|整饬边备|军前缺饷|辽东军情|"
    r"甲的回话|甲的历史|已离开实时|已撤回)"
)

FREE_NOTE_LHS = re.compile(
    r"(execution_note|resolution_summary|memorial_text|arrears_text|"
    r"\brecap\b|\[.answer.\]|\.answer\b|stance_segment|promulgation_reason)"
)

QUAL_RE = re.compile(r"欠饷(严重|约)")


def _lits(detail: str) -> list[str]:
    return [a or b for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", detail)]


def _joined(lits: list[str]) -> str:
    return "".join(lits)


def _is_ui_fixed(lits: list[str], detail: str) -> bool:
    for s in lits:
        if s in UI_FIXED_EXACT:
            return True
        if any(s.startswith(p) for p in UI_FIXED_PREFIX):
            return True
        if any(p in s for p in UI_FIXED_CONTAIN):
            return True
    if any(p in detail for p in UI_FIXED_CONTAIN):
        return True
    if "yearMonthLabel" in detail or "year-month" in detail:
        return True
    if "menu-busy" in detail or "offOption" in detail:
        return True
    if "audience-type-label" in detail or "audience-roster h2" in detail:
        return True
    return False


def _is_struct_identity(detail: str, lits: list[str]) -> bool:
    if any(
        tok in detail
        for tok in (
            "office", "station", "leader", "protagonist", "archive_key",
            "appointment_tenure", "dimension", "otype", "infer(",
            "involved_characters", "trigger_kind", "progress_band",
            "execution_outcome", "origin_ref", "actor_kind", "channels",
            "holders", "minister-office", "data-actor", "data-source",
            "alt", "/portraits/", "slot:", "central:", "任别",
            "item_json", "effect_on_fail", "payload_json", "audibility",
            "recent_segment", "recent_context", "founding",
        )
    ):
        return True
    # short name tokens only
    prose = [s for s in lits if is_prose(s)]
    if prose and all(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·@:\-]{1,12}", s) for s in prose):
        if not any(p in _joined(prose) for p in "。！？"):
            if any(k in detail for k in ("name", "speaker", "faction", "power", "region")):
                return True
    return False


def _is_error_id(detail: str, lits: list[str]) -> bool:
    blob = detail + _joined(lits)
    markers = (
        "不存在", "必填", "未知 metric", "非对象", "退出码", "调用失败", "id 不",
        "LLM 不可用", "残留观测", "承诺 issue", "Authentication", "Unknown model",
        "fail_chat_turn", "highlight trail", "identity read failed",
        "post-fiscal failure", "injected continuation",
    )
    if any(m in blob for m in markers):
        return True
    if "str(exc)" in detail or "gate_key_form_error" in detail:
        return True
    if any(s.startswith("【") for s in lits):
        return True
    if "provider_message" in detail or "traceback" in detail:
        return True
    return False


def _is_technical_ascii(lits: list[str]) -> bool:
    if not lits:
        return False
    for s in lits:
        if re.search(r"[\u4e00-\u9fff]", s):
            return False
    return True


def _is_speech(lits: list[str]) -> bool:
    return bool(SPEECH_RE.search(_joined(lits)))


def classify(path: str, kind: str, detail: str) -> tuple[str, str]:
    lits = _lits(detail)
    prose = [s for s in lits if is_prose(s)]

    if kind in {"neg_membership", "vitest_neg"} or ".not." in detail:
        return "KEEP", "permission_or_negative_contract"
    if kind.startswith("path_member") or kind == "assert_truthy_paths":
        return "KEEP", "path_or_directory_structure"
    if kind.startswith("material_body"):
        return "FIX", "material_body_free_substring"
    if kind in {"assert_truthy_body", "assert_len_body"}:
        # structured presence on office/classes/gatekeepers ≠ free prose stare
        if any(
            tok in detail
            for tok in (".office", "['classes']", "['gatekeepers']", "context[")
        ):
            return "KEEP", "structured_presence_not_free_prose"
        return "FIX", "free_body_truthy_or_len_sentinel"

    # empty-string / structural answer presence checks
    if re.search(r"""\banswer\b.*(?:toBe|==)\(\s*['"]{2}\s*\)""", detail) or re.search(
        r"""(?:toBe|==)\(\s*['"]{2}\s*\)""", detail
    ):
        if "answer" in detail:
            return "KEEP", "structured_enum_or_identity_field"

    if (
        "extract_agent_text" in detail
        or re.search(r"\btexts\s*==", detail)
        or re.search(r"\bout\s*==", detail)
    ):
        return "KEEP", "verbatim_transmission_equality"
    # founding-segment merge helpers: contract is verbatim text merge
    if "merge_founding_segment" in detail or "merge_founding" in path:
        return "KEEP", "verbatim_transmission_equality"
    if _is_ui_fixed(lits, detail):
        return "KEEP", "ui_fixed_chrome_p7"
    if _is_error_id(detail, lits):
        return "KEEP", "cli_fixed_option_or_error_identifier"
    if _is_technical_ascii(lits) and not prose:
        return "KEEP", "cli_fixed_option_or_error_identifier"
    if _is_technical_ascii(lits) and all(not re.search(r"[\u4e00-\u9fff]", s) for s in lits):
        return "KEEP", "cli_fixed_option_or_error_identifier"
    # citation / formula / dump markers
    if any("《" in s or "公式" in s or "_formula" in detail or "printenv" in s for s in lits) or "_formula" in detail:
        return "KEEP", "structured_enum_or_identity_field"
    if "finish_reason" in detail or "reasoning_tokens" in detail or "中转 reasoning" in _joined(lits):
        return "KEEP", "cli_fixed_option_or_error_identifier"
    if "只输出一个 JSON" in _joined(lits) or "has_pending_failure" in _joined(lits):
        return "KEEP", "cli_fixed_option_or_error_identifier"
    if "npm run" in _joined(lits) or "--host" in _joined(lits):
        return "KEEP", "cli_fixed_option_or_error_identifier"
    if _is_struct_identity(detail, lits):
        return "KEEP", "structured_enum_or_identity_field"
    if kind == "structured_field_eq_prose":
        return "KEEP", "structured_field_equality"
    # short identity in vitest (洪承畴, 场次N)
    if kind.startswith("vitest") and prose and all(
        re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·：:]{1,12}", s) for s in prose
    ):
        if not _is_speech(lits):
            return "KEEP", "ui_identity_or_fixed_label_or_technical"

    # decree_text / this_decree fixture input written by test
    if "decree_text" in detail and not _is_speech(lits):
        return "KEEP", "structured_enum_or_identity_field"

    # qualitative display
    if QUAL_RE.search(_joined(lits)) or QUAL_RE.search(detail):
        return "FIX", "qualitative_display_free_substring"

    # free note / stance / answer fields
    if FREE_NOTE_LHS.search(detail):
        return "FIX", "dialogue_or_note_free_equality"

    # user-role / question echoes of fixture questions → transport
    if kind == "assert_list_eq_prose":
        if "terminal_state" in detail or "上游事件" in _joined(prose):
            return "KEEP", "cli_fixed_option_or_error_identifier"
        if (
            "role='user'" in detail
            or 'role="user"' in detail
            or "role'] == 'user'" in detail
            or 'role"] == "user"' in detail
            or "users" in detail
        ):
            return "KEEP", "verbatim_transmission_equality"
        if re.search(r"\bquestion\b", detail) and "minister" not in detail:
            return "KEEP", "verbatim_transmission_equality"
        if "highlight" in detail.lower():
            return "KEEP", "structured_enum_or_identity_field"
        if ".body" in detail or "memorial" in detail or _is_speech(lits):
            return "FIX", "dialogue_list_free_equality"
        return "KEEP", "structured_enum_identity_transport_or_contract"

    # Vitest free wording
    if kind in {"vitest_pos_prose", "vitest_pos_prose_gazetteish", "vitest_eq_prose"}:
        if _is_speech(lits):
            return "FIX", "vitest_dialogue_free_wording"
        # gazette / situation fixture body locks
        if any(k in path for k in ("settlement", "situation", "gazette")) and prose:
            if any(len(s) >= 4 for s in prose):
                return "FIX", "vitest_fixture_free_prose"
        # staleGuard dialogue panels
        if "staleGuard" in path and _is_speech(lits):
            return "FIX", "vitest_dialogue_free_wording"
        if "staleGuard" in path and prose and any("甲：" in s or "回话" in s for s in prose):
            return "FIX", "vitest_dialogue_free_wording"
        # remaining longer Chinese in chat modals / durable wiring
        if any(k in path for k in ("modals", "mindreading", "appDurable", "drawers")) and _is_speech(lits):
            return "FIX", "vitest_dialogue_free_wording"
        if any(k in path for k in ("modals", "mindreading")) and prose and any(len(s) >= 4 for s in prose):
            # non-speech but free fixture narrative in chat surface
            if not _is_ui_fixed(lits, detail) and not _is_struct_identity(detail, lits):
                return "FIX", "vitest_fixture_free_prose"
        return "KEEP", "ui_identity_or_fixed_label_or_technical"

    if kind == "vitest_pos":
        return "KEEP", "ui_identity_or_fixed_label_or_technical"

    # Python in/eq
    if kind in {"assert_in_prose", "assert_eq_prose"}:
        # fiscal config keys / reason_code / normalized enums / prompt chrome
        if any(
            tok in detail
            for tok in (
                "get_fiscal_config", "reason_code", "normalized", "fidelity_state",
                "legacy_spillover", "APPOINTMENT_TEXT", "due_priority_",
                "surcharge_section", "tsv.splitlines", "payload_summary",
            )
        ):
            return "KEEP", "structured_enum_or_identity_field"
        if "prompt" in detail and (
            "输出 ok" in _joined(lits)
            or "官名：" in _joined(lits)
            or "相对期限" in _joined(lits)
            or "默认军饷" in _joined(lits)
            or "陕西=" in _joined(lits)
            or "dossier:<" in _joined(lits)
            or "不得使用" in _joined(lits)
        ):
            return "KEEP", "cli_fixed_option_or_error_identifier"
        if "power_updates" in _joined(lits) or "查无此势力" in _joined(lits):
            return "KEEP", "cli_fixed_option_or_error_identifier"
        if "实征" in _joined(lits) or "起运" in _joined(lits) or "火耗" in _joined(lits):
            return "KEEP", "structured_enum_or_identity_field"
        if "read_material" in detail:
            return "FIX", "material_body_free_substring"
        if _is_speech(lits):
            return "FIX", "dialogue_or_llm_free_equality"
        # CLI free stdout narrative (not error id)
        if "capsys" in detail or ".out" in detail:
            return "FIX", "cli_free_output_substring"
        # faction stance / generated narrative segments
        if "stance_segment" in detail or "segment" in detail:
            return "FIX", "dialogue_or_note_free_equality"
        # issue reason category tokens 主账/候选 — structured markers
        if "['reason']" in detail or '["reason"]' in detail:
            if prose and all(len(s) <= 4 for s in prose):
                return "KEEP", "structured_enum_or_identity_field"
        # content summary/precondition narrative in event defs
        if any(k in detail for k in ("['summary']", '["summary"]', "precondition")):
            return "FIX", "dialogue_or_note_free_equality"
        # origin_context free
        if "origin_context" in detail:
            return "FIX", "dialogue_or_note_free_equality"
        # identity-in-note (徐光启 in note) — identity KEEP
        if re.search(r"\bnote\b", detail) and prose and all(
            re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·（）()]{1,16}", s) for s in prose
        ):
            return "KEEP", "structured_enum_or_identity_field"
        if prose and all(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·@:\-]{1,16}", s) for s in prose):
            return "KEEP", "structured_enum_or_identity_field"
        if prose:
            return "FIX", "free_prose_mechanical_dependency"
        return "KEEP", "structured_enum_identity_transport_or_contract"

    return "KEEP", "structured_enum_identity_transport_or_contract"


def main() -> int:
    rows = []
    for path, line, kind, detail in iter_hits():
        decision, basis = classify(path, kind, detail)
        rows.append(
            {
                "path": path,
                "line": line,
                "kind": kind,
                "detail": detail,
                "decision": decision,
                "basis": basis,
            }
        )
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fix_lines = [
        f"{r['path']}:{r['line']}:{r['basis']}:{r['detail']}"
        for r in rows
        if r["decision"] == "FIX"
    ]
    OUT_FIX.write_text("\n".join(fix_lines) + ("\n" if fix_lines else ""), encoding="utf-8")
    c = Counter(r["decision"] for r in rows)
    print(f"TOTAL={len(rows)} FIX={c['FIX']} KEEP={c['KEEP']}")
    print("FIX bases:", dict(Counter(r["basis"] for r in rows if r["decision"] == "FIX")))
    print("KEEP bases:", dict(Counter(r["basis"] for r in rows if r["decision"] == "KEEP")))
    print(f"wrote {OUT_FIX} ({len(fix_lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
