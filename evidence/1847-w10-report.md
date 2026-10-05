# #1847 修内司 w10 交卷 — N11 旧档专属按行为拆净（同树续修）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w8-n11-n13-n14-n15`
- 底座 HEAD（动手前）：`da4e0ce79095e3f62fa3914478f2b99f717c5344`（w9）
- delivery commit：`e89e925ea953d048b3137835bdd58a1c58ef2646`
- 判词真源：`evidence/1847-w9-verdict.json`（N11-R2 / N11-X1 / N13-R2；本轮按续令纠正 w9 误上呈）
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- 禁止项遵守：未 stash / amend / rewrite / push / PR / SIGKILL / 全量 / 真模型；未改宪法、Soul、席位、宿主配置

## 续令要点（相对 w9）

w9 将 `ensure_column` 整段、`_FISCAL_MIGRATIONS`、faction offset 老档反推标为 ESCALATE。续令明确：

- **不得**以边界不清代替缺 owner 决定
- 上述三项必须核对函数体与新档 CREATE／初始化，按已授权「拆旧兼容」修净
- **唯一**合法阻断＝两明文法源相抵的人口单位（ADR 0088 vs 09-28 口谕）；逐字可核验上呈，不自裁
- 删旧档补列时：新档所需列并入 CREATE 权威定义、索引归位、保新档重开；不新增格式识别／拒收／迁移层

## 法源（阻断项核验指针）

| 法源 | 逐字要点 | 路径 |
|---|---|---|
| ADR 0088 | 「无标即按『万人』legacy 读写与展示；不得依赖 content 元信息判别」 | `docs/adr/0088-population-unit-persons-aligned-with-manpower.md` |
| 陛下 2026-09-28 口谕（ADR 0108 / 0152 引） | 「不考虑旧存档兼容，以前不，现在不，以后也不，除非哪天我明确说要考虑才开始考虑」 | queued_command uuid `64b7aa45-8865-4d2d-9495-dd1925545a08`；引于 `docs/adr/0108-intrigue-ability-substrate-column.md`、`docs/adr/0152-independent-manual-draft-entry-collapses-to-audience.md` |

两法源对「无标旧档万人 legacy 读写」相抵 → **BLOCKER unfinished**，不自拆。

---

## 本轮已完成

### 1) ensure_column 旧档补列 → CREATE 权威

- 将仍缺于 CREATE 的列并入建表定义（含 `game_state.ended/ending_status`、`characters` 肖像／affair、`factions.edict_overdraw/leverage_offset`、`pending_*`、`fiscal_config` 元数据列、`economy_ledger.beyond_intent`、三溯源 `beyond_intent`、`turn_reports` 标题／递话、`secret_orders.excluded_targets`、`story_ledger_entries.origin_ref`、`turn_directives.source_pending_action_id`、`relation_edge_events.affair_id` 等）
- 索引归位到 CREATE 旁：`idx_pending_actions_source_turn`、`idx_chat_turns_night`、`idx_ledger_origin_ref`、`idx_relation_edge_events_affair`、`idx_characters_affair`
- 删除 init_schema 内整段 `ensure_column` 调用与 `ensure_column` 方法本身
- 删除 `load_state` 对 `ended`／`ending_status` 的缺列软读
- 保留新档／现役共享：`_ensure_office_type_parents`、内容名册同步、退役表 DROP、实体 store、`init_fiscal_config` 调用
- 新档 smoke：CREATE→seed→reopen，列与索引在、校准标记在

### 2) 财政配置：初始真源保留，旧升版支链删

`init_fiscal_config`：

- **保留**：无 `__schema_version` → 自 JSON 整体 seed 一次
- **删除**：`_FISCAL_MIGRATIONS` 与 `cur < json` 逐版差量升版
- 已有版本号的库一律不碰（玩家状态神圣；不补旧档缺 key）

### 3) faction offset：新档校准保留，旧反推拆

- **保留**：`seed_static_data` → `_calibrate_faction_offsets(is_fresh_factions_seed=True)`（钦定 content 基线 − 权重和；落持久标记）
- **删除**：init_schema 内 `offset_col_added`／全 0 反推／缺标记补锚／float v2 升版；`_faction_offsets_all_zero`；参数 `offset_col_added`
- 已校准标记存在则早返（reload 不重锚）

### 4) 专属旧档测试删除／改挂

删除：`test_legacy_save_calibrates_offset_on_open` 及 crash/marker helpers、`test_old_save_migration_night_id_index_order`、`test_undo_survives_db_created_before_undone_at_column`、`test_fiscal_config_v8_migration_*`、mutiny／person_archive 旧档补列重开案。  
`test_half_weight_odd_baseline_no_round_drift` 改为直接写精确 float offset + recompute（不经旧反推入口）。

### 5) w9 已结项复扫（仍成立）

- N13-R2：`provider_message` 保留再追加 cause（未回退）
- N11-X1：seal 不可能护栏与 settle 双分支仍无
- purge／opening_gazette／maintenance DROP／payload 回落仍无

---

## 全仓旧档专属性复扫

### 枚举

```bash
# 标记索引（非结清事实）
# → evidence/1847-w10-scans/n11_old_archive_markers.tsv（93 行；生产 33）
# 行为分类表（结清用）
# → evidence/1847-w10-scans/n11_old_archive_members.tsv
```

谓词＝生产代码是否**只服务旧存档**（函数体／分支），非引用计数、非注释有「旧档」即删。

### 分类摘要

| 处置 | 成员 |
|---|---|
| DELETE_DONE | ensure 整段、财政旧升版、offset 旧反推、相关独占测试；w9 purge/DROP/回落/X1 |
| KEEP_SHARED / CONTENT_SYNC / TEST_READ | 新档 seed、内容名册同步、开局修正／关系 fresh 门、tenure 缺备兜底、config 白名单、runtime 饷率锚、合法测试读口 |
| BLOCKER_ESCALATE | **仅** `population_unit`／`scale_content_population_to_save_unit`／无标「万人」legacy（见上法源表） |

人口单位相关测试（`tests/test_population_unit_648.py`）随生产代码暂留，待 owner 裁决两法源后再处置。

---

## 聚焦测试（七 false；非全量）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  tests/test_cli_backend.py tests/test_month_chain_1847.py \
  tests/test_scene_llm_1836.py tests/test_audience_translate_1837.py \
  tests/test_cli_transport_1465.py tests/test_run_agent_text_transport_1465.py \
  tests/test_army_maintenance_retire_173.py tests/test_menu_lifecycle_drain_396.py \
  tests/test_new_game_write_path_1749.py tests/test_fiscal_substrate_bridge.py \
  tests/test_relation_brew_636.py tests/test_faction_brew_637.py \
  tests/test_faction_leverage_9.py tests/test_audience_night_498.py \
  tests/test_audience_undo_506.py tests/test_population_unit_648.py
```

实测：`453 passed, 1 warning in 24.72s`（`evidence/1847-w10-scans/focused_pytest.out`）

残迹：`self.ensure_column(` / `_FISCAL_MIGRATIONS` / `offset_col_added` → **NONE**（生产）

---

## 状态（如实；不宣告 converged）

| 项 | 状态 |
|---|---|
| N11-R2 ensure_column 旧档补列 | **已完成** |
| N11-R2 fiscal 旧升版支链 | **已完成** |
| N11-R2 faction offset 旧反推 | **已完成** |
| N11-X1 / N13-R2（w9） | **已完成**（本轮未回退） |
| N11-R2 人口万人 legacy（ADR 0088 vs 09-28） | **unfinished（BLOCKER 上呈）** |
| N14 / N15 | 判词已结清；未重开 |

**不用** `partial_completed`：除人口法源冲突外，本轮授权面已修净；人口项为合法拒绝自裁的 unfinished。

## 自查二连 done

- 同类：旧档专属按行为拆（CREATE 并列 + 删 ensure／升版／反推），未再误标「边界不清→上呈」
- 引入：新档 smoke 列／索引／校准；聚焦 453 绿；未加格式识别／拒收／迁移层；未碰宪法配置
