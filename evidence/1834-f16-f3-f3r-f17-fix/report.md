# #1834 修内司回执 · F16 / F3 / F3-R / F17（续修，清空原 36 FIX_REMAINING）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**本轮 parent**：`fe4c04deb7847438a57e4f6a6947d6d41f9c2c91`
**本轮**：逐项清空 `f16_hand_member_table.tsv` 原 36 `FIX_REMAINING`；复扫误 KEEP 自由正文漏项；机器键经类型职责证据 KEEP；F3 独立契约复检仍在；F3-R 手核表无新增真弱重复删除；F17 临时入口装回旧 strip 逻辑红绿。

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 1. F16「自由正文搬运仍改写原文」

### 扫描范围 / 枚举

- 枚举文件：`enum_f16_all_candidates.txt`
- 形状计数：`enum_f16_shape_counts.txt`
- 方法说明：`f16_hand_member_table.METHOD.txt`
- 逐项处置：`f16_hand_member_table.tsv`

### 处置计数（本轮后）

| disposition | count |
| --- | ---: |
| FIX_APPLIED | 100 |
| FIX_REMAINING | 0 |
| KEEP | 2185 |

### 原 36 FIX_REMAINING 处置

| 类 | 成员 | 处置 |
| --- | --- | --- |
| 自由正文保原文 | audience_night body；cli_backend player_message/正文/failure_reason/decree_text/confirmation material/merge chunk/dossier note；content status_reason/clear_narrative；db highlights/dossier note/legacy name；decree_vocabulary title/note；highlight_judge phrases/reply；mechanical_tail gazette body；month_chain cheat；rescript note；session message/title/body/stance；cheatConsole/useSettlementFlow cheat | **FIX_APPLIED**（判空用 strip 副本；禁 regex 删正文 / trim 写出） |
| 已先修 | `db.py` person_logs `source` 裁剪（前轮已去 `[:80]`） | **FIX_APPLIED**（表对齐 live） |
| 机器键 KEEP | `covert_progress` category/region/region_target；`legacies.legacy_key[:60]`；`investigation_spoiled_facts.origin_ref[:120]` | **KEEP**（结构化身份/合同键，非自由正文） |

### 复扫漏项（原误 KEEP 为「非供料」）

| loc（表内） | 处置 |
| --- | --- |
| `cli_backend.py:3119` push `draft_text` strip | FIX_APPLIED |
| `cli_backend.py:3841` `_split_audience_context` 皇帝任务 `.strip()` | FIX_APPLIED（结构前缀仍用 strip 副本匹配；任务正文保原文；confirmation 不再 regex 剥原子） |
| `cli_backend.py:4013` confirm_dossier_links 标题供料 strip | FIX_APPLIED |
| `content.py:106` seed_guilt.crime strip | FIX_APPLIED |
| `session.py:1016` 含糊收夜 answer strip | FIX_APPLIED |
| `issues.py` legacy name strip（表外漏项） | 代码已修；写入路径与 `insert_legacy` name 保原文同向 |

合法例外（机器键，非正文）：`legacy_key` / `origin_ref` / covert `category|region|region_target`（及同角色 account/field 等既有 KEEP）。

---

## 2. F3「测试清理再次误删独立契约」

双向成员表：`f3_bidirectional_member_table.md`（历史 MISSING 集本树已恢复；复检仍在）。

| 断言 | 文件 | 复检 |
| --- | --- | --- |
| `"参与人" in capsys.readouterr().out` | `tests/test_decree_dossiers_571.py` | 在 |
| `"不足额" in execution_note`（在途+即时） | 同上 | 在 |
| `"应拨10两"` / `实拨{n}两` | 同上 | 在 |
| `"名实已乖" in execution_note` | `tests/test_dossier_reported_progress_619.py` | 在 |
| `recent_context == "后事。（天启六年二月）"` | `tests/test_relation_seed_638.py` | 在 |
| `"人物终态：dead；途中病故"` | `tests/test_secret_order_monthly_progress_566.py` | 在 |
| `not.toMatch(/臣.*叩见\|恭请圣安/)` | `web/src/components/modals.test.tsx` | 在 |
| `"许誉卿" in _gatekeeper_names(after)` | `tests/test_promulgation_judge_561.py` L692 | 在 |

本轮无新增契约恢复（上轮已齐）；无形状冒充语义。

---

## 3. F3-R「语义复核」

手核表：`f3r_hand_member_table.tsv`（合并 batch1–3 + 既有 FIX_DELETED）。

| disposition | count |
| --- | ---: |
| FIX_DELETED | 12 |
| KEEP | 377 |

本轮复检：自动 exact-dup 行扫描噪声大（大量 before/after / 互斥分支）；对照手核 KEEP 依据（互斥 param 臂、中间有真实状态变迁）—**无新增可证 weak⊂strong 同对象弱断言**需删。先前真重复删除仍保持（forecast `calls==[1]` 尾、deformation outcome 重申、mutiny/observed/tend_u 后置等只留强侧）。

质量自检：截断 `A=test_…` 主体 = 0；`intervening=assign@` 自动层 = 0。

---

## 4. F17

| 项 | 处置 |
| --- | --- |
| 永久 `mutation_real_old_red.py` / `probe_new_green.py` | 已删；历史 JSON + `*.REVOKED_METHOD.txt` 保留未改写 |
| 证明 | 临时进程内替换旧 strip 实现 → `mutation_temp_real_entry.json`（含 entry_points + old_logic_restore；符号装回） |

观察（本机本次）：staged/decision current preserve=true、old=false；region reason 全长落库且后缀「禁再向百姓加派。」；`verdict=true`。

---

## 5. 聚焦测试（完整命令 + 原始输出）

### pytest

完整命令与原始输出见 `pytest_focus.txt`：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_material_directory_1830.py tests/test_scene_llm_1836.py \
  tests/test_player_payload_1022.py tests/test_cli_runner_error_typed_1299.py \
  tests/test_dossier_reported_progress_619.py tests/test_staged_assignment_identity_1890.py \
  tests/test_promulgation_judge_561.py tests/test_qa_h1_seed_data.py \
  tests/test_execution_joint_liability_565.py tests/test_rescript_choices_563.py \
  tests/test_cli_backend.py tests/test_audience_undo_506.py \
  tests/test_decree_forecast_1861.py tests/test_deformation_dual_rail_622.py \
  tests/test_player_army_projection_321.py tests/test_secret_order_monthly_progress_566.py \
  tests/test_supervision_625.py tests/test_decree_dossiers_571.py \
  tests/test_relation_seed_638.py \
  tests/test_highlight_judge_544.py tests/test_month_chain_1843.py \
  -q -p no:cacheprovider --tb=line
```

结果（`pytest_focus.txt`）：**499 passed in 19.10s**

### vitest

完整命令与原始输出见 `vitest_focus.txt`：

```bash
cd web && npm test -- \
  src/appDurableWiring.test.tsx src/components/settlementGazettePanel.test.tsx \
  src/components/modals.test.tsx src/components/drawers.test.tsx \
  src/components/decisionModal.test.tsx src/decisionRouting.test.tsx \
  src/components/situation.test.tsx
```

结果：**Test Files 7 passed；Tests 190 passed**。
诚实：`git diff --check` 对 `vitest_focus.txt` → `new blank line at EOF`（原始输出尾空行保留，未为过 check 而篡改）。

邻票 `test_commitment_progress_contexts_are_structured` NameError 依判词交 #1873，不夹入。

---

## 6. 临时真实入口变异（可核）

文件：`mutation_temp_real_entry.json`

| 项 | 内容 |
| --- | --- |
| 入口 | `normalize_commitment_stages`；`parse_decision_blocks`；`apply_region_deltas`→`region_logs.reason`（经 `_seed_opening_db`） |
| 装回旧逻辑 | 进程内 monkeypatch 为 local `old_*`（`.strip()` 自由正文），比较后恢复原符号；**无永久证明脚本** |
| 观察 | current staged/decision preserve=true；old preserve=false；region reason 全长且后缀「禁再向百姓加派。」 |
| verdict | `true` |

历史 `mutation_old_red.json` / `probe_new_green.json` 字节保留 + `*.REVOKED_METHOD.txt`。

---

## 未结（诚实）

- F16：表内 `FIX_REMAINING=0`（原 36 已处置：31 FIX_APPLIED + 5 机器键 KEEP；另复扫误 KEEP 漏项 5 + issues.py 表外 1）。不声称枚举全集永无新形状命中——权威以手核表为准。
- F3-R：手核表维持；不声称「枚举外永无真重复」。
- `git diff --check`：`vitest_focus.txt` EOF blank **未净**（照实）。
- 未跑全量；未 stash/amend/push/PR。

自查二连 done。
