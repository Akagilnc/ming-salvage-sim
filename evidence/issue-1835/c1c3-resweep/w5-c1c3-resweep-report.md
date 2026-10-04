# #1835 w5 C1 DRY 归一回执（`_event_outcome_label`）

同工作树续作；纠正上轮「双侧有生产消费者 → 保留两侧」——C1 平行路径按错误形状不是零引用，**DRY 有消费者仍须一个权威实现**。不宣告关票；不交终局工具。

## 授权与动因

- 同工作树 `#1835`：`_event_outcome_label` 字面同形须归一
- 全局约束已读：`~/.claude/CLAUDE.md` SHARED_HARD_RULES + 仓内 `CLAUDE.md` / `AGENTS.md`
- 动因：上轮以消费者理由保留重复不成立；须实证语义异同，同则沿既有真源归一

## 语义实证

`issues._event_outcome_label` 与删前 `preflight._event_outcome_label` 函数体 **BYTE_IDENTICAL**（`ast.get_source_segment` 比对 `IDENTICAL True`）。无行为分歧可举例，故不保留第二定义。

## 生产改动

| 动作 | 路径 |
|---|---|
| **保留真源** | `ming_sim/issues.py` `_event_outcome_label` |
| **删副本** | `ming_sim/settlement/preflight.py` 本地 `_event_outcome_label` |
| **改导入** | preflight `_strategic_event_outcome_label_or_error` 与既有 `_preflight_declared_event_groups`（~1254）均 `from ming_sim.issues import _event_outcome_label`（函数内 import，避 issues↔preflight 环） |

未造新模块 / helper / 兼容桥。

## 后扫（可运行 AST 全表）

```sh
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
python3 evidence/issue-1835/c1c3-resweep/ast_c1c3_resweep_enum.py \
  2>&1 | tee evidence/issue-1835/c1c3-resweep/enum-run-stdout.txt
```

实跑摘要：`TARGET_DEFS=98 WITH_CROSS=2`（原 3→2）；`TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME=0`；`TOPLEVEL_FORWARDERS=0`。

跨仓同名剩余：

| 符号 | 语义核对 | 处置 |
|---|---|---|
| `bind_content` | 各模块私有 GameContent 注入；非平行核 | **保留全部** |
| `_ctx` | 各模块读本模块 `_content`；测试夹具同名≠生产 | **保留全部** |

`_event_outcome_label`：`CROSS_DEF (none)`；resolved_prod=6（declaration_dispatch + preflight 两处 ImportFrom/Name）；**保留 issues 真源**。

全表处置见 `disposition-full-table.md`。

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
  /usr/bin/time -p \
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

结果写入 `focused.txt`：**421 passed, 1 skipped in 11.92s**；`/usr/bin/time -p` → real 12.56 / user 8.20 / sys 3.21。

## 自查二连

- 同类型：C1 同形按单一真源归一；跨名全表与后扫已更新；EOF 无多余空行。
- 引入 bug：聚焦回归确认 preflight 改 import 后无回归。

## 禁令遵守

未 stash / amend / rewrite / push / PR；未新增证明测试；不交终局工具。
