# issue #1571 / ADR 0151 施工证据：纵切 PR 波次与依赖序

- HEAD：`e88cc29c28a91c28129b320588934aa12768792b`（`e88cc29c Merge pull request #1580 from Akagilnc/kimi/issue-1572`），分支 `kimi/issue-1571`。
- 本文回应大理寺一审打回项：「优先按 schema、护送对账、监督检举、进展双轨、核心状态机等可独立 seam 做纵切 PR」；二审（run 01a04322）判 continue 后按「未证不可再拆就要拆」再拆三片、并统一与 boundary-inventory 的归属矛盾。**结论先行：采纳纵切，不走单 PR**；16 片均可独立合并，每片合并后目标分支不存在壳/双实现（论证模板与各片逐项论证见 §2）。单 PR 案因此无需再证——其不可拆性主张已被 §2 的逐片可合性反证推翻。
- 方法分组口径与 boundary-inventory（另票证据）同源（成案/查询读面/进展双轨/护送对账/监视检举/连坐毁约/状态机/verdict 物化），且**方法归属一律以 boundary-inventory 为真源**（毁约/连坐拆分形状以 breach-liability-split §2 为真源），本文片内容跟随修正；但本文**所有数字均为本 HEAD 用 AST+grep 自行核实**，不依赖该文件存在。测试总数口径另票核定，本文引用处写「见 test-disposition」。
- 施工前置：排在 #1572 PR-1（实体目录地基）与 PR-4（verdict 效果物化上浮）之后（ADR 0151 决定 1）。
- 复审修订（owner 裁定，decision key `issue1571-source-revision-owner-ruling-A`）：PR-1 拆为 PR-1a（schema DDL 就位）+ PR-1b（迁移组自治）；PR-6 拆为 PR-6a（actual 轨）+ PR-6b（reported 轨 + 监视 origin 读面）；全片测试政策删 blanket「断言零变化」改为「不弱化行为断言，删除/改写冻结 HEAD 中违法的盯文与盯源码测试」。片数 14 → 16，其余片号不变。

## 1. 规模总账（本 HEAD 实测）

GameDB = `ming_sim/db.py` 22,392 行 / 536 方法（AST 实数，与 ADR 引文一致）。

| 项 | 实测 | 口径 |
|---|---:|---|
| 案卷块区间 | span **5,320 行**、**105 方法**（AST） | 含块内迁移 5 件与 verdict 物化族；旧口径 5,247 行 / 104 方法（不含 `_migrate_legacy_pending_review_secret_orders`），二审统一归 ensure_schema 迁移组后并入（boundary §1 为真源） |
| 区间外散点方法 | **393 行** = 随迁/段 181 + 留 GameDB 212 | 随迁/段：`_ensure_decree_dossier_locality_indexes`（12）+ directive 散点两段（46/45）+ actual 轨写读（78，含 `list_dossier_actual_rail` 15 段适配器拆分）。**留 GameDB**（实读 db.py 核：均不触案卷 13 表，boundary §2.2 为真源）：`list_night/list_promulgated_directives`（129，读口令账/turn_directives）+ `list_office/skill_grants_for_dossier`（18，读 office_change_records/skill_grants）+ directive 读缝（16）+ durable 轨读面（49，读 economy_ledger/fiscal_config_*） |
| schema DDL | **242 行 / 13 表** | ADR 决定 2 明列 12 表 + `faction_denunciations`（dossier_id 锚定卫星表，0077 检举随迁，合 13 表） |
| 迁移编排点 | init_schema 内一带 **~35 行** ensure_column/调用编排 | #654 属地列+复合索引、#562 break_rank 回填等顺序约束所在 |
| 迁移方法 5 组 6 件 | **220 行** | `_migrate_legacy_pending_review_secret_orders`（72）、`_migrate_legacy_secret_order_dossiers`（65）、`_migrate_reaction_value`+`_migrate_legacy_reaction_severity`（49）、`_ensure_decree_dossier_locality_indexes`（12）、`_backfill_proposed_appointment_break_ranks`（22） |
| **触及面合计** | **~5,540 行**（含 verdict 物化族 634 归 #1572 PR-4；留 GameDB 散点 212 不计） | **本票净额 ~4,900 行** + record_verdict 新写 |
| 生产触点 | **~137 处方法调用 / 18 模块** + **裸 SQL 14 处 / 7 模块** + **私有常量外部直读 3 处** | 逐方法 grep 实数，模块清单见 §4.3 |
| 测试面 | 关键词扫描 **936 函数 / 112 文件**（含 verdict 物化 ~119 归 0150）；本票 **~817** | 与判词「约 830」吻合；权威口径见 test-disposition |

裸 SQL 实核（ADR 称「10 处散在 8 个模块」，本 HEAD 实量 **14 处 / 7 模块**：issues 2、execution_pressure 3、breach_plea 1、decree 1、covert_levy 5、covert_progress 1、action_materialize 1——逐处清单施工时 grep 现查；含 covert_levy 的查询模板常量与 covert_levy 的 `faction_denunciations` origin 直读，后者为旧稿漏列，notary 开卷证实，boundary §3.2 同口径）。
私有常量外部直读 3 处实核：`issues.py` 与 `due_review.py` 各 1（直读 `GameDB._JOINT_LIABILITY_TRIGGERS`）、`supervision.py` 1（抄录成平行闭集 `EXECUTION_FORMS`，ADR 决定 6 点名消亡）。另 `supervision.py` 一处持有 `DENUNCIATION_TABLE`/`PRESENCE_TABLE`/`EXPOSURE_TABLE` 表名+列白名单——schema 知识外泄，随 PR-7 收编。

## 2. 纵切方案（16 片）

**「无壳/双实现」论证模板（每片适用）**：该片的方法从 GameDB 整体删除、迁入 `ming_sim/entities/dossier/`（段适配器件则迁出 GameDB 到段层，不入包），其生产调用点与测试调用点在**同一 PR** 内改径 store/段；GameDB 侧不留任何同名转发。机械可验：合并后 `grep -n "def <method>" ming_sim/db.py` 对片内每个方法命中 0；**测试政策（复审修宪，decision key `issue1571-source-revision-owner-ruling-A`）：每片只跑该片聚焦测试切片，绿即可合；最终收敛片（PR-14）合并后跑全量 `python -m pytest tests/ -q -n auto` 一次绿**。断言处置口径：**不弱化行为断言**——迁移不改写行为断言语义；但冻结 HEAD 中违法的盯文（断言 LLM 生成文本字面）与盯源码（断言内部结构/源码形态）测试属存量违宪（owner 全局硬规 12-14），随片删除或改写为行为断言、并在片 PR 描述逐条点名；行为主干、restore/幂等/失败边界断言一律保留，「不红即迁移正确性证据」口径（ADR 0151 决定 10）不变。片间允许「仍驻 GameDB 的方法改调 store」（正向调用改径，非壳）；**禁止反向**（store 回调 GameDB 案卷方法）——此约束决定 §3 依赖序。

行数 = 本 HEAD（e88cc29c）AST 函数跨度实量求和（含函数内注释/空行，全部重核，不照抄一审旧数）；测试数 = 该组方法名在 tests/ 的逐函数 AST 直调命中数（一函数命中多组时各组各计一次，跨组求和会重复计数，见 §4.4）。

### PR-1a【schema DDL 就位】

- 内容：`entities/dossier/` 包骨架；`ensure_schema(conn)` 承载 13 表 DDL（242 行）；`GameDB.init_schema` 的案卷 DDL 段改调它（ADR 0151 决定 8 编排点方向）。迁移 5 组 6 件与 init_schema 编排段**不随本片**（归 PR-1b）：本片合并后迁移方法与编排段暂留 GameDB，init_schema 体内「调 store DDL → 调本类迁移方法」全为 GameDB→store 正向 + 类内自调，无反向。
- 规模：~242 行 + 包骨架；生产调用点 1 处（init_schema 内部编排）；无公开读面变化。
- 聚焦测试：`test_rescript_draft_656.py`、`test_execution_pressure_654.py`、`test_pihong_dossier_1490.py`、`test_dossier_reported_progress_619.py` 中 PRAGMA/schema 断言直引处（迁移断言部分随 PR-1b）。本片聚焦测试绿即可合（测试政策见 §2 模板；全量一次在 PR-14 后）。
- 独立可合论证：DDL 只有一个编排调用点，搬走即单真源；迁移整组留 GameDB 由 init_schema 类内自调，不存在「包内 DDL + GameDB DDL」双写，中间态无壳/无双实现。

### PR-1b【迁移组自治 + ensure_schema 编排收口】

- 内容：迁移 5 组 6 件（220 行）+ init_schema 编排段（~35 行）迁入包，`ensure_schema` 扩为「DDL + 迁移」编排入口，`GameDB.init_schema` 案卷部分收缩为单行调用；**含 `_migrate_legacy_pending_review_secret_orders`**（归 ensure_schema 迁移组，boundary §1 为真源，不再留 GameDB；其案卷轨 3 处 self 调用在组内以私有读件/内联写自给，不反向调 GameDB；其 `secret_orders`/`game_state` 读写为 schema 期遗留数据迁移，随组随迁）；迁移顺序约束原样保留（§4.7）。
- 规模：~255 行；生产调用点 0 处（仅 init_schema 编排内部）。
- 聚焦测试：原 PR-1 聚焦集中的迁移断言直引处（`test_dossier_reported_progress_619.py` 等）。
- 依赖：PR-1a（DDL/包骨架就位——迁移组挂 `ensure_schema` 编排，表未建则迁移无可施）。
- 不可再拆论证：6 件迁移共用同一编排点与顺序约束（§4.7），逐件拆片会使前片迁移半留 GameDB 被 store 编排回调（反向，§2 模板明文禁止）或留转发壳；整组一次迁入后 GameDB 侧迁移方法清零，无壳/无双实现。

### PR-2【查询读面 kernel + 写原语 + 裸 SQL/私有常量收编】

- 内容：`_commit_dossier_write`（5）、`_dossier_row`（47）、`get_decree_dossier`（5）、`get_dossier_for_directive`（10）、`list_dossiers_for_directive`（10）、`get_dossier_for_secret_order`（6）、`list_referenceable_dossiers`（51）、`list_decree_dossiers`（22）、`list_decree_dossier_decisions`（28）、`list_closed_army_pay_dossiers_for_provenance`（39）、`list_decree_dossiers_for_simulation`（59）、`executable_decree_dossier_ids`（8）、**颁赏纯件 4 个**（`_is_army_pay_grant_payload` 6、`_grant_allocation_is_monthly` 2、`_grant_allocation_is_honorific` 2、`_normalize_army_pay_grant_payload` 44——纯 payload 函数、零 conn/state，实读核；boundary §2.2 已据实读自「段适配器」改归 store 私有）、**叶方法提前入 kernel**：`merge_execution_note`（31）、`dossier_authorizes_effects`（21）、公开常量 `DOSSIER_MODES`/`DOSSIER_REPORT_ORIGIN_*`；同 PR 收编裸 SQL 14 处中的 **12 处**与私有常量直读 1 处（`supervision.py` 抄录的 `EXECUTION_FORMS` 平行闭集消亡，改引 store 公开常量 `_DOSSIER_EXECUTION_OUTCOMES` 公开化）。**改口径（二审统一归属，boundary 为真源）**：`list_office/skill_grants_for_dossier`、durable 轨读面（`list_economy_moves/list_fiscal_effects/list_dossier_durable_effects`）、`list_night/list_promulgated_directives` **不入包、留 GameDB**（实读：分别读 office_change_records/skill_grants、economy_ledger/fiscal_config_*、口令账/turn_directives，均非案卷 13 表）；`list_closed_army_pay_dossiers_for_provenance` 体内的补饷流水过滤（经 `list_economy_moves_for_dossier`）上提调用方组合，store 面只出 closed grant_allocation 案卷集 + 纯件过滤。两处裸 SQL 随目标所在片改径：`covert_progress` 实况轨幂等查随 PR-6a（实况轨幂等写内化）、`covert_levy` 的 `faction_denunciations` origin 直读随 PR-9（`list_faction_denunciations` 就位后改道）。
- 规模：~400 行；生产触点 ~68（方法调用 55 + 裸 SQL 12 + 常量直读 1）。`get_decree_dossier` 一家 24 处 / 10 模块（action_materialize、breach_plea、covert_levy、credit_events、due_review、issues、pay_order、population_pressure、simulation、urge_lever）。
- 聚焦测试：57 文件 / 334 函数命中；核心 `test_decree_dossiers_571.py`（72）、`test_promulgation_judge_561.py`（23）、`test_promulgation_seam_560.py`（14）、`test_execution_pressure_654.py`（13）、`test_secret_order_payoff_1504.py`（12）、`test_executor_routing_721.py`（11）、`test_military_order_materialize_521.py`（11）、`test_due_review_621.py`（10）。
- 独立可合论证：片内方法全是叶/近叶（AST 调用图核实：callee 不出 kernel ∪ GameDB-other 夹带，夹带点 §4.2 点名）；它是唯一被所有后续片依赖的片，先行合并后各片不再互相卡序。
- 叶方法提前说明：`merge_execution_note`（callee 仅 `_commit_dossier_write`+`get_decree_dossier`）与 `dossier_authorizes_effects`（零 callee）被连坐毁约/护送对账/执行格三方共用，提前进 kernel 是为消除组级环（§4.1），不提前则 PR-11/PR-10 必须排在 PR-14 后，纵切序退化成单链尾大头。

### PR-3【成案写】

- 内容：`create_decree_dossier`（51）、`create_decree_dossiers`（289）、`_create_decree_dossier_row`（315）、`_validate_dossier_delegations`（11）、`_dossier_has_execution_surface`（6）、`_normalize_dossier_mode`（5）；**段适配器随迁（入段层、不入包）**：`_create_grant_fiscal_item`（28，state 夹带）——`_create_decree_dossier_row` 内 immediate 颁赏物化三枝（`_create_grant_fiscal_item`/`_apply_army_pay_grant_effect`/`record_issue_economy_move`）析出为段侧消费，store create 只落案卷行、效果意图交段（同 breach-liability-split 的判定写/效果消费二分）；`_apply_army_pay_grant_effect`/`_apply_grant_honorific_effect` 双调用方件的归属随 #1572 PR-4 落地形态接线（§4.5）。**改口径**：颁赏纯件 4 个已入 PR-2 kernel；`_find_pacification_target` 不入本片（段适配器，随 PR-4）；`_decode/read_directive_dossier_payload` 留 GameDB（directive 读缝）。
- 规模：~705 行（包内 677 + 段搬迁 28）；生产调用点 3 处（rescript_actions 1；GameDB 内部 `create_secret_order`、`_apply_pending_action` 改道）。
- 聚焦测试：37 文件 / 134 函数命中；核心 `test_decree_dossiers_571.py`、`test_execution_pressure_654.py`、`test_pay_order_override_653.py`、`test_promulgation_seam_560.py`。
- 依赖：PR-2（`_commit_dossier_write`/颁赏纯件/kernel 读面）；须在 #1572 PR-4 之后（§4.5）。
- 不可再拆论证：批量入口 `create_decree_dossiers` → 逐行 `_create_decree_dossier_row` → 校验链 `_validate_dossier_delegations` 是同一写路径的连续调用链，`create_decree_dossier` 只是单卷变体；把「批量」与「写行」切片会使前片留 GameDB 转发壳（create 公开面在 GameDB 只剩半链），违反无壳约束；段侧物化析出后片内已无 cross-concern 赘肉。
- 独立可合论证：callee 闭包 = 片内 + kernel + GameDB-other 夹带（§4.2 点名）；生产 3 调用点同 PR 改径后 GameDB 侧零残留。

### PR-4【directive 准入正规化】

- 内容（判词点名拆出）：`_normalize_directive_dossier_payload`（311）、`_directive_dossier_action_type`（7）、`_directive_executor`（12）、`_ensure_directive_dossier`（46）入包为 store 私有；**段适配器随迁**：`ensure_dossiers_for_draft_directives`（45，旨稿边界成案编排，读 turn_directives 经 GameDB `list_directives`）与 `_find_pacification_target`（27，content 检索 helper，实读只触 characters/powers 表——boundary §2.2 段适配器为真源，不入包；`_normalize_directive_dossier_payload` 体内对其的调用改为调用方预计算注入，消解 content 夹带）。
- 规模：~450 行；生产触点 7（外部 3：rescript_actions 2（`_normalize` 外读改径、`_find_pacification_target` 随段）、session 1（`_find_pacification_target` 随段）；GameDB 内部 4：`_merge_directive_payload`、`_prepare_pending_directive`、`_apply_pending_action`、`confirm_directive` 改道）。`ensure_dossiers_for_draft_directives` 生产零外部调用（27 处测试随片改道）。
- 聚焦测试：12 文件 / 40 函数命中。
- 依赖：PR-2（kernel 写原语/颁赏纯件）、PR-3（`_ensure_directive_dossier` 调 `create_decree_dossiers`）。
- 独立可合论证：片内 4 个 store 私有件 callee 仅 kernel + PR-3 + 段侧预计算注入；两段适配器件出 GameDB 即清零片内方法。

### PR-5【参与人 + 背书 + 关联槽】

- 内容：`append_decree_dossier_participants`（52）、`_validate_dossier_endorsement`（30）、`add_dossier_endorsement`（22）、`list_dossier_endorsements`（12）、`_record_dossier_link_rejection`（10）、`add_dossier_links`（52）、`list_dossier_links`（12）、`list_dossier_link_rejections`（15）、`list_commitments_for_dossier`（7）、`resolve_commitment_origin_ref`（32）。公开面按 boundary §2.1 拆三实名入口：`attach_participants`/`attach_links`/`attach_endorsements`。
- 规模：~245 行；生产调用点 4 处（`decree.py` 2、`issues.py` 2）。
- 聚焦测试：`test_secret_dossier_participants_1252.py`、`test_dossier_endorsements_612.py`、`test_dossier_links_559.py` + 散点，合计 10 文件 / 36 函数命中。
- 依赖：PR-2（`_commit_dossier_write`、query reads）、PR-3（`_validate_dossier_delegations` 与成案共用，随成案先迁）。
- 独立可合论证：三子组 callee 均只落在 kernel/成案/片内；`add_dossier_links`/`add_dossier_endorsement` 生产零外部调用（见 §4.6），改径面极小。

### PR-6a【actual 轨（实况轨）】

- 内容：actual 轨散点 `record_dossier_actual_progress`（51）、`list_dossier_actual_progress`（6）、`sum_dossier_actual_progress_units`（6）；**段适配器拆分搬迁**：`list_dossier_actual_rail`（15）——实况轨行→store `list_progress`，durable 效果行→GameDB 效果读面组合（boundary §2.2）；同 PR 改径裸 SQL `covert_progress` 一处（实况轨同回合幂等查 → `record_progress` 实况轨内部子步骤）。
- 规模：~78 行；生产调用点 = 原 PR-6 的 20 处中归属实况轨者（`covert_progress.py` 4 处 + 散点，随片施工时逐处重核点名）+ 裸 SQL 1。
- 聚焦测试：原 PR-6 聚焦集中命中实况轨三件/rail 的函数（随片施工时逐函数重核点名）。
- 依赖：PR-2（kernel 写原语/读面）。
- 独立可合论证：actual 轨三件与 reported 轨十件写读路径各自闭合、无互相调用边（随片施工时 AST 复核）；`list_dossier_actual_rail` 无生产外部直达，段拆分后 GameDB 侧零残留，无壳/无双实现。

### PR-6b【reported 轨 + 监视 origin 读面】

- 内容：reported 轨 `_normalize_dossier_report_origin`（14）、`_coerce_dossier_progress_row`（17）、`_record_secret_dossier_progress`（41）、`_record_general_dossier_progress`（47）、`record_dossier_progress`（46）、`list_dossier_progress`（30）、`_audit_fork_signals_for_source`（23）、`read_dossier_fork_state`（32）、`list_monthly_dossier_progress_nudges`（29）、`record_monthly_dossier_progress`（44）；**监视 origin 读面随迁**：`list_supervision_presence`（37）、`list_supervision_history`（54）、`compose_supervision_report_origin`（27）——三件均为子模块私有实现件（零生产外部调用，boundary §2.1 私有清单），随迁只为断环，不构成公开面。**改口径**：`dossier_has_beyond_intent` 留 GameDB（实读核：经 `list_dossier_durable_effects` 读 economy/fiscal 表，非案卷 13 表），不入本片；actual 轨与 `covert_progress` 裸 SQL 已随 PR-6a。
- 规模：~440 行；生产调用点 = 原 PR-6 的 20 处剔除实况轨后归属 reported 轨者（随片施工时逐处重核点名）。
- 聚焦测试：原 PR-6 口径（15 文件 / 55 函数命中）剔除实况轨命中后随片重核；核心 `test_secret_order_monthly_progress_566.py`、`test_secret_order_payoff_1504.py`、`test_army_pay_decree_1503.py`、`test_dossier_reported_progress_619.py`、`test_deformation_dual_rail_622.py`。
- 依赖：PR-2（`get_decree_dossier`）、PR-5（`list_dossier_links`——`_audit_fork_signals_for_source` 用）。
- origin 读面随迁说明：`record_monthly_dossier_progress` 调 `compose_supervision_report_origin`（双轨→监视边），而 `accept_faction_denunciations`/`build_faction_denunciation_facts` 调 `read_dossier_fork_state`（监视→双轨边）——组级环。`compose_supervision_report_origin`+`list_supervision_history` 是纯读面（callee 仅 kernel+`list_supervision_presence`），随本片先行即断环；写侧 facts 留 PR-7、反制/检举分留 PR-8/PR-9。不如此则双轨与监视检举只能并片，违背纵切初衷。
- 不可再拆说明（~440 行）：reported 轨与 origin 读面同处上揭组级环，再拆则环复闭或留 GameDB→store 私有 seam；~440 行为 owner 裁定拆法（actual 轨 / reported+origin 二分，decision key `issue1571-source-revision-owner-ruling-A`）下的最小合法单元。
- 独立可合论证：断环后 callee 闭包 = 片内 + kernel + PR-5；生产改径面同 PR 完成。

### PR-7【监视 facts（presence/exposures 事实记录）】

- 内容（判词点名自旧「监视检举」片拆出）：`dossier_has_supervision_presence`（12）、`record_monthly_supervision_presence`（62）、`record_monthly_loophole_exposures_from_reconciliations`（35）、`record_monthly_supervision_facts`（18）、`record_loophole_exposure`（36）、`list_loophole_exposures`（33）、`build_supervision_judge_surface`（21）；其中 `dossier_has_supervision_presence`/`record_monthly_supervision_facts`/`record_loophole_exposure`/`list_loophole_exposures` 为子模块私有实现件（零生产外部调用，grep 实核，boundary §2.1 私有清单），公开入口仅 `record_monthly_supervision_presence`/`record_monthly_loophole_exposures_from_reconciliations`/`build_supervision_judge_surface` 3 个；同 PR 收编 `supervision.py` 的表名/列白名单常量段入包（`EXECUTION_FORMS` 平行闭集已于 PR-2 消亡）。
- 规模：~217 行（db.py 侧）+ `supervision.py` 常量收编；生产调用点 5 处（decree 3、due_review 1、simulation 1）。
- 聚焦测试：2 文件 / 10 函数命中（`test_supervision_625.py` 为主）。
- 依赖：PR-2（kernel 写原语）、PR-6b（`build_supervision_judge_surface` 体内调 `list_supervision_history`）。
- 独立可合论证：callee = 片内 + kernel + PR-6b 读面（AST 实核）；`supervision.py` 的 LLM surface 组词逻辑留原地（判官生产侧类比，ADR 决定 3），只收编其 schema 知识常量。

### PR-8【反制候选纯读 + decree 编排消费（countermeasure）】

- 内容（五审自旧「检举与对策」片拆出——两片无互相调用边、判词认定可独立纵切）：`trigger_supervision_countermeasures`（78）**拆分**：纯读半（presence 全库聚合 + 连续月判定，仅读 13 表内 `dossier_supervision_presence`）→ supervision 公开新件 `list_supervision_countermeasure_candidates`（boundary §2.1 #25；纯参数、零 commit）；**store 返候选行（auditor/dossier_id/连续月数），段侧消费**——integrity 过滤（`character_faction_integrity` 读 characters/factions=GameDB-other 夹带）、issue 查重 `find_any_issue_by_origin`、创建 `insert_issue`、commit 全部归编排层（decree.py 结算段现传 commit=False，事务内逐候选消费，同 PR-12 `trigger_commitment_backlashes` 编排半口径）；supervision.py 候选判定纯件收编入包：`derive_consecutive_months`（23）+`COUNTERMEASURE_PRESENCE_MONTHS`（皆纯参数零 db，共 ~25 行）；`character_faction_integrity`（吃 db handle）与段侧自用的 `COUNTERMEASURE_ORIGIN_KIND`/`countermeasure_origin_ref`/`pick_countermeasure_kind`/`is_upright_integrity` 留 supervision.py 原地。
- 规模：触及 ~78 行（方法体拆分出块）+ 新写 ~90 行（纯读件 ~25 + 纯件收编 ~25 + 段侧编排半 ~40 落 decree.py 结算段）；生产调用点 1 处（decree.py 结算段）。
- 聚焦测试：2 文件 / 2 函数命中（AST 逐函数实核）：`test_supervision_625.py::test_ac2_paired_observation_slots_and_countermeasure_hard_gate`、`test_commitment_backlash_626.py::test_ac5_hook_idempotent_no_gate_table_expansion`。
- 依赖：PR-1a（`dossier_supervision_presence` 表随 schema 片就位）——片内自含（自有聚合 SQL + 收编纯件），不依赖 PR-6b；与 PR-9 无互相调用边（AST 实核：trigger 体内 self 调用仅 GameDB-other 的 `find_any_issue_by_origin`/`insert_issue`，检举三件体内无 trigger 调用），两片先后可换；序号取两方法在 db.py 中的先后自然序，非拓扑强制。
- 独立可合论证：包内 callee = 片内收编纯件（零 kernel 写原语需求——纯读件无写路径）；GameDB-other 依赖（`character_faction_integrity`/`find_any_issue_by_origin`/`insert_issue`/characters-factions 读）全部留编排层点名，包内零反向调用；decree.py 结算段单调用点同 PR 改径后 GameDB 侧零残留；与 PR-7 不触同函数（PR-7 收表名/列白名单常量段、本片收反制判定纯件）。

### PR-9【检举读/事实/承接（denunciation）】

- 内容（五审自旧「检举与对策」片拆出）：`list_faction_denunciations`（48）原样随迁（公开读端）；`build_faction_denunciation_facts`（178）原样随迁——跨表读派系/处境（`faction_leverage`/`faction_satisfaction`）为 GameDB-other 夹带，§4.2 注入/预计算；`accept_faction_denunciations`（155）**改造保留公开**：state 入参消解为 `turn:int` 纯标量（实读仅取 `state.turn`）；clamp 夹带上提段侧预解析注入纯参数——检举人在场/faction（characters 表裸读）与被检举人派系（`character_faction_integrity`）皆 GameDB-other；commit 移除、由段侧统一提交（decree.py 现传 commit=False）；实写仅 `faction_denunciations` INSERT（13 表内），读侧 `get_decree_dossier`/`read_dossier_fork_state`/去重 SELECT 皆 13 表内；supervision.py 检举判定纯件收编入包：`DENUNCIATION_ORIGIN_BASE`+`derive_denunciation_is_true`+`compose_denunciation_origin`+`denunciation_case_upgraded`（皆纯参数零 db，共 ~47 行）；`faction_denunciations` 表已随 PR-1a；同 PR 改径裸 SQL `covert_levy` 的 `faction_denunciations` origin 直读（→ `list_faction_denunciations`）。
- 规模：~381 行（db.py 三方法体，HEAD 实核 48+178+155）+ 新写 ~50 行（纯件收编 ~47 + accept 段侧预解析）；生产调用点 4 处（HEAD 实核：decree/issues/simulation 各 1 + 裸 SQL 1）。
- 聚焦测试：2 文件 / 8 函数命中（AST 逐函数实核）：`test_faction_denunciation_627.py` 7 函数、`test_impeachment_surge_655.py::test_transformed_fact_is_projected_as_namespaced_candidate`。
- 依赖：PR-2（kernel 写原语——`faction_denunciations` INSERT 收编 kernel 写路径）、PR-6b（`read_dossier_fork_state`——`build_faction_denunciation_facts` 与 `accept_faction_denunciations` 体内调用，AST 实核）；与 PR-8 无互相调用边（见 PR-8 依赖行），先后可换。
- 独立可合论证：改造后包内 callee = 片内 + kernel + PR-6b 读面 + 收编纯件；GameDB-other 依赖（`faction_leverage`/`faction_satisfaction`/`character_faction_integrity`/characters clamp）全部注入/预计算，包内零反向调用；与 PR-7 不触同函数（PR-7 收表名/列白名单常量段、本片收检举判定纯件）。

### PR-10【护送对账子模块】

- 内容：`_grant_escort_presence`（9）、`list_monthly_grant_reconciliation_targets`（42）、`list_dossier_reconciliations`（29）、`list_open_grant_reconciliations`（22）、`record_monthly_grant_reconciliations`（95）、`merge_grant_reconciliation_into_execution_note`（13）。公开面 4 个（`list_monthly_grant_reconciliation_targets`、`_grant_escort_presence` 子模块私有——前者零生产外部调用、仅包内 `list_open_grant_reconciliations`/`record_monthly_grant_reconciliations` 用，boundary §2.1 私有清单），公开入口见 boundary §2.1 #29-32。
- 规模：~210 行；生产调用点 5 处（`decree.py` 1、`simulation.py` 1、`issues.py` 3）。
- 聚焦测试：2 文件 / 7 函数命中：`test_grant_reconciliation_567.py`、`test_army_pay_decree_1503.py`。
- 依赖：PR-2（`merge_execution_note` 叶与颁赏纯件 `_grant_allocation_is_monthly/honorific` 均已进 kernel）、PR-5（`list_dossier_links`——`_grant_escort_presence` 用）。
- 独立可合论证：全片 callee 均在 kernel/关联槽/片内；0058 语义自含，是全票最小的写侧片，适合作为包内子模块形态的示范片。

### PR-11【连坐毁约判定写（override/breach/joint-liability 纯判定写拆分）】

- 内容（形状真源 = breach-liability-split §2；九审自旧片拆出 backlash 组为 PR-12——两组无互相调用边，AST 实核见下）：常量组 `_OVERRIDE_AUTHORITY_COST`/`_REACTION_INTENSITY`/`_REACTION_SIGN`/`_BREACH_FACTION_REACTION`/`_JOINT_LIABILITY_COST_IDENTITY`/`_EXECUTION_OUTCOME_INTENSITY`/`_JOINT_LIABILITY_TRIGGERS`/`_INTENSITY_DOWNGRADE`（~12 行，迁后去下划线公开化）、`_record_decree_cost`（12）、`_current_judge_affected_parties`（24）、`list_execution_liability_parties`（8）、`validate_joint_liability_affected_parties`（29）原样随迁；**三个混合旧动词拆分**：`_apply_authority_cost`（17）+`_apply_override_costs`（38）判定半 → store 公开 `record_override_judgment`、效果半（metrics/adjust_factions/adjust_classes）→ 段 `apply_override_effects`；`breach_decree_dossier`（83）→ `record_breach_judgment` + 段 `apply_breach_effects`；`apply_execution_joint_liability`（93）→ `record_joint_liability` + 段 `apply_joint_liability_effects`；旧名整体消亡、不留转发（ADR 0151 决定 6）；issues/due_review 两处私有常量直读改公开常量。
- 规模：~316 行（8 方法体 AST 跨度合计 304 + 常量组 ~12）+ `record_*_judgment` 三动词与段侧 `apply_*_effects` 新写；生产调用点 7 处，集中在 breach_plea/issues/due_review（逐处清单施工时 grep 现查）+ 常量直读 2。
- 聚焦测试：3 文件 / 9 函数命中（AST 逐函数实核）：`test_override_breach_costs_564.py` 5、`test_execution_joint_liability_565.py` 3、`test_breach_plea_623.py` 1。
- 依赖：PR-2（`dossier_authorizes_effects`/`merge_execution_note` 叶 + kernel 读面/写原语——`list_commitments_for_dossier` 为 backlash 组 callee，本片不需要，PR-5 依赖随 PR-12）。**须在 PR-14 前**：`apply_dossier_promulgation` 调 `_apply_override_costs`（两处内联点）；反向边（`breach_decree_dossier`→`dossier_authorizes_effects`、`apply_execution_joint_liability`→`merge_execution_note`）已被 kernel 提前吸收，环断。
- 独立可合论证：断环后 callee 闭包 = 片内 + kernel + GameDB-other 夹带（§4.2）；判定写先于段效果消费、同事务的原子顺序不变式见 breach-liability-split §3。与 PR-12 零互相调用边（AST 实核：liability 组 self-calls 仅 cost/judge/get/adjust/relation/note 组——`_record_decree_cost`/`_current_judge_affected_parties`/`get_decree_dossier`/`adjust_factions`/`adjust_classes`/`record_relation_edge_event`/`merge_execution_note`/`dossier_authorizes_effects`，无一指 backlash 组），生产入口（breach_plea/issues/due_review + 常量直读）与 decree.py 结算段分离，两片先后可换。

### PR-12【commitment backlash（store 纯读组合 + 编排层消费）】

- 内容（九审自旧「连坐毁约判定写」片拆出；拆分形状真源 = breach-liability-split §2.1）：`trigger_commitment_backlashes`（177）**拆分**：纯读半（终值扫描 + `list_commitments_for_dossier`）→ store 公开 `list_backlash_terminal_dossiers`（boundary §2.1 #14；仅限 13 表内读）；`dossier_has_beyond_intent` 实读 economy/fiscal 表、留 GameDB，beyond_intent 过滤由编排层组合；metrics/issue 创建半（经 `insert_issue`/`advance_issue`/`_apply_metric_dict`/`list_next_audience_todos`/`find_any_issue_by_origin`——GameDB-other 夹带）→ 编排层，decree.py 结算段逐候选消费（现传 commit=False，同 PR-8 反制编排半口径）。
- 规模：触及 ~177 行（方法体拆分出块）+ 新写 ~60 行（store 纯读组合件 ~20 + 编排层消费半 ~40 落 decree.py 结算段）；生产调用点 1 处（decree.py 结算段）。
- 聚焦测试：2 文件 / 16 函数命中（AST 逐函数实核）：`test_commitment_backlash_626.py` 14、`test_fiscal_beyond_intent_1260.py` 2；其中 `test_ac5_hook_idempotent_no_gate_table_expansion` 同中 PR-8 反制组（跨组重复计数，§4.4）。
- 依赖：PR-2（kernel 读面）、PR-5（`list_commitments_for_dossier`——纯读半体内调用，AST 实核）；与 PR-11 零互相调用边（AST 实核：backlash self-calls 仅 todo/commitment/beyond-intent/issue 组——`list_next_audience_todos`/`list_commitments_for_dossier`/`dossier_has_beyond_intent`/`find_any_issue_by_origin`/`insert_issue`/`advance_issue`，无一指 liability 组），生产入口仅 decree.py 结算段，与 PR-11 先后可换。
- 独立可合论证：store 纯读件 callee = kernel + PR-5 关联槽读面；GameDB-other 依赖（`dossier_has_beyond_intent`/`insert_issue`/`advance_issue`/`_apply_metric_dict`/`list_next_audience_todos`/`find_any_issue_by_origin`）全部留编排层点名，包内零反向调用；decree.py 结算段单调用点同 PR 改径后 GameDB 侧零残留。

### PR-13【pending verdicts durability】

- 内容（判词点名自旧收敛片拆出）：`save_pending_promulgation_verdicts`（15）、`get_pending_promulgation_verdicts`（20）；待颁布判决两态持久化对，保存点保持自主提交（ADR 0151 决定 7 事务两态唯一例外）。
- 规模：~35 行；生产调用点 2 处（decree.py save/get 各 1）。
- 聚焦测试：5 文件 / 27 函数命中（`test_promulgation_judge_561.py`、`test_promulgation_seam_560.py` 等）。
- 依赖：PR-2（kernel 写原语）。
- 独立可合论证：两态对只触 `pending_promulgation_verdicts` 表（PR-1a 已就位），callee 仅 kernel；是全票最小片，先行合并不影响核心状态机迁移形态。

### PR-14【核心状态机 + record_verdict 收编】（收敛片）

- 内容：状态机常量 `_DOSSIER_STATUSES`/`_DOSSIER_ACTION_TYPES`/`_DOSSIER_TRANSITIONS`/`_PROMULGATION_BLOCKED_LAYERS`/`_DOSSIER_EXECUTION_OUTCOMES`（15）、`transition_decree_dossier`（27）、`record_dossier_decision`（92）、`close_decree_dossier`（21）、`record_dossier_execution`（52）、`apply_dossier_promulgation`（370）、`_append_midzhi_stigma`（31）、`interrupt_dossiers_for_character`（38）；**record_verdict 新写**：判官管线六步中「校验→拒收归因→持久化→verdict 合并」收编为 store 深入口（ADR 0151 决定 4），`record_dossier_decision`（生产外部 0 调用、59 测试函数）与 `transition_decree_dossier`（**生产外部 0 调用；GameDB 密令区内部 2 处在用**：`close_secret_order`、`mark_secret_order_in_progress` 体内各 1——随 `record_execution`/`close` 改道，**内化非删除**；12 测试函数改道）内化为私有子步骤；pending verdicts 两态已随 PR-13。
- 规模：~645 行 + record_verdict 新写；生产调用点 ~9 处（`decree.py` 2、`due_review.py` 1、`breach_plea.py` 2、`issues.py` 1、GameDB 内部 3：`set_character_status`→`interrupt_dossiers_for_character`——唯一块外留存调用方，改径后 GameDB 人物终态流仍可调 store；密令区 `close_secret_order`/`mark_secret_order_in_progress` 改道）+ **段侧物化件改径 10 处**（AST 实核：`_apply_referral_verdict_effect` 直调 `transition_decree_dossier` 与 `record_dossier_execution` 各 4、`_apply_assignment_verdict_effect` 直调 2——#1572 PR-4 上浮后这些调用点居段层，本片同 PR 改道 store 公开入口）。
- 聚焦测试：28 文件 / 116 函数命中；核心 `test_decree_dossiers_571.py`、`test_pay_order_override_653.py`、`test_override_breach_costs_564.py`、`test_promulgation_seam_560.py`、`test_promulgation_judge_561.py`。**本片合并后跑全量 `python -m pytest tests/ -q -n auto` 一次绿**（测试政策见 §2 模板）。
- 依赖：PR-2/3/5/6a/6b/7/11/13——`apply_dossier_promulgation` 扇入最大（AST 实核：调颁赏段侧 helper、`record_override_judgment` 前身 `_apply_override_costs`、`record_dossier_decision`/`record_dossier_execution`/`transition_decree_dossier`），`record_dossier_execution` 另调监视 facts（`dossier_has_supervision_presence`/`record_loophole_exposure`）。故本片天然居末。
- 不可再拆证明（pending verdicts 拆出后；逐边，全部经本 HEAD AST 调用图实核）：
  1. `transition_decree_dossier` 归宿 = store 私有（内化 `record_verdict`，ADR 决定 5）。其生产调用方 = `close_decree_dossier`、`interrupt_dossiers_for_character`、`apply_dossier_promulgation`（6 处）、段侧物化件（5 处）、密令区（2 处）。块内三个调用方（close/interrupt/promulgation）若不随片迁移，迁后即成 GameDB→store 私有件的**临时跨包私有 seam**；若先把 transition 公开再收回则是**临时公开 API**——两者皆违法。块外调用方（段侧物化件、密令区）同 PR 改道公开入口即可，不构成卡序。
  2. `record_dossier_decision`、`_append_midzhi_stigma` 归宿 = store 私有，生产唯一调用方均为 `apply_dossier_promulgation`（decision 2 处、stigma 3 处，AST 实核）——同理必须与 promulgation 同片，否则 GameDB→store 私有 seam。
  3. promulgation 不能**先于** transition/decision 迁移：那样 store 侧 promulgation 回调 GameDB 案卷方法 = 反向调用，§2 模板明文禁止。
  4. `record_dossier_execution`（公开入口）也不能拆出先迁：其体内调 `close_decree_dossier`、`close_decree_dossier` 调 transition、`interrupt` 直调 transition——execution 先迁就要求 close/interrupt/transition 已在包内；而 transition 入包又要求 promulgation 同片（据 1）；promulgation 体内调 execution 8 处（AST 实核），若 execution 已迁而 promulgation 未迁虽是合法正向改径，但 transition 的私有化仍把 promulgation 锁进同一片——闭合，全部只能同片。
  5. 唯一可合法拆出的 pending verdicts 两态已拆为 PR-13（只触 `pending_promulgation_verdicts` 自有表，对上述方法零入边）。残片 ~645 行 + record_verdict 新写为最小合法单元；record_verdict 收编对象即 promulgation 骨架，按 §4.5「两片 diff 不得同时触碰同一函数」也不得再分。
- 独立可合论证：本片合并后 GameDB 案卷块方法清零（§3），db.py 剩 ~17,000 行；`apply_dossier_verdicts`（81 行，verdict 物化族）在 #1572 PR-4 已上浮，其剩余编排骨架即 record_verdict 的收编对象，两片接缝在 PR-4 落地形态上对接（§4.5）。

## 3. 依赖序与 fixed point 边界

```
#1572 PR-1（实体目录地基）→ #1572 PR-4（verdict 物化上浮）
        │
PR-1a schema DDL ──→ PR-1b 迁移组自治
   │
   ├──→ PR-8 反制候选纯读+decree 编排消费（仅依 PR-1a 表；与 PR-9 零互相调用边，先后可换）
   │
   └──→ PR-2 读面 kernel ──→ PR-3 成案写 ──→ PR-4 directive 准入
            │                │
            │                └──────→ PR-5 参与人/背书/关联槽
            │                            │
            ├──────────────→ PR-6a actual 轨
            │                            │
            ├──────────────→ PR-6b reported 轨+origin ←┘
            │                    │
            │                    ├──→ PR-7 监视 facts
            │                    └──→ PR-9 检举读/事实/承接
            ├────────→ PR-10 护送对账（另依 PR-5）
            ├────────→ PR-11 连坐毁约判定写
            ├────────→ PR-12 commitment backlash（另依 PR-5；与 PR-11 零互相调用边，先后可换）
            └────────→ PR-13 pending verdicts durability
        PR-3/5/6a/6b/7/11/13 全部 ──→ PR-14 核心状态机+record_verdict（收敛片）
```

**fixed point 结论：每片都是纵切，无需单一大 fixed point PR；但存在天然收敛片 = PR-14。** 论证：

1. 「点」的传统定义（摘完它 GameDB 案卷块清零）由依赖序自动落在 PR-14：`apply_dossier_promulgation` 是块内扇入最大的方法（AST 实核 24 个 dossier-internal callee，含 verdict 物化族 8 个，横跨成案/读面/双轨/监视/连坐五组），它不动，块就不可能清零；它能动的前提是所有被调组已就位（同片强制集逐边证明见 §2 PR-14）。这不是人为指定，是调用关系的拓扑必然。
2. PR-1a 至 PR-13 每片合并后，目标分支上 GameDB 案卷块单调缩小、无转发壳（每片论证见 §2），中间任何一片合并后**该片聚焦测试绿**（全量一次在 PR-14 后，§2 模板）——满足判词「可独立 seam 纵切」的全部要件。
3. 因此不走「PR-0 薄壳 + PR-1 大 fixed point」双段式（#1572 曾因壳态风险把 fixed point 压进单 PR commit 链，见 migration-inventory §7）；本案各片无壳，波次即真相。

各片规模/触点/测试汇总（行数全部按 HEAD e88cc29c AST 重核）：

| 片 | 行数 | 生产触点 | 测试函数命中（文件数） | 硬依赖 |
|---|---:|---:|---:|---|
| PR-1a schema DDL | ~242+包骨架 | 1（init_schema 编排） | PRAGMA/schema 断言直引 | #1572 PR-1 |
| PR-1b 迁移组自治 | ~255 | 0（编排点内部） | 迁移断言直引 | PR-1a |
| PR-2 读面 kernel | ~400 | ~68 | 334（57） | PR-1a |
| PR-3 成案写 | ~705 | 3 | 134（37） | PR-2，#1572 PR-4 |
| PR-4 directive 准入 | ~450 | 7（外部 3 + 内部 4） | 40（12） | PR-2、PR-3 |
| PR-5 参与人/背书/关联槽 | ~245 | 4 | 36（10） | PR-2、PR-3 |
| PR-6a actual 轨 | ~78 | 实况轨部分+裸 SQL 1（随片重核） | 随片重核 | PR-2 |
| PR-6b reported+origin | ~440 | reported 部分（随片重核） | 55（15）剔实况后重核 | PR-2、PR-5 |
| PR-7 监视 facts | ~217 | 5 | 10（2） | PR-2、PR-6b |
| PR-8 反制候选+编排消费 | ~78 触及+新写 ~90（纯读件/收编/段侧编排半） | 1 | 2（2） | PR-1a |
| PR-9 检举读/事实/承接 | ~381+新写 ~50（纯件收编/段侧预解析） | 4 | 8（2） | PR-2、PR-6b |
| PR-10 护送对账 | ~210 | 5 | 7（2） | PR-2、PR-5 |
| PR-11 连坐毁约判定写 | ~316+新写（三判定写动词/段侧效果消费） | 7 | 9（3） | PR-2 |
| PR-12 commitment backlash | ~177 触及+新写 ~60（纯读组合件/编排层消费半） | 1 | 16（2） | PR-2、PR-5 |
| PR-13 pending verdicts | ~35 | 2 | 27（5） | PR-2 |
| PR-14 核心状态机（收敛片） | ~645+新写 | ~19（含段侧物化件改径 10） | 116（28） | PR-2/3/5/6a/6b/7/11/13 |

## 4. 风险点

### 4.1 多子组共用方法与断环处置（卡序点全清单）

以下共用边全部由本 HEAD AST 调用图实核，逐条给出处置：

| 共用件 | 使用方 | 环/序风险 | 处置 |
|---|---|---|---|
| `_dossier_row`、`get_decree_dossier` | 读面/双轨/监视/连坐/状态机/成案各组共 20+ 处 internal 调用 | 一切片的前置 | PR-2 kernel 先行 |
| `_commit_dossier_write` | 成案/双轨/背书/关联槽/参与人/状态机写路径共用 | 同上 | PR-2 kernel 先行 |
| `merge_execution_note`（叶）、`dossier_authorizes_effects`（叶） | 护送对账、连坐毁约 ← → 执行格（PR-14） | 组级环；不断则 PR-10/PR-11 排到 PR-14 后，尾部臃肿 | 两叶提前入 PR-2 kernel（callee 全在 kernel 内，有资格） |
| `compose_supervision_report_origin`+`list_supervision_history` | 双轨 `record_monthly_dossier_progress` 调监视 origin；检举 `accept_faction_denunciations`/`build_faction_denunciation_facts` 调双轨 `read_dossier_fork_state` | 双轨↔监视组级环；不断则双轨与监视/检举各片须并片（~1,200 行） | origin 读面（纯读、callee 仅 kernel）随 PR-6b 先行，facts 留 PR-7、检举留 PR-9 |
| `_validate_dossier_delegations` | 成案 3 处 + `append_decree_dossier_participants` | 成案↔参与人共用 | 随 PR-3 成案先迁，PR-5 排后 |
| 颁赏纯件 4 个（`_grant_allocation_is_monthly/honorific`、`_normalize_army_pay_grant_payload`、`_is_army_pay_grant_payload`） | kernel 读面 + 成案 + directive 准入 + 护送对账四方 | 纯 payload 函数（零 conn/state，实读核）；归段会造包→段反向调用 | 全部入 PR-2 kernel（store 私有，boundary §2.2 已据实读改归）；物化 3 件（`_create_grant_fiscal_item`/`_apply_army_pay_grant_effect`/`_apply_grant_honorific_effect`）仍段适配器，成案内 immediate 物化析出段侧（PR-3） |
| durable 读轨（`list_economy_moves/list_fiscal_effects/list_dossier_durable_effects`） | provenance 读面 + backlash 过滤 + 颁布格 | 实读：读 economy_ledger/fiscal_config_*，非案卷 13 表（AST 实核） | **留 GameDB**（boundary §2.2 为真源，二审统一）；`list_closed_army_pay_dossiers_for_provenance` 的补饷过滤与 `list_dossier_actual_rail` 的 durable 半上提调用方/段组合，不入包 |
| `_apply_override_costs` 代价簇 | 连坐毁约（PR-11）+ `apply_dossier_promulgation`（PR-14） | 单向 | 判定半随 PR-11 先成 `record_override_judgment`，PR-14 内联点改调之，无环 |

### 4.2 夹带点（ADR 0151 决定 9「逐个点名，不静默继承」预清单）

块内 30 个方法签名带 `state`/`content`/`registry`（AST 实核），其中 verdict 物化族 10 个随 #1572 PR-4 处置（`_append_midzhi_stigma` 不属物化族——只写 `decree_dossiers.stigma_json`、纯参数，随 PR-14 入 store 私有）、颁赏效果 2 个（`_apply_army_pay_grant_effect`/`_apply_grant_honorific_effect`）为双调用方件按 §4.5 处置；本票须逐个点名的 17 个：`_normalize_directive_dossier_payload(content)`、`_find_pacification_target(content)`、`trigger_supervision_countermeasures(state)`、`accept_faction_denunciations(state)`、`trigger_commitment_backlashes(state)`、`_create_grant_fiscal_item(state)`、`create_decree_dossier/create_decree_dossiers/_create_decree_dossier_row(state)`、`append_decree_dossier_participants(state)`、`resolve_commitment_origin_ref(state)`、`apply_dossier_promulgation(state,content,registry)`、`_apply_authority_cost/_apply_override_costs(state)`、`breach_decree_dossier(state)`、`apply_execution_joint_liability(state)`、`interrupt_dossiers_for_character(state)`。

GameDB-other 依赖（store 不可反向调用，须注入/预计算/留编排层，逐片 PR 描述点名）：`_normalize_participant_roster`、`_validate_participant_roster_references`、`register_character_knowledge_source`、`_character_knowledge_events`、`record_issue_economy_move`、`create_fiscal_item`、`adjust_factions`、`adjust_classes`、`record_person_log`、`get_character_status`、`set_character_status`（体内一处反向调 interrupt）、`close_secret_order`、`apply_army_deltas`、`_commit_office_action`、`coerce_beyond_intent_flag`、`faction_leverage`/`faction_satisfaction`、`find_any_issue_by_origin`、`insert_issue`、`advance_issue`、`list_next_audience_todos`、`record_relation_edge_event`、`list_directives`。

### 4.3 生产调用模块清单（18 模块 + 2 裸 SQL 模块）

action_materialize、breach_plea、cli/terminal、covert_levy、covert_progress、credit_events、decree、due_review、issues、participant_roster、pay_order、population_pressure、registry、rescript_actions、session、simulation、tools、urge_lever（ADR 称 ~15，本 HEAD 实核 18，差为 ADR 起草后新增触点）；裸 SQL 专项：execution_pressure、supervision（常量/白名单形态）。另有 db.py 内一处块内留存调用方（`set_character_status`→`interrupt_dossiers_for_character`）。

### 4.4 测试文件跨片重叠

`test_decree_dossiers_571.py`（94 函数命中多组）、`test_promulgation_judge_561.py`、`test_execution_pressure_654.py`、`test_override_breach_costs_564.py` 等会被多片重复机械改径。重叠不构成合并障碍（每片只改本片方法的调用点、不弱化行为断言，违宪盯文/盯源码测试处置见 §2 模板），但放大各片 diff 噪音；各片 PR 描述须声明「本 PR 仅改 X 组调用点」，评审按组核对。16 片跨组求和（794——五审 PR-8 拆分实核：旧「检举与对策」片记 11 函数为关键词口径，AST 逐函数直调实为 10 = 反制 2 + 检举 8；九审 PR-11 拆分实核：25 = liability 9 + backlash 16，无同函数双中，求和不变）低于去重口径（~817）：留 GameDB 方法（effects 读面/directive 读缝/night 明发读面等）的测试命中不再计入任何片；求和仍含同函数命中多组的重复计数。权威口径见 test-disposition。

### 4.5 与 #1572 PR-4 的接缝

`apply_dossier_promulgation` 现调 10 个 `_apply_*_verdict_effect`（AST 跨度求和 **634 行**，含军事令二件套/颁赏效果二件；`_append_midzhi_stigma` 31 行不在其列，随 PR-14 入 store 私有）——全部归 0150 PR-4 上浮。`_apply_army_pay_grant_effect`/`_apply_grant_honorific_effect` 为**双调用方**（成案即时效果 + 颁布格 verdict 效果），其最终归属由 #1572 PR-4 落地形态决定，PR-3/PR-14 均须在其后接线，不得抢跑（ADR 0151 决定 1「不同代码不搬两次」）。`apply_dossier_verdicts`（81 行）跨两票：效果族上浮后其剩余骨架（blocked-layer 过滤 + 逐个 verdict 路由）即 record_verdict 收编对象，两片 diff 不得同时触碰该函数。

### 4.6 生产零外部调用方法（窄 interface 私有化候选，随片执行）

ADR 决定 5 已点名 `transition_decree_dossier`/`record_dossier_decision` 内化（本 HEAD 实核：`record_dossier_decision` 生产外部 0 调用、59 测试函数；`transition_decree_dossier` 生产外部 0 调用，但 **GameDB 密令区内部 2 处在用**——`close_secret_order`、`mark_secret_order_in_progress` 体内各 1，随 `record_execution`/`close` 改道，内化非删除；测试 12 函数）。另实核生产零外部调用（仅测试或块内自用）：`ensure_dossiers_for_draft_directives`、`list_night_promulgated_directives`、`list_promulgated_directives`、`list_office_effects_for_dossier`、`list_skill_grants_for_dossier`、`add_dossier_links`、`add_dossier_endorsement`、`close_decree_dossier`、`list_dossiers_for_directive`、`list_dossier_link_rejections`、`list_commitments_for_dossier`、`list_monthly_grant_reconciliation_targets`、`dossier_has_supervision_presence`、`record_monthly_supervision_facts`、`record_loophole_exposure`、`list_supervision_presence`、`list_loophole_exposures`、`list_supervision_history`、`compose_supervision_report_origin`、`list_faction_denunciations`、`list_dossier_actual_progress`、`list_dossier_actual_rail`——随各片私有化进包或留 GameDB（`list_night/list_promulgated_directives`、`list_office/skill_grants_for_dossier` 留 GameDB，§1），测试改道；`interrupt_dossiers_for_character` 唯一生产调用为 `set_character_status` 体内。这批实核支撑决定 5「~75 个现有方法私有化、窄 interface 取向」的可行性；公开面实数 32 个（store 21 + supervision 7 + reconciliation 4，逐项见 boundary §2.1——二审修订：不设「≤15 封顶」硬约束，owner 只批「~15」量级取向；三审修订：8 个零生产外部调用的实现件——supervision 7 个含 `dossier_has_supervision_presence`/`record_monthly_supervision_facts`/`record_loophole_exposure`/三件 origin 读面、reconciliation `list_monthly_grant_reconciliation_targets`——降包内私有，不入 `__init__` 导出表，grep/AST 实核见 boundary §2.1 私有清单；四审修订：supervision 7 组成换一件——`trigger_supervision_countermeasures` 拆分剔出公开面（纯读半析出新入口 `list_supervision_countermeasure_candidates`，integrity 过滤/issue 创建/commit 半归编排层），`accept_faction_denunciations` 改造保留（state→`turn:int`、clamp 段侧预解析、零 commit），实数 32 不变，逐项见 boundary §2.1/§2.2）。

### 4.7 schema 先行片的迁移顺序约束

PR-1b 搬迁迁移组时须保留 init_schema 现行顺序约束（注释明载；DDL 已随 PR-1a 就位）：decisions 列组 → `_migrate_legacy_reaction_severity` → executor/roster 列 → #654 `region_id` 列 → `_ensure_decree_dossier_locality_indexes`（复合索引重建须在列后）→ `_backfill_proposed_appointment_break_ranks` → `_migrate_legacy_secret_order_dossiers` → `_migrate_legacy_pending_review_secret_orders`（#1504：须在案卷补建之后）。**二审统一**：`_migrate_legacy_pending_review_secret_orders`（72 行）归 ensure_schema 迁移组（boundary §1 为真源，不再留 GameDB），随 PR-1b 搬迁且顺序约束不变（仍排最后）；其案卷轨 3 处 self 调用（`get_dossier_for_secret_order`、`sum_dossier_actual_progress_units`、`mark_secret_order_in_progress` 内联 transition）在迁移组内以私有读件/内联写自给（迁移组持有 13 表 schema 权威），不反向调 GameDB 公开面。

## 5. 复核指引

- 方法行数/跨度：`python3 -c "import ast; ..."` 对 `ming_sim/db.py` GameDB 类取 `lineno/end_lineno`（本文全部函数行数由此出）；块区间边界可用 `sed -n` 抽查。
- 生产调用方复算：对任一方法名 `grep -rn "<method>" ming_sim/ --include=*.py | grep -v db.py`；裸 SQL 复算：在 §1 点名的 7 个模块内 grep 案卷表名逐处核。
- 夹带点复算：AST 取各函数 `args`，筛 `state/content/registry`（§4.2 清单由此出）。
- 测试命中复算：按组方法名正则对 tests/ 逐 `def test_` 切块计数。
- 每片合并后壳检查：`grep -n "def <片内方法>" ming_sim/db.py` 应 0 命中；`grep -rn "GameDB\.<片内私有常量>" ming_sim/` 应 0 命中。

---
记录 HEAD：`e88cc29c28a91c28129b320588934aa12768792b`（2026-08-27 实读）。
