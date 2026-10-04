# #1835 w5 证据复核回执（C1/C3 三模块 · 可运行 AST 全表）

本轮只交证据复核提交，未 merge、未 push、未开 PR；不宣告关票。不提交终局回执（由驱动 session 汇验）。

## 授权与动因

- 同工作树 `#1835` 最终证据复核（驱动消息正文）
- 全局约束已读：`~/.claude/CLAUDE.md` SHARED_HARD_RULES + 仓内 `CLAUDE.md` / `AGENTS.md`
- 动因：上轮 `disposition-full-table.md` 枚举命令是 **heredoc 注释壳**（不可运行）；跨仓同名表只点名 3 符号，**不足证明**对三模块 98 个顶层/嵌套 def 做了跨仓同名核对；消费者把未解析同名 Attribute 当准确消费者

## 本轮产物（调查脚本，非测试）

| 文件 | 作用 |
|---|---|
| `ast_c1c3_resweep_enum.py` | 可运行调查脚本：单次 AST 索引全仓 FunctionDef/AsyncFunctionDef |
| `enum-run-stdout.txt` | 实跑 stdout |
| `enumeration-resolved.txt` | 98 def：CROSS_DEF + RESOLVED_PROD/TEST + SAME + UNCERTAIN |
| `cross-name-candidates.txt` | 98 条每人完整跨模块同名定义路径 |
| `review-flags.txt` | 零生产 / 转发壳 / 跨名机读摘要 |
| `disposition-full-table.md` | 全表处置（含可运行命令 + 语义核对 + EOF 单换行） |

## 枚举命令（真实执行）

```sh
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
python3 evidence/issue-1835/c1c3-resweep/ast_c1c3_resweep_enum.py \
  2>&1 | tee evidence/issue-1835/c1c3-resweep/enum-run-stdout.txt
```

实跑摘要：`TARGET_DEFS=98 WITH_CROSS=3`；`TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME=0`；`TOPLEVEL_FORWARDERS=0`。

## 跨仓同名（完整 98）

机械结果：仅 3 个名字有跨模块同名定义；其余 95 条在 `cross-name-candidates.txt` 为 `CROSS_DEF (none)`。

| 符号 | 语义核对 | 处置 |
|---|---|---|
| `bind_content` | 各模块私有 GameContent 注入；非平行局势核 | **保留全部** |
| `_ctx` | 各模块读本模块 `_content`；测试夹具同名≠生产 | **保留全部** |
| `_event_outcome_label` | 与 `preflight` **字面同形**，但两侧均有生产消费者 | **保留两侧**（不机械删；记后续 DRY 候选） |

## C1/C3 删简闸

- 真实生产零消费者（resolved_prod=0 且 same_module=0）：**0**
- 单调用转发壳：**0**
- 仅 uncertain Attribute：**0** → 无「不确定却误删」
- 上轮四处删除（`default_situation_shape` / `_commitment_bar_value` / `_situation_terminal_effects` / `_COLLAPSIBLE_KINDS`）复核仍成立
- **本轮无新增生产删码**

## 聚焦测试

强制前缀七 `MING_SIM_*_BIN=/usr/bin/false`。解释器：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`（cwd=本树）。

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

结果写入 `focused.txt`：**421 passed, 1 skipped in 12.72s**；`/usr/bin/time -p` → real 13.30 / user 7.94 / sys 3.10。

## 自查二连

- 同类型：可运行脚本 + 98 全表跨名 + 解析/未解析消费者分列已落盘；EOF 无多余空行；`git diff --check` 过。
- 引入 bug：本轮不改生产代码；聚焦回归确认无回归。

## 禁令遵守

未 stash / amend / rewrite / push / PR；未新增证明测试；不交终局工具。
