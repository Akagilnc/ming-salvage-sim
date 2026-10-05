# #1891/#1899 CHOICE-C1 + CLEANUP 全层复核回执

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。

## 分轮 HEAD 史（自初开工 `34262577a`；不得抹）

| 轮 | SHA | 内容 |
| --- | --- | --- |
| 初开工 | `34262577af3f6dbf455e64698ee5335dfcd51ddd` | docs residual independent verify |
| d80 | `d80db9754eca88b28d7daefa0ae50228134f36d5` | CHOICE `terminal_reason` 接收键删 + CLEANUP 点名死支持 |
| 653 | `653b83d47c0cfb776fecdeb6640300aaf31de008` | docs pin choice-cleanup 日志指针／SHA |
| 764 | `764f64b06a744eda6b1465fa23570b0251348d54` | 全层 F401／orphan cleanup + 回执（曾重写抹掉 113／83 史；本轮恢复） |
| 本轮 | （本 commit） | Class 方法同形残余 2 DELETE + 回执 A／C／选择器／病史修补 |

法源方向：CHOICE 退役选项契约残留；CLEANUP 无消费者冗余绑定；**本轮用户授权**＝全仓同类 Class 方法／闭包零静态死定义一并清（非 advisor 可选宽口径）。
附件：`docs/reports/1891-1899-f401-member-table.tsv`；`docs/reports/1891-1899-class-methods-zero.tsv`。

## 撤回

1. **入口变异证明**：撤回。现有对照只覆盖 `canonical_choice`／`_choices_equal` helper，不是 `submit_rescript_decision` 真入口。CHOICE 合法动作只有一键删除接收键表项；不为清退新增永久测试。
2. **ExceptionGroup「旧误报／非本轮」**：撤回。指派 target 为 py313；漏 `--target-version py313` 才会 F821。按 py313 重跑记录实际结果，不恢复 import 兼容，不把错误归旧。
3. **「C＝methods 已净」**：撤回。原 C 脚本对嵌套 `ClassDef` 直接 `return`，只扫嵌套 `FunctionDef` 的 `Name(Load)`，**从不扫 Class methods 的 Attribute**；`NESTED_FN_ORPHANS=0` 不得冒称 methods 闭包。

## 环境

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
# ruff 0.11.2: uv tool run --from ruff==0.11.2 ruff
# 目录自包含；uv 两变量与日志根同场创建
TMPROOT=$(mktemp -d /tmp/1891-class-methods.XXXXXX)
mkdir -p "$TMPROOT/logs" "$TMPROOT/user" "$TMPROOT/pytest" \
  "$TMPROOT/uv-tools" "$TMPROOT/uv-cache"
export UV_TOOL_DIR="$TMPROOT/uv-tools" UV_CACHE_DIR="$TMPROOT/uv-cache"
# 本轮实测根（指针；复跑命令自包含不依赖此种子）
# TMPROOT=/tmp/1891-class-methods.TbsOIH
# 史：d80 日志根 /tmp/1891-choice-cleanup.x4Z74B ；764 /tmp/1891-fullclass.1UvSWC
```

审计为 inline 标准库 `ast` + 现成 ruff；不新造通用扫描框架／永久测试；`ast.parse` 失败直抛。

## 可复跑枚举命令

### A. 全仓 F401（target py313，ignore-noqa）

```bash
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
uv tool run --from ruff==0.11.2 ruff check \
  --target-version py313 --select F401,F821 --ignore-noqa web_app.py
# 实际（764 原卷 /tmp/1891-fullclass.1UvSWC/logs/web_app-py313-f401-f821.txt）：All checks passed!

uv tool run --from ruff==0.11.2 ruff check \
  --select F401,F821 --ignore-noqa web_app.py
# 实际（同根 web_app-default-f401-f821.txt）：3× F821 ExceptionGroup
# （默认 target <3.11）；漏 --target-version py313 才会红——非源码缺陷，勿加兼容 import
```

### C. 嵌套 FunctionDef 孤儿（Name-only；**不是** Class methods）

**范围声明（诚实）**：本脚本只枚举函数体内嵌套的 `FunctionDef|AsyncFunctionDef`，用包围作用域 `Name(Load)` 判消费者；遇嵌套 `ClassDef` **直接跳过**。因此 **不覆盖** Class／嵌套 Class 的 methods（那些走 Attribute／协议，见下节 D）。`NESTED_FN_ORPHANS=0` ≠ methods 已净。

```bash
$PY - <<'PY'
import ast, subprocess
from pathlib import Path
files = [f for f in subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
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
print('NESTED_FN_ORPHANS', len(orphans),
      '(scope=nested FunctionDef Name-only; Class methods excluded)')
for x in orphans:
    print(x)
PY
```

实际：`NESTED_FN_ORPHANS 0`。样本：`_FakeSession._merge_…`／pihong `_gen` 已不存在。

### D. 全仓 Class 方法零静态（含嵌套 Class；本轮真源）

判据：所有 `ClassDef`（含函数内嵌套类）体方法；消费者＝仓内 **Attribute ∧ Import ∧ 标识符字符串 ∧ getattr 常量**；`Name(Load)` 若仅为同名形参／局部变量 **不算** caller；方法体自引用 Attribute 排除。

修前顾问独立扫描合格零静态 **23**＝**2 DELETE + 21 KEEP**。本轮用户 scope 明确删除 2 个非协议死定义（无 protocol 保留）。

#### 修前 DELETE（本轮已删；无失效专属支持物）

| # | qualified | 依据 |
| --- | --- | --- |
| 1 | `ming_sim.entities.affair.store.AffairStore.origin_refs` | 全仓无 `.origin_refs` Attribute；`breach_plea` 的 `origin_refs` 仅为形参／局部（`_commitment_origin_refs`），非本方法消费者；生产 `origin_ref` 单数路径保留 |
| 2 | `ming_sim.rescript_actions.ValidatedBatch.by_key` | 全仓无 `.by_key(`；他处 `desk_by_key`／`revise_by_key` 等为局部 dict，非本方法 |

二者无独立失效支持物（`origin_ref`／`dossiers`／`items` 仍有他消费者）。

#### KEEP 21（精确机制；不得机械零删）

| qualified | KEEP 机制 |
| --- | --- |
| `launcher._NullStream.isatty` | **io_protocol**（stdio／uvicorn 着色探测） |
| `ming_sim.cli_backend.CliChat.ainvoke` | **llm_sdk_protocol**（`type: ignore[override]`） |
| `ming_sim.cli_backend.CliChat.ainvoke_stream` | **llm_sdk_protocol** |
| `ming_sim.applier._SuspendableConnection.__enter__`／`__exit__` | **language_protocol_dunder** |
| `ming_sim.decree._PromulgationJudgeSession.__post_init__` | **language_protocol_dunder** |
| `ming_sim.session_write_queue.ClassifiedWriteGate.__enter__`／`__exit__` | **language_protocol_dunder** |
| `ming_sim.session_write_queue.TicketedWriteGate.__enter__`／`__exit__` | **language_protocol_dunder** |
| `web_app._NonBlockingWebWriteGate.__enter__`／`__exit__` | **language_protocol_dunder** |
| `tests.test_event_chain_cascade._TempEvents.__enter__`／`__exit__` | **language_protocol_dunder** |
| `tests.test_new_issues_section_rejections._TempEvents.__enter__`／`__exit__` | **language_protocol_dunder** |
| `tests.test_gazette_author_1862.ObservedFact.__getattr__` | **language_protocol_dunder** |
| `tests.test_qa_1281_issue_audience_case_facts.FailingEventAudienceConnection.__getattr__` | **language_protocol_dunder** |
| `tests.test_commitment_display_348.TestCommitmentTimedBarValue.test_timed_bar_percentage_clamp_and_none_cases` | **pytest_test_method** |
| `tests.test_commitment_display_348.TestTimedBarIntegration.test_bar_tracks_elapsed_via_wall_clock` | **pytest_test_method** |
| `tests.test_commitment_display_348.TestTimedBarIntegration.test_origin_turn_unset_falls_back_to_state_turn` | **pytest_test_method** |

#### 修后复扫补记（排除方法体自引用后）

同口径扫描另见 2 个仅方法体内 `super().同名` 的零外部静态项，**同为协议 KEEP、非死定义**：

| qualified | KEEP 机制 |
| --- | --- |
| `ming_sim.cli_backend.CliChat.aresponse_stream` | **llm_sdk_protocol**（Agno `OpenAIChat.aresponse_stream` override） |
| `tests.test_pihong_dossier_1490.PhaseRaceState.__getattribute__` | **language_protocol_dunder** |

→ 修后零静态表见 `1891-1899-class-methods-zero.tsv`（23 行，全部 KEEP）。无其他非协议残余。

### E. 失效守面（生产 + 现役 docs，排除 raw／reports 病史）

```bash
rg -n '_require_active_minister' ming_sim web_app.py docs \
  --glob '!docs/raw/**' --glob '!docs/reports/**'
# 实际：无命中
```

`terminal_reason` 在事件账（`mark_event_triggered`／`event_triggers`／`Event.terminal_reason_labels`）为现役 KEEP，与已删 choice 接收键无关。

### F. CHOICE helper-only 核（非入口变异）

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

KEEP：事件账 `terminal_reason` 全链路（见上 E）。

## CLEANUP 成员（F401 全类 + Class 方法）

完整 86 行 F401 处置表见附件 TSV（82 F401 + 4 context）。摘要：

| 桶 | 处置 | 说明 |
| --- | --- | --- |
| docs/raw×4 | KEEP | 冻结卷宗，不改 |
| launcher `urllib.request` | KEEP | `urllib.request.urlopen` 实耗 |
| `action_materialize` 副作用 import×2 | KEEP | 安装 package catalog |
| `game`／`tracer_client` fixture 导入×11 | KEEP | 非 conftest 模块的 pytest 发现 |
| 其余 F401 | DELETE | 无 Name／fixture／副作用消费者 |
| `context.match_{army,region}_id_from_text` + `_match_*` | DELETE | 无 ImportFrom／Name 消费者；权威留 `ming_sim.matching` |
| `AffairStore.origin_refs`／`ValidatedBatch.by_key` | DELETE（本轮） | 全仓零 Attribute；非协议 |

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

### 本轮：2 定义触及最小现役契约（不全量）

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

## 尾随空格首次红史

764 开工时 `git diff --check 34262577a..HEAD` 首次红（原卷 `/tmp/1891-fullclass.1UvSWC/logs/diff-check-before.txt`）：`docs/reports/1891-1899-choice-cleanup.md` 多行 trailing whitespace（行末全角／ASCII 空格，来自 d80／653 回执）。764 重写回执时去掉；本轮交卷前再跑 `--check` 须无红。

## 漏 py313 错误说明

指派／复跑须带 `--target-version py313`。漏该旗时 ruff 默认 target\<3.11，`web_app.py` 对 `ExceptionGroup` 报 3× F821——**不是**源码缺 import，也不是「旧误报可忽略」；正确处置＝补 py313 target 重跑（见上 B），禁止加兼容 import 伪装通过。

## 修后复扫要点

```
F401 py313 ignore-noqa: COUNT 18 (all KEEP)
NESTED_FN_ORPHANS 0 (Class methods excluded by design)
CLASS_METHODS_ZERO_STATIC post-delete: 23 (all KEEP; see D + tsv)
AffairStore.origin_refs / ValidatedBatch.by_key: DEFS_GONE
context.match_army_id_from_text False
context.match_region_id_from_text False
web_app F401,F821 --target-version py313: All checks passed!
CHOICE terminal_reason in canonical_choice: False
_require_active_minister (prod+active docs): none
focus-class-methods: 38 passed
touched ruff py313: All checks passed!
```

## 自查二连

1. **同类**：F401 全表处置保留；嵌套 FunctionDef 孤儿 0（范围诚实）；Class 方法同形 2 DELETE + 21 KEEP 协议表齐；无其他非协议零静态残余。
2. **引入 bug**：未改财政／DRY／事件账 `terminal_reason`；未恢复兼容 import；`origin_ref` 单数与 ValidatedBatch 字段仍存；fixture／副作用／SDK／dunder／pytest KEEP。

## 交卷

代码：`ming_sim/entities/affair/store.py`（删 `origin_refs`）；`ming_sim/rescript_actions.py`（删 `ValidatedBatch.by_key`）。
文档：本回执（恢复 d80／653／764 分轮与 113／83／250／51 完整选择器；修正 A heredoc／C 范围；Class 方法成员）+ `1891-1899-class-methods-zero.tsv`。
forward `ak-roles:` 提交（不 amend／stash／reset／push）。
