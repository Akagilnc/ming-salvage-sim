# #1902 D5-A 第5条：诊断信号断言全仓清退回执

基准工作树：`ak-roles/issue-1902-w5`（未 commit / stash / amend / push / PR）。

判词原文：`evidence/issue-1902/d5-signal-review.json`（完整读取，不仅按点名）。
原派单：`/Users/akagilnc/.ak-roles/books/Ming_LLM/1902/runs/01a10801-ef07-7a2d-8851-ab4324f97e3e@fixer/fix-packet.md`
宪法：仓内 `CLAUDE.md` / `AGENTS.md`；全局 `~/.claude/CLAUDE.md` + `~/.codex/AGENTS.md`（§13：盯文、重复、仅测内部结构的测试应删除）。

## 本轮范围（仅 D5-A 第5条）

以诊断 tlog／stdout／stderr／异常类名／实现信号条数或存在性为契约的断言，以及专用捕获夹具、未使用捕获、静默 tlog monkeypatch。

**不做**：第1–4、6条；D5-B；新造测试／扫描机制／生产护栏；改已结其他类或治理文件。

**保留**：结构化落库结果、真实入口、闸类隔离负向。capsys 仅当 CLI 真实用户原始来源透传且能证明非诊断打印。不以「外部可见」泛化日志例外。

## 根因

上轮回执自述 rg 复扫只覆盖 `test_fiscal_levy_effect.py` 与 `test_db_broad_except_surface.py` 的 tlog，未对全仓测试枚举 caplog／capsys／tlog 捕获；判词点名样本之外同类残留仍在。封驳依据=类别未扫净，不是测试红绿。

## 确切全仓枚举命令（已执行；临时物仅 `/tmp`，不入仓、不造永久扫描机制）

### 1) 测试路径全集

```bash
PRED='(^|/)(tests?/|__tests__/|conftest\.py$|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$|fixtures?/)'
git ls-files | rg -i "$PRED" | sort -u | tee /tmp/d5-signal-1902/enum/universe.txt | wc -l
# → 263
```

### 2) 诊断夹具／捕获宽扫（Python + Web；修前对照 `git grep` HEAD）

```bash
rg -n 'caplog|capsys|capfd' tests web/src --glob '*.{py,ts,tsx,js,jsx}'
rg -n 'readouterr|redirect_stdout|redirect_stderr' tests web/src --glob '*.{py,ts,tsx,js,jsx}'
rg -n 'monkeypatch\.setattr\([^)]*["'\''"](tlog|_tlog|log|print|logger)["'\''"]|(tlog|_tlog)\s*=|logs\.append|_capture_tlog' tests web/src --glob '*.{py,ts,tsx,js,jsx}'
rg -n 'console\.(log|error|warn)|spyOn\(console|vi\.spyOn\(console' web/src --glob '*.{ts,tsx,js,jsx}'
git grep -n -E 'caplog|capsys|capfd|readouterr|redirect_stdout|_capture_tlog|logs\.append|spyOn\(console|vi\.spyOn\(console' HEAD -- tests web/src
git grep -n -E 'monkeypatch\.setattr\([^)]*["'\''"](tlog|_tlog|log|print|logger)["'\''"]' HEAD -- tests web/src
```

### 3) logger mock／call_count／error／exception class 宽扫（不得只收 caplog）

```bash
rg -n 'caplog\.(text|records|messages)|exc_info|assert logs|assert msgs|JSONDecodeError|__class__\.__name__|type\([^\)]*\)\.__name__|assert_called|call_count|logger\.(error|warning|info|exception)|MagicMock|patch\(.*log|mock.*log' tests web/src --glob '*.{py,ts,tsx,js,jsx}'
rg -n 'assert_called|call_count|\.error\(|\.exception\(|\.warning\(|MagicMock|AsyncMock|unittest\.mock|patch\(' tests --glob '*.py' | rg -i 'log|logger|tlog|caplog|exc_info|exception|error'
rg -n '__class__\.__name__|type\(exc\)\.__name__|type\(.*\)\.__name__' tests web/src --glob '*.{py,ts,tsx}'
rg -n 'logger\s*=\s*MagicMock|patch\([^\n]*logger|getLogger|assert_called_with|assert_called_once' tests --glob '*.py'
```

说明：未写入仓内 AST／分类器脚本；候选由上列可复跑命令 + 对命中行实读函数名得到。临时输出曾写 `/tmp/d5-signal-1902/enum/`，交卷前删除。

## 完整候选表（修前命中 → 处置；精确路径 + 函数 + 断言／依据）

修前诊断捕获核心（`git grep` HEAD）+ 宽扫假阳性／保留项一并入表。判词点名五样本全部落入「改／整删」。

### A. 改／整删（诊断信号或死夹具）

| 路径 | 测试函数 | 修前命中（断言／夹具） | 处置 | 依据 |
|---|---|---|---|---|
| `tests/test_rescript_draft_656.py` | `test_validate_items_empty_options_drops_item_keeps_siblings` | `monkeypatch.setattr(..., "tlog", logs.append)`；`assert logs`；`any(title in msg for msg in logs)` | **改** | 删 tlog 诊断信号与专用捕获；保留 siblings 结构化草稿 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_non_list_options_drops_item_keeps_siblings` | 同上（含 `assert any(bad["title"] in msg…)`） | **改** | 同上 |
| `tests/test_override_breach_costs_564.py` | `test_legacy_persisted_reaction_severity_migrates_narrowly_and_idempotently` | `caplog.text`；`assert "decree_dossier_decisions" in warning`；`assert str(malformed_id) in warning`；`assert expected_exc in warning` | **改** | 删异常类名／日志筛选；保留迁移结构化落库与 malformed 原样残留 |
| `tests/test_decree_commitment_creation_136.py` | `test_decree_commitment_same_account_alias_miss_emits_residual_signal` → `…_still_lands` | `capsys.readouterr()`；`assert "徐光启三务公费" in (out+err)` | **改** | 删打印信号；保留异名 fiscal 落库 |
| `tests/test_decree_commitment_creation_136.py` | `test_decree_commitment_unrelated_account_no_residual_signal` | `capsys`；`assert "督江差役" not in (out+err)` | **整删** | 纯诊断信号负向，删后无结构化契约可留 |
| `tests/test_chat_stream_failpaths_393.py` | `test_worker_cleanup_double_failure_emits_original_error_end_and_logs` → 去 `_and_logs` | `caplog.at_level(...)`；`assert any(r.exc_info for r in caplog.records)` | **改** | 删日志 `exc_info` 实现信号；保留 error→end／原 message |
| `tests/test_relation_seed_638.py` | `test_existing_save_is_never_touched_by_seed_import` | `logs=[]`；`monkeypatch.setattr(token_stats, "tlog", logs.append)`（未使用） | **改** | 清退无用夹具与 `token_stats` import；保留流水／摘要不变 |
| `tests/test_decree_dossiers_571.py` | `test_manual_directive_capture_rejects_malformed_roster` | 未使用 `capsys` 参数 | **改** | 清退死参数；保留 ValueError／无写库 |
| `tests/test_cli_entry_1902.py` | `test_save_load_round_trip_through_shared_core` | 未使用 `capsys`／`monkeypatch` 参数 | **改** | 清退死参数；保留存读档结构化 |
| `tests/test_decree_commitment_settlement_229.py` | `test_commitment_progress_contexts_are_structured` | `capsys.readouterr()` 仅 drain、无断言 | **改** | 清退无契约捕获；保留 `inputs` 结构化 |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_incomplete_first_pass_does_not_freeze_zero_share_seed` | `monkeypatch.setattr(issues, "tlog", lambda msg: None)` | **改** | 静默无用夹具清退；保留隔离行为；去多余 `monkeypatch` 参数 |
| `tests/test_llm_channel_config.py` | `test_agent_factories_omit_max_tokens_on_param_surface` | `monkeypatch.setattr(agents_mod, "tlog", lambda *a, **k: None)` | **改** | 静默 tlog 清退；保留 factory kwargs |
| `web/src/useSettlementFlow.test.tsx` | `throttles inflight reloads and converges to the visible phase returned after waiting` | `vi.spyOn(console, "warn")`；`warn.mock.calls.some(... pollError)` | **改** | 删 console 诊断信号；保留 phase／error／loadState |

### B. 保留 — CLI capsys（逐条：测试断言 ↔ 生产输出来源）

入口均为 `ming_sim/cli/terminal.py` → `play_turn`；捕获的是用户终端 stdout，不是 tlog／logger。

| 测试函数 | 测试断言（源字段） | 生产输出来源（文件／函数／字段） | 为何非诊断 |
|---|---|---|---|
| `test_issue_refusal_stays_in_loop` | `assert str(exc) in capsys.readouterr().out`；`exc`=parametrize 的 `SettlementAbort`／`LLMContractError` 消息 | `play_turn` issue 分支 `except … as error: print(f"\n{error}")`（`terminal.py`） | 用户可见拒因原文透传 |
| `test_play_turn_skip_settlement_abort_stays_in_player_loop` | 同上（skip 路径） | `play_turn` skip 分支同形 `print(f"\n{error}")` | 同上 |
| `test_play_turn_reports_default_approval_secret_order_failure` | `assert str(failure_id) in out`；`failure_id`∈`{42,0}` 来自 pending action `id` | `_print_pending_action_failures` → `print(f"【密令落库失败{suffix}】…")`，`suffix` 用 `failure["id"]`；payload 由 `session._pending_action_failure_payload` 填 `"id": int(pa.get("id") or 0)` | 密令失败 id 用户通道 |
| `test_play_turn_reports_secret_order_failure_when_settlement_aborts` | `assert "42" in out`（pending `id=42`） | 同上：abort 后仍 `_print_pending_action_failures(...)` | 同上 |
| `test_play_turn_skip_prints_dossier_settlement_report_and_ends_turn` | `assert "留中案卷本月重判月报" in out`；字符串来自 stub `result.report` | `_adjudicate_cli_decisions` 在非 awaiting 时 `return result.report`；`play_turn` `print(report)` | 月报原文用户通道透传 |

### C. 保留 — 闸类隔离负向

| 路径 | 测试函数 | 命中 | 生产来源 | 依据 |
|---|---|---|---|---|
| `tests/test_player_army_projection_321.py` | `test_four_chains_embed_situation_matrix` | `contextlib.redirect_stdout`；`assert header_army_sentinel not in header_out` | `ming_sim/report.py` → `print_header`（#321：header 不回流 `army_report`） | 隔离负向：哨兵军名不得出现在 header；非诊断条数／类名 |

### D. 宽扫候选但非 D5-A§5 诊断契约（精确列出，勿泛指）

#### D1. `assert logs` → 结构化 DB 流水（变量名假阳性）

| 路径 | 测试函数 | 断言 | 实际依据 |
|---|---|---|---|
| `tests/test_pihong_dossier_1490.py` | `test_657_abi_mapper_matrix_a1_a12` | `assert logs` | `logs = SELECT action FROM person_logs …` |
| `tests/test_mutiny_third_strike_318.py` | `test_zero_manpower_latched_clears_before_continue_no_third_strike` | `assert logs, "…army_logs…"` | `_logs(db, …)` → `army_logs` |
| `tests/test_fiscal_substrate_bridge.py` | `test_army_delta_arrears_rejects_exempt_army_under_cutover` | `assert logs["count"] == 0` | `SELECT COUNT(*) AS count FROM army_logs …` |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_materializes_derived_release_before_appointment` | `assert logs == [{action…}, …]` | `SELECT … FROM person_logs` |
| `tests/test_person_delta_adapter.py` | `test_historical_death_tick_writes_person_log` | `assert logs` | `person_logs` |
| `tests/test_person_delta_adapter.py` | `test_historical_debut_tick_sets_reason_code_and_log` | `assert logs` | `person_logs` |
| `tests/test_shared_resource_order_1844.py` | `test_player_decrees_sequential_army_station_reads_updated_roster` | `assert logs[-2/-1][old/new_value]…` | `SELECT old_value, new_value FROM army_logs …` |

#### D2. `type(…).__name__`／异常类 — 非 caplog 类名筛选

| 路径 | 测试／符号 | 命中 | 处置依据 |
|---|---|---|---|
| `tests/test_pihong_dossier_1490.py` | `_657_subprocess_resolve` | `summary.update({"exc": type(exc).__name__, …})` | 子进程结果摘要字段，非日志筛选 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | `test_production_seam_cancel_blocks_trail_write` | `outcome["cancelled"] = type(exc).__name__`；后断言 `== "TicketCancelled"` | 结构化 outcome，非 caplog |
| `tests/test_chat_stream_failpaths_393.py` | `_base_runtime` | `if type(ev).__name__ == "RunContent"` | agno 事件分流，非日志 |
| `tests/test_chat_stream_failpaths_393.py` | `RunErrorEvent`（类／doc） | 文档说明 `type(event).__name__ == 'RunErrorEvent'` | 事件替身类名，非 caplog 筛选 |
| `tests/test_web_audience_night_498.py` | `RunCompletedEvent`（类注释） | 注释：web_app 按 `type(event).__name__` 判终帧 | 生产事件契约替身，非诊断日志 |
| `tests/test_qa_1281_issue_audience_case_facts.py` | `test_malformed_event_audience_fails_loud_from_material_entry` | parametrize `expected_exc`∈`TypeError`／`json.JSONDecodeError`；`pytest.raises(expected_exc)` | raises 类型契约，非「按日志筛异常类名」 |
| `tests/test_character_knowledge_489.py` | （含 `pytest.raises((TypeError, ValueError, json.JSONDecodeError))` 的案） | `pytest.raises(…JSONDecodeError)` | 同上 |
| `tests/test_month_loop_tracer_1468.py` | （含 `except json.JSONDecodeError` 的案） | 解析防御分支 | 非日志断言 |
| `tests/test_runtime_llm_config.py` | （docstring 提及 `JSONDecodeError`） | 文档说明坏 JSON 分支 | 非断言命中 |

#### D3. `call_count` — 非 logger.call_count

| 路径 | 测试函数 | 命中 | 处置依据 |
|---|---|---|---|
| `tests/test_month_chain_1847.py` | `test_step_4a_incomplete_0058_report_fails_loud_and_retry_restarts` | `assert call_count == 2` | 本地计数 `supply_run` 重试次数 |
| `tests/test_month_chain_1847.py` | `test_step_4a_crash_recovery_resumes_without_re_running_supply` | `assert call_count == 1` | 同上，防重跑 supply |
| `tests/test_month_chain_1847.py` | `test_step_4a_non_validation_failure_keeps_product_on_retry` | `assert call_count == 1` | 同上 |

#### D4. logger mock／`assert_called` on logger

宽扫 `logger = MagicMock`／`patch(...logger)`／`getLogger`＋`assert_called*`：**无命中**（0 条诊断 logger mock 契约）。

`tests/test_material_directory_1830.py` 仅 `from unittest.mock import MagicMock, patch` 导入行命中宽扫，文件内无 `MagicMock(`/`patch(` 调用、无 logger 断言 → **非 D5-A§5 成员**。

`pytest.raises(...) as exc_info`（如 `test_fiscal_substrate_bridge`／`test_month_chain_1843`／`test_web_llm_runtime_config`／`test_enter_settlement_period_1235`／`test_secret_order_monthly_progress_566`／`test_chat_stream_failpaths_393` 结构化 payload 案）属 raises 绑定，**不是** `caplog.records` 的 `exc_info` 筛选。

## 复扫（含保留项）

修后对诊断捕获谓词复扫，残留仅：

```text
KEEP  tests/test_cli_play_turn.py
      — 上表 B：play_turn 用户 stdout（str(exc)／failure id／result.report）
KEEP  tests/test_player_army_projection_321.py
      — 上表 C：print_header 隔离负向
```

```bash
rg -n 'caplog|capsys|capfd|readouterr|redirect_stdout|redirect_stderr|setattr\([^)]*["'\''](tlog|_tlog|log|print)["'\'']|logs\.append|_capture_tlog|spyOn\(console|vi\.spyOn\(console' tests web/src -g '*.{py,ts,tsx}'
# 诊断捕获／断言：仅 cli_play_turn（capsys 用户出口）+ player_army_projection（隔离负向）
# 无 caplog 诊断断言；无 tlog 捕获／静默 monkeypatch；无 console.warn spy 断言
# logger mock / logger.call_count：仍为 0
```

旧成员表触及项已标 `SIGNAL`，见 `evidence/issue-1902/D5-members.md`（本轮同步更新保留依据）。

## 变异证明

本轮为纯删诊断信号／死夹具，无新增 behavior → **不写变异证明**（纯删无需新增证明；未引用用户变异授权原话，亦不冒标授权）。

## 验证（七 BIN 完整前缀；只聚焦）

代码面本轮证据补齐未再改测试；下列为改码当轮实测（证据层修订不要求重跑）。

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false

/usr/bin/time -p python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/d5-signal-1902/bt-focus \
  tests/test_rescript_draft_656.py \
  tests/test_override_breach_costs_564.py \
  tests/test_decree_commitment_creation_136.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_relation_seed_638.py \
  tests/test_decree_dossiers_571.py \
  tests/test_cli_entry_1902.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_fiscal_levy_effect.py \
  tests/test_llm_channel_config.py \
  tests/test_cli_play_turn.py \
  tests/test_player_army_projection_321.py

cd web && /usr/bin/time -p npx vitest run --environment jsdom \
  src/useSettlementFlow.test.tsx
```

## 变更路径

```
tests/test_rescript_draft_656.py
tests/test_override_breach_costs_564.py
tests/test_decree_commitment_creation_136.py
tests/test_chat_stream_failpaths_393.py
tests/test_relation_seed_638.py
tests/test_decree_dossiers_571.py
tests/test_cli_entry_1902.py
tests/test_decree_commitment_settlement_229.py
tests/test_fiscal_levy_effect.py
tests/test_llm_channel_config.py
tests/test_cli_play_turn.py          # 未改代码；成员表标保留（上表 B）
tests/test_player_army_projection_321.py  # 未改代码；成员表标保留（上表 C）
web/src/useSettlementFlow.test.tsx
evidence/issue-1902/D5-members.md
evidence/issue-1902/d5-signal-receipt.md
```

## 禁止项自检

- 未 commit／stash／amend／push／PR
- 未新造测试／扫描机制／生产护栏
- 未改已结其他类处置为「另造信号约束」
- 临时物仅 `/tmp/d5-signal-1902/`；交卷后清理
- 未冒标变异授权原话

## 验证实测

```text
七 BIN 前缀 + python3 -m pytest -q -p no:cacheprovider --basetemp=/tmp/d5-signal-1902/bt-focus \
  （上列 12 个触及／保留 Python 文件）
→ 472 passed in 10.49s
  real 11.06  user 6.41  sys 2.40

cd web && npx vitest run --environment jsdom src/useSettlementFlow.test.tsx
→ Test Files 1 passed；Tests 18 passed
  Duration 906ms；real 1.39  user 1.20  sys 0.23

git diff --check → 无输出（exit 0）
死 import／参数／夹具自查：触及文件无残留 caplog/capsys/token_stats/_capture_tlog；
  useSettlementFlow.test.tsx 无 console.warn spy／warn.mock 断言
```

## 主修内司复验

七 BIN 完整前缀执行 `python3 -m pytest -q -p no:cacheprovider tests/test_rescript_draft_656.py tests/test_decree_commitment_creation_136.py tests/test_chat_stream_failpaths_393.py`：`116 passed in 2.66s`。
`git diff --check` 无输出；自建目录不存在，输出 `d5-signal-1902_removed=True`。

## 清理

```bash
rm -rf /tmp/d5-signal-1902
test ! -e /tmp/d5-signal-1902 && echo 'd5-signal-1902_removed=True'
```

## 未结项

- 主修内司已复核，独立提交 SHA 见终局回执。
- 未跑全量 pytest／未 push／未开 PR。
