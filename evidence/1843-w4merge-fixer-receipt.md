# #1843 W5 R5 F2：合并 `claude/1812-w4` 修内司回执

## 基线

- 本票分支：`ak-roles/issue-1843-w5-r5-f2`
- 开工 HEAD：`7eb8a1208`（#1843 F2 R9）
- 并入底座：`claude/1812-w4` @ `10e64fbef`（含 #1901/#1838 等已收敛）
- merge-base：`ae4a2a3e6`
- 约束：merge commit；禁 rebase/amend/squash/stash/push/开 PR；不改席位/宿主/Soul/宪法
- 优先：底座已收敛结果 + 本票 F2 退役责任（旧结算/simulator 支持树不复活；措辞锁不恢复）

## Advisor 预检（动手前）

- 工作树干净；冲突清单与 fix-packet 一致
- 无待决产品设计：逐冲突可按「F2 退役 vs 底座 #1901 迁出/去措辞锁」归类
- 阻断项：无（未猜新行为）

## 逐文件处置

| 文件 | 来源冲突 | 处置 | 理由 |
| --- | --- | --- | --- |
| `ming_sim/agents.py` | import | 保留 `asdict/is_dataclass`；不保留未用 `Callable` | 底座 #1901 dump JSONL 现役；F2 已退役 stream 用 `Callable` |
| `ming_sim/decree.py` | issues import | 仅 `apply_historical_fiscal_rates` | 底座清死导入；符号已迁 `situation_drift` 等，decree 体无引用 |
| `ming_sim/fiscal_fact_brief.py` | modify/delete | **删除**（ours） | F2 退役旧 simulator 财政盘面投影；底座仅改 import 路径，无生产消费者 |
| `tests/test_army_card_status_1501.py` | content | `army_roster`；去「欠饷严重」措辞锁；`army_needed`→`army_pay` | F2 退役 `army_detail`；底座去措辞锁；#1901 军饷属主 |
| `tests/test_army_display_173.py` | content | 取底座 payload 键契约侧 | 去 roster/report 措辞锁；保留 `army_pay.army_needed` |
| `tests/test_army_firearms.py` | content | 删 `test_army_public_exits_*` | 底座 J3 删形状/措辞测；且依赖已退役 `army_detail` |
| `tests/test_mutiny_third_strike_318.py` | content | 底座 `_configure(db)` substrate-only；**不**恢复 `_simulator_*`；不恢复源码形状 production 测 | F2 退役 simulator 助手；#1901 删源码形状测 |
| `tests/test_power_section_rejections.py` | content | **不**恢复 `format_power_changes` 测 | F2 已删 formatter |
| `tests/test_section4_rejections.py` | content | **不**恢复 `format_region/army_changes` 测 | 同上 |
| `tests/test_secret_order_payoff_1504.py` | content | 保留底座 `decide_secret_order_settlement`/seed_guilt/合同测；**不**导入 `build_secret_covert_effect_briefs` | F2 R5 退役 briefs；底座单元契约现役 |
| `tests/test_llm_channel_config.py` | content | 删 SSOT 源码形状测；保留 `create_rescript_revise_agent` 头表行为测 | 底座 J3；F2 退役 draft agent |
| `tests/test_rescript_draft_656.py` | content | **整文件取 HEAD（F2）** | 底座仍含 `generate_rescript_draft` 树，不得复活 |
| `tests/test_pihong_dossier_1490.py` | content | S10 取 HEAD（`normalize_rescript_layer_a_option`） | 底座侧走已退役 `generate_rescript_draft` |
| `tests/test_pay_order_override_653.py` | content | HEAD（无 fact_brief）；hub golden 改查 `army_pay`；不恢复 brief/turn_region_summary 测 | F2 退役 brief/summary；#1901 军饷迁出 |
| `tests/test_fiscal_substrate_bridge.py` | content | HEAD + 端口座两则现役测；`army_needed`/`army_pay_morale_delta`→`army_pay`；删 legacy_engine 与 `turn_army_summary` 测 | F2 退役 summary；底座去 legacy 单值路；保留影子/预算现役断言 |
| `tests/test_qa_e1_numeric_presentation.py` | content | 底座反散文结构 + HEAD #1471 工程词不泄漏 | 不恢复浮点/万两措辞锁 |

## 退役/措辞锁扫描（解决后）

生产与 tests 中未复活：`fiscal_fact_brief`、`build_secret_covert_effect_briefs`、`create_rescript_draft_agent`/`generate_rescript_draft`、`run_agent_stream_text`、`GameDB.army_detail`、`pending_promulgation_verdicts`、`_simulator_army_dicts`、`format_power/region_changes`、`turn_region/army_summary`。

## 聚焦测试

七旗（同前缀，未真调模型）：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false
export MING_SIM_CODEX_BIN=/usr/bin/false
export MING_SIM_CLAUDE_BIN=/usr/bin/false
export MING_SIM_CURSOR_BIN=/usr/bin/false
export MING_SIM_KIMI_BIN=/usr/bin/false
export MING_SIM_GROK_BIN=/usr/bin/false
export MING_SIM_PI_BIN=/usr/bin/false
```

解释器：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`

命令：上表 13 个冲突涉及测试文件，`-q --tb=line`。

结果（见 `evidence/1843-w4merge-fixer-pytest.log`）：**542 passed, 2 skipped**；EXIT 0。非全量。

## Advisor 终检

- 合并冲突已全部 `git add`；无未合并路径
- 未 push / 未开 PR / 未 stash / 未改席位配置
- 无新增产品行为；仅合并接缝与 import 属主改径
- 剩余问题：无阻断。家族收尾全量 suite 不在本派工范围

## 移交

请以本合并提交交复审；证据本文件 + pytest log。
