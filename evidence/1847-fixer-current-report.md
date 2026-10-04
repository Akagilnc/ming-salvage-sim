#1847 修内司交卷 — w7 第三次自检修正

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- 派单: `/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10906-b970-7021-8014-282026406f92@fixer/fix-packet.md`
- 判词真源: 附件 `03-1847-judge-bcf7a7bf7.json` **末份 payload**
- 禁令: 未 amend / rewrite / push / PR / stash

## 主席复检未结 → 本轮纠正

上一交卷以机械 `POTENTIAL_*` / `MECHANICAL_OTHER` / `name_pattern_not_authority` 冒充语义结案；`n14_fix` 列 51 项未读未修；证据 TSV 默认 CRLF 导致 `git diff --check` 尾空白爆炸。本轮：

1. **逐项语义终裁**：全仓重扫后按来源→去向 / 消费者图 / 外部行为归入终态桶；`disposition_summary.json.unresolved_open_buckets = 0`（无 POTENTIAL/MECHANICAL 待分类）。
2. **N11 消费者图闭包**：只裁决判词种子 + 独占 landing-recovery 孤儿；**删除** `compose_secret_order_landing_recovery` / `_secret_landing_gap_feature` / `_SECRET_LANDING_GAP_LABELS`（零消费者）。不按 name_pattern 灌表。`_ledger_by_origin_ref` / `secret_order_can_land` 现役保留。
3. **N13**：生产吞失败/强杀/析构逐项终裁；注释中的 `.kill(` 不作 FIX。`close(force=False)` 为前置生态选择；软失败后只补齐官方 close 会写的 public `closed`/`fd` 字段（已核 `dir(PtyProcess)` 无 detach）。
4. **N14 真成员**：删散文哨兵、改结构化 `report_section` / `payload.text` / 原文全等；`str(结构化字段)` 归 `FALSE_POSITIVE_STRUCT_COERCE`，不自动当身份哨兵。
5. **证据收敛**：CSV `lineterminator='\n'`；去掉 raw/classified 重复副本与旧 classify；保留可重跑 `scan_*` + `finalize_judgments.py`、结论表、N13 变异探针。

## 可重跑枚举

```bash
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w7-correction/finalize_judgments.py
```

| 类 | 结论表 | 终态 |
|---|---|---|
| N6 | `n6_groups.tsv` + `n6_map.tsv`（2843→9 组） | open_potential=0；transport_fix_hits=[] |
| N11 | `n11_closure.tsv`（16 符号） | 15 DELETED_CONFIRMED + 1 KEEP_LIVE_SHARED；actionable=[] |
| N13 | `n13_final.tsv`（284） | fix_residue=[]；生产 55 项均 KEEP_* |
| N14 | `n14_groups.tsv` + `n14_map.tsv` | open_potential=0；getsource=0 |

### N6 分组保留依据（同根）

| group | disposition | 核要点 |
|---|---|---|
| G_EMPTY_LOCAL | KEEP_EMPTY_LOCAL | 判空局部 strip；运输用原文（如 audience_night body） |
| G_IDENT | KEEP_IDENTIFIER_NORMALIZE | id/name/status/office/action 等 |
| G_FORM | KEEP_FORM_LANGUAGE | JSON 信封 / 封闭口令 |
| G_TEMPLATE / G_PATH / G_IO / G_SLICE_STRUCT | KEEP_* | 模板、路径、IO、结构切片 |
| G_NOT_TRANSPORT | FALSE_POSITIVE_NOT_TRANSPORT | 变更器命中但非自由正文运输 sink |
| G_TEST | OUT_OF_N6_CLASS | 归 N14 |

### N11 闭包

| symbol | disposition |
|---|---|
| rescript_summon_* / prepare_* / RESCRIPT_EMITTED_* / find_deliberation_* / _extract_secret_order / assemble_* / _DRAFT/_SECRET/_so_json / confirm_dossier_links | DELETED_CONFIRMED |
| compose_secret_order_landing_recovery 及 feature/labels | DELETED_CONFIRMED（本轮删） |
| _ledger_by_origin_ref | KEEP_LIVE_SHARED |

### N13 生产终裁摘要

- soft：`KEEP_SOFT_*`（cli_backend / play_as_emperor）
- 注释 SIGKILL/kill：`KEEP_DOC_COMMENT`
- rollback/telemetry/launcher/log close：`KEEP_*_BEST_EFFORT` / `KEEP_RESOURCE_CLOSE`
- web_app 自 SIGTERM：`KEEP_SOFT_SELF_SIGTERM`
- FIX 残留：**[]**

### N14 本轮代码修复

- `test_month_chain_1847`：删 `"不是行动" not in str(origin)`；`sim_note` 改为原文全等
- `test_audience_translate_1837`：`payload_json` → `payload["text"] == "拟旨赈济"`
- `test_web_audience_night_498`：`match["text"] == "着户部核边饷"`
- `test_issue_entities` / `test_population_transfers_649`：`report_section` 结构化筛拒收

其余 `str(origin/office/id/…)` → 组 `FALSE_POSITIVE_STRUCT_COERCE`；异常文案 → `KEEP_ERROR_DIAGNOSTIC`；`assert a==b` → `KEEP_BEHAVIOR_EQUALITY`。

## N13 变异（旧红/现绿）

`n13_lifecycle_probe.py` → `n13_lifecycle_probe.json`：raise 不覆盖 body；cli soft-fail 留痕；pty soft 路径无 SIGKILL。VERDICT **GREEN**。

## 聚焦测试

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

- `git diff --check`：绿（TSV 均为 LF）
- 净删简：删 landing-recovery 孤儿；N14 去散文哨兵；无新增监管/重试层
- 0055 / 无人站台 / 中旨 / 御笔强推案仍在
- 无 secrets；无 amend/push/PR/stash

## git 事实

- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- delivery commit：以本交卷 `git rev-parse HEAD` 为准

## 自查二连 done

- 同类：机械 POTENTIAL 冒充结案；name_pattern 冒充 N11；str() 字段强制当身份哨兵；CRLF 灌爆 diff --check
- 引入：终裁桶须可核到 map/closure；N11 不经 live shared 一跳灌 get/keys；注释 kill 不进 FIX
