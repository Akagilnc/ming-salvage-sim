#!/usr/bin/env python3
"""#1900 J6 冻结分析：宽谓词结构候选旗标（非生产机制，非语义处置）。

读 j6-universe.jsonl 对应源码，按**保守宽谓词**列出候选。故意覆盖类定义全文信号：
  - 所有 assert/expect 文本比对与计数
  - 所有 mock/patch/spy 与调用断言
  - 所有 helper/private 调用与内部公式/oracle
  - 退役/迁移标记符号
不因存在结果 token（list_/apply_/status_code 等）而跳过其它内部断言。
web 不因有 fireEvent/userEvent 而豁免 mock/spy/calls。

硬约束：
  - 有信号 ≠ 即属 J6 类；无信号 ≠ 不属类。
  - 本脚本**禁止**写 action=retain。语义结论只写在 disposition / class-members。

用法（工作树根，先跑 j6_enumerate_universe.py）：
  python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(__file__).resolve().parent
UNIVERSE = OUT_DIR / "j6-universe.jsonl"

# Local test fixtures named _foo are still helper-shaped; flag them for semantic review.
PRIVATE_CALL_RE = re.compile(
    r"(?:"
    r"from\s+ming_sim[\w.]*\s+import\s+[^\n]*\b_\w+"
    r"|\b(?:db|game|session|web_app|month_chain|issues|decree_mod|ep)\._[a-zA-Z]\w*\s*\("
    r"|\b_[a-zA-Z]\w*\s*\("
    r")"
)
ORACLE_RE = re.compile(
    r"\b(?:power_band|recompute_\w+|_\w*oracle\w*|oracle_\w+)\s*\(",
    re.I,
)
TEXT_ASSERT_PY_RE = re.compile(
    r"(?:"
    r"pytest\.raises\s*\([^)]*\bmatch\s*="
    r"|assert\s+[^\n]*(?:==|!=|in|not in)\s*[^\n]*[\"']"
    r"|assert\s+[\"'][^\n]*(?:in|not in)"
    r"|assert\s+[^\n]*\.(?:startswith|endswith|find|index|count)\s*\("
    r")"
)
COUNT_ASSERT_PY_RE = re.compile(
    r"(?:"
    r"assert\s+len\s*\("
    r"|assert\s+[^\n]*\b(?:count|calls?|attempts?|rows?|lines?|tickets?)\w*\s*==\s*\d+"
    r"|assert\s+\d+\s*==\s*[^\n]*\b(?:count|calls?|len|attempts?|rows?|lines?)"
    r"|assert\s+[^\n]*==\s*\d+\b"
    r")"
)
MOCK_PY_RE = re.compile(
    r"(?:"
    r"monkeypatch\.setattr"
    r"|unittest\.mock"
    r"|MagicMock\s*\("
    r"|Mock\s*\("
    r"|AsyncMock\s*\("
    r"|patch\s*\("
    r"|create_autospec\s*\("
    r"|PropertyMock\s*\("
    r")"
)
CALLS_ASSERT_PY_RE = re.compile(
    r"(?:"
    r"assert_called"
    r"|assert_not_called"
    r"|assert_any_call"
    r"|assert_has_calls"
    r"|call_count"
    r"|assert\s+\w*calls?\w*\s*=="
    r")"
)
RETIRED_RE = re.compile(
    r"(?:"
    r"_set_meta_flag"
    r"|__leverage_offsets"
    r"|escort_sources"
    r"|dossier_escort_outcomes"
    r"|_resolve_covert_escort"
    r"|retired|退役|legacy_"
    r")",
    re.I,
)
WEB_MOCK_RE = re.compile(
    r"(?:"
    r"toHaveBeenCalled"
    r"|vi\.mock\s*\("
    r"|vi\.spyOn\s*\("
    r"|vi\.fn\s*\("
    r"|jest\.fn\s*\("
    r"|jest\.spyOn\s*\("
    r"|jest\.mock\s*\("
    r"|\.mockImplementation"
    r"|\.mockReturnValue"
    r")"
)
WEB_TEXT_RE = re.compile(
    r"(?:"
    r"toHaveTextContent\s*\("
    r"|getBy(?:Text|LabelText|PlaceholderText|DisplayValue|AltText|Title|Role)\s*\("
    r"|findBy(?:Text|LabelText|Role)\s*\("
    r"|queryBy(?:Text|LabelText|Role)\s*\("
    r"|expect\s*\([^)]*\)\s*\.\s*(?:toBe|toEqual|toContain|toMatch)\s*\(\s*[\"'`]"
    r")"
)
WEB_COUNT_RE = re.compile(
    r"(?:"
    r"toHaveBeenCalledTimes\s*\("
    r"|toHaveLength\s*\("
    r"|expect\s*\([^)]*\.length[^)]*\)\s*\.\s*(?:toBe|toEqual)\s*\(\s*\d+"
    r")"
)


def _seg(source: str, line: int, end: int) -> str:
    lines = source.splitlines()
    return "\n".join(lines[line - 1:end])


def flag_py(seg: str) -> list[str]:
    flags: list[str] = []
    if TEXT_ASSERT_PY_RE.search(seg):
        flags.append("assert_text_compare_or_match")
    if COUNT_ASSERT_PY_RE.search(seg):
        flags.append("assert_count")
    if MOCK_PY_RE.search(seg):
        flags.append("mock_or_patch_present")
    if CALLS_ASSERT_PY_RE.search(seg):
        flags.append("assert_calls_shape")
    if PRIVATE_CALL_RE.search(seg):
        flags.append("helper_or_private_call")
    if ORACLE_RE.search(seg):
        flags.append("internal_formula_oracle")
    if RETIRED_RE.search(seg):
        flags.append("retired_or_meta_marker")
    return flags


def flag_web(seg: str) -> list[str]:
    flags: list[str] = []
    if WEB_MOCK_RE.search(seg):
        flags.append("web_mock_spy_or_calls")
    if WEB_TEXT_RE.search(seg):
        flags.append("web_text_assert")
    if WEB_COUNT_RE.search(seg):
        flags.append("web_count_assert")
    if RETIRED_RE.search(seg):
        flags.append("retired_or_meta_marker")
    return flags


def main() -> int:
    if not UNIVERSE.is_file():
        print("missing j6-universe.jsonl; run j6_enumerate_universe.py first", file=sys.stderr)
        return 1
    cache: dict[str, str] = {}
    candidates = []
    for line in UNIVERSE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        path = ROOT / row["file"]
        source = cache.setdefault(row["file"], path.read_text(encoding="utf-8", errors="replace"))
        seg = _seg(source, row["line"], row["end"])
        flags = flag_web(seg) if row["kind"] == "web" else flag_py(seg)
        if flags:
            candidates.append({**row, "flags": flags})

    summary = {
        "universe_path": str(UNIVERSE.relative_to(ROOT)),
        "candidate_count": len(candidates),
        "by_flag": {},
        "note": (
            "WIDE structural candidates only; presence of result/API tokens does not suppress "
            "other flags; absence of flag does not prove non-membership; "
            "do not treat this file as retain disposition"
        ),
        "widened": True,
        "removed_narrowing": [
            "no longer require Chinese>=10 + wording/label/材料/邸报 for text locks",
            "no longer suppress helper/mock when list_/apply_/status_code tokens present",
            "no longer require web toHaveBeenCalled AND absence of fireEvent/userEvent",
        ],
    }
    for item in candidates:
        for flag in item["flags"]:
            summary["by_flag"][flag] = summary["by_flag"].get(flag, 0) + 1

    out = OUT_DIR / "j6-structural-candidates.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for item in candidates:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    (OUT_DIR / "j6-structural-candidates-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {out.relative_to(ROOT)} ({len(candidates)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
