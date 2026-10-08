# SettlementOutcome 投影契约盘点（issue #1572 / ADR 0150 施工证据 ①）

- HEAD：`3ef603c68bb7b7276b4948a55ff0ecbfee63da71`（以下全部行号以此 commit 实读为准）
- 判词要求：盘点现有 applied dict 的全部消费者，并给 SettlementOutcome 的 typed 投影表——每个既有消费键由哪个 SectionResult/附加结果提供、哪些键删除、哪些仍由外层追加。
- 方法：实读 `ming_sim/issues.py:7756-9102`（`apply_score_extraction` 返回组装）、`ming_sim/decree.py:2273-2632`（`_settle_with_delta_atomic_body` 对 applied 的全部 mutate/read），rg 全仓其它消费方（`session.py` / `driver.py` / `web_app.py` / `ming_sim/*` / `tests/`），并以 AST 直调盘点钉死测试面规模（§3.1）。
- 术语：段适配器、稀疏 delta、拒收报告、颁布格/执行格 均按 CONTEXT.md:127/130/176/196/204 口径。

## 1. 现状返回 dict 全键清单（`apply_score_extraction`，issues.py:9057-9099）

返回 39 个顶层键。其中 4 个是**恒空兼容键**（issues.py:8866-8872 显式置空，注释自述「ADR0009 legacy aliases……Keep response keys for compatibility」），1 对**双份键**（`person_changes` = 规范化后的**输入回声** issues.py:7923；`applied_person_changes` = 落库结果 issues.py:8039/8067/8344），2 个是**拒收报告前置闸产物**（非段落格）。

`issue_summary` 子结构（`apply_issue_tracker_output` 返回，issues.py:6049-6058，由 issues.py:8260 承接）：`advances / new_issues / closes / cancels / entity_rejections / applied_person_changes / touched_ids / pairing_warnings` 八个子键。

## 2. settle 外层（`_settle_after_extract_body`，decree.py:2356-2632）对 applied 的全部 mutate/read

| 行号 (decree.py) | 动作 | 键 | 说明 |
|---|---|---|---|
| 2418 | 追加 | `settled_summon_origins` | `settle_applied_arrived_summons(db, applied)`（audience_night.py:1743-1771）**读** `applied_person_changes`（未拒收且 `transit_to=beizhili`）结清在途召旨 origin |
| 2419 | 追加 | `retired_summon_origins` | `retire_unsettled_summons_for_inactive(db)` 不读 applied，纯 DB 扫描 |
| 2420-2421 | mutate | `population_transfers` / `population_transfers_rejections` | `_apply_levy_driven_transfers`（:2407）在途摊派转移 extend 进段结果 |
| 2427-2431 | 追加 | `covert_actual_progress` | `apply_monthly_covert_actual_progress`（covert_progress.py:467），当月实况进度，只读 `extracted` |
| 2436 | 全键扫描 | 全部 list / dict-of-list 键 | `_collect_inline_rejections`（decree.py:2273-2322）递归扫 `{"rejected": True}` 项入拒收报告收集器，含硬编码特例 `issue_summary.closes.applied_person_changes`（:2312） |
| 2445-2447 | 读 | `issue_summary.advances[].issue_id` | 组 `touched_ids` 喂 inertia（注意：decree 侧自行重建，不消费 issue_summary 自带的 `touched_ids` 子键） |
| 2448-2454 | 调用 | — | `apply_issue_inertia_and_ongoing(db, state, touched_ids=…, applied_person_changes=inertia_person_changes)`（issues.py:9113），inertia 人物变更经出参带回 |
| 2455-2461 | mutate | `issue_summary.applied_person_changes` | inertia 人物变更合并进 issue_summary（不存在则新建子键） |
| 2462-2475 | 二次桥接 | inertia 拒收 + inertia 人物变更 | 补收进收集器并再 flush（桥接跑在 inertia 前的时序补偿） |
| 2479 | 追加 | `covert_levy_exposure_settlements` | `settle_exposure_from_canonical_actions`（covert_levy.py:88-167）**读** `population_transfers`、`economy_moves`、`fiscal_changes`、`fiscal_creates`、`fiscal_removes`、`applied_person_changes`、`issue_summary.applied_person_changes`、`relation_edge_event_resolutions` 共 8 键判定「禁摊派/默许/查办」 |
| 2480 | 追加 | `covert_levy_exposures` | `write_exposure_todos`（covert_levy.py:170-224）**读** `population_transfers`（未拒收且 `origin_ref=dossier:N`、`reason=摊派`） |
| 2490-2492 | 追加 | `secret_order_settlements` | `settle_due_secret_orders`（covert_progress.py:572-…），到期密令只读实况轨对账结案，不读 applied |
| 2538-2544 | 全量投影 | 全部键 | `db.save_turn_extraction(…, extractor_output=json.dumps(_player_visible_extractor_output(applied)))`——玩家可见 extraction 的唯一持久化点；`_player_visible_extractor_output`（settlement_payload.py:407-428）pop `person_changes` 与 7 个内部拒收/校验键，并把 `issue_summary.applied_person_changes` 并入顶层 `applied_person_changes` |
| 2571 | 读 | 经 `effect_brief` | `chapter_recorder` → `record_chapter_memory`（memories.py:292-344）→ `effect_brief(applied)`（memories.py:103-131+）**读** `metric_delta`、`issue_summary.closes/advances`（含 `closes[].building_ops`） |
| 2586 | 读 | `victory_status` | 结局判定入口（`_resolve_victory` 已把叙事型结局写进返回，issues.py:9098/9102-9110） |
| 2631 | 组装 | `victory_status`（间接） | `full_report = 颁布诏书 decree_text + narrative + ending`；applied 对 full_report 的唯一输入是 `victory_status`（经 :2586-2628 的 outcome→ending） |

注：2479-2492 追加的 4 个键（`covert_levy_exposure_settlements` / `covert_levy_exposures` / `secret_order_settlements` 等）产生在 :2436 桥接扫描**之后**，其内部拒收项不进入本轮拒收报告收集器——这是现状时序事实，r1 编排器须决定是否保持（不在本证据裁决范围，仅记录）。

## 3. settle 体外的运行时消费方（rg 全仓，排除 `.hermes/` 沙箱副本）

| 消费方 | 消费的键 | 位置 |
|---|---|---|
| GameDB 颁布格/执行格上浮路径（反向合成伪 delta 回调全机，ADR 0150 决定 5 点名整治） | `authority_changes`（逐项 rejected → fail-loud） | ming_sim/db.py:16354-16371、16392-16407（授予/收权案卷） |
| 同上 | `issue_summary.new_issues`（首项 rejected → 执行格落 failed） | ming_sim/db.py:16631-16642（下议 initiative）、16718-16729（交办 initiative） |
| 哭谏捆带收权 | `authority_changes`（逐项 rejected → raise） | ming_sim/breach_plea.py:656-666 |
| 召对夜传召启程 | `applied_person_changes`（空或含 rejected → `AudienceNightError`） | ming_sim/audience_night.py:1928-1951 |
| 玩家历史接口 | `get_turn_extraction(turn)` 仅取 `decree_text/year/period`，不读 extractor_output | web_app.py:4660-4680 |
| 时间线摘要（月度归档 → 每回合效果摘要） | 持久化 extractor_output 全 dict → `effect_brief`（`metric_delta`、`issue_summary.closes/advances`） | ming_sim/memories.py:256-264 |
| 人口压力投影（机械人口真相） | 持久化 extractor_output 的 `population_transfers`（逐 region 净额） | ming_sim/population_pressure.py:25-44 |
| `session.py` / `driver.py` | 不直接读 applied；`driver.py:243-260` 以 `delta_applier=lambda …: apply_score_extraction(…)` 注入并取 `settle_with_delta` 返回的 full_report 文本 | driver.py:243-260；session.py:3270 注释确认全链走 settle_with_delta |
| `tests/` | 直调规模见 §3.1 AST 盘点（三审前此处误引 `grep -rln` 文本命中数 96，已订正）；消费持久化 extractor_output 的典型测试：`tests/test_settle_core.py:94`、`tests/test_driver.py:236/292/346`、`tests/test_population_transfers_662.py:168`、`tests/test_surcharge_causal_chain_650.py:299/370/…` | tests/ |

另：`pairing_warnings` 顶层键（issues.py:9097）与 `world_advance`（issues.py:9085，输入透传）**无任何运行时读者**——前者只被 `tests/test_initiative_resolve_pairing.py:131/154` 读（且读的是 `apply_issue_tracker_output` 的返回），后者仅随 extractor_output 落库、无任何消费端解析。

### 3.1 AST 直调盘点（替代文本命中统计，三审计正）

方法：`ast.parse` 解析 `tests/` 与 `ming_sim/` 全部 `.py`，只认 `Call` 节点且 `func` 为 `Name('apply_score_extraction')` 或 `Attribute(attr='apply_score_extraction')`；注释/docstring/字符串提及与非调用的属性引用（import、别名赋值）不计入。结果（HEAD `3ef603c6`）：

| 口径 | 文件数 | 调用点数 | 说明 |
|---|---|---|---|
| AST 直调合计 | 52 | 449 | tests/ 48 文件 440 点 + ming_sim/ 4 文件 9 点 |
| ming_sim/ 直调明细 | 4 | 9 | decree.py:1400/1668/2411；db.py:16354/16392/16631/16718；audience_night.py:1928；breach_plea.py:656 |
| 别名间接调用（monkeypatch 包装） | 2 | — | `real_apply = ….apply_score_extraction` 后 `real_apply(*args, **kwargs)`：tests/test_audience_travel_gating_670.py:433/509/652/733（该文件无直调节点）、tests/test_surcharge_causal_chain_650.py:335（该文件另有 24 处直调） |
| 文本命中对照（`git grep -l`，≠直调） | tests/ 57 路径、ming_sim/ 10 路径 | — | tests/ 含 56 个 .py + `tests/game_fixture_retained_inventory.tsv`；ming_sim/ 的 10 个文本命中文件中只有 4 个存在真实调用 |
| AST 范围外手工确认 | 2 | 2 | 根目录 `driver.py:255`（lambda 内直调）＋ `scripts/promulgation_gate_561.py:242`——均不在 tests//ming_sim/ 包内 |
| **全仓合计**（scoped 52/449 + 外围 2/2；五审重跑 AST 核实，排除 .hermes/.worktrees 等副本目录） | **54** | **451** | ADR 0150 决定 6 引此口径 |

tests/ 48 个直调文件清单（按调用点数降序，供迁移排期）：test_event_trigger_gate.py(91)、test_person_delta_adapter.py(68)、test_decree_commitment_creation_136.py(30)、test_surcharge_causal_chain_650.py(24)、test_relation_capture_633.py(23)、test_authority_ledger_611.py(15)、test_decree_dossiers_571.py(15)、test_effect_origin_558.py(15)、test_population_transfers_649.py(15)、test_covert_levy_651.py(13)、test_credit_events_628.py(13)、test_fiscal_beyond_intent_1260.py(10)、test_issue_entities.py(10)、test_person_archive_contract_index.py(8)、test_person_transit_write_667.py(8)、test_army_pay_decree_1503.py(6)、test_decree_commitment_settlement_229.py(6)、test_staged_commitment_620.py(6)、test_transit_aging_346.py(6)、test_deformation_dual_rail_622.py(4)、test_due_review_621.py(4)、test_secret_dossier_participants_1252.py(4)、test_secret_order_isolation_883.py(4)、test_yuan_arrival_185.py(4)、test_breach_plea_623.py(3)、test_extractor_slot_routing_629.py(3)、test_mutiny_noop_whitelist_319.py(3)、test_pacification_materialize_522.py(3)、test_population_transfers_662.py(3)、test_faction_brew_637.py(2)、test_population_unit_648.py(2)、test_presentation_p4_family_629.py(2)、test_secret_order_section_rejections.py(2)、以及各 1 处的 15 个文件：test_appointment_tenure_607 / test_commitment_backlash_626 / test_dossier_reported_progress_619 / test_execution_joint_liability_565 / test_family_tail_615 / test_grant_reconciliation_567 / test_mutiny_actual_residence_659 / test_pay_order_override_653 / test_power_section_rejections / test_promulgation_judge_561 / test_region_cannon_delta / test_secret_order_monthly_progress_566 / test_secret_order_payoff_1504 / test_supervision_625 / test_urge_lever_624。

### 3.2 三处 `delta_applier=lambda …: apply_score_extraction(…)` 注入点（判词②点名）

| 注入点 | 所在路径 | lambda 捕获的额外参数（除 d/s/ex/ct/rg 透传外） |
|---|---|---|
| decree.py:1400-1406 | 恢复重灌路（resolve_context 直入 apply，不重跑 extractor） | `llm_config`；`candidate_event_ids_at_input`（simulator_payload 派生）；`impeachment_surge_candidates_at_input`（`gather_impeachment_surge_candidates`）；`dossier_ids_at_input`；`secret_dossier_ids_at_input` |
| decree.py:1668-1674 | resolve 主路（注释：闭包捕获 llm_config 供 issue/office 通道感知 enrichment 选后端，结算核本体不见 llm_config） | 同上一组五项（来源分别为 simulator_payload / 入参 / 密令扫描） |
| driver.py:255-259 | driver 纯确定性路（#54） | `llm_config=_DETERMINISTIC_LLM`；`dossier_ids_at_input`；`secret_dossier_ids_at_input`（无 candidate/impeachment 两项） |

另有一处默认分支 decree.py:2411（`delta_applier is None` 时裸调 `apply_score_extraction(db, state, extracted, content=content, registry=registry)`，不注入任何冻结输入）。四处的返回都是同一个 applied dict，经 decree.py:2418 起进入 §2 的 mutate/read 序列。迁约见 §4.4。

## 4. SettlementOutcome typed 投影表

「r1 后」列口径：**段** = ADR 0150 实体适配器目录中段模块的 `SectionResult`（`applied` + `RejectedItem` 拒收列表，项级四字段自带 source，框架集中补 turn/section）；**附加结果** = SettlementOutcome 上的 typed 字段，由编排器/外层 settle 产物提供；**删除** = 无投影，消费端同步迁走。

### 4.1 段落格键（稀疏 delta → SectionResult）

| 既有键 | 现状消费者 (file:line) | r1 后投影 |
|---|---|---|
| `metric_delta` | memories.py:106（effect_brief，章节记忆+时间线） | metric 段 SectionResult.applied |
| `economy_moves` / `economy_moves_rejections` | covert_levy.py:129-134；settlement_payload.py:417（pop）；_collect_inline_rejections 扫描 decree.py:2436 | 经济段 SectionResult（applied/rejected 合一，独立 `*_rejections` 键删除——拒收走 RejectedItem 单形状） |
| `faction_delta` / `faction_delta_rejections` | settlement_payload.py:413（pop）；桥接扫描 | 派系段 SectionResult；`*_rejections` 键删除 |
| `class_delta` / `class_delta_rejections` | settlement_payload.py:414（pop）；桥接扫描 | 阶层段 SectionResult；`*_rejections` 键删除 |
| `population_transfers` / `population_transfers_rejections` | covert_levy.py:127、175；decree.py:2420-2421（外层 extend 在途摊派）；持久化后 population_pressure.py:37；settlement_payload.py:415（pop） | 人口/民变段 SectionResult；外层追加部分见 4.3；`*_rejections` 键删除 |
| `surcharge_decrees` / `surcharge_decrees_rejections` | settlement_payload.py:416（pop）；桥接扫描 | 加派旨段 SectionResult；`*_rejections` 键删除 |
| `region_changes` / `army_changes` / `created_armies` / `power_changes` | 桥接扫描；持久化 | 战区/军队/势力段 SectionResult |
| `issue_summary`（八子键） | decree.py:2445-2461（advances→touched_ids、inertia 人物合并）；covert_levy.py:136；memories.py:121-131；settlement_payload.py:420-427；db.py:16634/16721（`new_issues`） | issue tracker 段 SectionResult（applied 按 advances/new_issues/closes/cancels 分子表，`applied_person_changes` 子键随段；`touched_ids` 子键见下注；`entity_rejections` 入 RejectedItem 流） |
| `dossier_executions` / `dossier_participants` / `secret_dossier_participants` | 桥接扫描；持久化 | 案卷执行段 SectionResult |
| `breach_plea_resolutions` | 桥接扫描；持久化 | 哭谏段 SectionResult |
| `credit_event_resolutions` | 持久化 | 信用事件段 SectionResult |
| `relation_edge_event_resolutions` | covert_levy.py:141-146；持久化 | 关系边事件段 SectionResult |
| `authority_changes` | db.py:16367/16403；breach_plea.py:659；桥接扫描 | 委任授权段 SectionResult；ADR 0150 决定 5 上浮后 GameDB 三处反向合成点改消费 typed 结果 |
| `fiscal_changes` / `fiscal_creates` / `fiscal_removes` | covert_levy.py:129-134；持久化 | 财政段 SectionResult（removes→creates→changes 段序由登记表承载，ADR 0150 决定 4） |
| `secret_order_updates` | 桥接扫描；持久化 | 密令推演副作用段 SectionResult |
| `applied_person_changes` | audience_night.py:1754（summons 结清）、1942（启程校验）；covert_levy.py:135；settlement_payload.py:424（与 issue 子键合并）；持久化 | 人物段 SectionResult.applied（pre/post-issue 拆分段序由登记表承载） |

注：`issue_summary.touched_ids` 子键现状**无消费者**（decree.py:2445-2447 自行从 advances 重建），r1 后由编排器从 issue 段 SectionResult.advances 派生，不再入投影。

### 4.2 删除键

| 既有键 | 删除理由（证据） |
|---|---|
| `appointments` / `character_status_changes` / `character_power_changes` / `office_changes` | 恒空兼容键：issues.py:8866-8872 显式置空 + 注释自述「do not retain a second set of direct writers」；ADR 0150「无恒空兼容键」条款 |
| `person_changes` | 双份键之输入回声（issues.py:7923 规范化后原样回显）；唯一专门处理是玩家可见投影时 pop 掉（settlement_payload.py:411）——存在即噪声 |
| `world_advance` | 纯输入透传（issues.py:9085），无任何消费端（§3 rg 无读者） |
| `secret_order_closes` | 段真源已退役（issues.py:8955-8966 一律 `retired_source` 拒收）；结案真源 = `settle_due_secret_orders`（外层附加结果） |
| `pairing_warnings`（顶层） | issue_summary 子键的顶层重复投影（issues.py:9097），运行时无读者；告警保留在 issue 段 SectionResult 附加字段即可 |
| `validate_shape_rejections` / `module_misroute_rejections` | 编排器前置闸产物（sanitize/误投），非段落格；r1 后直接进拒收报告收集器，不经 SettlementOutcome 段落格投影 |
| 全部 `*_rejections` 独立键（5 个） | ADR 0150 决定 2：RejectedItem 为全系统唯一拒收形状，独立拒收键与递归桥接同 fixed point 删除 |

### 4.3 外层追加 / 编排器附加结果键

| 既有键 | 现状生产点 | r1 后投影 |
|---|---|---|
| `settled_summon_origins` | decree.py:2418 | SettlementOutcome 附加结果（typed `list[str]`）；`settle_applied_arrived_summons` 的入参由「applied dict」改为人物段 SectionResult |
| `retired_summon_origins` | decree.py:2419 | 同上（不读 applied，纯外层产物） |
| 在途摊派转移并入 `population_transfers` | decree.py:2407/2420-2421 | 编排器段间合成：levy 转移 SectionResult 与人口段结果在 SettlementOutcome 上并列或合并为 typed 字段，不再 mutate dict |
| `covert_actual_progress` | decree.py:2427 | SettlementOutcome 附加结果 |
| inertia `applied_person_changes` 并入 `issue_summary` | decree.py:2448-2461 | 编排器附加结果（inertia 出参 typed 化）；玩家可见投影的合并点（settlement_payload.py:420-427）同步改为 typed 合并 |
| `covert_levy_exposure_settlements` | decree.py:2479 | SettlementOutcome 附加结果；`settle_exposure_from_canonical_actions` 入参 8 键改为 typed 段结果视图 |
| `covert_levy_exposures` | decree.py:2480 | SettlementOutcome 附加结果；`write_exposure_todos` 入参 `population_transfers` 改 typed |
| `secret_order_settlements` | decree.py:2490 | SettlementOutcome 附加结果 |
| `victory_status` | issues.py:9098（`_resolve_victory`） | SettlementOutcome 附加结果（结局判定非落库段，上浮编排器；decree.py:2586 消费点不动） |
| 玩家可见 extraction 整体 | decree.py:2538-2544 | 由 SettlementOutcome 统一投影：pop 清单（settlement_payload.py:411-419）转化为 typed 边界——内部拒收/校验字段在类型上不存在，`_strip_player_internal_fields` 的 `item/report_section/report_category` 剔除（settlement_payload.py:431-439）随 RejectedItem 单形状自然消失 |

### 4.4 三处 `delta_applier` 注入点与默认分支的迁约（判词②）

ADR 0150 决定 6：旧入口 `apply_score_extraction` 整体退役删除，settle_with_delta 内层落库调用点（decree.py:2409-2411）改调 `settle_delta(state, db, delta, ctx) -> SettlementOutcome`。四处生产 applied 的调用点逐一迁约如下；`delta_applier` 注入缝（decree.py:2107-2114 的参数与文档串）随旧入口同 fixed point 删除，settle_with_delta 签名收窄，不再有「None 则回退裸调」分支。

| 调用点 | 现状形态 | r1 后迁约 |
|---|---|---|
| decree.py:1400-1406（恢复重灌路） | lambda 捕获 llm_config + 4 项冻结输入闭集，返回 applied dict | 不再传 `delta_applier`。4 项冻结输入（`candidate_event_ids_at_input` / `impeachment_surge_candidates_at_input` / `dossier_ids_at_input` / `secret_dossier_ids_at_input`，#633/0079 闸门真源）改由调用方组装进 typed `ctx` 字段随 `settle_delta` 传入；`llm_config`（通道感知 enrichment 选后端用）上移为编排器/段目录构造期注入，`ctx` 不再经闭包暗带。返回 SettlementOutcome，:2418 起的下游按 §4 投影表改 typed 访问 |
| decree.py:1668-1674（resolve 主路） | 同上形状 | 同上一行迁约；注释所载「结算核本体不见 llm_config」边界由 ctx 类型显式承载（无此字段即无此能力） |
| driver.py:255-259（driver 纯确定性路，#54） | lambda 捕获 `llm_config=_DETERMINISTIC_LLM` + 2 项冻结输入 | 同上；`_DETERMINISTIC_LLM` 语义（不注入运行时通道、纯确定性落库）改为 ctx 上的确定性模式标记（或不传 llm 通道等价），不保留特殊 lambda |
| decree.py:2411（`delta_applier is None` 默认分支） | 裸调、不注入任何冻结输入（闸门口径 fail-closed 见 issues.py:9046-9047 注释） | 分支删除；`ctx` 冻结输入字段缺省=空闭集，行为等价 |

共同返回处理：四处返回值由 dict 换为 SettlementOutcome 后，decree.py:2418（summons 结清读 `applied_person_changes`）、:2420-2421（transfers extend）、:2427/:2479/:2480/:2490（外层附加结果赋值）、:2436（桥接扫描，删除）、:2445-2461（touched_ids/inertia 合并）、:2538-2544（玩家可见投影持久化）、:2571（章节记忆）、:2586（victory_status）的读取逐一对应 §4.1/§4.3 的 typed 字段，无遗漏——§2 表即这份读取清单的权威枚举。

## 5. settle_with_delta 无损组装 full_report 证明

`full_report` 组装点 decree.py:2631：`full_report = "\n本{TURN_UNIT}颁布诏书：\n" + decree_text + "\n\n" + narrative + ending`。三要素来源：

1. `decree_text`、`narrative`：settle_with_delta 的**入参**（decree.py:2364-2365 签名；in-world 拒收提示在 :2516-2517 于 save_turn_report 前并入 narrative），不经过 applied/SettlementOutcome。
2. `ending`：由 `outcome` 派生（decree.py:2586-2628），`outcome = applied.get("victory_status") or victory_status(db, state)`——对 applied 的**唯一**读键，r1 后由 SettlementOutcome 附加结果 `victory_status` 提供（§4.3），fallback `victory_status(db, state)` 为纯 DB 读。

因此：只要 SettlementOutcome 携带 `victory_status` 附加结果，settle_with_delta 组装 full_report 不读任何其它 applied 键，无损成立。其余 settle 体内消费（summons/population/touched_ids/inertia/covert/secret-order/玩家可见 extraction 持久化/章节记忆）均为**体内自产自销**或 DB 持久化投影，已逐项列入 §4 投影表，无表外消费。

## 6. 遗留风险记录（非本证据裁决项）

- §2 注：:2479-2492 四个外层追加键产生在 :2436 桥接扫描之后，其内嵌拒收项现状不进拒收报告；r1 RejectedItem 单形状落地后此窗口自然消失，但迁约期间须测试钉住现行行为或显式裁决变更。
- §3.1：tests/ 48 个文件 440 处 AST 直调（另 1 个文件纯别名间接调用）——按 ADR 0150 Consequences 的测试迁移口径（DB 态断言为主不动、公共主干塌缩、三域迁真 SQLite 行为测试），迁移规模以此数为准（三审前误引文本命中数 96，已订正）。
