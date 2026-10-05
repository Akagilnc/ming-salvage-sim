# 1834 F22-R 修内司回执（absolute_zero / 专属旧结构删除）

BASELINE: `ebcd2d1a168e46da52ccf7f3f898406b9e29e54f`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`
（最终 SHA 见本轮 commit stdout；回执不 stamp HEAD）

## 本轮范围

- **只修 F22-R**。F21 庭核已通过，不重开。
- 根因：成员表对「全仓只剩定义」用「零调用但无退役职责证据／公开 API 表面」循环 KEEP；与判词「没有消费者就是没有现行职责」抵触。

## 根因与全类枚举处置路径

1. 读全局仓级法 + 本树 `ENUM_CMDS.txt` / `MEMBER_TABLE.md` + PI 会话末份 F22-R 判词。
2. 全仓 inline AST 定义/引用扫描（stdlib+rg；无永久分类脚本）。
3. **先删 absolute_zero**（排除 HTTP 装饰器路由、Protocol/dunder、scripts/spike）。
4. **重扫**级联 dead helpers → 再删（`person_write_inventory` 整模块、`list_night_promulgated_directives`、`_authorization_*` 等）。
5. **test-only**：仅旧结构专属测试支撑者删结构+专属测试；共享现役能力（财政桥、写闸、拟旨、HTTP 等）KEEP。
6. 重写 `MEMBER_TABLE.md` §F22；更新 `ENUM_CMDS.txt` ABSENT_CHECK；聚焦测试。

## 枚举计数（F22-R 实跑）

| CMD | 结果 |
|---|---|
| F22 inline AST recount | def_count=3306；zero_abs=21（含 HTTP/scripts 排除项）；zero_prod_test_only=63；py_files=117；ts_files=45；corpus_files=421 |
| ABSENT_CHECK 点名样本 | `_collect_compliant_promulgation_items` / `apply_audience_turn_translation` / `mark_chat_turn_failed` / `stage_authorization_candidate` / `format_region_changes` / `person_write_inventory` / `status_delta_from_delta` → hits=0 |

成员表：`MEMBER_TABLE.md`（F21 保留；F22 DELETE 表 + 仍存候选完整处置）。

## 聚焦测试（七 BIN=/usr/bin/false；完整命令）

```
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1

../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_cli_play_turn.py \
  tests/test_audience_night_498.py \
  tests/test_audience_presence_500.py \
  tests/test_world_materials_1834.py \
  tests/test_material_directory_1830.py \
  tests/test_candidate_supply_1893.py \
  tests/test_cli_backend.py \
  tests/test_audience_translate_1837.py \
  tests/test_scene_llm_1836.py \
  tests/test_cli_transport_1465.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_highlight_judge_544.py \
  tests/test_pihong_dossier_1490.py::test_657_abi_mapper_matrix_a1_a12 \
  tests/test_promulgation_judge_561.py::test_leader_only_mutation_changes_faction_posture_not_roster \
  tests/test_faction_leverage_9.py \
  tests/test_execution_pressure_654.py \
  tests/test_section4_rejections.py \
  tests/test_power_section_rejections.py \
  tests/test_pay_order_override_653.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-f22-r/pytest-focus --tb=line
```

结果：`470 passed, 1 skipped, 1 warning in 11.69s`（real 12.20s）→ `pytest-focus.out`

```
cd web && ./node_modules/.bin/vitest run --environment jsdom \
  src/appDurableWiring.test.tsx \
  src/components/drawers.test.tsx \
  src/components/situation.test.tsx \
  src/components/modals.test.tsx \
  src/staleGuard.test.tsx
```

结果：`Test Files 5 passed；Tests 158 passed；Duration 4.03s`（real 4.22s）→ `vitest-focus.out`


## 保留例外

- 装饰器注册 HTTP 路由（函数名零 Python 调用属常态）
- Protocol / dunder
- scripts / spike 本地定义；及仅被 scripts 消费的 `require_fresh_cli_trace`
- 共享现役能力的 prod_zero_test_only（如 `settle_province_tick`、`SessionWriteQueue.*`、`generate_rescript_draft`、value_matrix 兄弟读口等）— 理由=真实现役架构职责，非「公开 API」空话

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill/全量。
- 未新增永久分类层或永久证明测试。
- 自查二连：同类型（循环 KEEP vs 零消费者即删；专属测试 vs 共享能力）；引入（删定义-only 不误伤 HTTP/共享管线）。
