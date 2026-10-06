# #1889 修内司回执（R1–R4）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 分支：`ak-roles/1889-seven-class-fixer`
- 约束：无 amend / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦

## 授权未结类

R1 / R2 / R3 / R4（判词 submission.latest.accepted.fix.classes）

---

## R1 持久读失败转正常空值

**谓词**：`except sqlite3.OperationalError` 后返回 `None`/`[]`/`0`/空成功，而非上抛；合法无行语义不在此列。

**枚举范围**：`ming_sim/**/*.py`

**成员与处置**：

| 成员 | 处置 |
|---|---|
| `GameDB._latest_held_user_chat_message_id` | DELETE 吞错，原失败上抛 |
| `GameDB._secret_origin_message_protection` 配对 turns 读 | DELETE 吞错 |
| `GameDB._withhold_origin_chat_messages` existing_ids | DELETE 吞错 |
| `GameDB.release_held_audience_knowledge` held_rows | DELETE 吞错 |
| `ReignStateStore._current_open_night_id` | DELETE 吞错；合法无夜仍返 0 |
| `issues.py` trigger_gate no-such-column → ValueError | KEEP：fail-loud 文档化转抛，非空成功 |

**复扫**：`except sqlite3.OperationalError` 仅剩 issues.py 两处 fail-loud。LIVE DELETE 残差 0。

---

## R2 散文判月与拆改正文

**谓词**：从密令 `result`/`sim_note` 正文 split/去空行/前缀删行/regex 排序/startswith 月戳反推月份；或退役 `text_log_json` 正文账。

**枚举范围**：`ming_sim/**/*.py`

**根因**：密令进展把月份身份写进散文戳，再从正文反解析；与 0058/0073 结构化轨并存。

**处置**：

- 删除 `_append_secret_order_line` / `_has_secret_order_period_line` / text_log 死链
- 进展/核议/催办 → `record_dossier_progress`（`_note_secret_order_report`，origin 分 MONTHLY/REVIEW/RUSH）
- 推演 sim_note → `dossier_actual_progress.note`（保 units，不改正文列）
- materials 本月已推进改读 `dossier_progress` 结构化 turn+origin
- 正文列 result/sim_note 不再被进展路径拆改

**复扫（二轮）**：
- 同月替换按 `report_origin_base` 分身份，催办/核议/月报并存
- `sim_note` 只追加 `secret_orders.sim_note` 正文列，不创建 `dossier_actual_progress` 空单位行
- R2 谓词与身份混写残差 0

---

## R3 旧形状兼容 / 死实现 / 专属测试

**谓词**：对现役 SELECT 已含字段做 `in row.keys()` 缺列默认；无消费者死实现（text_log / 日期自动改名入口）；专属旧行为测试。

**枚举范围**：`ming_sim/**/*.py` + 对应 tests

**处置 DELETE**：

- `ReignStateStore.read` ended/ending_status 缺列默认
- `IssueStore._project_rescript_desk_row` rejection/opposition 缺列默认
- `staged_declaration` `_load_optional_json` / forecast_text 缺列分支
- `list_secret_orders` / `get_secret_order` due_turn/sim_note/excluded_* 缺列默认
- location / mutiny_probation / commitment_kind / origin_ref / stages_json / draft text 同类
- `apply_historical_power_renames` + `test_historical_power_rename_tick_reads_huangtaiji_event_effect`
- text_log 全链 + `secret_period_line` / `update_secret_order_assignments` 无消费者

**KEEP**：

- `apply_power_rename`（issues 事件 effect 现役）
- 合法 NULL/无行；dict 迭代 `.keys()`；character_knowledge PRAGMA 发现 participant_roster 表（非旧档缺列默认）

**复扫（二轮）**：清退 breach_plea/issues/decree/materials 缺列默认及悬空 `keys`；谓词命中 0。

---

## R4 内部形状 / 假主体 / 重复结论测试

**谓词**：mock 被测主体、inspect 签名、SQL trace 锁逐表恰好 N 次、仅保内部调用形状。

**删除**：

- `test_shadow_spine_uses_batch_bridge_without_per_region_reload`
- `test_history_projection_handlers_are_sync_for_sqlite_access`
- `test_closed_night_archive_batches_each_metadata_store_once`
- `test_read_night_scroll_reads_each_metadata_store_once`
- `test_pending_person_gate_prefetches_character_rows_for_displacement`
- `test_event_pool_pending_gate_reuses_shadow_prefetch_across_new_issues`
- `test_auto_trigger_historical_event_to_issue_uses_outer_transaction`
- `test_auto_trigger_historical_events_use_preloaded_terminal_refs`

**保留/复用**：既有真实财政落库/回滚案、夜档结果案、皇太极模型选择案、保密负向案。未新增平行证明测试；未改批量/事务契约。

**复扫**：R4 谓词命中 0。

---

## 测试适配（非新增证明案）

- `test_settle_due_keeps_existing_progress_result_over_memorial` → `test_settle_due_close_follows_surviving_memorial_and_actual`（进展走结构化轨，result 列不再被写）
- `test_emperor_private_payload_preserves_monthly_report`：保留 `memorial_text` 对测试自注入原文的存读保真；保留材料路径存在（承办人可读己方月报）

---

## 聚焦验证

```bash
MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
../Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider --tb=short \
  tests/test_new_game_smoke.py \
  tests/test_transaction_boundary.py \
  tests/test_db_broad_except_surface.py \
  tests/test_secret_order_isolation_883.py::test_976_secret_chat_turn_withholds_both_sides_but_public_turn_survives \
  tests/test_secret_order_payoff_1504.py::test_settle_due_close_follows_surviving_memorial_and_actual \
  tests/test_secret_order_payoff_1504.py::test_submit_unlimited_keeps_frozen_target \
  tests/test_secret_order_payoff_1504.py::test_rush_preserves_frozen_contract \
  tests/test_secret_order_payoff_1504.py::test_unlimited_investigation_due_now_reads_real_acquisitions \
  tests/test_decree_dossiers_571.py::test_secret_order_progress_persists_executing_until_terminal \
  tests/test_decree_dossiers_571.py::test_secret_order_progress_undo_restores_order_and_dossier_axes \
  tests/test_decree_dossiers_571.py::test_secret_order_progress_rolls_back_both_axes_in_outer_atomic \
  tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_commits_shadow_substrate_when_standalone \
  tests/test_fiscal_substrate_bridge.py::test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic \
  tests/test_fiscal_substrate_bridge.py::test_all_ming_settle_substrates_advance_on_fixed_flows \
  tests/test_fiscal_substrate_bridge.py::test_province_tick_shortfall_lands_fully_on_real_army_rows \
  tests/test_fiscal_substrate_bridge.py::test_new_dongjiang_army_makes_province_due_exactly_its_row_due \
  tests/test_event_trigger_gate.py::test_huangtaiji_chengdi_lands_only_when_model_picks_it \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_audience_scroll_539.py::test_history_turns_lists_every_closed_night_including_night_only_turns \
  tests/test_audience_scroll_539.py::test_closed_night_archive_derives_stable_titles_people_and_no_content \
  tests/test_secret_order_section_rejections.py \
  tests/test_secret_order_monthly_progress_566.py
```

**二轮聚焦**：`84 passed, 1 warning in 3.08s`（`/tmp/1889-r2r4-r2.out`，含判词点名案）

未跑全量；未改宿主/席位/存档；未 amend/stash/push。
