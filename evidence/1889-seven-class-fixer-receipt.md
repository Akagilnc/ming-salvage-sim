# #1889 七类修内司回执（末判 6b513b99f）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-seven-class-fixer`
- 判词真源：`…/attachments/05-1889-judge-6b513b99f.json` → `outcome.payloads` **末份**
- 开工基线：`6b513b99f`
- 约束：无 amend / rebase / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦；不新建证明测试/护栏/兼容/功能补齐；不改治理/Soul/宿主/SDK/席位；不碰既存存档

---

## 授权未结类（末判原文类名）

K4 / K1 / K5 / K8 / K9 / K3 / K7

---

## 可复跑枚举

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
# 谓词脚本（系统临时目录；覆盖票面类定义全文，非点名白名单）
python3 /tmp/1889-seven-enum/enumerate.py
# 修后成员表真源
# evidence/1889-seven-class-member-disposition.tsv
```

### 修后残差谓词复扫（ming_sim + tests + web_app.py）

| 谓词 | 命中 |
|---|---|
| `scale_tian_fu\|read_scale_tian_fu` | 0 |
| `callable(_commit) and not callable(_conn)` | 0 |
| `default_terminal_reason` | 0 |
| lenient `excluded_*` try→`[]/{}` | 0 |
| `Close only by explicit declaration\|close_from_declaration` | 0 |
| `Internal Server Error\|KEEP_P4_ABSENCE`（tests/evidence 处置已撤销） | tests 生产断言 0 |
| `_agno_legacy_runs_blob\|_rewrite_session…\|_decode_agno_runs\|merge_runs_table_with_legacy_blob` | 0 |
| `secret_order(?:_brief)?` accept-both regex | 0 |

修后 disposition 表：K1 KEEP=44、K5 KEEP=23（均为现役职责/保密负向/不同语义规则）；K4/K8/K9/K3/K7 残差 0。

---

## 逐类结果

### K4 — 退役财政标量路径

**类定义边界**：清退 tax_per_turn 残差标量链及其专属联动；保留现役 substrate hub、辽饷/盐税/商税 dynamic 旁路与人口核算；不补税改功能。

**处置**：
- DELETE `GameDB.scale_tian_fu`、`RegionStore.read_scale_tian_fu`
- DELETE `remove_fiscal_item` / `_write_fiscal_config_change` 的「田赋→标量」分支
- KEEP `apply_dynamic_fiscal_scale`（辽饷/盐税/商税）及 `test_section_fiscal_rejections` 辽饷好路案

**复扫**：scale API = 0。

### K1 — 被取代来源 / 旧存储兼容

**类定义边界**：清退应用侧旧兼容；保留保密负向与现役恢复；不删存档、不改 SDK/宿主。

**处置**：
- `_SECRET_ORDER_SOURCE` → 仅 `secret_order_brief:(\d+)`
- 删除 Agno2 `sessions.runs` blob 解码/合并/回写；`agno_runs_length` / truncate 只认 `agno_runs`
- DELETE 专属旧 blob 测试：`test_legacy_agno_sessions_runs_blob_*`、`test_logical_history_matches_agno_merge_*`、`test_reconcile_blob_baseline_*`、`test_truncate_migrated_overlap_*`
- KEEP 保密负向；知识用例注入源改为 live `secret_order_brief:`（非恢复 bare 兼容）
- KEEP `SECRET_ORDER_ORIGIN_PREFIX`（案卷 origin_ref，非 knowledge source 接受双形）
- KEEP `create_agno_db` 的 agno_runs 钉选注释

### K5 — 同一持久规则双份权威

**类定义边界**：收拢重复规则；不改事务边界；不把批量写退化成逐项提交。

**处置**：
- `read_ack_due_commitment_issue` → `row()`
- `_delete_pending_decision_rows` 单删规则；`clear` 仍自带 commit；`save_pending_decisions` 批量路径复用删规则
- `save_pending_promulgation_verdicts` → 先 `clear` 再批量 insert
- `_METRIC_UPSERT_SQL` 共享；`save` 仍 `executemany`，`upsert_metric` 仍单条
- `read_get_secret_order` → `secret_order_row`
- KEEP 不同生命周期/不同 status/不同 class 名的同形 SQL（与末判驳回 C6 一致）

### K8 — 宽松排除解码

**类定义边界**：删除吞错副本；复用严格真源；保留真实失败。

**处置**：`knowledge_items_for_turn` 改用 `_load_list` / `_load_targets`。

**既有入口变异**：损坏 `excluded_names='{broken'` → `ValueError 角色见闻名单 损坏`（红）；合法 `[]` → 归档可读（绿）。未新造测试。

### K9 — 未授权护栏 + 七份提交判别

**类定义边界**：拆除无消费者护栏与复制判别；遵循既有事务所有权。

**处置**：
- DELETE `content.py` `default_terminal_reason` 白名单 + `test_load_event_rejects_default_terminal_reason_outside_labels`
- DELETE 七处 `callable(_commit) and not callable(_conn)`
- 恢复既有提交所有权入口：`GameDB.append_chat_message`、`GameDB.clear_month_open_snapshot`（insert/delete + `conn.commit`；atomic 内仍 no-op）
- 调用方改回上述入口（非新增平行机制）

### K3 — 自由诊断措辞负断言

**类定义边界**：清理非契约诊断锁与错误保留依据；保留结构化/输入保真/真实闸负向。

**处置**：
- DELETE `tests/test_chat_stream_failpaths_393.py` 两行 `Internal Server Error` 缺席断言
- 撤销证据 `KEEP_P4_ABSENCE` → `DELETE_REVOKED_K3`（`evidence/1889-c6-member-disposition.tsv` / `group-review.tsv`）
- KEEP `_assert_structured_llm_http` 的 status/code/message/provider_message 契约

### K7 — 撤回机制过期说明

**处置**：`AffairStore` docstring 去掉「Close only by explicit declaration。」；不恢复显式了结、不建自动了结。

---

## 聚焦测试

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`。

```bash
../Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_section_fiscal_rejections.py \
  tests/test_audience_restore_505.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_event_trigger_gate.py::test_load_event_requires_latest_or_open_window \
  tests/test_event_trigger_gate.py::test_load_event_rejects_non_boolean_open_window \
  tests/test_character_knowledge_489.py \
  tests/test_affairs_1831.py \
  tests/test_rescript_draft_656.py::test_clear_pending_decisions_keeps_rescript_drafts \
  tests/test_promulgation_seam_560.py \
  tests/test_new_game_smoke.py
```

**实测**：`148 passed in 4.03s`（wall ~4.48s）。完整输出：`/tmp/1889-seven-focused.out`。

测试改动契约/成本：
- 删专属旧 blob / 护栏证明案（净减）
- 保密用例源 id 改为 live brief（最小必要，保负向语义）
- 撤销错误 KEEP_P4_ABSENCE 证据标签
- 未新增证明性测试

---

## Advisor 自查

- 无新增护栏/兼容层/平行恢复/自动了结/功能补齐
- K9 恢复的是被误删的既有提交所有权方法，不是新判别
- K5 保留 batch `executemany` 与 clear 的 commit 边界
- 未改治理宪法 / Soul / 宿主 / SDK / 席位 / 既存存档
- 未 amend / stash / push / 开 PR

---

## 证据路径

| 文件 | 用途 |
|---|---|
| `evidence/1889-seven-class-member-disposition.tsv` | 修后全员处置表 |
| `evidence/1889-seven-class-enum.tsv` | 修前/过程枚举 |
| `evidence/1889-seven-class-enum-raw.tsv` | 宽谓词原始扫 |
| `evidence/1889-c6-member-disposition.tsv` | K3 错误 KEEP 撤销 |
| `evidence/1889-seven-class-fixer-receipt.md` | 本回执 |
