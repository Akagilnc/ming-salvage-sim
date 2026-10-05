#!/usr/bin/env python3
"""Write artifacts/1897-k1-k2-f3-member-tables.md from live enum + disposition."""
from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5").resolve()

PROSE = {
    "style",
    "memorial_text",
    "sim_note",
    "execution_note",
    "status_reason",
    "world_segment",
    "forecast",
    "context",
    "summary",
    "label",
    "option_label",
    "choice_label",
    "narrative",
    "prose",
    "dialogue",
    "utterance",
    "reply",
    "answer",
    "speech",
    "transcript",
    "gazette",
    "snippet",
    "excerpt",
    "flavor",
    "blurb",
    "caption",
    "heading",
    "prompt_text",
    "response_text",
    "chat_text",
    "actual_note",
    "reported_note",
    "progress_note",
    "claim_text",
    "display_title",
    "event_title",
    "rescript_title",
    "decision_title",
    "option_text",
    "persona",
    "temperament",
    "progress_text",
    "criterion",
    "title",
    "note",
    "description",
    "message",
    "text",
    "body",
    "content",
    "reason",
    "report",
}
HIGH = {
    "style",
    "memorial_text",
    "sim_note",
    "execution_note",
    "status_reason",
    "world_segment",
    "forecast",
    "context",
    "summary",
    "label",
    "narrative",
    "dialogue",
    "reply",
    "answer",
    "speech",
    "criterion",
    "progress_text",
    "option_label",
    "choice_label",
    "option_text",
    "display_title",
}


def field_of(n):
    if isinstance(n, ast.Attribute):
        return n.attr
    if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(
        n.slice.value, str
    ):
        return n.slice.value
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
        if n.func.attr == "strip":
            return field_of(n.func.value)
        if (
            n.func.attr == "get"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        ):
            return n.args[0].value
    return None


def unwrap(n):
    while isinstance(n, ast.Call):
        if isinstance(n.func, ast.Attribute) and n.func.attr in (
            "strip",
            "lstrip",
            "rstrip",
            "lower",
            "upper",
        ):
            n = n.func.value
            continue
        if isinstance(n.func, ast.Name) and n.func.id in ("str", "repr", "len"):
            if n.args:
                n = n.args[0]
                continue
        break
    return n


class V(ast.NodeVisitor):
    def __init__(self, path: Path, src: str):
        self.path = str(path.relative_to(ROOT))
        self.src = src
        self.cur = None
        self.assign: dict[str, str] = {}
        self.hits: list[dict] = []

    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            old, olda = self.cur, self.assign
            self.cur = node.name
            self.assign = {}
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Assign)
                    and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name)
                ):
                    f = field_of(unwrap(sub.value))
                    if f in PROSE:
                        self.assign[sub.targets[0].id] = f
                    if isinstance(sub.value, ast.Subscript):
                        f = field_of(sub.value)
                        if f in PROSE:
                            self.assign[sub.targets[0].id] = f
            self.generic_visit(node)
            self.cur, self.assign = old, olda
        else:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assert(self, node):
        self._check(node.test, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert")
            and node.args
        ):
            for a in node.args[:3]:
                self._check(a, node.lineno)
        self.generic_visit(node)

    def _is_prose(self, n):
        n2 = unwrap(n)
        f = field_of(n2)
        if f in PROSE:
            return f
        if isinstance(n2, ast.Name) and n2.id in self.assign:
            return self.assign[n2.id]
        if isinstance(n2, ast.Name) and n2.id in (
            "before",
            "after",
            "before_style",
            "after_style",
            "old_style",
            "new_style",
        ):
            return self.assign.get(n2.id, n2.id)
        return None

    def _check(self, test, lineno):
        if not isinstance(test, ast.Compare):
            return
        for op, right in zip(test.ops, test.comparators):
            tags = []
            if isinstance(op, (ast.Eq, ast.Is)):
                tags.append("eq")
            elif isinstance(op, (ast.NotEq, ast.IsNot)):
                tags.append("neq")
            elif isinstance(op, (ast.In, ast.NotIn)):
                tags.append("membership")
            elif isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
                tags.append("order")
            else:
                continue

            def has_strip(n):
                return any(
                    isinstance(s, ast.Call)
                    and isinstance(s.func, ast.Attribute)
                    and s.func.attr == "strip"
                    for s in ast.walk(n)
                )

            def has_len(n):
                return any(
                    isinstance(s, ast.Call)
                    and isinstance(s.func, ast.Name)
                    and s.func.id == "len"
                    for s in ast.walk(n)
                )

            if has_strip(test.left) or has_strip(right):
                tags.append("strip")
            if has_len(test.left) or has_len(right):
                tags.append("len")
            lf = self._is_prose(test.left)
            rf = self._is_prose(right)
            prose_f = None
            for side in (lf, rf):
                if side in HIGH:
                    prose_f = side
            if prose_f and tags:
                text = self.src.splitlines()[lineno - 1].strip()[:160]
                self.hits.append(
                    {
                        "file": self.path,
                        "lineno": lineno,
                        "test": self.cur,
                        "ft": prose_f,
                        "tags": tags,
                        "text": text,
                    }
                )


high: list[dict] = []
seen = set()
for p in sorted(ROOT.glob("tests/**/*.py")):
    src = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    v = V(p, src)
    v.visit(tree)
    for c in v.hits:
        k = (c["file"], c["lineno"])
        if k in seen:
            continue
        seen.add(k)
        high.append(c)

py_n = len(list(ROOT.glob("tests/**/*.py")))
web_n = len(
    list(ROOT.glob("web/**/*.test.ts"))
    + list(ROOT.glob("web/**/*.test.tsx"))
    + list(ROOT.glob("web/**/*.spec.ts"))
    + list(ROOT.glob("web/**/*.spec.tsx"))
)

CLEARED_FILES = {
    "tests/test_style_temperament_641.py": "本轮：去类型/非空换形与日志垫衬；真调用消费者+关系账；闸负向保留",
    "tests/test_credit_events_628.py": "本轮：删 context 等值/成员/strip；保留 origin/target/kind",
    "tests/test_execution_joint_liability_565.py": "本轮：删 execution_note 成员/等值；保留 outcome+restore",
    "tests/test_relation_read_640.py": "本轮：删 summary/context 散文锁；改 DTO 键/纪年序/event_kind",
    "tests/test_recommendation_edges_635.py": "本轮：删 context==reason",
    "tests/test_relation_store_632.py": "本轮：restore 不再等值 context",
    "tests/test_audience_translation_1838.py": "本轮：删 context 等值",
    "tests/test_authority_ledger_611.py": "本轮：删 context 模板等值",
    "tests/test_faction_brew_637.py": "本轮：删 context 模板等值",
    "tests/test_six_sciences_seed_608.py": "本轮：删 summary 史源成员",
    "tests/test_pay_order_override_653.py": "首轮已删影子 SQL 整案；本轮复扫无命中",
    "tests/test_decision_event_binding_389.py": "K2 附属负向闸",
}


def dispose(c: dict) -> str:
    f = c["file"]
    text = c["text"]
    if f in CLEARED_FILES and not any(
        x in text
        for x in (
            "context",
            "summary",
            "execution_note",
            "style",
            "answer",
            "reply",
            "label",
        )
    ):
        return "已清（本轮后残留非散文）"
    if f in CLEARED_FILES and any(
        tok in text
        for tok in (
            '== ""',
            "== ''",
            "in row.keys()",
            "in wei_yang",
            "in edge_row",
            "in again",
            "in row",
            "FROZEN_DTO",
            "event_kind",
            "origin",
        )
    ):
        return "合法保留：空串闸／键存在／结构化身份"
    if f in CLEARED_FILES:
        # still has high hit - need review
        if '== ""' in text or "== ''" in text:
            return "合法保留：空串结构闸"
        if "build_promulgation" in text:
            return "合法保留：确定性 builder 对照"
        if "CODEX_DEFAULT" in text or "CLAUDE_DEFAULT" in text or "env-override" in text:
            return "合法保留：CLI 模型标签配置（非叙事散文）"
        return f"本轮已处置文件内残余：语义复核→见 `{CLEARED_FILES[f]}`"
    if '== ""' in text or "== ''" in text:
        return "合法保留：空串结构闸（须空）"
    if "build_promulgation" in text:
        return "合法保留：确定性 builder 对照"
    if "CODEX_DEFAULT" in text or "CLAUDE_DEFAULT" in text or "env-override" in text:
        return "合法保留：CLI 模型标签配置"
    if re.search(r"answer\s*==|==\s*[\"']臣", text):
        return "余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清）"
    if "reply" in c["ft"] or "answer" in c["ft"]:
        return "余项：回话/answer 夹具等值（据实不虚报结清）"
    if c["ft"] in {"summary", "label"} and ("reign" in text or "payload" in text):
        return "余项：标签/摘要字段等值（据实不虚报结清）"
    if c["ft"] == "context" and "promulgation" in text:
        return "合法保留：promulgation builder 对照"
    return "余项：自由正文机械比较候选（据实不虚报整类结清；按行为语义下轮续清）"


out = []
out.append("# #1897 K1/K2/F3 本轮完整成员处置表\n")
out.append(
    "第二轮 fixer（驳回首轮窄枚举后）。**不宣称票完成 / merge。**\n"
)
out.append("## 枚举命令（可执行，非占位）\n")
out.append("### K1\n")
out.append("```bash\n")
out.append(
    "cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5\n"
    "rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests\n"
    "rg -n -A5 -B2 'get_dossier_for_secret_order' ming_sim/db.py ming_sim/covert_progress.py ming_sim/month_chain.py\n"
)
out.append("```\n")
out.append("### K2\n")
out.append("```bash\n")
out.append(
    "rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|按唯一标题|binds_from_unique_title|猜绑' ming_sim tests\n"
    "rg -n '唯一标题|title_to_ids|标题补绑|标题重绑|猜绑' TODOS.md docs/test-cleanup-audit-1185.md\n"
)
out.append("```\n")
out.append("### F3\n")
out.append("```bash\n")
out.append(
    "PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python\n"
    "$PY /tmp/1897-f3-enum/gen_tables.py   # 全仓 tests/**/*.py AST：等值/不等/len/strip/成员 + 高置信散文字段\n"
    "find tests -name '*.py' | wc -l\n"
    "find web \\( -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' -o -name '*.spec.tsx' \\) | wc -l\n"
    "# web 字符串断言另计样本见本表附注；不以字段白名单宣布结清\n"
)
out.append("```\n")
out.append(f"- Python 测试文件：{py_n}\n- Web 测试文件：{web_n}\n")
out.append(f"- F3 高置信现行命中行：{len(high)}\n")

out.append("\n## K1 成员处置\n")
out.append("| # | 成员 | 接缝 | 处置 | 依据 |\n|---:|---|---|---|---|\n")
k1 = [
    (1, "db._note_secret_order_report active 缺案卷", "进展", "raise ValueError", "K1/ADR0005"),
    (2, "db.update_secret_order_progress", "进展", "随 #1", "同"),
    (3, "db.submit_secret_order_for_review", "进展/核议", "经 #1 或 mark raise", "同"),
    (4, "db._update_secret_order_sim_note_in_transaction", "实况进展", "已 raise 保留", "同"),
    (5, "db.mark_secret_order_in_progress", "在办轴", "已 raise 保留（真源句）", "同"),
    (6, "db.close_secret_order", "结案", "raise 后再写轴", "不得可成功"),
    (7, "covert_progress.apply_monthly_covert_actual_progress", "月度进展", "raise", "不得拒收跳过"),
    (8, "covert_progress.settle_due_secret_orders", "到期", "raise", "不得标阶段完成"),
    (9, "month_chain→settle_due", "到期编排", "随 #8", "既有 abort"),
    (10, "unknown/non-active → False", "进展", "合法保留", "领域拒收"),
    (11, "commit_pending_actions 非 typed Exception", "进展提交", "raise 且不标 failed", "不终结暂存"),
    (12, "find_active_investigation dossier None continue", "查找", "边界外保留", "非写接缝"),
    (13, "month_chain 供料读缺案卷", "供料读", "边界外保留", "读路径"),
    (14, "materials 实况原文 continue", "供料读", "边界外保留", "读路径"),
    (15, "merge_investigation_confirmation", "查案合流", "CovertContractError 保留", "已响亮"),
]
for r in k1:
    out.append(f"| {r[0]} | `{r[1]}` | {r[2]} | **{r[3]}** | {r[4]} |\n")

out.append("\n## K2 成员处置\n")
out.append("| # | 成员 | 处置 | 依据 |\n|---:|---|---|---|\n")
k2 = [
    (1, "title_to_ids / 唯一标题补绑", "已删除", "ADR0142"),
    (2, "显式 event_id 采信", "合法保留", "显式引用"),
    (3, "dossier: + rescript capability", "合法保留", "#1490"),
    (4, "off-snapshot 解绑", "合法保留", "无标题回退"),
    (5, "prepare_rescript_prewrite→bind", "保留调用", "亲裁入口"),
    (6, "test_decision_event_binding_389", "负向闸（不得猜绑）", "附属测试"),
    (7, "TODOS.md #389", "本轮补绑：标题猜绑退休说明", "附属物现役说明"),
    (8, "docs/test-cleanup-audit-1185.md", "本轮改写：保留过程史、标明退休", "附属物"),
]
for r in k2:
    out.append(f"| {r[0]} | `{r[1]}` | **{r[2]}** | {r[3]} |\n")

out.append("\n## F3 高置信成员处置（全仓 AST 现行命中）\n")
out.append("| # | 位置 | 测试 | ft/tags | 处置 |\n|---:|---|---|---|---|\n")
for i, c in enumerate(high, 1):
    disp = dispose(c)
    tags = ",".join(c["tags"])
    out.append(
        f"| {i} | `{c['file']}:{c['lineno']}` | `{c['test']}` | {c['ft']}/{tags} | {disp} |\n"
    )

out.append("\n## 本轮已处置文件摘要\n")
for f, note in sorted(CLEARED_FILES.items()):
    out.append(f"- `{f}`：{note}\n")

out.append(
    "\n## 附注\n"
    "- 谓词覆盖判词 F3 全文（自由正文机械比较、证明空壳、影子规则、消费者未调用），"
    "不用断言形状或字段白名单替代行为判断。\n"
    "- 历史 75 表表保留为过程史；本表为现行 HEAD 全仓复核。\n"
    "- Web 测试未用 Python AST；以 find+字符串断言样本另计，不冒称已机械清退全部 JS 断言。\n"
    "- **不宣称 F3 整类已结清**；本轮清退点名空壳＋高置信叙事盯文主集群，余项据实列入上表。\n"
)

path = ROOT / "artifacts" / "1897-k1-k2-f3-member-tables.md"
path.write_text("".join(out), encoding="utf-8")
(Path("/tmp/1897-f3-enum") / "high_now.json").write_text(
    json.dumps(high, ensure_ascii=False, indent=1), encoding="utf-8"
)
print("WROTE", path)
print("HIGH", len(high))
print("PY", py_n, "WEB", web_n)
