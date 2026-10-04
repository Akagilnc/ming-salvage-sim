# #1835 w5 修内司回执（fixer）

本轮只交修理提交，未 merge、未 push、未开 PR；不宣告关票。不提交终局回执（由驱动 session 汇验）。

## 授权与法源

- 任务包：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108ff-575c-70a9-a4e6-3f226f700bcf@fixer/fix-packet.md`
- 冻结判词末份：`attachments/02-1835-judge-e22cba1e3.json` → `outcome.payloads[-1]` 七类未结
- 票面：#1835 / #1812 / #1901；ADR 0150、0008、0015、0142、0154

## Advisor 自审（执行前）

1. 不新造机制：平行核归一到既有接缝（situation_drift / displaced_population / entities.*）；拒收走既有返回通道；不造递归收集器/护栏/识别层/自然归档。
2. 官方优先检索：Python `str.strip` 保留原串、副本判空（docs.python.org）；frozen dataclass `FrozenInstanceError`（docs.python.org/dataclasses）作独立进程变异标尺。
3. 验收以 #1812「复杂度/旧路退出」为主；测试红与功能接线次要，缺口如实记。

## 枚举命令（七类定义全文，未收窄为点名样本）

修前完整转储：`evidence/issue-1835/pre/enumeration.txt`  
修后复扫：`evidence/issue-1835/post/enumeration.txt`

```sh
rg -n "def (_apply_metric_dict|apply_metric_dict|_apply_economy_list|apply_levy_driven_transfers|_apply_levy_driven_transfers|apply_issue_inertia_and_ongoing|apply_situation_monthly_drift|apply_recovery_driven_transfers|_apply_recovery_driven_transfers)" ming_sim -g "*.py"
rg -n "apply_issue_inertia|_apply_levy_driven|situation_drift|displaced_population|recovery" ming_sim/month_chain.py
rg -n "_apply_issue_entities|_ISSUE_PSEUDO_EVENT|_monthly_economy_items|_spawn_legacy_from_effect" ming_sim/issues.py
rg -n "backlash_results|backlash_rejections|\.pop\([\'"]backlash" ming_sim -g "*.py"
rg -n "ordinal:|def ordered_sections|def section_for_delta_key|caller_transaction" ming_sim/settlement -g "*.py"
rg -n "def describe\(|test_victory_status_is_set|test_ongoing_outcome_carries" ming_sim/settlement/views.py tests -g "*.py"
rg -n "declare_closed|close_from_declaration|ATTACH_RESULT_CLOSE|事务尚有未了" ming_sim/entities/affair tests -g "*.py"
rg -n "STAY_ATTEND_COMMANDS|AMBIGUOUS_CLOSE_COMMANDS|陛下是要退朝么|stay_attend_in_audience|recognize_audience_command" ming_sim tests -g "*.py"
rg -n "resolve_condition|fail_condition|\.strip\(\)" ming_sim/materials.py
```

## 逐类根因、成员与处置

### 1. 旧核、兼容桥及合并后的平行路径未退出（完整性C1）

- **根因**：#1901 已抽出 `situation_drift` / `displaced_population` / `entities.population.recovery`，但 `month_chain` 仍调 `issues` 旧核；`situation_drift` 仍 import 已退役的 `flows._apply_*`；`issues` 保留 re-export 与平行 inertia/levy；`flows` 保留重复 metric/economy 核；`displaced_population` 与 entity recovery 双持回流。
- **成员（修前）**：见 pre 枚举——`flows._apply_metric_dict/_apply_economy_list`；`issues.apply_issue_inertia_and_ongoing/_apply_levy_driven_transfers` 与 re-export 七符号；`situation_drift.apply_situation_monthly_drift`；`displaced_population.apply_levy/apply_recovery`；`entities.population.recovery`；`month_chain:625/1411/1859`。
- **修复**：月链改调 `apply_situation_monthly_drift` + `apply_levy_driven_transfers`；drift 改接实体 economy/metric/issue.effects；删除 issues 平行 inertia/levy/re-export/commitment 平行 resolve·expire·ongoing；删除 flows 重复核与 displaced 回流副本；issues 终结效果懒委托 situation_drift。测试/decree 迁约至新入口。
- **例外**：`declare_closed` store 方法仍供夹具/将来自然归档读改（本切片不新造自然归档）；`run.py` 局部 `caller_transaction` 仍承重（判词明示除外）。

### 2. 拒收仍藏在成功载荷（完整性C2）

- **根因**：`character/apply` 把 `backlash_rejections` 塞进 applied 的 `backlash_results`；多处 `.pop("backlash_results")` 特殊搬运。
- **成员**：`character/apply.py` 嵌套写入；`character/delta_section.py`、`issue/delta_section.py`、`issue/effects.py`×2 pop；`settlement/preflight.py` 嵌套扫描；log 过滤键。
- **修复**：拒收改 `rejections.extend(backlash_rejections)`；删除全部 pop 桥与 preflight 嵌套扫描。

### 3. 无消费者接口与冗余运行态（完整性C3）

- **根因**：`SectionSpec.ordinal`、`ordered_sections`、`section_for_delta_key`、`SettlementRun.caller_transaction` 无读取。
- **修复**：删除上述死字段/函数及 `__init__` 导出；保留 `apply_person_changes_only` 局部 `caller_transaction`（判词除外）。

### 4. 平行证明测试及仅测试消费的生产摘要（完整性C4）

- **成员**：`tests/test_settlement_fixed_point_1835.py`（两案）；`settlement/views.describe`（仅 person_delta_adapter 断言消息）。
- **修复**：删测试文件与 `describe`；断言消息改用既有 `view()`。

### 5. 已撤销的事务 close 动作及守门（正确性C1）

- **根因**：affair delta_section 解析 close、未了局势守门、`declare_closed`；`close_from_declaration` 同形。
- **修复**：段改为空允许集通用拒收，不执行 close、不查未了；删除 `close_from_declaration` 与 close 词表默认准入；保留 store.`declare_closed` 供夹具（不新造自然归档）。既有 `test_affairs_1831` close 拒收契约仍绿。

### 6. 退役自然语言口令与固定台词（正确性C2）

- **成员**：`STAY_ATTEND_COMMANDS` / `AMBIGUOUS_CLOSE_COMMANDS`；`recognize_audience_command` 分支；`stay_attend_in_audience`；session 含糊确认 cue「陛下是要退朝么？」；CLI 留侍分支；专属测试 `test_scene_stay_attend_*`。
- **修复**：全部删除；明确「退朝」封闭集保留（不扩张删除无关系统退朝口令）。
- **例外**：历史账标签 `TAG_STAY_ATTEND` 仍可投影旧账（只读标签，非口令识别层）。

### 7. 供料裁剪模型条件原文（正确性C3）

- **根因**：`materials._visible_affair_lines` 对 resolve/fail_condition `.strip()` 后写入材料。
- **修复**：保留原值；消费端判空用 `.strip()` 副本。

## 聚焦测试

强制前缀七 BIN=/usr/bin/false。

```sh
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  .venv/bin/python -m pytest -q --tb=line \
  tests/test_declaration_dispatch_1835.py tests/test_affairs_1831.py \
  tests/test_person_delta_adapter.py tests/test_rejection_wiring.py \
  tests/test_month_chain_1847.py tests/test_issue_entities.py \
  tests/test_audience_translate_1837.py tests/test_material_directory_1830.py \
  tests/test_population_transfers_649.py tests/test_commitment_backlash_626.py \
  tests/test_section4_rejections.py tests/test_decree_commitment_settlement_229.py \
  tests/test_style_temperament_641.py tests/test_effect_origin_558.py \
  tests/test_deformation_dual_rail_622.py tests/test_fiscal_beyond_intent_1260.py
```

结果（实查）：`392 passed, 1 skipped in 9.64s`（wall `real 10.12`）。日志：`evidence/issue-1835/post/focused-final.txt`。未跑全量。

## 变异证据

独立进程 `/tmp/1835-w5-mut/mutate_probes.py`（不改工作树）：见 `evidence/issue-1835/post/mutation-probes.txt`，7/7 PASS（C6 cue 缺席、C7 strip 红/恢复绿、C2 通道、C1 接线、C4 FrozenInstanceError、C5 段无 declare_closed）。

## 剩余范围 / 缺口

- 家族复杂度对比、全量 CI、真宿主验收留家族收尾。
- `ATTACH` close 词表与 `declare_closed` 夹具方法仍在 store；自然归档未建（授权不要求）。
- `TAG_STAY_ATTEND` 只读投影保留。
- 未向 #1873 代登本轮功能缺口（判词要求调用方补交，非本施工处方）。

## 约束遵守

未 amend / rewrite / push / PR / stash；未改宪法/Soul/宿主配置；未新造兼容桥/递归拒收收集器/护栏/识别层/证明性测试。
