#!/usr/bin/env python3
"""#1900 J6 冻结分析：结构信号候选旗标（非生产机制，非语义处置）。

读 j6-universe.jsonl 对应源码，按结构信号列出**候选**（mock+calls-only、
私有 helper 直调、meta 迁移标记、疑似文字锁）。

硬约束：
  - 有信号 ≠ 即属 J6 类；无信号 ≠ 不属类。
  - 本脚本**禁止**写 action=retain。语义结论只写在 j6-class-members.jsonl。

用法（工作树根，先跑 j6_enumerate_universe.py）：
  python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py

产出：
  evidence/1900-j18-j6-retire-fixer/j6-structural-candidates.jsonl
  evidence/1900-j18-j6-retire-fixer/j6-structural-candidates-summary.json
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(__file__).resolve().parent
UNIVERSE = OUT_DIR / "j6-universe.jsonl"

EXT_BOUNDARIES = (
    "Popen", "subprocess", "create_chat_model", "run_agent_text", "Agent",
    "CliChat", "httpx", "urllib", "create_promulgation_judge_agent",
    "create_decree_forecast_agent", "create_scene_agent", "create_relation_brew_agent",
    "create_faction_brew_agent", "_run_backend_for_config",
)


def _seg(source: str, line: int, end: int) -> str:
    lines = source.splitlines()
    return "\n".join(lines[line - 1:end])


def flag_py(seg: str) -> list[str]:
    flags: list[str] = []
    has_mp = (
        "monkeypatch.setattr" in seg
        or "unittest.mock" in seg
        or "MagicMock" in seg
        or "patch(" in seg
    )
    asserts_calls = bool(re.search(r"assert\s+\w*calls\w*\s*==", seg)) or (
        "assert_called" in seg
    )
    has_result = any(
        token in seg
        for token in (
            "faction_leverage", "get_character", "list_", "reload_state",
            "apply_", "commit_", "create_decree", "state_payload",
            "status_code", "TestClient", "fetchone", "fetchall",
            "prepare_character_materials", "army_payload",
        )
    )
    ext = any(token in seg for token in EXT_BOUNDARIES)
    if has_mp and asserts_calls and not has_result and not ext:
        flags.append("mock_sut_calls_only")
    if re.search(r"from\s+ming_sim[\w.]*\s+import\s+[^\n]*_\w+", seg) or re.search(
        r"\b(?:db|game|session|web_app|month_chain|issues)\._[a-zA-Z]\w*\s*\(", seg,
    ):
        if not has_result:
            flags.append("private_helper_call_no_obs_token")
    if "_set_meta_flag" in seg or "__leverage_offsets" in seg:
        flags.append("meta_migration_marker_touch")
    if re.search(r"assert\s+.*(in|==|not in).*[\"'][\u4e00-\u9fff]{10,}", seg):
        if any(k in seg for k in ("措辞", "wording", "label", "材料", "邸报")):
            flags.append("possible_text_lock")
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
        if row["kind"] != "py":
            # web：只记 toHaveBeenCalled 且无用户事件 token 的粗信号
            path = ROOT / row["file"]
            source = cache.setdefault(row["file"], path.read_text(encoding="utf-8", errors="replace"))
            seg = _seg(source, row["line"], row["end"])
            if "toHaveBeenCalled" in seg and "fireEvent" not in seg and "userEvent" not in seg:
                candidates.append({**row, "flags": ["web_calls_without_ui_token"]})
            continue
        path = ROOT / row["file"]
        source = cache.setdefault(row["file"], path.read_text(encoding="utf-8", errors="replace"))
        seg = _seg(source, row["line"], row["end"])
        flags = flag_py(seg)
        if flags:
            candidates.append({**row, "flags": flags})

    summary = {
        "universe_path": str(UNIVERSE.relative_to(ROOT)),
        "candidate_count": len(candidates),
        "by_flag": {},
        "note": (
            "structural candidates only; absence of flag does not prove non-membership; "
            "do not treat this file as retain disposition"
        ),
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
