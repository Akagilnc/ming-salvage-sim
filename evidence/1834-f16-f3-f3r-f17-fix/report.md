# #1834 修内司回执 · F16 / F3 / F3-R / F17（续修，末判 ee3b5da31）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**前序误交**：`e998bc2d4` / `712c4029d`（自动 KEEP 层 + 永久证明脚本，本轮撤销）
**本轮 commit**：`04b62b858d14b3efb77afdcb7d7db1feca375e88`

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 0. 自审纠正（相对 e998bc2d4）

| 问题 | 处置 |
| --- | --- |
| `dispose_f3r_semantic.py` 按 kind 自动 KEEP（IN_THEN_EQ_FULL / NOTIN_THEN_EQ_FULL / LEN_THEN_EQ / 全部 JS / adjacent duplicate）并冠 `hand:` | **删除脚本**；删除其产物 `enum_f3r_disposition.tsv` |
| `mutation_real_old_red.py` 275 + `probe_new_green.py` 110 永久平行证明 | **删除脚本**；历史 JSON 字节保留+`*.REVOKED_METHOD.txt`；权威证明改为临时入口替换 → `mutation_temp_real_entry.json` |
| F16 以 log-only 免除 `reason[:80]/[:120]` | **撤销该 KEEP**：`region_logs`/`army_logs`/`building_logs`/`power_logs` 的 reason 进入 `turn_*_summary` 与账本实况；属写入路径自由正文改写 |
| F3 仅 `git show 1e9b6d1b1` | 双向复核 89468d498→e998bc2d4 清理史 + 核实 `evidence/1834-fixer-f3-f14/` 历史表 |

---

## 1. F16「自由正文搬运仍改写原文」

### 扫描范围

```bash
rg -n "\[:\d+\]|\.strip\(\)" ming_sim --glob "*.py"
# 供料写路径：staged_commitment / settlement_payload / materials / month_chain /
# affair store / due_review / issues / db delta·logs·HITL·legacy
```

施工后仍见 strip/切片的 KEEP（非本类自由正文改写）：机器键/身份查找、路径身份、`stages` JSON 信封判空、`bind_decision_options` 键、局部 `if not x.strip()` 判空副本、console `tlog` 截断（不改写落库正文）、`person_logs` 整行转储已由 F12 移出供料。

### 本轮 FIX（写入路径自由正文）

| 成员 | 操作 |
| --- | --- |
| `db.apply_region_deltas` reason | 去 `.strip()[:80]`；空则回退 `event.title`，存 raw |
| `db.apply_army_deltas` reason | 同上 |
| `db.apply_building_deltas` / `remove_building` reason | 去 crop/strip 存 raw |
| `db.create_armies` / merge 扩军 reason | 去 `[:80]` |
| `db.apply_power_updates` reason/last_action | 去 `[:120]`；判空用副本 |
| `db` power rename log reason | 去 `[:200]` |
| `db.apply_character_power_changes` reason | 去 `[:120]` |
| `db` HITL choice label | 去 `[:200]` |
| `db.insert_legacy` / `issues` narrative_hint | 去 `[:200]` |
| `issues` surcharge reason | 去 strip+120 字拒写闸；存 raw |
| `db` joint-liability reason_text | strip 仅判空，不改写存文 |

前序已修（仍保留）：`staged_commitment` / `settlement_payload` / affair name·origin / due_review / initiative body 等。

### 临时真实入口变异

`mutation_temp_real_entry.json`：`verdict=true`；旧 strip 实现装回后 staged/decision `preserves=false`；当前绿；`region_logs.reason` 长度 109 全文含「严禁再向百姓加派。」。

---

## 2. F3「测试清理再次误删独立契约」

### 双向历史复核

覆盖提交：`89468d498` `7ab5e8dea` `f2ef16753` `ea2a01556` `7b70f4d51` `b6cd114f3` `96de23c8d` `888c33a9a` `1e9b6d1b1` `e998bc2d4`；并核实 `evidence/1834-fixer-f3-f14/f3_member_table.md`、`f3_deletion_side_member_table.md`、`rejudge-17-disposition.md`。

| 结论 | 说明 |
| --- | --- |
| `许誉卿 in _gatekeeper_names(after)` | 已在现行 `test_promulgation_judge_561` 保留；before==after **不蕴含**成员 |
| 1e9b6d1b1 / e998bc2d4 KEEP_DELETED | 仍由剩余全文 `==` 蕴含；无新的独立契约空洞 |
| 空壳 | 本轮触及文件无无断言用例 |

---

## 3. F3-R「语义复核被自动 KEEP 代替」

### 枚举（只枚举，不处置）

`scripts/enum_f3r_ast.py` 覆盖：`DUPLICATE_ASSERT`、`IN/NOTIN_THEN_EQ_FULL`、`EQ_THEN_IN_REVERSE`、`ISNOTNONE_THEN_EQ`、`LEN_THEN_EQ_CAND`、**新增** `LEN0_THEN_EMPTY_EQ`、`EQ_THEN_LEN`；JS weak/strong/dup；同函数无窗口上限。

现行计数：py 329 + js 51（删弱后）。

### 处置表（手核，非自动 KEEP）

路径：`evidence/1834-f16-f3-f3r-f17-fix/f3r_hand_member_table.tsv`

每行含：主体、操作/时点、蕴含结论。禁止 kind 默认 KEEP。

### 本轮删除的真重复

| 文件 | 弱断言 | 依据 |
| --- | --- | --- |
| `test_cli_backend` | `len(title)==len(long_title)` | `title == long_title` 蕴含 |
| `test_audience_undo_506` | `len(replies)==0` | `replies == []` 蕴含 |
| `decisionModal.test` | label/hint `not.toBe` 中旨串 | 精确 `toBe` 蕴含 |
| `decisionRouting.test` | `error not.toBe(PAUSED/"")` | `toBeNull` 蕴含 |
| `drawers.test` | `after.left not.toBe("")` | `after == dragged` 且 `dragged.left!=""` 蕴含 |

前序 e998bc2d4 已删的 equality-entailed 弱断言维持删除。

---

## 4. F17

| 项 | 处置 |
| --- | --- |
| 历史 four-class 假变异 / 源码措辞证明 | 见 `F17_F3R_REVOCATION.txt`；历史输出不改写 |
| 本树永久 `mutation_real_old_red.py` / `probe_new_green.py` | 删除 |
| 证明 | 临时进程内替换旧 strip 实现；结果 `mutation_temp_real_entry.json` |

---

## 聚焦测试

```bash
# pytest（见 pytest_focus.txt）
pytest：426 passed in 34.27s（pytest_focus.txt）
# vitest：190 passed / 7 files（vitest_focus.txt）
```

邻票 `test_commitment_progress_contexts_are_structured` NameError 依判词交 #1873，不夹入。

---

## 未结（诚实）

- 不以「成员表为空」冒充全清；以类定义 + 全谓词枚举 + 手核表为准。
- `person_logs` payload_summary 等审计信封截断：F12 已移出供料；本轮未扩为平行摘要层。
- 未跑全量；未 stash/amend/push/PR。

自查二连 done。
