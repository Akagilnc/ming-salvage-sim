# #1843 修内司回执（w5 / F2-R12 continue T1+T2）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r12-f2`
基线 HEAD（施工前）：`3670caaa04ea3db04b7a5916a0b048cba7c71505`
裁文：本票 `run-state.json` → `currentCourt.summons.instruction`（冻结副本 `artifacts/latest-court-continue.json`）
未 amend / stash / push / PR；七 `MING_SIM_*_BIN=/usr/bin/false`。不跑全量。F2-R12-2/-4 已核结，不另扩。

## T1 ensure_column 补列阶梯

探针（空库构造 GameDB，包装 `ensure_column`）：施工前 162 次＝126 CREATE 已含空操作 + 36 真新增；施工后 **36 次真新增、0 空操作**（`evidence/1843-w5-r12-ensure-column-probe.json`）。

处置：
- 删除「新档 CREATE 已含该列」的 `ensure_column` 调用与 powers/`origin_ref` 日志表循环，以及仅服务旧库的 `office_change_records.turn` DROP 阶梯。
- **保留** `ensure_column` 本体与 CREATE 之后才真正新增的 36 列初始化。
- 删除专属旧库夹具 `test_undo_survives_db_created_before_undone_at_column`（DROP 列再期望重开补列）。
- 未整删 `ensure_column`。

### 相关旧档措辞残留（按消费关系，不按词删）

| 位置 | 结论 |
|---|---|
| `db.py` 成案来源轮载荷回落 | **保留**：无 pending 的直写路径现役消费；注释已改为「现役直写接缝」说明。 |
| `army_pay.py` / `constants.py` 引用已删 `_backfill_salary_rate` | **改注释**：结算咽喉锚定仍现役；删死引用措辞。 |
| `appointment_tenure.normalize_appointment_tenure` | **保留**：缺备档/空任别读端兜底，非旧库缺列迁移。 |

## T2 洗职单一权威

授权：数据为名分真源，删重复 runtime 洗职；保留数据修正与 load 离事空 office 合法读取；不解析 `status_reason`。

处置：
- `content/characters.json` 既有离事清空保持（数据真源）。
- 删除 `wash_ousted_current_office` 整函数及 `load_character_content` / `seed_static_data` 两处调用。
- load：离事者允许空 `office` 合法读取；在事者仍 `str_field` 必填。
- seed：只落库 content，不再二次洗职。
- 未引入任何 `status_reason` 解析。

## 聚焦测试

完整命令见下方「命令」。无 `-k` deselect。

- collected：**238**
- deselected：**0**
- 结果：`3 failed, 234 passed, 1 skipped in 3.28s`（wall `real 3.73`）
- 日志：`evidence/1843-w5-r12-t1t2-pytest.log` / `evidence/1843-w5-r12-t1t2-collect.log`
- 三红（与上轮同因，**归 #1873 待汇总，不恢复旧功能**）：
  1. `test_r4_named_characters_debut_in_historical_order`
  2. `test_restoration_and_displaced_third_state_use_latest_historical_office`
  3. `test_seed_archives_clean_historical_office_for_dismissed_ministers`

## 自查二连

- 同类型：旧库补列按 CREATE 已含 vs 真新增核对退役；洗职双权威收为数据单源。
- 引入 bug：未删 ensure_column 本体；直写载荷回落与缺备档任别读端保留；不解析 status_reason。

## HEAD

`cdd29c39f04f18559b2e2cff58e1b93b133f399e`

## 命令
```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_person_delta_adapter.py \
  tests/test_population_unit_648.py \
  tests/test_population_transfers_649.py \
  tests/test_person_archive_contract_index.py \
  tests/test_named_characters_seed_484.py \
  tests/test_office_inference.py \
  tests/test_office_rank_562.py \
  tests/test_audience_undo_506.py \
  tests/test_faction_leverage_9.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_army_firearms.py \
  tests/test_region_citydefense.py \
  tests/test_person_archive_schema.py
```
