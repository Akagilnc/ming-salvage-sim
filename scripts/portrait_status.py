#!/usr/bin/env python3
"""扫 content/characters.json + web/public/portraits/，生成立绘进度表 docs/portrait-status.md。

可反复跑：生图进度变了重跑刷新表。
状态判定：
  已生成      —— 存在 clean 文件名 minister_<姓名>.png / consort_<姓名>.png
  待生成      —— 两者皆无
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OUT = ROOT / "web" / "public" / "portraits"
DOC = ROOT / "docs" / "portrait-status.md"
CHARACTERS = ROOT / "content" / "characters.json"

MING_POWER_ID = "ming"
CONSORT_RANKS = {"皇后", "贵人", "贵妃", "妃", "嫔"}
POOL_N = 20


def main() -> None:
    characters = json.loads(CHARACTERS.read_text("utf-8"))["characters"]

    clean = {p.name for p in OUT.glob("*.png")} if OUT.exists() else set()

    ministers = [
        (c["name"], c.get("office", ""), c.get("faction", ""), f"minister_{c['name']}.png")
        for c in characters
        if "rank" not in c
    ]
    consorts = [
        (c["name"], c.get("office", ""), c.get("faction", ""), f"consort_{c['name']}.png")
        for c in characters
        if c.get("power_id") == MING_POWER_ID and c.get("rank") in CONSORT_RANKS
    ]

    m_rows = ["| 人物 | 势力/派系 | 职位 | 文件 | 状态 |", "|---|---|---|---|---|"]
    m_done = 0
    for cn, office, faction, fn in ministers:
        st = "已生成" if fn in clean else "待生成"
        if st == "已生成":
            m_done += 1
        m_rows.append(f"| {cn} | {faction} | {office} | `{fn}` | {st} |")
    m_n = len(ministers)

    c_rows = ["| 人物 | 派系 | 位分/职位 | 文件 | 状态 |", "|---|---|---|---|---|"]
    c_person_done = 0
    for cn, office, faction, fn in consorts:
        st = "已生成" if fn in clean else "待生成"
        if st == "已生成":
            c_person_done += 1
        c_rows.append(f"| {cn} | {faction} | {office} | `{fn}` | {st} |")
    c_person_n = len(consorts)

    # 后宫预设图池：consort_pool_1..20
    pool_have = sorted(
        int(p.name[len("consort_pool_"):-4])
        for p in OUT.glob("consort_pool_*.png")
        if p.name[len("consort_pool_"):-4].isdigit()
    ) if OUT.exists() else []
    c_done = len(pool_have)

    out = [
        "# 立绘生成进度",
        "",
        "> 自动生成：`.venv/bin/python scripts/portrait_status.py`。改图后重跑刷新。",
        "> 人员名单来源：`content/characters.json`。臣僚/外臣/流寇 = `minister_<中文名>.png`；开局后宫 = `consort_<中文名>.png`；后宫池 = `consort_pool_<N>.png`（不绑人）。",
        "",
        f"## 人物专属图（{m_done}/{m_n} 已生成）",
        "",
        "\n".join(m_rows),
        "",
        f"## 开局后宫专属图（{c_person_done}/{c_person_n} 已生成）",
        "",
        "\n".join(c_rows),
        "",
        f"## 后宫预设图池（{c_done}/{POOL_N} 槽已出图）",
        "",
        f"已出图槽位：{pool_have}",
        f"待补槽位：{[n for n in range(1, POOL_N + 1) if n not in pool_have]}",
        "",
    ]
    DOC.write_text("\n".join(out), encoding="utf-8")
    print(f"写 {DOC}  大臣 {m_done}/{m_n}  后宫池 {c_done}/{POOL_N}")


if __name__ == "__main__":
    main()
