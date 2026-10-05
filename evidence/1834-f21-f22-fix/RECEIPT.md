# 1834 F22-R² 修内司回执（test-only 无本定义生产消费者 → 删）

BASELINE: `ebcd2d1a168e46da52ccf7f3f898406b9e29e54f`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`
（最终 SHA 见本轮 commit stdout；回执不 stamp HEAD）

## 本轮范围

- **只修 F22-R²**。F21 庭核已通过，不重开。
- 根因：成员表对 `prod_zero_test_only` 用「共享现役能力／模块有生产兄弟消费者」循环 KEEP；与判词「兄弟在用 ≠ 该定义在用；测试运行 ≠ 生产消费者」抵触。

## 根因与全类枚举处置路径

1. 读 MEMBER_TABLE / ENUM_CMDS / 本庭 F22-R² 判词。
2. 对表内每个 test-only 成员核 **该定义本身** 的生产引用（ming_sim/web_app/web/src；不含 tests）。
3. 无本定义生产消费者／动态注册／庭核排除 → DELETE 定义 + 专属测试；不误删仍被现役定义调用的共享 helper。
4. 级联复扫 absolute_zero helpers（generate_rescript_draft heal 链、audit 白名单、fiscal_fact_brief 整模块等）再删。
5. 重写 MEMBER_TABLE §F22：每个 KEEP 给本定义消费者具体 path 或明确排除（HTTP `@app.*` / scripts path / dunder）。
6. 聚焦测试（七 BIN=/usr/bin/false）；不全量。

## 枚举计数（F22-R² 实跑）

| CMD | 结果 |
|---|---|
| F22 inline AST recount | def_count=2794；zero_abs=20（HTTP+scripts hline+`__post_init__`）；zero_prod_test_only=29（全 HTTP）；py_files=116；ts_files=45；corpus_files=417 |
| ABSENT_CHECK 点名 | `settle_province_tick` / `get_message_highlights` / `list_dossiers_for_directive` / `generate_rescript_draft` / `value_axes` / `axis_collision_stances` / `matrix_snapshot` / `fiscal_fact_brief` / `IssueGroup` / `run_month_end_relation_brew` / `stage_month_segment` / `is_sealed` / `run_exclusive` 等 → hits=0 |

成员表：`MEMBER_TABLE.md`（F21 保留；F22 DELETE 表 + KEEP 均带本定义消费者 path）。

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
  -q -p no:cacheprovider --basetemp=/tmp/1834-f22-r2/pytest-focus --tb=line
```

结果：`429 passed, 1 skipped, 1 warning in 10.33s` → `pytest-focus.out`

```
cd web && ./node_modules/.bin/vitest run --environment jsdom \
  src/appDurableWiring.test.tsx \
  src/components/drawers.test.tsx \
  src/components/situation.test.tsx \
  src/components/modals.test.tsx \
  src/staleGuard.test.tsx
```

结果：`Test Files 5 passed；Tests 154 passed；Duration 3.80s` → `vitest-focus.out`

## 保留例外（每条有本定义依据）

- 装饰器注册 HTTP 路由（`web_app.py` `@app.*` 行）
- Protocol / dunder（如 `_PromulgationJudgeSession.__post_init__`）
- scripts / spike 本地定义（`hline`）；及本定义被 scripts 消费的 `require_fresh_cli_trace` / `get_pending_promulgation_verdicts`

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill/全量。
- 未新增永久分类层或永久证明测试。
- 自查二连：同类型（兄弟现役 ≠ 本定义消费者；专属测试随删）；引入（不误伤 HTTP/scripts/现役 normalize_*/dispatch_month_segment/MonthEndRelationBrewLeg/set_message_highlights 等）。
