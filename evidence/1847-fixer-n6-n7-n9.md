# #1847 修内司报告：N6 / N7 / N9（席内错分复核）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-n6-n7-n9`
- 本轮：席内复核错分（`useChatActions` trim→运输 = N6）→ 同形重核 KEEP_* → 修净适用成员 → 删违规证明测试 → 补可执行扫描
- **不宣称**全局功能闭环或已 merge

## 官方文档（动手前）

| 问题 | 文档 | 简单修法 |
|---|---|---|
| N7 stderr 冒充正文 | [Python subprocess](https://docs.python.org/3/library/subprocess.html) | 正文只取 stdout；空输出走既有失败 |
| N7 Codex | [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode) | 禁止 banner/stderr 充正文 |
| N6 trim | [MDN String.prototype.trim](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/trim) | 自由文本运输不 strip/截断；判空可读 strip |

## 根因类定义（末份 + 票面）

1. **N6**：适用自由文本运输接缝上的 strip/lstrip/rstrip/trim、切片截断、replace/regex/split/join/filter/非空后 fallback 等删改。范围含 LLM 产出、玩家输入、角色材料、数据库运输、UI 展示。不含机械身份、枚举、形式语言、**仅判空**（strip 结果只用于条件，不可赋给后续运输值）。
2. **N7**：全部引擎 stdout/stderr 读取及空输出成功路线；禁止 stderr/banner 充正文或把空输出洗成成功。
3. **N9**：本票删除生产入口后的私有闭包与专属测试（调用图扫描）。保留生产共享与现役 0055 负向闸。

跨票不施工：**N8**（#1873）、**X1/X2**（#1826/#1873）。

## 可重跑完整枚举命令（可执行，无伪代码）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
cd "$ROOT"
mkdir -p /tmp/ming1847-fixer-scan
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python   # 或本机 python3

# ---------- 1) 宽 rg 候选（不限字段名）----------
rg -n --no-heading \
  '(\.strip\(|\.lstrip\(|\.rstrip\(|\.trim\(|\[:\s*[0-9]+\]|\.replace\(|re\.(sub|split|findall|search|match|fullmatch)|\.split\(|\.join\(|\.filter\()' \
  -g'*.py' -g'*.ts' -g'*.tsx' -g'*.js' \
  --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!**/dist/**' \
  | tee /tmp/ming1847-fixer-scan/rg-wide.txt | wc -l

# ---------- 2) N6 AST+TS 全量候选 → evidence/1847-n6-candidates-raw.tsv ----------
# 完整表分类不以自动 KEEP 为判断证据：新候选标 NEEDS_HUMAN；已有行保留人工 disposition。
"$PY" <<'PY'
from __future__ import annotations
import ast, csv, pathlib, re
ROOT = pathlib.Path(".").resolve()
OUT = ROOT / "evidence" / "1847-n6-candidates-raw.tsv"
STRIP = {"strip", "lstrip", "rstrip"}
RE_FUNCS = {"sub", "split", "findall", "search", "match", "fullmatch"}
SKIP = {"node_modules", ".venv", "dist", ".git", "__pycache__", "archive"}

def enclosing(tree, lineno):
    best, best_ln = "", -1
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if getattr(n, "lineno", 10**9) <= lineno and n.lineno >= best_ln:
                best_ln, best = n.lineno, n.name
    return best

class Coll(ast.NodeVisitor):
    def __init__(self, path, src):
        self.path, self.lines = path, src.splitlines()
        self.tree, self.rows = ast.parse(src), []
    def run(self):
        self.visit(self.tree); return self.rows
    def add(self, node, kind, detail=""):
        ln = getattr(node, "lineno", 0)
        snip = self.lines[ln - 1].rstrip()[:200] if 1 <= ln <= len(self.lines) else ""
        self.rows.append({"lang": "py", "file": self.path, "line": ln, "kind": kind,
                          "detail": detail, "ctx": enclosing(self.tree, ln), "snip": snip})
    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in STRIP:
            self.add(node, "strip_call", f.attr)
        if isinstance(f, ast.Attribute) and f.attr in {"replace", "split", "join", "filter"}:
            self.add(node, f"{f.attr}_call", f.attr)
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id == "re" and f.attr in RE_FUNCS):
            self.add(node, f"re_{f.attr}", f.attr)
        self.generic_visit(node)
    def visit_Subscript(self, node):
        sl = node.slice
        if isinstance(sl, ast.Slice) and sl.lower is None and sl.upper is not None:
            self.add(node, "slice_trunc_expr", "[:expr]")
        self.generic_visit(node)

raw = []
paths = list(ROOT.glob("ming_sim/**/*.py")) + [ROOT / "web_app.py", ROOT / "launcher.py"]
paths += list((ROOT / "web" / "src").rglob("*.ts")) + list((ROOT / "web" / "src").rglob("*.tsx"))
for path in sorted(set(paths)):
    if not path.is_file() or (set(path.parts) & SKIP):
        continue
    rel = str(path.relative_to(ROOT))
    if path.suffix == ".py":
        try:
            raw.extend(Coll(rel, path.read_text(encoding="utf-8")).run())
        except SyntaxError:
            pass
        continue
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lang = path.suffix.lstrip(".")
    for i, line in enumerate(lines, 1):
        for kind, pat in [
            ("trim_call", r"\.trim\s*\("), ("replace_call", r"\.replace\s*\("),
            ("split_call", r"\.split\s*\("), ("join_call", r"\.join\s*\("),
            ("filter_call", r"\.filter\s*\("),
        ]:
            if re.search(pat, line):
                raw.append({"lang": lang, "file": rel, "line": i, "kind": kind,
                            "detail": "", "ctx": "", "snip": line.rstrip()[:200]})
        if re.search(r"\[\s*:\s*\d+", line) and not line.strip().startswith("//"):
            raw.append({"lang": lang, "file": rel, "line": i, "kind": "slice_trunc_expr",
                        "detail": "[:N]", "ctx": "", "snip": line.rstrip()[:200]})
seen, uniq = set(), []
for r in raw:
    k = (r["file"], r["line"], r["kind"], r["detail"])
    if k in seen:
        continue
    seen.add(k); uniq.append(r)
with OUT.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["lang", "file", "line", "kind", "detail", "ctx", "snip"], delimiter="\t")
    w.writeheader(); w.writerows(uniq)
print("raw_rows", len(uniq), "->", OUT)
PY

# ---------- 2b) 运输赋值形审计（判空定义：strip 结果不可赋给运输）----------
"$PY" <<'PY' | tee /tmp/ming1847-fixer-scan/n6-assign-transport.txt
# 输出「Name = *.strip()/trim() 且后续非纯 if-判空仍 Load」的生产位点，供人工核。
import ast, pathlib, re
ROOT = pathlib.Path(".").resolve()
STRIP = {"strip", "lstrip", "rstrip"}
assign_re = re.compile(r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*.*\.trim\(\)\s*;?\s*$")

class V(ast.NodeVisitor):
    def __init__(self, lines): self.lines, self.findings = lines, []
    def visit_FunctionDef(self, node):
        self._scan(node.body); self.generic_visit(node)
    visit_AsyncFunctionDef = visit_FunctionDef
    def _is_strip(self, n):
        return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in STRIP
    def _scan(self, body):
        for stmt in body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name) and self._is_strip(stmt.value):
                name = stmt.targets[0].id
                uses = []
                for s in body:
                    if getattr(s, "lineno", 0) <= stmt.lineno: continue
                    for n in ast.walk(s):
                        if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load):
                            ul = self.lines[n.lineno - 1]
                            if re.search(rf"if\s+not\s+{name}\b", ul) or re.search(rf"if\s+{name}\s*:", ul):
                                continue
                            uses.append((n.lineno, ul.strip()[:100]))
                if uses:
                    self.findings.append((stmt.lineno, name, self.lines[stmt.lineno-1].strip()[:100], uses[:4]))

print("=== PY strip-assign transport suspects ===")
for path in sorted(ROOT.glob("ming_sim/**/*.py")) + [ROOT/"web_app.py"]:
    src = path.read_text(encoding="utf-8"); lines = src.splitlines()
    try: v = V(lines); v.visit(ast.parse(src))
    except SyntaxError: continue
    rel = str(path.relative_to(ROOT))
    for ln, name, snip, uses in v.findings:
        # 仅打印自由文本形名字，避免身份字段淹没
        if not re.search(r"(text|message|answer|report|draft|prose|condition|purpose|question|cheat|directive|spoken|status_text|reason)", name, re.I):
            continue
        print(f"{rel}:{ln} {name} | {snip}")
        for uln, ul in uses: print(f"  use@{uln}: {ul}")

print("=== TS trim-assign transport suspects ===")
for path in list((ROOT/"web/src").rglob("*.ts")) + list((ROOT/"web/src").rglob("*.tsx")):
    if ".test." in path.name: continue
    rel = str(path.relative_to(ROOT)); lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        m = assign_re.match(line)
        if not m: continue
        name = m.group(1); uses = []
        for j in range(i, min(i + 60, len(lines))):
            ul = lines[j]
            if not re.search(rf"\b{name}\b", ul): continue
            if re.search(rf"if\s*\(\s*!\s*{name}\b", ul) or re.search(rf"if\s*\(\s*{name}\s*\)", ul):
                continue
            uses.append((j + 1, ul.strip()[:100]))
        if uses:
            print(f"{rel}:{i} {name} | {line.strip()[:100]}")
            for uln, ul in uses[:4]: print(f"  use@{uln}: {ul}")
PY

# ---------- 3) N7：引擎 stdout/stderr / 空输出（可执行）----------
rg -n 'stderr|stdout|communicate|subprocess\.(run|Popen)|OpenAI Codex v|llm_empty_output|empty_output_failure|final_text|stdout_text' \
  ming_sim web_app.py launcher.py tests/test_cli_backend.py \
  | tee /tmp/ming1847-fixer-scan/n7-rg.txt | wc -l
rg -n 'OpenAI Codex v' ming_sim || true   # 期望：无

# ---------- 4) N9：退役闭包调用图（可执行，非三符号伪定义）----------
"$PY" <<'PY'
import ast, pathlib, re, csv
ROOT = pathlib.Path(".").resolve()
seeds = [
    "prepare_rescript_prewrite", "bind_decisions_to_candidate_events",
    "parse_rescript_capability_pair", "decision_has_rescript_capability",
    "RESCRIPT_CAPABILITY_DECISIONS", "derive_draft_capability",
    "_DRAFT_CAPABILITY_KEYS", "_DRAFT_CAPABILITY_JSON_KEYS", "PARTICIPANT_ROSTER_KEY",
]
KW = re.compile(r"(rescript|pihong|capability|prewrite|candidate_event|draft_capability)", re.I)
defs = {}
for path in list(ROOT.glob("ming_sim/**/*.py")) + [ROOT / "web_app.py"]:
    src = path.read_text(encoding="utf-8")
    try: tree = ast.parse(src)
    except SyntaxError: continue
    rel = str(path.relative_to(ROOT))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if KW.search(n.name) or n.name in seeds:
                defs.setdefault(n.name, []).append(f"{rel}:{n.lineno}")
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and (KW.search(t.id) or t.id in seeds):
                    defs.setdefault(t.id, []).append(f"{rel}:{n.lineno}")
names = sorted(set(seeds) | set(defs))
call_index = {n: [] for n in names}
test_index = {n: [] for n in names}
for path in list(ROOT.glob("ming_sim/**/*.py")) + [ROOT/"web_app.py"] + list(ROOT.glob("tests/**/*.py")):
    rel = str(path.relative_to(ROOT)); text = path.read_text(encoding="utf-8"); is_test = rel.startswith("tests/")
    for name in names:
        for m in re.finditer(rf"\b{re.escape(name)}\b", text):
            ln = text.count("\n", 0, m.start()) + 1
            line = text.splitlines()[ln - 1]
            if re.search(rf"^\s*(def|async def|class)\s+{re.escape(name)}\b", line): continue
            if re.search(rf"^\s*{re.escape(name)}\s*=", line): continue
            (test_index if is_test else call_index)[name].append(f"{rel}:{ln}")
out = ROOT / "evidence" / "1847-n9-members-classified.tsv"
with out.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["disposition", "reason", "symbol", "defs", "prod_callers", "test_refs"])
    for name in names:
        d, c, t = defs.get(name, []), call_index[name], test_index[name]
        if not d and not c:
            disp, reason = "GONE", "定义与引用均已删除"
        else:
            disp, reason = "KEEP_production", "仍有生产定义或调用"
        w.writerow([disp, reason, name, ";".join(d) or "NONE", ";".join(c[:12]) or "NONE", ";".join(t[:12]) or "NONE"])
        print(f"{disp:16} {name}")
print("->", out)
PY
```

### 冻结文件

| 文件 | 行数（含表头） | 内容 |
|---|---:|---|
| `evidence/1847-n6-candidates-raw.tsv` | 2204 | 全仓 AST/TS 原始候选（本轮可执行扫描重写） |
| `evidence/1847-n6-members-classified.tsv` | 2217 | 生产侧分类；**人工 disposition**；新候选 `NEEDS_HUMAN`（不以自动 KEEP 作判断） |
| `evidence/1847-n7-members-classified.tsv` | 203 | 引擎/测试 stdout·stderr 成员表（可执行 rg 复扫，无 banner） |
| `evidence/1847-n9-members-classified.tsv` | 33 | 调用图种子+KW 符号完整表（可执行脚本重写） |
| `evidence/1847-fix-done.tsv` | 18 | 已修短清单 |

**完整成员表以 TSV 为准。** `NEEDS_HUMAN` = 扫描新增、尚未人工定性；**不得**把自动 KEEP 当证据。本轮人工重核重点 = 全部 `KEEP_empty_check` / `KEEP_ui_*` / `KEEP_match_or_normalize` / `KEEP_identity_or_formal` 中「strip/trim 赋给运输值」同形。

## N6 本轮处置

### 错分样本（席内）→ 已修

| 位置 | 原错分 | 处置 |
|---|---|---|
| `web/src/useChatActions.ts` `sendChat` | `KEEP_ui_empty_or_layout` | **FIX**：`if (!text.trim())` 判空；`message = text` 原文 → `runAudienceTurn` |
| `web_app.py` `chat_stream` | `KEEP_match_or_normalize` | **FIX**：`text = str(message or "")`；strip 仅判空 |
| `web/src/useEdictActions.ts` `saveDirective` | `KEEP_ui_empty_or_layout` | **FIX**：trim 仅判空；PATCH 用原文 |
| `web_app.py` `api_update_directive` | 空检查旁仍 `text.strip()` 入 capture/update | **FIX**：capture/update 用原文 |
| `web/src/components/cheatConsole.tsx` | `KEEP_ui_empty_or_layout` | **FIX**：`onCommit(draft)` 原文 |
| `web/src/useSettlementFlow.ts` cheat | `KEEP_ui_empty_or_layout` | **FIX**：`cheat` body 原文；`trim` 仅判空清空 |
| `ming_sim/cli/terminal.py` 中断提示 | （展示层剥空白） | **FIX**：question 原文展示 |
| `ming_sim/materials.py` `status_text` | `KEEP_empty_check`（实为赋值运输） | **FIX**：strip 仅判空/比 `active`；档料行用原文 |

### 人工核后 KEEP（非 FIX）

| 位置 | 结论 |
|---|---|
| `action_clusters.py` `s[:spec.max_len]` | **KEEP_identity_or_formal**：max_len 字段全集 = name/office/region_id/station*/target_*/responsible_bodies（机械），非自由叙事散文 |
| `declaration_dispatch` `purpose.strip` | **KEEP_identity_or_formal**：ECONOMY_PURPOSES 枚举链 |
| `cli_backend._grounding_source_text` | **KEEP_match_or_normalize**：接地匹配源，非召对原文账本运输 |
| UI 条件判空（history/report/gazette/situation/chatModal button） | **KEEP_empty_check**：trim 只在条件；展示/运输用原值 |
| `edictModal` source/actor trim | **KEEP_identity_or_formal**：结构化标签 |
| `settleStream` error trim | **KEEP_diag** |
| `format.splitReportItems` | **KEEP_dead_or_unused**：无生产调用方 |
| 菜单 baseUrl/model trim | **KEEP_ui_config_or_empty** / 身份配置 |

### 复扫

- `disposition` 以 `FIX`（未完成）开头 = **0**
- `FIX_DONE` 见 `evidence/1847-fix-done.tsv` + classified 表

## N7 / N9

- N7：生产无 `OpenAI Codex v` banner；正文路径仍 stdout/`final_text`；`test_run_codex_stderr_banner_does_not_become_body` 现役。上轮非法成功测试改结构化负向闸 **保留**。
- N9：种子+KW 调用图脚本可重跑；`derive_draft_capability` 等仍 GONE；现役 `run_rescript_text` / desk 等 KEEP_production。未补 N8。

## 测试改动（最小必要成本）

| 项 | 处置 |
|---|---|
| `tests/test_scene_llm_1836.py` 上轮新增三则（58 行） | **已删**（`preserves_player_message_whitespace` / `preserves_answer_whitespace` / `preserves_question_whitespace`）；含自由文本 assert 锁字，违反「不得造修复证明测试」 |
| 文件行数 | 299 → **241**（与加入前一致） |
| N7 结构化负向闸 | **保留**（`test_run_codex_stderr_banner_does_not_become_body` 等） |
| 本轮新增测试 | **0** |

证明：临时变异真实入口可观察输入结构 + 既有聚焦测试（见下）。

## 聚焦测试

前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `MING_SIM_TRACE_PATH` / `--basetemp` → `/tmp/ming1847-fixer.*`  
解释器：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`

```bash
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_HERMES_BIN=/usr/bin/false
export MING_SIM_GEMINI_BIN=/usr/bin/false
export MING_SIM_OPENAI_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_TRACE_PATH=/tmp/ming1847-fixer-trace
mkdir -p /tmp/ming1847-fixer-basetemp /tmp/ming1847-fixer-trace

/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_month_chain_1847.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_month_chain_1843.py \
  tests/test_month_call_recovery_1846.py \
  tests/test_cli_backend.py \
  tests/test_rescript_choices_563.py \
  tests/test_llm_channel_config.py::test_scene_and_rescript_entries_pass_default_headers_at_transport \
  tests/test_new_issues_section_rejections.py::test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition \
  tests/test_scene_llm_1836.py \
  -q --basetemp=/tmp/ming1847-fixer-basetemp
```

结果：**208 passed in 14.63s**（`real 15.70`；相对上轮 211 − 已删三则 = 208）。

`web`：`npx tsc -p . --noEmit` → exit 0（`real 2.69`）。

未跑全量；未做真实模型；未 stash/amend/push/PR/配置改动。

## 变异证据（临时，不入仓）

| 类 | 操作 | 结果 |
|---|---|---|
| N6 | 临时 `session.scene_chat`：`message_text=….strip()`；`/tmp` 外真实入口探针观测 FakeAgent 入参 | **红** `assert ['边饷如何？'] == ['  边饷如何？  \n']` 1 failed / 0.96s → 恢复后 **绿** 1 passed / 0.66s（探针已删，未入仓） |
| N6 | 临时 `web_app.chat_stream`：`text=message.strip()` | 源码层可观察运输绑定剥空白 → 已恢复 |
| N7 | 既有负向闸 | `test_run_codex_stderr_banner_does_not_become_body` 1 passed |
| N9 | `from ming_sim.decree_vocabulary import derive_draft_capability` | ImportError |

## 质量合法性自查（自查二连 done）

- 同类根因：按「判空≠运输赋值」重核 KEEP_empty/ui/match/identity；UI+web_app 同形修净；max_len/purpose/status 逐字段人工定性
- 引入 bug：未恢复六动作、未补 N8/X1/X2、未造证明测试、未全量
- 删简优先：只删违规三则测试；无新机制
- 自建物仅 `evidence/` 与 `/tmp/ming1847-fixer.*`；扫描脚本嵌本报告，无持久 runtime 模块

## commitSha / 剩余跨票

- **先验生产修理**：`00e2d9a44828cd369e9624e8c263f85ebd5934bf`
- **本轮 commitSha**：见交卷 `git rev-parse HEAD`
- **剩余跨票**：N8→#1873；X1→#1826；X2→#1873/#1826
