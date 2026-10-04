# #1834 修内司回执 · F16 / F3 / F3-R / F17（续修，基线 ee3b5da31）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**本轮 commit**：`7bc1f626c01c43ce16e0d460308961e7c85f2aa2`  
**本轮**：撤销 AST/kind 自动 KEEP 表后，逐函数手核 F3-R；恢复 F3 独立契约；继续清 F16 供料/写路径正文改写；F17 仅临时入口替换。

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 0. 自审纠正（相对 04b62b858）

| 问题 | 处置 |
| --- | --- |
| `f3r_hand_member_table.tsv` 以 `intervening=assign@…` / 截断函数名冒充手核 | **撤销** → `f3r_hand_member_table.REVOKED_AST_AUTO.txt`；现行表由逐函数打开写出（见 §3） |
| `enum_f16_supply_path_after.tsv` 相对 live 失实且缺 web | **撤销权威地位** → `enum_f16_supply_path_after.REVOKED_STALE.txt`；权威 = `enum_f16_all_candidates.txt` + `f16_hand_member_table.tsv` |
| F16 枚举仅 ming_sim / 仅 strip·切片 | 重枚举含 `replace/re.sub/lstrip/rstrip/split/join/trim/slice`，范围 `ming_sim` + `web_app.py` + `web/src`（非 test） |
| F3 仅提交名核实 | 完整双向成员表 + 命令 → `f3_bidirectional_member_table.md`；并恢复 `beff66c17` 后仍缺失的独立契约 |
| report 测试段无完整命令；变异仅 verdict | 本回执补完整命令原文与入口/装回方法（§5–§6） |
| `git diff --check` vitest EOF blank | **不声称净**；`vitest_focus.txt` 保留原始尾空行（见 §5） |

---

## 1. F16「自由正文搬运仍改写原文」

### 扫描范围 / 枚举

- 枚举文件：`enum_f16_all_candidates.txt`（2285 行形状命中）
- 形状计数：`enum_f16_shape_counts.txt`（含 STRIP/SLICE/REPLACE/RE_SUB/LSTRIP/RSTRIP/SPLIT/JOIN/TRIM/SLICE_JS）
- 方法说明：`f16_hand_member_table.METHOD.txt`
- 逐项处置：`f16_hand_member_table.tsv`

### 处置计数（不以表自称全清）

| disposition | count |
| --- | ---: |
| FIX_APPLIED | 64 |
| FIX_REMAINING | 36 |
| KEEP | 2185 |

### 本轮已修（写入/供料自由正文，摘）

- `action_materialize` body/title：保原文，判空用副本
- `declaration_dispatch` 密令 title/content：保原文
- `audience_translate.build_pending_summaries`：去掉 `[:60]`
- `web_app` 召对 message / 旨意 PATCH：保原文
- `web/src/useChatActions.ts` / `useEdictActions.ts`：去 trim 写库
- `db.merge_execution_note` / `person_logs` 摘要裁剪：保原文
- `issues` execution note、`credit_events`/`relations` context·origin、`cli_backend` draft/secret assemble、`cli/terminal` 指令输入、`staged_declaration` forecast_text：保原文
- 前序已修：region/army/building/power log reason、HITL label、surcharge reason 闸等

### 实际剩余

见 `f16_hand_member_table.tsv` 中全部 `FIX_REMAINING` 行（当前 36）。**不声称 F16 全清。**

---

## 2. F3「测试清理再次误删独立契约」

### 双向历史复核（完整命令与成员表）

路径：`f3_bidirectional_member_table.md`（自 `evidence/1834-fixer-f3-f14/f3_bidirectional_independent_contract_member_table_HEAD.md` 复制并追加本轮恢复注记）。

表内含：`git log` / `git show` / `git diff 52809cdf3 HEAD` 等命令原文 + 删除侧成员逐项 RESTORE_OK / 先前 MISSING。

### 本轮恢复（原 MISSING，outcome/空 chrome 不蕴含）

| 断言 | 文件 |
| --- | --- |
| `"参与人" in capsys.readouterr().out` | `tests/test_decree_dossiers_571.py` |
| `"不足额" in execution_note`（在途+即时） | 同上 |
| `"应拨10两"` / `实拨{n}两` | 同上 |
| `"名实已乖" in execution_note` | `tests/test_dossier_reported_progress_619.py` |
| `recent_context == "后事。（天启六年二月）"` | `tests/test_relation_seed_638.py` |
| `"人物终态：dead；途中病故"` | `tests/test_secret_order_monthly_progress_566.py` |
| `not.toMatch(/臣.*叩见\|恭请圣安/)` | `web/src/components/modals.test.tsx` |

经典：`assert "许誉卿" in _gatekeeper_names(after)` 仍在 `test_promulgation_judge_561`（L692）。

---

## 3. F3-R「语义复核被自动 KEEP 代替」

### 撤销

- `f3r_hand_member_table.REVOKED_AST_AUTO.txt`（04b62b858 自动层）
- 历史 four-class / dispose 脚本：见 `F17_F3R_REVOCATION.txt`（历史输出未改写）

### 枚举（只枚举）

`enum_f3r_py_all_candidates.txt` + `enum_f3r_js_all_candidates.txt`（`scripts/enum_f3r_ast.py`）

### 手核表

`f3r_hand_member_table.tsv`（由 `f3r_semantic_batch{1,2,3}*.tsv` 合并 + 本轮 FIX_DELETED）

| disposition | count |
| --- | ---: |
| FIX_DELETED | 12 |
| KEEP | 377 |

质量自检：截断 `A=test_…` 主体 = 0；`intervening=assign@` 自动层 = 0。
本轮新删真重复：forecast `calls==[1]` 尾断言、deformation `execution_outcome` 重申、`mutiny_loyalty_cap` 后置、`observed=={…}` 后置、`tend_u has_upright_auditor` 后置（及前序 5 项）。

---

## 4. F17

| 项 | 处置 |
| --- | --- |
| 永久 `mutation_real_old_red.py` / `probe_new_green.py` | 已删；历史 JSON + `*.REVOKED_METHOD.txt` 保留未改写 |
| 证明 | 临时进程内替换旧 strip 实现 → `mutation_temp_real_entry.json`（含 entry_points + old_logic_restore） |

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
  -q -p no:cacheprovider --tb=line
```

结果（`pytest_focus.txt`）：**470 passed in 14.17s**

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
诚实：`git diff --check ee3b5da31 -- evidence/.../vitest_focus.txt` → `new blank line at EOF`（原始输出尾空行保留，未为过 check 而篡改）。

邻票 `test_commitment_progress_contexts_are_structured` NameError 依判词交 #1873，不夹入。

---

## 6. 临时真实入口变异（可核）

文件：`mutation_temp_real_entry.json`

| 项 | 内容 |
| --- | --- |
| 入口 | `normalize_commitment_stages`；`parse_decision_blocks`；`apply_region_deltas`→`region_logs.reason`（经 `_seed_opening_db`） |
| 装回旧逻辑 | 进程内 monkeypatch 为 local `old_normalize`/`old_parse`（`.strip()` 自由正文），比较后恢复原符号；**无永久证明脚本** |
| 观察 | current staged/decision preserve=true；old preserve=false；region reason length=109 含「禁再向百姓加派。」 |
| verdict | `true`（本机本次临时跑通；**不据此宣称 F16 全类结清**） |

历史 `mutation_old_red.json` / `probe_new_green.json` 字节保留 + `*.REVOKED_METHOD.txt`。

---

## 未结（诚实）

- F16：`FIX_REMAINING=36`（见处置表）；不以 KEEP 行数冒充全清。
- F3-R：手核表已重建；不声称「无剩余真重复可能」——仅对枚举候选集逐项记账。
- `git diff --check ee3b5da31 HEAD`：`vitest_focus.txt` EOF blank **未净**。
- 未跑全量；未 stash/amend/push/PR。

自查二连 done。
