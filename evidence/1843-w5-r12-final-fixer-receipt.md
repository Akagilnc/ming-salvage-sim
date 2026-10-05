# #1843 修内司回执（w5 / F2-R12 final recheck）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r12-f2`
基线：`52e2a2268`（F2-R12 residual）
本局 HEAD：见文末 commit（独立 `ak-roles:`，**禁止 amend / stash / push**）
未 push、未 PR；七 `MING_SIM_*_BIN=/usr/bin/false`。**不跑全量。**

## 调查结论（allegations 核实）

### 1. `seed_static_data` 空 `character_offices` 回填口

| 消费链 | 结论 |
|---|---|
| 新档 | `GameSession.__init__` → `seed_static_data`：`characters` 空 → 灌名册 → 同呼叫写 `character_offices`。**真新档 seed，保留。** |
| 既有档恢复 | 同入口每次打开都调；两表已有行则两侧跳过。**现役恢复不依赖「人有、备档空」回填。** |
| 旧档专属 | `characters` 已有行 + `DELETE character_offices` 再 `seed_static_data` 才触发空表回填——仅测试 `test_seed_backfill_skips_person_title_character_offices` 明文模拟。 |

处置：**收窄**为 `is_fresh_characters_seed` 门闩；source `存档迁移`→`静态接档`；**删除**旧档模拟专属案。新档 person-title 守卫仍由 `test_fresh_static_seed_person_title_character_no_offices_parent` 咬。

离事洗净后无现职：不建空备档；有现职／身份者仍走真实 `_record_character_office` 写口。

### 1b. 违宪修法撤除（相对 `145ce308a`，后续独立 commit）

主席 `git show 145ce308a` 指出并已撤除：

- 删除 `archived_office_title_for_ousted` 及其导入／seed 调用（`startswith('前')` / `split('，罢居/革职')` 解析自由文本 `status_reason`，违 ADR 0142／锚定宪法）。
- `apply_historical_debuts` 恢复至基线 `450a482bb` 既有实现；删除自 `status_reason` 回填 `office`／备档的新机制。
- 胡廷宴 `status_reason` 回退为 `延绥兵变弹压不力，革职候勘`（撤「前…革职」形以便解析的迁就）。
- 登场职衔洗净后无现职回填、离事历史备档缺口**如实留 #1873**，本轮不另造机制、不恢复全部旧功能。
- **禁止**任何新增 `status_reason` 文本分类。

前版回执曾正当化「自 status_reason 回收备档／登场回填」及据此宣称的绿证明——**作废**；见下「测试历史」保留当时命令与结果，并注明后续撤除后须重跑聚焦面。

### 2. 人口双口径残留

- `tests/test_population_unit_648.py`：F4/AC 旧档双口径说明删；废常量 `JIANZHOU_RESTORE_POP_WAN`；废 `auto_trigger_seed_issues` 导入。
- `tests/test_population_transfers_649.py`：legacy 万口径说明删；废 `LEGACY_*` 常量；废未用 `json`/`os`。

### 3. `current_title_kind` 与 transition

上轮把未仕/宗藩/后宫/外臣并进 `current_title_kind`，相对既有事件闸 nested 口径会扩 `resolve_person_transition`。本轮：

- `current_title_kind`：**收回**为 transition 旧口径（空职 / 显式身名分 / `PERSON_IDENTITY_TITLES` / `normalize_title_kind`）。
- 身份桶洗档留在 `wash_ousted_current_office`，复用 `WEISHI_OFFICE_TYPE` / `VASSAL_PRINCE_OFFICE_TYPE` +「后宫」「外臣」。
- **未改** `PERSON_TITLE_KIND_TRANSITION_OVERRIDES` / 矩阵。

### 4. substrate malformed 弱面（留 #1873，本轮不加测）

实测仍绿（隔离 no-op，非本轮缺口消失）：

- `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_container_isolated`
- `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_json_isolated`

日志：`evidence/1843-w5-r12-malformed-substrate-spot.log`。**不能以本轮没红称没缺口**；汇总归 #1873。

## 聚焦测试（七变量完整展开；无 `-k` deselect）

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
  tests/test_office_rank_562.py
```

### 测试历史（`145ce308a` 当时；**含违宪算法下的错误绿，不可再作证明**）

- **collected：175**（`evidence/1843-w5-r12-final-collect.log`）
- **deselected：0**（无 deselect 行；未使用 `-k` 名排除）
- 节点全表：`evidence/1843-w5-r12-final-nodes.txt`（175 行，无通配缩略）
- 结果：`175 passed in 2.46s`（`evidence/1843-w5-r12-final-pytest.log`）
- **后续撤除**：删 status_reason 解析备档 helper + 登场回填后，上列绿证明作废。

### 撤除后重跑（本 commit；七 BIN 全展开；无 deselect）

- **collected：175**（`evidence/1843-w5-r12-constitutional-collect.log`）
- **deselected：0**
- 结果：`3 failed, 172 passed in 2.38s`（`evidence/1843-w5-r12-constitutional-pytest.log`）
- 红（既有契约，未放松断言；**归 #1873 待汇总，不称已登记**）：
  1. `tests/test_named_characters_seed_484.py::test_r4_named_characters_debut_in_historical_order` — 洗净后 `office==''`，基线 debuts 不从 `status_reason` 回填；断言仍要史实职衔。
  2. `tests/test_office_rank_562.py::test_restoration_and_displaced_third_state_use_latest_historical_office` — 无解析备档 → `basis` 落 `first_appointment_high_office` 而非 `historical_office`。
  3. `tests/test_office_rank_562.py::test_seed_archives_clean_historical_office_for_dismissed_ministers` — 洗净后无现职者不建备档 → `character_offices` 无袁可立行。

### 测试文件（全列）

1. `tests/test_person_delta_adapter.py`
2. `tests/test_population_unit_648.py`
3. `tests/test_population_transfers_649.py`
4. `tests/test_person_archive_contract_index.py`
5. `tests/test_named_characters_seed_484.py`
6. `tests/test_office_inference.py`
7. `tests/test_office_rank_562.py`

## 自查二连

- 同类型：旧档空表回填 / 人口双口径文案常量 / transition 名分扩语义，按真实消费链处置；**不再**用 status_reason 文本分类补备档或登场现职。
- 引入 bug：收窄 offices seed 门闩只绑 fresh characters；清洗后无 office 者不造空／解析备档；debuts 回到基线，缺口留 #1873。

## HEAD

（commit 后填）
