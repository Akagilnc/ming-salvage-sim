# #1834 修内司回执 · F16 packaging-KEEP 反例全类修理

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**父 HEAD（开工）**：`71c0a4868`（stamp after f1635db3a）
**判词**：`evidence/1834-f16-f3-f3r-f17-fix/continued-ruling.json` + 用户反例（cli_backend 856/859）
**法源**：CLAUDE.md P6 / ADR 0142；判词 F16「自由文本零删改」；stdout 包装改写**不是**合法例外。

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

F3 / F17：保持已修；F17 已获允许撤销证明，本轮未新造变异。

---

## 反例

用户实读 `ming_sim/cli_backend.py` 825–910：`_iter_cli_runner_text` 对 `stdout_text.strip()` / `final_text.strip()` yield，`_run_cli_runner` `return text.strip(), 1`。旧 `f16_hand_verify_after_ruling.tsv` 对 856/859 标 KEEP「进程包装不是自由正文」。真实返回是 LLM 正文，经 CliChat.invoke / `_run_backend_for_config` 进入 extract → 拟诏/召对/密令等 supply/write 链。

---

## 1. 撤销

| 证据 | 处置 |
| --- | --- |
| `f16_hand_verify_after_ruling.tsv` | **REVOKED_PACKAGING_KEEP**（误把 stdout 包装当合法例外） |
| `f16_hand_member_table.tsv` | 仍 **REVOKED_TEMPLATE**；内容 stub，去重复堆叠 |
| 旧窄枚举 `enum_f16_rewrite_shapes_rerun.txt` 等 | stub；权威枚举改 broad |

---

## 2. F16 枚举（完整形状，非四类收窄）

完整命令与 HIT：`enum_f16_broad_meta.txt` / `f16_disposition_after_counterexample.METHOD.txt`

```bash
rg -n --glob 'ming_sim/**/*.py' --glob 'web_app.py' --glob 'web/src/**/*.{ts,tsx}' \
  '\.strip\(\)|\.lstrip\(\)|\.rstrip\(\)|\.trim\(\)|\.trimStart\(\)|\.trimEnd\(\)|\.replace\(|re\.sub\(|\[:\s*\d+\s*\]|\.split\(|\.join\(|\.substring\(|\.slice\('
# → enum_f16_rewrite_shapes_broad.txt  HIT_COUNT=2241
```

高信号 return/assign：`enum_f16_return_assign_strip.txt`

权威处置（按真实同一职责归并，成员全列）：`f16_disposition_after_counterexample.tsv`

---

## 3. 本轮 FIX_APPLIED（生产）

| loc | 实质 |
| --- | --- |
| `cli_backend._iter_cli_runner_text` / `_run_cli_runner` | LLM 终文：判空用 strip 副本；yield/return 原文；codex 横幅只切不 strip |
| `decree.write_decree_with_agno` | 拟诏正文保原文 |
| `llm_contract.require_non_empty_text` | 判空副本，返回原文 |
| `action_materialize._parse_json_field` | JSON 判空副本；非 JSON 回落原文 |
| `cli_backend._matched_prefix` | 只 lstrip 定位前缀；正文 raw |
| `situation.tsx` commitmentProgressText / barLabel | 展示 trim 只判空 |
| `closedIssues.tsx` closedBarLabel | 同上 |
| `edictModal.tsx` sourceLabel | 同上（结构化 source/actor） |

合法 KEEP 类：机器键/枚举；JSON 围栏；局部判空；静态配置；HTTP 错误信道；退役无调用的 recommend 信封残段（未删宿主、未复活 import）。

---

## 4. 真实入口观察

`probe_cli_body_preserve.txt`：cli_runner / decree / contract / json_field / matched_prefix 均保边空白。

---

## 5. 聚焦测试

### pytest

完整输出：`pytest_focus.txt`

结果：**121 passed**（`test_cli_runner_error_typed_1299` + `test_cli_backend` + `test_cli_transport_1465`）

### vitest

```bash
cd web && npx vitest run --environment jsdom src/components/situation.test.tsx
```

完整输出：`vitest_focus.txt` — **11 passed**

---

## 未结（诚实）

- 不声称 2241 候选外永无新形状；权威以本轮 disposition 表为准。
- 退役 `_cli_recommendation_call` 残段未删（宿主机制保留）；不在 live 调用图。
- F17：仍仅撤销申报，无新旧并排变异。
- 未跑全量；未 stash/amend/push/PR。

自查二连 done（再读本轮 diff：CLI/拟诏/契约/JSON 回落/前端展示均判空副本+取值 raw；未把 stdout 包装当 KEEP；证据去重 stub 旧表）。
