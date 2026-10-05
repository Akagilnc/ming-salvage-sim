# 1834 F21/F22 修内司回执（交卷证据根因纠正）

BASELINE: `ebcd2d1a168e46da52ccf7f3f898406b9e29e54f`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`
PRODUCTION（代码 FIX/DELETE 已落）: `66b88fa77f5158c8f015d97480803e798283dd3e`
（最终 SHA 见本轮 commit stdout；回执不 stamp HEAD）

## 本轮只修证据根因

1. **ENUM_CMDS.txt** 曾退化成搜固定保原文样本文字 / 具名已删列表 → 恢复可执行：
   - F21：全仓 broad `rg`（strip 带参 / re.sub / replace / split / join / slice）
   - F22：inline ~50 行一次性 Python AST（defs/fields + TS export/type + 引用计数，覆盖 zero/test-only）
   - 不恢复永久 `scripts/` 分类层 / 全量 jsonl
2. **test-only KEEP** 同句套话不可结清 → MEMBER_TABLE 逐条补具体测试 consumer 路径 + 现行职责；明示 KEEP≠已证全部现役
3. **mutation_real_entry.out** 曾只剩 current_green → 用 `/tmp` 脚本从 `git show ebcd2d1a1` 装完整旧函数入 mapper/物化/highlights 真实入口；old_red + current_green；脚本不入库

## 根因（生产语义不变）

- **F21**：人读自由字段不得 strip 改写落库；判空用副本。
- **F22**：退役零消费者专属结构删除后全仓复验；无退役证据不泛删。

## 枚举计数（本轮实跑）

| CMD | 结果 |
|---|---|
| F21 CMD1 broad | HIT_COUNT=2205 |
| F21 CMD2 strip-with-args | HIT_COUNT=10 |
| F21 CMD3 assign/append/return | HIT_COUNT=1146 |
| F22 inline AST | def_count=3349；zero_abs=51；zero_prod_test_only=69；py_files=118；ts_files=45；corpus_files=422 |

成员表：`MEMBER_TABLE.md`（F21 FIX 组 + 132 freeish 处置；F22 DELETE 表 + zero 候选处置；test-only 已列具体测试路径）。

## 真实入口旧红新绿

方法（临时 `/tmp/1834-f21-f22-r5/real_entry_mutation.py`，不入库）：
`git show ebcd2d1a1` 完整函数体 → `map_rescript_option_or_choice` / `_parse_highlights_json` / `_apply_military_order_station_effect` 真实入口。

```
old_map_src_chars=14279 old_parse_src_chars=420 old_apply_src_chars=1846
current_mapper_preserved=true current_hl_preserved=true current_materialize_preserved=true
current_materialize_station="  山海关  "
old_mapper_preserved=false old_mapper_station=山海关
old_hl_preserved=false old_hl_read=["辽饷"]
old_materialize_preserved=false old_materialize_station=山海关
current_green=true old_red=true
MUTATION_OK current_green_old_red real_old_funcs_from_ebcd2d1a1
```

完整 stdout：`mutation_real_entry.out`。不得伪称仅 rg 当前站点 intact = 真实入口证明。伪变异撤销见 `MUTATION_FAKE_REVOKED.txt`。

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
  -q -p no:cacheprovider --basetemp=/tmp/1834-f21-f22-r5/pytest-focus --tb=line
```

结果：`323 passed, 1 warning in 10.05s`（real 10.50s）→ `pytest-focus.out`

```
cd web && ./node_modules/.bin/vitest run --environment jsdom \
  src/appDurableWiring.test.tsx \
  src/components/drawers.test.tsx \
  src/components/situation.test.tsx \
  src/components/modals.test.tsx \
  src/staleGuard.test.tsx
```

结果：`Test Files 5 passed；Tests 158 passed；Duration 4.43s`（real 4.63s）→ `vitest-focus.out`

## 准确剩余 scope（不冒充全清）

- prod_zero_test_only / absolute_zero KEEP：已列测试 consumer 或公开表面职责；**未证明全部现役热路径**。
- 冻结 evidence 内旧符号叙述不改写。
- 本票其它未结类 / 接线票不在本回执范围。

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill/全量。
- 未新增永久分类层或永久证明测试。
- 自查二连：同类型（机械枚举 vs 样本文字哨兵；真实入口旧函数 vs current_green-only）；引入（证据纠正不改生产语义）。
