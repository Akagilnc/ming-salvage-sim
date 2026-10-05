# #1891/#1899 CHOICE-C1 + CLEANUP 全层复核回执

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。

## 分轮 HEAD 史（自初开工 `34262577a`；不得抹）

| 轮 | SHA | 内容 |
| --- | --- | --- |
| 初开工 | `34262577af3f6dbf455e64698ee5335dfcd51ddd` | docs residual independent verify |
| d80 | `d80db9754eca88b28d7daefa0ae50228134f36d5` | CHOICE `terminal_reason` 接收键删 + CLEANUP 点名死支持 |
| 653 | `653b83d47c0cfb776fecdeb6640300aaf31de008` | docs pin choice-cleanup 日志指针／SHA |
| 764 | `764f64b06a744eda6b1465fa23570b0251348d54` | 全层 F401／orphan cleanup + 回执（曾重写抹掉 113／83 史；本轮恢复） |
| 2f0 | `2f0c1e3930ee2b69c9119d658174ac5b6e1f23d5` | Class 方法同形残余 2 DELETE + 回执 A／C／选择器／病史修补 |
| d59 | `d590e92e3268df54257870bc4cb94c0577b7b576` | docs-only：D 自包含 AST 命令＋消费语义∨＋ZERO_STATIC23＋最初13点名补表＋CHOICE 全仓 `terminal_reason` 清单 |
| 本轮 | （本 commit） | ACMR lint 红史→`test_rejection_wiring` `game` fixture 拆行 `# noqa: F401`；独立 thcaU3 事实入档 |

法源方向：CHOICE 退役选项契约残留；CLEANUP 无消费者冗余绑定；**用户授权**＝全仓同类 Class 方法／闭包零静态死定义一并清（非 advisor 可选宽口径）。本轮**仅** fixture 发现标注小修（不改断言／功能）；独立复跑事实与 lint 红史并入回执。
附件：`docs/reports/1891-1899-f401-member-table.tsv`（86＝F401+context）；`docs/reports/1891-1899-class-methods-zero.tsv`（ZERO_STATIC23）。

## 撤回

1. **入口变异证明**：撤回。现有对照只覆盖 `canonical_choice`／`_choices_equal` helper，不是 `submit_rescript_decision` 真入口。CHOICE 合法动作只有一键删除接收键表项；不为清退新增永久测试。
2. **ExceptionGroup「旧误报／非本轮」**：撤回。指派 target 为 py313；漏 `--target-version py313` 才会 F821。按 py313 重跑记录实际结果，不恢复 import 兼容，不把错误归旧。
3. **「C＝methods 已净」**：撤回。原 C 脚本对嵌套 `ClassDef` 直接 `return`，只扫嵌套 `FunctionDef` 的 `Name(Load)`，**从不扫 Class methods 的 Attribute**；`NESTED_FN_ORPHANS=0` 不得冒称 methods 闭包。
4. **消费者＝合取**：撤回。曾写「Attribute ∧ Import ∧ 字符串」——误为须三者同时命中才算消费。正确＝**任一真实消费即可**；零候选＝三者皆无。见下 D。
5. **PARSED345＝全仓**：撤回。`git ls-files '*.py'`＝**351**（含 `docs/raw`×6 冻结卷）；345＝排除 raw 的子集，不得冒称全仓 parse。

## 环境

```bash
set -euo pipefail
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
# ruff 0.11.2: uv tool run --from ruff==0.11.2 ruff
# 目录自包含；uv 两变量与日志根同场创建；命令不依赖既有 /tmp 种子
TMPROOT=$(mktemp -d /tmp/1891-class-methods.XXXXXX)
mkdir -p "$TMPROOT/logs" "$TMPROOT/user" "$TMPROOT/pytest" \
  "$TMPROOT/uv-tools" "$TMPROOT/uv-cache"
export UV_TOOL_DIR="$TMPROOT/uv-tools" UV_CACHE_DIR="$TMPROOT/uv-cache"
# 史指针（可选 tee；复跑不依赖）：2f0=/tmp/1891-class-methods.TbsOIH
# d80=/tmp/1891-choice-cleanup.x4Z74B ；764=/tmp/1891-fullclass.1UvSWC
```

审计为 inline 标准库 `ast` + 现成 ruff；**不新造仓内扫描框架／永久测试**；`ast.parse` 失败直抛；stdio 出 JSON。

## 可复跑枚举命令

### P0. 全仓 gittracked Python 先 `ast.parse`（351；raw 仅解析不删）

```bash
set -euo pipefail
$PY - <<'PY' | tee "$TMPROOT/logs/parsed-python.json"
import ast, json, subprocess, sys
from pathlib import Path
files = subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
fail = []
for rel in files:
    try:
        ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)
    except Exception as e:
        fail.append({'file': rel, 'error': f'{type(e).__name__}: {e}'})
out = {
    'TRACKED_PY': len(files),
    'PARSED_PYTHON': len(files) - len(fail),
    'PARSE_FAIL': len(fail),
    'docs_raw_py': sum(1 for f in files if f.startswith('docs/raw/')),
    'non_raw_py': sum(1 for f in files if not f.startswith('docs/raw/')),
    'fail': fail,
}
json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
print(file=sys.stdout)
if fail:
    raise SystemExit('ast.parse failed')
PY
# 实际：TRACKED_PY=351 PARSED_PYTHON=351 PARSE_FAIL=0 docs_raw_py=6 non_raw_py=345
# 345 只是非 raw 子集计数，不是全仓 parse 口径
```

### A. 全仓 F401（target py313，ignore-noqa）

```bash
set -euo pipefail
uv tool run --from ruff==0.11.2 ruff check \
  --target-version py313 --select F401 --ignore-noqa \
  --output-format json $(git ls-files '*.py') > "$TMPROOT/logs/f401.json"
$PY - "$TMPROOT/logs/f401.json" <<'PY'
import json, sys
from pathlib import Path
root = Path('.').resolve()
data = json.loads(Path(sys.argv[1]).read_text())
for x in data:
    rel = str(Path(x['filename']).resolve().relative_to(root))
    msg = x.get('message') or ''
    # 契约字段优先：message（结构化诊断）；不依赖非契约旁文
    sym = msg.split('`')[1] if '`' in msg else msg
    loc = x['location']
    print(f"{rel}:{loc['row']}:{loc['column']}\t{sym}")
print('COUNT', len(data), file=sys.stderr)
PY
```

764 修前 COUNT **82**；修后／本轮 COUNT **18**（全部 KEEP，见 F401 成员表）。

### B. ExceptionGroup／web_app F821（必须带 py313）

```bash
set -euo pipefail
uv tool run --from ruff==0.11.2 ruff check \
  --target-version py313 --select F401,F821 --ignore-noqa web_app.py
# 实际（764 原卷 /tmp/1891-fullclass.1UvSWC/logs/web_app-py313-f401-f821.txt）：All checks passed!

uv tool run --from ruff==0.11.2 ruff check \
  --select F401,F821 --ignore-noqa web_app.py
# 实际（同根 web_app-default-f401-f821.txt）：3× F821 ExceptionGroup
# （默认 target <3.11）；漏 --target-version py313 才会红——非源码缺陷，勿加兼容 import
```

### C. 嵌套 FunctionDef 孤儿（Name-only；**不是** Class methods）

**范围声明（诚实）**：本脚本只枚举函数体内嵌套的 `FunctionDef|AsyncFunctionDef`，用包围作用域 `Name(Load)` 判消费者；遇嵌套 `ClassDef` **直接跳过**。因此 **不覆盖** Class／嵌套 Class 的 methods（那些走 Attribute／Import／字符串，见下节 D）。`NESTED_FN_ORPHANS=0` ≠ methods 已净。扫描跳过 `docs/raw/`（冻结仅 P0 解析）；**不得**把非 raw 的 345 写成 `PARSED_PYTHON` 全仓。

```bash
set -euo pipefail
$PY - <<'PY' | tee "$TMPROOT/logs/nested-fn-orphans.json"
import ast, json, subprocess, sys
from pathlib import Path
files = [f for f in subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
         if not f.startswith('docs/raw/')]
orphans = []
for rel in files:
    tree = ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)
    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            self._scan(node); self.generic_visit(node)
        def visit_AsyncFunctionDef(self, node):
            self._scan(node); self.generic_visit(node)
        def _scan(self, node):
            for st in node.body:
                self._stmt(st, node, rel)
        def _stmt(self, st, enc, rel):
            if isinstance(st, ast.ClassDef):
                return  # Class methods OUT OF SCOPE — 见 D
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own = set(range(st.lineno, getattr(st, 'end_lineno', st.lineno) + 1))
                refs = [n for n in ast.walk(enc)
                        if isinstance(n, ast.Name) and n.id == st.name
                        and isinstance(n.ctx, ast.Load) and n.lineno not in own]
                if not refs:
                    orphans.append(f'{rel}:{st.lineno}:{enc.name}.{st.name}')
                return
            for attr in ('body', 'orelse', 'finalbody'):
                for st2 in getattr(st, attr, []) or []:
                    self._stmt(st2, enc, rel)
            for h in getattr(st, 'handlers', []) or []:
                for st2 in h.body:
                    self._stmt(st2, enc, rel)
    V().visit(tree)
json.dump({
    'scope': 'nested FunctionDef Name-only; Class methods excluded; docs/raw skipped',
    'scan_files': len(files),
    'NESTED_FN_ORPHANS': len(orphans),
    'orphans': orphans,
}, sys.stdout, ensure_ascii=False, indent=2)
print()
PY
```

实际：`NESTED_FN_ORPHANS 0`。样本：`_FakeSession._merge_…`／pihong `_gen` 已不存在。

### D. 全仓 Class 方法零静态（含函数内嵌套 Class；本轮命令真源）

**消费者语义（修正）**：仓内对方法名的 **Attribute ∨ Import/ImportFrom 绑定 ∨ 标识符字符串（含 getattr 常量）**——**任一**真实命中即算有消费；**零候选＝三者皆无**。方法体自身行号范围（含 `super().同名`）一律排除。同名 `Name(Load)` 形参／局部变量 **不自动算 caller**（仅诊断，不入消费判定）。

**病史（不得抹）**：

| 口径 | 修前零静态 | 构成 | 说明 |
| --- | --- | --- | --- |
| 旧误计（漏排除 `super().同名` 自引用） | 23 | 2 DELETE + 21 KEEP | 把仅方法体内 super 自引用当成外部消费，漏计 2 个协议 KEEP |
| **正确：排除 self 后** | **25** | **2 DELETE + 23 KEEP** | 本轮真源；2＝`AffairStore.origin_refs`／`ValidatedBatch.by_key`（已在 `2f0c1e393` 删） |
| 修后（defs gone） | 23 | 0 DELETE + 23 KEEP | 见 `1891-1899-class-methods-zero.tsv`；机制 label **由人读表解释**，命令只出候选 |

#### D1. 自包含 AST 命令（stdio JSON；不依赖 /tmp 种子）

```bash
set -euo pipefail
$PY - <<'PY' | tee "$TMPROOT/logs/class-methods-zero-static.json"
import ast, json, subprocess, sys
from pathlib import Path

files = subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
trees = {}
fail = []
for rel in files:
    try:
        trees[rel] = ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)
    except Exception as e:
        fail.append({'file': rel, 'error': f'{type(e).__name__}: {e}'})
if fail:
    json.dump({'PARSE_FAIL': fail}, sys.stdout, ensure_ascii=False, indent=2)
    raise SystemExit('ast.parse failed')

methods = []

class Collector(ast.NodeVisitor):
    """递归 Class 体方法；qualified 含函数内嵌套 Class 路径。"""
    def __init__(self, rel, mod):
        self.rel, self.mod, self.stack = rel, mod, []

    def _qual(self, name):
        return '.'.join([self.mod] + [n for _, n in self.stack] + [name])

    def visit_ClassDef(self, node):
        self.stack.append(('class', node.name))
        for st in node.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append({
                    'qualified': self._qual(st.name),
                    'rel': self.rel,
                    'lineno': st.lineno,
                    'end_lineno': getattr(st, 'end_lineno', st.lineno),
                    'name': st.name,
                    'class': node.name,
                })
                self._visit_fn_for_nested_class(st)
            elif isinstance(st, ast.ClassDef):
                self.visit_ClassDef(st)
        self.stack.pop()

    def _visit_fn_for_nested_class(self, node):
        self.stack.append(('fn', node.name))
        for st in node.body:
            self._stmt(st)
        self.stack.pop()

    def _stmt(self, st):
        if isinstance(st, ast.ClassDef):
            self.visit_ClassDef(st)
            return
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._visit_fn_for_nested_class(st)
            return
        for attr in ('body', 'orelse', 'finalbody'):
            for st2 in getattr(st, attr, []) or []:
                self._stmt(st2)
        for h in getattr(st, 'handlers', []) or []:
            for st2 in h.body:
                self._stmt(st2)

    def visit_FunctionDef(self, node):
        self._visit_fn_for_nested_class(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_fn_for_nested_class(node)

for rel, tree in trees.items():
    mod = rel[:-3].replace('/', '.') if rel.endswith('.py') else rel
    if mod.endswith('.__init__'):
        mod = mod[: -len('.__init__')]
    Collector(rel, mod).visit(tree)

attr_hits, import_hits, string_hits, name_hits = {}, {}, {}, {}
for rel, tree in trees.items():
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.attr, str):
            attr_hits.setdefault(n.attr, []).append((rel, getattr(n, 'lineno', 0)))
        elif isinstance(n, ast.Import):
            for a in n.names:
                bind = a.asname or a.name.split('.')[-1]
                import_hits.setdefault(bind, []).append((rel, getattr(n, 'lineno', 0)))
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                bind = a.asname or a.name
                import_hits.setdefault(bind, []).append((rel, getattr(n, 'lineno', 0)))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            string_hits.setdefault(n.value, []).append((rel, getattr(n, 'lineno', 0)))
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            name_hits.setdefault(n.id, []).append((rel, getattr(n, 'lineno', 0)))

def outside(hits, rel, lo, hi):
    return [(r, ln) for r, ln in hits if not (r == rel and lo <= ln <= hi)]

zeros = []
for m in methods:
    name, rel, lo, hi = m['name'], m['rel'], m['lineno'], m['end_lineno']
    a = outside(attr_hits.get(name, []), rel, lo, hi)
    i = outside(import_hits.get(name, []), rel, lo, hi)
    s = outside(string_hits.get(name, []), rel, lo, hi)
    n = outside(name_hits.get(name, []), rel, lo, hi)  # 诊断 only；不算消费
    # OR：任一真实消费即可；零＝Attribute/Import/string 三者皆无
    if not (a or i or s):
        zeros.append({
            'qualified': m['qualified'],
            'rel': rel,
            'lineno': lo,
            'name': name,
            'class': m['class'],
            'attr_out': len(a),
            'import_out': len(i),
            'string_out': len(s),
            'name_out_diag_not_consumer': len(n),
        })

json.dump({
    'TRACKED_PY': len(files),
    'PARSED_PYTHON': len(trees),
    'METHOD_DEFS': len(methods),
    'consumer_rule': 'Attribute OR Import OR string; Name(Load) not auto-caller; exclude own lineno range',
    'ZERO_STATIC_COUNT': len(zeros),
    'ZERO_STATIC': zeros,
}, sys.stdout, ensure_ascii=False, indent=2)
print()
PY
# 修后实际：TRACKED_PY=351 PARSED_PYTHON=351 METHOD_DEFS≈1105 ZERO_STATIC_COUNT=23
# 机制 label 不由命令输出——人读候选表后写入 tsv／下表
```

#### 修前 DELETE（已在 `2f0c1e393` 删；无失效专属支持物）

| # | qualified | 依据 |
| --- | --- | --- |
| 1 | `ming_sim.entities.affair.store.AffairStore.origin_refs` | 全仓无 `.origin_refs` Attribute；`breach_plea` 的 `origin_refs` 仅为形参／局部（`_commitment_origin_refs`），非本方法消费者；生产 `origin_ref` 单数路径保留 |
| 2 | `ming_sim.rescript_actions.ValidatedBatch.by_key` | 全仓无 `.by_key(`；他处 `desk_by_key`／`revise_by_key` 等为局部 dict，非本方法 |

二者无独立失效支持物（`origin_ref`／`dossiers`／`items` 仍有他消费者）。**无新残余，本轮不施工。**

#### KEEP ZERO_STATIC23（机制由人读表；不得机械零删）

完整 qualified 候选见附件 `1891-1899-class-methods-zero.tsv`（含函数内嵌套 Class 路径）。摘要机制桶：

| 机制 | 例 |
| --- | --- |
| `io_protocol` | `launcher._NullStream.isatty` |
| `llm_sdk_protocol` | `CliChat.ainvoke`／`ainvoke_stream`／`aresponse_stream` |
| `language_protocol_dunder` | `__enter__`／`__exit__`／`__post_init__`／`__getattr__`／`__getattribute__` |
| `pytest_test_method` | `tests.test_commitment_display_348.Test*…` |

### E. 失效守面（生产 + 现役 docs，排除 raw／reports 病史）

```bash
set -euo pipefail
rg -n '_require_active_minister' ming_sim web_app.py docs \
  --glob '!docs/raw/**' --glob '!docs/reports/**' || true
# 实际：无命中
```

### F. CHOICE helper-only 核（非入口变异）+ 全仓 `terminal_reason` 机械清单

#### F1. helper 字面／runtime（非全仓）

```bash
set -euo pipefail
$PY - <<'PY' | tee "$TMPROOT/logs/choice-helper.json"
import ast, json, sys
from pathlib import Path
from ming_sim.rescript_actions import canonical_choice, _choices_equal
src = Path('ming_sim/rescript_actions.py').read_text(encoding='utf-8')
tree = ast.parse(src)
keys = set()
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == 'canonical_choice':
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                keys.add(n.value)
a = {'decision_key': 'rescript_draft:1:0', 'action': 'midzhi', 'label': 'x', 'terminal_reason': '已准'}
b = {'decision_key': 'rescript_draft:1:0', 'action': 'midzhi', 'label': 'x'}
json.dump({
    'canonical_choice_literal_has_terminal_reason': 'terminal_reason' in keys,
    'runtime_canonical_has_terminal_reason': 'terminal_reason' in canonical_choice(a),
    'choices_equal_helper': _choices_equal(a, b),
}, sys.stdout, ensure_ascii=False, indent=2)
print()
PY
```

实际：字面量与 runtime 均无 `terminal_reason`；helper equality True。未碰 `submit_rescript_decision`，未加永久测试。

#### F2. 全仓 `terminal_reason` 字段／标识机械出现（来源消费分类）

不只扫 `canonical_choice` 字面——对 **全部 gittracked `*.py`** 做 AST 节点级清单，并按来源桶分类（事件账 KEEP vs choice 接收 DELETE）：

```bash
set -euo pipefail
$PY - <<'PY' | tee "$TMPROOT/logs/terminal-reason-repo.json"
import ast, json, subprocess, sys
from collections import Counter
from pathlib import Path

TERM = 'terminal_reason'
CHOICE_DELETE_FILES = {
    # 旧 choice 接收键所在面；键已删后此处应无 TERM 节点
    'ming_sim/rescript_actions.py',
}
EVENT_LEDGER_KEEP_PREFIXES = (
    'ming_sim/db.py', 'ming_sim/issues.py', 'ming_sim/models.py',
    'ming_sim/content.py', 'ming_sim/materials.py', 'ming_sim/decree.py',
    'ming_sim/month_translate.py', 'ming_sim/audience_translate.py',
)

def bucket(rel: str) -> str:
    if rel in CHOICE_DELETE_FILES:
        return 'choice_receive_DELETE_surface'
    if rel.startswith('docs/raw/'):
        return 'docs_raw_frozen'
    if rel.startswith('docs/'):
        return 'docs_history'
    if rel in EVENT_LEDGER_KEEP_PREFIXES or rel.startswith('tests/'):
        return 'event_ledger_KEEP'
    return 'other_review'

files = subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
hits = []
parse_fail = []
for rel in files:
    try:
        tree = ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)
    except Exception as e:
        parse_fail.append({'file': rel, 'error': f'{type(e).__name__}: {e}'})
        continue
    for n in ast.walk(tree):
        kind = None
        if isinstance(n, ast.Attribute) and n.attr == TERM:
            kind = 'Attribute'
        elif isinstance(n, ast.keyword) and n.arg == TERM:
            kind = 'keyword'
        elif isinstance(n, ast.Constant) and n.value == TERM:
            kind = 'Constant_str'
        elif isinstance(n, ast.Name) and n.id == TERM:
            kind = 'Name'
        elif isinstance(n, ast.arg) and n.arg == TERM:
            kind = 'arg'
        if kind:
            hits.append({
                'file': rel,
                'lineno': getattr(n, 'lineno', 0),
                'kind': kind,
                'bucket': bucket(rel),
            })
if parse_fail:
    raise SystemExit(json.dumps({'PARSE_FAIL': parse_fail}, ensure_ascii=False))

by_bucket = Counter(h['bucket'] for h in hits)
by_kind = Counter(h['kind'] for h in hits)
choice_hits = [h for h in hits if h['bucket'] == 'choice_receive_DELETE_surface']
json.dump({
    'TRACKED_PY': len(files),
    'PARSED_PYTHON': len(files) - len(parse_fail),
    'terminal_reason_ast_hits': len(hits),
    'by_bucket': dict(by_bucket),
    'by_kind': dict(by_kind),
    'choice_receive_DELETE_surface_hits': choice_hits,
    'files': sorted({h['file'] for h in hits}),
}, sys.stdout, ensure_ascii=False, indent=2)
print()
PY
# 修后实际（摘要）：choice_receive_DELETE_surface_hits=[]；
# 命中均落 event_ledger_KEEP（db/issues/models/content/… + tests）；
# 与「choice 接收键已删、事件账 terminal_reason 现役」一致
```

## CHOICE-C1

| # | qualified | 处置 | 依据 |
| --- | --- | --- | --- |
| 1 | `ming_sim.rescript_actions.canonical_choice` 接收键 `"terminal_reason"` | DELETE（已在 `d80db9754`） | 旧选项解释者已删；仅残留接收规范化；一键删键表项 |

KEEP：事件账 `terminal_reason` 全链路（F2 桶 `event_ledger_KEEP`；含 `mark_event_triggered`／`event_triggers`／`Event.terminal_reason_labels`）。

## CLEANUP 成员（全类；不白名单）

**86 行 F401+context TSV 不是全类成员表**——漏 d80 最初 13 点名（method／nested／import／失效说明）。下表补齐最初 13；其后为 764 F401 层与 2f0 Class 方法层。全类成员均须显式处置，禁止「未点名＝白名单放过」。

### 最初 13（d80 点名；方法／嵌套／导入／失效说明）

| # | qualified 成员 | 种类 | 处置 | 消费者复核／说明 |
| --- | --- | --- | --- | --- |
| 1 | `tests.test_web_chat_serialization_393._FakeSession._merge_staged_new_secret_order_content` | method | DELETE（d80） | Name/Attribute 全仓 0；非 fixture／协议 |
| 2 | `tests.test_pihong_dossier_1490.test_657_web_http_hitl_lock_boundary_same_gate._gen` | nested | DELETE（d80） | 案内无接线；setprofile 历史 0 调用 |
| 3 | `tests.test_levy_petition_month_chain_1891` → `import math` | import | DELETE（d80） | 文件内无 Name 消费 |
| 4 | 同上 → `from ming_sim.agents import strip_json_fence`（伪保留 noqa） | import | DELETE（d80） | 权威 `ming_sim.assets.strip_json_fence` 仍有他消费 |
| 5 | `tests.test_secret_order_payoff_1504` → `offline_empty_audience_translate` | import | DELETE（d80） | 本文件无 Load；权威 conftest 仍有他案消费 |
| 6 | 同上 → `stub_audience_translate` | import | DELETE（d80） | 同上 |
| 7 | 同上 → `stub_scene_agent` | import | DELETE（d80） | 同上 |
| 8 | `ming_sim.context` → `army_aliases` re-export | import | DELETE（d80） | `from ming_sim.context import …` 反向 0；权威 matching KEEP |
| 9 | `ming_sim.context` → `compact_name` | import | DELETE（d80） | 同上 |
| 10 | `ming_sim.context` → `region_aliases` | import | DELETE（d80） | 同上 |
| 11 | `web_app` → `LLMContractError`（伪保留 noqa） | import | DELETE（d80） | web_app 内 Name Load 0；权威 exceptions 仍被消费 |
| 12 | `ming_sim.models.is_vassal_prince` 文档守面项 `_require_active_minister` | 失效说明 | DELETE 字样（d80） | 生产函数已不存在；改列现役 web／session 面 |
| 13 | `ming_sim.session.GameSession.can_summon` 注释「web _require_active_minister」 | 失效说明 | DELETE 字样（d80） | 改为 `is_vassal_prince`／roster 同口径 |

### F401／context 层（附件 86 行 TSV）

完整处置见 `1891-1899-f401-member-table.tsv`（82 F401 + 4 context）。摘要：

| 桶 | 处置 | 说明 |
| --- | --- | --- |
| docs/raw×4（F401 行；另 P0 解析含 raw×6） | KEEP | 冻结卷宗，仅 parse 不删 |
| launcher `urllib.request` | KEEP | `urllib.request.urlopen` 实耗 |
| `action_materialize` 副作用 import×2 | KEEP | 安装 package catalog |
| `game`／`tracer_client` fixture 导入×11 | KEEP | 非 conftest 模块的 pytest 发现 |
| 其余 F401 | DELETE | 无 Name／fixture／副作用消费者 |
| `context.match_{army,region}_id_from_text` + `_match_*` | DELETE | 无 ImportFrom／Name 消费者；权威留 `ming_sim.matching` |

### Class 方法层（2f0）

| qualified | 处置 | 说明 |
| --- | --- | --- |
| `AffairStore.origin_refs`／`ValidatedBatch.by_key` | DELETE（2f0） | 全仓零 Attribute∨Import∨string；非协议 |
| ZERO_STATIC23 协议／pytest | KEEP | 见 D＋tsv；机制人读 |

### 已结实例死定义（无新残余；不施工）

| qualified | 状态 |
| --- | --- |
| `tests.wait_utils.ObservingLock` | 已删（658）；复扫无新残余 |
| `tests.test_audience_background.ToolExec` | 已删（658）；复扫无新残余 |

## 聚焦测试（完整命令；七 BIN + 新 dirs + no cache）

### 史：d80 轮（113／83）— 原卷 `/tmp/1891-choice-cleanup.x4Z74B/logs/`

```bash
# TMPROOT=/tmp/1891-choice-cleanup.x4Z74B （d80 实测）
export MING_SIM_USER_DATA_DIR="$TMPROOT/user"
mkdir -p "$TMPROOT/user" "$TMPROOT/pytest-core" "$TMPROOT/pytest-support" "$TMPROOT/logs"
$PY -m pytest -p no:cacheprovider -q --tb=short \
  --basetemp="$TMPROOT/pytest-core" \
  tests/test_levy_petition_month_chain_1891.py \
  tests/test_fiscal_levy_abolition_1899.py \
  tests/test_fiscal_levy_effect.py \
  tests/test_rescript_choices_563.py \
  tests/test_cli_play_turn.py \
  tests/test_web_court_visibility.py::test_zongfan_cannot_be_summoned_via_can_summon \
  2>&1 | tee "$TMPROOT/logs/focus-core.log"
# 实际：113 passed in 54.87s

$PY -m pytest -p no:cacheprovider -q --tb=short \
  --basetemp="$TMPROOT/pytest-support" \
  tests/test_web_chat_serialization_393.py \
  tests/test_pihong_dossier_1490.py::test_657_web_http_hitl_lock_boundary_same_gate \
  tests/test_secret_order_payoff_1504.py \
  tests/test_web_court_visibility.py \
  tests/test_qa_s2_copy_prompts_1356_1402.py \
  2>&1 | tee "$TMPROOT/logs/focus-support.log"
# 实际：83 passed in 3.48s
```

### 史：764 轮（250／51）— 原卷 `/tmp/1891-fullclass.1UvSWC/logs/`

```bash
# TMPROOT=/tmp/1891-fullclass.1UvSWC （764 实测）
export MING_SIM_USER_DATA_DIR="$TMPROOT/user"
$PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/basetemp" \
  tests/test_qa_c3_secret_order_path_1357_1376.py \
  tests/test_settle_core.py \
  tests/test_affairs_1831.py \
  tests/test_covert_levy_651.py \
  tests/test_error_pack.py \
  tests/test_state_reload.py \
  tests/test_due_review_621.py \
  tests/test_section4_rejections.py \
  tests/test_faction_leverage_9.py \
  tests/test_audience_restore_505.py \
  tests/test_urge_lever_624.py \
  tests/test_recommendations.py \
  tests/test_executor_routing_721.py \
  tests/test_cli_model_choices.py \
  tests/test_style_temperament_641.py \
  --tb=no -q 2>&1 | tee "$TMPROOT/logs/focus-f401-recount.txt"
# 实际：250 passed in 7.56s

$PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/basetemp3" \
  tests/test_rescript_choices_563.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_pihong_dossier_1490.py::test_657_web_http_hitl_lock_boundary_same_gate \
  tests/test_impeachment_surge_655.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_court_layout_1290.py \
  --tb=line -q 2>&1 | tee "$TMPROOT/logs/focus-adj.txt"
# 实际：51 passed in 2.03s
```

### 史：2f0 轮（38）— Class 方法 2 DELETE 触及

```bash
# TMPROOT=/tmp/1891-class-methods.TbsOIH
export MING_SIM_USER_DATA_DIR="$TMPROOT/user"
$PY -m pytest -p no:cacheprovider -q --tb=short \
  --basetemp="$TMPROOT/pytest" \
  tests/test_affairs_1831.py \
  tests/test_world_materials_1834.py \
  tests/test_audience_translation_1838.py \
  tests/test_rescript_choices_563.py \
  tests/test_pihong_dossier_1490.py::test_657_web_http_hitl_lock_boundary_same_gate \
  2>&1 | tee "$TMPROOT/logs/focus-class-methods.txt"
# 实际：38 passed in 4.38s
```

触及存活文件 ruff：

```bash
uv tool run --from ruff==0.11.2 ruff check --target-version py313 --select F401,F821 \
  ming_sim/entities/affair/store.py ming_sim/rescript_actions.py
# 实际：All checks passed!
```

本轮 docs-only：**不重跑**上述聚焦测试。

## 尾随空格首次红史

764 开工时 `git diff --check 34262577a..HEAD` 首次红（原卷 `/tmp/1891-fullclass.1UvSWC/logs/diff-check-before.txt`）：`docs/reports/1891-1899-choice-cleanup.md` 多行 trailing whitespace（行末全角／ASCII 空格，来自 d80／653 回执）。764 重写回执时去掉；交卷前再跑 `--check` 须无红。

## 漏 py313 错误说明

指派／复跑须带 `--target-version py313`。漏该旗时 ruff 默认 target\<3.11，`web_app.py` 对 `ExceptionGroup` 报 3× F821——**不是**源码缺 import，也不是「旧误报可忽略」；正确处置＝补 py313 target 重跑（见上 B），禁止加兼容 import 伪装通过。

## 修后复扫要点

```
P0 PARSED_PYTHON: 351 (docs_raw_py=6 freeze parse-only; non_raw_py=345 ≠ full-repo claim)
F401 py313 ignore-noqa: COUNT 18 (all KEEP)
NESTED_FN_ORPHANS 0 (Class methods excluded by design)
CLASS_METHODS_ZERO_STATIC post-delete: 23 (all KEEP; D OR-semantics; see tsv)
pre-delete correct (exclude self): 25 = 2 DELETE + 23 KEEP
legacy miscount (missed super self-ref): 23 = 2 + 21
AffairStore.origin_refs / ValidatedBatch.by_key: DEFS_GONE
context.match_army_id_from_text False
context.match_region_id_from_text False
web_app F401,F821 --target-version py313: All checks passed!
CHOICE terminal_reason in canonical_choice: False
CHOICE F2 choice_receive_DELETE_surface_hits: []
F2 hits bucket: event_ledger_KEEP (db/issues/models/… + tests)
_require_active_minister (prod+active docs): none
ObservingLock / ToolExec: already gone; no new residual
member table: original-13 + F401-86 + class-method-2 (no whitelist gaps)
```

## 独立复跑事实（主助手；原卷 `/tmp/1891-choice-cleanup-independent.thcaU3/`）

主助手独立已复跑报告 D／C／F1 并聚焦最终代码；本段只钉原卷实测，不改断言口径。

| 件 | 原卷 | 实测 |
| --- | --- | --- |
| D methods | `methods.py`／`methods.log` | TRACKED_PY／PARSED **351**；METHOD_DEFS **1105**；ZERO_STATIC_COUNT **23** |
| C nested | `nested.py`／`nested.log` | scan_files **345**（非 raw）；NESTED_FN_ORPHANS **0** |
| F1 choice | `choice.py`／`choice.log` | helper canonical；`choices_equal_helper` **True**；canonical／runtime `terminal_reason` 皆 **false**（**非**真入口变异证明） |
| 选择器 | `command.txt` | **23** 选择器＝764＋2f0 去重聚焦面 |
| 聚焦测 | `focus.log` | 七 BIN＝false；`user`／`basetemp`＝`$TMPROOT/{user,pytest}`；`PYTHONDONTWRITEBYTECODE=1`；`-p no:cacheprovider`；**317 passed in 11.25s**（墙钟 **11.833s**） |

## lint 红史 → fixture 标记修正（本轮）

ACMR 真跑（**无** `--ignore-noqa`；`34262577a..HEAD` ACMR `*.py`）：

```bash
UV_TOOL_DIR=/tmp/1891-uv-tools UV_CACHE_DIR=/tmp/1891-uv-cache \
  uv tool run --from ruff==0.11.2 ruff check \
  --target-version py313 --select F401,F821 \
  $(git diff --name-only --diff-filter=ACMR 34262577a..HEAD -- '*.py')
```

- **修前红**：`tests/test_rejection_wiring.py:14:45` F401 `tests.section_rejection_helpers.game` imported but unused（与 `rejection_rows` 同 import 行；`game` 为真 pytest fixture，不可删）。
- **修正**：拆行 + 仅 fixture 豁免，对齐 `test_adr0015_per_item_rejection.py`／`section_rejection_helpers` re-export 生态：
  - `from tests.section_rejection_helpers import game  # noqa: F401  # pytest fixture discovery`
  - `from tests.section_rejection_helpers import rejection_rows`（无 noqa）
- **修后**：同上 ACMR 命令 **All checks passed!**
- **A 口径不变**：`F401 --ignore-noqa` 全仓 COUNT **18**（全部 KEEP）＝正确非失败；成员表 `game` KEEP 行号改为 L14（豁免后仍入 18）。

本轮聚焦测（仅受影响文件；事务契约两案亦可）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
$PY -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_rejection_wiring.py::test_rejected_item_lands_in_reports_and_jsonl \
  tests/test_rejection_wiring.py::test_rollback_leaves_no_rows_and_no_jsonl
```

本轮实测原卷：`/tmp/1891-fixture-noqa.b5oxUm/logs/`

- `acmr-f401-f821.txt`：**All checks passed!**
- `f401-ignore-noqa.count.txt`：COUNT **18**（含 `tests/test_rejection_wiring.py:14:45	tests.section_rejection_helpers.game` KEEP）
- `focus-rejection-wiring.txt`：**2 passed in 0.70s**（墙钟 real 1.09s）
## 自查二连

1. **同类**：F401 全表处置保留；嵌套 FunctionDef 孤儿 0（C 范围诚实）；Class 方法修前正确 25＝2 DELETE＋23 KEEP，修后 ZERO_STATIC23；消费语义改为 OR；最初 13 点名回成员表；CHOICE 全仓 `terminal_reason` 清单命令齐；独立 thcaU3 351／1105／ZERO23＋NESTED0＋choice helper＋23 选择器／317 passed 入档；ACMR lint 红＝fixture 缺 noqa，按既有 discovery 标注修，不删 `game`。
2. **引入 bug**：本轮只拆 `game` import＋`# noqa: F401` 与回执／TSV 行号；未改断言／功能／财政／DRY／事件账 `terminal_reason`；未恢复兼容 import；未加永久测试／仓脚本框架；`--ignore-noqa` 18 KEEP 口径未动。

## 交卷

文档：本回执（独立 thcaU3 事实＋lint 红史→fixture noqa）+ `1891-1899-f401-member-table.tsv`（`test_rejection_wiring` `game` L14 KEEP）。
代码：仅 `tests/test_rejection_wiring.py` fixture 发现标注。
forward `ak-roles:` 提交（不 amend／stash／reset／push）。

## 追加：CLEANUP-C1 已删符号——范围撤回 + 框架删简（不变 CHOICE）

**撤回**：把旧 `/tmp/cleanup-c1-audit` 的 **3233 OK** 摘要当成全类闭合（仅摘要；192 unresolved 无成员表）。

**再撤回**：曾入库的 835 行解析器 + AUDIT 壳 + 全员 JSON/TSV/卡片——属超授权「新框架／报告生成物」，已 **forward 删除**；证据仅在 `/tmp/cleanup-c1-forward-delete.hIkScB`。

本类短回执：**`docs/reports/1891-1899-deleted-symbol-tests.md`**（缺符删项 + 9 nonprod + 6 dynamic + 深解析合并表 + 自包含 AST 命令）。**CHOICE 结论与处置不变**。
