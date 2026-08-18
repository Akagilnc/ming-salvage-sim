"""#629 S2 — 复命/哭谏/检举用词 prompt 定向增量。

目标文件 + 章节清单（白名单；白名单外 diff 必须零变化）：
1. content/prompts/season_simulator.md
   - 输入真值 · `due_commitments` 条
   - 奏章目录 · `N+2` 章名
   - `### 复命` 章（原「承诺复核」）
   - `### 探子回报` 章（检举 diegetic）
   - 范例章「六、复命」
   - 文末略章说明中的章名
2. content/prompts/minister_agent.md
   - 召对场面用词（复命/哭谏/泣血陈情）段

正向表述（P4 明文口径）：复命 / 复期已至 / 泣血陈情 / 检举；
禁系统词（due_review / breach_plea / foundation_tier 等）入 prompt 玩家向说明。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_REF = "5d7223ba"  # 票面 base

# 白名单：相对 ROOT 的路径 → 允许改动的章节锚点（### 标题或唯一行锚）
S2_PROMPT_WHITELIST: dict[str, tuple[str, ...]] = {
    "content/prompts/season_simulator.md": (
        "due_commitments",  # 输入真值条（行内锚）
        "N+2",  # 目录章名
        "### 复命",  # 主章（含原承诺复核更名）
        "### 探子回报",
        "六、复命",  # 范例
        "没有军事",  # 文末略章说明
        # base 侧更名过渡锚（旧章名行被替换时仍算白名单内）
        "承诺复核",
    ),
    "content/prompts/minister_agent.md": (
        "## 召对场面用词",
    ),
}

# 仅检查本片新增/改写的 diegetic 段，不扫既有「严禁 xxx 系统词」说明行
_DIEGETIC_SECTION_TITLES = (
    "### 复命",
    "### 探子回报",
    "## 召对场面用词",
)

_SYSTEM_LEAK = (
    "due_review",
    "breach_plea",
    "foundation_tier",
    "ENTRY_KIND_",
    "grace_fake",
    "denunciation_true",
    "midcourse_breach_plea",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _git_show(rel: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASE_REF}:{rel}"],
        cwd=ROOT,
        text=True,
    )


def _split_sections(text: str) -> dict[str, str]:
    """按 markdown ## / ### 标题切段；序言键=''。"""
    parts = re.split(r"(?m)^(#{2,3} .+)$", text)
    out: dict[str, str] = {"": parts[0]}
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out[title] = body
    return out


def test_s2_whitelist_declaration_complete():
    """先声明目标文件+章节清单（票面机械可验前提）。"""
    assert set(S2_PROMPT_WHITELIST) == {
        "content/prompts/season_simulator.md",
        "content/prompts/minister_agent.md",
    }
    for rel, anchors in S2_PROMPT_WHITELIST.items():
        assert (ROOT / rel).is_file(), rel
        assert anchors, rel


def test_diegetic_terms_in_simulator_and_minister_prompts():
    """正向表述：复命/复期已至/泣血陈情/检举入 simulator+召对 prompt。"""
    sim = _read("content/prompts/season_simulator.md")
    assert "复命" in sim
    assert "复期已至" in sim
    assert "检举" in sim
    # 章名收口为 diegetic「复命」，旧系统味「承诺复核」不再作章标题
    assert re.search(r"^### 复命", sim, re.M)
    assert not re.search(r"^### 承诺复核", sim, re.M)

    minister = _read("content/prompts/minister_agent.md")
    assert "复命" in minister
    assert "哭谏" in minister or "泣血陈情" in minister
    assert "泣血陈情" in minister

    # 本片 diegetic 段不得把系统标识当正面用词写入（既有「严禁 xxx」说明不在此扫）
    for rel, titles in (
        ("content/prompts/season_simulator.md", ("### 复命", "### 探子回报")),
        ("content/prompts/minister_agent.md", ("## 召对场面用词",)),
    ):
        secs = _split_sections(_read(rel))
        for title_key, body in secs.items():
            if not any(title_key.startswith(t) for t in titles):
                continue
            blob = title_key + body
            for token in _SYSTEM_LEAK:
                assert token not in blob, (rel, title_key, token)


def test_whitelist_outside_sections_zero_diff_vs_base():
    """白名单外章节相对票面 base diff 零变化。"""
    for rel, anchors in S2_PROMPT_WHITELIST.items():
        base = _git_show(rel)
        head = _read(rel)
        if rel.endswith("minister_agent.md"):
            # 新章整段追加：base 全文必须是 head 的前缀（只许尾部增量）
            # 或：除白名单新章外，其余 section 字节级相等
            base_secs = _split_sections(base)
            head_secs = _split_sections(head)
            for title, body in base_secs.items():
                if title.startswith("## 召对场面用词"):
                    continue
                assert title in head_secs, f"丢失章节 {title!r} in {rel}"
                # 尾随空行因新章追加会产生，不计入实质 diff
                assert head_secs[title].rstrip("\n") == body.rstrip("\n"), (
                    f"白名单外章节被改：{title!r} in {rel}"
                )
            # 新章必须存在
            assert any(t.startswith("## 召对场面用词") for t in head_secs), rel
            continue

        # season_simulator：按行 diff，仅允许命中白名单锚点的行及其紧邻段变化
        base_lines = base.splitlines(keepends=True)
        head_lines = head.splitlines(keepends=True)
        # 用简单 LCS-unaware：逐行对齐失败则按「变更行必须含锚点或落在白名单节内」
        if base == head:
            continue
        import difflib
        sm = difflib.SequenceMatcher(a=base_lines, b=head_lines)
        changed_head_idxs: list[int] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            changed_head_idxs.extend(range(j1, j2))
            # 删除行也须能在 base 侧归因到白名单（改名/改写）
            for bi in range(i1, i2):
                line = base_lines[bi]
                assert any(a in line for a in anchors) or _line_in_whitelist_section(
                    base_lines, bi, anchors
                ), f"base 非白名单行被改/删：L{bi+1}: {line!r}"

        for ji in changed_head_idxs:
            line = head_lines[ji]
            assert any(a in line for a in anchors) or _line_in_whitelist_section(
                head_lines, ji, anchors
            ), f"head 非白名单行新增/改写：L{ji+1}: {line!r}"


def _line_in_whitelist_section(lines: list[str], idx: int, anchors: tuple[str, ...]) -> bool:
    """向上找最近 ###/目录锚，判断是否落在白名单节。"""
    # 目录区：含 N+2 的 fenced 目录块
    for a in anchors:
        if a in ("N+2", "六、复命", "没有军事", "due_commitments"):
            # 这些是行级锚：允许该锚出现的行及其同段连续改写
            pass
    # 回溯最近 ### 标题
    title = ""
    for k in range(idx, -1, -1):
        s = lines[k].strip()
        if s.startswith("### "):
            title = s
            break
        if s.startswith("## ") and not s.startswith("### "):
            title = s
            break
    if title:
        for a in anchors:
            if a.startswith("###") and title.startswith(a):
                return True
    # 行本身或邻近 ±2 行含锚点
    lo = max(0, idx - 2)
    hi = min(len(lines), idx + 3)
    window = "".join(lines[lo:hi])
    return any(a in window for a in anchors)
