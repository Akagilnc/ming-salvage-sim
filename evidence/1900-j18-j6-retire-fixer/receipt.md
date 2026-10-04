# #1900 修内司施工回执（J18 + J6 续修）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
分支：`ak-roles/1900-j18-retire-revoked-mechanisms`
底座续修前 HEAD：`ac76923f4`
既存 `?? .baseline/` 未动；无 stash / amend / rewrite / push / PR。

未结类别以末份判词 continue payload 为准：J18（P1）、J6（P2）。
本轮针对复核指摘：J6 谓词收窄、泛化保留无逐成员核、缺全仓成员表。

---

## 1. J18 行为形状（不止旧符号）

### 类定义（未收窄）

撤去旧处方新造的暗护双载体承接、专用实况账本、聚合、专用资格校验及其记录/核算/供料/恢复配套；不另造替代机制。

### 本轮补删（上轮符号复扫空后的行为形状残留）

| 成员 | 处置 |
|---|---|
| `materials._world_board_text` 的 `hasattr(escort_route_ledger_text)` 兼容读口 | 删除 |
| `month_chain._escort_route_facts` 恒空 `escort_routes*` 注入 + 供料 instruction 点名 escort_routes 账本 | 删除函数与注入；instruction 改为据关联/核账事实 |
| `decree_forecast._append_this_decree_escort_grounding` 的 `escort_link` 双载体目录行 / `sources` 形参 | 删除；仅保留本旨自带押解标记 |

### 复扫

见 `j18-behavior-rescan.txt`：生产+测试空；仅 `DELTA_SCHEMA` 已退役标题。

### `escorted=False` 核验

`list_monthly_grant_reconciliation_targets` / `grant_route_reader_facts` / `test_grant_reconciliation_567` 中 `escorted is False` 记录本切片退役后的无护口径与家族接续缺口（#1873），不是把「永远无护」写成新玩法契约，也不恢复旧软判实抵。

---

## 2. J6 全仓成员表 + 逐成员语义处置

### 类定义（未收窄）

非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向不可盲删；原文无损 ≠ 拼装措辞锁。

### 枚举（原完整谓词 / 保守全集，非 named-shapes）

命令见 `j6-enum-cmd.txt`。

| 项 | 值 |
|---|---|
| 全集 | **2886**（Python test 函数 2602 + web it/test 块 284） |
| 逐成员表 | `j6-all-members-disposition.json` |
| 可读索引 | `j6-disposition.md`（逐 reason 完整成员列表，可核） |

不另立自由文本正则生产机制；冻结分析脚本只写证据，不进运行时。

### 本轮代码删修（真 J6 / 同形）

| 成员 | 处置 |
|---|---|
| `test_settle_path_triggers_reconcile_before_next_period` spy `recompute_all` 只锁 calls/turn | 改为 `_settle_empty_month` 真入口 → `faction_leverage` 去 sentinel |
| `test_rank_rule_offset_reanchor_*` 调 `_rank_rules_562_legacy_weight_sum` | 去掉私有 helper；公开高 offset + 外部 leverage |
| `test_character_knowledge_*` 断言 `_office_archive_key` | 删除私有 key 断言；保留 `list_referenceable_dossiers` 可见性 |
| `test_review_issue_reaches_staged_directive_default_approval` `calls == ["enter_review"]` | 只保留 `review_directives` 返回 `"issue"` |

上轮已处置的点名样本（six_sciences / promulgation power_band / meta flag）保持外部结果契约。

### 逐成员保留 reason（可核，非 5 条空泛类别）

直方图见 disposition；每成员一条 reason，完整索引在 `j6-disposition.md`：

- `R_live_entry_result` / `R_gate_negative_live` / `R_gate_shape`
- `R_external_boundary`（LLM/Popen/传输边界）
- `R_persisted_projection_after_live_entry`（月链落库投影读）
- `R_ui_lifecycle_gate` / `R_web_ui_callback_contract` / `R_web_ui_or_unit_no_j6`
- `R_no_j6_signal`

语义覆核后开放 J6 计数：**0**（见 disposition summary）。

### 变异

- `j6-mutation-red.log`：吞掉退场后 leverage 回算 → `assert 28 < 28` FAILED，exit 1
- `j6-mutation-green.log`：现行实现 1 passed

---

## 3. 聚焦测试

七变量均 `/usr/bin/false`。见 `focused-round2.log`（需 `git add -f`）：

`236 passed in 11.74s`（escort / grant recon / six_sciences / promulgation / faction / office_rank / character_knowledge / cli_play_turn / month_chain_1847 / decree_forecast / relation_capture / web_court_visibility）。

未跑全量。

---

## 4. 自查

- 类定义未收窄；全集 2886 逐成员有 action/reason。
- J18 行为形状复扫仅失效说明。
- `escorted=False` 仅为退役口径/缺口记录。
- 未 stash/amend/rewrite/push/PR；`.baseline/` 未动。
- 自查二连 done。

## 5. 未结项（如实）

- 不自行宣布 merge / 关票 / converged。
- 有护核账与暗护玩法接续仍归家族收尾 / #1873。
