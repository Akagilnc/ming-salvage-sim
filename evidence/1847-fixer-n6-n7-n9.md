# #1847 修内司报告：N6 / N7 / N9（证据质量收尾）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-n6-n7-n9`
- 本轮：证据 TSV 记录换行改 LF；扫描脚本 `csv.writer(..., lineterminator='\n')`；全仓重扫 HEAD；全部 `NEEDS_HUMAN` 人工核归类；适用运输删改 FIX 修净；过期删改实例标 `FIX_DONE`
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
3. **N9**：本票删除生产入口后的私有闭包与专属测试（**调用图**扫描）。保留生产共享与现役 0055 负向闸。**最终类别不以符号名称启发为界**。

跨票不施工：**N8**（#1873）、**X1/X2**（#1826/#1873）。

## 可重跑完整枚举命令（可执行；写出一律 LF）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
cd "$ROOT"
mkdir -p /tmp/ming1847-fixer-scan
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python   # 或本机 python3

# ---------- 1) 宽 rg 候选（不限字段名；全仓 py/ts/tsx，无名称白名单）----------
rg -n --no-heading \
  '(\.strip\(|\.lstrip\(|\.rstrip\(|\.trim\(|\[:\s*[0-9]+\]|\.replace\(|re\.(sub|split|findall|search|match|fullmatch)|\.split\(|\.join\(|\.filter\()' \
  -g'*.py' -g'*.ts' -g'*.tsx' -g'*.js' \
  --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!**/dist/**' \
  | tee /tmp/ming1847-fixer-scan/rg-wide.txt | wc -l

# ---------- 2) N6 AST+TS 全量候选 → evidence/1847-n6-candidates-raw.tsv ----------
# 完整表分类不以自动 KEEP 为判断证据：新候选标 NEEDS_HUMAN；已有行保留人工 disposition。
# 写出：csv.DictWriter(..., lineterminator='\n')——只改记录换行，不改 snip 自由文本。
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
paths += list(ROOT.glob("*.py"))
for path in sorted(set(paths)):
    if not path.is_file() or (set(path.parts) & SKIP):
        continue
    if "tests" in path.parts or ".test." in path.name:
        continue  # N6 生产成员表不含测试文件
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
    w = csv.DictWriter(
        f, fieldnames=["lang", "file", "line", "kind", "detail", "ctx", "snip"],
        delimiter="\t", lineterminator="\n",
    )
    w.writeheader(); w.writerows(uniq)
print("raw_rows", len(uniq), "->", OUT)
PY

# ---------- 2b) 运输赋值形审计（判空定义：strip 结果不可赋给运输；无名称白名单）----------
"$PY" <<'PY' | tee /tmp/ming1847-fixer-scan/n6-assign-transport.txt
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

print("=== PY strip-assign transport suspects (no name whitelist) ===")
for path in sorted(ROOT.glob("ming_sim/**/*.py")) + [ROOT/"web_app.py"]:
    src = path.read_text(encoding="utf-8"); lines = src.splitlines()
    try: v = V(lines); v.visit(ast.parse(src))
    except SyntaxError: continue
    rel = str(path.relative_to(ROOT))
    for ln, name, snip, uses in v.findings:
        print(f"{rel}:{ln} {name} | {snip}")
        for uln, ul in uses: print(f"  use@{uln}: {ul}")

print("=== TS trim-assign transport suspects (no name whitelist) ===")
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

# ---------- 4) N9：退役闭包调用图（最终类别=调用图证据，非符号名启发）----------
"$PY" <<'PY'
import ast, pathlib, re, csv
ROOT = pathlib.Path(".").resolve()
# 固定种子 = 本票已知退役生产入口；另列现役已知入口作 KEEP 对照。
# 禁止用 rescript/capability 等名称正则作为最终类别界限。
SEEDS = [
    "prepare_rescript_prewrite", "bind_decisions_to_candidate_events",
    "parse_rescript_capability_pair", "decision_has_rescript_capability",
    "RESCRIPT_CAPABILITY_DECISIONS", "derive_draft_capability",
    "_DRAFT_CAPABILITY_KEYS", "_DRAFT_CAPABILITY_JSON_KEYS", "PARTICIPANT_ROSTER_KEY",
]
LIVE = ["run_rescript_text", "run_player_month_chain", "resolve_directives"]
names = SEEDS + LIVE
defs = {n: [] for n in names}
call_index = {n: [] for n in names}
test_index = {n: [] for n in names}
files = list(ROOT.glob("ming_sim/**/*.py")) + [ROOT/"web_app.py"] + list(ROOT.glob("tests/**/*.py"))
for path in files:
    src = path.read_text(encoding="utf-8")
    try: tree = ast.parse(src)
    except SyntaxError: continue
    rel = str(path.relative_to(ROOT)); is_test = rel.startswith("tests/")
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names:
            defs[n.name].append(f"{rel}:{n.lineno}")
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in names:
                    defs[t.id].append(f"{rel}:{n.lineno}")
    for name in names:
        for m in re.finditer(rf"\b{re.escape(name)}\b", src):
            ln = src.count("\n", 0, m.start()) + 1
            line = src.splitlines()[ln - 1]
            if re.search(rf"^\s*(def|async def|class)\s+{re.escape(name)}\b", line): continue
            if re.search(rf"^\s*{re.escape(name)}\s*=", line): continue
            (test_index if is_test else call_index)[name].append(f"{rel}:{ln}")
out = ROOT / "evidence" / "1847-n9-members-classified.tsv"
with out.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t", lineterminator="\n")
    w.writerow(["disposition", "reason", "symbol", "defs", "prod_callers", "test_refs"])
    for name in names:
        d, c, t = defs.get(name, []), call_index[name], test_index[name]
        if not d and not c:
            disp, reason = "GONE", "定义与生产引用均已删除（调用图）"
        else:
            disp, reason = "KEEP_production", "仍有生产定义或调用（调用图；非名称启发）"
        w.writerow([disp, reason, name, ";".join(d) or "NONE", ";".join(c[:12]) or "NONE", ";".join(t[:12]) or "NONE"])
        print(f"{disp:16} {name}")
print("->", out)
PY
```

### 冻结文件（本轮实测）

| 文件 | 行数（含表头） | 内容 |
|---|---:|---|
| `evidence/1847-n6-candidates-raw.tsv` | 2149 | 全仓 AST/TS 原始候选（LF；生产侧，不含 `*.test.*`） |
| `evidence/1847-n6-members-classified.tsv` | 2152 | 生产侧分类；**人工 disposition**；`NEEDS_HUMAN=0` |
| `evidence/1847-n7-members-classified.tsv` | 166 | 引擎/测试 stdout·stderr 成员表（LF；生产无 Codex banner） |
| `evidence/1847-n9-members-classified.tsv` | 13 | 调用图种子+现役入口（LF；**非名称启发定界**） |
| `evidence/1847-fix-done.tsv` | 21 | 已修短清单（含本轮 3 处） |

**完整成员表以 TSV 为准。** 本轮重扫后全部原 `NEEDS_HUMAN` 已逐条人工核；**不得**用「未完成 FIX=0」掩盖未核项——当前实测：`NEEDS_HUMAN=0`，未完成 `FIX=` 前缀=0，`FIX_DONE`（成员表）=8。

## N6 本轮处置

### 适用运输删改候选（实测列出）→ 已修净

| 位置 | 原状 | 处置 |
|---|---|---|
| `ming_sim/month_chain.py` `run_world_segment_text` | `message = cheat.strip() + …` | **FIX**：判空可读 strip；拼入世界段用原文 |
| `ming_sim/month_chain.py` `run_player_month_chain` | `chain["cheat_directive"]=cheat.strip()` | **FIX**：持久化原文；strip 仅判空 |
| `ming_sim/credit_events.py` `_narrative_context` | `text=….strip(); return text` | **FIX**：strip 仅判空；`return` 原文 |

### 过期删改实例（表内不得再 KEEP）

| 旧表位 | 现况 | 处置 |
|---|---|---|
| `web_app.py` 旧 L5527/5538 `text.strip()` 入 capture/update | HEAD 现 L5529/L5540 用原文 `text` | **FIX_DONE**（引用 `1847-fix-done.tsv`） |
| 既有 UI/web/CLI/materials 修净行 | 见 fix-done | **FIX_DONE** |

### 人工核后 KEEP（重点复核，非字段名启发）

| 位置 | 结论 |
|---|---|
| `action_clusters.py` `s[:spec.max_len]` | **KEEP_identity_or_formal**：catalog 实测 max_len 字段 = `target_id` / `target_candidate` / `name` / `station*` / `office` / `region_id` / `responsible_bodies`（机械身份/机关串）；**不是**自由叙事散文。不凭模块名判形式语言。 |
| `declaration_dispatch` `purpose.strip` | **KEEP_identity_or_formal**：ECONOMY_PURPOSES 枚举链 |
| `cli_backend._grounding_source_text` | **KEEP_match_or_normalize**：接地匹配输入面（ADR 0142）；玩家召对原文运输在 scene/chat 路径另线保留 |
| `audience_night.recognize_*` strip | **KEEP_command**：封闭口令集匹配 |
| UI 条件判空（history/report/gazette/situation/chatModal） | **KEEP_empty_check**：trim 只在条件；展示/运输用原值 |
| `web_app` L2773 / L5522 `if not text.strip()` | **KEEP_empty_check**：仅判空（运输已原文） |
| `edictModal` source/actor trim | **KEEP_identity_or_formal**：结构化标签 |
| `settleStream` error trim | **KEEP_diag** |
| `format.splitReportItems` | **KEEP_dead_or_unused**：无生产调用方 |
| 菜单 baseUrl/model trim | **KEEP_ui_config_or_empty** / 身份配置 |
| 诊断 `raw[:N]` / `tlog(title[:N])` / 列表限额切片 | **KEEP_diag** / **KEEP_structural**（本轮原 NEEDS_HUMAN 已核） |

### 复扫计数（HEAD 实测）

- `NEEDS_HUMAN` = **0**（逐条人工核后）
- 未完成 `disposition=FIX` = **0**
- `FIX_DONE`（成员表）= **8**；`1847-fix-done.tsv` = **17 FIX_DONE + 3 FIX_DONE_PRIOR**
- 证据 TSV：`file` 报无 CRLF（本轮改 LF）

## N7 / N9

- N7：生产 `ming_sim` 无 `OpenAI Codex v` banner；正文路径仍 stdout/`final_text`；负向闸测试保留。成员表 165 行（LF）。
- N9：固定退役种子 9 个全部 **GONE**（调用图 defs=0 且 prod_callers=0）；现役 `run_rescript_text` / `run_player_month_chain` / `resolve_directives` **KEEP_production**。最终类别仅依调用图，**未**用符号名 KW 作界限。未补 N8。

## 测试改动

| 项 | 处置 |
|---|---|
| 本轮新增证明测试 | **0** |
| 上轮已删三则自由文本锁字测试 | 保持删除 |
| N7 结构化负向闸 | **保留** |

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

结果：**208 passed in 13.71s**。

`web`：`npx tsc -p . --noEmit` → exit 0。

`git diff --check`（工作树）：无报错。提交后对 `6d042ddd9..HEAD` 复检应无证据 TSV CRLF trailing whitespace。

未跑全量；未做真实模型；未 stash/amend/push/PR/配置改动；未补 N8。

## 质量合法性自查（自查二连 done）

- 同类根因：无名称白名单运输赋值审计；`KEEP_match_or_normalize` / `KEEP_identity_or_formal`（含 max_len）按字段语义核，不凭模块/字段名；证据 CRLF→LF；脚本 `lineterminator='\n'`
- 引入 bug：未恢复六动作、未补 N8/X1/X2、未造证明测试、未全量
- 删简优先：只修适用运输 strip；无新机制
- 自建物仅 `evidence/` 与 `/tmp/ming1847-fixer.*`

## commitSha / 剩余跨票

- **先验生产修理**：`00e2d9a44828cd369e9624e8c263f85ebd5934bf`
- **本轮 commitSha**：见交卷 `git rev-parse HEAD`
- **剩余跨票**：N8→#1873；X1→#1826；X2→#1873/#1826
