#1847 修内司交卷 — w7 自验修正（废除 KEEP_HARNESS_CONTEXT 活正文豁免）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- 派单: `/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10906-b970-7021-8014-282026406f92@fixer/fix-packet.md`
- 判词真源: 附件 `03-1847-judge-bcf7a7bf7.json` **末份 payload**
- 禁令: 未 amend / rewrite / push / PR / stash

## 本轮自验指摘 → 纠正

上一交卷 `human_n6.tsv` 将 `ask_emperor` 的 `cli_chunk[-3500:]` 标为 `KEEP_HARNESS_CONTEXT`。错误：

- 活脚本 CLI 含模型人物自由正文；截断后递另一 LLM = 活原文运输删改
- 并非冻结卷宗统计；判词已说「脚本驱动活模型非豁免」
- harness / 新底座不是正文运输豁免理由

本轮：

1. **删除** `scripts/play_as_emperor.py:ask_emperor` 的 `cli_chunk[-3500:]`；payload 嵌入完整 `cli_chunk`。
2. **扫描**同脚本及仓内活模型供料窗口裁剪同形：生产/脚本中 stdout→另 LLM 仅此一处；`child.before[-2000:]` / `prompt_hint.strip()[:40]` 等为冻结日志诊断，合法保留；`agents.py` tlog `[-160:]` / error `raw[:800]` 同属诊断。
3. **禁止**另加 token/保护/适配层；不发明 harness context 豁免。
4. **read_text**：生产侧仅 asset/config IO（`opening_gazette` fingerprint strip、VERSION、requirements、seed JSON）；无自由原文换行改写入运输。
5. **保留**结构切片/形式信封：`parse_emperor_output` envelope locate；`findall` 待核定 id；封闭口令/DSL form。

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
| N6 | 2893（全 `POTENTIAL_*`/`TEST_HIT`，**零自动 KEEP**；删 `[-3500:]` 后较上轮少 1） | `human_n6.tsv` |
| N11 | 24 闭包符号（21 ABSENT + 3 KEEP_LIVE_CONSUMER） | `human_n11.tsv` |
| N13 | 284 | `human_n13.tsv` |
| N14 | 432（含 298 `assert_same_name_eq` 机械候选） | `human_n14.tsv` |

**明确非声称**：机械候选数 ≠ 已审核成员数。

## N6（真成员 + 合法例外）

- **真类成员本轮 FIX**：`ask_emperor` CLI→emperor LLM 窗口裁剪（`FIXED_THIS_ROUND`）。
- **真类成员残差**：无（其余自由正文运输 sink 经阅读：故事账→opening、spoken、gazette、public_sayings、parse_emperor→sendline、issue fail_condition 非 DSL 直通，均无 strip/replace/slice 入运输）。
- **合法同根例外**（路径见 `human_n6.tsv`）：empty-local 判空、封闭口令/DSL form、**冻结日志/error 诊断截断**、asset fingerprint `read_text`、sqlite sanitize。**无 KEEP_HARNESS_CONTEXT**。
- **read_text**：人工区分 asset/config IO vs 自由正文运输；无 decode 后删改/换行改写入运输。
- **展示截断**：玩家面 `fail_condition` 原样（`situation.tsx`）；`format.ts:splitReportItems` 无生产引用。

## N11 / N13 / N14

未改；见上一交卷与 `human_n11.tsv` / `human_n13.tsv` / `human_n14.tsv`。

## 真实入口旧逻辑红 / 当前绿（七 false；既有 mutation，不新建证明测试）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w5-correction/n6_ask_emperor_pty_mutation.py
```

| 证据 | 结果 |
|---|---|
| `N6_OLD_CLI_CHUNK_WINDOW_DROPS_PREFIX_*` | PASS（旧 `[-3500:]` 丢掉 PREFIX 人物正文） |
| `N6_ASK_EMPEROR_CLI_CHUNK_FULL_*` | PASS（当前 payload 含完整 cli_chunk） |
| `N6_NO_CLI_CHUNK_SLICE_3500` / `N6_ASK_EMPEROR_USES_FULL_CLI_CHUNK` | PASS |
| `N6_LOG_DIAG_TRUNC_RETAINED` | PASS（日志诊断截断保留） |
| PTY sendline 原样 + 旧 strip/splitlines/[:200] 变异对 | PASS（既有） |

全文：`evidence/1847-w5-correction/n6_ask_emperor_pty_mutation.txt`。

N13 lifecycle：既有 `n13_lifecycle_probe.py`（本轮未改）。

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

- 无源码判桶测试、无灌卷伪 KEEP map、无新建证明测试
- 无新增监管/重试/保护/token 适配层
- 0055 / 无人站台 / 中旨 / 御笔强推仍在
- 无 secrets；无 amend/push/PR/stash
- 无 harness / 新底座正文运输豁免

## git 事实

- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- delivery commit：以本交卷 `git rev-parse HEAD` 为准

## 自查二连 done

- 同类：把活脚本 CLI→另 LLM 窗口裁剪误标 harness 豁免；冻结日志诊断与活运输混淆
- 引入：删截断后不得另加 token 护栏；日志 `[-2000:]` 等诊断截断须保留；不把机械候选当已审成员
