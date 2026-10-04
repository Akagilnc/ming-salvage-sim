# #1902 修内司 F1–F4 回执（round3：逐项结清续跑）

- 分支：`ak-roles/1902-f1-f4-fix`
- 上一提交：`138f8b714`（承认 scroll/lens 全文 pin 未清、F1 未逐项语义）
- 本轮底座判词：`02-1902-judge-94f5289f1.json` payload F1–F4（`status=continue`）
- 分类证据：`evidence/issue-1902/f1-f4-classification-table.md`
- **无**永久扫描器、**无** classification-table.json 大包；扫描只活 `/tmp/ming1902-f1f4-round3/`

测试前缀（每条必带）：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 枚举命令（完整可执行；输出只进 /tmp）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-f1f4-round3
mkdir -p "$TMP"

# 启发式摘要（成员计数≠结清；结清靠分类表逐项语义）
python3 - <<'PY' | tee "$TMP/enum_all.out"
# 见本回执同轮写入的 $TMP/enum_summary.json
# F1 except→return/pass；F4 单语句 Return(Call)；F3 测试文件计数
PY

# 语义复读焦点（手工，非路径表冒充）：
# F1：confirm 条目非法；multi invalid_batch；token base_url；enrich _canonical；TPE 导入
# F2：api_menu_status ↔ llm_config_from_runtime
# F3：ministerScrollLens / modals scroll·archive / appDurableWiring / audience_scroll_539
#     + 确认零引用死夹具 + pi argv 来源弱化
# F4：死别名/死查询/validate_delta_shape
```

实测摘要：

| 项 | 结果 |
|---|---|
| F1 探针 | `CONFIRM_MALFORMED_RAISE` / `CONFIRM_BAD_REL_RAISE` / `MULTI_WRONG_COUNT_RAISE` / `MULTI_SOFT_DEGRADE 无` / `TPE_IN_MODULE` |
| F2 探针 | `MENU_CALLS_CORE True` |
| F4 探针 | `primary_alias_gone` / `list_recent_gone` / `validate_delta_gone` |
| 死夹具 | 28 个确认零引用 helper 已删（成员名见分类表/下方） |

### 本轮删除的死夹具成员（28）

`_canned`（advance_without_edict_token）· `_assert_next_accepted` · `_session_double` · `_tool_registry` · `_assert_structured_llm_http` · `_noop_atomic` · `_complete_session` · `_terminal_sse` · `_clear_character_offices` · `_gate_cfg` · `_bind_content` · `_settled_land_by_region` · `_simulator_army_dicts`×2 · `_find_simulator_army` · `_canned_settle` · `_columns` · `_658_session` · `_drive_resolve_directives` · `_bajiu_names` · `_reflux` · `_module_of` · `_stamp_heal_ids` · `_canned_monthly_settlement` · `_army_none_legal_item` · `_assert_ledger_match`

---

## F1

### 代码
- `confirm_dossier_links`：非法条目 / 非法 relation → raise（禁洗 `[]`）
- multi `extract_draft_intent`：LLM soft-fail 与 `invalid_batch` 分离；后者 raise；classify ValueError re-raise
- `token_stats._get_client_base_url`：except → tlog
- `enrich_initiative_effects`：`_canonical` except → `_log`
- `from concurrent.futures import ThreadPoolExecutor`

### 保留依据更正
首抽 LLM→「无」：依据源码 owner 注释（纠错 raise / 首抽吞），**废除**对已失踪 `test_extract_draft_intent_backend_exception_degrades_to_none` 的引用。

---

## F2

菜单生效值走共核；分槽仅表单。未见第二套生效规则。

---

## F3

### 代码/测试
- scroll/lens：`ministerScrollLens` / `modals` / `appDurableWiring` / `test_audience_scroll_539` 对话全文 pin → 结构契约
- 28 死夹具删除
- pi argv 来源弱化收紧为 `"-p" in cmd`
- 保留：来源透传、闸负向、P6 markdown、approx / P4 隔离

### 变异（既有真实入口；七 BIN）

```bash
MING1902_MUT=reason PYTHONPATH=/tmp/ming1902-f1f4-round3/mut_plugin:$PYTHONPATH \
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest -q -p no:cacheprovider -p corrupt_contracts \
  --basetemp=/tmp/ming1902-f1f4-round3/mut-reason \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it
# → 1 failed；reason==CORRUPTED；~1.01s

# 恢复：
…同七 BIN… python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-round3/mut-restore \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it \
  tests/test_cli_entry_1902.py::test_cli_blank_pick_on_urgent_reaches_core_hold \
  tests/test_cli_backend.py::test_public_cli_support_restores_existing_runners \
  tests/test_cli_backend.py::test_run_pi_flags_thinking_and_stdout \
  tests/test_llm_channel_config.py::test_cli_supports_reasoning_strength_matrix \
  tests/test_web_llm_runtime_config.py::test_1271_three_endpoints_grok_reasoning_supported_and_capability_list
# → 15 passed in 0.96s；real 1.43s
```

---

## F4

删：`_primary_source_only_army_pay_container_total`、`list_recent_issue_advances`、`validate_delta_shape`（+ decree 未用 import）。  
保留 façade/供料缝/路由——写清语义，不用「资源适配」。

---

## 聚焦测试（七 BIN）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-round3/focus-final \
  tests/test_cli_entry_1902.py tests/test_cli_play_turn.py tests/test_web_entry_1902.py \
  tests/test_runtime_llm_config.py tests/test_web_llm_runtime_config.py \
  tests/test_cli_backend.py tests/test_faction_denunciation_627.py \
  tests/test_on_scene_immediate_write_1839.py tests/test_draft_admission_resubmit_1769.py \
  tests/test_llm_channel_config.py tests/test_cli_model_choices.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_month_loop_tracer_1468.py tests/test_world_materials_1834.py \
  tests/test_audience_scroll_539.py
```

```text
325 passed in 10.22s
real 10.89s
```

召对触及面：

```bash
…同七 BIN…
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-f1f4-round3/focus-extra \
  tests/test_audience_night_498.py tests/test_web_audience_night_498.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_manual_directive_locality_1685.py
```

```text
101 passed in 7.74s
real 8.27s
```

```bash
cd web && npm test -- --run \
  src/ministerScrollLens.test.ts src/components/modals.test.tsx \
  src/appDurableWiring.test.tsx src/cliRunners.test.ts
# → 128 passed；Duration ~4.10s；real 4.43s
```

未跑全量。未改治理文件 / 宿主配置。未 stash/amend/push/PR。未新增永久扫描/生产护栏/平行测试。

---

## 完成范围（stdout 须同此诚实）

**已做（相对上轮未结项）**：
- F1：抽取缝非法产物/来源伪造/静默旁路逐项审验并修复；保留面写可核依据（非统一套话）
- F2：唯一共核复核
- F3：scroll/lens 对话全文 pin 清扫；确认死夹具；触及面来源弱化收紧；保留来源透传与闸负向
- F4：再删 3 处死转发；语义复扫其余启发式

**合法未结（非本授权阻断）**：
- 家族收尾全量 suite（#1185 / #1873 政策：切片聚焦，全量待合并态）
- 全仓每一个 except→pass 启发式命中的非抽取缝压缩面：已语义未见抽取非法洗，但未改写成「零启发式」——见分类表压缩保留
