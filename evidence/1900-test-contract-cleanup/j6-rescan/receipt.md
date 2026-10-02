# #1900 J6 本轮施工记录（未结类）

不申报 J6 completed。上一轮 completed 结论已在上级 receipt.md 撤回。本轮没有发现合法阻断，也不申报 refused、partially_completed 或以工作量为由申报 unfinished。

## 机械枚举

命令：`python3 evidence/1900-test-contract-cleanup/inventory.py.txt`。

复用标准库 AST 和仓内 TypeScript compiler API，枚举 Git 基线 f21ce4d05 与当前追踪路径的并集，包括嵌套声明及重复声明 occurrence。更新后的完整声明账为 `../all-members.json`，变化成员表为 `../changed-members.md`；本轮数值摘要为 `summary.json`。385 源文件、248 测试声明文件，3368 → 2908 声明；2396 retained、479 modified、493 removed、33 added，154 文件/1005 声明变化。这是声明超集及源码变化账，不是全部 retained 声明的 J6 语义免责证明。

复扫命令：

```sh
rg -n '_apply_issue_entities\(|_apply_economy_list\(|_apply_person_changes\(|_backfill_army_salary_rate\(|_restore_runtime_snapshot\(' tests
```

退出 1，无匹配。空输出保存于 `helper-rescan.log`；不据此把其他 helper 或其他错误形状排除在类外。

## 本轮处置

| 成员范围（具体声明见变化成员表） | 处置/真实入口 |
|---|---|
| test_cli_backend | runner/argv/cwd/readonly、失败码和临时物清理改走 CliChat.invoke/response_stream，仅替代外部 Popen；删除直接 runner/prompt/helper 专测 |
| test_issue_entities、test_section4_rejections、test_event_trigger_gate | 持久化 issue + apply_issue_tracker_output；保留未知军、必填非法、容忍拒收、好字段落库、外层事务回滚和事件 pending 闸 |
| test_person_delta_adapter、test_audience_travel_gating_670、test_office_inference | apply_person_changes_only、reload_state_from_db、apply_office_appointment；旧直接 helper 调用删除 |
| test_person_delta_adapter、test_person_transit_write_667 | 任免案卷 + apply_dossier_promulgation，保留宗藩拒绝及罢免清赴任状态 |
| test_web_court_visibility | WebGame.state_payload、任命及真实受理；保留宗藩/外邦/赴任拒绝和零故事账 |
| test_execution_pressure_654 | create_decree_dossiers、ensure_dossiers_for_draft_directives、commit_pending_actions；负向零写入不删 |
| test_army_salary_44 | DROP salary_rate + init_schema 验旧档升级；删除独立 backfill/pool 专测，pool 现役契约保留在 commitment 测试 |
| test_fiscal_substrate_bridge、test_mutiny_noop_whitelist_319、test_covert_levy_651 | apply_score_extraction/settle_province_tick/apply_fixed_period_flows 验补饷、脏档、回滚；保留零实付不触发效果及按真实 SettlementAbort.stage 验失败 |
| test_pay_order_override_653 | 中央折发改验固定流逐军结构化账；删除同源 helper oracle 和三项持久化实现变异专测；settle_tick 非法序参拒绝仍保留 |
| test_deformation_dual_rail_622 | 删除两个绕过来源校验、空 origin/虚构父来源的 economy helper 矩阵；保留真实 commitment pool 旨外拆分落账 |
| test_faction_leverage_9 | 新校准走 init_schema 旧档入口；删除 snapshot/迁移标记专测和部分内部权重/标记断言 |
| test_transit_aging_346、test_due_review_621、test_material_directory_1830 | 删除独立 snapshot 恢复、场景文字、目录呈现 helper 专测 |
| test_runtime_llm_config、test_secret_order_isolation_883、test_enter_settlement_period_1235、test_web_chat_serialization_393、test_chat_stream_failpaths_393 | 删除 backend label、assignee helper、私有 counter 断言及退役 require-active monkeypatch；不把仍在生产使用的 settlement counter 宣称为退役 |

没有修改生产文件，没有新增通用运行机制、兼容层或宿主适配，也没有改本机宿主/席位配置。迁移后的任命 fixture 通过 set_character_office 建立真实地方任所关系，不再只改 characters.office 伪造席位。

## 验证

所有 pytest 命令带七变量：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false python3 -m pytest $(git diff --name-only -- 'tests/*.py') -q --tb=short -p no:cacheprovider
```

25 个变化测试文件：**994 passed in 28.11s**，见 `final-focused.log`；不是全量。`git diff --check` 通过。

失败留痕：第一次误用本机不存在的 python 命令，退出 127；改用现有 python3。两次入口迁移验证分别为 745 passed/1 failed（13.68s）与 348 passed/1 failed（20.36s），见相应日志。唯一失败暴露地方任命 fixture 缺任所及未建立 character_offices 关系，补真实席位后该文件 101 passed in 2.53s，最终全部变化面绿；没有放松顶替与清 transit 的断言。本机无 Ruff 可执行文件及 python ruff 模块，未申报 lint 通过。pytest 已完成变化面导入与执行验证，无独立 Python typecheck 通过声明。

测试契约：正确调用实际入口后，拒收类别/机器错误码、账本、状态、零写入及事务回滚可见；删除实现专测而不重建平行证明。最小必要成本：复用既有 fixture 与测试，将调用换成真实入口；新增/重命名声明不能等同新增平行测试套。601 行新增、3353 行删除左右，超常规新增行参考线的成本来自多个同类入口迁移，纯删除为主，未以规模作为阻断理由。

## 仍未完成的派工范围

- 完整声明账的 retained 项还未逐项完成按全文类定义的语义处置/免责；声明枚举不能替代这一步。
- 已知继续核对范围包括 `test_six_sciences_seed_608` 的私有权重 oracle/重算调用 mock、`test_faction_leverage_9` 剩余权重与迁移标记断言，以及 `test_promulgation_judge_561` 的脚本 helper 专测与 `test_qa_c2_settlement_display_lifecycle_1343` 的 shell/helper 专测。需沿同形继续扫全仓，不限于这些样本；必要失败路必须迁移而不是盲删。
- 本轮没有足够证据宣称所有自由文本、内部形状、helper 专测与退役行为都已修净。本记录不构成 J6 结类回执。

既存 `.baseline/` 未动。无 amend、stash、push 或 PR 操作。
