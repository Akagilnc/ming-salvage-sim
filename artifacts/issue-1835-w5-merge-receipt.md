# Issue #1835 W5 修内司 apply — merge `claude/1812-w4` 回执（修正轮）

- **票面**: #1835（retire `EMPTY_EXTRACTION` / `apply_score_extraction` → `settle_delta`）+ 底座 `claude/1812-w4`（#1812 / #1892 / #1894 / #1895 / #1896 / #1901）
- **merge commit**（禁止 amend）: `861da98c9`
- **ours tip**: `6bda8348e`（#1835-w5）
- **theirs tip**: `10e64fbef`（claude/1812-w4）
- **本轮**: 独立 `ak-roles:` 提交修正聚焦命令七名 `MING_SIM_*_BIN` 前缀硬约束违规，并重跑仓内清单聚焦验证；不 amend / rewrite / stash / push / 不开 PR
- **保护未跟踪产出**: `artifacts/issue-1835-w5-ast-audit.py`、`artifacts/issue-1835-w5-mutation-probes.py`（未覆盖、未删除、未纳入提交）
- **前序修正提交**（错误 ours / 31 失败）: `f08ff8675`（保留；本轮不 amend）

## 对上一版回执的纠错

上一版 `861da98c9` 回执披露保留 HEAD `urge_lever`、恢复 `default_terminal_reason`、并以 HEAD 测试为权威——**违派单**「不复活任一侧已删旧路，以底座已收敛票现役结果为准」。本轮逐票复核后：

| 错选 | 纠为 | 票面 |
|---|---|---|
| ours 保留 HEAD `urge_lever` + HEAD 测试族 | **theirs** W4 `#1895` 退役改判词写路 + `test_urge_no_longer_rewrites_verdict_ac1_1895` | #1895 |
| hybrid 恢复 `default_terminal_reason`（models/content/events） | **theirs** 删除字段；`apply_historical_fiscal_rates` 不再代批 | #1892 |
| 以 HEAD 测试旧行为为权威 | 以底座已收敛票 + #1835 settle_delta 契约为准；失效/措辞锁测试删除 | 派单 |

## 聚焦测试

清单（仓内，禁止 `/tmp`）: `artifacts/issue-1835-w5-conflict-tests.txt`  
命令脚本: `artifacts/issue-1835-w5-focused-cmd.sh`  
最终日志: `artifacts/issue-1835-w5-focused-final.txt`（同步副本 `artifacts/issue-1835-w5-focused-final.log`）

### 前序绿证据不能冒充满足前缀约束（诚实核验）

`f08ff8675` 入库的 `artifacts/issue-1835-w5-focused-cmd.sh` 与当时回执命令**只有** `MING_SIM_AGY_BIN`；其余六名为裸 `CODEX_BIN` / `CLAUDE_BIN` / `CURSOR_BIN` / `KIMI_BIN` / `GROK_BIN` / `PI_BIN`，**不是**派单硬约束的 `MING_SIM_*_BIN`。  
同提交的 `artifacts/issue-1835-w5-focused-final.txt`（2269 passed / ≈61.19s real）是由该**缺前缀**脚本跑出的——**不得**把那次绿结果表述为「已满足完整七名 `MING_SIM_*_BIN`」。  
对照：同仓 `artifacts/issue-1835-w5-repair.md` 早先正确写法已是七名 `MING_SIM_*_BIN`；本轮聚焦脚本曾误写成裸名。

### 本轮修正后命令（完整七名）

```bash
./artifacts/issue-1835-w5-focused-cmd.sh
# equivalent:
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider -q --tb=line \
  $(cat artifacts/issue-1835-w5-conflict-tests.txt)
```

**本轮实测结果（完整七名前缀）: 2269 passed / 0 failed / 4 skipped**（≈85.47s real；exit 0）

---

## 冲突文件逐文件处置（双方 commit + 票面 + 理由）

双方来源列：`ours=6bda8348e` / `theirs=10e64fbef`。处置后的现役形状以本工作树 + 本轮修正提交为准。

### 生产 / 文档

| 路径 | ours | theirs | 处置 | 票面引证与理由 |
|---|---|---|---|---|
| `docs/SETTLEMENT_FLOW.md` | #1835 月链/settle_delta | W4 世界腿叙述 | **ours** | #1835 月链契约真源；与 `settle_delta` 一致 |
| `ming_sim/action_materialize.py` | #1835 staging | #1890 无 payload `source_chat_turn_id` 等 | **hybrid→W4 意图** | 取 W4 #1890 撤令/成案字段；保留 #1835 声明侧入口 |
| `ming_sim/breach_plea.py` | 无 `close_target` | #1894 `close_target` | **hybrid** | 保留 ours 骨架，透传 W4 `close_target=False`（#1894 F2） |
| `ming_sim/cli_backend.py` | #1835 | W4 查案/供料 | **hybrid** | 种子罪情走 W4 宽容解析；不复活 `apply_score` |
| `ming_sim/content.py` | 含 `default_terminal_reason` 校验 | 已删字段 | **theirs** | #1892 退役默认终态；禁止恢复 |
| `ming_sim/context.py` | #1835 | W4 | **ours** | 现役上下文契约 |
| `ming_sim/covert_progress.py` | #1835 `(applied, rejections)` | #1896 查案逐证 | **hybrid** | W4 查案核算 + #1835 RejectedItem；月链扫 applied 行上 invalid |
| `ming_sim/db.py` | #1835 DeclarationDataError；仍有旧 lane 预写 | W4 月报/撤令/`seed_investigation` | **hybrid+修** | 补 `validate_monthly_dossier_progress`；修复 `resolve_revoke_decree_target_ids`（漏 `source`/`fields`，merge 损坏）；**删除**开案旧 `fact_lanes` 预写（progress/used→难度钉 0，违 #1896） |
| `ming_sim/declaration_dispatch.py` | settle_delta 声明派发 | W4 亲裁/撤令交办 | **hybrid+修** | #1835 落账入口；补 #1892 `apply_petition_event_outcome`；**补回** #1894 `stage_revoke_decree_candidate` 交办支路（merge 丢失致撤令落成 special_decree） |
| `ming_sim/decree.py` | 仍调监督反制硬门 | #1895 退役硬门 | **hybrid** | 去监督反制硬调；保留 `trigger_commitment_backlashes` |
| `ming_sim/due_review.py` | #1835 | W4 去失真档 + `current_audience_scene` | **theirs 意图** | #1895 到期复核不因催办改判词 |
| `ming_sim/flows.py` | 2-arg payable | `army_pay` 1-arg | **theirs+适配** | #1901 军饷进 `army_pay` |
| `ming_sim/issues.py` | 无 `apply_score`；实体写口迁 effects | 仍含旧总入口 + 亲裁/饷率 | **hybrid+修** | #1835 退役总入口；迁入 W4 `apply_petition_*` / `gather_fiscal_levy_petitions`；**`apply_historical_fiscal_rates` 改 W4 形**（不代批、不过 default_terminal） |
| `ming_sim/knowledge.py` | #1835 | W4 | **hybrid** | 现役知识投影 |
| `ming_sim/materials.py` | #1835 | W4 查案/撤令供料 | **hybrid** | 材料目录接 W4 撤令事实 |
| `ming_sim/month_chain.py` | #1835/#1846 fault-honest | W4 army_pay/inertia | **hybrid+修** | 保留 invalid declarations；Phase-3 同时扫 applied 查案 invalid 行 |
| `ming_sim/simulation.py` | #1835 | W4 | **ours** | 现役模拟编排 |
| `ming_sim/staged_commitment.py` | #1835 | W4 | **ours** | 现役暂存承诺 |
| `ming_sim/urge_lever.py` | HEAD 催紧改判词 | #1895 退役改判词 | **theirs** | 与 W4 逐字节对齐；不复活 HEAD 写路 |
| `web_app.py` | 保留 POST `/api/directives` | ADR 0152 退役手拟新增口 | **theirs** | #1835/#1849：删除 `DirectiveRequest` + POST；改稿只走 PATCH |
| `content/events.json` | 四条三饷有 `default_terminal_reason` | 已删 | **theirs** | #1892 |
| `ming_sim/models.py` | 有字段 | 已删 | **theirs** | 随 content 契约（非独立冲突文件，同批修正） |
| `ming_sim/settlement/preflight.py` | #1835 | — | **修** | 三饷亲裁预检分支接 #1892（非冲突表项，本轮接缝） |
| `ming_sim/settlement/run.py` | 仅 abdicate/suicide | W4/`cb43ec63a` `_declared_emperor_ending` | **修** | #1847/#1835：恢复非空 `emperor_fate`（含「被废」）透传 |
| `ming_sim/entities/issue/tracker.py` | 模型选中 situation 不落 `effect_on_trigger` | W4 #1893 随选中落改国号 | **修** | #1893：`event_to_issue` 后补 `effect_on_trigger`（huangtaiji→大清） |

### 冲突触及测试（逐文件）

| 路径 | ours | theirs | 处置 | 票面引证与理由 |
|---|---|---|---|---|
| `tests/test_advance_paths_atomic.py` | settle_delta | apply_score 名 | **适配** | #1835 换口；不复活旧总入口 |
| `tests/test_advances_section_rejections.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_affairs_1831.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_applier_contract.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_appointment_tenure_607.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_army_card_status_1501.py` | 同上 | #1901 hub | **适配** | #1835+#1901 |
| `tests/test_army_display_173.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_army_firearms.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_army_maintenance_retire_173.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_audience_travel_gating_670.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_breach_plea_623.py` | 推迟挽留用例 | #1894 当月落实 | **hybrid** | 撤推迟锁；`apply_score`→`settle_delta`；#1894 |
| `tests/test_character_knowledge_489.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_chat_stream_failpaths_393.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_cli_backend.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_cli_runner_error_typed_1299.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_close_issues_section_rejections.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_commitment_backlash_626.py` | 同上 | #1895 | **适配** | #1835+#1895 |
| `tests/test_commitment_display_348.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_decree_commitment_creation_136.py` | SettlementOutcome | dict | **适配** | #1835 视图/metrics；别名账户断言对齐现役 |
| `tests/test_decree_commitment_schema_136.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_decree_commitment_settlement_229.py` | 裸 int 崩 | 非数字跳过 | **适配** | #1835 拒收边界（非数字 gate） |
| `tests/test_decree_dossiers_571.py` | web POST 手拟 | ADR 0152 退役 web 轴 | **theirs** | 取 W4 手拟测（只留行为维；断言路由已退役） |
| `tests/test_decree_forecast_1861.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_deepseek_thinking_disable_1797.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_deformation_dual_rail_622.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_dossier_links_559.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_due_review_621.py` | HEAD 失真档 | #1895 | **theirs 意图** | 与退役 urge 写路一致 |
| `tests/test_effect_origin_558.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_enrich_list_guards.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_enter_settlement_period_1235.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_error_pack.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_event_trigger_gate.py` | SettlementOutcome 误用 `view(new_issues)` | W4 dict/`issue_summary` | **适配+修生产** | #1835 `issue_rows`；生产补 #1893 `effect_on_trigger` |
| `tests/test_execution_joint_liability_565.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_executor_routing_721.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_faction_denunciation_627.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_faction_leverage_9.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_featured_dossiers_494.py` | modify/delete | W4 | **按侧** | 冲突形态 modify/delete；取现役侧 |
| `tests/test_fiscal_beyond_intent_1260.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_fiscal_levy_effect.py` | 自动代批假设 | #1892 亲裁 | **theirs+适配** | 对齐请旨/留中/信封；`SettlementOutcome` 视图 |
| `tests/test_fiscal_substrate_bridge.py` | settle_delta | #1901 | **适配** | #1835+#1901 |
| `tests/test_grant_reconciliation_567.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_history_decree_text_1843_reopen.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_hitl_quota_delete_1467.py` | modify/delete | W4 | **按侧** | modify/delete |
| `tests/test_impeachment_surge_655.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_issue_decree_token_1277.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_issue_entities.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_llm_channel_config.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_material_directory_1830.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_month_call_recovery_1846.py` | #1846 | W4 | **适配** | #1835+#1846 |
| `tests/test_month_chain_1847.py` | 缺 `validate_*` / fate 透传 | W4 4a + #1847 被废 | **修生产** | 补校验口；`_declared_emperor_ending` |
| `tests/test_mutiny_noop_whitelist_319.py` | settle_delta | #1901 | **适配** | #1835+#1901 |
| `tests/test_mutiny_third_strike_318.py` | 同上 | 同上 | **适配** | #1835+#1901 |
| `tests/test_new_issues_section_rejections.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_no_edict_full_settlement_1274.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_on_scene_immediate_write_1839.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_opening_gazette_delete_1356.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_override_breach_costs_564.py` | 同上 | #1894 | **适配** | #1835+#1894 |
| `tests/test_pay_order_override_653.py` | 撤令不断 | #1894 当月恢复 | **修生产** | 交办撤令支路 + `resolve_revoke_*` |
| `tests/test_pay_order_override_extraction_653.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_person_delta_adapter.py` | 无快照契约 | W4 falsy 快照锁 | **删 W4 锁测** | #1835「本核不做快照」；删除 `test_new_appointment_falsy_return_restores_snapshot` |
| `tests/test_person_transit_write_667.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_player_army_projection_321.py` | PATHS 含 legacy | W4 仅 hub | **theirs 意图** | #1901：legacy scalar 军饷路退役；PATHS=`substrate_hub` |
| `tests/test_population_transfers_649.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_population_unit_648.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_power_section_rejections.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_pre_settle_transaction.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_promulgation_judge_561.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_qa_b3_409_ux.py` | 文案/相位 | W4 | **适配** | 接现役相位消息 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 仍认 POST | 退役手拟口 | **theirs** | 与 web_app 退役一致 |
| `tests/test_qa_e1_numeric_presentation.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_qa_h1_seed_data.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_rejection_wiring.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_relation_capture_633.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_relation_seed_638.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_rescript_draft_656.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_secret_order_isolation_883.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_secret_order_monthly_progress_566.py` | sim_note NameError | W4 | **适配** | 绑定局部 `sim_note`；settle_delta |
| `tests/test_secret_order_payoff_1504.py` | 短套 settle_delta | W4 查案长套仍调 apply_score | **W4 基线+适配** | #1896；解包 `(applied, rejections)`；生产修 lane 预写 |
| `tests/test_section4_rejections.py` | 历史 ValueError pin | #1835 实体拒收 | **删三测** | 合法退役：issue 路不再 raise 的措辞/历史严格锁 |
| `tests/test_session_write_queue_1353.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_state_reload.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_style_temperament_641.py` | 同上 | 同上 | **适配** | #1835 |
| `tests/test_urge_lever_624.py` | HEAD 全族 | #1895 AC1 | **theirs** | 取 W4；含 `test_urge_no_longer_rewrites_verdict_ac1_1895` |
| `tests/test_web_court_visibility.py` | settle_delta | apply_score | **适配** | #1835 |
| `tests/test_web_llm_runtime_config.py` | 同上 | 同上 | **适配** | #1835 |

## 31 失败归类（已关闭）

| 类 | 处理 |
|---|---|
| #1892 三饷代批 / default_terminal | 生产取 W4 pass；删字段 |
| #1895 urge 改判词 | 生产+测试取 W4 |
| #1894 撤令当月恢复 | 补交办撤令支路 + 修 `resolve_revoke_decree_target_ids` |
| #1896 查案 invalid / spoliation | 月链扫 applied invalid；删旧 lane 预写 |
| #1893 称帝改国号 | tracker 补 `effect_on_trigger` |
| #1847 被废终局 | `_declared_emperor_ending` |
| #1835 SettlementOutcome / 退役口 | 测适配 `issue_rows`/`settle_delta`；删 POST 手拟与 section4 ValueError pin；删快照锁测 |
| #1901 legacy 军饷 | 聚焦测只留 hub |

## 前置阻断

无。未发现需 owner 新决定才能继续的缺口；工作量/后续另片不构成阻断。

## 提交

- 类型：独立普通提交（**非** amend `f08ff8675` / `861da98c9`；不 rewrite / stash / push / PR）
- 前缀：`ak-roles:`
- 含：修正后的 `focused-cmd.sh`、更新后的本回执与聚焦最终日志
- 不含：`artifacts/issue-1835-w5-ast-audit.py`、`artifacts/issue-1835-w5-mutation-probes.py`（保留为未跟踪）

---

## 本轮封驳：`merge-seam-retired-symbol-import`（独立新提交）

### 承认前序聚焦缺口

前序聚焦清单只覆盖**冲突文件**（`artifacts/issue-1835-w5-conflict-tests.txt`），漏掉底座 W4 自动并入的**非冲突新增**测试。  
实证：`tests/test_staged_assignment_identity_1890.py` 仍 `import apply_score_extraction`，全仓 `pytest --collect-only` 收集中断。

### 按类扫描

- 报告：`artifacts/issue-1835-w5-retired-symbol-scan.md` + `.json`
- 范围：W4 新增 ∪ W4/merge 修改的全部 `tests/`（universe=162），AST 扫 `apply_score_extraction` / `EMPTY_EXTRACTION` / `default_terminal_reason` / `MODULE_FIELDS` 的 import/Call
- 收集级命中（修复前）：仅 `tests/test_staged_assignment_identity_1890.py`
- 同类运行时命中（聚焦扩充后暴露）：`tests/test_candidate_supply_1893.py` 仍按旧 dict 下标读 `SettlementOutcome`

### 处置

| 文件 | 处置 |
|---|---|
| `tests/test_staged_assignment_identity_1890.py` | 两条 `new_issues` → `settle_delta` + `issue_rows` / `rejected_view`；散文年诺拒收、结构化 stages 落段 |
| `tests/test_candidate_supply_1893.py` | `result.effects.applied[0]` 改读 `issue_rows` / `rejected_view`（对齐 `test_event_trigger_gate`） |
| `ming_sim/declaration_dispatch.py` | 复核同文件其余用例：补回 `_dispatch_commissions` 各支路丢失的 `source_chat_turn_id=`（#1890） |
| `ming_sim/action_materialize.py` | 责成 stages 改回 `stages_to_json` 严格面（散文串 durable 拒收，#1890/ADR 0142） |

不恢复 `apply_score_extraction` / `EMPTY_EXTRACTION` / 兼容壳。

### 扩充聚焦清单

- 新清单：`artifacts/issue-1835-w5-focused-tests.txt` = 原冲突清单 ∪ W4 非冲突新增 ∪ 按类扫描受影响文件（93 路径）
- 命令：`artifacts/issue-1835-w5-focused-cmd.sh`（完整七名 `MING_SIM_*_BIN`）

### 本轮验证

**聚焦**（七名前缀）:

```bash
./artifacts/issue-1835-w5-focused-cmd.sh
```

结果：**2303 passed / 0 failed / 4 skipped**（≈61.37s real；exit 0）  
日志：`artifacts/issue-1835-w5-focused-final.txt`（同步 `.log`）

**全仓收集**（用户明确要求；收集而非全量执行；七名前缀）:

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p .../python -m pytest -p no:cacheprovider --collect-only -q
```

结果：**3707 tests collected / 0 collection errors**（≈5.43s real；exit 0）  
日志：`artifacts/issue-1835-w5-collect-only.txt`

### 本轮提交约束

- 独立 `ak-roles:` 新提交；禁止 amend / rewrite / rebase / stash / push / PR
- 保护未跟踪：`artifacts/issue-1835-w5-ast-audit.py`、`artifacts/issue-1835-w5-mutation-probes.py`
