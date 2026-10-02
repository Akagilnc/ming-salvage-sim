# #1834 W5 — F6 修内司回执

基点：`3de079325bbf97df80ee020436ae11e1852a5d2c`。处置：[P2]「事务关联奏报与实况历史漏供」——施工修复并交卷；不宣称已合并、关票或庭审收敛。

## 法源与类边界

已读本机全局规则、仓级 CLAUDE.md / AGENTS.md、CONTEXT、ADR 0155 / 0154 / 0073、派单及冻结判词。`gh issue view 1834 --repo Akagilnc/ming-salvage-sim --json title,body` 核对现行正文：完整目录、实况／人物经历／公开说法三层可取阅，使读取方能分清实况与奏报；不要求旧链或其他票的生产接线。

本类枚举谓词：已落事务关联的持久材料，沿 `affair_id`、`affair:`、`origin_ref`（含 dossier 跳转）及各双轨读口追到实际材料载体；覆盖起因、当前情况、按月文字事实、案卷、奏报、流水和实况历史，以及三层现有投影。不按人物是否在朝、事务开放／关闭、案卷状态、密令／一般案卷、月份或恢复状态收窄。夜里未落暂存不是已落事实；公共作者显式身份排除不是全知推演者的过滤条件。

## 全仓机械枚举、成员表与复扫

仓根执行（枚举后复扫同一谓词）：

```sh
git grep -l -E 'affair_id|affair:|origin_ref|list_dossier_progress|list_dossier_actual_rail|list_dossier_actual_progress|list_dossier_durable_effects|dossier_progress_json|dossier_reported_progress|dossier_actual_progress' -- '*.py' '*.md' '*.json'
git grep -n -E 'affair_id|affair:|origin_ref|list_dossier_progress|list_dossier_actual_rail|list_dossier_actual_progress|list_dossier_durable_effects|dossier_progress_json|dossier_reported_progress|dossier_actual_progress' -- '*.py' '*.md' '*.json'
git grep -n -E '_write_world_tree|list_dossier_actual_rail|list_dossier_progress|list_decree_dossiers\(' -- ming_sim/materials.py
git grep -n -E 'prepare_world_materials\(' -- ming_sim
```

广搜结果：141 个文件、2227 个候选位置（包含源码、测试及既有冻结证据，不把全部文本命中误称生产缺陷）。沿 `entities/affair/store.py` 的指针表、origin_refs / dossiers / experiences 与 `db.py` 持久读口核对，按材料来源而非判词点名函数归类：

| 成员／物理载体 | 权威读口及处置 |
| --- | --- |
| affairs 起因、身份、状态；textual_facts 的 affair 按月实况 | 既有 list_all / current_situation → `_world_affair_lines`；保留 F5 的开放／关闭全集与开场子集分离 |
| decree_dossiers 的事务关联案卷、原旨、参与人、执行格 | 原目录无独立载体；现从无状态过滤的 list_decree_dossiers 供 `事务/<事务键>/案卷/<id>/案卷.txt` |
| decree_dossier_decisions、decree_dossier_endorsements、decree_dossier_links | 复用 list_decree_dossier_decisions / list_dossier_endorsements / list_dossier_links，随案卷供历史；关联保持既有单向引用，不复制目标案卷 |
| dossier_reported_progress：一般执行面奏报 | 原目录漏供；复用 list_dossier_progress → `奏报.txt`，全部月份与终态条目，不按案卷状态过滤 |
| secret_orders.dossier_progress_json：密令奏报 | 与一般奏报同一个统一读口，同样供 `奏报.txt`；未另写物理表解析器 |
| dossier_actual_progress：实况投入与办理记录 | 原目录漏供；复用 list_dossier_actual_rail → `实况.txt`，保留逐月记录与 origin |
| economy_ledger：案卷实付／效果历史 | list_dossier_actual_rail 已复用 list_dossier_durable_effects；现随案卷实况供完整来源字段。盘面 treasury_report(limit=None) 的全局流水摘要保留，不用摘要替代本案双轨 |
| fiscal_config_creations / fiscal_config_changes / fiscal_config_tombstones：财政效果历史 | 同一既有 actual rail / durable_effects；创建、变更、撤销全部供阅，不新建合并实现 |
| decree_dossier_reconciliations：到达、损耗与护送对账历史 | 复用 list_dossier_reconciliations，随实况供阅，不以大臣奏报替代 |
| 人物／军队／地区文字事实、人物经历（含关联经历与故事账）、公开说法、历月邸报 | 保留现有唯一对象按月载体、全人物经历及公开／邸报读面；本次不复制这些已有材料到另一载体 |
| 事务关联 issue、人物、边事件指针及其供料投影 | 属广搜关联候选，沿既有 knowledge、对象盘面／经历及文字事实供阅；不是两轨奏报表或实况进展表，不另建第二套角色权限投影 |
| due_review、breach_plea、issues、covert_progress 的专项双轨消费，及 CLI、测试、文档命中 | 核对其真实读口用于追全来源；专项复核／撤令／检举输入不能替代世界目录，亦不改成新的世界备料入口；冻结过程记录不改写 |

真实世界备料调用枚举：decree_forecast.py:152；month_chain.py:55、317、1235、1794；唯一发布入口 prepare_world_materials → `_write_world_tree`。整类修复在共同世界写树处，不逐调用打补丁。人物／场景目录保持原身份可及范围，不将全知双轨灌给大臣。

复扫：目录内新增双轨读取各一处；保留的另一 list_dossier_progress 是既有撤令专项输入，不作世界目录替代。无新增持久账本、缓存、摘要、模型调用、状态白名单或选择规则。目录仍人读字段清单；已解码的案卷字段供阅，跳过物理 JSON 存储字段及 office_archive_keys，避免重复原始序列化副本。公共作者的 exclude_secret_order_dossiers 原规则传到共同写树，密令三份文件一起排除；全知调用不传该排除。

## 根因与诊断

最小真实写口探针：开事务 → 成案并关联 → 分别 record_dossier_progress / record_dossier_actual_progress → prepare_world_materials → list_materials / read_material。修前连续两次在奏报路径不可达处报红，1.19s / 0.97s；前次修正探针事务路径为现有 `_safe_segment` 规则后再复现，不把路径夹具错误算生产缺陷。

核对三项可证伪原因：①事务投影根本未接双轨；②状态过滤裁切；③关联／恢复丢失。持久双轨读口有记录，原写树没有任何 actual rail 读取、仅专项撤令有 reported 读取，证实①；新写树不按状态过滤，真实执行中、关闭及恢复探针同审，关联和两轨仍持久。无需再加日志或补一层。

## 验证命令与结果

以下每次 pytest／游戏探针均使用七个变量前缀（无真实模型调用）：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
```

聚焦命令：

```sh
../Ming_LLM/.venv/bin/python -m pytest tests/_probe_1834_f6.py tests/test_candidate_supply_1893.py tests/test_world_materials_1834.py tests/test_material_directory_1830.py tests/test_affairs_1831.py tests/test_faction_denunciation_627.py tests/test_gazette_author_1862.py tests/test_month_chain_1843.py::test_world_segment_reads_material_directory tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree tests/test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics tests/test_mechanical_tail_1845.py::test_chapter_memory_retired_from_three_readers -q -p no:cacheprovider
```

输出：`48 passed in 10.95s`（47 个既有聚焦用例＋一个临时真实探针）。清理探针后，相同命令去掉 `tests/_probe_1834_f6.py`，交卷代码状态复跑输出 `47 passed in 9.70s`。只跑触及面，不跑全量。

变异命令（可独立重跑，不改工作树或历史；先装完整旧模块，再让 pytest 导入现行既有测试）：

```sh
../Ming_LLM/.venv/bin/python - <<'PY'
import subprocess
import ming_sim.materials as materials
exec(compile(subprocess.check_output(['git', 'show', '3de079325:ming_sim/materials.py']), 'old-materials.py', 'exec'), vars(materials))
import pytest
raise SystemExit(pytest.main(['tests/test_world_materials_1834.py::test_prepare_rebuilds_from_world_record_after_restore', '-q', '-p', 'no:cacheprovider']))
PY
../Ming_LLM/.venv/bin/python -m pytest tests/test_world_materials_1834.py::test_prepare_rebuilds_from_world_record_after_restore -q -p no:cacheprovider
```

旧逻辑：`FileNotFoundError: 事务/affair-1-5cf720a24fe8/案卷/1/奏报.txt`，`1 failed in 0.95s`。恢复新逻辑：`1 passed in 1.05s`。此前一次把临时 old 注入与已经导入新函数的测试混跑，产生私有写树参数不匹配 TypeError；不当作修复证据。上述先注入再导入的独立命令已消除夹具混用并得到目标缺陷报红。

临时探针命令：七变量前缀加 `OLD=1 .../python -m pytest tests/_probe_1834_f6.py -q -p no:cacheprovider`，旧逻辑 `AssertionError: ('rail unreachable', 'open', 1, '奏报')`，`1 failed in 1.01s`；去掉 OLD、加 `-s` 后输出：

- `PHASE_GREEN open general+secret+API/CLI+public-exclusion`
- `PHASE_GREEN executing general+secret+API/CLI+public-exclusion`
- `PHASE_GREEN closed general+secret+API/CLI+public-exclusion`
- `PHASE_GREEN restored general+secret+API/CLI+public-exclusion`
- `1 passed in 3.35s`

探针经真实 policy 颁布进入 executing、真实执行格关闭案卷、关闭事务、重开 GameDB；两种奏报物理轨都经统一真实写口与读口。每种状态的案卷／奏报／实况文件经 API 和 `/bin/cat` 读取逐字一致；公共排除后只有密令案卷三文件不可达。打印材料供特征化观察：奏报称全领讫、实况记录两份凭照及余未交付，CRLF 和尾空白仍原样；没有正文关键词、长度、哨兵或模板断言。

测试改动仅加强既有恢复入口用例，新增测试函数为零：真实关联案卷和两轨写入后关库，恢复备料，再从 read_material 读取三份结构化路径。契约是持久两轨在恢复／关闭事务后仍可及，不解析或约束人读正文。最小必要成本：20 行净新增，复用原 game 夹具与恢复闭环，无第二条平行测试或模型／网络依赖。

编译：`compile(Path(name).read_bytes(), name, 'exec')` 检查两份触及 Python 文件，输出 `Touched Python files compile: 2 PASS`。仓内没有 Python typechecker，本片未触 Web，不冒称 typecheck。`git diff --check` 无输出。

## 复杂度、合法性与剩余

先搜互联网：`curl -L -s https://docs.python.org/3/library/sqlite3.html` 读取标准库官方文档；仓内搜索所有双轨／事务／origin 读口，确认已有 list_dossier_actual_rail 将 progress + economy + fiscal 合并，list_dossier_progress 将两种奏报轨合并。标准库和生态不负责本仓领域关联；没有新造通用件、不引依赖。只连接既有领域读口与既有 `_material_facts_text`。

生产净增 33 行，测试净增 19 行；没有新 helper、schema、物理载体账本或兼容路径。既有最低开场规则不变，案卷历史按需读；保留此前已结清 F1–F5。未改 Soul／宪法／席位／宿主配置，未 amend、stash、push 或开 PR。

临时探针已删除；只清理本轮自建临时下载、枚举和探针日志，不动他人产出。剩余：本类无未结施工项；待庭审复核、合并和调用者真实宿主验收，不由修内司冒称完成。
