"""#629 S2 — 复命/哭谏/检举用词 prompt 定向增量。

目标文件 + 章节清单（闸类声明；戏内词契约由本文件钉）：
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
        # #1344 夹带：停 LLM 自算年号，改喂 reign_period_label 事实
        "先判当前日期",  # base 旧行
        "直填年号纪年",  # base 旧行
        "{year}年{period}月",  # base 抬头模板旧行
        "reign_period_label",  # head 新行
        "本回合年月",  # head 新行
    ),
    "content/prompts/minister_agent.md": (
        "## 召对场面用词",
    ),
}

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
