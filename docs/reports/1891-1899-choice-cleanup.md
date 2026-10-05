# #1891/#1899 CHOICE-C1 + CLEANUP 全层复核回执

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。
本轮开工 HEAD：`653b83d47c0cfb776fecdeb6640300aaf31de008`。
法源方向：CHOICE 退役选项契约残留；CLEANUP 无消费者冗余绑定（含同形测试导入／嵌套／方法／失效守面）。
附件成员表：`docs/reports/1891-1899-f401-member-table.tsv`（82 个 F401 候选逐项 + 4 条 context 孤儿包装）。

## 撤回

1. **入口变异证明**：撤回。现有对照只覆盖 `canonical_choice`／`_choices_equal` helper，不是 `submit_rescript_decision` 真入口。CHOICE 合法动作只有一键删除接收键表项；不为清退新增永久测试。
2. **ExceptionGroup「旧误报／非本轮」**：撤回。指派 target 为 py313；漏 `--target-version py313` 才会 F821。本轮按 py313 重跑，记录实际结果（见下），不恢复 import 兼容，不把错误归旧。

## 环境

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
# ruff 0.11.2: uv tool run --from ruff==0.11.2 ruff
# 本轮日志根（可复跑命令不依赖此路径种子；仅作现场指针）
TMPROOT=/tmp/1891-fullclass.1UvSWC
```

审计为 inline 标准库 `ast` + 现成 ruff；不新造通用扫描框架／永久测试；`ast.parse` 失败直抛。

## 可复跑枚举命令

### A. 全仓 F401（target py313，ignore-noqa）

```bash
uv tool run --from ruff==0.11.2 ruff check \
  --target-version py313 --select F401 --ignore-noqa \
  --output-format json $(git ls-files '*.py') > "$TMPROOT/logs/f401.json"
$PY - <<'PY'
import json, re, sys
from pathlib import Path
root = Path('.').resolve()
data = json.loads(Path(sys.argv[1]).read_text())
for x in data:
    rel = str(Path(x['filename']).resolve().relative_to(root))
    m = re.search(r'`([^`]+)` imported but unused', x['message'])
    sym = m.group(1) if m else x['message']
    loc = x['location']
    print(f"{rel}:{loc['row']}:{loc['column']}\t{sym}")
print('COUNT', len(data), file=sys.stderr)
PY
"$TMPROOT/logs/f401.json"
```

修前 COUNT **82**；修后 COUNT **18**（全部 KEEP，见成员表）。

### B. ExceptionGroup／web_app F821（必须带 py313）

```bash
uv tool run --from ruff==0.11.2 ruff check \
  --target-version py313 --select F401,F821 --ignore-noqa web_app.py
# 实际：All checks passed!

uv tool run --from ruff==0.11.2 ruff check \
  --select F401,F821 --ignore-noqa web_app.py
# 实际：3× F821 ExceptionGroup（默认 target <3.11）；非源码缺陷，勿加兼容 import
```

### C. 递归 defs／methods／嵌套（标准 ast inline）

```bash
$PY - <<'PY'
import ast, subprocess
from pathlib import Path
files = [f for f in subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
         if not f.startswith('docs/raw/')]
for rel in files:
    ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)
print('PARSED_PYTHON', len(files))
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
                return  # 嵌套类方法走 Attribute／协议，不按 Name 误删
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
print('NESTED_FN_ORPHANS', len(orphans))
for x in orphans:
    print(x)
PY
```

实际：`PARSED_PYTHON 345`；`NESTED_FN_ORPHANS 0`。
样本：`_FakeSession._merge_staged_new_secret_order_content` 已不存在；pihong `_gen` 已不存在。嵌套类内 duck-typing 方法（`run`／`__init__` 等）按协议／Attribute 保留，不误计自身方法体 Name。

### D. 失效守面（生产 + 现役 docs，排除 raw／reports 病史）

```bash
rg -n '_require_active_minister' ming_sim web_app.py docs \
  --glob '!docs/raw/**' --glob '!docs/reports/**'
# 实际：无命中
```

`terminal_reason` 在事件账（`mark_event_triggered`／`event_triggers`／`Event.terminal_reason_labels`）为现役 KEEP，与已删 choice 接收键无关。

### E. CHOICE helper-only 核（非入口变异）

```bash
$PY - <<'PY'
import ast
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
print('canonical_choice_literal_has_terminal_reason', 'terminal_reason' in keys)
a = {'decision_key': 'rescript_draft:1:0', 'action': 'midzhi', 'label': 'x', 'terminal_reason': '已准'}
b = {'decision_key': 'rescript_draft:1:0', 'action': 'midzhi', 'label': 'x'}
print('runtime_canonical_has_terminal_reason', 'terminal_reason' in canonical_choice(a))
print('choices_equal_helper', _choices_equal(a, b))
PY
```

实际：字面量与 runtime 均无 `terminal_reason`；helper equality True。未碰 `submit_rescript_decision`，未加永久测试。

## CHOICE-C1

| # | qualified | 处置 | 依据 |
| --- | --- | --- | --- |
| 1 | `ming_sim.rescript_actions.canonical_choice` 接收键 `"terminal_reason"` | DELETE（已在 `d80db9754`） | 旧选项解释者已删；仅残留接收规范化；一键删键表项 |

KEEP：事件账 `terminal_reason` 全链路（见上 D）。

## CLEANUP 成员（全类）

完整 86 行处置表见附件 TSV（82 F401 + 4 context）。摘要：

| 桶 | 处置 | 说明 |
| --- | --- | --- |
| docs/raw×4 | KEEP | 冻结卷宗，不改 |
| launcher `urllib.request` | KEEP | `urllib.request.urlopen` 实耗 |
| `action_materialize` 副作用 import×2 | KEEP | 安装 package catalog |
| `game`／`tracer_client` fixture 导入×11 | KEEP | 非 conftest 模块的 pytest 发现 |
| 其余 F401 | DELETE | 无 Name／fixture／副作用消费者；含 qa_c3／settle_core／affairs1831 等同形 |
| `context.match_{army,region}_id_from_text` + `_match_*` | DELETE | 无 ImportFrom／Name 消费者；权威留 `ming_sim.matching` |
| `error_pack.atomic`／`urge_lever.tlog` | DELETE | 非副作用，纯闲置绑定 |
| FakeSession 死 method／pihong `_gen` | 已净 | 本轮复扫 NESTED_FN_ORPHANS=0 |

不以「早于本轮／外 diff」免责；本轮对 82 候选逐项 AST 复核后落删。

## 修后复扫要点

```
F401 py313 ignore-noqa: COUNT 18 (all KEEP)
PARSED_PYTHON 345
NESTED_FN_ORPHANS 0
context.match_army_id_from_text False
context.match_region_id_from_text False
FakeSession_has__merge False
web_app F401,F821 --target-version py313: All checks passed!
CHOICE terminal_reason in canonical_choice: False
_require_active_minister (prod+active docs): none
```

## 聚焦测试

七 BIN + `MING_SIM_USER_DATA_DIR` + `--basetemp` + `-p no:cacheprovider`；未跑全量。

| 日志 | 选择器 | 结果 |
| --- | --- | --- |
| `$TMPROOT/logs/focus-f401-recount.txt` | qa_c3／settle_core／affairs1831／covert_levy／error_pack／state_reload／due_review／section4／faction_leverage／audience_restore／urge_lever／recommendations／executor_routing／cli_model_choices／style_temperament | **250 passed in 7.56s** |
| `$TMPROOT/logs/focus-adj.txt` | rescript_choices_563／web_chat_serialization／pihong 657 锁窗／impeachment_surge／month_open_snapshot／court_layout | **51 passed in 2.03s** |

## 尾随空格

```bash
git diff --check 34262577a..HEAD
```

本轮重写本回执并去掉历史 trailing whitespace；交卷前再跑 `--check` 须无红。

## 自查二连

1. **同类**：82 F401 全表处置；嵌套／方法同形复扫 0 孤儿；失效守面生产+现役 docs 无退休接缝；CHOICE 仅 helper 证伪并撤回入口变异话术。
2. **引入 bug**：未改财政／DRY／事件账 `terminal_reason`；未恢复兼容 import；权威 matching 保留；fixture／副作用 KEEP。

## 交卷

代码：`ming_sim/context.py`／`error_pack.py`／`urge_lever.py` + scripts×2 + 测试闲置导入清退（见 git show）。
文档：本回执 + `1891-1899-f401-member-table.tsv`。
forward `ak-roles:` 提交（不 amend／stash／reset／push）。
