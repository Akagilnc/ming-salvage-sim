# #1835 w5 修内司回执（fixer · C1/C3 三模块全类补扫）

本轮只交修理提交，未 merge、未 push、未开 PR；不宣告关票。不提交终局回执（由驱动 session 汇验）。

## 授权与动因

- 任务包路径（驱动给定）：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108ff-575c-70a9-a4e6-3f226f700bcf@fixer/fix-packet.md`（本机开干时该目录尚未落地；按驱动消息正文执行）
- 票面：#1835 / #1812 / #1901；接缝 ADR 0150 / 0154 / 0047 / 0158
- 动因：上轮 advisor-rescan 回执写「issues 旧核 AST 无 def/reexport」——谓词仍点名旧符号样本，**未**对 `situation_drift.py` / `displaced_population.py` / `issues.py` 全部顶层与嵌套 def 做同名跨仓消费者全表，漏掉：
  1. `situation_drift._commitment_bar_value`（C1 同形重复零调用）
  2. `default_situation_shape`（C3 零消费者）
  3. `issues._situation_terminal_effects`（C1/C3 单调用转接壳）

## 先前收窄结论纠正

| 上轮表述 | 事实 |
|---|---|
| 「issues inertia/levy 旧核与 re-export；本轮 AST 无 def/reexport」 | 对点名旧核符号为真，但**不等于**三模块全文已清；同形死副本与转接壳仍在 |
| 「situation_drift / displaced_population 保留为 #1901 接缝」 | 模块接线应留，但模块内零消费者/同形重复/转接壳必须整类扫净 |

## 枚举命令（真实执行，未收窄为点名样本）

```sh
python3 <<'PY'
# AST walk FunctionDef/AsyncFunctionDef (top-level + nested) in:
#   ming_sim/situation_drift.py
#   ming_sim/displaced_population.py
#   ming_sim/issues.py
# Consumers: Name / Attribute Load + ImportFrom across ming_sim + tests + web_app.py
# Plus module-level KINDS / ALLCAPS / _CONST assigns in the three files
# Plus cross-repo same-name for _commitment_bar_value vs commitment_display
PY
```

产物：

- 修前原始：`evidence/issue-1835/c1c3-resweep/enumeration-raw.txt`
- 修后原始：`evidence/issue-1835/c1c3-resweep/enumeration-post.txt`（DEFS=98，CONSTS=26，零引用顶层残留=0）
- 全表处置：`evidence/issue-1835/c1c3-resweep/disposition-full-table.md`

## 本轮删除

| 路径 | 成员 | 分类 | 处置 |
|---|---|---|---|
| `ming_sim/situation_drift.py` | `default_situation_shape` | C3 零消费者 | **已删**；开局形状真源=`issues.event_to_issue` 内联 kind 分支 |
| `ming_sim/situation_drift.py` | `_commitment_bar_value` | C1 同形重复零调用 | **已删**；真源/唯一调用=`commitment_display._commitment_bar_value` |
| `ming_sim/issues.py` | `_situation_terminal_effects` | C1/C3 转接壳 | **已删**；`event_to_issue` 直接 `from ming_sim.situation_drift import situation_terminal_effects`（lazy，避循环 import；不新增桥函数） |
| `ming_sim/issues.py` | `_COLLAPSIBLE_KINDS` | C3 零引用常量 | **已删**（原壳附属）；真源=`COLLAPSIBLE_SITUATION_KINDS` |

未新增任何兼容桥 / re-export / 转发壳。

## 注释与空白

| 文件 | 处置 |
|---|---|
| `ming_sim/entities/affair/store.py` | docstring 去掉退役 `declare_closed` 词面 |
| `ming_sim/materials.py` | 可见事务 docstring 去掉退役 `declare_closed` 词面 |
| `ming_sim/constants.py` | `COURT_BREAK_COMMANDS` 注释去掉「今日且到此」退役叙事 |
| `ming_sim/settlement/registry.py` | EOF 多余空行收成单换行 |
| `evidence/issue-1835/w5-fixer-report.md` | 行尾空白 6 处清除 |

## 聚焦测试

强制前缀：

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q --tb=line \
  tests/test_declaration_dispatch_1835.py tests/test_affairs_1831.py \
  tests/test_person_delta_adapter.py tests/test_rejection_wiring.py \
  tests/test_month_chain_1847.py tests/test_issue_entities.py \
  tests/test_audience_translate_1837.py tests/test_material_directory_1830.py \
  tests/test_population_transfers_649.py tests/test_commitment_backlash_626.py \
  tests/test_section4_rejections.py tests/test_decree_commitment_settlement_229.py \
  tests/test_style_temperament_641.py tests/test_effect_origin_558.py \
  tests/test_deformation_dual_rail_622.py tests/test_fiscal_beyond_intent_1260.py \
  tests/test_month_translate_1840.py
```

结果（`focused.txt`）：**421 passed, 1 skipped in 9.96s**；`/usr/bin/time -p` → real 10.43 / user 7.00 / sys 2.79。

解释器：工作树无 `.venv`，用 `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`（cwd=本树）。

## 自查二连

- 同类型：三模块全文 AST 消费者表已落盘；修后顶层零引用=0；无新桥。
- 引入 bug：聚焦含 commitment / month_chain / affairs / materials 相关案，全绿。

## 禁令遵守

未 stash / amend / rewrite / push / PR；未改宪法配置；自建物仅本工作树 `evidence/issue-1835/c1c3-resweep/` 与系统临时枚举脚本（无持久 `/tmp` 残留依赖）。
