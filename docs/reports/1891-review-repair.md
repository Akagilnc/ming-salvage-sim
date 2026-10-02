# #1891 复审修理回执

本轮基线 b1900c284；组合范围 2f20f18bd..HEAD。类1/类2原抽验成立，本轮不改生产 phase2 或逃生语义、不增兼容层。首轮「#1625 组合外基线」及「全仓只剩九个协议项」结论撤回。

## 类：交卷状态存在本分支引入的红测试

根因：2f74dc641 将 turn_phase 派生从 GameSession 搬入 decree.resolve_decisions_phase2；旧成功替身返回报告串但绕过相位派生。已核对该 commit 的真实 diff。不是外部基线失败。

扫描：`rg -n 'setattr\(.*resolve_decisions_phase2|resolve_decisions_phase2\s*=' tests --glob '*.py'`，再 AST 枚举这些替身及 return/raise/真实委托路径。

| 成员 | 处置 |
| --- | --- |
| test_pihong_dossier_1490：test_missing_dossier_fields_stay_pending_then_full_retry_decides | 成功替身移至 run_player_month_chain |
| test_due_commitment_shaped_submit_does_not_poison_or_deadlock | 同上 |
| test_lying_label_rebuilt_from_server_option | 同上 |
| test_mixed_legal_illegal_options_illegal_choice_stays_pending | 同上；保留拒绝路径 |
| test_ordinary_event_with_hallucinated_capability_submits | 同上 |
| test_1589_empty_desk_rejects_nonempty_keyless_choices | 同上；保留空案头拒绝路径 |
| test_1620_http_follow_draft_grant_uses_stored_amount | 同上 |
| test_1625_inflight_phase2_does_not_advertise_resume | 同上；保留原相位及 resume_phase2 断言 |
| test_advance_paths_atomic.test_submit_event_decision_persists_choice_after_pending_cleanup | 同上；补合法 resolve_context 输入 |
| test_advance_paths_atomic.test_submit_decisions_does_not_overwrite_already_decided_rows | 同上；保留已存 choice 原样断言 |
| _kill_at_phase2 | 保留 SystemExit 崩溃替身，不伪称成功 |
| illegal summon 的 _phase2 | 保留 AssertionError 不可达断言 |
| _count_phase2 | 保留真实 resolve_decisions_phase2 委托 |

共扫描 11 个原成功替身：10 个移到下层，另一个所属旧标题猜绑测试按退役类删除（见下）。使用现有 ResolveResult(report=..., awaiting=False, advanced=False)：桩没有推进月份，不能冒称 advanced；真实 phase2 决定 SETTLING 相位。没有修改 #1625 或其他有效入口的断言。固定 SQL 前置数据和原真实 HTTP/session 入口保留。

## 类：退役闭包全仓枚举仍有零引用成员

首轮脚本把生产引用从全仓收集，却只对 ming_sim 声明生成候选，漏掉 web_app；脚本验收引用又遮住了已无生产供给的 pending verdict getter。修正为对所有存在的 tracked Python 源码声明统一 ast.walk，覆盖函数、类、方法和内嵌闭包，逐个复核注册/协议及实际供给。

```sh
git ls-files '*.py'
# 对上述现存非 tests 源码统一 ast.parse/ast.walk：
# Name(load)、Attribute、ImportFrom、显式字符串身份反查全部声明。
git grep -n 'get_pending_promulgation_verdicts\|apply_llm_config\|_open_night_court_break' -- '*.py'
rg -n 'pending_promulgation_verdicts' ming_sim web_app.py
```

| 删除成员 | 根因/伴随处置 |
| --- | --- |
| web_app.WebGame.apply_llm_config | build/verify/commit 分步端点替代，旧合并入口无调用 |
| web_app.WebGame._open_night_court_break | 旧按大臣开面板路径撤除后的空闭包 |
| web_app.WebGame._pending_writes_count | 只为测试维持的兼容只读 counter；现役 wait 改直接读既有队列 inflight_count |
| web_app._require_active_minister | 原端点撤除，现役入口使用 session.can_summon；无注册或调用 |
| ming_sim.db.GameDB.get_pending_promulgation_verdicts | pending verdict 已无生产写入供给，旧 getter 无生产消费者 |
| scripts.promulgation_gate_561（整个闭包） | 旧 phase1 verdict 暂存/批次重判验收链已不现役；不能用历史验收脚本维持 getter |
| scripts.make_steam_assets.hline | 无供给/调用的孤立画线 helper |
| test_submit_event_decision_binds_from_candidate_snapshot_without_event_id | 旧按生成 title 猜绑候选事件的专属测试，先前错误恢复；仅恢复猜绑才能满足旧断言，依法删除，不另造证明测试 |

存量 verdict migration 消费测试保留，改用 SQL 读取真实持久化行，原迁移断言和失败路径不变；不恢复旧 getter。存量表/记录不删。

`bake_distance_matrix` 有现役离线资产构建脚本消费者；gate CLI helpers 有其他现役命令脚本消费者；apply_dossier_verdicts 有 family_tail_acceptance_570 的实际调用，并供给共享 dossier 效果，保留。不能把只扫描 Web/Python 主入口的缺引用计数冒充全仓结论。

## 聚焦证据

所有游戏测试先 export 七个 MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false，以及 PYTHONDONTWRITEBYTECODE=1；Python 为 `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。

- `$PY -m pytest tests/test_pihong_dossier_1490.py tests/test_advance_paths_atomic.py tests/test_override_breach_costs_564.py tests/test_audience_background.py -q -p no:cacheprovider --basetemp=/tmp/1891-repair-check --tb=short`：90 passed，16.06s。包含 #1625，不排除任何仍现役的失败路径。
- 变异真跑：只将 #1625 的下层替身装回旧 resolve_decisions_phase2 替身，原 HTTP 入口 1 failed/0.87s，resume_phase2=True；恢复后 1 passed/0.79s。日志 `/tmp/1891-phase2-mutation-{red,green}.log`；随后 advanced=False 最终状态包含于上面 90 绿。无新增证明用例。
- 最终 #1625 单跑：1 passed/1.10s；本轮四文件 collect-only：90 tests collected/0.67s。
- 初次下层迁移暴露第一案少 resolve_context、第二案仍要求废弃 title 猜绑，2 failed/62 passed；按合法输入和退役类别处理，未放松断言、未补生产兼容层。
- 最终 354 个 tracked Python 全部 AST 通过；from-import 真源绑定缺项 []；全仓候选最终仅 60 个有实际协议/注册消费者的保留项，逐项表见下；触及面 Ruff F401/F821、diff --check 通过。无 Python typecheck 配置，不冒称。
- 未跑全量/真实 LLM，未改席位、宿主安装或配置，未 push/PR/amend/stash。

测试最小必要成本：复用 ResolveResult 与既有月链替身，不添加测试/通用 helper；修改补齐合法输入及读取既有 SQL 行。以现有测试保调用输入，保持真实 phase2 契约和全部原拒绝断言。纯删除不计新增复杂度。

## 全仓候选保留表

最终 60 项：48 个 FastAPI 装饰器注册处理器，12 个标准/SDK 协议成员。无无依据保留项。

| 路径/限定名 | 消费者 |
| --- | --- |
| `launcher.py:_NullStream.isatty` | `stdio 文件对象协议` |
| `ming_sim/applier.py:_SuspendableConnection.__enter__` | `Python with 协议` |
| `ming_sim/applier.py:_SuspendableConnection.__exit__` | `Python with 协议` |
| `ming_sim/cli_backend.py:CliChat.ainvoke` | `Agno/OpenAIChat model 异步 override` |
| `ming_sim/cli_backend.py:CliChat.ainvoke_stream` | `Agno/OpenAIChat model 异步 override` |
| `ming_sim/decree.py:_PromulgationJudgeSession.__post_init__` | `dataclass 初始化协议` |
| `ming_sim/session_write_queue.py:ClassifiedWriteGate.__enter__` | `Python with 协议` |
| `ming_sim/session_write_queue.py:ClassifiedWriteGate.__exit__` | `Python with 协议` |
| `ming_sim/session_write_queue.py:TicketedWriteGate.__enter__` | `Python with 协议` |
| `ming_sim/session_write_queue.py:TicketedWriteGate.__exit__` | `Python with 协议` |
| `web_app.py:_NonBlockingWebWriteGate.__enter__` | `Python with 协议` |
| `web_app.py:_NonBlockingWebWriteGate.__exit__` | `Python with 协议` |
| `web_app.py:dependency_mismatch_handler` | `app.exception_handler(DependencyMismatch)` |
| `web_app.py:api_menu_status` | `app.get('/api/menu/status')` |
| `web_app.py:api_menu_new_game` | `app.post('/api/menu/new_game')` |
| `web_app.py:api_menu_continue` | `app.post('/api/menu/continue')` |
| `web_app.py:api_menu_load_save` | `app.post('/api/menu/load_save/{name}')` |
| `web_app.py:api_menu_delete_save` | `app.delete('/api/menu/saves/{name}')` |
| `web_app.py:api_menu_exit` | `app.post('/api/menu/exit_to_menu')` |
| `web_app.py:api_menu_shutdown` | `app.post('/api/menu/shutdown')` |
| `web_app.py:api_menu_save_llm` | `app.post('/api/menu/llm')` |
| `web_app.py:api_state` | `app.get('/api/game/state')` |
| `web_app.py:api_retry_mechanical_tail` | `app.post('/api/game/mechanical_tail/retry')` |
| `web_app.py:api_memorials_read` | `app.post('/api/memorials/read')` |
| `web_app.py:api_secret_orders` | `app.get('/api/secret_orders')` |
| `web_app.py:api_history_turns` | `app.get('/api/history/turns')` |
| `web_app.py:api_history_turn` | `app.get('/api/history/turn/{turn}')` |
| `web_app.py:api_map` | `app.get('/api/map')` |
| `web_app.py:api_buildings` | `app.get('/api/buildings')` |
| `web_app.py:api_add_favorite` | `app.post('/api/favorites/{minister_name}')` |
| `web_app.py:api_remove_favorite` | `app.delete('/api/favorites/{minister_name}')` |
| `web_app.py:api_audience_scroll` | `app.get('/api/audience/scroll')` |
| `web_app.py:api_audience_chat_history` | `app.get('/api/audience/chat')` |
| `web_app.py:api_audience_chat` | `app.post('/api/audience/chat')` |
| `web_app.py:api_retry_audience_reply` | `app.post('/api/audience/reply/retry')` |
| `web_app.py:api_undo_audience_chat` | `app.post('/api/audience/chat/undo')` |
| `web_app.py:api_retry_pending_translation` | `app.post('/api/audience/translation/retry')` |
| `web_app.py:api_audience_chat_stream` | `app.post('/api/audience/chat/stream')` |
| `web_app.py:api_update_directive` | `app.patch('/api/directives/{directive_id}')` |
| `web_app.py:api_delete_directive` | `app.delete('/api/directives/{directive_id}')` |
| `web_app.py:api_advance_without_edict` | `app.post('/api/decree/advance_without_edict')` |
| `web_app.py:api_issue_decree` | `app.post('/api/decree/issue')` |
| `web_app.py:api_issue_decree_stream` | `app.post('/api/decree/issue/stream')` |
| `web_app.py:api_resolve_decisions_stream` | `app.post('/api/decree/resolve_decisions/stream')` |
| `web_app.py:api_list_saves` | `app.get('/api/saves')` |
| `web_app.py:api_create_save` | `app.post('/api/saves')` |
| `web_app.py:api_delete_save` | `app.delete('/api/saves/{name}')` |
| `web_app.py:api_load_save` | `app.post('/api/saves/{name}/load')` |
| `web_app.py:api_get_llm_config` | `app.get('/api/llm/config')` |
| `web_app.py:api_set_llm_config` | `app.post('/api/llm/config')` |
| `web_app.py:api_upload_portrait` | `app.post('/api/consorts/{name}/portrait')` |
| `web_app.py:api_delete_portrait` | `app.delete('/api/consorts/{name}/portrait')` |
| `web_app.py:api_get_court_layout` | `app.get('/api/court_layout')` |
| `web_app.py:api_set_court_layout` | `app.post('/api/court_layout')` |
| `web_app.py:api_get_portrait` | `app.get('/portraits/custom/{name}')` |
| `web_app.py:api_admin_tables` | `app.get('/api/admin/tables')` |
| `web_app.py:api_admin_table` | `app.get('/api/admin/table/{table}')` |
| `web_app.py:api_admin_upsert` | `app.post('/api/admin/table/{table}/upsert')` |
| `web_app.py:api_admin_delete` | `app.post('/api/admin/table/{table}/delete')` |
| `web_app.py:admin_page` | `app.get('/admin')` |
