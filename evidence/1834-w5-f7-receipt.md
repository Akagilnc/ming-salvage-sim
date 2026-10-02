# #1834 W5 — F7 修内司回执

基点：`7593354622b9163a3e78b0a583d8452fa28e5ed4`。本轮只修 [P2]「已拍事务单文件取阅粒度未落实」。施工交卷不宣称已合并、关票或庭审收敛。

## 法源、边界及根因

已读全局规则、仓级 CLAUDE.md / AGENTS.md、CONTEXT 相关词表、ADR 0155 / 0073、两份冻结判词及派单；以 `gh issue view 1834 --repo Akagilnc/ming-salvage-sim --json title,body,comments` 核对现行票面。最终判词撤销先前 converged，不撤销 F1–F6 已补齐材料的事实。

源卷 `~/.claude/projects/-Users-akagilnc-WorkSpace-Ming-LLM-design/c7fcfe3c-854d-4bf9-b772-76faafc5178c.jsonl`：问题 uuid `ec7ed858-3c27-470e-a9ea-b08732fceead` 明列「起因、当前情况、文字事实按月、案卷、奏报、流水摘要，一事务一文件」，推荐理由「想查『宁远那件事』开一个文件」；owner uuid `12213109-4b27-44de-9da6-e64e17b4f843`：「q12 你的意思是api和cli行为就一致了？别的没意见」。已实际打开核对，不以 ADR 省略覆盖原话。

类定义覆盖本票授权世界目录内每一事务的起因、当前情况、按月文字事实、全部关联案卷、奏报、流水及实况历史；不按开放／关闭、案卷状态、月份、一般／密令、恢复状态或调用者收窄。沿关联与效果读口枚举全部来源，并检查人物目录同类写口；角色权限与公开作者既有排除不变。

根因：上一轮在共同 `_write_world_tree` 把关联历史按案卷、按双轨另写文件。内容可达不等于单文件取阅。最小恢复案从真实开事务、成案、写两轨、关闭事务、关库恢复进入真实备料与列目录：原逻辑列出 4 个文件，`assert 4 == 1`，`1 failed in 0.99s`。核对世界写口、人物／场景写口及恢复链，证实拆分发生在写树，而非恢复重复。

## 全仓机械枚举与成员表

修改前后都扫描材料载体；复扫另用全文类定义扩大候选词，不排除 archive、evidence 或其他目录：

```sh
rg -n 'def _safe_segment|def _material_facts_text|案卷/|当前情况.txt|_AFFAIR_DIR' --glob '*.py' --glob '*.md' .
git grep -n -E 'affair_id|affair:|origin_ref|事务|起因|当前情况|文字事实|案卷|奏报|流水|实况|list_dossier_progress|list_dossier_actual_rail|list_dossier_durable_effects' -- '*.py' '*.md' '*.json'
git grep -n -E '_AFFAIR_DIR|事务/|案卷/|当前情况.txt|prepare_world_materials\(' -- ming_sim tests
```

广搜复扫为 336 个文件、4140 个候选位置（新增本回执前）；词面命中包含 SQL transaction、测试、文档及过程记录，不将它们冒称缺陷。按来源／实际材料路径列全成员：

| 成员／写口／来源 | 处置 |
| --- | --- |
| affairs 身份、起因、状态；affair textual_facts 按月事实 | `_world_affair_lines` 的全事务投影不变，仍写 `事务/<键>/当前情况.txt`；开放开场子集不变 |
| decree_dossiers 原旨、人物、执行格与关联字段 | 全状态 `list_decree_dossiers`，改为追加到所属事务同一文件，不另写案卷子树 |
| decisions、endorsements、links | 原判决／背书／单向关联读口原样保留，随案卷收入同文件 |
| dossier_reported_progress；secret_orders.dossier_progress_json | 复用统一 `list_dossier_progress`，全部月份奏报收入该文件独立奏报层 |
| dossier_actual_progress | `list_dossier_actual_rail` 原样收入独立实况层，不与奏报认证或混算 |
| economy_ledger；fiscal_config_creations / changes / tombstones | 既有 actual rail → durable_effects 的来源与流水不变，随所属案卷收入同文件，不新增摘要 |
| decree_dossier_reconciliations | 原对账读口收入实况层，不另写碎片 |
| 人物／军队／地区文字事实、人物经历、公开说法、邸报 | 原独立对象载体不变；不是事务拆分文件，不复制到事务另造汇总 |
| 单人物 `_write_tree`；场景 `_write_scene_person_subtree` | 既有每事项一个当前情况文件；知识／权限投影不同于全知世界目录。本轮不把世界实况或双轨灌给人物 |
| 人物 `_write_textual_fact_files` 的角色可读事实；关联 issue 投影 | 按原角色可及范围供料，不是本票世界目录写口；保留，不扩展人物权限或重构邻票供料 |
| prepare_world_materials → `_write_world_tree` | 唯一世界发布写口修净，无第二套汇总机制或兼容碎片路径 |
| decree_forecast:152；month_chain:55 / 317 / 1235 / 1794 | 全部复用同一入口，无逐调用补丁 |
| 世界恢复用例、其他列目录／读文件测试 | 恢复用例改为断言事务路径集合只有一个文件并实际读取；其他结构化契约保持 |
| docs / archive / evidence 的历史记述；专项核账／撤令／检举等读口 | 过程记录不重写；专项输入不是世界事务文件，既有领域行为不改 |

复扫：授权世界目录事务仅一个写盘点；旧 `案卷/<id>/<层>.txt` 写盘逻辑删除，无平行汇总。每案先按事务键收集已有材料，再一次写出；同事务多案卷不会覆盖前案卷。公共作者 `exclude_dossier_ids` 仍在材料加入前执行。索引只有单个事务文件项。

## 验证

所有 pytest 与游戏探针均使用：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
```

聚焦命令：

```sh
../Ming_LLM/.venv/bin/python -m pytest tests/test_candidate_supply_1893.py tests/test_world_materials_1834.py tests/test_material_directory_1830.py tests/test_affairs_1831.py tests/test_faction_denunciation_627.py tests/test_gazette_author_1862.py tests/test_month_chain_1843.py::test_world_segment_reads_material_directory tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree tests/test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics tests/test_mechanical_tail_1845.py::test_chapter_memory_retired_from_three_readers -q -p no:cacheprovider --basetemp=/tmp/1834-w5-green
```

结果：`47 passed in 8.45s`。补充同前缀：

```sh
../Ming_LLM/.venv/bin/python -m pytest tests/test_public_projection_consistency_1830.py tests/test_fiscal_levy_effect.py::test_fiscal_levy_held_petition_is_supplied_to_next_world_segment tests/test_world_materials_1834.py::test_prepare_rebuilds_from_world_record_after_restore -q -p no:cacheprovider --basetemp=/tmp/1834-w5-supplement-corrected
```

结果：`4 passed in 1.84s`。一次补充命令误写 levy 用例名，`no tests ran in 0.46s`，纠正后以上结果才计为证据。未跑全量。

变异真跑，同七变量前缀，完整旧模块注入后才导入现行测试：

```sh
../Ming_LLM/.venv/bin/python - <<'PY'
import subprocess
import ming_sim.materials as materials
exec(compile(subprocess.check_output(['git', 'show', '759335462:ming_sim/materials.py']), 'old-materials.py', 'exec'), vars(materials))
import pytest
raise SystemExit(pytest.main(['tests/test_world_materials_1834.py::test_prepare_rebuilds_from_world_record_after_restore', '-q', '-p', 'no:cacheprovider', '--basetemp=/tmp/1834-w5-mutation']))
PY
```

旧逻辑：`assert 4 == 1`，`1 failed in 0.98s`。恢复当前模块同用例包含于两次绿色运行，无改历史或覆盖源码。

临时真实入口观察：复用本轮恢复用例独占临时库，追加第二份关联案卷与两个月两轨记录，重新 `prepare_world_materials → list_materials → read_material`；输出 `MULTIPLE_DOSSIERS_SINGLE_FILE 2 1`、`DATED_RAIL_ROWS 2 2`、`API_CLI_IDENTICAL True`（同文件 API 与 `/bin/cat` 读取相等）。原旨、起因、相互冲突的奏报／实况正文均在同文件中观察可达，不将正文观察写成机械断言或持久测试。首次探针漏调用 issues.bind_content，真实报错并停止；补齐既有 content 注入后重跑以上结果。

已直接打开绿色恢复用例材料观察：起因、关闭状态、原旨、案卷信息、奏报、实况及对账在同一个文件，未裁正文。编译两份触及 Python 文件：`Touched Python files compile: 2 PASS`；`git diff --check` 无输出。仓内无 Python typechecker，本轮不触 Web，不冒称类型检查。

## 质量、成本与剩余

互联网方向核对：`curl -L -s https://docs.python.org/3/library/pathlib.html -o /tmp/1834-pathlib.html`，官方标准库读取语义；仓内已有 `_material_facts_text` 与两轨统一读口足够，使用 Python dict/list 收集，不新造通用件、不引依赖或生态替代层。

生产 13 增 14 删，测试 3 增 7 删。测试最小必要成本：既有恢复用例以一个事务文件集合断言替代三份拆层路径读取；无新增测试函数、夹具、模型或网络行为，断言只落结构化目录契约，不约束正文措辞。没有新增账本、摘要、模型调用、身份规则或生产接线。无 Soul／宪法／席位／宿主配置改动；无 amend、stash、push 或 PR 操作。旧 F6 回执是过程史，本回执修正当前粒度结论，不洗掉病史。

F7 授权施工无剩余；待大理寺复核、后续合并与调用者真实宿主验收。临时下载、枚举与本轮 pytest／探针产物仅在系统临时目录创建，交卷前清理自建之物。
