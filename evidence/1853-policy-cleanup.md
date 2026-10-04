# #1853 末判两类修理回执

范围：全仓 tracked 源码、调用、类型、测试与施工证据；末判 J4-T / J5-R，不重开已结类。基线 `b0acff26d522f590210beefac6a96c00d5bb262a`。

## 1. 写前事务归属政策单一权威

枚举命令（施工前、施工后均执行；不是按判词点名文件过滤）：

```sh
git grep -n -E '_commit_suspended|_atomic_depth|in_transaction|owns_transaction' -- '*.py'
```

逐命中回到所属函数，区分写前是否允许自提交/开 atomic、写后是否暂停提交、真实连接操作与缓存资格。`in_transaction` 官方语义已查阅： https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.in_transaction （curl 下载官方文档于系统临时目录）。仅引用仓内现成 `applier.connection_owns_transaction`，GameDB 使用其现有委托 `owns_transaction()`；不新造政策或事务框架。

### 重复政策全成员表（18 处）

| 文件 | 成员 | 处置 |
|---|---|---|
| db.py | `_run_pending_action_commit_lifecycle` | 默认归属引用 `self.owns_transaction()`；保留显式参数、savepoint 与恢复回调 |
| db.py | `commit_pending_actions` | 写前引用；保留输入准备与逐项共同生命周期 |
| db.py | `withdraw_pending_action` | 引用 |
| db.py | `hold_over_pending_actions` | 引用 |
| db.py | `drop_pending_actions_for_minister` | 引用 |
| db.py | `insert_issue_with_affair_declaration` | 外层归属取公共政策反值 |
| db.py | `list_active_legacies` | 失活写前归属取反值 |
| db.py | `legacy_modifiers` | 写前提交及缓存资格引用 |
| audience_night.py | `discard_inactive_office_summon` | 引用 `connection_owns_transaction(conn)` |
| issues.py | `apply_historical_fiscal_rates` | 引用 |
| issues.py | `apply_event_cascading_invalidations` | 引用 |
| issues.py | `apply_event_terminal_states` | 引用 |
| issues.py | `apply_issue_tracker_output` | 引用反值，内存恢复注册不变 |
| issues.py | `_apply_person_changes` | 默认外层归属引用反值 |
| issues.py | `apply_person_changes_only` | 引用反值，内存恢复不变 |
| issues.py | `apply_score_extraction` | 引用反值，内存恢复不变 |
| issues.py | `_apply_score_extraction_body._apply_normalized_person_changes` | 进入人物写口时引用反值 |
| situation_drift.py | `apply_situation_monthly_drift` | 写前归属引用 |

### 已引用公共政策的成员（保持）

| 文件 | 成员 |
|---|---|
| applier.py / db.py | `connection_owns_transaction` 真源 / `owns_transaction` 委托 |
| db.py | `set_fiscal_config`, `set_fiscal_config_batch`, `record_relation_edge_event`, `apply_seed_founding_segment`, `apply_relation_brew_result`, `mark_relation_brew_pending`, `claim_relation_brew_targets`, `claim_faction_brew_targets`, `mark_faction_brew_pending`, `apply_faction_brew_result` |
| declaration_dispatch.py | `_item_savepoint_scope` |
| entities/affair/store.py | `open`, `declare_closed`, `attach_pointer` |
| entities/staged_declaration/store.py | `stage`, `discard`, `clear_questions`, `mark_settled` |
| entities/textual_fact/store.py | `append` |
| flows.py | `_advance_province_fiscal_substrate` |
| issues.py | `apply_petition_event_outcome`, `_apply_surcharge_decrees`, `_apply_bandit_absorptions` |
| pay_order.py / public_sayings.py / session.py | `materialize_pay_order_decree`, `record_public_saying`, `register_unlisted_person_record` |

### 原谓词其余命中不属于写前政策副本

- `applier.py` Connection 的 commit/rollback/executescript/context、atomic 深度和 BEGIN、runtime outcome callback 深度：事务实现或回调执行边界，不是再次定义调用者归属。
- `db.py` 原行 9357、9642、11850、17260、17310、17388、17422、17552、21755；`audience_night.py` 276、1746；`audience_translation.py` 160；`session.py` 1242：DML **之后**的暂停提交判断。不得换为写前政策，否则自身隐式事务令正常写永不提交。
- `db.py` 回报/actual-progress 写后深度检查；`covert_progress.py` 1529、1870、2091：写后提交。
- `db.py:close_secret_order` 的 `in_transaction`：决定现有连接是否能开 SAVEPOINT，与 else BEGIN 路径相对；其 commit/depth 为写后提交，保持差异。
- `db.py:backup_to`、`flows.py` 54 / 1029、`decree.py` 的深度、`month_chain.py` 错误包出口：备份限制、原子域限制、写后提交/错误出口，不是写前归属政策。
- 注释、测试观察、名字含 `_in_transaction` 的实际内部写函数不是政策实现。Web / 根目录 / scripts 扫描没有额外生产政策副本。

复扫：所有写前归属成员均引用公共政策；剩余 raw flags 如上分属真实事务操作与写后提交，未机械替换。

## 2. 退役失败路径无消费者残余清退

枚举不限失败 getter 的名字；联合 SQL、状态字面量、查询/读取命名及消费者：

```sh
git grep -n -i -E '(get|list|find|read|count|has)[[:alnum:]_]*(fail|reject|error)|(fail|reject|error)[[:alnum:]_]*(get|list|find|read|count)' -- ':!evidence' ':!docs' ':!archive'
git grep -n -E 'SELECT.*(failed|rejection)|FROM.*(fail|rejection)' -- ming_sim
```

并对 `git ls-files '*.py'` 每个非测试/非 archive 函数做 AST 枚举：合并全部字符串常量，若含 SELECT 且含 fail/reject/error，或读取函数名含这些类别，即枚举候选；逐函数用 `git grep -n -w <函数名> -- '*.py' ':!tests' ':!archive'` 查生产消费者。这样动态拼接 SQL、普通名称且过滤失败状态的查询不被漏掉。AST 大函数的写操作/正常实体查询只是候选，不冒称退役失败读取。

| 成员/候选族 | 消费者与处置 |
|---|---|
| `db.list_failed_secret_order_actions` | 只有定义及一条测试调用；三个 Web 消费者已退役。**删除** getter 及专属查询断言 |
| `RejectionCollector.has_player_visible_rejection` | 全仓无生产/测试消费者；只剩历史 ADR 提及。服务旧邸报固定失败提示，现役拒收供料直接读 durable 行。**删除**旧布尔读取；不改法源文档 |
| `db.discard_failed_secret_order_intents` | decree 现役清理直接 DELETE；**保留**，不是上述 getter 消费者 |
| `db._secret_origin_message_protection` | `release_held_audience_knowledge` 与 materials 消费；现役保密，**保留** |
| `db.list_pending_actions` | 现役提交、保密、暂存操作共享查询；**保留** |
| `db.list_in_flight_chat_turns`, `get_interrupted_reply_retries`, `get_post_reply_retries`, `list_unextracted_replies` | CLI / Web / 翻译任务消费；现役系统失败或待办读取，**保留** |
| `audience_night.list_chat_turns_for_night`, `reproject_night_protagonist` | 夜卷、材料、转译、撤回消费，**保留** |
| `audience_night.audit_night_direct_writes` | 测试消费现役夜内写白名单审计；不是退役失败展示查询，**保留** |
| `db.list_dossier_link_rejections` | 测试查询现役 durable 关联拒收审计。拒收写口仍生产落审计，不是退役失败路径，**保留** |
| `db.list_pending_decisions`, `list_rescript_desk`, `get_rescript_desk_rows_by_keys` | 月链/session 消费现役批红数据，**保留** |
| `db.list_closed_night_archives`, `list_decree_dossiers_for_simulation`, `list_closed_issues_at`, `find_any_issue_by_origin`, `list_monthly_grant_reconciliation_targets` | 正常档案/实体生命周期、财政对账查询，不是退役失败读取；**保留** |
| `month_chain._month_fact_materials` | 现役拒收行供料；世界段与其他供料消费，**保留** |
| `month_chain._dossier_rejection_is_this_turn` | 现役批红供料过滤，**保留** |
| 其余 SQL 候选（init_schema、实体 apply/create/update/close、confirm/extract、材料、pay-order、relation-read、Web restore） | 查询正常实体或执行现役写路径；没有失去生产消费者的退役失败查询，不删除 |

纠正 `evidence/1853-fixer-final.md`：“清理查询”保留理由不成立。保密行为案保留真实 stage→commit→另项 commit→知识状态与共享库断言；仅移去死 getter 断言，重命名并改注释为拒收保密，而非未交付的“可重试”生命周期。失败终态、拒收审计和清理不删；不补消费者。

复扫：生产和测试中的两个删除符号零命中；历史法源引用和本回执删除说明不算消费者。

## 3. 自验与变异

所有测试/探针前缀：

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" MING_SIM_USER_DATA_DIR=/tmp/1853-policy-data
```

Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。

临时探针（不固化永久测试）：从真实 `stage_pending_action → commit_pending_actions` 进入，缺目标的密令声明触发拒收。外层 BEGIN 或 atomic 中提交后 rollback；断言连接仍有事务且原动作回到 pending。删除多余查询后仅需这条动作，没有模型、网络、并发或异常注入。

- 修前：`python -m pytest -p tests.conftest /tmp/test_1853_policy_probe.py -q -p no:cacheprovider --basetemp=/tmp/1853-policy-red`：**1 failed, 1 passed in 1.31s**；BEGIN 实际 `(False, failed)`，预期 `(True, pending)`。
- 修后同入口：**2 passed in 1.08s**。
- 变异命令：Python 内联 AST 提取 `git show b0acff26d:ming_sim/db.py` 的 `_run_pending_action_commit_lifecycle` 与 `commit_pending_actions`，只在当前进程替换 GameDB 两方法；`pytest.main` 同一探针：**1 failed, 1 passed in 0.95s**，`OLD_EXIT=1`；finally 恢复，`METHODS_RESTORED=True`。
- 变异同进程第二次 pytest 忘带 conftest 插件：**2 errors in 0.09s**（fixture game not found），不是产品失败或绿测。随后独立真实入口聚焦重跑已带插件，恢复逻辑再次绿。
- 聚焦命令：`python -m pytest -p tests.conftest /tmp/test_1853_policy_probe.py tests/test_transaction_boundary.py tests/test_audience_commit_failure_1853.py tests/test_secret_order_isolation_883.py tests/test_dossier_links_559.py tests/test_decree_dossiers_571.py tests/test_person_delta_adapter.py tests/test_web_audience_night_498.py tests/test_event_chain_cascade.py tests/test_event_trigger_gate.py -q -p no:cacheprovider --basetemp=/tmp/1853-policy-focus --durations=5`：**507 passed, 1 skipped in 10.69s**。
- 遗产、财政、惯性触及面：`python -m pytest tests/test_empire_modifier_income_only_341.py tests/test_fiscal_levy_effect.py tests/test_decree_commitment_settlement_229.py -q -p no:cacheprovider --basetemp=/tmp/1853-policy-extra --durations=3`：**85 passed in 2.65s**。

仅删除失效专属断言，不新增永久证明测试；保留现有保密负向契约。未跑全量，未改席位/宿主配置，未调真实模型，无新事务框架、恢复层、护栏或状态。诊断根因已有判词独立取证，未重复假设/加日志；临时反馈环用于验证真实因果。临时探针及自建数据、pytest 目录、扫描产物、下载文档交卷前清理。

剩余：核心功能接线及既有连续读失败仍按前判留 #1873 / 家族收尾，不归本轮两类修理；本轮不宣称其已实现，也不作切片阻断。切片提交不等于合并或总票完成。
