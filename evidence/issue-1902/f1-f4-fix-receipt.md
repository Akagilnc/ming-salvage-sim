# #1902 修内司 F1–F4 回执（纠举补扫·清扫入库扫描器轮）

- 分支：`ak-roles/1902-f1-f4-fix`
- 上一提交：`0f87eb495`（误把 `scan_*.py` + ~4 万行 JSON 永久入库；分类表套话 retain）
- 本轮底座判词：`02-1902-judge-94f5289f1.json` payload F1–F4（`status=continue`）
- **纠正**：删除本轮自建 `evidence/issue-1902/tmp-scans-1902-round/` 与冗余 `f1-f4-classification-table.json`（有清理授权）；扫描器只活在 `/tmp`；完整枚举命令见下
- **禁止口径已废**：「非本轮 F3 点名失效/重复内部类」——分类表已按全定义重判
- 官方先行：
  - [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
  - [Python Errors and Exceptions](https://docs.python.org/3/tutorial/errors.html)
  - ADR 0005：宽吞旁路必须 log，不得静默

测试前缀（每条必带）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

分类证据（精简）：`evidence/issue-1902/f1-f4-classification-table.md`  
**无**永久扫描器、**无** classification-table.json 大包。

---

## 枚举命令（完整可执行；输出只进 /tmp）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-f1f4-round2
mkdir -p "$TMP"

# 临时脚本（勿 git add）：可从本回执重建，或复用上轮已删内容的 git show
# git show 0f87eb495:evidence/issue-1902/tmp-scans-1902-round/scan_f1_except.py > $TMP/scan_f1_except.py
# …同理 scan_f1_post_except / scan_f2_config / scan_f3_tests / scan_f4_forward

# 本轮综合枚举（成员级摘要，不入库）
python3 $TMP/enum_all.py "$ROOT" | tee $TMP/enum_all.out

# 语义复读焦点（手工 + explore）：
# F1：cli_backend 抽取/投影/关联确认；month_chain secret supply；token_stats
# F2：web_app.api_menu_status vs llm_config_from_runtime；表单槽 vs 生效值
# F3：git ls-files tests web/src/**/*.test.* → 逐函数/逐 it 语义（非仅子串 flags）
# F4：AST 单语句 Return(Call) 后再逐项语义（禁「资源适配」套话）
```

实测摘要（本轮）：

| 项 | 结果 |
|---|---|
| 清理 | `tmp-scans-1902-round/` + `f1-f4-classification-table.json` 已删出工作树 |
| F3 dead_helper 扫描（/tmp，有假阳性：pytest fixture） | 仅处置**确认零引用**者 |
| F4 AST 单行候选 | 67 条启发式 → 语义后删 2（别名+死方法）；其余保留写清理由 |
| 完成范围 | **未**凭候选数量称结清；F3 对话全文 pin（scroll/lens）诚实未整片清 |

---

## F1

### 本轮代码

- `project_draft_extract_to_directive_payload`：去掉 `ValueError→ordinary` 伪造
- `confirm_dossier_links`：失败 re-raise；非法产物 raise（不洗 `[]`）
- `_extract_secret_order`：确认失败 → `extract_failed` + reason
- `month_chain` 非 dict supply → `secret_orders_supply_invalid` + `_abort_month_call`
- `token_stats` 装补丁 import 失败 → `tlog`
- 补 `from ming_sim.constants import DOSSIER_LINK_TYPES`（确认路径本就引用）

### 探针

```text
MUTATED_CLASSIFY_CURRENT: raised ValueError: mutated_classify
OLD_WASH: returned {..., '_washed': True}
CONFIRM: raised RuntimeError: mutated_confirm_fail
normalize_ok True
```

### 保留（非「有日志」）
首抽映「无」、enrich 空效果、breach 逐项、TicketCancelled——公开契约见分类表。

---

## F2

菜单生效值走 `llm_config_from_runtime`（上轮）；本轮复读：

```text
MENU_USES_CORE True
MENU_NO_PARALLEL_EFFECTIVE True
```

分槽原样强度仅表单。未见第二套生效规则需再改。

---

## F3

### 本轮

- 删/改内部能力集合锁：`test_cli_backend` / `test_cli_model_choices` / `cliRunners.test.ts`
- 删死夹具：`_cli_schedule_pending_noop`；month_loop 无调用月链/COURT_BREAK 夹具（**保留**跨文件共享 `_post_issue_stream` 等）
- 删 materials denunciation 冗余 key 集合锁
- 上轮末判 P3 正向重复 / 错缝 / 精确 reason：维持

### 变异（既有真实入口；七 BIN）

```bash
MING1902_MUT=reason PYTHONPATH=/tmp/ming1902-f1f4-round2/mut_plugin:$PYTHONPATH \
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest -q -p no:cacheprovider -p corrupt_contracts \
  --basetemp=/tmp/ming1902-f1f4-round2/mut-reason3 \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it
# → 1 failed；assert reason == … 得到 CORRUPTED；ELAPSED≈1s

# 恢复：
…同七 BIN… python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-round2/mut-restore3 \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it \
  tests/test_cli_entry_1902.py::test_cli_blank_pick_on_urgent_reaches_core_hold \
  tests/test_cli_backend.py::test_public_cli_support_restores_existing_runners \
  tests/test_llm_channel_config.py::test_cli_supports_reasoning_strength_matrix \
  tests/test_web_llm_runtime_config.py::test_1271_three_endpoints_grok_reasoning_supported_and_capability_list
# → 14 passed in 0.88s
```

### 保留重判（非法缩窄已去掉）
army 欠饷 approx 文案 / 内部分账列名隔离 = 呈现契约与 P4 负向，**不是**「非点名故留」。  
scroll/lens 对话全文 pin：**未声称已清**。

---

## F4

- 维持上轮：`_review` / `ensure_open_night…` / `qualitative_character_attribute` 已除
- 本轮：`_transaction_categories` 内联；`GameDB.read_credit_events_as_edges` 删除
- 保留：`GameSession._character`（web_app 消费）、写闸 adapter、`investigation_tip_records` 供料缝——写清语义，不用「资源适配」糊弄

```text
ensure_alias_removed True
qual_attr_removed True
terminal_review_removed True
transaction_categories_alias_removed True
read_credit_edges_removed True
open_night_is_real True
```

---

## 聚焦测试（七 BIN）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-round2/focus-final \
  tests/test_cli_entry_1902.py tests/test_cli_play_turn.py tests/test_web_entry_1902.py \
  tests/test_runtime_llm_config.py tests/test_web_llm_runtime_config.py \
  tests/test_cli_backend.py tests/test_faction_denunciation_627.py \
  tests/test_on_scene_immediate_write_1839.py tests/test_draft_admission_resubmit_1769.py \
  tests/test_llm_channel_config.py tests/test_cli_model_choices.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_month_loop_tracer_1468.py tests/test_world_materials_1834.py
```

```text
302 passed in 8.06s
```

召对触及面：

```bash
…同七 BIN…
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-round2/focus-extra \
  tests/test_audience_night_498.py tests/test_web_audience_night_498.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_manual_directive_locality_1685.py
```

```text
101 passed in 6.80s
```

```bash
cd web && npm test -- --run src/cliRunners.test.ts
# → 3 passed；Duration ~0.63s
```

未跑全量。未改治理文件 / 宿主配置。未 stash/amend/push/PR。未新增平行测试机制。

---

## 完成范围（stdout 须同此诚实）

**已做**：清掉永久扫描器与冗余 JSON；F1 投影伪造/确认洗空/供给非 dict/装补丁静默 + 常量导入；F2 复核共核；F3 同类集合锁与确认死夹具；F4 再删两处纯转发；既有入口 reason 变异红恢复绿；聚焦绿。

**未做 / 不声称结清**：F3 全仓每一条对话全文 pin（scroll/lens 等）未整片改写；F1 全仓每一个 except→return 启发式命中未逐条改生产（压缩保留面见分类表，依据是公开契约/逐项隔离，不是候选计数）。

## 剩余工作
- scroll/lens 呈现散文机械（若下轮单独立法）
- breach_plea 逐项、家族收尾 #1873、全量 suite
