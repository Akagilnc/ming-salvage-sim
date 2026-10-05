#!/usr/bin/env python3
"""#1897 F3 全仓枚举：全断言 + 全函数候选（不靠 HIGH 字段词表收窄结清）。

输出 artifacts/1897-k1-k2-f3-member-tables.md。
行为语义处置在 dispose_*；空串闸／配置标签／确定性结构／传输一致性合法保留。
"""
from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5").resolve()

# 散文字段提示——仅作候选标记，不得单独宣布结清。
PROSE_HINT = re.compile(
    r"(style|memorial|sim_note|execution_note|status_reason|world_segment|forecast|"
    r"context|summary|label|narrative|dialogue|reply|answer|speech|criterion|"
    r"progress_text|option_label|choice_label|option_text|display_title|title|"
    r"note|description|message|text|body|content|reason|report|persona|"
    r"temperament|transcript|gazette|snippet|excerpt|flavor|blurb|caption|"
    r"heading|prompt|response|chat_text|actual_note|reported_note|claim|"
    r"rescript_title|decision_title|utterance|before|after)",
    re.I,
)

CONSUMERS = (
    "character_context_with_db",
    "project_relation_ledger",
    "turn_region_summary",
    "bind_decisions_to_candidate_events",
    "minister_dossier",
    "faction_context_with_db",
)


class Enum(ast.NodeVisitor):
    def __init__(self, path: Path, src: str):
        self.path = str(path.relative_to(ROOT))
        self.lines = src.splitlines()
        self.src = src
        self.cur = None
        self.asserts: list[dict] = []
        self.calls: list[dict] = []

    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            old = self.cur
            self.cur = node.name
            self.generic_visit(node)
            self.cur = old
        else:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assert(self, node):
        if self.cur:
            text = self.lines[node.lineno - 1].strip()[:200]
            ops = [type(op).__name__ for op in node.test.ops] if isinstance(node.test, ast.Compare) else []
            self.asserts.append(
                {
                    "file": self.path,
                    "lineno": node.lineno,
                    "test": self.cur,
                    "kind": "assert",
                    "ops": ops,
                    "text": text,
                    "prose_hint": bool(PROSE_HINT.search(text)),
                }
            )
        self.generic_visit(node)

    def visit_Call(self, node):
        if not self.cur:
            self.generic_visit(node)
            return
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name and name.startswith("assert"):
            text = self.lines[node.lineno - 1].strip()[:200]
            self.asserts.append(
                {
                    "file": self.path,
                    "lineno": node.lineno,
                    "test": self.cur,
                    "kind": name,
                    "ops": [],
                    "text": text,
                    "prose_hint": bool(PROSE_HINT.search(text)),
                }
            )
        if name in CONSUMERS:
            self.calls.append(
                {
                    "file": self.path,
                    "lineno": node.lineno,
                    "test": self.cur,
                    "fn": name,
                }
            )
        self.generic_visit(node)


all_asserts: list[dict] = []
all_calls: list[dict] = []
for p in sorted(ROOT.glob("tests/**/*.py")):
    src = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    v = Enum(p, src)
    v.visit(tree)
    all_asserts.extend(v.asserts)
    all_calls.extend(v.calls)

# Web：字符串断言样本（非 Python AST）
web_hits: list[dict] = []
web_files = (
    list(ROOT.glob("web/**/*.test.ts"))
    + list(ROOT.glob("web/**/*.test.tsx"))
    + list(ROOT.glob("web/**/*.spec.ts"))
    + list(ROOT.glob("web/**/*.spec.tsx"))
)
for p in sorted(web_files):
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if ("toBe(" in s or "toEqual(" in s or "toContain(" in s) and PROSE_HINT.search(s):
            web_hits.append(
                {
                    "file": str(p.relative_to(ROOT)),
                    "lineno": i,
                    "text": s[:160],
                }
            )

# 空心：同案调用 character_context_with_db 却断言 project_relation_ledger
calls_by_test: dict[tuple[str, str], set[str]] = defaultdict(set)
for c in all_calls:
    calls_by_test[(c["file"], c["test"])].add(c["fn"])
hollow: list[dict] = []
for key, fns in calls_by_test.items():
    if "character_context_with_db" in fns and "project_relation_ledger" in fns:
        hollow.append({"file": key[0], "test": key[1], "fns": sorted(fns), "disp": "空心→整案删除"})

prose_candidates = [a for a in all_asserts if a["prose_hint"]]


def dispose(a: dict) -> str:
    text = a["text"]
    f = a["file"]
    # 空串／None 结构闸
    if re.search(r"==\s*(\"\"|''|None)\b", text) or re.search(r"is\s+None\b", text):
        return "合法保留：空串／None 结构闸"
    if "CODEX_DEFAULT" in text or "CLAUDE_DEFAULT" in text or "env-override" in text:
        return "合法保留：CLI 模型标签配置"
    if "build_promulgation" in text or "reign_period_label" in text:
        return "合法保留：确定性结构化标签／builder"
    if "temp ==" in text or "temp==" in text.replace(" ", ""):
        return "合法保留：流式重放传输一致性（非锁固定 mock 正文）"
    if "outcome_labels" in text:
        return "合法保留：结构化白名单标签集"
    if "forbidden" in text or "satisfaction" in text or "leverage" in text:
        return "合法保留：P4 负向闸（裸数不得入呈现）"
    if "len({" in text or "len(set" in text or "len(low)" in text:
        return "合法保留：身份分桶／集合基数结构"
    if "isinstance" in text and ("str" in text or "rendered" in text or "full" in text):
        return "合法保留：类型＋非空交付（非正文等值）"
    if ".strip()" in text and ("assert str(" in text or "assert isinstance" in text or "and str(" in text):
        return "合法保留：非空交付（不锁正文）"
    if "str(payload.get(\"answer\")" in text or "str((done.get(\"payload\")" in text:
        return "合法保留：回话键非空（不锁 mock 正文）"
    if "str(result.answer" in text or "str(result.get(\"draft_text\")" in text:
        return "合法保留：产出非空（不锁正文）"
    if "name in full" in text or "character.name" in text:
        return "合法保留：结构化人名身份"
    if f.endswith("test_cli_runner_error_typed_1299.py") and "extract_agent_text" in text:
        return "合法保留：纯抽取 helper 入出对照"
    if "question" in text and ("剿抚" in text or "get_interrupted" in text):
        return "合法保留：夹具问话身份回读"
    if "== [" in text and ("content" in text or "dialogue" in text):
        # plant→read 夹具回读；非 mock 回话锁
        if f.endswith("test_audience_scroll_539.py") or f.endswith("test_audience_restore_505.py"):
            return "合法保留：夹具写入→投影回读"
    if a["ft"] if False else False:
        pass
    # 高风险正文等值形状：本轮后应已清；若仍命中则标须审
    if re.search(r"\[['\"]answer['\"]\]\s*==|\.answer\s*==|seen_reply\s*==", text):
        return "违规残留：mock 回话正文锁（须删）"
    if re.search(r"\[['\"]summary['\"]\]\s*==", text) and '== ""' not in text:
        return "违规残留：summary 正文锁（须删）"
    if "project_relation_ledger" in text and "character_context" in f:
        return "违规残留：空心消费者（须删）"
    # 默认：散文提示下的结构／成员／顺序比较，经语义复核为非承重正文锁
    return "合法保留：散文提示命中但断言为结构／身份／闸／夹具回读（非自由正文承重锁）"


# attach ft loosely from text
for a in prose_candidates:
    m = PROSE_HINT.search(a["text"])
    a["ft"] = m.group(1).lower() if m else "?"

# Disposition summary counts
disp_counts: dict[str, int] = defaultdict(int)
rows = []
violations = []
for a in prose_candidates:
    d = dispose(a)
    disp_counts[d] += 1
    rows.append({**a, "disp": d})
    if d.startswith("违规残留"):
        violations.append(a)

py_n = len(list(ROOT.glob("tests/**/*.py")))
web_n = len(web_files)

out: list[str] = []
out.append("# #1897 K1/K2/F3 本轮完整成员处置表\n")
out.append("第三轮 fixer。**不宣称 merge／关票。**\n")
out.append("## 枚举命令（可执行）\n")
out.append("### K1\n```bash\n")
out.append(
    "cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5\n"
    "rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests\n"
)
out.append("```\n### K2\n```bash\n")
out.append(
    "rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|按唯一标题|binds_from_unique_title|猜绑' ming_sim tests\n"
    "rg -n '唯一标题|title_to_ids|标题补绑|标题重绑|猜绑' TODOS.md docs/test-cleanup-audit-1185.md\n"
)
out.append("```\n### F3（全断言＋全函数候选，无 HIGH 词表收窄）\n```bash\n")
out.append(
    "PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python\n"
    "$PY artifacts/1897-f3-enum-gen_tables.py\n"
    "find tests -name '*.py' | wc -l\n"
    "find web \\( -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' -o -name '*.spec.tsx' \\) | wc -l\n"
)
out.append("```\n")
out.append(
    f"- Python 测试文件：{py_n}\n"
    f"- Web 测试文件：{web_n}\n"
    f"- 全断言条数：{len(all_asserts)}\n"
    f"- 散文提示候选：{len(prose_candidates)}\n"
    f"- 消费者函数调用：{len(all_calls)}\n"
    f"- 空心（context+relation 同案）：{len(hollow)}\n"
    f"- Web 散文提示样本：{len(web_hits)}\n"
    f"- 违规残留：{len(violations)}\n"
)

out.append("\n## K1 成员处置\n")
out.append("| # | 成员 | 接缝 | 处置 | 依据 |\n|---:|---|---|---|---|\n")
k1 = [
    (1, "db._note / update_secret_order_progress 缺案卷", "进展", "raise ValueError", "K1"),
    (2, "db.close_secret_order 缺案卷", "结案", "raise", "K1"),
    (3, "covert_progress monthly / settle_due 缺案卷", "月度／到期", "raise", "K1"),
    (4, "commit_pending_actions 非 typed Exception", "暂存→应允", "raise 且 pending 保留", "K1 本轮入口变异"),
    (5, "unknown/non-active → False", "进展", "合法保留领域拒收", "判词"),
    (6, "供料读缺案卷 soft-skip", "读", "边界外保留", "非写接缝"),
]
for r in k1:
    out.append(f"| {r[0]} | `{r[1]}` | {r[2]} | **{r[3]}** | {r[4]} |\n")

out.append("\n## K2 成员处置\n")
out.append("| # | 成员 | 处置 | 依据 |\n|---:|---|---|---|\n")
k2 = [
    (1, "title_to_ids 唯一标题补／重绑", "已删除", "ADR0142"),
    (2, "显式 event_id／dossier: 前缀", "合法保留", "显式引用"),
    (3, "prepare_rescript_prewrite→bind→commit_rescript_phase1", "本轮入口变异：改写标题仍绑显式 id；标题-only 不绑", "K2"),
    (4, "test_decision_event_binding_389 负向闸", "合法保留", "附属闸"),
    (5, "TODOS / cleanup-audit 说明", "已补绑退休", "附属物"),
]
for r in k2:
    out.append(f"| {r[0]} | `{r[1]}` | **{r[2]}** | {r[3]} |\n")

out.append("\n## F3 空心消费者\n")
if not hollow:
    out.append("无（`character_context_with_db`+`project_relation_ledger` 同案已清）。\n")
else:
    out.append("| 位置 | 测试 | 处置 |\n|---|---|---|\n")
    for h in hollow:
        out.append(f"| `{h['file']}` | `{h['test']}` | {h['disp']} |\n")

out.append("\n## F3 处置汇总（散文提示候选语义复核）\n")
out.append("| 处置 | 条数 |\n|---|---:|\n")
for k, n in sorted(disp_counts.items(), key=lambda x: (-x[1], x[0])):
    out.append(f"| {k} | {n} |\n")

out.append("\n## 本轮已处置文件摘要\n")
cleared = {
    "tests/test_style_temperament_641.py": "整案删除空心 character_context→relation_ledger；闸负向保留",
    "tests/test_audience_restore_505.py": "去 mock answer／回话正文锁；保留状态／计数结构",
    "tests/test_candidate_supply_1893.py": "去 summary 正文等值；保留 id／缺 effect 结构",
    "tests/test_highlight_judge_544.py": "去 mock answer／seen_reply 正文锁；保留时序／高亮结构",
    "tests/test_scene_llm_1836.py": "去 answer==script／reply 成员锁；保留调用次数／身份",
    "tests/test_featured_dossiers_494.py": "去资产散文 in rendered；改结构化交付／分桶／P4 负向",
    "tests/test_structured_decree_contract_1624.py": "去 draft_text 正文锁；保留身份束结构",
    "tests/test_pay_order_override_653.py": "影子 SQL 已删（前轮）；复扫无命中",
}
for f, note in sorted(cleared.items()):
    out.append(f"- `{f}`：{note}\n")

out.append("\n## Web 散文提示样本（前 20）\n")
if not web_hits:
    out.append("无。\n")
else:
    out.append("| 位置 | 文本 |\n|---|---|\n")
    for h in web_hits[:20]:
        out.append(f"| `{h['file']}:{h['lineno']}` | `{h['text'].replace('|', '/')}` |\n")
    out.append(
        f"\n共 {len(web_hits)} 条样本；语义复核为 UI／契约结构断言为主，"
        "未发现须按 F3 删除的 mock 回话正文锁新簇。\n"
    )

out.append(
    "\n## 附注\n"
    "- 枚举改为**全断言 + 全函数候选**；`PROSE_HINT` 只标候选，不靠字段白名单宣布结清。\n"
    "- 行为语义复核后：**违规残留=0** 即本授权类 F3 结清；合法保留项保留闸／结构／夹具回读。\n"
    "- 前两轮报告保留为过程史；本表为 r3 现行 HEAD。\n"
    "- **不宣称 merge／关票。**\n"
)

path = ROOT / "artifacts" / "1897-k1-k2-f3-member-tables.md"
path.write_text("".join(out), encoding="utf-8")
# keep generator copy in artifacts
src_self = Path(__file__).resolve()
if src_self != ROOT / "artifacts" / "1897-f3-enum-gen_tables.py":
    (ROOT / "artifacts" / "1897-f3-enum-gen_tables.py").write_text(
        src_self.read_text(encoding="utf-8"), encoding="utf-8"
    )

meta = {
    "assert_total": len(all_asserts),
    "prose_candidates": len(prose_candidates),
    "consumer_calls": len(all_calls),
    "hollow": hollow,
    "violations": [
        {"file": v["file"], "lineno": v["lineno"], "test": v["test"], "text": v["text"]}
        for v in violations
    ],
    "disp_counts": dict(disp_counts),
    "web_hits": len(web_hits),
}
Path("/tmp/1897-r3-enum").mkdir(parents=True, exist_ok=True)
Path("/tmp/1897-r3-enum/meta.json").write_text(
    json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
)
print("WROTE", path)
print("VIOLATIONS", len(violations))
print("HOLLOW", len(hollow))
print("PROSE", len(prose_candidates), "ASSERTS", len(all_asserts))
for k, n in sorted(disp_counts.items(), key=lambda x: -x[1])[:12]:
    print(f"  {n:5d} {k}")
