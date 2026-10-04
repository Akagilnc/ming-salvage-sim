#1847 修内司交卷 — w7 主席复检修正（废除伪结清）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- 派单: `/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10906-b970-7021-8014-282026406f92@fixer/fix-packet.md`
- 判词真源: 附件 `03-1847-judge-bcf7a7bf7.json` **末份 payload**
- 禁令: 未 amend / rewrite / push / PR / stash

## 主席未结 → 本轮纠正

上一交卷 `finalize_judgments.py` 按 `FREE_TEXT_NAMES`/snip 正则自动 KEEP（read_text→G_IO、未命中名→G_NOT_TRANSPORT、slice→展示截断 KEEP），伪称语义结清。本轮：

1. **删除**伪结清脚本及 map/summary（见 `evidence/1847-w7-correction/CORRECTION.md`）。
2. **保留**通用机械枚举 `scan_n6_n11_n13_n14.py`（只产 `POTENTIAL_*` 等机械桶；N11 按旧消费者路径闭包，不按 name_pattern 灌表；局部变量不进 defs）。
3. **实际阅读**生产自由正文赋值/返回/供料/展示与 trim/re.sub/replace/slice/read_text 用途；报告只列真类成员 + 合法同根例外（真实调用路径）。
4. **N11**：闭包含 extract/summon/landing 独占助手；删死投影 `secret_order_landing_recovery`（session + web_app）；保留 `_ledger_by_origin_ref` / `secret_order_can_land` / `secret_order_landing_gaps` 现役路径。
5. **N13**：生产位点逐项阅读；best-effort 一律写明 continue 契约（见 `human_n13.tsv`），否则不予 KEEP。
6. **N14**：不把 `assert a==b` 一律当 `BEHAVIOR_EQUALITY`；区分真实入口负向案 vs 同值空复查。机械 298 条仍是候选，不是已审成员。

## 可重跑机械枚举（非法源）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w7-correction/scan_n6_n11_n13_n14.py
```

| 类 | 机械候选（`scan_summary.json`） | 人工结论表 |
|---|---|---|
| N6 | 2894（全 `POTENTIAL_*`/`TEST_HIT`，**零自动 KEEP**） | `human_n6.tsv` |
| N11 | 24 闭包符号（21 ABSENT + 3 KEEP_LIVE_CONSUMER） | `human_n11.tsv` |
| N13 | 284 | `human_n13.tsv` |
| N14 | 432（含 298 `assert_same_name_eq` 机械候选） | `human_n14.tsv` |

**明确非声称**：机械候选数 ≠ 已审核成员数；未把 2894/432 行映射成 KEEP。

## N6（真成员 + 合法例外）

- **真类成员残差**：无（自由正文运输 sink 经阅读：故事账→opening、spoken、gazette、public_sayings、parse_emperor→sendline、issue fail_condition 非 DSL 直通，均无 strip/replace 入运输）。
- **合法同根例外**（路径见 `human_n6.tsv`）：empty-local 判空、封闭口令/DSL form、harness `cli_chunk[-3500:]`、asset fingerprint `read_text`、error/diag 截断、sqlite sanitize。
- **read_text**：不再豁免；人工区分 asset/config IO vs 自由正文运输（本轮未发现 decode 后删改入运输）。
- **展示截断**：玩家面 `fail_condition` 原样（`situation.tsx`）；error/diag/harness 截断见例外表。`format.ts:splitReportItems` 无生产引用。

## N11（旧消费者路径闭包）

| 处置 | 符号 |
|---|---|
| DELETED_CONFIRMED | summon/extract/landing 岛及独占助手（见 human 表 21 ABSENT） |
| DELETED_THIS_ROUND | `secret_order_landing_recovery`（session 字段 + `_chat_payload` 键；零前端消费者、零生产者） |
| KEEP_LIVE_SHARED | `_ledger_by_origin_ref` ← `audience_night.py:1764/1789/1808`；`secret_order_can_land` ← `declaration_dispatch.py:1242`；`secret_order_landing_gaps` ← `can_land` |

未按 legacy 字样猜删；0055 / 另旨·中旨 / 御笔强推案未动。

## N13（continue 契约）

生产软收尾：

- `cli_backend._terminate_cli_process` / `_iter_cli_process_lines.finally`：软终止失败留痕，不覆盖 body 失败。
- `play_as_emperor.close(force=False)`：生态选择；软失败补官方 closed/fd；`log_file.close` 为 host best-effort（契约见 human 表）。
- db/audience_night rollback：best-effort 后 **必 raise**。
- token_stats / launcher：telemetry/host glue continue 契约已文档化。
- FIX 残差：**[]**（无可达 `force=True` / 子进程 SIGKILL）。

变异：`n13_lifecycle_probe.py` → `n13_lifecycle_probe.json`；stderr **VERDICT GREEN**（七 false）。N6 PTY mutation：全部 PASS（`n6_ask_emperor_pty_mutation.txt`）。

## N14

- getsource 真成员：0。
- `assert a==b`：**不**一律行为相等；负向真实入口（操作已跑、期望不变）保留；同值空复查在聚焦案中已无。
- 机械 `POTENTIAL_SAME_VALUE_RECHECK` 298 = 候选，**不是**已审成员。

## 真实入口变异（七 false）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w7-correction/n13_lifecycle_probe.py
```

N6 ask_emperor→PTY：既有 `evidence/1847-w5-correction/n6_ask_emperor_pty_mutation.py`（真入口，非 mutation-probes HTTP）。

## 聚焦测试（七 false）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_month_chain_1847.py tests/test_audience_translate_1837.py \
  tests/test_web_audience_night_498.py tests/test_issue_entities.py \
  tests/test_population_transfers_649.py tests/test_cli_backend.py \
  tests/test_advance_paths_atomic.py tests/test_pihong_dossier_1490.py \
  -q --basetemp=/tmp/1847-fixer-w7/focused
```

实测：`231 passed`（`focused_pytest.txt`）。未跑全量。

## 提交前质量复检

- 无源码判桶测试、无灌卷伪 KEEP map
- 无新增监管/重试/保护层
- 0055 / 无人站台 / 中旨 / 御笔强推仍在
- 无 secrets；无 amend/push/PR/stash

## git 事实

- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- delivery commit：以本交卷 `git rev-parse HEAD` 为准

## 自查二连 done

- 同类：FREE_TEXT_NAMES/snip 自动 KEEP；N11 只贴判词种子；N13 best-effort 无 continue 契约；N14 assert 一律 BEHAVIOR_EQUALITY；机械候选冒充已审成员
- 引入：删死投影须核前端零引用；N11 defs 不含局部 Assign；报告分开「机械候选 / 人工成员」
