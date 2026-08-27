# issue #1572 / ADR 0150 迁移证据：per-实体迁移规模清单 + registry 权威关系

- HEAD：`3ef603c68bb7b7276b4948a55ff0ecbfee63da71`（`3ef603c6 Merge pull request #1557 from Akagilnc/codex/issue-659`）
- 行号口径：全部以该 HEAD 实读 `ming_sim/issues.py`（9,456 行）、`ming_sim/simulation.py`（1,946 行）、`ming_sim/flows.py`（2,352 行）、`ming_sim/decree.py`、`ming_sim/db.py` 实测为准；行数 = 函数/段起止行差实量（段尾=下一顶层 def 前一行）。
- 术语：段适配器 / 稀疏 delta / 拒收报告 / 颁布格 / 执行格 均按 CONTEXT.md 定义。
- 一处文稿勘正：ADR 0150 引文称 `apply_score_extraction` 为 1,346 行；本 HEAD 实量 7756–9099 = **1,344 行**（差 2 行，系 ADR 起草后该函数两次小编辑所致，不影响结论）。

## 1. 总览：迁移触及面分账

| 桶 | 行数 | 说明 |
|---|---:|---|
| `apply_score_extraction` 本体（issues.py:7756-9099） | 1,344 | 编排核，全量退役删除；逻辑行提取为段，接缝行重写 |
| 体外落库/读侧 helper（issues.py + flows.py，随段迁入实体目录） | 4,630 | 见 §2 逐实体表逐函数实量求和 |
| **迁移触及面合计** | **5,974** | 纯移动 ≈4,460；行为改动 ≈1,515（见 §4 分账） |
| 另：decree.py/db.py 侧直接删除（§3） | ~130+ | 不计入上两行（非 issues/flows 触及面） |
| 留内不迁（事件门闩求值引擎等） | ~1,000+ | 见 §6 |
| 邻接面（改 import 不搬家） | ~360 | `apply_issue_inertia_and_ongoing` 9113-9386（274）、`_apply_levy_driven_transfers` 7569-7650（82）等 |

分段口径说明：§2 各段行数含段内空行/注释，段间空行归属有 ±数行取舍；体内总计以 7756–9099 = 1,344 实量为准，§2 体内分段之和与它的差（≤20 行）即此类边界空行。

## 2. per-实体迁移清单

目标目录名按 ADR 0150 决定 1 的 `ming_sim/entities/<entity>/`。「体内行数」= `apply_score_extraction` 本体内该段所占行；「体外 helper」= 独立顶层函数，绝大多数为单实现纯移动候选（调用方清单已逐一 grep 核实）。

### 2.1 entities/dossier（案卷：参与人 / 执行格终值 / 授权账）

| 段 | 现位置 | 行数 | 分类 | 关联测试 | 顺序依赖 |
|---|---|---:|---|---|---|
| `dossier_participants` + `secret_dossier_participants` 两段调用 | issues.py:7791-7810 | 20 | 行为改动（包段契约） | test_secret_dossier_participants_1252.py、test_decree_dossiers_571.py | sanitize 之后即可；authority_set 来自编排器 ctx 冻结输入（7798/7806） |
| `_apply_dossier_participant_items` | issues.py:7356-7427 | 72 | **纯移动**（唯一调用方 7795/7802） | 同上 | — |
| `dossier_executions`（执行格终值） | issues.py:7811-7879 | 69 | 行为改动（段契约 + 拒收形状归一） | test_dossier_reported_progress_619.py、test_deformation_dual_rail_622.py、test_decree_dossiers_571.py | 依赖 `due_review.dossiers_with_pending_due_review` 接管窗闸（7815-7816，fail-loud 不可 fail-open）；须早于信用事件段（9009） |
| `authority_changes` 循环 | issues.py:7880-7908 | 29 | 行为改动 | test_authority_ledger_611.py、test_revoke_authority_materialize_523.py、test_authorization_materialize_528.py | 成功项在 8857-8864 触发段尾 commit——commit 归编排器后此耦合消失 |
| `_apply_authority_change_item` | issues.py:98-227 | 130 | **纯移动**（唯一调用方 7891） | 同上 | — |
| `_payload_owned_dossier_for_origin` | issues.py:228-250 | 23 | **纯移动**（双调用方 8099 economy 判重 + authority 链） | test_army_pay_decree_1503.py | 共享件，建议住 entities/dossier 供 economy 段 import |
| 呈现侧 | 无 | 0 | — | — | — |

小计：体内 118 + 体外 225 = **343 行**。

### 2.2 entities/character（人物：pre/post-issue 拆分 + `_apply_person_changes`）

| 段 | 现位置 | 行数 | 分类 | 关联测试 | 顺序依赖 |
|---|---|---:|---|---|---|
| 人物 normalize/canonicalize + legacy 兼容入口 | issues.py:7916-7929 | 14 | 行为改动（归一化真源 `person_delta_adapter.normalize_person_changes` 已独立成模块，116 行，顺手共置） | test_person_delta_adapter.py、test_production_person_key_contract_558.py | 须早于一切段内消费 |
| pre/post-issue 拆分 `_split_pre_issue_person_changes`（评定=pre，余=post）+ 战略战果拆出 | issues.py:7953-7974 | 22 | 行为改动（nested def 提取为编排器件） | test_person_write_inventory.py | **段序硬约束**：pre 在 issue tracker 前（8254-8257），post 在战略重放后（8511-8514）；ADR 决定 4 明言此约束入登记表 |
| 赦免冲突闸 `_amnesty_conflict_power_ids` | issues.py:7976-8025 | 51 | 行为改动（nested def 提取；跨 character×power 守卫） | test_power_section_rejections.py | 须早于 power_updates 段（8238 消费其结果） |
| legacy 拒收注记 + `_apply_normalized_person_changes` wrapper | issues.py:8027-8068 | 42 | 行为改动（legacy 别名注记随段契约归一后可简化） | test_person_delta_adapter.py | — |
| `_apply_person_changes` 本体 | issues.py:6544-7338 | 795 | **纯移动主体**；但 `external_transaction` 参数与内部快照调用为行为改动接缝 | test_memory_person_changes.py、test_person_transit_write_667.py、test_personnel_origin_prompt_558.py、test_person_archive_contract_index.py、test_person_archive_schema.py | 经 wrapper 被 pre/post/战略三路调用 |
| `apply_office_appointment` | issues.py:6383-6543 | 161 | **纯移动**（调用方 6873/6944 均在 `_apply_person_changes` 内） | 同上 | 随 `_apply_person_changes` 同目录 |
| 人物写快照/恢复族（`_snapshot_person_write_state`/`_snapshot_content_character_rows`/`_restore_content_character_rows`/`_restore_person_write_state`） | issues.py:6153-6310 | 158 | **删除/上收**：ADR 决定 3——段不做内存态快照/恢复，回滚后由最外层统一 `reload_state_from_db` | test_applier_contract.py（collector 事务/镜像生命周期行为迁移复用） | 固定点内一次到位 |
| `_restore_person_content_from_snapshot` | issues.py:4941-4953 | 13 | 同上（删除/上收） | 同上 | — |
| `_legacy_person_report_section` | issues.py:7339-7355 | 17 | **纯移动**（唯一调用方 8030） | — | — |
| `_canonicalize_person_change_names` + `_person_change_name` | issues.py:4037-4058 / 4027-4036 | 32 | **纯移动**（物理位置在战略簇 3953-4940 内，归属 character） | test_person_delta_adapter.py | — |

小计：体内 129 + 体外 1,176 = **1,305 行**（其中快照族 171 行为删除/上收，非搬家）。

### 2.3 entities/fiscal（财政：removes→creates→changes + 加派账）

| 段 | 现位置 | 行数 | 分类 | 关联测试 | 顺序依赖 |
|---|---|---:|---|---|---|
| `fiscal_removes`（裁撤） | issues.py:8528-8602 | 75 | 行为改动（循环体机械提取 + commit= 删除） | test_section_fiscal_rejections.py、test_fiscal_beyond_intent_1260.py | **removes 最先**（8528 注释：优先级最高，先于 creates/changes） |
| `fiscal_creates`（新立） | issues.py:8604-8706 | 103 | 行为改动 | 同上 + test_covert_levy_651.py | 先于 changes（8604 注释：「新立关税+立即调率」同月落地）；commitment 去重依赖 issue tracker 产出的 `commitment_economy_carriers`（8274-8287）→ **fiscal 段须在 issue tracker 段后** |
| `fiscal_changes`（调率，含损耗对递延批写） | issues.py:8708-8856 | 149 | 行为改动 | test_section_fiscal_rejections.py、test_pay_order_override_653.py | 在 removes/creates 之后；段尾 commit（8861-8864）删除归编排器 |
| `_norm_int_leaf`（nested） | issues.py:8516-8526 | 11 | 行为改动（提取为 fiscal 段内件） | — | — |
| `_write_fiscal_config_change` | issues.py:7651-7671 | 21 | **纯移动**（双调用方 7748/8811，7748 在 `neutralize_covert_fiscal_effects` 内——verdict 侧邻接面，import 改径） | test_section_fiscal_rejections.py | — |
| `surcharge_decrees` 段（加派明渠逐省累积账） | issues.py:8132-8137 | 6 | 行为改动（包段） | test_surcharge_causal_chain_650.py | 须早于 population_transfers 段（8150：同旨人口后果由加派账唯一拥有，重复者拒收） |
| `_apply_surcharge_decrees` + `_surcharge_population_pool_members` | issues.py:7439-7568 / 7428-7438 | 141 | **纯移动**（唯一落库调用方 8133；`_apply_levy_driven_transfers` 7569-7650 共 82 行是 decree.py:2407 的月初旧账缝，**邻接不迁**） | test_surcharge_causal_chain_650.py | — |

小计：体内 344 + 体外 162 = **506 行**。

### 2.4 entities/army / entities/region / entities/power（军务外势）

| 段 | 现位置 | 行数 | 分类 | 关联测试 | 顺序依赖 |
|---|---|---:|---|---|---|
| `new_armies` 建军循环 | issues.py:8210-8214（+战略重放内 8458-8464） | 12 | 行为改动（包段；db.create_armies_from_extraction 不动） | test_military_order_materialize_521.py、test_army_pay_decree_1503.py | **先建军再 army_delta**（8205 注释），入登记表 |
| `region_delta` 循环 | issues.py:8215-8220（+重放 8465-8472） | 14 | 行为改动（db.apply_region_deltas 不动；pseudo_event 8191-8201 随编排器） | test_region_cannon_delta.py、test_region_citydefense.py | 与 army 同批 |
| `army_delta` 循环 | issues.py:8221-8226（+重放 8473-8480） | 14 | 行为改动 | test_army_firearms.py | 在 new_armies 后 |
| `power_updates` 段 | issues.py:8231-8252 | 22 | 行为改动 | test_power_section_rejections.py、test_bandit_power_model_190.py | 须在赦免冲突闸（7976-8025）之后；8238-8246 的拒收逻辑随段走 |

小计：体内约 62 行（三实体合并计，pseudo_event 11 行归编排器）。体外无 helper（落库原语全在 GameDB，不动）。

### 2.5 entities/metric / entities/economy / entities/faction / entities/class / entities/population（内政五段）

| 段 | 现位置（体内） | 体外 helper | 行数（体内+体外） | 分类 | 关联测试 | 顺序依赖 |
|---|---|---|---:|---|---|---|
| `metric_delta` | issues.py:8070-8071 | flows.py:908-941 `_apply_metric_dict` | 3+34 | helper **纯移动**（多调用方：db.py:13643 verdict 伪 delta 回调——决定 5 上浮后消亡；tracker 实体后果 5165/5182/5205/5900/6032；inertia 9160/9183——均 import 改径） | test_issue_entities.py | 无前置 |
| `economy_moves`（含 #1503 案卷判重前置过滤 8080-8106） | issues.py:8072-8115 | flows.py:1107-1316 `_apply_economy_list` | 44+210 | helper **纯移动**（多调用方：covert_progress.py:420、db.py:13921、tracker/inertia 多处）；体内判重过滤 44 行为行为改动 | test_economy_section_rejections.py、test_army_pay_decree_1503.py | 无前置 |
| `faction_delta` | issues.py:8116-8124 | flows.py:2050-2101 `_apply_faction_dict` | 9+52 | helper **纯移动**（多调用方：980、tracker 5187/5210/5905/6038、inertia 9162/9185） | test_faction_class_section_rejections.py | 无前置 |
| `class_delta` | issues.py:8125-8131 | flows.py:2287-2352 `_apply_class_dict` | 7+66 | helper **纯移动**（调用方 986/8127） | test_faction_class_section_rejections.py | 无前置 |
| `population_transfers`（含加派重复拒收前置 8140-8157） | issues.py:8138-8161 | flows.py:2102-2286 `_apply_population_transfers` | 24+185 | helper **纯移动**（调用方 7645 levy 缝/8158）；体内 24 行为行为改动 | test_population_transfers_649.py、test_population_transfers_662.py、test_population_unit_648.py | 须在 surcharge 段后（加派账唯一拥有同旨人口后果） |
| 共享 `_value_reject` | — | flows.py:2035-2049 | 15 | **纯移动**（faction/class 共用，住 entities 共享件或随首迁者） | — | — |

小计：体内 87 + 体外 562 = **649 行**。这五段是全仓最干净的纯移动面：helper 单实现、语义自含、无段间耦合。

### 2.6 entities/issue（局势 tracker）

| 段 | 现位置 | 行数 | 分类 | 关联测试 | 顺序依赖 |
|---|---|---:|---|---|---|
| tracker 调用点（advances/new_issues/close_issues/cancels 四键转发） | issues.py:8259-8272 | 14 | 行为改动（入参含 post_issue 人物变更门闩快照、战略闸 id 集——编排器 ctx 供给） | test_advances_section_rejections.py、test_new_issues_section_rejections.py、test_close_issues_section_rejections.py | **须在 pre-issue 人物变更之后**（门闩读人物落态）；产出 new_issues 供 fiscal 承诺去重与战略重放消费 |
| `apply_issue_tracker_output` 本体（内部：advances 5107-5234 / new_issues 5235-5759 / closes 5760-5935 / cancels 5936-6060） | issues.py:5053-6067 | 1,015 | **纯移动主体**；`external_transaction`/commit 接缝为行为改动 | 同上 + test_decree_commitment_creation_136.py、test_decree_commitment_schema_136.py、test_event_trigger_gate.py、test_event_outcome_retry.py | — |
| `_apply_issue_entities`（结案/失败实体后果） | issues.py:3678-3831 | 154 | **纯移动**（调用方 2811/2834/5190/5213/5426/5912/9169/9190 含 inertia 邻接面） | test_issue_entities.py | 随 tracker 同目录 |
| `_apply_issue_buildings`（建筑落库唯一路） | issues.py:368-436 | 69 | **纯移动**（调用方 5188/5211/5906/9163/9186） | test_issue_entities.py | 同上 |
| `_initiative_resolve_pairing_warnings` + `_emit_pairing_warnings` | issues.py:4978-5052 | 75 | **纯移动** | test_initiative_resolve_pairing.py | — |
| `_has_economy_entry` | issues.py:4954-4977 | 24 | **纯移动** | — | — |
| 呈现 helper 读侧共置（web_app.py:69 私有 import 的那组：`commitment_progress_payload` 527-566 / `_commitment_arrears_remaining_text`+`commitment_display_text` 567-606 / `commitment_timed_bar_value`+`_commitment_bar_value` 607-643 / `_format_issue_ongoing` 2856-2876） | issues.py 上述行 | 138 | **纯移动**（ADR 决定 8 明言顺手迁入读侧；web_app import 改径） | test_decree_commitment_schema_136.py | 任意时点，无依赖 |

小计：体内 14 + 体外 1,475（含读侧 138）= **1,489 行**——单实体最大块。

### 2.7 entities/secret_order（密令）

| 段 | 现位置 | 行数 | 分类 | 关联测试 | 顺序依赖 |
|---|---|---:|---|---|---|
| `secret_order_updates`（推演副作用 + disclosed 公共知识晋升） | issues.py:8874-8953 | 80 | 行为改动（包段；8952 的裸 `except Exception` 拒收形状须归一到 RejectedItem） | test_secret_order_section_rejections.py、test_secret_order_update.py、test_secret_order_isolation_883.py | 无前置 |
| `secret_order_closes`（#1504 已退役真源，一律拒收留痕） | issues.py:8955-8966 | 12 | 行为改动（保留为永久拒收段） | test_secret_order_payoff_1504.py | 无前置 |

小计：**92 行**。全仓最小段，适合做 fixed-point 后第一个深化示范。

### 2.8 编排器/框架件（不属单一实体目录）

| 件 | 现位置 | 行数 | 分类 | 说明 |
|---|---|---:|---|---|
| 函数头 + 事务接管判定 + `_register_runtime_rollback_snapshot` + 关系 pre-roster | issues.py:7756-7782 | 27 | 行为改动 | 事务边界归编排器独占（决定 3）；pre-roster 观察点保留为编排器职责 |
| `sanitize_delta_shape` + `validate_delta_shape` + 体内调用 | issues.py:6311-6373 + 7783-7784 | 65 | 框架前置段 | 消费 EMPTY_EXTRACTION 作 key 白名单（6320-6340，懒 import）——registry 权威关系见 §5 |
| breach_plea 哭谏消费 | issues.py:7785-7790 | 6 | 行为改动（包段；实现已在 breach_plea.py） | **须先于 cancels 物化**（7785-7786 注释），入登记表 |
| 战略事件簇（拆分/路由/outcome 标签/预检/物量判定 全 24 helper，已扣出归属 character 的 `_canonicalize_person_change_names`/`_person_change_name` 32 行，避免与 §2.2 双计） | issues.py:3953-4940 | 956 | 求值/拆分 helper **纯移动**；其中 `_strategic_event_result_preflight_error` 4460-4905（446 行）为战果重放预检 | 跨实体编排子机，建议住编排器邻接（非单一实体目录）；事件门闩求值引擎本体（`_eval_gate_key`/`_gate_passed` 等 2356-2544）**留内**（ADR 决定 8：求值器非落库段） |
| 战略战果体内编排（输入闸预备 7909-7915 / gate 预备 7930-7951 / 实体 delta 拆分 8162-8189 / 压拒 def 8289-8360 / 压拒扫描 8362-8377 / 重放主循环 8379-8510 / pseudo_event 8191-8201） | issues.py 上述行 | 293 | 行为改动 | **须在 issue tracker 段后**（消费 deferred_trigger new_issues）；重放内逐类调用 army/region/power/character 段 → 段序约束：战略重放是这些段的**第二批调用方**，登记表须支持同段多次调用或重放整体作为一个复合段 |
| `commitment_economy_carriers` 提取 | issues.py:8274-8287 | 14 | 行为改动 | 编排器在 fiscal 段前从 issue 段产出备 ctx |
| 信用事件后置段 | issues.py:8982-9039 | 58 | 行为改动（实现已在 credit_events.py） | **须在全段落格校验后**（0079：只消费未 rejected 项，禁为被拒项立伪信用档） |
| relation 边事件后置段 | issues.py:9041-9054 | 14 | 行为改动（实现已在 relations.py） | **须在全批人物变更落定后**（T1 B 案：端点 ∈ pre∪post 名册并集，9051-9053） |
| validate/module 拒收聚合 | issues.py:8968-8980 | 13 | 行为改动 | 框架集中补 turn/section 后归 RejectedItem 单形状 |
| 段尾 commit + 恒空兼容键（appointments/character_status_changes/character_power_changes/office_changes） | issues.py:8857-8872 | 16 | **删除** | commit 归编排器；恒空键是 ADR 点名的病灶 |
| `state.clamp()` + ~35 键返回 dict | issues.py:9056-9099 | 44 | 行为改动 | → 类型化 `SettlementOutcome`，无恒空兼容键/双份键（决定 6） |
| `_resolve_victory` | issues.py:9102-9112 | 11 | **纯移动**（编排器尾部或框架段） | 消费 `emperor_fate` |

小计：**约 1,520 行**（含战略簇 956；体内编排件 ≈490 + 体外 helper ≈1,030）。

## 3. 删除账（不搬家，直接消亡）

| 删除对象 | 位置 | 规模 | 依据 |
|---|---|---:|---|
| `_collect_inline_rejections` 递归桥（含硬编码特例）+ 2 调用点 | decree.py:2273-约2330；调用点 2436/2472 | ~60 行 | 决定 2 fixed point |
| GameDB `owns_rejection_collector` 分支 ×3 | db.py:14532-14629、17607-17727（`rejection_collector` 全文件 36 处引用） | 3 处分支 | 决定 2 |
| GameDB verdict 路反向合成伪 delta 的懒 import 回调（`from ming_sim.flows import _apply_metric_dict` db.py:13643、`_apply_economy_list` db.py:13888 等，ADR 全文称 ≥5 处，本 HEAD 可直指 2 处落库回调 + breach_plea/applier 等编排层懒 import 若干） | db.py:13643、13888 等 | ≥5 处 | 决定 5（verdict 效果物化上浮编排层） |
| `apply_score_extraction` 名与返回 dict | issues.py:7756-9099 | 整体退役 | 决定 6，不留 deprecated 壳 |
| 恒空兼容键 4 枚 + 双份键 | issues.py:8866-8872、9057-9099 | ~10 行 | 决定 6 |

## 4. 纯移动 vs 行为改动分账汇总

| 分类 | 行数 | 构成 |
|---|---:|---|
| **纯移动**（整函数搬迁，仅 import 改径，零行为差） | ≈4,460 | dossier helpers 225 + character 1,005（795+161+17+32）+ issue 1,475（含读侧 138）+ fiscal helpers 162 + 内政五段 flows helpers 562 + 战略求值/拆分 helper 956 + sanitize 63 + victory 11 |
| **行为改动**（段契约化：commit=/事务/快照删除、拒收形状归一 RejectedItem、返回 SectionResult、nested def 提取、dict→SettlementOutcome） | ≈1,515 | 体内 1,344 全量段契约化（其中接缝重写约 240：事务头 27、commit 点+恒空键 16、return 44、wrapper/nested defs ~150；余 ~1,100 为循环体机械提取 + 包装层新写）+ character 快照族 171 删除/上收 |
| **删除**（decree.py/db.py 侧，在 5,974 触及面之外） | ~130+ | §3 全表（恒空键 16 行属体内 1,344 子集，不重复计） |

分账方法说明：体内 1,344 行的循环体逻辑（校验→拒收→落库调用）逐行平移到段模块属机械提取，但每个循环都必须换签名（`commit=` 删除、返回 SectionResult、拒收项改 RejectedItem），故整段记「行为改动」，仅包装层是新写代码；体外 helper 若调用方只改 import 路径则记「纯移动」。「issues.py 9,456 行全为机械搬家」不成立：迁移触及面 5,974 中纯移动仅 ≈4,460，余 ≈1,515 为段契约化/删除/上收；此外 ~1,000+ 行事件门闩求值引擎等留内不迁（§6）、~360 行邻接面只改 import，decree.py/db.py 侧另有 ~130+ 行直接删除（§3）。

## 5. registry 权威关系（simulation.py:921-985）

### 5.1 现状：四个「真源」的实读事实

| 常量/机制 | 位置 | 内容 | 消费方（本 HEAD 实核） |
|---|---|---|---|
| `EXTRACTION_MODULES` | simulation.py:921 | 5 个 extractor 模块的**并发装配序**（internal/military_external/issues/personnel_secret/relations） | simulation.py:1782/1839-1907（extractor 并发 fan-out）、decree.py:1544/1592 |
| `EMPTY_EXTRACTION` | simulation.py:923-960（36 键） | canonical delta 顶层 key 全集 + 各键空值形状 | simulation.py:1490（`_sanitize_module_output` 补空）、1779（deepcopy 合并底）；issues.py:6320-6340（`sanitize_delta_shape` 以其为 key 白名单，懒 import） |
| `MODULE_FIELDS` | simulation.py:962-976 | 模块→允许产出字段白名单（misroute 剔除依据） | simulation.py:1374-1378（extractor prompt 契约）、1488-1504（`_sanitize_module_output`）；测试 test_parallel_extractors.py、test_extractor_misroute_surface.py、test_extractor_slot_routing_629.py、test_relation_capture_633.py 等 7 份直接引用 |
| `_FIELD_OWNER_MODULE` | simulation.py:982-985 | 由 MODULE_FIELDS **派生**的反向图（`setdefault` 保留首见 owner；`new_issues` 双 owner 的首选 owner=issues） | simulation.py:1502-1504（misroute 留痕指向） |
| 现执行顺序 | issues.py:7756-9099 函数体 | 落库段序（仅活在代码物理顺序与注释里：先建军再 army_delta 8205、pre/post-issue 7953、removes→creates→changes 8528/8604） | 无（无机器可读表示） |

### 5.2 关键实读发现：有 7 个键没有 apply_score_extraction 内的落库段

`dossier_progress_reports`、`faction_denunciations`、`dossier_reconciliations`（decree.py:2389/2394/2398 在 settle 尾部机械落库）、`covert_exec_selections`（decree.py:2429 → covert_progress）、`world_advance`（纯 passthrough，issues.py:9085）、`emperor_fate`（`_resolve_victory` 9105 消费）、`事件结局`（战略 outcome 标签闸 4390/4449 消费）。**任何「从登记表派生 EMPTY_EXTRACTION」的方案，这 7 键必须以框架段/机械段条目登记，否则派生缩键、`sanitize_delta_shape` 会开始拒收合法键**——这是派生案的硬约束。

### 5.3 建议（择一）：登记表为唯一手写真源，三常量全部派生或消亡

**采纳案：登记表条目 = `(段名, lazy module_path, delta_keys 含空值工厂, extractor_owners tuple)`，顺序即段序。**

- **现执行顺序 → 被替代**：登记表物理顺序即唯一段序真源（ADR 决定 4 已授权）。先建军再 army_delta、pre/post-issue、removes→creates→changes、surcharge→population、breach_plea→cancels、人物落定→relation 边事件，全部由条目顺序表达，注释降为说明。
- **`EMPTY_EXTRACTION` → 消亡，改派生视图**：`empty_extraction() = {key: factory() for entry in registry for key, factory in entry.delta_keys}`（模块级惰性缓存）。`sanitize_delta_shape` 与 simulation.py:1490/1779 改读派生视图。若保留手写 EMPTY_EXTRACTION，即与登记表 `delta_keys` 形成第二份顶层 key 清单——判词明令禁止，且 36 键清单正是历史上靠人肉同步的漂移面。
- **`MODULE_FIELDS` → 消亡，改派生视图**：`MODULE_FIELDS = {module: {key for entry in registry if module in entry.extractor_owners}}`；`_FIELD_OWNER_MODULE` 沿用现 `setdefault` 语义从登记表顺序派生（首选 owner=条目序首见，与 982-985 现行行为逐键等价，含 `new_issues` 双 owner=（issues, personnel_secret）的情形——`extractor_owners=("issues", "personnel_secret")` 一条即表达，不再靠 978-981 注释维持）。`_sanitize_module_output` 与 prompt 契约（1374-1378）改读派生视图，白名单语义逐键不变，7 份直接引用测试改断派生视图。
- **`EXTRACTION_MODULES` → 保留，不替代**：它是 extractor 侧并发装配序（读/产轴），与落库段序（写轴）不同轴，登记表不复制该清单。**不加任何「两集等价」启动断言**（三审删除，理由见下「护栏删除论证」）。

**否决案（「反向派生」：登记表只钉段序，key/白名单仍手写于 simulation.py，登记表从 MODULE_FIELDS 派生 key）**：MODULE_FIELDS 是「模块→产出」投影，不含落库段序信息，段序仍须在登记表手写；而段→key 映射一旦手写即与 MODULE_FIELDS 的 value 集合构成第二份 key 清单——恰好踩判词红线。且 `sanitize_delta_shape` 需要的空值形状在 MODULE_FIELDS 里根本不存在，仍需第三处手写。否决。

**不双写论证**：手写事实只剩一处——登记表条目（段名/路径/key+空值工厂/owners/顺序）。EMPTY_EXTRACTION、MODULE_FIELDS、_FIELD_OWNER_MODULE 三者的全部信息（key 全集、空值形状、模块↔键归属、首选 owner）均为登记表四个字段的机械投影，派生函数各十余行，无信息增量。

**护栏删除论证（为何派生方案无需「owner 集 ≡ EXTRACTION_MODULES」启动断言）**：派生后 MODULE_FIELDS 不再是独立事实，只是登记表的只读投影，两集合即便漂移也不构成第二真源——所有消费方（prompt 契约 1374-1378、`_sanitize_module_output` 1488-1504）只读派生视图。且三种漂移失败模式已被既有 seam 响亮覆盖，断言无增量检出能力：

- **模块在 EXTRACTION_MODULES 但无 registry owner** → 其派生白名单为空 → 该模块产出的每个 key 被 `_sanitize_module_output` 按 misroute 剔除并留痕上浮（`module_misroute_rejections` 进返回与拒收报告，非静默吞），test_extractor_misroute_surface.py 直接覆盖此面。
- **registry owner 名不在 EXTRACTION_MODULES** → 该模块永不跑，对应段收到空集、输出为空，无静默错写；7 份直接引用测试（test_parallel_extractors.py、test_extractor_slot_routing_629.py、test_relation_capture_633.py、test_secret_dossier_participants_1252.py 等）逐模块断言白名单/槽位内容，集合漂移立刻红。
- **registry 条目 lazy module_path 写错** → fail-loud import（ADR 0005），首次 settle 即炸。

更根本地，该断言把「extractor 并发装配集」（读/产轴）与「落库段 owner 集」（写轴）两个不同轴概念强绑等价——现行码中二者恰相等只是当前事实而非领域不变式（extractor fan-out 已允许不占落库段的 side leg：simulation.py:1848/1891 的 N+1 路 side_leg 即先例）；把偶合钉成断言属投机通用性，且提不出真实可复现的失败证据。故删。

## 6. 留内不迁与邻接面

| 件 | 位置 | 处置 | 依据 |
|---|---|---|---|
| 事件门闩求值引擎（`_eval_gate_key`/`_eval_gate_key_str`/`_gate_passed`/`_gate_sql_field` 等） | issues.py:2356-2544 一带 | **留内**：求值器非落库段 | ADR 决定 8 |
| `apply_issue_inertia_and_ongoing`（惯性/ongoing 自动月支） | issues.py:9113-9386（274 行） | 邻接面：不在本次替代范围；其调用的 `_apply_metric_dict`/`_apply_economy_list`/`_apply_faction_dict`/`_apply_issue_buildings`/`_apply_issue_entities`（9160-9190）搬迁后 import 改径 | 判词范围=apply_score_extraction 替代 |
| `_apply_levy_driven_transfers` | issues.py:7569-7650（82 行） | 邻接不迁：decree.py:2407 的月初旧账消费缝 | 同上 |
| `neutralize_covert_fiscal_effects` | issues.py:7672-7755（84 行） | 邻接不迁：covert_levy.py:121 verdict 侧调用；决定 5 上浮时随 verdict 线处理 | 同上 |
| `show_active_issues`/`issue_to_payload`/`_format_inertia` 等 CLI/呈现 | issues.py:2850-2915 等 | 留内或后续读侧波次 | ADR 决定 8「呈现 helper 顺手迁」仅限 web_app 私有 import 的那组（§2.6 已列） |

## 7. PR 切分建议（纯移动先行；任何独立可合 PR 都不是薄壳态）

判词要求「优先把单实现纯移动拆为独立可合 PR」；ADR 0150 Considered Options 否决「目录薄壳 + 实现原地」。据此切分两档：**可独立合并的只有 PR-0 系列（实现随迁的整函数纯移动，零行为差、零壳）**；fixed point 是**单个 PR 内部的 commit 链**（PR-1），骨架、类型、登记表与**全部剩余实现的真实搬家**一次到位——壳态/半搬态只存在于 PR-1 的中间 commit，**不得独立落目标分支**。PR-0 各 PR 互相无依赖、可按任意序合入，每 PR 后跑 `python -m pytest tests/ -q -n auto` 全量即证。

| PR | 内容 | 规模 | 可合性/理由 |
|---|---|---:|---|
| PR-0a | entities/population + entities/faction + entities/class + entities/metric + entities/economy：flows.py 5 个 `_apply_*` helper + `_value_reject`（562 行）迁入，issues.py/db.py/covert_progress.py/decree.py 调用方 import 改径 | ~570 行 | **可独立合并**：实现随迁纯移动；多调用方早迁可让 PR-1 的 diff 只剩编排重写 |
| PR-0b | entities/dossier：`_apply_dossier_participant_items`+`_apply_authority_change_item`+`_payload_owned_dossier_for_origin`（225 行） | ~230 行 | **可独立合并**：单实现、调用方全在 issues.py 内 |
| PR-0c | entities/fiscal 读侧件：`_apply_surcharge_decrees`+`_surcharge_population_pool_members`+`_write_fiscal_config_change`（162 行） | ~170 行 | **可独立合并**：唯一落库调用方 8133；`neutralize_covert_fiscal_effects` 内 7748 调用 import 改径 |
| PR-0d | entities/issue 读侧呈现 helper 4 枚（138 行），web_app.py:69 私有 import 改公开路径 | ~140 行 | **可独立合并**：ADR 决定 8 明言顺手迁；与写侧零耦合 |
| PR-0e | entities/character 纯 helper：`apply_office_appointment`+`_legacy_person_report_section`+`_canonicalize_person_change_names`+`_person_change_name`（210 行） | ~210 行 | **可独立合并**；`_apply_person_changes` 本体（795 行）因快照族耦合决定 3，随 PR-1 走，不抢跑 |
| **PR-1（地基 fixed point：单 PR、内部 commit 链，不可拆成多个独立合并 PR）** | entities/ 骨架 + ApplyContext/SectionResult/RejectedItem 承重 + 有序登记表（§5.3 条目形状）+ `settle_delta` 接任内层子核 + **全部剩余实现随段真实搬家**——体内 1,344 行段契约化；tracker 1,015 + `_apply_issue_entities`/`_apply_issue_buildings`/pairing 族/`_has_economy_entry`（322）沉 entities/issue；`_apply_person_changes` 795 沉 entities/character + 快照族 171 删除/上收编排器统一 reload；战略子机 956 helper + 293 体内编排入编排器邻接；sanitize 63 + victory 11 成框架段——+ §3 删除（`_collect_inline_rejections`/`owns_rejection_collector`/恒空键/伪 delta 回调）+ `apply_score_extraction` 退役 + `settle_with_delta` 内部落库调用点改调（decree.py:2411 一带）+ **直调旧入口测试同步迁移**（test-disposition 的 45 个迁移函数改调新 adapter/`settle_delta` 入口 + 6 个死类型绿卡删除——与旧入口退役不可分，不入本 PR 则删入口即红）+ **主干·adapter 臂 23 个函数 import 机械改径**（`apply_issue_tracker_output` 沉 entities/issue 后调用方改径，与 PR-0 系列同款零行为差） | ~4,970 行触及 + §3 删除 + 测试面 74 函数（45 迁 + 6 删 + 23 改径） | 决定 2 fixed point：canonical 化、真实搬家与删旧桥同一 PR 一次到位——**「全段返回 SectionResult + 删旧桥」与「实现入目录」不可分，否则即被否决的薄壳态**；PR 内按实体分 commit（每 commit 实现只有一份、可测，中间 commit 允许旧编排器 import 已搬模块——决定 8），最终合并态单入口、无兼容层 |
| PR-2 | 测试参数化塌缩（不阻塞合并的质量整合）：section_rejections 家族 72 个公共主干函数（49 driver 臂 + 23 adapter 臂）参数化塌缩——入口在 PR-1 已就位，塌缩前后均绿，故可独立成 PR；独立最短 tracer 逐份保留不动。四类处置总账 72/86/45/6 不变 | 测试面 | 入口不变、纯测试内整合，天然满足波次纪律 |
| PR-3 | 实体逻辑深化小切片（一实体一 PR；首例建议 entities/secret_order，92 行最小段） | 小段 | 只深化实体逻辑，不再补契约 |
| PR-4 | GameDB verdict 效果物化上浮（决定 5）：施工前先附逐 action_type 的 effect_owner × execution_surface × 现行拒收处置矩阵（四份证据之二） | db.py 懒 import 面 | 依赖 settle_delta 已能按 action_type 路由段 |

波次纪律（ADR 决定 8 + 三审口径）：**独立可合 PR 的判定标准 = 合并后目标分支上不存在「壳在、实现原地」两张皮**——PR-0 系列满足（实现随迁），PR-1 满足（合并态全量到位，含直调旧入口测试同步迁移，故合并后全量测试仍绿；其中间 commit 不满足，故不许中途拆合），PR-2 起只做不阻塞的测试整合/深化逻辑，天然满足。

## 8. 复核指引

- 行数复算：`grep -n "^def " ming_sim/issues.py` 得 175 个顶层 def，本清单所有体外 helper 行数=起止 def 行差实量；体内段行数以 §2 各表「现位置」逐段 sed 复核。
- 调用方复算：§2 每个「纯移动」判定均附调用方行号，可 `grep -rn <fn> ming_sim/` 复核。
- registry 消费方复算：`grep -rn "EMPTY_EXTRACTION\|MODULE_FIELDS\|_FIELD_OWNER_MODULE\|EXTRACTION_MODULES" ming_sim/ tests/`（本 HEAD 命中见 §5.1 表）。

---
记录 HEAD：`3ef603c68bb7b7276b4948a55ff0ecbfee63da71`（2026-08-27 实读）。
