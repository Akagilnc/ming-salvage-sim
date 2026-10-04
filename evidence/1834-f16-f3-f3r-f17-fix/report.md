# #1834 修内司回执 · F16 自审复检（尾空白 / 空 snippet 重映 / 广扫去测试假充）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**父 HEAD（复检开工）**：`37a4608f5`
**尾空白清理 commit**：`15025f0177d2518f6059d7e867b992148a2519ba`
**本轮 commit**：`4b734295089c91805f8268d6ea909fe366a7aca3`
**用户续判唯一真源**：`evidence/1834-f16-f3-f3r-f17-fix/continued-ruling.json`
**法源**：CLAUDE.md P6 / ADR 0142；判词 F16「自由文本零删改」；stdout 包装改写**不是**合法例外。

**归因（勿冒称用户续判）**：

| 表述 | 归因 |
| --- | --- |
| F3-N / F16-R / F17-R 三类处置 | 用户续判 `continued-ruling.json`（真源） |
| 「退役残段不得宿主保留」「16 组全员映射」 | **本角色自审纠正**（宪法：零调用退役残段随改删除；空 snippet≠语义已读；广扫仅生产候选）— **非**用户原判逐字 |

**共同测试前缀（七变量，pytest / vitest 均实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 三类处置（单真源引用，本回执不覆盖）

本轮自审局部**不**重写 F3-N / F16-R / F17-R 结清叙事。权威成员与撤回说明仍以既有单真源为准：

| 类 | 单真源 | 摘要锚点 |
| --- | --- | --- |
| **F3-N** 恢复越界撤回 | `git show f1635db3a:evidence/1834-f16-f3-f3r-f17-fix/report.md` §1；`enum_f3n_rescan.txt` | 撤回措辞/模板锁；保留 561 许誉卿；透传改回「途中病故」「后事。」 |
| **F16-R** origin/crime 等修理成员 | 同上 §2；`probe_current_side.txt`；`f16_hand_member_table.REVOKED_TEMPLATE.txt` | `_seed_guilt_storage_value` crime 保原文；`covert_progress` origin 保原文；`_split_audience_context` raw 切片；staged/due 判空回退 |
| **F17-R** 撤回「旧生产逻辑装回」 | 同上 §3；`F17_F3R_REVOCATION.txt`；`mutation_temp_real_entry.json` | `verdict_old_logic_restored=false`；仅当前侧观察；无新旧并排、无新造永久证明 |

---

## 本轮自审复检修正

### 1) `git diff --check ee3b5da31 HEAD` 本轮自建尾空白

| 文件 | 问题 | 处置 |
| --- | --- | --- |
| `f16_disposition_member_locs.tsv` | 空 snippet 尾 TAB | 重映后写入真实源码行；无尾空白 |
| `report.md` | markdown 行尾双空格 | 重写回执，去掉 |
| `vitest_focus.txt` | EOF 空行 | 重跑聚焦后无多余 EOF 空行 |

用户判词允许去掉本轮自建尾空白 → 已清。

### 2) 空 snippet / 错位 loc（非语义已读）

空串不得充当 `machine_key` / 其它组的已读依据。漂移行按当前源码重映（旧 loc→新函数），详见 `f16_member_loc_remap.txt`。

样本：

| 旧 loc | 新 loc | 函数 |
| --- | --- | --- |
| `action_materialize.py:1019`（空） | `:1022` | `re_split_bodies` |
| `action_materialize.py:1130`（空） | `:1133` | `_match_office_row_by_name_office` |
| `action_materialize.py:1536`（空） | `:1539` | `stage_assignment_candidate` |
| `action_materialize.py:1775`（空） | `:1778` | `stage_referral_candidate` |
| `cli_backend.py:4534`（空） | `:4465` | `invoke_stream` |
| `cli_backend.py:4674+`（OOB / `<err>`） | `:4605`…`:4653` | `gate_llm_config_from_args` / `require_fresh_cli_trace` / `gate_evidence_config` |

### 3) 广扫仅生产候选 — 去掉 `situation.test.tsx:87` 假充

- `situation.test.tsx:87` 在表中为空行，却标 `static_asset_config_load` → **假充语义结论**。
- 自审纠正：广扫 / member_locs **排除** `web/src/**/*.test.*`（非生产供料/写口候选）；不新增分类机制。
- `enum_f16_rewrite_shapes_broad.txt` HIT_COUNT 见 `enum_f16_broad_meta.txt`；权威组表仍 16 组（`f16_disposition_after_counterexample.tsv`）。

### 4) 仍保留的既有处置（非本轮新造）

- 五条新永久证明测试已删（见父轮 `7fc7108a2`）。
- `_cli_recommendation_*` 零调用残段 **DELETED**（自审+宪法，非用户续判逐字）。
- F17 维持合法撤销路线；本轮未新造证据/变异机制。

---

## 聚焦测试

### pytest

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest tests/test_cli_runner_error_typed_1299.py tests/test_cli_backend.py tests/test_cli_transport_1465.py -q --tb=line
```

完整输出：`pytest_focus.txt` — **117 passed**

### vitest

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
npx vitest run --environment jsdom src/components/situation.test.tsx
```

（cwd=`web/`）完整输出：`vitest_focus.txt` — **10 passed**

---

## 未结（诚实）

- 不声称生产广扫外永无新形状；权威以 disposition + member_locs + remap 为准。
- F17：仍仅撤销申报，无新旧并排变异，无新造证据机制。
- 未跑全量；未 stash/amend/push/PR。
- 本轮**未新增**永久证明脚本或测试。

自查二连 done（再读：空 snippet/OOB 已重映、测试假充已移出生产广扫、尾空白已清、三类处置单真源引用未覆盖、归因已标明自审 vs continued-ruling.json）。
